#!/usr/bin/env python3
"""
reverse_engineer_queries_local.py
=================================
Масштабный локальный Image-to-Query на SigLIP ($0 API).

Цель: 1000 новых каруселей × 3 слайда = 3000 фото.
Батчи по 16, gc каждые 100, сохранение patterns каждые 200.

Запуск:
  python core/reverse_engineer_queries_local.py
  python core/reverse_engineer_queries_local.py --limit-images 3000
  python core/reverse_engineer_queries_local.py --dry-run
  python core/reverse_engineer_queries_local.py --resume
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "reelfarm_database.db"
CAROUSELS_ROOT = ROOT / "downloaded_carousels"
ALL_DIR = CAROUSELS_ROOT / "_all"
ORG_MAP_PATH = CAROUSELS_ROOT / "_organization_map.json"
RENAME_MAP_PATH = CAROUSELS_ROOT / "_rename_map.json"

DATA_DIR = ROOT / "data"
PATTERNS_PATH = DATA_DIR / "viral_query_patterns.json"
REPORT_PATH = DATA_DIR / "query_taxonomy_report.md"
CHECKPOINT_PATH = DATA_DIR / "viral_query_local_checkpoint.jsonl"
GEMINI_CHECKPOINT = DATA_DIR / "viral_query_checkpoint.jsonl"

DEFAULT_TARGET_IMAGES = 3000
DEFAULT_CAROUSELS = 1000
SLIDES_PER = 3
BATCH_SIZE = 16
GC_EVERY = 100
SAVE_EVERY = 200
MAX_SIDE = 384  # быстрее + меньше RAM

PRIORITY_NICHES = (
    "fitness",
    "skincare",
    "relationships",
    "relationship",
    "career",
    "dating",
    "clean girl",
    "wellness",
    "self improvement",
)

ARCHETYPES: dict[str, str] = {
    "pov_hands": (
        "close-up first-person view of hands holding phone coffee mug keys "
        "mirror selfie arms visible casual iPhone POV snapshot"
    ),
    "cozy_bed_space": (
        "unmade bed with pillows blankets books journal morning bedroom "
        "person reading under duvet cozy bed space candid photo"
    ),
    "silhouette_behind": (
        "person seen from behind walking away facing landscape window "
        "back view silhouette figure overlooking scene cinematic photo"
    ),
    "warm_interior": (
        "furnished living room sofa lamp wooden table warm tungsten light "
        "home interior lifestyle candid without bed focus"
    ),
    "flatlay_details": (
        "top-down flat lay desk skincare bottles notebook pen coffee cup "
        "arranged objects on table overhead detail photo"
    ),
    "ambient_city_window": (
        "night city lights through rainy apartment window glass reflection "
        "urban skyline view from inside ambient window photo"
    ),
}

NICHE_TAGS = (
    "gym mirror selfie",
    "gym girl aesthetic",
    "workout mirror selfie",
    "protein shake gym",
    "pilates mat aesthetic",
    "aesthetic yoga home",
    "woman practicing yoga",
    "clean girl skincare",
    "glow skin routine",
    "skincare mirror selfie",
    "aesthetic bathroom vanity",
    "clean girl vanity",
    "rory gilmore aesthetic",
    "dark academia aesthetic",
    "book on bed aesthetic",
    "book on bed",
    "cozy study aesthetic",
    "aesthetic journaling pov",
    "girl reading book",
    "person reading library",
    "dark academia desk",
    "cozy bedroom aesthetic",
    "cozy pajamas reading bed",
    "cozy window reading nook",
    "messy bed aesthetic",
    "golden hour aesthetic",
    "golden hour kitchen",
    "aesthetic candle interior",
    "cozy warm living room",
    "empty coffee cup aesthetic",
    "brunch table aesthetic",
    "girl mirror selfie",
    "mirror selfie aesthetic",
    "pov car aesthetic",
    "low angle selfie aesthetic",
    "aesthetic laptop workspace",
    "laptop window view",
    "spotify listening aesthetic",
    "couple aesthetic",
    "couple cozy aesthetic",
    "relationship couple candid",
    "couple sunset walk",
    "night city street aesthetic",
    "cozy night city view",
    "woman balcony sunset",
    "sunset city skyline",
    "90s moody aesthetic",
    "office desk aesthetic",
    "old money office",
    "career girl laptop",
)

_BANNED_QUERY_EXACT = {
    "pov aesthetic",
    "protein aesthetic",
    "hour aesthetic",
    "hour cozy aesthetic",
    "routine aesthetic",
    "moody aesthetic",
    "gym aesthetic",
    "night aesthetic",
    "girl aesthetic",
    "car aesthetic",
    "city aesthetic",
    "book aesthetic",
    "woman aesthetic",
    "skin aesthetic",
    "skin cozy aesthetic",
    "protein cozy aesthetic",
    "routine cozy aesthetic",
    "pov cozy aesthetic",
    "city cozy aesthetic",
    "skincare cozy aesthetic",
}

_BANNED_HEADS = {
    "pov", "protein", "hour", "routine", "moody", "gym", "night", "girl",
    "car", "city", "book", "woman", "skin", "selfie", "cozy",
}

ARCHETYPE_ORDER = list(ARCHETYPES.keys())


def is_good_query(q: str) -> bool:
    """Отсечь мусор вида 'protein aesthetic' / 'hour cozy aesthetic'."""
    q = re.sub(r"\s+", " ", (q or "").strip().lower())
    words = re.findall(r"[a-z0-9']+", q)
    if len(words) < 2 or len(words) > 4:
        return False
    q = " ".join(words)
    if q in _BANNED_QUERY_EXACT:
        return False
    if len(words) == 2 and words[1] == "aesthetic" and words[0] in _BANNED_HEADS:
        return False
    if (
        len(words) == 3
        and words[1] == "cozy"
        and words[2] == "aesthetic"
    ):
        # разрешаем только осмысленные объекты, не прилагательные-обрубки
        if words[0] not in {"couple", "bedroom", "study", "night", "home", "sofa"}:
            return False
    if words[0] == "hour":
        return False
    # "glow cozy aesthetic", "minimalist aesthetic quote" и т.п.
    if len(words) >= 2 and words[-1] == "aesthetic" and words[0] in {
        "glow", "minimalist", "routine", "protein", "hour", "moody", "empty"
    } and "cup" not in words and "coffee" not in words:
        if q not in {"empty coffee cup aesthetic"}:
            # empty coffee cup — ок, ловится выше словами
            if words[0] in {"glow", "minimalist", "routine", "protein", "hour", "moody"}:
                return False
    return True


def hard_gc() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    gc.collect()


def ram_mb() -> float:
    try:
        import psutil  # type: ignore

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        try:
            import resource

            # Linux: ru_maxrss KB; Windows fallback 0
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        except Exception:
            return 0.0


def connect_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------

def load_folder_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    for map_path in (ORG_MAP_PATH, RENAME_MAP_PATH):
        if not map_path.is_file():
            continue
        try:
            data = json.loads(map_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for cid, meta in data.items():
            if not isinstance(meta, dict):
                continue
            folder_name = str(meta.get("folder") or "").strip()
            if not folder_name:
                continue
            candidate = ALL_DIR / folder_name
            if candidate.is_dir() and (candidate / "1.jpg").is_file():
                index[str(cid)] = candidate
        del data
    hard_gc()
    return index


def resolve_folder(carousel_id: str, index: dict[str, Path]) -> Path | None:
    if carousel_id in index:
        return index[carousel_id]
    direct = CAROUSELS_ROOT / carousel_id
    if direct.is_dir() and (direct / "1.jpg").is_file():
        return direct
    suffix = carousel_id[:8] if len(carousel_id) >= 8 else carousel_id
    if ALL_DIR.is_dir() and suffix:
        for p in ALL_DIR.iterdir():
            if p.is_dir() and p.name.endswith(suffix) and (p / "1.jpg").is_file():
                return p
    return None


def slide_paths(folder: Path, n: int = SLIDES_PER) -> list[Path]:
    out: list[Path] = []
    for i in range(1, n + 1):
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            path = folder / f"{i}{ext}"
            if path.is_file() and path.stat().st_size > 0:
                out.append(path)
                break
    return out


def load_used_carousel_ids() -> set[str]:
    used: set[str] = set()
    if PATTERNS_PATH.is_file():
        try:
            data = json.loads(PATTERNS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        for arch in (data.get("archetypes") or {}).values():
            for ex in arch.get("examples") or []:
                cid = str(ex.get("carousel_id") or "")
                if cid:
                    used.add(cid)
    for cp in (GEMINI_CHECKPOINT, CHECKPOINT_PATH):
        if not cp.is_file():
            continue
        with cp.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cid = str(row.get("carousel_id") or "")
                if cid:
                    used.add(cid)
    return used


def niche_priority(niche: str) -> int:
    low = (niche or "").lower()
    for i, key in enumerate(PRIORITY_NICHES):
        if key in low:
            return i
    return 100


def fetch_candidate_carousels(
    conn: sqlite3.Connection,
    used: set[str],
    *,
    need: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, title, niche, views, bookmarks, save_rate
        FROM viral_playbook
        WHERE save_rate IS NOT NULL AND save_rate > 0
        ORDER BY save_rate DESC, bookmarks DESC
        """
    ).fetchall()
    pool: list[dict[str, Any]] = []
    for r in rows:
        cid = str(r["id"])
        if cid in used:
            continue
        pool.append(
            {
                "id": cid,
                "title": str(r["title"] or ""),
                "niche": str(r["niche"] or ""),
                "views": int(r["views"] or 0),
                "bookmarks": int(r["bookmarks"] or 0),
                "save_rate": float(r["save_rate"] or 0),
                "_prio": niche_priority(str(r["niche"] or "")),
            }
        )
    pool.sort(key=lambda x: (x["_prio"], -x["save_rate"], -x["bookmarks"]))
    return pool[: max(need * 4, need)]


