#!/usr/bin/env python3
"""
1307 — карусель «I was a flight attendant for 20 years. DON’T fly until you know this ✈️»: 6 слайдов 3:4
(1080×1440). Тексты — дословно из ТЗ (с эмодзи), переносы по смыслу вручную (\\n — строка, \\n\\n — отступ).
Типографика и вёрстка — как build_1283_carousels.py (TikTok-шрифт, белый с обводкой, по центру, только внутри
безопасной рамки core/safe_zones: x 180–900, y 6–78 %), место текста — мимо лица и главного объекта.
Слайды «яркие и сочные» (ТЗ): без затемнения, лёгкий подъём яркости/насыщенности (vivid).

Кадры: output/1307_slides/s1…s6/v*.jpg — генерации пользователя (Google Flow, 896×1200):
  s1 селфи стюардессы в салоне · s2 выход/дверь · s3 полки с багажом / проход · s4 обувь ·
  s5 столик и салфетка (POV) · s6 камбуз / стюардесса с интерфоном у двери.

  python build_1307_carousels.py --qa --out output/carousels_1307_test -n 3
  python build_1307_carousels.py -n 100 --out output/carousels_1307 --flat output/1307_100 --flat-id 1307 --qa
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
from PIL import Image, ImageDraw, ImageEnhance

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1283_carousels as C  # noqa: E402  (place / fit_bg / типографика)
import build_grandma_carousels as G  # noqa: E402
from core.safe_zones import check_box, draw_overlay  # noqa: E402

W, H = C.W, C.H
NL = chr(10)
SL = ROOT / "output" / "1307_slides"

# папка, текст ТЗ с переносами по смыслу, режим, cy, макс. высота блока, crop_top
C.SLIDES = [
    (SL / "s1",
     "I was a flight attendant\nfor 20 years.\n\nDON’T fly until\nyou know this ✈️",
     "fixed", 0.60, 0.22, 0.0),                           # лицо сверху — текст на форме
    (SL / "s2",
     "count the rows\nto your nearest exit.\n\nin smoke you can’t see,\nyou can only count 😳",
     "fixed", 0.72, 0.22, 0.0),
    (SL / "s3",
     "if we ever evacuate,\nLEAVE YOUR BAG.\n\npeople who stop to grab\ntheir carry-on block the aisle\n"
     "for everyone behind them 😳",
     "fixed", 0.66, 0.26, 0.0),
    (SL / "s4",
     "wear real shoes\nfor takeoff and landing.\n\nflip flops are the first thing\npeople lose\n"
     "when they have to move fast",
     "fixed", 0.24, 0.27, 0.0),
    (SL / "s5",
     "wipe your tray table\nbefore you eat off it.\n\nit’s one of the dirtiest things\non the plane,\n"
     "and nobody cleans it\nbetween flights as well as you think",
     "fixed", 0.22, 0.30, 0.0),                           # столик и рука снизу — текст на спинке кресла
    (SL / "s6",
     "the thing I wish everyone did:\nlisten to the safety demo.\nyes, EVERY time.\n\n"
     "I’ve seen what happens\nwhen people don’t 🥹\n\nwhich one did you not know?",
     "fixed", 0.27, 0.32, 0.0),                           # дверь сверху пустая — стюардесса ниже
]
# свои места у отдельных кадров (индекс слайда → начало имени файла → cy | {cy, mh}): голова стюардессы
C.PER_IMAGE = {
    5: {"v02": {"cy": 0.205, "mh": 0.24},           # голова у двери с 33 % высоты — текст выше
        "v03": {"cy": 0.645, "mh": 0.27}},          # голова на 21–31 % — текст ниже, на юбке/коленях
}
C.CX, C.MW = {}, {}


def vivid(im: Image.Image) -> Image.Image:
    """«Ярко и сочно»: чуть насыщеннее, светлее и контрастнее, без выбивания светов."""
    im = ImageEnhance.Color(im).enhance(1.15)
    im = ImageEnhance.Contrast(im).enhance(1.04)
    return ImageEnhance.Brightness(im).enhance(1.03)


def frame(src: Path, k: int, layer: Image.Image) -> Image.Image:
    bg = vivid(C.fit_bg(src, C.SLIDES[k][5]))
    return Image.alpha_composite(bg.convert("RGBA"), layer).convert("RGB")


# обложка (клиент): первый абзац — белый с обводкой, второй («DON’T fly until…») — чёрный на белой плашке
PLATE_PARA = 1


def plate_block(lines: list[str], px: int) -> Image.Image:
    """Чёрный TikTok-текст на белых плашках, слитых «лесенкой» со скруглением (как фон текста в TikTok);
    эмодзи — Apple PNG в строке."""
    font, adv = C.B.R._load_font(px), C.B.R.line_advance_for(px)
    pad, r = int(0.42 * px), int(0.26 * px)
    widths = [C.B.A._line_width_mixed(ln, font, px, 0) for ln in lines]
    cw, ch = int(max(widths) + 2 * pad + 4 * r), adv * len(lines) + 4 * r
    mask = np.zeros((ch, cw), np.uint8)
    for k, w in enumerate(widths):
        x0 = int((cw - w) / 2 - pad)
        mask[2 * r + k * adv:2 * r + (k + 1) * adv, x0:x0 + int(w + 2 * pad)] = 255
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    mask = cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kern), cv2.MORPH_OPEN, kern)
    img = Image.new("RGBA", (cw, ch), (255, 255, 255, 0))
    img.putalpha(Image.fromarray(mask))
    d = ImageDraw.Draw(img)
    ascent, descent = font.getmetrics()
    for k, (ln, w) in enumerate(zip(lines, widths)):
        cx = (cw - w) / 2
        top = 2 * r + k * adv + (adv - (ascent + descent)) / 2
        base = top + ascent
        for kind, chunk in C.B.A._tokenize_runs(ln):
            if kind == "emoji":
                e = C.B.A._apple_emoji_rgba(chunk, C.B.A._emoji_px(px))
                if e is not None:
                    img.alpha_composite(e, (int(cx), int(base - e.height * 0.84)))
            else:
                d.text((cx, base), chunk, font=font, anchor="ls", fill=(0, 0, 0, 255))
            cx += C.B.A._chunk_width(chunk, kind, font, px, 0)
    return img


def place(k: int, name: str) -> tuple[Image.Image, tuple[int, int, int, int]]:
    if k != 0:
        return C.place(k, name)
    _d, text, _mode, cy, mh, _crop = C.SLIDES[0]
    paras = text.split(NL + NL)
    px = next((p for p in range(C.B.PX_MAX, C.B.PX_MIN - 1, -1) if C.B.fits(text, p, int(mh * H))), C.B.PX_MIN)
    top_block = C.B.text_block(NL.join(paras[:PLATE_PARA]), int(mh * H), px)
    plate = plate_block([C.B.A.sanitize_overlay_text(C.B.R._normalize_text(ln))
                         for ln in NL.join(paras[PLATE_PARA:]).split(NL)], px)
    gap = int(C.B.R.line_advance_for(px) * C.B.PARA_GAP)
    h = top_block.height + gap + plate.height
    y = int(cy * H - h / 2)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(top_block, ((W - top_block.width) // 2, y))
    out.alpha_composite(plate, ((W - plate.width) // 2, y + top_block.height + gap))
    x0 = min((W - top_block.width) // 2, (W - plate.width) // 2)
    return out, (x0, y, W - x0, y + h)


def redo_slide(slide: int, out: Path, flat: Path | None, flat_id: str) -> None:
    """Перерисовать один слайд во всех уже собранных каруселях (те же кадры по manifest.json)."""
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    folder = C.SLIDES[slide - 1][0]
    cache: dict = {}
    for i, m in enumerate(manifest, 1):
        name = m["frames"][slide - 1]
        if name not in cache:
            layer, box = place(slide - 1, name)
            bad = check_box(W, H, box)
            if bad:
                raise SystemExit(f"{name}: текст вне безопасной зоны — {bad}")
            cache[name] = layer
        dest = out / m["carousel"] / f"{slide}.jpg"
        frame(folder / name, slide - 1, cache[name]).save(dest, quality=95)
        if flat:
            suffix = f"_{flat_id}" if flat_id else ""
            shutil.copy2(dest, flat / f"sort_{slide}_{i}{suffix}.jpg")
    print(f"слайд {slide} перерисован в {len(manifest)} каруселях")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=1307)
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_<id>.jpg")
    ap.add_argument("--flat-id", default="")
    ap.add_argument("--qa", action="store_true", help="QA-листы: все кадры слайда с текстом и зонами")
    ap.add_argument("--redo-slide", type=int, help="перерисовать только этот слайд в уже собранных каруселях")
    args = ap.parse_args()
    if args.redo_slide:
        redo_slide(args.redo_slide, args.out, args.flat, args.flat_id)
        return 0
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    pools = [sorted(f for f in d.iterdir() if f.is_file() and f.suffix.lower() in C.EXT and not f.name.startswith("_"))
             for d, *_ in C.SLIDES]
    print("кадров: " + " · ".join(f"{d.name} {len(p)}" for (d, *_), p in zip(C.SLIDES, pools)), flush=True)
    layers: dict = {}
    for k, pool in enumerate(pools):
        for src in pool:
            layer, box = place(k, src.name)
            bad = check_box(W, H, box)
            if bad:
                raise SystemExit(f"{C.SLIDES[k][0].name}/{src.name}: текст вне безопасной зоны — {bad}")
            layers[src], layers[(src, "box")] = layer, box

    args.out.mkdir(parents=True, exist_ok=True)
    if args.qa:
        tw, th = 270, 360
        for k, pool in enumerate(pools):
            sheet = Image.new("RGB", (tw * len(pool), th), "white")
            for i, src in enumerate(pool):
                im = draw_overlay(frame(src, k, layers[src]))
                dr = ImageDraw.Draw(im)
                dr.rectangle(layers[(src, "box")], outline=(255, 255, 0), width=5)
                dr.text((12, 12), src.name, fill=(255, 255, 0))
                sheet.paste(im.resize((tw, th)), (i * tw, 0))
            sheet.save(args.out / f"_qa_{k + 1}_{C.SLIDES[k][0].name}.jpg", quality=86)

    carousels = G.plan(args.n, pools, random.Random(args.seed))
    manifest = []
    for i, combo in enumerate(carousels, 1):
        d = args.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, src in enumerate(combo, 1):
            frame(src, k - 1, layers[src]).save(d / f"{k}.jpg", quality=95)
            if args.flat:
                args.flat.mkdir(parents=True, exist_ok=True)
                suffix = f"_{args.flat_id}" if args.flat_id else ""
                shutil.copy2(d / f"{k}.jpg", args.flat / f"sort_{k}_{i}{suffix}.jpg")
        manifest.append({"carousel": d.name, "frames": [p.name for p in combo]})
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    for k, (d, *_r) in enumerate(C.SLIDES):
        c = Counter(m["frames"][k] for m in manifest)
        print(f"{d.name}: {len(c)} кадров, повторов {min(c.values())}–{max(c.values())}")
    print(f"уникальных каруселей: {len({tuple(m['frames']) for m in manifest})} из {len(manifest)}")
    print(f"готово: {len(manifest)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
