#!/usr/bin/env python3
"""
Правила уровня всей карусели (фидбек 2026-09-29, пачка 06_food_body_image).

1. Роли слайдов:
     1-й слайд            -> scene   (кадр по сценарию)
     середина             -> scene / neutral по очереди
     последний слайд      -> final   (всегда приятный нейтральный)
   Для тяжёлых тем (депрессия, горе, одиночество…) нейтральные кадры
   в середине могут быть тёмными/moody, последний — спокойный, но не грязный.

2. Грязь (грязная посуда, мусор, разлитое, гора снеков):
     не больше MAX_MESS_NORMAL кадров на карусель (для тяжёлых тем
     MAX_MESS_HEAVY) и НИКОГДА на последнем слайде.

3. Одно место (кухня+холодильник, кровать, стол…) — не больше
   MAX_SAME_PLACE слайдов на карусель.

4. Одно фото — одна карусель на всю серию: pin_id + отпечаток картинки
   (dHash) сверяются с учётом в PhotoVault.

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
ROLE_NEUTRAL = "neutral"
ROLE_FINAL = "final"

RULES_ENABLED = True
MAX_MESS_NORMAL = 1
MAX_MESS_HEAVY = 2
MAX_SAME_PLACE = 2
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


def plan_roles(n: int) -> list[str]:
    """
    6 слайдов -> scene, scene, neutral, scene, neutral, final
    7 слайдов -> scene, scene, neutral, scene, neutral, scene, final
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
    return roles


# Все запросы проверены через finalize_photo_query (проходят без обрезки)
NEUTRAL_LIGHT: tuple[str, ...] = (
    "tea mug windowsill",
    "hands holding coffee cup",
    "coffee cup cafe table",
    "walking city street daytime",
    "book coffee table",
    "sneakers walking sidewalk",
    "sheer curtains bedroom window",
    "flowers vase table",
    "park bench trees autumn",
    "bicycle city street",
    "bare feet wooden floor",
    "potted plant windowsill",
    "window seat book",
    "autumn leaves sidewalk",
    "city tram window",
    "sky clouds window",
)
NEUTRAL_FOOD: tuple[str, ...] = (
    "strawberries bowl table",
    "breakfast table croissant",
    "fruit bowl kitchen table",
    "farmers market fruit",
    "iced coffee cafe",
    "lemons bowl table",
    "bakery window pastries",
    "herbs kitchen windowsill",
    "fresh bread bakery",
)
NEUTRAL_MOODY: tuple[str, ...] = (
    "rainy window city",
    "bus window night city",
    "street night walk",
    "candle table dark room",
    "rain car window",
    "night sky balcony",
)
FINAL_PLEASANT: tuple[str, ...] = (
    "tea mug windowsill",
    "flowers vase table",
    "sunset sky walk",
    "hands holding coffee cup",
    "sheer curtains bedroom window",
    "book tea cozy",
    "coffee cup cafe table",
    "potted plant windowsill",
    "window seat book",
    "sunset city skyline",
    "clean kitchen table flowers",
)
FINAL_CALM: tuple[str, ...] = (
    "tea mug windowsill",
    "candle book cozy",
    "hands holding tea",
    "sunset sky walk",
    "sheer curtains bedroom window",
    "book tea cozy",
)

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
) -> SlidePhotoPlan:
    """Нейтральный / финальный запрос. Не повторяет запросы из taken."""
    taken = taken if taken is not None else set()
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
    free = [q for q in ordered if q.lower() not in taken] or ordered
    query = free[0]
    alts = [q for q in free[1:3]]
    taken.add(query.lower())
    scene = f"{mood} everyday photo, {query}, clean and tidy, nothing dirty"
    return SlidePhotoPlan(
        role=role,
        query=query,
        search_text=f"{mood} photo: {query}",
        visual_scene=scene,
        alts=alts,
    )


