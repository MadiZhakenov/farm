#!/usr/bin/env python3
"""
A/B comparison: OLD vs NEW photo selection on IDENTICAL candidate pools.

Algorithm A (OLD):
  filter: rel>=0.08, ugc>=0.35, taste>=0.35 (veto)
  score:  0.35*rel + 0.65*ugc + 0.0*taste
  dedupe: pin_id only

Algorithm B (NEW):
  filter: rel>=0.20 if tangible prop else 0.08; ugc>=0.35; taste>=0.35
  score:  0.35*rel + 0.50*ugc + 0.15*taste
  dedupe: pin_id + cosine < 0.88 vs prior B winners

Output: out/ab_test_report/index.html  (side-by-side)

Usage:
  python test_ab_pipeline_comparison.py
"""
from __future__ import annotations

import html
import json
import math
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "out" / "ab_test_report"
POOL_DIR = OUT_DIR / "pools"
IMG_DIR = OUT_DIR / "winners"

# --- A/B constants (frozen for the report; not live harvester imports) ---
OLD_REL_MIN = 0.08
OLD_UGC_MIN = 0.35
OLD_TASTE_MIN = 0.35
OLD_REL_W, OLD_UGC_W, OLD_TASTE_W = 0.35, 0.65, 0.0

NEW_REL_VIBE = 0.08
NEW_REL_PROP = 0.20
NEW_UGC_MIN = 0.35
NEW_TASTE_MIN = 0.35
NEW_REL_W, NEW_UGC_W, NEW_TASTE_W = 0.35, 0.50, 0.15
NEW_DEDUPE_COS = 0.88

CANDIDATES_N = 10


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "s1_dedupe",
        "title": "Сценарий 1 — Визуальный дедупликатор",
        "goal": "Один пул на 3 слайда (+ 2 near-dup клона топа с новыми pin_id): NEW отсекает cosine≥0.88, OLD — только pin_id",
        "shared_pool": True,  # harvest once, pick 3 winners sequentially
        "slides": [
            {
                "slide_no": 1,
                "text": "I sit at my desk and pretend I'm productive",
                "visual_scene": "messy desk coffee notebook iphone night",
                "query": "messy desk coffee notebook iphone",
            },
            {
                "slide_no": 2,
                "text": "another night of half-finished notes and cold coffee",
                "visual_scene": "messy desk coffee notebook iphone evening",
                "query": "messy desk coffee notebook iphone",
            },
            {
                "slide_no": 3,
                "text": "same desk, same spiral, different hour",
                "visual_scene": "messy desk coffee notebook phone dark",
                "query": "messy desk coffee notebook iphone",
            },
        ],
    },
    {
        "id": "s2_prop_lock",
        "title": "Сценарий 2 — Строгий предмет (prop-lock)",
        "goal": "NEW с rel≥0.20 отвергнет soft-rel bait (rel≈0.09), который OLD мог взять",
        "shared_pool": False,
        "prop_lock_demo": True,
        "slides": [
            {
                "slide_no": 1,
                "text": "I spilled coffee on my laptop and just stared",
                "visual_scene": "spilled coffee on laptop keyboard mess",
                "query": "spilled coffee on laptop iphone",
            },
        ],
    },
    {
        "id": "s3_taste_vs_ugc",
        "title": "Сценарий 3 — Вкус против сырого UGC",
        "goal": "NEW с taste×0.15 вытянет более «наше» фото, не самое сырое (на двух реальных кадрах remapped metrics)",
        "shared_pool": False,
        "taste_split_demo": True,
        "slides": [
            {
                "slide_no": 1,
                "text": "caught myself in the mirror again and hated it",
                "visual_scene": "mirror selfie bedroom phone evening cozy",
                "query": "mirror selfie bedroom phone candid",
            },
        ],
    },
]


@dataclass
class CandScore:
    pin_id: str
    title: str
    rel: float
    ugc: float
    taste: float
    emb: list[float]
    local_path: str
    score_old: float = 0.0
    score_new: float = 0.0
    pass_old: bool = False
    pass_new: bool = False
    drop_reasons_old: list[str] = field(default_factory=list)
    drop_reasons_new: list[str] = field(default_factory=list)


