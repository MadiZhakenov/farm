#!/usr/bin/env python3
"""
Генерация текстов карусели через Google Gemini API (gemini-3.1-flash-lite).

Динамический JSON-контракт: slides[] из 6–9 элементов (hook / body… / cta)
с индивидуальным search_query на каждый слайд.
search_query = human situation & vibe (pose + place, 3–4 слова),
НЕ literal word→object из текста слайда.
Few-shot: локальный RAG (fastembed) по всей viral_playbook (~1600).
Ключ: GEMINI_API_KEY (.env).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_MAX_OUTPUT_TOKENS = 1200
GEMINI_API_BASE = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{DEFAULT_GEMINI_MODEL}:generateContent"
)

# Few-shot: динамический RAG по viral_playbook (fastembed, $0)
FEW_SHOT_N = 3
MAX_EXAMPLE_SLIDES = 5
MAX_EXAMPLE_CHARS = 420

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "reelfarm_database.db"
VIRAL_QUERY_PATTERNS_PATH = ROOT / "data" / "viral_query_patterns.json"


def load_viral_query_rule(path: Path | None = None) -> str:
    """PROVEN PINTEREST TAXONOMY для системного промпта (QueryPatternManager)."""
    from core.query_patterns import get_query_pattern_manager

    mgr = get_query_pattern_manager(path)
    return mgr.get_top_archetypes_summary()


def extract_niche_tags(data: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """Обратная совместимость: топ-теги по нишам."""
    del data
    from core.query_patterns import get_query_pattern_manager

    mgr = get_query_pattern_manager()
    return {
        "Fitness": mgr.get_patterns_for_niche("fitness", limit=10),
        "Skincare/Beauty": mgr.get_patterns_for_niche("skincare", limit=10),
        "Study/Intellectual": mgr.get_patterns_for_niche("study", limit=10),
        "Cozy/Bed": mgr.get_patterns_for_niche("cozy", limit=10),
        "Relationships/Night": mgr.get_patterns_for_niche("relationships", limit=10),
        "Career": mgr.get_patterns_for_niche("career", limit=10),
    }


PREFERRED_NICHES = (
    "self improvement",
    "productivity",
    "mental health",
    "study",
    "discipline",
    "mindset",
    "motivation",
    "relationships",
    "feminine lifestyle",
    "clean girl",
    "skincare",
)

# Базовые банальности + лайф-коуч клише
BANNED_GENERIC = (
    "stop wasting time",
    "drink water",
    "set goals",
    "just start",
    "believe in yourself",
    "wake up earlier",
    "make a to-do list",
    "stay positive",
    "hustle harder",
    "meditate for 5",
    "meditate for five",
    "gratitude journal",
    "empty cup",
    "pareto",
    "80/20",
    "80 20",
    "burn to-do list",
    "burn your to-do",
)

# Абстрактные коуч-глаголы/фразы — запрещены в body
BANNED_COACH_PHRASES = (
    "embrace",
    "find true contentment",
    "unlock potential",
    "unlock your full mental potential",
    "unlock your",
    "practice mindfulness",
    "realize",
    "cherish",
    "be present",
    "reflect on feelings",
    "stay strong",
    "true contentment",
    "inner peace",
    "find peace",
    "full mental potential",
    "embrace spontaneity",
    "embrace growth",
    "embrace boredom",
)

# Робот-консультант / корпоративный коучинг — полный бан
BANNED_ROBOT_VOICE = (
    "protocol",
    "protocols",
    "audit your",
    "audit the",
    "triage checklist",
    "triage your",
    "cognitive performance",
    "optimize output",
    "optimize your output",
    "sensory reset",
    "focus protocol",
    "elimination protocol",
    "contextual protocol",
    "performance protocol",
    "mental protocol",
    "reset protocol",
    "workflow audit",
    "habit audit",
    "energy audit",
    "priority triage",
    "bandwidth triage",
    "executive function",
    "cognitive load optimization",
    "high-leverage",
    "high leverage habit",
    "systems thinking",
    "operating system for",
    "install this habit",
    "run this protocol",
)

# Универсальный набор «фикс на всё» — нельзя штамповать на любую тему
BANNED_UNIVERSAL_TOOLKIT = (
    "drink cold water",
    "cold water",
    "5 deep breaths",
    "deep breaths",
    "deep breathing",
    "mindful breathing",
    "take a walk",
    "walk outside",
    "sticky note",
    "sticky notes",
    "write on sticky",
    "stare at trees",
    "push-ups",
    "push ups",
    "jumping jacks",
    "lemon water",
)

# «Close tabs» — только для тем про context switching / вкладки
_CLOSE_TAB_PHRASES = (
    "close every browser tab",
    "close all browser tab",
    "close browser tab",
    "close every tab",
    "close all tab",
    "close every open tab",
    "close all open tab",
    "close every irrelevant tab",
    "close all but one tab",
)

# Хуки-клоны — точные штампы (санитайзер пересобирает)
BANNED_HOOK_STAMPS = (
    "busy isn't productive",
    "boundary scripts worth screenshotting",
    "scripts worth screenshotting",
    "cures why multitasking feels",
    "the 15-minute rule that cures",
    "micro-habits you should steal",
    "nobody tells you",
    "the real problem with",
    "protocol:",
    " audit your",
    "triage checklist",
)

# legacy fallback patterns (если RAG-индекс отсутствует)
CURATED_HOOK_PATTERNS = (
    "%professor at Oxford%",
    "%disciplined isn't hard%",
    "%apologize better for repairing%",
    "%11 things people learn too late%",
)

# Ложные рефреймы вредных привычек (хвалить нельзя)
BANNED_FALSE_REFRAMES = (
    "it's actually brain training",
    "is actually brain training",
    "it's actually insight",
    "is actually insight",
    "is actually a reset",
    "it's actually a reset",
    "is actually self-care",
    "context switching isn't chaos, it's actually",
    "overthinking isn't waste, it's actually",
    "overthinking is actually insight",
    "multitasking is actually",
    "brain training",
)

BANNED_HOOK_PATTERNS = (
    re.compile(r"\b\d+\s+ways?\s+to\b", re.I),
    re.compile(r"\b\d+\s+habits?\s+to\b", re.I),
    re.compile(r"\b\d+\s+steps?\s+to\b", re.I),
    re.compile(r"\b\d+\s+rules?\s+to\b", re.I),
    re.compile(r"\ba\s+neuroscientist\s+taught\s+me\b", re.I),
    re.compile(r"^nobody\s+tells\s+you\b", re.I),
    re.compile(r"micro[- ]?habits you should steal", re.I),
    re.compile(
        r"to anyone whose brain completely shuts down at\s*\d+\s*pm",
        re.I,
    ),
)

QUERY_LEAK_PHRASES = (
    "english query",
    "search query",
    "search_query",
)

# Старые суффиксы — вычищать из ответов модели
QUERY_DUP_SUFFIXES = (
    "candid 35mm film",
    "candid shot on iphone 35mm film raw snapshot",
    "candid shot on iphone, 35mm film, raw lifestyle snapshot",
    "candid shot on iphone 35mm film",
    "35mm film photo",
    "authentic lifestyle photo",
)

# Legacy UGC-маркеры — больше НЕ дописываем к запросам (iphone ломал выдачу)
UGC_QUERY_MARKERS: tuple[str, ...] = ()

# Обратная совместимость: critic/batch могут импортировать QUERY_SUFFIX
QUERY_SUFFIX = "open journal pen"

# Абстрактные мудборд-фразы — навсегда вне search_query
BANNED_MOODBOARD_PHRASES: tuple[str, ...] = (
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
    "study aesthetic",
    "girl aesthetic",
    "aesthetic journaling",
    # Empty lifestyle fillers — look like stock, weak slide sense
    "wooden chair table",
    "wooden chair kitchen",
    "empty dining chair",
    "old books wooden",
    "notebook wooden chair",
    "aesthetic room",
    "minimalist interior",
)

BANNED_STOCK_QUERY_TERMS: tuple[str, ...] = (
    "editorial",
    "studio",
    "cinematic",
    "professional photoshoot",
    "magazine",
    "moody film still",
    "hyperrealistic",
    "concept art",
    "unreal engine",
    "35mm film",
    "candid 35mm film",
    "film still",
    "photoshoot",
    "stock photo",
    "stock image",
    "portrait",
    "headshot",
    "close up face",
    "close-up face",
    "face looking",
    "person staring",
    "looking stressed",
    "stressed face",
    "sad face",
    "angry face",
    "crying face",
    "person staring at screen",
    "face looking at phone",
    "man looking stressed",
    "woman looking stressed",
    "0.5x lens",
    "0.5x",
    "0,5x lens",
    "wallpaper",
    "gradient",
    "vector",
    "illustration",
    "photo dump",
    "shot on iphone",
    "girlhood",
    "bed rotting",
    *BANNED_MOODBOARD_PHRASES,
)

# Стоковые лица / corporate stress — бан (НЕ банить viral pose: staring phone, looking window)
BANNED_FACE_QUERY_PHRASES: tuple[str, ...] = (
    "person staring at screen",
    "face looking at phone",
    "man looking stressed",
    "woman looking stressed",
    "girl looking stressed",
    "looking stressed",
    "close up face",
    "close-up face",
    "face close up",
    "portrait of",
    "headshot",
    "stock photo",
    "stock image",
    "businessman",
    "businesswoman",
    "office worker stressed",
    "depressed person",
    "anxious person",
    "person crying",
    "woman crying",
    "man crying",
)

# Мёртвые неодушевленные кадры — навсегда вне запросов
# (НЕ банить ceiling/floor как часть human pose: lying bed staring ceiling)
BANNED_DEAD_OBJECT_PHRASES: tuple[str, ...] = (
    "lightbulb",
    "light bulb",
    "lamp glow floor",
    "sunset lamp",
    "blinds",
    "bare wall",
    "empty desk",
    "empty room",
    "empty kitchen",
    "bare room",
    "floor shadows",
    "lamp product",
    "product shot lamp",
    "hanging bulb",
    "exposed bulb",
    "only lamp",
    "just a lamp",
    "architectural corner",
    "empty corner",
)

# Улица / прогулка: бан фэшн-моделей — только POV (кофе в руках, ноги, витрины)
BANNED_FASHION_STREET_TERMS: tuple[str, ...] = (
    "coat",
    "outfit",
    "fashion",
    "street style",
    "streetstyle",
    "ootd",
    "model walk",
    "full body outfit",
    "lookbook",
    "trench coat",
    "wool coat",
)

# Кровать запрещена вне sleep-тем (strip, НЕ подмена стабом)
_BED_QUERY_WORDS: tuple[str, ...] = (
    "bed",
    "bedroom",
    "duvet",
    "sheets",
    "blanket",
)

_SLEEP_TOPIC_KEYS: tuple[str, ...] = (
    "sleep",
    "insomnia",
    "bedtime",
    "wake up",
    "waking",
    "can't sleep",
    "cant sleep",
    "oversleep",
    "nap ",
    " napping",
    "dream",
    "bed rotting",
    "morning routine sleep",
    "rest day sleep",
)

_SKIN_TOPIC_KEYS: tuple[str, ...] = (
    "skin",
    "beauty",
    "glow",
    "skincare",
    "serum",
    "makeup",
    "cleanser",
    "moisturizer",
    "vanity",
    "glass skin",
)

# Стоп-слова при выжимке search_query из visual_scene
_SCENE_QUERY_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "of", "on", "in", "at", "to", "for", "with", "and",
        "or", "as", "by", "from", "into", "onto", "over", "under", "near",
        "next", "beside", "against", "about", "around", "between", "their",
        "his", "her", "its", "this", "that", "these", "those", "some", "any",
        "very", "just", "also", "while", "where", "when", "who", "whom",
        "whose", "which", "what", "dim", "soft", "ambient", "natural",
        "warm", "cool", "bright", "harsh", "low", "high", "late", "early",
        "light", "lighting", "lights", "glow", "shadowy", "illuminated",
        "tired", "lonely", "sad", "anxious", "quiet", "empty", "young",
        "old", "alone", "someone", "somebody", "anyone", "people", "person",
        "figure", "human", "woman", "man", "girl", "boy", "guy", "lady",
        "candid", "aesthetic", "photo", "photograph", "frame", "shot",
        "camera", "lifestyle", "scene", "image", "picture", "view",
    }
)

_SCENE_STYLE_WORDS: frozenset[str] = frozenset({"candid", "aesthetic"})

# Поза / действие — маркеры human situation (для валидации, НЕ пул стабов)
_HUMAN_POSE_MARKERS: frozenset[str] = frozenset(
    {
        "sitting",
        "lying",
        "leaning",
        "walking",
        "pacing",
        "staring",
        "holding",
        "waiting",
        "looking",
        "hands",
        "head",
        "overwhelmed",
        "open",
        "packed",
        "clutching",
        "writing",
        "reading",
    }
)
_HUMAN_PLACE_MARKERS: frozenset[str] = frozenset(
    {
        "alone",
        "girl",
        "floor",
        "wall",
        "ceiling",
        "sidewalk",
        "steps",
        "shadow",
        "blurry",
        "dusk",
        "phone",
        "window",
        "desk",
        "bed",
        "room",
        "couch",
        "night",
        "dark",
        "outside",
        "kitchen",
        "suitcase",
        "laptop",
        "fridge",
        "table",
        "door",
        "chair",
    }
)
_HUMAN_SITUATION_MARKERS: frozenset[str] = _HUMAN_POSE_MARKERS | _HUMAN_PLACE_MARKERS

# Legacy aliases — пустые (стабы уничтожены; импорты не падают)
_ANXIETY_SITUATION_QUERIES: tuple[str, ...] = ()
_LONELY_SITUATION_QUERIES: tuple[str, ...] = ()
_NIGHT_SPIRAL_QUERIES: tuple[str, ...] = ()
_BREAKUP_SITUATION_QUERIES: tuple[str, ...] = ()
_OVERWHELM_SITUATION_QUERIES: tuple[str, ...] = ()
_SKINCARE_MOOD_QUERIES: tuple[str, ...] = ()
_RELATIONSHIP_MOOD_QUERIES: tuple[str, ...] = ()
_STUDY_MOOD_QUERIES: tuple[str, ...] = ()
_SLEEP_MOOD_QUERIES: tuple[str, ...] = ()
_NIGHT_MOOD_QUERIES: tuple[str, ...] = ()
_DAY_MOOD_QUERIES: tuple[str, ...] = ()


def extract_visual_scene_nouns(visual_scene: str, *, limit: int = 3) -> list[str]:
    """2–3 главных физических токена из visual_scene (для Pinterest query)."""
    words = re.findall(r"[A-Za-z]{3,}", visual_scene or "")
    out: list[str] = []
    seen: set[str] = set()
    for w in words:
        low = w.lower()
        if low in _SCENE_QUERY_STOPWORDS or low in _SCENE_STYLE_WORDS:
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(low)
        if len(out) >= limit:
            break
    return out


def search_query_from_visual_scene(
    visual_scene: str,
    *,
    style: str = "candid",
    topic: str = "",
) -> str:
    """
    search_query = сжатая выжимка visual_scene:
    2–3 физических слова + candid|aesthetic → строго 3–4 слова.
    """
    style_w = style.lower().strip() if style else "candid"
    if style_w not in _SCENE_STYLE_WORDS:
        style_w = "candid"

    scene = re.sub(r"\s+", " ", (visual_scene or "").strip())
    if topic and not _topic_allows_bed(topic):
        scene = _strip_bed_words(scene)

    nouns = extract_visual_scene_nouns(scene, limit=3)
    if not nouns:
        # слабый запас: любые длинные токены сцены
        raw = [
            w.lower()
            for w in re.findall(r"[A-Za-z]{4,}", scene)
            if w.lower() not in _SCENE_STYLE_WORDS
        ]
        nouns = []
        seen: set[str] = set()
        for w in raw:
            if w in seen:
                continue
            seen.add(w)
            nouns.append(w)
            if len(nouns) >= 2:
                break
    if not nouns:
        nouns = ["everyday", "indoor"]

    if len(nouns) >= 3:
        words = nouns[:3]
        # 3 существительных → + style = 4 слова
        q = " ".join(words + [style_w])
    elif len(nouns) == 2:
        q = f"{nouns[0]} {nouns[1]} {style_w}"
    else:
        q = f"{nouns[0]} scene {style_w}"

    # bed strip повторно на готовом запросе
    if topic and not _topic_allows_bed(topic) and _query_has_bed_words(q):
        q = _strip_bed_words(q)
        parts = [w for w in q.split() if w]
        if style_w not in parts:
            parts.append(style_w)
        while len(parts) < 3:
            parts.insert(0, "indoor")
        q = " ".join(parts[:4])
    return re.sub(r"\s+", " ", q).strip()


def query_shares_scene_nouns(query: str, visual_scene: str) -> bool:
    """
    True если search_query реально из visual_scene:
    все content-слова query ⊆ scene, ИЛИ ≥2 общих существительных.
    Одно общее слово (kitchen/floor) недостаточно — иначе стаб
    'fridge glow kitchen night' проходит мимо polaroid-сцены.
    """
    scene_nouns = set(extract_visual_scene_nouns(visual_scene, limit=12))
    if not scene_nouns:
        return bool(re.findall(r"[A-Za-z]{3,}", query or ""))
    q_words = {
        w
        for w in re.findall(r"[a-z]{3,}", (query or "").lower())
        if w not in _SCENE_STYLE_WORDS and w not in _SCENE_QUERY_STOPWORDS
    }
    if not q_words:
        return False
    overlap = q_words & scene_nouns
    if not overlap:
        return False
    if q_words <= scene_nouns:
        return True
    return len(overlap) >= 2


def align_search_query_to_scene(
    search_query: str,
    visual_scene: str,
    *,
    topic: str = "",
    index: int = 0,
) -> str:
    """
    Если query не пересекается с visual_scene — пересобрать из scene nouns.
    Никаких mood-стабов.
    """
    del index
    scene = re.sub(r"\s+", " ", (visual_scene or "").strip())
    q = re.sub(r"\s+", " ", (search_query or "").strip())

    # лёгкая чистка banned tails без подмены смысла
    for phrase in sorted(BANNED_MOODBOARD_PHRASES, key=len, reverse=True):
        q = re.sub(re.escape(phrase), " ", q, flags=re.I)
    q = re.sub(r"\b(iphone|finsta|35mm|snapshot|photo dump)\b", " ", q, flags=re.I)
    q = re.sub(r"\s+", " ", q).strip(" ,.-")

    if topic and not _topic_allows_bed(topic) and _query_has_bed_words(q):
        stripped = _strip_bed_words(q)
        if query_shares_scene_nouns(stripped, scene):
            q = stripped
        else:
            q = ""

    if scene and (not q or not query_shares_scene_nouns(q, scene)):
        rebuilt = search_query_from_visual_scene(scene, topic=topic)
        logger.warning(
            "search_query realigned to visual_scene: %r → %r (scene=%r)",
            search_query,
            rebuilt,
            scene[:80],
        )
        q = rebuilt

    if not q:
        q = search_query_from_visual_scene(scene or "everyday indoor scene", topic=topic)

    # clamp 3–4 words, preserve scene nouns
    parts = [w for w in q.split() if w]
    style = next((w for w in parts if w.lower() in _SCENE_STYLE_WORDS), "candid")
    core = [w for w in parts if w.lower() not in _SCENE_STYLE_WORDS]
    if len(core) > 3:
        core = core[:3]
    while len(core) < 2:
        core.append("indoor")
    if len(core) + 1 <= 4:
        q = " ".join(core + [style])
    else:
        q = " ".join(core[:3])
    return q


_RELATIONSHIP_TOPIC_KEYS: tuple[str, ...] = (
    "love",
    "relationship",
    "dating",
    "anxiety",
    "anxious",
    "text",
    "situationship",
    "boyfriend",
    "girlfriend",
    "breakup",
    "heartbreak",
    "attachment",
)

_STUDY_TOPIC_KEYS: tuple[str, ...] = (
    "study",
    "studying",
    "productivity",
    "productive",
    "desk",
    "library",
    "exam",
    "homework",
    "focus",
    "work",
    "career",
    "deep work",
    "procrastinat",
    "discipline",
)

# Конкретные предметы/локации слайда → нельзя подменять столом с книгами
_TANGIBLE_OBJECT_MAP: tuple[tuple[str, str], ...] = (
    ("chips", "chips snack bag"),
    ("chip bag", "chips snack bag"),
    ("crisps", "chips snack bag"),
    ("kitchen", "fridge open snack"),
    ("fridge", "fridge open snack"),
    ("refrigerator", "fridge open snack"),
    ("freezer", "fridge open snack"),
    ("pantry", "pantry snack shelf"),
    ("snack", "snack bag counter"),
    ("cereal", "cereal bowl kitchen"),
    ("pizza", "pizza box counter"),
    ("ice cream", "ice cream pint"),
    ("cookies", "cookies on plate"),
    ("noodles", "noodles bowl desk"),
    ("ramen", "ramen bowl desk"),
    ("coffee", "coffee mug laptop"),
    ("matcha", "matcha cup desk"),
    ("tea", "tea mug window"),
    ("wine", "wine glass table"),
    ("sneakers", "sneakers by door"),
    ("shoes", "shoes by door"),
    ("mirror", "gym mirror selfie shoes"),
    ("phone", "hands holding phone"),
    ("laptop", "coffee mug laptop"),
    ("car", "hands holding steering wheel"),
    ("steering", "hands holding steering wheel"),
    ("driving", "hands holding steering wheel"),
    ("keys", "keys on table"),
    ("journal", "open journal pen"),
    ("notebook", "open journal pen"),
    ("charger", "charger tangled desk"),
    ("door", "keys by door"),
    ("window", "rain on window"),
    ("gym", "gym mirror selfie shoes"),
    ("workout", "gym mirror selfie shoes"),
    ("serum", "hands applying serum"),
    ("skincare", "serum bottle sink"),
    ("sink", "bathroom sink splash"),
    ("vanity", "vanity mirror bottles"),
)

_STUDY_DESK_MARKERS: tuple[str, ...] = (
    "desk", "journal", "library", "bookstore", "notebook", "academia", "gilmore",
)

# Динамическая длина карусели (sweet spot: 6)
MIN_CAROUSEL_SLIDES = 6
MAX_CAROUSEL_SLIDES = 9

# Legacy 5-slot keys (fallback для старых ответов)
SLOT_KEYS = ("hook", "point_1", "point_2", "point_3", "cta")

WORD_NUM = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}

CTA_ACTION_WORDS = ("save", "send")

# Пустые / грамматически неверные CTA — принудительная замена
BANNED_EMPTY_CTAS = (
    "save this insight",
    "save this guide",
    "keep this list",
    "save this tip",
    "save this advice",
    "save this reminder",
    "save this trick",
    "save this hack",
    "save this productivity hack",
    "keep this mindset shift",
    "keep this guide",
    "save these tips",
    "save these tips for emotional healing",
    "keep this list to break free",
    "keep this list to prioritize",
    "save this tip for calm",
    "save this tip for next time",
    "save this tip to boost your focus",
    "save this moment of truth",
)

EMPTY_CTA_REPLACEMENT = (
    "Save this for the next time you're spiraling over a 10-minute task."
)

# Только две разрешённые грамматики
_CTA_SAVE_FOR_RE = re.compile(r"^save this for\b", re.I)
_CTA_SEND_TO_RE = re.compile(r"^send this to\b", re.I)
_CTA_SEND_FOR_RE = re.compile(r"^send this for\b", re.I)
_CTA_SEND_WHEN_RE = re.compile(r"^send this when\b", re.I)


@dataclass
class ViralExample:
    hook: str
    slides: list[str]
    niche: str
    save_rate: float
    bookmarks: int


@dataclass
class GeneratedSlide:
    text: str
    search_query: str
    role: str = "body"
    visual_scene: str = ""


class CharacterDNA(BaseModel):
    """
    Паспорт героя карусели — только базовые физические маркеры
    (волосы / кожа / возраст / телосложение) для query + SigLIP lock.
    Одинаковое лицо и одинаковый outfit НЕ требуются.
    """

    gender: Literal["female", "male"] = "female"
    hair: str = "long brown hair"
    style: str = "woman mid 20s, casual"
    skin_tone: str = "olive"
    build: str = "average"

    @field_validator("gender", mode="before")
    @classmethod
    def _norm_gender(cls, value: Any) -> str:
        raw = str(value or "female").strip().lower()
        if raw in {"male", "man", "guy", "boy", "m"}:
            return "male"
        return "female"

    @field_validator("hair", "style", "skin_tone", "build", mode="before")
    @classmethod
    def _strip_str(cls, value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip())[:80]


class GeminiApiKeyMissing(RuntimeError):
    """GEMINI_API_KEY не задан."""


# backward compat для carousel_factory / batch_factory
OllamaUnavailable = GeminiApiKeyMissing


class CarouselSlideItem(BaseModel):
    role: Literal["hook", "body", "cta"] = "body"
    text: str
    visual_scene: str = ""
    search_query: str = ""

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: Any) -> str:
        raw = str(value or "body").strip().lower()
        if raw in {"hook", "body", "cta"}:
            return raw
        if raw in {"point", "tip", "advice", "slide"}:
            return "body"
        return "body"


class CarouselSlidesSchema(BaseModel):
    character_dna: CharacterDNA = Field(default_factory=CharacterDNA)
    slides: list[CarouselSlideItem] = Field(
        min_length=MIN_CAROUSEL_SLIDES,
        max_length=MAX_CAROUSEL_SLIDES,
    )


# backward-compat alias
CarouselSlotsSchema = CarouselSlidesSchema


def _topic_implied_body_count(topic: str) -> int | None:
    """
    Если тема явно задаёт число советов ('7 habits', 'five rules') —
    вернуть N body-слайдов (1..7). Иначе None.
    """
    low = (topic or "").lower()
    # digit form: 7 habits / 5 rules / 6 steps / 8 ways / 9 signs
    m = re.search(
        r"\b([1-9])\s*(?:habits?|rules?|steps?|ways?|tips?|signs?|"
        r"things?|lessons?|secrets?|reasons?|shifts?|moves?|protocols?)\b",
        low,
    )
    if m:
        n = int(m.group(1))
        return max(1, min(7, n))
    # word form: seven habits
    m = re.search(
        r"\b(one|two|three|four|five|six|seven|eight|nine)\s+"
        r"(?:habits?|rules?|steps?|ways?|tips?|signs?|things?|lessons?|"
        r"secrets?|reasons?|shifts?|moves?|protocols?)\b",
        low,
    )
    if m:
        n = WORD_NUM.get(m.group(1), 0)
        if n:
            return max(1, min(7, n))
    return None


def _gemini_key_hint() -> str:
    return (
        "GEMINI_API_KEY не найден.\n"
        "Создайте файл .env в корне проекта:\n"
        "  GEMINI_API_KEY=your_key_here\n"
        "Или задайте переменную окружения GEMINI_API_KEY."
    )


def _ensure_api_key() -> str:
    load_dotenv(ROOT / ".env")
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key or key.lower() in {"your_key_here", "your-key-here", "changeme"}:
        raise GeminiApiKeyMissing(_gemini_key_hint())
    return key


def _clean_slide_text(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    if not s or s.upper() == "NONE":
        return ""
    if len(re.findall(r"[A-Za-zА-Яа-яЁё]", s)) < 8:
        return ""
    return s[:220]


def _hook_quality_ok(hook: str) -> bool:
    h = _clean_slide_text(hook)
    if len(h) < 18 or len(h) > 160:
        return False
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9']+", h)
    if len(words) < 5:
        return False
    garbage = ("trus yoir", "oa pe y", "film for thought", "banana pudding")
    low = h.lower()
    if any(g in low for g in garbage):
        return False
    return True


def load_curated_few_shot_examples(
    db_path: Path = DEFAULT_DB,
) -> list[ViralExample]:
    """Fallback: 3–4 статичных прецедента, если RAG-индекс ещё не собран."""
    if not db_path.is_file():
        return load_viral_examples(db_path, limit=FEW_SHOT_N)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    out: list[ViralExample] = []
    seen: set[str] = set()
    try:
        for pattern in CURATED_HOOK_PATTERNS:
            row = conn.execute(
                """
                SELECT niche, save_rate, bookmarks, real_hook, slides_text_json
                FROM viral_playbook
                WHERE real_hook LIKE ?
                  AND slides_text_json IS NOT NULL
                  AND length(trim(slides_text_json)) > 10
                ORDER BY bookmarks DESC
                LIMIT 1
                """,
                (pattern,),
            ).fetchone()
            if not row:
                continue
            try:
                texts = json.loads(row["slides_text_json"] or "[]")
            except json.JSONDecodeError:
                continue
            if not isinstance(texts, list):
                continue
            cleaned = [_clean_slide_text(str(t)) for t in texts]
            cleaned = [t for t in cleaned if t]
            if len(cleaned) < 2:
                continue
            hook = _clean_slide_text(str(row["real_hook"] or "")) or cleaned[0]
            if not _hook_quality_ok(hook):
                continue
            key = hook.lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            slides = [hook] + [t for t in cleaned if t.lower() != hook.lower()]
            out.append(
                ViralExample(
                    hook=hook,
                    slides=slides[:MAX_EXAMPLE_SLIDES],
                    niche=str(row["niche"] or ""),
                    save_rate=float(row["save_rate"] or 0),
                    bookmarks=int(row["bookmarks"] or 0),
                )
            )
    finally:
        conn.close()

    if len(out) < FEW_SHOT_N:
        for ex in load_viral_examples(db_path, limit=FEW_SHOT_N * 2):
            key = ex.hook.lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            out.append(ex)
            if len(out) >= FEW_SHOT_N:
                break
    return out[:FEW_SHOT_N]


def _dicts_to_viral_examples(rows: list[dict[str, Any]]) -> list[ViralExample]:
    out: list[ViralExample] = []
    for row in rows:
        hook = _clean_slide_text(str(row.get("hook") or ""))
        raw_slides = row.get("slides") or row.get("slides_text") or []
        slides = [_clean_slide_text(str(t)) for t in raw_slides]
        slides = [t for t in slides if t]
        if hook and (not slides or slides[0].lower() != hook.lower()):
            slides = [hook] + [s for s in slides if s.lower() != hook.lower()]
        if not slides:
            continue
        if not hook:
            hook = slides[0]
        out.append(
            ViralExample(
                hook=hook,
                slides=slides[:MAX_EXAMPLE_SLIDES],
                niche=str(row.get("niche") or ""),
                save_rate=float(row.get("save_rate") or 0),
                bookmarks=int(row.get("bookmarks") or 0),
            )
        )
    return out


def load_rag_few_shot_examples(
    topic: str,
    niche: str = "",
    *,
    top_k: int = FEW_SHOT_N,
    db_path: Path = DEFAULT_DB,
) -> list[ViralExample]:
    """
    Динамический few-shot из всей базы viral_playbook (локальный FastEmbed RAG).
    Если индекса нет — мягкий fallback на curated.
    """
    topic = (topic or "").strip()
    try:
        from core.rag_retriever import get_retriever

        retriever = get_retriever()
        if retriever.available():
            rows = retriever.get_top_examples(topic, niche=niche, top_k=top_k)
            examples = _dicts_to_viral_examples(rows)
            if examples:
                logger.info(
                    "RAG few-shot: %d examples for topic=%r (top sim=%.3f)",
                    len(examples),
                    topic[:60],
                    float(rows[0].get("similarity") or 0),
                )
                return examples[:top_k]
    except Exception as exc:
        logger.warning("RAG retriever failed (%s) — curated fallback", exc)

    logger.info("RAG index missing/empty — curated few-shot fallback")
    return load_curated_few_shot_examples(db_path)



def load_viral_examples(
    db_path: Path = DEFAULT_DB,
    limit: int = FEW_SHOT_N,
) -> list[ViralExample]:
    """Топ вирусных прецедентов с реальным OCR-хуком (высокий save rate)."""
    if not db_path.is_file():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT niche, save_rate, bookmarks, real_hook, slides_text_json
            FROM viral_playbook
            WHERE slides_text_json IS NOT NULL
              AND length(trim(slides_text_json)) > 10
            ORDER BY
              CASE
                WHEN lower(coalesce(niche, '')) IN ({niches}) THEN 0
                ELSE 1
              END,
              save_rate DESC,
              bookmarks DESC
            LIMIT 80
            """.format(niches=",".join("?" * len(PREFERRED_NICHES))),
            PREFERRED_NICHES,
        ).fetchall()
    finally:
        conn.close()

    out: list[ViralExample] = []
    seen_hooks: set[str] = set()
    for row in rows:
        try:
            texts = json.loads(row["slides_text_json"] or "[]")
        except json.JSONDecodeError:
            continue
        if not isinstance(texts, list):
            continue
        cleaned = [_clean_slide_text(str(t)) for t in texts]
        cleaned = [t for t in cleaned if t]
        if len(cleaned) < 2:
            continue
        hook = _clean_slide_text(str(row["real_hook"] or "")) or cleaned[0]
        if not _hook_quality_ok(hook):
            continue
        key = hook.lower()[:80]
        if key in seen_hooks:
            continue
        seen_hooks.add(key)
        slides = [hook] + [t for t in cleaned if t.lower() != hook.lower()]
        out.append(
            ViralExample(
                hook=hook,
                slides=slides[:MAX_EXAMPLE_SLIDES],
                niche=str(row["niche"] or ""),
                save_rate=float(row["save_rate"] or 0),
                bookmarks=int(row["bookmarks"] or 0),
            )
        )
        if len(out) >= limit:
            break
    return out


