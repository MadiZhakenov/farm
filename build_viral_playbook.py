#!/usr/bin/env python3
"""
build_viral_playbook.py
=======================
Отбор «Золотого фонда» каруселей из reelfarm_database.db
и оцифровка хуков через локальную Ollama (qwen2.5:7b).

Ограничения железа (8 ГБ RAM / 8 ГБ VRAM):
  - num_ctx=2048, num_predict=350
  - одна карусель за раз, без fetchall() на всю БД
  - gc.collect() после каждого шага

Запуск:
  python build_viral_playbook.py
  python build_viral_playbook.py --limit 20
  python build_viral_playbook.py --resume
"""

from __future__ import annotations

import argparse
import gc
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import httpx

# ---------------------------------------------------------------------------
# Константы (жёсткие лимиты под 8 ГБ)
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "reelfarm_database.db"

OLLAMA_HOST = "http://127.0.0.1:11434"
MODEL = "qwen2.5:7b"
NUM_CTX = 2048
NUM_PREDICT = 350
REQUEST_TIMEOUT = 120.0

TOP_N = 150
# Двухконтурный фильтр «золотого фонда»
SAVES_HARD_MIN = 50_000          # контур A: абсолютные хиты
VIEWS_RATE_MIN = 25_000          # контур B: мин. просмотры (анти-шум)
SAVES_RATE_MIN = 1_500           # контур B: мин. сохранения
SAVE_RATE_MIN = 0.05             # контур B: save-rate ≥ 5%

# В схеме БД колонка называется saves (= bookmarks / сохранения)
BOOKMARKS_COL = "saves"

GOLD_WHERE = f"""
(
    {BOOKMARKS_COL} >= ?
    OR (
        views >= ?
        AND {BOOKMARKS_COL} >= ?
        AND CAST({BOOKMARKS_COL} AS FLOAT) / NULLIF(views, 0) >= ?
    )
)
AND COALESCE(title, '') != ''
"""
GOLD_PARAMS = (SAVES_HARD_MIN, VIEWS_RATE_MIN, SAVES_RATE_MIN, SAVE_RATE_MIN)


# ---------------------------------------------------------------------------
# Память
# ---------------------------------------------------------------------------

