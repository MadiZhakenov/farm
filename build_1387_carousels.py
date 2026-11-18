#!/usr/bin/env python3
"""
1387 — Inspoy, «my ex invited me to his birthday»: 6 слайдов 3:4 (1080×1440). Тексты ТЗ дословно, TikTok-шрифт
с обводкой, переносы по смыслу; вёрстка, безопасная рамка, QA и уникальные сочетания — build_1283.
  s1 яркое эмоциональное селфи (Flow) · s2 подруга подбирает образы (Flow, POV) — output/1387_slides/s1, s2
  s3–s5 образы: селфи в зеркале той же героини (Flow, одна съёмка) — output/1387_slides/s3, s4, s5
  s6 образ + вставка с настоящим скрином Inspoy (make_1387_s6.py → output/1387_slides/s6)

  python build_1387_carousels.py --qa --out output/carousels_1387_test -n 3 --darken 0.08
  python build_1387_carousels.py -n 100 --out output/carousels_1387 --flat output/1387_100 --flat-id 1387 --darken 0.08
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1283_carousels as C  # noqa: E402

SL = ROOT / "output" / "1387_slides"
LIB = ROOT / "output" / "1387_lib"

# папка, текст, режим, cy, макс. высота блока (доли кадра), crop_top
C.SLIDES = [
    (SL / "s1", "girrrls\n\nmy ex invited me\nto his birthday 😳\nand i have one hour\nto decide what to wear",
     "fixed", 0.155, 0.19, 0.0),                       # над головой: переносы, мельче
    (SL / "s2", "my best friend said:\ndress for the version of you\nhe regrets.\n\nand she picked outfits for me",
     "fixed", 0.125, 0.17, 0.0),                       # стена над подругой
    (SL / "s3", "the \"i'm fine\" look", "fixed", 0.10, 0.08, 0.0),
    (SL / "s4", "the \"i'm better than fine\" look", "fixed", 0.10, 0.08, 0.0),
    (SL / "s5", "the \"who are you again\" look", "fixed", 0.10, 0.08, 0.0),
    (SL / "s6", "she put all these looks together\nin Inspoy: Outfit Maker, Planner.\n\nlooks like i'm going 🥹",
     "fixed", 0.15, 0.22, 0.0),
]
C.CX, C.MW, C.PER_IMAGE = {}, {}, {}
C.EXT = (".jpg", ".jpeg", ".png", ".webp")

if __name__ == "__main__":
    raise SystemExit(C.main())
