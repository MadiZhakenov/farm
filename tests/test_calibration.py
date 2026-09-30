#!/usr/bin/env python3
"""
Пороги грязи/места на реальных фото пачки 06 (300 слайдов, ручная разметка).
Данные: tests/data/rules_validation_*.json — выход validate_rules.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import carousel_rules as cr  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
RUNS = sorted(DATA.glob("rules_validation_*.json"))


def _labels():
    out = {}
    for line in (DATA / "labels_06.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            k, m, p = line.split()
            out[k] = (m, p)
    return out


def _load(path):
    val = json.loads(path.read_text(encoding="utf-8"))
    sims = np.array(val["sims"], dtype=np.float64)
    groups: dict[str, list[tuple[int, str]]] = {}
    for j, name in enumerate(val["prompts"]):
        g, t = name.split("::", 1)
        groups.setdefault(g, []).append((j, t))
    keys = []
    for fn in val["files"]:
        _, c, s, _ = fn.split("_")
        keys.append(f"{int(c)}.{int(s)}")
    return val, sims, groups, keys


@pytest.mark.parametrize("path", RUNS, ids=[p.stem for p in RUNS])
def test_prompts_match_module(path):
    """Якоря в данных проверки = якоря, которыми пользуется фабрика."""
    _val, _s, groups, _k = _load(path)
    assert [t for _, t in groups["mess"][: len(cr.MESS_PROMPTS)]] == list(cr.MESS_PROMPTS)
    assert [t for _, t in groups["clean"][: len(cr.CLEAN_PROMPTS)]] == list(cr.CLEAN_PROMPTS)
    for place, prompts in cr.PLACE_PROMPTS.items():
        assert [t for _, t in groups[f"place_{place}"]] == list(prompts)


@pytest.mark.parametrize("path", RUNS, ids=[p.stem for p in RUNS])
def test_mess_detector_quality(path):
    val, sims, groups, keys = _load(path)
    cal = cr.calibration_for(val["backend"])
    labels = _labels()
    m_cols = [j for j, _ in groups["mess"][: len(cr.MESS_PROMPTS)]]
    c_cols = [j for j, _ in groups["clean"][: len(cr.CLEAN_PROMPTS)]]
    probs = np.array([
        cr.mess_probability(sims[i, m_cols].max(), sims[i, c_cols].max(), cal["mess_margin"])
        for i in range(len(keys))
    ])
    pred = probs >= cr.MESS_THRESHOLD
    y = np.array([labels[k][0] for k in keys])
    tp = int((pred & (y == "M")).sum())
    recall = tp / int((y == "M").sum())
    precision = tp / max(1, int((pred & (y != "B")).sum()))
    print(f"{val['backend']}: recall={recall:.2f} precision={precision:.2f}")
    assert recall >= 0.80
    assert precision >= 0.65
    # последние слайды: грязные финалы, которые проверяющая ругала, ловятся
    finals = ["3.6", "5.6", "6.6", "13.6"]
    if "siglip" in val["backend"]:
        finals += ["15.6", "4.6", "9.6"]  # разлитый кофе и грязные тарелки
    for k in finals:
        assert pred[keys.index(k)], f"грязный финал {k} не пойман"


@pytest.mark.parametrize("path", RUNS, ids=[p.stem for p in RUNS])
def test_kitchen_detector_quality(path):
    val, sims, groups, keys = _load(path)
    cal = cr.calibration_for(val["backend"])
    labels = _labels()
    places = list(cr.PLACE_PROMPTS)
    P = np.stack([sims[:, [j for j, _ in groups[f"place_{p}"]]].max(1) for p in places], 1)
    z = P / cal["place_temp"]
    z -= z.max(1, keepdims=True)
    pr = np.exp(z)
    pr /= pr.sum(1, keepdims=True)
    pred = np.array([
        places[a] if c >= cal["place_min_prob"] else "other"
        for a, c in zip(pr.argmax(1), pr.max(1))
    ])
    y = np.array([labels[k][1] for k in keys])
    k_pred, k_true = pred == "kitchen", y == "kitchen"
    precision = (k_pred & k_true).sum() / max(1, k_pred.sum())
    recall = (k_pred & k_true).sum() / max(1, k_true.sum())
    print(f"{val['backend']}: kitchen precision={precision:.2f} recall={recall:.2f}")
    assert precision >= 0.70 and recall >= 0.85
    # «история с 4 холодильниками» (карусель 1) — кухня видна минимум на 4 слайдах
    assert sum(pred[keys.index(f"1.{s}")] == "kitchen" for s in range(1, 7)) >= 4
