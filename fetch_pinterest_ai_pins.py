#!/usr/bin/env python3
"""
Скачать пины, которые Pinterest сам пометил как ИИ (is_ai в выдаче), из
search_cache.json замеров — примеры «ИИ / рендер» для детектора.

  python fetch_pinterest_ai_pins.py --src out/query_liveness_v2 ... --n 300 --out out/pinterest_ai_pins
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from build_label_pack import download  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, nargs="+", required=True)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--exclude", type=Path, default=None, help="pack.json — эти пины не брать")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    skip = set()
    if args.exclude and args.exclude.exists():
        skip = {r["pin_id"] for r in json.loads(args.exclude.read_text(encoding="utf-8"))}
    metas: dict[str, dict] = {}
    for src in args.src:
        f = src / "search_cache.json"
        if f.exists():
            for q, pins in json.loads(f.read_text(encoding="utf-8")).items():
                for p in pins:
                    if p.get("is_ai") is True and str(p["pin_id"]) not in skip:
                        metas.setdefault(str(p["pin_id"]), {**p, "search": q})
    pins = list(metas.values())
    random.Random(3).shuffle(pins)
    rows = [{"pin_id": str(p["pin_id"]), "search": p["search"], "thumb": ""} for p in pins[: args.n]]
    (args.out / "imgs").mkdir(parents=True, exist_ok=True)
    asyncio.run(download(rows, metas, args.out / "imgs"))
    rows = [r for r in rows if r.get("file")]
    (args.out / "pins.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ИИ-пинов Pinterest: {len(metas)} · скачано {len(rows)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
