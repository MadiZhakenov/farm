#!/usr/bin/env python3
"""
Уровень 5: кластеризация viral_playbook → data/archetypes_dna.json

Запуск:
  pip install scikit-learn fastembed
  python cluster_playbook.py
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rag_retriever import (  # noqa: E402
    DEFAULT_DB,
    DEFAULT_INDEX,
    DEFAULT_MODEL,
    embed_texts,
)

OUT_PATH = ROOT / "data" / "archetypes_dna.json"
N_CLUSTERS = 8
RANDOM_STATE = 42

# Именованные архетипы — матч по TF-IDF ключевикам
NAME_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("The Brutal Reframe", ("reframe", "actually", "truth", "lie", "wrong", "honest")),
    ("The Identity Callout", ("you", "girls", "people", "anyone", "identity", "who")),
    ("The Friction Protocol", ("rule", "protocol", "habit", "system", "timer", "block")),
    ("The Visual Cheat-Sheet", ("screenshot", "list", "checklist", "things", "ways", "signs")),
    ("The Named System", ("method", "framework", "matrix", "formula", "playbook")),
    ("The Situational Punch", ("when", "before", "after", "tonight", "morning", "stuck")),
    ("The Authority Drop", ("therapist", "professor", "scientist", "taught", "learned")),
    ("The Soft Imperative", ("stop", "quit", "never", "don", "enough", "need")),
]


def ensure_sklearn() -> None:
    try:
        import sklearn  # noqa: F401
    except ImportError:
        print("[..] installing scikit-learn...")
        import subprocess

        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "scikit-learn", "-q"]
        )
        print("[OK] scikit-learn installed")


def load_playbook(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, title, niche, real_hook, slides_text_json,
                   save_rate, bookmarks
            FROM viral_playbook
            WHERE real_hook IS NOT NULL
              AND length(trim(real_hook)) > 5
            ORDER BY bookmarks DESC
            """
        ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        hook = str(r["real_hook"] or "").strip()
        if not hook:
            continue
        slides: list[str] = []
        try:
            raw = json.loads(r["slides_text_json"] or "[]")
            if isinstance(raw, list):
                slides = [str(t).strip() for t in raw if str(t).strip()]
        except json.JSONDecodeError:
            slides = []
        if hook and (not slides or slides[0].lower() != hook.lower()):
            slides = [hook] + [s for s in slides if s.lower() != hook.lower()]
        out.append(
            {
                "id": str(r["id"]),
                "title": str(r["title"] or ""),
                "niche": str(r["niche"] or ""),
                "hook": hook,
                "slides": slides,
                "save_rate": float(r["save_rate"] or 0),
                "bookmarks": int(r["bookmarks"] or 0),
            }
        )
    return out


def load_or_embed_vectors(
    rows: list[dict[str, Any]],
) -> np.ndarray:
    """Reuse playbook_vectors.npz if ids align; else embed hooks."""
    index = DEFAULT_INDEX
    if index.is_file():
        try:
            data = np.load(index, allow_pickle=True)
            ids = [str(x) for x in data["ids"].tolist()]
            vectors = np.asarray(data["vectors"], dtype=np.float32)
            id_to_i = {pid: i for i, pid in enumerate(ids)}
            if all(r["id"] in id_to_i for r in rows):
                order = [id_to_i[r["id"]] for r in rows]
                print(f"[OK] reused embeddings from {index.name}")
                return vectors[order]
            print("[..] index id mismatch — re-embedding hooks")
        except Exception as exc:
            print(f"[..] index load fail ({exc}) — re-embedding")
    hooks = [r["hook"] for r in rows]
    print(f"[..] embedding {len(hooks)} hooks via FastEmbed…")
    return embed_texts(hooks, model_name=DEFAULT_MODEL)


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


def name_archetype(keywords: list[str], cluster_id: int) -> str:
    low = " ".join(keywords).lower()
    best_name = ""
    best_hits = 0
    for name, seeds in NAME_RULES:
        hits = sum(1 for s in seeds if s in low)
        if hits > best_hits:
            best_hits = hits
            best_name = name
    if best_hits >= 1 and best_name:
        return best_name
    # fallback from top keywords
    parts = [k.title() for k in keywords[:2] if k]
    if len(parts) >= 2:
        return f"The {parts[0]} {parts[1]} Pattern"
    if parts:
        return f"The {parts[0]} Protocol"
    return f"Archetype {cluster_id + 1}"


