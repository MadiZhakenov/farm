#!/usr/bin/env python3
"""
1341 — Inspoy, «5 outfits I wore for my husband»: 6 слайдов 3:4 (1080×1440), все 6 хуков обложки по кругу.
  1  она с мужем (яркие цвета) + хук под подбородком
  2–5 Day 1–4: она в полный рост в образах 1–4, подпись на свободном месте кадра
  6  Day 5: он на колене с кольцом, она в шоке; внизу «I planned all of these in Inspoy…» + телефон с настоящим скрином
Тексты ТЗ дословно, переносы по смыслу, TikTok-шрифт с обводкой; весь текст в рамке core/safe_zones (x 180–900, y 6–78 %).
Кадры: по несколько вариантов на слайд (серии Flow) + 3 скрина Inspoy → уникальные сочетания (G.plan), хуки по кругу;
плюс «минимальный уник»: зум/сдвиг кадра до 4 %, яркость ±3 %, сдвиг текста ±6 px.

  python build_1341_carousels.py --test          # 6 каруселей (по хуку) + QA → output/carousels_1341_test
  python build_1341_carousels.py -n 64 --out output/carousels_1341 --flat output/1341_64
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1283_carousels as C  # noqa: E402  (block_for — TikTok-текст с обводкой, подбор кегля)
import build_grandma_carousels as G  # noqa: E402  (plan — уникальные сочетания кадров)
import make_1329_s5_collage as K  # noqa: E402  (phone, drop_any — телефон с тенью)
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402

W, H = 1080, 1440
X0, Y0, X1, Y1 = text_rect(W, H)
SL = ROOT / "output" / "1341_slides"
SCREENS = SL / "s6_screens"
C.B.PX_MAX = 72                           # крупнее подписей по умолчанию (50)

HOOKS = [
    "5 outfits I wore for my husband.\n\n(after the last one\nhe proposed again)",
    "my husband and I\ngot a second wedding\nbecause of these 5 outfits.\n\n(the last one did it)",
    "5 outfits.\n\n(after number 5 my husband said\n\"marry me again\")",
    "I dressed up for my husband\nfor 5 days.\n\n(day 5 he got down on one knee)",
    "5 outfits that made my husband\nfall in love with me again.\n\n(spoiler: the last one)",
    "married 9 years.\n\n(after the last outfit he asked me\nto marry him again)",
]
# слайд: (папка, текст, cx, cy, ширина, высота блока) — доли кадра; место выбрано по свободной зоне каждого кадра
DAYS = [
    ("s2", "Day 1. He noticed.", 0.5, 0.125, 0.667, 0.08),               # над головой, по фасаду
    ("s3", "Day 2.\nHe stopped scrolling.", 0.5, 0.70, 0.667, 0.15),     # на кожаной юбке
    ("s4", "Day 3.\nHe booked a table.", 0.5, 0.155, 0.667, 0.15),       # ночное небо над головой
    ("s5", "Day 4.\nHe couldn't stop smiling.", 0.5, 0.70, 0.667, 0.15), # на джинсах и переходе
]
S6_TITLE = ("Day 5. 💍\n\"marry me again\"", 0.5, 0.125, 0.667, 0.15)   # над ними, по тёмным балкам
S6_BOTTOM = ("I planned all of these\nin Inspoy:\nOutfit Maker, Planner", 0.665, 0.70, 0.43, 0.16)  # внизу справа
PHONE_H, PHONE_CX, PHONE_TOP, PHONE_ANGLE = 690, 262, 712, 5            # внизу слева, на его ногах; кольцо видно
HOOK_CY, HOOK_MH = 0.70, 0.165             # под подбородком, на красном топе / синей рубашке


def pool(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".jpg", ".png", ".webp")
                  and not p.name.startswith("_"))


def jitter_bg(src: Path, rng: random.Random) -> Image.Image:
    im = ImageOps.fit(Image.open(src).convert("RGB"), (W, H), Image.Resampling.LANCZOS)
    z = rng.uniform(1.0, 1.04)
    big = im.resize((round(W * z), round(H * z)), Image.Resampling.LANCZOS)
    x = round((big.width - W) * rng.uniform(0, 1))
    y = round((big.height - H) * rng.uniform(0, 1))
    out = big.crop((x, y, x + W, y + H))
    return ImageEnhance.Brightness(out).enhance(rng.uniform(0.97, 1.03))


def put_text(img: Image.Image, text: str, cx: float, cy: float, mw: float, mh: float, rng: random.Random, what: str) -> tuple:
    block = C.block_for(text, int(mh * H), int(mw * W))
    x = int(cx * W - block.width / 2) + rng.randint(-6, 6)
    y = int(cy * H - block.height / 2) + rng.randint(-6, 6)
    x, y = max(X0, min(X1 - block.width, x)), max(Y0, min(Y1 - block.height, y))
    box = (x, y, x + block.width, y + block.height)
    bad = check_box(W, H, box)
    if bad:
        raise SystemExit(f"{what}: текст вне безопасной зоны {bad}")
    img.alpha_composite(block, (x, y))
    return box


def render(combo: list[Path], hook: int, seed: int) -> list[Image.Image]:
    """combo: s1, s2, s3, s4, s5, s6, скрин."""
    rng = random.Random(seed)
    out = []
    im = jitter_bg(combo[0], rng).convert("RGBA")
    put_text(im, HOOKS[hook], 0.5, HOOK_CY, (X1 - X0) / W, HOOK_MH, rng, f"хук {hook + 1}")
    out.append(im)
    for src, (_folder, text, cx, cy, mw, mh) in zip(combo[1:5], DAYS):
        im = jitter_bg(src, rng).convert("RGBA")
        put_text(im, text, cx, cy, mw, mh, rng, src.name)
        out.append(im)
    im = jitter_bg(combo[5], rng).convert("RGBA")
    ph = K.phone(combo[6], PHONE_H)
    K.drop_any(ph, im, PHONE_CX + rng.randint(-6, 6), PHONE_TOP + rng.randint(-6, 6),
               angle=PHONE_ANGLE + rng.uniform(-1, 1), alpha=120)
    put_text(im, *S6_TITLE, rng, "слайд 6, заголовок")
    put_text(im, *S6_BOTTOM, rng, "слайд 6, низ")
    out.append(im)
    return [s.convert("RGB") for s in out]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=64)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "carousels_1341_test")
    ap.add_argument("--flat", type=Path)
    ap.add_argument("--flat-id", default="1341")
    ap.add_argument("--seed", type=int, default=1341)
    ap.add_argument("--test", action="store_true", help="6 каруселей (по одной на хук) + QA-листы")
    a = ap.parse_args()
    n = len(HOOKS) if a.test else a.n
    pools = [pool(SL / f"s{k}") for k in range(1, 7)] + [pool(SCREENS)]
    print("кадров:", [len(p) for p in pools], flush=True)
    plan = G.plan(n, pools, random.Random(a.seed))
    a.out.mkdir(parents=True, exist_ok=True)
    man = []
    for i, combo in enumerate(plan, 1):
        hook = (i - 1) % len(HOOKS)
        d = a.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, im in enumerate(render(combo, hook, a.seed * 1000 + i), 1):
            im.save(d / f"{k}.jpg", quality=95)
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                im.save(a.flat / f"sort_{k}_{i}_{a.flat_id}.jpg", quality=95)
        man.append({"carousel": d.name, "hook": hook + 1, "frames": [p.name for p in combo]})
    (a.out / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    if a.test:
        for k in range(1, 7):
            draw_overlay(Image.open(a.out / "001" / f"{k}.jpg").convert("RGB")).save(a.out / f"_qa_{k}.jpg", quality=85)
        covers = Image.new("RGB", (1100 * n, 1440), "white")
        for i in range(n):
            covers.paste(Image.open(a.out / f"{i + 1:03d}" / "1.jpg"), (i * 1100, 0))
        covers.resize((covers.width // 4, covers.height // 4)).save(a.out / "_covers.jpg", quality=90)
        strip = Image.new("RGB", (1100 * 6, 1440), "white")
        for k in range(6):
            strip.paste(Image.open(a.out / "001" / f"{k + 1}.jpg"), (k * 1100, 0))
        strip.resize((strip.width // 4, strip.height // 4)).save(a.out / "_preview_001.jpg", quality=90)
    print(f"готово: {n} → {a.out}; уникальных {len({tuple(m['frames']) + (m['hook'],) for m in man})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
