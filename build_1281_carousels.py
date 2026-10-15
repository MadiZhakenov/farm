#!/usr/bin/env python3
"""
1281 — Global Work, карусель «i provide for my husband and kids but i lost my job…»: 7 слайдов 3:4
(1080×1440) из output/1281_slides/<слайд>/. Тексты — дословно из ТЗ, переносы расставлены вручную по
смыслу (\\n — строка, \\n\\n — отступ между мыслями). Текст TikTok-стилем (белый с обводкой), только
внутри безопасной рамки core/safe_zones (x 180–900, y 6–78 %); кегль — самый крупный, что влезает.

Место текста — мимо лиц, кружек и экранов, для КАЖДОГО кадра:
  fixed  — центр блока по высоте (cy) для всех кадров слайда (+ PER_IMAGE — свой cy у отдельных кадров);
  screen — ищем светлый экран ноутбука и ставим текст в свободное место под ним (или над ним);
  split  — текст делится на части (\\n|\\n) со своими местами: над экраном и под ним (кегль общий).
Где фон — сплошной текст (резюме), под текстом мягкая тёмная подложка. Фото затемняются на 20 %.
Карусели не повторяются, кадры слайда расходуются поровну.

  python build_1281_carousels.py -n 3 --out output/carousels_1281_test --qa
  python build_1281_carousels.py -n 100 --out output/carousels_1281 --flat output/1281_100 --flat-id 1281 --qa
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402
import build_grandma_carousels as G  # noqa: E402
import build_tired_carousels as T  # noqa: E402
from core import renderer as R  # noqa: E402
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402

W, H = 1080, 1440
X0, Y0, X1, Y1 = text_rect(W, H)     # 180, 86, 900, 1123
MAX_W = X1 - X0
SL = ROOT / "output" / "1281_slides"
PX_MAX, PX_MIN = 50, 30
PARA_GAP = 0.45
MARGIN = int(0.025 * H)              # отступ текста от края экрана

# (папка, текст ТЗ с переносами по смыслу, режим, cy, макс. высота блока — доли кадра, подложка)
SLIDES = [
    ("s1_family",
     "i provide\nfor my husband and kids\nbut i lost my job\nthis year and…",
     "fixed", 0.70, 0.16, False),                         # лица сверху — текст на кардигане
    ("s2_morning",
     "…i haven’t told anyone.\n\nevery morning i still get up at 7\nand act like everything is fine\n"
     "so my kids don’t see me scared 😭",
     "fixed", 0.155, 0.18, False),                        # у большинства кадров кружка в середине
    ("s3_laptop",
     "so i did what everyone says:\napply to EVERYTHING.\n\n143 applications. same resume.\n2 replies",
     "screen", None, 0.20, False),
    ("s4_night",
     "every night at 1am:\ncopy, paste, “dear hiring manager.”\n\nthe silence was louder\nthan any rejection",
     "screen", None, 0.20, False),
    ("s5_resume",
     "then i realized\nthe problem wasn’t me.\n\nmy applications were all the same.\nbut tailoring each one\n"
     "took 40 minutes",
     "fixed", 0.50, 0.26, True),                          # фон — сплошной текст резюме
    ("s6_app",                                           # экран посередине: начало над ним, конец — на клавиатуре
     "that’s when i found Global Work 🙌\nit tailors my resume and cover letter\nto every job,\n|\n"
     "and i approve every application\nbefore it goes out.\n\nfor the first time in months\ni felt in control again",
     "split", [(0.115, 0.11), (0.587, 0.135)], None, False),
    ("s7_family",
     "do you think it’s normal\nthat I provide for my family?\n\nmy parents say\nthat’s my husband’s job… 👇",
     "fixed", 0.155, 0.18, False),                        # стена над головами
]
# свой центр текста у отдельных кадров (начало имени файла → cy): кружка сверху — текст ниже
PER_IMAGE = {
    "s2_morning": {"004_": 0.52, "051_": 0.69},
}


def _paras(text: str) -> list[list[str]]:
    return [[A.sanitize_overlay_text(R._normalize_text(ln)) for ln in p.split("\n")] for p in text.split("\n\n")]


def fits(text: str, px: int, max_h: int) -> bool:
    paras = _paras(text)
    font, stroke, adv = R._load_font(px), R.stroke_width_for(px), R.line_advance_for(px)
    widest = max(A._line_width_mixed(ln, font, px, stroke) for p in paras for ln in p)
    h = sum(len(p) for p in paras) * adv + int((len(paras) - 1) * adv * PARA_GAP) + 4 * stroke
    return widest <= MAX_W - 2 * stroke and h <= max_h


def text_block(text: str, max_h: int, px: int | None = None) -> Image.Image:
    """Строки как в тексте (без автопереноса); кегль уменьшается, пока блок не влезет в ширину и высоту."""
    paras = _paras(text)
    if px is None:
        px = next((p for p in range(PX_MAX, PX_MIN - 1, -1) if fits(text, p, max_h)), PX_MIN)
    font, stroke, adv = R._load_font(px), R.stroke_width_for(px), R.line_advance_for(px)
    h = sum(len(p) for p in paras) * adv + int((len(paras) - 1) * adv * PARA_GAP) + 4 * stroke
    img = Image.new("RGBA", (W, h + adv), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 2 * stroke
    for k, p in enumerate(paras):
        for ln in p:
            lw = int(round(A._line_width_mixed(ln, font, px, stroke)))
            A._draw_line_mixed(img, d, (W - lw) // 2, y, ln, font, px, stroke)
            y += adv
        if k < len(paras) - 1:
            y += int(adv * PARA_GAP)
    return img.crop(img.getbbox())


def backdrop(block: Image.Image) -> Image.Image:
    """Мягкая тёмная тень по форме текста — читается на белом листе с мелким шрифтом."""
    pad = 70
    a = Image.new("L", (block.width + 2 * pad, block.height + 2 * pad), 0)
    a.paste(block.getchannel("A"), (pad, pad))
    a = a.filter(ImageFilter.MaxFilter(31)).filter(ImageFilter.GaussianBlur(26)).point(lambda v: int(v * 0.62))
    out = Image.new("RGBA", a.size, (0, 0, 0, 0))
    out.putalpha(a)
    out.alpha_composite(block, (pad, pad))
    return out


def screen_box(bg: Image.Image) -> tuple[int, int] | None:
    """(верх, низ) светлого экрана ноутбука в кадре или None."""
    hsv = cv2.cvtColor(np.asarray(bg), cv2.COLOR_RGB2HSV)
    m = ((hsv[..., 2] > 165) & (hsv[..., 1] < 70)).astype(np.uint8)
    blue = (hsv[..., 0] > 95) & (hsv[..., 0] < 125) & (hsv[..., 1] > 110) & (hsv[..., 2] > 140)
    m = ((m > 0) | blue).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((31, 31), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    if n < 2:
        return None
    k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    if st[k, cv2.CC_STAT_AREA] < 0.05 * W * H:
        return None
    rows = np.where((lab == k).sum(1) > 0.15 * st[k, cv2.CC_STAT_WIDTH])[0]
    return int(rows.min()), int(rows.max())


@lru_cache(maxsize=None)
def block_for(slide: int, max_h: int) -> Image.Image:
    _d, text, _mode, _cy, _mh, shade = SLIDES[slide]
    b = text_block(text, max_h)
    return backdrop(b) if shade else b


def place_split(slide: int) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Текст частями (\n|\n) в свои места, кегль общий — самый крупный, что влезает во все части."""
    _d, text, _mode, spots, _mh, _shade = SLIDES[slide]
    parts = text.split("\n|\n")
    px = next((p for p in range(PX_MAX, PX_MIN - 1, -1)
               if all(fits(t, p, int(mh * H)) for t, (_cy, mh) in zip(parts, spots))), PX_MIN)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    xs, ys = [], []
    for t, (cy, mh) in zip(parts, spots):
        b = text_block(t, int(mh * H), px)
        x, y = (W - b.width) // 2, int(cy * H - b.height / 2)
        y = max(Y0, min(Y1 - b.height, y))
        out.alpha_composite(b, (x, y))
        xs += [x, x + b.width]
        ys += [y, y + b.height]
    return out, (min(xs), min(ys), max(xs), max(ys))


