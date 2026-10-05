"""
Universal Pinterest query forge.

Goal: every slide gets a searchable LIVE scene string —
  [action/state] + [prop] + [place]   (3–5 words)

DNA hair/gender NEVER enter the Pinterest string (handled by attr/gender locks).
Filler stems (hands/feet/door/girl/hair) are banned unless the slide text
literally names them as the subject.
"""
from __future__ import annotations

import re
from typing import Iterable

# ---------------------------------------------------------------------------
# Lexicons
# ---------------------------------------------------------------------------

# DNA / casting tokens — never belong in a search string
_DNA_CAST_RE = re.compile(
    r"\b(girl|guy|woman|women|man|men|female|male|boyfriend|girlfriend|"
    r"blonde|blond|brunette|ginger|auburn|redhead|platinum|caramel|honey|"
    r"black hair|dark hair|brown hair|long hair|short hair|hair)\b",
    re.I,
)

# Stock filler stems — OK only if literally in slide text
_FILLER_STEMS: frozenset[str] = frozenset(
    {
        "hands",
        "hand",
        "feet",
        "foot",
        "sneakers",
        "shoes",
        "door",
        "doors",
        "window",
        "hallway",
        "selfie",
        "mirror",
        "portrait",
        "bathroom",
        "candid",
        "aesthetic",
        "floor",
        "wooden",
        "closed",
        "empty",
        "tea",
        "cup",
    }
)

# Photographable props → preferred Pinterest phrasing
# Matched as whole words in slide_text / visual_scene (longest first).
_PROP_PHRASES: tuple[tuple[str, str], ...] = (
    ("chip bag", "chip bags night"),
    ("ice cream", "ice cream pint"),
    ("food scale", "food scale kitchen"),
    ("protein shake", "protein shake gym"),
    ("takeout box", "takeout box table"),
    ("kitchen counter", "kitchen counter night"),
    ("open fridge", "open fridge night"),
    ("empty plate", "empty plate table"),
    ("meal plan", "meal plan calendar"),
    ("gym bag", "gym bag floor"),
    ("yoga mat", "yoga mat floor"),
    ("almonds", "almonds handful desk"),
    ("almond", "almonds handful desk"),
    ("spinach", "weighing spinach scale"),
    # calorie alone is weak — only used if no food prop matched
    ("calories", "food scale kitchen"),
    ("calorie", "food scale kitchen"),
    ("pantry", "open pantry night"),
    ("fridge", "open fridge night"),
    ("refrigerator", "open fridge night"),
    ("freezer", "open freezer night"),
    ("salad", "sad salad lunch"),
    ("chips", "chip bags night"),
    ("snacks", "snack bags counter"),
    ("snack", "snack bags counter"),
    # NEVER bare "pretzel(s)" — Pinterest maps that to German soft pretzels
    ("stale pretzels", "stale pretzel chips bag"),
    ("pretzel bag", "pretzel chips bag night"),
    ("pretzels", "pretzel chips bag night"),
    ("pretzel", "pretzel chips bag night"),
    ("pasta", "pasta bowl table"),
    ("noodles", "noodles bowl table"),
    ("ramen", "ramen bowl desk"),
    ("pizza", "pizza box counter"),
    ("sink", "kitchen sink window"),
    ("counter", "standing kitchen counter"),
    ("scale", "food scale kitchen"),
    ("laptop", "laptop snacks desk"),
    ("calendar", "calendar meal planning"),
    ("notebook", "notebook pen desk"),
    ("journal", "open journal desk"),
    ("plate", "plate of food table"),
    ("wrappers", "snack bag table"),
    ("gym", "gym bag locker"),
    ("workout", "gym bag floor"),
    ("locker", "gym locker sneakers"),
    ("sneakers", "sneakers floor hallway"),
    ("coffee", "coffee mug desk"),
    ("tea", "tea mug window"),
    ("water bottle", "water bottle gym"),
    ("phone", "phone notes screen"),
    ("desk", "desk lamp night"),
    ("kitchen", "kitchen counter night"),
    # reflection / vibe scenes (body-check, disconnection, look-up)
    ("storefront", "silhouette storefront window"),
    ("shop window", "silhouette shop window reflection"),
    ("store window", "silhouette store window reflection"),
    ("hallway mirror", "blurry hallway mirror silhouette"),
    ("body checking", "silhouette window reflection"),
    ("looking up", "looking up sky sidewalk"),
    ("open sky", "looking up sky sidewalk"),
    ("reflection", "window reflection silhouette"),
    ("storefront glass", "hand on storefront glass"),
    ("window pane", "hand on rainy window pane"),
    ("rainy window", "rainy window city lights"),
    ("rain window", "rain on window night city"),
    ("wet window", "looking through wet window"),
    ("mirror", "dark mirror reflection silhouette"),
    ("silhouette", "silhouette window reflection"),
    ("window", "window reflection candid"),
    ("glass", "hand on glass window"),
    ("skyline", "looking up city sky"),
    ("sidewalk", "city sidewalk candid"),
    ("sky", "looking up sky sidewalk"),
)

