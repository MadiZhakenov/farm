"""Prepare cat reference photos (from Google Flow) for projection onto the low-poly cat.
  python lowpoly/cat_photo_prep.py IN_DIR OUT_DIR
IN_DIR holds side.png / top.png / front.png / face*.png (any of jpg/png/webp). For every view:
  - find the cat by separating it from the plain light background,
  - crop tightly to the cat,
  - bleed fur colour into the background pixels (so silhouette mismatch never shows grey),
  - downscale to PS2-ish resolution (side/top 512 wide, front/face 256).
Writes OUT_DIR/<view>.png and OUT_DIR/boxes.json (crop box in the source, for reference).
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

SIZES = {"side": 512, "top": 512, "front": 256}


def cat_mask(rgb: np.ndarray) -> np.ndarray:
    """GrabCut (OpenCV) seeded with 'border = background, colour-distant pixels = probably cat';
    falls back to plain border-colour distance when OpenCV is missing."""
    try:
        import cv2
        h, w, _ = rgb.shape
        border = np.concatenate([rgb[:8].reshape(-1, 3), rgb[-8:].reshape(-1, 3), rgb[:, :8].reshape(-1, 3), rgb[:, -8:].reshape(-1, 3)])
        bg = np.median(border, axis=0)
        d = np.sqrt(((rgb - bg) ** 2).sum(-1))
        mask = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
        mask[d > 45] = cv2.GC_PR_FGD
        mask[d > 90] = cv2.GC_FGD
        mask[:6], mask[-6:], mask[:, :6], mask[:, -6:] = cv2.GC_BGD, cv2.GC_BGD, cv2.GC_BGD, cv2.GC_BGD
        bgm, fgm = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        img = np.clip(rgb, 0, 255).astype(np.uint8)[..., ::-1].copy()
        cv2.grabCut(img, mask, None, bgm, fgm, 6, cv2.GC_INIT_WITH_MASK)
        m = (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)) > 0
        n, lab, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8))
        if n > 1:                                   # keep the biggest blob (the cat)
            big = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
            m = lab == big
        return m
    except ImportError:
        pass
    """Foreground = differs from the border colour (plain studio background)."""
    border = np.concatenate([rgb[:8].reshape(-1, 3), rgb[-8:].reshape(-1, 3), rgb[:, :8].reshape(-1, 3), rgb[:, -8:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    d = np.sqrt(((rgb - bg) ** 2).sum(-1))
    m = d > 28
    im = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(7))
    return np.asarray(im) > 127


def bleed(rgb: np.ndarray, mask: np.ndarray, it: int = 0) -> np.ndarray:
    """Fill background with fur colour: erode the mask (drop light edge halo), then push-pull pyramid fill."""
    try:
        import cv2
        mask = cv2.erode(mask.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    except ImportError:
        pass
    levels = []
    img, w = rgb * mask[..., None], mask.astype(np.float32)
    while min(img.shape[:2]) > 2:
        levels.append((img, w))
        h, wd = img.shape[0] // 2 * 2, img.shape[1] // 2 * 2
        img2 = img[:h, :wd].reshape(h // 2, 2, wd // 2, 2, 3).sum((1, 3))
        w2 = w[:h, :wd].reshape(h // 2, 2, wd // 2, 2).sum((1, 3))
        img, w = img2, w2
    col = img.sum((0, 1)) / max(1e-6, w.sum())
    fill = np.ones(img.shape[:2] + (3,), np.float32) * col
    for img, w in reversed(levels):
        up = np.asarray(Image.fromarray(np.clip(fill, 0, 255).astype(np.uint8)).resize((img.shape[1], img.shape[0]), Image.BILINEAR)).astype(np.float32)
        known = w > 0
        avg = np.where(known[..., None], img / np.maximum(w, 1e-6)[..., None], up)
        fill = avg
    out = rgb.copy()
    out[~mask] = fill[~mask]
    return out


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    dst.mkdir(parents=True, exist_ok=True)
    boxes = {}
    for p in sorted(src.iterdir()):
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        view = p.stem.lower()
        im = Image.open(p).convert("RGB")
        rgb = np.asarray(im).astype(np.float32)
        if view.startswith("face"):
            im.resize((256, 256), Image.LANCZOS).save(dst / f"{view}.png")
            continue
        m = cat_mask(rgb)
        ys, xs = np.where(m)
        if len(xs) < 100:
            print("no cat found in", p.name)
            continue
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        boxes[view] = [int(x0), int(y0), int(x1), int(y1)]
        crop = rgb[y0:y1 + 1, x0:x1 + 1]
        cm = m[y0:y1 + 1, x0:x1 + 1]
        filled = bleed(crop, cm)
        out = Image.fromarray(np.clip(filled, 0, 255).astype(np.uint8))
        w = SIZES.get(view.split("_")[0], 512)
        out = out.resize((w, max(8, int(w * out.height / out.width))), Image.LANCZOS)
        out.save(dst / f"{view}.png")
        print(view, "crop", boxes[view], "->", out.size)
    json.dump(boxes, open(dst / "boxes.json", "w"), indent=1)


if __name__ == "__main__":
    main()
