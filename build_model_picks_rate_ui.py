#!/usr/bin/env python3
"""Add YES/NO rating UI to model_picks gallery."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out" / "model_picks_20260928_101407"
data = json.loads((run_dir / "picks.json").read_text(encoding="utf-8"))
items = data.get("items") or []
items_json = json.dumps(items, ensure_ascii=False)
run_name = run_dir.name
n = len(items)

html = f"""<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Model picks — rate {n}</title>
<style>
:root {{
  --bg:#0e0f12; --panel:#171a21; --text:#e8eaed; --muted:#8b93a7;
  --yes:#3ddc97; --no:#e85d5d;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font-family:"Segoe UI",system-ui,sans-serif; }}
header {{
  display:flex; align-items:center; gap:12px; flex-wrap:wrap;
  padding:12px 16px; background:var(--panel); border-bottom:1px solid #2a2f3a;
  position:sticky; top:0; z-index:5;
}}
h1 {{ margin:0; font-size:16px; font-weight:600; }}
.stats {{ color:var(--muted); font-size:13px; }}
.stats b {{ color:var(--text); }}
.stats .y {{ color:var(--yes); }} .stats .n {{ color:var(--no); }}
.grow {{ flex:1; }}
header button {{
  background:#252a36; color:var(--text); border:1px solid #3a4150;
  border-radius:8px; padding:8px 12px; cursor:pointer; font-size:13px;
}}
.hint {{ width:100%; color:var(--muted); font-size:12px; }}
.hint kbd {{ background:#252a36; border:1px solid #3a4150; border-radius:4px; padding:1px 5px; }}
.progress {{ height:4px; background:#252a36; }}
.progress > div {{ height:100%; background:var(--yes); width:0%; }}
.grid {{
  display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr));
  gap:14px; padding:16px;
}}
.card {{
  background:var(--panel); border-radius:10px; overflow:hidden;
  border:2px solid #2a2f3a; display:flex; flex-direction:column;
}}
.card.yes {{ border-color:var(--yes); }}
.card.no {{ border-color:var(--no); }}
.card .rank {{ padding:8px 10px 0; font-size:13px; font-weight:700; color:var(--yes); }}
.card img {{
  width:100%; aspect-ratio:3/4; object-fit:cover; display:block; background:#0a0b0e;
  cursor:pointer;
}}
.card .meta {{ padding:6px 10px; font-size:11px; color:var(--muted); word-break:break-all; min-height:2.4em; }}
.card .btns {{
  display:grid; grid-template-columns:1fr 1fr; gap:8px; padding:0 10px 10px;
}}
.card .btns button {{
  border:none; border-radius:8px; padding:12px 8px; cursor:pointer;
  font-size:15px; font-weight:800;
}}
.card .btns .yes {{ background:var(--yes); color:#0e0f12; }}
.card .btns .no {{ background:var(--no); color:#fff; }}
.card.yes .btns .yes {{ outline:2px solid #fff; outline-offset:1px; }}
.card.no .btns .no {{ outline:2px solid #fff; outline-offset:1px; }}
.lightbox {{
  display:none; position:fixed; inset:0; background:rgba(0,0,0,.92);
  z-index:20; align-items:center; justify-content:center; flex-direction:column; gap:12px; padding:20px;
}}
.lightbox.on {{ display:flex; }}
.lightbox img {{ max-width:95vw; max-height:78vh; object-fit:contain; border-radius:6px; }}
.lightbox .lb-btns {{ display:flex; gap:12px; }}
.lightbox .lb-btns button {{
  border:none; border-radius:10px; padding:14px 28px; cursor:pointer;
  font-size:18px; font-weight:800;
}}
.lightbox .lb-btns .yes {{ background:var(--yes); color:#0e0f12; }}
.lightbox .lb-btns .no {{ background:var(--no); color:#fff; }}
</style>
</head><body>
<header>
  <h1>Оценка пиков модели · {run_name}</h1>
  <div class="stats">
    marked <b id="nMarked">0</b>/{n}
    · <span class="y">ДА <b id="nYes">0</b></span>
    · <span class="n">НЕТ <b id="nNo">0</b></span>
  </div>
  <div class="grow"></div>
  <button type="button" id="btnUnlabeled">К неразмеченным</button>
  <button type="button" id="btnExport">Export JSON</button>
  <button type="button" id="btnReset">Reset</button>
  <div class="hint">На карточке: ДА / НЕТ. Клик по фото — зум. В зуме <kbd>1</kbd>/<kbd>Y</kbd>=ДА · <kbd>2</kbd>/<kbd>N</kbd>=НЕТ · ←/→ · Esc</div>
</header>
<div class="progress"><div id="bar"></div></div>
<div class="grid" id="grid"></div>
<div class="lightbox" id="lb">
  <img id="lbImg" alt="" />
  <div class="lb-btns">
    <button type="button" class="yes" id="lbYes">1 · ДА</button>
    <button type="button" class="no" id="lbNo">2 · НЕТ</button>
  </div>
</div>
<script>
const ITEMS = {items_json};
const KEY = "model_picks_rate_{run_name}_v1";
const RUN = "{run_name}";
let focusIdx = 0;

function load() {{
  try {{ return JSON.parse(localStorage.getItem(KEY) || "{{}}") || {{}}; }}
  catch (e) {{ return {{}}; }}
}}
function save(v) {{ localStorage.setItem(KEY, JSON.stringify(v)); }}
function vid(it) {{ return String(it.pin_id) + "_" + String(it.rank); }}

function stats() {{
  const v = load();
  let y = 0, n = 0;
  for (const x of Object.values(v)) {{
    if (x === "yes") y++; else if (x === "no") n++;
  }}
  document.getElementById("nMarked").textContent = y + n;
  document.getElementById("nYes").textContent = y;
  document.getElementById("nNo").textContent = n;
  document.getElementById("bar").style.width = (100 * (y + n) / Math.max(1, ITEMS.length)) + "%";
}}

function vote(id, label) {{
  const v = load();
  v[id] = label;
  save(v);
  const card = document.querySelector('.card[data-id="' + CSS.escape(id) + '"]');
  if (card) {{
    card.classList.remove("yes", "no");
    card.classList.add(label);
  }}
  stats();
}}

function render() {{
  const v = load();
  const grid = document.getElementById("grid");
  const parts = [];
  for (let idx = 0; idx < ITEMS.length; idx++) {{
    const it = ITEMS[idx];
    const id = vid(it);
    const hum = v[id] || "";
    const cls = hum === "yes" ? " yes" : hum === "no" ? " no" : "";
    const ugc = Math.round((it.ugc || 0) * 100);
    parts.push(
      '<article class="card' + cls + '" data-id="' + id + '" data-idx="' + idx + '">' +
      '<div class="rank">#' + it.rank + ' · ugc ' + ugc + '% · batch ' + (it.batch || 1) + '</div>' +
      '<img src="' + it.img + '" loading="lazy" data-full="' + it.img + '" data-idx="' + idx + '" alt="" />' +
      '<div class="meta">' + (it.src || "") + '</div>' +
      '<div class="btns">' +
      '<button type="button" class="yes" data-v="yes" data-id="' + id + '">ДА</button>' +
      '<button type="button" class="no" data-v="no" data-id="' + id + '">НЕТ</button>' +
      '</div></article>'
    );
  }}
  grid.innerHTML = parts.join("");
  stats();
}}

function openLb(idx) {{
  focusIdx = idx;
  document.getElementById("lbImg").src = ITEMS[idx].img;
  document.getElementById("lb").classList.add("on");
}}
function closeLb() {{ document.getElementById("lb").classList.remove("on"); }}

document.getElementById("grid").addEventListener("click", (e) => {{
  const btn = e.target.closest("button[data-v]");
  if (btn) {{ vote(btn.getAttribute("data-id"), btn.getAttribute("data-v")); return; }}
  const img = e.target.closest("img[data-full]");
  if (img) openLb(Number(img.getAttribute("data-idx") || 0));
}});

document.getElementById("lbYes").addEventListener("click", (e) => {{
  e.stopPropagation();
  vote(vid(ITEMS[focusIdx]), "yes");
  if (focusIdx < ITEMS.length - 1) openLb(focusIdx + 1); else closeLb();
}});
document.getElementById("lbNo").addEventListener("click", (e) => {{
  e.stopPropagation();
  vote(vid(ITEMS[focusIdx]), "no");
  if (focusIdx < ITEMS.length - 1) openLb(focusIdx + 1); else closeLb();
}});
document.getElementById("lb").addEventListener("click", (e) => {{
  if (e.target.id === "lb" || e.target.id === "lbImg") closeLb();
}});

window.addEventListener("keydown", (e) => {{
  const lbOn = document.getElementById("lb").classList.contains("on");
  if (!lbOn) return;
  const c = e.code;
  if (e.key === "Escape") {{ closeLb(); return; }}
  if (e.key === "1" || c === "Digit1" || c === "KeyY") {{
    e.preventDefault(); vote(vid(ITEMS[focusIdx]), "yes");
    if (focusIdx < ITEMS.length - 1) openLb(focusIdx + 1); else closeLb();
  }} else if (e.key === "2" || c === "Digit2" || c === "KeyN") {{
    e.preventDefault(); vote(vid(ITEMS[focusIdx]), "no");
    if (focusIdx < ITEMS.length - 1) openLb(focusIdx + 1); else closeLb();
  }} else if (e.key === "ArrowRight") {{
    e.preventDefault(); openLb(Math.min(ITEMS.length - 1, focusIdx + 1));
  }} else if (e.key === "ArrowLeft") {{
    e.preventDefault(); openLb(Math.max(0, focusIdx - 1));
  }}
}});

document.getElementById("btnExport").addEventListener("click", () => {{
  const v = load();
  const detail = ITEMS.map(it => {{
    const id = vid(it);
    return Object.assign({{}}, it, {{ id: id, human: v[id] || null }});
  }});
  let y = 0, n = 0;
  for (const d of detail) {{
    if (d.human === "yes") y++; else if (d.human === "no") n++;
  }}
  const payload = {{
    run: RUN,
    type: "model_picks_yes_no",
    exported_at: new Date().toISOString(),
    marked: y + n, yes: y, no: n,
    model_precision: (y + n) ? (y / (y + n)) : null,
    votes: v, detail: detail,
  }};
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {{ type: "application/json" }}));
  a.download = "model_picks_votes_" + RUN + ".json";
  a.click();
}});

document.getElementById("btnReset").addEventListener("click", () => {{
  if (!confirm("Сбросить все ДА/НЕТ?")) return;
  localStorage.removeItem(KEY);
  render();
}});

document.getElementById("btnUnlabeled").addEventListener("click", () => {{
  const v = load();
  for (let i = 0; i < ITEMS.length; i++) {{
    const id = vid(ITEMS[i]);
    if (!v[id]) {{
      const el = document.querySelector('.card[data-id="' + CSS.escape(id) + '"]');
      if (el) el.scrollIntoView({{ behavior: "smooth", block: "center" }});
      return;
    }}
  }}
  alert("Всё размечено");
}});

render();
</script>
</body></html>
"""

out = run_dir / "gallery.html"
out.write_text(html, encoding="utf-8")
print(f"wrote {out} n={n}")
