#!/usr/bin/env python3
"""
Визуальная проверка single-pass отбора фото: 5 запросов → топ-10 → коллажи.

Запуск из корня репо:
  python test_query_collages.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.harvester import (  # noqa: E402
    CandidateImage,
    PinterestHarvester,
    SELECT_RELEVANCE_MIN,
    TASTE_HARD_FLOOR,
    UGC_HARD_FLOOR,
    apply_pov_fashion_ugc_penalty,
    candidate_final_score,
    is_junk_candidate_image,
)

OUT_DIR = ROOT / "out" / "test_collages"
THUMB_W = 300
THUMB_H = 400
COLS = 5
ROWS = 2
TOP_N = 10
FETCH_LIMIT = 28  # сырой пул до скоринга
# Санитарные пороги: мягкие, без пустых слайдов
COLLAGE_UGC_MIN = UGC_HARD_FLOOR  # 0.38
COLLAGE_TASTE_MIN = TASTE_HARD_FLOOR  # 0.35
COLLAGE_REL_MIN = SELECT_RELEVANCE_MIN  # 0.12
COLLAGE_FINAL_MIN = 0.40
HEADER_H = 56
LABEL_H = 44
PAD = 8
BG = (18, 18, 20)
HEADER_BG = (28, 28, 32)
LABEL_BG = (0, 0, 0, 180)
TEXT = (245, 245, 245)
MUTED = (180, 180, 186)

# (index, slug, query, short title for console)
QUERIES: list[tuple[int, str, str, str]] = [
    (
        1,
        "fridge",
        "kitchen fridge open warm evening lamp iphone",
        "Теплый вечерний перекус",
    ),
    (
        2,
        "tea",
        "tea mug table warm evening lamp iphone",
        "Вечерний чай/стол",
    ),
    (
        3,
        "journal",
        "open journal table warm evening lamp iphone",
        "Вечерний блокнот",
    ),
    (
        4,
        "coffee",
        "coffee mug window morning sunlight iphone",
        "Утренний кофе у окна",
    ),
    (
        5,
        "street",
        "holding coffee walking city street pov candid iphone",
        "Уличный POV с кофе",
    ),
]


def _font(size: int) -> ImageFont.ImageFont:
    for name in (
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_cover(img: Image.Image, tw: int, th: int) -> Image.Image:
    """Center-crop cover в tw×th."""
    src = img.convert("RGB")
    sw, sh = src.size
    if sw <= 0 or sh <= 0:
        return Image.new("RGB", (tw, th), (40, 40, 40))
    scale = max(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - tw) // 2)
    top = max(0, (nh - th) // 2)
    return resized.crop((left, top, left + tw, top + th))


def score_pool_single_pass(
    harvester: PinterestHarvester,
    candidates: list[CandidateImage],
    *,
    query: str,
) -> list[CandidateImage]:
    """
    Junk → scores → POV fashion-penalty → санитария
    (ugc≥0.38, taste≥0.35, rel≥0.12, final≥0.40) → топ по final.
    """
    pre: list[CandidateImage] = []
    junk_n = 0
    for c in candidates:
        if is_junk_candidate_image(c.image, c.title):
            junk_n += 1
            continue
        pre.append(c)
    print(f"    junk dropped: {junk_n}, scoring: {len(pre)}")
    if not pre:
        return []

    pre = harvester._apply_text_relevance_gate(pre, query, query=query)
    pre = harvester._apply_ugc_gate(pre)
    pre = harvester._apply_taste_gate(pre)
    pov_n = apply_pov_fashion_ugc_penalty(pre, query)
    if pov_n:
        print(f"    POV fashion-penalty −25% UGC ×{pov_n}")
    harvester._score_harmony(pre, None)

    for cand in pre:
        taste_v = (
            float(cand.taste_score) if getattr(cand, "taste_scored", False) else None
        )
        cand.combined_score = candidate_final_score(
            float(getattr(cand, "text_relevance", 0.5) or 0.5),
            float(getattr(cand, "ugc_score", 0.5) or 0.5),
            float(getattr(cand, "harmony_score", 100.0) or 100.0),
            taste=taste_v,
        )
        cand.relevance_reason = "single_pass_collage"
        cand.selection_mode = "single_pass_argmax"

    kept = [
        c
        for c in pre
        if float(c.ugc_score) >= COLLAGE_UGC_MIN
        and float(c.taste_score) >= COLLAGE_TASTE_MIN
        and float(c.text_relevance) >= COLLAGE_REL_MIN
        and float(c.combined_score) >= COLLAGE_FINAL_MIN
    ]
    dropped = len(pre) - len(kept)
    print(
        f"    sanitary: kept {len(kept)} / {len(pre)} "
        f"(ugc≥{COLLAGE_UGC_MIN:.0%}, taste≥{COLLAGE_TASTE_MIN:.0%}, "
        f"rel≥{COLLAGE_REL_MIN:.0%}, final≥{COLLAGE_FINAL_MIN:.0%}, "
        f"dropped {dropped})"
    )
    kept.sort(key=lambda c: c.combined_score, reverse=True)
    top = kept[:TOP_N]
    if len(top) < TOP_N:
        print(
            f"    collage slots: {len(top)}/{TOP_N} — "
            f"остальные empty (кандидатов физически меньше)"
        )
    return top


def build_collage(
    candidates: list[CandidateImage],
    *,
    query: str,
    title: str,
    out_path: Path,
) -> Path:
    font_title = _font(18)
    font_label = _font(12)
    font_empty = _font(14)

    grid_w = COLS * THUMB_W + (COLS + 1) * PAD
    grid_h = ROWS * (THUMB_H + LABEL_H) + (ROWS + 1) * PAD
    canvas_w = grid_w
    canvas_h = HEADER_H + grid_h

    canvas = Image.new("RGB", (canvas_w, canvas_h), BG)
    draw = ImageDraw.Draw(canvas)

    # header
    draw.rectangle((0, 0, canvas_w, HEADER_H), fill=HEADER_BG)
    header = f"{title}  ·  {query}"
    draw.text((PAD + 4, 16), header, fill=TEXT, font=font_title)

    slots = list(candidates[:TOP_N])
    while len(slots) < TOP_N:
        slots.append(None)  # type: ignore[arg-type]

    for i, cand in enumerate(slots):
        row, col = divmod(i, COLS)
        x0 = PAD + col * (THUMB_W + PAD)
        y0 = HEADER_H + PAD + row * (THUMB_H + LABEL_H + PAD)

        cell = Image.new("RGB", (THUMB_W, THUMB_H + LABEL_H), (32, 32, 36))
        if cand is None:
            d = ImageDraw.Draw(cell)
            d.text(
                (THUMB_W // 2 - 40, THUMB_H // 2),
                "(empty)",
                fill=MUTED,
                font=font_empty,
            )
        else:
            thumb = _fit_cover(cand.image, THUMB_W, THUMB_H)
            cell.paste(thumb, (0, 0))
            # metric bar
            bar = Image.new("RGBA", (THUMB_W, LABEL_H), LABEL_BG)
            bd = ImageDraw.Draw(bar)
            ugc = float(getattr(cand, "ugc_score", 0.0) or 0.0)
            taste = float(getattr(cand, "taste_score", 0.0) or 0.0)
            rel = float(getattr(cand, "text_relevance", 0.0) or 0.0)
            final = float(getattr(cand, "combined_score", 0.0) or 0.0)
            line1 = f"UGC: {ugc:.0%} | Taste: {taste:.0%}"
            line2 = f"Rel: {rel:.0%} | Final: {final:.0%}"
            bd.text((6, 4), line1, fill=TEXT, font=font_label)
            bd.text((6, 22), line2, fill=MUTED, font=font_label)
            cell.paste(bar.convert("RGB"), (0, THUMB_H))

        canvas.paste(cell, (x0, y0))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, quality=92, optimize=True)
    return out_path


def run_one(
    harvester: PinterestHarvester,
    *,
    index: int,
    slug: str,
    query: str,
    title: str,
) -> Path | None:
    print(f"\n=== [{index}] {title} ===")
    print(f"    query: {query}")
    t0 = time.perf_counter()

    harvester.reset_used()
    raw, prog = harvester.harvest_for_query(
        query,
        limit=FETCH_LIMIT,
        slide_text=query,
        apply_score=False,
        allow_broaden=False,
    )
    print(
        f"    downloaded: {len(raw)} "
        f"(stage={prog.stage}, pins_found≈{prog.found}, "
        f"net={prog.elapsed_sec:.1f}s)"
    )

    ranked = score_pool_single_pass(harvester, raw, query=query)
    top = ranked[:TOP_N]
    print(f"    top-{TOP_N}: {len(top)} / scored {len(ranked)}")
    for i, c in enumerate(top, 1):
        print(
            f"      #{i:02d} pin={c.pin_id} "
            f"final={c.combined_score:.0%} "
            f"ugc={c.ugc_score:.0%} taste={c.taste_score:.0%} "
            f"rel={c.text_relevance:.0%}"
        )

    out_path = OUT_DIR / f"collage_{index}_{slug}.jpg"
    build_collage(top, query=query, title=f"#{index} {title}", out_path=out_path)

    # освободить RAM
    for c in raw:
        try:
            c.image.close()
        except Exception:
            pass

    dt = time.perf_counter() - t0
    print(f"    time: {dt:.1f}s")
    print(f"    file: {out_path.resolve()}")
    return out_path


def main() -> int:
    print("test_query_collages · single-pass visual check")
    print(f"out → {OUT_DIR.resolve()}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    def status(msg: str) -> None:
        print(f"    [harvester] {msg}")

    harvester = PinterestHarvester(on_status=status)
    try:
        print("warming Pinterest session…")
        harvester.warm()
    except Exception as exc:
        print(f"[WARNING] warm failed: {exc}")

    # SigLIP warm (не обязателен, но быстрее первый скор)
    try:
        from core.taste_embedder import get_embedder

        emb = get_embedder()
        emb.ensure()
        print(f"SigLIP ready ({emb.device})")
    except Exception as exc:
        print(f"[WARNING] SigLIP warm: {exc}")

    results: list[tuple[str, Path | None, float]] = []
    t_all = time.perf_counter()
    for index, slug, query, title in QUERIES:
        t0 = time.perf_counter()
        try:
            path = run_one(
                harvester,
                index=index,
                slug=slug,
                query=query,
                title=title,
            )
        except Exception as exc:
            print(f"    FAIL: {exc}")
            path = None
        results.append((query, path, time.perf_counter() - t0))

    print("\n" + "=" * 64)
    print("SUMMARY")
    for query, path, dt in results:
        if path and path.exists():
            print(f"  OK  {dt:5.1f}s  {path.resolve()}")
        else:
            print(f"  FAIL {dt:5.1f}s  {query!r}")
    print(f"total: {time.perf_counter() - t_all:.1f}s")
    harvester.close()
    return 0 if all(p and p.exists() for _, p, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
