#!/usr/bin/env python3
"""
«Скриншот» переписки Instagram Direct (iPhone, тёмная или светлая тема) для слайдов каруселей.
Групповой чат: аватар и имя над первой репликой собеседника, большие эмодзи без пузыря, «Seen by …»,
реакции под пузырём, ссылки подчёркнуты. Ширина 1080 (скрин iPhone, ужатый до 1080).

Как в render_imessage (1248 s2): сообщения идут сверху под шапкой, ниже — пустой фон под подпись слайда.

  from render_igdm import Chat, render
  img = render(Chat(title="the girls 🫶", subtitle="Active now", avatars=[...], rows=[...]), height=1440)

rows: ("time", "8:14 PM") · ("me", "текст") · ("them", "текст", "mia", avatar_path) ·
      ("seen", "Seen by everyone") · ("react", "🔥😭", 3)  — реакция под предыдущим пузырём
"""

from __future__ import annotations

import sys
import urllib.request
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402  (разбор строки на текст/эмодзи)

W = 1080
SS = 3
PT = W / 430                      # px на pt iPhone (Pro Max: 430 pt в ширину)
FONT_VAR = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "variable" / "TikTokSans[opsz,slnt,wdth,wght].ttf"
ICONS = Path("C:/Windows/Fonts/SegoeIcons.ttf")
EMOJI_DIR = ROOT / "assets" / "emoji_apple_160"
EMOJI_CDN = "https://cdn.jsdelivr.net/gh/iamcal/emoji-data@master/img-apple-160/{key}.png"

STATUS_H = round(54 * PT)
HEADER_H = round(58 * PT)
MSG_PX = round(15.5 * PT)
PAD_X, PAD_Y = round(12 * PT), round(8.2 * PT)
LINE_GAP = 1.22
GAP_RUN, GAP_SWITCH = round(2 * PT), round(11 * PT)
R_BIG, R_SMALL = round(19 * PT), round(5 * PT)
SIDE_ME = round(12 * PT)
AV = round(28 * PT)
AV_X = round(12 * PT)
TH_X = AV_X + AV + round(8 * PT)
MAX_W = 0.66 * W
BIG_EMOJI = round(42 * PT)
SMALL_PX = round(12 * PT)

THEMES = {
    "dark": dict(bg=(0, 0, 0), text=(245, 245, 245), them=(38, 38, 38), gray=(168, 168, 168),
                 sub=(168, 168, 168), line=(38, 38, 38), field=(38, 38, 38), icon=(245, 245, 245),
                 me_text=(255, 255, 255), react_bg=(38, 38, 38), react_ring=(0, 0, 0)),
    "light": dict(bg=(255, 255, 255), text=(0, 0, 0), them=(239, 239, 239), gray=(115, 115, 115),
                  sub=(115, 115, 115), line=(219, 219, 219), field=(239, 239, 239), icon=(0, 0, 0),
                  me_text=(255, 255, 255), react_bg=(239, 239, 239), react_ring=(255, 255, 255)),
}
# фирменный градиент исходящих: сверху фиолетовый, снизу синий (зависит от места на экране)
ME_TOP, ME_BOT = (143, 52, 250), (55, 117, 255)


@dataclass
class Chat:
    title: str
    subtitle: str = ""
    avatars: list = field(default_factory=list)   # 1 файл — личка, 2 — группа (два кружка)
    rows: list = field(default_factory=list)
    theme: str = "dark"
    clock: str = "8:15"
    battery: float = 0.62


@lru_cache(maxsize=None)
def font(px: int, wght: int = 400) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_VAR), px)
    f.set_variation_by_axes([min(max(px / SS / PT, 8), 36), 100, wght, 0])
    return f


@lru_cache(maxsize=None)
def icon_font(px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ICONS), px)


@lru_cache(maxsize=None)
def emoji(cluster: str, px: int) -> Image.Image | None:
    EMOJI_DIR.mkdir(parents=True, exist_ok=True)
    for key in A._emoji_filename_keys(cluster):
        dest = EMOJI_DIR / f"{key}.png"
        if not (dest.is_file() and dest.stat().st_size > 100):
            try:
                req = urllib.request.Request(EMOJI_CDN.format(key=key), headers={"User-Agent": "Mozilla/5.0"})
                dest.write_bytes(urllib.request.urlopen(req, timeout=20).read())
            except Exception:
                dest.unlink(missing_ok=True)
                continue
        return Image.open(dest).convert("RGBA").resize((px, px), Image.Resampling.LANCZOS)
    return None


