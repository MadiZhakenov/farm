#!/usr/bin/env python3
"""
Build a large HTML taste-label pack from unseen clean/agent photos.

Usage:
  python build_taste_label_pack.py --n 1000
  python build_taste_label_pack.py --n 1000 --band 0.40 0.70 --fill
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import time
from datetime import datetime
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
CLEAN = ROOT / "data" / "cache" / "clean_photos"
AGENT = OUT / "agent_sessions"
EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def pin_guess(p: Path) -> str:
    for part in p.stem.replace("-", "_").split("_"):
        if part.isdigit() and len(part) >= 6:
            return part
    return p.stem


def load_seen_pins() -> set[str]:
    seen: set[str] = set()
    for vp in OUT.rglob("taste_votes_*.json"):
        try:
            data = json.loads(vp.read_text(encoding="utf-8"))
        except Exception:
            continue
        for row in data.get("detail") or []:
            if (row.get("human") or "").strip().lower() not in (
                "keep",
                "stock",
                "wrong",
            ):
                continue
            pid = str(row.get("pin_id") or "").strip()
            if pid:
                seen.add(pid)
    return seen


def collect_pool(seen: set[str]) -> list[Path]:
    pool: list[Path] = []
    if CLEAN.is_dir():
        for p in CLEAN.iterdir():
            if p.is_file() and p.suffix.lower() in EXTS and not p.name.startswith("_"):
                pool.append(p)
    if AGENT.is_dir():
        for p in AGENT.rglob("*"):
            if not (
                p.is_file()
                and p.suffix.lower() in EXTS
                and not p.name.startswith("_")
            ):
                continue
            parts = {x.lower() for x in p.parts}
            if "carousel" in parts and "pool" not in parts:
                continue
            pool.append(p)
    uniq = {str(p.resolve()): p for p in pool}
    out: list[Path] = []
    for p in uniq.values():
        if pin_guess(p) in seen:
            continue
        out.append(p)
    return out


def score_paths(
    paths: list[Path], *, batch: int = 24
) -> list[tuple[Path, float]]:
    from core.ugc_classifier import get_ugc_live_classifier

    clf = get_ugc_live_classifier()
    if not clf.is_trained:
        raise SystemExit("ugc model not trained")
    scored: list[tuple[Path, float]] = []
    t0 = time.perf_counter()
    for i in range(0, len(paths), batch):
        chunk = paths[i : i + batch]
        imgs: list[Image.Image] = []
        ok: list[Path] = []
        for p in chunk:
            try:
                im = Image.open(p).convert("RGB")
                im.load()
                imgs.append(im)
                ok.append(p)
            except Exception:
                continue
        if not imgs:
            continue
        for p, sc in zip(ok, clf.predict_live_scores(imgs)):
            scored.append((p, float(sc)))
        done = min(i + batch, len(paths))
        if done % 200 < batch or done == len(paths):
            dt = time.perf_counter() - t0
            print(f"  scored {done}/{len(paths)} ({dt:.0f}s)")
    return scored


def pick(
    scored: list[tuple[Path, float]],
    n: int,
    lo: float,
    hi: float,
    fill: bool,
) -> list[tuple[Path, float]]:
    mid = [(p, s) for p, s in scored if lo <= s <= hi]
    mid.sort(key=lambda x: abs(x[1] - 0.55))
    picked = mid[:n]
    if fill and len(picked) < n:
        rest = [(p, s) for p, s in scored if not (lo <= s <= hi)]
        # prefer closer to band edges
        rest.sort(key=lambda x: min(abs(x[1] - lo), abs(x[1] - hi)))
        need = n - len(picked)
        picked.extend(rest[:need])
    return picked[:n]


def write_html(run_dir: Path, run_name: str, items: list[dict]) -> Path:
    items_json = json.dumps(items, ensure_ascii=False)
    page = f"""<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Taste pack — {run_name}</title>
