#!/usr/bin/env python3
"""
Анти-сток фильтр (Zero-Shot Polarization) на локальном SigLIP/CLIP.

Не одна оценка: несколько независимых сигналов + VETO.
Сток проходит только если ВСЕ «живые» головы согласны; любая жёсткая
сток-голова обнуляет скор ниже harvester floors.

Сигналы:
  1) supervised LogReg P(live) — data/ugc_live_model.pkl
  2) zero-shot якоря UGC↔Stock (softmax best-match)
  3) margin = cos_ugc − cos_stock
  4) studio/pro эвристика (белый фон, airbrush, bokeh)

Без API. Текстовые якоря предвычисляются один раз при старте.
"""
from __future__ import annotations

import math
import threading
from typing import Any, Sequence

import numpy as np
from PIL import Image

UGC_ANCHORS: tuple[str, ...] = (
    (
        "flat mobile phone camera, deep depth of field, sharp background without bokeh, "
        "zero blur in background, casual wide angle iphone snapshot, grainy mobile sensor, "
        "unedited authentic reality"
    ),
    (
        "real life candid photo, imperfect framing, natural window light, "
        "everyday room, phone snapshot no filter"
    ),
    (
        "grainy night photo at home, handheld phone, harsh flash or dim lamp, "
        "authentic everyday moment"
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
    (
        "lifestyle magazine editorial, color graded cinematic food photography, "
        "pro propped scene, perfect composition stock"
    ),
)

# Softmax temperature (как у CLIP/SigLIP logit scale ≈ 1/0.07)
SOFTMAX_TEMP = 0.07
# Жёсткий порог: ближе к стоку / рендеру → отсев
UGC_MIN_SCORE = 0.55  # sync с harvester.UGC_HARD_FLOOR
# Soft-pass при всех ugc < UGC_MIN_SCORE ЗАПРЕЩЁН (см. harvester._apply_ugc_gate)
UGC_SOFT_PASS = False

# --- Multi-signal stock veto (не усреднение «одной цифры») ---
# Любой триггер → score forced below COMPLETION_UGC_FLOOR (0.48) и HARD (0.55).
STOCK_VETO_ENABLED = True
STOCK_VETO_SCORE = 0.30
STOCK_VETO_SUP_MAX = 0.42  # LogReg thinks stock
STOCK_VETO_ZS_MAX = 0.38  # zero-shot thinks stock
STOCK_VETO_MARGIN_MAX = -0.012  # stock cosine closer than ugc
STOCK_VETO_PEN_MIN = 0.18  # studio heuristic
# Agreement: final live score cannot exceed the weaker of the two heads
STOCK_AGREE_MIN = True  # score = min(sup, zs−pen)
# Hard veto only when >=2 stock heads agree (cuts false kills on live UGC)
STOCK_VETO_MIN_HITS = 2
# Итог = обученная модель живости. Zero-shot, эвристики и вето её только портили:
# на ручной разметке 2026-10-05 (205 кадров) AUC 0.88 против 0.79 у «худшего из
# двух + вето»; при пороге 0.55 доля живых среди прошедших 74% против 67%, найдено
# живых 69% против 28%. Без модели (нет файла, сломалась загрузка) оценка
# падает с LivenessModelError, а не тихо уходит на zero-shot (AUC 0.53).
MODEL_ONLY = True


class LivenessModelError(RuntimeError):
    """Модель живости недоступна при MODEL_ONLY — собирать карусели нельзя."""

# Сигнатура якорей — при смене текста пересчитываем эмбеддинги
_ANCHOR_SIG = hash(
    (
        UGC_ANCHORS,
        STOCK_ANCHORS,
        STOCK_VETO_ENABLED,
        STOCK_AGREE_MIN,
        STOCK_VETO_MIN_HITS,
        MODEL_ONLY,
    )
)

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
    0..0.45 penalty for studio/pro tells:
      - bright near-white corners (seamless studio)
      - ultra-smooth airbrushed look (low edge energy)
      - extreme center-sharp / edge-blur (portrait bokeh)
      - oversaturated 'magazine' chroma (common stock grade)
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
            pen += 0.14
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

        # Magazine grade: high chroma + low noise → stock lifestyle
        chroma = float(np.mean(np.std(arr, axis=2)))
        noise = float(np.std(gray - np.mean(gray)))
        if chroma > 38.0 and noise < 28.0 and edge < 9.0:
            pen += 0.08

        return float(min(0.45, pen))
    except Exception:
        return 0.0


def _combine_signals(
    *,
    supervised: float | None,
    zero_shot: float,
    margin: float,
    penalty: float,
) -> tuple[float, list[str]]:
    """
    Multi-head combine + stock veto.
    Returns (score 0..1, list of veto reasons).
    """
    reasons: list[str] = []
    if supervised is not None and MODEL_ONLY:
        return float(min(1.0, max(0.0, float(supervised)))), reasons
    zs = max(0.0, float(zero_shot) - float(penalty))
    if supervised is None:
        score = zs
    elif STOCK_AGREE_MIN:
        # Weaker head wins — stock can't hide behind one optimistic score
        score = max(0.0, min(float(supervised), zs))
    else:
        score = float(0.55 * float(supervised) + 0.45 * zs)

    if not STOCK_VETO_ENABLED:
        return float(min(1.0, score)), reasons

    if supervised is not None and float(supervised) < STOCK_VETO_SUP_MAX:
        reasons.append(f"sup<{STOCK_VETO_SUP_MAX:.2f}")
    if float(zero_shot) < STOCK_VETO_ZS_MAX:
        reasons.append(f"zs<{STOCK_VETO_ZS_MAX:.2f}")
    if float(margin) < STOCK_VETO_MARGIN_MAX:
        reasons.append(f"margin<{STOCK_VETO_MARGIN_MAX:.3f}")
    if float(penalty) >= STOCK_VETO_PEN_MIN:
        reasons.append(f"pen>={STOCK_VETO_PEN_MIN:.2f}")

    # Need concordant stock heads — one flaky signal alone shouldn't nuke live UGC
    if len(reasons) >= int(STOCK_VETO_MIN_HITS):
        score = min(score, STOCK_VETO_SCORE)
    else:
        reasons = []
    return float(min(1.0, max(0.0, score))), reasons


class UGCFilter:
    """Multi-signal UGC ↔ Stock на эмбеддингах SigLIP/CLIP."""

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

    def get_ugc_scores(
        self,
        images: Sequence[Image.Image],
        *,
        cache_keys: list[str | None] | None = None,
        image_vecs: np.ndarray | None = None,
    ) -> np.ndarray:
        """Пакетный UGC-скор, shape (N,). Один SigLIP-проход на картинку."""
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
        """Per-image multi-signal breakdown (for tests / debugging)."""
        if not images and image_vecs is None:
            return []

        from core.taste_embedder import get_embedder

        embedder = get_embedder()
        if image_vecs is None:
            img_vecs = embedder.embed_images(list(images), cache_keys=cache_keys)
        else:
            img_vecs = np.asarray(image_vecs, dtype=np.float32)

        supervised: np.ndarray | None = None
        try:
            from core.ugc_classifier import get_ugc_live_classifier

            clf = get_ugc_live_classifier()
            if clf.is_trained:
                supervised = np.asarray(
                    clf.predict_live_scores_from_vecs(img_vecs),
                    dtype=np.float32,
                )
        except Exception as exc:
            if MODEL_ONLY:
                raise LivenessModelError(f"модель живости не сработала: {exc}") from exc
            supervised = None
        if supervised is None and MODEL_ONLY:
            raise LivenessModelError("модель живости не загружена (data/ugc_live_model.pkl)")

        self.ensure()
        assert self._ugc_vecs is not None and self._stock_vecs is not None

        sim_ugc = img_vecs @ self._ugc_vecs.T
        sim_stock = img_vecs @ self._stock_vecs.T
        best_ugc = sim_ugc.max(axis=1)
        best_stock = sim_stock.max(axis=1)
        n = len(img_vecs)
        imgs = list(images) if images else [None] * n
        out: list[dict[str, Any]] = []
        for i in range(n):
            zs_raw = _softmax2(float(best_ugc[i]), float(best_stock[i]), SOFTMAX_TEMP)
            pen = 0.0
            if imgs[i] is not None:
                pen = stock_pro_heuristic_penalty(imgs[i])
            margin = float(best_ugc[i] - best_stock[i])
            sup = float(supervised[i]) if supervised is not None else None
            score, reasons = _combine_signals(
                supervised=sup,
                zero_shot=zs_raw,
                margin=margin,
                penalty=pen,
            )
            out.append(
                {
                    "score": score,
                    "supervised": sup,
                    "zero_shot": float(zs_raw),
                    "margin": margin,
                    "penalty": float(pen),
                    "veto": reasons,
                    "vetoed": bool(reasons),
                }
            )
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
    aesthetic: float | None = None,
) -> float:
    """
    Итоговый ранг — те же веса, что harvest candidate_final_score.
    """
    del harmony
    from core.harvester import candidate_final_score

    return candidate_final_score(
        0.5 if relevance is None else float(relevance),
        float(ugc),
        100.0,
        taste=taste,
        aesthetic=aesthetic,
    )