_ACTION_CUES: tuple[tuple[str, str], ...] = (
    ("standing", "standing"),
    ("staring", "staring"),
    ("weighing", "weighing"),
    ("counting", "counting"),
    ("procrastinat", "procrastinating"),
    ("skip", "skipped"),
    ("over the counter", "over counter"),
    ("10pm", "night"),
    ("midnight", "night"),
    ("3am", "night"),
)

_MESS_CUES = (
    "binge",
    "demolish",
    "mess",
    "trash",
    "fugitive",
    "wrapper",
    "10pm",
    "midnight",
    "chips",
    "snack",
    "standing",
)
_RESTRICT_CUES = (
    "weigh",
    "count",
    "calorie",
    "portion",
    "spinach",
    "almond",
    "scale",
    "track",
)

_STOP = frozenset(
    {
        "the",
        "and",
        "with",
        "for",
        "a",
        "an",
        "of",
        "to",
        "in",
        "by",
        "at",
        "on",
        "is",
        "it",
        "my",
        "your",
        "you",
        "i",
        "me",
        "just",
        "like",
        "that",
        "this",
        "from",
        "into",
        "about",
        "when",
        "then",
        "only",
        "really",
        "actually",
        "basically",
        "honestly",
        "apparently",
        "turns",
        "out",
        "because",
        "while",
        "over",
        "were",
        "was",
        "are",
        "been",
        "being",
        "have",
        "has",
        "had",
        "not",
        "dont",
        "doesn't",
        "didn't",
        "can't",
        "wont",
        "what",
        "why",
        "how",
        "who",
        "every",
        "single",
        "version",
        "myself",
        "yourself",
        "human",
        "person",
        "people",
        "brain",
        "mind",
        "truth",
        "thing",
        "things",
        "time",
        "times",
        "today",
        "yesterday",
        "hours",
        "minutes",
        "spent",
        "feel",
        "feeling",
        "want",
        "need",
        "know",
        "think",
        "thought",
        "make",
        "made",
        "get",
        "got",
        "even",
        "still",
        "also",
        "very",
        "more",
        "most",
        "some",
        "any",
        "all",
        "own",
        "other",
        "than",
        "too",
        "so",
        "as",
        "or",
        "if",
        "but",
        "up",
        "down",
        "out",
        "off",
        "back",
        "again",
        "here",
        "there",
        "where",
        "which",
        "their",
        "them",
        "they",
        "she",
        "he",
        "her",
        "his",
        "our",
        "we",
    }
)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def query_is_dna_cast(query: str) -> bool:
    """True if query is mostly DNA casting (hair/girl) with no scene prop."""
    low = (query or "").lower().strip()
    if not low:
        return True
    toks = _words(low)
    if not toks:
        return True
    cast_hits = len(_DNA_CAST_RE.findall(low))
    # strip cast tokens — anything left?
    stripped = _DNA_CAST_RE.sub(" ", low)
    rest = [w for w in _words(stripped) if w not in {"candid", "aesthetic", "scene"}]
    if cast_hits >= 1 and len(rest) <= 1:
        return True
    # classic patterns
    if re.fullmatch(
        r"(hands?\s+)?(girl|guy|woman|man)\s+\w+\s+hair",
        low,
    ) or re.fullmatch(r"\w+\s+hair\s+(girl|guy|woman|man)", low):
        return True
    if re.fullmatch(r"(dark|blonde|black|ginger|caramel|auburn|short|long)\s+\w+\s+(girl|guy)", low):
        return True
    return False


def query_is_filler_only(query: str, *, slide_text: str = "") -> bool:
    """True if query is stock filler with no confession prop."""
    toks = [w for w in _words(query) if w not in {"candid", "aesthetic"}]
    if not toks:
        return True
    text_low = (slide_text or "").lower()
    non_filler = []
    for w in toks:
        if w in _FILLER_STEMS and w not in text_low:
            continue
        if _DNA_CAST_RE.search(w):
            continue
        non_filler.append(w)
    return len(non_filler) < 2


# Stationery / desk props — demote when a food/body confession prop is present
_STATIONERY_PROP_KEYS: frozenset[str] = frozenset(
    {"notebook", "journal", "calendar", "laptop"}
)
_FOOD_PROP_KEYS: frozenset[str] = frozenset(
    {
        "almonds",
        "almond",
        "pantry",
        "fridge",
        "refrigerator",
        "freezer",
        "pasta",
        "noodles",
        "ramen",
        "pizza",
        "chips",
        "snacks",
        "snack",
        "salad",
        "spinach",
        "sink",
        "counter",
        "kitchen counter",
        "open fridge",
        "empty plate",
        "plate",
        "crumbs",
        "wrappers",
        "chip bag",
        "ice cream",
        "food scale",
        "scale",
        "takeout box",
        "protein shake",
        "pretzels",
        "pretzel",
    }
)

# "Clean day" props — demote when a binge/night prop is also in the blob
_CLEAN_DAY_PROP_KEYS: frozenset[str] = frozenset(
    {
        "protein shake",
        "salad",
        "spinach",
        "meal plan",
        "gym bag",
        "gym",
        "workout",
        "yoga mat",
        "food scale",
        "scale",
        "calories",
        "calorie",
    }
)
_BINGE_PROP_KEYS: frozenset[str] = frozenset(
    {
        "pantry",
        "fridge",
        "refrigerator",
        "freezer",
        "chips",
        "chip bag",
        "snacks",
        "snack",
        "pretzels",
        "pretzel",
        "pasta",
        "pizza",
        "ice cream",
        "wrappers",
        "crumbs",
        "empty plate",
        "takeout box",
        "sink",
        "open fridge",
    }
)


