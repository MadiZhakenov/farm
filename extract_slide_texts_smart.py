#!/usr/bin/env python3
"""
extract_slide_texts_smart.py
============================
EasyOCR + Ollama (qwen2.5:7b) → чистые тексты слайдов для viral_playbook.

Жёсткие лимиты (8 ГБ RAM / 8 ГБ VRAM):
  - EasyOCR на CPU (VRAM оставляем Ollama)
  - Ollama: num_ctx=1024, num_predict=120
  - строго последовательно: OCR → ИИ → следующий слайд
  - gc.collect() после каждого слайда

Запуск:
  python extract_slide_texts_smart.py
  python extract_slide_texts_smart.py --limit 5
  python extract_slide_texts_smart.py --resume
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
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "reelfarm_database.db"
ALL_DIR = ROOT / "downloaded_carousels" / "_all"

OLLAMA_HOST = "http://127.0.0.1:11434"
MODEL = "qwen2.5:7b"
NUM_CTX = 1024
NUM_PREDICT = 120
OLLAMA_TIMEOUT = 90.0

OCR_LANGS = ["en"]
OCR_MAX_SIDE = 1280  # даунскейл до OCR — экономия RAM
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

MIN_RAW_LEN = 3


# ---------------------------------------------------------------------------
# Память
# ---------------------------------------------------------------------------

def hard_gc() -> None:
    gc.collect()
    gc.collect()


def ram_mb() -> float:
    try:
        import psutil  # type: ignore

        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        return -1.0


def vram_mb() -> tuple[float, float]:
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
        used_s, total_s = [x.strip() for x in out.strip().splitlines()[0].split(",")]
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


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

def connect_db(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"Database not found: {path}")
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-2000")
    return conn


def ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(viral_playbook)")}
    for name, typedef in (
        ("real_hook", "TEXT"),
        ("slides_text_json", "TEXT"),
        ("real_cta", "TEXT"),
        ("ocr_done_at", "TEXT"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE viral_playbook ADD COLUMN {name} {typedef}")


def iter_playbook_rows(conn: sqlite3.Connection, limit: int | None) -> list[sqlite3.Row]:
    sql = """
        SELECT id, title, bookmarks, real_hook, slides_text_json
        FROM viral_playbook
        ORDER BY bookmarks DESC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    # LIMIT маленький (≤150) — безопасно
    return list(conn.execute(sql))


def already_ocr_done(row: sqlite3.Row) -> bool:
    slides = row["slides_text_json"]
    hook = row["real_hook"]
    if not slides:
        return False
    try:
        arr = json.loads(slides)
    except json.JSONDecodeError:
        return False
    return isinstance(arr, list) and len(arr) > 0 and bool(hook)


def save_carousel_texts(
    conn: sqlite3.Connection,
    carousel_id: str,
    cleaned: list[str],
) -> None:
    real_hook = cleaned[0] if cleaned else ""
    real_cta = cleaned[-1] if cleaned else ""
    # NONE → пустая строка в JSON, но храним как есть для прозрачности
    payload = json.dumps(cleaned, ensure_ascii=False)
    conn.execute(
        """
        UPDATE viral_playbook
        SET real_hook = ?,
            slides_text_json = ?,
            real_cta = ?,
            ocr_done_at = datetime('now')
        WHERE id = ?
        """,
        (real_hook, payload, real_cta, carousel_id),
    )


# ---------------------------------------------------------------------------
# Папки слайдов
# ---------------------------------------------------------------------------

def build_id_to_folder(all_dir: Path, needed_ids: set[str]) -> dict[str, Path]:
    """Сканирует meta.json только пока не найдёт все нужные id."""
    index: dict[str, Path] = {}
    if not all_dir.is_dir():
        return index
    for p in all_dir.iterdir():
        if len(index) >= len(needed_ids):
            break
        if not p.is_dir():
            continue
        meta = p / "meta.json"
        if not meta.is_file():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        cid = str(data.get("id") or data.get("original_id") or "").strip()
        if cid in needed_ids and cid not in index:
            index[cid] = p
        del data
    return index


