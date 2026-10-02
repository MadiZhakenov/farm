#!/usr/bin/env python3
"""
Плашка TikTok «Reply to <name>'s comment» (ответ видео на комментарий).

Белая карточка «обтягивает» текст: ширина по самой длинной строке, вопрос
переносится по ширине колонки; серый заголовок сверху, жирный вопрос,
круглая аватарка слева у вопроса, хвостик снизу слева. Размеры — в долях
кегля вопроса (F), пропорции сняты с реальной плашки. Рисуется в 4x и
уменьшается (сглаживание). Эмодзи — Apple PNG, как в остальном оверлее.

    from core.comment_sticker import render_reply_sticker, NEUTRAL_COMMENTERS
    img = render_reply_sticker("maddie", "Whats the app called? 😬", body_px=24)
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
_FONT_DIR = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "otf"
FONT_BOLD = _FONT_DIR / "TikTokSans12pt-Bold.otf"
FONT_REGULAR = _FONT_DIR / "TikTokSans12pt-Regular.otf"

SS = 4  # суперсэмплинг
TEXT_COLOR = (22, 24, 35, 255)  # #161823 — текст TikTok
HEADER_COLOR = (138, 139, 145, 255)  # серый заголовок
CARD_COLOR = (255, 255, 255, 255)

# Пропорции в долях кегля вопроса (F), по реальной плашке
HEADER_SCALE = 0.56
LINE_GAP = 1.16  # межстрочный вопроса
HEADER_LINE_GAP = 1.22
HEADER_TO_BODY = 0.18
PAD_LEFT = 0.42
PAD_RIGHT = 0.55
PAD_TOP = 0.42
PAD_BOTTOM = 0.48
AVATAR_D = 1.38
AVATAR_GAP = 0.36
COLUMN_MAX = 7.3  # ширина колонки текста → «Whats the app / called? 😬»
RADIUS = 0.30
TAIL_W = 0.62
TAIL_H = 0.46
EMOJI_SCALE = 1.08

# Выдуманные нейтральные ники (не реальные аккаунты) + пастельные аватарки
NEUTRAL_COMMENTERS = (
    "maddie", "lena.k", "cozy.soph", "jules", "emmy",
    "bri ☁️", "kayla m", "sophie.r", "ash", "nina 🍂",
)
_AVATAR_PALETTE = (
    ((247, 196, 206), (233, 142, 166)),
    ((255, 218, 185), (240, 170, 120)),
    ((200, 220, 250), (140, 175, 235)),
    ((210, 235, 210), (150, 200, 160)),
    ((230, 210, 245), (180, 150, 220)),
    ((250, 232, 180), (225, 190, 110)),
)


def _font(path: Path, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), px)


def _runs(text: str) -> list[tuple[str, str]]:
    from assemble_ugc_reels import _tokenize_runs

    return _tokenize_runs(text)


def _emoji(cluster: str, px: int) -> Image.Image | None:
    from assemble_ugc_reels import _apple_emoji_rgba

    return _apple_emoji_rgba(cluster, px)


def _width(text: str, font: ImageFont.FreeTypeFont, emoji_px: int) -> float:
    w = 0.0
    for kind, chunk in _runs(text):
        if kind == "emoji":
            w += emoji_px + emoji_px * 0.08
        else:
            w += font.getlength(chunk)
    return w


def _is_emoji_only(word: str) -> bool:
    from assemble_ugc_reels import _EMOJI_RE

    return not _EMOJI_RE.sub("", word).replace("️", "").strip()


def _wrap(text: str, font: ImageFont.FreeTypeFont, emoji_px: int, max_w: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        # эмодзи не начинает строку: остаётся с предыдущим словом
        if cur and _width(trial, font, emoji_px) > max_w and not _is_emoji_only(w):
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _draw_line(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: float,
    y_top: float,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    emoji_px: int,
) -> None:
    ascent, _ = font.getmetrics()
    baseline = y_top + ascent
    cx = x
    for kind, chunk in _runs(text):
        if kind == "emoji":
            em = _emoji(chunk, emoji_px)
            if em is not None:
                img.alpha_composite(em, (int(round(cx)), int(round(baseline - emoji_px * 0.86))))
            cx += emoji_px + emoji_px * 0.08
        else:
            draw.text((cx, baseline), chunk, font=font, fill=fill, anchor="ls")
            cx += font.getlength(chunk)


def _avatar(d: int, seed: str) -> Image.Image:
    """Пастельный кружок с силуэтом — нейтральная заглушка вместо фото."""
    idx = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16) % len(_AVATAR_PALETTE)
    top, bottom = _AVATAR_PALETTE[idx]
    grad = Image.new("RGBA", (d, d))
    gd = ImageDraw.Draw(grad)
    for y in range(d):
        t = y / max(1, d - 1)
        gd.line([(0, y), (d, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    sil = ImageDraw.Draw(grad)
    head_r = d * 0.18
    cx, cy = d / 2, d * 0.40
    sil.ellipse((cx - head_r, cy - head_r, cx + head_r, cy + head_r), fill=(255, 255, 255, 200))
    sil.ellipse((cx - d * 0.33, d * 0.64, cx + d * 0.33, d * 1.12), fill=(255, 255, 255, 200))
    mask = Image.new("L", (d, d), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, d - 1, d - 1), fill=255)
    out = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out


def render_reply_sticker(
    username: str,
    comment: str,
    *,
    body_px: int = 24,
    avatar_seed: str | None = None,
) -> Image.Image:
    """Плашка RGBA по размеру содержимого (с хвостиком). body_px — кегль
    вопроса в пикселях итогового кадра."""
    F = body_px * SS
    body_font = _font(FONT_BOLD, F)
    head_font = _font(FONT_REGULAR, int(round(F * HEADER_SCALE)))
    e_body = int(round(F * EMOJI_SCALE))
    e_head = int(round(F * HEADER_SCALE * EMOJI_SCALE))

    col_max = F * COLUMN_MAX
    head_lines = _wrap(f"Reply to {username}'s comment", head_font, e_head, col_max)
    body_lines = _wrap(comment, body_font, e_body, col_max)
    col_w = max(
        [_width(t, head_font, e_head) for t in head_lines]
        + [_width(t, body_font, e_body) for t in body_lines]
    )

    head_h = len(head_lines) * head_font.size * HEADER_LINE_GAP
    body_h = len(body_lines) * F * LINE_GAP
    av = int(round(F * AVATAR_D))
    text_x = F * PAD_LEFT + av + F * AVATAR_GAP
    card_w = int(round(text_x + col_w + F * PAD_RIGHT))
    card_h = int(round(F * PAD_TOP + head_h + F * HEADER_TO_BODY + body_h + F * PAD_BOTTOM))
    tail_h = int(round(F * TAIL_H))

    img = Image.new("RGBA", (card_w, card_h + tail_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = int(round(F * RADIUS))
    draw.rounded_rectangle((0, 0, card_w - 1, card_h - 1), radius=r, fill=CARD_COLOR)
    # хвостик снизу слева: левый край уходит вниз остриём
    draw.polygon(
        [(0, card_h - r), (F * TAIL_W, card_h - 1), (0, card_h - 1 + tail_h)],
        fill=CARD_COLOR,
    )

    y = F * PAD_TOP
    for t in head_lines:
        _draw_line(img, draw, text_x, y, t, head_font, HEADER_COLOR, e_head)
        y += head_font.size * HEADER_LINE_GAP
    y += F * HEADER_TO_BODY
    body_top = y
    for t in body_lines:
        _draw_line(img, draw, text_x, y, t, body_font, TEXT_COLOR, e_body)
        y += F * LINE_GAP

    av_img = _avatar(av, avatar_seed or username)
    av_y = int(round(body_top + (body_h - av) / 2))
    img.alpha_composite(av_img, (int(round(F * PAD_LEFT)), av_y))

    return img.resize(
        (max(1, img.width // SS), max(1, img.height // SS)), Image.Resampling.LANCZOS
    )