def format_few_shot_block(examples: list[ViralExample]) -> str:
    if not examples:
        return "(no local precedents yet — invent sharp, specific English copy)"

    chunks: list[str] = []
    for i, ex in enumerate(examples, 1):
        slides = ex.slides[:MAX_EXAMPLE_SLIDES]
        body_lines = [f"  1. {slides[0]}"]
        for j, t in enumerate(slides[1:], 2):
            short = t if len(t) <= 90 else t[:87] + "…"
            body_lines.append(f"  {j}. {short}")
        block = (
            f"EX{i} [{ex.niche or 'general'} · {ex.bookmarks // 1000}k saves]: "
            f"{ex.hook}\n"
            + "\n".join(body_lines)
        )
        if len(block) > MAX_EXAMPLE_CHARS:
            block = block[: MAX_EXAMPLE_CHARS - 1] + "…"
        chunks.append(block)
    return "\n\n".join(chunks)


HOOK_ARCHETYPES = (
    "A",  # personal confession / absurd self-truth
    "B",  # self-aware punchline about a fictional better self
    "C",  # specific spiraling moment (texts, tasks, people-pleasing)
    "D",  # quiet shame → blunt honesty
)

BANNED_CTAS = (
    "save this for tomorrow morning",
)

_CTA_FALLBACKS = (
    "Save this for the next time you're spiraling over a 10-minute task.",
    "Send this to someone who tries to do everyone's job.",
    "Save this for when you need to hear that resting isn't failing.",
    "Save this for the next time you rewrite the same email five times.",
    "Send this to someone who volunteers for everything then burns out.",
    "Save this for when your brain turns a small task into a moral crisis.",
)