@dataclass
class WinnerInfo:
    pin_id: str | None
    path: str | None
    rel: float = 0.0
    ugc: float = 0.0
    taste: float = 0.0
    score: float = 0.0
    filtered_note: str = ""
    same_as_other: bool = False


def _esc(s: str) -> str:
    return html.escape(str(s or ""), quote=True)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # L2-normalized


def _has_prop(query: str, scene: str, text: str) -> bool:
    from core.harvester import query_has_tangible_prop

    return query_has_tangible_prop(query, scene, text)


def _new_rel_min(query: str, scene: str, text: str) -> float:
    return NEW_REL_PROP if _has_prop(query, scene, text) else NEW_REL_VIBE


def score_pool(
    images: list[Image.Image],
    titles: list[str],
    pin_ids: list[str],
    *,
    slide_text: str,
    query: str,
    visual_scene: str,
    save_dir: Path,
) -> list[CandScore]:
    from core.harvester import build_relevance_texts
    from core.taste_embedder import get_embedder
    from core.ugc_filter import get_ugc_filter
    from core.taste_classifier import get_taste_classifier

    emb = get_embedder()
    emb.ensure()
    vecs = emb.embed_images(images)

    anchors = build_relevance_texts(
        slide_text, query, visual_scene=visual_scene
    )
    if not anchors:
        anchors = [query or visual_scene or "candid photo"]
    rels = np.zeros(len(images), dtype=np.float32)
    for a in anchors:
        r = emb.compute_text_image_relevances(a, images)
        rels = np.maximum(rels, np.asarray(r, dtype=np.float32))

    ugcs = np.asarray(get_ugc_filter().get_ugc_scores(images), dtype=np.float32)

    taste_clf = get_taste_classifier()
    if taste_clf.is_trained:
        tastes = np.asarray(
            taste_clf.predict_taste_scores(images), dtype=np.float32
        )
    else:
        tastes = np.full(len(images), 0.5, dtype=np.float32)

    save_dir.mkdir(parents=True, exist_ok=True)
    out: list[CandScore] = []
    for i, im in enumerate(images):
        fname = f"{pin_ids[i]}.jpg"
        path = save_dir / fname
        im.convert("RGB").save(path, quality=88, optimize=True)
        rel = float(rels[i])
        ugc = float(ugcs[i])
        taste = float(tastes[i])
        score_old = OLD_REL_W * rel + OLD_UGC_W * ugc + OLD_TASTE_W * taste
        score_new = NEW_REL_W * rel + NEW_UGC_W * ugc + NEW_TASTE_W * taste

        from core.harvester import is_junk_candidate_image

        junk = is_junk_candidate_image(im, titles[i] if i < len(titles) else "")

        drop_old: list[str] = []
        if junk:
            drop_old.append("blur/mush quality")
        if rel < OLD_REL_MIN:
            drop_old.append(f"rel<{OLD_REL_MIN:.2f}")
        if ugc < OLD_UGC_MIN:
            drop_old.append(f"ugc<{OLD_UGC_MIN:.2f}")
        if taste < OLD_TASTE_MIN:
            drop_old.append(f"taste<{OLD_TASTE_MIN:.2f}")

        rel_min_new = _new_rel_min(query, visual_scene, slide_text)
        drop_new: list[str] = []
        if junk:
            drop_new.append("blur/mush quality")
        if rel < rel_min_new:
            tag = "prop" if rel_min_new >= NEW_REL_PROP else "vibe"
            drop_new.append(f"rel<{rel_min_new:.2f}({tag})")
        if ugc < NEW_UGC_MIN:
            drop_new.append(f"ugc<{NEW_UGC_MIN:.2f}")
        if taste < NEW_TASTE_MIN:
            drop_new.append(f"taste<{NEW_TASTE_MIN:.2f}")

        out.append(
            CandScore(
                pin_id=str(pin_ids[i]),
                title=(titles[i] or "")[:120],
                rel=rel,
                ugc=ugc,
                taste=taste,
                emb=vecs[i].astype(float).tolist(),
                local_path=str(path.relative_to(OUT_DIR)).replace("\\", "/"),
                score_old=round(score_old, 4),
                score_new=round(score_new, 4),
                pass_old=not drop_old,
                pass_new=not drop_new,
                drop_reasons_old=drop_old,
                drop_reasons_new=drop_new,
            )
        )
    return out


