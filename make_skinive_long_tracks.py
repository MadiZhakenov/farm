#!/usr/bin/env python3
"""Skinive 3/6 уникализация: длинные «ведущие» клипы родинок вместо 3-секундных окон. Трекер Лукаса–Канаде из
make_skinive3_moles (стартовые точки — те же проверенные окна), но на весь остаток клипа; наезд мягкий (Z 1.2),
родинка в центре кадра (0.5 W, 0.5 H) — дальше в сборщике у каждого ролика свой доп. зум/сдвиг/поворот и свой старт.
Пишет output/_work/skinive_overlay/long/<id>.mp4 + <id>.json (скорость пути по кадрам — где рука дёргается).

  python make_skinive_long_tracks.py [--sheet]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import make_skinive3_moles as M  # noqa: E402

OUT = ROOT / "output" / "_work" / "skinive_overlay" / "long"
W, H, FPS = 1080, 1920, 30
Z = 1.2
# (id, клип, старт, конец, x, y стартовой точки) — группы: c = IMG_6378 (кружки маркером, «??»), a = тату-рука
LONG = [
    ("c1", "IMG_6378", 2.6, 9.15, 0.48, 0.52),
    ("a1", "IMG_6381", 0.3, 7.10, 0.33, 0.57),
    ("a2", "IMG_6382", 0.5, 6.80, 0.33, 0.645),
    ("a3", "IMG_6382", 6.8, 12.0, 0.33, 0.56),
    ("p1", "IMG_6281", 0.2, 13.0, 0.30, 0.545),       # та же рука без маркера (мелкие родинки), skinive_3
]


def render(wid: str, clip: str, t0: float, t1: float, x0: float, y0: float) -> None:
    M.DUR = t1 - t0 - 0.1
    fr = M.frames(clip, t0)
    path = M.track(fr, x0, y0)
    cw, ch = round(W / Z / 2) * 2, round(H / Z / 2) * 2
    OUT.mkdir(parents=True, exist_ok=True)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
                            "-i", "-", "-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "14", "-g", "15",
                            "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                            str(OUT / f"{wid}.mp4")], stdin=subprocess.PIPE)
    for f, (px, py) in zip(fr, path):
        x = int(np.clip(px - cw / 2, 0, W - cw))
        y = int(np.clip(py - ch / 2, 0, H - ch))
        enc.stdin.write(cv2.resize(f[y:y + ch, x:x + cw], (W, H), interpolation=cv2.INTER_LANCZOS4).tobytes())
    enc.stdin.close()
    enc.wait()
    sp = np.r_[0, np.linalg.norm(np.diff(path, axis=0), axis=1)]           # px/кадр в исходнике
    (OUT / f"{wid}.json").write_text(json.dumps({"fps": FPS, "n": len(path), "speed": [round(float(v), 2) for v in sp]}))
    print(f"  {wid}: {len(path)} кадров, медиана скорости {np.median(sp):.1f}, макс {sp.max():.1f}", flush=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    only = sys.argv[1].split(",") if len(sys.argv) > 1 else None
    for w in LONG:
        if not only or w[0] in only:
            render(*w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