def _extract_props(blob: str, *, limit: int = 3) -> list[str]:
    """Return preferred query phrases for props found in blob."""
    low = (blob or "").lower()
    found: list[str] = []
    found_keys: list[str] = []
    used_spans: list[tuple[int, int]] = []
    weak_keys = {"calories", "calorie", "scale"}
    has_food = any(
        re.search(rf"\b{re.escape(k)}\b", low) for k in _FOOD_PROP_KEYS
    )
    has_binge = any(
        re.search(rf"\b{re.escape(k)}\b", low) for k in _BINGE_PROP_KEYS
    )
    # Pass 1: strong concrete props (food beats stationery; binge beats clean-day)
    for key, phrase in sorted(_PROP_PHRASES, key=lambda x: -len(x[0])):
        if key in weak_keys:
            continue
        if has_food and key in _STATIONERY_PROP_KEYS:
            continue
        if has_binge and key in _CLEAN_DAY_PROP_KEYS:
            continue
        for m in re.finditer(rf"\b{re.escape(key)}\b", low):
            span = m.span()
            if any(not (span[1] <= a or span[0] >= b) for a, b in used_spans):
                continue
            used_spans.append(span)
            if phrase not in found:
                found.append(phrase)
                found_keys.append(key)
            break
        if len(found) >= limit:
            return found[:limit]
    # Pass 2: weak abstractions only if nothing concrete
    if not found:
        for key, phrase in _PROP_PHRASES:
            if key not in weak_keys:
                continue
            if re.search(rf"\b{re.escape(key)}\b", low):
                found.append(phrase)
                break
    return found[:limit]


def _query_covers_prop(query: str, phrase: str) -> bool:
    """True if query already carries the prop's content words."""
    q = (query or "").lower()
    if not q or not phrase:
        return False
    keys = [
        w
        for w in phrase.lower().split()
        if len(w) >= 4 or w in {"sink", "desk", "night", "bag", "sky"}
    ]
    if not keys:
        return phrase.lower() in q
    # Weak verbs/body words alone do not count as covering a scene prop
    weak = {
        "hand",
        "hands",
        "close",
        "resting",
        "person",
        "night",
        "desk",
        "floor",
        "kitchen",
        "messy",
        "candid",
        "pressed",
        "looking",
        "walking",
        "alone",
    }
    anchors = [w for w in keys if w not in weak]
    check = anchors or keys
    # Need an anchor noun (glass/window/sky/fridge…), not just "hand"
    return any(k in q for k in check)


def query_misses_slide_prop(
    query: str,
    *,
    slide_text: str = "",
    visual_scene: str = "",
    topic: str = "",
) -> bool:
    """True when blob has a strong prop the query does not name.

    Prefer props from visual_scene, then slide_text — topic only as last resort
    so a topic like 'window reflection' does not overwrite a sky/fridge scene.
    """
    props = (
        _extract_props(visual_scene or "", limit=1)
        or _extract_props(slide_text or "", limit=1)
        or _extract_props(topic or "", limit=1)
    )
    if not props:
        return False
    return not _query_covers_prop(query, props[0])


def _extract_action(blob: str) -> str:
    low = (blob or "").lower()
    for key, act in _ACTION_CUES:
        if key in low:
            return act
    # Раньше binge/trash/midnight -> "messy": тянуло грязную посуду и мусор
    # (фидбек 2026-09-29). Теперь «беспорядочные» темы не добавляют слов.
    if any(c in low for c in _RESTRICT_CUES):
        return "weighing"
    return ""


def _scene_nouns(scene: str, *, limit: int = 4) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for w in _words(scene):
        if w in _STOP or len(w) < 3:
            continue
        if _DNA_CAST_RE.search(w):
            continue
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= limit:
            break
    return out


def _valence_tail(blob: str) -> str:
    low = (blob or "").lower()
    mess = sum(1 for c in _MESS_CUES if c in low)
    rest = sum(1 for c in _RESTRICT_CUES if c in low)
    if mess > rest and mess > 0:
        return "night" if "night" in low or "10pm" in low or "midnight" in low else ""
    if rest > 0:
        return "kitchen"
    return ""


def _clamp(words: Iterable[str], *, max_w: int = 4) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        low = (w or "").lower().strip()
        if not low or low in seen:
            continue
        if _DNA_CAST_RE.fullmatch(low):
            continue
        # skip tokens already covered as substring of a kept multi-word chunk
        if any(low in s or s in low for s in seen if len(s) > 2):
            # still allow distinct short place words
            if low not in {"night", "desk", "floor", "kitchen"}:
                continue
        seen.add(low)
        out.append(low)
        if len(out) >= max_w:
            break
    while len(out) < 3:
        for filler in ("kitchen", "night", "desk", "floor", "room"):
            if filler not in seen:
                out.append(filler)
                seen.add(filler)
                break
        else:
            break
        if len(out) >= 3:
            break
    return " ".join(out[:max_w])


