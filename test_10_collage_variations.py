#!/usr/bin/env python3
"""
Generate 10 trending collage variations (1080×1440 / 3:4) for Pinterest & Lemon8.

Usage:
  python test_10_collage_variations.py
  python test_10_collage_variations.py --dir E:\\Users\\Desktop\\download
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

W, H = 1080, 1440
ROOT = Path(__file__).resolve().parent
DEFAULT_SRC = Path(r"E:\Users\Desktop\download")
OUT_DIR = ROOT / "out" / "collage_experiments"
FONTS_DIR = ROOT / "fonts"

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Slot order: silk, scalp, gummies, hair(hero)
_SLOT_HINTS = (
    (0, ("pillow", "bed", "silk", "messy_bed", "slip")),
    (1, ("scalp", "brush", "sink", "bathroom", "massage")),
    (2, ("vitamin", "gummi", "gummy", "palm", "hand")),
    (3, ("mirror", "hair", "part", "regrowth", "holding_hair", "selfie")),
)

LABELS_SHORT = ("silk slip", "scalp care", "daily gummies", "real progress")
LABELS_NUM = ("01", "02", "03", "04")
STEPS = ("STEP 1", "STEP 2", "STEP 3", "STEP 4")

MONTSERRAT_BOLD = FONTS_DIR / "Montserrat-Bold.ttf"
MONTSERRAT_REG = FONTS_DIR / "Montserrat-Regular.ttf"
PLAYFAIR_BOLD = FONTS_DIR / "PlayfairDisplay-Bold.ttf"
PLAYFAIR_REG = FONTS_DIR / "PlayfairDisplay-Regular.ttf"

MONTSERRAT_BOLD_URL = (
    "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf"
)
MONTSERRAT_REG_URL = (
    "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Regular.ttf"
)
PLAYFAIR_BOLD_URL = (
    "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf"
)


# ── Fonts ────────────────────────────────────────────────────────────────────

def _download(url: str, dest: Path) -> Path | None:
    try:
        if dest.is_file() and dest.stat().st_size > 8_000:
            return dest
        FONTS_DIR.mkdir(parents=True, exist_ok=True)
        req = Request(url, headers={"User-Agent": "CollageExperiments/1.0"})
        with urlopen(req, timeout=25) as resp:
            data = resp.read()
        if len(data) < 8_000:
            return None
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return dest
    except Exception:
        return None


def _tt(path: Path | str, size: int) -> ImageFont.FreeTypeFont | None:
    try:
        if Path(path).is_file():
            return ImageFont.truetype(str(path), size)
    except OSError:
        pass
    return None


def font_serif(size: int, *, bold: bool = False, italic: bool = False) -> ImageFont.ImageFont:
    cands: list[Path] = []
    if bold:
        cands += [PLAYFAIR_BOLD, Path(r"C:\Windows\Fonts\georgiab.ttf"), Path(r"C:\Windows\Fonts\timesbd.ttf")]
    elif italic:
        cands += [Path(r"C:\Windows\Fonts\georgiai.ttf"), Path(r"C:\Windows\Fonts\timesi.ttf")]
    else:
        cands += [PLAYFAIR_REG, Path(r"C:\Windows\Fonts\georgia.ttf"), Path(r"C:\Windows\Fonts\times.ttf")]
    for p in cands:
        f = _tt(p, size)
        if f:
            return f
    if bold:
        _download(MONTSERRAT_BOLD_URL, MONTSERRAT_BOLD)
    return font_sans(size, bold=bold)


def font_sans(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    if bold:
        order = [
            MONTSERRAT_BOLD,
            FONTS_DIR / "TikTokSans-Bold.ttf",
            Path(r"C:\Windows\Fonts\segoeuib.ttf"),
            Path(r"C:\Windows\Fonts\arialbd.ttf"),
        ]
        urls = [(MONTSERRAT_BOLD_URL, MONTSERRAT_BOLD)]
    else:
        order = [
            MONTSERRAT_REG,
            Path(r"C:\Windows\Fonts\segoeui.ttf"),
            Path(r"C:\Windows\Fonts\arial.ttf"),
        ]
        urls = [(MONTSERRAT_REG_URL, MONTSERRAT_REG)]
    for p in order:
        f = _tt(p, size)
        if f:
            return f
    for url, dest in urls:
        if _download(url, dest):
            f = _tt(dest, size)
            if f:
                return f
    return ImageFont.load_default()


def font_hand(size: int) -> ImageFont.ImageFont:
    for p in (
        Path(r"C:\Windows\Fonts\segoesc.ttf"),
        Path(r"C:\Windows\Fonts\segoepr.ttf"),
        Path(r"C:\Windows\Fonts\Gabriola.ttf"),
    ):
        f = _tt(p, size)
        if f:
            return f
    return font_serif(size, italic=True)


def font_emoji(size: int) -> ImageFont.ImageFont | None:
    for p in (Path(r"C:\Windows\Fonts\seguiemj.ttf"), Path(r"C:\Windows\Fonts\SegoeUIEmoji.ttf")):
        f = _tt(p, size)
        if f:
            return f
    return None


# ── Image helpers ────────────────────────────────────────────────────────────

def cover_crop(img: Image.Image, tw: int, th: int, *, bias_y: float = 0.4) -> Image.Image:
    src = img.convert("RGB")
    sw, sh = src.size
    if sw <= 0 or sh <= 0:
        return Image.new("RGB", (tw, th), (240, 236, 228))
    scale = max(tw / sw, th / sh)
    nw, nh = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - tw) // 2)
    top = max(0, min(nh - th, int(round((nh - th) * bias_y)))) if nh > th else 0
    return resized.crop((left, top, left + tw, top + th))


def rounded(img: Image.Image, radius: int) -> Image.Image:
    rgba = img.convert("RGBA")
    mask = Image.new("L", rgba.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, rgba.size[0] - 1, rgba.size[1] - 1), radius=radius, fill=255
    )
    out = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    out.paste(rgba, (0, 0), mask)
    return out


def soft_shadow(
    card: Image.Image,
    *,
    blur: int = 16,
    offset: tuple[int, int] = (0, 6),
    opacity: int = 55,
) -> Image.Image:
    pad = blur * 2 + 8
    cw, ch = card.size
    layer = Image.new("RGBA", (cw + pad * 2, ch + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(
        (0, 0, cw - 1, ch - 1), radius=8, fill=(40, 32, 28, opacity)
    )
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    layer.alpha_composite(sh, (pad + offset[0], pad + offset[1]))
    layer.alpha_composite(card, (pad, pad))
    return layer


def paper_texture(base: Image.Image, seed: int = 11) -> Image.Image:
    rng = random.Random(seed)
    w, h = base.size
    noise = Image.new("L", (w, h), 128)
    px = noise.load()
    assert px is not None
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            v = 128 + rng.randint(-14, 14)
            for dy in range(2):
                for dx in range(2):
                    if x + dx < w and y + dy < h:
                        px[x + dx, y + dy] = v
    noise = noise.filter(ImageFilter.GaussianBlur(1.0))
    canvas = base.convert("RGBA")
    grain = Image.merge("RGBA", (noise, noise, noise, Image.new("L", (w, h), 22)))
    return Image.alpha_composite(canvas, grain)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    b = draw.textbbox((0, 0), text, font=font)
    return b[2] - b[0], b[3] - b[1]


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        if text_size(draw, trial, font)[0] <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    color: tuple = (50, 42, 38, 220),
    width: int = 2,
) -> None:
    dx, dy = x1 - x0, y1 - y0
    mx = (x0 + x1) / 2 - dy * 0.12
    my = (y0 + y1) / 2 + dx * 0.12
    pts = []
    for i in range(16):
        t = i / 15
        pts.append(
            (
                (1 - t) ** 2 * x0 + 2 * (1 - t) * t * mx + t**2 * x1,
                (1 - t) ** 2 * y0 + 2 * (1 - t) * t * my + t**2 * y1,
            )
        )
    draw.line(pts, fill=color, width=width, joint="curve")
    ang = math.atan2(pts[-1][1] - pts[-2][1], pts[-1][0] - pts[-2][0])
    ah = 11
    a1 = (x1 - ah * math.cos(ang - 0.5), y1 - ah * math.sin(ang - 0.5))
    a2 = (x1 - ah * math.cos(ang + 0.5), y1 - ah * math.sin(ang + 0.5))
    draw.polygon([(x1, y1), a1, a2], fill=color)


# ── Asset picking ────────────────────────────────────────────────────────────

def list_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_EXTS]
    # Prefer single-subject shots over combined flatlays for the 4 slots
    files.sort(key=lambda p: ("and" in p.stem.lower(), -p.stat().st_mtime))
    return files


def pick_four(folder: Path) -> list[Image.Image]:
    files = list_images(folder)
    if len(files) < 4:
        raise FileNotFoundError(f"Need ≥4 images in {folder}, found {len(files)}")
    slots: list[Path | None] = [None, None, None, None]
    rem = list(files)
    for slot, hints in _SLOT_HINTS:
        for p in rem:
            if any(h in p.stem.lower() for h in hints) and "and" not in p.stem.lower():
                slots[slot] = p
                rem.remove(p)
                break
    for i in range(4):
        if slots[i] is None and rem:
            slots[i] = rem.pop(0)
    if any(s is None for s in slots):
        raise FileNotFoundError("Could not resolve 4 images")
    imgs: list[Image.Image] = []
    for p in slots:
        assert p is not None
        with Image.open(p) as im:
            imgs.append(im.convert("RGB").copy())
        print(f"  [{LABELS_SHORT[len(imgs)-1]}] {p.name}")
    return imgs


# ── Variations ───────────────────────────────────────────────────────────────

def var_01_editorial_magazine(imgs: list[Image.Image]) -> Image.Image:
    BG = (247, 244, 238)
    canvas = Image.new("RGBA", (W, H), (*BG, 255))
    draw = ImageDraw.Draw(canvas)

    title_f = font_serif(42, italic=True)
    title = "the daily routine that saved my hair"
    lines = wrap(draw, title, title_f, W - 120)
    y = 48
    for line in lines:
        tw, th = text_size(draw, line, title_f)
        draw.text(((W - tw) // 2, y), line, font=title_f, fill=(28, 24, 22))
        y += th + 6
    # thin rule
    draw.line((W // 2 - 80, y + 8, W // 2 + 80, y + 8), fill=(168, 120, 110), width=1)
    y += 28

    pad = 28
    gap = 22
    top = y
    bot = H - 40
    avail_h = bot - top
    cell_w = (W - pad * 2 - gap) // 2
    cell_h = (avail_h - gap) // 2
    num_f = font_serif(22, italic=True)

    positions = (
        (pad, top),
        (pad + cell_w + gap, top),
        (pad, top + cell_h + gap),
        (pad + cell_w + gap, top + cell_h + gap),
    )
    for i, (x, yy) in enumerate(positions):
        tile = cover_crop(imgs[i], cell_w - 4, cell_h - 4)
        card = rounded(tile, 6)
        # thin frame
        frame = Image.new("RGBA", (cell_w, cell_h), (255, 255, 255, 255))
        frame.alpha_composite(card, (2, 2))
        fd = ImageDraw.Draw(frame)
        fd.rectangle((0, 0, cell_w - 1, cell_h - 1), outline=(210, 200, 190), width=1)
        canvas.alpha_composite(frame, (x, yy))
        # delicate number
        draw = ImageDraw.Draw(canvas)
        draw.text((x + 14, yy + 10), LABELS_NUM[i], font=num_f, fill=(255, 255, 255, 230))
    return canvas


def var_02_asymmetric_hero_left(imgs: list[Image.Image]) -> Image.Image:
    BG = (250, 247, 242)
    canvas = Image.new("RGBA", (W, H), (*BG, 255))
    silk, scalp, gum, hair = imgs

    # Top sticker
    hand = font_hand(28)
    sticker_txt = "what actually stopped the shedding"
    probe = ImageDraw.Draw(canvas)
    tw, th = text_size(probe, sticker_txt, hand)
    sw, sh = tw + 40, th + 22
    sticker = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sticker)
    sd.rounded_rectangle((0, 0, sw - 1, sh - 1), radius=12, fill=(255, 255, 255, 240))
    sd.text((20, 10), sticker_txt, font=hand, fill=(30, 26, 24))
    canvas.alpha_composite(sticker, ((W - sw) // 2, 36))

    margin = 28
    top = 100
    gap = 16
    left_w = int((W - margin * 2 - gap) * 0.55)
    right_w = W - margin * 2 - gap - left_w
    col_h = H - top - margin

    hero = rounded(cover_crop(hair, left_w, col_h, bias_y=0.32), 18)
    canvas.alpha_composite(soft_shadow(hero, blur=14), (margin - 20, top - 20))

    small_h = (col_h - gap * 2) // 3
    rights = [silk, scalp, gum]
    ry = top
    for i, im in enumerate(rights):
        tile = rounded(cover_crop(im, right_w, small_h), 14)
        canvas.alpha_composite(
            soft_shadow(tile, blur=10, opacity=45),
            (margin + left_w + gap - 14, ry - 14),
        )
        ry += small_h + gap
    return canvas


def var_03_polaroid_scrapbook(imgs: list[Image.Image]) -> Image.Image:
    BG = (242, 232, 216)
    canvas = Image.new("RGBA", (W, H), (*BG, 255))
    canvas = paper_texture(canvas, seed=21)

    angles = (-2.5, 1.5, -1.0, 2.0)
    captions = ("01. silk only", "02. scalp care", "03. 2 gummies", "04. patience")
    # 2x2 polaroid positions (centers)
    centers = ((300, 400), (780, 380), (320, 1050), (800, 1070))
    hand = font_hand(20)

    for i, (img, ang, cap, center) in enumerate(zip(imgs, angles, captions, centers)):
        pw, ph = 340, 400
        tile = cover_crop(img, pw, ph)
        tile = ImageEnhance.Color(tile).enhance(0.93)
        side, bot = 14, 56
        fw, fh = pw + side * 2, ph + side + bot
        frame = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
        fd = ImageDraw.Draw(frame)
        fd.rounded_rectangle((0, 0, fw - 1, fh - 1), radius=3, fill=(255, 255, 255, 255))
        frame.paste(tile.convert("RGBA"), (side, side))
        cw, ch = text_size(fd, cap, hand)
        fd.text(((fw - cw) // 2, side + ph + (bot - ch) // 2 - 1), cap, font=hand, fill=(70, 60, 55))

        pad = 22
        sheet = Image.new("RGBA", (fw + pad * 2, fh + pad * 2), (0, 0, 0, 0))
        sh = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((0, 0, fw - 1, fh - 1), radius=3, fill=(50, 40, 30, 70))
        sh = sh.filter(ImageFilter.GaussianBlur(12))
        sheet.alpha_composite(sh, (pad + 2, pad + 6))
        sheet.alpha_composite(frame, (pad, pad))
        tilted = sheet.rotate(ang, resample=Image.Resampling.BICUBIC, expand=True)
        tw, th = tilted.size
        canvas.alpha_composite(tilted, (int(center[0] - tw / 2), int(center[1] - th / 2)))
    return canvas


def var_04_clean_girl_minimal(imgs: list[Image.Image]) -> Image.Image:
    BG = (252, 250, 247)
    canvas = Image.new("RGBA", (W, H), (*BG, 255))
    outer, gap, radius = 32, 20, 32
    cell_w = (W - outer * 2 - gap) // 2
    cell_h = (H - outer * 2 - gap) // 2
    pos = (
        (outer, outer),
        (outer + cell_w + gap, outer),
        (outer, outer + cell_h + gap),
        (outer + cell_w + gap, outer + cell_h + gap),
    )
    for i, (x, y) in enumerate(pos):
        tile = rounded(cover_crop(imgs[i], cell_w, cell_h), radius)
        canvas.alpha_composite(tile, (x, y))

    # Center oval pill
    txt = "my holy grail protocol ✨"
    sans = font_sans(28, bold=False)
    emoji = font_emoji(26)
    probe = ImageDraw.Draw(canvas)
    plain = "my holy grail protocol"
    tw, th = text_size(probe, plain, sans)
    ew = text_size(probe, "✨", emoji)[0] if emoji else 0
    bw, bh = tw + ew + 56, th + 28
    pill = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pill)
    pd.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=bh // 2, fill=(255, 255, 255, 230))
    pd.text((28, 12), plain, font=sans, fill=(30, 28, 26))
    if emoji:
        pd.text((28 + tw + 8, 10), "✨", font=emoji, embedded_color=True)
    # soft shadow
    sh = Image.new("RGBA", (bw + 24, bh + 24), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((8, 10, 8 + bw, 10 + bh), radius=bh // 2, fill=(0, 0, 0, 50))
    sh = sh.filter(ImageFilter.GaussianBlur(8))
    canvas.alpha_composite(sh, ((W - bw) // 2 - 8, (H - bh) // 2 - 8))
    canvas.alpha_composite(pill, ((W - bw) // 2, (H - bh) // 2))
    return canvas


def var_05_top_hero_bottom_three(imgs: list[Image.Image]) -> Image.Image:
    BG = (248, 245, 240)
    canvas = Image.new("RGBA", (W, H), (*BG, 255))
    silk, scalp, gum, hair = imgs
    margin, gap = 24, 14

    # Header integrated into top edge
    title_f = font_serif(36, italic=True)
    draw = ImageDraw.Draw(canvas)
    title = "my hair protocol"
    tw, th = text_size(draw, title, title_f)
    draw.text(((W - tw) // 2, 28), title, font=title_f, fill=(32, 28, 26))

    hero_top = 28 + th + 18
    hero_h = int(H * 0.45)
    hero_w = W - margin * 2
    hero = rounded(cover_crop(hair, hero_w, hero_h, bias_y=0.3), 16)
    canvas.alpha_composite(hero, (margin, hero_top))

    bot_top = hero_top + hero_h + gap
    bot_h = H - bot_top - margin
    col_w = (W - margin * 2 - gap * 2) // 3
    for i, im in enumerate((silk, scalp, gum)):
        x = margin + i * (col_w + gap)
        tile = rounded(cover_crop(im, col_w, bot_h), 14)
        canvas.alpha_composite(tile, (x, bot_top))
    return canvas


def var_06_lemon8_sticker_note(imgs: list[Image.Image]) -> Image.Image:
    BG = (246, 242, 236)
    canvas = Image.new("RGBA", (W, H), (*BG, 255))

    # Sticker note with tape
    note_f = font_hand(30)
    note = "hair shedding starter pack"
    probe = ImageDraw.Draw(canvas)
    tw, th = text_size(probe, note, note_f)
    nw, nh = tw + 48, th + 36
    note_img = Image.new("RGBA", (nw + 20, nh + 30), (0, 0, 0, 0))
    # tape
    td = ImageDraw.Draw(note_img)
    td.rectangle((nw // 2 - 40, 0, nw // 2 + 40, 18), fill=(255, 250, 220, 180))
    # paper
    td.rounded_rectangle((10, 14, 10 + nw, 14 + nh), radius=4, fill=(255, 255, 252, 250))
    td.text((10 + 24, 14 + 14), note, font=note_f, fill=(40, 36, 32))
    # slight tilt
    note_img = note_img.rotate(-1.2, resample=Image.Resampling.BICUBIC, expand=True)
    canvas.alpha_composite(note_img, ((W - note_img.size[0]) // 2, 28))

    outer, gap, rad = 36, 18, 20
    grid_top = 120
    cell_w = (W - outer * 2 - gap) // 2
    cell_h = (H - grid_top - 36 - gap) // 2
    pos = (
        (outer, grid_top),
        (outer + cell_w + gap, grid_top),
        (outer, grid_top + cell_h + gap),
        (outer + cell_w + gap, grid_top + cell_h + gap),
    )
    caps = ("silk", "scalp", "gummies", "progress")
    hand = font_hand(20)
    for i, ((x, y), cap) in enumerate(zip(pos, caps)):
        tile = rounded(cover_crop(imgs[i], cell_w, cell_h), rad)
        canvas.alpha_composite(tile, (x, y))
        # arrow + label in corner
        draw = ImageDraw.Draw(canvas)
        lx, ly = x + 18, y + 18
        chip_w = text_size(draw, cap, hand)[0] + 20
        chip = Image.new("RGBA", (chip_w, 32), (0, 0, 0, 0))
        cd = ImageDraw.Draw(chip)
        cd.rounded_rectangle((0, 0, chip_w - 1, 31), radius=10, fill=(255, 255, 255, 210))
        cd.text((10, 6), cap, font=hand, fill=(40, 36, 32))
        canvas.alpha_composite(chip, (lx, ly))
        draw = ImageDraw.Draw(canvas)
        draw_arrow(draw, lx + chip_w + 4, ly + 16, x + cell_w * 0.55, y + cell_h * 0.45)
    return canvas


def var_07_instagram_story_grid(imgs: list[Image.Image]) -> Image.Image:
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    gap = 4
    cell_w = (W - gap) // 2
    cell_h = (H - gap) // 2
    pos = ((0, 0), (cell_w + gap, 0), (0, cell_h + gap), (cell_w + gap, cell_h + gap))
    for i, (x, y) in enumerate(pos):
        tile = cover_crop(imgs[i], cell_w, cell_h)
        canvas.paste(tile, (x, y))

    # Frosted glass oval in center
    ow, oh = 520, 200
    region = canvas.crop(
        ((W - ow) // 2, (H - oh) // 2, (W + ow) // 2, (H + oh) // 2)
    ).filter(ImageFilter.GaussianBlur(18))
    frost = ImageEnhance.Brightness(region).enhance(0.75)
    frost = frost.convert("RGBA")
    # oval mask
    mask = Image.new("L", (ow, oh), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, ow - 1, oh - 1), fill=200)
    oval = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
    oval.paste(frost, (0, 0), mask)
    # frosted white wash
    wash = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
    ImageDraw.Draw(wash).ellipse((0, 0, ow - 1, oh - 1), fill=(255, 255, 255, 70))
    oval = Image.alpha_composite(oval, wash)

    # TikTok-style text with black outline
    txt = "the only 4 things\nthat actually worked"
    font = font_sans(36, bold=True)
    td = ImageDraw.Draw(oval)
    lines = txt.split("\n")
    total_h = sum(text_size(td, ln, font)[1] for ln in lines) + 8
    ty = (oh - total_h) // 2
    for ln in lines:
        tw, th = text_size(td, ln, font)
        tx = (ow - tw) // 2
        # outline
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                if dx or dy:
                    td.text((tx + dx, ty + dy), ln, font=font, fill=(0, 0, 0, 220))
        td.text((tx, ty), ln, font=font, fill=(255, 255, 255, 255))
        ty += th + 8

    canvas.alpha_composite(oval, ((W - ow) // 2, (H - oh) // 2))
    return canvas


def var_08_35mm_contact_sheet(imgs: list[Image.Image]) -> Image.Image:
    BG = (36, 36, 38)
    canvas = Image.new("RGBA", (W, H), (*BG, 255))
    draw = ImageDraw.Draw(canvas)

    # film edge perforations (decorative)
    for y in range(20, H - 20, 28):
        for x in (12, W - 28):
            draw.rounded_rectangle((x, y, x + 14, y + 18), radius=3, fill=(22, 22, 24))

    pad, gap = 48, 12
    cell_w = (W - pad * 2 - gap) // 2
    cell_h = (H - pad * 2 - gap - 40) // 2
    top = pad + 10
    pos = (
        (pad, top),
        (pad + cell_w + gap, top),
        (pad, top + cell_h + gap),
        (pad + cell_w + gap, top + cell_h + gap),
    )
    label_f = font_sans(18, bold=False)
    caps = ("SILK", "SCALP", "GUMMIES", "GROWTH")
    for i, (x, y) in enumerate(pos):
        tile = cover_crop(imgs[i], cell_w - 4, cell_h - 24)
        # thin white frame
        frame = Image.new("RGBA", (cell_w, cell_h), (28, 28, 30, 255))
        fd = ImageDraw.Draw(frame)
        fd.rectangle((0, 0, cell_w - 1, cell_h - 1), outline=(200, 200, 200), width=1)
        frame.paste(tile, (2, 2))
        canvas.alpha_composite(frame, (x, y))
        draw = ImageDraw.Draw(canvas)
        draw.text((x + 8, y + cell_h - 22), caps[i], font=label_f, fill=(240, 240, 240))

    # orange timestamp
    ts_f = font_sans(16, bold=True)
    draw.text((pad, H - 36), "'26  9  23", font=ts_f, fill=(232, 120, 48))
    return canvas


def var_09_numbered_protocol_steps(imgs: list[Image.Image]) -> Image.Image:
    BG = (250, 248, 244)
    canvas = Image.new("RGBA", (W, H), (*BG, 255))
    pad, gap = 24, 16
    footer_h = 72
    cell_w = (W - pad * 2 - gap) // 2
    cell_h = (H - pad * 2 - gap - footer_h) // 2
    pos = (
        (pad, pad),
        (pad + cell_w + gap, pad),
        (pad, pad + cell_h + gap),
        (pad + cell_w + gap, pad + cell_h + gap),
    )
    badge_f = font_sans(16, bold=True)
    for i, (x, y) in enumerate(pos):
        tile = rounded(cover_crop(imgs[i], cell_w, cell_h), 16)
        canvas.alpha_composite(tile, (x, y))
        # STEP badge
        label = STEPS[i]
        probe = ImageDraw.Draw(canvas)
        tw, th = text_size(probe, label, badge_f)
        bw, bh = tw + 28, th + 16
        badge = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        bd = ImageDraw.Draw(badge)
        bd.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=bh // 2, fill=(212, 175, 120, 235))
        bd.text((14, 7), label, font=badge_f, fill=(40, 30, 20))
        canvas.alpha_composite(badge, (x + 14, y + 14))

    # bottom result bar
    bar = Image.new("RGBA", (W - pad * 2, footer_h - 12), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    bd.rounded_rectangle((0, 0, bar.size[0] - 1, bar.size[1] - 1), radius=14, fill=(30, 28, 26, 235))
    result_f = font_sans(28, bold=True)
    txt = "90 days consistency"
    tw, th = text_size(bd, txt, result_f)
    bd.text(((bar.size[0] - tw) // 2, (bar.size[1] - th) // 2 - 1), txt, font=result_f, fill=(255, 255, 255))
    canvas.alpha_composite(bar, (pad, H - pad - footer_h + 8))
    return canvas


def var_10_modern_compact_pill(imgs: list[Image.Image]) -> Image.Image:
    BG = (248, 246, 242)
    canvas = Image.new("RGBA", (W, H), (*BG, 255))
    outer, gap, rad = 20, 14, 20
    cell_w = (W - outer * 2 - gap) // 2
    cell_h = (H - outer * 2 - gap) // 2
    pos = (
        (outer, outer),
        (outer + cell_w + gap, outer),
        (outer, outer + cell_h + gap),
        (outer + cell_w + gap, outer + cell_h + gap),
    )
    for i, (x, y) in enumerate(pos):
        tile = rounded(cover_crop(imgs[i], cell_w, cell_h), rad)
        canvas.alpha_composite(tile, (x, y))

    # Ultra-compact center pill — small so it doesn't cover faces/hands
    line1 = "4 things"
    line2 = "that worked ✨"
    f1 = font_sans(22, bold=True)
    f2 = font_sans(18, bold=False)
    emoji = font_emoji(16)
    probe = ImageDraw.Draw(canvas)
    w1, h1 = text_size(probe, line1, f1)
    plain2 = "that worked"
    w2a, h2 = text_size(probe, plain2, f2)
    ew = text_size(probe, "✨", emoji)[0] if emoji else 0
    text_w = max(w1, w2a + 6 + ew)
    bw, bh = text_w + 36, h1 + h2 + 28
    pill = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pill)
    pd.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=14, fill=(255, 255, 255, 245))
    pd.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=14, outline=(230, 224, 216), width=1)
    pd.text(((bw - w1) // 2, 10), line1, font=f1, fill=(20, 20, 20))
    x2 = (bw - (w2a + 6 + ew)) // 2
    pd.text((x2, 10 + h1 + 4), plain2, font=f2, fill=(60, 56, 52))
    if emoji:
        pd.text((x2 + w2a + 6, 10 + h1 + 2), "✨", font=emoji, embedded_color=True)

    sh = Image.new("RGBA", (bw + 20, bh + 20), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((6, 8, 6 + bw, 8 + bh), radius=14, fill=(0, 0, 0, 45))
    sh = sh.filter(ImageFilter.GaussianBlur(6))
    canvas.alpha_composite(sh, ((W - bw) // 2 - 6, (H - bh) // 2 - 6))
    canvas.alpha_composite(pill, ((W - bw) // 2, (H - bh) // 2))
    return canvas


# ── Orchestration ────────────────────────────────────────────────────────────

VARIATIONS: list[tuple[str, Callable[[list[Image.Image]], Image.Image]]] = [
    ("var_01_editorial_magazine.jpg", var_01_editorial_magazine),
    ("var_02_asymmetric_hero_left.jpg", var_02_asymmetric_hero_left),
    ("var_03_polaroid_scrapbook.jpg", var_03_polaroid_scrapbook),
    ("var_04_clean_girl_minimal.jpg", var_04_clean_girl_minimal),
    ("var_05_top_hero_bottom_three.jpg", var_05_top_hero_bottom_three),
    ("var_06_lemon8_sticker_note.jpg", var_06_lemon8_sticker_note),
    ("var_07_instagram_story_grid.jpg", var_07_instagram_story_grid),
    ("var_08_35mm_contact_sheet.jpg", var_08_35mm_contact_sheet),
    ("var_09_numbered_protocol_steps.jpg", var_09_numbered_protocol_steps),
    ("var_10_modern_compact_pill.jpg", var_10_modern_compact_pill),
]


def run(src_dir: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Picking assets from {src_dir}")
    imgs = pick_four(src_dir)
    saved: list[Path] = []
    t0 = time.perf_counter()
    for name, fn in VARIATIONS:
        print(f"  building {name} ...")
        canvas = fn(imgs)
        path = out_dir / name
        canvas.convert("RGB").save(path, "JPEG", quality=94, optimize=True, subsampling=0)
        saved.append(path)
        print(f"    -> {path}")
    print(f"\nDone {len(saved)} variations in {time.perf_counter() - t0:.1f}s")
    print(f"Output: {out_dir.resolve()}")
    return saved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build 10 collage style experiments.")
    ap.add_argument("--dir", type=Path, default=DEFAULT_SRC)
    ap.add_argument("-o", "--out", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    try:
        run(args.dir, args.out)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
