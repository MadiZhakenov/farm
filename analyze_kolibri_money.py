#!/usr/bin/env python3
"""
Kolibri ≤ 7 с: библиотека кусков под структуру ТЗ (фидбек 2026-11-10: «структура не сохранилась»).
По кадрам исходников (2 к/с, 540×960) ищем:
  - «деньги в мире»: крупные белые числа с тёмной обводкой (3.77M, 220.15M, 657.43ad…) вне интерфейса — накопление денег;
  - «апгрейд»: открытая панель улучшений с зелёной кнопкой UPGRADE (без экрана статистики с оранжевыми полосами).
Выход downloads/calibri/lib7.json: money (окна 4 с — хук), world (окна 2.4 с с числами — рост суммы), panel (окна 2.4 с — апгрейд).

  python analyze_kolibri_money.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
D = ROOT / "downloads" / "calibri"
SRC = D / "src"
FILES = {"IBT_bank-03.mp4": (32, 610), "IBT_bank-06.mp4": (18, 860), "IBT_bank-11.mp4": (12, 690), "IBT_new-account.mp4.mp4": (185, 820)}
W, H = 540, 960


def numbers(f: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Крупные белые числа с тёмной обводкой вне интерфейса."""
    white = (f.min(2) > 218).astype(np.uint8)
    dark = (f.max(2) < 75).astype(np.uint8)
    outl = white & cv2.dilate(dark, np.ones((5, 5), np.uint8))
    m = cv2.dilate(outl, np.ones((7, 17), np.uint8))
    m[: int(H * .15)] = 0
    m[int(H * .86):] = 0
    m[:, int(W * .86):] = 0
    m[:, : int(W * .08)] = 0
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if 24 <= h <= 95 and w >= 1.8 * h and w <= 330:
            fill = white[y:y + h, x:x + w].mean()
            if .18 <= fill <= .65:
                out.append((int(x), int(y), int(w), int(h)))
    return out


def panel_ok(f: np.ndarray) -> bool:
    r, g, b = (f[..., k].astype(np.int16) for k in range(3))
    btn = ((g > 165) & (r < 120) & (b < 150))[int(H * .55):int(H * .74), int(W * .58):int(W * .98)].mean()
    orange = ((r > 200) & (g > 120) & (g < 205) & (b < 100))[int(H * .3):int(H * .85)].mean()
    navy = ((b > r + 15) & (f.max(2) < 95))[int(H * .45):int(H * .9)].mean()
    return bool(btn > .03 and orange < .02 and navy > .3)


def scan(name: str) -> tuple[str, list]:
    a, b = FILES[name]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-threads", "2", "-ss", str(a), "-to", str(b), "-i", str(SRC / name),
                          "-vf", f"fps=2,scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
    rows = []
    for i, f in enumerate(v):
        navy = ((f[..., 2].astype(np.int16) > f[..., 0].astype(np.int16) + 15) & (f.max(2) < 95))[int(H * .45):int(H * .9)].mean()
        lum = f.mean()
        world = bool(navy < .12 and lum > 68)
        nums = numbers(f) if world else []
        rows.append(dict(t=round(a + i / 2, 1), world=world, nums=nums, panel=panel_ok(f)))
    print(name, len(rows), "кадров;", sum(1 for r in rows if r["nums"]), "с числами;", sum(r["panel"] for r in rows), "панелей", flush=True)
    return name, rows


def windows(rows: list, k: int, need, gap: float) -> list:
    out = []
    for i in range(len(rows) - k):
        seg = rows[i:i + k]
        s = need(seg)
        if s is not None:
            out.append((s, rows[i]["t"], seg))
    out.sort(key=lambda z: -z[0])
    kept = []
    for s, t, seg in out:
        if all(abs(t - q["t"]) >= gap for q in kept):
            boxes = [b for r in seg for b in r["nums"]]
            cx = float(np.mean([(x + w / 2) / W for x, y, w, h in boxes])) if boxes else .5
            cy = float(np.mean([(y + h / 2) / H for x, y, w, h in boxes])) if boxes else .55
            kept.append(dict(t=t, score=round(float(s), 2), cx=round(cx, 3), cy=round(cy, 3)))
    return sorted(kept, key=lambda q: q["t"])


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with ThreadPoolExecutor(4) as ex:
        res = dict(ex.map(scan, FILES))
    (D / "scan7.json").write_text(json.dumps(res), encoding="utf-8")
    lib = {"money": {}, "world": {}, "panel": {}}
    for name, rows in res.items():
        lib["money"][name] = windows(rows, 8, lambda s: (sum(bool(r["nums"]) for r in s) + .01 * sum(w * h for r in s for _, _, w, h in r["nums"]) / 400)
                                     if all(r["world"] for r in s) and sum(bool(r["nums"]) for r in s) >= 3 else None, 3.0)
        lib["world"][name] = windows(rows, 5, lambda s: sum(bool(r["nums"]) for r in s) if all(r["world"] for r in s) and sum(bool(r["nums"]) for r in s) >= 2 else None, 2.5)
        lib["panel"][name] = windows(rows, 5, lambda s: 1.0 if all(r["panel"] for r in s) else None, 2.5)
        print(name[:22], "хук", len(lib["money"][name]), "мир", len(lib["world"][name]), "апгрейд", len(lib["panel"][name]), flush=True)
    (D / "lib7.json").write_text(json.dumps(lib), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
