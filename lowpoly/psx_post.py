"""PS1 post for rendered frames (docs/PS1_LOOK.md): RGB555 + PSX 4x4 ordered dither at the internal
resolution, then nearest-neighbour upscale to 1080x1920.
  python lowpoly/psx_post.py IN_DIR OUT_DIR [--scale 4] [--no-dither]
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

D = np.array([[-4, 0, -3, 1], [2, -2, 3, -1], [-3, 1, -4, 0], [3, -1, 2, -2]], np.int16)


def psx(img: np.ndarray, dither=True) -> np.ndarray:
    h, w, _ = img.shape
    c = img.astype(np.int16)
    if dither:
        c = c + np.tile(D, (h // 4 + 1, w // 4 + 1))[:h, :w, None]
    c = np.clip(c, 0, 255) >> 3
    return ((c << 3) | (c >> 2)).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--w", type=int, default=1080)
    ap.add_argument("--h", type=int, default=1920)
    ap.add_argument("--no-dither", action="store_true")
    a = ap.parse_args()
    src, dst = Path(a.src), Path(a.dst)
    dst.mkdir(parents=True, exist_ok=True)

    def one(p):
        im = np.asarray(Image.open(p).convert("RGB"))
        out = Image.fromarray(psx(im, not a.no_dither)).resize((a.w, a.h), Image.NEAREST)
        out.save(dst / p.name)

    fs = sorted(src.glob("*.png"))
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(one, fs))
    print("psx post", len(fs), "->", dst)


if __name__ == "__main__":
    main()
