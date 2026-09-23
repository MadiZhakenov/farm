#!/usr/bin/env python3
"""
11 editorial magazine collage layouts — 1080×1440 (3:4).

Each layout keeps the var_01 magazine DNA (air, thin frames, serif masthead)
but uses a distinct palette / type treatment so they read as different.

Public API:
  LAYOUT_REGISTRY[1..11]  → render functions
  layout_key(n)           → "layout_01" … "layout_11"
  render_layout(n, imgs, captions, title=…) → Image
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1440
ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "fonts"

LayoutFn = Callable[..., Image.Image]

DEFAULT_TITLE = "the daily routine that saved my hair"
DEFAULT_CAPTIONS = (
    "01 · silk pillowcase",
    "02 · scalp stimulation",
    "03 · daily hair gummies (sulu)",
    "04 · 90-day hairline progress",
)

ROMAN = ("I", "II", "III", "IV")
CIRCLED = ("①", "②", "③", "④")

WHITE = (255, 255, 255)


@dataclass(frozen=True)
class Theme:
    bg: tuple[int, int, int]
    ink: tuple[int, int, int]
    caption: tuple[int, int, int]
    accent: tuple[int, int, int]
    frame: tuple[int, int, int]
    card: tuple[int, int, int] = WHITE
    band: tuple[int, int, int] = WHITE
    divider: tuple[int, int, int] = (210, 200, 188)


# Distinct personalities — backgrounds intentionally far apart (still editorial)
T_CLASSIC = Theme(
    # warm linen (original winner)
    bg=(247, 244, 238), ink=(26, 26, 26), caption=(42, 42, 42),
    accent=(168, 120, 110), frame=(220, 212, 202),
)
T_KIN = Theme(
    # cool bone / blue-ivory
    bg=(236, 240, 242), ink=(28, 32, 36), caption=(48, 54, 60),
    accent=(120, 136, 148), frame=(200, 210, 216),
    card=(250, 252, 253), band=(250, 252, 253),
)
T_CEREAL = Theme(
    # honey butter
    bg=(252, 242, 220), ink=(56, 40, 24), caption=(80, 58, 36),
    accent=(196, 148, 88), frame=(230, 210, 170),
    card=(255, 250, 240),
)
T_DIVIDER = Theme(
    # dusty blush
    bg=(244, 228, 226), ink=(48, 32, 32), caption=(72, 48, 48),
    accent=(180, 112, 112), frame=(220, 190, 188),
    divider=(210, 168, 164),
)
T_ROMAN = Theme(
    # warm parchment / peach
    bg=(250, 236, 220), ink=(40, 28, 22), caption=(60, 40, 32),
    accent=(160, 68, 56), frame=(220, 196, 176),
    band=(255, 246, 236), card=(255, 248, 240),
)
T_MUSEUM = Theme(
    # cool museum gray-green
    bg=(228, 230, 226), ink=(32, 34, 32), caption=(52, 56, 52),
    accent=(96, 108, 96), frame=(180, 186, 178),
    card=(244, 246, 242),
)
T_GALLERY = Theme(
    # soft sage wash
    bg=(226, 234, 226), ink=(28, 36, 30), caption=(44, 56, 46),
    accent=(78, 118, 92), frame=(170, 190, 174),
    card=(246, 250, 246),
)
T_POLAROID = Theme(
    # apricot paper
    bg=(252, 232, 210), ink=(52, 36, 24), caption=(78, 52, 34),
    accent=(196, 120, 72), frame=(230, 200, 170),
    card=(255, 248, 238),
)
T_FOOTER = Theme(
    # dusty rose
    bg=(240, 224, 228), ink=(44, 28, 34), caption=(68, 44, 52),
    accent=(168, 88, 108), frame=(214, 186, 194),
    card=(252, 244, 246),
)
T_TWOTONE = Theme(
    # olive mist
    bg=(232, 236, 220), ink=(32, 40, 28), caption=(48, 58, 42),
    accent=(92, 120, 72), frame=(190, 200, 170),
    band=(246, 250, 236), card=(248, 252, 240),
)
T_CIRCLED = Theme(
    # soft lilac
    bg=(236, 230, 242), ink=(36, 28, 44), caption=(58, 46, 68),
    accent=(128, 96, 152), frame=(200, 188, 214),
    band=(246, 240, 252), card=(250, 246, 255),
)


# ── Fonts ────────────────────────────────────────────────────────────────────

def _tt(path: Path | str, size: int) -> ImageFont.FreeTypeFont | None:
    try:
        if Path(path).is_file():
            return ImageFont.truetype(str(path), size)
    except OSError:
        pass
    return None


def font_serif_italic(size: int) -> ImageFont.ImageFont:
    for p in (
        FONTS_DIR / "PlayfairDisplay-Italic.ttf",
        FONTS_DIR / "CormorantGaramond-Italic.ttf",
        Path(r"C:\Windows\Fonts\georgiai.ttf"),
        Path(r"C:\Windows\Fonts\timesi.ttf"),
    ):
        f = _tt(p, size)
        if f:
            return f
    return font_sans(size)


def font_serif_regular(size: int) -> ImageFont.ImageFont:
    for p in (
        FONTS_DIR / "PlayfairDisplay-Regular.ttf",
        FONTS_DIR / "CormorantGaramond-Regular.ttf",
        Path(r"C:\Windows\Fonts\georgia.ttf"),
        Path(r"C:\Windows\Fonts\times.ttf"),
    ):
        f = _tt(p, size)
        if f:
            return f
    return font_sans(size)


def font_serif_bold(size: int) -> ImageFont.ImageFont:
    for p in (
        Path(r"C:\Windows\Fonts\georgiab.ttf"),
        Path(r"C:\Windows\Fonts\timesbd.ttf"),
        FONTS_DIR / "PlayfairDisplay-Regular.ttf",
    ):
        f = _tt(p, size)
        if f:
            return f
    return font_serif_regular(size)


def font_sans(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    order = (
        [
            FONTS_DIR / "Montserrat-Bold.ttf",
            Path(r"C:\Windows\Fonts\segoeuib.ttf"),
            Path(r"C:\Windows\Fonts\arialbd.ttf"),
        ]
        if bold
        else [
            FONTS_DIR / "Montserrat-Regular.ttf",
            FONTS_DIR / "Inter-Regular.ttf",
            Path(r"C:\Windows\Fonts\segoeui.ttf"),
            Path(r"C:\Windows\Fonts\arial.ttf"),
        ]
    )
    for p in order:
        f = _tt(p, size)
        if f:
            return f
    return ImageFont.load_default()


# ── Helpers ──────────────────────────────────────────────────────────────────

def cover_crop(img: Image.Image, tw: int, th: int, *, bias_y: float = 0.38) -> Image.Image:
    src = img.convert("RGB")
    sw, sh = src.size
    if sw <= 0 or sh <= 0:
        return Image.new("RGB", (tw, th), T_CLASSIC.bg)
    scale = max(tw / sw, th / sh)
    nw, nh = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - tw) // 2)
    top = max(0, min(nh - th, int(round((nh - th) * bias_y)))) if nh > th else 0
    return resized.crop((left, top, left + tw, top + th))


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


def draw_tracked(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple,
    tracking: float = 0.9,
) -> int:
    x, y = xy
    for i, ch in enumerate(text):
        draw.text((x, y), ch, font=font, fill=fill)
        w, _ = text_size(draw, ch, font)
        x += w
        if i < len(text) - 1:
            x += int(round(tracking))
    return x - xy[0]


def tracked_width(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, tracking: float = 0.9
) -> int:
    if not text:
        return 0
    total = 0
    for i, ch in enumerate(text):
        total += text_size(draw, ch, font)[0]
        if i < len(text) - 1:
            total += int(round(tracking))
    return total


def soft_white_label(text: str, font: ImageFont.ImageFont) -> Image.Image:
    probe = Image.new("RGBA", (10, 10))
    pd = ImageDraw.Draw(probe)
    tw, th = text_size(pd, text, font)
    pad = 20
    layer = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for ox, oy in ((2, 3), (1, 2), (3, 3)):
        sd.text((pad + ox, pad + oy), text, font=font, fill=(0, 0, 0, 55))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=2.5))
    layer = Image.alpha_composite(layer, shadow)
    ld = ImageDraw.Draw(layer)
    ox, oy = pad, pad
    for dx in (-2, -1, 0, 1, 2):
        for dy in (-2, -1, 0, 1, 2):
            if dx or dy:
                ld.text((ox + dx, oy + dy), text, font=font, fill=(0, 0, 0, 220))
    ld.text((ox, oy), text, font=font, fill=(*WHITE, 255))
    return layer


def _ensure4(
    imgs: Sequence[Image.Image], captions: Sequence[str] | None
) -> tuple[list[Image.Image], tuple[str, str, str, str]]:
    if len(imgs) != 4:
        raise ValueError("Need exactly 4 images")
    caps = tuple(captions) if captions is not None else DEFAULT_CAPTIONS
    if len(caps) != 4:
        raise ValueError("Need exactly 4 captions")
    return [im.convert("RGB") for im in imgs], (caps[0], caps[1], caps[2], caps[3])


def new_canvas(theme: Theme) -> Image.Image:
    return Image.new("RGBA", (W, H), (*theme.bg, 255))


def draw_masthead(
    canvas: Image.Image,
    title: str,
    theme: Theme,
    *,
    y: int = 48,
    max_w: int | None = None,
    size: int = 44,
    italic: bool = True,
    underline: bool = True,
    tracking: float = 0,
    rule_w: int = 80,
) -> int:
    draw = ImageDraw.Draw(canvas)
    title_f = font_serif_italic(size) if italic else font_serif_regular(size)
    text = (title or DEFAULT_TITLE).strip() or DEFAULT_TITLE
    lines = wrap(draw, text, title_f, max_w or (W - 120))
    yy = y
    for line in lines:
        if tracking:
            tw = tracked_width(draw, line, title_f, tracking)
            draw_tracked(draw, ((W - tw) // 2, yy), line, title_f, (*theme.ink, 255), tracking)
            th = text_size(draw, line, title_f)[1]
        else:
            tw, th = text_size(draw, line, title_f)
            draw.text(((W - tw) // 2, yy), line, font=title_f, fill=theme.ink)
        yy += th + 6
    if underline:
        draw.line(
            (W // 2 - rule_w, yy + 10, W // 2 + rule_w, yy + 10),
            fill=(*theme.accent, 210),
            width=1,
        )
        return yy + 30
    return yy + 16


def draw_footer_title(canvas: Image.Image, title: str, theme: Theme) -> int:
    draw = ImageDraw.Draw(canvas)
    title_f = font_serif_italic(40)
    text = (title or DEFAULT_TITLE).strip() or DEFAULT_TITLE
    lines = wrap(draw, text, title_f, W - 140)
    line_h = text_size(draw, "Ag", title_f)[1] + 6
    block_h = len(lines) * line_h + 28
    top = H - block_h - 28
    draw.line((W // 2 - 50, top, W // 2 + 50, top), fill=(*theme.accent, 210), width=1)
    yy = top + 10
    for line in lines:
        tw, th = text_size(draw, line, title_f)
        draw.text(((W - tw) // 2, yy), line, font=title_f, fill=theme.ink)
        yy += th + 6
    return top


def photo_tile(
    img: Image.Image,
    tw: int,
    th: int,
    theme: Theme,
    *,
    frame: int = 2,
    double_border: bool = False,
) -> Image.Image:
    outer_w = tw + frame * 2 + (6 if double_border else 0)
    outer_h = th + frame * 2 + (6 if double_border else 0)
    tile = cover_crop(img, tw, th)
    card = Image.new("RGBA", (outer_w, outer_h), (*theme.card, 255))
    ox = frame + (3 if double_border else 0)
    oy = frame + (3 if double_border else 0)
    card.paste(tile.convert("RGBA"), (ox, oy))
    cd = ImageDraw.Draw(card)
    if double_border:
        cd.rectangle((0, 0, outer_w - 1, outer_h - 1), outline=theme.frame, width=1)
        cd.rectangle((3, 3, outer_w - 4, outer_h - 4), outline=theme.accent, width=1)
    else:
        cd.rectangle((0, 0, outer_w - 1, outer_h - 1), outline=theme.frame, width=1)
    return card


def paste(canvas: Image.Image, card: Image.Image, xy: tuple[int, int]) -> None:
    canvas.alpha_composite(card, xy)


def grid_2x2(
    top: int, bot: int, *, pad: int = 28, gap: int = 22
) -> tuple[list[tuple[int, int]], int, int]:
    avail_h = bot - top
    cell_w = (W - pad * 2 - gap) // 2
    cell_h = (avail_h - gap) // 2
    positions = [
        (pad, top),
        (pad + cell_w + gap, top),
        (pad, top + cell_h + gap),
        (pad + cell_w + gap, top + cell_h + gap),
    ]
    return positions, cell_w, cell_h


def _base_label(caption: str) -> str:
    if "·" in caption:
        return caption.split("·", 1)[1].strip()
    return caption.strip()


# ── 01 classic_overlay — terracotta accent, white italic on photos ───────────

def layout_01_classic_overlay(
    imgs: Sequence[Image.Image],
    captions: Sequence[str] | None = None,
    title: str = DEFAULT_TITLE,
) -> Image.Image:
    theme = T_CLASSIC
    imgs, caps = _ensure4(imgs, captions)
    canvas = new_canvas(theme)
    top = draw_masthead(canvas, title, theme, size=44)
    positions, cell_w, cell_h = grid_2x2(top, H - 36)
    frame = 2
    pw, ph = cell_w - frame * 2, cell_h - frame * 2
    cap_f = font_serif_italic(28)
    for i, (x, y) in enumerate(positions):
        card = photo_tile(imgs[i], pw, ph, theme, frame=frame)
        card.alpha_composite(soft_white_label(caps[i], cap_f), (10, 6))
        paste(canvas, card, (x, y))
    return canvas


# ── 02 bottom_white_captions — cooler stone, tracked regular serif ───────────

def layout_02_bottom_white_captions(
    imgs: Sequence[Image.Image],
    captions: Sequence[str] | None = None,
    title: str = DEFAULT_TITLE,
) -> Image.Image:
    theme = T_KIN
    imgs, caps = _ensure4(imgs, captions)
    canvas = new_canvas(theme)
    top = draw_masthead(canvas, title, theme, size=42, italic=False, tracking=1.0, rule_w=60)
    pad, gap, frame = 28, 22, 2
    caption_h = 58
    positions, cell_w, cell_h = grid_2x2(top, H - 32, pad=pad, gap=gap)
    photo_h = cell_h - caption_h
    photo_w = cell_w - frame * 2
    cap_f = font_serif_regular(25)
    for i, (x, y) in enumerate(positions):
        card = Image.new("RGBA", (cell_w, cell_h), (*theme.card, 255))
        tile = cover_crop(imgs[i], photo_w, photo_h)
        card.paste(tile.convert("RGBA"), (frame, frame))
        cd = ImageDraw.Draw(card)
        cd.rectangle((0, 0, cell_w - 1, cell_h - 1), outline=theme.frame, width=1)
        cd.line(
            (frame, frame + photo_h, cell_w - frame - 1, frame + photo_h),
            fill=theme.accent,
            width=1,
        )
        label = caps[i].upper()
        tw = tracked_width(cd, label, cap_f, tracking=0.8)
        th = text_size(cd, label, cap_f)[1]
        draw_tracked(
            cd,
            ((cell_w - tw) // 2, frame + photo_h + (caption_h - th) // 2 - 1),
            label,
            cap_f,
            (*theme.caption, 255),
            tracking=0.8,
        )
        paste(canvas, card, (x, y))
    return canvas


# ── 03 cereal_wide_margins — warm cream, airy, smaller soft title ────────────

def layout_03_cereal_wide_margins(
    imgs: Sequence[Image.Image],
    captions: Sequence[str] | None = None,
    title: str = DEFAULT_TITLE,
) -> Image.Image:
    theme = T_CEREAL
    imgs, caps = _ensure4(imgs, captions)
    canvas = new_canvas(theme)
    top = draw_masthead(canvas, title, theme, y=56, size=40, rule_w=40)
    pad, gap = 52, 20
    positions, cell_w, cell_h = grid_2x2(top, H - 52, pad=pad, gap=gap)
    frame = 1
    pw, ph = cell_w - frame * 2, cell_h - frame * 2
    cap_f = font_serif_italic(26)
    for i, (x, y) in enumerate(positions):
        card = photo_tile(imgs[i], pw, ph, theme, frame=frame)
        card.alpha_composite(soft_white_label(caps[i], cap_f), (8, 6))
        paste(canvas, card, (x, y))
    return canvas


# ── 04 hairline_thin_dividers — blush linen, flush photos, beige rules ───────

def layout_04_hairline_thin_dividers(
    imgs: Sequence[Image.Image],
    captions: Sequence[str] | None = None,
    title: str = DEFAULT_TITLE,
) -> Image.Image:
    theme = T_DIVIDER
    imgs, caps = _ensure4(imgs, captions)
    canvas = new_canvas(theme)
    top = draw_masthead(canvas, title, theme, size=42, rule_w=100)
    pad = 32
    positions, cell_w, cell_h = grid_2x2(top, H - 36, pad=pad, gap=0)
    draw = ImageDraw.Draw(canvas)
    mid_x = pad + cell_w
    mid_y = top + cell_h
    right = pad + cell_w * 2
    bot = top + cell_h * 2
    draw.line((mid_x, top + 8, mid_x, bot - 8), fill=theme.divider, width=2)
    draw.line((pad + 8, mid_y, right - 8, mid_y), fill=theme.divider, width=2)
    cap_f = font_serif_italic(26)
    for i, (x, y) in enumerate(positions):
        inset = 8
        pw, ph = cell_w - inset * 2, cell_h - inset * 2
        tile = cover_crop(imgs[i], pw, ph)
        canvas.paste(tile, (x + inset, y + inset))
        canvas.alpha_composite(soft_white_label(caps[i], cap_f), (x + inset + 8, y + inset + 6))
    return canvas


# ── 05 roman_numerals — wine accent, bold roman + italic name ────────────────

def layout_05_roman_numerals(
    imgs: Sequence[Image.Image],
    captions: Sequence[str] | None = None,
    title: str = DEFAULT_TITLE,
) -> Image.Image:
    theme = T_ROMAN
    imgs, caps = _ensure4(imgs, captions)
    canvas = new_canvas(theme)
    top = draw_masthead(canvas, title, theme, size=42, italic=True, rule_w=48)
    positions, cell_w, cell_h = grid_2x2(top, H - 36, pad=30, gap=20)
    frame = 2
    caption_h = 52
    pw = cell_w - frame * 2
    ph = cell_h - caption_h - frame
    num_f = font_serif_bold(24)
    name_f = font_serif_italic(22)
    for i, (x, y) in enumerate(positions):
        card = Image.new("RGBA", (cell_w, cell_h), (*theme.band, 255))
        tile = cover_crop(imgs[i], pw, ph)
        card.paste(tile.convert("RGBA"), (frame, frame))
        cd = ImageDraw.Draw(card)
        cd.rectangle((0, 0, cell_w - 1, cell_h - 1), outline=theme.frame, width=1)
        roman = ROMAN[i]
        base = _base_label(caps[i])
        rw, rh = text_size(cd, roman, num_f)
        cd.text((14, frame + ph + (caption_h - rh) // 2), roman, font=num_f, fill=theme.accent)
        nw, nh = text_size(cd, base, name_f)
        cd.text(
            (14 + rw + 14, frame + ph + (caption_h - nh) // 2),
            base,
            font=name_f,
            fill=theme.caption,
        )
        paste(canvas, card, (x, y))
    return canvas


# ── 06 museum_matting — cool gray linen, wide passepartout, sans labels ──────

def layout_06_museum_matting(
    imgs: Sequence[Image.Image],
    captions: Sequence[str] | None = None,
    title: str = DEFAULT_TITLE,
) -> Image.Image:
    theme = T_MUSEUM
    imgs, caps = _ensure4(imgs, captions)
    canvas = new_canvas(theme)
    top = draw_masthead(canvas, title, theme, y=50, size=40, italic=False, tracking=1.6, rule_w=36)
    pad, gap = 42, 30
    positions, cell_w, cell_h = grid_2x2(top, H - 44, pad=pad, gap=gap)
    matte = 22
    for i, (x, y) in enumerate(positions):
        mat = Image.new("RGBA", (cell_w, cell_h), (*theme.card, 255))
        md = ImageDraw.Draw(mat)
        md.rectangle((0, 0, cell_w - 1, cell_h - 1), outline=theme.frame, width=1)
        pw = cell_w - matte * 2
        ph = cell_h - matte * 2 - 40
        tile = cover_crop(imgs[i], pw, ph)
        mat.paste(tile.convert("RGBA"), (matte, matte))
        name_f = font_sans(20)
        label = caps[i].upper()
        tw = tracked_width(md, label, name_f, tracking=0.8)
        th = text_size(md, label, name_f)[1]
        draw_tracked(
            md,
            ((cell_w - tw) // 2, matte + ph + 10),
            label,
            name_f,
            (*theme.caption, 255),
            tracking=0.8,
        )
        paste(canvas, mat, (x, y))
    return canvas


# ── 07 double_border_gallery — sage accent double frame, quiet type ──────────

def layout_07_double_border_gallery(
    imgs: Sequence[Image.Image],
    captions: Sequence[str] | None = None,
    title: str = DEFAULT_TITLE,
) -> Image.Image:
    theme = T_GALLERY
    imgs, caps = _ensure4(imgs, captions)
    canvas = new_canvas(theme)
    top = draw_masthead(canvas, title, theme, size=40, italic=True, rule_w=70)
    positions, cell_w, cell_h = grid_2x2(top, H - 36, pad=30, gap=24)
    for i, (x, y) in enumerate(positions):
        pw, ph = cell_w - 12, cell_h - 12
        card = photo_tile(imgs[i], pw, ph, theme, frame=1, double_border=True)
        # caption bottom-left inside frame, small regular
        short = _base_label(caps[i])
        label = soft_white_label(f"{i + 1:02d}  {short}", font_serif_regular(24))
        card.alpha_composite(label, (14, card.size[1] - label.size[1] - 8))
        paste(canvas, card, (x, y))
    return canvas


# ── 08 polaroid_editorial — warm paper, wide bottom band, soft italic ────────

def layout_08_polaroid_editorial(
    imgs: Sequence[Image.Image],
    captions: Sequence[str] | None = None,
    title: str = DEFAULT_TITLE,
) -> Image.Image:
    theme = T_POLAROID
    imgs, caps = _ensure4(imgs, captions)
    canvas = new_canvas(theme)
    top = draw_masthead(canvas, title, theme, size=40, rule_w=55)
    pad, gap = 34, 22
    positions, cell_w, cell_h = grid_2x2(top, H - 40, pad=pad, gap=gap)
    bottom_band = 64
    side = 12
    for i, (x, y) in enumerate(positions):
        card = Image.new("RGBA", (cell_w, cell_h), (*theme.card, 255))
        pw = cell_w - side * 2
        ph = cell_h - side - bottom_band
        tile = cover_crop(imgs[i], pw, ph)
        card.paste(tile.convert("RGBA"), (side, side))
        cd = ImageDraw.Draw(card)
        cd.rectangle((0, 0, cell_w - 1, cell_h - 1), outline=theme.frame, width=1)
        # warm accent hairline above caption
        cd.line(
            (side + 20, side + ph + 10, cell_w - side - 20, side + ph + 10),
            fill=(*theme.accent, 160),
            width=1,
        )
        name_f = font_serif_italic(22)
        label = caps[i]
        tw, th = text_size(cd, label, name_f)
        cd.text(
            ((cell_w - tw) // 2, side + ph + (bottom_band - th) // 2 + 2),
            label,
            font=name_f,
            fill=theme.caption,
        )
        paste(canvas, card, (x, y))
    return canvas


# ── 09 footer_title — dusty rose rule, title below grid ──────────────────────

def layout_09_footer_title(
    imgs: Sequence[Image.Image],
    captions: Sequence[str] | None = None,
    title: str = DEFAULT_TITLE,
) -> Image.Image:
    theme = T_FOOTER
    imgs, caps = _ensure4(imgs, captions)
    canvas = new_canvas(theme)
    footer_top = draw_footer_title(canvas, title, theme)
    # small top kicker
    draw = ImageDraw.Draw(canvas)
    kick_f = font_sans(13, bold=True)
    kick = "HAIR PROTOCOL"
    tw = tracked_width(draw, kick, kick_f, tracking=2.5)
    draw_tracked(draw, ((W - tw) // 2, 28), kick, kick_f, (*theme.accent, 255), tracking=2.5)

    positions, cell_w, cell_h = grid_2x2(52, footer_top - 18, pad=28, gap=18)
    frame = 2
    pw, ph = cell_w - frame * 2, cell_h - frame * 2
    for i, (x, y) in enumerate(positions):
        card = photo_tile(imgs[i], pw, ph, theme, frame=frame)
        card.alpha_composite(soft_white_label(caps[i], font_serif_italic(26)), (10, 6))
        paste(canvas, card, (x, y))
    return canvas


# ── 10 two_tone_serif — sage linen, regular number + italic name ─────────────

def layout_10_two_tone_serif(
    imgs: Sequence[Image.Image],
    captions: Sequence[str] | None = None,
    title: str = DEFAULT_TITLE,
) -> Image.Image:
    theme = T_TWOTONE
    imgs, caps = _ensure4(imgs, captions)
    canvas = new_canvas(theme)
    top = draw_masthead(canvas, title, theme, size=42, italic=False, tracking=1.0, rule_w=90)
    positions, cell_w, cell_h = grid_2x2(top, H - 36, pad=28, gap=20)
    frame = 2
    band = 54
    for i, (x, y) in enumerate(positions):
        card = Image.new("RGBA", (cell_w, cell_h), (*theme.band, 255))
        pw = cell_w - frame * 2
        ph = cell_h - band - frame
        tile = cover_crop(imgs[i], pw, ph)
        card.paste(tile.convert("RGBA"), (frame, frame))
        cd = ImageDraw.Draw(card)
        cd.rectangle((0, 0, cell_w - 1, cell_h - 1), outline=theme.frame, width=1)
        cd.rectangle((0, frame + ph, cell_w - 1, cell_h - 1), fill=(*theme.band, 255))
        num = f"{i + 1:02d}"
        base = _base_label(caps[i])
        num_f = font_serif_bold(20)
        name_f = font_serif_italic(22)
        nw, nh = text_size(cd, num, num_f)
        cd.text((14, frame + ph + (band - nh) // 2), num, font=num_f, fill=theme.accent)
        mid = "  ·  "
        mid_f = font_serif_regular(18)
        mw, _ = text_size(cd, mid, mid_f)
        cd.text((14 + nw, frame + ph + (band - nh) // 2), mid, font=mid_f, fill=theme.frame)
        bw, bh = text_size(cd, base, name_f)
        cd.text(
            (14 + nw + mw, frame + ph + (band - bh) // 2),
            base,
            font=name_f,
            fill=theme.caption,
        )
        paste(canvas, card, (x, y))
    return canvas


# ── 11 circled_numbers — lilac accent, filled number badge + italic ──────────

def _draw_index_badge(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    n: int,
    theme: Theme,
) -> int:
    """Filled circular index; returns right edge x for caption placement."""
    r = 17
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        fill=(*theme.accent, 255),
    )
    num = str(n)
    num_f = font_sans(15, bold=True)
    # Optical center via textbbox (ascent/descent aware)
    left, top, right, bottom = draw.textbbox((0, 0), num, font=num_f)
    tw, th = right - left, bottom - top
    tx = cx - tw // 2 - left
    ty = cy - th // 2 - top
    draw.text((tx, ty), num, font=num_f, fill=WHITE)
    return cx + r


def layout_11_circled_numbers(
    imgs: Sequence[Image.Image],
    captions: Sequence[str] | None = None,
    title: str = DEFAULT_TITLE,
) -> Image.Image:
    theme = T_CIRCLED
    imgs, caps = _ensure4(imgs, captions)
    canvas = new_canvas(theme)
    top = draw_masthead(canvas, title, theme, size=42, rule_w=64)
    positions, cell_w, cell_h = grid_2x2(top, H - 36, pad=28, gap=20)
    frame = 2
    band = 58
    for i, (x, y) in enumerate(positions):
        card = Image.new("RGBA", (cell_w, cell_h), (*theme.band, 255))
        pw = cell_w - frame * 2
        ph = cell_h - band - frame
        tile = cover_crop(imgs[i], pw, ph)
        card.paste(tile.convert("RGBA"), (frame, frame))
        cd = ImageDraw.Draw(card)
        cd.rectangle((0, 0, cell_w - 1, cell_h - 1), outline=theme.frame, width=1)
        cd.rectangle((1, frame + ph, cell_w - 2, cell_h - 2), fill=(*theme.band, 255))

        cy = frame + ph + band // 2
        badge_right = _draw_index_badge(cd, 32, cy, i + 1, theme)

        base = _base_label(caps[i])
        name_f = font_serif_italic(22)
        left, top, right, bottom = cd.textbbox((0, 0), base, font=name_f)
        bh = bottom - top
        cd.text((badge_right + 14, cy - bh // 2 - top), base, font=name_f, fill=theme.caption)
        paste(canvas, card, (x, y))
    return canvas


# ── Registry (11 surviving layouts, renumbered) ──────────────────────────────

LAYOUT_NAMES: dict[int, str] = {
    1: "classic_overlay",
    2: "bottom_white_captions",
    3: "cereal_wide_margins",
    4: "hairline_thin_dividers",
    5: "roman_numerals",
    6: "museum_matting",
    7: "double_border_gallery",
    8: "polaroid_editorial",
    9: "footer_title",
    10: "two_tone_serif",
    11: "circled_numbers",
}

LAYOUT_REGISTRY: dict[int, LayoutFn] = {
    1: layout_01_classic_overlay,
    2: layout_02_bottom_white_captions,
    3: layout_03_cereal_wide_margins,
    4: layout_04_hairline_thin_dividers,
    5: layout_05_roman_numerals,
    6: layout_06_museum_matting,
    7: layout_07_double_border_gallery,
    8: layout_08_polaroid_editorial,
    9: layout_09_footer_title,
    10: layout_10_two_tone_serif,
    11: layout_11_circled_numbers,
}

assert set(LAYOUT_REGISTRY) == set(range(1, 12))
assert set(LAYOUT_NAMES) == set(LAYOUT_REGISTRY)


def layout_key(n: int) -> str:
    if n not in LAYOUT_REGISTRY:
        raise KeyError(f"Unknown layout id: {n}")
    return f"layout_{n:02d}"


def layout_id_from_key(key: str) -> int:
    if key.startswith("layout_"):
        return int(key.split("_", 1)[1])
    if key in ("overlay", "classic_overlay"):
        return 1
    if key in ("bottom_captions", "bottom_white_captions"):
        return 2
    raise KeyError(f"Unknown layout key: {key}")


def render_layout(
    layout_id: int,
    imgs: Sequence[Image.Image],
    captions: Sequence[str] | None = None,
    title: str = DEFAULT_TITLE,
) -> Image.Image:
    fn = LAYOUT_REGISTRY.get(layout_id)
    if fn is None:
        raise KeyError(f"Unknown layout id: {layout_id}")
    return fn(imgs, captions, title=title)


__all__ = [
    "W",
    "H",
    "LAYOUT_REGISTRY",
    "LAYOUT_NAMES",
    "layout_key",
    "layout_id_from_key",
    "render_layout",
    "DEFAULT_TITLE",
    "DEFAULT_CAPTIONS",
]
