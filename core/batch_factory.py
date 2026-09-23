#!/usr/bin/env python3
"""
Пакетная сборка каруселей: Gemini → Pinterest → Color Matcher → render → disk.

Строго последовательно, gc.collect() после каждой карусели (8 ГБ RAM/VRAM).
"""

from __future__ import annotations

import gc
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from core.caption_engine import generate_caption
from core.color_matcher import get_color_profile, get_harmony_score
from core.harvester import (
    CandidateImage,
    PinterestHarvester,
    finalize_photo_query,
    weighted_promote_top3,
)
from core.llm_engine import OllamaGenerator
from core.renderer import render_slide
from core.visual_judge import combined_rank_score

ProgressCb = Callable[[str], None]
CarouselDoneCb = Callable[[int, int, Path], None]  # idx, total, folder

CANDIDATES = 10
MIN_KEEP = 3
MAX_ALTS_SAVED = 6


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


def _apply_combined_ranking(slide: BatchSlide) -> None:
    if not slide.candidates:
        return
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
        combined = combined_rank_score(
            ugc, taste=taste, harmony=harm, relevance=rel
        )
        cand.combined_score = combined
        scored.append((combined, i))
    scored.sort(key=lambda x: x[0], reverse=True)
    order = [i for _, i in scored]
    _reorder_batch_slide(slide, order, list(slide.harmony_scores))
    # Weighted top-3 после harmony — иначе argmax снова убивает sample из judge
    if slide.candidates:
        prior = getattr(slide.candidates[0], "selection_mode", "") or ""
        if prior in ("emergency_guarded", "single_pass_argmax"):
            # Уже выбран single-pass / emergency — не ломать argmax resample'ом
            slide.selected = 0
        else:
            mode = "hard_top3_sample"
            slide.candidates = weighted_promote_top3(slide.candidates, mode=mode)
            slide.selected = 0


