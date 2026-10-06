#!/usr/bin/env python3
"""
Трёхчастные UGC-рилы «iPad girlies / Cozy Home»:
  [0–4 с] лицо (хук-текст) → [4–6 с] планшет с котом → [6–8 с] руки раскрашивают
  (второй текст на 4–8 с). Музыка: первые 4 с — спокойная часть, склейка
  на 4.00 с попадает в кульминацию.

Отрисовка текста (белый + чёрная обводка, Apple-эмодзи), SDR bt709 —
из assemble_ugc_reels.py / core.ugc_color (см. UGC_REELS_HANDOFF.md).

  python assemble_ugc_reels_3part.py -n 5 --out output/ugc_3part_test --seed 1
  python assemble_ugc_reels_3part.py -n 250 --out output/ugc_3part_250 --seed 42
  python assemble_ugc_reels_3part.py --preset deleted -n 100 --by-hook --out output/ugc_3part_deleted

Пресет (--preset) = тексты + звуки + плашка; старты звуков у каждого пресета
свои (ugc_sound_starts*.json, подгоняются в ugc_sound_tuner.py --preset …).
"""

from __future__ import annotations

import argparse
import itertools
import math
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

import assemble_ugc_reels as A
from core import renderer as R
from core.comment_sticker import NEUTRAL_COMMENTERS, render_reply_sticker
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR, vf_scale_crop_fps_sdr

ROOT = Path(__file__).resolve().parent
CLIPS = ROOT / "output" / "clips_custom"
CLIPS_P2 = ROOT / "output" / "clips_proj2"
CLIPS_P3 = ROOT / "output" / "clips_proj3"
# пулы клипов и длительности — из пресета (use_preset)
FIRST_DIR = MID_DIR = END_DIR = CLIPS
FIRST_DUR = MID_DUR = END_DUR = TOTAL = CUT = 0.0  # CUT — смена текста и вход кульминации

# Звуки делятся поровну. start — секунда трека, с которой играет звук:
# первые 4 с ролика — спокойная часть, на склейке 4.0 с — кульминация.
# start здесь — запасные значения; рабочие лежат в файле стартов пресета,
# их подгоняют на слух в ugc_sound_tuner.py.
D = ROOT / "downloads"
SOUND_LIB = {
    "strokes": (D / "tiktok_klaraa.ipod_7651216358830656801_TheStrokes-TheAdultsAreTalking.mp3", 29.8),
    "kanye": (D / "tiktok_elena.spylisa_7652523630374554902.mp3", 0.11),
    "bes": (D / "tiktok_hothighpriestess_7621007557435428109.mp3", 0.73),
    "lochie": (D / "tiktok_tweetytakespics_7650000045508545824.mp3", 45.0),  # громче с 49 с
    "lisa": (D / "tiktok_aya.photo.marie_7648323760147254548.mp3", 0.0),  # громче с 4 с
    "kailyn": (D / "tiktok_kailyn.lifts_7623850765102173454.mp3", 1.0),  # громче с 4 с
    "uzi": (D / "tiktok_phileinevansprang_7683911977307049238_LilUziVert-WhatYouSaying.m4a", 11.25),  # вход 14.25 с
    "berry": (D / "tiktok_berryblind_7018946187533323522.m4a", 4.25),  # громче с 7.25 с
    "mammogus": (D / "tiktok_kukumber_art_7057616060727561474.m4a", 4.0),  # громче с 7.0 с
}

# Плашка «Reply to …'s comment» — весь ролик, сверху слева (как в примере)
STICKER_COMMENT = "Whats the app called? 😬"
STICKER_BODY_PX = 30  # референс 24 (≈22% ширины) × 1.25 — читабельнее
STICKER_X, STICKER_Y = 85, 420

# ТЗ: по 50 роликов на каждый хук; один текст на части 2–3.
# Строки (\n) — по смыслу: не рвём «make me feel», «so much», «literally
# cried»; эмодзи закрывают свою строку.
HOOKS = [
    "To all my iPad girlies 😭🍂\nyou NEED this app this fall!!",
    "OMG iPad girlies,\nupgrade your fall evenings NOW 🍁🔥",
    "I was having the worst week 😞🍂\nand then I found this app…",
    "I didn't think anything\ncould make me feel better this fall 🥺🍂\nuntil this…",
    "Guys… I saw this app\nand literally cried\nfrom how cute it is 😭🥹",
]
BODY = (
    "My bestie told me to try Cozy Home\n"
    "and I'm OBSESSED…\n"
    "just LOOK at all these\n"
    "tiny cute details 😭🧸✨\n"
    "my whole day\n"
    "got so much better 🍂💛"
)

# Пресет «deleted»: 2 хука по 50, без плашки, 5 звуков
DELETED_HOOKS = [
    "I deleted Instagram this fall 🍂\nand found something way better…",
    "I deleted Pinterest 🗑\nnow THIS is my cozy place 🍂💛",
]

