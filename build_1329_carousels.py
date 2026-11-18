#!/usr/bin/env python3
"""
1329 — Inspoy, «i'm a stylist and these are the 3 best halloween looks…»: 3:4 (1080×1440) из output/1329_slides/<папка>.
Тексты ТЗ дословно (на обложке «5» → «3» с согласия пользователя), TikTok-шрифт с обводкой, переносы по смыслу;
«[[…]]» — строка на белой подложке (обложка: «3 best halloween looks», просьба клиента).
Вёрстка, безопасная рамка и QA — из build_1283_carousels.py. Слайд 5 — готовый коллаж скринов Inspoy (make_1329_s5_collage.py), кладётся как есть.

  python build_1329_carousels.py --qa --out output/carousels_1329_test -n 3
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1283_carousels as C  # noqa: E402

SL = ROOT / "output" / "1329_slides"
C.B.PX_MAX = 78                                          # подписи образов короткие — крупнее

# папка, текст, режим, cy, макс. высота блока (доли кадра), crop_top
C.SLIDES = [
    (SL / "s1_cover",                                     # лицо сверху, руки с вешалкой — середина; текст ниже рук
     "i'm a stylist and these are the\n[[3 best halloween looks]]\nyou have to wear\nat least once in your life 🎃\n\n"
     "which one are you wearing? 👇",
     "fixed", 0.665, 0.25, 0.0),
    (SL / "s2_witch", "witch but\nmake it expensive", "fixed", 0.72, 0.15, 0.0),
    (SL / "s3_vamp", "vampire in velvet", "fixed", 0.72, 0.10, 0.0),
    (SL / "s4_angel", "all white angel\n(my clients' fave)", "fixed", 0.72, 0.15, 0.0),
    (SL / "s5_inspoy", "", "ready", 0, 0, 0.0),           # коллаж скринов Inspoy с текстом — make_1329_s5_collage.py
]
C.CX, C.MW, C.PER_IMAGE = {}, {}, {}
C.EXT = (".jpg", ".jpeg", ".png", ".webp")
PLATE_FILL, PLATE_INK = (255, 255, 255, 255), (17, 17, 17, 255)
HL_SCALE = 1.15                                          # строка на подложке чуть крупнее остального текста


def plate_line(text: str, px: int) -> Image.Image:
    """Строка на белой TikTok-подложке: тот же шрифт и кегль, чёрный текст без обводки."""
    font = C.B.R._load_font(px)
    l, t, r, b = font.getbbox(text)
    padx, h = int(px * 0.42), int(px * 1.32)
    im = Image.new("RGBA", (r - l + 2 * padx, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, im.width - 1, h - 1], int(px * 0.28), fill=PLATE_FILL)
    d.text((im.width / 2, h / 2), text, font=font, fill=PLATE_INK, anchor="mm")
    return im


_place = C.place


def place(slide: int, name: str):
    """Строка в [[…]] — отдельной строкой на подложке (обложка: «3 best halloween looks»)."""
    _d, text, mode, cy, mh, _crop = C.SLIDES[slide]
    if "[[" not in text:
        return _place(slide, name)
    top, rest = text.split("[[", 1)
    hl, bottom = rest.split("]]", 1)
    top, bottom = top.strip("\n"), bottom.strip("\n")
    plain = "\n".join(x for x in (top, hl, bottom) if x)
    max_h, max_w = int(mh * C.H), int(C.MW.get(slide, (C.X1 - C.X0) / C.W) * C.W)
    px = next((q for q in range(C.B.PX_MAX, C.B.PX_MIN - 1, -1)
               if C.fits(plain, q, max_h - int(q * 0.5), max_w - int(q * 0.9))), C.B.PX_MIN)
    gap = int(px * 0.22)
    parts = [C.B.text_block(top, max_h, px)] if top else []
    parts.append(plate_line(hl, int(px * HL_SCALE)))
    if bottom:
        parts.append(C.B.text_block(bottom, max_h, px))
    bh = sum(p.height for p in parts) + gap * (len(parts) - 1)
    bw = max(p.width for p in parts)
    y = int(cy * C.H - bh / 2)
    y = max(C.Y0, min(C.Y1 - bh, y))
    out = Image.new("RGBA", (C.W, C.H), (0, 0, 0, 0))
    yy = y
    for p in parts:
        out.alpha_composite(p, ((C.W - p.width) // 2, yy))
        yy += p.height + gap
    x = (C.W - bw) // 2
    return out, (x, y, x + bw, y + bh)


C.place = place

if __name__ == "__main__":
    raise SystemExit(C.main())
