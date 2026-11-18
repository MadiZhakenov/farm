#!/usr/bin/env python3
"""
Колибри 4 (Idle Bank Tycoon, ID 1) — «My mom thinks I own banks» 💀: storytime-карусель 8 слайдов (реф @chloe.dvss
7615411227421953302) + видео из тех же слайдов под драматичную музыку.
  1 ночь, кухня, счета · 2 письмо о повышении аренды · 3 сыр обратно на полку · 4 входящий звонок «Mom» (рисую)
  5 серьёзное селфи · 6 семейный чат (рисую) · 7 телефон с игрой · 8 на диване с игрой
Кадры Flow — output/kolibri4/slides/s<k>/*.jpg (3:4). Текст ТЗ дословно, переносы по смыслу, белый TikTok-шрифт с мягкой
тенью, как в рефе; позиция по высоте — своя у слайда (не закрывать лицо, письмо, сыр, экран игры).
Карусель 1080×1440, видео 1080×1920 (фото — по высоте с обрезкой боков, экраны 4 и 6 рисуются сразу в 9:16).

Музыка видео — по кругу все треки из downloads/kolibri4/music (кроме dramatic.mp3 — отклонён): видео i → трек (i-1) % N.

  python build_kolibri4.py --test                         # 5 каруселей + 5 видео → output/_work/kolibri4_test5
  python build_kolibri4.py -n 100 --carousels             # → output/kolibri4_carousels_100 + flat output/kolibri4_100
  python build_kolibri4.py -n 100 --video                 # → output/kolibri4_YT_100
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1380_carousels as C  # noqa: E402  (white_line — белый TikTok-шрифт с мягкой двойной тенью, эмодзи Apple)
import build_text_story as T  # noqa: E402  (draw_text / text_w с эмодзи — для экранов iPhone)
import render_imessage as IM  # noqa: E402
import strip_jpeg_meta  # noqa: E402
from core.safe_zones import check_box  # noqa: E402

W = 1080
SL = ROOT / "output" / "kolibri4" / "slides"
FONT_UI = ROOT / "fonts" / "inter" / "Inter-Bold.ttf"
FONT_UI_R = ROOT / "fonts" / "inter" / "Inter-Regular.ttf"

TEXTS = [
    ("2026 has been the most", "financially disrespectful year", "of my entire life 😭"),
    ("My landlord raised my rent", "and told me to 'stay positive'", "like GIRL WITH WHAT MONEY 💀"),
    ("I checked my account", "at the grocery store", "and had to put the CHEESE back.", "THE CHEESE."),
    ("Then my mom called asking", "if I was finally doing", "something productive with my life."),
    ("I told her I've actually been", "managing multiple banks lately."),
    ("She got so excited she told", "the entire family", "I was working in finance 😭"),
    ("The banks I've been managing:",),
    ("Anyway my virtual employees need me.", "My landlord can get in line 💀"),
]
# центр текста по высоте (доля кадра) для карусели 3:4 / видео 9:16
CY = {"c": [0.62, 0.27, 0.66, 0.45, 0.68, None, 0.755, 0.64], "v": [0.60, 0.30, 0.64, 0.45, 0.66, None, 0.775, 0.70]}
# 7: экран игры не закрываем — строка под телефоном, над рукой
VCX = {7: 0.8}                                          # 9:16 режет бока: на 8 слайде она справа — окно правее
CHAT_BAND = (395, 625)                                  # полоса под подпись в чате: от низа шапки iMessage (380 px) вниз
NAMES = ["Jess", "Kayla", "Maddie", "Emma", "Taylor", "Sarah", "Hannah", "Brooke"]
MOMS = ["Mom", "Mom ❤️", "Mommy", "Mom 🏡", "Mama"]
FAMILY_CHATS = ["Family 🏡", "The Fam ❤️", "Family Chat", "Fam 🫶", "Family 🥰"]


def cover(p: Path, w: int, h: int, rng: random.Random, cx: float = 0.5) -> Image.Image:
    """Фото по размеру кадра: лёгкий наезд 1.00–1.05 и сдвиг (своё у каждой карусели), яркость/тепло чуть по-разному."""
    im = Image.open(p).convert("RGB")
    z = rng.uniform(1.0, 1.05)
    cw, ch = im.width / z, im.height / z
    x0, y0 = rng.uniform(0, im.width - cw), rng.uniform(0, im.height - ch)
    im = im.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch)))
    im = ImageOps.fit(im, (w, h), Image.Resampling.LANCZOS, centering=(cx, 0.45))
    im = ImageEnhance.Brightness(im).enhance(rng.uniform(0.97, 1.04))
    return ImageEnhance.Color(im).enhance(rng.uniform(0.96, 1.06))


def caption(im: Image.Image, lines: tuple, cy: float, h: int, max_w: int, px: int = 56) -> list[tuple]:
    """Строки белым TikTok-шрифтом с мягкой тенью, блок по центру на высоте cy·h; кегль общий — по самой длинной строке."""
    for q in range(px, 30, -2):
        if all(C.white_line(ln, 10_000, q)[1][0] <= max_w for ln in lines):
            break
    sizes = [C.white_line(ln, 10_000, q)[1] for ln in lines]
    gap = int(q * 0.18)
    y = int(cy * h - (sum(s[1] for s in sizes) + gap * (len(lines) - 1)) / 2)
    boxes = []
    for ln, (tw, th) in zip(lines, sizes):
        blk, _ = C.white_line(ln, 10_000, q)
        ox, oy = (blk.width - tw) // 2, (blk.height - th) // 2
        x = (W - blk.width) // 2
        im.alpha_composite(blk, (x, y - oy))
        boxes.append((x + ox, y, x + ox + tw, y + th))
        y += th + gap
    return boxes


# ---------------------------------------------------------------- экран входящего звонка (iOS 17)
def handset_img(size: int, rot: float) -> Image.Image:
    """Залитая трубка как в iOS: контур трубки из Segoe Fluent Icons (U+E717), дырка внутри залита; rot — поворот."""
    import numpy as np
    from scipy.ndimage import binary_fill_holes
    k = 4
    S = size * k
    f = ImageFont.truetype("C:/Windows/Fonts/SegoeIcons.ttf", int(S * 0.62))
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).text((S / 2, S / 2), chr(0xE717), font=f, fill=255, anchor="mm")
    a = binary_fill_holes(np.asarray(m) > 100)
    im = Image.new("RGBA", (S, S), (255, 255, 255, 0))
    im.putalpha(Image.fromarray((a * 255).astype("uint8")))
    im = im.rotate(rot, resample=Image.Resampling.BICUBIC)
    return im.resize((size, size), Image.Resampling.LANCZOS)


INTER_VAR = ROOT / "fonts" / "inter_var" / "Inter-Variable.ttf"
CALL_NAMES = ["Mom", "Mommy", "Mama", "Mom", "Mother"]
POSTERS = [((92, 108, 140), (28, 34, 52)), ((88, 96, 108), (24, 26, 32)), ((84, 112, 118), (20, 40, 46)),
           ((104, 96, 128), (32, 28, 46)), ((70, 92, 128), (16, 24, 44))]


def glyph_icon(cp: int, size: int, fill_holes: bool) -> Image.Image:
    """Белая иконка из Segoe Fluent Icons; fill_holes — залить внутренность (пузырь сообщения — сплошной, как в iOS)."""
    import numpy as np
    from scipy.ndimage import binary_fill_holes
    k = 4
    S = size * k
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).text((S / 2, S / 2), chr(cp), font=ImageFont.truetype("C:/Windows/Fonts/SegoeIcons.ttf", int(S * 0.8)),
                            fill=255, anchor="mm")
    a = np.asarray(m) > 100
    if fill_holes:
        a = binary_fill_holes(a)
    im = Image.new("RGBA", (S, S), (255, 255, 255, 0))
    im.putalpha(Image.fromarray((a * 255).astype("uint8")))
    return im.resize((size, size), Image.Resampling.LANCZOS)


def alarm_icon(size: int) -> Image.Image:
    """Будильник как в iOS: часы (Segoe U+E121) + два колокольчика сверху + ножки."""
    k = 4
    S = size * k
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    clock = glyph_icon(0xE121, int(S * 0.78), False)
    im.alpha_composite(clock, ((S - clock.width) // 2, int(S * 0.15)))
    d = ImageDraw.Draw(im)
    for cx, a0 in ((S * 0.2, 180), (S * 0.8, 270)):
        d.pieslice((cx - S * 0.17, S * 0.02, cx + S * 0.17, S * 0.36), a0, a0 + 90, fill="white")
    w = int(S * 0.07)
    d.line((S * 0.3, S * 0.86, S * 0.22, S * 0.97), fill="white", width=w)
    d.line((S * 0.7, S * 0.86, S * 0.78, S * 0.97), fill="white", width=w)
    return im.resize((size, size), Image.Resampling.LANCZOS)


def inter(px: int, weight: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(INTER_VAR), px)
    f.set_variation_by_axes([min(32, max(14, px / 3)), weight])
    return f


def incoming_call(bg: Path, h: int, rng: random.Random) -> Image.Image:
    """Входящий вызов iOS 17/18 с постером контакта (как видят его почти все — на заблокированном экране):
    сверху мелкое «mobile», под ним огромное тонкое имя по центру; фон — постер контакта (мягкий градиент);
    внизу круглые полупрозрачные «Message» слева и «Remind Me» справа, под ними плашка «slide to answer»
    с белым кружком и зелёной трубкой; справа сверху (i), полоска «домой»."""
    s = 2
    w, hh = W * s, h * s
    top, bot = rng.choice(POSTERS)
    # у каждой карусели свой оттенок и плавность постера — иначе одинаковые Mom+палитра дают байт-в-байт тот же слайд
    top, bot = (tuple(max(0, min(255, c + rng.randint(-12, 12))) for c in col) for col in (top, bot))
    gam = rng.uniform(0.85, 1.6)
    base = Image.new("RGBA", (w, hh))
    g = ImageDraw.Draw(base)
    for yy in range(hh):
        t = (yy / hh) ** gam
        g.line((0, yy, w, yy), fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bot)) + (255,))
    d = ImageDraw.Draw(base)
    fy = lambda f: f * hh                                   # noqa: E731
    # статус-бар
    clock = f"{rng.randint(5, 8)}:{rng.randint(10, 59):02d}"
    d.text((98 * s, 44 * s), clock, font=inter(int(42 * s), 600), fill="white")
    sx, sy0 = (W - 240) * s, 66 * s
    for i_, hb in enumerate((12, 18, 24, 30)):
        d.rounded_rectangle((sx + i_ * 15 * s, sy0 + (30 - hb) * s, sx + i_ * 15 * s + 10 * s, sy0 + 30 * s), radius=2 * s, fill="white")
    wx, wy = sx + 85 * s, sy0 + 31 * s
    for rr, wd in ((30, 6), (19, 6), (8, 8)):
        d.arc((wx - rr * s, wy - rr * s - 6 * s, wx + rr * s, wy + rr * s - 6 * s), 225, 315, fill="white", width=wd * s)
    bxx = sx + 130 * s
    d.rounded_rectangle((bxx, sy0 + 2 * s, bxx + 56 * s, sy0 + 30 * s), radius=8 * s, outline=(255, 255, 255, 150), width=3 * s)
    d.rounded_rectangle((bxx + 5 * s, sy0 + 7 * s, bxx + 34 * s, sy0 + 25 * s), radius=4 * s, fill="white")
    # (i) справа сверху
    ix, iy = (W - 80) * s, fy(0.105)
    d.ellipse((ix - 26 * s, iy - 26 * s, ix + 26 * s, iy + 26 * s), outline="white", width=4 * s)
    d.text((ix, iy + 2 * s), "i", font=inter(int(34 * s), 600), fill="white", anchor="mm")
    # mobile + огромное тонкое имя
    d.text((w / 2, fy(0.155)), "mobile", font=inter(int(46 * s), 600), fill="white", anchor="mm")
    name = rng.choice(CALL_NAMES)
    px = int(230 * s)
    while inter(px, 150).getlength(name) > w * 0.9:
        px -= 4 * s
    d.text((w / 2, fy(0.155) + 44 * s), name, font=inter(px, 150), fill="white", anchor="mt")
    # Message / Remind Me — полупрозрачные круги
    glass = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glass)
    cy_b = fy(0.70)
    rb = 66 * s
    for xf in (0.21, 0.79):
        gd.ellipse((xf * w - rb, cy_b - rb, xf * w + rb, cy_b + rb), fill=(255, 255, 255, 70))
    sl_y0, sl_y1 = fy(0.835), fy(0.835) + 150 * s
    gd.rounded_rectangle((0.09 * w, sl_y0, 0.91 * w, sl_y1), radius=75 * s, fill=(255, 255, 255, 70))
    base.alpha_composite(glass)
    d = ImageDraw.Draw(base)
    lab = inter(int(40 * s), 400)
    for xf, label, icon in ((0.21, "Message", glyph_icon(0xE8BD, int(64 * s), True)), (0.79, "Remind Me", alarm_icon(int(76 * s)))):
        cx = xf * w
        base.alpha_composite(icon, (int(cx - icon.width / 2), int(cy_b - icon.height / 2)))
        d = ImageDraw.Draw(base)
        d.text((cx, cy_b + rb + 42 * s), label, font=lab, fill="white", anchor="mm")
    # slide to answer
    kr = (sl_y1 - sl_y0) / 2 - 10 * s
    kx, ky = 0.09 * w + 10 * s + kr, (sl_y0 + sl_y1) / 2
    d.ellipse((kx - kr, ky - kr, kx + kr, ky + kr), fill="white")
    hs = handset_img(int(kr * 1.25), 0)
    green = Image.new("RGBA", hs.size, (48, 199, 90, 255))
    green.putalpha(hs.getchannel("A"))
    base.alpha_composite(green, (int(kx - hs.width / 2), int(ky - hs.height / 2)))
    d = ImageDraw.Draw(base)
    d.text(((kx + kr + 0.91 * w) / 2, ky), "slide to answer", font=inter(int(46 * s), 400), fill=(255, 255, 255, 235), anchor="mm")
    d.rounded_rectangle((w / 2 - 140 * s, hh - 26 * s, w / 2 + 140 * s, hh - 15 * s), radius=6 * s, fill="white")
    return base.resize((W, h), Image.Resampling.LANCZOS)


# ---------------------------------------------------------------- семейный чат iMessage (тёмная тема)
def group_chat(h: int, rng: random.Random, cap_band: tuple[int, int]) -> Image.Image:
    """Скрин группового чата: шапка с названием семьи, мамины сообщения и реакции родни, имя отправителя над пузырём.
    Между шапкой и перепиской — полоса под подпись ТЗ (cap_band — её верх и низ в итоговом кадре)."""
    s = IM.SS
    me = rng.choice(NAMES)
    msgs = [
        ("Mom", rng.choice(["EVERYONE!!! 📣", "BIG NEWS FAMILY 📣📣", "ok everyone listen 📣"])),
        ("Mom", rng.choice([f"{me} is working in FINANCE now 😭🙏", f"my baby {me} works in FINANCE now 😭🙏"])),
        ("Mom", rng.choice(["she manages MULTIPLE BANKS 🏦🏦", "she runs multiple banks!!! 🏦"])),
        (rng.choice(["Aunt Linda", "Aunt Carol", "Aunt Diane"]), rng.choice(["omg so proud of you sweetie!! 💕", "WOW congrats honey 🥹"])),
        ("Grandma", rng.choice(["Does she have a 401k", "Is it a good bank", "Tell her to call me about my savings"])),
        (rng.choice(["Uncle Mike", "Uncle Rob", "Uncle Dave"]), rng.choice(["finally someone in this family with money 😂", "can she get me a loan 😂"])),
        ("me", rng.choice(["mom…", "MOM 😭", "mom what"])),
    ]
    img = Image.new("RGBA", (W * s, h * s), IM.C_BG)
    d = ImageDraw.Draw(img)
    y = cap_band[1] * s + 18 * s
    tpx = 30 * s
    when = f"Today {rng.randint(5, 8)}:{rng.randint(10, 59):02d} PM"
    IM.T.draw_text(img, W * s / 2 - IM.T.text_w(when, tpx) / 2, y, when, tpx, fill=IM.C_GRAY)
    y += 60 * s
    prev = None
    px = IM.FONT_PX * s
    lh = round(px * IM.LINE_GAP)
    for who, text in msgs:
        right = who == "me"
        lines = IM.T.wrap(text, px, IM.MAX_W * s - 2 * IM.PAD_X * s)
        bw = int(max(IM.T.text_w(ln, px) for ln in lines) + 2 * IM.PAD_X * s)
        bh = int(lh * len(lines) + 2 * IM.PAD_Y * s)
        new_sender = who != prev
        need = ((IM.GAP_SWITCH if prev else 0) + (40 if not right else 0)) * s if new_sender else IM.GAP_SAME * s
        if y + need + bh > (h - 40) * s:              # не влезает — обрываем переписку, без «висящего» имени
            break
        if new_sender:
            y += (IM.GAP_SWITCH if prev else 0) * s
            if not right:
                IM.T.draw_text(img, (IM.SIDE + 40) * s, y, who, 28 * s, fill=IM.C_GRAY)
                y += 40 * s
        else:
            y += IM.GAP_SAME * s
        bx1 = (W - IM.SIDE) * s if right else (IM.SIDE + 40) * s + bw
        bx0 = bx1 - bw
        color = IM.C_ME if right else IM.C_THEM
        r = int(bh // 2) - 1
        d.rounded_rectangle((bx0, y, bx1, y + bh), radius=min(r, 40 * s), fill=color)
        ty = y + IM.PAD_Y * s
        for ln in lines:
            IM.T.draw_text(img, bx0 + IM.PAD_X * s, ty, ln, px)
            ty += lh
        y += bh
        prev = who
    IM.header(img, s, rng.choice(FAMILY_CHATS))
    d.rectangle((0, 0, W * s, IM.STATUS_H * s), fill=IM.C_HEADER)
    IM.status_bar(img, s, f"{rng.randint(5, 8)}:{rng.randint(10, 59):02d}")
    return img.resize((W, h), Image.Resampling.LANCZOS)


# ---------------------------------------------------------------- сборка
def pools() -> list[list[Path]]:
    out = []
    for k in range(1, 9):
        fs = sorted((SL / f"s{k}").glob("*.jpg")) + sorted((SL / f"s{k}").glob("*.png"))
        out.append(fs)
    return out


def plan(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    ps = pools()
    total = 1
    for p in ps:
        total *= max(1, len(p))
    rows, seen = [], set()
    while len(rows) < n:
        pick = [rng.choice(p).name if p else None for p in ps]
        key = tuple(pick)
        if key in seen and len(seen) < total:          # повтор сочетания — только когда все уже использованы
            continue
        seen.add(key)
        rows.append({"i": len(rows) + 1, "pick": pick, "seed": rng.randrange(1 << 30)})
    return rows


def slides(r: dict, mode: str) -> list[tuple[Image.Image, list[tuple]]]:
    h = 1440 if mode == "c" else 1920
    rng = random.Random(r["seed"])
    out = []
    for k in range(8):
        if k == 3:
            bg = SL / "s1" / r["pick"][0]
            im = incoming_call(bg, h, random.Random(r["seed"] * 31 + 4))   # свой rng: слайд 4 можно перерисовать отдельно
        elif k == 5:
            im = group_chat(h, rng, CHAT_BAND)
        else:
            cx = VCX.get(k, 0.5) if mode == "v" else 0.5
            im = cover(SL / f"s{k + 1}" / r["pick"][k], W, h, rng, cx).convert("RGBA")
        max_w = 720 if mode == "c" else 780
        cy = CY[mode][k] if k != 5 else (CHAT_BAND[0] + CHAT_BAND[1]) / 2 / h
        boxes = caption(im, TEXTS[k], cy, h, max_w)
        out.append((im.convert("RGB"), boxes))
    return out


def save_carousel(r: dict, out: Path, flat: Path | None, suffix: str) -> None:
    d = out / f"{r['i']:03d}"
    d.mkdir(parents=True, exist_ok=True)
    for k, (im, boxes) in enumerate(slides(r, "c"), 1):
        for b in boxes:
            if bad := check_box(W, 1440, b):
                raise SystemExit(f"{r['i']:03d} слайд {k}: текст вне безопасной зоны {b} — {bad}")
        im.save(d / f"{k}.jpg", quality=93)
        if flat:
            flat.mkdir(parents=True, exist_ok=True)
            shutil.copy2(d / f"{k}.jpg", flat / f"sort_{k}_{r['i']}_{suffix}.jpg")
    (d / "plan.json").write_text(json.dumps(r, indent=1), encoding="utf-8")


MUSIC = sorted(f for f in (ROOT / "downloads" / "kolibri4" / "music").glob("*.mp3") if f.name != "dramatic.mp3")
DUR = [2.6, 2.8, 2.8, 2.6, 2.4, 2.6, 2.0, 3.2]          # секунд на слайд: успеть прочитать, ~21 с


def save_video(r: dict, out: Path, work: Path, music: Path, music_ss: float, suffix: str) -> Path:
    fr = work / f"v{r['i']:03d}"
    fr.mkdir(parents=True, exist_ok=True)
    ins, fc, labels = [], [], []
    for k, (im, boxes) in enumerate(slides(r, "v")):
        for b in boxes:
            if bad := check_box(W, 1920, b):
                raise SystemExit(f"{r['i']:03d} кадр {k + 1}: текст вне безопасной зоны {b} — {bad}")
        p = fr / f"{k + 1}.png"
        im.save(p, compress_level=1)
        n = round(DUR[k] * 30)
        ins += ["-i", str(p)]
        fc.append(f"[{k}:v]format=yuv420p,loop=loop={n - 1}:size=1:start=0,settb=1/30,setpts=N[s{k}]")
        labels.append(f"[s{k}]")
    total = sum(round(x * 30) for x in DUR) / 30
    fc.append("".join(labels) + f"concat=n=8:v=1:a=0[v]")
    ins += ["-ss", f"{music_ss:.2f}", "-t", f"{total + 0.3:.2f}", "-i", str(music)]
    fc.append(f"[8:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
              f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=in:d=0.3,afade=t=out:st={total - 1.0:.3f}:d=1.0[a]")
    dest = out / f"{r['i']:03d}_{suffix}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
                    "-t", f"{total:.3f}", "-r", "30", "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27",
                    "-maxrate", "6M", "-bufsize", "12M", "-pix_fmt", "yuv420p",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-c:a", "aac", "-b:a", "160k",
                    "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
                    "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=",
                    "-movflags", "+faststart", str(dest)], check=True)
    shutil.rmtree(fr)
    return dest


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--carousels", action="store_true")
    ap.add_argument("--video", action="store_true")
    ap.add_argument("--seed", type=int, default=4401)
    ap.add_argument("--music", type=Path, default=None, help="один трек вместо круга из всех")
    ap.add_argument("--test-n", type=int, default=5)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--music-ss", type=float, default=0.0)
    ap.add_argument("--suffix", default="1")
    a = ap.parse_args()
    work = ROOT / "output" / "_work" / "kolibri4"
    work.mkdir(parents=True, exist_ok=True)
    tracks = [a.music] if a.music else MUSIC
    track = lambda i: tracks[(i - 1) % len(tracks)]          # noqa: E731
    if a.test:
        rows = plan(a.test_n, a.seed)
        out = ROOT / "output" / "_work" / "kolibri4_test5"
        for r in rows:
            save_carousel(r, out / "carousels", None, a.suffix)
            save_video(r, out, work, track(r["i"]), a.music_ss, a.suffix)
            print(f"  тест {r['i']:03d}: {r['pick']} · {track(r['i']).name}", flush=True)
        return 0
    rows = plan(a.n, a.seed)
    if a.carousels:
        out, flat = ROOT / "output" / "kolibri4_carousels_100", ROOT / "output" / "kolibri4_100"
        for r in rows:
            save_carousel(r, out, flat, a.suffix)
            print(f"  {r['i']:03d}", flush=True)
        sys.argv = ["strip", str(out), str(flat)]
        strip_jpeg_meta.main()
    if a.video:
        out = ROOT / "output" / "kolibri4_YT_100"
        out.mkdir(parents=True, exist_ok=True)
        rows_v = [r for r in plan(a.n, a.seed + 1) if not (out / f"{r['i']:03d}_{a.suffix}.mp4").exists()]
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(a.jobs) as ex:          # 4 параллельно: рисование слайдов — CPU, NVENC тянет 4 сессии
            futs = [ex.submit(save_video, r, out, work, track(r["i"]), a.music_ss, a.suffix) for r in rows_v]
            for r, f in zip(rows_v, futs):
                print(" ", f.result().name, track(r["i"]).name, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
