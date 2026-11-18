#!/usr/bin/env python3
"""
Inspoy, ID 1 — ТЗ «палец на палитре» (build_inspoy_thumb_full.py) в оформлении квиза 1322 (партия v4): 9:16, фон и темы
1322, serif, круги/карточки с акцентным кольцом, скруглённые плашки цветов. Текст ТЗ дословно.
  s1 — обложка квиза: 4 круга звёзд по сезонам + палитры (output/1322_lib4);
  s2–s5 — «spring?…»: 12 плашек цветов сезона вокруг пустого нейтрального круга (туда кладут палец);
  s6 — карточка с кадром шкафа (camel) + плашки; s7 — карточка девушки + плашки soft summer + карточка App Store.

  python build_inspoy_thumb_quiz.py -n 2 --themes cream,lilac --out output/inspoy_thumb_quiz_test
"""

from __future__ import annotations

import argparse
import itertools
import random
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1322_carousels as B  # noqa: E402
import build_inspoy_thumb as T  # noqa: E402
import build_inspoy_thumb_full as F  # noqa: E402
from core.safe_zones import check_box, draw_overlay  # noqa: E402

NEUTRAL = (214, 212, 207)
EXTRA = {"spring": ["#FFD7A8", "#B6E0A0"], "summer": ["#C9D6DF", "#9D8AA5"],
         "autumn": ["#A44A3F", "#8A6A3B"], "winter": ["#7A0C2E", "#E6E8EE"]}   # до 12 плашек на сезон
CAMEL = ["#C19A6B", "#B8895A", "#A9784A", "#D2B48C", "#8B6B45", "#E0C9A6"]
CHIP_X = [119, 264, 408, 551, 695, 839]
COVER_DY = 25
SIZE, GAP = 190, 17
RING = [(r, c) for r in range(4) for c in range(4) if not (r in (1, 2) and c in (1, 2))]


def cover(pick: dict[str, Path]) -> B.Slide:
    sl = B.Slide()
    y = sl.text(540, 205, "place your thumb on each palette", 49, 600) + 16
    y = sl.text(540, y, "and swipe.", 49, 600) + 18
    sl.text(540, y, "your skin will tell you your season", 38, 450, emoji="👇", alt=True)
    for name, box, (cx, ty) in B.SEASONS:
        key = name.lower()
        zoom, drop = B.circle_frame(pick[key], key) or B.CIRCLE_FRAME[key]
        ph = B.ref_grade(B.frame_portrait(pick[key], 352, 352, zoom, drop, pad=True), box, 1)
        sl.paste(B.framed(ph, "circle"), box[0] + 6 - 26, box[1] + 6 - 26 + COVER_DY)
        sl.text(cx, ty + COVER_DY, name, 47, 600)
        px, py = B.PAL1[name]
        cols = [B.sample(1, px + 18 + c * 36, py + 18 + r * 36) for r in range(2) for c in range(5)]
        sl.squares(px + 2, py + 2 + COVER_DY, cols, 32, 4, 5)
    return sl


def season_slide(season: str, seed: int) -> B.Slide:
    sl = B.Slide()
    text, base = T.SEASONS[season]
    colors = base + EXTRA[season]
    random.Random(seed).shuffle(colors)
    sl.text(540, 395, text, 104, 600)
    x0, y0 = 540 - (4 * SIZE + 3 * GAP) / 2, 570
    for (r, c), col in zip(RING, colors):
        x, y, c3 = x0 + c * (SIZE + GAP), y0 + r * (SIZE + GAP), T.rgb(col)
        sl.squares(x, y, [c3], SIZE, 0, 1, 18)
        if sum(c3) / 3 > 215:                        # светлые плашки не сливаются с фоном: тонкий контур
            line = tuple(round(v * 0.8 + i * 0.2) for v, i in zip(c3, B.THEME["ink"]))
            sl.d.rounded_rectangle((x * B.SS, y * B.SS, (x + SIZE) * B.SS - 1, (y + SIZE) * B.SS - 1),
                                   radius=18 * B.SS, outline=line, width=2 * B.SS)
    d = 356
    disc = B.framed(Image.new("RGB", (d, d), NEUTRAL), "circle")
    cy = y0 + 2 * SIZE + 1.5 * GAP
    sl.paste(disc, 540 - disc.width / 2, cy - disc.height / 2)
    return sl


def chips(sl: B.Slide, y: float, cols: list) -> None:
    for x, c in zip(CHIP_X, cols):
        sl.squares(x, y, [c], 122, 0, 1)


