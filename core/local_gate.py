#!/usr/bin/env python3
"""
Local Ollama controller for agent_gate stages.

Replaces Cursor-agent pauses with:
  - qwen2.5:7b  → text / query approve + rewrite
  - moondream   → photo pick among pool candidates

Deterministic helpers (prop-lock, vibe soft-band, title blacklist) still
run in query_forge / harvester — this module is the LLM brain on top.

Env:
  OLLAMA_HOST              default http://127.0.0.1:11434
  CRITIC_OLLAMA_MODEL      default qwen2.5:7b
  LOCAL_GATE_VISION_MODEL  default moondream
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OLLAMA_HOST = (os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434").strip()
if OLLAMA_HOST and "://" not in OLLAMA_HOST:
    OLLAMA_HOST = "http://" + OLLAMA_HOST
TEXT_MODEL = (os.getenv("CRITIC_OLLAMA_MODEL") or "qwen2.5:7b").strip()
VISION_MODEL = (os.getenv("LOCAL_GATE_VISION_MODEL") or "moondream").strip()

_DNA_ARCH_RE = re.compile(
    r"(study books|clean girl|that girl|soft life|dark academia)",
    re.I,
)
_OFFTOPIC_WELLNESS = (
    "embrace",
    "mindfulness",
    "inner peace",
    "believe in yourself",
    "gratitude journal",
    "lemon water",
    "cold water",
    "deep breaths",
)


def ollama_up() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


def list_models() -> list[str]:
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=5.0)
        r.raise_for_status()
        return [str(m.get("name") or "") for m in (r.json().get("models") or [])]
    except Exception:
        return []


def _model_ready(want: str) -> bool:
    base = want.split(":")[0]
    for name in list_models():
        if name == want or name.startswith(base + ":"):
            return True
    return False


def _extract_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError(f"local_gate: no JSON in response: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def ollama_generate(
    prompt: str,
    *,
    model: str | None = None,
    images_b64: list[str] | None = None,
    temperature: float = 0.1,
    num_predict: int = 400,
    as_json: bool = True,
    timeout: float = 120.0,
) -> dict[str, Any] | str:
    payload: dict[str, Any] = {
        "model": model or TEXT_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    if as_json:
        payload["format"] = "json"
    if images_b64:
        payload["images"] = images_b64
    r = httpx.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"ollama HTTP {r.status_code}: {r.text[:200]}")
    content = (r.json().get("response") or "").strip()
    if as_json:
        return _extract_json(content)
    return content


def _slide_texts_blob(texts: dict[str, Any]) -> str:
    lines = [f"Topic: {texts.get('topic')}"]
    for s in texts.get("slides") or []:
        lines.append(f"[{s.get('index')}] {s.get('text')}")
        scene = (s.get("visual_scene") or "").strip()
        if scene:
            lines.append(f"    scene: {scene}")
    return "\n".join(lines)


def heuristic_text_ok(texts: dict[str, Any]) -> tuple[bool, list[str]]:
    """Fast reject before calling Ollama."""
    problems: list[str] = []
    topic = (texts.get("topic") or "").strip()
    if not topic:
        problems.append("empty topic")
    arch = str(texts.get("dna_archetype") or "")
    if _DNA_ARCH_RE.search(arch):
        problems.append(f"stale DNA archetype: {arch!r}")
    slides = texts.get("slides") or []
    if len(slides) < 4:
        problems.append(f"too few slides ({len(slides)})")
    for s in slides:
        t = (s.get("text") or "").lower()
        for ban in _OFFTOPIC_WELLNESS:
            if ban in t:
                problems.append(f"slide {s.get('index')}: wellness fluff «{ban}»")
                break
        if not (s.get("visual_scene") or "").strip():
            problems.append(f"slide {s.get('index')}: empty visual_scene")
    # Topic keyword overlap — at least one slide should echo topic nouns
    topic_words = {
        w
        for w in re.findall(r"[a-z]{4,}", topic.lower())
        if w
        not in {
            "that",
            "this",
            "with",
            "from",
            "your",
            "when",
            "what",
            "have",
            "just",
            "only",
            "after",
            "every",
            "about",
        }
    }
    if topic_words:
        joined = " ".join((s.get("text") or "").lower() for s in slides)
        hits = sum(1 for w in topic_words if w in joined)
        if hits < max(1, len(topic_words) // 4):
            problems.append("slides barely mention topic keywords")
    return (len(problems) == 0), problems


def approve_texts(texts: dict[str, Any]) -> dict[str, Any]:
    """
    Return {approve: bool, reason: str, problems: [...], source: str}.
    May rewrite slides in-place keys under 'rewritten_slides' if LLM fixes.
    """
    ok, problems = heuristic_text_ok(texts)
    if ok and not ollama_up():
        return {
            "approve": True,
            "reason": "heuristic OK (ollama down)",
            "problems": [],
            "source": "heuristic",
        }
    if not ollama_up():
        return {
            "approve": False,
            "reason": "ollama down + heuristic problems",
            "problems": problems,
            "source": "heuristic",
        }

    prompt = (
        "You gate Instagram confession carousels BEFORE photo harvest.\n"
        "Approve ONLY if every slide stays on the given topic (no wellness fluff, "
        "no Study Books / Clean Girl DNA casting, no off-topic social anxiety "
        "unless the topic is about that).\n"
        "visual_scene must describe a CAMERA FRAME (props, place, light) — "
        "never hair/gender casting.\n\n"
        f"{_slide_texts_blob(texts)}\n\n"
        "Return ONLY JSON:\n"
        '{"approve": true, "reason": "short", "problems": []}\n'
        "If reject: approve=false and list problems as strings."
    )
    try:
        data = ollama_generate(prompt, model=TEXT_MODEL, num_predict=250)
        assert isinstance(data, dict)
        approve = bool(data.get("approve"))
        reason = str(data.get("reason") or "")
        probs = [str(p) for p in (data.get("problems") or [])]
        if problems and approve:
            # heuristic hard vetoes override LLM
            approve = False
            probs = problems + probs
            reason = "heuristic veto + " + reason
        return {
            "approve": approve,
            "reason": reason,
            "problems": probs or problems,
            "source": "ollama",
        }
    except Exception as exc:
        logger.warning("approve_texts ollama failed: %s", exc)
        return {
            "approve": ok,
            "reason": f"ollama failed ({exc}); heuristic={'ok' if ok else 'fail'}",
            "problems": problems,
            "source": "heuristic_fallback",
        }


def lock_queries(queries: dict[str, Any], texts: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Deterministic prop-lock rewrite of queries.json slides.
    Returns updated queries dict + list of notes.
    """
    from core.query_forge import (
        _extract_props,
        normalize_pinterest_query_aliases,
        own_slide_query,
        query_misses_slide_prop,
        vibe_rescue_queries,
    )
    from core.harvester import finalize_photo_query

    notes: list[str] = []
    topic = (queries.get("topic") or "").strip()
    text_by_idx: dict[int, dict[str, Any]] = {}
    if texts:
        for s in texts.get("slides") or []:
            text_by_idx[int(s["index"])] = s

    for row in queries.get("slides") or []:
        idx = int(row["index"])
        slide_text = row.get("text") or ""
        scene = row.get("visual_scene") or ""
        tslide = text_by_idx.get(idx) or {}
        if tslide.get("visual_scene"):
            scene = tslide["visual_scene"]
            row["visual_scene"] = scene
        if tslide.get("text"):
            slide_text = tslide["text"]
            row["text"] = slide_text

        primary = (row.get("primary") or "").strip()
        if query_misses_slide_prop(
            primary, slide_text=slide_text, visual_scene=scene, topic=topic
        ):
            fixed = own_slide_query(
                slide_text=slide_text,
                visual_scene=scene,
                topic=topic,
                slide_index=idx - 1,
                draft_query=primary,
            )
            if query_misses_slide_prop(
                fixed, slide_text=slide_text, visual_scene=scene, topic=topic
            ):
                props = (
                    _extract_props(scene, limit=1)
                    or _extract_props(slide_text, limit=1)
                    or _extract_props(topic, limit=1)
                )
                if props:
                    fixed = normalize_pinterest_query_aliases(
                        finalize_photo_query(props[0], idx - 1, slide_text=slide_text)
                    )
            notes.append(f"slide {idx}: prop-lock {primary!r} -> {fixed!r}")
            row["primary"] = fixed
            row["agent_note"] = (row.get("agent_note") or "") + " [local_gate prop-lock]"
        # refresh alts/rescue lightly from locked primary
        avoid = {row["primary"].lower()}
        alts = list(row.get("alts") or [])
        props = (
            _extract_props(scene, limit=2)
            or _extract_props(f"{slide_text} {topic}", limit=2)
        )
        if props and not any(
            not query_misses_slide_prop(
                a, slide_text=slide_text, visual_scene=scene, topic=topic
            )
            for a in alts
        ):
            alt = own_slide_query(
                slide_text=slide_text,
                visual_scene=scene,
                topic=topic,
                slide_index=idx - 1,
                draft_query=props[0],
            )
            if alt.lower() not in avoid:
                alts = [alt] + [a for a in alts if a.lower() != alt.lower()]
                row["alts"] = alts[:2]
        rescues = vibe_rescue_queries(
            slide_text=slide_text,
            visual_scene=scene,
            topic=topic,
            avoid=avoid | {a.lower() for a in alts},
            max_n=2,
        )
        if rescues:
            row["vibe_rescue"] = rescues

    return {"queries": queries, "notes": notes}