# Хук: люди и отношения на фото — «подтекст», который останавливает скролл
# (папа с дочкой, пара, мама на кухне). Такой запрос хука не заменяем
# пропом сцены. Цвет волос / girl / guy по-прежнему запрещены (DNA-lock).
_RELATIONSHIP_RE = re.compile(
    r"\b(father|dad|daddy|mother|mom|mum|daughter|son|parents?|couple|"
    r"boyfriend|girlfriend|husband|wife|ex|best\s+friends?|friends|sisters?|"
    r"brothers?|grandma|grandpa|grandmother|grandfather|family|siblings?)\b",
    re.I,
)


def query_names_relationship(query: str) -> bool:
    return bool(_RELATIONSHIP_RE.search(query or ""))


def forge_pinterest_query(
    *,
    slide_text: str = "",
    visual_scene: str = "",
    topic: str = "",
    slide_index: int = 0,
    draft_query: str = "",
) -> str:
    """
    Build a universal live-UGC Pinterest query for any slide.

    Priority:
      1. Keep draft if it already has real scene props (not DNA/filler)
      2. visual_scene nouns + action
      3. props extracted from slide_text / topic
      4. last-resort indoor candid with valence place
    """
    text = (slide_text or "").strip()
    scene = scrub_dna_from_scene(visual_scene or "")
    draft = re.sub(r"\s+", " ", (draft_query or "").strip())
    blob = f"{scene} {text} {topic}"

    def _out(q: str) -> str:
        return normalize_pinterest_query_aliases(q)

    # 0) Хук с людьми / отношениями — оставляем как есть (подтекст хука)
    if (
        int(slide_index) == 0
        and draft
        and query_names_relationship(draft)
        and not query_is_dna_cast(draft)
    ):
        toks = _words(re.sub(r"\s+", " ", _DNA_CAST_RE.sub(" ", draft)).strip())
        if len(toks) >= 2:
            return _out(_clamp(toks, max_w=4))

    # 1) Keep a good draft — but NEVER if it misses the slide's strongest prop
    # Prefer scene props; topic must not overwrite a sky/fridge scene with "window"
    props_early = (
        _extract_props(scene, limit=2)
        or _extract_props(text, limit=2)
        or _extract_props(topic, limit=2)
    )
    if draft and not query_is_dna_cast(draft) and not query_is_filler_only(
        draft, slide_text=text
    ):
        misses_prop = bool(props_early) and not _query_covers_prop(
            draft, props_early[0]
        )
        if not misses_prop:
            cleaned = _DNA_CAST_RE.sub(" ", draft)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            toks = _words(cleaned)
            if len(toks) >= 3:
                return _out(_clamp(toks, max_w=4))
            if len(toks) == 2:
                tail = _valence_tail(blob) or "candid"
                return _out(_clamp(toks + [tail], max_w=4))

    # 2) Prop phrases from text/scene (strongest signal)
    props = props_early or _extract_props(blob, limit=2)
    action = _extract_action(blob)
    if props:
        base = _words(props[0])
        # Prefer a second concrete food/place prop over abstract calorie→scale
        if len(props) > 1 and props[0].startswith("food scale"):
            base = _words(props[1]) + base
        if action and action not in " ".join(base):
            # don't prepend if action tokens already inside phrase
            act_toks = _words(action)
            if not any(t in base for t in act_toks):
                base = act_toks + base
        if len(props) > 1:
            for w in _words(props[1]):
                if w not in base:
                    base.append(w)
                if len(base) >= 4:
                    break
        return _out(_clamp(base, max_w=4))

    # 3) visual_scene nouns
    nouns = _scene_nouns(scene, limit=4)
    if len(nouns) >= 2:
        if action and action not in nouns:
            nouns = [action] + nouns
        return _out(_clamp(nouns, max_w=4))

    # 4) Free nouns from slide text (skip stopwords / DNA / abstract fluff)
    text_nouns = _scene_nouns(text, limit=6)
    emotion = {
        "tired",
        "scared",
        "afraid",
        "anxious",
        "lonely",
        "guilty",
        "shame",
        "exhausted",
        "terrified",
        "hungry",
        "bored",
        "appetite",
        "procrastination",
        "procrastinating",
        "dopamine",
        "discipline",
        "control",
        "spiral",
        "spiraling",
        "tool",
        "version",
        "portal",
        "dimension",
        "equation",
        "math",
        "brain",
        "mind",
    }
    concrete = [w for w in text_nouns if w not in emotion and len(w) >= 4]
    if len(concrete) >= 2:
        if action and action not in concrete and action not in emotion:
            concrete = [action] + concrete
        return _out(_clamp(concrete, max_w=4))

    # 5) Last resort — valence place, never DNA
    place = _valence_tail(blob) or "indoor"
    low_blob = blob.lower()
    if "procrastinat" in low_blob or "dopamine" in low_blob:
        return _out(_clamp(["snacks", "laptop", "desk"], max_w=4))
    if action and action not in emotion:
        return _out(_clamp([action, place, "kitchen"], max_w=4))
    return _out(_clamp([place, "kitchen", "candid"], max_w=4))


