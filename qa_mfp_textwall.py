#!/usr/bin/env python3
"""Проверка каждого кадра текстволлов MyFitnessPal (build_mfp_textwall.py) — параллельно, распаковка на видеокарте (3 потока),
прогресс на дашборде. Для каждого ролика: кадров = длина × 30, нет чёрных кадров, фон не стоит дольше 1.2 с
(энергия — склейки в такт), громкость; лист 3 кадра/с на ролик → output/_work/mfp_textwall/qa/<папка>.jpg.

  python qa_mfp_textwall.py output/myfitnesspal_textwall_20
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

WORK = ROOT / "output" / "_work" / "mfp_textwall"


def check(job: tuple[Path, dict]) -> tuple[Path, list[str], np.ndarray]:
    f, m = job
    raw = subprocess.run(["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-i", str(f), "-vf", "scale=108:192",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 192, 108, 3)
    errs = []
    if abs(len(fr) - round(m["total"] * 30)) > 1:
        errs.append(f"кадров {len(fr)}, ждали {round(m['total'] * 30)}")
    if (fr.reshape(len(fr), -1).mean(1) < 12).any():
        errs.append("есть чёрные кадры")
    d = np.abs(np.diff(fr.astype(np.int16), axis=0)).mean(axis=(1, 2, 3))
    still, run = 0, 0
    for x in d:
        run = run + 1 if x < 0.4 else 0
        still = max(still, run)
    if still > 36:
        errs.append(f"фон стоит {still / 30:.1f} с")
    vol = subprocess.run(["ffmpeg", "-v", "info", "-i", str(f), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    mv = [ln for ln in vol.splitlines() if "mean_volume" in ln]
    if not mv or float(mv[0].split(":")[1].split()[0]) < -25:
        errs.append(f"тихо: {mv}")
    Q.tick()
    return f, errs, fr[::10]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dirs = [Path(x) for x in sys.argv[1:]]
    jobs = []
    for d in dirs:
        man = json.loads((WORK / f"manifest_{d.name}.json").read_text(encoding="utf-8"))
        jobs += [(f, man[f.name]) for f in sorted(d.glob("*.mp4"))]
    Q._state["total"] = len(jobs)
    Q.tick("каждый кадр: длина, чёрные кадры, склейки, звук")
    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(check, jobs))
    qa = WORK / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        rows = [s for f, _, s in res if f.parent == d]
        cols = max(len(s) for s in rows)
        g = Image.new("RGB", (cols * 108, len(rows) * 192))
        for i, s in enumerate(rows):
            for j, x in enumerate(s):
                g.paste(Image.fromarray(x), (j * 108, i * 192))
        g.save(qa / f"{d.name}.jpg", quality=82)
    bad = [(f, e) for f, e, _ in res if e]
    print(f"проверено {len(res)} роликов, с ошибками {len(bad)}")
    for f, e in bad:
        print("  ", f.name, e)
    Q.PROG.unlink(missing_ok=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
