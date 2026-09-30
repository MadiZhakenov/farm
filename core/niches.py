#!/usr/bin/env python3
"""
Ниши контента: определение по словам, хештеги и фильтр тем под категорию.

Используется:
  - caption_engine  -> хештеги по теме (а не всегда #productivity)
  - batch_factory   -> темы/карусели, которые ушли не в ту категорию,
                       пропускаются (пример: «отражение в коридоре» в пачке про еду)
Без сети и без моделей — только словари, чтобы поведение было предсказуемым.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Sequence

# niche -> ключевые слова (корни, ищутся как начало слова)
NICHE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "food": (
        "food", "eat", "ate", "eating", "meal", "snack", "hungr", "hunger",
        "calorie", "diet", "fridge", "pantry", "dinner", "lunch", "breakfast",
        "brunch", "sugar", "carb", "bread", "sourdough", "pizza", "pasta",
        "binge", "craving", "cookie", "oreo", "chips", "almond", "salad",
        "protein", "kale", "juice", "soda", "coffee", "yogurt", "fasting",
        "fast", "macros", "menu", "recipe", "leftover", "plate", "kitchen",
        "chocolate", "peanut", "sandwich", "zucchini", "olive", "gummies",
        "cheat", "nutrition", "fullness", "full", "starving", "stomach",
        "bite", "cereal", "ice cream", "grocery",
    ),
    "body_image": (
        "body", "mirror", "reflection", "weight", "scale", "jeans", "pants",
        "size", "dress", "clothes", "shopping", "bloat", "belly", "thighs",
        "skinny", "shrink", "fit into",
    ),
    "fitness": (
        "gym", "workout", "run", "running", "treadmill", "pilates", "yoga",
        "lift", "cardio", "steps", "miles", "exercise", "training",
    ),
    "skincare": (
        "skin", "skincare", "serum", "acne", "glow", "moisturizer", "spf",
        "makeup", "vanity",
    ),
    "relationships": (
        "boyfriend", "girlfriend", "partner", "relationship", "dating", "date",
        "ex", "breakup", "text back", "situationship", "crush", "love",
    ),
    "productivity": (
        "work", "task", "deadline", "procrastinat", "productive", "focus",
        "study", "email", "boss", "office", "laptop", "meeting", "project",
        "to-do", "todo", "planner", "habit",
    ),
    "mental_health": (
        "anxiety", "anxious", "overthink", "panic", "depress", "therapy",
        "burnout", "spiral", "lonely", "stress", "overwhelm", "boundar",
    ),
    "sleep": ("sleep", "insomnia", "bedtime", "3am", "nap", "tired", "alarm"),
    "money": (
        "money", "budget", "spend", "salary", "rent", "debt", "save money",
        "shopping cart", "paycheck",
    ),
}

# Смежные ниши, которые не считаются «уходом из категории»
COMPATIBLE: dict[str, frozenset[str]] = {
    "food": frozenset({"food"}),
    "body_image": frozenset({"body_image", "food", "fitness"}),
    "fitness": frozenset({"fitness", "body_image", "food"}),
    "mental_health": frozenset({"mental_health", "sleep", "relationships"}),
    "productivity": frozenset({"productivity", "mental_health"}),
}

HASHTAGS: dict[str, str] = {
    "food": "#foodfreedom #intuitiveeating #foodnoise #dietculture #healthymindset #selfcompassion #relationshipwithfood",
    "body_image": "#bodyimage #bodyneutrality #selflove #dietculture #selfcompassion #healingjourney #mindset",
    "fitness": "#fitnessjourney #gymtok #workoutmotivation #healthyhabits #fitnessmindset #selfcare #mindset",
    "skincare": "#skincare #skincareroutine #glowup #selfcare #skintok #beautytips #selflove",
    "relationships": "#relationships #datingadvice #selfworth #healing #boundaries #lovelife #mindset",
    "productivity": "#productivity #discipline #focus #habits #selfgrowth #mindset #motivation",
    "mental_health": "#mentalhealth #healing #selfawareness #mindset #growth #anxiety #boundaries",
    "sleep": "#sleep #sleepbetter #nightroutine #selfcare #mentalhealth #rest #mindset",
    "money": "#moneytips #personalfinance #budgeting #moneymindset #financialfreedom #saving #mindset",
}
DEFAULT_HASHTAGS = HASHTAGS["productivity"]

_TOKEN_RE = re.compile(r"[a-z0-9'-]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower().replace("’", "'"))


def niche_scores(text: str) -> Counter[str]:
    """Сколько слов каждой ниши встречается в тексте."""
    low = (text or "").lower().replace("’", "'")
    toks = _tokens(low)
    scores: Counter[str] = Counter()
    for niche, words in NICHE_KEYWORDS.items():
        n = 0
        for w in words:
            if " " in w or "-" in w:
                n += low.count(w)
            else:
                n += sum(1 for t in toks if t == w or (len(w) >= 4 and t.startswith(w)))
        if n:
            scores[niche] = n
    return scores


def detect_niche(text: str, *, default: str = "productivity") -> str:
    scores = niche_scores(text)
    if not scores:
        return default
    return scores.most_common(1)[0][0]


def hashtags_for(topic: str = "", texts: Sequence[str] = ()) -> str:
    """Тема весит вдвое больше текстов слайдов."""
    scores = niche_scores(" ".join(texts))
    for k, v in niche_scores(topic).items():
        scores[k] += 2 * v
    if not scores:
        return DEFAULT_HASHTAGS
    niche = scores.most_common(1)[0][0]
    return HASHTAGS.get(niche, DEFAULT_HASHTAGS)


def dominant_category(topics: Iterable[str], *, min_share: float = 0.5) -> str | None:
    """
    Главная ниша списка тем (если её доля >= min_share), иначе None —
    тогда фильтр по категории не включается (смешанный список).
    """
    niches = [detect_niche(t, default="") for t in topics if (t or "").strip()]
    niches = [n for n in niches if n]
    if len(niches) < 3:
        return None
    niche, cnt = Counter(niches).most_common(1)[0]
    if cnt / len(niches) < min_share:
        return None
    return niche


def fits_category(
    category: str | None,
    topic: str = "",
    texts: Sequence[str] = (),
    *,
    min_hits: int = 2,
) -> bool:
    """
    True, если тема+тексты карусели про категорию.
    Нужно >= min_hits слов категории (тема считается дважды).
    """
    if not category:
        return True
    allowed = COMPATIBLE.get(category, frozenset({category}))
    hits = 0
    for niche in allowed:
        if niche != category:
            continue
        hits += 2 * niche_scores(topic).get(niche, 0)
        hits += niche_scores(" ".join(texts)).get(niche, 0)
    return hits >= min_hits
