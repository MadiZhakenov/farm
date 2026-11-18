#!/usr/bin/env python3
"""Стабилизированные «ведущие» клипы родинок для skinive (юзер 2026-11-13: «почему рука дрожит или это видео»).

Замер 13.11: старые треки (make_skinive_long_tracks.py) трясутся на 35–45 % сильнее исходника. Окно кадра там
идёт по сглаженному пути Лукаса–Канаде (тряска рук остаётся в кадре) и встаёт в целые пиксели (ступеньки ±0.5 px,
после зума — заметно). Здесь путь окна = точные покадровые сдвиги участка вокруг родинки (фазовая корреляция,
доли пикселя — гасит тряску рук) + медленная поправка к пути Лукаса–Канаде (родинка остаётся в центре, без
дрейфа). Окно вырезается с точностью до долей пикселя (cv2.getRectSubPix). Те же клипы и отрезки, что у старых
треков → output/_work/skinive_overlay/long_stab/<id>.mp4 (+ .json).

  python make_skinive_long_tracks_stab.py [c1 a1 a2 a3]
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import make_skinive3_moles as M  # noqa: E402
import make_skinive_long_tracks as LT  # noqa: E402

OUT = ROOT / "output" / "_work" / "skinive_overlay" / "long_stab"
W, H, FPS = 1080, 1920, 30
PATCH = 384                                            # участок вокруг родинки для фазовой корреляции


def gauss(x: np.ndarray, sigma: float) -> np.ndarray:
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.pad(x, ((r, r), (0, 0)), mode="edge")
    return np.stack([np.convolve(pad[:, i], k, mode="valid") for i in range(x.shape[1])], 1)


def stab_path(fr: np.ndarray, lk: np.ndarray) -> np.ndarray:
    g = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in fr]
    win = cv2.createHanningWindow((PATCH, PATCH), cv2.CV_32F)
    pc = [lk[0].astype(np.float64)]
    for i in range(1, len(g)):
        cx, cy = pc[-1]
        x = int(np.clip(cx - PATCH / 2, 0, W - PATCH))
        y = int(np.clip(cy - PATCH / 2, 0, H - PATCH))
        a = g[i - 1][y:y + PATCH, x:x + PATCH]
        b = g[i][y:y + PATCH, x:x + PATCH]
        (dx, dy), resp = cv2.phaseCorrelate(a, b, win)
        lx, ly = lk[i] - lk[i - 1]
        # не нашлось или «ложный пик» (сдвиг далеко от шага Лукаса–Канаде) — берём шаг LK: иначе окно дёргалось
        # на 40–50 px за кадр (a1 кадр 143, a2 кадр 92 — «срывы», 13.11)
        if resp < 0.05 or abs(dx - lx) > 6 or abs(dy - ly) > 6:
            dx, dy = lx, ly
        pc.append(pc[-1] + (dx, dy))
    pc = np.array(pc)
    return pc + gauss(lk - pc, 10.0)                     # точные мелкие сдвиги + медленная привязка к пути LK


def render(wid: str, clip: str, t0: float, t1: float, x0: float, y0: float) -> None:
    M.DUR = t1 - t0 - 0.1
    fr = M.frames(clip, t0)
    lk = M.track(fr, x0, y0).astype(np.float64)
    path = stab_path(fr, lk)
    cw, ch = round(W / LT.Z / 2) * 2, round(H / LT.Z / 2) * 2
    OUT.mkdir(parents=True, exist_ok=True)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "14",
                            "-g", "2", "-bf", "0", "-pix_fmt", "yuv420p", "-bsf:v",
                            "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1",
                            str(OUT / f"{wid}.mp4")], stdin=subprocess.PIPE)
    for f, (px, py) in zip(fr, path):
        cx = float(np.clip(px, cw / 2, W - cw / 2))
        cy = float(np.clip(py, ch / 2, H - ch / 2))
        crop = cv2.getRectSubPix(f, (cw, ch), (cx, cy))
        enc.stdin.write(cv2.resize(crop, (W, H), interpolation=cv2.INTER_LANCZOS4).tobytes())
    enc.stdin.close()
    enc.wait()
    src_json = LT.OUT / f"{wid}.json"
    if src_json.exists():
        shutil.copy(src_json, OUT / f"{wid}.json")
    print(f"  {wid}: {len(fr)} кадров → {OUT / (wid + '.mp4')}", flush=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    want = set(sys.argv[1:]) or {"c1", "a1", "a2", "a3"}
    for wid, clip, t0, t1, x0, y0 in LT.LONG:
        if wid in want:
            render(wid, clip, t0, t1, x0, y0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
