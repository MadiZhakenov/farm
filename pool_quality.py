#!/usr/bin/env python3
"""
Отсев мыльных и пиксельных кадров из пула (harvest_carousel_pool.py): кадр в пуле — уже кроп 3:4 до 1080×1440,
поэтому смотрим, из какого исходника он сделан (manifest.json → source_px) и насколько он резкий.

  пиксельный — ширина кропа 3:4 в исходнике меньше --min-src (сильный апскейл до 1080);
  мыльный    — дисперсия Лапласиана на 540×720 меньше --min-sharp (мало деталей / не в фокусе / шум размыт).

Непрошедшие уходят в <pool>/_lowq (ничего не удаляется).

  python pool_quality.py output/_work/1385/pool/pa_s1 output/_work/1385/pool/pa_s3 --min-src 900 --min-sharp 180
  python pool_quality.py output/_work/1385/pool/pa_s2 --min-src 900 --min-sharp 90 --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np


def metrics(path: Path, src: tuple[int, int] | None) -> tuple[int, float]:
    g = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_GRAYSCALE)
    sharp = float(cv2.Laplacian(cv2.resize(g, (540, 720), interpolation=cv2.INTER_AREA), cv2.CV_64F).var())
    sw, sh = src if src else g.shape[::-1]
    return int(min(sw, sh * 3 / 4)), sharp


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("pools", type=Path, nargs="+")
    ap.add_argument("--min-src", type=int, default=900, help="мин. ширина кропа 3:4 в исходнике, px")
    ap.add_argument("--min-sharp", type=float, default=180, help="мин. дисперсия Лапласиана на 540×720")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for d in args.pools:
        man = {}
        if (d / "manifest.json").exists():
            man = {r["file"]: r.get("source_px") for r in json.loads((d / "manifest.json").read_text(encoding="utf-8"))}
        keep, bad = [], []
        for f in sorted(p for p in d.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
                        and not p.name.startswith("_")):
            src, sharp = metrics(f, man.get(f.name))
            why = (["пиксели"] if src < args.min_src else []) + (["мыло"] if sharp < args.min_sharp else [])
            (bad if why else keep).append((f, src, sharp, why))
        for f, src, sharp, why in bad:
            print(f"  {d.name}/{f.name[:3]}: {'+'.join(why)} (src {src}, sharp {sharp:.0f})")
            if not args.dry_run:
                (d / "_lowq").mkdir(exist_ok=True)
                shutil.move(str(f), str(d / "_lowq" / f.name))
        print(f"{d.name}: осталось {len(keep)}, убрано {len(bad)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
