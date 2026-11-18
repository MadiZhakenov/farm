#!/usr/bin/env python3
"""
1388 (Drops) слайд 3: фото экрана компьютера из Flow → на экран ставим НАСТОЯЩИЙ скрин drops.game.
Flow держит крупные «DROP A SONG.» / «get a playable game.», но мелкий текст портит («Get starnd», «Upload a cong»),
поэтому содержимое экрана заменяется скрином с той же перспективой; блики окна и оттенок жёлтого берутся с фото.

Углы области содержимого экрана (TL, TR, BR, BL) в пикселях исходного фото — SCREENS; скрин под пропорции экрана.
Результат 2× от исходника → output/1388d_slides/s3_photo/<имя>.jpg

  python make_1388d_s3_screens.py
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "downloads" / "1388d" / "zip65"
SHOT = ROOT / "downloads" / "1388d"
OUT = ROOT / "output" / "1388d_slides" / "s3_photo"
UP = 2

SCREENS = {   # фото → (углы TL, TR, BR, BL; скрин сайта)
    "Computer_screen_on_desk_dc3c251f": ([(182.5, 575.5), (677.0, 577.4), (680.5, 860.0), (178.5, 865.0)],
                                         "screen_drops_169.png", "imac_01"),
    "Laptop_showing_website_on_desk_914657d6": ([(230.0, 584.0), (683.0, 584.0), (690.5, 872.0), (223.0, 872.0)],
                                                "screen_drops_1610.png", "macbook_01"),
}


def yellow_mask(rgb: np.ndarray) -> np.ndarray:
    r, g, b = (rgb[..., k].astype(np.int16) for k in range(3))
    return (r > 170) & (g > 140) & (b < 130) & (r - b > 80)


def smooth_fill(values: np.ndarray, mask: np.ndarray, sigma: float) -> np.ndarray:
    """Нормированная свёртка: гладкая карта по точкам mask, дыры (буквы, кнопки) заполняются соседями."""
    v = cv2.GaussianBlur(np.where(mask, values, 0).astype(np.float32), (0, 0), sigma)
    w = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), sigma)
    return v / np.maximum(w, 1e-3)


def compose(stem: str, quad, shot_name: str, out_name: str) -> Path:
    photo = Image.open(SRC / f"{stem}.jpg").convert("RGB")
    W, H = photo.width * UP, photo.height * UP
    base = np.asarray(photo.resize((W, H), Image.Resampling.LANCZOS)).astype(np.float32)
    dst = np.float32(quad) * UP
    qw = int(max(np.linalg.norm(dst[1] - dst[0]), np.linalg.norm(dst[2] - dst[3])))
    shot = Image.open(SHOT / shot_name).convert("RGB")
    shot = shot.resize((int(qw * 1.25), int(qw * 1.25 * shot.height / shot.width)), Image.Resampling.LANCZOS)
    s = np.asarray(shot).astype(np.float32)
    src = np.float32([(0, 0), (s.shape[1], 0), (s.shape[1], s.shape[0]), (0, s.shape[0])])
    M = cv2.getPerspectiveTransform(src, dst)
    warp = cv2.warpPerspective(s, M, (W, H), flags=cv2.INTER_LINEAR)
    poly = np.zeros((H, W), np.uint8)
    cv2.fillPoly(poly, [np.round(dst).astype(np.int32)], 255)
    inside = poly > 0

    # блики/виньетка экрана с фото: яркость жёлтого фона Flow относительно медианы → гладкая карта усиления
    ym_f = yellow_mask(base) & inside
    lum_f = base.mean(2)
    ref_f = np.median(lum_f[ym_f])
    gain = smooth_fill(lum_f / ref_f, ym_f, 14 * UP)
    gain = np.clip(gain, 0.85, 1.18)
    # оттенок: жёлтый скрина → жёлтый с фото (по каналам)
    ym_s = yellow_mask(warp) & inside
    tint = np.clip(np.median(base[ym_f], 0) / np.maximum(np.median(warp[ym_s], 0), 1), 0.92, 1.08)
    scr = warp * tint[None, None, :]
    grey = scr.mean(2, keepdims=True)
    scr = grey + (scr - grey) * 0.9                                  # снятый на телефон экран чуть менее насыщен
    scr = (scr * 0.93 + 14) * gain[..., None]                        # чёрный экрана не 0: приподнять тени
    scr = np.clip(scr, 0, 255)
    scr = cv2.GaussianBlur(scr, (0, 0), 0.55 * UP / 2)                 # мягкость камеры телефона
    rng = np.random.default_rng(1388)
    scr = np.clip(scr + rng.normal(0, 2.2, scr.shape[:2])[..., None], 0, 255)   # зерно как на фото

    a = cv2.GaussianBlur(poly.astype(np.float32) / 255, (0, 0), 0.6 * UP)[..., None]
    out = base * (1 - a) + scr * a
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{out_name}.jpg"
    Image.fromarray(out.astype(np.uint8)).save(p, quality=95)
    return p


def main() -> int:
    for stem, (quad, shot, name) in SCREENS.items():
        print(compose(stem, quad, shot, name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
