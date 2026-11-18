#!/usr/bin/env python3
"""
1338 — тот же тест стиля, что 1337, но оформление КАК В РЕФЕ (@moodonmute101/photo/7538171477858733367):
  1  ЦВЕТНОЕ фото «как с телефона» (селфи в зеркало, лицо за телефоном — фидбек клиента: не фотосессия, не ч/б)
     + жирный курсив «find your style in 30 sec», внизу мелкая подпись;
  2–5 светло-серый фон, подпись над каждым из двух квадратных фото (жирный курсив), справа большие серифные «A.» / «B.»;
  6  результаты на рваном листе крафт-бумаги со скотчем, 16 строк «AAAA – Cozy Layered» в два столбца.
3:4 (1080×1440), тексты ТЗ дословно, весь текст в безопасной рамке core/safe_zones (x 180–900, y 6–78 %).

«Минимальный уник»: каждая карусель — своё сочетание фото (G.plan) + мелкий разброс на каждом слайде
(оттенок фона ±3, зум/сдвиг фото до 5 %, яркость ±3 %, сдвиг вёрстки ±5 px, свой лист крафта).

Фото: output/1338_pick/<вариант>/*.jpg (свои, не те, что в 1337), обложки: output/1338_slides/s1_cover/*.jpg
(Pinterest, профиль q38_cover_ugc; каждая ещё и зеркально, кроме кадров с надписями), заголовок — в самое
спокойное место кадра: чёрный на светлом ровном фоне, иначе белый с мягкой тенью.

  python build_1338_carousels.py --test                 # 3 карусели + QA-листы → output/carousels_1338_test
  python build_1338_carousels.py -n 64 --out output/carousels_1338 --flat output/1338_64 --flat-id 1338
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_grandma_carousels as G  # noqa: E402
from core.text_shadow import shadow_full_frame  # noqa: E402
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402

W, H = 1080, 1440
X0, Y0, X1, Y1 = text_rect(W, H)
PICK = ROOT / "output" / "1338_pick"
COVERS = ROOT / "output" / "1338_slides" / "s1_cover"
TT = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf"
F_BI = TT / "TikTokSans36pt-BoldItalic.ttf"        # заголовки и подписи — жирный курсив, как в рефе
F_MED = TT / "TikTokSans12pt-Medium.ttf"
F_BOLD = TT / "TikTokSans12pt-Bold.ttf"
F_SERIF = ROOT / "fonts" / "serif" / "Newsreader[opsz,wght].ttf"
BG = (241, 240, 241)
INK = (22, 22, 22)

QUESTIONS = [
    ("Outfit:", ("A.", "oversized and cozy", "outfit_a"), ("B.", "tailored and sharp", "outfit_b")),
    ("Colors:", ("A.", "soft neutrals", "color_a"), ("B.", "one bold color", "color_b")),
    ("Jewelry:", ("A.", "gold stack", "jewel_a"), ("B.", "one tiny piece", "jewel_b")),
    ("Shoes:", ("A.", "sneakers", "shoes_a"), ("B.", "heels", "shoes_b")),
]
RESULTS = [
    ("AAAA", "Cozy Layered"), ("AAAB", "Soft Romantic"), ("AABA", "Quiet Casual"), ("AABB", "Effortless Chic"),
    ("ABAA", "Colorful Cozy"), ("ABAB", "Playful Glam"), ("ABBA", "Color Pop Minimal"), ("ABBB", "Bold Soft"),
    ("BAAA", "Smart Casual Gold"), ("BAAB", "Classic Glam"), ("BABA", "Clean Minimal"), ("BABB", "Quiet Luxury"),
    ("BBAA", "Bold Smart Casual"), ("BBAB", "Statement Chic"), ("BBBA", "Color Blocker"), ("BBBB", "Sharp Modern"),
]
COVER_TITLE = "find your style\nin 30 sec"                      # две строки по смыслу, вверху кадра над головой
COVER_NOTE = "i'm a stylist. pick A or B.\nresult on the last slide"
PHOTO = 470
PHOTO_X = X0 + 10                # +10: курсив и сдвиг ±5 не вылезают за рамку
LABEL_Y = (165, 725)            # верх подписи над фото A / B (низ фото B уходит под интерфейс — как в рефе, там не текст)
TITLE_Y = 78
NO_MIRROR = {"ugc_021.jpg"}       # в кадре надпись (цифры на свитшоте) — зеркалить нельзя
TITLE_PX = 94                   # заголовок обложки (в рефе ~ 80 px на 1440)


def font(p: Path, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(p), px)


def serif(px: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(F_SERIF), px)
    f.set_variation_by_axes([300, 72])
    return f


def checked(boxes: list[tuple[int, int, int, int]], what: str) -> None:
    for bx in boxes:
        bad = check_box(W, H, bx)
        if bad:
            raise SystemExit(f"{what}: текст вне безопасной зоны {bad} {bx}")


def jitter_photo(src: Path, size: tuple[int, int], rng: random.Random, gray: bool = False) -> Image.Image:
    """Кадрирование с мелким случайным зумом/сдвигом и яркостью — «минимальный уник»."""
    im = Image.open(src).convert("RGB")
    if gray:
        im = ImageOps.grayscale(im).convert("RGB")
    z = rng.uniform(1.0, 1.05)
    cx, cy = rng.uniform(0.47, 0.53), rng.uniform(0.47, 0.53)
    tw, th = int(size[0] * z), int(size[1] * z)
    big = ImageOps.fit(im, (tw, th), Image.Resampling.LANCZOS, centering=(0.5, 0.45 if gray else 0.5))
    x0, y0 = int((tw - size[0]) * cx * 2 / 2), int((th - size[1]) * cy * 2 / 2)
    out = big.crop((x0, y0, x0 + size[0], y0 + size[1]))
    return ImageEnhance.Brightness(out).enhance(rng.uniform(0.97, 1.03))


def bg_color(rng: random.Random) -> tuple[int, int, int]:
    d = rng.randint(-3, 3)
    return tuple(max(0, min(255, c + d + rng.randint(-1, 1))) for c in BG)


# --- слайд 1 ------------------------------------------------------------------------------------------------
def calm_spot(g: np.ndarray, w: int, h: int, ys: range, xs: tuple[int, ...]) -> tuple[int, int]:
    """Место под текст на ФОНЕ, а не на девушке: фон = яркость как у краёв кадра; минимум доли «не фона» и разброса."""
    border = np.concatenate([g[:, :40].ravel(), g[:, -40:].ravel()])
    bg = (np.abs(g - np.median(border)) < 22).astype(float)
    best = None
    for y in ys:
        for x in xs:
            score = (1 - bg[y:y + h, x:x + w].mean()) * 100 + g[y:y + h, x:x + w].std() * 0.2
            if best is None or score < best[0]:
                best = (score, x, y)
    return best[1], best[2]


def cover_slide(src: tuple[Path, bool], rng: random.Random) -> tuple[Image.Image, list]:
    path, flip = src
    img = jitter_photo(path, (W, H), rng)
    if flip:                                                          # зеркало — ещё вариант обложки
        img = ImageOps.mirror(img)
    g = np.asarray(img.convert("L")).astype(float)
    ft = font(F_BI, TITLE_PX)
    lines = COVER_TITLE.split("\n")
    lead = int(TITLE_PX * 0.98)
    th = lead * len(lines)
    tw = max(int(ft.getlength(l)) for l in lines) + 12
    # верх кадра (над головой в зеркальном селфи): слева / по центру / справа — где спокойнее
    xs = (X0 + 4, (W - tw) // 2, X1 - tw - 4)
    tx, ty = calm_spot(g, tw, th, range(Y0 + 6, Y0 + 130, 12), xs)
    ty += rng.randint(-5, 5)
    zone = g[ty:ty + th, tx:tx + tw]
    dark_ink = zone.mean() > 175 and zone.std() < 28
    ink = INK if dark_ink else (255, 255, 255)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    boxes = []
    x, anchor = {xs[0]: (tx + 4, "la"), xs[1]: (W // 2, "ma"), xs[2]: (tx + tw - 4, "ra")}[tx]
    for i, ln in enumerate(lines):
        y = ty + i * lead
        d.text((x, y), ln, font=ft, fill=ink, anchor=anchor)
        boxes.append(d.textbbox((x, y), ln, font=ft, anchor=anchor))
    if not dark_ink:
        layer = shadow_full_frame(layer, blur=7, opacity=0.6, offset=(0, 3), grow=2)
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

    # мелкая подпись внизу по центру — на полупрозрачной светлой плашке, читается на любом кадре
    fn = font(F_MED, 31)
    note_lines = COVER_NOTE.split("\n")
    nw = max(int(fn.getlength(l)) for l in note_lines)
    ny = Y1 - 2 * 42 - 24 + rng.randint(-4, 4)
    pad = (22, 12)
    pl = (W // 2 - nw // 2 - pad[0], ny - pad[1], W // 2 + nw // 2 + pad[0], ny + 2 * 42 + pad[1] - 6)
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(over).rounded_rectangle(pl, 18, fill=(250, 250, 250, 200))
    img = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(note_lines):
        p = (W / 2, ny + i * 42)
        d.text(p, ln, font=fn, fill=INK, anchor="ma")
        boxes.append(d.textbbox(p, ln, font=fn, anchor="ma"))
    boxes.append(pl)
    checked(boxes, f"обложка {path.name}")
    return img, boxes


# --- слайды 2–5 ---------------------------------------------------------------------------------------------
def question_slide(q: int, a: Path, b: Path, rng: random.Random) -> tuple[Image.Image, list]:
    title, (la, ta, _ka), (lb, tb, _kb) = QUESTIONS[q]
    img = Image.new("RGB", (W, H), bg_color(rng))
    d = ImageDraw.Draw(img)
    dx, dy = rng.randint(-5, 5), rng.randint(-5, 5)
    boxes = []
    ftit = font(F_BI, 64)
    d.text((PHOTO_X + dx, TITLE_Y + dy), title, font=ftit, fill=INK, anchor="la")
    boxes.append(d.textbbox((PHOTO_X + dx, TITLE_Y + dy), title, font=ftit, anchor="la"))
    flab, fab = font(F_BI, 42), serif(132)
    for src, letter, label, ly in ((a, la, ta, LABEL_Y[0]), (b, lb, tb, LABEL_Y[1])):
        d.text((PHOTO_X + dx, ly + dy), label, font=flab, fill=INK, anchor="la")
        boxes.append(d.textbbox((PHOTO_X + dx, ly + dy), label, font=flab, anchor="la"))
        py = ly + dy + 56
        img.paste(jitter_photo(src, (PHOTO, PHOTO), rng), (PHOTO_X + dx, py))
        lx, lyc = (PHOTO_X + dx + PHOTO + X1) // 2, py + PHOTO // 2     # по центру между фото и краем рамки
        d.text((lx, lyc), letter, font=fab, fill=INK, anchor="mm")
        boxes.append(d.textbbox((lx, lyc), letter, font=fab, anchor="mm"))
    checked(boxes, f"вопрос {q + 1}")
    return img, boxes


# --- слайд 6: крафт ------------------------------------------------------------------------------------------
def kraft_card(size: tuple[int, int], rng: random.Random) -> Image.Image:
    """Лист крафт-бумаги с рваными краями и светлой каймой волокон (RGBA)."""
    w, h = size
    nr = np.random.default_rng(rng.randint(0, 2**31))
    fine = Image.fromarray(np.uint8(np.clip(128 + nr.normal(0, 40, (h, w)), 0, 255))).filter(ImageFilter.GaussianBlur(0.8))
    coarse = Image.fromarray(np.uint8(np.clip(128 + nr.normal(0, 60, (h // 16, w // 16)), 0, 255))).resize(
        (w, h), Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(6))
    tex = (np.asarray(fine, float) - 128) * 0.10 + (np.asarray(coarse, float) - 128) * 0.16
    base = np.array([176, 152, 128], float) + rng.uniform(-4, 4)
    paper = np.clip(base[None, None, :] + tex[..., None] * np.array([1.0, 0.9, 0.8]), 0, 255).astype(np.uint8)
    card = Image.fromarray(paper, "RGB")
    fib = ImageDraw.Draw(card, "RGBA")                                # волокна
    for _ in range(260):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        ang, ln = rng.uniform(0, np.pi), rng.uniform(6, 22)
        c = (205, 186, 160, 70) if rng.random() < 0.6 else (120, 98, 76, 60)
        fib.line([(x, y), (x + ln * np.cos(ang), y + ln * np.sin(ang))], fill=c, width=1)

    def torn(inset: int, amp: float) -> list[tuple[float, float]]:
        pts = []
        step = 7
        wob = lambda: rng.uniform(-amp, amp)  # noqa: E731
        for x in range(inset, w - inset, step):
            pts.append((x, inset + wob()))
        for y in range(inset, h - inset, step):
            pts.append((w - inset + wob(), y))
        for x in range(w - inset, inset, -step):
            pts.append((x, h - inset + wob()))
        for y in range(h - inset, inset, -step):
            pts.append((inset + wob(), y))
        return pts

    rim = Image.new("L", (w, h), 0)
    ImageDraw.Draw(rim).polygon(torn(6, 6), fill=255)
    core = Image.new("L", (w, h), 0)
    ImageDraw.Draw(core).polygon(torn(14, 5), fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(Image.new("RGB", (w, h), (214, 200, 178)), (0, 0), rim)  # светлая рваная кайма
    out.paste(card, (0, 0), core)
    return out


def tape(rng: random.Random) -> Image.Image:
    w, h = 250, 74
    t = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pts = [(0, rng.uniform(0, 6))] + [(x, rng.uniform(-3, 3)) for x in range(10, w, 12)] + [(w, rng.uniform(0, 6))]
    pts += [(w - rng.uniform(0, 6), y) for y in range(8, h, 9)]
    pts += [(x, h - rng.uniform(0, 4)) for x in range(w, 0, -12)] + [(rng.uniform(0, 6), y) for y in range(h, 0, -9)]
    ImageDraw.Draw(t).polygon(pts, fill=(232, 224, 205, 185))
    return t.rotate(rng.uniform(-4, 4), Image.Resampling.BICUBIC, expand=True)


def results_slide(rng: random.Random) -> tuple[Image.Image, list]:
    img = Image.new("RGBA", (W, H), bg_color(rng) + (255,))
    cw, ch = 780, 1000
    cx0 = (W - cw) // 2 + rng.randint(-5, 5)
    cy0 = 110 + rng.randint(-5, 5)
    card = kraft_card((cw, ch), rng)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    a = Image.new("L", (W, H), 0)
    a.paste(card.getchannel("A").point(lambda v: 60 if v else 0), (cx0 + 6, cy0 + 12))
    sh.putalpha(a.filter(ImageFilter.GaussianBlur(14)))
    img.alpha_composite(sh)
    img.alpha_composite(card, (cx0, cy0))
    tp = tape(rng)
    img.alpha_composite(tp, (cx0 + cw // 2 - tp.width // 2, cy0 - tp.height // 2 + 6))
    d = ImageDraw.Draw(img)
    fc, fn = font(F_BOLD, 37), font(F_BOLD, 33)
    ink = (38, 28, 20)
    boxes = []
    top, row = cy0 + 110, 104
    cols = (cx0 + cw * 0.27, cx0 + cw * 0.73)
    for i, (code, name) in enumerate(RESULTS):
        c, r = i // 8, i % 8
        x, y = cols[c], top + r * row
        d.text((x, y), f"{code} –", font=fc, fill=ink, anchor="ma")
        d.text((x, y + 45), name, font=fn, fill=ink, anchor="ma")
        boxes.append(d.textbbox((x, y), f"{code} –", font=fc, anchor="ma"))
        boxes.append(d.textbbox((x, y + 45), name, font=fn, anchor="ma"))
    checked(boxes, "результаты")
    return img.convert("RGB"), boxes


# --- сборка ---------------------------------------------------------------------------------------------------
def pools() -> list[list]:
    covers = sorted(p for p in COVERS.glob("*") if p.suffix.lower() in (".jpg", ".png", ".webp") and not p.name.startswith("_"))
    out: list[list] = [[(c, f) for c in covers for f in (False, True) if not (f and c.name in NO_MIRROR)]]  # + зеркальные
    for _t, (_la, _ta, ka), (_lb, _tb, kb) in QUESTIONS:
        pa, pb = sorted((PICK / ka).glob("*.jpg")), sorted((PICK / kb).glob("*.jpg"))
        out.append(list(itertools.product(pa, pb)))
    return out


def render(combo: list, seed: int) -> list[Image.Image]:
    rng = random.Random(seed)
    slides = [cover_slide(combo[0], rng)[0]]
    for q, (a, b) in enumerate(combo[1:]):
        slides.append(question_slide(q, a, b, rng)[0])
    slides.append(results_slide(rng)[0])
    return slides


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=64)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "carousels_1338_test")
    ap.add_argument("--flat", type=Path)
    ap.add_argument("--flat-id", default="1338")
    ap.add_argument("--seed", type=int, default=1338)
    ap.add_argument("--test", action="store_true", help="3 карусели + QA-листы зон + превью")
    a = ap.parse_args()
    pl = pools()
    print("в пулах:", [len(p) for p in pl], flush=True)
    n = 3 if a.test else a.n
    plan = G.plan(n, pl, random.Random(a.seed))
    a.out.mkdir(parents=True, exist_ok=True)
    man = []
    for i, combo in enumerate(plan, 1):
        d = a.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        slides = render(combo, a.seed * 1000 + i)
        for k, im in enumerate(slides, 1):
            im.save(d / f"{k}.jpg", quality=95)
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                im.save(a.flat / f"sort_{k}_{i}_{a.flat_id}.jpg", quality=95)
        man.append({"carousel": d.name, "cover": combo[0][0].name + (" (mirror)" if combo[0][1] else ""),
                    "pairs": [[x.name, y.name] for x, y in combo[1:]]})
        if i % 10 == 0:
            print(f"  {i}/{n}", flush=True)
    (a.out / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    if a.test:
        first = sorted((a.out / "001").glob("*.jpg"))
        for f in first:
            draw_overlay(Image.open(f).convert("RGB")).save(a.out / f"_qa_{f.stem}.jpg", quality=85)
        strip = Image.new("RGB", (1100 * 6, 1460 * len(plan)), "white")
        for r in range(len(plan)):
            for k in range(6):
                strip.paste(Image.open(a.out / f"{r + 1:03d}" / f"{k + 1}.jpg"), (k * 1100, r * 1460))
        strip.resize((strip.width // 4, strip.height // 4)).save(a.out / "_preview.jpg", quality=90)
    print(f"готово: {len(plan)} → {a.out}; уникальных {len({json.dumps(m) for m in man})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
