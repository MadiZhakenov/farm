#!/usr/bin/env python3
"""Drops (ID 1582) «whimsical websites to train your ear»: тюнер начала песни и смен слайдов видео (YT).
Зелёная линия — старт песни, белые — смены (обложка → musicmap → drops → whosampled → samplette), красная — конец.
Сохраняет downloads/drops_ear/_start.json — его берёт build_drops_ear.py (видео, --reencode).
  python tuner_drops_ear.py     # http://127.0.0.1:8776"""

from __future__ import annotations

import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SONG = ROOT / "downloads" / "1391" / "music" / "sound.mp3"          # трек 1391 — тот же, что в роликах
SAVE = ROOT / "downloads" / "drops_ear" / "_start.json"
HTML = ROOT / "tuner_drops_ear.html"
WORK = ROOT / "output" / "_work" / "drops_ear" / "_tuner"
SAMPLE = ROOT / "output" / "1582_drops_ear_YT_200"
PORT = 8776
# как в готовых роликах: обложка 0–1.61, musicmap → 2.40, drops → 3.97, whosampled → 5.55, samplette → 7.135
DEFAULTS = [0.0, 1.610, 2.403, 3.974, 5.551, 7.135]


def beats() -> dict:
    cf = WORK / "_beats.json"
    if cf.exists():
        return json.loads(cf.read_text(encoding="utf-8"))
    import librosa
    import numpy as np
    y, sr = librosa.load(str(SONG), sr=22050)
    env = librosa.onset.onset_strength(y=y, sr=sr)
    _, b = librosa.beat.beat_track(onset_envelope=env, sr=sr)
    bt = librosa.frames_to_time(b, sr=sr)
    hit = env[b] / (np.median(env[b]) + 1e-6) * 5
    d = {"beats": [round(float(t), 3) for t in bt], "hit": [round(float(h), 2) for h in hit]}
    cf.write_text(json.dumps(d), encoding="utf-8")
    return d


def slides() -> None:
    """Пять слайдов для превью — кадры из середины каждого слайда готового ролика 001."""
    if all((WORK / f"{i}.jpg").exists() for i in range(5)):
        return
    vid = next(iter(sorted(SAMPLE.glob("*.mp4"))))
    for i, (a, b) in enumerate(zip(DEFAULTS[:5], DEFAULTS[1:])):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{(a + b) / 2:.3f}", "-i", str(vid), "-frames:v", "1",
                        "-vf", "scale=540:-2", "-q:v", "3", str(WORK / f"{i}.jpg")], check=True)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a) -> None:
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/":
            return self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/state":
            b = beats()
            saved = json.loads(SAVE.read_text(encoding="utf-8")) if SAVE.exists() else {}
            return self._send(200, json.dumps({"beats": b["beats"], "hits": b["hit"], "start": saved.get("start", DEFAULTS[0]),
                                               "cuts": saved.get("cuts", DEFAULTS[1:5]), "end": saved.get("end", DEFAULTS[5]),
                                               "defaults": DEFAULTS}).encode(), "application/json")
        if self.path == "/media/song":
            return self._send(200, SONG.read_bytes(), "audio/mpeg")
        if m := re.fullmatch(r"/media/slide/(\d)", self.path):
            return self._send(200, (WORK / f"{m[1]}.jpg").read_bytes(), "image/jpeg")
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/api/save":
            return self._send(404, b"not found", "text/plain")
        d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        data = {"start": round(float(d["start"]), 3), "cuts": [round(float(x), 3) for x in d["cuts"]], "end": round(float(d["end"]), 3)}
        if len(data["cuts"]) != 4:
            return self._send(400, b"need 4 cuts", "text/plain")
        tmp = SAVE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, SAVE)
        self._send(200, b"{}", "application/json")


if __name__ == "__main__":
    WORK.mkdir(parents=True, exist_ok=True)
    beats()
    slides()
    print(f"http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
