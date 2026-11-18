#!/usr/bin/env python3
"""Локальный тюнер дропов Drops band: на волне песни двигаешь момент появления игры, слушаешь как в ролике, точки сохраняются
в downloads/drops_band/music/_drops_manual.json — их берёт build_drops_band_drop.py.
  python tuner_drops_band.py     # http://127.0.0.1:8765"""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
D = ROOT / "downloads" / "drops_band"
MANUAL = D / "music" / "_drops_manual.json"
HTML = ROOT / "tuner_drops_band.html"
SCENE = D / "clips_trash" / "t1_phones.mp4"
SONGS = {
    "MP1_Get_Back": ("Get Back", "1 Get Back.mp3", [137.358, 168.664]),
    "MP2_Get_Out_Of_My_Head": ("Get Out of My Head", "2 Get Out of My Head.mp3", [92.746]),
    "MP3_The_Best_Bad_Idea": ("The Best Bad Idea", "3 The Best Bad Idea.mp3", [134.072, 53.923, 37.634]),
    "MP4_Were_Not_Going_Home": ("We're Not Going Home", "4 We're Not Going Home.mp3", [95.115, 129.956, 30.302, 49.650]),
    "MP5_Your_Coat_On_The_Chair": ("Your Coat on the Chair", "5 Your Coat on the Chair.mp3", [78.135, 86.326]),
}
TYPES = {".mp3": "audio/mpeg", ".mp4": "video/mp4"}


def state() -> dict:
    saved = json.loads(MANUAL.read_text(encoding="utf-8")) if MANUAL.exists() else {}
    return {"songs": [{"key": k, "title": title, "points": saved.get(k, [{"t": t, "on": True} for t in pts]), "defaults": pts}
                      for k, (title, _, pts) in SONGS.items()]}


def media_path(url: str) -> Path | None:
    if url == "/media/scene":
        return SCENE
    if m := re.fullmatch(r"/media/music/(\w+)", url):
        return D / "music" / SONGS[m[1]][1] if m[1] in SONGS else None
    if m := re.fullmatch(r"/media/game/(\w+)", url):
        return D / "screencasts" / f"{m[1]}.mp4" if m[1] in SONGS else None
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
    print("http://127.0.0.1:8765", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8765), H).serve_forever()
