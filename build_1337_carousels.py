#!/usr/bin/env python3
"""
1337 — «i'm a stylist and this 4-question test finds your style in 30 seconds» (схема рефа @moodonmute101:
обложка → 4 вопроса A/B → список результатов). 3:4 (1080×1440), шрифт TikTok Sans, оформление «зумерское»:
светлый фон, фото со скруглёнными углами, подписи вариантов — белые TikTok-плашки поверх угла фото.
Тексты ТЗ дословно. Весь текст — внутри безопасной рамки core/safe_zones (x 180–900, y 6–78 %).

Фото вариантов: output/1337_pick/<вариант>/*.jpg (Pinterest, без лиц). Обложка: output/1337_slides/s1_cover/*
(цветные селфи в зеркало из пула 1338, не те, что в 1338; каждая ещё и зеркально).
Слайд-вопрос = пара (фото A, фото B); все пары заранее, карусели — уникальные сочетания (G.plan).

  python build_1337_carousels.py --test                 # слайды 2–6 → output/carousels_1337_test
  python build_1337_carousels.py -n 50 --out output/carousels_1337 --flat output/1337_50 --flat-id 1337
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1281_carousels as B  # noqa: E402  (текст с обводкой и эмодзи для обложки)
import build_grandma_carousels as G  # noqa: E402
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402

W, H = 1080, 1440
X0, Y0, X1, Y1 = text_rect(W, H)
PICK = ROOT / "output" / "1337_pick"
SL = ROOT / "output" / "1337_slides"
WORK = ROOT / "output" / "1337" / "_slides"
TT = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf"
F_BOLD, F_SEMI = TT / "TikTokSans12pt-Bold.ttf", TT / "TikTokSans12pt-SemiBold.ttf"
BG = (243, 241, 238)
INK = (17, 17, 17)

QUESTIONS = [
    ("Outfit:", ("A. oversized and cozy", "outfit_a"), ("B. tailored and sharp", "outfit_b")),
    ("Colors:", ("A. soft neutrals", "color_a"), ("B. one bold color", "color_b")),
    ("Jewelry:", ("A. gold stack", "jewel_a"), ("B. one tiny piece", "jewel_b")),
    ("Shoes:", ("A. sneakers", "shoes_a"), ("B. heels", "shoes_b")),
]
RESULTS = [
    ("AAAA", "Cozy Layered"), ("AAAB", "Soft Romantic"), ("AABA", "Quiet Casual"), ("AABB", "Effortless Chic"),
    ("ABAA", "Colorful Cozy"), ("ABAB", "Playful Glam"), ("ABBA", "Color Pop Minimal"), ("ABBB", "Bold Soft"),
    ("BAAA", "Smart Casual Gold"), ("BAAB", "Classic Glam"), ("BABA", "Clean Minimal"), ("BABB", "Quiet Luxury"),
    ("BBAA", "Bold Smart Casual"), ("BBAB", "Statement Chic"), ("BBBA", "Color Blocker"), ("BBBB", "Sharp Modern"),
]
COVER_TEXT = "i'm a stylist and\nthis 4-question test\nfinds your style\nin 30 seconds 🤍\n\npick A or B.\nyour result is\non the last slide"
PHOTO, PHOTO_X, PHOTO_Y = 540, (W - 540) // 2, (215, 800)
COVER_CY = 0.585                # центр текста обложки: на корпусе, ниже телефона/головы
RADIUS = 34


def font(p: Path, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(p), px)


def rounded(im: Image.Image, r: int) -> Image.Image:
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, im.width - 1, im.height - 1], r, fill=255)
    out = im.convert("RGBA")
    out.putalpha(m)
    return out


def shadow(size: tuple[int, int], r: int, blur: int = 22, alpha: int = 60) -> Image.Image:
    pad = blur * 2
    s = Image.new("RGBA", (size[0] + 2 * pad, size[1] + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(s).rounded_rectangle([pad, pad + 8, pad + size[0], pad + size[1] + 8], r, fill=(0, 0, 0, alpha))
    return s.filter(ImageFilter.GaussianBlur(blur))


def plate(text: str, px: int = 46, fnt: Path = F_SEMI) -> Image.Image:
    """TikTok-плашка: белый скруглённый прямоугольник, чёрный текст."""
    f = font(fnt, px)
    l, t, r, b = f.getbbox(text)
    pw, ph = r - l + 2 * 26, int(px * 1.45)
    im = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, pw - 1, ph - 1], 18, fill=(255, 255, 255, 255))
    d.text((pw / 2, ph / 2), text, font=f, fill=INK + (255,), anchor="mm")
    return im


def question_slide(q: int, a: Path, b: Path, dest: Path) -> list[tuple[int, int, int, int]]:
    title, (la, _ka), (lb, _kb) = QUESTIONS[q]
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    boxes = []
    ft = font(F_BOLD, 82)
    tb = d.textbbox((W / 2, 128), title, font=ft, anchor="mm")
    d.text((W / 2, 128), title, font=ft, fill=INK, anchor="mm")
    boxes.append(tb)
    for src, label, y in ((a, la, PHOTO_Y[0]), (b, lb, PHOTO_Y[1])):
        ph = rounded(ImageOps.fit(Image.open(src).convert("RGB"), (PHOTO, PHOTO), Image.Resampling.LANCZOS), RADIUS)
        sh = shadow((PHOTO, PHOTO), RADIUS)
        img.alpha_composite(sh, (PHOTO_X - 44, y - 44))
        img.alpha_composite(ph, (PHOTO_X, y))
        p = plate(label)
        px, py = max(X0, PHOTO_X - 24), y - p.height // 2 + 6
        img.alpha_composite(p, (px, py))
        boxes.append((px, py, px + p.width, py + p.height))
    for bx in boxes:
        bad = check_box(W, H, bx)
        if bad:
            raise SystemExit(f"{dest.name}: текст вне безопасной зоны {bad}")
    img.convert("RGB").save(dest, quality=95)
    return boxes


def results_slide(dest: Path) -> None:
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    cols, rows = 2, 8
    gap_x, gap_y = 22, 16
    cw = (X1 - X0 - gap_x) // cols
    top, bottom = Y0 + 20, Y1 - 10
    ch = (bottom - top - gap_y * (rows - 1)) // rows
    fc, fn = font(F_BOLD, 40), font(F_SEMI, 33)
    for i, (code, name) in enumerate(RESULTS):
        c, r = i // rows, i % rows
        x, y = X0 + c * (cw + gap_x), top + r * (ch + gap_y)
        d.rounded_rectangle([x, y, x + cw, y + ch], 22, fill=(255, 255, 255))
        d.text((x + 24, y + ch * 0.34), code, font=fc, fill=INK, anchor="lm")
        fsize = 33
        while font(F_SEMI, fsize).getlength(name) > cw - 48 and fsize > 22:
            fsize -= 1
        d.text((x + 24, y + ch * 0.72), name, font=font(F_SEMI, fsize), fill=(90, 90, 90), anchor="lm")
        bad = check_box(W, H, (x, y, x + cw, y + ch))
        if bad:
            raise SystemExit(f"результаты вне безопасной зоны {bad}")
    img.convert("RGB").save(dest, quality=95)


def cover_slide(src: Path, dest: Path, mirror: bool = False) -> None:
    """Цветное селфи в зеркало (лицо за телефоном); текст — на корпусе, ниже телефона/головы."""
    bg = ImageOps.fit(Image.open(src).convert("RGB"), (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    if mirror:
        bg = ImageOps.mirror(bg)
    block = B.text_block(COVER_TEXT, int(0.36 * H), 64)                  # крупнее подписей (B.PX_MAX 50)
    y = max(Y0, min(Y1 - block.height, int(COVER_CY * H - block.height / 2)))
    x = (W - block.width) // 2
    bad = check_box(W, H, (x, y, x + block.width, y + block.height))
    if bad:
        raise SystemExit(f"обложка: текст вне безопасной зоны {bad}")
    out = bg.convert("RGBA")
    out.alpha_composite(block, (x, y))
    out.convert("RGB").save(dest, quality=95)


def prepare() -> list[list[Path]]:
    """Все слайды заранее: обложки, все пары A×B каждого вопроса, результаты. Возвращает пулы по позициям."""
    WORK.mkdir(parents=True, exist_ok=True)
    pools: list[list[Path]] = []
    covers = sorted(p for p in (SL / "s1_cover").glob("*") if p.suffix.lower() in (".jpg", ".png", ".webp")
                    and not p.name.startswith("_")) if (SL / "s1_cover").is_dir() else []
    cv = []
    for c in covers:
        for mirror in (False, True):                                  # + зеркальная — ещё вариант обложки
            dst = WORK / f"s1_{c.stem}{'_m' if mirror else ''}.jpg"
            cover_slide(c, dst, mirror)
            cv.append(dst)
    pools.append(cv)
    for q, (_t, (_la, ka), (_lb, kb)) in enumerate(QUESTIONS):
        pa, pb = sorted((PICK / ka).glob("*.jpg")), sorted((PICK / kb).glob("*.jpg"))
        sl = []
        for a, b in itertools.product(pa, pb):
            dst = WORK / f"s{q + 2}_{a.stem}_{b.stem}.jpg"
            if not dst.exists():
                question_slide(q, a, b, dst)
            sl.append(dst)
        pools.append(sl)
    res = WORK / "s6_results.jpg"
    results_slide(res)
    pools.append([res])
    return pools


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=50)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "carousels_1337_test")
    ap.add_argument("--flat", type=Path)
    ap.add_argument("--flat-id", default="1337")
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--test", action="store_true", help="2 карусели + QA-листы зон")
    a = ap.parse_args()
    pools = prepare()
    print("слайдов в пулах:", [len(p) for p in pools], flush=True)
    if not pools[0]:
        print("обложек нет — собираю без 1-го слайда (тест)")
        pools = pools[1:]
    n = 2 if a.test else a.n
    plan = G.plan(n, pools, random.Random(a.seed))
    a.out.mkdir(parents=True, exist_ok=True)
    first = 1 if len(pools) == 6 else 2
    man = []
    for i, combo in enumerate(plan, 1):
        d = a.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, src in enumerate(combo, first):
            shutil.copy2(src, d / f"{k}.jpg")
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, a.flat / f"sort_{k}_{i}_{a.flat_id}.jpg")
        man.append({"carousel": d.name, "slides": [p.name for p in combo]})
    (a.out / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    if a.test:
        for k, src in enumerate(plan[0], first):
            draw_overlay(Image.open(src).convert("RGB")).save(a.out / f"_qa_{k}.jpg", quality=85)
    print(f"готово: {len(plan)} → {a.out}; уникальных {len({tuple(m['slides']) for m in man})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
