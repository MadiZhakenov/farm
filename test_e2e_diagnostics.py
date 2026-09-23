#!/usr/bin/env python3
"""
E2E diagnostics: текст → search_query → Pinterest → SigLIP → HTML-отчёт.

Сквозная проверка смыслового подбора картинок на актуальном пайплайне.

Запуск из корня репо:
  python test_e2e_diagnostics.py              # 3 разнородные темы из пула
  python test_e2e_diagnostics.py --limit 5
  python test_e2e_diagnostics.py --all
  python test_e2e_diagnostics.py --indices 0,5,12

Отчёт: out/e2e_diagnostics/report.html
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from core.harvester import (  # noqa: E402
    CANDIDATES_PER_SLIDE,
    CandidateImage,
    PinterestHarvester,
    finalize_photo_query,
)
from core.llm_engine import OllamaGenerator  # noqa: E402

OUT_ROOT = ROOT / "out" / "e2e_diagnostics"
CANDIDATES = 10
ALTS_KEEP = 3

# ---------------------------------------------------------------------------
# Тестовый пул: 20 контрастных тем
# ---------------------------------------------------------------------------

TOPIC_POOL: tuple[str, ...] = (
    "Why you feel a wave of sadness right after achieving a major goal",
    "Signs you are not healed, you just got better at hiding your triggers",
    "How to stop over-analyzing subtle tone shifts in casual text messages",
    "The quiet grief of realizing your parents are just aging, flawed humans",
    "Why being the 'easygoing girl' in relationships always backfires",
    "The difference between taking a real mental health day and escaping reality",
    "How to stop impulsive spending when you are emotionally exhausted",
    "Signs your poor gut health is secretly causing your daily mood swings",
    "Why you sabotage good things the moment life starts feeling peaceful",
    "The 10-minute Sunday reset that prevents Monday morning dread",
    "How to unlearn the habit of apologizing before asking for basic respect",
    "Why your brain craves late-night sugar when you are actually touch-starved",
    "Signs someone is subtly competing with you disguised as a supportive friend",
    "How to detach from a situationship that is draining your life energy",
    "The brutal reason why resting on the couch makes you feel guilty",
    "How to rebuild self-trust after breaking promises to yourself for years",
    "Why walking into an empty apartment feels peaceful to some and terrifying to others",
    "Signs you are confusing emotional instability for genuine romantic chemistry",
    "How to stop living your entire life in preparation for a future that never arrives",
    "The silent relief of letting someone misunderstand you instead of fighting back",
)

# 3 разнородные по умолчанию: достижения/грусть · gut/health · situationship
DEFAULT_INDICES: tuple[int, ...] = (0, 7, 13)


@dataclass
class CandSnap:
    pin_id: str
    rel: float
    taste: float
    ugc: float
    final: float
    mode: str
    reason: str
    path: str  # relative to OUT_ROOT


@dataclass
class SlideSnap:
    index: int
    role: str
    text: str
    search_query: str
    visual_scene: str = ""
    winner: CandSnap | None = None
    alts: list[CandSnap] = field(default_factory=list)
    error: str = ""


@dataclass
class TopicSnap:
    topic_index: int  # 1-based in this run
    topic_total: int
    pool_index: int
    topic: str
    slides: list[SlideSnap] = field(default_factory=list)
    error: str = ""
    elapsed_sec: float = 0.0


def _slug(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return (s[:max_len] or "topic").rstrip("_")


def _save_jpg(img: Image.Image, path: Path, quality: int = 88) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(path, quality=quality, optimize=True)


def _cand_snap(cand: CandidateImage, rel_path: str) -> CandSnap:
    return CandSnap(
        pin_id=str(cand.pin_id or ""),
        rel=float(getattr(cand, "text_relevance", 0.0) or 0.0),
        taste=float(getattr(cand, "taste_score", 0.0) or 0.0),
        ugc=float(getattr(cand, "ugc_score", 0.0) or 0.0),
        final=float(getattr(cand, "combined_score", 0.0) or 0.0),
        mode=str(getattr(cand, "selection_mode", "") or ""),
        reason=str(getattr(cand, "relevance_reason", "") or ""),
        path=rel_path.replace("\\", "/"),
    )


def run_one_topic(
    *,
    topic: str,
    pool_index: int,
    topic_index: int,
    topic_total: int,
    generator: OllamaGenerator,
    harvester: PinterestHarvester,
    out_dir: Path,
    run_used_pins: set[str],
) -> TopicSnap:
    snap = TopicSnap(
        topic_index=topic_index,
        topic_total=topic_total,
        pool_index=pool_index,
        topic=topic,
    )
    t0 = time.perf_counter()
    topic_dir = out_dir / f"topic_{topic_index:02d}_{_slug(topic)}"
    topic_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = generator.generate_carousel(
            topic, product_name="", variation_index=0
        )
        slides_raw = result.get("slides") or []
        if not slides_raw:
            snap.error = "LLM returned 0 slides"
            snap.elapsed_sec = time.perf_counter() - t0
            return snap

        # HARD BAN на весь e2e-запуск: seed finals прошлых тем
        harvester.reset_used()
        if run_used_pins:
            harvester.seed_used(run_used_pins)

        specs: list[tuple[str, str, int, str]] = []
        for i, s in enumerate(slides_raw):
            text = str(s.get("text") or "").strip()
            role = str(s.get("role") or ("hook" if i == 0 else "body"))
            raw_q = str(s.get("search_query") or "").strip()
            scene = str(s.get("visual_scene") or "").strip()
            query = finalize_photo_query(raw_q or text, i, slide_text=text)
            specs.append((query, text, i, scene))
            snap.slides.append(
                SlideSnap(
                    index=i + 1,
                    role=role,
                    text=text,
                    search_query=query,
                    visual_scene=scene,
                )
            )

        harvested = harvester.harvest_slides_parallel(
            specs,
            limit=CANDIDATES,
            min_keep=1,
            topic=topic,
            max_attempts=1,
            max_workers=2,
        )

        for slide_snap, (_query, _text, _idx, _scene), (cands, _prog, used_q) in zip(
            snap.slides, specs, harvested
        ):
            if used_q:
                slide_snap.search_query = used_q
            slide_dir = topic_dir / f"slide_{slide_snap.index:02d}"
            slide_dir.mkdir(parents=True, exist_ok=True)

            if not cands:
                slide_snap.error = "no candidates"
                print(
                    f"[Тема {topic_index}/{topic_total}] Слайд {slide_snap.index}: "
                    f"'{slide_snap.search_query}' -> НЕТ КАДРОВ"
                )
                continue

            ranked = list(cands)
            winner = ranked[0]
            alts = ranked[1 : 1 + ALTS_KEEP]

            w_name = "winner.jpg"
            _save_jpg(winner.image, slide_dir / w_name)
            rel_base = f"{topic_dir.name}/{slide_dir.name}"
            slide_snap.winner = _cand_snap(winner, f"{rel_base}/{w_name}")

            for j, alt in enumerate(alts, start=1):
                a_name = f"alt_{j}.jpg"
                _save_jpg(alt.image, slide_dir / a_name)
                slide_snap.alts.append(
                    _cand_snap(alt, f"{rel_base}/{a_name}")
                )

            print(
                f"[Тема {topic_index}/{topic_total}] Слайд {slide_snap.index}: "
                f"'{slide_snap.search_query}' -> Победитель: pin_{winner.pin_id} "
                f"(Rel: {slide_snap.winner.rel:.0%}, "
                f"Taste: {slide_snap.winner.taste:.0%}, "
                f"Final: {slide_snap.winner.final:.0%})"
            )

            pid = str(winner.pin_id or "")
            if pid:
                run_used_pins.add(pid)
                harvester.mark_used([pid])

        (topic_dir / "summary.json").write_text(
            json.dumps(
                {
                    "topic": topic,
                    "pool_index": pool_index,
                    "slides": [
                        {
                            "index": s.index,
                            "role": s.role,
                            "text": s.text,
                            "visual_scene": s.visual_scene,
                            "search_query": s.search_query,
                            "error": s.error,
                            "winner": asdict(s.winner) if s.winner else None,
                            "alts": [asdict(a) for a in s.alts],
                        }
                        for s in snap.slides
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        snap.error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        print(f"[Тема {topic_index}/{topic_total}] FAIL: {snap.error}")

    snap.elapsed_sec = time.perf_counter() - t0
    return snap


def _badge_html(c: CandSnap) -> str:
    mode = html.escape(c.mode or "—")
    return (
        f'<span class="badge">Смысл {c.rel:.0%}</span>'
        f'<span class="badge">Вкус {c.taste:.0%}</span>'
        f'<span class="badge">UGC {c.ugc:.0%}</span>'
        f'<span class="badge accent">Final {c.final:.0%}</span>'
        f'<span class="badge muted">Mode: {mode}</span>'
    )


def _cand_card(c: CandSnap, *, title: str, winner: bool = False) -> str:
    cls = "cand winner" if winner else "cand"
    reason = html.escape(c.reason or "")
    return f"""
    <div class="{cls}">
      <div class="cand-title">{html.escape(title)}</div>
      <img src="{html.escape(c.path)}" alt="pin {html.escape(c.pin_id)}" loading="lazy"/>
      <div class="badges">{_badge_html(c)}</div>
      <div class="pin">pin_{html.escape(c.pin_id)}</div>
      {"<div class='reason'>" + reason + "</div>" if reason else ""}
    </div>
    """


def build_html_report(snaps: list[TopicSnap], *, started: str) -> str:
    blocks: list[str] = []
    for snap in snaps:
        slides_html: list[str] = []
        for s in snap.slides:
            if s.error and not s.winner:
                body = (
                    f'<div class="err">Ошибка слайда: '
                    f"{html.escape(s.error)}</div>"
                )
            elif s.winner:
                alts = "".join(
                    _cand_card(a, title=f"Alt {i}")
                    for i, a in enumerate(s.alts, start=1)
                ) or '<div class="muted">Нет альтернатив</div>'
                body = f"""
                <div class="winner-wrap">
                  {_cand_card(s.winner, title="Победитель", winner=True)}
                </div>
                <div class="alts-label">Отвергнутые альтернативы</div>
                <div class="alts-row">{alts}</div>
                """
            else:
                body = '<div class="err">Нет победителя</div>'

            slides_html.append(
                f"""
                <article class="slide">
                  <header>
                    <h3>Слайд {s.index}
                      <span class="role">{html.escape(s.role)}</span>
                    </h3>
                  </header>
                  <p class="slide-text">{html.escape(s.text)}</p>
                  <p class="query">visual_scene:
                    <code>{html.escape(s.visual_scene or "—")}</code>
                  </p>
                  <p class="query">search_query:
                    <code>{html.escape(s.search_query)}</code>
                  </p>
                  {body}
                </article>
                """
            )

        err_banner = (
            f'<div class="err topic-err">{html.escape(snap.error)}</div>'
            if snap.error
            else ""
        )
        blocks.append(
            f"""
            <section class="topic">
              <h2>Тема {snap.topic_index}/{snap.topic_total}
                <span class="pool">#{snap.pool_index}</span>
              </h2>
              <p class="topic-title">{html.escape(snap.topic)}</p>
              <p class="meta">{snap.elapsed_sec:.1f}s · {len(snap.slides)} slides</p>
              {err_banner}
              {"".join(slides_html)}
            </section>
            """
        )

    ok_n = sum(1 for s in snaps if not s.error)
    slide_ok = sum(1 for s in snaps for sl in s.slides if sl.winner is not None)
    slide_all = sum(len(s.slides) for s in snaps)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>E2E Diagnostics — Carousel Pipeline</title>
<style>
  :root {{
    --bg: #0f1115;
    --panel: #1a1d24;
    --panel2: #22262f;
    --fg: #e8eaed;
    --muted: #9aa0a6;
    --accent: #3ddc97;
    --border: #2e3440;
    --danger: #e74c3c;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px;
    font-family: "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--fg);
    line-height: 1.45;
  }}
  h1 {{ font-size: 1.6rem; margin: 0 0 8px; }}
  h2 {{ font-size: 1.25rem; margin: 0 0 6px; color: var(--accent); }}
  h3 {{ font-size: 1.05rem; margin: 0; }}
  .summary {{
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px 18px; margin-bottom: 28px;
  }}
  .summary .muted {{ color: var(--muted); font-size: 0.9rem; }}
  .topic {{
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px; margin-bottom: 32px;
  }}
  .topic-title {{ font-size: 1.1rem; margin: 4px 0 8px; }}
  .pool {{
    font-size: 0.75rem; color: var(--muted); font-weight: 400;
    margin-left: 8px;
  }}
  .meta {{ color: var(--muted); font-size: 0.85rem; margin: 0 0 16px; }}
  .slide {{
    background: var(--panel2); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px; margin: 14px 0;
  }}
  .role {{
    display: inline-block; margin-left: 8px;
    padding: 2px 8px; border-radius: 999px;
    background: #2a3140; color: var(--accent);
    font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
  }}
  .slide-text {{
    font-size: 1.15rem; font-weight: 600; margin: 12px 0 10px;
    white-space: pre-wrap;
  }}
  .query {{
    color: var(--muted); font-size: 0.9rem; margin: 0 0 14px;
  }}
  .query code {{
    color: var(--accent); background: #12151c;
    padding: 2px 8px; border-radius: 4px; font-size: 0.95rem;
  }}
  .winner-wrap {{
    margin-bottom: 12px;
    max-width: 260px;
  }}
  .alts-label {{
    color: var(--muted); font-size: 0.8rem;
    text-transform: uppercase; letter-spacing: 0.04em;
    margin: 8px 0 8px;
  }}
  .alts-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
  }}
  .alts-row .cand {{
    width: 180px;
    flex: 0 0 180px;
  }}
  .cand {{
    background: #12151c; border: 1px solid var(--border);
    border-radius: 8px; padding: 8px; overflow: hidden;
    max-width: 260px;
  }}
  .cand.winner {{
    border-color: var(--accent);
    max-width: 260px;
  }}
  .cand-title {{
    font-size: 0.72rem; color: var(--muted);
    margin-bottom: 4px; text-transform: uppercase;
  }}
  .cand img {{
    width: 100%;
    max-width: 244px;
    height: 325px;
    object-fit: cover;
    border-radius: 6px; display: block; background: #000;
  }}
  .alts-row .cand img {{
    max-width: 164px;
    height: 219px;
  }}
  .badges {{
    display: flex; flex-wrap: wrap; gap: 3px; margin-top: 6px;
  }}
  .badge {{
    font-size: 0.68rem; padding: 2px 6px; border-radius: 4px;
    background: #2a3140; color: var(--fg);
  }}
  .badge.accent {{ background: #1a3d2e; color: var(--accent); }}
  .badge.muted {{ color: var(--muted); }}
  .pin {{ font-size: 0.68rem; color: var(--muted); margin-top: 4px; word-break: break-all; }}
  .reason {{ font-size: 0.68rem; color: var(--muted); margin-top: 2px; }}
  .err {{
    color: var(--danger); background: #2a1515;
    border: 1px solid #5a2020; padding: 10px 12px;
    border-radius: 6px; margin: 8px 0;
  }}
  @media (max-width: 900px) {{
    .alts-row .cand {{ width: 140px; flex-basis: 140px; }}
    .alts-row .cand img {{ max-width: 124px; height: 165px; }}
  }}
</style>
</head>
<body>
  <div class="summary">
    <h1>E2E Diagnostics — смысловой подбор фото</h1>
    <p class="muted">
      Started {html.escape(started)} · topics OK {ok_n}/{len(snaps)} ·
      slides with winner {slide_ok}/{slide_all} ·
      candidates/slide={CANDIDATES} · alts shown={ALTS_KEEP}
    </p>
    <p class="muted">
      Pipeline: llm_engine.generate_carousel → finalize_photo_query →
      harvest_slides_parallel (SigLIP rel/taste/ugc) → report
    </p>
  </div>
  {"".join(blocks)}
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="E2E carousel image-sense diagnostics"
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Прогнать все 20 тем из пула",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Сколько тем взять из default-набора / пула",
    )
    p.add_argument(
        "--indices",
        type=str,
        default="",
        help="Индексы из пула через запятую, напр. 0,7,13",
    )
    return p.parse_args()


def resolve_indices(args: argparse.Namespace) -> list[int]:
    if args.indices.strip():
        out: list[int] = []
        for part in args.indices.split(","):
            part = part.strip()
            if not part:
                continue
            i = int(part)
            if i < 0 or i >= len(TOPIC_POOL):
                raise SystemExit(
                    f"index {i} вне диапазона 0..{len(TOPIC_POOL) - 1}"
                )
            out.append(i)
        return out
    if args.all:
        return list(range(len(TOPIC_POOL)))
    if args.limit and args.limit > 0:
        base = list(DEFAULT_INDICES)
        if args.limit <= len(base):
            return base[: args.limit]
        extra = [i for i in range(len(TOPIC_POOL)) if i not in base]
        return (base + extra)[: args.limit]
    return list(DEFAULT_INDICES)


def main() -> int:
    args = parse_args()
    indices = resolve_indices(args)
    total = len(indices)
    started = datetime.now().isoformat(timespec="seconds")

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"E2E diagnostics · {total} тем · out={OUT_ROOT}")
    print(f"Indices: {indices}")
    print(
        f"CANDIDATES={CANDIDATES} "
        f"(harvester default {CANDIDATES_PER_SLIDE})"
    )

    generator = OllamaGenerator()
    if not generator.is_available():
        print("ERROR: GEMINI_API_KEY не задан (.env)")
        return 2

    harvester = PinterestHarvester(
        on_status=lambda m: print(f"  [harvester] {m}") if m else None
    )

    # HARD BAN pin_id на весь e2e-запуск (все темы / все слайды)
    run_used_pins: set[str] = set()

    snaps: list[TopicSnap] = []
    try:
        try:
            from core.taste_embedder import get_embedder

            t_w = time.perf_counter()
            get_embedder().ensure()
            print(f"[TIMER] SigLIP ensure: {time.perf_counter() - t_w:.1f}s")
        except Exception as exc:
            print(f"[WARNING] SigLIP ensure skip: {exc}")

        try:
            harvester.warm_session(force=False)
            probe = harvester.search(
                "messy desk closed laptop", finalize=False
            )
            print(f"[Pinterest] preflight · {len(probe or [])} pins")
            if not probe:
                print("ERROR: Pinterest недоступен (probe=0)")
                return 3
        except Exception as exc:
            print(f"ERROR: Pinterest preflight: {exc}")
            return 3

        for run_i, pool_i in enumerate(indices, start=1):
            topic = TOPIC_POOL[pool_i]
            print()
            print("=" * 72)
            print(f"Тема {run_i}/{total} (pool #{pool_i}): {topic}")
            print("=" * 72)
            snap = run_one_topic(
                topic=topic,
                pool_index=pool_i,
                topic_index=run_i,
                topic_total=total,
                generator=generator,
                harvester=harvester,
                out_dir=OUT_ROOT,
                run_used_pins=run_used_pins,
            )
            snaps.append(snap)
            print(
                f"[Тема {run_i}/{total}] done in {snap.elapsed_sec:.1f}s · "
                f"run_used_pins={len(run_used_pins)}"
            )
    finally:
        try:
            harvester.close()
        except Exception:
            pass

    report_path = OUT_ROOT / "report.html"
    report_path.write_text(
        build_html_report(snaps, started=started), encoding="utf-8"
    )
    manifest = {
        "started": started,
        "finished": datetime.now().isoformat(timespec="seconds"),
        "indices": indices,
        "topics": [TOPIC_POOL[i] for i in indices],
        "candidates": CANDIDATES,
        "report": str(report_path),
        "results": [
            {
                "topic": s.topic,
                "error": s.error,
                "elapsed_sec": s.elapsed_sec,
                "slides_ok": sum(1 for sl in s.slides if sl.winner),
                "slides_total": len(s.slides),
            }
            for s in snaps
        ],
    }
    (OUT_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print()
    print(f"HTML report: {report_path}")
    print(f"Manifest:    {OUT_ROOT / 'manifest.json'}")
    return 0 if all(not s.error for s in snaps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
