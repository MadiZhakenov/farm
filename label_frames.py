#!/usr/bin/env python3
"""
Разметка кадров в браузере: 1 — живое, 2 — сток, 3 — ИИ / 3D-рендер,
0 — непонятно (коллаж, скрин, текст). ← / Backspace — назад.
Каждый голос сразу пишется в <pack>/votes.json (можно закрыть и продолжить).

  python label_frames.py out/label_pack_20261005          # http://127.0.0.1:8766
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LABELS = {"1": "live", "2": "stock", "3": "ai", "0": "unclear"}

PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Разметка кадров</title>
<style>
  :root { --bg:#f4f3f0; --ink:#1d1d1f; --muted:#6e6e73; --card:#fff; --line:#e2e0db;
          --live:#2f9e5b; --stock:#c47a1d; --ai:#7b4bd6; --unc:#8a8a8f; }
  @media (prefers-color-scheme: dark) { :root { --bg:#151517; --ink:#f2f2f4; --muted:#9a9aa0;
          --card:#1f1f22; --line:#2e2e33; } }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.4 -apple-system,"Segoe UI",system-ui,sans-serif;
         height:100vh; display:flex; flex-direction:column; }
  header { display:flex; gap:16px; align-items:center; padding:10px 16px; border-bottom:1px solid var(--line); flex-wrap:wrap; }
  h1 { font-size:15px; margin:0; }
  .bar { flex:1; min-width:120px; height:6px; background:var(--line); border-radius:3px; overflow:hidden; }
  .bar i { display:block; height:100%; background:var(--live); width:0; }
  #stat { color:var(--muted); font-variant-numeric:tabular-nums; }
  main { flex:1; display:flex; min-height:0; }
  .stage { flex:1; display:flex; align-items:center; justify-content:center; padding:12px; min-height:0; }
  .stage img { max-width:100%; max-height:100%; object-fit:contain; border-radius:10px; box-shadow:0 2px 16px rgba(0,0,0,.18); }
  aside { width:300px; padding:14px 16px; border-left:1px solid var(--line); display:flex; flex-direction:column; gap:10px; overflow:auto; }
  .k { display:flex; gap:10px; align-items:flex-start; padding:10px; border:1px solid var(--line); border-radius:10px;
       background:var(--card); cursor:pointer; }
  .k b { display:inline-flex; width:28px; height:28px; border-radius:7px; align-items:center; justify-content:center;
         color:#fff; flex:none; font-size:15px; }
  .k small { color:var(--muted); display:block; }
  .k.on { outline:2px solid var(--ink); }
  .live b { background:var(--live); } .stock b { background:var(--stock); } .ai b { background:var(--ai); } .unc b { background:var(--unc); }
  .hint { color:var(--muted); font-size:13px; }
  #done { display:none; text-align:center; padding:40px; }
  @media (max-width: 760px) { main { flex-direction:column; } aside { width:auto; border-left:none; border-top:1px solid var(--line); } }
</style></head><body>
<header><h1>Разметка кадров</h1><div class="bar"><i id="prog"></i></div><span id="stat"></span></header>
<main>
  <div class="stage"><img id="img" alt=""><div id="done"><h2>Готово 🎉</h2><p>Все кадры размечены и сохранены. Можно закрыть страницу.</p></div></div>
  <aside>
    <div class="k live" data-l="live"><b>1</b><div>Живое<small>обычное фото с телефона, как у реального человека — годится в карусель</small></div></div>
    <div class="k stock" data-l="stock"><b>2</b><div>Сток<small>настоящее фото, но профи: постановка, реклама, каталог, глянец</small></div></div>
    <div class="k ai" data-l="ai"><b>3</b><div>ИИ / 3D<small>сгенерировано или отрендерено — не фотография</small></div></div>
    <div class="k unc" data-l="unclear"><b>0</b><div>Непонятно<small>коллаж, скриншот, текст, не разобрать</small></div></div>
    <div class="hint">← или Backspace — назад к прошлому кадру. Голос сохраняется сразу; можно закрыть и вернуться.</div>
    <div class="hint" id="counts"></div>
  </aside>
</main>
<script>
let pack = [], votes = {}, i = 0;
const $ = s => document.querySelector(s);
const keyMap = {"1":"live","2":"stock","3":"ai","0":"unclear"};
async function init() {
  const d = await (await fetch("/api/state")).json();
  pack = d.pack; votes = d.votes;
  i = pack.findIndex(p => !(p.pin_id in votes)); if (i < 0) i = pack.length;
  show();
}
function show() {
  const n = Object.keys(votes).length;
  $("#prog").style.width = (100 * n / pack.length) + "%";
  $("#stat").textContent = `${n} / ${pack.length}`;
  const c = {live:0, stock:0, ai:0, unclear:0}; for (const v of Object.values(votes)) c[v]++;
  $("#counts").textContent = `живое ${c.live} · сток ${c.stock} · ИИ ${c.ai} · непонятно ${c.unclear}`;
  if (i >= pack.length) { $("#img").style.display = "none"; $("#done").style.display = "block"; return; }
  $("#img").style.display = ""; $("#done").style.display = "none";
  $("#img").src = "/img/" + pack[i].file;
  document.querySelectorAll(".k").forEach(k => k.classList.toggle("on", votes[pack[i].pin_id] === k.dataset.l));
  for (let k = 1; k <= 3; k++) if (pack[i + k]) new Image().src = "/img/" + pack[i + k].file;
}
async function vote(label) {
  if (i >= pack.length) return;
  const pid = pack[i].pin_id;
  votes[pid] = label;
  i++; show();
  fetch("/api/vote", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({pin_id: pid, label})});
}
document.addEventListener("keydown", e => {
  if (keyMap[e.key]) { e.preventDefault(); vote(keyMap[e.key]); }
  else if (e.key === "ArrowLeft" || e.key === "Backspace") { e.preventDefault(); if (i > 0) { i--; show(); } }
  else if (e.key === "ArrowRight") { e.preventDefault(); if (i < pack.length) { i++; show(); } }
});
document.querySelectorAll(".k").forEach(k => k.onclick = () => vote(k.dataset.l));
init();
</script></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pack", type=Path)
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    pack_dir = args.pack.resolve()
    pack = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    votes_f = pack_dir / "votes.json"
    votes: dict[str, str] = json.loads(votes_f.read_text(encoding="utf-8")) if votes_f.exists() else {}
    lock = threading.Lock()
    public = [{"pin_id": r["pin_id"], "file": r["file"]} for r in pack]  # без оценок модели

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body: bytes, ctype: str, status=HTTPStatus.OK):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/state":
                with lock:
                    body = json.dumps({"pack": public, "votes": votes}, ensure_ascii=False)
                self._send(body.encode("utf-8"), "application/json; charset=utf-8")
            elif path.startswith("/img/"):
                f = pack_dir / "imgs" / Path(path[5:]).name
                if f.is_file():
                    self._send(f.read_bytes(), "image/jpeg")
                else:
                    self._send(b"", "text/plain", HTTPStatus.NOT_FOUND)
            else:
                self._send(b"", "text/plain", HTTPStatus.NOT_FOUND)

        def do_POST(self):
            if self.path != "/api/vote":
                return self._send(b"", "text/plain", HTTPStatus.NOT_FOUND)
            try:
                d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                pid, label = str(d["pin_id"]), str(d["label"])
                assert label in LABELS.values()
            except Exception:
                return self._send(b"bad", "text/plain", HTTPStatus.BAD_REQUEST)
            with lock:
                votes[pid] = label
                tmp = votes_f.with_suffix(".tmp")
                tmp.write_text(json.dumps(votes, ensure_ascii=False, indent=0), encoding="utf-8")
                tmp.replace(votes_f)
            self._send(b"ok", "text/plain")

    class Server(ThreadingHTTPServer):
        allow_reuse_address = False

    url = f"http://127.0.0.1:{args.port}/"
    srv = Server(("127.0.0.1", args.port), H)
    print(f"разметка: {url} · {len(pack)} кадров, уже размечено {len(votes)} · голоса → {votes_f}")
    if not args.no_open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
