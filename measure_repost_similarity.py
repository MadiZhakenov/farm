#!/usr/bin/env python3
"""
Насколько ролик-переделка похож на оригинал (docs/REPOST_HYPOTHESES.md).

Картинка: каждый кадр ролика (2 к/с) сравнивается со ВСЕМИ кадрами оригинала (10 к/с, тот же кроп 9:16):
  - pHash (DCT 8×8 из 32×32) — ближайший кадр оригинала, расстояние Хэмминга из 64 бит;
    «узнаваемый» кадр — расстояние ≤ 12 (порог дубликата у типовых систем — около 10–14);
  - SSIM (270×480, серый) с этим ближайшим кадром.
Своё в кадре: доля пикселей, отличающихся от ближайшего кадра оригинала больше чем на 40/255 (текст, карточки).
Выход — таблица и CSV в output/_work/xmas_r3/similarity.csv.

  python measure_repost_similarity.py
"""

from __future__ import annotations

import csv
import glob
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim

ROOT = Path(__file__).resolve().parent
SW, SH = 270, 480


def frames(path: Path, fps: float) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                          f"fps={fps},scale={SW}:{SH}:force_original_aspect_ratio=increase,crop={SW}:{SH}",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, SH, SW)


def phash(g: np.ndarray) -> np.ndarray:
    d = cv2.dct(cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32))[:8, :8]
    return (d > np.median(d)).flatten()


def compare(video: Path, orig: Path) -> dict:
    A, O = frames(video, 2), frames(orig, 10)
    oh = np.array([phash(f) for f in O])
    dist, sims, own = [], [], []
    for f in A:
        h = phash(f)
        dd = (oh != h).sum(1)
        k = int(dd.argmin())
        dist.append(int(dd[k]))
        sims.append(ssim(f, O[k], data_range=255))
        own.append(float((np.abs(f.astype(int) - O[k].astype(int)) > 40).mean()))
    dist = np.array(dist)
    return dict(frames=len(A), recog=float((dist <= 12).mean()), ham=float(dist.mean()), ssim=float(np.mean(sims)),
                own_px=float(np.mean(own)))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    src = ROOT / "downloads" / "xmas_proj" / "src"
    origs = {"v1": src / "DcNWKlfAbOo.mp4", "v2": src / "DdGwGMEx-Uj.mp4", "v3": src / "DdZ5O2bR39c.mp4"}
    rows = []
    for hyp in ("R3-3d_vo_original", "R3-6_reply", "R3-7_vo_heart", "R3-8_vo_review"):
        for k, o in origs.items():
            f = next(Path(p) for p in glob.glob(str(ROOT / "output" / "xmas_r3" / hyp / f"*_{k}_noid.mp4")))
            rows.append(dict(group=hyp, video=k, **compare(f, o)))
    # эталон: копии TikFusion из теста 1346 (0 просмотров) против своего исходника (plate)
    plate = ROOT / "output" / "1346" / "plate"
    names = ["Christmas Coloring Blanket with Markers", "Glowing Halloween Fog Cauldrons", "GTA Money Stack Lamp",
             "Light-Up Christmas Heel Boots", "Water Jug Cabinet Dispenser"]
    for folder in ("h01_strong", "h12_all", "h14_zoom_120", "h15_crop_15"):
        for i, nm in enumerate(names):
            f = ROOT / "output" / "1346_tf" / folder / f"{folder}_{2 * i + 1:02d}_1346.mp4"
            if f.exists():
                rows.append(dict(group="TF_" + folder, video=nm.split()[0], **compare(f, plate / f"{nm}.mp4")))
    out = ROOT / "output" / "_work" / "xmas_r3" / "similarity.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    groups = {}
    for r in rows:
        groups.setdefault(r["group"], []).append(r)
    for g, rs in groups.items():
        m = lambda key: np.mean([r[key] for r in rs])  # noqa: E731
        print(f"{g:22s} n={len(rs)}  узнаваемых кадров {m('recog') * 100:5.1f}%  pHash {m('ham'):4.1f}/64  "
              f"SSIM {m('ssim'):.2f}  своих пикселей {m('own_px') * 100:4.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
