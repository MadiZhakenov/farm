#!/usr/bin/env python3
"""Block-level unit checks — no full carousel generation."""
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

FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAIL
    mark = "OK" if ok else "FAIL"
    if not ok:
        FAIL += 1
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


def test_selection_contract() -> None:
    print("\n=== BLOCK: selection contract ===")
    from core import harvester as H

    check("STRICT on", H.STRICT_SELECTION_CONTRACT is True)
    check("completion fill on", H.COMPLETION_FILL_ENABLED is True)
    check("soft_rel disabled", H.SOFT_REL_ENABLED is False)
    check("pool_soft disabled", H.POOL_SOFT_UGC_ENABLED is False)
    check("guarantee_soft disabled", H.GUARANTEE_SOFT_ENABLED is False)
    check(
        "emergency ugc == hard",
        H.EMERGENCY_UGC_FLOOR == H.UGC_HARD_FLOOR,
        f"{H.EMERGENCY_UGC_FLOOR} vs {H.UGC_HARD_FLOOR}",
    )
    check(
        "ugc soft band set",
        H.UGC_SOFT_FLOOR == 0.48 and H.UGC_SOFT_REL_MIN == 0.30,
        f"{H.UGC_SOFT_FLOOR}/{H.UGC_SOFT_REL_MIN}",
    )
    check(
        "ugc_eligible soft keep",
        H.ugc_eligible(0.48, 0.64) is True,
    )
    check(
        "ugc_eligible soft reject low rel",
        H.ugc_eligible(0.48, 0.10) is False,
    )
    check(
        "ugc_eligible hard stock reject",
        H.ugc_eligible(0.30, 0.99) is False,
    )
    check(
        "emergency rel == select min",
        H.EMERGENCY_REL_FLOOR == H.SELECT_RELEVANCE_MIN,
        f"{H.EMERGENCY_REL_FLOOR} vs {H.SELECT_RELEVANCE_MIN}",
    )


def test_rank_weights_aligned() -> None:
    print("\n=== BLOCK: rank weight alignment ===")
    from core.harvester import FINAL_REL_W, FINAL_TASTE_W, FINAL_UGC_W
    from core.ugc_filter import final_rank_score

    s = final_rank_score(0.8, 0.5, relevance=0.4)
    expected = round(0.4 * FINAL_REL_W + 0.5 * FINAL_TASTE_W + 0.8 * FINAL_UGC_W, 4)
    check("final_rank_score uses FINAL_*", s == expected, f"{s} vs {expected}")