# Пресет «magicsort»: лицо 3 с + 2 клипа игры по 2 с = 7 с; 10 пар текстов
# (кадр 1 / кадр 2) по 20 роликов. Строки — по смыслу фраз.
MAGICSORT_TEXTS = [
    ("day 1 post breakup.\ndon't laugh but\ni deleted every app\nand kept only THIS one",
     "all i do now is sort liquids\ninto tubes fr.\ncan't think about anything else,\nESPECIALLY not him.\n"
     "it's called Magic Sort btw,\neveryone's obsessed"),
    ("not me deleting every app\nafter the breakup\nand keeping only this one",
     "pouring colors into lil tubes\nis my whole personality now.\nhim? who??\n"
     "it's Magic Sort btw,\nliterally everyone's on it"),
    ("breakup day 1 and i'm coping\nin the weirdest way possible",
     "i just sort liquids\nin tubes all day\nand my brain is SILENT.\nno thoughts of him, zero.\n"
     "Magic Sort btw,\nit's going viral rn"),
    ("pov: he left\nso i deleted everything\nexcept this app",
     "sorting colors into tubes >\ncrying over a man.\nlowkey healing era.\n"
     "it's called Magic Sort,\neveryone's talking about it"),
    ("no bc after the breakup\ni deleted all my apps\nand kept ONE",
     "it's literally just mixing\nliquids in tubes\nand i'm hooked.\nforgot his name ngl.\n"
     "Magic Sort btw,\nit's everywhere rn"),
    ("day 1 of being single\nand this app is\nmy emotional support",
     "me sorting colors into tubes\ninstead of checking his stories.\ngrowth fr.\n"
     "it's Magic Sort,\ny'all need it"),
    ("don't judge me\nbut this is how\ni'm surviving the breakup",
     "i sort liquids into tubes\nuntil my brain goes quiet.\nhim who?\nnever heard of him.\n"
     "Magic Sort btw,\neveryone's playing it"),
    ("he really thought\ni'd be crying rn.\ninstead i'm doing THIS",
     "pouring colors into tubes\nis so satisfying\ni forgot i was sad.\nit's giving healing.\n"
     "Magic Sort btw,\nit's blowing up"),
    ("breakup recovery tier list:\nthis app is S tier",
     "i literally just sort liquids\nand it's the only thing\nin my head.\nnot him, not the texts, nothing.\n"
     "it's Magic Sort, trust me"),
    ("deleted his number,\ndeleted every app,\nkept only THIS",
     "sorting tubes until 3am\ninstead of overthinking.\nthis is my villain arc.\n"
     "it's called Magic Sort btw,\neveryone's talking about it"),
]

W, H = A.W, A.H
# Хук — как в остальных рилах (центр + 12%: на груди, лицо открыто).
# Текст частей 2–3 — сверху: по центру кадра он закрывал экран планшета
# с раскраской (то самое «LOOK at all these tiny cute details») и кота.
BODY_TOP_Y = 630  # под плашкой (низ плашки ~585)