def build_system_prompt(examples: list[ViralExample]) -> str:
    few = format_few_shot_block(examples)
    banned = ", ".join(f'"{b}"' for b in BANNED_GENERIC)
    coach = ", ".join(f'"{b}"' for b in BANNED_COACH_PHRASES)
    robot = ", ".join(f'"{b}"' for b in BANNED_ROBOT_VOICE)
    toolkit = ", ".join(f'"{b}"' for b in BANNED_UNIVERSAL_TOOLKIT)
    stamps = ", ".join(f'"{b}"' for b in BANNED_HOOK_STAMPS)
    return f"""You are a TikTok/Instagram carousel writer with a living human voice.
You sound like a tired, honest millennial/Gen-Z creator who keeps stepping on the same rakes —
NOT a consultant, coach, therapist, or productivity guru on a stage.
Output ONLY valid JSON. No markdown. No commentary.

LANGUAGE: All fields MUST be fluent conversational American English. Zero Russian.
Use natural glue where it fits: "turns out", "honestly", "apparently", "the truth is", "so basically".
No corporate speak. No lecture tone. No textbook advice voice.

VOICE = Relatable Confession & Self-Awareness:
- First person or second person that feels lived-in ("I…", "You…", "we pretend…").
- Vulnerable, specific, a little embarrassed — never motivational-poster energy.
- Short punches > long frameworks.

=== FEW-SHOT EXAMPLES (retrieved from viral_playbook by topic similarity) ===
{few}
=== END FEW-SHOT EXAMPLES ===
Use precedents for rhythm/structure ONLY. Rewrite into the confession voice above —
do NOT copy robotic coach phrasing even if an example uses it.

FIXED STRUCTURE — dynamic JSON (character passport + slides 6–9):
{{
  "character_dna": {{
    "gender": "female",
    "hair": "long brown hair",
    "style": "woman mid 20s, casual",
    "skin_tone": "olive",
    "build": "slim"
  }},
  "slides": [
    {{"role": "hook", "text": "...", "visual_scene": "...", "search_query": "..."}},
    {{"role": "body", "text": "...", "visual_scene": "...", "search_query": "..."}},
    {{"role": "body", "text": "...", "visual_scene": "...", "search_query": "..."}},
    {{"role": "cta", "text": "...", "visual_scene": "...", "search_query": "..."}}
  ]
}}

=== CHARACTER DNA (passport — REQUIRED) ===
- character_dna MUST be filled once for the whole carousel BEFORE writing slides.
- Lock ONLY coarse physical traits — NOT the same face, NOT the same outfit.
  What must stay stable: hair color+length, skin_tone, approximate age band, build.
  Outfit / clothes / jewelry / nails can change freely between slides.
- gender: "female" or "male" (match the first-person narrator of THIS topic).
- hair: concrete, searchable — VARY across carousels. Examples of VALID looks
  (pick ONE, do NOT default to blonde):
  "long brown hair", "long dark curly hair", "long black hair",
  "shoulder length auburn hair", "wavy light brown hair",
  "short dark hair", "long ginger hair", "long blonde hair".
- style: age band + vibe (e.g. "woman mid 20s, casual", "woman early 30s, casual").
- skin_tone: fair / light / medium / olive / brown / deep — vary; do not always use fair.
- build: slim / average / athletic / soft — one word.
- NEVER copy the JSON example's hair/skin blindly. Stereotype "long blonde + fair"
  is ALLOWED only when the topic itself mentions blonde/blond — otherwise prefer
  brown / dark / black / auburn / ginger / light brown.

=== CHARACTER DNA → search_query inheritance ===
- DNA hair/gender/age are for CONSISTENCY LOCKS after download — NOT for Pinterest.
- NEVER put hair color / girl / guy / blonde / brunette into search_query.
- search_query must name the CONFESSION PROP + place + optional action
  (pantry, fridge, pasta bowl, food scale, plate of food, gym bag…).
- Slide 1 MAY show a person in visual_scene, but search_query still searches the SCENE
  (e.g. "open pantry night"), not the passport photo.
- Slides 2..N: POV / hands / objects / rooms — still scene nouns, not DNA casting.
- Pure environment may omit people, but MUST NOT show a person whose hair color
  clashes with DNA (enforced by attr-lock, not by stuffing hair into the query).

LENGTH RULES:
- Slide 1 MUST be role="hook". Final slide MUST be role="cta".
- Middle slides MUST be role="body" (punchy insights, not protocols).
- If the topic states an explicit number (e.g. "7 habits", "5 rules", "6 steps"):
  produce exactly 1 hook + exactly N body slides + 1 CTA
  (total = N+2, clamped to 6–9).
- If the topic has NO number: choose 6–8 total slides
  (hook + 4–6 body + cta). Prefer 6. Never exceed 9. Never go below 6.

=== SLIDE STRUCTURE: CONFESSION → PUNCHLINE → TRUTH ===

HOOK (slide 1) — personal observation or absurd self-truth about THIS topic:
Shape: a lived moment, a spiral, or a shameful little math problem — not a named system.
Good shapes:
- "I avoided one simple task for 3 weeks. It took me 18 minutes to finish."
- "My boss texted 'can we talk?' and I spent 6 hours preparing to get fired."
- "I realized half my workload was stuff I volunteered for just so people would like me."
- "You don't hate Mondays. You hate plans made for a fictional version of yourself."
Rotate styles (pick ONE):
1) Personal Confession — specific time/cost/action you (or "you") wasted (~35%)
2) Spiral Moment — an overreaction to a tiny trigger (~30%)
3) Self-Awareness Punch — calling out the fake better self (~25%)
4) Quiet Shame → Honesty — soft setup, sharp ending (~10%)
FORBIDDEN hook styles: "The [Name] protocol/rule/checklist", "Audit your…",
"N ways/habits/steps/rules to…", "Nobody tells you…", "A neuroscientist taught me…",
"Micro-habits you should steal…", screenshot-checklist default stamps.

BODY (slides 2–4+) — short forehead-punch insights, NO fancy terms:
Aim for 8–18 words. One or two complete sentences. End with a period.
Good shapes:
- "Perfectionism is just procrastination wearing a nice outfit."
- "You're preparing to work instead of actually working."
- "Would you talk to a friend the way you talk to yourself when you fail? No. So stop."
- "You don't need a better planner. You need permission to leave things unfinished."
Rules:
- Insight > instruction. Permission > protocol. Observation > lecture.
- Prefer "honestly / turns out / the truth is / so basically" over imperative coach verbs.
- FORBIDDEN openers & jargon: Audit, Define, Protocol, Triage, Optimize, Sensory reset,
  cognitive performance, checklist-as-identity.
- TAB ADVICE: "Close browser tabs" ONLY if the topic is literally about tabs / context switching.
- FORBIDDEN universal toolkit: {toolkit}
- FORBIDDEN coach fluff: {coach}
- FORBIDDEN robot-consultant lexicon: {robot}
- FORBIDDEN generic filler: {banned}
- NEVER reframe harmful habits as "actually brain training / self-care / a reset".
- TIME CONTEXT: afternoon-crash topics → afternoon truth only (no morning ritual spam).

CTA (final slide) — warm, low-drama call to action:
ONLY these two grammars:
1) "Save this for [specific spiral / moment]"
2) "Send this to [specific person type]"
Good shapes:
- "Save this for the next time you're spiraling over a 10-minute task."
- "Send this to someone who tries to do everyone's job."
- "Save this for when you need to hear that resting isn't failing."
FORBIDDEN: "Send this for when…", "Send this when…", "Keep this…", "Share this…",
"Save this insight/tip/guide/hack", "Save this for tomorrow morning",
anything that sounds like a corporate closing slide.

=== CHARACTER CONSISTENCY RULE (First-person narrative) ===
- Slide 1 (Hook): Allowed to show the person / silhouette / mirror selfie to establish identity.
- Slides 2, 3, 4, 5… (Body + CTA): STRICTLY FORBIDDEN to show other human faces!
  Body/CTA slides MUST be 100% POV (Point of View), hands, objects, shoes, environment,
  or back-of-head only!
  Example visual_scene / search_query energy:
  "hands holding notebook", "feet walking pavement", "coffee cup window", "closed door".
  NEVER introduce a new different person's face mid-carousel!
- visual_scene on slides 2+: NEVER a second person's face, portrait, or stranger selfie.
  Prefer hands, feet, desk objects, rooms, streets, food, screens — no other faces.

TOPIC RELEVANCE: Hook + body MUST be uniquely synthesized from THIS topic's nouns.
NEVER reuse fixed catchphrases. NEVER copy example lines from this prompt.
Forbidden clone phrases: {stamps}

NUMERIC ACCURACY: If the topic mentions "2-minute rule" / "two-minute rule", NEVER mention "2pm"
or afternoon slump. Stay on short 2-minute friction.

=== PINTEREST SEARCH QUERY + VISUAL_SCENE (camera bridge) ===
Each slide MUST include BOTH:
  text          — what the reader reads (metaphor / confession OK)
  visual_scene  — what a CAMERA would physically see (REQUIRED)
  search_query  — 3–4 Pinterest words derived from visual_scene, NOT from metaphors

visual_scene rules (philosophy → vision bridge):
- Describe a REAL PHYSICAL FRAME: who/what, where, posture/action, light.
- Example shape: "person standing at open pantry at night, hand in snack bag, dim light"
- Slide 1 MAY include the narrator as silhouette / back / hands — NEVER hair color casting.
- FORBIDDEN in visual_scene: DNA casting (blonde/brunette/auburn/ginger/black hair,
  girl/guy/woman with [hair], shoulder-length hair). Hair/gender live in character_dna only.
- Slides 2+: MUST be POV / hands / objects / shoes / room / street — NEVER another face.
- FORBIDDEN in visual_scene: quotes, abstract nouns alone (sadness, healing, triggers),
  motivational slogans, product slogans.
- visual_scene is the SigLIP relevance anchor — it must match photographable objects.
- NEVER describe dirt: no dirty dishes, food waste, crumbs, trash, garbage, wrappers
  everywhere, spilled drinks, greasy pans, messy counters. Show the SAME moment cleanly
  (a snack bag on a tidy table, an open fridge, a plate of food, a mug by a window).
- If text names pretzels/chips as a BAG snack, scene must show a snack bag — NOT a
  soft street pretzel / Christmas market pretzel.

search_query rules:
- Exactly 3–4 words. MUST be a compressed extract of THIS slide's visual_scene
  OR the concrete props named in the slide text (salad, pantry, pasta, sink…).
- Formula: [action/state] + [prop] + [place]  (optional candid last).
- Examples:
  text about midnight pantry binge → "open pantry night"
  text about cold pasta over sink → "pasta bowl kitchen"
  text about counting almonds → "almonds handful desk"
  text about stale pretzels bag → "pretzel chips bag night" (NOT bare "pretzels")
  visual_scene "open suitcase on bedroom floor with clothes"
    → search_query "open suitcase floor candid"
- NEVER invent a query that does not share nouns with visual_scene OR slide props.
- NEVER put DNA casting in search_query: no blonde/brunette/ginger/girl/guy/hair.
- NEVER copy, recycle, or rotate a fixed phrase bank across slides/topics.
- Do NOT reuse the same 3–4 word query on more than one slide in this carousel.
- FORBIDDEN literal abstract→object from metaphors
  ('spark'≠coffee, 'analyzed'≠notebook) — but LITERAL props in the text ARE required
  (if text says pantry/fridge/pasta/scale, the query MUST include that prop).
- HARD BAN: iphone / finsta / snapshot / 35mm / photo dump / moodboard-only
  ("cozy aesthetic", "dark academia", "aesthetic night").
- phone ONLY if visual_scene is literally about waiting/texting/doomscroll.
- candid|aesthetic ONLY as optional last word — never alone.
- BAN filler-only queries: "hands candid", "feet sneakers floor", "closed door candid"
  unless the slide text literally is about hands/feet/door.

=== NO LITERAL OBJECT MATCHING ===
Never map slide vocabulary → desk props by keyword.
Psychology / relationships → invent a fresh physical scene each time via visual_scene.

PRODUCT RULE:
- Mention a product ONLY if the user message explicitly names one.
- If no product is named, invent ZERO app/tool/product names.
- If a product is named, weave it into ONE body slide only — never the hook or CTA —
  like a personal habit, not an ad."""



