#!/usr/bin/env python3
"""
Final editorial magazine collage generator (var_01 winner, polished).

Two caption layouts on warm linen (#F7F4EE), 1080×1440:

  A  Overlay — white serif italic on photos (soft shadow)
  B  Captions — Kinfolk-style labels in white fields under each photo

Usage:
  python build_editorial_collage.py
  python build_editorial_collage.py --dir E:\\Users\\Desktop\\download
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1440
BG = (247, 244, 238)  # warm linen #F7F4EE
INK = (28, 24, 22)
ACCENT = (168, 120, 110)
CAPTION_INK = (42, 42, 42)  # #2A2A2A
FRAME_EDGE = (220, 212, 202)
WHITE = (255, 255, 255)

ROOT = Path(__file__).resolve().parent
DEFAULT_SRC = Path(r"E:\Users\Desktop\download")
OUT_A = ROOT / "out" / "collages" / "editorial_v1_overlay.jpg"
OUT_B = ROOT / "out" / "collages" / "editorial_v2_captions.jpg"
FONTS_DIR = ROOT / "fonts"

TITLE = "the daily routine that saved my hair"

CAPTIONS = (
    "01 · silk pillowcase",
    "02 · scalp stimulation",
    "03 · daily hair gummies (sulu)",
    "04 · 90-day hairline progress",
)

_SLOT_HINTS = (
    (0, ("pillow", "bed", "silk", "messy_bed", "slip")),
    (1, ("scalp", "brush", "sink", "bathroom", "massage")),
    (2, ("vitamin", "gummi", "gummy", "jar", "sulu", "vitamins")),
    (3, ("mirror", "hair", "part", "regrowth", "holding_hair", "selfie")),
)
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

MONTSERRAT_BOLD = FONTS_DIR / "Montserrat-Bold.ttf"
MONTSERRAT_REG = FONTS_DIR / "Montserrat-Regular.ttf"
MONTSERRAT_BOLD_URL = (
    "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf"
)
MONTSERRAT_REG_URL = (
    "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Regular.ttf"
)


# ── Fonts ────────────────────────────────────────────────────────────────────

def _download(url: str, dest: Path) -> Path | None:
    try:
        if dest.is_file() and dest.stat().st_size > 8_000:
            return dest
        FONTS_DIR.mkdir(parents=True, exist_ok=True)
        req = Request(url, headers={"User-Agent": "EditorialCollage/1.0"})
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


def font_serif_italic(size: int) -> ImageFont.ImageFont:
    for p in (
        FONTS_DIR / "PlayfairDisplay-Italic.ttf",
        FONTS_DIR / "CormorantGaramond-Italic.ttf",
        Path(r"C:\Windows\Fonts\georgiai.ttf"),
        Path(r"C:\Windows\Fonts\timesi.ttf"),
        Path(r"C:\Windows\Fonts\CAMBRIAI.TTF"),
    ):
        f = _tt(p, size)
        if f:
            return f
    return font_sans(size, bold=False)


def font_serif_regular(size: int) -> ImageFont.ImageFont:
    """Clean editorial serif for Kinfolk caption bars (not italic)."""
    for p in (
        FONTS_DIR / "PlayfairDisplay-Regular.ttf",
        FONTS_DIR / "CormorantGaramond-Regular.ttf",
        Path(r"C:\Windows\Fonts\georgia.ttf"),
        Path(r"C:\Windows\Fonts\times.ttf"),
        Path(r"C:\Windows\Fonts\cambria.ttc"),
    ):
        f = _tt(p, size)
        if f:
            return f
    return font_sans(size, bold=False)


def font_sans(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    if bold:
        order = [
            MONTSERRAT_BOLD,
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


# ── Image helpers ────────────────────────────────────────────────────────────

def cover_crop(img: Image.Image, tw: int, th: int, *, bias_y: float = 0.38) -> Image.Image:
    src = img.convert("RGB")
    sw, sh = src.size
    if sw <= 0 or sh <= 0:
        return Image.new("RGB", (tw, th), BG)
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
    tracking: float = 1.2,
) -> int:
    """Letter-spaced text; returns advance width."""
    x, y = xy
    for i, ch in enumerate(text):
        draw.text((x, y), ch, font=font, fill=fill)
        w, _ = text_size(draw, ch, font)
        x += w
        if i < len(text) - 1:
            x += int(round(tracking))
    return x - xy[0]


def tracked_width(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, tracking: float = 1.2
) -> int:
    if not text:
        return 0
    total = 0
    for i, ch in enumerate(text):
        total += text_size(draw, ch, font)[0]
        if i < len(text) - 1:
            total += int(round(tracking))
    return total


def soft_white_label(
    text: str,
    font: ImageFont.ImageFont,
) -> Image.Image:
    """White serif caption with black outline + soft shadow for readability."""
    probe = Image.new("RGBA", (10, 10))
    pd = ImageDraw.Draw(probe)
    tw, th = text_size(pd, text, font)
    pad = 20
    layer = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))

    # Soft ambient shadow behind the outlined text
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for ox, oy in ((2, 3), (1, 2), (3, 3)):
        sd.text((pad + ox, pad + oy), text, font=font, fill=(0, 0, 0, 55))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=2.5))
    layer = Image.alpha_composite(layer, shadow)

    ld = ImageDraw.Draw(layer)
    # Black outline (stroke) then white fill
    ox, oy = pad, pad
    for dx in (-2, -1, 0, 1, 2):
        for dy in (-2, -1, 0, 1, 2):
            if dx or dy:
                ld.text((ox + dx, oy + dy), text, font=font, fill=(0, 0, 0, 220))
    ld.text((ox, oy), text, font=font, fill=(*WHITE, 255))
    return layer


# ── Assets ───────────────────────────────────────────────────────────────────

def list_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_EXTS]
    files.sort(key=lambda p: ("and" in p.stem.lower(), -p.stat().st_mtime))
    return files


def pick_four(folder: Path) -> list[Image.Image]:
    files = list_images(folder)
    if len(files) < 4:
        raise FileNotFoundError(f"Need ≥4 images in {folder}, found {len(files)}")
    slots: list[Path | None] = [None, None, None, None]
    rem = list(files)

    def _score(path: Path, hints: tuple[str, ...]) -> int:
        name = path.stem.lower()
        return sum(1 for h in hints if h in name)

    for slot, hints in _SLOT_HINTS:
        # Prefer strongest keyword match; skip combined flatlays
        ranked = sorted(
            (p for p in rem if "and_" not in p.stem.lower() or slot == 2),
            key=lambda p: -_score(p, hints),
        )
        for p in ranked:
            if _score(p, hints) > 0:
                # Slot 3 (hairline) must be mirror/selfie — not the vitamins jar
                if slot == 3 and ("vitamin" in p.stem.lower() or "jar" in p.stem.lower()):
                    continue
                # Slot 2 prefers jar/vitamins over old palm shots
                slots[slot] = p
                rem.remove(p)
                break

    for i in range(4):
        if slots[i] is None and rem:
            slots[i] = rem.pop(0)
    if any(s is None for s in slots):
        raise FileNotFoundError("Could not resolve 4 images")
    imgs: list[Image.Image] = []
    for i, p in enumerate(slots):
        assert p is not None
        with Image.open(p) as im:
            imgs.append(im.convert("RGB").copy())
        print(f"  [{CAPTIONS[i]}] {p.name}")
    return imgs


# ── Shared masthead ──────────────────────────────────────────────────────────

HEADLINE_INK = (26, 26, 26)  # #1A1A1A — masthead only


def draw_header(canvas: Image.Image, title: str | None = None) -> int:
    """Journal masthead. Returns y below the decorative rule."""
    draw = ImageDraw.Draw(canvas)
    title_f = font_serif_italic(44)
    text = (title if title is not None else TITLE).strip() or TITLE
    lines = wrap(draw, text, title_f, W - 120)
    y = 48
    for line in lines:
        tw, th = text_size(draw, line, title_f)
        draw.text(((W - tw) // 2, y), line, font=title_f, fill=HEADLINE_INK)
        y += th + 6
    # Thin rule under the central phrase
    draw.line((W // 2 - 80, y + 10, W // 2 + 80, y + 10), fill=(*ACCENT, 200), width=1)
    return y + 30


# ── Variant A — overlay captions ─────────────────────────────────────────────

def build_v1_overlay(
    imgs: list[Image.Image],
    captions: tuple[str, ...] | list[str] | None = None,
    title: str | None = None,
) -> Image.Image:
    caps = tuple(captions) if captions is not None else CAPTIONS
    if len(imgs) != 4 or len(caps) != 4:
        raise ValueError("Need exactly 4 images and 4 captions")

    canvas = Image.new("RGBA", (W, H), (*BG, 255))
    header_bottom = draw_header(canvas, title=title)

    pad, gap, frame = 28, 22, 2
    top = header_bottom
    bot = H - 36
    avail_h = bot - top
    cell_w = (W - pad * 2 - gap) // 2
    cell_h = (avail_h - gap) // 2
    photo_w, photo_h = cell_w - frame * 2, cell_h - frame * 2

    positions = (
        (pad, top),
        (pad + cell_w + gap, top),
        (pad, top + cell_h + gap),
        (pad + cell_w + gap, top + cell_h + gap),
    )

    cap_f = font_serif_italic(28)

    for i, (x, y) in enumerate(positions):
        tile = cover_crop(imgs[i], photo_w, photo_h)
        card = Image.new("RGBA", (cell_w, cell_h), (*WHITE, 255))
        card.paste(tile.convert("RGBA"), (frame, frame))
        cd = ImageDraw.Draw(card)
        cd.rectangle((0, 0, cell_w - 1, cell_h - 1), outline=FRAME_EDGE, width=1)

        label = soft_white_label(caps[i], cap_f)
        card.alpha_composite(label, (10, 6))
        canvas.alpha_composite(card, (x, y))

    return canvas


# ── Variant B — Kinfolk captions under photos ────────────────────────────────

def build_v2_captions(
    imgs: list[Image.Image],
    captions: tuple[str, ...] | list[str] | None = None,
    title: str | None = None,
) -> Image.Image:
    caps = tuple(captions) if captions is not None else CAPTIONS
    if len(imgs) != 4 or len(caps) != 4:
        raise ValueError("Need exactly 4 images and 4 captions")

    canvas = Image.new("RGBA", (W, H), (*BG, 255))
    header_bottom = draw_header(canvas, title=title)

    pad, gap, frame = 28, 22, 2
    caption_h = 44  # white field under photo
    top = header_bottom
    bot = H - 32
    avail_h = bot - top
    cell_w = (W - pad * 2 - gap) // 2
    cell_h = (avail_h - gap) // 2
    photo_h = cell_h - caption_h
    photo_w = cell_w - frame * 2

    positions = (
        (pad, top),
        (pad + cell_w + gap, top),
        (pad, top + cell_h + gap),
        (pad + cell_w + gap, top + cell_h + gap),
    )

    cap_f = font_serif_regular(21)
    tracking = 0.9

    for i, (x, y) in enumerate(positions):
        # White card = photo + caption band
        card = Image.new("RGBA", (cell_w, cell_h), (*WHITE, 255))
        tile = cover_crop(imgs[i], photo_w, photo_h)
        card.paste(tile.convert("RGBA"), (frame, frame))
        cd = ImageDraw.Draw(card)
        cd.rectangle((0, 0, cell_w - 1, cell_h - 1), outline=FRAME_EDGE, width=1)
        # hairline between photo and caption field
        cd.line(
            (frame, frame + photo_h, cell_w - frame - 1, frame + photo_h),
            fill=(235, 230, 222),
            width=1,
        )

        # Centered tracked editorial serif caption
        label = caps[i]
        tw = tracked_width(cd, label, cap_f, tracking)
        th = text_size(cd, label, cap_f)[1]
        tx = (cell_w - tw) // 2
        ty = frame + photo_h + (caption_h - th) // 2 - 1
        draw_tracked(cd, (tx, ty), label, cap_f, (*CAPTION_INK, 255), tracking=tracking)

        canvas.alpha_composite(card, (x, y))

    return canvas


# ── Main ─────────────────────────────────────────────────────────────────────

def build_both(src_dir: Path) -> tuple[Path, Path]:
    print(f"Assets from {src_dir}")
    imgs = pick_four(src_dir)
    t0 = time.perf_counter()

    OUT_A.parent.mkdir(parents=True, exist_ok=True)

    v1 = build_v1_overlay(imgs)
    v1.convert("RGB").save(OUT_A, "JPEG", quality=95, optimize=True, subsampling=0)

    v2 = build_v2_captions(imgs)
    v2.convert("RGB").save(OUT_B, "JPEG", quality=95, optimize=True, subsampling=0)

    dt = time.perf_counter() - t0
    print(f"\nBuilt in {dt:.2f}s")
    print(f"  A overlay  -> {OUT_A.resolve()}")
    print(f"  B captions -> {OUT_B.resolve()}")
    return OUT_A, OUT_B


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build editorial magazine collage (2 caption styles).")
    ap.add_argument("--dir", type=Path, default=DEFAULT_SRC)
    args = ap.parse_args(argv)
    try:
        build_both(args.dir)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