_COZY_CLIPS = {
    "clips": (CLIPS / "MyResultVideo_face_4s", CLIPS / "IMG_9759_play_2s", CLIPS / "IMG_9745_play_2s"),
    "durs": (4.0, 2.0, 2.0),
}
# hooks — текст кадра 1; bodies — текст кадра 2 (один на всех или по хуку);
# label — имя группы в файлах/папках (hook1…, text1…)
PRESETS = {
    "cozy": {
        **_COZY_CLIPS, "hooks": HOOKS, "bodies": [BODY], "sticker": True, "body_top_y": BODY_TOP_Y,
        "sounds": ["strokes", "kanye", "bes"], "starts_file": "ugc_sound_starts.json", "label": "hook",
    },
    "deleted": {
        **_COZY_CLIPS, "hooks": DELETED_HOOKS, "bodies": [BODY], "sticker": False, "body_top_y": 260,
        "sounds": ["strokes", "kanye", "bes", "lochie", "lisa"],
        "starts_file": "ugc_sound_starts_deleted.json", "label": "hook",
    },
    # 2-й кадр — два разных клипа игры из одного пула
    "magicsort": {
        "clips": (CLIPS_P2 / "IMG_9736_face_3s", CLIPS_P2 / "IMG_9758_play_2s", CLIPS_P2 / "IMG_9758_play_2s"),
        "durs": (3.0, 2.0, 2.0),
        "hooks": [h for h, _ in MAGICSORT_TEXTS], "bodies": [b for _, b in MAGICSORT_TEXTS],
        "sticker": False, "body_top_y": 260, "min_gap": 10.0,
        "sounds": ["kailyn", "kanye"], "starts_file": "ugc_sound_starts_magicsort.json", "label": "text",
    },
}
# «breakup»: 4 части (эмоция 3 с → рисует 2.5 с → кот 2 с → руки 1 с = 8.5 с),
# один длинный текст на весь ролик (как в assemble_ugc_reels), у каждого
# ролика свой текст из файла; text1/text2 — два набора текстов, свои папки
_BREAKUP = {
    "clips": (CLIPS_P3 / "IMG_9736_face_3s", CLIPS_P3 / "IMG_9761_play_2.5s",
              CLIPS_P3 / "IMG_9759_play_2s", CLIPS_P3 / "IMG_9745_play_1s"),
    "durs": (3.0, 2.5, 2.0, 1.0),
    "single_text": True, "hooks": [], "bodies": [], "sticker": False, "body_top_y": 260,
    "sounds": ["uzi", "berry", "mammogus"], "starts_file": "ugc_sound_starts_breakup.json", "label": "t",
}
PRESETS["breakup1"] = {**_BREAKUP, "texts_file": D / "breakup_text1.txt"}
PRESETS["breakup2"] = {**_BREAKUP, "texts_file": D / "breakup_text2.txt"}
# «deleted_ms»: лицо 4 с (MyResultVideo) → игра 3 с (IMG_9758) → 1 с со съёмки
# телефона (magicsort_story_clips_v2, phone) = 8 с; хуки «deleted», текст про Magic Sort
CLIPS_P4 = ROOT / "output" / "clips_proj4"
MAGICSORT_BODY = (
    "My bestie told me to try Magic Sort\n"
    "and I'm OBSESSED…\n"
    "just LOOK at all these pretty colors\n"
    "falling into place 😭🧪✨\n"
    "my brain\n"
    "finally got quiet 🌈💛"
)
PRESETS["deleted_ms"] = {
    "clips": (CLIPS / "MyResultVideo_face_4s", CLIPS_P4 / "IMG_9758_play_3s", CLIPS_P4 / "phone_1s"),
    "durs": (4.0, 3.0, 1.0),
    "hooks": DELETED_HOOKS, "bodies": [MAGICSORT_BODY], "sticker": False, "body_top_y": 260,
    "sounds": ["strokes", "kanye", "bes", "lochie", "lisa"],
    "starts_file": "ugc_sound_starts_deleted_ms.json", "label": "hook",
}
SOUNDS: list[dict] = []
SOUND_STARTS_FILE = ROOT / "ugc_sound_starts.json"
STICKER = True
CLIP_DIRS: tuple[Path, ...] = ()
DURS: tuple[float, ...] = ()
SINGLE_TEXT = False


def load_numbered(path: Path) -> list[str]:
    """«1. текст» → список текстов по порядку номеров."""
    raw = path.read_text(encoding="utf-8-sig")
    items = re.findall(r"(?m)^\s*(\d+)\.\s+(.+?)\s*$", raw)
    return [t for _, t in sorted(items, key=lambda x: int(x[0]))]
BODIES: list[str] = []
LABEL = "hook"
# 2-й и 3-й клипы из одного исходника: минимум секунд между ними по таймлайну
# исходника (чтобы склейка читалась, а не выглядела как продолжение)
MIN_GAP = 0.0