def cluster_keywords(hooks: list[str], top_n: int = 6) -> list[str]:
    from sklearn.feature_extraction.text import TfidfVectorizer

    if not hooks:
        return []
    vec = TfidfVectorizer(
        max_features=4000,
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1,
    )
    try:
        X = vec.fit_transform(hooks)
    except ValueError:
        return []
    scores = np.asarray(X.sum(axis=0)).ravel()
    terms = np.asarray(vec.get_feature_names_out())
    order = np.argsort(-scores)[:top_n]
    return [str(terms[i]) for i in order]


def build_dna(
    rows: list[dict[str, Any]],
    vectors: np.ndarray,
    labels: np.ndarray,
    centroids: np.ndarray,
) -> dict[str, Any]:
    archetypes: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for cid in range(N_CLUSTERS):
        idx = np.where(labels == cid)[0]
        if idx.size == 0:
            continue
        cluster_rows = [rows[i] for i in idx]
        hooks = [r["hook"] for r in cluster_rows]
        keywords = cluster_keywords(hooks)
        name = name_archetype(keywords, cid)
        # unique names
        base = name
        n = 2
        while name in used_names:
            name = f"{base} #{n}"
            n += 1
        used_names.add(name)

        avg_words = float(np.mean([word_count(h) for h in hooks])) if hooks else 0.0
        avg_sr = float(np.mean([r["save_rate"] for r in cluster_rows]))
        # beacons: top-3 by bookmarks then save_rate
        ranked = sorted(
            cluster_rows,
            key=lambda r: (r["bookmarks"], r["save_rate"]),
            reverse=True,
        )[:3]
        beacons = [
            {
                "id": b["id"],
                "hook": b["hook"],
                "slides": b["slides"][:6],
                "save_rate": b["save_rate"],
                "bookmarks": b["bookmarks"],
                "niche": b["niche"],
            }
            for b in ranked
        ]
        archetypes.append(
            {
                "id": int(cid),
                "name": name,
                "keywords": keywords,
                "size": int(idx.size),
                "avg_hook_words": round(avg_words, 2),
                "avg_save_rate": round(avg_sr, 6),
                "centroid": [round(float(x), 6) for x in centroids[cid].tolist()],
                "beacons": beacons,
            }
        )

    archetypes.sort(key=lambda a: a["avg_save_rate"], reverse=True)
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model": DEFAULT_MODEL,
        "n_clusters": N_CLUSTERS,
        "n_posts": len(rows),
        "archetypes": archetypes,
    }


def main() -> int:
    ensure_sklearn()
    from sklearn.cluster import KMeans

    print("=" * 56)
    print("  Level 5 - Cluster viral_playbook DNA")
    print(f"  DB: {DEFAULT_DB}")
    print(f"  Out: {OUT_PATH}")
    print("=" * 56)

    t0 = time.perf_counter()
    rows = load_playbook(DEFAULT_DB)
    print(f"[OK] posts: {len(rows)}")
    if len(rows) < N_CLUSTERS:
        print("[FAIL] not enough posts")
        return 1

    vectors = load_or_embed_vectors(rows)
    print(f"[OK] vectors: {vectors.shape}")

    print(f"[..] KMeans n_clusters={N_CLUSTERS}...")
    km = KMeans(
        n_clusters=N_CLUSTERS,
        random_state=RANDOM_STATE,
        n_init=10,
        max_iter=300,
    )
    labels = km.fit_predict(vectors)
    # L2-normalize centroids for cosine select later
    cents = km.cluster_centers_.astype(np.float32)
    norms = np.linalg.norm(cents, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    cents = cents / norms

    dna = build_dna(rows, vectors, labels, cents)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(dna, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    elapsed = time.perf_counter() - t0
    print(f"[OK] saved {OUT_PATH} in {elapsed:.1f}s")
    for a in dna["archetypes"]:
        print(
            f"  - {a['name']}: n={a['size']} "
            f"words={a['avg_hook_words']} sr={a['avg_save_rate']:.4f} "
            f"kw={', '.join(a['keywords'][:4])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
