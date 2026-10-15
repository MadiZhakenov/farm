#!/usr/bin/env python3
"""
1292 — Magic Sort, карусель «my 78 y/o grandpa called me at 3:12am…» (как 1248): 6 слайдов 3:4 (1080×1440)
из output/1292_slides/<папка>. Тексты — дословно из ТЗ, переносы по смыслу вручную (\\n — строка, \\n\\n — отступ,
\\n|\\n — делим текст на части со своими местами). Вёрстка, безопасная рамка и QA — из build_1283_carousels.py.

  python build_1292_carousels.py --qa --out output/carousels_1292_test -n 3
  python build_1292_carousels.py -n 100 --out output/carousels_1292 --flat output/1292_100 --flat-id 1292 --qa
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1283_carousels as C  # noqa: E402

SL = ROOT / "output" / "1292_slides"

# папка, текст ТЗ с переносами по смыслу, режим, cy (или места split), макс. высота блока, crop_top
C.SLIDES = [
    (SL / "s1_selfie",
     "my 78 y/o grandpa called me at 3:12am.\nhe NEVER calls.\n\nhe whispered:\n“don’t tell grandma. i need you. now.”",
     "fixed", 0.69, 0.17, 0.0),                           # лица в середине — текст на свитерах
    (SL / "s2_door",                                      # дед в центре двери: начало над ним, конец — под рукой
     "i drove 40 minutes\nwith 3% battery,\nready for anything.\n|\n"
     "he opened the door in his robe:\n“hurry. quiet.”\nlooking left and right like a spy",
     "split", [(0.155, 0.17), (0.705, 0.15)], None, 0.0),
    (SL / "s3_kitchen",                                   # без Magic Sort: iPad стоит спиной к камере (k11–k14)
     "he led me to the kitchen.\none lamp. his reading glasses.\nhis iPad glowing on the table.\n\ni held my breath…",
     "fixed", 0.20, 0.24, 0.0),                           # шкафы сверху; стол с iPad — в середине
    (SL / "s4_stuck",                                     # без Magic Sort: дед держит iPad спиной к камере —
     "“i’m stuck.”\n\nthat’s it.\nthat’s the emergency.\n\nhe’d been up since 9pm\nand grandma had hidden\nhis iPad twice",
     "fixed", 0.625, 0.30, 0.0),                          # текст на задней крышке iPad под лицом (st11–st14)
    (SL / "s5_wow",                                       # то же: iPad справа
     "level 312 of Magic Sort.\n\ni said “move the green one”\nand he looked at me\nlike i had just solved\nworld peace",
     "fixed", 0.635, 0.28, 0.0),
    (SL / "s6_grandma",                                   # бабушка справа — блок левее, над головой деда
     "we beat it at 5:40am.\n\ngrandma walked in:\n“so THIS is where\nyou two have been.”\n\n"
     "grandpa didn’t even look up:\n“shh. one more level.”",
     "fixed", 0.18, 0.23, 0.0),
]
C.CX = {3: 0.546, 4: 0.40, 5: 0.42}
C.MW = {3: 0.42, 4: 0.47, 5: 0.51}
C.PER_IMAGE: dict = {}

if __name__ == "__main__":
    raise SystemExit(C.main())
