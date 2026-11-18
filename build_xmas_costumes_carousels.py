#!/usr/bin/env python3
"""
Inspoy — «hot christmas costumes» (айди нет): 7 слайдов 3:4 (1080×1440), по формату нашей 1319 (build_1319_carousels).
  s1 обложка: девушка, зеркальное селфи в её тёплой комнате — белый TikTok-текст на платье ниже рук с телефоном
  s2–s6 образы на ЕЁ кровати (mrs. claus / the elf / snowflake / reindeer / chic grinch) — чёрное название с белой
       обводкой в свободной полосе над вещами (стена над кроватью)
  s7 та же девушка в образе, телефон закрывает лицо — текст ТЗ + карточка Inspoy из App Store (app_card 1319)
Фото — output/xmas_costumes/slides/s<k>/*.jpg (Flow). Тексты ТЗ дословно, переносы по смыслу, безопасная рамка,
у каждой карусели свой набор кадров + лёгкий зум/сдвиг. Метаданные JPEG вычищаются.

  python build_xmas_costumes_carousels.py -n 2 --out output/xmas_costumes_test --qa
  python build_xmas_costumes_carousels.py -n 100 --out output/carousels_xmas --flat output/xmas_100
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1319_carousels as K  # noqa: E402  (fit_bg, block, label_block, chin_y, items_top, app_card)
import strip_jpeg_meta  # noqa: E402
from core.safe_zones import check_box, draw_overlay  # noqa: E402

W, H = K.W, K.H
X0, Y0, X1, Y1 = K.X0, K.Y0, K.X1, K.Y1
NL = chr(10)
SL = ROOT / "output" / "xmas_costumes" / "slides"

# текст ТЗ дословно; режим как в 1319: face — под подбородком, top — над вещами, app — текст + карточка App Store
SLIDES = [
    ([NL.join(["hot christmas", "costumes 🎄"])], "low", 84),
    (["mrs. claus", NL.join(["mrs.", "claus"])], "top", 104),
    (["the elf"], "top", 104),
    (["snowflake"], "top", 104),
    (["reindeer"], "top", 104),
    (["chic grinch", NL.join(["chic", "grinch"])], "top", 104),
    ([NL.join(["i found all of this in Inspoy:", "Outfit Maker, Planner", "", "and planned it", "the night before btw 🎄"])],
     "app", 56),
]
APP_TOP = 0.33                                         # s7: верх блока «текст + карточка» — под телефоном (доля кадра)
COVER_BAND = (0.53, 0.72)                             # s1: текст на платье ниже рук с телефоном (доли кадра)
# s2–s6: название на стене над кроватью — сначала между ёлкой и дверью, иначе на всю ширину рамки (доли кадра)
WALL_BOXES = [(0.33, 0.0, 1.0, 0.25), (0.0, 0.0, 1.0, 0.25)]
TITLE_OK_PX = 56                                       # полосы по порядку: первая, где влезает кегль ≥ этого


GRADE = False                                          # True — «живой свежий» цвет (кадры Flow тусклые и жёлтые от лампы)


def fresh(im: Image.Image, rng: random.Random) -> Image.Image:
    """Жёлтый налёт лампы — к нейтральному на ~35 %, затем чуть сочнее, контрастнее и светлее (у каждой карусели своё)."""
    a = np.asarray(im).astype(np.float32)
    m = a.reshape(-1, 3).mean(0)
    a = a * (1 + 0.35 * (m.mean() / m - 1))
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    im = ImageEnhance.Color(im).enhance(rng.uniform(1.12, 1.18))
    im = ImageEnhance.Contrast(im).enhance(rng.uniform(1.05, 1.08))
    return ImageEnhance.Brightness(im).enhance(rng.uniform(1.03, 1.06))


def jitter(im: Image.Image, rng: random.Random) -> Image.Image:
    """Лёгкий зум 1–4 % и сдвиг — у каждой карусели свой."""
    z = rng.uniform(1.015, 1.05)                       # не меньше 1,5 % — иначе два одинаковых кадра совпадают побайтово
    w, h = W / z, H / z
    x, y = rng.uniform(0, W - w), rng.uniform(0, H - h)
    return im.crop((round(x), round(y), round(x + w), round(y + h))).resize((W, H), Image.Resampling.LANCZOS)


def bx_w(bx: tuple) -> int:
    return -(bx[2] - bx[0])                             # при равном кегле — узкая полоса (между ёлкой и дверью)


def place(k: int, bg: Image.Image) -> tuple[Image.Image, tuple]:
    texts, mode, max_px = SLIDES[k]
    if mode == "low":                                  # обложка: на платье, ниже рук с телефоном
        top, bottom = int(COVER_BAND[0] * H), int(COVER_BAND[1] * H)
        px = max_px
        b = K.block(texts[0], px)
        while (b.width > X1 - X0 or b.height > bottom - top) and px > K.LABEL_MIN_PX:
            px -= 2
            b = K.block(texts[0], px)
        x, y = (W - b.width) // 2, top + (bottom - top - b.height) // 2
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        layer.alpha_composite(b, (x, y))
        return layer, (x, y, x + b.width, y + b.height)
    if mode == "top":
        boxes = [(max(X0, int(a * W)), max(Y0, int(b * H)), min(X1, int(c * W)), min(Y1, int(d * H)))
                 for a, b, c, d in WALL_BOXES]
        fits = [(f, bx) for bx in boxes if (f := K.fit_label(texts, max_px, bx))]
        if not fits:
            raise SystemExit(f"слайд {k + 1}: нет места под название")
        good = [v for v in fits if v[0][0] >= TITLE_OK_PX]   # первая полоса из списка, где кегль уже нормальный
        (px, t), bx = good[0] if good else max(fits, key=lambda v: (v[0][0], bx_w(v[1])))
        b = K.label_block(t, px)
        x, y = (bx[0] + bx[2] - b.width) // 2, (bx[1] + bx[3] - b.height) // 2
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        layer.alpha_composite(b, (x, y))
        return layer, (x, y, x + b.width, y + b.height)
    K.SLIDES[0] = (None, texts, mode, max_px)          # 1319 place() берёт текст и режим из своей таблицы
    K.APP_TOP = {"_": APP_TOP}
    layer, box, _px = K.place(0, Path("_.jpg"), bg)
    return layer, box


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_noid.jpg")
    ap.add_argument("--seed", type=int, default=25)
    ap.add_argument("--qa", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    pools = [sorted((SL / f"s{k + 1}").glob("*.jpg")) for k in range(len(SLIDES))]
    for k, pl in enumerate(pools):
        if not pl:
            raise SystemExit(f"нет фото для слайда {k + 1}")
    rng0 = random.Random(a.seed)
    combos = list(itertools.product(*[range(len(pl)) for pl in pools]))
    rng0.shuffle(combos)
    a.out.mkdir(parents=True, exist_ok=True)
    manifest, qa = [], []
    for i in range(1, a.n + 1):
        rng = random.Random(a.seed * 1000 + i)
        picks = [pl[j] for pl, j in zip(pools, combos[(i - 1) % len(combos)])]
        d = a.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, src in enumerate(picks):
            bg = jitter(K.fit_bg(src), rng)
            if GRADE:
                bg = fresh(bg, rng)
            layer, box = place(k, bg)
            if bad := check_box(W, H, box):
                raise SystemExit(f"{i:03d} слайд {k + 1}: вне безопасной зоны {box} — {bad}")
            im = Image.alpha_composite(bg.convert("RGBA"), layer).convert("RGB")
            im.save(d / f"{k + 1}.jpg", quality=93)
            if a.qa and i <= 2:
                q = draw_overlay(im)
                ImageDraw.Draw(q).rectangle(box, outline=(255, 220, 0), width=5)
                qa.append(q)
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d / f"{k + 1}.jpg", a.flat / f"sort_{k + 1}_{i}_noid.jpg")
        manifest.append({"carousel": d.name, "photos": [p.name for p in picks]})
        print(f"  {d.name}", flush=True)
    if qa:
        tw, th = 300, 400
        nc = len(SLIDES)
        sheet = Image.new("RGB", (nc * tw, ((len(qa) + nc - 1) // nc) * th), (30, 30, 30))
        for j, q in enumerate(qa):
            sheet.paste(q.resize((tw, th)), ((j % nc) * tw, (j // nc) * th))
        sheet.save(a.out / "_qa.jpg", quality=86)
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    sys.argv = ["strip", str(a.out)] + ([str(a.flat)] if a.flat else [])
    strip_jpeg_meta.main()
    print(f"готово: {a.n} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
