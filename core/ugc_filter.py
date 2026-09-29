#!/usr/bin/env python3
"""
Анти-сток фильтр (Zero-Shot Polarization) на локальном SigLIP/CLIP.

Сравнивает эмбеддинг картинки с несколькими UGC vs Stock якорями +
эвристика studio/pro (белый фон, airbrush, bokeh).

Без API. Текстовые якоря предвычисляются один раз при старте.
"""
from __future__ import annotations

import math
import threading
from typing import Sequence

import numpy as np
from PIL import Image

UGC_ANCHORS: tuple[str, ...] = (
    (
        "flat mobile phone camera, deep depth of field, sharp background without bokeh, "
        "zero blur in background, casual wide angle iphone snapshot, grainy mobile sensor, "
        "unedited authentic reality"
    ),
    (
        "messy real life candid photo, imperfect framing, natural window light, "
        "lived-in room, phone snapshot no filter"
    ),
    (
        "grainy night kitchen photo, handheld phone, harsh flash or dim lamp, "
        "authentic domestic chaos"
    ),
)

STOCK_ANCHORS: tuple[str, ...] = (
    (
        "DSLR shallow depth of field, creamy bokeh blur, heavily blurred background, "
        "telephoto portrait lens, professional macro lens, smooth airbrushed skin, "
        "glossy polished commercial photography, studio lighting"
    ),
    (
        "studio product photography on white seamless background, pack shot, "
        "catalog ecommerce listing, brand packaging hero shot"
    ),
    (
        "Shutterstock Getty Images commercial stock photo, posed model, "
        "perfect lighting, retouched skin, advertising campaign"
    ),
    (
        "3D render CGI unreal engine glossy, digital art illustration, "
        "AI generated image midjourney"
    ),
    (
        "organized pantry aesthetic, meal prep containers flat lay, "
        "influencer wellness fridge restock"
    ),
)

# Softmax temperature (как у CLIP/SigLIP logit scale ≈ 1/0.07)
SOFTMAX_TEMP = 0.07
# Жёсткий порог: ближе к стоку / рендеру → отсев
UGC_MIN_SCORE = 0.55  # sync с harvester.UGC_HARD_FLOOR
# Soft-pass при всех ugc < UGC_MIN_SCORE ЗАПРЕЩЁН (см. harvester._apply_ugc_gate)
UGC_SOFT_PASS = False
# Сигнатура якорей — при смене текста пересчитываем эмбеддинги
_ANCHOR_SIG = hash((UGC_ANCHORS, STOCK_ANCHORS))

_LOCK = threading.Lock()
_FILTER: UGCFilter | None = None


def _softmax2(a: float, b: float, temp: float = SOFTMAX_TEMP) -> float:
    """P(a) = exp(a/T) / (exp(a/T) + exp(b/T)), численно стабильно."""
    t = max(1e-6, float(temp))
    m = max(a / t, b / t)
    ea = math.exp(a / t - m)
    eb = math.exp(b / t - m)
    denom = ea + eb
    if denom <= 0.0:
        return 0.5
    return float(ea / denom)


def stock_pro_heuristic_penalty(image: Image.Image) -> float:
    """
    0..0.40 penalty subtracted from UGC score for studio/pro tells:
      - bright near-white corners (seamless studio)
      - ultra-smooth airbrushed look (low edge energy)
      - extreme center-sharp / edge-blur (portrait bokeh)
    """
    try:
        im = image.convert("RGB")
        w, h = im.size
        if w < 32 or h < 32:
            return 0.0
        small = im.resize((96, 96), Image.Resampling.BILINEAR)
        arr = np.asarray(small, dtype=np.float32)
        gray = arr.mean(axis=2)

        c = 12
        corners = np.concatenate(
            [
                gray[:c, :c].ravel(),
                gray[:c, -c:].ravel(),
                gray[-c:, :c].ravel(),
                gray[-c:, -c:].ravel(),
            ]
        )
        corner_mean = float(corners.mean())
        corner_std = float(corners.std())
        pen = 0.0
        if corner_mean > 220 and corner_std < 28:
            pen += 0.22
        elif corner_mean > 200 and corner_std < 35:
            pen += 0.12

        gy, gx = np.gradient(gray)
        edge = float(np.mean(np.abs(gx) + np.abs(gy)))
        if edge < 4.5:
            pen += 0.12
        elif edge < 7.0:
            pen += 0.06

        center = gray[32:64, 32:64]
        c_edge = float(np.mean(np.abs(np.gradient(center)[0])) + 1e-3)
        b_e2 = float(
            np.mean(np.abs(np.gradient(gray[:16, :])[0]))
            + np.mean(np.abs(np.gradient(gray[-16:, :])[0]))
            + 1e-3
        )
        ratio = c_edge / max(b_e2, 1e-3)
        if ratio > 3.5 and b_e2 < 6.0:
            pen += 0.10

        return float(min(0.40, pen))
    except Exception:
        return 0.0


