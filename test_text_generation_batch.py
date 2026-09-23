#!/usr/bin/env python3
"""
test_text_generation_batch.py
=============================
TEXT-ONLY стресс-тест core/llm_engine.py на 50 темах.
Без Pinterest / Pillow / рендера — только Gemini (gemini-3.1-flash-lite).

Запуск:
  python test_text_generation_batch.py
  python test_text_generation_batch.py --limit 5
  python test_text_generation_batch.py --product "FocusFlow: 3 priorities a day"
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from core.llm_engine import (
    GeminiApiKeyMissing,
    OllamaGenerator,
    _gemini_key_hint,
)

ROOT = Path(__file__).resolve().parent
OUT_MD = ROOT / "test_50_texts_results.md"
OUT_JSONL = ROOT / "test_50_texts.jsonl"

# ---------------------------------------------------------------------------
# 50 тем × 5 направлений
# ---------------------------------------------------------------------------

TOPICS: list[tuple[str, str]] = [
    # --- Продуктивность и мозг (10) ---
    ("productivity", "Dopamine detox without becoming a monk"),
    ("productivity", "Why you procrastinate even when you care"),
    ("productivity", "The 2-minute rule that actually sticks"),
    ("productivity", "Task overload: when your to-do list is lying to you"),
    ("productivity", "Morning brain fog and how to cut through it"),
    ("productivity", "Context switching is quietly destroying your IQ"),
    ("productivity", "Deep work blocks for people who hate calendars"),
    ("productivity", "Decision fatigue after noon — fix the afternoon crash"),
    ("productivity", "Why multitasking feels productive but isn't"),
    ("productivity", "Closing open loops so your brain can finally rest"),
    # --- Психология и эмоции (10) ---
    ("psychology", "Emotional sobriety for people who feel everything"),
    ("psychology", "Imposter syndrome that shows up right before wins"),
    ("psychology", "Boundaries that don't make you the villain"),
    ("psychology", "Overthinking spirals at 1am"),
    ("psychology", "How to let go of a version of you that no longer fits"),
    ("psychology", "People-pleasing dressed up as kindness"),
    ("psychology", "Shame vs guilt — stop confusing the two"),
    ("psychology", "Anxiety that masquerades as productivity"),
    ("psychology", "Emotional flashbacks you keep calling drama"),
    ("psychology", "Self-abandonment in relationships and at work"),
    # --- Самодисциплина и привычки (10) ---
    ("discipline", "Why motivation is lying to you again"),
    ("discipline", "How to rebuild your personality one boring rep at a time"),
    ("discipline", "The 1% rule when you feel stuck at zero"),
    ("discipline", "The power of boredom in a dopamine world"),
    ("discipline", "Quitting your phone without quitting your life"),
    ("discipline", "Identity-based habits that survive bad weeks"),
    ("discipline", "Discipline vs punishment — stop bullying yourself"),
    ("discipline", "Streaks that break and how to restart without shame"),
    ("discipline", "Making hard things easier by making them smaller"),
    ("discipline", "Environment design beats willpower every time"),
    # --- Отношения и социальный интеллект (10) ---
    ("relationships", "Hidden red flags that look like chemistry"),
    ("relationships", "Why people quietly pull away"),
    ("relationships", "How to say a solid no without over-explaining"),
    ("relationships", "Emotional safety vs constant intensity"),
    ("relationships", "Anxious attachment in modern dating"),
    ("relationships", "Repairing after conflict without fake apologies"),
    ("relationships", "Stop auditioning for people who already decided"),
    ("relationships", "Soft power: influence without manipulation"),
    ("relationships", "Friendship drift and how to name it kindly"),
    ("relationships", "Choosing peace over being understood every time"),
    # --- Карьера и навыки (10) ---
    ("career", "Learn 3x faster without binge-watching tutorials"),
    ("career", "Negotiation rules nobody teaches at work"),
    ("career", "Money habits that quietly build options"),
    ("career", "Career reset when your job title feels like a cage"),
    ("career", "Personal brand without becoming a content machine"),
    ("career", "Asking for a raise without sounding desperate"),
    ("career", "Skill stacking for people starting from average"),
    ("career", "Meetings that steal your life — take it back"),
    ("career", "Portfolio thinking for freelancers and operators"),
    ("career", "Leaving a toxic workplace without torching the bridge"),
]


def word_count(text: str) -> int:
    return len([w for w in (text or "").split() if w.strip()])


def hard_gc() -> None:
    gc.collect()
    gc.collect()


def fmt_md_entry(i: int, topic: str, niche: str, slides: list[dict], elapsed: float) -> str:
    lines = [
        "---",
        f"### [#{i:02d}] Тема: {topic}",
        f"*Ниша:* `{niche}` · *время:* {elapsed:.1f}s",
        "",
    ]
    queries: list[str] = []
    n = len(slides)
    for j, s in enumerate(slides, 1):
        text = str(s.get("text") or "").strip()
        q = str(s.get("search_query") or "").strip()
        if q:
            queries.append(q)
        wc = word_count(text)
        if j == 1:
            label = "Slide 1 (Hook)"
        elif j == n:
            label = f"Slide {j} (CTA)"
        else:
            label = f"Slide {j}"
        lines.append(f"* **{label}:** {text} *(слов: {wc})*")
    lines.append(f"* **Pinterest Queries:** {'; '.join(queries) if queries else '—'}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def run(*, limit: int | None, product: str, out_md: Path, out_jsonl: Path) -> int:
    topics = TOPICS[: limit] if limit else TOPICS
    total = len(topics)

    print("=" * 64)
    print("  TEXT-ONLY batch · core/llm_engine.py · Gemini")
    print(f"  Topics: {total}  |  product: {product or '(none)'}")
    print(f"  MD:    {out_md}")
    print(f"  JSONL: {out_jsonl}")
    print("=" * 64)

    load_dotenv(ROOT / ".env")
    llm = OllamaGenerator()
    if not llm.is_available():
        print(f"\n[FAIL]\n{_gemini_key_hint()}")
        return 2

    n_ex = len(llm.examples)
    print(f"[OK] Gemini · model `{llm.resolve_model()}` · few-shot: {n_ex}\n")

    md_parts: list[str] = [
        "# Text Generation Batch — 50 topics",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Model: `{llm.resolve_model()}` · few-shot: {n_ex}",
        f"Product: {product or '—'}",
        "",
    ]

    out_jsonl.write_text("", encoding="utf-8")
    ok = 0
    failed = 0
    t_all = time.perf_counter()

    for i, (niche, topic) in enumerate(topics, start=1):
        t0 = time.perf_counter()
        try:
            result = llm.generate_carousel(
                topic,
                product_name=product,
                variation_index=i - 1,
            )
            slides = result.get("slides") or []
            elapsed = time.perf_counter() - t0
            hook = str((slides[0] or {}).get("text") or "") if slides else ""
            hook_short = hook if len(hook) <= 64 else hook[:61] + "…"
            print(
                f"[{i:02d}/{total}] Тема: '{topic}' | "
                f"Хук: '{hook_short}' | Время: {elapsed:.1f} с"
            )
            md_parts.append(fmt_md_entry(i, topic, niche, slides, elapsed))
            row = {
                "index": i,
                "niche": niche,
                "topic": topic,
                "elapsed_sec": round(elapsed, 3),
                "model": result.get("model"),
                "few_shot_count": result.get("few_shot_count"),
                "product": product,
                "slides": slides,
            }
            with out_jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            ok += 1
            del result, slides, row
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            kind = "Gemini" if isinstance(exc, GeminiApiKeyMissing) else "ERR"
            print(
                f"[{i:02d}/{total}] FAIL {kind} '{topic}' "
                f"({elapsed:.1f}s): {exc}"
            )
            failed += 1
            with out_jsonl.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "index": i,
                            "niche": niche,
                            "topic": topic,
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                            "elapsed_sec": round(elapsed, 3),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        hard_gc()

    total_elapsed = time.perf_counter() - t_all
    md_parts.extend(
        [
            "",
            "## Summary",
            f"- OK: **{ok}** / {total}",
            f"- Failed: **{failed}**",
            f"- Wall time: **{total_elapsed:.1f}s** "
            f"(~{total_elapsed / max(1, ok):.1f}s per topic)",
            "",
        ]
    )
    out_md.write_text("\n".join(md_parts), encoding="utf-8")

    print("\n" + "-" * 64)
    print(f"Done: {ok} ok, {failed} fail, {total_elapsed:.1f}s total")
    print(f"Wrote: {out_md}")
    print(f"Wrote: {out_jsonl}")
    print("-" * 64)
    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="TEXT-ONLY LLM batch test (50 topics)")
    ap.add_argument("--limit", type=int, default=None, help="Only first N topics")
    ap.add_argument(
        "--product",
        type=str,
        default="",
        help='Optional product, e.g. "FocusFlow: 3 priorities a day"',
    )
    ap.add_argument("--out-md", type=Path, default=OUT_MD)
    ap.add_argument("--out-jsonl", type=Path, default=OUT_JSONL)
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    return run(
        limit=args.limit,
        product=args.product.strip(),
        out_md=args.out_md,
        out_jsonl=args.out_jsonl,
    )


if __name__ == "__main__":
    raise SystemExit(main())