def build_photo_plans(
    texts: Sequence[str],
    scene_specs: Sequence[tuple[str, str, list[str]]],
    *,
    topic: str = "",
    seed: Any = "",
    enabled: bool = True,
) -> tuple[list[SlidePhotoPlan], bool]:
    """
    scene_specs[i] = (query, visual_scene, alts) — сценарный запрос слайда
    (как раньше строил query_forge). Для neutral/final слайдов заменяется.
    Возвращает (plans, heavy).
    """
    n = len(texts)
    heavy = is_heavy_topic(topic, texts)
    roles = plan_roles(n) if enabled else [ROLE_SCENE] * n
    taken: set[str] = set()
    plans: list[SlidePhotoPlan] = []
    for i, (text, role) in enumerate(zip(texts, roles)):
        q, scene, alts = scene_specs[i] if i < len(scene_specs) else ("", "", [])
        if role == ROLE_SCENE:
            taken.add((q or "").lower())
            plans.append(
                SlidePhotoPlan(
                    role=role,
                    query=q,
                    search_text=text,
                    visual_scene=scene,
                    alts=list(alts or []),
                )
            )
        else:
            plans.append(
                neutral_plan(
                    role,
                    topic=topic,
                    slide_text=text,
                    slide_index=i,
                    heavy=heavy,
                    seed=seed,
                    taken=taken,
                )
            )
    return plans, heavy


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

    def features(self, images: Sequence[Image.Image]) -> list[PhotoFeatures]:
        if not images:
            return []
        from core.taste_embedder import get_embedder

        self._ensure()
        emb = get_embedder()
        vecs = emb.embed_images([im.convert("RGB") for im in images])
        out: list[PhotoFeatures] = []
        for im, v in zip(images, vecs):
            out.append(self.features_from_vector(v, fp=image_fingerprint(im)))
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
        return PhotoFeatures(
            mess=round(float(mess), 4),
            is_mess=bool(mess >= MESS_THRESHOLD),
            place=place,
            place_prob=round(float(prob), 4),
            fp=fp,
        )


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
    series_reused: bool = False
    relaxed: list[str] = field(default_factory=list)
    swapped: bool = False

    def to_meta(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "photo_role": self.photo_role,
            "mess_score": self.mess,
            "is_mess": self.is_mess,
            "place": self.place,
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
    Если никто не проходит — правила ослабляются по очереди
    (место → повтор в серии → лимит грязи), но грязь на последнем слайде
    не пропускается никогда, пока есть хоть один чистый кадр.
    """
    n = len(slides)
    classifier = classifier or get_photo_classifier()
    used = used or UsedIndex()
    mess_budget = MAX_MESS_HEAVY if heavy else MAX_MESS_NORMAL
    results: list[SlideRuleResult | None] = [None] * n
    place_count: Counter[str] = Counter()
    mess_used = 0
    chosen_fps: list[int] = []
    last = n - 1
    order = ([last] if n > 0 else []) + list(range(0, max(0, n - 1)))

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
        role = roles[i] if i < len(roles) else ROLE_SCENE
        is_final = i == last and n > 1
        cands = list(getattr(slide, "candidates", []) or [])
        if not cands:
            results[i] = SlideRuleResult(photo_role=role, relaxed=["empty"])
            continue

        def evaluate(pool: list[Any]) -> tuple[int, list[str]] | None:
            head = pool[: max(1, max_check)]
            # Лениво: обычно хватает 1–2 кадров, остальные оцениваем по надобности
            _prefetch(head[:2], classifier)
            reserved = [fp for j, fp in sole_fp.items() if j != i]
            tiers = (
                ("prefer_free",),
                (),
                ("place",),
                ("place", "series"),
                ("place", "series", "mess_budget"),
            )
            for relaxed in tiers:
                for idx, c in enumerate(head):
                    f = _cand_features(c, classifier)
                    if f.fp is not None and fp_matches(f.fp, chosen_fps):
                        continue  # тот же кадр уже стоит в этой карусели
                    if "prefer_free" in relaxed and fp_matches(f.fp, reserved):
                        continue
                    if is_final and f.is_mess:
                        continue  # никогда не ослабляется
                    if "mess_budget" not in relaxed and f.is_mess and mess_used >= mess_budget:
                        continue
                    if "series" not in relaxed and used.is_used(getattr(c, "pin_id", None), f.fp):
                        continue
                    if (
                        "place" not in relaxed
                        and f.place in LIMITED_PLACES
                        and place_count[f.place] >= MAX_SAME_PLACE
                    ):
                        continue
                    return idx, [r for r in relaxed if r != "prefer_free"]
            return None

        picked = evaluate(cands)
        if picked is None and refill is not None:
            try:
                extra = list(refill(i) or [])
            except Exception as exc:
                print(f"[rules] refill slide {i + 1} fail: {exc}")
                extra = []
            if extra:
                cands = cands + extra
                picked = evaluate(cands)
        relaxed: list[str]
        if picked is None:
            idx, relaxed = 0, ["all"]
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
        res = SlideRuleResult(
            photo_role=role,
            mess=f.mess,
            is_mess=f.is_mess,
            place=f.place,
            series_reused=used.is_used(getattr(chosen, "pin_id", None), f.fp),
            relaxed=relaxed,
            swapped=idx != 0,
        )
        if idx != 0 or relaxed:
            print(
                f"[rules] слайд {i + 1} ({role}): кадр #{idx} "
                f"mess={f.mess:.2f} place={f.place}"
                + (f" ослаблено={relaxed}" if relaxed else "")
            )
        results[i] = res
    return [r or SlideRuleResult(photo_role=ROLE_SCENE) for r in results]

