#!/usr/bin/env python3
"""Re-run the 5 food-noise topics (current harvester flags)."""
from __future__ import annotations

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
from core.ugc_classifier import get_ugc_live_classifier  # noqa: E402

TOPICS = [
    "Why you eat clean all day only to lose your mind in the pantry at 10pm",
    "The hidden exhaustion behind counting every single almond in your head",
    "How to stop eating standing over the kitchen counter like a fugitive",
    "Signs your 'healthy lifestyle' is secretly just an eating disorder in gym clothes",
    "The brutal reality of food noise: why your brain never stops thinking about lunch",
]


def status(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    print(
        f"floor={UGC_HARD_FLOOR} ugc_w={FINAL_UGC_W} "
        f"taste={'ON' if TASTE_ENABLED else 'OFF'} "
        f"trained={get_ugc_live_classifier().is_trained}",
        flush=True,
    )
    result = run_batch(
        topics=TOPICS,
        product="",
        out_root=ROOT / "out",
        on_status=status,
    )
    print("DONE", result.made, result.failed, result.run_dir, flush=True)
    return 0 if result.made > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
