#!/usr/bin/env python3
"""
1389b — «top 5 things [to do when you’re] bored (you won’t expect #4)»: докрутка формата 1389 с акцентом на Drops.
Тот же язык (вода/небо, звёзды, iMac, меню Copy, белая карточка, [N.]), тексты ТЗ дословно, переносы по смыслу.
  слайды 1–3 — шуточные: своё фото на экране iMac (пулы output/1389b_pick/{room,dog,skill});
  слайд 4   — drops.game на iMac с адресной строкой;
  слайд 5   — игра Drops на телефоне (кадры output/1388d_slides/s4 без заставок).

Карусель 3:4 (вода, рамка x 180–900, y 6–78 %) и видео 9:16 (небо 1391, звук 1391, смена слайдов на бит).

  python build_1389b.py --test                                   # 2 карусели + QA → output/1389b_test
  python build_1389b.py --test --video --half                    # 2 видео (смена 2 раза за такт)
  python build_1389b.py -n 100 --flat output/1389b_100
  python build_1389b.py -n 100 --video --seven --out output/1389b_video_100
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1389_carousels as B  # noqa: E402
import build_1391_reels as V  # noqa: E402
from core.safe_zones import check_box, draw_overlay  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402

PICK = ROOT / "output" / "1389b_pick"
GAMES = ROOT / "output" / "1388d_slides" / "s4"
ITEMS = [  # (строки заголовка, строки описания, пул экрана) — дословно из ТЗ
    (["rearrange your room", "at midnight"], ["you’ll hate it by morning"], "room"),
    (["text your ex’s dog"], ["he misses you"], "dog"),
    (["learn one really", "useless skill"], ["juggling. moonwalking. whistling."], "skill"),
    (["turn your own song", "into a game"],
     ["upload your song and it builds", "a playable game", "around its tempo and mood"], "site"),
    (["send it", "to your friends"], ["now they’re stuck playing your song"], "game"),
]
# 7 с по тому же биту 1391: смены только на замеренных 1-й и 3-й долях. 7 полутактов на 5 слайдов — шуточным по одному,
# слайдам Drops по два (акцент на приложении и время прочитать). Конец — 3-я доля, 7.135 с.
SEVEN_MARKS = [V.BEATS13[i] for i in (0, 1, 2, 3, 5)]
SEVEN_END = V.BEATS13[7]
DEFAULT_MENU = ["Copy", "Select All", "Look Up"]
SHARE_MENU = ["Copy Link", "Share"]


def title_block(lines: list[str], f, fill, track: float = -0.03) -> Image.Image:
    """Заголовок в несколько строк с постоянным шагом базовой линии (text_img обрезает по буквам — шаг бы плавал)."""
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    lh = round(f.size * 1.14)
    width = int(max(sum(d.textlength(c, font=f) + track * f.size for c in s) for s in lines)) + 8
    asc, desc = f.getmetrics()
    im = Image.new("RGBA", (width, lh * (len(lines) - 1) + asc + desc), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im)
    for k, s in enumerate(lines):
        x = 2.0
        for c in s:
            dd.text((x, k * lh + asc), c, font=f, fill=fill, anchor="ls")
            x += d.textlength(c, font=f) + track * f.size
    return im.crop(im.getbbox())


def card(num: int, title: list[str], desc: list[str], width: int = 520) -> tuple[Image.Image, list]:
    pad = 28
    tw = width - 2 * pad
    px = 58
    while max(B.font(B.F_BOLD, px).getlength(s) * 0.97 for s in title) > tw:
        px -= 1
    t_img = title_block(title, B.font(B.F_BOLD, px), B.INK + (255,))
    tg = B.tag(f"{num}.", 30)
    fd = B.font(B.F_REG, 25)
    lh = 33
    h = pad + 26 + tg.height + 8 + t_img.height + 18 + lh * len(desc) + pad - 6
    c = B.rounded((width, h), 22, (255, 255, 255, 255))
    d = ImageDraw.Draw(c)
    for k, col in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
        d.ellipse((pad + k * 20, pad - 2, pad + k * 20 + 11, pad + 9), fill=col)
    y = pad + 26
    c.alpha_composite(tg, (pad - 4, y))
    y += tg.height + 8
    c.alpha_composite(t_img, (pad - 2, y))
    y += t_img.height + 18
    for ln in desc:
        d.text((pad, y), ln, font=fd, fill=B.INK2)
        y += lh
    return c, [(pad - 4, pad + 26, width - pad, h - pad + 6)]


def menu(items: list[str]) -> Image.Image:
    if items == DEFAULT_MENU:
        return B.menu_pill()
    f = B.font(B.F_REG, 19)
    pad = 18
    ws = [f.getlength(t) + 2 * pad for t in items]
    w, h = int(sum(ws)), 46
    pill = B.rounded((w, h), 12, (252, 252, 252, 250))
    d = ImageDraw.Draw(pill)
    x = 0
    for k, t in enumerate(items):
        d.text((x + ws[k] / 2, h / 2), t, font=f, fill=(20, 20, 22), anchor="mm")
        x += ws[k]
        if k < len(items) - 1:
            d.line((x, 9, x, h - 9), fill=(205, 205, 210), width=1)
    return pill


def status_bar(w: int, h: int, bg: tuple[int, int, int]) -> Image.Image:
    """Верхняя безопасная зона iPhone в цвет шапки приложения: время, «островок», связь, Wi-Fi, батарея."""
    S = 4
    im = Image.new("RGB", (w * S, h * S), bg)
    d = ImageDraw.Draw(im)
    fg = (16, 16, 18) if 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2] > 140 else (250, 250, 250)
    d.rounded_rectangle(((w / 2 - 44) * S, 10 * S, (w / 2 + 44) * S, 36 * S), 13 * S, fill=(6, 6, 8))
    d.text((54 * S, 24 * S), "9:41", font=B.font(B.F_SEMI, 17 * S), fill=fg, anchor="mm")
    for k, bar_h in enumerate((5, 8, 11, 14)):
        x = w - 84 + k * 5
        d.rounded_rectangle((x * S, (30 - bar_h) * S, (x + 3) * S, 30 * S), S, fill=fg)
    cx, cy = w - 52, 30
    for r_ in (14, 9):
        d.arc(((cx - r_) * S, (cy - r_) * S, (cx + r_) * S, (cy + r_) * S), 228, 312, fill=fg, width=3 * S)
    d.ellipse(((cx - 2) * S, (cy - 4) * S, (cx + 2) * S, cy * S), fill=fg)
    d.rounded_rectangle(((w - 38) * S, 17 * S, (w - 14) * S, 30 * S), 4 * S, outline=fg, width=S)
    d.rounded_rectangle(((w - 36) * S, 19 * S, (w - 18) * S, 28 * S), 2 * S, fill=fg)
    d.rounded_rectangle(((w - 13) * S, 21 * S, (w - 11) * S, 26 * S), S, fill=fg)
    return im.resize((w, h), Image.Resampling.LANCZOS)


def phone(shot: Path) -> Image.Image:
    """Телефон с кадром игры: контент приложения начинается ПОД верхней безопасной зоной (статус-бар и «островок»),
    шапка не упирается в скругления; снизу кадр обрезается на высоту полосы (там панель, её и так закрывает карточка)."""
    sw, sh, band = 290, 628, 46
    bz = 11
    out = B.rounded((sw + 2 * bz, sh + 2 * bz), 54, (16, 16, 18, 255))
    src = ImageOps.exif_transpose(Image.open(shot)).convert("RGB")
    app = ImageOps.fit(src, (sw, round(sw * src.height / src.width)), Image.Resampling.LANCZOS, centering=(0.5, 0.0))
    header = tuple(int(v) for v in np.median(np.asarray(app.crop((90, 0, sw - 90, 5))).reshape(-1, 3), axis=0))
    scr = Image.new("RGB", (sw, sh), header)
    scr.paste(status_bar(sw, band, header), (0, 0))
    scr.paste(app, (0, band))
    mask = B.rounded((sw, sh), 44, (255, 255, 255, 255)).getchannel("A")
    out.paste(scr, (bz, bz), mask)
    return out


def layer_imac(k: int, shot: Path, S: float, W: int, limit: int) -> tuple[Image.Image, list, int]:
    title, desc, kind = ITEMS[k]
    has_bar = kind == "site"
    mac, pill = B.imac(shot), menu(DEFAULT_MENU)
    cd, cboxes = card(k + 1, title, desc)
    lw = mac.width + 60
    by = 40
    bar = B.address_bar("drops.game") if has_bar else None
    bx = (lw - B.address_bar("x").width) // 2
    mx, my = (lw - mac.width) // 2, by + 60 + 36
    px_, py_ = mx + mac.width - pill.width - 4, my + 383 + 32 + 22
    x0f = (W - lw * S) / 2
    cx_ = int(min(lw - cd.width - 4, lw // 2 + 30, (limit - x0f) / S - cboxes[0][2]))
    cy_ = my + 383 + 32 + 22 + 46 + 10
    lh = cy_ + cd.height + 60
    L = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    els = [(mac, (mx, my), (18, 0.35, 10)), (pill, (px_, py_), (8, 0.25, 3)), (cd, (cx_, cy_), (18, 0.3, 10))]
    if bar is not None:
        els.insert(0, (bar, (bx, by), (10, 0.2, 4)))
    for el, (x, y), sh in els:
        s, p = B.shadowed(el, blur=sh[0], opacity=sh[1], offset=(0, sh[2]))
        L.alpha_composite(s, (x - p, y - p))
    cur = B.cursor()
    L.alpha_composite(cur, (cx_ + cd.width - 44, cy_ + cd.height - 44))
    boxes = [(cx_ + a, cy_ + b, cx_ + c, cy_ + d) for a, b, c, d in cboxes]
    if bar is not None:
        boxes.append((bx + 60, by + 8, bx + bar.width - 60, by + bar.height - 8))
    L = L.resize((round(lw * S), round(lh * S)), Image.Resampling.LANCZOS)
    return L, [tuple(round(v * S) for v in b) for b in boxes], round(my * S)


def layer_phone(k: int, shot: Path, S: float) -> tuple[Image.Image, list, int]:
    title, desc, _ = ITEMS[k]
    ph, pill = phone(shot), menu(SHARE_MENU)
    cd, cboxes = card(k + 1, title, desc)
    lw = max(ph.width, cd.width) + 180
    px, py = (lw - ph.width) // 2, 20
    cx_, cy_ = (lw - cd.width) // 2, py + ph.height - 46
    lh = cy_ + cd.height + 60
    L = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    pill_xy = (px + ph.width - 18, py + 300)
    for el, (x, y), sh in ((ph, (px, py), (22, 0.4, 12)), (pill, pill_xy, (8, 0.25, 3)), (cd, (cx_, cy_), (18, 0.3, 10))):
        s, p = B.shadowed(el, blur=sh[0], opacity=sh[1], offset=(0, sh[2]))
        L.alpha_composite(s, (x - p, y - p))
    cur = B.cursor()
    L.alpha_composite(cur, (cx_ + cd.width - 44, cy_ + cd.height - 44))
    boxes = [(cx_ + a, cy_ + b, cx_ + c, cy_ + d) for a, b, c, d in cboxes]
    L = L.resize((round(lw * S), round(lh * S)), Image.Resampling.LANCZOS)
    return L, [tuple(round(v * S) for v in b) for b in boxes], 0


def slide(k: int, shot: Path, bg: Path, rng: random.Random, video: bool) -> tuple[Image.Image, list]:
    W, H = (V.W, V.H) if video else (B.W, B.H)
    S = V.SCALE if video else 1.0
    limit = 930 if video else 895
    im = (V.background if video else B.background)(bg, rng)
    if ITEMS[k][2] == "game":
        L, boxes, up = layer_phone(k, shot, S)
    else:
        L, boxes, up = layer_imac(k, shot, S, W, limit)
    x0 = (W - L.width) // 2
    if ITEMS[k][2] == "game":
        y0 = int(880 - L.height / 2) if video else int(622 - L.height / 2)       # центр безопасной зоны
    else:
        y0 = (400 if video else 250) - up                                        # верх iMac на одной высоте на всех слайдах
    avoid = [(x0, y0 + 30, x0 + L.width, y0 + L.height - 40)]
    stars(im, rng, avoid, rng.randint(12, 17) if video else rng.randint(9, 13), W, H)
    im.alpha_composite(L, (x0, y0))
    return im.convert("RGB"), [(a + x0, b + y0, c + x0, d + y0) for a, b, c, d in boxes]


def stars(im: Image.Image, rng: random.Random, avoid: list, n: int, W: int, H: int) -> None:
    w0, h0 = B.W, B.H
    B.W, B.H = W, H                                                # B.stars берёт размер кадра из модуля
    try:
        B.stars(im, rng, avoid, n)
    finally:
        B.W, B.H = w0, h0


def cover(bg: Path, rng: random.Random, video: bool) -> tuple[Image.Image, list]:
    """top 5 / things / [to do when you’re] / bored / (you won’t expect #4) / save for later!"""
    W, H = (V.W, V.H) if video else (B.W, B.H)
    k = 1.14 if video else 1.0
    im = (V.background if video else B.background)(bg, rng)
    white = (255, 255, 255, 255)
    px = round(186 * k)
    while True:
        big = B.font(B.F_BOLD, px)
        w1, w2 = B.text_img("things", big, white, track=-0.045), B.text_img("bored", big, white, track=-0.045)
        if max(w1.width, w2.width) <= (760 if video else 690):
            break
        px -= 4
    top = B.text_img("top 5", B.font(B.F_SEMI, round(58 * k)), white, track=-0.02)
    fav = B.text_img("(you won’t expect #4)", B.font(B.F_SEMI, round(42 * k)), white, track=-0.01)
    save = B.text_img("save for later!", B.font(B.F_SEMI, round(34 * k)), white)
    tg = B.tag("to do when you’re", round(34 * k))
    cx = W // 2
    gap = round(6 * k)
    hsum = top.height + 18 + w1.height + gap + tg.height + 4 + w2.height + 28 + fav.height + 30 + save.height
    y = int((840 if video else 600) - hsum / 2)
    els = []
    x1 = cx - w1.width // 2
    els.append((top, x1 + 6, y)); y += top.height + 18
    els.append((w1, x1, y)); y += w1.height + gap
    els.append((tg, cx - tg.width // 2 + round(40 * k), y - 10)); y += tg.height + 4
    els.append((w2, cx - w2.width // 2, y)); y += w2.height + 28
    els.append((fav, cx - fav.width // 2, y)); y += fav.height + 30
    els.append((save, cx - save.width // 2, y))
    x0 = min(e[1] for e in els); y0 = min(e[2] for e in els)
    x1_ = max(e[1] + e[0].width for e in els); y1_ = max(e[2] + e[0].height for e in els)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for e, x, yy in els:
        if e is not tg:
            layer.alpha_composite(e, (x, yy))
    stars(im, rng, [(x0, y0, x1_, y1_)], rng.randint(14, 19) if video else rng.randint(12, 16), W, H)
    lum = float(np.asarray(im.convert("L").crop((x0, y0, x1_, y1_)), dtype=np.float32).mean()) / 255
    d = min(max((lum - 0.42) * 1.3, 0.0), 0.38)
    if d > 0:
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).ellipse((x0 - 90, y0 - 75, x1_ + 90, y1_ + 75), fill=int(255 * d))
        dim = Image.new("RGBA", (W, H), (20, 40, 70, 0) if video else (8, 30, 40, 0))
        dim.putalpha(m.filter(ImageFilter.GaussianBlur(75)))
        im.alpha_composite(dim)
    sh = add_shadow(layer, blur=3, opacity=0.55, offset=(0, 2), grow=1, pad=0)
    sh = add_shadow(sh, blur=22, opacity=0.4, offset=(0, 0), grow=8, pad=0)
    im.alpha_composite(sh)
    im.alpha_composite(add_shadow(tg, blur=6, opacity=0.3, offset=(0, 2), grow=1, pad=20),
                       (els[2][1] - 20, els[2][2] - 20))
    return im.convert("RGB"), [(x0, y0, x1_, y1_)]


def images(d: Path, glob: str = "*") -> list[Path]:
    return sorted(f for f in d.glob(glob) if f.suffix.lower() in B.EXT and not f.name.startswith("_") and "_title" not in f.name)


def libs(video: bool) -> tuple[list[Path], list[list[Path]]]:
    bgs = images(V.BG if video else B.BG)
    pools = [images(PICK / "room"), images(PICK / "dog"), images(PICK / "skill"), [f for f in images(B.SHOTS, "drops_*") if f.stem != "drops_03"], images(GAMES)]   # drops_03: «coming soon»
    return bgs, pools


def qa_sheet(slides: list, dest: Path, video: bool) -> None:
    w, h = (270, 480) if video else (324, 432)
    sheet = Image.new("RGB", (w * len(slides), h))
    for k, (im, boxes) in enumerate(slides):
        q = draw_overlay(im.copy())
        for b in boxes:
            ImageDraw.Draw(q).rectangle(b, outline=(255, 200, 0), width=4)
        sheet.paste(q.resize((w, h)), (k * w, 0))
    sheet.save(dest, quality=86)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--video", action="store_true")
    ap.add_argument("--bars", type=int, default=1)
    ap.add_argument("--half", action="store_true")
    ap.add_argument("--seven", action="store_true", help="7.1 с: слайды Drops вдвое дольше, смены на тех же долях")
    ap.add_argument("--flat", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--seed", type=int, default=13892)
    a = ap.parse_args()
    bgs, pools = libs(a.video)
    if not bgs or not all(pools):
        raise SystemExit(f"пустые библиотеки: фонов {len(bgs)}, пулы {[len(p) for p in pools]}")
    W, H = (V.W, V.H) if a.video else (B.W, B.H)
    default = ROOT / "output" / ("1389b_test" if a.test else f"{'video' if a.video else 'carousels'}_1389b_{a.n}")
    out = a.out or default
    out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "output" / "_work" / "1389b_frames"
    if a.video:
        work.mkdir(parents=True, exist_ok=True)
        if a.seven:
            cuts, end = [0.0] + [round(t * V.FPS) / V.FPS for t in SEVEN_MARKS], round(SEVEN_END * V.FPS) / V.FPS
        else:
            cuts, end = V.timing(a.bars, a.half)
        wav = V.music(ROOT / "output" / "_work", end)
        print(f"смены: {[round(c, 3) for c in cuts]} конец {end:.3f}")
    pals = {bg: (V.palettes(bg) if a.video else B.bg_palettes(bg)) for bg in bgs}
    rng = random.Random(a.seed + (1 if a.video else 0))
    seen, manifest = set(), []
    for i in range(1, a.n + 1):
        for _ in range(500):
            bg, pick = rng.choice(bgs), tuple(rng.choice(p) for p in pools)
            pal = rng.choice(pals[bg])
            key = (bg.name, pal) + tuple(p.name for p in pick)
            if key not in seen:
                break
        else:
            raise SystemExit("не нашлось нового сочетания")
        seen.add(key)
        B.PAL = B.PALETTES[pal]
        r = random.Random(a.seed * 10000 + i + (500000 if a.video else 0))
        slides = [cover(bg, r, a.video)] + [slide(k, pick[k], bg, r, a.video) for k in range(5)]
        for k, (im, boxes) in enumerate(slides, 1):
            for b in boxes:
                bad = check_box(W, H, b)
                if bad:
                    raise SystemExit(f"{i:03d} слайд {k}: текст вне безопасной зоны {b} — {bad}")
        if a.video:
            fr = []
            for k, (im, _) in enumerate(slides, 1):
                p = work / f"{i:03d}_{k}.png"
                im.save(p)
                fr.append(p)
            mp4 = out / f"{i:03d}_1389.mp4"
            V.render(fr, wav, mp4, cuts, end)
            for p in fr:
                p.unlink()
            manifest.append({"video": mp4.name, "bg": bg.name, "palette": pal, "shots": [p.name for p in pick]})
        else:
            d = out / f"{i:03d}"
            d.mkdir(exist_ok=True)
            for k, (im, _) in enumerate(slides, 1):
                im.save(d / f"{k}.jpg", quality=94)
                if a.flat:
                    a.flat.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(d / f"{k}.jpg", a.flat / f"sort_{k}_{i}_1389.jpg")
            manifest.append({"carousel": d.name, "bg": bg.name, "palette": pal, "shots": [p.name for p in pick]})
        if a.test:
            qa_sheet(slides, out / f"_qa_{'v' if a.video else 'c'}_{i:03d}.jpg", a.video)
        print(f"  {i:03d}", flush=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    if a.video:
        shutil.rmtree(work, ignore_errors=True)
    print(f"готово: {a.n} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
