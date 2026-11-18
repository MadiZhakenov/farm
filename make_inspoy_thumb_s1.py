#!/usr/bin/env python3
"""Inspoy ID 1, слайд 1: на белый экран телефона (кадр Flow) кладём ту же палитру, что на слайде «spring?», как будто это
открытая карусель. Маска непрерывная (яркость + нейтральность цвета): край экрана и палец остаются сглаженными, как на фото.
Экран подсвечен светом кадра: снятый чёрный подъём, лёгкая десатурация, блик от окна, тень пальца, шум.
  python make_inspoy_thumb_s1.py     # downloads/inspoy_thumb/flow2/s1_palette.jpg"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_inspoy_thumb as T  # noqa: E402

D = ROOT / "downloads" / "inspoy_thumb" / "flow2"
SRC = D / "Person_holding_glowing_phone_on_38543c82.jpg"
OUT = D / "s1_palette.jpg"
SW, SH = 1170, 2532
SEASON, SEED = "spring", 7128


def smoothstep(x: np.ndarray, a: float, b: float) -> np.ndarray:
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def screen_region(a: np.ndarray) -> np.ndarray:
    """Грубая область экрана: нужна только чтобы отсечь другие светлые места кадра и найти 4 угла."""
    m = ((a.min(2) > 188) & (np.ptp(a, 2) < 34)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    k = max(range(1, n), key=lambda i: st[i, 4] if st[i, 3] > st[i, 2] * 1.25 else 0)
    return (lab == k).astype(np.uint8) * 255


def slide_artwork() -> np.ndarray:
    """Палитра в масштабе настоящего слайда, вырезанная под пропорцию экрана: складки те же, что на слайде 2."""
    T.CY = 750                                                       # круг чуть ниже — большой палец прямо на нём
    colors = T.SEASONS[SEASON][1][:]
    random.Random(SEED).shuffle(colors)
    wheel = T.wheel(colors, SEED)
    T.paper_circle(wheel, SEED)
    cw = round(T.H * SW / SH)
    x0 = round(T.CX - 0.474 * cw)
    im = wheel.convert("RGB").crop((x0, 0, x0 + cw, T.H)).resize((SW, SH), Image.Resampling.LANCZOS)
    return np.asarray(im).astype(np.float32)


def main() -> int:
    a = np.asarray(Image.open(SRC).convert("RGB")).astype(np.float32)
    h, w = a.shape[:2]
    comp = screen_region(a.astype(np.int32))
    cnt = max(cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)
    pts = cnt.reshape(-1, 2).astype(np.float32)
    s, d = pts.sum(1), pts[:, 0] - pts[:, 1]
    quad = np.float32([pts[s.argmin()], pts[d.argmax()], pts[s.argmax()], pts[d.argmin()]])   # TL TR BR BL
    c = quad.mean(0)
    quad = c + (quad - c) * 1.03
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [SW, 0], [SW, SH], [0, SH]]), quad)

    art = slide_artwork()
    grey = art.mean(2, keepdims=True)
    art = grey + (art - grey) * 0.9                                  # камера снимает экран чуть менее сочным
    art = 16 + art * 0.9
    warp = cv2.warpPerspective(art, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)

    # непрерывная маска: белое и нейтральное = экран; кожа тёплая, рамка тёмная. Край остаётся сглаженным, как снято
    chroma = a[..., 0] - a[..., 2]
    alpha = smoothstep(a.min(2), 120, 205) * (1 - smoothstep(chroma, 16, 40))
    area = cv2.dilate(cv2.morphologyEx(comp, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8)), np.ones((7, 7), np.uint8))
    area = cv2.GaussianBlur(area, (5, 5), 0).astype(np.float32) / 255
    alpha = np.clip(cv2.GaussianBlur(alpha, (3, 3), 0.7) * area, 0, 1)
    hole = (cv2.morphologyEx((alpha > 0.5).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)) > 0)
    alpha = np.where(hole & (alpha > 0.2), np.maximum(alpha, 0.98), alpha)   # точка посреди белого экрана

    # свет кадра на экране
    shade = cv2.GaussianBlur(a.mean(2), (0, 0), 9) / 232.0
    glare_u = np.linspace(1, 0, SW)[None, :] * np.linspace(1, 0, SH)[:, None]
    glare = cv2.warpPerspective(glare_u.astype(np.float32), M, (w, h), flags=cv2.INTER_LINEAR)
    lit = warp * np.clip(shade, 0.85, 1.08)[..., None] + (glare[..., None] ** 1.5) * 16

    # мягкая тень пальца на экране
    thumb = 1 - alpha
    inside = cv2.erode((area > 0.9).astype(np.uint8), np.ones((31, 31), np.uint8)).astype(np.float32)
    shadow = cv2.GaussianBlur(np.roll(thumb * inside, (8, -6), axis=(0, 1)), (0, 0), 9)
    lit = lit * (1 - 0.34 * np.clip(shadow, 0, 1))[..., None]

    lit = cv2.GaussianBlur(lit, (0, 0), 0.8)                         # резкость как у остального снимка
    rng = np.random.default_rng(SEED)
    lit += rng.normal(0, 2.2, lit.shape).astype(np.float32)
    out = a * (1 - alpha[..., None]) + lit * alpha[..., None]
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(OUT, quality=95)
    print("готово:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
