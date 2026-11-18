#!/usr/bin/env python3
"""
1343 — Inspoy, «my 82-year-old grandma stopped answering my calls»: 6 слайдов 3:4 (1080×1440) из
output/1343_slides/<папка>. История как у бабушки/дедушки (1249/1248), развязка — Inspoy. Тексты ТЗ дословно,
TikTok-шрифт с обводкой, переносы по смыслу; вёрстка, безопасная рамка, QA и уникальные сочетания — build_1283.
Слайд 6 — кадры с готовой вставкой настоящего скрина Inspoy (make_1343_s6.py → output/1343_slides/s6).

  python build_1343_carousels.py --qa --out output/carousels_1343_test -n 4
  python build_1343_carousels.py -n 64 --out output/carousels_1343 --flat output/1343_64 --flat-id 1343 --qa
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1283_carousels as C  # noqa: E402

SL = ROOT / "output" / "1343_slides"

# папка, текст, режим, cy, макс. высота блока (доли кадра), crop_top
C.SLIDES = [
    (SL / "s1_selfie",                                    # лица сверху — текст на свитерах, под подбородками
     "my 82-year-old grandma\nstopped answering my calls 😳\n\ni called 14 times. nothing.\ni assumed the worst",
     "fixed", 0.70, 0.17, 0.0),
    (SL / "s2_phone",                                     # телефон с 25 % высоты — текст на потолке коридора
     "i called the neighbors.\nnobody had seen her\nsince Sunday",
     "fixed", 0.13, 0.13, 0.0),
    (SL / "s3_office",                                    # потолок переговорки
     "i left work\nin the middle of a meeting.\n\ni didn't even grab my coat",
     "fixed", 0.135, 0.16, 0.0),
    (SL / "s4_drive",                                     # тёмная дорога и небо сверху
     "i drove 10 hours straight.\ni was crying.\ni was bargaining with God",
     "fixed", 0.15, 0.15, 0.0),
    (SL / "s5_couch",                                     # потолок комнаты над окном
     "i burst in and she's on the couch,\nglasses on, tongue out,\nfully locked in on the phone\n"
     "she said she \"would never use\"",
     "fixed", 0.14, 0.17, 0.0),
    (SL / "s6",                                           # вставка со скрином — слева вверху; текст на одежде
     "turns out she'd been putting\noutfits together in Inspoy:\nOutfit Maker, Planner all day.\n\n"
     "she looked up: \"shh. i picked yours.\nyou're wearing it tonight\" 🥹",
     "fixed", 0.66, 0.24, 0.0),
]
C.CX, C.MW, C.PER_IMAGE = {}, {}, {}
C.EXT = (".jpg", ".jpeg", ".png", ".webp")

if __name__ == "__main__":
    raise SystemExit(C.main())
