#!/usr/bin/env python3
"""
Карусели «The REAL reason you're always tired this fall» (Cozy Home):
4 слайда 1080×1440 из отобранных кадров output/carousel_stills/s1…s4,
обычный TikTok-текст (белый, тонкая обводка, Apple-эмодзи) по центру.

  python build_tired_carousels.py -n 50 --out output/carousels_tired

Правила подбора:
  * карусели не повторяются, кадры каждого слайда расходуются равномерно;
  * слайд 1 и слайд 3 не из одного видео (иначе почти один и тот же кадр).
Выход: <out>/001/1.jpg … 4.jpg + manifest.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

import assemble_ugc_reels as A
import assemble_ugc_reels_3part as M
from core import renderer as R

ROOT = Path(__file__).resolve().parent
STILLS = ROOT / "output" / "carousel_stills"
W, H = 1080, 1440

# \n\n — строки ТЗ (между ними небольшой отступ), \n — переносы по смыслу.
# Автоперенос — только если строка не влезает по ширине.
SLIDES = [
    "The REAL reason you're\nalways tired this fall 🍂😮‍💨\n\n"
    "(and no, it's not your sleep)",
    "I was exhausted too\nevery single day\n\n"
    "coffee early nights vitamins\nNOTHING helped\n\n"
    "until I found one thing\nthat changed everything",
    "Turns out my brain\nnever got a real break\nfrom work and notifications\n\n"
    "So every evening I turn off\nALL notifications,\nlight a candle, make tea\n\n"
    "and open Cozy Home.",
    "30 minutes in the evening\nand my brain is finally calm.\n\n"
    "Save this so you don't lose it.",
]

# Версия про Magic Sort (2026-10-05): тот же сценарий, слайды 3–4 — игра
SLIDES_MAGICSORT = [
    "The ONE reason you're\nalways tired this fall 🍂😮‍💨\n\n"
    "(and no, it's not your sleep)",
    "I was exhausted too.\nEvery single day.\n\n"
    "Coffee, early nights, vitamins,\na \"digital detox\"\nthat lasted 40 minutes.\nNOTHING helped.\n\n"
    "Until I found one very funny thing\nthat changed everything.",
    "Turns out my brain\nnever got a real break\nfrom work and notifications.\n\n"
    "So every evening I turn off\nALL notifications,\nlight a candle, make tea\n\n"
    "and pour colored liquids into tubes\nlike a very serious scientist.\n\n"
    "It's called Magic Sort.",
    "30 minutes in the evening\nand my brain is finally calm.\n\n"
    "My only problem now\nis that the blue one won't fit.\n\n"
    "Save this so you don't lose it.",
]
# Короткая версия про Magic Sort: текст как у Cozy Home, но «The ONE» и «open Magic Sort.»
SLIDES_MAGICSORT_SHORT = [
    "The ONE reason you're\nalways tired this fall 🍂😮‍💨\n\n"
    "(and no, it's not your sleep)",
    SLIDES[1],
    "Turns out my brain\nnever got a real break\nfrom work and notifications\n\n"
    "So every evening I turn off\nALL notifications,\nlight a candle, make tea\n\n"
    "and open Magic Sort.",
    SLIDES[3],
]
TEXTS = {"cozy": SLIDES, "magicsort": SLIDES_MAGICSORT, "magicsort_short": SLIDES_MAGICSORT_SHORT}

MAX_W = int(W * 0.80)
FONT_START, FONT_MIN = 54, 40
PARA_GAP = 0.45  # доп. отступ между строками ТЗ, в долях высоты строки
# Затемнение фото, чтобы белый текст читался: uniform — весь кадр
# (выбор команды, 20%), band — только полоса за текстом посередине
DARKEN = 0.20
DARKEN_MODE = "uniform"
BAND_HALF = 0.45  # полуширина полосы в долях половины высоты кадра


def darken(img: Image.Image, strength: float = DARKEN, mode: str = DARKEN_MODE) -> Image.Image:
    import numpy as np

    if strength <= 0:
        return img
    if mode == "band":
        y = np.linspace(-1, 1, img.height, dtype=np.float32)[:, None, None]
        keep = 1 - strength * np.exp(-(y / BAND_HALF) ** 4)
    else:
        keep = 1 - strength
    a = np.asarray(img.convert("RGB"), dtype=np.float32) * keep
    return Image.fromarray(a.clip(0, 255).astype("uint8"))


def _layout(text: str, size: int) -> tuple[list[list[str]], int, int] | None:
    font = R._load_font(size)
    stroke = R.stroke_width_for(size)
    wrap_w = MAX_W - 2 * stroke
    paras = []
    for block in text.split("\n\n"):
        lines = []
        for ln in block.split("\n"):
            ln = A.sanitize_overlay_text(R._normalize_text(ln))
            if A._line_width_mixed(ln, font, size, stroke) <= wrap_w:
                lines.append(ln)
            else:
                lines += M._balanced_wrap(ln, font, size, wrap_w, stroke)
        paras.append(lines)
    adv = R.line_advance_for(size)
    n_lines = sum(len(p) for p in paras)
    h = n_lines * adv + int((len(paras) - 1) * adv * PARA_GAP)
    widest = max(A._line_width_mixed(ln, font, size, stroke) for p in paras for ln in p)
    if widest > MAX_W or n_lines > 10:
        return None
    return paras, h, adv


def render_text(text: str) -> Image.Image:
    """Прозрачный слой 1080×1440 с текстом по центру кадра."""
    for size in range(FONT_START, FONT_MIN - 1, -1):
        lay = _layout(text, size)
        if lay:
            break
    paras, h, adv = lay
    font = R._load_font(size)
    stroke = R.stroke_width_for(size)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = (H - h) // 2
    for k, p in enumerate(paras):
        for ln in p:
            lw = int(round(A._line_width_mixed(ln, font, size, stroke)))
            A._draw_line_mixed(img, draw, (W - lw) // 2, y, ln, font, size, stroke)
            y += adv
        if k < len(paras) - 1:
            y += int(adv * PARA_GAP)
    return img


def source_of(p: Path) -> str:
    return re.sub(r"_\d+(\.\d+)?$", "", p.stem)


def plan(n: int, pools: list[list[Path]], rng: random.Random) -> list[list[Path]]:
    use = [Counter() for _ in pools]
    seen: set[tuple] = set()
    out = []
    for _ in range(n):
        for attempt in range(2000):
            combo = []
            for k, pool in enumerate(pools):
                cands = pool
                if k == 2 and source_of(combo[0]).startswith("IMG_"):
                    # слайд 3 не из того же видео, что слайд 1 (кадры из видео)
                    cands = [p for p in pool if source_of(p) != source_of(combo[0])] or pool
                low = min(use[k][p] for p in cands)
                slack = 0 if attempt < 500 else 1
                cands = [p for p in cands if use[k][p] <= low + slack]
                combo.append(rng.choice(cands))
            if tuple(combo) not in seen:
                break
        seen.add(tuple(combo))
        for k, p in enumerate(combo):
            use[k][p] += 1
        out.append(combo)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=50)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--texts", choices=sorted(TEXTS), default="cozy")
    for i in range(1, 5):
        ap.add_argument(f"--s{i}", type=Path, default=STILLS / f"s{i}", help=f"папка кадров слайда {i}")
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<карусель>_<слайд>_<id>.jpg")
    ap.add_argument("--flat-id", default="1227")
    ap.add_argument("--darken", type=float, default=DARKEN, help="0 — без затемнения")
    ap.add_argument("--darken-mode", choices=("uniform", "band"), default=DARKEN_MODE)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    pools = [sorted(f for f in getattr(args, f"s{i}").glob("*.jpg") if not f.name.startswith("_"))
             for i in range(1, 5)]
    print("кадров: " + " · ".join(f"s{i + 1} {len(p)}" for i, p in enumerate(pools)), flush=True)
    slides = TEXTS[args.texts]
    layers = [render_text(t) for t in slides]
    carousels = plan(args.n, pools, random.Random(args.seed))

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, combo in enumerate(carousels, 1):
        d = args.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, (src, layer) in enumerate(zip(combo, layers), 1):
            bg = darken(R.cover_resize(Image.open(src).convert("RGB"), W, H), args.darken, args.darken_mode).convert("RGBA")
            Image.alpha_composite(bg, layer).convert("RGB").save(d / f"{k}.jpg", quality=95)
            if args.flat:
                args.flat.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d / f"{k}.jpg", args.flat / f"sort_{i}_{k}_{args.flat_id}.jpg")
        manifest.append({"carousel": d.name, "frames": [p.name for p in combo], "texts": slides})
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    for k in range(4):
        c = Counter(m["frames"][k] for m in manifest)
        print(f"слайд {k + 1}: {len(c)} кадров, повторов {min(c.values())}–{max(c.values())}")
    print(f"уникальных каруселей: {len({tuple(m['frames']) for m in manifest})} из {len(manifest)}")
    print(f"готово: {len(manifest)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
