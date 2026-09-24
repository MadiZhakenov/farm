#!/usr/bin/env python3
"""
Рендер слайда карусели 3:4 — нативный вирусный стиль TikTok
+ Negative Space Detection (текст в «тихой» зоне кадра).

Спека:
  - 1080 × 1440
  - safe zones: top 150, bottom 250, sides 90
  - max text width ≈ 76% кадра (~820 px)
  - белый текст + плотная чёрная обводка
  - auto-fit 72→34 pt (шаг 2)
  - text bbox ≤ 24% площади (Farace et al., JM)
  - позиция по минимуму визуального шума (верх / центр / низ)
"""

from __future__ import annotations

import re
import statistics
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

SLIDE_W = 1080
SLIDE_H = 1440
SAFE_TOP = 150
SAFE_BOTTOM = 250
SAFE_SIDE = 90

MAX_TEXT_WIDTH_RATIO = 0.76
MAX_TEXT_WIDTH = int(SLIDE_W * MAX_TEXT_WIDTH_RATIO)  # ~820

MAX_TEXT_AREA_RATIO = 0.24
# Pixel-locked vs ammyeyelash 3.jpg @ 1080 (continuous draw, no per-glyph stroke inflate):
# SemiBold 61 / stroke 3 / tracking 0 / shadow (0,1) / advance 73
# width MAE ≈ 2.4px vs ref line boxes
FONT_START = 61
FONT_MIN = 42
FONT_STEP = 1
LINE_ADVANCE_RATIO = 73.0 / 61.0  # band pitch / font size @ 1080 lock
LINE_HEIGHT_RATIO = 1.12  # fallback gap ratio if bbox measure unavailable
LETTER_SPACING = 0.0  # keep 0 — char-by-char stroke inflates width
# TikTok slideshow: hard 1px drop under glyphs
TEXT_SHADOW_OFFSET = (0, 1)

TEXT_FILL = (255, 255, 255, 255)  # #FFFFFF
STROKE_FILL = (0, 0, 0, 255)      # #000000
SHADOW_FILL = (0, 0, 0, 255)

# миниатюра для negative-space анализа
NS_W = 180
NS_H = 240

# кандидатные слоты (центр по Y в полном разрешении, внутри safe zone)
SLOT_TOP_Y = (200, 240)
SLOT_MID_Y = (520, 560)
SLOT_BOT_Y = (820, 880)

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "fonts"
MONTSERRAT_BOLD = FONTS_DIR / "Montserrat-Bold.ttf"
MONTSERRAT_URL = (
    "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf"
)

