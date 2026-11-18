#!/usr/bin/env python3
"""
Раунд 4, вариант B (визуально другой): стереть вшитые заголовки 1346, чтобы кадр можно было зеркалить, а заголовок поставить заново
своим шрифтом (build_1346_r4.py --variant B). Вход — src_clean (без чужих призывов) или src; маска — буквы, белые во всём окне
времени, + прямоугольники эмодзи; заливка LaMa по кропу вокруг надписи. Выход 30 к/с без звука → downloads/1346/src_b.

  python clean_1346_titles.py --preview   # только листы масок, файлы не меняются
  python clean_1346_titles.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import warnings
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import clean_1346_cta as C  # noqa: E402

OUT = ROOT / "downloads" / "1346" / "src_b"
FPS = 30
# файл: (окно маски, область, раздутие, порог белого, не позже t, прямоугольники эмодзи)
CFG = {
    "Christmas Coloring Blanket with Markers.mp4": ((0.1, 8.9), (90, 250, 1000, 650), 11, 205, 9.1, [(585, 365, 680, 455), (280, 545, 370, 635)]),
    "Glowing Halloween Fog Cauldrons.mp4": ((0.2, 1.0), (130, 525, 950, 675), 10, 190, 1.37, [(740, 605, 825, 670)]),
    "GTA Money Stack Lamp.mp4": ((0.3, 10.0), (240, 295, 840, 470), 11, 200, 10.3, [(615, 375, 710, 470)]),
    "Light-Up Christmas Heel Boots.mp4": ((0.1, 9.2), (130, 170, 950, 350), 11, 205, 9.5, [(765, 245, 945, 350)]),
}


def source(name: str) -> Path:
    return C.OUT / name if (C.OUT / name).exists() else C.SRC / name


def build_mask(name: str):
    win, box, grow, thr, t_max, rects = CFG[name]
    p = source(name)
    core, m = C.mask_of(p, win, box, grow, thr)
    for x0, y0, x1, y1 in rects:
        m[y0:y1, x0:x1] = 255
    return p, core, m, thr, t_max


def preview(dest: Path) -> None:
    tiles = []
    for name in CFG:
        p, core, m, _, t_max = build_mask(name)
        w, h = C.size(p)
        b = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t_max * 0.5:.2f}", "-i", str(p), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True).stdout
        fr = np.frombuffer(b, np.uint8).reshape(h, w, 3).copy()
        fr[m > 0] = (fr[m > 0] * 0.3 + np.array([255, 0, 0]) * 0.7).astype(np.uint8)
        print(name[:20], "маска, % кадра:", round(float((m > 0).mean() * 100), 2), flush=True)
        tiles.append(Image.fromarray(fr).resize((432, 768)))
    s = Image.new("RGB", (432 * len(tiles), 768))
    for i, t in enumerate(tiles):
        s.paste(t, (i * 432, 0))
    s.save(dest, quality=86)


def clean(name: str, lama) -> None:
    p, core, m, thr, t_max = build_mask(name)
    w, h = C.size(p)
    ys, xs = np.where(m > 0)
    pad = 90
    x0, y0, x1, y1 = max(0, xs.min() - pad), max(0, ys.min() - pad), min(w, xs.max() + pad), min(h, ys.max() + pad)
    x1, y1 = x0 + ((x1 - x0) // 8) * 8, y0 + ((y1 - y0) // 8) * 8
    mc = Image.fromarray(m[y0:y1, x0:x1])
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(p), "-vf", f"fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-", "-an", "-c:v", "h264_nvenc",
                            "-preset", "p6", "-rc", "vbr", "-cq", "14", "-pix_fmt", "yuv420p", str(OUT / name)], stdin=subprocess.PIPE)
    sz, n, done = w * h * 3, 0, 0
    while True:
        buf = dec.stdout.read(sz)
        if len(buf) < sz:
            break
        fr = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        if n / FPS <= t_max:
            res = np.asarray(lama(Image.fromarray(fr[y0:y1, x0:x1]), mc))[: y1 - y0, : x1 - x0]
            fr = fr.copy()
            fr[y0:y1, x0:x1] = np.where(m[y0:y1, x0:x1, None] > 0, res, fr[y0:y1, x0:x1])
            done += 1
        enc.stdin.write(fr.tobytes())
        n += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()
    print(f"{name}: кадров {n}, залито {done}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    if a.preview:
        preview(a.preview)
        return 0
    from simple_lama_inpainting import SimpleLama
    lama = SimpleLama()
    for name in CFG:
        clean(name, lama)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
