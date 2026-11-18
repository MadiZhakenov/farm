#!/usr/bin/env python3
"""
Drops3 (айди пока нет) — мем-карусель 3 слайда 3:4 (1080×1440), тексты ТЗ дословно:
  1. «just releasing music<<boring» — мем-картинка «скука» (Pinterest, животные) на белом, текст сверху
  2. «MAKE A GAME OUT OF YOUR MUSIC >>» — яркий кадр динамичной игры Drops, крупные заглавные по центру
  3. «i made mine on drops 🎮» — скрин телефона: наша игра «Party Pop» на drops.game (Safari, адрес сверху)
Кадры: output/drops3_slides/meme | bg | screen. Все надписи — в безопасной рамке, метаданные JPEG вычищаются.

  python build_drops3_carousels.py -n 4 --out output/drops3_test
  python build_drops3_carousels.py -n 150 --out output/carousels_drops3 --flat output/drops3_150
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1307_carousels as P  # noqa: E402  (plate_block — чёрный текст на белых TikTok-плашках)
import build_1281_carousels as B  # noqa: E402
import render_igdm as R  # noqa: E402  (статус-бар iPhone, иконки)
import strip_jpeg_meta  # noqa: E402
from core.safe_zones import check_box, draw_overlay  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402

W, H = 1080, 1440
SL = ROOT / "output" / "drops3_slides"
T1 = "just releasing music<<boring"
T2 = ["MAKE A GAME", "OUT OF YOUR", "MUSIC >>"]
T3 = "i made mine on drops 🎮"
ANTON = ROOT / "fonts" / "cand1390" / "Anton-Regular.ttf"
TT = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "variable" / "TikTokSans[opsz,slnt,wdth,wght].ttf"


def pool(name: str) -> list[Path]:
    return sorted(p for p in (SL / name).glob("*.jpg") if not p.name.startswith("_"))


# ---------------------------------------------------------------- 1: мем
def slide_meme(meme: Path, rng: random.Random) -> tuple[Image.Image, list]:
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    for px in range(66, 30, -2):
        f = R.font(px, 650)
        tw = f.getlength(T1)
        if tw <= 700:
            break
    asc, desc = f.getmetrics()
    x, y = (W - tw) / 2, 150
    d.text((x, y + asc), T1, font=f, fill=(0, 0, 0), anchor="ls")
    box = (int(x), y, int(x + tw), y + asc + desc)
    m = ImageOps.exif_transpose(Image.open(meme)).convert("RGB")
    mw = rng.randint(820, 900)
    mh = min(round(m.height * mw / m.width), 1060)
    m = ImageOps.fit(m, (mw, mh), Image.Resampling.LANCZOS, centering=(0.5, 0.45))
    m = m.filter(ImageFilter.UnsharpMask(radius=1.4, percent=40, threshold=2))
    top = box[3] + 50
    im.paste(m, ((W - mw) // 2, top))
    return im, [box]


# ---------------------------------------------------------------- 2: яркий кадр игры + заглавные
def game_crop(src: Path, rng: random.Random) -> Image.Image:
    """Кадр записи 1210×2100 (CSS 484×840 ×2.5) → только игровое поле (без шапки и нижнего меню) в 3:4."""
    im = Image.open(src).convert("RGB")
    k = im.width / 484
    top, bot = int(118 * k), int(742 * k)                         # ниже счёта/HP, выше нижнего меню
    h = bot - top
    w = int(h * W / H)
    x0 = (im.width - w) // 2 + rng.randint(-15, 15)
    im = im.crop((max(0, x0), top, max(0, x0) + w, bot)).resize((W, H), Image.Resampling.LANCZOS)
    im = ImageEnhance.Color(im).enhance(1.35)
    return ImageEnhance.Brightness(ImageEnhance.Contrast(im).enhance(1.06)).enhance(1.08)


def slide_game(bg: Path, rng: random.Random) -> tuple[Image.Image, list]:
    im = game_crop(bg, rng).convert("RGBA")
    for px in range(170, 80, -4):
        f = ImageFont.truetype(str(ANTON), px)
        if max(f.getlength(ln) for ln in T2) <= 700:
            break
    stroke = max(6, px // 18)
    step = int(px * 1.08)
    bw = int(max(f.getlength(ln) for ln in T2)) + 2 * stroke + 8
    blk = Image.new("RGBA", (bw, step * len(T2) + stroke * 2 + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(blk)
    for k, ln in enumerate(T2):
        lw = f.getlength(ln)
        d.text(((bw - lw) / 2, stroke + k * step), ln, font=f, fill=(255, 255, 255), stroke_width=stroke,
               stroke_fill=(0, 0, 0))
    blk = blk.crop(blk.getbbox())
    raw = blk.size
    blk = add_shadow(blk, blur=16, opacity=0.55, offset=(0, 8), grow=4)
    pad = (blk.width - raw[0]) // 2
    x, y = (W - blk.width) // 2, (H - blk.height) // 2 - 60
    im.alpha_composite(blk, (x, y))
    return im.convert("RGB"), [(x + pad, y + pad, x + pad + raw[0], y + pad + raw[1])]


# ---------------------------------------------------------------- 3: скрин телефона (Safari, адрес drops.game)
def safari_bar(w: int, s: int) -> Image.Image:
    """Адресная строка Safari iOS сверху (тёмная тема): «AA · drops.game · ↻»."""
    pt = w / 430
    h = int(56 * pt)
    bar = Image.new("RGBA", (w * s, h * s), (28, 28, 30, 255))
    d = ImageDraw.Draw(bar)
    m, ph = 12 * pt, 40 * pt
    y0 = (h - ph) / 2
    d.rounded_rectangle((m * s, y0 * s, (w - m) * s, (y0 + ph) * s), radius=int(12 * pt * s), fill=(58, 58, 60))
    cy = y0 + ph / 2
    f = ImageFont.truetype(str(ROOT / "fonts" / "inter" / "Inter-Medium.ttf"), int(17 * pt * s))
    fa = ImageFont.truetype(str(ROOT / "fonts" / "inter" / "Inter-SemiBold.ttf"), int(15 * pt * s))
    d.text(((m + 14 * pt) * s, cy * s), "AA", font=fa, fill=(235, 235, 245), anchor="lm")
    d.text((w / 2 * s, cy * s), "drops.game", font=f, fill=(255, 255, 255), anchor="mm")
    R.icon(bar, 0xE72C, (w - m - 20 * pt) * s, cy * s, int(17 * pt * s), (235, 235, 245))
    return bar.resize((w, h), Image.Resampling.LANCZOS)


def phone_shot(src: Path, rng: random.Random) -> Image.Image:
    """Скрин айфона: статус-бар + адресная строка Safari (drops.game) + страница игры (запись)."""
    page = Image.open(src).convert("RGB")
    w = page.width
    pt = w / 430
    st_h = int(54 * pt)
    bar = safari_bar(w, 2)
    keep = page.crop((0, 0, w, int(page.height * 0.93)))
    shot = Image.new("RGBA", (w, st_h + bar.height + keep.height), (0, 0, 0, 255))
    st = Image.new("RGBA", (W * 3, round(R.STATUS_H) * 3), (28, 28, 30, 255))
    clock = f"{rng.randint(7, 11)}:{rng.randint(10, 59)}"
    R.status_bar(st, 3, R.Chat(title="", theme="dark", clock=clock, battery=rng.uniform(0.3, 0.9)), R.THEMES["dark"])
    shot.alpha_composite(st.resize((w, st_h), Image.Resampling.LANCZOS), (0, 0))
    shot.alpha_composite(bar, (0, st_h))
    shot.paste(keep, (0, st_h + bar.height))
    return shot.convert("RGB")


def slide_screen(src: Path, rng: random.Random) -> tuple[Image.Image, list]:
    shot = phone_shot(src, rng)
    bg = ImageOps.fit(Image.open(src).convert("RGB"), (W, H), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg).enhance(0.6).convert("RGBA")
    lines = [B.A.sanitize_overlay_text(B.R._normalize_text(T3))]
    for px in range(60, 34, -2):
        cap = P.plate_block(lines, px)
        if cap.width <= 720:
            break
    cy0 = (H - cap.height) // 2                                       # подпись ровно по центру слайда (клиент)
    pad = int(0.42 * px)
    box = ((W - cap.width) // 2 + pad, cy0 + pad // 2, (W + cap.width) // 2 - pad, cy0 + cap.height - pad // 2)
    sw = 840                                                          # скрин крупно, низ уходит за кадр
    sh = round(shot.height * sw / shot.width)
    card = shot.resize((sw, sh), Image.Resampling.LANCZOS).convert("RGBA")
    m = Image.new("L", (sw * 3, sh * 3), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, sw * 3 - 1, sh * 3 - 1), radius=int(sw * 0.07 * 3), fill=255)
    card.putalpha(m.resize((sw, sh), Image.Resampling.LANCZOS))
    ty = 70                                                           # скрин сверху, низ уходит за кадр
    bg.alpha_composite(card.crop((0, 0, sw, min(sh, H - ty))), ((W - sw) // 2, ty))
    bg.alpha_composite(cap, ((W - cap.width) // 2, cy0))
    return bg.convert("RGB"), [box]


# ---------------------------------------------------------------- план
def plan(n: int, seed: int) -> list[tuple[Path, Path, Path]]:
    rng = random.Random(seed)
    combos = list(itertools.product(pool("meme"), pool("bg"), pool("screen")))
    rng.shuffle(combos)
    if n > len(combos):
        raise SystemExit(f"сочетаний только {len(combos)}")
    used: dict = {}
    out = []
    for _ in range(n):
        best = min(combos[:4000], key=lambda c: (sum(used.get(f, 0) for f in c), rng.random()))
        combos.remove(best)
        for f in best:
            used[f] = used.get(f, 0) + 1
        out.append(best)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=4)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_noid.jpg")
    ap.add_argument("--seed", type=int, default=3)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, (meme, bg, scr) in enumerate(plan(a.n, a.seed), 1):
        rng = random.Random(a.seed * 1000 + i)
        d = a.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        slides = [slide_meme(meme, rng), slide_game(bg, rng), slide_screen(scr, rng)]
        for k, (im, boxes) in enumerate(slides, 1):
            for b in boxes:
                if bad := check_box(W, H, b):
                    raise SystemExit(f"{i:03d} слайд {k}: текст вне безопасной зоны {b} — {bad}")
            im.save(d / f"{k}.jpg", quality=93)
            if i <= 2:
                q = draw_overlay(im)
                for b in boxes:
                    ImageDraw.Draw(q).rectangle(b, outline=(255, 200, 0), width=4)
                q.save(d / f"_qa_{k}.jpg", quality=80)
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d / f"{k}.jpg", a.flat / f"sort_{k}_{i}_noid.jpg")
        manifest.append({"carousel": d.name, "meme": meme.name, "bg": bg.name, "screen": scr.name})
        print(f"  {d.name}", flush=True)
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    sys.argv = ["strip", str(a.out)] + ([str(a.flat)] if a.flat else [])
    strip_jpeg_meta.main()
    print(f"готово: {a.n} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
