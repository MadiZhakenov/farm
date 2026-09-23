#!/usr/bin/env python3
"""
Industrial batch collage combinator — 10k unique editorial collages.

Features:
  • SQLite registry (resume-safe, skip duplicates by visual hash_id)
  • N editorial layouts from core/collage_layouts.py (layout_01 …)
  • Slot 4 fixed = hairline; slots 1–3 permute pillow / brush / product
  • Labels always follow their item
  • 25 masthead headlines rotate per unique collage (not part of hash space)
  • Chunked output: out/collages_10k/batch_001/ …

Usage:
  python batch_collage_combinator.py --count 100
  python batch_collage_combinator.py --count 10000 --chunk-size 500
  python batch_collage_combinator.py --count 50 --seed 42
  python batch_collage_combinator.py --count 100 --sequential
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import random
import sqlite3
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.collage_layouts import (  # noqa: E402
    LAYOUT_REGISTRY,
    layout_id_from_key,
    layout_key,
    render_layout,
)

DEFAULT_ASSETS = ROOT / "assets"
DEFAULT_FALLBACK = Path(r"E:\Users\Desktop\download")
DB_PATH = ROOT / "data" / "collage_production.db"
OUT_ROOT = ROOT / "out" / "collages_10k"

CATEGORIES = ("pillows", "brushes", "products", "hairlines")
ITEM_KEYS = ("pillow", "brush", "product", "hairline")

# Base caption text (slot number is prepended at render time)
ITEM_LABELS: dict[str, str] = {
    "pillow": "silk pillowcase",
    "brush": "scalp stimulation",
    "product": "daily hair gummies (sulu)",
    "hairline": "90-day hairline progress",
}

# Round-robin layouts from core/collage_layouts (layout_01 … layout_N)
LAYOUTS = tuple(layout_key(i) for i in sorted(LAYOUT_REGISTRY))
assert len(LAYOUTS) == len(LAYOUT_REGISTRY)
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# 25 magazine mastheads — rotated onto unique visual recipes (NOT in hash_id)
HEADLINE_VARIATIONS = [
    "the daily routine that saved my hair",
    "what actually stopped my postpartum shedding",
    "my 90-day hair density starter pack",
    "the simple habits that brought my hairline back",
    "everything that actually worked for my thinning hair",
    "my holy grail routine for hair regrowth",
    "the 4 steps that completely transformed my hair",
    "how i finally stopped my hair from falling out",
    "the minimal routine that fixed my hairline",
    "what i wish i knew before my hair started thinning",
    "the unglamorous routine that actually grew my hair",
    "my everyday protocol for thicker, fuller hair",
    "how i went from constant shedding to new baby hairs",
    "the only hair habits worth keeping in 2026",
    "what saved my hair when nothing else worked",
    "my daily non-negotiables for hair density",
    "the quiet routine behind my hair comeback",
    "the realistic habits that stopped the shower clumps",
    "my honest hair growth stack (under 5 mins a day)",
    "what finally fixed my temple thinning for good",
    "the simple daily protocol that saved my scalp",
    "how i rebuilt my hair after months of shedding",
    "the 4 essentials behind my 3-month hair growth",
    "everything my hair actually needed to start growing",
    "the low-effort routine that gave me my hair back",
]

# Fallback keyword → category when inventing pools from a flat folder
_FALLBACK_HINTS: dict[str, tuple[str, ...]] = {
    "pillows": ("pillow", "bed", "silk", "messy"),
    "brushes": ("scalp", "brush", "sink", "massage"),
    "products": ("vitamin", "gummi", "gummy", "jar", "sulu", "product"),
    "hairlines": ("mirror", "hairline", "holding_hair", "selfie", "part"),
}


# ── SQLite registry ──────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS collages (
    hash_id     TEXT PRIMARY KEY,
    layout_type TEXT NOT NULL,
    slot1_item  TEXT NOT NULL,
    slot2_item  TEXT NOT NULL,
    slot3_item  TEXT NOT NULL,
    slot4_item  TEXT NOT NULL,
    slot1_label TEXT NOT NULL,
    slot2_label TEXT NOT NULL,
    slot3_label TEXT NOT NULL,
    slot4_label TEXT NOT NULL,
    headline    TEXT,
    file_path   TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collages_created ON collages(created_at);
"""


def connect_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(SCHEMA)
    _migrate_headline_column(conn)
    conn.commit()
    return conn


def _migrate_headline_column(conn: sqlite3.Connection) -> None:
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(collages)").fetchall()
    }
    if "headline" not in cols:
        conn.execute("ALTER TABLE collages ADD COLUMN headline TEXT")


