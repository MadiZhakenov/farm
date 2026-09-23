#!/usr/bin/env python3
"""
Классификатор личного визуального вкуса.

Эмбеддинги SigLIP/CLIP + LogisticRegression(C=1.0).
Вероятность класса «ДА» — это и есть калибровка (predict_proba),
она сохраняется вместе с моделью в data/my_taste_model.pkl.
Без API.
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
MODEL_PATH = ROOT / "data" / "my_taste_model.pkl"
TASTE_MIN_SCORE = 0.60

_LOCK = threading.Lock()
_CLASSIFIER: TasteClassifier | None = None


class TasteClassifier:
    def __init__(self, model_path: Path | None = None) -> None:
        self.model_path = Path(model_path) if model_path else MODEL_PATH
        self._clf: LogisticRegression | None = None
        self._backend = ""
        self._dim = 0
        self._mtime: float | None = None
        self._n_positive = 0
        self._n_negative = 0

    @property
    def is_trained(self) -> bool:
        self._reload_if_needed()
        return self._clf is not None

    def train(
        self,
        positive_images: list[Image.Image],
        negative_images: list[Image.Image],
        *,
        model_path: Path | None = None,
    ) -> dict[str, Any]:
        """Учит фильтр на ДА/НЕТ и сохраняет модель с вероятностной калибровкой."""
        if len(positive_images) < 2 or len(negative_images) < 2:
            raise ValueError("нужно минимум 2 фото «ДА» и 2 фото «НЕТ»")

        from core.taste_embedder import get_embedder

        embedder = get_embedder()
        backend = embedder.ensure()
        pos = embedder.embed_images(positive_images)
        neg = embedder.embed_images(negative_images)
        if pos.shape[1] != neg.shape[1]:
            raise RuntimeError("разная размерность эмбеддингов ДА и НЕТ")

        x = np.vstack([pos, neg])
        y = np.array([1] * len(pos) + [0] * len(neg), dtype=np.int32)
        clf = LogisticRegression(
            C=1.0,
            max_iter=1000,
            solver="lbfgs",
            class_weight="balanced",
        )
        clf.fit(x, y)

        path = Path(model_path) if model_path else self.model_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": clf,
            "calibration": "logistic_predict_proba",
            "threshold": TASTE_MIN_SCORE,
            "embed_backend": backend,
            "embed_dim": int(x.shape[1]),
            "n_positive": int(len(pos)),
            "n_negative": int(len(neg)),
            "trained_at": datetime.now().isoformat(timespec="seconds"),
        }
        joblib.dump(payload, path)

        with _LOCK:
            self.model_path = path
            self._clf = clf
            self._backend = backend
            self._dim = int(x.shape[1])
            self._n_positive = int(len(pos))
            self._n_negative = int(len(neg))
            try:
                self._mtime = path.stat().st_mtime
            except OSError:
                self._mtime = None
        return payload

    def predict_taste_score(self, image: Image.Image) -> float:
        """Вероятность класса «ДА» от 0 до 1. Без модели — 0.5."""
        scores = self.predict_taste_scores([image])
        return scores[0] if scores else 0.5

    def predict_taste_scores(self, images: list[Image.Image]) -> list[float]:
        self._reload_if_needed()
        if self._clf is None or not images:
            return [0.5] * len(images)

        from core.taste_embedder import get_embedder

        embedder = get_embedder()
        embedder.ensure(self._backend or None)
        if self._backend and embedder.backend_id != self._backend:
            raise RuntimeError(
                f"эмбеддер {embedder.backend_id} не совпадает с обучением ({self._backend})"
            )
        vecs = embedder.embed_images(images)
        if self._dim and vecs.shape[1] != self._dim:
            raise RuntimeError(
                f"размерность {vecs.shape[1]} != обученной {self._dim}"
            )
        proba = self._clf.predict_proba(vecs)
        classes = list(self._clf.classes_)
        if 1 not in classes:
            return [0.5] * len(images)
        col = classes.index(1)
        out = np.clip(proba[:, col], 0.0, 1.0)
        return [float(v) for v in out]

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
                self._n_positive = int(payload.get("n_positive") or 0)
                self._n_negative = int(payload.get("n_negative") or 0)


def get_taste_classifier() -> TasteClassifier:
    global _CLASSIFIER
    with _LOCK:
        if _CLASSIFIER is None:
            _CLASSIFIER = TasteClassifier()
        return _CLASSIFIER