<style>
:root {{ --bg:#0e0f12; --panel:#171a21; --text:#e8eaed; --muted:#8b93a7;
  --keep:#3ddc97; --stock:#e85d5d; --wrong:#f0c14b; }}
* {{ box-sizing:border-box; }}
html,body {{ margin:0; height:100%; background:var(--bg); color:var(--text);
  font-family:"Segoe UI",system-ui,sans-serif; }}
body {{ display:flex; flex-direction:column; }}
header {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap;
  padding:10px 16px; background:var(--panel); border-bottom:1px solid #2a2f3a;
  position:sticky; top:0; z-index:5; }}
header h1 {{ font-size:15px; margin:0; font-weight:600; }}
.stats {{ color:var(--muted); font-size:13px; }}
.stats b {{ color:var(--text); }}
.stats .k {{ color:var(--keep); }} .stats .s {{ color:var(--stock); }}
.stats .w {{ color:var(--wrong); }}
.grow {{ flex:1; }}
header button {{ background:#252a36; color:var(--text); border:1px solid #3a4150;
  border-radius:8px; padding:8px 12px; cursor:pointer; font-size:13px; }}
header .vote-btns {{ display:flex; gap:8px; }}
header .vote-btns button {{
  border:none; border-radius:8px; padding:8px 14px; cursor:pointer;
  font-size:13px; font-weight:800;
}}
header .vote-btns .keep {{ background:var(--keep); color:#0e0f12; }}
header .vote-btns .stock {{ background:var(--stock); color:#fff; }}
header .vote-btns .wrong {{ background:var(--wrong); color:#1a1400; }}
main {{ flex:1; display:grid; grid-template-columns:1fr 300px; min-height:0; }}
@media(max-width:900px){{ main {{ grid-template-columns:1fr; }} }}
.stage {{
  display:flex; flex-direction:column; align-items:center; justify-content:center;
  padding:12px 12px 8px; background:#0a0b0e; gap:12px; min-height:0;
}}
.stage img {{
  max-width:100%; max-height:calc(100vh - 260px); object-fit:contain;
  border-radius:6px; box-shadow:0 8px 40px rgba(0,0,0,.5);
}}
.bar-keys {{
  display:grid; grid-template-columns:1fr 1fr 1fr 0.7fr; gap:10px;
  width:min(920px, 100%); flex-shrink:0;
}}
.bar-keys button {{
  border:none; border-radius:12px; padding:18px 10px; cursor:pointer;
  font-size:18px; font-weight:800; color:#0e0f12;
}}
.bar-keys .keep {{ background:var(--keep); }}
.bar-keys .stock {{ background:var(--stock); color:#fff; }}
.bar-keys .wrong {{ background:var(--wrong); color:#1a1400; }}
.bar-keys .skip {{ background:#2c3342; color:var(--muted); font-weight:700; }}
.side {{ background:var(--panel); border-left:1px solid #2a2f3a;
  padding:14px 16px; overflow:auto; display:flex; flex-direction:column; gap:10px; }}
.meta {{ font-size:12px; color:var(--muted); line-height:1.45; }}
.meta .topic {{ color:var(--text); font-size:14px; font-weight:600; margin-bottom:6px; }}
.meta .slide-text {{ color:#c5cad6; font-size:11px; margin:8px 0; word-break:break-all; }}
.keys {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
.keys button {{ border:none; border-radius:10px; padding:16px 10px; cursor:pointer;
  font-size:15px; font-weight:700; color:#0e0f12; }}
.keys .keep {{ background:var(--keep); }}
.keys .stock {{ background:var(--stock); color:#fff; }}
.keys .wrong {{ background:var(--wrong); color:#1a1400; grid-column:1/-1; }}
.keys .skip {{ background:#2c3342; color:var(--muted); grid-column:1/-1; font-weight:600; }}
.hint {{ font-size:12px; color:var(--muted); line-height:1.5; }}
.hint kbd {{ background:#252a36; border:1px solid #3a4150; border-radius:4px;
  padding:1px 6px; font-size:11px; color:var(--text); }}
.progress {{ height:4px; background:#252a36; }}
.progress>div {{ height:100%; background:var(--keep); width:0%; }}
.done-banner {{ display:none; padding:20px; text-align:center; color:var(--keep);
  font-size:18px; font-weight:700; }}
.pill {{ display:inline-block; padding:2px 8px; border-radius:999px;
  background:#252a36; font-size:11px; color:var(--muted); margin-right:4px; }}
</style></head><body>
<header>
  <h1>Taste · {run_name}</h1>
  <div class="stats">
    <span id="pos">0</span>/<span id="total">{len(items)}</span>
    · marked <b id="nMarked">0</b>
    · <span class="k">keep <b id="nKeep">0</b></span>
    · <span class="s">stock <b id="nStock">0</b></span>
    · <span class="w">junk <b id="nWrong">0</b></span>
  </div>
  <div class="grow"></div>
  <div class="vote-btns">
    <button type="button" class="keep" data-v="keep">1 KEEP</button>
    <button type="button" class="stock" data-v="stock">2 STOCK</button>
    <button type="button" class="wrong" data-v="wrong">3 JUNK</button>
  </div>
  <button type="button" id="btnUnlabeled">К неразмеченным</button>
  <button type="button" id="btnExport">Export JSON</button>
  <button type="button" id="btnReset">Reset</button>
</header>
<div class="progress"><div id="bar"></div></div>
<main>
  <div class="stage">
    <img id="img" alt="photo" decoding="async" />
    <div class="done-banner" id="done">Готово — Export JSON</div>
    <div class="bar-keys">
      <button type="button" class="keep" data-v="keep">1 · KEEP</button>
      <button type="button" class="stock" data-v="stock">2 · STOCK</button>
      <button type="button" class="wrong" data-v="wrong">3 · JUNK</button>
      <button type="button" class="skip" data-v="skip">Space</button>
    </div>
  </div>
  <aside class="side">
    <div class="meta">
      <div class="topic" id="topic"></div>
      <div>
        <span class="pill" id="slidePill"></span>
        <span class="pill" id="ugcPill"></span>
        <span class="pill" id="modePill"></span>
      </div>
      <div class="slide-text" id="slideText"></div>
    </div>
    <div class="keys">
      <button type="button" class="keep" data-v="keep">1 · KEEP</button>
      <button type="button" class="stock" data-v="stock">2 · STOCK</button>
      <button type="button" class="wrong" data-v="wrong">3 · JUNK / LQ</button>
      <button type="button" class="skip" data-v="skip">Space · skip</button>
    </div>
    <div class="hint">
      Кнопки под фото / в шапке / справа · клавиши работают на RU раскладке.<br/>
      <kbd>1</kbd>/<kbd>A</kbd> keep · <kbd>2</kbd>/<kbd>S</kbd> stock · <kbd>3</kbd>/<kbd>D</kbd> junk<br/>
      <kbd>←</kbd>/<kbd>→</kbd> · <kbd>Z</kbd> undo · autosave localStorage
    </div>
  </aside>
</main>
<script>
const ITEMS = {items_json};
const KEY = "taste_label_{run_name}_v1";
const RUN = "{run_name}";
let i = 0;
const undoStack = [];
function load() {{
  try {{ return JSON.parse(localStorage.getItem(KEY) || "{{}}") || {{}}; }}
  catch (e) {{ return {{}}; }}
}}
function save(v) {{ localStorage.setItem(KEY, JSON.stringify(v)); }}
function stats() {{
  const v = load();
  let k=0,s=0,w=0;
  for (const x of Object.values(v)) {{
    if (x === "keep") k++; else if (x === "stock") s++; else if (x === "wrong") w++;
  }}
  const m = k+s+w;
  document.getElementById("nMarked").textContent = m;
  document.getElementById("nKeep").textContent = k;
  document.getElementById("nStock").textContent = s;
  document.getElementById("nWrong").textContent = w;
  document.getElementById("bar").style.width = (100 * m / Math.max(1, ITEMS.length)) + "%";
}}
function show(idx) {{
  if (idx < 0) idx = 0;
  if (idx >= ITEMS.length) {{
    i = ITEMS.length;
    document.getElementById("img").style.display = "none";
    document.getElementById("done").style.display = "block";
    document.getElementById("pos").textContent = ITEMS.length;
    stats(); return;
  }}
  document.getElementById("done").style.display = "none";
  document.getElementById("img").style.display = "block";
  i = idx;
  const it = ITEMS[i];
  document.getElementById("img").src = it.img;
  document.getElementById("pos").textContent = String(i+1);
  document.getElementById("total").textContent = String(ITEMS.length);
  document.getElementById("topic").textContent = it.topic;
  document.getElementById("slideText").textContent = it.src || "";
  document.getElementById("slidePill").textContent = "#" + it.slide;
  document.getElementById("ugcPill").textContent =
    it.ugc != null ? ("ugc " + Math.round(it.ugc*100) + "%") : "ugc —";
  document.getElementById("modePill").textContent = it.mode || "—";
  for (let j = 1; j <= 3; j++) {{
    if (i+j < ITEMS.length) {{ const im = new Image(); im.src = ITEMS[i+j].img; }}
  }}
  stats();
}}
function vote(label) {{
  if (i >= ITEMS.length) return;
  const it = ITEMS[i];
  const v = load();
  undoStack.push({{ id: it.id, prev: v[it.id] || null, idx: i }});
  if (label === "skip") {{ show(i+1); return; }}
  v[it.id] = label; save(v); show(i+1);
}}
function undo() {{
  const last = undoStack.pop();
  if (!last) return;
  const v = load();
  if (last.prev == null) delete v[last.id]; else v[last.id] = last.prev;
  save(v); show(last.idx);
}}
function jumpUnlabeled() {{
  const v = load();
  for (let j = 0; j < ITEMS.length; j++) {{
    if (!v[ITEMS[j].id]) {{ show(j); return; }}
  }}
  show(ITEMS.length);
}}
document.querySelectorAll("button[data-v]").forEach(btn => {{
  btn.addEventListener("click", () => vote(btn.getAttribute("data-v")));
}});
document.getElementById("btnExport").addEventListener("click", () => {{
  const v = load();
  const detail = ITEMS.map(it => ({{
    id: it.id, carousel: it.carousel, slide: it.slide, pin_id: it.pin_id,
    topic: it.topic, text: it.text, img: it.img, ugc: it.ugc, mode: it.mode,
    src: it.src || null, human: v[it.id] || null,
  }}));
  let k=0,s=0,w=0;
  for (const d of detail) {{
    if (d.human === "keep") k++;
    else if (d.human === "stock") s++;
    else if (d.human === "wrong") w++;
  }}
  const payload = {{
    run: RUN, exported_at: new Date().toISOString(),
    marked: k+s+w, keep: k, stock: s, wrong: w, votes: v, detail,
  }};
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {{type:"application/json"}}));
  a.download = "taste_votes_" + RUN + ".json";
  a.click();
}});
document.getElementById("btnReset").addEventListener("click", () => {{
  if (!confirm("Сбросить все оценки?")) return;
  localStorage.removeItem(KEY); undoStack.length = 0; show(0);
}});
document.getElementById("btnUnlabeled").addEventListener("click", jumpUnlabeled);
window.addEventListener("keydown", e => {{
  if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;
  const k = e.key;
  const c = e.code;
  if (k === "1" || c === "Digit1" || c === "Numpad1") {{ e.preventDefault(); vote("keep"); }}
  else if (k === "2" || c === "Digit2" || c === "Numpad2") {{ e.preventDefault(); vote("stock"); }}
  else if (k === "3" || c === "Digit3" || c === "Numpad3") {{ e.preventDefault(); vote("wrong"); }}
  else if (c === "KeyA") {{ e.preventDefault(); vote("keep"); }}
  else if (c === "KeyS") {{ e.preventDefault(); vote("stock"); }}
  else if (c === "KeyD") {{ e.preventDefault(); vote("wrong"); }}
  else if (k === "ArrowRight" || k === " " || k === "Spacebar" || c === "Space") {{ e.preventDefault(); vote("skip"); }}
  else if (k === "ArrowLeft") {{ e.preventDefault(); show(i-1); }}
  else if (k === "z" || k === "Z" || c === "KeyZ") {{ e.preventDefault(); undo(); }}
}});
jumpUnlabeled();
</script></body></html>
"""
    path = run_dir / "label_taste.html"
    path.write_text(page, encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--band", nargs=2, type=float, default=[0.40, 0.70])
    ap.add_argument(
        "--fill",
        action="store_true",
        default=True,
        help="fill remaining slots outside band",
    )
    ap.add_argument("--no-fill", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    fill = not args.no_fill
    lo, hi = float(args.band[0]), float(args.band[1])
    seed = args.seed or (int(time.time()) % 10_000_000)
    random.seed(seed)

    seen = load_seen_pins()
    cands = collect_pool(seen)
    random.shuffle(cands)
    print(f"seen_pins={len(seen)} unseen={len(cands)} target={args.n} band=[{lo},{hi}] fill={fill}")
    if len(cands) < 50:
        raise SystemExit("too few unseen photos")

    # score all unseen (or cap scan a bit above n*1.5 for speed if huge)
    scan = cands if len(cands) <= max(args.n * 2, 1500) else cands[: max(args.n * 2, 1500)]
    print(f"scoring {len(scan)}…")
    scored = score_paths(scan)
    picked = pick(scored, args.n, lo, hi, fill)
    print(f"picked={len(picked)} mid_in_band={sum(1 for _,s in picked if lo<=s<=hi)}")

    run_name = f"taste_pack_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = OUT / run_name
    photos = run_dir / "photos"
    photos.mkdir(parents=True, exist_ok=True)

    items: list[dict] = []
    for i, (src, ugc) in enumerate(picked):
        pid = pin_guess(src)
        dest_name = f"{i:04d}_{pid}{src.suffix.lower()}"
        dest = photos / dest_name
        shutil.copy2(src, dest)
        try:
            rel = str(src.relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            rel = src.name
        in_band = lo <= ugc <= hi
        items.append(
            {
                "id": f"pack_{i:04d}_{pid}",
                "carousel": "pack",
                "slide": i + 1,
                "topic": "mid-band" if in_band else "fill",
                "text": rel,
                "query": "",
                "img": f"photos/{dest_name}",
                "ugc": round(ugc, 3),
                "rel": None,
                "mode": "midband" if in_band else "fill",
                "pin_id": pid,
                "src": rel,
            }
        )

    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run": run_name,
                "n": len(items),
                "seed": seed,
                "band": [lo, hi],
                "fill": fill,
                "items": items,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    html_path = write_html(run_dir, run_name, items)
    ugcs = [it["ugc"] for it in items]
    print(f"wrote {html_path}")
    print(
        f"run={run_name} n={len(items)} "
        f"ugc {min(ugcs):.3f}–{max(ugcs):.3f} mean={sum(ugcs)/len(ugcs):.3f}"
    )
    print(html_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
