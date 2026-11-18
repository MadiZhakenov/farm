#!/usr/bin/env python3
"""Drops band: где в каждой песне дроп (скачок громкости и низа на сильной доле) и самые жёсткие удары → music/_drops.json.
Точка уточняется по атаке с шагом ~6 мс: на неё ставится первый кадр игры.
  python map_drops_band_drops.py"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import librosa
import numpy as np

ROOT = Path(__file__).resolve().parent
MUSIC = ROOT / "downloads" / "drops_band" / "music"
SR, HOP = 22050, 128


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = {}
    for p in sorted(MUSIC.glob("*.mp3")):
        y, sr = librosa.load(str(p), sr=SR, mono=True)
        dur = len(y) / sr
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
        bpm = float(np.atleast_1d(tempo)[0])
        rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0]
        S = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
        low = np.sqrt((S[freqs < 150] ** 2).mean(0))
        env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
        n = min(len(rms), len(low), len(env))
        rms, low, env = rms[:n], low[:n], env[:n]
        t2f = lambda t: int(np.clip(t * sr / HOP, 0, n - 1))   # noqa: E731

        def snap(t: float) -> float:
            """Пик атаки в пределах ±50 мс от доли."""
            a, b = t2f(t - 0.05), t2f(t + 0.05)
            return round((a + int(np.argmax(env[a:b + 1]))) * HOP / sr, 3)

        def seg(arr: np.ndarray, a: float, b: float) -> float:
            return float(np.mean(arr[t2f(a):max(t2f(a) + 1, t2f(b))]))

        rows = []
        med = float(np.median(env))
        for b in beats:
            if b < 3.2 or b > dur - 5.2:
                continue
            t = snap(float(b))
            jump = 20 * np.log10((seg(rms, t + 0.02, t + 2.0) + 1e-6) / (seg(rms, t - 2.0, t - 0.1) + 1e-6))
            jump_low = 20 * np.log10((seg(low, t + 0.02, t + 2.0) + 1e-6) / (seg(low, t - 2.0, t - 0.1) + 1e-6))
            hit = float(env[t2f(t)] / (med + 1e-6))
            level = 20 * np.log10(seg(rms, t + 0.02, t + 5.0) + 1e-6)
            rows.append(dict(t=t, jump=round(float(jump), 2), low=round(float(jump_low), 2), hit=round(hit, 1), level=round(float(level), 1)))
        peak = np.percentile([r["level"] for r in rows], 90)
        pick = sorted(rows, key=lambda r: -(r["jump"] + 0.4 * max(0.0, r["low"]) + 0.15 * r["hit"]))
        drops: list[dict] = []
        for r in pick:
            if r["jump"] < 2.0 or r["level"] < peak - 4.0:      # после дропа должно быть громко
                continue
            if all(abs(r["t"] - d["t"]) >= 4.0 for d in drops):
                drops.append(r)
        hits: list[dict] = []
        for r in sorted(rows, key=lambda r: -r["hit"]):
            if r["level"] >= peak - 3.0 and all(abs(r["t"] - h["t"]) >= 1.2 for h in hits):
                hits.append(r)
        out[p.name] = dict(bpm=round(bpm, 1), dur=round(dur, 2), drops=sorted(drops, key=lambda d: d["t"]), hits=sorted(hits[:24], key=lambda d: d["t"]))
        print(f"== {p.name}  {bpm:.0f} BPM  {dur:.0f} с  дропов {len(drops)}  ударов {len(hits)}")
        for d in sorted(drops, key=lambda d: -d["jump"])[:10]:
            print(f"   {d['t']:7.2f}  +{d['jump']:.1f} дБ  низ {d['low']:+.1f}  удар {d['hit']}  уровень {d['level']}")
    (MUSIC / "_drops.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
