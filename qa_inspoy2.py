#!/usr/bin/env python3
"""Проверка каждого кадра роликов «Инспой 2» (build_inspoy2_reels.py) — параллельно, распаковка на видеокарте (3 потока),
прогресс на дашборде. Для каждого: 207 кадров; смены фото ровно на кадрах рефа и больше нигде (между сменами кадр стоит);
громкость; лист «кадр после каждой смены» → output/_work/inspoy_fits/qa/<папка>.jpg (смотреть глазами: финал, текст, фото).

  python qa_inspoy2.py output/inspoy2_TT_150 output/inspoy2_YT_150
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
import build_inspoy2_reels as B  # noqa: E402
import qa_batch as Q  # noqa: E402

WORK = ROOT / "output" / "_work" / "inspoy2"


def check(job: tuple[Path, float]) -> tuple[Path, list[str], np.ndarray]:
    f, ss = job
    cuts_s, total, _ = B.timing(ss)
    CUTS = [round(c * B.FPS) for c in cuts_s]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-i", str(f), "-vf", "scale=108:192",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 192, 108, 3)
    errs = []
    if len(fr) != round(total * B.FPS):
        errs.append(f"кадров {len(fr)}")
    d = np.abs(np.diff(fr.astype(np.int16), axis=0)).mean(axis=(1, 2, 3))
    moved = [i + 1 for i in np.where(d > 1.0)[0]]
    if moved != CUTS:
        errs.append(f"смены {moved} ≠ реф {CUTS}")
    weak = [c for c in CUTS if c - 1 < len(d) and d[c - 1] < 6]
    if weak:
        errs.append(f"слабая смена (похожие фото подряд) на кадрах {weak}")
    vol = subprocess.run(["ffmpeg", "-v", "info", "-i", str(f), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    mv = [ln for ln in vol.splitlines() if "mean_volume" in ln]
    if not mv or float(mv[0].split(":")[1].split()[0]) < -25:
        errs.append(f"тихо: {mv}")
    Q.tick()
    return f, errs, fr[[0] + CUTS]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dirs = [Path(x) for x in sys.argv[1:]]
    files = []
    for d in dirs:
        man = json.loads((WORK / f"manifest_{d.name}.json").read_text(encoding="utf-8"))
        files += [(f, man[f.name]["ss"]) for f in sorted(d.glob("*.mp4"))]
    Q._state["total"] = len(files)
    Q.tick("каждый кадр: смены фото по рефу, длина, звук")
    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(check, files))
    qa = WORK / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        rows = [s for f, _, s in res if f.parent == d]
        g = Image.new("RGB", (len(rows[0]) * 54, len(rows) * 96))
        for i, s in enumerate(rows):
            for j, x in enumerate(s):
                g.paste(Image.fromarray(x).resize((54, 96)), (j * 54, i * 96))
        g.save(qa / f"{d.name}.jpg", quality=80)
    bad = [(f, e) for f, e, _ in res if e]
    print(f"проверено {len(res)} роликов, с ошибками {len(bad)}")
    for f, e in bad[:20]:
        print("  ", f.parent.name, f.name, e)
    Q.PROG.unlink(missing_ok=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
