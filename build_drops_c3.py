#!/usr/bin/env python3
"""
Drops — три карусели-истории (по 100, 3:4; ТЗ 2026-11-10, промпты output/drops_carousels3/PROMPTS.md).
  1 — «My best friend exposed himself» (8 слайдов): Flow-фото + рендер переписок (1.2, 1.8) + настоящий Drops на жёлтых экранах.
Фото — output/drops_c3_slides/c<карусель>_<слайд>/*.jpg (пулы: основной кадр + серийные варианты).
Тексты ТЗ дословно, переносы по смыслу, TikTok-шрифт с обводкой (как в прошлых Drops-историях), только в безопасной рамке.
Компоненты — build_drops_story_carousels (кадр, цвет, подпись, вставка экрана, чат).

  python build_drops_c3.py --story 1 -n 2 --out output/drops_c3_test --qa
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_drops_story_carousels as S  # noqa: E402
import strip_jpeg_meta  # noqa: E402
from core.safe_zones import check_box, draw_overlay  # noqa: E402

D, R = S.D, S.R
W, H = S.W, S.H
NL = "\n"
SLIDES = ROOT / "output" / "drops_c3_slides"
SCR = ROOT / "downloads" / "drops_carousels3"
CREATE = SCR / "screens" / "desk_create.png"
RANKS = SCR / "ranks"
HOME = SCR / "screens" / "desk_home.png"
MOBILE = SCR / "mobile"

TEXTS = {
    "1": [
        NL.join(["I found out my best friend", "had been lying about", "listening to my music", "for almost a YEAR 😭"]),
        NL.join(["Every time I sent him a new song", "he'd reply 'BRO THIS IS FIRE 🔥'", "within like 8 seconds."]),
        NL.join(["I thought he was just being supportive", "until I asked him", "what his favorite part was."]),
        NL.join(["This man said 'the beat drop' ...", "BRO IT'S AN ACOUSTIC SONG", "WITH NO DRUMS 💀"]),
        NL.join(["So I stopped sending him links.", "Clearly nobody was", "opening them anyway."]),
        NL.join(["Instead I turned one of my songs", "into a little game", "and sent it to our group chat."]),
        NL.join(["He spent 20 minutes", "trying to beat his own score.", "ON A SONG HE'D NEVER", "EVEN LISTENED TO 😭"]),
        NL.join(["Anyway he still can't name the song", "but apparently he's", "the world champion of it now 💀"]),
    ],
    "2": [
        NL.join(["My mom asked me", "when I was gonna stop making music", "and get a real job.", "I genuinely cried after that."]),
        NL.join(["I'd been making beats", "in my bedroom for 4 years.", "Most of my songs", "had less than 100 plays."]),
        NL.join(["The worst part?", "She used to be the FIRST person", "I played every new song for."]),
        NL.join(["Then one day I played her something", "I'd worked on for 3 weeks", "and she said 'that's nice honey'", "without looking up 😭"]),
        NL.join(["I stopped asking people to listen.", "Instead I started making", "little playable games", "out of my tracks."]),
        NL.join(["Last week I showed her one.", "She kept trying to get a better score", "and made me restart it", "THREE TIMES 💀"]),
        NL.join(["She still doesn't understand my music.", "But hearing her ask", "'can we play your song again?'", "genuinely made my week 🥹"]),
    ],
    "3": [
        NL.join(["I accidentally showed", "my Spotify stats", "to the girl I was trying to impress", "and I genuinely wanted to disappear 💀"]),
        NL.join(["I told her I make music.", "She said 'wait that's", "actually so cool,", "how many people listen?'"]),
        NL.join(["I confidently opened", "my artist profile", "like I was about to reveal", "a Grammy nomination."]),
        NL.join(["11 monthly listeners. ELEVEN.", "And I'm pretty sure", "4 of them are me 😭"]),
        NL.join(["She said 'aww that's cute'", "and I swear I heard", "my ancestors laughing."]),
        NL.join(["A few days later", "I sent her a little game", "I made using one of my songs", "instead of another Spotify link."]),
        NL.join(["She beat my high score", "and sent me a screenshot", "saying 'skill issue' 💀", "We are now officially enemies."]),
    ],
}
# слайд: ("photo", полоса подписи) · ("create"|"game", полоса) — жёлтый экран → страница создания / игра Drops · ("chat", функция)
SPEC = {
    "1": [("photo", (0.56, 0.78)), ("chat", "dm"), ("photo", (0.05, 0.25)), ("photo", (0.57, 0.78)),
          ("photo", (0.05, 0.30)), ("create", (0.05, 0.33)), ("photo", (0.05, 0.27)), ("chat", "ranks")],     # 1.7 — Flow: экран к нему, только отсвет
    # 2: s1 — на худи под лицом, s2 — над ноутбуком (стена со стикерами), s3 — над фото в руке, s4 — потолок над мамой,
    #    s5 — на одеяле под ноутбуком (главная Drops: «Upload a track»), s6 — над головой мамы (её телефон → игра), s7 — на худи
    "2": [("photo", (0.56, 0.78)), ("photo", (0.05, 0.26)), ("photo", (0.05, 0.30)), ("photo", (0.05, 0.24)),
          ("home", (0.60, 0.78)), ("photo", (0.05, 0.24)), ("photo", (0.62, 0.78))],   # 2.6 — Flow с игрой на экране
    # 3: s1/s5 — на рубашке под лицом (машина), s2 — потолок кафе над ней, s3 — над её свитером, над телефоном с профилем,
    #    s4 — экран профиля «11 monthly listeners», s6 — стена над ноутбуком (игра Drops), s7 — переписка с Mia
    "3": [("photo", (0.60, 0.78)), ("photo", (0.05, 0.22)), ("photo", (0.05, 0.22)), ("stats", None),   # 3.3 — Flow с профилем на экране
          ("photo", (0.62, 0.78)), ("desk_game", (0.05, 0.27)), ("chat", "mia")],
}
ARTIST = "Ryan Cole"

SEND = [["new song 🎧 lmk what u think", "made this tonight, be honest", "ok last one i promise 😭"],
        ["new one!! tell me what you think 🎧", "another one, rough mix", "this one's my favorite so far"],
        ["just finished this 🎧", "new demo, be honest pls", "ok this one's different"]]
DAYS = [["Mon 11:42 PM", "Thu 1:07 AM", "Sat 9:15 PM"], ["Tue 10:58 PM", "Fri 12:31 AM", "Sun 8:44 PM"],
        ["Wed 11:16 PM", "Sat 2:03 AM", "Mon 7:52 PM"]]


def yellow_all(photo: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """Жёлтый экран целиком: главный кусок + отрезанные пальцем куски рядом (строго) и «желтоватые» пиксели (мягко)."""
    a = np.asarray(photo).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    # экран ~(235, 211, 76): синего меньше половины зелёного, r−g ≈ 24; кожа пальца ~(211, 169, 99): b/g 0.57, r−g ≈ 42
    strict = ((r > 150) & (g > 150) & (b < 0.5 * g) & (r - g < 38) & (g - r < 30)).astype(np.uint8)
    loose = ((r > 90) & (g > 80) & (b < 0.62 * g) & (r - g < 45) & (r - b > 45)).astype(np.uint8)
    main = S.yellow_mask(photo) > 0
    near = cv2.dilate(main.astype(np.uint8), np.ones((61, 61), np.uint8)) > 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(strict)
    keep = np.zeros_like(strict)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= 25 and near[lab == i].any():
            keep[lab == i] = 1
    keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    return keep, loose


def phone_quad(mask: np.ndarray) -> np.ndarray:
    """Экран телефона, который держат боком (с перспективой): по повёрнутому прямоугольнику берём точки контура у каждой
    его стороны и проводим по ним прямую (Huber — вмятины от пальцев и выреза камеры не тянут линию), углы — пересечения.
    Верх игры — верхняя на фото длинная сторона. Порядок углов tl, tr, br, bl."""
    m = cv2.morphologyEx(mask.astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    pts = np.vstack([c.reshape(-1, 2) for c in cnts]).astype(np.float32)
    box = cv2.boxPoints(cv2.minAreaRect(pts))
    short = min(np.linalg.norm(box[1] - box[0]), np.linalg.norm(box[2] - box[1]))
    lines = []
    for k in range(4):
        p0, p1 = box[k], box[(k + 1) % 4]
        L = np.linalg.norm(p1 - p0)
        u = (p1 - p0) / L
        nrm = np.array([-u[1], u[0]])
        rel = pts - p0
        along, off = rel @ u, rel @ nrm
        sel = pts[(np.abs(off) < 0.12 * short) & (along > 0.1 * L) & (along < 0.9 * L)]
        if len(sel) < 8:
            lines.append((p0, u))
            continue
        vx, vy, x0, y0 = cv2.fitLine(sel, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((np.array([x0, y0]), np.array([vx, vy])))

    def cross(l1, l2):
        (q1, d1), (q2, d2) = l1, l2
        t = np.linalg.solve(np.array([d1, -d2]).T, q2 - q1)
        return q1 + t[0] * d1
    corners = np.array([cross(lines[(k - 1) % 4], lines[k]) for k in range(4)], np.float32)   # угол k — между сторонами k-1 и k
    edges = [(corners[k], corners[(k + 1) % 4]) for k in range(4)]
    longs = sorted(edges, key=lambda e: -np.linalg.norm(e[1] - e[0]))[:2]
    top = min(longs, key=lambda e: (e[0][1] + e[1][1]) / 2)
    bot = max(longs, key=lambda e: (e[0][1] + e[1][1]) / 2)
    tl, tr = sorted(top, key=lambda q: q[0])
    bl, br = sorted(bot, key=lambda q: q[0])
    return np.array([tl, tr, br, bl], np.float32)


def insert_screen(photo: Image.Image, shot: Image.Image, rng: random.Random, kind: str, centering) -> Image.Image:
    """Кадр Drops в жёлтый экран. Рисуем только там, где на фото жёлто: пальцы и края корпуса остаются поверх."""
    strict, loose = yellow_all(photo)
    q = phone_quad(strict) if kind == "game" else S.screen_quad(strict * 255)
    qw = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    qh = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    tw = int(max(qw * 1.3, 64))
    th_ = max(2, round(tw * qh / qw))
    if centering == "page":                                       # страница сайта: вся ширина, низ — фон страницы
        pg = shot.convert("RGB").resize((tw, round(tw * shot.height / shot.width)), Image.Resampling.LANCZOS)
        crop = Image.new("RGB", (tw, th_), pg.getpixel((4, pg.height - 4)))
        crop.paste(pg.crop((0, 0, tw, min(th_, pg.height))), (0, 0))
    elif kind == "game":                                          # телефон: скрин целиком, его настоящие пропорции —
        crop = shot.convert("RGB").resize((tw, round(tw * shot.height / shot.width)), Image.Resampling.LANCZOS)   # перспективу даёт warp
    else:
        crop = ImageOps.fit(shot.convert("RGB"), (tw, th_), Image.Resampling.LANCZOS, centering=centering)
    crop = crop.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    src = np.float32([[0, 0], [crop.width, 0], [crop.width, crop.height], [0, crop.height]])
    M = cv2.getPerspectiveTransform(src, q)
    warped = cv2.warpPerspective(np.asarray(crop), M, photo.size, flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    poly = np.zeros(strict.shape, np.uint8)
    cv2.fillConvexPoly(poly, np.round(q).astype(np.int32), 1)
    a_ = np.asarray(photo).astype(np.int16)
    r_, g_, b_ = a_[..., 0], a_[..., 1], a_[..., 2]
    lum = a_.mean(2)
    near = cv2.dilate(poly, np.ones((13, 13), np.uint8)) > 0
    # светящаяся каёмка экрана (светло-жёлтая, почти белая) и любые жёлтые полутона у края — тоже под картинку
    if kind == "game":
        # телефон: рисуем только по жёлтому (пальцы остаются поверх) + жёлто-оранжевые полутона у края жёлтого
        # (смесь кожи/рамки с жёлтым: синего меньше половины зелёного; у настоящей кожи — больше)
        grow = cv2.dilate(poly, np.ones((5, 5), np.uint8)) > 0
        m0 = ((strict > 0) | ((loose > 0) & (cv2.dilate(strict, np.ones((7, 7), np.uint8)) > 0))) & grow
        fringe = (b_ < 0.5 * g_) & (r_ > 100) & (g_ > 85) & (cv2.dilate(m0.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0)
        m = m0 | fringe
        # жёлто-оранжевый отсвет экрана на кончике пальца (синего меньше 45 % зелёного — у кожи больше) — тоже под картинку
        m = m | ((b_ < 0.45 * g_) & (r_ > 120) & (g_ > 90) & grow)
        # тонкая жёлтая полоска у самой рамки (светлее, синего чуть больше) — в 2 px от экрана
        edge2 = cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        m = m | ((b_ < 0.66 * g_) & (r_ - g_ < 40) & (g_ > 95) & edge2)
    else:
        # ноутбук: экран ничем не закрыт — весь четырёхугольник + светящаяся жёлтая каёмка у края
        rim = (lum > 140) & (b_ < 0.88 * g_) & (r_ > 0.85 * g_) & near
        m = (poly > 0) | ((strict > 0) & near) | ((loose > 0) & near) | rim
    k = cv2.GaussianBlur(m.astype(np.float32), (5, 5) if kind == "game" else (3, 3), 0)[..., None]
    base = np.asarray(photo).astype(np.float32)
    lum = base.mean(2)
    ref = np.percentile(lum[strict > 0], 95)
    shade = np.clip(lum / max(ref, 1), 0.7, 1.05)[..., None]
    w = warped.astype(np.float32) * (0.8 + 0.2 * shade) * rng.uniform(0.93, 0.98)
    w = w + np.random.default_rng(rng.randrange(1 << 30)).normal(0, 1.6, w.shape)
    out = base * (1 - k) + w * k
    if kind == "game":                                           # жёлтый отсвет экрана на рамке телефона — убираем цвет
        near15 = cv2.dilate(poly, np.ones((21, 21), np.uint8)) > 0
        cast = near15 & (k[..., 0] < 0.5) & (b_ < 0.66 * g_) & (r_ > 70) & (g_ > 60) & (r_ - g_ < 45)
        cast = cv2.GaussianBlur(cast.astype(np.float32), (5, 5), 0)[..., None]
        gray = np.repeat((base.mean(2) * 0.8)[..., None], 3, axis=2)
        out = out * (1 - cast) + gray * cast
        # жёлтый отсвет экрана на пальцах рядом с экраном: на экране теперь тёмная игра — переводим в цвет кожи с отсветом игры
        near31 = cv2.dilate(poly, np.ones((41, 41), np.uint8)) > 0
        glow = near31 & (k[..., 0] < 0.5) & (b_ < 0.62 * g_) & (r_ > 110) & (g_ > 80)
        gk = cv2.GaussianBlur(glow.astype(np.float32), (9, 9), 0)[..., None]
        tint = w[poly > 0].mean(0) if (poly > 0).any() else np.array([120, 90, 160], np.float32)
        lumv = out.mean(2, keepdims=True)
        skin = np.concatenate([lumv * 1.12, lumv * 0.92, lumv * 0.82], axis=2) * 0.85 + tint * 0.15 * (lumv / 160)
        out = out * (1 - 0.75 * gk) + skin * 0.75 * gk
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def screen_slide(photo: Image.Image, shot: Image.Image, band: tuple, rng: random.Random, centering, kind: str) -> tuple[Image.Image, tuple]:
    raw = S.frame(photo, rng, 2)
    big = insert_screen(raw, shot, rng, kind, centering)
    im = S.grade(big.resize((W, H), Image.Resampling.LANCZOS), rng).convert("RGBA")
    layer, box = S.caption(TEXT_CUR, *band, rng)
    return Image.alpha_composite(im, layer).convert("RGB"), box


TEXT_CUR = ""


def chat_dm(rng: random.Random) -> callable:
    av = rng.choice(D.AVATARS)
    v = rng.randrange(len(SEND))
    sends, days = SEND[v], DAYS[v]
    bat = rng.uniform(.2, .85)

    def make(hist: int) -> R.Chat:
        rows = [("mark", "top")]
        for k in range(3):
            rows += [("time", days[k]), ("me", sends[k]), ("them", "BRO THIS IS FIRE 🔥", None, av)]   # личка — без имени над пузырём
        return R.Chat(title="tyler", subtitle="Active now", avatars=[av], rows=rows, theme="dark",
                      clock=days[2].split()[1].removesuffix("PM").removesuffix("AM").strip()[:5] if False else D.clock(21, 16), battery=bat)
    return make


def chat_ranks(rng: random.Random) -> callable:
    names = rng.sample([n for n in D.NAMES if n not in ("tyler", "noah")], 2)
    av = rng.sample(D.AVATARS, 3)
    rk = rng.choice(sorted(RANKS.glob("ranks_tyler_*.png")))
    img = Image.open(rk).convert("RGB").crop((0, 40, 1080, 1380))
    group = rng.choice(D.GROUPS)
    h, m = rng.choice([22, 23, 0, 1]), rng.randint(0, 59)
    champ = rng.choice(["world champion btw 🏆", "#1 in the world btw 🏆", "who's the champ now 🏆"])
    ask = rng.choice(["ok what's the song called", "name the song. right now", "cool. what's the song called tho"])
    reply = rng.choice(["the one with the beat drop obviously", "doesn't matter i'm #1", "…the fire one 🔥"])

    def make(hist: int) -> R.Chat:
        rows = [("mark", "top"), ("time", D.fmt(h, m)), ("photo", img, "them", "tyler", av[0], 0.4),
                ("them", champ, "tyler", av[0]), ("me", ask), ("them", reply, "tyler", av[0]), ("them", "💀", names[0], av[1])]
        return R.Chat(title=group, subtitle="Active now", avatars=av[:2], rows=rows, theme="dark",
                      clock=D.clock(h, m + rng.randint(2, 9)), battery=rng.uniform(.2, .85))
    return make


def chat_mia(rng: random.Random) -> callable:
    av = rng.choice(D.AVATARS)
    rk = rng.choice(sorted((SCR / "ranks_mia").glob("ranks_mia_*.png")))
    img = Image.open(rk).convert("RGB").crop((0, 40, 1080, 1380))
    h, m = rng.choice([21, 22, 23]), rng.randint(0, 40)
    sent = rng.choice(["made this out of one of my songs, try it 🎮", "ok forget spotify. play this instead", "made a little game from my song lol"])
    after = rng.choice(["HOW", "excuse me??", "that's literally my song"])
    end = rng.choice(["we're enemies now", "you're blocked", "i want a rematch"])
    last = rng.choice(["😌", "rematch denied", "sore loser 💀"])

    def make(hist: int) -> R.Chat:
        rows = [("mark", "top"), ("me", sent), ("time", D.fmt(h, m + 17)),
                ("photo", img, "them", None, av, 0.36), ("them", "skill issue 💀", None, av), ("me", end)]
        return R.Chat(title="mia", subtitle="Active now", avatars=[av], rows=rows, theme="dark",
                      clock=D.clock(h, m + 19), battery=rng.uniform(.2, .85))
    return make


CHATS = {"dm": chat_dm, "ranks": chat_ranks, "mia": chat_mia}


def white_quad(photo: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """Пустой белый экран телефона (вертикально, лицом в камеру): крупный светлый ненасыщенный прямоугольник."""
    a = np.asarray(photo).astype(np.int16)
    mn, mx = a.min(2), a.max(2)
    m = ((mn > 205) & (mx - mn < 28)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    best, score = None, 0
    for i in range(1, n):
        x, y, w, h, ar = st[i]
        if ar < 1500 or h < 1.4 * w or h > 3.2 * w:
            continue
        fill = ar / (w * h)
        if fill > 0.6 and ar * fill > score:
            best, score = i, ar * fill
    if best is None:
        raise SystemExit("не нашёл белый экран телефона")
    mask = (lab == best).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    return S.screen_quad(mask), mask


def phone_white_slide(photo: Image.Image, band: tuple, rng: random.Random, seed: int) -> tuple[Image.Image, tuple]:
    import render_artist_stats as AS
    raw = S.frame(photo, rng, 2)
    q, mask = white_quad(raw)
    screen = AS.render(ARTIST, 11, AS.songs_for(seed), height=2340, seed=seed)
    qw = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    tw = int(qw * 1.4)
    crop = screen.resize((tw, round(tw * screen.height / screen.width)), Image.Resampling.LANCZOS)
    src = np.float32([[0, 0], [crop.width, 0], [crop.width, crop.height], [0, crop.height]])
    M = cv2.getPerspectiveTransform(src, q)
    warped = cv2.warpPerspective(np.asarray(crop), M, raw.size, flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    poly = np.zeros(mask.shape, np.uint8)
    cv2.fillConvexPoly(poly, np.round(q).astype(np.int32), 1)
    a = np.asarray(raw).astype(np.int16)
    skin = (a[..., 0] - a[..., 1] > 22) & (a[..., 0] > 110) & (a[..., 2] < 0.85 * a[..., 0])
    m = ((poly > 0) | (mask > 0)) & ~skin
    k = cv2.GaussianBlur(m.astype(np.float32), (3, 3), 0)[..., None]
    base = a.astype(np.float32)
    w = warped.astype(np.float32) * rng.uniform(0.93, 0.98) + np.random.default_rng(seed).normal(0, 1.6, warped.shape)
    big = Image.fromarray(np.clip(base * (1 - k) + w * k, 0, 255).astype(np.uint8))
    im = S.grade(big.resize((W, H), Image.Resampling.LANCZOS), rng).convert("RGBA")
    layer, box = S.caption(TEXT_CUR, *band, rng)
    return Image.alpha_composite(im, layer).convert("RGB"), box


def stats_slide(rng: random.Random, seed: int) -> tuple[Image.Image, tuple]:
    import render_artist_stats as AS
    im = AS.render(ARTIST, 11, AS.songs_for(seed), height=H, seed=seed, head_frac=0.5, arrow=False).convert("RGBA")
    layer, box = S.caption(TEXT_CUR, 0.09, 0.31, rng)
    return Image.alpha_composite(im, layer).convert("RGB"), box


def chat_slide(text: str, make_chat) -> tuple[Image.Image, tuple]:
    """Как S.chat_slide, но «высокий телефон» до 2600 px — в чате с фото-сообщением переписка выше."""
    C = S.C
    chat = make_chat(0)

    def heights():
        for hh in range(H, 2600, 160):
            yield hh, True
    found = None
    for hh, coarse in heights():
        if _chat_try(text, chat, hh) is not None:
            found = hh
            break
    if found is None:
        raise SystemExit("подпись не помещается над перепиской")
    for hh in range(max(H, found - 120), found + 1, 40):
        res = _chat_try(text, chat, hh)
        if res is not None:
            return res
    raise SystemExit("подпись не помещается над перепиской")


def _chat_try(text: str, chat, hh: int):
    C = S.C
    if True:
        k = H / hh
        shot = R.render(chat, hh, full=True, anchor="bottom")
        sw = round(W * k)
        bg = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        ox = (W - sw) // 2
        bg.paste(shot.resize((sw, H), Image.Resampling.LANCZOS), (ox, 0))
        top = max(int(R.render.header_bottom * k) + 20, S.Y0)
        first = min(int(R.render.marks["top"] * k) - 20, S.Y1)
        if first - top < 200 or not C.fits(text, 44, first - top, S.X1 - S.X0):
            return None
        block = C.block_for(text, first - top, S.X1 - S.X0)
        x, y = (W - block.width) // 2, (top + first) // 2 - block.height // 2
        box = (x, y, x + block.width, y + block.height)
        boxes = [(ox + q[0] * k, q[1] * k, ox + q[2] * k, q[3] * k) for q in R.render.boxes]
        if any(q[3] > R.render.header_bottom * k and D.overlaps(box, q) for q in boxes):
            return None
        bg.alpha_composite(block, (x, y))
        return bg.convert("RGB"), box


def pool(story: str, k: int) -> list[Path]:
    d = SLIDES / f"c{story}_{k + 1}"
    return sorted(f for f in d.glob("*.jpg") if not f.name.startswith("_")) if d.is_dir() else []


def build(story: str, rng: random.Random, picks: list, game: tuple) -> tuple[list[Image.Image], list[tuple]]:
    global TEXT_CUR
    out, boxes = [], []
    for k, (kind, arg) in enumerate(SPEC[story]):
        TEXT_CUR = TEXTS[story][k]
        if kind == "chat":
            im, box = chat_slide(TEXT_CUR, CHATS[arg](rng))
        elif kind == "stats":
            im, box = stats_slide(rng, rng.randrange(1 << 20))
        elif kind == "phone_white":
            im, box = phone_white_slide(Image.open(picks[k]).convert("RGB"), arg, rng, rng.randrange(1 << 20))
        elif kind in ("create", "game", "home", "desk_game"):
            photo = Image.open(picks[k]).convert("RGB")
            if kind == "desk_game":                              # ноутбук: настоящая игра Drops с сайта (шапка + поле)
                g = S.game_frame(*game[:2])
                shot, cen = g.crop((S.SCREEN_BOX_X[0], S.SCREEN_TOP, S.SCREEN_BOX_X[1], 1080)), "page"
            elif kind == "home":
                shot, cen = Image.open(HOME).convert("RGB").crop((0, 0, 2880, 1300)), "page"
            elif kind == "create":
                shot, cen = Image.open(CREATE).convert("RGB").crop((0, 0, 2880, 1745)), "page"   # без чёрного подвала
            else:                                                # телефон боком — мобильная версия игры Party Pop (альбомная)
                lands = sorted(MOBILE.glob("land_*.png"))
                sh = Image.open(lands[game[2] % len(lands)]).convert("RGB")
                shot, cen = sh.crop((0, 0, sh.width, int(sh.height * 0.935))), (0.5, 0.5)   # без полосы TERMS · PRIVACY (экран iPhone 2.16:1)
            im, box = screen_slide(photo, shot, arg, rng, cen, kind)
        else:
            photo = Image.open(picks[k]).convert("RGB")
            base = S.grade(S.frame(photo, rng), rng).convert("RGBA")
            layer, box = S.caption(TEXT_CUR, *arg, rng)
            im = Image.alpha_composite(base, layer).convert("RGB")
        out.append(im)
        boxes.append(box)
    return out, boxes


def render_one(job):
    story, i, seed, picks, game, out, flat = job
    rng = random.Random(seed * 1000 + i)
    slides, boxes = build(story, rng, [Path(p) if p else None for p in picks], game)
    d = Path(out) / f"{i:03d}"
    d.mkdir(exist_ok=True)
    for k, (im, b) in enumerate(zip(slides, boxes)):
        if bad := check_box(W, H, b):
            raise SystemExit(f"{i:03d} слайд {k + 1}: вне безопасной зоны {b} — {bad}")
        im.save(d / f"{k + 1}.jpg", quality=93)
        if flat:
            shutil.copy2(d / f"{k + 1}.jpg", Path(flat) / f"sort_{k + 1}_{i}_1.jpg")
    return i, picks, game


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", default="1", choices=list(TEXTS))
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--flat", type=Path)
    ap.add_argument("--seed", type=int, default=310)
    ap.add_argument("--qa", action="store_true")
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    spec = SPEC[a.story]
    pools = [pool(a.story, k) if kind not in ("chat", "stats") else [] for k, (kind, _) in enumerate(spec)]
    for k, (kind, _) in enumerate(spec):
        if kind not in ("chat", "stats") and not pools[k]:
            raise SystemExit(f"нет фото для слайда {k + 1}: {SLIDES / f'c{a.story}_{k + 1}'}")
    rng0 = random.Random(a.seed)
    combos = list(itertools.product(*[range(len(p)) if p else [None] for p in pools]))
    rng0.shuffle(combos)
    codes = list(S.GAME_T)
    games = [(codes[i % len(codes)], round(rng0.uniform(*S.GAME_T[codes[i % len(codes)]]), 2), i) for i in range(a.n)]
    rng0.shuffle(games)
    a.out.mkdir(parents=True, exist_ok=True)
    if a.flat:
        a.flat.mkdir(parents=True, exist_ok=True)
    jobs = []
    for i in range(1, a.n + 1):
        picks = [str(p[j]) if p else None for p, j in zip(pools, combos[(i - 1) % len(combos)])]
        jobs.append((a.story, i, a.seed, picks, games[i - 1], str(a.out), str(a.flat) if a.flat else None))
    manifest, qa = [], []
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(a.jobs) as ex:
        for i, picks, game in ex.map(render_one, jobs):
            manifest.append({"carousel": f"{i:03d}", "photos": [Path(p).name if p else None for p in picks], "game": game})
            print(f"  {i:03d}", flush=True)
    if a.qa:
        for i in (1, 2):
            for k in range(len(spec)):
                f = a.out / f"{i:03d}" / f"{k + 1}.jpg"
                if f.exists():
                    qa.append(draw_overlay(Image.open(f).convert("RGB")))
    n_sl = len(spec)
    if qa:
        tw, th = 270, 360
        sheet = Image.new("RGB", (n_sl * tw, (len(qa) // n_sl) * th), (30, 30, 30))
        for j, q in enumerate(qa):
            sheet.paste(q.resize((tw, th)), ((j % n_sl) * tw, (j // n_sl) * th))
        sheet.save(a.out / "_qa.jpg", quality=86)
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    sys.argv = ["strip", str(a.out)] + ([str(a.flat)] if a.flat else [])
    strip_jpeg_meta.main()
    print(f"готово: {a.n} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
