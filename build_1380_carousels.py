#!/usr/bin/env python3
"""
1380 — «male gaze vs female gaze» (Inspoy): 3 слайда 3:4 (1080×1440), просто 2×2 встык, без рамок.
  1. «when she dresses for the male gaze 🙄» — mini / corset / sheer / backless, заголовок одной строкой ровно по центру
     (белый TikTok-шрифт с мягкой тенью, на стыке четырёх фото)
  2. «when she dress for the ✨ female gaze ✨» — так же, «✨ female gaze ✨» второй строкой: satin / blazer / knit / slip
  3. «looking for looks like these? search heeere girls 🤍» — девушка на весь кадр, белый текст сверху,
     карточка Inspoy из App Store (build_1319.app_card) на ногах, лицо открыто.
Фото — output/1380_slides/s1|s2|s3 (<образ>_<n>.jpg). Каждая карусель — своё сочетание фото (8 × 16 × 2 = 256),
порядок плиток — свой. Тексты ТЗ дословно, переносы по смыслу. Метаданные JPEG вычищаются.

  python build_1380_carousels.py -n 6 --out output/carousels_1380_test --qa
  python build_1380_carousels.py -n 200 --out output/carousels_1380 --flat output/1380_200 --qa
  # v2 (11.11): фото ближе (Flow-рефрейм, output/1380v2/slides), ID 1, папки с именем приложения
  python build_1380_carousels.py -n 100 --slides output/1380v2/slides --diag --suffix 1 --seed 13802       --out output/inspoy_1380_v2_carousels_100 --flat output/inspoy_1380_v2_100 --qa
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1281_carousels as B  # noqa: E402  (разбор строки на текст/эмодзи, Apple-эмодзи)
import build_1319_carousels as C1319  # noqa: E402  (app_card — шапка Inspoy в App Store)
import strip_jpeg_meta  # noqa: E402
from core.safe_zones import check_box, draw_overlay  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402

W, H = 1080, 1440
SL = ROOT / "output" / "1380_slides"
LOOKS = {1: ["m_mini", "m_corset", "m_sheer", "m_backless"], 2: ["f_satin", "f_blazer", "f_knit", "f_slip"]}
# заголовки дословно по ТЗ (строки — по смыслу; «✨ female gaze ✨» по просьбе — второй строкой); текст слайда 3 — две строки
TITLES = {1: ("when she dresses for the male gaze 🙄",), 2: ("when she dress for the", "✨ female gaze ✨")}
S3_LINES = ("looking for looks like these?", "search heeere girls 🤍")


def mixed_line(text: str, f: ImageFont.FreeTypeFont, ink: tuple, e_px: int) -> Image.Image:
    """Строка шрифтом f, Apple-эмодзи PNG в строку (по базовой линии)."""
    A = B.A
    runs = list(A._tokenize_runs(A.sanitize_overlay_text(B.R._normalize_text(text))))
    asc, desc = f.getmetrics()
    gap = int(e_px * 0.18)
    widths = [(f.getlength(ch) if kind != "emoji" else e_px + 2 * gap) for kind, ch in runs]
    img = Image.new("RGBA", (int(sum(widths)) + 20, asc + desc + 20), (0, 0, 0, 0))
    d, x, base = ImageDraw.Draw(img), 10.0, asc + 10
    for (kind, ch), w in zip(runs, widths):
        if kind == "emoji":
            e = A._apple_emoji_rgba(ch, e_px)
            if e is not None:
                img.alpha_composite(e, (int(x + gap), int(base - e_px * 0.78)))
        else:
            d.text((x, base), ch, font=f, anchor="ls", fill=ink + (255,))
        x += w
    return img.crop(img.getbbox())


def white_line(text: str, max_w: int, px_max: int) -> tuple[Image.Image, tuple[int, int]]:
    """Белый TikTok-шрифт без обводки + мягкая двойная тень (читается и на небе, и на фасаде).
    Возвращает картинку с полями тени и размер самого текста (он по центру картинки)."""
    for px in range(px_max, 24, -2):
        raw = mixed_line(text, B.R._load_font(px), (255, 255, 255), int(px * 1.05))
        if raw.width <= max_w:
            break
    blk = add_shadow(raw, blur=2.5, opacity=0.55, offset=(0, 2), grow=1)
    return add_shadow(blk, blur=18, opacity=0.35, offset=(0, 4), grow=6), raw.size


def put_line(im: Image.Image, text: str, y_top: int, max_w: int, px_max: int) -> tuple[int, int, int, int]:
    """Строка по центру кадра, верх текста на y_top; возвращает рамку самого текста."""
    blk, (tw, th) = white_line(text, max_w, px_max)
    px_, py_ = (blk.width - tw) // 2, (blk.height - th) // 2
    x, y = (W - blk.width) // 2, y_top - py_
    im.alpha_composite(blk, (x, y))
    return (x + px_, y_top, x + px_ + tw, y_top + th)


def collage_slide(k: int, photos: list[Path], rnd: random.Random) -> tuple[Image.Image, list[tuple]]:
    """2×2 встык, без рамок; заголовок ровно по центру кадра."""
    im = Image.new("RGBA", (W, H))
    tw, th = W // 2, H // 2
    for j, p in enumerate(photos):
        t = ImageOps.fit(Image.open(p).convert("RGB"), (tw, th), Image.Resampling.LANCZOS, centering=(0.5, 0.42))
        im.paste(t, ((j % 2) * tw, (j // 2) * th))
    lines, gap = TITLES[k], 14
    hs = [white_line(ln, 720, 50)[1][1] for ln in lines]
    y = H // 2 - (sum(hs) + gap * (len(lines) - 1)) // 2            # блок ровно по центру, на стыке четырёх фото
    boxes = []
    for ln, h in zip(lines, hs):
        boxes.append(put_line(im, ln, y, 720, 50))
        y += h + gap
    return im.convert("RGB"), boxes


def store_card(width: int) -> Image.Image:
    c = C1319.app_card(width).convert("RGBA")
    m = Image.new("L", (c.width * 4, c.height * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, c.width * 4 - 1, c.height * 4 - 1), radius=round(width * 0.045) * 4, fill=255)
    c.putalpha(m.resize(c.size, Image.Resampling.LANCZOS))
    return add_shadow(c, blur=16, opacity=0.45, offset=(0, 8), grow=2)


def girl_slide(p: Path, rnd: random.Random) -> tuple[Image.Image, list[tuple]]:
    src = Image.open(p).convert("RGB")
    z = rnd.uniform(1.0, 1.07)                                  # у каждой карусели свой наезд/сдвиг — слайд 3 не повторяется
    cw, ch = src.width / z, src.height / z
    x0, y0 = rnd.uniform(0, src.width - cw), rnd.uniform(0, (src.height - ch) * 0.6)
    src = src.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch)))
    im = ImageOps.fit(src, (W, H), Image.Resampling.LANCZOS).convert("RGBA")
    boxes, y = [], 104
    for ln in S3_LINES:
        boxes.append(put_line(im, ln, y, 720, 60))
        y = boxes[-1][3] + 18
    card = store_card(660)
    cx, cy = (W - card.width) // 2, int(0.72 * H - card.height / 2)
    im.alpha_composite(card, (cx, cy))
    return im.convert("RGB"), boxes


def plan(n: int, seed: int) -> list[dict]:
    """n разных сочетаний (фото на каждый образ + девушка слайда 3); фото — поровну, насколько возможно."""
    rnd = random.Random(seed)
    pools = {look: sorted((SL / ("s1" if look.startswith("m_") else "s2")).glob(f"{look}_*.jpg"))
             for k in (1, 2) for look in LOOKS[k]}
    girls = sorted((SL / "s3").glob("*.jpg"))
    keys = list(pools) + ["s3"]
    combos = list(itertools.product(*[pools[l] for l in pools], girls))
    if n > len(combos):
        raise SystemExit(f"уникальных сочетаний только {len(combos)} < {n}")
    rnd.shuffle(combos)
    used: Counter = Counter()
    out = []
    for _ in range(n):                                   # жадно: сочетание с наименее использованными фото
        best = min(combos, key=lambda c: (sum(used[f] for f in c), rnd.random()))
        combos.remove(best)
        used.update(best)
        pick = dict(zip(keys, best))
        orders = {k: rnd.sample(LOOKS[k], 4) for k in (1, 2)}
        out.append({"pick": {k: str(v.relative_to(ROOT)) for k, v in pick.items()}, "order": orders})
    return out


def plan_diag(n: int, seed: int) -> list[dict]:
    """v2: в каждом коллаже 2 близких кадра (B, *_B.jpg) строго по одной диагонали — плитки 1 и 4 или 2 и 3,
    на другой диагонали — 2 кадра A; 4 разных образа. Сочетания разные, фото — поровну, насколько возможно."""
    rnd = random.Random(seed)
    var = {}
    for k in (1, 2):
        for look in LOOKS[k]:
            fs = sorted((SL / ("s1" if k == 1 else "s2")).glob(f"{look}_*.jpg"))
            var[look] = {"A": [f for f in fs if not f.stem.endswith("_B")], "B": [f for f in fs if f.stem.endswith("_B")]}
    girls = sorted((SL / "s3").glob("*.jpg"))
    used: Counter = Counter()
    seen, seen_k, out = set(), {1: set(), 2: set()}, []
    while len(out) < n:
        best = None
        for _ in range(400):
            cand = {}
            for k in (1, 2):
                looks = rnd.sample(LOOKS[k], 4)
                b_looks, a_looks = looks[:2], looks[2:]
                diag, other = rnd.choice([((0, 3), (1, 2)), ((1, 2), (0, 3))])
                tiles = [None] * 4
                for pos, look in zip(diag, b_looks):
                    tiles[pos] = rnd.choice(var[look]["B"])
                for pos, look in zip(other, a_looks):
                    tiles[pos] = rnd.choice(var[look]["A"])
                cand[k] = tiles
            cand[3] = rnd.choice(girls)
            key = tuple(f.name for f in cand[1] + cand[2]) + (cand[3].name,)
            if key in seen or any(tuple(f.name for f in cand[k]) in seen_k[k] for k in (1, 2)):
                continue
            score = (sum(used[f] for f in cand[1] + cand[2] + [cand[3]]), rnd.random())
            if best is None or score < best[0]:
                best = (score, key, cand)
        _, key, cand = best
        seen.add(key)
        for k in (1, 2):
            seen_k[k].add(tuple(f.name for f in cand[k]))
        used.update(cand[1] + cand[2] + [cand[3]])
        out.append({"tiles": {str(k): [str(f.relative_to(ROOT)) for f in cand[k]] for k in (1, 2)},
                    "s3": str(cand[3].relative_to(ROOT))})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=4)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "carousels_1380_test")
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_1380.jpg")
    ap.add_argument("--seed", type=int, default=1380)
    ap.add_argument("--qa", action="store_true", help="листы с рамкой безопасной зоны")
    ap.add_argument("--slides", type=Path, default=ROOT / "output" / "1380_slides", help="папка с пулами s1/s2/s3")
    ap.add_argument("--diag", action="store_true", help="v2: близкие кадры (B) только по диагонали — 1 и 4 или 2 и 3")
    ap.add_argument("--suffix", default="1380", help="хвост имени во flat-папке: sort_<слайд>_<номер>_<suffix>.jpg")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    globals()["SL"] = a.slides.resolve()
    items = plan_diag(a.n, a.seed) if a.diag else plan(a.n, a.seed)
    a.out.mkdir(parents=True, exist_ok=True)
    qa = []
    for i, it in enumerate(items, 1):
        rnd = random.Random(a.seed * 1000 + i)
        d = a.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        if a.diag:
            slides = [collage_slide(k, [ROOT / f for f in it["tiles"][str(k)]], rnd) for k in (1, 2)]
            slides.append(girl_slide(ROOT / it["s3"], rnd))
        else:
            slides = [collage_slide(k, [ROOT / it["pick"][look] for look in it["order"][k]], rnd) for k in (1, 2)]
            slides.append(girl_slide(ROOT / it["pick"]["s3"], rnd))
        for k, (img, boxes) in enumerate(slides, 1):
            for b in boxes:
                if bad := check_box(W, H, b):
                    raise SystemExit(f"{i:03d} слайд {k}: текст вне безопасной зоны {bad}")
            img.save(d / f"{k}.jpg", quality=93)
            if a.qa and i <= 6:
                qa.append(draw_overlay(img))
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d / f"{k}.jpg", a.flat / f"sort_{k}_{i}_{a.suffix}.jpg")
        (d / "plan.json").write_text(json.dumps(it, indent=1), encoding="utf-8")
        print(f"{i:03d} ✓", flush=True)
    if qa:
        tw, th = 360, 480
        sheet = Image.new("RGB", (3 * tw, (len(qa) // 3) * th), (30, 30, 30))
        for j, q in enumerate(qa):
            sheet.paste(q.resize((tw, th)), ((j % 3) * tw, (j // 3) * th))
        sheet.save(a.out / "_qa.jpg", quality=88)
    sys.argv = ["strip", str(a.out)] + ([str(a.flat)] if a.flat else [])
    strip_jpeg_meta.main()
    print(f"готово: {len(items)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
