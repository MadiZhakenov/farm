#!/usr/bin/env python3
"""Build carousel_ranking.html + carousel_ranking_data.json from downloaded_carousels/_all."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ALL_DIR = ROOT / "downloaded_carousels" / "_all"
OUT_HTML = ROOT / "carousel_ranking.html"
OUT_JSON = ROOT / "carousel_ranking_data.json"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def list_slides(folder: Path) -> list[str]:
    files: dict[int, Path] = {}
    for p in folder.iterdir():
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and p.stem.isdigit():
            files[int(p.stem)] = p
    return [f"downloaded_carousels/_all/{folder.name}/{files[i].name}" for i in sorted(files)]


def load_meta(folder: Path) -> dict:
    p = folder / "meta.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def main() -> None:
    items = []
    folders = sorted([p for p in ALL_DIR.iterdir() if p.is_dir()], key=lambda p: p.name.lower())
    for i, folder in enumerate(folders, 1):
        meta = load_meta(folder)
        metrics = meta.get("metrics") or {}
        views = int(metrics.get("views") or meta.get("views") or 0)
        likes = int(metrics.get("likes") or meta.get("likes") or 0)
        saves = int(
            metrics.get("saves")
            or metrics.get("bookmarks")
            or meta.get("saves")
            or meta.get("bookmarks")
            or 0
        )
        slides = list_slides(folder)
        if not slides and meta.get("slide_count"):
            # still include missing ones so ranking is complete
            pass
        save_rate = round(saves / views, 6) if views > 0 else 0.0
        like_rate = round(likes / views, 6) if views > 0 else 0.0
        items.append(
            {
                "id": str(meta.get("original_id") or meta.get("id") or folder.name[-8:]),
                "folder": folder.name,
                "title": meta.get("title") or folder.name,
                "creator": str(meta.get("creator_unique_id") or "").strip("@") or "unknown",
                "niche": (meta.get("niche") or "unknown").strip() or "unknown",
                "product": str(meta.get("product_medium") or "None"),
                "audience": str(meta.get("audience_region") or ""),
                "views": views,
                "likes": likes,
                "saves": saves,
                "slides_n": len(slides) or int(meta.get("slide_count") or 0),
                "save_rate": save_rate,
                "like_rate": like_rate,
                "slides": slides,
            }
        )
        if i % 1000 == 0 or i == len(folders):
            print(f"\rindexed {i}/{len(folders)}", end="", flush=True)
    print()

    OUT_JSON.write_text(json.dumps(items, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUT_JSON} ({OUT_JSON.stat().st_size/1e6:.1f} MB, {len(items)} carousels)")

    # Embed data so file:// open works without a local server
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    html = (
        HTML_TEMPLATE.replace("__COUNT__", str(len(items))).replace(
            "/*__DATA__*/",
            f"window.CAROUSEL_DATA = {payload};",
        )
    )
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT_HTML} ({OUT_HTML.stat().st_size/1e6:.1f} MB)")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ReelFarm — рейтинг каруселей</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,500;9..144,700&display=swap" rel="stylesheet" />
<style>
:root {
  --bg0: #0f1412;
  --bg1: #171e1a;
  --bg2: #1f2923;
  --line: rgba(232, 240, 228, 0.10);
  --text: #e8f0e4;
  --muted: #8fa094;
  --accent: #c8f560;
  --accent2: #7fd4c2;
  --danger: #ff8f7a;
  --card: #1a221d;
  --shadow: 0 18px 50px rgba(0,0,0,.45);
  --radius: 18px;
  --font: "Instrument Sans", system-ui, sans-serif;
  --display: "Fraunces", Georgia, serif;
}
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; }
body {
  font-family: var(--font);
  color: var(--text);
  background:
    radial-gradient(1200px 600px at 10% -10%, rgba(200,245,96,.12), transparent 55%),
    radial-gradient(900px 500px at 100% 0%, rgba(127,212,194,.10), transparent 50%),
    linear-gradient(180deg, #121816 0%, var(--bg0) 40%, #0c100e 100%);
  background-attachment: fixed;
}
button, input, select { font: inherit; color: inherit; }
a { color: var(--accent2); }

.shell { max-width: 1440px; margin: 0 auto; padding: 28px 22px 80px; }

.hero {
  display: grid;
  gap: 10px;
  margin-bottom: 22px;
  animation: rise .55s ease both;
}
.hero h1 {
  margin: 0;
  font-family: var(--display);
  font-weight: 700;
  font-size: clamp(2rem, 4vw, 3.1rem);
  letter-spacing: -.03em;
  line-height: 1.05;
}
.hero p {
  margin: 0;
  color: var(--muted);
  max-width: 52ch;
  font-size: 1.02rem;
}
.hero .stats {
  display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px;
}
.pill {
  border: 1px solid var(--line);
  background: rgba(255,255,255,.03);
  border-radius: 999px;
  padding: 7px 12px;
  font-size: .86rem;
  color: var(--muted);
}
.pill b { color: var(--accent); font-weight: 600; }

.controls {
  position: sticky; top: 10px; z-index: 20;
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: rgba(15,20,18,.82);
  backdrop-filter: blur(14px);
  box-shadow: var(--shadow);
  margin-bottom: 18px;
  animation: rise .55s .05s ease both;
}
.row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.row label { font-size: .78rem; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
.field {
  display: grid; gap: 5px; min-width: 140px; flex: 1;
}
.field input, .field select {
  width: 100%;
  background: var(--bg2);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 12px;
  outline: none;
}
.field input:focus, .field select:focus { border-color: rgba(200,245,96,.45); }
.sort-btns { display: flex; flex-wrap: wrap; gap: 8px; }
.sort-btns button {
  border: 1px solid var(--line);
  background: var(--bg2);
  border-radius: 999px;
  padding: 8px 14px;
  cursor: pointer;
  transition: .15s ease;
}
.sort-btns button:hover { border-color: rgba(200,245,96,.35); }
.sort-btns button.active {
  background: var(--accent);
  color: #132012;
  border-color: transparent;
  font-weight: 600;
}
.dir-btn {
  border: 1px solid var(--line);
  background: var(--bg2);
  border-radius: 12px;
  padding: 10px 12px;
  cursor: pointer;
  min-width: 48px;
}

.meta-line {
  display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap;
  color: var(--muted); font-size: .9rem;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}
.card {
  border: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(255,255,255,.03), transparent 40%), var(--card);
  border-radius: 16px;
  overflow: hidden;
  cursor: pointer;
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
  animation: rise .45s ease both;
}
.card:hover {
  transform: translateY(-3px);
  border-color: rgba(200,245,96,.28);
  box-shadow: 0 16px 40px rgba(0,0,0,.35);
}
.cover {
  aspect-ratio: 3/4;
  background: #0a0e0c;
  position: relative;
  overflow: hidden;
}
.cover img {
  width: 100%; height: 100%; object-fit: cover; display: block;
  transition: transform .35s ease;
}
.card:hover .cover img { transform: scale(1.04); }
.rank {
  position: absolute; top: 10px; left: 10px;
  background: rgba(15,20,18,.78);
  border: 1px solid var(--line);
  color: var(--accent);
  font-weight: 700;
  font-size: .82rem;
  padding: 4px 8px;
  border-radius: 999px;
  backdrop-filter: blur(8px);
}
.badge-slides {
  position: absolute; right: 10px; bottom: 10px;
  background: rgba(15,20,18,.78);
  border: 1px solid var(--line);
  padding: 4px 8px;
  border-radius: 999px;
  font-size: .78rem;
  color: var(--text);
}
.body { padding: 12px 13px 14px; display: grid; gap: 8px; }
.creator { font-size: .78rem; color: var(--accent2); }
.title {
  font-weight: 600; font-size: .95rem; line-height: 1.25;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.metrics {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px;
}
.metric {
  background: rgba(255,255,255,.03);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 6px 7px;
}
.metric span { display: block; color: var(--muted); font-size: .68rem; text-transform: uppercase; letter-spacing: .04em; }
.metric b { font-size: .86rem; font-weight: 600; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; }
.tag {
  font-size: .72rem; color: var(--muted);
  border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px;
}

.pager {
  display: flex; justify-content: center; align-items: center; gap: 10px;
  margin-top: 22px;
}
.pager button {
  border: 1px solid var(--line); background: var(--bg2);
  border-radius: 12px; padding: 10px 16px; cursor: pointer;
}
.pager button:disabled { opacity: .35; cursor: not-allowed; }

/* Modal */
.modal {
  position: fixed; inset: 0; z-index: 50;
  display: none; align-items: stretch; justify-content: center;
  background: rgba(5,8,7,.78); backdrop-filter: blur(10px);
  padding: 18px;
}
.modal.open { display: flex; }
.modal-panel {
  width: min(1100px, 100%);
  max-height: 100%;
  overflow: auto;
  background: var(--bg1);
  border: 1px solid var(--line);
  border-radius: 20px;
  box-shadow: var(--shadow);
  display: grid;
  grid-template-rows: auto 1fr;
}
.modal-head {
  display: flex; justify-content: space-between; gap: 12px; align-items: start;
  padding: 16px 18px; border-bottom: 1px solid var(--line);
  position: sticky; top: 0; background: rgba(23,30,26,.95); backdrop-filter: blur(8px); z-index: 2;
}
.modal-head h2 {
  margin: 0 0 4px; font-family: var(--display); font-size: 1.35rem; letter-spacing: -.02em;
}
.modal-head .sub { color: var(--muted); font-size: .9rem; }
.close {
  border: 1px solid var(--line); background: var(--bg2);
  width: 40px; height: 40px; border-radius: 12px; cursor: pointer; font-size: 1.2rem;
}
.modal-body { padding: 16px 18px 24px; display: grid; gap: 16px; }
.modal-metrics {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px;
}
.slide-strip {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px;
}
.slide-strip figure {
  margin: 0; border-radius: 14px; overflow: hidden;
  border: 1px solid var(--line); background: #0a0e0c;
  position: relative;
}
.slide-strip img {
  width: 100%; aspect-ratio: 3/4; object-fit: cover; display: block; cursor: zoom-in;
}
.slide-strip figcaption {
  position: absolute; left: 8px; top: 8px;
  background: rgba(0,0,0,.55); border-radius: 999px; padding: 2px 8px; font-size: .75rem;
}
.empty {
  text-align: center; color: var(--muted); padding: 60px 20px;
  border: 1px dashed var(--line); border-radius: var(--radius);
}
.lightbox {
  position: fixed; inset: 0; z-index: 80; display: none;
  align-items: center; justify-content: center;
  background: rgba(0,0,0,.9); padding: 20px;
}
.lightbox.open { display: flex; }
.lightbox img {
  max-width: min(96vw, 1100px); max-height: 92vh;
  object-fit: contain; border-radius: 8px;
  box-shadow: var(--shadow);
}
.lb-nav {
  position: absolute; top: 50%; transform: translateY(-50%);
  border: 1px solid var(--line); background: rgba(20,20,20,.7);
  color: white; width: 48px; height: 48px; border-radius: 50%;
  cursor: pointer; font-size: 1.3rem;
}
.lb-prev { left: 18px; }
.lb-next { right: 18px; }
.lb-close {
  position: absolute; top: 16px; right: 16px;
  border: 1px solid var(--line); background: rgba(20,20,20,.7);
  color: white; width: 44px; height: 44px; border-radius: 12px; cursor: pointer;
}

@keyframes rise {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: none; }
}
@media (max-width: 720px) {
  .shell { padding: 16px 12px 60px; }
  .metrics { grid-template-columns: repeat(3, 1fr); }
}
</style>
</head>
<body>
<div class="shell">
  <header class="hero">
    <h1>Рейтинг каруселей</h1>
    <p>Все скачанные slideshow из ReelFarm: сортировка по сохранениям, просмотрам, лайкам и конверсии. Кликни карточку — откроются все фото.</p>
    <div class="stats">
      <div class="pill">Каруселей: <b id="statTotal">__COUNT__</b></div>
      <div class="pill">Показано: <b id="statShown">0</b></div>
      <div class="pill">Страница: <b id="statPage">1</b></div>
    </div>
  </header>

  <section class="controls">
    <div class="row">
      <div class="field" style="flex:2">
        <label>Поиск</label>
        <input id="q" type="search" placeholder="@creator, ниша, название…" />
      </div>
      <div class="field">
        <label>Ниша</label>
        <select id="niche"><option value="">Все</option></select>
      </div>
      <div class="field">
        <label>Регион</label>
        <select id="region"><option value="">Все</option></select>
      </div>
      <div class="field" style="flex:0; min-width:90px">
        <label>На стр.</label>
        <select id="pageSize">
          <option value="24">24</option>
          <option value="48" selected>48</option>
          <option value="96">96</option>
        </select>
      </div>
    </div>
    <div class="row">
      <label style="width:100%">Сортировка</label>
      <div class="sort-btns" id="sortBtns">
        <button data-sort="saves" class="active">Saves</button>
        <button data-sort="views">Views</button>
        <button data-sort="likes">Likes</button>
        <button data-sort="save_rate">Save rate</button>
        <button data-sort="like_rate">Like rate</button>
        <button data-sort="slides_n">Слайды</button>
      </div>
      <button class="dir-btn" id="dirBtn" title="Направление">↓</button>
    </div>
    <div class="meta-line">
      <span id="filterHint">Загрузка данных…</span>
      <span>Открой файл через локальный путь рядом с папкой <code>downloaded_carousels</code></span>
    </div>
  </section>

  <div id="grid" class="grid"></div>
  <div id="empty" class="empty" hidden>Ничего не найдено</div>
  <div class="pager">
    <button id="prevBtn">← Назад</button>
    <span id="pageInfo">1 / 1</span>
    <button id="nextBtn">Вперёд →</button>
  </div>
</div>

<div class="modal" id="modal" role="dialog" aria-modal="true">
  <div class="modal-panel">
    <div class="modal-head">
      <div>
        <h2 id="mTitle"></h2>
        <div class="sub" id="mSub"></div>
      </div>
      <button class="close" id="closeModal" aria-label="Закрыть">×</button>
    </div>
    <div class="modal-body">
      <div class="modal-metrics" id="mMetrics"></div>
      <div class="slide-strip" id="mSlides"></div>
    </div>
  </div>
</div>

<div class="lightbox" id="lightbox">
  <button class="lb-close" id="lbClose">×</button>
  <button class="lb-nav lb-prev" id="lbPrev">‹</button>
  <img id="lbImg" alt="" />
  <button class="lb-nav lb-next" id="lbNext">›</button>
</div>

<script>/*__DATA__*/</script>
<script>
const fmt = (n) => {
  n = Number(n) || 0;
  if (n >= 1e6) return (n/1e6).toFixed(1).replace(/\.0$/,'') + 'M';
  if (n >= 1e3) return (n/1e3).toFixed(1).replace(/\.0$/,'') + 'K';
  return String(n);
};
const pct = (x) => ((Number(x)||0)*100).toFixed(2) + '%';

let DATA = [];
let sortKey = 'saves';
let sortDir = -1; // desc
let page = 1;
let filtered = [];
let currentItem = null;
let lbIndex = 0;

const els = {
  grid: document.getElementById('grid'),
  empty: document.getElementById('empty'),
  q: document.getElementById('q'),
  niche: document.getElementById('niche'),
  region: document.getElementById('region'),
  pageSize: document.getElementById('pageSize'),
  sortBtns: document.getElementById('sortBtns'),
  dirBtn: document.getElementById('dirBtn'),
  prevBtn: document.getElementById('prevBtn'),
  nextBtn: document.getElementById('nextBtn'),
  pageInfo: document.getElementById('pageInfo'),
  filterHint: document.getElementById('filterHint'),
  statShown: document.getElementById('statShown'),
  statPage: document.getElementById('statPage'),
  modal: document.getElementById('modal'),
  mTitle: document.getElementById('mTitle'),
  mSub: document.getElementById('mSub'),
  mMetrics: document.getElementById('mMetrics'),
  mSlides: document.getElementById('mSlides'),
  closeModal: document.getElementById('closeModal'),
  lightbox: document.getElementById('lightbox'),
  lbImg: document.getElementById('lbImg'),
  lbClose: document.getElementById('lbClose'),
  lbPrev: document.getElementById('lbPrev'),
  lbNext: document.getElementById('lbNext'),
};

function fillFilters() {
  const niches = [...new Set(DATA.map(d => d.niche).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
  const regions = [...new Set(DATA.map(d => d.audience).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
  for (const n of niches) {
    const o = document.createElement('option'); o.value = n; o.textContent = n; els.niche.appendChild(o);
  }
  for (const r of regions) {
    const o = document.createElement('option'); o.value = r; o.textContent = r; els.region.appendChild(o);
  }
}

function apply() {
  const q = els.q.value.trim().toLowerCase();
  const niche = els.niche.value;
  const region = els.region.value;
  filtered = DATA.filter(d => {
    if (niche && d.niche !== niche) return false;
    if (region && d.audience !== region) return false;
    if (!q) return true;
    const hay = `${d.creator} ${d.title} ${d.niche} ${d.folder} ${d.product}`.toLowerCase();
    return hay.includes(q);
  });
  filtered.sort((a,b) => {
    const av = Number(a[sortKey]) || 0;
    const bv = Number(b[sortKey]) || 0;
    if (av === bv) return (b.saves - a.saves);
    return (av - bv) * sortDir;
  });
  const pages = Math.max(1, Math.ceil(filtered.length / Number(els.pageSize.value)));
  if (page > pages) page = pages;
  render();
}

function render() {
  const size = Number(els.pageSize.value);
  const pages = Math.max(1, Math.ceil(filtered.length / size));
  const start = (page - 1) * size;
  const slice = filtered.slice(start, start + size);
  els.grid.innerHTML = '';
  els.empty.hidden = slice.length > 0;
  slice.forEach((item, i) => {
    const rank = start + i + 1;
    const cover = item.slides[0] || '';
    const card = document.createElement('article');
    card.className = 'card';
    card.style.animationDelay = `${Math.min(i, 12) * 0.02}s`;
    card.innerHTML = `
      <div class="cover">
        <span class="rank">#${rank}</span>
        ${cover ? `<img loading="lazy" src="${cover}" alt="" />` : `<div style="display:grid;place-items:center;height:100%;color:var(--muted)">нет фото</div>`}
        <span class="badge-slides">${item.slides_n} фото</span>
      </div>
      <div class="body">
        <div class="creator">@${item.creator}</div>
        <div class="title">${escapeHtml(item.title)}</div>
        <div class="metrics">
          <div class="metric"><span>Saves</span><b>${fmt(item.saves)}</b></div>
          <div class="metric"><span>Views</span><b>${fmt(item.views)}</b></div>
          <div class="metric"><span>Rate</span><b>${pct(item.save_rate)}</b></div>
        </div>
        <div class="tags">
          <span class="tag">${escapeHtml(item.niche)}</span>
          ${item.audience ? `<span class="tag">${escapeHtml(item.audience)}</span>` : ''}
        </div>
      </div>`;
    card.addEventListener('click', () => openModal(item, rank));
    els.grid.appendChild(card);
  });
  els.pageInfo.textContent = `${page} / ${pages}`;
  els.prevBtn.disabled = page <= 1;
  els.nextBtn.disabled = page >= pages;
  els.statShown.textContent = String(filtered.length);
  els.statPage.textContent = String(page);
  els.filterHint.textContent = `Сортировка: ${sortKey} ${sortDir < 0 ? '↓' : '↑'} · найдено ${filtered.length}`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function openModal(item, rank) {
  currentItem = item;
  els.mTitle.textContent = `#${rank}  @${item.creator}`;
  els.mSub.textContent = `${item.title} · ${item.niche}${item.audience ? ' · ' + item.audience : ''}`;
  els.mMetrics.innerHTML = `
    <div class="metric"><span>Saves</span><b>${fmt(item.saves)}</b></div>
    <div class="metric"><span>Views</span><b>${fmt(item.views)}</b></div>
    <div class="metric"><span>Likes</span><b>${fmt(item.likes)}</b></div>
    <div class="metric"><span>Save rate</span><b>${pct(item.save_rate)}</b></div>
    <div class="metric"><span>Like rate</span><b>${pct(item.like_rate)}</b></div>
    <div class="metric"><span>Слайды</span><b>${item.slides_n}</b></div>`;
  els.mSlides.innerHTML = '';
  if (!item.slides.length) {
    els.mSlides.innerHTML = '<div class="empty">Нет локальных фото</div>';
  } else {
    item.slides.forEach((src, idx) => {
      const fig = document.createElement('figure');
      fig.innerHTML = `<img loading="lazy" src="${src}" alt="slide ${idx+1}" /><figcaption>${idx+1}</figcaption>`;
      fig.querySelector('img').addEventListener('click', (e) => {
        e.stopPropagation();
        openLightbox(idx);
      });
      els.mSlides.appendChild(fig);
    });
  }
  els.modal.classList.add('open');
}

function closeModal() { els.modal.classList.remove('open'); }

function openLightbox(idx) {
  if (!currentItem || !currentItem.slides.length) return;
  lbIndex = idx;
  els.lbImg.src = currentItem.slides[lbIndex];
  els.lightbox.classList.add('open');
}
function closeLightbox() { els.lightbox.classList.remove('open'); }
function lbStep(d) {
  if (!currentItem) return;
  const n = currentItem.slides.length;
  lbIndex = (lbIndex + d + n) % n;
  els.lbImg.src = currentItem.slides[lbIndex];
}

els.sortBtns.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-sort]');
  if (!btn) return;
  els.sortBtns.querySelectorAll('button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  sortKey = btn.dataset.sort;
  page = 1;
  apply();
});
els.dirBtn.addEventListener('click', () => {
  sortDir *= -1;
  els.dirBtn.textContent = sortDir < 0 ? '↓' : '↑';
  apply();
});
els.q.addEventListener('input', () => { page = 1; apply(); });
els.niche.addEventListener('change', () => { page = 1; apply(); });
els.region.addEventListener('change', () => { page = 1; apply(); });
els.pageSize.addEventListener('change', () => { page = 1; apply(); });
els.prevBtn.addEventListener('click', () => { page--; apply(); });
els.nextBtn.addEventListener('click', () => { page++; apply(); });
els.closeModal.addEventListener('click', closeModal);
els.modal.addEventListener('click', (e) => { if (e.target === els.modal) closeModal(); });
els.lbClose.addEventListener('click', closeLightbox);
els.lightbox.addEventListener('click', (e) => { if (e.target === els.lightbox) closeLightbox(); });
els.lbPrev.addEventListener('click', (e) => { e.stopPropagation(); lbStep(-1); });
els.lbNext.addEventListener('click', (e) => { e.stopPropagation(); lbStep(1); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closeLightbox(); closeModal(); }
  if (els.lightbox.classList.contains('open')) {
    if (e.key === 'ArrowLeft') lbStep(-1);
    if (e.key === 'ArrowRight') lbStep(1);
  }
});

async function boot() {
  if (Array.isArray(window.CAROUSEL_DATA) && window.CAROUSEL_DATA.length) {
    DATA = window.CAROUSEL_DATA;
  } else {
    try {
      const res = await fetch('carousel_ranking_data.json');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      DATA = await res.json();
    } catch (err) {
      els.filterHint.textContent = 'Не удалось загрузить данные.';
      console.error(err);
      return;
    }
  }
  document.getElementById('statTotal').textContent = String(DATA.length);
  fillFilters();
  apply();
}
boot();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
