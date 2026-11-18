#!/usr/bin/env python3
"""
Drops beats: долевые и сильные доли треков клиента (librosa) → downloads/drops_beats/music/_beats.json
{трек: {"bpm": …, "beats": [с], "onsets": [с], "dur": с}}. Сборщик ставит по ним шаги сетки в карточке,
пульс геймплея и смены кадров.

  python beat_map_drops_beats.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import librosa
import numpy as np

ROOT = Path(__file__).resolve().parent
MUSIC = ROOT / "downloads" / "drops_beats" / "music"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = {}
    for p in sorted(MUSIC.glob("*.mp3")):
        y, sr = librosa.load(str(p), sr=22050, mono=True)
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
        ons = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=False)
        bpm = float(np.atleast_1d(tempo)[0])
        out[p.name] = {"bpm": round(bpm, 2), "beats": [round(float(t), 3) for t in beats],
                       "onsets": [round(float(t), 3) for t in ons], "dur": round(len(y) / sr, 2)}
        print(f"{p.name}: {bpm:.1f} BPM, {len(beats)} долей, первая {beats[0]:.2f} с", flush=True)
    (MUSIC / "_beats.json").write_text(json.dumps(out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
