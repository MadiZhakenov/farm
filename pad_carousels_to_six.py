#!/usr/bin/env python3
"""Pad 5-slide carousels in a run to 6: insert body before CTA, harvest + render."""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

RUN = ROOT / "out" / "run_20260928_131535"


def _load_meta(folder: Path) -> dict[str, Any]:
    return json.loads((folder / "meta.json").read_text(encoding="utf-8"))


def _save_meta(folder: Path, meta: dict[str, Any]) -> None:
    (folder / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _gen_body_slide(
    *,
    topic: str,
    existing: list[dict[str, Any]],
    dna: dict[str, Any] | None,
) -> dict[str, str]:
    import httpx
    from core.llm_engine import (
        GeminiGenerator,
        GEMINI_API_BASE,
        GEMINI_MAX_OUTPUT_TOKENS,
    )

    eng = GeminiGenerator()
    api_key = eng._api_key_or_raise()
    lines = [
        f"TOPIC: {topic}",
        "TASK: Write ONE extra middle body slide for an existing Instagram carousel.",
        "It will be inserted BEFORE the final CTA. Match the tired-honest confession voice.",
        "Do NOT repeat existing slides. Do NOT write a CTA (no Save/Send).",
        "Return JSON only with keys text, visual_scene, search_query.",
        "",
        "EXISTING SLIDES:",
    ]
    for i, s in enumerate(existing, 1):
        role = "hook" if i == 1 else ("cta" if i == len(existing) else "body")
        lines.append(f"{i}. [{role}] {s.get('text')}")
    if dna:
        lines.append(f"CHARACTER DNA (visual consistency only): {dna}")
    user_prompt = "\n".join(lines)
    system_prompt = (
        "You write one short Instagram carousel body slide in English. "
        "JSON only, no markdown."
    )
    url = f"{GEMINI_API_BASE}?key={api_key}"
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.85,
            "maxOutputTokens": min(1024, GEMINI_MAX_OUTPUT_TOKENS),
            "responseMimeType": "application/json",
        },
    }
    r = httpx.post(url, json=payload, timeout=90.0)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:400]}")
    data = r.json()
    parts = (
        ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")
        or []
    )
    raw_text = "".join(str(p.get("text") or "") for p in parts).strip()
    if not raw_text:
        raise RuntimeError(f"Gemini empty: {json.dumps(data)[:300]}")
    # strip fences if any
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:].strip()
    parsed = json.loads(raw_text)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"bad LLM payload: {type(parsed)}")
    text = str(parsed.get("text") or "").strip()
    scene = str(parsed.get("visual_scene") or "").strip()
    query = str(parsed.get("search_query") or scene or "").strip()
    if not text or len(text) < 20:
        raise RuntimeError(f"empty/short body text: {text!r}")
    return {"text": text, "visual_scene": scene, "search_query": query}


