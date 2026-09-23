#!/usr/bin/env python3
"""
Загрузка DNA-архетипов (Level 5) и выбор релевантного под тему.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np

from core.rag_retriever import DEFAULT_MODEL, embed_texts

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DNA = ROOT / "data" / "archetypes_dna.json"

_DNA: dict[str, Any] | None = None
_DNA_LOCK = threading.Lock()


def load_archetypes_dna(path: Path | None = None) -> dict[str, Any] | None:
    global _DNA
    with _DNA_LOCK:
        if _DNA is not None:
            return _DNA
        p = Path(path) if path else DEFAULT_DNA
        if not p.is_file():
            logger.warning("archetypes DNA missing: %s", p)
            return None
        try:
            _DNA = json.loads(p.read_text(encoding="utf-8"))
            return _DNA
        except Exception as exc:
            logger.warning("DNA load failed: %s", exc)
            return None


def reload_archetypes_dna(path: Path | None = None) -> dict[str, Any] | None:
    global _DNA
    with _DNA_LOCK:
        _DNA = None
    return load_archetypes_dna(path)


def select_archetype(
    topic: str,
    *,
    dna: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Выбрать архетип: cosine(topic_embed, centroid) * 0.7 + avg_save_rate_norm * 0.3
    """
    dna = dna or load_archetypes_dna()
    if not dna:
        return None
    arches = dna.get("archetypes") or []
    if not arches:
        return None

    topic = (topic or "").strip()
    if not topic:
        return arches[0]

    try:
        q = embed_texts([topic], model_name=str(dna.get("model") or DEFAULT_MODEL))[0]
    except Exception as exc:
        logger.warning("archetype embed failed (%s) — top by save_rate", exc)
        return max(arches, key=lambda a: float(a.get("avg_save_rate") or 0))

    sr_vals = [float(a.get("avg_save_rate") or 0) for a in arches]
    sr_min, sr_max = min(sr_vals), max(sr_vals)
    denom = max(sr_max - sr_min, 1e-9)

    best: dict[str, Any] | None = None
    best_score = -1e9
    for a in arches:
        cent = np.asarray(a.get("centroid") or [], dtype=np.float32)
        if cent.size == 0 or cent.shape[0] != q.shape[0]:
            sim = 0.0
        else:
            cnorm = float(np.linalg.norm(cent)) or 1e-12
            cent = cent / cnorm
            sim = float(np.dot(q, cent))
        sr_n = (float(a.get("avg_save_rate") or 0) - sr_min) / denom
        score = sim * 0.7 + sr_n * 0.3
        if score > best_score:
            best_score = score
            best = dict(a)
            best["match_score"] = round(score, 4)
            best["match_similarity"] = round(sim, 4)
    return best


def archetype_prompt_hint(archetype: dict[str, Any] | None) -> str:
    if not archetype:
        return ""
    name = str(archetype.get("name") or "Unknown")
    kws = ", ".join(archetype.get("keywords") or [])
    avg_w = archetype.get("avg_hook_words")
    beacons = archetype.get("beacons") or []
    beacon_hooks = "; ".join(
        str(b.get("hook") or "")[:70] for b in beacons[:2] if b.get("hook")
    )
    return (
        f"DNA ARCHETYPE for this topic: «{name}». "
        f"Match viral DNA: avg hook ~{avg_w} words; keywords [{kws}]. "
        f"Beacon vibes (do NOT copy verbatim): {beacon_hooks}. "
        f"Write ORIGINAL copy in this archetype's energy."
    )
