#!/usr/bin/env python3
"""
skinive_3: крупные планы родинок (ТЗ «родинка крупно 3 сек»). Руки в исходниках двигаются, поэтому родинку
(круг маркером / сама родинка) ведём по кадрам: шаблон 240×240 вокруг стартовой точки → cv2.matchTemplate в окне
±90 px на каждом кадре (шаблон плавно обновляется), путь сглаживается, кроп 1080/Z × 1920/Z вокруг точки (родинка на
0.55 H — ниже подписи сверху) → 1080×1920. Каждое окно один раз в кэш output/_work/skinive3/moles/<id>.mp4 (3.4 с).

  python make_skinive3_moles.py            # все окна
  python make_skinive3_moles.py --sheet    # + контакт-листы для проверки
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
PROXY = ROOT / "downloads" / "skinive3" / "proxy"
OUT = ROOT / "output" / "_work" / "skinive3" / "moles"
W, H, FPS, DUR = 1080, 1920, 30, 3.1
Z = 1.6                                   # наезд (крупно), исходник уже 1080p — лёгкое смягчение допустимо
AT_Y = 0.55                               # где на кадре стоит родинка (по высоте)
# (id, клип, старт, x, y стартовой точки в долях кадра)
WINDOWS = [   # только спокойные участки (без рывков руки), стартовые точки — центр группы родинок, по сетке кадра
    ("c1", "IMG_6378", 2.6, 0.48, 0.52),  # обведённые маркером родинки и «??»
    ("c3", "IMG_6378", 6.0, 0.55, 0.55),
    ("a1", "IMG_6381", 0.3, 0.33, 0.57),  # тату-рука, родинка в круге со стрелкой
    ("a2", "IMG_6382", 0.5, 0.33, 0.645),
    ("a3", "IMG_6382", 6.8, 0.33, 0.56),
    ("p1", "IMG_6281", 0.2, 0.30, 0.545),  # та же рука, что на фото в приложении
    ("p3", "IMG_6281", 3.6, 0.31, 0.55),
]
T, SR = 380, 110                          # шаблон крупнее (с маленьким сползал по коже), окно поиска ±110
ZP = 2.0                                  # p-окна: родинка мелкая — наезд сильнее


def frames(clip: str, t0: float) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{DUR + 0.1:.3f}", "-i", str(PROXY / f"{clip}.mp4"),
                          "-vf", f"fps={FPS}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)


def track(fr: np.ndarray, x0: float, y0: float) -> np.ndarray:
    """Оптический поток Лукаса–Канаде по угловым точкам в квадрате 420 px вокруг родинки (штрихи маркера, сами
    родинки): центр сдвигается на медианное смещение точек; точки пересобираются, если их стало мало."""
    g = [cv2.cvtColor(cv2.resize(f, (W // 2, H // 2)), cv2.COLOR_BGR2GRAY) for f in fr]
    cx, cy = x0 * W / 2, y0 * H / 2
    R = 105                                         # полуразмер квадрата (в половинном масштабе)

    def feats(img, x, y):
        m = np.zeros_like(img)
        cv2.rectangle(m, (int(x - R), int(y - R)), (int(x + R), int(y + R)), 255, -1)
        return cv2.goodFeaturesToTrack(img, 60, 0.01, 5, mask=m)
    pts = feats(g[0], cx, cy)
    path = [(cx, cy)]
    lk = dict(winSize=(25, 25), maxLevel=3, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    for a_, b_ in zip(g[:-1], g[1:]):
        if pts is None or len(pts) < 8:
            pts = feats(a_, cx, cy)
        if pts is None:
            path.append((cx, cy)); continue
        nxt, st, _ = cv2.calcOpticalFlowPyrLK(a_, b_, pts, None, **lk)
        ok = st.reshape(-1) == 1
        if ok.sum() >= 4:
            d = np.median((nxt[ok] - pts[ok]).reshape(-1, 2), 0)
            cx, cy = cx + d[0], cy + d[1]
            pts = nxt[ok].reshape(-1, 1, 2)
        path.append((cx, cy))
    p_ = np.array(path, np.float32) * 2
    k = 7
    pad = np.pad(p_, ((k // 2, k // 2), (0, 0)), mode="edge")
    return np.stack([np.convolve(pad[:, i], np.ones(k) / k, mode="valid") for i in range(2)], 1)


def render(wid: str, clip: str, t0: float, x0: float, y0: float) -> Path:
    fr = frames(clip, t0)
    path = track(fr, x0, y0)
    z = ZP if wid.startswith("p") else Z
    cw, ch = round(W / z / 2) * 2, round(H / z / 2) * 2
    dest = OUT / f"{wid}.mp4"
    OUT.mkdir(parents=True, exist_ok=True)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
                            "-i", "-", "-t", f"{DUR:.3f}", "-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "14",
                            "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                            str(dest)], stdin=subprocess.PIPE)
    for f, (px, py) in zip(fr, path):
        x = int(np.clip(px - cw / 2, 0, W - cw))
        y = int(np.clip(py - ch * AT_Y, 0, H - ch))
        enc.stdin.write(cv2.resize(f[y:y + ch, x:x + cw], (W, H), interpolation=cv2.INTER_LANCZOS4).tobytes())
    enc.stdin.close()
    enc.wait()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--sheet", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sel = [w for w in WINDOWS if not a.only or w[0] in a.only.split(",")]
    for w in sel:
        print("  ", render(*w).name, flush=True)
    if a.sheet:
        from PIL import Image, ImageDraw
        rows = []
        for w in sel:
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(OUT / f"{w[0]}.mp4"), "-vf", "fps=2.5,scale=135:240",
                                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
            n = len(raw) // (135 * 240 * 3)
            r = Image.new("RGB", (135 * 9, 240), "white")
            for i in range(min(n, 9)):
                r.paste(Image.frombuffer("RGB", (135, 240), raw[i * 135 * 240 * 3:(i + 1) * 135 * 240 * 3]), (135 * i, 0))
            ImageDraw.Draw(r).text((4, 4), w[0], fill=(255, 0, 0))
            rows.append(r)
        s = Image.new("RGB", (135 * 9, 240 * len(rows)))
        for i, r in enumerate(rows):
            s.paste(r, (0, 240 * i))
        s.save(OUT / "_sheet.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
