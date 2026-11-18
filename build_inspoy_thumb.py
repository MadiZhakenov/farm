#!/usr/bin/env python3
"""
Inspoy, ID 1 — «place your thumb on each palette and swipe»: слайды 2–5 (3:4) = образцы ткани стилиста колесом вокруг
нейтрального круга под большой палец. Цвета — кодом (точные: Flow искажает оттенки), поверх процедурные складки/плетение.
Круг и колесо в одной точке на всех четырёх слайдах: после свайпа палец сразу на месте, меняются только цвета вокруг.

  python build_inspoy_thumb.py --test                      # 2 набора + QA → output/inspoy_thumb_test
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import check_box, draw_overlay  # noqa: E402

W, H = 1080, 1440
CX, CY, R = 540, 700, 172          # центр и радиус круга: ~22 мм на телефоне шириной 70 мм, под большой палец
PAPER = (216, 214, 210)
FONT = ROOT / "fonts" / "TikTokSans-Bold.ttf"
SEASONS = {  # подпись дословно из ТЗ; 10 цветов сезона
    "spring": ("spring?", ["#F2725B", "#F9B48F", "#2FB5A6", "#F6C445", "#8CC63F", "#F7EBCF", "#F58F7C", "#66CDBF", "#E84A33", "#D9A066"]),
    "summer": ("summer?", ["#CF9AA7", "#A9C3DC", "#B4A7D1", "#A3B8A8", "#A98298", "#4F5F80", "#E0AEBF", "#7F95B3", "#86688A", "#B4B8C0"]),
    "autumn": ("autumn?", ["#BE8C53", "#B2502A", "#C9981E", "#6E6E2F", "#C66B45", "#5B3A26", "#D67A28", "#7D7C3C", "#2F6C6B", "#E7D3A8"]),
    "winter": ("winter?", ["#C8102E", "#00835A", "#0F4FC2", "#D6127F", "#141417", "#F8F9FB", "#F3C6DC", "#4B1E8C", "#BFE3F5", "#0B4F3F"]),
}


def rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def smooth_noise(rng: np.random.Generator, scale: int) -> np.ndarray:
    n = rng.random((H // scale + 2, W // scale + 2), dtype=np.float32)
    im = Image.fromarray((n * 255).astype(np.uint8)).resize((W, H), Image.Resampling.BICUBIC)
    return np.asarray(im, dtype=np.float32) / 255 - 0.5


def wheel(colors: list[str], seed: int) -> Image.Image:
    """Клинья ткани от центра: каждый ложится на соседний (тень на стыке), мягкие радиальные складки, плетение."""
    gen = np.random.default_rng(seed)
    py = random.Random(seed)
    n = len(colors)
    cols = np.array([rgb(c) for c in colors], dtype=np.float32)
    widths = np.array([py.uniform(0.82, 1.18) for _ in range(n)])
    bounds = np.cumsum(widths / widths.sum() * 2 * np.pi)
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    dx, dy = x - CX, y - CY
    r = np.hypot(dx, dy)
    ang = np.arctan2(dy, dx) + py.uniform(0, 2 * np.pi)
    ang += 0.022 * np.sin(r / 83 + py.uniform(0, 6)) + 0.013 * np.sin(r / 37 + py.uniform(0, 6))   # край неровный, как у ткани
    ang = np.mod(ang, 2 * np.pi)
    idx = np.minimum(np.searchsorted(bounds, ang), n - 1)
    starts = np.concatenate(([0.0], bounds[:-1]))
    rel = ang - starts[idx]
    d0 = rel * r                                                    # пикселей от края клина
    freq, phase = gen.uniform(9, 17, n)[idx], gen.uniform(0, 6.3, n)[idx]
    folds = 0.055 * np.sin(rel * freq * 3 + phase + smooth_noise(gen, 220) * 5)
    soft = 0.05 * smooth_noise(gen, 150)
    edge = -0.30 * np.exp(-d0 / 16)                                  # тень от соседнего клина
    weave = 0.012 * np.sin(x * 1.75) * np.sin(y * 1.75) + 0.012 * (gen.random((H, W), dtype=np.float32) - 0.5)
    shade = 1 + folds + soft + edge + weave
    img = np.clip(cols[idx] * shade[..., None], 0, 255).astype(np.uint8)
    return Image.fromarray(img, "RGB").convert("RGBA")


def paper_circle(im: Image.Image, seed: int) -> None:
    gen = np.random.default_rng(seed + 7)
    s = Image.new("L", (W, H), 0)
    ImageDraw.Draw(s).ellipse((CX - R, CY - R + 8, CX + R, CY + R + 8), fill=135)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh.putalpha(s.filter(ImageFilter.GaussianBlur(16)))
    im.alpha_composite(sh)
    S = 3
    m = Image.new("L", (2 * R * S, 2 * R * S), 0)
    ImageDraw.Draw(m).ellipse((0, 0, 2 * R * S - 1, 2 * R * S - 1), fill=255)
    m = m.resize((2 * R, 2 * R), Image.Resampling.LANCZOS)
    grain = 1 + 0.012 * (gen.random((2 * R, 2 * R), dtype=np.float32) - 0.5)
    arr = np.clip(np.array(PAPER, dtype=np.float32) * grain[..., None], 0, 255).astype(np.uint8)
    disc = Image.fromarray(arr, "RGB").convert("RGBA")
    disc.putalpha(m)
    im.alpha_composite(disc, (CX - R, CY - R))


def label(im: Image.Image, text: str, px: int = 118, cy: int = 262) -> tuple[int, int, int, int]:
    f = ImageFont.truetype(str(FONT), px)
    d = ImageDraw.Draw(im)
    sw = round(px * 0.075)
    d.text((W // 2, cy), text, font=f, fill=(255, 255, 255, 255), anchor="mm", stroke_width=sw, stroke_fill=(0, 0, 0, 255))
    return tuple(int(v) for v in d.textbbox((W // 2, cy), text, font=f, anchor="mm", stroke_width=sw))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("-n", type=int, default=2)
    a = ap.parse_args()
    out = ROOT / "output" / "inspoy_thumb_test"
    out.mkdir(parents=True, exist_ok=True)
    for i in range(1, a.n + 1):
        d = out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        qa = []
        for k, season in enumerate(SEASONS, 2):
            text, base = SEASONS[season]
            seed = 7100 + i * 13 + k
            py = random.Random(seed)
            colors = base[:]
            py.shuffle(colors)
            im = wheel(colors, seed)
            paper_circle(im, seed)
            box = label(im, text)
            bad = check_box(W, H, box)
            if bad:
                raise SystemExit(f"{season}: текст вне безопасной зоны {box} — {bad}")
            rgb_im = im.convert("RGB")
            rgb_im.save(d / f"{k}.jpg", quality=94)
            q = draw_overlay(rgb_im.copy())
            ImageDraw.Draw(q).rectangle(box, outline=(255, 200, 0), width=4)
            qa.append(q.resize((360, 480)))
        sheet = Image.new("RGB", (360 * len(qa), 480))
        for k, q in enumerate(qa):
            sheet.paste(q, (k * 360, 0))
        sheet.save(out / f"_qa_{i:03d}.jpg", quality=86)
        print(f"  {d.name}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