def list_slide_images(folder: Path) -> list[Path]:
    found: dict[int, Path] = {}
    if not folder.is_dir():
        return []
    for p in folder.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        if not p.stem.isdigit():
            continue
        if p.stat().st_size <= 0:
            continue
        found[int(p.stem)] = p
    return [found[i] for i in sorted(found)]


# ---------------------------------------------------------------------------
# EasyOCR
# ---------------------------------------------------------------------------

class OcrEngine:
    """Ленивая инициализация EasyOCR на CPU."""

    def __init__(self) -> None:
        self._reader: Any = None

    def _ensure(self) -> Any:
        if self._reader is not None:
            return self._reader
        print("[OCR] Loading EasyOCR (CPU)…")
        import easyocr

        # gpu=False — VRAM только для Ollama
        self._reader = easyocr.Reader(OCR_LANGS, gpu=False, verbose=False)
        hard_gc()
        print(f"[OCR] Ready | {mem_tag()}")
        return self._reader

    def read_raw(self, image_path: Path) -> str:
        from PIL import Image
        import numpy as np

        reader = self._ensure()
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        scale = min(1.0, OCR_MAX_SIDE / max(w, h))
        if scale < 1.0:
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.BILINEAR,
            )
        arr = np.asarray(img)
        del img
        # detail=0 → только строки текста
        lines = reader.readtext(arr, detail=0, paragraph=True)
        del arr
        if not lines:
            return ""
        if isinstance(lines, str):
            raw = lines
        else:
            raw = " ".join(str(x).strip() for x in lines if str(x).strip())
        raw = re.sub(r"\s+", " ", raw).strip()
        return raw


# ---------------------------------------------------------------------------
# Ollama cleanup
# ---------------------------------------------------------------------------

def ollama_alive() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


def build_cleanup_prompt(raw_text: str) -> str:
    # Короткие куски — num_ctx=1024
    clipped = (raw_text or "")[:700]
    return (
        "Перед тобой сырой OCR-текст со слайда вирусного TikTok:\n"
        "---\n"
        f"{clipped}\n"
        "---\n"
        "На фото может быть фоновый шум: надписи на заднем плане, плакатах, "
        "кружках или рукописные заметки.\n"
        "Твоя задача:\n"
        "1. Выдели только ГЛАВНЫЙ читаемый текст/посыл этого слайда.\n"
        "2. Исправь опечатки OCR и склей разорванные строки.\n"
        "3. Удали весь фоновый мусор.\n"
        "Верни ТОЛЬКО очищенную фразу на английском (без пояснений и кавычек). "
        "Если текста нет — верни NONE."
    )


def clean_with_ollama(raw_text: str) -> str:
    payload = {
        "model": MODEL,
        "prompt": build_cleanup_prompt(raw_text),
        "stream": False,
        "options": {
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
            "temperature": 0.1,
        },
    }
    r = httpx.post(
        f"{OLLAMA_HOST}/api/generate",
        json=payload,
        timeout=OLLAMA_TIMEOUT,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:180]}")
    data = r.json()
    text = str(data.get("response") or "").strip()
    del data, r, payload

    # снять случайные кавычки / markdown
    text = text.strip().strip("`").strip()
    if text.lower().startswith("none") and len(text) <= 8:
        return "NONE"
    # первая строка, если модель разговорилась
    first = text.splitlines()[0].strip().strip('"').strip("'")
    if not first:
        return "NONE"
    if first.upper() == "NONE":
        return "NONE"
    return first[:400]


