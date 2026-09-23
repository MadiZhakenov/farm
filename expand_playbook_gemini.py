#!/usr/bin/env python3
"""
expand_playbook_gemini.py
=========================
Пакетное расширение viral_playbook до ~1000 постов через Gemini 3.1 Flash Lite (Vision).

- Берёт следующие N каруселей из slideshows, которых ещё нет в viral_playbook
- Читает локальные слайды (downloaded_carousels/_all или {id}/)
- Сжимает JPEG в памяти (max 768px, q=80) и шлёт в Gemini Vision
- Пишет результат в БД сразу после каждой карусели (autocommit)

Запуск:
  python expand_playbook_gemini.py
  python expand_playbook_gemini.py --limit 50
  python expand_playbook_gemini.py --dry-run
"""

from __future__ import annotations

import argparse
import base64
import gc
import io
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from PIL import Image

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "reelfarm_database.db"
CAROUSELS_ROOT = ROOT / "downloaded_carousels"
ALL_DIR = CAROUSELS_ROOT / "_all"
ORG_MAP_PATH = CAROUSELS_ROOT / "_organization_map.json"
RENAME_MAP_PATH = CAROUSELS_ROOT / "_rename_map.json"

DEFAULT_MODEL = "gemini-3.1-flash-lite"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{DEFAULT_MODEL}:generateContent"
)

# В slideshows колонка называется saves (= bookmarks)
BOOKMARKS_COL = "saves"
DEFAULT_LIMIT = 850
BOOKMARKS_MIN = 1500
VIEWS_MIN = 25_000

MAX_LONG_SIDE = 768
JPEG_QUALITY = 80
MAX_SLIDES = 12  # защита по токенам / RAM

REQUEST_TIMEOUT = 180.0
MAX_RETRIES = 6
BACKOFF_BASE_SEC = 15.0

HOOK_TYPES = {
    "reframe",
    "identity_callout",
    "named_protocol",
    "checklist",
    "curiosity_gap",
}


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def hard_gc() -> None:
    gc.collect()
    gc.collect()


def ram_mb() -> float:
    try:
        import psutil  # type: ignore

        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def truncate(text: str, n: int = 60) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def ensure_api_key() -> str:
    load_dotenv(ROOT / ".env")
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        raise SystemExit(
            "GEMINI_API_KEY не найден.\n"
            "Создайте .env:\n  GEMINI_API_KEY=your_key_here"
        )
    return key


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

def connect_db(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"Database not found: {path}")
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-2000")
    return conn


def ensure_playbook_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS viral_playbook (
            id TEXT PRIMARY KEY,
            title TEXT,
            niche TEXT,
            views INTEGER,
            bookmarks INTEGER,
            save_rate REAL,
            hook_type TEXT,
            trigger_text TEXT,
            template TEXT,
            raw_json TEXT,
            model TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            real_hook TEXT,
            slides_text_json TEXT,
            real_cta TEXT,
            ocr_done_at TEXT
        )
        """
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(viral_playbook)")}
    for name, typedef in (
        ("real_hook", "TEXT"),
        ("slides_text_json", "TEXT"),
        ("real_cta", "TEXT"),
        ("ocr_done_at", "TEXT"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE viral_playbook ADD COLUMN {name} {typedef}")


def fetch_candidates(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """
    Следующие N результативных каруселей, которых ещё нет в viral_playbook.
    bookmarks в запросе пользователя = saves в БД.
    """
    sql = f"""
        SELECT
            s.id,
            s.title,
            s.niche,
            s.views,
            s.{BOOKMARKS_COL} AS bookmarks
        FROM slideshows s
        WHERE s.id NOT IN (SELECT id FROM viral_playbook)
          AND (s.{BOOKMARKS_COL} >= ? OR s.views >= ?)
          AND COALESCE(s.title, '') != ''
        ORDER BY s.{BOOKMARKS_COL} DESC
        LIMIT ?
    """
    return list(conn.execute(sql, (BOOKMARKS_MIN, VIEWS_MIN, int(limit))))


def save_playbook_row(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO viral_playbook (
            id, title, niche, views, bookmarks, save_rate,
            hook_type, trigger_text, template, raw_json, model,
            real_hook, slides_text_json, real_cta, ocr_done_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title,
            niche=excluded.niche,
            views=excluded.views,
            bookmarks=excluded.bookmarks,
            save_rate=excluded.save_rate,
            hook_type=excluded.hook_type,
            trigger_text=excluded.trigger_text,
            template=excluded.template,
            raw_json=excluded.raw_json,
            model=excluded.model,
            real_hook=excluded.real_hook,
            slides_text_json=excluded.slides_text_json,
            real_cta=excluded.real_cta,
            ocr_done_at=datetime('now')
        """,
        (
            row["id"],
            row.get("title"),
            row.get("niche"),
            row.get("views"),
            row.get("bookmarks"),
            row.get("save_rate"),
            row.get("hook_type"),
            row.get("trigger"),
            row.get("template"),
            row.get("raw_json"),
            row.get("model"),
            row.get("real_hook"),
            row.get("slides_text_json"),
            row.get("real_cta"),
        ),
    )