def build_user_prompt(
    topic: str,
    product_name: str = "",
    variation_index: int = 0,
    archetype_hint: str = "",
    avoid_character_looks: list[str] | None = None,
) -> str:
    topic = topic.strip()
    product = product_name.strip()
    style = HOOK_ARCHETYPES[variation_index % len(HOOK_ARCHETYPES)]
    style_hint = {
        "A": (
            "HOOK STYLE A (Personal Confession) — a specific thing YOU avoided / overdid / "
            "volunteered for, with a concrete time cost or awkward math. Lived-in, a little ashamed."
        ),
        "B": (
            "HOOK STYLE B (Self-Awareness Punch) — call out the fictional better self / fake plans. "
            "Example energy: 'You don't hate Mondays. You hate plans made for a fictional you.'"
        ),
        "C": (
            "HOOK STYLE C (Spiral Moment) — one tiny trigger that blew into a 6-hour panic "
            "(a text, a task, a meeting invite). Specific to THIS topic."
        ),
        "D": (
            "HOOK STYLE D (Quiet Shame → Honesty) — soft setup, then a blunt true sentence. "
            "No named protocols, no checklists, no 'Audit your…'."
        ),
    }[style]

    implied_bodies = _topic_implied_body_count(topic)
    if implied_bodies is not None:
        total = max(MIN_CAROUSEL_SLIDES, min(MAX_CAROUSEL_SLIDES, implied_bodies + 2))
        length_hint = (
            f"LENGTH: topic implies {implied_bodies} tips → "
            f"exactly 1 hook + {implied_bodies} body + 1 CTA "
            f"(total {implied_bodies + 2} slides, clamp to {total} if needed)."
        )
    else:
        length_hint = (
            "LENGTH: no explicit number in topic — choose 6–8 total slides "
            "(hook + 4–6 body + cta) for depth. Prefer 6. Max 9."
        )

    lines = [
        f"TOPIC: {topic}",
        f"VARIATION: #{variation_index + 1}",
        style_hint,
        "VOICE: tired honest human — confession → punchline → truth. Not a robot consultant.",
        "TOPIC RELEVANCE: synthesize from this topic's nouns. Never reuse fixed catchphrases.",
        length_hint,
        "",
        "Return JSON with a slides[] array now (6–9 items).",
        'First slide role="hook", middle role="body", last role="cta".',
        "Hook: personal/absurd self-truth. Never 'The X protocol/rule/checklist'. Never Audit/Define.",
        "Body: short forehead-punch insights (8–18 words). Complete sentences with periods.",
        "Body language: turns out / honestly / apparently / the truth is / so basically — not coach verbs.",
        "CHARACTER LOCK: coarse traits only (hair color, skin, age band, build). "
        "Same face / same outfit NOT required. Slide 1 may show narrator; "
        "slides 2+ prefer POV/hands/objects — no clashing hair color on any person.",
        "REQUIRED top-level character_dna: gender, hair, style, skin_tone, build — "
        "VARY hair/skin across carousels (do NOT default to long blonde + fair). "
        "DNA is for post-download locks ONLY — NEVER put hair/girl/guy into search_query.",
        "Ban: protocol, audit your, triage checklist, cognitive performance, optimize output, sensory reset.",
        "Do not use 'close tabs' unless topic is context switching.",
        'CTA grammar ONLY: "Save this for …" OR "Send this to …" — warm, specific, zero corporate close.',
        "search_query: 3–4 words = [action] + [confession PROP] + [place]. "
        "If text says pantry/pasta/fridge/almonds/scale — those words MUST be in the query. "
        "ALSO required: visual_scene = physical camera frame "
        "(who/where/pose/light) — NOT a metaphor quote. "
        "CRITICAL: every slide MUST have a UNIQUE search_query. "
        "FORBIDDEN DNA casting queries: 'blonde hair girl', 'hands girl black hair', "
        "'ginger hair bathroom'. "
        "FORBIDDEN filler-only: hands candid / feet sneakers / closed door — "
        "unless the slide text is literally about that. "
        "FORBIDDEN: literal abstract→object, iphone/finsta/35mm, moodboard-only.",
    ]

    if archetype_hint:
        lines.insert(2, archetype_hint)

    if product:
        lines.insert(
            3,
            (
                f'PRODUCT (optional native weave into ONE body slide only): "{product}". '
                "Make it feel like a personal practice, not an ad. No buy-now / link-in-bio."
            ),
        )
    else:
        lines.insert(
            3,
            "NO PRODUCT: do not invent or name any app, tool, brand, or product.",
        )

    if _topic_is_two_minute_rule(topic):
        lines.append(
            '2-MINUTE RULE TOPIC: NEVER mention "2pm" or afternoon slump in hook or slides. '
            "Focus strictly on 2-minute micro-task friction / avoidance."
        )

    avoided = [a.strip() for a in (avoid_character_looks or []) if a and str(a).strip()]
    if avoided:
        lines.append(
            "DNA DIVERSITY: do NOT reuse these already-used looks from earlier carousels "
            "in this run: "
            + "; ".join(avoided[:8])
            + ". Pick a clearly different hair color family and/or skin_tone."
        )
    else:
        lines.append(
            "DNA DIVERSITY: prefer non-blonde looks unless the topic itself says blonde/blond."
        )

    return "\n".join(lines)



def _call_gemini_json(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    timeout: float,
) -> dict[str, Any]:
    """Gemini generateContent со strict JSON (response_schema)."""
    from core.usage_meter import (
        estimate_tokens,
        extract_usage_from_sdk,
        record_gemini,
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
                response_mime_type="application/json",
                response_schema=CarouselSlidesSchema,
                system_instruction=system_prompt,
            ),
        )
    except Exception as exc:
        raise RuntimeError(f"Gemini API error: {exc}") from exc

    inp, out, est = extract_usage_from_sdk(response)
    if est or (inp == 0 and out == 0):
        inp = estimate_tokens(system_prompt) + estimate_tokens(user_prompt)
        out = estimate_tokens(response.text or "")
        est = True
    record_gemini(
        kind="gemini_text_gen",
        model=model,
        input_tokens=inp,
        output_tokens=out,
        note="generate_carousel",
        estimated=est,
    )

    parsed = response.parsed
    if isinstance(parsed, CarouselSlidesSchema):
        return parsed.model_dump()
    if isinstance(parsed, BaseModel):
        return parsed.model_dump()
    raw = response.text or ""
    if not raw:
        raise RuntimeError("Gemini вернул пустой ответ")
    data = _parse_carousel_json(raw)
    return data


def _call_gemini_json_httpx(
    *,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    timeout: float,
) -> dict[str, Any]:
    """Fallback: прямой REST к Google AI Studio."""
    from core.usage_meter import (
        estimate_tokens,
        extract_usage_from_http,
        record_gemini,
    )

    url = f"{GEMINI_API_BASE}?key={api_key}"
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
            "responseMimeType": "application/json",
            # responseJsonSchema понимает $defs/$ref из pydantic (responseSchema — нет → HTTP 400)
            "responseJsonSchema": CarouselSlidesSchema.model_json_schema(),
        },
    }
    try:
        r = httpx.post(url, json=payload, timeout=timeout)
    except httpx.RequestError as exc:
        raise RuntimeError(f"Gemini HTTP error: {exc}") from exc
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:400]}")
    data = r.json()
    parts = (
        ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")
        or []
    )
    text = "".join(str(p.get("text") or "") for p in parts)
    if not text:
        raise RuntimeError(f"Gemini пустой ответ: {json.dumps(data)[:400]}")

    inp, out, est = extract_usage_from_http(data)
    if est or (inp == 0 and out == 0):
        inp = estimate_tokens(system_prompt) + estimate_tokens(user_prompt)
        out = estimate_tokens(text)
        est = True
    record_gemini(
        kind="gemini_text_gen",
        model=DEFAULT_GEMINI_MODEL,
        input_tokens=inp,
        output_tokens=out,
        note="generate_carousel_httpx",
        estimated=est,
    )
    return _parse_carousel_json(text)


