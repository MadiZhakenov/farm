#!/usr/bin/env python3
"""Проверка каждого кадра партии OneState 3 (build_onestate3_reels.py --tt/--yt) — параллельно, распаковка на видеокарте
(3 потока), прогресс на дашборде. По манифесту: кадров = длина × 30; каждая склейка (кино → кино → геймплей → …) — на своём
кадре; чёрных кадров нет; громкость; лист «кадр каждого куска» → output/_work/onestate3/qa/<папка>.jpg.

  python qa_onestate3.py output/onestate_3_TT_100 output/onestate_3_YT_200
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

FPS = 30
WORK = ROOT / "output" / "_work" / "onestate3"


def check(job: tuple[Path, dict]) -> tuple[Path, list[str], list[np.ndarray]]:
    f, j = job
    raw = subprocess.run(["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-i", str(f), "-vf", "scale=108:192",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 192, 108, 3)
    errs = []
    total = sum(p["n"] for p in j["pieces"])
    if len(fr) != total:
        errs.append(f"кадров {len(fr)}, ждали {total}")
    d = np.abs(np.diff(fr.astype(np.int16), axis=0)).mean(axis=(1, 2, 3))
    acc, bounds = 0, []
    for p in j["pieces"][:-1]:
        acc += p["n"]
        bounds.append(acc)
    for b in bounds:
        if not (b - 1 < len(d) and d[b - 1] > 10):
            errs.append(f"нет склейки на кадре {b} ({d[b - 1] if b - 1 < len(d) else -1:.1f})")
    if (fr.reshape(len(fr), -1).mean(1) < 10).any():
        errs.append("чёрные кадры")
    vol = subprocess.run(["ffmpeg", "-v", "info", "-i", str(f), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    mv = [ln for ln in vol.splitlines() if "mean_volume" in ln]
    if not mv or float(mv[0].split(":")[1].split()[0]) < -30:
        errs.append(f"тихо: {mv}")
    Q.tick()
    starts = [0] + bounds
    return f, errs, [fr[min(len(fr) - 1, s + 8)] for s in starts]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dirs = [Path(x) for x in sys.argv[1:]]
    jobs = []
    for d in dirs:
        man = json.loads((WORK / f"manifest_{d.name}.json").read_text(encoding="utf-8"))
        jobs += [(f, man[f.name]) for f in sorted(d.glob("*.mp4"))]
    Q._state["total"] = len(jobs)
    Q.tick("каждый кадр: склейки, длина, звук")
    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(check, jobs))
    qa = WORK / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        rows = [m for f, _, m in res if f.parent == d]
        cols = max(len(m) for m in rows)
        g = Image.new("RGB", (2 * cols * 108, ((len(rows) + 1) // 2) * 192))
        for i, m in enumerate(rows):
            for k, x in enumerate(m):
                g.paste(Image.fromarray(x), ((i % 2) * cols * 108 + k * 108, (i // 2) * 192))
        g.save(qa / f"{d.name}.jpg", quality=80)
    bad = [(f, e) for f, e, _ in res if e]
    print(f"проверено {len(res)} роликов, с ошибками {len(bad)}")
    for f, e in bad[:20]:
        print("  ", f.parent.name, f.name, e)
    Q.PROG.unlink(missing_ok=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