def ram_mb() -> float:
    """Текущий RSS процесса, МБ."""
    try:
        import psutil  # type: ignore

        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        GetCurrentProcess = ctypes.windll.kernel32.GetCurrentProcess
        GetProcessMemoryInfo = ctypes.windll.psapi.GetProcessMemoryInfo
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        if GetProcessMemoryInfo(GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return pmc.WorkingSetSize / (1024 * 1024)
    except Exception:
        pass
    return -1.0


def vram_mb() -> tuple[float, float]:
    """(used_mb, total_mb) через nvidia-smi; (-1,-1) если недоступно."""
    import shutil
    import subprocess

    smi = shutil.which("nvidia-smi")
    if not smi:
        for p in (
            Path(r"C:\Windows\System32\nvidia-smi.exe"),
            Path(r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"),
        ):
            if p.is_file():
                smi = str(p)
                break
    if not smi:
        return -1.0, -1.0
    try:
        out = subprocess.check_output(
            [
                smi,
                "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        )
        line = out.strip().splitlines()[0]
        used_s, total_s = [x.strip() for x in line.split(",")]
        return float(used_s), float(total_s)
    except Exception:
        return -1.0, -1.0


def mem_tag() -> str:
    ram = ram_mb()
    vu, vt = vram_mb()
    parts: list[str] = []
    if ram >= 0:
        parts.append(f"RAM {ram:.0f}MB")
    if vu >= 0:
        parts.append(f"VRAM {vu:.0f}/{vt:.0f}MB")
    return " | ".join(parts) if parts else "mem n/a"


def hard_gc() -> None:
    gc.collect()
    gc.collect()


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

def connect_db(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"Database not found: {path}")
    # isolation_level=None → autocommit (прогресс не теряется)
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-2000")  # ~2 МБ page cache
    return conn


def ensure_playbook_table(conn: sqlite3.Connection) -> None:
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
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_viral_playbook_bookmarks "
        "ON viral_playbook(bookmarks DESC)"
    )


def count_all_slideshows(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM slideshows").fetchone()
    return int(row["n"] if row else 0)


def count_gold_fund(conn: sqlite3.Connection) -> int:
    """Сколько каруселей проходит строгий двухконтурный фильтр (без LIMIT)."""
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM slideshows WHERE {GOLD_WHERE}",
        GOLD_PARAMS,
    ).fetchone()
    return int(row["n"] if row else 0)


def iter_gold_ids(conn: sqlite3.Connection, limit: int) -> Iterator[str]:
    """
    Стримит только id золотого фонда (лёгкий курсор, без fetchall на всю БД).
    bookmarks в формуле пользователя = колонка saves в reelfarm.
    """
    sql = f"""
        SELECT id
        FROM slideshows
        WHERE {GOLD_WHERE}
        ORDER BY {BOOKMARKS_COL} DESC
        LIMIT ?
    """
    cur = conn.execute(sql, (*GOLD_PARAMS, limit))
    while True:
        row = cur.fetchone()
        if row is None:
            break
        yield str(row["id"])
        del row


def fetch_one_carousel(conn: sqlite3.Connection, carousel_id: str) -> dict[str, Any] | None:
    cur = conn.execute(
        f"""
        SELECT id, title, niche, views, {BOOKMARKS_COL} AS bookmarks,
               product_medium, audience_region
        FROM slideshows
        WHERE id = ?
        LIMIT 1
        """,
        (carousel_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    d = {k: row[k] for k in row.keys()}
    del row
    return d


def already_done(conn: sqlite3.Connection, carousel_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM viral_playbook WHERE id = ? LIMIT 1",
        (carousel_id,),
    ).fetchone()
    return row is not None


def save_playbook_row(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO viral_playbook (
            id, title, niche, views, bookmarks, save_rate,
            hook_type, trigger_text, template, raw_json, model
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            created_at=datetime('now')
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
        ),
    )


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

def ollama_alive() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


def build_prompt(title: str, niche: str) -> str:
    # Короткий промпт — укладываемся в num_ctx=2048
    title = (title or "")[:180].replace('"', "'")
    niche = (niche or "general")[:60].replace('"', "'")
    return (
        f"Перед тобой заголовок вирусной карусели с 50k+ сохранений: '{title}'. "
        f"Ниша: {niche}. "
        "Определи: "
        "1. Тип хука (pain_point, mistake, curiosity_gap, listicle, transformation). "
        "2. Почему он зацепил людей (в 1 коротком предложении). "
        "3. Формулу шаблона на английском (например: 'The [time] rule that cured my [problem]'). "
        'Верни строго JSON: {"hook_type": "...", "trigger": "...", "template": "..."}'
    )


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


ALLOWED_HOOKS = {
    "pain_point",
    "mistake",
    "curiosity_gap",
    "listicle",
    "transformation",
}


def analyze_with_ollama(title: str, niche: str) -> dict[str, str]:
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You output only valid compact JSON. No markdown.",
            },
            {"role": "user", "content": build_prompt(title, niche)},
        ],
        "stream": False,
        "format": "json",
        "options": {
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
            "temperature": 0.3,
        },
    }
    r = httpx.post(
        f"{OLLAMA_HOST}/api/chat",
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:200]}")

    body = r.json()
    content = ((body.get("message") or {}).get("content")) or ""
    # освободить большой ответ ASAP
    del body
    del r

    data = _extract_json(content)
    del content

    hook = str(data.get("hook_type") or "").strip().lower().replace(" ", "_")
    if hook not in ALLOWED_HOOKS:
        # мягкая нормализация
        for key in ALLOWED_HOOKS:
            if key in hook or hook in key:
                hook = key
                break
        else:
            hook = "curiosity_gap"

    trigger = str(data.get("trigger") or data.get("why") or "").strip()[:240]
    template = str(data.get("template") or data.get("formula") or "").strip()[:240]
    if not template:
        template = "The [X] that changed my [Y]"

    return {
        "hook_type": hook,
        "trigger": trigger or "Strong save-bait hook",
        "template": template,
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def short_title(text: str, n: int = 48) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t if len(t) <= n else t[: n - 1] + "…"


def run(*, limit: int, resume: bool, db_path: Path) -> int:
    print("=" * 64)
    print("  Viral Playbook Builder")
    print(f"  DB:    {db_path}")
    print(f"  Model: {MODEL}  num_ctx={NUM_CTX}  num_predict={NUM_PREDICT}")
    print(f"  Top:   {limit}  |  {mem_tag()}")
    print("=" * 64)

    if not ollama_alive():
        print("\n[FAIL] Ollama ne otvechaet. Zapustite: ollama serve")
        return 1

    conn = connect_db(db_path)
    ensure_playbook_table(conn)

    total_db = count_all_slideshows(conn)
    gold_total = count_gold_fund(conn)
    print(
        f"\n[FILTER] Strogii otbor: {gold_total:,} karuseley "
        f"iz {total_db:,} zapisey "
        f"(A: saves>={SAVES_HARD_MIN:,} | "
        f"B: views>={VIEWS_RATE_MIN:,} & saves>={SAVES_RATE_MIN:,} "
        f"& rate>={SAVE_RATE_MIN:.0%})"
    )
    hard_gc()

    # Собираем только список id (строки ~20 байт × 150 — копейки)
    ids: list[str] = []
    for cid in iter_gold_ids(conn, limit):
        ids.append(cid)
    hard_gc()

    total = len(ids)
    if total == 0:
        print("[WARN] Zolotoy fond pust (0 ryadov).")
        conn.close()
        return 0

    print(
        f"[OK] V rabotu: TOP-{total} iz {gold_total:,} "
        f"(ORDER BY saves DESC). Start analiza...\n"
    )

    done = 0
    skipped = 0
    failed = 0
    t0 = time.perf_counter()

    for i, cid in enumerate(ids, start=1):
        if resume and already_done(conn, cid):
            skipped += 1
            print(f"[{i}/{total}] SKIP (uzhe v playbook) id={cid}")
            hard_gc()
            continue

        car = fetch_one_carousel(conn, cid)
        if not car:
            failed += 1
            hard_gc()
            continue

        title = str(car.get("title") or "")
        niche = str(car.get("niche") or "")
        views = int(car.get("views") or 0)
        bookmarks = int(car.get("bookmarks") or 0)
        save_rate = (bookmarks / views) if views > 0 else 0.0

        try:
            analysis = analyze_with_ollama(title, niche)
        except Exception as exc:
            failed += 1
            print(
                f"[{i}/{total}] FAIL {short_title(title)} | {exc} | {mem_tag()}"
            )
            del car
            hard_gc()
            # небольшая пауза при ошибке (модель могла перегрузиться)
            time.sleep(1.0)
            continue

        row = {
            "id": cid,
            "title": title,
            "niche": niche,
            "views": views,
            "bookmarks": bookmarks,
            "save_rate": round(save_rate, 6),
            "hook_type": analysis["hook_type"],
            "trigger": analysis["trigger"],
            "template": analysis["template"],
            "raw_json": json.dumps(analysis, ensure_ascii=False),
            "model": MODEL,
        }
        save_playbook_row(conn, row)
        done += 1

        print(
            f"[{i}/{total}] {short_title(title)} | "
            f"Sohraneniy: {bookmarks:,} | "
            f"Shablon: {short_title(analysis['template'], 56)} | "
            f"{mem_tag()}"
        )

        # жёсткая очистка
        del analysis, row, car, title, niche
        hard_gc()

        # лёгкий throttle, чтобы VRAM не копила очередь
        if i % 10 == 0:
            time.sleep(0.3)

    elapsed = time.perf_counter() - t0
    print("\n" + "-" * 64)
    print(
        f"Done: {done}  skipped: {skipped}  failed: {failed}  "
        f"elapsed: {elapsed:.1f}s  |  {mem_tag()}"
    )
    print(f"Table: viral_playbook  in  {db_path}")
    print("-" * 64)

    conn.close()
    hard_gc()
    return 0 if failed == 0 or done > 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Build viral_playbook from reelfarm DB")
    ap.add_argument("--limit", type=int, default=TOP_N, help=f"Top N (default {TOP_N})")
    ap.add_argument(
        "--resume",
        action="store_true",
        help="Skip ids already present in viral_playbook",
    )
    ap.add_argument("--db", type=Path, default=DB_PATH, help="Path to reelfarm_database.db")
    args = ap.parse_args()
    limit = max(1, min(int(args.limit), 500))
    return run(limit=limit, resume=bool(args.resume), db_path=args.db)


if __name__ == "__main__":
    # Windows console safety
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
