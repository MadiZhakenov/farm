#!/usr/bin/env python3
"""
1322: из одной сгенерённой руки (кулак, внутренняя сторона запястья) — три руки для слайда «What's your Undertone?»:
вырезаем руку с фона (PNG с альфой), обрезаем снизу над манжетой свитера и перекрашиваем вены
A — зеленоватые (warm), B — сине-зелёные (neutral), C — сине-фиолетовые (cool). Вены чуть темнее, чтобы читались.

  python make_1322_wrists.py downloads/1322/wrist/flow_fist.jpg output/1322_pick/002
  python make_1322_wrists.py - output/1322_pick/002 --plain warm.jpg neutral.jpg cool.jpg   # руки уже из Flow
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# цвет вен в Lab (a, b) и насколько темнее кожи (ΔL)
VEINS = {"a": (-12, 26, 20), "b": (-16, -16, 20), "c": (20, -30, 20)}


def arm_mask(rgb: np.ndarray) -> np.ndarray:
    """Рука = тёплое/насыщенное относительно серо-сиреневой стены; одна самая большая область, без дыр."""
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    h, w = rgb.shape[:2]
    edge = np.concatenate([lab[:, :25].reshape(-1, 3), lab[:, -25:].reshape(-1, 3)])
    bg = np.median(edge, axis=0)
    d = np.sqrt(((lab[..., 1:] - bg[1:]) ** 2).sum(-1)) + 0.35 * np.abs(lab[..., 0] - bg[0])
    m = (d > 14).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab_, st, _ = cv2.connectedComponentsWithStats(m, 8)
    big = 1 + int(np.argmax(st[1:, 4]))
    m = (lab_ == big).astype(np.uint8)
    ff = m.copy()
    cv2.floodFill(ff, None, (0, 0), 1)
    m = m | (1 - ff)                                  # заливка дыр
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    m = cv2.erode(m, np.ones((3, 3), np.uint8))
    return cv2.GaussianBlur(m.astype(np.float32), (0, 0), 1.2)


def vein_mask(rgb: np.ndarray, arm: np.ndarray) -> np.ndarray:
    """Вены = тонкие места темнее и синее окружающей кожи (на запястье и предплечье)."""
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    base = cv2.GaussianBlur(lab, (0, 0), 9)
    dl = base[..., 0] - lab[..., 0]                   # темнее
    db = base[..., 2] - lab[..., 2]                   # синее (меньше b)
    v = np.clip(dl / 10, 0, 1) * np.clip(db / 6, 0, 1)
    v = cv2.GaussianBlur(v, (0, 0), 1.5)
    inner = cv2.erode((arm > 0.5).astype(np.uint8), np.ones((25, 41), np.uint8)).astype(np.float32)
    ys = np.where(arm.max(axis=1) > 0.5)[0]
    top, bot = ys.min(), ys.max()
    rows = np.zeros(arm.shape[0], np.float32)          # только запястье и предплечье: ниже ладони
    rows[int(top + 0.47 * (bot - top)):int(top + 0.92 * (bot - top))] = 1
    rows = cv2.GaussianBlur(rows.reshape(-1, 1), (1, 0), sigmaX=0, sigmaY=12).ravel()
    return np.clip(v * 1.6, 0, 1) * inner * rows[:, None]


def recolor(rgb: np.ndarray, vm: np.ndarray, a: float, b: float, dl: float) -> np.ndarray:
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    base = cv2.GaussianBlur(lab, (0, 0), 9)
    tgt = lab.copy()
    tgt[..., 0] = np.minimum(lab[..., 0], base[..., 0] - dl)
    tgt[..., 1] = 128 + a
    tgt[..., 2] = 128 + b
    out = lab + (tgt - lab) * vm[..., None]
    return cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--plain", type=Path, nargs=3, metavar=("WARM", "NEUTRAL", "COOL"),
                    help="три готовые руки из Flow (кожа и вены уже свои) — только вырезать, без перекраски")
    ap.add_argument("--cut", type=float, default=0.835, help="низ кадра (доля высоты) — над манжетой свитера")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args.out.mkdir(parents=True, exist_ok=True)
    if args.plain:
        for slot, src in zip("abc", args.plain):
            rgb = np.asarray(Image.open(src).convert("RGB"))
            rgb = rgb[: round(rgb.shape[0] * args.cut)]
            arm = arm_mask(rgb)
            ys, xs = np.where(arm > 0.5)
            im = Image.fromarray(rgb).convert("RGBA")
            im.putalpha(Image.fromarray((arm * 255).astype(np.uint8)))
            im.crop((xs.min() - 4, ys.min() - 4, xs.max() + 5, rgb.shape[0])).save(args.out / f"wrist_{slot}.png")
        print("готово (без перекраски) →", args.out)
        return 0
    rgb = np.asarray(Image.open(args.src).convert("RGB"))
    rgb = rgb[: round(rgb.shape[0] * args.cut)]
    arm = arm_mask(rgb)
    vm = vein_mask(rgb, arm)
    ys, xs = np.where(arm > 0.5)
    box = (xs.min() - 4, ys.min() - 4, xs.max() + 5, rgb.shape[0])
    args.out.mkdir(parents=True, exist_ok=True)
    for slot, (a, b, dl) in VEINS.items():
        im = Image.fromarray(recolor(rgb, vm, a, b, dl)).convert("RGBA")
        im.putalpha(Image.fromarray((arm * 255).astype(np.uint8)))
        im.crop(box).save(args.out / f"wrist_{slot}.png")
    Image.fromarray((vm * 255).astype(np.uint8)).crop(box).save(args.out / "_veins_mask.png")
    print("готово:", ", ".join(f"wrist_{s}.png" for s in VEINS), "→", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
