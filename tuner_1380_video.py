#!/usr/bin/env python3
"""1380 v2 видео: тюнер смен фото и куска песни.
Сверху вся песня — тянешь зелёный блок, и весь ролик едет по песне (какой кусок звучит).
Снизу крупно этот кусок — тянешь любую линию: зелёная — старт звука и 1-е фото, белые — смены фото, красная — конец ролика.
Сохраняет downloads/1380/music/_tuner.json, его берёт build_1380_video.py.
  python tuner_1380_video.py                 # http://127.0.0.1:8771
  python tuner_1380_video.py --variant 7s    # http://127.0.0.1:8772 — 7 с: фото на полудолях, CTA ≤ 1.5 с в конце"""

from __future__ import annotations

import io
import json
import os
import re
import sys
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1380_video as V  # noqa: E402

VARIANT = "7s" if "--variant" in sys.argv and sys.argv[sys.argv.index("--variant") + 1] == "7s" else ""
V.set_variant(VARIANT)
SAVE = V.TUNE
BEATS_JSON = V.MUSIC.parent / "_beats.json"
HTML = ROOT / "tuner_1380_video.html"
WORK = ROOT / "output" / "_work" / "1380v2_video"
PORT = 8772 if VARIANT == "7s" else 8771


def beats() -> dict:
    if BEATS_JSON.exists():
        return json.loads(BEATS_JSON.read_text(encoding="utf-8"))
    import librosa
    import numpy as np
    y, sr = librosa.load(str(V.MUSIC), sr=22050, mono=True)
    env = librosa.onset.onset_strength(y=y, sr=sr)
    _, fr = librosa.beat.beat_track(onset_envelope=env, sr=sr)
    t = librosa.frames_to_time(fr, sr=sr)
    s = env[fr] / (np.percentile(env[fr], 95) or 1) * 10
    d = {"beats": [round(float(x), 3) for x in t], "hit": [round(float(x), 2) for x in s]}
    BEATS_JSON.write_text(json.dumps(d), encoding="utf-8")
    return d


def plan_rows() -> list[dict]:
    p = WORK / "plan.json"
    if p.exists():
        rows = json.loads(p.read_text(encoding="utf-8"))
        if len(rows) >= 100:
            return rows
    return V.plan(100, 13803)


ROWS = plan_rows()
OV = V.overlays(WORK)


@lru_cache(maxsize=400)
def frame(v: int, k: int) -> bytes:
    """Кадр k ролика v — как в рендере (масштаб, сдвиг, текст), уменьшенный до 540×960."""
    s = ROWS[v - 1]["shots"][k]
    im = Image.open(ROOT / s["photo"]).convert("RGB")
    sw = round(1434 * s["z0"] / 2) * 2
    sh = round(sw * 1200 / 896 / 2) * 2
    x, y = round((sw - V.W) * s["cx"]), round((sh - V.H) * s["cy"])
    im = im.resize((sw, sh), Image.Resampling.LANCZOS).crop((x, y, x + V.W, y + V.H)).convert("RGBA")
    key = "male" if k < V.N_MALE else "female" if k < V.N_MALE + V.CTA_FROM - 1 else "cta"
    im.alpha_composite(Image.open(OV[key]).convert("RGBA"))
    b = io.BytesIO()
    im.convert("RGB").resize((540, 960), Image.Resampling.LANCZOS).save(b, "JPEG", quality=84)
    return b.getvalue()


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
            d = V.defaults()
            saved = json.loads(SAVE.read_text(encoding="utf-8")) if SAVE.exists() else d
            b = beats()
            return self._send(200, json.dumps({"beats": b["beats"], "hits": b["hit"], **saved, "defaults": d,
                                               "n_male": V.N_MALE, "n_female": V.N_FEMALE, "cta_from": V.CTA_FROM,
                                               "videos": len(ROWS), "variant": VARIANT, "cta_max": V.CTA_MAX,
                                               "target": V.TARGET}).encode(), "application/json")
        if self.path == "/media/song":
            return self._send(200, V.MUSIC.read_bytes(), "audio/mpeg")
        if m := re.fullmatch(r"/media/frame/(\d+)/(\d+)", self.path):
            v, k = int(m[1]), int(m[2])
            if 1 <= v <= len(ROWS) and 0 <= k < V.N_MALE + V.N_FEMALE:
                return self._send(200, frame(v, k), "image/jpeg")
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/api/save":
            return self._send(404, b"not found", "text/plain")
        d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        cuts = [round(float(x), 3) for x in d["cuts"]]
        if len(cuts) != V.N_MALE + V.N_FEMALE - 1:
            return self._send(400, b"bad cuts", "text/plain")
        data = {"start": round(float(d["start"]), 3), "cuts": cuts, "end": round(float(d["end"]), 3)}
        tmp = SAVE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, SAVE)
        self._send(200, b"{}", "application/json")


if __name__ == "__main__":
    beats()
    print(f"http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