def pad_one(folder: Path) -> None:
    """Pad a 5-slide carousel folder to 6 (body before CTA)."""
    print(f"\n=== {folder.name} ===", flush=True)
    meta = _load_meta(folder)
    slides = list(meta.get("slides") or [])
    jpgs = sorted(
        [p for p in folder.glob("[0-9]*.jpg")],
        key=lambda p: int(p.stem),
    )
    if len(jpgs) >= 6 and len(slides) >= 6:
        print("  already 6 — skip")
        return
    if len(jpgs) != 5 or len(slides) != 5:
        raise RuntimeError(
            f"unexpected state: jpgs={len(jpgs)} meta={len(slides)}"
        )

    topic = str(meta.get("topic") or "")
    dna = meta.get("character_dna") if isinstance(meta.get("character_dna"), dict) else None
    cta_entry = dict(slides[4])
    head = [dict(s) for s in slides[:4]]

    body = _gen_body_slide(topic=topic, existing=slides, dna=dna)
    print(f"  body: {body['text'][:110]}", flush=True)
    print(f"  q={body['search_query']!r}", flush=True)

    # move CTA file 5 → 6
    src, dst = folder / "5.jpg", folder / "6.jpg"
    if dst.exists():
        dst.unlink()
    shutil.move(str(src), str(dst))
    alts = folder / "alts"
    if alts.is_dir():
        for p in list(alts.glob("5_*.jpg")):
            new = alts / ("6_" + p.name.split("_", 1)[1])
            if new.exists():
                new.unlink()
            shutil.move(str(p), str(new))

    used = {str(s.get("pin_id") or "") for s in head if s.get("pin_id")}
    if cta_entry.get("pin_id"):
        used.add(str(cta_entry["pin_id"]))

    from core.harvester import PinterestHarvester
    from core.query_forge import (
        own_slide_queries,
        style_pivot_queries,
        vibe_rescue_queries,
    )
    from core.renderer import render_slide

    harv = PinterestHarvester()
    try:
        harv.warm_session(force=False)
    except Exception as exc:
        print(f"  warm warn: {exc}", flush=True)
    harv.reset_used()
    if used:
        harv.seed_used({u for u in used if u})

    primary, q_alts = own_slide_queries(
        slide_text=body["text"],
        visual_scene=body["visual_scene"],
        topic=topic,
        slide_index=4,
        draft_query=body["search_query"],
        character_dna=dna,
        max_alts=2,
    )
    chain = [primary, *q_alts]
    avoid = {c.lower() for c in chain}
    chain.extend(
        vibe_rescue_queries(
            slide_text=body["text"],
            visual_scene=body["visual_scene"],
            topic=topic,
            avoid=avoid,
            max_n=3,
            include_style_pivot=True,
        )
    )
    chain.extend(
        style_pivot_queries(
            avoid=avoid,
            max_n=2,
            slide_text=body["text"],
            visual_scene=body["visual_scene"],
            topic=topic,
        )
    )
    seen: set[str] = set()
    uniq: list[str] = []
    for q in chain:
        low = (q or "").strip().lower()
        if not low or low in seen:
            continue
        seen.add(low)
        uniq.append(q.strip())

    cands = []
    used_q = primary
    for qi, q in enumerate(uniq):
        print(f"  harvest[{qi+1}/{len(uniq)}] «{q}»…", flush=True)
        cands, _ = harv.harvest_for_query(
            q,
            limit=10,
            exclude_ids={u for u in used if u},
            slide_text=body["text"],
            slide_index=4,
            ignore_used=qi > 2,
            apply_score=True,
            allow_broaden=(qi == 0),
            visual_scene=body["visual_scene"],
            _allow_emergency=True,
        )
        if cands:
            used_q = q
            break

    if not cands:
        raise RuntimeError(f"{folder.name}: no photo for slide 5")

    winner = cands[0]
    alts_dir = folder / "alts"
    alts_dir.mkdir(exist_ok=True)
    alt_pin_ids: list[str] = []
    for j, cand in enumerate(cands[:6]):
        cand.image.convert("RGB").save(
            alts_dir / f"5_{j}.jpg", quality=85, optimize=True
        )
        if cand.pin_id:
            alt_pin_ids.append(str(cand.pin_id))

    rendered, rmeta = render_slide(winner.image, body["text"])
    rendered.save(folder / "5.jpg", quality=92, optimize=True)

    new_slide = {
        "index": 5,
        "text": body["text"],
        "query": used_q,
        "visual_scene": body["visual_scene"],
        "selected_alt": 0,
        "alt_count": min(len(cands), 6),
        "pin_id": winner.pin_id,
        "alt_pin_ids": alt_pin_ids,
        "selection_mode": getattr(winner, "selection_mode", "") or "pad_to_six",
        "relevance_score": float(getattr(winner, "relevance_score", 0) or 0),
        "text_relevance": (
            round(float(winner.text_relevance), 4)
            if getattr(winner, "text_relevance_scored", False)
            else None
        ),
        "taste_score": (
            round(float(winner.taste_score), 4)
            if getattr(winner, "taste_scored", False)
            else None
        ),
        "ugc_score": (
            round(float(winner.ugc_score), 4)
            if getattr(winner, "ugc_scored", False)
            else None
        ),
        "combined_score": float(getattr(winner, "combined_score", 0) or 0),
        "slot": getattr(rmeta, "slot", None),
        "role": "body",
    }
    cta_entry["index"] = 6
    cta_entry["role"] = "cta"
    for i, s in enumerate(head, 1):
        s["index"] = i
        s["role"] = "hook" if i == 1 else "body"

    meta["slides"] = head + [new_slide, cta_entry]
    meta["n_slides"] = 6
    meta["complete"] = True
    meta["padded_to_six_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save_meta(folder, meta)

    final = sorted(folder.glob("[0-9]*.jpg"), key=lambda p: int(p.stem))
    print(
        f"  OK → {[p.name for p in final]} meta={len(meta['slides'])} "
        f"pin={winner.pin_id}",
        flush=True,
    )


def main() -> int:
    if not RUN.is_dir():
        print(f"missing run {RUN}")
        return 1
    targets = [
        p
        for p in sorted(RUN.iterdir())
        if p.is_dir() and p.name.startswith("carousel_")
    ]
    for folder in targets:
        pad_one(folder)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
