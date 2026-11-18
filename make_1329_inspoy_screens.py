#!/usr/bin/env python3
"""
1329, слайд 5: настоящие скрины Inspoy (вкладка Style, карточка «Inspiration for You») → в карточку вставляем
нашу хэллоуин-раскладку (downloads/1329/inspoy/flatlays/*.jpg, белый фон), подпись категории → «Halloween».
Интерфейс (иконки, Try On, Unlock, меню) — пиксели оригинала; меняем только картинку внутри карточки и слово.

  python make_1329_inspoy_screens.py      # → output/1329_slides/s5_screens/<screen>_<look>.png
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
D = ROOT / "downloads" / "1329" / "inspoy"
OUT = ROOT / "output" / "1329_slides" / "s5_screens"
FONT = ROOT / "fonts" / "ig_lookalike" / "PlusJakartaSans.ttf"
GREY = (138, 138, 140)

# карточка по скринам (923×2000): x0, x1 белой карточки; область раскладки; подпись (x, базовая y) и что стираем
SCREENS = {
    "screen_3": {"card": (71, 823), "label_x": 110},
    "screen_4": {"card": (73, 824), "label_x": 111},
    "screen_1": {"card": (43, 795), "label_x": 82},
    "screen_2": {"card": (0, 752), "label_x": 38},       # Office: левый край карточки за кадром
}
LAY_Y0, LAY_Y1 = 650, 1305          # где лежит раскладка (под иконками, над подписью и кнопкой Try On)
CLEAR_Y0, CLEAR_Y1 = 648, 1392      # что стираем слева (вместе со старой подписью y 1357–1377)
CAP_H, BASE_Y = 21, 1377            # заглавная старой подписи (E/P/V/O): высота и базовая линия — на всех скринах
WEIGHT = 760
ICON_SRC = ("screen_4", (740, 705, 796, 761), 824)   # «поделиться»: чистый кусок (фон белый) + правый край карточки
KEEP_LABEL_Y, TRYON_TOP = 1350, 1314   # низ стирания, если родная подпись остаётся (её верх 1357) / над Try On (верх 1318)
TRYON_X = {"screen_3": 604, "screen_4": 605, "screen_1": 576, "screen_2": 534}


def font_for(cap_h: int) -> ImageFont.FreeTypeFont:
    best = None
    for px in range(18, 60):
        f = ImageFont.truetype(str(FONT), px)
        f.set_variation_by_axes([WEIGHT])
        h = -f.getbbox("H", anchor="ls")[1]
        if best is None or abs(h - cap_h) < abs(best[0] - cap_h):
            best = (h, f)
    return best[1]


def make(screen: str, look: Path, label: str | None = "Halloween", out: Path = OUT) -> Path:
    """label=None — оставить родную подпись категории (Office / Everyday / Party …)."""
    cfg = SCREENS[screen]
    base = Image.open(D / f"{screen}.webp").convert("RGB")
    x0, x1 = cfg["card"]
    a = np.asarray(base.convert("L")).astype(int)
    reg = a[1340:1400, cfg["label_x"] - 6:cfg["label_x"] + 40]
    lx = int(np.where(reg < 200)[1].min()) + cfg["label_x"] - 6
    arr = np.asarray(base).copy()
    tx = TRYON_X[screen] - 14
    arr[CLEAR_Y0:CLEAR_Y1 if label else KEEP_LABEL_Y, x0 + 6:tx] = 255   # слева — до подписи (вкл., если меняем)
    arr[CLEAR_Y0:TRYON_TOP, tx:x1 - 6] = 255                     # справа — до кнопки Try On (тени старых вещей)
    band = arr[TRYON_TOP:KEEP_LABEL_Y, tx:x1 - 6]                 # у кнопки: всё, что не фиолетовое, — в белый
    band[(band[..., 2].astype(int) - band[..., 1].astype(int)) <= 25] = 255
    src_name, (ix0, iy0, ix1, iy1), src_x1 = ICON_SRC          # иконка «поделиться» с чистым фоном
    icon = np.asarray(Image.open(D / f"{src_name}.webp").convert("RGB"))[iy0:iy1, ix0:ix1]
    dx = x1 - src_x1
    arr[iy0:iy1, ix0 + dx:ix1 + dx] = icon
    bx = TRYON_X[screen] - 6                                      # чистая кнопка Try On с screen_3 (без теней вещей)
    btn = np.asarray(Image.open(D / "screen_3.webp").convert("RGB"))[1310:1402, 598:800]
    arr[1310:1402, bx:bx + btn.shape[1]] = btn
    im = Image.fromarray(arr)
    lay = Image.open(look).convert("RGB")
    side = min(x1 - x0 - 110, LAY_Y1 - LAY_Y0)
    lay = lay.resize((side, side), Image.Resampling.LANCZOS)
    lx0 = x0 + (x1 - x0 - side) // 2
    ly0 = LAY_Y0 + (LAY_Y1 - LAY_Y0 - side) // 2
    region = np.asarray(im.crop((lx0, ly0, lx0 + side, ly0 + side))).astype(np.int16)
    merged = np.minimum(region, np.asarray(lay).astype(np.int16)).astype(np.uint8)
    im.paste(Image.fromarray(merged), (lx0, ly0))
    if label:
        d = ImageDraw.Draw(im)
        f = font_for(CAP_H)
        l = f.getbbox(label, anchor="ls")[0]
        d.text((lx - l, BASE_Y), label, font=f, fill=GREY, anchor="ls")
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{screen}_{look.stem}.png"
    im.save(dest)
    return dest


if __name__ == "__main__":
    for s in ("screen_3", "screen_4", "screen_1"):
        for look in sorted((D / "flatlays").glob("*.jpg")):
            print(make(s, look))
