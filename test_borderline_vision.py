"""Smoke: borderline UGC needs vision KEEP (not formula auto-pass)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PIL import Image

from core.harvester import (
    BORDERLINE_VISION_ENABLED,
    UGC_HARD_FLOOR,
    ugc_eligible,
    ugc_is_borderline,
)
from core.local_gate import ollama_up, vision_borderline_is_live, list_models


def main() -> int:
    print("BORDERLINE_VISION_ENABLED =", BORDERLINE_VISION_ENABLED)
    print("UGC_HARD_FLOOR =", UGC_HARD_FLOOR)

    # unit: hard vs soft vs vibe
    cases = [
        (0.60, 0.20, "", False, True),   # hard → not borderline, eligible
        (0.50, 0.35, "", True, True),    # soft → borderline
        (0.40, 0.20, "", False, False),  # too low
        (0.35, 0.60, "rain on window night", True, True),  # vibe soft
    ]
    print("\n=== unit ugc_is_borderline ===")
    for ugc, rel, scene, want_b, want_e in cases:
        b = ugc_is_borderline(ugc, rel, visual_scene=scene, slide_text=scene)
        e = ugc_eligible(ugc, rel, visual_scene=scene, slide_text=scene)
        ok = (b == want_b) and (e == want_e)
        print(
            f"  ugc={ugc:.2f} rel={rel:.2f} scene={scene!r} "
            f"border={b} elig={e} {'OK' if ok else 'FAIL'}"
        )
        if not ok:
            return 1

    print("\n=== ollama / moondream ===")
    up = ollama_up()
    print("ollama_up =", up)
    if up:
        print("models =", [m for m in list_models() if "moon" in m or "qwen" in m][:8])

    imgs = sorted((ROOT / "out" / "style_pivot_test").glob("*.jpg"))[:3]
    if not imgs:
        print("no sample jpgs — skip live vision")
        return 0

    print("\n=== vision on sample photos ===")
    for p in imgs:
        im = Image.open(p).convert("RGB")
        r = vision_borderline_is_live(
            im, scene="confession night kitchen", slide_text="guilt binge"
        )
        print(
            f"  {p.name}: ok={r['ok']} keep={r['keep']} "
            f"score={r['score']} source={r['source']} · {r['why']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
