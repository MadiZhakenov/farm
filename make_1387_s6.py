#!/usr/bin/env python3
"""
1387, слайд 6: без повтора фото со слайда 5 — размытая комната со стойкой и вещами (кадры слайда 2) + по центру
телефон с НАСТОЯЩИМ скрином Inspoy (вкладка Style, downloads/1329/inspoy/screen_1..4) с тенью и лёгким наклоном.
Текст ТЗ сверху ставит build_1387_carousels.py.

  python make_1387_s6.py    # output/1387_slides/s2 × скрины → output/1387_slides/s6/<кадр>_<скрин>.jpg
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import make_1329_s5_collage as K  # noqa: E402  (phone, drop_any — телефон с тенью)

BASES = ROOT / "output" / "1387_slides" / "s2"
SCREENS = sorted((ROOT / "downloads" / "1329" / "inspoy").glob("screen_*.webp"))
OUT = ROOT / "output" / "1387_slides" / "s6"
W, H = 1080, 1440
PHONE_H, PHONE_TOP, ANGLE = 860, 400, -4      # телефон под текстом сверху (текст до ~25 % высоты)
SS = 4                                          # телефон рисуем и поворачиваем в 4×, потом уменьшаем — без «лесенки»


def phone_smooth(src: Path) -> Image.Image:
    big = K.phone(src, PHONE_H * SS).rotate(ANGLE, Image.Resampling.BICUBIC, expand=True)
    return big.resize((round(big.width / SS), round(big.height / SS)), Image.Resampling.LANCZOS)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    bases = sorted(p for p in BASES.iterdir() if p.suffix.lower() in (".jpg", ".png", ".webp"))
    n = 0
    for k, b in enumerate(bases):
        bg = ImageOps.fit(Image.open(b).convert("RGB"), (W, H), Image.Resampling.LANCZOS)
        bg = ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(22))).enhance(0.9).convert("RGBA")
        for j in range(2):                                     # 2 разных скрина на кадр
            s = SCREENS[(k * 2 + j) % len(SCREENS)]
            im = bg.copy()
            K.drop_any(phone_smooth(s), im, W // 2, PHONE_TOP, 0, alpha=130)
            im.convert("RGB").save(OUT / f"{b.stem}_{s.stem}.jpg", quality=95)
            n += 1
    print(f"готово: {n} → {OUT}")


if __name__ == "__main__":
    main()
