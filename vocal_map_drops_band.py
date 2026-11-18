#!/usr/bin/env python3
"""
Drops band: где в треках клиента звучит голос. Demucs (htdemucs, GPU) отделяет вокал, по нему — громкость
вокала по 0,1 с → downloads/drops_band/music/_vocals.json {трек: {"hop": 0.1, "rms": [...], "thr": порог}}.
Сборщик берёт отрезки, где голос идёт в первые 3 с (группа поёт в кадре) и почти весь ролик.

  python vocal_map_drops_band.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch
from demucs.apply import apply_model
from demucs.pretrained import get_model

ROOT = Path(__file__).resolve().parent
MUSIC = ROOT / "downloads" / "drops_band" / "music"
SR, HOP = 44100, 0.1


def load(p: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).T.copy()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    model = get_model("htdemucs").cuda().eval()
    vi = model.sources.index("vocals")
    out = {}
    for p in sorted(MUSIC.glob("*.mp3")):
        wav = torch.from_numpy(load(p))
        ref = wav.mean(0)
        x = (wav - ref.mean()) / (ref.std() + 1e-8)
        with torch.no_grad():
            src = apply_model(model, x[None].cuda(), device="cuda", split=True, overlap=0.25, progress=False)[0]
        voc = (src[vi] * ref.std() + ref.mean()).mean(0).cpu().numpy()
        n = int(SR * HOP)
        rms = np.sqrt(np.add.reduceat(voc[: len(voc) // n * n] ** 2, np.arange(0, len(voc) // n * n, n)) / n)
        db = 20 * np.log10(rms + 1e-6)
        thr = float(np.percentile(db, 90) - 18)                       # голос есть: не тише пика вокала на 18 дБ
        out[p.name] = {"hop": HOP, "db": [round(float(v), 1) for v in db], "thr": round(thr, 1)}
        print(p.name, f"{len(db) * HOP:.0f} s, голос {np.mean(db > thr) * 100:.0f} % времени, порог {thr:.1f} dB", flush=True)
    (MUSIC / "_vocals.json").write_text(json.dumps(out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
