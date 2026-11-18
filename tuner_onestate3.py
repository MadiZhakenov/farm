#!/usr/bin/env python3
"""Тюнер звуков OneState 3 (ID 1, «CEO → таксист / коп»): на волне мема двигаешь момент, где «кино»-кадр сменяется на
геймплей (красная линия), и сколько «кино» до него; склейки геймплея сами встают на доли (каждые 1 или 2 доли) до 7 с.
Цветные полоски — что будет на экране. Точки → downloads/onestate3/music/_cuts_manual.json — их берёт build_onestate3_reels.py.
  python tuner_onestate3.py     # http://127.0.0.1:8773"""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MUS = ROOT / "downloads" / "onestate3" / "music"
MANUAL = MUS / "_cuts_manual.json"
HTML = ROOT / "tuner_onestate3.html"
WORK = ROOT / "output" / "_work" / "onestate3"
PORT = 8773
SONGS = {
    # 13.11 юзер: вместо мема Drive — SNAP! Rhythm Is A Dancer (slowed + reverb), полная версия с YouTube z6_ZshbfDdM (4:38)
    "rhythm": ("Rhythm Is A Dancer (slowed, YouTube)", "rhythm_slowed_yt_z6_ZshbfDdM.mp3"),
    "cat": ("Кот (мем)", "jojx_photo_7475022940808006934.mp3"),
}
# как в тестах: Drive с дропа (дроп 6.0 с, 3 с кино до него) и с начала; кот — с 0.3 с
DEFAULTS = {"rhythm": [{"t": 38.731, "pre": 3.0, "step": 2, "on": True}, {"t": 135.303, "pre": 3.0, "step": 2, "on": True}],   # два дропа трека
            "cat": [{"t": 1.53, "pre": 1.23, "step": 2, "on": True}]}
TOTAL = 7.0
TYPES = {".mp3": "audio/mpeg", ".mp4": "video/mp4"}
_BEATS: dict = {}


def beats(key: str) -> list[float]:
    if key not in _BEATS:
        cache = WORK / f"beats_{key}.json"
        if cache.exists():
            _BEATS[key] = json.loads(cache.read_text(encoding="utf-8"))
        else:
            import subprocess
            import librosa
            import numpy as np
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(MUS / SONGS[key][1]), "-ac", "1", "-ar", "22050",
                                  "-f", "f32le", "-"], capture_output=True).stdout
            y = np.frombuffer(raw, np.float32)
            _, fr = librosa.beat.beat_track(y=y, sr=22050)
            _BEATS[key] = [round(float(t), 3) for t in librosa.frames_to_time(fr, sr=22050)]
            WORK.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(_BEATS[key]), encoding="utf-8")
    return _BEATS[key]


_DUR: dict = {}


def duration(key: str) -> float:
    if key not in _DUR:
        import subprocess
        _DUR[key] = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                          str(MUS / SONGS[key][1])], capture_output=True, text=True).stdout)
    return _DUR[key]


def points() -> dict:
    saved = json.loads(MANUAL.read_text(encoding="utf-8")) if MANUAL.exists() else {}
    return {k: saved.get(k) or DEFAULTS[k] for k in SONGS}


def segments(key: str, p: dict) -> list[tuple[str, float, float]]:
    """Отрезки ролика по времени ТРЕКА: кино (1 или 2 кадра) до точки, дальше геймплей с доли на долю — до 7 с.
    Та же логика — в tuner_onestate3.html (segs)."""
    t, pre, step = p["t"], p["pre"], int(p.get("step", 2))
    start, end = t - pre, min(t - pre + TOTAL, duration(key) - 0.05)       # звук кончился — ролик короче
    bs = beats(key)
    out = []
    if pre >= 2.2:                                         # два кино-кадра: склейка на доле ближе к середине
        mid = min((b for b in bs if start + 0.8 <= b <= t - 0.8), key=lambda b: abs(b - (start + pre / 2)), default=None)
        out += [("кино 1", start, mid), ("кино 2", mid, t)] if mid else [("кино", start, t)]
    else:
        out.append(("кино", start, t))
    after = [b for b in bs if b > t + 0.3]
    cuts = [b for k, b in enumerate(after) if (k + 1) % step == 0 and b < end - 0.5]
    a = t
    for k, c in enumerate(cuts + [end], 1):
        out.append((f"игра {k}", a, c))
        a = c
    return out


def media_path(url: str) -> Path | None:
    if url == "/media/hook":
        return WORK / "tuner_hook.mp4"
    if url == "/media/game":
        return WORK / "tuner_game.mp4"
    if m := re.fullmatch(r"/media/music/(\w+)", url):
        return MUS / SONGS[m[1]][1] if m[1] in SONGS else None
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
            pts = points()
            st = {"total": TOTAL, "songs": [{"key": k, "title": t, "beats": beats(k), "dur": duration(k), "points": pts[k],
                                             "defaults": DEFAULTS[k]}
                                            for k, (t, _f) in SONGS.items()]}
            return self._send(200, json.dumps(st).encode(), "application/json")
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
        clean = {k: [{"t": round(float(p["t"]), 3), "pre": round(float(p["pre"]), 3), "step": int(p.get("step", 2)),
                      "on": bool(p["on"])} for p in data.get(k, [])] for k in SONGS}
        tmp = MANUAL.with_suffix(".tmp")
        tmp.write_text(json.dumps(clean, indent=1), encoding="utf-8")
        os.replace(tmp, MANUAL)
        self._send(200, b"{}", "application/json")


if __name__ == "__main__":
    for k in SONGS:
        beats(k)
    print(f"http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
