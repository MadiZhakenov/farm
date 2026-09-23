#!/usr/bin/env python3
"""
Two conversion visual formats — 3:4 (1080×1440).

  Format 1  Apple Notes aesthetic
  Format 2  Annotated flatlay with arrows

Usage:
  python build_two_formats.py
  python build_two_formats.py --dir E:\\Users\\Desktop\\download
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1440
ROOT = Path(__file__).resolve().parent
DEFAULT_SRC = Path(r"E:\Users\Desktop\download")
OUT_DIR = ROOT / "out" / "test_formats"

# Apple Notes palette
NOTES_BG = (251, 251, 252)       # #FBFBFC
NOTES_INK = (28, 28, 30)         # #1C1C1E
NOTES_MUTED = (142, 142, 147)    # #8E8E93
NOTES_YELLOW = (228, 168, 52)    # #E4A834  (check / back chevron)
NOTES_LINK = (0, 122, 255)       # iOS blue-ish fallback for share

# Flatlay palette
FLAT_INK = (34, 34, 34)          # #222222
FLAT_CHIP = (255, 255, 255, 210)
FLAT_BANNER = (255, 255, 255, 200)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


# ── Fonts ────────────────────────────────────────────────────────────────────

def _truetype(path: Path | str, size: int) -> ImageFont.FreeTypeFont | None:
    try:
        p = Path(path)
        if p.is_file():
            return ImageFont.truetype(str(p), size)
    except OSError:
        pass
    return None


def font_sf(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    """San Francisco stand-ins: Segoe UI / Montserrat / Arial."""
    order: list[Path] = []
    if bold:
        order += [
            ROOT / "fonts" / "Montserrat-Bold.ttf",
            Path(r"C:\Windows\Fonts\segoeuib.ttf"),
            Path(r"C:\Windows\Fonts\arialbd.ttf"),
            Path(r"C:\Windows\Fonts\msyhbd.ttc"),
        ]
    else:
        order += [
            ROOT / "fonts" / "Montserrat-Regular.ttf",
            ROOT / "fonts" / "Montserrat-Medium.ttf",
            Path(r"C:\Windows\Fonts\segoeui.ttf"),
            Path(r"C:\Windows\Fonts\arial.ttf"),
        ]
    for p in order:
        f = _truetype(p, size)
        if f is not None:
            return f
    return ImageFont.load_default()


def font_serif(size: int, *, italic: bool = False) -> ImageFont.ImageFont:
    order = (
        [
            Path(r"C:\Windows\Fonts\georgiai.ttf"),
            Path(r"C:\Windows\Fonts\timesi.ttf"),
        ]
        if italic
        else [
            Path(r"C:\Windows\Fonts\georgia.ttf"),
            Path(r"C:\Windows\Fonts\times.ttf"),
        ]
    )
    for p in order:
        f = _truetype(p, size)
        if f is not None:
            return f
    return font_sf(size)


def font_hand(size: int) -> ImageFont.ImageFont:
    for p in (
        Path(r"C:\Windows\Fonts\segoesc.ttf"),
        Path(r"C:\Windows\Fonts\segoepr.ttf"),
        Path(r"C:\Windows\Fonts\segoescb.ttf"),
        Path(r"C:\Windows\Fonts\Gabriola.ttf"),
    ):
        f = _truetype(p, size)
        if f is not None:
            return f
    return font_serif(size, italic=True)


def font_emoji(size: int) -> ImageFont.ImageFont | None:
    for p in (
        Path(r"C:\Windows\Fonts\seguiemj.ttf"),
        Path(r"C:\Windows\Fonts\SegoeUIEmoji.ttf"),
    ):
        f = _truetype(p, size)
        if f is not None:
            return f
    return None


# ── Image helpers ────────────────────────────────────────────────────────────

def cover_crop(img: Image.Image, tw: int, th: int, *, bias_y: float = 0.4) -> Image.Image:
    src = img.convert("RGB")
    sw, sh = src.size
    if sw <= 0 or sh <= 0:
        return Image.new("RGB", (tw, th), NOTES_BG)
    scale = max(tw / sw, th / sh)
    nw, nh = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - tw) // 2)
    top = max(0, min(nh - th, int(round((nh - th) * bias_y)))) if nh > th else 0
    return resized.crop((left, top, left + tw, top + th))


def rounded_card(photo: Image.Image, size: tuple[int, int], radius: int = 16) -> Image.Image:
    tw, th = size
    tile = cover_crop(photo, tw, th)
    card = tile.convert("RGBA")
    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, tw - 1, th - 1), radius=radius, fill=255)
    out = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    out.paste(card, (0, 0), mask)
    return out


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_w: int,
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        if _text_size(draw, trial, font)[0] <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def soft_paper(base: Image.Image, seed: int = 7) -> Image.Image:
    """Very subtle Notes paper grain."""
    import random

    rng = random.Random(seed)
    w, h = base.size
    noise = Image.new("L", (w, h), 128)
    px = noise.load()
    assert px is not None
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            v = 128 + rng.randint(-10, 10)
            for dy in range(3):
                for dx in range(3):
                    if x + dx < w and y + dy < h:
                        px[x + dx, y + dy] = v
    noise = noise.filter(ImageFilter.GaussianBlur(0.8))
    canvas = base.convert("RGBA")
    grain = Image.merge("RGBA", (noise, noise, noise, Image.new("L", (w, h), 16)))
    return Image.alpha_composite(canvas, grain)


# ── Source picking ───────────────────────────────────────────────────────────

def _list_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_EXTS]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def pick_assets(folder: Path) -> dict[str, Path]:
    """
    Resolve:
      hair     — mirror / part
      gummies  — vitamins on palm
      silk     — pillowcase
      scalp    — massager
      flatlay  — combined product shot if present
    """
    files = _list_images(folder)
    if not files:
        raise FileNotFoundError(f"No images in {folder}")

    slots: dict[str, Path | None] = {
        "hair": None,
        "gummies": None,
        "silk": None,
        "scalp": None,
        "flatlay": None,
    }
    hints = {
        "flatlay": ("flatlay", "pillowcase_and", "silk_pillowcase_and", "starter"),
        "hair": ("mirror", "hair", "part", "holding_hair"),
        "gummies": ("gummi", "gummy", "vitamin"),
        "silk": ("pillow", "bed", "silk", "messy_bed"),
        "scalp": ("scalp", "brush", "sink", "massage"),
    }
    remaining = list(files)
    for key, words in hints.items():
        for p in remaining:
            name = p.stem.lower()
            if any(w in name for w in words):
                # Prefer dedicated flatlay match for flatlay key
                if key == "flatlay" and ("and" in name or "flatlay" in name or "starter" in name):
                    slots[key] = p
                    remaining.remove(p)
                    break
                if key != "flatlay":
                    slots[key] = p
                    remaining.remove(p)
                    break
        # flatlay fallback: newest multi-subject name
        if key == "flatlay" and slots[key] is None:
            for p in remaining:
                if "and" in p.stem.lower():
                    slots[key] = p
                    remaining.remove(p)
                    break

    # Fill missing from leftovers
    for key in slots:
        if slots[key] is None and remaining:
            slots[key] = remaining.pop(0)

    missing = [k for k, v in slots.items() if v is None and k != "flatlay"]
    if missing:
        raise FileNotFoundError(f"Missing assets {missing} in {folder}")

    return {k: v for k, v in slots.items() if v is not None}  # type: ignore[misc]


# ── FORMAT 1: Apple Notes ────────────────────────────────────────────────────

CHECKLIST = (
    "pure silk pillowcase (stops friction breakage)",
    "silicone scalp massager (3 mins in shower for blood flow)",
    "targeted hair gummies (Amazon, 2 daily — game changer)",
    "zero tight ponytails for 90 days",
)


def _aa_icon(draw_big_fn, size: int, scale: int = 5) -> Image.Image:
    """Draw vector icon at high-res then downscale for clean antialiasing."""
    big = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    draw_big_fn(ImageDraw.Draw(big), scale)
    return big.resize((size, size), Image.Resampling.LANCZOS)


def icon_notes_back(size: int = 32) -> Image.Image:
    """Bold iOS-style yellow back chevron."""

    def _draw(d: ImageDraw.ImageDraw, s: int) -> None:
        S = size * s
        # Filled chevron polygon (crisp, not a skinny polyline)
        tip_x = S * 0.22
        right_x = S * 0.78
        mid_y = S * 0.50
        half = S * 0.38
        thick = S * 0.14  # arm thickness
        # Outer chevron path
        outer = [
            (right_x, mid_y - half),
            (tip_x, mid_y),
            (right_x, mid_y + half),
            (right_x, mid_y + half - thick),
            (tip_x + thick * 1.35, mid_y),
            (right_x, mid_y - half + thick),
        ]
        d.polygon(outer, fill=NOTES_YELLOW)

    return _aa_icon(_draw, size, scale=6)


def icon_notes_share(size: int = 34) -> Image.Image:
    """Bold iOS share: filled rounded bars for tray + arrow."""

    def _draw(d: ImageDraw.ImageDraw, s: int) -> None:
        S = size * s
        t = max(3, int(3.8 * s))
        L, R = S * 0.18, S * 0.82
        T, B = S * 0.50, S * 0.90
        rr = t / 2
        # left / right posts
        d.rounded_rectangle((L - rr, T, L + rr, B - rr), radius=rr, fill=NOTES_YELLOW)
        d.rounded_rectangle((R - rr, T, R + rr, B - rr), radius=rr, fill=NOTES_YELLOW)
        # bottom
        d.rounded_rectangle((L, B - t, R, B), radius=rr, fill=NOTES_YELLOW)
        # top shoulders
        sh = S * 0.17
        d.rounded_rectangle((L - rr, T - rr, L + sh, T + rr), radius=rr, fill=NOTES_YELLOW)
        d.rounded_rectangle((R - sh, T - rr, R + rr, T + rr), radius=rr, fill=NOTES_YELLOW)
        # up arrow
        cx = S * 0.50
        tip = S * 0.05
        ah = S * 0.26
        d.polygon(
            [(cx, tip), (cx - ah, tip + ah), (cx + ah, tip + ah)],
            fill=NOTES_YELLOW,
        )
        d.rounded_rectangle(
            (cx - rr, tip + ah * 0.4, cx + rr, S * 0.66),
            radius=rr,
            fill=NOTES_YELLOW,
        )

    return _aa_icon(_draw, size, scale=6)


def icon_notes_check(size: int = 30) -> Image.Image:
    """Yellow filled circle + bold white check."""

    def _draw(d: ImageDraw.ImageDraw, s: int) -> None:
        S = size * s
        pad = int(S * 0.02)
        d.ellipse((pad, pad, S - 1 - pad, S - 1 - pad), fill=NOTES_YELLOW)
        stroke = max(3, int(round(3.2 * s)))
        p1 = (S * 0.26, S * 0.52)
        p2 = (S * 0.44, S * 0.70)
        p3 = (S * 0.76, S * 0.32)
        d.line([p1, p2, p3], fill=(255, 255, 255, 255), width=stroke, joint="curve")
        r = stroke // 2 + 1
        for pt in (p1, p2, p3):
            d.ellipse((pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r), fill=(255, 255, 255))

    return _aa_icon(_draw, size)


def build_format_1_notes(hair: Image.Image, gummies: Image.Image) -> Image.Image:
    canvas = Image.new("RGBA", (W, H), (*NOTES_BG, 255))
    canvas = soft_paper(canvas, seed=3)
    draw = ImageDraw.Draw(canvas)

    # ── Top system bar (iOS Notes chrome) ────────────────────────────────
    bar_y = 52
    nav_font = font_sf(28, bold=False)
    date_font = font_sf(20, bold=False)

    back = icon_notes_back(30)
    canvas.alpha_composite(back, (38, bar_y))
    draw.text((76, bar_y), "Notes", font=nav_font, fill=NOTES_YELLOW)

    share = icon_notes_share(34)
    canvas.alpha_composite(share, (W - 42 - 34, bar_y - 2))

    # Date under nav, left-aligned
    date_str = "September 23, 2026 at 10:14 AM"
    draw.text((48, bar_y + 46), date_str, font=date_font, fill=NOTES_MUTED)

    # ── Title ────────────────────────────────────────────────────────────
    title_font = font_sf(44, bold=True)
    title = "hair shedding protocol (what actually worked)"
    title_x = 48
    title_y = bar_y + 88
    max_title_w = W - 96
    title_lines = wrap_text(draw, title, title_font, max_title_w)
    ty = title_y
    line_gap = 6
    for line in title_lines:
        draw.text((title_x, ty), line, font=title_font, fill=NOTES_INK)
        th = _text_size(draw, line, title_font)[1]
        ty += th + line_gap

    # ── Two photo cards (slightly larger to fill dead space) ─────────────
    photos_y = ty + 28
    gap = 16
    margin = 44
    card_w = (W - margin * 2 - gap) // 2
    card_h = int(card_w * 1.20)

    card_hair = rounded_card(hair, (card_w, card_h), radius=16)
    card_gum = rounded_card(gummies, (card_w, card_h), radius=16)
    canvas.alpha_composite(card_hair, (margin, photos_y))
    canvas.alpha_composite(card_gum, (margin + card_w + gap, photos_y))

    # ── Checklist ────────────────────────────────────────────────────────
    list_y = photos_y + card_h + 36
    body_font = font_sf(27, bold=False)
    check = icon_notes_check(28)
    left = 50
    text_x = left + 28 + 14
    max_body_w = W - text_x - 44
    row_gap = 22
    line_h = 34

    draw = ImageDraw.Draw(canvas)
    cy = list_y
    for item in CHECKLIST:
        lines = wrap_text(draw, item, body_font, max_body_w)
        canvas.alpha_composite(check, (left, cy + 2))
        for i, line in enumerate(lines):
            draw.text((text_x, cy + i * line_h), line, font=body_font, fill=NOTES_INK)
        cy += max(32, len(lines) * line_h) + row_gap

    return canvas


# ── FORMAT 2: Annotated flatlay ──────────────────────────────────────────────

def _arrow(
    draw: ImageDraw.ImageDraw,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    color: tuple = (*FLAT_INK, 235),
    width: int = 2,
    bend: float = 0.12,
) -> None:
    """Short elegant curve ending ON the subject (not past it)."""
    dx, dy = x1 - x0, y1 - y0
    dist = math.hypot(dx, dy) or 1.0
    # Pull tip back 2px so arrowhead sits on the surface of the object
    pull = min(4.0, dist * 0.02)
    x1 = x1 - dx / dist * pull
    y1 = y1 - dy / dist * pull
    dx, dy = x1 - x0, y1 - y0

    mx = (x0 + x1) / 2 - dy * bend
    my = (y0 + y1) / 2 + dx * bend
    pts: list[tuple[float, float]] = []
    n = 20
    for i in range(n + 1):
        t = i / n
        xb = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * mx + t**2 * x1
        yb = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * my + t**2 * y1
        pts.append((xb, yb))

    shadow = [(p[0] + 1.2, p[1] + 1.2) for p in pts]
    draw.line(shadow, fill=(0, 0, 0, 40), width=width + 1, joint="curve")
    draw.line(pts, fill=color, width=width, joint="curve")

    ang = math.atan2(pts[-1][1] - pts[-3][1], pts[-1][0] - pts[-3][0])
    ah, spread = 16, 0.55
    # Filled arrowhead (more readable than open V)
    a1 = (x1 - ah * math.cos(ang - spread), y1 - ah * math.sin(ang - spread))
    a2 = (x1 - ah * math.cos(ang + spread), y1 - ah * math.sin(ang + spread))
    draw.polygon([(x1, y1), a1, a2], fill=color)


def _chip_label(
    canvas: Image.Image,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.ImageFont,
    *,
    anchor: str = "left",
) -> tuple[int, int, int, int]:
    """Semi-transparent label chip. Returns bbox."""
    draw = ImageDraw.Draw(canvas)
    tw, th = _text_size(draw, text, font)
    pad_x, pad_y = 14, 8
    bw, bh = tw + pad_x * 2, th + pad_y * 2
    tx, ty = xy
    if anchor == "right":
        tx -= bw
    elif anchor == "center":
        tx -= bw // 2

    chip = Image.new("RGBA", (bw + 6, bh + 6), (0, 0, 0, 0))
    # whisper shadow
    sd = ImageDraw.Draw(chip)
    sd.rounded_rectangle((3, 4, bw + 2, bh + 3), radius=bh // 2, fill=(0, 0, 0, 35))
    chip = chip.filter(ImageFilter.GaussianBlur(2))
    cd = ImageDraw.Draw(chip)
    cd.rounded_rectangle((1, 1, bw, bh), radius=bh // 2, fill=FLAT_CHIP)
    cd.text((1 + pad_x, 1 + pad_y - 1), text, font=font, fill=(*FLAT_INK, 255))
    canvas.alpha_composite(chip, (tx - 1, ty - 1))
    return (tx, ty, tx + bw, ty + bh)


def _arrow_from_chip(
    box: tuple[int, int, int, int],
    tip: tuple[int, int],
) -> tuple[float, float]:
    """Start just outside the chip edge, aimed at the tip (never through the text)."""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    tx, ty = tip
    candidates = (
        (cx, y1),  # bottom
        (cx, y0),  # top
        (x1, cy),  # right
        (x0, cy),  # left
    )
    bx, by = min(candidates, key=lambda p: (p[0] - tx) ** 2 + (p[1] - ty) ** 2)
    # Nudge 10px outward from chip toward tip
    dx, dy = tx - bx, ty - by
    dist = math.hypot(dx, dy) or 1.0
    return bx + dx / dist * 10, by + dy / dist * 10


def compose_flatlay_fallback(
    silk: Image.Image,
    scalp: Image.Image,
    gummies: Image.Image,
) -> Image.Image:
    """Simple 3-item flatlay board if no dedicated flatlay photo exists."""
    board = Image.new("RGBA", (W, H), (245, 240, 232, 255))
    # Soft linen wash
    board = soft_paper(board, seed=11)

    # Place three rounded product cards in a triangle / row mood
    silk_c = rounded_card(silk, (420, 520), radius=20)
    scalp_c = rounded_card(scalp, (360, 360), radius=20)
    gum_c = rounded_card(gummies, (340, 340), radius=20)

    board.alpha_composite(silk_c, (80, 280))
    board.alpha_composite(scalp_c, (620, 320))
    board.alpha_composite(gum_c, (380, 900))
    return board


def build_format_2_flatlay(
    flatlay: Image.Image | None,
    *,
    silk: Image.Image | None = None,
    scalp: Image.Image | None = None,
    gummies: Image.Image | None = None,
) -> Image.Image:
    if flatlay is not None:
        base = cover_crop(flatlay, W, H, bias_y=0.45).convert("RGBA")
        # Soft vignette edges so labels pop
        wash = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        wd = ImageDraw.Draw(wash)
        wd.rectangle((0, 0, W - 1, 160), fill=(255, 252, 248, 40))
        base = Image.alpha_composite(base, wash)
    else:
        assert silk and scalp and gummies
        base = compose_flatlay_fallback(silk, scalp, gummies)

    canvas = base

    # ── Top banner ───────────────────────────────────────────────────────
    banner_font = font_serif(34, italic=True)
    emoji_f = font_emoji(30)
    plain = "my daily hair regrowth starter pack"
    spark = "✨"

    probe = ImageDraw.Draw(canvas)
    pw, ph = _text_size(probe, plain, banner_font)
    ew = _text_size(probe, spark, emoji_f)[0] if emoji_f else 0
    pad_x, pad_y = 28, 16
    bw = pw + (12 + ew if emoji_f else 0) + pad_x * 2
    bh = ph + pad_y * 2

    banner = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    bd = ImageDraw.Draw(banner)
    bd.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=14, fill=FLAT_BANNER)
    bd.rounded_rectangle(
        (0, 0, bw - 1, bh - 1), radius=14, outline=(255, 255, 255, 180), width=1
    )
    bd.text((pad_x, pad_y - 1), plain, font=banner_font, fill=(*FLAT_INK, 255))
    if emoji_f is not None:
        bd.text((pad_x + pw + 10, pad_y), spark, font=emoji_f, embedded_color=True)

    # Soft drop shadow under banner
    shadow = Image.new("RGBA", (bw + 20, bh + 20), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (8, 10, 8 + bw, 10 + bh), radius=14, fill=(0, 0, 0, 55)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    bx = (W - bw) // 2
    by = 56
    canvas.alpha_composite(shadow, (bx - 8, by - 8))
    canvas.alpha_composite(banner, (bx, by))

    # ── Callouts — tips land ON subjects (this flatlay composition) ──────
    # Layout of Silk_pillowcase_and_scalp_brush_*:
    #   silk fabric  → left / lower-left
    #   gummies jar  → upper-right
    #   scalp brush  → lower-right
    hand = font_hand(26)
    # Chips in EMPTY marble — short arrows into object centers
    annotations = (
        # empty top-left marble → into silk fold
        ("01. silk only ($15)", (300, 860), (48, 560), "left", 0.08),
        # right of massager → into brush center
        ("02. scalp blood flow", (790, 990), (1030, 1200), "right", -0.06),
        # left of jar → into jar body / loose gummies (short, no overlap)
        ("03. daily follicle vitamins (Sulu)", (780, 540), (420, 400), "left", 0.0),
    )

    for label, tip, text_xy, anchor, bend in annotations:
        box = _chip_label(canvas, label, text_xy, hand, anchor=anchor)
        # Keep chip fully on canvas
        x0, y0, x1, y1 = box
        dx = dy = 0
        if x0 < 8:
            dx = 8 - x0
        if x1 > W - 8:
            dx = (W - 8) - x1
        if y0 < 8:
            dy = 8 - y0
        if y1 > H - 8:
            dy = (H - 8) - y1
        if dx or dy:
            # redraw shifted (rare)
            pass
        ax0, ay0 = _arrow_from_chip(box, tip)
        draw = ImageDraw.Draw(canvas)
        _arrow(draw, ax0, ay0, tip[0], tip[1], bend=bend, width=3)

    return canvas


# ── Main ─────────────────────────────────────────────────────────────────────

def build_both(src_dir: Path, out_dir: Path = OUT_DIR) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    assets = pick_assets(src_dir)
    print("Assets:")
    for k, p in assets.items():
        print(f"  [{k}] {p.name}")

    t0 = time.perf_counter()

    with Image.open(assets["hair"]) as im:
        hair = im.convert("RGB").copy()
    with Image.open(assets["gummies"]) as im:
        gummies = im.convert("RGB").copy()

    f1 = build_format_1_notes(hair, gummies)
    p1 = out_dir / "format_1_notes.jpg"
    f1.convert("RGB").save(p1, "JPEG", quality=95, optimize=True, subsampling=0)

    flatlay_img: Image.Image | None = None
    silk = scalp = gum2 = None
    if "flatlay" in assets:
        with Image.open(assets["flatlay"]) as im:
            flatlay_img = im.convert("RGB").copy()
    if "silk" in assets:
        with Image.open(assets["silk"]) as im:
            silk = im.convert("RGB").copy()
    if "scalp" in assets:
        with Image.open(assets["scalp"]) as im:
            scalp = im.convert("RGB").copy()
    gum2 = gummies

    f2 = build_format_2_flatlay(flatlay_img, silk=silk, scalp=scalp, gummies=gum2)
    p2 = out_dir / "format_2_flatlay_arrows.jpg"
    f2.convert("RGB").save(p2, "JPEG", quality=95, optimize=True, subsampling=0)

    dt = time.perf_counter() - t0
    print(f"\nBuilt in {dt:.2f}s")
    print(f"  -> {p1.resolve()}")
    print(f"  -> {p2.resolve()}")
    return p1, p2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build Notes + Flatlay conversion formats.")
    ap.add_argument("--dir", type=Path, default=DEFAULT_SRC)
    ap.add_argument("-o", "--out", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    try:
        build_both(args.dir, args.out)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
