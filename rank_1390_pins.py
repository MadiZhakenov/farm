#!/usr/bin/env python3
"""
1390 — отбор под кадры рефа (downloads/1390/ref): на слайде джинсы — ГЛАВНЫЙ объект крупно (карманы / принт /
вышивка, на теле сзади или сбоку, по пояс и ниже, без лица), тёмные телефонные фото в помещении, ночь / вспышка, Y2K.
Сначала соответствие рефу (тип кадра + вайб), лайки / сохранения — только порядок внутри подходящих.

Строки из встроенного браузера (под входом пользователя) «id|лайки|сохранения|хеш картинки»:
  output/1390_pins/q_<слот>.txt            — выдача простых запросов (поиск затравок)
  output/1390_pins/rel_<слот>.txt          — «Ещё похожее» затравок, порядок Pinterest (самые похожие первыми), компактно:
                                             «<№ затравки в seeds.json>>хеш base64url|лайки|сохранения»

  python rank_1390_pins.py rank embroidered     # → output/1390_pins/<слот>/_rank.jpg — кандидаты в затравки
  python rank_1390_pins.py pairs embroidered    # → _pairs_<затравка>.jpg — затравка + её «похожие» по сходству
"""

from __future__ import annotations

import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import harvest_carousel_pool as HP  # noqa: E402  (dhash)

PINS = ROOT / "output" / "1390_pins"
TILES = ROOT / "downloads" / "1390" / "ref" / "tiles"
REF_JEANS = [TILES / f"s{k}_{s}.jpg" for k in (2, 3, 6) for s in "ab"]       # LDN, Schuze blossom, Ed Hardy

POS = ["a close up phone photo of baggy jeans worn by a person, back pockets, no face",
       "a close up of the back of jeans with a big print or embroidery",
       "jeans laid out on a bed or on the floor, dark phone photo",
       "a close up of a jeans pocket with studs or embroidery"]
NEG = ["a full body photo of a woman standing, face visible", "a mirror selfie showing the face",
       "a street style photo of a person outdoors in daylight", "a clothing store with racks of jeans",
       "a collage grid of many photos", "a product photo of jeans on a plain white background",
       "a man posing in jeans", "a portrait of a person's face", "shoes", "a hoodie", "a watch"]
COVER_POS = ["a girl in baggy denim jacket and baggy jeans at night, flash photo, face turned away",
             "a girl in an oversized denim outfit on the street at night, flash"]
COVER_NEG = ["a daylight street style photo", "a mirror selfie in a bright room", "a product photo on white",
             "a collage grid of many photos", "a man posing in jeans", "a clothing store", "a close up of jeans"]


def rows(path: Path, seeds: list[str] | None = None) -> list[tuple[str, str, int, int, str]]:
    """«id|L|S|sig» или компактное «k>sig64|L|S» (id затравки = seeds[k], id пина — потом по хешу) →
    (затравка, id, L, S, sig hex)."""
    import base64
    out = []
    for ln in path.read_text(encoding="utf-8").split():
        seed, _, rest = ln.rpartition(">")
        parts = rest.split("|")
        if len(parts) == 3:
            s64, likes, saves = parts
            sig = base64.urlsafe_b64decode(s64 + "=" * (-len(s64) % 4)).hex()
            out.append((seeds[int(seed)] if seed else "", "", int(likes), int(saves), sig))
        else:
            pid, likes, saves, sig = parts
            out.append((seed, pid, int(likes), int(saves), sig))
    return out


def thumb(cli: httpx.Client, sig: str) -> Image.Image | None:
    f = PINS / "_thumbs" / f"{sig}.jpg"
    if f.exists():
        return Image.open(f).convert("RGB")
    try:
        r = cli.get(f"https://i.pinimg.com/474x/{sig[:2]}/{sig[2:4]}/{sig[4:6]}/{sig}.jpg")
        if r.status_code != 200:
            return None
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(r.content))).convert("RGB")
    except Exception:
        return None
    f.parent.mkdir(parents=True, exist_ok=True)
    im.save(f, quality=90)
    return im


