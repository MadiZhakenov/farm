#!/usr/bin/env python3
"""
1323 — доски-коллажи «как на рефе» (@alikillpack: большие разборы на кремовом фоне) из НАСТОЯЩИХ результатов
Inspoy по её селфи (скрины downloads/1323/screens2, 1170×2532). Всё, что можно, рисуем сами (карточки, палитры,
подписи); из скринов берём только точно вырезанные картинки: её лицо в примерках, плитки цветов волос, иконки
макияжа, ногти. Тексты результатов — дословно из приложения. Весь текст досок — внутри безопасной рамки 3:4
(x 180–900, y до 78 %); фон и фото могут выходить за неё.

  b1 «My Face & Color Analysis» — селфи + 5 выводов + подтон кожи (палитра) + пояснение приложения;
  b2 «My Hair Guide» — 3 примерки причёсок/цвета на ней + цвета волос «идут» / «избегать»;
  b3 «My Makeup & Nails» — примерка макияжа + палитра (губы/глаза/кожа) + оттенки и формы ногтей.

  python build_1323_boards.py            → output/1323_slides/boards/b1.jpg … b3.jpg
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import text_rect  # noqa: E402

W, H = 1080, 1440
X0, Y0, X1, Y1 = text_rect(W, H)                      # 180, 86, 900, 1123
P = ROOT / "downloads" / "1323" / "screens2"
SELFIE = P / "Young_woman_smiling_for_selfie_20261023111650.jpg"
OUT = ROOT / "output" / "1323_slides" / "boards"
BG, CARD, LINE = (245, 240, 233), (255, 253, 250), (228, 220, 210)
INK, MUTED, GOLD, OK, NO = (38, 32, 28), (128, 116, 106), (184, 150, 96), (86, 140, 84), (196, 84, 70)
# цветовые темы досок (у каждой карусели своя): фон, карточка, линия, текст, приглушённый, акцент
THEMES = {
    "cream": ((245, 240, 233), (255, 253, 250), (228, 220, 210), (38, 32, 28), (128, 116, 106), (184, 150, 96)),
    "blush": ((248, 232, 232), (255, 249, 249), (236, 214, 214), (60, 36, 40), (150, 110, 115), (214, 128, 140)),
    "sage": ((232, 239, 228), (250, 253, 248), (212, 224, 206), (34, 48, 36), (104, 124, 104), (122, 154, 108)),
    "lavender": ((237, 233, 246), (252, 250, 255), (222, 214, 238), (44, 36, 66), (120, 110, 150), (150, 124, 206)),
    "sky": ((230, 239, 247), (250, 252, 255), (210, 224, 238), (30, 44, 62), (100, 120, 146), (96, 140, 196)),
    "butter": ((248, 242, 222), (255, 253, 245), (236, 226, 196), (54, 44, 24), (138, 122, 90), (206, 166, 64)),
    "mocha": ((232, 220, 208), (247, 240, 233), (214, 198, 184), (52, 36, 28), (128, 104, 90), (150, 104, 74)),
    "peach": ((252, 234, 222), (255, 250, 246), (240, 214, 198), (66, 40, 30), (156, 114, 96), (232, 138, 100)),
}


def apply_theme(name: str) -> None:
    global BG, CARD, LINE, INK, MUTED, GOLD
    BG, CARD, LINE, INK, MUTED, GOLD = THEMES[name]


SERIF = ROOT / "fonts" / "serif" / "Newsreader[opsz,wght].ttf"
INTER = ROOT / "fonts" / "inter"
SS = 2                                                # рисуем ×2, потом уменьшаем — ровные края


def serif(px: float, wght: int = 600, italic: bool = False) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(SERIF), round(px * SS))
    f.set_variation_by_axes([wght, min(72, px)])
    return f


def sans(px: float, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(INTER / ("Inter-SemiBold.ttf" if bold else "Inter-Regular.ttf")), round(px * SS))


def scr(n: str, box: tuple[int, int, int, int]) -> Image.Image:
    return Image.open(P / f"IMG_{n}.PNG").convert("RGB").crop(box)


class Board:
    def __init__(self) -> None:
        self.im = Image.new("RGBA", (W * SS, H * SS), BG + (255,))
        self.d = ImageDraw.Draw(self.im)

    def s(self, *v: float) -> tuple:
        return tuple(round(x * SS) for x in v)

    def sparkle(self, cx: float, cy: float, r: float, color=None) -> None:
        color = color or GOLD
        pts = []
        for k in range(8):
            ang = math.pi / 4 * k - math.pi / 2
            rr = r if k % 2 == 0 else r * 0.28
            pts.append(((cx + rr * math.cos(ang)) * SS, (cy + rr * math.sin(ang)) * SS))
        self.d.polygon(pts, fill=color)

    def title(self, text: str, sub: str, y: float = 96) -> None:
        f = serif(50)
        tw = self.d.textlength(text, font=f) / SS
        self.d.text(self.s(W / 2, y), text, font=f, fill=INK, anchor="mt")
        self.sparkle(W / 2 - tw / 2 - 30, y + 26, 13)
        self.sparkle(W / 2 + tw / 2 + 30, y + 26, 13)
        self.d.text(self.s(W / 2, y + 70), sub.upper(), font=sans(17, True), fill=MUTED, anchor="mt")

    def label(self, x: float, y: float, text: str, color=None, anchor: str = "lt") -> None:
        color = color or MUTED
        self.d.text(self.s(x, y), text.upper(), font=sans(17, True), fill=color, anchor=anchor)

    def photo(self, im: Image.Image, box: tuple[float, float, float, float], r: float = 26, border: float = 0) -> None:
        x0, y0, x1, y1 = box
        w, h = round((x1 - x0) * SS), round((y1 - y0) * SS)
        ph = im.convert("RGB").resize((w, h), Image.Resampling.LANCZOS).convert("RGBA")
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), radius=round(r * SS), fill=255)
        ph.putalpha(m)
        pad = round(30 * SS)
        sh = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
        sh.paste(m, (pad, pad + round(8 * SS)))
        sh = sh.filter(ImageFilter.GaussianBlur(14 * SS)).point(lambda v: int(v * 0.20))
        layer = Image.new("RGBA", sh.size, (70, 50, 40, 0))
        layer.putalpha(sh)
        self.im.alpha_composite(layer, (round(x0 * SS) - pad, round(y0 * SS) - pad))
        if border:
            self.d.rounded_rectangle(self.s(x0 - border, y0 - border, x1 + border, y1 + border),
                                     radius=round((r + border) * SS), fill=CARD)
        self.im.alpha_composite(ph, (round(x0 * SS), round(y0 * SS)))

    def card(self, box: tuple[float, float, float, float], r: float = 20) -> None:
        self.d.rounded_rectangle(self.s(*box), radius=round(r * SS), fill=CARD, outline=LINE, width=round(1.5 * SS))

    def wrap(self, text: str, f, max_w: float) -> list[str]:
        lines, cur = [], ""
        for wd in text.split():
            cand = f"{cur} {wd}".strip()
            if cur and self.d.textlength(cand, font=f) / SS > max_w:
                lines.append(cur)
                cur = wd
            else:
                cur = cand
        return lines + [cur]

    def save(self, path: Path) -> None:
        self.im.resize((W, H), Image.Resampling.LANCZOS).convert("RGB").save(path, quality=95)


def circle_crop(im: Image.Image, cx: int, cy: int, r: int) -> Image.Image:
    c = im.crop((cx - r, cy - r, cx + r, cy + r)).convert("RGBA")
    m = Image.new("L", (8 * r, 8 * r), 0)
    ImageDraw.Draw(m).ellipse((0, 0, 8 * r - 1, 8 * r - 1), fill=255)
    c.putalpha(m.resize((2 * r, 2 * r), Image.Resampling.LANCZOS))
    return c


def hair_tiles(n: str, y0: int) -> list[Image.Image]:
    """Три плитки цвета волос (с подписями приложения), границы — по белому фону карточки."""
    a = np.asarray(Image.open(P / f"IMG_{n}.PNG").convert("RGB")).astype(int)
    out = []
    for x0, x1 in ((84, 414), (420, 750), (756, 1086)):
        frac = (np.abs(a[:, x0 + 20:x1 - 20] - 255).sum(2) > 30).mean(1)     # доля не-белого по строке плитки
        top = next(y for y in range(y0 - 60, y0 + 60) if frac[y] > 0.5)
        bot = next(y for y in range(top + 100, top + 500) if frac[y] < 0.5)
        out.append(Image.open(P / f"IMG_{n}.PNG").convert("RGB").crop((x0 + 2, top + 2, x1 - 2, bot - 2)))
    return out


TRYON = (190, 455, 960, 1482)                         # её лицо в примерке, без значка inspoy и кнопки сравнения
TRYON_SQ = (190, 455, 960, 1340)                      # то же, ниже обрезано (1 : 1.15)


def fit(path: Path, aspect: float) -> Image.Image:
    """Фото → кадр нужных пропорций (w/h) по центру, чуть выше середины (лица)."""
    from PIL import ImageOps
    im = Image.open(path).convert("RGB")
    w = min(im.width, round(im.height * aspect))
    return ImageOps.fit(im, (w, round(w / aspect)), Image.Resampling.LANCZOS, centering=(0.5, 0.4))


def board1(selfie_path: Path | None = None, rng=None) -> Board:
    b = Board()
    b.title("My Face & Color Analysis", "made from one selfie in inspoy")
    selfie = fit(selfie_path, 3 / 4) if selfie_path else Image.open(SELFIE).convert("RGB").crop((48, 30, 848, 1097))
    b.photo(selfie, (X0, 220, X0 + 300, 620), r=28)
    y = 220
    chips = [("Face shape", "Oval"), ("Hair", "Straight · Dense"), ("Skin undertone", "Neutral-Warm"),
             ("Contrast level", "Low"), ("Color season", "Light Spring")]
    if rng:
        rng.shuffle(chips)
    for lab, val in chips:
        b.card((X0 + 320, y, X1, y + 72), 16)
        b.d.text(b.s(X0 + 340, y + 12), lab.upper(), font=sans(14, True), fill=MUTED)
        b.d.text(b.s(X0 + 340, y + 32), val, font=serif(27), fill=INK)
        y += 82
    b.label(X0, 660, "My skin undertone · Neutral-Warm")
    cols = [(255, 222, 197), (251, 210, 188), (236, 198, 159), (234, 184, 151), (212, 158, 124)]
    sw, gap = 128, (X1 - X0 - 5 * 128) / 4
    circles = bool(rng and rng.random() < 0.5)
    for k, c in enumerate(cols):
        x = X0 + k * (sw + gap)
        b.d.rounded_rectangle(b.s(x, 695, x + sw, 695 + sw), radius=round((sw / 2 if circles else 22) * SS), fill=c,
                              outline=LINE, width=round(1.5 * SS))
    b.d.text(b.s(X0, 863), "“", font=serif(70), fill=GOLD)
    quote = "Your complexion leans warm and peachy. Your veins are likely green in daylight, " \
            "and gold suits you more than silver"
    f = serif(27, 450)
    yy = 875
    for ln in b.wrap(quote, f, X1 - X0 - 50):
        b.d.text(b.s(X0 + 46, yy), ln, font=f, fill=INK)
        yy += 38
    b.d.text(b.s(X0 + 46, yy + 6), "— Inspoy, why this is you", font=sans(16), fill=MUTED)
    return b


def board2(tryons: list[tuple[Path, str]] | None = None, rng=None) -> Board:
    b = Board()
    b.title("My Hair Guide", "tried on my own face in inspoy")
    tw = (X1 - X0 - 2 * 20) / 3
    ph = tw * 1.15
    items = tryons or [(None, n, lab) for n, lab in (("7733", "Soft shoulder bob"), ("7734", "High ponytail"),
                                                     ("7738", "Ash blonde"))]
    items = [it if len(it) == 3 else (it[0], None, it[1]) for it in items]
    if rng:
        rng.shuffle(items)
    pw = (X1 - X0 - 20 * (len(items) - 1)) / len(items)  # 2 или 3 примерки в ряд
    ph = pw * 1.15
    for k, (path, n, lab) in enumerate(items):
        x = X0 + k * (pw + 20)
        b.photo(fit(path, 1 / 1.15) if path else scr(n, TRYON_SQ), (x, 215, x + pw, 215 + ph), r=22)
        b.d.text(b.s(x + pw / 2, 225 + ph), lab, font=sans(18), fill=INK, anchor="mt")
    y = 215 + ph + 58
    for title, n, y0, color in (("Hair colors that suit me", "7725", 1245, OK), ("Colors to avoid", "7737", 1280, NO)):
        b.label(X0, y, title, color)
        tiles = hair_tiles(n, y0)
        if rng:
            rng.shuffle(tiles)
        th = tw * tiles[0].height / tiles[0].width
        for k, tile in enumerate(tiles):
            x = X0 + k * (tw + 20)
            b.photo(tile, (x, y + 32, x + tw, y + 32 + th), r=18)
        y += 32 + th + 36
    return b


def board3(makeup_path: Path | None = None, rng=None) -> Board:
    b = Board()
    b.title("My Makeup & Nails", "my palette for a light spring")
    b.photo(fit(makeup_path, 285 / 380) if makeup_path else scr("7735", TRYON), (X0, 215, X0 + 285, 215 + 380), r=24)
    b.d.text(b.s(X0 + 142, 605), "Soft glam try-on", font=sans(17), fill=INK, anchor="mt")
    src = Image.open(P / "IMG_7728.PNG").convert("RGB")
    rows = (("Lips", 1334, "Soft peach, warm nude, and light coral-pink shades"),
            ("Eyes", 1651, "Warm champagne, light warm taupe, and subtle bronze shades"),
            ("Skin", 1986, "Light peach foundations, soft apricot blushes, and warm champagne highlighters"))
    rows = list(rows)
    if rng:
        rng.shuffle(rows)
    x = X0 + 305
    y = 215
    for lab, cy, text in rows:
        b.card((x, y, X1, y + 120), 18)
        ic = circle_crop(src, 176, cy, 104).resize((round(76 * SS), round(76 * SS)), Image.Resampling.LANCZOS)
        b.im.alpha_composite(ic, b.s(x + 14, y + 22))
        b.d.text(b.s(x + 104, y + 14), lab, font=sans(19, True), fill=INK)
        f = sans(15)
        yy = y + 42
        for ln in b.wrap(text, f, X1 - x - 118)[:3]:
            b.d.text(b.s(x + 104, yy), ln, font=f, fill=MUTED)
            yy += 21
        y += 130
    b.label(X0, 660, "My nail shades")
    b.card((X0, 692, X1, 880), 20)
    nails = scr("7730", (120, 1100, 1060, 1340))
    nw = X1 - X0 - 40
    b.im.alpha_composite(nails.resize((round(nw * SS), round(nw * 240 / 940 * SS)), Image.Resampling.LANCZOS)
                         .convert("RGBA"), b.s(X0 + 20, 698))
    b.label(X0, 910, "Shapes that flatter my hands")
    b.card((X0, 942, X1, 1100), 20)
    shapes = scr("7730", (150, 1515, 1020, 1660))
    sw = X1 - X0 - 60
    b.im.alpha_composite(shapes.resize((round(sw * SS), round(sw * 145 / 870 * SS)), Image.Resampling.LANCZOS)
                         .convert("RGBA"), b.s(X0 + 30, 950))
    for lab, fx in (("Oval", 0.22), ("Squoval", 0.5), ("Almond", 0.78)):
        b.d.text(b.s(X0 + (X1 - X0) * fx, 1064), lab, font=sans(17), fill=INK, anchor="mt")
    return b


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    for k, fn in enumerate((board1, board2, board3), 1):
        fn().save(OUT / f"b{k}.jpg")
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
