#!/usr/bin/env python3
"""Проверка каждого кадра партии «папа-дальнобойщик» видео (Inspoy, ID 1) — ПАРАЛЛЕЛЬНО, распаковка на видеокарте (3 потока,
правило CUDA ≤ 3), прогресс виден в progress_server.py (раздел «Сейчас идёт»).
  • ровно 6 свайпов, каждый 7–11 кадров и кончается там, где положено по долям звука этого видео; между свайпами кадр стоит;
  • длительность = расчёт по старту звука (из batch.log);
  • громкость не тихая;
  • сетки «слайд k во всех видео» → output/_work/dad_trucker_video/qa/ — смотреть глазами (текст, лица, карточка).
Общая проверка (теги, md5, битые кадры) — qa_batch.py, запускать вместе.

  python qa_dad_trucker_video.py output/inspoy_dad_trucker_video_TT_150 output/inspoy_dad_trucker_video_YT_150
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_dad_trucker_video as V  # noqa: E402
import qa_batch as Q  # noqa: E402  (tick — прогресс для дашборда)

WORK = ROOT / "output" / "_work" / "dad_trucker_video"


def frames(f: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-i", str(f), "-vf", "scale=108:192",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, 192, 108, 3)


def check(job: tuple[Path, float]) -> tuple[Path, list[str], list[np.ndarray]]:
    f, start = job
    b0 = next(b for b in V.STARTS if abs(V.BEATS[b] - start) < 0.01)
    _, ends, total = V.timing(b0)
    errs = []
    fr = frames(f)
    if abs(len(fr) - round(total * V.FPS)) > 1:
        errs.append(f"кадров {len(fr)}, ждали {round(total * V.FPS)}")
    d = np.abs(np.diff(fr.astype(np.int16), axis=0)).mean(axis=(1, 2, 3))
    runs: list[list[int]] = []
    for i in np.where(d > 1.5)[0] + 1:
        if runs and i <= runs[-1][1] + 1:
            runs[-1][1] = i
        else:
            runs.append([int(i), int(i)])
    exp = [round(e * V.FPS) for e in ends]
    if len(runs) != 6 or any(abs(r[1] - (e - 1)) > 1 or not 7 <= r[1] - r[0] + 1 <= 11 for r, e in zip(runs, exp)):
        errs.append(f"свайпы {runs}, ждали к кадрам {exp}")
    vol = subprocess.run(["ffmpeg", "-v", "info", "-i", str(f), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    mv = [ln for ln in vol.splitlines() if "mean_volume" in ln]
    if not mv or float(mv[0].split(":")[1].split()[0]) < -25:
        errs.append(f"тихо: {mv}")
    holds = [0] + exp
    mids = [fr[min(len(fr) - 1, h + 15)] for h in holds]
    Q.tick()
    return f, errs, mids


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dirs = [Path(x) for x in sys.argv[1:]]
    start_of = {}
    for ln in (WORK / "batch.log").read_text(encoding="utf-8", errors="replace").splitlines():
        p = ln.split()
        if len(p) > 3 and p[0].startswith("inspoy_dad") and p[-2] == "start":
            start_of[(p[0], p[1])] = float(p[-1])
    jobs, missing = [], []
    for d in dirs:
        for f in sorted(d.glob("*.mp4")):
            st = start_of.get((d.name, f.name))
            (jobs.append((f, st)) if st is not None else missing.append(f"{d.name}/{f.name}"))
    Q._state["total"] = len(jobs)
    Q.tick("каждый кадр: свайпы, длительность, звук")
    with ThreadPoolExecutor(3) as ex:                    # CUDA ≤ 3
        res = list(ex.map(check, jobs))
    bad = [(f, e) for f, e, _ in res if e]
    qa = WORK / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        rows = [m for f, _, m in res if f.parent == d]
        for k in range(7):
            g = Image.new("RGB", (15 * 108, ((len(rows) + 14) // 15) * 192))
            for j, m in enumerate(rows):
                g.paste(Image.fromarray(m[k]), (j % 15 * 108, j // 15 * 192))
            g.save(qa / f"{d.name}_slide{k + 1}.jpg", quality=80)
    print(f"проверено {len(res)} видео, с ошибками {len(bad)}, нет в логе {len(missing)} {missing[:3]}")
    for f, e in bad[:20]:
        print("  ", f.parent.name, f.name, e)
    print("сетки слайдов →", qa)
    Q.PROG.unlink(missing_ok=True)
    return 1 if bad or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