def apply_color_harmony(slides: list[BatchSlide]) -> None:
    """Якорь = слайд 1; ранг = rel×0.35 + taste×0.35 + ugc×0.20 + harm×0.10."""
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
    _apply_combined_ranking(anchor_slide)

    anchor = anchor_slide.color_profiles[anchor_slide.selected]
    for s in slides[1:]:
        if not s.candidates:
            s.harmony_scores = []
            continue
        scores_orig = [get_harmony_score(anchor, p) for p in s.color_profiles]
        s.harmony_scores = scores_orig
        for c, h in zip(s.candidates, scores_orig):
            c.harmony_score = float(h)
        _apply_combined_ranking(s)


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

    status(f"[{index}] Gemini · unique angle #{variation_index + 1}…")
    t1 = time.perf_counter()
    result = llm.generate_carousel(
        topic,
        product_name=product,
        variation_index=variation_index,
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
    if len(texts) < 5:
        raise RuntimeError(f"Too few slides from LLM: {len(texts)}")

    texts = texts[:9]
    queries = queries[: len(texts)]
    scenes = (scenes + [""] * len(texts))[: len(texts)]

    # Run-level HARD BAN: финалы прошлых каруселей. Soft-reuse запрещён.
    harvester.reset_used()
    if used_pins_run:
        harvester.seed_used(used_pins_run)
    specs: list[tuple[str, str, int, str]] = []
    for i, text in enumerate(texts):
        q = queries[i] if i < len(queries) and queries[i] else text
        query = finalize_photo_query(q, i + variation_index, slide_text=text)
        scene = scenes[i] if i < len(scenes) else ""
        specs.append((query, text, i, scene))

    status(f"[{index}] Pinterest parallel · {len(specs)} слайдов…")
    # Быстрый preflight: если Pinterest недоступен — сразу понятная ошибка
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

    harvester.reset_timing()
    harvested = harvester.harvest_slides_parallel(
        specs,
        limit=CANDIDATES,
        min_keep=max(1, MIN_KEEP),
        topic=topic,
        max_attempts=1,
        max_workers=2,
    )
    print(
        f"[TIMER] 2. Поиск и фильтрация в Pinterest (все слайды): "
        f"{float(harvester.timing_pinterest_sec):.1f} с"
    )
    print(
        f"[TIMER] 3. Расчет SigLIP (UGC + Relevance + Taste): "
        f"{float(harvester.timing_siglip_sec):.1f} с"
    )

    batch_slides: list[BatchSlide] = []
    for (query, text, _idx, _scene), (cands, _prog, used_q) in zip(
        specs, harvested
    ):
        batch_slides.append(
            BatchSlide(
                text=text,
                query=used_q or query,
                candidates=cands[:CANDIDATES],
                selected=0,
            )
        )
    status(f"[{index}] Color Matcher + локальный вкус…")
    apply_color_harmony(batch_slides)

    folder = out_dir / (folder_name or f"carousel_{index:03d}")
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
        "quality": result.get("quality"),
        "few_shot_source": result.get("few_shot_source"),
        "slides": [],
    }

    status(f"[{index}] Render + Negative Space…")
    t4 = time.perf_counter()
    selected_pins: list[str] = []
    for i, s in enumerate(batch_slides):
        if not s.candidates:
            # Гарантия: last-resort search вместо падения всей карусели
            status(f"[{index}] Слайд {i + 1}: пусто — guarantee fill…")
            g_kept, g_q = harvester.guarantee_at_least_one(
                slide_text=s.text,
                slide_index=i,
                preferred_query=s.query,
                limit=max(1, MIN_KEEP),
                topic=topic,
            )
            if g_kept:
                s.candidates = g_kept
                if g_q:
                    s.query = g_q
                print(
                    f"[GUARANTEE] batch slide {i + 1}: filled "
                    f"{len(g_kept)} via «{g_q}»"
                )
            else:
                raise RuntimeError(
                    f"No photos for slide {i + 1} "
                    f"(Pinterest недоступен даже на last-resort)"
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
        meta["slides"].append(
            {
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
        )
        del rendered
        hard_gc()

    _timer("4. Рендер картинок и Negative Space", t4)

    # Только pin_id реально пошедших на финальный JPEG (selected=0).
    # Отвергнутые alts / сырой пул в used_pins_run НЕ попадают.
    if used_pins_run is not None and selected_pins:
        used_pins_run.update(selected_pins)
        harvester.mark_used(selected_pins)
        print(
            f"[dedupe] финалы карусели → used_pins_run "
            f"+{len(selected_pins)} (всего {len(used_pins_run)})"
        )

    status(f"[{index}] Caption…")
    caption = generate_caption(texts, topic, product)
    (folder / "caption.txt").write_text(caption + "\n", encoding="utf-8")
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
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = out_root / f"run_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "rejected").mkdir(exist_ok=True)

    llm = llm or OllamaGenerator()
    harvester = harvester or PinterestHarvester(on_status=on_status)
    result = BatchResult(run_dir=run_dir)
    # Run-level dedupe pin_id across all carousels in this batch
    used_pins_run: set[str] = set()
    harvester.reset_used()

    topic_list = [t.strip() for t in (topics or []) if t and str(t).strip()]
    multi = len(topic_list) > 1
    if not topic_list:
        if not (topic or "").strip():
            raise ValueError("Пустая тема для batch")
        topic_list = [topic.strip()]
        multi = False

    total = len(topic_list) if multi else max(1, int(count))

    from core.usage_meter import get_meter

    meter = get_meter()
    mode_label = f"multi-topic x{total}" if multi else f"batch x{total}"
    meter.reset_session(label=mode_label)

    t0 = time.perf_counter()
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
            on_status(progress_msg)
        try:
            folder = build_one_carousel(
                llm=llm,
                harvester=harvester,
                topic=cur_topic,
                product=product,
                out_dir=run_dir,
                index=i,
                variation_index=variation_index,
                on_status=on_status,
                folder_name=folder_name,
                used_pins_run=used_pins_run,
            )
            result.made += 1
            result.folders.append(folder)
            if on_carousel_done:
                on_carousel_done(i, total, folder)
            snap = meter.snapshot()
            if on_status:
                if multi:
                    on_status(
                        f"Сборка темы {i} / {total}: «{cur_topic[:48]}» | "
                        f"Собрано каруселей: {result.made} · {snap.line()}"
                    )
                else:
                    on_status(f"[{i}] OK · {snap.line()}")
        except Exception as exc:
            result.failed += 1
            if on_status:
                on_status(f"[{i}] FAIL («{cur_topic[:40]}»): {exc}")
            err = run_dir / f"{folder_name}_FAILED.txt"
            err.write_text(
                f"topic: {cur_topic}\n{exc}", encoding="utf-8"
            )
        hard_gc()

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
        on_status(
            f"Batch done: {result.made}/{total} · fail {result.failed} · "
            f"{meter.snapshot().line()} · log {summary_path.name}"
        )
    hard_gc()
    return result
