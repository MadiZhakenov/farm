#!/usr/bin/env python3
"""
Динамическая таксономия вирусных Pinterest-запросов.

Источник: data/viral_query_patterns.json (Gemini Vision + локальный SigLIP).
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATTERNS_PATH = ROOT / "data" / "viral_query_patterns.json"

# Ниша → ключевые слова для матчинга тегов / архетипов
NICHE_KEYS: dict[str, tuple[str, ...]] = {
    "fitness": (
        "gym", "workout", "protein", "pilates", "yoga", "shake", "training", "mirror selfie",
    ),
    "skincare": (
        "skincare", "glow", "skin", "vanity", "clean girl", "bathroom", "routine",
    ),
    "beauty": (
        "skincare", "glow", "skin", "vanity", "clean girl", "bathroom", "mirror selfie",
    ),
    "study": (
        "gilmore", "academia", "book", "journal", "study", "library", "reading", "desk", "notes",
    ),
    "intellectual": (
        "gilmore", "academia", "book", "journal", "study", "library", "reading",
    ),
    "cozy": (
        "cozy", "bed", "bedroom", "pajamas", "golden hour", "candle", "messy bed", "coffee cup",
    ),
    "bed": (
        "bed", "bedroom", "pajamas", "messy bed", "reading", "duvet",
    ),
    "relationships": (
        "couple", "relationship", "date", "sunset walk", "bar",
    ),
    "dating": (
        "couple", "relationship", "date", "sunset",
    ),
    "night": (
        "night", "city", "street", "window", "moody", "90s", "car",
    ),
    "career": (
        "laptop", "office", "desk", "workspace", "career",
    ),
    "self improvement": (
        "mirror selfie", "journal", "study", "cozy", "laptop", "book",
    ),
}

# Архетип JSON → нишевые алиасы
ARCHETYPE_TO_NICHE: dict[str, str] = {
    "pov_hands": "fitness",  # часто selfie/gym; уточняется ключами
    "cozy_bed_space": "cozy",
    "silhouette_behind": "night",
    "warm_interior": "cozy",
    "flatlay_details": "skincare",
    "ambient_city_window": "night",
}

_DEFAULT_BY_NICHE: dict[str, list[str]] = {
    "fitness": [
        "gym mirror selfie shoes",
        "sneakers by gym bag",
        "water bottle gym floor",
        "workout shoes rack",
        "protein shaker gym",
    ],
    "skincare": [
        "serum bottle sink",
        "vanity mirror bottles",
        "bathroom sink splash",
        "hands applying serum",
        "skincare bottles shelf",
    ],
    "beauty": [
        "serum bottle sink",
        "vanity mirror bottles",
        "bathroom sink splash",
    ],
    "study": [
        "open journal pen",
        "spilled coffee laptop",
        "stacked books lamp",
        "highlighter notebook desk",
        "laptop charger cord",
    ],
    "intellectual": [
        "open journal pen",
        "stacked books lamp",
        "spilled coffee laptop",
    ],
    "cozy": [
        "tea mug window",
        "coffee mug desk",
        "socks on bed",
        "keys on table",
        "open journal pen",
    ],
    "bed": [
        "phone on pillow",
        "alarm clock nightstand",
        "water glass nightstand",
    ],
    "relationships": [
        "hands holding steering wheel",
        "two coffee cups",
        "keys on table",
        "rain on window",
    ],
    "dating": [
        "two coffee cups",
        "hands holding steering wheel",
        "keys on table",
    ],
    "night": [
        "hands holding steering wheel",
        "rain on window",
        "fridge open snack",
        "spilled coffee laptop",
    ],
    "career": [
        "spilled coffee laptop",
        "laptop charger cord",
        "keys on table",
        "open notebook desk",
    ],
    "self improvement": [
        "gym mirror selfie shoes",
        "open journal pen",
        "spilled coffee laptop",
        "sneakers by door",
    ],
}

_BANNED_EXACT = {
    "pov aesthetic",
    "protein aesthetic",
    "hour aesthetic",
    "shake aesthetic",
    "routine aesthetic",
    "moody aesthetic",
    "gym aesthetic",
    "night aesthetic",
    "girl aesthetic",
    "car aesthetic",
    "city aesthetic",
    "book aesthetic",
    "woman aesthetic",
    "glow cozy aesthetic",
    "skin cozy aesthetic",
    "protein cozy aesthetic",
    "dark academia",
    "dark academia aesthetic",
    "cozy aesthetic",
    "aesthetic night",
    "cozy night",
    "aesthetic mood",
    "vibe",
    "vibes",
    "cozy night city view",
    "rory gilmore aesthetic",
    "aesthetic journaling pov",
    "cozy study aesthetic",
}

_BANNED_SUBSTRINGS = (
    "dark academia",
    "cozy aesthetic",
    "aesthetic night",
    "cozy night",
    "aesthetic mood",
    "rory gilmore",
)

_LOCK = threading.Lock()
_MANAGER: QueryPatternManager | None = None


def is_clean_tag(q: str) -> bool:
    q = re.sub(r"\s+", " ", (q or "").strip().lower())
    words = re.findall(r"[a-z0-9']+", q)
    if len(words) < 2 or len(words) > 4:
        return False
    q = " ".join(words)
    if q in _BANNED_EXACT:
        return False
    if any(s in q for s in _BANNED_SUBSTRINGS):
        return False
    if "quote" in q:
        return False
    if "aesthetic" in words or "academia" in words or "vibe" in words or "vibes" in words:
        return False
    if len(words) == 2 and words[1] == "aesthetic" and words[0] in {
        "pov", "protein", "hour", "shake", "routine", "moody", "gym", "night",
        "girl", "car", "city", "book", "woman", "skin", "cozy", "glow",
    }:
        return False
    if words[0] == "hour":
        return False
    return True


class QueryPatternManager:
    """Загрузчик и выдачник вирусных Pinterest-тегов."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_PATTERNS_PATH
        self._mtime: float | None = None
        self.data: dict[str, Any] = {}
        self.all_tags: list[tuple[str, int]] = []  # (query, count)
        self.n_tags = 0
        self.n_samples = 0
        self.reload(force=True)

    def reload(self, *, force: bool = False) -> bool:
        if not self.path.is_file():
            if force or not self.data:
                self.data = {}
                self.all_tags = []
                self.n_tags = 0
                self.n_samples = 0
            return False
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return False
        if not force and self._mtime == mtime and self.data:
            return True
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("query_patterns load failed: %s", exc)
            return False

        self.data = raw if isinstance(raw, dict) else {}
        self._mtime = mtime
        self.n_samples = int(self.data.get("n_samples") or 0)

        scored: dict[str, int] = {}
        for item in self.data.get("query_frequency") or []:
            q = str(item.get("query") or "").strip().lower()
            if not is_clean_tag(q):
                continue
            scored[q] = max(scored.get(q, 0), int(item.get("count") or 0))
        for arch, block in (self.data.get("archetypes") or {}).items():
            del arch
            for item in block.get("top_queries") or []:
                q = str(item.get("query") or "").strip().lower()
                if not is_clean_tag(q):
                    continue
                scored[q] = max(scored.get(q, 0), int(item.get("count") or 0))

        self.all_tags = sorted(scored.items(), key=lambda x: (-x[1], x[0]))
        self.n_tags = len(self.all_tags)
        return True

    def _normalize_niche(self, niche: str) -> str:
        low = re.sub(r"[\s_\-]+", " ", (niche or "").strip().lower())
        # прямое попадание
        if low in NICHE_KEYS:
            return low
        # алиасы
        aliases = {
            "fit": "fitness",
            "workout": "fitness",
            "gym": "fitness",
            "skin": "skincare",
            "clean girl": "skincare",
            "studytok": "study",
            "booktok": "study",
            "academia": "study",
            "relationship": "relationships",
            "romance": "relationships",
            "city": "night",
            "urban": "night",
            "bedroom": "cozy",
            "home": "cozy",
            "wellness": "cozy",
            "mental health": "self improvement",
            "productivity": "career",
            "office": "career",
        }
        for key, canon in aliases.items():
            if key in low:
                return canon
        for canon in NICHE_KEYS:
            if canon in low:
                return canon
        # архетип как ниша
        if low in ARCHETYPE_TO_NICHE:
            return ARCHETYPE_TO_NICHE[low]
        return low or "self improvement"

    def get_patterns_for_niche(self, niche: str, *, limit: int = 10) -> list[str]:
        """Топ эффективных 2–4 словных тегов под нишу/архетип."""
        self.reload()
        canon = self._normalize_niche(niche)
        keys = NICHE_KEYS.get(canon) or NICHE_KEYS.get("self improvement", ())
        # сильные маркеры ниши (предметные) vs слабые (общие selfie/cozy)
        strong_map = {
            "fitness": ("gym", "workout", "protein", "pilates", "yoga", "shake"),
            "skincare": ("skincare", "glow", "vanity", "clean girl", "bathroom"),
            "beauty": ("skincare", "glow", "vanity", "clean girl"),
            "study": ("gilmore", "academia", "book", "journal", "study", "library", "reading"),
            "intellectual": ("gilmore", "academia", "book", "journal"),
            "cozy": ("cozy", "bedroom", "pajamas", "golden hour", "messy bed", "candle"),
            "bed": ("bed", "bedroom", "pajamas", "messy bed"),
            "relationships": ("couple", "relationship", "date"),
            "dating": ("couple", "relationship", "date"),
            "night": ("night city", "street", "90s moody", "pov car", "window"),
            "career": ("laptop", "office", "workspace", "career", "desk"),
        }
        strong = strong_map.get(canon, ())

        def score(q: str, cnt: int) -> tuple[int, int, int]:
            has_strong = 1 if any(k in q for k in strong) else 0
            has_any = 1 if any(k in q for k in keys) else 0
            return (has_strong, has_any, cnt)

        ranked = sorted(
            ((q, c) for q, c in self.all_tags if any(k in q for k in keys) or any(k in q for k in strong)),
            key=lambda x: score(x[0], x[1]),
            reverse=True,
        )
        picked: list[str] = []
        for q, _cnt in ranked:
            if q not in picked:
                picked.append(q)
            if len(picked) >= limit:
                return picked

        for q in _DEFAULT_BY_NICHE.get(canon, _DEFAULT_BY_NICHE["self improvement"]):
            if is_clean_tag(q) and q not in picked:
                picked.append(q)
            if len(picked) >= limit:
                break

        if len(picked) < limit:
            for q, _ in self.all_tags:
                if q not in picked:
                    picked.append(q)
                if len(picked) >= limit:
                    break
        return picked[:limit]

    def get_top_archetypes_summary(self) -> str:
        """
        Компактный блок для системного промпта Gemini:
        PROVEN PINTEREST TAXONOMY …
        """
        self.reload()
        niches_order = (
            ("Fitness", "fitness"),
            ("Skincare/Beauty", "skincare"),
            ("Study/Intellectual", "study"),
            ("Cozy/Bed", "cozy"),
            ("Relationships/Night", "relationships"),
            ("Career", "career"),
        )
        lines = [
            "PROVEN PINTEREST TAXONOMY (Strictly 3-4 words per query):",
            "When generating `search_query`, search HUMAN SITUATION & VIBE — "
            "pose + place + optional aesthetic/candid. "
            f"Never map random slide words to objects "
            f"({self.n_samples or self.n_tags} labeled backgrounds, "
            f"{self.n_tags} tags as niche flavor only):",
        ]
        for label, key in niches_order:
            tags = self.get_patterns_for_niche(key, limit=4)
            fmt = ", ".join(f"'{t}'" for t in tags[:4])
            lines.append(f"- {label}: {fmt}")
        lines.append(
            "RULE: Every query = [pose/action] + [place/situation] + optional aesthetic|candid."
        )
        lines.append(
            "Invent a UNIQUE 3–4 word query from THIS slide's visual_scene — "
            "never recycle a fixed phrase bank across slides."
        )
        lines.append(
            "BANNED: literal word→object, 'dark academia', 'cozy aesthetic' alone, "
            "'aesthetic night', iphone/finsta/35mm, stock faces."
        )
        lines.append("NEVER write sentences. Exactly 3-4 words.")
        return "\n".join(lines)

    def status_line(self) -> str:
        self.reload()
        return (
            f"Loaded viral patterns: {self.n_tags} tags "
            f"from {self.path.as_posix()} ({self.n_samples} samples)"
        )


def get_query_pattern_manager(path: Path | None = None) -> QueryPatternManager:
    global _MANAGER
    with _LOCK:
        if _MANAGER is None or (path and Path(path) != _MANAGER.path):
            _MANAGER = QueryPatternManager(path)
        else:
            _MANAGER.reload()
        return _MANAGER
