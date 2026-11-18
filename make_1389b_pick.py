#!/usr/bin/env python3
"""1389b: строгий отбор фото для слайдов 2–4 и ручной кадр 16:9 под экран iMac (из оригиналов _full, сюжет целиком в кадре).
Таблица ниже — результат просмотра каждого кадра; номер → вертикальный центр кадра.
  python make_1389b_pick.py   # пересобирает output/1389b_pick/{room,dog,skill}, в конце лист «как вставлено» на всех фото"""

from __future__ import annotations

import random
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1389_carousels as B  # noqa: E402
import build_1389b as P  # noqa: E402

POOLS = {1: ROOT / "output" / "1389b_pool", 2: ROOT / "output" / "1389b_pool2"}
PICK = ROOT / "output" / "1389b_pick"
OUT = (1360, 766)
MIN_W = 900
TABLE = {   # (пул, номер): вертикальный центр кадра; все источники шириной ≥ 900, вся морда собаки в кадре
    "room": {(2, "003"): .42, (2, "004"): .42, (2, "010"): .42, (2, "013"): .42, (2, "028"): .42, (2, "030"): .42, (2, "037"): .42,
             (2, "042"): .42, (2, "051"): .42, (2, "068"): .42, (2, "071"): .42},
    "dog": {(2, "001"): .42, (2, "007"): .42, (2, "022"): .22, (2, "023"): .42, (2, "032"): .39,
            (2, "051"): .42, (2, "053"): .34, (2, "078"): .42, (2, "086"): .42, (2, "087"): .42, (2, "100"): .25, (2, "129"): .22,
            (1, "005"): .42, (1, "014"): .42, (1, "022"): .2},
    "skill": {(2, "007"): .42, (2, "012"): .42, (2, "014"): .42, (2, "025"): .42, (2, "026"): .42, (2, "032"): .42, (2, "054"): .42,
              (2, "056"): .42, (2, "076"): .42, (2, "077"): .42, (2, "107"): .42, (2, "133"): .42, (1, "035"): .42},
}
SLIDE = {"room": 0, "dog": 1, "skill": 2}


def main() -> int:
    for name, rows in TABLE.items():
        d = PICK / name
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        for (pool, n), cy in rows.items():
            src = next((POOLS[pool] / name / "_full").glob(f"{n}_*"))
            im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
            if im.width < MIN_W:
                raise SystemExit(f"{name} {n}: мало пикселей {im.size}")
            ImageOps.fit(im, OUT, Image.Resampling.LANCZOS, centering=(0.5, cy)).save(d / f"p{pool}_{n}.jpg", quality=95)
        print(name, len(rows))
    bg = sorted(f for f in B.BG.glob("*") if f.suffix.lower() in B.EXT)[0]
    B.PAL = B.PALETTES["sky"]
    f = ImageFont.truetype(str(B.F_BOLD), 30)
    cells = []
    for name, rows in TABLE.items():
        for pool, n in rows:
            im, _ = P.slide(SLIDE[name], PICK / name / f"p{pool}_{n}.jpg", bg, random.Random(5), False)
            ImageDraw.Draw(im).text((20, 16), f"{name} p{pool}_{n}", font=f, fill=(255, 230, 0), stroke_width=3, stroke_fill=(0, 0, 0))
            cells.append(im.crop((150, 40, 930, 800)).resize((390, 380), Image.Resampling.LANCZOS))
    C = 8
    R = (len(cells) + C - 1) // C
    sheet = Image.new("RGB", (390 * C, 380 * R), "white")
    for i, c in enumerate(cells):
        sheet.paste(c, (i % C * 390, i // C * 380))
    (ROOT / "output" / "1389b_test").mkdir(exist_ok=True)
    sheet.save(ROOT / "output" / "1389b_test" / "_all_photos.jpg", quality=88)
    print("лист:", len(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
