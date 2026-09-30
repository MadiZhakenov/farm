#!/usr/bin/env python3
"""
Отдельная оценка привлекательности / качества кадра (не UGC и не personal taste).

Сигналы:
  1) Zero-shot SigLIP: «красиво снято / хорошая композиция» vs «мыло / криво / уродливо»
  2) Техкачество: резкость, экспозиция, контраст (без второй нейросети)

Использует тот же SigLIP + pin-cache — лишнего GPU-forward нет, если vec уже есть.
"""
from __future__ import annotations

import math
import threading
from typing import Any, Sequence

import numpy as np
from PIL import Image

GOOD_ANCHORS: tuple[str, ...] = (
    (
        "beautiful well composed photograph, pleasing lighting, sharp subject, "
        "attractive candid phone photo, good framing"
    ),
    (
        "aesthetically pleasing everyday photo, balanced composition, "
        "natural light, visually appealing mood"
    ),
    (
        "high quality smartphone photo, clear focus, nice color, "
        "interesting framing, pretty scene"
    ),
)

BAD_ANCHORS: tuple[str, ...] = (
    (
        "ugly poorly shot photo, blurry out of focus, bad lighting, "
        "unattractive composition, accidental snapshot"
    ),
    (
        "low quality grainy dark underexposed photo, motion blur, "
        "crooked framing, boring empty frame"
    ),
    (
        "overexposed washed out photo, noise, muddy colors, "
        "badly cropped, unappealing image"
    ),
)

SOFTMAX_TEMP = 0.07
# Blend: semantic beauty + technical craft
ZS_W = 0.55
TECH_W = 0.45

_ANCHOR_SIG = hash((GOOD_ANCHORS, BAD_ANCHORS, ZS_W, TECH_W))
_LOCK = threading.Lock()
_FILTER: AestheticFilter | None = None


def _softmax2(a: float, b: float, temp: float = SOFTMAX_TEMP) -> float:
    t = max(1e-6, float(temp))
    m = max(a / t, b / t)
    ea = math.exp(a / t - m)
    eb = math.exp(b / t - m)
    denom = ea + eb
    if denom <= 0.0:
        return 0.5
    return float(ea / denom)


def technical_quality_score(image: Image.Image) -> float:
    """
    0..1 craft score from pixels only.
    Penalizes blur, crushed/blown exposure, dead flat contrast, extreme noise.
    """
    try:
        im = image.convert("RGB")
        w, h = im.size
        if w < 32 or h < 32:
            return 0.25
        small = im.resize((128, 128), Image.Resampling.BILINEAR)
        arr = np.asarray(small, dtype=np.float32)
        gray = arr.mean(axis=2)

        # Sharpness via Laplacian variance
        lap = (
            -4.0 * gray
            + np.roll(gray, 1, 0)
            + np.roll(gray, -1, 0)
            + np.roll(gray, 1, 1)
            + np.roll(gray, -1, 1)
        )
        sharp = float(lap.var())
        # Typical phone: 30–400; mushy < 12
        sharp_s = max(0.0, min(1.0, (sharp - 8.0) / 120.0))

        mean = float(gray.mean())
        std = float(gray.std())
        # Mid exposure preferred; crushed dark / blown white hurt
        if mean < 35:
            exp_s = mean / 35.0 * 0.55
        elif mean > 220:
            exp_s = max(0.0, (255.0 - mean) / 35.0) * 0.55
        else:
            exp_s = 0.55 + 0.45 * (1.0 - abs(mean - 125.0) / 125.0)

        # Contrast: too flat = boring/bad
        contrast_s = max(0.0, min(1.0, (std - 12.0) / 55.0))

        # Highlight/shadow clipping
        clip_hi = float((gray > 248).mean())
        clip_lo = float((gray < 8).mean())
        clip_pen = min(0.35, clip_hi * 0.8 + clip_lo * 0.8)

        # Color presence (not muddy gray sludge) — soft
        chroma = float(np.mean(np.std(arr, axis=2)))
        chroma_s = max(0.0, min(1.0, chroma / 35.0))

        score = (
            0.40 * sharp_s
            + 0.25 * exp_s
            + 0.20 * contrast_s
            + 0.15 * chroma_s
            - clip_pen
        )
        return float(max(0.0, min(1.0, score)))
    except Exception:
        return 0.5


class AestheticFilter:
    """Attractiveness / craft — separate from UGC-live and personal taste."""

    def __init__(self) -> None:
        self._good: np.ndarray | None = None
        self._bad: np.ndarray | None = None
        self._ready = False
        self._anchor_sig: int | None = None
        self.backend_id = ""

    @property
    def ready(self) -> bool:
        return (
            self._ready
            and self._good is not None
            and self._bad is not None
            and self._anchor_sig == _ANCHOR_SIG
        )

    def ensure(self) -> None:
        if self.ready:
            return
        with _LOCK:
            if self.ready:
                return
            from core.taste_embedder import get_embedder

            emb = get_embedder()
            emb.ensure()
            texts = list(GOOD_ANCHORS) + list(BAD_ANCHORS)
            vecs = emb.embed_texts(texts)
            n_g = len(GOOD_ANCHORS)
            if vecs.shape[0] < n_g + 1:
                raise RuntimeError("AestheticFilter: no text embeddings")
            self._good = np.asarray(vecs[:n_g], dtype=np.float32)
            self._bad = np.asarray(vecs[n_g:], dtype=np.float32)
            self.backend_id = emb.backend_id
            self._anchor_sig = _ANCHOR_SIG
            self._ready = True

    def get_aesthetic_scores(
        self,
        images: Sequence[Image.Image],
        *,
        cache_keys: list[str | None] | None = None,
        image_vecs: np.ndarray | None = None,
    ) -> np.ndarray:
        details = self.score_details(
            images, cache_keys=cache_keys, image_vecs=image_vecs
        )
        if not details:
            return np.zeros((0,), dtype=np.float32)
        return np.asarray([d["score"] for d in details], dtype=np.float32)

    def score_details(
        self,
        images: Sequence[Image.Image],
        *,
        cache_keys: list[str | None] | None = None,
        image_vecs: np.ndarray | None = None,
    ) -> list[dict[str, Any]]:
        if not images and image_vecs is None:
            return []

        from core.taste_embedder import get_embedder

        embedder = get_embedder()
        if image_vecs is None:
            img_vecs = embedder.embed_images(list(images), cache_keys=cache_keys)
        else:
            img_vecs = np.asarray(image_vecs, dtype=np.float32)

        self.ensure()
        assert self._good is not None and self._bad is not None

        sim_g = img_vecs @ self._good.T
        sim_b = img_vecs @ self._bad.T
        best_g = sim_g.max(axis=1)
        best_b = sim_b.max(axis=1)
        imgs = list(images) if images else [None] * len(img_vecs)
        out: list[dict[str, Any]] = []
        for i in range(len(img_vecs)):
            zs = _softmax2(float(best_g[i]), float(best_b[i]), SOFTMAX_TEMP)
            tech = (
                technical_quality_score(imgs[i])
                if imgs[i] is not None
                else 0.5
            )
            score = float(ZS_W * zs + TECH_W * tech)
            out.append(
                {
                    "score": max(0.0, min(1.0, score)),
                    "zero_shot": float(zs),
                    "technical": float(tech),
                }
            )
        return out


def get_aesthetic_filter() -> AestheticFilter:
    global _FILTER
    with _LOCK:
        if _FILTER is None or (
            _FILTER is not None
            and getattr(_FILTER, "_anchor_sig", None) != _ANCHOR_SIG
        ):
            _FILTER = AestheticFilter()
        return _FILTER