def hash_exists(conn: sqlite3.Connection, hash_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM collages WHERE hash_id = ? LIMIT 1", (hash_id,)
    ).fetchone()
    return row is not None


def insert_collage(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT INTO collages (
            hash_id, layout_type,
            slot1_item, slot2_item, slot3_item, slot4_item,
            slot1_label, slot2_label, slot3_label, slot4_label,
            headline, file_path, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["hash_id"],
            row["layout_type"],
            row["slot1_item"],
            row["slot2_item"],
            row["slot3_item"],
            row["slot4_item"],
            row["slot1_label"],
            row["slot2_label"],
            row["slot3_label"],
            row["slot4_label"],
            row["headline"],
            row["file_path"],
            row["created_at"],
        ),
    )


def registry_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM collages").fetchone()[0])


# ── Asset pools ──────────────────────────────────────────────────────────────

def _list_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
    ]
    files.sort(key=lambda p: p.name.lower())
    return files


def _cycle_to_n(files: list[Path], n: int = 10) -> list[Path]:
    if not files:
        return []
    out: list[Path] = []
    i = 0
    while len(out) < n:
        out.append(files[i % len(files)])
        i += 1
    return out


def _fallback_pools(flat_dir: Path) -> dict[str, list[Path]]:
    """Build 4 pools of 10 from a flat folder (or project scans)."""
    files = _list_images(flat_dir)
    if not files:
        files = sorted(
            p
            for p in ROOT.rglob("*")
            if p.is_file()
            and p.suffix.lower() in _IMAGE_EXTS
            and "node_modules" not in p.parts
            and ".git" not in p.parts
        )[:40]
    if not files:
        raise FileNotFoundError(
            f"No images found in {flat_dir} or project. "
            "Add assets/pillows|brushes|products|hairlines or drop files in download/."
        )

    pools: dict[str, list[Path]] = {c: [] for c in CATEGORIES}
    rem = list(files)

    for cat, hints in _FALLBACK_HINTS.items():
        best: Path | None = None
        best_score = 0
        for p in rem:
            name = p.stem.lower()
            score = sum(1 for h in hints if h in name)
            if cat == "hairlines" and ("vitamin" in name or "jar" in name or "sulu" in name):
                continue
            if cat == "products" and ("mirror" in name and "vitamin" not in name and "jar" not in name):
                continue
            if score > best_score:
                best_score = score
                best = p
        if best is not None and best_score > 0:
            pools[cat].append(best)
            rem.remove(best)

    leftover = rem if rem else files
    for cat in CATEGORIES:
        if not pools[cat]:
            pools[cat] = [leftover[abs(hash(cat)) % len(leftover)]]
        pools[cat] = _cycle_to_n(pools[cat], 10)

    return pools


def load_asset_pools(assets_dir: Path, fallback_dir: Path) -> dict[str, list[Path]]:
    """
    Prefer assets/{pillows,brushes,products,hairlines}/01..10.jpg
    Else invent pools from fallback_dir (cycled to 10 each).
    """
    pools: dict[str, list[Path]] = {}
    structured = True
    for cat in CATEGORIES:
        folder = assets_dir / cat
        files = _list_images(folder)
        if not files:
            structured = False
            break
        pools[cat] = _cycle_to_n(files, 10)

    if structured:
        print(f"Assets: structured pools from {assets_dir}")
        for cat, files in pools.items():
            print(f"  {cat}: {len(files)} (cycled to 10) e.g. {files[0].name}")
        return pools

    print(f"Assets: no structured assets/ — fallback from {fallback_dir}")
    pools = _fallback_pools(fallback_dir)
    for cat, files in pools.items():
        uniq = len({str(p) for p in files})
        print(f"  {cat}: {uniq} unique → 10 slots (cycled) e.g. {files[0].name}")
    return pools


