#!/usr/bin/env python3
"""
1321 v2 — формат 1321 («my grandma had 7 husbands»), 100 новых вариантов: s1/s2/s6 — одобренные кадры 1321,
s3–s5 «Husband #1 / #4 / #7 look» — образы-раскладки с Pinterest как есть (output/1321v2_pick, отбор по популярности
и живости, без человека), разложены по трём слайдам. Вёрстка, тексты, безопасная рамка — build_1321_carousels.

  python build_1321v2_carousels.py --no-plate --qa -n 100 --out output/carousels_1321v2 --flat output/1321v2_100 --flat-id 1321
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1321_carousels as B  # noqa: E402

SL = ROOT / "output" / "1321v2_slides"
B.SLIDES = [(SL / d.name, *rest) for d, *rest in B.SLIDES]

if __name__ == "__main__":
    raise SystemExit(B.main())