def comp(img: Image.Image, im: Image.Image, xy) -> None:
    """alpha_composite, которому можно отрицательные координаты (строки, ушедшие под шапку)."""
    x, y = int(xy[0]), int(xy[1])
    if x < 0 or y < 0:
        im = im.crop((max(0, -x), max(0, -y), im.width, im.height))
        x, y = max(0, x), max(0, y)
    if im.width > 0 and im.height > 0 and x < img.width and y < img.height:
        img.alpha_composite(im, (x, y))


def text_w(text: str, px: int, wght: int = 400) -> float:
    return sum(px * 1.12 if k == "emoji" else font(px, wght).getlength(c) for k, c in A._tokenize_runs(text))


def draw_text(img: Image.Image, x: float, y_top: float, text: str, px: int, fill, wght: int = 400,
              underline: bool = False) -> None:
    d = ImageDraw.Draw(img)
    f = font(px, wght)
    base = y_top + f.getmetrics()[0]
    cx = x
    for kind, chunk in A._tokenize_runs(text):
        if kind == "emoji":
            e = emoji(chunk, int(px * 1.02))
            if e is not None:
                comp(img, e, (int(cx + px * 0.05), int(base - px * 0.88)))
            cx += px * 1.12
        else:
            d.text((cx, base), chunk, font=f, fill=fill, anchor="ls")
            if underline:
                lw = f.getlength(chunk)
                d.line((cx, base + px * 0.12, cx + lw, base + px * 0.12), fill=fill, width=max(1, px // 16))
            cx += f.getlength(chunk)


def wrap(text: str, px: int, max_w: float) -> list[str]:
    """По словам; слово длиннее строки (ссылка) рвётся по символам, как в Instagram."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and text_w(trial, px) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
        while text_w(cur, px) > max_w:
            k = len(cur)
            while k > 1 and text_w(cur[:k], px) > max_w:
                k -= 1
            lines.append(cur[:k])
            cur = cur[k:]
    return lines + ([cur] if cur else [])


def only_emoji(text: str) -> bool:
    runs = [(k, c) for k, c in A._tokenize_runs(text.strip()) if c.strip()]
    return 0 < len(runs) <= 3 and all(k == "emoji" for k, _ in runs)


def circle(src, d: int) -> Image.Image:
    im = src if isinstance(src, Image.Image) else Image.open(src)
    im = ImageOps.fit(im.convert("RGB"), (d, d), Image.Resampling.LANCZOS).convert("RGBA")
    m = Image.new("L", (d * 4, d * 4), 0)
    ImageDraw.Draw(m).ellipse((0, 0, d * 4 - 1, d * 4 - 1), fill=255)
    im.putalpha(m.resize((d, d), Image.Resampling.LANCZOS))
    return im


def icon(img: Image.Image, cp: int, cx: float, cy: float, px: int, fill) -> None:
    ImageDraw.Draw(img).text((cx, cy), chr(cp), font=icon_font(px), fill=fill, anchor="mm")


def status_bar(img: Image.Image, s: int, c: Chat, th: dict) -> None:
    d = ImageDraw.Draw(img)
    fg = th["text"]
    draw_text(img, 96 * s, 50 * s, c.clock, 44 * s, fg, wght=600)
    x, y = (W - 240) * s, 66 * s
    for i, h in enumerate((12, 18, 24, 30)):
        d.rounded_rectangle((x + i * 15 * s, y + (30 - h) * s, x + i * 15 * s + 10 * s, y + 30 * s), radius=2 * s, fill=fg)
    wx, wy = x + 85 * s, y + 31 * s
    for r, wd in ((30, 6), (19, 6), (8, 8)):
        d.arc((wx - r * s, wy - r * s - 6 * s, wx + r * s, wy + r * s - 6 * s), 225, 315, fill=fg, width=wd * s)
    bx = x + 130 * s
    rim = (120, 120, 124) if c.theme == "dark" else (160, 160, 164)
    d.rounded_rectangle((bx, y + 2 * s, bx + 56 * s, y + 30 * s), radius=8 * s, outline=rim, width=3 * s)
    d.rounded_rectangle((bx + 5 * s, y + 7 * s, bx + 5 * s + int(46 * c.battery) * s, y + 25 * s), radius=4 * s, fill=fg)
    d.rounded_rectangle((bx + 59 * s, y + 11 * s, bx + 63 * s, y + 21 * s), radius=2 * s, fill=rim)


def header(img: Image.Image, s: int, c: Chat, th: dict) -> None:
    d = ImageDraw.Draw(img)
    top, bot = STATUS_H * s, (STATUS_H + HEADER_H) * s
    d.rectangle((0, 0, W * s, bot), fill=th["bg"])
    cy = (top + bot) / 2
    icon(img, 0xE76B, 30 * PT / 1.1 * s, cy, int(26 * PT * s), th["icon"])
    ax = 44 * PT * s
    if len(c.avatars) >= 2:                        # группа: два кружка внахлёст
        d2 = int(25 * PT * s)
        a1, a2 = circle(c.avatars[0], d2), circle(c.avatars[1], d2)
        ring = int(2 * PT * s)
        comp(img, a1, (int(ax), int(cy - d2 * 0.82)))
        r2 = Image.new("RGBA", (d2 + 2 * ring, d2 + 2 * ring), (0, 0, 0, 0))
        ImageDraw.Draw(r2).ellipse((0, 0, d2 + 2 * ring - 1, d2 + 2 * ring - 1), fill=th["bg"] + (255,))
        comp(img, r2, (int(ax + d2 * 0.42 - ring), int(cy - d2 * 0.18 - ring)))
        comp(img, a2, (int(ax + d2 * 0.42), int(cy - d2 * 0.18)))
        tx = ax + d2 * 1.42 + 10 * PT * s
    else:
        d1 = int(34 * PT * s)
        if c.avatars:
            comp(img, circle(c.avatars[0], d1), (int(ax), int(cy - d1 / 2)))
        tx = ax + d1 + 10 * PT * s
    npx, spx = int(16 * PT * s), int(12 * PT * s)
    if c.subtitle:
        draw_text(img, tx, cy - npx * 1.08, c.title, npx, th["text"], wght=650)
        draw_text(img, tx, cy + spx * 0.05, c.subtitle, spx, th["sub"])
    else:
        draw_text(img, tx, cy - npx * 0.62, c.title, npx, th["text"], wght=650)
    ip = int(25 * PT * s)
    icon(img, 0xE717, (W - 92 * PT) * s, cy, ip, th["icon"])
    icon(img, 0xE714, (W - 36 * PT) * s, cy, int(ip * 1.05), th["icon"])


def me_color(y: float, total: float) -> tuple:
    t = min(max(y / total, 0), 1)
    return tuple(int(a + (b - a) * t) for a, b in zip(ME_TOP, ME_BOT))


def gradient_bubble(img: Image.Image, box, radii, s: int, total_h: float) -> None:
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = x1 - x0, y1 - y0
    grad = Image.new("RGBA", (1, h))
    for yy in range(h):
        grad.putpixel((0, yy), me_color(y0 + yy, total_h) + (255,))
    grad = grad.resize((w, h))
    m = rounded_mask(w, h, radii)
    img.paste(grad, (x0, y0), m)


def rounded_mask(w: int, h: int, radii) -> Image.Image:
    """Маска пузыря с разными радиусами углов (tl, tr, br, bl)."""
    m = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(m)
    for corner, rr in zip(("tl", "tr", "br", "bl"), radii):
        rr = int(min(rr, w / 2, h / 2))
        if rr <= 0:
            continue
        x0 = 0 if corner in ("tl", "bl") else w - rr
        y0 = 0 if corner in ("tl", "tr") else h - rr
        cx0 = 0 if corner in ("tl", "bl") else w - 2 * rr
        cy0 = 0 if corner in ("tl", "tr") else h - 2 * rr
        d.rectangle((x0, y0, x0 + rr, y0 + rr), fill=0)
        d.ellipse((cx0, cy0, cx0 + 2 * rr - 1, cy0 + 2 * rr - 1), fill=255)
    return m


def bubble(img: Image.Image, box, radii, color) -> None:
    x0, y0, x1, y1 = [int(v) for v in box]
    m = rounded_mask(x1 - x0, y1 - y0, radii)
    img.paste(Image.new("RGBA", (x1 - x0, y1 - y0), tuple(color) + (255,)), (x0, y0), m)


def input_bar(img: Image.Image, s: int, height: int, th: dict) -> None:
    d = ImageDraw.Draw(img)
    hbar = 34 * PT
    fh = 44 * PT
    top = height - hbar - fh - 8 * PT
    d.rectangle((0, (top - 8 * PT) * s, W * s, height * s), fill=th["bg"])
    x0, x1 = 12 * PT, W - 12 * PT
    d.rounded_rectangle((x0 * s, top * s, x1 * s, (top + fh) * s), radius=fh / 2 * s, fill=th["field"])
    cr = 18 * PT
    ccx, ccy = x0 + 4 * PT + cr, top + fh / 2
    cam = Image.new("RGBA", (int(2 * cr * s), int(2 * cr * s)))
    g = Image.new("RGBA", (1, cam.height))
    for yy in range(cam.height):
        t = yy / cam.height
        g.putpixel((0, yy), tuple(int(a + (b - a) * t) for a, b in zip((88, 81, 219), (55, 151, 240))) + (255,))
    cam = g.resize(cam.size)
    img.paste(cam, (int((ccx - cr) * s), int((ccy - cr) * s)), circle(Image.new("RGB", cam.size, "white"), cam.width).split()[3])
    icon(img, 0xE722, ccx * s, ccy * s, int(19 * PT * s), (255, 255, 255))
    draw_text(img, (ccx + cr + 9 * PT) * s, (ccy - 10.5 * PT) * s, "Message...", int(16 * PT * s), th["gray"])
    for i, cp in enumerate((0xE720, 0xE91B, 0xE76E)):
        icon(img, cp, (x1 - 22 * PT - i * 38 * PT) * s, ccy * s, int(22 * PT * s), th["icon"])
    hb = height - 9 * PT
    d.rounded_rectangle(((W / 2 - 67 * PT) * s, (hb - 2.5 * PT) * s, (W / 2 + 67 * PT) * s, (hb + 2.5 * PT) * s),
                        radius=3 * PT * s, fill=th["text"])


def input_top(height: int) -> float:
    """Верх строки ввода (px) — над ней в Instagram заканчивается переписка."""
    return height - 34 * PT - 44 * PT - 8 * PT


def link_card(img: Image.Image, s: int, x1: float, y: float, row, th: dict) -> tuple[float, float]:
    """Превью ссылки (исходящее): картинка сверху, ниже название и домен. → (x0, высота)."""
    _k, src, title, domain = row[:4]
    cw = 200 * PT * s
    ih = cw / 1.91
    ttl_px, dom_px = int(14.5 * PT * s), int(12 * PT * s)
    pad = 11 * PT * s
    th_ = ih + pad + ttl_px * 1.25 + dom_px * 1.3 + pad
    x0 = x1 - cw
    im = src if isinstance(src, Image.Image) else Image.open(src)
    pic = ImageOps.fit(im.convert("RGB"), (int(cw), int(ih)), Image.Resampling.LANCZOS)
    card = Image.new("RGBA", (int(cw), int(th_)), th["them"] + (255,))
    card.paste(pic, (0, 0))
    while text_w(title, ttl_px, 600) > cw - 2 * pad and len(title) > 4:   # длинное название — с многоточием
        title = title[:-2].rstrip() + "…"
    draw_text(card, pad, ih + pad * 0.9, title, ttl_px, th["text"], wght=600)
    draw_text(card, pad, ih + pad * 0.9 + ttl_px * 1.3, domain, dom_px, th["gray"])
    r = int(R_BIG * s)
    img.paste(card, (int(x0), int(y)), rounded_mask(card.width, card.height, (r, r, r, r)))
    return x0, th_


def _rows(img: Image.Image, c: Chat, y: float, height: int, th: dict) -> tuple[float, dict]:
    """Рисует строки переписки с y (px×SS); → (низ, отметки ("mark", имя) → y)."""
    s = SS
    rows = c.rows
    marks, boxes = {}, []

    def same_run(i: int, j: int) -> bool:
        if not (0 <= j < len(rows)):
            return False
        a, b = rows[i], rows[j]
        if a[0] != b[0] or a[0] not in ("me", "them"):
            return False
        return a[0] == "me" or a[2] == b[2]

    prev_bubble = None
    for i, row in enumerate(rows):
        kind = row[0]
        if kind == "mark":
            marks[row[1]] = y / s
            continue
        if kind == "time":
            y += 10 * PT * s
            tpx = int(12 * PT * s)
            tw = text_w(row[1], tpx, 600)
            draw_text(img, W * s / 2 - tw / 2, y, row[1], tpx, th["gray"], wght=600)
            boxes.append(((W * s / 2 - tw / 2) / s, y / s, (W * s / 2 + tw / 2) / s, (y + tpx * 1.2) / s))
            y += 30 * PT * s
            prev_bubble = None
            continue
        if kind == "seen":
            spx = int(12 * PT * s)
            draw_text(img, (W - SIDE_ME) * s - text_w(row[1], spx), y + 4 * PT * s, row[1], spx, th["gray"])
            boxes.append((((W - SIDE_ME) * s - text_w(row[1], spx)) / s, y / s, W - SIDE_ME, (y + 22 * PT * s) / s))
            y += 22 * PT * s
            continue
        if kind == "react" and prev_bubble:
            x0, y1, right = prev_bubble
            px = int(13 * PT * s)
            label = row[1] + (f" {row[2]}" if len(row) > 2 and row[2] else "")
            pw = text_w(label, px) + 14 * PT * s
            ph = 24 * PT * s
            rx = (x0 - pw + 8 * PT * s) if right else (x0 + 4 * PT * s)
            ry = y1 - 4 * PT * s
            d = ImageDraw.Draw(img)
            ring = 3 * PT * s
            d.rounded_rectangle((rx - ring, ry - ring, rx + pw + ring, ry + ph + ring), radius=ph, fill=th["react_ring"])
            d.rounded_rectangle((rx, ry, rx + pw, ry + ph), radius=ph, fill=th["react_bg"])
            draw_text(img, rx + 7 * PT * s, ry + 4.2 * PT * s, label, px, th["text"])
            boxes.append((rx / s, ry / s, (rx + pw) / s, (ry + ph) / s))
            y += 20 * PT * s
            continue
        if kind == "card":
            if prev_bubble is not None:
                y += GAP_SWITCH * s
            x1 = (W - SIDE_ME) * s
            x0, ch = link_card(img, s, x1, y, row, th)
            prev_bubble = (x1, y + ch, True)
            boxes.append((x0 / s, y / s, x1 / s, (y + ch) / s))
            y += ch
            continue
        if kind == "photo":                                       # ("photo", картинка, "me"|"them", имя, аватар) — фото-сообщение
            src, side = row[1], row[2]
            right = side == "me"
            im = (src if isinstance(src, Image.Image) else Image.open(src)).convert("RGB")
            pw = (row[5] if len(row) > 5 else 0.5) * W * s                # доля ширины экрана
            ph = min(pw * im.height / im.width, 1.25 * pw)
            pic = ImageOps.fit(im, (int(pw), int(ph)), Image.Resampling.LANCZOS, centering=(0.5, 0.0))
            if prev_bubble is not None:
                y += GAP_SWITCH * s
            if not right and len(row) > 3 and row[3]:
                npx = int(12 * PT * s)
                draw_text(img, (TH_X + 12 * PT) * s, y, row[3], npx, th["gray"])
                y += 18 * PT * s
            bx0 = (W - SIDE_ME) * s - pw if right else TH_X * s
            rr = int(R_BIG * s)
            img.paste(pic, (int(bx0), int(y)), rounded_mask(pic.width, pic.height, (rr, rr, rr, rr)))
            if not right and len(row) > 4 and row[4]:
                comp(img, circle(row[4], AV * s), (int(AV_X * s), int(y + ph - AV * s)))
            prev_bubble = (bx0 + pw if right else bx0, y + ph, right)
            boxes.append(((AV_X * s if not right else bx0) / s, y / s, (bx0 + pw) / s, (y + ph) / s))
            y += ph
            continue
        if kind not in ("me", "them"):
            continue
        text = row[1]
        right = kind == "me"
        first = not same_run(i, i - 1)
        last = not same_run(i, i + 1)
        if prev_bubble is not None:
            y += (GAP_RUN if not first else GAP_SWITCH) * s
        if not right and first and len(row) > 2 and row[2]:
            npx = int(12 * PT * s)
            draw_text(img, (TH_X + 12 * PT) * s, y, row[2], npx, th["gray"])
            boxes.append((TH_X + 12 * PT, y / s, TH_X + 12 * PT + text_w(row[2], npx) / s, (y + 18 * PT * s) / s))
            y += 18 * PT * s
        link = text.startswith("[link]")
        text = text.removeprefix("[link]")
        if only_emoji(text):
            ep = BIG_EMOJI * s
            n = len([1 for k, ch in A._tokenize_runs(text) if k == "emoji"])
            bw, bh = int(ep * 1.08 * n), int(ep * 1.05)
            bx1 = (W - SIDE_ME) * s if right else TH_X * s + bw
            bx0 = bx1 - bw
            cx = bx0
            for k, ch in A._tokenize_runs(text):
                if k == "emoji":
                    e = emoji(ch, int(ep))
                    if e is not None:
                        comp(img, e, (int(cx), int(y)))
                    cx += ep * 1.08
        else:
            px = MSG_PX * s
            lines = wrap(text, px, MAX_W * s - 2 * PAD_X * s)
            lh = round(px * LINE_GAP)
            bw = int(max(text_w(ln, px) for ln in lines) + 2 * PAD_X * s)
            bh = int(lh * len(lines) + 2 * PAD_Y * s)
            bx1 = (W - SIDE_ME) * s if right else TH_X * s + bw
            bx0 = bx1 - bw
            R, r = min(R_BIG * s, bh / 2), R_SMALL * s
            if right:   # tl, tr, br, bl
                radii = (R, R if first else r, R if last else r, R)
                gradient_bubble(img, (bx0, y, bx1, y + bh), [int(v) for v in radii], s, height * s)
                fg = th["me_text"]
            else:
                radii = (R if first else r, R, R, R if last else r)
                bubble(img, (bx0, y, bx1, y + bh), [int(v) for v in radii], th["them"])
                fg = th["text"]
            ty = y + PAD_Y * s
            for ln in lines:
                draw_text(img, bx0 + PAD_X * s, ty + px * 0.03, ln, px, fg, underline=link)
                ty += lh
        if not right and last and len(row) > 3 and row[3]:
            a = circle(row[3], AV * s)
            comp(img, a, (int(AV_X * s), int(y + bh - AV * s)))
        prev_bubble = (bx1 if right else bx0, y + bh, right)
        boxes.append(((AV_X * s if not right else bx0) / s, y / s, bx1 / s, (y + bh) / s))
        y += bh
    _rows.boxes = boxes
    return y / s, marks


def render(c: Chat, height: int = 1440, full: bool = False, top_gap: float = 14, anchor: str = "top") -> Image.Image:
    """Скрин W×height. full — строка ввода внизу; anchor="bottom" — переписка прижата к строке ввода,
    как в Instagram (старые сообщения уходят под шапку). render.bottom / render.marks / render.header_bottom —
    координаты для подписи слайда."""
    s = SS
    th = THEMES[c.theme]
    y0 = STATUS_H + HEADER_H + top_gap * PT
    if anchor == "bottom":
        probe = Image.new("RGBA", (W * s, (height + 4000) * s), th["bg"] + (255,))
        end, _m = _rows(probe, c, 0, height, th)
        y0 = (input_top(height) if full else height) - 10 * PT - end
    img = Image.new("RGBA", (W * s, height * s), th["bg"] + (255,))
    render.bottom, render.marks = _rows(img, c, y0 * s, height, th)
    render.boxes = _rows.boxes          # (x0, y0, x1, y1) в px кадра: пузыри, имена, время, реакции, Seen
    render.header_bottom = STATUS_H + HEADER_H
    if full:
        input_bar(img, s, height, th)
    header(img, s, c, th)
    status_bar(img, s, c, th)
    return img.resize((W, height), Image.Resampling.LANCZOS).convert("RGB")


if __name__ == "__main__":
    import random
    av = sorted((ROOT / "output" / "1283_pool" / "s7").glob("*.jpg"))[:6]
    rng = random.Random(1)
    c = Chat(title="the girls 🫶", subtitle="mia, jess, sam and 2 others", avatars=[av[0], av[1]], rows=[
        ("time", "Yesterday 6:02 PM"),
        ("them", "who's free saturday", "mia", av[0]),
        ("them", "me!!", "jess", av[2]),
        ("time", "8:14 PM"),
        ("me", "[link]soundcloud.com/lilyhart/first-light"),
        ("me", "new song out now 🎧"),
        ("them", "🔥", "jess", av[2]),
        ("them", "sounds good bro", "sam", av[3]),
        ("seen", "Seen by mia, ava"),
    ], clock="8:21")
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "output" / "_work" / "igdm_test.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    render(c, 1440).save(out)
    c.theme = "light"
    render(c, 2340, full=True).save(out.with_name(out.stem + "_light.png"))
    print(out)
