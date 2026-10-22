#!/usr/bin/env python3
"""
Global Work «Best websites to find jobs in 2026» — дополнительная карусель к output/gw_sites_carousel2
(тот же сборщик build_gw_sites_carousel.py: тексты рефа, стиль, тон под реф). Фото — Drive
1Ci7lQeCd9wAvhEwqJNX_3Cp_ATAKi2jC → downloads/gw_carousel2/srcB_new (7 фото; IMG_5717 и IMG_2612 — те же,
что в gw_sites_carousel2). Отдельная папка: output/gw_sites_carousel3/sort_<слайд>_1_noid.jpg.
Обложка — селфи в лифте (лицо 128–335 px → заголовок под подбородком), 2 — ноут с GlobalWork.ai,
5 — лифт (над головой места нет — заголовок под подбородком), 7 — зеркальное селфи целиком: плашка над головой, текст под подбородком.

  python build_gw_sites_carousel2b.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_sites_carousel as C  # noqa: E402

C.SRC = ROOT / "downloads" / "gw_carousel2" / "srcB_new"
C.OUT = ROOT / "output" / "gw_sites_carousel3"
C.CAROUSEL = 1
C.PHOTOS = {
    1: ("IMG_8120.PNG", None),                          # селфи в лифте, лицо 128–335 px → заголовок под подбородком
    2: ("IMG_5717.jpg", None),                          # ноут, вкладка GlobalWork.ai
    3: ("IMG_8003.jpg", None),                          # балкон: планшет, завтрак, блокнот
    4: ("IMG_2612.jpg", None),                          # ноут в кафе
    5: ("IMG_8121.PNG", None),                          # лифт
    6: ("IMG_8122.PNG", None),                          # рука с кольцами
    7: ("IMG_9887.jpg", None),                          # зеркальное селфи целиком: лицо 410–560 px → текст под подбородком
}
C.LAYOUT = {2: (300, 420, C.Y1), 3: (300, 420, C.Y1), 4: (260, 380, C.Y1), 5: (380, 450, C.Y1),  # 5: лицо до 320 px
            6: (300, 420, C.Y1), 7: (240, 600, C.Y1)}
C.COVER_TOP = 380

if __name__ == "__main__":
    raise SystemExit(C.main())
