#!/usr/bin/env python3
"""
organize_reelfarm_folders.py
============================
Re-organize downloaded_carousels/ to mirror ReelFarm database groupings:

  downloaded_carousels/
    _all/                         # canonical carousel folders
    by_niche/{niche}/...
    by_product_medium/{medium}/...
    by_account_region/{region}/...   # creator.region (US, GB, ...)
    by_audience_region/{country}/... # top country from audience_regions

Each carousel is linked into EVERY matching group (duplicates across trees).
On Windows uses directory junctions (no extra disk). Falls back to copytree
if junction creation fails.

Usage:
  python organize_reelfarm_folders.py
  python organize_reelfarm_folders.py --mode copy   # real copies (heavy)
  python organize_reelfarm_folders.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "reelfarm_database.db"
OUT_ROOT = ROOT / "downloaded_carousels"
ALL_DIR = OUT_ROOT / "_all"
MAP_PATH = OUT_ROOT / "_rename_map.json"
ORG_MAP_PATH = OUT_ROOT / "_organization_map.json"

WIN_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize(name: str, max_len: int = 80) -> str:
    name = unicodedata.normalize("NFKC", str(name or ""))
    name = WIN_BAD.sub("", name)
    name = name.replace("\n", " ").replace("\r", " ").strip()
    name = re.sub(r"\s+", " ", name)
    # Keep spaces for readability in category folders (like ReelFarm labels)
    if not name or name.lower() in {"none", "null"}:
        return "none"
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .")
    # Windows reserved
    if name.upper() in {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        name = f"_{name}"
    return name


def top_audience_country(raw_json: str | None) -> str:
    if not raw_json:
        return "unknown"
    try:
        raw = json.loads(raw_json)
    except json.JSONDecodeError:
        return "unknown"
    regions = (raw.get("creator") or {}).get("audience_regions") or []
    if not regions:
        return "unknown"
    top = max(regions, key=lambda x: int(x.get("count") or 0))
    return top.get("country") or top.get("countryCode") or "unknown"


def load_db_rows() -> dict[str, dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    out: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT id, niche, product_medium, audience_region, creator_unique_id, raw_json "
        "FROM slideshows"
    ):
        d = dict(r)
        d["account_region"] = d.get("audience_region") or "unknown"  # stored region code
        d["audience_country"] = top_audience_country(d.get("raw_json"))
        d["niche"] = d.get("niche") or "none"
        d["product_medium"] = d.get("product_medium") or "none"
        out[str(d["id"])] = d
    conn.close()
    return out


def discover_carousel_dirs(out_root: Path) -> list[Path]:
    """Find carousel folders currently at root or already in _all."""
    found: list[Path] = []
    skip_names = {
        "_all",
        "by_niche",
        "by_product_medium",
        "by_account_region",
        "by_audience_region",
    }
    all_dir = out_root / "_all"
    if all_dir.is_dir():
        for p in all_dir.iterdir():
            if p.is_dir() and not p.name.startswith("."):
                found.append(p)
    for p in out_root.iterdir():
        if not p.is_dir() or p.name.startswith(".") or p.name.startswith("_"):
            continue
        if p.name in skip_names or p.name.startswith("by_"):
            continue
        found.append(p)
    return found


def resolve_id(folder: Path) -> str | None:
    meta_path = folder / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
        for key in ("original_id", "id"):
            if meta.get(key):
                return str(meta[key])
    # rename map reverse
    return None


def load_rename_map() -> dict[str, str]:
    """original_id -> folder name"""
    if not MAP_PATH.is_file():
        return {}
    data = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    out = {}
    for oid, info in data.items():
        if isinstance(info, dict) and info.get("folder"):
            out[str(oid)] = info["folder"]
        elif isinstance(info, str):
            out[str(oid)] = info
    return out


def ensure_link_or_copy(target: Path, link: Path, mode: str) -> str:
    """
    Create link -> target (junction/symlink) or copy.
    Returns 'junction' | 'symlink' | 'copy' | 'exists'.
    """
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        # If already points correctly, skip
        try:
            if link.resolve() == target.resolve():
                return "exists"
        except Exception:
            pass
        # Replace broken / wrong (junctions are reparse points; rmdir removes junction)
        try:
            if link.is_symlink():
                link.unlink()
            elif link.is_dir():
                link.rmdir()
            else:
                link.unlink()
        except OSError:
            shutil.rmtree(link, ignore_errors=True)
            if link.exists():
                raise

    if mode == "copy":
        shutil.copytree(target, link, dirs_exist_ok=False)
        return "copy"

    # Prefer Windows junction (no admin)
    if os.name == "nt":
        # mklink /J link target
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and link.exists():
            return "junction"
        # try symlink
        try:
            os.symlink(str(target), str(link), target_is_directory=True)
            return "symlink"
        except OSError:
            shutil.copytree(target, link)
            return "copy"

    # POSIX
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return "symlink"
    except OSError:
        shutil.copytree(target, link)
        return "copy"


def move_to_all(folders: list[Path], dry_run: bool) -> dict[str, Path]:
    """Move root-level carousel folders into _all/. Return id -> path in _all."""
    ALL_DIR.mkdir(parents=True, exist_ok=True)
    id_to_path: dict[str, Path] = {}
    rename_map = load_rename_map()
    # reverse folder name -> id from rename map
    folder_to_id = {v: k for k, v in rename_map.items()}

    for folder in folders:
        # already under _all
        under_all = ALL_DIR in folder.parents or folder.parent == ALL_DIR
        cid = resolve_id(folder) or folder_to_id.get(folder.name)
        if not cid:
            # try meta again / folder name as id
            cid = folder.name if len(folder.name) == 16 and "__" not in folder.name else None
        if not cid:
            cid = resolve_id(folder)
        if not cid:
            # last resort: keep using folder name as key
            cid = f"path:{folder.name}"

        dest = ALL_DIR / folder.name
        if under_all:
            id_to_path[cid] = folder
            continue

        if dry_run:
            print(f"  MOVE {folder.name} -> _all/")
            id_to_path[cid] = dest
            continue

        if dest.exists():
            # already moved
            id_to_path[cid] = dest
            if folder != dest and folder.exists() and folder.parent == OUT_ROOT:
                # duplicate at root — remove root leftover if identical name
                pass
            continue

        folder.rename(dest)
        id_to_path[cid] = dest

    return id_to_path


def organize(*, mode: str, dry_run: bool, limit: int | None) -> int:
    if not OUT_ROOT.is_dir():
        print(f"Missing {OUT_ROOT}")
        return 1
    rows = load_db_rows()
    folders = discover_carousel_dirs(OUT_ROOT)
    if limit is not None:
        folders = folders[:limit]

    print(f"Found {len(folders)} carousel folders")
    print(f"DB rows: {len(rows)}")
    print(f"Mode: {mode}  dry_run={dry_run}")

    # Phase 1: consolidate into _all
    print("\n[1/2] Consolidating into _all/ ...")
    id_to_path = move_to_all(folders, dry_run=dry_run)

    # Rebuild map by scanning _all + meta (more reliable after move)
    if not dry_run:
        id_to_path = {}
        for p in ALL_DIR.iterdir():
            if not p.is_dir() or p.name.startswith("."):
                continue
            cid = resolve_id(p)
            if cid and cid in rows:
                id_to_path[cid] = p
            elif cid:
                id_to_path[cid] = p

    print(f"Canonical folders mapped: {len(id_to_path)}")

    # Phase 2: link into taxonomy trees
    print("\n[2/2] Linking into ReelFarm groupings ...")
    taxonomies = {
        "by_niche": "niche",
        "by_product_medium": "product_medium",
        "by_account_region": "account_region",
        "by_audience_region": "audience_country",
    }

    stats = defaultdict(int)
    org_map: dict[str, dict] = {}

    items = list(id_to_path.items())
    if limit is not None:
        items = items[:limit]

    total = len(items)
    for i, (cid, path) in enumerate(items, 1):
        row = rows.get(cid)
        if not row:
            # try strip path: prefix
            row = rows.get(cid.replace("path:", ""))
        if not row:
            stats["unmatched_db"] += 1
            # still put under unknown in all groups
            row = {
                "niche": "unknown",
                "product_medium": "unknown",
                "account_region": "unknown",
                "audience_country": "unknown",
            }

        links = {}
        for tree, field in taxonomies.items():
            cat = sanitize(row.get(field) or "unknown")
            link = OUT_ROOT / tree / cat / path.name
            links[tree] = str(Path(tree) / cat / path.name)
            if dry_run:
                stats[f"plan_{tree}"] += 1
                continue
            kind = ensure_link_or_copy(path.resolve(), link, mode=mode)
            stats[kind] += 1
            stats[f"n_{tree}"] += 1

        org_map[cid] = {
            "folder": path.name,
            "niche": row.get("niche"),
            "product_medium": row.get("product_medium"),
            "account_region": row.get("account_region"),
            "audience_country": row.get("audience_country"),
            "links": links,
        }

        if i % 200 == 0 or i == total:
            print(f"\r  {i}/{total}  junctions={stats['junction']} copy={stats['copy']} skip={stats['exists']}", end="", flush=True)

    print()

    if not dry_run:
        ORG_MAP_PATH.write_text(json.dumps(org_map, ensure_ascii=False, indent=2), encoding="utf-8")

    # Summary counts like ReelFarm
    print("\n" + "=" * 64)
    print("Organization complete")
    print(f"  _all/: {len(list(ALL_DIR.iterdir())) if ALL_DIR.exists() else 0} folders")
    for tree in taxonomies:
        tree_path = OUT_ROOT / tree
        if tree_path.exists():
            cats = [p for p in tree_path.iterdir() if p.is_dir()]
            print(f"  {tree}/: {len(cats)} categories")
    print(f"  stats: {dict(stats)}")
    print(f"  map: {ORG_MAP_PATH}")
    print("=" * 64)
    print("Layout:")
    print("  downloaded_carousels/_all/")
    print("  downloaded_carousels/by_niche/<niche>/")
    print("  downloaded_carousels/by_product_medium/<medium>/")
    print("  downloaded_carousels/by_account_region/<US|GB|...>/")
    print("  downloaded_carousels/by_audience_region/<United States|...>/")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode",
        choices=["junction", "copy"],
        default="junction",
        help="junction=Windows dir links (default, no extra disk); copy=full duplicates",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    return organize(mode=args.mode, dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
