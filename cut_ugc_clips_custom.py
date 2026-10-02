#!/usr/bin/env python3
"""
Нарезка произвольных исходников на клипы заданной длины — та же оценка окон,
отбор и SDR-экспорт, что в cut_ugc_clips_cozy.py (скорер лица или «игры»),
но длительность и отрезок задаются на источник.

  python cut_ugc_clips_custom.py --dry-run
  python cut_ugc_clips_custom.py --thumbs
  python cut_ugc_clips_custom.py --project proj2 --thumbs

Выход: output/clips_custom/ (proj2 → output/clips_proj2/) <slug>_<scorer>_<N>s/*.mp4 + manifest.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

import cut_ugc_clips_cozy as cz

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "downloads"
# scorer: "face" (реакция лицом) или "play" (планшет / руки / игра).
# start/end — отрезок исходника в секундах (None = весь).
PROJECTS: dict[str, dict] = {
    "cozy": {
        "out": ROOT / "output" / "clips_custom",
        "sources": [
            {"file": "MyResultVideo.mp4", "scorer": "face", "clip": 4.0, "start": None, "end": None},
            {"file": "IMG_9759.mov", "scorer": "play", "clip": 2.0, "start": 8.0, "end": 19.0},
            {"file": "IMG_9745.mov", "scorer": "play", "clip": 2.0, "start": None, "end": None},
        ],
    },
    # 1-й кадр 3 с (лицо) + 2 клипа по 2 с с планшетом = 7 с; лицо ещё и по 2 с.
    # IMG_9758: до 3 с пустой стол / подходит, после 28.5 с уходит.
    "proj2": {
        "out": ROOT / "output" / "clips_proj2",
        "sources": [
            {"file": "IMG_9736.MP4", "scorer": "face", "clip": 3.0, "start": None, "end": None},
            {"file": "IMG_9736.MP4", "scorer": "face", "clip": 2.0, "start": None, "end": None},
            {"file": "IMG_9758.mov", "scorer": "play", "clip": 2.0, "start": 3.0, "end": 28.5},
        ],
    },
    # лицо 3 с — те же отобранные клипы из clips_proj2 (IMG_9736_face_3s);
    # рисует с лицом 2.5 с → кот + планшет 2 с → руки раскрашивают 1 с.
    # IMG_9759: до 14 с пустой стол / кот подходит; IMG_9745: планшет кладут/убирают
    "proj3": {
        "out": ROOT / "output" / "clips_proj3",
        "sources": [
            {"file": "IMG_9761.mp4", "scorer": "play", "clip": 2.5, "start": None, "end": None},
            {"file": "IMG_9759.mov", "scorer": "play", "clip": 2.0, "start": 14.0, "end": None},
            {"file": "IMG_9745.mov", "scorer": "play", "clip": 1.0, "start": 5.0, "end": 66.0},
        ],
    },
}
# скореры cozy: "guy" = лицо, "girl" = игра
COZY_ROLE = {"face": "guy", "play": "girl"}


def cut_source(spec: dict, min_score: float, face_cascade) -> list[cz.ClipPick]:
    path = RAW_DIR / spec["file"]
    role = COZY_ROLE[spec["scorer"]]
    dur = cz.probe_duration(path)
    t0 = float(spec["start"] or 0.0)
    t1 = min(dur, float(spec["end"] or dur))
    print(f"\n=== {path.name} scorer={spec['scorer']} clip={spec['clip']}s "
          f"range={t0:.1f}–{t1:.1f}s ===", flush=True)

    times, metrics, reasons, scores = cz.analyze_timeline(
        path, role, face_cascade if role == "guy" else None
    )
    # Отрезок: сдвинуть таймлайн к нулю, чтобы края считались от отрезка
    mask = (times >= t0) & (times <= t1)
    idx = np.where(mask)[0]
    sub_times = times[idx] - t0
    sub_metrics = [metrics[i] for i in idx]
    sub_reasons = [reasons[i] for i in idx]
    sub_scores = scores[idx]
    print(f"  samples {len(idx)} · score min/mean/max "
          f"{sub_scores.min():.2f}/{sub_scores.mean():.2f}/{sub_scores.max():.2f}", flush=True)

    saved = cz.ROLE_DURATION[role]
    cz.ROLE_DURATION[role] = float(spec["clip"])  # pick_from_timeline читает длину отсюда
    try:
        picks = cz.pick_from_timeline(
            path, role, t1 - t0, min_score,
            sub_times, sub_metrics, sub_reasons, sub_scores,
        )
    finally:
        cz.ROLE_DURATION[role] = saved

    slug = cz.slug_source(path.name)
    for i, p in enumerate(picks, 1):
        p.start = round(p.start + t0, 3)
        p.role = spec["scorer"]
        p.out_name = f"{slug}_{spec['scorer']}_{i:03d}_{p.start:.2f}s.mp4"
    print(f"  kept {len(picks)} clips (min_score={min_score})", flush=True)
    for p in picks:
        print(f"    [{p.score:.2f}] {p.start:6.2f}s  {', '.join(p.reasons[:3]) or 'ok'}", flush=True)
    return picks


def folder_for(spec: dict) -> str:
    return f"{cz.slug_source(spec['file'])}_{spec['scorer']}_{spec['clip']:g}s"


def main() -> int:
    ap = argparse.ArgumentParser(description="Cut custom UGC sources into fixed-length clips")
    ap.add_argument("--project", choices=sorted(PROJECTS), default="cozy")
    ap.add_argument("--out-dir", type=Path, help="по умолчанию — папка проекта")
    ap.add_argument("--min-score", type=float, default=0.48)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--thumbs", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")

    project = PROJECTS[args.project]
    args.out_dir = args.out_dir or project["out"]
    face_cascade = cz.load_face_cascade()
    cz.FACE_ALT = cz.load_face_alt()

    manifest: dict = {"min_score": args.min_score, "sources": []}
    for spec in project["sources"]:
        picks = cut_source(spec, args.min_score, face_cascade)
        sub = args.out_dir / folder_for(spec)
        if not args.dry_run:
            for p in picks:
                dest = sub / p.out_name
                cz.export_clip(RAW_DIR / spec["file"], p, dest)
                if args.thumbs:
                    cz.write_thumb(RAW_DIR / spec["file"], p, sub / "_thumbs" / (dest.stem + ".jpg"))
        manifest["sources"].append({**spec, "folder": folder_for(spec), "clips": [asdict(p) for p in picks]})

    if not args.dry_run:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print("\n======== SUMMARY ========")
    for s in manifest["sources"]:
        print(f"{s['folder']}: {len(s['clips'])} clips")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