def scrub_dna_from_query(query: str) -> str:
    """Remove DNA casting tokens; keep remaining scene words."""
    cleaned = _DNA_CAST_RE.sub(" ", query or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def scrub_dna_from_scene(scene: str) -> str:
    """
    visual_scene must stay a camera frame, never a DNA casting sheet.
    Strip hair/gender casting; keep props, rooms, actions.
    """
    s = scrub_dna_from_query(scene or "")
    # Orphan style leftovers after DNA strip
    s = re.sub(
        r"\b(shoulder[- ]length|long|short|wavy|straight|curly)\b",
        " ",
        s,
        flags=re.I,
    )
    s = re.sub(
        r"\b(woman|man|girl|guy|female|male)\s+(standing|sitting|looking|reaching)\b",
        r"person \2",
        s,
        flags=re.I,
    )
    s = re.sub(r"\b(woman|man|girl|guy|female|male)\b", "person", s, flags=re.I)
    s = re.sub(r"\bperson person\b", "person", s, flags=re.I)
    s = re.sub(r"\bwith\s+(standing|sitting|looking|reaching)\b", r"\1", s, flags=re.I)
    s = re.sub(r"^\s*with\s+", "", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def normalize_pinterest_query_aliases(query: str) -> str:
    """Fix known Pinterest polysemy (soft pretzel ≠ snack bag)."""
    q = re.sub(r"\s+", " ", (query or "").strip())
    low = q.lower()
    # Bare pretzel(s) without chips/bag/snack → force snack-bag phrasing
    if re.search(r"\bpretzels?\b", low) and not re.search(
        r"\b(chips?|bag|snack|stale|pantry)\b", low
    ):
        q = re.sub(r"\bpretzels?\b", "pretzel chips bag", q, flags=re.I)
        q = re.sub(r"\s+", " ", q).strip()
    return q


def own_slide_query(
    *,
    slide_text: str = "",
    visual_scene: str = "",
    topic: str = "",
    slide_index: int = 0,
    draft_query: str = "",
    character_dna: dict[str, str] | None = None,
) -> str:
    """
    Single QueryOwner for the hot path.

    Pipeline (exactly once):
      DNA soft scrub → forge scene props → finalize_photo_query
    No repeated forge/inject/align ping-pong.
    """
    from core.harvester import finalize_photo_query

    scene = scrub_dna_from_scene(visual_scene or "")
    q = re.sub(r"\s+", " ", (draft_query or "").strip())
    if character_dna:
        try:
            from core.llm_engine import inject_character_markers_into_query

            q = inject_character_markers_into_query(
                q, character_dna, slide_index=slide_index
            )
        except Exception:
            q = scrub_dna_from_query(q)

    q = forge_pinterest_query(
        slide_text=slide_text,
        visual_scene=scene,
        topic=topic,
        slide_index=slide_index,
        draft_query=q,
    )
    q = finalize_photo_query(q, slide_index, slide_text=slide_text or "")
    q = normalize_pinterest_query_aliases(q)

    if query_is_dna_cast(q) or query_is_filler_only(q, slide_text=slide_text):
        q = forge_pinterest_query(
            slide_text=slide_text,
            visual_scene=scene,
            topic=topic,
            slide_index=slide_index,
            draft_query="",
        )
        q = finalize_photo_query(q, slide_index, slide_text=slide_text or "")
        q = normalize_pinterest_query_aliases(q)

    # Hard prop-lock: primary must name the strongest visual_scene/text prop
    # (кроме хука с людьми / отношениями — там главное люди, а не проп)
    hook_people = int(slide_index) == 0 and query_names_relationship(q)
    if not hook_people and query_misses_slide_prop(
        q, slide_text=slide_text, visual_scene=scene, topic=topic
    ):
        props = (
            _extract_props(scene, limit=1)
            or _extract_props(slide_text, limit=1)
            or _extract_props(topic, limit=1)
        )
        if props:
            q = forge_pinterest_query(
                slide_text=slide_text,
                visual_scene=scene,
                topic=topic,
                slide_index=slide_index,
                draft_query=props[0],
            )
            q = finalize_photo_query(q, slide_index, slide_text=slide_text or "")
            q = normalize_pinterest_query_aliases(q)
            # Last resort: force prop phrase as the query core
            if query_misses_slide_prop(
                q, slide_text=slide_text, visual_scene=scene, topic=topic
            ):
                q = finalize_photo_query(
                    props[0], slide_index, slide_text=slide_text or ""
                )
                q = normalize_pinterest_query_aliases(q)

    return re.sub(r"\s+", " ", (q or "").strip())


def own_slide_queries(
    *,
    slide_text: str = "",
    visual_scene: str = "",
    topic: str = "",
    slide_index: int = 0,
    draft_query: str = "",
    character_dna: dict[str, str] | None = None,
    max_alts: int = 1,
) -> tuple[str, list[str]]:
    """
    Primary + alternate scene queries for multi-query retrieval.
    Alts must differ from primary (case-insensitive).
    """
    primary = own_slide_query(
        slide_text=slide_text,
        visual_scene=visual_scene,
        topic=topic,
        slide_index=slide_index,
        draft_query=draft_query,
        character_dna=character_dna,
    )
    alts: list[str] = []
    seen = {primary.lower()}

    # Alt 1: visual_scene compress (if present)
    if max_alts >= 1 and (visual_scene or "").strip():
        try:
            from core.llm_engine import search_query_from_visual_scene

            scene_draft = search_query_from_visual_scene(
                visual_scene, topic=topic
            )
        except Exception:
            scene_draft = ""
        if scene_draft:
            alt = own_slide_query(
                slide_text=slide_text,
                visual_scene=visual_scene,
                topic=topic,
                slide_index=slide_index,
                draft_query=scene_draft,
                character_dna=character_dna,
            )
            if alt.lower() not in seen:
                alts.append(alt)
                seen.add(alt.lower())

    # Alt 2: second prop phrase from text (if forge only used first)
    if len(alts) < max_alts:
        props = _extract_props(f"{visual_scene} {slide_text} {topic}", limit=2)
        if len(props) >= 2:
            alt = own_slide_query(
                slide_text=slide_text,
                visual_scene=visual_scene,
                topic=topic,
                slide_index=slide_index,
                draft_query=props[1],
                character_dna=character_dna,
            )
            if alt.lower() not in seen:
                alts.append(alt)
                seen.add(alt.lower())

    return primary, alts[:max_alts]


# ---------------------------------------------------------------------------
# Easy (high-yield) mood pivots — when literal prop search fails.
# Goal: queries that Pinterest floods with live UGC AND that fit the slide's
# emotional context (not the literal object named in the text).
# ---------------------------------------------------------------------------

# mood bucket → easy searchable scenes (3–4 words, proven hit-rate)
_EASY_MOOD_BANKS: dict[str, tuple[str, ...]] = {
    # late-night food guilt / binge / fridge / scale spirals
    "food_night": (
        "open fridge night phone",
        "snack bags bed night",
        "kitchen counter night",
        "empty plate table night",
        "chip bag couch night",
        "phone torch pantry shelf",
    ),
    # diet / wellness / meal-prep pressure (soften away from stock meal-prep)
    "food_control": (
        "fruit bowl kitchen table",
        "tea mug kitchen morning",
        "grocery bags floor hallway",
        "empty plate table night",
        "hands holding tea mug",
        "kitchen counter night",
    ),
    # bed / doomscroll / can't sleep / phone spiral
    "bed_spiral": (
        "phone on pillow night",
        "hands holding phone bed",
        "laptop bed night",
        "water glass nightstand dark",
        "socks on bed candid",
        "laptop bed evening candid",
    ),
    # work / school / laptop guilt / procrastination
    "desk_work": (
        "desk phone night",
        "laptop charger cord desk",
        "open notebook pen desk",
        "hands typing laptop night",
        "coffee mug laptop desk",
        "sticky notes laptop desk",
    ),
    # city loneliness / walking it off / leaving the house
    "outside_night": (
        "rainy window city night",
        "feet sneakers pavement walk",
        "car cup holder night",
        "hands holding steering wheel",
        "bus window night city",
        "keys on table hallway",
    ),
    # gym avoidance / body / mirror tension (easy objects, not face casting)
    "body_gym": (
        "sneakers by gym bag",
        "water bottle gym floor",
        "workout shoes door rack",
        "gym bag car trunk",
        "yoga mat rolled corner",
        "sneakers by door candid",
    ),
    # generic confession fallback — still easy, still on-brand
    "general": (
        "hands holding phone bed",
        "rainy window city night",
        "desk phone night",
        "kitchen counter night",
        "feet sneakers pavement walk",
        "tea mug window morning",
        "keys on table hallway",
        "open fridge night phone",
    ),
}

# keyword hints → mood bucket (order = priority if multiple match)
_MOOD_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "food_night",
        (
            "binge", "fridge", "freezer", "pantry", "chips", "snack",
            "almond", "scale", "1am", "2am", "3am", "midnight", "ate", "eating",
            "craving", "pasta", "cereal", "ice cream", "leftover",
        ),
    ),
    (
        "food_control",
        (
            "meal prep", "quinoa", "smoothie", "wellness", "diet", "calorie",
            "protein", "salad", "clean eat", "weigh", "macros", "restrict",
            "green juice", "mealprep", "food noise",
        ),
    ),
    (
        "bed_spiral",
        (
            "bed", "pillow", "sleep", "insomnia", "doomscroll", "can't sleep",
            "cant sleep", "laying", "lying in", "blanket", "duvet", "nightstand",
        ),
    ),
    (
        "desk_work",
        (
            "laptop", "work", "desk", "email", "deadline", "study", "homework",
            "office", "zoom", "slack", "procrastinat", "essay", "exam",
        ),
    ),
    (
        "outside_night",
        (
            "walk", "city", "street", "drive", "drove", "car", "rain", "window",
            "leave", "outside", "uber", "bus", "train", "parked",
        ),
    ),
    (
        "body_gym",
        (
            "gym", "workout", "run", "mirror", "body", "weigh myself",
            "treadmill", "pilates", "yoga", "sneakers", "membership",
        ),
    ),
)

