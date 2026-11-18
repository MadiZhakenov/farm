#!/usr/bin/env python3
"""
1340 — Inspoy, «5 outfits that make you look 10 years younger»: 5 слайдов 3:4 (1080×1440), тест 6 текстов обложки (A–F).
  1  селфи девушки (output/1340_slides/s1) + текст обложки A–F под подбородком
  2–4 образ на кровати (одна кровать, разные кадры) + заголовок вверху над вещами
  5  девушка в образе 1 (красное пальто) + телефон с настоящим скрином Inspoy (Work / Date Night / Night Out)
Тексты ТЗ дословно, переносы по смыслу, TikTok-шрифт с обводкой; весь текст в рамке core/safe_zones (x 180–900, y 6–78 %).
Кадры: по несколько вариантов на слайд (серии Flow) + 3 скрина Inspoy → уникальные сочетания (G.plan); тексты обложки
по кругу (64 → по 10–11 на текст); плюс «минимальный уник»: зум/сдвиг кадра до 4 %, яркость ±3 %, сдвиг текста ±6 px.

  python build_1340_carousels.py --test          # 6 каруселей (A–F) + QA → output/carousels_1340_test
  python build_1340_carousels.py -n 64 --out output/carousels_1340 --flat output/1340_64
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
SL = ROOT / "output" / "1340_slides"
SCR = SL / "s5_screens"
C.B.PX_MAX = 72                           # крупнее подписей по умолчанию (50)

COVERS = {
    "A": "5 outfits that make you look\n10 years younger.\n\n(the last one is a cheat code)",
    "B": "5 outfits that make you look\n10 years younger.\n\n(the last one is unfair)",
    "C": "5 outfits that make you look\n10 years younger.\n\n(the last one hits different)",
    "D": "5 outfits that make you look\nfresher and more put together.\n\n(the last one is a cheat code)",
    "E": "5 outfits for women over 30.\n\n(the last one is a cheat code)",
    "F": "if you're 30+ and tired of black,\ntry these 5 outfits.\n\n(the last one is a cheat code)",
}
LOOKS = [  # папка, заголовок, центр заголовка по y (доля кадра) — над вещами, на подушке/простыне
    ("s2", "1. Enters the room", 0.105),
    ("s3", "2. Plot twist", 0.105),
    ("s4", "3. Walks in slow motion", 0.098),
]
S5_TEXT = "tried them all on\nin Inspoy:\nOutfit Maker, Planner"
COVER_CY, COVER_MH = 0.585, 0.27          # под подбородком, на груди
S5_CY, S5_MH = 0.36, 0.165                # под подбородком, над телефоном
PHONE_H, PHONE_CX, PHONE_TOP, PHONE_ANGLE = 720, 742, 652, -4   # карточка с образом — выше UI TikTok


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


def put_text(img: Image.Image, text: str, cy: float, mh: float, rng: random.Random, what: str) -> tuple:
    block = C.block_for(text, int(mh * H), X1 - X0)
    x = (W - block.width) // 2 + rng.randint(-6, 6)
    y = int(cy * H - block.height / 2) + rng.randint(-6, 6)
    x, y = max(X0, min(X1 - block.width, x)), max(Y0, min(Y1 - block.height, y))
    box = (x, y, x + block.width, y + block.height)
    bad = check_box(W, H, box)
    if bad:
        raise SystemExit(f"{what}: текст вне безопасной зоны {bad}")
    img.alpha_composite(block, (x, y))
    return box


def render(combo: list[Path], cover_key: str, seed: int) -> list[Image.Image]:
    """combo: s1, s2, s3, s4, s5, скрин."""
    rng = random.Random(seed)
    out = []
    im = jitter_bg(combo[0], rng).convert("RGBA")
    put_text(im, COVERS[cover_key], COVER_CY, COVER_MH, rng, f"обложка {cover_key}")
    out.append(im)
    for src, (_folder, title, cy) in zip(combo[1:4], LOOKS):
        im = jitter_bg(src, rng).convert("RGBA")
        put_text(im, title, cy, 0.075, rng, src.name)
        out.append(im)
    im = jitter_bg(combo[4], rng).convert("RGBA")
    ph = K.phone(combo[5], PHONE_H)
    K.drop_any(ph, im, PHONE_CX + rng.randint(-6, 6), PHONE_TOP + rng.randint(-6, 6),
               angle=PHONE_ANGLE + rng.uniform(-1, 1), alpha=120)
    put_text(im, S5_TEXT, S5_CY, S5_MH, rng, "слайд 5")
    out.append(im)
    return [s.convert("RGB") for s in out]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=64)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "carousels_1340_test")
    ap.add_argument("--flat", type=Path)
    ap.add_argument("--flat-id", default="1340")
    ap.add_argument("--seed", type=int, default=1340)
    ap.add_argument("--test", action="store_true", help="6 каруселей (по одной на текст A–F) + QA-листы")
    a = ap.parse_args()
    n = len(COVERS) if a.test else a.n
    keys = list(COVERS)
    pools = [pool(SL / f"s{k}") for k in range(1, 6)] + [[p for p in pool(SCR) if p.suffix == ".png"]]
    print("кадров:", [len(p) for p in pools], flush=True)
    plan = G.plan(n, pools, random.Random(a.seed))
    a.out.mkdir(parents=True, exist_ok=True)
    man = []
    for i, combo in enumerate(plan, 1):
        key = keys[(i - 1) % len(keys)]
        d = a.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, im in enumerate(render(combo, key, a.seed * 1000 + i), 1):
            im.save(d / f"{k}.jpg", quality=95)
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                im.save(a.flat / f"sort_{k}_{i}_{a.flat_id}.jpg", quality=95)
        man.append({"carousel": d.name, "cover_text": key, "frames": [p.name for p in combo]})
    (a.out / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    if a.test:
        for k in range(1, 6):
            draw_overlay(Image.open(a.out / "001" / f"{k}.jpg").convert("RGB")).save(a.out / f"_qa_{k}.jpg", quality=85)
        covers = Image.new("RGB", (1100 * n, 1440), "white")
        for i in range(n):
            covers.paste(Image.open(a.out / f"{i + 1:03d}" / "1.jpg"), (i * 1100, 0))
        covers.resize((covers.width // 4, covers.height // 4)).save(a.out / "_covers.jpg", quality=90)
        strip = Image.new("RGB", (1100 * 5, 1440), "white")
        for k in range(5):
            strip.paste(Image.open(a.out / "001" / f"{k + 1}.jpg"), (k * 1100, 0))
        strip.resize((strip.width // 4, strip.height // 4)).save(a.out / "_preview_001.jpg", quality=90)
    print(f"готово: {n} → {a.out}; уникальных {len({tuple(m['frames']) + (m['cover_text'],) for m in man})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
