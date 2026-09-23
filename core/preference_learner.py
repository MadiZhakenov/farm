#!/usr/bin/env python3
"""
PreferenceLearner — Continuous Active Learning для UGC-поиска.

Хранит веса в data/ugc_preferences.json.
Арена: Чемпион (exploit) vs Претендент (explore).
Темы: случайный слайд из viral_playbook или встроенный пул.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "ugc_preferences.json"
DEFAULT_DB = ROOT / "reelfarm_database.db"

WIN_DELTA = 1.0
LOSS_DELTA = 0.5
TIE_DELTA = 0.5  # Space: оба хорошие — лёгкий плюс обоим
BOTH_BAD_DELTA = 0.5  # X: оба плохие — штраф обоим

# Связки и токены UGC / explore-мутации
TRACKED_PHRASES: tuple[str, ...] = (
    "shot on iphone photo dump",
    "casual camera roll snapshot",
    "candid raw photo dump",
    "amateur flash photo",
    "raw photo dump",
    "candid flash",
    "mirror selfie",
    "girlhood aesthetic cozy",
    "pinterest girl aesthetic night",
    "bed rotting aesthetic",
    "cozy girl bedroom night",
    "bed mess",
    "photo dump",
    "camera roll",
    "shot on iphone",
    "flash photo",
    "raw photo",
    "casual snapshot",
)

TRACKED_TOKENS: tuple[str, ...] = (
    "iphone",
    "photo",
    "dump",
    "flash",
    "amateur",
    "candid",
    "raw",
    "casual",
    "snapshot",
    "camera",
    "roll",
    "messy",
    "bedroom",
    "nightstand",
    "selfie",
    "mirror",
    "girlhood",
    "cozy",
    "bed",
)

DEFAULT_MODIFIERS: tuple[str, ...] = (
    "girlhood aesthetic cozy",
    "pinterest girl aesthetic night",
    "bed rotting aesthetic",
    "cozy girl bedroom night",
    "shot on iphone photo dump",
    "casual camera roll snapshot",
)

# Explore-мутации (претендент) — ротация новых связок
EXPLORE_MUTATIONS: tuple[str, ...] = (
    "mirror selfie",
    "raw photo dump",
    "candid flash",
    "bed mess",
    "girlhood aesthetic cozy",
    "pinterest girl aesthetic night",
    "bed rotting aesthetic",
    "cozy girl bedroom night",
    "casual camera roll snapshot",
    "shot on iphone photo dump",
)

# 100 разнородных UGC-сценариев (fallback без БД)
FALLBACK_TOPICS: tuple[str, ...] = (
    "Turn off phone 1 hour before bed",
    "Drink water before your first coffee",
    "Make the bed as soon as you wake up",
    "Leave your phone in another room while working",
    "Write three priorities on paper each morning",
    "Take a 10 minute walk without headphones",
    "Put dirty clothes straight into the laundry basket",
    "Prep tomorrow outfit the night before",
    "Eat breakfast without scrolling",
    "Stretch for five minutes after sitting all day",
    "Charge your phone outside the bedroom",
    "Open a window for fresh air every morning",
    "Cook one simple meal instead of ordering",
    "Clear your desk before ending the workday",
    "Say no to one optional plan this week",
    "Read ten pages before sleep",
    "Floss every night without skipping",
    "Keep a glass of water on your nightstand",
    "Delete one unused app today",
    "Put shoes away when you walk in",
    "Journal one sentence about your day",
    "Do dishes before they pile up",
    "Take vitamins with breakfast",
    "Stretch your neck between meetings",
    "Use a paper notebook for brain dumps",
    "Walk while taking phone calls",
    "Set a hard bedtime alarm",
    "Buy groceries with a short list only",
    "Wash your face before bed",
    "Silence group chats after 9pm",
    "Tidy one drawer this evening",
    "Stand up every hour at your desk",
    "Pack your bag the night before",
    "Skip dessert twice this week",
    "Leave earlier so you are not rushing",
    "Drink herbal tea instead of late coffee",
    "Put laundry away the same day",
    "Keep only three tabs open",
    "Text less reply more in person",
    "Stretch calves after a long walk",
    "Wipe the kitchen counter after cooking",
    "Change pillowcases weekly",
    "Sit on the floor while stretching",
    "Log spending for one day",
    "Take stairs instead of elevator",
    "Leave sunglasses by the door",
    "Water your plants on Sundays",
    "Mute notifications during deep work",
    "Eat fruit before packaged snacks",
    "Hang your coat instead of tossing it",
    "Write a thank you note by hand",
    "Check the weather before dressing",
    "Keep charging cables in one box",
    "Do a two minute cold rinse",
    "Put leftovers in clear containers",
    "Stretch hips after sitting in a car",
    "Leave keys in the same bowl every day",
    "Brush teeth right after dinner",
    "Unsubscribe from one email list",
    "Wear sunscreen even on cloudy days",
    "Take photos of receipts not piles of paper",
    "Sit near a window while working",
    "Swap soda for sparkling water",
    "Fold laundry while a show plays",
    "Keep a spare charger in your bag",
    "Stretch shoulders before sleep",
    "Throw out expired fridge items",
    "Walk the long way home once a week",
    "Leave your laptop closed during meals",
    "Put dirty dishes in the sink immediately",
    "Keep nail clippers in the bathroom drawer",
    "Schedule one no plans evening",
    "Wipe phone screen every night",
    "Wear comfortable shoes for errands",
    "Keep a tote for thrift or returns",
    "Eat dinner at the table not the couch",
    "Do a short body scan before sleep",
    "Leave rainy day shoes by the entrance",
    "Refill the soap dispenser before empty",
    "Keep a book on the pillow",
    "Stretch wrists after typing",
    "Pack lunch the night before",
    "Turn lights warmer after sunset",
    "Keep a shopping list on the fridge",
    "Air out sneakers after long walks",
    "Sit up straight for one full meeting",
    "Put makeup away after use",
    "Drink water after every coffee",
    "Keep a trash bag in the car",
    "Change into home clothes after work",
    "Leave the bathroom fan on after shower",
    "Keep stamps with envelopes together",
    "Stretch quads after running",
    "Clear camera roll of blurry shots",
    "Put vitamins next to the kettle",
    "Leave a sticky note with one goal",
    "Wear layers instead of cranking heat",
    "Keep a reusable bottle filled",
    "Wipe bathroom mirror weekly",
    "End the day with phone face down",
)

_lock = threading.RLock()
_topic_cursor = 0


def _extract_keywords(query: str) -> list[str]:
    """Достаёт отслеживаемые фразы/токены из поискового запроса."""
    low = re.sub(r"\s+", " ", (query or "").lower()).strip()
    found: list[str] = []
    remaining = low
    for phrase in sorted(TRACKED_PHRASES, key=len, reverse=True):
        if phrase in remaining:
            found.append(phrase)
            remaining = remaining.replace(phrase, " ")
    tokens = re.findall(r"[a-z0-9.]{3,}", remaining)
    for tok in tokens:
        if tok in TRACKED_TOKENS and tok not in found:
            found.append(tok)
    if not found:
        stop = {"the", "and", "for", "with", "on", "in", "of", "to", "a", "an"}
        found = [t for t in re.findall(r"[a-z]{4,}", low) if t not in stop][:4]
    return found


def _scene_from_slide(slide_text: str) -> str:
    """Простая бытовая сцена из текста слайда (без UGC-хвоста)."""
    stop = {
        "the", "and", "for", "that", "with", "your", "you", "this", "from",
        "have", "will", "are", "not", "but", "can", "how", "why", "what",
        "when", "just", "into", "before", "after", "every", "without",
    }
    words = [
        w.lower()
        for w in re.findall(r"[A-Za-z]{3,}", slide_text or "")
        if w.lower() not in stop
    ]
    if not words:
        return "messy bedroom everyday moment"
    return " ".join(words[:7])


def _clean_slide(s: str) -> str:
    t = re.sub(r"\s+", " ", (s or "").strip())
    return t[:160]


class PreferenceLearner:
    def __init__(
        self,
        path: Path | None = None,
        db_path: Path | None = None,
    ) -> None:
        self.path = path or DEFAULT_PATH
        self.db_path = db_path or DEFAULT_DB
        self._data: dict[str, Any] = {"weights": {}, "choices": 0, "history": []}
        self._topic_cache: list[str] = []
        self._load()
        self._warm_topics()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = raw
                self._data.setdefault("weights", {})
                self._data.setdefault("choices", 0)
                self._data.setdefault("history", [])
        except (OSError, json.JSONDecodeError):
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def _warm_topics(self) -> None:
        """Подтянуть слайды из viral_playbook (много сохранений)."""
        topics: list[str] = []
        if self.db_path.is_file():
            try:
                conn = sqlite3.connect(str(self.db_path), timeout=5.0)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT real_hook, slides_text_json, bookmarks
                    FROM viral_playbook
                    WHERE slides_text_json IS NOT NULL
                      AND length(trim(slides_text_json)) > 10
                    ORDER BY bookmarks DESC
                    LIMIT 400
                    """
                ).fetchall()
                conn.close()
                for row in rows:
                    try:
                        texts = json.loads(row["slides_text_json"] or "[]")
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(texts, list):
                        continue
                    for t in texts:
                        cleaned = _clean_slide(str(t))
                        if len(cleaned) >= 12 and cleaned.lower() not in {
                            x.lower() for x in topics
                        }:
                            topics.append(cleaned)
                    hook = _clean_slide(str(row["real_hook"] or ""))
                    if len(hook) >= 12 and hook.lower() not in {
                        x.lower() for x in topics
                    }:
                        topics.append(hook)
            except Exception:
                topics = []
        self._topic_cache = topics

    def get_next_training_topic(self) -> str:
        """
        Случайный реальный слайд из viral_playbook (высокие saves).
        Fallback — ротация встроенного пула из 100 сценариев.
        """
        global _topic_cursor
        with _lock:
            if self._topic_cache:
                return random.choice(self._topic_cache)
            topic = FALLBACK_TOPICS[_topic_cursor % len(FALLBACK_TOPICS)]
            _topic_cursor += 1
            return topic

    def log_choice(self, winner_query: str, loser_query: str) -> dict[str, float]:
        """
        Победитель +1.0, проигравший −0.5 (пол ≥ 0). Сохранение сразу на диск.
        """
        with _lock:
            self._load()
            weights: dict[str, float] = dict(self._data.get("weights") or {})
            winners = _extract_keywords(winner_query)
            losers = _extract_keywords(loser_query)
            touched: dict[str, float] = {}

            for key in winners:
                weights[key] = float(weights.get(key, 0.0)) + WIN_DELTA
                touched[key] = weights[key]
            for key in losers:
                if key in winners:
                    continue
                weights[key] = max(0.0, float(weights.get(key, 0.0)) - LOSS_DELTA)
                touched[key] = weights[key]

            self._data["weights"] = weights
            self._data["choices"] = int(self._data.get("choices") or 0) + 1
            hist = list(self._data.get("history") or [])
            hist.append(
                {
                    "winner": winner_query[:160],
                    "loser": loser_query[:160],
                    "winner_keys": winners,
                    "loser_keys": losers,
                }
            )
            self._data["history"] = hist[-120:]
            self._save()
            return touched

    def log_both_good(self, query_a: str, query_b: str) -> dict[str, float]:
        """
        Space / ничья: оба варианта хорошие.
        Ключевики обеих сторон получают +TIE_DELTA (без штрафа).
        """
        with _lock:
            self._load()
            weights: dict[str, float] = dict(self._data.get("weights") or {})
            keys = list(
                dict.fromkeys(
                    _extract_keywords(query_a) + _extract_keywords(query_b)
                )
            )
            touched: dict[str, float] = {}
            for key in keys:
                weights[key] = float(weights.get(key, 0.0)) + TIE_DELTA
                touched[key] = weights[key]

            self._data["weights"] = weights
            self._data["choices"] = int(self._data.get("choices") or 0) + 1
            hist = list(self._data.get("history") or [])
            hist.append(
                {
                    "tie": True,
                    "query_a": (query_a or "")[:160],
                    "query_b": (query_b or "")[:160],
                    "keys": keys,
                }
            )
            self._data["history"] = hist[-120:]
            self._save()
            return touched

    def log_both_bad(self, query_a: str, query_b: str) -> dict[str, float]:
        """
        X / оба плохие: ключевики обеих сторон −BOTH_BAD_DELTA (пол ≥ 0).
        """
        with _lock:
            self._load()
            weights: dict[str, float] = dict(self._data.get("weights") or {})
            keys = list(
                dict.fromkeys(
                    _extract_keywords(query_a) + _extract_keywords(query_b)
                )
            )
            touched: dict[str, float] = {}
            for key in keys:
                weights[key] = max(
                    0.0, float(weights.get(key, 0.0)) - BOTH_BAD_DELTA
                )
                touched[key] = weights[key]

            self._data["weights"] = weights
            self._data["choices"] = int(self._data.get("choices") or 0) + 1
            hist = list(self._data.get("history") or [])
            hist.append(
                {
                    "both_bad": True,
                    "query_a": (query_a or "")[:160],
                    "query_b": (query_b or "")[:160],
                    "keys": keys,
                }
            )
            self._data["history"] = hist[-120:]
            self._save()
            return touched

    def get_best_modifiers(self) -> list[str]:
        """Топ-3 любимых UGC-связок (актуальные веса с диска)."""
        with _lock:
            self._load()
            weights: dict[str, float] = dict(self._data.get("weights") or {})

        has_signal = any(float(v) > 0 for v in weights.values())
        if not has_signal:
            return list(DEFAULT_MODIFIERS[:3])

        scored: list[tuple[float, int, str]] = []
        seen: set[str] = set()
        for i, mod in enumerate(DEFAULT_MODIFIERS):
            score = float(weights.get(mod, 0.0))
            for part in _extract_keywords(mod):
                if part != mod:
                    score += float(weights.get(part, 0.0)) * 0.5
            scored.append((score, i, mod))
            seen.add(mod)

        for phrase in TRACKED_PHRASES:
            if phrase in seen:
                continue
            w = float(weights.get(phrase, 0.0))
            if w > 0:
                scored.append((w, 100, phrase))
                seen.add(phrase)

        # одиночные токены с высоким весом тоже в топ
        for tok, w in weights.items():
            if tok in seen or float(w) <= 0:
                continue
            if tok in TRACKED_TOKENS or tok in TRACKED_PHRASES:
                scored.append((float(w), 200, tok))
                seen.add(tok)

        scored.sort(key=lambda x: (-x[0], x[1]))
        banned_bits = ("0.5x", "lightbulb", "ceiling", "blinds", "bare wall", "empty desk")
        top: list[str] = []
        for _, _, m in scored:
            low = m.lower()
            if any(b in low for b in banned_bits):
                continue
            top.append(m)
            if len(top) >= 3:
                break
        for mod in DEFAULT_MODIFIERS:
            if len(top) >= 3:
                break
            if mod not in top:
                top.append(mod)
        return top[:3]

    def get_top_keywords(self, n: int = 3) -> list[str]:
        """Топ-N ключевиков с наивысшим положительным весом."""
        return self.get_best_modifiers()[:n]

    def generate_competing_queries(self, slide_text: str) -> tuple[str, str]:
        """
        А = Чемпион (exploit): сцена + топ-3 ключевых слов.
        B = Претендент (explore): сцена + UGC-мутация из пула explore.
        """
        from core.harvester import scrub_banned_query_terms

        scene = scrub_banned_query_terms(_scene_from_slide(slide_text))
        top = self.get_top_keywords(3)
        # Чемпион: склеить топ-3 (уникальные), приоритет полным фразам
        champ_bits: list[str] = []
        for k in top:
            if k.lower() not in " ".join(champ_bits).lower():
                champ_bits.append(k)
        if not champ_bits:
            champ_bits = list(DEFAULT_MODIFIERS[:2])
        query_a = f"{scene} {' '.join(champ_bits[:3])}".strip()

        # Претендент: мутация, которой нет у чемпиона
        champ_blob = " ".join(champ_bits).lower()
        explore_pool = [
            m for m in EXPLORE_MUTATIONS if m.lower() not in champ_blob
        ] or list(EXPLORE_MUTATIONS)
        mutation = random.choice(explore_pool)
        # слегка сдвинуть сцену
        alt_scene = scene
        if "phone" in scene:
            alt_scene = f"{scene} dark room"
        elif "bed" in scene:
            alt_scene = f"{scene} morning light"
        else:
            alt_scene = f"{scene} home"
        query_b = f"{scrub_banned_query_terms(alt_scene)} {mutation}".strip()

        query_a = scrub_banned_query_terms(query_a)[:160]
        query_b = scrub_banned_query_terms(query_b)[:160]
        return query_a, query_b

    def snapshot(self) -> dict[str, Any]:
        with _lock:
            self._load()
            top = self.get_best_modifiers()
            return {
                "choices": int(self._data.get("choices") or 0),
                "top_modifiers": top,
                "weights": dict(
                    sorted(
                        (self._data.get("weights") or {}).items(),
                        key=lambda kv: (-float(kv[1]), kv[0]),
                    )[:20]
                ),
            }

    def status_line(self) -> str:
        snap = self.snapshot()
        top = ", ".join(snap["top_modifiers"][:3]) or "—"
        return (
            f"Прокачано раундов: {snap['choices']} | "
            f"Доминирующий стиль: [{top}] | "
            f"Статус: Обучается на лету"
        )
