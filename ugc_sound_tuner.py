#!/usr/bin/env python3
"""
Ручная подгонка старта звуков для UGC-роликов (assemble_ugc_reels_3part.py).

Страница в браузере: видео (без своего звука) + волна трека, окно 8 с
двигается мышью / кнопками, линия склейки 4.0 с = вход кульминации.
«Сохранить» пишет ugc_sound_starts.json — сборщик берёт старты оттуда.

  python ugc_sound_tuner.py                      # http://127.0.0.1:8765
  python ugc_sound_tuner.py --videos output/ugc_3part_sound_test3
  python ugc_sound_tuner.py --preset deleted     # 5 звуков, свой файл стартов
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import assemble_ugc_reels_3part as M

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "ugc_sound_tuner.html"


def find_videos(folder: Path | None) -> list[Path]:
    if folder:
        return sorted(folder.rglob("*.mp4"))[:20]
    # по умолчанию — самая свежая папка с тестовыми роликами
    dirs = [d for d in (ROOT / "output").glob("ugc_3part*") if d.is_dir() and any(d.rglob("*.mp4"))]
    for d in sorted(dirs, key=lambda d: d.stat().st_mtime, reverse=True):
        return sorted(d.rglob("*.mp4"))[:20]
    return []


def make_handler(videos: list[Path], preset: str):
    sounds = {sd["name"]: sd for sd in M.SOUNDS}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # тихо
            pass

        def _send(self, body: bytes, ctype: str, status=HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status=HTTPStatus.OK) -> None:
            self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", status)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._json({
                    "cut": M.CUT,
                    "total": M.TOTAL,
                    "file": M.SOUND_STARTS_FILE.name,
                    "preset": preset,
                    "sounds": [{"name": sd["name"], "file": sd["file"].name, "start": sd["start"]}
                               for sd in M.SOUNDS],
                    "videos": [f"{v.parent.name}/{v.name}" for v in videos],
                })
            elif path.startswith("/media/sound/"):
                sd = sounds.get(path.rsplit("/", 1)[-1])
                if not sd:
                    return self._json({"error": "нет звука"}, HTTPStatus.NOT_FOUND)
                self._send(sd["file"].read_bytes(), "audio/mpeg")
            elif path.startswith("/media/video/"):
                try:
                    v = videos[int(path.rsplit("/", 1)[-1])]
                except (ValueError, IndexError):
                    return self._json({"error": "нет видео"}, HTTPStatus.NOT_FOUND)
                self._send(v.read_bytes(), "video/mp4")
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self):
            if self.path != "/api/save":
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                starts = {name: round(max(0.0, float(data[name])), 2) for name in sounds if name in data}
            except (ValueError, TypeError, KeyError):
                return self._json({"error": "плохие данные"}, HTTPStatus.BAD_REQUEST)
            try:
                saved = json.loads(M.SOUND_STARTS_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = {}
            saved.update(starts)
            M.SOUND_STARTS_FILE.write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
            for name, start in starts.items():
                sounds[name]["start"] = start
            print("сохранено: " + ", ".join(f"{k} {v:.2f}с" for k, v in saved.items()), flush=True)
            self._json({"ok": True, "saved": saved})

    return Handler


class Server(ThreadingHTTPServer):
    # на Windows reuse_address позволяет двум тюнерам слушать один порт —
    # браузер тогда попадает в старый; лучше упасть с «порт занят»
    allow_reuse_address = False


def main() -> int:
    ap = argparse.ArgumentParser(description="GUI: подгонка старта звуков UGC")
    ap.add_argument("--videos", type=Path, help="папка с роликами для превью (звук глушится)")
    ap.add_argument("--preset", choices=sorted(M.PRESETS), default="cozy")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")

    M.use_preset(args.preset)
    videos = find_videos(args.videos)
    if not videos:
        raise SystemExit("Нет роликов для превью: собери тест (-n 5) или укажи --videos")
    url = f"http://127.0.0.1:{args.port}/"
    server = Server(("127.0.0.1", args.port), make_handler(videos, args.preset))
    print(f"тюнер звуков [{args.preset}]: {url}  (видео из {videos[0].parent.name}, "
          f"старты → {M.SOUND_STARTS_FILE.name}, Ctrl+C — выход)", flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