# ---------------------------------------------------------------------------
# Query pool + tagger
# ---------------------------------------------------------------------------

def build_query_pool(patterns: dict[str, Any] | None) -> list[str]:
    """
    Только whitelist реальных 2–4 словных Pinterest-фраз.
    Без '{keyword} aesthetic' expansion.
    """
    pool: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        q = re.sub(r"\s+", " ", (raw or "").strip().lower())
        words = re.findall(r"[a-z0-9']+", q)
        if not words:
            return
        q = " ".join(words[:4])
        if not is_good_query(q) or q in seen:
            return
        seen.add(q)
        pool.append(q)

    for t in NICHE_TAGS:
        add(t)

    if patterns:
        for item in patterns.get("query_frequency") or []:
            add(str(item.get("query") or ""))
        for arch in (patterns.get("archetypes") or {}).values():
            for item in arch.get("top_queries") or []:
                add(str(item.get("query") or ""))
            for ex in arch.get("examples") or []:
                src = str(ex.get("source") or "")
                # Gemini-фразы всегда; локальный мусор отсечёт is_good_query
                if src != "local_siglip" or is_good_query(str(ex.get("pinterest_query") or "")):
                    add(str(ex.get("pinterest_query") or ""))
    return pool


class LocalQueryTagger:
    """Zero-shot SigLIP: архетип + лучший тег. Батчи изображений."""

    def __init__(self) -> None:
        self._emb = None
        self.arch_labels: list[str] = []
        self.arch_vecs: np.ndarray | None = None
        self.query_labels: list[str] = []
        self.query_vecs: np.ndarray | None = None

    def ensure(self, query_pool: list[str]) -> None:
        from core.taste_embedder import get_embedder

        self._emb = get_embedder()
        self._emb.ensure()
        self.arch_labels = list(ARCHETYPE_ORDER)
        self.arch_vecs = self._emb.embed_texts([ARCHETYPES[a] for a in self.arch_labels])
        self.query_labels = list(query_pool)
        rows: list[np.ndarray] = []
        for i in range(0, len(self.query_labels), 32):
            rows.append(self._emb.embed_texts(self.query_labels[i : i + 32]))
            if i and i % 128 == 0:
                hard_gc()
        self.query_vecs = (
            np.concatenate(rows, axis=0) if rows else np.zeros((0, 768), np.float32)
        )

    def tag_batch(
        self, images: list[Image.Image]
    ) -> list[tuple[str, str, float, float]]:
        assert self._emb is not None
        assert self.arch_vecs is not None and self.query_vecs is not None
        if not images:
            return []
        vecs = self._emb.embed_images(images)
        arch_sims = vecs @ self.arch_vecs.T
        # центрирование по строке — меньше схлопывания в один архетип
        arch_sims = arch_sims - arch_sims.mean(axis=1, keepdims=True)
        q_sims = vecs @ self.query_vecs.T
        out: list[tuple[str, str, float, float]] = []
        for i in range(len(images)):
            ai = int(np.argmax(arch_sims[i]))
            qi = int(np.argmax(q_sims[i]))
            out.append(
                (
                    self.arch_labels[ai],
                    self.query_labels[qi],
                    float(arch_sims[i, ai]),
                    float(q_sims[i, qi]),
                )
            )
        return out