class Scorer:
    def __init__(self) -> None:
        from core.taste_embedder import get_embedder
        self.e = get_embedder()
        self.e.ensure()
        self.ref = {"jeans": self.e.embed_images([Image.open(p).convert("RGB") for p in REF_JEANS]),
                    "cover": self.e.embed_images([Image.open(TILES / "cover.jpg").convert("RGB")])}
        self.txt = {"jeans": (self.e.embed_texts(POS + NEG), len(POS)),
                    "cover": (self.e.embed_texts(COVER_POS + COVER_NEG), len(COVER_POS))}

    def score(self, ims: list[Image.Image], kind: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """(похоже на кадр рефа 0–1, p «нужный тип кадра», сходство с кадрами рефа, тёмность) + эмбеддинги."""
        v = self.e.embed_images(ims)
        tv, npos = self.txt[kind]
        logits = (v @ tv.T) * 100
        p = np.exp(logits - logits.max(1, keepdims=True))
        p = p / p.sum(1, keepdims=True)
        ptype = p[:, :npos].sum(1)
        ref = (v @ self.ref[kind].T).max(1)
        dark = np.array([1 - np.asarray(im.convert("L").resize((64, 64)), dtype=np.float32).mean() / 255 for im in ims])
        s = 0.5 * ptype + 0.3 * np.clip((ref - 0.35) / 0.4, 0, 1) + 0.2 * dark
        return s, ptype, ref, v


def sheet(cells: list[tuple[Image.Image, str]], dest: Path, cols: int = 8, tw: int = 180, th: int = 320,
          title: str | None = None) -> None:
    font = ImageFont.truetype("arial.ttf", 14)
    top = 30 if title else 0
    s = Image.new("RGB", (cols * tw, top + ((len(cells) + cols - 1) // cols) * (th + 20)), (22, 22, 22))
    d = ImageDraw.Draw(s)
    if title:
        d.text((6, 6), title, fill=(255, 255, 255), font=ImageFont.truetype("arialbd.ttf", 18))
    for i, (im, lab) in enumerate(cells):
        x, y = (i % cols) * tw, top + (i // cols) * (th + 20)
        s.paste(ImageOps.fit(im, (tw - 2, th), centering=(0.5, 0.45)), (x, y + 20))
        d.text((x + 3, y + 2), lab, fill=(255, 230, 80), font=font)
    s.save(dest, quality=85)


def load(slot_file: Path, seeds: list[str] | None = None) -> tuple[list, list[Image.Image | None]]:
    rs = rows(slot_file, seeds)
    cli = httpx.Client(timeout=25, follow_redirects=True,
                       headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com/"})
    with ThreadPoolExecutor(8) as ex:
        ims = list(ex.map(lambda r: thumb(cli, r[4]), rs))
    return rs, ims


def rank(slot: str, sc: Scorer, show: int = 40) -> None:
    rs, ims = load(PINS / f"q_{slot}.txt")
    keep = [(r, im) for r, im in zip(rs, ims) if im is not None]
    s, pt, ref, _v = sc.score([im for _r, im in keep], "cover" if slot == "cover" else "jeans")
    order = np.argsort(-s)
    out = PINS / slot
    out.mkdir(parents=True, exist_ok=True)
    ranked = [{"n": k + 1, "pin_id": keep[i][0][1], "likes": keep[i][0][2], "saves": keep[i][0][3], "sig": keep[i][0][4],
               "score": round(float(s[i]), 3), "type": round(float(pt[i]), 2), "ref": round(float(ref[i]), 2)}
              for k, i in enumerate(order)]
    (out / "rank.json").write_text(json.dumps(ranked, indent=1), encoding="utf-8")
    sheet([(keep[i][1], f"{k + 1} L{keep[i][0][2]} S{keep[i][0][3] // 1000}k")
           for k, i in enumerate(order[:show])], out / "_rank.jpg", title=f"{slot}: кандидаты в затравки (по сходству с рефом)")
    print(f"{slot}: {len(keep)} → _rank.jpg (топ {show})")


def pairs(slot: str, sc: Scorer, per_seed: int = 15) -> None:
    seeds = json.loads((PINS / "seeds.json").read_text(encoding="utf-8"))[slot]
    rs, ims = load(PINS / f"rel_{slot}.txt", seeds)
    kind = "cover" if slot == "cover" else "jeans"
    rank_ = {r["pin_id"]: r for r in json.loads((PINS / slot / "rank.json").read_text(encoding="utf-8"))}
    cli = httpx.Client(timeout=25, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    out = PINS / slot
    summary = {}
    for seed in seeds:
        group = [(r, im) for r, im in zip(rs, ims) if r[0] == seed and im is not None]
        sim = thumb(cli, rank_[seed]["sig"])
        allims = [sim] + [im for _r, im in group]
        s, pt, _ref, v = sc.score(allims, kind)
        cos = v[1:] @ v[0]
        fp0 = HP.dhash(sim)
        cand = []
        for (r, im), c, sc_, p_ in zip(group, cos, s[1:], pt[1:]):
            if bin(HP.dhash(im) ^ fp0).count("1") <= HP.DUP_HAMMING:   # та же фотография — не пара
                continue
            cand.append((r, im, float(c), float(sc_), float(p_)))
        cand = [c for c in cand if c[4] >= 0.25]                        # тип кадра: крупно джинсы, не полный рост / магазин
        cand.sort(key=lambda t: -t[2])                                  # ближе к затравке — выше шанс той же вещи
        cells = [(sim, f"ЗАТРАВКА L{rank_[seed]['likes']} S{rank_[seed]['saves'] // 1000}k")]
        cells += [(im, f"{k + 1} L{r[2]} S{r[3] // 1000}k c{c:.2f}") for k, (r, im, c, _s, _p) in enumerate(cand[:per_seed])]
        sheet(cells, out / f"_pairs_{seed}.jpg", title=f"{slot}: затравка {seed} и её «похожие» (c — сходство)")
        summary[seed] = [{"n": k + 1, "pin_id": r[1], "likes": r[2], "saves": r[3], "sig": r[4], "cos": round(c, 3),
                          "score": round(s_, 3)} for k, (r, _im, c, s_, _p) in enumerate(cand[:per_seed])]
    (out / "pairs.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"{slot}: затравок {len(seeds)} → _pairs_*.jpg")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    mode, slots = sys.argv[1], sys.argv[2:]
    sc = Scorer()
    for slot in slots:
        (rank if mode == "rank" else pairs)(slot, sc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def overview(slot: str, per_row: int = 9) -> None:
    """Один лист на слайд: строка = затравка + её самые похожие (по сходству), чтобы найти пару той же вещи."""
    summ = json.loads((PINS / slot / "pairs.json").read_text(encoding="utf-8"))
    rank_ = {r["pin_id"]: r for r in json.loads((PINS / slot / "rank.json").read_text(encoding="utf-8"))}
    tw, th, top = 150, 266, 20
    font = ImageFont.truetype("arial.ttf", 13)
    s = Image.new("RGB", ((per_row + 1) * tw + 6, len(summ) * (th + top)), (22, 22, 22))
    d = ImageDraw.Draw(s)
    for row, (seed, items) in enumerate(summ.items()):
        y = row * (th + top)
        cells = [(rank_[seed]["sig"], f"S{row}: L{rank_[seed]['likes']} S{rank_[seed]['saves'] // 1000}k")]
        cells += [(it["sig"], f"{row}.{it['n']} L{it['likes']} S{it['saves'] // 1000}k") for it in items[:per_row]]
        for i, (sig, lab) in enumerate(cells):
            x = i * tw + (6 if i else 0)
            im = Image.open(PINS / "_thumbs" / f"{sig}.jpg").convert("RGB")
            s.paste(ImageOps.fit(im, (tw - 2, th), centering=(0.5, 0.45)), (x, y + top))
            d.text((x + 2, y + 3), lab, fill=(120, 220, 255) if i == 0 else (255, 230, 80), font=font)
    s.save(PINS / slot / "_pairs_all.jpg", quality=84)


def brands(slot: str, sc: "Scorer", per_brand: int = 16) -> None:
    """Бренды (пользователь: «ни одного тренда и бренда»): b_<слот>.txt — «Бренд_Модель>хеш base64url|лайки|сохранения»,
    только пины с брендом в тексте (поиск по бренду + «похожие» лучших). Строка листа = бренд, внутри — по сходству
    с кадром рефа (крупно джинсы, темно); полный рост / магазин / коллаж отсеяны (тип кадра < 0.25)."""
    import base64
    rs = []
    for ln in (PINS / f"b_{slot}.txt").read_text(encoding="utf-8").split():
        brand, _, rest = ln.partition(">")
        s64, likes, saves = rest.split("|")
        sig = base64.urlsafe_b64decode(s64 + "=" * (-len(s64) % 4)).hex()
        rs.append((brand.replace("_", " "), int(likes), int(saves), sig))
    cli = httpx.Client(timeout=25, follow_redirects=True,
                       headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com/"})
    with ThreadPoolExecutor(8) as ex:
        ims = list(ex.map(lambda r: thumb(cli, r[3]), rs))
    keep = [(r, im) for r, im in zip(rs, ims) if im is not None]
    s, pt, _ref, _v = sc.score([im for _r, im in keep], "cover" if slot == "cover" else "jeans")
    groups: dict[str, list] = {}
    for (r, im), sc_, p_ in zip(keep, s, pt):
        if p_ >= 0.25:
            groups.setdefault(r[0], []).append((r, im, float(sc_)))
    out = PINS / slot
    out.mkdir(parents=True, exist_ok=True)
    summary, cells_rows = {}, []
    for bi, (brand, items) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1]))):
        items.sort(key=lambda t: -t[2])
        items = items[:per_brand]
        summary[brand] = [{"n": k + 1, "likes": r[1], "saves": r[2], "sig": r[3], "score": round(sc_, 3)}
                          for k, (r, _im, sc_) in enumerate(items)]
        cells_rows.append((f"B{bi} {brand}", [(im, f"{bi}.{k + 1} L{r[1]} S{r[2] // 1000}k")
                                              for k, (r, im, _s) in enumerate(items)]))
    (out / "brands.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    tw, th, top, cols = 150, 266, 20, 10
    font = ImageFont.truetype("arial.ttf", 13)
    fb = ImageFont.truetype("arialbd.ttf", 17)
    nrows = sum(1 + (len(c) - 1) // cols for _t, c in cells_rows)
    sh = Image.new("RGB", (cols * tw, nrows * (th + top) + 26 * len(cells_rows)), (22, 22, 22))
    d = ImageDraw.Draw(sh)
    y = 0
    for title, cells in cells_rows:
        d.text((4, y + 3), title, fill=(120, 220, 255), font=fb)
        y += 26
        for i, (im, lab) in enumerate(cells):
            if i and i % cols == 0:
                y += th + top
            x = (i % cols) * tw
            sh.paste(ImageOps.fit(im, (tw - 2, th), centering=(0.5, 0.45)), (x, y + top))
            d.text((x + 2, y + 3), lab, fill=(255, 230, 80), font=font)
        y += th + top
    sh.save(out / "_brands.jpg", quality=84)
    print(f"{slot}: " + ", ".join(f"{b} {len(v)}" for b, v in summary.items()))
