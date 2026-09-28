#!/usr/bin/env python3
"""
Pinterest search + AI filter + resilient in-memory downloads.

Протестированная логика из pinterest_gui_test / downloader / resilience.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote_plus, urlparse

import httpx
from PIL import Image

# Корень репо — только для query-scoped кэша (md5 запроса).
# НИКОГДА не подмешиваем test_downloads/ или общий data/cache/.
_HARVESTER_ROOT = Path(__file__).resolve().parent.parent
_QUERY_CACHE_ROOT = _HARVESTER_ROOT / "data" / "cache" / "pinterest_by_query"

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

AI_SOURCE_TYPE = 11
DOWNLOAD_CONCURRENCY = 12
RELATED_DOWNLOAD_WORKERS = 10
AI_CHECK_WORKERS = 10
MAX_SEARCH_PINS = 40
CANDIDATES_PER_SLIDE = 10  # больше пул -> меньше emergency keep
RELATED_PINS_DEFAULT = 8
# Pinterest HTML/API часто >5с при параллели — иначе массовый raw=0
REQUEST_TIMEOUT = 20.0
CDN_TIMEOUT = 12.0
# Fail-fast dead TLS; successful reads still use REQUEST_TIMEOUT
CONNECT_TIMEOUT = 5.0
# Сеть: primary + 1 повтор
MAX_NETWORK_RETRIES = 2
MAX_QUERY_ATTEMPTS = 1  # только primary — без candid/finsta-цепочек
# 3 slide-workers: fewer wait waves for 6 slides; same pins/quality
SEARCH_MAX_WORKERS = 3
WARM_COOLDOWN_SEC = 45.0

# Text↔image (SigLIP) + финальный ранг после полной загрузки пула
TEXT_RELEVANCE_MIN = 0.08  # legacy alias; отбор — SELECT_RELEVANCE_MIN
SELECT_RELEVANCE_MIN = 0.08
# ---------------------------------------------------------------------------
# Selection contract:
#   STRICT=True → normal path never soft-ships junk (pool_soft / guarantee_soft off).
#   COMPLETION_FILL=True → if still empty after vibe+guarantee, last-mile soft keep
#   so the factory NEVER ships a carousel with a missing slide. Marked in meta.
# ---------------------------------------------------------------------------
STRICT_SELECTION_CONTRACT = True
COMPLETION_FILL_ENABLED = True
SOFT_REL_ENABLED = not STRICT_SELECTION_CONTRACT
POOL_SOFT_UGC_ENABLED = not STRICT_SELECTION_CONTRACT
GUARANTEE_SOFT_ENABLED = not STRICT_SELECTION_CONTRACT
# Last-mile floors (only COMPLETION_FILL path)
COMPLETION_UGC_FLOOR = 0.32
COMPLETION_REL_FLOOR = 0.05
COMPLETION_MAX_SEARCHES = 4
SOFT_REL_FLOOR = 0.02
# Taste: раньше саботировал (красивый сток бил живое в ранге).
# Режим VETO: вкус считает и режет совсем чужое, но НЕ влияет на вес ранга.
TASTE_ENABLED = True
TASTE_VETO_ONLY = True  # True = floor only, weight 0 in final score
FINAL_REL_W = 0.35
FINAL_TASTE_W = 0.0 if (not TASTE_ENABLED or TASTE_VETO_ONLY) else 0.30
FINAL_UGC_W = 0.65 if (not TASTE_ENABLED or TASTE_VETO_ONLY) else 0.40
FINAL_HARM_W = 0.0
# Полы синхронизированы с probe (live≈0.55): ниже 0.50 = сток/глянец → DROP
UGC_HARD_FLOOR = 0.55
# Soft band: real night-fridge / messy-counter often land 0.45–0.51.
# Allow ONLY when relevance already proves scene match (not stock-bypass).
UGC_SOFT_FLOOR = 0.48
UGC_SOFT_REL_MIN = 0.30
# Vibe scenes (rain/glass/sky/mirror): SigLIP often scores ugc 0.25–0.44
# even on good UGC frames — allow lower floor when rel already proves match.
UGC_VIBE_SOFT_FLOOR = 0.32
UGC_VIBE_SOFT_REL_MIN = 0.55
_VIBE_SCENE_RE = re.compile(
    r"\b("
    r"rain|rainy|window|windows|glass|mirror|reflection|silhouette|"
    r"sky|skyline|storefront|shop\s*window|city\s*lights|bokeh|"
    r"hallway|dusk|twilight"
    r")\b",
    re.I,
)
# Вкус < 40% — DROP (staged / AI-look); 0 если TASTE_ENABLED=False
TASTE_HARD_FLOOR = 0.0 if not TASTE_ENABLED else 0.40
# Emergency: hard floor OR soft-band with rel (same as main gate)
EMERGENCY_UGC_FLOOR = UGC_HARD_FLOOR if STRICT_SELECTION_CONTRACT else 0.48
EMERGENCY_TASTE_FLOOR = 0.0 if not TASTE_ENABLED else 0.38
EMERGENCY_REL_FLOOR = (
    SELECT_RELEVANCE_MIN if STRICT_SELECTION_CONTRACT else 0.05
)
# Guarantee soft floor — only used when GUARANTEE_SOFT_ENABLED
GUARANTEE_UGC_FLOOR = UGC_HARD_FLOOR if STRICT_SELECTION_CONTRACT else 0.42


def is_vibe_scene(visual_scene: str = "", query: str = "", slide_text: str = "") -> bool:
    """True for rain/glass/sky/mirror scenes where UGC scorer is unreliable."""
    blob = f"{visual_scene} {query} {slide_text}"
    return bool(_VIBE_SCENE_RE.search(blob or ""))


def ugc_eligible(
    ugc: float,
    rel: float = 0.0,
    *,
    visual_scene: str = "",
    query: str = "",
    slide_text: str = "",
) -> bool:
    """Hard UGC floor, or soft band when relevance already clears."""
    u = float(ugc or 0.0)
    r = float(rel or 0.0)
    # Avoid float-edge drops at exactly ~0.45 / 0.52
    u_r = round(u, 4)
    r_r = round(r, 4)
    if u_r >= UGC_HARD_FLOOR:
        return True
    if u_r >= UGC_SOFT_FLOOR and r_r >= UGC_SOFT_REL_MIN:
        return True
    if (
        is_vibe_scene(visual_scene, query, slide_text)
        and u_r >= UGC_VIBE_SOFT_FLOOR
        and r_r >= UGC_VIBE_SOFT_REL_MIN
    ):
        return True
    return False


def ugc_is_borderline(
    ugc: float,
    rel: float = 0.0,
    *,
    visual_scene: str = "",
    query: str = "",
    slide_text: str = "",
) -> bool:
    """
    True when the frame is only eligible via soft/vibe soft bands —
    not hard UGC ≥0.55. These need a vision glance, not auto-pass.
    """
    u_r = round(float(ugc or 0.0), 4)
    if u_r >= UGC_HARD_FLOOR:
        return False
    return ugc_eligible(
        ugc,
        rel,
        visual_scene=visual_scene,
        query=query,
        slide_text=slide_text,
    )


# Soft-band frames: moondream KEEP required (no formula auto-pass)
BORDERLINE_VISION_ENABLED = True
BORDERLINE_VISION_FAIL_CLOSED = True  # no ollama → soft band DROP
BORDERLINE_VISION_MAX = 6  # max vision calls per slide

GUARANTEE_MAX_SEARCHES = 2
# Hard cap: primary+alt+vibe rescues — no 13min retry death spiral
SLIDE_SEARCH_BUDGET = 5
MERGE_DOWNLOAD_CAP = 14
RESCUE_DOWNLOAD_CAP = 10
# Last-resort: без фиктивных стабов — только нейтральный запас, если сцена пуста
LAST_RESORT_QUERIES: tuple[str, ...] = ()
# Fake pin_id от HTML-скрейпа без реального id (зомби-градиенты)
_FAKE_PIN_ID_RE = re.compile(r"^img\d{1,4}$", re.I)
# Хвостовые маркеры: бессмысленно НЕ дописываем; срезаем если прилипли
MOBILE_QUERY_MARKERS: frozenset[str] = frozenset(
    {"iphone", "candid", "snapshot", "finsta"}
)
# phone в запросе ок только если слайд реально про телефон
_PHONE_CONTENT_HINTS: tuple[str, ...] = (
    "phone",
    "iphone",
    "scroll",
    "texting",
    "smartphone",
    "screen time",
    "doomscroll",
)

# Устаревшие lighting-фразы — ВЫРЕЗАТЬ, никогда не склеивать в запрос
CAROUSEL_LIGHTING_ANCHORS: tuple[str, ...] = (
    "warm evening ambient lamp",
    "soft morning natural sunlight",
    "cozy rain window moody",
    "candid golden hour",
)
_LIGHTING_WORD_SPAM: frozenset[str] = frozenset(
    {
        # только слова из Exact lighting-фраз (candid — стиль формулы, НЕ spam)
        "warm", "evening", "ambient", "soft", "morning",
        "natural", "sunlight", "moody",
        "golden", "hour", "sunny", "golden-hour",
    }
)

# Позы/действия — НИКОГДА не вырезать в clamp
_SITUATION_POSE_KEEP: frozenset[str] = frozenset(
    {
        "sitting", "lying", "leaning", "walking", "pacing",
        "staring", "holding", "waiting", "looking", "hands",
        "head", "writing", "focused",
    }
)

# Промпты нейросетей / глянец / moodboard — никогда не использовать в поисковых запросах
BANNED_QUERY_TERMS: tuple[str, ...] = (
    "moody film still",
    "cinematic",
    "hyperrealistic",
    "concept art",
    "unreal engine",
    "editorial",
    "studio",
    "professional photoshoot",
    "magazine",
    "35mm film",
    "candid 35mm film",
    "film still",
    "photoshoot",
    "authentic lifestyle photo",
    "dark academia",
    "cozy aesthetic",
    "aesthetic night",
    "cozy night",
    "aesthetic mood",
    "vibe",
    "vibes",
    "moody aesthetic",
    "night aesthetic",
    "academia aesthetic",
    "rory gilmore aesthetic",
    "aesthetic journaling",
    "cozy study aesthetic",
)

# Слова без осязаемого предмета — сами по себе невалидный запрос
_ABSTRACT_ONLY_WORDS: frozenset[str] = frozenset(
    {
        "cozy",
        "aesthetic",
        "night",
        "mood",
        "moody",
        "vibe",
        "vibes",
        "soft",
        "dark",
        "academia",
        "lifestyle",
        "girlhood",
        "ambient",
        "minimalist",
        "vintage",
        "dreamy",
        "iphone",
        "candid",
        "snapshot",
        "finsta",
        "girl",
        "boy",
        "pov",
    }
)

# Маркеры сырого UGC / iPhone camera roll (legacy; НЕ дописывать в короткий 3–5 word query)
AUTHENTIC_PHOTO_MARKERS: tuple[str, ...] = (
    "cozy",
    "aesthetic",
    "candid",
    "iphone",
)

# Названия / теги — явный мусор (обои, градиенты, виджеты, вектор)
JUNK_TITLE_TERMS: tuple[str, ...] = (
    "wallpaper",
    "gradient",
    "vector",
    "illustration",
    "3d render",
    "3d graphic",
    "digital art",
    "abstract background",
    "phone wallpaper",
    "lockscreen",
    "homescreen",
    "desktop background",
    "stock background",
    "neon gradient",
    "mesh gradient",
    "blur gradient",
    # экраны / виджеты / мокапы вместо реальных предметов
    "widget",
    "mockup",
    "app icon",
    "ios theme",
    "digital template",
    "phone mockup",
    "ui kit",
    "ios widget",
    "android widget",
    # org / wellness pantry & product pack — confession vibe killers
    "pantry organization",
    "organized pantry",
    "pantry makeover",
    "pantry goals",
    "pantry inspo",
    "walk-in pantry",
    "walk in pantry",
    "kitchen organization",
    "snack station",
    "pantry labels",
    "container store",
    "home organization",
    "product photography",
    "product shot",
    "pack shot",
    "packaging design",
    "stock photo",
    "getty images",
    "shutterstock",
    # retail / brand / lookbook / UI chrome — drop before download
    "armani",
    "gucci",
    "louis vuitton",
    "chanel",
    "prada",
    "nike store",
    "adidas store",
    "zara window",
    "h&m window",
    "shop window display",
    "window display mannequin",
    "mannequin display",
    "retail display",
    "department store",
    "fashion lookbook",
    "street style blog",
    "outfit of the day",
    "ootd",
    "camera ui",
    "iphone camera",
    "ios camera",
    "android camera",
    "screenshot",
    "screen recording",
    "instagram story",
    "instagram ui",
    "tiktok ui",
    "stories template",
    "xiaohongshu",
    "rednote",
    "little red book",
)

# Title phrases that mark org/product junk even as substrings
_CONFESSION_VIBE_BAN_TITLE: tuple[str, ...] = (
    "pantry organization",
    "organized pantry",
    "pantry makeover",
    "kitchen organization",
    "snack station",
    "walk-in pantry",
    "walk in pantry",
    "product photography",
    "packaging design",
    "amazon finds",
    "homeroom",
    "window display",
    "mannequin",
    "lookbook",
    "outfit of the day",
    "camera app",
    "instagram ui",
    "screenshot",
)

# Скрытый ИИ без официальной метки Pinterest — по тексту пина
AI_TEXT_STOPWORDS: tuple[str, ...] = (
    "midjourney",
    "aiart",
    "ai art",
    "flux",
    "stablediffusion",
    "stable diffusion",
    "dall-e",
    "dalle",
    "civitai",
    "digital art",
    "render",
    "generated",
    "prompt",
)

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

HTML_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.pinterest.com/",
    "Upgrade-Insecure-Requests": "1",
}

CDN_HEADERS = {
    "User-Agent": CHROME_UA,
    "Referer": "https://www.pinterest.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

API_HEADERS_BASE = {
    "User-Agent": CHROME_UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "X-Pinterest-AppState": "active",
    "Origin": "https://www.pinterest.com",
    "Content-Type": "application/x-www-form-urlencoded",
}

ProgressCb = Callable[[str], None]


# ---------------------------------------------------------------------------
# Анти-ИИ поисковые формулы
# ---------------------------------------------------------------------------

def scrub_banned_query_terms(query: str) -> str:
    """Убирает из запроса промпт-лексику нейросетей."""
    cleaned = query
    for term in sorted(BANNED_QUERY_TERMS, key=len, reverse=True):
        cleaned = re.sub(re.escape(term), " ", cleaned, flags=re.I)
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_lighting_anchor(query: str) -> tuple[str, str]:
    """Вернуть (lighting_phrase|'', query_без_lighting)."""
    q = re.sub(r"\s+", " ", (query or "").strip())
    low = q.lower()
    for anchor in sorted(CAROUSEL_LIGHTING_ANCHORS, key=len, reverse=True):
        if anchor in low:
            cleaned = re.sub(re.escape(anchor), " ", q, count=1, flags=re.I)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return anchor, cleaned
    return "", q


def _slide_wants_phone(slide_text: str = "", query: str = "") -> bool:
    """True если слайд реально про телефон — тогда слово phone можно оставить."""
    blob = f"{slide_text or ''} {query or ''}".lower()
    return any(h in blob for h in _PHONE_CONTENT_HINTS)


def _clamp_query_words(
    query: str,
    *,
    min_w: int = 3,
    max_w: int = 4,
    allow_phone: bool = False,
) -> str:
    """
    [pose/action] [place/situation] [optional aesthetic|candid].
    iphone/finsta/snapshot НИКОГДА не дописываем; срезаем если прилипли.
    phone оставляем только если allow_phone (слайд про телефон).
    Позы (sitting/holding/staring…) НЕ выкидываем — это смысл запроса.
    """
    drop = {
        "shot", "on", "photo", "dump", "raw",
        "camera", "roll", "amateur", "flash", "girlhood", "pinterest",
        "rotting", "covering", "oversized", "from", "behind",
        "fairy", "lights", "blanket", "duvet", "hoodie", "open",
        "the", "and", "with", "for", "a", "an", "of", "to", "in", "by", "at", "on",
        "iphone", "finsta", "snapshot",  # шум; candid/aesthetic — стиль формулы
        *_LIGHTING_WORD_SPAM,
    }
    # позы ситуации защищены даже если попали в spam-список
    drop -= _SITUATION_POSE_KEEP
    if not allow_phone:
        drop.add("phone")

    style_ok = {"aesthetic", "candid"}
    words = [
        w for w in re.findall(r"[A-Za-z0-9']+", (query or "").lower())
        if len(w) > 1
    ]
    seen: set[str] = set()
    uniq: list[str] = []
    trailing_style = ""
    for w in words:
        if w in _SITUATION_POSE_KEEP:
            if w not in seen:
                seen.add(w)
                uniq.append(w)
            if len(uniq) >= max_w:
                break
            continue
        if w in drop or w in seen:
            continue
        if w in style_ok:
            trailing_style = w
            seen.add(w)
            continue
        seen.add(w)
        uniq.append(w)
        if len(uniq) >= max_w:
            break

    if trailing_style and len(uniq) < max_w:
        uniq.append(trailing_style)

    if len(uniq) < min_w:
        for filler in ("alone", "night", "window", "room", "desk", "floor"):
            if filler not in seen:
                uniq.append(filler)
                seen.add(filler)
            if len(uniq) >= min_w:
                break
    return " ".join(uniq[:max_w])


def ensure_mobile_query_marker(
    query: str, marker: str = "iphone"
) -> str:
    """
    Legacy-имя. Маркеры НЕ дописываем.
    Срезаем iphone/finsta, смысл situation-query сохраняем.
    """
    del marker
    return _clamp_query_words(query or "everyday indoor candid", allow_phone=False)


def finalize_photo_query(
    base: str, index: int = 0, *, slide_text: str = ""
) -> str:
    """
    Pinterest-запрос: human situation 3–4 слова.

    - iphone/finsta бессмысленно НЕ добавляем;
    - НЕ инжектим noun из случайных слов слайда;
    - phone оставляем только когда слайд реально про телефон;
    - aesthetic|candid — опциональный хвост формулы.
    """
    del index
    _, base_rest = extract_lighting_anchor(base)
    cleaned = scrub_banned_query_terms(base_rest)
    for legacy in (
        "candid 35mm film",
        "35mm film photo",
        "35mm film",
        "authentic lifestyle photo",
        "shot on iphone photo dump",
        "casual camera roll snapshot",
        "candid raw photo dump",
        "amateur flash photo",
        "girlhood aesthetic cozy",
        "pinterest girl aesthetic night",
        "bed rotting aesthetic",
        "cozy girl bedroom night",
        "girl bed cozy",
        "desk open journal",
        "aesthetic photo dump",
        "0.5x lens",
        "dark academia",
        "cozy aesthetic",
        "aesthetic night",
        "cozy night",
        "aesthetic mood",
        "rory gilmore aesthetic",
        *CAROUSEL_LIGHTING_ANCHORS,
    ):
        cleaned = re.sub(re.escape(legacy), " ", cleaned, flags=re.I)
    cleaned = re.sub(
        r"\b(academia|vibes?|moody|ambient)\b",
        " ",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # НЕ _inject_slide_noun — это и был literal word->object баг
    allow_phone = _slide_wants_phone(slide_text, cleaned)
    out = _clamp_query_words(
        cleaned, min_w=3, max_w=4, allow_phone=allow_phone
    )
    out = scrub_banned_query_terms(out) or out
    out = _clamp_query_words(
        out, min_w=3, max_w=4, allow_phone=allow_phone
    )
    return out or "everyday indoor candid"


def with_ugc_retry_marker(query: str) -> str:
    """Legacy: тот же situation-query (без iphone)."""
    return finalize_photo_query(query or "everyday indoor candid")


def situation_query_for_slide(
    text: str, index: int = 0, *, visual_scene: str = ""
) -> str:
    """
    Фоллбэк search_query = выжимка из visual_scene (или текста как сцены).
    ЗАПРЕЩЕНО: mood-стабы / keyword->object.
    """
    del index
    try:
        from core.llm_engine import search_query_from_visual_scene

        scene = (visual_scene or "").strip() or (text or "").strip()
        q = search_query_from_visual_scene(scene)
    except Exception:
        words = re.findall(r"[A-Za-z]{3,}", (visual_scene or text or ""))[:3]
        q = " ".join(words + ["candid"]) if words else "everyday indoor candid"
    return finalize_photo_query(q, slide_text=text or "")


# Legacy alias — GUI/старые вызовы
def aesthetic_query_for_slide(text: str, index: int = 0) -> str:
    """Deprecated name -> situation_query_for_slide (без object-map)."""
    return situation_query_for_slide(text, index)


def _query_is_abstract_only(query: str) -> bool:
    words = re.findall(r"[a-z0-9']+", (query or "").lower())
    if not words:
        return True
    return all(w in _ABSTRACT_ONLY_WORDS for w in words)


def _inject_slide_noun(query: str, slide_text: str = "") -> str:
    """Если запрос из одних абстракций — первое слово = noun/tangible из текста слайда."""
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not _query_is_abstract_only(q):
        return q
    # Сначала карта осязаемых объектов из llm_engine
    try:
        from core.llm_engine import _extract_tangible_query

        tangible = _extract_tangible_query(slide_text or "")
        if tangible:
            return tangible
    except Exception:
        pass
    noun = extract_key_noun(slide_text or "", query=q)
    noun = (noun or "").strip().lower()
    if not noun or noun in _ABSTRACT_ONLY_WORDS or len(noun) < 3:
        # запасной физический якорь — phone/keys только если явно в тексте слайда
        for fallback in (
            "window", "coffee", "laptop", "mug", "journal", "paper",
            "phone", "keys",
        ):
            if fallback in (slide_text or "").lower():
                noun = fallback
                break
        else:
            noun = "window"
    rest = [
        w
        for w in re.findall(r"[a-z0-9']+", q.lower())
        if w not in _ABSTRACT_ONLY_WORDS
        and w != noun
        and w not in MOBILE_QUERY_MARKERS
    ]
    parts = [noun] + rest[:1]
    return " ".join(parts)


def query_cache_key(search_query: str) -> str:
    """Ключ дискового кэша — строго md5 полного текста запроса."""
    norm = (search_query or "").strip().lower()
    return hashlib.md5(norm.encode("utf-8")).hexdigest()


def query_cache_dir(search_query: str) -> Path:
    """Папка только для ЭТОГО запроса. Чужие md5-папки трогать нельзя."""
    return _QUERY_CACHE_ROOT / query_cache_key(search_query)


def simplify_search_query(query: str) -> str:
    """
    Расширение пустого поиска: убрать самое узкое слово справа.
    Тема сохраняется — никаких чужих bedroom/kitchen fallback.
    """
    words = [w for w in re.split(r"\s+", (query or "").strip()) if w]
    if len(words) <= 1:
        return (query or "").strip()
    shorter = " ".join(words[:-1])
    cleaned = scrub_banned_query_terms(shorter)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or words[0]


# Узкие слова -> более частые Pinterest-синонимы (smart broaden)
_BROADEN_SYNONYMS: dict[str, str] = {
    "door": "floor",
    "doors": "floor",
    "feet": "socks",
    "foot": "socks",
    "rug": "carpet",
    "rugs": "carpet",
    "barefoot": "socks",
    "doormat": "carpet",
    "threshold": "hallway",
    "floorboards": "floor",
}


def is_fake_stub_pin_id(pin_id: str) -> bool:
    """True для зомби pin_img000 / img000 — ненастоящий Pinterest id."""
    return bool(_FAKE_PIN_ID_RE.fullmatch(str(pin_id or "").strip()))


def smart_broaden_queries(query: str, *, max_alts: int = 5) -> list[str]:
    """
    Если primary дал 0 результатов — расширить запрос:
    синонимы узких слов + отброс одного лишнего токена.
    Пример: 'feet rug door candid' -> 'feet rug floor candid', 'rug floor candid'…
    Без локальных заглушек.
    """
    raw = re.sub(r"\s+", " ", (query or "").strip())
    if not raw:
        return []
    words = [w for w in raw.split() if w]
    if len(words) < 2:
        return []

    style = ""
    core = list(words)
    if core and core[-1].lower() in {"candid", "aesthetic"}:
        style = core.pop()

    out: list[str] = []
    seen: set[str] = {raw.lower()}

    def _emit(parts: list[str]) -> None:
        parts = [p for p in parts if p]
        if not parts:
            return
        q = " ".join(parts + ([style] if style else []))
        q = re.sub(r"\s+", " ", q).strip()
        key = q.lower()
        if not q or key in seen:
            return
        seen.add(key)
        out.append(q)

    # 1) синонимная замена каждого узкого слова
    for i, w in enumerate(core):
        alt = _BROADEN_SYNONYMS.get(w.lower())
        if not alt:
            continue
        swapped = list(core)
        swapped[i] = alt
        _emit(swapped)

    # 2) отбросить одно слово с конца / начала core
    if len(core) >= 2:
        _emit(core[:-1])
        _emit(core[1:])

    # 3) отбросить два самых узких (оставить 2 + style)
    if len(core) >= 3:
        _emit(core[-2:])
        _emit(core[:2])

    # 4) simplify хвост (без style)
    shorter = simplify_search_query(raw)
    if shorter and shorter.lower() != raw.lower():
        key = shorter.lower()
        if key not in seen:
            seen.add(key)
            out.append(shorter)

    return out[: max(1, int(max_alts))]


_NOUN_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "if", "then", "than", "that",
        "this", "these", "those", "to", "of", "in", "on", "at", "for", "from",
        "with", "without", "about", "into", "over", "under", "my", "your",
        "our", "their", "his", "her", "its", "me", "you", "we", "they", "i",
        "is", "are", "was", "were", "be", "been", "being", "am", "do", "does",
        "did", "have", "has", "had", "will", "would", "can", "could", "should",
        "just", "only", "also", "very", "really", "like", "when", "while",
        "because", "so", "as", "it", "not", "no", "yes", "how", "what", "why",
        "who", "where", "which", "all", "any", "some", "more", "most", "too",
        "actually", "honestly", "yourself", "myself", "himself", "herself",
        "itself", "themselves", "ourselves", "someone", "something", "nothing",
        "everything", "everyone", "anyone", "being", "functioning", "adult",
        "truth", "need", "needs", "needed", "want", "wants", "feel", "feels",
        "feeling", "feels", "guilty", "hungry", "tired", "stressed", "exhausted",
        "pretending", "working", "stop", "turn", "off", "don", "doesn", "isn",
        "aren", "arent", "wasn", "weren", "won", "can", "cant", "dont", "didnt",
        "wont", "youre", "im", "its", "theres", "heres", "whats", "thats",
        "isnt", "wasnt", "werent", "havent", "hasnt", "hadnt", "wouldnt",
        "couldnt", "shouldnt", "late",
        "night", "day", "time", "still", "even", "ever", "never", "always",
        "often", "again", "once", "here", "there", "now", "then", "out",
        "up", "down", "back", "away", "after", "before", "during", "through",
        "into", "onto", "upon", "via", "per", "each", "every", "other",
        "same", "such", "own", "few", "many", "much", "lot", "bit", "way",
        "thing", "things", "stuff", "kind", "sort", "type", "part", "end",
        "start", "make", "made", "get", "got", "go", "goes", "went", "come",
        "came", "take", "took", "give", "gave", "keep", "kept", "let", "put",
        "say", "said", "tell", "told", "know", "knew", "think", "thought",
        "see", "saw", "look", "looking", "seem", "seems", "try", "trying",
        "use", "used", "using", "я", "ты", "он", "она", "мы", "вы", "они",
        "это", "как", "что", "для", "при", "над", "под", "без", "или", "но",
        "уже", "ещё", "еще", "мне", "тебе", "нас", "вас", "их", "его", "её",
        "ее", "просто", "очень", "когда", "чтобы", "если", "также", "был",
        "была", "были", "есть", "нет", "да",
    }
)


def _content_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-zА-Яа-яЁё']+", text or "")
    out: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        low = tok.lower().replace("'", "").strip()
        if len(low) < 3 or low in _NOUN_STOPWORDS:
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(low)
    return out


def extract_key_noun(slide_text: str, query: str = "") -> str:
    """
    Ключевой объект для noun-retry Pinterest.
    Приоритет: первое content-слово query -> tangible-map -> content из слайда.
    Никогда не возвращает stopwords вроде actually/honestly/yourself.
    """
    text = (slide_text or "").strip()
    q = (query or "").strip()

    # Из query: [объект] [локация] [стиль] — объект слева
    q_tokens = _content_tokens(q)
    if q_tokens:
        return q_tokens[0]

    try:
        from core.llm_engine import _extract_tangible_query

        for src in (text, q):
            if not src:
                continue
            tangible = _extract_tangible_query(src)
            if tangible:
                first = tangible.split()[0].lower()
                if first and first not in _NOUN_STOPWORDS:
                    return first
    except Exception:
        pass

    scored: list[tuple[int, str]] = []
    for low in _content_tokens(text):
        scored.append((len(low), low))
    if not scored:
        return ""
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def build_relevance_text(
    slide_text: str,
    query: str = "",
    *,
    visual_scene: str = "",
) -> str:
    """
    Primary SigLIP anchor. Prefer visual_scene physics; else query+props.
    """
    texts = build_relevance_texts(
        slide_text, query, visual_scene=visual_scene
    )
    return texts[0] if texts else "lifestyle photo"


def build_relevance_texts(
    slide_text: str,
    query: str = "",
    *,
    visual_scene: str = "",
) -> list[str]:
    """
    One or two anchors: scene physics AND confession-prop vibe.
    Caller takes max(score_scene, score_vibe) per image.
    """
    out: list[str] = []
    scene = re.sub(r"\s+", " ", (visual_scene or "").strip())
    if len(scene) >= 8:
        words = scene.split()
        if len(words) > 28:
            scene = " ".join(words[:28])
        out.append(scene)

    # Vibe / prop anchor from slide text + query (even when scene exists)
    parts: list[str] = []
    q = (query or "").strip()
    if q:
        parts.append(q)
    try:
        from core.llm_engine import _extract_tangible_query

        tangible = _extract_tangible_query(slide_text or "")
        if tangible and tangible.lower() not in {p.lower() for p in parts}:
            parts.append(tangible)
    except Exception:
        pass
    try:
        from core.query_forge import _extract_props

        for phrase in _extract_props(
            f"{slide_text} {query} {visual_scene}", limit=2
        ):
            if phrase.lower() not in {p.lower() for p in parts}:
                parts.append(phrase)
    except Exception:
        pass
    extra = _content_tokens(slide_text or "")[:6]
    for w in extra:
        if w not in {p.lower() for p in parts}:
            if q and w in q.lower().split():
                continue
            parts.append(w)
        if len(" ".join(parts).split()) >= 10:
            break
    vibe = " ".join(parts).strip()
    if vibe:
        # Skip near-duplicate of scene
        if not out or vibe.lower() != out[0].lower():
            # Enough overlap with scene → don't burn a second SigLIP call
            if out:
                scene_toks = set(out[0].lower().split())
                vibe_toks = set(vibe.lower().split())
                overlap = len(scene_toks & vibe_toks) / max(len(vibe_toks), 1)
                if overlap < 0.6:
                    out.append(vibe)
            else:
                out.append(vibe)
    if not out:
        out.append(q or "lifestyle photo")
    return out[:2]


_WEAK_QUERY_HEADS = frozenset(
    {
        "sad", "happy", "person", "people", "man", "woman", "guy", "girl",
        "dim", "empty", "looking", "away", "someone", "everybody", "human",
        "people", "face", "portrait", "model",
    }
)


def is_weak_pinterest_query(query: str) -> bool:
    """Слишком абстрактный/стоковый запрос -> почти всегда 0 живых фото."""
    words = [w for w in re.split(r"\s+", (query or "").strip().lower()) if w]
    if not words:
        return True
    if len(words) == 1:
        return True
    if words[0] in _WEAK_QUERY_HEADS:
        return True
    if "person" in words or "people" in words:
        return True
    return False


def build_fallback_queries(
    primary: str,
    slide_text: str = "",
    *,
    index: int = 0,
    topic: str = "",
) -> list[str]:
    """
    Цепочка альтернативных Pinterest-запросов.
    Если primary не дал фото — пробуем упрощения, tangible, mood-pool.
    """
    seen: set[str] = set()
    out: list[str] = []

    def _add(raw: str, *, allow_weak: bool = False) -> None:
        q = scrub_banned_query_terms((raw or "").strip())
        q = re.sub(r"\s+", " ", q).strip()
        if not q:
            return
        # clamp без bed-fallback: finalize может вернуть ""
        try:
            clamped = finalize_photo_query(q, index, slide_text=slide_text or "")
        except Exception:
            clamped = q
        q = (clamped or q).strip()
        key = q.lower()
        if not key or key in seen:
            return
        if not allow_weak and is_weak_pinterest_query(q):
            return
        seen.add(key)
        out.append(q)

    primary = (primary or "").strip()
    if primary and not is_weak_pinterest_query(primary):
        _add(primary, allow_weak=True)
    elif primary:
        # слабый primary — всё равно пробуем первым, но сразу копит алиасы
        _add(primary, allow_weak=True)

    # Упрощение того же запроса (2–3 слова)
    q = primary
    for _ in range(3):
        broad = simplify_search_query(q)
        if not broad or broad.lower() == q.lower():
            break
        if len(broad.split()) >= 2:
            _add(broad)
        q = broad

    noun = extract_key_noun(slide_text, query=primary)
    if noun and noun.lower() not in _WEAK_QUERY_HEADS:
        _add(f"{noun} on table")
        _add(f"{noun} in hands")
        _add(f"{noun} by window")

    try:
        from core.llm_engine import search_query_from_visual_scene

        # Только выжимка из текста/primary как сцены — без mood-стабов
        scene_q = search_query_from_visual_scene(
            slide_text or primary or "", topic=topic or ""
        )
        if scene_q:
            _add(scene_q)
        # упрощённый вариант без style-хвоста
        core = " ".join(
            w
            for w in scene_q.split()
            if w.lower() not in {"candid", "aesthetic"}
        )
        if core and core.lower() != scene_q.lower():
            _add(core)
    except Exception:
        pass

    if not out and primary:
        out = [primary]
    return out


def candidate_final_score(
    relevance: float,
    ugc: float,
    harmony: float = 100.0,
    taste: float | None = None,
) -> float:
    """
    final_score = relevance×0.30 + taste×0.30 + ugc×0.40
    (harmony в сигнатуре для совместимости, вес 0).
    taste=None / untrained -> 0.50.
    """
    del harmony
    r = max(0.0, min(1.0, float(relevance)))
    u = max(0.0, min(1.0, float(ugc)))
    if taste is None:
        t = 0.50
    else:
        t = max(0.0, min(1.0, float(taste)))
    return round(
        r * FINAL_REL_W + t * FINAL_TASTE_W + u * FINAL_UGC_W,
        4,
    )


_FASHION_TITLE_HINTS: tuple[str, ...] = (
    "outfit",
    "fashion",
    "street style",
    "streetstyle",
    "ootd",
    "lookbook",
    "model",
    "posing",
    "full body",
    "fullbody",
    "coat",
    "trench",
)


def looks_like_fullbody_fashion_shot(
    image: Image.Image, title: str = ""
) -> bool:
    """
    Full-body fashion / модель на улице (не POV от первого лица).
    Title-hints + SigLIP fashion vs POV (если доступен).
    """
    low = (title or "").lower()
    if any(h in low for h in _FASHION_TITLE_HINTS):
        return True
    try:
        from core.taste_embedder import get_embedder

        emb = get_embedder()
        fashion = float(
            emb.compute_text_image_relevances(
                "full body fashion model street style outfit posed standing on city sidewalk",
                [image],
            )[0]
        )
        pov = float(
            emb.compute_text_image_relevances(
                "first person pov hands holding coffee cup walking sidewalk feet on asphalt",
                [image],
            )[0]
        )
        return fashion > pov + 0.08
    except Exception:
        return False


def apply_pov_fashion_ugc_penalty(
    candidates: list[CandidateImage], query: str
) -> int:
    """
    Если в query есть 'pov' и кадр = full-body fashion -> ugc × 0.75 (−25%).
    Возвращает число оштрафованных.
    """
    if "pov" not in (query or "").lower() or not candidates:
        return 0
    # Быстрый title-pass
    flagged: list[int] = []
    need_vision: list[int] = []
    for i, c in enumerate(candidates):
        low = (c.title or "").lower()
        if any(h in low for h in _FASHION_TITLE_HINTS):
            flagged.append(i)
        else:
            need_vision.append(i)

    if need_vision:
        try:
            from core.taste_embedder import get_embedder

            emb = get_embedder()
            imgs = [candidates[i].image for i in need_vision]
            fashion = emb.compute_text_image_relevances(
                "full body fashion model street style outfit posed standing on city sidewalk",
                imgs,
            )
            pov = emb.compute_text_image_relevances(
                "first person pov hands holding coffee cup walking sidewalk feet on asphalt",
                imgs,
            )
            for j, idx in enumerate(need_vision):
                if float(fashion[j]) > float(pov[j]) + 0.08:
                    flagged.append(idx)
        except Exception:
            pass

    for i in flagged:
        candidates[i].ugc_score = max(
            0.0, float(candidates[i].ugc_score) * POV_FASHION_UGC_MULT
        )
    return len(set(flagged))


# ---------------------------------------------------------------------------
# Gender Lock + No Faces in Body (carousel consistency)
# ---------------------------------------------------------------------------

GENDER_FEMALE_PROMPT = "a woman, a girl"
GENDER_MALE_PROMPT = "a man, a guy"
# Drop when opposite gender is within this of the lock (was 0.10 — too soft on hands)
GENDER_LOCK_MARGIN = 0.02

FEMININE_HANDS_PROMPT = (
    "woman hands, feminine hands, manicured nails, nail polish, long nails"
)
MASCULINE_HANDS_PROMPT = (
    "man hands, masculine hands, male hands, no nail polish, short nails"
)

FACE_FRONTAL_PROMPT = (
    "close-up frontal portrait of a person's face looking at the camera"
)
POV_NO_FACE_PROMPT = (
    "first person pov hands objects shoes feet environment back of head no face"
)
FACE_BODY_MARGIN = 0.08

# Attribute Lock (Character DNA -> SigLIP hair color / length)
ATTR_BLONDE_PROMPT = "blonde hair, light blonde hair"
ATTR_DARK_PROMPT = "dark hair, brunette, black hair, male"
ATTR_LONG_PROMPT = "long hair, long flowing hair"
ATTR_SHORT_PROMPT = "pixie cut, short hair, buzz cut"
# Want must beat reject by this margin, else drop (stops blonde↔brunette ties)
ATTR_COLOR_MARGIN = 0.015
ATTR_LENGTH_MARGIN = 0.015
PERSON_PRESENT_PROMPT = (
    "a person visible in frame, human body hair face hands silhouette"
)
NO_PERSON_PROMPT = (
    "empty room objects only still life interior no people no human"
)
PERSON_PRESENT_MARGIN = 0.02

_FEMALE_TITLE_HINTS: tuple[str, ...] = (
    "woman",
    "girl ",
    "female",
    "girlfriend",
    "wife",
    "ladies",
    "manicure",
    "nail polish",
    "nails",
    "lipstick",
    "bra ",
    "dress",
    "blouse",
)
_MALE_TITLE_HINTS: tuple[str, ...] = (
    "man ",
    " men",
    "guy ",
    "male ",
    "boyfriend",
    "husband",
    "beard",
)


def image_has_visible_person(image: Image.Image) -> bool:
    """SigLIP: True if a person (body/hair/face) is likely visible."""
    try:
        score_p, score_n = attribute_cosine_pair(
            image, PERSON_PRESENT_PROMPT, NO_PERSON_PROMPT
        )
        return score_p > score_n + PERSON_PRESENT_MARGIN
    except Exception:
        return False


_FACE_TITLE_HINTS: tuple[str, ...] = (
    "portrait",
    "selfie",
    "face",
    "close up",
    "closeup",
    "headshot",
    "mugshot",
    "profile pic",
    "smiling woman",
    "smiling man",
    "beautiful girl",
    "handsome guy",
)


def gender_cosine_pair(image: Image.Image) -> tuple[float, float]:
    """
    Raw L2-cosine (dot) vs female/male text anchors.
    Returns (sim_female, sim_male).
    """
    from core.taste_embedder import get_embedder
    import numpy as np

    emb = get_embedder()
    i_vec = emb.embed_images([image.convert("RGB")])[0]
    t_mat = emb.embed_texts([GENDER_FEMALE_PROMPT, GENDER_MALE_PROMPT])
    sim_f = float(np.dot(i_vec, t_mat[0]))
    sim_m = float(np.dot(i_vec, t_mat[1]))
    return sim_f, sim_m


def attribute_cosine_pair(
    image: Image.Image, want_prompt: str, reject_prompt: str
) -> tuple[float, float]:
    """Dot(img, want_text) vs Dot(img, reject_text)."""
    from core.taste_embedder import get_embedder
    import numpy as np

    emb = get_embedder()
    i_vec = emb.embed_images([image.convert("RGB")])[0]
    t_mat = emb.embed_texts([want_prompt, reject_prompt])
    return float(np.dot(i_vec, t_mat[0])), float(np.dot(i_vec, t_mat[1]))


def _dna_hair_color_prompts(
    dna: dict[str, str] | None,
) -> tuple[str, str] | None:
    """(want, reject) hair-color prompts from character_dna, or None."""
    if not dna:
        return None
    hair = str(dna.get("hair") or "").lower()
    gender = str(dna.get("gender") or "female").lower()
    if any(t in hair for t in ("blonde", "blond", "platinum", "light blonde")):
        reject = "dark hair, brunette, black hair, ginger hair, red hair"
        if gender != "female":
            reject = "dark hair, brunette, black hair, woman, long nails"
        return ATTR_BLONDE_PROMPT, reject
    # light brown / caramel before generic brown
    if any(
        t in hair
        for t in ("light brown", "caramel", "honey", "dirty blonde")
    ) or ("light" in hair and "brown" in hair):
        return (
            "light brown hair, dirty blonde hair, honey brown hair, caramel hair",
            "platinum blonde hair, jet black hair, ginger red hair",
        )
    if any(
        t in hair
        for t in ("brunette", "dark hair", "black hair", "brown hair", "dark ")
    ):
        return (
            "dark hair, brunette, brown hair, black hair",
            "blonde hair, light blonde hair, platinum blonde, ginger hair, red hair",
        )
    if "ginger" in hair or "red" in hair or "auburn" in hair:
        return (
            "ginger hair, red hair, auburn hair",
            "blonde hair, platinum blonde, black hair, dark brunette",
        )
    return None


def _dna_hair_length_prompts(
    dna: dict[str, str] | None,
) -> tuple[str, str] | None:
    """(want, reject) length prompts when DNA specifies long/short."""
    if not dna:
        return None
    hair = str(dna.get("hair") or "").lower()
    if "long" in hair:
        return ATTR_LONG_PROMPT, ATTR_SHORT_PROMPT
    if "short" in hair or "pixie" in hair or "buzz" in hair:
        return ATTR_SHORT_PROMPT, ATTR_LONG_PROMPT
    return None


def _query_is_personish(text: str) -> bool:
    """True if query/title implies a person, hair, or hands (needs attribute gate)."""
    low = (text or "").lower()
    # word-boundary match — plain "man" in "window"/"human" must NOT fire
    return bool(
        re.search(
            r"\b(girl|guy|woman|women|man|men|person|people|hair|"
            r"blonde|blond|brunette|ginger|auburn|hand|hands|selfie|mirror|"
            r"portrait|face|model|behind)\b",
            low,
        )
    )


def _query_is_handsish(text: str) -> bool:
    low = (text or "").lower()
    return bool(re.search(r"\b(hand|hands|holding|manicure|nails)\b", low))


def attribute_mismatches_dna(
    image: Image.Image,
    character_dna: dict[str, str] | None,
    title: str = "",
    *,
    query: str = "",
) -> bool:
    """
    True = hard-drop: candidate hair/gender attributes clash with character_dna.

    Personish queries always gated. Object/environment queries are gated ONLY
    when a person is actually visible in the image (fixes brunette-on-blonde
    pantry etc.). Empty object still-lifes skip hair SigLIP.
    Outfit is intentionally ignored — only hair color/length + gender.
    """
    if not character_dna:
        return False
    personish = _query_is_personish(query) or _query_is_personish(title)
    if not personish:
        # Object query — gate only if a person slipped into the frame
        if not image_has_visible_person(image):
            return False

    low = (title or "").lower()
    hair = str(character_dna.get("hair") or "").lower()
    gender = str(character_dna.get("gender") or "").lower()
    handsish = _query_is_handsish(query) or _query_is_handsish(title)

    # Fast title rejects (gender)
    if gender == "female" and any(h in low for h in _MALE_TITLE_HINTS):
        return True
    if gender == "male" and any(h in low for h in _FEMALE_TITLE_HINTS):
        return True

    # Fast title rejects (hair color family)
    if "blonde" in hair or "blond" in hair:
        if any(
            h in low
            for h in (
                "brunette",
                "black hair",
                "dark hair",
                "ginger",
                "redhead",
                "auburn",
                "pixie cut",
            )
        ):
            if "blonde" not in low and "blond" not in low:
                return True
    if any(t in hair for t in ("brunette", "brown", "dark", "black")):
        if any(
            h in low
            for h in ("blonde", "blond", "platinum", "ginger", "redhead", "auburn")
        ):
            if not any(t in low for t in ("brunette", "brown", "dark", "black")):
                return True
    if any(t in hair for t in ("ginger", "red", "auburn")):
        if any(
            h in low for h in ("blonde", "blond", "platinum", "brunette", "black hair")
        ):
            if not any(t in low for t in ("ginger", "redhead", "auburn", "red hair")):
                return True
    if "long" in hair and any(
        h in low for h in ("pixie", "buzz cut", "short bob", "crew cut")
    ):
        return True
    if ("short" in hair or "pixie" in hair) and any(
        h in low for h in ("long hair", "long wavy", "flowing hair")
    ):
        return True

    # DNA gender via SigLIP (critical for hands/behind where titles are weak)
    if gender in ("female", "male"):
        try:
            sim_f, sim_m = gender_cosine_pair(image)
            if gender == "female" and sim_m > sim_f + GENDER_LOCK_MARGIN:
                return True
            if gender == "male" and sim_f > sim_m + GENDER_LOCK_MARGIN:
                return True
        except Exception:
            pass
        # Hands close-ups: feminine nails vs masculine hands
        if handsish:
            try:
                fem, masc = attribute_cosine_pair(
                    image, FEMININE_HANDS_PROMPT, MASCULINE_HANDS_PROMPT
                )
                if gender == "male" and fem > masc + GENDER_LOCK_MARGIN:
                    return True
                if gender == "female" and masc > fem + GENDER_LOCK_MARGIN:
                    return True
            except Exception:
                pass

    # Hair color/length — on hands frames hair is often at edges; still drop
    # clear color clashes (fixes auburn DNA + dirty-blonde hands selfies).
    color_pair = _dna_hair_color_prompts(character_dna)
    if color_pair:
        want, reject = color_pair
        try:
            score_want, score_reject = attribute_cosine_pair(
                image, want, reject
            )
            if handsish:
                # Only hard-drop clear opposite colors (avoid emptying pool)
                if score_reject > score_want + ATTR_COLOR_MARGIN:
                    return True
            elif score_want < score_reject + ATTR_COLOR_MARGIN:
                return True
        except Exception:
            pass

    if handsish:
        return False

    length_pair = _dna_hair_length_prompts(character_dna)
    if length_pair:
        want_l, reject_l = length_pair
        try:
            score_want_l, score_reject_l = attribute_cosine_pair(
                image, want_l, reject_l
            )
            if score_want_l < score_reject_l + ATTR_LENGTH_MARGIN:
                return True
        except Exception:
            pass

    return False


def apply_attribute_lock_filter(
    candidates: list[CandidateImage],
    character_dna: dict[str, str] | None,
    *,
    slide_index: int = 0,
    query: str = "",
) -> tuple[list[CandidateImage], int]:
    """
    Hard attribute gate when character_dna is set.
    Object-only slides still check per-image if a person is visible.
    """
    if not character_dna or not candidates:
        return candidates, 0
    kept: list[CandidateImage] = []
    dropped = 0
    hair = str(character_dna.get("hair") or "")
    for c in candidates:
        q = query or getattr(c, "query", "") or ""
        if attribute_mismatches_dna(
            c.image, character_dna, c.title, query=q
        ):
            dropped += 1
            c.is_relevant = False
            c.relevance_reason = (
                f"attribute-lock: mismatch vs DNA hair={hair!r}"
            )
            continue
        kept.append(c)
    if dropped:
        print(
            f"[attr-lock] slide {slide_index + 1}: dropped {dropped} "
            f"(dna hair={hair!r}, left={len(kept)})"
        )
    return kept, dropped


def infer_carousel_gender(image: Image.Image) -> str:
    """Slide-1 lock: 'female' if sim_female > sim_male else 'male'."""
    try:
        sim_f, sim_m = gender_cosine_pair(image)
        gender = "female" if sim_f > sim_m else "male"
        print(
            f"[gender-lock] slide1 -> {gender} "
            f"(female={sim_f:.3f} male={sim_m:.3f})"
        )
        return gender
    except Exception as exc:
        print(f"[gender-lock] infer fail: {exc} - default female")
        return "female"


def gender_mismatches_lock(
    image: Image.Image,
    carousel_gender: str,
    title: str = "",
    *,
    query: str = "",
) -> bool:
    """
    True = drop candidate: opposite gender attributes clearly dominate.
    female lock -> drop if sim_male > sim_female + margin
    male lock -> drop if sim_female > sim_male + margin
    Also drops feminine-nail hand closeups under male lock.
    """
    g = (carousel_gender or "").strip().lower()
    if g not in ("female", "male"):
        return False
    low = (title or "").lower()
    if g == "female" and any(h in low for h in _MALE_TITLE_HINTS):
        return True
    if g == "male" and any(h in low for h in _FEMALE_TITLE_HINTS):
        return True
    try:
        sim_f, sim_m = gender_cosine_pair(image)
        if g == "female" and sim_m > sim_f + GENDER_LOCK_MARGIN:
            return True
        if g == "male" and sim_f > sim_m + GENDER_LOCK_MARGIN:
            return True
    except Exception:
        pass
    # Hands / nail closeups under male DNA
    if g == "male" and (
        _query_is_handsish(title) or _query_is_handsish(query)
    ):
        try:
            fem, masc = attribute_cosine_pair(
                image, FEMININE_HANDS_PROMPT, MASCULINE_HANDS_PROMPT
            )
            if fem > masc + GENDER_LOCK_MARGIN:
                return True
        except Exception:
            pass
    return False


def looks_like_frontal_face(image: Image.Image, title: str = "") -> bool:
    """Large frontal face / portrait — forbidden on body slides 2..N."""
    low = (title or "").lower()
    if any(h in low for h in _FACE_TITLE_HINTS):
        return True
    try:
        from core.taste_embedder import get_embedder

        emb = get_embedder()
        face = float(
            emb.compute_text_image_relevances(FACE_FRONTAL_PROMPT, [image])[0]
        )
        pov = float(
            emb.compute_text_image_relevances(POV_NO_FACE_PROMPT, [image])[0]
        )
        return face > pov + FACE_BODY_MARGIN
    except Exception:
        return False


def apply_gender_lock_filter(
    candidates: list[CandidateImage],
    carousel_gender: str | None,
    *,
    slide_index: int = 0,
    query: str = "",
) -> tuple[list[CandidateImage], int]:
    """
    All slides: drop opposite-gender attributes vs DNA / slide-1 lock.
    (Previously skipped slide 1 — that let male DNA start with a female hook.)
    """
    if not carousel_gender or not candidates:
        return candidates, 0
    kept: list[CandidateImage] = []
    dropped = 0
    for c in candidates:
        q = query or getattr(c, "query", "") or ""
        if gender_mismatches_lock(
            c.image, carousel_gender, c.title, query=q
        ):
            dropped += 1
            c.is_relevant = False
            c.relevance_reason = (
                f"gender-lock ({carousel_gender}): opposite attributes"
            )
            continue
        kept.append(c)
    if dropped:
        print(
            f"[gender-lock] slide {slide_index + 1}: dropped {dropped} "
            f"(lock={carousel_gender}, left={len(kept)})"
        )
    return kept, dropped


def apply_no_faces_body_filter(
    candidates: list[CandidateImage],
    *,
    slide_index: int = 0,
) -> tuple[list[CandidateImage], int]:
    """
    Slides 2..N: drop frontal portraits; prefer POV / hands / objects.
    Slide 1 may keep faces.
    """
    if slide_index <= 0 or not candidates:
        return candidates, 0
    kept: list[CandidateImage] = []
    dropped = 0
    for c in candidates:
        if looks_like_frontal_face(c.image, c.title):
            dropped += 1
            c.is_relevant = False
            c.relevance_reason = "no-faces-body: frontal portrait"
            continue
        kept.append(c)
    if dropped:
        print(
            f"[no-faces] slide {slide_index + 1}: dropped {dropped} "
            f"frontal faces (left={len(kept)})"
        )
    return kept, dropped


def _filter_consistency_gates(
    candidates: list[CandidateImage],
    *,
    slide_index: int = 0,
    carousel_gender: str | None = None,
    character_dna: dict[str, str] | None = None,
    query: str = "",
) -> list[CandidateImage]:
    """Attribute DNA + no-faces + gender lock (pre-rank)."""
    if not candidates:
        return candidates
    out = candidates
    out, _ = apply_attribute_lock_filter(
        out, character_dna, slide_index=slide_index, query=query
    )
    out, _ = apply_no_faces_body_filter(out, slide_index=slide_index)
    out, _ = apply_gender_lock_filter(
        out, carousel_gender, slide_index=slide_index, query=query
    )
    return out


def title_looks_like_junk(title: str) -> bool:
    """True если в названии/тегах wallpaper / gradient / org-pantry / product pack."""
    low = (title or "").lower()
    if any(term in low for term in JUNK_TITLE_TERMS):
        return True
    if any(term in low for term in _CONFESSION_VIBE_BAN_TITLE):
        return True
    return False


def title_looks_like_org_or_product(title: str) -> bool:
    """Org pantry / brand pack shot — not confession UGC."""
    low = (title or "").lower()
    return any(term in low for term in _CONFESSION_VIBE_BAN_TITLE)


def looks_like_letterbox_wallpaper(image: Image.Image) -> bool:
    """
    Широкие почти-чёрные полосы по краям (обои / фиктивный 3D на чёрном фоне).
    """
    try:
        img = image.convert("RGB")
        w, h = img.size
        if w < 40 or h < 40:
            return False
        # сэмпл маленькой сетки
        small = img.resize((64, 64), Image.Resampling.BILINEAR)
        px = small.load()
        assert px is not None

        def band_stats(rows: range, cols: range) -> tuple[float, float]:
            vals: list[float] = []
            for y in rows:
                for x in cols:
                    r, g, b = px[x, y]
                    vals.append(0.299 * r + 0.587 * g + 0.114 * b)
            if not vals:
                return 255.0, 255.0
            mean = sum(vals) / len(vals)
            var = sum((v - mean) ** 2 for v in vals) / len(vals)
            return mean, var

        top_m, top_v = band_stats(range(0, 8), range(64))
        bot_m, bot_v = band_stats(range(56, 64), range(64))
        left_m, left_v = band_stats(range(64), range(0, 8))
        right_m, right_v = band_stats(range(64), range(56, 64))
        mid_m, _ = band_stats(range(20, 44), range(20, 44))

        # классический letterbox: тёмные однородные полосы + более светлая середина
        h_bars = (
            top_m < 28
            and bot_m < 28
            and top_v < 80
            and bot_v < 80
            and mid_m > 45
        )
        v_bars = (
            left_m < 28
            and right_m < 28
            and left_v < 80
            and right_v < 80
            and mid_m > 45
        )
        return bool(h_bars or v_bars)
    except Exception:
        return False


def looks_like_flat_gradient(image: Image.Image) -> bool:
    """Грубый детектор плоского градиента / абстрактного фона (мало деталей)."""
    try:
        small = image.convert("RGB").resize((32, 32), Image.Resampling.BILINEAR)
        px = list(small.getdata())
        if len(px) < 64:
            return False
        # низкая локальная вариация = «мыло» / градиент
        diffs = 0
        for i in range(0, len(px) - 1):
            r1, g1, b1 = px[i]
            r2, g2, b2 = px[i + 1]
            if abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2) > 40:
                diffs += 1
        # почти нет резких переходов -> подозрительно гладко
        return diffs < 18
    except Exception:
        return False


def looks_like_low_quality(image: Image.Image, *, bytes_len: int = 0) -> bool:
    """
    Soft/noisy/tiny phone dumps we never want in a carousel.
    - short side too small
    - tiny file (heavy compress / icon)
    - extreme blur (Laplacian variance)
    - near-uniform mush
    """
    try:
        import numpy as np

        img = image.convert("RGB")
        w, h = img.size
        short = min(w, h)
        if short < 480:
            return True
        if w * h < 480 * 640:
            return True
        if bytes_len and bytes_len < 18_000:
            return True

        # Blur via Laplacian variance on downscaled gray
        small = img.resize((320, 320), Image.Resampling.BILINEAR)
        gray = np.asarray(small.convert("L"), dtype=np.float32)
        # 3x3 Laplacian kernel
        lap = (
            -4 * gray
            + np.roll(gray, 1, 0)
            + np.roll(gray, -1, 0)
            + np.roll(gray, 1, 1)
            + np.roll(gray, -1, 1)
        )
        var = float(lap.var())
        if var < 18.0:  # very soft / out of focus
            return True
        if var < 28.0 and float(gray.std()) < 28.0:
            return True  # soft + flat = mush
        return False
    except Exception:
        return False


def is_junk_candidate_image(
    image: Image.Image, title: str = "", *, bytes_len: int = 0
) -> bool:
    """Pillow + title: обои / градиенты / виджеты / studio-stock / low-quality."""
    if title_looks_like_junk(title):
        return True
    if looks_like_letterbox_wallpaper(image):
        return True
    if looks_like_flat_gradient(image):
        return True
    if looks_like_low_quality(image, bytes_len=bytes_len):
        return True
    try:
        from core.ugc_filter import stock_pro_heuristic_penalty

        # Hard studio white / airbrush — never keep even in completion
        if stock_pro_heuristic_penalty(image) >= 0.34:
            return True
    except Exception:
        pass
    return False


def _board_text(obj: dict[str, Any]) -> str:
    board = obj.get("board")
    if isinstance(board, dict):
        parts = [
            board.get("name"),
            board.get("url"),
            board.get("slug"),
            board.get("description"),
        ]
        return " ".join(str(p) for p in parts if p)
    if board is not None:
        return str(board)
    return ""


def _pin_text_blob(obj: dict[str, Any]) -> str:
    """title + description + link + board — поля для текстового анти-ИИ фильтра."""
    parts: list[str] = []
    for key in (
        "title",
        "grid_title",
        "gridTitle",
        "description",
        "closeup_description",
        "rich_summary",
        "link",
        "dominant_link",
        "source_link",
    ):
        val = obj.get(key)
        if val:
            parts.append(str(val))
    parts.append(_board_text(obj))
    return " ".join(parts).lower()


def _text_looks_like_ai(obj: dict[str, Any]) -> bool:
    """True, если в метаданных пина есть стоп-слова скрытого ИИ."""
    blob = _pin_text_blob(obj)
    if not blob.strip():
        return False
    for stop in AI_TEXT_STOPWORDS:
        if stop in blob:
            return True
    return False


# ---------------------------------------------------------------------------
# Данные
# ---------------------------------------------------------------------------

@dataclass
class PinMeta:
    pin_id: str
    title: str
    image_url: str
    orig_url: str
    is_ai: bool | None = None
    # True when returned via soft-reuse after run-wide pin exhaustion
    reuse_after_exhaustion: bool = False


@dataclass
class CandidateImage:
    pin_id: str
    title: str
    source_url: str
    query: str
    image: Image.Image
    via_fallback: bool = False
    bytes_len: int = 0
    relevance_score: float = 0.0
    is_relevant: bool = True
    relevance_reason: str = ""
    combined_score: float = 0.0
    text_relevance: float = 0.0
    text_relevance_scored: bool = False
    taste_score: float = 0.5
    taste_scored: bool = False
    ugc_score: float = 0.5
    ugc_scored: bool = False
    harmony_score: float = 100.0
    selection_mode: str = ""
    # Propagated from PinMeta when soft-reused after used_pins exhaustion
    reuse_after_exhaustion: bool = False


def weighted_promote_top3(
    ranked: list[CandidateImage],
    *,
    mode: str = "hard_top3_sample",
) -> list[CandidateImage]:
    """
    Взвешенный выбор среди топ-3 по combined_score; победитель -> индекс 0.
    Не трогает пул с единственным кандидатом; нулевые веса страхуем.
    """
    if not ranked:
        return ranked
    if len(ranked) == 1:
        if not ranked[0].selection_mode:
            ranked[0].selection_mode = mode
        return ranked
    top_candidates = ranked[:3]
    weights = [max(float(c.combined_score), 1e-6) for c in top_candidates]
    chosen = random.choices(top_candidates, weights=weights, k=1)[0]
    chosen.selection_mode = mode
    rest = [c for c in ranked if c is not chosen]
    return [chosen] + rest


def emergency_candid_iphone_query(slide_text: str = "", query: str = "") -> str:
    """Короткий fallback: [предмет] [локация] (без iphone)."""
    return finalize_photo_query(
        query or "coffee window", slide_text=slide_text or ""
    )


@dataclass
class HarvestProgress:
    stage: str = ""
    found: int = 0
    ai_rejected: int = 0
    downloaded: int = 0
    bytes_total: int = 0
    elapsed_sec: float = 0.0
    speed_mbps: float = 0.0


# ---------------------------------------------------------------------------
# Парсинг пинов
# ---------------------------------------------------------------------------

def _normalize_html(html: str) -> str:
    return (
        html.replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\/", "/")
    )


def _pick_image_url(images: dict[str, Any] | None) -> tuple[str, str]:
    if not isinstance(images, dict):
        return "", ""
    order_preview = ("736x", "564x", "474x", "236x", "orig", "originals")
    order_orig = ("orig", "originals", "736x", "564x", "474x")

    def url_of(key: str) -> str:
        node = images.get(key)
        if isinstance(node, dict):
            return str(node.get("url") or "")
        if isinstance(node, str):
            return node
        return ""

    preview = next((url_of(k) for k in order_preview if url_of(k)), "")
    orig = next((url_of(k) for k in order_orig if url_of(k)), preview)
    if preview and "/originals/" in preview:
        preview = preview.replace("/originals/", "/736x/")
    return preview, orig


def _walk_collect_pins(obj: Any, out: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > 28 or len(out) >= MAX_SEARCH_PINS * 2:
        return
    if isinstance(obj, dict):
        pid = obj.get("id") or obj.get("entityId")
        images = obj.get("images")
        if pid and isinstance(images, dict):
            out.append(obj)
        for v in obj.values():
            _walk_collect_pins(v, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj[:100]:
            _walk_collect_pins(item, out, depth + 1)


def _ai_flag_from_obj(obj: dict[str, Any]) -> bool | None:
    dmst = obj.get("digitalMediaSourceType")
    if dmst is None:
        dmst = obj.get("digital_media_source_type")
    topics = obj.get("genAiTopics") or obj.get("gen_ai_topics")
    if dmst == AI_SOURCE_TYPE or dmst == str(AI_SOURCE_TYPE):
        return True
    if isinstance(topics, list) and len(topics) > 0:
        return True
    return None


def _pin_from_obj(obj: dict[str, Any]) -> PinMeta | None:
    pid = str(obj.get("id") or obj.get("entityId") or "").strip()
    if not re.fullmatch(r"\d{6,20}", pid):
        return None
    preview, orig = _pick_image_url(obj.get("images"))
    if not preview:
        for key in ("image_large_url", "image_medium_url", "image_square_url"):
            if obj.get(key):
                preview = str(obj[key])
                orig = preview
                break
    if not preview or "pinimg.com" not in preview:
        return None
    title = (
        obj.get("title")
        or obj.get("grid_title")
        or obj.get("gridTitle")
        or obj.get("description")
        or ""
    )
    title = re.sub(r"\s+", " ", str(title)).strip()[:80]

    # Официальная метка Pinterest ИЛИ текстовые маркеры скрытого ИИ / retail junk
    is_ai = _ai_flag_from_obj(obj)
    if is_ai is not True and _text_looks_like_ai(obj):
        is_ai = True
    if is_ai is not True and title_looks_like_junk(_pin_text_blob(obj)):
        is_ai = True

    return PinMeta(
        pin_id=pid,
        title=title or f"pin {pid}",
        image_url=preview,
        orig_url=orig or preview,
        is_ai=is_ai,
    )


def _dedupe_pins(items: list[PinMeta], limit: int = MAX_SEARCH_PINS) -> list[PinMeta]:
    seen: set[str] = set()
    out: list[PinMeta] = []
    # PhotoVault blacklist — мгновенный отсев до download
    try:
        from core.photo_vault import get_photo_vault

        vault = get_photo_vault()
    except Exception:
        vault = None
    blocked_n = 0
    for p in items:
        # ЗАПРЕТ: зомби img000 / pin_img000 (ненастоящий id, часто градиент-мусор)
        if is_fake_stub_pin_id(p.pin_id):
            continue
        if not re.fullmatch(r"\d{6,20}", str(p.pin_id or "")):
            continue
        if vault is not None and vault.is_blacklisted(p.pin_id):
            blocked_n += 1
            continue
        if p.pin_id in seen:
            continue
        seen.add(p.pin_id)
        out.append(p)
        if len(out) >= limit:
            break
    if blocked_n:
        print(f"[vault] blacklist drop ×{blocked_n} (pre-download)")
    return out


def _extract_from_pws_html(html: str) -> list[PinMeta]:
    html = _normalize_html(html)
    items: list[PinMeta] = []
    for sid in ("__PWS_DATA__", "__PWS_INITIAL_PROPS__"):
        m = re.search(
            rf'<script[^>]+id=["\']{re.escape(sid)}["\'][^>]*>(.*?)</script>',
            html,
            re.I | re.S,
        )
        if not m:
            continue
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        raw: list[dict[str, Any]] = []
        _walk_collect_pins(data, raw)
        for obj in raw:
            pin = _pin_from_obj(obj)
            if pin:
                items.append(pin)
    # НЕ подмешиваем URL-only «img000» без настоящего pin_id —
    # это источник неоновых градиентов-зомби при пустом API.
    return _dedupe_pins(items)


def _to_736x(url: str) -> str:
    if "/originals/" in url:
        return url.replace("/originals/", "/736x/")
    if "/736x/" in url:
        return url
    # generic size tier -> 736x
    return re.sub(r"/(\d+x)/", "/736x/", url, count=1)


def _extract_og_image(html: str) -> str | None:
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I)
        if m and "pinimg.com" in m.group(1):
            return m.group(1)
    return None


def _extract_image_from_pws(html: str) -> str | None:
    m = re.search(
        r'<script[^>]+id=["\']__PWS_DATA__["\'][^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    )
    if not m:
        m = re.search(
            r'<script[^>]+id=["\']__PWS_INITIAL_PROPS__["\'][^>]*>(.*?)</script>',
            html,
            re.I | re.S,
        )
    if not m:
        return None
    raw = m.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        found = re.findall(
            r"https://i\.pinimg\.com/(?:originals|\d+x)/[0-9a-f/]+\.(?:jpg|jpeg|png|webp)",
            raw,
            re.I,
        )
        return found[0] if found else None

    candidates: list[str] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for v in obj.values():
                if isinstance(v, str) and "i.pinimg.com" in v:
                    candidates.append(v)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    if not candidates:
        return None

    def score(u: str) -> tuple[int, int]:
        path = urlparse(u).path
        tier = 0
        if "/originals/" in path:
            tier = 3
        elif "/736x/" in path:
            tier = 2
        elif "/474x/" in path:
            tier = 1
        return (tier, len(u))

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def dedupe_carousel_pools(
    pools: list[list[CandidateImage]],
    *,
    selected_index: int = 0,
) -> list[list[CandidateImage]]:
    """
    Уникальные pin_id на позиции selected_index между слайдами карусели.
    Если #1 занят другим слайдом — двигаем следующий свободный alt вперёд.
    Дубль на selected ЗАПРЕЩЁН: если свободного pin нет — пустой пул
    (caller обязан guarantee/refill), а не повтор того же кадра.
    """
    if not pools:
        return pools
    claimed: set[str] = set()
    out: list[list[CandidateImage]] = []
    for pool in pools:
        if not pool:
            out.append([])
            continue
        ordered = list(pool)
        sel = max(0, min(int(selected_index), len(ordered) - 1))
        ranked = [ordered[sel]] + [
            c for i, c in enumerate(ordered) if i != sel
        ]
        pick_i = None
        for i, c in enumerate(ranked):
            pid = str(c.pin_id or "")
            if pid and pid in claimed:
                continue
            pick_i = i
            if pid:
                claimed.add(pid)
            break
        if pick_i is None:
            print(
                f"[WARNING] dedupe: нет свободного pin "
                f"(все заняты другими слайдами) — пустой пул, "
                f"не оставляю дубль {ranked[0].pin_id}"
            )
            out.append([])
            continue
        chosen = ranked[pick_i]
        rest = [c for i, c in enumerate(ranked) if i != pick_i]
        rest_unique = []
        for c in rest:
            pid = str(c.pin_id or "")
            if pid and pid in claimed:
                continue
            rest_unique.append(c)
            if pid:
                claimed.add(pid)
        new_pool = [chosen] + rest_unique
        if len(new_pool) < min(2, len(ordered)):
            for c in ranked:
                if c is chosen:
                    continue
                if c not in new_pool:
                    new_pool.append(c)
        out.append(new_pool)
    return out


def dedupe_selected_across_slides(
    pools: list[list[CandidateImage]],
) -> list[list[CandidateImage]]:
    """
    После reorder (color harmony): гарантировать уникальный pin на [0]
    между слайдами. Дубликаты на selected — hard fail → swap с alts.
    """
    return dedupe_carousel_pools(pools, selected_index=0)


# ---------------------------------------------------------------------------
# Клиент
# ---------------------------------------------------------------------------

class PinterestHarvester:
    def __init__(self, on_status: ProgressCb | None = None) -> None:
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                REQUEST_TIMEOUT,
                connect=min(CONNECT_TIMEOUT, REQUEST_TIMEOUT),
                read=REQUEST_TIMEOUT,
                write=REQUEST_TIMEOUT,
                pool=REQUEST_TIMEOUT,
            ),
            follow_redirects=True,
            transport=httpx.HTTPTransport(retries=MAX_NETWORK_RETRIES),
            headers=HTML_HEADERS,
        )
        self._csrf = ""
        self._on_status = on_status or (lambda _s: None)
        # Только pin_id ФИНАЛЬНЫХ слайдов (selected). Альтернативы НЕ баним.
        self._used_pin_ids: set[str] = set()
        # Сколько раз pin уже ушёл в финальный рендер в этом запуске
        self._pin_use_counts: dict[str, int] = {}
        self._io_lock = threading.Lock()  # csrf/cookies
        self._used_lock = threading.Lock()
        self._timing_lock = threading.Lock()
        # Один поиск за раз — иначе 6× SSL handshake -> raw=0
        self._search_lock = threading.Lock()
        self._warm_lock = threading.Lock()
        self._last_warm_ts = 0.0
        self.timing_pinterest_sec = 0.0
        self.timing_siglip_sec = 0.0

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def reset_used(self) -> None:
        with self._used_lock:
            self._used_pin_ids.clear()
            self._pin_use_counts.clear()

    def seed_used(self, pin_ids: Iterable[str]) -> None:
        """
        Засеять exclude финалами предыдущих каруселей (без +count).
        Альтернативы / сырой пул сюда НЕ передавать.
        """
        extra = {str(p) for p in pin_ids if p}
        if not extra:
            return
        with self._used_lock:
            self._used_pin_ids |= extra
            for pid in extra:
                self._pin_use_counts.setdefault(pid, 1)

    def mark_used(self, pin_ids: Iterable[str]) -> None:
        """Пометить ФИНАЛЬНО выбранные pin_id (+1 к счётчику повторов)."""
        extra = [str(p) for p in pin_ids if p]
        if not extra:
            return
        with self._used_lock:
            for pid in extra:
                self._used_pin_ids.add(pid)
                self._pin_use_counts[pid] = (
                    int(self._pin_use_counts.get(pid, 0)) + 1
                )

    def pin_use_count(self, pin_id: str) -> int:
        with self._used_lock:
            return int(self._pin_use_counts.get(str(pin_id or ""), 0))

    def _select_pins_avoiding_used(
        self,
        pins: list[PinMeta],
        *,
        exclude: set[str],
        ignore_used: bool,
        want: int = 4,
    ) -> tuple[list[PinMeta], int, int]:
        """
        Свежие (не в _used_pin_ids) предпочтительны.

        При полном истощении уникальных pin в длинном батче (все eligible
        уже в used) — soft-reuse кандидатов с минимальным pin_use_counts,
        с флагом reuse_after_exhaustion=True (для meta.json).

        Returns: (selected, raw_count, dups_count)
        """
        raw_count = len(pins)
        eligible = [p for p in pins if p.pin_id not in exclude]
        if ignore_used:
            for p in eligible:
                p.reuse_after_exhaustion = False
            return eligible, raw_count, 0
        with self._used_lock:
            used = set(self._used_pin_ids)
            counts = dict(self._pin_use_counts)
        fresh = [p for p in eligible if p.pin_id not in used]
        dups_count = len(eligible) - len(fresh)
        if fresh:
            for p in fresh:
                p.reuse_after_exhaustion = False
            return fresh, raw_count, dups_count
        if not eligible:
            return [], raw_count, dups_count
        # Pin exhaustion safety: least-used among eligible (never empty list)
        n = max(1, int(want))
        reused = sorted(
            eligible,
            key=lambda p: (int(counts.get(p.pin_id, 0)), str(p.pin_id)),
        )[:n]
        for p in reused:
            p.reuse_after_exhaustion = True
        min_c = int(counts.get(reused[0].pin_id, 0)) if reused else 0
        print(
            f"[dedupe] PIN EXHAUSTION: soft-reuse least-used "
            f"x{len(reused)} (min_count={min_c}, used={len(used)}, "
            f"eligible={len(eligible)}) - reuse_after_exhaustion=true"
        )
        return reused, raw_count, dups_count

    def reset_timing(self) -> None:
        with self._timing_lock:
            self.timing_pinterest_sec = 0.0
            self.timing_siglip_sec = 0.0

    def _add_timing(self, *, pinterest: float = 0.0, siglip: float = 0.0) -> None:
        with self._timing_lock:
            self.timing_pinterest_sec += max(0.0, float(pinterest))
            self.timing_siglip_sec += max(0.0, float(siglip))

    def _status(self, msg: str) -> None:
        text = str(msg or "")
        # Windows cp1251 consoles choke on ↔ × — … etc.
        for a, b in (
            ("\u2194", "<->"),
            ("\u00d7", "x"),
            ("\u2192", "->"),
            ("\u2014", "-"),
            ("\u2013", "-"),
            ("\u2026", "..."),
            ("\u2212", "-"),
            ("\u00ab", "\""),
            ("\u00bb", "\""),
        ):
            text = text.replace(a, b)
        try:
            self._on_status(text)
        except UnicodeEncodeError:
            self._on_status(text.encode("ascii", "replace").decode("ascii"))
        self._on_status(msg)

    def warm(self) -> None:
        self._client.get("https://www.pinterest.com/", headers=HTML_HEADERS)
        with self._io_lock:
            self._csrf = self._client.cookies.get("csrftoken") or ""

    def warm_session(self, *, force: bool = False) -> bool:
        """
        Мягкий перезапуск сессии. Под lock + cooldown —
        6 параллельных warm убивают SSL handshake.
        """
        with self._warm_lock:
            now = time.perf_counter()
            if (
                not force
                and self._last_warm_ts > 0
                and (now - self._last_warm_ts) < WARM_COOLDOWN_SEC
            ):
                return False
            try:
                self.warm()
                self._last_warm_ts = time.perf_counter()
                print("[Pinterest] warm_session: cookies/csrf обновлены")
                return True
            except Exception as exc:
                print(f"[WARNING] warm_session fail: {exc}")
                # Пересоздать клиент после SSL timeout
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = httpx.Client(
                    timeout=httpx.Timeout(
                        REQUEST_TIMEOUT,
                        connect=min(CONNECT_TIMEOUT, REQUEST_TIMEOUT),
                        read=REQUEST_TIMEOUT,
                        write=REQUEST_TIMEOUT,
                        pool=REQUEST_TIMEOUT,
                    ),
                    follow_redirects=True,
                    transport=httpx.HTTPTransport(retries=MAX_NETWORK_RETRIES),
                    headers=HTML_HEADERS,
                )
                try:
                    self.warm()
                    self._last_warm_ts = time.perf_counter()
                    print("[Pinterest] warm_session: клиент пересоздан OK")
                    return True
                except Exception as exc2:
                    print(f"[WARNING] warm_session recreate fail: {exc2}")
                    return False

    def _api_headers(self, referer: str) -> dict[str, str]:
        h = dict(API_HEADERS_BASE)
        h["Referer"] = referer
        with self._io_lock:
            csrf = self._csrf
        if csrf:
            h["X-CSRFToken"] = csrf
        return h

    def search(self, query: str, *, finalize: bool = True) -> list[PinMeta]:
        raw_q = (query or "").strip()
        if not raw_q:
            return []
        q = finalize_photo_query(raw_q) if finalize else raw_q
        if not q:
            return []
        # Сериализуем HTML+API поиск (общий Client + Pinterest rate-limit)
        with self._search_lock:
            return self._search_unlocked(q)

    def _search_unlocked(self, q: str) -> list[PinMeta]:
        source = f"/search/pins/?q={quote_plus(q)}"
        page_url = f"https://www.pinterest.com{source}"
        t0 = time.perf_counter()

        try:
            page = self._client.get(page_url, headers=HTML_HEADERS)
        except httpx.HTTPError as exc:
            print(f"[Pinterest] search HTML fail «{q}»: {exc}")
            self._add_timing(pinterest=time.perf_counter() - t0)
            return []
        with self._io_lock:
            self._csrf = self._client.cookies.get("csrftoken") or self._csrf
        html_pins = _extract_from_pws_html(page.text)

        data = {
            "options": {
                "query": q,
                "scope": "pins",
                "page_size": min(MAX_SEARCH_PINS, 25),
                "bookmarks": [],
            },
            "context": {},
        }
        api_pins: list[PinMeta] = []
        try:
            resp = self._client.post(
                "https://www.pinterest.com/resource/BaseSearchResource/get/",
                headers=self._api_headers(page_url),
                data={
                    "source_url": source,
                    "data": json.dumps(data, separators=(",", ":")),
                },
            )
            if resp.status_code == 200 and resp.content[:1] == b"{":
                raw: list[dict[str, Any]] = []
                _walk_collect_pins(resp.json(), raw)
                for obj in raw:
                    pin = _pin_from_obj(obj)
                    if pin:
                        api_pins.append(pin)
            elif resp.status_code >= 400:
                print(
                    f"[Pinterest] search API HTTP {resp.status_code} «{q}»"
                )
        except httpx.HTTPError as exc:
            print(f"[Pinterest] search API fail «{q}»: {exc}")

        self._add_timing(pinterest=time.perf_counter() - t0)
        return _dedupe_pins(api_pins + html_pins)

    def check_ai(self, pin_id: str) -> bool:
        """True если GenAI по метке Pinterest или текстовым стоп-словам метаданных."""
        if not re.fullmatch(r"\d{6,20}", pin_id):
            return False
        source = f"/pin/{pin_id}/"
        data = {
            "options": {"id": pin_id, "field_set_key": "detailed_with_board"},
            "context": {},
        }
        # Отдельный клиент — filter_ai параллельный, без блокировки search
        try:
            with httpx.Client(
                timeout=httpx.Timeout(
                    REQUEST_TIMEOUT,
                    connect=min(CONNECT_TIMEOUT, REQUEST_TIMEOUT),
                ),
                follow_redirects=True,
                transport=httpx.HTTPTransport(retries=MAX_NETWORK_RETRIES),
            ) as client:
                # csrf из основного клиента (read-only cookies snapshot)
                with self._io_lock:
                    csrf = self._csrf
                    cookies = dict(self._client.cookies)
                for k, v in cookies.items():
                    client.cookies.set(k, v)
                headers = dict(API_HEADERS_BASE)
                headers["Referer"] = f"https://www.pinterest.com{source}"
                if csrf:
                    headers["X-CSRFToken"] = csrf
                resp = client.post(
                    "https://www.pinterest.com/resource/PinResource/get/",
                    headers=headers,
                    data={
                        "source_url": source,
                        "data": json.dumps(data, separators=(",", ":")),
                    },
                )
                if resp.status_code != 200 or resp.content[:1] != b"{":
                    return False
                pin = resp.json().get("resource_response", {}).get("data") or {}
                if isinstance(pin, dict):
                    if _ai_flag_from_obj(pin) is True:
                        return True
                    if _text_looks_like_ai(pin):
                        return True
                text = resp.text
                if re.search(r'"digital_media_source_type"\s*:\s*11\b', text):
                    return True
                if re.search(r'"digitalMediaSourceType"\s*:\s*11\b', text):
                    return True
                if re.search(r'"genAiTopics"\s*:\s*\[\s*\{', text):
                    return True
        except httpx.HTTPError:
            return False
        return False

    def filter_ai(self, pins: list[PinMeta]) -> tuple[list[PinMeta], int]:
        # Уже отсеянные текстовым фильтром / SSR-меткой не ходят в API
        pre_rejected = sum(1 for p in pins if p.is_ai is True)
        need = [p for p in pins if p.is_ai is None]
        # Жёсткий потолок API-проверок (сеть ≤5 с) — иначе batch убивается
        _AI_CHECK_CAP = 12
        if len(need) > _AI_CHECK_CAP:
            for p in need[_AI_CHECK_CAP:]:
                p.is_ai = False  # неизвестно -> пропускаем без API
            need = need[:_AI_CHECK_CAP]
        t0 = time.perf_counter()
        if need:
            self._status(
                f"Проверка ИИ-меток ({len(need)} пинов"
                f"{f', текст-фильтр уже отсёк {pre_rejected}' if pre_rejected else ''})…"
            )

            def check_one(p: PinMeta) -> tuple[str, bool]:
                return p.pin_id, self.check_ai(p.pin_id)

            with ThreadPoolExecutor(max_workers=min(AI_CHECK_WORKERS, len(need))) as pool:
                futures = {pool.submit(check_one, p): p for p in need}
                for fut in as_completed(futures):
                    try:
                        pid, is_ai = fut.result()
                    except Exception:
                        continue
                    for p in pins:
                        if p.pin_id == pid:
                            p.is_ai = is_ai
                            break

        kept: list[PinMeta] = []
        rejected = 0
        for p in pins:
            if p.is_ai is True or title_looks_like_junk(p.title):
                rejected += 1
                continue
            p.is_ai = False
            kept.append(p)
        self._add_timing(pinterest=time.perf_counter() - t0)
        return kept, rejected

    def resurrect_pin_url(self, pin_id: str) -> str | None:
        """Воскрешение CDN URL по pin_id (og:image / __PWS_DATA__)."""
        if not re.fullmatch(r"\d{6,20}", pin_id):
            return None
        url = f"https://www.pinterest.com/pin/{pin_id}/"
        try:
            resp = self._client.get(url, headers=HTML_HEADERS)
        except httpx.HTTPError:
            return None
        final = str(resp.url).lower()
        if "/login" in final:
            return None
        html = _normalize_html(resp.text)
        low = html.lower()
        if "just a moment" in low or (
            "cloudflare" in low and "challenge" in low
        ):
            return None
        return _extract_og_image(html) or _extract_image_from_pws(html)

    async def _fetch_bytes(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> tuple[int | None, bytes | None]:
        try:
            resp = await client.get(url, headers=CDN_HEADERS)
            if resp.status_code == 200 and resp.content:
                return resp.status_code, resp.content
            return resp.status_code, None
        except httpx.HTTPError:
            return None, None

    async def _download_one(
        self,
        client: httpx.AsyncClient,
        sem: asyncio.Semaphore,
        pin: PinMeta,
        query: str,
    ) -> CandidateImage | None:
        async with sem:
            url = pin.orig_url or pin.image_url
            status, body = await self._fetch_bytes(client, url)
            via_fallback = False

            if body is None and status in {404, 403, None}:
                alt = _to_736x(url)
                if alt != url:
                    status2, body2 = await self._fetch_bytes(client, alt)
                    if body2 is not None:
                        body = body2
                        url = alt
                        via_fallback = True
                        status = status2

            if body is None and re.fullmatch(r"\d{6,20}", pin.pin_id):
                # воскрешение по pin_id (sync в executor, чтобы не блокировать loop сильно)
                resurrected = await asyncio.to_thread(
                    self.resurrect_pin_url, pin.pin_id
                )
                if resurrected:
                    status3, body3 = await self._fetch_bytes(client, resurrected)
                    if body3 is None and status3 in {404, 403, None}:
                        alt = _to_736x(resurrected)
                        if alt != resurrected:
                            _, body3 = await self._fetch_bytes(client, alt)
                            resurrected = alt
                            via_fallback = True
                    if body3 is not None:
                        body = body3
                        url = resurrected

            if not body:
                return None
            try:
                img = Image.open(io.BytesIO(body))
                img.load()
                img = img.convert("RGB")
            except Exception:
                return None
            if is_junk_candidate_image(img, pin.title, bytes_len=len(body)):
                return None
            return CandidateImage(
                pin_id=pin.pin_id,
                title=pin.title,
                source_url=url,
                query=query,
                image=img,
                via_fallback=via_fallback,
                bytes_len=len(body),
                reuse_after_exhaustion=bool(
                    getattr(pin, "reuse_after_exhaustion", False)
                ),
            )

    async def download_candidates(
        self,
        pins: list[PinMeta],
        query: str,
        limit: int = CANDIDATES_PER_SLIDE,
        *,
        concurrency: int | None = None,
    ) -> tuple[list[CandidateImage], HarvestProgress]:
        """
        Скачать ВЕСЬ пул пинов через asyncio.gather (без CDN-race).
        Ранжирование — только после полной загрузки, в judge_and_filter.
        `limit` оставлен для совместимости API и не режет скачивание раньше срока.
        """
        del limit  # полный пул; отсечение — после скоринга
        t0 = time.perf_counter()
        workers = max(1, int(concurrency or DOWNLOAD_CONCURRENCY))
        sem = asyncio.Semaphore(workers)
        timeout = httpx.Timeout(CDN_TIMEOUT)
        limits = httpx.Limits(
            max_connections=workers,
            max_keepalive_connections=workers,
        )
        out: list[CandidateImage] = []
        bytes_total = 0

        async with httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            follow_redirects=True,
        ) as client:
            tasks = [
                asyncio.create_task(self._download_one(client, sem, pin, query))
                for pin in pins
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, BaseException) or res is None:
                    continue
                out.append(res)
                bytes_total += res.bytes_len

        elapsed = time.perf_counter() - t0
        self._add_timing(pinterest=elapsed)
        mb = bytes_total / (1024 * 1024)
        progress = HarvestProgress(
            stage="download",
            found=len(pins),
            downloaded=len(out),
            bytes_total=bytes_total,
            elapsed_sec=elapsed,
            speed_mbps=(mb / elapsed) if elapsed > 0 else 0.0,
        )
        return out, progress

    def _apply_text_relevance_gate(
        self,
        candidates: list[CandidateImage],
        slide_text: str,
        *,
        query: str = "",
        visual_scene: str = "",
    ) -> list[CandidateImage]:
        """
        SigLIP text↔image: max(scene_anchor, vibe_anchor) per image.
        Отбор победителя по SELECT_RELEVANCE_MIN — в judge_and_filter.
        """
        if not candidates:
            return []
        anchors = build_relevance_texts(
            slide_text, query, visual_scene=visual_scene
        )
        if (
            not (visual_scene or "").strip()
            and not (slide_text or "").strip()
            and not (query or "").strip()
        ):
            for cand in candidates:
                cand.text_relevance = 1.0
                cand.text_relevance_scored = False
            return candidates

        label = " | ".join(a[:36] for a in anchors)
        self._status(
            f"Смысл text↔image («{label}»): оценка {len(candidates)}…"
        )
        t0 = time.perf_counter()
        try:
            from core.taste_embedder import get_embedder

            emb = get_embedder()
            images = [c.image for c in candidates]
            best_scores = [0.0] * len(candidates)
            for anchor in anchors:
                scores = emb.compute_text_image_relevances(anchor, images)
                for i, score in enumerate(scores):
                    best_scores[i] = max(best_scores[i], float(score))
        except Exception as exc:
            self._add_timing(siglip=time.perf_counter() - t0)
            self._status(
                f"Смысл: сбой ({exc.__class__.__name__}) — baseline 0.5"
            )
            for cand in candidates:
                cand.text_relevance = 0.5
                cand.text_relevance_scored = False
            return candidates

        for cand, score in zip(candidates, best_scores):
            cand.text_relevance = float(score)
            cand.text_relevance_scored = True
        self._add_timing(siglip=time.perf_counter() - t0)
        best = max(c.text_relevance for c in candidates)
        low_n = sum(
            1 for c in candidates if c.text_relevance < SELECT_RELEVANCE_MIN
        )
        self._status(
            f"Смысл: scored {len(candidates)}, "
            f"best={best:.0%}, below_select_floor={low_n} "
            f"(<{int(round(SELECT_RELEVANCE_MIN * 100))}%)"
            + (f" · anchors={len(anchors)}" if len(anchors) > 1 else "")
        )
        return candidates

    def _score_harmony(
        self,
        candidates: list[CandidateImage],
        anchor_image: Image.Image | None,
    ) -> None:
        """Проставить harmony_score 0..100 к якорю (или 100 без якоря)."""
        if not candidates:
            return
        if anchor_image is None:
            for cand in candidates:
                cand.harmony_score = 100.0
            return
        try:
            from core.color_matcher import get_color_profile, get_harmony_score

            anchor = get_color_profile(anchor_image)
            for cand in candidates:
                cand.harmony_score = float(
                    get_harmony_score(anchor, get_color_profile(cand.image))
                )
        except Exception:
            for cand in candidates:
                cand.harmony_score = 100.0

    def _apply_ugc_gate(self, candidates: list[CandidateImage]) -> list[CandidateImage]:
        """UGC-скоры для всех кандидатов (без hard-wipe пула)."""
        if not candidates:
            return []
        from core.ugc_filter import get_ugc_filter

        self._status(f"UGC-фильтр (локально): оценка {len(candidates)}…")
        t0 = time.perf_counter()
        try:
            filt = get_ugc_filter()
            scores = filt.get_ugc_scores([c.image for c in candidates])
        except Exception as exc:
            self._add_timing(siglip=time.perf_counter() - t0)
            self._status(
                f"UGC: сбой ({exc.__class__.__name__}) — baseline 0.5"
            )
            for cand in candidates:
                cand.ugc_score = 0.5
                cand.ugc_scored = False
            return candidates

        for cand, score in zip(candidates, scores):
            cand.ugc_score = float(score)
            cand.ugc_scored = True
        self._add_timing(siglip=time.perf_counter() - t0)
        best = max(c.ugc_score for c in candidates)
        self._status(f"UGC: scored {len(candidates)}, лучший {best:.0%}")
        return candidates

    def _apply_taste_gate(self, candidates: list[CandidateImage]) -> list[CandidateImage]:
        """Taste-скоры для всех кандидатов (без hard-wipe пула)."""
        if not candidates:
            return []
        if not TASTE_ENABLED:
            for cand in candidates:
                cand.taste_score = 0.5
                cand.taste_scored = False
            self._status("Вкус: DISABLED (experiment)")
            return candidates
        from core.taste_classifier import get_taste_classifier

        clf = get_taste_classifier()
        if not clf.is_trained:
            for cand in candidates:
                cand.taste_score = 0.5
                cand.taste_scored = False
            return candidates

        self._status(f"Вкус (локально): оценка {len(candidates)} кандидатов…")
        t0 = time.perf_counter()
        try:
            scores = clf.predict_taste_scores([c.image for c in candidates])
        except Exception as exc:
            self._add_timing(siglip=time.perf_counter() - t0)
            self._status(
                f"Вкус: сбой ({exc.__class__.__name__}) — baseline 0.5"
            )
            for cand in candidates:
                cand.taste_score = 0.5
                cand.taste_scored = False
            return candidates

        for cand, score in zip(candidates, scores):
            cand.taste_score = float(score)
            cand.taste_scored = True
            cand.relevance_score = round(cand.taste_score * 10.0, 2)
        self._add_timing(siglip=time.perf_counter() - t0)
        best = max(c.taste_score for c in candidates)
        self._status(f"Вкус: scored {len(candidates)}, лучший {best:.0%}")
        return candidates

    def _apply_borderline_vision(
        self,
        candidates: list[CandidateImage],
        *,
        visual_scene: str = "",
        query: str = "",
        slide_text: str = "",
    ) -> int:
        """
        Soft/vibe UGC band cannot auto-pass: moondream KEEP required.
        Returns number of borderline frames dropped.
        """
        if not BORDERLINE_VISION_ENABLED or not candidates:
            return 0
        borderline = [
            c
            for c in candidates
            if getattr(c, "is_relevant", False)
            and ugc_is_borderline(
                float(getattr(c, "ugc_score", 0) or 0),
                float(getattr(c, "text_relevance", 0) or 0),
                visual_scene=visual_scene,
                query=query,
                slide_text=slide_text,
            )
        ]
        if not borderline:
            return 0
        borderline.sort(
            key=lambda c: float(getattr(c, "combined_score", 0) or 0),
            reverse=True,
        )
        to_check = borderline[: max(1, BORDERLINE_VISION_MAX)]
        # Unchecked extras beyond cap: fail-closed DROP (don't auto-pass soft)
        dropped = 0
        for c in borderline[len(to_check) :]:
            c.is_relevant = False
            c.relevance_reason = "borderline_vision_cap DROP"
            dropped += 1

        self._status(
            f"Взгляд (пограничный UGC): {len(to_check)} кадров через vision…"
        )
        try:
            from core.local_gate import vision_borderline_is_live
        except Exception as exc:
            print(f"[VISION] import fail: {exc}")
            if BORDERLINE_VISION_FAIL_CLOSED:
                for c in to_check:
                    c.is_relevant = False
                    c.relevance_reason = "borderline_vision offline DROP"
                    dropped += 1
            return dropped

        for c in to_check:
            result = vision_borderline_is_live(
                c.image,
                scene=visual_scene or query,
                slide_text=slide_text,
            )
            pid = str(getattr(c, "pin_id", "") or "")[-8:]
            if not result.get("ok"):
                if BORDERLINE_VISION_FAIL_CLOSED:
                    c.is_relevant = False
                    c.relevance_reason = (
                        f"borderline_vision unavailable DROP "
                        f"({result.get('why')})"
                    )
                    dropped += 1
                    print(
                        f"  [VISION] {pid} ugc={c.ugc_score:.0%} "
                        f"OFFLINE→DROP",
                        flush=True,
                    )
                else:
                    c.relevance_reason = "single_pass_ugc_soft (vision skip)"
                continue
            keep = bool(result.get("keep"))
            why = str(result.get("why") or "")[:60]
            score = float(result.get("score") or 0)
            if keep:
                c.is_relevant = True
                c.relevance_reason = f"vision_keep {score:.0f}: {why}"
                c.selection_mode = "borderline_vision"
                print(
                    f"  [VISION] {pid} ugc={c.ugc_score:.0%} KEEP "
                    f"{score:.0f} · {why}",
                    flush=True,
                )
            else:
                c.is_relevant = False
                c.relevance_reason = f"vision_drop {score:.0f}: {why}"
                dropped += 1
                print(
                    f"  [VISION] {pid} ugc={c.ugc_score:.0%} DROP "
                    f"{score:.0f} · {why}",
                    flush=True,
                )
        return dropped

    async def judge_and_filter(
        self,
        candidates: list[CandidateImage],
        slide_text: str = "",
        *,
        min_score: int = 6,
        anchor_image: Image.Image | None = None,
        query: str = "",
        visual_scene: str = "",
        slide_index: int = 0,
        carousel_gender: str | None = None,
        character_dna: dict[str, str] | None = None,
    ) -> list[CandidateImage]:
        """
        Single-pass scoring:
        1) junk (обои/виджеты/3D);
        2) attribute DNA + body: no frontal faces + gender lock;
        3) UGC/Taste/Rel scores; POV+full-body fashion -> ugc×0.75;
        4) final = rel×0.40 + taste×0.35 + ugc×0.25;
        5) soft gate floors -> вне топа.
        """
        del min_score
        pre: list[CandidateImage] = []
        junk_n = 0
        for c in candidates:
            if is_junk_candidate_image(c.image, c.title):
                junk_n += 1
                c.relevance_score = 0.0
                c.is_relevant = False
                c.relevance_reason = "junk wallpaper/gradient"
                c.taste_score = 0.0
                c.ugc_score = 0.0
                c.text_relevance = 0.0
                continue
            pre.append(c)
        if junk_n:
            self._status(f"Анти-мусор: отброшено {junk_n} обоев/градиентов/виджетов")
        if not pre:
            return []

        # Attribute DNA + gender + no faces before SigLIP soft gates
        pre = _filter_consistency_gates(
            pre,
            slide_index=slide_index,
            carousel_gender=carousel_gender,
            character_dna=character_dna,
            query=query,
        )
        if not pre:
            self._status(
                f"Consistency: 0 left after attr/gender/face gates "
                f"(slide {slide_index + 1})"
            )
            return []

        pre = self._apply_text_relevance_gate(
            pre, slide_text, query=query, visual_scene=visual_scene
        )
        pre = self._apply_ugc_gate(pre)
        pre = self._apply_taste_gate(pre)
        pov_pen = apply_pov_fashion_ugc_penalty(pre, query)
        if pov_pen:
            self._status(
                f"POV fashion-penalty: −25% UGC ×{pov_pen} (full-body model)"
            )
        self._score_harmony(pre, anchor_image)

        ugc_drop = 0
        taste_drop = 0
        rel_drop = 0
        ugc_soft_n = 0
        for cand in pre:
            taste_v = (
                float(cand.taste_score)
                if getattr(cand, "taste_scored", False)
                else None
            )
            cand.combined_score = candidate_final_score(
                float(getattr(cand, "text_relevance", 0.5) or 0.5),
                float(getattr(cand, "ugc_score", 0.5) or 0.5),
                float(getattr(cand, "harmony_score", 100.0) or 100.0),
                taste=taste_v,
            )
            rel_v = float(cand.text_relevance)
            ugc_v = float(cand.ugc_score)
            ugc_ok = ugc_eligible(
                ugc_v,
                rel_v,
                visual_scene=visual_scene,
                query=query,
                slide_text=slide_text,
            )
            taste_ok = float(cand.taste_score) >= TASTE_HARD_FLOOR
            rel_ok = rel_v >= SELECT_RELEVANCE_MIN
            if (
                ugc_ok
                and ugc_v < UGC_HARD_FLOOR
                and rel_v >= UGC_SOFT_REL_MIN
            ):
                ugc_soft_n += 1
            if not ugc_ok:
                ugc_drop += 1
                cand.is_relevant = False
                cand.relevance_reason = (
                    f"ugc < {UGC_HARD_FLOOR:.2f} (gloss/pro)"
                )
            elif not taste_ok:
                taste_drop += 1
                cand.is_relevant = False
                cand.relevance_reason = (
                    f"taste < {TASTE_HARD_FLOOR:.2f} (AI/staged)"
                )
            elif not rel_ok:
                rel_drop += 1
                cand.is_relevant = False
                cand.relevance_reason = (
                    f"rel < {SELECT_RELEVANCE_MIN:.2f} (offtopic)"
                )
            else:
                cand.is_relevant = True
                cand.relevance_reason = (
                    "single_pass_ugc_soft"
                    if ugc_v < UGC_HARD_FLOOR
                    else "single_pass"
                )

        vision_drop = self._apply_borderline_vision(
            pre,
            visual_scene=visual_scene,
            query=query,
            slide_text=slide_text,
        )

        if ugc_drop or taste_drop or rel_drop or ugc_soft_n or vision_drop:
            self._status(
                f"Санитария: ugc<{int(round(UGC_HARD_FLOOR * 100))}%×{ugc_drop}, "
                f"taste<{int(round(TASTE_HARD_FLOOR * 100))}%×{taste_drop}, "
                f"rel<{int(round(SELECT_RELEVANCE_MIN * 100))}%×{rel_drop}"
                + (
                    f", ugc_soft×{ugc_soft_n}"
                    if ugc_soft_n
                    else ""
                )
                + (
                    f", vision_drop×{vision_drop}"
                    if vision_drop
                    else ""
                )
            )

        eligible = [
            c
            for c in pre
            if ugc_eligible(
                float(c.ugc_score),
                float(c.text_relevance),
                visual_scene=visual_scene,
                query=query,
                slide_text=slide_text,
            )
            and float(c.taste_score) >= TASTE_HARD_FLOOR
            and float(c.text_relevance) >= SELECT_RELEVANCE_MIN
            and bool(getattr(c, "is_relevant", False))
        ]
        if not eligible:
            # Soft-rel: only when contract allows quality surrender
            if SOFT_REL_ENABLED:
                soft = [
                    c
                    for c in pre
                    if ugc_eligible(
                        float(c.ugc_score),
                        float(c.text_relevance),
                        visual_scene=visual_scene,
                        query=query,
                        slide_text=slide_text,
                    )
                    and float(c.taste_score) >= TASTE_HARD_FLOOR
                    and float(c.text_relevance) >= SOFT_REL_FLOOR
                    and bool(getattr(c, "is_relevant", False))
                ]
                if soft:
                    soft.sort(key=lambda c: c.combined_score, reverse=True)
                    for c in soft:
                        c.is_relevant = True
                        c.relevance_reason = "soft_rel (ugc+taste ok)"
                        c.selection_mode = "soft_rel_fallback"
                    self._status(
                        f"Ранг: soft-rel fallback {len(soft)} "
                        f"(ugc≥{UGC_HARD_FLOOR:.0%} · rel soft) "
                        f"best={soft[0].combined_score:.0%}"
                    )
                    eligible = soft
            if not eligible:
                self._status(
                    f"Ранг: 0 selectable "
                    f"(ugc≥{UGC_HARD_FLOOR:.0%} · taste≥{TASTE_HARD_FLOOR:.0%} · "
                    f"rel≥{SELECT_RELEVANCE_MIN:.0%}"
                    f"{'' if SOFT_REL_ENABLED else ' · STRICT contract'}) "
                    f"из {len(pre)}"
                )
                return []

        eligible.sort(key=lambda c: c.combined_score, reverse=True)
        winner = eligible[0]
        if "vision_keep" in (winner.relevance_reason or ""):
            winner.selection_mode = "borderline_vision"
        else:
            winner.selection_mode = "single_pass_argmax"
        kept = [winner] + eligible[1:]
        self._status(
            f"Ранг: top final={winner.combined_score:.0%} "
            f"(UGC {winner.ugc_score:.0%} · вкус {winner.taste_score:.0%} · "
            f"смысл {winner.text_relevance:.0%}) "
            f"[{winner.selection_mode} · pool={len(kept)}/{len(pre)}]"
        )
        return kept

    async def _download_and_judge(
        self,
        pins: list[PinMeta],
        query: str,
        limit: int,
        slide_text: str,
        *,
        concurrency: int | None = None,
        fetch_limit: int | None = None,
        anchor_image: Image.Image | None = None,
        apply_score: bool = True,
        visual_scene: str = "",
        slide_index: int = 0,
        carousel_gender: str | None = None,
        character_dna: dict[str, str] | None = None,
    ) -> tuple[list[CandidateImage], HarvestProgress]:
        fetch = max(limit, int(fetch_limit or limit), 3)
        pool = pins[:fetch]
        # Полный gather всего пула — без early-exit по «кто быстрее».
        cands, dl_prog = await self.download_candidates(
            pool, query, limit=fetch, concurrency=concurrency
        )
        if apply_score:
            cands = await self.judge_and_filter(
                cands,
                slide_text=slide_text,
                anchor_image=anchor_image,
                query=query,
                visual_scene=visual_scene,
                slide_index=slide_index,
                carousel_gender=carousel_gender,
                character_dna=character_dna,
            )
            cands = cands[: max(limit, 1)]
        dl_prog.downloaded = len(cands)
        return cands, dl_prog

    def score_candidates(
        self,
        candidates: list[CandidateImage],
        slide_text: str = "",
        *,
        query: str = "",
        limit: int = CANDIDATES_PER_SLIDE,
        anchor_image: Image.Image | None = None,
        visual_scene: str = "",
        slide_index: int = 0,
        carousel_gender: str | None = None,
        character_dna: dict[str, str] | None = None,
    ) -> list[CandidateImage]:
        """SigLIP UGC + Relevance + Taste (sync wrapper, single-pass)."""
        if not candidates:
            return []
        # Зомби img000 / градиенты — никогда не в топ
        candidates = [
            c
            for c in candidates
            if not is_fake_stub_pin_id(getattr(c, "pin_id", ""))
        ]
        if not candidates:
            return []
        kept = asyncio.run(
            self.judge_and_filter(
                candidates,
                slide_text=slide_text,
                anchor_image=anchor_image,
                query=query,
                visual_scene=visual_scene,
                slide_index=slide_index,
                carousel_gender=carousel_gender,
                character_dna=character_dna,
            )
        )
        return kept[: max(limit, 1)]

    def rank_pool_emergency(
        self,
        candidates: list[CandidateImage],
        slide_text: str = "",
        *,
        query: str = "",
        limit: int = 1,
        anchor_image: Image.Image | None = None,
        visual_scene: str = "",
    ) -> list[CandidateImage]:
        """
        Аварийный ранжир: вкус < TASTE_HARD_FLOOR (0.35) — DROP ALWAYS.
        Без локальных заглушек. Без ослабления пола вкуса.
        """
        if not candidates:
            return []
        # Сразу выкинуть зомби img000 и junk-градиенты
        pre = [
            c
            for c in candidates
            if not is_fake_stub_pin_id(c.pin_id)
            and not is_junk_candidate_image(c.image, c.title)
        ]
        if not pre:
            return []

        # Проставляем скоры (гейты могут обнулить список — игнорируем return)
        try:
            self._apply_text_relevance_gate(
                list(pre),
                slide_text,
                query=query,
                visual_scene=visual_scene,
            )
        except Exception:
            for c in pre:
                c.text_relevance = 0.5
                c.text_relevance_scored = False
        try:
            from core.ugc_filter import get_ugc_filter

            scores = get_ugc_filter().get_ugc_scores([c.image for c in pre])
            for c, s in zip(pre, scores):
                c.ugc_score = float(s)
                c.ugc_scored = True
        except Exception:
            for c in pre:
                c.ugc_score = 0.5
                c.ugc_scored = False
        try:
            from core.taste_classifier import get_taste_classifier

            if not TASTE_ENABLED:
                for c in pre:
                    c.taste_score = 0.5
                    c.taste_scored = False
            else:
                clf = get_taste_classifier()
                if clf.is_trained:
                    scores = clf.predict_taste_scores([c.image for c in pre])
                    for c, s in zip(pre, scores):
                        c.taste_score = float(s)
                        c.taste_scored = True
                else:
                    for c in pre:
                        c.taste_score = 0.5
                        c.taste_scored = False
        except Exception:
            for c in pre:
                c.taste_score = 0.5
                c.taste_scored = False

        apply_pov_fashion_ugc_penalty(pre, query)
        self._score_harmony(pre, anchor_image)

        # HARD: вкус < 0.35 — никогда не проходит (даже emergency)
        taste_ok = [
            c
            for c in pre
            if float(getattr(c, "taste_score", 0.0) or 0.0) >= EMERGENCY_TASTE_FLOOR
        ]
        dropped_taste = len(pre) - len(taste_ok)
        if dropped_taste:
            print(
                f"[WARNING] emergency: DROP taste<{EMERGENCY_TASTE_FLOOR:.0%} "
                f"×{dropped_taste} (в т.ч. зомби-градиенты)"
            )
        if not taste_ok:
            print(
                f"[WARNING] emergency-keep: 0 кадров с "
                f"taste≥{EMERGENCY_TASTE_FLOOR:.0%} — пусто (без локальных stub)"
            )
            return []

        for cand in taste_ok:
            taste_v = (
                float(cand.taste_score)
                if getattr(cand, "taste_scored", False)
                else None
            )
            cand.combined_score = candidate_final_score(
                float(getattr(cand, "text_relevance", 0.5) or 0.5),
                float(getattr(cand, "ugc_score", 0.5) or 0.5),
                float(getattr(cand, "harmony_score", 100.0) or 100.0),
                taste=taste_v,
            )
            cand.is_relevant = True

        usable = [
            c
            for c in taste_ok
            if float(getattr(c, "text_relevance", 0.0) or 0.0) >= EMERGENCY_REL_FLOOR
        ]
        pool_for_pick = usable if usable else taste_ok

        # Soft-band emergency keeps also need vision KEEP
        for c in pool_for_pick:
            c.is_relevant = True
        self._apply_borderline_vision(
            pool_for_pick,
            visual_scene=visual_scene,
            query=query,
            slide_text=slide_text,
        )

        guarded = [
            c
            for c in pool_for_pick
            if ugc_eligible(
                float(c.ugc_score),
                float(getattr(c, "text_relevance", 0.0) or 0.0),
                visual_scene=visual_scene,
                query=query,
                slide_text=slide_text,
            )
            and float(c.taste_score) >= EMERGENCY_TASTE_FLOOR
            and float(getattr(c, "text_relevance", 0.0) or 0.0)
            >= EMERGENCY_REL_FLOOR
            and bool(getattr(c, "is_relevant", False))
        ]
        if guarded:
            guarded.sort(key=lambda c: c.combined_score, reverse=True)
            for c in guarded:
                if "vision_keep" in (c.relevance_reason or ""):
                    c.selection_mode = "emergency_borderline_vision"
                else:
                    c.relevance_reason = "emergency keep (gates empty)"
                    c.selection_mode = "emergency_guarded"
            top = guarded[: max(limit, 1)]
            print(
                f"[WARNING] emergency-keep (guarded): беру {len(top)} из "
                f"{len(guarded)}/{len(pool_for_pick)} "
                f"(best final={top[0].combined_score:.0%} · "
                f"ugc={top[0].ugc_score:.0%} · "
                f"taste={top[0].taste_score:.0%} · "
                f"rel={top[0].text_relevance:.0%})"
            )
            return top

        # Не роняем пол UGC ради «хоть чего-то» — лучше пусто → guarantee/refill
        print(
            f"[WARNING] emergency-keep: 0 кадров с "
            f"ugc≥{UGC_SOFT_FLOOR:.0%}(+rel≥{UGC_SOFT_REL_MIN:.0%})/"
            f"{EMERGENCY_UGC_FLOOR:.0%} · "
            f"taste≥{EMERGENCY_TASTE_FLOOR:.0%} "
            f"из {len(pool_for_pick)} — пусто (без сток-bypass)"
        )
        return []

    def guarantee_at_least_one(
        self,
        *,
        slide_text: str = "",
        slide_index: int = 0,
        preferred_query: str = "",
        limit: int = 1,
        topic: str = "",
        visual_scene: str = "",
        avoid_queries: set[str] | frozenset[str] | None = None,
        searches_budget: int | None = None,
        allow_soft: bool = False,
    ) -> tuple[list[CandidateImage], str]:
        """
        Vibe-rescue guarantee: NEW scene-angle queries only.
        Never re-search queries already tried (empty > stock; vibe > empty).

        allow_soft=True → completion-fill path (softer UGC floor, labeled).
        """
        slide_no = slide_index + 1
        soft_ok = bool(allow_soft) or GUARANTEE_SOFT_ENABLED
        soft_floor = (
            COMPLETION_UGC_FLOOR if allow_soft else GUARANTEE_UGC_FLOOR
        )
        avoid: set[str] = {
            (a or "").strip().lower()
            for a in (avoid_queries or ())
            if (a or "").strip()
        }
        pref = (preferred_query or "").strip()
        if pref:
            avoid.add(pref.lower())

        from core.query_forge import style_pivot_queries, vibe_rescue_queries

        budget = int(
            GUARANTEE_MAX_SEARCHES
            if searches_budget is None
            else max(0, searches_budget)
        )
        # Prop/scene angles first; reserve ~half budget for style pivot later
        prop_budget = max(1, budget - min(3, max(1, budget // 2))) if budget >= 2 else budget
        ordered = vibe_rescue_queries(
            slide_text=slide_text,
            visual_scene=visual_scene,
            topic=topic,
            avoid=avoid,
            max_n=max(prop_budget, 1),
            include_style_pivot=False,
        )
        # Only if vibe dry AND preferred never searched — one shot
        if not ordered and pref and pref.lower() not in {
            (a or "").strip().lower() for a in (avoid_queries or ()) if a
        }:
            ordered = [pref]

        tried: list[str] = []
        seen_q: set[str] = set(avoid)
        searches_left = budget
        vibe_tried: list[str] = []

        def _try_chain(
            queries: list[str],
            *,
            ignore_used: bool,
            max_n: int,
            allow_repeat: bool = False,
            selection_mode: str = "vibe_rescue",
            reason: str = "vibe_rescue guarantee",
            use_soft: bool = False,
            skip_finalize: bool = False,
        ) -> tuple[list[CandidateImage], str]:
            nonlocal searches_left
            local_seen: set[str] = set() if allow_repeat else set(seen_q)
            n_done = 0
            soft_this = bool(use_soft) and soft_ok
            for raw_q in queries:
                if searches_left <= 0 or n_done >= max_n:
                    break
                if skip_finalize:
                    q = re.sub(r"\s+", " ", (raw_q or "").strip())
                else:
                    q = (
                        finalize_photo_query(
                            raw_q, slide_index, slide_text=slide_text
                        )
                        or raw_q
                    )
                    q = re.sub(r"\s+", " ", q).strip()
                if not q or q.lower() in local_seen:
                    continue
                local_seen.add(q.lower())
                tried.append(q)
                if not ignore_used:
                    vibe_tried.append(q)
                searches_left -= 1
                n_done += 1
                mode = "ignore_used" if ignore_used else "fresh-only"
                tag = selection_mode
                print(
                    f"[GUARANTEE] Слайд {slide_no}: {tag} «{q}» "
                    f"({mode}, left={searches_left}"
                    f"{', soft' if soft_this else ''})…"
                )
                try:
                    cands, _prog = self.harvest_for_query(
                        q,
                        limit=max(limit, 3),
                        slide_text=slide_text,
                        slide_index=slide_index,
                        allow_broaden=False,
                        ignore_used=ignore_used,
                        apply_score=False,
                        _allow_emergency=True,
                        visual_scene=visual_scene,
                    )
                except Exception as exc:
                    print(f"[GUARANTEE] search fail «{q}»: {exc}")
                    continue
                if not cands:
                    continue
                cands = cands[:RESCUE_DOWNLOAD_CAP]
                # Score UGC/rel so soft floors can apply
                try:
                    self._apply_text_relevance_gate(
                        cands,
                        slide_text=slide_text,
                        query=q,
                        visual_scene=visual_scene,
                    )
                except Exception:
                    pass
                try:
                    from core.ugc_filter import get_ugc_filter

                    scores = get_ugc_filter().get_ugc_scores(
                        [c.image for c in cands]
                    )
                    for c, s in zip(cands, scores):
                        c.ugc_score = float(s)
                        c.ugc_scored = True
                except Exception:
                    for c in cands:
                        if not getattr(c, "ugc_scored", False):
                            c.ugc_score = 0.5
                            c.ugc_scored = True
                kept = self.rank_pool_emergency(
                    cands,
                    slide_text=slide_text,
                    query=q,
                    limit=max(limit, 1),
                    visual_scene=visual_scene,
                )
                if kept:
                    for c in kept:
                        c.relevance_reason = reason
                        c.selection_mode = selection_mode
                    return kept, q
                if not soft_this:
                    print(
                        f"[GUARANTEE] «{q}»: empty under STRICT "
                        f"(need ugc≥{EMERGENCY_UGC_FLOOR:.0%} · "
                        f"rel≥{EMERGENCY_REL_FLOOR:.0%})"
                    )
                    continue
                scored = [
                    c
                    for c in cands
                    if float(getattr(c, "ugc_score", 0) or 0) >= soft_floor
                    and float(getattr(c, "text_relevance", 0) or 0)
                    >= (COMPLETION_REL_FLOOR if allow_soft else EMERGENCY_REL_FLOOR)
                ]
                if not scored:
                    # last ditch: best ugc in downloaded pool
                    scored = sorted(
                        cands,
                        key=lambda c: float(getattr(c, "ugc_score", 0) or 0),
                        reverse=True,
                    )[: max(limit, 1)]
                    if scored and float(getattr(scored[0], "ugc_score", 0) or 0) < 0.22:
                        scored = []
                if scored:
                    scored.sort(
                        key=lambda c: float(getattr(c, "ugc_score", 0) or 0),
                        reverse=True,
                    )
                    top = scored[: max(limit, 1)]
                    for c in top:
                        c.relevance_reason = (
                            "completion_fill soft"
                            if allow_soft
                            else "guarantee soft ugc"
                        )
                        c.selection_mode = (
                            "completion_fill" if allow_soft else "guarantee_soft"
                        )
                    print(
                        f"[GUARANTEE] soft-keep ugc={top[0].ugc_score:.0%} "
                        f"(floor {soft_floor:.0%}) «{q}»"
                        f"{' [completion]' if allow_soft else ''}"
                    )
                    return top, q
                print(
                    f"[GUARANTEE] «{q}»: пуст даже soft "
                    f"(ugc<{soft_floor:.0%}) — next vibe"
                )
            if not allow_repeat:
                seen_q.update(local_seen)
            return [], ""

        if ordered and searches_left > 0:
            kept, win_q = _try_chain(
                ordered,
                ignore_used=False,
                max_n=prop_budget,
                use_soft=False,
            )
            if kept:
                return kept, win_q

        # Style pivot: radical eased queries (coffee/hands/window) with HARD floors
        # Better a strong on-brand mood frame than soft junk from the same prop.
        if searches_left > 0:
            pivot_avoid = set(seen_q) | {t.lower() for t in tried}
            pivots = style_pivot_queries(
                avoid=pivot_avoid,
                max_n=max(searches_left, 1),
                seed_text=f"{visual_scene} {slide_text} {topic}",
                slide_text=slide_text,
                visual_scene=visual_scene,
                topic=topic,
            )
            if pivots:
                print(
                    f"[GUARANTEE] Слайд {slide_no}: style-pivot "
                    f"({len(pivots)} eased queries, hard UGC)…"
                )
                kept, win_q = _try_chain(
                    pivots,
                    ignore_used=False,
                    max_n=searches_left,
                    selection_mode="style_pivot",
                    reason="style_pivot eased frame",
                    use_soft=False,
                    skip_finalize=True,
                )
                if kept:
                    return kept, win_q

        if searches_left > 0 and vibe_tried:
            print(
                f"[GUARANTEE] Слайд {slide_no}: fresh-only пусто — "
                f"1x ignore_used on best vibe"
            )
            kept, win_q = _try_chain(
                vibe_tried[:1],
                ignore_used=True,
                max_n=1,
                allow_repeat=True,
                use_soft=soft_ok,
            )
            if kept:
                return kept, win_q

        # Soft pass only after prop + style-pivot hard fails (completion path)
        if soft_ok and searches_left > 0:
            soft_qs = style_pivot_queries(
                avoid=set(seen_q) | {t.lower() for t in tried},
                max_n=max(searches_left, 1),
                seed_text=f"{visual_scene} {slide_text} {topic}",
                slide_text=slide_text,
                visual_scene=visual_scene,
                topic=topic,
            ) or vibe_tried[:1]
            if soft_qs:
                print(
                    f"[GUARANTEE] Слайд {slide_no}: soft after pivot miss…"
                )
                kept, win_q = _try_chain(
                    soft_qs,
                    ignore_used=True,
                    max_n=searches_left,
                    allow_repeat=True,
                    selection_mode="completion_fill",
                    reason="completion_fill soft after pivot",
                    use_soft=True,
                    skip_finalize=True,
                )
                if kept:
                    return kept, win_q

        if not ordered and not tried:
            print(
                f"[GUARANTEE] Слайд {slide_no}: no vibe queries left "
                f"(avoid={len(avoid)}) — empty slot"
            )
        else:
            print(
                f"[GUARANTEE] Слайд {slide_no}: FAILED — empty > stock "
                f"(tried vibe={tried})"
            )
        return [], ""

    def force_any_candidate(
        self,
        *,
        slide_text: str = "",
        slide_index: int = 0,
        topic: str = "",
        visual_scene: str = "",
        preferred_query: str = "",
        limit: int = 1,
    ) -> tuple[list[CandidateImage], str]:
        """
        Nuclear completion: MUST return a photo if Pinterest returns anything.
        ignore_used + broaden + pick best non-junk by ugc (no floor).
        """
        slide_no = slide_index + 1
        from core.query_forge import (
            _extract_props,
            _scene_nouns,
            style_pivot_queries,
            vibe_rescue_queries,
        )

        queries: list[str] = []
        # Prefer radical eased frames before re-searching the failed prop
        queries.extend(
            style_pivot_queries(
                avoid=set(),
                max_n=5,
                seed_text=f"{visual_scene} {slide_text} {topic}",
                slide_text=slide_text,
                visual_scene=visual_scene,
                topic=topic,
            )
        )
        if preferred_query:
            queries.append(preferred_query)
        queries.extend(
            vibe_rescue_queries(
                slide_text=slide_text,
                visual_scene=visual_scene,
                topic=topic,
                avoid=set(),
                max_n=3,
                include_style_pivot=False,
            )
        )
        for phrase in _extract_props(f"{visual_scene} {slide_text}", limit=3):
            queries.append(phrase)
        nouns = _scene_nouns(visual_scene or slide_text, limit=3)
        if nouns:
            queries.append(" ".join(nouns))
        # Broad domestic fallbacks tied to confession niche
        for fb in (
            "messy kitchen night candid",
            "snack counter phone photo",
            "open fridge night phone",
            "desk snacks evening",
            "city window night phone",
        ):
            queries.append(fb)

        seen: set[str] = set()
        best: CandidateImage | None = None
        best_q = ""
        for raw in queries:
            q = re.sub(r"\s+", " ", (raw or "").strip())
            if not q or q.lower() in seen:
                continue
            seen.add(q.lower())
            print(f"[NUCLEAR] Слайд {slide_no}: force «{q}»…")
            try:
                cands, _ = self.harvest_for_query(
                    q,
                    limit=max(limit, 4),
                    slide_text=slide_text,
                    slide_index=slide_index,
                    allow_broaden=True,
                    ignore_used=True,
                    apply_score=False,
                    _allow_emergency=True,
                    visual_scene=visual_scene,
                )
            except Exception as exc:
                print(f"[NUCLEAR] fail «{q}»: {exc}")
                continue
            if not cands:
                continue
            # score ugc
            try:
                from core.ugc_filter import get_ugc_filter

                scores = get_ugc_filter().get_ugc_scores([c.image for c in cands])
                for c, s in zip(cands, scores):
                    c.ugc_score = float(s)
                    c.ugc_scored = True
            except Exception:
                for c in cands:
                    c.ugc_score = 0.45
                    c.ugc_scored = True
            alive = [
                c
                for c in cands
                if not is_junk_candidate_image(c.image, getattr(c, "title", "") or "")
            ]
            pool = alive or list(cands)
            pool.sort(
                key=lambda c: float(getattr(c, "ugc_score", 0) or 0), reverse=True
            )
            top = pool[0]
            if best is None or float(top.ugc_score) > float(best.ugc_score):
                best = top
                best_q = q
            # Good enough — stop early
            if float(top.ugc_score) >= 0.40:
                break

        if best is None:
            print(f"[NUCLEAR] Слайд {slide_no}: Pinterest gave nothing usable")
            return [], ""
        best.selection_mode = "completion_nuclear"
        best.relevance_reason = "nuclear fill — slot must not be empty"
        print(
            f"[NUCLEAR] Слайд {slide_no}: keep ugc={best.ugc_score:.0%} «{best_q}»"
        )
        return [best], best_q

    def _taste_fetch_limit(self, limit: int) -> int:
        """Запас под отсев — умеренный (скорость batch)."""
        return max(limit * 2, limit + 4)

    def harvest_for_query(
        self,
        query: str,
        limit: int = CANDIDATES_PER_SLIDE,
        exclude_ids: set[str] | None = None,
        slide_text: str = "",
        *,
        slide_index: int | None = None,
        allow_broaden: bool = True,
        _broaden_depth: int = 0,
        anchor_image: Image.Image | None = None,
        ignore_used: bool = False,
        _ugc_candid_retry: bool = False,
        apply_score: bool = True,
        _allow_emergency: bool = True,
        visual_scene: str = "",
    ) -> tuple[list[CandidateImage], HarvestProgress]:
        """
        Полный цикл: Pinterest search -> ИИ-отсев -> полный CDN gather ->
        смысл/UGC/вкус. Без candid/finsta-retry (дают 0 и тормозят).
        При пустых гейтах — emergency из уже скачанного пула.
        """
        t0 = time.perf_counter()
        text = (slide_text or "").strip()
        scene = (visual_scene or "").strip()
        q = finalize_photo_query(
            (query or "").strip(), slide_text=text
        ) or (query or "").strip()
        exclude = exclude_ids or set()
        slide_label = (slide_index + 1) if slide_index is not None else "?"
        # legacy kwargs
        del _ugc_candid_retry
        do_broaden = bool(allow_broaden)
        del _broaden_depth

        self._status(f"Поиск: {q}")
        _ = query_cache_dir(q)

        pins_raw = self.search(q)
        # Пустая сеть -> warm + soft retry, затем Smart Broaden (не локальные stub!)
        if not pins_raw:
            print(
                f"[Слайд {slide_label}] Pinterest Search '{q}': "
                f"получено из сети=0 -> warm_session + retry"
            )
            self.warm_session()
            time.sleep(0.5)
            q_soft = " ".join(
                w
                for w in re.split(r"\s+", q)
                if w and w.lower() != "iphone"
            ).strip() or q
            soft_pins = self.search(q_soft, finalize=False)
            if soft_pins:
                pins_raw = soft_pins
                q = q_soft
            else:
                time.sleep(0.4)
                pins_raw = self.search(q)

        if not pins_raw and do_broaden:
            for alt_q in smart_broaden_queries(q, max_alts=1):
                print(
                    f"[Слайд {slide_label}] Smart Broaden: «{q}» -> «{alt_q}»"
                )
                alt_pins = self.search(alt_q, finalize=False)
                if alt_pins:
                    pins_raw = alt_pins
                    q = alt_q
                    break
                time.sleep(0.25)

        want = max(self._taste_fetch_limit(limit), 4)
        pins, raw_count, dups_count = self._select_pins_avoiding_used(
            pins_raw,
            exclude=exclude,
            ignore_used=ignore_used,
            want=want,
        )
        # ещё раз выкинуть зомби img000 если пролезли
        before = len(pins)
        pins = [p for p in pins if not is_fake_stub_pin_id(p.pin_id)]
        if len(pins) < before:
            print(
                f"[Слайд {slide_label}] DROP fake stub pins "
                f"img000×{before - len(pins)}"
            )
        # PhotoVault blacklist — никогда не скачиваем / не показываем
        try:
            from core.photo_vault import drop_blacklisted_pins

            pins, bl_n = drop_blacklisted_pins(pins)
            if bl_n:
                print(
                    f"[Слайд {slide_label}] vault blacklist drop ×{bl_n}"
                )
        except Exception as exc:
            print(f"[vault] filter skip: {exc}")
        print(
            f"[Слайд {slide_label}] Pinterest Search '{q}': "
            f"получено из сети={raw_count}, отсеяно повторов={dups_count}, "
            f"готово к отбору={len(pins)}"
        )

        def _empty(stage: str, **progress_kw: Any) -> tuple[
            list[CandidateImage], HarvestProgress
        ]:
            print(
                f"[Слайд {slide_label}] Pinterest Search '{q}': "
                f"итог 0 кадров (stage={stage})"
            )
            return [], HarvestProgress(
                stage=stage,
                elapsed_sec=time.perf_counter() - t0,
                **progress_kw,
            )

        if not pins:
            return _empty("empty")

        kept, ai_rejected = self.filter_ai(pins)
        if not kept:
            return _empty(
                "ai_filtered", found=len(pins), ai_rejected=ai_rejected
            )

        self._status(
            f"Скачивание ({DOWNLOAD_CONCURRENCY} потоков)… кандидатов: {len(kept)}"
        )
        fetch_limit = self._taste_fetch_limit(limit)
        # Rescue/guarantee path: smaller CDN pool (speed)
        cap = RESCUE_DOWNLOAD_CAP if not do_broaden else max(fetch_limit, 10)
        pool = kept[: min(cap, max(fetch_limit, 10))]
        raw_cands, dl_prog = asyncio.run(
            self._download_and_judge(
                pool,
                q,
                limit,
                text,
                fetch_limit=len(pool),
                anchor_image=anchor_image,
                apply_score=False,
                visual_scene=scene,
            )
        )
        cands = list(raw_cands)
        if apply_score and cands:
            cands = self.score_candidates(
                cands,
                slide_text=text,
                query=q,
                limit=limit,
                anchor_image=anchor_image,
                visual_scene=scene,
                slide_index=int(slide_index) if slide_index is not None else 0,
            )

        # НЕ баним альтернативы / сырой пул — только mark_used(финал) снаружи

        if not cands:
            # Гейты обнулили — берём лучшее из уже скачанного (без нового поиска)
            if apply_score and raw_cands and _allow_emergency:
                print(
                    f"[WARNING] Слайд {slide_label}: гейты обнулили — "
                    f"emergency-keep из {len(raw_cands)} скачанных"
                )
                kept_em = self.rank_pool_emergency(
                    raw_cands,
                    slide_text=text,
                    query=q,
                    limit=max(limit, 1),
                    anchor_image=anchor_image,
                    visual_scene=scene,
                )
                if kept_em:
                    elapsed = time.perf_counter() - t0
                    return kept_em, HarvestProgress(
                        stage="emergency",
                        found=raw_count,
                        ai_rejected=ai_rejected,
                        downloaded=len(kept_em),
                        bytes_total=dl_prog.bytes_total,
                        elapsed_sec=elapsed,
                        speed_mbps=dl_prog.speed_mbps,
                    )
            return _empty(
                "filtered_empty",
                found=raw_count,
                ai_rejected=ai_rejected,
                downloaded=0,
            )

        ids_preview = ", ".join(c.pin_id for c in cands[:8]) or "—"
        print(
            f"[Слайд {slide_label}] Pinterest Search '{q}': "
            f"сеть={raw_count}, повторы={dups_count}, "
            f"к отбору={len(pins)}, скачано/ранг={len(cands)} "
            f"(IDs: {ids_preview})"
        )

        elapsed = time.perf_counter() - t0
        return cands, HarvestProgress(
            stage="done",
            found=raw_count,
            ai_rejected=ai_rejected,
            downloaded=len(cands),
            bytes_total=dl_prog.bytes_total,
            elapsed_sec=elapsed,
            speed_mbps=dl_prog.speed_mbps,
        )

    def _search_select_pins(
        self,
        query: str,
        *,
        slide_text: str = "",
        slide_index: int | None = None,
        limit: int = CANDIDATES_PER_SLIDE,
        allow_broaden: bool = True,
        ignore_used: bool = False,
        exclude_ids: set[str] | None = None,
    ) -> tuple[list[PinMeta], str, int]:
        """
        Search + pin select + AI filter — NO CDN download.
        Returns (pins, used_query, ai_rejected_count).
        """
        text = (slide_text or "").strip()
        q = finalize_photo_query(
            (query or "").strip(), slide_text=text
        ) or (query or "").strip()
        if not q:
            return [], "", 0
        exclude = exclude_ids or set()
        slide_label = (slide_index + 1) if slide_index is not None else "?"

        pins_raw = self.search(q)
        if not pins_raw:
            print(
                f"[Слайд {slide_label}] Pinterest Search '{q}': "
                f"сеть=0 -> warm + retry"
            )
            self.warm_session()
            time.sleep(0.2)
            q_soft = " ".join(
                w
                for w in re.split(r"\s+", q)
                if w and w.lower() != "iphone"
            ).strip() or q
            soft_pins = self.search(q_soft, finalize=False)
            if soft_pins:
                pins_raw = soft_pins
                q = q_soft
            else:
                time.sleep(0.2)
                pins_raw = self.search(q)

        if not pins_raw and allow_broaden:
            for alt_q in smart_broaden_queries(q, max_alts=1):
                print(
                    f"[Слайд {slide_label}] Smart Broaden: «{q}» -> «{alt_q}»"
                )
                alt_pins = self.search(alt_q, finalize=False)
                if alt_pins:
                    pins_raw = alt_pins
                    q = alt_q
                    break
                time.sleep(0.15)

        if not pins_raw:
            print(
                f"[Слайд {slide_label}] Pinterest Search '{q}': 0 pins"
            )
            return [], q, 0

        want = max(self._taste_fetch_limit(limit), 4)
        pins, raw_count, dups_count = self._select_pins_avoiding_used(
            pins_raw,
            exclude=exclude,
            ignore_used=ignore_used,
            want=want,
        )
        pins = [p for p in pins if not is_fake_stub_pin_id(p.pin_id)]
        try:
            from core.photo_vault import drop_blacklisted_pins

            pins, bl_n = drop_blacklisted_pins(pins)
            if bl_n:
                print(
                    f"[Слайд {slide_label}] vault blacklist drop ×{bl_n}"
                )
        except Exception as exc:
            print(f"[vault] filter skip: {exc}")

        print(
            f"[Слайд {slide_label}] Pinterest Search '{q}': "
            f"сеть={raw_count}, dups={dups_count}, к отбору={len(pins)}"
        )
        if not pins:
            return [], q, 0
        kept, ai_rejected = self.filter_ai(pins)
        return kept, q, ai_rejected

    def harvest_until_filled(
        self,
        primary_query: str,
        *,
        slide_text: str = "",
        slide_index: int = 0,
        limit: int = CANDIDATES_PER_SLIDE,
        min_keep: int = 1,
        anchor_image: Image.Image | None = None,
        topic: str = "",
        max_attempts: int = MAX_QUERY_ATTEMPTS,
        apply_score: bool = True,
        visual_scene: str = "",
        alt_queries: list[str] | None = None,
        avoid_queries: set[str] | frozenset[str] | None = None,
        search_budget: int | None = None,
    ) -> tuple[list[CandidateImage], HarvestProgress, str]:
        """
        Multi-query: search budgeted queries → merge pins → ONE CDN download.
        On empty: vibe-rescue NEW angles (never re-search failed qs).
        empty slot > stock photo.
        """
        del min_keep, max_attempts
        scene = (visual_scene or "").strip()
        budget = int(
            SLIDE_SEARCH_BUDGET if search_budget is None else max(0, search_budget)
        )
        primary = re.sub(r"\s+", " ", (primary_query or "").strip())
        prior_avoid = {
            (a or "").strip().lower()
            for a in (avoid_queries or ())
            if (a or "").strip()
        }
        chain: list[str] = []
        if primary and primary.lower() not in prior_avoid:
            chain.append(primary)
        for aq in alt_queries or []:
            a = re.sub(r"\s+", " ", (aq or "").strip())
            if (
                a
                and a.lower() not in {c.lower() for c in chain}
                and a.lower() not in prior_avoid
            ):
                chain.append(a)
        if not chain:
            chain = ["everyday indoor candid"]

        t0 = time.perf_counter()
        # Multi-query diversifies — skip Smart Broaden (saves ≤5 searches)
        broaden = len(chain) <= 1 and budget <= 2
        merged_pins: list[PinMeta] = []
        seen_ids: set[str] = set()
        winning = chain[0]
        total_ai = 0
        tried: list[str] = []
        searches_used = 0

        for qi, q in enumerate(chain):
            if searches_used >= budget:
                print(
                    f"[Слайд {slide_index + 1}] search budget "
                    f"{budget} hit — skip remaining chain"
                )
                break
            label = "primary" if qi == 0 else f"alt{qi}"
            self._status(f"Слайд {slide_index + 1}: «{q}» ({label})…")
            print(f"[Слайд {slide_index + 1}] {label}: '{q}'")
            pins, used_q, ai_n = self._search_select_pins(
                q,
                slide_text=slide_text,
                slide_index=slide_index,
                limit=limit,
                allow_broaden=broaden and searches_used + 1 < budget,
                ignore_used=False,
            )
            searches_used += 1
            tried.append(used_q or q)
            total_ai += ai_n
            before = len(merged_pins)
            for p in pins:
                if p.pin_id in seen_ids:
                    continue
                seen_ids.add(p.pin_id)
                merged_pins.append(p)
            if len(merged_pins) > before:
                if qi == 0 or before == 0:
                    winning = used_q or q

        collected: list[CandidateImage] = []
        total_bytes = 0
        if merged_pins:
            pool = merged_pins[:MERGE_DOWNLOAD_CAP]
            print(
                f"[Слайд {slide_index + 1}] merge-download "
                f"{len(pool)} pins (from {len(tried)} queries, "
                f"cap={MERGE_DOWNLOAD_CAP})"
            )
            self._status(
                f"Скачивание ({DOWNLOAD_CONCURRENCY} потоков)… "
                f"кандидатов: {len(pool)}"
            )
            raw_cands, dl_prog = asyncio.run(
                self._download_and_judge(
                    pool,
                    winning,
                    limit,
                    slide_text,
                    fetch_limit=len(pool),
                    anchor_image=anchor_image,
                    apply_score=False,
                    visual_scene=scene,
                )
            )
            collected = list(raw_cands)
            total_bytes = int(getattr(dl_prog, "bytes_total", 0) or 0)
            if apply_score and collected:
                collected = self.score_candidates(
                    collected,
                    slide_text=slide_text,
                    query=winning,
                    limit=limit,
                    visual_scene=scene,
                    slide_index=slide_index,
                )

        # Vibe rescue: different angles matching slide text — before empty
        if not collected and searches_used < budget:
            from core.query_forge import vibe_rescue_queries

            avoid = prior_avoid | {t.lower() for t in tried}
            rescues = vibe_rescue_queries(
                slide_text=slide_text,
                visual_scene=scene,
                topic=topic,
                avoid=avoid,
                max_n=min(3, budget - searches_used),
            )
            for ri, rq in enumerate(rescues):
                if searches_used >= budget:
                    break
                print(
                    f"[Слайд {slide_index + 1}] vibe-rescue{ri + 1}: '{rq}'"
                )
                pins, used_q, ai_n = self._search_select_pins(
                    rq,
                    slide_text=slide_text,
                    slide_index=slide_index,
                    limit=limit,
                    allow_broaden=False,
                    ignore_used=False,
                )
                searches_used += 1
                tried.append(used_q or rq)
                total_ai += ai_n
                rescue_pins = [
                    p for p in pins if p.pin_id not in seen_ids
                ][:RESCUE_DOWNLOAD_CAP]
                for p in rescue_pins:
                    seen_ids.add(p.pin_id)
                if not rescue_pins:
                    continue
                print(
                    f"[Слайд {slide_index + 1}] vibe-download "
                    f"{len(rescue_pins)} pins"
                )
                raw_cands, dl_prog = asyncio.run(
                    self._download_and_judge(
                        rescue_pins,
                        used_q or rq,
                        limit,
                        slide_text,
                        fetch_limit=len(rescue_pins),
                        anchor_image=anchor_image,
                        apply_score=False,
                        visual_scene=scene,
                    )
                )
                total_bytes += int(getattr(dl_prog, "bytes_total", 0) or 0)
                if not raw_cands:
                    continue
                if apply_score:
                    scored = self.score_candidates(
                        list(raw_cands),
                        slide_text=slide_text,
                        query=used_q or rq,
                        limit=limit,
                        visual_scene=scene,
                        slide_index=slide_index,
                    )
                    if scored:
                        collected = scored
                        winning = used_q or rq
                        break
                else:
                    collected = list(raw_cands)
                    winning = used_q or rq
                    break

        if not collected:
            remain = max(0, budget - searches_used)
            # Budget spent on vibe already — empty slot beats stock re-search
            if remain > 0:
                g_kept, g_q = self.guarantee_at_least_one(
                    slide_text=slide_text,
                    slide_index=slide_index,
                    preferred_query=winning or chain[0],
                    limit=max(limit, 1),
                    topic=topic,
                    visual_scene=scene,
                    avoid_queries=prior_avoid | {t.lower() for t in tried},
                    searches_budget=min(GUARANTEE_MAX_SEARCHES, remain),
                )
                if g_kept:
                    collected = list(g_kept)
                    winning = g_q or winning
            else:
                print(
                    f"[Слайд {slide_index + 1}] budget exhausted "
                    f"({searches_used}/{budget}) — empty > stock"
                )

        elapsed = time.perf_counter() - t0
        mb = total_bytes / (1024 * 1024) if total_bytes else 0.0
        prog = HarvestProgress(
            stage="done" if collected else "empty",
            found=len(collected),
            ai_rejected=total_ai,
            downloaded=len(collected),
            bytes_total=total_bytes,
            elapsed_sec=elapsed,
            speed_mbps=(mb / elapsed) if elapsed > 0 else 0.0,
        )
        keep_n = limit if apply_score else self._taste_fetch_limit(limit)
        return collected[: max(keep_n * 2, keep_n)], prog, winning

    def harvest_slides_parallel(
        self,
        slides: list[tuple],
        *,
        limit: int = CANDIDATES_PER_SLIDE,
        min_keep: int = 1,
        topic: str = "",
        max_attempts: int = MAX_QUERY_ATTEMPTS,
        max_workers: int = 6,
        character_dna: dict[str, str] | None = None,
    ) -> list[tuple[list[CandidateImage], HarvestProgress, str]]:
        """
        1) asyncio.gather — параллельный Pinterest search+CDN всех слайдов
        2) затем SigLIP (UGC/Relevance/Taste) последовательно на GPU

        slides: (query, text, idx) или (query, text, idx, visual_scene)
        character_dna: optional passport -> attribute + gender lock
        """
        n = len(slides)
        if n == 0:
            return []

        self.last_attribute_consistency: str | None = None
        dna = character_dna if isinstance(character_dna, dict) else None
        if dna:
            print(
                f"[attr-lock] character_dna active: "
                f"gender={dna.get('gender')} hair={dna.get('hair')!r}"
            )
        def _norm(
            item: tuple,
        ) -> tuple[str, str, int, str, list[str]]:
            q = str(item[0] or "")
            text = str(item[1] or "") if len(item) > 1 else ""
            idx = int(item[2]) if len(item) > 2 else 0
            scene = str(item[3] or "") if len(item) > 3 else ""
            alts_raw = item[4] if len(item) > 4 else []
            alts: list[str] = []
            if isinstance(alts_raw, (list, tuple)):
                alts = [str(a).strip() for a in alts_raw if str(a).strip()]
            elif isinstance(alts_raw, str) and alts_raw.strip():
                alts = [alts_raw.strip()]
            return q, text, idx, scene, alts

        normalized = [_norm(s) for s in slides]

        # Не больше SEARCH_MAX_WORKERS — иначе SSL/rate-limit -> raw=0
        workers = max(1, min(int(max_workers), SEARCH_MAX_WORKERS, max(n, 1)))

        # Один прогрев ДО параллели (не из 6 воркеров сразу)
        self.warm_session(force=False)

        def _download_one(
            q: str, text: str, idx: int, scene: str, alts: list[str]
        ) -> tuple[list[CandidateImage], HarvestProgress, str]:
            return self.harvest_until_filled(
                q,
                slide_text=text,
                slide_index=idx,
                limit=limit,
                min_keep=min_keep,
                anchor_image=None,
                topic=topic,
                max_attempts=max_attempts,
                apply_score=False,
                visual_scene=scene,
                alt_queries=alts,
            )

        print(
            f"[PARALLEL] gather · {n} слайдов · workers={workers} · "
            f"max_attempts={max_attempts} · multi-query=on"
        )

        t_pin0 = time.perf_counter()

        async def _gather_downloads() -> list[
            tuple[list[CandidateImage], HarvestProgress, str]
        ]:
            loop = asyncio.get_running_loop()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                tasks = [
                    loop.run_in_executor(
                        pool, _download_one, q, text, idx, scene, alts
                    )
                    for q, text, idx, scene, alts in normalized
                ]
                return list(await asyncio.gather(*tasks))

        raw = asyncio.run(_gather_downloads())

        # Если почти всё пусто — vibe-only sequential (НЕ те же primary/alt)
        empty_n = sum(1 for cands, _p, _q in raw if not cands)
        if empty_n >= max(1, (n + 1) // 2):
            print(
                f"[WARNING] parallel: {empty_n}/{n} пустых — "
                f"vibe-rescue sequential…"
            )
            self.warm_session(force=True)
            time.sleep(1.0)
            from core.query_forge import vibe_rescue_queries

            fixed_raw: list[
                tuple[list[CandidateImage], HarvestProgress, str]
            ] = []
            for (q, text, idx, scene, alts), (cands, prog, used_q) in zip(
                normalized, raw
            ):
                if cands:
                    fixed_raw.append((cands, prog, used_q))
                    continue
                avoid = {q.lower(), (used_q or "").lower(), *(a.lower() for a in alts)}
                avoid.discard("")
                rescues = vibe_rescue_queries(
                    slide_text=text,
                    visual_scene=scene,
                    topic=topic,
                    avoid=avoid,
                    max_n=2,
                )
                if not rescues:
                    fixed_raw.append((cands, prog, used_q))
                    continue
                more, prog2, win2 = self.harvest_until_filled(
                    rescues[0],
                    slide_text=text,
                    slide_index=idx,
                    limit=limit,
                    min_keep=min_keep,
                    anchor_image=None,
                    topic=topic,
                    max_attempts=1,
                    apply_score=False,
                    visual_scene=scene,
                    alt_queries=rescues[1:],
                    avoid_queries=avoid,
                    search_budget=2,
                )
                fixed_raw.append((more, prog2, win2 or used_q or q))
                time.sleep(0.35)
            raw = fixed_raw

        pin_wall = time.perf_counter() - t_pin0

        # Фаза SigLIP — последовательно (CUDA + один _LOCK)
        # Gender: DNA gender preferred; else infer from slide 1 winner
        t_sig0 = time.perf_counter()
        self.reset_timing()  # накопители гейтов; wall ниже важнее
        # Process in slide_index order so gender lock sees slide 1 first
        order = sorted(range(n), key=lambda i: normalized[i][2])
        carousel_gender: str | None = None
        if dna and str(dna.get("gender") or "").lower() in ("female", "male"):
            carousel_gender = str(dna["gender"]).lower()
            print(f"[gender-lock] from character_dna -> {carousel_gender}")
        interim: dict[int, tuple[list[CandidateImage], HarvestProgress, str]] = {}

        for pos in order:
            q, text, idx, scene, _alts = normalized[pos]
            cands, prog, used_q = raw[pos]
            slide_no = idx + 1
            if not cands:
                if COMPLETION_FILL_ENABLED:
                    print(
                        f"[COMPLETION] Слайд {slide_no}: download empty — "
                        f"soft vibe refill…"
                    )
                    avoid0 = {
                        (used_q or q or "").lower(),
                        *(a.lower() for a in _alts),
                    }
                    avoid0.discard("")
                    g0, g0q = self.guarantee_at_least_one(
                        slide_text=text,
                        slide_index=idx,
                        preferred_query=used_q or q,
                        limit=max(limit, 1),
                        topic=topic,
                        visual_scene=scene,
                        avoid_queries=avoid0,
                        searches_budget=COMPLETION_MAX_SEARCHES,
                        allow_soft=True,
                    )
                    if g0:
                        interim[pos] = (g0, prog, g0q or used_q)
                        continue
                    n0, n0q = self.force_any_candidate(
                        slide_text=text,
                        slide_index=idx,
                        topic=topic,
                        visual_scene=scene,
                        preferred_query=used_q or q,
                        limit=max(limit, 1),
                    )
                    if n0:
                        interim[pos] = (n0, prog, n0q or used_q)
                        continue
                interim[pos] = ([], prog, used_q)
                continue
            original_pool = list(cands)
            kept = self.score_candidates(
                cands,
                slide_text=text,
                query=used_q or q,
                limit=limit,
                visual_scene=scene,
                slide_index=idx,
                carousel_gender=carousel_gender,
                character_dna=dna,
            )
            win_q = used_q or q
            # Soft-gate пуст — emergency из уже скачанных (с теми же consistency gates)
            if not kept:
                print(
                    f"[WARNING] Слайд {slide_no}: нет selectable "
                    f"из {len(original_pool)} кадров — emergency-keep"
                )
                pool_em = _filter_consistency_gates(
                    list(original_pool),
                    slide_index=idx,
                    carousel_gender=carousel_gender,
                    character_dna=dna,
                    query=used_q or q,
                )
                if not pool_em:
                    if STRICT_SELECTION_CONTRACT:
                        print(
                            f"[STRICT] Слайд {slide_no}: consistency emptied "
                            f"pool — no lock bypass"
                        )
                        pool_em = []
                    else:
                        pool_em = list(original_pool)
                kept = self.rank_pool_emergency(
                    pool_em,
                    slide_text=text,
                    query=used_q or q,
                    limit=max(limit, 1),
                    visual_scene=scene,
                )
                win_q = used_q or q
            # Soft from downloaded pool — disabled under STRICT contract
            if not kept and POOL_SOFT_UGC_ENABLED:
                scored_pool = [
                    c
                    for c in original_pool
                    if float(getattr(c, "ugc_score", 0) or 0) >= GUARANTEE_UGC_FLOOR
                    and float(getattr(c, "taste_score", 0) or 0) >= EMERGENCY_TASTE_FLOOR
                ]
                if scored_pool:
                    scored_pool.sort(
                        key=lambda c: float(getattr(c, "ugc_score", 0) or 0),
                        reverse=True,
                    )
                    kept = scored_pool[: max(limit, 1)]
                    for c in kept:
                        c.selection_mode = "pool_soft_ugc"
                        c.relevance_reason = "pool soft ugc (skip re-search)"
                    print(
                        f"[SPEED] Слайд {slide_no}: pool-soft "
                        f"ugc={kept[0].ugc_score:.0%} — без guarantee-search"
                    )
            elif not kept and STRICT_SELECTION_CONTRACT:
                print(
                    f"[STRICT] Слайд {slide_no}: no eligible after emergency "
                    f"— skip pool_soft_ugc (contract)"
                )
            # Guarantee: vibe-rescue only; never re-search failed primary/alt
            if not kept:
                avoid = {
                    (used_q or q or "").lower(),
                    (win_q or "").lower(),
                    *(a.lower() for a in _alts),
                }
                avoid.discard("")
                g_kept, g_q = self.guarantee_at_least_one(
                    slide_text=text,
                    slide_index=idx,
                    preferred_query=used_q or q,
                    limit=max(limit, 1),
                    topic=topic,
                    visual_scene=scene,
                    avoid_queries=avoid,
                    searches_budget=GUARANTEE_MAX_SEARCHES,
                )
                if g_kept:
                    # Still drop frontal faces / gender / attr clash when possible
                    g_kept = _filter_consistency_gates(
                        g_kept,
                        slide_index=idx,
                        carousel_gender=carousel_gender,
                        character_dna=dna,
                        query=win_q,
                    ) or g_kept
                    kept = g_kept
                    win_q = g_q or win_q
                elif STRICT_SELECTION_CONTRACT and not COMPLETION_FILL_ENABLED:
                    print(
                        f"[STRICT] Слайд {slide_no}: empty after guarantee "
                        f"— slide will fail (no soft-ship)"
                    )
            # Completion fill: last mile so factory never ships missing slides
            if not kept and COMPLETION_FILL_ENABLED:
                print(
                    f"[COMPLETION] Слайд {slide_no}: last-mile — "
                    f"style-pivot first, soft only after…"
                )
                # 1) Radical eased queries with HARD floors (coffee/hands/window)
                avoid2 = {
                    (used_q or q or "").lower(),
                    (win_q or "").lower(),
                    *(a.lower() for a in _alts),
                }
                avoid2.discard("")
                g_pivot, g_pivot_q = self.guarantee_at_least_one(
                    slide_text=text,
                    slide_index=idx,
                    preferred_query=used_q or q,
                    limit=max(limit, 1),
                    topic=topic,
                    visual_scene=scene,
                    avoid_queries=avoid2,
                    searches_budget=COMPLETION_MAX_SEARCHES,
                    allow_soft=False,
                )
                if g_pivot:
                    kept = g_pivot
                    win_q = g_pivot_q or win_q
                    print(
                        f"[COMPLETION] style-pivot «{win_q}» "
                        f"ugc={kept[0].ugc_score:.0%} "
                        f"mode={kept[0].selection_mode}"
                    )
                # 2) soft from already-downloaded pool (only if pivot missed)
                if not kept and original_pool:
                    scored_pool = [
                        c
                        for c in original_pool
                        if float(getattr(c, "ugc_score", 0) or 0)
                        >= COMPLETION_UGC_FLOOR
                    ]
                    if not scored_pool:
                        scored_pool = sorted(
                            original_pool,
                            key=lambda c: float(getattr(c, "ugc_score", 0) or 0),
                            reverse=True,
                        )
                        # Drop only hard junk; keep low-ugc over empty
                        scored_pool = [
                            c
                            for c in scored_pool
                            if not is_junk_candidate_image(
                                c.image, getattr(c, "title", "") or ""
                            )
                        ] or scored_pool[:1]
                    if scored_pool:
                        scored_pool.sort(
                            key=lambda c: float(getattr(c, "ugc_score", 0) or 0),
                            reverse=True,
                        )
                        kept = scored_pool[: max(limit, 1)]
                        for c in kept:
                            c.selection_mode = "completion_fill"
                            c.relevance_reason = "completion_fill pool"
                        print(
                            f"[COMPLETION] pool-soft ugc={kept[0].ugc_score:.0%}"
                        )
                # 3) extra vibe searches with soft floors
                if not kept:
                    g2, g2q = self.guarantee_at_least_one(
                        slide_text=text,
                        slide_index=idx,
                        preferred_query=used_q or q,
                        limit=max(limit, 1),
                        topic=topic,
                        visual_scene=scene,
                        avoid_queries=avoid2,
                        searches_budget=COMPLETION_MAX_SEARCHES,
                        allow_soft=True,
                    )
                    if g2:
                        kept = g2
                        win_q = g2q or win_q
                        print(
                            f"[COMPLETION] vibe-soft «{win_q}» "
                            f"ugc={kept[0].ugc_score:.0%}"
                        )
                # 4) nuclear — any non-junk photo beats an empty slot
                if not kept:
                    n_kept, n_q = self.force_any_candidate(
                        slide_text=text,
                        slide_index=idx,
                        topic=topic,
                        visual_scene=scene,
                        preferred_query=used_q or q,
                        limit=max(limit, 1),
                    )
                    if n_kept:
                        kept = n_kept
                        win_q = n_q or win_q
                if not kept:
                    print(
                        f"[COMPLETION] Слайд {slide_no}: still empty "
                        f"— carousel will fail"
                    )
            # Lock gender from slide 1 winner if DNA did not set it
            if idx == 0 and kept and carousel_gender is None:
                try:
                    carousel_gender = infer_carousel_gender(kept[0].image)
                except Exception as exc:
                    print(f"[gender-lock] slide1 lock fail: {exc}")
                    carousel_gender = "female"
            prog.downloaded = len(kept)
            prog.stage = "done" if kept else "filtered_empty"
            interim[pos] = (kept, prog, win_q)

        scored = [interim[i] for i in range(n)]
        if carousel_gender:
            print(f"[gender-lock] carousel locked as {carousel_gender}")
        if dna:
            self.last_attribute_consistency = "pass"
            print("[attr-lock] attribute_consistency=pass")

        # Empty after download: harvest_until_filled already ran vibe+guarantee.
        # Do NOT re-search the same slide (that was the 13min death spiral).
        for i, ((_q, _text, idx, _scene, _alts), (cands, prog, used_q)) in enumerate(
            zip(normalized, scored)
        ):
            if cands:
                continue
            print(
                f"[STRICT] Слайд {idx + 1}: still empty after vibe budget "
                f"— empty slot > stock (q={used_q!r})"
            )

        # Уникальные pin между слайдами (параллельный download легко дублирует)
        pools = [list(cands) for cands, _p, _q in scored]
        deduped = dedupe_carousel_pools(pools, selected_index=0)
        fixed: list[tuple[list[CandidateImage], HarvestProgress, str]] = []
        for i, ((cands, prog, win_q), new_pool) in enumerate(zip(scored, deduped)):
            q, text, idx, scene, _alts = normalized[i]
            if new_pool is not cands and [
                c.pin_id for c in (cands[:1] or [])
            ] != [c.pin_id for c in (new_pool[:1] or [])]:
                print(
                    f"[dedupe] slide pin {cands[0].pin_id if cands else '-'} "
                    f"-> {new_pool[0].pin_id if new_pool else '-'}"
                )
            # Dedupe emptied the slide — nuclear refill (never leave hole)
            if not new_pool and COMPLETION_FILL_ENABLED:
                print(
                    f"[dedupe] slide {idx + 1} emptied — nuclear refill"
                )
                n_kept, n_q = self.force_any_candidate(
                    slide_text=text,
                    slide_index=idx,
                    topic=topic,
                    visual_scene=scene,
                    preferred_query=win_q or q,
                    limit=max(limit, 1),
                )
                if n_kept:
                    new_pool = n_kept
                    win_q = n_q or win_q
            # Hard-ban финальных pin сразу — следующие карусели / slides не возьмут
            if new_pool and new_pool[0].pin_id:
                self.mark_used([str(new_pool[0].pin_id)])
            prog.downloaded = len(new_pool)
            prog.stage = "done" if new_pool else prog.stage
            fixed.append((new_pool, prog, win_q))
        scored = fixed

        sig_wall = time.perf_counter() - t_sig0
        # Wall-тайминги фаз (для [TIMER] в batch_factory)
        with self._timing_lock:
            self.timing_pinterest_sec = pin_wall
            self.timing_siglip_sec = sig_wall
        return scored

    # ------------------------------------------------------------------
    # Ideas / recommendation-like feed (без логина)
    # UserHomefeedResource требует auth -> берём /ideas/{topic} + Related.
    # ------------------------------------------------------------------

    def discover_idea_topics(self) -> list[tuple[str, str]]:
        """[(path, slug), ...] с https://www.pinterest.com/ideas/."""
        try:
            resp = self._client.get(
                "https://www.pinterest.com/ideas/", headers=HTML_HEADERS
            )
        except httpx.HTTPError:
            return []
        self._csrf = self._client.cookies.get("csrftoken") or self._csrf
        found: list[tuple[str, str]] = []
        seen: set[str] = set()
        for path, slug in re.findall(
            r'(/ideas/([a-z0-9\-]+)/\d+/)', resp.text, flags=re.I
        ):
            slug_l = slug.lower()
            # цитаты / типографика — не для вкуса фонов
            if slug_l in {"quotes", "quote", "typography", "lettering"}:
                continue
            if path in seen:
                continue
            seen.add(path)
            found.append((path, slug_l))
        return found

    def fetch_ideas_topic_metas(self, topic_path: str, limit: int = 40) -> list[PinMeta]:
        """Пины с публичной topic-страницы /ideas/.../."""
        path = topic_path if topic_path.startswith("/") else f"/{topic_path}"
        try:
            resp = self._client.get(
                f"https://www.pinterest.com{path}", headers=HTML_HEADERS
            )
        except httpx.HTTPError:
            return []
        self._csrf = self._client.cookies.get("csrftoken") or self._csrf
        if resp.status_code >= 400:
            return []
        pins = _extract_from_pws_html(resp.text)
        pins = [p for p in pins if re.fullmatch(r"\d{6,20}", p.pin_id)]
        return _dedupe_pins(pins, limit=limit)

    def fetch_feed_metas(
        self,
        limit: int = 120,
        *,
        related_seeds: int = 10,
        related_per_seed: int = 16,
    ) -> list[PinMeta]:
        """
        Рекомендательный пул без узких search-запросов:
        1) хабы /ideas/{topic}
        2) Related Pins от случайных семян (как «ещё из ленты»).
        """
        import random as _rnd

        self._status("Лента Ideas: темы Pinterest…")
        topics = self.discover_idea_topics()
        if not topics:
            # запасной список публичных хабов
            topics = [
                ("/ideas/home-decor/935249274030/", "home-decor"),
                ("/ideas/travel/908182459161/", "travel"),
                ("/ideas/art/961238559656/", "art"),
                ("/ideas/beauty/935541271955/", "beauty"),
                ("/ideas/design/902065567321/", "design"),
                ("/ideas/diy-and-crafts/934876475639/", "diy-and-crafts"),
                ("/ideas/food-and-drink/918530398158/", "food-and-drink"),
                ("/ideas/mens-fashion/924581335376/", "mens-fashion"),
                ("/ideas/womens-fashion/948967005229/", "womens-fashion"),
                ("/ideas/animals/925056443165/", "animals"),
                ("/ideas/weddings/903260720461/", "weddings"),
            ]
        _rnd.shuffle(topics)
        # берём побольше тем для ширины ленты
        pick = topics[: max(6, min(10, len(topics)))]

        pool: list[PinMeta] = []
        seen: set[str] = set()
        for path, slug in pick:
            if len(pool) >= limit:
                break
            self._status(f"Лента Ideas · {slug}…")
            for pin in self.fetch_ideas_topic_metas(path, limit=28):
                if pin.pin_id in seen:
                    continue
                seen.add(pin.pin_id)
                pool.append(pin)
                if len(pool) >= limit:
                    break

        # Related — «рекомендации от пинов ленты»
        seeds = [p for p in pool if re.fullmatch(r"\d{6,20}", p.pin_id)]
        _rnd.shuffle(seeds)
        for seed in seeds[: max(0, related_seeds)]:
            if len(pool) >= limit:
                break
            self._status(f"Related от {seed.pin_id}…")
            try:
                related = self.fetch_related_metas(
                    seed.pin_id,
                    limit=related_per_seed,
                    exclude_ids=seen,
                )
            except Exception:
                related = []
            for pin in related:
                if pin.pin_id in seen:
                    continue
                seen.add(pin.pin_id)
                pool.append(pin)
                if len(pool) >= limit:
                    break

        _rnd.shuffle(pool)
        self._status(f"Лента: {len(pool)} пинов (ideas + related)")
        return pool[:limit]

    # ------------------------------------------------------------------
    # Related Pins (визуальные близнецы)
    # ------------------------------------------------------------------

    def _related_from_api(self, pin_id: str, page_size: int = 24) -> list[PinMeta]:
        """RelatedModulesResource — visually/contextually similar pins."""
        source = f"/pin/{pin_id}/"
        page_url = f"https://www.pinterest.com{source}"
        options = {
            "pin_id": pin_id,
            "context_pin_ids": [],
            "page_size": page_size,
            "search_query": "",
            "source": "deep_linking",
            "top_level_source": "deep_linking",
            "top_level_source_depth": 1,
            "is_pdp": False,
            "bookmarks": [""],
            "additional_fields": ["pin.gen_ai_topics"],
        }
        data = {"options": options, "context": {}}
        pins: list[PinMeta] = []
        try:
            resp = self._client.post(
                "https://www.pinterest.com/resource/RelatedModulesResource/get/",
                headers=self._api_headers(page_url),
                data={
                    "source_url": source,
                    "data": json.dumps(data, separators=(",", ":")),
                },
            )
            if resp.status_code == 200 and resp.content[:1] == b"{":
                raw: list[dict[str, Any]] = []
                _walk_collect_pins(resp.json(), raw)
                for obj in raw:
                    pin = _pin_from_obj(obj)
                    if pin and pin.pin_id != pin_id:
                        pins.append(pin)
        except httpx.HTTPError:
            pass
        return _dedupe_pins(pins)

    def _related_from_pin_page(self, pin_id: str) -> list[PinMeta]:
        """Fallback: __PWS_DATA__ со страницы пина (Related Pins в SSR)."""
        url = f"https://www.pinterest.com/pin/{pin_id}/"
        try:
            resp = self._client.get(url, headers=HTML_HEADERS)
        except httpx.HTTPError:
            return []
        self._csrf = self._client.cookies.get("csrftoken") or self._csrf
        final = str(resp.url).lower()
        if "/login" in final:
            return []
        html = resp.text
        low = html.lower()
        if "just a moment" in low or ("cloudflare" in low and "challenge" in low):
            return []
        pins = _extract_from_pws_html(html)
        return [p for p in pins if p.pin_id != pin_id and re.fullmatch(r"\d{6,20}", p.pin_id)]

    def fetch_related_metas(
        self,
        pin_id: str,
        *,
        limit: int = 24,
        exclude_ids: set[str] | None = None,
    ) -> list[PinMeta]:
        """Сырые метаданные Related Pins (без скачивания)."""
        if not re.fullmatch(r"\d{6,20}", str(pin_id or "")):
            return []
        exclude = set(exclude_ids or set())
        exclude.add(str(pin_id))

        self._status(f"Related Pins для {pin_id}…")
        pins = self._related_from_api(pin_id, page_size=max(limit * 2, 24))
        if len(pins) < limit:
            page_pins = self._related_from_pin_page(pin_id)
            pins = _dedupe_pins(pins + page_pins)

        pins = [p for p in pins if p.pin_id not in exclude]
        return pins[: max(limit * 3, limit)]

    def get_related_pins(
        self,
        pin_id: str,
        limit: int = RELATED_PINS_DEFAULT,
        *,
        slide_text: str = "",
        exclude_ids: set[str] | None = None,
        query: str = "related pins",
        judge: bool = False,
    ) -> list[CandidateImage]:
        """
        Похожие пины (Related / visually similar) для seed pin_id.

        1) RelatedModulesResource (+ fallback __PWS_DATA__ страницы пина)
        2) Фильтр ИИ (digitalMediaSourceType == 11)
        3) Скачивание превью в память (~10 потоков)
        """
        t0 = time.perf_counter()
        metas = self.fetch_related_metas(
            pin_id, limit=limit, exclude_ids=exclude_ids
        )
        if not metas:
            self._status(f"Related Pins: пусто для {pin_id}")
            return []

        kept, ai_rejected = self.filter_ai(metas)
        if not kept:
            self._status(
                f"Related Pins: все отсеяны как ИИ ({ai_rejected}) для {pin_id}"
            )
            return []

        fetch_limit = self._taste_fetch_limit(limit)
        pool = kept[: max(fetch_limit * 2, 12)]
        self._status(
            f"Related: скачивание {len(pool)} близнецов "
            f"({RELATED_DOWNLOAD_WORKERS} потоков)…"
        )

        cands, _prog = asyncio.run(
            self._download_and_judge(
                pool,
                query or f"related:{pin_id}",
                limit,
                slide_text if judge else "",
                concurrency=RELATED_DOWNLOAD_WORKERS,
                fetch_limit=fetch_limit,
            )
        )

        # Не баним related-альтернативы — только mark_used(финал) снаружи

        elapsed = time.perf_counter() - t0
        self._status(
            f"Related Pins: {len(cands)} фото за {elapsed:.1f}с "
            f"(AI−{ai_rejected})"
        )
        return cands

