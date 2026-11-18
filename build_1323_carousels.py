#!/usr/bin/env python3
"""
1323 — Inspoy, карусель «I let an app analyze my face and style»: 5 слайдов 3:4 (1080×1440), 100 уникальных.
Девушка — одна (её селфи прогнано через Inspoy), фото уникализированы ИИ пользователем: output/1323_slides/ai/
  selfie/ (4) · bob/ (4) · ponytail/ (4) · ash/ (4) · makeup/ (4).
  s1 — селфи + заголовок ТЗ чёрным на белых плашках (TikTok) + «(new hair at the end 😭)» белым с обводкой без
       подложки — над головой (под подбородком обе строки не влезают);
  s2–s4 — доски-коллажи из её реальных результатов Inspoy (build_1323_boards.py): анализ лица и цвета / причёски и
       цвета волос / макияж и ногти; у каждой карусели своя цветовая тема (8) и своя раскладка (порядок карточек,
       форма свотчей, порядок примерок и плиток);
  s5 — её фото с каре (на доске причёсок каре нет — там 2 примерки) + финальный текст ТЗ над лбом (белый TikTok с
       обводкой) + карточка App Store под подбородком; фото чуть сдвинуто вверх (s5_layout), каре с слишком крупным
       лицом на s5 не берём.
Все тексты — внутри безопасной рамки 3:4.

  python build_1323_carousels.py -n 3 --out output/carousels_1323_test --qa
  python build_1323_carousels.py -n 100 --out output/carousels_1323 --flat output/1323_100 --qa
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1321_carousels as R  # noqa: E402  (chins_y, plates, C.block, C.app_card)
import build_1323_boards as BD  # noqa: E402
from core.safe_zones import check_box, draw_overlay  # noqa: E402

W, H = R.W, R.H
X0, Y0, X1, Y1 = R.X0, R.Y0, R.X1, R.Y1
NL = R.NL
AI = ROOT / "output" / "1323_slides" / "ai"
SLOTS = ["selfie", "bob", "ponytail", "ash", "makeup"]
TEXT1 = NL.join(["I let an app analyze", "my face and style"])
SUB1 = "(new hair at the end 😭)"
CARD_W = 360                 # карточка App Store на s5
S5_MIN_BAND = 180            # минимум места над лбом под текст s5
TEXT5 = NL.join(["my full analysis in", "Inspoy: Outfit Maker, Planner.", "", "girls you need to try it!"])


def fit_bg(src: Path) -> Image.Image:
    im = Image.open(src).convert("RGB")
    im = ImageOps.fit(im, (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.45))
    return im.filter(ImageFilter.UnsharpMask(radius=1.4, percent=55, threshold=2))


def face_top(bg: Image.Image) -> int:
    import build_1322_carousels as Q
    fb = Q.face_box(bg)
    return int(fb[1]) if fb else Y0 + 300


def slide1(src: Path) -> tuple[Image.Image, tuple]:
    """Заголовок ТЗ на белых плашках + строка SUB1 белым с обводкой (без подложки) — над головой:
    под подбородком на две части места нет."""
    bg = fit_bg(src)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    band = face_top(bg) - R.GAP - Y0
    px = 72
    while True:
        pl, sb = R.plates(TEXT1, px), R.C.block(SUB1, round(px * 0.78))
        gap = round(px * 0.22)
        bw, bh = max(pl.width, sb.width), pl.height + gap + sb.height
        if (bw <= X1 - X0 and bh <= band) or px <= R.MIN_PX:
            break
        px -= 2
    b = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    b.alpha_composite(pl, ((bw - pl.width) // 2, 0))
    b.alpha_composite(sb, ((bw - sb.width) // 2, pl.height + gap))
    x, y = (W - bw) // 2, Y0 + max(0, (band - bh) // 2)
    out.alpha_composite(b, (x, y))
    return Image.alpha_composite(bg.convert("RGBA"), out).convert("RGB"), (x, y, x + bw, y + bh)


def s5_layout(src: Path) -> tuple[Image.Image, int, int, int] | None:
    """Фото с каре сдвигаем вверх на shift (низ свитера продлеваем зеркалом — это зона подписи), чтобы под
    подбородком влезла карточка App Store, а над лбом — текст. None — лицо слишком крупное."""
    bg = fit_bg(src)
    top, chin = face_top(bg), R.chins_y(bg)
    card_h = R.C.app_card(CARD_W).height
    shift = max(0, card_h + R.GAP - (Y1 - chin))
    if top - shift - R.GAP - Y0 < S5_MIN_BAND:
        return None
    if shift:
        im = Image.new("RGB", (W, H))
        im.paste(bg, (0, -shift))
        im.paste(ImageOps.flip(bg.crop((0, H - shift, W, H))), (0, H - shift))
        bg = im
    return bg, top - shift, chin - shift, shift


def slide5(src: Path) -> tuple[Image.Image, tuple]:
    """Текст ТЗ над лбом (белый TikTok с обводкой), карточка App Store под подбородком."""
    bg, top, chin, _ = s5_layout(src)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    b, px = R.fit_text(TEXT5, 56, top - R.GAP - Y0)
    tx, ty = (W - b.width) // 2, Y0 + max(0, (top - R.GAP - Y0 - b.height) // 2)
    out.alpha_composite(b, (tx, ty))
    c = R.C.app_card(CARD_W)
    cx, cy = (W - c.width) // 2, chin + R.GAP + max(0, (Y1 - chin - R.GAP - c.height) // 2)
    out.alpha_composite(c, (cx, cy))
    box = (min(tx, cx), ty, max(tx + b.width, cx + c.width), cy + c.height)
    return Image.alpha_composite(bg.convert("RGBA"), out).convert("RGB"), box


def plan(n: int, seed: int) -> list[dict]:
    """Тема — по кругу; фото — реже всего использованные (с шумом); набор не повторяется."""
    rng = random.Random(seed)
    pool = {s: sorted(p.name for p in (AI / s).glob("*.jpg")) for s in SLOTS}
    pool["bob"] = [p for p in pool["bob"] if s5_layout(AI / "bob" / p)]
    themes = list(BD.THEMES)
    use: Counter = Counter()
    seen, jobs = set(), []
    for i in range(n):
        for _ in range(500):
            pick = lambda s, excl=(): min((p for p in pool[s] if p not in excl),  # noqa: E731
                                          key=lambda p: use[p] + rng.random() * 0.9)
            s1 = pick("selfie")
            b1 = pick("selfie", (s1,))
            job = {"n": i + 1, "theme": themes[i % len(themes)], "s1": s1, "b1": b1,
                   "bob": pick("bob"), "ponytail": pick("ponytail"), "ash": pick("ash"), "makeup": pick("makeup"),
                   "seed": rng.randint(0, 10 ** 6)}
            key = tuple(job[k] for k in ("theme", "s1", "b1", "bob", "ponytail", "ash", "makeup"))
            if key not in seen:
                break
        seen.add(key)
        for k in ("s1", "b1", "bob", "ponytail", "ash", "makeup"):
            use[job[k]] += 1
        jobs.append(job)
    return jobs


def render(job: dict) -> tuple[str, list]:
    d = Path(job["out"]) / f"{job['n']:03d}"
    d.mkdir(parents=True, exist_ok=True)
    rng = random.Random(job["seed"])
    BD.apply_theme(job["theme"])
    sel = lambda s, f: AI / s / f  # noqa: E731
    im1, box1 = slide1(sel("selfie", job["s1"]))
    im1.save(d / "1.jpg", quality=95)
    BD.board1(sel("selfie", job["b1"]), rng).save(d / "2.jpg")
    BD.board2([(sel("ponytail", job["ponytail"]), "High ponytail"), (sel("ash", job["ash"]), "Ash blonde")],
              rng).save(d / "3.jpg")
    BD.board3(sel("makeup", job["makeup"]), rng).save(d / "4.jpg")
    im5, box5 = slide5(sel("bob", job["bob"]))
    im5.save(d / "5.jpg", quality=95)
    bad = check_box(W, H, box1) + check_box(W, H, box5)
    if bad:
        raise SystemExit(f"{d.name}: текст вне безопасной зоны — {bad}")
    if job.get("flat"):
        flat = Path(job["flat"])
        for k in range(1, 6):
            shutil.copy2(d / f"{k}.jpg", flat / f"sort_{k}_{job['n']}_1323.jpg")
    return d.name, [box1, box5]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=3)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--flat", type=Path)
    ap.add_argument("--seed", type=int, default=1323)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--qa", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    jobs = plan(args.n, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.flat:
        args.flat.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        j["out"] = str(args.out)
        j["flat"] = str(args.flat) if args.flat else None
    (args.out / "manifest.json").write_text(json.dumps(jobs, indent=1), encoding="utf-8")
    with ProcessPoolExecutor(args.jobs) as ex:
        for k, (name, _b) in enumerate(ex.map(render, jobs), 1):
            print(f"[{k}/{len(jobs)}] {name}", flush=True)
    if args.qa:
        for k, slot, key in ((1, "selfie", "s1"), (5, "bob", "bob")):
            names = sorted({j[key] for j in jobs})
            sheet = Image.new("RGB", (324 * len(names), 432), "white")
            for i, nm in enumerate(names):
                im, box = (slide1 if k == 1 else slide5)(AI / slot / nm)
                q = draw_overlay(im)
                ImageDraw.Draw(q).rectangle(box, outline=(255, 255, 0), width=6)
                sheet.paste(q.resize((324, 432)), (i * 324, 0))
            sheet.save(args.out / f"_qa_s{k}.jpg", quality=86)
    keys = {tuple(j[k] for k in ("theme", "s1", "b1", "bob", "ponytail", "ash", "makeup")) for j in jobs}
    print(f"тем: {Counter(j['theme'] for j in jobs)}")
    print(f"уникальных каруселей: {len(keys)} из {len(jobs)}")
    print(f"готово: {len(jobs)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
