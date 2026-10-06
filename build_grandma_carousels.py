#!/usr/bin/env python3
"""
Карусели «бабушка не берёт трубку» (Cozy Home, сторителлинг): 6 слайдов
1080×1440 из папок output/grandma_slides/<слайд>/. Текст — TikTok-стиль
(как build_tired_carousels): строки сценария не переносятся, кегль
подбирается так, чтобы каждая влезла целиком. У каждого слайда своя высота
текста, чтобы не закрывать лица / экран. Фото затемняются на 20%; на
скриншоте переписки текст ставится в пустое место под сообщениями.

  python build_grandma_carousels.py -n 100 --out output/carousels_grandma [--flat DIR --flat-id 1260]

Подбор: карусели не повторяются, кадры каждого слайда расходуются поровну.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

import assemble_ugc_reels as A
import build_tired_carousels as T
from core import renderer as R

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "output" / "grandma_slides"
W, H = T.W, T.H
FONT_MIN = 30

# (папка, текст, центр текста по высоте в долях кадра, затемнять)
# \n\n — абзац ТЗ, \n — перенос по смыслу (автопереноса нет)
SLIDES = [
    ("s1_selfie",
     "my grandma lives alone\nand she stopped\nanswering my calls...\n\n"
     "i called 14 times. nothing.\nat this point\ni was nervous in my head",
     0.74, True),
    ("s2_chats",
     "i called the neighbors.\nnobody had seen her\nsince Sunday.\n\ni started shaking",
     None, False),
    ("s3_office",
     "i left work\nin the middle of a meeting.\n\nno coat. no plan.\njust vibes and panic",
     0.70, True),
    ("s4_car",
     "i drove 10 hours straight,\ncrying, bargaining with God,\n\npromising to be\na better granddaughter",
     0.34, True),
    ("s5_grandma",
     "i burst through the door\nscreaming \"GRANDMA???\"\n\nand there she is\nin her armchair,\n"
     "glasses on, tongue out,\nfully locked in on the iPad\ni got her last Christmas\n"
     "that she said\nshe \"would never use\"",
     0.68, True),
    ("s6_screen",
     "she's sitting there\nplaying Cozy Home\nwith a cup of tea\nlike nothing happened.\n\n"
     "\"i have 14 missed calls?\ni was BUSY\"",
     0.17, True),
]


def text_block(text: str, max_h: int = H) -> Image.Image:
    """Блок текста без автопереноса: кегль уменьшается, пока строки влезают."""
    paras = [[A.sanitize_overlay_text(R._normalize_text(ln)) for ln in b.split("\n")]
             for b in text.split("\n\n")]
    for size in range(T.FONT_START, FONT_MIN - 1, -1):
        font = R._load_font(size)
        stroke = R.stroke_width_for(size)
        adv = R.line_advance_for(size)
        widest = max(A._line_width_mixed(ln, font, size, stroke) for p in paras for ln in p)
        h = sum(len(p) for p in paras) * adv + int((len(paras) - 1) * adv * T.PARA_GAP) + adv
        if widest <= T.MAX_W and h <= max_h:
            break
    img = Image.new("RGBA", (W, h + 4 * stroke), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = 2 * stroke
    for k, p in enumerate(paras):
        for ln in p:
            lw = int(round(A._line_width_mixed(ln, font, size, stroke)))
            A._draw_line_mixed(img, draw, (W - lw) // 2, y, ln, font, size, stroke)
            y += adv
        if k < len(paras) - 1:
            y += int(adv * T.PARA_GAP)
    return img.crop(img.getbbox())


def place(block: Image.Image, y: int) -> Image.Image:
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    y = max(50, min(H - block.height - 50, y))
    out.alpha_composite(block, ((W - block.width) // 2, y))
    return out


def chat_layer(text: str, shot: Image.Image) -> Image.Image:
    """Скриншот переписки: текст в пустое место под последним сообщением."""
    g = np.asarray(shot.convert("L"))
    rows = np.where((g[400:] > 40).sum(1) > 4)[0]
    bottom = 400 + (int(rows.max()) if len(rows) else 0)
    room = H - bottom - 60
    block = text_block(text, max_h=room)
    return place(block, bottom + 30 + max(0, (room - block.height) // 2))


def plan(n: int, pools: list[list[Path]], rng: random.Random) -> list[list[Path]]:
    use = [Counter() for _ in pools]
    seen: set[tuple] = set()
    out = []
    for _ in range(n):
        for attempt in range(3000):
            slack = 0 if attempt < 1000 else 1
            combo = []
            for k, pool in enumerate(pools):
                low = min(use[k][p] for p in pool)
                combo.append(rng.choice([p for p in pool if use[k][p] <= low + slack]))
            if tuple(combo) not in seen:
                break
        seen.add(tuple(combo))
        for k, p in enumerate(combo):
            use[k][p] += 1
        out.append(combo)
    return out


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
    layers = [place(text_block(t), int(cy * H - text_block(t).height / 2)) if cy is not None else None
              for _d, t, cy, _dk in SLIDES]
    carousels = plan(args.n, pools, random.Random(args.seed))

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, combo in enumerate(carousels, 1):
        d = args.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, (src, layer, (_d, text, _cy, dark)) in enumerate(zip(combo, layers, SLIDES), 1):
            bg = ImageOps.fit(Image.open(src).convert("RGB"), (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
            if layer is None:
                layer = chat_layer(text, bg)
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
