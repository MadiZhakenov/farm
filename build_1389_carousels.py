#!/usr/bin/env python3
"""
1389 — «top 5 websites [to cure your] boredom (#4 is my favorite)»: копия рефа @farahzzrs (downloads/1389/ref),
6 слайдов 3:4 (1080×1440). Фон — фактура воды (Pinterest, output/1389_pool/bg_water) со звёздочками; на слайдах 2–6:
адресная строка Safari → розовый iMac со скрином сайта → меню «Copy / Select All / Look Up» → белая карточка-окно
(светофор, номер и название, описание) и курсор. Наш клиент — слайд 5, Drops (drops.game).
Тексты — дословно из ТЗ, всё внутри безопасной рамки 3:4 (core/safe_zones).

Скрины сайтов: downloads/1389/shots/<site>_*.png|jpg (capture_1389_sites.py + встроенный браузер).

  python build_1389_carousels.py --test                       # 2 карусели + QA → output/1389_test
  python build_1389_carousels.py -n 200 --flat output/1389_200
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import check_box, draw_overlay  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402

W, H = 1080, 1440
SHOTS = ROOT / "downloads" / "1389" / "shots"
BG = ROOT / "output" / "1389_pool" / "bg_pick"   # строгий отбор из bg_water/_full (оригиналы)
F_BOLD, F_SEMI = ROOT / "fonts" / "inter" / "Inter-Bold.ttf", ROOT / "fonts" / "inter" / "Inter-SemiBold.ttf"
F_MED, F_REG = ROOT / "fonts" / "inter" / "Inter-Medium.ttf", ROOT / "fonts" / "inter" / "Inter-Regular.ttf"
EXT = (".jpg", ".jpeg", ".png", ".webp")

BEZEL = (246, 243, 241)
# Пастельные цвета iMac: корпус/подбородок, ножка, текст метки, подложка метки
PALETTES = {
    "pink": {"body": (236, 182, 192), "dark": (214, 150, 163), "fg": (214, 74, 108), "bg": (250, 214, 223)},
    "peach": {"body": (247, 192, 152), "dark": (226, 162, 120), "fg": (214, 96, 36), "bg": (253, 225, 203)},
    "butter": {"body": (245, 219, 142), "dark": (222, 191, 108), "fg": (178, 118, 0), "bg": (252, 238, 188)},
    "sky": {"body": (178, 205, 235), "dark": (146, 176, 212), "fg": (36, 100, 196), "bg": (214, 230, 250)},
    "lilac": {"body": (206, 194, 238), "dark": (178, 164, 216), "fg": (110, 78, 200), "bg": (233, 226, 251)},
}
PAL = PALETTES["pink"]


def bg_palettes(src: Path) -> list[str]:
    """Гармоничные к фону цвета (по средневзвешенному тону и яркости воды): к бирюзе/зелени — без розового."""
    hsv = np.asarray(Image.open(src).convert("HSV").resize((240, 320)), dtype=np.float32)
    h, s_, v = hsv[..., 0] * 360 / 255, hsv[..., 1] / 255, hsv[..., 2] / 255
    m = (s_ > 0.15) & (v > 0.12)
    a = np.deg2rad(h[m])
    hue = (np.rad2deg(np.arctan2((np.sin(a) * s_[m]).sum(), (np.cos(a) * s_[m]).sum())) + 360) % 360
    val = float(v.mean())
    if hue < 180:                                   # бирюза / зелень
        return ["sky", "butter", "lilac"] if val >= 0.55 else ["peach", "butter"]
    return ["pink", "peach", "butter"] if val >= 0.58 else ["pink", "peach", "sky"]   # светлый бассейн / тёмное море
INK, INK2 = (20, 20, 22), (70, 70, 74)

SITES = [  # (ключ скринов, домен в адресной строке, заголовок ТЗ, описание ТЗ)
    ("neal", "neal.fun", "1. Neal.fun",
     "a collection of tiny interactive games and weird experiments you can lose an hour in"),
    ("radio", "radio.garden", "2. Radio Garden", "spin a globe and listen to live radio from anywhere in the world"),
    ("window", "window-swap.com", "3. Window Swap", "look out of strangers' windows from around the world"),
    ("drops", "drops.game", "4. Drops",
     "upload any song and it builds a playable game around its tempo and mood, free to start and plays right in the browser"),
    ("patatap", "patatap.com", "5. Patatap", "press any key to make sounds and animations, weirdly relaxing"),
]


def font(path: Path, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), px)


def text_img(s: str, f: ImageFont.FreeTypeFont, fill, track: float = 0.0) -> Image.Image:
    """Строка с трекингом (доля кегля), RGBA по габаритам букв."""
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    xs, x = [], 0.0
    for ch in s:
        xs.append(x)
        x += d.textlength(ch, font=f) + track * f.size
    asc, desc = f.getmetrics()
    im = Image.new("RGBA", (int(x - track * f.size) + 4, asc + desc + 4), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im)
    for ch, cx in zip(s, xs):
        dd.text((cx + 2, 2), ch, font=f, fill=fill)
    return im.crop(im.getbbox() or (0, 0, 1, 1))


def wrap(s: str, f: ImageFont.FreeTypeFont, width: int) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if f.getlength(t) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def rounded(size, r, fill) -> Image.Image:
    s = 3
    im = Image.new("RGBA", (size[0] * s, size[1] * s), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, size[0] * s - 1, size[1] * s - 1), r * s, fill=fill)
    return im.resize(size, Image.Resampling.LANCZOS)


def shadowed(el: Image.Image, blur=14, opacity=0.35, offset=(0, 8)) -> tuple[Image.Image, int]:
    pad = 40
    return add_shadow(el, blur=blur, opacity=opacity, offset=offset, grow=1, pad=pad), pad


def tag(s: str, px: int) -> Image.Image:
    """Розовая метка в квадратных скобках на светло-розовой подложке — как «[by plasmastarfish]» в рефе."""
    t = text_img(f"[{s}]", font(F_REG, px), PAL["fg"] + (255,), track=-0.01)
    pad_x, pad_y = round(px * 0.18), round(px * 0.12)
    out = Image.new("RGBA", (t.width + 2 * pad_x, t.height + 2 * pad_y), PAL["bg"] + (235,))
    out.alpha_composite(t, (pad_x, pad_y))
    return out


def star(r: int, fill) -> Image.Image:
    s = 4
    im = Image.new("RGBA", (r * 2 * s, r * 2 * s), (0, 0, 0, 0))
    pts = []
    for k in range(10):
        a = -np.pi / 2 + k * np.pi / 5
        rr = r * s if k % 2 == 0 else r * s * 0.45
        pts.append((r * s + rr * np.cos(a), r * s + rr * np.sin(a)))
    ImageDraw.Draw(im).polygon(pts, fill=fill)
    return im.resize((r * 2, r * 2), Image.Resampling.LANCZOS)


def stars(im: Image.Image, rng: random.Random, avoid: list[tuple[int, int, int, int]], n: int) -> None:
    placed = 0
    for _ in range(400):
        if placed >= n:
            break
        r = rng.randint(11, 22)
        x, y = rng.randint(30, W - 30), rng.randint(40, H - 60)
        if any(a - 30 < x < c + 30 and b - 30 < y < d + 30 for a, b, c, d in avoid):
            continue
        col = (255, 248, 220, 245) if rng.random() < 0.6 else (255, 255, 255, 240)
        s = add_shadow(star(r, col), blur=4, opacity=0.25, offset=(0, 1), grow=1, pad=10)
        im.alpha_composite(s, (x - s.width // 2, y - s.height // 2))
        placed += 1


def background(src: Path, rng: random.Random) -> Image.Image:
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    if rng.random() < 0.5:
        im = ImageOps.mirror(im)
    im = ImageOps.fit(im, (W, H), Image.Resampling.LANCZOS, centering=(rng.uniform(0.35, 0.65), rng.uniform(0.35, 0.65)))
    return im.convert("RGBA")


def address_bar(domain: str) -> Image.Image:
    w, h = 640, 60
    bar = rounded((w, h), 18, (255, 255, 255, 228))
    d = ImageDraw.Draw(bar)
    d.text((24, h // 2), "AA", font=font(F_MED, 17), fill=(120, 120, 126), anchor="lm")
    f = font(F_REG, 26)
    tw = f.getlength(domain)
    x0 = (w - tw) / 2 + 9
    lx, ly = x0 - 22, h // 2                                   # замок
    d.rounded_rectangle((lx - 7, ly - 3, lx + 7, ly + 8), 2, fill=(70, 70, 74))
    d.arc((lx - 5, ly - 12, lx + 5, ly + 2), 180, 360, fill=(70, 70, 74), width=2)
    d.text((x0, h // 2 + 1), domain, font=f, fill=(28, 28, 30), anchor="lm")
    cx, cy = w - 32, h // 2                                    # «обновить»
    d.arc((cx - 10, cy - 10, cx + 10, cy + 10), 40, 330, fill=(110, 110, 116), width=2)
    d.polygon([(cx + 9, cy - 11), (cx + 11, cy - 3), (cx + 3, cy - 5)], fill=(110, 110, 116))
    return bar


def imac(shot: Path) -> Image.Image:
    """Розовый iMac: светлая рамка экрана со скрином, розовый подбородок, ножка."""
    sw, sh = 680, 383
    bz = 16
    W_, H_ = sw + 2 * bz, sh + 2 * bz + 100 + 70
    out = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
    stand = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
    ImageDraw.Draw(stand).polygon([(W_ / 2 - 80, sh + 2 * bz + 80), (W_ / 2 + 80, sh + 2 * bz + 80),
                                   (W_ / 2 + 92, H_), (W_ / 2 - 92, H_)], fill=PAL["dark"] + (255,))
    out.alpha_composite(stand)
    body = rounded((W_, sh + 2 * bz + 100), 22, PAL["body"] + (255,))
    ImageDraw.Draw(body).rectangle((0, 0, W_, sh + 2 * bz - 1), fill=BEZEL + (255,))
    m = rounded((W_, sh + 2 * bz + 100), 22, (255, 255, 255, 255)).getchannel("A")
    body.putalpha(m)
    out.alpha_composite(body)
    d = ImageDraw.Draw(out)
    d.ellipse((W_ / 2 - 3, 5, W_ / 2 + 3, 11), fill=(60, 60, 64))
    scr = ImageOps.fit(ImageOps.exif_transpose(Image.open(shot)).convert("RGB"), (sw, sh), Image.Resampling.LANCZOS,
                       centering=(0.5, 0.0))
    scr = scr.filter(ImageFilter.UnsharpMask(radius=1.0, percent=40, threshold=2))
    out.paste(scr, (bz, bz))
    return out


def menu_pill() -> Image.Image:
    items = ["Copy", "Select All", "Look Up"]
    f = font(F_REG, 19)
    pad, gap = 18, 0
    ws = [f.getlength(t) + 2 * pad for t in items] + [44]
    w, h = int(sum(ws)), 46
    pill = rounded((w, h), 12, (252, 252, 252, 250))
    d = ImageDraw.Draw(pill)
    x = 0
    for k, t in enumerate(items):
        d.text((x + ws[k] / 2, h / 2), t, font=f, fill=(20, 20, 22), anchor="mm")
        x += ws[k]
        d.line((x, 9, x, h - 9), fill=(205, 205, 210), width=1)
    cx = x + 22
    d.line((cx - 4, h / 2 - 8, cx + 4, h / 2), fill=(30, 30, 32), width=3)
    d.line((cx + 4, h / 2, cx - 4, h / 2 + 8), fill=(30, 30, 32), width=3)
    return pill


def card(title: str, desc: str, width: int = 410) -> tuple[Image.Image, list]:
    """Белое окно: светофор, заголовок ТЗ (номер — розовой меткой), описание ТЗ. Возвращает картинку и боксы текста."""
    num, name = title.split(" ", 1)
    pad = 26
    ft = font(F_BOLD, 64)
    tw = width - 2 * pad
    while ft.getlength(name) > tw and ft.size > 36:
        ft = font(F_BOLD, ft.size - 2)
    t_img = text_img(name, ft, INK + (255,), track=-0.035)
    tg = tag(num, 28)
    fd = font(F_REG, 20)
    lines = wrap(desc, fd, tw)
    lh = 27
    h = pad + 26 + tg.height + 6 + t_img.height + 16 + lh * len(lines) + pad
    c = rounded((width, h), 20, (255, 255, 255, 255))
    d = ImageDraw.Draw(c)
    for k, col in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
        d.ellipse((pad + k * 20, pad - 2, pad + k * 20 + 11, pad + 9), fill=col)
    y = pad + 26
    c.alpha_composite(tg, (pad - 4, y))
    y += tg.height + 6
    c.alpha_composite(t_img, (pad - 2, y))
    y += t_img.height + 16
    for ln in lines:
        d.text((pad, y), ln, font=fd, fill=INK2)
        y += lh
    return c, [(pad - 4, pad + 26, width - pad, h - pad)]


def cursor(size: int = 46) -> Image.Image:
    s = 4
    im = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    pts = [(0.08, 0.05), (0.08, 0.80), (0.27, 0.62), (0.40, 0.92), (0.52, 0.87), (0.40, 0.58), (0.66, 0.58)]
    P = [(x * size * s, y * size * s) for x, y in pts]
    d = ImageDraw.Draw(im)
    d.polygon(P, fill=(255, 255, 255, 255), outline=(25, 25, 25, 255), width=3 * s)
    return add_shadow(im.resize((size, size), Image.Resampling.LANCZOS), blur=3, opacity=0.35, offset=(1, 2), grow=1, pad=8)


def slide_site(k: int, shot: Path, bg: Path, rng: random.Random) -> tuple[Image.Image, list]:
    key, domain, title, desc = SITES[k]
    im = background(bg, rng)
    jx, jy = rng.randint(-14, 14), rng.randint(-10, 10)
    bar = address_bar(domain)
    bx, by = (W - bar.width) // 2 + jx, 200 + jy
    mac = imac(shot)
    mx, my = (W - mac.width) // 2 + jx, by + bar.height + 36
    pill = menu_pill()
    cd, cboxes = card(title, desc)
    cx_ = min(900 - cd.width + 24, W // 2 + 30 + jx)
    cy_ = my + 383 + 32 + 22 + 46 + 10
    avoid = [(bx, by, bx + bar.width, by + bar.height), (mx, my, mx + mac.width, my + mac.height),
             (cx_, cy_, cx_ + cd.width, cy_ + cd.height)]
    stars(im, rng, avoid, rng.randint(9, 13))
    s, p = shadowed(bar, blur=10, opacity=0.2, offset=(0, 4)); im.alpha_composite(s, (bx - p, by - p))
    s, p = shadowed(mac, blur=18, opacity=0.35, offset=(0, 10)); im.alpha_composite(s, (mx - p, my - p))
    px_, py_ = mx + mac.width - pill.width - 4, my + 383 + 32 + 22
    s, p = shadowed(pill, blur=8, opacity=0.25, offset=(0, 3)); im.alpha_composite(s, (px_ - p, py_ - p))
    s, p = shadowed(cd, blur=18, opacity=0.3, offset=(0, 10)); im.alpha_composite(s, (cx_ - p, cy_ - p))
    cur = cursor()
    im.alpha_composite(cur, (cx_ + cd.width - 44, cy_ + cd.height - 44))
    boxes = [(bx + 60, by + 8, bx + bar.width - 60, by + bar.height - 8)]
    boxes += [(cx_ + a, cy_ + b, cx_ + c, cy_ + d) for a, b, c, d in cboxes]
    return im.convert("RGB"), boxes


def slide_cover(bg: Path, rng: random.Random) -> tuple[Image.Image, list]:
    """Обложка: «top 5» / «websites» / [to cure your] / «boredom» / (#4 is my favorite) / save for later!"""
    im = background(bg, rng)
    white = (255, 255, 255, 255)
    big = font(F_BOLD, 150)
    w1 = text_img("websites", big, white, track=-0.045)
    w2 = text_img("boredom", big, white, track=-0.045)
    while max(w1.width, w2.width) > 700:
        big = font(F_BOLD, big.size - 4)
        w1, w2 = text_img("websites", big, white, track=-0.045), text_img("boredom", big, white, track=-0.045)
    top = text_img("top 5", font(F_SEMI, 56), white, track=-0.02)
    fav = text_img("(#4 is my favorite)", font(F_SEMI, 40), white, track=-0.01)
    save = text_img("save for later!", font(F_SEMI, 34), white)
    tg = tag("to cure your", 34)
    cx = W // 2 + rng.randint(-10, 10)
    y = 470 + rng.randint(-25, 25)
    els = []
    x1 = cx - w1.width // 2
    els.append((top, x1 + 6, y)); y += top.height + 18
    els.append((w1, x1, y)); y += w1.height + 6
    els.append((tg, x1 + 80, y - 10)); y += tg.height + 4
    els.append((w2, cx - w2.width // 2, y)); y += w2.height + 26
    els.append((fav, cx - fav.width // 2, y)); y += fav.height + 30
    els.append((save, cx - save.width // 2, y))
    x0 = min(e[1] for e in els); y0 = min(e[2] for e in els)
    x1_ = max(e[1] + e[0].width for e in els); y1_ = max(e[2] + e[0].height for e in els)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for e, x, yy in els:
        if e is not tg:
            layer.alpha_composite(e, (x, yy))
    stars(im, rng, [(x0, y0, x1_, y1_)], rng.randint(12, 16))
    # светлая вода под текстом → мягкое затемнение пятном (на тёмной воде его нет), чтобы белый текст читался
    lum = float(np.asarray(im.convert("L").crop((x0, y0, x1_, y1_)), dtype=np.float32).mean()) / 255
    k = min(max((lum - 0.42) * 1.3, 0.0), 0.38)
    if k > 0:
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).ellipse((x0 - 90, y0 - 70, x1_ + 90, y1_ + 70), fill=int(255 * k))
        dim = Image.new("RGBA", (W, H), (8, 30, 40, 0))
        dim.putalpha(m.filter(ImageFilter.GaussianBlur(70)))
        im.alpha_composite(dim)
    # двойная тень: чёткий край + широкий мягкий ореол
    sh = add_shadow(layer, blur=3, opacity=0.55, offset=(0, 2), grow=1, pad=0)
    sh = add_shadow(sh, blur=22, opacity=0.4, offset=(0, 0), grow=8, pad=0)
    im.alpha_composite(sh)
    im.alpha_composite(add_shadow(tg, blur=6, opacity=0.3, offset=(0, 2), grow=1, pad=20),
                       (els[2][1] - 20, els[2][2] - 20))
    return im.convert("RGB"), [(x0, y0, x1_, y1_)]


def libs() -> tuple[list[Path], dict[str, list[Path]]]:
    bgs = sorted(f for f in BG.glob("*") if f.suffix.lower() in EXT and not f.name.startswith("_"))
    shots = {k: sorted(f for f in SHOTS.glob(f"{k}_*") if f.suffix.lower() in EXT) for k, *_ in SITES}
    return bgs, shots


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--flat", type=Path)
    ap.add_argument("--seed", type=int, default=1389)
    a = ap.parse_args()
    bgs, shots = libs()
    miss = [k for k, v in shots.items() if not v]
    if not bgs or miss:
        raise SystemExit(f"нет фонов ({len(bgs)}) или скринов: {miss}")
    n = a.n
    out = ROOT / "output" / ("1389_test" if a.test else f"carousels_1389_{n}")
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    pals = {bg: bg_palettes(bg) for bg in bgs}
    seen, manifest = set(), []
    global PAL
    for i in range(1, n + 1):
        for _ in range(200):
            bg = rng.choice(bgs)
            pal = rng.choice(pals[bg])
            pick = tuple(rng.choice(shots[k]) for k, *_ in SITES)
            key = (bg.name, pal) + tuple(p.name for p in pick)
            if key not in seen or len(seen) > 10 ** 6:
                break
        seen.add(key)
        PAL = PALETTES[pal]
        r = random.Random(a.seed * 10000 + i)
        slides = [slide_cover(bg, r)] + [slide_site(k, pick[k], bg, r) for k in range(len(SITES))]
        d = out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        qa = []
        for k, (im, boxes) in enumerate(slides, 1):
            for b in boxes:
                bad = check_box(W, H, b)
                if bad:
                    raise SystemExit(f"{i:03d} слайд {k}: текст вне безопасной зоны {b} — {bad}")
            im.save(d / f"{k}.jpg", quality=94)
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d / f"{k}.jpg", a.flat / f"sort_{k}_{i}_1389.jpg")
            if a.test:
                q = draw_overlay(im.copy())
                for b in boxes:
                    ImageDraw.Draw(q).rectangle(b, outline=(255, 200, 0), width=4)
                qa.append(q.resize((324, 432)))
        if a.test:
            sh = Image.new("RGB", (324 * len(qa), 432))
            for k, q in enumerate(qa):
                sh.paste(q, (k * 324, 0))
            sh.save(out / f"_qa_{i:03d}.jpg", quality=86)
        manifest.append({"carousel": d.name, "bg": key[0], "palette": pal, "shots": list(key[2:])})
        print(f"  {d.name}", flush=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"готово: {n} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
