#!/usr/bin/env python3
"""
Правила уровня всей карусели (фидбек 2026-09-29, пачка 06_food_body_image;
фидбек команды 2026-10-02 — «смысловые / несмысловые слайды», чипсы ×3).

1. Роли слайдов (смысловые — буквально по тексту, филлеры — настроение):
     1-й слайд            -> scene   (хук, кадр по сценарию)
     слайд с продуктом    -> product (кадр по сценарию, лимит предмета не действует)
     без продукта         -> один scene в середине (второй смысловой)
     остальная середина   -> neutral (филлер из своего «семейства» сцен)
     последний слайд      -> final   (всегда приятный нейтральный)
   Для тяжёлых тем (депрессия, горе, одиночество…) нейтральные кадры
   в середине могут быть тёмными/moody, последний — спокойный, но не грязный.
   Филлеры — только «живые» запросы (FILLER_LIVENESS по факту прогонов) и
   с предметами, которых ещё нет в карусели; смысловые слайды с одним
   предметом в запросе разводятся до поиска.

2. Грязь (грязная посуда, мусор, разлитое, гора снеков):
     не больше MAX_MESS_NORMAL кадров на карусель (для тяжёлых тем
     MAX_MESS_HEAVY) и НИКОГДА на последнем слайде.

3. Одно место (кухня+холодильник, кровать, стол…) — не больше
   MAX_SAME_PLACE слайдов на карусель.

4. Один предмет (снеки, дорога, окно, напиток, машина…) — не больше
   MAX_SAME_SUBJECT кадров на карусель; слайд с продуктом не считается.

5. Одно фото — одна карусель на всю серию: pin_id + отпечаток картинки
   (dHash) сверяются с учётом в PhotoVault. Филлеры (neutral/final) можно
   переиспользовать (банк филлеров батча, core/filler_bank.py).

Модуль не лезет в сеть. Картинки оцениваются тем же SigLIP, что и весь
пайплайн (core.taste_embedder); в тестах подставляется фейковый классификатор.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from PIL import Image

# ---------------------------------------------------------------------------
# Константы (пороги калибруются скриптом validate_rules.py)
# ---------------------------------------------------------------------------

ROLE_SCENE = "scene"
ROLE_PRODUCT = "product"
ROLE_NEUTRAL = "neutral"
ROLE_FINAL = "final"
SEMANTIC_ROLES = frozenset({ROLE_SCENE, ROLE_PRODUCT})
FILLER_ROLES = frozenset({ROLE_NEUTRAL, ROLE_FINAL})

RULES_ENABLED = True
MAX_MESS_NORMAL = 1
MAX_MESS_HEAVY = 2
MAX_SAME_PLACE = 2
MAX_SAME_SUBJECT = 1
# Замена кадра ради разнообразия предмета — только на кадр не менее живой
# (UGC-оценка пайплайна) больше чем на LIVE_MARGIN; иначе повтор остаётся.
# Цель — простые живые фото, разнообразие вторично (проверка 2026-10-02).
LIVE_MARGIN = 0.05


def _live(c: Any) -> float | None:
    if getattr(c, "ugc_scored", False):
        try:
            return float(getattr(c, "ugc_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            return None
    return None
# Сколько кандидатов слайда проверять (кандидаты уже отсортированы по рангу)
MAX_CHECK_PER_SLIDE = 8

# Пороги зависят от модели картинок (SigLIP / запасной CLIP). Подобраны
# validate_rules.py на 300 слайдах пачки 06 + ручной разметке (82 грязных кадра).
#   mess_margin    — насколько «грязный» якорь должен быть ближе «чистого»
#   place_temp     — температура softmax по местам
#   place_min_prob — уверенность, с которой место засчитывается (иначе "other")
CALIBRATION: dict[str, dict[str, float]] = {
    # SigLIP (основная модель фабрики): AUC грязь/чисто 0.95; при margin 0.018
    # находит 87% грязи, 84% срабатываний верные (14 ложных из 178 чистых).
    # Кухня: precision 0.89, recall 0.87.
    "google/siglip-base-patch16-224": {
        "mess_margin": 0.018,
        "place_temp": 0.01,
        "place_min_prob": 0.45,
    },
    # CLIP ViT-B/32: AUC грязь/чисто 0.93; при margin 0.022 находит 87% грязи,
    # 72% срабатываний верные. Кухня: precision 0.75, recall 0.94.
    "openai/clip-vit-base-patch32": {
        "mess_margin": 0.022,
        "place_temp": 0.02,
        "place_min_prob": 0.35,
    },
}
DEFAULT_BACKEND = "google/siglip-base-patch16-224"
# mess_score в meta — вероятность: 0.5 ровно на пороге модели
MESS_THRESHOLD = 0.5
MESS_SOFTMAX_TEMP = 0.01

# dHash: расстояние Хэмминга (из 64 бит), при котором считаем «то же фото»
FP_HAMMING_MAX = 10

# Места, на которые действует лимит MAX_SAME_PLACE
LIMITED_PLACES = frozenset(
    {"kitchen", "bed", "desk", "bathroom", "car", "cafe", "street"}
)

MESS_PROMPTS: tuple[str, ...] = (
    "dirty dishes piled in a kitchen sink",
    "a dirty plate with food leftovers and crumbs",
    "trash, garbage and food wrappers everywhere",
    "a messy cluttered kitchen counter with dirty dishes",
    "spilled coffee or a spilled drink on a table",
    "a pile of junk food bags and candy wrappers",
    "an overflowing trash can",
    "a dirty greasy stove with used pans",
)
CLEAN_PROMPTS: tuple[str, ...] = (
    "a clean tidy table",
    "a calm cozy room",
    "a cup of tea by a window",
    "a person walking outside",
    "a neat clean kitchen",
    "fresh food on a clean plate",
    "a city street",
    "an open fridge with food inside",
    "a bed with white sheets",
    "a desk with a laptop and notebook",
)
PLACE_PROMPTS: dict[str, tuple[str, ...]] = {
    "kitchen": (
        "a kitchen",
        "an open fridge",
        "a kitchen counter",
        "a pantry shelf with food",
        "a kitchen sink",
        "a stove with pans",
    ),
    "bed": ("a bed with sheets and pillows", "a bedroom", "lying in bed"),
    "desk": (
        "a desk with a laptop",
        "a work desk with papers",
        "a study desk with notebooks",
    ),
    "bathroom": ("a bathroom", "a bathroom mirror and sink"),
    "street": ("a city street", "a sidewalk outdoors", "a park outdoors"),
    "car": ("inside a car", "a view from a bus window"),
    "cafe": ("a cafe table", "a restaurant table"),
    "food": ("a close-up of food", "snacks on a surface"),
    "other": ("a photo of an object", "a hallway", "the sky"),
}

# Предмет кадра (что на фото), zero-shot по тем же эмбеддингам SigLIP.
# Проверено на 30 каруселях пачек 2026-10-01: чипсы -> snacks ~1.0,
# дорога -> road ~0.99, сумка в зал -> gym ~1.0; спорные кадры ниже 0.6.
SUBJECT_PROMPTS: dict[str, tuple[str, ...]] = {
    "snacks": ("a bag of chips", "snack bags and candy", "junk food snacks", "a bag of crisps on a couch"),
    "plate": ("a plate of food", "a meal on a plate", "a bowl of food", "breakfast on a plate"),
    "fruit": ("a bowl of fruit", "strawberries", "fresh fruit on a table"),
    "drink": ("a cup of coffee", "a mug of tea", "a glass of water", "an iced coffee"),
    "kitchen": ("a kitchen counter", "an open fridge", "a pantry shelf", "a kitchen at night"),
    "window": ("a window with curtains", "a view through a window", "a windowsill", "rain on a window"),
    "road": ("a road", "a city street", "a sidewalk", "a street at night"),
    "car": ("inside a car", "a car steering wheel", "a car interior at night", "a bus window"),
    "bed": ("a bed with pillows", "a bedroom with a bed", "lying in bed"),
    "desk": ("a desk with a laptop", "a desk with notebooks", "a work desk"),
    "phone": ("a phone screen", "a hand holding a smartphone"),
    "sky": ("the sky", "a sunset sky", "clouds", "a night sky"),
    "plants": ("flowers in a vase", "potted plants", "a garden"),
    "book": ("an open book", "a stack of books"),
    "bathroom": ("a bathroom mirror", "a bathroom sink"),
    "gym": ("a gym bag", "sneakers and workout gear", "a gym"),
    "clothes": ("folded clothes", "a pile of clothes", "an outfit on a chair"),
    "groceries": ("grocery bags", "a supermarket aisle"),
    "person": ("a portrait of a woman", "a selfie of a person", "a person's face"),
    "pets": ("a cat", "a dog", "a pet on a lap"),
    "room": ("a cozy living room", "a couch in a room", "a hallway"),
}
SUBJECT_TEMP = 0.01
SUBJECT_MIN_PROB = 0.6

# ---------------------------------------------------------------------------
# 1. Роли слайдов
# ---------------------------------------------------------------------------

_HEAVY_CUES: tuple[str, ...] = (
    "depress",
    "grief",
    "griev",
    "trauma",
    "lonely",
    "loneliness",
    "burnout",
    "burned out",
    "burnt out",
    "panic attack",
    "breakup",
    "break up",
    "broke up",
    "heartbreak",
    "numb",
    "hopeless",
    "worthless",
    "empty inside",
    "crying",
    "cried myself",
    "funeral",
    "loss of",
)


def is_heavy_topic(topic: str = "", texts: Iterable[str] = ()) -> bool:
    """Тяжёлая тема — можно больше тёмных кадров в середине (не в конце)."""
    blob = " ".join([topic or "", *[t or "" for t in texts]]).lower()
    return any(c in blob for c in _HEAVY_CUES)


def plan_roles(n: int, *, product_index: int | None = None) -> list[str]:
    """
    Середина — сцена / филлер по очереди: сценные слайды ищутся буквально по
    тексту и дают живые бытовые кадры (только хук + продукт давали в 2 раза
    больше филлеров и сток, проверка 2026-10-02). Слайд с продуктом —
    смысловой (product).
      6 слайдов            -> scene, scene, neutral, scene, neutral, final
      6 слайдов, продукт 2 -> scene, scene, product, scene, neutral, final
    """
    n = int(n)
    if n <= 0:
        return []
    if n == 1:
        return [ROLE_SCENE]
    roles = [ROLE_SCENE] * n
    roles[-1] = ROLE_FINAL
    for i in range(1, n - 1):
        roles[i] = ROLE_SCENE if i % 2 == 1 else ROLE_NEUTRAL
    if product_index is not None and 0 < int(product_index) < n - 1:
        roles[int(product_index)] = ROLE_PRODUCT
    return roles


def product_names(product: str = "") -> list[str]:
    """
    Имена продукта из поля «Продукт»: «Приложение FocusFlow: лимит 3 задачи»
    -> ["focusflow"], «Cozy Home» -> ["cozy home"].
    """
    import re

    raw = (product or "").strip()
    if not raw:
        return []
    head = re.split(r"[:—–\-|(]", raw, maxsplit=1)[0].strip()
    head = re.sub(
        r"^(приложение|приложуха|app|the app|application|игра|game)\s+",
        "",
        head,
        flags=re.I,
    ).strip()
    head = re.sub(r"\s+(app|application|приложение)$", "", head, flags=re.I).strip()
    names: list[str] = []
    if head:
        names.append(head.lower())
    # бренд-слова латиницей с заглавной (FocusFlow, Cozy, Magic Sort)
    for brand in re.findall(r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*", raw):
        b = brand.lower()
        if b not in names and b not in {"app", "the"}:
            names.append(b)
    return names


def find_product_slide(texts: Sequence[str], product: str = "") -> int | None:
    """Индекс слайда (не хук и не финал), где назван продукт."""
    import re

    pats = [
        re.compile(r"(?<!\w)" + re.escape(n) + r"(?!\w)")
        for n in product_names(product)
        if len(n) >= 3
    ]
    if not pats:
        return None
    for i, text in enumerate(texts):
        low = (text or "").lower()
        if 0 < i < len(texts) - 1 and any(p.search(low) for p in pats):
            return i
    return None


# Банк филлер-запросов — по замеру выдачи Pinterest (probe_query_liveness.py,
# 2026-10-05; out/filler_bank_probe, out/query_liveness_v2): в первых 12
# кадрах ≥ 4 «живых без лица» (UGC ≥ 0.55, лиц нет), лица ≤ 25%, ИИ-метка
# ≤ 20%, чистильщик запросов оставляет запрос как есть. Форма «pov … /
# … candid / … real life» даёт живые фото; натюрморты и интерьеры
# («flowers vase table», «sheer curtains bedroom window») — сток (0 из 12).
NEUTRAL_LIGHT: tuple[str, ...] = (
    "pov reading book candid",
    "pov walking dog",
    "pov holding flowers candid",
    "pov headphones couch",
    "pov driving car",
    "pov watering plants",
    "pov sunset walk",
    "sky clouds window",
    "pov cat lap",
    "pov working laptop",
    "pov park walk",
    "pov holding phone bed",
    "pov looking out window",
    "sneakers walking sidewalk",
    "standing sneakers floor hallway",
    "flowers bouquet candid",
    "pov lying bed",
    "phone screen text candid",
)
NEUTRAL_FOOD: tuple[str, ...] = (
    "pov drinking tea candid",
    "pov drinking coffee",
    "coffee cup real life",
    "tea mug real life",
    "coffee cup candid",
)
NEUTRAL_MOODY: tuple[str, ...] = (
    "car window night candid",
    "laptop bed night candid",
    "pov walking rain",
    "pov looking out window",
    "pov lying bed",
    "pov holding phone bed",
    "pov headphones couch",
    "pov drinking tea candid",
)
FINAL_PLEASANT: tuple[str, ...] = (
    "pov sunset walk",
    "sky clouds window",
    "pov holding flowers candid",
    "pov walking dog",
    "pov cat lap",
    "coffee cup real life",
    "pov reading book candid",
    "flowers bouquet candid",
    "pov watering plants",
)
FINAL_CALM: tuple[str, ...] = (
    "pov drinking tea candid",
    "tea mug real life",
    "pov reading book candid",
    "pov cat lap",
    "pov looking out window",
    "sky clouds window",
    "pov holding flowers candid",
)

# Доля «живых без лица» в первых 12 кадрах выдачи (замер 2026-10-05).
# Нет в таблице — считается достаточной.
FILLER_LIVENESS: dict[str, float] = {
    "pov cat lap": 0.917,
    "pov reading book candid": 0.667,
    "pov walking dog": 0.667,
    "pov holding flowers candid": 0.583,
    "pov holding flowers": 0.583,
    "car window night candid": 0.583,
    "pov headphones couch": 0.5,
    "laptop bed night candid": 0.5,
    "pov drinking tea candid": 0.5,
    "pov driving car": 0.5,
    "pov watering plants": 0.5,
    "pov sunset walk": 0.5,
    "sky clouds window": 0.417,
    "flowers bouquet candid": 0.417,
    "phone screen text candid": 0.417,
    "pov working laptop": 0.417,
    "pov drinking coffee": 0.333,
    "pov park walk": 0.333,
    "pov holding phone bed": 0.333,
    "coffee cup real life": 0.333,
    "pov walking rain": 0.333,
    "tea mug real life": 0.333,
    "pov looking out window": 0.333,
    "pov lying bed": 0.333,
    "sneakers walking sidewalk": 0.333,
    "coffee cup candid": 0.333,
    "standing sneakers floor hallway": 0.333,
    # прежние филлеры — сток по замеру (для дозапросов и старых записей)
    "flowers vase table": 0.0,
    "sheer curtains bedroom window": 0.0,
    "window seat book": 0.0,
    "sunset city skyline": 0.0,
    "book coffee table": 0.0,
    "fresh bread bakery": 0.0,
    "strawberries bowl table": 0.0,
    "breakfast table croissant": 0.0,
    "park bench trees autumn": 0.0,
}
FILLER_LIVE_MIN = 0.33


def filler_liveness(query: str) -> float:
    return FILLER_LIVENESS.get((query or "").strip().lower(), 0.5)


# Предмет, который скорее всего окажется на кадре по запросу (те же имена,
# что в SUBJECT_PROMPTS). Нужен ДО поиска: два слайда с одним предметом в
# запросе — это и есть «чипсы ×3 / кофе ×4».
QUERY_SUBJECT_WORDS: dict[str, tuple[str, ...]] = {
    "drink": ("coffee", "tea", "mug", "cup", "latte", "iced", "glass", "water", "matcha", "drink"),
    "road": ("street", "sidewalk", "walk", "walking", "sneakers", "bicycle", "road", "crosswalk"),
    "sky": ("sky", "sunset", "sunrise", "clouds", "skyline"),
    "window": ("window", "windowsill", "curtains"),
    "car": ("car", "bus", "tram", "train", "steering", "wheel", "subway"),
    "plants": ("flowers", "flower", "plant", "plants", "vase", "herbs", "garden", "bouquet"),
    "fruit": ("fruit", "strawberries", "lemons", "apples", "apple", "banana", "berries", "oranges"),
    "plate": ("plate", "bowl", "breakfast", "croissant", "bread", "pastries", "pasta", "meal",
              "dinner", "lunch", "salad", "toast", "eggs", "oatmeal", "soup", "sandwich"),
    "snacks": ("chip", "chips", "crisps", "crisp", "snack", "snacks", "candy", "cookies",
               "cookie", "crackers", "pretzel", "pretzels", "chocolate"),
    "kitchen": ("kitchen", "fridge", "pantry", "counter", "stove", "freezer"),
    "desk": ("desk", "laptop", "notebook", "computer", "keyboard", "planner"),
    "bed": ("bed", "sheets", "pillow", "pillows", "blanket", "duvet"),
    "book": ("book", "books", "reading"),
    "room": ("floor", "feet", "couch", "sofa", "hallway", "rug"),
    "candle": ("candle", "candles"),
    "phone": ("phone", "screen", "scrolling"),
    "gym": ("gym", "workout", "dumbbell", "dumbbells", "yoga", "treadmill"),
    "clothes": ("hoodie", "shirt", "clothes", "laundry", "jeans", "sweater", "outfit"),
    "bathroom": ("bathroom", "mirror", "shower", "bathtub"),
    "groceries": ("grocery", "groceries", "supermarket", "cart"),
    "pets": ("cat", "cats", "kitten", "dog", "dogs", "puppy"),
}
_WORD_SUBJECT = {w: k for k, ws in QUERY_SUBJECT_WORDS.items() for w in ws}


def query_subjects(query: str) -> set[str]:
    """Все предметы, названные в запросе (для разведения смысловых слайдов)."""
    import re

    return {
        _WORD_SUBJECT[w]
        for w in re.findall(r"[a-z]+", (query or "").lower())
        if w in _WORD_SUBJECT
    }


# Главный предмет кадра, если в запросе их несколько: «bus window» — автобус,
# «sky clouds window» — небо, «tea mug windowsill» — напиток
_SUBJECT_PRIORITY = (
    "snacks", "fruit", "plate", "drink", "car", "phone", "gym", "groceries",
    "bathroom", "clothes", "desk", "bed", "candle", "book", "plants",
    "kitchen", "pets", "sky", "road", "window", "room",
)


def query_subject(query: str) -> str:
    subj = query_subjects(query)
    return next((s for s in _SUBJECT_PRIORITY if s in subj), "other")


# Проверка запросов до поиска: «главное существительное» запроса —
# слова без общих (время суток, ракурс, настроение, действие)
_GENERIC_QUERY_WORDS = frozenset(
    {
        "a", "an", "the", "of", "on", "in", "at", "with", "and",
        "candid", "aesthetic", "cozy", "night", "morning", "evening",
        "daytime", "day", "dark", "dim", "light", "soft", "warm", "alone",
        "home", "photo", "close", "closeup", "up", "pov", "standing",
        "sitting", "walking", "looking", "holding", "hands", "hand",
        "empty", "quiet", "calm", "clean", "fresh", "old", "new", "small",
        "big", "late", "early", "city", "room", "table", "floor", "bag",
    }
)
_NOUN_SYNONYMS: dict[str, str] = {
    "crisp": "chip",
    "chips": "chip",
    "snacks": "snack",
    "mug": "cup",
    "latte": "coffee",
    "espresso": "coffee",
    "fridge": "fridge",
    "refrigerator": "fridge",
    "road": "street",
    "sidewalk": "street",
    "pavement": "street",
    "windowsill": "window",
    "auto": "car",
}


def query_nouns(query: str) -> set[str]:
    """Значимые слова запроса (ед. число, синонимы сведены)."""
    import re

    out: set[str] = set()
    for w in re.findall(r"[a-z]+", (query or "").lower()):
        if w in _GENERIC_QUERY_WORDS or len(w) < 3:
            continue
        w = _NOUN_SYNONYMS.get(w, w)
        if len(w) > 3 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(_NOUN_SYNONYMS.get(w, w))
    return out


def queries_conflict(a: str, b: str) -> bool:
    """
    Два запроса тянут один предмет («chip bag couch» / «chips bag counter»,
    «coffee mug desk» / «hands holding coffee cup») или это один и тот же
    запрос другими словами.
    """
    sa, sb = query_subjects(a), query_subjects(b)
    if sa and sb:
        return bool(sa & sb)
    na, nb = query_nouns(a), query_nouns(b)
    return bool(na) and na == nb

_FOOD_CUES: tuple[str, ...] = (
    "food",
    "eat",
    "ate ",
    "meal",
    "snack",
    "hungry",
    "hunger",
    "calorie",
    "diet",
    "fridge",
    "pantry",
    "dinner",
    "lunch",
    "breakfast",
    "sugar",
    "carb",
    "bread",
    "pizza",
    "pasta",
    "binge",
)


def _stable_seed(*parts: Any) -> int:
    raw = "|".join(str(p) for p in parts)
    return int(hashlib.md5(raw.encode("utf-8")).hexdigest()[:8], 16)


@dataclass
class SlidePhotoPlan:
    """Что искать для слайда. text — только для поиска/релевантности."""

    role: str
    query: str
    search_text: str
    visual_scene: str
    alts: list[str] = field(default_factory=list)


def neutral_plan(
    role: str,
    *,
    topic: str = "",
    slide_text: str = "",
    slide_index: int = 0,
    heavy: bool = False,
    seed: Any = "",
    taken: set[str] | None = None,
    used_subjects: set[str] | None = None,
    avoid_queries: Sequence[str] = (),
    prefer: Iterable[str] = (),
) -> SlidePhotoPlan:
    """
    Нейтральный / финальный запрос из одобренных пулов. Порядок важности:
    живой запрос (FILLER_LIVENESS ≥ FILLER_LIVE_MIN) → предмет, которого
    ещё нет в карусели (used_subjects, предметы avoid_queries) → не
    повторять запросы из taken. prefer — запросы с кадрами в банке филлеров.
    """
    taken = taken if taken is not None else set()
    used_subjects = used_subjects if used_subjects is not None else set()
    blob = f"{topic} {slide_text}".lower()
    foodish = any(c in blob for c in _FOOD_CUES)
    if role == ROLE_FINAL:
        pool = list(FINAL_CALM if heavy else FINAL_PLEASANT)
        mood = "calm pleasant" if heavy else "bright pleasant"
    else:
        pool = list(NEUTRAL_MOODY if heavy else NEUTRAL_LIGHT)
        if foodish and not heavy:
            # чередуем: приятная еда / спокойный быт
            mixed: list[str] = []
            for a, b in zip(NEUTRAL_FOOD, NEUTRAL_LIGHT):
                mixed += [a, b]
            pool = mixed + [q for q in NEUTRAL_LIGHT if q not in mixed]
        mood = "quiet moody" if heavy else "calm neutral"
    start = _stable_seed(topic, seed, role, slide_index) % len(pool)
    ordered = pool[start:] + pool[:start]
    preferred = {p.lower() for p in prefer}
    if preferred:
        ordered = [q for q in ordered if q.lower() in preferred] + [
            q for q in ordered if q.lower() not in preferred
        ]
    busy = set(used_subjects)
    for a in avoid_queries:
        busy |= query_subjects(a)

    def ok(q: str, *, live: bool, subject: bool) -> bool:
        if q.lower() in taken:
            return False
        if live and filler_liveness(q) < FILLER_LIVE_MIN:
            return False
        if subject and query_subject(q) in busy:
            return False
        return True

    free: list[str] = []
    # живость важнее разнообразия: сначала живой запрос с новым предметом,
    # потом живой с повтором, и только потом стоковый
    for live, subject in ((True, True), (True, False), (False, True), (False, False)):
        free = [q for q in ordered if ok(q, live=live, subject=subject)]
        if free:
            break
    free = free or ordered
    query = free[0]
    # альты — живые запросы с тем же предметом (слайд остаётся «кофе» / «улицей»)
    subj = query_subject(query)
    same = [
        q for q in ordered
        if q != query and q.lower() not in taken
        and filler_liveness(q) >= FILLER_LIVE_MIN
        and (query_subject(q) == subj or query_subject(q) not in busy)
    ]
    alts = same[:2]
    taken.add(query.lower())
    if subj != "other":
        used_subjects.add(subj)
    scene = f"{mood} everyday photo, {query}, clean and tidy, nothing dirty"
    return SlidePhotoPlan(
        role=role,
        query=query,
        search_text=f"{mood} photo: {query}",
        visual_scene=scene,
        alts=alts,
    )


# «candid» в конце сценного запроса: +0.08 живости на реальных запросах
# Gemini, тема кадра не меняется (эксперимент 2026-10-05, 15 из 18). Чистильщик
# режет запросы длиннее 4 слов — берём первые 3 слова сцены.
_CANDID_DROP = frozenset({"candid", "alone", "aesthetic", "film", "my"})


def candid_variant(query: str) -> str:
    words = [w for w in (query or "").split() if w.lower() not in _CANDID_DROP]
    if len(words) < 2:
        return ""
    return " ".join(words[:3] + ["candid"])


def build_photo_plans(
    texts: Sequence[str],
    scene_specs: Sequence[tuple[str, str, list[str]]],
    *,
    topic: str = "",
    seed: Any = "",
    enabled: bool = True,
    product: str = "",
    prefer: Iterable[str] = (),
) -> tuple[list[SlidePhotoPlan], bool]:
    """
    scene_specs[i] = (query, visual_scene, alts) — сценарный запрос слайда
    (как раньше строил query_forge). Для neutral/final слайдов заменяется.
    product — имя продукта: его слайд смысловой (role=product).
    prefer — запросы филлеров, для которых уже есть кадры в банке батча.

    Проверка до поиска: второй смысловой слайд не должен делить главное
    существительное с хуком («chip bag couch» и «chips bag counter») —
    берётся его альт без общего существительного, иначе слайд становится
    филлером. Филлеры не делят существительные со смысловыми и берутся
    из разных семейств сцен.
    Возвращает (plans, heavy).
    """
    n = len(texts)
    heavy = is_heavy_topic(topic, texts)
    product_index = find_product_slide(texts, product) if enabled else None
    roles = plan_roles(n, product_index=product_index) if enabled else [ROLE_SCENE] * n
    taken: set[str] = set()
    used_subjects: set[str] = set()
    semantic_queries: list[str] = []
    plans: list[SlidePhotoPlan | None] = [None] * n
    # 1) смысловые слайды
    for i, (text, role) in enumerate(zip(texts, roles)):
        if role not in SEMANTIC_ROLES:
            continue
        q, scene, alts = scene_specs[i] if i < len(scene_specs) else ("", "", [])
        alts = [a for a in (alts or []) if a]
        if enabled and role == ROLE_SCENE and i > 0 and semantic_queries:
            chain = [c for c in [q, *alts] if c]
            fresh = [
                c for c in chain
                if not any(queries_conflict(c, s) for s in semantic_queries)
            ]
            if not fresh:
                print(
                    f"[plan] слайд {i + 1}: «{q}» повторяет предмет "
                    f"{sorted(query_subjects(q)) or sorted(query_nouns(q))} — делаю филлером"
                )
                roles[i] = ROLE_NEUTRAL
                continue
            if fresh[0] != q:
                print(f"[plan] слайд {i + 1}: «{q}» -> «{fresh[0]}» (другой предмет)")
            q, alts = fresh[0], fresh[1:]
        taken.add((q or "").lower())
        semantic_queries.append(q or "")
        alts = list(alts)
        if enabled and not any("candid" in (x or "").split() for x in [q, *alts]):
            cv = candid_variant(q)
            if cv and cv.lower() != (q or "").lower():
                alts = [cv] + alts
        plans[i] = SlidePhotoPlan(
            role=role,
            query=q,
            search_text=text,
            visual_scene=scene,
            alts=alts,
        )
    # 2) филлеры: живые запросы с предметами, которых ещё нет в карусели.
    # Финал первым — у него самый маленький пул.
    order = ([n - 1] if n and plans[n - 1] is None else []) + [
        i for i in range(n - 1) if plans[i] is None
    ]
    for i in order:
        text, role = texts[i], roles[i]
        plans[i] = neutral_plan(
            role,
            topic=topic,
            slide_text=text,
            slide_index=i,
            heavy=heavy,
            seed=seed,
            taken=taken,
            used_subjects=used_subjects,
            avoid_queries=semantic_queries,
            prefer=prefer,
        )
    return [p for p in plans if p is not None], heavy


# ---------------------------------------------------------------------------
# 2. Отпечаток картинки (для «одно фото — одна карусель»)
# ---------------------------------------------------------------------------


def image_fingerprint(image: Image.Image | None) -> int | None:
    """64-битный dHash: устойчив к размеру/сжатию, ловит перезаливы пина."""
    if image is None:
        return None
    try:
        g = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        px = list(g.tobytes())
    except Exception:
        return None
    bits = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
    return bits


def fp_to_hex(fp: int | None) -> str:
    return "" if fp is None else f"{fp:016x}"


def fp_from_hex(raw: str | None) -> int | None:
    try:
        return int(str(raw), 16) if raw else None
    except ValueError:
        return None


def hamming(a: int, b: int) -> int:
    return bin(int(a) ^ int(b)).count("1")


def fp_matches(fp: int | None, pool: Iterable[int], max_dist: int = FP_HAMMING_MAX) -> bool:
    if fp is None:
        return False
    return any(hamming(fp, other) <= max_dist for other in pool)


@dataclass
class UsedIndex:
    """Что уже стоит в других каруселях серии."""

    pins: set[str] = field(default_factory=set)
    fps: list[int] = field(default_factory=list)

    def is_used(self, pin_id: Any = None, fp: int | None = None) -> bool:
        pid = str(pin_id or "").strip()
        if pid and pid in self.pins:
            return True
        return fp_matches(fp, self.fps)

    def add(self, pin_id: Any = None, fp: int | None = None) -> None:
        pid = str(pin_id or "").strip()
        if pid:
            self.pins.add(pid)
        if fp is not None:
            self.fps.append(int(fp))


# ---------------------------------------------------------------------------
# 3. Классификатор кадра (грязь / место) на SigLIP
# ---------------------------------------------------------------------------


@dataclass
class PhotoFeatures:
    mess: float = 0.0
    is_mess: bool = False
    place: str = "other"
    place_prob: float = 0.0
    fp: int | None = None
    subject: str = "other"
    subject_prob: float = 0.0
    faces: int = 0


_FACE_CASCADE = None


def count_faces(image: Image.Image | None) -> int:
    """Лица в кадре (Haar, как в нарезке UGC). На слайдах 2+ чужих лиц быть
    не должно (character consistency) — правило отбора предпочитает кадры
    без лица."""
    global _FACE_CASCADE
    if image is None:
        return 0
    try:
        import cv2
        import numpy as np

        if _FACE_CASCADE is None:
            _FACE_CASCADE = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
        g = image.convert("L")
        g.thumbnail((640, 640))
        return int(len(_FACE_CASCADE.detectMultiScale(np.asarray(g), 1.1, 5, minSize=(28, 28))))
    except Exception:
        return 0


def _softmax_best(sims: dict[str, float], temp: float) -> tuple[str, float]:
    import math

    keys = list(sims)
    vals = [sims[k] / temp for k in keys]
    m = max(vals)
    ex = [math.exp(v - m) for v in vals]
    s = sum(ex) or 1.0
    best = max(range(len(keys)), key=lambda i: ex[i])
    return keys[best], ex[best] / s


def calibration_for(backend: str | None) -> dict[str, float]:
    return CALIBRATION.get(backend or "", CALIBRATION[DEFAULT_BACKEND])


def mess_probability(
    best_mess: float, best_clean: float, margin: float = 0.0
) -> float:
    """0.5 ровно на пороге: (грязь − чисто) == margin."""
    import math

    z = (float(best_clean) + float(margin) - float(best_mess)) / MESS_SOFTMAX_TEMP
    z = max(-60.0, min(60.0, z))
    return 1.0 / (1.0 + math.exp(z))


class SiglipPhotoClassifier:
    """Грязь и место через текстовые якоря SigLIP (без обучения)."""

    def __init__(self) -> None:
        self._t_mess = None
        self._t_clean = None
        self._t_place: dict[str, Any] = {}
        self._t_subject: dict[str, Any] = {}
        self.backend = ""
        self.cal = calibration_for(None)

    def _ensure(self) -> None:
        if self._t_mess is not None:
            return
        from core.taste_embedder import get_embedder

        emb = get_embedder()
        self.backend = emb.ensure()
        self.cal = calibration_for(self.backend)
        print(f"[rules] модель кадров: {self.backend} · пороги {self.cal}")
        self._t_mess = emb.embed_texts(list(MESS_PROMPTS))
        self._t_clean = emb.embed_texts(list(CLEAN_PROMPTS))
        self._t_place = {
            k: emb.embed_texts(list(v)) for k, v in PLACE_PROMPTS.items()
        }
        self._t_subject = {
            k: emb.embed_texts(list(v)) for k, v in SUBJECT_PROMPTS.items()
        }

    def features(self, images: Sequence[Image.Image]) -> list[PhotoFeatures]:
        if not images:
            return []
        from core.taste_embedder import get_embedder

        self._ensure()
        emb = get_embedder()
        vecs = emb.embed_images([im.convert("RGB") for im in images])
        out: list[PhotoFeatures] = []
        for im, v in zip(images, vecs):
            f = self.features_from_vector(v, fp=image_fingerprint(im))
            f.faces = count_faces(im)
            out.append(f)
        return out

    def features_from_vector(self, v: Any, *, fp: int | None = None) -> PhotoFeatures:
        import numpy as np

        self._ensure()
        v = np.asarray(v, dtype=np.float32)
        best_mess = float(np.max(self._t_mess @ v))
        best_clean = float(np.max(self._t_clean @ v))
        mess = mess_probability(best_mess, best_clean, self.cal["mess_margin"])
        place_sims = {k: float(np.max(t @ v)) for k, t in self._t_place.items()}
        place, prob = _softmax_best(place_sims, self.cal["place_temp"])
        if prob < self.cal["place_min_prob"]:
            place = "other"
        subject, s_prob = self.subject_of_vector(v)
        return PhotoFeatures(
            mess=round(float(mess), 4),
            is_mess=bool(mess >= MESS_THRESHOLD),
            place=place,
            place_prob=round(float(prob), 4),
            fp=fp,
            subject=subject,
            subject_prob=round(float(s_prob), 4),
        )

    def subject_of_vector(self, v: Any) -> tuple[str, float]:
        """Предмет кадра; ниже SUBJECT_MIN_PROB — "other" (не ограничивается)."""
        import numpy as np

        self._ensure()
        v = np.asarray(v, dtype=np.float32).reshape(-1)
        sims = {k: float(np.max(t @ v)) for k, t in self._t_subject.items()}
        subject, prob = _softmax_best(sims, SUBJECT_TEMP)
        if prob < SUBJECT_MIN_PROB:
            subject = "other"
        return subject, prob


_CLASSIFIER: SiglipPhotoClassifier | None = None


def get_photo_classifier() -> SiglipPhotoClassifier:
    global _CLASSIFIER
    if _CLASSIFIER is None:
        _CLASSIFIER = SiglipPhotoClassifier()
    return _CLASSIFIER


# ---------------------------------------------------------------------------
# 4. Применение правил к готовым пулам слайдов
# ---------------------------------------------------------------------------


@dataclass
class SlideRuleResult:
    photo_role: str
    mess: float | None = None
    is_mess: bool = False
    place: str = "other"
    subject: str = "other"
    faces: int = 0
    series_reused: bool = False
    relaxed: list[str] = field(default_factory=list)
    swapped: bool = False

    def to_meta(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "photo_role": self.photo_role,
            "mess_score": self.mess,
            "is_mess": self.is_mess,
            "place": self.place,
            "subject": self.subject,
            "faces": self.faces,
        }
        if self.series_reused:
            d["series_reused"] = True
        if self.relaxed:
            d["rules_relaxed"] = list(self.relaxed)
        if self.swapped:
            d["rules_swapped"] = True
        return d


def _cand_features(cand: Any, classifier: Any) -> PhotoFeatures:
    cached = getattr(cand, "_rule_features", None)
    if isinstance(cached, PhotoFeatures):
        return cached
    try:
        feats = classifier.features([cand.image])[0]
    except Exception as exc:  # модель недоступна — правила по картинке пропускаем
        print(f"[rules] classifier fail: {exc}")
        feats = PhotoFeatures(fp=image_fingerprint(getattr(cand, "image", None)))
    try:
        setattr(cand, "_rule_features", feats)
    except Exception:
        pass
    return feats


def _prefetch(cands: Sequence[Any], classifier: Any) -> None:
    """Один пакетный проход модели на слайд вместо N одиночных."""
    todo = [c for c in cands if not isinstance(getattr(c, "_rule_features", None), PhotoFeatures)]
    if not todo:
        return
    try:
        feats = classifier.features([c.image for c in todo])
    except Exception as exc:
        print(f"[rules] classifier batch fail: {exc}")
        feats = [PhotoFeatures(fp=image_fingerprint(getattr(c, "image", None))) for c in todo]
    for c, f in zip(todo, feats):
        try:
            setattr(c, "_rule_features", f)
        except Exception:
            pass


def enforce_carousel_rules(
    slides: Sequence[Any],
    *,
    roles: Sequence[str],
    heavy: bool = False,
    used: UsedIndex | None = None,
    classifier: Any = None,
    refill: Callable[[int], list[Any]] | None = None,
    max_check: int = MAX_CHECK_PER_SLIDE,
) -> list[SlideRuleResult]:
    """
    slides[i].candidates — уже отранжированный пул (индекс 0 = текущий выбор).
    Переставляет в [0] первый кандидат, который проходит правила.
    Если никто не проходит — сначала дозапрос (филлеры), потом правила
    ослабляются по очереди: место → лимит грязи → лица → повтор в серии.
    Повтор в серии и лица — последними: раньше они снимались до дозапроса,
    и одно фото вставало в две карусели (аудит 2026-10-05). Грязь на
    последнем слайде не пропускается никогда, пока есть хоть один чистый
    кадр; один и тот же кадр дважды в карусель не ставится.

    Порядок выбора: смысловые слайды (хук, продукт, сцена) → финал →
    филлеры, чтобы уступал филлер, а не хук. Слайд с продуктом не считается
    в лимите предмета.
    """
    n = len(slides)
    classifier = classifier or get_photo_classifier()
    used = used or UsedIndex()
    mess_budget = MAX_MESS_HEAVY if heavy else MAX_MESS_NORMAL
    results: list[SlideRuleResult | None] = [None] * n
    place_count: Counter[str] = Counter()
    subject_count: Counter[str] = Counter()
    mess_used = 0
    chosen_fps: list[int] = []
    last = n - 1

    def _role(j: int) -> str:
        return roles[j] if j < len(roles) else ROLE_SCENE

    semantic = [j for j in range(n) if j != last and _role(j) in SEMANTIC_ROLES]
    fillers = [j for j in range(n) if j != last and j not in semantic]
    order = semantic + ([last] if n > 0 else []) + fillers
    strict_tiers = (("prefer_free",), (), ("place",))
    relax_tiers = (
        ("place", "mess_budget"),
        ("place", "mess_budget", "faces"),
        ("place", "mess_budget", "faces", "series"),
    )

    # Кадры, которые у какого-то слайда единственные: другим слайдам их не отдаём
    sole_fp: dict[int, int] = {}
    for j, sl in enumerate(slides):
        pool_j = list(getattr(sl, "candidates", []) or [])
        if len(pool_j) == 1:
            fj = _cand_features(pool_j[0], classifier).fp
            if fj is not None:
                sole_fp[j] = fj

    for i in order:
        slide = slides[i]
        role = _role(i)
        is_final = i == last and n > 1
        subject_applies = role != ROLE_PRODUCT
        faces_banned = i > 0  # хук может показать героиню, дальше — без чужих лиц
        cands = list(getattr(slide, "candidates", []) or [])
        if not cands:
            results[i] = SlideRuleResult(photo_role=role, relaxed=["empty"])
            continue

        def evaluate(pool: list[Any], tiers) -> tuple[int, list[str]] | None:
            """
            Первый кадр, прошедший правила ступени (ref). Если его предмет уже
            есть в карусели — берётся следующий прошедший кадр другого
            предмета, но только не менее живой (LIVE_MARGIN); иначе ref с
            пометкой «subject». Предмет не вызывает дозапрос: дозапрос
            медленный и даёт кадры хуже.
            """
            head = pool[: max(1, max_check)]
            # Лениво: обычно хватает 1–2 кадров, остальные оцениваем по надобности
            _prefetch(head[:2], classifier)
            reserved = [fp for j, fp in sole_fp.items() if j != i]

            def subject_free(f: PhotoFeatures) -> bool:
                return (
                    not subject_applies
                    or f.subject == "other"
                    or subject_count[f.subject] < MAX_SAME_SUBJECT
                )

            for relaxed in tiers:
                ref: tuple[int, Any] | None = None
                for idx, c in enumerate(head):
                    f = _cand_features(c, classifier)
                    if f.fp is not None and fp_matches(f.fp, chosen_fps):
                        continue  # тот же кадр уже стоит в этой карусели
                    if "prefer_free" in relaxed and fp_matches(f.fp, reserved):
                        continue
                    if is_final and f.is_mess:
                        continue  # никогда не ослабляется
                    if faces_banned and "faces" not in relaxed and f.faces > 0:
                        continue
                    if "mess_budget" not in relaxed and f.is_mess and mess_used >= mess_budget:
                        continue
                    if "series" not in relaxed and used.is_used(
                        getattr(c, "pin_id", None), f.fp
                    ):
                        continue
                    if (
                        "place" not in relaxed
                        and f.place in LIMITED_PLACES
                        and place_count[f.place] >= MAX_SAME_PLACE
                    ):
                        continue
                    if ref is None:
                        ref = (idx, c)
                    if subject_free(f):
                        ref_live, live = _live(ref[1]), _live(c)
                        if idx == ref[0] or ref_live is None or live is None or (
                            live >= ref_live - LIVE_MARGIN
                        ):
                            return idx, [r for r in relaxed if r != "prefer_free"]
                if ref is not None:
                    return ref[0], [r for r in relaxed if r != "prefer_free"] + ["subject"]
            return None

        picked = evaluate(cands, strict_tiers)
        if picked is None and refill is not None:
            try:
                extra = list(refill(i) or [])
            except Exception as exc:
                print(f"[rules] refill slide {i + 1} fail: {exc}")
                extra = []
            if extra:
                cands = cands + extra
                picked = evaluate(cands, strict_tiers)
        if picked is None:
            picked = evaluate(cands, relax_tiers)
        relaxed: list[str]
        if picked is None:
            # хоть что-то, но не кадр, который уже стоит в этой карусели
            idx = next(
                (
                    j
                    for j, c in enumerate(cands)
                    if (fj := _cand_features(c, classifier).fp) is None
                    or not fp_matches(fj, chosen_fps)
                ),
                0,
            )
            relaxed = ["all"]
            print(
                f"[rules] слайд {i + 1}: ни один кадр не прошёл правила — "
                f"оставлен лучший по рангу"
            )
        else:
            idx, relaxed = picked
        chosen = cands[idx]
        f = _cand_features(chosen, classifier)
        if idx != 0:
            cands = [chosen] + [c for j, c in enumerate(cands) if j != idx]
        try:
            slide.candidates = cands
            slide.selected = 0
        except Exception:
            pass
        if f.fp is not None:
            chosen_fps.append(f.fp)
        if f.is_mess:
            mess_used += 1
        if f.place in LIMITED_PLACES:
            place_count[f.place] += 1
        if subject_applies and f.subject != "other":
            subject_count[f.subject] += 1
        res = SlideRuleResult(
            photo_role=role,
            mess=f.mess,
            is_mess=f.is_mess,
            place=f.place,
            subject=f.subject,
            faces=f.faces,
            series_reused=used.is_used(getattr(chosen, "pin_id", None), f.fp),
            relaxed=relaxed,
            swapped=idx != 0,
        )
        if idx != 0 or relaxed:
            print(
                f"[rules] слайд {i + 1} ({role}): кадр #{idx} "
                f"mess={f.mess:.2f} place={f.place} subject={f.subject}"
                + (f" ослаблено={relaxed}" if relaxed else "")
            )
        results[i] = res
    return [r or SlideRuleResult(photo_role=ROLE_SCENE) for r in results]

