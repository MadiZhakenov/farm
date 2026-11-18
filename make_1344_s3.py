#!/usr/bin/env python3
"""
1344, слайд 3: вечер накануне (кровать, платье на дверце шкафа) + крупная вставка НАСТОЯЩЕГО скрина Inspoy
(вкладка Style, блок «Inspiration for You», downloads/1329/inspoy/screen_1..4) справа вверху — на стене над
головой, мимо лица, платья и колонки кнопок TikTok. Вставка — make_1343_s6.inset (4× суперсэмплинг, белая рамка, тень, наклон).

  python make_1344_s3.py      # output/1344_slides/s3_bed/*.jpg × скрины → output/1344_slides/s3/<кадр>_<скрин>.jpg
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import make_1343_s6 as M  # noqa: E402

BASES = ROOT / "output" / "1344_slides" / "s3_bed"
OUT = ROOT / "output" / "1344_slides" / "s3"
W, H = 1080, 1440
X, Y = 600, 88                                   # левый верх вставки (без тени) — выше головы


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    M.INSET_W, M.ANGLE = 318, 4
    for b in sorted(p for p in BASES.iterdir() if p.suffix.lower() in (".jpg", ".png", ".webp") and not p.name.startswith("_")):
        bg = ImageOps.fit(Image.open(b).convert("RGB"), (W, H), Image.Resampling.LANCZOS).convert("RGBA")
        for s in M.SCREENS:
            im = bg.copy()
            im.alpha_composite(M.inset(s), (X - 40, Y - 40))
            dst = OUT / f"{b.stem}_{s.stem}.jpg"
            im.convert("RGB").save(dst, quality=95)
            print(dst)


if __name__ == "__main__":
    main()