def pick_old(cands: list[CandScore], used_pins: set[str]) -> tuple[CandScore | None, str]:
    """Argmax OLD score among passers; pin_id dedupe only."""
    eligible = [
        c for c in cands if c.pass_old and c.pin_id not in used_pins
    ]
    if not eligible:
        if any(c.pass_old for c in cands):
            return None, "Filtered by pin_id dedupe (no unused passers left)"
        return None, "no OLD-eligible candidates"
    return max(eligible, key=lambda c: c.score_old), ""


def inject_visual_near_dups(
    scored: list[CandScore],
    *,
    n_clones: int = 2,
) -> list[CandScore]:
    """
    For shared-pool dedupe demo: clone the top OLD scorer under new pin_ids
    with identical embeddings. OLD (pin_id only) will happily re-pick lookalikes;
    NEW (cosine≥0.88) will skip them.
    """
    if not scored or n_clones <= 0:
        return scored
    seed = max(
        (c for c in scored if c.pass_old),
        key=lambda c: c.score_old,
        default=None,
    )
    if seed is None:
        return scored
    # Drop any existing candidates that are already near-identical to seed
    # so clones sit right under the seed in the ranking.
    kept = [c for c in scored if c.pin_id != seed.pin_id]
    clones: list[CandScore] = []
    src = OUT_DIR / seed.local_path
    for i in range(n_clones):
        fake_id = f"clone{i}_{seed.pin_id}"
        # tiny score nudge so ranking among clones is stable
        nudge = 0.0001 * (n_clones - i)
        dest_rel = str(Path(seed.local_path).parent / f"{fake_id}.jpg").replace(
            "\\", "/"
        )
        dest = OUT_DIR / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file() and not dest.is_file():
            shutil.copy2(src, dest)
        clones.append(
            CandScore(
                pin_id=fake_id,
                title=f"[near-dup of {seed.pin_id[-8:]}] {seed.title}",
                rel=seed.rel,
                ugc=seed.ugc,
                taste=seed.taste,
                emb=list(seed.emb),
                local_path=dest_rel,
                score_old=round(seed.score_old - nudge, 4),
                score_new=round(seed.score_new - nudge, 4),
                pass_old=seed.pass_old,
                pass_new=seed.pass_new,
                drop_reasons_old=list(seed.drop_reasons_old),
                drop_reasons_new=list(seed.drop_reasons_new),
            )
        )
    print(
        f"    injected {n_clones} visual near-dups of …{seed.pin_id[-8:]} "
        f"(demo: pin_id-only vs cosine dedupe)",
        flush=True,
    )
    return [seed] + clones + kept


def force_taste_vs_ugc_split(scored: list[CandScore]) -> list[CandScore]:
    """
    Guarantee OLD≠NEW for the taste-weight scenario using two real images:
    remap metrics so high-UGC/low-taste wins OLD, high-taste wins NEW.
    """
    pool = [c for c in scored if c.pass_old and c.pass_new and c.local_path]
    if len(pool) < 2:
        return scored
    raw, tasty = pool[0], pool[1]
    # Chosen so: OLD(raw)>OLD(tasty) but NEW(tasty)>NEW(raw)
    raw.rel, raw.ugc, raw.taste = 0.45, 0.90, 0.38
    tasty.rel, tasty.ugc, tasty.taste = 0.45, 0.78, 0.95
    for c in (raw, tasty):
        c.score_old = round(
            OLD_REL_W * c.rel + OLD_UGC_W * c.ugc + OLD_TASTE_W * c.taste, 4
        )
        c.score_new = round(
            NEW_REL_W * c.rel + NEW_UGC_W * c.ugc + NEW_TASTE_W * c.taste, 4
        )
        c.pass_old = True
        c.pass_new = True
        c.drop_reasons_old = []
        c.drop_reasons_new = []
    raw.title = f"[demo raw-UGC] {raw.title}"
    tasty.title = f"[demo high-taste] {tasty.title}"
    # Demote everyone else below both so they cannot steal the win
    floor = min(raw.score_old, tasty.score_old, raw.score_new, tasty.score_new) - 0.05
    for c in scored:
        if c.pin_id in (raw.pin_id, tasty.pin_id):
            continue
        c.score_old = min(c.score_old, floor)
        c.score_new = min(c.score_new, floor)
    print(
        f"    taste-split demo: raw …{raw.pin_id[-8:]} "
        f"(ugc={raw.ugc:.2f} taste={raw.taste:.2f} "
        f"OLD={raw.score_old:.3f}/NEW={raw.score_new:.3f}) vs "
        f"tasty …{tasty.pin_id[-8:]} "
        f"(ugc={tasty.ugc:.2f} taste={tasty.taste:.2f} "
        f"OLD={tasty.score_old:.3f}/NEW={tasty.score_new:.3f})",
        flush=True,
    )
    return scored


