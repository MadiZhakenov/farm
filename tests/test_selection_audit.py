#!/usr/bin/env python3
"""
Правки по аудиту ветки (2026-10-05): повторы фото, порядок ослабления правил,
фильтр «мыло», закреплённый случайный выбор, громкий сбой модели живости.

Запуск:  python -m pytest tests/test_selection_audit.py -q
Сеть, Gemini и SigLIP не нужны.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.carousel_rules import UsedIndex, image_fingerprint  # noqa: E402
from tests.test_feedback_rules import Cand, Slide, run_rules  # noqa: E402

# ---------------------------------------------------------------------------
# №1 / №3 — повтор в серии и лица ослабляются последними
# ---------------------------------------------------------------------------


def test_series_kept_when_refill_gives_fresh_photo():
    used = UsedIndex()
    stale = Cand("used-pin", seed=901)
    used.add("used-pin", image_fingerprint(stale.image))
    fresh = Cand("fresh", seed=902)
    slides = [Slide([Cand("hook", seed=1)]), Slide([stale]), Slide([Cand("fin", seed=3)])]
    res = run_rules(
        slides,
        roles=["scene", "neutral", "final"],
        used=used,
        refill=lambda i: [fresh] if i == 1 else [],
        extra_cands=[fresh],
    )
    assert slides[1].candidates[0].pin_id == "fresh"
    assert not res[1].series_reused and "series" not in res[1].relaxed


def test_faces_relaxed_before_series():
    used = UsedIndex()
    stale = Cand("used-pin", seed=903)
    used.add("used-pin", image_fingerprint(stale.image))
    with_face = Cand("face", seed=904, faces=1)
    slides = [Slide([Cand("hook", seed=1)]), Slide([stale, with_face]), Slide([Cand("fin", seed=3)])]
    res = run_rules(slides, roles=["scene", "scene", "final"], used=used)
    assert slides[1].candidates[0].pin_id == "face"
    assert "faces" in res[1].relaxed and "series" not in res[1].relaxed
    assert not res[1].series_reused


def test_last_resort_does_not_put_same_photo_twice():
    # финал: оба кадра «грязные» (на финале не ослабляется) → крайний случай;
    # первый из них — тот же кадр, что уже стоит на хуке
    hook = Cand("hook", seed=905)
    twin = Cand("twin", seed=905, mess=0.95)
    other = Cand("other", seed=906, mess=0.95)
    slides = [Slide([hook]), Slide([twin, other])]
    res = run_rules(slides, roles=["scene", "final"])
    assert res[1].relaxed == ["all"]
    assert slides[1].candidates[0].pin_id == "other"


def test_filler_bank_serves_each_photo_once_by_default():
    from core.filler_bank import FillerBank

    bank = FillerBank(min_serve=1)
    bank.add("pov cat lap", [Cand(f"c{k}", seed=910 + k) for k in range(2)])
    got = bank.take("pov cat lap")
    bank.mark_used([got[0].pin_id])
    assert [c.pin_id for c in bank.available("pov cat lap")] == ["c1"]


# ---------------------------------------------------------------------------
# №7 — перестановка в фабрике: выбор сборщика, смысл, сид
# ---------------------------------------------------------------------------


def _cand(pid: str, *, ugc: float, rel: float, mode: str = "hard_top3_sample"):
    from core.harvester import CandidateImage

    c = CandidateImage(pin_id=pid, title="", source_url="", query="q", image=Image.new("RGB", (8, 8)))
    c.ugc_score, c.ugc_scored = ugc, True
    c.taste_score, c.taste_scored = 0.7, True
    c.text_relevance, c.text_relevance_scored = rel, True
    c.selection_mode = mode
    return c


def _slide(cands):
    from core.batch_factory import BatchSlide

    return BatchSlide(text="t", query="q", candidates=list(cands), harmony_scores=[100.0] * len(cands))


def test_rerank_never_promotes_photo_further_from_text():
    from core.batch_factory import _apply_combined_ranking

    picks = set()
    for seed in range(40):
        lead = _cand("lead", ugc=0.70, rel=0.60)
        off = _cand("off-topic", ugc=0.95, rel=0.10)
        closer = _cand("closer", ugc=0.80, rel=0.70)
        s = _slide([lead, off, closer])
        _apply_combined_ranking(s, random.Random(seed))
        picks.add(s.candidates[0].pin_id)
    assert "off-topic" not in picks
    assert picks <= {"lead", "closer"}


def test_rerank_is_reproducible_with_same_topic_seed():
    from core.batch_factory import _apply_combined_ranking, _selection_rng

    def run() -> list[str]:
        cands = [_cand(f"p{k}", ugc=0.7 + k / 100, rel=0.5) for k in range(4)]
        s = _slide(cands)
        _apply_combined_ranking(s, _selection_rng("тема про ужин", 0))
        return [c.pin_id for c in s.candidates]

    assert run() == run()


def test_argmax_keeps_harvester_choice_and_replaces_only_below_floor():
    from core.batch_factory import _apply_combined_ranking

    lead = _cand("lead", ugc=0.60, rel=0.5, mode="single_pass_argmax")
    better = _cand("better", ugc=0.95, rel=0.9, mode="single_pass_argmax")
    s = _slide([lead, better])
    _apply_combined_ranking(s, random.Random(0))
    assert s.candidates[0].pin_id == "lead"

    weak = _cand("weak", ugc=0.30, rel=0.5, mode="single_pass_argmax")
    live = _cand("live", ugc=0.80, rel=0.6, mode="single_pass_argmax")
    s = _slide([weak, live])
    _apply_combined_ranking(s, random.Random(0))
    assert s.candidates[0].pin_id == "live"


# ---------------------------------------------------------------------------
# №6 — фильтр «мыло»: только явный брак
# ---------------------------------------------------------------------------


def test_soft_but_real_photo_is_not_low_quality():
    from core.harvester import looks_like_low_quality

    rng = np.random.default_rng(0)
    # гладкий «мех»: плавный градиент + мягкое зерно, без резких краёв
    y, x = np.mgrid[0:800, 0:600]
    base = 90 + 80 * np.sin(x / 90.0) * np.cos(y / 120.0)
    arr = np.clip(base + rng.normal(0, 2.0, base.shape), 0, 255).astype(np.uint8)
    soft = Image.fromarray(np.stack([arr, arr * 0.9, arr * 0.8], axis=-1).astype(np.uint8))
    assert not looks_like_low_quality(soft, bytes_len=90_000)


def test_tiny_or_dead_flat_photo_is_low_quality():
    from core.harvester import looks_like_low_quality

    assert looks_like_low_quality(Image.new("RGB", (300, 400), (120, 110, 100)))
    assert looks_like_low_quality(Image.new("RGB", (600, 800), (120, 110, 100)), bytes_len=90_000)
    assert looks_like_low_quality(Image.new("RGB", (600, 800), (120, 110, 100)), bytes_len=9_000)


# ---------------------------------------------------------------------------
# №10 — без модели живости собирать нельзя
# ---------------------------------------------------------------------------


class _Untrained:
    is_trained = False


def test_liveness_scoring_fails_loudly_without_model(monkeypatch):
    from core import ugc_classifier, ugc_filter

    monkeypatch.setattr(ugc_filter, "MODEL_ONLY", True)
    monkeypatch.setattr(ugc_classifier, "get_ugc_live_classifier", lambda: _Untrained())
    with pytest.raises(ugc_filter.LivenessModelError):
        ugc_filter.UGCFilter().score_details([], image_vecs=np.zeros((1, 8), dtype=np.float32))


def test_batch_refuses_to_start_without_liveness_model(monkeypatch):
    from core import batch_factory, ugc_classifier, ugc_filter

    monkeypatch.setattr(ugc_filter, "MODEL_ONLY", True)
    monkeypatch.setattr(ugc_classifier, "get_ugc_live_classifier", lambda: _Untrained())
    with pytest.raises(ugc_filter.LivenessModelError):
        batch_factory._require_liveness_model()
