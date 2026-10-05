#!/usr/bin/env python3
"""
Тесты правок по фидбеку 2026-09-29 (пачка 06_food_body_image).

Запуск:  python -m pytest tests/test_feedback_rules.py -q
Сеть, Gemini и SigLIP не нужны: картинки оцениваются фейковым классификатором,
Pinterest и Gemini подменены заглушками.
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import carousel_rules as cr  # noqa: E402
from core.carousel_rules import (  # noqa: E402
    PhotoFeatures,
    UsedIndex,
    build_photo_plans,
    enforce_carousel_rules,
    hamming,
    image_fingerprint,
    plan_roles,
)

MESS_WORDS = re.compile(
    r"\b(mess|messy|dirty|dishes|trash|garbage|crumbs|spill|spilled|wrappers|"
    r"leftovers?|chaos|clutter|over sink)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------


def make_img(seed: int, size=(240, 320)) -> Image.Image:
    """Уникальная картинка: цветные прямоугольники по seed."""
    import random

    rnd = random.Random(seed)
    im = Image.new("RGB", size, tuple(rnd.randrange(256) for _ in range(3)))
    d = ImageDraw.Draw(im)
    for _ in range(12):
        x0, y0 = rnd.randrange(size[0]), rnd.randrange(size[1])
        x1, y1 = x0 + rnd.randrange(20, 120), y0 + rnd.randrange(20, 160)
        d.rectangle([x0, y0, x1, y1], fill=tuple(rnd.randrange(256) for _ in range(3)))
    return im


class Cand:
    def __init__(self, pin, *, mess=0.1, place="other", seed=None, title="", subject="other", ugc=None, faces=0):
        self.pin_id = str(pin)
        self.title = title
        self.image = make_img(seed if seed is not None else hash(pin) % 10_000)
        self._mess = mess
        self._place = place
        self._subject = subject
        self._faces = faces
        if ugc is not None:
            self.ugc_score, self.ugc_scored = float(ugc), True


class FakeClassifier:
    def features(self, images):
        raise AssertionError("use cand features")


class CandClassifier:
    """Берёт «правду» из атрибутов кандидата (для enforce_*)."""

    def __init__(self, cands):
        self.by_img = {id(c.image): c for c in cands}

    def features(self, images):
        out = []
        for im in images:
            c = self.by_img[id(im)]
            out.append(
                PhotoFeatures(
                    mess=c._mess,
                    is_mess=c._mess >= cr.MESS_THRESHOLD,
                    place=c._place,
                    place_prob=0.9,
                    fp=image_fingerprint(im),
                    subject=c._subject,
                    subject_prob=0.9 if c._subject != "other" else 0.0,
                    faces=c._faces,
                )
            )
        return out


class Slide:
    def __init__(self, cands):
        self.candidates = list(cands)
        self.selected = 0


def run_rules(slides, roles=None, **kw):
    allc = [c for s in slides for c in s.candidates]
    extra = kw.pop("extra_cands", [])
    clf = CandClassifier(allc + list(extra))
    roles = roles or plan_roles(len(slides))
    return enforce_carousel_rules(slides, roles=roles, classifier=clf, **kw)


# ---------------------------------------------------------------------------
# 1. Роли слайдов
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [6, 7, 8, 9])
def test_roles_first_scene_last_final_middle_alternates(n):
    # сцена / филлер по очереди: сценные слайды дают живые бытовые кадры
    roles = plan_roles(n)
    assert roles[0] == "scene"
    assert roles[-1] == "final"
    middle = roles[1:-1]
    assert "neutral" in middle and "scene" in middle
    for a, b in zip(middle, middle[1:]):
        assert a != b, f"середина должна чередоваться: {roles}"


def test_roles_six_slides_exact():
    assert plan_roles(6) == ["scene", "scene", "neutral", "scene", "neutral", "final"]
    assert plan_roles(3) == ["scene", "scene", "final"]


def test_roles_product_slide_is_semantic():
    roles = plan_roles(8, product_index=4)
    assert roles == ["scene", "scene", "neutral", "scene", "product", "scene", "neutral", "final"]


def test_product_name_from_free_text_field():
    assert cr.product_names("Приложение FocusFlow: лимит 3 задачи в день") == ["focusflow"]
    assert cr.product_names("cozy home app — coloring") == ["cozy home"]
    texts = ["hook", "line", "I opened Cozy Home and colored for 20 min", "x", "save this"]
    assert cr.find_product_slide(texts, "Cozy Home") == 2
    assert cr.find_product_slide(texts, "") is None
    # продукт на хуке / финале не делает их «продуктом»
    assert cr.find_product_slide(["Cozy Home saved me", "a", "b"], "Cozy Home") is None


def test_neutral_and_final_queries_are_clean_and_survive_cleaner():
    from core.harvester import finalize_photo_query, is_weak_pinterest_query

    pools = (
        cr.NEUTRAL_LIGHT + cr.NEUTRAL_FOOD + cr.NEUTRAL_MOODY
        + cr.FINAL_PLEASANT + cr.FINAL_CALM
    )
    for q in pools:
        assert not MESS_WORDS.search(q), q
        f = finalize_photo_query(q, 1, slide_text="")
        assert f == q, f"чистильщик запросов меняет «{q}» -> «{f}»"
        assert not is_weak_pinterest_query(f), q


def test_build_plans_food_topic():
    texts = [
        "I ate a salad for lunch and then stood in front of my pantry at 10pm",
        "Turns out your brain isn't weak, it's starving",
        "Honestly the hunger at night is interest on skipped calories",
        "You didn't fail your diet, you failed to feed yourself",
        "Stop shrinking yourself during the day",
        "Save this for the next time you feel guilty for being hungry",
    ]
    props = ["open pantry night", "lunch salad desk", "tea mug bed",
             "calorie app phone", "lunch box office", "tea mug bed"]
    specs = [(props[i], "scene", []) for i in range(6)]
    plans, heavy = build_photo_plans(texts, specs, topic="night binge after eating clean", seed=1)
    assert not heavy
    assert [p.role for p in plans] == plan_roles(6)
    # сценарные слайды сохраняют свой запрос и настоящий текст для поиска
    assert plans[0].query == "open pantry night" and plans[0].search_text == texts[0]
    queries = [p.query for p in plans]
    assert len(set(queries)) == len(queries), "запросы в карусели не повторяются"
    for p in plans:
        if p.role != "scene":
            assert not MESS_WORDS.search(p.query)
            assert "pantry" not in p.search_text  # нейтральный кадр не ищет проп сценария
            assert "nothing dirty" in p.visual_scene
    assert plans[-1].query in cr.FINAL_PLEASANT


def test_build_plans_heavy_topic_uses_moody_middle_calm_final():
    texts = ["I have been depressed for months"] + ["line"] * 5
    specs = [("bed phone night", "", [])] * 6
    plans, heavy = build_photo_plans(texts, specs, topic="living with depression", seed=2)
    assert heavy
    for p in plans:
        if p.role == "neutral":
            assert p.query in cr.NEUTRAL_MOODY
        if p.role == "final":
            assert p.query in cr.FINAL_CALM


def test_plans_rotate_between_carousels():
    texts = ["a"] * 6
    specs = [("q", "", [])] * 6
    finals = {
        build_photo_plans(texts, specs, topic=f"topic {k}", seed=k)[0][-1].query
        for k in range(12)
    }
    assert len(finals) >= 4, f"финальные запросы не должны быть одинаковыми: {finals}"


# ---------------------------------------------------------------------------
# 2. Антигрязь в запросах
# ---------------------------------------------------------------------------


MESSY_SLIDES = [
    ("I ate a loaf of sourdough over the sink at midnight", "person eating bread over kitchen sink at midnight"),
    ("I layered snack wrappers under old mail so my roommate wouldn't know", "snack wrappers under mail on table"),
    ("that empty plate with crumbs is my whole personality", "empty plate with crumbs"),
    ("my desk was a disaster of takeout boxes", "desk with takeout boxes"),
    ("I binged a whole bag of chips in the dark", "chip bag on couch at night"),
    ("I stood at the kitchen counter demolishing leftovers", "kitchen counter at night"),
    ("I spiraled over one slice of pizza", "pizza box on counter"),
    ("cold pasta straight from the pot over the sink", "pasta pot at sink"),
]


@pytest.mark.parametrize("text,scene", MESSY_SLIDES)
def test_query_forge_produces_no_mess_words(text, scene):
    from core.query_forge import own_slide_query, forge_pinterest_query

    q1 = own_slide_query(slide_text=text, visual_scene=scene, topic="food binge", slide_index=2)
    q2 = forge_pinterest_query(slide_text=text, visual_scene="", topic="food binge")
    for q in (q1, q2):
        assert not MESS_WORDS.search(q), f"{text!r} -> {q!r}"


def test_mood_banks_and_prop_phrases_clean():
    from core import query_forge as qf

    for bank in qf._EASY_MOOD_BANKS.values():
        for q in bank:
            assert not MESS_WORDS.search(q), q
    for _k, phrase in qf._PROP_PHRASES:
        assert not MESS_WORDS.search(phrase), phrase
    for _k, act in qf._ACTION_CUES:
        assert act != "messy"


def test_ugc_anchors_no_longer_reward_mess():
    from core.ugc_filter import UGC_ANCHORS

    for a in UGC_ANCHORS:
        assert "messy" not in a and "chaos" not in a


def test_gemini_prompt_forbids_dirt_in_visual_scene():
    from core.llm_engine import build_system_prompt

    prompt = build_system_prompt([])
    assert "NEVER describe dirt" in prompt
    assert '"pasta over sink"' not in prompt


# ---------------------------------------------------------------------------
# 3. Правила карусели
# ---------------------------------------------------------------------------


def test_final_slide_never_mess():
    slides = [Slide([Cand(f"s{i}a"), Cand(f"s{i}b")]) for i in range(5)]
    slides.append(Slide([Cand("f_dirty", mess=0.9), Cand("f_clean", mess=0.1)]))
    res = run_rules(slides)
    assert slides[-1].candidates[0].pin_id == "f_clean"
    assert res[-1].swapped and not res[-1].is_mess


def test_mess_budget_one_per_carousel():
    slides = [
        Slide([Cand("a_dirty", mess=0.9), Cand("a_clean")]),
        Slide([Cand("b_dirty", mess=0.9), Cand("b_clean")]),
        Slide([Cand("c_dirty", mess=0.9), Cand("c_clean")]),
        Slide([Cand("d")]),
        Slide([Cand("e")]),
        Slide([Cand("f")]),
    ]
    res = run_rules(slides)
    picked = [s.candidates[0].pin_id for s in slides]
    assert sum(1 for p in picked if "dirty" in p) == 1
    assert picked[0] == "a_dirty"  # первый грязный остаётся (бюджет 1)
    assert picked[1] == "b_clean" and picked[2] == "c_clean"
    assert sum(r.is_mess for r in res) == 1


def test_heavy_topic_allows_two_mess_but_not_final():
    slides = [Slide([Cand(f"{k}_dirty", mess=0.9), Cand(f"{k}_clean")]) for k in "abcdef"]
    run_rules(slides, heavy=True)
    picked = [s.candidates[0].pin_id for s in slides]
    assert sum(1 for p in picked if "dirty" in p) == 2
    assert picked[-1] == "f_clean"


def test_same_place_max_two():
    slides = [
        Slide([Cand(f"k{i}", place="kitchen"), Cand(f"o{i}", place="other")])
        for i in range(5)
    ]
    slides.append(Slide([Cand("fin", place="other")]))
    res = run_rules(slides)
    places = [r.place for r in res]
    assert places.count("kitchen") == 2, places
    assert not any(r.relaxed for r in res)


def test_every_limited_place_counts():
    """Кухня и улица обе на лимите -> третья улица/кухня только с ослаблением."""
    slides = [
        Slide([Cand(f"k{i}", place="kitchen"), Cand(f"s{i}", place="street")])
        for i in range(5)
    ]
    slides.append(Slide([Cand("fin", place="other")]))
    res = run_rules(slides)
    places = [r.place for r in res]
    assert places.count("street") == 2
    assert sum(1 for r in res if "place" in r.relaxed) == 1


def test_place_limit_relaxed_when_no_alternative():
    slides = [Slide([Cand(f"k{i}", place="kitchen")]) for i in range(4)]
    res = run_rules(slides, roles=["scene"] * 4)
    assert [r.place for r in res].count("kitchen") == 4
    assert any("place" in r.relaxed for r in res)


def test_series_used_photo_is_skipped_by_pin_and_by_fingerprint():
    a = Cand("used_pin")
    b_img_same_as_other_carousel = Cand("repin_new_id", seed=777)
    good = Cand("fresh")
    used = UsedIndex()
    used.add("used_pin", None)
    used.add("some_other", image_fingerprint(make_img(777)))
    slides = [Slide([a, good]), Slide([b_img_same_as_other_carousel, Cand("fresh2")])]
    res = run_rules(slides, roles=["scene", "final"], used=used)
    assert slides[0].candidates[0].pin_id == "fresh"
    assert slides[1].candidates[0].pin_id == "fresh2"
    assert not any(r.series_reused for r in res)


def test_series_relaxed_only_when_nothing_else_and_flagged():
    used = UsedIndex()
    used.add("only", None)
    slides = [Slide([Cand("only")])]
    res = run_rules(slides, roles=["scene"], used=used)
    assert res[0].series_reused and "series" in res[0].relaxed


def test_no_duplicate_photo_inside_carousel():
    twin1 = Cand("p1", seed=55)
    twin2 = Cand("p2", seed=55)  # тот же кадр под другим pin
    slides = [Slide([twin1]), Slide([twin2, Cand("other")])]
    run_rules(slides, roles=["scene", "final"])
    assert {slides[0].candidates[0].pin_id, slides[1].candidates[0].pin_id} != {"p1", "p2"}


def test_final_all_mess_triggers_refill():
    extra = [Cand("refill_clean", mess=0.05)]
    slides = [Slide([Cand("a")]), Slide([Cand("f1", mess=0.9), Cand("f2", mess=0.8)])]
    calls = []

    def refill(i):
        calls.append(i)
        return extra

    res = run_rules(slides, roles=["scene", "final"], refill=refill, extra_cands=extra)
    assert calls == [1]
    assert slides[1].candidates[0].pin_id == "refill_clean"
    assert not res[1].is_mess


def test_rules_keep_rank_order_when_nothing_violated():
    slides = [Slide([Cand(f"s{i}a"), Cand(f"s{i}b")]) for i in range(6)]
    res = run_rules(slides)
    assert [s.candidates[0].pin_id for s in slides] == [f"s{i}a" for i in range(6)]
    assert not any(r.swapped for r in res)


def test_classifier_failure_does_not_break_selection():
    class Broken:
        def features(self, images):
            raise RuntimeError("no model")

    slides = [Slide([Cand("x"), Cand("y")]), Slide([Cand("z")])]
    res = enforce_carousel_rules(slides, roles=["scene", "final"], classifier=Broken())
    assert slides[0].candidates[0].pin_id == "x"
    assert res[1].photo_role == "final"


# ---------------------------------------------------------------------------
# 4. Отпечаток фото
# ---------------------------------------------------------------------------


def test_fingerprint_survives_resize_and_jpeg_but_separates_different_photos():
    base = ROOT / "bg_ipad.jpg"
    im = Image.open(base).convert("RGB")
    fp = image_fingerprint(im)
    small = im.resize((im.width // 3, im.height // 3))
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=55)
    recompressed = Image.open(io.BytesIO(buf.getvalue()))
    assert hamming(fp, image_fingerprint(recompressed)) <= cr.FP_HAMMING_MAX
    others = [image_fingerprint(make_img(s, size=im.size)) for s in range(30)]
    assert min(hamming(fp, o) for o in others) > cr.FP_HAMMING_MAX


# ---------------------------------------------------------------------------
# 5. Учёт серии в PhotoVault
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    from core import photo_vault as pv

    v = pv.PhotoVault(db_path=tmp_path / "v.db", thumbs_dir=tmp_path / "thumbs")
    monkeypatch.setattr(pv, "_vault", v)
    return v


def test_vault_usage_roundtrip(vault):
    img = make_img(1)
    vault.register_usage("C:/out/run1/carousel_001", 1, pin_id="111", image=img)
    vault.register_usage("C:/out/run1/carousel_002", 3, pin_id="222", image=make_img(2))
    idx = vault.used_index()
    assert {"111", "222"} <= idx.pins
    assert idx.is_used(None, image_fingerprint(img))
    own = vault.used_index(exclude_carousel="C:/out/run1/carousel_001")
    assert "111" not in own.pins and "222" in own.pins
    # ручная замена того же слайда заменяет запись
    vault.register_usage("C:/out/run1/carousel_002", 3, pin_id="333", image=make_img(3))
    idx2 = vault.used_index()
    assert "222" not in idx2.pins and "333" in idx2.pins
    assert vault.release_carousel("C:/out/run1/carousel_002") == 1


def test_vault_register_selected_records_usage_and_fp(vault):
    items = [
        {"pin_id": "900", "image": make_img(9), "query": "q", "carousel": "K", "slide": 1},
        {"pin_id": "901", "image": make_img(10), "query": "q", "carousel": "K", "slide": 2},
    ]
    assert vault.register_selected(items) == 2
    idx = vault.used_index()
    assert {"900", "901"} <= idx.pins
    assert idx.is_used(None, image_fingerprint(make_img(9)))
    # свои фото карусели не считаются занятыми при отсмотре
    own = vault.used_index(exclude_carousel="K")
    assert not own.is_used("900", image_fingerprint(make_img(9)))


def test_vault_backfills_fingerprints_from_old_thumbs(vault):
    vault.add_approved_photo("777", make_img(77), query="old")
    with vault._connect() as conn:
        conn.execute("UPDATE approved_photos SET fp=NULL")
        conn.commit()
    idx = vault.used_index()
    assert idx.is_used(None, image_fingerprint(make_img(77)))


def test_vault_migrates_old_db_without_fp_column(tmp_path):
    import sqlite3

    from core.photo_vault import PhotoVault

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE approved_photos (pin_id TEXT PRIMARY KEY, image_url TEXT, "
        "local_thumb_path TEXT, query TEXT, tags TEXT, added_at TEXT, status TEXT);"
        "INSERT INTO approved_photos VALUES ('5','', '', 'q','t','x','approved');"
    )
    conn.commit()
    conn.close()
    v = PhotoVault(db_path=db, thumbs_dir=tmp_path / "t")
    assert "5" in v.used_index().pins


# ---------------------------------------------------------------------------
# 6. Категории и хештеги
# ---------------------------------------------------------------------------


def _hooks_from_batch():
    p = Path("/mnt/user-data/uploads/farm-main/06_food_body_image/tt_descriptions.txt")
    if not p.is_file():
        pytest.skip("нет tt_descriptions.txt пачки 06")
    raw = p.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=\d+\.\n)", raw)
    return [b.strip().split("\n")[1:3] for b in blocks]


def test_category_filter_on_real_batch():
    from core.niches import dominant_category, fits_category

    rows = _hooks_from_batch()
    cat = dominant_category([r[0] for r in rows])
    assert cat == "food"
    off = [i + 1 for i, (hook, body) in enumerate(rows) if not fits_category(cat, hook, [body])]
    assert 10 in off and 46 in off, off  # «отражение в коридоре», «примерочная»
    assert 7 not in off  # «приглашение на ужин» проверяющей понравилось
    assert len(off) <= 5, off


def test_hashtags_follow_topic():
    from core.caption_engine import generate_caption

    food = generate_caption(["I binged crackers at 10pm", "your brain is starving"], "night binge after dieting")
    assert "#productivity" not in food and "#intuitiveeating" in food
    work = generate_caption(["I avoided one email for 3 weeks"], "procrastination at work")
    assert "#productivity" in work
    body = generate_caption(["I checked my reflection 20 times"], "body image and mirrors")
    assert "#bodyimage" in body


def test_mixed_topic_list_has_no_category():
    from core.niches import dominant_category

    assert dominant_category(["gym motivation", "skincare at night", "procrastinating work", "dating anxiety"]) is None


# ---------------------------------------------------------------------------
# Фидбек 2026-10-02: смысловые / филлеры, один предмет на карусель
# ---------------------------------------------------------------------------


def test_query_nouns_and_conflicts():
    assert cr.queries_conflict("chip bag couch night", "chips bag counter candid")
    assert cr.queries_conflict("coffee mug desk", "hands holding coffee cup")
    assert not cr.queries_conflict("open pantry night", "street night walk")
    assert "chip" in cr.query_nouns("crisps on couch")


def test_second_semantic_slide_sharing_hook_noun_takes_alt_or_becomes_filler():
    texts = ["hook", "a", "b", "c", "d", "save"]
    specs = [("chip bag couch night", "", [])] + [("x", "", [])] * 5
    # середина (индекс 3) тянет те же чипсы, но есть альт без них
    specs[3] = ("chips bag counter candid", "", ["dinner plate table"])
    plans, _ = build_photo_plans(texts, specs, topic="snacks", seed=3)
    assert plans[3].role == "scene" and plans[3].query == "dinner plate table"
    # альта нет — слайд становится филлером
    specs[3] = ("chips bag counter candid", "", ["crisps on couch"])
    plans, _ = build_photo_plans(texts, specs, topic="snacks", seed=3)
    assert plans[3].role == "neutral"


def test_fillers_are_live_and_take_distinct_subjects():
    texts = ["hook"] + ["line"] * 8 + ["save"]
    specs = [("coffee mug desk morning", "", [])] + [("x", "", [])] * 9
    for seed in range(15):
        for topic in (f"tired at work {seed}", f"snack binge food {seed}", f"breakup grief {seed}"):
            plans, _ = build_photo_plans(texts, specs, topic=topic, seed=seed)
            fillers = [p for p in plans if p.role in ("neutral", "final")]
            subj = [cr.query_subject(p.query) for p in fillers]
            assert len(subj) == len(set(subj)), f"{topic}: предметы повторяются {[p.query for p in fillers]}"
            for p in fillers:
                assert cr.filler_liveness(p.query) >= cr.FILLER_LIVE_MIN, p.query
                assert not cr.queries_conflict(p.query, "coffee mug desk morning"), p.query


def test_query_subjects_map():
    assert cr.query_subjects("hands holding coffee cup") == {"drink"}
    assert cr.query_subject("bus window night city") == "car"
    assert cr.query_subject("sky clouds window") == "sky"
    assert cr.query_subjects("chip bag couch night") == {"snacks", "room"}
    assert "kitchen" in cr.query_subjects("standing kitchen counter night")
    # «counting» — не предмет: разные предметы не конфликтуют
    assert not cr.queries_conflict("counting almonds handful desk", "counting kitchen counter night")
    assert cr.queries_conflict("standing kitchen counter night", "kitchen counter night plate")


def test_same_subject_max_one_per_carousel_filler_yields():
    # хук — чипсы; у филлера первыми тоже чипсы, глубже — окно
    slides = [
        Slide([Cand("hook-chips", subject="snacks")]),
        Slide([Cand("f-chips", subject="snacks"), Cand("f-window", subject="window")]),
        Slide([Cand("fin", subject="drink")]),
    ]
    res = run_rules(slides, roles=["scene", "neutral", "final"])
    assert slides[0].candidates[0].pin_id == "hook-chips"
    assert slides[1].candidates[0].pin_id == "f-window"
    assert [r.subject for r in res] == ["snacks", "window", "drink"]


def test_product_slide_not_limited_by_subject():
    slides = [
        Slide([Cand("hook-tablet", subject="desk")]),
        Slide([Cand("prod-tablet", subject="desk"), Cand("prod-other", subject="room")]),
        Slide([Cand("fin", subject="drink")]),
    ]
    run_rules(slides, roles=["scene", "product", "final"])
    assert slides[1].candidates[0].pin_id == "prod-tablet"


def test_subject_never_triggers_slow_refill():
    calls = []

    def refill(i):
        calls.append(i)
        return [Cand("refill-sky", subject="sky")]

    slides = [
        Slide([Cand("hook-road", subject="road")]),
        Slide([Cand("f-road", subject="road")]),
        Slide([Cand("fin", subject="drink")]),
    ]
    res = run_rules(slides, roles=["scene", "neutral", "final"], refill=refill)
    # дозапрос медленный и даёт кадры хуже: из-за предмета его не делаем
    assert calls == []
    assert slides[1].candidates[0].pin_id == "f-road"
    assert "subject" in res[1].relaxed


def test_subject_swap_never_costs_liveness():
    # другой предмет заметно менее живой — оставляем повтор
    slides = [
        Slide([Cand("hook-chips", subject="snacks", ugc=0.70)]),
        Slide([Cand("f-chips", subject="snacks", ugc=0.68), Cand("f-stock", subject="window", ugc=0.40)]),
        Slide([Cand("fin", subject="drink", ugc=0.6)]),
    ]
    res = run_rules(slides, roles=["scene", "neutral", "final"])
    assert slides[1].candidates[0].pin_id == "f-chips"
    assert "subject" in res[1].relaxed
    # почти такой же живой — меняем
    slides = [
        Slide([Cand("hook-chips", subject="snacks", ugc=0.70)]),
        Slide([Cand("f-chips", subject="snacks", ugc=0.68), Cand("f-window", subject="window", ugc=0.65)]),
        Slide([Cand("fin", subject="drink", ugc=0.6)]),
    ]
    run_rules(slides, roles=["scene", "neutral", "final"])
    assert slides[1].candidates[0].pin_id == "f-window"


def test_subject_relaxed_only_when_nothing_else():
    slides = [
        Slide([Cand("hook-road", subject="road")]),
        Slide([Cand("f-road", subject="road")]),
        Slide([Cand("fin", subject="drink")]),
    ]
    res = run_rules(slides, roles=["scene", "neutral", "final"])
    assert slides[1].candidates[0].pin_id == "f-road"
    assert "subject" in res[1].relaxed


def test_bank_filler_may_repeat_series_photo_but_semantic_may_not():
    old = Cand("old-pin", seed=777)
    used = UsedIndex()
    used.add("old-pin", image_fingerprint(old.image))
    fresh = Cand("fresh", seed=778)
    # филлер: pin из банка батча — повтор разрешён
    slides = [Slide([Cand("hook", seed=1)]), Slide([old, fresh]), Slide([Cand("fin", seed=3)])]
    run_rules(slides, roles=["scene", "neutral", "final"], used=used, reuse_ok={"old-pin"})
    assert slides[1].candidates[0].pin_id == "old-pin"
    # смысловой слайд: тот же pin занят в серии — берём свежий
    old2 = Cand("old-pin", seed=777)
    slides = [Slide([Cand("hook", seed=1)]), Slide([old2, Cand("fresh2", seed=779)]), Slide([Cand("fin", seed=3)])]
    run_rules(slides, roles=["scene", "scene", "final"], used=used, reuse_ok={"old-pin"})
    assert slides[1].candidates[0].pin_id == "fresh2"


def test_filler_bank_reuse_cap_and_isolation():
    from core.filler_bank import FillerBank

    bank = FillerBank(max_reuse=2, min_serve=2)
    cands = [Cand(f"p{k}", seed=500 + k) for k in range(3)]
    assert bank.add("tea mug windowsill", cands) == 3
    assert bank.can_serve("tea mug windowsill")
    got = bank.take("tea mug windowsill")
    assert [c.pin_id for c in got] == ["p0", "p1", "p2"]
    # копии: закрытие картинки карусели не портит банк
    got[0].image.close()
    assert bank.take("tea mug windowsill")[0].image.size == cands[0].image.size
    bank.mark_used(["p0", "p0", "p1", "p1"])
    left = [c.pin_id for c in bank.available("tea mug windowsill")]
    assert left == ["p2"] and not bank.can_serve("tea mug windowsill")
    assert bank.known_pins() == {"p0", "p1", "p2"}


def test_wide_assign_soft_subject_penalty():
    import numpy as np
    from core import harvester as hv

    def mk(pid, rank):
        c = hv.CandidateImage(pin_id=pid, title="", source_url="", query="q", image=None)
        c._wide_rank = rank
        c.text_relevance = 0.9
        return c

    # слайд 0: чипсы (1.0); слайд 1: чипсы (0.9) или окно (0.6, та же ступень)
    eligible = [[mk("chips-a", 8.9)], [mk("chips-b", 8.8), mk("window", 8.5)]]
    rng = np.random.default_rng(0)
    vec_of = {}
    for pid in ("chips-a", "chips-b", "window"):
        v = rng.normal(size=16).astype(np.float32)
        vec_of[pid] = v / np.linalg.norm(v)
    subjects = {"chips-a": "snacks", "chips-b": "snacks", "window": "window"}
    out = hv._wide_assign(eligible, vec_of, limit=3, subjects=subjects)
    assert out[1][0].pin_id == "window"
    # без меток — берётся лучший по рангу
    out = hv._wide_assign(eligible, vec_of, limit=3)
    assert out[1][0].pin_id == "chips-b"
    # слайд-продукт не штрафуется
    out = hv._wide_assign(eligible, vec_of, limit=3, subjects=subjects, exempt={1})
    assert out[1][0].pin_id == "chips-b"
    # штраф не опускает на ступень ниже: окно ступени B (6.x) не берём
    eligible2 = [[mk("chips-a", 8.9)], [mk("chips-b", 8.8), mk("window", 6.9)]]
    out = hv._wide_assign(eligible2, vec_of, limit=3, subjects=subjects)
    assert out[1][0].pin_id == "chips-b"
    # и не ценой живости: окно заметно менее живое — остаются чипсы
    b, w = mk("chips-b", 8.8), mk("window", 8.5)
    b.ugc_score, b.ugc_scored = 0.70, True
    w.ugc_score, w.ugc_scored = 0.40, True
    out = hv._wide_assign([[mk("chips-a", 8.9)], [b, w]], vec_of, limit=3, subjects=subjects)
    assert out[1][0].pin_id == "chips-b"


def test_hook_keeps_relationship_query():
    from core.query_forge import own_slide_queries

    dna = {"gender": "female", "hair": "long brown hair"}
    q, _ = own_slide_queries(slide_text="my mom said I was too thin",
                             visual_scene="mom daughter kitchen", topic="food guilt",
                             slide_index=0, draft_query="mom daughter kitchen",
                             character_dna=dna, max_alts=1)
    assert q == "mom daughter kitchen"
    q2, _ = own_slide_queries(slide_text="my dad asks if I ate", visual_scene="father daughter cafe",
                              topic="food", slide_index=0, draft_query="father daughter cafe",
                              character_dna=dna, max_alts=1)
    assert q2 == "father daughter cafe"


def test_prompt_has_hook_photo_rule():
    from core.llm_engine import build_system_prompt

    prompt = build_system_prompt([])
    assert "HOOK PHOTO (slide 1)" in prompt
    assert "father daughter cafe" in prompt


def test_filler_bank_query_cap_rotates_scenes():
    from core.filler_bank import FillerBank

    bank = FillerBank(max_reuse=10, min_serve=1, max_query_reuse=2)
    bank.add("ocean waves beach", [Cand(f"o{k}", seed=600 + k) for k in range(5)])
    bank.add("record player vinyl", [Cand(f"v{k}", seed=700 + k) for k in range(5)])
    assert bank.take("ocean waves beach") and bank.take("ocean waves beach")
    # запрос взят в 2 карусели — больше не предлагается, реже взятые — первыми
    assert not bank.take("ocean waves beach")
    assert bank.ready_queries() == ["record player vinyl"]



def test_filler_bank_queries_are_measured_live_and_survive_cleaner():
    pools = cr.NEUTRAL_LIGHT + cr.NEUTRAL_FOOD + cr.NEUTRAL_MOODY + cr.FINAL_PLEASANT + cr.FINAL_CALM
    for q in set(pools):
        assert cr.filler_liveness(q) >= cr.FILLER_LIVE_MIN, q
    # стоковые прежние филлеры в пулы не вернулись
    for q in ("flowers vase table", "sheer curtains bedroom window", "sunset city skyline"):
        assert q not in pools


def test_faces_skipped_after_hook_but_allowed_on_hook():
    slides = [
        Slide([Cand("hook-face", faces=1), Cand("hook-noface")]),
        Slide([Cand("f-face", faces=2), Cand("f-noface")]),
        Slide([Cand("fin-face", faces=1)]),
    ]
    res = run_rules(slides, roles=["scene", "neutral", "final"])
    assert slides[0].candidates[0].pin_id == "hook-face"
    assert slides[1].candidates[0].pin_id == "f-noface"
    # заменить нечем — лицо остаётся, с пометкой
    assert slides[2].candidates[0].pin_id == "fin-face"
    assert "faces" in res[2].relaxed


def test_scene_slides_get_candid_variant():
    texts = ["hook", "a", "b", "c", "d", "save"]
    specs = [("standing kitchen counter night", "", []), ("pasta plate", "", []),
             ("x", "", []), ("gym bag floor hallway", "", []), ("x", "", []), ("x", "", [])]
    plans, _ = build_photo_plans(texts, specs, topic="food", seed=1)
    assert "standing kitchen counter candid" in plans[0].alts
    assert cr.candid_variant("chip bag couch night aesthetic") == "chip bag couch candid"
    assert cr.candid_variant("x") == ""
