#!/usr/bin/env python3
"""18 girl-aesthetic intros with REAL layout variety (not same card recolored)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.renderer import (  # noqa: E402
    _draw_tracked_text,
    _line_width,
    _text_bbox,
    stroke_width_for,
)

W, H = 1080, 1920
OUT = ROOT / "yandex_videos" / "_intro_previews"

TT_SEMI = ROOT / "fonts" / "TikTokSans-SemiBold.ttf"
TT_BOLD = ROOT / "fonts" / "TikTokSans-Bold.ttf"
TT_ITAL = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf" / "TikTokSans12pt-MediumItalic.ttf"
GEORGIA_I = Path(r"C:\Windows\Fonts\georgiai.ttf")
GEORGIA_B = Path(r"C:\Windows\Fonts\georgiab.ttf")


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size=size)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def wash(c1, c2) -> Image.Image:
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        t = (y / (H - 1)) ** 0.95
        col = lerp(c1, c2, t)
        for x in range(W):
            px[x, y] = col
    return img


def diagonal_wash(c1, c2) -> Image.Image:
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        for x in range(0, W, 2):  # slight skip ok
            t = (x / W * 0.55 + y / H * 0.45)
            t = max(0, min(1, t))
            c = lerp(c1, c2, t)
            px[x, y] = c
            if x + 1 < W:
                px[x + 1, y] = c
    return img


def blob(img, cx, cy, rx, ry, color, alpha):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(*color, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(int(min(rx, ry) * 0.5)))
    base = img.convert("RGBA")
    img.paste(Image.alpha_composite(base, layer).convert("RGB"))


def vignette(img, strength=0.22, color=(200, 120, 145)):
    sw, sh = 48, 85
    small = Image.new("L", (sw, sh), 0)
    sp = small.load()
    cx, cy = sw / 2, sh / 2
    max_r = math.hypot(cx, cy)
    for y in range(sh):
        for x in range(sw):
            t = math.hypot(x - cx, y - cy) / max_r
            sp[x, y] = int(max(0, min(255, (t - 0.4) / 0.6 * 255 * strength)))
    alpha = small.resize((W, H), Image.Resampling.LANCZOS)
    over = Image.new("RGBA", (W, H), (*color, 0))
    over.putalpha(alpha)
    base = img.convert("RGBA")
    img.paste(Image.alpha_composite(base, over).convert("RGB"))


def sparkles(img, seed, n=14):
    def rnd():
        nonlocal seed
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        return seed / 0x7FFFFFFF
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        x = int(60 + rnd() * (W - 120))
        y = int(100 + rnd() * (H - 200))
        r = 1 + int(rnd() * 2.5)
        a = int(100 + rnd() * 90)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, a))
        if rnd() > 0.65:
            d.line([x - 5, y, x + 5, y], fill=(255, 255, 255, a // 2), width=1)
            d.line([x, y - 5, x, y + 5], fill=(255, 255, 255, a // 2), width=1)
    base = img.convert("RGBA")
    img.paste(Image.alpha_composite(base, layer).convert("RGB"))


def bow(img, x, y, scale=1.0, color=(255, 185, 205, 170)):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    s = 22 * scale
    d.ellipse([x - s * 2.1, y - s * 0.85, x - s * 0.15, y + s * 0.85], fill=color)
    d.ellipse([x + s * 0.15, y - s * 0.85, x + s * 2.1, y + s * 0.85], fill=color)
    d.ellipse([x - s * 0.4, y - s * 0.4, x + s * 0.4, y + s * 0.4], fill=color)
    d.polygon([(x, y), (x - s * 1.2, y + s * 1.6), (x + s * 0.15, y + s * 0.35)], fill=color)
    d.polygon([(x, y), (x + s * 1.2, y + s * 1.6), (x - s * 0.15, y + s * 0.35)], fill=color)
    layer = layer.filter(ImageFilter.GaussianBlur(0.8))
    base = img.convert("RGBA")
    img.paste(Image.alpha_composite(base, layer).convert("RGB"))


def heart(img, x, y, s=18, color=(255, 170, 190, 160)):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([x - s, y - s * 0.6, x, y + s * 0.4], fill=color)
    d.ellipse([x, y - s * 0.6, x + s, y + s * 0.4], fill=color)
    d.polygon([(x - s, y), (x + s, y), (x, y + s * 1.15)], fill=color)
    layer = layer.filter(ImageFilter.GaussianBlur(0.7))
    base = img.convert("RGBA")
    img.paste(Image.alpha_composite(base, layer).convert("RGB"))


def hairline(img, y, half=140, color=(255, 255, 255, 160)):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.line([W / 2 - half, y, W / 2 + half, y], fill=color, width=2)
    d.ellipse([W / 2 - 3, y - 3, W / 2 + 3, y + 3], fill=color)
    base = img.convert("RGBA")
    img.paste(Image.alpha_composite(base, layer).convert("RGB"))


def draw_line(img, text, *, fnt, y, fill, stroke_fill, stroke, align="center", x_shift=0):
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    # TikTok-style black outline (user request for reels_out)
    try:
        fs = int(getattr(fnt, "size", 72) or 72)
    except (TypeError, ValueError):
        fs = 72
    stroke = max(3, stroke_width_for(fs))
    stroke_fill = (0, 0, 0)
    bb = _text_bbox(probe, (0, 0), text, fnt, stroke)
    lw = _line_width(fnt, text, stroke)
    if align == "center":
        x = W / 2 - lw / 2 + x_shift
    elif align == "left":
        x = 100 + x_shift
    else:
        x = W - 100 - lw + x_shift
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    _draw_tracked_text(
        draw, (x, y - bb[1]), text, fnt,
        fill=(*fill, 255), stroke_width=stroke, stroke_fill=(*stroke_fill, 255),
    )
    base = img.convert("RGBA")
    img.paste(Image.alpha_composite(base, layer).convert("RGB"))
    return bb[3] - bb[1]


def stamp(img, n, name):
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("arial.ttf", 26)
    except OSError:
        f = ImageFont.load_default()
    d.rectangle([0, 0, W, 52], fill=(255, 250, 252))
    d.text((20, 12), f"#{n:02d}  {name}", fill=(160, 120, 135), font=f)


# Each variant: unique layout recipe — all fonts min 72, line gap ~12
def v01(img):
    """Blush air — white TikTok + sparkles."""
    sparkles(img, 11, 18)
    f = font(TT_SEMI, 72)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.46, fill=(255, 255, 255), stroke_fill=(215, 130, 155), stroke=0)
    draw_line(img, "how I color", fnt=f, y=H * 0.46 + h1 + 12, fill=(255, 255, 255), stroke_fill=(215, 130, 155), stroke=0)


def v02(img):
    """Cream editorial — Georgia italic + bow."""
    bow(img, W / 2, H * 0.40, 1.2, (255, 175, 195, 180))
    f = font(GEORGIA_I, 72)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.46, fill=(130, 80, 90), stroke_fill=(255, 245, 245), stroke=0)
    hairline(img, H * 0.46 + h1 + 6, 100, (220, 160, 175, 140))
    draw_line(img, "how I color", fnt=f, y=H * 0.46 + h1 + 14, fill=(130, 80, 90), stroke_fill=(255, 245, 245), stroke=0)


def v03(img):
    """Lilac high — big bold upper."""
    sparkles(img, 33, 12)
    f = font(TT_BOLD, 80)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.38, fill=(255, 255, 255), stroke_fill=(170, 130, 200), stroke=0)
    draw_line(img, "how I color", fnt=f, y=H * 0.38 + h1 + 12, fill=(255, 255, 255), stroke_fill=(170, 130, 200), stroke=0)


def v04(img):
    """Peach low — lower position + heart."""
    heart(img, W / 2, H * 0.52, 16, (255, 160, 170, 150))
    f = font(TT_SEMI, 74)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.56, fill=(255, 255, 255), stroke_fill=(210, 120, 115), stroke=0)
    draw_line(img, "how I color", fnt=f, y=H * 0.56 + h1 + 12, fill=(255, 255, 255), stroke_fill=(210, 120, 115), stroke=0)


def v05(img):
    """Ballet tiny — bow + sparkles."""
    sparkles(img, 55, 22)
    bow(img, W / 2, H * 0.42, 1.0, (255, 190, 210, 140))
    f = font(TT_SEMI, 72)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.48, fill=(255, 255, 255), stroke_fill=(220, 140, 160), stroke=0)
    draw_line(img, "how I color", fnt=f, y=H * 0.48 + h1 + 12, fill=(255, 255, 255), stroke_fill=(220, 140, 160), stroke=0)


def v06(img):
    """Pearl hierarchy — bigger second line."""
    f1 = font(GEORGIA_I, 72)
    f2 = font(TT_BOLD, 82)
    h1 = draw_line(img, "lemme show you", fnt=f1, y=H * 0.44, fill=(140, 95, 100), stroke_fill=(255, 248, 245), stroke=0)
    draw_line(img, "how I color", fnt=f2, y=H * 0.44 + h1 + 10, fill=(140, 95, 100), stroke_fill=(255, 248, 245), stroke=0)


def v07(img):
    """Berry bold — vivid pink."""
    sparkles(img, 77, 10)
    f = font(TT_BOLD, 78)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.46, fill=(255, 255, 255), stroke_fill=(150, 40, 90), stroke=0)
    draw_line(img, "how I color", fnt=f, y=H * 0.46 + h1 + 12, fill=(255, 255, 255), stroke_fill=(150, 40, 90), stroke=0)


def v08(img):
    """Mauve aside — slight left shift."""
    f = font(TT_SEMI, 74)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.46, fill=(255, 250, 252), stroke_fill=(140, 95, 120), stroke=0, x_shift=-30)
    draw_line(img, "how I color", fnt=f, y=H * 0.46 + h1 + 12, fill=(255, 250, 252), stroke_fill=(140, 95, 120), stroke=0, x_shift=-30)


def v09(img):
    """Cotton italic — diagonal wash."""
    sparkles(img, 99, 16)
    f = font(TT_ITAL if TT_ITAL.exists() else TT_SEMI, 72)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.46, fill=(95, 75, 120), stroke_fill=(245, 235, 255), stroke=0)
    draw_line(img, "how I color", fnt=f, y=H * 0.46 + h1 + 12, fill=(95, 75, 120), stroke_fill=(245, 235, 255), stroke=0)


def v10(img):
    """Rosewater hearts — hearts flanking."""
    heart(img, W / 2 - 260, H * 0.48, 14, (255, 170, 190, 140))
    heart(img, W / 2 + 260, H * 0.48, 14, (255, 170, 190, 140))
    f = font(TT_SEMI, 72)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.46, fill=(145, 70, 90), stroke_fill=(255, 235, 240), stroke=0)
    draw_line(img, "how I color", fnt=f, y=H * 0.46 + h1 + 12, fill=(145, 70, 90), stroke_fill=(255, 235, 240), stroke=0)


def v11(img):
    """Nude serif — Georgia elegant."""
    f = font(GEORGIA_I, 74)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.46, fill=(120, 80, 70), stroke_fill=(255, 242, 235), stroke=0)
    draw_line(img, "how I color", fnt=f, y=H * 0.46 + h1 + 12, fill=(120, 80, 70), stroke_fill=(255, 242, 235), stroke=0)


def v12(img):
    """Bubble XL — big bold + bow."""
    sparkles(img, 121, 20)
    bow(img, W / 2, H * 0.38, 1.4, (255, 200, 220, 160))
    f = font(TT_BOLD, 84)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.46, fill=(255, 255, 255), stroke_fill=(200, 80, 130), stroke=0)
    draw_line(img, "how I color", fnt=f, y=H * 0.46 + h1 + 10, fill=(255, 255, 255), stroke_fill=(200, 80, 130), stroke=0)


def v13(img):
    """Lav spaced — lavender sparkles."""
    sparkles(img, 13, 14)
    f = font(TT_SEMI, 74)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.46, fill=(105, 80, 135), stroke_fill=(235, 225, 245), stroke=0)
    draw_line(img, "how I color", fnt=f, y=H * 0.46 + h1 + 12, fill=(105, 80, 135), stroke_fill=(235, 225, 245), stroke=0)


def v14(img):
    """Strawberry bow — bow top."""
    bow(img, W / 2, H * 0.40, 1.3, (255, 150, 175, 170))
    f = font(TT_SEMI, 74)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.48, fill=(150, 55, 80), stroke_fill=(255, 235, 240), stroke=0)
    draw_line(img, "how I color", fnt=f, y=H * 0.48 + h1 + 12, fill=(150, 55, 80), stroke_fill=(255, 235, 240), stroke=0)


def v15(img):
    """Dusk rose — white on pink."""
    sparkles(img, 15, 14)
    f = font(TT_BOLD, 76)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.46, fill=(255, 255, 255), stroke_fill=(160, 50, 95), stroke=0)
    draw_line(img, "how I color", fnt=f, y=H * 0.46 + h1 + 12, fill=(255, 255, 255), stroke_fill=(160, 50, 95), stroke=0)


def v16(img):
    """Ivory coquette — bow + hairline."""
    bow(img, W / 2, H * 0.40, 1.0, (255, 190, 205, 150))
    f = font(TT_SEMI, 72)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.46, fill=(145, 95, 105), stroke_fill=(255, 250, 250), stroke=0)
    hairline(img, H * 0.46 + h1 + 6, 80, (230, 180, 190, 120))
    draw_line(img, "how I color", fnt=f, y=H * 0.46 + h1 + 14, fill=(145, 95, 105), stroke_fill=(255, 250, 250), stroke=0)
    sparkles(img, 16, 10)


def v17(img):
    """Pink clouds — white text."""
    f = font(TT_SEMI, 74)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.46, fill=(255, 255, 255), stroke_fill=(200, 110, 145), stroke=0)
    draw_line(img, "how I color", fnt=f, y=H * 0.46 + h1 + 12, fill=(255, 255, 255), stroke_fill=(200, 110, 145), stroke=0)


def v18(img):
    """Rose gold — heart + serif."""
    heart(img, W / 2, H * 0.40, 15, (255, 170, 175, 150))
    f = font(GEORGIA_B if GEORGIA_B.exists() else GEORGIA_I, 74)
    h1 = draw_line(img, "lemme show you", fnt=f, y=H * 0.46, fill=(255, 255, 255), stroke_fill=(175, 95, 100), stroke=0)
    draw_line(img, "how I color", fnt=f, y=H * 0.46 + h1 + 12, fill=(255, 255, 255), stroke_fill=(175, 95, 100), stroke=0)


VARIANTS = [
    ("blush_air", ((255, 236, 242), (255, 190, 210)), False, v01),
    ("cream_editorial", ((255, 252, 250), (255, 235, 238)), False, v02),
    ("lilac_high", ((248, 242, 255), (225, 205, 240)), False, v03),
    ("peach_low", ((255, 245, 238), (255, 200, 188)), False, v04),
    ("ballet_tiny", ((255, 225, 232), (255, 195, 210)), False, v05),
    ("pearl_hierarchy", ((255, 252, 250), (250, 235, 232)), False, v06),
    ("berry_bold", ((255, 215, 228), (255, 155, 185)), False, v07),
    ("mauve_aside", ((245, 228, 238), (220, 185, 210)), False, v08),
    ("cotton_italic", ((235, 242, 255), (255, 215, 232)), True, v09),
    ("rosewater_hearts", ((255, 240, 244), (255, 200, 212)), False, v10),
    ("nude_serif", ((255, 245, 238), (250, 220, 210)), False, v11),
    ("bubble_xl", ((255, 225, 238), (255, 170, 200)), False, v12),
    ("lav_spaced", ((242, 235, 250), (225, 210, 240)), False, v13),
    ("strawberry_bow", ((255, 248, 250), (255, 185, 200)), False, v14),
    ("dusk_rose", ((255, 210, 225), (255, 155, 185)), False, v15),
    ("ivory_coquette", ((255, 252, 250), (255, 242, 244)), False, v16),
    ("pink_clouds", ((255, 248, 252), (255, 190, 212)), False, v17),
    ("rose_gold", ((255, 235, 225), (245, 185, 180)), True, v18),
]


def contact_sheet(images, cols=6):
    rows = math.ceil(len(images) / cols)
    tw, th = 270, 480
    sheet = Image.new("RGB", (cols * tw + 24, rows * th + 24), (255, 245, 248))
    for i, im in enumerate(images):
        thumb = im.resize((tw - 10, th - 10), Image.Resampling.LANCZOS)
        r, c = divmod(i, cols)
        sheet.paste(thumb, (14 + c * tw, 14 + r * th))
    return sheet


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.glob("intro_*.jpg"):
        p.unlink()
    rendered = []
    for i, (name, colors, diag, fn) in enumerate(VARIANTS, 1):
        img = diagonal_wash(*colors) if diag else wash(*colors)
        fn(img)
        stamp(img, i, name)
        path = OUT / f"intro_{i:02d}_{name}.jpg"
        img.save(path, "JPEG", quality=93)
        rendered.append(img)
        print(f"[{i:02d}] {name}")
    contact_sheet(rendered).save(OUT / "_all_18_contact.jpg", "JPEG", quality=92)
    print(f"\n→ {OUT / '_all_18_contact.jpg'}")


if __name__ == "__main__":
    main()