def load_resized(path: Path, max_side: int = MAX_SIDE) -> Image.Image | None:
    try:
        with Image.open(path) as im:
            img = im.convert("RGB")
            w, h = img.size
            long_side = max(w, h)
            if long_side > max_side:
                scale = max_side / float(long_side)
                img = img.resize(
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    Image.Resampling.BILINEAR,
                )
            return img
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Persist
# ---------------------------------------------------------------------------

def load_patterns() -> dict[str, Any]:
    if not PATTERNS_PATH.is_file():
        return {
            "generated_at": "",
            "model": "local-siglip",
            "source": "",
            "n_samples": 0,
            "n_carousels": 0,
            "top_keywords": [],
            "archetypes": {
                a: {"count": 0, "top_queries": [], "top_objects": [], "examples": []}
                for a in ARCHETYPE_ORDER
            },
            "query_frequency": [],
        }
    return json.loads(PATTERNS_PATH.read_text(encoding="utf-8"))


def append_checkpoint_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CHECKPOINT_PATH.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_local_checkpoint() -> dict[str, dict[str, Any]]:
    done: dict[str, dict[str, Any]] = {}
    if not CHECKPOINT_PATH.is_file():
        return done
    with CHECKPOINT_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = str(row.get("key") or "")
            if key:
                done[key] = row
    return done


