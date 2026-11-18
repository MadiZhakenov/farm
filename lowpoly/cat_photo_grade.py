"""Re-colour prepared cat photos toward the ref cat (light sandy tabby, soft stripes).
  python lowpoly/cat_photo_grade.py IN_DIR OUT_DIR
Lab statistics transfer: body photos (side/top/front) get mean + contrast of the target fur;
face photos only get a softer version (keeps white muzzle and dark pupils readable).
TARGET was measured once on ref close-up fur (numbers only, no ref pixels are used).
"""
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

# OpenCV 8-bit Lab: L 0..255, a/b centred on 128
TARGET_MU = np.array([124.0, 131.0, 141.5], np.float32)
TARGET_SD = np.array([15.0, 1.3, 3.4], np.float32)
BODY_RECT = {"side": (0.30, 0.20, 0.68, 0.58)}          # fur-only area (fractions) used for the source stats


def stats(lab, rect=None):
    h, w, _ = lab.shape
    if rect:
        x0, y0, x1, y1 = rect
        lab = lab[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    px = lab.reshape(-1, 3)
    return px.mean(0), px.std(0) + 1e-6


def transfer(img, mu_s, sd_s, mu_t, sd_t, k_sd=1.0):
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    scale = 1.0 + (sd_t / sd_s - 1.0) * k_sd
    out = (lab - mu_s) * scale + mu_t
    return cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    dst.mkdir(parents=True, exist_ok=True)
    side = cv2.imread(str(src / "side.png"))
    mu_s, sd_s = stats(cv2.cvtColor(side, cv2.COLOR_BGR2LAB).astype(np.float32), BODY_RECT["side"])
    print("source fur", mu_s.round(1), sd_s.round(2))
    for p in sorted(src.glob("*.png")):
        img = cv2.imread(str(p))
        if p.stem.startswith("face"):
            # same colour shift, half the contrast squeeze, lifted a bit less
            mu_f, sd_f = stats(cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32), (0.1, 0.05, 0.9, 0.35))
            mu_t = mu_f + (TARGET_MU - mu_s) * np.array([0.8, 1.2, 1.25], np.float32)
            out = transfer(img, mu_f, sd_f, mu_t, np.maximum(TARGET_SD, sd_s * 0.6), k_sd=0.5)
        else:
            out = transfer(img, mu_s, sd_s, TARGET_MU, TARGET_SD)
        cv2.imwrite(str(dst / p.name), out)
        print(p.name, "->", dst / p.name)
    for extra in src.glob("*.json"):
        shutil.copy(extra, dst / extra.name)


if __name__ == "__main__":
    main()