# ---------------------------------------------------------------------------
# Папки слайдов
# ---------------------------------------------------------------------------

def load_folder_index() -> dict[str, Path]:
    """id → Path к папке со слайдами (1.jpg, 2.jpg, …)."""
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

    # fallback: downloaded_carousels/{id}/
    direct = CAROUSELS_ROOT / carousel_id
    if direct.is_dir() and (direct / "1.jpg").is_file():
        return direct

    # fallback: суффикс id в _all
    suffix = carousel_id[:8]
    if ALL_DIR.is_dir() and len(suffix) >= 8:
        for p in ALL_DIR.iterdir():
            if p.is_dir() and p.name.endswith(suffix) and (p / "1.jpg").is_file():
                return p
    return None


def list_slide_images(folder: Path) -> list[Path]:
    found: dict[int, Path] = {}
    for p in folder.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        if not p.stem.isdigit():
            continue
        if p.stat().st_size <= 0:
            continue
        found[int(p.stem)] = p
    return [found[i] for i in sorted(found)]


# ---------------------------------------------------------------------------
# Image prep (RAM / tokens)
# ---------------------------------------------------------------------------

def resize_slide_jpeg(path: Path, max_side: int = MAX_LONG_SIDE, quality: int = JPEG_QUALITY) -> bytes:
    """Уменьшить слайд в памяти → JPEG bytes (без записи на диск)."""
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
        data = buf.getvalue()
        del img, buf
        return data


def build_inline_parts(slide_paths: list[Path]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for path in slide_paths[:MAX_SLIDES]:
        raw = resize_slide_jpeg(path)
        b64 = base64.b64encode(raw).decode("ascii")
        parts.append(
            {
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": b64,
                }
            }
        )
        del raw, b64
    return parts


# ---------------------------------------------------------------------------
# Gemini Vision
# ---------------------------------------------------------------------------

def build_prompt(title: str, niche: str, n_slides: int) -> str:
    return (
        f"Before you are the slides of a viral social media carousel "
        f"(title: {title}, niche: {niche}). There are {n_slides} slide image(s) "
        f"in order from first to last.\n"
        "Task:\n"
        "1. Extract the clean, readable text of EACH slide in order. "
        "Ignore background noise/posters/mugs.\n"
        "2. Extract real_hook (Slide 1 text) and real_cta (final slide text).\n"
        "3. Classify hook_type (reframe, identity_callout, named_protocol, "
        "checklist, curiosity_gap).\n"
        "4. Formulate the abstract template formula in English.\n"
        "Return STRICT JSON:\n"
        "{\n"
        '  "real_hook": "...",\n'
        '  "slides": ["slide 1 text", "slide 2 text", ...],\n'
        '  "real_cta": "...",\n'
        '  "hook_type": "...",\n'
        '  "trigger": "short 1-sentence reason why it hooked people",\n'
        '  "template": "abstract formula"\n'
        "}"
    )


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No JSON object in Gemini response")
    return json.loads(text[start : end + 1])


