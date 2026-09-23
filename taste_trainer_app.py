#!/usr/bin/env python3
"""
Быстрая галерея разметки личного вкуса.

Только чистые фоны БЕЗ запечённого текста слайдов:
  - test_downloads/ и data/cache/
  - при нехватке (<60) или по кнопке — Random Word Queries → Pinterest (core/harvester.py)

Обучение — локальный SigLIP + LogisticRegression (без API).

Запуск: python taste_trainer_app.py
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Callable

from PIL import Image, ImageFilter, ImageStat, ImageTk


def _open_rgb(path: Path) -> Image.Image:
    with Image.open(path) as img:
        return img.convert("RGB")

ROOT = Path(__file__).resolve().parent
TEST_DOWNLOADS = ROOT / "test_downloads"
DATA_CACHE = ROOT / "data" / "cache"
CLEAN_CACHE = DATA_CACHE / "clean_photos"
REJECT_PATH = ROOT / "data" / "taste_rejects.json"  # legacy
HISTORY_PATH = ROOT / "data" / "taste_history.json"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

GALLERY_N = 90
PINTEREST_TARGET = 95
MIN_DISK_PHOTOS = 60
TASTE_KEEP_MIN = 0.55  # в тренере чуть мягче фабрики (0.60)
MAX_NO_RATIO = 2.0  # НЕТ не больше, чем 2× ДА — иначе модель учит «всё плохо»
MIN_NO_SAMPLES = 20  # но совсем без негативов линейная граница не строится
HASH_SIZE = 12
# порог похожести на уже отмеченные НЕТ (из 144 бит)
HASH_MAX_DIST = 16
HISTORY_MAX = 8000
HASH_MAX = 2500
COLS = 6
THUMB_W = 148
THUMB_H = 196
TARGET_YES = 40
TARGET_NO = 40
ZOOM_H = 680
DOUBLE_CLICK_MS = 240

BG = "#1a1b1e"
PANEL = "#24262b"
PANEL2 = "#2c2f36"
FG = "#f2f2f2"
MUTED = "#9aa0a6"
YES = "#3ddc97"
NO = "#e74c3c"
BORDER = "#3a3f48"
OVERLAY_BG = "#0a0b0d"

# 0 сброс, 1 ДА, 2 НЕТ
STATE_COLORS = {0: BORDER, 1: YES, 2: NO}
STATE_CAPTION = {0: "", 1: "ДА", 2: "НЕТ"}

# ---------------------------------------------------------------------------
# Random Query Synthesizer — 80+ бытовых существительных + атмосфера
# ---------------------------------------------------------------------------

RANDOM_NOUNS: tuple[str, ...] = (
    "coat",
    "bicycle",
    "umbrella",
    "dog",
    "cat",
    "piano",
    "train",
    "bakery",
    "croissant",
    "stairs",
    "guitar",
    "books",
    "mirror",
    "boots",
    "bridge",
    "subway",
    "tea",
    "pottery",
    "vinyl",
    "lake",
    "rooftop",
    "painting",
    "flowers",
    "camera",
    "typewriter",
    "balcony",
    "doorway",
    "kitchen",
    "bench",
    "puddle",
    "scarf",
    "window",
    "clock",
    "sneakers",
    "mug",
    "lamp",
    "sofa",
    "blanket",
    "toaster",
    "newspaper",
    "headphones",
    "backpack",
    "journal",
    "candles",
    "plant",
    "keys",
    "wallet",
    "suitcase",
    "tram",
    "ferry",
    "market",
    "bookstore",
    "library",
    "hallway",
    "fireplace",
    "bathtub",
    "sink",
    "fridge",
    "pan",
    "bread",
    "apples",
    "oranges",
    "cheese",
    "wine",
    "coffee",
    "pastry",
    "sandwich",
    "sneakers",
    "hat",
    "gloves",
    "jacket",
    "jeans",
    "sweater",
    "raincoat",
    "postcard",
    "envelope",
    "stamps",
    "sketchbook",
    "paintbrush",
    "easel",
    "record",
    "speaker",
    "radio",
    "telephone",
    "doorbell",
    "fence",
    "garden",
    "porch",
    "driveway",
    "mailbox",
    "bicycle",
    "scooter",
    "skateboard",
    "helmet",
    "tent",
    "campfire",
    "thermos",
    "lantern",
    "map",
    "compass",
    "binoculars",
    "telescope",
    "shells",
    "pebbles",
    "moss",
    "ivy",
    "vase",
    "bowl",
    "chopsticks",
    "napkin",
    "tablecloth",
    "curtains",
    "rug",
    "pillow",
    "mattress",
    "hanger",
    "iron",
    "sewing",
    "yarn",
    "knitting",
    "toolbox",
    "hammer",
    "nails",
    "woodpile",
)

RANDOM_MOODS: tuple[str, ...] = (
    "rainy",
    "morning",
    "dusk",
    "foggy",
    "golden hour",
    "cozy",
    "candid",
    "messy",
    "quiet",
    "shadows",
    "sunny",
    "autumn",
    "evening",
)

QUERY_BATCH_MIN = 10
QUERY_BATCH_MAX = 12
PER_QUERY_MIN = 7
PER_QUERY_MAX = 8


def synthesize_random_queries(count: int | None = None) -> list[str]:
    """
    Случайные пары noun + mood → '{noun} {mood} candid aesthetic'.
    На прогон: 10–12 уникальных запросов.
    """
    n = count if count is not None else random.randint(QUERY_BATCH_MIN, QUERY_BATCH_MAX)
    n = max(QUERY_BATCH_MIN, min(QUERY_BATCH_MAX, int(n)))
    nouns = list(dict.fromkeys(RANDOM_NOUNS))  # стабильный дедуп
    moods = list(RANDOM_MOODS)
    queries: list[str] = []
    seen: set[str] = set()
    attempts = 0
    while len(queries) < n and attempts < n * 40:
        attempts += 1
        noun = random.choice(nouns)
        mood = random.choice(moods)
        # mood уже «candid» → не дублировать слово
        if mood.strip().lower() == "candid":
            query = f"{noun} candid aesthetic"
        else:
            query = f"{noun} {mood} candid aesthetic"
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(query)
    return queries


# Метаданные пина: явные надписи / цитаты / типографика
TEXT_TITLE_TERMS: tuple[str, ...] = (
    "quote",
    "quotes",
    "typography",
    "lettering",
    "text overlay",
    "overlay text",
    "affirmation",
    "affirmations",
    "wallpaper quote",
    "inspirational quote",
    "motivational quote",
    "daily reminder",
    "reminder",
    "poem",
    "poetry",
    "caption",
    "sayings",
    "saying",
    "font",
    "typewriter",
    "hand lettering",
    "calligraphy",
    "words of",
    "word art",
    "poster quote",
    "slide",
    "carousel",
    "tip:",
    "tips:",
)


def _cover_thumb(image: Image.Image) -> Image.Image:
    img = image.convert("RGB")
    scale = max(THUMB_W / img.width, THUMB_H / img.height)
    nw, nh = max(1, int(img.width * scale)), max(1, int(img.height * scale))
    img = img.resize((nw, nh), Image.Resampling.BILINEAR)
    left = (nw - THUMB_W) // 2
    top = (nh - THUMB_H) // 2
    return img.crop((left, top, left + THUMB_W, top + THUMB_H))


def _fit_zoom(image: Image.Image, *, max_h: int = ZOOM_H, max_w: int = 920) -> Image.Image:
    """Увеличить кадр до ~650–700 px по высоте, не вылезая за ширину экрана."""
    img = image.convert("RGB")
    scale = min(max_h / max(1, img.height), max_w / max(1, img.width), 1.0)
    if img.height < max_h:
        scale = min(max_h / max(1, img.height), max_w / max(1, img.width), 2.0)
    nw = max(1, int(round(img.width * scale)))
    nh = max(1, int(round(img.height * scale)))
    return img.resize((nw, nh), Image.Resampling.LANCZOS)


def _is_photo(path: Path) -> bool:
    return (
        path.is_file()
        and path.suffix.lower() in IMAGE_EXTS
        and not path.name.startswith("_")
    )


def title_looks_like_text(title: str) -> bool:
    """True если в названии пина явно цитата / типографика / надпись."""
    low = re.sub(r"\s+", " ", (title or "").lower()).strip()
    if not low:
        return False
    if any(term in low for term in TEXT_TITLE_TERMS):
        return True
    # много слов в кавычках / «...» — типичный quote-pin
    if low.count('"') >= 2 or low.count("«") >= 1:
        return True
    return False


def looks_like_text_overlay(image: Image.Image) -> bool:
    """
    Лёгкий анти-текст: плотные контрастные контуры в центральной полосе
    (белые/тёмные буквы на атмосферном фото).
    """
    try:
        small = image.convert("L").resize((160, 200), Image.Resampling.BILINEAR)
        edges = small.filter(ImageFilter.FIND_EDGES)
        edge_mean = float(ImageStat.Stat(edges).mean[0])
        hist = small.histogram()
        total = float(sum(hist) or 1)
        bright = sum(hist[200:]) / total
        dark = sum(hist[:45]) / total

        w, h = small.size
        mid = small.crop((int(w * 0.08), int(h * 0.22), int(w * 0.92), int(h * 0.78)))
        mid_edges = mid.filter(ImageFilter.FIND_EDGES)
        mid_edge = float(ImageStat.Stat(mid_edges).mean[0])

        # Типичный quote-poster: резкие контуры + яркие или чёрные глифы в центре
        if mid_edge > 33 and (bright > 0.08 or dark > 0.14):
            return True
        if mid_edge > 38:
            return True
        if edge_mean > 38 and mid_edge > 28:
            return True
        # Много почти-белых пикселей при высоких краях → белый текст
        if bright > 0.16 and mid_edge > 26:
            return True
        return False
    except Exception:
        return False


def is_clean_photo(image: Image.Image, title: str = "") -> bool:
    """Пропускать только атмосферные кадры без явных надписей."""
    if title_looks_like_text(title):
        return False
    try:
        from core.harvester import is_junk_candidate_image

        if is_junk_candidate_image(image, title):
            return False
    except Exception:
        pass
    if looks_like_text_overlay(image):
        return False
    return True


def _iter_local_photo_paths() -> list[Path]:
    """Чистые фоны с диска: test_downloads/ + data/cache/ (без downloaded_carousels)."""
    roots = [TEST_DOWNLOADS, DATA_CACHE]
    found: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not _is_photo(path):
                continue
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(path)
    return found


def collect_local_clean_paths(limit: int = GALLERY_N * 3) -> list[Path]:
    """Локальные файлы без уже показанных / размеченных / похожих на НЕТ."""
    paths = _iter_local_photo_paths()
    random.shuffle(paths)
    history = load_history()
    clean: list[Path] = []
    for path in paths:
        if is_blocked_path(path, history):
            continue
        try:
            with Image.open(path) as img:
                rgb = img.convert("RGB")
                if not is_clean_photo(rgb):
                    continue
                if is_blocked_image(rgb, pin_id=pin_id_from_path(path), path=path, history=history):
                    continue
        except Exception:
            continue
        clean.append(path)
        if len(clean) >= limit:
            break
    return clean


def save_clean_candidate(image: Image.Image, pin_id: str) -> Path | None:
    CLEAN_CACHE.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-]+", "_", str(pin_id or "pin"))[:40] or "pin"
    path = CLEAN_CACHE / f"{safe}_{int(time.time() * 1000) % 10_000_000}.jpg"
    try:
        image.convert("RGB").save(path, format="JPEG", quality=90, optimize=True)
        return path
    except Exception:
        return None


def image_ahash(image: Image.Image, size: int = HASH_SIZE) -> str:
    """Простой average-hash для отсева почти тех же кадров / кропов."""
    gray = image.convert("L").resize((size, size), Image.Resampling.BILINEAR)
    # Pillow 11+: getdata deprecated → get_flattened_data
    flat = getattr(gray, "get_flattened_data", None)
    pixels = list(flat() if callable(flat) else gray.getdata())
    avg = sum(pixels) / max(1, len(pixels))
    return "".join("1" if p >= avg else "0" for p in pixels)


def hamming_dist(a: str, b: str) -> int:
    if len(a) != len(b):
        return 10_000
    return sum(x != y for x, y in zip(a, b))


def pin_id_from_path(path: Path) -> str:
    return path.stem.split("_")[0]


def _norm_path(path: Path | str) -> str:
    return str(Path(path).resolve()).replace("\\", "/").lower()


def load_history() -> dict[str, set[str]]:
    """
    История разметки/показов:
      seen — уже показывали в галерее
      no / yes — явные метки
      paths — файлы
      no_hashes — perceptual hash кадров «НЕТ» (режем похожие)
    """
    data: dict[str, set[str]] = {
        "seen": set(),
        "no": set(),
        "yes": set(),
        "paths": set(),
        "no_hashes": set(),
    }
    # legacy rejects → как НЕТ + seen
    if REJECT_PATH.is_file():
        try:
            raw = json.loads(REJECT_PATH.read_text(encoding="utf-8"))
            for p in raw.get("pins") or []:
                data["no"].add(str(p).strip())
                data["seen"].add(str(p).strip())
            for p in raw.get("paths") or []:
                data["paths"].add(str(p).replace("\\", "/").lower())
        except Exception:
            pass
    if HISTORY_PATH.is_file():
        try:
            raw = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        for key in ("seen", "no", "yes", "paths", "no_hashes"):
            for item in raw.get(key) or []:
                if item:
                    data[key].add(str(item).strip())
        for p in raw.get("pins") or []:
            data["no"].add(str(p).strip())
            data["seen"].add(str(p).strip())
    return data


def save_history(data: dict[str, set[str]]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "seen": sorted(data["seen"])[-HISTORY_MAX:],
        "no": sorted(data["no"])[-HISTORY_MAX:],
        "yes": sorted(data["yes"])[-HISTORY_MAX:],
        "paths": sorted(data["paths"])[-HISTORY_MAX:],
        "no_hashes": sorted(data["no_hashes"])[-HASH_MAX:],
    }
    HISTORY_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # дублируем no → legacy, чтобы старый код не терял список
    REJECT_PATH.write_text(
        json.dumps(
            {"pins": payload["no"], "paths": payload["paths"]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def remember_history(
    *,
    seen_pins: list[str] | None = None,
    no_pins: list[str] | None = None,
    yes_pins: list[str] | None = None,
    paths: list[Path] | None = None,
    no_images: list[Image.Image] | None = None,
) -> None:
    data = load_history()
    for pid in seen_pins or []:
        if pid:
            data["seen"].add(str(pid).strip())
    for pid in no_pins or []:
        if pid:
            data["no"].add(str(pid).strip())
            data["seen"].add(str(pid).strip())
    for pid in yes_pins or []:
        if pid:
            data["yes"].add(str(pid).strip())
            data["seen"].add(str(pid).strip())
    for path in paths or []:
        data["paths"].add(_norm_path(path))
        guess = pin_id_from_path(path)
        if guess.isdigit() and len(guess) >= 6:
            data["seen"].add(guess)
    for img in no_images or []:
        try:
            data["no_hashes"].add(image_ahash(img))
        except Exception:
            pass
    save_history(data)


def blocked_pin_ids(history: dict[str, set[str]] | None = None) -> set[str]:
    data = history or load_history()
    return set(data["seen"]) | set(data["no"]) | set(data["yes"])


def is_blocked_path(path: Path, history: dict[str, set[str]] | None = None) -> bool:
    data = history or load_history()
    if _norm_path(path) in data["paths"]:
        return True
    pid = pin_id_from_path(path)
    return pid in blocked_pin_ids(data)


def is_blocked_image(
    image: Image.Image,
    *,
    pin_id: str = "",
    path: Path | None = None,
    history: dict[str, set[str]] | None = None,
) -> bool:
    """Уже показывали / размечали этот pin, либо кадр похож на прошлые НЕТ."""
    data = history or load_history()
    if pin_id and pin_id in blocked_pin_ids(data):
        return True
    if path is not None and is_blocked_path(path, data):
        return True
    try:
        h = image_ahash(image)
    except Exception:
        return False
    for prev in data["no_hashes"]:
        if hamming_dist(h, prev) <= HASH_MAX_DIST:
            return True
    return False


# --- совместимость со старыми вызовами ---
def load_rejects() -> dict[str, set[str]]:
    h = load_history()
    return {"pins": blocked_pin_ids(h), "paths": set(h["paths"])}


def remember_rejects(
    *,
    pin_ids: list[str] | None = None,
    paths: list[Path] | None = None,
) -> None:
    remember_history(no_pins=pin_ids, paths=paths, seen_pins=pin_ids)


def is_rejected_path(path: Path, rejects: dict[str, set[str]] | None = None) -> bool:
    if rejects is not None:
        key = _norm_path(path)
        if key in rejects.get("paths", set()):
            return True
        if pin_id_from_path(path) in rejects.get("pins", set()):
            return True
        return False
    return is_blocked_path(path)


def filter_scored_by_taste(
    items: list[tuple[str, Image.Image]],
    *,
    min_score: float = TASTE_KEEP_MIN,
    min_keep: int = 24,
    on_status: Callable[[str], None] | None = None,
) -> list[tuple[str, Image.Image, float]]:
    """
    Если модель обучена — предпочитаем высокий вкус.
    Если жёсткий порог выкосил почти всё (перекос НЕТ) —
    мягкий режим: топ по скору, галерея не пустеет.
    """
    from core.taste_classifier import get_taste_classifier

    def status(msg: str) -> None:
        if on_status:
            on_status(msg)

    if not items:
        return []

    clf = get_taste_classifier()
    if not clf.is_trained:
        out = [(pid, img, 0.5) for pid, img in items]
        random.shuffle(out)
        return out

    status(f"Вкус: оценка {len(items)} кадров…")
    try:
        scores = clf.predict_taste_scores([img for _, img in items])
    except Exception as exc:
        status(f"Вкус: оценка fail ({exc.__class__.__name__}) — без фильтра")
        out = [(pid, img, 0.5) for pid, img in items]
        random.shuffle(out)
        return out

    ranked = sorted(
        (
            (pid, img, float(sc))
            for (pid, img), sc in zip(items, scores)
        ),
        key=lambda x: x[2],
        reverse=True,
    )
    hard = [row for row in ranked if row[2] >= min_score]
    if len(hard) >= min_keep:
        status(f"Вкус: жёсткий отбор {len(hard)} (≥{min_score:.0%})")
        return hard

    # Модель слишком строгая (мало ДА при обучении) — берём лучших по скору
    need = max(min_keep, min(len(ranked), GALLERY_N))
    soft = ranked[:need]
    if soft:
        status(
            f"Вкус: мягкий топ-{len(soft)} "
            f"(лучший {soft[0][2]:.0%}, порог {min_score:.0%} выкосил почти всё)"
        )
    else:
        status("Вкус: нечего показывать")
    return soft


def filter_paths_by_taste(
    paths: list[Path],
    *,
    min_score: float = TASTE_KEEP_MIN,
    min_keep: int = 24,
    exclude: set[str] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> list[Path]:
    """Локальные пути: история показов/меток + вкус."""
    history = load_history()
    exclude = exclude or set()
    candidates: list[tuple[str, Image.Image, Path]] = []
    for path in paths:
        key = _norm_path(path)
        if key in exclude or is_blocked_path(path, history):
            continue
        try:
            img = _open_rgb(path)
        except Exception:
            continue
        if not is_clean_photo(img):
            continue
        pid = pin_id_from_path(path)
        if is_blocked_image(img, pin_id=pid, path=path, history=history):
            continue
        candidates.append((pid, img, path))

    if not candidates:
        return []

    scored = filter_scored_by_taste(
        [(pid, img) for pid, img, _ in candidates],
        min_score=min_score,
        min_keep=min_keep,
        on_status=on_status,
    )
    path_by_pid: dict[str, list[Path]] = {}
    for pid, _img, path in candidates:
        path_by_pid.setdefault(pid, []).append(path)

    out: list[Path] = []
    used: set[str] = set()
    for pid, _img, _sc in scored:
        for path in path_by_pid.get(pid, []):
            key = str(path.resolve()).lower()
            if key in used:
                continue
            used.add(key)
            out.append(path)
            break
    return out


def fetch_clean_from_pinterest(
    n: int = PINTEREST_TARGET,
    *,
    on_status: Callable[[str], None] | None = None,
    use_taste: bool = True,
) -> list[Path]:
    """
    Авто-пул с рекомендательной ленты Pinterest (без узких search-запросов):
      /ideas/{topic} + Related Pins → скачивание → вкус/anti-text → shuffle.
    """
    from core.harvester import PinterestHarvester
    from core.taste_classifier import get_taste_classifier

    def status(msg: str) -> None:
        if on_status:
            on_status(msg)

    history = load_history()
    blocked = blocked_pin_ids(history)
    taste_on = bool(use_taste and get_taste_classifier().is_trained)
    if taste_on:
        status("Модель вкуса активна — лента пройдёт через фильтр ДА/НЕТ")
    else:
        status("Модель вкуса ещё не обучена — сырая лента Ideas/Related")
    status(f"Уже скрыто из истории: {len(blocked)} pin’ов")

    harvester = PinterestHarvester(on_status=status)
    memory: list[tuple[str, Image.Image]] = []
    seen_pins: set[str] = set(blocked)
    target_raw = max(n * 2, n + 40) if taste_on else n + 24

    try:
        status("Pinterest: прогрев…")
        try:
            harvester.warm()
        except Exception:
            pass

        status("Собираю ленту Ideas + Related (не search)…")
        try:
            feed = harvester.fetch_feed_metas(
                limit=max(target_raw + 40, 160),
                related_seeds=12,
                related_per_seed=18,
            )
        except Exception as exc:
            status(f"Лента fail ({exc.__class__.__name__})")
            feed = []

        feed = [
            p
            for p in feed
            if p.pin_id not in seen_pins and not title_looks_like_text(p.title)
        ]
        status(f"Лента: {len(feed)} новых пинов (без уже виденных)")

        if feed:
            try:
                kept, ai_n = harvester.filter_ai(feed)
            except Exception:
                kept, ai_n = feed, 0
            kept = [p for p in kept if not title_looks_like_text(p.title)]
            status(f"После anti-AI: {len(kept)} (отсеяно ИИ: {ai_n})")
            random.shuffle(kept)
            # качаем пачками — шире, чем по одному запросу
            chunk = 28
            for i in range(0, len(kept), chunk):
                if len(memory) >= target_raw:
                    break
                batch = kept[i : i + chunk]
                need = min(chunk, target_raw - len(memory) + 6)
                status(
                    f"Скачиваю ленту {i + 1}–{i + len(batch)} / {len(kept)}…"
                )
                try:
                    cands, _prog = asyncio.run(
                        harvester.download_candidates(
                            batch, "ideas-feed", limit=need
                        )
                    )
                except Exception as exc:
                    status(f"Скачивание fail ({exc.__class__.__name__})")
                    continue
                for cand in cands:
                    if cand.pin_id in seen_pins:
                        continue
                    seen_pins.add(cand.pin_id)
                    if not is_clean_photo(cand.image, cand.title):
                        continue
                    if is_blocked_image(
                        cand.image, pin_id=cand.pin_id, history=history
                    ):
                        continue
                    memory.append((cand.pin_id, cand.image.copy()))
                    if len(memory) >= target_raw:
                        break
                status(f"В памяти новых кадров: {len(memory)}")

        # Если лента совсем пустая — один мягкий fallback на широкие запросы
        if len(memory) < max(12, n // 3):
            status("Лента мало новых — запасной широкий search…")
            for raw_q in synthesize_random_queries(8):
                if len(memory) >= target_raw:
                    break
                try:
                    pins = harvester.search(raw_q)
                except Exception:
                    continue
                pins = [
                    p
                    for p in pins
                    if p.pin_id not in seen_pins and not title_looks_like_text(p.title)
                ]
                if not pins:
                    continue
                try:
                    kept, _ = harvester.filter_ai(pins)
                except Exception:
                    kept = pins
                try:
                    cands, _ = asyncio.run(
                        harvester.download_candidates(
                            kept[:30], raw_q, limit=8
                        )
                    )
                except Exception:
                    continue
                for cand in cands:
                    if cand.pin_id in seen_pins:
                        continue
                    seen_pins.add(cand.pin_id)
                    if not is_clean_photo(cand.image, cand.title):
                        continue
                    if is_blocked_image(
                        cand.image, pin_id=cand.pin_id, history=history
                    ):
                        continue
                    memory.append((cand.pin_id, cand.image.copy()))
    finally:
        harvester.close()

    random.shuffle(memory)
    if taste_on:
        scored = filter_scored_by_taste(
            memory,
            min_score=TASTE_KEEP_MIN,
            min_keep=max(24, min(n, GALLERY_N)),
            on_status=on_status,
        )
    else:
        scored = [(pid, img, 0.5) for pid, img in memory]
        random.shuffle(scored)

    saved: list[Path] = []
    saved_pids: set[str] = set()
    for pin_id, img, _sc in scored:
        if len(saved) >= n:
            break
        path = save_clean_candidate(img, pin_id)
        if path is None:
            continue
        saved.append(path)
        saved_pids.add(pin_id)

    for pid, img in memory:
        if pid in saved_pids:
            continue
        try:
            img.close()
        except Exception:
            pass

    if taste_on and saved:
        top_n = max(12, min(len(saved), n // 4))
        top = saved[:top_n]
        rest = saved[top_n:]
        random.shuffle(rest)
        saved = top + rest
    else:
        random.shuffle(saved)

    status(
        f"Готово: {len(saved)} фонов с ленты"
        + (" (вкус-фильтр вкл.)" if taste_on else "")
    )
    return saved


def ensure_clean_gallery(
    n: int = GALLERY_N,
    *,
    force_pinterest: bool = False,
    on_status: Callable[[str], None] | None = None,
) -> list[Path]:
    """
    Источник галереи: локальный кэш → при нехватке / force — Pinterest.
    После обучения вкуса — отсев «как НЕТ» и чёрный список уже размеченных.
    """
    from core.taste_classifier import get_taste_classifier

    def status(msg: str) -> None:
        if on_status:
            on_status(msg)

    if force_pinterest:
        status("Качаю свежие фото с учётом вкуса…")
        fetched = fetch_clean_from_pinterest(
            PINTEREST_TARGET, on_status=on_status, use_taste=True
        )
        if len(fetched) >= min(20, n):
            return fetched[:n]
        status(
            f"Pinterest дал мало ({len(fetched)}) — добираю из кэша топом по вкусу…"
        )
        local = collect_local_clean_paths(limit=max(n * 3, 120))
        local = filter_paths_by_taste(
            local, min_keep=n, on_status=on_status
        )
        bag = fetched + [p for p in local if p not in fetched]
        chosen: list[Path] = []
        seen: set[str] = set()
        for path in bag:
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            chosen.append(path)
            if len(chosen) >= n:
                break
        return chosen

    local = collect_local_clean_paths(limit=max(n * 3, MIN_DISK_PHOTOS * 2))
    status(f"Локальный кэш чистых фото: {len(local)}")
    local = filter_paths_by_taste(local, min_keep=n, on_status=on_status)
    if len(local) < min(20, n):
        status(
            f"После вкуса/чёрного списка мало ({len(local)}) — лента Ideas/Related…"
        )
        fetched = fetch_clean_from_pinterest(
            PINTEREST_TARGET, on_status=on_status, use_taste=True
        )
        rejects = load_history()
        bag = [
            p
            for p in (fetched + local)
            if not is_blocked_path(p, rejects)
        ]
    else:
        bag = local

    if get_taste_classifier().is_trained and bag:
        top_n = max(12, min(len(bag), n // 4))
        top = bag[:top_n]
        rest = bag[top_n:]
        random.shuffle(rest)
        bag = top + rest
    else:
        random.shuffle(bag)

    chosen: list[Path] = []
    seen: set[str] = set()
    for path in bag:
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        chosen.append(path)
        if len(chosen) >= n:
            break
    return chosen


class TasteTrainerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Taste Trainer — чистые фото без текста")
        self.root.configure(bg=BG)
        self.root.geometry("1040x820")
        self.root.minsize(860, 560)

        self._photos: list[ImageTk.PhotoImage] = []
        self._cells: list[dict] = []
        self._training = False
        self._loading = False
        self._zoom_win: tk.Toplevel | None = None
        self._zoom_cell: dict | None = None
        self._zoom_photo: ImageTk.PhotoImage | None = None
        self._pending_click: str | None = None
        self._pending_after: object | None = None

        self._build()
        self.root.after(80, lambda: self.reload_gallery(force_pinterest=True))

    def _build(self) -> None:
        top = tk.Frame(self.root, bg=PANEL)
        top.pack(fill=tk.X)

        tk.Label(
            top,
            text="Разметь вкус на чистых фонах (без текста слайдов)",
            bg=PANEL,
            fg=FG,
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor=tk.W, padx=14, pady=(12, 2))

        self.count_var = tk.StringVar(value=self._count_text(0, 0))
        tk.Label(
            top,
            textvariable=self.count_var,
            bg=PANEL,
            fg=YES,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor=tk.W, padx=14, pady=(0, 4))

        tk.Label(
            top,
            text="После «Обучить» свежая пачка режет похожие на НЕТ · "
            "кнопки: ДА / НЕТ / сброс · клик по фото — зум",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
            wraplength=980,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=14, pady=(0, 8))

        actions = tk.Frame(top, bg=PANEL)
        actions.pack(fill=tk.X, padx=14, pady=(0, 8))

        self.train_btn = tk.Button(
            actions,
            text="🚀 Обучить мой фильтр вкуса",
            bg=YES,
            fg="#102018",
            activebackground="#2bb67a",
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=8,
            cursor="hand2",
            command=self.start_train,
        )
        self.train_btn.pack(side=tk.LEFT)

        self.pinterest_btn = tk.Button(
            actions,
            text="🔄 Загрузить свежие фото из ленты Pinterest",
            bg="#4f8cff",
            fg="#0a1220",
            activebackground="#3a6fd8",
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=8,
            cursor="hand2",
            command=self.reload_from_pinterest,
        )
        self.pinterest_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.resample_btn = tk.Button(
            actions,
            text="Другая выборка",
            bg=PANEL2,
            fg=FG,
            activebackground=BORDER,
            relief=tk.FLAT,
            font=("Segoe UI", 10),
            padx=12,
            pady=8,
            cursor="hand2",
            command=lambda: self.reload_gallery(force_pinterest=False),
        )
        self.resample_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.status_var = tk.StringVar(
            value="Источник: лента Ideas + Related · кэш data/cache/"
        )
        tk.Label(
            top,
            textvariable=self.status_var,
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(0, 10))

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        scroll = tk.Scrollbar(body, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.grid = tk.Frame(self.canvas, bg=BG)
        self._win = self.canvas.create_window((0, 0), window=self.grid, anchor="nw")
        self.grid.bind("<Configure>", self._on_grid_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_grid_configure(self, _event: object) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self.canvas.itemconfigure(self._win, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        if self._zoom_win is not None:
            return
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _count_text(self, yes: int, no: int) -> str:
        return f"Выбрано ДА: {yes} / {TARGET_YES} | Выбрано НЕТ: {no} / {TARGET_NO}"

    def _refresh_counts(self) -> None:
        yes = sum(1 for c in self._cells if c["state"] == 1)
        no = sum(1 for c in self._cells if c["state"] == 2)
        self.count_var.set(self._count_text(yes, no))

    def _set_busy_ui(self, busy: bool) -> None:
        state = tk.DISABLED if busy else tk.NORMAL
        self.train_btn.configure(state=state)
        self.pinterest_btn.configure(state=state)
        self.resample_btn.configure(state=state)

    def reload_from_pinterest(self) -> None:
        self.reload_gallery(force_pinterest=True)

    def reload_gallery(self, *, force_pinterest: bool = False) -> None:
        if self._training or self._loading:
            return
        self.close_zoom()
        self._cancel_pending_click()
        self._loading = True
        self._set_busy_ui(True)
        for child in self.grid.winfo_children():
            child.destroy()
        self._photos.clear()
        self._cells.clear()
        self._refresh_counts()
        self.status_var.set(
            "Качаю ленту Ideas + Related…"
            if force_pinterest
            else "Собираю чистые фоны (кэш / лента)…"
        )

        def worker() -> None:
            err = ""
            paths: list[Path] = []
            try:
                paths = ensure_clean_gallery(
                    GALLERY_N,
                    force_pinterest=force_pinterest,
                    on_status=lambda m: self.root.after(0, lambda msg=m: self.status_var.set(msg)),
                )
            except Exception as exc:
                err = f"{exc.__class__.__name__}: {exc}"
            self.root.after(0, lambda: self._on_gallery_ready(paths, err, force_pinterest))

        threading.Thread(target=worker, daemon=True).start()

    def _on_gallery_ready(
        self,
        paths: list[Path],
        err: str,
        force_pinterest: bool,
    ) -> None:
        self._loading = False
        self._set_busy_ui(False)
        if err:
            self.status_var.set("Не удалось собрать галерею.")
            messagebox.showerror("Галерея", err)
            return

        col = 0
        row = 0
        shown = 0
        shown_paths: list[Path] = []
        history = load_history()
        for path in paths:
            if is_blocked_path(path, history):
                continue
            try:
                with Image.open(path) as img:
                    rgb = img.convert("RGB")
                    if not is_clean_photo(rgb):
                        continue
                    if is_blocked_image(
                        rgb,
                        pin_id=pin_id_from_path(path),
                        path=path,
                        history=history,
                    ):
                        continue
                    thumb = _cover_thumb(rgb)
            except Exception:
                continue
            photo = ImageTk.PhotoImage(thumb)
            self._photos.append(photo)
            cell = self._make_cell(photo, path, row, col)
            self._cells.append(cell)
            shown_paths.append(path)
            shown += 1
            col += 1
            if col >= COLS:
                col = 0
                row += 1
            if shown >= GALLERY_N:
                break

        self._refresh_counts()
        self.canvas.yview_moveto(0)
        if shown_paths:
            try:
                remember_history(
                    seen_pins=[pin_id_from_path(p) for p in shown_paths],
                    paths=shown_paths,
                )
            except Exception:
                pass
        if not self._cells:
            # последняя страховка: кэш только из ещё не виденных
            fallback = collect_local_clean_paths(GALLERY_N * 2)
            random.shuffle(fallback)
            col = row = shown = 0
            extra: list[Path] = []
            for path in fallback:
                if shown >= GALLERY_N:
                    break
                try:
                    with Image.open(path) as img:
                        thumb = _cover_thumb(img.convert("RGB"))
                except Exception:
                    continue
                photo = ImageTk.PhotoImage(thumb)
                self._photos.append(photo)
                self._cells.append(self._make_cell(photo, path, row, col))
                extra.append(path)
                shown += 1
                col += 1
                if col >= COLS:
                    col = 0
                    row += 1
            self._refresh_counts()
            if extra:
                try:
                    remember_history(
                        seen_pins=[pin_id_from_path(p) for p in extra],
                        paths=extra,
                    )
                except Exception:
                    pass
            if self._cells:
                self.status_var.set(
                    f"Показал {len(self._cells)} новых из кэша "
                    f"(история скрыла повторы)."
                )
                return
            self.status_var.set(
                "Не удалось набрать НОВЫЕ фото — всё уже было в истории. "
                "Попробуй ленту ещё раз или очисти data/taste_history.json."
            )
            messagebox.showwarning(
                "Пусто",
                "Новых кадров нет: всё уже показывали или похоже на прошлые НЕТ.\n"
                "Нажми загрузку ленты ещё раз или переобучи вкус с большим числом ДА.",
            )
            return
        hist = load_history()
        src = "лента Pinterest" if force_pinterest else "кэш/лента"
        self.status_var.set(
            f"В галерее {len(self._cells)} НОВЫХ фонов ({src}). "
            f"В истории скрыто: {len(blocked_pin_ids(hist))}."
        )

    def _make_cell(
        self, photo: ImageTk.PhotoImage, path: Path, row: int, col: int
    ) -> dict:
        frame = tk.Frame(
            self.grid,
            bg=PANEL2,
            highlightthickness=4,
            highlightbackground=BORDER,
        )
        frame.grid(row=row, column=col, padx=6, pady=6)

        img_lbl = tk.Label(frame, image=photo, bg=PANEL2, bd=0, cursor="hand2")
        img_lbl.pack()

        cap = tk.Label(
            frame,
            text="",
            bg=PANEL2,
            fg=MUTED,
            font=("Segoe UI", 8, "bold"),
            height=1,
        )
        cap.pack(fill=tk.X)

        btns = tk.Frame(frame, bg=PANEL2)
        btns.pack(fill=tk.X, padx=2, pady=(0, 4))

        cell: dict = {
            "path": path,
            "state": 0,
            "frame": frame,
            "cap": cap,
            "id": id(frame),
            "btn_yes": None,
            "btn_no": None,
            "btn_clear": None,
        }

        def mark_yes(_event: object | None = None, item: dict = cell) -> None:
            self._cancel_pending_click()
            self._apply_state(item, 1)

        def mark_no(_event: object | None = None, item: dict = cell) -> None:
            self._cancel_pending_click()
            self._apply_state(item, 2)

        def mark_clear(_event: object | None = None, item: dict = cell) -> None:
            self._cancel_pending_click()
            self._apply_state(item, 0)

        def open_z(_event: object | None = None, item: dict = cell) -> str:
            self._cancel_pending_click()
            self.open_zoom(item)
            return "break"

        btn_yes = tk.Button(
            btns,
            text="ДА",
            bg=YES,
            fg="#102018",
            activebackground="#2bb67a",
            activeforeground="#102018",
            relief=tk.FLAT,
            bd=0,
            font=("Segoe UI", 8, "bold"),
            cursor="hand2",
            padx=2,
            pady=2,
            command=mark_yes,
        )
        btn_yes.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))

        btn_no = tk.Button(
            btns,
            text="НЕТ",
            bg=NO,
            fg="#fff",
            activebackground="#c0392b",
            activeforeground="#fff",
            relief=tk.FLAT,
            bd=0,
            font=("Segoe UI", 8, "bold"),
            cursor="hand2",
            padx=2,
            pady=2,
            command=mark_no,
        )
        btn_no.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))

        btn_clear = tk.Button(
            btns,
            text="✕",
            bg=BORDER,
            fg=FG,
            activebackground=PANEL,
            activeforeground=FG,
            relief=tk.FLAT,
            bd=0,
            font=("Segoe UI", 8, "bold"),
            cursor="hand2",
            padx=2,
            pady=2,
            command=mark_clear,
        )
        btn_clear.pack(side=tk.LEFT, expand=True, fill=tk.X)

        cell["btn_yes"] = btn_yes
        cell["btn_no"] = btn_no
        cell["btn_clear"] = btn_clear

        # фото / рамка — только зум, метки ставятся кнопками
        for widget in (frame, img_lbl, cap):
            widget.bind("<Button-1>", open_z)
            widget.bind("<Button-3>", open_z)
            widget.bind("<Double-Button-1>", open_z)
        return cell

    def _cancel_pending_click(self) -> None:
        if self._pending_after is not None:
            try:
                self.root.after_cancel(self._pending_after)
            except Exception:
                pass
        self._pending_after = None
        self._pending_click = None

    def _apply_state(self, cell: dict, state: int) -> None:
        if self._training or self._loading:
            return
        prev = int(cell.get("state") or 0)
        state = int(state) % 3
        cell["state"] = state
        color = STATE_COLORS[state]
        cell["frame"].configure(highlightbackground=color)
        cell["cap"].configure(
            text=STATE_CAPTION[state],
            fg=color if state else MUTED,
            bg="#143026" if state == 1 else ("#3a1616" if state == 2 else PANEL2),
        )
        yes_btn = cell.get("btn_yes")
        no_btn = cell.get("btn_no")
        clear_btn = cell.get("btn_clear")
        if yes_btn is not None:
            yes_btn.configure(bg="#1e7a4f" if state == 1 else YES)
        if no_btn is not None:
            no_btn.configure(bg="#8b1e1e" if state == 2 else NO)
        if clear_btn is not None:
            clear_btn.configure(bg=PANEL if state == 0 else BORDER)
        # ДА/НЕТ → в историю, чтобы не крутить те же кадры снова
        if state == 2 and prev != 2:
            try:
                path = Path(cell["path"])
                img = _open_rgb(path)
                remember_history(
                    no_pins=[pin_id_from_path(path)],
                    paths=[path],
                    no_images=[img],
                )
            except Exception:
                try:
                    remember_history(
                        no_pins=[pin_id_from_path(Path(cell["path"]))],
                        paths=[Path(cell["path"])],
                    )
                except Exception:
                    pass
        elif state == 1 and prev != 1:
            try:
                path = Path(cell["path"])
                remember_history(
                    yes_pins=[pin_id_from_path(path)],
                    paths=[path],
                )
            except Exception:
                pass
        self._refresh_counts()

    def _cycle(self, cell: dict) -> None:
        if self._training or self._loading:
            return
        self._apply_state(cell, (int(cell["state"]) + 1) % 3)

    def open_zoom(self, cell: dict) -> None:
        """Модальный крупный просмотр (~680 px) с быстрой разметкой."""
        if self._training or self._loading:
            return
        self.close_zoom()
        try:
            preview = _fit_zoom(_open_rgb(cell["path"]))
        except Exception as exc:
            messagebox.showerror("Зум", f"Не удалось открыть кадр:\n{exc}")
            return

        win = tk.Toplevel(self.root)
        win.title("Zoom Preview")
        win.configure(bg=OVERLAY_BG)
        win.transient(self.root)
        win.attributes("-topmost", True)
        try:
            win.state("zoomed")
        except tk.TclError:
            self.root.update_idletasks()
            win.geometry(
                f"{self.root.winfo_width()}x{self.root.winfo_height()}+"
                f"{self.root.winfo_rootx()}+{self.root.winfo_rooty()}"
            )
        win.grab_set()
        win.focus_force()

        overlay = tk.Frame(win, bg=OVERLAY_BG, cursor="arrow")
        overlay.pack(fill=tk.BOTH, expand=True)
        overlay.bind("<Button-1>", lambda _e: self.close_zoom())

        card = tk.Frame(overlay, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        card.place(relx=0.5, rely=0.5, anchor="center")
        card.bind("<Button-1>", lambda _e: "break")

        photo = ImageTk.PhotoImage(preview)
        self._zoom_photo = photo
        img_lbl = tk.Label(card, image=photo, bg="#111", bd=0, cursor="hand2")
        img_lbl.pack(padx=14, pady=(14, 8))
        img_lbl.bind("<Button-1>", lambda _e: "break")

        hint = tk.Label(
            card,
            text="1 / Z = ДА   ·   2 / X = НЕТ   ·   Esc или клик вне кадра = закрыть",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        )
        hint.pack(pady=(0, 6))

        btns = tk.Frame(card, bg=PANEL)
        btns.pack(pady=(0, 14))

        tk.Button(
            btns,
            text="👍 ДА (Зеленый)",
            bg=YES,
            fg="#102018",
            activebackground="#2bb67a",
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=14,
            pady=8,
            cursor="hand2",
            command=lambda: self._zoom_mark(1),
        ).pack(side=tk.LEFT, padx=6)

        tk.Button(
            btns,
            text="👎 НЕТ (Красный)",
            bg=NO,
            fg="#fff",
            activebackground="#c0392b",
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=14,
            pady=8,
            cursor="hand2",
            command=lambda: self._zoom_mark(2),
        ).pack(side=tk.LEFT, padx=6)

        tk.Button(
            btns,
            text="Закрыть (Esc)",
            bg=PANEL2,
            fg=FG,
            activebackground=BORDER,
            relief=tk.FLAT,
            font=("Segoe UI", 10),
            padx=14,
            pady=8,
            cursor="hand2",
            command=self.close_zoom,
        ).pack(side=tk.LEFT, padx=6)

        self._zoom_win = win
        self._zoom_cell = cell
        win.bind("<Escape>", lambda _e: self.close_zoom())
        win.bind("<KeyPress-1>", lambda _e: self._zoom_mark(1))
        win.bind("<KeyPress-z>", lambda _e: self._zoom_mark(1))
        win.bind("<KeyPress-Z>", lambda _e: self._zoom_mark(1))
        win.bind("<KeyPress-2>", lambda _e: self._zoom_mark(2))
        win.bind("<KeyPress-x>", lambda _e: self._zoom_mark(2))
        win.bind("<KeyPress-X>", lambda _e: self._zoom_mark(2))
        win.protocol("WM_DELETE_WINDOW", self.close_zoom)

    def _zoom_mark(self, state: int) -> None:
        cell = self._zoom_cell
        if cell is None:
            self.close_zoom()
            return
        self._apply_state(cell, state)
        self.close_zoom()

    def close_zoom(self) -> None:
        win = self._zoom_win
        self._zoom_win = None
        self._zoom_cell = None
        self._zoom_photo = None
        if win is None:
            return
        try:
            win.grab_release()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass
        try:
            self.root.focus_force()
        except Exception:
            pass

    def start_train(self) -> None:
        if self._training or self._loading:
            return
        if self._zoom_win is not None:
            self.close_zoom()
        yes_paths = [c["path"] for c in self._cells if c["state"] == 1]
        no_paths = [c["path"] for c in self._cells if c["state"] == 2]
        if len(yes_paths) < 2 or len(no_paths) < 2:
            messagebox.showwarning(
                "Мало примеров",
                "Нужно минимум 2 «ДА» и 2 «НЕТ». Цель — примерно по 40.",
            )
            return
        self._training = True
        self._set_busy_ui(True)
        self.status_var.set(
            "Загружаю SigLIP и считаю эмбеддинги… это один раз, дальше быстро."
        )
        threading.Thread(
            target=self._train_worker,
            args=(list(yes_paths), list(no_paths)),
            daemon=True,
        ).start()

    def _train_worker(self, yes_paths: list[Path], no_paths: list[Path]) -> None:
        err = ""
        report = ""
        try:
            # текущий экран сначала в историю, потом учим на всём накопленном
            remember_history(
                yes_pins=[pin_id_from_path(p) for p in yes_paths],
                no_pins=[pin_id_from_path(p) for p in no_paths],
                paths=list(yes_paths) + list(no_paths),
                no_images=[_open_rgb(p) for p in no_paths],
            )
            train_yes, train_no = build_training_sets(yes_paths, no_paths)
            self.root.after(
                0,
                lambda: self.status_var.set(
                    f"Учу на всей истории: {len(train_yes)} ДА / {len(train_no)} НЕТ…"
                ),
            )

            positives = [_open_rgb(p) for p in train_yes]
            negatives = [_open_rgb(p) for p in train_no]
            from core.taste_classifier import get_taste_classifier

            # пишем в singleton — следующая загрузка сразу видит модель
            payload = get_taste_classifier().train(positives, negatives)
            pos = int(payload["n_positive"])
            neg = int(payload["n_negative"])
            report = (
                f"Фильтр обучен на {pos + neg} примерах "
                f"({pos} ДА / {neg} НЕТ, вся история + этот экран)."
            )
        except Exception as exc:
            err = f"{exc.__class__.__name__}: {exc}"
        self.root.after(0, lambda: self._train_done(report, err))

    def _train_done(self, report: str, err: str) -> None:
        self._training = False
        self._set_busy_ui(False)
        if err:
            self.status_var.set("Обучение не удалось.")
            messagebox.showerror("Вкус", err)
            return
        self.status_var.set(report)
        go = messagebox.askyesno(
            "Вкус обучен",
            report + "\n\nЗагрузить свежую пачку уже через фильтр вкуса?",
        )
        if go:
            self.reload_gallery(force_pinterest=True)


def collect_history_training_paths() -> tuple[list[Path], list[Path]]:
    """Все ранее размеченные кадры из кэша: (ДА, НЕТ) по истории."""
    data = load_history()
    yes_pins = set(data["yes"])
    no_pins = set(data["no"])
    # противоречивые метки не тащим в обучение
    conflict = yes_pins & no_pins
    yes_pins -= conflict
    no_pins -= conflict

    yes_paths: list[Path] = []
    no_paths: list[Path] = []
    used: set[str] = set()
    if not CLEAN_CACHE.is_dir():
        return yes_paths, no_paths
    for path in CLEAN_CACHE.iterdir():
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
            continue
        pid = pin_id_from_path(path)
        if pid in used:
            continue
        if pid in yes_pins:
            used.add(pid)
            yes_paths.append(path)
        elif pid in no_pins:
            used.add(pid)
            no_paths.append(path)
    return yes_paths, no_paths


def build_training_sets(
    current_yes: list[Path],
    current_no: list[Path],
    *,
    max_no_ratio: float = MAX_NO_RATIO,
) -> tuple[list[Path], list[Path]]:
    """
    Накопительный датасет: текущий экран + вся история разметки.
    НЕТ ограничиваем кратностью к ДА, иначе модель учит «всё плохо».
    """
    hist_yes, hist_no = collect_history_training_paths()

    def merge(primary: list[Path], extra: list[Path]) -> list[Path]:
        out: list[Path] = []
        seen: set[str] = set()
        for path in list(primary) + list(extra):
            pid = pin_id_from_path(Path(path))
            key = pid if pid.isdigit() else _norm_path(path)
            if key in seen:
                continue
            seen.add(key)
            out.append(Path(path))
        return out

    yes_all = merge(current_yes, hist_yes)
    no_all = merge(current_no, hist_no)

    # жёсткий лимит: свежие НЕТ с экрана в приоритете, историю добираем случайно
    cap = max(MIN_NO_SAMPLES, int(len(yes_all) * max_no_ratio))
    if len(no_all) > cap:
        fresh = no_all[: len(current_no)][:cap]
        rest = no_all[len(current_no) :]
        random.shuffle(rest)
        no_all = fresh + rest[: max(0, cap - len(fresh))]
    return yes_all, no_all


def bootstrap_no_hashes_from_cache(limit: int = 400) -> int:
    """Один раз добить perceptual-hash по уже накопленным НЕТ из кэша."""
    data = load_history()
    if len(data["no_hashes"]) >= min(80, len(data["no"])):
        return 0
    if not CLEAN_CACHE.is_dir() or not data["no"]:
        return 0
    added = 0
    for path in CLEAN_CACHE.iterdir():
        if added >= limit:
            break
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
            continue
        pid = pin_id_from_path(path)
        if pid not in data["no"]:
            continue
        try:
            with Image.open(path) as img:
                data["no_hashes"].add(image_ahash(img.convert("RGB")))
            added += 1
        except Exception:
            continue
    if added:
        save_history(data)
    return added


def main() -> None:
    try:
        bootstrap_no_hashes_from_cache()
    except Exception:
        pass
    root = tk.Tk()
    TasteTrainerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
