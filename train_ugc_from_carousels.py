#!/usr/bin/env python3
"""
UGC retrain — HUMAN LABELS ONLY.

HARD RULE (audit 2026-09-28): NEVER train the supervised UGC model on
`ugc_score` produced by the same model or zero-shot formula. That creates a
self-training loop that locks in old mistakes.

Allowed sources:
  - probe human_votes (ok/bad vs pred) via train_ugc_from_probe.collect_samples
  - taste_votes JSON (keep/stock/wrong) — use train_ugc_from_taste_votes.py

This script used to auto-label carousel finals by meta ugc_score.
That path is permanently disabled.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("=" * 64)
    print("  BLOCKED: train_ugc_from_carousels (self-training loop)")
    print("=" * 64)
    print(
        "\nRefusing to label carousel finals from model ugc_score.\n"
        "Train ONLY on human labels:\n"
        "  python train_ugc_from_probe.py\n"
        "  python train_ugc_from_taste_votes.py <taste_votes.json>\n"
    )
    # Fail loudly if someone wires this into CI / batch
    raise AssertionError(
        "train_ugc_from_carousels.py is disabled: do not train UGC on "
        "model/zero-shot ugc_score. Use human probe/taste_votes only."
    )


# Guard imported helpers that previously auto-labeled from ugc_score
def harvest_carousel_run(run_dir: Path):  # noqa: ARG001
    raise AssertionError(
        "harvest_carousel_run disabled — auto labels from ugc_score forbidden"
    )


if __name__ == "__main__":
    raise SystemExit(main())
