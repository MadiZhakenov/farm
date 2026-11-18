#!/usr/bin/env python3
"""Drops «Websites that keep you inspired to make music Part 2»: тюнер начала песни и смен слайдов видео.
Зелёная линия — старт песни, белые — смены (обложка → cratedrop → drops → radiooooo), красная — конец.
Сохраняет downloads/drops_inspire/music/_start.json — его берёт build_drops_inspire.py (видео).
  python tuner_drops_inspire.py     # http://127.0.0.1:8775"""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MUSIC = ROOT / "downloads" / "drops_inspire" / "music"
SAVE = MUSIC / "_start.json"
HTML = ROOT / "tuner_drops_inspire.html"
SLIDES = ROOT / "output" / "_work" / "drops_inspire" / "_tuner"
PORT = 8775


def beats() -> dict:
    cf = MUSIC / "_beats.json"
    if cf.exists():
        return json.loads(cf.read_text(encoding="utf-8"))
    import librosa
    import numpy as np
    y, sr = librosa.load(str(MUSIC / "sound.mp3"), sr=22050)
    env = librosa.onset.onset_strength(y=y, sr=sr)
    _, b = librosa.beat.beat_track(onset_envelope=env, sr=sr)
    bt = librosa.frames_to_time(b, sr=sr)
    hit = env[b] / (np.median(env[b]) + 1e-6) * 5
    d = {"beats": [round(float(t), 3) for t in bt], "hit": [round(float(h), 2) for h in hit]}
    cf.write_text(json.dumps(d), encoding="utf-8")
    return d


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
            bt = b["beats"]
            dflt = [0.0, bt[4], bt[8], bt[12], bt[16]]
            saved = json.loads(SAVE.read_text(encoding="utf-8")) if SAVE.exists() else {}
            return self._send(200, json.dumps({"beats": bt, "hits": b["hit"], "start": saved.get("start", dflt[0]),
                                               "cuts": saved.get("cuts", dflt[1:4]), "end": saved.get("end", dflt[4]),
                                               "defaults": dflt}).encode(), "application/json")
        if self.path == "/media/song":
            return self._send(200, (MUSIC / "sound.mp3").read_bytes(), "audio/mpeg")
        if m := re.fullmatch(r"/media/slide/(\d)", self.path):
            return self._send(200, (SLIDES / f"{m[1]}.jpg").read_bytes(), "image/jpeg")
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/api/save":
            return self._send(404, b"not found", "text/plain")
        d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        data = {"start": round(float(d["start"]), 3), "cuts": [round(float(x), 3) for x in d["cuts"]], "end": round(float(d["end"]), 3)}
        tmp = SAVE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, SAVE)
        self._send(200, b"{}", "application/json")


if __name__ == "__main__":
    beats()
    print(f"http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
