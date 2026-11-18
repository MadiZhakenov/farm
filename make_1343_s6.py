#!/usr/bin/env python3
"""
1343, слайд 6: бабушка и внучка в новых образах + маленькая вставка с НАСТОЯЩИМ скрином Inspoy в углу
(вкладка Style, карточка «Inspiration for You» — downloads/1329/inspoy/screen_1..4, скрины пользователя).
Вставка: блок «Inspiration for You» — заголовок, карточка с образом и Try On (весь высокий скрин крупно не влезает
мимо лиц), скруглённые углы, белая рамка, мягкая тень, лёгкий наклон; крупно — чтобы читалось после сжатия.
Левый верхний угол кадра (стена/вешалка над бабушкой — мимо лиц и мимо UI TikTok снизу и справа).

  python make_1343_s6.py      # output/1343_slides/s6_final/*.jpg × скрины → output/1343_slides/s6/<кадр>_<скрин>.jpg
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
BASES = ROOT / "output" / "1343_slides" / "s6_final"
SCREENS = sorted((ROOT / "downloads" / "1329" / "inspoy").glob("screen_*.webp"))
OUT = ROOT / "output" / "1343_slides" / "s6"
W, H = 1080, 1440
INSET_W, CROP, X, Y, ANGLE = 330, (440, 1440), 26, 88, 4       # CROP — полоса скрина по y (923×2000)


def inset(src: Path, ss: int = 4) -> Image.Image:
    """Всё рисуем в ss× (маска скругления, рамка, поворот) и уменьшаем — ровные гладкие края без «лесенки»."""
    sc = Image.open(src).convert("RGB")
    sc = sc.crop((0, CROP[0], sc.width, min(CROP[1], sc.height)))
    w = INSET_W * ss
    h = round(sc.height * w / sc.width)
    sc = sc.resize((w, h), Image.Resampling.LANCZOS)
    r, ring = 26 * ss, 6 * ss
    card = Image.new("RGBA", (w + 2 * ring, h + 2 * ring), (255, 255, 255, 0))
    ImageDraw.Draw(card).rounded_rectangle((0, 0, card.width - 1, card.height - 1), r + ring, fill=(255, 255, 255, 255))
    m = Image.new("L", sc.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    card.paste(sc, (ring, ring), m)
    card = card.rotate(ANGLE, Image.Resampling.BICUBIC, expand=True)
    card = card.resize((round(card.width / ss), round(card.height / ss)), Image.Resampling.LANCZOS)
    pad = 40
    out = Image.new("RGBA", (card.width + 2 * pad, card.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("L", out.size, 0)
    sh.paste(card.getchannel("A").point(lambda v: int(v * 0.43)), (pad + 6, pad + 12))
    shadow = Image.new("RGBA", out.size, (0, 0, 0, 0))
    shadow.putalpha(sh.filter(ImageFilter.GaussianBlur(14)))
    out.alpha_composite(shadow)
    out.alpha_composite(card, (pad, pad))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    bases = sorted(p for p in BASES.iterdir() if p.suffix.lower() in (".jpg", ".png", ".webp") and not p.name.startswith("_"))
    for b in bases:
        bg = ImageOps.fit(Image.open(b).convert("RGB"), (W, H), Image.Resampling.LANCZOS).convert("RGBA")
        for s in SCREENS:
            im = bg.copy()
            ins = inset(s)
            im.alpha_composite(ins, (X - 40, Y - 40))
            dst = OUT / f"{b.stem}_{s.stem}.jpg"
            im.convert("RGB").save(dst, quality=95)
            print(dst)


if __name__ == "__main__":
    main()