def tokenize_keywords(queries: list[str]) -> Counter[str]:
    stop = {
        "a", "an", "the", "and", "or", "of", "in", "on", "with", "to", "for",
        "photo", "aesthetic", "candid", "shot", "iphone", "dump",
    }
    c: Counter[str] = Counter()
    for q in queries:
        for w in re.findall(r"[a-z0-9']+", q.lower()):
            if len(w) >= 3 and w not in stop:
                c[w] += 1
    return c


def rebuild_patterns(all_rows: list[dict[str, Any]], *, base_meta: dict[str, Any]) -> dict[str, Any]:
    by_arch: dict[str, list[dict[str, Any]]] = {a: [] for a in ARCHETYPE_ORDER}
    all_queries: list[str] = []
    for row in all_rows:
        arch = str(row.get("archetype") or "warm_interior")
        if arch not in by_arch:
            arch = "warm_interior"
        query = str(row.get("pinterest_query") or "").strip().lower()
        entry = {
            "carousel_id": row.get("carousel_id"),
            "slide": row.get("slide"),
            "save_rate": row.get("save_rate"),
            "pinterest_query": query,
            "dominant_objects": row.get("dominant_objects") or [],
            "folder": row.get("folder"),
            "source": row.get("source") or "local_siglip",
            "niche": row.get("niche"),
        }
        by_arch[arch].append(entry)
        if query:
            all_queries.append(query)

    archetypes_out: dict[str, Any] = {}
    for arch in ARCHETYPE_ORDER:
        items = by_arch[arch]
        q_counter = Counter(i["pinterest_query"] for i in items if i.get("pinterest_query"))
        archetypes_out[arch] = {
            "count": len(items),
            "top_queries": [{"query": q, "count": n} for q, n in q_counter.most_common(20)],
            "top_objects": [],
            "examples": items[:20],
        }

    kw = tokenize_keywords(all_queries)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": "gemini+local-siglip",
        "source": (
            f"{base_meta.get('source') or 'viral'} + local SigLIP x3000 "
            f"(batch={BATCH_SIZE})"
        ),
        "n_samples": len(all_rows),
        "n_carousels": len({r.get("carousel_id") for r in all_rows}),
        "top_keywords": [{"keyword": k, "count": n} for k, n in kw.most_common(50)],
        "archetypes": archetypes_out,
        "query_frequency": [
            {"query": q, "count": n} for q, n in Counter(all_queries).most_common(80)
        ],
        "samples_note": "examples truncated per archetype; full rows in checkpoint jsonl",
    }


