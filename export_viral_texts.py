#!/usr/bin/env python3
"""
export_viral_texts.py — красивый экспорт текстов из viral_playbook.

Выход:
  out/viral_texts.html   — читаемый каталог
  out/viral_texts.md     — markdown
  out/viral_texts.json   — данные
  out/viral_texts.csv    — Excel
"""

from __future__ import annotations

import csv
import html
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "reelfarm_database.db"
OUT_DIR = ROOT / "out"


def fmt_num(n: int | None) -> str:
    if n is None:
        return "—"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    if n >= 1_000:
        return f"{n / 1_000:.1f}K".rstrip("0").rstrip(".")
    return str(n)


def parse_slides(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        arr = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(arr, list):
        return []
    out: list[str] = []
    for x in arr:
        s = str(x or "").strip()
        if not s or s.upper() == "NONE":
            continue
        out.append(s)
    return out


def load_rows(db: Path) -> list[dict]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = []
    for r in conn.execute(
        """
        SELECT id, title, niche, views, bookmarks, save_rate,
               hook_type, trigger_text, template,
               real_hook, slides_text_json, real_cta, ocr_done_at
        FROM viral_playbook
        ORDER BY bookmarks DESC
        """
    ):
        slides = parse_slides(r["slides_text_json"])
        if not slides and not r["real_hook"]:
            continue
        rows.append(
            {
                "id": r["id"],
                "title": r["title"] or "",
                "niche": r["niche"] or "",
                "views": int(r["views"] or 0),
                "bookmarks": int(r["bookmarks"] or 0),
                "save_rate": float(r["save_rate"] or 0),
                "hook_type": r["hook_type"] or "",
                "trigger": r["trigger_text"] or "",
                "template": r["template"] or "",
                "real_hook": (r["real_hook"] or "").strip(),
                "slides": slides,
                "real_cta": (r["real_cta"] or "").strip(),
                "ocr_done_at": r["ocr_done_at"] or "",
            }
        )
    conn.close()
    return rows


def write_json(rows: list[dict], path: Path) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "#",
                "bookmarks",
                "views",
                "save_rate",
                "niche",
                "hook_type",
                "title",
                "real_hook",
                "slides",
                "real_cta",
                "template",
                "id",
            ]
        )
        for i, r in enumerate(rows, 1):
            slides_joined = " | ".join(
                f"{j}. {t}" for j, t in enumerate(r["slides"], 1)
            )
            w.writerow(
                [
                    i,
                    r["bookmarks"],
                    r["views"],
                    f"{r['save_rate']:.4f}",
                    r["niche"],
                    r["hook_type"],
                    r["title"],
                    r["real_hook"],
                    slides_joined,
                    r["real_cta"],
                    r["template"],
                    r["id"],
                ]
            )


