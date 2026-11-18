#!/usr/bin/env python3
"""
Экран профиля исполнителя в музыкальном приложении (тёмная тема, обобщённый — без логотипа и фирменного вида Spotify):
шапка-градиент, имя, «11 monthly listeners», Follow / ⋯ / круглая Play, список Popular с маленькими числами прослушиваний.
Для Drops-карусели 3 (build_drops_c3.py): слайд 3.4 и экран телефона на 3.3.

  from render_artist_stats import render
  img = render("Ryan Cole", 11, songs, height=2340, seed=3)
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import render_igdm as R  # noqa: E402  (шрифт TikTok Sans, текст, иконки)

W = 1080
SONGS = ["late night drive", "blue hour", "paper planes", "somewhere in between", "half asleep", "rooftop", "static",
         "nothing new", "slow motion", "4am thoughts", "after the rain", "low battery"]
PALETTES = [((86, 46, 140), (20, 14, 34)), ((28, 74, 120), (12, 18, 30)), ((120, 48, 70), (26, 12, 18)),
            ((40, 100, 90), (10, 24, 22)), ((110, 80, 40), (24, 18, 10))]


def _grad(w: int, h: int, top, bottom) -> Image.Image:
    t = np.linspace(0, 1, h)[:, None, None]
    a = np.array(top, np.float32)[None, None] * (1 - t) + np.array(bottom, np.float32)[None, None] * t
    return Image.fromarray(np.repeat(a, w, axis=1).astype(np.uint8))


def _cover(size: int, rng: random.Random) -> Image.Image:
    c1 = tuple(rng.randint(40, 220) for _ in range(3))
    c2 = tuple(rng.randint(10, 120) for _ in range(3))
    im = _grad(size, size, c1, c2)
    d = ImageDraw.Draw(im)
    for _ in range(3):
        x, y, r = rng.randint(0, size), rng.randint(0, size), rng.randint(size // 6, size // 2)
        d.ellipse((x - r, y - r, x + r, y + r), fill=tuple(rng.randint(60, 240) for _ in range(3)))
    return im.filter(ImageFilter.GaussianBlur(size / 9))


def render(name: str, listeners: int, songs: list[tuple[str, int]], height: int = 2340, seed: int = 0,
           head_frac: float = 0.36, arrow: bool = True) -> Image.Image:
    rng = random.Random(seed)
    top, bot = rng.choice(PALETTES)
    img = Image.new("RGB", (W, height), (18, 18, 18))
    head_h = int(height * head_frac)
    img.paste(_grad(W, head_h, top, (18, 18, 18)), (0, 0))
    d = ImageDraw.Draw(img)
    s = 1
    # статус-бар
    R.draw_text(img, 70, 52, f"{rng.randint(7, 11)}:{rng.randint(10, 59):02d}", 44, (255, 255, 255), wght=600)
    for i in range(4):
        d.rounded_rectangle((850 + i * 18, 76 - i * 8, 862 + i * 18, 92), radius=3, fill=(255, 255, 255))
    d.rounded_rectangle((940, 62, 1010, 96), radius=10, outline=(255, 255, 255), width=3)
    d.rounded_rectangle((946, 68, 946 + int(58 * rng.uniform(0.3, 0.9)), 90), radius=6, fill=(255, 255, 255))
    # назад
    if arrow:
        d.line((96, 210, 70, 236, 96, 262), fill=(255, 255, 255), width=8, joint="curve")
    # имя и слушатели
    ny = head_h - 250
    R.draw_text(img, 60, ny, name, 118, (255, 255, 255), wght=800)
    R.draw_text(img, 62, ny + 165, f"{listeners} monthly listeners", 40, (190, 190, 190), wght=500)
    by = head_h + 20
    d.rounded_rectangle((60, by, 250, by + 76), radius=38, outline=(150, 150, 150), width=3)
    R.draw_text(img, 100, by + 16, "Follow", 36, (255, 255, 255), wght=600)
    for i in range(3):
        d.ellipse((300 + i * 22, by + 33, 312 + i * 22, by + 45), fill=(180, 180, 180))
    cx, cy, r = W - 130, by + 38, 70
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255))
    d.polygon([(cx - 20, cy - 30), (cx - 20, cy + 30), (cx + 32, cy)], fill=(18, 18, 18))
    # Popular
    py = by + 170
    R.draw_text(img, 60, py, "Popular", 56, (255, 255, 255), wght=800)
    y = py + 110
    for i, (title, plays) in enumerate(songs):
        if y + 130 > height - 40:
            break
        R.draw_text(img, 66, y + 34, str(i + 1), 40, (170, 170, 170), wght=500)
        img.paste(_cover(120, rng), (130, y))
        R.draw_text(img, 290, y + 14, title, 44, (255, 255, 255), wght=500)
        R.draw_text(img, 290, y + 72, f"{plays}", 36, (170, 170, 170), wght=400)
        for k in range(3):
            d.ellipse((W - 90, y + 40 + k * 18, W - 80, y + 50 + k * 18), fill=(170, 170, 170))
        y += 160
    return img


def songs_for(seed: int) -> list[tuple[str, int]]:
    rng = random.Random(seed)
    titles = rng.sample(SONGS, 6)
    plays = sorted(rng.sample(range(3, 41), 6), reverse=True)
    return list(zip(titles, plays))


if __name__ == "__main__":
    render("Ryan Cole", 11, songs_for(1)).save(ROOT / "output" / "_work" / "artist_stats_demo.png")