class UGCFilter:
    """Zero-shot полярность UGC ↔ Stock на эмбеддингах SigLIP/CLIP."""

    def __init__(self) -> None:
        self._ugc_vecs: np.ndarray | None = None
        self._stock_vecs: np.ndarray | None = None
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
        """Предвычислить текстовые якоря (один раз / при смене якорей)."""
        if self.ready:
            return
        with _LOCK:
            if self.ready:
                return
            from core.taste_embedder import get_embedder

            emb = get_embedder()
            emb.ensure()
            texts = list(UGC_ANCHORS) + list(STOCK_ANCHORS)
            vecs = emb.embed_texts(texts)
            n_u = len(UGC_ANCHORS)
            if vecs.shape[0] < n_u + 1:
                raise RuntimeError("UGCFilter: не удалось получить текстовые эмбеддинги")
            self._ugc_vecs = np.asarray(vecs[:n_u], dtype=np.float32)
            self._stock_vecs = np.asarray(vecs[n_u:], dtype=np.float32)
            ug = self._ugc_vecs.mean(axis=0)
            st = self._stock_vecs.mean(axis=0)
            self._ugc_vec = ug / (float(np.linalg.norm(ug)) + 1e-8)
            self._stock_vec = st / (float(np.linalg.norm(st)) + 1e-8)
            self.backend_id = emb.backend_id
            self._anchor_sig = _ANCHOR_SIG
            self._ready = True

    def get_ugc_score(self, image: Image.Image) -> float:
        """Индекс аутентичности 0..1 (1 = живое мобильное UGC)."""
        scores = self.get_ugc_scores([image])
        return float(scores[0]) if len(scores) else 0.5

    def get_ugc_scores(self, images: Sequence[Image.Image]) -> np.ndarray:
        """Пакетный UGC-скор, shape (N,). Предпочитает обученную голову."""
        if not images:
            return np.zeros((0,), dtype=np.float32)

        supervised: np.ndarray | None = None
        try:
            from core.ugc_classifier import get_ugc_live_classifier

            clf = get_ugc_live_classifier()
            if clf.is_trained:
                supervised = np.asarray(
                    clf.predict_live_scores(list(images)), dtype=np.float32
                )
        except Exception:
            supervised = None

        self.ensure()
        assert self._ugc_vecs is not None and self._stock_vecs is not None

        from core.taste_embedder import get_embedder

        img_vecs = get_embedder().embed_images(list(images))
        sim_ugc = img_vecs @ self._ugc_vecs.T
        sim_stock = img_vecs @ self._stock_vecs.T
        best_ugc = sim_ugc.max(axis=1)
        best_stock = sim_stock.max(axis=1)
        out = np.empty((len(images),), dtype=np.float32)
        for i in range(len(images)):
            zs = _softmax2(float(best_ugc[i]), float(best_stock[i]), SOFTMAX_TEMP)
            pen = stock_pro_heuristic_penalty(images[i])
            zs = max(0.0, zs - pen)
            if supervised is not None:
                out[i] = float(0.55 * supervised[i] + 0.45 * zs)
            else:
                out[i] = float(zs)
        return out


def get_ugc_filter() -> UGCFilter:
    global _FILTER
    with _LOCK:
        if _FILTER is None or (
            _FILTER is not None and getattr(_FILTER, "_anchor_sig", None) != _ANCHOR_SIG
        ):
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
    Итоговый ранг — те же веса, что harvest candidate_final_score:
      live: rel×0.35 + taste×0.15 + ugc×0.50
    Veto floor taste≥0.40 применяется в harvester.judge, не здесь.
    """
    del harmony
    from core.harvester import FINAL_REL_W, FINAL_TASTE_W, FINAL_UGC_W

    u = max(0.0, min(1.0, float(ugc)))
    t = max(0.0, min(1.0, float(taste if taste is not None else 0.5)))
    if relevance is not None:
        r = max(0.0, min(1.0, float(relevance)))
        return round(r * FINAL_REL_W + t * FINAL_TASTE_W + u * FINAL_UGC_W, 4)
    tw = FINAL_TASTE_W
    uw = FINAL_UGC_W
    s = tw + uw
    if s <= 0:
        return round(u, 4)
    return round(u * (uw / s) + t * (tw / s), 4)
