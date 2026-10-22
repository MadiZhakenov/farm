#!/usr/bin/env python3
"""
1285 — UNO Mobile POV с очков-камеры: уникализация готовых роликов клиента (downloads/dropbox_8k3sofvt,
локации Airport / Office / Restaurant / Subway; в каждом ролике один вшитый текст «POV: …» сверху).

  h1 — один ролик режем ровно пополам или ровно на 3 части и переставляем (см. «Гипотеза 1» ниже):
       группа 1 — длина как у ролика, группа 2 (h1s) — ролик ≤ 10 с. Ролики — сплошные дубли, поэтому точки реза выбираем сами:
       стык должен выглядеть как монтаж (кадры по разные стороны заметно отличаются), а не как «дёрнулось».
  h2 — нарезка из разных роликов одной локации (разные видеоряды); вшитые тексты у них разные, поэтому
       сверху белая плашка (TikTok-стиль, чёрный текст) с одним текстом той же локации — дословно с роликов.
  h3 — в ролик вставляем 1 кадр (видео-пин Pinterest той же локации) вместо куска того же ролика:
       вшитый текст вырезаем маской из оригинала и кладём поверх всего ролика — на вставке он тоже есть.

Звук: в Airport/Office — музыка с битом, её не режем: идёт целиком с начала (h1/h3 — родная, h2 — от одного
из роликов нарезки), склейки видео ставим на удары. Restaurant/Subway — без музыки (тишина / шум).
Каждому ролику — лёгкий сдвиг яркости/контраста/насыщенности, метаданные стираются.
Текст плашки — внутри безопасной зоны 9:16 (docs/SAFE_ZONES.md, core/safe_zones.py).

  python build_1285_remix.py h1 --count 500 --out output/1285_500_h1 --jobs 5
  python build_1285_remix.py h1s --count 500 --out output/1285_500_h1_10s --jobs 5
  python build_1285_remix.py h2 --count 500 --out output/1285_500_h2 --jobs 5   # h2_NNN_1285.mp4
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import check_box, draw_overlay  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
SRC = ROOT / "downloads" / "dropbox_8k3sofvt"
PIN = ROOT / "downloads" / "1285" / "pinterest"
CACHE = ROOT / "output" / "1285" / "_cache"
ID = "1285"
W, H, FPS = 1080, 1920, 30
FONT = ROOT / "fonts" / "TikTokSans-SemiBold.ttf"
TXT_Y0, TXT_Y1 = 280, 640                 # полоса, где во всех роликах стоит вшитый текст
MIN_PART = 1.4                            # h1: минимальная длина куска, с

# Тексты роликов — дословно с кадров (фигурные апострофы/кавычки как в оригинале).
# Subway_V4: в оригинале перенос «they’re t / aking» — это сбой переноса, слово «taking».
TEXTS = {
    "Airport/Uno_Chair_V1": "POV: you got to the airport way too early",
    "Airport/Uno_Chair_V2": "POV: you and your friends have been waiting to board forever",
    "Airport/Uno_Chair_V3": "POV: your flight isn’t for another 3 hours",
    "Airport/Uno_Chair_V4": "POV: when you have way too much time before boarding",
    "Airport/Uno_Chair_V5": "POV: you have nothing to do until your flight",
    "Airport/Uno_Chair_V6": "POV: you and your friends found a way to kill time",
    "Airport/Uno_Chair_V7": "POV: waiting for your flight just got competitive",
    "Airport/Uno_Chair_V8": "POV: you missed your flight and now you have all day to play UNO",
    "Airport/Uno_Chair_V9": "POV: your gate isn’t opening anytime soon",
    "Airport/Uno_Chair_V10": "POV: you’ve been waiting at the gate forever",
    "Airport/Uno_Chair_V11": "POV: boarding time is taking forever",
    "Airport/Uno_Chair_V12": "POV: you arrived early and came prepared",
    "Airport/Uno_Chair_V13": "POV: your flight isn’t for another 3 hours",
    "Airport/Uno_Chair_V14": "POV: when you have way too much time before boarding",
    "Airport/Uno_Chair_V15": "POV: waiting for your flight just got competitive",
    "Airport/Uno_Solo_V1": "POV: waiting at the airport takes forever",
    "Airport/Uno_Solo_V2": "POV: your layover is way too long",
    "Airport/Uno_Solo_V3": "POV: when your flight is delayed again",
    "Airport/Uno_Solo_V4": "POV: you have 4 hours to kill at the airport",
    "Airport/Uno_Solo_V5": "POV: when you have nothing to do before your flight",
    "Airport/Uno_Solo_V6": "POV: your layover just got a little more fun",
    "Airport/Uno_Solo_V7": "POV: when you have way too much time before boarding",
    "Airport/Uno_Solo_V8": "POV: trying to survive a 5-hour layover",
    "Airport/Uno_Solo_V9": "POV: you got to the airport way too early",
    "Airport/Uno_Solo_V10": "POV: finding something to do while waiting for your flight",
    "Airport/Uno_Solo_V11": "POV: waiting at the airport takes forever",
    "Airport/Uno_Solo_V12": "POV: your layover is way too long",
    "Airport/Uno_Solo_V13": "POV: when your flight is delayed again",
    "Airport/Uno_Solo_V14": "POV: you have 4 hours to kill at the airport",
    "Airport/Uno_Solo_V15": "POV: when you have nothing to do before your flight",
    "Airport/Uno_Solo_V16": "POV: your layover just got a little more fun",
    "Airport/Uno_Solo_V17": "POV: when you have way too much time before boarding",
    "Airport/Uno_Solo_V18": "POV: trying to survive a 5-hour layover",
    "Airport/Uno_Solo_V19": "POV: when you have way too much time before boarding",
    "Airport/Uno_Solo_V20": "POV: trying to survive a 5-hour layover",
    "Airport/Uno_Solo_V21": "POV: you got to the airport way too early",
    "Airport/Uno_Solo_V22": "POV: finding something to do while waiting for your flight",
    "Airport/Uno_Solo_V23": "POV: waiting at the airport takes forever",
    "Airport/Uno_Solo_V24": "POV: your layover is way too long",
    "Airport/Uno_Solo_V25": "POV: when your flight is delayed again",
    "Airport/Uno_Solo_V26": "POV: you have 4 hours to kill at the airport",
    "Airport/Uno_Solo_V27": "POV: when you have nothing to do before your flight",
    "Airport/Uno_Solo_V28": "POV: your layover just got a little more fun",
    "Airport/Uno_Solo_V29": "POV: when you have way too much time before boarding",
    "Airport/Uno_Solo_V30": "POV: trying to survive a 5-hour layover",
    "Airport/Uno_Walk_V1": "POV: everyone at the airport is playing UNO Mobile",
    "Airport/Uno_Walk_V2": "POV: the whole airport is obsessed with UNO Mobile",
    "Airport/Uno_Walk_V3": "POV: everyone around you is playing UNO Mobile",
    "Airport/Uno_Walk_V4": "POV: you walk through the airport and everyone is playing UNO Mobile",
    "Airport/Uno_Walk_V5": "POV: UNO Mobile is everywhere at the airport",
    "Airport/Uno_Walk_V6": "POV: you can’t go anywhere without seeing someone play UNO Mobile",
    "Airport/Uno_Walk_V7": "POV: the airport has become an UNO tournament",
    "Airport/Uno_Walk_V8": "POV: you thought you were the only one playing UNO Mobile",
    "Airport/Uno_Walk_V9": "POV: you’re surrounded by UNO players",
    "Airport/Uno_Walk_V10": "POV: you keep spotting people playing UNO Mobile",
    "Airport/Uno_Walk_V11": "POV: everyone found a way to kill time at the airport",
    "Airport/Uno_Walk_V12": "POV: the airport is full of UNO players",
    "Airport/Uno_Walk_V13": "POV: you can’t go anywhere without seeing someone play UNO Mobile",
    "Airport/Uno_Walk_V14": "POV: the airport has become an UNO tournament",
    "Airport/Uno_Walk_V15": "POV: you thought you were the only one playing UNO Mobile",
    "Office/V1": "POV: the whole office is obsessed with UNO! Mobile",
    "Office/V2": "POV: you and your coworkers are “working”",
    "Office/V3": "POV: everyone in the office is secretly playing UNO! Mobile",
    "Office/V4": "POV: your coworkers take UNO very seriously",
    "Office/V5": "POV: nobody in the office is actually working",
    "Office/V6": "POV: you came to work but everyone is playing UNO! Mobile",
    "Office/V7": "POV: UNO is the most important thing at the office",
    "Office/V8": "POV: nobody in the office is actually working",
    "Office/V9": "POV: you found out your coworkers are all playing UNO",
    "Office/V10": "POV: your coworkers have a very important meeting",
    "Office/V11": "POV: when the whole office is addicted to UNO",
    "Office/V12": "POV: UNO is the most important thing at the office",
    "Restaurant/Restaurant_V1": "POV: you and your date can’t stop playing UNO! Mobile",
    "Restaurant/Restaurant_V2": "POV: you came here for dinner",
    "Restaurant/Restaurant_V3": "POV: the food is right there but you have a game to finish",
    "Restaurant/Restaurant_V4": "POV: your date is getting competitive",
    "Restaurant/Restaurant_V5": "POV: dinner can wait",
    "Restaurant/Restaurant_V6": "POV: you’re both ignoring the food because of UNO Mobile",
    "Restaurant/Restaurant_V7": "POV: when your date turns into an UNO Mobile tournament",
    "Restaurant/Restaurant_V8": "POV: you both forgot you were supposed to be on a date",
    "Restaurant/Restaurant_V9": "POV: the date is going great… except nobody is eating",
    "Restaurant/Restaurant_V10": "POV: your friends start eating your food because you’re too busy playing UNO Mobile",
    "Restaurant/Restaurant_V11": "POV: you’re fighting for your life in UNO Mobile while they’re eating your dinner",
    "Restaurant/Restaurant_V12": "POV: they saw you playing UNO Mobile and knew your food was free",
    "Restaurant/Restaurant_V13": "POV: you’re too busy playing UNO Mobile to protect your food",
    "Restaurant/Restaurant_V14": "POV: your friends know you won’t stop playing",
    "Restaurant/Restaurant_V15": "POV: you chose UNO Mobile over your food and they took advantage",
    "Restaurant/Restaurant_V16": "POV: you can’t stop playing UNO Mobile",
    "Restaurant/Restaurant_V17": "POV: you said “one game before we eat”",
    "Restaurant/Restaurant_V18": "POV: you’re not eating until you beat your friends",
    "Restaurant/Restaurant_V19": "POV: nobody wants to put UNO Mobile down",
    "Restaurant/Restaurant_V20": "POV: dinner can wait, we have a game to finish",
    "Restaurant/Restaurant_V21": "POV: you came for brunch but started playing UNO Mobile",
    "Restaurant/Restaurant_V22": "POV: you and your friends take UNO Mobile way too seriously",
    "Restaurant/Restaurant_V23": "POV: “one more game” turned into this",
    "Restaurant/Restaurant_V24": "POV: the food is getting cold but nobody cares",
    "Restaurant/Restaurant_V25": "POV: you and your friends have one tiny problem… you can’t stop playing",
    "Restaurant/Restaurant_V26": "POV: you forgot you came here to eat",
    "Restaurant/Restaurant_V27": "POV: your friends refuse to let you win",
    "Restaurant/Restaurant_V28": "POV: the food arrived at the worst possible time",
    "Restaurant/Restaurant_V29": "POV: nobody is touching their food until someone wins",
    "Restaurant/Restaurant_V30": "POV: you and your friends completely forgot about dinner",
    "Subway/Subway_V1": "Hope she doesn’t miss his stop",
    "Subway/Subway_V2": "Bro is way too locked in",
    "Subway/Subway_V3": "He’s definitely missing his stop",
    "Subway/Subway_V4": "POV: you see someone playing UNO! Mobile and they’re taking WAY too long",
    "Subway/Subway_V5": "POV: when the person next to you is taking forever to make a move",
    "Subway/Subway_V6": "Me pretending I’m not watching",
    "Subway/Subway_V7": "Bro has no idea I’m watching",
    "Subway/Subway_V8": "I really hope he wins",
    "Subway/Subway_V9": "POV: when you know exactly what move they should make",
    "Subway/Subway_V10": "POV: he’s taking FOREVER",
    "Subway/Subway_V11": "I’m emotionally invested in a stranger’s UNO! Mobile game",
    "Subway/Subway_V12": "That was definitely not the move I would’ve made",
    "Subway/Subway_V13": "She really chose THAT card?",
    "Subway/Subway_V14": "POV: bro was taking too long so I had to help",
    "Subway/Subway_V15": "Bro was running out of time",
    "Subway/Subway_V16": "Okay, I would’ve played a different card",
    "Subway/Subway_V17": "Watching someone play UNO! Mobile is stressful",
    "Subway/Subway_V18": "POV: you spot someone playing UNO! Mobile on the subway",
    "Subway/Subway_V19": "POV: someone’s playing UNO! Mobile on the subway",
    "Subway/Subway_V20": "Why am I rooting for him",
    "Subway/Subway_V21": "I definitely need to see one more round",
}

# Видео-пины Pinterest для h3 (отобраны вручную: та же локация, без надписей и вотермарок)
# Гипотеза 3: живые видео с Pinterest той же локации, отобранные вручную (harvest_pin_videos.py --profile 1285_<loc>
# … --pick N,N) — файлы NN_<pin>.mp4 в папках кандидатов.
PIN_DIRS = {"Airport": ["airport/cands"], "Restaurant": ["restaurant/cands", "restaurant/cands2"],
            "Subway": ["subway/cands"], "Office": ["office/cands", "office/cands2"]}


def pins_for(loc: str) -> list[Path]:
    return sorted(f for d in PIN_DIRS.get(loc, []) for f in (PIN / d).glob("[0-9][0-9]_*.mp4"))


def key_of(p: Path) -> str:
    m = re.search(r"_V(\d+)", p.name)
    if p.parent.name == "Office":
        return f"Office/V{m.group(1)}"
    return f"{p.parent.name}/{p.stem}"


# ---------------- анализ исходников (кэш) ----------------
def probe_dur(p: Path) -> float:
    return float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)


_THUMBS: dict[Path, np.ndarray] = {}


def thumbs(p: Path) -> np.ndarray:
    """Серые миниатюры 30 к/с без верхней трети (там текст) — для стыков и похожести кадров (кэш в памяти)."""
    if p in _THUMBS:
        return _THUMBS[p]
    c = CACHE / "thumbs" / (key_of(p).replace("/", "_") + ".npy")
    if c.exists():
        _THUMBS[p] = np.load(c).astype(np.float32)
        return _THUMBS[p]
    raw = subprocess.run([FF, "-v", "error", "-i", str(p), "-vf", f"fps={FPS},scale=54:96", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, 96, 54)[:, 32:].astype(np.float32)
    v = v - v.mean((1, 2), keepdims=True)
    v /= v.std((1, 2), keepdims=True) + 1e-6
    c.parent.mkdir(parents=True, exist_ok=True)
    np.save(c, v.astype(np.float16))
    return v


def frame_corr(a: np.ndarray, b: np.ndarray) -> float:
    return float((a.astype(np.float32) * b.astype(np.float32)).mean())


def text_layer(p: Path) -> tuple[list[int], np.ndarray, np.ndarray]:
    """Вшитый текст: белая заливка стабильно светлая во всех кадрах, обводка стабильно тёмная.
    Возвращает рамку текста и RGBA-маску полосы TXT_Y0..TXT_Y1 (цвет — медиана по времени)."""
    raw = subprocess.run([FF, "-v", "error", "-i", str(p), "-vf", f"fps=12,crop={W}:{TXT_Y1 - TXT_Y0}:0:{TXT_Y0}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, TXT_Y1 - TXT_Y0, W, 3)
    lum = v.mean(3)
    p5, p95, std = np.percentile(lum, 5, axis=0), np.percentile(lum, 95, axis=0), lum.std(0)
    fill0 = p5 > 190
    stroke0 = p95 < 90
    near_stroke = cv2.dilate(stroke0.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    fill = fill0 & near_stroke                               # белое без тёмной обводки рядом — это фон, не текст
    fill = cv2.morphologyEx(fill.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)) > 0
    ys, xs = np.where(fill)
    if len(ys) < 50:
        raise SystemExit(f"{p.name}: не нашёл вшитый текст")
    box = [int(xs.min()) - 6, int(ys.min()) + TXT_Y0 - 6, int(xs.max()) + 6, int(ys.max()) + TXT_Y0 + 6]
    near = cv2.dilate(fill.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))) > 0
    near2 = cv2.dilate(fill.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    core = (fill | (stroke0 & near) | ((std < 14) & near2)).astype(np.uint8)
    core = cv2.morphologyEx(core, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    alpha = (np.clip(cv2.GaussianBlur(core.astype(np.float32), (3, 3), 0.8), 0, 1) * 255).astype(np.uint8)
    return box, np.median(v, axis=0).astype(np.uint8), alpha


def onsets(p: Path) -> list[float]:
    """Удары музыки (пики роста энергии), с. Пусто, если звука нет."""
    raw = subprocess.run([FF, "-v", "error", "-i", str(p), "-ac", "1", "-ar", "11025", "-f", "s16le", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    if len(a) < 11025 or np.sqrt((a ** 2).mean()) < 0.003:
        return []
    hop = 256
    n = len(a) // hop
    e = np.log(np.array([(a[i * hop:(i + 1) * hop] ** 2).sum() for i in range(n)]) + 1e-6)
    flux = np.maximum(0, np.diff(e, prepend=e[0]))
    th = flux.mean() + 1.5 * flux.std()
    out, last = [], -1.0
    for i in range(1, n - 1):
        t = i * hop / 11025
        if flux[i] > th and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1] and t - last > 0.22:
            out.append(round(t, 3))
            last = t
    return out


@dataclass
class Src:
    key: str
    path: Path
    loc: str
    dur: float
    music: bool
    box: list[int]
    beats: list[float]


def catalog() -> dict[str, Src]:
    cj = CACHE / "catalog.json"
    if cj.exists():
        d = json.loads(cj.read_text(encoding="utf-8"))
        return {k: Src(k, Path(v["path"]), v["loc"], v["dur"], v["music"], v["box"], v["beats"]) for k, v in d.items()}
    CACHE.mkdir(parents=True, exist_ok=True)
    out = {}
    for p in sorted(SRC.glob("*/*.mp4")):
        k = key_of(p)
        box, rgb, alpha = text_layer(p)
        m = np.zeros((H, W, 4), np.uint8)
        m[TXT_Y0:TXT_Y1, :, :3], m[TXT_Y0:TXT_Y1, :, 3] = rgb, alpha
        (CACHE / "matte").mkdir(exist_ok=True)
        Image.fromarray(m, "RGBA").save(CACHE / "matte" / (k.replace("/", "_") + ".png"))
        b = onsets(p)
        out[k] = Src(k, p, p.parent.name, probe_dur(p), len(b) > 4 and p.parent.name in ("Airport", "Office"), box, b)
        thumbs(p)
        print(f"{k}: {out[k].dur:.1f} с, текст {box}, ударов {len(b)}", flush=True)
    cj.write_text(json.dumps({k: {"path": str(s.path), "loc": s.loc, "dur": s.dur, "music": s.music, "box": s.box,
                                  "beats": s.beats} for k, s in out.items()}, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def snap(t: float, beats: list[float], win: float = 0.2) -> float:
    if beats:
        b = min(beats, key=lambda x: abs(x - t))
        if abs(b - t) <= win:
            t = b
    return round(t * FPS) / FPS


# ---------------- оверлеи ----------------
PLATE_PX, PLATE_TOP, PAD_X, PAD_Y = 58, 294, 36, 22
FIT_M, FIT_TOL_X, FIT_TOL_Y = 10, 30, 12     # куски берём, только если их вшитый текст влезает под плашку текста


def plate_layout(text: str, max_w: float = 740, n_lines: int | None = None
                 ) -> tuple[list[str], float, int, list[float], int]:
    """Строки (ровный перенос), ширина/высота текста, «родная» рамка плашки и кегль. n_lines — сколько строк
    у вшитого текста первого клипа: если наш перенос даёт больше, чуть уменьшаем кегль (до 48), чтобы строк
    было столько же и плашка не раздувалась по ширине оригинала."""
    ss = 2
    for px in range(PLATE_PX, 47, -1):
        font = ImageFont.truetype(str(FONT), px * ss)

        def greedy(limit: float) -> list[str]:
            out, cur = [], ""
            for w in text.split():
                c = (cur + " " + w).strip()
                if cur and font.getlength(c) > limit:
                    out.append(cur)
                    cur = w
                else:
                    cur = c
            return out + [cur]

        lines = greedy(max_w * ss)
        if n_lines is None or len(lines) <= n_lines:
            break
    lo, hi = 150.0 * ss, max_w * ss          # то же число строк, но ровнее — без одинокого слова внизу
    while hi - lo > 2:
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if len(greedy(mid)) <= len(lines) else (mid, hi)
    lines = greedy(hi)
    tw = max(font.getlength(x) for x in lines) / ss
    th = int(px * 1.24) * len(lines)
    rect = [W / 2 - tw / 2 - PAD_X, PLATE_TOP, W / 2 + tw / 2 + PAD_X, PLATE_TOP + th + 2 * PAD_Y]
    return lines, tw, th, rect, px


def box_lines(box: list[int]) -> int:
    """Сколько строк во вшитом тексте (по высоте рамки: строка ≈ 77 px, рамка с запасом 6 px)."""
    return max(1, round((box[3] - box[1] - 12 - 58) / 77) + 1)


def fits_plate(box: list[int], rect: list[float]) -> bool:
    return (box[0] - FIT_M >= rect[0] - FIT_TOL_X and box[2] + FIT_M <= rect[2] + FIT_TOL_X
            and box[1] - FIT_M >= rect[1] - FIT_TOL_Y and box[3] + FIT_M <= rect[3] + FIT_TOL_Y)


def plate_png(text: str, under: list[list[int]], dest: Path, max_w: float = 740, n_lines: int | None = None) -> dict:
    """Белая скруглённая плашка с чёрным текстом по размеру текста; чуть растёт, только чтобы закрыть
    вшитые тексты кусков (under) — куски заранее подобраны так, что их тексты под неё влезают."""
    ss = 2
    lines, tw, th, (x0, y0, x1, y1), px = plate_layout(text, max_w, n_lines)
    font = ImageFont.truetype(str(FONT), px * ss)
    adv = int(px * 1.24)
    m = FIT_M
    ux0, uy0 = min(b[0] for b in under), min(b[1] for b in under)
    ux1, uy1 = max(b[2] for b in under), max(b[3] for b in under)
    x0, x1 = min(x0, ux0 - m), max(x1, ux1 + m)
    half = min(max(W / 2 - x0, x1 - W / 2), W / 2 - 16)
    x0, x1 = W / 2 - half, W / 2 + half
    y0, y1 = min(y0, uy0 - m), max(y1, uy1 + m)
    ty = (y0 + y1) / 2 - th / 2
    img = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0 * ss, y0 * ss, x1 * ss, y1 * ss], radius=24 * ss, fill=(255, 255, 255, 255))
    for i, ln in enumerate(lines):
        d.text((W / 2 * ss, (ty + (i + 0.5) * adv) * ss), ln, font=font, fill=(0, 0, 0, 255), anchor="mm")
    img = img.resize((W, H), Image.Resampling.LANCZOS)
    img.save(dest)
    tbox = (int(W / 2 - tw / 2), int(ty), int(W / 2 + tw / 2), int(ty + th))
    bad = check_box(W, H, tbox)
    if bad:
        raise SystemExit(f"текст плашки вне безопасной зоны: {bad}")
    covered = x0 <= ux0 - 6 and x1 >= ux1 + 6 and y0 <= uy0 - 6 and y1 >= uy1 + 6
    if not covered:
        raise SystemExit(f"плашка не закрывает вшитый текст: плашка {(x0, y0, x1, y1)}, тексты {(ux0, uy0, ux1, uy1)}")
    return {"plate": [int(x0), int(y0), int(x1), int(y1)], "text_box": list(tbox), "lines": lines, "px": px}


# ---------------- рендер ----------------
def jitter(rng: np.random.Generator) -> str:
    return (f"eq=brightness={rng.uniform(-0.025, 0.025):.3f}:contrast={rng.uniform(0.97, 1.03):.3f}:"
            f"saturation={rng.uniform(0.94, 1.07):.3f}")


def render(segs: list[tuple[Path, float, float]], audio: tuple[Path, float] | None, overlay: Path | None,
           dest: Path, eqf: str) -> float:
    """segs — куски видео (файл, начало, конец) по порядку; audio — (файл, длительность) звук целиком с 0;
    overlay — PNG во весь кадр поверх; eqf — лёгкий сдвиг цвета. Пишем во временный файл, потом переименовываем."""
    part = dest.with_name(dest.stem + ".part.mp4")
    args, chains = [FF, "-v", "error", "-y"], []
    for i, (p, a, b) in enumerate(segs):
        args += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(p)]
        chains.append(f"[{i}:v]fps={FPS},scale={W}:{H}:flags=lanczos:force_original_aspect_ratio=increase,"
                      f"crop={W}:{H},setsar=1,setpts=PTS-STARTPTS,format=yuv420p[v{i}]")
    total = sum(b - a for _, a, b in segs)
    n = len(segs)
    concat = "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[cat]"
    fc = ";".join(chains) + ";" + concat + f";[cat]{eqf}[j]"
    k = n
    if overlay:
        args += ["-i", str(overlay)]
        fc += f";[j][{k}:v]overlay=0:0:format=auto[o]"
        k += 1
    else:
        fc += ";[j]null[o]"
    fc += f";[o]format=yuv420p,{SET_SDR}[v]"
    if audio:
        a_from = audio[2] if len(audio) > 2 else 0.0
        args += ["-ss", f"{a_from:.3f}", "-t", f"{total:.3f}", "-i", str(audio[0])]
        fc += f";[{k}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={max(0, total - 0.15):.3f}:d=0.15[a]"
    else:
        args += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
        fc += f";[{k}:a]anull[a]"
    args += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
             *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "128k", "-map_metadata", "-1", "-map_chapters", "-1",
             "-movflags", "+faststart", "-t", f"{total:.3f}", str(part)]
    subprocess.run(args, check=True)
    part.replace(dest)
    return total


JOBS: list[tuple] = []          # (segs, audio, overlay, dest, eqf) — план считаем последовательно, рендер параллельно


def run_jobs(jobs: int, force: bool = False) -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    todo = [j for j in JOBS if force or not j[3].exists()]   # уже готовые (после обрыва) не пересобираем
    print(f"рендер: {len(todo)} из {len(JOBS)} (готовых {len(JOBS) - len(todo)}), потоков {jobs}", flush=True)
    done = 0
    with ThreadPoolExecutor(jobs) as ex:
        futs = [ex.submit(render, *j) for j in todo]
        for f in as_completed(futs):
            f.result()
            done += 1
            if done % 25 == 0 or done == len(todo):
                print(f"  готово {done}/{len(todo)}", flush=True)


# ---------------- гипотезы ----------------
# Гипотеза 1 — ровные части одного ролика (правило клиента): ровно пополам или ровно на 3 равные части, перемешать.
#   группа 1 (h1)  — ролик целиком, длина как у оригинала;
#   группа 2 (h1s) — ролик ≤ 10 с: 2 куска по 5 с или 3 по 3.33 с. Ролики до 10 с делятся целиком
#                    (то же, что в группе 1 — поэтому их варианты делим между группами без повторов),
#                    из длинных берём 10-секундное окно в разных местах (шаг 1.5 с) и делим его ровно.
# Порядки: BA; BAC, CBA (сильные); ACB, BCA, CAB (слабые: начало как у оригинала или две трети подряд) —
# слабым даём лёгкий наезд 5 % и свой сдвиг цвета. ABC «как было» не бывает.
EQ_ORDERS = {"BA": [1, 0], "BAC": [1, 0, 2], "CBA": [2, 1, 0], "ACB": [0, 2, 1], "BCA": [1, 2, 0], "CAB": [2, 0, 1]}
WEAK = {"ACB", "BCA", "CAB"}
EQ_TH3 = 4.5                    # короче — только пополам (кусок трети < 1.5 с)
G2_MAX, G2_STEP = 10.0, 1.5     # группа 2: окно 10 с, сдвиг окна 1.5 с
ZOOM = f"scale={round(W * 1.05 / 2) * 2}:{round(H * 1.05 / 2) * 2},crop={W}:{H}"   # наезд 5 % от центра
GROUP_N = 500


def eq_parts(a: float, b: float, k: int) -> list[tuple[float, float]]:
    n = round((b - a) * FPS)
    e = [a + round(n * i / k) / FPS for i in range(k + 1)]
    return [(e[i], e[i + 1]) for i in range(k)]


def eq_variants(a: float, b: float) -> list[tuple[str, list[tuple[float, float]]]]:
    """Все ровные перестановки отрезка [a, b]: пополам — BA, на трети — 5 порядков (если трети не короче 1.5 с)."""
    h = eq_parts(a, b, 2)
    out = [("BA", [h[i] for i in EQ_ORDERS["BA"]])]
    if b - a >= EQ_TH3:
        t = eq_parts(a, b, 3)
        out += [(nm, [t[i] for i in EQ_ORDERS[nm]]) for nm in ("BAC", "CBA", "ACB", "BCA", "CAB")]
    return out


def same_video_text(cat: dict[str, Src]) -> dict[str, str]:
    """Файлы «то же видео + тот же текст» (у клиента бывают перевыгрузки с другим цветом) → один ключ."""
    keys = sorted(cat)
    canon = {k: k for k in keys}
    for i, a in enumerate(keys):
        if canon[a] != a:
            continue
        ta = thumbs(cat[a].path).astype(np.float32)
        for b in keys[i + 1:]:
            if cat[b].loc != cat[a].loc or TEXTS[b] != TEXTS[a] or canon[b] != b:
                continue
            tb = thumbs(cat[b].path).astype(np.float32)
            n = min(len(ta), len(tb))
            if abs(len(ta) - len(tb)) <= 2 and float((ta[:n:6] * tb[:n:6]).mean()) > 0.8:
                canon[b] = a
    return canon


def round_robin(groups: list[list], need: int) -> tuple[list, list]:
    """Берём по одному из каждой группы по кругу, пока не наберём need; возвращаем (взятые, остаток)."""
    taken, groups = [], [list(g) for g in groups]
    while len(taken) < need and any(groups):
        for g in groups:
            if g and len(taken) < need:
                taken.append(g.pop(0))
    return taken, [x for g in groups for x in g]


def allocate(cat: dict[str, Src], seed: int) -> tuple[list[dict], list[dict]]:
    """Делим все ровные варианты между группами без повторов (детерминированно — обе группы считают одно и то же)."""
    rng = np.random.default_rng(seed)
    canon = same_video_text(cat)
    keys = sorted(set(canon.values()))
    dur = {k: len(thumbs(cat[k].path)) / FPS for k in keys}

    def mk(k: str, nm: str, parts: list, win: float | None = None) -> dict:
        return {"src": k, "order": nm, "parts": parts, "weak": nm in WEAK, "window": win}

    long_k = [k for k in keys if dur[k] > G2_MAX]
    short_k = [k for k in keys if dur[k] <= G2_MAX]
    g1 = [mk(k, nm, pr) for k in long_k for nm, pr in eq_variants(0.0, dur[k])]          # длинные целиком — только в г1
    strong, weak = [], []
    for k in short_k:
        v = [mk(k, nm, pr) for nm, pr in eq_variants(0.0, dur[k])]
        strong += [x for x in v if not x["weak"]]
        w = [x for x in v if x["weak"]]
        weak.append([w[i] for i in rng.permutation(len(w))])
    g1 += strong
    more, short_left = round_robin(weak, GROUP_N - len(g1))                               # слабые — поровну по роликам
    g1 += more
    win_groups = []
    for k in long_k:
        n_win = int((dur[k] - G2_MAX) / G2_STEP + 1e-6) + 1
        v = [mk(k, nm, pr, round(i * G2_STEP, 2)) for i in range(n_win)
             for nm, pr in eq_variants(i * G2_STEP, i * G2_STEP + G2_MAX)]
        v = [v[i] for i in rng.permutation(len(v))]
        v.sort(key=lambda x: x["weak"])                                                  # сначала сильные порядки
        win_groups.append(v)
    wins, _ = round_robin(win_groups, GROUP_N - len(short_left))
    g2 = short_left + wins
    g1 = [g1[i] for i in rng.permutation(len(g1))][:GROUP_N]
    g2 = [g2[i] for i in rng.permutation(len(g2))][:GROUP_N]
    seen = {(x["src"], tuple(map(tuple, x["parts"]))) for x in g1}
    assert not any((x["src"], tuple(map(tuple, x["parts"]))) in seen for x in g2), "повтор между группами"
    return g1, g2


def run_eq(cat: dict[str, Src], out: Path, seed: int, group: int, count: int) -> list[dict]:
    g = allocate(cat, seed)[group - 1][:count]
    rng = np.random.default_rng(seed + group)
    tag = "h1" if group == 1 else "h1s"
    rep = []
    for n, v in enumerate(g, 1):
        s = cat[v["src"]]
        dest = out / f"{ID}_{tag}_{n:04d}.mp4"
        eqf = (ZOOM + "," if v["weak"] else "") + jitter(rng)
        JOBS.append(([(s.path, a, b) for a, b in v["parts"]], (s.path, s.dur), None, dest, eqf))   # родной звук с 0
        total = sum(b - a for a, b in v["parts"])
        rep.append({"file": dest.name, **{k: v[k] for k in ("src", "order", "weak", "window")},
                    "parts": [[round(a, 3), round(b, 3)] for a, b in v["parts"]], "total": round(total, 2)})
    print(f"группа {group}: {len(rep)} роликов, слабых порядков (с наездом) {sum(r['weak'] for r in rep)}", flush=True)
    return rep


# Гипотеза 2 — нарезка из разных роликов одной папки (локации), 10 с: 2 клипа по 5 с или 3 по 3.33 с.
# Текст — первого клипа (дословно), на белой плашке поверх всего ролика; вшитые тексты остальных клипов
# должны влезать под неё. Кадры других роликов обязательны (разные видеоряды), поэтому с h1 не пересекается.
# Многие ролики клиента нарезаны из одной записи (иногда со сдвигом) — ищем общие куски кадр в кадр и не ставим
# клипы одной записи ближе H2_NEAR секунд друг к другу (иначе первый клип = то, что «пару секунд назад» у второго).
H2_LEN = {2: 5.0, 3: 10.0 / 3}
H2_FULL = False                      # --full: длина = длине оригинала первого клипа, ровно на 2 или 3 части
H2_NEAR = 5.0
H2_QUOTA = {"Airport": 0.46, "Restaurant": 0.26, "Subway": 0.15, "Office": 0.13}
LINK_TH, LINK_RUN = 0.8, 5          # совпадение кадров (корр.) и минимум 1 с подряд (5 к/с)
CLIP_SIM_MAX = 0.7                   # любые два кадра разных клипов не должны быть почти одинаковыми


def clip_sim(c1: tuple[str, float, float], c2: tuple[str, float, float], cat: dict[str, Src]) -> float:
    """Максимальная похожесть кадров двух клипов (10 к/с) — ловит ту же сцену, даже если клиент кадрировал иначе."""
    sub = FPS // 10
    x = thumbs(cat[c1[0]].path)[round(c1[1] * FPS):round(c1[2] * FPS):sub]
    y = thumbs(cat[c2[0]].path)[round(c2[1] * FPS):round(c2[2] * FPS):sub]
    x, y = x.reshape(len(x), -1), y.reshape(len(y), -1)
    return float((x @ y.T).max() / x.shape[1])


def footage_links(cat: dict[str, Src], keys: list[str]) -> tuple[dict[tuple[str, str], list[float]], dict[str, str]]:
    """Общие куски записи между роликами одной локации: (a, b) → сдвиги off (время в b = время в a + off).
    Плюс видеоряд: ролики, совпадающие почти целиком без сдвига (тот же ролик с другим текстом), — одна группа."""
    sub = FPS // 5
    F = {k: thumbs(cat[k].path)[::sub].reshape(-1, thumbs(cat[k].path)[0].size) for k in keys}
    links: dict[tuple[str, str], list[float]] = {}
    group = {k: k for k in keys}

    def root(x: str) -> str:
        while group[x] != x:
            x = group[x]
        return x

    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if cat[a].loc != cat[b].loc:
                continue
            M = (F[a] @ F[b].T) / F[a].shape[1] > LINK_TH
            offs, cover0 = set(), 0
            for off in range(-M.shape[0] + 1, M.shape[1]):
                d = np.diagonal(M, offset=off)
                run = best = 0
                for x in d:
                    run = run + 1 if x else 0
                    best = max(best, run)
                if best >= LINK_RUN:
                    offs.add(off / 5)
                    if abs(off) <= 1:
                        cover0 = max(cover0, int(d.sum()))
            if offs:
                links[(a, b)] = sorted(offs)
                links[(b, a)] = sorted(-o for o in offs)
                if cover0 >= 0.7 * min(len(F[a]), len(F[b])):
                    group[root(a)] = root(b)
    return links, {k: root(k) for k in keys}


def too_near(c1: tuple[str, float, float], c2: tuple[str, float, float], links: dict) -> bool:
    """Клип c1 переносим на шкалу ролика c2 по каждому общему сдвигу — ближе H2_NEAR к c2 нельзя."""
    for off in links.get((c1[0], c2[0]), []):
        a, b = c1[1] + off, c1[2] + off
        if a < c2[2] + H2_NEAR and c2[1] < b + H2_NEAR:
            return True
    return False


def run_h2(cat: dict[str, Src], count: int, out: Path, seed: int, locs: list[str] | None) -> list[dict]:
    rng = np.random.default_rng(seed + 2)
    canon = same_video_text(cat)
    keys = sorted(set(canon.values()))
    links, foot = footage_links(cat, keys)
    dur = {k: len(thumbs(cat[k].path)) / FPS for k in keys}
    quota = {l: 1 / len(locs) for l in locs} if locs else H2_QUOTA
    plan = []
    for loc, q in quota.items():
        plan += [loc] * int(round(q * count))
    plan = (plan + list(quota))[:count]
    rng.shuffle(plan)
    firsts = {loc: [k for k in keys if cat[k].loc == loc] for loc in quota}
    for loc in firsts:
        firsts[loc] = [firsts[loc][i] for i in rng.permutation(len(firsts[loc]))]
    fcur = {loc: 0 for loc in quota}
    used_combo: set[tuple[str, ...]] = set()
    fr = lambda k, t: thumbs(cat[k].path)[min(len(thumbs(cat[k].path)) - 1, max(0, int(round(t * FPS))))]  # noqa: E731
    rep = []
    for n, loc in enumerate(plan, 1):
        got = None
        for _attempt in range(400):
            nclip = int(rng.choice([2, 3], p=[0.4, 0.6]))
            k1 = firsts[loc][fcur[loc] % len(firsts[loc])]               # первые клипы (= тексты) — по кругу
            fcur[loc] += 1
            if H2_FULL:                                                   # длина как у оригинала первого клипа
                if dur[k1] < EQ_TH3:
                    nclip = 2
                L = int(dur[k1] * FPS / nclip) / FPS
            else:
                L = H2_LEN[nclip]
            nf = round(L * FPS)
            if dur[k1] < L:
                continue
            text = TEXTS[k1]
            b1 = cat[k1].box
            wrap = min(800.0, max(300.0, b1[2] - b1[0] - 12))     # переносим строки как в оригинале первого клипа
            nl = box_lines(b1)
            rect = plate_layout(text, wrap, nl)[3]
            rect = [min(rect[0], b1[0] - FIT_M), min(rect[1], b1[1] - FIT_M), max(rect[2], b1[2] + FIT_M),
                    max(rect[3], b1[3] + FIT_M)]
            pool = [k for k in keys if cat[k].loc == loc and foot[k] != foot[k1] and dur[k] >= L
                    and fits_plate(cat[k].box, rect)]
            if len({foot[k] for k in pool}) < nclip - 1:
                continue
            clips: list[tuple[str, float, float]] = []
            ok = True
            for j in range(nclip):
                for _t in range(120):
                    k = k1 if j == 0 else pool[int(rng.integers(len(pool)))]
                    if j and foot[k] in {foot[c[0]] for c in clips}:
                        continue
                    a = int(rng.integers(0, round(dur[k] * FPS) - nf + 1)) / FPS
                    c = (k, a, a + nf / FPS)
                    if any(too_near(c, q, links) or too_near(q, c, links) or clip_sim(c, q, cat) > CLIP_SIM_MAX
                           for q in clips):
                        continue
                    if clips and frame_corr(fr(clips[-1][0], clips[-1][2] - 1 / FPS), fr(k, a)) > 0.5:
                        continue                                          # стык должен быть заметной склейкой
                    clips.append(c)
                    break
                else:
                    ok = False
                    break
            if not ok:
                continue
            combo = tuple(c[0] for c in clips)
            if combo in used_combo:                                       # тот же набор роликов в том же порядке — нет
                continue
            used_combo.add(combo)
            got = (text, clips, wrap, nl)
            break
        if got is None:
            raise SystemExit(f"h2: не собрал ролик {n} для {loc}")
        text, clips, wrap, nl = got
        total = sum(b - a for _k, a, b in clips)
        mus = cat[clips[0][0]] if cat[clips[0][0]].music and cat[clips[0][0]].dur >= total else None
        if mus is None:
            mm = [cat[k] for k in keys if cat[k].loc == loc and cat[k].music and cat[k].dur >= total]
            mus = mm[int(rng.integers(len(mm)))] if mm else None
        dest = out / f"h2_{n:03d}_1285.mp4"
        png = out / "_png" / f"h2_{n:03d}.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        info = plate_png(text, [cat[k].box for k, _a, _b in clips], png, wrap, nl)
        JOBS.append(([(cat[k].path, a, b) for k, a, b in clips], (mus.path, mus.dur) if mus else None, png, dest,
                     jitter(rng)))
        rep.append({"file": dest.name, "loc": loc, "text": text, "first": clips[0][0], "music": mus.key if mus else None,
                    "parts": [[k, round(a, 3), round(b, 3)] for k, a, b in clips], "total": round(total, 2), **info})
    print(f"h2: {len(rep)} роликов; 2 клипа {sum(len(r['parts']) == 2 for r in rep)}, 3 клипа "
          f"{sum(len(r['parts']) == 3 for r in rep)}; по папкам {dict(Counter(r['loc'] for r in rep))}", flush=True)
    return rep


H3_MAX, H3_STEP = 10.0, 1.5              # ролик ≤ 10 с; окна длинных роликов — с шагом 1.5 с
H3_INS = (1.0, 1.4)                      # длина вставки, с
H3_QUOTA = {"Airport": 0.44, "Restaurant": 0.26, "Subway": 0.16, "Office": 0.14}


def run_h3(cat: dict[str, Src], count: int, out: Path, seed: int, only: list[str] | None) -> list[dict]:
    """Гипотеза 3, ≤ 10 с: ролик (до 10 с — целиком, длиннее — 10-секундное окно) + 1 вставка живого видео
    с Pinterest той же локации около ⅓ или ⅔ ролика вместо куска той же длины. Вшитый текст — маской поверх
    всего ролика (на вставке он тоже есть). Звук оригинала с начала окна, в такт картинке."""
    rng = np.random.default_rng(seed + 3)
    canon = same_video_text(cat)
    keys = sorted(set(canon.values()))
    dur = {k: len(thumbs(cat[k].path)) / FPS for k in keys}
    pins = {loc: pins_for(loc) for loc in H3_QUOTA}
    quota = {l: q for l, q in H3_QUOTA.items() if pins[l]}
    if only:
        quota = {l: 1 / len(only) for l in only if pins.get(l)}
    tot = sum(quota.values())
    plan = []
    for loc, q in quota.items():
        plan += [loc] * int(round(q / tot * count))
    plan = (plan + list(quota))[:count]
    rng.shuffle(plan)
    # все варианты (ролик, окно, место вставки) по локациям — по кругу, без повторов
    slots: dict[str, list] = {}
    for loc in quota:
        v = []
        for k in keys:
            if cat[k].loc != loc:
                continue
            wins = [0.0] if dur[k] <= H3_MAX else [i * H3_STEP for i in range(int((dur[k] - H3_MAX) / H3_STEP + 1e-6) + 1)]
            for w0 in wins:
                L = min(H3_MAX, dur[k] - w0)
                for pos in ((1 / 3, 2 / 3) if L >= 8 else (0.5,)):
                    v.append((k, w0, L, pos))
        slots[loc] = [v[i] for i in rng.permutation(len(v))]
    cur = {loc: 0 for loc in quota}
    pcur = {loc: 0 for loc in quota}
    pdur = {f: probe_dur(f) for loc in quota for f in pins[loc]}
    rep = []
    for n, loc in enumerate(plan, 1):
        k, w0, L, pos = slots[loc][cur[loc] % len(slots[loc])]
        cur[loc] += 1
        s = cat[k]
        pin = pins[loc][pcur[loc] % len(pins[loc])]                      # видео с Pinterest — по кругу
        pcur[loc] += 1
        d = round(float(rng.uniform(*H3_INS)) * FPS) / FPS
        t0 = round((w0 + L * pos - d / 2) * FPS) / FPS
        t1 = round((t0 + d) * FPS) / FPS
        end = round((w0 + L) * FPS) / FPS
        pa = round(float(rng.uniform(0.3, max(0.31, pdur[pin] - d - 0.3))) * FPS) / FPS
        segs = [(s.path, w0, t0), (pin, pa, pa + d), (s.path, t1, end)]
        dest = out / f"h3_{n:03d}_1285.mp4"
        matte = CACHE / "matte" / (k.replace("/", "_") + ".png")
        JOBS.append((segs, (s.path, s.dur, w0), matte, dest, jitter(rng)))
        rep.append({"file": dest.name, "loc": loc, "src": k, "window": [round(w0, 2), round(end, 2)], "pin": pin.name,
                    "insert": [round(t0 - w0, 2), round(t1 - w0, 2)], "pin_from": pa, "total": round(end - w0, 2)})
    print(f"h3: {len(rep)} роликов; по папкам {dict(Counter(r['loc'] for r in rep))}; видео с Pinterest "
          f"{ {l: len(pins[l]) for l in quota} }", flush=True)
    return rep


def qa_sheet(out: Path, files: list[str]) -> None:
    """Кадр с каждого ролика + зоны интерфейса (красное) и рамка текста (зелёная)."""
    tiles = []
    for f in files:
        raw = subprocess.run([FF, "-v", "error", "-ss", "1.0", "-i", str(out / f), "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        im = draw_overlay(Image.frombytes("RGB", (W, H), raw)).resize((270, 480))
        tiles.append(im)
    sheet = Image.new("RGB", (280 * len(tiles), 480), "white")
    for i, t in enumerate(tiles):
        sheet.paste(t, (i * 280, 0))
    sheet.save(out / "_qa_safezones.jpg", quality=85)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["catalog", "h1", "h1s", "h2", "h3"])
    ap.add_argument("--count", type=int, default=2)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "1285_test")
    ap.add_argument("--seed", type=int, default=1285)
    ap.add_argument("--only", nargs="*", help="ключи исходников (h1/h3) или локации (h2)")
    ap.add_argument("--jobs", type=int, default=4, help="сколько роликов рендерить параллельно")
    ap.add_argument("--force", action="store_true", help="перерендерить и уже существующие файлы")
    ap.add_argument("--full", action="store_true", help="h2: длина как у оригинала первого клипа (без лимита 10 с)")
    a = ap.parse_args()
    global H2_FULL
    H2_FULL = a.full
    cat = catalog()
    if a.mode == "catalog":
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    if a.mode in ("h1", "h1s"):
        rep = run_eq(cat, a.out, a.seed, 1 if a.mode == "h1" else 2, a.count)
    else:
        rep = {"h2": run_h2, "h3": run_h3}[a.mode](cat, a.count, a.out, a.seed, a.only)
    run_jobs(a.jobs, a.force)
    man = a.out / f"manifest_{a.mode}.json"
    old = json.loads(man.read_text(encoding="utf-8")) if man.exists() else []
    names = {r["file"] for r in rep}
    man.write_text(json.dumps([r for r in old if r["file"] not in names] + rep, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    if a.mode == "h2":
        qa_sheet(a.out, [r["file"] for r in rep][:: max(1, len(rep) // 12)][:12])
    print("готово →", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
