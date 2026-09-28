#!/usr/bin/env python3
"""
Live-curate: ONE food topic → one carousel → stop.
Agent reviews winners before any further topics.

  python live_one_carousel.py
  python live_one_carousel.py --topic "Why you eat clean..."
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from core.batch_factory import run_batch  # noqa: E402
from core.harvester import FINAL_UGC_W, TASTE_ENABLED, UGC_HARD_FLOOR  # noqa: E402

DEFAULT = (
    "Why you eat clean all day only to lose your mind in the pantry at 10pm"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default=DEFAULT)
    args = ap.parse_args()
    topic = (args.topic or DEFAULT).strip()
    print(
        f"[LIVE] ONE carousel only · floor={UGC_HARD_FLOOR} "
        f"ugc_w={FINAL_UGC_W} taste={'ON' if TASTE_ENABLED else 'OFF'}",
        flush=True,
    )
    print(f"[LIVE] topic: {topic}", flush=True)
    result = run_batch(
        topics=[topic],
        product="",
        out_root=ROOT / "out",
        on_status=lambda m: print(m, flush=True),
    )
    print(
        f"[LIVE] DONE made={result.made} failed={result.failed} "
        f"dir={result.run_dir}",
        flush=True,
    )
    if result.run_dir:
        print(f"[LIVE] REVIEW: open slides in {result.run_dir}", flush=True)
    return 0 if result.made > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