# ── Recipe space ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Recipe:
    layout: str
    # item keys for slots 1..3 (permutation of pillow/brush/product)
    slot_items: tuple[str, str, str]  # keys
    # indices into each category pool (0..9)
    pillow_i: int
    brush_i: int
    product_i: int
    hairline_i: int

    def paths(self, pools: dict[str, list[Path]]) -> tuple[Path, Path, Path, Path]:
        key_to_path = {
            "pillow": pools["pillows"][self.pillow_i],
            "brush": pools["brushes"][self.brush_i],
            "product": pools["products"][self.product_i],
            "hairline": pools["hairlines"][self.hairline_i],
        }
        s1, s2, s3 = self.slot_items
        return (
            key_to_path[s1],
            key_to_path[s2],
            key_to_path[s3],
            key_to_path["hairline"],
        )

    def labels(self) -> tuple[str, str, str, str]:
        s1, s2, s3 = self.slot_items
        return (
            f"01 · {ITEM_LABELS[s1]}",
            f"02 · {ITEM_LABELS[s2]}",
            f"03 · {ITEM_LABELS[s3]}",
            f"04 · {ITEM_LABELS['hairline']}",
        )

    def hash_id(self, pools: dict[str, list[Path]]) -> str:
        """Visual uniqueness only — layout + 4 image paths (order = permutation).

        Headline is intentionally excluded so masthead rotation never inflates
        the combination space or re-hashes the same picture set.
        """
        p1, p2, p3, p4 = self.paths(pools)
        raw = "|".join(
            [
                self.layout,
                str(p1.resolve()),
                str(p2.resolve()),
                str(p3.resolve()),
                str(p4.resolve()),
                # Labels follow items; included for stability with earlier registry rows
                *self.labels(),
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def iter_recipes_sequential() -> Iterator[Recipe]:
    """
    Deterministic full sweep (resume-friendly).

    Space size = 10³ × 10 hairlines × 3! perms × N layouts
               = 60_000 × N
    """
    perms = list(itertools.permutations(("pillow", "brush", "product")))
    for hair_i in range(10):
        for pillow_i in range(10):
            for brush_i in range(10):
                for product_i in range(10):
                    for perm in perms:
                        for layout in LAYOUTS:
                            yield Recipe(
                                layout=layout,
                                slot_items=perm,
                                pillow_i=pillow_i,
                                brush_i=brush_i,
                                product_i=product_i,
                                hairline_i=hair_i,
                            )


def iter_recipes_random(rng: random.Random) -> Iterator[Recipe]:
    """Endless stream of randomly sampled unique visual recipes."""
    perms = list(itertools.permutations(("pillow", "brush", "product")))
    while True:
        yield Recipe(
            layout=rng.choice(LAYOUTS),
            slot_items=rng.choice(perms),
            pillow_i=rng.randrange(10),
            brush_i=rng.randrange(10),
            product_i=rng.randrange(10),
            hairline_i=rng.randrange(10),
        )


def pick_headline(collage_counter: int, rng: random.Random | None = None) -> str:
    """Even rotation, or fully random if rng is provided."""
    if rng is not None:
        return rng.choice(HEADLINE_VARIATIONS)
    return HEADLINE_VARIATIONS[collage_counter % len(HEADLINE_VARIATIONS)]


# ── Rendering ────────────────────────────────────────────────────────────────

_IMG_CACHE: dict[str, Image.Image] = {}


def load_rgb(path: Path) -> Image.Image:
    key = str(path.resolve())
    if key not in _IMG_CACHE:
        with Image.open(path) as im:
            _IMG_CACHE[key] = im.convert("RGB").copy()
        if len(_IMG_CACHE) > 80:
            for k in list(_IMG_CACHE.keys())[:20]:
                _IMG_CACHE.pop(k, None)
    return _IMG_CACHE[key]


def render_recipe(
    recipe: Recipe,
    pools: dict[str, list[Path]],
    headline: str,
) -> Image.Image:
    paths = recipe.paths(pools)
    labels = recipe.labels()
    imgs = [load_rgb(p) for p in paths]
    lid = layout_id_from_key(recipe.layout)
    return render_layout(lid, imgs, labels, title=headline)


def batch_dir(out_root: Path, global_index: int, chunk_size: int) -> Path:
    """1-based batch folder for the Nth successfully saved collage (0-based index)."""
    batch_num = global_index // chunk_size + 1
    d = out_root / f"batch_{batch_num:03d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Progress ─────────────────────────────────────────────────────────────────

def fmt_progress(
    done: int,
    total: int,
    skipped: int,
    t0: float,
) -> str:
    elapsed = max(time.perf_counter() - t0, 1e-6)
    rate = done / elapsed
    pct = 100.0 * done / total if total else 0.0
    return (
        f"[{done} / {total}] ({pct:.1f}%) | "
        f"Speed: ~{rate:.1f} collages/s | "
        f"Skipped dups: {skipped}"
    )


# ── Main run ─────────────────────────────────────────────────────────────────

def run(
    *,
    count: int,
    chunk_size: int,
    assets_dir: Path,
    fallback_dir: Path,
    db_path: Path,
    out_root: Path,
    shuffle: bool = True,
    seed: int | None = None,
) -> int:
    pools = load_asset_pools(assets_dir, fallback_dir)
    conn = connect_db(db_path)
    already = registry_count(conn)

    rng = random.Random(seed)
    if shuffle:
        recipe_iter: Iterator[Recipe] = iter_recipes_random(rng)
        mode = f"random (seed={seed if seed is not None else 'entropy'})"
    else:
        recipe_iter = iter_recipes_sequential()
        mode = "sequential"

    print(f"Registry: {db_path}  ({already} collages on disk)")
    print(f"Mode: {mode}")
    print(f"Target this run: {count} new | chunk_size={chunk_size}")
    print(f"Output: {out_root}\n")

    out_root.mkdir(parents=True, exist_ok=True)

    produced = 0
    skipped = 0
    t0 = time.perf_counter()
    last_print = 0.0
    # Safety: don't spin forever if space is exhausted
    max_attempts = max(count * 50, 10_000)

    try:
        for attempt, recipe in enumerate(recipe_iter):
            if produced >= count:
                break
            if attempt >= max_attempts and produced == 0:
                print("ERROR: no unique recipes found — registry may be full", file=sys.stderr)
                break
            if attempt >= max_attempts and produced < count:
                print(
                    f"\nStopped early: too many duplicate hits "
                    f"({produced}/{count} after {attempt} tries).",
                    file=sys.stderr,
                )
                break

            hid = recipe.hash_id(pools)
            if hash_exists(conn, hid):
                skipped += 1
                now = time.perf_counter()
                if now - last_print >= 0.5:
                    print(
                        fmt_progress(produced, count, skipped, t0)
                        + "  (scanning…)",
                        end="\r",
                        flush=True,
                    )
                    last_print = now
                continue

            collage_counter = already + produced
            headline = pick_headline(
                collage_counter, rng=rng if shuffle else None
            )

            canvas = render_recipe(recipe, pools, headline)
            paths = recipe.paths(pools)
            labels = recipe.labels()

            global_idx = collage_counter
            bdir = batch_dir(out_root, global_idx, chunk_size)
            fname = f"collage_{hid}.jpg"
            fpath = bdir / fname

            canvas.convert("RGB").save(
                fpath, "JPEG", quality=92, optimize=True, subsampling=0
            )
            canvas.close()

            insert_collage(
                conn,
                {
                    "hash_id": hid,
                    "layout_type": recipe.layout,
                    "slot1_item": str(paths[0]),
                    "slot2_item": str(paths[1]),
                    "slot3_item": str(paths[2]),
                    "slot4_item": str(paths[3]),
                    "slot1_label": labels[0],
                    "slot2_label": labels[1],
                    "slot3_label": labels[2],
                    "slot4_label": labels[3],
                    "headline": headline,
                    "file_path": str(fpath.resolve()),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            produced += 1

            if produced % 25 == 0:
                conn.commit()

            now = time.perf_counter()
            if produced == 1 or produced == count or now - last_print >= 0.25:
                print(fmt_progress(produced, count, skipped, t0), end="\r", flush=True)
                last_print = now

    except KeyboardInterrupt:
        print("\n\nInterrupted — committing registry…")
        conn.commit()
        print(fmt_progress(produced, count, skipped, t0))
        print(f"Saved {produced} this run. Re-run to continue.")
        conn.close()
        return 130

    conn.commit()
    conn.close()
    print()
    print(fmt_progress(produced, count, skipped, t0))
    elapsed = time.perf_counter() - t0
    print(f"Done. {produced} new collages in {elapsed:.1f}s → {out_root.resolve()}")
    return 0

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Batch-generate unique editorial collages with SQLite dedup."
    )
    ap.add_argument(
        "--count",
        type=int,
        default=10_000,
        help="How many NEW collages to generate this run (default: 10000)",
    )
    ap.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help="Files per batch_XXX folder (default: 500)",
    )
    ap.add_argument(
        "--assets-dir",
        type=Path,
        default=DEFAULT_ASSETS,
        help="Root with pillows/brushes/products/hairlines (default: assets/)",
    )
    ap.add_argument(
        "--fallback-dir",
        type=Path,
        default=DEFAULT_FALLBACK,
        help="Flat folder used when assets/ missing (default: Desktop/download)",
    )
    ap.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help=f"SQLite registry path (default: {DB_PATH})",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=OUT_ROOT,
        help=f"Output root (default: {OUT_ROOT})",
    )
    ap.add_argument(
        "--sequential",
        action="store_true",
        help="Sweep recipe space in fixed order (default is random)",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed for reproducible random runs",
    )
    args = ap.parse_args(argv)

    if args.count < 1:
        print("ERROR: --count must be >= 1", file=sys.stderr)
        return 2
    if args.chunk_size < 1:
        print("ERROR: --chunk-size must be >= 1", file=sys.stderr)
        return 2

    try:
        return run(
            count=args.count,
            chunk_size=args.chunk_size,
            assets_dir=args.assets_dir,
            fallback_dir=args.fallback_dir,
            db_path=args.db,
            out_root=args.out,
            shuffle=not args.sequential,
            seed=args.seed,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
