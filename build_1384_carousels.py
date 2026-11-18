#!/usr/bin/env python3
"""
1384 — Inspoy, квиз «какой у тебя цветотип» по рефу @luvy_y (tiktok photo 7407930227256495366), 9 слайдов 9:16:
  1 обложка: фото звезды из ТЗ на весь кадр + белый текст (вариант 1 или 2 из ТЗ);
  2 волосы A black · B ginger · C blonde · D brown (жёлтая рамка, круглые фото);
  3 подтон A cool · B neutral · C warm (бирюзовая рамка, запястья из 1322);
  4 глаза A green · B blue · C dark · D brown (синяя рамка);
  5 «write down your 3 letters…» (розовая рамка);
  6–8 по 4 сезона: коды, круглое фото звезды, НАЗВАНИЕ, like …, палитра 2×8 (снята с рефа), your colors;
  9 Inspoy: текст ТЗ + два реальных экрана (сканирование лица и результат с сезоном).
Дизайн рефа: белый фон, жирный геометрический гротеск (Manrope), цветные рамки на вопросах. Тексты ТЗ дословно,
переносы по смыслу; весь текст в безопасной рамке 9:16 (x 140–940, y 200–1540) — проверка check_box.

  python build_1384_carousels.py --test                     # одна карусель → output/carousels_1384_test/001 + QA
  python build_1384_carousels.py -n 100 --flat output/1384_100
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402  (Apple-эмодзи)
import build_1322_carousels as B  # noqa: E402  (face_box, frame_eyes)
import build_1342_carousels as C  # noqa: E402  (frame_centered)
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402

W, H = 1080, 1920
X0, Y0, X1, Y1 = text_rect(W, H)                     # 140, 200, 940, 1540
SS = 2
FONT = ROOT / "fonts" / "ig_lookalike" / "Manrope.ttf"
FONT_COVER = ROOT / "fonts" / "TikTokSans-Bold.ttf"
INK = (17, 17, 17)
GREY = (90, 90, 90)
FRAME = {"hair": (247, 214, 74), "undertone": (64, 217, 181), "eyes": (16, 160, 214), "letters": (244, 154, 193)}
BORDER = 46
REF = ROOT / "downloads" / "1384" / "ref"
SCREENS = ROOT / "downloads" / "1384" / "inspoy"
LIB = ROOT / "output" / "1384_lib"
OUT_TEST = ROOT / "output" / "carousels_1384_test"

COVER_TEXTS = [["this 3-question test", "finds your color season", "in 30 seconds"],
               ["your color season", "in 30 seconds", "(answer honestly)"]]
HAIR = [("A", "black"), ("B", "ginger"), ("C", "blonde"), ("D", "brown")]
UNDERTONE = [("A", "cool undertones:", "purple or bluish veins", "wrist_cool", ["B5A3DC", "4C77A6"]),
             ("B", "neutral undertones:", "blue-green veins", "wrist_neutral", ["4C77A6", "1E98A0", "1F6B45"]),
             ("C", "warm undertones:", "olive or greenish veins", "wrist_warm", ["1F6B3A", "A8A65A"])]
EYES = [("A", "green"), ("B", "blue"), ("C", "dark"), ("D", "brown")]
# (коды, НАЗВАНИЕ, звезда, ключ палитры/слота)
SEASONS = [
    [("AAA / ABA", "CLEAR WINTER", "Megan Fox", "clear_winter"),
     ("AAB / AAD / ABB", "COOL WINTER", "Liv Tyler", "cool_winter"),
     ("AAC / DAC / ABC", "DEEP WINTER", "Lucy Liu", "deep_winter"),
     ("CAC / DAA / DAB", "COOL SUMMER", "Lily Collins", "cool_summer")],
    [("CAA / CAB / CBB", "LIGHT SUMMER", "Margot Robbie", "light_summer"),
     ("CAD / DAD / CBC / DBA / DBB", "SOFT SUMMER", "Mindy Kaling", "soft_summer"),
     ("BBA / ACA / ACB", "CLEAR SPRING", "Emma Watson", "clear_spring"),
     ("BBB / CBA / CCA / CCB", "LIGHT SPRING", "Blake Lively", "light_spring")],
    [("BCA / BCB / CCC / CCD / DCB", "WARM SPRING", "Amy Adams", "warm_spring"),
     ("BBC / CBD / DBD / DCA", "SOFT AUTUMN", "Jennifer Aniston", "soft_autumn"),
     ("BBD / ACD / BCC / BCD / DCD", "WARM AUTUMN", "Jennifer Lopez", "warm_autumn"),
     ("ABD / DBC / ACC / DCC", "DEEP AUTUMN", "Kendall Jenner", "deep_autumn")],
]
SEASON_KEYS = [k for sl in SEASONS for *_x, k in sl]
# палитры сняты с рефа (downloads/1384/ref/palettes.json); cool summer в рефе нет — своя, мягкие холодные
PALETTES = json.loads((REF / "palettes.json").read_text(encoding="utf-8"))
PALETTES["warm_spring"] = ["E4AD5D", "4B744A", "4D8A83", "C75867", "A25244", "725EA2", "4374B8", "403E3F",
                           "F0D27A", "9DBA62", "6FB67A", "E18592", "E18571", "9781B2", "60A2D2", "6E6663"]
PALETTES["cool_summer"] = ["E3DFA6", "4F8E86", "3E6F9E", "8C4A62", "B0638F", "6A5C99", "3D4E7A", "4B5560",
                           "F1EFD0", "8BC3B3", "8EB8DA", "E58FA8", "D9A6C9", "A796C9", "6E8CC4", "A8ADB4"]
SLOTS = (["cover"] + SEASON_KEYS + ["hair_" + w for _l, w in HAIR] + ["eyes_" + w for _l, w in EYES]
         + ["wrist_cool", "wrist_neutral", "wrist_warm", "screens"])
EXTS = (".jpg", ".jpeg", ".png", ".webp")


def font(px: float, wght: int = 700, path: Path = FONT) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(path), max(1, round(px * SS)))
    if path == FONT:
        f.set_variation_by_axes([wght])
    return f


def hexrgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


class Slide:
    """Холст ×SS; координаты — в пикселях готового слайда 1080×1920."""

    def __init__(self, frame: str | None = None, bg: Image.Image | None = None) -> None:
        self.im = (bg.resize((W * SS, H * SS), Image.Resampling.LANCZOS).convert("RGBA") if bg is not None
                   else Image.new("RGBA", (W * SS, H * SS), (255, 255, 255, 255)))
        self.d = ImageDraw.Draw(self.im)
        self.boxes: list[tuple[int, int, int, int]] = []
        if frame:
            b = BORDER * SS
            self.d.rectangle((0, 0, W * SS - 1, H * SS - 1), outline=FRAME[frame], width=b)

    def text(self, x: float, top: float, s: str, px: float, wght: int = 700, fill=INK, anchor: str = "m",
             emoji: str = "", path: Path = FONT, stroke: int = 0, shadow: bool = False) -> float:
        """Строка: anchor m — по центру x, l — от x, r — до x; top — верх заглавных. Возвращает низ строки."""
        f = font(px, wght, path)
        tw = f.getlength(s)
        e = A._apple_emoji_rgba(emoji, round(px * 1.05 * SS)) if emoji else None
        gap = px * 0.25 * SS if e is not None else 0
        total = tw + gap + (e.width if e is not None else 0)
        left = {"m": x * SS - total / 2, "l": x * SS, "r": x * SS - total}[anchor]
        base = top * SS + 0.73 * px * SS
        if shadow:                                      # мягкая тень под белым текстом обложки
            sh = Image.new("RGBA", self.im.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).text((left, base + 3 * SS), s, font=f, fill=(0, 0, 0, 150), anchor="ls",
                                    stroke_width=stroke * SS, stroke_fill=(0, 0, 0, 150))
            self.im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(5 * SS)))
        self.d.text((left, base), s, font=f, fill=fill, anchor="ls", stroke_width=stroke * SS,
                    stroke_fill=(0, 0, 0) if stroke else None)
        if e is not None:
            self.im.alpha_composite(e, (round(left + tw + gap), round(base - e.height * 0.82)))
        bb = self.d.textbbox((left, base), s, font=f, anchor="ls", stroke_width=stroke * SS)
        self.boxes.append((round(left / SS), round(bb[1] / SS), round((left + total) / SS), round(bb[3] / SS)))
        return bb[3] / SS

    def paste(self, el: Image.Image, x: float, y: float) -> None:
        e = el.convert("RGBA").resize((round(el.width * SS), round(el.height * SS)), Image.Resampling.LANCZOS)
        self.im.alpha_composite(e, (round(x * SS), round(y * SS)))

    def circle(self, cx: float, cy: float, dia: float, color) -> None:
        r = dia / 2 * SS
        self.d.ellipse((cx * SS - r, cy * SS - r, cx * SS + r, cy * SS + r), fill=color)

    def render(self) -> tuple[Image.Image, list]:
        return self.im.resize((W, H), Image.Resampling.LANCZOS).convert("RGB"), self.boxes


def round_mask(w: int, h: int, radius: float, circle: bool = False) -> Image.Image:
    m = Image.new("L", (w * 4, h * 4), 0)
    d = ImageDraw.Draw(m)
    if circle:
        d.ellipse((0, 0, w * 4 - 1, h * 4 - 1), fill=255)
    else:
        d.rounded_rectangle((0, 0, w * 4 - 1, h * 4 - 1), radius=radius * 4, fill=255)
    return m.resize((w, h), Image.Resampling.LANCZOS)


def shaped(photo: Image.Image, circle: bool = True, radius: float = 0, shadow: bool = False) -> Image.Image:
    w, h = photo.size
    ph = photo.convert("RGBA")
    ph.putalpha(round_mask(w, h, radius, circle))
    if not shadow:
        return ph
    pad = 30
    out = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("L", out.size, 0)
    sh.paste(round_mask(w, h, radius, circle), (pad, pad + 8))
    sh = sh.filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.28))
    out.putalpha(sh)
    out.alpha_composite(ph, (pad, pad))
    return out


def square_crop(src: Path, side: int, top_bias: float = 0.45) -> Image.Image:
    im = Image.open(src).convert("RGB")
    s = min(im.size)
    x0 = (im.width - s) // 2
    y0 = round((im.height - s) * top_bias)
    return im.crop((x0, y0, x0 + s, y0 + s)).resize((side, side), Image.Resampling.LANCZOS)


SET: dict[str, Path] = {}
VARIANT = [0]                                          # вариант текста обложки


# ---------------- слайды ----------------
def cover_crop(src: Path) -> tuple[Image.Image, tuple[float, float, float, float]]:
    """9:16 на весь кадр: лицо по центру по горизонтали и в верхней трети; возвращает и рамку лица в кадре."""
    im = Image.open(src).convert("RGB")
    fb = B.face_box(im)
    ar = W / H
    if im.width / im.height > ar:
        ch, cw = im.height, im.height * ar
    else:
        cw, ch = im.width, im.width / ar
    if fb:
        fx, fy = (fb[0] + fb[2]) / 2, (fb[1] + fb[3]) / 2
    else:
        fx, fy = im.width / 2, im.height * 0.3
    x0 = min(max(fx - cw / 2, 0), im.width - cw)
    y0 = min(max(fy - ch * 0.30, 0), im.height - ch)
    k = W / cw
    crop = im.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch))).resize((W, H), Image.Resampling.LANCZOS)
    face = ((fb[0] - x0) * k, (fb[1] - y0) * k, (fb[2] - x0) * k, (fb[3] - y0) * k) if fb else (0, 0, 0, 0)
    return crop, face


def slide_cover() -> Slide:
    photo, face = cover_crop(SET["cover"])
    sl = Slide(bg=photo)
    lines = COVER_TEXTS[VARIANT[0]]
    px = [84, 84, 84] if VARIANT[0] == 0 else [88, 88, 60]
    widest = max(font(p, path=FONT_COVER).getlength(t) / SS / p for t, p in zip(lines, px))   # ширина на 1 px кегля
    k = min(1.0, (X1 - X0 - 20) / (widest * max(px)))                                          # всё в рамку x 140–940
    px = [p * k for p in px]
    lh = [p * 1.22 for p in px]
    total = sum(lh)
    top = max(face[3] + 70, 980)                       # под подбородком, не на лице
    top = min(top, Y1 - total - 10)
    y = top
    for s, p, h in zip(lines, px, lh):
        sl.text(540, y, s, p, path=FONT_COVER, fill=(255, 255, 255), stroke=3, shadow=True)
        y += h
    return sl


def title(sl: Slide, topic: str) -> None:
    sl.text(540, 236, "choose your", 78, 800)
    sl.text(540, 336, topic, 70, 400)


def slide_hair() -> Slide:
    sl = Slide("hair")
    title(sl, "hair color")
    dia = 330
    for k, (letter, word) in enumerate(HAIR):
        cx, cy = (335, 745)[k % 2], (680, 1150)[k // 2]
        sl.paste(shaped(square_crop(SET["hair_" + word], dia, 0.35)), cx - dia / 2, cy - dia / 2)
        sl.text(cx - dia / 2 + 8, cy + dia / 2 - 34, letter, 60, 800, anchor="l")
        sl.text(cx + dia / 2 - 4, cy + dia / 2 - 6, word, 36, 500, anchor="r")
    return sl


def slide_undertone() -> Slide:
    sl = Slide("undertone")
    title(sl, "undertone")
    for k, (letter, lab, sub, slot, dots) in enumerate(UNDERTONE):
        y = 470 + k * 352
        wr = Image.open(SET[slot]).convert("RGBA")
        h = 330
        wr = wr.resize((round(wr.width * h / wr.height), h), Image.Resampling.LANCZOS)
        sl.paste(wr, 250 - wr.width / 2, y)
        tx = 400
        sl.text(tx, y + 40, letter, 70, 800, anchor="l")
        sl.text(tx, y + 140, lab, 42, 700, anchor="l")
        sl.text(tx, y + 200, sub, 34, 400, fill=GREY, anchor="l")
        for j, c in enumerate(dots):
            sl.circle(tx + 26 + j * 40, y + 285, 52, hexrgb(c))
    return sl


def slide_eyes() -> Slide:
    """4 полоски глаз столбиком, как в 1322/1342: тот же кадр обоих глаз, скругление, светлый ободок и тень."""
    sl = Slide("eyes")
    title(sl, "eye color")
    tw, th = 460, 158
    x = (W - tw) // 2
    for k, (letter, word) in enumerate(EYES):
        y = 478 + k * 268
        sl.text(x, y, letter, 48, 800, anchor="l")
        lw = font(48, 800).getlength(letter) / SS
        sl.text(x + lw + 12, y + 10, word, 36, 500, anchor="l")
        ph = B.frame_eyes(SET["eyes_" + word], tw, th)
        if ph is None:
            raise SystemExit(f"{SET['eyes_' + word].name}: глаза не влезают")
        sl.paste(B.framed(ph, "rect", 14), x - 26, y + 60 - 26)
    return sl


def slide_letters() -> Slide:
    sl = Slide("letters")
    sl.text(540, 400, "write down", 84, 800)
    sl.text(540, 505, "your 3 letters", 84, 800)
    sl.text(540, 655, "hair + undertone + eyes", 48, 500, fill=GREY)
    # три буквы примера крупно
    for k, ch in enumerate("ABC"):
        cx = 360 + k * 180
        sl.d.rounded_rectangle(((cx - 72) * SS, 790 * SS, (cx + 72) * SS, 934 * SS), radius=28 * SS,
                               fill=FRAME["letters"])
        sl.text(cx, 824, ch, 84, 800, fill=(255, 255, 255))
    sl.d.rounded_rectangle((150 * SS, 1010 * SS, 930 * SS, 1290 * SS), radius=34 * SS, fill=(244, 244, 246))
    sl.text(540, 1050, "example:", 42, 700)
    sl.text(540, 1122, "ABC = black hair,", 42, 500)
    sl.text(540, 1190, "neutral undertone, dark eyes", 42, 500)
    sl.text(540, 1390, "swipe to find your season →", 50, 800)
    return sl


def season_photo(src: Path, dia: int) -> Image.Image:
    ph = C.frame_centered(src, dia, dia, C.CIRCLE_FIT)
    if ph is None:
        raise SystemExit(f"{src.name}: не годится для круга")
    return shaped(ph)


def slide_seasons(k: int) -> Slide:
    sl = Slide()
    dia, row_h, y0 = 236, 336, 205
    for j, (codes, name, star, key) in enumerate(SEASONS[k]):
        y = y0 + j * row_h
        sl.paste(season_photo(SET[key], dia), 150, y + 30)
        tx = 418
        sl.text(tx, y + 6, codes, 30, 800, anchor="l")
        sl.text(tx, y + 50, name, 48, 800, anchor="l")
        sl.text(tx, y + 110, f"like {star}", 30, 400, fill=GREY, anchor="l")
        cols = PALETTES[key]
        d, g = 52, 12
        for i, c in enumerate(cols):
            sl.circle(tx + d / 2 + (i % 8) * (d + g), y + 178 + (i // 8) * (d + g), d, hexrgb(c))
        sl.text(tx + (8 * d + 7 * g) / 2, y + 282, "your colors", 26, 400, fill=GREY)
    return sl


def screen(path: Path, w: int) -> Image.Image:
    im = Image.open(path).convert("RGB")
    im = im.resize((w, round(im.height * w / im.width)), Image.Resampling.LANCZOS)
    return shaped(im, circle=False, radius=w * 0.09, shadow=True)


def slide_inspoy() -> Slide:
    sl = Slide()
    sl.text(540, 236, "i did my full color analysis", 50, 800)
    sl.text(540, 306, "in Inspoy: Outfit Maker, Planner", 50, 800)
    sl.text(540, 410, "it scans your face", 42, 500, fill=GREY)
    sl.text(540, 468, "and picks the colors for you", 42, 500, fill=GREY)
    scan, result = SET["screens"]
    w = 372
    a, b = screen(scan, w), screen(result, w)
    sl.paste(a, 540 - 12 - w - 30, 600 - 30)
    sl.paste(b, 540 + 12 - 30, 600 - 30)
    return sl


def build_all() -> list[tuple[Image.Image, list]]:
    return [s.render() for s in (slide_cover(), slide_hair(), slide_undertone(), slide_eyes(), slide_letters(),
                                 slide_seasons(0), slide_seasons(1), slide_seasons(2), slide_inspoy())]


# ---------------- библиотека и партия ----------------
SCREEN_SETS = [("IMG_7748.PNG", "IMG_7749.PNG"), ("IMG_7784.PNG", "IMG_7785.PNG"), ("IMG_7818.PNG", "IMG_7819.PNG")]


def lib_files(slot: str) -> list:
    if slot == "screens":
        return [tuple(SCREENS / n for n in pair) for pair in SCREEN_SETS]
    return sorted(f for f in (LIB / slot).iterdir() if f.suffix.lower() in EXTS)


def plan_lib(n: int, seed: int) -> list[dict]:
    """n уникальных наборов: в каждом слоте — реже всего использованная картинка (с шумом); обложка — звезда не
    тем же фото, что у неё в сезонах; вариант текста обложки чередуется."""
    rng = random.Random(seed)
    lib = {sl: lib_files(sl) for sl in SLOTS}
    empty = [sl for sl, v in lib.items() if not v]
    if empty:
        raise SystemExit(f"пустые слоты: {empty}")
    use: dict = {}
    seen, out = set(), []
    for i in range(n):
        for _try in range(500):
            pick = {sl: min(lib[sl], key=lambda f: use.get(f, 0) + rng.random() * 0.9) for sl in SLOTS if sl != "cover"}
            used = set(pick.values())
            pick["cover"] = min((f for f in lib["cover"] if f not in used),
                                key=lambda f: use.get(f, 0) + rng.random() * 0.9)
            key = tuple(pick[sl] for sl in SLOTS) + (i % 2,)
            if key not in seen:
                break
        else:
            raise SystemExit("не хватает уникальных комбинаций")
        seen.add(key)
        for f in pick.values():
            use[f] = use.get(f, 0) + 1
        out.append({**pick, "variant": i % 2})
    return out


def apply(pick: dict) -> None:
    SET.clear()
    SET.update({k: v for k, v in pick.items() if k != "variant"})
    VARIANT[0] = pick.get("variant", 0)


def save(i: int, out: Path, flat: Path | None, qa: bool = False) -> None:
    d = out / f"{i:03d}"
    d.mkdir(parents=True, exist_ok=True)
    sheet = []
    for k, (im, boxes) in enumerate(build_all(), 1):
        for b in boxes:
            bad = check_box(W, H, b)
            if bad:
                raise SystemExit(f"{i:03d} слайд {k}: текст вне безопасной зоны {b} — {bad}")
        im.save(d / f"{k}.jpg", quality=95)
        if flat:
            im.save(flat / f"sort_{k}_{i}_1384.jpg", quality=95)
        if qa:
            q = draw_overlay(im.copy())
            dr = ImageDraw.Draw(q)
            for b in boxes:
                dr.rectangle(b, outline=(255, 200, 0), width=3)
            sheet.append(q.resize((270, 480)))
    if qa:
        s = Image.new("RGB", (270 * len(sheet), 480), "white")
        for k, q in enumerate(sheet):
            s.paste(q, (k * 270, 0))
        s.save(out / f"_qa_{i:03d}.jpg", quality=86)


def render_one(job: tuple) -> str:
    i, pick, out, flat = job
    apply({k: (tuple(Path(x) for x in v) if isinstance(v, list) else (Path(v) if isinstance(v, str) else v))
           for k, v in pick.items()})
    save(i, Path(out), Path(flat) if flat else None)
    return f"{i:03d}"


def render_cover(job: tuple) -> str:
    """Только слайд 1 (обложка) уже готовой карусели — остальные слайды не трогаем."""
    i, cover, variant, out, flat = job
    SET.clear()
    SET["cover"] = Path(cover)
    VARIANT[0] = variant
    im, boxes = slide_cover().render()
    for bx in boxes:
        bad = check_box(W, H, bx)
        if bad:
            raise SystemExit(f"{i:03d} обложка: текст вне безопасной зоны {bx} — {bad}")
    im.save(Path(out) / f"{i:03d}" / "1.jpg", quality=95)
    if flat:
        im.save(Path(flat) / f"sort_1_{i}_1384.jpg", quality=95)
    return f"{i:03d}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="одна карусель + QA-лист → output/carousels_1384_test")
    ap.add_argument("--variant", type=int, default=0)
    ap.add_argument("-n", type=int, default=0)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "carousels_1384")
    ap.add_argument("--flat", type=Path)
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--seed", type=int, default=1384)
    ap.add_argument("--covers-only", action="store_true",
                    help="перераздать обложки из output/1384_lib/cover по готовой партии (manifest.json) и "
                         "перерисовать только слайд 1")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if args.test:
        pick = plan_lib(1, args.seed)[0]
        pick["variant"] = args.variant
        apply(pick)
        OUT_TEST.mkdir(parents=True, exist_ok=True)
        save(1 + args.variant, OUT_TEST, None, qa=True)
        print("готово →", OUT_TEST)
        return 0
    if args.covers_only:
        man_path = args.out / "manifest.json"
        man = json.loads(man_path.read_text(encoding="utf-8"))
        covers = lib_files("cover")
        rng = random.Random(args.seed)
        use: dict = {}
        jobs = []
        for i, row in enumerate(man, 1):
            f = min(covers, key=lambda f: use.get(f, 0) + rng.random() * 0.9)
            use[f] = use.get(f, 0) + 1
            row["cover"] = f.name
            jobs.append((i, str(f), row.get("variant", 0), str(args.out), str(args.flat) if args.flat else None))
        man_path.write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"обложки: {len(covers)} фото, повторов {min(use.values())}–{max(use.values())}")
        with ProcessPoolExecutor(args.jobs) as ex:
            for k, name in enumerate(ex.map(render_cover, jobs), 1):
                print(f"[{k}/{len(jobs)}] {name}", flush=True)
        print(f"готово: обложки {len(jobs)} → {args.out}")
        return 0
    picks = plan_lib(args.n, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.flat:
        args.flat.mkdir(parents=True, exist_ok=True)
    (args.out / "manifest.json").write_text(json.dumps(
        [{"carousel": f"{i:03d}", **{k: ([x.name for x in v] if isinstance(v, tuple) else
                                         (v.name if isinstance(v, Path) else v)) for k, v in p.items()}}
         for i, p in enumerate(picks, 1)], indent=1, ensure_ascii=False), encoding="utf-8")
    for sl in SLOTS:
        c = Counter(str(p[sl]) for p in picks)
        print(f"{sl}: {len(c)} картинок, повторов {min(c.values())}–{max(c.values())}")
    jobs = [(i, {k: ([str(x) for x in v] if isinstance(v, tuple) else (str(v) if isinstance(v, Path) else v))
                 for k, v in p.items()}, str(args.out), str(args.flat) if args.flat else None)
            for i, p in enumerate(picks, 1)]
    with ProcessPoolExecutor(args.jobs) as ex:
        for k, name in enumerate(ex.map(render_one, jobs), 1):
            print(f"[{k}/{len(jobs)}] {name}", flush=True)
    print(f"готово: {len(jobs)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
