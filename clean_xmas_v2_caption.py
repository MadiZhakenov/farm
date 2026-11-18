#!/usr/bin/env python3
"""
V2 (DdGwGMEx-Uj): стереть вшитую нижнюю подпись «DO NOT show this to a Christmas-aholic😱🤫…» (0–9.3 с),
чтобы заголовок можно было поставить СВЕРХУ, а субтитры — внизу (правило юзера 2026-11-05: «тайтл всегда сверху,
субт внизу»). Маска — статичные белые буквы (≥60 % кадров), раздутая на 10 px (чёрная обводка и тень) + эмодзи;
заливка — LaMa (simple-lama-inpainting, big-lama) по кропу вокруг полосы. После 9.3 с подписи нет — кадры как есть.

  python clean_xmas_v2_caption.py   → downloads/xmas_proj/src_clean/DdGwGMEx-Uj.mp4 (без звука)
"""

from __future__ import annotations

import subprocess
import warnings
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "downloads" / "xmas_proj" / "src" / "DdGwGMEx-Uj.mp4"
MASK = ROOT / "downloads" / "xmas_proj" / "v2_caption_mask.png"
OUT = ROOT / "downloads" / "xmas_proj" / "src_clean" / "DdGwGMEx-Uj.mp4"
W, H, FPS = 720, 1280, 30
UNTIL = 9.40                       # подпись видна до ~9.3 с
CROP = (700, 1100)                 # контекст для LaMa по высоте
SPECK_T = (4.0, 5.2)               # LaMa оставляет тёмную точку на тыльной стороне ладони (рука на коробке)


def fix_specks(fr: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Тёмные пятнышки внутри маски, окружённые кожей: темнее локальной медианы на 28+ → cv2.inpaint (Telea)."""
    x = fr.astype(np.int16)
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    skin = ((r > 150) & (r - g > 12) & (r - b > 20)).astype(np.uint8)
    skin_frac = cv2.blur(skin.astype(np.float32), (31, 31))
    lum = fr.mean(2).astype(np.float32)
    med = cv2.medianBlur(fr, 21).mean(2).astype(np.float32)
    speck = (np.abs(lum - med) > 14) & (m > 0) & (skin_frac > 0.55)
    num, lab, st, _ = cv2.connectedComponentsWithStats(speck.astype(np.uint8))
    keep = np.zeros_like(skin)
    for i in range(1, num):
        if 3 <= st[i, cv2.CC_STAT_AREA] <= 1500:
            keep[lab == i] = 1
    if not keep.any():
        return fr
    keep = cv2.dilate(keep, np.ones((13, 13), np.uint8))
    return cv2.inpaint(np.ascontiguousarray(fr), keep * 255, 6, cv2.INPAINT_TELEA)


def main() -> int:
    from simple_lama_inpainting import SimpleLama
    lama = SimpleLama()
    m = cv2.imread(str(MASK), 0)
    a, b = CROP
    mc = Image.fromarray(m[a:b])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(SRC), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-an", "-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr",
                            "-cq", "14", "-pix_fmt", "yuv420p", str(OUT)], stdin=subprocess.PIPE)
    n = 0
    sz = W * H * 3
    while True:
        buf = dec.stdout.read(sz)
        if len(buf) < sz:
            break
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        if n / FPS <= UNTIL:
            res = np.asarray(lama(Image.fromarray(fr[a:b]), mc))[: b - a, :W]
            fr = fr.copy()
            fr[a:b] = np.where(m[a:b, :, None] > 0, res, fr[a:b])
            if SPECK_T[0] <= n / FPS <= SPECK_T[1]:
                fr = fix_specks(fr, m)
        enc.stdin.write(fr.tobytes())
        n += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()
    print(f"кадров {n} → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
