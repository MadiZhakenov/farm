#!/usr/bin/env python3
"""
Global Work «Best websites to find jobs in 2026» — та же карусель (build_gw_sites_carousel.py: тексты рефа, стиль,
тон под реф), новые фото креатора: downloads/gw_carousel2/srcA (Drive 1AurQE35bLH4doPlTytcO00pq9QpKRwe_).
Обложка — селфи (заголовок под подбородком), слайд 2 — ноут с открытым GlobalWork.ai, YC Jobs — лифт
(заголовок над головой, текст под лицом); селфи на улице — кадрировано на деревья и улицу без лица, как Бурдж в первой.

  python build_gw_sites_carousel2.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_sites_carousel as C  # noqa: E402

C.SRC = ROOT / "downloads" / "gw_carousel2" / "srcA"
C.OUT = ROOT / "output" / "gw_sites_carousel2"
C.PHOTOS = {
    1: ("IMG_9380.jpg", None),                          # селфи у домов, лицо 433–787 px → заголовок под подбородком
    2: ("IMG_5717.jpg", None),                          # ноут, вкладка GlobalWork.ai
    3: ("IMG_2881.jpg", None),                          # ноут, кофе, блокнот
    4: ("IMG_2612.jpg", None),                          # ноут на террасе
    5: ("IMG_3729.jpg", None),                          # лифт: лицо ~370–500 px
    6: ("IMG_7857.jpg", (0.25, 0.0, 0.85, 0.6)),        # кафе: стул, цветы, верх ноута — её лицо на экране ниже текста
    7: ("IMG_3720.jpg", (0.68, 0.08, 1.0, 0.40)),       # улица и деревья без лица
}
C.LAYOUT = {2: (300, 420, C.Y1), 3: (300, 420, C.Y1), 4: (260, 380, C.Y1), 5: (250, 530, C.Y1),
            6: (300, 420, C.Y1), 7: (300, 420, C.Y1)}
C.COVER_TOP = 793                                     # низ подписи ровно на 1123 (граница зоны)

if __name__ == "__main__":
    raise SystemExit(C.main())