_FONT_CANDIDATES = (
    FONTS_DIR / "TikTokSans-SemiBold.ttf",
    FONTS_DIR
    / "TikTokSans"
    / "TikTokSans-v4.000"
    / "fonts"
    / "ttf"
    / "TikTokSans36pt-SemiBold.ttf",
    FONTS_DIR / "TikTokSans-Bold.ttf",
    FONTS_DIR
    / "TikTokSans"
    / "TikTokSans-v4.000"
    / "fonts"
    / "ttf"
    / "TikTokSans36pt-Bold.ttf",
    MONTSERRAT_BOLD,
    FONTS_DIR / "Inter-Bold.ttf",
    FONTS_DIR / "ProximaNova-Bold.ttf",
    Path(r"C:\Windows\Fonts\montserrat-bold.ttf"),
    Path(r"C:\Windows\Fonts\Montserrat-Bold.ttf"),
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
    Path(r"C:\Windows\Fonts\seguisb.ttf"),
    Path(r"C:\Windows\Fonts\seguiib.ttf"),
    Path(r"C:\Windows\Fonts\segoeuib.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
)

_font_lock = threading.Lock()
_resolved_font_path: str | None = None


@dataclass
class SlideRenderMeta:
    font_size: int
    lines: list[str]
    text_area_ratio: float
    text_box: tuple[int, int, int, int]
    within_scientific_limit: bool
    stroke_width: int = 4
    slot: str = "mid"  # top | mid | bot
    zone_luma: float = 128.0
    zone_noise: float = 0.0

    @property
    def plate_box(self) -> tuple[int, int, int, int]:
        return self.text_box


def stroke_width_for(font_size: int, zone_luma: float = 128.0) -> int:
    """Pixel-locked TikTok slideshow stroke = 3px @ SemiBold 61 lock.

    zone_luma retained for API compat; do NOT inflate stroke — thicker outlines
    break the pixel match vs native TikTok text.
    """
    _ = zone_luma
    return 3 if font_size >= 48 else 2


def line_advance_for(font_size: int) -> int:
    """Целевой шаг строк — pixel-lock ammyeyelash (79px @ SemiBold 67pt)."""
    return max(1, int(round(font_size * LINE_ADVANCE_RATIO)))


def line_spacing_for(font_size: int, line_box_height: int | None = None) -> int:
    """Межстрочный зазор = target_advance − высота строки (со stroke)."""
    target = line_advance_for(font_size)
    if line_box_height is not None and line_box_height > 0:
        return max(2, target - line_box_height)
    return max(2, int(round(font_size * (LINE_HEIGHT_RATIO - 1.0))))


def _download_montserrat_bold() -> Path | None:
    try:
        FONTS_DIR.mkdir(parents=True, exist_ok=True)
        if MONTSERRAT_BOLD.is_file() and MONTSERRAT_BOLD.stat().st_size > 10_000:
            return MONTSERRAT_BOLD
        req = Request(
            MONTSERRAT_URL,
            headers={"User-Agent": "CarouselFactory/1.0 (font-fetch)"},
        )
        with urlopen(req, timeout=30) as resp:
            data = resp.read()
        if len(data) < 10_000:
            return None
        tmp = MONTSERRAT_BOLD.with_suffix(".ttf.part")
        tmp.write_bytes(data)
        tmp.replace(MONTSERRAT_BOLD)
        return MONTSERRAT_BOLD
    except Exception:
        return None


def _find_font_path() -> str | None:
    global _resolved_font_path
    if _resolved_font_path and Path(_resolved_font_path).is_file():
        return _resolved_font_path

    with _font_lock:
        if _resolved_font_path and Path(_resolved_font_path).is_file():
            return _resolved_font_path

        for path in _FONT_CANDIDATES:
            if path.is_file():
                _resolved_font_path = str(path)
                return _resolved_font_path

        downloaded = _download_montserrat_bold()
        if downloaded and downloaded.is_file():
            _resolved_font_path = str(downloaded)
            _load_font.cache_clear()
            return _resolved_font_path

    return None


@lru_cache(maxsize=64)
def _load_font(size: int) -> ImageFont.ImageFont:
    path = _find_font_path()
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def cover_resize(img: Image.Image, width: int = SLIDE_W, height: int = SLIDE_H) -> Image.Image:
    """Масштаб cover + center crop под 3:4."""
    src = img.convert("RGB")
    scale = max(width / src.width, height / src.height)
    nw = max(1, int(src.width * scale))
    nh = max(1, int(src.height * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - width) // 2
    top = (nh - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _safe_box() -> tuple[int, int, int, int]:
    return (
        SAFE_SIDE,
        SAFE_TOP,
        SLIDE_W - SAFE_SIDE,
        SLIDE_H - SAFE_BOTTOM,
    )


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return re.sub(r"[ \t]+", " ", text)


def _text_bbox(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    stroke: int,
) -> tuple[int, int, int, int]:
    return draw.textbbox(
        xy,
        text or " ",
        font=font,
        stroke_width=stroke,
        align="center",
    )


def _line_width(
    font: ImageFont.ImageFont,
    text: str,
    stroke: int,
    tracking: float = LETTER_SPACING,
) -> float:
    """Width of a line including stroke and letter-spacing."""
    if not text:
        return float(2 * stroke)
    if abs(tracking) < 1e-9:
        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        bb = _text_bbox(probe, (0, 0), text, font, stroke)
        return float(bb[2] - bb[0])
    total = sum(float(font.getlength(ch)) for ch in text)
    total += tracking * max(0, len(text) - 1)
    return total + 2 * stroke


def _draw_tracked_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    *,
    fill,
    stroke_width: int,
    stroke_fill,
    tracking: float = LETTER_SPACING,
) -> None:
    x, y = xy
    if abs(tracking) < 1e-9:
        draw.text(
            (x, y),
            text,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
            align="center",
        )
        return
    cur = float(x)
    for ch in text:
        draw.text(
            (int(round(cur)), y),
            ch,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
        cur += float(font.getlength(ch)) + tracking


def _wrap_paragraph(
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
    stroke: int,
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if _line_width(font, trial, stroke) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _wrap_text(
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
    stroke: int,
) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()] or [""]
    lines: list[str] = []
    for part in paragraphs:
        lines.extend(_wrap_paragraph(part, font, max_width, draw, stroke))
    return lines


def _measure_block(
    lines: Sequence[str],
    font: ImageFont.ImageFont,
    draw: ImageDraw.ImageDraw,
    font_size: int,
    stroke: int,
) -> tuple[int, int, int]:
    """Возвращает (width, height, line_advance)."""
    if not lines:
        return 0, 0, 0
    widths: list[int] = []
    heights: list[int] = []
    for line in lines:
        bbox = _text_bbox(draw, (0, 0), line, font, stroke)
        widths.append(int(round(_line_width(font, line, stroke))))
        heights.append(bbox[3] - bbox[1])
    line_h = max(heights)
    advance = line_advance_for(font_size)
    # keep a tiny gap even if FreeType box is unusually tall
    if advance < line_h + 2:
        advance = line_h + 2
    gap = advance - line_h
    total_h = line_h * len(lines) + gap * max(0, len(lines) - 1)
    return (max(widths) if widths else 0), total_h, advance


# ---------------------------------------------------------------------------
# Negative Space Detection
# ---------------------------------------------------------------------------

def _clamp_text_box(
    tw: int,
    th: int,
    center_y: int,
) -> tuple[int, int, int, int]:
    """Горизонтальный центр + вертикаль вокруг center_y, внутри safe zone."""
    left, top, right, bottom = _safe_box()
    tw = min(tw, right - left, MAX_TEXT_WIDTH)
    th = min(th, bottom - top)
    x0 = (SLIDE_W - tw) // 2
    x0 = max(left, min(x0, right - tw))
    y0 = center_y - th // 2
    y0 = max(top, min(y0, bottom - th))
    return x0, y0, x0 + tw, y0 + th


def _region_noise_and_luma(
    gray: Image.Image,
    box: tuple[int, int, int, int],
) -> tuple[float, float]:
    """
    Визуальный шум = std яркости + сила градиента (края/детали).
    Меньше = спокойнее фон для текста.
    """
    x0, y0, x1, y1 = box
    x0 = max(0, min(x0, gray.width - 1))
    y0 = max(0, min(y0, gray.height - 1))
    x1 = max(x0 + 1, min(x1, gray.width))
    y1 = max(y0 + 1, min(y1, gray.height))
    crop = gray.crop((x0, y0, x1, y1))
    pixels = list(crop.getdata())
    if len(pixels) < 4:
        return 9999.0, 128.0

    luma = float(statistics.fmean(pixels))
    try:
        std = float(statistics.pstdev(pixels))
    except statistics.StatisticsError:
        std = 0.0

    # градиент: find_edges → средняя яркость краёв
    edges = crop.filter(ImageFilter.FIND_EDGES)
    edge_px = list(edges.getdata())
    edge_mean = float(statistics.fmean(edge_px)) if edge_px else 0.0

    # соседние перепады по горизонтали (сэмпл)
    w, h = crop.size
    diffs: list[float] = []
    step = max(1, w // 40)
    for yy in range(0, h, max(1, h // 30)):
        row_off = yy * w
        for xx in range(0, w - 1, step):
            diffs.append(abs(pixels[row_off + xx] - pixels[row_off + xx + 1]))
    grad = float(statistics.fmean(diffs)) if diffs else 0.0

    noise = std * 0.55 + edge_mean * 0.30 + grad * 0.15
    return noise, luma


def find_optimal_text_position(
    image: Image.Image,
    text_bbox_w: int,
    text_bbox_h: int,
) -> tuple[int, int, str, float, float]:
    """
    Ищет «тихую» зону для текста.

    Returns:
        (x, y, slot_name, zone_luma, zone_noise) — top-left блока текста.
    """
    # cover → анализ на 180×240 L
    full = cover_resize(image, SLIDE_W, SLIDE_H)
    thumb = full.convert("L").resize((NS_W, NS_H), Image.Resampling.BILINEAR)
    sx = NS_W / SLIDE_W
    sy = NS_H / SLIDE_H

    slots: list[tuple[str, int]] = [
        ("top", (SLOT_TOP_Y[0] + SLOT_TOP_Y[1]) // 2),
        ("mid", (SLOT_MID_Y[0] + SLOT_MID_Y[1]) // 2),
        ("bot", (SLOT_BOT_Y[0] + SLOT_BOT_Y[1]) // 2),
    ]

    best: tuple[float, str, int, int, float, float] | None = None
    for name, cy in slots:
        x0, y0, x1, y1 = _clamp_text_box(text_bbox_w, text_bbox_h, cy)
        # чуть расширим окно анализа вокруг текста (+padding)
        pad = 24
        ax0 = max(0, x0 - pad)
        ay0 = max(0, y0 - pad)
        ax1 = min(SLIDE_W, x1 + pad)
        ay1 = min(SLIDE_H, y1 + pad)
        tbox = (
            int(ax0 * sx),
            int(ay0 * sy),
            max(int(ax0 * sx) + 1, int(ax1 * sx)),
            max(int(ay0 * sy) + 1, int(ay1 * sy)),
        )
        noise, luma = _region_noise_and_luma(thumb, tbox)
        # лёгкий приоритет верхней зоне при равном шуме (читаемость в TikTok)
        score = noise + (0.0 if name == "top" else 0.8 if name == "mid" else 1.2)
        if best is None or score < best[0]:
            best = (score, name, x0, y0, luma, noise)

    assert best is not None
    _, slot, x, y, luma, noise = best
    return x, y, slot, luma, noise


def autofit_typography(
    text: str,
    *,
    zone_luma: float = 128.0,
) -> SlideRenderMeta:
    """Подбирает размер шрифта и раскладку (ширина ≤ 76% кадра, ≤ 24% площади)."""
    probe = Image.new("RGB", (SLIDE_W, SLIDE_H))
    draw = ImageDraw.Draw(probe)
    left, top, right, bottom = _safe_box()
    max_text_w = min(MAX_TEXT_WIDTH, right - left)
    max_text_h = bottom - top
    slide_area = SLIDE_W * SLIDE_H
    clean = _normalize_text(text)

    best: SlideRenderMeta | None = None
    for size in range(FONT_START, FONT_MIN - 1, -FONT_STEP):
        stroke = stroke_width_for(size, zone_luma)
        wrap_w = max(40, max_text_w - 2 * stroke)
        font = _load_font(size)
        lines = _wrap_text(clean, font, wrap_w, draw, stroke)
        tw, th, _ = _measure_block(lines, font, draw, size, stroke)
        if tw > max_text_w or th > max_text_h:
            continue
        ratio = (tw * th) / slide_area
        if ratio > MAX_TEXT_AREA_RATIO:
            continue
        # временный box — позиция уточнится negative-space
        x0 = (SLIDE_W - tw) // 2
        y0 = top + (max_text_h - th) // 2
        best = SlideRenderMeta(
            font_size=size,
            lines=list(lines),
            text_area_ratio=ratio,
            text_box=(x0, y0, x0 + tw, y0 + th),
            within_scientific_limit=True,
            stroke_width=stroke,
        )
        break

    if best is not None:
        return best

    size = FONT_MIN
    stroke = stroke_width_for(size, zone_luma)
    font = _load_font(size)
    wrap_w = max(40, max_text_w - 2 * stroke)
    lines = _wrap_text(clean, font, wrap_w, draw, stroke)
    tw, th, _ = _measure_block(lines, font, draw, size, stroke)
    tw = min(max_text_w, tw)
    th = min(max_text_h, th)
    ratio = (tw * th) / slide_area if slide_area else 0.0
    x0 = (SLIDE_W - tw) // 2
    y0 = top + max(0, (max_text_h - th) // 2)
    return SlideRenderMeta(
        font_size=size,
        lines=list(lines),
        text_area_ratio=ratio,
        text_box=(x0, y0, x0 + tw, y0 + th),
        within_scientific_limit=ratio <= MAX_TEXT_AREA_RATIO,
        stroke_width=stroke,
    )


def render_slide(
    background: Image.Image,
    text: str,
    *,
    darken: float = 0.0,
) -> tuple[Image.Image, SlideRenderMeta]:
    """
    Накладывает TikTok-типографику на фон с negative-space позиционированием.
    """
    base = cover_resize(background).convert("RGBA")
    if darken > 0:
        shade = Image.new(
            "RGBA",
            (SLIDE_W, SLIDE_H),
            (0, 0, 0, int(255 * min(0.6, max(0.0, darken)))),
        )
        base = Image.alpha_composite(base, shade)

    # 1) черновой fit → размер блока
    draft = autofit_typography(text)
    tw = draft.text_box[2] - draft.text_box[0]
    th = draft.text_box[3] - draft.text_box[1]

    # 2) тихая зона на реальном кадре
    x0, y0, slot, luma, noise = find_optimal_text_position(base, tw, th)

    # 3) финальный fit с учётом яркости зоны (stroke)
    meta = autofit_typography(text, zone_luma=luma)
    tw = meta.text_box[2] - meta.text_box[0]
    th = meta.text_box[3] - meta.text_box[1]
    # пересчитать x/y под финальный размер в том же слоте
    slot_cy = {
        "top": (SLOT_TOP_Y[0] + SLOT_TOP_Y[1]) // 2,
        "mid": (SLOT_MID_Y[0] + SLOT_MID_Y[1]) // 2,
        "bot": (SLOT_BOT_Y[0] + SLOT_BOT_Y[1]) // 2,
    }.get(slot, (SLOT_MID_Y[0] + SLOT_MID_Y[1]) // 2)
    x0, y0, x1, y1 = _clamp_text_box(tw, th, slot_cy)
    meta.text_box = (x0, y0, x1, y1)
    meta.slot = slot
    meta.zone_luma = luma
    meta.zone_noise = noise
    meta.stroke_width = stroke_width_for(meta.font_size, luma)

    font = _load_font(meta.font_size)
    stroke = meta.stroke_width
    box_w, box_h = x1 - x0, y1 - y0

    layer = Image.new("RGBA", (SLIDE_W, SLIDE_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    _, block_h, advance = _measure_block(
        meta.lines, font, probe, meta.font_size, stroke
    )

    text_top = y0 + max(0, (box_h - block_h) // 2)
    y = text_top
    cx = x0 + box_w // 2
    shx, shy = TEXT_SHADOW_OFFSET
    for line in meta.lines:
        bbox = _text_bbox(probe, (0, 0), line, font, stroke)
        lw = _line_width(font, line, stroke)
        x = cx - lw / 2.0
        # when tracking=0, PIL bbox left bearing must be subtracted
        if abs(LETTER_SPACING) < 1e-9:
            x = cx - lw / 2.0 - bbox[0]
        yy = y - bbox[1]
        if shx or shy:
            _draw_tracked_text(
                draw,
                (x + shx, yy + shy),
                line,
                font,
                fill=SHADOW_FILL,
                stroke_width=stroke,
                stroke_fill=SHADOW_FILL,
            )
        _draw_tracked_text(
            draw,
            (x, yy),
            line,
            font,
            fill=TEXT_FILL,
            stroke_width=stroke,
            stroke_fill=STROKE_FILL,
        )
        y += advance

    out = Image.alpha_composite(base, layer).convert("RGB")
    return out, meta


def render_preview(
    background: Image.Image,
    text: str,
    preview_w: int,
    preview_h: int,
) -> Image.Image:
    full, _ = render_slide(background, text)
    return full.resize((preview_w, preview_h), Image.Resampling.LANCZOS)
