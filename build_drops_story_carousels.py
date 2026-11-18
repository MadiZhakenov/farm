#!/usr/bin/env python3
"""
Drops — сторителлинг-карусели (айди нет): 2 истории × 6 слайдов 3:4 (1080×1440), по 150.
  A — парень-битмейкер («I had 47 unfinished beats…»), одна комната ночью:
      s1 селфи за столом-студией · s2 рука на MIDI · s3 пустой стул от двери · s4 лёжа на кровати, ноги к столу ·
      s5 ноутбук с жёлтым экраном → на экран встаёт настоящий кадр игры Drops · s6 групповой чат Instagram:
      моя карточка-ссылка на игру, 🔥 и «wait, this is YOUR song?».
  C — «my dad played in bars for 30 years»: 6 фото (s1 селфи с папой, s5 ноутбук → настоящий кадр Drops), без чата.
  B — девушка с гитарой («The last time I sent my music…»): s1 селфи на кровати · s2 тетрадь с текстом ·
      s3 ужин у родителей, колонка · s4 кафе, малознакомая подруга рассказывает · s5 ноутбук на кровати →
      настоящий кадр Drops · s6 групповой чат: её ссылка на игру, 🔥 3, «wait, how do you beat the second part??».
Фото — output/drops_story_slides/<a1..a5>/*.jpg (Flow; лицо только на s1, дальше POV одной рукой).
Кадры игр — скринкасты Drops (downloads/drops_beats/screencasts, SP*/MP*): у каждой карусели своя игра и момент,
та же игра — в превью ссылки в чате. Чат рисует render_igdm заново (имена, группа, время, реакции — свои).
Тексты ТЗ дословно, переносы по смыслу, TikTok-шрифт с обводкой (C.block_for), только в безопасной рамке.

  python build_drops_story_carousels.py --story A -n 4 --out output/drops_story_test --qa
  python build_drops_story_carousels.py --story A -n 150 --out output/carousels_drops_story_A --flat output/drops_story_A_150
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1283_carousels as C  # noqa: E402  (block_for — TikTok-текст с обводкой и эмодзи)
import build_1388d_carousels as D  # noqa: E402  (имена, группы, аватарки без лиц, старая болтовня, fmt/clock)
import render_igdm as R  # noqa: E402
import strip_jpeg_meta  # noqa: E402
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402

W, H = 1080, 1440
X0, Y0, X1, Y1 = text_rect(W, H)
SL = ROOT / "output" / "drops_story_slides"
SC = ROOT / "downloads" / "drops_beats" / "screencasts"
GAME_BOX = (60, 92, 1380, 1062)              # игровое поле в скринкасте 1920×1080 (для превью ссылки)
NL = "\n"
# на экране ноутбука и в превью — только читаемые игры (яркие, крупные формы), окно времени в скринкасте;
# пёстрая туманность SP1 в начале, тусклые MP2/MP5, серый SP3 — нет («мыльно и ничего не видно»)
GAME_T = {"MP1": (6, 30), "MP4": (12, 28), "SP1": (22, 30), "SP2": (6, 18), "SP4": (6, 18), "SP5": (6, 18),
          "SP6": (6, 26), "SP7": (6, 26)}
SCREEN_BOX_X = (4, 1430)                     # на экране: жёлтая шапка с названием + игра, без панели рекордов (≥ 1435)
SCREEN_TOP = 24                              # строки 0–23 скринкаста — тёмная системная полоса
GAMES = {"SP1": "Where The Good Times Go", "SP2": "When I Say Go", "SP3": "The Little Game",
         "SP4": "Take It Easy Darling", "SP5": "Stay Till The Morning", "SP6": "Some Threads Stay With Me",
         "SP7": "We're Not Going Home", "MP1": "1 Get Back", "MP2": "2 Get Out Of My Head", "MP3": "3 The Best Bad Idea",
         "MP4": "4 We're Not Going Home", "MP5": "5 Your Coat On The Chair"}

# текст ТЗ дословно; переносы по смыслу
TEXTS = {
    "A": [
        NL.join(["I had 47 unfinished beats,", "6 released songs,", "and approximately 3 people", "who actually listened."]),
        NL.join(["I kept telling myself", "the next track would be the one.", "I’d stay up until 3am", "tweaking a snare,",
                 "then post it and watch the numbers", "sit at the same place."]),
        NL.join(["I tried everything:", "short clips, behind-the-scenes,", "begging my friends for a share.",
                 "It started to feel like", "I was making music", "for an empty room."]),
        NL.join(["Last week my cousin mentioned", "a site called Drops", "where you can turn your own music",
                 "into a game.", "I rolled my eyes,", "but I was too tired", "to scroll anymore."]),
        NL.join(["So I uploaded one of my", "unfinished beats to Drops,", "answered a few questions,",
                 "and a playable game appeared.", "I sent the link to my group chat", "instead of another demo."]),
        NL.join(["Two of them played it right away.", "One said “wait, this is YOUR song?”", "It wasn’t a huge moment,",
                 "but it was the first time", "in a long time", "that someone reacted."]),
    ],
    "B": [
        NL.join(["The last time I sent my music", "to our group chat,", "someone changed the subject", "in 10 seconds."]),
        NL.join(["I actually timed it.", "Ten seconds and then the whole chat", "was about where to get dinner.",
                 "Nobody was rude,", "it just wasn’t interesting to them."]),
        NL.join(["I’d spent three weeks on that song.", "I played it for my family,", "posted it everywhere,",
                 "and kept hoping someone", "would ask a question about it."]),
        NL.join(["A friend I barely talk to", "told me about Drops,", "a website where you can turn",
                 "your own music into a game.", "I thought it sounded like a joke,", "but I was curious."]),
        NL.join(["I uploaded the same song to Drops,", "built a game from it,", "and sent my group chat the link",
                 "instead of the track.", "No downloads, no signups,", "they just opened it."]),
        NL.join(["Within a minute someone texted", "“wait, how do you beat", "the second part??”",
                 "and three people played it twice."]),
    ],
    "C": [                                                         # папа играл в барах 30 лет (дословно, со «”» на s2)
        NL.join(["my dad played in bars", "for 30 years.", "these are the things", "he told me about music 🎸"]),
        NL.join(["finish it.", "a bad song you finished", "is worth more than", "a perfect one in your head.”"]),
        NL.join(["if you don’t feel it at 2am,", "don’t release it at noon."]),
        NL.join(["never fix a song", "when you’re angry at it.", "sleep first."]),
        NL.join(["play with your own music.", "don’t just listen to it.", "i do it in Drops now,",
                 "and it’s how i find out", "what my track actually needs."]),
        NL.join(["play it for one person", "before everyone.", "their face will tell you more", "than any comment."]),
    ],
}
# полоса подписи (доли высоты): s1 — на футболке под наушниками, s2 — на ноутбуке над MIDI, s3/s4 — стена/потолок,
# s5 — на клавиатурах под экраном с игрой; s6 — чат (полоса между шапкой и перепиской)
BANDS = {"A": [(0.60, 0.78), (0.37, 0.62), (0.06, 0.33), (0.06, 0.36), (0.56, 0.78), None],
         # B: s1 — на гитаре под лицом, s2 — на кровати над тетрадью, s3 — на родителях (без лиц) над салатом,
         # s4 — на столе (руки подруги сверху открыты), s5 — на подушках над ноутбуком
         "B": [(0.56, 0.78), (0.06, 0.31), (0.06, 0.32), (0.44, 0.78), (0.05, 0.31), None],
         # C: s1 — на стене с постерами над головами, s2 — над тетрадью, s3/s4 — на стене, s5 — на клавиатуре и столе
         # под экраном, s6 — над головой папы (улица)
         "C": [(0.05, 0.23), (0.05, 0.23), (0.06, 0.30), (0.06, 0.32), (0.52, 0.78), (0.05, 0.24)]}
CHAT = {"A": 5, "B": 5, "C": None}                                 # у C чата нет — все 6 слайдов фото

MY_DROP = ["made one of my beats into a game, try it", "ok play this", "turned an unfinished beat into a game lol",
           "try this 👀", "new thing, play it", "this is one of my beats. play it"]
SECOND = ["just got 9k on it", "played it twice already", "ok this is actually fun", "how do i get past the drop 😭",
          "8,450. beat that", "wait it's actually hard"]
AGAIN = ["played it twice already", "ok one more try", "running it back 😭", "again. i'm doing it again",
         "twice. still stuck there", "round 2 lol"]


# ---------------------------------------------------------------- кадр, цвет, подпись
def grade(im: Image.Image, rng: random.Random) -> Image.Image:
    """Ночь под лампой: чуть сочнее и контрастнее (сильный vivid дальнобойщика пережигает тёплый свет)."""
    im = ImageEnhance.Color(im).enhance(rng.uniform(1.06, 1.14))
    im = ImageEnhance.Contrast(im).enhance(rng.uniform(1.03, 1.07))
    im = ImageEnhance.Brightness(im).enhance(rng.uniform(1.0, 1.05))
    a = np.asarray(im).astype(np.float32)
    warm = rng.uniform(-3, 4)
    a[..., 0] += warm
    a[..., 2] -= warm
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def frame(im: Image.Image, rng: random.Random, scale: int = 1) -> Image.Image:
    """3:4 → 1080×1440 (× scale) с лёгким зумом и сдвигом (своими у каждой карусели)."""
    z = rng.uniform(1.0, 1.06)
    w, h = im.width / z, im.height / z
    x, y = rng.uniform(0, im.width - w), rng.uniform(0, im.height - h)
    return im.crop((round(x), round(y), round(x + w), round(y + h))).resize((W * scale, H * scale),
                                                                           Image.Resampling.LANCZOS)


def caption(text: str, top: float, bottom: float, rng: random.Random) -> tuple[Image.Image, tuple]:
    top, bottom = max(int(top * H), Y0), min(int(bottom * H), Y1)
    block = C.block_for(text, bottom - top, X1 - X0)
    x = max(X0, min(X1 - block.width, int(W / 2 - block.width / 2 + rng.randint(-12, 12))))
    y = max(Y0, min(Y1 - block.height, int((top + bottom) / 2 - block.height / 2 + rng.randint(-10, 10))))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.alpha_composite(block, (x, y))
    return layer, (x, y, x + block.width, y + block.height)


# ---------------------------------------------------------------- экран ноутбука: настоящий кадр Drops
def game_frame(code: str, t: float) -> Image.Image:
    src = next(SC.glob(f"{code}_*.mp4"))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return Image.frombytes("RGB", (1920, 1080), raw)


def yellow_mask(photo: Image.Image) -> np.ndarray:
    a = np.asarray(photo).astype(np.int16)
    m = ((a[..., 0] > 150) & (a[..., 1] > 150) & (a[..., 2] < 120) & (np.abs(a[..., 0] - a[..., 1]) < 80)).astype(np.uint8)
    m = cv2.morphologyEx(m * 255, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    return (lab == k).astype(np.uint8) * 255


def screen_quad(mask: np.ndarray) -> np.ndarray:
    """Углы жёлтого экрана (tl, tr, br, bl): по каждой стороне — прямая по точкам контура (без скруглённых углов),
    углы — пересечения прямых. Крайние точки сдвигаются скруглением и строкой браузера — вставка шла криво."""
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    pts = max(cnts, key=cv2.contourArea).reshape(-1, 2).astype(np.float32)
    sm, df = pts.sum(1), pts[:, 0] - pts[:, 1]
    q0 = np.array([pts[sm.argmin()], pts[df.argmax()], pts[sm.argmax()], pts[df.argmin()]], np.float32)
    lines = []
    for i in range(4):
        p, r = q0[i], q0[(i + 1) % 4]
        d = r - p
        L = np.linalg.norm(d)
        u = d / L
        nrm = np.array([-u[1], u[0]])
        rel = pts - p
        along, off = rel @ u, rel @ nrm
        sel = pts[(np.abs(off) < 0.02 * L + 3) & (along > 0.12 * L) & (along < 0.88 * L)]
        vx, vy, x0, y0 = cv2.fitLine(sel, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((np.array([x0, y0]), np.array([vx, vy])))

    def cross(l1, l2):
        (p1, d1), (p2, d2) = l1, l2
        t = np.linalg.solve(np.array([d1, -d2]).T, p2 - p1)
        return p1 + t[0] * d1
    # стороны: 0 верх (tl→tr), 1 право, 2 низ, 3 лево; угол i — пересечение стороны i-1 и i
    return np.array([cross(lines[(i - 1) % 4], lines[i]) for i in range(4)], np.float32)


def put_screen(photo: Image.Image, shot: Image.Image, rng: random.Random) -> Image.Image:
    """Кадр Drops по 4 углам в жёлтый экран; тени/блики экрана с фото переносим на картинку, лёгкое зерно."""
    ym = yellow_mask(photo)
    q = screen_quad(ym)
    qw = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    qh = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    asp = qw / qh
    x0, x1 = SCREEN_BOX_X                                        # шапка + игра, без правой панели рекордов
    y0 = SCREEN_TOP                                              # без тёмной системной полосы над шапкой
    crop = shot.crop((x0, y0, x1, min(shot.height, y0 + round((x1 - x0) / asp))))
    # сначала уменьшаем до размера экрана ×1,3 (LANCZOS) и чуть подтачиваем — иначе warp даёт мыло
    tw = int(qw * 1.3)
    crop = crop.resize((tw, round(tw * crop.height / crop.width)), Image.Resampling.LANCZOS)
    crop = crop.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    src = np.float32([[0, 0], [crop.width, 0], [crop.width, crop.height], [0, crop.height]])
    M = cv2.getPerspectiveTransform(src, q)
    warped = cv2.warpPerspective(np.asarray(crop), M, photo.size, flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    poly = np.zeros_like(ym)
    cv2.fillConvexPoly(poly, np.round(q).astype(np.int32), 255)
    # ни одного жёлтого пикселя по краю: у мягкой границы экрана полутона жёлтого не проходят строгий порог —
    # у самой рамки (полоса ~1,5 % ширины экрана) забираем и «желтоватые» пиксели; за quad — повтор края кадра игры
    a = np.asarray(photo).astype(np.int16)
    loose = ((a[..., 0] > 90) & (a[..., 1] > 80) & (a[..., 0] - a[..., 2] > 45) & (a[..., 1] - a[..., 2] > 35)
             ).astype(np.uint8) * 255
    r = max(3, int(qw * 0.015)) | 1
    near = cv2.dilate(poly, np.ones((r, r), np.uint8))
    mask = np.maximum(poly, cv2.dilate(ym, np.ones((3, 3), np.uint8)))
    mask = np.maximum(mask, cv2.dilate(loose & near, np.ones((3, 3), np.uint8)))
    mask = cv2.GaussianBlur(mask, (3, 3), 0)
    base = np.asarray(photo).astype(np.float32)
    lum = base.mean(2)
    ref = np.percentile(lum[ym > 0], 95)
    shade = np.clip(lum / max(ref, 1), 0.7, 1.05)[..., None]     # неравномерность подсветки экрана
    w = warped.astype(np.float32) * (0.8 + 0.2 * shade) * rng.uniform(0.93, 0.98)
    w = w + np.random.default_rng(rng.randrange(1 << 30)).normal(0, 1.6, w.shape)
    k = (mask.astype(np.float32) / 255)[..., None]
    return Image.fromarray(np.clip(base * (1 - k) + w * k, 0, 255).astype(np.uint8))


def card_image(shot: Image.Image) -> Image.Image:
    g = shot.crop(GAME_BOX)
    return ImageOps.fit(g, (764, 250), Image.Resampling.LANCZOS, centering=(0.5, 0.55))   # низкое превью — место подписи


# ---------------------------------------------------------------- чат
def plan_chat(rng: random.Random) -> dict:
    return dict(names=rng.sample(D.NAMES, 5), av=rng.sample(D.AVATARS, 5), group=rng.choice(D.GROUPS),
                t=(rng.choice([8, 9, 10, 11]), rng.randint(0, 59)), after=rng.randint(3, 40),
                drop=rng.choice(MY_DROP), second=rng.choice(SECOND), react=rng.choice(["🔥", "🔥😭", "😭🔥", "🔥"]),
                again=rng.choice(AGAIN),
                filler=rng.choice(D.FILLER), filler_who=rng.randint(2, 4), bat=rng.uniform(0.2, 0.85))


def chat_a6(p: dict, shot: Image.Image, title: str, hist: int) -> R.Chat:
    h, m = p["t"]
    n, av = p["names"], p["av"]
    wi = p["filler_who"]
    rows = [("mark", "top")] + [("them", p["filler"][-1], n[wi], av[wi])][:hist] + [
        ("time", D.fmt(h, m)), ("mark", "key"), ("card", card_image(shot), title, "drops.game"),
        ("react", p["react"], 2),                                   # «двое сразу сыграли»
        ("them", "wait, this is YOUR song?", n[0], av[0])]
    return R.Chat(title=p["group"], subtitle="Active now", avatars=av[:2], rows=rows, theme="dark",
                  clock=D.clock(h, m + p["after"]), battery=p["bat"])


def chat_b6(p: dict, shot: Image.Image, title: str, hist: int) -> R.Chat:
    """Её ссылка на игру вместо трека; через минуту — «wait, how do you beat the second part??», 🔥 3 и «сыграли дважды»."""
    h, m = p["t"]
    n, av = p["names"], p["av"]
    wi = p["filler_who"]
    rows = [("mark", "top")] + [("them", p["filler"][-1], n[wi], av[wi])][:hist] + [
        ("time", D.fmt(h, m)), ("mark", "key"), ("card", card_image(shot), title, "drops.game"),
        ("react", p["react"], 3),
        ("them", "wait, how do you beat the second part??", n[0], av[0]),
        ("them", p["again"], n[1], av[1])]
    return R.Chat(title=p["group"], subtitle="Active now", avatars=av[:2], rows=rows, theme="dark",
                  clock=D.clock(h, m + 1 + p["after"] % 4), battery=p["bat"])


CHATS = {"A": chat_a6, "B": chat_b6}


def chat_slide(text: str, make_chat) -> tuple[Image.Image, tuple]:
    """Скрин чата, переписка прижата к строке ввода; подпись — в чёрной полосе под шапкой, не задевая пузыри.
    Длинной подписи не хватает места на 1440 — рендерим скрин на «высокий телефон» и целиком уменьшаем до 1440:
    фон чата чёрный, поля по бокам не видны. Берём самое слабое уменьшение, при котором кегль подписи ≥ 44."""
    chat = make_chat(0)
    for hh in range(H, 2000, 40):
        k = H / hh
        shot = R.render(chat, hh, full=True, anchor="bottom")
        sw = round(W * k)
        bg = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        ox = (W - sw) // 2
        bg.paste(shot.resize((sw, H), Image.Resampling.LANCZOS), (ox, 0))
        top = max(int(R.render.header_bottom * k) + 20, Y0)
        first = min(int(R.render.marks["top"] * k) - 20, Y1)
        if first - top < 200 or not C.fits(text, 44, first - top, X1 - X0):
            continue
        block = C.block_for(text, first - top, X1 - X0)
        x, y = (W - block.width) // 2, (top + first) // 2 - block.height // 2
        box = (x, y, x + block.width, y + block.height)
        boxes = [(ox + b[0] * k, b[1] * k, ox + b[2] * k, b[3] * k) for b in R.render.boxes]
        if any(b[3] > R.render.header_bottom * k and D.overlaps(box, b) for b in boxes):
            continue
        bg.alpha_composite(block, (x, y))
        return bg.convert("RGB"), box
    raise SystemExit("подпись не помещается над перепиской")


# ---------------------------------------------------------------- сборка
def pool(k: str) -> list[Path]:
    d = SL / k
    return sorted(f for f in d.glob("*.jpg") if not f.name.startswith("_")) if d.is_dir() else []


def build(story: str, i: int, rng: random.Random, picks: list, game: tuple) -> tuple[list[Image.Image], list[list]]:
    code, t = game
    shot = game_frame(code, t)
    title = GAMES[code]
    out, boxes = [], []
    for k, text in enumerate(TEXTS[story]):
        if k == CHAT[story]:
            p = plan_chat(rng)
            im, box = chat_slide(text, lambda hist: CHATS[story](p, shot, title, hist))
            out.append(im)
            boxes.append([box])
            continue
        photo = Image.open(picks[k]).convert("RGB")
        band = BANDS[story][k]
        if k == 4:                                               # экран вписываем в ×2 от финального кадра
            raw = frame(photo, rng, 2)
            sb = float(screen_quad(yellow_mask(raw))[:, 1].max()) / raw.height
            if band[0] < 0.5 < band[1]:                          # подпись под экраном — ниже его края, не на игре
                band = (max(band[0], sb + 0.025), band[1])
            big = put_screen(raw, shot, rng)
            im = grade(big.resize((W, H), Image.Resampling.LANCZOS), rng).convert("RGBA")
        else:
            im = grade(frame(photo, rng), rng).convert("RGBA")
        layer, box = caption(text, *band, rng)
        out.append(Image.alpha_composite(im, layer).convert("RGB"))
        boxes.append([box])
    return out, boxes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", default="A", choices=list(TEXTS))
    ap.add_argument("-n", type=int, default=4)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_noid.jpg")
    ap.add_argument("--seed", type=int, default=47)
    ap.add_argument("--qa", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    st = a.story.lower()
    pools = [pool(f"{st}{k + 1}") for k in range(6)]
    for k, pl in enumerate(pools):
        if not pl and k != CHAT[a.story]:
            raise SystemExit(f"нет фото для слайда {k + 1}: {SL / f'{st}{k + 1}'}")
    rng0 = random.Random(a.seed)
    combos = list(itertools.product(*[range(len(pl)) if pl else [None] for pl in pools]))   # свой набор кадров
    rng0.shuffle(combos)
    games = []                                                      # своя игра и момент у каждой карусели
    codes = list(GAME_T)
    for i in range(a.n):
        code = codes[i % len(codes)]
        games.append((code, round(rng0.uniform(*GAME_T[code]), 2)))
    rng0.shuffle(games)
    a.out.mkdir(parents=True, exist_ok=True)
    manifest, qa = [], []
    for i in range(1, a.n + 1):
        rng = random.Random(a.seed * 1000 + i)
        picks = [pl[j] if pl else None for pl, j in zip(pools, combos[(i - 1) % len(combos)])]
        slides, boxes = build(a.story, i, rng, picks, games[i - 1])
        d = a.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, (im, bx) in enumerate(zip(slides, boxes)):
            for b in bx:
                if bad := check_box(W, H, b):
                    raise SystemExit(f"{i:03d} слайд {k + 1}: вне безопасной зоны {b} — {bad}")
            im.save(d / f"{k + 1}.jpg", quality=93)
            if a.qa and i <= 2:
                q = draw_overlay(im)
                for b in bx:
                    ImageDraw.Draw(q).rectangle(b, outline=(255, 220, 0), width=5)
                qa.append(q)
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d / f"{k + 1}.jpg", a.flat / f"sort_{k + 1}_{i}_noid.jpg")
        manifest.append({"carousel": d.name, "photos": [p.name if p else None for p in picks], "game": games[i - 1]})
        print(f"  {d.name}", flush=True)
    if qa:
        tw, th = 300, 400
        sheet = Image.new("RGB", (6 * tw, (len(qa) // 6) * th), (30, 30, 30))
        for j, q in enumerate(qa):
            sheet.paste(q.resize((tw, th)), ((j % 6) * tw, (j // 6) * th))
        sheet.save(a.out / "_qa.jpg", quality=86)
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    sys.argv = ["strip", str(a.out)] + ([str(a.flat)] if a.flat else [])
    strip_jpeg_meta.main()
    print(f"готово: {a.n} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
