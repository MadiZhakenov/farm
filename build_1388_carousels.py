#!/usr/bin/env python3
"""
1388 — Inspoy, «my crush just texted "what are you doing tonight?"»: 6 слайдов 3:4 (1080×1440), формат 1387.
Тексты ТЗ дословно, TikTok-шрифт с обводкой, переносы по смыслу; вёрстка, безопасная рамка, QA и уникальные
сочетания — build_1283. Одна героиня и одна квартира на всех кадрах (Flow, «живые» промпты — output/1388_pick).
  s1 эмоциональное селфи в зеркале с телефоном · s2 подруга подбирает образы (POV) — output/1388_slides/s1, s2
  s3–s5 образы со стойки подруги: селфи в зеркале — output/1388_slides/s3, s4, s5
  s6 размытая комната + телефон с настоящим скрином Inspoy (make_1388_s6.py → output/1388_slides/s6)

  python build_1388_carousels.py --qa --out output/carousels_1388_test -n 3 --darken 0.08
  python build_1388_carousels.py -n 100 --out output/carousels_1388 --flat output/1388_100 --flat-id 1388 --darken 0.08
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1283_carousels as C  # noqa: E402

SL = ROOT / "output" / "1388_slides"

# папка, текст, режим, cy, макс. высота блока (доли кадра), crop_top — позиции уточнить по готовым кадрам
C.SLIDES = [
    (SL / "s1", "girrrls\n\nmy crush just texted\n\"what are you doing tonight?\" 😳\nand i have 30 minutes\n"
                "to decide what to wear",
     "fixed", 0.135, 0.15, 0.0),                       # выше и мельче — над макушкой
    (SL / "s2", "my best friend said:\ndress like you didn't try.\nbut you did.\n\nand she picked outfits for me",
     "fixed", 0.125, 0.17, 0.0),
    (SL / "s3", "the \"i just woke up\nlike this\" look", "fixed", 0.115, 0.11, 0.0),   # справа от поднятой руки
    (SL / "s4", "the \"i was just in the area\" look", "fixed", 0.10, 0.08, 0.0),
    (SL / "s5", "the \"i've been planning this\nsince 2019\" look", "fixed", 0.11, 0.11, 0.0),
    (SL / "s6", "she put all these looks together\nin Inspoy: Outfit Maker, Planner.\n\nlooks like i'm going 🥹",
     "fixed", 0.15, 0.22, 0.0),
]
C.CX, C.MW, C.PER_IMAGE = {2: 0.625}, {2: 0.41}, {}
C.EXT = (".jpg", ".jpeg", ".png", ".webp")

if __name__ == "__main__":
    raise SystemExit(C.main())
