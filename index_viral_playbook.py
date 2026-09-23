#!/usr/bin/env python3
"""
Индексация viral_playbook → data/playbook_vectors.npz (FastEmbed, CPU, $0).

Запуск:
  pip install fastembed
  python index_viral_playbook.py
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rag_retriever import (  # noqa: E402
    DEFAULT_DB,
    DEFAULT_INDEX,
    DEFAULT_MODEL,
    build_index_doc,
    embed_texts,
)


def ensure_fastembed() -> None:
    try:
        import fastembed  # noqa: F401
    except ImportError:
        print("[..] fastembed не установлен — ставлю…")
        import subprocess

        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "fastembed", "-q"]
        )
        print("[OK] fastembed установлен")


def load_rows(db_path: Path) -> list[dict]:
    if not db_path.is_file():
        raise FileNotFoundError(f"DB not found: {db_path}")
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
    out = []
    for r in rows:
        hook = str(r["real_hook"] or "").strip()
        if not hook:
            continue
        out.append(
            {
                "id": str(r["id"]),
                "title": str(r["title"] or ""),
                "niche": str(r["niche"] or ""),
                "hook": hook,
                "slides_json": str(r["slides_text_json"] or "[]"),
                "save_rate": float(r["save_rate"] or 0),
                "bookmarks": int(r["bookmarks"] or 0),
            }
        )
    return out


def main() -> int:
    ensure_fastembed()
    import numpy as np

    db = DEFAULT_DB
    out = DEFAULT_INDEX
    print("=" * 56)
    print("  Index viral_playbook -> FastEmbed vectors")
    print(f"  DB:    {db}")
    print(f"  Model: {DEFAULT_MODEL}")
    print(f"  Out:   {out}")
    print("=" * 56)

    t0 = time.perf_counter()
    rows = load_rows(db)
    print(f"[OK] rows with real_hook: {len(rows)}")
    if not rows:
        print("[FAIL] empty playbook")
        return 1

    docs = [
        build_index_doc(r["niche"], r["hook"], r["title"]) for r in rows
    ]
    print(f"[..] embedding {len(docs)} docs on CPU...")
    t_emb = time.perf_counter()
    vectors = embed_texts(docs, model_name=DEFAULT_MODEL)
    emb_sec = time.perf_counter() - t_emb
    print(
        f"[OK] vectors shape={vectors.shape} dtype={vectors.dtype} "
        f"in {emb_sec:.1f}s"
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out,
        vectors=vectors,
        ids=np.asarray([r["id"] for r in rows], dtype=object),
        niches=np.asarray([r["niche"] for r in rows], dtype=object),
        titles=np.asarray([r["title"] for r in rows], dtype=object),
        hooks=np.asarray([r["hook"] for r in rows], dtype=object),
        save_rates=np.asarray([r["save_rate"] for r in rows], dtype=np.float32),
        bookmarks=np.asarray([r["bookmarks"] for r in rows], dtype=np.int32),
        slides_json=np.asarray([r["slides_json"] for r in rows], dtype=object),
        model=np.asarray([DEFAULT_MODEL], dtype=object),
    )
    total = time.perf_counter() - t0
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"[OK] saved {out} ({size_mb:.1f} MB) in {total:.1f}s total")
    print("     Retriever ready: from core.rag_retriever import get_retriever")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
