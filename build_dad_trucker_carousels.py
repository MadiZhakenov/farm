#!/usr/bin/env python3
"""
Папа-дальнобойщик (Inspoy, айди нет): 7 слайдов 3:4 (1080×1440), по одному Flow-кадру на слайд
(output/dad_trucker_slides/final/s1..s7/*.jpg — оригинал + 3 серийных кадра). Тексты ТЗ дословно, переносы по смыслу, TikTok-шрифт с обводкой
(как 1283/1385), только в безопасной рамке. Цвет ярче (кадры из Flow тусклые). s7 — без телефона (клиент):
выбор образа на кровати + карточка Inspoy из App Store (build_1319.app_card). Уникальность 150 каруселей: своё сочетание кадров (4^7), зум/сдвиг, оттенок и место текста у каждой.

  python build_dad_trucker_carousels.py -n 4 --out output/dad_trucker_test
  python build_dad_trucker_carousels.py -n 150 --out output/carousels_dad_trucker --flat output/dad_trucker_150
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1283_carousels as C  # noqa: E402  (block_for — TikTok-текст с обводкой и эмодзи)
import strip_jpeg_meta  # noqa: E402
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402

W, H = 1080, 1440
X0, Y0, X1, Y1 = text_rect(W, H)
SL = ROOT / "output" / "dad_trucker_slides" / "final"
SCREENS = sorted((ROOT / "downloads" / "1329" / "inspoy").glob("screen_*.webp"))
NL = "\n"
C.B.PX_MAX = 64

# текст ТЗ дословно; (текст, центр блока по высоте, макс. высота блока) — полоса подобрана под каждый кадр
SLIDES = [
    ("my dad drives trucks for a living\nand gave me the best\nfashion advice of my life", 0.675, 0.19),  # под лицами
    ("“if you have to adjust it all day,\ntake it off”", 0.12, 0.12),         # над зеркалом
    ("“one good coat\nis better than\nfour okay ones”", 0.145, 0.17),        # по красной кабине
    ("“clean shoes\nmake any outfit\nlook expensive”", 0.145, 0.17),         # по красной панели
    ("“don’t dress like\neveryone else\njust to be liked”", 0.14, 0.16),     # потолок магазина
    ("“wear what makes you\nstand a little straighter”", 0.12, 0.12),        # стена лифта над головой
    ("i pick my outfits in Inspoy\nand think about this\nevery time", 0.145, 0.17),
]


def vivid(im: Image.Image, rng: random.Random) -> Image.Image:
    """Кадры Flow тусклые: сочнее, чуть контрастнее и светлее; у каждой карусели свой лёгкий оттенок."""
    im = ImageEnhance.Color(im).enhance(rng.uniform(1.22, 1.32))
    im = ImageEnhance.Contrast(im).enhance(rng.uniform(1.06, 1.10))
    im = ImageEnhance.Brightness(im).enhance(rng.uniform(1.03, 1.07))
    a = np.asarray(im).astype(np.float32)
    warm = rng.uniform(-3, 5)
    a[..., 0] += warm
    a[..., 2] -= warm
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def frame(src: Path, rng: random.Random) -> Image.Image:
    """Кадр 3:4 → 1080×1440 с лёгким зумом и сдвигом (своим у каждой карусели)."""
    im = Image.open(src).convert("RGB")
    z = rng.uniform(1.0, 1.06)
    w, h = im.width / z, im.height / z
    x, y = rng.uniform(0, im.width - w), rng.uniform(0, im.height - h)
    return im.crop((round(x), round(y), round(x + w), round(y + h))).resize((W, H), Image.Resampling.LANCZOS)


def phone_screen(src: Path, screen: Path) -> Image.Image:
    """s7: в белый пустой экран телефона кладём настоящий экран Inspoy по 4 углам; маска — только белые пиксели
    экрана, поэтому палец, вырез и рамка остаются сверху."""
    im = Image.open(src).convert("RGB")
    a = np.asarray(im).astype(np.int32)
    m = ((a.min(2) > 205) & (np.ptp(a, 2) < 22)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    k = max(range(1, n), key=lambda i: st[i, 4] if st[i, 3] > st[i, 2] * 1.6 else 0)   # высокий узкий — экран
    comp = (lab == k).astype(np.uint8) * 255
    cnt = max(cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)
    pts = cnt.reshape(-1, 2).astype(np.float32)
    s, d = pts.sum(1), pts[:, 0] - pts[:, 1]
    quad = np.float32([pts[s.argmin()], pts[d.argmax()], pts[s.argmax()], pts[d.argmin()]])   # TL TR BR BL
    c = quad.mean(0)
    quad = c + (quad - c) * 1.04                                       # углы скруглены — чуть шире
    scr = np.asarray(Image.open(screen).convert("RGB")).astype(np.float32)
    sh, sw = scr.shape[:2]
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [sw, 0], [sw, sh], [0, sh]]), quad)
    warp = cv2.warpPerspective(scr, M, (im.width, im.height), flags=cv2.INTER_AREA)
    warp = warp * 0.93 + 6                                             # экран чуть темнее бумаги белого
    mask = cv2.GaussianBlur(cv2.dilate(comp, np.ones((3, 3), np.uint8)), (3, 3), 0).astype(np.float32)[..., None] / 255
    out = a * (1 - mask) + warp * mask
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


CARD_W, CARD_CY = 700, 0.655                           # s7: карточка Inspoy из App Store (как 1385/1390)


def store_card() -> Image.Image:
    import build_1319_carousels as C1319
    c = C1319.app_card(CARD_W).convert("RGBA")
    m = Image.new("L", (c.width * 4, c.height * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, c.width * 4 - 1, c.height * 4 - 1), radius=round(c.height * 4 * 0.1), fill=255)
    c.putalpha(m.resize(c.size, Image.Resampling.LANCZOS))
    return c                                             # без полупрозрачной тени-обводки (клиент)


def caption(k: int, rng: random.Random) -> tuple[Image.Image, tuple]:
    text, cy, mh = SLIDES[k]
    cy += rng.uniform(-0.008, 0.008)
    top, bottom = max(int((cy - mh / 2) * H), Y0), min(int((cy + mh / 2) * H), Y1)
    block = C.block_for(text, bottom - top, X1 - X0)
    x = int(W / 2 - block.width / 2 + rng.randint(-14, 14))
    x = max(X0, min(X1 - block.width, x))
    y = max(Y0, min(Y1 - block.height, int((top + bottom) / 2 - block.height / 2)))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.alpha_composite(block, (x, y))
    return layer, (x, y, x + block.width, y + block.height)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=4)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_noid.jpg")
    ap.add_argument("--seed", type=int, default=77)
    ap.add_argument("--qa", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    pools = [sorted((SL / f"s{k}").glob("*.jpg")) for k in range(1, 8)]
    plan_rng = random.Random(a.seed)
    combos = list(itertools.product(*[range(len(pl)) for pl in pools]))
    plan_rng.shuffle(combos)
    used: dict = {}
    picks = []
    for _ in range(a.n):                                   # сочетание с наименее использованными кадрами
        best = min(combos[:3000], key=lambda c: (sum(used.get((k, j), 0) for k, j in enumerate(c)), plan_rng.random()))
        combos.remove(best)
        for k, j in enumerate(best):
            used[(k, j)] = used.get((k, j), 0) + 1
        picks.append([pools[k][j] for k, j in enumerate(best)])
    a.out.mkdir(parents=True, exist_ok=True)
    manifest, qa = [], []
    for i in range(1, a.n + 1):
        rng = random.Random(a.seed * 1000 + i)
        d = a.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, src in enumerate(picks[i - 1]):
            im = vivid(frame(src, rng), rng).convert("RGBA")
            layer, box = caption(k, rng)
            if bad := check_box(W, H, box):
                raise SystemExit(f"{i:03d} слайд {k + 1}: текст вне безопасной зоны {box} — {bad}")
            if k == 6:                                         # последний слайд — скрин карточки App Store
                card = store_card()
                cx, cy = (W - card.width) // 2, round(CARD_CY * H - card.height / 2)
                im.alpha_composite(card, (cx, cy))
                pad = (card.width - CARD_W) // 2
                if bad := check_box(W, H, (cx + pad, cy + pad, cx + card.width - pad, cy + card.height - pad)):
                    raise SystemExit(f"{i:03d} карточка App Store вне безопасной зоны — {bad}")
            out = Image.alpha_composite(im, layer).convert("RGB")
            out.save(d / f"{k + 1}.jpg", quality=93)
            if a.qa and i <= 2:
                q = draw_overlay(out)
                ImageDraw.Draw(q).rectangle(box, outline=(255, 220, 0), width=5)
                qa.append(q)
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d / f"{k + 1}.jpg", a.flat / f"sort_{k + 1}_{i}_noid.jpg")
        manifest.append({"carousel": d.name, "frames": [f.name for f in picks[i - 1]]})
        print(f"  {d.name}", flush=True)
    if qa:
        tw, th = 300, 400
        sheet = Image.new("RGB", (7 * tw, (len(qa) // 7) * th), (30, 30, 30))
        for j, q in enumerate(qa):
            sheet.paste(q.resize((tw, th)), ((j % 7) * tw, (j // 7) * th))
        sheet.save(a.out / "_qa.jpg", quality=86)
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    sys.argv = ["strip", str(a.out)] + ([str(a.flat)] if a.flat else [])
    strip_jpeg_meta.main()
    print(f"готово: {a.n} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
