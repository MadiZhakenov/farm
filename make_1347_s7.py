#!/usr/bin/env python3
"""
1347, слайд 7: холодильник со старым серым и новым оранжевым рисунком + вставка НАСТОЯЩЕГО скрина Inspoy
(My Beauty Report → Why This Is You → Skin Undertone: Warm, персиковые оттенки — IMG_7789 из «скриншоты на будущее»).
Вставка — make_1343_s6.inset (4× суперсэмплинг, белая рамка, тень, наклон) из карточки «Why This Is You /
Skin Undertone: Warm» (обрезана по карточке — крупнее читается), слева под текстом: на дверце холодильника и солнце
старого рисунка, мимо серой мамы, мимо кнопок TikTok справа. Текст — во всю ширину сверху.

  python make_1347_s7.py      # output/1347_slides/s7_fridge/*.webp → output/1347_slides/s7/<кадр>.jpg
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import make_1343_s6 as M  # noqa: E402

BASES = ROOT / "output" / "1347_slides" / "s7_fridge"
SCREEN = Path(r"C:\Users\user\Downloads\Telegram Desktop\скриншоты на будущее\IMG_7789.PNG")
OUT = ROOT / "output" / "1347_slides" / "s7"
W, H = 1080, 1440
X, Y = 24, 318                                   # левый верх вставки (без тени): под текстом, низ ~680 — выше головы папы
CARD = (30, 760, 1030, 1500)                     # «Why This Is You» + Skin Undertone: Warm + оттенки (без обрезанной строки описания)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    card = OUT / "_screen_card.png"
    Image.open(SCREEN).convert("RGB").crop(CARD).save(card)
    M.INSET_W, M.ANGLE, M.CROP = 400, -4, (0, CARD[3] - CARD[1])
    ins = M.inset(card)
    for b in sorted(p for p in BASES.iterdir() if p.suffix.lower() in (".jpg", ".png", ".webp") and not p.name.startswith("_")):
        bg = ImageOps.fit(Image.open(b).convert("RGB"), (W, H), Image.Resampling.LANCZOS).convert("RGBA")
        bg.alpha_composite(ins, (X - 40, Y - 40))
        dst = OUT / f"{b.stem}.jpg"
        bg.convert("RGB").save(dst, quality=95)
        print(dst, ins.size)


if __name__ == "__main__":
    main()