def test_query_forge() -> None:
    print("\n=== BLOCK: query_forge ===")
    from core.query_forge import (
        forge_pinterest_query,
        own_slide_query,
        own_slide_queries,
        query_is_dna_cast,
        query_is_filler_only,
    )

    cases = [
        (
            "I eat a sad salad at noon then demolish snacks at 10pm staring into the pantry",
            "woman black hair girl",
            ("pantry", "snack", "salad", "chip"),
        ),
        (
            "cold pasta over the sink like a raccoon",
            "caramel hair girl candid",
            ("pasta", "sink"),
        ),
        (
            "counting every almond calorie at my desk",
            "hands girl auburn hair",
            ("almond",),
        ),
        (
            "appetite as a procrastination tool for years",
            "feet sneakers floor candid",
            ("snack", "laptop", "desk", "fridge"),
        ),
        (
            "weighing my spinach on a food scale",
            "ginger hair bathroom girl",
            ("spinach", "scale"),
        ),
        (
            "I spent forty minutes staring at a calendar to decide lunch",
            "dark short hair guy",
            ("calendar", "meal"),
        ),
    ]
    for text, draft, must_any in cases:
        cast = query_is_dna_cast(draft)
        fill = query_is_filler_only(draft, slide_text=text)
        out = forge_pinterest_query(slide_text=text, draft_query=draft)
        has_prop = any(m in out for m in must_any)
        no_cast = not query_is_dna_cast(out)
        # Bad drafts (DNA cast OR filler) must be rewritten to a prop query
        check(
            f"forge ← {draft!r}",
            (cast or fill) and has_prop and no_cast,
            f"out={out!r} bad_in={cast or fill} prop={has_prop}",
        )

    keep = forge_pinterest_query(
        slide_text="messy binge with chip bags on the table",
        draft_query="messy table night candid",
    )
    check("keep good draft", keep == "messy table night candid", keep)

    owned = own_slide_query(
        slide_text="cold pasta over the sink",
        draft_query="blonde hair girl",
        character_dna={"gender": "female", "hair": "long blonde hair"},
    )
    check(
        "own_slide_query strips DNA cast",
        not query_is_dna_cast(owned) and ("pasta" in owned or "sink" in owned),
        owned,
    )
    primary, alts = own_slide_queries(
        slide_text="counting almonds at my desk then open the fridge",
        visual_scene="handful of almonds next to a notebook on a desk",
        draft_query="hands girl dark hair",
        max_alts=1,
    )
    check(
        "own_slide_queries multi has food/desk prop",
        any(
            any(t in x for t in ("almond", "fridge", "desk", "notebook"))
            for x in [primary, *alts]
        ),
        f"primary={primary!r} alts={alts}",
    )
    check(
        "own_slide_queries alt differs or empty",
        (not alts) or alts[0].lower() != primary.lower(),
        f"primary={primary!r} alts={alts}",
    )
    # Prop must win over notebook when both in scene
    forced = forge_pinterest_query(
        slide_text="counting every single almond in my head at my desk",
        visual_scene="handful of almonds next to a notebook on a desk",
        draft_query="counting messy notebook scribbles",
    )
    check(
        "forge forces almond over notebook draft",
        "almond" in forced,
        forced,
    )
    pantry_q = own_slide_query(
        slide_text="lose my mind in the pantry at 10pm",
        visual_scene="open pantry door at night hand reaching snacks",
        draft_query="messy kitchen candid",
    )
    check(
        "own_slide_query pantry beats generic kitchen",
        "pantry" in pantry_q or "snack" in pantry_q or "fridge" in pantry_q,
        pantry_q,
    )

    pretzel_q = forge_pinterest_query(
        slide_text="ate an entire bag of stale pretzels at 10pm staring into the pantry",
        visual_scene="hand in a bag of pretzels at open pantry night",
        draft_query="hand holding pretzels night",
    )
    check(
        "pretzel → chips/bag not bare soft pretzel",
        "chip" in pretzel_q or "bag" in pretzel_q or "snack" in pretzel_q,
        pretzel_q,
    )
    check(
        "pretzel query not bare pretzels alone",
        pretzel_q.strip().lower() not in ("pretzels", "pretzel", "holding pretzels night"),
        pretzel_q,
    )

    from core.query_forge import scrub_dna_from_scene, normalize_pinterest_query_aliases

    scrubbed = scrub_dna_from_scene(
        "woman with shoulder length auburn hair standing in kitchen looking into open pantry"
    )
    check(
        "scrub DNA from visual_scene",
        "auburn" not in scrubbed.lower() and "hair" not in scrubbed.lower(),
        scrubbed,
    )
    check(
        "scrub keeps pantry prop",
        "pantry" in scrubbed.lower(),
        scrubbed,
    )
    check(
        "alias bare pretzel",
        "chip" in normalize_pinterest_query_aliases("holding pretzels night").lower()
        or "bag" in normalize_pinterest_query_aliases("holding pretzels night").lower(),
        normalize_pinterest_query_aliases("holding pretzels night"),
    )

    from core.harvester import build_relevance_texts, title_looks_like_junk

    anchors = build_relevance_texts(
        "lose my mind in the pantry at 10pm",
        "open pantry night",
        visual_scene="open pantry door at night, hand reaching for snacks",
    )
    check(
        "relevance dual anchors when scene+props",
        len(anchors) >= 1,
        str(anchors),
    )
    check(
        "junk title org pantry",
        title_looks_like_junk("Walk-in Pantry Organization Goals 2024"),
    )
    check(
        "junk title product photography",
        title_looks_like_junk("Snack product photography pack shot"),
    )
    check(
        "not junk normal pantry title",
        not title_looks_like_junk("late night pantry snack binge candid"),
    )

    from core.query_forge import vibe_rescue_queries
    from core import harvester as H

    check("SLIDE_SEARCH_BUDGET <= 5", H.SLIDE_SEARCH_BUDGET <= 5, str(H.SLIDE_SEARCH_BUDGET))
    check("MERGE_DOWNLOAD_CAP <= 14", H.MERGE_DOWNLOAD_CAP <= 14, str(H.MERGE_DOWNLOAD_CAP))

    failed = {primary.lower(), *(a.lower() for a in alts)}
    rescues = vibe_rescue_queries(
        slide_text="counting almonds at my desk then open the fridge",
        visual_scene="handful of almonds next to a notebook on a desk",
        topic="midnight snacks",
        avoid=failed,
        max_n=3,
    )
    check("vibe_rescue returns queries", len(rescues) >= 1, str(rescues))
    check(
        "vibe_rescue avoids failed",
        all(r.lower() not in failed for r in rescues),
        f"rescues={rescues} failed={failed}",
    )
    check(
        "vibe_rescue no DNA cast",
        all(not query_is_dna_cast(r) for r in rescues),
        str(rescues),
    )
    # Prop/vibe signal from confession
    check(
        "vibe_rescue has scene prop",
        any(
            any(t in r.lower() for t in ("almond", "fridge", "desk", "notebook", "snack"))
            for r in rescues
        ),
        str(rescues),
    )


