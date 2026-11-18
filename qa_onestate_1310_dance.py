#!/usr/bin/env python3
"""Проверка каждого кадра партии 1310 «первый клип — танец» (build_1310_reels.py --dance) — параллельно, распаковка на видеокарте
(3 потока), прогресс на дашборде. По манифесту: 660 кадров (11 с × 60); каждая склейка моментов — на своём кадре (скачок
разницы кадров ≥ 3× медианы); лист «первый кадр (танец) + кадр после него (копы)» → output/_work/onestate_1310_dance/qa/.

  python qa_onestate_1310_dance.py output/onestate_1310_dance_TT_100 output/onestate_1310_dance_YT_100
"""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import qa_batch as Q  # noqa: E402

FPS = 60
WORK = ROOT / "output" / "_work" / "onestate_1310_dance"


def check(job: tuple[Path, dict]) -> tuple[Path, list[str], list[np.ndarray]]:
    f, j = job
    raw = subprocess.run(["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-i", str(f), "-vf", "scale=108:192",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 192, 108, 3)
    errs = []
    if len(fr) != 660:
        errs.append(f"кадров {len(fr)}")
    d = np.abs(np.diff(fr.astype(np.int16), axis=0)).mean(axis=(1, 2, 3))
    med = float(np.median(d)) + 0.05
    acc, bounds = 0, []
    for _f, dur in j["moments"][:-1]:
        acc += round(dur * FPS)
        bounds.append(acc)
    for b in bounds:
        win = d[max(0, b - 3):b + 2]
        if not len(win) or win.max() < 3 * med:
            errs.append(f"нет склейки у кадра {b} (макс {win.max() if len(win) else -1:.2f}, медиана {med:.2f})")
    Q.tick()
    return f, errs, [fr[3], fr[min(len(fr) - 1, bounds[0] + 10)]]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dirs = [Path(x) for x in sys.argv[1:]]
    jobs = []
    for d in dirs:
        man = {f"{j['n']:03d}_1310.mp4": j for j in json.loads((WORK / f"manifest_{d.name}.json").read_text(encoding="utf-8"))}
        jobs += [(f, man[f.name]) for f in sorted(d.glob("*.mp4"))]
    Q._state["total"] = len(jobs)
    Q.tick("каждый кадр: склейки моментов, длина")
    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(check, jobs))
    qa = WORK / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        rows = [m for f, _, m in res if f.parent == d]
        g = Image.new("RGB", (10 * 216, ((len(rows) + 4) // 5) * 192))
        for i, m in enumerate(rows):
            for k, x in enumerate(m):
                g.paste(Image.fromarray(x), ((i % 5) * 216 + k * 108, (i // 5) * 192))
        g.save(qa / f"{d.name}.jpg", quality=80)
    bad = [(f, e) for f, e, _ in res if e]
    print(f"проверено {len(res)} роликов, с ошибками {len(bad)}")
    for f, e in bad[:20]:
        print("  ", f.parent.name, f.name, e)
    Q.PROG.unlink(missing_ok=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
