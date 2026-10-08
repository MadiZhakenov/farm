#!/usr/bin/env python3
"""
Нарезка видео-вставок (b-roll) на куски фиксированной длины: склейки внутри
исходника → отдельные планы, каждый план режется подряд на куски по --len;
отсев смаза, почти чёрных кусков и рывков камеры; экспорт 1080×1920 30 fps
SDR без звука + лист для ручного отбора (лишнее — в _rejected/).

  python cut_broll_clips.py --src downloads/1254/broll/car/_v2 --out downloads/1254/broll/car/clips_1.1s
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.ugc_color import SDR_COLOR_ARGS, vf_scale_crop_fps_sdr  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
W, H, FPS = 1080, 1920, 30
CUT_DIFF = 28.0       # средняя разница кадров (0–255) выше — склейка / резкий рывок
DARK_ABS, DARK_REL = 3.0, 0.45  # кусок темнее max(3, 0.45 × медиана исходника) — почти чёрный
                                # (ночное видео само по себе ~6–8 из 255 — это норма)
BLUR_REL = 0.35       # резкость куска ниже этой доли от медианы исходника — смаз
EDGE_SKIP = 0.15      # с краёв плана, с: на стыке часто смаз / вспышка


def analyze(path: Path) -> tuple[float, np.ndarray, np.ndarray, np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    bright, sharp, diff, prev = [], [], [], None
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(cv2.resize(fr, (270, 480)), cv2.COLOR_BGR2GRAY)
        bright.append(float(g.mean()))
        sharp.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
        diff.append(float(np.abs(g.astype(np.int16) - prev).mean()) if prev is not None else 0.0)
        prev = g.astype(np.int16)
    return fps, np.array(bright), np.array(sharp), np.array(diff)


def detect_bars(path: Path) -> tuple[int, int, int, int] | None:
    """Чёрные полосы (letterbox), вшитые в исходник: (x, y, w, h) области картинки или None.
    Полоса — строки/столбцы почти чистого чёрного (max ≤ 12), одинаковые в большинстве кадров:
    ночную темноту в кадре так не срежет."""
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    boxes = []
    for k in range(9):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (0.1 + 0.8 * k / 8)))
        ok, fr = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        rows, cols = np.where(g.max(1) > 12)[0], np.where(g.max(0) > 12)[0]
        if len(rows) and len(cols):
            boxes.append((cols[0], rows[0], cols[-1] + 1, rows[-1] + 1))
    if len(boxes) < 5:
        return None
    x0, y0, x1, y1 = (int(np.median([b[i] for b in boxes])) for i in range(4))
    agree = sum(abs(b[1] - y0) <= 4 and abs(b[3] - y1) <= 4 and abs(b[0] - x0) <= 4 and abs(b[2] - x1) <= 4
                for b in boxes)
    h, w = g.shape
    if agree < 0.7 * len(boxes) or (y0 < 0.03 * h and h - y1 < 0.03 * h and x0 < 0.03 * w and w - x1 < 0.03 * w):
        return None
    x0, y0 = x0 + 2, y0 + 2  # с запасом от мягкого края полосы
    return x0, y0, (x1 - 2 - x0) // 2 * 2, (y1 - 2 - y0) // 2 * 2


def windows(path: Path, length: float) -> list[dict]:
    fps, bright, sharp, diff = analyze(path)
    n = len(bright)
    cuts = [0] + [i for i in range(1, n) if diff[i] > CUT_DIFF] + [n]
    med_sharp = float(np.median(sharp)) or 1.0
    dark = max(DARK_ABS, DARK_REL * float(np.median(bright)))
    win, edge = int(round(length * fps)), int(round(EDGE_SKIP * fps))
    out = []
    for a, b in zip(cuts, cuts[1:]):
        s = a + (edge if a > 0 else 0)
        while s + win <= b - (edge if b < n else 0):
            seg = slice(s, s + win)
            reason = None
            if bright[seg].mean() < dark:
                reason = "dark"
            elif sharp[seg].mean() < BLUR_REL * med_sharp:
                reason = "blur"
            out.append({"start": round(s / fps, 3), "bright": round(float(bright[seg].mean()), 1),
                        "sharp": round(float(sharp[seg].mean()) / med_sharp, 2),
                        "motion": round(float(diff[s + 1:s + win].max()), 1), "reject": reason})
            s += win
    return out


def export(src: Path, start: float, length: float, dest: Path, bars: tuple | None = None) -> None:
    vf = vf_scale_crop_fps_sdr(W, H, FPS)
    if bars:
        vf = "crop={2}:{3}:{0}:{1},".format(*bars) + vf
    subprocess.run([FF, "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{length:.3f}",
                    "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "18", *SDR_COLOR_ARGS, "-movflags", "+faststart", str(dest)],
                   stdin=subprocess.DEVNULL, check=True)


def sheet(clips: list[Path], dest: Path, length: float) -> None:
    FW, FH, COLS = 108, 192, 8
    font = ImageFont.truetype("arial.ttf", 20)
    rows = (len(clips) + COLS - 1) // COLS
    img = Image.new("RGB", (COLS * (FW * 3 + 8), rows * (FH + 6)), "white")
    d = ImageDraw.Draw(img)
    tmp = dest.parent / "_f.png"
    for i, c in enumerate(clips):
        x0, y0 = (i % COLS) * (FW * 3 + 8), (i // COLS) * (FH + 6)
        for j, t in enumerate((0.05, length / 2, length - 0.08)):
            subprocess.run([FF, "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(c), "-frames:v", "1",
                            "-vf", f"scale={FW}:{FH}", str(tmp)], stdin=subprocess.DEVNULL)
            img.paste(Image.open(tmp).convert("RGB"), (x0 + j * FW, y0))
        d.rectangle([x0, y0, x0 + 44, y0 + 24], fill="black")
        d.text((x0 + 3, y0 + 1), c.name.split("_")[0], fill="yellow", font=font)
    tmp.unlink(missing_ok=True)
    img.save(dest, quality=88)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True, help="папка с исходными mp4")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--len", type=float, default=1.1)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest, k = [], 0
    for src in sorted(args.src.glob("*.mp4")):
        ws = windows(src, args.len)
        kept = [w for w in ws if not w["reject"]]
        bars = detect_bars(src)
        if bars:
            print(f"{src.name}: чёрные полосы → crop {bars}", flush=True)
        print(f"{src.name}: кусков {len(ws)}, оставлено {len(kept)} "
              f"(тёмных {sum(w['reject'] == 'dark' for w in ws)}, смаз {sum(w['reject'] == 'blur' for w in ws)})",
              flush=True)
        for w in kept:
            k += 1
            name = f"{k:03d}_{src.stem.split('_')[0]}_{w['start']:.2f}s.mp4"
            export(src, w["start"], args.len, args.out / name, bars)
            manifest.append({"file": name, "src": src.name, **w})
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    sheet(sorted(args.out.glob("*.mp4")), args.out / "_sheet.jpg", args.len)
    print(f"готово: {k} кусков → {args.out} (лист: _sheet.jpg)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
