#!/usr/bin/env python3
"""skinive_5: тату-рука с родинкой (обведена, стрелка) — первый кадр текстволла. Трекер skinive_3 (Лукас–Канаде),
наезд 1.5, родинка на 0.45 H — тату и родинка НАД текстволлом (он внизу, под подбородком на лице).
Кэш: output/_work/skinive5/tattoo/<id>.mp4 (3.1 с, 1080×1920, 30 fps).
  python make_skinive5_tattoo.py [--sheet]"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import make_skinive3_moles as M  # noqa: E402

M.OUT = ROOT / "output" / "_work" / "skinive5" / "tattoo"
M.Z, M.AT_Y = 1.5, 0.45
M.WINDOWS = [   # (id, клип, старт, x, y стартовой точки) — спокойные участки, точка = родинка в круге
    ("t1", "IMG_6381", 0.3, 0.33, 0.57),
    ("t2", "IMG_6382", 0.5, 0.33, 0.645),
    ("t3", "IMG_6382", 6.8, 0.33, 0.56),
]

if __name__ == "__main__":
    raise SystemExit(M.main())
