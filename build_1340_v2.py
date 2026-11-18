#!/usr/bin/env python3
"""
1340 v2 — Inspoy, докрутка «5 outfits that make you look 10 years younger» (реф TikTok 7703543830322220309): новые цепляющие обложки,
три девушки, та же девушка на последнем слайде, весь текст на белых плашках. Кадры Flow в 9:16: основной + 3 серийных на слот
(output/1340_v2/pool, make_1340_v2_pools.py); плашки и кроп едут за кадром по pool.json.
  карусели 3:4 и 9:16: обложка, образы 1–3, последний слайд с карточкой Inspoy, по папке на девушку;
  видео 9:16: обложка, образы 1–5, последний слайд, смены и начало песни — из тюнера (tuner_1340_start.py).
Файлы с айди 1: sort_<слайд>_<n>_1.jpg, NNN_1.mp4.

  python build_1340_v2.py --allframes output/_work/1340_v2_all                  # все кадры всех слотов на листах
  python build_1340_v2.py --mode c34 -n 50 --out output/1340_v2_carousels_3x4_50
  python build_1340_v2.py --mode c916 -n 50 --out output/1340_v2_carousels_9x16_50
  python build_1340_v2.py --mode video -n 100 --range 1-25 --out output/1340_v2_video_100
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1307_carousels as P  # noqa: E402  (plate_block)
import build_1340_carousels as C40  # noqa: E402  (тексты, телефон)
import build_1391_reels as V  # noqa: E402  (сборка видео на бит)
from core.safe_zones import check_box, draw_overlay  # noqa: E402

POOL = ROOT / "output" / "1340_v2" / "pool"
SCR = ROOT / "output" / "1340_slides" / "s5_screens"
XF = json.loads((POOL / "pool.json").read_text(encoding="utf-8"))
W = 1080
FULL_H = round(1376 * W / 768)
VARIANTS = 4
# y подбородка на обложке, низ руки с телефоном на последнем слайде и верх кропа 3:4 — в px основного кадра 1080×FULL_H
GIRLS = {
    "g1": dict(dir="red_coat", cover="covers/g1_red", last="last/g1_red", screen="screen_2_coat.png", chin=985, y34=250, last_y34=220, hand=835),
    "g2": dict(dir="leather_jacket", cover="covers/g2_leather", last="last/g2_leather", screen="screen_4_leather.png", chin=1125, y34=330, last_y34=300, hand=880),
    "g3": dict(dir="burgundy_dress", cover="covers/g3_burgundy", last="last/g3_burgundy", screen="screen_3_dress.png", chin=905, y34=200, last_y34=260, hand=895),
}
LOOKS = [("looks/l1_coat", "1. Enters the room", 250), ("looks/l2_leather", "2. Plot twist", 260), ("looks/l3_dress", "3. Walks in slow motion", 200),
         ("looks/l4_green", "4. Main character", 250), ("looks/l5_pink", "5. The cheat code", 200)]
# звук поста TikTok 7703543830322220309; начало и смены настроены юзером в тюнере
_MUSIC = ROOT / "downloads" / "1340" / "music"
V.MUSIC = _MUSIC / "tt_sound.mp3"
_SAVED = json.loads((_MUSIC / "_start.json").read_text(encoding="utf-8"))
START, SONG_CUTS, SONG_END = _SAVED["start"], _SAVED["cuts"], _SAVED["end"]
CUTS = [0.0] + [round((t - START) * V.FPS) / V.FPS for t in SONG_CUTS]
END = round((SONG_END - START) * V.FPS) / V.FPS
ID = "1"


def music(work: Path) -> Path:
    """Трек с выбранного начала: затухание в конце, -14 LUFS."""
    out = work / f"sound_{START:.3f}_{END:.3f}.wav"
    if not out.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{START:.3f}", "-i", str(V.MUSIC), "-t", f"{END:.3f}", "-af",
                        f"afade=t=out:st={END - 0.25:.3f}:d=0.25,loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "2", str(out)], check=True)
    return out


def rel(slot: str, v: int) -> str:
    return f"{slot}_v{v}.jpg"


def at(y: float, name: str) -> int:
    """Координата y основного кадра → на серийном кадре."""
    t = XF[name]
    return round(t["s"] * y + t["dy"])


def full(name: str, r: random.Random) -> Image.Image:
    im = ImageOps.fit(Image.open(POOL / name).convert("RGB"), (W, FULL_H), Image.Resampling.LANCZOS)
    return ImageEnhance.Brightness(im).enhance(r.uniform(0.98, 1.03))


def crop34(im: Image.Image, y0: int, r: random.Random) -> tuple[Image.Image, int]:
    y0 = max(0, min(FULL_H - 1440, y0 + r.randint(-14, 14)))
    return im.crop((0, y0, W, y0 + 1440)), y0


def crop916(im: Image.Image, r: random.Random) -> tuple[Image.Image, int]:
    y0 = r.randint(0, FULL_H - 1920)
    return im.crop((0, y0, W, y0 + 1920)), y0


def plate(text: str, px: int, max_w: int) -> Image.Image:
    lines = [ln for ln in text.split("\n") if ln.strip()]
    while True:
        im = P.plate_block(lines, px)
        im = im.crop(im.getbbox())
        if im.width <= max_w or px <= 30:
            return im
        px -= 2


def stick(img: Image.Image, pl: Image.Image, cy: int) -> tuple:
    x, y = (img.width - pl.width) // 2, cy - pl.height // 2
    img.alpha_composite(pl, (x, y))
    return (x, y, x + pl.width, y + pl.height)


def cover(g: dict, key: str, tall: bool, name: str, r: random.Random) -> tuple[Image.Image, list]:
    im = full(name, r)
    px, mw = (54, 800) if tall else (46, 720)
    im, y0 = crop916(im, r) if tall else crop34(im, at(g["y34"], name), r)
    im = im.convert("RGBA")
    pl = plate(C40.COVERS[key], px, mw)
    return im, [stick(im, pl, at(g["chin"], name) - y0 + 40 + pl.height // 2)]


def look(k: int, tall: bool, name: str, r: random.Random) -> tuple[Image.Image, list]:
    _, title, y34 = LOOKS[k]
    im = full(name, r)
    im = (crop916(im, r) if tall else crop34(im, at(y34, name), r))[0].convert("RGBA")
    return im, [stick(im, plate(title, 60 if tall else 54, 800 if tall else 720), 300 if tall else 128)]


def last(g: dict, tall: bool, name: str, r: random.Random) -> tuple[Image.Image, list]:
    im = full(name, r)
    im, y0 = crop916(im, r) if tall else crop34(im, at(g["last_y34"], name), r)
    top = at(g["hand"], name) - y0 + (20 if tall else 12)
    ph_h, px, mw = (530, 50, 800) if tall else (500, 44, 720)
    im = im.convert("RGBA")
    pl = plate(C40.S5_TEXT, px, mw)
    box = stick(im, pl, top + pl.height // 2)
    C40.K.drop_any(C40.K.phone(SCR / g["screen"], ph_h), im, 760, box[3] + 14, angle=-4, alpha=120)
    return im, [box]


def check(boxes: list, im: Image.Image, what: str) -> None:
    for b in boxes:
        if bad := check_box(im.width, im.height, b):
            raise SystemExit(f"{what}: вне безопасной зоны {b} — {bad}")


class Deck:
    """Варианты кадра выдаются равномерно: перемешанная колода на слот."""

    def __init__(self, rng: random.Random):
        self.rng, self.left = rng, {}

    def take(self, slot: str) -> int:
        if not self.left.get(slot):
            self.left[slot] = list(range(VARIANTS))
            self.rng.shuffle(self.left[slot])
        return self.left[slot].pop()


def plan(n: int, seed: int, n_looks: int) -> list[dict]:
    rng, deck, seen, rows = random.Random(seed), None, set(), []
    deck = Deck(rng)
    girls, keys = list(GIRLS), list(C40.COVERS)
    for i in range(1, n + 1):
        gk = girls[(i - 1) % len(girls)]
        key = keys[((i - 1) // len(girls)) % len(keys)]               # у каждой девушки все тексты обложки по кругу
        g = GIRLS[gk]
        while True:
            c, l = deck.take(g["cover"]), deck.take(g["last"])
            lk = tuple(deck.take(LOOKS[k][0]) for k in range(n_looks))
            sig = (gk, key, c, l, lk)
            if sig not in seen:
                break
        seen.add(sig)
        rows.append(dict(i=i, gk=gk, key=key, cover=rel(g["cover"], c), last=rel(g["last"], l), looks=[rel(LOOKS[k][0], v) for k, v in enumerate(lk)]))
    return rows


def slides_for(row: dict, tall: bool, r: random.Random) -> list:
    g = GIRLS[row["gk"]]
    return [cover(g, row["key"], tall, row["cover"], r)] + [look(k, tall, nm, r) for k, nm in enumerate(row["looks"])] + [last(g, tall, row["last"], r)]


def all_frames(out: Path) -> None:
    """Лист со всеми кадрами всех слотов — проверить, как вставлено на каждом."""
    out.mkdir(parents=True, exist_ok=True)
    r = random.Random(3)
    for tall, name, cw, ch in ((False, "c34", 216, 288), (True, "916", 180, 320)):
        rows = []
        for gk, g in GIRLS.items():
            rows.append([cover(g, "A", tall, rel(g["cover"], v), r) for v in range(VARIANTS)])
            rows.append([last(g, tall, rel(g["last"], v), r) for v in range(VARIANTS)])
        for k, (slot, *_ ) in enumerate(LOOKS):
            if tall or k < 3:
                rows.append([look(k, tall, rel(slot, v), r) for v in range(VARIANTS)])
        cols = 8
        cells = [c for row in rows for c in row]
        sh = Image.new("RGB", (cols * cw, ((len(cells) + cols - 1) // cols) * ch), "white")
        for i, (im, boxes) in enumerate(cells):
            check(boxes, im, f"лист {name} {i}")
            q = draw_overlay(im.convert("RGB"))
            for b in boxes:
                ImageDraw.Draw(q).rectangle(b, outline=(255, 200, 0), width=4)
            sh.paste(q.resize((cw, ch)), (i % cols * cw, i // cols * ch))
        sh.save(out / f"_all_{name}.jpg", quality=86)
        print(name, sh.size, flush=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["c34", "c916", "video"])
    ap.add_argument("-n", type=int, default=50)
    ap.add_argument("--range", default="")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--allframes", type=Path)
    a = ap.parse_args()
    if a.allframes:
        all_frames(a.allframes)
        return 0
    tall, video = a.mode != "c34", a.mode == "video"
    seed = {"c34": 13401, "c916": 13402, "video": 13403}[a.mode]
    rows = plan(a.n, seed, 5 if video else 3)
    lo, hi = map(int, a.range.split("-")) if a.range else (1, a.n)
    work = ROOT / "output" / "_work" / "1340_v2" / a.mode
    work.mkdir(parents=True, exist_ok=True)
    a.out.mkdir(parents=True, exist_ok=True)
    wav = music(work.parent) if video else None
    for row in rows:
        i = row["i"]
        if not lo <= i <= hi:
            continue
        r = random.Random(seed * 1000 + i)
        slides = slides_for(row, tall, r)
        for k, (im, boxes) in enumerate(slides, 1):
            check(boxes, im, f"{i:03d} слайд {k}")
        if video:
            fr = []
            for k, (im, _) in enumerate(slides, 1):
                p = work / f"{i:03d}_{k}.png"
                im.convert("RGB").save(p)
                fr.append(p)
            V.render(fr, wav, a.out / f"{i:03d}_{ID}.mp4", CUTS, END)
            for p in fr:
                p.unlink()
        else:
            d = a.out / GIRLS[row["gk"]]["dir"]
            d.mkdir(exist_ok=True)
            for k, (im, _) in enumerate(slides, 1):
                im.convert("RGB").save(d / f"sort_{k}_{i}_{ID}.jpg", quality=95)
        print(f"  {i:03d} {row['gk']} {row['key']}", flush=True)
    (work / f"manifest_{lo}-{hi}.json").write_text(json.dumps(rows[lo - 1:hi], indent=1), encoding="utf-8")
    print(f"готово: {lo}-{hi} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
