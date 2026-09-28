#!/usr/bin/env python3
"""
Dump FULL scored pools (including below-floor rejects) for parallel human/agent judge.

Saves every downloaded candidate with system scores + gate verdicts.
Does NOT change production floors — audit only.

  python audit_parallel_judge.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from core.harvester import (  # noqa: E402
    SELECT_RELEVANCE_MIN,
    UGC_HARD_FLOOR,
    PinterestHarvester,
    candidate_final_score,
    ugc_eligible,
)
from core.query_forge import own_slide_queries, vibe_rescue_queries  # noqa: E402

OUT = ROOT / "out" / "parallel_judge"
SLIDES = [
    {
        "id": "pantry_10pm",
        "text": "I eat clean all day then lose my mind in the pantry at 10pm",
        "scene": "open pantry door at night, hand reaching for snacks on a shelf",
        "topic": "pantry binge at night",
    },
    {
        "id": "almonds_desk",
        "text": "counting every single almond in my head at my desk",
        "scene": "handful of almonds next to a notebook on a desk",
        "topic": "counting almonds",
    },
    {
        "id": "counter_fugitive",
        "text": "eating standing over the kitchen counter like a fugitive",
        "scene": "person standing at messy kitchen counter eating from a plate",
        "topic": "kitchen counter eating",
    },
]


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40]


def score_keep_all(h: PinterestHarvester, cands, *, text: str, query: str, scene: str):
    """Run same gates as production but KEEP rejects with reasons."""
    if not cands:
        return []
    # relevance
    h._apply_text_relevance_gate(cands, slide_text=text, query=query, visual_scene=scene)
    # ugc
    try:
        from core.ugc_filter import get_ugc_filter

        scores = get_ugc_filter().get_ugc_scores([c.image for c in cands])
        for c, s in zip(cands, scores):
            c.ugc_score = float(s)
            c.ugc_scored = True
    except Exception as exc:
        print(f"[ugc] fail: {exc}")
        for c in cands:
            c.ugc_score = 0.5
            c.ugc_scored = False
    # taste off
    for c in cands:
        if not getattr(c, "taste_scored", False):
            c.taste_score = 0.5
    rows = []
    for c in cands:
        ugc = float(c.ugc_score or 0)
        rel = float(getattr(c, "text_relevance", 0) or 0)
        taste = float(c.taste_score or 0)
        final = float(
            candidate_final_score(rel, ugc, 100.0, taste=taste)
        )
        drops = []
        if not ugc_eligible(ugc, rel):
            drops.append(f"ugc<{UGC_HARD_FLOOR:.0%}")
        if rel < SELECT_RELEVANCE_MIN:
            drops.append(f"rel<{SELECT_RELEVANCE_MIN:.0%}")
        if not drops and ugc < UGC_HARD_FLOOR:
            verdict = "PASS_SOFT"
        else:
            verdict = "PASS" if not drops else "DROP:" + ",".join(drops)
        c.combined_score = final
        rows.append(
            {
                "pin_id": str(c.pin_id),
                "ugc": round(ugc, 4),
                "rel": round(rel, 4),
                "taste": round(taste, 4),
                "final": round(final, 4),
                "system_verdict": verdict,
                "query": query,
            }
        )
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    h = PinterestHarvester()
    h.warm_session(force=False)
    report: list[dict] = []

    for slide in SLIDES:
        sid = slide["id"]
        text, scene, topic = slide["text"], slide["scene"], slide["topic"]
        primary, alts = own_slide_queries(
            slide_text=text,
            visual_scene=scene,
            topic=topic,
            draft_query="",
            max_alts=2,
        )
        avoid = {primary.lower(), *(a.lower() for a in alts)}
        rescues = vibe_rescue_queries(
            slide_text=text,
            visual_scene=scene,
            topic=topic,
            avoid=avoid,
            max_n=2,
        )
        queries = [primary, *alts, *rescues]
        print(f"\n=== {sid} ===", flush=True)
        print(f"text: {text}", flush=True)
        print(f"queries: {queries}", flush=True)

        slide_dir = OUT / sid
        slide_dir.mkdir(parents=True, exist_ok=True)
        all_rows: list[dict] = []
        seen: set[str] = set()

        for qi, q in enumerate(queries[:4]):  # cap 4 searches
            label = "primary" if qi == 0 else f"q{qi}"
            print(f"  [{label}] search «{q}»…", flush=True)
            t0 = time.perf_counter()
            cands, _prog = h.harvest_for_query(
                q,
                limit=8,
                slide_text=text,
                slide_index=0,
                allow_broaden=False,
                apply_score=False,
                _allow_emergency=False,
                visual_scene=scene,
            )
            # already trimmed by rescue cap when broaden=False
            fresh = []
            for c in cands:
                pid = str(c.pin_id)
                if pid in seen:
                    continue
                seen.add(pid)
                fresh.append(c)
            print(
                f"  [{label}] downloaded {len(fresh)} unique "
                f"({time.perf_counter() - t0:.1f}s)",
                flush=True,
            )
            if not fresh:
                continue
            rows = score_keep_all(h, fresh, text=text, query=q, scene=scene)
            for i, (c, row) in enumerate(zip(fresh, rows)):
                fname = f"{label}_{i:02d}_{_slug(row['system_verdict'])}_{pid_short(c.pin_id)}.jpg"
                path = slide_dir / fname
                try:
                    c.image.convert("RGB").save(path, quality=85, optimize=True)
                except Exception as exc:
                    print(f"  save fail: {exc}")
                    continue
                row["file"] = str(path.relative_to(OUT))
                row["label"] = label
                all_rows.append(row)
                print(
                    f"    {fname}: ugc={row['ugc']:.0%} rel={row['rel']:.0%} "
                    f"→ {row['system_verdict']}",
                    flush=True,
                )

        slide_report = {
            "id": sid,
            "text": text,
            "scene": scene,
            "topic": topic,
            "queries": queries,
            "n": len(all_rows),
            "pass_n": sum(1 for r in all_rows if r["system_verdict"] == "PASS"),
            "drop_ugc": sum(1 for r in all_rows if "ugc<" in r["system_verdict"]),
            "drop_rel": sum(1 for r in all_rows if "rel<" in r["system_verdict"]),
            "candidates": sorted(all_rows, key=lambda r: -r["final"]),
        }
        (slide_dir / "scores.json").write_text(
            json.dumps(slide_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report.append(slide_report)
        print(
            f"  SUMMARY {sid}: {slide_report['pass_n']}/{slide_report['n']} PASS "
            f"(ugc_drop={slide_report['drop_ugc']} rel_drop={slide_report['drop_rel']})",
            flush=True,
        )

    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nDONE → {OUT}", flush=True)
    return 0


def pid_short(pid: str) -> str:
    s = str(pid)
    return s[-8:] if len(s) > 8 else s


if __name__ == "__main__":
    raise SystemExit(main())
