#!/usr/bin/env python3
"""
Локальный RAG по viral_playbook (fastembed ONNX, $0, CPU).

Индекс: data/playbook_vectors.npz
Сборка: python index_viral_playbook.py
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "reelfarm_database.db"
DEFAULT_INDEX = ROOT / "data" / "playbook_vectors.npz"
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_TOP_K = 3

_EMBEDDER = None
_EMBEDDER_LOCK = threading.Lock()
# Fix forward ref: PlaybookRetriever used before class body finishes for singleton
_RETRIEVER = None  # type: ignore[var-annotated]
_RETRIEVER_LOCK = threading.Lock()


@dataclass
class RetrievedExample:
    id: str
    niche: str
    title: str
    hook: str
    slides: list[str]
    save_rate: float
    bookmarks: int
    score: float
    similarity: float


def _get_embedder(model_name: str = DEFAULT_MODEL):
    global _EMBEDDER
    with _EMBEDDER_LOCK:
        if _EMBEDDER is None:
            from fastembed import TextEmbedding

            logger.info("Loading FastEmbed model %s …", model_name)
            _EMBEDDER = TextEmbedding(model_name=model_name)
        return _EMBEDDER


def embed_texts(texts: list[str], model_name: str = DEFAULT_MODEL) -> np.ndarray:
    """Batch embed → L2-normalized float32 matrix (N, D)."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    model = _get_embedder(model_name)
    vectors = list(model.embed(texts))
    mat = np.asarray(vectors, dtype=np.float32)
    # bge usually returns normalized; ensure anyway
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return mat / norms


def build_index_doc(niche: str, hook: str, title: str) -> str:
    return f"Niche: {niche or 'general'}. Hook: {hook}. Title: {title or ''}"


def cosine_sim_matrix(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """query (D,) or (1,D), matrix (N,D) — both L2-normalized → cosine = dot."""
    q = query.reshape(-1).astype(np.float32)
    return matrix @ q


class PlaybookRetriever:
    """Векторный поиск по локальному индексу viral_playbook."""

    def __init__(
        self,
        index_path: Path | str | None = None,
        model_name: str = DEFAULT_MODEL,
        db_path: Path | str | None = None,
    ) -> None:
        self.index_path = Path(index_path) if index_path else DEFAULT_INDEX
        self.model_name = model_name
        self.db_path = Path(db_path) if db_path else DEFAULT_DB
        self.vectors: np.ndarray = np.zeros((0, 0), dtype=np.float32)
        self.ids: list[str] = []
        self.niches: list[str] = []
        self.titles: list[str] = []
        self.hooks: list[str] = []
        self.save_rates: np.ndarray = np.zeros(0, dtype=np.float32)
        self.bookmarks: np.ndarray = np.zeros(0, dtype=np.int32)
        self.slides_json: list[str] = []
        self._loaded = False
        self._load_error: str | None = None

    @property
    def size(self) -> int:
        return int(self.vectors.shape[0]) if self._loaded else 0

    def available(self) -> bool:
        if not self._loaded:
            self.load()
        return self._loaded and self.size > 0

    def load(self) -> bool:
        if self._loaded and self.size > 0:
            return True
        path = self.index_path
        if not path.is_file():
            self._load_error = f"index missing: {path}"
            logger.warning(self._load_error)
            return False
        try:
            data = np.load(path, allow_pickle=True)
            self.vectors = np.asarray(data["vectors"], dtype=np.float32)
            self.ids = [str(x) for x in data["ids"].tolist()]
            self.niches = [str(x) for x in data["niches"].tolist()]
            self.titles = [str(x) for x in data["titles"].tolist()]
            self.hooks = [str(x) for x in data["hooks"].tolist()]
            self.save_rates = np.asarray(data["save_rates"], dtype=np.float32)
            self.bookmarks = np.asarray(data["bookmarks"], dtype=np.int32)
            self.slides_json = [str(x) for x in data["slides_json"].tolist()]
            self._loaded = True
            self._load_error = None
            logger.info(
                "PlaybookRetriever loaded %d vectors from %s",
                self.size,
                path,
            )
            return True
        except Exception as exc:
            self._load_error = str(exc)
            logger.warning("Failed to load playbook index: %s", exc)
            return False

    def get_top_examples(
        self,
        topic: str,
        niche: str = "",
        top_k: int = DEFAULT_TOP_K,
    ) -> list[dict[str, Any]]:
        """
        Топ-k вирусных прецедентов под тему.
        score = similarity*0.7 + save_rate_norm*0.3
        """
        if not self.available():
            return []

        topic = (topic or "").strip()
        if not topic:
            return []

        query_parts = [topic]
        if (niche or "").strip():
            query_parts.insert(0, f"Niche: {niche.strip()}")
        query_text = ". ".join(query_parts)

        q = embed_texts([query_text], model_name=self.model_name)[0]
        sims = cosine_sim_matrix(q, self.vectors)

        # soft niche boost: +0.05 if niche token appears
        niche_l = (niche or "").strip().lower()
        if niche_l:
            for i, n in enumerate(self.niches):
                if niche_l in (n or "").lower():
                    sims[i] = min(1.0, float(sims[i]) + 0.05)

        sr = self.save_rates.astype(np.float32)
        sr_max = float(sr.max()) if sr.size else 1.0
        sr_min = float(sr.min()) if sr.size else 0.0
        denom = max(sr_max - sr_min, 1e-9)
        sr_norm = (sr - sr_min) / denom

        scores = sims * 0.7 + sr_norm * 0.3
        k = max(1, min(int(top_k), self.size))
        # argpartition then sort top-k
        if self.size > k:
            idx = np.argpartition(-scores, k)[:k]
            idx = idx[np.argsort(-scores[idx])]
        else:
            idx = np.argsort(-scores)

        out: list[dict[str, Any]] = []
        for i in idx[:k]:
            slides = self._parse_slides(self.slides_json[i], self.hooks[i])
            out.append(
                {
                    "id": self.ids[i],
                    "niche": self.niches[i],
                    "title": self.titles[i],
                    "hook": self.hooks[i],
                    "slides": slides,
                    "slides_text": slides,
                    "save_rate": float(self.save_rates[i]),
                    "bookmarks": int(self.bookmarks[i]),
                    "score": float(scores[i]),
                    "similarity": float(sims[i]),
                }
            )
        return out

    @staticmethod
    def _parse_slides(raw_json: str, hook: str) -> list[str]:
        slides: list[str] = []
        try:
            data = json.loads(raw_json or "[]")
            if isinstance(data, list):
                slides = [str(t).strip() for t in data if str(t).strip()]
        except json.JSONDecodeError:
            slides = []
        hook_c = (hook or "").strip()
        if hook_c and (not slides or slides[0].lower() != hook_c.lower()):
            slides = [hook_c] + [s for s in slides if s.lower() != hook_c.lower()]
        elif not slides and hook_c:
            slides = [hook_c]
        return slides


def get_retriever(
    index_path: Path | str | None = None,
    model_name: str = DEFAULT_MODEL,
) -> PlaybookRetriever:
    global _RETRIEVER
    with _RETRIEVER_LOCK:
        if _RETRIEVER is None:
            _RETRIEVER = PlaybookRetriever(
                index_path=index_path,
                model_name=model_name,
            )
            _RETRIEVER.load()
        return _RETRIEVER


def examples_as_dicts_to_prompt_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Нормализация для llm_engine."""
    return rows