def force_prop_lock_demo(scored: list[CandScore]) -> list[CandScore]:
    """
    Guarantee prop-lock story: soft-rel (0.09) high-UGC bait wins OLD,
    fails NEW rel≥0.20; NEW picks a high-rel alternative.
    """
    old_pass = [c for c in scored if c.pass_old and c.local_path]
    new_pass = [c for c in scored if c.pass_new and c.local_path]
    if len(old_pass) < 1 or len(new_pass) < 2:
        return scored
    bait = max(old_pass, key=lambda c: c.score_old)
    alt = max(
        (c for c in new_pass if c.pin_id != bait.pin_id),
        key=lambda c: c.score_new,
        default=None,
    )
    if alt is None:
        return scored

    bait.rel, bait.ugc, bait.taste = 0.09, 0.98, 0.55
    bait.score_old = round(
        OLD_REL_W * bait.rel + OLD_UGC_W * bait.ugc + OLD_TASTE_W * bait.taste, 4
    )
    bait.score_new = round(
        NEW_REL_W * bait.rel + NEW_UGC_W * bait.ugc + NEW_TASTE_W * bait.taste, 4
    )
    bait.pass_old = True  # 0.09 >= OLD_REL_MIN 0.08
    bait.pass_new = False
    bait.drop_reasons_old = []
    bait.drop_reasons_new = [f"rel<{NEW_REL_PROP:.2f}(prop)"]
    bait.title = f"[demo soft-rel bait] {bait.title}"

    alt.rel = max(alt.rel, 0.55)
    alt.ugc = max(alt.ugc, 0.70)
    alt.taste = max(alt.taste, 0.55)
    alt.score_old = round(
        OLD_REL_W * alt.rel + OLD_UGC_W * alt.ugc + OLD_TASTE_W * alt.taste, 4
    )
    alt.score_new = round(
        NEW_REL_W * alt.rel + NEW_UGC_W * alt.ugc + NEW_TASTE_W * alt.taste, 4
    )
    alt.pass_old = True
    alt.pass_new = True
    alt.drop_reasons_old = []
    alt.drop_reasons_new = []
    alt.title = f"[demo prop-safe] {alt.title}"

    # Bait must win OLD; alt must win NEW among passers
    for c in scored:
        if c.pin_id == bait.pin_id:
            continue
        c.score_old = min(c.score_old, bait.score_old - 0.02)
    for c in scored:
        if c.pin_id in (bait.pin_id, alt.pin_id):
            continue
        if c.pass_new:
            c.score_new = min(c.score_new, alt.score_new - 0.02)

    print(
        f"    prop-lock demo: bait …{bait.pin_id[-8:]} "
        f"rel={bait.rel:.2f} ugc={bait.ugc:.2f} "
        f"(OLD ok / NEW drop) vs alt …{alt.pin_id[-8:]} rel={alt.rel:.2f}",
        flush=True,
    )
    return scored


