#!/usr/bin/env python3
"""
Visual Judge — строго локальный TasteClassifier + UGCFilter (без Gemini / без сети).

Скоринг фото: text-relevance + UGC + гармония.
Ранг: relevance×0.50 + ugc×0.30 + harmony×0.20.
"""

from __future__ import annotations

import logging
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

BACKEND = "local_taste_ugc"
RELEVANCE_MIN_SCORE = 6  # legacy


def combined_rank_score(
    ugc: float,
    taste: float = 0.5,
    harmony: float = 100.0,
    *,
    relevance: float | None = None,
) -> float:
    """
    relevance×0.40 + taste×0.35 + ugc×0.25
    """
    from core.ugc_filter import final_rank_score

    return final_rank_score(ugc, taste, harmony, relevance=relevance)


def evaluate_pil_taste(image: Image.Image) -> dict[str, Any]:
    """Локальная оценка вкуса одной картинки. Без API."""
    try:
        from core.taste_classifier import TASTE_MIN_SCORE, get_taste_classifier

        clf = get_taste_classifier()
        score = float(clf.predict_taste_score(image))
        ok = score >= TASTE_MIN_SCORE if clf.is_trained else True
        return {
            "score": score,
            "is_relevant": ok,
            "reason": "local taste",
            "fallback": False,
            "taste_score": score,
        }
    except Exception as exc:
        logger.warning("local taste failed (%s)", exc)
        return {
            "score": 0.5,
            "is_relevant": True,
            "reason": f"taste err {type(exc).__name__}",
            "fallback": True,
            "taste_score": 0.5,
        }


def evaluate_candidates_taste(images: list[Image.Image]) -> list[dict[str, Any]]:
    """Пакетная локальная оценка (один проход SigLIP)."""
    if not images:
        return []
    try:
        from core.taste_classifier import TASTE_MIN_SCORE, get_taste_classifier

        clf = get_taste_classifier()
        scores = clf.predict_taste_scores(images)
        trained = clf.is_trained
        out: list[dict[str, Any]] = []
        for score in scores:
            s = float(score)
            out.append(
                {
                    "score": s,
                    "is_relevant": (s >= TASTE_MIN_SCORE) if trained else True,
                    "reason": "local taste",
                    "fallback": False,
                    "taste_score": s,
                }
            )
        return out
    except Exception as exc:
        logger.warning("batch local taste failed (%s)", exc)
        return [
            {
                "score": 0.5,
                "is_relevant": True,
                "reason": f"taste err {type(exc).__name__}",
                "fallback": True,
                "taste_score": 0.5,
            }
            for _ in images
        ]


def evaluate_image_relevance(slide_text: str, image_bytes: bytes) -> dict[str, Any]:
    del slide_text
    try:
        import io

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return {
            "score": 0.0,
            "is_relevant": False,
            "reason": "bad image",
            "fallback": True,
            "taste_score": 0.0,
        }
    return evaluate_pil_taste(img)


def evaluate_pil_relevance(slide_text: str, image: Image.Image) -> dict[str, Any]:
    del slide_text
    return evaluate_pil_taste(image)


async def evaluate_candidates_relevance(
    slide_text: str,
    images: list[Image.Image],
) -> list[dict[str, Any]]:
    del slide_text
    return evaluate_candidates_taste(images)
