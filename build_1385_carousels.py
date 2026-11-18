#!/usr/bin/env python3
"""
1385 — Inspoy, советы «prime» в стиле рефа @tips.with.alex/photo/7640214198382873878 (эстетичные фото, по центру
заголовок крупнее + текст мельче); шрифт — белый TikTok с чёрной обводкой (просьба пользователя). Два набора по 70 каруселей,
4 слайда 3:4 (1080×1440):
  A — «how to be in your prime at 20 (nobody told you this)»: девушки ~20;
  B — «your prime isn't over. do these 4 things» (обложка выделена белыми плашками TikTok): женщины 35–50.
Фото — живые с телефона с Pinterest (harvest_carousel_pool.py --profile pa_s1…pb_s4 → output/_work/1385/pool/<профиль>,
лишнее удаляется руками из папки). Обложка — яркая, без серой одежды. На последнем слайде — карточка Inspoy в App
Store (как карточка Albo на рефе). Тексты ТЗ дословно, переносы по смыслу.
Блок текста ставится мимо лица: под подбородком или над головой (MediaPipe), всегда в безопасной рамке 3:4.

  python build_1385_carousels.py --set A -n 4 --test
  python build_1385_carousels.py --set A -n 70      # → output/1385_A_70/sort_<слайд>_<n>_1385.jpg
  python build_1385_carousels.py --set A -n 4 --test --pool output/_work/1385/pick_pool   # по 3 лучших фото на слайд
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
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402

ID = "1385"
W, H = 1080, 1440
X0, Y0, X1, Y1 = text_rect(W, H)
NL = chr(10)
POOL = ROOT / "output" / "_work" / ID / "pool"
WORK = ROOT / "output" / "_work" / ID
FONT = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "otf" / "TikTokSans12pt-Medium.otf"
GAP = 26                                             # отступ блока от подбородка / макушки
EXT = (".jpg", ".jpeg", ".png", ".webp")

# (папка пула, заголовок, текст) — заголовок None: обложка; текст ТЗ дословно, переносы по смыслу
SETS = {
    "A": [
        ("pa_s1", None, "how to be in your prime at 20" + NL + "(nobody told you this)"),
        ("pa_s2", "sleep like it's your job",
         NL.join(["the girls in their prime", "aren't doing a 10-step routine.", "they're asleep by 11.",
                  "skin, mood, energy,", "it all comes from there."])),
        ("pa_s3", "stop saving, start doing",
         NL.join(["your saved tiktoks are a graveyard", "of the person you wanted to be.",
                  "clean them out and do one thing", "from it this week."])),
        ("pa_s4", "decide who you are" + NL + "before you walk out",
         NL.join(["peak girls don't figure out", "their outfit at 7am.", "they plan the look the night before",
                  "and walk out like they own the room.", "i use Inspoy: Outfit Maker, Planner"])),
    ],
    "B": [
        ("pb_s1", None, "your prime isn't over." + NL + "do these 4 things"),
        ("pb_s2", "stand like you belong there",
         NL.join(["posture is the cheapest upgrade.", "you walk in the room and people", "decide in two seconds.",
                  "shoulders back, chin level, done."])),
        ("pb_s3", "stop buying random pieces",
         NL.join(["women in their prime have a uniform.", "five combinations that always work,",
                  "nothing they regret,", "mornings that take ten minutes."])),
        ("pb_s4", "plan your week on sunday",
         NL.join(["i lay out the whole week on sunday night,", "shoes and bag included.", "no more 8am panic.",
                  "i use Inspoy: Outfit Maker, Planner"])),
    ],
}
PLATE_COVER = {"B"}                                  # обложка набора выделена плашками («выделить» в ТЗ)
CARD_W = 440


def font(px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), px)


def lines_img(text: str, px: int, lead: float = 1.22) -> Image.Image:
    f = font(px)
    lines = text.split(NL)
    adv = round(px * lead)
    w = max(round(f.getlength(ln)) for ln in lines) + 8
    img = Image.new("RGBA", (w, adv * len(lines) + round(px * 0.3)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        d.text((w / 2, i * adv + px), ln, font=f, anchor="ms", fill=(255, 255, 255, 255))
    return img.crop(img.getbbox())


def text_block(title: str | None, body: str, scale: float = 1.0) -> Image.Image:
    """Заголовок + текст (или одна строка обложки): белый TikTok-шрифт с чёрной обводкой (как в остальных
    каруселях), заголовок крупнее, по центру."""
    import build_1281_carousels as TT
    parts = []
    if title:
        parts.append(TT.text_block(title, H, round(66 * scale)))
        parts.append(TT.text_block(body, H, round(44 * scale)))
    else:
        parts.append(TT.text_block(body, H, round(68 * scale)))
    gap = round(18 * scale)
    w = max(p.width for p in parts)
    h = sum(p.height for p in parts) + gap * (len(parts) - 1)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    y = 0
    for p in parts:
        out.alpha_composite(p, ((w - p.width) // 2, y))
        y += p.height + gap
    return out


def plate_block(text: str, scale: float = 1.0) -> Image.Image:
    import build_1321_carousels as R
    return R.plates(text, round(64 * scale))


def card(width: int = CARD_W) -> Image.Image:
    import build_1319_carousels as AS
    c = AS.app_card(width)
    m = Image.new("L", (c.width * 4, c.height * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, c.width * 4 - 1, c.height * 4 - 1), radius=20 * 4, fill=255)
    c.putalpha(m.resize(c.size, Image.Resampling.LANCZOS))
    return c


_FL = None


def face_span(bg: Image.Image) -> tuple[int, int] | None:
    """(верх лба − запас на волосы, низ подбородка) самого крупного лица или None."""
    global _FL
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    if _FL is None:
        _FL = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "face_landmarker.task")), num_faces=3))
    r = _FL.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(bg).copy()))
    if not r.face_landmarks:
        return None
    spans = [(min(q.y for q in f) * H, max(q.y for q in f) * H) for f in r.face_landmarks]
    top = min(a for a, _ in spans)
    bot = max(b for _, b in spans)
    return int(top - (bot - top) * 0.35), int(bot)


def dim_behind(bg: Image.Image, box: tuple, strength: float = 0.3) -> Image.Image:
    """Мягкое затемнение под блоком текста (размытое пятно) — белый текст читается и на светлых простынях."""
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).rectangle((box[0] - 40, box[1] - 30, box[2] + 40, box[3] + 30), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(55))
    a = np.asarray(bg).astype(np.float32) * (1 - strength * np.asarray(m, np.float32)[..., None] / 255)
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


# насыщенность слайдов с одеждой (просьба клиента «одежду поярче — чтоб насыщенно»): {(набор, слайд): (цвет, контраст)}
VIVID = {("B", 3): (1.6, 1.08), ("B", 4): (1.6, 1.08)}


def vivid(im: Image.Image, color: float, contrast: float) -> Image.Image:
    from PIL import ImageEnhance
    return ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(color)).enhance(contrast)


def fit_bg(src: Path) -> Image.Image:
    im = Image.open(src).convert("RGB")
    im = ImageOps.fit(im, (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.42))
    return im.filter(ImageFilter.UnsharpMask(radius=1.2, percent=40, threshold=2))


def compose(slide: tuple, bg: Image.Image, cover_plate: bool, last: bool) -> tuple[Image.Image, tuple]:
    _p, title, body = slide
    span = face_span(bg)
    bands = []
    if span:
        bands.append((max(Y0, span[1] + GAP), Y1))          # под подбородком
        bands.append((Y0, min(Y1, span[0] - GAP)))          # над головой
    else:
        bands.append((Y0 + int((Y1 - Y0) * 0.30), Y1))      # без лица — ниже середины, как на рефе
    for scale in (1.0, 0.92, 0.85, 0.78, 0.72, 0.66, 0.6):
        b = plate_block(body, scale) if (title is None and cover_plate) else text_block(title, body, scale)
        items = [b] + ([card(max(330, round(CARD_W * scale)))] if last else [])   # карточка уменьшается вместе с текстом
        gap = round(28 * scale)
        w = max(i.width for i in items)
        h = sum(i.height for i in items) + gap * (len(items) - 1)
        if w > X1 - X0:
            continue
        for a, z in bands:
            if z - a >= h:
                y = a + (z - a - h) // 2
                out = bg.convert("RGBA")
                yy = y
                for it in items:
                    out.alpha_composite(it, ((W - it.width) // 2, yy))
                    yy += it.height + gap
                box = ((W - w) // 2, y, (W + w) // 2, y + h)
                return out.convert("RGB"), box
    return None                                           # лицо на весь кадр — места под текст нет


def bg_for(set_name: str, k: int, f: Path) -> Image.Image:
    bg = fit_bg(f)
    return vivid(bg, *VIVID[(set_name, k)]) if (set_name, k) in VIVID else bg


def pools(set_name: str) -> list[list[Path]]:
    return [sorted(p for p in (POOL / s[0]).glob("*") if p.suffix.lower() in EXT and not p.name.startswith("_"))
            for s in SETS[set_name]]


def plan(set_name: str, n: int) -> list[dict]:
    """Все сочетания кадров слайдов; берём n разных, каждый раз — самое «недоиспользованное» (кадры поровну)."""
    import itertools
    rng = random.Random(1385 + ord(set_name))
    ps = pools(set_name)
    combos = list(itertools.product(*ps))
    rng.shuffle(combos)
    if n > len(combos):
        raise SystemExit(f"нужно {n}, а разных сочетаний только {len(combos)} — добавьте кадров")
    use: Counter = Counter()
    jobs = []
    for i in range(n):
        best = min(combos, key=lambda c: (sum(use[f] for f in c), max(use[f] for f in c)))
        combos.remove(best)
        use.update(best)
        jobs.append({"n": i + 1, "files": [str(f) for f in best]})
    return jobs


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=sorted(SETS), required=True)
    ap.add_argument("-n", type=int, default=70)
    ap.add_argument("--test", action="store_true", help="→ output/_work/1385/test_<set>")
    ap.add_argument("--pool", type=Path, default=POOL, help="папка пулов <профиль>/ (по умолчанию — Pinterest-пул)")
    args = ap.parse_args()
    globals()["POOL"] = args.pool
    cache: dict = {}
    for k, slide in enumerate(SETS[args.set], 1):          # кадры, где текст не встаёт мимо лица, — в _nofit
        for f in pools(args.set)[k - 1]:
            r = compose(slide, bg_for(args.set, k, f), args.set in PLATE_COVER, k == len(SETS[args.set]))
            if r is None:
                (f.parent / "_nofit").mkdir(exist_ok=True)
                shutil.move(str(f), str(f.parent / "_nofit" / f.name))
                print(f"нет места под текст → _nofit: {slide[0]}/{f.name}", flush=True)
            else:
                cache[(k, str(f))] = r
    ps = pools(args.set)
    print("кадров:", " · ".join(f"{s[0]} {len(p)}" for s, p in zip(SETS[args.set], ps)), flush=True)
    jobs = plan(args.set, args.n)
    per = WORK / (f"test_{args.set}" if args.test else f"carousels_{args.set}")
    flat = None if args.test else ROOT / "output" / f"{ID}_{args.set}_{args.n}"
    for d in (per, flat):
        if d:
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        d = per / f"{j['n']:03d}"
        d.mkdir(exist_ok=True)
        for k, (slide, f) in enumerate(zip(SETS[args.set], j["files"]), 1):
            key = (k, f)
            if key not in cache:
                cache[key] = compose(slide, bg_for(args.set, k, Path(f)), args.set in PLATE_COVER, k == len(SETS[args.set]))
            im, box = cache[key]
            bad = check_box(W, H, box)
            if bad:
                raise SystemExit(f"{Path(f).name}: текст вне безопасной зоны — {bad}")
            im.save(d / f"{k}.jpg", quality=93)
            if flat:
                shutil.copy2(d / f"{k}.jpg", flat / f"sort_{k}_{j['n']}_{ID}.jpg")
        print(f"[{j['n']}/{len(jobs)}]", flush=True)
    (per / "manifest.json").write_text(json.dumps(jobs, indent=1, ensure_ascii=False), encoding="utf-8")
    # QA: все кадры пула каждого слайда с рамкой
    for k, (slide, p) in enumerate(zip(SETS[args.set], ps), 1):
        tiles = []
        for f in p:
            key = (k, str(f))
            if key not in cache:
                cache[key] = compose(slide, bg_for(args.set, k, f), args.set in PLATE_COVER, k == len(SETS[args.set]))
            tiles.append(draw_overlay(cache[key][0]).resize((216, 288)))
        sheet = Image.new("RGB", (216 * min(8, len(tiles)), 288 * ((len(tiles) + 7) // 8)), "white")
        for i, t in enumerate(tiles):
            sheet.paste(t, ((i % 8) * 216, (i // 8) * 288))
        sheet.save(per / f"_qa_{k}.jpg", quality=85)
    keys = {tuple(j["files"]) for j in jobs}
    print(f"уникальных каруселей: {len(keys)} из {len(jobs)} → {flat or per}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