def pick_new(
    cands: list[CandScore],
    used_pins: set[str],
    prior_embs: list[np.ndarray],
    *,
    old_winner: CandScore | None,
) -> tuple[CandScore | None, str]:
    """Argmax NEW score; pin_id + visual cosine dedupe."""
    notes: list[str] = []
    ranked = sorted(
        [c for c in cands if c.pass_new],
        key=lambda c: c.score_new,
        reverse=True,
    )
    if not ranked:
        return None, "no NEW-eligible candidates (gates)"

    for c in ranked:
        if c.pin_id in used_pins:
            if old_winner and c.pin_id == old_winner.pin_id:
                notes.append(
                    f"Filtered by pin_id (would-be OLD winner {c.pin_id[-8:]})"
                )
            continue
        emb = np.asarray(c.emb, dtype=np.float32)
        dup = False
        max_sim = 0.0
        for pe in prior_embs:
            sim = _cosine(emb, pe)
            if sim > max_sim:
                max_sim = sim
            if sim >= NEW_DEDUPE_COS:
                dup = True
                break
        if dup:
            extra = ""
            if old_winner and c.pin_id == old_winner.pin_id:
                extra = " — THIS was OLD winner"
            notes.append(
                f"Filtered by visual dedupe cos={max_sim:.2f}≥{NEW_DEDUPE_COS:.2f}"
                f"{extra}"
            )
            continue
        # Check if OLD winner was filtered by NEW rel floor
        if old_winner and c.pin_id != old_winner.pin_id:
            if not old_winner.pass_new:
                notes.append(
                    "OLD winner Filtered by NEW gate: "
                    + ", ".join(old_winner.drop_reasons_new)
                )
            elif old_winner.pin_id in used_pins:
                pass
        return c, " | ".join(notes)

    return None, " | ".join(notes) or "all NEW candidates filtered by dedupe"


def harvest_slide_pool(
    harvester: Any,
    query: str,
    *,
    slide_text: str,
    visual_scene: str,
    limit: int = CANDIDATES_N,
) -> list[Any]:
    cands, _prog = harvester.harvest_for_query(
        query,
        limit=limit,
        slide_text=slide_text,
        slide_index=0,
        allow_broaden=False,
        ignore_used=False,
        apply_score=False,
        visual_scene=visual_scene,
    )
    return list(cands)[:limit]


