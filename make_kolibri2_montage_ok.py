#!/usr/bin/env python3
"""Колибри 2: покадровая проверка планов трейлерных нарезок (MONTAGES в build_kolibri2.py). Каждый кадр окна (родная частота фильма)
сравнивается с соседним: резкая смена картинки = склейка фильма. План обрезается внутрь своей сцены (±2 кадра от склеек), тёмные
кадры затемнения в начале/конце срезаются. → downloads/calibri2/montage_ok.json: {название: [[старт, макс. длина], …]}
и лист кадров итоговых окон (каждый кадр) для просмотра.
  python make_kolibri2_montage_ok.py <папка для листов>"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_kolibri2 as B  # noqa: E402

OUT = ROOT / "downloads" / "calibri2" / "montage_ok.json"
SW, SH = 96, 96
HD_CUT, FD_CUT, MARGIN = 0.38, 30.0, 2
# ручные решения после покадрового просмотра: (нарезка, старт из MONTAGES) → (старт, макс. длина) или None (выбросить)
OVERRIDE: dict[tuple[str, float], tuple[float, float] | None] = {
    ("endgame", 53.7): (53.78, 0.62),                                                                     # дальше силуэты тонут в тёмном дыму
    ("godzilla", 165.3): (165.30, 0.62), ("kong", 4.0): (4.0, 1.08), ("kong", 167.9): (167.9, 1.75),     # белый луч — одна сцена
    ("jaeger", 38.2): (38.2, 0.58), ("jaeger", 169.8): (169.8, 0.96),
    ("highway", 45.9): (45.9, 1.54), ("highway", 57.0): (57.0, 0.83), ("highway", 68.0): (68.0, 1.54),
    ("robots", 175.4): (175.4, 1.46), ("robots", 190.6): (190.6, 1.04),
    ("hulk", 51.3): (51.43, 0.71), ("hulk", 104.4): (104.57, 0.79), ("hulk", 63.5): (63.75, 0.5), ("hulk", 72.2): (72.2, 0.95),
    ("fury_road", 198.7): (198.7, 1.6), ("fury_road", 200.3): (200.3, 1.58),                            # огонь, не склейки
    ("mirror", 106.9): (106.9, 1.25), ("mirror", 119.6): (119.6, 1.29),
    ("man_of_steel", 81.2): (81.2, 0.7),                                                                  # без лежащего человека после взрыва
    ("inception", 177.3): (178.55, 0.50),                                                                 # кафе взрывается на 178.8
}


def window(fid: str, t0: float, t1: float) -> tuple[np.ndarray, float]:
    p = B.MOV / f"{fid}.mp4"
    fps = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True).stdout.strip()
    a, b = fps.split(",")[0].split("/")
    fps_v = float(a) / float(b)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", str(p), "-vf", f"crop=ih:ih,scale={SW}:{SH}",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, SH, SW).astype(np.float32), fps_v


def clamp(fid: str, t: float, d: float, strict: bool = True) -> tuple[float, float, list[float]]:
    pre, post = 1.0, d + 1.0
    t0 = max(0.0, t - pre)
    v, fps = window(fid, t0, t + post)
    n = len(v)
    sm = v.reshape(n, 24, 4, 24, 4).mean((2, 4))                                    # 24×24: мерцание огня и зерно усредняются
    dist = lambda i, j: float(np.abs(sm[j] - sm[i]).mean())                        # noqa: E731
    fd = np.array([dist(i, i + 1) for i in range(n - 1)])
    hist = [np.histogram(f, bins=16, range=(0, 255))[0] / f.size for f in v]
    hd = np.array([np.abs(hist[i + 1] - hist[i]).sum() for i in range(n - 1)])
    cuts = []
    for i in range(n - 1):                                                          # кадр i+1 — первый кадр новой сцены
        loc = np.median(np.r_[fd[max(0, i - 4):i], fd[i + 1:i + 5]]) if n > 2 else 0
        jump = fd[i] > max(12.0, 2.5 * loc) or (hd[i] > 0.5 and fd[i] > max(8.0, 2.0 * loc))
        if not jump:
            continue
        back = [dist(i, j) for j in (i + 2, i + 3) if j < n]                       # вспышка: через 1–2 кадра картинка возвращается
        if back and min(back) < 0.5 * fd[i]:
            continue
        cuts.append(i + 1)
    if strict:                                                                      # + чувствительный детектор (ловит и огонь — потом ручная проверка)
        fd96 = np.abs(np.diff(v, axis=0)).mean((1, 2))
        cuts = sorted(set(cuts) | {i + 1 for i in range(n - 1) if hd[i] > HD_CUT or fd96[i] > FD_CUT})
    i_t = int(round((t - t0) * fps))
    i_ref = min(n - 1, i_t + int(0.15 * fps))
    lo = max([c for c in cuts if c <= i_ref], default=0)
    hi = min([c for c in cuts if c > i_ref], default=n)
    s = max(i_t, lo + MARGIN if lo else i_t)
    e = min(int(round((t + d + 0.25 - t0) * fps)), hi - MARGIN)                    # +0,25 с — запас для сдвига (jit) в plan()
    lum = v.mean((1, 2))
    med = np.median(lum[s:e]) if e > s else 0
    while s < e and lum[s] < 0.45 * med:                                           # затемнение в начале
        s += 1
    while e > s and lum[e - 1] < 0.45 * med:
        e -= 1
    return round(t0 + s / fps, 3), round((e - s) / fps, 3), [round(t0 + c / fps, 2) for c in cuts]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sheets = Path(sys.argv[1])
    res = {}
    for name, fid, shots in B.MONTAGES:
        res[name] = []
        for t, d in shots:
            s, ln, cuts = clamp(fid, t, d)
            s2, ln2, _ = clamp(fid, t, d, strict=False)
            if (name, t) in OVERRIDE:
                ov = OVERRIDE[(name, t)]
                if ov is None:
                    print(f"{name:13s} {t:7.2f} — выброшен вручную", flush=True)
                    continue
                s, ln = ov
            res[name].append([s, ln])
            flag = "  <-- КОРОТКО" if ln < 0.5 else ""
            diff = f"   (мягкий: {s2:.3f} макс {ln2:.2f})" if abs(ln2 - ln) > 0.08 and (name, t) not in OVERRIDE else ""
            print(f"{name:13s} {t:7.2f}+{d:.2f} → {s:7.3f} макс {ln:.2f}{flag}{diff}", flush=True)
        print(f"{name:13s} сумма {sum(x[1] for x in res[name]):.2f}", flush=True)
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    T, C = 104, 26
    for gi in range(0, len(B.MONTAGES), 4):
        grp = B.MONTAGES[gi:gi + 4]
        rows = []
        for name, fid, _ in grp:
            for s, ln in res[name]:
                raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{s:.3f}", "-t", f"{ln:.3f}", "-i", str(B.MOV / f"{fid}.mp4"), "-vf",
                                      f"crop=ih:ih,scale={T}:{T}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
                k = len(raw) // (T * T * 3)
                rows.append((name, s, [Image.frombytes("RGB", (T, T), raw[i * T * T * 3:(i + 1) * T * T * 3]) for i in range(k)]))
        lines = sum((len(fr) + C - 1) // C for *_, fr in rows)
        im = Image.new("RGB", (80 + T * C, (T + 2) * lines), "black")
        dr = ImageDraw.Draw(im)
        y = 0
        for name, s, fr in rows:
            dr.text((2, y + 4), f"{name}\n{s:.2f}\n{len(fr)} к", fill=(255, 255, 255))
            for i, x in enumerate(fr):
                if i and i % C == 0:
                    y += T + 2
                im.paste(x, (80 + i % C * T, y))
            y += T + 2
        im.save(sheets / f"montage_ok_{gi // 4}.jpg", quality=84)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
