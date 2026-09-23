#!/usr/bin/env python3
"""
Тест генерации текстов карусели через gemini-3.1-flash-lite
по спеке formulas.json (скелет Listicle Save-Bait).

Запуск:
  # положите ключ в .env: GEMINI_API_KEY=...
  python test_carousel_generator.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
FORMULAS_PATH = ROOT / "formulas.json"
MODEL_ID = "gemini-3.1-flash-lite"
SKELETON_ALIASES = (
    "listicle_save_bait",
    "listicle save-bait",
    "listicle / reference dump",
    "listicle save bait",
)

PRODUCT = {
    "name": "FocusFlow",
    "essence": (
        "Минималистичный планер, который принудительно ограничивает день "
        "ровно 3 главными задачами."
    ),
    "carousel_role": (
        "инструмент/артефакт, сжимающий шаги 1–4 в одну простую систему"
    ),
}

CAMPAIGN_TOPIC = "7 habits that quietly kill your morning focus"
AUDIENCE = "Young professionals, relatable, no fluff"

OUTPUT_SKELETON_NAME = "Listicle Save-Bait"


# ---------------------------------------------------------------------------
# Structured output schema
# ---------------------------------------------------------------------------

class SlideOut(BaseModel):
    slide_number: int = Field(ge=1, le=20)
    role: str
    text: str
    word_count: int = Field(ge=0)


class CarouselOut(BaseModel):
    skeleton: str
    slides: list[SlideOut]


# ---------------------------------------------------------------------------
# formulas.json
# ---------------------------------------------------------------------------

def load_formulas(path: Path = FORMULAS_PATH) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Не найден {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def pick_listicle_skeleton(formulas: dict[str, Any]) -> dict[str, Any]:
    skeletons = formulas.get("skeletons") or []
    if not skeletons:
        raise RuntimeError("В formulas.json нет skeletons")

    for sk in skeletons:
        blob = f"{sk.get('id', '')} {sk.get('name', '')}".lower()
        if any(alias in blob for alias in SKELETON_ALIASES):
            return sk
    # fallback: первый
    return skeletons[0]


def word_limits_for_role(role: str, formulas: dict[str, Any], slide_meta: dict[str, Any]) -> tuple[int, int]:
    words = (formulas.get("meta") or {}).get("global_constraints", {}).get("words", {})
    role_l = role.lower()
    max_from_slide = int(slide_meta.get("max_words") or 15)

    if "hook" in role_l:
        w = words.get("hook_slide_1") or {"min": 6, "max": 12}
        return int(w["min"]), min(int(w["max"]), max_from_slide)
    if role_l.strip() == "cta" or role_l.endswith("/cta") or role_l == "cta":
        w = words.get("cta_final") or {"min": 5, "max": 8}
        return int(w["min"]), min(int(w["max"]), max_from_slide)
    # Body / Pain / Bridge / Ad / Resolution / Second cover
    w = words.get("body_total_per_slide") or {"min": 10, "max": 15}
    # slide 2 second-cover: разрешаем чуть короче (микро-хук), но не длиннее body max
    if slide_meta.get("slide_number") == 2:
        return 6, min(int(w["max"]), max_from_slide)
    return int(w["min"]), min(int(w["max"]), max_from_slide)


def count_words(text: str) -> int:
    # слова = токены из букв/цифр (EN/RU), без чистой пунктуации
    return len(re.findall(r"[A-Za-zА-Яа-яЁё0-9]+(?:'[A-Za-z]+)?", text))


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def build_prompt(formulas: dict[str, Any], skeleton: dict[str, Any]) -> str:
    stop_words = formulas.get("stop_words") or []
    hooks = formulas.get("hook_formulas") or []
    save_triggers = (formulas.get("triggers") or {}).get("saves") or []
    constraints = (formulas.get("meta") or {}).get("global_constraints", {})
    words = constraints.get("words") or {}

    slides_spec = []
    for s in skeleton.get("slides") or []:
        n = s["slide_number"]
        role = s["role"]
        lo, hi = word_limits_for_role(role, formulas, s)
        purpose = s.get("purpose", "")
        if n == 2:
            purpose = (
                "SECOND COVER / IG re-serve: standalone micro-hook. "
                "Must work if shown without slide 1. "
                + purpose
            )
        slides_spec.append(
            {
                "slide_number": n,
                "role": role,
                "word_min": lo,
                "word_max": hi,
                "purpose": purpose,
                "trigger_example": s.get("trigger_example"),
            }
        )

    ad = skeleton.get("native_ad_slot") or {}
    payload = {
        "task": "Generate Instagram/TikTok carousel slide copy as strict JSON.",
        "skeleton_id": skeleton.get("id"),
        "skeleton_name_out": OUTPUT_SKELETON_NAME,
        "skeleton_description": skeleton.get("description"),
        "target_metric": skeleton.get("target_metric"),
        "campaign": {
            "topic": CAMPAIGN_TOPIC,
            "audience": AUDIENCE,
            "language": "English only",
        },
        "product": PRODUCT,
        "native_ad_slot": ad,
        "word_rules": words,
        "hook_formulas": hooks,
        "save_cta_triggers": save_triggers,
        "stop_words_forbidden": stop_words,
        "slides_spec": slides_spec,
        "hard_rules": [
            "Slide 1 (Hook): 6–12 words; use number and/or error/disappointment pattern; NO stop-words.",
            "Slide 2: SECOND COVER — standalone micro-hook for Instagram re-serve algorithm.",
            "Slides 3–4 (Body): 10–15 words each; exactly ONE thesis per slide; concrete/screenshotable.",
            f"Slide {ad.get('slide', 5)} (Ad/Product): FocusFlow as method/protocol that compresses steps 1–4 — NOT a logo dump, NOT 'buy now'.",
            "Bridge into the ad naturally (tool that sequences prior habits).",
            "Final CTA slide: 5–8 words; Save trigger like 'Save for tomorrow morning'.",
            "Young professionals tone: sharp, relatable, zero fluff.",
            "Output English only.",
            "word_count on each slide MUST equal the actual word count of text.",
            f'skeleton field MUST be exactly "{OUTPUT_SKELETON_NAME}".',
            "Return one object with keys skeleton + slides array covering ALL slide_numbers in slides_spec.",
        ],
    }
    return (
        "You are a carousel copy engineer. Follow the JSON spec below exactly.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------

def generate_carousel(prompt: str, api_key: str) -> tuple[CarouselOut, float, str]:
    client = genai.Client(api_key=api_key)
    t0 = time.perf_counter()
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            response_mime_type="application/json",
            response_schema=CarouselOut,
        ),
    )
    elapsed = time.perf_counter() - t0

    parsed = response.parsed
    raw = response.text or ""
    if parsed is None:
        # fallback parse
        parsed = CarouselOut.model_validate_json(raw)
    elif not isinstance(parsed, CarouselOut):
        parsed = CarouselOut.model_validate(parsed)

    return parsed, elapsed, raw


# ---------------------------------------------------------------------------
# Linter
# ---------------------------------------------------------------------------

class SlideLint:
    def __init__(self, slide_number: int) -> None:
        self.slide_number = slide_number
        self.ok = True
        self.notes: list[str] = []

    def fail(self, msg: str) -> None:
        self.ok = False
        self.notes.append(msg)

    def warn(self, msg: str) -> None:
        self.notes.append(f"warn: {msg}")


def lint_carousel(
    data: CarouselOut,
    formulas: dict[str, Any],
    skeleton: dict[str, Any],
) -> tuple[bool, list[SlideLint], list[str]]:
    global_fails: list[str] = []
    by_num = {s.slide_number: s for s in data.slides}
    meta_by_num = {s["slide_number"]: s for s in skeleton.get("slides") or []}
    stop_words = [sw.lower() for sw in (formulas.get("stop_words") or [])]
    ad_slide_n = int((skeleton.get("native_ad_slot") or {}).get("slide") or 5)

    # все слайды скелета присутствуют
    expected = sorted(meta_by_num.keys())
    got = sorted(by_num.keys())
    if expected != got:
        global_fails.append(f"slide set mismatch: expected {expected}, got {got}")

    if data.skeleton.strip() != OUTPUT_SKELETON_NAME:
        global_fails.append(
            f'skeleton name: got {data.skeleton!r}, want {OUTPUT_SKELETON_NAME!r}'
        )

    slide_lints: list[SlideLint] = []
    ad_found = False

    for n in expected:
        lint = SlideLint(n)
        slide = by_num.get(n)
        meta = meta_by_num[n]
        if slide is None:
            lint.fail("missing slide")
            slide_lints.append(lint)
            continue

        text = (slide.text or "").strip()
        actual_wc = count_words(text)
        declared = slide.word_count
        lo, hi = word_limits_for_role(meta.get("role", slide.role), formulas, meta)

        if not text:
            lint.fail("empty text")
        if declared != actual_wc:
            lint.fail(f"word_count field={declared} != actual={actual_wc}")
        if actual_wc < lo or actual_wc > hi:
            lint.fail(f"words {actual_wc} out of band [{lo}, {hi}]")

        low = text.lower()
        for sw in stop_words:
            # спец-кейсы со скобками в stop list
            needle = re.sub(r"\s*\(.*?\)\s*", " ", sw).strip()
            if needle and needle in low:
                lint.fail(f"stop-word hit: {sw!r}")

        # рекламный слот
        if n == ad_slide_n or "ad" in (slide.role or "").lower() or "product" in (slide.role or "").lower():
            if PRODUCT["name"].lower() in low:
                ad_found = True
            else:
                lint.fail(f"ad slot must mention {PRODUCT['name']}")

        # CTA: save trigger
        if n == max(expected) or (slide.role or "").lower() == "cta":
            if "save" not in low:
                lint.fail("CTA must include Save trigger")

        slide_lints.append(lint)

    if not ad_found:
        global_fails.append(
            f"ad slot missing: no FocusFlow on slide {ad_slide_n} / Ad role"
        )

    overall = (not global_fails) and all(s.ok for s in slide_lints)
    return overall, slide_lints, global_fails


# ---------------------------------------------------------------------------
# Console report
# ---------------------------------------------------------------------------

def _bar(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def print_report(
    data: CarouselOut,
    skeleton: dict[str, Any],
    formulas: dict[str, Any],
    overall: bool,
    slide_lints: list[SlideLint],
    global_fails: list[str],
    elapsed: float,
) -> None:
    lint_by_n = {s.slide_number: s for s in slide_lints}
    meta_by_n = {s["slide_number"]: s for s in skeleton.get("slides") or []}
    line = "═" * 72
    thin = "─" * 72

    print()
    print(line)
    print("  CAROUSEL GENERATOR · gemini-3.1-flash-lite")
    print(line)
    print(f"  Skeleton : {data.skeleton}")
    print(f"  Topic    : {CAMPAIGN_TOPIC}")
    print(f"  Product  : {PRODUCT['name']}")
    print(f"  Model    : {MODEL_ID}")
    print(f"  Latency  : {elapsed:.2f} s")
    print(f"  Linter   : {_bar(overall)}")
    print(thin)

    for slide in sorted(data.slides, key=lambda s: s.slide_number):
        meta = meta_by_n.get(slide.slide_number, {})
        lint = lint_by_n.get(slide.slide_number)
        role = slide.role or meta.get("role", "?")
        actual = count_words(slide.text)
        if meta:
            lo, hi = word_limits_for_role(meta.get("role", role), formulas, meta)
            band = f"{lo}-{hi}"
        else:
            band = "?"
        status = _bar(lint.ok) if lint else "FAIL"
        print()
        print(f"  ┌─ Slide {slide.slide_number} · {role}")
        print(f"  │  {slide.text}")
        print(
            f"  │  words: {actual} (declared {slide.word_count})  "
            f"band: {band}  ·  {status}"
        )
        if lint and lint.notes:
            for note in lint.notes:
                print(f"  │  · {note}")
        print("  └─")

    if global_fails:
        print()
        print("  GLOBAL FAILS:")
        for g in global_fails:
            print(f"    × {g}")

    print()
    print(thin)
    print(f"  VERDICT: {_bar(overall)}  |  {elapsed:.2f}s  |  slides={len(data.slides)}")
    print(line)
    print()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    load_dotenv(ROOT / ".env")
    import os

    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        print(
            "ERROR: GEMINI_API_KEY не задан.\n"
            "Создайте файл .env в корне проекта:\n"
            "  GEMINI_API_KEY=your_key_here"
        )
        return 2

    formulas = load_formulas()
    skeleton = pick_listicle_skeleton(formulas)
    print(
        f"Loaded formulas.json · skeleton={skeleton.get('id')!r} "
        f"({skeleton.get('name')})"
    )

    prompt = build_prompt(formulas, skeleton)
    print(f"Calling {MODEL_ID}…")

    try:
        data, elapsed, _raw = generate_carousel(prompt, api_key)
    except Exception as exc:
        print(f"Gemini error: {exc.__class__.__name__}: {exc}")
        return 1

    overall, slide_lints, global_fails = lint_carousel(data, formulas, skeleton)
    print_report(
        data, skeleton, formulas, overall, slide_lints, global_fails, elapsed
    )
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
