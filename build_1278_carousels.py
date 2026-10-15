#!/usr/bin/env python3
"""
1278 — «couldn't switch my brain off at night» (Magic Sort, реф TikTok @joey.growth): 6 слайдов
1080×1440 (3:4, как реф). Слайд 1 — селфи, 2–6 — от первого лица (ИИ-фото пользователя) из
output/1278_slides/<версия>/sN_*. Текст — TikTok-стиль (build_grandma_carousels.text_block, белый с
обводкой, без автопереноса), у каждого слайда своя высота (POS), чтобы не закрывать лицо/игру,
и всё внутри безопасной зоны интерфейса TikTok/Instagram/YouTube (SAFE_*).
Версия bright — без затемнения (сочные цвета, как реф). Карусели не повторяются, кадры
каждого слайда расходуются поровну.

  python build_1278_carousels.py -n 3 --out output/carousels_1278_test
  python build_1278_carousels.py -n 100 --out output/carousels_1278_bright --flat output/1278_100_bright
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

import build_grandma_carousels as G
import build_tired_carousels as T

ROOT = Path(__file__).resolve().parent
W, H = G.W, G.H
SLIDES_DIR = ROOT / "output" / "1278_slides"
ID = "1278"

# ---- безопасная зона для 3:4 (TikTok фото-режим, Инста, image posts YouTube Shorts) ----
# Замер официального макета фото-режима TikTok (newsroom, фото 3:4): фото во всю ширину сразу под
# вкладками, ник/подпись/музыка/точки — под фото; колонка аватар/лайк/коммент/сохранить накрывает
# правые ~14% ширины (x ≥ 926 из 1080) от ~46% высоты фото до низа. Длинная подпись в TikTok и
# полноэкранный просмотр Инсты/Shorts залезают на низ фото → нижние ~20% тоже не трогаем.
# Текст: полоса 6–78% высоты, ширина ≤ 720 px по центру (x 180–900) — мимо колонки кнопок.
SAFE_TOP, SAFE_BOT, SAFE_W = 0.06, 0.78, 720
T.MAX_W = SAFE_W

# (папка, текст); \n — перенос по смыслу
SLIDES = [
    ("s1_selfie", "i couldn’t switch my brain off\nat night for months and this\nmade all the difference…"),
    ("s2_stickers", "every night: lie down,\nbrain starts a meeting,\n17 tabs open 😭"),
    ("s3_mirror", "i tried the usual stuff.\nphone, scrolling,\none more video.\nmy brain stayed loud"),
    ("s4_table", "then i found something\nthat gives my hands a job\nand my brain a break"),
    ("s5_balcony", "just sorting colors for 5 min.\nno timer, no pressure.\nMagic Sort 🧩\n"
                   "it’s weirdly quiet\nin my head after"),
    ("s6_coffee", "how long did you doomscroll\nlast night? be honest 👇"),
]
# центр текста по высоте (доля кадра) для каждой версии: мимо лица, игры и стакана, внутри SAFE-полосы
POS = {
    "bright":  [0.69, 0.25, 0.15, 0.20, 0.16, 0.14],
    "evening": [0.69, 0.25, 0.15, 0.27, 0.16, 0.21],
}


def layer_for(text: str, cy: float) -> Image.Image:
    block = G.text_block(text)
    y = int(cy * H - block.height / 2)
    y = max(int(SAFE_TOP * H), min(int(SAFE_BOT * H) - block.height, y))
    return G.place(block, y)


# зерно по уровням из теста output/1278_grain_test (σ шума из 255); в итоге решили без зерна (0)
GRAIN_LEVELS = {0: 0, 1: 5, 2: 9, 3: 13, 4: 18, 5: 24}


def add_grain(img: Image.Image, sigma: float, rng: np.random.Generator) -> Image.Image:
    """Монохромное плёночное зерно ~1.5 px, чуть сильнее в средних тонах; только на фото, не на текст."""
    if sigma <= 0:
        return img
    a = np.asarray(img).astype(np.float32)
    n = cv2.GaussianBlur(rng.normal(0, 1, a.shape[:2]).astype(np.float32), (0, 0), 0.7)
    n /= n.std()
    luma = a.mean(2, keepdims=True) / 255
    w = 0.55 + 1.8 * luma * (1 - luma)
    return Image.fromarray(np.clip(a + n[..., None] * sigma * w, 0, 255).astype(np.uint8))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", choices=sorted(POS), default="bright", help="подпапка output/1278_slides/<версия>")
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--darken", type=float, default=0.0)
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_1278.jpg")
    ap.add_argument("--grain", type=int, choices=sorted(GRAIN_LEVELS), default=0, help="уровень зерна 0–5")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    src = SLIDES_DIR / args.version
    pools = [sorted(f for f in (src / d).iterdir() if f.suffix.lower() in (".jpg", ".png") and not f.name.startswith("_"))
             for d, *_ in SLIDES]
    print("кадров: " + " · ".join(f"{d} {len(p)}" for (d, *_), p in zip(SLIDES, pools)), flush=True)
    layers = [layer_for(t, cy) for (_d, t), cy in zip(SLIDES, POS[args.version])]
    carousels = G.plan(args.n, pools, random.Random(args.seed))

    args.out.mkdir(parents=True, exist_ok=True)
    if args.flat:
        args.flat.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, combo in enumerate(carousels, 1):
        d = args.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, (p, layer) in enumerate(zip(combo, layers), 1):
            bg = ImageOps.fit(Image.open(p).convert("RGB"), (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            if args.darken > 0:
                bg = T.darken(bg, args.darken, "uniform")
            bg = add_grain(bg, GRAIN_LEVELS[args.grain], np.random.default_rng(i * 10 + k))
            Image.alpha_composite(bg.convert("RGBA"), layer).convert("RGB").save(d / f"{k}.jpg", quality=95)
            if args.flat:
                shutil.copy2(d / f"{k}.jpg", args.flat / f"sort_{k}_{i}_{ID}.jpg")
        manifest.append({"carousel": d.name, "frames": [f.name for f in combo]})
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    for k, (d, *_r) in enumerate(SLIDES):
        c = Counter(m["frames"][k] for m in manifest)
        print(f"{d}: {len(c)} кадров, повторов {min(c.values())}–{max(c.values())}")
    print(f"уникальных каруселей: {len({tuple(m['frames']) for m in manifest})} из {len(manifest)}")
    print(f"готово: {len(manifest)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