def write_report(patterns: dict[str, Any]) -> None:
    lines = [
        "# Viral Query Taxonomy",
        "",
        f"Generated: `{patterns.get('generated_at')}`",
        f"Model: `{patterns.get('model')}`",
        f"Source: {patterns.get('source')}",
        f"Samples: **{patterns.get('n_samples')}** from **{patterns.get('n_carousels')}** carousels",
        "",
        "## Top-50 keywords",
        "",
    ]
    for i, item in enumerate(patterns.get("top_keywords") or [], 1):
        lines.append(f"{i}. `{item['keyword']}` — {item['count']}")
    lines.append("")
    lines.append("## Archetype distribution")
    lines.append("")
    total = max(1, int(patterns.get("n_samples") or 1))
    for arch in ARCHETYPE_ORDER:
        block = (patterns.get("archetypes") or {}).get(arch) or {}
        n = int(block.get("count") or 0)
        pct = 100.0 * n / total
        lines.append(f"- `{arch}`: **{n}** ({pct:.1f}%)")
    lines.append("")
    lines.append("## Archetypes detail")
    lines.append("")
    for arch in ARCHETYPE_ORDER:
        block = (patterns.get("archetypes") or {}).get(arch) or {}
        lines.append(f"### `{arch}` ({block.get('count', 0)} slides)")
        lines.append("")
        for t in (block.get("top_queries") or [])[:12]:
            lines.append(f"- **{t['query']}** x{t['count']}")
        lines.append("")
        for ex in (block.get("examples") or [])[:6]:
            lines.append(
                f"  - `{ex.get('carousel_id')}` s{ex.get('slide')}: "
                f"`{ex.get('pinterest_query')}` [{ex.get('source')}]"
            )
        lines.append("")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def collect_existing_rows(
    patterns: dict[str, Any],
    local_done: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    if GEMINI_CHECKPOINT.is_file():
        with GEMINI_CHECKPOINT.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = str(row.get("key") or "")
                if key and row.get("pinterest_query"):
                    row = dict(row)
                    row.setdefault("source", "gemini_vision")
                    by_key[key] = row
    for arch_name, block in (patterns.get("archetypes") or {}).items():
        for ex in block.get("examples") or []:
            cid = str(ex.get("carousel_id") or "")
            slide = ex.get("slide")
            key = f"{cid}:{slide}"
            if not cid or key in by_key:
                continue
            by_key[key] = {
                "key": key,
                "carousel_id": cid,
                "slide": slide,
                "save_rate": ex.get("save_rate"),
                "pinterest_query": ex.get("pinterest_query"),
                "archetype": arch_name,
                "dominant_objects": ex.get("dominant_objects") or [],
                "folder": ex.get("folder"),
                "source": "gemini_vision",
            }
    for key, row in local_done.items():
        if row.get("pinterest_query"):
            by_key[key] = row
    return by_key


def save_library(by_key: dict[str, dict[str, Any]], base_meta: dict[str, Any]) -> dict[str, Any]:
    out = rebuild_patterns(list(by_key.values()), base_meta=base_meta)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PATTERNS_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report(out)
    return out


def progress_line(
    done: int,
    total: int,
    *,
    speed: float,
    tags_found: int,
) -> str:
    pct = int(round(100.0 * done / max(1, total)))
    return (
        f"[{done:04d} / {total}] ({pct}%) | "
        f"Speed: ~{speed:.0f} foto/s | "
        f"RAM: {ram_mb():.0f} MB | "
        f"Tags found: {tags_found} | Cost: $0.00"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    *,
    limit_images: int,
    dry_run: bool,
    resume: bool,
    carousels: int,
) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    print("=" * 72)
    print("  reverse_engineer_queries_local | SigLIP batch | $0.00")
    print("=" * 72)

    used = load_used_carousel_ids()
    print(f"  Already covered carousels: {len(used)}")

    patterns = load_patterns()
    need_carousels = max(carousels, (limit_images + SLIDES_PER - 1) // SLIDES_PER)

    conn = connect_db(DB_PATH)
    candidates = fetch_candidate_carousels(conn, used, need=need_carousels)
    conn.close()

    print("  Building folder index…")
    index = load_folder_index()
    print(f"  Folder index: {len(index)}")

    plan: list[dict[str, Any]] = []
    for c in candidates:
        if len(plan) >= need_carousels:
            break
        folder = resolve_folder(c["id"], index)
        if folder is None:
            continue
        slides = slide_paths(folder)
        if len(slides) < SLIDES_PER:
            continue  # строго 3 слайда
        plan.append({**c, "folder": folder, "slides": slides[:SLIDES_PER]})

    flat: list[tuple[dict[str, Any], int, Path]] = []
    for p in plan:
        for si, path in enumerate(p["slides"], 1):
            if len(flat) >= limit_images:
                break
            flat.append((p, si, path))
        if len(flat) >= limit_images:
            break

    # ровно кратно 3, если возможно
    if len(flat) > limit_images:
        flat = flat[:limit_images]

    print(f"  Planned carousels: {len(plan)}")
    print(f"  Images queued: {len(flat)} (target {limit_images})")
    print(f"  Batch size: {BATCH_SIZE} | GC every {GC_EVERY} | Save every {SAVE_EVERY}")
    print()

    if dry_run:
        for i, (p, si, path) in enumerate(flat[:15], 1):
            print(f"  [dry {i}/{len(flat)}] {p['id']} {p['niche']!r} s{si} -> {path.name}")
        print("\n  Dry-run only.")
        return

    local_done = load_local_checkpoint() if resume else {}
    if resume:
        print(f"  Resume: {len(local_done)} checkpoint rows")
    elif CHECKPOINT_PATH.is_file():
        bak = CHECKPOINT_PATH.with_suffix(".jsonl.bak")
        try:
            if bak.exists():
                bak.unlink()
            CHECKPOINT_PATH.replace(bak)
            print(f"  Old checkpoint -> {bak.name}")
        except OSError:
            pass

    by_key = collect_existing_rows(patterns, local_done)
    tags_before = len(by_key)

    # skip already tagged keys in this run queue
    todo = [(p, si, path) for p, si, path in flat if f"{p['id']}:{si}" not in local_done]
    skipped = len(flat) - len(todo)
    if skipped:
        print(f"  Skipping cached in queue: {skipped}")

    query_pool = build_query_pool(patterns)
    print(f"  Query pool: {len(query_pool)}")
    print("  Loading SigLIP + text anchors…")
    tagger = LocalQueryTagger()
    t_load = time.perf_counter()
    tagger.ensure(query_pool)
    print(
        f"  Ready in {time.perf_counter() - t_load:.1f}s "
        f"({getattr(tagger._emb, 'backend_id', '?')})"
    )
    print()

    t0 = time.perf_counter()
    processed = 0
    since_gc = 0
    since_save = 0
    pending_ckpt: list[dict[str, Any]] = []
    n_total = len(flat)
    done_display = skipped

    for start in range(0, len(todo), BATCH_SIZE):
        chunk = todo[start : start + BATCH_SIZE]
        images: list[Image.Image] = []
        meta: list[tuple[dict[str, Any], int, Path]] = []
        for item, si, path in chunk:
            img = load_resized(path)
            if img is None:
                continue
            images.append(img)
            meta.append((item, si, path))

        if not images:
            continue

        try:
            tagged = tagger.tag_batch(images)
        except Exception as exc:
            print(f"  BATCH FAIL {exc.__class__.__name__}: {exc}")
            for im in images:
                del im
            hard_gc()
            continue

        ts = datetime.now().isoformat(timespec="seconds")
        for (item, si, path), (arch, tag, a_sc, t_sc) in zip(meta, tagged):
            key = f"{item['id']}:{si}"
            row = {
                "key": key,
                "carousel_id": item["id"],
                "slide": si,
                "save_rate": item["save_rate"],
                "bookmarks": item["bookmarks"],
                "views": item["views"],
                "niche": item["niche"],
                "folder": str(item["folder"]),
                "image": path.name,
                "pinterest_query": tag,
                "archetype": arch,
                "dominant_objects": tag.split()[:2],
                "arch_score": round(a_sc, 4),
                "tag_score": round(t_sc, 4),
                "source": "local_siglip",
                "ts": ts,
            }
            pending_ckpt.append(row)
            local_done[key] = row
            by_key[key] = row
            processed += 1
            done_display += 1
            since_gc += 1
            since_save += 1

        for im in images:
            del im
        del images, tagged, meta

        elapsed = max(1e-6, time.perf_counter() - t0)
        speed = processed / elapsed
        print(
            progress_line(
                done_display,
                n_total,
                speed=speed,
                tags_found=len(by_key),
            ),
            flush=True,
        )

        if since_gc >= GC_EVERY:
            append_checkpoint_rows(pending_ckpt)
            pending_ckpt.clear()
            hard_gc()
            since_gc = 0

        if since_save >= SAVE_EVERY:
            if pending_ckpt:
                append_checkpoint_rows(pending_ckpt)
                pending_ckpt.clear()
            save_library(by_key, patterns)
            print(
                f"  >> checkpoint saved: {PATTERNS_PATH.name} "
                f"({len(by_key)} tags, RAM {ram_mb():.0f} MB)",
                flush=True,
            )
            since_save = 0
            hard_gc()

    if pending_ckpt:
        append_checkpoint_rows(pending_ckpt)
        pending_ckpt.clear()

    out = save_library(by_key, patterns)
    hard_gc()

    elapsed = max(1e-6, time.perf_counter() - t0)
    print()
    print("=" * 72)
    print(f"  Done. New tags this run: {processed}")
    print(f"  Library samples: {out['n_samples']}  |  carousels: {out['n_carousels']}")
    print(f"  Avg speed: {processed / elapsed:.1f} foto/s  |  RAM: {ram_mb():.0f} MB")
    print(f"  -> {PATTERNS_PATH}")
    print(f"  -> {REPORT_PATH}")
    print(f"  Tags before/after: {tags_before} -> {len(by_key)}")
    print("  Cost: $0.00")
    print("=" * 72)


def resolve_row_image(row: dict[str, Any]) -> Path | None:
    folder = Path(str(row.get("folder") or ""))
    image = str(row.get("image") or "")
    if folder.is_dir():
        if image:
            p = folder / image
            if p.is_file():
                return p
        slide = int(row.get("slide") or 0)
        if slide > 0:
            for ext in (".jpg", ".jpeg", ".png", ".webp"):
                p = folder / f"{slide}{ext}"
                if p.is_file():
                    return p
    return None


def run_retag_local(*, dry_run: bool = False) -> None:
    """
    Переразметить все local_siglip строки whitelist-пулом.
    Gemini-строки не трогаем. Пересобираем patterns + report.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    print("=" * 72)
    print("  RETAG local SigLIP | whitelist queries | $0.00")
    print("=" * 72)

    patterns = load_patterns()
    local_done = load_local_checkpoint()
    by_key = collect_existing_rows(patterns, local_done)

    gemini_keys = {
        k for k, r in by_key.items()
        if str(r.get("source") or "") == "gemini_vision"
    }
    todo_rows: list[tuple[dict[str, Any], Path]] = []
    kept_good_local = 0
    for key, row in by_key.items():
        if key in gemini_keys:
            continue
        # всё не-gemini (local_siglip / unknown) — переразметить
        path = resolve_row_image(row)
        if path is None:
            # оставить только если тег уже хороший
            if is_good_query(str(row.get("pinterest_query") or "")):
                kept_good_local += 1
            continue
        todo_rows.append((row, path))

    print(f"  Keep Gemini rows: {len(gemini_keys)}")
    print(f"  Retag local images: {len(todo_rows)}")
    print(f"  Keep local without file (good tag): {kept_good_local}")

    query_pool = build_query_pool(patterns)
    # жёстко ещё раз профильтровать пул
    query_pool = [q for q in query_pool if is_good_query(q)]
    print(f"  Whitelist pool size: {len(query_pool)}")
    if dry_run:
        print("  Sample pool:", ", ".join(query_pool[:12]))
        print("  Dry-run only.")
        return

    tagger = LocalQueryTagger()
    t_load = time.perf_counter()
    tagger.ensure(query_pool)
    print(f"  SigLIP ready in {time.perf_counter() - t_load:.1f}s")
    print()

    # новый локальный чекпоинт
    if CHECKPOINT_PATH.is_file():
        bak = CHECKPOINT_PATH.with_suffix(".jsonl.preretag.bak")
        try:
            if bak.exists():
                bak.unlink()
            CHECKPOINT_PATH.replace(bak)
            print(f"  Old local checkpoint -> {bak.name}")
        except OSError as exc:
            print(f"  checkpoint backup warn: {exc}")

    new_local: dict[str, dict[str, Any]] = {}
    # сохранить gemini в by_key
    clean_by_key = {k: by_key[k] for k in gemini_keys}
    for key, row in by_key.items():
        if key in gemini_keys:
            continue
        if resolve_row_image(row) is None and is_good_query(str(row.get("pinterest_query") or "")):
            clean_by_key[key] = row

    t0 = time.perf_counter()
    processed = 0
    pending: list[dict[str, Any]] = []
    n_total = len(todo_rows)
    since_gc = 0
    since_save = 0

    for start in range(0, n_total, BATCH_SIZE):
        chunk = todo_rows[start : start + BATCH_SIZE]
        images: list[Image.Image] = []
        meta: list[dict[str, Any]] = []
        for row, path in chunk:
            img = load_resized(path)
            if img is None:
                continue
            images.append(img)
            meta.append(row)

        if not images:
            continue

        try:
            tagged = tagger.tag_batch(images)
        except Exception as exc:
            print(f"  BATCH FAIL {exc.__class__.__name__}: {exc}")
            hard_gc()
            continue

        ts = datetime.now().isoformat(timespec="seconds")
        for row, (arch, tag, a_sc, t_sc) in zip(meta, tagged):
            if not is_good_query(tag):
                # не должно случаться с whitelist, но на всякий
                tag = query_pool[0] if query_pool else "cozy bedroom aesthetic"
            key = str(row.get("key") or f"{row.get('carousel_id')}:{row.get('slide')}")
            new_row = dict(row)
            new_row.update(
                {
                    "key": key,
                    "pinterest_query": tag,
                    "archetype": arch,
                    "dominant_objects": tag.split()[:2],
                    "arch_score": round(a_sc, 4),
                    "tag_score": round(t_sc, 4),
                    "source": "local_siglip",
                    "ts": ts,
                    "retagged": True,
                }
            )
            pending.append(new_row)
            new_local[key] = new_row
            clean_by_key[key] = new_row
            processed += 1
            since_gc += 1
            since_save += 1

        for im in images:
            del im
        del images, tagged, meta

        elapsed = max(1e-6, time.perf_counter() - t0)
        print(
            progress_line(
                processed,
                n_total,
                speed=processed / elapsed,
                tags_found=len(clean_by_key),
            ),
            flush=True,
        )

        if since_gc >= GC_EVERY:
            append_checkpoint_rows(pending)
            pending.clear()
            hard_gc()
            since_gc = 0

        if since_save >= SAVE_EVERY:
            if pending:
                append_checkpoint_rows(pending)
                pending.clear()
            save_library(clean_by_key, patterns)
            print(
                f"  >> saved mid-retag library ({len(clean_by_key)} tags)",
                flush=True,
            )
            since_save = 0
            hard_gc()

    if pending:
        append_checkpoint_rows(pending)

    out = save_library(clean_by_key, patterns)
    # быстрая статистика качества
    freqs = out.get("query_frequency") or []
    bad_n = sum(1 for t in freqs if not is_good_query(str(t.get("query") or "")))
    print()
    print("=" * 72)
    print(f"  Retag done: {processed} local images")
    print(f"  Library: {out['n_samples']} samples / {out['n_carousels']} carousels")
    print(f"  Bad queries left in top list: {bad_n}")
    print("  Top-10 now:")
    for t in freqs[:10]:
        print(f"    {t['count']:4}  {t['query']}")
    print("  Archetypes:")
    for a in ARCHETYPE_ORDER:
        b = (out.get("archetypes") or {}).get(a) or {}
        print(f"    {a:22} {b.get('count', 0)}")
    print(f"  -> {PATTERNS_PATH}")
    print(f"  -> {REPORT_PATH}")
    print("  Cost: $0.00")
    print("=" * 72)


def main() -> None:
    ap = argparse.ArgumentParser(description="Local SigLIP Image-to-Query x3000 ($0)")
    ap.add_argument("--limit-images", type=int, default=DEFAULT_TARGET_IMAGES)
    ap.add_argument("--carousels", type=int, default=DEFAULT_CAROUSELS)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument(
        "--retag-local",
        action="store_true",
        help="Re-tag all local_siglip rows with cleaned whitelist (no Gemini)",
    )
    args = ap.parse_args()
    if args.retag_local:
        run_retag_local(dry_run=bool(args.dry_run))
        return
    run(
        limit_images=max(1, int(args.limit_images)),
        dry_run=bool(args.dry_run),
        resume=bool(args.resume),
        carousels=max(1, int(args.carousels)),
    )


if __name__ == "__main__":
    main()
