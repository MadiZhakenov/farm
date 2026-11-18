#!/usr/bin/env python3
"""
«Скриншот» iOS 26 Телефон → Недавние (тёмная тема), сверено с реальным скрином iOS 26 (Classic):
кнопки-капсулы Edit / All·Missed / фильтр, крупный заголовок, поиск, строки с аватаром (фото / инициалы / здание),
стрелка ↗ исходящий / ↙ входящий + подпись, время, кнопка ⓘ в круге, плавающая панель вкладок.
Ширина 1080 (скрин iPhone, ужатый), высота 2338.

  python render_ios_recents.py --out recents.png [--clock 9:47] [--face фото.jpg]
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
TT = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf"
ICONS = r"C:\Windows\Fonts\SegoeIcons.ttf"
W, H, SS = 1080, 2338, 2
C_TEXT, C_GRAY, C_BLUE, C_RED = (255, 255, 255), (142, 142, 147), (10, 132, 255), (255, 69, 58)
C_BTN, C_SEP = (38, 38, 40), (40, 40, 43)
# имя, повторы, подпись, время, пропущенный, исходящий, аватар: "face" / "mono" / "building"
CALLS = [
    ("Grandma", 14, "home", "9:41 PM", False, True, "face"),
    ("Mrs. Patterson", 0, "mobile", "9:12 PM", False, True, "mono"),
    ("Linda (next door)", 0, "mobile", "9:05 PM", False, True, "mono"),
    ("Mr. Henderson", 0, "home", "8:58 PM", False, True, "mono"),
    ("Grandma", 6, "home", "Yesterday", False, True, "face"),
    ("Mom", 0, "mobile", "Yesterday", True, False, "mono"),
    ("Grandma", 0, "mobile", "Sunday", False, False, "face"),
    ("Work", 0, "work", "Friday", False, False, "building"),
]


def font(px: float, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(TT / f"TikTokSans12pt-{weight}.ttf"), round(px * SS))


def text(d: ImageDraw.ImageDraw, x: float, y: float, s: str, px: float, weight: str = "Regular", fill=C_TEXT,
         anchor: str = "ls") -> float:
    f = font(px, weight)
    d.text((x * SS, y * SS), s, font=f, fill=fill, anchor=anchor)
    return f.getlength(s) / SS


def glyph(ch: str, px: float, fill) -> Image.Image:
    f = ImageFont.truetype(ICONS, round(px * SS))
    l, t, r, b = f.getbbox(ch)
    m = Image.new("L", (r - l + 4, b - t + 4), 0)
    ImageDraw.Draw(m).text((2 - l, 2 - t), ch, font=f, fill=255)
    out = Image.new("RGBA", m.size, fill + (0,))
    out.putalpha(m)
    return out


def paste_c(img: Image.Image, el: Image.Image, cx: float, cy: float) -> None:
    img.alpha_composite(el, (round(cx * SS - el.width / 2), round(cy * SS - el.height / 2)))


def capsule(d: ImageDraw.ImageDraw, x0, y0, x1, y1, fill) -> None:
    d.rounded_rectangle((x0 * SS, y0 * SS, x1 * SS, y1 * SS), radius=(y1 - y0) / 2 * SS, fill=fill)


def arrow(d: ImageDraw.ImageDraw, x: float, y: float, out_call: bool) -> None:
    """↗ исходящий / ↙ входящий — тонкая серая стрелка перед подписью."""
    s, k = SS, 13
    if out_call:
        a, b = (x - k, y + k), (x + k, y - k)
        head = [(x + k - 13, y - k), (x + k, y - k), (x + k, y - k + 13)]
    else:
        a, b = (x + k, y - k), (x - k, y + k)
        head = [(x - k + 13, y + k), (x - k, y + k), (x - k, y + k - 13)]
    d.line((a[0] * s, a[1] * s, b[0] * s, b[1] * s), fill=C_GRAY, width=4 * s)
    d.line([(p * s, q * s) for p, q in head], fill=C_GRAY, width=4 * s, joint="curve")


def mono_avatar(initials: str, dia: int) -> Image.Image:
    n = dia * SS
    g = np.linspace(0, 1, n)[:, None]
    top, bot = np.array([165, 169, 182]), np.array([112, 117, 132])
    rgb = (top + (bot - top) * g[..., None]).repeat(n, axis=1).astype(np.uint8)
    im = Image.fromarray(rgb, "RGB").convert("RGBA")
    m = Image.new("L", (n, n), 0)
    ImageDraw.Draw(m).ellipse((0, 0, n - 1, n - 1), fill=255)
    im.putalpha(m)
    ImageDraw.Draw(im).text((n / 2, n / 2 + n * 0.02), initials, font=font(dia * 0.42, "SemiBold"),
                            fill=C_TEXT, anchor="mm")
    return im


def face_avatar(face: Path, dia: int) -> Image.Image:
    n = dia * SS
    im = Image.open(face).convert("RGB")
    side = min(im.size)
    im = im.crop(((im.width - side) // 2, (im.height - side) // 2, (im.width + side) // 2, (im.height + side) // 2))
    im = im.resize((n, n), Image.Resampling.LANCZOS).convert("RGBA")
    m = Image.new("L", (n, n), 0)
    ImageDraw.Draw(m).ellipse((0, 0, n - 1, n - 1), fill=255)
    im.putalpha(m)
    return im


def building_avatar(dia: int) -> Image.Image:
    n = dia * SS
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, n - 1, n - 1), radius=n * 0.22, fill=(108, 124, 170))
    bw, bh = n * 0.36, n * 0.56
    x0, y0 = n / 2 - bw / 2, n / 2 - bh / 2
    d.rectangle((x0, y0, x0 + bw, y0 + bh), fill=(235, 238, 248))
    for r in range(4):
        for c in range(2):
            wx, wy = x0 + bw * (0.22 + c * 0.38), y0 + bh * (0.1 + r * 0.21)
            d.rectangle((wx, wy, wx + bw * 0.2, wy + bh * 0.12), fill=(108, 124, 170))
    return im


def initials(name: str) -> str:
    words = [w for w in name.replace("(", " ").replace(")", " ").split() if w[0].isalpha()]
    words = [w for w in words if w.rstrip(".") not in ("Mrs", "Mr", "Ms", "next", "door")] or words
    return "".join(w[0] for w in words[:2]).upper()


def status_bar(img: Image.Image, d: ImageDraw.ImageDraw, clock: str) -> None:
    s = SS
    text(d, 108, 92, clock, 50, "SemiBold")
    x, y = 820, 58                                       # сигнал
    for i, h in enumerate((12, 18, 24, 30)):
        d.rounded_rectangle(((x + i * 15) * s, (y + 30 - h) * s, (x + i * 15 + 10) * s, (y + 30) * s), radius=2 * s,
                            fill=C_TEXT)
    wx, wy = x + 98, y + 34                              # wi-fi
    for r, wd in ((34, 7), (22, 7), (9, 9)):
        d.arc(((wx - r) * s, (wy - r - 6) * s, (wx + r) * s, (wy + r - 6) * s), 225, 315, fill=C_TEXT, width=wd * s)
    bx = x + 140                                         # батарея с процентом
    d.rounded_rectangle((bx * s, (y - 1) * s, (bx + 68) * s, (y + 33) * s), radius=10 * s, fill=C_TEXT)
    d.rounded_rectangle(((bx + 70) * s, (y + 10) * s, (bx + 75) * s, (y + 22) * s), radius=2 * s, fill=(160, 160, 164))
    text(d, bx + 34, y + 27, "86", 27, "Bold", (0, 0, 0), "ms")


def tab_bar(img: Image.Image) -> None:
    """Плавающая «стеклянная» капсула вкладок; Recents выделен."""
    s = SS
    y0, y1, x0, x1 = 2124, 2290, 36, 1044
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x0 * s, (y0 + 6) * s, x1 * s, (y1 + 6) * s), radius=83 * s, fill=(0, 0, 0, 160))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14 * s)))
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.rounded_rectangle((x0 * s, y0 * s, x1 * s, y1 * s), radius=83 * s, fill=(28, 28, 30, 236),
                        outline=(58, 58, 62, 255), width=2 * s)
    tabs = ["Favorites", "Recents", "Contacts", "Keypad", "Voicemail"]
    step = (x1 - x0 - 30) / len(tabs)
    for k, name in enumerate(tabs):
        cx = x0 + 15 + step * (k + 0.5)
        sel = name == "Recents"
        col = C_BLUE if sel else C_TEXT
        if sel:
            d.rounded_rectangle(((cx - step / 2 + 6) * s, (y0 + 12) * s, (cx + step / 2 - 6) * s, (y1 - 12) * s),
                                radius=70 * s, fill=(58, 58, 62, 255))
        iy = y0 + 64
        if name == "Favorites":
            pts = [(cx + 30 * math.cos(math.radians(-90 + 36 * i)) * (1 if i % 2 == 0 else 0.46),
                    iy + 30 * math.sin(math.radians(-90 + 36 * i)) * (1 if i % 2 == 0 else 0.46)) for i in range(10)]
            d.polygon([(px * s, py * s) for px, py in pts], fill=col)
        elif name == "Recents":
            d.ellipse(((cx - 29) * s, (iy - 29) * s, (cx + 29) * s, (iy + 29) * s), fill=col)
            d.line((cx * s, (iy - 17) * s, cx * s, (iy + 1) * s, (cx - 12) * s, (iy + 1) * s), fill=(58, 58, 62),
                   width=5 * s, joint="curve")
        elif name == "Contacts":
            d.ellipse(((cx - 29) * s, (iy - 29) * s, (cx + 29) * s, (iy + 29) * s), fill=col)
            d.ellipse(((cx - 10) * s, (iy - 20) * s, (cx + 10) * s, (iy + 0) * s), fill=(28, 28, 30))
            d.chord(((cx - 21) * s, (iy + 4) * s, (cx + 21) * s, (iy + 40) * s), 180, 360, fill=(28, 28, 30))
            m = Image.new("L", lay.size, 0)
            ImageDraw.Draw(m).ellipse(((cx - 29) * s, (iy - 29) * s, (cx + 29) * s, (iy + 29) * s), fill=255)
        elif name == "Keypad":
            for r in range(4):
                for c in range(3):
                    if r == 3 and c != 1:
                        continue
                    x, y = cx + (c - 1) * 19, iy - 27 + r * 17
                    d.ellipse(((x - 7) * s, (y - 7) * s, (x + 7) * s, (y + 7) * s), fill=col)
        else:
            for dx in (-18, 18):
                d.ellipse(((cx + dx - 14) * s, (iy - 14) * s, (cx + dx + 14) * s, (iy + 14) * s), outline=col, width=5 * s)
            d.line(((cx - 18) * s, (iy + 12) * s, (cx + 18) * s, (iy + 12) * s), fill=col, width=5 * s)
        d.text((cx * s, (y0 + 132) * s), name, font=font(27, "Medium"), fill=col, anchor="ms")
    img.alpha_composite(lay)
    ImageDraw.Draw(img).rounded_rectangle(((W / 2 - 150) * s, (H - 26) * s, (W / 2 + 150) * s, (H - 14) * s),
                                          radius=6 * s, fill=C_TEXT)


def render(out: Path, clock: str, face: Path | None) -> Path:
    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 255))
    d = ImageDraw.Draw(img)
    status_bar(img, d, clock)
    # верхний ряд: Edit · All/Missed · фильтр
    capsule(d, 36, 156, 212, 252, C_BTN)
    text(d, 124, 218, "Edit", 46, "Regular", C_TEXT, "ms")
    capsule(d, 318, 156, 762, 252, C_BTN)
    capsule(d, 326, 164, 532, 244, (72, 72, 76))
    text(d, 429, 218, "All", 46, "Regular", C_TEXT, "ms")
    text(d, 645, 218, "Missed", 46, "Regular", C_TEXT, "ms")
    d.ellipse(((1044 - 96) * SS, 156 * SS, 1044 * SS, 252 * SS), fill=C_BTN)
    for k, half in enumerate((24, 18, 11)):
        yy = 186 + k * 18
        d.line(((996 - half) * SS, yy * SS, (996 + half) * SS, yy * SS), fill=C_TEXT, width=5 * SS)
    text(d, 46, 392, "Recents", 96, "Bold")
    # поиск
    capsule(d, 36, 432, 1044, 544, (28, 28, 30))
    paste_c(img, glyph("\ue721", 44, C_GRAY), 98, 488)
    text(d, 144, 505, "Search", 50, "Regular", C_GRAY)
    paste_c(img, glyph("\ue720", 44, C_GRAY), 990, 488)
    # строки
    y, row, dia = 588, 202, 136
    for name, n, sub, when, missed, out_call, av in CALLS:
        cy = y + row / 2
        if av == "face" and face:
            a = face_avatar(face, dia)
        elif av == "building":
            a = building_avatar(dia)
        else:
            a = mono_avatar(initials(name), dia)
        paste_c(img, a, 108, cy)
        label = f"{name} ({n})" if n else name
        text(d, 206, cy - 8, label, 54, "Medium", C_RED if missed else C_TEXT)
        arrow(d, 222, cy + 40, out_call)
        text(d, 252, cy + 56, sub, 48, "Regular", C_GRAY)
        tw = font(48).getlength(when) / SS
        text(d, 908 - tw, cy + 18, when, 48, "Regular", C_GRAY)
        d.ellipse(((990 - 52) * SS, (cy - 52) * SS, (990 + 52) * SS, (cy + 52) * SS), fill=C_BTN)
        paste_c(img, glyph("\ue946", 50, C_BLUE), 990, cy)
        d.line((206 * SS, (y + row) * SS, 1044 * SS, (y + row) * SS), fill=C_SEP, width=2 * SS)
        y += row
    tab_bar(img)
    img = img.resize((W, H), Image.Resampling.LANCZOS).convert("RGB")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "1343_slides" / "_recents" / "recents.png")
    ap.add_argument("--clock", default="9:47")
    ap.add_argument("--face", type=Path, help="фото контакта Grandma (квадратный кроп лица)")
    a = ap.parse_args()
    print(render(a.out, a.clock, a.face))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
