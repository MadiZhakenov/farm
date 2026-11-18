#!/usr/bin/env python3
"""Колибри 2: библиотека эффектных планов из киносцен (downloads/calibri2/movies). Склейки — по резкой смене кадра,
у каждого плана: движение, доля ярких насыщенных пикселей (огонь, вспышки, энергия), громкость звука, тёмность.
→ downloads/calibri2/shots.json + листы кандидатов (лучшие по оценке) для ручного отбора.
  python make_kolibri2_shots.py <папка для листов>"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
MOV = ROOT / "downloads" / "calibri2" / "movies"
OUT = ROOT / "downloads" / "calibri2" / "shots.json"
FPS_A, SW, SH = 10, 96, 72                     # анализ: 10 кадр/с, центр 4:3 → 96×72
SKIP = {"4WGMhicoCa8": (0, 210), "cgLbRQK_Rg4": (0, 230), "fRKviUgMP4o": (0, 293), "ET9SHYzMz_4": (0, 226),
        "ooOSFvBa55w": (8, 278), "sZ3mJIh0bFY": (0, 296), "BhF7G3EDtzs": (0, 510), "v2H1s9gj5DA": (0, 414),
        "pjl3XN_HIdA": (0, 210), "jBRN0NLZ4HI": (0, 290), "bwe1vu1L2k0": (0, 166)}   # без заставок и финальных карточек


def frames(p: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vf", f"fps={FPS_A},crop=ih*4/3:ih,scale={SW}:{SH}", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, SH, SW, 3)


def audio_db(p: Path, n: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    hop = 8000 // FPS_A
    out = np.full(n, -90.0)
    for i in range(min(n, len(a) // hop)):
        seg = a[i * hop:(i + 1) * hop]
        out[i] = 20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-6)
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sheets = Path(sys.argv[1])
    shots = []
    for p in sorted(MOV.glob("*.mp4")):
        lo, hi = SKIP[p.stem]
        v = frames(p).astype(np.float32)
        n = len(v)
        db = audio_db(p, n)
        gray = v.mean(3)
        diff = np.abs(np.diff(gray, axis=0)).mean((1, 2))
        hist = [np.histogram(f, bins=16, range=(0, 255))[0] / f.size for f in gray]
        hd = np.array([np.abs(hist[i + 1] - hist[i]).sum() for i in range(n - 1)])
        cuts = [0] + [i + 1 for i in range(n - 1) if hd[i] > 0.5 or diff[i] > 38] + [n]
        mx, mn = v.max(3), v.min(3)
        sat = (mx - mn) / (mx + 1)
        hot = ((mx > 200) & (sat > 0.35)).mean((1, 2))
        lum = gray.mean((1, 2))
        for a, b in zip(cuts, cuts[1:]):
            t0, t1 = a / FPS_A, b / FPS_A
            if t1 - t0 < 0.6 or t0 < lo or t1 > hi:
                continue
            motion = float(diff[a:b - 1].mean()) if b - a > 1 else 0.0
            shots.append(dict(fid=p.stem, t0=round(t0, 2), t1=round(t1, 2), motion=round(motion, 2), hot=round(float(hot[a:b].mean()), 3),
                              lum=round(float(lum[a:b].mean()), 1), db=round(float(np.percentile(db[a:b], 90)), 1)))
        print(p.stem, n, "shots", sum(1 for s in shots if s["fid"] == p.stem), flush=True)
    for s in shots:
        s["score"] = round(s["motion"] * 1.0 + s["hot"] * 120 + max(0, s["db"] + 30) * 0.6 - (12 if s["lum"] < 28 else 0), 2)
    OUT.write_text(json.dumps(shots, indent=1), encoding="utf-8")
    f = ImageFont.truetype(str(ROOT / "fonts" / "inter" / "Inter-Bold.ttf"), 12)
    for fid in sorted({s["fid"] for s in shots}):
        cand = sorted((s for s in shots if s["fid"] == fid), key=lambda s: -s["score"])[:40]
        cand.sort(key=lambda s: s["t0"])
        W, H, C = 192, 144, 10
        sh = Image.new("RGB", (W * C, H * ((len(cand) + C - 1) // C)), "black")
        for i, s in enumerate(cand):
            t = (s["t0"] + s["t1"]) / 2
            out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(MOV / f"{fid}.mp4"), "-frames:v", "1", "-vf",
                                  f"crop=ih*4/3:ih,scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
            if len(out) != W * H * 3:
                continue
            im = Image.frombytes("RGB", (W, H), out)
            ImageDraw.Draw(im).text((3, 2), f"{s['t0']:.1f}-{s['t1']:.1f} s{s['score']:.0f}", font=f, fill=(255, 230, 0),
                                    stroke_width=2, stroke_fill=(0, 0, 0))
            sh.paste(im, (i % C * W, i // C * H))
        sh.save(sheets / f"shots_{fid}.jpg", quality=80)
    print("всего планов", len(shots))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
