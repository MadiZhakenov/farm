#!/usr/bin/env python3
"""
1347 — Inspoy, «my 6-year-old drew our family and colored me gray»: 7 слайдов 3:4 (1080×1440) из
output/1347_slides/<папка>. История от первого лица: серая мама на детском рисунке → шкаф → её тёплые цвета →
коралловый у школы → новый оранжевый рисунок на холодильнике. Тексты ТЗ дословно, TikTok-шрифт с обводкой,
переносы по смыслу; вёрстка, безопасная рамка, QA и уникальные сочетания — build_1283.
Слайд 7 — кадры с готовой вставкой настоящего скрина Inspoy (make_1347_s7.py → output/1347_slides/s7).

  python build_1347_carousels.py --qa --out output/carousels_1347_test -n 4
  python build_1347_carousels.py -n 64 --out output/carousels_1347 --flat output/1347_64 --flat-id 1347 --qa
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1283_carousels as C  # noqa: E402

SL = ROOT / "output" / "1347_slides"

# папка, текст, режим, cy, макс. высота блока (доли кадра), crop_top
C.SLIDES = [
    (SL / "s1_drawing",                                   # верх листа (солнце слева, справа пусто)
     "my 6-year-old drew our family\nand colored me gray 🥺",
     "fixed", 0.165, 0.13, 0.0),
    (SL / "s2_closeup",                                   # чистый лист и мелки сверху
     "dad: blue. brother: yellow.\nher: pink. me: gray.\n\ni asked why",
     "fixed", 0.14, 0.2, 0.0),
    (SL / "s3_child",                                     # деревянный стол над листом
     "she said:\n\"because you always\nwear gray, mommy\"",
     "fixed", 0.125, 0.19, 0.0),
    (SL / "s4_closet",                                    # верхняя полка и штанга
     "i opened my closet.\nblack. grey. beige. navy.\n14 years of \"safe\"",
     "fixed", 0.13, 0.19, 0.0),
    (SL / "s5_swatches",                                  # ноутбук и лампа сверху — над лоскутами
     "that night i finally found out\nmy real colors.\nwarm. coral, peach, terracotta.\n\nnone of them were gray",
     "fixed", 0.15, 0.25, 0.0),
    (SL / "s6_hug",                                       # двор и дети вдали — над головой девочки
     "next morning i wore coral\nto school pickup.\n\nshe ran across the whole yard\nscreaming \"mommy,\n"
     "you look like a sunset!\"",
     "fixed", 0.165, 0.27, 0.0),
    (SL / "s7",                                           # чистая дверь холодильника сверху; скрин — слева под текстом
     "she redrew me. in orange.\nit's on our fridge now 🧡\n\ni found my colors in\nInspoy: Outfit Maker, Planner",
     "fixed", 0.135, 0.165, 0.0),
]
C.CX, C.MW, C.PER_IMAGE = {}, {}, {}
C.EXT = (".jpg", ".jpeg", ".png", ".webp")

if __name__ == "__main__":
    raise SystemExit(C.main())
