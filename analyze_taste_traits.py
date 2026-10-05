#!/usr/bin/env python3
"""
Чем фото, которые человек выбирает, отличаются от отклонённых — 100 понятных
параметров, а не одна цифра модели.

Метки:
  A  ручная разметка label_frames.py (живое vs сток / ИИ)
  B  data/taste_history.json (да / нет при отборе в карусели); одна и та же
     картинка под разными пинами склеивается, спорные копии (и да, и нет)
     выкидываются
Параметры (100):
  пиксельные (37)        — свет, цвет, резкость, композиция
  смысловые (40)         — SigLIP, пары формулировок («если да» vs «если нет»)
  запрос, файл, разметка (15) — слова в запросе, место в выдаче, метка ИИ
                           Pinterest, размер оригинала, сжимаемость, порядок
                           разметки, повторы
  оценки моделей (8)     — живость (итог и части), вкус, похожесть на прошлые
                           «да», на ИИ-пины Pinterest
Для каждого: AUC (0.5 — не различает; > 0.5 — больше у выбранных), 95%
бутстрэп-интервал, медианы у выбранных и отклонённых, q (Манна–Уитни с
поправкой Бенджамини–Хохберга на число проверок). Плюс: какие параметры
дублируют друг друга, сколько угадывают все вместе, листы кадров, index.html.

  python analyze_taste_traits.py --pack out/label_pack_20261005 --out out/taste_traits_100
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import warnings
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"
OUT_ROOT = ROOT.parent.parent / "out" if ROOT.parent.name == ".worktrees" else ROOT / "out"

# пиксельные: имя → (группа, что измеряет)
PIXEL = {
    "яркость": ("Свет", "средняя яркость кадра"),
    "контраст": ("Свет", "разброс яркости"),
    "динамический диапазон": ("Свет", "от самых тёмных (1%) до самых светлых (99%) точек"),
    "светлота теней (подсветка)": ("Свет", "насколько светлые самые тёмные 5% — высоко, если тени «приподняты»"),
    "пересветы (% белого)": ("Свет", "доля выбитых в белое пикселей"),
    "провалы в чёрное (%)": ("Свет", "доля почти чёрных пикселей"),
    "тональное разнообразие": ("Свет", "энтропия гистограммы яркости"),
    "центр светлее краёв": ("Свет", "центр минус края по яркости (виньетка, свет на предмете)"),
    "верх светлее низа": ("Свет", "верхняя треть минус нижняя (окно, небо сверху)"),
    "неравномерный свет по кадру": ("Свет", "разброс яркости между 36 участками"),
    "насыщенность": ("Цвет", "средняя насыщенность"),
    "цветастость": ("Цвет", "метрика Хаслера — сколько разных ярких цветов"),
    "теплота (красное − синее)": ("Цвет", "средний сдвиг в тёплое"),
    "цветовой сдвиг (баланс белого)": ("Цвет", "насколько весь кадр окрашен в один оттенок"),
    "разнообразие оттенков": ("Цвет", "энтропия оттенков среди цветных пикселей"),
    "бежевые тона (%)": ("Цвет", "доля светлых малонасыщенных тёплых пикселей"),
    "зелень (%)": ("Цвет", "доля зелёных пикселей"),
    "телесные тона (%)": ("Цвет", "доля пикселей цвета кожи (ловит и бежевые стены)"),
    "пастельные тона (%)": ("Цвет", "доля светлых и блёклых пикселей"),
    "холодные тени (тонировка)": ("Цвет", "синее минус красное в тенях — признак цветокоррекции"),
    "резкость": ("Резкость и камера", "общая резкость (дисперсия лапласиана)"),
    "самый резкий участок": ("Резкость и камера", "резкость лучшего из 36 участков"),
    "разброс резкости по кадру": ("Резкость и камера", "одни участки резкие, другие размыты — малая ГРИП"),
    "размытие фона (центр резче краёв)": ("Резкость и камера", "резкость центра минус краёв"),
    "шум / зерно": ("Резкость и камера", "мелкий яркостный шум"),
    "цветовой шум": ("Резкость и камера", "цветные пятна шума — темнота и маленькая матрица"),
    "смаз в одну сторону": ("Резкость и камера", "градиенты по одной оси слабее — смаз движением"),
    "детали / захламлённость": ("Композиция", "плотность контуров"),
    "детали в центре, а не по краям": ("Композиция", "контуры в центре против краёв"),
    "главное смещено от центра": ("Композиция", "центр масс контуров далеко от центра кадра"),
    "зеркальная симметрия": ("Композиция", "левая половина похожа на правую"),
    "пустое пространство (%)": ("Композиция", "доля ровных участков без деталей"),
    "прямые линии": ("Композиция", "число длинных прямых (мебель, архитектура)"),
    "завал горизонта (°)": ("Композиция", "среднее отклонение длинных линий от горизонтали/вертикали"),
    "белый край кадра (студийный фон)": ("Композиция", "доля белых пикселей по краю"),
    "лица": ("Композиция", "число лиц (Haar)"),
    "вертикальность (h/w)": ("Композиция", "высота / ширина"),
}

# смысловые: (группа, имя, «если да», «если нет»)
PAIRS = [
    ("Что в кадре", "вид от первого лица", "a first person point of view photo", "a third person view photo"),
    ("Что в кадре", "в кадре руки", "a person's hands in the frame", "no hands in the frame"),
    ("Что в кадре", "в кадре человек", "a person in the photo", "no people in the photo"),
    ("Что в кадре", "селфи", "a selfie", "not a selfie"),
    ("Что в кадре", "зеркальное селфи", "a mirror selfie", "a photo without a mirror"),
    ("Что в кадре", "ноги в кадре", "feet or legs in the frame", "no feet or legs in the frame"),
    ("Что в кадре", "бытовые предметы вокруг, живой фон", "a background with everyday clutter", "an empty clean minimalist background"),
    ("Что в кадре", "беспорядок", "a messy untidy space", "a perfectly tidy space"),
    ("Что в кадре", "еда во время еды", "half-eaten food in the middle of a meal", "untouched perfectly arranged food"),
    ("Что в кадре", "экран телефона или ноутбука", "a phone or laptop screen", "no screens or devices"),
    ("Что в кадре", "животное", "a pet cat or dog", "no animals"),
    ("Что в кадре", "растения, цветы", "plants or flowers", "no plants or flowers"),
    ("Что в кадре", "кровать, постель", "a bed with sheets and pillows", "no bed"),
    ("Что в кадре", "предмет на белом фоне", "a product on a white background", "an object in a real environment"),
    ("Что в кадре", "текст или логотип на фото", "a photo with text or a logo", "a photo without any text"),
    ("Место", "обычная квартира, не журнал", "a regular lived-in apartment", "an interior design magazine photo"),
    ("Место", "на улице", "an outdoor photo", "an indoor photo"),
    ("Место", "в машине", "inside a car", "not inside a car"),
    ("Место", "кафе или ресторан", "inside a cafe or restaurant", "at home"),
    ("Место", "общий план комнаты", "a wide shot of a whole room", "a close-up of a detail"),
    ("Свет", "естественный свет, не студийный", "natural light from a window", "studio lighting with softboxes"),
    ("Свет", "тёмное, вечер/ночь", "a dark photo at night", "a bright daytime photo"),
    ("Свет", "тёплый уютный свет", "warm cozy lighting", "cold bluish lighting"),
    ("Свет", "вспышка", "a flash photo", "a photo without flash"),
    ("Свет", "тени от растений или жалюзи на стене", "shadows of plants or blinds on a wall", "a wall without shadow patterns"),
    ("Цвет", "яркие насыщенные цвета", "vivid saturated colors", "muted desaturated colors"),
    ("Стиль и постановка", "снято на телефон", "a casual photo taken with a smartphone", "a professional photograph taken with a DSLR camera"),
    ("Стиль и постановка", "случайный момент, не постановка", "an unposed everyday moment", "a staged styled photo shoot"),
    ("Стиль и постановка", "личное фото, не реклама", "a personal photo from someone's camera roll", "an advertisement or stock photo"),
    ("Стиль и постановка", "модель позирует", "a model posing for the camera", "a person not posing"),
    ("Стиль и постановка", "«эстетика Pinterest»", "a Pinterest aesthetic photo", "a random ordinary photo"),
    ("Стиль и постановка", "еда как фуд-фото", "professional food photography", "a casual snapshot of food"),
    ("Стиль и постановка", "раскладка сверху (flat lay)", "a styled flat lay from above", "a casual angle snapshot"),
    ("Стиль и постановка", "ровная симметричная композиция по центру", "a symmetrical centered composition", "an off-center casual composition"),
    ("Стиль и постановка", "натюрморт", "a styled still life arrangement", "objects left where they were"),
    ("Стиль и постановка", "кинематографично", "a cinematic film still", "a casual snapshot"),
    ("Стиль и постановка", "стоковое фото", "a stock photo", "an amateur photo"),
    ("Качество и ИИ", "настоящая фотография, не рендер", "a real photograph", "a 3d render or AI generated image"),
    ("Качество и ИИ", "неидеальное, чуть смазанное фото", "a slightly blurry imperfect photo", "a perfectly sharp crisp photo"),
    ("Качество и ИИ", "размытый фон, боке", "shallow depth of field with a blurry background", "everything in focus"),
]

# запрос, файл, разметка: имя → (группа, что измеряет)
META = {
    "в запросе pov": ("Запрос и выдача", "в поисковом запросе есть pov"),
    "в запросе candid": ("Запрос и выдача", "в запросе есть candid"),
    "в запросе aesthetic": ("Запрос и выдача", "в запросе есть aesthetic"),
    "в запросе iphone photo / photo dump": ("Запрос и выдача", "в запросе есть iphone photo или photo dump"),
    "в запросе real life": ("Запрос и выдача", "в запросе есть real life"),
    "голый предмет без модификатора": ("Запрос и выдача", "запрос — только предмет, без pov/candid/aesthetic/…"),
    "место в выдаче Pinterest": ("Запрос и выдача", "позиция пина в поиске (0 — первый)"),
    "Pinterest пометил как ИИ": ("Запрос и выдача", "флаг is_ai в выдаче Pinterest"),
    "в скольких запросах всплывает": ("Запрос и выдача", "число разных запросов, где встретился пин"),
    "ширина оригинала": ("Файл и разметка", "ширина исходной картинки, px"),
    "мегапиксели оригинала": ("Файл и разметка", "размер исходной картинки"),
    "пропорции телефонного кадра": ("Файл и разметка", "стороны 3:4, 9:16 или 9:19.5 (±2%)"),
    "сжимаемость (байт на пиксель)": ("Файл и разметка", "размер JPEG при одинаковом сжатии — сколько в кадре мелкой информации"),
    "порядок разметки": ("Файл и разметка", "когда фото попалось при разметке (0 — первым, 1 — последним)"),
    "повторы фото в отборе": ("Файл и разметка", "сколько раз та же картинка встречалась под разными пинами"),
}

MODELS = {
    "итоговая живость (как в фабрике)": "оценка UGC, по которой фабрика пускает кадр (порог 0.55)",
    "модель живости": "обученная модель живости (часть итоговой)",
    "zero-shot живость": "похожесть на описания «живого» против «стока» (часть итоговой)",
    "штраф эвристик стока": "штраф за признаки профи-съёмки (часть итоговой)",
    "вето стока": "сработало вето (1) или нет",
    "оценка вкуса (taste model)": "старая модель вкуса — училась на наборе B, там цифра завышена",
    "похожесть на прошлые «да»": "близость к прежним «да» минус к прежним «нет» (5 ближайших)",
    "похожесть на ИИ-пины Pinterest": "близость к 300 пинам, которые Pinterest пометил как ИИ",
}

PHONE_RATIOS = (4 / 3, 16 / 9, 19.5 / 9)
QUERY_MODS = r"\b(pov|candid|aesthetic|iphone|photo dump|real life|flash|alone|my|selfie)\b"


def _entropy(hist: np.ndarray) -> float:
    p = hist.astype(np.float64) / max(1.0, float(hist.sum()))
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum())


_FACE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def pixel_features(path: Path) -> dict:
    im = Image.open(path).convert("RGB")
    ow, oh = im.size
    im.thumbnail((512, 512))
    u8 = np.asarray(im)
    a = u8.astype(np.float32)
    g8 = cv2.cvtColor(u8, cv2.COLOR_RGB2GRAY)
    g = g8.astype(np.float32)
    hsv = cv2.cvtColor(u8, cv2.COLOR_RGB2HSV).astype(np.float32)
    lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    ycc = cv2.cvtColor(u8, cv2.COLOR_RGB2YCrCb).astype(np.float32)
    r, gg, b = a[..., 0], a[..., 1], a[..., 2]
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    H, W = g.shape
    inner = np.zeros_like(g, bool)
    inner[H // 4: 3 * H // 4, W // 4: 3 * W // 4] = True

    lap = cv2.Laplacian(g, cv2.CV_32F)
    th, tw = H // 6, W // 6
    tmean, tsharp = [], []
    for i in range(6):
        for j in range(6):
            sl = (slice(i * th, (i + 1) * th), slice(j * tw, (j + 1) * tw))
            tmean.append(g[sl].mean())
            tsharp.append(np.log1p(lap[sl].var()))
    tmean, tsharp = np.array(tmean), np.array(tsharp)

    rg, yb = r - gg, 0.5 * (r + gg) - b
    colorful = np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    p1, p5, p99 = np.percentile(g, [1, 5, 99])
    colored = (sat > 40) & (val > 40)
    hue_ent = _entropy(np.histogram(hue[colored], bins=18, range=(0, 180))[0]) if colored.sum() > 200 else 0.0
    shadows = g < 70
    cold_shadows = float((b - r)[shadows].mean()) if shadows.sum() > 200 else float("nan")
    cr, cb = ycc[..., 1], ycc[..., 2]
    chroma_noise = float(np.median(np.abs(cr - cv2.GaussianBlur(cr, (3, 3), 0)))
                         + np.median(np.abs(cb - cv2.GaussianBlur(cb, (3, 3), 0))))
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    aniso = abs(np.log((gx ** 2).sum() + 1) - np.log((gy ** 2).sum() + 1))

    edges = cv2.Canny(g8, 80, 160)
    e = edges > 0
    ys, xs = np.nonzero(e)
    off = float(np.hypot(xs.mean() / W - 0.5, ys.mean() / H - 0.5)) if len(xs) else 0.0
    small = cv2.resize(g, (64, 64), interpolation=cv2.INTER_AREA)
    m = cv2.blur(g, (15, 15))
    lstd = np.sqrt(np.maximum(cv2.blur(g * g, (15, 15)) - m * m, 0))
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 60, minLineLength=int(0.2 * min(H, W)), maxLineGap=4)
    devs = []
    for x1, y1, x2, y2 in (lines[:, 0] if lines is not None else []):
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180
        d = min(ang, 180 - ang, abs(ang - 90))
        if d < 20:
            devs.append(d)
    border = np.concatenate([a[:8].reshape(-1, 3), a[-8:].reshape(-1, 3), a[:, :8].reshape(-1, 3), a[:, -8:].reshape(-1, 3)])
    faces = len(_FACE.detectMultiScale(g8, 1.1, 5, minSize=(24, 24)))
    center_sharp = float(lap[inner].var())
    edge_sharp = float(lap[~inner].var())
    return {
        "яркость": float(g.mean()),
        "контраст": float(g.std()),
        "динамический диапазон": float(p99 - p1),
        "светлота теней (подсветка)": float(p5),
        "пересветы (% белого)": float((g > 250).mean() * 100),
        "провалы в чёрное (%)": float((g < 8).mean() * 100),
        "тональное разнообразие": _entropy(np.histogram(g, bins=64, range=(0, 256))[0]),
        "центр светлее краёв": float(g[inner].mean() - g[~inner].mean()),
        "верх светлее низа": float(g[: H // 3].mean() - g[-(H // 3):].mean()),
        "неравномерный свет по кадру": float(tmean.std() / (tmean.mean() + 1)),
        "насыщенность": float(sat.mean()),
        "цветастость": float(colorful),
        "теплота (красное − синее)": float((r - b).mean()),
        "цветовой сдвиг (баланс белого)": float(np.hypot(lab[..., 1].mean() - 128, lab[..., 2].mean() - 128)),
        "разнообразие оттенков": hue_ent,
        "бежевые тона (%)": float(((hue >= 8) & (hue <= 25) & (sat >= 20) & (sat <= 100) & (val > 140)).mean() * 100),
        "зелень (%)": float(((hue >= 35) & (hue <= 85) & (sat > 60) & (val > 40)).mean() * 100),
        "телесные тона (%)": float(((cr >= 135) & (cr <= 173) & (cb >= 77) & (cb <= 127) & (ycc[..., 0] > 50)).mean() * 100),
        "пастельные тона (%)": float(((val > 190) & (sat < 60)).mean() * 100),
        "холодные тени (тонировка)": cold_shadows,
        "резкость": float(np.log1p(lap.var())),
        "самый резкий участок": float(tsharp.max()),
        "разброс резкости по кадру": float(tsharp.std()),
        "размытие фона (центр резче краёв)": float(np.log1p(center_sharp) - np.log1p(edge_sharp)),
        "шум / зерно": float(np.median(np.abs(g - cv2.GaussianBlur(g, (3, 3), 0)))),
        "цветовой шум": chroma_noise,
        "смаз в одну сторону": float(aniso),
        "детали / захламлённость": float(e.mean() * 100),
        "детали в центре, а не по краям": float(np.log((e[inner].mean() + 0.002) / (e[~inner].mean() + 0.002))),
        "главное смещено от центра": off,
        "зеркальная симметрия": float(-np.abs(small - small[:, ::-1]).mean()),
        "пустое пространство (%)": float((lstd < 4).mean() * 100),
        "прямые линии": float(0 if lines is None else len(lines)),
        "завал горизонта (°)": float(np.median(devs)) if devs else float("nan"),
        "белый край кадра (студийный фон)": float((border.min(axis=1) > 235).mean() * 100),
        "лица": float(faces),
        "вертикальность (h/w)": float(oh / max(1, ow)),
        "пропорции телефонного кадра": float(any(abs(max(ow, oh) / max(1, min(ow, oh)) / q - 1) < 0.02 for q in PHONE_RATIOS)),
        "сжимаемость (байт на пиксель)": path.stat().st_size / max(1, ow * oh),
        "_w": float(ow), "_h": float(oh),
    }


def query_features(q: str) -> dict:
    q = q.lower()
    return {
        "в запросе pov": float(bool(re.search(r"\bpov\b", q))),
        "в запросе candid": float("candid" in q),
        "в запросе aesthetic": float("aesthetic" in q),
        "в запросе iphone photo / photo dump": float("iphone" in q or "photo dump" in q),
        "в запросе real life": float("real life" in q),
        "голый предмет без модификатора": float(not re.search(QUERY_MODS, q)),
    }


def load_labels(pack: Path) -> list[dict]:
    rows = []
    pk = {r["pin_id"]: r for r in json.loads((pack / "pack.json").read_text(encoding="utf-8"))}
    votes = json.loads((pack / "votes.json").read_text(encoding="utf-8"))
    for i, (pid, v) in enumerate(votes.items()):
        if v != "unclear" and pid in pk:
            rows.append({"set": "A", "pin": pid, "path": pack / "imgs" / pk[pid]["file"], "key": f"labelpack:{pid}",
                         "y": 1 if v == "live" else 0, "search": pk[pid]["search"],
                         "порядок разметки": i / max(1, len(votes) - 1)})
    hist = json.loads((DATA / "taste_history.json").read_text(encoding="utf-8"))
    yes, no = set(map(str, hist["yes"])), set(map(str, hist["no"]))
    order = {str(p): i / max(1, len(hist["seen"]) - 1) for i, p in enumerate(hist["seen"])}
    for f in sorted((DATA / "cache" / "clean_photos").glob("*.jpg")):
        pid = f.name.split("_")[0]
        if pid in yes or pid in no:
            rows.append({"set": "B", "pin": pid, "path": f, "key": f"clean:{f.stem}", "y": 1 if pid in yes else 0,
                         "порядок разметки": order.get(pid, float("nan"))})
    return rows


def search_meta(srcs: list[Path]) -> tuple[dict, dict]:
    """(место в выдаче по (запрос, пин), is_ai по пину); пин → число запросов."""
    rank: dict[tuple[str, str], int] = {}
    is_ai: dict[str, bool] = {}
    queries: dict[str, set] = {}
    for src in srcs:
        f = src / "search_cache.json"
        if not f.exists():
            continue
        for q, pins in json.loads(f.read_text(encoding="utf-8")).items():
            for i, p in enumerate(pins):
                pid = str(p["pin_id"])
                rank.setdefault((q, pid), i)
                is_ai[pid] = bool(p.get("is_ai")) or is_ai.get(pid, False)
                queries.setdefault(pid, set()).add(q)
    return {"rank": rank, "is_ai": is_ai}, {k: len(v) for k, v in queries.items()}


def dedupe_b(rows: list[dict], V: np.ndarray) -> tuple[list[int], dict]:
    """Склеить одинаковые картинки в B. Вернуть индексы строк, которые оставить."""
    idx = [i for i, r in enumerate(rows) if r["set"] == "B"]
    X = V[idx]
    S = X @ X.T
    group = [-1] * len(idx)
    keep, stats = [], {"копий": 0, "спорных групп": 0, "групп": 0}
    for i in range(len(idx)):
        if group[i] >= 0:
            continue
        mem = [j for j in np.where(S[i] > 0.97)[0] if group[j] < 0]
        for j in mem:
            group[j] = i
        stats["групп"] += 1
        stats["копий"] += len(mem) - 1
        if len({rows[idx[j]]["y"] for j in mem}) > 1:
            stats["спорных групп"] += 1
            continue
        rows[idx[i]]["повторы фото в отборе"] = float(len(mem))
        keep.append(idx[i])
    return keep, stats


def fast_auc(x: np.ndarray, y: np.ndarray) -> float:
    from scipy.stats import rankdata

    rk = rankdata(x)
    n1 = y.sum()
    n0 = len(y) - n1
    return float((rk[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def stat(x: np.ndarray, y: np.ndarray, n_boot: int = 1000, seed: int = 0) -> dict | None:
    from scipy.stats import mannwhitneyu

    ok = ~np.isnan(x)
    x, y = x[ok], y[ok]
    if len(y) < 30 or y.min() == y.max() or np.ptp(x) == 0:
        return None
    auc = fast_auc(x, y)
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(n_boot):
        i = rng.integers(0, len(y), len(y))
        if y[i].min() != y[i].max():
            bs.append(fast_auc(x[i], y[i]))
    p = float(mannwhitneyu(x[y == 1], x[y == 0], alternative="two-sided").pvalue)
    binary = set(np.unique(x).tolist()) <= {0.0, 1.0}
    if binary:
        sel, rej = float(x[y == 1].mean() * 100), float(x[y == 0].mean() * 100)
    else:
        sel, rej = float(np.median(x[y == 1])), float(np.median(x[y == 0]))
    return {"auc": auc, "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)), "p": p,
            "n": int(len(y)), "binary": binary, "sel": sel, "rej": rej}


def bh(ps: list[float]) -> list[float]:
    ps = np.asarray(ps, dtype=float)
    n = len(ps)
    o = np.argsort(ps)
    q = ps[o] * n / (np.arange(n) + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(n)
    out[o] = np.minimum(q, 1)
    return out.tolist()


def fmt(v: float, binary: bool) -> str:
    if binary:
        return f"{v:.0f}%"
    a = abs(v)
    return f"{v:.3f}" if a < 1 else (f"{v:.2f}" if a < 10 else f"{v:.1f}" if a < 100 else f"{v:.0f}")


def verdict(d: dict) -> tuple[str, str]:
    """(текст, css-класс)"""
    sig = {s: d[s] is not None and d[s]["q"] < 0.05 for s in ("A", "B")}
    dirs = {s: d[s]["auc"] > 0.5 for s in ("A", "B") if sig[s]}
    if sig["A"] and sig["B"]:
        if dirs["A"] == dirs["B"]:
            return ("у выбранных" if dirs["A"] else "у отклонённых"), ("sel" if dirs["A"] else "rej")
        return "в A и B наоборот", "mix"
    for s in ("A", "B"):
        if sig[s]:
            other = "B" if s == "A" else "A"
            side = "у выбранных" if dirs[s] else "у отклонённых"
            where = f"есть только в {s}" if d[other] is None else f"только в {s}"
            return f"{side} — {where}", ("sel1" if dirs[s] else "rej1")
    return "не различает", "none"


def strength(d: dict) -> float:
    v = [abs(d[s]["auc"] - 0.5) for s in ("A", "B") if d[s] is not None and d[s]["q"] < 0.05]
    w = [abs(d[s]["auc"] - 0.5) for s in ("A", "B") if d[s] is not None]
    return (sum(v) / 2 + 0.001 * sum(w)) if v else 0.001 * sum(w)


def multivariate(rows: list[dict], names_by_group: dict[str, list[str]], s: str) -> dict:
    from sklearn.linear_model import LogisticRegressionCV
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    sub = [r for r in rows if r["set"] == s]
    y = np.array([r["y"] for r in sub])

    def matrix(names):
        X = np.array([[r.get(n, np.nan) for n in names] for r in sub], dtype=float)
        keep = [j for j in range(X.shape[1]) if not np.isnan(X[:, j]).all() and np.nanstd(X[:, j]) > 0]
        X = X[:, keep]
        X = np.where(np.isnan(X), np.nanmedian(X, axis=0), X)
        return X, [names[j] for j in keep]

    def model():
        return make_pipeline(StandardScaler(), LogisticRegressionCV(Cs=8, penalty="l1", solver="liblinear",
                                                                    scoring="roc_auc", cv=4, max_iter=3000))

    cv = StratifiedKFold(5, shuffle=True, random_state=0)
    res = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for label, names in names_by_group.items():
            X, _kept = matrix(names)
            if X.shape[1] == 0:
                continue
            if X.shape[1] == 1:
                res[label] = {"auc": float(roc_auc_score(y, X[:, 0])), "k": 1}
                continue
            p = cross_val_predict(model(), X, y, cv=cv, method="predict_proba")[:, 1]
            res[label] = {"auc": float(roc_auc_score(y, p)), "k": X.shape[1]}
        X, kept = matrix(names_by_group["все параметры без моделей"])
        pipe = model().fit(X, y)
    coef = pipe[-1].coef_[0]
    top = sorted([(kept[j], float(coef[j])) for j in range(len(kept)) if abs(coef[j]) > 1e-6], key=lambda t: -abs(t[1]))
    res["_вклад"] = top[:15]
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--search", type=Path, nargs="*",
                    default=[OUT_ROOT / "query_liveness_v2", OUT_ROOT / "filler_bank_probe"])
    ap.add_argument("--ai-pins", type=Path, default=OUT_ROOT / "pinterest_ai_pins")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from core.taste_classifier import get_taste_classifier
    from core.taste_embedder import get_embedder
    from core.ugc_filter import get_ugc_filter

    out = args.out
    (out / "sheets").mkdir(parents=True, exist_ok=True)
    rows = load_labels(args.pack)
    print(f"меток: A {sum(r['set'] == 'A' for r in rows)}, B {sum(r['set'] == 'B' for r in rows)}", flush=True)

    emb = get_embedder()
    vecs = []
    for i in range(0, len(rows), 64):
        ims = [Image.open(r["path"]).convert("RGB") for r in rows[i:i + 64]]
        vecs.append(emb.embed_images(ims, cache_keys=[r["key"] for r in rows[i:i + 64]]))
    V = np.vstack(vecs).astype(np.float32)

    keep_b, dstats = dedupe_b(rows, V)
    keep = [i for i, r in enumerate(rows) if r["set"] == "A"] + keep_b
    rows = [rows[i] for i in keep]
    V = V[keep]
    print(f"B после склейки дублей: {len(keep_b)} ({dstats})", flush=True)

    for k, r in enumerate(rows):
        r.update(pixel_features(r["path"]))
        if r["set"] == "B":
            r["ширина оригинала"] = r["_w"]
            r["мегапиксели оригинала"] = r["_w"] * r["_h"] / 1e6
        if k % 200 == 0:
            print(f"  пиксели {k}/{len(rows)}", flush=True)

    sm, nq = search_meta(args.search)
    for r in rows:
        if r["set"] == "A":
            r.update(query_features(r["search"]))
            rk = sm["rank"].get((r["search"], r["pin"]))
            r["место в выдаче Pinterest"] = float(rk) if rk is not None else float("nan")
            r["Pinterest пометил как ИИ"] = float(sm["is_ai"].get(r["pin"], False))
            r["в скольких запросах всплывает"] = float(nq.get(r["pin"], 1))

    tp = emb.embed_texts([p for _g, _n, p, _q in PAIRS])
    tn = emb.embed_texts([q for _g, _n, _p, q in PAIRS])
    sem = V @ tp.T - V @ tn.T
    for k, r in enumerate(rows):
        for j, (_g, name, _p, _q) in enumerate(PAIRS):
            r[name] = float(sem[k, j])

    filt = get_ugc_filter()
    for i in range(0, len(rows), 64):
        chunk = rows[i:i + 64]
        ims = [Image.open(r["path"]).convert("RGB") for r in chunk]
        for r, d in zip(chunk, filt.score_details(ims, image_vecs=V[i:i + 64])):
            r["итоговая живость (как в фабрике)"] = float(d["score"])
            r["модель живости"] = float(d["supervised"]) if d["supervised"] is not None else float("nan")
            r["zero-shot живость"] = float(d["zero_shot"])
            r["штраф эвристик стока"] = float(d["penalty"])
            r["вето стока"] = float(d["vetoed"])
    for r, t in zip(rows, get_taste_classifier().predict_taste_scores_from_vecs(V)):
        r["оценка вкуса (taste model)"] = float(t)
    b_idx = np.array([i for i, r in enumerate(rows) if r["set"] == "B"])
    b_pos = np.array([rows[i]["y"] == 1 for i in b_idx])
    S = V @ V[b_idx].T
    S[S > 0.97] = -1  # сама картинка и её копии
    for i, r in enumerate(rows):
        sy = np.sort(S[i, b_pos])[-5:].mean()
        sn = np.sort(S[i, ~b_pos])[-5:].mean()
        r["похожесть на прошлые «да»"] = float(sy - sn)
    import train_liveness_v2 as T

    C = T.load_c(args.ai_pins)
    SC = V @ C.T
    SC[SC > 0.97] = -1
    for i, r in enumerate(rows):
        r["похожесть на ИИ-пины Pinterest"] = float(np.sort(SC[i])[-5:].mean())

    reg = []
    for n, (g, desc) in PIXEL.items():
        reg.append({"параметр": n, "группа": g, "что": desc, "вид": "пиксели"})
    for g, n, p, q in PAIRS:
        reg.append({"параметр": n, "группа": g, "что": f"«{p}» против «{q}»", "вид": "смысл"})
    for n, (g, desc) in META.items():
        reg.append({"параметр": n, "группа": g, "что": desc, "вид": "переменная"})
    for n, desc in MODELS.items():
        reg.append({"параметр": n, "группа": "Оценки моделей", "что": desc, "вид": "модель"})
    assert len(reg) == 100, len(reg)

    for s in ("A", "B"):
        sub = [r for r in rows if r["set"] == s]
        y = np.array([r["y"] for r in sub])
        for d in reg:
            d[s] = stat(np.array([r.get(d["параметр"], np.nan) for r in sub], dtype=float), y)
        tested = [d for d in reg if d[s] is not None]
        for d, q in zip(tested, bh([d[s]["p"] for d in tested])):
            d[s]["q"] = q
    for d in reg:
        d["вывод"], d["css"] = verdict(d)
        d["сила"] = strength(d)

    try:
        import pandas as pd

        df = pd.DataFrame([{d["параметр"]: r.get(d["параметр"], np.nan) for d in reg} for r in rows])
        cor = df.corr(method="spearman", min_periods=60)
        for d in reg:
            c = cor[d["параметр"]].drop(d["параметр"]).dropna()
            c = c[c.abs() >= 0.6].sort_values(key=lambda t: -t.abs())
            d["похожие"] = [(k, float(v)) for k, v in c.head(3).items()]
    except Exception as e:  # noqa: BLE001
        print("корреляции:", e)
        for d in reg:
            d["похожие"] = []

    groups = {
        "пиксели (37)": [d["параметр"] for d in reg if d["вид"] == "пиксели"],
        "смысловые (40)": [d["параметр"] for d in reg if d["вид"] == "смысл"],
        "запрос, файл, разметка (15)": [d["параметр"] for d in reg if d["вид"] == "переменная"],
        "все параметры без моделей": [d["параметр"] for d in reg if d["вид"] != "модель"],
        "модель живости": ["модель живости"],
        "итоговая живость (как в фабрике)": ["итоговая живость (как в фабрике)"],
    }
    print("многомерная проверка…", flush=True)
    mv = {s: multivariate(rows, groups, s) for s in ("A", "B")}

    font = ImageFont.truetype("arial.ttf", 16)
    ranked = sorted(reg, key=lambda d: -d["сила"])
    sheet_of = {}
    for d in ranked:
        if d["css"] == "none" or d["вид"] == "переменная" or len(sheet_of) >= 45:
            continue
        f = d["параметр"]
        sets = [s for s in ("A", "B") if d[s] is not None and d[s]["q"] < 0.05]
        pool = [r for r in rows if r["set"] in sets and not np.isnan(r.get(f, np.nan))]
        hi = np.mean([d[s]["auc"] for s in sets]) > 0.5
        sel = sorted([r for r in pool if r["y"] == 1], key=lambda r: -r[f] if hi else r[f])[:8]
        rej = sorted([r for r in pool if r["y"] == 0], key=lambda r: r[f] if hi else -r[f])[:8]
        tw, th = 170, 220
        s = Image.new("RGB", (8 * tw, 2 * (th + 26) + 34), (24, 24, 24))
        dr = ImageDraw.Draw(s)
        aucs = " · ".join(f"{k} {d[k]['auc']:.2f}" for k in ("A", "B") if d[k] is not None)
        dr.text((6, 6), f"{f}: AUC {aucs}  ({'больше' if hi else 'меньше'} у выбранных)", fill=(255, 230, 120), font=font)
        for row_i, (lab, items) in enumerate((
                ("ВЫБРАНО — " + ("признак сильнее всего" if hi else "признака меньше всего"), sel),
                ("ОТКЛОНЕНО — " + ("признака меньше всего" if hi else "признак сильнее всего"), rej))):
            y0 = 34 + row_i * (th + 26)
            dr.text((6, y0), lab, fill=(140, 220, 160) if row_i == 0 else (240, 140, 140), font=font)
            for j, r in enumerate(items):
                im = Image.open(r["path"]).convert("RGB")
                im.thumbnail((tw - 4, th - 4))
                s.paste(im, (j * tw + 2, y0 + 22))
        fn = f"{len(sheet_of) + 1:02d}_{re.sub(r'[^0-9A-Za-zА-Яа-яЁё]+', '_', f).strip('_')[:40]}.jpg"
        s.save(out / "sheets" / fn, quality=85)
        sheet_of[f] = fn

    import random

    rng = random.Random(4)
    for lab, yv in (("live", 1), ("stock", 0)):
        items = [r for r in rows if r["set"] == "A" and r["y"] == yv]
        rng.shuffle(items)
        tw, th = 160, 210
        s = Image.new("RGB", (10 * tw, 4 * th), (24, 24, 24))
        for j, r in enumerate(items[:40]):
            im = Image.open(r["path"]).convert("RGB")
            im.thumbnail((tw - 4, th - 4))
            s.paste(im, ((j % 10) * tw + 2, (j // 10) * th + 2))
        s.save(out / "sheets" / f"00_A_{lab}.jpg", quality=85)

    def cell(d, s):
        t = d[s]
        if t is None:
            return "—"
        return (f"{t['auc']:.2f} ({t['lo']:.2f}–{t['hi']:.2f}) q={t['q']:.3f} · "
                f"{fmt(t['sel'], t['binary'])} / {fmt(t['rej'], t['binary'])}")

    na = sum(r["set"] == "A" for r in rows)
    nb = sum(r["set"] == "B" for r in rows)
    L = ["# 100 параметров: чем выбранные фото отличаются от отклонённых", "",
         f"A — новая разметка «живое/сток» ({na} фото); B — прежний отбор «да/нет» ({nb} фото после склейки "
         f"{dstats['копий']} копий, {dstats['спорных групп']} спорных групп выкинуто). AUC: 0.50 — не различает, "
         "выше — больше у выбранных. q — вероятность случайности с поправкой на 100 проверок (< 0.05 — надёжно). "
         "После q: значение у выбранных / у отклонённых (медиана или доля).", "",
         "| № | группа | параметр | A | B | вывод | похожие |", "|---|---|---|---|---|---|---|"]
    for i, d in enumerate(ranked, 1):
        sim = ", ".join(f"{k} ({v:+.2f})" for k, v in d["похожие"])
        L.append(f"| {i} | {d['группа']} | {d['параметр']} | {cell(d, 'A')} | {cell(d, 'B')} | {d['вывод']} | {sim} |")
    L += ["", "## Сколько угадывают вместе (5-кратная проверка, AUC)", "", "| набор параметров | A | B |", "|---|---|---|"]
    for g in groups:
        L.append(f"| {g} | {mv['A'].get(g, {}).get('auc', float('nan')):.2f} | {mv['B'].get(g, {}).get('auc', float('nan')):.2f} |")
    for s in ("A", "B"):
        L += ["", f"Независимый вклад в {s} (L1, стандартизовано; + за выбранные):",
              ", ".join(f"{n} {c:+.2f}" for n, c in mv[s]["_вклад"])]
    (out / "traits.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (out / "traits.json").write_text(json.dumps({"params": reg, "multivariate": mv, "dedupe": dstats, "n": {"A": na, "B": nb}},
                                                ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    import csv

    with (out / "rows.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["set", "pin", "y", "file"] + [d["параметр"] for d in reg])
        for r in rows:
            wr.writerow([r["set"], r["pin"], r["y"], str(r["path"])] + [r.get(d["параметр"], "") for d in reg])
    write_html(out, reg, ranked, mv, groups, sheet_of, na, nb, dstats)
    print("\n".join(L))
    print(f"\n→ {out}")
    return 0


GROUP_ORDER = ["Стиль и постановка", "Что в кадре", "Место", "Свет", "Цвет", "Резкость и камера", "Композиция",
               "Качество и ИИ", "Запрос и выдача", "Файл и разметка", "Оценки моделей"]


def write_html(out, reg, ranked, mv, groups, sheet_of, na, nb, dstats) -> None:
    e = html.escape

    def bar(t):
        if t is None:
            return '<td class="na">—</td>'
        x = (t["auc"] - 0.5) * 200
        side = "r" if x >= 0 else "l"
        weak = "" if t["q"] < 0.05 else " weak"
        vals = f"{fmt(t['sel'], t['binary'])} / {fmt(t['rej'], t['binary'])}"
        return (f'<td><div class="bar"><span class="{side}{weak}" style="width:{min(abs(x), 100) / 2:.1f}%"></span></div>'
                f'<b>{t["auc"]:.2f}</b> <small>{t["lo"]:.2f}–{t["hi"]:.2f} · q {t["q"]:.3f}</small><br>'
                f'<small>выбр / откл: {vals}</small></td>')

    def row(i, d):
        sim = "; ".join(f"{e(k)} {v:+.2f}" for k, v in d["похожие"])
        sh = sheet_of.get(d["параметр"])
        link = f'<a href="sheets/{e(sh)}" target="_blank">примеры</a>' if sh else ""
        return (f'<tr class="{d["css"]}"><td class="n">{i}</td><td><b>{e(d["параметр"])}</b><br><small>{e(d["что"])}</small></td>'
                f'{bar(d["A"])}{bar(d["B"])}<td class="verdict">{e(d["вывод"])}</td><td><small>{sim}</small></td><td>{link}</td></tr>')

    num = {d["параметр"]: i for i, d in enumerate(ranked, 1)}
    head = ('<tr><th>№</th><th>параметр</th><th>A: новая разметка</th><th>B: прежний отбор</th><th>вывод</th>'
            '<th>похож на</th><th></th></tr>')
    parts = ['<h2>Сильнее всего — за выбор и за отказ</h2><div class="two">']
    for title, css in (("Больше у выбранных", ("sel", "sel1")), ("Больше у отклонённых", ("rej", "rej1"))):
        parts.append(f"<div><h3>{title}</h3><ol>")
        for d in [d for d in ranked if d["css"] in css][:15]:
            sh = sheet_of.get(d["параметр"])
            aucs = " · ".join(f"{s} {d[s]['auc']:.2f}" for s in ("A", "B") if d[s] is not None)
            name = f'<a href="sheets/{e(sh)}" target="_blank">{e(d["параметр"])}</a>' if sh else e(d["параметр"])
            parts.append(f"<li>{name} <small>{aucs} · {e(d['вывод'])}</small></li>")
        parts.append("</ol></div>")
    parts.append("</div><h2>Сколько угадывают вместе</h2><table class='mv'><tr><th>набор</th><th>A</th><th>B</th></tr>")
    for g in groups:
        parts.append(f"<tr><td>{e(g)}</td><td>{mv['A'].get(g, {}).get('auc', float('nan')):.2f}</td>"
                     f"<td>{mv['B'].get(g, {}).get('auc', float('nan')):.2f}</td></tr>")
    parts.append("</table>")
    for s in ("A", "B"):
        parts.append(f"<p><b>Независимый вклад в {s}</b> (+ за выбранные): "
                     + ", ".join(f"{e(n)} {c:+.2f}" for n, c in mv[s]["_вклад"]) + "</p>")
    for g in GROUP_ORDER:
        ds = sorted([d for d in reg if d["группа"] == g], key=lambda d: -d["сила"])
        parts.append(f"<h2>{e(g)} <small>({len(ds)})</small></h2><table>{head}")
        parts += [row(num[d["параметр"]], d) for d in ds]
        parts.append("</table>")
    doc = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>100 параметров вкуса</title><style>
:root{{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66;--line:#e4e3de;--sel:#2f8f5b;--rej:#c4473a;--selbg:#eaf6ee;--rejbg:#fbecea}}
@media (prefers-color-scheme:dark){{:root{{--bg:#191917;--fg:#ecebe6;--mut:#9a9992;--line:#33322e;--sel:#5cc28a;--rej:#e8776b;--selbg:#1f2e24;--rejbg:#33201d}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1400px;padding:16px}}
h1{{font-size:22px}} h2{{margin-top:32px;font-size:18px}} small{{color:var(--mut)}} a{{color:inherit}}
table{{border-collapse:collapse;width:100%}} td,th{{border-bottom:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}}
td.n{{color:var(--mut);width:28px}} tr.sel td.verdict,tr.sel1 td.verdict{{color:var(--sel);font-weight:600}}
tr.rej td.verdict,tr.rej1 td.verdict{{color:var(--rej);font-weight:600}} tr.sel{{background:var(--selbg)}} tr.rej{{background:var(--rejbg)}}
tr.none td{{opacity:.6}} .bar{{position:relative;height:8px;background:var(--line);border-radius:4px;margin:2px 0 4px;width:160px}}
.bar:after{{content:"";position:absolute;left:50%;top:-2px;height:12px;border-left:1px solid var(--mut)}}
.bar span{{position:absolute;top:0;height:8px;border-radius:4px}} .bar .r{{left:50%;background:var(--sel)}} .bar .l{{right:50%;background:var(--rej)}}
.bar .weak{{opacity:.35}} .two{{display:grid;grid-template-columns:1fr 1fr;gap:24px}} table.mv{{width:auto}}
@media (max-width:800px){{.two{{grid-template-columns:1fr}} table{{display:block;overflow-x:auto}}}}
</style></head><body>
<h1>100 параметров: что ты выбираешь и что отклоняешь</h1>
<p>A — новая разметка «живое / сток» ({na} фото). B — прежний отбор «да / нет» ({nb} фото; склеено {dstats['копий']} копий,
выкинуто {dstats['спорных групп']} спорных групп). AUC 0.50 — не различает; зелёная полоса — больше у выбранных, красная — у отклонённых;
бледная — может быть случайностью (q ≥ 0.05 с поправкой на 100 проверок). «выбр / откл» — медиана или доля у выбранных и у отклонённых.</p>
{''.join(parts)}
</body></html>"""
    (out / "index.html").write_text(doc, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
