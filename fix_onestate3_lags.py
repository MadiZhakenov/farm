#!/usr/bin/env python3
"""OneState 3 (ID 1): убрать «лаги» записи игры (юзер 13.11: «фризит, лагает»).

В самих записях игры есть повторённые кадры — игра подтормаживала во время записи (Taxi_job_1 около кадров
243–247 и 570–573, Polic_job около 392 и 468–476 и т.д.); в ролике такой повтор посреди движения = микрофриз.
Скрипт: находит повторы в исходниках → ролики партии, где кусок их захватывает (core/gpu_ffmpeg.bad_frames), получают
новый набор кусков, обходящий эти места (тот же звук/текст/профессия) → старые файлы удаляются → сборщик
build_onestate3_uniq.py дособирает только их (готовые пропускает).

  python fix_onestate3_lags.py --seed 31341
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_onestate3_uniq as U  # noqa: E402
from core import gpu_ffmpeg as G  # noqa: E402

FPS = 30


def source_lags(name: str) -> set[int]:
    """Кадры исходника, которые повторяют предыдущий (лаг записи), ±2 кадра запаса."""
    f = U.R.SRC / f"{name}.mp4"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-i", str(f), "-vf", "scale=96:54",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 54, 96, 3).astype(np.int16)
    d = np.abs(np.diff(fr.mean(axis=3), axis=0)).mean(axis=(1, 2))
    out = set()
    for i in range(len(d)):
        if d[i] < 0.12:
            out.update(range(i + 1 - 2, i + 1 + 3))
    return out


def piece_hits(p: dict, lags: dict) -> bool:
    k0 = round(p["st"] * FPS)
    k1 = k0 + int(np.ceil(p["n"] * p["speed"])) + 2
    return any(k in lags.get(p["f"], ()) for k in range(k0, k1))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=31341)
    ap.add_argument("--n", type=int, default=300)
    a = ap.parse_args()
    names = sorted({x[0] for pool in (U.POOL_FIRST, U.POOL_SECOND, U.POOL_GAME) for lst in pool.values() for x in lst})
    lags = {nm: source_lags(nm) for nm in names}
    print("лаги в записях игры (кадров с запасом):", {k: len(v) for k, v in lags.items()}, flush=True)
    plan_f = U.WORK / f"uniq_plan_{a.n}_{a.seed}.json"
    rows = json.loads(plan_f.read_text(encoding="utf-8"))
    dirs = [ROOT / "output" / "onestate_3_TT_100", ROOT / "output" / "onestate_3_YT_200"]
    files = [f for d in dirs for f in sorted(d.glob("*.mp4"))]
    with ThreadPoolExecutor(6) as ex:
        flags = dict(zip(files, ex.map(G.bad_frames, files)))
    bad_files = [f for f, fl in flags.items() if fl]
    mans = {d: json.loads((U.WORK / f"manifest_{d.name}.json").read_text(encoding="utf-8")) for d in dirs}
    bad_idx = {mans[f.parent][f.name]["i"] for f in bad_files}
    # плюс ролики, у которых кусок захватывает лаг, даже если проверка его не поймала
    for r in rows:
        if any(piece_hits(p, lags) for p in r["pieces"]):
            bad_idx.add(r["i"])
    print(f"роликов с фризами по проверке: {len(bad_files)}; всего к пересборке (кусок задевает лаг): {len(bad_idx)}",
          flush=True)
    rng = random.Random(a.seed * 7 + 11)
    for r in rows:
        if r["i"] not in bad_idx:
            continue
        for _ in range(400):
            c = U.candidate(rng, r["prof"], r["snd"])
            if not any(piece_hits(p, lags) for p in c["pieces"]):
                break
        else:
            raise SystemExit(f"ролик {r['i']}: не нашлось кусков без лагов")
        c.update(i=r["i"], text=r["text"], snd=r["snd"], score=r.get("score", 0))
        rows[r["i"] - 1] = c
    plan_f.write_text(json.dumps(rows), encoding="utf-8")
    removed = 0
    for d in dirs:
        for name, j in mans[d].items():
            if j["i"] in bad_idx:
                (d / name).unlink(missing_ok=True)
                removed += 1
    print(f"план обновлён, удалено {removed} роликов — дособрать: python build_onestate3_uniq.py --seed {a.seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