def test_dna_inject_soft() -> None:
    print("\n=== BLOCK: inject_character_markers (soft) ===")
    from core.llm_engine import inject_character_markers_into_query

    male = {"gender": "male", "hair": "short dark hair"}
    female = {"gender": "female", "hair": "long blonde hair"}

    # Must NOT rewrite scene queries into DNA casting
    q1 = inject_character_markers_into_query(
        "open pantry night", female, slide_index=0
    )
    check("keep pantry (female DNA)", "pantry" in q1 and "blonde" not in q1, q1)

    q2 = inject_character_markers_into_query(
        "pasta over sink", male, slide_index=1
    )
    check("keep pasta (male DNA)", "pasta" in q2 and "guy" not in q2, q2)

    # Must strip opposite gender / foreign color
    q3 = inject_character_markers_into_query(
        "blonde girl mirror kitchen", male, slide_index=0
    )
    check(
        "strip girl+blonde for male",
        "girl" not in q3.lower() and "blonde" not in q3.lower(),
        q3,
    )

    q4 = inject_character_markers_into_query(
        "hands guy black hair", female, slide_index=2
    )
    check("strip guy for female", "guy" not in q4.lower(), q4)

    # Must NOT produce classic DNA cast hijacks
    q5 = inject_character_markers_into_query(
        "mirror selfie bathroom", female, slide_index=0
    )
    from core.query_forge import query_is_dna_cast

    check("no hijack mirror→blonde hair girl", not query_is_dna_cast(q5), q5)


def test_locks_on_existing_photos() -> None:
    print("\n=== BLOCK: attr/gender lock on known jpgs ===")
    from PIL import Image

    from core.harvester import (
        attribute_mismatches_dna,
        gender_mismatches_lock,
    )

    root = ROOT / "out" / "run_20260925_111007"
    male_face = (
        root
        / "carousel_005_the_brutal_reality_of_food_noise"
        / "1.jpg"
    )
    female_black = (
        root
        / "carousel_001_why_you_eat_clean_all_day_only_t"
        / "1.jpg"
    )
    if not male_face.exists() or not female_black.exists():
        check("fixture jpgs present", False, "missing run_20260925_111007")
        return

    male_dna = {
        "gender": "male",
        "hair": "short dark hair",
        "style": "man mid 20s",
        "skin_tone": "fair",
        "build": "average",
    }
    female_blonde = {
        "gender": "female",
        "hair": "long blonde hair",
        "style": "woman mid 20s",
        "skin_tone": "fair",
        "build": "slim",
    }
    female_black_dna = {
        "gender": "female",
        "hair": "long black hair",
        "style": "woman mid 20s",
        "skin_tone": "olive",
        "build": "slim",
    }

    img_m = Image.open(male_face).convert("RGB")
    img_f = Image.open(female_black).convert("RGB")

    # Male face vs male DNA → keep
    check(
        "male face OK for male DNA",
        not attribute_mismatches_dna(img_m, male_dna, query="guy dark hair"),
    )
    check(
        "male face OK for male gender lock",
        not gender_mismatches_lock(img_m, "male", query="guy dark hair"),
    )

    # Male face vs female DNA → drop
    check(
        "male face DROP for female DNA",
        attribute_mismatches_dna(img_m, female_blonde, query="blonde hair girl")
        or gender_mismatches_lock(img_m, "female", query="blonde hair girl"),
    )

    # Black-hair woman vs blonde DNA → drop (hair)
    check(
        "black hair DROP for blonde DNA",
        attribute_mismatches_dna(
            img_f, female_blonde, query="blonde long hair girl"
        ),
    )

    # Black-hair woman vs black DNA → keep
    check(
        "black hair OK for black DNA",
        not attribute_mismatches_dna(
            img_f, female_black_dna, query="woman black hair"
        ),
    )


def main() -> int:
    test_selection_contract()
    test_rank_weights_aligned()
    test_query_forge()
    test_dna_inject_soft()
    test_locks_on_existing_photos()
    print(f"\n=== DONE fails={FAIL} ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
