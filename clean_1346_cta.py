#!/usr/bin/env python3
"""
Раунд 4 (docs/REPOST_HYPOTHESES.md): стереть из исходников 1346 чужие призывы — GTA «Link in bio», Heels «Comment HEELS for
the link», Water «Comment DIY for more info». Заголовки в начале роликов не трогаем.
Маска — буквы, которые остаются белыми во всём окне времени (минимум по кадрам) + раздутие на обводку/тень; заливка — LaMa
по кропу вокруг надписи, только в кадрах, где надпись видна. Выход 30 к/с без звука → downloads/1346/src_clean.

  python clean_1346_cta.py
"""

from __future__ import annotations

import subprocess
import sys
import warnings
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "downloads" / "1346" / "src"
OUT = ROOT / "downloads" / "1346" / "src_clean"
FPS = 30
# файл: (окно для маски, область надписи x0 y0 x1 y1, раздутие px, порог белого, не раньше t, доп. прямоугольник маски)
CFG = {
    "GTA Money Stack Lamp.mp4": ((13.3, 18.6), (240, 1690, 840, 1890), 11, 170, 12.9, (495, 1745, 585, 1830)),   # 🔗 серый — не попадает в белое
    "Light-Up Christmas Heel Boots.mp4": ((10.3, 13.5), (90, 110, 990, 430), 11, 175, 9.3, None),                 # раньше — заголовок, его не трогаем
    "Water Jug Cabinet Dispenser.mp4": ((6.8, 8.3), (150, 620, 570, 1040), 8, 170, 6.5, None),
}


def size(p: Path) -> tuple[int, int]:
    s = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                        str(p)], capture_output=True, text=True).stdout.strip().split(",")
    return int(s[0]), int(s[1])


def mask_of(p: Path, win: tuple[float, float], box: tuple[int, int, int, int], grow: int, thr: int) -> np.ndarray:
    w, h = size(p)
    b = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(win[0]), "-to", str(win[1]), "-i", str(p), "-vf", "fps=10", "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    fr = np.frombuffer(b, np.uint8).reshape(-1, h, w, 3)
    mn = fr.min(3).min(0)
    m = np.zeros((h, w), np.uint8)
    x0, y0, x1, y1 = box
    m[y0:y1, x0:x1] = (mn[y0:y1, x0:x1] > thr).astype(np.uint8) * 255
    num, lab, st, _ = cv2.connectedComponentsWithStats(m)
    for i in range(1, num):
        if st[i, cv2.CC_STAT_AREA] < 12:
            m[lab == i] = 0
    core = m.copy()
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    return core, cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))


def clean(name: str, lama) -> None:
    p = SRC / name
    (win, box, grow, thr, t_min, extra) = CFG[name]
    w, h = size(p)
    core, m = mask_of(p, win, box, grow, thr)
    if extra:
        m[extra[1]:extra[3], extra[0]:extra[2]] = 255
    cv2.imwrite(str(OUT / f"_mask_{p.stem}.png"), m)
    ys, xs = np.where(m > 0)
    pad = 90
    x0, y0, x1, y1 = max(0, xs.min() - pad), max(0, ys.min() - pad), min(w, xs.max() + pad), min(h, ys.max() + pad)
    x1 = x0 + ((x1 - x0) // 8) * 8
    y1 = y0 + ((y1 - y0) // 8) * 8
    mc = Image.fromarray(m[y0:y1, x0:x1])
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(p), "-vf", f"fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-",
                            "-an", "-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "14", "-pix_fmt", "yuv420p",
                            str(OUT / name)], stdin=subprocess.PIPE)
    sz, n, done, seen = w * h * 3, 0, 0, []
    frames = []
    while True:
        buf = dec.stdout.read(sz)
        if len(buf) < sz:
            break
        fr = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        frames.append(n)
        seen.append(float((fr.min(2)[core > 0] > thr - 20).mean()))
        n += 1
        vis = seen[-1] > 0.45 and n / FPS >= t_min
        if vis or (n / FPS >= win[0] and n / FPS <= win[1]):
            res = np.asarray(lama(Image.fromarray(fr[y0:y1, x0:x1]), mc))[: y1 - y0, : x1 - x0]
            fr = fr.copy()
            fr[y0:y1, x0:x1] = np.where(m[y0:y1, x0:x1, None] > 0, res, fr[y0:y1, x0:x1])
            done += 1
        enc.stdin.write(fr.tobytes())
    enc.stdin.close()
    enc.wait()
    dec.wait()
    first = next((i for i, v in enumerate(seen) if v > 0.45 and i / FPS >= t_min), -1)
    print(f"{name}: кадров {n}, залито {done}, надпись с {first / FPS:.2f} с", flush=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from simple_lama_inpainting import SimpleLama
    OUT.mkdir(parents=True, exist_ok=True)
    lama = SimpleLama()
    for name in CFG:
        clean(name, lama)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