def closet_slide(src: Path, rng: random.Random) -> B.Slide:
    sl = B.Slide()
    y = sl.text(540, 225, "I was SO sure I was an autumn.", 58, 600) + 22
    sl.text(540, y, "I’ve been wearing camel for 5 years", 44, 500, alt=True)
    im = F.real_life(F.frame_top(src, rng), rng)
    w, h = 812, 900
    ch = round(im.width * h / w)
    photo = im.crop((0, im.height - ch, im.width, im.height)).resize((w, h), Image.Resampling.LANCZOS)
    sl.paste(B.framed(photo, "rect", 34), 134 - 26, 420 - 26)
    chips(sl, 1372, [T.rgb(c) for c in CAMEL])
    return sl


def girl_crop(im: Image.Image, w: int, h: int) -> Image.Image:
    """Кадр вокруг девушки у зеркала: по лицу, если найдено; иначе — правая часть кадра."""
    fb = B.face_box(im)
    if fb is not None:
        x0, y0, x1, y1, _ = fb
        fh = y1 - y0
        ch = min(im.height, 5.4 * fh)
        cx, top = (x0 + x1) / 2, y0 - 1.1 * fh
    else:
        ch = im.height * 0.52
        cx, top = im.width * 0.76, im.height * 0.2
    cw = ch * w / h
    if cw > im.width:
        cw, ch = im.width, im.width * h / w
    left = min(max(0, cx - cw / 2), im.width - cw)
    top = min(max(0, top), im.height - ch)
    return im.crop((round(left), round(top), round(left + cw), round(top + ch))).resize((w, h), Image.Resampling.LANCZOS)


def result_slide(src: Path, rng: random.Random) -> B.Slide:
    sl = B.Slide()
    y = sl.text(540, 215, "one selfie in inspoy:", 58, 600) + 20
    y = sl.text(540, y, "soft summer.", 58, 500, alt=True) + 22
    sl.text(540, y, "the beige was washing me out the whole time", 37, 500, alt=True)
    photo = girl_crop(F.real_life(F.frame_top(src, rng), rng), 600, 700)
    sl.paste(B.framed(photo, "rect", 34), 540 - 300 - 26, 440 - 26)
    cols = [B.sample(7, x + 61, 1539, 12) for x in CHIP_X]
    for x, c in zip(CHIP_X, cols):
        sl.squares(x + 16, 1172, [c], 90, 0, 1)
    card = B.C1319.app_card(540)
    sl.paste(card, 540 - card.width / 2, 1290)
    return sl


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "inspoy_thumb_quiz_test")
    ap.add_argument("--themes", default="cream,sage,lilac,butter,sky")
    ap.add_argument("--range", default="", help="a-b: только эти номера плана (для параллельных процессов)")
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_1.jpg")
    a = ap.parse_args()
    lo, hi = map(int, a.range.split("-")) if a.range else (1, a.n)
    B.LIB = ROOT / "output" / "1322_lib4"
    picks = B.plan_lib(a.n, 8101)
    themes = a.themes.split(",")
    combos = list(itertools.product(F.POOLS[6], F.POOLS[7]))
    random.Random(1702).shuffle(combos)
    for i, pick in enumerate(picks, 1):
        if not lo <= i <= hi:
            continue
        B.THEME.clear()
        B.THEME.update(B.THEMES[themes[(i - 1) % len(themes)]])
        rng = random.Random(5100 + i)
        s6, s7 = combos[(i - 1) % len(combos)]
        slides = [cover(pick)] + [season_slide(s, 7300 + i * 13 + k) for k, s in enumerate(T.SEASONS)]
        slides += [closet_slide(s6, rng), result_slide(s7, rng)]
        d = a.out / f"{i:03d}"
        d.mkdir(parents=True, exist_ok=True)
        qa = []
        for k, sl in enumerate(slides, 1):
            im, boxes = sl.render()
            for b in boxes:
                if bad := check_box(B.W, B.H, b):
                    raise SystemExit(f"{i:03d} слайд {k}: вне безопасной зоны {b} — {bad}")
            im.save(d / f"{k}.jpg", quality=95)
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d / f"{k}.jpg", a.flat / f"sort_{k}_{i}_1.jpg")
            q = draw_overlay(im.copy())
            for b in boxes:
                ImageDraw.Draw(q).rectangle(b, outline=(255, 200, 0), width=4)
            qa.append(q.resize((270, 480)))
        sheet = Image.new("RGB", (270 * 7, 480))
        for k, q in enumerate(qa):
            sheet.paste(q, (k * 270, 0))
        sheet.save(a.out / f"_qa_{i:03d}.jpg", quality=86)
        clean = [Image.open(d / f"{k}.jpg").resize((270, 480)) for k in range(1, 8)]
        sheet = Image.new("RGB", (270 * 7, 480))
        for k, q in enumerate(clean):
            sheet.paste(q, (k * 270, 0))
        sheet.save(a.out / f"_sheet_{i:03d}.jpg", quality=88)
        print(f"  {i:03d}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
