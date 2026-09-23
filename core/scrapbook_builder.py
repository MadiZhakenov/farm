"""
Asymmetric Scrapbook / Moodboard collage compositor (Lemon8 · Pinterest).

Layout (1080×1440, 3:4):
  • Warm linen paper background with soft grain
  • Serif + cursive journal header
  • Hero card — mirror selfie
  • Three larger tilted polaroid product cards
  • Soft handwritten labels (no arrows)
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

W, H = 1080, 1440
BG = (247, 244, 238)  # noble warm linen #F7F4EE
INK = (28, 24, 22)
INK_SOFT = (70, 62, 56)
ACCENT = (156, 108, 112)  # dusty rose for flourishes

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "fonts"

TITLE = "my holy grail hair routine"
SUBTITLE = "everything that actually stopped the shedding ✨"

# Soft labels on cards (no arrows)
LABELS = (
    ("01. silk only", "silk"),
    ("02. scalp stimulation", "scalp"),
    ("03. 2 gummies daily", "gummies"),
)

# Slot order expected by build_scrapbook(images):
#   0 = silk pillowcase (polaroid)
#   1 = scalp massager (polaroid)
#   2 = gummies on palm (polaroid)
#   3 = mirror selfie (HERO)
SLOT_HINTS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (0, ("pillow", "bed", "silk", "messy_bed", "phone_cable", "slip")),
    (1, ("scalp", "brush", "sink", "bathroom", "massage")),
    (2, ("vitamin", "gummi", "gummy", "palm", "hand", "candy")),
    (3, ("mirror", "hair", "part", "regrowth", "holding_hair", "progress", "selfie")),
)


# ── Fonts ────────────────────────────────────────────────────────────────────

def _truetype(path: Path | str, size: int) -> ImageFont.FreeTypeFont | None:
    try:
        p = Path(path)
        if p.is_file():
            return ImageFont.truetype(str(p), size)
    except OSError:
        pass
    return None


def font_serif(size: int, *, italic: bool = False, bold: bool = False) -> ImageFont.ImageFont:
    order: list[Path] = []
    if bold and italic:
        order += [
            Path(r"C:\Windows\Fonts\georgiaz.ttf"),
            Path(r"C:\Windows\Fonts\timesbi.ttf"),
        ]
    elif bold:
        order += [
            Path(r"C:\Windows\Fonts\georgiab.ttf"),
            Path(r"C:\Windows\Fonts\timesbd.ttf"),
            FONTS_DIR / "Montserrat-Bold.ttf",
        ]
    elif italic:
        order += [
            Path(r"C:\Windows\Fonts\georgiai.ttf"),
            Path(r"C:\Windows\Fonts\timesi.ttf"),
            Path(r"C:\Windows\Fonts\CAMBRIAI.TTF"),
        ]
    else:
        order += [
            Path(r"C:\Windows\Fonts\georgia.ttf"),
            Path(r"C:\Windows\Fonts\times.ttf"),
            Path(r"C:\Windows\Fonts\cambria.ttc"),
        ]
    for p in order:
        f = _truetype(p, size)
        if f is not None:
            return f
    return ImageFont.load_default()


def font_script(size: int) -> ImageFont.ImageFont:
    for p in (
        Path(r"C:\Windows\Fonts\segoesc.ttf"),
        Path(r"C:\Windows\Fonts\segoescb.ttf"),
        Path(r"C:\Windows\Fonts\MTCORSVA.TTF"),
        Path(r"C:\Windows\Fonts\Gabriola.ttf"),
        Path(r"C:\Windows\Fonts\segoepr.ttf"),
    ):
        f = _truetype(p, size)
        if f is not None:
            return f
    return font_serif(size, italic=True)


def font_hand(size: int) -> ImageFont.ImageFont:
    """Casual handwritten captions (Segoe Print / Script)."""
    for p in (
        Path(r"C:\Windows\Fonts\segoepr.ttf"),
        Path(r"C:\Windows\Fonts\segoeprb.ttf"),
        Path(r"C:\Windows\Fonts\segoesc.ttf"),
        Path(r"C:\Windows\Fonts\comic.ttf"),
    ):
        f = _truetype(p, size)
        if f is not None:
            return f
    return font_script(size)


def font_emoji(size: int) -> ImageFont.ImageFont | None:
    for p in (
        Path(r"C:\Windows\Fonts\seguiemj.ttf"),
        Path(r"C:\Windows\Fonts\SegoeUIEmoji.ttf"),
    ):
        f = _truetype(p, size)
        if f is not None:
            return f
    return None


# ── Paper / crop helpers ─────────────────────────────────────────────────────

def paper_texture(base: Image.Image, seed: int = 42) -> Image.Image:
    """Subtle linen grain + warm vignette wash."""
    rng = random.Random(seed)
    w, h = base.size
    noise = Image.new("L", (w, h), 128)
    px = noise.load()
    assert px is not None
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            v = 128 + rng.randint(-18, 18)
            px[x, y] = v
            if x + 1 < w:
                px[x + 1, y] = v
            if y + 1 < h:
                px[x, y + 1] = v
                if x + 1 < w:
                    px[x + 1, y + 1] = v
    noise = noise.filter(ImageFilter.GaussianBlur(radius=1.2))

    canvas = base.convert("RGBA")
    grain = Image.merge(
        "RGBA",
        (noise, noise, noise, Image.new("L", (w, h), 28)),
    )
    canvas = Image.alpha_composite(canvas, grain)

    # Soft warm wash at edges
    wash = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    wd = ImageDraw.Draw(wash)
    for i, alpha in enumerate((18, 12, 7)):
        m = 8 + i * 14
        wd.rectangle((m, m, w - 1 - m, h - 1 - m), outline=(210, 190, 170, alpha), width=10)
    wash = wash.filter(ImageFilter.GaussianBlur(radius=20))
    return Image.alpha_composite(canvas, wash)


def cover_crop(img: Image.Image, tw: int, th: int, *, bias_y: float = 0.38) -> Image.Image:
    """Proportional cover crop; bias_y < 0.5 keeps faces / upper subject inset."""
    src = img.convert("RGB")
    sw, sh = src.size
    if sw <= 0 or sh <= 0:
        return Image.new("RGB", (tw, th), BG)
    scale = max(tw / sw, th / sh)
    nw = max(1, int(round(sw * scale)))
    nh = max(1, int(round(sh * scale)))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - tw) // 2)
    top = max(0, min(nh - th, int(round((nh - th) * bias_y)))) if nh > th else 0
    return resized.crop((left, top, left + tw, top + th))


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255
    )
    return mask


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


# ── Card makers ──────────────────────────────────────────────────────────────

def make_hero_card(photo: Image.Image, size: tuple[int, int], radius: int = 20) -> Image.Image:
    """Large soft-corner photo card with ambient shadow."""
    tw, th = size
    tile = cover_crop(photo, tw, th, bias_y=0.32)
    blur, offset_y, pad = 22, 8, 36

    layer = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (0, 0, tw - 1, th - 1), radius=radius, fill=(45, 35, 28, 60)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=blur))
    layer.alpha_composite(shadow, (pad, pad + offset_y))

    card = tile.convert("RGBA")
    mask = rounded_mask((tw, th), radius)
    rounded = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    rounded.paste(card, (0, 0), mask)
    ImageDraw.Draw(rounded).rounded_rectangle(
        (0, 0, tw - 1, th - 1),
        radius=radius,
        outline=(255, 252, 248, 100),
        width=1,
    )
    layer.alpha_composite(rounded, (pad, pad))
    return layer


def make_polaroid(
    photo: Image.Image,
    photo_size: tuple[int, int],
    *,
    angle: float,
    caption: str | None = None,
    bottom_margin: int = 52,
    side_margin: int = 12,
) -> Image.Image:
    """Classic white-border polaroid with optional footer caption, slightly tilted."""
    pw, ph = photo_size
    tile = cover_crop(photo, pw, ph, bias_y=0.42)
    tile = ImageEnhance.Color(tile).enhance(0.94)
    tile = ImageEnhance.Contrast(tile).enhance(0.97)

    if caption:
        bottom_margin = max(bottom_margin, 58)

    fw = pw + side_margin * 2
    fh = ph + side_margin + bottom_margin
    frame = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    fd = ImageDraw.Draw(frame)
    fd.rounded_rectangle((0, 0, fw - 1, fh - 1), radius=4, fill=(255, 255, 255, 255))
    frame.paste(tile.convert("RGBA"), (side_margin, side_margin))
    fd.rounded_rectangle(
        (0, 0, fw - 1, fh - 1), radius=4, outline=(230, 224, 216, 220), width=1
    )

    if caption:
        cap_font = font_hand(17)
        cw, ch = _text_size(fd, caption, cap_font)
        cx = (fw - cw) // 2
        cy = side_margin + ph + (bottom_margin - ch) // 2 - 1
        fd.text((cx, cy), caption, font=cap_font, fill=INK_SOFT)

    # Compact ambient shadow (smaller pad = less wasted canvas)
    pad = 18
    sheet = Image.new("RGBA", (fw + pad * 2, fh + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(
        (0, 0, fw - 1, fh - 1), radius=4, fill=(50, 40, 32, 65)
    )
    sh = sh.filter(ImageFilter.GaussianBlur(radius=10))
    sheet.alpha_composite(sh, (pad + 1, pad + 4))
    sheet.alpha_composite(frame, (pad, pad))

    return sheet.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)


# ── Header + labels ──────────────────────────────────────────────────────────

def draw_header(canvas: Image.Image) -> int:
    """Journal masthead. Returns y below header."""
    draw = ImageDraw.Draw(canvas)
    title_font = font_serif(46, italic=True)
    sub_font = font_script(28)
    emoji_f = font_emoji(26)

    # Title
    tw, th = _text_size(draw, TITLE, title_font)
    tx = (W - tw) // 2
    ty = 42
    draw.text((tx, ty), TITLE, font=title_font, fill=INK)

    # Decorative thin rule under title
    rule_y = ty + th + 10
    rule_w = min(220, tw // 2)
    rx0 = (W - rule_w) // 2
    draw.line((rx0, rule_y, rx0 + rule_w, rule_y), fill=(*ACCENT, 160), width=1)

    # Subtitle — split emoji if needed
    sub_plain = "everything that actually stopped the shedding"
    spark = "✨"
    sw, sh = _text_size(draw, sub_plain, sub_font)
    if emoji_f is not None:
        ew, eh = _text_size(draw, spark, emoji_f)
        total = sw + 8 + ew
        sx = (W - total) // 2
        sy = rule_y + 14
        draw.text((sx, sy), sub_plain, font=sub_font, fill=INK_SOFT)
        draw.text(
            (sx + sw + 8, sy + max(0, (sh - eh) // 2 - 2)),
            spark,
            font=emoji_f,
            embedded_color=True,
        )
        return sy + max(sh, eh) + 18
    else:
        full = sub_plain + " *"
        sw, sh = _text_size(draw, full, sub_font)
        sx = (W - sw) // 2
        sy = rule_y + 14
        draw.text((sx, sy), full, font=sub_font, fill=INK_SOFT)
        return sy + sh + 18


def draw_label(
    canvas: Image.Image,
    text: str,
    text_xy: tuple[int, int],
    font: ImageFont.ImageFont,
    *,
    anchor: str = "left",
) -> None:
    """Soft paper chip label — no arrows."""
    draw = ImageDraw.Draw(canvas)
    tw, th = _text_size(draw, text, font)
    tx, ty = text_xy
    if anchor == "right":
        tx = tx - tw
    elif anchor == "center":
        tx = tx - tw // 2

    pad_x, pad_y = 8, 5
    chip = Image.new("RGBA", (tw + pad_x * 2, th + pad_y * 2), (0, 0, 0, 0))
    cd = ImageDraw.Draw(chip)
    cd.rounded_rectangle(
        (0, 0, tw + pad_x * 2 - 1, th + pad_y * 2 - 1),
        radius=8,
        fill=(255, 252, 247, 210),
    )
    canvas.alpha_composite(chip, (tx - pad_x, ty - pad_y))
    draw = ImageDraw.Draw(canvas)
    draw.text((tx, ty), text, font=font, fill=INK_SOFT)


# ── Main compose ─────────────────────────────────────────────────────────────

def build_scrapbook(images: Sequence[Image.Image]) -> Image.Image:
    """
    Compose asymmetric scrapbook from 4 PIL images.

    Order: [silk, scalp, gummies, hero_mirror]
    """
    if len(images) != 4:
        raise ValueError(f"Expected 4 images, got {len(images)}")

    silk, scalp, gummies, hero = images

    canvas = Image.new("RGBA", (W, H), (*BG, 255))
    canvas = paper_texture(canvas)

    header_bottom = draw_header(canvas)

    # ── Hero — wide card, shorter so polaroids can breathe ───────────────
    side_gutter = 48
    hero_w = W - side_gutter * 2  # 984
    hero_h = 460
    hero_card = make_hero_card(hero, (hero_w, hero_h), radius=20)
    hero_pad = 36  # matches make_hero_card pad
    hx = (W - hero_w) // 2 - hero_pad
    hy = header_bottom - 2

    canvas.alpha_composite(hero_card, (hx, hy))
    hero_photo_box = (
        hx + hero_pad,
        hy + hero_pad,
        hx + hero_pad + hero_w,
        hy + hero_pad + hero_h,
    )

    # Soft chip on hero (no number)
    hand = font_hand(20)
    draw_label(
        canvas,
        "3 months of patience",
        text_xy=(hero_photo_box[2] - 22, hero_photo_box[1] + 22),
        font=hand,
        anchor="right",
    )

    # ── Polaroids — fill bottom band (no dead air under hero) ────────────
    zone_top = hero_photo_box[3] + 18
    zone_bottom = H - 22
    avail_h = zone_bottom - zone_top

    # Size from remaining height first, then fit 3-across width
    # outer ≈ photo_h + side(12) + footer(58) + shadow pad(36) + tilt(~4%)
    photo_h = int((avail_h - 12 - 58 - 36) / 1.04)
    photo_h = max(340, min(photo_h, avail_h - 80))
    photo_w = min(310, int(photo_h * 0.72))

    margin = 16
    est_outer = photo_w + 12 * 2 + 18 * 2 + 24
    while est_outer * 3 + margin * 2 > W - 4 and photo_w > 240:
        photo_w -= 4
        est_outer = photo_w + 12 * 2 + 18 * 2 + 24

    # Same photo box for all three → even baseline after tilt
    specs = (
        (silk, (photo_w, photo_h), -1.6, "01. silk only"),
        (scalp, (photo_w, photo_h), 2.0, "02. scalp stimulation"),
        (gummies, (photo_w, photo_h), -1.2, "03. 2 gummies daily"),
    )

    pols = [
        make_polaroid(img, size, angle=ang, caption=cap)
        for img, size, ang, cap in specs
    ]

    widths = [p.size[0] for p in pols]
    heights = [p.size[1] for p in pols]
    total_w = sum(widths)
    free = W - 2 * margin - total_w
    if free < 4:
        photo_w = max(230, photo_w - 18)
        photo_h = max(300, photo_h - 18)
        specs = (
            (silk, (photo_w, photo_h), -1.6, "01. silk only"),
            (scalp, (photo_w, photo_h), 2.0, "02. scalp stimulation"),
            (gummies, (photo_w, photo_h), -1.2, "03. 2 gummies daily"),
        )
        pols = [
            make_polaroid(img, size, angle=ang, caption=cap)
            for img, size, ang, cap in specs
        ]
        widths = [p.size[0] for p in pols]
        heights = [p.size[1] for p in pols]
        total_w = sum(widths)
        free = W - 2 * margin - total_w

    gap = max(4, free / (len(pols) - 1)) if len(pols) > 1 else 0
    max_ph = max(heights)
    # Align bottoms of rotated layers so the row reads as one band
    row_bottom = zone_top + max_ph

    x = float(margin)
    for pol, pw, ph in zip(pols, widths, heights):
        px = int(round(x))
        py = int(row_bottom - ph)
        px = max(0, min(W - pw, px))
        py = max(0, min(H - ph, py))
        canvas.alpha_composite(pol, (px, py))
        x += pw + gap

    return canvas


def build_scrapbook_from_paths(paths: Sequence[Path]) -> Image.Image:
    imgs: list[Image.Image] = []
    for p in paths:
        with Image.open(p) as im:
            imgs.append(im.convert("RGB").copy())
    return build_scrapbook(imgs)
