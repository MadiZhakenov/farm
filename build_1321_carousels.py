#!/usr/bin/env python3
"""
1321 — Inspoy, карусель-история «my grandma had 7 husbands 😳and…»: 6 слайдов 3:4 (1080×1440). Тексты — дословно
из ТЗ, переносы по смыслу, TikTok-шрифт (белый с обводкой, типографика build_1281_carousels), только внутри
безопасной рамки core/safe_zones (3:4: x 180–900, y 6–78 %). Одна девушка и одна бабушка на все карусели:
лица видны на s1, s2, s6 (s2 и s6 — правки кадра s1 во Flow), образы s3–s5 — селфи в зеркало, лицо за телефоном.
  s1 внучка с бабушкой, s2 бабушка у шкафа, s6 их селфи: текст под самым нижним подбородком (MediaPipe);
  s3–s5 «Husband #N look»: название сверху рамки, над головой;
  s6: текст ТЗ и под ним карточка App Store (app_card из 1319).

Кадры: output/1321_slides/s1…s6/*.jpg — генерации пользователя (Google Flow, 3:4 896×1200).

  python build_1321_carousels.py --qa --out output/carousels_1321_test -n 1
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
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1319_carousels as C  # noqa: E402  (block — TikTok-текст с обводкой, app_card)
import build_1307_carousels as P7  # noqa: E402  (plate_block — чёрный текст на белых плашках TikTok)
import build_grandma_carousels as G  # noqa: E402  (plan — равномерные уникальные комбинации)
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402

W, H = 1080, 1440
X0, Y0, X1, Y1 = text_rect(W, H)
NL = chr(10)
SL = ROOT / "output" / "1321_slides"
EXT = (".jpg", ".jpeg", ".png", ".webp")
GAP = 22
MIN_PX = 36

# папка, текст ТЗ с переносами по смыслу, режим, макс. кегль
SLIDES = [
    (SL / "s1", NL.join(["my grandma had", "7 husbands 😳and…"]), "plate", 70),     # клиент: белая подложка,
    (SL / "s2", NL.join(["she said the whole secret", "is in the clothes.", "", "and she picked outfits for me"]),
     "plate", 56),                                                                    # чёрный шрифт
    (SL / "s3", "Husband #1 look", "title", 76),
    (SL / "s4", "Husband #4 look", "title", 76),
    (SL / "s5", "Husband #7 look", "title", 76),
    (SL / "s6", NL.join(["she put all these looks together in", "Inspoy: Outfit Maker, Planner.", "",
                         "looks like I'll find a husband soon too 🥹"]), "app", 52),
]
CHIN_DEFAULT = 0.45


def fit_bg(src: Path) -> Image.Image:
    im = Image.open(src).convert("RGB")
    im = ImageOps.fit(im, (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    return im.filter(ImageFilter.UnsharpMask(radius=1.4, percent=55, threshold=2))


_FL = None


def chins_y(bg: Image.Image) -> int:
    """Самый нижний подбородок (до двух лиц): весь кадр и верхний квадрат в нескольких масштабах."""
    global _FL
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    if _FL is None:
        _FL = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "face_landmarker.task")), num_faces=2,
            min_face_detection_confidence=0.2, min_face_presence_confidence=0.2))
    found = []
    for y0, y1 in ((0, H), (0, W)):
        crop = bg.crop((0, y0, W, y1))
        for sc in (1.0, 0.6, 0.4):
            im = crop.resize((round(crop.width * sc), round(crop.height * sc)))
            r = _FL.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(im).copy()))
            found += [y0 + max(q.y for q in f) * (y1 - y0) for f in r.face_landmarks]
    return int(max(found)) if found else int(CHIN_DEFAULT * H)


def fit_text(text: str, max_px: int, max_h: int) -> tuple[Image.Image, int]:
    px = max_px
    b = C.block(text, px)
    while (b.width > X1 - X0 or b.height > max_h) and px > MIN_PX:
        px -= 2
        b = C.block(text, px)
    return b, px


def plates(text: str, px: int) -> Image.Image:
    """Абзацы — отдельные блоки белых плашек TikTok (чёрный текст), между ними отступ."""
    norm = C.B.A.sanitize_overlay_text
    blocks = [P7.plate_block([norm(C.B.R._normalize_text(ln)) for ln in par.split(NL)], px)
              for par in text.split(NL + NL)]
    gap = round(px * 0.35)
    out = Image.new("RGBA", (max(b.width for b in blocks), sum(b.height for b in blocks) + gap * (len(blocks) - 1)))
    y = 0
    for b in blocks:
        out.alpha_composite(b, ((out.width - b.width) // 2, y))
        y += b.height + gap
    return out


def place(k: int, src: Path, bg: Image.Image) -> tuple[Image.Image, tuple[int, int, int, int], float]:
    _d, text, mode, max_px = SLIDES[k]
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if mode == "title":                               # название образа — сверху рамки, над головой
        b, px = fit_text(text, max_px, H)
        x, y = (W - b.width) // 2, Y0 + GAP
        out.alpha_composite(b, (x, y))
        return out, (x, y, x + b.width, y + b.height), float(px)
    top = min(chins_y(bg) + GAP, Y1 - 160)
    if mode == "plate":                               # чёрный текст на белой подложке под подбородками
        px = max_px
        b = plates(text, px)
        while (b.width > X1 - X0 or b.height > Y1 - top) and px > MIN_PX:
            px -= 2
            b = plates(text, px)
        x, y = (W - b.width) // 2, top + (Y1 - top - b.height) // 3
        out.alpha_composite(b, (x, y))
        return out, (x, y, x + b.width, y + b.height), float(px)
    if mode == "chin":                                # текст под подбородками, ближе к лицам
        b, px = fit_text(text, max_px, Y1 - top)
        x, y = (W - b.width) // 2, top + (Y1 - top - b.height) // 3
        out.alpha_composite(b, (x, y))
        return out, (x, y, x + b.width, y + b.height), float(px)
    if mode == "app":                                 # текст, под ним карточка App Store
        for px in range(max_px, MIN_PX - 1, -2):
            b, c = C.block(text, px), C.app_card(min(X1 - X0, round(px * 12.5)))
            h = b.height + GAP + c.height
            if b.width <= X1 - X0 and h <= Y1 - top:
                break
        y = top + (Y1 - top - h) // 3
        out.alpha_composite(b, ((W - b.width) // 2, y))
        out.alpha_composite(c, ((W - c.width) // 2, y + b.height + GAP))
        x0 = min((W - b.width) // 2, (W - c.width) // 2)
        return out, (x0, y, W - x0, y + h), float(px)
    raise ValueError(mode)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=1321)
    ap.add_argument("--qa", action="store_true", help="QA-листы: все кадры слайда с текстом и зонами")
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_<id>.jpg")
    ap.add_argument("--flat-id", default="")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    pools = [sorted(f for f in d.iterdir() if f.is_file() and f.suffix.lower() in EXT and not f.name.startswith("_"))
             for d, *_ in SLIDES]
    print("кадров: " + " · ".join(f"{d.name} {len(p)}" for (d, *_), p in zip(SLIDES, pools)), flush=True)
    frames: dict = {}
    for k, pool in enumerate(pools):
        for src in pool:
            bg = fit_bg(src)
            layer, box, px = place(k, src, bg)
            bad = check_box(W, H, box)
            if bad:
                raise SystemExit(f"{SLIDES[k][0].name}/{src.name}: текст вне безопасной зоны — {bad}")
            print(f"  {SLIDES[k][0].name}/{src.name}: {px:.0f} px")
            frames[src] = (Image.alpha_composite(bg.convert("RGBA"), layer).convert("RGB"), box)

    args.out.mkdir(parents=True, exist_ok=True)
    if args.qa:
        tw, th = 324, 432
        for k, pool in enumerate(pools):
            sheet = Image.new("RGB", (tw * len(pool), th), "white")
            for i, src in enumerate(pool):
                im, box = frames[src]
                im = draw_overlay(im.copy())
                dr = ImageDraw.Draw(im)
                dr.rectangle(box, outline=(255, 255, 0), width=6)
                dr.text((14, 14), src.name, fill=(255, 255, 0))
                sheet.paste(im.resize((tw, th)), (i * tw, 0))
            sheet.save(args.out / f"_qa_{k + 1}_{SLIDES[k][0].name}.jpg", quality=86)

    carousels = G.plan(args.n, pools, random.Random(args.seed))
    manifest = []
    for i, combo in enumerate(carousels, 1):
        d = args.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, src in enumerate(combo, 1):
            frames[src][0].save(d / f"{k}.jpg", quality=95)
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