def use_preset(name: str) -> None:
    """Выставить клипы, длительности, тексты, звуки (со стартами из файла
    пресета) и плашку."""
    global HOOKS, BODY, BODIES, BODY_TOP_Y, STICKER, SOUND_STARTS_FILE, LABEL, MIN_GAP
    global FIRST_DIR, MID_DIR, END_DIR, FIRST_DUR, MID_DUR, END_DUR, TOTAL, CUT
    global CLIP_DIRS, DURS, SINGLE_TEXT
    p = PRESETS[name]
    HOOKS, BODY_TOP_Y, STICKER, LABEL = p["hooks"], p["body_top_y"], p["sticker"], p["label"]
    if "texts_file" in p:
        HOOKS = load_numbered(p["texts_file"])
    SINGLE_TEXT = p.get("single_text", False)
    MIN_GAP = p.get("min_gap", 0.0)
    BODIES = p["bodies"] if len(p["bodies"]) == len(HOOKS) else p["bodies"] * len(HOOKS)
    BODY = BODIES[0] if BODIES else ""
    CLIP_DIRS, DURS = tuple(p["clips"]), tuple(p["durs"])
    if len(CLIP_DIRS) == 3:
        FIRST_DIR, MID_DIR, END_DIR = CLIP_DIRS
        FIRST_DUR, MID_DUR, END_DUR = DURS
    TOTAL, CUT = sum(DURS), DURS[0]
    SOUND_STARTS_FILE = ROOT / p["starts_file"]
    try:
        saved = json.loads(SOUND_STARTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    SOUNDS[:] = [
        {"name": n, "file": SOUND_LIB[n][0], "start": round(float(saved.get(n, SOUND_LIB[n][1])), 2)}
        for n in p["sounds"]
    ]


use_preset("cozy")
# Фраза (до эмодзи включительно) — одной строкой, если для этого хватает
# шрифта не мельче этого; иначе сбалансированный перенос внутри фразы
PHRASE_MIN_FONT = 40
# Автоперенос (длинная строка без ручных переносов): не заканчивать строку
# на связующем слове — «got so / much», «could make me / feel»
NO_BREAK_AFTER = {
    "a", "an", "the", "to", "of", "in", "on", "at", "for", "with", "from",
    "and", "or", "but", "so", "too", "very", "just", "all", "my", "your",
    "his", "her", "our", "their", "this", "that", "these", "those", "i",
    "i'm", "could", "would", "can", "will", "make", "made", "me", "got",
    "get", "is", "are", "was", "be",
}


def _is_emoji_only(word: str) -> bool:
    return bool(word) and not A._EMOJI_RE.sub("", word).replace("\uFE0F", "").strip()


def _glue_emoji(text: str) -> list[str]:
    """Слова строки; эмодзи приклеены к предыдущему слову — строка не может
    начаться с эмодзи («…worst week / 😞🍂 and then…»)."""
    out: list[str] = []
    for w in text.split():
        if out and _is_emoji_only(w):
            out[-1] = f"{out[-1]} {w}"
        else:
            out.append(w)
    return out


def _phrases(text: str) -> list[str]:
    """Строка ТЗ → фразы: разрыв после группы эмодзи («…worst week 😞🍂 |
    and then…»). Эмодзи закрывают фразу и остаются в конце своей строки."""
    out: list[list[str]] = [[]]
    for w in _glue_emoji(text):
        out[-1].append(w)
        if _is_emoji_only(w.split()[-1]):
            out.append([])
    return [" ".join(ws) for ws in out if ws]


def _balanced_wrap(text: str, font, size: int, max_w: int, stroke: int) -> list[str]:
    """Перенос одной строки ТЗ на строки примерно равной длины: без висячих
    слов и без эмодзи в начале строки."""
    words = _glue_emoji(text)

    def width(ws: list[str]) -> float:
        return A._line_width_mixed(" ".join(ws), font, size, stroke)

    # жадно — сколько строк нужно (единицы переноса — склеенные слова)
    greedy: list[list[str]] = [[]]
    for w in words:
        if greedy[-1] and width(greedy[-1] + [w]) > max_w:
            greedy.append([w])
        else:
            greedy[-1].append(w)
    k = len(greedy)
    if k <= 1 or len(words) <= k:
        return [" ".join(ln) for ln in greedy]
    if math.comb(len(words) - 1, k - 1) > 500:
        # длинный абзац: перебор взрывается — та же цель динамикой
        return _balanced_wrap_dp(words, width, max_w, k) or [" ".join(ln) for ln in greedy]
    best = None
    for cuts in itertools.combinations(range(1, len(words)), k - 1):
        bounds = (0, *cuts, len(words))
        lines = [words[a:b] for a, b in zip(bounds, bounds[1:])]
        widths = [width(ln) for ln in lines]
        if max(widths) > max_w:
            continue
        # не оставлять строку из одного слова
        if any(len(ln) == 1 and len(words) > k + 1 for ln in lines):
            continue
        weak = sum(
            1 for ln in lines[:-1]
            if ln[-1].lower().strip(",.!?…") in NO_BREAK_AFTER
        )
        score = weak * 1000 + max(widths) - min(widths)
        if best is None or score < best[0]:
            best = (score, [" ".join(ln) for ln in lines])
    return best[1] if best else [" ".join(ln) for ln in greedy]


def _balanced_wrap_dp(words: list[str], width, max_w: int, k: int) -> list[str] | None:
    """k строк, каждая не шире max_w: минимум суммы (ширина − средняя)²,
    штраф за строку на связующем слове и за строку из одного слова."""
    n = len(words)
    # ширина строки = сумма ширин слов + пробелы (без перемера каждой строки)
    pre = [0.0]
    for x in words:
        pre.append(pre[-1] + width([x]))
    gap = width(["a", "a"]) - 2 * width(["a"])  # пробел минус лишний обвод

    def w(a: int, b: int) -> float:
        return pre[b] - pre[a] + gap * (b - a - 1)

    target = w(0, n) / k
    inf = float("inf")
    cost = [[inf] * (n + 1) for _ in range(k + 1)]
    back = [[0] * (n + 1) for _ in range(k + 1)]
    cost[0][0] = 0.0
    for j in range(1, k + 1):
        for i in range(j, n + 1):
            for a in range(j - 1, i):
                if cost[j - 1][a] == inf:
                    continue
                lw = w(a, i)
                if lw > max_w:
                    continue
                c = (lw - target) ** 2
                if j < k and words[i - 1].lower().strip(",.!?…") in NO_BREAK_AFTER:
                    c += 1e6
                if i - a == 1 and n > k + 1:
                    c += 1e7
                if cost[j - 1][a] + c < cost[j][i]:
                    cost[j][i], back[j][i] = cost[j - 1][a] + c, a
    if cost[k][n] == inf:
        return None
    lines, i = [], n
    for j in range(k, 0, -1):
        a = back[j][i]
        lines.append(" ".join(words[a:i]))
        i = a
    return lines[::-1]


def render_text_png(text: str, dest: Path, *, top_y: int | None = None) -> None:
    """Как A.render_text_png (стиль, шрифт, Apple-эмодзи), но строки из ТЗ
    сохраняются, длинная строка переносится сбалансированно; top_y — верх
    текстового блока (None = как в остальных рилах)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    paragraphs = [
        A.sanitize_overlay_text(R._normalize_text(p))
        for p in text.split("\n")
        if p.strip()
    ]
    max_w = int(W * A.MAX_W_RATIO)
    left = (W - max_w) // 2
    top_limit, bot_limit = A.SAFE_TOP, H - A.SAFE_BOTTOM

    phrases = [ph for p in paragraphs for ph in _phrases(p)]

    def layout(size: int, strict: bool):
        font = R._load_font(size)
        stroke = R.stroke_width_for(size)
        wrap_w = max(40, max_w - 2 * stroke)
        lines: list[str] = []
        for ph in phrases:
            if A._line_width_mixed(ph, font, size, stroke) <= wrap_w:
                lines.append(ph)
            elif strict:
                return None
            else:
                lines += _balanced_wrap(ph, font, size, wrap_w, stroke)
        tw, th = A._measure_block_mixed(lines, font, size, stroke)
        if th > (bot_limit - top_limit) or (tw * th) / float(W * H) > A.MAX_AREA:
            return None
        return size, font, stroke, lines, tw, th

    # 1) каждая фраза одной строкой, шрифт не мельче PHRASE_MIN_FONT;
    # 2) иначе — как раньше, длинная фраза переносится сбалансированно
    chosen = next(
        (c for size in range(A.FONT_START, PHRASE_MIN_FONT - 1, -A.FONT_STEP)
         if (c := layout(size, strict=True))),
        None,
    ) or next(
        (c for size in range(A.FONT_START, A.FONT_MIN - 1, -A.FONT_STEP)
         if (c := layout(size, strict=False))),
        None,
    ) or layout(A.FONT_MIN, strict=False)

    size, font, stroke, lines, tw, th = chosen
    if top_y is not None:
        y = max(top_limit, top_y)
    else:
        y = top_limit + max(0, (bot_limit - top_limit - th) // 2)
        y = int(y + H * A.TEXT_DOWN_FRAC)
    if y + th > bot_limit:
        y = max(top_limit, bot_limit - th)
    for line in lines:
        lw = int(round(A._line_width_mixed(line or " ", font, size, stroke)))
        # по центру кадра (left + центр в блоке max_w уводил узкий текст влево)
        x = max(left, (W - lw) // 2)
        A._draw_line_mixed(img, draw, x, y, line, font, size, stroke)
        y += R.line_advance_for(size)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)


def _src_time(clip: Path) -> float:
    """Старт клипа в исходнике — из имени (…_003_7.25s.mp4)."""
    m = re.search(r"_(\d+(?:\.\d+)?)s\.mp4$", clip.name)
    return float(m.group(1)) if m else 0.0


def plan_videos(n: int, firsts: list[Path], mids: list[Path], ends: list[Path], rng: random.Random) -> list[dict]:
    """
    n уникальных троек (начало, середина, конец) с равномерным расходом
    клипов; хуки по n/len(HOOKS) штук. Внутри группы хука пары
    (начало, конец) не повторяются. Середина и конец из одного пула —
    разные клипы, не ближе MIN_GAP с по исходнику; при равном расходе
    берётся пара с бо́льшим разрывом.
    """
    triples = list(itertools.product(range(len(firsts)), range(len(mids)), range(len(ends))))
    gap = {t: abs(_src_time(mids[t[1]]) - _src_time(ends[t[2]])) for t in triples}
    if mids == ends:  # два клипа из одного пула — не один и тот же дважды
        triples = [t for t in triples if t[1] != t[2] and gap[t] >= MIN_GAP]
    if n > len(triples):
        raise SystemExit(f"Нужно {n}, а уникальных видеорядов только {len(triples)}")
    rng.shuffle(triples)
    use = [Counter(), Counter(), Counter()]
    caps = [-(-n // len(firsts)), -(-n // len(mids)), -(-n // len(ends))]
    hooks = [i % len(HOOKS) for i in range(n)]
    rng.shuffle(hooks)
    pairs_in_hook: dict[int, set] = {h: set() for h in range(len(HOOKS))}

    plan: list[dict] = []
    for hook in hooks:
        best = None
        for t in triples:
            if any(use[k][t[k]] >= caps[k] for k in range(3)):
                continue
            if (t[0], t[2]) in pairs_in_hook[hook]:
                continue
            # меньше всего использованные клипы — первыми, затем дальше по таймлайну
            key = (use[1][t[1]], use[0][t[0]], use[2][t[2]], -gap[t])
            if best is None or key < best[0]:
                best = (key, t)
        if best is None:
            raise SystemExit("Не удалось подобрать уникальную тройку")
        t = best[1]
        triples.remove(t)
        for k in range(3):
            use[k][t[k]] += 1
        pairs_in_hook[hook].add((t[0], t[2]))
        plan.append({"hook": hook, "first": firsts[t[0]], "mid": mids[t[1]], "end": ends[t[2]]})
    # звук и ник — поровну и вперемешку, независимо от хука
    sounds = [i % len(SOUNDS) for i in range(n)]
    names = [i % len(NEUTRAL_COMMENTERS) for i in range(n)]
    rng.shuffle(sounds)
    rng.shuffle(names)
    for v, si, ni in zip(plan, sounds, names):
        v["sound"], v["commenter"] = si, ni
    return plan


def render_sticker_png(username: str, dest: Path) -> None:
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    st = render_reply_sticker(username, STICKER_COMMENT, body_px=STICKER_BODY_PX)
    canvas.alpha_composite(st, (STICKER_X, STICKER_Y))
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest)


def _frame(clip: Path, t: float) -> Image.Image:
    r = subprocess.run(
        [A.find_ffmpeg(), "-v", "error", "-ss", f"{t:.2f}", "-i", str(clip), "-frames:v", "1",
         "-vf", f"scale={W}:{H}", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True, stdin=subprocess.DEVNULL,
    )
    from io import BytesIO
    return Image.open(BytesIO(r.stdout)).convert("RGBA")


def text_preview(first: Path, end: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    face, hands = _frame(first, 1.0), _frame(end, 1.0)
    shots = [(f"{LABEL}{h + 1}", text, face, None) for h, text in enumerate(HOOKS)]
    if len(set(BODIES)) == 1:
        shots.append(("body", BODY, hands, BODY_TOP_Y))
    else:
        shots += [(f"{LABEL}{h + 1}_body", b, hands, BODY_TOP_Y) for h, b in enumerate(BODIES)]
    for name, text, bg, top_y in shots:
        png = out / f"_{name}.png"
        render_text_png(text, png, top_y=top_y)
        frame = bg.copy()
        frame.alpha_composite(Image.open(png))
        frame.convert("RGB").save(out / f"{name}.jpg", quality=90)
        png.unlink()
        print(f"превью: {out / (name + '.jpg')}")


def concat_three(clips: list[Path], dest: Path, work: Path) -> None:
    ffmpeg = A.find_ffmpeg()
    lst = work / "concat.txt"
    lst.write_text(
        "\n".join(f"file '{c.resolve().as_posix()}'" for c in clips), encoding="utf-8"
    )
    cmd = [
        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-an",
        "-vf", vf_scale_crop_fps_sdr(W, H, 30),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        *SDR_COLOR_ARGS, "-t", f"{TOTAL:.2f}", str(dest),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])


def burn(
    video: Path,
    hook_png: Path,
    body_png: Path,
    sticker_png: Path | None,
    sound: dict,
    dest: Path,
) -> None:
    ffmpeg = A.find_ffmpeg()
    # плашка (вход 4) — поверх всего ролика, если есть
    sticker = "[v2];[v2][4:v]overlay=0:0:format=auto," if sticker_png else ","
    fc = (
        f"[0:v][2:v]overlay=0:0:format=auto:enable='lt(t,{CUT})'[v1];"
        f"[v1][3:v]overlay=0:0:format=auto:enable='gte(t,{CUT})'{sticker}"
        f"format=yuv420p,{SET_SDR}[v];"
        f"[1:a]atrim=0:{TOTAL},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d=0.08,afade=t=out:st={TOTAL - 0.35:.2f}:d=0.35[a]"
    )
    cmd = [
        ffmpeg, "-y",
        "-i", str(video),
        "-ss", f"{sound['start']:.3f}", "-i", str(sound["file"]),
        "-i", str(hook_png), "-i", str(body_png),
        *(["-i", str(sticker_png)] if sticker_png else []),
        "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        *SDR_COLOR_ARGS,
        "-c:a", "aac", "-b:a", "160k",
        "-t", f"{TOTAL:.2f}", "-movflags", "+faststart", str(dest),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])


def burn_single(video: Path, text_png: Path, sound: dict, dest: Path) -> None:
    """Один текст на весь ролик + звук (фейды как в burn)."""
    fc = (
        f"[0:v][2:v]overlay=0:0:format=auto,format=yuv420p,{SET_SDR}[v];"
        f"[1:a]atrim=0:{TOTAL},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d=0.08,afade=t=out:st={TOTAL - 0.35:.2f}:d=0.35[a]"
    )
    cmd = [
        A.find_ffmpeg(), "-y", "-i", str(video),
        "-ss", f"{sound['start']:.3f}", "-i", str(sound["file"]),
        "-i", str(text_png),
        "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", *SDR_COLOR_ARGS,
        "-c:a", "aac", "-b:a", "160k",
        "-t", f"{TOTAL:.2f}", "-movflags", "+faststart", str(dest),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])


def plan_single(n: int, pools: list[list[Path]], rng: random.Random) -> list[dict]:
    """Каждый ролик — свой текст (по кругу, если роликов больше текстов);
    в каждой позиции берётся наименее использованный клип; видеоряды не
    повторяются; звуки поровну."""
    texts: list[int] = []
    while len(texts) < n:
        chunk = list(range(len(HOOKS)))
        rng.shuffle(chunk)
        texts += chunk
    use = [Counter() for _ in pools]
    seen: set[tuple[int, ...]] = set()
    plan = []
    for i in range(n):
        for _ in range(1000):
            combo = []
            for k, pool in enumerate(pools):
                low = min(use[k][j] for j in range(len(pool)))
                cands = [j for j in range(len(pool)) if use[k][j] <= low + (1 if _ else 0)]
                combo.append(rng.choice(cands))
            if tuple(combo) not in seen:
                break
        seen.add(tuple(combo))
        for k, j in enumerate(combo):
            use[k][j] += 1
        plan.append({"hook": texts[i], "clips": [pools[k][j] for k, j in enumerate(combo)]})
    sounds = [i % len(SOUNDS) for i in range(n)]
    rng.shuffle(sounds)
    for v, si in zip(plan, sounds):
        v["sound"] = si
    return plan


def text_preview_single(pools: list[list[Path]], out: Path) -> None:
    """Самый короткий и самый длинный текст поверх кадра каждой части."""
    out.mkdir(parents=True, exist_ok=True)
    frames = [_frame(pool[len(pool) // 2], d / 2) for pool, d in zip(pools, DURS)]
    order = sorted(range(len(HOOKS)), key=lambda h: len(HOOKS[h]))
    for tag, h in (("short", order[0]), ("long", order[-1])):
        png = out / f"_{tag}.png"
        render_text_png(HOOKS[h], png)
        overlay = Image.open(png)
        row = Image.new("RGB", (W // 3 * len(frames), H // 3))
        for k, fr in enumerate(frames):
            f = fr.copy()
            f.alpha_composite(overlay)
            row.paste(f.convert("RGB").resize((W // 3, H // 3)), (k * (W // 3), 0))
        row.save(out / f"{LABEL}{h + 1}_{tag}.jpg", quality=88)
        png.unlink()
        print(f"превью: {out / f'{LABEL}{h + 1}_{tag}.jpg'}")


def main_single(args) -> int:
    pools = [sorted(d.glob("*.mp4")) for d in CLIP_DIRS]
    if not (all(pools) and all(sd["file"].is_file() for sd in SOUNDS) and HOOKS):
        raise SystemExit("Нет клипов, звука или текстов")
    combos = math.prod(len(p) for p in pools)
    print("пулы: " + " · ".join(f"{d.name} {len(p)}" for d, p in zip(CLIP_DIRS, pools))
          + f" → {combos} видеорядов · {TOTAL:g} с · текстов {len(HOOKS)}", flush=True)
    print("старты звуков: " + ", ".join(f"{sd['name']} {sd['start']:.2f}с" for sd in SOUNDS), flush=True)
    if args.text_preview:
        text_preview_single(pools, args.out)
        return 0

    plan = plan_single(args.n, pools, random.Random(args.seed))
    args.out.mkdir(parents=True, exist_ok=True)
    work_root = Path(tempfile.mkdtemp(prefix="ugc4_"))
    manifest = []
    try:
        pngs = {}
        for h in sorted({v["hook"] for v in plan}):
            pngs[h] = work_root / f"t{h + 1}.png"
            render_text_png(HOOKS[h], pngs[h])
        pad = max(3, len(str(args.n)))
        for i, v in enumerate(plan, 1):
            name = f"{i:0{pad}d}_{LABEL}{v['hook'] + 1:03d}.mp4"
            dest = args.out / name
            if not (dest.is_file() and dest.stat().st_size > 10_000):
                work = Path(tempfile.mkdtemp(prefix=f"ugc4_{i}_"))
                try:
                    silent = work / "silent.mp4"
                    concat_three(v["clips"], silent, work)
                    burn_single(silent, pngs[v["hook"]], SOUNDS[v["sound"]], dest)
                finally:
                    shutil.rmtree(work, ignore_errors=True)
            manifest.append({
                "file": name,
                "hook": v["hook"] + 1,
                "clips": [c.name for c in v["clips"]],
                "audio": SOUNDS[v["sound"]]["file"].name,
                "audio_start": SOUNDS[v["sound"]]["start"],
                "sticker": None,
                "hook_text": HOOKS[v["hook"]],
            })
            print(f"[{i}/{args.n}] {name}", flush=True)
            if i % 10 == 0 or i == args.n:
                (args.out / "manifest.json").write_text(
                    json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    finally:
        shutil.rmtree(work_root, ignore_errors=True)

    for k, d in enumerate(CLIP_DIRS):
        c = Counter(m["clips"][k] for m in manifest)
        print(f"{d.name}: {len(c)} клипов, использование {min(c.values())}–{max(c.values())}")
    print(f"разных текстов: {len({m['hook'] for m in manifest})} из {len(manifest)} роликов")
    print(f"звуки: {dict(Counter(m['audio'][:24] for m in manifest))}")
    print(f"готово: {len(manifest)} → {args.out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=5)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--by-hook", action="store_true", help="раскладывать по папкам hook1…/text1…")
    ap.add_argument("--preset", choices=sorted(PRESETS), default="cozy")
    ap.add_argument("--text-preview", action="store_true",
                    help="только картинки текста поверх кадров (без видео)")
    args = ap.parse_args()
    use_preset(args.preset)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if SINGLE_TEXT:
        return main_single(args)

    firsts = sorted(FIRST_DIR.glob("*.mp4"))
    mids = sorted(MID_DIR.glob("*.mp4"))
    ends = sorted(END_DIR.glob("*.mp4"))
    if not (firsts and mids and ends and all(sd["file"].is_file() for sd in SOUNDS)):
        raise SystemExit("Нет клипов или звука")
    combos = len(firsts) * len(mids) * (len(ends) - (mids == ends))
    print(f"пулы: начало {len(firsts)} · середина {len(mids)} · конец {len(ends)} "
          f"→ {combos} уникальных видеорядов · {TOTAL:g} с, склейка {CUT:g} с", flush=True)
    print("старты звуков: " + ", ".join(f"{sd['name']} {sd['start']:.2f}с" for sd in SOUNDS), flush=True)

    if args.text_preview:
        text_preview(firsts[0], mids[0], args.out)  # текст 2–3 поверх середины (конец бывает 1 с)
        return 0

    rng = random.Random(args.seed)
    plan = plan_videos(args.n, firsts, mids, ends, rng)
    args.out.mkdir(parents=True, exist_ok=True)

    work_root = Path(tempfile.mkdtemp(prefix="ugc3_"))
    pngs = {}
    try:
        for h, text in enumerate(HOOKS):
            pngs[h] = work_root / f"hook{h + 1}.png"
            render_text_png(text, pngs[h])
        body_pngs = {}
        for h, text in enumerate(BODIES):
            body_pngs[h] = work_root / f"body{h + 1}.png"
            render_text_png(text, body_pngs[h], top_y=BODY_TOP_Y)
        stickers = {}
        for ni, name in enumerate(NEUTRAL_COMMENTERS if STICKER else ()):
            stickers[ni] = work_root / f"sticker{ni}.png"
            render_sticker_png(name, stickers[ni])

        manifest = []
        pad = max(3, len(str(args.n)))
        for i, v in enumerate(plan, 1):
            name = f"{i:0{pad}d}_{LABEL}{v['hook'] + 1}.mp4"
            if args.by_hook:
                name = f"{LABEL}{v['hook'] + 1}/{name}"
            dest = args.out / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not (dest.is_file() and dest.stat().st_size > 10_000):
                work = Path(tempfile.mkdtemp(prefix=f"ugc3_{i}_"))
                try:
                    silent = work / "silent.mp4"
                    concat_three([v["first"], v["mid"], v["end"]], silent, work)
                    burn(silent, pngs[v["hook"]], body_pngs[v["hook"]], stickers.get(v["commenter"]),
                         SOUNDS[v["sound"]], dest)
                finally:
                    shutil.rmtree(work, ignore_errors=True)
            manifest.append({
                "file": name,
                "hook": v["hook"] + 1,
                "clips": [v["first"].name, v["mid"].name, v["end"].name],
                "audio": SOUNDS[v["sound"]]["file"].name,
                "audio_start": SOUNDS[v["sound"]]["start"],
                "sticker": ({"name": NEUTRAL_COMMENTERS[v["commenter"]], "comment": STICKER_COMMENT}
                            if STICKER else None),
                "hook_text": HOOKS[v["hook"]],
                "body_text": BODIES[v["hook"]],
            })
            print(f"[{i}/{args.n}] {name}", flush=True)
            if i % 10 == 0 or i == args.n:
                (args.out / "manifest.json").write_text(
                    json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
                )
    finally:
        shutil.rmtree(work_root, ignore_errors=True)

    for k, label in ((0, "начало"), (1, "середина"), (2, "конец")):
        c = Counter(m["clips"][k] for m in manifest)
        print(f"{label}: {len(c)} клипов, использование {min(c.values())}–{max(c.values())}")
    print(f"тексты: {dict(sorted(Counter(m['hook'] for m in manifest).items()))}")
    print(f"звуки: {dict(Counter(m['audio'][:24] for m in manifest))}")
    print(f"готово: {len(manifest)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
