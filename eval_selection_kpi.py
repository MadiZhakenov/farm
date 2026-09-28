#!/usr/bin/env python3
"""
Block KPI: selection_mode / ugc / rel distribution from a run folder.

No generation — reads existing meta.json files.
Exit 1 if STRICT contract violated (soft-ship modes present) or quality gates fail.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Soft-ship modes forbidden under STRICT contract
_FORBIDDEN_MODES = frozenset(
    {"pool_soft_ugc", "guarantee_soft", "soft_rel_fallback"}
)
# Preferred healthy modes
_GOOD_MODES = frozenset(
    {"single_pass_argmax", "single_pass", "hard_top3_sample", "emergency_guarded", "guarantee"}
)


def _load_slides(run_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for meta in sorted(run_dir.glob("carousel_*/meta.json")):
        data = json.loads(meta.read_text(encoding="utf-8"))
        for s in data.get("slides") or []:
            rows.append(
                {
                    "carousel": meta.parent.name,
                    "index": s.get("index"),
                    "query": s.get("query"),
                    "mode": (s.get("selection_mode") or "").strip() or "unknown",
                    "ugc": s.get("ugc_score"),
                    "rel": s.get("text_relevance"),
                }
            )
    return rows


def evaluate_run(run_dir: Path) -> int:
    from core.harvester import (
        SELECT_RELEVANCE_MIN,
        STRICT_SELECTION_CONTRACT,
        UGC_HARD_FLOOR,
    )

    rows = _load_slides(run_dir)
    if not rows:
        print(f"FAIL: no slides in {run_dir}")
        return 1

    modes = Counter(r["mode"] for r in rows)
    ugcs = [float(r["ugc"]) for r in rows if r["ugc"] is not None]
    rels = [float(r["rel"]) for r in rows if r["rel"] is not None]

    print(f"=== KPI run={run_dir.name} slides={len(rows)} ===")
    print(f"STRICT_SELECTION_CONTRACT={STRICT_SELECTION_CONTRACT}")
    print(f"floors: ugc>={UGC_HARD_FLOOR:.2f} rel>={SELECT_RELEVANCE_MIN:.2f}")
    print("selection_mode:")
    for m, c in modes.most_common():
        flag = " FORBIDDEN" if m in _FORBIDDEN_MODES else ""
        print(f"  {m}: {c}{flag}")

    if ugcs:
        mean_u = sum(ugcs) / len(ugcs)
        below_u = sum(1 for u in ugcs if u < UGC_HARD_FLOOR)
        print(
            f"ugc: mean={mean_u:.3f} min={min(ugcs):.3f} "
            f"below_hard={below_u}/{len(ugcs)}"
        )
    if rels:
        mean_r = sum(rels) / len(rels)
        below_r = sum(1 for r in rels if r < SELECT_RELEVANCE_MIN)
        print(
            f"rel: mean={mean_r:.3f} min={min(rels):.3f} "
            f"below_hard={below_r}/{len(rels)}"
        )

    fails = 0
    if STRICT_SELECTION_CONTRACT:
        soft = sum(modes[m] for m in _FORBIDDEN_MODES if m in modes)
        if soft:
            print(f"FAIL: {soft} soft-ship slides under STRICT contract")
            fails += 1
        # Shipped slides should meet hard floors when scored
        if ugcs and any(u < UGC_HARD_FLOOR for u in ugcs):
            print("FAIL: shipped ugc below UGC_HARD_FLOOR")
            fails += 1
        if rels and any(r < SELECT_RELEVANCE_MIN for r in rels):
            print(
                "WARN: shipped rel below SELECT_RELEVANCE_MIN "
                "(legacy run may predate STRICT)"
            )
            # Don't fail hard on old runs — only warn
            if run_dir.name >= "run_20260925_120000":
                fails += 1

    good = sum(modes[m] for m in _GOOD_MODES if m in modes)
    print(f"good_mode_share={good}/{len(rows)}")
    print(f"=== DONE fails={fails} ===")
    return 1 if fails else 0


def main() -> int:
    if len(sys.argv) > 1:
        run_dir = Path(sys.argv[1])
    else:
        runs = sorted(
            (ROOT / "out").glob("run_*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not runs:
            print("No out/run_* found")
            return 1
        run_dir = runs[0]
        print(f"(using latest) {run_dir}")
    return evaluate_run(run_dir)


if __name__ == "__main__":
    raise SystemExit(main())
