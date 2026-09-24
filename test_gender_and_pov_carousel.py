#!/usr/bin/env python3
"""
Наглядный тест Gender Lock + No Faces in Body.

Прогон: Gemini -> Pinterest harvest (gender/POV gates) -> render -> полоска 1×6.

Запуск из корня репо:
  python test_gender_and_pov_carousel.py

Артефакт:
  out/test_collages/strip_1x6_check.jpg
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from core.harvester import (  # noqa: E402
    CANDIDATES_PER_SLIDE,
    PinterestHarvester,
    finalize_photo_query,
    gender_cosine_pair,
    infer_carousel_gender,
    looks_like_frontal_face,
)
from core.llm_engine import OllamaGenerator  # noqa: E402
from core.renderer import render_slide  # noqa: E402

TOPIC = "Why being the 'easygoing girl' in relationships always backfires"
TARGET_SLIDES = 6
THUMB_W, THUMB_H = 360, 480
GAP = 8
LABEL_H = 40
OUT_DIR = ROOT / "out" / "test_collages"
STRIP_PATH = OUT_DIR / "strip_1x6_check.jpg"
SLIDES_DIR = OUT_DIR / "slides"


def _status(msg: str) -> None:
    print(f"  · {msg}", flush=True)


def _label_font(size: int = 18) -> ImageFont.ImageFont:
    candidates = [
        ROOT / "fonts" / "TikTokSans-SemiBold.ttf",
        ROOT / "fonts" / "TikTokSans-Bold.ttf",
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                continue
    return ImageFont.load_default()


def _build_strip(rendered: list[Image.Image], labels: list[str]) -> Image.Image:
    n = len(rendered)
    canvas_w = n * THUMB_W + max(0, n - 1) * GAP
    canvas_h = LABEL_H + THUMB_H
    # чуть шире/выше под спеку ~2200×520 при 6 слайдах
    canvas = Image.new("RGB", (canvas_w, canvas_h), (22, 22, 28))
    draw = ImageDraw.Draw(canvas)
    font = _label_font(17)
    for i, (img, label) in enumerate(zip(rendered, labels)):
        x = i * (THUMB_W + GAP)
        thumb = img.convert("RGB").resize(
            (THUMB_W, THUMB_H), Image.Resampling.LANCZOS
        )
        canvas.paste(thumb, (x, LABEL_H))
        # label centered over thumb
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        tx = x + max(0, (THUMB_W - tw) // 2)
        ty = max(4, (LABEL_H - (bbox[3] - bbox[1])) // 2)
        draw.text((tx, ty), label, font=font, fill=(230, 230, 235))
        if i < n - 1:
            sep_x = x + THUMB_W
            draw.rectangle(
                [sep_x, LABEL_H, sep_x + GAP - 1, canvas_h - 1],
                fill=(40, 40, 48),
            )
    return canvas


def main() -> int:
    t0 = time.perf_counter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SLIDES_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("  Gender Lock + POV Body — strip 1x6 check")
    print("=" * 64)
    print(f"Topic: {TOPIC}")
    print()

    # --- 1) LLM ---
    print("[1/3] Gemini · generate_carousel…")
    try:
        llm = OllamaGenerator()
        result = llm.generate_carousel(TOPIC, product_name="", variation_index=0)
    except Exception as exc:
        print(f"FAIL Gemini: {exc}")
        traceback.print_exc()
        return 1

    slides_raw = list(result.get("slides") or [])
    if len(slides_raw) < 5:
        print(f"FAIL: too few slides from LLM ({len(slides_raw)})")
        return 1

    # Ровно 6: обрезаем или (редко) берём все если меньше 6
    slides_raw = slides_raw[:TARGET_SLIDES]
    texts = [str(s.get("text") or "").strip() for s in slides_raw]
    queries = [str(s.get("search_query") or "").strip() for s in slides_raw]
    scenes = [str(s.get("visual_scene") or "").strip() for s in slides_raw]
    roles = [str(s.get("role") or "").strip() for s in slides_raw]

    print(f"  slides from LLM: {len(slides_raw)}")
    dna = result.get("character_dna") or {}
    if dna:
        print(
            f"  character_dna: gender={dna.get('gender')} "
            f"hair={dna.get('hair')!r} style={dna.get('style')!r}"
        )
    for i, (text, scene, q, role) in enumerate(
        zip(texts, scenes, queries, roles), start=1
    ):
        tag = "HOOK" if i == 1 else ("CTA" if i == len(texts) else "BODY")
        print(f"  [{i}|{role or tag}] q={q!r}")
        print(f"       scene={scene[:90]!r}")
        print(f"       text={text[:80]!r}")

    specs: list[tuple[str, str, int, str]] = []
    for i, text in enumerate(texts):
        q = queries[i] if i < len(queries) and queries[i] else text
        query = finalize_photo_query(q, i, slide_text=text)
        scene = scenes[i] if i < len(scenes) else ""
        specs.append((query, text, i, scene))

    # --- 2) Harvest (Gender Lock + No Faces) ---
    print()
    print("[2/3] Pinterest harvest_slides_parallel (gender + attribute lock)…")
    harvester = PinterestHarvester(on_status=_status)
    try:
        harvester.warm_session(force=False)
        harvested = harvester.harvest_slides_parallel(
            specs,
            limit=max(CANDIDATES_PER_SLIDE, 8),
            min_keep=1,
            topic=TOPIC,
            max_workers=4,
            character_dna=dna if isinstance(dna, dict) else None,
        )
    except Exception as exc:
        print(f"FAIL harvest: {exc}")
        traceback.print_exc()
        return 1
    finally:
        harvester.close()

    selected_imgs: list[Image.Image] = []
    selected_meta: list[dict] = []
    for i, ((q, text, idx, scene), (cands, prog, used_q)) in enumerate(
        zip(specs, harvested)
    ):
        if not cands:
            print(f"FAIL: empty pool on slide {i + 1} (stage={prog.stage})")
            return 1
        winner = cands[0]
        selected_imgs.append(winner.image.copy())
        selected_meta.append(
            {
                "index": i + 1,
                "query": used_q or q,
                "scene": scene,
                "text": text,
                "pin_id": winner.pin_id,
                "title": winner.title,
                "taste": float(getattr(winner, "taste_score", 0) or 0),
                "ugc": float(getattr(winner, "ugc_score", 0) or 0),
                "rel": float(getattr(winner, "text_relevance", 0) or 0),
            }
        )
        print(
            f"  slide {i + 1}: pin={winner.pin_id} "
            f"taste={winner.taste_score:.0%} ugc={winner.ugc_score:.0%} "
            f"rel={winner.text_relevance:.0%} · {used_q or q!r}"
        )

    # Gender lock report from slide 1 photo
    carousel_gender = infer_carousel_gender(selected_imgs[0])
    try:
        sim_f, sim_m = gender_cosine_pair(selected_imgs[0])
    except Exception:
        sim_f, sim_m = 0.0, 0.0

    face_hits = 0
    pov_ok = 0
    for i, img in enumerate(selected_imgs):
        if i == 0:
            continue
        is_face = looks_like_frontal_face(img, selected_meta[i].get("title", ""))
        if is_face:
            face_hits += 1
            print(f"  [WARN] slide {i + 1}: frontal face still detected")
        else:
            pov_ok += 1

    # --- 3) Render ---
    print()
    print("[3/3] Render slides + build 1x6 strip…")
    rendered: list[Image.Image] = []
    labels: list[str] = []
    for i, (img, meta) in enumerate(zip(selected_imgs, selected_meta)):
        out, _rmeta = render_slide(img, meta["text"])
        out_path = SLIDES_DIR / f"slide_{i + 1:02d}.jpg"
        out.convert("RGB").save(out_path, quality=92, optimize=True)
        rendered.append(out.convert("RGB"))
        if i == 0:
            labels.append("Слайд 1 (Герой)")
        else:
            labels.append(f"Слайд {i + 1} (POV)")
        print(f"  rendered {out_path.name}")

    # pad to 6 if LLM returned fewer (shouldn't after truncate)
    while len(rendered) < TARGET_SLIDES:
        blank = Image.new("RGB", (1080, 1440), (30, 30, 36))
        rendered.append(blank)
        labels.append(f"Слайд {len(rendered)} (empty)")

    strip = _build_strip(rendered[:TARGET_SLIDES], labels[:TARGET_SLIDES])
    strip.save(STRIP_PATH, quality=95, optimize=True)

    elapsed = time.perf_counter() - t0
    body_n = max(0, len(selected_imgs) - 1)

    print()
    print("=" * 64)
    print("  ОТЧЁТ ПРОВЕРКИ")
    print("=" * 64)
    print(f"  Зафиксированный пол героя на Слайде 1: {carousel_gender}")
    print(f"    sim_female={sim_f:.3f}  sim_male={sim_m:.3f}")
    print(
        f"  Проверка слайдов 2–{len(selected_imgs)}: "
        f"чужих лиц анфас = {face_hits} шт "
        f"(POV OK = {pov_ok}/{body_n})"
    )
    print(f"  Полоска 1x6: {STRIP_PATH.resolve()}")
    print(f"  Размер: {strip.size[0]}×{strip.size[1]} px · {elapsed:.1f} с")
    print("=" * 64)

    if face_hits > 0:
        print("  RESULT: WARN — на body всё ещё есть лица (см. выше)")
        return 2
    print("  RESULT: OK — gender lock + POV body выглядят консистентно")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
