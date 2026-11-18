#!/usr/bin/env python3
"""
1341, слайд 6: настоящий скрин Inspoy (вкладка Style, карточка «Inspiration for You») с образом 5 (синее платье)
в карточке и подписью «Date Night». Коллаж образа (Flow, белый фон, раскладка как в карточке Inspoy):
output/1341_slides/_pack/look5.jpg. Вклейка — make_1329_inspoy_screens.make (интерфейс — пиксели оригинала).

  python make_1341_inspoy_screens.py      # → output/1341_slides/s6_screens/<screen>_<look>.png
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import make_1329_inspoy_screens as M  # noqa: E402

PACK = ROOT / "output" / "1341_slides" / "_pack"
OUT = ROOT / "output" / "1341_slides" / "s6_screens"

LOOKS = [("screen_3", "look5"), ("screen_1", "look5_b1"), ("screen_4", "look5_b2")]   # 3 раскладки × 3 разных скрина

if __name__ == "__main__":
    for screen, look in LOOKS:
        print(M.make(screen, PACK / f"{look}.jpg", label="Date Night", out=OUT))
