#!/usr/bin/env python3
"""
Agent-gated carousel pipeline.

Gates can be driven by Cursor agent OR local Ollama (qwen + moondream):

  # Cursor / manual
  python agent_gate.py new --topic "..."
  python agent_gate.py text
  python agent_gate.py approve text
  python agent_gate.py queries
  python agent_gate.py approve queries
  python agent_gate.py harvest-slide 1
  python agent_gate.py pick 1 --pin <id>
  python agent_gate.py approve picks
  python agent_gate.py render

  # Local LLM (no Cursor needed after start)
  python agent_gate.py approve text --llm
  python agent_gate.py approve queries --llm   # also prop-locks queries.json
  python agent_gate.py pick 1 --llm            # moondream ranks pool
  python agent_gate.py auto-local --topic "..."   # full run with local gates

Abort anytime: python agent_gate.py abort
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

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

SESSIONS = ROOT / "out" / "agent_sessions"
CURRENT = SESSIONS / "CURRENT"


def _slug(s: str, n: int = 40) -> str:
    x = re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")
    return (x[:n] or "topic").rstrip("_")


def _load_current() -> Path:
    if not CURRENT.exists():
        raise SystemExit("No active session. Run: python agent_gate.py new --topic ...")
    p = Path(CURRENT.read_text(encoding="utf-8").strip())
    if not p.is_dir():
        raise SystemExit(f"Broken CURRENT → {p}")
    return p


def _state(sess: Path) -> dict[str, Any]:
    sp = sess / "state.json"
    return json.loads(sp.read_text(encoding="utf-8"))


def _save_state(sess: Path, st: dict[str, Any]) -> None:
    st["updated_at"] = datetime.now().isoformat(timespec="seconds")
    (sess / "state.json").write_text(
        json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _print_gate(msg: str) -> None:
    print("\n" + "=" * 60, flush=True)
    print(f"  AGENT GATE: {msg}", flush=True)
    print("=" * 60 + "\n", flush=True)


def cmd_new(topic: str) -> int:
    SESSIONS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sess = SESSIONS / f"sess_{ts}_{_slug(topic)}"
    sess.mkdir(parents=True)
    (sess / "slides").mkdir()
    st = {
        "topic": topic,
        "stage": "new",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "gates": {
            "text": False,
            "queries": False,
            "pools": False,
            "picks": False,
        },
        "n_slides": 0,
        "harvested_slides": [],
        "picked_slides": [],
    }
    _save_state(sess, st)
    CURRENT.write_text(str(sess), encoding="utf-8")
    print(f"[agent] session → {sess}", flush=True)
    _print_gate("Next: python agent_gate.py text")
    return 0


def cmd_status() -> int:
    sess = _load_current()
    st = _state(sess)
    print(json.dumps({"session": str(sess), **st}, ensure_ascii=False, indent=2))
    return 0


def cmd_text() -> int:
    sess = _load_current()
    st = _state(sess)
    from core.llm_engine import OllamaGenerator
    from core.taste_embedder import get_embedder

    try:
        get_embedder().ensure()
    except Exception as exc:
        print(f"[warn] SigLIP warm: {exc}", flush=True)

    llm = OllamaGenerator()
    print(f"[agent] Gemini · {st['topic']!r}…", flush=True)
    result = llm.generate_carousel(
        st["topic"], product_name="", variation_index=0
    )
    slides_raw = result.get("slides") or []
    slides = []
    for i, s in enumerate(slides_raw):
        text = str(s.get("text") or "").strip()
        if not text:
            continue
        slides.append(
            {
                "index": i + 1,
                "text": text,
                "draft_query": str(s.get("search_query") or "").strip(),
                "visual_scene": str(s.get("visual_scene") or "").strip(),
            }
        )
    if len(slides) < 5:
        raise SystemExit(f"Too few slides: {len(slides)}")
    slides = slides[:9]
    dna = result.get("character_dna")
    if not isinstance(dna, dict):
        dna = None
    (sess / "texts.json").write_text(
        json.dumps(
            {
                "topic": st["topic"],
                "model": result.get("model"),
                "dna_archetype": result.get("dna_archetype"),
                "character_dna": dna,
                "slides": slides,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    st["stage"] = "text"
    st["n_slides"] = len(slides)
    st["gates"]["text"] = False
    _save_state(sess, st)
    print(f"[agent] wrote texts.json · {len(slides)} slides", flush=True)
    for s in slides:
        print(f"  [{s['index']}] {s['text'][:80]}…", flush=True)
        print(f"       scene: {s['visual_scene'][:70]}", flush=True)
    _print_gate(
        "Read texts.json. If OK → python agent_gate.py approve text && "
        "python agent_gate.py queries\n"
        "  If text is junk → abort / new topic. Do NOT harvest yet."
    )
    return 0


def cmd_queries() -> int:
    sess = _load_current()
    st = _state(sess)
    if not (sess / "texts.json").exists():
        raise SystemExit("Need texts first")
    data = json.loads((sess / "texts.json").read_text(encoding="utf-8"))
    dna = data.get("character_dna")
    from core.query_forge import own_slide_queries, vibe_rescue_queries

    rows = []
    for s in data["slides"]:
        primary, alts = own_slide_queries(
            slide_text=s["text"],
            visual_scene=s.get("visual_scene") or "",
            topic=st["topic"],
            slide_index=s["index"] - 1,
            draft_query=s.get("draft_query") or "",
            character_dna=dna if isinstance(dna, dict) else None,
            max_alts=2,
        )
        avoid = {primary.lower(), *(a.lower() for a in alts)}
        rescues = vibe_rescue_queries(
            slide_text=s["text"],
            visual_scene=s.get("visual_scene") or "",
            topic=st["topic"],
            avoid=avoid,
            max_n=2,
        )
        rows.append(
            {
                "index": s["index"],
                "text": s["text"],
                "visual_scene": s.get("visual_scene") or "",
                "primary": primary,
                "alts": alts,
                "vibe_rescue": rescues,
                "agent_note": "",
            }
        )
        print(
            f"  [{s['index']}] primary={primary!r} alts={alts} rescue={rescues}",
            flush=True,
        )
    (sess / "queries.json").write_text(
        json.dumps({"topic": st["topic"], "slides": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    st["stage"] = "queries"
    st["gates"]["queries"] = False
    _save_state(sess, st)
    _print_gate(
        "Edit queries.json if primary misses the prop.\n"
        "  Then: python agent_gate.py approve queries\n"
        "  Then: python agent_gate.py harvest-slide 1\n"
        "  Do NOT run all slides until slide 1 pool looks good."
    )
    return 0


def cmd_approve(what: str, *, llm: bool = False) -> int:
    sess = _load_current()
    st = _state(sess)
    if what not in st["gates"] and what != "pools":
        raise SystemExit(f"Unknown gate: {what}")

    if llm and what == "text":
        from core.local_gate import approve_texts

        tpath = sess / "texts.json"
        texts = json.loads(tpath.read_text(encoding="utf-8"))
        verdict = approve_texts(texts)
        print(
            f"[local_gate] text approve={verdict['approve']} "
            f"source={verdict['source']} · {verdict['reason']}",
            flush=True,
        )
        for p in verdict.get("problems") or []:
            print(f"  · {p}", flush=True)
        if not verdict["approve"]:
            (sess / "local_gate_text.json").write_text(
                json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            raise SystemExit(
                "Local gate REJECTED texts. Fix texts.json then retry "
                "`approve text --llm` (see local_gate_text.json)."
            )
        # Scrub stale DNA archetype label when approving
        if texts.get("dna_archetype") and "study" in str(texts["dna_archetype"]).lower():
            texts["dna_archetype"] = "local_gate_approved"
            texts["character_dna"] = {}
            tpath.write_text(
                json.dumps(texts, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    if llm and what == "queries":
        from core.local_gate import approve_queries

        qpath = sess / "queries.json"
        tpath = sess / "texts.json"
        queries = json.loads(qpath.read_text(encoding="utf-8"))
        texts = (
            json.loads(tpath.read_text(encoding="utf-8")) if tpath.exists() else None
        )
        verdict = approve_queries(queries, texts)
        # Always write prop-locked queries back
        locked = verdict.get("queries") or queries
        qpath.write_text(
            json.dumps(locked, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for n in verdict.get("notes") or []:
            print(f"  [prop-lock] {n}", flush=True)
        print(
            f"[local_gate] queries approve={verdict['approve']} "
            f"source={verdict['source']} · {verdict['reason']}",
            flush=True,
        )
        for p in verdict.get("problems") or []:
            print(f"  · {p}", flush=True)
        (sess / "local_gate_queries.json").write_text(
            json.dumps(
                {k: v for k, v in verdict.items() if k != "queries"},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if not verdict["approve"]:
            raise SystemExit(
                "Local gate REJECTED queries after prop-lock. "
                "Edit queries.json and retry."
            )

    if what == "pools":
        st["gates"]["pools"] = True
    else:
        st["gates"][what] = True
    _save_state(sess, st)
    who = "local_gate" if llm else "agent"
    print(f"[{who}] gate «{what}» = APPROVED", flush=True)
    return 0


def cmd_pick(
    slide_no: int,
    pin: str | None,
    index: int | None,
    *,
    llm: bool = False,
) -> int:
    sess = _load_current()
    st = _state(sess)
    scores_path = sess / "slides" / f"{slide_no:02d}" / "scores.json"
    if not scores_path.exists():
        raise SystemExit(f"No pool for slide {slide_no}. harvest-slide first.")
    data = json.loads(scores_path.read_text(encoding="utf-8"))

    if llm:
        from core.local_gate import pick_from_pool

        print(f"[local_gate] vision-pick slide {slide_no}…", flush=True)
        verdict = pick_from_pool(sess=sess, slide_no=slide_no, scores=data)
        (sess / "slides" / f"{slide_no:02d}" / "local_gate_pick.json").write_text(
            json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        pin = verdict.get("pin_id")
        if not pin:
            raise SystemExit(f"Local gate could not pick slide {slide_no}: {verdict}")
        print(
            f"[local_gate] chose {pin} · {verdict.get('source')} · "
            f"{verdict.get('reason')}",
            flush=True,
        )

    cand = None
    if pin:
        cand = next((c for c in data["candidates"] if c["pin_id"] == pin), None)
        if not cand:
            # allow suffix match
            cand = next(
                (c for c in data["candidates"] if c["pin_id"].endswith(pin)), None
            )
    elif index is not None:
        # index among PASS only, else raw
        passes = [c for c in data["candidates"] if c["verdict"].startswith("PASS")]
        pool = passes if passes else data["candidates"]
        if index < 0 or index >= len(pool):
            raise SystemExit(f"index {index} out of range 0..{len(pool)-1}")
        cand = pool[index]
    else:
        raise SystemExit("Need --pin, --index, or --llm")
    if not cand:
        raise SystemExit("Candidate not found")

    data["pick"] = {
        "pin_id": cand["pin_id"],
        "file": cand["file"],
        "ugc": cand["ugc"],
        "rel": cand["rel"],
        "verdict": cand["verdict"],
        "agent_picked_at": datetime.now().isoformat(timespec="seconds"),
        "picker": "local_gate" if llm else "agent",
    }
    scores_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    picks_path = sess / "picks.json"
    picks = {"slides": {}}
    if picks_path.exists():
        picks = json.loads(picks_path.read_text(encoding="utf-8"))
    picks.setdefault("slides", {})[str(slide_no)] = data["pick"]
    picks_path.write_text(
        json.dumps(picks, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    picked = list(st.get("picked_slides") or [])
    if slide_no not in picked:
        picked.append(slide_no)
    st["picked_slides"] = sorted(picked)
    st["gates"]["picks"] = False
    _save_state(sess, st)
    who = "local_gate" if llm else "agent"
    print(
        f"[{who}] pick slide {slide_no} → {cand['pin_id']} "
        f"({cand['verdict']} ugc={cand['ugc']:.0%} rel={cand['rel']:.0%})",
        flush=True,
    )
    nxt = slide_no + 1
    if nxt <= int(st.get("n_slides") or 0):
        _print_gate(
            f"Pick locked for slide {slide_no}.\n"
            f"  Next: python agent_gate.py harvest-slide {nxt}\n"
            f"  (still do NOT render until all slides picked + approve picks)"
        )
    else:
        _print_gate(
            "All slides have pools/picks path done.\n"
            "  python agent_gate.py approve picks\n"
            "  python agent_gate.py render"
        )
    return 0


def cmd_auto_local(topic: str) -> int:
    """
    Full carousel with local Ollama gates (no Cursor).
    Still stage-based internally; stops on reject.
    Requires: ollama serve + qwen2.5:7b (+ moondream for picks).
    """
    from core.local_gate import ollama_up, list_models

    if not ollama_up():
        raise SystemExit(
            "Ollama not running. Start it, then: python setup_ollama.py"
        )
    print(f"[auto-local] models={list_models()}", flush=True)
    cmd_new(topic)
    rc = cmd_text()
    if rc:
        return rc
    rc = cmd_approve("text", llm=True)
    if rc:
        return rc
    rc = cmd_queries()
    if rc:
        return rc
    rc = cmd_approve("queries", llm=True)
    if rc:
        return rc
    sess = _load_current()
    st = _state(sess)
    n = int(st.get("n_slides") or 0)
    for i in range(1, n + 1):
        rc = cmd_harvest_slide(i)
        if rc:
            return rc
        rc = cmd_pick(i, pin=None, index=None, llm=True)
        if rc:
            return rc
    rc = cmd_approve("picks", llm=False)
    if rc:
        return rc
    return cmd_render()


def cmd_harvest_slide(slide_no: int) -> int:
    sess = _load_current()
    st = _state(sess)
    if not st["gates"].get("queries"):
        raise SystemExit("Approve queries first: python agent_gate.py approve queries")
    qdata = json.loads((sess / "queries.json").read_text(encoding="utf-8"))
    tdata = json.loads((sess / "texts.json").read_text(encoding="utf-8"))
    dna = tdata.get("character_dna")
    row = next((s for s in qdata["slides"] if s["index"] == slide_no), None)
    if not row:
        raise SystemExit(f"No slide {slide_no} in queries.json")

    from core.harvester import (
        UGC_HARD_FLOOR,
        PinterestHarvester,
        candidate_final_score,
        select_relevance_min,
        ugc_eligible,
    )

    slide_dir = sess / "slides" / f"{slide_no:02d}"
    pool_dir = slide_dir / "pool"
    pool_dir.mkdir(parents=True, exist_ok=True)
    # clear old pool
    for old in pool_dir.glob("*.jpg"):
        old.unlink()

    h = PinterestHarvester()
    h.warm_session(force=False)
    if isinstance(dna, dict):
        # seed nothing special; locks applied at score time if we use judge
        pass

    chain = [
        row["primary"],
        *(row.get("alts") or []),
        *(row.get("vibe_rescue") or []),
    ]
    # dedupe
    seen_q: set[str] = set()
    queries: list[str] = []
    for q in chain:
        q = re.sub(r"\s+", " ", (q or "").strip())
        if q and q.lower() not in seen_q:
            seen_q.add(q.lower())
            queries.append(q)
    queries = queries[:4]

    text = row["text"]
    scene = row.get("visual_scene") or ""
    all_rows: list[dict[str, Any]] = []
    seen_pins: set[str] = set()

    print(f"[agent] harvest slide {slide_no} · queries={queries}", flush=True)
    for qi, q in enumerate(queries):
        label = "primary" if qi == 0 else f"q{qi}"
        cands, _ = h.harvest_for_query(
            q,
            limit=8,
            slide_text=text,
            slide_index=slide_no - 1,
            allow_broaden=False,
            apply_score=False,
            _allow_emergency=False,
            visual_scene=scene,
        )
        fresh = []
        for c in cands:
            pid = str(c.pin_id)
            if pid in seen_pins:
                continue
            seen_pins.add(pid)
            fresh.append(c)
        if not fresh:
            print(f"  [{label}] 0 unique", flush=True)
            continue
        # score keep-all
        h._apply_text_relevance_gate(
            fresh, slide_text=text, query=q, visual_scene=scene
        )
        try:
            from core.ugc_filter import get_ugc_filter

            scores = get_ugc_filter().get_ugc_scores([c.image for c in fresh])
            for c, s in zip(fresh, scores):
                c.ugc_score = float(s)
                c.ugc_scored = True
        except Exception as exc:
            print(f"  [ugc] {exc}", flush=True)
            for c in fresh:
                c.ugc_score = 0.5
        for c in fresh:
            c.taste_score = 0.5

        for i, c in enumerate(fresh):
            ugc = float(c.ugc_score or 0)
            rel = float(getattr(c, "text_relevance", 0) or 0)
            final = float(candidate_final_score(rel, ugc, 100.0, taste=0.5))
            rel_min = select_relevance_min(
                query=q, visual_scene=scene, slide_text=text
            )
            ok = (
                ugc_eligible(
                    ugc, rel, visual_scene=scene, query=q, slide_text=text
                )
                and rel >= rel_min
            )
            soft = ok and ugc < UGC_HARD_FLOOR
            verdict = "PASS_SOFT" if soft else ("PASS" if ok else "DROP")
            if not ok:
                reasons = []
                if not ugc_eligible(
                    ugc, rel, visual_scene=scene, query=q, slide_text=text
                ):
                    reasons.append("ugc")
                if rel < rel_min:
                    reasons.append("rel")
                verdict = "DROP:" + ",".join(reasons)
            fname = (
                f"{label}_{i:02d}_{verdict.replace(':', '_').replace(',', '-')}"
                f"_{str(c.pin_id)[-8:]}.jpg"
            )
            path = pool_dir / fname
            try:
                c.image.convert("RGB").save(path, quality=85, optimize=True)
            except Exception:
                continue
            all_rows.append(
                {
                    "pin_id": str(c.pin_id),
                    "file": str(path.relative_to(sess)),
                    "ugc": round(ugc, 4),
                    "rel": round(rel, 4),
                    "final": round(final, 4),
                    "verdict": verdict,
                    "query": q,
                    "label": label,
                }
            )
            print(
                f"  {fname}: ugc={ugc:.0%} rel={rel:.0%} → {verdict}",
                flush=True,
            )

    all_rows.sort(key=lambda r: -r["final"])
    scores_path = slide_dir / "scores.json"
    scores_path.write_text(
        json.dumps(
            {
                "slide": slide_no,
                "text": text,
                "scene": scene,
                "queries": queries,
                "n": len(all_rows),
                "pass_n": sum(1 for r in all_rows if r["verdict"].startswith("PASS")),
                "candidates": all_rows,
                "pick": None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    harvested = list(st.get("harvested_slides") or [])
    if slide_no not in harvested:
        harvested.append(slide_no)
    st["harvested_slides"] = sorted(harvested)
    st["stage"] = f"pool_{slide_no}"
    st["gates"]["pools"] = False
    _save_state(sess, st)

    pass_n = sum(1 for r in all_rows if r["verdict"].startswith("PASS"))
    _print_gate(
        f"Slide {slide_no} pool ready · {pass_n}/{len(all_rows)} PASS\n"
        f"  Folder: {pool_dir}\n"
        f"  AGENT MUST Read the jpgs now.\n"
        f"  If junk queries → edit queries.json, re-run harvest-slide {slide_no}\n"
        f"  If good frame → python agent_gate.py pick {slide_no} --pin <pin_id>\n"
        f"  If whole pool is шлак → abort. Do NOT harvest slide {slide_no + 1} yet."
    )
    return 0


def cmd_render() -> int:
    sess = _load_current()
    st = _state(sess)
    if not st["gates"].get("picks"):
        raise SystemExit("Approve picks first: python agent_gate.py approve picks")
    picks = json.loads((sess / "picks.json").read_text(encoding="utf-8"))
    tdata = json.loads((sess / "texts.json").read_text(encoding="utf-8"))
    n = int(st["n_slides"])
    for i in range(1, n + 1):
        if str(i) not in picks.get("slides", {}):
            raise SystemExit(f"Missing pick for slide {i}")

    from core.renderer import render_slide
    from PIL import Image

    out = sess / "carousel"
    out.mkdir(exist_ok=True)
    meta_slides = []
    for i in range(1, n + 1):
        text = next(s["text"] for s in tdata["slides"] if s["index"] == i)
        pick = picks["slides"][str(i)]
        src = sess / pick["file"]
        if not src.exists():
            raise SystemExit(f"Missing image {src}")
        img = Image.open(src).convert("RGB")
        rendered, rmeta = render_slide(img, text)
        dest = out / f"{i}.jpg"
        rendered.save(dest, quality=92, optimize=True)
        meta_slides.append(
            {
                "index": i,
                "text": text,
                "pin_id": pick["pin_id"],
                "ugc_score": pick["ugc"],
                "text_relevance": pick["rel"],
                "file": f"{i}.jpg",
                "selection_mode": "agent_pick",
            }
        )
        print(f"[agent] rendered {dest}", flush=True)

    meta = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "topic": st["topic"],
        "character_dna": tdata.get("character_dna"),
        "agent_session": str(sess),
        "slides": meta_slides,
    }
    (out / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    st["stage"] = "rendered"
    _save_state(sess, st)
    _print_gate(f"Rendered → {out}\n  Agent: Read {out}/1.jpg … for final QA.")
    return 0


def cmd_abort() -> int:
    if CURRENT.exists():
        sess = CURRENT.read_text(encoding="utf-8").strip()
        CURRENT.unlink()
        print(f"[agent] aborted session {sess}", flush=True)
    else:
        print("[agent] no current session", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent-gated carousel pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new")
    p_new.add_argument("--topic", required=True)

    p_auto = sub.add_parser(
        "auto-local",
        help="Full run with Ollama gates (qwen text/queries, moondream picks)",
    )
    p_auto.add_argument("--topic", required=True)

    sub.add_parser("status")
    sub.add_parser("text")
    sub.add_parser("queries")

    p_ap = sub.add_parser("approve")
    p_ap.add_argument("what", choices=["text", "queries", "pools", "picks"])
    p_ap.add_argument(
        "--llm",
        action="store_true",
        help="Use local Ollama gate (text critic / query prop-lock)",
    )

    p_hs = sub.add_parser("harvest-slide")
    p_hs.add_argument("slide", type=int)

    p_pick = sub.add_parser("pick")
    p_pick.add_argument("slide", type=int)
    p_pick.add_argument("--pin", default=None)
    p_pick.add_argument("--index", type=int, default=None)
    p_pick.add_argument(
        "--llm",
        action="store_true",
        help="Use local moondream to pick from pool",
    )

    sub.add_parser("render")
    sub.add_parser("abort")

    args = ap.parse_args()
    if args.cmd == "new":
        return cmd_new(args.topic)
    if args.cmd == "auto-local":
        return cmd_auto_local(args.topic)
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "text":
        return cmd_text()
    if args.cmd == "queries":
        return cmd_queries()
    if args.cmd == "approve":
        return cmd_approve(args.what, llm=bool(getattr(args, "llm", False)))
    if args.cmd == "harvest-slide":
        return cmd_harvest_slide(args.slide)
    if args.cmd == "pick":
        return cmd_pick(
            args.slide,
            args.pin,
            args.index,
            llm=bool(getattr(args, "llm", False)),
        )
    if args.cmd == "render":
        return cmd_render()
    if args.cmd == "abort":
        return cmd_abort()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
