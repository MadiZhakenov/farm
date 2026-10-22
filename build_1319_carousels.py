#!/usr/bin/env python3
"""
1319 — Inspoy, карусель «Hot Girl Halloween Costumes»: слайды 3:4 (1080×1440). Тексты — дословно из ТЗ,
TikTok-шрифт (белый с обводкой, типографика build_1281_carousels), только внутри безопасной рамки core/safe_zones
(3:4: x 180–900, y 6–78 %).
  s1 обложка — девушка: белый текст с обводкой под подбородком (MediaPipe), кегль — сколько влезет;
  s2–s4 костюм на кровати: название — чёрный TikTok-шрифт с белой обводкой на простыне над вещами
  (полоса от верха рамки до верхней вещи; BOXES — запасные места, где полоса узкая), кегль —
  максимальный, что влезает; s5 — та же девушка в костюме (лицо за телефоном): текст ТЗ и под ним карточка
  App Store (app_card, как в рефе) — под телефоном. 4 девушки: обложка s1_<д>_* ↔ финал s5_<д>, поровну.

Кадры: output/1319_slides/s1…s4/*.jpg — генерации пользователя (Google Flow, 3:4 896×1200; 9:16 — в _916).

  python build_1319_carousels.py --qa --out output/carousels_1319_test -n 4
  python build_1319_carousels.py -n 100 --out output/carousels_1319 --flat output/1319_100 --flat-id 1319 --qa
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
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1281_carousels as B  # noqa: E402  (text_block — TikTok-текст с обводкой)
import build_grandma_carousels as G  # noqa: E402  (plan — равномерные уникальные комбинации)
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402

W, H = 1080, 1440
X0, Y0, X1, Y1 = text_rect(W, H)
NL = chr(10)
SL = ROOT / "output" / "1319_slides"
EXT = (".jpg", ".jpeg", ".png", ".webp")

# папка, варианты текста (переносы по смыслу), режим, макс. кегль
SLIDES = [
    (SL / "s1", [NL.join(["Hot Girl", "Halloween Costumes.", "", "(the last one is spicy)"])], "face", 72),
    (SL / "s2", ["Mean Girl Cat", NL.join(["Mean Girl", "Cat"])], "top", 96),
    (SL / "s3", ["Witch, Please", NL.join(["Witch,", "Please"])], "top", 96),
    (SL / "s4", ["Fallen Angel", NL.join(["Fallen", "Angel"])], "top", 96),
    (SL / "s5", [NL.join(["which one should I wear?", "", "tried them all on in Inspoy:", "Outfit Maker, Planner 🎃"])],
     "app", 56),
]
# девушки: обложка s1_<девушка>_<кадр> ↔ финал s5_<девушка> (одна и та же девушка в карусели)
GIRLS = ["001", "007", "009", "022"]
# s5: верх блока «текст + карточка» — сразу под телефоном/рукой (доля кадра)
APP_TOP = {"s5_001": 0.465, "s5_007": 0.395, "s5_009": 0.465, "s5_022": 0.375}
# доп. места у кадров, где полоса над вещами узкая (доли кадра x0, y0, x1, y1; внутри рамки 3:4)
BOXES: dict[str, list[tuple[float, float, float, float]]] = {}
# полосы по ширине, в которых ищем пустую простыню над вещами (шляпа ведьмы часто сбоку)
SPANS = [(0.0, 1.0), (0.0, 0.5), (0.5, 1.0), (0.0, 0.62), (0.38, 1.0)]
LABEL_MIN_PX = 40
GAP = 16                                              # отступ текста от вещей / подбородка, px


def fit_bg(src: Path) -> Image.Image:
    """Кадры Flow уже 3:4 (896×1200) → 1080×1440."""
    im = Image.open(src).convert("RGB")
    im = ImageOps.fit(im, (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    return im.filter(ImageFilter.UnsharpMask(radius=1.4, percent=55, threshold=2))


def block(text: str, px: int) -> Image.Image:
    return B.text_block(text, H, px)


def label_block(text: str, px: int) -> Image.Image:
    """Чёрный TikTok-текст с белой обводкой (стиль outline): читается и у чёрных вещей; строки по центру."""
    font, adv = B.R._load_font(px), B.R.line_advance_for(px)
    sw = max(3, round(px * 0.07))
    lines = text.split(NL)
    img = Image.new("RGBA", (W, adv * len(lines) + adv), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        d.text((W / 2, i * adv + adv * 0.8), ln, font=font, anchor="ms", fill=(0, 0, 0, 255),
               stroke_width=sw, stroke_fill=(255, 255, 255, 255))
    return img.crop(img.getbbox())


def items_top(bg: Image.Image, x0: int = X0, x1: int = X1) -> int:
    """Верх самой верхней вещи в полосе x0–x1: тёмное / цветное / металл относительно простыни.
    Пятна, касающиеся верхнего/боковых краёв кадра, — стена, изголовье, пол вокруг кровати, не вещи."""
    a = np.asarray(bg)
    g = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY).astype(np.float32)
    sat = cv2.cvtColor(a, cv2.COLOR_RGB2HSV)[..., 1].astype(np.float32)
    sheet = np.median(g[Y0:Y1, X0:X1])
    m = ((g < sheet * 0.80) | (sat > 45)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, st, _c = cv2.connectedComponentsWithStats(m, 8)
    edge = [i for i in range(1, n) if st[i, cv2.CC_STAT_TOP] == 0 or st[i, cv2.CC_STAT_LEFT] == 0
            or st[i, cv2.CC_STAT_LEFT] + st[i, cv2.CC_STAT_WIDTH] >= W]
    m[np.isin(lab, edge)] = 0
    m = m[:, x0:x1]
    rows = np.where(m.sum(axis=1) > 12)[0]
    rows = rows[rows >= Y0]
    return int(rows[0]) if len(rows) else Y1


_FL = None


def chin_y(bg: Image.Image) -> int | None:
    global _FL
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    if _FL is None:
        _FL = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "face_landmarker.task")), num_faces=1))
    r = _FL.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(bg).copy()))
    return int(max(q.y for q in r.face_landmarks[0]) * H) if r.face_landmarks else None


def fit_label(texts: list[str], max_px: int, box: tuple[int, int, int, int]) -> tuple[int, str] | None:
    bw, bh = box[2] - box[0], box[3] - box[1]
    for p in range(max_px, LABEL_MIN_PX - 1, -2):
        for t in texts:
            b = label_block(t, p)
            if b.width <= bw and b.height <= bh:
                return p, t
    return None


# карточка App Store (s5) — как в рефе: шапка страницы приложения из скрина iPhone (тёмная тема), без «поделиться»
ICON = ROOT / "downloads" / "1319" / "inspoy_icon_1024.png"
F_SEMI, F_REG = ROOT / "fonts" / "inter" / "Inter-SemiBold.ttf", ROOT / "fonts" / "inter" / "Inter-Regular.ttf"
APP_TITLE, APP_SUB = ["Inspoy: Outfit", "Maker, Planner"], "Applabel LTD"


def app_card(width: int) -> Image.Image:
    """Рисуем в масштабе скрина (экран 923 px) и уменьшаем до width."""
    from PIL import ImageFont
    cw, ch = 760, 330
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
    ic = Image.open(ICON).convert("RGBA").resize((272, 272), Image.Resampling.LANCZOS)
    mask = Image.new("L", (272 * 4, 272 * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 272 * 4 - 1, 272 * 4 - 1), radius=int(272 * 4 * 0.2237), fill=255)
    ic.putalpha(mask.resize((272, 272), Image.Resampling.LANCZOS))
    img.alpha_composite(ic, (28, 29))
    d = ImageDraw.Draw(img)
    ft, fs = ImageFont.truetype(str(F_SEMI), 50), ImageFont.truetype(str(F_REG), 34)
    for i, ln in enumerate(APP_TITLE):
        d.text((342, 78 + i * 60), ln, font=ft, anchor="ls", fill=(255, 255, 255, 255))
    d.text((342, 190), APP_SUB, font=fs, anchor="ls", fill=(142, 142, 147, 255))
    d.rounded_rectangle((342, 230, 515, 303), radius=37, fill=(10, 132, 255, 255))
    d.text((428, 267), "Get", font=ImageFont.truetype(str(F_SEMI), 36), anchor="mm", fill=(255, 255, 255, 255))
    fp = ImageFont.truetype(str(F_REG), 19)
    d.text((530, 262), "In-App", font=fp, anchor="ls", fill=(142, 142, 147, 255))
    d.text((530, 285), "Purchases", font=fp, anchor="ls", fill=(142, 142, 147, 255))
    return img.resize((width, round(ch * width / cw)), Image.Resampling.LANCZOS)


def place(k: int, src: Path, bg: Image.Image) -> tuple[Image.Image, tuple[int, int, int, int], float]:
    _d, texts, mode, max_px = SLIDES[k]
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if mode == "top":                                 # название — на простыне над вещами, по центру
        spans = [(X0 + int(a * (X1 - X0)), X0 + int(b * (X1 - X0))) for a, b in SPANS]
        boxes = [(a, Y0, b, items_top(bg, a, b) - GAP) for a, b in spans]
        boxes += [(int(a * W), int(b * H), int(c * W), int(d * H)) for a, b, c, d in BOXES.get(src.stem, [])]
        fits = [(f, bx) for bx in boxes if bx[3] > bx[1] and (f := fit_label(texts, max_px, bx))]
        if not fits:
            raise SystemExit(f"{src.name}: нет места под название")
        (p, t), bx = max(fits, key=lambda v: v[0][0])
        b = label_block(t, p)
        x, y = (bx[0] + bx[2] - b.width) // 2, (bx[1] + bx[3] - b.height) // 2
        out.alpha_composite(b, (x, y))
        return out, (x, y, x + b.width, y + b.height), float(p)
    if mode == "face":                                # обложка: текст под подбородком, кегль — сколько влезет
        chin = chin_y(bg)
        if chin is None:
            raise SystemExit(f"{src.name}: лицо не найдено")
        top = chin + GAP
        px = max_px
        b = block(texts[0], px)
        while (b.width > X1 - X0 or b.height > Y1 - top) and px > LABEL_MIN_PX:
            px -= 2
            b = block(texts[0], px)
        x, y = (W - b.width) // 2, top + (Y1 - top - b.height) // 2
        out.alpha_composite(b, (x, y))
        return out, (x, y, x + b.width, y + b.height), float(px)
    if mode == "app":                                 # финал: текст ТЗ и под ним карточка App Store — под телефоном
        top = int(APP_TOP[src.stem] * H)
        for px in range(max_px, LABEL_MIN_PX - 1, -2):
            b, c = block(texts[0], px), app_card(min(X1 - X0, round(px * 12.5)))
            h = b.height + GAP + c.height
            if b.width <= X1 - X0 and h <= Y1 - top:
                break
        y = top + (Y1 - top - h) // 3
        out.alpha_composite(b, ((W - b.width) // 2, y))
        out.alpha_composite(c, ((W - c.width) // 2, y + b.height + GAP))
        x0 = min((W - b.width) // 2, (W - c.width) // 2)
        return out, (x0, y, W - x0, y + h), float(px)
    raise ValueError(mode)


def plan_girls(n: int, pools: list[list[Path]], rng: random.Random) -> list[list[Path]]:
    """n каруселей поровну на девушек (по кругу); обложка — кадры этой девушки по очереди, финал — её s5;
    слайды 2–4 — G.plan (равномерно, все тройки разные)."""
    mids = G.plan(n, pools[1:4], rng)
    covers = {g: [p for p in pools[0] if p.stem.startswith(f"s1_{g}_")] for g in GIRLS}
    finals = {g: next(p for p in pools[4] if p.stem == f"s5_{g}") for g in GIRLS}
    for g in GIRLS:
        rng.shuffle(covers[g])
    out = []
    for i, mid in enumerate(mids):
        g = GIRLS[i % len(GIRLS)]
        out.append([covers[g][(i // len(GIRLS)) % len(covers[g])], *mid, finals[g]])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=3)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=1319)
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
            layer, box, frac = place(k, src, bg)
            bad = check_box(W, H, box)
            if bad:
                raise SystemExit(f"{SLIDES[k][0].name}/{src.name}: текст вне безопасной зоны — {bad}")
            print(f"  {SLIDES[k][0].name}/{src.name}: {frac:.0f} px")
            frames[src] = (Image.alpha_composite(bg.convert("RGBA"), layer).convert("RGB"), box)

    args.out.mkdir(parents=True, exist_ok=True)
    if args.qa:
        tw, th = 324, 576
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

    carousels = plan_girls(args.n, pools, random.Random(args.seed))
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
        assert combo[0].stem.split("_")[1] == combo[4].stem.split("_")[1], combo     # обложка и финал — одна девушка
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
