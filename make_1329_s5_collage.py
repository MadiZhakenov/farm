#!/usr/bin/env python3
"""
1329, слайд 5 (3:4, 1080×1440): три скрина Inspoy (output/1329_slides/s5_screens, ведьма / вампир / ангел)
в рамках телефонов — коллаж, чтобы был виден интерфейс приложения. Текст ТЗ дословно, переносы по смыслу,
вверху внутри безопасной рамки core/safe_zones (x 180–900, y 6–78 %).

Раскладки:
  fan    — веер: средний телефон крупно и прямо, боковые меньше и наклонены, фон — размытая обложка
  podium — три прямых телефона, средний выше и крупнее, тёмный фон с тёплым свечением
  fan_dark / podium_cover — те же раскладки с другим фоном (белый текст с обводкой на светлом фоне не читается)

  python make_1329_s5_collage.py              # → output/1329_slides/s5_collage/<layout>.jpg + _qa_<layout>.jpg + _sheet.jpg
  python make_1329_s5_collage.py --variants   # fan × 6 порядков образов → output/1329_slides/s5_inspoy
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1283_carousels as C  # noqa: E402  (block_for — TikTok-текст с обводкой и эмодзи)
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402

W, H = 1080, 1440
X0, Y0, X1, Y1 = text_rect(W, H)
SCR = ROOT / "output" / "1329_slides" / "s5_screens"
COVER = ROOT / "output" / "1329_slides" / "s1_cover" / "c01.webp"
OUT = ROOT / "output" / "1329_slides" / "s5_collage"
TEXT = ("all my looks are made here 👉\nInspoy: Outfit Maker, Planner.\n\n"
        "comment \"costume\"\nand i'll send you the app 🎃")
TEXT_MAX_H = 330
SHOTS = ("screen_3_witch", "screen_4_vamp", "screen_1_angel")   # слева, по центру, справа


def phone(src: Path, h: int) -> Image.Image:
    """Скрин в чёрной рамке телефона со скруглёнными углами."""
    shot = Image.open(src).convert("RGB")
    sw = round(shot.width * h / shot.height)
    shot = shot.resize((sw, h), Image.Resampling.LANCZOS)
    bez = max(8, sw // 40)
    r_in = sw // 8
    pw, ph = sw + 2 * bez, h + 2 * bez
    out = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    ImageDraw.Draw(out).rounded_rectangle([0, 0, pw - 1, ph - 1], r_in + bez, fill=(18, 18, 20, 255))
    m = Image.new("L", shot.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, sw - 1, h - 1], r_in, fill=255)
    out.paste(shot, (bez, bez), m)
    return out


def paste_safe(canvas: Image.Image, img: Image.Image, x: int, y: int) -> None:
    """alpha_composite с обрезкой по краям холста (телефоны могут выходить за кадр)."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(img, (x, y), img)
    canvas.alpha_composite(layer)


def drop_any(img: Image.Image, canvas: Image.Image, cx: int, top: int, angle: float = 0.0, alpha: int = 110) -> None:
    if angle:
        img = img.rotate(angle, Image.Resampling.BICUBIC, expand=True)
    blur = 30
    a = Image.new("L", canvas.size, 0)
    x, y = cx - img.width // 2, top
    a.paste(img.getchannel("A").point(lambda v: alpha if v > 128 else 0), (x, y + 18))
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sh.putalpha(a.filter(ImageFilter.GaussianBlur(blur)))
    canvas.alpha_composite(sh)
    paste_safe(canvas, img, x, y)