def place(slide: int, bg: Image.Image, name: str) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Слой с текстом для конкретного кадра + рамка текста (без подложки) для проверки."""
    d, _text, mode, cy, mh, shade = SLIDES[slide]
    if mode == "split":
        return place_split(slide)
    max_h = int(mh * H)
    if mode == "screen" and (sb := screen_box(bg)):
        top, bottom = sb
        below = (bottom + MARGIN, Y1)
        above = (Y0, top - MARGIN)
        lo, hi = max(below, above, key=lambda g: g[1] - g[0])
        max_h = min(max_h, hi - lo)
        cy = (lo + hi) / 2 / H
    else:
        for pre, v in PER_IMAGE.get(d, {}).items():
            if name.startswith(pre):
                cy = v
    block = block_for(slide, max_h)
    pad = 70 if shade else 0
    th = block.height - 2 * pad
    y = int(cy * H - th / 2)
    y = max(Y0, min(Y1 - th, y))
    x = (W - (block.width - 2 * pad)) // 2
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(block, (x - pad, y - pad))
    return out, (x, y, x + block.width - 2 * pad, y + th)


def fit_bg(src: Path) -> Image.Image:
    return ImageOps.fit(Image.open(src).convert("RGB"), (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.45))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--darken", type=float, default=0.20)
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_<id>.jpg")
    ap.add_argument("--flat-id", default="")
    ap.add_argument("--qa", action="store_true", help="QA-листы: ВСЕ кадры каждого слайда с текстом и зонами")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    pools = [sorted(f for f in (SL / d).iterdir() if f.is_file() and f.suffix.lower() in (".jpg", ".png")
                    and not f.name.startswith("_")) for d, *_ in SLIDES]
    print("кадров: " + " · ".join(f"{d} {len(p)}" for (d, *_), p in zip(SLIDES, pools)), flush=True)

    # слой текста для каждого кадра: считаем один раз, сразу проверяем безопасную зону
    layers: dict[Path, Image.Image] = {}
    for k, pool in enumerate(pools):
        for src in pool:
            layer, box = place(k, fit_bg(src), src.name)
            bad = check_box(W, H, box)
            if bad:
                raise SystemExit(f"{SLIDES[k][0]}/{src.name}: текст вне безопасной зоны — {bad}")
            layers[src] = layer
            layers[(src, "box")] = box

    if args.qa:
        args.out.mkdir(parents=True, exist_ok=True)
        tw, th = 216, 288
        for k, pool in enumerate(pools):
            sheet = Image.new("RGB", (tw * len(pool), th), "white")
            for i, src in enumerate(pool):
                im = Image.alpha_composite(T.darken(fit_bg(src), args.darken, "uniform").convert("RGBA"),
                                           layers[src]).convert("RGB")
                im = draw_overlay(im)
                ImageDraw.Draw(im).rectangle(layers[(src, "box")], outline=(255, 255, 0), width=5)
                sheet.paste(im.resize((tw, th)), (i * tw, 0))
            sheet.save(args.out / f"_qa_{k + 1}_{SLIDES[k][0]}.jpg", quality=86)

    carousels = G.plan(args.n, pools, random.Random(args.seed))
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, combo in enumerate(carousels, 1):
        d = args.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, src in enumerate(combo, 1):
            bg = T.darken(fit_bg(src), args.darken, "uniform")
            Image.alpha_composite(bg.convert("RGBA"), layers[src]).convert("RGB").save(d / f"{k}.jpg", quality=95)
            if args.flat:
                args.flat.mkdir(parents=True, exist_ok=True)
                suffix = f"_{args.flat_id}" if args.flat_id else ""
                shutil.copy2(d / f"{k}.jpg", args.flat / f"sort_{k}_{i}{suffix}.jpg")
        manifest.append({"carousel": d.name, "frames": [p.name for p in combo]})
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    for k, (d, *_r) in enumerate(SLIDES):
        c = Counter(m["frames"][k] for m in manifest)
        print(f"{d}: {len(c)} кадров, повторов {min(c.values())}–{max(c.values())}")
    print(f"уникальных каруселей: {len({tuple(m['frames']) for m in manifest})} из {len(manifest)}")
    print(f"готово: {len(manifest)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
