#!/usr/bin/env python3
"""
1321 v3 — формат 1321 («my grandma had 7 husbands»), 300 вариантов: s1/s2/s6 — одобренные кадры 1321,
s3–s5 «Husband #1 / #4 / #7 look» — по 5 раскладок на кровати, сведённых во Flow в один вайб (downloads/1321/zip67, отбор по популярности
и живости, без человека), разложены по трём слайдам. Вёрстка, тексты, безопасная рамка — build_1321_carousels.

  python build_1321v3_carousels.py --no-plate --qa -n 300 --out output/carousels_1321v3 --flat output/1321v3_300 --flat-id 1321
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1321_carousels as B  # noqa: E402

SL = ROOT / "output" / "1321v3_slides"
B.SLIDES = [(SL / d.name, *rest) for d, *rest in B.SLIDES]

if __name__ == "__main__":
    raise SystemExit(B.main())
