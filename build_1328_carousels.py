#!/usr/bin/env python3
"""
1328 — Inspoy, карусель-история «my grandpa has been married to the same woman for 52 years 😳»: формат 1321
(build_1321_carousels.py — 6 слайдов 3:4, s1/s2 чёрный текст на белой подложке под лицами, s3–s5 названия сверху,
s6 текст + карточка App Store), только с дедушкой и образами «Year 1 / 25 / 52». Тексты — дословно из ТЗ.

Кадры: output/1328_slides/s1…s6/*.jpg — генерации пользователя (Google Flow, 3:4).

  python build_1328_carousels.py --qa --out output/carousels_1328_test -n 1
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1321_carousels as C  # noqa: E402

NL = C.NL
C.SL = SL = ROOT / "output" / "1328_slides"
C.SLIDES = [
    (SL / "s1", NL.join(["my grandpa has been married", "to the same woman", "for 52 years 😳", "", "his secret is…"]),
     "plate", 64),
    (SL / "s2", NL.join(["he said:", "dress like it's always", "a first date,", "", "and picked outfits for me"]),
     "plate", 60),
    (SL / "s3", "Year 1 look", "title", 76),
    (SL / "s4", "Year 25 look", "title", 76),
    (SL / "s5", "Year 52 look", "title", 76),
    (SL / "s6", NL.join(["he put all these looks together in", "Inspoy: Outfit Maker, Planner.", "",
                         "looks like i'll be married 52 years too 🥹"]), "app", 52),
]

if __name__ == "__main__":
    raise SystemExit(C.main())
