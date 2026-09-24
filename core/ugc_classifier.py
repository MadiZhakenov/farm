#!/usr/bin/env python3
"""
Обученный классификатор live (быт) vs stock (профи).

SigLIP embedding + LogisticRegression — как TasteClassifier.
Модель: data/ugc_live_model.pkl
Если модели нет — вызывающий код может fallback на zero-shot якоря.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from PIL import Image
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "data" / "ugc_live_model.pkl"

_LOCK = threading.Lock()
_CLF: UGCLiveClassifier | None = None


class UGCLiveClassifier:
    """P(live) ∈ [0,1] — выше = живее / меньше сток."""

    def __init__(self, model_path: Path | None = None) -> None:
        self.model_path = Path(model_path) if model_path else MODEL_PATH
        self._clf: LogisticRegression | None = None
        self._backend = ""
        self._dim = 0
        self._mtime: float | None = None
        self._n_live = 0
        self._n_stock = 0

    @property
    def is_trained(self) -> bool:
        self._reload_if_needed()
        return self._clf is not None

    def train(
        self,
        live_images: list[Image.Image],
        stock_images: list[Image.Image],
        *,
        model_path: Path | None = None,
    ) -> dict[str, Any]:
        if len(live_images) < 2 or len(stock_images) < 2:
            raise ValueError("нужно минимум 2 live и 2 stock")

        from core.taste_embedder import get_embedder

        embedder = get_embedder()
        backend = embedder.ensure()
        pos = embedder.embed_images(live_images)
        neg = embedder.embed_images(stock_images)
        x = np.vstack([pos, neg])
        y = np.array([1] * len(pos) + [0] * len(neg), dtype=np.int32)
        clf = LogisticRegression(
            C=1.0,
            max_iter=2000,
            solver="lbfgs",
            class_weight="balanced",
        )
        clf.fit(x, y)

        path = Path(model_path) if model_path else self.model_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": clf,
            "calibration": "logistic_predict_proba",
            "label_positive": "live",
            "label_negative": "stock",
            "embed_backend": backend,
            "embed_dim": int(x.shape[1]),
            "n_live": int(len(pos)),
            "n_stock": int(len(neg)),
            "trained_at": datetime.now().isoformat(timespec="seconds"),
        }
        joblib.dump(payload, path)

        with _LOCK:
            self.model_path = path
            self._clf = clf
            self._backend = backend
            self._dim = int(x.shape[1])
            self._n_live = int(len(pos))
            self._n_stock = int(len(neg))
            try:
                self._mtime = path.stat().st_mtime
            except OSError:
                self._mtime = None
        return payload

    def predict_live_score(self, image: Image.Image) -> float:
        scores = self.predict_live_scores([image])
        return scores[0] if scores else 0.5

    def predict_live_scores(self, images: list[Image.Image]) -> list[float]:
        self._reload_if_needed()
        if self._clf is None or not images:
            return [0.5] * len(images)

        from core.taste_embedder import get_embedder

        embedder = get_embedder()
        embedder.ensure(self._backend or None)
        if self._backend and embedder.backend_id != self._backend:
            raise RuntimeError(
                f"эмбеддер {embedder.backend_id} != обучения ({self._backend})"
            )
        vecs = embedder.embed_images(images)
        if self._dim and vecs.shape[1] != self._dim:
            raise RuntimeError(
                f"dim {vecs.shape[1]} != trained {self._dim}"
            )
        proba = self._clf.predict_proba(vecs)
        classes = list(self._clf.classes_)
        if 1 not in classes:
            return [0.5] * len(images)
        col = classes.index(1)
        return [float(v) for v in np.clip(proba[:, col], 0.0, 1.0)]

    def _reload_if_needed(self) -> None:
        path = self.model_path
        try:
            mtime = path.stat().st_mtime if path.is_file() else None
        except OSError:
            mtime = None
        with _LOCK:
            if mtime == self._mtime and (self._clf is not None or mtime is None):
                return
            self._mtime = mtime
            self._clf = None
            self._backend = ""
            self._dim = 0
            if mtime is None:
                return
            payload = joblib.load(path)
            model = payload.get("model") if isinstance(payload, dict) else payload
            if not hasattr(model, "predict_proba"):
                return
            self._clf = model
            if isinstance(payload, dict):
                self._backend = str(payload.get("embed_backend") or "")
                self._dim = int(payload.get("embed_dim") or 0)
                self._n_live = int(payload.get("n_live") or 0)
                self._n_stock = int(payload.get("n_stock") or 0)


def get_ugc_live_classifier() -> UGCLiveClassifier:
    global _CLF
    with _LOCK:
        if _CLF is None:
            _CLF = UGCLiveClassifier()
        return _CLF
