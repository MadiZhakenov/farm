#!/usr/bin/env python3
"""
Fetch viral Scrapbook / Moodboard collage references from Pinterest.

Saves ~15 JPEGs into data/collage_references/ for style analysis
(layout, typography, polaroid cards, handwritten labels).

Usage:
  python fetch_collage_refs.py
  python fetch_collage_refs.py --per-query 5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.harvester import PinterestHarvester  # noqa: E402

OUT_DIR = ROOT / "data" / "collage_references"

QUERIES: tuple[str, ...] = (
    "hair growth routine aesthetic collage",
    "lemon8 starter pack collage",
    "clean girl routine moodboard aesthetic",
)


def _slug(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return (s[:max_len] or "pin").rstrip("_")


def fetch_refs(*, per_query: int = 5, out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    saved: list[Path] = []
    seen_ids: set[str] = set()

    harvester = PinterestHarvester(
        on_status=lambda m: print(f"  - {m}".encode("ascii", "replace").decode("ascii"))
    )
    try:
        print("Warming Pinterest session...")
        harvester.warm()

        for qi, query in enumerate(QUERIES, 1):
            print(f"\n=== [{qi}/{len(QUERIES)}] {query} ===")
            t0 = time.perf_counter()
            harvester.reset_used()
            raw, prog = harvester.harvest_for_query(
                query,
                limit=max(per_query * 3, 12),
                slide_text=query,
                apply_score=False,
                allow_broaden=False,
            )
            print(
                f"  downloaded={len(raw)} stage={prog.stage} "
                f"pins~{prog.found} net={prog.elapsed_sec:.1f}s"
            )

            kept = 0
            for cand in raw:
                if kept >= per_query:
                    break
                if cand.pin_id in seen_ids:
                    continue
                seen_ids.add(cand.pin_id)
                kept += 1
                fname = (
                    f"q{qi:02d}_{kept:02d}_{_slug(query)}_{_slug(cand.pin_id, 16)}.jpg"
                )
                path = out_dir / fname
                rgb = cand.image.convert("RGB")
                rgb.save(path, "JPEG", quality=92, optimize=True)
                saved.append(path)
                manifest.append(
                    {
                        "file": fname,
                        "query": query,
                        "pin_id": cand.pin_id,
                        "title": cand.title,
                        "source_url": cand.source_url,
                        "size": list(cand.image.size),
                    }
                )
                print(f"  saved {fname}  ({cand.image.size[0]}x{cand.image.size[1]})")

            for c in raw:
                try:
                    c.image.close()
                except Exception:
                    pass

            print(f"  query done in {time.perf_counter() - t0:.1f}s  kept={kept}")

    finally:
        harvester.close()

    man_path = out_dir / "manifest.json"
    man_path.write_text(
        json.dumps(
            {
                "created_unix": int(time.time()),
                "queries": list(QUERIES),
                "count": len(manifest),
                "items": manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved {len(saved)} refs -> {out_dir.resolve()}")
    print(f"Manifest -> {man_path.resolve()}")
    return saved


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fetch Pinterest collage style references.")
    p.add_argument("--per-query", type=int, default=5, help="Images per query (default 5)")
    p.add_argument(
        "--out",
        type=Path,
        default=OUT_DIR,
        help=f"Output folder (default: {OUT_DIR})",
    )
    args = p.parse_args(argv)
    try:
        paths = fetch_refs(per_query=args.per_query, out_dir=args.out)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0 if paths else 2


if __name__ == "__main__":
    raise SystemExit(main())