# Keep old name as flat union for tests / callers that scan the bank
STYLE_PIVOT_QUERIES: tuple[str, ...] = tuple(
    dict.fromkeys(
        q for bank in _EASY_MOOD_BANKS.values() for q in bank
    )
)

# Concrete subjects: if a query with these failed, do NOT retry same subject
# (almond hand → almond tree / almonds desk). Ambient words (kitchen, night,
# window, desk…) stay allowed so style-pivot can jump to a different scene.
_CONCRETE_SUBJECT_STEMS: frozenset[str] = frozenset(
    {
        "almond",
        "almonds",
        "spinach",
        "quinoa",
        "smoothie",
        "pasta",
        "noodles",
        "ramen",
        "pizza",
        "chips",
        "chip",
        "snack",
        "snacks",
        "salad",
        "fridge",
        "refrigerator",
        "freezer",
        "pantry",
        "scale",
        "pretzel",
        "pretzels",
        "cereal",
        "cookie",
        "oreo",
        "yogurt",
        "wrappers",
        "crumbs",
        "calories",
        "calorie",
        "macros",
        "protein",
        "shake",
        "takeout",
        "ice",  # ice cream — matched with cream via phrase; keep cream too
        "cream",
        "gym",
        "treadmill",
        "yoga",
        "sneakers",  # borderline; still a strong subject when gym failed
        "mirror",
        "silhouette",
        "reflection",
        "storefront",
    }
)


