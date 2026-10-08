#!/usr/bin/env python3
"""
1251 — карусели «my dog stopped getting excited» (Magic Sort, сторителлинг по
рефу @pocket.the.doxie): 5 слайдов 1080×1440 из output/dog_slides/<слайд>/.
Текст, подбор кадров и экспорт — как у бабушки (build_grandma_carousels):
TikTok-текст без автопереноса, фото затемняются на 20%, кадры каждого слайда
расходуются поровну, карусели не повторяются.

  python build_dog_carousels.py -n 3 --out output/carousels_dog_test
  python build_dog_carousels.py -n 100 --out output/carousels_dog --flat output/carousels_dog_flat --flat-id 1251
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps

import build_grandma_carousels as G
import build_tired_carousels as T

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "output" / "dog_slides"
W, H = T.W, T.H

# (папка, текст, центр текста по высоте) — текст на пустом месте, не на мордах
SLIDES = [
    ("s1_sad", "my dog stopped getting\nexcited about anything 😭", 0.88),           # под лицами, на кофте
    ("s2_window", "no walks, no toys, no treats.\nhe just laid by the window\nALL day 💔", 0.82),  # пол
    ("s3_curious", "then i found the one thing\nthat cheered him up.\ntotally unexpected 🥹", 0.17),  # диван сверху
    ("s4_watch", "he lifted his head.\nwatched every tube in Magic Sort.\nevery color. didn't blink 🧪✨", 0.88),
    ("s5_happy", "he's my level 300\nemotional support dog now 😭🧪", 0.64),      # плед, над телефоном
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--darken", type=float, default=0.20)
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_<id>.jpg")
    ap.add_argument("--flat-id", default="")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    pools = [sorted(f for f in (SRC / d).iterdir()
                    if f.suffix.lower() in (".jpg", ".png") and not f.name.startswith("_"))
             for d, *_ in SLIDES]
    print("кадров: " + " · ".join(f"{d} {len(p)}" for (d, *_), p in zip(SLIDES, pools)), flush=True)
    layers = []
    for _d, text, cy in SLIDES:
        block = G.text_block(text)
        layers.append(G.place(block, int(cy * H - block.height / 2)))
    carousels = G.plan(args.n, pools, random.Random(args.seed))

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, combo in enumerate(carousels, 1):
        d = args.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, (src, layer) in enumerate(zip(combo, layers), 1):
            bg = ImageOps.fit(Image.open(src).convert("RGB"), (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
            bg = T.darken(bg, args.darken, "uniform")
            Image.alpha_composite(bg.convert("RGBA"), layer).convert("RGB").save(d / f"{k}.jpg", quality=95)
            if args.flat:
                args.flat.mkdir(parents=True, exist_ok=True)
                suffix = f"_{args.flat_id}" if args.flat_id else ""
                shutil.copy2(d / f"{k}.jpg", args.flat / f"sort_{k}_{i}{suffix}.jpg")
        manifest.append({"carousel": d.name, "frames": [p.name for p in combo]})
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    for k, (d, *_r) in enumerate(SLIDES):
        c = Counter(m["frames"][k] for m in manifest)
        print(f"{d}: {len(c)} кадров, повторов {min(c.values())}–{max(c.values())}")
    print(f"готово: {len(manifest)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
