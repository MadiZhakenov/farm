#!/usr/bin/env python3
"""Похожесть роликов раунда 4 на оригиналы 1346 (метод measure_repost_similarity): обычная и с учётом зеркала
(кадр сравнивается ещё и с отзеркаленным оригиналом).

  python measure_1346_r4.py [--variant A,B]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
from skimage.metrics import structural_similarity as ssim

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1346_r4 as B  # noqa: E402
import measure_repost_similarity as M  # noqa: E402


def compare(video: Path, orig: Path) -> dict:
    A, O = M.frames(video, 2), M.frames(orig, 10)
    F = O[:, :, ::-1]
    oh, fh = np.array([M.phash(f) for f in O]), np.array([M.phash(f) for f in F])
    d1, d2, sims = [], [], []
    for f in A:
        h = M.phash(f)
        dd = (oh != h).sum(1)
        k = int(dd.argmin())
        d1.append(int(dd[k]))
        d2.append(min(int(dd[k]), int((fh != h).sum(1).min())))
        sims.append(ssim(f, O[k], data_range=255))
    return dict(recog=float((np.array(d1) <= 12).mean()), recog_flip=float((np.array(d2) <= 12).mean()), ssim=float(np.mean(sims)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="A,B")
    ap.add_argument("--out", type=Path, default=B.OUT)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = []
    variants = a.variant.split(",")
    for var in variants:
        tag = "_B" if var == "B" else ""
        for hyp, folder in B.FOLDER.items():
            for v, cfg in B.VIDEOS.items():
                f = a.out / f"{folder}{tag}" / f"{hyp}_{v}_{cfg['slug']}{tag}_noid.mp4"
                if f.exists():
                    rows.append(dict(var=var, hyp=hyp, video=v, **compare(f, B.SRC / cfg["src"])))
    work = ROOT / "output" / "_work" / "1346_r4"
    work.mkdir(parents=True, exist_ok=True)
    with open(work / "similarity.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for var in variants:
        for hyp in B.FOLDER:
            rs = [r for r in rows if r["var"] == var and r["hyp"] == hyp]
            if rs:
                print(f"{var} {hyp:6s} n={len(rs)}  узнаваемых {np.mean([r['recog'] for r in rs]) * 100:5.1f}%  "
                      f"с учётом зеркала {np.mean([r['recog_flip'] for r in rs]) * 100:5.1f}%  SSIM {np.mean([r['ssim'] for r in rs]):.2f}")
    for v in B.VIDEOS:
        parts = []
        for var in variants:
            rs = [r["recog_flip"] for r in rows if r["var"] == var and r["video"] == v]
            if rs:
                parts.append(f"{var}: {np.mean(rs) * 100:.0f}%")
        print(v, "с учётом зеркала —", ", ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
