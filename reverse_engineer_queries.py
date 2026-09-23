#!/usr/bin/env python3
"""
reverse_engineer_queries.py
===========================
Image-to-Query: обратный инжиниринг Pinterest-запросов по фонам
топ-каруселей из viral_playbook.

1) Берёт топ-N каруселей по Save Rate из reelfarm_database.db
2) Для каждой читает слайды 1–3 из downloaded_carousels/
3) Gemini 3.1 Flash Lite (Vision) → 3–4 word query + archetype
4) Агрегирует в data/viral_query_patterns.json + data/query_taxonomy_report.md

Запуск:
  python reverse_engineer_queries.py
  python reverse_engineer_queries.py --limit 60
  python reverse_engineer_queries.py --dry-run
  python reverse_engineer_queries.py --resume
"""

from __future__ import annotations

import argparse
import base64
import gc
import io
import json
import os
import random
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from PIL import Image

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "reelfarm_database.db"
CAROUSELS_ROOT = ROOT / "downloaded_carousels"
ALL_DIR = CAROUSELS_ROOT / "_all"
ORG_MAP_PATH = CAROUSELS_ROOT / "_organization_map.json"
RENAME_MAP_PATH = CAROUSELS_ROOT / "_rename_map.json"

DATA_DIR = ROOT / "data"
OUT_PATTERNS = DATA_DIR / "viral_query_patterns.json"
OUT_REPORT = DATA_DIR / "query_taxonomy_report.md"
CHECKPOINT_PATH = DATA_DIR / "viral_query_checkpoint.jsonl"

DEFAULT_MODEL = "gemini-3.1-flash-lite"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{DEFAULT_MODEL}:generateContent"
)

DEFAULT_TOP_N = 60
SLIDES_PER_CAROUSEL = 3
MAX_LONG_SIDE = 512
JPEG_QUALITY = 75

REQUEST_TIMEOUT = 90.0
MAX_RETRIES = 6
BACKOFF_BASE_SEC = 2.0
PAUSE_BETWEEN_CALLS = (1.0, 2.0)  # jitter

ARCHETYPES = (
    "pov_hands",
    "cozy_bed_space",
    "silhouette_behind",
    "warm_interior",
    "flatlay_details",
    "ambient_city_window",
)

ARCHETYPE_SET = set(ARCHETYPES)

PROMPT = (
    "You are an expert Pinterest visual researcher. Look at this viral social media background.\n"
    "Task:\n"
    "1. What exact 3-4 word search query in Pinterest would lead to a real-life candid image "
    "like this? (NO fluff, NO long sentences, strictly 3-4 words).\n"
    "2. Classify the visual archetype into ONE category:\n"
    "   ['pov_hands', 'cozy_bed_space', 'silhouette_behind', 'warm_interior', "
    "'flatlay_details', 'ambient_city_window'].\n"
    "Return STRICT JSON:\n"
    '{"pinterest_query": "3-4 words", "archetype": "category_name", '
    '"dominant_objects": ["word1", "word2"]}'
)


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def hard_gc() -> None:
    gc.collect()
    gc.collect()


def ensure_api_key() -> str:
    load_dotenv(ROOT / ".env")
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        raise SystemExit(
            "GEMINI_API_KEY не найден.\n"
            "Создайте .env:\n  GEMINI_API_KEY=your_key_here"
        )
    return key


