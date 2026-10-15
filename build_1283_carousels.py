#!/usr/bin/env python3
"""
1283 — Magic Sort, карусель «i couldn’t get into a relationship for 3 years until i saw a guy on the street
doing THIS…»: 7 слайдов 3:4 (1080×1440). Тексты — дословно из ТЗ, переносы по смыслу вручную (\\n — строка,
\\n\\n — отступ между мыслями), TikTok-стиль по центру, только внутри безопасной рамки core/safe_zones
(x 180–900, y 6–78 %). Вёрстка/QA — как build_1281_carousels.py (fixed / split, PER_IMAGE, проверка рамки).

Кадры: свои слайды output/1283_slides/<папка>, Pinterest-пулы output/1283_pool/<sN> (пользователь чистит).
crop_top — доля кадра, срезаемая сверху до кадрирования в 3:4 (s5: убрать подбородок).

  python build_1283_carousels.py --qa --out output/carousels_1283_test -n 3
  python build_1283_carousels.py -n 100 --out output/carousels_1283 --flat output/1283_100 --flat-id 1283 --qa
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1281_carousels as B  # noqa: E402  (text_block / fits — та же типографика)
import build_grandma_carousels as G  # noqa: E402
import build_tired_carousels as T  # noqa: E402
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402

W, H = B.W, B.H
X0, Y0, X1, Y1 = text_rect(W, H)
SL = ROOT / "output" / "1283_slides"
POOL = ROOT / "output" / "1283_pool"
EXT = (".jpg", ".jpeg", ".png", ".webp")

# папка, текст ТЗ с переносами по смыслу, режим, cy (или места split), макс. высота блока, crop_top
SLIDES = [
    (SL / "s1_selfie",
     "i couldn’t get into a relationship\nfor 3 years\nuntil i saw a guy on the street\ndoing THIS…\n\n(read to the end)",
     "fixed", 0.675, 0.20, 0.0),                          # лицо сверху — текст на шарфе/свитере
    (POOL / "s2",
     "every date was the same:\nphones out, small talk,\n“so what do you do?”\n\ni was bored\n"
     "before the food even arrived 😭",
     "fixed", 0.45, 0.24, 0.0),
    (SL / "s3_bench",
     "then one rainy evening\ni saw a guy on a bench\nignoring the whole world.\n\nfully locked in on his phone,\n"
     "smiling at it like a little kid",
     "fixed", 0.235, 0.27, 0.0),                          # небо над ним; парень — слева внизу
    (SL / "s4_show",                                      # телефон в центре: начало над ним, конец — под рукой
     "i walked past.\nthen walked back.\n\n“what are you playing?”\n|\n"
     "he looked up, a little embarrassed,\nand turned the screen to me… 😳",
     "split", [(0.165, 0.19), (0.735, 0.085)], None, 0.0),
    (SL / "s5_surgeon",
     "it was Magic Sort 🧩\n\nhe was sorting colors\nwith the focus of a surgeon,\nand i couldn’t stop laughing",
     "fixed", 0.27, 0.26, 0.08),                          # руки и телефон ниже середины
    (SL / "s6_handoff",
     "3 things i noticed:\n\n1) he wasn’t hiding that something\nso small made him happy\n\n"
     "2) he wasn’t performing for anyone\n\n3) he said “wanna try?”\nand handed me his phone",
     "fixed", 0.205, 0.27, 0.0),                          # телефон с 42 % высоты — текст над ним
    (SL / "s7_hands",
     "we’ve been together ever since 🫶\n\nwhich of the 3\nwould make YOU say yes?\n\n1, 2 or 3? 👇",
     "fixed", 0.31, 0.26, 0.0),                           # руки на парапете снизу — текст над рекой
]
# свои настройки у отдельных кадров: {индекс слайда: {начало имени файла: cy | {"cy", "mh", "cx", "mw", "text"}}}
PER_IMAGE: dict[int, dict[str, float | dict]] = {}
# центр блока по горизонтали и его макс. ширина (доли кадра) — когда сбоку экран/лицо: {индекс слайда: значение}
CX: dict[int, float] = {}
MW: dict[int, float] = {}


def fits(text: str, px: int, max_h: int, max_w: int) -> bool:
    """B.fits, но с заданной шириной блока."""
    paras = B._paras(text)
    font, stroke, adv = B.R._load_font(px), B.R.stroke_width_for(px), B.R.line_advance_for(px)
    widest = max(B.A._line_width_mixed(ln, font, px, stroke) for p in paras for ln in p)
    h = sum(len(p) for p in paras) * adv + int((len(paras) - 1) * adv * B.PARA_GAP) + 4 * stroke
    return widest <= max_w - 2 * stroke and h <= max_h


@lru_cache(maxsize=None)
def block_for(text: str, max_h: int, max_w: int) -> Image.Image:
    px = next((p for p in range(B.PX_MAX, B.PX_MIN - 1, -1) if fits(text, p, max_h, max_w)), B.PX_MIN)
    return B.text_block(text, max_h, px)


def place_split(slide: int) -> tuple[Image.Image, tuple[int, int, int, int]]:
    _d, text, _mode, spots, _mh, _crop = SLIDES[slide]
    parts = text.split("\n|\n")
    px = next((p for p in range(B.PX_MAX, B.PX_MIN - 1, -1)
               if all(B.fits(t, p, int(mh * H)) for t, (_cy, mh) in zip(parts, spots))), B.PX_MIN)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    xs, ys = [], []
    for t, (cy, mh) in zip(parts, spots):
        b = B.text_block(t, int(mh * H), px)
        x, y = (W - b.width) // 2, int(cy * H - b.height / 2)
        y = max(Y0, min(Y1 - b.height, y))
        out.alpha_composite(b, (x, y))
        xs += [x, x + b.width]
        ys += [y, y + b.height]
    return out, (min(xs), min(ys), max(xs), max(ys))


def place(slide: int, name: str) -> tuple[Image.Image, tuple[int, int, int, int]]:
    _d, text, mode, cy, mh, _crop = SLIDES[slide]
    if mode == "split":
        return place_split(slide)
    cx, mw = CX.get(slide, 0.5), MW.get(slide, (X1 - X0) / W)
    for pre, v in PER_IMAGE.get(slide, {}).items():
        if name.startswith(pre):
            if isinstance(v, dict):
                text, cy, mh = v.get("text", text), v.get("cy", cy), v.get("mh", mh)
                cx, mw = v.get("cx", cx), v.get("mw", mw)
            else:
                cy = v
    block = block_for(text, int(mh * H), int(mw * W))
    y = int(cy * H - block.height / 2)
    y = max(Y0, min(Y1 - block.height, y))
    x = int(cx * W - block.width / 2)
    x = max(X0, min(X1 - block.width, x))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(block, (x, y))
    return out, (x, y, x + block.width, y + block.height)


def fit_bg(src: Path, crop_top: float = 0.0) -> Image.Image:
    im = Image.open(src).convert("RGB")
    if crop_top:
        im = im.crop((0, int(crop_top * im.height), im.width, im.height))
    return ImageOps.fit(im, (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.45 if not crop_top else 0.0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--darken", type=float, default=0.20)
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_<id>.jpg")
    ap.add_argument("--flat-id", default="")
    ap.add_argument("--qa", action="store_true", help="QA-листы: ВСЕ кадры каждого слайда с текстом и зонами")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    pools = [sorted(f for f in d.iterdir() if f.is_file() and f.suffix.lower() in EXT and not f.name.startswith("_"))
             if d.is_dir() else [] for d, *_ in SLIDES]
    print("кадров: " + " · ".join(f"{d.name} {len(p)}" for (d, *_), p in zip(SLIDES, pools)), flush=True)

    layers: dict = {}
    for k, pool in enumerate(pools):
        for src in pool:
            layer, box = place(k, src.name)
            bad = check_box(W, H, box)
            if bad:
                raise SystemExit(f"{SLIDES[k][0].name}/{src.name}: текст вне безопасной зоны — {bad}")
            layers[src] = layer
            layers[(src, "box")] = box

    if args.qa:
        args.out.mkdir(parents=True, exist_ok=True)
        tw, th, cols = 216, 288, 14
        for k, pool in enumerate(pools):
            if not pool:
                continue
            rows = (len(pool) + cols - 1) // cols
            sheet = Image.new("RGB", (tw * min(cols, len(pool)), th * rows), "white")
            for i, src in enumerate(pool):
                im = Image.alpha_composite(T.darken(fit_bg(src, SLIDES[k][5]), args.darken, "uniform").convert("RGBA"),
                                           layers[src]).convert("RGB")
                im = draw_overlay(im)
                dr = ImageDraw.Draw(im)
                dr.rectangle(layers[(src, "box")], outline=(255, 255, 0), width=5)
                dr.text((12, 12), src.name[:12], fill=(255, 255, 0))
                sheet.paste(im.resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
            sheet.save(args.out / f"_qa_{k + 1}_{SLIDES[k][0].name}.jpg", quality=86)

    empty = [SLIDES[k][0].name for k, p in enumerate(pools) if not p]
    if empty:
        print("нет кадров: " + ", ".join(empty) + " — карусели не собираю")
        return 0 if args.qa else 1

    carousels = G.plan(args.n, pools, random.Random(args.seed))
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, combo in enumerate(carousels, 1):
        d = args.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, src in enumerate(combo, 1):
            bg = T.darken(fit_bg(src, SLIDES[k - 1][5]), args.darken, "uniform")
            Image.alpha_composite(bg.convert("RGBA"), layers[src]).convert("RGB").save(d / f"{k}.jpg", quality=95)
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
