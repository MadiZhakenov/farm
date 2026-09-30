#!/usr/bin/env python3
"""
PhotoVault — библиотека одобренных фото + перманентный blacklist пинов.

SQLite: data/photo_vault.db
  - approved_photos (превью + метаданные)
  - blacklisted_pins (вечный бан pin_id)

Превью: data/vault_thumbs/{pin_id}.jpg (длинная сторона 120px).
In-memory set для O(1) is_blacklisted().
"""

from __future__ import annotations

import io
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "photo_vault.db"
DEFAULT_THUMBS = ROOT / "data" / "vault_thumbs"
THUMB_MAX = 240  # длинная сторона превью (для читаемой галереи)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approved_photos (
    pin_id TEXT PRIMARY KEY,
    image_url TEXT,
    local_thumb_path TEXT,
    query TEXT,
    tags TEXT,
    added_at TEXT,
    status TEXT DEFAULT 'approved'
);

CREATE TABLE IF NOT EXISTS blacklisted_pins (
    pin_id TEXT PRIMARY KEY,
    blocked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_approved_status ON approved_photos(status);
CREATE INDEX IF NOT EXISTS idx_approved_query ON approved_photos(query);

-- Какое фото стоит в какой карусели/слайде (одно фото — одна карусель на серию)
CREATE TABLE IF NOT EXISTS used_photos (
    carousel TEXT NOT NULL,
    slide INTEGER NOT NULL,
    pin_id TEXT,
    fp TEXT,
    used_at TEXT,
    PRIMARY KEY (carousel, slide)
);
CREATE INDEX IF NOT EXISTS idx_used_pin ON used_photos(pin_id);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_pin_id(pin_id: Any) -> str:
    return str(pin_id or "").strip()


class PhotoVault:
    """Менеджер библиотеки фото + blacklist (thread-safe)."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        thumbs_dir: Path | str | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB
        self.thumbs_dir = Path(thumbs_dir) if thumbs_dir else DEFAULT_THUMBS
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._blacklist: set[str] = set()
        self._ensure_schema()
        self._reload_blacklist()

    # -- DB -----------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.executescript(_SCHEMA)
                cols = {
                    str(r["name"])
                    for r in conn.execute("PRAGMA table_info(approved_photos)")
                }
                if "fp" not in cols:
                    # отпечаток картинки (dHash hex) — ловит перезаливы пина
                    conn.execute("ALTER TABLE approved_photos ADD COLUMN fp TEXT")
                conn.commit()

    def _reload_blacklist(self) -> None:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT pin_id FROM blacklisted_pins"
                ).fetchall()
            self._blacklist = {_as_pin_id(r["pin_id"]) for r in rows if r["pin_id"]}

    # -- blacklist ----------------------------------------------------------

    def is_blacklisted(self, pin_id: Any) -> bool:
        """O(1) проверка — забаненные пины никогда не качаем."""
        pid = _as_pin_id(pin_id)
        if not pid:
            return False
        return pid in self._blacklist

    def blacklist_pin(self, pin_id: Any) -> bool:
        """
        Перманентный бан: запись в blacklisted_pins, удаление из approved,
        обновление in-memory set. Thumb файл удаляется.
        """
        pid = _as_pin_id(pin_id)
        if not pid:
            return False
        with self._lock:
            thumb_path: Path | None = None
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT local_thumb_path FROM approved_photos WHERE pin_id=?",
                    (pid,),
                ).fetchone()
                if row and row["local_thumb_path"]:
                    thumb_path = Path(str(row["local_thumb_path"]))
                conn.execute(
                    "INSERT OR REPLACE INTO blacklisted_pins(pin_id, blocked_at) "
                    "VALUES (?, ?)",
                    (pid, _utc_now()),
                )
                conn.execute(
                    "DELETE FROM approved_photos WHERE pin_id=?", (pid,)
                )
                conn.commit()
            self._blacklist.add(pid)
            if thumb_path and thumb_path.is_file():
                try:
                    thumb_path.unlink()
                except OSError:
                    pass
            # default thumb location
            fallback = self.thumbs_dir / f"{pid}.jpg"
            if fallback.is_file() and fallback != thumb_path:
                try:
                    fallback.unlink()
                except OSError:
                    pass
        return True

    def unblacklist_pin(self, pin_id: Any) -> bool:
        """Снять бан (редко нужно)."""
        pid = _as_pin_id(pin_id)
        if not pid:
            return False
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM blacklisted_pins WHERE pin_id=?", (pid,)
                )
                conn.commit()
            self._blacklist.discard(pid)
        return True

    # -- approved library ---------------------------------------------------

    def _make_thumb(
        self, image: Image.Image | bytes | Path | str, pin_id: str
    ) -> Path:
        """Сохранить JPEG-превью (длинная сторона THUMB_MAX px)."""
        if isinstance(image, (bytes, bytearray)):
            img = Image.open(io.BytesIO(image)).convert("RGB")
        elif isinstance(image, Image.Image):
            img = image.convert("RGB")
        else:
            img = Image.open(str(image)).convert("RGB")

        w, h = img.size
        if max(w, h) > THUMB_MAX:
            if w >= h:
                nh = max(1, int(round(h * THUMB_MAX / w)))
                img = img.resize((THUMB_MAX, nh), Image.Resampling.LANCZOS)
            else:
                nw = max(1, int(round(w * THUMB_MAX / h)))
                img = img.resize((nw, THUMB_MAX), Image.Resampling.LANCZOS)

        out = self.thumbs_dir / f"{pin_id}.jpg"
        img.save(out, format="JPEG", quality=82, optimize=True)
        return out

    def add_approved_photo(
        self,
        pin_id: Any,
        image_bytes_or_path: Image.Image | bytes | Path | str | None,
        query: str = "",
        tags: str | list[str] | None = None,
        *,
        image_url: str = "",
        status: str = "approved",
    ) -> dict[str, Any] | None:
        """
        Сохранить превью + запись в approved_photos.
        Если pin в blacklist — отказ (None).
        """
        pid = _as_pin_id(pin_id)
        if not pid:
            return None
        if self.is_blacklisted(pid):
            return None

        if isinstance(tags, (list, tuple)):
            tags_s = ", ".join(str(t).strip() for t in tags if str(t).strip())
        else:
            tags_s = str(tags or "").strip()

        thumb_rel = ""
        if image_bytes_or_path is not None:
            try:
                thumb_path = self._make_thumb(image_bytes_or_path, pid)
                try:
                    thumb_rel = str(thumb_path.relative_to(ROOT))
                except ValueError:
                    thumb_rel = str(thumb_path)
            except Exception as exc:
                print(f"[vault] thumb fail pin={pid}: {exc}")
                thumb_rel = ""

        now = _utc_now()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO approved_photos
                        (pin_id, image_url, local_thumb_path, query, tags,
                         added_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(pin_id) DO UPDATE SET
                        image_url=COALESCE(excluded.image_url, image_url),
                        local_thumb_path=CASE
                            WHEN excluded.local_thumb_path != ''
                            THEN excluded.local_thumb_path
                            ELSE local_thumb_path END,
                        query=CASE
                            WHEN excluded.query != '' THEN excluded.query
                            ELSE query END,
                        tags=CASE
                            WHEN excluded.tags != '' THEN excluded.tags
                            ELSE tags END,
                        status=excluded.status,
                        added_at=COALESCE(approved_photos.added_at, excluded.added_at)
                    """,
                    (
                        pid,
                        image_url or "",
                        thumb_rel,
                        (query or "").strip(),
                        tags_s,
                        now,
                        status or "approved",
                    ),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM approved_photos WHERE pin_id=?", (pid,)
                ).fetchone()
        return dict(row) if row else None

    def set_status(self, pin_id: Any, status: str = "approved") -> bool:
        """✅ Оставить — зафиксировать status=approved (или иной)."""
        pid = _as_pin_id(pin_id)
        if not pid or self.is_blacklisted(pid):
            return False
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "UPDATE approved_photos SET status=? WHERE pin_id=?",
                    (status, pid),
                )
                conn.commit()
                return cur.rowcount > 0

    def count_approved(self, *, search: str = "") -> int:
        """Число approved (для пагинации), с учётом search."""
        q = (search or "").strip().lower()
        with self._lock:
            with self._connect() as conn:
                if not q:
                    row = conn.execute(
                        "SELECT COUNT(*) AS n FROM approved_photos"
                    ).fetchone()
                    return int(row["n"])
                like = f"%{q}%"
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS n FROM approved_photos
                    WHERE lower(pin_id) LIKE ?
                       OR lower(query) LIKE ?
                       OR lower(tags) LIKE ?
                    """,
                    (like, like, like),
                ).fetchone()
                return int(row["n"])

    def get_approved_photos(
        self,
        *,
        search: str = "",
        include_blocked_badge: bool = False,
        limit: int = 48,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Список для галереи (новые сверху). search — по query/tags/pin_id."""
        q = (search or "").strip().lower()
        lim = max(1, int(limit))
        off = max(0, int(offset))
        with self._lock:
            with self._connect() as conn:
                if q:
                    like = f"%{q}%"
                    rows = conn.execute(
                        """
                        SELECT pin_id, image_url, local_thumb_path, query, tags,
                               added_at, status
                        FROM approved_photos
                        WHERE lower(pin_id) LIKE ?
                           OR lower(query) LIKE ?
                           OR lower(tags) LIKE ?
                        ORDER BY added_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (like, like, like, lim, off),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT pin_id, image_url, local_thumb_path, query, tags,
                               added_at, status
                        FROM approved_photos
                        ORDER BY added_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (lim, off),
                    ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            pid = _as_pin_id(d.get("pin_id"))
            if self.is_blacklisted(pid):
                if not include_blocked_badge:
                    continue
                d["status"] = "blocked"
            rel = str(d.get("local_thumb_path") or "")
            thumb = Path(rel) if rel else self.thumbs_dir / f"{pid}.jpg"
            if not thumb.is_absolute():
                thumb = ROOT / thumb
            d["thumb_abs"] = str(thumb) if thumb.is_file() else ""
            out.append(d)
        return out

    def stats(self) -> dict[str, int]:
        with self._lock:
            with self._connect() as conn:
                approved = conn.execute(
                    "SELECT COUNT(*) AS n FROM approved_photos "
                    "WHERE status != 'blocked'"
                ).fetchone()["n"]
                blocked = conn.execute(
                    "SELECT COUNT(*) AS n FROM blacklisted_pins"
                ).fetchone()["n"]
        return {
            "approved": int(approved),
            "blacklisted": int(blocked),
            "blacklist_memory": len(self._blacklist),
        }

    # -- учёт использования (серия) ---------------------------------------

    def _set_approved_fp(self, pid: str, image: Any) -> None:
        """Отпечаток для approved-строки, если его ещё нет."""
        from core.carousel_rules import fp_to_hex, image_fingerprint

        img = self._open_image(image)
        fp = image_fingerprint(img) if img is not None else None
        if fp is None:
            return
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE approved_photos SET fp=? "
                    "WHERE pin_id=? AND (fp IS NULL OR fp='')",
                    (fp_to_hex(fp), pid),
                )
                conn.commit()

    @staticmethod
    def _open_image(image: Any) -> Image.Image | None:
        if image is None:
            return None
        if isinstance(image, Image.Image):
            return image
        try:
            if isinstance(image, (bytes, bytearray)):
                return Image.open(io.BytesIO(image)).convert("RGB")
            return Image.open(str(image)).convert("RGB")
        except Exception:
            return None

    def register_usage(
        self,
        carousel: str | Path,
        slide: int,
        *,
        pin_id: Any = None,
        image: Any = None,
        fp: int | None = None,
    ) -> None:
        """
        Слайд `slide` карусели `carousel` теперь стоит на этом фото.
        Старая запись этого слайда заменяется (ручная замена фона).
        """
        from core.carousel_rules import fp_to_hex, image_fingerprint

        key = str(carousel)
        if fp is None:
            img = self._open_image(image)
            fp = image_fingerprint(img) if img is not None else None
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO used_photos"
                    "(carousel, slide, pin_id, fp, used_at) VALUES (?,?,?,?,?)",
                    (key, int(slide), _as_pin_id(pin_id), fp_to_hex(fp), _utc_now()),
                )
                conn.commit()

    def release_carousel(self, carousel: str | Path) -> int:
        """Карусель удалена/пересобрана — её фото снова свободны."""
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM used_photos WHERE carousel=?", (str(carousel),)
                )
                conn.commit()
                return int(cur.rowcount or 0)

    def _backfill_approved_fps(self) -> int:
        """Отпечатки для старых approved-фото по их превью (один раз)."""
        from core.carousel_rules import fp_to_hex, image_fingerprint

        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT pin_id, local_thumb_path FROM approved_photos "
                    "WHERE (fp IS NULL OR fp='') AND local_thumb_path != ''"
                ).fetchall()
        updates: list[tuple[str, str]] = []
        for r in rows:
            p = Path(str(r["local_thumb_path"]))
            if not p.is_absolute():
                p = ROOT / p
            if not p.is_file():
                continue
            try:
                with Image.open(p) as im:
                    fp = image_fingerprint(im)
            except Exception:
                continue
            if fp is not None:
                updates.append((fp_to_hex(fp), _as_pin_id(r["pin_id"])))
        if updates:
            with self._lock:
                with self._connect() as conn:
                    conn.executemany(
                        "UPDATE approved_photos SET fp=? WHERE pin_id=?", updates
                    )
                    conn.commit()
            print(f"[vault] отпечатки для {len(updates)} старых фото")
        return len(updates)

    def used_index(
        self,
        *,
        exclude_carousel: str | Path | None = None,
        exclude_pins: set[str] | None = None,
    ):
        """
        Все фото, уже стоящие в каруселях серии:
        approved_photos (финалы прошлых запусков) + used_photos (ручные замены).
        exclude_carousel / exclude_pins — «свои» фото карусели не считаются
        занятыми (иначе нельзя вернуть слайду его же прежний кадр).
        """
        from core.carousel_rules import UsedIndex, fp_from_hex

        try:
            self._backfill_approved_fps()
        except Exception as exc:
            print(f"[vault] backfill fp skip: {exc}")
        idx = UsedIndex()
        ex = str(exclude_carousel) if exclude_carousel is not None else None
        own = {str(p) for p in (exclude_pins or set()) if p}
        with self._lock:
            with self._connect() as conn:
                used_rows = conn.execute(
                    "SELECT carousel, pin_id, fp FROM used_photos"
                ).fetchall()
                if ex is not None:
                    own |= {
                        _as_pin_id(r["pin_id"])
                        for r in used_rows
                        if str(r["carousel"]) == ex and r["pin_id"]
                    }
                for r in conn.execute(
                    "SELECT pin_id, fp FROM approved_photos WHERE status != 'blocked'"
                ):
                    if _as_pin_id(r["pin_id"]) in own:
                        continue
                    idx.add(r["pin_id"], fp_from_hex(r["fp"]))
                for r in used_rows:
                    if ex is not None and str(r["carousel"]) == ex:
                        continue
                    if _as_pin_id(r["pin_id"]) in own:
                        continue
                    idx.add(r["pin_id"], fp_from_hex(r["fp"]))
        return idx

    def register_selected(
        self,
        items: list[dict[str, Any]],
    ) -> int:
        """
        Авто-регистрация финальных фото карусели.
        items: {pin_id, image|path, query?, tags?, image_url?}
        """
        n = 0
        for it in items:
            if not isinstance(it, dict):
                continue
            pid = _as_pin_id(it.get("pin_id"))
            if not pid or self.is_blacklisted(pid):
                continue
            img = it.get("image")
            if img is None:
                img = it.get("path") or it.get("image_path")
            row = self.add_approved_photo(
                pid,
                img,
                query=str(it.get("query") or ""),
                tags=it.get("tags"),
                image_url=str(it.get("image_url") or it.get("source_url") or ""),
                status="approved",
            )
            if row:
                n += 1
                try:
                    self._set_approved_fp(pid, img)
                except Exception:
                    pass
            carousel = it.get("carousel")
            if carousel is not None and it.get("slide") is not None:
                try:
                    self.register_usage(
                        carousel, int(it["slide"]), pin_id=pid, image=img
                    )
                except Exception as exc:
                    print(f"[vault] usage skip: {exc}")
        if n:
            print(f"[vault] registered {n} approved photo(s)")
        return n

    def import_from_exports(
        self,
        out_root: Path | str | None = None,
        *,
        skip_existing: bool = True,
    ) -> dict[str, int]:
        """
        Бэкап библиотеки из уже собранных каруселей в out/.
        Берёт pin_id из meta.json + превью из alts/{i}_0.jpg или {i}.jpg.
        """
        root = Path(out_root) if out_root else ROOT / "out"
        if not root.is_dir():
            return {"scanned": 0, "added": 0, "skipped": 0, "blocked": 0}

        existing: set[str] = set()
        if skip_existing:
            with self._lock:
                with self._connect() as conn:
                    rows = conn.execute(
                        "SELECT pin_id FROM approved_photos"
                    ).fetchall()
                existing = {_as_pin_id(r["pin_id"]) for r in rows}

        scanned = 0
        added = 0
        skipped = 0
        blocked = 0
        seen_pins: set[str] = set(existing)

        for meta_path in sorted(root.rglob("meta.json")):
            folder = meta_path.parent
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            slides = data.get("slides") or []
            if not isinstance(slides, list):
                continue
            topic = str(data.get("topic") or folder.name)
            scanned += 1
            for slide in slides:
                if not isinstance(slide, dict):
                    continue
                pid = _as_pin_id(slide.get("pin_id"))
                if not pid:
                    continue
                if pid in seen_pins:
                    skipped += 1
                    continue
                if self.is_blacklisted(pid):
                    blocked += 1
                    continue

                idx = int(slide.get("index") or 0)
                # raw alt предпочтительнее (без текста)
                alt = folder / "alts" / f"{idx}_0.jpg"
                rendered = folder / str(slide.get("file") or f"{idx}.jpg")
                img_path: Path | None = None
                if alt.is_file():
                    img_path = alt
                elif rendered.is_file():
                    img_path = rendered
                if img_path is None:
                    skipped += 1
                    continue

                row = self.add_approved_photo(
                    pid,
                    img_path,
                    query=str(slide.get("query") or ""),
                    tags=topic[:80],
                    image_url=str(
                        slide.get("source_url") or slide.get("image_url") or ""
                    ),
                    status="approved",
                )
                if row:
                    added += 1
                    seen_pins.add(pid)
                else:
                    skipped += 1

        print(
            f"[vault] import out/: scanned={scanned} added={added} "
            f"skipped={skipped} blocked={blocked}"
        )
        return {
            "scanned": scanned,
            "added": added,
            "skipped": skipped,
            "blocked": blocked,
        }

    def regenerate_thumbs_from_exports(
        self,
        out_root: Path | str | None = None,
    ) -> dict[str, int]:
        """
        Пересобрать превью для уже известных pin_id из out/
        (alts/{i}_0.jpg или {i}.jpg) — крупнее / чётче.
        """
        root = Path(out_root) if out_root else ROOT / "out"
        updated = 0
        missing = 0
        if not root.is_dir():
            return {"updated": 0, "missing": 0}

        # pin_id -> best source path (prefer alts)
        sources: dict[str, Path] = {}
        for meta_path in root.rglob("meta.json"):
            folder = meta_path.parent
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for slide in data.get("slides") or []:
                if not isinstance(slide, dict):
                    continue
                pid = _as_pin_id(slide.get("pin_id"))
                if not pid or self.is_blacklisted(pid):
                    continue
                idx = int(slide.get("index") or 0)
                alt = folder / "alts" / f"{idx}_0.jpg"
                rendered = folder / str(slide.get("file") or f"{idx}.jpg")
                src = alt if alt.is_file() else (
                    rendered if rendered.is_file() else None
                )
                if src is None:
                    continue
                # alts предпочтительнее уже записанного rendered
                prev = sources.get(pid)
                if prev is None or ("alts" in str(src) and "alts" not in str(prev)):
                    sources[pid] = src

        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT pin_id FROM approved_photos"
                ).fetchall()
            pins = [_as_pin_id(r["pin_id"]) for r in rows]

        for pid in pins:
            src = sources.get(pid)
            if src is None or not src.is_file():
                missing += 1
                continue
            try:
                thumb_path = self._make_thumb(src, pid)
                try:
                    thumb_rel = str(thumb_path.relative_to(ROOT))
                except ValueError:
                    thumb_rel = str(thumb_path)
                with self._lock:
                    with self._connect() as conn:
                        conn.execute(
                            "UPDATE approved_photos SET local_thumb_path=? "
                            "WHERE pin_id=?",
                            (thumb_rel, pid),
                        )
                        conn.commit()
                updated += 1
            except Exception:
                missing += 1

        print(f"[vault] regenerate thumbs: updated={updated} missing={missing}")
        return {"updated": updated, "missing": missing}


# -- singleton --------------------------------------------------------------

_vault: PhotoVault | None = None
_vault_lock = threading.Lock()


def get_photo_vault() -> PhotoVault:
    """Глобальный синглтон — один in-memory blacklist на процесс."""
    global _vault
    if _vault is not None:
        return _vault
    with _vault_lock:
        if _vault is None:
            _vault = PhotoVault()
        return _vault


def drop_blacklisted_pins(pins: list[Any]) -> tuple[list[Any], int]:
    """
    Отфильтровать список PinMeta / объектов с .pin_id.
    Returns (kept, dropped_count).
    """
    try:
        vault = get_photo_vault()
    except Exception:
        return pins, 0
    kept: list[Any] = []
    dropped = 0
    for p in pins:
        pid = _as_pin_id(getattr(p, "pin_id", None) or (p.get("pin_id") if isinstance(p, dict) else ""))
        if pid and vault.is_blacklisted(pid):
            dropped += 1
            continue
        kept.append(p)
    return kept, dropped