class OllamaGenerator:
    """Генератор карусели через Gemini (имя класса сохранено для совместимости)."""

    def __init__(
        self,
        model: str = DEFAULT_GEMINI_MODEL,
        timeout: float = 120.0,
        db_path: Path | None = None,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.db_path = Path(db_path) if db_path else DEFAULT_DB
        self._api_key = (api_key or "").strip() or None
        self._examples = load_curated_few_shot_examples(self.db_path)
        self._system_prompt = build_system_prompt(self._examples)
        self._rag_source = "curated_fallback"

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def examples(self) -> list[ViralExample]:
        return self._examples

    def reload_examples(self, topic: str = "", niche: str = "") -> list[ViralExample]:
        """Подтянуть few-shot под тему (RAG) или fallback curated."""
        topic = (topic or "").strip()
        if topic:
            try:
                from core.rag_retriever import get_retriever

                if get_retriever().available():
                    self._examples = load_rag_few_shot_examples(
                        topic, niche=niche, db_path=self.db_path
                    )
                    self._rag_source = "rag"
                else:
                    self._examples = load_curated_few_shot_examples(self.db_path)
                    self._rag_source = "curated_fallback"
            except Exception:
                self._examples = load_curated_few_shot_examples(self.db_path)
                self._rag_source = "curated_fallback"
        else:
            self._examples = load_curated_few_shot_examples(self.db_path)
            self._rag_source = "curated_fallback"
        self._system_prompt = build_system_prompt(self._examples)
        return self._examples

    def _api_key_or_raise(self) -> str:
        if self._api_key:
            return self._api_key
        return _ensure_api_key()

    def is_available(self) -> bool:
        try:
            self._api_key_or_raise()
            return True
        except GeminiApiKeyMissing:
            return False

    def list_models(self) -> list[str]:
        return [self.model]

    def resolve_model(self) -> str:
        return self.model

    def generate_carousel(
        self,
        topic: str,
        product_name: str = "",
        variation_index: int = 0,
        niche: str = "",
        *,
        run_critic: bool = False,
        avoid_character_dnas: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        topic = (topic or "").strip()
        if not topic:
            raise ValueError("Тема карусели пустая")

        api_key = self._api_key_or_raise()
        examples = self.reload_examples(topic=topic, niche=niche)
        product = (product_name or "").strip()
        temperature = 0.75 + min(0.15, 0.02 * variation_index)

        from core.archetypes import archetype_prompt_hint, select_archetype

        avoid_families = {
            _hair_color_family(str(d.get("hair") or ""))
            for d in (avoid_character_dnas or [])
            if isinstance(d, dict)
        }
        avoid_families.discard("other")
        avoid_looks = []
        for d in avoid_character_dnas or []:
            if not isinstance(d, dict):
                continue
            bit = ", ".join(
                x
                for x in (
                    str(d.get("hair") or "").strip(),
                    str(d.get("skin_tone") or "").strip(),
                    str(d.get("build") or "").strip(),
                )
                if x
            )
            if bit:
                avoid_looks.append(bit)

        archetype = select_archetype(topic)
        arch_hint = archetype_prompt_hint(archetype)
        user_prompt = build_user_prompt(
            topic,
            product,
            variation_index=variation_index,
            archetype_hint=arch_hint,
            avoid_character_looks=avoid_looks,
        )
        system_prompt = build_system_prompt(examples)

        try:
            parsed = _call_gemini_json(
                api_key=api_key,
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                timeout=self.timeout,
            )
        except RuntimeError as sdk_exc:
            try:
                parsed = _call_gemini_json_httpx(
                    api_key=api_key,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    timeout=self.timeout,
                )
            except RuntimeError as http_exc:
                raise RuntimeError(f"{sdk_exc} | REST fallback: {http_exc}") from http_exc

        character_dna = sanitize_character_dna(
            parsed.get("character_dna") if isinstance(parsed, dict) else None,
            topic=topic,
            variation_index=variation_index,
            avoid_families=avoid_families,
        )
        slides = sanitize_and_slots_to_slides(
            parsed,
            product=product,
            topic=topic,
            character_dna=character_dna,
        )
        slides = diversify_cta(slides, seed=variation_index)

        slide_dicts = [
            {
                "role": s.role,
                "text": s.text,
                "visual_scene": s.visual_scene,
                "search_query": s.search_query,
            }
            for s in slides
        ]
        critic_meta: dict[str, Any] = {
            "score": None,
            "archetype": (archetype or {}).get("name"),
            "rewritten": False,
            "source": None,
        }
        if run_critic:
            try:
                from core.critic_engine import CarouselCritic

                critic = CarouselCritic()
                slide_dicts, verdict = critic.review(topic, slide_dicts)
                critic_meta = {
                    "score": verdict.score,
                    "needs_rewrite": verdict.needs_rewrite,
                    "flaw_slide": verdict.flaw_slide,
                    "fix_instruction": verdict.fix_instruction,
                    "rewritten": verdict.rewritten,
                    "source": verdict.source,
                    "lint_penalty": verdict.lint_penalty,
                    "archetype": (archetype or {}).get("name"),
                    "archetype_id": (archetype or {}).get("id"),
                    "archetype_match": (archetype or {}).get("match_score"),
                }
            except Exception as exc:
                logger.warning("Critic skipped: %s", exc)
                critic_meta["error"] = str(exc)

        logger.info(
            "character_dna locked: gender=%s hair=%r skin=%r build=%r style=%r",
            character_dna.get("gender"),
            character_dna.get("hair"),
            character_dna.get("skin_tone"),
            character_dna.get("build"),
            character_dna.get("style"),
        )
        return {
            "model": self.model,
            "provider": "gemini",
            "topic": topic,
            "product_name": product,
            "few_shot_count": len(examples),
            "few_shot_source": self._rag_source,
            "few_shot_hooks": [e.hook for e in examples],
            "hook_archetype": HOOK_ARCHETYPES[variation_index % len(HOOK_ARCHETYPES)],
            "dna_archetype": (archetype or {}).get("name"),
            "character_dna": character_dna,
            "quality": critic_meta,
            "slides": slide_dicts,
        }


# явный алиас
GeminiGenerator = OllamaGenerator


def _extract_json_object(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _parse_carousel_json(content: str) -> dict[str, Any]:
    raw = _extract_json_object(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Модель вернула невалидный JSON: {exc}\n---\n{content[:500]}"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError("Ожидался JSON-объект со slides[]")
    return data


def _has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text or ""))


def _looks_like_cta(text: str) -> bool:
    return _cta_grammar_ok(text)


def _cta_grammar_ok(text: str) -> bool:
    """Разрешены только: 'Save this for …' или 'Send this to …'."""
    t = (text or "").strip()
    if not t:
        return False
    if _CTA_SEND_FOR_RE.match(t) or _CTA_SEND_WHEN_RE.match(t):
        return False
    return bool(_CTA_SAVE_FOR_RE.match(t) or _CTA_SEND_TO_RE.match(t))


def _fix_cta_grammar(text: str, seed: int = 0) -> str:
    """Починить или заменить CTA под две разрешённые грамматики."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if _cta_grammar_ok(t):
        return t
    # Send this for/when … → Save this for …
    m = re.match(r"^send this for\s+(.+)$", t, flags=re.I)
    if m:
        fixed = f"Save this for {m.group(1).strip()}".rstrip(".")
        if _cta_grammar_ok(fixed):
            return fixed
    m = re.match(r"^send this when\s+(.+)$", t, flags=re.I)
    if m:
        fixed = f"Save this for when {m.group(1).strip()}".rstrip(".")
        if _cta_grammar_ok(fixed):
            return fixed
    # Keep/Share this for … → Save this for …
    m = re.match(r"^(?:keep|share) this for\s+(.+)$", t, flags=re.I)
    if m:
        fixed = f"Save this for {m.group(1).strip()}".rstrip(".")
        if _cta_grammar_ok(fixed):
            return fixed
    return _CTA_FALLBACKS[seed % len(_CTA_FALLBACKS)]


def _is_empty_cta(text: str) -> bool:
    low = re.sub(r"[.!?]+$", "", (text or "").lower().strip())
    if low in BANNED_EMPTY_CTAS or low in BANNED_CTAS:
        return True
    if re.match(
        r"^(save|keep|share)\s+this(\s+(tip|insight|guide|hack|advice|"
        r"reminder|trick|list|moment of truth))?$",
        low,
    ):
        return True
    if "tomorrow morning" in low and low.startswith("save this for tomorrow"):
        return True
    if not _cta_grammar_ok(text or ""):
        return True
    return False


def diversify_cta(slides: list[GeneratedSlide], seed: int = 0) -> list[GeneratedSlide]:
    """Заменить пустой/грамматически неверный CTA на разрешённый."""
    if len(slides) < 2:
        return slides
    fixed = _fix_cta_grammar(slides[-1].text, seed=seed)
    if _is_empty_cta(fixed):
        fixed = _CTA_FALLBACKS[seed % len(_CTA_FALLBACKS)]
    if fixed == slides[-1].text:
        return slides
    out = list(slides)
    out[-1] = GeneratedSlide(
        text=fixed,
        search_query=slides[-1].search_query,
        role="cta",
        visual_scene=slides[-1].visual_scene,
    )
    return out


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


def _hook_has_banned_stamp(hook: str) -> bool:
    low = (hook or "").lower()
    return any(s in low for s in BANNED_HOOK_STAMPS)


def _rebuild_hook_from_topic(topic: str) -> str:
    t = re.sub(r"\s+", " ", (topic or "").strip())
    t = re.split(r"[—–|:]", t, maxsplit=1)[0].strip()
    t = re.split(
        r"\s+(?:is|are|that|when|for|without|and how|after|before)\b",
        t,
        maxsplit=1,
        flags=re.I,
    )[0].strip(" —–-:")
    words = t.split()
    if len(words) > 6:
        t = " ".join(words[:6])
    if not t:
        t = "this habit"
    low = t.lower()
    return (
        f"I kept pretending {low} was a personality trait. "
        f"Honestly, it was just me avoiding the uncomfortable part."
    )




def ugc_marker_for(index: int = 0) -> str:
    return UGC_QUERY_MARKERS[index % len(UGC_QUERY_MARKERS)]


def extract_lighting_anchor(query: str) -> tuple[str, str]:
    """Вернуть (lighting_phrase|'', query_без_lighting)."""
    from core.harvester import CAROUSEL_LIGHTING_ANCHORS

    q = re.sub(r"\s+", " ", (query or "").strip())
    low = q.lower()
    for anchor in sorted(CAROUSEL_LIGHTING_ANCHORS, key=len, reverse=True):
        if anchor in low:
            cleaned = re.sub(re.escape(anchor), " ", q, count=1, flags=re.I)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return anchor, cleaned
    return "", q


def _clamp_query_to_word_limit(query: str, *, min_w: int = 3, max_w: int = 4) -> str:
    """
    Situation-query 3–4 слова через harvester.finalize_photo_query.
    Позы sitting/staring/walking/lying сохраняются (_SITUATION_POSE_KEEP).
    """
    from core.harvester import finalize_photo_query

    del min_w, max_w
    q = (query or "").strip()
    if not q:
        return ""
    return finalize_photo_query(q)


def _strip_ugc_and_legacy_tails(query: str) -> str:
    """
    Вырезать legacy spam-хвосты, сток и moodboard-фразы.
    Одиночный trailing aesthetic|candid сохраняем (формула situation).
    """
    q = re.sub(r"\s+", " ", (query or "").strip())
    for suf in sorted(
        (
            *QUERY_DUP_SUFFIXES,
            *BANNED_MOODBOARD_PHRASES,
            "shot on iphone photo dump",
            "casual camera roll snapshot",
            "candid raw photo dump",
            "amateur flash photo",
            "girlhood aesthetic cozy",
            "pinterest girl aesthetic night",
            "bed rotting aesthetic",
            "cozy girl bedroom night",
            "aesthetic photo dump",
            "dark academia aesthetic",
            "cozy night city view",
        ),
        key=len,
        reverse=True,
    ):
        q = re.sub(re.escape(suf), " ", q, flags=re.I)
    for ban in (
        *BANNED_STOCK_QUERY_TERMS,
        *BANNED_FACE_QUERY_PHRASES,
        *BANNED_DEAD_OBJECT_PHRASES,
        *BANNED_FASHION_STREET_TERMS,
    ):
        q = re.sub(re.escape(ban), " ", q, flags=re.I)
    q = re.sub(
        r"\b(coat|outfit|fashion|ootd|lookbook|streetstyle)\b",
        " ",
        q,
        flags=re.I,
    )
    q = re.sub(r"\b0\.5x(?:\s*lens)?\b", " ", q, flags=re.I)
    q = re.sub(
        r"\b(35mm|film|wallpaper|gradient|vector|illustration|academia)\b",
        " ",
        q,
        flags=re.I,
    )
    # vibe/vibes — шум; aesthetic|candid оставляем как опциональный хвост формулы
    q = re.sub(r"\b(vibe|vibes|moody|ambient)\b", " ", q, flags=re.I)
    return re.sub(r"\s+", " ", q).strip(" ,.-")


def _dedupe_query_tags(query: str) -> str:
    """Убрать дубли хвостов, сток и moodboard-слова."""
    return _strip_ugc_and_legacy_tails(query)


_ABSTRACT_QUERY_WORDS: frozenset[str] = frozenset(
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
        "pov",
    }
)


def _has_human_situation(query: str) -> bool:
    """True если есть поза/действие (+ желательно место), не still-life из слова слайда."""
    words = set(re.findall(r"[a-z0-9']+", (query or "").lower()))
    if not words:
        return False
    return bool(words & _HUMAN_POSE_MARKERS)


def _query_is_abstract_only(query: str) -> bool:
    """True если одни mood/mobile слова без позы/места."""
    words = re.findall(r"[a-z0-9']+", (query or "").lower())
    if not words:
        return True
    if _has_human_situation(query):
        return False
    return all(w in _ABSTRACT_QUERY_WORDS for w in words)


def _force_tangible_noun_prefix(
    query: str,
    slide_text: str = "",
    topic: str = "",
    index: int = 0,
) -> str:
    """
    Больше НЕ подменяет запрос mood-стабом.
    Если query уже не abstract-only — оставляем как есть.
    """
    del slide_text, topic, index
    q = re.sub(r"\s+", " ", (query or "").strip())
    return q


def _scrub_query(
    query: str,
    fallback_words: list[str],
    index: int = 0,
    preferred_marker: str | None = None,
    *,
    slide_text: str = "",
    topic: str = "",
    visual_scene: str = "",
) -> str:
    """Нормализовать search_query: вычистить banned tails, затем выровнять к visual_scene."""
    del preferred_marker, fallback_words
    _, q_rest = extract_lighting_anchor(query)
    q = re.sub(r"\s+", " ", (q_rest or "").strip())
    for phrase in sorted(BANNED_MOODBOARD_PHRASES, key=len, reverse=True):
        q = re.sub(re.escape(phrase), " ", q, flags=re.I)
    q = re.sub(r"\b(academia|vibes?|moody|ambient)\b", " ", q, flags=re.I)
    q = re.sub(r"\s+", " ", q).strip(" ,.-")

    for leak in QUERY_LEAK_PHRASES:
        if leak in q.lower():
            q = re.sub(re.escape(leak), " ", q, flags=re.I)

    for junk in (
        "candid 35mm film",
        "35mm film",
        "photo dump",
        "camera roll",
        "shot on iphone",
        "dark academia",
        "cozy aesthetic",
        "aesthetic night",
        "cozy night",
        "warm evening ambient lamp",
        "soft morning natural sunlight",
        "cozy rain window moody",
        "candid golden hour",
    ):
        q = re.sub(re.escape(junk), " ", q, flags=re.I)

    changed = True
    while changed:
        changed = False
        low = q.lower().strip()
        for suf in sorted(QUERY_DUP_SUFFIXES, key=len, reverse=True):
            if low.endswith(suf):
                q = q[: len(q) - len(suf)].rstrip(" ,.-")
                changed = True
                break
            idx = low.find(suf)
            if idx > 0:
                q = q[:idx].rstrip(" ,.-")
                changed = True
                break

    q = re.sub(r"\s+", " ", q).strip(" ,.-")
    for ban in (
        *BANNED_STOCK_QUERY_TERMS,
        *BANNED_FACE_QUERY_PHRASES,
        *BANNED_DEAD_OBJECT_PHRASES,
        *BANNED_FASHION_STREET_TERMS,
        "hyperrealistic",
        "concept art",
        "unreal engine",
        "midjourney",
        "ai art",
        "amateur flash photo",
        "aesthetic photo dump",
        "photo dump",
        "shot on iphone",
        "girlhood",
        "bed rotting",
    ):
        q = re.sub(re.escape(ban), " ", q, flags=re.I)
    q = re.sub(r"\b0\.5x(?:\s*lens)?\b", " ", q, flags=re.I)
    q = re.sub(
        r"\b(portrait|headshot|selfie face|stressed|depressed|anxious|"
        r"wallpaper|gradient|vector|illustration|academia|"
        r"coat|outfit|fashion|ootd|lookbook|streetstyle)\b",
        " ",
        q,
        flags=re.I,
    )
    q = re.sub(r"\s+", " ", q).strip(" ,.-")
    q = _dedupe_query_tags(q)

    scene = (visual_scene or "").strip() or slide_text
    q = align_search_query_to_scene(q, scene, topic=topic, index=index)
    q = _clamp_query_to_word_limit(q) or q
    return q



_STAMP_BODY_VERBS = (
    "Audit",
    "Define",
    "Replace",
    "Optimize",
    "Triage",
    "Protocol",
    "Implement",
    "Calibrate",
    "Leverage",
)

# Человеческие переписывалки вместо Cut/Block/Kill-императивов
_HUMAN_BODY_OPENERS = (
    "Honestly,",
    "Turns out",
    "The truth is,",
    "So basically,",
    "Apparently,",
    "You're",
    "I keep",
    "Most days,",
)

# Face/stock + dead-object bans (legacy name kept for imports)
_BANNED_DECOR_QUERY_PHRASES = (
    *BANNED_FACE_QUERY_PHRASES,
    *BANNED_DEAD_OBJECT_PHRASES,
)


def _topic_is_two_minute_rule(topic: str) -> bool:
    low = re.sub(r"[^\w\s-]", " ", (topic or "").lower())
    return bool(re.search(r"\b2[\s-]?minute|\btwo[\s-]?minute", low))


def _contains_2pm(text: str) -> bool:
    return bool(re.search(r"\b2\s*pm\b", text or "", re.I))


def _strip_offtopic_2pm(text: str, topic: str) -> str:
    """Убрать 2pm из текста, если тема про 2-minute rule."""
    if not _topic_is_two_minute_rule(topic):
        return text
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not _contains_2pm(t):
        return t
    sentences = re.split(r"(?<=[.!?])\s+", t)
    kept = [s for s in sentences if s and not _contains_2pm(s)]
    if kept:
        result = " ".join(kept).strip()
        logger.warning("Stripped off-topic 2pm: %r → %r", t, result)
        return result
    if _contains_2pm(t):
        logger.warning("Removed all-2pm slot text for 2-minute-rule topic: %r", t)
        return ""
    return t


def _rebuild_two_minute_hook(_topic: str) -> str:
    return (
        "I avoided a tiny task for three days. Turns out the 2-minute rule "
        "was just me finally starting."
    )


def _scrub_robot_lexicon(text: str) -> str:
    """Вычистить корпоративные штампы из уже сгенерированного текста."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    replacements = (
        (r"\bprotocol\b", "habit"),
        (r"\bprotocols\b", "habits"),
        (r"\baudit your\b", "look at your"),
        (r"\baudit the\b", "look at the"),
        (r"\btriage checklist\b", "messy priority list"),
        (r"\btriage your\b", "sort your"),
        (r"\bcognitive performance\b", "how your brain feels"),
        (r"\boptimize (?:your )?output\b", "get less done while panicking more"),
        (r"\bsensory reset\b", "phone-down minute"),
        (r"\belimination protocol\b", "honest cut"),
        (r"\bfocus protocol\b", "focus habit"),
        (r"\bworkflow audit\b", "honest look at your week"),
        (r"\bhabit audit\b", "honest look at your habits"),
        (r"\benergy audit\b", "honest look at your energy"),
        (r"\bhigh-leverage\b", "actually useful"),
        (r"\bhigh leverage\b", "actually useful"),
        (r"\boperating system for\b", "default setting for"),
        (r"\brun this protocol\b", "try this once"),
        (r"\binstall this habit\b", "try this habit"),
    )
    for pat, repl in replacements:
        t = re.sub(pat, repl, t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def _dedupe_body_verb_openers_list(body_texts: list[str]) -> list[str]:
    """Убрать робот-открывашки (Audit/Define/…) и не штамповать одни human openers."""
    stamp_lower = {verb.lower() for verb in _STAMP_BODY_VERBS}
    used_openers: set[str] = set()
    rewrite_idx = 0
    out = list(body_texts)

    def _next_human_opener() -> str:
        nonlocal rewrite_idx
        while True:
            candidate = _HUMAN_BODY_OPENERS[rewrite_idx % len(_HUMAN_BODY_OPENERS)]
            rewrite_idx += 1
            key = candidate.lower().rstrip(",")
            if key not in used_openers:
                return candidate

    for i, text in enumerate(out):
        cleaned = _scrub_robot_lexicon(text)
        match = re.match(r"^([A-Za-z]+)\b", cleaned)
        if not match:
            out[i] = cleaned
            continue
        verb_low = match.group(1).lower()
        needs_replace = verb_low in stamp_lower or verb_low == "label"
        if needs_replace:
            new_opener = _next_human_opener()
            rest = re.sub(r"^[A-Za-z]+\b\s*", "", cleaned, count=1).strip()
            if rest:
                rest = rest[0].lower() + rest[1:]
                out[i] = f"{new_opener} {rest}"
            else:
                out[i] = new_opener
            used_openers.add(new_opener.lower().rstrip(","))
            logger.warning(
                "Rewrote robot body opener[%d]: %r → %r", i, text, out[i]
            )
        else:
            out[i] = cleaned
            used_openers.add(verb_low)
    return out


def _dedupe_body_verb_openers(texts: dict[str, str]) -> None:
    """Legacy dict-форма (point_1..3) — для совместимости."""
    point_keys = ("point_1", "point_2", "point_3")
    bodies = [texts[k] for k in point_keys if k in texts]
    if not bodies:
        return
    fixed = _dedupe_body_verb_openers_list(bodies)
    for key, value in zip(point_keys, fixed):
        if key in texts:
            texts[key] = value


def _query_scene_key(query: str) -> str:
    core = _strip_ugc_and_legacy_tails(query or "").lower()
    return re.sub(r"\s+", " ", core)


def _slide_is_night_vibe(text: str) -> bool:
    low = (text or "").lower()
    night_keys = (
        "night", "tonight", "midnight", "3am", "2am", "insomnia", "can't sleep",
        "cant sleep", "spiral", "overthink", "anxiety", "anxious", "doomscroll",
        "late", "dark", "alone", "crying", "bed", "sleep", "tired", "exhausted",
        "rumina", "panic", "shame", "lonely",
    )
    day_keys = (
        "morning", "monday", "desk", "meeting", "boss", "email", "deadline",
        "planner", "notebook", "coffee", "matcha", "sun", "work", "office",
        "productive", "focus", "task", "calendar",
    )
    night_hits = sum(1 for k in night_keys if k in low)
    day_hits = sum(1 for k in day_keys if k in low)
    if night_hits > day_hits:
        return True
    if day_hits > night_hits:
        return False
    return True


def _topic_allows_bed(topic: str) -> bool:
    """Кровать разрешена только если тема про сон / пробуждение."""
    low = f" {(topic or '').lower()} "
    return any(k in low for k in _SLEEP_TOPIC_KEYS)


def _topic_has_any(topic: str, keys: tuple[str, ...]) -> bool:
    low = (topic or "").lower()
    for k in keys:
        k = k.strip()
        if not k:
            continue
        if " " in k or len(k) >= 5:
            if k in low:
                return True
        elif re.search(rf"\b{re.escape(k)}\b", low):
            return True
    return False


def _topic_is_skincare(topic: str) -> bool:
    return _topic_has_any(topic, _SKIN_TOPIC_KEYS)


def _topic_is_relationship(topic: str) -> bool:
    return _topic_has_any(topic, _RELATIONSHIP_TOPIC_KEYS)


def _topic_is_study_or_work(topic: str) -> bool:
    return _topic_has_any(topic, _STUDY_TOPIC_KEYS)


def _query_has_bed_words(query: str) -> bool:
    low = (query or "").lower()
    return any(
        re.search(rf"\b{re.escape(w)}\b", low) for w in _BED_QUERY_WORDS
    )


def _strip_bed_words(query: str) -> str:
    q = query or ""
    for w in _BED_QUERY_WORDS:
        q = re.sub(rf"\b{re.escape(w)}\b", " ", q, flags=re.I)
    return re.sub(r"\s+", " ", q).strip(" ,.-")


def _force_geography_query(query: str, topic: str, slide_text: str = "") -> str:
    """
    Bed как декоративный still-life вне sleep — срезать слова, НЕ стаб.
    Human situation с bed (lying bed staring…) — оставляем.
    """
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not q:
        return q
    if _topic_allows_bed(topic):
        return q
    if not _query_has_bed_words(q):
        return q
    # поза на кровати = валидная night-spiral сцена
    if _has_human_situation(q):
        return q

    stripped = _strip_bed_words(q)
    if stripped and not _query_has_bed_words(stripped):
        logger.warning("Stripped bed words from query: %r → %r", q, stripped)
        # добить до 3 слов из оставшихся токенов сцены/текста
        if len(stripped.split()) >= 2:
            return align_search_query_to_scene(
                stripped, slide_text or stripped, topic=topic
            )
        return align_search_query_to_scene(
            "", slide_text or stripped, topic=topic
        )
    logger.warning(
        "Bed banned — rebuild from remaining scene nouns: %r",
        q,
    )
    return search_query_from_visual_scene(
        _strip_bed_words(slide_text or q) or "indoor room floor",
        topic=topic,
    )


def _query_has_tangible_object(text: str) -> bool:
    """Legacy helper: tangible map keys (не использовать для literal inject)."""
    low = (text or "").lower()
    for key, _ in _TANGIBLE_OBJECT_MAP:
        if re.search(rf"\b{re.escape(key)}\b", low):
            return True
    return False


def _extract_tangible_query(slide_text: str) -> str | None:
    """
    Legacy: карта предмет→query.
    НЕ вызывать из генерации search_query (убивает смысл метафор).
    Оставлено для совместимости импортов / relevance.
    """
    low = (slide_text or "").lower()
    for key, query in sorted(_TANGIBLE_OBJECT_MAP, key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(key)}\b", low):
            return query
    return None


def _query_looks_like_study_desk(query: str) -> bool:
    low = (query or "").lower()
    return any(m in low for m in _STUDY_DESK_MARKERS)


def _slide_situation_pool(slide_text: str, topic: str = "") -> tuple[str, ...]:
    """Legacy: стабы удалены — один query из текста как visual_scene."""
    q = search_query_from_visual_scene(slide_text or topic or "", topic=topic)
    return (q,) if q else ("everyday indoor candid",)


def _mood_query_from_slide(
    slide_text: str, index: int = 0, topic: str = ""
) -> str:
    """Fallback без стабов: выжимка существительных из текста слайда."""
    del index
    return search_query_from_visual_scene(
        slide_text or topic or "everyday indoor scene",
        topic=topic,
    )


def _looks_like_literal_person_scene(query: str) -> bool:
    """Стоковый 'stressed man staring at laptop' — не viral pose."""
    low = (query or "").lower()
    if _has_human_situation(low) and not re.search(
        r"\b(stressed|depressed|sad face|angry face|crying face)\b", low
    ):
        return False
    has_person = bool(
        re.search(r"\b(man|woman|person|people|guy|lady|boy)\b", low)
    )
    has_stress = bool(
        re.search(r"\b(stressed|sad|angry|crying|depressed|anxious)\b", low)
    )
    return has_person and has_stress


def _has_dead_objects(query: str) -> bool:
    low = (query or "").lower()
    # поза человека важнее dead-object бан-листа
    if _has_human_situation(low):
        return False
    if any(p in low for p in BANNED_DEAD_OBJECT_PHRASES):
        return True
    if any(p in low for p in BANNED_FASHION_STREET_TERMS):
        return True
    if re.search(r"\b(coat|outfit|fashion|ootd|lookbook)\b", low):
        return True
    if re.search(r"\b0\.5x(?:\s*lens)?\b", low):
        return True
    return False


def _is_banned_face_or_stock_query(query: str) -> bool:
    low = (query or "").lower()
    if any(p in low for p in BANNED_FACE_QUERY_PHRASES):
        return True
    if re.search(
        r"\b(portrait|headshot|stock photo|stock image|looking stressed|"
        r"face looking|close[- ]?up face)\b",
        low,
    ):
        return True
    if _looks_like_literal_person_scene(low):
        return True
    return False


def _has_human_presence(query: str) -> bool:
    """Живая situation-сцена или явный lifestyle-якорь."""
    if _has_human_situation(query):
        return True
    low = (query or "").lower()
    return any(
        k in low
        for k in (
            "hands", "socks", "bed", "desk", "coffee", "tea",
            "matcha", "phone", "laptop", "notes", "notebook", "hoodie",
            "mirror", "selfie", "mug", "writing", "reading", "keys",
            "fridge", "sneakers", "journal", "charger", "window", "door",
            "steering", "wheel", "snack", "pen", "floor", "sidewalk",
            "ceiling", "wall", "steps",
        )
    )


def _is_banned_query(query: str) -> bool:
    """Бан: мёртвые предметы + сток-лица + wallpaper + moodboard-only."""
    if _has_dead_objects(query) or _is_banned_face_or_stock_query(query):
        return True
    low = (query or "").lower()
    if any(t in low for t in ("wallpaper", "gradient", "vector", "illustration")):
        return True
    if any(p in low for p in BANNED_MOODBOARD_PHRASES):
        return True
    _, obj_q = extract_lighting_anchor(query)
    check = (obj_q or query or "").strip()
    if not check:
        return True
    if _query_is_abstract_only(check):
        return True
    words = [
        w
        for w in check.lower().split()
        if w not in {"iphone", "snapshot", "finsta"}
    ]
    # aesthetic|candid — опциональный 4-й стиль, не считаем мусором
    if len(words) > 4:
        return True
    if not words:
        return True
    if _has_human_situation(check) or _has_human_presence(check):
        return False
    return True


def _is_banned_decor_query(query: str) -> bool:
    """Совместимость имени: теперь = полный query ban."""
    return _is_banned_query(query)


def _hair_color_family(hair: str) -> str:
    h = (hair or "").lower()
    if any(t in h for t in ("blonde", "blond", "platinum")):
        return "blonde"
    if any(t in h for t in ("ginger", "auburn", "red hair", "redhead")):
        return "ginger"
    # light brown / caramel BEFORE generic brown
    if any(
        t in h
        for t in ("light brown", "caramel", "honey", "dirty blonde")
    ) or ("light" in h and "brown" in h):
        return "light_brown"
    if any(t in h for t in ("black",)):
        return "black"
    if any(t in h for t in ("brunette", "brown", "dark")):
        return "brown"
    if "light" in h:
        return "light_brown"
    return "other"


# Diverse female looks — blonde is ONE option, not the default.
_FEMALE_DNA_PALETTE: list[dict[str, str]] = [
    {
        "hair": "long brown hair",
        "style": "woman mid 20s, casual",
        "skin_tone": "olive",
        "build": "slim",
    },
    {
        "hair": "long dark curly hair",
        "style": "woman early 20s, casual",
        "skin_tone": "medium",
        "build": "average",
    },
    {
        "hair": "long black hair",
        "style": "woman mid 20s, casual",
        "skin_tone": "deep",
        "build": "slim",
    },
    {
        "hair": "shoulder length auburn hair",
        "style": "woman early 30s, casual",
        "skin_tone": "fair",
        "build": "average",
    },
    {
        "hair": "wavy light brown hair",
        "style": "woman mid 20s, casual",
        "skin_tone": "light",
        "build": "soft",
    },
    {
        "hair": "short dark hair",
        "style": "woman late 20s, casual",
        "skin_tone": "olive",
        "build": "athletic",
    },
    {
        "hair": "long ginger hair",
        "style": "woman early 20s, casual",
        "skin_tone": "fair",
        "build": "slim",
    },
    {
        "hair": "long blonde hair",
        "style": "woman early 20s, casual",
        "skin_tone": "fair",
        "build": "slim",
    },
]

_MALE_DNA_PALETTE: list[dict[str, str]] = [
    {
        "hair": "short dark hair",
        "style": "man mid 20s, casual",
        "skin_tone": "fair",
        "build": "average",
    },
    {
        "hair": "short brown hair",
        "style": "man early 30s, casual",
        "skin_tone": "olive",
        "build": "athletic",
    },
    {
        "hair": "short black hair",
        "style": "man mid 20s, casual",
        "skin_tone": "medium",
        "build": "average",
    },
    {
        "hair": "curly dark hair",
        "style": "man late 20s, casual",
        "skin_tone": "deep",
        "build": "soft",
    },
]


def _default_character_dna(
    topic: str = "",
    *,
    variation_index: int = 0,
    avoid_families: set[str] | None = None,
) -> dict[str, str]:
    """Stable-but-diverse passport from topic + variation (no blonde monopoly)."""
    low = (topic or "").lower()
    female_cues = (
        "girl",
        "woman",
        "she ",
        "her ",
        "girlfriend",
        "wife",
        "female",
        "blonde",
        "easygoing girl",
    )
    male_cues = ("guy", "man ", "he ", "his ", "boyfriend", "husband", "male")
    male = any(c in low for c in male_cues) and not any(
        c in low for c in female_cues
    )
    palette = _MALE_DNA_PALETTE if male else _FEMALE_DNA_PALETTE
    avoid = set(avoid_families or ())

    # Topic explicitly asks for blonde → allow blonde pick.
    force_blonde = (not male) and ("blonde" in low or "blond" in low)

    candidates = []
    for look in palette:
        fam = _hair_color_family(look["hair"])
        if force_blonde and fam != "blonde":
            continue
        if fam in avoid and not force_blonde:
            continue
        candidates.append(look)
    if not candidates:
        candidates = list(palette)

    # Blonde is allowed but not preferred — only when topic asks or
    # non-blonde options are exhausted by avoid_families.
    if not force_blonde:
        non_blonde = [
            c
            for c in candidates
            if _hair_color_family(c["hair"]) != "blonde"
        ]
        if non_blonde:
            candidates = non_blonde

    # Deterministic pick from topic+variation so same topic is stable,
    # different topics / indices spread across the palette.
    digest = hashlib.md5(
        f"{low}|{variation_index}|dna_v2".encode("utf-8")
    ).hexdigest()
    seed = int(digest[:8], 16)
    pick = candidates[seed % len(candidates)]
    return {
        "gender": "male" if male else "female",
        "hair": pick["hair"],
        "style": pick["style"],
        "skin_tone": pick["skin_tone"],
        "build": pick["build"],
    }


def sanitize_character_dna(
    raw: Any,
    *,
    topic: str = "",
    variation_index: int = 0,
    avoid_families: set[str] | None = None,
) -> dict[str, str]:
    """Normalize character_dna; diversify away from overused hair families."""
    base = _default_character_dna(
        topic, variation_index=variation_index, avoid_families=avoid_families
    )
    if not isinstance(raw, dict):
        return base
    try:
        dna = CharacterDNA(
            gender=raw.get("gender", base["gender"]),
            hair=raw.get("hair") or base["hair"],
            style=raw.get("style") or base["style"],
            skin_tone=raw.get("skin_tone") or base["skin_tone"],
            build=raw.get("build") or base.get("build") or "average",
        )
        out = dna.model_dump()
    except Exception:
        return base

    fam = _hair_color_family(out["hair"])
    avoid = set(avoid_families or ())
    topic_low = (topic or "").lower()
    topic_wants_blonde = "blonde" in topic_low or "blond" in topic_low

    # Gemini copies the old blonde example → re-roll unless topic asks for it
    # or we already avoided that family.
    stereotype_blonde = fam == "blonde" and not topic_wants_blonde
    reused = fam in avoid and not topic_wants_blonde
    if stereotype_blonde or reused:
        return base
    return out


def character_hair_tokens(dna: dict[str, str]) -> list[str]:
    """Searchable hair tokens from DNA (e.g. blonde, long, hair)."""
    hair = re.sub(r"\s+", " ", str(dna.get("hair") or "").lower()).strip()
    words = re.findall(r"[a-z]{3,}", hair)
    # keep distinctive color/length first
    priority = (
        "blonde",
        "blond",
        "brunette",
        "ginger",
        "redhead",
        "auburn",
        "black",
        "brown",
        "dark",
        "light",
        "long",
        "short",
        "curly",
        "wavy",
        "straight",
        "hair",
    )
    ordered: list[str] = []
    for p in priority:
        if p in words and p not in ordered:
            ordered.append(p)
    for w in words:
        if w not in ordered:
            ordered.append(w)
    if "hair" not in ordered:
        ordered.append("hair")
    return ordered[:4]


def _dna_hair_color_token(dna: dict[str, str]) -> str:
    """Primary searchable hair-color token from DNA."""
    hair = str(dna.get("hair") or "").lower()
    # Prefer multi-word families before single-token scan.
    # "caramel" is a single Pinterest-friendly token (query is 4 words max).
    if "light brown" in hair or ("light" in hair and "brown" in hair):
        return "caramel"
    hair_toks = character_hair_tokens(dna)
    color = next(
        (
            t
            for t in hair_toks
            if t
            in {
                "blonde",
                "blond",
                "brunette",
                "ginger",
                "redhead",
                "black",
                "brown",
                "dark",
                "auburn",
            }
        ),
        "",
    )
    if color == "brown":
        return "brunette"
    if color == "redhead":
        return "ginger"
    if color == "auburn":
        return "auburn"
    if color == "blond":
        return "blonde"
    return color or (hair_toks[0] if hair_toks else "hair")


_FOREIGN_HAIR_COLORS: tuple[str, ...] = (
    "blonde",
    "blond",
    "platinum",
    "brunette",
    "ginger",
    "redhead",
    "auburn",
    "black",
    "brown",
    "dark",
    "caramel",
    "honey",
)


def _query_has_foreign_hair_color(query: str, dna_color: str) -> bool:
    """True if query names a hair color that is not the DNA color family."""
    low = (query or "").lower()
    dna_fam = _hair_color_family(dna_color)
    for tok in _FOREIGN_HAIR_COLORS:
        if tok not in low:
            continue
        # map token → family
        fam = _hair_color_family(tok)
        if fam != dna_fam and fam != "other":
            return True
    return False


def inject_character_markers_into_query(
    query: str,
    dna: dict[str, str],
    *,
    slide_index: int = 0,
) -> str:
    """
    Soft DNA hygiene ONLY — never hijack the Pinterest string.

    - Strip opposite-gender person words
    - Strip foreign hair-color tokens
    - Leave scene props intact (pasta/sink/pantry/…)

    Hair/gender consistency is enforced by SigLIP attr/gender locks after download.
    DNA casting queries like "blonde hair girl" destroy text↔photo relevance.
    """
    del slide_index
    if not dna:
        return query
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not q:
        return q

    gender = str(dna.get("gender") or "female").lower()
    color = _dna_hair_color_token(dna)

    # Kill opposite-gender person words
    if gender == "female":
        q = re.sub(r"\b(guy|man|men|male|boyfriend|husband)\b", " ", q, flags=re.I)
    else:
        q = re.sub(
            r"\b(girl|woman|women|female|girlfriend|wife|ladies)\b",
            " ",
            q,
            flags=re.I,
        )

    # Strip foreign hair colors only (keep scene nouns)
    dna_fam = _hair_color_family(color)
    for tok in _FOREIGN_HAIR_COLORS:
        if _hair_color_family(tok) == dna_fam:
            continue
        q = re.sub(rf"\b{re.escape(tok)}\b", " ", q, flags=re.I)

    q = re.sub(r"\s+", " ", q).strip()
    # If we emptied the query, caller (forge) will rebuild from slide text
    return q


def _query_from_slide_text(slide_text: str, index: int = 0, topic: str = "") -> str:
    """Физический fallback — осязаемый предмет, не moodboard."""
    return _mood_query_from_slide(slide_text, index, topic=topic)


def _sanitize_carousel_queries(
    queries: list[str],
    slide_texts: list[str],
    topic: str = "",
    visual_scenes: list[str] | None = None,
) -> list[str]:
    """
    search_query строго из visual_scene (noun overlap check).
    Без mood-стабов и без literal word→object inject.
    """
    scenes = list(visual_scenes or [])
    seen: set[str] = set()
    out: list[str] = []
    n = max(len(queries), len(slide_texts), len(scenes))

    for i in range(n):
        raw_q = queries[i] if i < len(queries) else ""
        slide_text = slide_texts[i] if i < len(slide_texts) else ""
        scene = scenes[i] if i < len(scenes) else ""
        if not scene.strip():
            scene = slide_text

        _, q = extract_lighting_anchor(raw_q)
        q = re.sub(r"\s+", " ", (q or "").strip())
        for phrase in sorted(BANNED_MOODBOARD_PHRASES, key=len, reverse=True):
            q = re.sub(re.escape(phrase), " ", q, flags=re.I)
        q = re.sub(r"\s+", " ", q).strip()

        q = align_search_query_to_scene(q, scene, topic=topic, index=i)

        scene_key = _query_scene_key(q)
        if scene_key and scene_key in seen:
            # сдвиг: взять следующие существительные сцены
            nouns = extract_visual_scene_nouns(scene, limit=6)
            if len(nouns) > 3:
                alt_scene = " ".join(nouns[1:4])
                alt = search_query_from_visual_scene(alt_scene, topic=topic)
            else:
                alt = search_query_from_visual_scene(
                    f"{scene} detail {i}", topic=topic
                )
            if _query_scene_key(alt) not in seen:
                logger.warning(
                    "Duplicate query slide[%d]: %r → %r", i, q, alt
                )
                q = alt
                scene_key = _query_scene_key(q)
        if scene_key:
            seen.add(scene_key)
        q = _clamp_query_to_word_limit(q) or q
        out.append(q)
    return out


def _topic_allows_tab_advice(topic: str) -> bool:
    low = (topic or "").lower()
    return any(
        k in low
        for k in (
            "context switch",
            "multitask",
            "browser tab",
            "open tab",
            "switching tab",
            "tab overload",
        )
    )


def _trim_incomplete_sentence_tail(text: str) -> str:
    """No-op: текст Gemini не обрезаем (раньше резал вторые предложения)."""
    return re.sub(r"\s+", " ", (text or "").strip())


def _strip_offtopic_tab_advice(text: str, topic: str) -> str:
    """Убрать советы про закрытие вкладок, если тема не про tabs/context switching."""
    if _topic_allows_tab_advice(topic):
        return text
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not any(p in t.lower() for p in _CLOSE_TAB_PHRASES):
        return t
    sentences = re.split(r"(?<=[.!?])\s+", t)
    kept = [
        s
        for s in sentences
        if s and not any(p in s.lower() for p in _CLOSE_TAB_PHRASES)
    ]
    if kept:
        result = " ".join(kept).strip()
        logger.warning("Stripped off-topic tab advice: %r → %r", t, result)
        return result
    logger.warning("Off-topic tab advice in slot (kept as-is): %r", t)
    return t


def _sanitize_slot_text(
    text: str,
    *,
    is_cta: bool = False,
    is_point: bool = False,
    topic: str = "",
    seed: int = 0,
) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = t.replace("FocusFlow", "").replace("focusflow", "")
    t = re.sub(r"\s+", " ", t).strip(" ,.-")
    if _has_cyrillic(t):
        return ""
    t = _scrub_robot_lexicon(t)
    if is_point:
        t = _strip_offtopic_tab_advice(t, topic)
        # НЕ обрезаем incomplete tails / вторые предложения
    if is_cta:
        t = _fix_cta_grammar(t, seed=seed)
        if _is_empty_cta(t):
            t = EMPTY_CTA_REPLACEMENT
    return t


def _contains_banned_cliche(text: str) -> bool:
    low = (text or "").lower()
    if any(b in low for b in BANNED_GENERIC):
        return True
    if any(b in low for b in BANNED_COACH_PHRASES):
        return True
    if any(b in low for b in BANNED_ROBOT_VOICE):
        return True
    if any(b in low for b in BANNED_UNIVERSAL_TOOLKIT):
        return True
    if any(b in low for b in BANNED_FALSE_REFRAMES):
        return True
    if any(b in low for b in BANNED_HOOK_STAMPS):
        return True
    return any(p.search(text or "") for p in BANNED_HOOK_PATTERNS)


def _normalize_role(raw: str, index: int, total: int) -> str:
    role = str(raw or "").strip().lower()
    if role in {"hook", "body", "cta"}:
        return role
    if index == 0:
        return "hook"
    if index == total - 1:
        return "cta"
    return "body"


def _fallback_visual_scene(text: str, query: str = "") -> str:
    """Физический кадр, если модель не вернула visual_scene."""
    q = re.sub(r"\s+", " ", (query or "").strip())
    # не подставлять mood-стабы в сцену
    if q and not any(
        stub in q.lower()
        for stub in (
            "laptop glow",
            "fridge glow",
            "balcony railing",
            "curtain gap",
            "hands clutching",
            "two mugs",
            "single place setting",
        )
    ):
        return f"candid lifestyle photo: {q}, natural light"
    words = re.findall(r"[A-Za-z]{3,}", text or "")[:14]
    if words:
        return (
            "person in everyday indoor scene, "
            + " ".join(words[:8])
            + ", soft ambient light"
        )
    return "tired person in quiet room, dim ambient light, candid frame"


def _raw_slides_from_payload(data: dict[str, Any]) -> list[dict[str, str]] | None:
    """Достать slides[] из нового или legacy-формата."""
    items = data.get("slides")
    if isinstance(items, list) and items:
        out: list[dict[str, str]] = []
        for i, item in enumerate(items):
            if isinstance(item, dict):
                text = str(
                    item.get("text") or item.get("copy") or ""
                ).strip()
                query = str(
                    item.get("search_query")
                    or item.get("query")
                    or item.get("pinterest_query")
                    or ""
                ).strip()
                scene = str(
                    item.get("visual_scene")
                    or item.get("scene")
                    or item.get("camera_scene")
                    or ""
                ).strip()
                role = str(item.get("role") or "")
            else:
                text = str(item or "").strip()
                query = ""
                scene = ""
                role = ""
            if text:
                out.append(
                    {
                        "role": role,
                        "text": text,
                        "visual_scene": scene,
                        "search_query": query,
                    }
                )
        if len(out) >= 4:
            return out

    # legacy fixed slots
    if all(k in data for k in SLOT_KEYS):
        queries = data.get("search_queries")
        if not isinstance(queries, list):
            queries = []
        while len(queries) < 5:
            queries.append("")
        return [
            {
                "role": "hook",
                "text": str(data.get("hook") or ""),
                "visual_scene": "",
                "search_query": str(queries[0] or ""),
            },
            {
                "role": "body",
                "text": str(data.get("point_1") or ""),
                "visual_scene": "",
                "search_query": str(queries[1] or ""),
            },
            {
                "role": "body",
                "text": str(data.get("point_2") or ""),
                "visual_scene": "",
                "search_query": str(queries[2] or ""),
            },
            {
                "role": "body",
                "text": str(data.get("point_3") or ""),
                "visual_scene": "",
                "search_query": str(queries[3] or ""),
            },
            {
                "role": "cta",
                "text": str(data.get("cta") or ""),
                "visual_scene": "",
                "search_query": str(queries[4] or ""),
            },
        ]
    return None


def _slots_from_legacy_slides(data: dict[str, Any]) -> dict[str, Any] | None:
    """Fallback: старый формат {"slides":[...]} → слоты (compat)."""
    raw = _raw_slides_from_payload(data)
    if raw is None or len(raw) < 4:
        return None
    hook = raw[0]["text"]
    cta = raw[-1]["text"]
    middles = [r["text"] for r in raw[1:-1]]
    while len(middles) < 3:
        middles.append(middles[-1] if middles else hook)
    middles = middles[:3]
    qs = [r["search_query"] for r in raw] + [""] * 5
    return {
        "hook": hook,
        "point_1": middles[0],
        "point_2": middles[1],
        "point_3": middles[2],
        "cta": cta,
        "search_queries": qs[:5],
    }


def sanitize_and_slots_to_slides(
    data: dict[str, Any],
    product: str = "",
    topic: str = "",
    character_dna: dict[str, str] | None = None,
) -> list[GeneratedSlide]:
    """
    Принять динамический slides[] (или legacy 5-slot JSON), вычистить протечки,
    вернуть 6–9 слайдов [{text, search_query, role}].
    character_dna markers are injected into every person/hair search_query.
    """
    payload = data if isinstance(data, dict) else {}
    dna = (
        character_dna
        if character_dna is not None
        else sanitize_character_dna(payload.get("character_dna"), topic=topic)
    )
    # stash for callers that only keep the slide list
    sanitize_and_slots_to_slides.last_character_dna = dna  # type: ignore[attr-defined]

    raw = _raw_slides_from_payload(payload)
    if raw is None:
        raise RuntimeError(
            "В ответе нет slides[] (и нет совместимого hook/point_*/cta)"
        )

    # clamp length
    if len(raw) > MAX_CAROUSEL_SLIDES:
        raw = raw[: MAX_CAROUSEL_SLIDES - 1] + [raw[-1]]
    if len(raw) < MIN_CAROUSEL_SLIDES:
        raise RuntimeError(
            f"Слишком мало слайдов: {len(raw)} (нужно {MIN_CAROUSEL_SLIDES}–"
            f"{MAX_CAROUSEL_SLIDES})"
        )

    # normalize roles
    for i, item in enumerate(raw):
        item["role"] = _normalize_role(item.get("role", ""), i, len(raw))
    raw[0]["role"] = "hook"
    raw[-1]["role"] = "cta"
    for item in raw[1:-1]:
        item["role"] = "body"

    # topic-implied body count: soft trim/pad not needed — just log
    implied = _topic_implied_body_count(topic)
    body_n = len(raw) - 2
    if implied is not None and body_n != implied:
        logger.warning(
            "Topic implies %d body slides, model returned %d (kept)",
            implied,
            body_n,
        )

    texts: list[str] = []
    queries: list[str] = []
    scenes: list[str] = []
    roles: list[str] = []
    for item in raw:
        role = item["role"]
        is_cta = role == "cta"
        is_point = role == "body"
        text = _sanitize_slot_text(
            item["text"],
            is_cta=is_cta,
            is_point=is_point,
            topic=topic,
        )
        if not text:
            raise RuntimeError(f"Пустой или не-английский слайд ({role})")
        texts.append(text)
        queries.append(item.get("search_query") or "")
        scenes.append(str(item.get("visual_scene") or "").strip())
        roles.append(role)

    # хуки-клоны → пересборка от темы
    if _hook_has_banned_stamp(texts[0]):
        rebuilt = _rebuild_hook_from_topic(topic)
        logger.warning("Banned hook stamp replaced: %r → %r", texts[0], rebuilt)
        texts[0] = rebuilt

    if _topic_is_two_minute_rule(topic):
        for i in range(len(texts) - 1):
            texts[i] = _strip_offtopic_2pm(texts[i], topic)
        if _contains_2pm(texts[0]) or not texts[0].strip():
            rebuilt = _rebuild_two_minute_hook(topic)
            logger.warning(
                "Rebuilt 2-minute-rule hook: %r → %r", texts[0], rebuilt
            )
            texts[0] = rebuilt

    # verb dedupe on body slides only
    body_idxs = [i for i, r in enumerate(roles) if r == "body"]
    if body_idxs:
        bodies = [texts[i] for i in body_idxs]
        fixed_bodies = _dedupe_body_verb_openers_list(bodies)
        for i, new_text in zip(body_idxs, fixed_bodies):
            texts[i] = new_text

    # product leaks
    if not product:
        for leak in ("FocusFlow", "focusflow", "VentNow", "ventnow"):
            for i in body_idxs:
                if leak.lower() in texts[i].lower():
                    texts[i] = re.sub(leak, "", texts[i], flags=re.I)
                    texts[i] = re.sub(r"\s+", " ", texts[i]).strip(" ,.-")

    for i in body_idxs:
        n = _word_count(texts[i])
        if n < 6:
            logger.warning(
                "Short body slide[%d] (%d words < 6): %r", i, n, texts[i]
            )

    # Сначала visual_scene (без DNA casting), потом query строго из неё
    from core.query_forge import scrub_dna_from_scene

    clean_scenes: list[str] = []
    for text, q, scene in zip(texts, queries, scenes):
        clean_scene = scrub_dna_from_scene(scene or "")
        if len(clean_scene) < 12 or _has_cyrillic(clean_scene):
            clean_scene = scrub_dna_from_scene(_fallback_visual_scene(text, q))
        clean_scenes.append(clean_scene)

    queries = _sanitize_carousel_queries(
        queries, texts, topic=topic, visual_scenes=clean_scenes
    )

    from core.query_forge import own_slide_query

    out: list[GeneratedSlide] = []
    for idx, (text, q, role, scene) in enumerate(
        zip(texts, queries, roles, clean_scenes)
    ):
        # One QueryOwner — no forge/inject/align ping-pong
        clean_q = own_slide_query(
            slide_text=text,
            visual_scene=scene,
            topic=topic,
            slide_index=idx,
            draft_query=q,
            character_dna=dna if isinstance(dna, dict) else None,
        )
        out.append(
            GeneratedSlide(
                text=text,
                search_query=clean_q,
                role=role,
                visual_scene=scene,
            )
        )

    cta_text = _fix_cta_grammar(out[-1].text)
    if _is_empty_cta(cta_text) or not _cta_grammar_ok(cta_text):
        cta_text = EMPTY_CTA_REPLACEMENT
    out[-1] = GeneratedSlide(
        text=cta_text,
        search_query=out[-1].search_query,
        role="cta",
        visual_scene=out[-1].visual_scene,
    )

    # Exact-query uniqueness (DNA inject often collapses to same "hands X hair")
    seen_exact: set[str] = set()
    diversifiers = (
        "mirror",
        "kitchen",
        "floor",
        "window",
        "bed",
        "desk",
        "doorway",
        "couch",
    )
    for i, slide in enumerate(out):
        key = re.sub(r"\s+", " ", (slide.search_query or "").lower()).strip()
        if key and key not in seen_exact:
            seen_exact.add(key)
            continue
        scene = slide.visual_scene or slide.text
        nouns = extract_visual_scene_nouns(scene, limit=5)
        alt = ""
        if nouns:
            alt = search_query_from_visual_scene(
                " ".join(nouns[:3]), topic=topic
            )
        if not alt or re.sub(r"\s+", " ", alt.lower()).strip() in seen_exact:
            div = diversifiers[i % len(diversifiers)]
            base = key.split()[:2] if key else ["candid", "indoor"]
            alt = " ".join((base + [div, "candid"])[:4])
        alt = inject_character_markers_into_query(alt, dna, slide_index=i)
        try:
            from core.query_forge import own_slide_query

            alt = own_slide_query(
                slide_text=slide.text,
                visual_scene=slide.visual_scene,
                topic=topic,
                slide_index=i,
                draft_query=alt,
                character_dna=dna if isinstance(dna, dict) else None,
            )
        except Exception:
            pass
        alt_key = re.sub(r"\s+", " ", alt.lower()).strip()
        # last resort: append slide index token via unique noun
        if alt_key in seen_exact:
            alt = f"{alt} {diversifiers[(i + 3) % len(diversifiers)]}".strip()
            alt = _clamp_query_to_word_limit(alt) or alt
            alt_key = re.sub(r"\s+", " ", alt.lower()).strip()
        if alt_key != key:
            logger.warning(
                "Unique query slide[%d]: %r → %r", i, slide.search_query, alt
            )
        seen_exact.add(alt_key)
        out[i] = GeneratedSlide(
            text=slide.text,
            search_query=alt,
            role=slide.role,
            visual_scene=slide.visual_scene,
        )

    return out


# --- обратная совместимость для импортов из тестов/фабрики ---
def _normalize_slides(data: dict[str, Any]) -> list[GeneratedSlide]:
    return sanitize_and_slots_to_slides(data, product="", topic="")


def enforce_hook_math(slides: list[GeneratedSlide]) -> list[GeneratedSlide]:
    """No-op: list-hooks запрещены контрактом; оставлено для совместимости импортов."""
    return slides


def fix_hook_list_number(hook_text: str, actual_count: int) -> str:
    return hook_text