def connect_db(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"Database not found: {path}")
    conn = sqlite3.connect(str(path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    return conn


def pause_jitter() -> None:
    lo, hi = PAUSE_BETWEEN_CALLS
    time.sleep(random.uniform(lo, hi))


# ---------------------------------------------------------------------------
# Folder resolution (same maps as expand_playbook_gemini)
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

    # id as suffix of _all folder name (…_ffef2dc8)
    suffix = carousel_id[:8] if len(carousel_id) >= 8 else carousel_id
    if ALL_DIR.is_dir() and suffix:
        for p in ALL_DIR.iterdir():
            if p.is_dir() and p.name.endswith(suffix) and (p / "1.jpg").is_file():
                return p
    # full id suffix
    if ALL_DIR.is_dir():
        for p in ALL_DIR.iterdir():
            if p.is_dir() and p.name.endswith(carousel_id) and (p / "1.jpg").is_file():
                return p
    return None


def slide_paths_for(folder: Path, n: int = SLIDES_PER_CAROUSEL) -> list[Path]:
    out: list[Path] = []
    for i in range(1, n + 1):
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            path = folder / f"{i}{ext}"
            if path.is_file() and path.stat().st_size > 0:
                out.append(path)
                break
    return out


# ---------------------------------------------------------------------------
# DB: top carousels by save_rate
# ---------------------------------------------------------------------------

def fetch_top_carousels(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, title, niche, views, bookmarks, save_rate
        FROM viral_playbook
        WHERE save_rate IS NOT NULL AND save_rate > 0
        ORDER BY save_rate DESC, bookmarks DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [
        {
            "id": str(r["id"]),
            "title": str(r["title"] or ""),
            "niche": str(r["niche"] or ""),
            "views": int(r["views"] or 0),
            "bookmarks": int(r["bookmarks"] or 0),
            "save_rate": float(r["save_rate"] or 0),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Image → JPEG bytes
# ---------------------------------------------------------------------------

def resize_slide_jpeg(
    path: Path,
    max_side: int = MAX_LONG_SIDE,
    quality: int = JPEG_QUALITY,
) -> bytes:
    with Image.open(path) as img:
        img = img.convert("RGB")
        w, h = img.size
        long_side = max(w, h)
        if long_side > max_side:
            scale = max_side / float(long_side)
            nw = max(1, int(w * scale))
            nh = max(1, int(h * scale))
            img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Gemini Vision (single image)
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No JSON object in Gemini response")
    return json.loads(text[start : end + 1])


def clamp_query(raw: str) -> str:
    words = re.findall(r"[A-Za-z0-9']+", (raw or "").lower())
    words = [w for w in words if w]
    if len(words) > 4:
        words = words[:4]
    if len(words) < 3 and words:
        # leave as-is if model returned shorter; still usable
        pass
    return " ".join(words)


def normalize_archetype(raw: str) -> str:
    key = re.sub(r"[\s\-]+", "_", (raw or "").strip().lower())
    if key in ARCHETYPE_SET:
        return key
    # soft aliases
    aliases = {
        "hands": "pov_hands",
        "pov": "pov_hands",
        "bed": "cozy_bed_space",
        "bedroom": "cozy_bed_space",
        "silhouette": "silhouette_behind",
        "interior": "warm_interior",
        "flatlay": "flatlay_details",
        "flat_lay": "flatlay_details",
        "city": "ambient_city_window",
        "window": "ambient_city_window",
    }
    for needle, arch in aliases.items():
        if needle in key:
            return arch
    return "warm_interior"  # safe default bucket


def normalize_verdict(parsed: dict[str, Any]) -> dict[str, Any]:
    query = clamp_query(str(parsed.get("pinterest_query") or ""))
    archetype = normalize_archetype(str(parsed.get("archetype") or ""))
    objs_raw = parsed.get("dominant_objects") or []
    objects: list[str] = []
    if isinstance(objs_raw, list):
        for item in objs_raw:
            w = re.sub(r"[^a-z0-9'\- ]", "", str(item or "").lower()).strip()
            if w:
                objects.append(w.split()[0] if w else "")
    objects = [o for o in objects if o][:6]
    return {
        "pinterest_query": query,
        "archetype": archetype,
        "dominant_objects": objects,
    }


def call_gemini_image_query(api_key: str, jpeg_bytes: bytes) -> dict[str, Any]:
    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": PROMPT},
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": b64,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 160,
            "responseMimeType": "application/json",
        },
    }
    del b64

    url = f"{GEMINI_URL}?key={api_key}"
    last_err: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = httpx.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        except httpx.RequestError as exc:
            last_err = exc
            wait = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            print(f"    [net] {exc} - retry in {wait:.1f}s ({attempt}/{MAX_RETRIES})")
            time.sleep(wait)
            continue

        if r.status_code == 429 or r.status_code >= 500:
            wait = BACKOFF_BASE_SEC * (2 ** (attempt - 1)) + random.uniform(0, 1.5)
            print(
                f"    [http {r.status_code}] backoff {wait:.1f}s "
                f"({attempt}/{MAX_RETRIES})"
            )
            time.sleep(wait)
            last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            continue

        if r.status_code >= 400:
            raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:400]}")

        data = r.json()
        parts = (
            ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")
            or []
        )
        text = "".join(str(p.get("text") or "") for p in parts)
        if not text:
            block = (data.get("promptFeedback") or {}).get("blockReason")
            raise RuntimeError(
                "Gemini empty response"
                + (f" (blocked: {block})" if block else f": {json.dumps(data)[:240]}")
            )
        return normalize_verdict(_extract_json(text))

    raise RuntimeError(f"Gemini failed after retries: {last_err}")


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def load_checkpoint() -> dict[str, dict[str, Any]]:
    """key = '{carousel_id}:{slide}' → result dict."""
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


def append_checkpoint(row: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CHECKPOINT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def tokenize_keywords(queries: list[str], objects: list[str]) -> Counter[str]:
    stop = {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "in",
        "on",
        "with",
        "to",
        "for",
        "photo",
        "aesthetic",
        "candid",
        "shot",
        "iphone",
        "dump",
    }
    c: Counter[str] = Counter()
    for q in queries:
        for w in re.findall(r"[a-z0-9']+", q.lower()):
            if len(w) < 3 or w in stop:
                continue
            c[w] += 1
    for obj in objects:
        w = re.sub(r"[^a-z0-9']", "", obj.lower())
        if len(w) >= 3 and w not in stop:
            c[w] += 2  # objects чуть весомее
    return c


def aggregate_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_arch: dict[str, list[dict[str, Any]]] = {a: [] for a in ARCHETYPES}
    all_queries: list[str] = []
    all_objects: list[str] = []

    for row in rows:
        arch = normalize_archetype(str(row.get("archetype") or ""))
        query = clamp_query(str(row.get("pinterest_query") or ""))
        objs = [str(x) for x in (row.get("dominant_objects") or []) if x]
        entry = {
            "carousel_id": row.get("carousel_id"),
            "slide": row.get("slide"),
            "save_rate": row.get("save_rate"),
            "pinterest_query": query,
            "dominant_objects": objs,
            "folder": row.get("folder"),
        }
        by_arch.setdefault(arch, []).append(entry)
        if query:
            all_queries.append(query)
        all_objects.extend(objs)

    archetypes_out: dict[str, Any] = {}
    for arch in ARCHETYPES:
        items = by_arch.get(arch) or []
        q_counter = Counter(
            i["pinterest_query"] for i in items if i.get("pinterest_query")
        )
        obj_counter = Counter()
        for i in items:
            for o in i.get("dominant_objects") or []:
                obj_counter[str(o).lower()] += 1
        archetypes_out[arch] = {
            "count": len(items),
            "top_queries": [
                {"query": q, "count": n} for q, n in q_counter.most_common(15)
            ],
            "top_objects": [
                {"object": o, "count": n} for o, n in obj_counter.most_common(12)
            ],
            "examples": items[:12],
        }

    kw = tokenize_keywords(all_queries, all_objects)
    top_keywords = [{"keyword": k, "count": n} for k, n in kw.most_common(30)]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": DEFAULT_MODEL,
        "source": "viral_playbook top by save_rate",
        "n_samples": len(rows),
        "n_carousels": len({r.get("carousel_id") for r in rows}),
        "top_keywords": top_keywords,
        "archetypes": archetypes_out,
        "query_frequency": [
            {"query": q, "count": n}
            for q, n in Counter(all_queries).most_common(40)
        ],
    }


def write_report(patterns: dict[str, Any], path: Path) -> None:
    lines: list[str] = []
    lines.append("# Viral Query Taxonomy")
    lines.append("")
    lines.append(f"Generated: `{patterns.get('generated_at')}`")
    lines.append(f"Model: `{patterns.get('model')}`")
    lines.append(
        f"Samples: **{patterns.get('n_samples')}** "
        f"from **{patterns.get('n_carousels')}** carousels"
    )
    lines.append("")
    lines.append("## Top-30 keywords")
    lines.append("")
    for i, item in enumerate(patterns.get("top_keywords") or [], 1):
        lines.append(f"{i}. `{item['keyword']}` — {item['count']}")
    lines.append("")
    lines.append("## Archetypes")
    lines.append("")

    for arch in ARCHETYPES:
        block = (patterns.get("archetypes") or {}).get(arch) or {}
        lines.append(f"### `{arch}` ({block.get('count', 0)} slides)")
        lines.append("")
        tops = block.get("top_queries") or []
        if tops:
            lines.append("Effective Pinterest queries:")
            lines.append("")
            for t in tops[:10]:
                lines.append(f"- **{t['query']}** ×{t['count']}")
            lines.append("")
        objs = block.get("top_objects") or []
        if objs:
            lines.append(
                "Objects: "
                + ", ".join(f"`{o['object']}` ({o['count']})" for o in objs[:8])
            )
            lines.append("")
        examples = block.get("examples") or []
        if examples:
            lines.append("Examples:")
            lines.append("")
            for ex in examples[:6]:
                lines.append(
                    f"- carousel `{ex.get('carousel_id')}` slide {ex.get('slide')}: "
                    f"`{ex.get('pinterest_query')}` "
                    f"(SR {float(ex.get('save_rate') or 0):.3f})"
                )
            lines.append("")

    lines.append("## Global query frequency")
    lines.append("")
    for t in (patterns.get("query_frequency") or [])[:25]:
        lines.append(f"- `{t['query']}` — {t['count']}")
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(
    *,
    limit: int,
    dry_run: bool,
    resume: bool,
    db_path: Path,
) -> None:
    print("=" * 64)
    print("  reverse_engineer_queries | Image-to-Query (Pinterest)")
    print("=" * 64)

    conn = connect_db(db_path)
    carousels = fetch_top_carousels(conn, limit)
    conn.close()
    print(f"  Top carousels by Save Rate: {len(carousels)}")

    index = load_folder_index()
    print(f"  Folder index entries: {len(index)}")

    # resolve which carousels have slides
    plan: list[dict[str, Any]] = []
    skipped = 0
    for c in carousels:
        folder = resolve_folder(c["id"], index)
        if folder is None:
            skipped += 1
            continue
        slides = slide_paths_for(folder, SLIDES_PER_CAROUSEL)
        if not slides:
            skipped += 1
            continue
        plan.append({**c, "folder": folder, "slides": slides})

    print(f"  With local slides: {len(plan)}  |  skipped (no folder): {skipped}")
    total_imgs = sum(len(p["slides"]) for p in plan)
    print(f"  Images to analyze: {total_imgs}")
    print()

    if dry_run:
        for i, p in enumerate(plan[:10], 1):
            print(
                f"  [dry {i}/{len(plan)}] {p['id']} SR={p['save_rate']:.4f} "
                f"slides={len(p['slides'])} -> {p['folder'].name}"
            )
        print("\n  Dry-run only. No Gemini calls.")
        return

    api_key = ensure_api_key()
    done = load_checkpoint() if resume else {}
    if resume:
        print(f"  Resume: {len(done)} checkpoint rows loaded")
    elif CHECKPOINT_PATH.is_file():
        # fresh run - archive old checkpoint
        bak = CHECKPOINT_PATH.with_suffix(".jsonl.bak")
        CHECKPOINT_PATH.replace(bak)
        print(f"  Old checkpoint -> {bak.name}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    # seed from checkpoint matching current plan
    plan_keys = {
        f"{p['id']}:{si}"
        for p in plan
        for si in range(1, len(p["slides"]) + 1)
    }
    for key, row in done.items():
        if key in plan_keys and row.get("pinterest_query"):
            results.append(row)

    processed = 0
    errors = 0
    n_car = len(plan)

    for ci, item in enumerate(plan, 1):
        cid = item["id"]
        slides: list[Path] = item["slides"]
        for si, path in enumerate(slides, 1):
            key = f"{cid}:{si}"
            if key in done and done[key].get("pinterest_query"):
                print(
                    f"[{ci}/{n_car}] Карусель {cid} | Слайд {si} -> "
                    f"'{done[key]['pinterest_query']}' "
                    f"[{done[key].get('archetype')}] (cached)"
                )
                continue

            try:
                jpeg = resize_slide_jpeg(path)
                verdict = call_gemini_image_query(api_key, jpeg)
                del jpeg
            except Exception as exc:
                errors += 1
                print(
                    f"[{ci}/{n_car}] Карусель {cid} | Слайд {si} -> FAIL "
                    f"{exc.__class__.__name__}: {exc}"
                )
                pause_jitter()
                continue

            row = {
                "key": key,
                "carousel_id": cid,
                "slide": si,
                "save_rate": item["save_rate"],
                "bookmarks": item["bookmarks"],
                "views": item["views"],
                "niche": item["niche"],
                "folder": str(item["folder"]),
                "image": path.name,
                "pinterest_query": verdict["pinterest_query"],
                "archetype": verdict["archetype"],
                "dominant_objects": verdict["dominant_objects"],
                "ts": datetime.now().isoformat(timespec="seconds"),
            }
            append_checkpoint(row)
            done[key] = row
            results.append(row)
            processed += 1

            print(
                f"[{ci}/{n_car}] Карусель {cid} | Слайд {si} -> "
                f"'{row['pinterest_query']}' [{row['archetype']}]"
            )
            pause_jitter()

        hard_gc()

    # de-dupe by key (prefer latest)
    by_key: dict[str, dict[str, Any]] = {}
    for r in results:
        by_key[str(r.get("key"))] = r
    unique = list(by_key.values())

    patterns = aggregate_results(unique)
    OUT_PATTERNS.write_text(
        json.dumps(patterns, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report(patterns, OUT_REPORT)

    print()
    print("=" * 64)
    print(f"  Done. New Gemini calls: {processed}  |  errors: {errors}")
    print(f"  Samples in library: {len(unique)}")
    print(f"  -> {OUT_PATTERNS}")
    print(f"  -> {OUT_REPORT}")
    print("=" * 64)


def main() -> None:
    # Windows consoles are often cp1251 — keep prints safe
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description="Reverse-engineer Pinterest queries from viral carousel backgrounds"
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_TOP_N,
        help=f"Top-N carousels by save_rate (default {DEFAULT_TOP_N})",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list carousels/slides, no Gemini calls",
    )
    ap.add_argument(
        "--resume",
        action="store_true",
        help="Continue from data/viral_query_checkpoint.jsonl",
    )
    ap.add_argument("--db", type=Path, default=DB_PATH, help="Path to reelfarm_database.db")
    args = ap.parse_args()
    run(
        limit=max(1, int(args.limit)),
        dry_run=bool(args.dry_run),
        resume=bool(args.resume),
        db_path=Path(args.db),
    )


if __name__ == "__main__":
    main()
