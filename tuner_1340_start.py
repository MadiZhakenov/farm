#!/usr/bin/env python3
"""1340 v2: тюнер начала песни. Зелёная линия — откуда стартует трек; смены слайдов сами встают на доли после неё.
Сохраняет downloads/1340/music/_start.json, его берёт build_1340_v2.py.
  python tuner_1340_start.py     # http://127.0.0.1:8766"""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MUSIC = ROOT / "downloads" / "1340" / "music"
SAVE = MUSIC / "_start.json"
HTML = ROOT / "tuner_1340_start.html"
SLIDES = ROOT / "output" / "1340_v2_test" / "_tuner"
DEFAULT_CUTS, DEFAULT_END = [6.153, 7.663, 8.26, 9.149, 10.06, 10.652], 12.748


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
            b = json.loads((MUSIC / "_beats.json").read_text(encoding="utf-8"))
            saved = json.loads(SAVE.read_text(encoding="utf-8")) if SAVE.exists() else {}
            start, cuts, end = saved.get("start", 4.31), saved.get("cuts", DEFAULT_CUTS), saved.get("end", DEFAULT_END)
            return self._send(200, json.dumps({"beats": b["beats"], "hits": b["hit"], "start": start, "cuts": cuts, "end": end,
                                               "defaults": [4.31, *DEFAULT_CUTS, DEFAULT_END]}).encode(), "application/json")
        if self.path == "/media/song":
            return self._send(200, (MUSIC / "tt_sound.mp3").read_bytes(), "audio/mpeg")
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
    print("http://127.0.0.1:8766", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8766), H).serve_forever()
