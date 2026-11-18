#!/usr/bin/env python3
"""
1386 — то же ТЗ, что 1383 (лицо 3 с → осенние коллажи 4 с → концовка 1.5 с с карточкой App Store), другая девушка:
3 реакции (downloads/1386/src/face_1..3.mov, эмоция с первого кадра) и 2 концовки (end_1 — рука у подбородка,
довольная ухмылка, 3.75 с; end_2 — улыбка и подмигивание, 2.0 с). Исходники SDR (bt709) — без тонмаппинга.
Лица крупные: текст части 1 — на свитере под подбородком, текст концовки — над головой, карточка App Store 540 px —
под подбородком. Доски — те же, что в 1383: 001–050 — Pinterest-пул 1383, 051–100 — наши доски 1345.
Сборка — build_1383_reels (настройки переопределены здесь, на уровне модуля — их видят и процессы-сборщики).

  python build_1386_reels.py --test
  python build_1386_reels.py -n 100 --last 50
  python build_1386_reels.py -n 100 --first 51 --boards downloads/inspoy_found/gen51
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1383_reels as B  # noqa: E402

B.ID = "1386"
B.D = ROOT / "downloads" / "1386"
B.WORK = ROOT / "output" / "_work" / "1386"
B.FACES = [("face_1", 0.0), ("face_2", 0.0), ("face_3", 0.0)]
B.ENDS = [("end_1", 3.75), ("end_2", 2.0)]
B.BAND1 = (1060, 1540)                                 # просьба клиента: по центру между 1060 и 1540 (y ≈ 1300)
B.BAND3 = (205, 370)                                   # над головой (волосы с ~380)
B.CARD_W, B.CARD_BOTTOM = 540, 1526                    # под подбородком (до ~1272)

if __name__ == "__main__":
    raise SystemExit(B.main())
