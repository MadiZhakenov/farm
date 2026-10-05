#!/usr/bin/env python3
"""
Пакетная сборка каруселей: Gemini -> Pinterest -> Color Matcher -> render -> disk.

Строго последовательно, gc.collect() после каждой карусели (8 ГБ RAM/VRAM).
"""

from __future__ import annotations

import gc
import hashlib
import json
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from core.caption_engine import generate_caption
from core.carousel_rules import (
    FILLER_ROLES,
    RULES_ENABLED,
    SEMANTIC_ROLES,
    UsedIndex,
    build_photo_plans,
    enforce_carousel_rules,
    image_fingerprint,
    neutral_plan,
    query_subjects,
)
from core.filler_bank import FillerBank
from core import ugc_filter
from core.ugc_filter import LivenessModelError
from core.color_matcher import get_color_profile, get_harmony_score
from core.harvester import (
    CandidateImage,
    PinterestHarvester,
    weighted_promote_top3,
)
from core.llm_engine import OllamaGenerator
from core.renderer import render_slide
from core.visual_judge import combined_rank_score

ProgressCb = Callable[[str], None]
CarouselDoneCb = Callable[[int, int, Path], None]  # idx, total, folder

CANDIDATES = 10
MIN_KEEP = 3
# Формат «короткая мысль» — 3 слайда, «польза» — до 10 (см. llm_engine)
MIN_SLIDES = 3
MAX_SLIDES = 10
MAX_ALTS_SAVED = 6
# Темы/карусели не своей категории пропускаются (фидбек: «10 не про еду»)
CATEGORY_FILTER_ENABLED = True
# Preflight-поиск Pinterest не повторять, если сеть отдавала пины недавно
PREFLIGHT_SKIP_SEC = 300.0



class OffCategoryError(RuntimeError):
    """Gemini написала карусель не про категорию пачки — карусель не собираем."""


def hard_gc() -> None:
    gc.collect()
    gc.collect()


@dataclass
class BatchSlide:
    text: str
    query: str
    candidates: list[CandidateImage] = field(default_factory=list)
    selected: int = 0
    color_profiles: list[dict[str, Any]] = field(default_factory=list)
    harmony_scores: list[float] = field(default_factory=list)


@dataclass
class BatchResult:
    run_dir: Path
    made: int = 0
    failed: int = 0
    folders: list[Path] = field(default_factory=list)
    skipped: int = 0  # темы не своей категории


def _reorder_batch_slide(
    slide: BatchSlide, order: list[int], scores_orig: list[float]
) -> None:
    if not order:
        slide.harmony_scores = []
        slide.selected = 0
        return
    slide.candidates = [slide.candidates[i] for i in order]
    if slide.color_profiles and len(slide.color_profiles) == len(order):
        slide.color_profiles = [slide.color_profiles[i] for i in order]
    slide.harmony_scores = [scores_orig[i] for i in order]
    slide.selected = 0


def _selection_rng(topic: str, variation_index: int) -> random.Random:
    """Сид от темы: те же тексты → те же фото (честное сравнение «до/после»)."""
    digest = hashlib.sha1(f"{topic}|{variation_index}".encode("utf-8")).hexdigest()
    return random.Random(int(digest[:12], 16))


