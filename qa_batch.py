#!/usr/bin/env python3
"""Быстрая проверка готовых партий видео — ПАРАЛЛЕЛЬНО (юзер 2026-11-12: «всегда параллельно и на видюхе»):
  • теги/метаданные, разрешение, длительность, число кадров (по пакетам — без декодирования), 8 потоков;
  • полное декодирование на видеокарте (NVDEC, -hwaccel cuda) — битые кадры/ошибки, 3 потока (правило: CUDA ≤ 3);
  • md5 — все файлы всех папок разные.
  python qa_batch.py output/a output/b [--w 1080 --h 1920] [--no-decode]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import os
import threading

PROG = Path(__file__).resolve().parent / "output" / "_work" / "_qa_progress" / f"{os.getpid()}.json"
_lock, _state = threading.Lock(), {"done": 0, "total": 0, "stage": ""}


def tick(stage: str | None = None) -> None:
    """Прогресс для progress_server.py (раздел «Сейчас идёт»): output/_work/_qa_progress/<pid>.json."""
    with _lock:
        if stage:
            _state["stage"] = stage
        else:
            _state["done"] += 1
        PROG.parent.mkdir(parents=True, exist_ok=True)
        PROG.write_text(json.dumps(_state), encoding="utf-8")


ALLOWED = {"language", "handler_name", "major_brand", "minor_version", "compatible_brands", "vendor_id"}


def probe(f: Path) -> dict:
    j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-show_entries",
                                   "format=duration:format_tags:stream=codec_type,width,height,nb_read_packets:stream_tags",
                                   "-of", "json", str(f)], capture_output=True, text=True).stdout or "{}")
    st = j.get("streams", [])
    v = next((s for s in st if s.get("codec_type") == "video"), {})
    tags = {k for s in st for k in s.get("tags", {})} | set(j.get("format", {}).get("tags", {}))
    return dict(f=f, ok=bool(v), w=v.get("width"), h=v.get("height"), frames=int(v.get("nb_read_packets", 0) or 0),
                dur=float(j.get("format", {}).get("duration", 0)), audio=any(s.get("codec_type") == "audio" for s in st),
                extra_tags=sorted(tags - ALLOWED), md5=hashlib.md5(f.read_bytes()).hexdigest()) | ({} if tick() else {})


def decode(f: Path) -> str:
    r = subprocess.run(["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-i", str(f), "-f", "null", "-"],
                       capture_output=True, text=True)
    tick()
    return r.stderr.strip()[:200]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+", type=Path)
    ap.add_argument("--w", type=int, default=1080)
    ap.add_argument("--h", type=int, default=1920)
    ap.add_argument("--no-decode", action="store_true")
    a = ap.parse_args()
    files = {d: sorted(d.glob("*.mp4")) for d in a.dirs}
    allf = [f for fs in files.values() for f in fs]
    _state["total"] = len(allf) * (1 if a.no_decode else 2)
    tick("теги, кадры, md5")
    with ThreadPoolExecutor(8) as ex:
        info = {r["f"]: r for r in ex.map(probe, allf)}
    errs = {}
    if not a.no_decode:
        tick("декодирование на видеокарте")
        with ThreadPoolExecutor(3) as ex:
            errs = {f: e for f, e in zip(allf, ex.map(decode, allf)) if e}
    for d, fs in files.items():
        rs = [info[f] for f in fs]
        other = [x.name for x in d.iterdir() if x.suffix != ".mp4"]
        bad = [r["f"].name for r in rs if not r["ok"] or not r["audio"] or (r["w"], r["h"]) != (a.w, a.h) or r["extra_tags"]]
        fr = [r["frames"] for r in rs] or [0]
        du = [r["dur"] for r in rs] or [0]
        print(f"{d.name}: {len(rs)} шт., {min(du):.2f}–{max(du):.2f} с, кадров {min(fr)}–{max(fr)}"
              f"{' | не mp4: ' + str(other[:3]) if other else ''}{' | ПРОБЛЕМЫ: ' + str(bad[:5]) if bad else ''}"
              f"{' | ошибки декодирования: ' + str(len([f for f in fs if f in errs])) if any(f in errs for f in fs) else ''}")
    md5 = [r["md5"] for r in info.values()]
    print(f"всего {len(md5)}, уникальных md5 {len(set(md5))}")
    for f, e in list(errs.items())[:5]:
        print("  декод:", f.name, e)
    PROG.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
