#!/usr/bin/env python3
"""
1342 — Inspoy, квиз «какой цвет волос тебе идёт»: концепт и дизайн нашей 1322 (реф @emily.vibes28 = наша 1322),
8 слайдов 9:16 (1080×1920). Вёрстка/хелперы — build_1322_carousels (Newsreader, градиент, круги и карточки с ободком
и тенью, всё масштабом S в безопасную рамку 9:16). Тексты ТЗ дословно.
  1  4 круга со звёздами по цвету волос: Ash Blonde / Golden Brown / Soft Espresso / Copper + 3 оттенка под подписью
  2  запястья A/B/C (из 1322)          3  натуральный цвет волос A/B/C (фото 1322)     4  глаза A/B/C (фото 1322)
  5–7 код · код / название + портрет в рамке + 3 оттенка с подписями
  8  «Your code isn't here?» + 2 настоящих скрина Inspoy (Hair Colors + Try On Hair Colors)
Партия: библиотека output/1342_lib/<слот>/ (люди — <человек>__<n>.jpg, один человек раз на карусель), уникальные
наборы (план как в 1322).

  python build_1342_carousels.py --test                       # 3 карусели → output/carousels_1342_test (+ QA)
  python build_1342_carousels.py -n 64 --out output/carousels_1342 --flat output/1342_64
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1322_carousels as B  # noqa: E402
from core.safe_zones import check_box, draw_overlay  # noqa: E402

W, H = B.W, B.H
LIB = ROOT / "output" / "1342_lib"
SCREENS = ROOT / "downloads" / "1342" / "inspoy"
MAX_TEXT_W = 860                                   # ширина строки в координатах рефа (×S=0.93 → 800 px рамки)

CIRCLES = [("Ash Blonde", "ash"), ("Golden Brown", "golden"), ("Soft Espresso", "espresso"), ("Copper", "copper")]
SHADES = {
    "ash": [("ash", (170, 160, 142)), ("pearl", (219, 210, 197)), ("champagne", (226, 204, 162))],
    "golden": [("honey", (190, 132, 62)), ("caramel", (158, 101, 48)), ("chestnut", (121, 66, 38))],
    "espresso": [("mocha", (108, 76, 60)), ("mushroom brown", (140, 122, 106)), ("dark chocolate", (61, 39, 33))],
    "copper": [("copper", (185, 88, 44)), ("ginger", (204, 110, 52)), ("auburn", (136, 58, 36))],
}
RESULTS = [(5, "CAA · CAB", "ash blonde", "ash"), (6, "ABB · ABC", "golden brown", "golden"),
           (7, "BCC · BCB", "soft espresso", "espresso")]
HAIR = [("A. Blonde", (120, 458, 368, 371), (304, 847)), ("B. Brown", (599, 460, 361, 369), (780, 847)),
        ("C. Dark / Black", (359, 1098, 368, 369), (543, 1487))]
EYES = [("A. Blue / Grey", 500), ("B. Green / Hazel", 850), ("C. Brown", 1200)]
SLOTS = ["ash", "golden", "espresso", "copper", "wrist_a", "wrist_b", "wrist_c", "hair_a", "hair_b", "hair_c",
         "eyes_a", "eyes_b", "eyes_c", "card_5", "card_6", "card_7", "s8"]
SET: dict[str, Path] = {}
B.CIRCLE_FRAME.update({k: (2.5, 0.12) for _n, k in CIRCLES})


def fit_px(text: str, px: float, wght: int, emoji: bool = False, max_w: float = MAX_TEXT_W) -> float:
    while px > 20:
        w = B.font(px, wght).getlength(text) / B.SS + (px * 1.33 if emoji else 0)
        if w <= max_w:
            return px
        px -= 1
    return px


CIRCLE_FIT = (2.5, 0.12, 1.5)          # желаемый кадр (высот лица), сдвиг центра вниз, минимум (ближе — только лицо с волосами)
CARD_FIT = (2.3, 0.22, 1.6)


def frame_centered(src: Path, w: int, h: int, fit: tuple[float, float, float]) -> Image.Image | None:
    """Кадр строго по центру лица, без достройки краёв (растянутые полосы) и без сдвига кадра вбок (лицо
    «не ровно»): если фото не даёт нужного запаса вокруг лица — кадр ближе, но не ближе минимума; иначе None."""
    zoom, drop, min_zoom = fit
    im = Image.open(src).convert("RGB")
    fb = B.face_box(im)
    if fb is None:
        return None
    x0, y0, x1, y1, _ = fb
    fh = y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 + drop * fh
    ar = w / h
    ch = min(zoom * fh, 2 * cx / ar, 2 * (im.width - cx) / ar, 2 * cy, 2 * (im.height - cy))
    if ch < min_zoom * fh:
        return None
    cw = ch * ar
    box = (round(cx - cw / 2), round(cy - ch / 2), round(cx + cw / 2), round(cy + ch / 2))
    return im.crop(box).resize((w, h), Image.Resampling.LANCZOS)


def circle_photo(src: Path, key: str) -> Image.Image:
    ph = frame_centered(src, 352, 352, CIRCLE_FIT)
    if ph is None:
        raise SystemExit(f"{src.name}: не годится для круга (check_lib)")
    return B.framed(ph, "circle")


def slide1() -> B.Slide:
    sl = B.Slide()
    t = "Let's find out your perfect hair color"
    sl.text(540, 210, t, fit_px(t, 49, 600, emoji=True), 600, emoji="✨")
    sl.text(540, 282, "(results in the last slides)", 34, 450)
    for (name, key), (_n, box, (cx, ty)) in zip(CIRCLES, B.SEASONS):
        sl.paste(circle_photo(SET[key], key), box[0] + 6 - 26, box[1] + 6 - 26)
        sl.text(cx, ty, name, 47, 600)
        cols = [c for _s, c in SHADES[key]]
        size, gap = 44, 6
        sl.squares(cx - (3 * size + 2 * gap) / 2, ty + 60, cols, size, gap, 3)
    return sl


def slide2() -> B.Slide:
    sl = B.Slide()
    sl.text(540, 210, "What's your undertone?", 49, 600)
    for lab, sub, box, dx in B.WRISTS:
        ph = Image.open(SET["wrist_" + lab[0].lower()]).convert("RGBA")
        k = min((box[2] + 40) / ph.width, box[3] / ph.height)
        ph = ph.resize((round(ph.width * k), round(ph.height * k)), Image.Resampling.LANCZOS)
        sl.paste(ph, box[0] + (box[2] - ph.width) / 2, box[1] + box[3] - ph.height)
        cx = box[0] + box[2] / 2
        sl.text(cx, 1273, lab, 40, 600)
        sl.text(cx, 1330, sub.lower().capitalize(), 26, 600)
        cols = [B.sample(2, dx + 17 + round(k * 39.5), 1386, 5) for k in range(3)]
        sl.dots(cx - (3 * 34 + 2 * 5.5) / 2, 1369, cols, 34, 5.5)
    return sl


def slide3() -> B.Slide:
    sl = B.Slide()
    t = "What's your natural hair color?"
    sl.text(540, 210, t, fit_px(t, 49, 600), 600)
    for lab, box, (cx, ty) in HAIR:
        ph = Image.open(SET["hair_" + lab[0].lower()]).convert("RGB")
        side = min(ph.size)
        ph = B.crop_box(ph, ph.width / 2, ph.height / 2, side, side).resize((356, 356), Image.Resampling.LANCZOS)
        sl.paste(B.framed(ph, "circle"), box[0] + 6 - 26, box[1] + 6 - 26)
        sl.text(cx, ty, lab, 47, 600)
    return sl


def slide4() -> B.Slide:
    sl = B.Slide()
    sl.text(540, 210, "What's your eye color?", 49, 600)
    for lab, y in EYES:
        strip = B.frame_eyes(SET["eyes_" + lab[0].lower()], 415, 142)
        sl.paste(B.framed(strip, "rect", 14), 332 - 26, y + 4 - 26)
        sl.text(540, y + 176, lab, 47, 600)
    return sl


def slide_result(i: int, code: str, low: str, key: str) -> B.Slide:
    sl = B.Slide()
    sl.text(540, 215, code, 65, 600)
    sl.text(540, 300, low, 47, 500)
    ph = frame_centered(SET[f"card_{i}"], 812, 834, CARD_FIT)
    if ph is None:
        raise SystemExit(f"{SET[f'card_{i}'].name}: не годится для карточки (check_lib)")
    sl.paste(B.framed(ph, "rect", 34), 134 - 26, 410 - 26)
    size, gap = 184, 58
    x0 = 540 - (3 * size + 2 * gap) / 2
    for k, (name, col) in enumerate(SHADES[key]):
        x = x0 + k * (size + gap)
        sl.squares(x, 1300, [col], size, 0, 1, radius=10)
        yy = 1512
        for ln in (name.split(" ", 1) if " " in name else [name]):     # «mushroom / brown» — по слову в строку
            yy = sl.text(x + size / 2, yy, ln, 34, 500) + 8
    return sl


def screen_card(path: Path, crop_h: int, w: int) -> Image.Image:
    im = Image.open(path).convert("RGB")
    im = im.crop((0, 0, im.width, crop_h))
    im = im.resize((w, round(crop_h * w / im.width)), Image.Resampling.LANCZOS)
    return B.framed(im, "rect", 30)


def make_pairs() -> list[Path]:
    """3 пары скринов (Hair Colors + Try On Hair Colors) → output/1342_lib/s8/pair_N.png (прозрачный фон)."""
    out = LIB / "s8"
    out.mkdir(parents=True, exist_ok=True)
    pairs = [("IMG_7759", "IMG_7772"), ("IMG_7795", "IMG_7808"), ("IMG_7829", "IMG_7839")]
    res = []
    for n, (hc, tryon) in enumerate(pairs, 1):
        a = screen_card(SCREENS / f"{hc}.PNG", 1480, 380).rotate(3, Image.Resampling.BICUBIC, expand=True)
        b = screen_card(SCREENS / f"{tryon}.PNG", 1440, 380).rotate(-3, Image.Resampling.BICUBIC, expand=True)
        canvas = Image.new("RGBA", (a.width + b.width - 30, max(a.height, b.height) + 40), (0, 0, 0, 0))
        canvas.alpha_composite(a, (0, 0))
        canvas.alpha_composite(b, (a.width - 30, 40))
        dst = out / f"pair_{n}.png"
        canvas.save(dst)
        res.append(dst)
    return res


def slide8() -> B.Slide:
    sl = B.Slide()
    y = 225
    for ln in ("Your code", "isn't here?"):
        y = sl.text(540, y, ln, 90, 700) + 30
    y += 30
    for ln in ("Inspoy shows hair colors", "that suit you", "on your own selfie"):
        y = sl.text(540, y, ln, 46, 500) + 16
    pair = Image.open(SET["s8"]).convert("RGBA")
    k = min(1000 / pair.width, (1650 - (y + 50)) / pair.height)       # картинки могут шире рамки текста
    pair = pair.resize((round(pair.width * k), round(pair.height * k)), Image.Resampling.LANCZOS)
    sl.paste(pair, 540 - pair.width / 2, y + 50)
    return sl


def build_all() -> list:
    slides = [slide1(), slide2(), slide3(), slide4()] + [slide_result(*r) for r in RESULTS] + [slide8()]
    return [sl.render() for sl in slides]


def render_one(job: tuple) -> str:
    i, pick, out, flat, flat_id = job
    SET.clear()
    SET.update({k: Path(v) for k, v in pick.items()})
    d = Path(out) / f"{i:03d}"
    d.mkdir(parents=True, exist_ok=True)
    for k, (im, boxes) in enumerate(build_all(), 1):
        for b in boxes:
            bad = check_box(W, H, b)
            if bad:
                raise SystemExit(f"{i:03d} слайд {k}: текст вне безопасной зоны {b} — {bad}")
        im.save(d / f"{k}.jpg", quality=95)
        if flat:
            im.save(Path(flat) / f"sort_{k}_{i}_{flat_id}.jpg", quality=95)
    return d.name


def check_lib() -> None:
    """Фото звёзд, которые нельзя кадрировать ровно по центру с запасом, → output/1342_lib/_rejected/<слот>."""
    import shutil
    for slot, fit, size in [(k, CIRCLE_FIT, (352, 352)) for _n, k in CIRCLES] +                            [(f"card_{i}", CARD_FIT, (812, 834)) for i in (5, 6, 7)]:
        for f in sorted((LIB / slot).glob("*.jpg")):
            if frame_centered(f, *size, fit) is None:
                dst = LIB / "_rejected" / slot
                dst.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dst / f.name))
                print(f"  убрал {slot}/{f.name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "carousels_1342_test")
    ap.add_argument("-n", type=int, default=64)
    ap.add_argument("--flat", type=Path)
    ap.add_argument("--flat-id", default="1342")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1342)
    ap.add_argument("--test", action="store_true", help="3 карусели + QA-лист")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    make_pairs()
    check_lib()
    B.LIB, B.SLOTS = LIB, SLOTS
    n = 3 if args.test else args.n
    picks = B.plan_lib(n, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.flat:
        args.flat.mkdir(parents=True, exist_ok=True)
    (args.out / "manifest.json").write_text(json.dumps(
        [{"carousel": f"{i:03d}", **{k: v.name for k, v in p.items()}} for i, p in enumerate(picks, 1)],
        indent=1, ensure_ascii=False), encoding="utf-8")
    for sl in SLOTS:
        c = Counter(p[sl].name for p in picks)
        print(f"{sl}: {len(c)} картинок, повторов {min(c.values())}–{max(c.values())}")
    jobs = [(i, {k: str(v) for k, v in p.items()}, str(args.out), str(args.flat) if args.flat else None, args.flat_id)
            for i, p in enumerate(picks, 1)]
    with ProcessPoolExecutor(args.jobs) as ex:
        for k, name in enumerate(ex.map(render_one, jobs), 1):
            print(f"[{k}/{len(jobs)}] {name}", flush=True)
    if args.test:
        tiles = []
        for k in range(1, 9):
            q = draw_overlay(Image.open(args.out / "001" / f"{k}.jpg").convert("RGB"))
            tiles.append(q.resize((270, 480)))
        sheet = Image.new("RGB", (270 * 8, 480 * (1 + n)), "white")
        for k, q in enumerate(tiles):
            sheet.paste(q, (k * 270, 0))
        for r in range(n):
            for k in range(8):
                sheet.paste(Image.open(args.out / f"{r + 1:03d}" / f"{k + 1}.jpg").resize((270, 480)), (k * 270, 480 * (r + 1)))
        sheet.save(args.out / "_preview.jpg", quality=86)
    print(f"готово: {len(jobs)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