def short(s: str, n: int = 90) -> str:
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_carousel(
    *,
    conn: sqlite3.Connection,
    ocr: OcrEngine,
    carousel_id: str,
    folder: Path,
    index: int,
    total: int,
) -> bool:
    slides = list_slide_images(folder)
    if not slides:
        print(f"[Карусель {index}/{total}] NO SLIDES in {folder.name}")
        return False

    cleaned: list[str] = []
    title_hint = folder.name[:60]

    for si, path in enumerate(slides, start=1):
        print(f"[Карусель {index}/{total} | Слайд {si}/{len(slides)}] {title_hint}")

        try:
            raw = ocr.read_raw(path)
        except Exception as exc:
            print(f"  OCR FAIL: {exc}")
            cleaned.append("NONE")
            hard_gc()
            continue

        if len(raw) < MIN_RAW_LEN:
            print(f'  Сырой OCR: "(пусто)"')
            print(f'  Чистый ИИ: "NONE"')
            cleaned.append("NONE")
            hard_gc()
            continue

        print(f'  Сырой OCR: "{short(raw)}"')
        try:
            clean = clean_with_ollama(raw)
        except Exception as exc:
            print(f"  Ollama FAIL: {exc} → оставляем сырой укороченный")
            clean = short(raw, 200) or "NONE"

        print(f'  Чистый ИИ: "{short(clean)}"  |  {mem_tag()}')
        cleaned.append(clean)

        del raw
        hard_gc()

    save_carousel_texts(conn, carousel_id, cleaned)
    print(
        f"  → saved: hook={short(cleaned[0], 50)!r}  "
        f"cta={short(cleaned[-1], 50)!r}  slides={len(cleaned)}"
    )
    del cleaned, slides
    hard_gc()
    return True


def run(*, limit: int | None, resume: bool, db_path: Path, all_dir: Path) -> int:
    print("=" * 64)
    print("  Smart slide text extraction  (EasyOCR + Ollama)")
    print(f"  DB:    {db_path}")
    print(f"  Slides:{all_dir}")
    print(f"  Model: {MODEL}  num_ctx={NUM_CTX}  num_predict={NUM_PREDICT}")
    print(f"  {mem_tag()}")
    print("=" * 64)

    if not ollama_alive():
        print("\n[FAIL] Ollama ne otvechaet. Zapustite: ollama serve")
        return 1
    if not all_dir.is_dir():
        print(f"\n[FAIL] Net papki so slaydami: {all_dir}")
        return 1

    conn = connect_db(db_path)
    ensure_columns(conn)

    rows = iter_playbook_rows(conn, limit)
    if resume:
        rows = [r for r in rows if not already_ocr_done(r)]

    if not rows:
        print("\n[OK] Nechego delat (vse uzhe gotovo ili pustoy playbook).")
        conn.close()
        return 0

    needed = {str(r["id"]) for r in rows}
    print(f"\n[INDEX] Ishchu papki dlya {len(needed)} karuseley…")
    id_to_folder = build_id_to_folder(all_dir, needed)
    print(f"[INDEX] Naydeno papok: {len(id_to_folder)}/{len(needed)} | {mem_tag()}")
    hard_gc()

    ocr = OcrEngine()
    total = len(rows)
    done = 0
    skipped_no_folder = 0
    failed = 0
    t0 = time.perf_counter()

    for i, row in enumerate(rows, start=1):
        cid = str(row["id"])
        folder = id_to_folder.get(cid)
        if folder is None:
            skipped_no_folder += 1
            print(f"[Карусель {i}/{total}] NO FOLDER id={cid}")
            continue
        try:
            ok = process_carousel(
                conn=conn,
                ocr=ocr,
                carousel_id=cid,
                folder=folder,
                index=i,
                total=total,
            )
            if ok:
                done += 1
            else:
                failed += 1
        except Exception as exc:
            failed += 1
            print(f"[Карусель {i}/{total}] FAIL {cid}: {exc}")
            hard_gc()

    elapsed = time.perf_counter() - t0
    print("\n" + "-" * 64)
    print(
        f"Done: {done}  no_folder: {skipped_no_folder}  failed: {failed}  "
        f"elapsed: {elapsed:.1f}s  |  {mem_tag()}"
    )
    print("-" * 64)

    # освободить OCR
    ocr._reader = None
    hard_gc()
    conn.close()
    return 0 if failed == 0 or done > 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="OCR+LLM slide text extraction")
    ap.add_argument("--limit", type=int, default=None, help="Only first N playbook rows")
    ap.add_argument("--resume", action="store_true", help="Skip already filled rows")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--slides-dir", type=Path, default=ALL_DIR)
    args = ap.parse_args()
    return run(
        limit=args.limit,
        resume=bool(args.resume),
        db_path=args.db,
        all_dir=args.slides_dir,
    )


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