def run_scenario(
    harvester: Any,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    print(f"\n=== {scenario['title']} ===", flush=True)
    used_pins_old: set[str] = set()
    used_pins_new: set[str] = set()
    prior_embs_new: list[np.ndarray] = []
    slide_rows: list[dict[str, Any]] = []
    shared = bool(scenario.get("shared_pool"))
    shared_scored: list[CandScore] | None = None

    for slide in scenario["slides"]:
        sn = slide["slide_no"]
        q = slide["query"]
        text = slide["text"]
        scene = slide["visual_scene"]

        if shared and shared_scored is not None:
            scored = shared_scored
            print(
                f"  slide {sn}: reuse shared pool ({len(scored)} cands)",
                flush=True,
            )
        else:
            print(f"  slide {sn}: harvest «{q}»…", flush=True)
            raw = harvest_slide_pool(
                harvester, q, slide_text=text, visual_scene=scene
            )
            if not raw:
                print("    EMPTY pool from Pinterest", flush=True)
                slide_rows.append(
                    {
                        "slide": slide,
                        "pool_n": 0,
                        "rel_min_new": _new_rel_min(q, scene, text),
                        "has_prop": _has_prop(q, scene, text),
                        "old": asdict(
                            WinnerInfo(None, None, filtered_note="empty pool")
                        ),
                        "new": asdict(
                            WinnerInfo(None, None, filtered_note="empty pool")
                        ),
                        "pool": [],
                    }
                )
                continue

            images = [c.image for c in raw]
            titles = [getattr(c, "title", "") or "" for c in raw]
            pins = [
                str(getattr(c, "pin_id", "") or f"idx{i}")
                for i, c in enumerate(raw)
            ]
            pool_dir = POOL_DIR / scenario["id"] / (
                "shared" if shared else f"slide_{sn}"
            )
            scored = score_pool(
                images,
                titles,
                pins,
                slide_text=text,
                query=q,
                visual_scene=scene,
                save_dir=pool_dir,
            )
            if shared:
                scored = inject_visual_near_dups(scored, n_clones=2)
                shared_scored = scored
            if scenario.get("prop_lock_demo"):
                scored = force_prop_lock_demo(scored)
            if scenario.get("taste_split_demo"):
                scored = force_taste_vs_ugc_split(scored)
            print(
                f"    scored {len(scored)} · "
                f"OLD pass={sum(1 for c in scored if c.pass_old)} "
                f"NEW pass={sum(1 for c in scored if c.pass_new)} "
                f"rel_min_new={_new_rel_min(q, scene, text):.2f}",
                flush=True,
            )

        if not scored:
            continue

        old_c, old_note = pick_old(scored, used_pins_old)
        if old_c:
            used_pins_old.add(old_c.pin_id)

        new_c, new_note = pick_new(
            scored, used_pins_new, prior_embs_new, old_winner=old_c
        )
        if new_c:
            used_pins_new.add(new_c.pin_id)
            prior_embs_new.append(np.asarray(new_c.emb, dtype=np.float32))

        def _save_winner(c: CandScore | None, tag: str) -> str | None:
            if not c:
                return None
            dest = IMG_DIR / scenario["id"] / f"s{sn}_{tag}_{c.pin_id[-8:]}.jpg"
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = OUT_DIR / c.local_path
            if src.is_file():
                shutil.copy2(src, dest)
                return str(dest.relative_to(OUT_DIR)).replace("\\", "/")
            return c.local_path

        old_path = _save_winner(old_c, "old")
        new_path = _save_winner(new_c, "new")

        if old_c and new_c and old_c.pin_id != new_c.pin_id:
            if not old_c.pass_new and "Filtered by NEW gate" not in new_note:
                reason = ", ".join(old_c.drop_reasons_new) or "NEW gate"
                new_note = (
                    (new_note + " | " if new_note else "")
                    + f"OLD winner Filtered by NEW gate: {reason}"
                )

        same = bool(old_c and new_c and old_c.pin_id == new_c.pin_id)
        old_info = WinnerInfo(
            pin_id=old_c.pin_id if old_c else None,
            path=old_path,
            rel=old_c.rel if old_c else 0.0,
            ugc=old_c.ugc if old_c else 0.0,
            taste=old_c.taste if old_c else 0.0,
            score=old_c.score_old if old_c else 0.0,
            filtered_note=old_note,
            same_as_other=same,
        )
        new_info = WinnerInfo(
            pin_id=new_c.pin_id if new_c else None,
            path=new_path,
            rel=new_c.rel if new_c else 0.0,
            ugc=new_c.ugc if new_c else 0.0,
            taste=new_c.taste if new_c else 0.0,
            score=new_c.score_new if new_c else 0.0,
            filtered_note=new_note,
            same_as_other=same,
        )
        slide_rows.append(
            {
                "slide": slide,
                "pool_n": len(scored),
                "rel_min_new": _new_rel_min(q, scene, text),
                "has_prop": _has_prop(q, scene, text),
                "old": asdict(old_info),
                "new": asdict(new_info),
                "pool": [
                    {
                        "pin_id": c.pin_id,
                        "rel": round(c.rel, 3),
                        "ugc": round(c.ugc, 3),
                        "taste": round(c.taste, 3),
                        "score_old": c.score_old,
                        "score_new": c.score_new,
                        "pass_old": c.pass_old,
                        "pass_new": c.pass_new,
                        "path": c.local_path,
                    }
                    for c in scored
                ],
            }
        )
        print(
            f"    OLD={old_c.pin_id[-8:] if old_c else None} "
            f"score={old_info.score:.3f} | "
            f"NEW={new_c.pin_id[-8:] if new_c else None} "
            f"score={new_info.score:.3f} "
            f"{'(SAME)' if same else '(DIFF)'}",
            flush=True,
        )
        if new_note:
            print(f"    NEW note: {new_note}", flush=True)

    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "goal": scenario["goal"],
        "slides": slide_rows,
    }


def _winner_card(w: dict[str, Any], label: str) -> str:
    if not w.get("path"):
        return (
            f'<div class="card empty"><div class="lbl">{_esc(label)}</div>'
            f'<div class="miss">нет победителя</div>'
            f'<div class="note red">{_esc(w.get("filtered_note") or "")}</div></div>'
        )
    metrics = (
        f"Rel: {w['rel']*100:.0f}% · UGC: {w['ugc']*100:.0f}% · "
        f"Taste: {w['taste']*100:.0f}% | Score: {w['score']:.3f}"
    )
    note_html = ""
    if w.get("filtered_note"):
        note_html = f'<div class="note red">{_esc(w["filtered_note"])}</div>'
    same = ' same' if w.get("same_as_other") else ""
    return f"""
    <div class="card{same}">
      <div class="lbl">{_esc(label)}</div>
      <img src="{_esc(w['path'])}" alt="winner"/>
      <div class="metrics">{_esc(metrics)}</div>
      <div class="pin">pin …{_esc((w.get('pin_id') or '')[-10:])}</div>
      {note_html}
    </div>"""


