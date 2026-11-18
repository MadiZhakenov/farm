#!/usr/bin/env python3
"""Похожесть роликов внутри партии (и между партиями): по 3 кадра в секунду, dHash 16×16 (256 бит) по кадру в оттенках
серого. Пара кадров «узнаётся», если расстояние Хэмминга ≤ 40 из 256 (≈ одна и та же картинка после лёгкого цвета/зерна).
Для пары роликов A→B: доля кадров A, у которых в B есть узнаваемый кадр (с учётом зеркала тоже).
Печатает среднее, 95-й перцентиль и максимум по всем парам, и сколько пар выше 30 %.

  python measure_skinive_uniq.py output/skinive3_TT_150 [--vs output/skinive3_YT_150] [--limit 60]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np


FPS, S, THR = 3, 16, 40


_GPU = threading.BoundedSemaphore(3)          # до 3 потоков распаковывают на видеокарте, остальные — на процессоре


def hashes(v: Path) -> np.ndarray:
    # видеокарта + процессор вместе: поток берёт видеокарту, если свободно одно из 3 мест, иначе распаковывает процессором
    # (результат одинаковый: h264 распаковывается побитно так же, уменьшение — на процессоре)
    gpu = _GPU.acquire(blocking=False)
    try:
        hw = ["-hwaccel", "cuda"] if gpu else ["-threads", "2"]
        raw = subprocess.run(["ffmpeg", "-v", "error", *hw, "-i", str(v), "-vf", f"fps={FPS},scale={S + 1}:{S}:flags=area,format=gray",
                              "-f", "rawvideo", "-"], capture_output=True).stdout
    finally:
        if gpu:
            _GPU.release()
    if gpu and not raw:                                  # видеокарта занята (cuvidCreateDecoder не создался) — процессором
        raw = subprocess.run(["ffmpeg", "-v", "error", "-threads", "2", "-i", str(v), "-vf",
                              f"fps={FPS},scale={S + 1}:{S}:flags=area,format=gray", "-f", "rawvideo", "-"],
                             capture_output=True).stdout
    if not raw:
        raise RuntimeError(f"{v}: не распаковался")
    fr = np.frombuffer(raw, np.uint8).reshape(-1, S, S + 1).astype(np.int16)
    h = fr[:, :, 1:] > fr[:, :, :-1]
    hm = fr[:, :, ::-1][:, :, 1:] > fr[:, :, ::-1][:, :, :-1]       # зеркальный кадр
    return np.stack([h.reshape(len(fr), -1), hm.reshape(len(fr), -1)], 1)


def match(a: np.ndarray, b: np.ndarray) -> float:
    d = (a[:, None, 0, :] != b[None, :, :, :].reshape(1, -1, a.shape[-1])).sum(-1)   # кадры A × (кадры B, B-зеркало)
    return float((d.min(1) <= THR).mean())


def load(folder: Path, limit: int) -> dict:
    vids = sorted(folder.glob("*.mp4"))[:limit]
    with ThreadPoolExecutor(6) as ex:
        return dict(zip([v.name for v in vids], ex.map(hashes, vids)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--vs", type=Path)
    ap.add_argument("--limit", type=int, default=60)
    a = ap.parse_args()
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    A = load(a.folder, a.limit)
    B = load(a.vs, a.limit) if a.vs else A
    vals = []
    for na, ha in A.items():
        for nb, hb in B.items():
            if a.vs is None and na >= nb:
                continue
            vals.append(max(match(ha, hb), match(hb, ha)))
    v = np.array(vals)
    what = f"{a.folder.name} × {a.vs.name}" if a.vs else a.folder.name
    print(f"{what}: {len(A)}×{len(B)} роликов, пар {len(v)} | узнаваемых кадров: среднее {v.mean() * 100:.1f} %, "
          f"95-й перц. {np.percentile(v, 95) * 100:.1f} %, макс {v.max() * 100:.1f} % | пар > 30 %: {(v > 0.3).mean() * 100:.1f} %")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
