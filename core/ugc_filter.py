#!/usr/bin/env python3
"""
Анти-сток фильтр (Zero-Shot Polarization) на локальном SigLIP/CLIP.

Сравнивает эмбеддинг картинки с двумя текстовыми антиподами:
  UGC (живой iPhone) vs Stock (студия / Shutterstock / 3D).

Без API. Текстовые якоря предвычисляются один раз при старте.
"""

from __future__ import annotations

import math
import threading
from typing import Sequence

import numpy as np
from PIL import Image

UGC_ANCHOR = (
    "flat mobile phone camera, deep depth of field, sharp background without bokeh, "
    "zero blur in background, casual wide angle iphone snapshot, grainy mobile sensor, "
    "unedited authentic reality"
)
STOCK_ANCHOR = (
    "DSLR shallow depth of field, creamy bokeh blur, heavily blurred background, "
    "telephoto portrait lens, professional macro lens, smooth airbrushed skin, "
    "glossy polished commercial photography, studio lighting"
)

# Softmax temperature (как у CLIP/SigLIP logit scale ≈ 1/0.07)
SOFTMAX_TEMP = 0.07
# Жёсткий порог: ближе к стоку / рендеру → отсев
UGC_MIN_SCORE = 0.35  # sync с harvester.UGC_HARD_FLOOR
# Soft-pass при всех ugc < UGC_MIN_SCORE ЗАПРЕЩЁН (см. harvester._apply_ugc_gate)
UGC_SOFT_PASS = False
# Сигнатура якорей — при смене текста пересчитываем эмбеддинги
_ANCHOR_SIG = hash((UGC_ANCHOR, STOCK_ANCHOR))

_LOCK = threading.Lock()
_FILTER: UGCFilter | None = None


def _softmax2(a: float, b: float, temp: float = SOFTMAX_TEMP) -> float:
    """P(a) = exp(a/T) / (exp(a/T) + exp(b/T)), численно стабильно."""
    t = max(1e-6, float(temp))
    # вычитаем max, чтобы не взорвать exp
    m = max(a / t, b / t)
    ea = math.exp(a / t - m)
    eb = math.exp(b / t - m)
    denom = ea + eb
    if denom <= 0.0:
        return 0.5
    return float(ea / denom)


class UGCFilter:
    """Zero-shot полярность UGC ↔ Stock на эмбеддингах SigLIP/CLIP."""

    def __init__(self) -> None:
        self._ugc_vec: np.ndarray | None = None
        self._stock_vec: np.ndarray | None = None
        self._ready = False
        self._anchor_sig: int | None = None
        self.backend_id = ""

    @property
    def ready(self) -> bool:
        return (
            self._ready
            and self._ugc_vec is not None
            and self._stock_vec is not None
            and self._anchor_sig == _ANCHOR_SIG
        )

    def ensure(self) -> None:
        """Предвычислить текстовые якоря (один раз / при смене UGC/STOCK_ANCHOR)."""
        if self.ready:
            return
        with _LOCK:
            if self.ready:
                return
            from core.taste_embedder import get_embedder

            emb = get_embedder()
            emb.ensure()
            vecs = emb.embed_texts([UGC_ANCHOR, STOCK_ANCHOR])
            if vecs.shape[0] < 2:
                raise RuntimeError("UGCFilter: не удалось получить текстовые эмбеддинги")
            self._ugc_vec = np.asarray(vecs[0], dtype=np.float32)
            self._stock_vec = np.asarray(vecs[1], dtype=np.float32)
            self.backend_id = emb.backend_id
            self._anchor_sig = _ANCHOR_SIG
            self._ready = True

    def get_ugc_score(self, image: Image.Image) -> float:
        """Индекс аутентичности 0..1 (1 = живое мобильное UGC)."""
        scores = self.get_ugc_scores([image])
        return float(scores[0]) if len(scores) else 0.5

    def get_ugc_scores(self, images: Sequence[Image.Image]) -> np.ndarray:
        """Пакетный UGC-скор, shape (N,)."""
        if not images:
            return np.zeros((0,), dtype=np.float32)
        self.ensure()
        assert self._ugc_vec is not None and self._stock_vec is not None

        from core.taste_embedder import get_embedder

        img_vecs = get_embedder().embed_images(list(images))
        # косинус = dot при L2-норме
        sim_ugc = img_vecs @ self._ugc_vec
        sim_stock = img_vecs @ self._stock_vec
        out = np.empty((len(images),), dtype=np.float32)
        for i in range(len(images)):
            out[i] = _softmax2(float(sim_ugc[i]), float(sim_stock[i]), SOFTMAX_TEMP)
        return out


def get_ugc_filter() -> UGCFilter:
    global _FILTER
    with _LOCK:
        if _FILTER is None:
            _FILTER = UGCFilter()
        return _FILTER


def final_rank_score(
    ugc: float,
    taste: float = 0.5,
    harmony: float = 100.0,
    *,
    relevance: float | None = None,
) -> float:
    """
    Итоговый ранг:
      relevance×0.40 + taste×0.35 + ugc×0.25
    (harmony в сигнатуре для совместимости, вес 0).

    Если relevance не передан — legacy ugc×0.45 + taste×0.35.
    """
    del harmony
    u = max(0.0, min(1.0, float(ugc)))
    t = max(0.0, min(1.0, float(taste if taste is not None else 0.5)))
    if relevance is not None:
        r = max(0.0, min(1.0, float(relevance)))
        return round(r * 0.40 + t * 0.35 + u * 0.25, 4)
    return round(u * 0.45 + t * 0.35, 4)
