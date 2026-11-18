#!/usr/bin/env python3
"""
Inspoy — «thanksgiving outfits for dinner with the family 🍂» (айди нет): 6 слайдов 3:4, та же схема, что
build_xmas_costumes_carousels (реф — наша 1319): s1 обложка — текст на брюках ниже рук · s2–s5 образы на её кровати,
название на стене/подушках над вещами · s6 та же девушка, телефон закрывает лицо — текст ТЗ + карточка Inspoy.
Фото — output/thanksgiving_outfits/slides/s<k>/*.jpg. Тексты ТЗ дословно, переносы по смыслу.

  python build_thanksgiving_carousels.py -n 2 --out output/thanksgiving_test --qa
  python build_thanksgiving_carousels.py -n 150 --out output/carousels_thanksgiving --flat output/thanksgiving_150
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_xmas_costumes_carousels as X  # noqa: E402

NL = chr(10)
X.SL = ROOT / "output" / "thanksgiving_outfits" / "slides"
X.SLIDES = [
    ([NL.join(["thanksgiving outfits", "for dinner with the family 🍂"])], "low", 76),
    ([NL.join(["for the aunt who comments:", "knit midi dress"]),
      NL.join(["for the aunt", "who comments:", "knit midi dress"])], "top", 60),
    ([NL.join(["for meeting his parents:", "wide trousers + turtleneck"]),
      NL.join(["for meeting his parents:", "wide trousers", "+ turtleneck"]),
      NL.join(["for meeting", "his parents:", "wide trousers", "+ turtleneck"])], "top", 60),
    ([NL.join(["for grandma’s table:", "cardigan over a slip dress"]),
      NL.join(["for grandma’s table:", "cardigan over", "a slip dress"])], "top", 60),
    ([NL.join(["for the second plate:", "burnt orange sweater", "+ straight jeans"]),
      NL.join(["for the", "second plate:", "burnt orange sweater", "+ straight jeans"])], "top", 60),
    ([NL.join(["i found all of this in Inspoy:", "Outfit Maker, Planner", "", "and planned it", "the night before btw 🍂"])],
     "app", 56),
]
X.GRADE = True                                         # юзер: «живо и свежо» — убираем жёлтый налёт, сочнее
X.COVER_BAND = (0.56, 0.76)                            # обложка: на брюках ниже пояса и рук
X.APP_TOP = 0.31                                       # финал: под телефоном, на свитере
# раскладки: верх кадра — стена с лампой слева и подушки; сначала правее лампы, иначе на всю ширину
X.WALL_BOXES = [(0.34, 0.0, 1.0, 0.33), (0.0, 0.0, 1.0, 0.33)]
X.TITLE_OK_PX = 46                                     # правее лампы даже мельче — лишь бы не на лампе

if __name__ == "__main__":
    raise SystemExit(X.main())