def bg_cover() -> Image.Image:
    im = ImageOps.fit(Image.open(COVER).convert("RGB"), (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    im = im.filter(ImageFilter.GaussianBlur(28))
    im = ImageEnhance.Brightness(im).enhance(0.55)
    return im.convert("RGBA")


def bg_glow(base: tuple[int, int, int], glow: tuple[int, int, int]) -> Image.Image:
    im = Image.new("RGB", (W, H), base)
    g = Image.new("L", (W, H), 0)
    ImageDraw.Draw(g).ellipse([W * 0.05, H * 0.30, W * 0.95, H * 1.05], fill=255)
    g = g.filter(ImageFilter.GaussianBlur(160)).point(lambda v: int(v * 0.55))
    im.paste(Image.new("RGB", (W, H), glow), (0, 0), g)
    return im.convert("RGBA")


def text_on(canvas: Image.Image) -> tuple[int, int, int, int]:
    block = C.block_for(TEXT, TEXT_MAX_H, X1 - X0)
    x, y = (W - block.width) // 2, Y0 + 14
    canvas.alpha_composite(block, (x, y))
    box = (x, y, x + block.width, y + block.height)
    bad = check_box(W, H, box)
    if bad:
        raise SystemExit(f"текст вне безопасной зоны {bad}")
    return box


def layout_fan(bg: Image.Image) -> tuple[Image.Image, tuple]:
    cv = bg.copy()
    box = text_on(Image.new("RGBA", (W, H)))           # узнать низ текста
    top = box[3] + 40
    side_h, mid_h = 860, 1000                          # низ телефонов уходит за кадр (там интерфейс TikTok)
    l, m, r = (phone(SCR / f"{s}.png", hh) for s, hh in zip(SHOTS, (side_h, mid_h, side_h)))
    drop_any(l, cv, 168, top + 80, angle=7)            # боковые разведены к краям: карточка с образом видна целиком
    drop_any(r, cv, W - 168, top + 80, angle=-7)
    drop_any(m, cv, W // 2, top, alpha=140)
    return cv, text_on(cv)


def layout_podium(bg: Image.Image) -> tuple[Image.Image, tuple]:
    cv = bg.copy()
    box = text_on(Image.new("RGBA", (W, H)))
    top = box[3] + 40
    l, m, r = (phone(SCR / f"{s}.png", hh) for s, hh in zip(SHOTS, (860, 1000, 860)))
    drop_any(l, cv, 160, top + 90)
    drop_any(r, cv, W - 160, top + 90)
    drop_any(m, cv, W // 2, top, alpha=150)
    return cv, text_on(cv)


LAYOUTS = {
    "fan": (layout_fan, bg_cover),
    "podium": (layout_podium, lambda: bg_glow((22, 14, 18), (120, 52, 22))),
    "fan_dark": (layout_fan, lambda: bg_glow((22, 14, 18), (120, 52, 22))),
    "podium_cover": (layout_podium, bg_cover),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for name, (fn, bg) in LAYOUTS.items():
        img, _box = fn(bg())
        dst = OUT / f"{name}.jpg"
        img.convert("RGB").save(dst, quality=95)
        draw_overlay(img.convert("RGB")).save(OUT / f"_qa_{name}.jpg", quality=85)
        made.append(img.convert("RGB"))
        print(dst)
    sheet = Image.new("RGB", (W * len(made) + 30 * (len(made) - 1), H), "white")
    for k, im in enumerate(made):
        sheet.paste(im, (k * (W + 30), 0))
    sheet.resize((sheet.width // 2, sheet.height // 2)).save(OUT / "_sheet.jpg", quality=88)


def fan_variants() -> None:
    """Для уникальности: раскладка fan, образы в 6 порядках (скрины по позициям — слева 3, центр 4, справа 1)
    → output/1329_slides/s5_inspoy/fan_<образы>.jpg."""
    global SHOTS
    dst_dir = ROOT / "output" / "1329_slides" / "s5_inspoy"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for order in itertools.permutations(("witch", "vamp", "angel")):
        SHOTS = tuple(f"{s}_{look}" for s, look in zip(("screen_3", "screen_4", "screen_1"), order))
        img, _box = layout_fan(bg_cover())
        dst = dst_dir / f"fan_{'_'.join(order)}.jpg"
        img.convert("RGB").save(dst, quality=95)
        print(dst)


if __name__ == "__main__":
    if "--variants" in sys.argv:
        fan_variants()
    else:
        main()
