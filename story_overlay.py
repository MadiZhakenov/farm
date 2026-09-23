#!/usr/bin/env python3
"""
Story Overlay — массовое наложение текстовых сторис на talking-head видео.

Запуск GUI:
  python story_overlay.py

В GUI: пути к папкам с видео + тексты 1. 2. 3. → Сгенерировать
(текст N идёт на следующий свободный клип; один клип — один раз)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_BG_DIR = SCRIPT_DIR / "output" / "clips_6s"
DEFAULT_BG_DIRS = (
    SCRIPT_DIR / "output" / "clips_6s",
    SCRIPT_DIR / "output" / "clips_6s_copy_7742D0E8",
    SCRIPT_DIR / "output" / "clips_6s_IMG_5193",
    SCRIPT_DIR / "output" / "clips_6s_IMG_5194",
)
DEFAULT_OUT_DIR = SCRIPT_DIR / "output" / "stories"
DEFAULT_TEXTS = SCRIPT_DIR / "story_texts.txt"
USAGE_PATH = SCRIPT_DIR / "story_usage.json"
SOUNDS_DIR = SCRIPT_DIR / "output" / "madi_sounds"
MAX_OUT_SEC = 6.0
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}

# --- Style calibrated from reference frame (476x848 → 1080x1920) ---
TARGET_W = 1080
TARGET_H = 1920
TEXT_COLOR = (234, 226, 166)  # #EAE2A6
OUTLINE_COLOR = (0, 0, 0)
OUTLINE_WIDTH = 4  # black stroke around glyphs
MAX_TEXT_WIDTH_FRAC = 0.82
FONT_SIZE = 45
LINE_GAP = 10  # extra px between lines (leading beyond font metrics)
PUNCHLINE_GAP = 42  # blank gap before punchline, scaled from ref
MIN_FONT_SIZE = 22
MAX_BLOCK_HEIGHT_FRAC = 0.92  # keep full text inside frame
WORDS_PER_SEC = 2.8
MIN_SCREEN_SEC = 4.0
MAX_SCREEN_SEC = 120.0  # one static frame — enough time to read
EXPORT_FPS = 30
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
DEFAULT_LOOK = "clean"
# Center-face luma on these folders is ~25–37 / 255. Exposure 62 is the lift
# that landed that face near 125 (measured on clips_6s and IMG_5193).
FACE_LUMA_TARGET = 125.0
LIFT_X = (0.0, 0.05, 0.12, 0.28, 1.0)
LIFT_Y = (0.02, 0.32, 0.52, 0.68, 0.96)


@dataclass(frozen=True)
class LookPreset:
    id: str
    label: str
    hint: str
    exposure: float
    contrast: float
    warmth: float
    saturation: float
    gamma: float
    tint: str = ""


LOOKS: tuple[LookPreset, ...] = (
    LookPreset("none", "Без эффекта", "Исходный тёмный кадр, без обработки", 0, 50, 50, 50, 50),
    LookPreset(
        "soft", "Тёплый",
        "Свет под эти клипы. Тепло мягкое — исходник и так жёлтый",
        62, 54, 54, 46, 50,
        "colortemperature=temperature=6800:mix=0.28",
    ),
    LookPreset(
        "cinema", "Кино",
        "Подъём света, тени холоднее, света чуть теплее",
        62, 58, 44, 48, 50,
        "colortemperature=temperature=7000:mix=0.3,"
        "colorbalance=rs=-0.015:bs=0.04:rm=0.01:bm=-0.012:rh=0.02:bh=-0.025",
    ),
    LookPreset(
        "clean", "Чистый",
        "Подъём света и снятие жёлтой лампы. Стартовый лук",
        66, 54, 38, 44, 50,
        "colortemperature=temperature=8000:mix=0.48,"
        "colorbalance=rs=-0.03:bs=0.06:rm=-0.02:bm=0.045",
    ),
    LookPreset(
        "gold", "Золотой час",
        "Подъём плюс 4800K на четверть, не заливка лица",
        60, 50, 68, 50, 50,
        "colortemperature=temperature=4800:mix=0.22,colorbalance=rh=0.025:rm=0.016:bh=-0.012",
    ),
    LookPreset(
        "film", "Плёнка",
        "Чуть мягче контраст после подъёма, жёлтую лампу приглушает",
        56, 42, 52, 40, 52,
        "colortemperature=temperature=7000:mix=0.25,colorbalance=rm=0.012:bm=-0.008",
    ),
)
LOOK_BY_ID = {item.id: item for item in LOOKS}

FONT_CANDIDATES = [
    SCRIPT_DIR / "fonts" / "TikTokSans-Bold.ttf",
    SCRIPT_DIR / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf" / "TikTokSans36pt-Bold.ttf",
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
    Path(r"C:\Windows\Fonts\segoeuib.ttf"),
]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class StyleConfig:
    font_size: int = FONT_SIZE
    line_gap: int = LINE_GAP
    punchline_gap: int = PUNCHLINE_GAP
    max_width_frac: float = MAX_TEXT_WIDTH_FRAC
    text_color: tuple[int, int, int] = TEXT_COLOR
    outline_color: tuple[int, int, int] = OUTLINE_COLOR
    outline_width: int = OUTLINE_WIDTH
    y_offset: int = 0  # manual vertical nudge in px (positive = down)
    words_per_sec: float = WORDS_PER_SEC
    min_screen_sec: float = MIN_SCREEN_SEC
    max_screen_sec: float = MAX_SCREEN_SEC


@dataclass
class Screen:
    lines: list[str]
    punchline_lines: list[str] = field(default_factory=list)
    duration: float = 6.0
    manual_lines: bool = False  # user edited line breaks
    font_size: int | None = None  # auto-fit size for this frame


@dataclass
class StoryJob:
    text: str
    screens: list[Screen] = field(default_factory=list)
    video_path: Path | None = None
    style: StyleConfig = field(default_factory=StyleConfig)


# ---------------------------------------------------------------------------
# Fonts / ffmpeg
# ---------------------------------------------------------------------------

def find_font(path: Path | None = None) -> Path:
    if path and path.exists():
        return path
    for p in FONT_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(
        "TikTok Sans Bold not found. Expected fonts/TikTokSans-Bold.ttf (or pass --font)."
    )


def load_font(size: int, font_path: Path | None = None) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(find_font(font_path)), size)


EMOJI_FONT_PATH = Path(r"C:\Windows\Fonts\seguiemj.ttf")
_EMOJI_FONT_CACHE: dict[int, ImageFont.FreeTypeFont | None] = {}
_EMOJI_GLYPH_CACHE: dict[tuple[str, int], Image.Image | None] = {}


def _is_regional(cp: int) -> bool:
    return 0x1F1E6 <= cp <= 0x1F1FF


def _is_skin(cp: int) -> bool:
    return 0x1F3FB <= cp <= 0x1F3FF


def _is_emoji_base(cp: int) -> bool:
    return (
        0x1F000 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0x2B00 <= cp <= 0x2BFF
        or 0x231A <= cp <= 0x231B
        or 0x23E9 <= cp <= 0x23FA
        or cp in {0x2328, 0x23CF, 0x24C2, 0x25AA, 0x25AB, 0x25B6, 0x25C0, 0x25FB, 0x25FC, 0x25FD, 0x25FE, 0x2934, 0x2935, 0x3030, 0x303D, 0x3297, 0x3299}
    )


def _emoji_span(text: str, i: int) -> int:
    """End index of one emoji cluster starting at i, or i if this isn't emoji."""
    n = len(text)
    if i >= n:
        return i
    ch = text[i]
    cp = ord(ch)
    j = i + 1
    if _is_regional(cp):
        if j < n and _is_regional(ord(text[j])):
            j += 1
        return j
    if ch in "0123456789#*":
        k = j
        if k < n and text[k] == "\uFE0F":
            k += 1
        if k < n and text[k] == "\u20E3":
            return k + 1
    forced = j < n and text[j] == "\uFE0F"
    if not _is_emoji_base(cp) and not forced:
        return i
    if j < n and text[j] in "\uFE0E\uFE0F":
        j += 1
    if j < n and _is_skin(ord(text[j])):
        j += 1
        if j < n and text[j] == "\uFE0F":
            j += 1
    while j < n and text[j] == "\u200D" and j + 1 < n:
        nxt = ord(text[j + 1])
        if not (_is_emoji_base(nxt) or _is_regional(nxt)):
            break
        j += 2
        if j < n and text[j] in "\uFE0E\uFE0F":
            j += 1
        if j < n and _is_skin(ord(text[j])):
            j += 1
    if j < n and 0xE0020 <= ord(text[j]) <= 0xE007F:
        while j < n and 0xE0020 <= ord(text[j]) <= 0xE007F:
            j += 1
    return j


def split_emoji_runs(text: str) -> list[tuple[bool, str]]:
    runs: list[tuple[bool, str]] = []
    buf: list[str] = []
    i = 0
    n = len(text)

    def flush() -> None:
        if buf:
            runs.append((False, "".join(buf)))
            buf.clear()

    while i < n:
        j = _emoji_span(text, i)
        if j > i:
            flush()
            runs.append((True, text[i:j]))
            i = j
        else:
            buf.append(text[i])
            i += 1
    flush()
    return runs


def _emoji_font(size: int) -> ImageFont.FreeTypeFont | None:
    if size in _EMOJI_FONT_CACHE:
        return _EMOJI_FONT_CACHE[size]
    font = ImageFont.truetype(str(EMOJI_FONT_PATH), size) if EMOJI_FONT_PATH.exists() else None
    _EMOJI_FONT_CACHE[size] = font
    return font


