#!/usr/bin/env python3
"""
rename_carousel_folders.py
==========================
Rename downloaded_carousels/{hash}/ → readable names from ReelFarm metadata.

ReelFarm DB has NO TikTok captions/prompts (all empty). Readable name =
  @{creator} __ {niche} __ {saves}saves __ {views}views __ {id8}

Keeps original id in meta.json and writes rename_map.json for reverse lookup.
Safe on Windows (illegal chars stripped, length capped, collision suffixes).
Supports --dry-run.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "reelfarm_database.db"
OUT_ROOT = ROOT / "downloaded_carousels"
MAP_PATH = ROOT / "downloaded_carousels" / "_rename_map.json"

WIN_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MULTI_SPACE = re.compile(r"\s+")
MULTI_US = re.compile(r"_+")


def parse_count_display(n) -> str:
    if n is None:
        return "0"
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    if n >= 1_000:
        return f"{n / 1_000:.1f}K".rstrip("0").rstrip(".")
    return str(n)


def sanitize(name: str, max_len: int = 120) -> str:
    name = unicodedata.normalize("NFKC", name)
    name = WIN_BAD.sub("", name)
    name = name.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    name = MULTI_SPACE.sub(" ", name).strip()
    name = name.replace(" ", "_")
    name = MULTI_US.sub("_", name)
    name = name.strip("._ ")
    # Windows reserved device names
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if name.upper() in reserved:
        name = f"_{name}"
    if len(name) > max_len:
        name = name[:max_len].rstrip("._ ")
    return name or "carousel"


def build_name(row: dict) -> str:
    creator = (row.get("creator_unique_id") or "unknown").strip().lstrip("@")
    niche = (row.get("niche") or "misc").strip()
    saves = parse_count_display(row.get("saves"))
    views = parse_count_display(row.get("views"))
    short = str(row["id"])[:8]
    # Prefer human title if it isn't the auto "X slideshow #N" pattern —
    # (currently all are auto; keep hook for future scrapes)
    title = (row.get("title") or "").strip()
    auto = bool(re.search(r"slideshow\s*#\s*\d+\s*$", title, re.I)) or not title

    if not auto and title:
        base = f"@{creator}__{title}__{saves}saves__{short}"
    else:
        base = f"@{creator}__{niche}__{saves}saves__{views}views__{short}"
    return sanitize(base)


def load_rows(db_path: Path) -> dict[str, dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    out = {}
    for r in conn.execute(
        "SELECT id, title, niche, product_medium, views, likes, saves, "
        "creator_unique_id, audience_region FROM slideshows"
    ):
        out[str(r["id"])] = dict(r)
    conn.close()
    return out


def unique_target(root: Path, desired: str, used: set[str]) -> str:
    name = desired
    n = 2
    while name.lower() in used or (root / name).exists():
        # keep short id suffix stable; add counter before it if needed
        name = sanitize(f"{desired}__{n}")
        n += 1
        if n > 5000:
            raise RuntimeError(f"Too many collisions for {desired}")
    used.add(name.lower())
    return name


def rename_all(*, dry_run: bool, limit: int | None) -> int:
    if not OUT_ROOT.is_dir():
        print(f"Missing folder: {OUT_ROOT}")
        return 1
    rows = load_rows(DB_PATH)
    dirs = [p for p in OUT_ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")]
    dirs.sort(key=lambda p: p.name)
    if limit is not None:
        dirs = dirs[:limit]

    used: set[str] = set()
    # Reserve names of folders we will NOT rename this pass (already good / other)
    mapping: dict[str, dict] = {}
    renamed = 0
    skipped = 0
    missing_meta = 0

    # First pass: compute targets
    plans: list[tuple[Path, str, dict]] = []
    for folder in dirs:
        meta_path = folder / "meta.json"
        meta = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
        cid = str(meta.get("id") or folder.name)
        row = rows.get(cid)
        if not row:
            # folder named by hash already, or already renamed — try reverse via meta
            if not row and meta.get("id"):
                row = rows.get(str(meta["id"]))
        if not row:
            # synthesize from meta only
            row = {
                "id": cid if len(cid) <= 32 else meta.get("original_id", folder.name),
                "title": meta.get("title"),
                "niche": meta.get("niche"),
                "views": (meta.get("metrics") or {}).get("views", meta.get("views")),
                "saves": (meta.get("metrics") or {}).get("saves", meta.get("saves")),
                "creator_unique_id": meta.get("creator_unique_id"),
            }
            # If folder name is already long readable and starts with @, skip
            if folder.name.startswith("@") and "__" in folder.name:
                skipped += 1
                used.add(folder.name.lower())
                continue
            missing_meta += 0

        # Resolve canonical id from DB when folder was already renamed
        if cid not in rows and meta.get("original_id"):
            cid = str(meta["original_id"])
            row = rows.get(cid, row)
        elif folder.name in rows:
            cid = folder.name
            row = rows[cid]
        elif meta.get("id") in rows:
            cid = str(meta["id"])
            row = rows[cid]

        desired = build_name(row if row else {"id": folder.name})
        plans.append((folder, desired, {"id": cid, "row": row, "meta": meta}))

    # Apply with collision handling (two-phase to avoid clobber)
    # Phase 1: rename to temp names if needed
    temps: list[tuple[Path, Path, str, dict]] = []
    for folder, desired, info in plans:
        target_name = unique_target(OUT_ROOT, desired, used)
        if folder.name == target_name:
            skipped += 1
            mapping[info["id"]] = {
                "folder": folder.name,
                "original_id": info["id"],
                "status": "already_named",
            }
            continue
        temp = OUT_ROOT / f".__tmp_rename_{info['id']}"
        temps.append((folder, temp, target_name, info))

    print(f"Plan: rename {len(temps)}, skip {skipped}, total scanned {len(dirs)}")
    if dry_run:
        for folder, _temp, target_name, info in temps[:30]:
            print(f"  DRY  {folder.name}")
            print(f"   ->  {target_name}")
        if len(temps) > 30:
            print(f"  ... and {len(temps) - 30} more")
        return 0

    # Phase 1 → temp
    for folder, temp, target_name, info in temps:
        if temp.exists():
            raise SystemExit(f"Temp exists, abort: {temp}")
        folder.rename(temp)

    # Phase 2 → final + meta update
    for folder, temp, target_name, info in temps:
        final = OUT_ROOT / target_name
        temp.rename(final)
        meta = info["meta"] or {}
        meta["original_id"] = info["id"]
        meta["id"] = info["id"]
        meta["folder_name"] = target_name
        if info.get("row"):
            meta.setdefault("title", info["row"].get("title"))
            meta.setdefault("niche", info["row"].get("niche"))
            meta.setdefault("creator_unique_id", info["row"].get("creator_unique_id"))
            meta["metrics"] = {
                "views": info["row"].get("views"),
                "likes": info["row"].get("likes"),
                "saves": info["row"].get("saves"),
                "bookmarks": info["row"].get("saves"),
            }
        (final / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        mapping[info["id"]] = {
            "folder": target_name,
            "original_id": info["id"],
            "from": folder.name,
            "status": "renamed",
        }
        renamed += 1
        if renamed % 200 == 0 or renamed == len(temps):
            print(f"\rRenamed {renamed}/{len(temps)}", end="", flush=True)

    print()
    MAP_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done. renamed={renamed} skipped={skipped}")
    print(f"Map: {MAP_PATH}")
    # show a few examples
    examples = [v["folder"] for v in mapping.values() if v.get("status") == "renamed"][:8]
    for e in examples:
        print(f"  ex: {e}")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Print plan only")
    ap.add_argument("--limit", type=int, default=None, help="Only first N folders")
    args = ap.parse_args()
    return rename_all(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
