#!/usr/bin/env python3
"""
1253 v2 — только игра Cozy Home: 3 с одного куска + 2 с другого (склейка). Исходники —
лишь IMG_9743, IMG_9745, IMG_9753, IMG_9759 (9736, 9758, 9761, MyResultVideo НЕ трогаем).
Чистые отрезки выбраны по кадрам; куски без перекрытий, 9759 (207 с) — через шаг, чтобы
не перевешивал. Метрики (резкость / рывок) в manifest.json для отбора, лишнее — в _rejected/.

  python cut_1253_clips.py   → output/clips_1253_v2/play_3s, play_2s
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import cut_broll_clips as C  # noqa: E402

RAW = ROOT / "downloads"
OUT = ROOT / "output" / "clips_1253_v2"
# файл: (начало, конец чистой игры, с; шаг для 3 с; шаг для 2 с; сдвиг 2-секундных)
SOURCES = {
    "IMG_9743.mov": (20.0, 30.8, 3.0, 2.0, 0.0),   # до 19 с кошка ходит по планшету / хвост
    "IMG_9745.mov": (6.0, 66.0, 3.0, 2.0, 0.0),    # до 6 с меню, в конце планшет откладывают
    "IMG_9753.mov": (5.5, 36.5, 3.0, 2.0, 0.0),    # до 5.5 с меню / загрузка
    "IMG_9759.mov": (14.0, 204.0, 6.0, 6.0, 3.0),  # до 14 с подходит; длинное — через шаг
}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    jobs, manifest = [], []
    for length, sub in ((3.0, "play_3s"), (2.0, "play_2s")):
        d = OUT / sub
        d.mkdir(parents=True, exist_ok=True)
        k = 0
        for name, (t0, t1, step3, step2, off2) in SOURCES.items():
            src = RAW / name
            fps, bright, sharp, diff = C.analyze(src)
            med = float(np.median(sharp)) or 1.0
            step = step3 if length == 3.0 else step2
            t = t0 + (off2 if length == 2.0 else 0.0)
            while t + length <= t1 + 1e-6:
                k += 1
                a, b = int(t * fps), int((t + length) * fps)
                dest = d / f"{k:03d}_{Path(name).stem}_{t:.2f}s.mp4"
                jobs.append((src, t, length, dest))
                manifest.append({"file": f"{sub}/{dest.name}", "src": name, "start": round(t, 2),
                                 "sharp": round(float(sharp[a:b].mean()) / med, 2),
                                 "jerk": round(float(diff[a + 1:b].max()), 1)})
                t += step
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda j: C.export(*j), jobs))
    for sub in ("play_3s", "play_2s"):
        d = OUT / sub
        C.sheet(sorted(d.glob("*.mp4")), d / "_sheet.jpg", 3.0 if sub == "play_3s" else 2.0)
        print(f"{sub}: {len(list(d.glob('*.mp4')))}", flush=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
