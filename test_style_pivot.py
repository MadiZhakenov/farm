"""
Test easy context-fit pivots (not coffee-always).

Shows: different slide moods → different easy high-yield queries.
Saves winners to out/style_pivot_test/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.harvester import PinterestHarvester
from core.query_forge import _mood_buckets_for_text, style_pivot_queries

OUT = ROOT / "out" / "style_pivot_test"
OUT.mkdir(parents=True, exist_ok=True)

CASES = [
    {
        "name": "quinoa_meal_prep",
        "topic": "food noise guilt",
        "slide_text": "I meal prepped quinoa bowls for the week and ate none of them",
        "visual_scene": "organized quinoa meal prep containers fridge shelf",
        "avoid_extra": [
            "quinoa meal prep",
            "meal prep containers",
            "organized fridge shelf",
            "quinoa bowls fridge",
        ],
    },
    {
        "name": "protein_scale_spiral",
        "topic": "binge recovery confession",
        "slide_text": "weighing every almond on a food scale at 1am again",
        "visual_scene": "kitchen food scale almonds night counter",
        "avoid_extra": [
            "kitchen food scale",
            "almonds on desk",
            "almonds kitchen candid",
            "food scale night",
        ],
    },
    {
        "name": "cant_sleep_phone",
        "topic": "anxiety spiral",
        "slide_text": "it's 2am and I still can't sleep so I'm doomscrolling again",
        "visual_scene": "phone glow in dark bedroom pillow",
        "avoid_extra": [
            "phone glow bedroom",
            "doomscrolling phone bed",
        ],
    },
    {
        "name": "skipped_gym",
        "topic": "fitness guilt",
        "slide_text": "paid for the gym membership and drove past it again",
        "visual_scene": "car parked outside gym entrance",
        "avoid_extra": [
            "car parked gym",
            "gym entrance outside",
        ],
    },
]


def main() -> int:
    print("=== unit: mood -> easy queries (no harvest) ===")
    for case in CASES:
        blob = f"{case['slide_text']} {case['visual_scene']} {case['topic']}"
        moods = _mood_buckets_for_text(blob)
        pivots = style_pivot_queries(
            max_n=4,
            slide_text=case["slide_text"],
            visual_scene=case["visual_scene"],
            topic=case["topic"],
        )
        print(f"\n[{case['name']}] moods={moods}")
        for p in pivots:
            print(f"  - {p}")

    print("\n=== live: guarantee -> easy context pivot ===")
    h = PinterestHarvester()
    # Mark pins used across cases so we don't repeat the same photo
    used_pins: set[str] = set()
    summary = []

    for i, case in enumerate(CASES):
        name = case["name"]
        print(f"\n--- CASE {i + 1}: {name} ---")
        avoid = {a.lower() for a in case["avoid_extra"]}
        moods = _mood_buckets_for_text(
            f"{case['slide_text']} {case['visual_scene']} {case['topic']}"
        )
        planned = style_pivot_queries(
            max_n=4,
            avoid=avoid,
            slide_text=case["slide_text"],
            visual_scene=case["visual_scene"],
            topic=case["topic"],
        )
        print(f"moods={moods}")
        print(f"planned pivots={planned}")

        kept, win_q = h.guarantee_at_least_one(
            slide_text=case["slide_text"],
            slide_index=i,
            preferred_query=case["avoid_extra"][0],
            limit=1,
            topic=case["topic"],
            visual_scene=case["visual_scene"],
            avoid_queries=avoid,
            searches_budget=5,
            allow_soft=False,
        )
        # If same pin as earlier case, try once more with that pin avoided via ignore
        # (harvester marks used on select; for this smoke test just note duplicates)
        row = {
            "name": name,
            "moods": moods,
            "planned_pivots": planned,
            "win_query": win_q,
            "n_kept": len(kept),
            "mode": kept[0].selection_mode if kept else None,
            "reason": kept[0].relevance_reason if kept else None,
            "ugc": round(float(kept[0].ugc_score), 3) if kept else None,
            "rel": round(float(kept[0].text_relevance), 3) if kept else None,
            "pin_id": getattr(kept[0], "pin_id", None) if kept else None,
        }
        print(json.dumps(
            {k: row[k] for k in ("name", "win_query", "mode", "ugc", "moods")},
            ensure_ascii=False,
            indent=2,
        ))

        if kept:
            pid = str(getattr(kept[0], "pin_id", "") or "")
            row["duplicate_pin"] = pid in used_pins and bool(pid)
            if pid:
                used_pins.add(pid)
            dest = OUT / f"{i + 1}_{name}.jpg"
            kept[0].image.convert("RGB").save(dest, quality=90)
            row["saved"] = str(dest)
            print(f"saved -> {dest}")
        else:
            row["duplicate_pin"] = False
            row["saved"] = None

        summary.append(row)

    report = OUT / "report.json"
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== REPORT -> {report} ===")
    for r in summary:
        print(
            f"  [{r.get('mode')}] {r['name']}: moods={r['moods'][:2]} "
            f"q=«{r['win_query']}» ugc={r['ugc']}"
        )
    ok = sum(1 for r in summary if r["n_kept"] > 0)
    print(f"\nfilled {ok}/{len(summary)}")
    return 0 if ok == len(summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