def write_md(rows: list[dict], path: Path) -> None:
    lines: list[str] = [
        "# Viral Playbook — тексты слайдов",
        "",
        f"Собрано: **{len(rows)}** каруселей · {datetime.now():%Y-%m-%d %H:%M}",
        "",
        "---",
        "",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(f"## {i}. {r['real_hook'] or r['title']}")
        lines.append("")
        meta = (
            f"**{fmt_num(r['bookmarks'])}** saves · "
            f"**{fmt_num(r['views'])}** views · "
            f"rate **{r['save_rate']*100:.1f}%** · "
            f"`{r['niche'] or '—'}` · "
            f"*{r['hook_type'] or '—'}*"
        )
        lines.append(meta)
        lines.append("")
        if r["template"]:
            lines.append(f"> Шаблон: `{r['template']}`")
            lines.append("")
        lines.append("### Слайды")
        lines.append("")
        for j, t in enumerate(r["slides"], 1):
            tag = ""
            if j == 1:
                tag = " *(hook)*"
            elif j == len(r["slides"]):
                tag = " *(cta)*"
            lines.append(f"{j}. {t}{tag}")
        lines.append("")
        lines.append("---")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_html(rows: list[dict], path: Path) -> None:
    niches: dict[str, int] = {}
    hooks: dict[str, int] = {}
    for r in rows:
        niches[r["niche"] or "—"] = niches.get(r["niche"] or "—", 0) + 1
        hooks[r["hook_type"] or "—"] = hooks.get(r["hook_type"] or "—", 0) + 1

    niche_opts = "".join(
        f'<option value="{html.escape(n)}">{html.escape(n)} ({c})</option>'
        for n, c in sorted(niches.items(), key=lambda x: -x[1])
    )
    hook_opts = "".join(
        f'<option value="{html.escape(n)}">{html.escape(n)} ({c})</option>'
        for n, c in sorted(hooks.items(), key=lambda x: -x[1])
    )

    cards = []
    for i, r in enumerate(rows, 1):
        slides_html = "".join(
            f'<li class="{"hook" if j == 1 else "cta" if j == len(r["slides"]) else ""}">'
            f'<span class="n">{j}</span>'
            f"<p>{html.escape(t)}</p></li>"
            for j, t in enumerate(r["slides"], 1)
        )
        cards.append(
            f"""
<article class="card" data-niche="{html.escape(r['niche'] or '')}" data-hook="{html.escape(r['hook_type'] or '')}" data-search="{html.escape((r['real_hook']+' '+r['title']+' '+' '.join(r['slides'])).lower())}">
  <header>
    <div class="rank">#{i}</div>
    <div class="stats">
      <span class="pill saves">{fmt_num(r['bookmarks'])} saves</span>
      <span class="pill">{fmt_num(r['views'])} views</span>
      <span class="pill">{r['save_rate']*100:.1f}% rate</span>
      <span class="pill niche">{html.escape(r['niche'] or '—')}</span>
      <span class="pill type">{html.escape(r['hook_type'] or '—')}</span>
    </div>
  </header>
  <h2>{html.escape(r['real_hook'] or r['title'] or 'Untitled')}</h2>
  <p class="orig">{html.escape(r['title'])}</p>
  {f'<p class="tpl"><span>Template</span> {html.escape(r["template"])}</p>' if r['template'] else ''}
  <ol class="slides">{slides_html}</ol>
</article>"""
        )

    doc = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Viral Playbook — тексты слайдов</title>
<style>
  :root {{
    --bg: #0f1115;
    --panel: #181b22;
    --card: #1e222b;
    --line: #2c3340;
    --text: #eef1f6;
    --muted: #9aa3b2;
    --accent: #5eead4;
    --hook: #fbbf24;
    --cta: #a78bfa;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Segoe UI", system-ui, sans-serif;
    background:
      radial-gradient(1200px 600px at 10% -10%, #1a2a33 0%, transparent 55%),
      radial-gradient(900px 500px at 100% 0%, #241a33 0%, transparent 50%),
      var(--bg);
    color: var(--text);
    line-height: 1.45;
  }}
  .wrap {{ max-width: 980px; margin: 0 auto; padding: 32px 20px 80px; }}
  h1 {{
    font-size: 2rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    margin: 0 0 8px;
  }}
  .sub {{ color: var(--muted); margin: 0 0 28px; }}
  .toolbar {{
    position: sticky; top: 0; z-index: 5;
    display: flex; flex-wrap: wrap; gap: 10px;
    padding: 14px 0 18px;
    background: linear-gradient(var(--bg) 70%, transparent);
    backdrop-filter: blur(8px);
  }}
  input, select {{
    background: var(--panel);
    border: 1px solid var(--line);
    color: var(--text);
    border-radius: 10px;
    padding: 10px 12px;
    font: inherit;
  }}
  input {{ flex: 1 1 220px; min-width: 180px; }}
  select {{ flex: 0 1 180px; }}
  .card {{
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 18px;
    padding: 22px 22px 10px;
    margin-bottom: 18px;
    box-shadow: 0 10px 40px rgba(0,0,0,.25);
  }}
  .card.hidden {{ display: none; }}
  header {{
    display: flex; gap: 14px; align-items: flex-start;
    margin-bottom: 10px;
  }}
  .rank {{
    font-weight: 800; color: var(--accent);
    font-size: 1.1rem; min-width: 42px;
  }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .pill {{
    font-size: .75rem;
    color: var(--muted);
    background: #12151b;
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: 3px 9px;
  }}
  .pill.saves {{ color: var(--accent); border-color: #2a5a52; }}
  .pill.type {{ color: #fcd34d; }}
  h2 {{
    margin: 6px 0 4px;
    font-size: 1.35rem;
    letter-spacing: -0.02em;
    line-height: 1.25;
  }}
  .orig {{ color: var(--muted); font-size: .85rem; margin: 0 0 10px; }}
  .tpl {{
    margin: 0 0 14px;
    font-size: .9rem;
    color: #c4b5fd;
    background: #17141f;
    border-left: 3px solid var(--cta);
    padding: 8px 12px;
    border-radius: 0 10px 10px 0;
  }}
  .tpl span {{ color: var(--muted); margin-right: 8px; font-size: .75rem; text-transform: uppercase; letter-spacing: .06em; }}
  .slides {{
    list-style: none;
    margin: 0;
    padding: 0;
  }}
  .slides li {{
    display: grid;
    grid-template-columns: 36px 1fr;
    gap: 10px;
    padding: 12px 4px;
    border-top: 1px solid var(--line);
  }}
  .slides .n {{
    width: 28px; height: 28px;
    border-radius: 8px;
    display: grid; place-items: center;
    font-size: .75rem; font-weight: 700;
    background: #12151b; color: var(--muted);
  }}
  .slides li.hook .n {{ background: #3a2e12; color: var(--hook); }}
  .slides li.cta .n {{ background: #2a2140; color: var(--cta); }}
  .slides p {{ margin: 0; font-size: 1.02rem; }}
  .slides li.hook p {{ color: #fde68a; }}
  .slides li.cta p {{ color: #ddd6fe; }}
  .count {{ color: var(--muted); font-size: .9rem; margin-left: auto; align-self: center; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Viral Playbook</h1>
  <p class="sub">{len(rows)} каруселей · тексты с слайдов (OCR + Ollama) · {datetime.now():%d.%m.%Y %H:%M}</p>
  <div class="toolbar">
    <input id="q" type="search" placeholder="Поиск по тексту / хуку / нише…"/>
    <select id="niche"><option value="">Все ниши</option>{niche_opts}</select>
    <select id="hook"><option value="">Все типы хуков</option>{hook_opts}</select>
    <span class="count" id="count"></span>
  </div>
  <div id="feed">
    {"".join(cards)}
  </div>
</div>
<script>
const cards = [...document.querySelectorAll('.card')];
const q = document.getElementById('q');
const niche = document.getElementById('niche');
const hook = document.getElementById('hook');
const count = document.getElementById('count');
function apply() {{
  const s = q.value.trim().toLowerCase();
  const n = niche.value;
  const h = hook.value;
  let shown = 0;
  for (const c of cards) {{
    const ok =
      (!s || c.dataset.search.includes(s)) &&
      (!n || c.dataset.niche === n) &&
      (!h || c.dataset.hook === h);
    c.classList.toggle('hidden', !ok);
    if (ok) shown++;
  }}
  count.textContent = shown + ' / ' + cards.length;
}}
q.addEventListener('input', apply);
niche.addEventListener('change', apply);
hook.addEventListener('change', apply);
apply();
</script>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_rows(DB_PATH)
    if not rows:
        print("Нет текстов для экспорта.")
        return

    json_path = OUT_DIR / "viral_texts.json"
    csv_path = OUT_DIR / "viral_texts.csv"
    md_path = OUT_DIR / "viral_texts.md"
    html_path = OUT_DIR / "viral_texts.html"

    write_json(rows, json_path)
    write_csv(rows, csv_path)
    write_md(rows, md_path)
    write_html(rows, html_path)

    print(f"Экспортировано: {len(rows)} каруселей")
    print(f"  HTML: {html_path}")
    print(f"  MD:   {md_path}")
    print(f"  CSV:  {csv_path}")
    print(f"  JSON: {json_path}")


if __name__ == "__main__":
    main()
