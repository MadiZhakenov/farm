#!/usr/bin/env python3
"""1340 v2: раскладывает серийные кадры Flow (downloads/1340/gen_v2_burst1) по слотам в output/1340_v2/pool и считает сдвиг каждого
кадра относительно основного (ORB + аффинное преобразование), чтобы плашки и кроп 3:4 ехали вместе с кадром → pool.json.
  python make_1340_v2_pools.py"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "output" / "1340_v2"
POOL = BASE / "pool"
BURST = sorted(p for p in (ROOT / "downloads" / "1340" / "gen_v2_burst1").iterdir() if p.suffix.lower() == ".jpg")
SCALE = 1080 / 768
SLOTS = {  # слот: (основной кадр, номера серийных кадров в сортированном списке — разобраны по листу)
    "covers/g1_red": ("covers/g1_red.jpg", [15, 18, 21]),
    "covers/g2_leather": ("covers/g2_leather.jpg", [8, 11, 20]),
    "covers/g3_burgundy": ("covers/g3_burgundy.jpg", [1, 13, 29]),
    "last/g1_red": ("last/g1_red.jpg", [5, 6, 17]),
    "last/g2_leather": ("last/g2_leather.jpg", [24, 26, 27]),
    "last/g3_burgundy": ("last/g3_burgundy.jpg", [19, 28, 32]),
    "looks/l1_coat": ("looks/l1_coat.jpg", [0, 2, 22]),
    "looks/l2_leather": ("looks/l2_leather.jpg", [12, 14, 31]),
    "looks/l3_dress": ("looks/l3_dress.jpg", [3, 10, 30]),
    "looks/l4_green": ("looks/l4_green.jpg", [4, 7, 23]),
    "looks/l5_pink": ("looks/l5_pink.jpg", [9, 16, 25]),
}


def xform(a: Path, b: Path) -> dict:
    """Где точка основного кадра оказывается на серийном: b = s * a + d (в координатах кадра шириной 1080)."""
    ia, ib = cv2.imread(str(a), 0), cv2.imread(str(b), 0)
    orb = cv2.ORB_create(5000)
    ka, da = orb.detectAndCompute(ia, None)
    kb, db = orb.detectAndCompute(ib, None)
    good = [m for m, n in cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2) if m.distance < 0.75 * n.distance]
    pa = np.float32([ka[m.queryIdx].pt for m in good])
    pb = np.float32([kb[m.trainIdx].pt for m in good])
    M, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=4.0)
    s = float(np.hypot(M[0, 0], M[1, 0]))
    return {"s": round(s, 4), "dx": round(float(M[0, 2]) * SCALE, 1), "dy": round(float(M[1, 2]) * SCALE, 1), "inliers": int(inl.sum()), "matches": len(good)}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(BURST) != 33:
        raise SystemExit(f"ожидалось 33 кадра, найдено {len(BURST)}")
    out = {}
    for slot, (base, idx) in SLOTS.items():
        (POOL / slot).parent.mkdir(parents=True, exist_ok=True)
        v0 = POOL / f"{slot}_v0.jpg"
        shutil.copy2(BASE / base, v0)
        out[f"{slot}_v0.jpg"] = {"s": 1.0, "dx": 0.0, "dy": 0.0, "inliers": 0, "matches": 0}
        for n, k in enumerate(idx, 1):
            dst = POOL / f"{slot}_v{n}.jpg"
            shutil.copy2(BURST[k], dst)
            t = xform(BASE / base, dst)
            out[f"{slot}_v{n}.jpg"] = t
            print(f"{slot}_v{n}: {t}", flush=True)
    (POOL / "pool.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("готово:", len(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