def _apply_combined_ranking(
    slide: BatchSlide, rng: random.Random | None = None
) -> None:
    """
    Порядок кандидатов слайда после сборщика. Выбор сборщика (_wide_assign
    видит всю карусель: смысл, предметы, близнецы) остаётся в [0], если
    проходит полы живости и вкуса; цвет и общий балл лишь упорядочивают
    запасные кадры. Случайный топ-3 (сид от темы) берёт только кадры не
    дальше от текста, чем выбор сборщика (аудит 2026-10-05, №7).
    """
    if not slide.candidates:
        return
    from core.harvester import TASTE_ENABLED, TASTE_HARD_FLOOR, UGC_HARD_FLOOR

    def _floor_ok(c: Any) -> bool:
        return float(getattr(c, "ugc_score", 0) or 0) >= UGC_HARD_FLOOR and (
            not TASTE_ENABLED
            or float(getattr(c, "taste_score", 0) or 0) >= TASTE_HARD_FLOOR
        )

    def _rel(c: Any) -> float | None:
        if not getattr(c, "text_relevance_scored", False):
            return None
        return float(getattr(c, "text_relevance", 0.0) or 0.0)

    lead = slide.candidates[0]
    lead_rel = _rel(lead)

    def _on_topic(c: Any) -> bool:
        r = _rel(c)
        return lead_rel is None or r is None or r >= lead_rel

    eligible_ids = {id(c) for c in slide.candidates if _floor_ok(c)}
    n = len(slide.candidates)
    if len(slide.harmony_scores) != n:
        slide.harmony_scores = [
            float(getattr(c, "harmony_score", 100.0) or 100.0)
            for c in slide.candidates
        ]
    scored: list[tuple[float, int]] = []
    for i, cand in enumerate(slide.candidates):
        rel = float(getattr(cand, "text_relevance", 0.5) or 0.5)
        ugc = float(getattr(cand, "ugc_score", 0.5) or 0.5)
        taste = (
            float(cand.taste_score)
            if getattr(cand, "taste_scored", False)
            else 0.5
        )
        harm = float(slide.harmony_scores[i] if i < len(slide.harmony_scores) else 0)
        cand.harmony_score = harm
        # Жёсткий штраф ниже пола — не выиграть hard_top3
        if id(cand) not in eligible_ids:
            combined = -1.0
        else:
            combined = combined_rank_score(
                ugc, taste=taste, harmony=harm, relevance=rel
            )
        cand.combined_score = combined
        scored.append((combined, i))
    # выбор сборщика (если проходит полы) — первым, остальные по баллу
    lead_first = id(lead) in eligible_ids
    scored.sort(key=lambda x: (lead_first and x[1] == 0, x[0]), reverse=True)
    order = [i for _, i in scored]
    _reorder_batch_slide(slide, order, list(slide.harmony_scores))
    promote = [
        c for c in slide.candidates if id(c) in eligible_ids and _on_topic(c)
    ] or [c for c in slide.candidates if id(c) in eligible_ids]
    rest = [c for c in slide.candidates if all(c is not p for p in promote)]
    prior = getattr(lead, "selection_mode", "") or ""
    slide.selected = 0
    if not promote:
        # не сэмплить сток — пусть правила/дозапрос ищут живое
        print("[rank] no eligible ugc/taste — keep order, selected may refill")
        return
    if prior.startswith("emergency") or prior == "single_pass_argmax":
        if id(lead) not in eligible_ids:
            slide.candidates = promote + rest
            print(
                f"[rank] replaced emergency ugc="
                f"{float(getattr(lead, 'ugc_score', 0) or 0):.0%} "
                f"-> ugc={float(slide.candidates[0].ugc_score):.0%}"
            )
        return
    slide.candidates = (
        weighted_promote_top3(promote, mode="hard_top3_sample", rng=rng) + rest
    )


def apply_color_harmony(
    slides: list[BatchSlide], rng: random.Random | None = None
) -> None:
    """Якорь = слайд 1; ранг = rel×0.30 + taste×0.30 + ugc×0.40 (+ harm soft)."""
    if not slides:
        return
    for s in slides:
        if s.candidates:
            s.color_profiles = [get_color_profile(c.image) for c in s.candidates]
    if not slides[0].candidates:
        return

    anchor_slide = slides[0]
    anchor_slide.harmony_scores = [100.0] * len(anchor_slide.candidates)
    for c in anchor_slide.candidates:
        c.harmony_score = 100.0
    _apply_combined_ranking(anchor_slide, rng)

    anchor = anchor_slide.color_profiles[anchor_slide.selected]
    for s in slides[1:]:
        if not s.candidates:
            s.harmony_scores = []
            continue
        scores_orig = [get_harmony_score(anchor, p) for p in s.color_profiles]
        s.harmony_scores = scores_orig
        for c, h in zip(s.candidates, scores_orig):
            c.harmony_score = float(h)
        _apply_combined_ranking(s, rng)

    # CRITICAL: harmony reorder can put the same pin back to [0] on two slides
    from core.harvester import dedupe_selected_across_slides

    pools = [list(s.candidates) for s in slides]
    fixed = dedupe_selected_across_slides(pools)
    for s, pool in zip(slides, fixed):
        before = str(s.candidates[0].pin_id) if s.candidates else ""
        s.candidates = pool
        s.selected = 0
        after = str(s.candidates[0].pin_id) if s.candidates else ""
        if before and after and before != after:
            print(f"[dedupe/harmony] selected {before} -> {after}")
        if before and not after:
            print(
                f"[WARNING] dedupe/harmony: slide lost all unique pins "
                f"(was {before}) — guarantee will refill"
            )


def _pinterest_preflight(harvester: PinterestHarvester) -> None:
    try:
        harvester.warm_session(force=False)
        probe = harvester.search("coffee table", finalize=False)
        if not probe:
            probe = harvester.search("keys desk", finalize=False)
        if not probe:
            raise RuntimeError(
                "Pinterest недоступен (сеть=0 на probe «coffee table»). "
                "Проверь VPN/firewall/прокси — SSL handshake к pinterest.com "
                "сейчас не проходит. Gemini-текст уже сгенерирован, но фото "
                "скачать нельзя."
            )
        print(f"[Pinterest] preflight OK · {len(probe)} pins на probe")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"Pinterest preflight fail: {exc}. "
            "Сеть до pinterest.com недоступна — фото не скачать."
        ) from exc