def approve_queries(queries: dict[str, Any], texts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prop-lock first; optional Ollama sanity check."""
    locked = lock_queries(queries, texts)
    queries = locked["queries"]
    notes = locked["notes"]

    from core.query_forge import query_misses_slide_prop

    misses: list[str] = []
    topic = queries.get("topic") or ""
    for row in queries.get("slides") or []:
        if query_misses_slide_prop(
            row.get("primary") or "",
            slide_text=row.get("text") or "",
            visual_scene=row.get("visual_scene") or "",
            topic=topic,
        ):
            misses.append(f"slide {row.get('index')}: primary still misses prop")

    if misses:
        return {
            "approve": False,
            "reason": "prop miss after lock",
            "problems": misses,
            "notes": notes,
            "queries": queries,
            "source": "prop_lock",
        }

    if not ollama_up():
        return {
            "approve": True,
            "reason": "prop-lock OK (ollama down)",
            "problems": [],
            "notes": notes,
            "queries": queries,
            "source": "prop_lock",
        }

    lines = [f"Topic: {topic}"]
    for row in queries.get("slides") or []:
        lines.append(
            f"[{row.get('index')}] text={row.get('text')!r}\n"
            f"    scene={row.get('visual_scene')!r}\n"
            f"    primary={row.get('primary')!r} alts={row.get('alts')}"
        )
    prompt = (
        "Check Pinterest search queries for a confession carousel.\n"
        "Each primary MUST name the concrete prop from visual_scene "
        "(window/fridge/bread/hand/sky…), not abstract filler.\n"
        "Reject fashion lookbook / brand storefront queries.\n\n"
        + "\n".join(lines)
        + "\n\nReturn ONLY JSON: "
        '{"approve": true, "reason": "", "problems": []}'
    )
    try:
        data = ollama_generate(prompt, model=TEXT_MODEL, num_predict=220)
        assert isinstance(data, dict)
        return {
            "approve": bool(data.get("approve")),
            "reason": str(data.get("reason") or ""),
            "problems": [str(p) for p in (data.get("problems") or [])],
            "notes": notes,
            "queries": queries,
            "source": "ollama+prop_lock",
        }
    except Exception as exc:
        return {
            "approve": True,
            "reason": f"prop-lock OK; ollama skip ({exc})",
            "problems": [],
            "notes": notes,
            "queries": queries,
            "source": "prop_lock",
        }


_JUNK_VISION_HINTS = (
    "mannequin",
    "retail display",
    "brand logo",
    "store logo",
    "product pack",
    "organized pantry",
    "meal prep containers",
    "instagram ui",
    "camera app ui",
    "screenshot",
    "horror glowing eyes",
    "stock white background",
)


def _img_b64(path: Path, *, max_side: int = 768) -> str:
    from PIL import Image
    import io

    im = Image.open(path).convert("RGB")
    w, h = im.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        im = im.resize((int(w * scale), int(h * scale)), Image.Resampling.BILINEAR)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _pil_b64(im: Any, *, max_side: int = 768) -> str:
    """Encode a PIL image for Ollama vision (no disk round-trip)."""
    import io
    from PIL import Image

    if not isinstance(im, Image.Image):
        raise TypeError("expected PIL Image")
    rgb = im.convert("RGB")
    w, h = rgb.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        rgb = rgb.resize((int(w * scale), int(h * scale)), Image.Resampling.BILINEAR)
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def vision_borderline_is_live(
    image: Any,
    *,
    scene: str = "",
    slide_text: str = "",
) -> dict[str, Any]:
    """
    Moondream glance for UGC soft-band frames (0.32–0.55).

    Returns {ok: bool, keep: bool, score: float, why: str, source: str}
    ok=False → vision unavailable / failed (caller decides fail-closed).
    """
    ask = (
        f"Scene: {(scene or slide_text or 'everyday candid')[:100]}\n"
        "Real phone UGC candid? YES=messy lived-in life. "
        "NO=glossy stock, studio, brand shelf, meal-prep aesthetic, packshot.\n"
        "Reply with ONLY one line:\n"
        "KEEP 8 reason\n"
        "or\n"
        "DROP 2 reason"
    )
    if not ollama_up() or not _model_ready(VISION_MODEL):
        return {
            "ok": False,
            "keep": False,
            "score": 0.0,
            "why": "vision unavailable",
            "source": "offline",
        }
    try:
        b64 = _pil_b64(image)
        raw = ollama_generate(
            ask,
            model=VISION_MODEL,
            images_b64=[b64],
            num_predict=40,
            as_json=False,
            timeout=60.0,
        )
        assert isinstance(raw, str)
        s = (raw or "").strip()
        # Take first non-empty line — ignore probability dumps
        line = ""
        for ln in s.splitlines():
            t = ln.strip()
            if t:
                line = t
                break
        if not line:
            line = s
        # "1. KEEP 8 …" / "- DROP 2 …"
        line = re.sub(r"^[\d\.\)\-]+\s*", "", line).strip()
        up = line.upper()
        keep: bool | None = None
        if re.match(r"^(KEEP|YES)\b", up):
            keep = True
        elif re.match(r"^(DROP|REJECT|NO)\b", up):
            keep = False
        elif "KEEP" in up and "DROP" not in up:
            keep = True
        elif "DROP" in up or "REJECT" in up:
            keep = False
        else:
            # No clear verdict → treat as vision failure (fail-closed upstream)
            return {
                "ok": False,
                "keep": False,
                "score": 0.0,
                "why": f"unparsed: {line[:60]}",
                "source": "parse_fail",
            }
        m = re.search(r"(?:KEEP|DROP|YES|NO)\s*([1-9]|10)\b", line, flags=re.I)
        score = float(m.group(1)) if m else (7.0 if keep else 2.0)
        why = re.sub(
            r"^(KEEP|DROP|REJECT|YES|NO)\s*\d*\s*",
            "",
            line,
            flags=re.I,
        ).strip()[:80]
        low = why.lower()
        if any(h in low for h in _JUNK_VISION_HINTS):
            keep = False
            score = min(score, 3.0)
        if keep and score < 5:
            keep = False
            why = (why + " | weak keep").strip(" |")
        try:
            from core.usage_meter import record_local_judge

            record_local_judge(model=VISION_MODEL, note="borderline_ugc")
        except Exception:
            pass
        return {
            "ok": True,
            "keep": bool(keep),
            "score": float(score),
            "why": why or ("live candid" if keep else "stock/gloss"),
            "source": "moondream",
        }
    except Exception as exc:
        logger.warning("borderline vision fail: %s", exc)
        return {
            "ok": False,
            "keep": False,
            "score": 0.0,
            "why": f"{exc.__class__.__name__}",
            "source": "error",
        }


def _candidate_shortlist(
    candidates: list[dict[str, Any]],
    *,
    scene: str,
    text: str,
    max_n: int = 8,
) -> list[dict[str, Any]]:
    """Prefer PASS/PASS_SOFT; for vibe scenes also high-rel DROPs."""
    from core.harvester import is_vibe_scene

    passes = [c for c in candidates if str(c.get("verdict", "")).startswith("PASS")]
    if len(passes) >= 3:
        return sorted(passes, key=lambda c: -float(c.get("final") or 0))[:max_n]

    vibe = is_vibe_scene(scene, slide_text=text)
    extras: list[dict[str, Any]] = []
    if vibe:
        for c in candidates:
            if str(c.get("verdict", "")).startswith("PASS"):
                continue
            if float(c.get("rel") or 0) >= 0.55 and float(c.get("ugc") or 0) >= 0.25:
                extras.append(c)
    pool = passes + extras
    if not pool:
        pool = list(candidates)
    return sorted(pool, key=lambda c: -float(c.get("final") or 0))[:max_n]


def pick_from_pool(
    *,
    sess: Path,
    slide_no: int,
    scores: dict[str, Any],
) -> dict[str, Any]:
    """
    Vision-rank shortlist with moondream; fallback = best PASS by final score.
    Returns {pin_id, reason, source, scores: [...]}
    """
    scene = scores.get("scene") or ""
    text = scores.get("text") or ""
    cands = list(scores.get("candidates") or [])
    short = _candidate_shortlist(cands, scene=scene, text=text)
    if not short:
        return {
            "pin_id": None,
            "reason": "empty pool",
            "source": "none",
            "scores": [],
        }

    # Fallback without vision
    def _fallback(reason: str) -> dict[str, Any]:
        best = short[0]
        return {
            "pin_id": best["pin_id"],
            "reason": reason,
            "source": "score_fallback",
            "scores": [
                {"pin_id": c["pin_id"], "verdict": c.get("verdict"), "final": c.get("final")}
                for c in short[:5]
            ],
        }

    if not ollama_up() or not _model_ready(VISION_MODEL):
        return _fallback("vision model unavailable — top PASS/final")

    ranked: list[dict[str, Any]] = []
    # moondream is tiny — keep prompt short, parse KEEP/DROP + score loosely
    ask = (
        f"Slide need: {scene or text}\n"
        "Is this a candid real-life photo matching that scene?\n"
        "REJECT: mannequin, brand store, pantry org, product pack, phone UI, fashion lookbook.\n"
        "Answer exactly like: KEEP 8 reason-here   OR   DROP 2 reason-here"
    )

    def _parse_vision(raw: str) -> tuple[bool, float, str]:
        s = (raw or "").strip()
        # JSON path
        try:
            if "{" in s:
                data = _extract_json(s)
                keep = bool(data.get("keep", data.get("KEEP", False)))
                score = float(data.get("score") or 0)
                why = str(data.get("why") or data.get("reason") or "")
                return keep, score, why
        except Exception:
            pass
        up = s.upper()
        keep = up.startswith("KEEP") or " KEEP" in f" {up}"
        if up.startswith("DROP") or up.startswith("REJECT"):
            keep = False
        m = re.search(r"\b([1-9]|10)\b", s)
        score = float(m.group(1)) if m else (7.0 if keep else 2.0)
        why = re.sub(r"^(KEEP|DROP|REJECT)\s*\d*\s*", "", s, flags=re.I).strip()[:80]
        return keep, score, why or s[:80]

    for c in short:
        path = sess / c["file"]
        if not path.is_file():
            continue
        try:
            b64 = _img_b64(path)
            raw = ollama_generate(
                ask,
                model=VISION_MODEL,
                images_b64=[b64],
                num_predict=60,
                as_json=False,
                timeout=90.0,
            )
            assert isinstance(raw, str)
            keep, score, why = _parse_vision(raw)
            low_why = why.lower()
            junk_hit = any(h in low_why for h in _JUNK_VISION_HINTS)
            if junk_hit:
                keep = False
                score = min(score, 3.0)
            # moondream is tiny — empty/weak DROP should not kill a strong PASS
            verdict = str(c.get("verdict") or "")
            final_v = float(c.get("final") or 0)
            if (
                not keep
                and not junk_hit
                and verdict.startswith("PASS")
                and final_v >= 0.45
            ):
                keep = True
                score = max(score, min(9.0, final_v * 12))
                why = (why + " | soft-keep PASS").strip(" |")
            ranked.append(
                {
                    "pin_id": c["pin_id"],
                    "keep": keep,
                    "score": score,
                    "why": why,
                    "final": c.get("final"),
                    "verdict": c.get("verdict"),
                }
            )
            print(
                f"  [local_gate] {c['pin_id'][-8:]} keep={keep} "
                f"score={score:.0f} · {why[:60]}",
                flush=True,
            )
        except Exception as exc:
            logger.warning("vision pick fail %s: %s", c.get("pin_id"), exc)
            continue

    keepers = [r for r in ranked if r.get("keep") and float(r.get("score") or 0) >= 5]
    if not keepers:
        keepers = [r for r in ranked if r.get("keep")]
    if keepers:
        best = max(
            keepers,
            key=lambda r: (float(r.get("score") or 0), float(r.get("final") or 0)),
        )
        return {
            "pin_id": best["pin_id"],
            "reason": best.get("why") or "vision keep",
            "source": "moondream",
            "scores": ranked,
        }
    return _fallback("vision rejected all - top final score")
