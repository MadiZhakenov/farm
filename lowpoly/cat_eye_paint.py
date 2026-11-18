"""Repaint the two eye icons of the Bicolor-layout atlas: wide 'staring' eyes like the ref cat.
  python lowpoly/cat_eye_paint.py ATLAS_IN ATLAS_OUT [--iris r,g,b] [--pupil 0.62]
Finds the white icon squares in the left column of the atlas and paints into each one an amber iris
with a dark rim, a big round pupil and a catch-light (the eyeball geometry samples exactly these squares).
"""
import argparse

import numpy as np
from PIL import Image


# eye icon squares of the Bicolor atlas layout, as fractions of the atlas size (measured on the 2048 original)
ICONS = [(40 / 2048, 227 / 2048, 138 / 2048, 325 / 2048), (40 / 2048, 748 / 2048, 138 / 2048, 846 / 2048)]


def find_icons(a):
    h, w, _ = a.shape
    return [(round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)) for x0, y0, x1, y1 in ICONS]


def paint_eye(size, iris, pupil_k, seed=0):
    s = size
    yy, xx = (np.mgrid[0:s, 0:s] + 0.5) / s * 2 - 1
    r = np.sqrt(xx ** 2 + yy ** 2)
    ang = np.arctan2(yy, xx)
    rng = np.random.default_rng(seed)
    streak = np.interp(ang, np.linspace(-np.pi, np.pi, 90), rng.normal(0, 1, 90))
    iris = np.array(iris, float)
    base = iris[None, None, :] * (1.15 - 0.45 * r[..., None]) * (1 + 0.08 * streak[..., None])
    rim = np.clip((r - 0.86) / 0.12, 0, 1)[..., None] * 0.8
    col = base * (1 - rim) + np.array([30, 20, 10])[None, None, :] * rim
    pupil = np.clip((pupil_k - r) / 0.04, 0, 1)[..., None]
    col = col * (1 - pupil) + np.array([8, 6, 5])[None, None, :] * pupil
    hl = np.clip((0.15 - np.sqrt((xx + 0.30) ** 2 + (yy + 0.32) ** 2)) / 0.03, 0, 1)[..., None]
    col = col * (1 - hl) + 250 * hl
    return np.clip(col, 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--iris", default="178,152,72")
    ap.add_argument("--pupil", type=float, default=0.48)
    a = ap.parse_args()
    im = np.asarray(Image.open(a.src).convert("RGB")).copy()
    boxes = find_icons(im)
    print("eye icons", boxes)
    iris = [float(v) for v in a.iris.split(",")]
    for k, (x0, y0, x1, y1) in enumerate(boxes):
        s = max(x1 - x0, y1 - y0) + 1
        eye = paint_eye(s, iris, a.pupil, seed=k)
        im[y0:y0 + s, x0:x0 + s] = eye[: im.shape[0] - y0, : im.shape[1] - x0]
    Image.fromarray(im).save(a.dst)
    print("saved", a.dst)


if __name__ == "__main__":
    main()