def call_gemini_vision(
    api_key: str,
    *,
    title: str,
    niche: str,
    slide_paths: list[Path],
) -> dict[str, Any]:
    prompt = build_prompt(title, niche, len(slide_paths))
    image_parts = build_inline_parts(slide_paths)
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}, *image_parts],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
        },
    }
    # освободить base64 из локальной ссылки после сериализации
    del image_parts

    url = f"{GEMINI_URL}?key={api_key}"
    last_err: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = httpx.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        except httpx.RequestError as exc:
            last_err = exc
            wait = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            print(f"  [net] {exc} — retry in {wait:.0f}s ({attempt}/{MAX_RETRIES})")
            time.sleep(wait)
            continue

        if r.status_code == 429 or r.status_code >= 500:
            wait = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            print(
                f"  [http {r.status_code}] rate/server — "
                f"retry in {wait:.0f}s ({attempt}/{MAX_RETRIES})"
            )
            time.sleep(wait)
            last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:240]}")
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
            # иногда блокировка / пустой кандидат
            block = (data.get("promptFeedback") or {}).get("blockReason")
            raise RuntimeError(
                f"Gemini empty response"
                + (f" (blocked: {block})" if block else f": {json.dumps(data)[:300]}")
            )
        return _extract_json(text)

    raise RuntimeError(f"Gemini failed after retries: {last_err}")