def _norm_subject_stem(token: str) -> str:
    t = (token or "").lower().strip()
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("s") and len(t) > 3 and not t.endswith("ss"):
        return t[:-1]
    return t


def banned_subject_stems(
    avoid_queries: Iterable[str] | None = None,
) -> set[str]:
    """Prop stems from already-failed queries (almond, fridge, scale…)."""
    banned: set[str] = set()
    for q in avoid_queries or ():
        low = (q or "").lower()
        if not low.strip():
            continue
        for stem in _CONCRETE_SUBJECT_STEMS:
            if re.search(rf"\b{re.escape(stem)}\b", low):
                banned.add(_norm_subject_stem(stem))
    return banned


def query_hits_banned_subject(
    query: str,
    banned: set[str] | frozenset[str] | None,
) -> bool:
    """True if query still revolves around a failed concrete subject."""
    if not banned:
        return False
    low = (query or "").lower()
    if not low.strip():
        return False
    for stem in banned:
        if not stem:
            continue
        if re.search(rf"\b{re.escape(stem)}\b", low):
            return True
        if re.search(rf"\b{re.escape(stem)}s\b", low):
            return True
    return False


def _mood_buckets_for_text(blob: str) -> list[str]:
    """Ordered mood buckets that fit the slide text / topic (best match first)."""
    low = (blob or "").lower()
    scored: list[tuple[int, int, str]] = []
    for bi, (bucket, keys) in enumerate(_MOOD_HINTS):
        hits = 0
        for k in keys:
            # Multi-word or short keys → word-ish match (avoid 'ate' in 'water')
            if " " in k or len(k) <= 3:
                if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", low):
                    hits += 2 if " " in k else 1
            elif k in low:
                hits += 1
        if hits:
            scored.append((-hits, bi, bucket))
    scored.sort()
    hits_ordered = [b for _neg, _bi, b in scored]
    if not hits_ordered:
        hits_ordered = ["general"]
    if "general" not in hits_ordered:
        hits_ordered.append("general")
    return hits_ordered


def _easy_query_context_score(query: str, blob: str) -> int:
    """Soft overlap: prefer easy queries that share mood words with the text."""
    q_toks = {
        w for w in re.findall(r"[a-z0-9']+", (query or "").lower()) if len(w) >= 3
    }
    b_toks = set(re.findall(r"[a-z0-9']+", (blob or "").lower()))
    score = len(q_toks & b_toks)
    nightish = bool(
        re.search(r"\b(night|1am|2am|3am|midnight|late)\b", blob or "")
    )
    if nightish and ("night" in q_toks or "dark" in q_toks):
        score += 2
    if re.search(r"\b(morning|wake)\b", blob or "") and "morning" in q_toks:
        score += 2
    return score


def style_pivot_queries(
    *,
    avoid: set[str] | frozenset[str] | None = None,
    max_n: int = 4,
    seed_text: str = "",
    slide_text: str = "",
    visual_scene: str = "",
    topic: str = "",
) -> list[str]:
    """
    Easy high-yield queries that still fit the slide's emotional context.

    Not "always coffee" — pick from mood banks (food night / bed / desk / city…)
    that Pinterest actually has live photos for. Does NOT re-forge onto the
    hard literal prop (that would defeat easing).
    """
    from core.harvester import finalize_photo_query

    avoid_l = {(a or "").strip().lower() for a in (avoid or ()) if a}
    banned = banned_subject_stems(avoid_l)
    blob = " ".join(
        x for x in (seed_text, slide_text, visual_scene, topic) if x
    ).lower()
    buckets = _mood_buckets_for_text(blob)
    # Failed food props → try bed/desk/city first (totally different subject)
    if banned & {
        "almond",
        "quinoa",
        "smoothie",
        "pasta",
        "scale",
        "fridge",
        "pantry",
        "salad",
        "chip",
        "snack",
        "pretzel",
        "cereal",
        "cream",
    }:
        deprior = {"food_night", "food_control"}
        buckets = [b for b in buckets if b not in deprior] + [
            b for b in buckets if b in deprior
        ]

    ranked: list[tuple[int, int, str]] = []
    seen_raw: set[str] = set()
    for bi, bucket in enumerate(buckets):
        for qi, raw in enumerate(_EASY_MOOD_BANKS.get(bucket, ())):
            low = raw.lower()
            if low in seen_raw or low in avoid_l:
                continue
            if query_hits_banned_subject(raw, banned):
                continue
            seen_raw.add(low)
            # earlier buckets + higher context overlap win
            score = _easy_query_context_score(raw, blob) * 10 - bi * 3 - qi
            ranked.append((score, bi, raw))

    ranked.sort(key=lambda t: (-t[0], t[1], t[2]))

    out: list[str] = []
    seen: set[str] = set(avoid_l)
    for _score, _bi, raw in ranked:
        q = finalize_photo_query(raw, slide_text="") or raw
        q = re.sub(r"\s+", " ", (q or "").strip())
        if not q or len(q.split()) < 2:
            continue
        if query_is_dna_cast(q):
            continue
        if query_hits_banned_subject(q, banned):
            continue
        low = q.lower()
        if low in seen:
            continue
        head = " ".join(low.split()[:2])
        if any(head == " ".join(s.split()[:2]) for s in seen):
            continue
        seen.add(low)
        out.append(q)
        if len(out) >= max_n:
            break
    return out


