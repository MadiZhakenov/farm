#!/usr/bin/env python3
"""
1344 — Inspoy, «How i look 95% of the time but… / this 1%>>>>> / the 1% is planned the night before in Inspoy»:
3 слайда 3:4 (1080×1440) из output/1344_slides/<папка>. Реф @lazybaddie._ (2 тёмных селфи), у нас — ярче и
контрастнее: худи → глэм-платье → вечер накануне с настоящим скрином Inspoy (make_1344_s3.py).
Тексты ТЗ дословно, TikTok-шрифт с обводкой, переносы по смыслу; вёрстка, рамка, QA, сочетания — build_1283.

  python build_1344_carousels.py --qa --out output/carousels_1344_test -n 4
  python build_1344_carousels.py -n 64 --out output/carousels_1344 --flat output/1344_64 --flat-id 1344 --qa
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1283_carousels as C  # noqa: E402

SL = ROOT / "output" / "1344_slides"
C.B.PX_MAX = 80                                          # короткие тексты — крупно

# папка, текст, режим, cy, макс. высота блока (доли кадра), crop_top
C.SLIDES = [
    (SL / "s1_hoodie", "How i look\n95% of the time\nbut…", "fixed", 0.66, 0.17, 0.0),    # на худи под лицом
    (SL / "s2_glam", "this 1%>>>>>", "fixed", 0.115, 0.07, 0.0),                     # стена/потолок над головой
    (SL / "s3", "the 1% is planned\nthe night before\nin Inspoy:\nOutfit Maker, Planner",  # на одеяле слева от неё
     "fixed", 0.70, 0.16, 0.0),
]
C.CX, C.MW, C.PER_IMAGE = {2: 0.39}, {2: 0.44}, {}
C.EXT = (".jpg", ".jpeg", ".png", ".webp")

if __name__ == "__main__":
    raise SystemExit(C.main())