def normalize_result(parsed: dict[str, Any], n_slides: int) -> dict[str, Any]:
    slides_raw = parsed.get("slides") or []
    if not isinstance(slides_raw, list):
        slides_raw = []
    slides: list[str] = []
    for s in slides_raw:
        t = re.sub(r"\s+", " ", str(s or "").strip())
        if t:
            slides.append(t[:500])

    real_hook = re.sub(r"\s+", " ", str(parsed.get("real_hook") or "").strip())
    real_cta = re.sub(r"\s+", " ", str(parsed.get("real_cta") or "").strip())
    if not real_hook and slides:
        real_hook = slides[0]
    if not real_cta and slides:
        real_cta = slides[-1]
    if not slides and real_hook:
        slides = [real_hook]
        if real_cta and real_cta != real_hook:
            slides.append(real_cta)

    hook_type = str(parsed.get("hook_type") or "curiosity_gap").strip().lower()
    hook_type = hook_type.replace(" ", "_").replace("-", "_")
    if hook_type not in HOOK_TYPES:
        # мягкий маппинг частых синонимов
        aliases = {
            "identity": "identity_callout",
            "callout": "identity_callout",
            "protocol": "named_protocol",
            "named_rule": "named_protocol",
            "list": "checklist",
            "curiosity": "curiosity_gap",
            "gap": "curiosity_gap",
        }
        hook_type = aliases.get(hook_type, "curiosity_gap")

    trigger = re.sub(r"\s+", " ", str(parsed.get("trigger") or "").strip())[:300]
    template = re.sub(r"\s+", " ", str(parsed.get("template") or "").strip())[:400]

    if len(slides) < 1:
        raise ValueError("No slide texts extracted")
    if n_slides >= 2 and len(slides) < 2:
        # не фатально, но подозрительно — оставим как есть
        pass

    return {
        "real_hook": real_hook[:400],
        "slides": slides,
        "real_cta": real_cta[:400],
        "hook_type": hook_type,
        "trigger": trigger,
        "template": template,
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def process_one(
    *,
    api_key: str,
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    folder: Path,
    slide_paths: list[Path],
) -> dict[str, Any]:
    title = str(row["title"] or "")
    niche = str(row["niche"] or "")
    views = int(row["views"] or 0)
    bookmarks = int(row["bookmarks"] or 0)
    save_rate = (bookmarks / views) if views > 0 else 0.0

    parsed = call_gemini_vision(
        api_key,
        title=title,
        niche=niche,
        slide_paths=slide_paths,
    )
    norm = normalize_result(parsed, len(slide_paths))

    out = {
        "id": str(row["id"]),
        "title": title,
        "niche": niche,
        "views": views,
        "bookmarks": bookmarks,
        "save_rate": round(save_rate, 6),
        "hook_type": norm["hook_type"],
        "trigger": norm["trigger"],
        "template": norm["template"],
        "raw_json": json.dumps(parsed, ensure_ascii=False),
        "model": DEFAULT_MODEL,
        "real_hook": norm["real_hook"],
        "slides_text_json": json.dumps(norm["slides"], ensure_ascii=False),
        "real_cta": norm["real_cta"],
    }
    save_playbook_row(conn, out)
    return out


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Expand viral_playbook via Gemini Vision"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"How many carousels to process (default {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list candidates / folders, no API calls",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help="Path to reelfarm_database.db",
    )
    args = parser.parse_args()
    limit = max(1, int(args.limit))

    api_key = "" if args.dry_run else ensure_api_key()
    conn = connect_db(args.db)
    ensure_playbook_schema(conn)

    already = int(conn.execute("SELECT COUNT(*) FROM viral_playbook").fetchone()[0])
    print("=" * 64)
    print("  expand_playbook_gemini.py · Gemini Vision")
    print(f"  DB:    {args.db}")
    print(f"  Model: {DEFAULT_MODEL}")
    print(f"  Already in playbook: {already}")
    print(f"  Target batch:        {limit}")
    print(f"  Filter: saves>={BOOKMARKS_MIN} OR views>={VIEWS_MIN}")
    print(f"  RAM now: {ram_mb():.0f} MB")
    print("=" * 64)

    print("\n[INDEX] Loading folder map…")
    folder_index = load_folder_index()
    print(f"[INDEX] Mapped folders: {len(folder_index)}")

    candidates = fetch_candidates(conn, limit)
    print(f"[SELECT] Candidates: {len(candidates)}")
    if not candidates:
        print("Nothing to do — no eligible carousels left.")
        return

    ok = 0
    skipped_no_folder = 0
    skipped_no_slides = 0
    failed = 0

    for i, row in enumerate(candidates, start=1):
        cid = str(row["id"])
        bookmarks = int(row["bookmarks"] or 0)
        t0 = time.perf_counter()

        folder = resolve_folder(cid, folder_index)
        if folder is None:
            skipped_no_folder += 1
            print(f"[{i}/{len(candidates)}] ID: {cid} | SKIP: no local folder")
            continue

        slides = list_slide_images(folder)
        if not slides:
            skipped_no_slides += 1
            print(f"[{i}/{len(candidates)}] ID: {cid} | SKIP: no slide images in {folder.name}")
            continue

        if args.dry_run:
            print(
                f"[{i}/{len(candidates)}] ID: {cid} | "
                f"folder={folder.name} | slides={len(slides)} | "
                f"saves={bookmarks:,}"
            )
            continue

        try:
            result = process_one(
                api_key=api_key,
                conn=conn,
                row=row,
                folder=folder,
                slide_paths=slides,
            )
            elapsed = time.perf_counter() - t0
            ok += 1
            print(
                f"[{i}/{len(candidates)}] ID: {cid} | "
                f"Хук: '{truncate(result['real_hook'])}' | "
                f"Слайдов: {len(json.loads(result['slides_text_json']))} | "
                f"Сохранений: {bookmarks:,} | "
                f"Время: {elapsed:.1f} с"
            )
        except Exception as exc:
            failed += 1
            elapsed = time.perf_counter() - t0
            print(
                f"[{i}/{len(candidates)}] ID: {cid} | "
                f"FAIL ({elapsed:.1f}s): {exc}"
            )

        hard_gc()

    total_now = int(conn.execute("SELECT COUNT(*) FROM viral_playbook").fetchone()[0])
    print("\n" + "=" * 64)
    print(f"  Done. OK={ok}  fail={failed}  "
          f"no_folder={skipped_no_folder}  no_slides={skipped_no_slides}")
    print(f"  viral_playbook size: {already} → {total_now}")
    print(f"  RAM end: {ram_mb():.0f} MB")
    print("=" * 64)
    conn.close()


if __name__ == "__main__":
    main()
