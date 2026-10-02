#!/usr/bin/env python3
"""
Кадры для каруселей из видео: в каждом окне берётся самый резкий кадр,
кадрируется в 3:4 (1080×1440) — по лицу (face) или по экрану планшета
(screen) — и кладётся в папку своего слайда. Дальше — ручной отбор по листам.

  python extract_carousel_stills.py              # все источники
  python extract_carousel_stills.py --only s4    # один слайд

Выход: output/carousel_stills/<slide>/<video>_<t>.jpg + _sheet.jpg
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import cut_ugc_clips_cozy as cz

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "downloads"
OUT = ROOT / "output" / "carousel_stills"
FF = str(Path(r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"))
OUT_W, OUT_H = 1080, 1440

# crop: face — лицо в верхней трети, zoom < 1 = крупнее (кроп меньше кадра);
# screen — по яркому экрану планшета; center — просто центр.
# every — окно, из которого берётся один самый резкий кадр (с)
SOURCES: list[dict] = [
    # 1 — устала: крупно лицо
    {"slide": "s1", "file": "MyResultVideo.mp4", "crop": "face", "zoom": 0.8, "every": 1.5},
    {"slide": "s1", "file": "IMG_9761.mp4", "crop": "face", "zoom": 0.8, "every": 3.0},
    # 2 — она же / дом
    {"slide": "s2", "file": "IMG_9736.MP4", "crop": "face", "zoom": 1.0, "every": 2.0},
    {"slide": "s2", "file": "MyResultVideo.mp4", "crop": "face", "zoom": 1.0, "every": 2.0},
    {"slide": "s2", "file": "IMG_9759.mov", "crop": "center", "zoom": 1.0, "every": 6.0, "start": 14},
    # 3 — уютный вечер с планшетом
    {"slide": "s3", "file": "IMG_9759.mov", "crop": "screen", "zoom": 1.0, "every": 4.0, "start": 14},
    {"slide": "s3", "file": "IMG_9758.mov", "crop": "screen", "zoom": 1.0, "every": 1.5, "start": 3, "end": 28.5},
    {"slide": "s3", "file": "IMG_9761.mp4", "crop": "center", "zoom": 1.0, "every": 4.0},
    # 4 — приложение крупно
    {"slide": "s4", "file": "IMG_9753.mov", "crop": "screen", "zoom": 0.85, "every": 1.0},
    {"slide": "s4", "file": "IMG_9745.mov", "crop": "screen", "zoom": 0.85, "every": 1.5, "start": 5, "end": 66},
    {"slide": "s4", "file": "IMG_9743.mov", "crop": "screen", "zoom": 0.85, "every": 1.0},
]


def probe(path: Path) -> tuple[float, int, int]:
    r = subprocess.run([FF.replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return float(r.stdout.strip()), 0, 0


def scan(path: Path, fps: float = 4.0) -> tuple[np.ndarray, list[float], list[float]]:
    """Сэмплы 270×480 в сером: время, резкость, движение."""
    r = subprocess.run([FF, "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale=270:480",
                        "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                       capture_output=True, stdin=subprocess.DEVNULL)
    a = np.frombuffer(r.stdout, np.uint8).reshape(-1, 480, 270)
    times = np.arange(len(a)) / fps
    sharp = [cv2.Laplacian(g, cv2.CV_64F).var() for g in a]
    motion = [0.0] + [float(np.abs(a[i].astype(int) - a[i - 1].astype(int)).mean()) for i in range(1, len(a))]
    return times, sharp, motion


def grab(path: Path, t: float) -> Image.Image:
    r = subprocess.run([FF, "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                        "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, stdin=subprocess.DEVNULL)
    return Image.open(BytesIO(r.stdout)).convert("RGB")


def crop_box(img: Image.Image, mode: str, zoom: float, cascade) -> tuple[int, int, int, int] | None:
    W, H = img.size
    cw = int(min(W, H * 3 / 4) * zoom)
    ch = int(cw * 4 / 3)
    cx, cy = W / 2, H / 2
    if mode == "face":
        g = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY)
        small = cv2.resize(g, (W // 3, H // 3))
        faces = cascade.detectMultiScale(small, 1.1, 5, minSize=(40, 40))
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3]) * 3
        cx, cy = x + w / 2, y + h / 2 + ch * 0.12  # лицо чуть выше центра кадра
    elif mode == "screen":
        g = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY)
        _, m = cv2.threshold(cv2.GaussianBlur(g, (21, 21), 0), 200, 255, cv2.THRESH_BINARY)
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            c = max(cnts, key=cv2.contourArea)
            if cv2.contourArea(c) > W * H * 0.04:
                x, y, w, h = cv2.boundingRect(c)
                cx, cy = x + w / 2, y + h / 2
    left = int(min(max(0, cx - cw / 2), W - cw))
    top = int(min(max(0, cy - ch / 2), H - ch))
    return left, top, left + cw, top + ch


def run_source(spec: dict, cascade, out_root: Path) -> list[Path]:
    path = RAW / spec["file"]
    times, sharp, motion = scan(path)
    t0, t1 = spec.get("start", 0.0), spec.get("end", times[-1])
    every = spec["every"]
    picks = []
    t = t0
    while t + every <= t1 + 1e-6:
        idx = [i for i, tt in enumerate(times) if t <= tt < t + every and motion[i] < 12]
        if idx:
            best = max(idx, key=lambda i: sharp[i])
            picks.append(float(times[best]))
        t += every
    # отсечь мутные: ниже 35-го перцентиля резкости по источнику
    sh = {tt: sharp[int(round(tt * 4))] for tt in picks}
    floor = np.percentile(list(sh.values()), 35) if sh else 0
    picks = [tt for tt in picks if sh[tt] >= floor]
    saved = []
    dest_dir = out_root / spec["slide"]
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(spec["file"]).stem
    for tt in picks:
        img = grab(path, tt)
        box = crop_box(img, spec["crop"], spec["zoom"], cascade)
        if box is None:
            continue
        out = img.crop(box).resize((OUT_W, OUT_H), Image.Resampling.LANCZOS)
        dest = dest_dir / f"{stem}_{tt:06.2f}.jpg"
        out.save(dest, quality=95)
        saved.append(dest)
    print(f"{spec['slide']} {spec['file']}: окон {int((t1 - t0) // every)}, сохранено {len(saved)}", flush=True)
    return saved


def sheet(folder: Path) -> None:
    files = sorted(f for f in folder.glob("*.jpg") if not f.name.startswith("_"))
    if not files:
        return
    tw, th, cols = 180, 240, 10
    rows = (len(files) + cols - 1) // cols
    s = Image.new("RGB", (cols * tw, rows * (th + 18)), (30, 30, 30))
    d = ImageDraw.Draw(s)
    font = ImageFont.truetype("arial.ttf", 13)
    for i, f in enumerate(files):
        x, y = (i % cols) * tw, (i // cols) * (th + 18)
        s.paste(Image.open(f).resize((tw, th)), (x, y + 18))
        d.text((x + 3, y + 2), f"{i + 1} {f.stem[-14:]}", fill=(255, 230, 80), font=font)
    s.save(folder / "_sheet.jpg", quality=85)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="s1 / s2 / s3 / s4")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    cascade = cz.load_face_cascade()
    for spec in SOURCES:
        if args.only and spec["slide"] != args.only:
            continue
        run_source(spec, cascade, args.out)
    for folder in sorted(args.out.glob("s*")):
        sheet(folder)
        n = len([f for f in folder.glob("*.jpg") if not f.name.startswith("_")])
        print(f"{folder.name}: {n} кадров")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
