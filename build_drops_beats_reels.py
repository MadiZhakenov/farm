#!/usr/bin/env python3
"""
Drops beats (айди нет): 9:16 ролики ~11 с, 5 концептов ТЗ × 30 (lofi / trap / sad / funk / napkin).
Анимации и звуки — копия рефов (downloads/drops_beats/refs, разбор → refs/_events.json):
  0 с     сверху плашка ТЗ, под ней сразу стоит строка коммента (ник + текст), без въезда; голос читает коммент
          (ElevenLabs, с 0,5 с, обычная скорость);
  F       один белый кадр и затухание за 0,17 с — коммент уже раскрыт до вложения (скрин секвенсора с битом ТЗ,
          у napkin — фото салфетки); звук вспышки из рефа;
  F+1,0   красный круг, стрелка и мем появляются разом, в один кадр; мемный звук из рефа;
  F+2,5   жёсткая склейка → реакция девушки (окна REACT, мимика под фразу; её фразу читает голос, J-cut) → жёсткая склейка → загрузка в Drops
          (статичный кадр, клик из рефа, дальше тишина) → кадр уезжает вверх, снизу геймплей — бит вступает только
          здесь, кадр пульсирует на его долях → CTA.
Звуки рефов — downloads/drops_beats/sfx_ref/{flash,meme,upload} (вырезаны по событиям, повторы убраны).
Тексты ТЗ дословно, ники меняем (ТЗ разрешает). Текст в безопасной зоне 9:16, nvenc cq 27, без метаданных.
Доли треков — beat_map_drops_beats.py → music/_beats.json.

  python build_drops_beats_reels.py --concept all -n 2 --out output/drops_beats_test8 --qa
  python build_drops_beats_reels.py --concept lofi -n 150 --out output/drops_beats_750/lofi   # и так по каждому
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1307_carousels as P  # noqa: E402  (шрифт и шаг строки TikTok-плашек)
import render_igdm as R  # noqa: E402  (Apple-эмодзи, разбор текста на текст/эмодзи)
from core.safe_zones import check_box, draw_overlay  # noqa: E402

W, H, FPS = 1080, 1920, 30
D = ROOT / "downloads" / "drops_beats"
FACES = ROOT / "downloads" / "drops_react" / "faces"
VOICE = D / "voice"
SFX_REF = D / "sfx_ref"
INTER = ROOT / "fonts" / "inter"
SYM = Path("C:/Windows/Fonts/seguisym.ttf")
GAME_BOX = (60, 92, 1380, 1062)            # игровое поле в скринкасте 1920×1080 (без шапки сайта и панели справа)
UP_T0 = 0.55                               # 00_Upload_Loading: пустое поле → файл тащат (1,0 с) → бросили (1,6 с)
UP_X0 = 140                                # как в рефах: статичный кроп 9:16 левой части (DROPS → UPLOAD A SONG)
RED = (232, 30, 30)
CX0, CW, CY0 = 30, 1020, 372               # карточка как в рефе: почти во всю ширину, углы прямые
TXT_X, TXT_R = 170, 900                    # текст карточки от x 200 до 930 (в безопасной зоне 140–940)
PLATE_Y = {"card": 262, "face": 1478, "upload": 256, "game": 330}     # face — ниже подбородка и жестов
VO_AT, VO_GAIN = 0.5, -6                   # голос как в рефах: с 0,5 с, тише мемного звука
REV_GAP, TARGET_TOTAL, CTA_MIN, HOOK_GAIN = 0.12, None, 1.2, 0   # build_drops_lofi9 меняет: вспышка раньше, ровная длина ролика
MEME_AFTER, CARD_AFTER, UPLOAD_LEN, FACE_MIN, INTRO_GAIN = 1.0, 2.5, 1.37, 1.4, -2   # длины сцен (lofi9 — короче, ради геймплея)
FACE_VO_GAIN, FACE_TAIL, JCUT_MAX = -4, 0.15, 0.25
# реакция девушки озвучена её фразой: длинная фраза начинается чуть раньше склейки (J-cut, до 0,25 с), кадр с лицом —
# не короче 1,4 с и до конца фразы + 0,15 с
SLIDE = 0.2                                # загрузка уезжает вверх, снизу геймплей
# окна реакций (клип, начало, сколько секунд мимика держится): отсмотрены покадрово, выражение совпадает с фразой,
# без смаза, без «говорит» и без руки, влетающей в кадр
REACT = {
    "lets_see": [("IMG_5737", 0.45, 1.8), ("IMG_5737", 1.3, 1.8), ("IMG_5721", 1.4, 1.5), ("IMG_5733", 0.0, 2.0),
                 ("IMG_5725", 0.0, 1.5), ("IMG_5732", 3.4, 1.5)],     # скепсис/задумалась: палец у подбородка, прищур
    "curious": [("IMG_5721", 3.0, 2.0), ("IMG_5737", 4.15, 1.25), ("IMG_5729", 4.0, 2.0), ("IMG_5726", 5.95, 1.2),
                ("IMG_5732", 3.25, 1.65)],
    "watch_me": [("IMG_5722", 1.0, 1.4), ("IMG_5728", 0.6, 1.4), ("IMG_5734", 1.4, 1.4)],   # ухмылка, кулак
    "not_ready": [("IMG_5723", 0.3, 1.4), ("IMG_5723", 1.6, 1.4), ("IMG_5722", 3.3, 1.4), ("IMG_5729", 0.5, 1.4),
                  ("IMG_5721", 0.5, 1.4), ("IMG_5733", 5.4, 1.4), ("IMG_5732", 0.0, 1.4)],   # рука на лбу / у рта
    "lets_go": [("IMG_5728", 1.0, 1.4), ("IMG_5728", 1.6, 1.4), ("IMG_5724", 0.2, 1.4), ("IMG_5729", 4.9, 1.4)],
}
# салфетка: только она и рука (без стакана пива и полок бара); область рисунка — для круга
NAPKIN = (D / "napkin" / "napkin_01.jpg", (140, 300, 655, 790), (94, 138, 478, 327))

CONCEPTS = {
    "lofi": dict(
        nicks=["sleepy.keys", "rainy.loops", "lofi.lena", "keys.at.3am", "mellow.mike", "slow.jules"],
        comment="try this one 🙏", avatar="🎧", vo="adam_lofi.wav", vo_face="face_lofi.wav",
        grid=[("kick", "●○○○●○○○●○○○●○○○"), ("snare", "○○○○●○○○○○○○●○○○"), ("hat", "●○●○●○●○●○●○●○●○"),
              ("chords", ["Am", "F", "C", "G"])],
        texts=["someone sent me this beat 👀", "okay, let’s see", "uploading it to Drops", "this one is so calm 🎧",
               "send me your next beat 👇"],
        music=["Minimal Beat 2.mp3", "Minimal Beat 4.mp3"],
        games=["SP6_Some_Threads_Stay_With_Me", "SP1_Where_The_Good_Times_Go", "SP4_Take_It_Easy_Darling"],
        react="lets_see", memes=("chill", [10, 23, 27, 41, 29]),
    ),
    "trap": dict(
        nicks=["808.mari", "trap.ivy", "drill.kade", "hihat.hunter", "808.nova", "bounce.reese"],
        comment="bet you can’t play this", avatar="🔊", vo="adam_trap.wav", vo_face="face_trap.wav",
        grid=[("kick", "●○○●○○●○○○●○○○○○"), ("snare", "○○○○●○○○○○○○●○○○"), ("hat", "●●●●●○●●●●●○●●●●"),
              ("bass", "🔊🔊○○🔊○○○")],
        texts=["okay, challenge accepted 😤", "watch me", "loading it into Drops", "this beat is NOT easy 😅",
               "who’s sending the next one?"],
        music=["Brooklyn drill (beat).mp3", "Energia Bruta.mp3"],
        games=["MP5_Your_Coat_On_The_Chair", "MP2_Get_Out_Of_My_Head", "SP7_Were_Not_Going_Home",
               "SP2_When_I_Say_Go"],
        react="watch_me", memes=("challenge", [1, 16, 32, 22]),
    ),
    "sad": dict(
        nicks=["late.night.chords", "sad.keys.only", "rainy.piano", "quiet.minor", "2am.chords", "soft.ivory"],
        comment="make something sad out of this", avatar="🌙", vo="adam_sad.wav", vo_face="face_sad.wav",
        grid=[("chords", ["Dm", "Bb", "F", "C"]), ("melody", "♪♪♫○♪♫♫"), ("kick", "●○○○○○●○●○○○○○○○")],
        texts=["this beat is already\nmaking me emotional 🥹", "not ready for this", "playing it in Drops",
               "i didn’t expect it to hit this hard", "send me more like this 😭"],
        music=["Minimal Beat 1.mp3", "Minimal Beat 3.mp3", "Minimal Beat 5.mp3"],
        games=["SP6_Some_Threads_Stay_With_Me", "SP4_Take_It_Easy_Darling", "SP1_Where_The_Good_Times_Go"],
        react="not_ready", memes=("crying", [5, 6, 8, 17]),
    ),
    "funk": dict(
        nicks=["funky.dan", "slap.bass.sam", "groove.theo", "funk.lola", "wah.wah.will", "disco.dre"],
        comment="can the game keep up with this?", avatar="🎸", vo="adam_funk.wav", vo_face="face_funk.wav",
        grid=[("kick", "●○○○●○●○○○●○○○○○"), ("snare", "○○○○●○○○○○○○●○○●"), ("hat", "○●○●○●○●○●○●○●○●"),
              ("bass", "🎸○🎸○○🎸○○")],
        texts=["this one looks hard 😅", "let’s go", "uploading to Drops", "okay it kept up 😳", "now you try 👇"],
        music=["Bouncy Drop.mp3", "Perreo de Verano.mp3"],
        games=["SP5_Stay_Till_The_Morning", "MP1_Get_Back", "SP4_Take_It_Easy_Darling"],
        react="lets_go", memes=("sweating", [25, 39, 10, 33]),
    ),
    "napkin": dict(
        nicks=["paper.beats", "napkin.notes", "doodle.drums", "pen.and.beat", "scribble.loops", "diner.beats"],
        comment="drew this on a napkin", avatar="✏️", vo="adam_napkin.wav", vo_face="face_napkin.wav", photo=NAPKIN,
        texts=["a napkin beat?? 👀", "okay, i’m curious", "putting it in Drops", "it actually works 😭",
               "send me your napkin beats"],
        music=["Omnipresent Glitch (beat).mp3", "Minimal Beat 1.mp3"],
        games=["SP3_The_Little_Game", "SP1_Where_The_Good_Times_Go", "SP5_Stay_Till_The_Morning"],
        react="curious", memes=("shocked", [5, 11, 20, 40]),
    ),
}


# ---------------------------------------------------------------- шрифты и текст с эмодзи
def fnt(weight: str, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(INTER / f"Inter-{weight}.ttf"), px)


def text_w(text: str, f: ImageFont.FreeTypeFont, px: int) -> float:
    return sum(px * 1.2 if k == "emoji" else f.getlength(c) for k, c in R.A._tokenize_runs(text))


def mixed(img: Image.Image, x: float, base: float, text: str, f: ImageFont.FreeTypeFont, px: int, fill) -> float:
    d = ImageDraw.Draw(img)
    for kind, ch in R.A._tokenize_runs(text):
        if kind == "emoji":
            e = R.emoji(ch, int(px * 1.1))
            if e is not None:
                img.alpha_composite(e, (int(x + px * 0.05), int(base - px * 0.95)))
            x += px * 1.2
        else:
            d.text((x, base), ch, font=f, fill=fill, anchor="ls")
            x += f.getlength(ch)
    return x


def plate(text: str, px: int = 56) -> tuple[Image.Image, int]:
    """Белая TikTok-плашка (строки через \\n — слитые плашки), чёрный текст; эмодзи — размером с текст и по центру
    строки (в общей plate_block он ×1,18 и сидит на базовой линии — вылезал за плашку). Кегль уменьшается, пока
    самая длинная строка не влезет в 780 px безопасной ширины."""
    A = P.C.B.A
    toks_l = [list(A._tokenize_runs(A.sanitize_overlay_text(P.C.B.R._normalize_text(ln)))) for ln in text.split("\n")]
    for q in range(px, 36, -2):
        font, ep = P.C.B.R._load_font(q), int(q * 0.94)
        ws = [sum(ep + q * 0.06 if k == "emoji" else font.getlength(c) for k, c in toks) for toks in toks_l]
        if max(ws) <= 780:
            break
    pad, h, r = int(0.42 * q), P.C.B.R.line_advance_for(q), int(0.26 * q)     # геометрия как у plate_block
    ascent, descent = font.getmetrics()
    pw = int(max(ws)) + 2 * pad
    img = Image.new("RGBA", (pw, h * len(ws)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for k, w in enumerate(ws):
        x0 = (pw - w - 2 * pad) / 2
        y1 = (k + 1) * h - 1 + (r if k < len(ws) - 1 else 0)       # перекрытие — строки сливаются
        d.rounded_rectangle((x0, k * h, x0 + w + 2 * pad - 1, y1), radius=r, fill=(255, 255, 255, 255))
    for k, (toks, w) in enumerate(zip(toks_l, ws)):
        x, base = (pw - w) / 2, k * h + (h - ascent - descent) / 2 + ascent
        for kind, c in toks:
            if kind == "emoji":
                e = A._apple_emoji_rgba(c, ep)
                if e is not None:
                    img.alpha_composite(e, (int(x + q * 0.03), int(base - q * 0.36 - ep / 2)))
                x += ep + q * 0.06
            else:
                d.text((x, base), c, font=font, fill=(0, 0, 0, 255), anchor="ls")
                x += font.getlength(c)
    return img, q


def plate_box(pl: Image.Image, x: int, y: int, px: int = 56) -> tuple:
    pad = int(0.42 * px)                                     # поля плашки — не текст
    return x + pad, y + pad // 2, x + pl.width - pad, y + pl.height - pad // 2


# ---------------------------------------------------------------- коммент: текст + вложение (скрин бита / фото)
SEQ_BG, SEQ_BAR, SEQ_LAB = (34, 37, 43), (25, 27, 32), (62, 68, 79)
PAD_OFF = ((70, 76, 88), (88, 72, 78))          # неактивные шаги: четверти чередуются по цвету, как в секвенсорах
PAD_ON = (236, 236, 240)
CHORD_C = (96, 150, 255)


def seq_shot(cfg: dict, bpm: int, width: int) -> tuple[Image.Image, list, tuple, list]:
    """Скриншот степ-секвенсора, приложенный к комменту фото: ряды ТЗ, горящие шаги — удары, аккорды — блоки.
    Возвращает картинку, (y0, y1) рядов, (x0, x1) шагов и «пустые» полосы под стрелку — в её координатах."""
    s, pad, top, lab_w, row_h, gap = 2, 14, 44, 128, 58, 8
    rows = cfg["grid"]
    hh = top + len(rows) * row_h + pad - 4
    img = Image.new("RGBA", (width * s, hh * s), SEQ_BG + (255,))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, width * s, (top - 10) * s), fill=SEQ_BAR + (255,))
    f_top, f_lab, f_ch = fnt("Medium", 18 * s), fnt("SemiBold", 22 * s), fnt("Bold", 21 * s)
    d.text((pad * s, (top - 10) * s / 2), "Pattern 1", font=f_top, fill=(170, 176, 188), anchor="lm")
    d.text(((width - pad) * s, (top - 10) * s / 2), f"{bpm} BPM", font=f_top, fill=(170, 176, 188), anchor="rm")
    sx0, sx1 = pad + lab_w + 10, width - pad
    pitch = (sx1 - sx0 - 3 * gap) / 16

    def step_x(i: int) -> float:
        return sx0 + i * pitch + (i // 4) * gap
    rows_y = []
    for r, (label, row) in enumerate(rows):
        y0, y1 = top + r * row_h + 5, top + (r + 1) * row_h - 5
        rows_y.append((y0, y1))
        d.rounded_rectangle((pad * s, y0 * s, (pad + lab_w) * s, y1 * s), radius=6 * s, fill=SEQ_LAB + (255,))
        d.text(((pad + 12) * s, (y0 + y1) / 2 * s), label, font=f_lab, fill=(228, 231, 238), anchor="lm")
        if isinstance(row, list) and all(t[:1].isalpha() for t in row):          # аккорды: блок на четверть такта
            for i, ch in enumerate(row):
                x0, x1 = step_x(4 * i), step_x(4 * i + 3) + pitch - 3
                d.rounded_rectangle((x0 * s, y0 * s, x1 * s, y1 * s), radius=5 * s, fill=CHORD_C + (255,))
                d.text(((x0 + 9) * s, (y0 + y1) / 2 * s), ch, font=f_ch, fill=(255, 255, 255), anchor="lm")
            continue
        toks = list(row) if isinstance(row, str) else row
        hits = {round(i * 16 / len(toks)) for i, t in enumerate(toks) if t not in "○"}
        for i in range(16):
            x0 = step_x(i)
            d.rounded_rectangle((x0 * s, y0 * s, (x0 + pitch - 4) * s, y1 * s), radius=4 * s,
                                fill=(PAD_ON if i in hits else PAD_OFF[(i // 4) % 2]) + (255,))
    img = img.resize((width, hh), Image.Resampling.LANCZOS)
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, width - 1, hh - 1), radius=18, fill=255)
    img.putalpha(m)
    lanes = [(step_x(4 * i) + 52, step_x(4 * i + 3) + pitch - 10) for i in range(4)]   # пустая часть блока
    return img, rows_y, (sx0, sx1), lanes


def photo_shot(spec: tuple, width: int) -> tuple[Image.Image, list, tuple, list]:
    """Фото, приложенное к комменту (салфетка): кроп без лишнего, скругление как у вложений; круг — вокруг рисунка."""
    path, crop, (ax0, ay0, ax1, ay1) = spec
    im = Image.open(path).convert("RGB").crop(crop)
    k = width / im.width
    im = im.resize((width, round(im.height * k)), Image.Resampling.LANCZOS).convert("RGBA")
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=18, fill=255)
    im.putalpha(m)
    x0, x1 = ax0 * k, ax1 * k
    return im, [(ay0 * k, ay1 * k)], (x0, x1), [(x0 + (x1 - x0) * 0.3, x0 + (x1 - x0) * 0.7)]


class Card:
    """Коммент как в рефе (светлая тема, прямые углы): аватар, ник · время, текст, вложение, Reply и лайки."""
    PAD, AV = 46, 96

    def __init__(self, cfg: dict, nick: str, ago: str, likes: str, bpm: int, rng: random.Random):
        pad, tx = self.PAD, TXT_X
        if cfg.get("photo"):
            shot, rows_y, (sx0, sx1), lanes = photo_shot(cfg["photo"], 560)
        else:
            shot, rows_y, (sx0, sx1), lanes = seq_shot(cfg, bpm, TXT_R - tx)
        iy = 168
        fy = iy + shot.height + 56
        self.ch = fy + 52
        self.strip_h = iy - 8                                       # строка коммента до раскрытия вложения
        img = Image.new("RGBA", (CW, self.ch), (255, 255, 255, 255))
        d = ImageDraw.Draw(img)
        av = rng.choice([(255, 170, 190), (186, 220, 255), (200, 236, 200), (255, 222, 170), (220, 200, 255)])
        d.ellipse((pad, 40, pad + self.AV, 40 + self.AV), fill=av)
        e = R.emoji(cfg["avatar"], 58)
        if e is not None:
            img.alpha_composite(e, (pad + 19, 59))
        f_nick, f_ago, f_com = fnt("SemiBold", 31), fnt("Regular", 31), fnt("Regular", 44)
        d.text((tx, 76), nick, font=f_nick, fill=(110, 110, 110), anchor="ls")
        d.text((tx + f_nick.getlength(nick) + 10, 76), f"· {ago}", font=f_ago, fill=(165, 165, 165), anchor="ls")
        mixed(img, tx, 132, cfg["comment"], f_com, 44, (20, 20, 20))
        img.alpha_composite(shot, (tx, iy))
        f_ft = fnt("Medium", 31)
        d.text((tx, fy), "Reply", font=f_ft, fill=(150, 150, 150), anchor="lm")
        lw = f_ft.getlength(likes)
        d.text((TXT_R - lw, fy), likes, font=f_ft, fill=(150, 150, 150), anchor="lm")
        d.text((TXT_R - lw - 12, fy + 2), "♡", font=ImageFont.truetype(str(SYM), 34), fill=(150, 150, 150),
               anchor="rm")
        self.text_boxes = [(tx, 40, tx + max(f_nick.getlength(nick) + 140, text_w(cfg["comment"], f_com, 44)), 146),
                           (tx, iy, tx + shot.width, iy + shot.height), (tx, fy - 20, TXT_R, fy + 20)]
        self.rows_y = [(iy + a, iy + b) for a, b in rows_y]
        self.sx0, self.sx1 = tx + sx0, tx + sx1
        self.lanes = [(tx + a, tx + b) for a, b in lanes]      # где стрелка не закроет подпись аккорда
        self.base = img


# ---------------------------------------------------------------- круг от руки, стрелка, мем
def hand_circle(cx: float, cy: float, rx: float, ry: float, rng: random.Random) -> list[tuple[float, float]]:
    a0 = math.radians(rng.uniform(-130, -70))
    ph1, ph2 = rng.uniform(0, 6.28), rng.uniform(0, 6.28)
    pts = []
    n = 90
    for k in range(n + 1):
        u = k / n
        a = a0 + u * 2 * math.pi * 1.1
        g = 1 + 0.035 * math.sin(2 * a + ph1) + 0.018 * math.sin(5 * a + ph2) + 0.06 * u
        pts.append((cx + rx * g * math.cos(a), cy + ry * g * math.sin(a)))
    return pts


def hand_arrow(p0: tuple, p1: tuple, rng: random.Random) -> list[tuple[float, float]]:
    """Стрелка выходит из круга почти вертикально (мимо подписей аккордов) и плавно уходит к мему."""
    mx, my = p0[0] + rng.uniform(-12, 12), p0[1] + (p1[1] - p0[1]) * 0.62
    pts = []
    for k in range(41):
        u = k / 40
        pts.append(((1 - u) ** 2 * p0[0] + 2 * (1 - u) * u * mx + u * u * p1[0],
                    (1 - u) ** 2 * p0[1] + 2 * (1 - u) * u * my + u * u * p1[1]))
    return pts


def draw_stroke(layer: Image.Image, pts: list, width: int, ss: int) -> None:
    ImageDraw.Draw(layer).line([(x * ss, y * ss) for x, y in pts], fill=RED + (255,), width=width * ss, joint="curve")
    for x, y in (pts[0], pts[-1]):                          # круглые концы линии
        r = width * ss / 2
        ImageDraw.Draw(layer).ellipse((x * ss - r, y * ss - r, x * ss + r, y * ss + r), fill=RED + (255,))


def arrow_head(pts: list) -> list[list[tuple]]:
    (x0, y0), (x1, y1) = pts[-4], pts[-1]
    a = math.atan2(y1 - y0, x1 - x0)
    return [[(x1 + 40 * math.cos(a + s * 2.6), y1 + 40 * math.sin(a + s * 2.6)), (x1, y1)] for s in (-1, 1)]


def meme_tile(path: Path, side: int) -> Image.Image:
    im = ImageOps.contain(Image.open(path).convert("RGB"), (side, side), Image.Resampling.LANCZOS)
    b = 9
    out = Image.new("RGBA", (im.width + 2 * b, im.height + 2 * b), (255, 255, 255, 255))
    out.paste(im, (b, b))
    return out


def render_card_scene(cfg: dict, v: dict, bpm: int, tm: dict, dest: Path, rng: random.Random) -> list:
    """Кадры 0..tm["end"], как в рефах — без анимаций, на жёстких сменах: строка коммента → (tm["rev"]) белый кадр
    и затухание, коммент уже целиком с вложением → (tm["meme"]) круг, стрелка и мем разом."""
    card = Card(cfg, v["nick"], v["ago"], v["likes"], bpm, rng)
    base = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    pl, q = plate(cfg["texts"][0])
    px_, py_ = (W - pl.width) // 2, PLATE_Y["card"] - pl.height // 2
    base.alpha_composite(pl, (px_, py_))
    boxes = [plate_box(pl, px_, py_, q)] + [(CX0 + a, CY0 + b, CX0 + c, CY0 + e) for a, b, c, e in card.text_boxes]
    strip = base.copy()
    strip.alpha_composite(card.base.crop((0, 0, CW, card.strip_h)), (CX0, CY0))
    full = base.copy()
    full.alpha_composite(card.base, (CX0, CY0))
    # круг вокруг ряда (у салфетки — вокруг рисунка), стрелка к мему
    ry0, ry1 = card.rows_y[v["circle_row"]]
    ccx, ccy = CX0 + (card.sx0 + card.sx1) / 2 + 6, CY0 + (ry0 + ry1) / 2
    circ = hand_circle(ccx, ccy, (card.sx1 - card.sx0) / 2 + 22, (ry1 - ry0) / 2 + 16, rng)
    meme = meme_tile(v["meme"], 420 if cfg.get("photo") else 520)
    la, lb = card.lanes[v["arrow_lane"] % len(card.lanes)]
    xs = CX0 + la + (lb - la) * rng.uniform(0.25, 0.75)
    mcx = int(min(max(xs + v["meme_dx"], 320), 760))
    mtop = CY0 + card.ch + 80
    start = (xs, ccy + (ry1 - ry0) / 2 + 18)
    arr = hand_arrow(start, (mcx + rng.uniform(-30, 30), mtop - 14), rng)
    ss = 2
    lay = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    for pts in [circ, arr] + arrow_head(arr):
        draw_stroke(lay, pts, 13, ss)
    final = full.copy()
    m = meme.rotate(v["meme_rot"], Image.Resampling.BICUBIC, expand=True)
    final.alpha_composite(m, (int(mcx - m.width / 2), int(mtop + meme.height / 2 - m.height / 2)))
    final.alpha_composite(lay.resize((W, H), Image.Resampling.LANCZOS))
    white = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    raw = {k: im.convert("RGB").tobytes() for k, im in (("strip", strip), ("full", full), ("final", final))}
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "15",
                             "-pix_fmt", "yuv420p", str(dest)], stdin=subprocess.PIPE)
    for k in range(round(tm["end"] * FPS)):
        t = k / FPS
        if t < tm["rev"]:
            proc.stdin.write(raw["strip"])
            continue
        fl = (t - tm["rev"]) / 0.17                                 # белый кадр и затухание, как в рефах
        key = "final" if t >= tm["meme"] else "full"
        if fl < 1:
            img = full if key == "full" else final
            proc.stdin.write(Image.blend(img, white, 1.0 if k == math.ceil(tm["rev"] * FPS) else 0.85 * (1 - fl))
                             .convert("RGB").tobytes())
        else:
            proc.stdin.write(raw[key])
    proc.stdin.close()
    if proc.wait():
        raise SystemExit("ffmpeg (карточка) упал")
    return boxes


# ---------------------------------------------------------------- сборка ролика
def dur(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)


_BEATS: dict = {}


def _beats(track: str) -> tuple[list[float], float]:
    """Доли трека; медленные (> 0,75 с, напр. дрилл 72 BPM) делим пополам — иначе пульс раз в 0,8 с."""
    if not _BEATS:
        _BEATS.update(json.loads((D / "music" / "_beats.json").read_text(encoding="utf-8")))
    bt = _BEATS[track]["beats"]
    tb = sorted(y - x for x, y in zip(bt, bt[1:]))[len(bt) // 2]
    if tb > 0.75:
        bt = [q for x, y in zip(bt, bt[1:]) for q in (x, (x + y) / 2)] + bt[-1:]
        tb /= 2
    return bt, tb


def face_len(cfg: dict) -> tuple[float, float]:
    """(насколько раньше склейки начинается фраза реакции, длина кадра с лицом)."""
    d = dur(VOICE / cfg["vo_face"])
    jcut = round(min(JCUT_MAX, max(0.0, d + FACE_TAIL - FACE_MIN)), 3)
    return jcut, round(max(FACE_MIN, d - jcut + FACE_TAIL), 3)


def audio_graph(tm: dict, v: dict, vo: Path, track: Path, m0: float, total: float, base: int) -> tuple[list, list, str]:
    """Звук как в рефах: голос, звук вспышки, мемный звук, клик загрузки (всё из рефов), потом тишина и бит — только
    с геймплея. base — номер первого аудиовхода ffmpeg."""
    parts = [(vo, tm["vo"], VO_GAIN), (v["fx_flash"], tm["rev"], 0), (v["fx_meme"], tm["meme"], 0),
             (VOICE / v["vo_face"], tm["face_vo"], FACE_VO_GAIN),
             (SFX_REF / "upload" / "b1_v1.wav", tm["upload"], 0)]
    if v.get("fx_hook"):                                       # удар с первого кадра
        parts.append((v["fx_hook"], 0.0, HOOK_GAIN))
    ins, fc, labels = [], [], []
    for j, (p, t, g) in enumerate(parts):
        ms = round(t * 1000)
        ins += ["-i", str(p)]
        fc.append(f"[{base + j}:a]volume={g}dB,aformat=sample_rates=44100:channel_layouts=stereo,adelay={ms}|{ms}[s{j}]")
        labels.append(f"[s{j}]")
    n = base + len(parts)
    ins += ["-i", str(track)]
    g0, ms = tm["game"], round(tm["game"] * 1000)
    fc.append(f"[{n}:a]atrim=start={m0:.3f}:duration={total - g0:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.2,"
              f"afade=t=out:st={total - g0 - 0.35:.3f}:d=0.35,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100,"
              f"aformat=channel_layouts=stereo,adelay={ms}|{ms}[mus]")
    labels.append("[mus]")
    if v.get("intro_beat"):                                    # бит с первого кадра: тот же отрезок трека, до вспышки
        end = tm["rev"] + 0.03
        ins += ["-i", str(track)]
        fc.append(f"[{n + 1}:a]atrim=start={m0:.3f}:duration=6,asetpts=PTS-STARTPTS,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100,"
                  f"aformat=channel_layouts=stereo,atrim=end={end:.3f},afade=t=out:st={end - 0.06:.3f}:d=0.06,volume={INTRO_GAIN}dB[intro]")
        labels.append("[intro]")
    fc.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest,"
              f"alimiter=limit=0.95,atrim=end={total:.3f}[a]")
    return ins, fc, "[a]"


def build(i: int, concept: str, v: dict, out: Path, work: Path) -> dict:
    cfg = CONCEPTS[concept]
    rng = random.Random(v["seed"])
    track = D / "music" / v["music"]
    beats, tb = _beats(track.name)
    vo = VOICE / cfg["vo"]
    tm = {"vo": VO_AT}
    tm["rev"] = round(VO_AT + dur(vo) + REV_GAP, 3)                   # вспышка — сразу после голоса, как в рефах
    tm["meme"] = round(tm["rev"] + MEME_AFTER, 3)
    TA = tm["end"] = round(tm["rev"] + CARD_AFTER, 3)
    jcut, TB = face_len(cfg)
    TC = UPLOAD_LEN + SLIDE
    tm["face"], tm["upload"] = TA, TA + TB
    tm["face_vo"] = round(TA - jcut, 3)
    T0 = tm["game"] = round(TA + TB + TC - SLIDE, 3)
    n_d, n_e = max(4, round(3.5 / tb)), max(2, round(1.4 / tb))
    room = (n_d + n_e + 1) * tb + 0.4
    cand = [b for k, b in enumerate(beats) if k % 4 == 0 and b - 0.03 >= 0 and b + room <= _BEATS[track.name]["dur"] - 0.2]
    m0 = round(rng.choice(cand) - 0.03, 3)                         # бит вступает на склейке, с сильной доли
    gb = [b - m0 for b in beats if b >= m0][: n_d + n_e + 1]
    while len(gb) < n_d + n_e + 1:
        gb.append(gb[-1] + tb)
    TD, TE = gb[n_d], gb[n_d + n_e] - gb[n_d]
    if TARGET_TOTAL:                                           # ровная длина: CTA на последней доле, где ему хватает времени
        left = TARGET_TOTAL - T0
        TD = max(q for q in gb if q <= left - CTA_MIN)
        TE = round(left - TD, 3)
    tm["cta"] = T0 + TD
    total = round(T0 + TD + TE, 3)
    w = work / f"{concept}_{i:03d}"
    w.mkdir(parents=True, exist_ok=True)
    boxes = render_card_scene(cfg, v, round(_BEATS[track.name]["bpm"]), tm, w / "card.mp4", rng)
    pls = {}
    for key, txt, yk in (("face", cfg["texts"][1], "face"), ("up", cfg["texts"][2], "upload"),
                         ("game", cfg["texts"][3], "game"), ("cta", cfg["texts"][4], "game")):
        pl, q = plate(txt, 60 if key == "cta" else 56)
        p = w / f"{key}.png"
        pl.save(p)
        x, y = (W - pl.width) // 2, PLATE_Y[yk] - pl.height // 2
        pls[key] = (p, x, y)
        boxes.append(plate_box(pl, x, y, q))
    for b in boxes:
        if bad := check_box(W, H, tuple(int(q) for q in b)):
            raise SystemExit(f"{concept} {i:03d}: текст вне безопасной зоны {b} — {bad}")
    clip, face_t = v["face"]
    face = FACES / f"{clip}.MOV"
    face_t = round(min(face_t + rng.uniform(0, 0.06), dur(face) - TB - 0.02), 2)
    upl = D / "screencasts" / "00_Upload_Loading.mp4"
    game = D / "screencasts" / f"{v['game']}.mp4"
    g0 = round(rng.uniform(4.0, dur(game) - TD - TE - 1.0), 2)
    z = v["zoom"]
    zw, zh = round(W * z / 2) * 2, round(H * z / 2) * 2
    fx, fy = rng.randint(0, zw - W), rng.randint(0, int((zh - H) * 0.5))
    ux = UP_X0 + rng.randint(-10, 10)
    gx0, gy0, gx1, gy1 = GAME_BOX
    gw = 840
    gcx = (gx0 + gx1) // 2 + v["game_dx"]
    gxs = gcx - gw // 2
    gh_out = round((gy1 - gy0) * W / gw / 2) * 2
    gy = (H - gh_out) // 2
    pulse = "+".join(f"if(gte(on/{FPS},{b:.3f}),exp(-9*(on/{FPS}-{b:.3f})),0)" for b in gb)

    def ov(src: str, n: int, key: str, a: float, b: float, out_l: str) -> str:
        p, x, y = pls[key]                                         # плашка стоит, как подписи в рефах
        return f"[{src}][{n}:v]overlay=x={x}:y={y}:enable='between(t,{a:.3f},{b:.3f})'[{out_l}]"
    fc = [
        f"[0:v]fps={FPS},format=yuv420p,setsar=1[A]",
        f"[1:v]trim=start={face_t}:duration={TB:.3f},setpts=PTS-STARTPTS,fps={FPS},scale={zw}:{zh}:"
        f"force_original_aspect_ratio=increase,crop={zw}:{zh},crop={W}:{H}:{fx}:{fy},setsar=1[b0]",
        ov("b0", 4, "face", 0, TB, "B"),
        f"[2:v]trim=start={UP_T0}:duration={TC:.3f},setpts=PTS-STARTPTS,fps={FPS},crop=608:1080:{ux}:0,"
        f"scale={W}:{H},setsar=1,trim=end_frame={round(TC * FPS)}[c0]",
        ov("c0", 5, "up", 0, TC, "C"),
        f"[3:v]trim=start={g0}:duration={TD + TE:.3f},setpts=PTS-STARTPTS,fps={FPS},crop={gw}:{gy1 - gy0}:{gxs}:{gy0},"
        f"zoompan=z='1+0.045*({pulse})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{gh_out}:fps={FPS},"
        f"pad={W}:{H}:0:{gy}:color=0x080808,setsar=1[d0]",
        ov("d0", 6, "game", 0, TD, "d2"),
        ov("d2", 7, "cta", TD, TD + TE, "Dv"),
        "[A][B][C]concat=n=3:v=1:a=0,fps=30,settb=AVTB,format=yuv420p[abc]",
        "[Dv]fps=30,settb=AVTB,format=yuv420p[dd]",
        f"[abc][dd]xfade=transition=slideup:duration={SLIDE}:offset={T0:.3f},format=yuv420p[v]",
    ]
    a_in, a_fc, a_out = audio_graph(tm, v, vo, track, m0, total, 8)
    dest = out / f"{concept}_{i:03d}_noid.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(w / "card.mp4"), "-i", str(face), "-i", str(upl), "-i", str(game),
           "-i", str(pls["face"][0]), "-i", str(pls["up"][0]), "-i", str(pls["game"][0]), "-i", str(pls["cta"][0]),
           *a_in, "-filter_complex", ";".join(fc + a_fc), "-map", "[v]", "-map", a_out, "-t", f"{total:.3f}",
           "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
           "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
           "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
           "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)]
    subprocess.run(cmd, check=True)
    shutil.rmtree(w, ignore_errors=True)
    return {"video": dest.name, "concept": concept, "nick": v["nick"], "music": v["music"], "music_t": m0,
            "face": clip, "face_t": face_t, "game": v["game"], "game_t": g0, "meme": v["meme"].name,
            "fx_flash": v["fx_flash"].name, "fx_meme": v["fx_meme"].name, "total": total,
            "events": {k: round(x, 2) for k, x in tm.items()},
            "cuts": [round(x, 2) for x in (TA, TA + TB, T0, T0 + TD)]}


def variants(concept: str, n: int, seed: int) -> list[dict]:
    """Варианты концепта: сочетания (ник, трек, окно мимики, игра, мем) не повторяются — каждый раз берётся
    наименее использованное; звуки вспышки/мема, ряд под кругом, кадр и отрезки трека/геймплея — свои у ролика."""
    cfg = CONCEPTS[concept]
    rng = random.Random(f"{concept}-{seed}")
    md, mi = cfg["memes"]
    memes = [D / "memes" / md / f"{k:03d}.jpg" for k in mi]
    tb = face_len(cfg)[1]
    faces = [(c, t) for c, t, mx in REACT[cfg["react"]] if mx >= tb - 0.01]      # окна, где мимика держится весь кадр
    flashes = sorted((SFX_REF / "flash").glob("*.wav"))
    meme_fx = sorted((SFX_REF / "meme").glob("*.wav"))
    dots = [r for r, (_l, row) in enumerate(cfg.get("grid", [])) if isinstance(row, str) and set(row) <= set("●○")]
    axes = [cfg["nicks"], cfg["music"], faces, cfg["games"], memes]
    combos = list(itertools.product(*[range(len(a)) for a in axes]))
    rng.shuffle(combos)
    used = [[0] * len(a) for a in axes]
    out = []
    for i in range(n):
        if not combos:
            combos = list(itertools.product(*[range(len(a)) for a in axes]))
            rng.shuffle(combos)
        j = min(range(len(combos)), key=lambda q: sum(used[k][x] for k, x in enumerate(combos[q])))
        pick = combos.pop(j)
        for k, x in enumerate(pick):
            used[k][x] += 1
        nick, music, face, game, meme = (axes[k][x] for k, x in enumerate(pick))
        out.append(dict(
            seed=seed * 1000 + i, nick=nick,
            ago=rng.choice(["2d ago", "1d ago", "5h ago", "3d ago", "12h ago", "1w ago", "4d ago", "9h ago"]),
            likes=f"{rng.randint(1100, 9800):,}", music=music, face=face, game=game,
            vo_face=cfg["vo_face"], meme=meme, fx_flash=flashes[(i * 3 + 1) % len(flashes)],
            fx_meme=meme_fx[(i * 5 + 2) % len(meme_fx)],
            circle_row=dots[i % len(dots)] if dots else 0, meme_dx=rng.choice([-140, -80, 0, 80, 140]),
            arrow_lane=rng.randint(0, 3), meme_rot=rng.uniform(-3, 3), game_dx=rng.randint(-70, 70),
            zoom=rng.uniform(1.0, 1.06)))
    return out


def qa_sheet(videos: list[Path], dest: Path) -> None:
    """Кадры по ключевым моментам каждого ролика + рамка безопасной зоны."""
    man = {m["video"]: m for m in json.loads((videos[0].parent / "manifest.json").read_text(encoding="utf-8"))}
    tiles = []
    for vp in videos:
        e, c = man[vp.name]["events"], man[vp.name]["cuts"]
        for t in (0.6, e["rev"] + 0.5, e["meme"] + 0.5, (c[0] + c[1]) / 2, c[1] + 0.8, c[2] + 1.0, c[3] + 0.5):
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(vp), "-frames:v", "1", "-f",
                                  "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
            tiles.append(draw_overlay(Image.frombytes("RGB", (W, H), raw)).resize((216, 384)))
    sheet = Image.new("RGB", (7 * 216, len(videos) * 384), (20, 20, 20))
    for k, im in enumerate(tiles):
        sheet.paste(im, ((k % 7) * 216, (k // 7) * 384))
    sheet.save(dest, quality=86)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--concept", default="all", choices=["all", *CONCEPTS])
    ap.add_argument("-n", type=int, default=2, help="роликов на концепт")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "drops_beats_test")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--qa", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    concepts = list(CONCEPTS) if a.concept == "all" else [a.concept]
    a.out.mkdir(parents=True, exist_ok=True)
    work = a.out / "_work"
    man_p = a.out / "manifest.json"
    man = [m for m in (json.loads(man_p.read_text(encoding="utf-8")) if man_p.exists() else [])
           if m["concept"] not in concepts]
    for c in concepts:
        for i, v in enumerate(variants(c, a.n, a.seed), 1):
            man.append(build(i, c, v, a.out, work))
            print(f"  {man[-1]['video']}  {man[-1]['total']} с", flush=True)
            man_p.write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    if a.qa:
        qa_sheet([a.out / f"{c}_001_noid.mp4" for c in concepts], a.out / "_qa.jpg")
    print(f"готово → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