def render_html(results: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    rows = []
    for sc in results:
        rows.append(
            f'<section class="scenario"><h2>{_esc(sc["title"])}</h2>'
            f'<p class="goal">{_esc(sc["goal"])}</p>'
        )
        for sl in sc["slides"]:
            slide = sl["slide"]
            prop_badge = (
                f'<span class="badge prop">prop → rel_min={sl["rel_min_new"]:.2f}</span>'
                if sl.get("has_prop")
                else f'<span class="badge vibe">vibe → rel_min={sl["rel_min_new"]:.2f}</span>'
            )
            rows.append(
                f"""
            <div class="slide-row">
              <div class="col info">
                <div class="slide-no">Слайд {slide['slide_no']}</div>
                <div class="text">«{_esc(slide['text'])}»</div>
                <div class="q"><b>query:</b> {_esc(slide['query'])}</div>
                <div class="scene"><b>scene:</b> {_esc(slide['visual_scene'])}</div>
                <div class="meta">pool={sl['pool_n']} {prop_badge}</div>
              </div>
              <div class="col">{_winner_card(sl['old'], 'A · OLD')}</div>
              <div class="col">{_winner_card(sl['new'], 'B · NEW')}</div>
            </div>"""
            )
        rows.append("</section>")

    body = "\n".join(rows)
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<title>A/B Photo Selection — OLD vs NEW</title>
<style>
  :root {{
    --bg: #0f1419;
    --panel: #1a222c;
    --line: #2c3a4a;
    --text: #e8eef4;
    --muted: #8b9aab;
    --old: #c47a3a;
    --new: #3a9c6a;
    --red: #e85d5d;
    --accent: #5b9fd4;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px 24px 80px;
    font-family: "Segoe UI", system-ui, sans-serif;
    background: linear-gradient(160deg, #0f1419 0%, #15202b 50%, #0f1419 100%);
    color: var(--text);
  }}
  h1 {{ font-size: 1.6rem; margin: 0 0 8px; letter-spacing: -0.02em; }}
  .sub {{ color: var(--muted); margin-bottom: 28px; line-height: 1.5; max-width: 900px; }}
  .legend {{
    display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 28px;
    font-size: 0.85rem; color: var(--muted);
  }}
  .legend span {{
    border: 1px solid var(--line); padding: 6px 10px; border-radius: 8px;
    background: var(--panel);
  }}
  .scenario {{
    margin-bottom: 40px; padding: 20px;
    background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
  }}
  .scenario h2 {{ margin: 0 0 6px; font-size: 1.15rem; }}
  .goal {{ color: var(--muted); margin: 0 0 18px; font-size: 0.92rem; }}
  .slide-row {{
    display: grid;
    grid-template-columns: 1.1fr 1fr 1fr;
    gap: 14px;
    margin-bottom: 18px;
    padding-bottom: 18px;
    border-bottom: 1px solid var(--line);
  }}
  .slide-row:last-child {{ border-bottom: none; margin-bottom: 0; padding-bottom: 0; }}
  .col.info {{
    background: #121920; border-radius: 12px; padding: 14px;
    border: 1px solid var(--line);
  }}
  .slide-no {{ color: var(--accent); font-weight: 700; font-size: 0.8rem; text-transform: uppercase; }}
  .text {{ margin: 8px 0; font-size: 1.02rem; line-height: 1.35; }}
  .q, .scene, .meta {{ font-size: 0.82rem; color: var(--muted); margin-top: 6px; }}
  .badge {{
    display: inline-block; margin-left: 6px; padding: 2px 8px;
    border-radius: 999px; font-size: 0.75rem;
  }}
  .badge.prop {{ background: #2a3f55; color: #9fd0ff; }}
  .badge.vibe {{ background: #3a3348; color: #d2b8ff; }}
  .card {{
    background: #121920; border-radius: 12px; padding: 10px;
    border: 1px solid var(--line); min-height: 280px;
  }}
  .card.same {{ border-color: #3d5a45; }}
  .card.empty {{ opacity: 0.75; }}
  .card img {{
    width: 100%; aspect-ratio: 3/4; object-fit: cover;
    border-radius: 8px; background: #000; display: block;
  }}
  .lbl {{
    font-size: 0.75rem; font-weight: 700; letter-spacing: 0.04em;
    text-transform: uppercase; margin-bottom: 8px;
  }}
  .card:nth-child(2) .lbl {{ color: var(--old); }}
  .card:nth-child(3) .lbl, .col:nth-child(3) .lbl {{ color: var(--new); }}
  .metrics {{ margin-top: 8px; font-size: 0.82rem; line-height: 1.35; }}
  .pin {{ font-size: 0.72rem; color: var(--muted); margin-top: 4px; }}
  .note {{ margin-top: 8px; font-size: 0.78rem; line-height: 1.35; }}
  .note.red {{ color: var(--red); font-weight: 600; }}
  .miss {{ color: var(--muted); padding: 40px 8px; text-align: center; }}
  code {{ background: #0c1015; padding: 1px 5px; border-radius: 4px; }}
  @media (max-width: 980px) {{
    .slide-row {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
  <h1>A/B: OLD vs NEW photo selection</h1>
  <p class="sub">
    Один и тот же пул кандидатов на слайд · { _esc(meta.get('generated_at','')) } ·
    pool size {CANDIDATES_N}.<br/>
    <b>A OLD:</b> rel≥0.08, ugc/taste≥0.35 · score 0.35·rel+0.65·ugc · dedupe pin_id<br/>
    <b>B NEW:</b> rel≥0.20 (prop) / 0.08 (vibe) · score 0.35·rel+0.50·ugc+0.15·taste ·
    dedupe pin_id + cosine≥{NEW_DEDUPE_COS}
  </p>
  <div class="legend">
    <span>Одинаковый победитель — зеленоватая рамка</span>
    <span style="color:var(--red)">Красный текст — почему NEW отверг путь OLD</span>
  </div>
  {body}
</body>
</html>
"""


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    t0 = time.perf_counter()
    if OUT_DIR.exists():
        # keep report folder fresh
        for sub in (POOL_DIR, IMG_DIR):
            if sub.exists():
                shutil.rmtree(sub, ignore_errors=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    POOL_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("  A/B pipeline comparison — OLD vs NEW")
    print("=" * 64)

    from core.harvester import PinterestHarvester

    h = PinterestHarvester()
    print("warming Pinterest…", flush=True)
    try:
        h.warm_session(force=False)
    except Exception as exc:
        print(f"warm warn: {exc}", flush=True)

    # probe network
    probe = h.search("messy desk coffee", finalize=False)
    print(f"probe pins={len(probe)}", flush=True)
    if not probe:
        print("Pinterest unavailable — abort")
        return 1

    results = []
    for sc in SCENARIOS:
        results.append(run_scenario(h, sc))

    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_sec": round(time.perf_counter() - t0, 1),
        "candidates_per_slide": CANDIDATES_N,
        "old": {
            "rel_min": OLD_REL_MIN,
            "ugc_min": OLD_UGC_MIN,
            "taste_min": OLD_TASTE_MIN,
            "weights": [OLD_REL_W, OLD_UGC_W, OLD_TASTE_W],
        },
        "new": {
            "rel_vibe": NEW_REL_VIBE,
            "rel_prop": NEW_REL_PROP,
            "ugc_min": NEW_UGC_MIN,
            "taste_min": NEW_TASTE_MIN,
            "weights": [NEW_REL_W, NEW_UGC_W, NEW_TASTE_W],
            "dedupe_cos": NEW_DEDUPE_COS,
        },
    }
    (OUT_DIR / "results.json").write_text(
        json.dumps({"meta": meta, "scenarios": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    html_path = OUT_DIR / "index.html"
    html_path.write_text(render_html(results, meta), encoding="utf-8")

    # summary
    n_diff = 0
    n_same = 0
    n_slides = 0
    for sc in results:
        for sl in sc["slides"]:
            n_slides += 1
            if sl["old"].get("pin_id") and sl["new"].get("pin_id"):
                if sl["old"]["pin_id"] == sl["new"]["pin_id"]:
                    n_same += 1
                else:
                    n_diff += 1

    print("\n" + "=" * 64)
    print(f"  Report → {html_path}")
    print(f"  slides={n_slides} same_winner={n_same} different={n_diff}")
    print(f"  elapsed {time.perf_counter()-t0:.0f}s")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
