#!/usr/bin/env python3
"""Проверка каждого кадра партий «карусель → видео со свайпами» (swipe_video.py) — ПАРАЛЛЕЛЬНО, распаковка на видеокарте
(3 потока, правило CUDA ≤ 3), прогресс виден на дашборде (progress_server.py, «Сейчас идёт»).
По manifest_<папка>.json, который пишет сборщик в output/_work/<проект>/:
  • кадров = длина × 30; ровно (слайдов − 1) свайпов по 7–11 кадров, каждый кончается на своей доле; между ними кадр стоит;
  • громкость не тихая;
  • сетки «слайд k во всех видео» → <work>/qa/<папка>_slide<k>.jpg — смотреть глазами (текст, лица, карточка).
Общая проверка (теги, md5, битые кадры) — qa_batch.py, запускать перед этой.

  python qa_swipe_video.py --work output/_work/xmas_video output/inspoy_xmas_video_YT_150 output/inspoy_xmas_video_TT_100
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import qa_batch as Q  # noqa: E402  (tick — прогресс для дашборда)

FPS = 30


def check(job: tuple[Path, dict]) -> tuple[Path, list[str], list[np.ndarray]]:
    f, m = job
    raw = subprocess.run(["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-i", str(f), "-vf", "scale=108:192",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 192, 108, 3)
    errs = []
    if abs(len(fr) - round(m["total"] * FPS)) > 1:
        errs.append(f"кадров {len(fr)}, ждали {round(m['total'] * FPS)}")
    d = np.abs(np.diff(fr.astype(np.int16), axis=0)).mean(axis=(1, 2, 3))
    runs: list[list[int]] = []
    for i in np.where(d > 1.5)[0] + 1:
        if runs and i <= runs[-1][1] + 1:
            runs[-1][1] = i
        else:
            runs.append([int(i), int(i)])
    exp = [round(e * FPS) for e in m["ends"]]
    if len(runs) != len(exp) or any(abs(r[1] - (e - 1)) > 1 or not 7 <= r[1] - r[0] + 1 <= 11 for r, e in zip(runs, exp)):
        errs.append(f"свайпы {runs}, ждали к кадрам {exp}")
    vol = subprocess.run(["ffmpeg", "-v", "info", "-i", str(f), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    mv = [ln for ln in vol.splitlines() if "mean_volume" in ln]
    if not mv or float(mv[0].split(":")[1].split()[0]) < -25:
        errs.append(f"тихо: {mv}")
    mids = [fr[min(len(fr) - 1, h + 12)] for h in [0] + exp]
    Q.tick()
    return f, errs, mids


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+", type=Path)
    ap.add_argument("--work", type=Path, required=True, help="папка с manifest_<папка>.json")
    a = ap.parse_args()
    jobs, missing = [], []
    for d in a.dirs:
        man = json.loads((a.work / f"manifest_{d.name}.json").read_text(encoding="utf-8"))
        for f in sorted(d.glob("*.mp4")):
            (jobs.append((f, man[f.name])) if f.name in man else missing.append(f"{d.name}/{f.name}"))
        missing += [f"{d.name}/{n} (нет файла)" for n in man if not (d / n).exists()]
    Q._state["total"] = len(jobs)
    Q.tick("каждый кадр: свайпы, длительность, звук")
    with ThreadPoolExecutor(3) as ex:                    # CUDA ≤ 3
        res = list(ex.map(check, jobs))
    bad = [(f, e) for f, e, _ in res if e]
    qa = a.work / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    for d in a.dirs:
        rows = [m for f, _, m in res if f.parent == d]
        for k in range(len(rows[0]) if rows else 0):
            g = Image.new("RGB", (15 * 108, ((len(rows) + 14) // 15) * 192))
            for j, m in enumerate(rows):
                g.paste(Image.fromarray(m[k]), (j % 15 * 108, j // 15 * 192))
            g.save(qa / f"{d.name}_slide{k + 1}.jpg", quality=80)
    print(f"проверено {len(res)} видео, с ошибками {len(bad)}, расхождений с планом {len(missing)} {missing[:3]}")
    for f, e in bad[:20]:
        print("  ", f.parent.name, f.name, e)
    print("сетки слайдов →", qa)
    Q.PROG.unlink(missing_ok=True)
    return 1 if bad or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