def vibe_rescue_queries(
    *,
    slide_text: str = "",
    visual_scene: str = "",
    topic: str = "",
    avoid: set[str] | frozenset[str] | None = None,
    max_n: int = 3,
    include_style_pivot: bool = False,
) -> list[str]:
    """
    Fresh Pinterest queries matching confession VIBE when primary pool failed.

    Prefer empty slot over stock — but try different scene angles first.
    Never DNA casting. Never reuse avoided queries.

    include_style_pivot=True appends easy context-fit queries after prop angles
    — for hard topics where literal props are scarce on Pinterest.
    """
    from core.harvester import finalize_photo_query

    avoid_l = {(a or "").strip().lower() for a in (avoid or ()) if a}
    banned = banned_subject_stems(avoid_l)
    blob = f"{visual_scene} {slide_text} {topic}"
    candidates: list[str] = []

    # 1) Every concrete prop phrase as its own query angle
    for phrase in _extract_props(blob, limit=4):
        if not query_hits_banned_subject(phrase, banned):
            candidates.append(phrase)

    # 2) Action + prop / place remixes
    action = _extract_action(blob)
    place = _valence_tail(blob)
    props = _extract_props(blob, limit=2)
    props = [p for p in props if not query_hits_banned_subject(p, banned)]
    if action and props:
        candidates.append(f"{action} {props[0]}")
    if props and place:
        candidates.append(f"{props[0]} {place}")
    if action and place and not banned:
        candidates.append(f"{action} {place} kitchen")

    # 3) visual_scene noun compress (different cut)
    nouns = _scene_nouns(visual_scene, limit=4)
    if len(nouns) >= 2:
        joined = " ".join(nouns[:3])
        if not query_hits_banned_subject(joined, banned):
            candidates.append(joined)
        if len(nouns) >= 3:
            joined2 = " ".join(nouns[1:4])
            if not query_hits_banned_subject(joined2, banned):
                candidates.append(joined2)

    # 4) High-signal confession props as short queries
    for key in (
        "pantry",
        "fridge",
        "pasta",
        "sink",
        "almonds",
        "scale",
        "spinach",
        "chips",
        "snacks",
        "laptop",
        "calendar",
        "plate",
        "gym",
        "sneakers",
        "counter",
    ):
        if query_hits_banned_subject(key, banned):
            continue
        if re.search(rf"\b{key}\b", blob, flags=re.I):
            if key in ("pantry", "fridge"):
                candidates.append(f"open {key} night")
            elif key == "pasta":
                candidates.append("pasta bowl sink")
            elif key == "almonds":
                candidates.append("almonds on desk")
            elif key == "scale":
                candidates.append("kitchen food scale")
            else:
                candidates.append(f"{key} kitchen candid")

    # Reserve slots for style pivots when requested
    prop_cap = max_n
    if include_style_pivot and max_n >= 2:
        prop_cap = max(1, max_n - min(3, max_n // 2))

    out: list[str] = []
    seen: set[str] = set(avoid_l)
    for raw in candidates:
        q = forge_pinterest_query(
            slide_text=slide_text,
            visual_scene=visual_scene,
            topic=topic,
            draft_query=raw,
        )
        q = finalize_photo_query(q, slide_text=slide_text or "") or q
        q = re.sub(r"\s+", " ", (q or "").strip())
        if not q or len(q.split()) < 2:
            continue
        if query_is_dna_cast(q):
            continue
        if query_hits_banned_subject(q, banned):
            continue
        low = q.lower()
        if low in seen:
            continue
        # Skip near-duplicates (same first two tokens)
        head = " ".join(low.split()[:2])
        if any(head == " ".join(s.split()[:2]) for s in seen):
            continue
        seen.add(low)
        out.append(q)
        if len(out) >= prop_cap:
            break

    if include_style_pivot and len(out) < max_n:
        for pq in style_pivot_queries(
            avoid=seen,
            max_n=max_n - len(out),
            seed_text=blob,
            slide_text=slide_text,
            visual_scene=visual_scene,
            topic=topic,
        ):
            low = pq.lower()
            if low in seen:
                continue
            if query_hits_banned_subject(pq, banned):
                continue
            seen.add(low)
            out.append(pq)
            if len(out) >= max_n:
                break
    return out
