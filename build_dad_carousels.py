#!/usr/bin/env python3
"""
«Правила папы-адвоката» (Magic Sort, реф @cravingthetea): 6 слайдов 1080×1920 (9:16).
Слайды 1 и 4 — ИИ (output/dad_slides/s1_kiss, s4_phone), 2/3/5/6 — Pinterest
(output/dad_pool/s2, s3, s5, s6 — оставлено пользователем). Текст — как у бабушки
(TikTok-стиль без автопереноса, build_grandma_carousels.text_block), фото затемняются на 20%.
Карусели не повторяются, кадры каждого слайда расходуются поровну.

  python build_dad_carousels.py -n 3 --out output/carousels_dad_test
  python build_dad_carousels.py -n 200 --out output/carousels_dad --flat output/<id>_200 --flat-id <id>

--project 1272 — «правила бабушки» (Cozy Home): слайды из output/gm_slides + output/gm_pool.
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
W, H = 1080, 1920
SL, POOL = ROOT / "output" / "dad_slides", ROOT / "output" / "dad_pool"
GSL, GPOOL = ROOT / "output" / "gm_slides", ROOT / "output" / "gm_pool"

# (папка, текст, центр текста по высоте в долях кадра) — по фидбеку текст по центру на всех слайдах
SLIDES = [
    (SL / "s1_kiss",
     "My dad was a divorce lawyer\nfor 30 years.\n\nThese are the rules he made\nevery girl in our family\n"
     "memorize before dating",
     0.50),
    (POOL / "s2",
     "The \"I'm Not Like Other Guys\" Rule.\n\nIf he says it,\nhe's exactly like other guys.",
     0.50),
    (POOL / "s3",
     "The Face-Down Phone Rule.\n\nDon't ask. Just notice.\nGuilt announces itself.",
     0.50),
    (SL / "s4_phone",
     "The Busy Rule.\n\nTell him you're busy\nplaying Magic Sort.\n\nA good one says \"have fun.\"\n"
     "A bad one says\n\"why aren't you answering me?\"",
     0.50),
    (POOL / "s5",
     "The Exit Rule.\n\nAlways have your own money,\nyour own keys, your own plan.",
     0.50),
    (POOL / "s6",
     "His last rule:\nif you have to ask twice,\nyou already have your answer.",
     0.50),
]

SLIDES_1272 = [
    (GSL / "s1_kiss",
     "My grandma was married\nfour times.\n\nThese are the rules she made\nevery girl in our family\n"
     "memorize before dating",
     0.50),
    (GPOOL / "s2",
     "The Mother Rule.\n\nWatch how he talks to his mom.\nThat's your future.",
     0.50),
    (GPOOL / "s3",
     "The Birthday Rule.\n\nIf he forgets your birthday\nin month 3, he'll forget\neverything else in year 3.",
     0.50),
    (GSL / "s4_cozy",
     "The Busy Rule.\n\nTell him you're busy decorating\na tiny room in Cozy Home.\n\nA good one says \"have fun.\"\n"
     "A bad one says\n\"why aren't you answering me?\"",
     0.50),
    (GPOOL / "s5",
     "The Running-Away Money Rule.\n\nKeep your own account.\nGrandma called it\n\"just in case money.\"",
     0.50),
    (GPOOL / "s6",
     "Her last rule:\nmarry the one who makes you laugh\non the worst day.\n\nMoney runs out.\nLaughter doesn't.",
     0.50),
]
PROJECTS = {"1271": SLIDES, "1272": SLIDES_1272}


def layer_for(text: str, cy: float) -> Image.Image:
    block = G.text_block(text)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    y = max(60, min(H - block.height - 60, int(cy * H - block.height / 2)))
    out.alpha_composite(block, ((W - block.width) // 2, y))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", choices=sorted(PROJECTS), default="1271")
    ap.add_argument("-n", type=int, default=200)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--darken", type=float, default=0.20)
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_<id>.jpg")
    ap.add_argument("--flat-id", default="")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    global SLIDES
    SLIDES = PROJECTS[args.project]

    pools = [sorted(f for f in d.iterdir() if f.is_file() and f.suffix.lower() in (".jpg", ".png")
                    and not f.name.startswith("_")) for d, *_ in SLIDES]
    print("кадров: " + " · ".join(f"{d.name} {len(p)}" for (d, *_), p in zip(SLIDES, pools)), flush=True)
    layers = [layer_for(t, cy) for _d, t, cy in SLIDES]
    carousels = G.plan(args.n, pools, random.Random(args.seed))

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, combo in enumerate(carousels, 1):
        d = args.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, (src, layer) in enumerate(zip(combo, layers), 1):
            bg = ImageOps.fit(Image.open(src).convert("RGB"), (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.45))
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
        print(f"{d.name}: {len(c)} кадров, повторов {min(c.values())}–{max(c.values())}")
    print(f"уникальных каруселей: {len({tuple(m['frames']) for m in manifest})} из {len(manifest)}")
    print(f"готово: {len(manifest)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
