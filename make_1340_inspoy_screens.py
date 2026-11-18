#!/usr/bin/env python3
"""
1340, слайд 5: настоящие скрины Inspoy (вкладка Style, карточка «Inspiration for You») с нашими образами в карточке.
Подпись категории — свой повод (выбор пользователя): пальто → Work (screen_2), платье + тренч → Date Night (screen_3),
кожанка → Night Out (screen_4); родная подпись стирается, новая — тем же шрифтом (как «Halloween» в 1329).
Коллажи образов (Flow, белый фон, раскладка как в карточках Inspoy): output/1340_slides/_pack/<образ>.jpg.
Вклейка — make_1329_inspoy_screens.make (интерфейс — пиксели оригинала).

  python make_1340_inspoy_screens.py      # → output/1340_slides/s5_screens/<screen>_<образ>.png
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import make_1329_inspoy_screens as M  # noqa: E402

PACK = ROOT / "output" / "1340_slides" / "_pack"
OUT = ROOT / "output" / "1340_slides" / "s5_screens"
LOOKS = {"coat": ("screen_2", "Work"), "dress": ("screen_3", "Date Night"), "leather": ("screen_4", "Night Out")}

if __name__ == "__main__":
    for look, (screen, label) in LOOKS.items():
        print(M.make(screen, PACK / f"{look}.jpg", label=label, out=OUT))
