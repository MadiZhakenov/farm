#!/usr/bin/env python3
"""
1248 — карусели «дедушка не берёт трубку» (Magic Sort, сторителлинг, как бабушка 1249):
6 слайдов 1080×1440 из output/grandpa_slides/<слайд>/. Текст, подбор кадров и экспорт —
из build_grandma_carousels: TikTok-текст без автопереноса, фото затемняются на 20%,
на скриншоте переписки текст ставится под сообщениями.

  python build_grandpa_carousels.py -n 3 --out output/carousels_grandpa_test
  python build_grandpa_carousels.py -n 100 --out output/carousels_grandpa --flat output/1248_100 --flat-id 1248
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
SRC = ROOT / "output" / "grandpa_slides"
W, H = T.W, T.H

# (папка, текст, центр текста по высоте или None = под сообщениями переписки, затемнять)
SLIDES = [
    ("s1_selfie",
     "my grandpa lives alone\nand he stopped\nanswering my calls…\n\ni called 14 times. nothing.\ni assumed the worst",
     0.80, True),                                   # на кардиганах, под лицами
    ("s2_chats",
     "i called the neighbors.\nnobody had seen him\nsince Sunday",
     None, False),
    ("s3_office",
     "i left work\nin the middle of a meeting.\ni didn't even grab my coat",
     0.15, True),                                   # потолок — пальто на стуле остаётся видно
    ("s4_car",
     "i drove 10 hours straight.\ni was crying.\ni was bargaining with God",
     0.28, True),                                   # тёмная дорога за стеклом
    ("s5_grandpa",
     "i burst in and he's on the couch,\nglasses on, tongue out,\nfully locked in on the iPad\ni got him last Christmas\n"
     "that he said\nhe \"would never use\"",
     0.80, True),                                   # пол перед креслом
    ("s6_screen",
     "it's called Magic Sort.\nlevel 256.\n\nhe looked at me and said\n\"shh. i'm almost done\nwith this one\"",
     0.15, True),                                   # стена с полками над iPad
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
    for _d, text, cy, _dk in SLIDES:
        if cy is None:
            layers.append(None)
            continue
        block = G.text_block(text)
        layers.append(G.place(block, int(cy * H - block.height / 2)))
    carousels = G.plan(args.n, pools, random.Random(args.seed))

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, combo in enumerate(carousels, 1):
        d = args.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, (src, layer, (_d, text, _cy, dark)) in enumerate(zip(combo, layers, SLIDES), 1):
            bg = ImageOps.fit(Image.open(src).convert("RGB"), (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
            if layer is None:
                layer = G.chat_layer(text, bg)
            if dark:
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
    print(f"уникальных каруселей: {len({tuple(m['frames']) for m in manifest})} из {len(manifest)}")
    print(f"готово: {len(manifest)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
