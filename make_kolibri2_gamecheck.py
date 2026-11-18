#!/usr/bin/env python3
"""Колибри 2: покадровая проверка сырых записей игры (downloads/calibri/src), 30 кадр/с. Кадр «чистый», если это вид мира:
есть яркая зелёная кнопка BOOST внизу, верхняя полоса и нижняя панель совпадают со скользящей медианой (±1,5 с) — так ловятся
Пункт управления iPhone, всплывающие окна и затемнения, панели улучшений, загрузки; плюс нет резкой смены всей картинки (склейка).
Плохие кадры расширяются на ±0,3 с; → downloads/calibri2/game_ok.json: {файл: [[от, до], …]} чистых интервалов ≥ 1 с.
  python make_kolibri2_gamecheck.py            # анализ (≈ 1–2 мин на файл)
  python make_kolibri2_gamecheck.py --stats    # распределения признаков по уже сохранённым данным
  python make_kolibri2_gamecheck.py --pool     # → downloads/calibri2/game_pool.json (куски для build_kolibri2.py)"""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "downloads" / "calibri" / "src"
OUT = ROOT / "downloads" / "calibri2" / "game_ok.json"
WORK = ROOT / "output" / "_work" / "kolibri2"
FILES = ["IBT_bank-03.mp4", "IBT_bank-06.mp4", "IBT_bank-11.mp4", "IBT_new-account.mp4.mp4"]
FPS_A, SW, SH = 30, 54, 96
BOOST = (slice(88, 94), slice(20, 34))          # кнопка BOOST в кадре 54×96
TOP, BOT = slice(0, 7), slice(85, 96)
BOOST_MIN, DLOC_MAX, FDIFF_MAX, PAD = 0.45, 14.0, 40.0, 0.3


def frames(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={FPS_A},scale={SW}:{SH}:flags=area", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, SH, SW, 3)


def boost_frac(v: np.ndarray, region=BOOST) -> np.ndarray:
    r = v[:, region[0], region[1]].astype(np.int16)
    g = (r[..., 1] > 150) & (r[..., 1] - r[..., 0] > 55) & (r[..., 1] - r[..., 2] > 25)
    return g.mean((1, 2))


def features(v: np.ndarray) -> dict[str, np.ndarray]:
    n = len(v)
    st = np.concatenate([v[:, TOP], v[:, BOT]], axis=1).astype(np.float32).mean(3)       # полосы интерфейса, серые
    half = int(1.5 * FPS_A)
    dloc = np.zeros(n, np.float32)
    for i in range(0, n, 5):                                                            # медиана окна ±1,5 с, шаг 5 кадров
        a, b = max(0, i - half), min(n, i + half + 1)
        med = np.median(st[a:b:3], axis=0)
        j1 = min(n, i + 5)
        dloc[i:j1] = np.abs(st[i:j1] - med[None]).mean((1, 2))
    g = v.astype(np.float32).mean(3)
    fd = np.r_[0, np.abs(np.diff(g, axis=0)).mean((1, 2))]
    return {"boost": boost_frac(v), "dloc": dloc, "fdiff": fd.astype(np.float32), "lum": g.mean((1, 2))}


def good_mask(ft: dict[str, np.ndarray]) -> np.ndarray:
    bad = (ft["boost"] < BOOST_MIN) | (ft["dloc"] > DLOC_MAX) | (ft["fdiff"] > FDIFF_MAX)
    k = int(PAD * FPS_A)
    bad = np.convolve(bad.astype(np.int32), np.ones(2 * k + 1, np.int32), "same") > 0
    return ~bad


def intervals(good: np.ndarray, min_len: float = 1.0) -> list[list[float]]:
    out, start = [], None
    for i, ok in enumerate(np.r_[good, False]):
        if ok and start is None:
            start = i
        elif not ok and start is not None:
            if (i - start) / FPS_A >= min_len:
                out.append([round(start / FPS_A, 3), round((i - 1) / FPS_A, 3)])
            start = None
    return out


def load_ok() -> dict[str, list[list[float]]]:
    return json.loads(OUT.read_text(encoding="utf-8"))["good"]


def is_clean(ok: dict[str, list[list[float]]], name: str, t0: float, t1: float) -> bool:
    return any(a <= t0 and t1 <= b for a, b in ok[name])


POOL = ROOT / "downloads" / "calibri2" / "game_pool.json"
POOL_MIN, POOL_MAX, POOL_STEP = 2.0, 4.0, 2.0                 # куски исходника: 2–4 с (на 1,25× → 1,6–3,2 с в ролике)


def build_pool() -> list[dict]:
    """Куски мира из чистых интервалов: старт каждые 2 с, длина до 4 с, всё внутри интервала (с отступом 0,1 с)."""
    ok = load_ok()
    pool = []
    for f in FILES:
        ft = dict(np.load(WORK / f"gamecheck_{f[:12]}.npz"))
        for a, b in ok[f]:
            t = a + 0.1
            while t + POOL_MIN <= b - 0.1:
                ln = round(min(POOL_MAX, b - 0.1 - t), 3)
                i0, i1 = int(t * FPS_A), int((t + ln) * FPS_A)
                pool.append(dict(file=f, start=round(t, 3), max_src=ln, motion=round(float(ft["fdiff"][i0:i1].mean()), 2)))
                t += POOL_STEP
    POOL.write_text(json.dumps(pool, indent=0), encoding="utf-8")
    return pool


def check_frames(v: np.ndarray) -> np.ndarray:
    """Проверка готовых кадров игры (54×96 RGB): видна кнопка BOOST и полосы интерфейса стабильны. → маска плохих кадров."""
    ft = features(v)
    return (ft["boost"] < BOOST_MIN) | (ft["dloc"] > DLOC_MAX) | (ft["fdiff"] > FDIFF_MAX)


def analyse(f: str) -> tuple[str, dict]:
    ft = features(frames(SRC / f))
    np.savez_compressed(WORK / f"gamecheck_{f[:12]}.npz", **ft)
    return f, ft


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    WORK.mkdir(parents=True, exist_ok=True)
    if "--pool" in sys.argv:
        pool = build_pool()
        for f in FILES:
            print(f, "кусков", sum(1 for p in pool if p["file"] == f))
        return 0
    if "--stats" in sys.argv:
        fts = {f: dict(np.load(WORK / f"gamecheck_{f[:12]}.npz")) for f in FILES}
    else:
        with ThreadPoolExecutor(4) as ex:
            fts = dict(ex.map(analyse, FILES))
    res = {}
    for f in FILES:
        ft = fts[f]
        good = good_mask(ft)
        res[f] = intervals(good)
        print(f, "кадров", len(good), "чистых %.0f%%" % (100 * good.mean()), "интервалов", len(res[f]),
              "| boost p5/50", np.percentile(ft["boost"], [5, 50]).round(2), "dloc p50/95/99", np.percentile(ft["dloc"], [50, 95, 99]).round(1),
              "fdiff p99", np.percentile(ft["fdiff"], 99).round(1), flush=True)
    OUT.write_text(json.dumps({"good": res, "fps": FPS_A, "boost_min": BOOST_MIN, "dloc_max": DLOC_MAX, "fdiff_max": FDIFF_MAX, "pad": PAD},
                              indent=0), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
