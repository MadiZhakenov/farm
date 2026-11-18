#!/usr/bin/env python3
"""Проверка каждого кадра партии Drops ghost (build_drops_ghost.py --music dugc) — параллельно, распаковка на видеокарте
(3 потока), прогресс на дашборде. По manifest_<папка>.json: кадров = сумма частей; склейки лицо → Ranks, Ranks → игра,
игра → игра стоят ровно на своих кадрах; чёрных кадров нет; громкость; лист «кадр каждой части» →
output/_work/drops_ghost/qa/<папка>.jpg.

  python qa_drops_ghost.py output/drops_ghost_TT_150 output/drops_ghost_YT_150
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
WORK = ROOT / "output" / "_work" / "drops_ghost"


def check(job: tuple[Path, dict]) -> tuple[Path, list[str], list[np.ndarray]]:
    f, r = job
    raw = subprocess.run(["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-i", str(f), "-vf", "scale=108:192",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 192, 108, 3)
    face = sum(round(ln * FPS) for _, _, ln in r["face"])
    rk = face + round(r["ranks_len"] * FPS)
    g1 = rk + round(r["cut1"] * FPS)
    total = g1 + round(r["cut2"] * FPS)
    errs = []
    if abs(len(fr) - total) > 1:
        errs.append(f"кадров {len(fr)}, ждали {total}")
    d = np.abs(np.diff(fr.astype(np.int16), axis=0)).mean(axis=(1, 2, 3))
    for name, b, thr in (("лицо→Ranks", face, 12), ("Ranks→игра", rk, 12), ("игра→игра", g1, 3)):
        if not (b - 1 < len(d) and d[b - 1] > thr):
            errs.append(f"нет склейки {name} на кадре {b} (разница {d[b - 1] if b - 1 < len(d) else -1:.1f})")
    if (fr.reshape(len(fr), -1).mean(1) < 10).any():
        errs.append("чёрные кадры")
    vol = subprocess.run(["ffmpeg", "-v", "info", "-i", str(f), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    mv = [ln for ln in vol.splitlines() if "mean_volume" in ln]
    if not mv or float(mv[0].split(":")[1].split()[0]) < -30:
        errs.append(f"тихо: {mv}")
    Q.tick()
    picks = [min(len(fr) - 1, x) for x in (face // 2, face + 5, rk + 8, g1 + 10)]
    return f, errs, [fr[i] for i in picks]


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
        g = Image.new("RGB", (4 * 108 * 4, ((len(rows) + 3) // 4) * 192))
        for i, m in enumerate(rows):
            for j, x in enumerate(m):
                g.paste(Image.fromarray(x), ((i % 4) * 432 + j * 108, (i // 4) * 192))
        g.save(qa / f"{d.name}.jpg", quality=80)
    bad = [(f, e) for f, e, _ in res if e]
    print(f"проверено {len(res)} роликов, с ошибками {len(bad)}")
    for f, e in bad[:20]:
        print("  ", f.parent.name, f.name, e)
    Q.PROG.unlink(missing_ok=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
