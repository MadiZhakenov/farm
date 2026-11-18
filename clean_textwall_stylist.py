#!/usr/bin/env python3
"""Текстволл «стилист» (ID 1): стереть вшитые подписи авторов в исходниках (downloads/textwall_stylist/src) перед нашим текстом.
  01 ashmanmolly — «What I wore as a / 25 year old / Fashion stylist» по центру (на человеке) весь ролик;
  02 bossymarie — «"what's luxury?" / no logos» по центру весь ролик;
  03, 05 ronhiree — «The stylist / The outfits» сверху на стене весь ролик;
  04 lilrotini — «wearing vs / styling» сверху только до 6,2 с → берём с 6,4 с, без заливки.
Маска: на человеке — пиксели, светлые почти во всех кадрах (буквы), раздутые под тень; на стене — весь прямоугольник
подписи. Заливка LaMa (simple-lama-inpainting) по кропу вокруг подписи. Всё в 30 к/с → downloads/textwall_stylist/clean/*.mp4
(без звука, звук берётся из исходника).
  python clean_textwall_stylist.py
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
D = ROOT / "downloads" / "textwall_stylist"
SRC, OUT = D / "src", D / "clean"
W, H, FPS = 1080, 1920, 30
# клип: (бокс подписи x0, y0, x1, y1 в 1080×1920, режим маски, кроп для LaMa y0, y1, начало, конец)
CLIPS = {
    "batch2_01_ashmanmolly_7631641876743064834": ((400, 880, 690, 1025), "text", (690, 1210), 0.0, None),
    "batch2_02_bossymarie_7610778660269722902": ((380, 775, 690, 905), "text", (580, 1100), 0.0, None),
    "batch2_03_ronhiree_7416339063420046624": ((395, 290, 685, 368), "box", (120, 540), 0.0, None),
    "batch2_04_lilrotini_7479940826311904558": (None, None, None, 6.4, None),
    "batch2_05_ronhiree_7685748672457346336": ((395, 290, 685, 368), "box", (120, 540), 0.0, None),
}


def frames(p: Path, ss: float = 0.0):
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", f"{ss}"] if ss else []) + ["-i", str(p), "-vf", f"fps={FPS},scale={W}:{H}",
                                                                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    dec = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    sz = W * H * 3
    while True:
        b = dec.stdout.read(sz)
        if len(b) < sz:
            break
        yield np.frombuffer(b, np.uint8).reshape(H, W, 3)
    dec.wait()


def text_mask(p: Path, box: tuple) -> np.ndarray:
    """Пиксели бокса, светлые в ≥ 85 % кадров (буквы стоят на месте, человек под ними двигается) + тень."""
    x0, y0, x1, y1 = box
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vf", f"fps=5,scale={W}:{H},crop={x1 - x0}:{y1 - y0}:{x0}:{y0}",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, y1 - y0, x1 - x0)
    m = (np.percentile(v, 15, axis=0) > 200).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    full = np.zeros((H, W), np.uint8)
    full[y0:y1, x0:x1] = cv2.dilate(m, np.ones((15, 15), np.uint8)) * 255
    return full


def main() -> int:
    from simple_lama_inpainting import SimpleLama
    lama = SimpleLama()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (box, mode, crop, ss, _) in CLIPS.items():
        p = SRC / f"{name}.mp4"
        dest = OUT / f"{name}.mp4"
        enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                                "-i", "-", "-an", "-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "14", "-pix_fmt", "yuv420p",
                                str(dest)], stdin=subprocess.PIPE)
        if box is None:
            m = None
        elif mode == "text":
            m = text_mask(p, box)
        else:
            m = np.zeros((H, W), np.uint8)
            x0, y0, x1, y1 = box
            m[y0:y1, x0:x1] = 255
        if m is not None:
            cv2.imwrite(str(OUT / f"{name}_mask.png"), m)
            a, b = crop
            mc = Image.fromarray(m[a:b])
        n = 0
        for fr in frames(p, ss):
            if m is not None:
                res = np.asarray(lama(Image.fromarray(fr[a:b]), mc))[: b - a, :W]
                fr = fr.copy()
                fr[a:b] = np.where(m[a:b, :, None] > 0, res, fr[a:b])
            enc.stdin.write(fr.tobytes())
            n += 1
        enc.stdin.close()
        enc.wait()
        print(name[:9], "кадров", n, "маска", int((m > 0).sum()) if m is not None else 0, "→", dest.name, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
