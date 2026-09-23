#!/usr/bin/env python3
"""
Уровень 4: автономный критик качества + self-correction (1 retry).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

OLLAMA_HOST = (os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434").strip()
if OLLAMA_HOST and "://" not in OLLAMA_HOST:
    OLLAMA_HOST = "http://" + OLLAMA_HOST
OLLAMA_MODEL = (os.getenv("CRITIC_OLLAMA_MODEL") or "qwen2.5:7b").strip()
SCORE_THRESHOLD = 8.0
MIN_BODY_WORDS = 10
MAX_BODY_WORDS = 16

STOP_PHRASES = (
    "embrace",
    "mindfulness",
    "practice mindfulness",
    "drink cold water",
    "cold water",
    "deep breaths",
    "deep breathing",
    "lemon water",
    "jumping jacks",
    "push-ups",
    "push ups",
    "unlock your",
    "inner peace",
    "believe in yourself",
    "stay positive",
    "gratitude journal",
)


@dataclass
class LintIssue:
    slide_index: int  # 0-based in full carousel
    kind: str
    detail: str
    penalty: float


@dataclass
class CriticVerdict:
    score: float
    needs_rewrite: bool
    flaw_slide: int | None  # 0-based, None = none
    fix_instruction: str
    lint_issues: list[LintIssue] = field(default_factory=list)
    lint_penalty: float = 0.0
    source: str = "heuristic"
    rewritten: bool = False


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


def _sentence_count(text: str) -> int:
    parts = [p.strip() for p in re.split(r"[.!?]+", text or "") if p.strip()]
    return len(parts)


def lint_carousel(
    hook: str,
    points: list[str],
    cta: str,
) -> tuple[list[LintIssue], float]:
    """Детерминированный линтер (~2 мс). Возвращает issues + суммарный штраф (0–3)."""
    issues: list[LintIssue] = []
    # body slides start at index 1
    for i, point in enumerate(points):
        idx = i + 1
        wc = _word_count(point)
        if wc < MIN_BODY_WORDS:
            issues.append(
                LintIssue(idx, "length_short", f"{wc} words (<{MIN_BODY_WORDS})", 0.4)
            )
        elif wc > MAX_BODY_WORDS:
            issues.append(
                LintIssue(idx, "length_long", f"{wc} words (>{MAX_BODY_WORDS})", 0.25)
            )
        sc = _sentence_count(point)
        if sc < 2 or not point.strip().endswith((".", "!", "?")):
            issues.append(
                LintIssue(
                    idx,
                    "structure",
                    f"need 2 finished sentences with period (got {sc})",
                    0.5,
                )
            )
        low = point.lower()
        for phrase in STOP_PHRASES:
            if phrase in low:
                issues.append(
                    LintIssue(idx, "stopword", f"banned: {phrase}", 0.6)
                )
                break

    # hook banality light check
    hlow = (hook or "").lower()
    for phrase in ("nobody tells you", "ways to", "habits to", "micro-habits"):
        if phrase in hlow:
            issues.append(LintIssue(0, "hook_banality", f"hook stamp: {phrase}", 0.5))
            break

    # CTA grammar
    clow = (cta or "").strip().lower()
    if clow and not (
        clow.startswith("save this for") or clow.startswith("send this to")
    ):
        issues.append(
            LintIssue(
                1 + len(points),
                "cta",
                "CTA must be 'Save this for…' or 'Send this to…'",
                0.4,
            )
        )

    penalty = min(3.0, sum(x.penalty for x in issues))
    return issues, penalty


def _extract_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("critic empty JSON")
    return json.loads(text[start : end + 1])


def _build_score_prompt(topic: str, hook: str, points: list[str], cta: str) -> str:
    pts = "\n".join(f"- {p}" for p in points)
    return (
        "Rate this carousel draft from 1-10.\n"
        f"Topic: {topic}\n"
        f"Hook: {hook}\n"
        f"Advice slides:\n{pts}\n"
        f"CTA: {cta}\n\n"
        "Criteria:\n"
        "1) Hook sharpness (no banal openers)\n"
        "2) Concrete actions (timers/objects, no coach fluff)\n"
        "3) Contextual CTA (Save this for… / Send this to…)\n\n"
        "Return ONLY JSON:\n"
        '{"score": 8.5, "needs_rewrite": false, "flaw_slide": null, '
        '"fix_instruction": ""}\n'
        "flaw_slide is 0-based index in [hook, ...points, cta] or null. "
        "If score < 8, set needs_rewrite true and name the worst slide."
    )


def _score_ollama(prompt: str) -> dict[str, Any]:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1, "num_predict": 160},
    }
    r = httpx.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=60.0)
    if r.status_code >= 400:
        raise RuntimeError(f"ollama critic HTTP {r.status_code}")
    content = (r.json().get("response") or "").strip()
    return _extract_json(content)


def _score_gemini(prompt: str) -> dict[str, Any]:
    from google import genai
    from google.genai import types

    from core.llm_engine import DEFAULT_GEMINI_MODEL, _ensure_api_key
    from core.usage_meter import (
        estimate_tokens,
        extract_usage_from_sdk,
        record_gemini,
    )

    api_key = _ensure_api_key()
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=DEFAULT_GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=180,
            response_mime_type="application/json",
        ),
    )
    inp, out, est = extract_usage_from_sdk(response)
    if est or (inp == 0 and out == 0):
        inp = estimate_tokens(prompt)
        out = estimate_tokens(response.text or "")
        est = True
    record_gemini(
        kind="critic",
        model=DEFAULT_GEMINI_MODEL,
        input_tokens=inp,
        output_tokens=out,
        note="carousel_critic",
        estimated=est,
    )
    return _extract_json(response.text or "")


def _heuristic_score(
    hook: str,
    points: list[str],
    cta: str,
    lint_penalty: float,
) -> dict[str, Any]:
    score = 9.0 - lint_penalty
    flaw = None
    instr = ""
    if lint_penalty > 0:
        # pick heaviest issue slide
        # recompute quickly
        issues, _ = lint_carousel(hook, points, cta)
        if issues:
            top = max(issues, key=lambda x: x.penalty)
            flaw = top.slide_index
            instr = top.detail
            score = min(score, 7.5)
    return {
        "score": round(max(1.0, min(10.0, score)), 2),
        "needs_rewrite": score < SCORE_THRESHOLD,
        "flaw_slide": flaw,
        "fix_instruction": instr,
    }


def score_draft(
    topic: str,
    hook: str,
    points: list[str],
    cta: str,
    *,
    prefer_ollama: bool = True,
) -> tuple[dict[str, Any], str]:
    """Локальный score. Gemini не вызывается (экономия: 1 API = только тексты слайдов)."""
    if prefer_ollama:
        try:
            prompt = _build_score_prompt(topic, hook, points, cta)
            return _score_ollama(prompt), "ollama"
        except Exception as exc:
            logger.warning("Ollama critic failed (%s)", exc)
    issues, penalty = lint_carousel(hook, points, cta)
    return _heuristic_score(hook, points, cta, penalty), "heuristic"


def rewrite_slide(
    *,
    topic: str,
    role: str,
    old_text: str,
    fix_instruction: str,
    search_query: str = "",
) -> tuple[str, str]:
    """
    Перегенерация слайда без Gemini (экономия API).
    Возвращает исходный текст — critic rewrite отключён по дизайну.
    """
    del topic, role, fix_instruction
    return old_text, search_query


class CarouselCritic:
    """Линтер → LLM score → 1× self-correction проблемного слайда."""

    def __init__(
        self,
        *,
        threshold: float = SCORE_THRESHOLD,
        prefer_ollama: bool = True,
        rewrite_fn: Callable[..., tuple[str, str]] | None = None,
    ) -> None:
        self.threshold = threshold
        self.prefer_ollama = prefer_ollama
        self.rewrite_fn = rewrite_fn or rewrite_slide

    def review(
        self,
        topic: str,
        slides: list[dict[str, Any]],
        *,
        allow_rewrite: bool = True,
    ) -> tuple[list[dict[str, Any]], CriticVerdict]:
        """
        slides: [{role, text, search_query}, ...]
        Возвращает (possibly fixed slides, verdict).
        """
        if not slides:
            return slides, CriticVerdict(
                score=1.0,
                needs_rewrite=True,
                flaw_slide=None,
                fix_instruction="empty carousel",
                source="lint",
            )

        hook = str(slides[0].get("text") or "")
        cta = str(slides[-1].get("text") or "") if len(slides) > 1 else ""
        points = [
            str(s.get("text") or "")
            for s in slides[1:-1]
        ] if len(slides) > 2 else []

        lint_issues, lint_penalty = lint_carousel(hook, points, cta)
        raw, source = score_draft(
            topic, hook, points, cta, prefer_ollama=self.prefer_ollama
        )

        try:
            score = float(raw.get("score") or 5)
        except (TypeError, ValueError):
            score = 5.0
        score = max(1.0, min(10.0, score - lint_penalty * 0.35))
        needs = bool(raw.get("needs_rewrite")) or score < self.threshold
        flaw = raw.get("flaw_slide")
        try:
            flaw_i = int(flaw) if flaw is not None else None
        except (TypeError, ValueError):
            flaw_i = None
        if flaw_i is None and lint_issues and needs:
            flaw_i = max(lint_issues, key=lambda x: x.penalty).slide_index
        if flaw_i is not None:
            flaw_i = max(0, min(len(slides) - 1, flaw_i))

        instr = str(raw.get("fix_instruction") or "")
        if not instr and lint_issues:
            instr = lint_issues[0].detail

        verdict = CriticVerdict(
            score=round(score, 2),
            needs_rewrite=needs,
            flaw_slide=flaw_i,
            fix_instruction=instr,
            lint_issues=lint_issues,
            lint_penalty=lint_penalty,
            source=source,
            rewritten=False,
        )

        if not (allow_rewrite and needs and flaw_i is not None):
            verdict.needs_rewrite = score < self.threshold
            return slides, verdict

        # one-shot rewrite of flaw slide only
        try:
            role = str(slides[flaw_i].get("role") or "body")
            old = str(slides[flaw_i].get("text") or "")
            old_q = str(slides[flaw_i].get("search_query") or "")
            new_text, new_q = self.rewrite_fn(
                topic=topic,
                role=role,
                old_text=old,
                fix_instruction=instr,
                search_query=old_q,
            )
            fixed = [dict(s) for s in slides]
            fixed[flaw_i]["text"] = new_text
            if new_q:
                fixed[flaw_i]["search_query"] = new_q
            # re-lint + light rescore without second rewrite
            h2 = str(fixed[0].get("text") or "")
            c2 = str(fixed[-1].get("text") or "") if len(fixed) > 1 else ""
            p2 = (
                [str(s.get("text") or "") for s in fixed[1:-1]]
                if len(fixed) > 2
                else []
            )
            issues2, pen2 = lint_carousel(h2, p2, c2)
            new_score = min(10.0, max(score, self.threshold) + 0.3 - pen2 * 0.2)
            verdict = CriticVerdict(
                score=round(new_score, 2),
                needs_rewrite=False,
                flaw_slide=flaw_i,
                fix_instruction=instr,
                lint_issues=issues2,
                lint_penalty=pen2,
                source=source + "+rewrite",
                rewritten=True,
            )
            return fixed, verdict
        except Exception as exc:
            logger.warning("Self-correction failed: %s", exc)
            return slides, verdict
