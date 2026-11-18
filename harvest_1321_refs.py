#!/usr/bin/env python3
"""
1321 v2 — образы «Husband #1 / #4 / #7» с Pinterest: раскладки на кровати без человека (база для Flow, один вайб):
harvest_carousel_pool.Pool + лайки и перепины.
Поиск листается на несколько страниц; у каждого пина берём реакции (лайки), подписчиков автора и дату, а одинаковые
фото (image_signature) склеиваем — сколько раз фото перепинили = «перепины». Сохранений Pinterest без входа не отдаёт.
Скор = релевантность сцене (SigLIP) + «живое фото» (UGC) + популярность; дальше отбор глазами по листам.
Фото, уже взятые в 1321 (output/1321_pool/*/_full, output/1321_pick), не берём.

  python harvest_1321_refs.py --slot s3 --target 110     # → output/1321v2_pool/<slot>/ + manifest.json + _sheet_*.jpg
  python harvest_1321_refs.py --slot bed --target 60
  python harvest_1321_refs.py --slot look --target 160   # v3: без эпох, популярность + эстетика
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import harvest_carousel_pool as HP  # noqa: E402
from core import harvester as hv  # noqa: E402

OUT = ROOT / "output" / "1321v2_pool"
USED = [ROOT / "output" / "1321_pool", ROOT / "output" / "1321_pick"]
PAGES = 3                   # страниц поиска на запрос (по 25)
W_TEXT, W_UGC, W_POP = 0.35, 0.40, 0.25   # живость важнее популярности

# Образы без человека — как outfit-пины: образ разложен на кровати (живое фото с телефона, не каталог). Во Flow потом
# сводим все три слайда к одной кровати / свету / палитре, человека не генерируем (меньше ИИ). #1 давно (ретро 50–60-х),
# #4 середина (80-е / 90-е), #7 сейчас (эффектный образ на вечер); bed — кандидаты в общую кровать-основу.
_LOOK = {"no_faces": True, "out": (1080, 1440), "min_aspect": 1.0, "related_rounds": 0, "related_seeds": 0,
         "weights": {"ref": 0.0, "text": W_TEXT, "ugc": W_UGC}, "min_ref": 0.0, "ref": [], "max_text_chars": 12,
         "ugc_floor": 0.3, "keep_full": True}
SLOTS = {
    "s3": {**_LOOK,  # Husband #1 — ретро 50–60-х
        "anchors": ["a complete retro 1960s inspired outfit laid out flat on a bed: polka dot or gingham dress, cardigan, "
                    "kitten heels or mary janes, pearls, real phone photo from above",
                    "vintage style clothes arranged on rumpled bed sheets as an outfit, casual daylight photo"],
        "queries": ["vintage outfit flat lay", "retro outfit laid out on bed", "60s outfit flat lay",
                    "polka dot dress flat lay", "vintage dress laid on bed", "retro outfit layout",
                    "vintage clothes flat lay bed", "50s outfit flat lay", "gingham dress flat lay",
                    "audrey hepburn outfit flat lay", "vintage cardigan skirt flat lay", "mary janes outfit flat lay",
                    "vintage outfit on bed", "retro dress and heels flat lay", "vintage ootd flat lay",
                    "thrifted vintage outfit laid out"]},
    "s4": {**_LOOK,  # Husband #4 — 80-е / 90-е
        "anchors": ["a complete 90s inspired outfit laid out flat on a bed: oversized blazer, slip skirt or straight jeans, "
                    "baby tee, loafers, small shoulder bag, real phone photo from above",
                    "an 80s or 90s style outfit arranged on rumpled bed sheets, casual daylight photo"],
        "queries": ["90s outfit flat lay", "90s outfit laid out on bed", "80s outfit flat lay", "blazer outfit flat lay",
                    "slip skirt outfit flat lay", "90s fashion flat lay", "mom jeans outfit flat lay",
                    "leather jacket outfit flat lay bed", "90s outfit layout", "power suit flat lay",
                    "baby tee outfit flat lay", "loafers outfit flat lay", "90s minimalist outfit flat lay",
                    "vintage 90s clothes laid out", "outfit laid out on bed jeans blazer", "90s ootd flat lay"]},
    "s5": {**_LOOK,  # Husband #7 — сейчас: эффектный образ на вечер
        "anchors": ["a complete glamorous date night outfit laid out flat on a bed: satin or sequin dress, heels, "
                    "small bag, jewelry, real phone photo from above",
                    "a going out outfit arranged on rumpled bed sheets, casual daylight photo"],
        "queries": ["date night outfit flat lay", "going out outfit laid out on bed", "night out outfit flat lay",
                    "party outfit flat lay bed", "satin dress flat lay", "sequin dress laid on bed",
                    "red dress outfit flat lay", "black dress heels flat lay", "dinner outfit laid out",
                    "outfit laid out on bed", "birthday outfit flat lay", "glam outfit flat lay",
                    "date outfit laid out on bed", "corset top outfit flat lay", "mini dress outfit flat lay",
                    "night out outfit laid out"]},
    "bed": {**_LOOK, "max_text_chars": 6,  # основа: пустая живая кровать при дневном свете, сверху / под углом
        "anchors": ["an empty unmade bed with soft rumpled linen sheets in a real bedroom, daylight from a window, phone photo from above",
                    "a cozy lived-in bedroom bed with crumpled white or cream bedding, morning sunlight, no people"],
        "queries": ["messy bed aesthetic", "unmade bed aesthetic", "linen bedding aesthetic", "white bed sheets morning light",
                    "rumpled sheets", "cozy bed aesthetic", "bedroom morning light bed", "linen bed top view",
                    "sunlight on bed", "vintage bedroom bed", "grandma bedroom aesthetic", "cream bedding aesthetic"]},
    # v3: без эпох — крутые образы. Первый пул (эпохи, «живость» 40 % + порог UGC) тянул нишевое и неказистое.
    # Здесь простые слова + в основном лайки; порога UGC нет, пины < 30 лайков не берём.
    "look": {**_LOOK, "ugc_floor": 0.0, "pages": 10, "min_likes": 30, "score": {"pop": 0.6, "aes": 0.2, "text": 0.2},
        "anchors": ["an outfit laid out flat on a bed: clothes, shoes, bag and accessories, real phone photo from above"],
        # как ищут обычные люди: одно-два повседневных слова, дальше Pinterest сам подсовывает популярное — отбор глазами
        "queries": ["outfits", "outfit", "ootd", "fits", "outfit ideas", "outfit inspo", "fit check", "outfit flat lay",
                    "outfit on bed", "outfit laid out", "flatlay", "flat lay outfit", "outfit flatlay", "fit laid out",
                    "laid out outfit", "outfit layout"],
        "only_flatlay": True},     # простые слова дают в основном людей и коллажи — оставляем только раскладки
}


KINDS = ["a real photo of clothes laid out flat on a bed or on the floor, seen from above, no person",
         "a photo of a person wearing an outfit, mirror selfie or full body photo",
         "a digital collage of clothing product cutouts on a plain white background"]


class EngPool(HP.Pool):
    """Pool с вовлечённостью: лайки, перепины одинакового фото, подписчики автора, дата."""

    def __init__(self, profile: dict, used: list[int]) -> None:
        super().__init__(profile)
        self.eng: dict[str, dict] = {}
        self.sig2pin: dict[str, str] = {}
        self.used = used

    def _page(self, q: str, bookmark: str | None) -> tuple[list[dict], str | None]:
        source = f"/search/pins/?q={hv.quote_plus(q)}"
        page_url = f"https://www.pinterest.com{source}"
        if bookmark is None:
            self.h._client.get(page_url, headers=hv.HTML_HEADERS)
            self.h._csrf = self.h._client.cookies.get("csrftoken") or self.h._csrf
        opts = {"query": q, "scope": "pins", "page_size": 25, "bookmarks": [bookmark] if bookmark else []}
        try:
            r = self.h._client.post("https://www.pinterest.com/resource/BaseSearchResource/get/",
                                    headers=self.h._api_headers(page_url),
                                    data={"source_url": source, "data": json.dumps({"options": opts, "context": {}},
                                                                                   separators=(",", ":"))})
        except Exception as exc:
            print(f"[search] {q!r}: {exc}", flush=True)
            return [], None
        if r.status_code != 200 or r.content[:1] != b"{":
            return [], None
        js = r.json()
        raw: list[dict] = []
        hv._walk_collect_pins(js, raw)
        bm = (js.get("resource_response") or {}).get("bookmark")
        return [o for o in raw if o.get("type") == "pin"], (bm if bm and bm != "-end-" else None)

    def search_all(self) -> None:
        for q in self.p["queries"]:
            bm, got, new = None, 0, 0
            for _ in range(self.p.get("pages", PAGES)):
                objs, bm = self._page(q, bm)
                for o in objs:
                    if o.get("videos") or o.get("is_promoted"):
                        continue
                    m = hv._pin_from_obj(o)
                    if m is None or m.is_ai is True:
                        continue
                    got += 1
                    likes = sum(int(v) for v in (o.get("reaction_counts") or {}).values())
                    sig = str(o.get("image_signature") or m.image_url.rsplit("/", 1)[-1].split(".")[0])
                    if sig in self.sig2pin:                       # то же фото другим пином — перепин
                        e = self.eng[self.sig2pin[sig]]
                        if m.pin_id not in e["pins"]:
                            e["pins"].add(m.pin_id)
                            e["likes"] += likes
                            e["followers"] = max(e["followers"], int((o.get("pinner") or {}).get("follower_count") or 0))
                        continue
                    self.sig2pin[sig] = m.pin_id
                    self.eng[m.pin_id] = {"pins": {m.pin_id}, "likes": likes, "created": o.get("created_at") or "",
                                          "followers": int((o.get("pinner") or {}).get("follower_count") or 0)}
                    new += self.add_metas([m], q)
                if not bm:
                    break
                time.sleep(0.4)
            print(f"[search] {q!r}: {got} пинов, новых фото {new}", flush=True)

    def download_new(self) -> None:
        super().download_new()
        for c in self.cands.values():                         # уже было в 1321 — не берём
            if c.image is not None and not c.reasons and not c.fp:
                c.fp = HP.dhash(c.image)
                if any(bin(c.fp ^ u).count("1") <= HP.DUP_HAMMING for u in self.used):
                    c.reasons.append("used")

    def pop_raw(self, c: HP.Cand) -> float:
        e = self.eng[c.pin_id]
        return math.log1p(e["likes"]) + math.log1p(len(e["pins"]) - 1)

    def rescore(self) -> None:
        live = [c for c in self.cands.values() if c.vec is not None]
        top = float(np.percentile([self.pop_raw(c) for c in live], 95)) or 1.0
        w = self.p.get("score")
        if w:                                                 # v3: популярность → эстетика кадра → релевантность
            from core.aesthetic_filter import get_aesthetic_filter
            aes = get_aesthetic_filter().get_aesthetic_scores([c.image for c in live],
                                                              image_vecs=np.stack([c.vec for c in live]))
            kind = None
            if self.p.get("only_flatlay"):                    # SigLIP zero-shot: раскладка / человек / коллаж
                kind = (np.stack([c.vec for c in live]) @ self.emb.embed_texts(KINDS).T).argmax(1)
            for i, (c, a) in enumerate(zip(live, aes)):
                if kind is not None and kind[i] != 0:
                    c.reasons.append("kind")
                self.eng[c.pin_id]["aes"] = float(a)
                c.score = w["pop"] * min(self.pop_raw(c) / top, 1.0) + w["aes"] * float(a) + w["text"] * c.text
                if self.eng[c.pin_id]["likes"] < self.p.get("min_likes", 0):
                    c.reasons.append("likes")
            return
        for c in live:
            c.score = W_TEXT * c.text + W_UGC * c.ugc + W_POP * min(self.pop_raw(c) / top, 1.0)

    def save(self, picked: list[HP.Cand], out: Path) -> None:
        super().save(picked, out)
        rows = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        for r in rows:
            e = self.eng[r["pin_id"]]
            r.update(likes=e["likes"], repins=len(e["pins"]), followers=e["followers"], created=e["created"],
                     aes=round(e.get("aes", 0.0), 3))
        (out / "manifest.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        sheets(out, rows)


def sheets(out: Path, rows: list[dict], per: int = 20) -> None:
    """Листы для отбора глазами: 5×4 крупно, номер, лайки (L), перепины (R), «живость» (u)."""
    tw, th, cols = 300, 400, 5
    font = ImageFont.truetype("arial.ttf", 18)
    for k in range(0, len(rows), per):
        part = rows[k:k + per]
        s = Image.new("RGB", (cols * tw, ((len(part) + cols - 1) // cols) * (th + 26)), (25, 25, 25))
        d = ImageDraw.Draw(s)
        for i, r in enumerate(part):
            x, y = (i % cols) * tw, (i // cols) * (th + 26)
            s.paste(Image.open(out / r["file"]).resize((tw, th)), (x, y + 26))
            d.text((x + 4, y + 3), f"{r['file'][:3]}  L{r['likes']}  a{r.get('aes', 0):.2f}  u{r['ugc']:.2f}",
                   fill=(255, 230, 80), font=font)
        s.save(out / f"_sheet_{k // per + 1:02d}.jpg", quality=86)


def used_hashes() -> list[int]:
    out = []
    for d in USED:
        for f in d.rglob("*.jpg"):
            try:
                out.append(HP.dhash(Image.open(f)))
            except Exception:
                pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", choices=sorted(SLOTS), required=True)
    ap.add_argument("--target", type=int, default=90)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    t0 = time.perf_counter()
    pool = EngPool(dict(SLOTS[args.slot]), used_hashes())
    pool.search_all()
    pool.download_new()
    pool.score_new()
    pool.rescore()
    picked = pool.select(args.target)
    out = OUT / args.slot
    pool.save(picked, out)
    why: dict[str, int] = {}
    for c in pool.cands.values():
        for r in c.reasons:
            why[r.split()[0]] = why.get(r.split()[0], 0) + 1
    print(f"фото {len(pool.cands)} · отсеяно {why} · отобрано {len(picked)} → {out} за {time.perf_counter() - t0:.0f} с")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