def _emoji_pad(font: ImageFont.ImageFont) -> int:
    return max(6, int(getattr(font, "size", 32)) // 10)


def emoji_glyph(cluster: str, box_h: int) -> Image.Image | None:
    box_h = max(12, int(box_h))
    key = (cluster, box_h)
    if key in _EMOJI_GLYPH_CACHE:
        return _EMOJI_GLYPH_CACHE[key]
    render_px = max(box_h * 2, 72)
    font = _emoji_font(render_px)
    if font is None:
        _EMOJI_GLYPH_CACHE[key] = None
        return None
    canvas = Image.new("RGBA", (render_px * 12, render_px * 4), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text(
        (render_px // 2, render_px // 3),
        cluster,
        font=font,
        embedded_color=True,
    )
    bbox = canvas.getbbox()
    if not bbox:
        _EMOJI_GLYPH_CACHE[key] = None
        return None
    crop = canvas.crop(bbox)
    nw = max(1, int(round(crop.width * (box_h / crop.height))))
    glyph = crop.resize((nw, box_h), Image.Resampling.LANCZOS)
    _EMOJI_GLYPH_CACHE[key] = glyph
    return glyph


def text_width(text: str, font: ImageFont.ImageFont) -> int:
    if not text:
        return 0
    ascent = font.getmetrics()[0]
    pad = _emoji_pad(font)
    total = 0
    for is_emoji, part in split_emoji_runs(text):
        if is_emoji:
            glyph = emoji_glyph(part, ascent)
            total += (glyph.width + pad * 2) if glyph is not None else int(font.getlength(part))
        else:
            total += int(font.getlength(part))
    return total


def draw_rich_line(
    layer: Image.Image,
    draw: ImageDraw.ImageDraw,
    text: str,
    x: float,
    y: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    stroke: int,
    stroke_fill: tuple[int, int, int, int],
) -> None:
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    pad = _emoji_pad(font)
    for is_emoji, part in split_emoji_runs(text):
        if is_emoji:
            glyph = emoji_glyph(part, ascent)
            if glyph is None:
                draw.text((int(x), y), part, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
                x += font.getlength(part)
                continue
            ey = y + (line_h - glyph.height) // 2
            layer.alpha_composite(glyph, (int(x + pad), int(ey)))
            x += glyph.width + pad * 2
        else:
            draw.text((int(x), y), part, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
            x += font.getlength(part)


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def find_ffprobe() -> str | None:
    return shutil.which("ffprobe")


def probe_duration(path: Path) -> float:
    ffprobe = find_ffprobe()
    if not ffprobe:
        cap = cv2.VideoCapture(str(path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        cap.release()
        return float(n / fps) if fps else 1.0
    cmd = [
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        return max(0.1, float(r.stdout.strip()))
    except ValueError:
        return 1.0


@dataclass
class GradeControls:
    look: str = DEFAULT_LOOK
    exposure: float | None = None
    contrast: float | None = None
    warmth: float | None = None
    saturation: float | None = None
    gamma: float | None = None

    def resolved(self) -> GradeControls:
        preset = LOOK_BY_ID.get(self.look) or LOOK_BY_ID[DEFAULT_LOOK]
        return GradeControls(
            look=preset.id,
            exposure=preset.exposure if self.exposure is None else self.exposure,
            contrast=preset.contrast if self.contrast is None else self.contrast,
            warmth=preset.warmth if self.warmth is None else self.warmth,
            saturation=preset.saturation if self.saturation is None else self.saturation,
            gamma=preset.gamma if self.gamma is None else self.gamma,
        )


def _clamp_knob(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def lift_curve(exposure: float) -> str:
    """Shadow/mid lift. 62 matches the measured grade for these dark clips."""
    strength = _clamp_knob(exposure) / 62.0
    if strength < 0.03:
        return ""
    strength = min(strength, 1.55)
    points: list[str] = []
    prev = 0.0
    for x, y in zip(LIFT_X, LIFT_Y):
        out = x + (y - x) * strength
        out = min(0.99, max(prev, out))
        prev = out
        points.append(f"{x:.3f}/{out:.3f}")
    return "curves=master='" + " ".join(points) + "'"


def _eq_from_knobs(contrast: float, saturation: float, gamma: float) -> str:
    # 50 on each knob is identity. Gamma stays above 0.9 — this ffmpeg build
    # crushes the frame to black if gamma drops toward 0.5.
    con = 1.0 + (_clamp_knob(contrast) - 50) / 50 * 0.18
    sat = 1.0 + (_clamp_knob(saturation) - 50) / 50 * 0.26
    gam = 1.0 + (_clamp_knob(gamma) - 50) / 50 * 0.16
    gam = max(0.90, gam)
    if abs(con - 1) < 0.012 and abs(sat - 1) < 0.012 and abs(gam - 1) < 0.012:
        return ""
    return f"eq=contrast={con:.3f}:saturation={sat:.3f}:gamma={gam:.3f}"


def _warmth_balance(warmth: float) -> str:
    t = (_clamp_knob(warmth) - 50) / 50
    if abs(t) < 0.04:
        return ""
    rs, rm, rh = 0.04 * t, 0.07 * t, 0.05 * t
    bs, bm, bh = -0.06 * t, -0.05 * t, -0.04 * t
    return (
        f"colorbalance=rs={rs:.3f}:bs={bs:.3f}:rm={rm:.3f}:"
        f"bm={bm:.3f}:rh={rh:.3f}:bh={bh:.3f}"
    )


def grade_filter(g: GradeControls) -> str:
    """Lift first (these clips are ~20/255), then the look, then the knobs."""
    g = g.resolved()
    preset = LOOK_BY_ID[g.look]
    parts = [lift_curve(g.exposure or 0)]
    parts.append(_eq_from_knobs(g.contrast or 50, g.saturation or 50, g.gamma or 50))
    if preset.tint:
        parts.append(preset.tint)
    parts.append(_warmth_balance(g.warmth or 50))
    return ",".join(part for part in parts if part)


def sample_face_luma(video: Path, extra_vf: str = "", t: float = 0.8) -> float | None:
    """Mean luma of the center of the frame, where the face sits in these clips."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not video.exists():
        return None
    scale = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H}"
    )
    vf = append_grade(scale, extra_vf)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        out = Path(tmp.name)
    try:
        r = subprocess.run(
            [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{t:.3f}", "-i", str(video),
                "-vf", vf, "-frames:v", "1", str(out),
            ],
            capture_output=True, text=True, check=False,
        )
        if r.returncode != 0 or not out.exists():
            return None
        frame = cv2.imread(str(out))
        if frame is None:
            return None
        y = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)[:, :, 0]
        h, w = y.shape
        face = y[int(h * 0.28):int(h * 0.62), int(w * 0.28):int(w * 0.72)]
        return float(face.mean())
    finally:
        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass


def exposure_for_face(video: Path, target: float = FACE_LUMA_TARGET) -> tuple[float, float, float] | None:
    """Binary-search the lift so the face lands near the measured target."""
    raw = sample_face_luma(video)
    if raw is None:
        return None
    if raw >= target - 15:
        return 0.0, raw, raw
    lo, hi = 12.0, 94.0
    chosen, graded = 62.0, raw
    for _ in range(6):
        mid = (lo + hi) / 2
        face = sample_face_luma(video, lift_curve(mid))
        if face is None:
            return None
        chosen, graded = mid, face
        if face < target:
            lo = mid
        else:
            hi = mid
    return chosen, raw, graded


def append_grade(chain: str, grade_f: str) -> str:
    if not grade_f:
        return chain
    return f"{chain},{grade_f}"


# ---------------------------------------------------------------------------
# Text layout
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def split_sentences(text: str) -> list[str]:
    text = normalize_text(text)
    # preserve explicit paragraph breaks as hard splits
    parts: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.replace("\n", " ").strip()
        if not block:
            continue
        sents = [s.strip() for s in _SENTENCE_SPLIT.split(block) if s.strip()]
        parts.extend(sents if sents else [block])
    return parts


def wrap_line(words: list[str], font: ImageFont.ImageFont, max_w: int) -> list[str]:
    if not words:
        return []
    lines: list[str] = []
    cur: list[str] = []
    for w in words:
        trial = (" ".join(cur + [w])).strip()
        if cur and text_width(trial, font) > max_w:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


def wrap_text(text: str, font: ImageFont.ImageFont, max_w: int) -> list[str]:
    text = text.replace("\n", " ").strip()
    if not text:
        return []
    return wrap_line(text.split(), font, max_w)


def extract_punchline(sentences: list[str]) -> tuple[list[str], list[str]]:
    """Last short sentence(s) become punchline — matches reference rhythm."""
    if len(sentences) < 2:
        return sentences, []

    punch: list[str] = []
    body = list(sentences)

    def word_count(s: str) -> int:
        return len(s.split())

    # Prefer an explicit short closer; allow two short beats (e.g. repeated line)
    while body and len(punch) < 2:
        last = body[-1]
        wc = word_count(last)
        # Ignore separator junk
        if re.fullmatch(r"-{2,}", last.strip()):
            body.pop()
            continue
        if wc <= 12 and (not punch or word_count(" ".join(punch)) + wc <= 16):
            punch.insert(0, body.pop())
            # If we already have a punchline and previous isn't a short echo, stop
            if len(punch) == 1 and body and word_count(body[-1]) > 12:
                break
        else:
            break

    if not punch and body:
        last = body[-1]
        if word_count(last) <= 16:
            punch = [body.pop()]

    if not body:
        body = punch
        punch = []

    return body, punch


def layout_screens(
    text: str,
    style: StyleConfig | None = None,
    font_path: Path | None = None,
    manual_lines: list[str] | None = None,
) -> list[Screen]:
    """Always one static screen with the full text (no multi-screen splits)."""
    style = style or StyleConfig()

    if manual_lines is not None:
        body: list[str] = []
        punch: list[str] = []
        seen_blank = False
        for ln in manual_lines:
            if ln.strip() == "":
                seen_blank = True
                continue
            (punch if seen_blank else body).append(ln)
        if not body and punch:
            body, punch = punch, []
        words = " ".join(body + punch).split()
        size = _fit_font_size(body, punch, style, font_path)
        return [Screen(
            lines=body,
            punchline_lines=punch,
            duration=clamp_duration(len(words), style),
            manual_lines=True,
            font_size=size,
        )]

    raw = normalize_text(text)
    # Explicit blank line = punchline; otherwise auto-detect short closer
    if "\n\n" in raw:
        pre, _, post = raw.partition("\n\n")
        body_sents = split_sentences(pre.replace("\n", " "))
        punch_sents = split_sentences(post.replace("\n", " "))
    else:
        body_sents, punch_sents = extract_punchline(split_sentences(raw))

    size, body_lines, punch_lines = _layout_at_best_size(
        " ".join(body_sents),
        " ".join(punch_sents) if punch_sents else "",
        style,
        font_path,
    )
    words = " ".join(body_lines + punch_lines).split()
    return [Screen(
        lines=body_lines,
        punchline_lines=punch_lines,
        duration=clamp_duration(len(words), style),
        font_size=size,
    )]


def _layout_at_best_size(
    body_text: str,
    punch_text: str,
    style: StyleConfig,
    font_path: Path | None,
) -> tuple[int, list[str], list[str]]:
    """Shrink font until the full wrapped block fits in one frame."""
    max_h = int(TARGET_H * MAX_BLOCK_HEIGHT_FRAC)
    chosen_size = style.font_size
    body_lines: list[str] = []
    punch_lines: list[str] = []

    for size in range(style.font_size, MIN_FONT_SIZE - 1, -1):
        font = load_font(size, font_path)
        max_w = int(TARGET_W * style.max_width_frac)
        body_lines = wrap_text(body_text, font, max_w)
        punch_lines = wrap_text(punch_text, font, max_w) if punch_text.strip() else []
        probe = Screen(lines=body_lines, punchline_lines=punch_lines)
        # measure with a style copy at this font size
        probe_style = replace(style, font_size=size)
        total_h, _, _ = measure_block(probe, font, probe_style)
        chosen_size = size
        if total_h <= max_h:
            break
    return chosen_size, body_lines, punch_lines


def _fit_font_size(
    body: list[str],
    punch: list[str],
    style: StyleConfig,
    font_path: Path | None,
) -> int:
    max_h = int(TARGET_H * MAX_BLOCK_HEIGHT_FRAC)
    for size in range(style.font_size, MIN_FONT_SIZE - 1, -1):
        font = load_font(size, font_path)
        probe_style = replace(style, font_size=size)
        total_h, _, _ = measure_block(Screen(lines=body, punchline_lines=punch), font, probe_style)
        if total_h <= max_h:
            return size
    return MIN_FONT_SIZE


def clamp_duration(n_words: int, style: StyleConfig) -> float:
    if n_words <= 0:
        return style.min_screen_sec
    d = n_words / max(0.5, style.words_per_sec)
    return float(max(style.min_screen_sec, min(style.max_screen_sec, round(d, 2))))


def screen_to_editable(screen: Screen) -> str:
    parts = list(screen.lines)
    if screen.punchline_lines:
        parts.append("")
        parts.extend(screen.punchline_lines)
    return "\n".join(parts)


def editable_to_screen(text: str, style: StyleConfig) -> Screen:
    lines = text.replace("\r\n", "\n").split("\n")
    body: list[str] = []
    punch: list[str] = []
    seen_blank = False
    for ln in lines:
        if ln.strip() == "" and body and not seen_blank:
            seen_blank = True
            continue
        if seen_blank:
            if ln.strip():
                punch.append(ln.rstrip())
        else:
            if ln.strip() or body:
                body.append(ln.rstrip())
    # trim trailing empties in body
    while body and body[-1].strip() == "":
        body.pop()
    words = " ".join(body + punch).split()
    size = _fit_font_size(body, punch, style, None)
    return Screen(
        lines=body,
        punchline_lines=punch,
        duration=clamp_duration(len(words), style),
        manual_lines=True,
        font_size=size,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def measure_block(
    screen: Screen,
    font: ImageFont.ImageFont,
    style: StyleConfig,
) -> tuple[int, int, list[tuple[str, int]]]:
    """Returns (total_h, max_line_w, [(line, width), ...])."""
    rows: list[tuple[str, int]] = []
    for ln in screen.lines:
        rows.append((ln, text_width(ln, font)))
    if screen.punchline_lines:
        rows.append(("", 0))  # marker for punchline gap
        for ln in screen.punchline_lines:
            rows.append((ln, text_width(ln, font)))

    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    total = 0
    first = True
    for ln, _ in rows:
        if ln == "" and not first:
            total += style.punchline_gap
            continue
        if not first:
            total += style.line_gap
        total += line_h
        first = False
    max_w = max((w for _, w in rows), default=0)
    return total, max_w, rows


def render_overlay_rgba(
    screen: Screen,
    style: StyleConfig | None = None,
    font_path: Path | None = None,
    size: tuple[int, int] = (TARGET_W, TARGET_H),
) -> Image.Image:
    style = style or StyleConfig()
    font_px = screen.font_size or style.font_size
    style = replace(style, font_size=font_px)
    w, h = size
    font = load_font(font_px, font_path)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent

    total_h, _, rows = measure_block(screen, font, style)
    # True center of the frame (horizontal + vertical), then optional nudge
    y0 = (h - total_h) // 2 + style.y_offset

    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    stroke = max(0, int(style.outline_width))
    stroke_fill = (*style.outline_color, 255)

    y = y0
    first = True
    for ln, lw in rows:
        if ln == "" and not first:
            y += style.punchline_gap
            continue
        if not first:
            y += style.line_gap
        x = (w - lw) // 2
        if ln:
            draw_rich_line(
                layer,
                draw,
                ln,
                x,
                y,
                font,
                (*style.text_color, 255),
                stroke,
                stroke_fill,
            )
        y += line_h
        first = False

    return layer


def grab_preview_frame(video: Path, t: float = 0.0) -> Image.Image:
    cap = cv2.VideoCapture(str(video))
    if t > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return Image.new("RGB", (TARGET_W, TARGET_H), (40, 30, 25))
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(frame)
    return letterbox(img, TARGET_W, TARGET_H)


def grab_graded_frame(
    video: Path,
    grade: GradeControls | None = None,
    t: float = 0.4,
) -> Image.Image:
    """Extract one frame with the same grade used on export."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return grab_preview_frame(video, t)
    grade = grade or GradeControls()
    grade_f = grade_filter(grade)
    scale = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H}"
    )
    vf = append_grade(scale, grade_f)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        out = Path(tmp.name)
    try:
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{t:.3f}", "-i", str(video),
            "-vf", vf, "-frames:v", "1", str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if r.returncode != 0 or not out.exists():
            return grab_preview_frame(video, t)
        return Image.open(out).convert("RGB")
    finally:
        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass


def letterbox(img: Image.Image, tw: int, th: int) -> Image.Image:
    img = img.convert("RGB")
    scale = max(tw / img.width, th / img.height)
    nw, nh = int(img.width * scale), int(img.height * scale)
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def composite_preview(
    video: Path | None,
    screen: Screen,
    style: StyleConfig | None = None,
    font_path: Path | None = None,
    grade: GradeControls | None = None,
) -> Image.Image:
    style = style or StyleConfig()
    if video and video.exists():
        bg = grab_graded_frame(video, grade, 0.4)
    else:
        bg = Image.new("RGB", (TARGET_W, TARGET_H), (55, 40, 35))
    overlay = render_overlay_rgba(screen, style, font_path)
    return Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")


def export_story(
    video: Path,
    screens: list[Screen],
    out_path: Path,
    style: StyleConfig | None = None,
    font_path: Path | None = None,
    progress_cb=None,
    grade: GradeControls | None = None,
) -> Path:
    """Render story: clip length + selected look."""
    style = style or StyleConfig()
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg не найден в PATH")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    grade = grade or GradeControls()
    grade_f = grade_filter(grade)

    with tempfile.TemporaryDirectory(prefix="story_ov_") as tmp:
        tmp_p = Path(tmp)
        parts: list[Path] = []
        clip_dur = min(probe_duration(video), MAX_OUT_SEC)
        sound = pick_sound()

        for i, screen in enumerate(screens):
            if progress_cb:
                progress_cb(i, len(screens), f"screen {i + 1}/{len(screens)}")
            overlay = render_overlay_rgba(screen, style, font_path)
            ov_path = tmp_p / f"ov_{i:02d}.png"
            overlay.save(ov_path)

            part = tmp_p / f"part_{i:02d}.mp4"
            # Output length = source clip length (clips_6s ≈ 6s). Do not extend by reading time.
            screen.duration = clip_dur

            grade_chain = append_grade("setsar=1", grade_f)
            fc = (
                f"[0:v]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
                f"crop={TARGET_W}:{TARGET_H},{grade_chain},fps={EXPORT_FPS}[bg];"
                f"[1:v]format=rgba[ov];"
                f"[bg][ov]overlay=0:0:format=auto[vout]"
            )
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-t", f"{clip_dur:.3f}", "-i", str(video),
                "-loop", "1", "-t", f"{clip_dur:.3f}", "-i", str(ov_path),
            ]
            if sound:
                cmd += ["-stream_loop", "-1", "-t", f"{clip_dur:.3f}", "-i", str(sound)]
            cmd += [
                "-filter_complex", fc,
                "-map", "[vout]",
            ]
            if sound:
                cmd += ["-map", "2:a:0", "-c:a", "aac", "-b:a", "160k"]
            else:
                cmd += ["-an"]
            cmd += [
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-t", f"{clip_dur:.3f}",
                str(part),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if r.returncode != 0:
                raise RuntimeError(r.stderr[-2000:] or "ffmpeg failed")
            parts.append(part)

        if len(parts) == 1:
            shutil.copy2(parts[0], out_path)
        else:
            lst = tmp_p / "list.txt"
            lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(lst),
                "-c", "copy", str(out_path),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if r.returncode != 0:
                # re-encode fallback
                cmd = [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-c:a", "aac", "-b:a", "160k",
                    "-pix_fmt", "yuv420p", "-t", f"{MAX_OUT_SEC:.3f}", str(out_path),
                ]
                r = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if r.returncode != 0:
                    raise RuntimeError(r.stderr[-2000:] or "concat failed")

    if progress_cb:
        progress_cb(len(screens), len(screens), "done")
    return out_path


# ---------------------------------------------------------------------------
# Batch helpers
# ---------------------------------------------------------------------------

def list_sounds(folder: Path | None = None) -> list[Path]:
    folder = folder or SOUNDS_DIR
    if not folder.exists() or not folder.is_dir():
        return []
    sounds = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
    return sorted(sounds, key=lambda p: p.name.lower())


def pick_sound() -> Path | None:
    sounds = list_sounds()
    return random.choice(sounds) if sounds else None


def parse_batch_texts(path: Path) -> list[str]:
    return parse_batch_text_blob(path.read_text(encoding="utf-8"), path.suffix.lower())


def parse_batch_text_blob(raw: str, suffix: str = ".txt") -> list[str]:
    if suffix == ".json":
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
        raise ValueError("JSON batch must be a list of strings")

    def clean(chunk: str) -> str:
        chunk = chunk.strip()
        chunk = re.sub(r"^\d+[\.)]\s*", "", chunk)
        chunk = re.sub(r"(?:^|\n)\s*---\s*(?:\n|$)", "\n", chunk)
        return chunk.strip(" -\n\t")

    numbered = re.split(r"\n\s*(?=\d+[\.)]\s)", raw.strip())
    if len(numbered) > 1:
        out = [clean(c) for c in numbered]
        out = [c for c in out if c]
        if out:
            return out

    parts = re.split(r"\n\s*---\s*\n", raw)
    return [clean(p) for p in parts if clean(p)]


def _natural_key(path: Path) -> list:
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def list_videos(folder: Path) -> list[Path]:
    if not folder.exists() or not folder.is_dir():
        return []
    vids = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    return sorted(vids, key=_natural_key)


_NUMBERED_PREFIX = re.compile(r"^\d+[\.)]\s*")
_URL_PREFIX = re.compile(r"^https?://", re.I)


def video_id(path: Path) -> str:
    """Stable identity. Same file under different spelling is still one video."""
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    return os.path.normcase(resolved)


def parse_source_groups(raw: str) -> tuple[list[tuple[str, list[Path]]], list[str]]:
    """One entry per pasted folder or file, in order. Duplicated paths are skipped."""
    chunks = re.split(r"[\n;|]+", raw.strip())
    groups: list[tuple[str, list[Path]]] = []
    warnings: list[str] = []
    seen_sources: set[str] = set()
    for chunk in chunks:
        chunk = chunk.strip().strip('"').strip("'")
        chunk = _NUMBERED_PREFIX.sub("", chunk).strip().strip('"').strip("'")
        if not chunk:
            continue
        if _URL_PREFIX.match(chunk):
            warnings.append("http-ссылки не читаются — нужен локальный путь к папке или файлу")
            continue
        path = Path(chunk)
        source_key = video_id(path)
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        if path.is_dir():
            vids = list_videos(path)
            if not vids:
                warnings.append(f"в папке нет видео: {path}")
            groups.append((str(path), vids))
        elif path.is_file() and path.suffix.lower() in VIDEO_EXTS:
            groups.append((str(path), [path]))
        elif path.is_file():
            warnings.append(f"это не видео: {path.name}")
        else:
            warnings.append(f"не найдено: {chunk}")
    uniq: list[str] = []
    for w in warnings:
        if w not in uniq:
            uniq.append(w)
    return groups, uniq


def parse_video_sources(raw: str) -> tuple[list[Path], list[str]]:
    """Folders or video files, one per line (also ``;`` / ``|``). Numbered ``2. path`` is ok.

    HTTP links are not sources — they are reported in the warning list.
    """
    groups, warnings = parse_source_groups(raw)
    seen: set[str] = set()
    out: list[Path] = []
    for _label, vids in groups:
        for vid in vids:
            key = video_id(vid)
            if key in seen:
                continue
            seen.add(key)
            out.append(vid)
    return out, warnings


def list_videos_from_folder_paths(raw: str) -> list[Path]:
    """Parse pasted folder/file paths and collect videos in order."""
    videos, _warnings = parse_video_sources(raw)
    return videos


def _fmt_used_at(iso: str) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m %H:%M")
    except ValueError:
        return ""


def slugify(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return (s[:n] or "story").rstrip("_")


def text_fingerprint(text: str) -> str:
    norm = normalize_text(text).casefold()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:20]


def _slug_from_out(out: str) -> str:
    stem = Path(out).stem
    if len(stem) > 3 and stem[:2].isdigit() and stem[2] == "_":
        return stem[3:]
    return stem


def _pair_id(vid: str, fingerprint: str) -> str:
    return f"{vid}::{fingerprint}"


class UsageLedger:
    """Tracks video+text pairs. Same clip can return with a different text.

    Videos in ``blocked`` (e.g. reserved on another PC) are never reused.
    Historical exports without full text are matched by output filename slug.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.blocked: dict[str, dict] = {}
        self.pairs: dict[str, dict] = {}
        self._keys_by_video: dict[str, set[str]] = {}
        self._slugs_by_video: dict[str, set[str]] = {}
        self._rows_by_video: dict[str, list[dict]] = {}
        self.load()

    def _rebuild_index(self) -> None:
        keys: dict[str, set[str]] = {}
        slugs: dict[str, set[str]] = {}
        rows: dict[str, list[dict]] = {}
        for key, rec in self.pairs.items():
            vid = key.split("::", 1)[0] if "::" in key else ""
            if not vid:
                path = str(rec.get("path") or "")
                vid = video_id(Path(path)) if path else ""
            if not vid:
                continue
            keys.setdefault(vid, set()).add(str(rec.get("text_key") or ""))
            slug = str(rec.get("text_slug") or "")
            if slug:
                slugs.setdefault(vid, set()).add(slug)
            rows.setdefault(vid, []).append(rec)
        for vid in rows:
            rows[vid].sort(key=lambda r: str(r.get("used_at") or ""))
        self._keys_by_video = keys
        self._slugs_by_video = slugs
        self._rows_by_video = rows

    def load(self) -> None:
        with self._lock:
            self.blocked = {}
            self.pairs = {}
            if not self.path.exists():
                self._rebuild_index()
                return
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                bad = self.path.with_suffix(".bad.json")
                try:
                    shutil.copy2(self.path, bad)
                except OSError:
                    pass
                self._rebuild_index()
                return
            if not isinstance(data, dict):
                self._rebuild_index()
                return
            version = int(data.get("version") or 1)
            if version >= 2:
                raw_b = data.get("blocked")
                raw_p = data.get("pairs")
                if isinstance(raw_b, dict):
                    self.blocked = {str(k): v for k, v in raw_b.items() if isinstance(v, dict)}
                if isinstance(raw_p, dict):
                    self.pairs = {str(k): v for k, v in raw_p.items() if isinstance(v, dict)}
                self._rebuild_index()
                return
            # v1 → pairs + blocked
            raw = data.get("used")
            if not isinstance(raw, dict):
                self._rebuild_index()
                return
            for key, rec in raw.items():
                if not isinstance(rec, dict):
                    continue
                vid = str(key)
                path = str(rec.get("path") or "")
                name = str(rec.get("name") or Path(path or vid).name)
                used_at = str(rec.get("used_at") or "")
                out = str(rec.get("out") or "")
                note = str(rec.get("note") or "")
                if note or not out:
                    self.blocked[vid] = {
                        "path": path,
                        "name": name,
                        "used_at": used_at,
                        "reason": note or "зарезервировано без текста",
                    }
                    continue
                slug = _slug_from_out(out)
                fp = f"slug:{slug}"
                self.pairs[_pair_id(vid, fp)] = {
                    "path": path,
                    "name": name,
                    "used_at": used_at,
                    "out": out,
                    "text": "",
                    "text_key": fp,
                    "text_slug": slug,
                    "text_preview": slug.replace("_", " ")[:80],
                }
            self._rebuild_index()

    def save(self) -> None:
        payload = {"version": 2, "blocked": self.blocked, "pairs": self.pairs}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def is_blocked(self, video: Path) -> bool:
        with self._lock:
            return video_id(video) in self.blocked

    def _combo_used_unlocked(
        self,
        video: Path,
        text: str,
        fp: str | None = None,
        slug: str | None = None,
    ) -> bool:
        vid = video_id(video)
        if vid in self.blocked:
            return True
        fp = fp or text_fingerprint(text)
        if fp in self._keys_by_video.get(vid, ()):
            return True
        if _pair_id(vid, fp) in self.pairs:
            return True
        slug = slug or slugify(text)
        return bool(slug) and slug in self._slugs_by_video.get(vid, ())

    def is_combo_used(self, video: Path, text: str) -> bool:
        with self._lock:
            return self._combo_used_unlocked(video, text)

    def unused_texts_for(self, video: Path, texts: list[str]) -> list[str]:
        with self._lock:
            vid = video_id(video)
            if vid in self.blocked:
                return []
            used_keys = self._keys_by_video.get(vid, ())
            used_slugs = self._slugs_by_video.get(vid, ())
            out: list[str] = []
            for text in texts:
                fp = text_fingerprint(text)
                if fp in used_keys or _pair_id(vid, fp) in self.pairs:
                    continue
                if slugify(text) in used_slugs:
                    continue
                out.append(text)
            return out

    def availability(
        self,
        videos: list[Path],
        texts: list[str],
    ) -> tuple[list[Path], int]:
        """Return (videos with ≥1 free text, total free combos)."""
        with self._lock:
            if not texts:
                free = [v for v in videos if video_id(v) not in self.blocked]
                return free, len(free)
            meta = [(t, text_fingerprint(t), slugify(t)) for t in texts]
            free: list[Path] = []
            combo = 0
            for video in videos:
                vid = video_id(video)
                if vid in self.blocked:
                    continue
                used_keys = self._keys_by_video.get(vid, ())
                used_slugs = self._slugs_by_video.get(vid, ())
                n = 0
                for _t, fp, slug in meta:
                    if fp in used_keys or _pair_id(vid, fp) in self.pairs:
                        continue
                    if slug in used_slugs:
                        continue
                    n += 1
                if n:
                    free.append(video)
                    combo += n
            return free, combo

    def available_videos(self, videos: list[Path], texts: list[str]) -> list[Path]:
        return self.availability(videos, texts)[0]

    def free_combo_count(self, videos: list[Path], texts: list[str]) -> int:
        return self.availability(videos, texts)[1]

    def pairs_for(self, video: Path) -> list[dict]:
        with self._lock:
            return list(self._rows_by_video.get(video_id(video), ()))

    def block_info(self, video: Path) -> dict | None:
        with self._lock:
            return self.blocked.get(video_id(video))

    def folder_usage_summary(
        self,
        groups: list[tuple[str, list[Path]]],
        texts: list[str],
        detail_limit: int = 12,
    ) -> dict:
        """Cheap summary for the usage panel (no per-line Text inserts yet)."""
        with self._lock:
            meta = [(t, text_fingerprint(t), slugify(t)) for t in texts] if texts else []
            free_all: list[Path] = []
            combo_n = 0
            folders: list[dict] = []
            for label, videos in groups:
                blocked_n = 0
                paired_n = 0
                free_here = 0
                details: list[str] = []
                for video in videos:
                    vid = video_id(video)
                    info = self.blocked.get(vid)
                    if info:
                        blocked_n += 1
                        if len(details) < detail_limit:
                            when = _fmt_used_at(str(info.get("used_at") or ""))
                            reason = str(info.get("reason") or "блок")
                            stamp = f" · {when}" if when else ""
                            details.append(f"  {video.name} — блок{stamp} · {reason}")
                        continue
                    rows = self._rows_by_video.get(vid, ())
                    if rows:
                        paired_n += 1
                    left = 0
                    if meta:
                        used_keys = self._keys_by_video.get(vid, ())
                        used_slugs = self._slugs_by_video.get(vid, ())
                        for _t, fp, slug in meta:
                            if fp in used_keys or _pair_id(vid, fp) in self.pairs:
                                continue
                            if slug in used_slugs:
                                continue
                            left += 1
                    elif not rows:
                        left = 1
                    if left:
                        free_here += 1
                        free_all.append(video)
                        combo_n += left if meta else 1
                    if rows and len(details) < detail_limit:
                        previews = []
                        for rec in rows[:2]:
                            prev = str(rec.get("text_preview") or rec.get("text_slug") or "?")
                            if len(prev) > 36:
                                prev = prev[:36] + "…"
                            previews.append(prev)
                        more = f" +{len(rows) - 2}" if len(rows) > 2 else ""
                        left_note = f" · ещё текстов {left}" if texts else ""
                        details.append(
                            f"  {video.name} — {len(rows)} текст(ов): "
                            + "; ".join(previews)
                            + more
                            + left_note
                        )
                folders.append({
                    "label": label,
                    "total": len(videos),
                    "blocked": blocked_n,
                    "paired": paired_n,
                    "free": free_here,
                    "details": details,
                    "details_more": max(0, blocked_n + paired_n - len(details)),
                })
            return {
                "free_n": len(free_all),
                "combo_n": combo_n if texts else len(free_all),
                "total": sum(len(v) for _, v in groups),
                "folders": folders,
                "free_ids": tuple(sorted(video_id(v) for v in free_all)),
            }

    def mark(self, video: Path, out: Path, text: str = "", *, save: bool = True) -> None:
        with self._lock:
            vid = video_id(video)
            fp = text_fingerprint(text) if text.strip() else f"slug:{slugify(Path(out).stem)}"
            slug = slugify(text) if text.strip() else _slug_from_out(str(out))
            preview = normalize_text(text).replace("\n", " ")[:120] if text.strip() else slug.replace("_", " ")
            rec = {
                "path": str(video.resolve()),
                "name": video.name,
                "used_at": datetime.now().isoformat(timespec="seconds"),
                "out": str(out),
                "text": text,
                "text_key": fp,
                "text_slug": slug,
                "text_preview": preview,
            }
            self.pairs[_pair_id(vid, fp)] = rec
            self._keys_by_video.setdefault(vid, set()).add(fp)
            if slug:
                self._slugs_by_video.setdefault(vid, set()).add(slug)
            bucket = self._rows_by_video.setdefault(vid, [])
            bucket.append(rec)
            if save:
                self.save()

    def forget(self, videos: list[Path]) -> int:
        with self._lock:
            n = 0
            for video in videos:
                vid = video_id(video)
                if self.blocked.pop(vid, None) is not None:
                    n += 1
                prefix = f"{vid}::"
                drop = [key for key in self.pairs if key.startswith(prefix)]
                for key in drop:
                    self.pairs.pop(key, None)
                    n += 1
                self._keys_by_video.pop(vid, None)
                self._slugs_by_video.pop(vid, None)
                self._rows_by_video.pop(vid, None)
            if n:
                self.save()
            return n


def unused_videos(videos: list[Path], ledger: UsageLedger, texts: list[str] | None = None) -> list[Path]:
    """Videos that can still be paired with at least one of the given texts."""
    return ledger.available_videos(videos, texts or [])


def sample_jobs(
    videos: list[Path],
    texts: list[str],
    n: int,
    ledger: UsageLedger,
) -> list[tuple[Path, str]]:
    """Pick n unique videos, each with a random unused text for that clip."""
    free, _combo = ledger.availability(videos, texts)
    if n > len(free):
        raise ValueError(f"need {n} free videos, have {len(free)}")
    chosen = random.sample(free, n)
    jobs: list[tuple[Path, str]] = []
    for video in chosen:
        opts = ledger.unused_texts_for(video, texts)
        if not opts:
            continue
        jobs.append((video, random.choice(opts)))
    if len(jobs) < n:
        raise ValueError(f"need {n} free videos, have {len(jobs)}")
    return jobs


from ui_hotkeys import enable_edit_hotkeys


def unique_story_path(out_dir: Path, text: str, taken: set[str]) -> Path:
    """Next export name that does not overwrite an earlier generation."""
    slug = slugify(text)
    n = 1
    while True:
        name = f"{n:02d}_{slug}.mp4"
        if name.lower() not in taken:
            taken.add(name.lower())
            return out_dir / name
        n += 1


# ---------------------------------------------------------------------------
# GUI — simple batch workflow
# ---------------------------------------------------------------------------

C_BG = "#0b0d10"
C_INPUT = "#0f1318"
C_BORDER = "#252b36"
C_TEXT = "#eef1f6"
C_MUTED = "#8b93a7"
C_ACCENT = "#e8d48b"
C_BTN = "#1c2430"
C_BTN_PRIMARY = "#e8d48b"
C_BTN_PRIMARY_FG = "#1a1408"
C_OK = "#6bcf8e"
C_ERR = "#ff6b6b"


class StoryApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Story Overlay")
        self.geometry("1280x960")
        self.minsize(1100, 860)
        self.configure(bg=C_BG)

        self.style_cfg = StyleConfig()
        self.font_path: Path | None = None
        self._worker: threading.Thread | None = None
        self._q: queue.Queue = queue.Queue()
        self._busy = False
        self._preview_job = None
        self.ledger = UsageLedger(USAGE_PATH)
        self._usage_key: tuple | None = None
        self._refresh_after: str | None = None
        self._stats_token = 0
        self._cache_texts_raw: str | None = None
        self._cache_texts: list[str] = []
        self._cache_folders_raw: str | None = None
        self._cache_groups: list[tuple[str, list[Path]]] = []
        self._cache_vids: list[Path] = []
        self._cache_warnings: list[str] = []

        self._build()
        self.after(200, self._poll)
        self.after(100, self._schedule_refresh)
        self.after(800, lambda: self.preview_folders(silent=True))

    def _build(self) -> None:
        shell = tk.Frame(self, bg=C_BG, padx=20, pady=16)
        shell.pack(fill=tk.BOTH, expand=True)

        # Right: one graded preview per folder
        right = tk.Frame(shell, bg=C_BG, width=360)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(16, 0))
        right.pack_propagate(False)
        tk.Label(
            right, text="Превью по папкам", fg=C_ACCENT, bg=C_BG,
            font=("Segoe UI Semibold", 11),
        ).pack(anchor="w")
        tk.Label(
            right, text="по 1 кадру из каждой папки, с тем же текстом и фильтром",
            fg=C_MUTED, bg=C_BG, font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 6))
        prev_wrap = tk.Frame(right, bg=C_BG)
        prev_wrap.pack(fill=tk.BOTH, expand=True)
        self._preview_canvas = tk.Canvas(prev_wrap, bg=C_BG, highlightthickness=0, bd=0)
        prev_scroll = ttk.Scrollbar(prev_wrap, orient=tk.VERTICAL, command=self._preview_canvas.yview)
        self._preview_canvas.configure(yscrollcommand=prev_scroll.set)
        prev_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._preview_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._preview_inner = tk.Frame(self._preview_canvas, bg=C_BG)
        self._preview_window = self._preview_canvas.create_window((0, 0), window=self._preview_inner, anchor="nw")
        self._preview_inner.bind("<Configure>", lambda _e: self._preview_canvas.configure(scrollregion=self._preview_canvas.bbox("all")))
        self._preview_canvas.bind("<Configure>", lambda e: self._preview_canvas.itemconfigure(self._preview_window, width=e.width))
        self._preview_canvas.bind("<MouseWheel>", self._on_preview_wheel)
        self._preview_photos: list[ImageTk.PhotoImage] = []
        self._preview_token = 0

        # Left: scrollable controls (window is shorter than the form)
        left_wrap = tk.Frame(shell, bg=C_BG)
        left_wrap.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._left_canvas = tk.Canvas(left_wrap, bg=C_BG, highlightthickness=0, bd=0)
        left_scroll = ttk.Scrollbar(left_wrap, orient=tk.VERTICAL, command=self._left_canvas.yview)
        self._left_canvas.configure(yscrollcommand=left_scroll.set)
        left_scroll.pack(side=tk.LEFT, fill=tk.Y)
        self._left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        root = tk.Frame(self._left_canvas, bg=C_BG)
        self._left_window = self._left_canvas.create_window((0, 0), window=root, anchor="nw")
        root.bind("<Configure>", self._sync_left_scroll)
        self._left_canvas.bind("<Configure>", self._sync_left_width)

        tk.Label(
            root, text="Story Overlay", fg=C_TEXT, bg=C_BG,
            font=("Segoe UI Semibold", 22),
        ).pack(anchor="w")
        tk.Label(
            root,
            text="N роликов · случайный свободный клип · случайный текст из списка",
            fg=C_MUTED, bg=C_BG, font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(2, 12))

        self._section(root, "Папки с видео")
        tk.Label(
            root,
            text="каждая папка или файл с новой строки:  2. путь   3. путь   —  http-ссылки не читаются",
            fg=C_MUTED, bg=C_BG, font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))
        row = tk.Frame(root, bg=C_BG)
        row.pack(fill=tk.X, pady=(6, 4))
        self.folders_box = tk.Text(
            row, height=5, wrap=tk.NONE, bg=C_INPUT, fg=C_TEXT,
            insertbackground=C_TEXT, font=("Segoe UI", 11),
            relief=tk.FLAT, padx=12, pady=8, undo=False,
            highlightthickness=1, highlightbackground=C_BORDER, highlightcolor=C_ACCENT,
        )
        self.folders_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.folders_box.insert("1.0", "\n".join(str(p) for p in DEFAULT_BG_DIRS))
        enable_edit_hotkeys(self.folders_box)
        self.folders_box.bind("<<Modified>>", self._on_folders_modified)
        self.folders_box.edit_modified(False)

        side = tk.Frame(row, bg=C_BG)
        side.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        self._btn(side, "Добавить папку", self.add_folder, primary=False).pack(fill=tk.X, pady=(0, 6))
        self._btn(side, "Очистить", self.clear_folders, primary=False).pack(fill=tk.X)

        self.video_count = tk.Label(root, text="", fg=C_MUTED, bg=C_BG, font=("Segoe UI", 9))
        self.video_count.pack(anchor="w", pady=(2, 6))

        usage_head = tk.Frame(root, bg=C_BG)
        usage_head.pack(fill=tk.X)
        self._btn(usage_head, "Сбросить занятость", self._reset_usage, primary=False).pack(side=tk.RIGHT)
        tk.Label(
            usage_head, text="Использование видео", fg=C_ACCENT, bg=C_BG,
            font=("Segoe UI Semibold", 11),
        ).pack(side=tk.LEFT, anchor="w")
        tk.Label(
            root,
            text="один клип + один текст = пара; тот же клип с другим текстом можно",
            fg=C_MUTED, bg=C_BG, font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))
        usage_row = tk.Frame(root, bg=C_BG)
        usage_row.pack(fill=tk.X, pady=(6, 10))
        self.usage_box = tk.Text(
            usage_row, height=8, wrap=tk.WORD, bg=C_INPUT, fg=C_TEXT,
            insertbackground=C_TEXT, font=("Segoe UI", 10),
            relief=tk.FLAT, padx=12, pady=8, cursor="arrow",
            highlightthickness=1, highlightbackground=C_BORDER, highlightcolor=C_BORDER,
        )
        self.usage_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.usage_box.tag_configure("folder", foreground=C_ACCENT, font=("Segoe UI Semibold", 10))
        self.usage_box.tag_configure("ok", foreground=C_OK)
        self.usage_box.tag_configure("bad", foreground=C_ERR)
        self.usage_box.tag_configure("muted", foreground=C_MUTED)
        usage_scroll = ttk.Scrollbar(usage_row, command=self.usage_box.yview)
        usage_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.usage_box.configure(yscrollcommand=usage_scroll.set)
        self.usage_box.bind("<KeyPress>", self._usage_keypress)
        self.usage_box.bind("<<Paste>>", lambda _e: "break")
        self.usage_box.bind("<<Cut>>", lambda _e: "break")

        self._section(root, "Папка экспорта")
        out_row = tk.Frame(root, bg=C_BG)
        out_row.pack(fill=tk.X, pady=(6, 10))
        self.out_var = tk.StringVar(value=str(DEFAULT_OUT_DIR))
        self.out_entry = tk.Entry(
            out_row, textvariable=self.out_var, bg=C_INPUT, fg=C_TEXT,
            insertbackground=C_TEXT, font=("Segoe UI", 11), relief=tk.FLAT,
            highlightthickness=1, highlightbackground=C_BORDER, highlightcolor=C_ACCENT,
        )
        self.out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(0, 10))
        enable_edit_hotkeys(self.out_entry)
        self._btn(out_row, "Обзор…", self.pick_out_dir, primary=False).pack(side=tk.RIGHT)

        bottom = tk.Frame(root, bg=C_BG)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))

        self._section(bottom, "Цвет / свет")
        self._look = DEFAULT_LOOK
        self._look_btns: dict[str, tk.Button] = {}
        self._loading_look = False
        looks = tk.Frame(bottom, bg=C_BG)
        looks.pack(fill=tk.X, pady=(6, 4))
        for i, preset in enumerate(LOOKS):
            btn = tk.Button(
                looks, text=preset.label, command=lambda k=preset.id: self._select_look(k),
                bg=C_BTN, fg=C_TEXT, activebackground="#2a3342", activeforeground=C_TEXT,
                relief=tk.FLAT, padx=8, pady=8, cursor="hand2",
                font=("Segoe UI", 10),
            )
            btn.grid(row=i // 3, column=i % 3, sticky="ew", padx=3, pady=3)
            self._look_btns[preset.id] = btn
        for col in range(3):
            looks.columnconfigure(col, weight=1)
        self._look_hint = tk.Label(
            bottom, text="", fg=C_MUTED, bg=C_BG, font=("Segoe UI", 9), anchor="w", justify="left", wraplength=640,
        )
        self._look_hint.pack(fill=tk.X, pady=(2, 4))

        self._knob_frame = tk.Frame(bottom, bg=C_BG)
        knob_head = tk.Frame(self._knob_frame, bg=C_BG)
        knob_head.pack(fill=tk.X)
        self._knob_title = tk.Label(
            knob_head, text="Подстройка", fg=C_ACCENT, bg=C_BG, font=("Segoe UI Semibold", 10),
        )
        self._knob_title.pack(side=tk.LEFT, anchor="w")
        self._btn(knob_head, "Подогнать по лицу", self._calibrate_face, primary=False).pack(side=tk.RIGHT)
        self._knob_vars: dict[str, tk.IntVar] = {}
        self._knob_labels: dict[str, tk.Label] = {}
        for key, title in (
            ("exposure", "Подъём света"),
            ("contrast", "Контраст"),
            ("warmth", "Теплота"),
            ("saturation", "Насыщенность"),
            ("gamma", "Гамма"),
        ):
            self._add_knob(self._knob_frame, key, title, 50)
        self._paint_look()
        self._apply_preset_knobs(self._look)
        self._knob_frame.pack(fill=tk.X, pady=(2, 8))

        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(0, 8))

        action = tk.Frame(bottom, bg=C_BG)
        action.pack(fill=tk.X)
        self.status = tk.Label(action, text="Готово к запуску", fg=C_MUTED, bg=C_BG, font=("Segoe UI", 10))
        self.status.pack(side=tk.LEFT, anchor="w")
        self.run_btn = self._btn(action, "Сгенерировать", self.run_batch, primary=True)
        self.run_btn.pack(side=tk.RIGHT)
        count_box = tk.Frame(action, bg=C_BG)
        count_box.pack(side=tk.RIGHT, padx=(0, 10))
        tk.Label(count_box, text="роликов", fg=C_MUTED, bg=C_BG, font=("Segoe UI", 9)).pack(side=tk.RIGHT)
        self.count_var = tk.StringVar(value="5")
        self.count_spin = tk.Spinbox(
            count_box, from_=1, to=500, width=5, textvariable=self.count_var,
            bg=C_INPUT, fg=C_TEXT, buttonbackground=C_BTN, insertbackground=C_TEXT,
            relief=tk.FLAT, font=("Segoe UI", 12), justify="center",
            command=self._schedule_refresh,
        )
        self.count_spin.pack(side=tk.RIGHT, padx=(0, 6), ipady=4)
        self.count_spin.bind("<KeyRelease>", lambda _e: self._schedule_refresh(120))
        self._btn(action, "Обновить превью", self.preview_folders, primary=False).pack(side=tk.RIGHT, padx=(0, 8))

        head = tk.Frame(root, bg=C_BG)
        head.pack(fill=tk.X)
        self._section(head, "Тексты")
        tk.Label(
            head, text="формат:  1. story…   2. story…   эмодзи можно",
            fg=C_MUTED, bg=C_BG, font=("Segoe UI", 9),
        ).pack(side=tk.RIGHT, anchor="e")

        self.text_box = tk.Text(
            root, height=12, wrap=tk.WORD, bg=C_INPUT, fg=C_TEXT,
            insertbackground=C_TEXT, font=("Segoe UI", 11),
            relief=tk.FLAT, padx=14, pady=12, undo=False,
            highlightthickness=1, highlightbackground=C_BORDER, highlightcolor=C_ACCENT,
        )
        self.text_box.pack(fill=tk.X, pady=(6, 4))
        if DEFAULT_TEXTS.exists():
            self.text_box.insert("1.0", DEFAULT_TEXTS.read_text(encoding="utf-8"))
        enable_edit_hotkeys(self.text_box)
        self.text_box.bind("<<Modified>>", self._on_texts_modified)
        self.text_box.edit_modified(False)

        self.text_count = tk.Label(root, text="", fg=C_MUTED, bg=C_BG, font=("Segoe UI", 9))
        self.text_count.pack(anchor="w", pady=(0, 4))
        self._bind_page_scroll(left_wrap)
        self._schedule_refresh(0)

    def _section(self, parent, title: str) -> None:
        tk.Label(
            parent, text=title, fg=C_ACCENT, bg=parent.cget("bg"),
            font=("Segoe UI Semibold", 11),
        ).pack(anchor="w")

    def _btn(self, parent, text, cmd, primary: bool = False) -> tk.Button:
        if primary:
            return tk.Button(
                parent, text=text, command=cmd,
                bg=C_BTN_PRIMARY, fg=C_BTN_PRIMARY_FG,
                activebackground="#f0dfa0", activeforeground=C_BTN_PRIMARY_FG,
                relief=tk.FLAT, padx=18, pady=10, cursor="hand2",
                font=("Segoe UI Semibold", 11),
            )
        return tk.Button(
            parent, text=text, command=cmd,
            bg=C_BTN, fg=C_TEXT,
            activebackground="#2a3342", activeforeground=C_TEXT,
            relief=tk.FLAT, padx=12, pady=8, cursor="hand2",
            font=("Segoe UI", 10),
        )

    def add_folder(self) -> None:
        d = filedialog.askdirectory(title="Папка с видео")
        if not d:
            return
        cur = self.folders_box.get("1.0", "end-1c").strip()
        if cur:
            self.folders_box.insert(tk.END, "\n" + d)
        else:
            self.folders_box.delete("1.0", tk.END)
            self.folders_box.insert("1.0", d)
        self.folders_box.edit_modified(False)
        self._cache_folders_raw = None
        self._schedule_refresh(0)

    def clear_folders(self) -> None:
        self.folders_box.delete("1.0", tk.END)
        self.folders_box.edit_modified(False)
        self._cache_folders_raw = None
        self._schedule_refresh(0)

    def pick_out_dir(self) -> None:
        d = filedialog.askdirectory(
            title="Папка экспорта",
            initialdir=self.out_var.get() or str(DEFAULT_OUT_DIR),
        )
        if d:
            self.out_var.set(d)
            self.out_entry._edit_remember()

    def _sync_left_scroll(self, _event=None) -> None:
        self._left_canvas.configure(scrollregion=self._left_canvas.bbox("all"))

    def _sync_left_width(self, event) -> None:
        self._left_canvas.itemconfigure(self._left_window, width=event.width)

    def _bind_page_scroll(self, widget) -> None:
        widget.bind("<MouseWheel>", self._on_page_wheel, add="+")
        for child in widget.winfo_children():
            self._bind_page_scroll(child)

    def _on_page_wheel(self, event):
        widget = event.widget
        if isinstance(widget, tk.Text):
            top, bottom = widget.yview()
            if event.delta < 0 and bottom < 0.999:
                return None
            if event.delta > 0 and top > 0.001:
                return None
        self._left_canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _usage_keypress(self, event):
        if event.keysym in (
            "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
            "Shift_L", "Shift_R", "Control_L", "Control_R",
        ):
            return None
        if (event.state & _CTRL_BIT) and not (event.state & _ALT_BIT):
            code = int(event.keycode)
            if code == _VK_A:
                _select_all(self.usage_box)
                return "break"
            if code == _VK_C:
                self.usage_box.event_generate("<<Copy>>")
                return "break"
        return "break"

    def _on_texts_modified(self, _event=None) -> None:
        if self.text_box.edit_modified():
            self.text_box.edit_modified(False)
            self._cache_texts_raw = None
            self._schedule_refresh(450)

    def _on_folders_modified(self, _event=None) -> None:
        if self.folders_box.edit_modified():
            self.folders_box.edit_modified(False)
            self._cache_folders_raw = None
            self._schedule_refresh(300)

    def _schedule_refresh(self, delay: int = 250) -> None:
        if self._refresh_after is not None:
            try:
                self.after_cancel(self._refresh_after)
            except tk.TclError:
                pass
        self._refresh_after = self.after(max(0, int(delay)), self._refresh_counts)

    def _write_usage(self, text: str, *tags: str) -> None:
        self.usage_box.insert(tk.END, text, tags)

    def _apply_usage_summary(self, summary: dict, texts_n: int) -> None:
        key = (
            summary.get("free_ids"),
            summary.get("combo_n"),
            summary.get("total"),
            texts_n,
            tuple(
                (f["label"], f["free"], f["blocked"], f["paired"], tuple(f["details"]))
                for f in summary.get("folders", ())
            ),
        )
        if key == self._usage_key:
            return
        y0 = self.usage_box.yview()[0]
        self._usage_key = key
        self.usage_box.delete("1.0", tk.END)
        folders = summary.get("folders") or []
        if not folders:
            self._write_usage(
                "Укажи папки — здесь будет, сколько видео свободно и какие уже заняты.",
                "muted",
            )
            return
        free_n = int(summary.get("free_n") or 0)
        combo_n = int(summary.get("combo_n") or 0)
        total = int(summary.get("total") or 0)
        self._write_usage(f"к генерации: свободно {free_n}", "ok" if free_n else "bad")
        self._write_usage(f" клипов из {total}", "muted")
        if texts_n:
            self._write_usage(f" · комбинаций {combo_n}", "ok" if combo_n else "bad")
        self._write_usage("\n", "muted")
        self._write_usage(
            "правило: один клип + один текст = одна пара; тот же клип с другим текстом можно\n",
            "muted",
        )
        for folder in folders:
            self._write_usage(f"\n{folder['label']}\n", "folder")
            self._write_usage(
                f"всего {folder['total']} · блок {folder['blocked']} · уже с текстом {folder['paired']} · "
            )
            self._write_usage(
                f"свободны для списка {folder['free']}\n",
                "ok" if folder["free"] else "bad",
            )
            details = folder.get("details") or []
            if details:
                self._write_usage("детали (кратко):\n", "muted")
                for line in details:
                    self._write_usage(line + "\n", "muted")
                more = int(folder.get("details_more") or 0)
                if more:
                    self._write_usage(f"  … и ещё {more}\n", "muted")
            else:
                self._write_usage("занятых нет\n", "muted")
        self.usage_box.yview_moveto(y0)

    def _reset_usage(self) -> None:
        if self._busy:
            messagebox.showinfo("Занято", "Подожди, идёт генерация")
            return
        vids, _warnings = self._videos()
        touched = [
            video for video in vids
            if self.ledger.is_blocked(video) or self.ledger.pairs_for(video)
        ]
        if not touched:
            messagebox.showinfo("Занятость", "В этих папках нет занятых видео")
            return
        names = "\n".join(video.name for video in touched[:12])
        more = f"\n… и ещё {len(touched) - 12}" if len(touched) > 12 else ""
        if not messagebox.askyesno(
            "Сбросить занятость",
            f"Снять пары и блоки с {len(touched)} видео в указанных папках?\n"
            f"Они снова попадут в генерацию.\n\n{names}{more}",
        ):
            return
        self.ledger.forget(touched)
        self._usage_key = None
        self._schedule_refresh(0)

    def _videos(self) -> tuple[list[Path], list[str]]:
        raw = self.folders_box.get("1.0", "end-1c")
        if raw != self._cache_folders_raw:
            self._cache_folders_raw = raw
            groups, warnings = parse_source_groups(raw)
            vids: list[Path] = []
            seen: set[str] = set()
            for _label, group_vids in groups:
                for vid in group_vids:
                    key = video_id(vid)
                    if key in seen:
                        continue
                    seen.add(key)
                    vids.append(vid)
            self._cache_groups = groups
            self._cache_vids = vids
            self._cache_warnings = warnings
        return self._cache_vids, self._cache_warnings

    def _texts(self) -> list[str]:
        raw = self.text_box.get("1.0", "end-1c")
        if raw != self._cache_texts_raw:
            self._cache_texts_raw = raw
            self._cache_texts = parse_batch_text_blob(raw)
        return self._cache_texts

    def _refresh_counts(self) -> None:
        self._refresh_after = None
        raw_text = self.text_box.get("1.0", "end-1c")
        raw_folders = self.folders_box.get("1.0", "end-1c")
        n = self._batch_count()
        self._stats_token += 1
        token = self._stats_token
        # Keep UI responsive: show that we're counting, compute off the main thread.
        self.video_count.config(text="считаю свободные клипы…", fg=C_MUTED)
        self.text_count.config(text="считаю тексты…", fg=C_MUTED)

        def work() -> None:
            try:
                texts = parse_batch_text_blob(raw_text)
                groups, warnings = parse_source_groups(raw_folders)
                vids: list[Path] = []
                seen: set[str] = set()
                for _label, group_vids in groups:
                    for vid in group_vids:
                        key = video_id(vid)
                        if key in seen:
                            continue
                        seen.add(key)
                        vids.append(vid)
                summary = self.ledger.folder_usage_summary(groups, texts, detail_limit=10)
                self._q.put((
                    "stats",
                    {
                        "token": token,
                        "texts": texts,
                        "groups": groups,
                        "vids": vids,
                        "warnings": warnings,
                        "raw_text": raw_text,
                        "raw_folders": raw_folders,
                        "summary": summary,
                        "n": n,
                    },
                ))
            except Exception as e:
                self._q.put(("stats_error", (token, str(e))))

        threading.Thread(target=work, daemon=True).start()

    def _apply_stats(self, payload: dict) -> None:
        if payload.get("token") != self._stats_token:
            return
        texts: list[str] = payload["texts"]
        vids: list[Path] = payload["vids"]
        warnings: list[str] = payload["warnings"]
        summary: dict = payload["summary"]
        n = int(payload.get("n") or 0)
        self._cache_texts_raw = payload["raw_text"]
        self._cache_texts = texts
        self._cache_folders_raw = payload["raw_folders"]
        self._cache_groups = payload["groups"]
        self._cache_vids = vids
        self._cache_warnings = warnings

        free_n = int(summary.get("free_n") or 0)
        combo_n = int(summary.get("combo_n") or 0)
        self._apply_usage_summary(summary, len(texts))

        if vids:
            extra = f"  ·  {warnings[0]}" if warnings else ""
            short = n > free_n if texts else not free_n
            self.video_count.config(
                text=(
                    f"свободно {free_n} из {len(vids)} клипов"
                    + (f" · {combo_n} комбинаций с текстами" if texts else "")
                    + extra
                ),
                fg=C_ERR if short or warnings else C_OK,
            )
        elif warnings:
            self.video_count.config(text=warnings[0], fg=C_ERR)
        else:
            self.video_count.config(
                text="Вставь пути к папкам или файлам, каждый с новой строки",
                fg=C_ERR,
            )

        if texts:
            if not vids:
                note = ""
            elif n > free_n:
                note = f"  ·  свободно только {free_n} клипов / {combo_n} пар"
            else:
                note = "  ·  клип+текст случайно, без повтора той же пары"
            self.text_count.config(
                text=f"{len(texts)} текстов в списке  ·  выйдет {n} роликов{note}",
                fg=C_ERR if vids and n > free_n else C_OK,
            )
        else:
            self.text_count.config(text="Вставь тексты в формате 1. … 2. …", fg=C_MUTED)

    def _add_knob(self, parent, key: str, title: str, default: int) -> None:
        row = tk.Frame(parent, bg=C_BG)
        row.pack(fill=tk.X, pady=1)
        tk.Label(row, text=title, fg=C_MUTED, bg=C_BG, font=("Segoe UI", 9), width=16, anchor="w").pack(side=tk.LEFT)
        var = tk.IntVar(value=default)
        self._knob_vars[key] = var
        lbl = tk.Label(row, text=str(default), fg=C_ACCENT, bg=C_BG, font=("Segoe UI Semibold", 10), width=3)
        self._knob_labels[key] = lbl
        lbl.pack(side=tk.RIGHT)
        tk.Scale(
            row, from_=0, to=100, orient=tk.HORIZONTAL, variable=var, showvalue=0,
            bg=C_BG, fg=C_TEXT, highlightthickness=0, troughcolor=C_INPUT,
            activebackground=C_ACCENT, sliderrelief=tk.FLAT, bd=0,
            command=lambda _v, k=key: self._on_knob(k),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

    def _paint_look(self) -> None:
        for key, btn in self._look_btns.items():
            if key == self._look:
                btn.config(bg=C_BTN_PRIMARY, fg=C_BTN_PRIMARY_FG, activebackground="#f0dfa0")
            else:
                btn.config(bg=C_BTN, fg=C_TEXT, activebackground="#2a3342")
        preset = LOOK_BY_ID[self._look]
        self._look_hint.config(text=preset.hint)
        if hasattr(self, "_knob_title"):
            self._knob_title.config(text=f"Подстройка · {preset.label}")

    def _apply_preset_knobs(self, key: str) -> None:
        preset = LOOK_BY_ID[key]
        self._loading_look = True
        self._knob_vars["exposure"].set(int(preset.exposure))
        self._knob_vars["contrast"].set(int(preset.contrast))
        self._knob_vars["warmth"].set(int(preset.warmth))
        self._knob_vars["saturation"].set(int(preset.saturation))
        self._knob_vars["gamma"].set(int(preset.gamma))
        for name, var in self._knob_vars.items():
            self._knob_labels[name].config(text=str(var.get()))
        self._loading_look = False

    def _select_look(self, key: str) -> None:
        if key not in LOOK_BY_ID:
            return
        self._look = key
        self._apply_preset_knobs(key)
        self._paint_look()
        if not self._knob_frame.winfo_ismapped():
            self._knob_frame.pack(fill=tk.X, pady=(2, 8), before=self.progress)
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(280, self._preview_look)

    def _on_knob(self, key: str) -> None:
        val = int(self._knob_vars[key].get())
        self._knob_labels[key].config(text=str(val))
        if self._loading_look:
            return
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(280, self._preview_look)

    def _calibrate_face(self) -> None:
        vids, _warnings = self._videos()
        free = unused_videos(vids, self.ledger, self._texts())
        video = (free or vids or [None])[0]
        if video is None:
            messagebox.showinfo("Калибровка", "Сначала укажи папку с видео")
            return
        self.status.config(text=f"Калибрую по лицу · {video.name}", fg=C_ACCENT)
        self.update_idletasks()
        found = exposure_for_face(video)
        if found is None:
            messagebox.showerror("Калибровка", "Не удалось прочитать кадр")
            return
        exposure, raw, graded = found
        self._knob_vars["exposure"].set(int(round(exposure)))
        self._on_knob("exposure")
        self._look_hint.config(
            text=f"Подогнано по {video.name}: лицо {raw:.0f} → {graded:.0f} из 255",
        )
        self.status.config(
            text=f"Свет подогнан · лицо {raw:.0f} → {graded:.0f}",
            fg=C_OK,
        )

    def _on_preview_wheel(self, event):
        self._preview_canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _batch_count(self) -> int:
        try:
            return max(0, int(str(self.count_var.get()).strip()))
        except (ValueError, tk.TclError):
            return 0

    def _preview_look(self) -> None:
        self._preview_job = None
        texts = self._texts()
        if not texts or not unused_videos(self._videos()[0], self.ledger, texts):
            return
        self.preview_folders(silent=True)

    def _grade_from_ui(self) -> GradeControls:
        v = self._knob_vars
        return GradeControls(
            look=self._look,
            exposure=float(v["exposure"].get()),
            contrast=float(v["contrast"].get()),
            warmth=float(v["warmth"].get()),
            saturation=float(v["saturation"].get()),
            gamma=float(v["gamma"].get()),
        )

    def preview_folders(self, silent: bool = False) -> None:
        self._preview_job = None
        if self._busy:
            return
        texts = self._texts()
        groups, _warnings = parse_source_groups(self.folders_box.get("1.0", tk.END))
        if not texts:
            if not silent:
                messagebox.showinfo("Превью", "Сначала вставь хотя бы один текст")
            return
        jobs: list[tuple[str, Path, int, int]] = []
        for label, vids in groups:
            free = unused_videos(vids, self.ledger, texts)
            video = free[0] if free else (vids[0] if vids else None)
            if video is None:
                continue
            jobs.append((Path(label).name, video, len(free), len(vids)))
        if not jobs:
            if not silent:
                messagebox.showinfo("Превью", "Сначала укажи папку с видео")
            return
        grade = self._grade_from_ui()
        style = replace(self.style_cfg)
        font_path = self.font_path
        text = texts[0]
        self._preview_token += 1
        token = self._preview_token
        self.status.config(text=f"Превью по папкам… 0/{len(jobs)}", fg=C_ACCENT)

        def work() -> None:
            try:
                ready: list[tuple[str, str, int, int, Image.Image]] = []
                screens = layout_screens(text, style, font_path)
                for i, (name, video, nfree, ntot) in enumerate(jobs):
                    self._q.put(("status", f"Превью {i + 1}/{len(jobs)} · {name}"))
                    img = composite_preview(video, screens[0], style, font_path, grade=grade)
                    ready.append((name, video.name, nfree, ntot, img))
                self._q.put(("previews", (token, ready)))
            except Exception as e:
                self._q.put(("status", f"Превью не собралось: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def _show_folder_previews(self, token: int, ready: list[tuple[str, str, int, int, Image.Image]]) -> None:
        if token != self._preview_token:
            return
        for child in self._preview_inner.winfo_children():
            child.destroy()
        self._preview_photos = []
        thumb_w = 300
        for name, clip, nfree, ntot, img in ready:
            thumb_h = max(1, int(thumb_w * img.height / img.width))
            thumb = img.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(thumb)
            self._preview_photos.append(photo)
            card = tk.Frame(self._preview_inner, bg=C_BG)
            card.pack(fill=tk.X, pady=(0, 12))
            tk.Label(
                card, text=name, fg=C_ACCENT, bg=C_BG,
                font=("Segoe UI Semibold", 9), anchor="w",
            ).pack(fill=tk.X)
            tk.Label(card, image=photo, bg="#050505").pack(anchor="w")
            note = f"{clip} · свободно {nfree} из {ntot}"
            if nfree == 0:
                note = f"{clip} · в папке всё занято"
            tk.Label(
                card, text=note, fg=C_ERR if nfree == 0 else C_MUTED, bg=C_BG,
                font=("Segoe UI", 8), anchor="w",
            ).pack(fill=tk.X, pady=(2, 0))
            card.bind("<MouseWheel>", self._on_preview_wheel)
            for child in card.winfo_children():
                child.bind("<MouseWheel>", self._on_preview_wheel)
        self.status.config(text=f"Превью: {len(ready)} папок", fg=C_OK)
        self._preview_canvas.yview_moveto(0)

    def run_batch(self) -> None:
        if self._busy:
            return
        texts = self._texts()
        vids, warnings = self._videos()
        free = unused_videos(vids, self.ledger, texts)
        if not texts:
            messagebox.showerror("Тексты", "Вставь тексты в формате 1. … 2. …")
            return
        n = self._batch_count()
        if n < 1:
            messagebox.showerror("Сколько роликов", "Поставь число роликов больше нуля")
            return
        if warnings and vids:
            self.status.config(text=warnings[0], fg=C_ERR)
        if not vids:
            messagebox.showerror("Видео", "Укажи хотя бы одну папку с видео")
            return
        if len(free) < n:
            combo_n = self.ledger.free_combo_count(vids, texts)
            messagebox.showerror(
                "Не хватает свободных комбинаций",
                f"Нужно {n} роликов, свободных клипов под эти тексты: {len(free)} "
                f"(комбинаций {combo_n}).\n"
                "Та же пара клип+текст повторно не берётся; клип с другим текстом — можно.",
            )
            return
        if not find_ffmpeg():
            messagebox.showerror("ffmpeg", "ffmpeg не найден в PATH")
            return

        out_dir = Path(self.out_var.get().strip() or str(DEFAULT_OUT_DIR))
        out_dir.mkdir(parents=True, exist_ok=True)
        style = replace(self.style_cfg)
        font_path = self.font_path
        grade = self._grade_from_ui()
        jobs = sample_jobs(vids, texts, n, self.ledger)
        taken_names = {p.name.lower() for p in out_dir.glob("*.mp4")} if out_dir.exists() else set()

        self._busy = True
        self.run_btn.config(state=tk.DISABLED)
        self.progress["maximum"] = n
        self.progress["value"] = 0
        self.status.config(text=f"Старт… {n} случайных пар клип+текст", fg=C_ACCENT)

        def work():
            try:
                for i, (video, text) in enumerate(jobs):
                    self._q.put(("status", f"{i + 1}/{n}  ·  {video.name}"))
                    self._q.put(("progress", i))
                    screens = layout_screens(text, style, font_path)
                    out = unique_story_path(out_dir, text, taken_names)
                    export_story(video, screens, out, style, font_path, grade=grade)
                    # Defer disk write until the end — avoids UI stalls mid-batch.
                    self.ledger.mark(video, out, text, save=False)
                    if i == n - 1 or (i + 1) % 5 == 0:
                        self._q.put(("usage_light", i + 1))
                self.ledger.save()
                self._q.put(("progress", n))
                self._q.put(("done", f"{n} роликов → {out_dir}"))
            except Exception as e:
                try:
                    self.ledger.save()
                except Exception:
                    pass
                self._q.put(("error", str(e)))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "status":
                    self.status.config(text=payload, fg=C_ACCENT)
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "usage_light":
                    # Cheap label only — full stats recalculate after the batch.
                    done = int(payload or 0)
                    total = int(self.progress["maximum"] or 0)
                    left = max(0, len(self._cache_vids) - done) if self._cache_vids else "?"
                    self.video_count.config(
                        text=f"генерация {done}/{total} · клипов в пуле ~{left}",
                        fg=C_ACCENT,
                    )
                elif kind == "stats":
                    self._apply_stats(payload)
                elif kind == "stats_error":
                    token, err = payload
                    if token == self._stats_token:
                        self.video_count.config(text=f"ошибка подсчёта: {err}", fg=C_ERR)
                        self.text_count.config(text="", fg=C_MUTED)
                elif kind == "previews":
                    token, ready = payload
                    self._show_folder_previews(token, ready)
                elif kind == "done":
                    self._busy = False
                    self.run_btn.config(state=tk.NORMAL)
                    self._usage_key = None
                    self._cache_texts_raw = None
                    self._schedule_refresh(0)
                    self.status.config(text=payload, fg=C_OK)
                    messagebox.showinfo("Готово", payload)
                    self.preview_folders(silent=True)
                elif kind == "error":
                    self._busy = False
                    self.run_btn.config(state=tk.NORMAL)
                    self._usage_key = None
                    self._schedule_refresh(0)
                    self.status.config(text="Ошибка", fg=C_ERR)
                    messagebox.showerror("Ошибка", payload)
        except queue.Empty:
            pass
        self.after(120, self._poll)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

SAMPLE_TEXTS = [
    'guys what do i do. our company just fired the one engineer who kept everything running because his tracker said he "only" worked three hours a day. this man automated half the company, ran our billing on Dodo Payments, shipped more than the other four combined, and still had time to go to the gym. leadership said full-time means "visible effort." he said "you pay me for outcomes," turned off Slack, and left. it\'s been a week and three systems are down that nobody knew existed. the only documentation is a file called notes.txt says "good luck." i think we fired the actual company.',
    "if you built something people actually use and you're still not charging for it, this is for you. my friend had the users, the reviews, the demand, but his monetisation plan was basically just hoping someone sponsors the repo. i had to explain that being a developer doesn't mean everything you make is free. i showed him Dodo Payments, subscriptions and global selling with the tax and reporting automated as merchant of record. now he's actually making money off the thing he spent months building. the product was never the problem. he just never learned to sell it. he just never learned to sell it.",
    "why the fuck was no one going to tell me when you join the corporate world you have to beg on your hands and knees for a task. but the ones they give you genuinely take 10-minutes but you have to pretend it's taking up the whole day. like last week they asked me to add the payments side to our app, i integrated Dodo Payments in five minutes and then spent the next three hours moving my mouse so Teams stayed green. Teams stayed green.",
    "guys our controller told leadership our runway math was wrong three months before it mattered, and they called her a pessimist. she was right, obviously. she'd automated the billing and tax through dodo payments so the revenue side was never the issue, the issue was the spending nobody wanted to look at. so she stopped bringing it up, updated the forecast quietly, and took another offer. it's been a week, the runway math has finally caught up with reality, and leadership is asking who could have possibly predicted this. she could have. she did. it's in an email they marked as read.",
    'guys we didn\'t extend our intern because "interns don\'t really do real work," and i think that\'s the funniest sentence anyone\'s ever been wrong about. this kid automated three of our workflows, set up our payments on Dodo Payments in what i can only assume was his spare time, and cleared a backlog older than his degree, all while being too polite to point out he was carrying more than the full-timers. his last day was tuesday. it is now thursday. two of the things he built have quietly stopped, nobody knew they existed, and the only trace he left was a Slack message that said "lmk if anything breaks." everything is breaking. he does not work here anymore. he starts at a competitor monday, and honestly, good for him.',
]


def write_sample_texts(path: Path) -> None:
    blocks = []
    for i, t in enumerate(SAMPLE_TEXTS, 1):
        blocks.append(f"{i}. {t}")
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def prepare_bg_from_source(src: Path, out_dir: Path, count: int = 4, clip_sec: float = 3.0) -> list[Path]:
    """Cut count random 3s clips and slow to 0.5x (→ 6s) — matches user pipeline."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg required")
    out_dir.mkdir(parents=True, exist_ok=True)
    dur = probe_duration(src)
    outs: list[Path] = []
    for i in range(count):
        start = random.uniform(0, max(0.1, dur - clip_sec - 1))
        out = out_dir / f"bg_{i + 1:02d}.mp4"
        # trim clip_sec then setpts=2.0*PTS for 0.5x
        fc = (
            f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{TARGET_H},setpts=2.0*PTS,fps={EXPORT_FPS}"
        )
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{start:.3f}", "-t", f"{clip_sec:.3f}",
            "-i", str(src),
            "-vf", fc, "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-1500:] or "prep failed")
        outs.append(out)
        print(f"prepared {out.name} from t={start:.1f}s")
    return outs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Story text overlay for talking-head videos")
    p.add_argument("--gui", action="store_true", help="Open GUI (default if no args)")
    p.add_argument("--text", type=str, help="Story text")
    p.add_argument("--text-file", type=Path, help="File with one story")
    p.add_argument("--batch", type=Path, help="Batch texts file (.txt / .json)")
    p.add_argument("--video", type=Path, help="Background video")
    p.add_argument("--videos-dir", type=Path, default=DEFAULT_BG_DIR)
    p.add_argument("--out", type=Path, help="Output mp4")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--font", type=Path, help="Bold .ttf path")
    p.add_argument("--font-size", type=int, default=FONT_SIZE)
    p.add_argument(
        "--look",
        choices=tuple(LOOK_BY_ID),
        default=DEFAULT_LOOK,
        help="none | soft | cinema | clean | gold | film",
    )
    p.add_argument("--preview", type=Path, help="Save preview PNG instead of video")
    p.add_argument("--write-samples", action="store_true", help="Write story_texts.txt")
    p.add_argument("--prepare-bgs", type=Path, help="Source video to cut 4 slowed clips into story_bgs/")
    p.add_argument("--prepare-count", type=int, default=4)
    args = p.parse_args(argv)

    if args.write_samples:
        write_sample_texts(DEFAULT_TEXTS)
        print(f"wrote {DEFAULT_TEXTS}")
        return 0

    if args.prepare_bgs:
        prepare_bg_from_source(args.prepare_bgs, DEFAULT_BG_DIR, args.prepare_count)
        return 0

    style = StyleConfig(font_size=args.font_size)
    font_path = args.font

    # Default to GUI when no actionable CLI flags
    want_cli = any([args.text, args.text_file, args.batch, args.preview, args.out])
    if args.gui or not want_cli:
        if not DEFAULT_TEXTS.exists():
            write_sample_texts(DEFAULT_TEXTS)
        app = StoryApp()
        app.mainloop()
        return 0

    videos = []
    if args.video:
        videos = [args.video]
    else:
        videos = list_videos(args.videos_dir)
    ledger = UsageLedger(USAGE_PATH)
    free = unused_videos(videos, ledger, None)

    if args.batch:
        texts = parse_batch_texts(args.batch)
        free = unused_videos(videos, ledger, texts)
        if not videos:
            print("No videos. Pass --video or use output/clips_6s/", file=sys.stderr)
            return 1
        if len(free) < len(texts):
            print(
                f"Не хватает свободных клипов под эти тексты: нужно {len(texts)}, свободно {len(free)}, "
                f"комбинаций {ledger.free_combo_count(videos, texts)}.",
                file=sys.stderr,
            )
            return 1
        args.out_dir.mkdir(parents=True, exist_ok=True)
        grade = GradeControls(look=args.look)
        taken_names = {p.name.lower() for p in args.out_dir.glob("*.mp4")} if args.out_dir.exists() else set()
        for i, text in enumerate(texts):
            # Prefer a free video for this specific text
            candidates = [v for v in free if not ledger.is_combo_used(v, text)]
            if not candidates:
                print(f"Нет свободного клипа для текста #{i + 1}", file=sys.stderr)
                return 1
            video = candidates[0]
            free = [v for v in free if v != video]
            screens = layout_screens(text, style, font_path)
            out = unique_story_path(args.out_dir, text, taken_names)
            clip_dur = probe_duration(video)
            print(f"[{i + 1}/{len(texts)}] {out.name} ({clip_dur:.1f}s, {screens[0].font_size}px) bg={video.name}")
            export_story(video, screens, out, style, font_path, grade=grade)
            ledger.mark(video, out, text)
        print(f"done -> {args.out_dir}")
        return 0

    text = args.text
    if args.text_file:
        text = args.text_file.read_text(encoding="utf-8").strip()
    if not text:
        print("Provide --text or --text-file", file=sys.stderr)
        return 1

    free = unused_videos(videos, ledger, [text])
    screens = layout_screens(text, style, font_path)
    if args.preview:
        vid = free[0] if free else (videos[0] if videos else None)
        img = composite_preview(vid, screens[0], style, font_path, grade=GradeControls(look=args.look))
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        img.save(args.preview)
        print(f"preview → {args.preview}")
        # also dump line breaks
        print("--- lines ---")
        print(screen_to_editable(screens[0]))
        return 0

    if not free:
        if videos:
            print("Нет свободной пары клип+этот текст (или клип в блоке).", file=sys.stderr)
        else:
            print("No videos. Pass --video or use output/clips_6s/", file=sys.stderr)
        return 1

    out = args.out or (args.out_dir / f"{slugify(text)}.mp4")
    export_story(free[0], screens, out, style, font_path, grade=GradeControls(look=args.look))
    ledger.mark(free[0], out, text)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
