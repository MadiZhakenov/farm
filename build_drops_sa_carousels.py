#!/usr/bin/env python3
"""
Drops (drops.game) — «small artists» промо: три карусели 3:4 (1080×1440), по 150, айди пока нет → папки drops_sa_*.
Тексты ТЗ дословно (переносы по смыслу), TikTok-шрифт с обводкой как в 1388d, всё в безопасной рамке core/safe_zones.

  A (4) small artists, stop sending "pls stream"…   s1 зеркальное селфи + подпись снизу · s2 чат с вялыми ответами
        + сториз с неоткрытой ссылкой · s3 экраны Drops (загрузка + Wizard; пока нет входа — заглушка/главная)
        · s4 игра + сообщение друга со счётом
  B (4) promo ideas … that aren't another SNIPPET     s1 селфи в наушниках + подпись · s2 заметка со списком и постом
        «3 likes» · s3 игра на Drops · s4 чат со ссылкой на игру
  C (5) free promo tips … (slide 3 is NEW)           s1 студия + подпись · s2 заметка на крупном плане той же студии
        · s3 игра (ярче) · s4 заметка на чате с друзьями · s5 заметка на комментариях под постом

Фото — output/drops_sa_slides/<c1_s1|c2_s1|c3_s1|c3_s2> (Flow, «живые» по правилу). Чаты/сториз/посты/комменты
рисуются заново для каждой карусели (имена, время, аватарки — разные). Метаданные JPEG вычищаются.

  python build_drops_sa_carousels.py --set C -n 4 --out output/drops_sa_test/C --qa
  python build_drops_sa_carousels.py --set C -n 150 --out output/carousels_drops_sa_C --flat output/drops_sa_C_150
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1388d_carousels as D  # noqa: E402  (чаты 1388d, превью ссылки на игру, кадры игр, раскладки)
import strip_jpeg_meta  # noqa: E402
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402

R, C, B = D.R, D.C, D.B
W, H = 1080, 1440
X0, Y0, X1, Y1 = text_rect(W, H)
SL = ROOT / "output" / "drops_sa_slides"
SITE = ROOT / "downloads" / "1388d" / "site"
SCREENS = sorted((ROOT / "output" / "1388d_slides" / "s3_photo").glob("*.jpg"))   # iMac / MacBook с drops.game
GAMES_OK = sorted((ROOT / "output" / "1388d_slides" / "s4").glob("*.png"))   # отобранные кадры игр (1388d)
GAMES_PLAY = [g for g in GAMES_OK if "_title" not in g.name]   # под скрин чата: без чёрной заставки (сливается с чатом)
NL = "\n"

TEXTS = {
    "A": ["small artists,\nstop sending “pls stream”.\ndo THIS instead",
          "what i used to do:\nstory post, snippet, link in bio,\nspam the group chat\n\nwhat i got:\n🔥 / “sounds good bro” / (seen)",
          "what i do now:\nupload the track to drops,\nanswer a few questions,\nand it turns into a game",
          "my friends actually\nopen it and play 😭"],
    "B": ["promo ideas for small artists\nthat aren’t another SNIPPET",
          None,                                        # заметка: см. NOTE_B
          "idea that’s actually different:\nturn the whole song\ninto something people can play",
          "i uploaded my song to drops,\nanswered a few questions,\nand sent my friends the play link"],
    "C": ["free promo tips\nfor small artists\n(slide 3 is NEW)",
          None,                                        # заметки: NOTE_C
          "2. turn your track into a game\npeople can play 🎮\n\ni tried drops",
          None, None],
}
FOOT = {"A": "me every release day 🙃", "B": "new song loading…\nand my motivation too", "C": "things i wish i knew sooner"}
NOTE_B = ("ideas everyone already tried:",
          ["1. 15 second snippet", "2. “link in bio”", "3. story countdown", "",
           "the result: 3 likes and my mom 🫶"])
NOTE_C3 = ("2. turn your track into a game people can play 🎮", "i tried drops")
NOTE_C = {2: "1. post the process, not just the song", 4: "3. ask 3 friends for honest feedback before you release",
          5: "4. reply to every comment in the first hour"}



# ---------------------------------------------------------------- подписи (TikTok-шрифт с обводкой, как 1388d)
def cap(text: str, top: float, bottom: float, cx: float = 0.5, mw: float | None = None,
        glow: bool = False) -> tuple[Image.Image, tuple]:
    top, bottom = max(int(top * H), Y0), min(int(bottom * H), Y1)
    block = C.block_for(text, bottom - top, int(mw * W) if mw else X1 - X0)
    x = max(X0, min(X1 - block.width, int(cx * W - block.width / 2)))
    y = max(Y0, min(Y1 - block.height, int((top + bottom) / 2 - block.height / 2)))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if glow:
        layer.alpha_composite(D.glow_block(block), (x - 70, y - 70))
    else:
        layer.alpha_composite(block, (x, y))
    return layer, (x, y, x + block.width, y + block.height)


def cap_plate(text: str, top: float, bottom: float) -> tuple[Image.Image, tuple]:
    """Подпись на геймплее: чёрный текст на белых слитых плашках TikTok (как 1307), по центру полосы [top, bottom]."""
    import build_1307_carousels as P
    lines = [B.A.sanitize_overlay_text(B.R._normalize_text(ln)) for ln in text.split(NL) if ln.strip()]
    top, bottom = max(int(top * H), Y0), min(int(bottom * H), Y1)
    for px in range(58, 30, -2):
        pl = P.plate_block(lines, px)
        if pl.width <= X1 - X0 + 40 and pl.height <= bottom - top + 60:
            break
    x = (W - pl.width) // 2
    y = max(Y0 - 20, min(Y1 - pl.height, int((top + bottom) / 2 - pl.height / 2)))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.alpha_composite(pl, (x, y))
    pad = int(0.42 * px)                                     # поля плашки — не текст
    return layer, (x + pad, y + pad // 2, x + pl.width - pad, y + pl.height - pad // 2)


def fit(src: Path | Image.Image, size=(W, H), centering=(0.5, 0.45)) -> Image.Image:
    im = src if isinstance(src, Image.Image) else Image.open(src)
    return ImageOps.fit(im.convert("RGB"), size, Image.Resampling.LANCZOS, centering=centering).convert("RGBA")


def photo_two(photo: Path, head: str, foot: str, lay: dict) -> tuple[Image.Image, list]:
    """Фото на весь кадр: заголовок сверху, короткая подпись снизу (над интерфейсом TikTok)."""
    bg = fit(photo)
    a, ba = cap(head, *lay["head"])
    b, bb = cap(foot, *lay["foot"])
    return Image.alpha_composite(Image.alpha_composite(bg, a), b).convert("RGB"), [ba, bb]


# ---------------------------------------------------------------- шрифт iOS (SF Pro → Inter) с Apple-эмодзи
SF = {400: ROOT / "fonts" / "inter" / "Inter-Regular.ttf", 500: ROOT / "fonts" / "inter" / "Inter-Medium.ttf",
      600: ROOT / "fonts" / "inter" / "Inter-SemiBold.ttf", 700: ROOT / "fonts" / "inter" / "Inter-Bold.ttf"}


def sf(px: float, wght: int = 400):
    from PIL import ImageFont
    return ImageFont.truetype(str(SF[wght]), int(px))


def sf_w(text: str, px: float, wght: int = 400) -> float:
    f, w = sf(px, wght), 0.0
    for kind, ch in B.A._tokenize_runs(text):
        w += px * 1.18 if kind == "emoji" else f.getlength(ch)
    return w


def sf_text(img: Image.Image, x: float, y_top: float, text: str, px: float, fill, wght: int = 400) -> None:
    f = sf(px, wght)
    base = y_top + f.getmetrics()[0]
    d = ImageDraw.Draw(img)
    for kind, ch in B.A._tokenize_runs(text):
        if kind == "emoji":
            e = R.emoji(ch, int(px * 1.06))
            if e is not None:
                R.comp(img, e, (int(x + px * 0.06), int(base - px * 0.9)))
            x += px * 1.18
        else:
            d.text((x, base), ch, font=f, fill=fill, anchor="ls")
            x += f.getlength(ch)


def sf_wrap(text: str, px: float, wght: int, max_w: float) -> list[str]:
    lines, cur = [], ""
    for w in text.split(" "):
        t = (cur + " " + w).strip()
        if sf_w(t, px, wght) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + [cur]


# ---------------------------------------------------------------- «Заметки» iPhone: скрин экрана заметки
NOTES_TINT = (227, 168, 0)                               # жёлтый акцент приложения Notes (светлая тема)
PT = R.PT


def notes_icons(img: Image.Image, s: int, cy: float) -> None:
    """Шапка Notes без редактирования: «‹ Notes» слева, справа «поделиться» и «⋯» в кружке."""
    d = ImageDraw.Draw(img)
    c, lw = NOTES_TINT, int(2.3 * PT * s)
    x0 = 10 * PT
    d.line([((x0 + 8 * PT) * s, (cy - 10 * PT) * s), (x0 * s, cy * s), ((x0 + 8 * PT) * s, (cy + 10 * PT) * s)],
           fill=c, width=lw, joint="curve")
    sf_text(img, (x0 + 15 * PT) * s, (cy - 12.5 * PT) * s, "Notes", 17 * PT * s, c)
    sx = W - 76 * PT                                         # «поделиться»: открытая сверху коробка + стрелка вверх
    d.line([((sx - 4 * PT) * s, (cy - 4 * PT) * s), ((sx - 8 * PT) * s, (cy - 4 * PT) * s),
            ((sx - 8 * PT) * s, (cy + 11 * PT) * s), ((sx + 8 * PT) * s, (cy + 11 * PT) * s),
            ((sx + 8 * PT) * s, (cy - 4 * PT) * s), ((sx + 4 * PT) * s, (cy - 4 * PT) * s)], fill=c, width=lw,
           joint="curve")
    d.line([(sx * s, (cy + 4 * PT) * s), (sx * s, (cy - 12 * PT) * s)], fill=c, width=lw)
    d.line([((sx - 5 * PT) * s, (cy - 7 * PT) * s), (sx * s, (cy - 12 * PT) * s), ((sx + 5 * PT) * s, (cy - 7 * PT) * s)],
           fill=c, width=lw, joint="curve")
    ex, r = W - 32 * PT, 11 * PT                             # «⋯» в кружке
    d.ellipse(((ex - r) * s, (cy - r) * s, (ex + r) * s, (cy + r) * s), outline=c, width=lw)
    for k in (-1, 0, 1):
        dx = ex + k * 5 * PT
        d.ellipse(((dx - 1.5 * PT) * s, (cy - 1.5 * PT) * s, (dx + 1.5 * PT) * s, (cy + 1.5 * PT) * s), fill=c)


def notes_screen(title: str, body: list[str], date: str, clock: str, bat: float) -> tuple[Image.Image, tuple]:
    """Скрин заметки на iPhone (светлая тема, ширина W): статус-бар, шапка Notes, дата, заголовок, текст.
    → (картинка, рамка текста в её пикселях)."""
    s = 2
    tpx, bpx, dpx = 30 * PT, 19 * PT, 13 * PT                # чуть крупнее стандарта (Larger Text) — читается в карусели
    mx = 20 * PT
    tl = sf_wrap(title, tpx, 700, W - 2 * mx)
    bl = [ln for para in body for ln in (sf_wrap(para, bpx, 400, W - 2 * mx) if para else [""])]
    y_date = R.STATUS_H + 44 * PT + 4 * PT
    y_title = y_date + dpx + 16 * PT
    y_body = y_title + len(tl) * tpx * 1.2 + 6 * PT
    hgt = int(y_body + len(bl) * bpx * 1.32 + 18 * PT)
    img = Image.new("RGBA", (W * s, hgt * s), (255, 255, 255, 255))
    R.status_bar(img, s, R.Chat(title="", theme="light", clock=clock, battery=bat), R.THEMES["light"])
    notes_icons(img, s, R.STATUS_H + 22 * PT)
    dw = sf_w(date, dpx)
    sf_text(img, (W - dw) / 2 * s, y_date * s, date, dpx * s, (142, 142, 147))
    x1, y = 0.0, y_title
    for ln in tl:
        sf_text(img, mx * s, y * s, ln, tpx * s, (0, 0, 0), 700)
        x1 = max(x1, mx + sf_w(ln, tpx, 700))
        y += tpx * 1.2
    y = y_body
    for ln in bl:
        if ln:
            sf_text(img, mx * s, y * s, ln, bpx * s, (0, 0, 0))
            x1 = max(x1, mx + sf_w(ln, bpx))
        y += bpx * 1.32
    box = (int(mx), int(y_title), int(x1), int(y - bpx * 0.2))
    return img.resize((W, hgt), Image.Resampling.LANCZOS), box


def note_date(rng: random.Random) -> str:
    mon = rng.choice(["October", "November"])
    day = rng.randint(1, 28 if mon == "November" else 31)
    h, m = rng.randint(1, 11), rng.randint(0, 59)
    return f"{mon} {day}, 2026 at {h}:{m:02d} {rng.choice(['AM', 'PM', 'PM'])}"


def note_card(title: str, body: list[str], rng: random.Random, width: int = 790) -> tuple[Image.Image, tuple]:
    """Скрин заметки как карточка (скругление, без тени) шириной width → (карточка, рамка текста в карточке)."""
    im, box = notes_screen(title, body, note_date(rng), f"{rng.randint(7, 11)}:{rng.randint(10, 59)}",
                           rng.uniform(0.3, 0.9))
    k = width / W
    card = rounded_card(im.resize((width, round(im.height * k)), Image.Resampling.LANCZOS), 34)
    return card, tuple(int(v * k) for v in box)


def note_slide(bg: Image.Image, title: str, body: list[str], rng: random.Random, top: int = 70, dim: float = 0.85
               ) -> tuple[Image.Image, list]:
    bg = ImageEnhance.Brightness(bg.convert("RGB")).enhance(dim).convert("RGBA")
    card, tb = note_card(title, body, rng)
    x = (W - card.width) // 2
    bg.alpha_composite(card, (x, top))
    return bg.convert("RGB"), [(x + tb[0], top + tb[1], x + tb[2], top + tb[3])]


# ---------------------------------------------------------------- куски интерфейса Instagram (SF → Inter)
def heart(img, cx, cy, px, fill, filled=False):
    R.icon(img, 0xEB52 if filled else 0xEB51, cx, cy, px, fill)


def ig_bubble(img: Image.Image, cx: float, cy: float, r: float, fill, lw: int) -> None:
    """Иконка комментария Instagram: круг-пузырь с хвостиком слева снизу."""
    d = ImageDraw.Draw(img)
    d.arc((cx - r, cy - r, cx + r, cy + r), start=150, end=120, fill=fill, width=lw)
    d.line([(cx - r * 0.87, cy + r * 0.5), (cx - r * 1.02, cy + r * 1.02), (cx - r * 0.5, cy + r * 0.87)],
           fill=fill, width=lw, joint="curve")


def ig_post_stats(photo: Path, user: str, likes: int, caption: str, ago: str,
                  width: int = 600, photo_part: float = 0.48, photo_top: float = 0.17) -> Image.Image:
    """Скрин низа поста в ленте Instagram (светлая тема, iOS): нижняя часть фото, ряд кнопок со счётчиком лайков
    рядом с сердечком, подпись «ник текст… more», время. Рисуем в ширину W, потом уменьшаем."""
    s = 2
    w = W * s
    ph = int(W * 1.25 * photo_part)                          # фото 4:5, видна нижняя часть
    rows_h = int(44 * PT + 26 * PT + 24 * PT + 14 * PT)
    img = Image.new("RGBA", (w, (ph + rows_h) * s), (255, 255, 255, 255))
    full = fit(photo, (w, int(w * 1.25)), (0.5, 0.4))
    y0 = int(photo_top * full.height)
    img.paste(full.crop((0, y0, w, y0 + ph * s)).convert("RGB"), (0, 0))
    y = ph + 22 * PT
    ink, lw = (0, 0, 0), int(2.0 * PT * s)
    x = 14 * PT
    heart(img, (x + 12 * PT) * s, y * s, int(26 * PT * s), ink)
    sf_text(img, (x + 30 * PT) * s, (y - 10 * PT) * s, str(likes), 15 * PT * s, ink, 600)
    x += 30 * PT + sf_w(str(likes), 15 * PT, 600) + 16 * PT
    ig_bubble(img, (x + 11 * PT) * s, y * s, 10.5 * PT * s, ink, lw)
    x += 40 * PT
    R.icon(img, 0xE8EE, (x + 11 * PT) * s, y * s, int(24 * PT * s), ink)          # репост
    x += 40 * PT
    R.icon(img, 0xE724, (x + 11 * PT) * s, y * s, int(24 * PT * s), ink)          # отправить
    bx, by = W - 24 * PT, y                                                         # закладка
    ImageDraw.Draw(img).line([((bx - 8 * PT) * s, (by - 11 * PT) * s), ((bx + 8 * PT) * s, (by - 11 * PT) * s),
                              ((bx + 8 * PT) * s, (by + 11 * PT) * s), (bx * s, (by + 4 * PT) * s),
                              ((bx - 8 * PT) * s, (by + 11 * PT) * s), ((bx - 8 * PT) * s, (by - 11 * PT) * s)],
                             fill=ink, width=lw, joint="curve")
    y = ph + 44 * PT
    cpx = 14 * PT
    sf_text(img, 14 * PT * s, y * s, user, cpx * s, ink, 600)
    cx0 = 14 * PT + sf_w(user, cpx, 600) + 5 * PT
    room = W - cx0 - 14 * PT
    if sf_w(caption, cpx) > room:
        while caption and sf_w(caption + "… more", cpx) > room:
            caption = caption[:-1]
        caption = caption.rstrip() + "…"
        sf_text(img, cx0 * s, y * s, caption, cpx * s, ink)
        sf_text(img, (cx0 + sf_w(caption + " ", cpx)) * s, y * s, "more", cpx * s, (115, 115, 115))
    else:
        sf_text(img, cx0 * s, y * s, caption, cpx * s, ink)
    sf_text(img, 14 * PT * s, (y + 24 * PT) * s, ago, 12 * PT * s, (115, 115, 115))
    out = img.resize((W, img.height // s), Image.Resampling.LANCZOS)
    return rounded_card(out.resize((width, round(out.height * width / W)), Image.Resampling.LANCZOS), 30)


def ig_insights(photo: Path, likes: int, views: int, date: str, width: int = 740) -> Image.Image:
    """Скрин «Post insights» Instagram (светлая тема, iOS): шапка, миниатюра поста 4:5 целиком, дата,
    ряд иконок со счётчиками (♡ 3, остальное 0), блок Overview. Рисуем в ширину W, потом уменьшаем."""
    s = 2
    ink, grey, line = (0, 0, 0), (115, 115, 115), (219, 219, 219)
    th_h = 84 * PT
    th_w = th_h * 0.8
    y_thumb = 52 * PT
    y_date = y_thumb + th_h + 10 * PT
    y_icons = y_date + 34 * PT
    y_line = y_icons + 48 * PT
    y_over = y_line + 16 * PT
    rows = [("Views", str(views)), ("Interactions", str(likes)), ("Profile activity", "0")]
    hgt = int(y_over + 30 * PT + len(rows) * 36 * PT + 10 * PT)
    img = Image.new("RGBA", (W * s, hgt * s), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    lw = int(2.2 * PT * s)
    cy = 24 * PT
    d.line([((16 + 8) * PT * s, (cy - 10 * PT) * s), (16 * PT * s, cy * s), ((16 + 8) * PT * s, (cy + 10 * PT) * s)],
           fill=ink, width=lw, joint="curve")
    tt = "Post insights"
    sf_text(img, (W - sf_w(tt, 17 * PT, 600)) / 2 * s, (cy - 12 * PT) * s, tt, 17 * PT * s, ink, 600)
    tw, th = int(th_w * s), int(th_h * s)                    # миниатюра — пост целиком, без обрезки сторон
    thumb = fit(photo, (tw, th), (0.5, 0.4))
    m = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, tw - 1, th - 1), radius=int(6 * PT * s), fill=255)
    img.paste(thumb.convert("RGB"), (int((W - th_w) / 2 * s), int(y_thumb * s)), m)
    sf_text(img, (W - sf_w(date, 13 * PT)) / 2 * s, y_date * s, date, 13 * PT * s, grey)
    icons = ["heart", "bubble", 0xE8EE, 0xE724, "save"]
    vals = [likes, 0, 0, 0, 0]
    for k, (ic, v) in enumerate(zip(icons, vals)):
        cx = W * (k + 1) / (len(icons) + 1)
        iy = y_icons + 2 * PT
        if ic == "heart":
            heart(img, cx * s, iy * s, int(26 * PT * s), ink)
        elif ic == "bubble":
            ig_bubble(img, cx * s, iy * s, 10.5 * PT * s, ink, lw)
        elif ic == "save":
            d.line([((cx - 8 * PT) * s, (iy - 11 * PT) * s), ((cx + 8 * PT) * s, (iy - 11 * PT) * s),
                    ((cx + 8 * PT) * s, (iy + 11 * PT) * s), (cx * s, (iy + 4 * PT) * s),
                    ((cx - 8 * PT) * s, (iy + 11 * PT) * s), ((cx - 8 * PT) * s, (iy - 11 * PT) * s)],
                   fill=ink, width=lw, joint="curve")
        else:
            R.icon(img, ic, cx * s, iy * s, int(24 * PT * s), ink)
        vt = str(v)
        sf_text(img, (cx - sf_w(vt, 15 * PT, 600) / 2) * s, (iy + 16 * PT) * s, vt, 15 * PT * s, ink, 600)
    d.line([(0, y_line * s), (W * s, y_line * s)], fill=line, width=max(1, int(0.8 * PT * s)))
    sf_text(img, 16 * PT * s, y_over * s, "Overview", 17 * PT * s, ink, 700)
    y = y_over + 34 * PT
    for name, val in rows:
        sf_text(img, 16 * PT * s, y * s, name, 15 * PT * s, ink)
        sf_text(img, (W - 16 * PT - sf_w(val, 15 * PT, 600)) * s, y * s, val, 15 * PT * s, ink, 600)
        y += 36 * PT
    out = img.resize((W, hgt), Image.Resampling.LANCZOS)
    return rounded_card(out.resize((width, round(hgt * width / W)), Image.Resampling.LANCZOS), 30)


def comments_screen(post: Path, user: str, my_av: Path, rows: list, clock: str, bat: float,
                    status: bool = True) -> Image.Image:
    """Комментарии под постом (тёмная тема): сверху пост, снизу шторка «Comments» с репликами и ответами автора."""
    s = 2
    img = Image.new("RGBA", (W * s, H * s), (0, 0, 0, 255))
    img.alpha_composite(fit(post, (W * s, int(0.36 * H) * s), (0.5, 0.4)), (0, 0))
    if status:
        R.status_bar(img, s, R.Chat(title="", theme="dark", clock=clock, battery=bat), R.THEMES["dark"])
    top = int(0.27 * H) * s
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, top, W * s, H * s + 60 * s), radius=40 * s, fill=(30, 30, 30, 255))
    d.rounded_rectangle(((W / 2 - 50) * s, top + 18 * s, (W / 2 + 50) * s, top + 28 * s), radius=6 * s, fill=(90, 90, 90))
    tw = sf_w("Comments", 36, 700)
    sf_text(img, (W - tw) / 2 * s, top + 46 * s, "Comments", 36 * s, (245, 245, 245), wght=700)
    y = top + 130 * s
    for who, av, ago, text, likes, reply in rows:
        x = (150 if reply else 40) * s
        avd = (56 if reply else 76) * s
        img.alpha_composite(R.circle(av, avd), (x, y))
        tx = x + avd + 26 * s
        sf_text(img, tx, y - 2 * s, who, 30 * s, (245, 245, 245), wght=600)
        sf_text(img, tx + sf_w(who, 30, 600) * s + 16 * s, y - 2 * s, ago, 28 * s, (168, 168, 168))
        lines = sf_wrap(text, 34, 400, W - tx / s - 120)
        ty = y + 42 * s
        for ln in lines:
            sf_text(img, tx, ty, ln, 34 * s, (245, 245, 245))
            ty += 46 * s
        sf_text(img, tx, ty + 6 * s, "Reply", 27 * s, (168, 168, 168), wght=600)
        heart(img, (W - 56) * s, y + 40 * s, 32 * s, (168, 168, 168))
        if likes:
            lw = sf_w(str(likes), 24, 400)
            sf_text(img, (W - 56 - lw / 2) * s, y + 66 * s, str(likes), 24 * s, (168, 168, 168))
        y = ty + 64 * s
        if y > (H - 200) * s:
            break
    d = ImageDraw.Draw(img)
    d.rectangle((0, (H - 150) * s, W * s, H * s), fill=(30, 30, 30, 255))
    img.alpha_composite(R.circle(my_av, 70 * s), (36 * s, (H - 120) * s))
    d.rounded_rectangle((124 * s, (H - 124) * s, (W - 36) * s, (H - 46) * s), radius=40 * s, outline=(70, 70, 70), width=3 * s)
    sf_text(img, 160 * s, (H - 104) * s, f"Add a comment for {user}…", 30 * s, (140, 140, 140))
    return img.resize((W, H), Image.Resampling.LANCZOS).convert("RGB")


STICKER_FONT = ROOT / "fonts" / "cand1390" / "BarlowCondensed-Medium.ttf"   # ближе всего к шрифту стикеров Instagram
STICKER_BLUE = (49, 125, 218)


def link_sticker(text: str, px: int) -> Image.Image:
    """Белый стикер-ссылка Instagram: цепочка + домен капсом узким шрифтом, синим; мягкая тень."""
    from PIL import ImageFont
    f = ImageFont.truetype(str(STICKER_FONT), px)
    tw = f.getlength(text)
    ic = int(px * 0.78)
    padx, h = int(px * 0.42), int(px * 1.55)
    w = int(padx + ic + px * 0.22 + tw + padx)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=int(h * 0.24), fill=(255, 255, 255, 255))
    R.icon(im, 0xE71B, padx + ic / 2, h / 2, ic, STICKER_BLUE)
    d.text((padx + ic + px * 0.22, h / 2 + px * 0.04), text, font=f, fill=STICKER_BLUE, anchor="lm")
    return add_shadow(im, blur=10, opacity=0.18, offset=(0, 4), grow=1)


def story_screen(photo: Path, user: str, avatar: Path, link: str, viewers: list[Path], width: int,
                 tilt: float = -8.0) -> Image.Image:
    """Своя сториз в Instagram (как видит автор): стикер-ссылка по умолчанию (белый, синяя цепочка и домен),
    внизу слева «Activity» с аватарками зрителей, справа Highlight / Send / More."""
    s = 2
    w, h = 1080 * s, 1920 * s
    img = fit(photo, (w, h), (0.5, 0.4))
    shade = Image.new("L", (1, 256))
    shade.putdata([int(150 * max(0.0, 1 - y / 70)) if y < 70 else int(170 * max(0.0, (y - 190) / 66)) for y in range(256)])
    sh = Image.new("RGBA", img.size, (0, 0, 0, 255))
    sh.putalpha(shade.resize(img.size))
    img = Image.alpha_composite(img, sh)                      # затемнение сверху и снизу, как у сторис
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((20 * s, 26 * s, (1080 - 20) * s, 31 * s), radius=3 * s, fill=(255, 255, 255, 235))
    img.alpha_composite(R.circle(avatar, 70 * s), (28 * s, 52 * s))
    R.draw_text(img, 114 * s, 66 * s, user, 32 * s, (255, 255, 255), wght=600)
    R.draw_text(img, (114 + R.text_w(user, 32, 600) + 14) * s, 66 * s, "2h", 32 * s, (220, 220, 220))
    R.icon(img, 0xE712, (1080 - 110) * s, 87 * s, 36 * s, (255, 255, 255))
    R.icon(img, 0xE711, (1080 - 44) * s, 87 * s, 34 * s, (255, 255, 255))
    # стикер-ссылка (стиль по умолчанию): узкий высокий шрифт капсом, как Instagram Sans Condensed, синий; чуть наклонён
    st = link_sticker(link.split("/")[0].upper(), 56 * s)
    st = st.rotate(tilt, resample=Image.Resampling.BICUBIC, expand=True)
    img.alpha_composite(st, (int((w - st.width) / 2), int(1100 * s - st.height / 2)))
    # низ: «Activity» с аватарками зрителей; справа Highlight / Send / More
    for k, v in enumerate(viewers[:3]):
        c = R.circle(v, 56 * s)
        ring = Image.new("RGBA", (60 * s, 60 * s), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse((0, 0, 60 * s - 1, 60 * s - 1), fill=(20, 20, 20, 255))
        ring.alpha_composite(c, (2 * s, 2 * s))
        img.alpha_composite(ring, ((40 + k * 38) * s, 1752 * s))
    R.draw_text(img, 40 * s, 1824 * s, "Activity", 28 * s, (255, 255, 255), wght=600)
    for k, (cp, label) in enumerate(((0xEB51, "Highlight"), (0xE724, "Send"), (0xE712, "More"))):
        cx = 1080 - 300 + k * 118
        R.icon(img, cp, cx * s, 1786 * s, 44 * s, (255, 255, 255))
        lw = R.text_w(label, 24, 500)
        R.draw_text(img, (cx - lw / 2) * s, 1824 * s, label, 24 * s, (255, 255, 255), wght=500)
    out = img.resize((width, int(width * 16 / 9)), Image.Resampling.LANCZOS)
    return rounded_card(out, 34)


def rounded_card(im: Image.Image, r: int) -> Image.Image:
    m = Image.new("L", (im.width * 3, im.height * 3), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, m.width - 1, m.height - 1), radius=r * 3, fill=255)
    out = im.convert("RGBA")
    out.putalpha(m.resize(im.size, Image.Resampling.LANCZOS))
    return out                                   # без тени: полупрозрачная кайма вокруг скринов смотрелась странно


def chat_card(chat: R.Chat, width: int, top_gap: int = 40) -> Image.Image:
    """Скрин чата ровно по высоте переписки (шапка → реплики → строка ввода), уменьшенный и скруглённый."""
    R.render(chat, 4000)                                        # замер: где кончаются реплики
    content = R.render.bottom - (R.STATUS_H + R.HEADER_H)
    h = int(R.STATUS_H + R.HEADER_H + top_gap + content + 96 * R.PT)
    full = R.render(chat, h, full=True, anchor="bottom")
    return rounded_card(full.resize((width, round(h * width / W)), Image.Resampling.LANCZOS), 34)


def chat_screen_card(chat: R.Chat, width: int, height: int) -> Image.Image:
    """Полный экран чата (переписка прижата к строке ввода) в размер width×height — как скрин телефона."""
    full = R.render(chat, round(height * W / width), full=True, anchor="bottom")
    return rounded_card(full.resize((width, height), Image.Resampling.LANCZOS), 30)


def tilted(card: Image.Image, angle: float) -> Image.Image:
    ss = 2
    big = card.resize((card.width * ss, card.height * ss), Image.Resampling.LANCZOS)
    big = big.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    return big.resize((big.width // ss, big.height // ss), Image.Resampling.LANCZOS)


# ---------------------------------------------------------------- игры / Drops
def game_bg(src: Path, bright: bool = False) -> tuple[Image.Image, dict]:
    lay = D.s4_layout(src.name)
    im = Image.open(src).convert("RGB")
    ch = int(im.width * H / W)
    top = max(0, min(im.height - ch, int(lay.get("top", 0.0) * im.height)))
    bg = im.crop((0, top, im.width, top + ch)).resize((W, H), Image.Resampling.LANCZOS)
    if bright:
        bg = ImageEnhance.Color(ImageEnhance.Brightness(bg).enhance(1.12)).enhance(1.35)
    return bg.convert("RGBA"), lay


def game_slide(text: str, src: Path, bright: bool = False) -> tuple[Image.Image, list]:
    bg, lay = game_bg(src, bright)
    layer, box = cap_plate(text, lay["text_top"], lay["text_bottom"] + (0.06 if text.count(NL) > 1 else 0))
    return Image.alpha_composite(bg, layer).convert("RGB"), [box]


# ---------------------------------------------------------------- люди в чатах
HANDLES = ["mila.wav", "noahsings", "itsjunie", "theo.demos", "avamusic_", "kaimakesbeats", "rosie.mp3", "eli.sounds",
           "lunaonrepeat", "jaydenwrites", "sadie.songs", "nico.loops", "harper.hums", "ezra.records"]
H_GUY = ["noahsings", "theo.demos", "kaimakesbeats", "eli.sounds", "jaydenwrites", "nico.loops", "ezra.records"]
H_GIRL = ["mila.wav", "itsjunie", "avamusic_", "rosie.mp3", "lunaonrepeat", "sadie.songs", "harper.hums"]
GIRL = {"c1_s1": {"selfie_3"}, "c2_s1": {"phones_1", "phones_2", "phones_4", "phones_5"}}   # кто на фото — для ника


def artist(photo: Path, rng: random.Random) -> tuple[str, Image.Image]:
    """Ник по тому, кто на фото, и аватарка — её/его же лицо (квадрат вокруг головы на селфи)."""
    girl = photo.stem in GIRL.get(photo.parent.name, set())
    im = Image.open(photo).convert("RGB")
    sz = int(im.width * 0.34)
    cx, cy = im.width // 2, int(im.height * 0.30)
    return rng.choice(H_GIRL if girl else H_GUY), im.crop((cx - sz // 2, cy - sz // 2, cx + sz // 2, cy + sz // 2))
FRIEND_REPLIES_A = [["🔥", "sounds good bro"], ["🔥🔥", "sounds good bro"], ["🔥", "sounds good bro"]]
COMMENTS = [("this is so good 😭", 4), ("the chorus omg", 3), ("when is it on spotify??", 2), ("on repeat rn", 5),
            ("the production is crazy", 3), ("ok the bridge 🔥", 2), ("need the full version", 4),
            ("this deserves way more views", 6), ("how did you make this", 1), ("added to my playlist", 3)]
REPLIES = ["thank you!! 🤍", "omg thank youuu", "coming friday 🫶", "means a lot 🥹", "ty 🤍🤍", "soon!! 👀"]
FEEDBACK = [("me", "can you listen before i drop it? be honest pls"), ("them", "ok the hook is SO good", 0),
            ("them", "2nd verse feels a bit long tho", 0), ("them", "bridge gave me chills 😭", 1),
            ("them", "maybe turn the vocals up a little", 2), ("me", "ok noted, thank youuu 🤍")]


def friends(rng: random.Random, n: int = 5) -> tuple[list[str], list[Path]]:
    return rng.sample(D.NAMES, n), rng.sample(D.AVATARS, n)


# ---------------------------------------------------------------- сборка каруселей
LAY_SELFIE = {"head": (0.055, 0.215), "foot": (0.70, 0.775)}
LAY_STUDIO = {"head": (0.055, 0.25), "foot": (0.70, 0.775)}


def carousel_a(rng: random.Random, pick: dict) -> list:
    t = TEXTS["A"]
    out = [photo_two(pick["s1"], t[0], FOOT["A"], LAY_SELFIE)]
    # s2: два скрина одного размера (чат и сториз), целиком в кадре, рядом, с лёгким встречным наклоном
    p = D.plan_chat(rng)
    bg = fit(pick["s1"]).filter(ImageFilter.GaussianBlur(28))
    bg = Image.alpha_composite(bg, Image.new("RGBA", bg.size, (0, 0, 0, 120)))
    layer, box = cap(t[1], 0.06, 0.37)
    cw, chh = 420, 747                                       # 9:16
    chat = tilted(chat_screen_card(D.chat_s2(p, hist=1), cw, chh), rng.uniform(2.0, 3.5))
    user, av = artist(pick["s1"], rng)
    st = tilted(story_screen(pick["s1"], user, av, p["link"] or "soundcloud.com/x", rng.sample(D.AVATARS, 3), cw,
                             tilt=rng.uniform(-12, -4) if rng.random() < 0.8 else 0.0), -rng.uniform(2.0, 3.5))
    gap, top = 28, int(0.41 * H)
    x0 = (W - chat.width - st.width - gap) // 2
    bg.alpha_composite(chat, (x0, top))
    bg.alpha_composite(st, (x0 + chat.width + gap, top + 6))
    out.append((Image.alpha_composite(bg, layer).convert("RGB"), [box]))
    # s3: фото экрана компа / ноутбука с открытым drops.game, подпись — на стене над экраном
    bg = fit(pick["screen"], centering=(0.5, 0.5))
    layer, box = cap(t[2], 0.055, 0.27)
    out.append((Image.alpha_composite(bg, layer).convert("RGB"), [box]))
    # s4: игра (не заставка) + сообщение друга со счётом
    bg, lay = game_bg(pick["play"])
    layer, box = cap_plate(t[3], lay["text_top"], lay["text_bottom"])
    names, avs = friends(rng, 2)
    score = rng.choice(["8k", "12k", "9.4k", "15k", "6.7k", "11k"])
    msg = rng.choice([f"my score is {score}, send me the next one 😭", f"got {score} 😭 beat that",
                      f"{score} on your song lol, again??"])
    mini = R.Chat(title=names[0], subtitle="Active now", avatars=[avs[0]], theme="dark",
                  rows=[("them", msg, "", avs[0])], clock="9:41")
    card = chat_card(mini, 720)
    bg.alpha_composite(card, ((W - card.width) // 2, box[3] + 36))     # сразу под подписью — герой игры внизу виден
    out.append((Image.alpha_composite(bg, layer).convert("RGB"), [box]))
    return out


def carousel_b(rng: random.Random, pick: dict) -> list:
    t = TEXTS["B"]
    out = [photo_two(pick["s1"], t[0], FOOT["B"], LAY_SELFIE)]
    # s2: скрин заметки со списком + под ним скрин статистики поста (Post insights): ♡ 3, остальное 0
    bg = ImageEnhance.Brightness(fit(pick["s1"]).filter(ImageFilter.GaussianBlur(30)).convert("RGB")).enhance(0.8)
    bg = bg.convert("RGBA")
    card, tb = note_card(*NOTE_B, rng, width=740)
    x, top = (W - card.width) // 2, 50
    bg.alpha_composite(card, (x, top))
    stats = ig_insights(pick["s1"], 3, rng.randint(31, 64), note_date(rng).split(" at ")[0], width=740)
    stats = tilted(stats, rng.uniform(-2.0, -1.0))
    bg.alpha_composite(stats, ((W - stats.width) // 2 + 14, top + card.height + 14))
    out.append((bg.convert("RGB"), [(x + tb[0], top + tb[1], x + tb[2], top + tb[3])]))
    out.append(game_slide(t[2], pick["game"]))
    # s4: игра (не заставка) + скрин чата: ссылка на игру (превью — та же игра) и ответ друга
    bg, lay = game_bg(pick["play"])
    layer, box = cap_plate(t[3], lay["text_top"], lay["text_bottom"] + 0.06)
    names, avs = friends(rng, 2)
    g = pick["play"].name[:11]
    rows = [("time", D.fmt(rng.randint(1, 9), rng.randint(0, 59))),
            ("card", D.card_image(g, rng.random()), D.GAME_TITLE.get(g[:2], "A game on Drops"), "drops.game"),
            ("me", rng.choice(D.HER_DROP)),
            ("them", rng.choice(D.EXTRA_FRIEND), names[0], avs[0])]
    chat = R.Chat(title=rng.choice(D.GROUPS), subtitle="Active now", avatars=avs[:2], rows=rows, theme="dark",
                  clock=f"{rng.randint(7, 11)}:{rng.randint(10, 59)}", battery=rng.uniform(0.3, 0.9))
    card = chat_card(chat, 600)
    bg.alpha_composite(card, ((W - card.width) // 2, box[3] + 36))     # сразу под подписью — герой игры внизу виден
    out.append((Image.alpha_composite(bg, layer).convert("RGB"), [box]))
    return out


def chat_text_slide(text: str, make_chat) -> tuple[Image.Image, list]:
    """Как D.chat_slide, но с любым текстом: подпись в полосе между шапкой и первой репликой."""
    for hist in (1, 0):
        chat = make_chat(hist)
        bg = R.render(chat, H, full=True, anchor="bottom").convert("RGBA")
        top, first = int(R.render.header_bottom) + 16, int(R.render.marks["top"]) - 16
        if first - top < 60 or not C.fits(text, D.CAP_PX_MIN, first - top, X1 - X0):
            continue
        layer, box = cap(text, top / H, first / H)
        if any(b[3] > R.render.header_bottom and D.overlaps(box, b) for b in R.render.boxes):
            continue
        return Image.alpha_composite(bg, layer).convert("RGB"), [box]
    raise SystemExit("подпись не помещается над перепиской")


def carousel_c(rng: random.Random, pick: dict) -> list:
    t = TEXTS["C"]
    out = [photo_two(pick["s1"], t[0], FOOT["C"], LAY_STUDIO)]
    out.append(note_slide(fit(pick["s2"]), NOTE_C[2], [], rng, top=90, dim=0.9))
    # s3: тот же стиль заметки поверх игры Drops, кадр игры ярче остальных (хук «slide 3 is NEW»)
    gbg, _lay = game_bg(pick["play"], bright=True)
    out.append(note_slide(gbg, NOTE_C3[0], [NOTE_C3[1]], rng, top=70, dim=1.0))
    # s4: заметка на чате с друзьями (просил честный отзыв)
    names, avs = friends(rng, 3)
    rows = [("mark", "top"), ("time", f"{rng.choice(['Yesterday', 'Sun', 'Sat'])} {rng.randint(6, 11)}:{rng.randint(0, 59):02d} PM")]
    for r in FEEDBACK[1:]:                                   # первую просьбу закрывает заметка — не торчит из-под неё
        rows.append(r if r[0] == "me" else ("them", r[1], names[r[2]], avs[r[2]]))
    chat = R.Chat(title=rng.choice(D.GROUPS), subtitle="Active now", avatars=avs[:2], rows=rows, theme="dark",
                  clock=f"{rng.randint(7, 11)}:{rng.randint(10, 59)}", battery=rng.uniform(0.3, 0.9))
    hdr = R.STATUS_H + R.HEADER_H                            # фон — только переписка, без шапки и статус-бара чата
    cbg = R.render(chat, H + hdr, full=True, anchor="bottom").crop((0, hdr, W, H + hdr)).convert("RGBA")
    out.append(note_slide(cbg, NOTE_C[4], [], rng, top=60, dim=0.7))
    # s5: заметка на комментариях под постом
    names, avs = friends(rng, 5)
    me, my_av = rng.choice(HANDLES), rng.choice(D.AVATARS)
    cm = rng.sample(COMMENTS, 4)
    rows = []
    for k, ((txt, lk), nm, av) in enumerate(zip(cm, names, avs)):
        rows.append((nm + rng.choice(["", "_", ".x", "22"]), av, f"{rng.randint(2, 50)}m", txt, lk, False))
        if k < 2:
            rows.append((me, my_av, f"{rng.randint(1, 40)}m", rng.choice(REPLIES), 1, True))
    scr = comments_screen(pick["s1"], me, my_av, rows, f"{rng.randint(7, 11)}:{rng.randint(10, 59)}",
                          rng.uniform(0.3, 0.9), status=False)
    out.append(note_slide(scr.convert("RGBA"), NOTE_C[5], [], rng, top=330, dim=0.7))
    return out


def pool(d: Path) -> list[Path]:
    return sorted(f for f in d.glob("*") if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
                  and not f.name.startswith("_")) if d.is_dir() else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["A", "B", "C"], required=True)
    ap.add_argument("-n", type=int, default=4)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>.jpg")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--qa", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    rng = random.Random(a.seed * 31 + ord(a.set))
    s1 = pool(SL / {"A": "c1_s1", "B": "c2_s1", "C": "c3_s1"}[a.set])
    games = GAMES_OK
    build = {"A": carousel_a, "B": carousel_b, "C": carousel_c}[a.set]
    a.out.mkdir(parents=True, exist_ok=True)
    manifest, qa = [], []
    for i in range(1, a.n + 1):
        k1 = (i - 1) % len(s1)
        pick = {"s1": s1[k1], "s2": SL / "c3_s2" / s1[k1].name, "game": games[(i * 7 + k1) % len(games)],
                "screen": SCREENS[i % len(SCREENS)],
                "play": GAMES_PLAY[(i * 5 + k1) % len(GAMES_PLAY)]}
        if pick["play"].name[:2] == pick["game"].name[:2]:            # на 3 и 4 слайдах — разные игры
            pick["play"] = next(g for g in GAMES_PLAY[(i * 5 + k1) % len(GAMES_PLAY):] + GAMES_PLAY
                                if g.name[:2] != pick["game"].name[:2])
        slides = build(rng, pick)
        d = a.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, (im, boxes) in enumerate(slides, 1):
            for b in boxes:
                if bad := check_box(W, H, b):
                    raise SystemExit(f"{i:03d} слайд {k}: текст вне безопасной зоны {b} — {bad}")
            im.save(d / f"{k}.jpg", quality=93)
            if a.qa and i <= 4:
                q = draw_overlay(im)
                for b in boxes:
                    ImageDraw.Draw(q).rectangle(b, outline=(255, 220, 0), width=5)
                qa.append(q)
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d / f"{k}.jpg", a.flat / f"sort_{k}_{i}.jpg")
        manifest.append({"carousel": d.name, **{k: v.name for k, v in pick.items()}})
        print(f"  {d.name}", flush=True)
    if qa:
        n = len(slides)
        tw, th = 300, 400
        sheet = Image.new("RGB", (n * tw, (len(qa) // n) * th), (30, 30, 30))
        for j, q in enumerate(qa):
            sheet.paste(q.resize((tw, th)), ((j % n) * tw, (j // n) * th))
        sheet.save(a.out / "_qa.jpg", quality=86)
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    sys.argv = ["strip", str(a.out)] + ([str(a.flat)] if a.flat else [])
    strip_jpeg_meta.main()
    print(f"готово: {a.n} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
