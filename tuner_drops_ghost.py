#!/usr/bin/env python3
"""Тюнер переходов Drops ghost (ID 1, «he hasn't texted me back…»): на волне трендового трека двигаешь момент перехода
лицо → игра (вкладка Ranks + геймплей), слушаешь как в ролике; биты трека отмечены зелёным, «К биту» прилипает к ближайшему.
Точки сохраняются в downloads/drops_ghost/music2/_cuts_manual.json — их берёт build_drops_ghost.py --music dugc
(старт звука = точка − длина лица, следующие склейки — на биты после точки).
  python tuner_drops_ghost.py     # http://127.0.0.1:8771"""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
M2 = ROOT / "downloads" / "drops_ghost" / "music2"
MANUAL = M2 / "_cuts_manual.json"
HTML = ROOT / "tuner_drops_ghost.html"
WORK = ROOT / "output" / "_work" / "drops_ghost"
SONGS = {
    "futile_devices": ("Futile Devices", "futile_devices_7498146795982228270.mp3"),
    "watch": ("watch", "watch_7269062050672397062.mp3"),
    "jenny": ("i'd always think of jenny", "jenny_7548582234221053953.mp3"),
    "rodwave": ("rodwavehairline", "rodwave_7596903333727210270.mp3"),
    "far_apart": ("delaudios", "far_apart_7354103379888769824.mp3"),
}
PRE = 3.2                                               # лицо до перехода (в ролике 2.9–3.2 с) — точка не раньше
TYPES = {".mp3": "audio/mpeg", ".mp4": "video/mp4", ".jpg": "image/jpeg"}
_BEATS: dict = {}


def beats(key: str) -> list[float]:
    """Биты трека (librosa), кэш в output/_work/drops_ghost/beats_<key>.json."""
    if key not in _BEATS:
        cache = WORK / f"beats_{key}.json"
        if cache.exists():
            _BEATS[key] = json.loads(cache.read_text(encoding="utf-8"))
        else:
            import librosa
            import numpy as np
            y, sr = librosa.load(str(M2 / SONGS[key][1]), sr=22050, mono=True)
            _, fr = librosa.beat.beat_track(y=y, sr=sr, units="frames")
            _BEATS[key] = [round(float(t), 3) for t in np.asarray(librosa.frames_to_time(fr, sr=sr))]
            WORK.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(_BEATS[key]), encoding="utf-8")
    return _BEATS[key]


def defaults(key: str) -> list[float]:
    """Как сейчас в партии: первый бит в окне 3.0–3.7 с (начало звука = тот кусок, что в вирусных роликах)."""
    b = beats(key)
    return [next((t for t in b if PRE <= t <= PRE + 0.7), PRE)]


def state() -> dict:
    saved = json.loads(MANUAL.read_text(encoding="utf-8")) if MANUAL.exists() else {}
    return {"pre": PRE, "songs": [{"key": k, "title": title, "beats": beats(k), "defaults": defaults(k),
                                   "points": saved.get(k, [{"t": t, "on": True} for t in defaults(k)])}
                                  for k, (title, _) in SONGS.items()]}


def media_path(url: str) -> Path | None:
    if url == "/media/scene":
        return WORK / "tuner_face.mp4"
    if url == "/media/game":
        return WORK / "tuner_gameplay.mp4"
    if url == "/media/ranks":
        return WORK / "tuner_ranks.jpg"
    if m := re.fullmatch(r"/media/music/(\w+)", url):
        return M2 / SONGS[m[1]][1] if m[1] in SONGS else None
    return None


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
            return self._send(200, json.dumps(state()).encode(), "application/json")
        p = media_path(self.path)
        if p is None or not p.exists():
            return self._send(404, b"not found", "text/plain")
        size = p.stat().st_size
        start, end, code = 0, size - 1, 200
        if m := re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "")):
            start = int(m[1]) if m[1] else max(0, size - int(m[2]))
            end = min(int(m[2]), size - 1) if m[1] and m[2] else size - 1
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", TYPES.get(p.suffix.lower(), "application/octet-stream"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with p.open("rb") as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0 and (chunk := f.read(min(left, 1 << 16))):
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass

    def do_POST(self) -> None:
        if self.path != "/api/save":
            return self._send(404, b"not found", "text/plain")
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        clean = {k: [{"t": round(float(p["t"]), 3), "on": bool(p["on"])} for p in data.get(k, [])] for k in SONGS}
        tmp = MANUAL.with_suffix(".tmp")
        tmp.write_text(json.dumps(clean, indent=1), encoding="utf-8")
        os.replace(tmp, MANUAL)
        self._send(200, b"{}", "application/json")


if __name__ == "__main__":
    for k in SONGS:
        beats(k)
    print("http://127.0.0.1:8771", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8771), H).serve_forever()
