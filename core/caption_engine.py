#!/usr/bin/env python3
"""
Генерация caption.txt для TikTok/Reels (нативный English).
Google Gemini; при сбое — эвристика без сети.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from core.llm_engine import DEFAULT_GEMINI_MODEL, _ensure_api_key

logger = logging.getLogger(__name__)

MODEL = DEFAULT_GEMINI_MODEL
GEMINI_API_BASE = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL}:generateContent"
)
MAX_OUTPUT_TOKENS = 400
TIMEOUT_SEC = 60.0


class CaptionSchema(BaseModel):
    hook: str = Field(min_length=1)
    essence: str = Field(min_length=1)
    cta: str = Field(min_length=1)
    hashtags: str = Field(min_length=1)


def _has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text or ""))


def _heuristic_caption(
    slides: list[str],
    topic: str,
    product: str = "",
) -> str:
    hook = (slides[0] if slides else topic).strip()
    body = " ".join(slides[1:-1]) if len(slides) > 2 else " ".join(slides[1:])
    essence = body[:180].strip() or f"A short carousel on {topic.strip() or 'focus'}."
    if product:
        cta = (
            f"Save this for tomorrow morning — and grab {product.split(':')[0].strip()} "
            f"(link in bio)."
        )
    else:
        cta = "Save this for tomorrow morning. You'll need the reminder."
    # Хештеги по нише темы (раньше почти всегда был #productivity,
    # даже в каруселях про еду и тело — фидбек 2026-09-29)
    from core.niches import hashtags_for

    tags = hashtags_for(topic, slides)
    return "\n".join([hook, essence, cta, tags])


def _build_prompt(slides: list[str], topic: str, product: str) -> str:
    return (
        "Write a TikTok/Reels caption in fluent viral American English ONLY.\n"
        f"Topic: {topic}\n"
        f"Product (optional): {product or 'none'}\n"
        f"Slide texts: {json.dumps(slides, ensure_ascii=False)}\n\n"
        "Return JSON with keys: hook, essence, cta, hashtags.\n"
        "Rules:\n"
        "- No Russian\n"
        "- hook: punchy 1-line opener tied to the carousel\n"
        "- essence: 1-2 sentences summarizing the value\n"
        "- cta: must include Save; if product given, mention link in bio\n"
        "- hashtags: 5-7 tags, space-separated, each starts with #"
    )


def _format_caption(data: dict[str, Any], slides: list[str], topic: str) -> str | None:
    hook = str(data.get("hook") or (slides[0] if slides else topic)).strip()
    essence = str(data.get("essence") or "").strip()
    cta = str(data.get("cta") or "").strip()
    tags = str(data.get("hashtags") or "").strip()
    if _has_cyrillic(hook + essence + cta + tags):
        return None
    if not essence or not cta or not tags:
        return None
    if "#" not in tags:
        from core.niches import hashtags_for

        tags = hashtags_for(topic, slides)
    return "\n".join([hook, essence, cta, tags])


def _call_gemini_sdk(api_key: str, prompt: str, model: str) -> dict[str, Any]:
    from core.usage_meter import (
        estimate_tokens,
        extract_usage_from_sdk,
        record_gemini,
    )

    sys_inst = (
        "You write short viral TikTok/Reels captions in American English. "
        "Output valid JSON only."
    )
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.65,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
            response_schema=CaptionSchema,
            system_instruction=sys_inst,
        ),
    )
    inp, out, est = extract_usage_from_sdk(response)
    if est or (inp == 0 and out == 0):
        inp = estimate_tokens(sys_inst) + estimate_tokens(prompt)
        out = estimate_tokens(response.text or "")
        est = True
    record_gemini(
        kind="caption",
        model=model,
        input_tokens=inp,
        output_tokens=out,
        note="generate_caption",
        estimated=est,
    )
    parsed = response.parsed
    if isinstance(parsed, CaptionSchema):
        return parsed.model_dump()
    raw = response.text or ""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("Gemini caption: empty/invalid JSON")
    return json.loads(raw[start : end + 1])


def _call_gemini_httpx(api_key: str, prompt: str) -> dict[str, Any]:
    from core.usage_meter import (
        estimate_tokens,
        extract_usage_from_http,
        record_gemini,
    )

    url = f"{GEMINI_API_BASE}?key={api_key}"
    sys_inst = (
        "You write short viral TikTok/Reels captions in American English. "
        "Output valid JSON only."
    )
    payload = {
        "systemInstruction": {"parts": [{"text": sys_inst}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.65,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "responseMimeType": "application/json",
            "responseJsonSchema": CaptionSchema.model_json_schema(),
        },
    }
    r = httpx.post(url, json=payload, timeout=TIMEOUT_SEC)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini caption HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    parts = (
        ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    )
    text = "".join(str(p.get("text") or "") for p in parts)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError(f"Gemini caption empty: {json.dumps(data)[:300]}")

    inp, out, est = extract_usage_from_http(data)
    if est or (inp == 0 and out == 0):
        inp = estimate_tokens(sys_inst) + estimate_tokens(prompt)
        out = estimate_tokens(text)
        est = True
    record_gemini(
        kind="caption",
        model=MODEL,
        input_tokens=inp,
        output_tokens=out,
        note="generate_caption_httpx",
        estimated=est,
    )
    return json.loads(text[start : end + 1])


def generate_caption(
    slides: list[str],
    topic: str,
    product: str = "",
    *,
    model: str = MODEL,
    host: str = "",  # legacy kwarg, ignored (was Ollama host)
) -> str:
    """
    Возвращает 4 строки caption.txt:
      1 hook, 2 essence, 3 CTA, 4 hashtags

    Строго локальный heuristic — без Gemini (1 API-вызов только на тексты слайдов).
    """
    del host, model  # keep signature for callers
    slides = [s.strip() for s in slides if s and s.strip()]
    return _heuristic_caption(slides, topic, product)