def build_one_carousel(
    *,
    llm: OllamaGenerator,
    harvester: PinterestHarvester,
    topic: str,
    product: str,
    out_dir: Path,
    index: int,
    variation_index: int,
    on_status: ProgressCb | None = None,
    folder_name: str | None = None,
    used_pins_run: set[str] | None = None,
    avoid_character_dnas: list[dict[str, str]] | None = None,
    batch_index: int = 0,
    batch_memory: dict[str, list[str]] | None = None,
    used_index: UsedIndex | None = None,
    category: str | None = None,
    filler_bank: FillerBank | None = None,
) -> Path:
    def status(msg: str) -> None:
        if on_status:
            on_status(msg)

    def _timer(label: str, t0: float) -> float:
        dt = time.perf_counter() - t0
        print(f"[TIMER] {label}: {dt:.1f} с")
        return dt

    t_carousel = time.perf_counter()

    # Прогрев SigLIP на CUDA один раз (чтобы таймер сети не включал load)
    t_warm = time.perf_counter()
    try:
        from core.taste_embedder import get_embedder

        emb = get_embedder()
        emb.ensure()
        print(
            f"[TIMER] 0. SigLIP warm ({emb.device}): "
            f"{time.perf_counter() - t_warm:.1f} с"
        )
    except Exception as exc:
        print(f"[WARNING] SigLIP warm fail: {exc}")
    # moondream в VRAM в фоне, пока идут Gemini + Pinterest (cold start ~28 с)
    try:
        from core.harvester import BORDERLINE_JUDGE, BORDERLINE_VISION_ENABLED

        if BORDERLINE_VISION_ENABLED and BORDERLINE_JUDGE == "moondream":
            from core.local_gate import warm_vision_model

            warm_vision_model()
    except Exception as exc:
        print(f"[WARNING] vision warm fail: {exc}")

    status(f"[{index}] Gemini · unique angle #{variation_index + 1}…")
    t1 = time.perf_counter()
    result = llm.generate_carousel(
        topic,
        product_name=product,
        variation_index=variation_index,
        avoid_character_dnas=avoid_character_dnas,
        batch_index=batch_index,
        batch_memory=batch_memory,
    )
    _timer("1. Генерация текста (Gemini)", t1)

    slides_raw = result.get("slides") or []
    texts = [str(s.get("text") or "").strip() for s in slides_raw if s.get("text")]
    queries = [
        str(s.get("search_query") or "").strip() for s in slides_raw if s.get("text")
    ]
    scenes = [
        str(s.get("visual_scene") or "").strip() for s in slides_raw if s.get("text")
    ]
    if len(texts) < MIN_SLIDES:
        raise RuntimeError(
            f"Too few slides from LLM: {len(texts)} (need ≥{MIN_SLIDES})"
        )

    texts = texts[:MAX_SLIDES]
    queries = queries[: len(texts)]
    scenes = (scenes + [""] * len(texts))[: len(texts)]

    if category and CATEGORY_FILTER_ENABLED:
        from core.niches import fits_category

        if not fits_category(category, topic, texts):
            raise OffCategoryError(
                f"карусель не про категорию «{category}» — пропуск темы"
            )

    # Run-level ban: финалы прошлых каруселей. Soft-reuse только
    # после полного истощения пула (см. _select_pins_avoiding_used).
    harvester.reset_used()
    if used_pins_run:
        harvester.seed_used(used_pins_run)
    # Серия: фото из прошлых запусков тоже заняты (одно фото — одна карусель)
    if used_index is not None and used_index.pins:
        harvester.seed_used(used_index.pins)
    scene_specs: list[tuple[str, str, list[str]]] = []
    character_dna = result.get("character_dna")
    if not isinstance(character_dna, dict):
        character_dna = None
    for i, text in enumerate(texts):
        q = queries[i] if i < len(queries) and queries[i] else text
        scene = scenes[i] if i < len(scenes) else ""
        from core.query_forge import own_slide_queries

        primary, alts = own_slide_queries(
            slide_text=text,
            visual_scene=scene,
            topic=topic,
            slide_index=i,
            draft_query=q,
            character_dna=character_dna,
            max_alts=2,
        )
        scene_specs.append((primary, scene, list(alts)))

    # Роли слайдов (фидбек 2026-10-02): смысловые — хук и слайд с продуктом
    # (без продукта — один в середине), остальное — филлеры из разных
    # семейств сцен; последний — всегда приятный. Филлеры, для которых в
    # банке батча уже есть кадры, в Pinterest не идут.
    plans, heavy = build_photo_plans(
        texts,
        scene_specs,
        topic=topic,
        seed=f"{index}:{variation_index}",
        enabled=RULES_ENABLED,
        product=product,
    )
    roles = [p.role for p in plans]
    # (query, text, idx, scene, alt_queries) — text здесь только для поиска
    specs: list[tuple] = []
    bank_cands: dict[int, list] = {}
    for i, plan in enumerate(plans):
        specs.append((plan.query, plan.search_text, i, plan.visual_scene, plan.alts))
        if filler_bank is not None and plan.role in FILLER_ROLES:
            got = filler_bank.take(plan.query)
            if got:
                bank_cands[i] = got
        print(
            f"[query-owner] slide {i + 1} [{plan.role}]: {plan.query!r}"
            + (f" +alts={plan.alts}" if plan.alts else "")
            + (f" · из банка ({len(bank_cands[i])})" if i in bank_cands else ""),
            flush=True,
        )
    live = [i for i in range(len(specs)) if i not in bank_cands]
    if heavy:
        print("[rules] тяжёлая тема: в середине можно темнее, финал спокойный")

    status(f"[{index}] Pinterest parallel · {len(specs)} слайдов…")
    # Быстрый preflight: если Pinterest недоступен — сразу понятная ошибка.
    # Сеть отвечала пинами недавно (прошлая карусель) — лишний поиск не нужен.
    last_ok = float(getattr(harvester, "last_search_ok_ts", 0.0) or 0.0)
    if time.monotonic() - last_ok < PREFLIGHT_SKIP_SEC:
        print(
            f"[Pinterest] preflight skip · сеть отвечала < "
            f"{PREFLIGHT_SKIP_SEC:.0f} с назад"
        )
    else:
        _pinterest_preflight(harvester)

    harvester.reset_timing()
    harvested_live = (
        harvester.harvest_slides_parallel(
            [specs[i] for i in live],
            limit=CANDIDATES,
            min_keep=max(1, MIN_KEEP),
            topic=topic,
            max_attempts=1,
            max_workers=3,
            character_dna=character_dna,
            roles=[roles[i] for i in live],
        )
        if live
        else []
    )
    harvested: list[Any] = [None] * len(specs)
    for i, res in zip(live, harvested_live):
        harvested[i] = res
        if filler_bank is not None and roles[i] in FILLER_ROLES and res[0]:
            # в банк — только кадры, найденные запросом этого филлера
            own = [c for c in res[0] if getattr(c, "_wide_own", True)]
            filler_bank.add(plans[i].query, own[:CANDIDATES])
    for i, cands in bank_cands.items():
        harvested[i] = (cands[:CANDIDATES], None, plans[i].query)
    print(
        f"[TIMER] 2. Поиск и фильтрация в Pinterest (все слайды): "
        f"{float(harvester.timing_pinterest_sec):.1f} с"
    )
    print(
        f"[TIMER] 3. Расчет SigLIP (UGC + Relevance + Taste): "
        f"{float(harvester.timing_siglip_sec):.1f} с"
    )

    batch_slides: list[BatchSlide] = []
    for i, (spec, (cands, _prog, used_q)) in enumerate(zip(specs, harvested)):
        query = str(spec[0] or "")
        # На слайде рисуется настоящий текст, а не поисковый текст роли
        text = texts[i] if i < len(texts) else str(spec[1] or "")
        batch_slides.append(
            BatchSlide(
                text=text,
                query=used_q or query,
                candidates=cands[:CANDIDATES],
                selected=0,
            )
        )
    status(f"[{index}] Color Matcher + локальный вкус…")
    apply_color_harmony(batch_slides, rng=_selection_rng(topic, variation_index))

    rule_results = []
    if RULES_ENABLED:
        status(f"[{index}] Правила карусели (грязь / место / повторы)…")
        t_rules = time.perf_counter()

        def _refill(slide_i: int) -> list:
            """Для финала/нейтрального слайда: ещё один чистый запрос
            другого семейства (сначала — из банка филлеров)."""
            if roles[slide_i] in SEMANTIC_ROLES:
                return []
            taken = {str(sp[0]).lower() for sp in specs}
            subjects: set[str] = set()
            for k, p in enumerate(plans):
                if k != slide_i:
                    subjects |= query_subjects(p.query)
            extra_plan = neutral_plan(
                roles[slide_i],
                topic=topic,
                slide_text=texts[slide_i],
                slide_index=slide_i + 100,
                heavy=heavy,
                seed=f"refill:{index}:{variation_index}",
                taken=taken,
                used_subjects=subjects,
            )
            print(f"[rules] слайд {slide_i + 1}: дозапрос «{extra_plan.query}»")
            if filler_bank is not None:
                got = filler_bank.take(extra_plan.query)
                if got:
                    print(f"[rules] слайд {slide_i + 1}: дозапрос из банка ({len(got)})")
                    return got
            more, _p, _q = harvester.harvest_until_filled(
                extra_plan.query,
                slide_text=extra_plan.search_text,
                slide_index=slide_i,
                limit=CANDIDATES,
                min_keep=1,
                topic=topic,
                visual_scene=extra_plan.visual_scene,
                alt_queries=extra_plan.alts,
            )
            more = list(more or [])
            gender = (character_dna or {}).get("gender")
            if more and gender in ("female", "male"):
                from core.harvester import apply_gender_lock_filter

                more, _dropped = apply_gender_lock_filter(
                    more, gender, slide_index=slide_i, query=extra_plan.query
                )
            if filler_bank is not None and more:
                filler_bank.add(extra_plan.query, more[:CANDIDATES])
            return more

        rule_results = enforce_carousel_rules(
            batch_slides,
            roles=roles,
            heavy=heavy,
            used=used_index,
            refill=_refill,
        )
        _timer("3b. Правила карусели", t_rules)

    # Atomic contract: every slide must have a photo BEFORE any final JPG is written.
    empty_idx = [i for i, s in enumerate(batch_slides) if not s.candidates]
    if empty_idx:
        raise RuntimeError(
            "No photos for slide(s) "
            + ", ".join(str(i + 1) for i in empty_idx)
            + " after completion fill — refusing incomplete carousel"
        )

    folder = out_dir / (folder_name or f"carousel_{index:03d}")
    # Wipe any previous partial attempt for this folder name
    if folder.exists():
        for stale in folder.glob("*.jpg"):
            try:
                stale.unlink()
            except Exception:
                pass
        meta_stale = folder / "meta.json"
        if meta_stale.exists():
            try:
                meta_stale.unlink()
            except Exception:
                pass
    folder.mkdir(parents=True, exist_ok=True)
    alts_root = folder / "alts"
    alts_root.mkdir(exist_ok=True)

    meta: dict[str, Any] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "topic": topic,
        "product": product,
        "variation_index": variation_index,
        "model": result.get("model"),
        "dna_archetype": result.get("dna_archetype"),
        "character_dna": character_dna,
        "attribute_consistency": (
            getattr(harvester, "last_attribute_consistency", None)
            or ("pass" if character_dna else None)
        ),
        "quality": result.get("quality"),
        "few_shot_source": result.get("few_shot_source"),
        "slides": [],
        "complete": True,
        "n_slides": len(batch_slides),
        "category": category,
        "photo_roles": roles,
        "heavy_topic": heavy,
        "format": result.get("format"),
    }

    status(f"[{index}] Render + Negative Space…")
    t4 = time.perf_counter()
    selected_pins: list[str] = []
    try:
        for i, s in enumerate(batch_slides):
            if not s.candidates:
                raise RuntimeError(
                    f"No photos for slide {i + 1} (race: emptied before render)"
                )
            alt_pin_ids: list[str] = []
            for j, cand in enumerate(s.candidates[:MAX_ALTS_SAVED]):
                alt_path = alts_root / f"{i + 1}_{j}.jpg"
                try:
                    cand.image.convert("RGB").save(alt_path, quality=85, optimize=True)
                except Exception:
                    pass
                if cand.pin_id:
                    alt_pin_ids.append(str(cand.pin_id))

            cand = s.candidates[s.selected]
            if cand.pin_id:
                selected_pins.append(str(cand.pin_id))
            rendered, rmeta = render_slide(cand.image, s.text)
            out_jpg = folder / f"{i + 1}.jpg"
            rendered.save(out_jpg, quality=92, optimize=True)
            sel_mode = getattr(cand, "selection_mode", "") or "single_pass_argmax"
            reuse_flag = bool(getattr(cand, "reuse_after_exhaustion", False))
            slide_meta: dict[str, Any] = {
                "index": i + 1,
                "text": s.text,
                "query": s.query,
                "selected_alt": s.selected,
                "alt_count": min(len(s.candidates), MAX_ALTS_SAVED),
                "pin_id": cand.pin_id,
                "alt_pin_ids": alt_pin_ids,
                "selection_mode": sel_mode,
                "relevance_score": float(cand.relevance_score or 0),
                "text_relevance": (
                    round(float(cand.text_relevance), 4)
                    if getattr(cand, "text_relevance_scored", False)
                    else None
                ),
                "taste_score": (
                    round(float(cand.taste_score), 4)
                    if getattr(cand, "taste_scored", False)
                    else None
                ),
                "ugc_score": (
                    round(float(cand.ugc_score), 4)
                    if getattr(cand, "ugc_scored", False)
                    else None
                ),
                "relevance_reason": cand.relevance_reason or "",
                "combined_score": float(cand.combined_score or 0),
                "slot": getattr(rmeta, "slot", None),
                "font_size": rmeta.font_size,
                "file": out_jpg.name,
            }
            if reuse_flag:
                slide_meta["reuse_after_exhaustion"] = True
            if i < len(rule_results):
                slide_meta.update(rule_results[i].to_meta())
            # alt-файл -> pin_id (для учёта при ручной замене в отсмотре)
            slide_meta["alt_pins"] = {
                str(j): str(c.pin_id)
                for j, c in enumerate(s.candidates[:MAX_ALTS_SAVED])
                if getattr(c, "pin_id", None)
            }
            meta["slides"].append(slide_meta)
            del rendered
            hard_gc()
    except Exception:
        # Never leave a half-rendered carousel for Quick Review
        for stale in folder.glob("*.jpg"):
            try:
                stale.unlink()
            except Exception:
                pass
        raise

    # Sanity: rendered count must equal slide count
    final_jpgs = sorted(folder.glob("[0-9]*.jpg"))
    if len(final_jpgs) != len(batch_slides) or len(meta["slides"]) != len(batch_slides):
        for stale in folder.glob("*.jpg"):
            try:
                stale.unlink()
            except Exception:
                pass
        raise RuntimeError(
            f"Incomplete render: {len(final_jpgs)}/{len(batch_slides)} jpgs — wiped"
        )

    _timer("4. Рендер картинок и Negative Space", t4)

    # Только pin_id реально пошедших на финальный JPEG (selected=0).
    # Отвергнутые alts / сырой пул в used_pins_run НЕ попадают.
    # Банк филлеров: кадр-филлер идёт не больше чем в MAX_REUSE каруселей
    if filler_bank is not None:
        filler_bank.mark_used(
            str(s.candidates[s.selected].pin_id or "")
            for k, s in enumerate(batch_slides)
            if s.candidates and roles[k] in FILLER_ROLES
        )
    if used_pins_run is not None and selected_pins:
        used_pins_run.update(selected_pins)
        harvester.mark_used(selected_pins)
        print(
            f"[dedupe] финалы карусели -> used_pins_run "
            f"+{len(selected_pins)} (всего {len(used_pins_run)})"
        )

    # PhotoVault: авто-регистрация финальных фото в библиотеку + учёт серии
    carousel_key = str(folder.resolve())
    try:
        from core.photo_vault import get_photo_vault

        vault = get_photo_vault()
        vault.release_carousel(carousel_key)
        vault_items: list[dict[str, Any]] = []
        for si, s in enumerate(batch_slides):
            if not s.candidates:
                continue
            cand = s.candidates[s.selected]
            if not cand.pin_id:
                continue
            vault_items.append(
                {
                    "pin_id": str(cand.pin_id),
                    "image": cand.image,
                    "query": s.query,
                    "image_url": getattr(cand, "source_url", "") or "",
                    "tags": topic,
                    "carousel": carousel_key,
                    "slide": si + 1,
                }
            )
        if vault_items:
            vault.register_selected(vault_items)
    except Exception as exc:
        print(f"[vault] auto-register skip: {exc}")
    # Следующие карусели этого запуска тоже не берут эти фото
    if used_index is not None:
        for s in batch_slides:
            if s.candidates:
                cand = s.candidates[s.selected]
                used_index.add(cand.pin_id, image_fingerprint(cand.image))

    status(f"[{index}] Caption…")
    caption = generate_caption(texts, topic, product)
    (folder / "caption.txt").write_text(caption + "\n", encoding="utf-8")
    if any(
        bool(s.get("reuse_after_exhaustion")) for s in meta.get("slides", [])
    ):
        meta["reuse_after_exhaustion"] = True
    (folder / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for s in batch_slides:
        for c in s.candidates:
            try:
                c.image.close()
            except Exception:
                pass
        s.candidates.clear()
    # Пачка: следующие карусели не повторяют хук / вступления / CTA / архетип
    from core.llm_engine import remember_carousel

    remember_carousel(batch_memory, result)
    del batch_slides, result, texts, queries
    hard_gc()
    _timer("ИТОГО на карусель", t_carousel)
    return folder


def _topic_slug(topic: str, *, max_len: int = 32) -> str:
    """Короткий безопасный хвост для имени папки carousel_001_slug."""
    import re

    raw = (topic or "").strip().lower()
    slug = re.sub(r"[^\w]+", "_", raw, flags=re.UNICODE)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug:
        slug = "topic"
    # Windows/mac/linux ok с unicode в имени папки
    return slug[:max_len].rstrip("_") or "topic"


def _require_liveness_model() -> None:
    """Без модели живости пачку не собираем: иначе каждый кадр получил бы
    почти случайную оценку и в карусели пошёл бы сток."""
    if not ugc_filter.MODEL_ONLY:
        return
    from core.ugc_classifier import get_ugc_live_classifier

    try:
        ok = get_ugc_live_classifier().is_trained
    except Exception as exc:
        raise LivenessModelError(f"модель живости не загрузилась: {exc}") from exc
    if not ok:
        raise LivenessModelError("модель живости не загружена (data/ugc_live_model.pkl)")


def run_batch(
    *,
    topic: str = "",
    product: str = "",
    count: int = 1,
    out_root: Path,
    llm: OllamaGenerator | None = None,
    harvester: PinterestHarvester | None = None,
    on_status: ProgressCb | None = None,
    on_carousel_done: CarouselDoneCb | None = None,
    should_stop: Callable[[], bool] | None = None,
    topics: list[str] | None = None,
) -> BatchResult:
    """
    Одна тема + count вариаций, ИЛИ список topics (по 1 карусели на тему).
    """
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    def _safe_status(msg: str) -> None:
        if not on_status:
            return
        text = str(msg or "")
        try:
            on_status(text)
        except UnicodeEncodeError:
            on_status(text.encode("ascii", "replace").decode("ascii"))

    _require_liveness_model()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = out_root / f"run_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "rejected").mkdir(exist_ok=True)

    llm = llm or OllamaGenerator()
    harvester = harvester or PinterestHarvester(on_status=_safe_status)
    result = BatchResult(run_dir=run_dir)
    # Одно фото — одна карусель на всю серию: всё, что уже стоит в каруселях
    try:
        from core.photo_vault import get_photo_vault

        used_index = get_photo_vault().used_index()
        print(
            f"[series] занято фото: {len(used_index.pins)} pin, "
            f"{len(used_index.fps)} отпечатков"
        )
    except Exception as exc:
        print(f"[series] учёт фото недоступен: {exc}")
        used_index = UsedIndex()
    # Run-level dedupe pin_id across all carousels in this batch
    used_pins_run: set[str] = set()
    used_character_dnas: list[dict[str, str]] = []
    from core.llm_engine import new_batch_memory

    batch_memory = new_batch_memory()
    harvester.reset_used()
    # Банк филлеров на весь батч (фидбек 2026-10-02)
    filler_bank = FillerBank()

    topic_list = [t.strip() for t in (topics or []) if t and str(t).strip()]
    multi = len(topic_list) > 1
    if not topic_list:
        if not (topic or "").strip():
            raise ValueError("Пустая тема для batch")
        topic_list = [topic.strip()]
        multi = False

    total = len(topic_list) if multi else max(1, int(count))

    # Категория пачки: по большинству тем (multi) или по самой теме
    from core.niches import detect_niche, dominant_category

    if multi:
        category = dominant_category(topic_list)
    else:
        category = detect_niche(topic_list[0], default="") or None
    if category:
        print(f"[category] категория пачки: {category}")
    skipped_path = run_dir / "skipped_topics.txt"

    from core.usage_meter import get_meter

    meter = get_meter()
    mode_label = f"multi-topic x{total}" if multi else f"batch x{total}"
    meter.reset_session(label=mode_label)

    t0 = time.perf_counter()
    failed_queue: list[tuple[int, str, str]] = []  # (index, topic, folder_name)
    for i in range(1, total + 1):
        if should_stop and should_stop():
            break
        if multi:
            cur_topic = topic_list[i - 1]
            variation_index = 0
            slug = _topic_slug(cur_topic)
            folder_name = f"carousel_{i:03d}_{slug}"
            progress_msg = (
                f"Сборка темы {i} / {total}: «{cur_topic[:60]}» | "
                f"Собрано каруселей: {result.made}"
            )
        else:
            cur_topic = topic_list[0]
            variation_index = i - 1
            folder_name = f"carousel_{i:03d}"
            elapsed = time.perf_counter() - t0
            avg = elapsed / max(1, result.made) if result.made else 0
            eta = avg * (total - i + 1) if avg > 0 else 0
            snap = meter.snapshot()
            progress_msg = (
                f"Собрано: {result.made} / {total} · "
                f"сейчас #{i} · ETA ~{int(eta // 60)}м {int(eta % 60)}с · "
                f"{snap.line()}"
            )

        if on_status:
            _safe_status(progress_msg)
        try:
            try:
                folder = build_one_carousel(
                    llm=llm,
                    harvester=harvester,
                    topic=cur_topic,
                    product=product,
                    out_dir=run_dir,
                    index=i,
                    variation_index=variation_index,
                    on_status=_safe_status,
                    folder_name=folder_name,
                    used_pins_run=used_pins_run,
                    avoid_character_dnas=list(used_character_dnas),
                    batch_index=i - 1,
                    batch_memory=batch_memory,
                    used_index=used_index,
                    category=category,
                    filler_bank=filler_bank,
                )
            except OffCategoryError as off:
                if multi:
                    raise
                # Одна тема + вариации: ещё один угол, потом пропуск
                print(f"[category] #{i}: {off} — пробую другой угол")
                folder = build_one_carousel(
                    llm=llm,
                    harvester=harvester,
                    topic=cur_topic,
                    product=product,
                    out_dir=run_dir,
                    index=i,
                    variation_index=variation_index + total,
                    on_status=_safe_status,
                    folder_name=folder_name,
                    used_pins_run=used_pins_run,
                    avoid_character_dnas=list(used_character_dnas),
                    batch_index=i - 1,
                    batch_memory=batch_memory,
                    used_index=used_index,
                    category=category,
                    filler_bank=filler_bank,
                )
            # Track DNA so the next carousel picks a different look
            try:
                meta_path = folder / "meta.json"
                if meta_path.is_file():
                    import json as _json

                    meta = _json.loads(meta_path.read_text(encoding="utf-8"))
                    dna = meta.get("character_dna")
                    if isinstance(dna, dict):
                        used_character_dnas.append(dna)
            except Exception:
                pass
            result.made += 1
            result.folders.append(folder)
            # Clear FAILED marker if retrying
            fail_marker = run_dir / f"{folder_name}_FAILED.txt"
            if fail_marker.exists():
                try:
                    fail_marker.unlink()
                except Exception:
                    pass
            if on_carousel_done:
                on_carousel_done(i, total, folder)
            snap = meter.snapshot()
            if on_status:
                if multi:
                    _safe_status(
                        f"Сборка темы {i} / {total}: «{cur_topic[:48]}» | "
                        f"Собрано каруселей: {result.made} · {snap.line()}"
                    )
                else:
                    _safe_status(f"[{i}] OK · {snap.line()}")
        except LivenessModelError:
            raise
        except OffCategoryError as off:
            result.skipped += 1
            msg = f"Пропущена тема #{i} (не про {category}): «{cur_topic[:70]}»"
            print(f"[category] {msg} · {off}")
            if on_status:
                _safe_status(msg)
            with skipped_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{i}\t{category}\t{cur_topic}\n")
        except Exception as exc:
            # Queue for end-of-batch retry; wipe partials
            result.failed += 1
            warn = (
                f"[BATCH WARNING] Пропуск темы '{cur_topic}' "
                f"из-за отсутствия фото."
            )
            exc_s = str(exc)
            if (
                "фото" not in exc_s.lower()
                and "pinterest" not in exc_s.lower()
                and "photo" not in exc_s.lower()
                and "No photos" not in exc_s
            ):
                warn = (
                    f"[BATCH WARNING] Пропуск темы '{cur_topic}' "
                    f"из-за ошибки сборки."
                )
            print(warn)
            print(f"[BATCH WARNING] detail: {exc_s}")
            if on_status:
                _safe_status(f"{warn} · {exc_s[:120]}")
            partial = run_dir / folder_name
            if partial.is_dir():
                for stale in partial.glob("*.jpg"):
                    try:
                        stale.unlink()
                    except Exception:
                        pass
                meta_p = partial / "meta.json"
                if meta_p.exists():
                    try:
                        meta_p.unlink()
                    except Exception:
                        pass
            err = run_dir / f"{folder_name}_FAILED.txt"
            err.write_text(
                (
                    f"topic: {cur_topic}\n"
                    f"index: {i}\n"
                    f"folder: {folder_name}\n"
                    f"reason: {exc_s}\n"
                    f"skipped: true\n"
                    f"continued_batch: true\n"
                    f"partial_wiped: true\n"
                    f"will_retry: true\n"
                ),
                encoding="utf-8",
            )
            failed_queue.append((i, cur_topic, folder_name))
        hard_gc()

    # ---- End-of-batch retry for fails (nuclear completion more aggressive) ----
    if failed_queue and not (should_stop and should_stop()):
        if on_status:
            _safe_status(
                f"Retry fail-тем: {len(failed_queue)} "
                f"(nuclear fill, soft dedupe)…"
            )
        # Soften dedupe for retry — pins already burned for similar food topics
        retry_used = set(used_pins_run)
        still_failed: list[tuple[int, str, str]] = []
        recovered = 0
        for i, cur_topic, folder_name in failed_queue:
            if should_stop and should_stop():
                still_failed.append((i, cur_topic, folder_name))
                continue
            try:
                print(f"[RETRY] topic #{i}: {cur_topic[:60]}")
                folder = build_one_carousel(
                    llm=llm,
                    harvester=harvester,
                    topic=cur_topic,
                    product=product,
                    out_dir=run_dir,
                    index=i,
                    variation_index=0,
                    on_status=_safe_status,
                    folder_name=folder_name,
                    used_pins_run=retry_used,
                    avoid_character_dnas=list(used_character_dnas),
                    batch_index=i - 1,
                    batch_memory=batch_memory,
                    used_index=used_index,
                    category=category,
                    filler_bank=filler_bank,
                )
                result.made += 1
                result.failed = max(0, result.failed - 1)
                result.folders.append(folder)
                recovered += 1
                fail_marker = run_dir / f"{folder_name}_FAILED.txt"
                if fail_marker.exists():
                    try:
                        fail_marker.unlink()
                    except Exception:
                        pass
                if on_carousel_done:
                    on_carousel_done(i, total, folder)
                if on_status:
                    _safe_status(
                        f"Retry OK #{i} · собрано {result.made}/{total}"
                    )
            except Exception as exc:
                print(f"[RETRY] still fail #{i}: {exc}")
                still_failed.append((i, cur_topic, folder_name))
                err = run_dir / f"{folder_name}_FAILED.txt"
                err.write_text(
                    (
                        f"topic: {cur_topic}\n"
                        f"index: {i}\n"
                        f"folder: {folder_name}\n"
                        f"reason: {exc}\n"
                        f"skipped: true\n"
                        f"retried: true\n"
                        f"partial_wiped: true\n"
                    ),
                    encoding="utf-8",
                )
            hard_gc()
        if on_status:
            _safe_status(
                f"Retry done: recovered {recovered}, "
                f"still fail {len(still_failed)}"
            )

    print(f"[filler-bank] {filler_bank.stats()}")
    usage = meter.summary_dict()
    summary_path = meter.write_summary(run_dir / "usage_summary.json")
    manifest = {
        "mode": "multi_topic" if multi else "single_topic_variations",
        "topic": topic_list[0] if not multi else None,
        "topics": topic_list if multi else None,
        "product": product,
        "requested": total,
        "made": result.made,
        "failed": result.failed,
        "skipped_off_category": result.skipped,
        "category": category,
        "run_dir": str(run_dir),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "usage": usage,
        "usage_summary_file": str(summary_path),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if on_status:
        _safe_status(
            f"Batch done: {result.made}/{total} · fail {result.failed} · "
            + (f"не по теме {result.skipped} · " if result.skipped else "")
            + f"{meter.snapshot().line()} · log {summary_path.name}"
        )
    hard_gc()
    return result
