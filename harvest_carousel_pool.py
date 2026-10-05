#!/usr/bin/env python3
"""
Пул картинок для слайда карусели с Pinterest: поиск по запросам →
(слайд 1) похожесть на реф-картинку + «похожие пины» лучших находок →
фильтры (ИИ-метка Pinterest, UGC «живое фото», надписи на картинке,
размер/формат, повторы одного фото) → лучшие кадры 1080×1440 (3:4).

  python harvest_carousel_pool.py --profile tired_s1 --out output/tired_pool/s1 --target 120
  python harvest_carousel_pool.py --profile tired_s2 --out output/tired_pool/s2 --target 80

Выход: <out>/NNN_<pin>.jpg + manifest.json + _sheet.jpg (ручной отбор: лишнее
просто удалить из папки — сборщик каруселей берёт то, что осталось).
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
OUT_W, OUT_H = 1080, 1440

# Профили слайдов. ref — реф-картинки (похожесть по SigLIP), anchors —
# описание сцены словами, related_rounds — сколько раз расширять пул
# «похожими пинами» лучших находок.
PROFILES: dict[str, dict] = {
    # Реф: @lovesickmia, кадр 1 — девушка лежит в кровати, рука у щеки,
    # смотрит в камеру, мягкий свет, светлое бельё
    "tired_s1": {
        "ref": [ROOT / "output" / "carousel_refs" / "lovesickmia_1.jpg"],
        "anchors": [
            "a young woman lying in bed with her hand on her cheek looking at the camera",
            "a sleepy girl resting her head on a pillow in a cozy bedroom",
            "a tired woman lying in bed under a blanket, soft light",
        ],
        # «girl» вместе с «bed» / «selfie» Pinterest без входа отдаёт пусто —
        # только woman / без подлежащего
        "queries": [
            "woman lying in bed selfie",
            "woman in bed aesthetic",
            "lazy morning in bed",
            "cozy bed aesthetic woman",
            "woman resting head on pillow",
            "bed selfie aesthetic",
            "sleepy selfie",
            "morning bed selfie",
            "woman under blanket cozy",
            "tired woman",
            "woman lying on pillow hand on cheek",
            "lying in bed looking at camera",
            "morning in bed aesthetic",
            "bed rot aesthetic",
            "sick day in bed aesthetic",
            "tired woman blanket couch",
            "woman lying on couch blanket",
            "sunday in bed aesthetic",
            "brunette woman bed selfie",
            "blonde woman lying in bed",
            "messy hair morning selfie",
            "cozy autumn morning bed woman",
            "white sheets selfie aesthetic",
            "pillow selfie aesthetic",
        ],
        "related_rounds": 2,
        "related_seeds": 14,
        "weights": {"ref": 0.55, "text": 0.15, "ugc": 0.30},
        "min_ref": 0.55,
    },
    # Жизнь героини: ресторан / кафе / её дом (несмысловой, можно повторять
    # между каруселями, но не внутри одной)
    "tired_s2": {
        "ref": [],
        "anchors": [
            "a candid photo of a cozy restaurant dinner table with candles",
            "a candid photo of a cafe table with coffee and dessert",
            "a cozy apartment living room in the evening",
            "a cozy kitchen at home with warm light",
            "a girl's cozy bedroom with fairy lights",
        ],
        "queries": [
            "dinner date restaurant aesthetic",
            "restaurant table candles aesthetic",
            "cozy restaurant night aesthetic",
            "cafe table coffee dessert aesthetic",
            "fall cafe aesthetic",
            "wine dinner table candid",
            "pasta dinner restaurant aesthetic",
            "cozy apartment aesthetic evening",
            "cozy living room fall aesthetic",
            "cozy kitchen aesthetic warm light",
            "cozy bedroom fairy lights",
            "home aesthetic autumn",
            "woman dinner restaurant candid",
            "brunch table aesthetic",
            "city bistro night aesthetic",
            "cozy home night candles",
        ],
        "related_rounds": 1,
        "related_seeds": 10,
        "weights": {"ref": 0.0, "text": 0.55, "ugc": 0.45},
        "min_ref": 0.0,
        "no_faces": True,  # чужое лицо на 2-м слайде ломает историю героини
        "ugc_floor": 0.35,  # сцены без людей UGC-модель недооценивает
    },
    # Второй проход для слайда 2: дом и кофе без людей
    "tired_s2_home": {
        "ref": [],
        "anchors": [
            "a cozy apartment interior in the evening with warm lamps",
            "a cup of coffee on a table at home, candid",
            "a cozy bedroom with a made bed and soft light",
            "breakfast on a table at home, candid photo",
            "a cozy kitchen at home with warm light",
        ],
        "queries": [
            "coffee at home aesthetic",
            "morning coffee table aesthetic",
            "cozy apartment aesthetic",
            "cozy bedroom aesthetic evening",
            "breakfast at home aesthetic",
            "latte cafe table aesthetic",
            "cozy kitchen evening aesthetic",
            "home aesthetic warm lamp",
            "living room evening lamp aesthetic",
            "coffee cup window aesthetic",
            "iced coffee aesthetic",
            "cozy fall apartment",
            "fall home decor cozy",
            "cafe window seat aesthetic",
            "tea and candles at home",
            "cozy night in aesthetic",
        ],
        "related_rounds": 1,
        "related_seeds": 10,
        "weights": {"ref": 0.0, "text": 0.6, "ugc": 0.4},
        "min_ref": 0.0,
        "no_faces": True,
        "ugc_floor": 0.35,
    },
}

UGC_FLOOR = 0.45          # ниже — сток / глянец
MIN_SHORT_SIDE = 600      # px у оригинала
MIN_ASPECT = 1.1          # h / w — нужна вертикаль (3:4 после кропа)
DUP_HAMMING = 10          # dHash: то же фото (репин)
DUP_COSINE = 0.95         # SigLIP: то же фото в другом кадрировании
OCR_MAX_CHARS = 6         # надпись длиннее — картинка с текстом, не берём
FACE_MIN_FRAC = 0.07      # лицо шире 7% кадра — «в кадре человек»


@dataclass
class Cand:
    pin_id: str
    title: str
    url: str
    orig_url: str
    found_by: str
    image: Image.Image | None = None
    vec: np.ndarray | None = None
    ref: float = 0.0
    text: float = 0.0
    ugc: float = 0.0
    score: float = 0.0
    fp: int = 0
    reasons: list[str] = field(default_factory=list)


def url_736(url: str) -> str:
    return re.sub(r"/(?:\d+x|originals)/", "/736x/", url, count=1)


def dhash(im: Image.Image) -> int:
    g = np.asarray(im.convert("L").resize((9, 8)), dtype=np.int16)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def fetch(cli: httpx.Client, url: str) -> Image.Image | None:
    try:
        r = cli.get(url)
        if r.status_code != 200:
            return None
        return ImageOps.exif_transpose(Image.open(io.BytesIO(r.content))).convert("RGB")
    except Exception:
        return None


class Pool:
    def __init__(self, profile: dict) -> None:
        sys.path.insert(0, str(ROOT))
        from core.harvester import PinterestHarvester
        from core.taste_embedder import get_embedder
        from core.ugc_filter import get_ugc_filter

        self.p = profile
        self.h = PinterestHarvester()
        self.h.warm_session(force=False)
        self.emb = get_embedder()
        self.emb.ensure()
        self.ugc = get_ugc_filter()
        self.cli = httpx.Client(
            timeout=25, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com/"},
        )
        self.cands: dict[str, Cand] = {}
        self.seen_related: set[str] = set()
        refs = [Image.open(r).convert("RGB") for r in profile["ref"]]
        self.ref_vecs = self.emb.embed_images(refs) if refs else None
        self.anchor_vecs = self.emb.embed_texts(list(profile["anchors"]))
        self._ocr = None
        self._faces = None

    # --- сбор -----------------------------------------------------------
    def add_metas(self, metas, found_by: str) -> int:
        n = 0
        for m in metas:
            if m.pin_id in self.cands or m.is_ai is True:
                continue
            self.cands[m.pin_id] = Cand(m.pin_id, m.title, m.image_url, m.orig_url, found_by)
            n += 1
        return n

    def search_all(self) -> None:
        for q in self.p["queries"]:
            pins = self.h.search(q, finalize=False)
            print(f"[search] {q!r}: {len(pins)} пинов, новых {self.add_metas(pins, q)}", flush=True)

    def download_new(self) -> None:
        todo = [c for c in self.cands.values() if c.image is None and not c.reasons]
        with ThreadPoolExecutor(8) as ex:
            ims = list(ex.map(lambda c: fetch(self.cli, url_736(c.url)), todo))
        for c, im in zip(todo, ims):
            if im is None:
                c.reasons.append("download")
            elif im.height / im.width < MIN_ASPECT:
                c.reasons.append("landscape")
            else:
                c.image = im
        print(f"[download] {len(todo)} → ок {sum(im is not None for im in ims)}", flush=True)

    def score_new(self) -> None:
        todo = [c for c in self.cands.values() if c.image is not None and c.vec is None]
        if not todo:
            return
        vecs = self.emb.embed_images([c.image for c in todo])
        ugc = self.ugc.get_ugc_scores([c.image for c in todo])
        text = self.emb._cosine_to_prob(vecs @ self.anchor_vecs.T).max(axis=1)
        ref = (vecs @ self.ref_vecs.T).max(axis=1) if self.ref_vecs is not None else np.zeros(len(todo))
        w = self.p["weights"]
        for c, v, u, t, r in zip(todo, vecs, ugc, text, ref):
            c.vec, c.ugc, c.text, c.ref = v, float(u), float(t), float(r)
            c.fp = dhash(c.image)
            c.score = w["ref"] * c.ref + w["text"] * c.text + w["ugc"] * c.ugc
            if c.ugc < self.p.get("ugc_floor", UGC_FLOOR):
                c.reasons.append(f"ugc {c.ugc:.2f}")
            if self.p["min_ref"] and c.ref < self.p["min_ref"]:
                c.reasons.append(f"ref {c.ref:.2f}")

    def live(self) -> list[Cand]:
        return sorted(
            (c for c in self.cands.values() if c.vec is not None and not c.reasons),
            key=lambda c: -c.score,
        )

    def expand_related(self) -> None:
        for rnd in range(self.p["related_rounds"]):
            seeds = [c for c in self.live() if c.pin_id not in self.seen_related][: self.p["related_seeds"]]
            added = 0
            for c in seeds:
                self.seen_related.add(c.pin_id)
                metas = self.h.fetch_related_metas(c.pin_id, limit=24, exclude_ids=set(self.cands))
                added += self.add_metas(metas, f"related:{c.pin_id}")
            print(f"[related] раунд {rnd + 1}: от {len(seeds)} лучших +{added} пинов", flush=True)
            self.download_new()
            self.score_new()

    # --- отбор ----------------------------------------------------------
    def has_text(self, im: Image.Image) -> bool:
        if self._ocr is None:
            import easyocr

            self._ocr = easyocr.Reader(["en"], gpu=True, verbose=False)
        small = im.copy()
        small.thumbnail((640, 640))
        res = self._ocr.readtext(np.asarray(small), detail=1)
        chars = sum(len(t.strip()) for _b, t, conf in res if conf >= 0.45)
        return chars > OCR_MAX_CHARS

    def has_face(self, im: Image.Image) -> bool:
        import cv2

        if self._faces is None:
            self._faces = [
                cv2.CascadeClassifier(cv2.data.haarcascades + name)
                for name in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml")
            ]
        small = im.copy()
        small.thumbnail((480, 480))
        g = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2GRAY)
        min_px = max(24, int(small.width * FACE_MIN_FRAC))
        return any(
            len(c.detectMultiScale(g, 1.1, 6, minSize=(min_px, min_px))) for c in self._faces
        )

    def select(self, target: int) -> list[Cand]:
        picked: list[Cand] = []
        for c in self.live():
            if len(picked) >= target:
                break
            if any(bin(c.fp ^ p.fp).count("1") <= DUP_HAMMING for p in picked):
                c.reasons.append("dup-fp")
                continue
            if any(float(c.vec @ p.vec) >= DUP_COSINE for p in picked):
                c.reasons.append("dup-cos")
                continue
            if self.p.get("no_faces") and self.has_face(c.image):
                c.reasons.append("face")
                continue
            if self.has_text(c.image):
                c.reasons.append("text")
                continue
            picked.append(c)
        return picked

    def save(self, picked: list[Cand], out: Path) -> None:
        out.mkdir(parents=True, exist_ok=True)
        rows = []
        for i, c in enumerate(picked, 1):
            full = fetch(self.cli, c.orig_url) or c.image
            if min(full.size) < MIN_SHORT_SIDE:
                full = c.image if min(c.image.size) >= min(full.size) else full
            img = ImageOps.fit(full, (OUT_W, OUT_H), Image.Resampling.LANCZOS, centering=(0.5, 0.42))
            name = f"{i:03d}_{c.pin_id}.jpg"
            img.save(out / name, quality=93)
            rows.append({
                "file": name, "pin_id": c.pin_id, "title": c.title,
                "pin_url": f"https://www.pinterest.com/pin/{c.pin_id}/",
                "found_by": c.found_by, "score": round(c.score, 3),
                "ref": round(c.ref, 3), "text": round(c.text, 3), "ugc": round(c.ugc, 3),
                "source_px": list(full.size),
            })
        (out / "manifest.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        sheet(out, rows)


def sheet(out: Path, rows: list[dict]) -> None:
    tw, th, cols = 180, 240, 10
    n = len(rows)
    s = Image.new("RGB", (cols * tw, ((n + cols - 1) // cols) * (th + 18)), (25, 25, 25))
    d = ImageDraw.Draw(s)
    font = ImageFont.truetype("arial.ttf", 13)
    for i, r in enumerate(rows):
        x, y = (i % cols) * tw, (i // cols) * (th + 18)
        s.paste(Image.open(out / r["file"]).resize((tw, th)), (x, y + 18))
        d.text((x + 2, y + 2), f"{r['file'][:3]} s{r['score']:.2f} u{r['ugc']:.2f}", fill=(255, 230, 80), font=font)
    s.save(out / "_sheet.jpg", quality=85)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=sorted(PROFILES), required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--target", type=int, default=100)
    ap.add_argument("--ref-dir", type=Path, help="рефы = все jpg папки (напр. уже отобранные)")
    ap.add_argument("--exclude-dir", type=Path, action="append", default=[],
                    help="пины из этих папок (вкл. _rejected) не брать")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    t0 = time.perf_counter()
    profile = dict(PROFILES[args.profile])
    if args.ref_dir:
        profile["ref"] = sorted(f for f in args.ref_dir.glob("*.jpg") if not f.name.startswith("_"))
    pool = Pool(profile)
    seen = {f.stem.rsplit("_", 1)[-1] for d in args.exclude_dir for f in d.rglob("*.jpg")}
    if args.ref_dir:
        # «похожие пины» сразу от отобранных вручную
        for pid in sorted({f.stem.rsplit("_", 1)[-1] for f in profile["ref"]}):
            pool.seen_related.add(pid)
            pool.add_metas(pool.h.fetch_related_metas(pid, limit=24, exclude_ids=seen), f"related:{pid}")
    for pid in seen:
        pool.cands.pop(pid, None)
    pool.add_metas = (lambda orig: (lambda metas, by: orig([m for m in metas if m.pin_id not in seen], by)))(pool.add_metas)
    pool.search_all()
    pool.download_new()
    pool.score_new()
    pool.expand_related()
    picked = pool.select(args.target)
    pool.save(picked, args.out)

    why: dict[str, int] = {}
    for c in pool.cands.values():
        for r in c.reasons:
            k = r.split()[0]
            why[k] = why.get(k, 0) + 1
    print(f"кандидатов {len(pool.cands)} · отсеяно {why} · отобрано {len(picked)}")
    print(f"готово за {time.perf_counter() - t0:.0f} с → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
