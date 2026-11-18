#!/usr/bin/env python3
"""
Curly (Mouthwashing) — рот на наклеечную бумагу A4 в реальном размере, 300 dpi.
Рот из Flow (output/curly/mouth_flow.jpg) вырезается из белого фона; 100 % = ряд зубов 5,3 см
(средняя ширина рта мужчины 180 см). На листе лесенка 90/100/110/120 % и контрольная линейка 5 см.

  python make_curly_sheet.py            # → output/curly/curly_mouth_A4.pdf + .png
  python make_curly_sheet.py --teeth 5.6   # если ширина рта измерена линейкой (см)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy import ndimage as nd

ROOT = Path(__file__).resolve().parent
DIR = ROOT / "output" / "curly"
DPI = 300
PX_CM = DPI / 2.54
W, H = round(21.0 * PX_CM), round(29.7 * PX_CM)          # A4 2480×3508
MARGIN = round(1.0 * PX_CM)
FONT = "C:/Windows/Fonts/arial.ttf"


def cutout(src: Path) -> tuple[Image.Image, int]:
    """RGBA рта без фона и ширина ряда зубов в пикселях исходника."""
    rgb = Image.open(src).convert("RGB")
    a = np.asarray(rgb).astype(int)
    nonw = a.min(2) < 225
    lab, n = nd.label(nonw)
    big = np.argmax(nd.sum(nonw, lab, range(1, n + 1))) + 1
    mask = nd.binary_fill_holes(lab == big)
    inner = nd.binary_erosion(mask, iterations=25)
    teeth = inner & (a.min(2) > 170) & (a.max(2) - a.min(2) < 45)
    cols = np.nonzero(teeth.sum(0) > 15)[0]
    alpha = Image.fromarray((mask * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.8))
    im = rgb.copy()
    im.putalpha(alpha)
    return im.crop(im.getbbox()), int(cols.max() - cols.min())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DIR / "mouth_flow.jpg"))
    ap.add_argument("--teeth", type=float, default=5.3, help="ширина ряда зубов при 100 %%, см")
    args = ap.parse_args()

    mouth, teeth_px = cutout(Path(args.src))
    base = args.teeth * PX_CM / teeth_px                       # масштаб 100 %
    f_big, f_small = ImageFont.truetype(FONT, 46), ImageFont.truetype(FONT, 34)

    sheet = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(sheet)
    d.text((MARGIN, MARGIN), "Curly — рот. Печать: 100 % / «Фактический размер», НЕ «вписать в страницу».",
           font=f_big, fill=(60, 60, 60))
    d.text((MARGIN, MARGIN + 60), "Режь по коричневому контуру. Сначала проверь линейку внизу: ровно 5 см.",
           font=f_small, fill=(110, 110, 110))

    def piece(pct: int) -> Image.Image:
        k = base * pct / 100
        return mouth.resize((round(mouth.width * k), round(mouth.height * k)), Image.Resampling.LANCZOS)

    y = MARGIN + 170
    for pct, copies in ((90, 2), (100, 2), (110, 1), (120, 1)):
        p = piece(pct)
        w_cm, h_cm = p.width / PX_CM, p.height / PX_CM
        d.text((MARGIN, y), f"{pct} %  ·  зубы {args.teeth * pct / 100:.1f} см  ·  весь рот {w_cm:.1f} × {h_cm:.1f} см",
               font=f_small, fill=(110, 110, 110))
        y += 55
        gap = (W - 2 * MARGIN - copies * p.width) // max(copies - 1, 1) if copies > 1 else 0
        for i in range(copies):
            sheet.paste(p, (MARGIN + i * (p.width + gap), y), p)
        y += p.height + 90

    # контрольная линейка 5 см с миллиметрами
    x0, ly = MARGIN, y + 40
    d.line((x0, ly, x0 + 5 * PX_CM, ly), fill="black", width=3)
    for mm in range(51):
        x = x0 + mm * PX_CM / 10
        t = 40 if mm % 10 == 0 else 24 if mm % 5 == 0 else 14
        d.line((x, ly, x, ly - t), fill="black", width=3 if mm % 10 == 0 else 2)
        if mm % 10 == 0:
            d.text((x - 10, ly + 10), str(mm // 10), font=f_small, fill="black")
    d.text((x0 + 5 * PX_CM + 40, ly - 30), "5 см — если не совпадает с линейкой, принтер ужал масштаб",
           font=f_small, fill=(110, 110, 110))
    assert ly + 60 < H - MARGIN, "не влезло на A4"

    out = DIR / "curly_mouth_A4"
    sheet.save(out.with_suffix(".pdf"), resolution=DPI)
    sheet.save(out.with_suffix(".png"), dpi=(DPI, DPI))
    piece(100).save(DIR / "curly_mouth_100.png", dpi=(DPI, DPI))
    print(f"teeth {teeth_px}px -> 100 % = {piece(100).width / PX_CM:.1f} x {piece(100).height / PX_CM:.1f} cm; {out}.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
