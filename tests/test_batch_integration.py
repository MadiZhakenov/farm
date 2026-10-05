#!/usr/bin/env python3
"""
Сквозной тест фабрики без сети: Gemini и Pinterest подменены заглушками,
классификатор кадров — фейковый. Проверяет, что правки реально
срабатывают внутри build_one_carousel / run_batch.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import carousel_rules as cr  # noqa: E402
from core.harvester import CandidateImage, HarvestProgress  # noqa: E402

FOOD_TEXTS = [
    "I ate a salad for lunch and then stood in my pantry at 10pm eating crackers",
    "Turns out your brain isn't weak. It's starving after a day of tiny meals",
    "Honestly the hunger at night is interest on the calories you skipped",
    "You didn't fail your diet. You failed to feed yourself enough",
    "So basically, stop shrinking your lunch and your dinner will calm down",
    "Save this for the next time you feel guilty for being hungry at night",
]
OFF_TEXTS = [
    "I spent 15 minutes checking my reflection in the office hallway",
    "The truth is you aren't looking for a flaw",
    "Every time you stop at a window you practice being mean to yourself",
    "It is okay to be seen without being inspected first",
    "You don't need a better reflection",
    "Save this for the next time you pause at every storefront",
]

FEATURES: dict[int, cr.PhotoFeatures] = {}


def _img(seed: int) -> Image.Image:
    rnd = random.Random(seed)
    im = Image.new("RGB", (240, 320), tuple(rnd.randrange(256) for _ in range(3)))
    d = ImageDraw.Draw(im)
    for _ in range(10):
        x, y = rnd.randrange(240), rnd.randrange(320)
        d.rectangle([x, y, x + 60, y + 80], fill=tuple(rnd.randrange(256) for _ in range(3)))
    return im


def _cand(pin: str, seed: int, *, mess=0.1, place="other", q="q") -> CandidateImage:
    im = _img(seed)
    c = CandidateImage(pin_id=pin, title="", source_url="", query=q, image=im)
    c.ugc_score, c.ugc_scored = 0.8, True
    c.taste_score, c.taste_scored = 0.8, True
    c.text_relevance, c.text_relevance_scored = 0.7, True
    FEATURES[id(im)] = cr.PhotoFeatures(
        mess=mess, is_mess=mess >= cr.MESS_THRESHOLD, place=place, place_prob=0.9,
        fp=cr.image_fingerprint(im),
    )
    return c


class FakeClassifier:
    def features(self, images):
        return [FEATURES[id(im)] for im in images]


class FakeLLM:
    def __init__(self, texts_by_topic):
        self.texts_by_topic = texts_by_topic
        self.calls = []

    def generate_carousel(self, topic, product_name="", variation_index=0, avoid_character_dnas=None, **_kw):
        self.calls.append((topic, variation_index))
        texts = self.texts_by_topic.get(topic, FOOD_TEXTS)
        return {
            "slides": [
                {"text": t, "search_query": "open pantry night", "visual_scene": "person at open pantry at night"}
                for t in texts
            ],
            "character_dna": {"gender": "female", "hair": "long brown hair"},
            "model": "fake",
        }


class FakeHarvester:
    timing_pinterest_sec = 0.0
    timing_siglip_sec = 0.0
    last_attribute_consistency = None

    def __init__(self):
        self.seeded: set[str] = set()
        self.specs: list[tuple] = []
        self.refills: list[str] = []
        self.n = 0

    def reset_used(self):
        pass

    def seed_used(self, pins):
        self.seeded |= set(pins)

    def mark_used(self, pins):
        pass

    def warm_session(self, force=False):
        pass

    def search(self, q, finalize=True):
        return [object()]

    def reset_timing(self):
        pass

    def harvest_slides_parallel(self, specs, **kw):
        self.specs = list(specs)
        self.roles = list(kw.get("roles") or [])
        self.n += 1
        out = []
        last = 5  # FOOD_TEXTS / OFF_TEXTS — по 6 слайдов
        for q, text, idx, scene, alts in specs:
            base = self.n * 1000 + idx * 20
            if idx == last:
                # финал: три грязных сверху, чистый глубже
                cands = [_cand(f"{base}-{k}", base + k, mess=0.9) for k in range(3)]
                cands.append(_cand(f"{base}-clean", base + 9, mess=0.05))
            elif idx in (1, 2, 3):
                # три кухни подряд + один занятый в серии pin
                cands = [
                    _cand("used-1" if idx == 1 else f"{base}-k", base, place="kitchen"),
                    _cand(f"{base}-alt", base + 1, place="other"),
                ]
            else:
                cands = [_cand(f"{base}-a", base, mess=0.9 if idx == 4 else 0.1),
                         _cand(f"{base}-b", base + 1)]
            out.append((cands, HarvestProgress(), q))
        return out

    def harvest_until_filled(self, q, **kw):
        self.refills.append(q)
        return [_cand(f"refill-{len(self.refills)}", 99_000 + len(self.refills))], HarvestProgress(), q


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from core import photo_vault as pv

    vault = pv.PhotoVault(db_path=tmp_path / "vault.db", thumbs_dir=tmp_path / "thumbs")
    monkeypatch.setattr(pv, "_vault", vault)
    monkeypatch.setattr(cr, "get_photo_classifier", lambda: FakeClassifier())
    # used-1 уже стоит в другой карусели серии
    vault.register_usage("OTHER/carousel_009", 2, pin_id="used-1", image=_img(424242))
    return vault, tmp_path


def test_build_one_carousel_applies_all_rules(env):
    from core.batch_factory import build_one_carousel

    vault, tmp = env
    harv = FakeHarvester()
    used = vault.used_index()
    folder = build_one_carousel(
        llm=FakeLLM({}),
        harvester=harv,
        topic="Why you binge at night after eating clean all day",
        product="",
        out_dir=tmp / "run",
        index=1,
        variation_index=0,
        used_index=used,
        category="food",
    )
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    roles = [s["photo_role"] for s in meta["slides"]]
    assert roles == meta["photo_roles"] == harv.roles
    # у FakeLLM все запросы «open pantry night»: второй смысловой слайд
    # делит существительное с хуком -> филлер; смысловой только хук
    assert roles == ["scene", "neutral", "neutral", "neutral", "neutral", "final"]

    # 1) нейтральные/финальный слайды искали нейтральное, а рисуют настоящий текст
    for i, spec in enumerate(harv.specs):
        q, search_text, idx, scene, alts = spec
        if roles[i] != "scene":
            assert "pantry" not in q and "nothing dirty" in scene
    assert [s["text"] for s in meta["slides"]] == FOOD_TEXTS

    # 2) финал не грязный
    assert meta["slides"][-1]["is_mess"] is False
    # 3) грязи не больше одной на карусель
    assert sum(1 for s in meta["slides"] if s["is_mess"]) <= 1
    # 4) кухня не больше двух раз
    assert [s["place"] for s in meta["slides"]].count("kitchen") <= 2
    # 5) фото из другой карусели серии не выбрано
    assert "used-1" not in [s["pin_id"] for s in meta["slides"]]
    assert "used-1" in harv.seeded
    # 6) хештеги по теме
    caption = (folder / "caption.txt").read_text(encoding="utf-8")
    assert "#productivity" not in caption and "#foodfreedom" in caption
    # 7) учёт серии записан: 6 слайдов этой карусели
    with vault._connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM used_photos WHERE carousel=?",
            (str(folder.resolve()),),
        ).fetchone()["n"]
    assert n == 6
    # 8) alt -> pin сохранён для ручной замены
    assert meta["slides"][0]["alt_pins"]["0"]


def test_run_batch_skips_off_category_and_keeps_series_unique(env, monkeypatch):
    from core import batch_factory as bf

    vault, tmp = env
    topics = [
        "Why you binge at night after eating clean all day",
        "Counting almonds and calories until dinner",
        "Eating dinner standing over the kitchen counter",
        "Checking my reflection in the office hallway",
    ]
    llm = FakeLLM({topics[3]: OFF_TEXTS})
    harv = FakeHarvester()
    res = bf.run_batch(topics=topics, out_root=tmp / "out", llm=llm, harvester=harv)
    assert res.made == 3 and res.skipped == 1 and res.failed == 0
    skipped = (res.run_dir / "skipped_topics.txt").read_text(encoding="utf-8")
    assert "reflection" in skipped
    manifest = json.loads((res.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["category"] == "food" and manifest["skipped_off_category"] == 1

    # смысловые фото — одна карусель на серию; филлеры из банка батча можно
    # повторить (не больше MAX_REUSE каруселей), но не дважды в одной
    from core.filler_bank import MAX_REUSE

    semantic, filler = [], []
    for meta_path in sorted(res.run_dir.glob("carousel_*/meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        own = [s["pin_id"] for s in meta["slides"]]
        assert len(own) == len(set(own)), "внутри карусели фото не повторяется"
        for s in meta["slides"]:
            (filler if s["photo_role"] in ("neutral", "final") else semantic).append(s["pin_id"])
    assert len(semantic) + len(filler) == 18
    assert len(semantic) == len(set(semantic))
    from collections import Counter

    assert max(Counter(filler).values()) <= MAX_REUSE
