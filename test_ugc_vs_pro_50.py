#!/usr/bin/env python3
"""
Визуальная проверка: живое бытовое UGC vs профессиональный сток.

Выкачивает ~50 фото с Pinterest по разнородным candid-запросам,
оценивает через core/ugc_filter + core/taste_classifier,
собирает HTML-галерею out/ugc_probe_50/report.html.

Запуск из корня репо:
  python test_ugc_vs_pro_50.py
"""

from __future__ import annotations

import asyncio
import html
import json
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from core.harvester import PinterestHarvester  # noqa: E402
from core.taste_classifier import get_taste_classifier  # noqa: E402
from core.ugc_filter import get_ugc_filter  # noqa: E402

OUT_DIR = ROOT / "out" / "ugc_probe_50"
IMG_DIR = OUT_DIR / "images"
REPORT_PATH = OUT_DIR / "report.html"
META_PATH = OUT_DIR / "results.json"
TARGET = 50
PER_QUERY = 10

QUERIES: list[str] = [
    "kitchen counter groceries candid iphone",
    "messy desk coffee mug candid iphone",
    "walking street sidewalk sneakers candid iphone",
    "casual mirror selfie phone covering face",
    "open window rainy day tea candid iphone",
    "unmade bed morning light candid iphone",
]

# Пороги вердикта (как в ТЗ)
UGC_LIVE = 0.55
TASTE_LIVE = 0.50
UGC_STOCK = 0.45
TASTE_STOCK = 0.40


@dataclass
class ProbeRow:
    index: int
    pin_id: str
    query: str
    file: str
    ugc: float
    taste: float
    status: str
    status_key: str  # live | stock | mixed


def _verdict(ugc: float, taste: float) -> tuple[str, str]:
    if ugc >= UGC_LIVE and taste >= TASTE_LIVE:
        return "✅ БЫТ / ЖИВОЕ (Candid iPhone)", "live"
    if ugc < UGC_STOCK or taste < TASTE_STOCK:
        return "❌ СТОК / ПРОФИ (Staged / Pro)", "stock"
    return "⚠️ ПОГРАНИЧНОЕ (Neutral / Mixed)", "mixed"


def _status(msg: str) -> None:
    print(f"  · {msg}", flush=True)


def collect_images(
    harvester: PinterestHarvester,
    *,
    target: int = TARGET,
) -> list[tuple[Image.Image, str, str]]:
    """
    Скачать до `target` уникальных фото.
    Returns list of (PIL image, pin_id, query).
    """
    collected: list[tuple[Image.Image, str, str]] = []
    seen: set[str] = set()

    for qi, query in enumerate(QUERIES, start=1):
        if len(collected) >= target:
            break
        print(f"\n[{qi}/{len(QUERIES)}] search «{query}»…", flush=True)
        try:
            pins = harvester.search(query, finalize=False)
        except Exception as exc:
            print(f"  FAIL search: {exc}", flush=True)
            continue
        # свежие, без дублей
        fresh = [p for p in pins if p.pin_id and p.pin_id not in seen]
        need = min(PER_QUERY, target - len(collected), len(fresh))
        pool = fresh[: max(need * 2, need)]  # запас на CDN-фейлы
        if not pool:
            print("  0 pins", flush=True)
            continue
        print(f"  pins={len(fresh)} → download up to {need}…", flush=True)
        try:
            cands, _prog = asyncio.run(
                harvester.download_candidates(
                    pool, query, limit=need, concurrency=8
                )
            )
        except Exception as exc:
            print(f"  FAIL download: {exc}", flush=True)
            continue

        got = 0
        for c in cands:
            if len(collected) >= target:
                break
            pid = str(c.pin_id or "")
            if not pid or pid in seen:
                continue
            try:
                img = c.image.convert("RGB")
            except Exception:
                continue
            seen.add(pid)
            collected.append((img, pid, query))
            got += 1
            if got >= need:
                break
        print(f"  kept +{got} (total {len(collected)}/{target})", flush=True)
        time.sleep(0.35)

    return collected[:target]


def score_and_save(
    items: list[tuple[Image.Image, str, str]],
) -> list[ProbeRow]:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    ugc_f = get_ugc_filter()
    taste_c = get_taste_classifier()
    ugc_f.ensure()

    rows: list[ProbeRow] = []
    n = len(items)
    for i, (img, pid, query) in enumerate(items, start=1):
        fname = f"{i:02d}_{pid}.jpg"
        path = IMG_DIR / fname
        try:
            img.save(path, format="JPEG", quality=88, optimize=True)
        except Exception as exc:
            print(f"[{i}/{n}] save fail: {exc}", flush=True)
            continue

        try:
            ugc = float(ugc_f.get_ugc_score(img))
        except Exception as exc:
            print(f"[{i}/{n}] ugc fail: {exc}", flush=True)
            ugc = 0.5
        try:
            taste = float(taste_c.predict_taste_score(img))
        except Exception as exc:
            print(f"[{i}/{n}] taste fail: {exc}", flush=True)
            taste = 0.5

        status, key = _verdict(ugc, taste)
        print(
            f"[{i}/{n}] Фото оценено: UGC={ugc:.0%}, Taste={taste:.0%} -> {status}",
            flush=True,
        )
        rows.append(
            ProbeRow(
                index=i,
                pin_id=pid,
                query=query,
                file=fname,
                ugc=round(ugc, 4),
                taste=round(taste, 4),
                status=status,
                status_key=key,
            )
        )
    return rows


def write_html(rows: list[ProbeRow], path: Path) -> None:
    live = sum(1 for r in rows if r.status_key == "live")
    stock = sum(1 for r in rows if r.status_key == "stock")
    mixed = sum(1 for r in rows if r.status_key == "mixed")
    total = len(rows)
    storage_key = "ugc_probe_50_votes_v1"

    cards: list[str] = []
    for r in rows:
        badge_cls = {
            "live": "badge-live",
            "stock": "badge-stock",
            "mixed": "badge-mixed",
        }.get(r.status_key, "badge-mixed")
        pid = html.escape(r.pin_id)
        cards.append(
            f"""
      <article class="card" data-pin="{pid}" data-pred="{html.escape(r.status_key)}">
        <div class="thumb">
          <img src="images/{html.escape(r.file)}" alt="{pid}" loading="lazy"/>
        </div>
        <div class="meta">
          <span class="badge {badge_cls}">{html.escape(r.status)}</span>
          <div class="scores">UGC: {r.ugc:.0%} | Taste: {r.taste:.0%}</div>
          <div class="query" title="{html.escape(r.query)}">{html.escape(r.query)}</div>
          <div class="pin">#{r.index} · {pid}</div>
          <div class="votes">
            <button type="button" class="btn-ok" data-vote="ok"
              title="Вердикт модели верный">✓ Верно</button>
            <button type="button" class="btn-bad" data-vote="bad"
              title="Вердикт модели ошибочный">✗ Ошибка</button>
          </div>
          <div class="vote-label" data-role="vote-label"></div>
        </div>
      </article>"""
        )

    doc = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>UGC vs Pro — probe {total}</title>
<style>
  :root {{
    --bg: #12141a;
    --card: #1c1f27;
    --fg: #f0f2f5;
    --muted: #9aa3b2;
    --live: #2ecc71;
    --stock: #e74c3c;
    --mixed: #f39c12;
    --border: #2e3440;
    --ok: #3ddc97;
    --bad: #e85d5d;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px;
    font-family: "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--fg);
  }}
  h1 {{ margin: 0 0 8px; font-size: 1.45rem; }}
  .summary {{
    color: var(--muted); margin-bottom: 10px; font-size: 0.95rem;
  }}
  .summary strong {{ color: var(--fg); }}
  .live {{ color: var(--live); }}
  .stock {{ color: var(--stock); }}
  .mixed {{ color: var(--mixed); }}
  .human-bar {{
    display: flex; flex-wrap: wrap; gap: 12px 20px; align-items: center;
    background: #181b22; border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 16px; margin-bottom: 20px;
    font-size: 0.92rem;
  }}
  .human-bar .stat strong {{ color: var(--fg); }}
  .human-bar .ok {{ color: var(--ok); }}
  .human-bar .bad {{ color: var(--bad); }}
  .human-bar .acc {{ color: #6cb6ff; }}
  .human-bar button {{
    margin-left: auto; background: #2a2f3a; color: var(--muted);
    border: 1px solid var(--border); border-radius: 6px;
    padding: 6px 12px; cursor: pointer; font-size: 0.8rem;
  }}
  .human-bar button:hover {{ color: var(--fg); }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 14px;
  }}
  @media (max-width: 1200px) {{ .grid {{ grid-template-columns: repeat(4, 1fr); }} }}
  @media (max-width: 900px) {{ .grid {{ grid-template-columns: repeat(3, 1fr); }} }}
  @media (max-width: 640px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  .card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    display: flex; flex-direction: column;
    transition: border-color .15s, box-shadow .15s;
  }}
  .card.voted-ok {{ border-color: var(--ok); box-shadow: 0 0 0 1px rgba(61,220,151,.25); }}
  .card.voted-bad {{ border-color: var(--bad); box-shadow: 0 0 0 1px rgba(232,93,93,.25); }}
  .thumb {{
    aspect-ratio: 3 / 4;
    background: #0d0f14;
    overflow: hidden;
  }}
  .thumb img {{
    width: 100%; height: 100%;
    object-fit: cover; display: block;
  }}
  .meta {{ padding: 10px 11px 12px; }}
  .badge {{
    display: inline-block;
    font-size: 0.72rem; font-weight: 700;
    padding: 4px 8px; border-radius: 6px;
    margin-bottom: 6px; line-height: 1.25;
  }}
  .badge-live {{ background: rgba(46,204,113,.18); color: var(--live); }}
  .badge-stock {{ background: rgba(231,76,60,.18); color: var(--stock); }}
  .badge-mixed {{ background: rgba(243,156,18,.18); color: var(--mixed); }}
  .scores {{ font-size: 0.82rem; font-weight: 600; margin-bottom: 4px; }}
  .query {{
    font-size: 0.72rem; color: var(--muted);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  .pin {{ font-size: 0.68rem; color: #667; margin-top: 4px; }}
  .votes {{
    display: flex; gap: 6px; margin-top: 8px;
  }}
  .votes button {{
    flex: 1; border: none; border-radius: 6px;
    padding: 7px 4px; font-size: 0.75rem; font-weight: 700;
    cursor: pointer; opacity: 0.85;
  }}
  .votes button:hover {{ opacity: 1; }}
  .btn-ok {{ background: #1e3a2f; color: var(--ok); }}
  .btn-bad {{ background: #3a2222; color: var(--bad); }}
  .card.voted-ok .btn-ok {{ outline: 2px solid var(--ok); opacity: 1; }}
  .card.voted-bad .btn-bad {{ outline: 2px solid var(--bad); opacity: 1; }}
  .vote-label {{
    min-height: 1.1em; margin-top: 5px;
    font-size: 0.72rem; font-weight: 600; color: var(--muted);
  }}
  .card.voted-ok .vote-label {{ color: var(--ok); }}
  .card.voted-bad .vote-label {{ color: var(--bad); }}
</style>
</head>
<body>
  <h1>UGC vs Pro — визуальный probe</h1>
  <p class="summary">
    Модель: Всего <strong>{total}</strong>
    | Живой быт: <strong class="live">{live}</strong>
    | Сток/Профи: <strong class="stock">{stock}</strong>
    | Пограничные: <strong class="mixed">{mixed}</strong>
  </p>
  <div class="human-bar" id="humanStats">
    <span class="stat">Оценено тобой: <strong id="nMarked">0</strong> / {total}</span>
    <span class="stat ok">✓ Верно: <strong id="nOk">0</strong></span>
    <span class="stat bad">✗ Ошибка: <strong id="nBad">0</strong></span>
    <span class="stat acc">Точность: <strong id="nAcc">—</strong></span>
    <button type="button" id="btnExport">Экспорт JSON</button>
    <button type="button" id="btnReset">Сбросить оценки</button>
  </div>
  <div class="grid">
{''.join(cards)}
  </div>
<script>
(function () {{
  const KEY = {json.dumps(storage_key)};
  const cards = Array.from(document.querySelectorAll(".card[data-pin]"));

  function loadVotes() {{
    try {{
      return JSON.parse(localStorage.getItem(KEY) || "{{}}") || {{}};
    }} catch (e) {{
      return {{}};
    }}
  }}

  function saveVotes(votes) {{
    localStorage.setItem(KEY, JSON.stringify(votes));
  }}

  function applyCard(card, vote) {{
    card.classList.remove("voted-ok", "voted-bad");
    const label = card.querySelector("[data-role=vote-label]");
    if (vote === "ok") {{
      card.classList.add("voted-ok");
      if (label) label.textContent = "Твоя оценка: верно";
    }} else if (vote === "bad") {{
      card.classList.add("voted-bad");
      if (label) label.textContent = "Твоя оценка: ошибка модели";
    }} else if (label) {{
      label.textContent = "";
    }}
  }}

  function refreshStats(votes) {{
    let ok = 0, bad = 0;
    for (const v of Object.values(votes)) {{
      if (v === "ok") ok++;
      else if (v === "bad") bad++;
    }}
    const marked = ok + bad;
    document.getElementById("nMarked").textContent = String(marked);
    document.getElementById("nOk").textContent = String(ok);
    document.getElementById("nBad").textContent = String(bad);
    document.getElementById("nAcc").textContent =
      marked ? Math.round((ok / marked) * 100) + "%" : "—";
  }}

  function init() {{
    const votes = loadVotes();
    for (const card of cards) {{
      const pin = card.getAttribute("data-pin");
      applyCard(card, votes[pin] || null);
      card.querySelectorAll("button[data-vote]").forEach((btn) => {{
        btn.addEventListener("click", () => {{
          const vote = btn.getAttribute("data-vote");
          const cur = loadVotes();
          // повторный клик по той же кнопке снимает оценку
          if (cur[pin] === vote) delete cur[pin];
          else cur[pin] = vote;
          saveVotes(cur);
          applyCard(card, cur[pin] || null);
          refreshStats(cur);
        }});
      }});
    }}
    refreshStats(votes);
  }}

  document.getElementById("btnReset").addEventListener("click", () => {{
    if (!confirm("Сбросить все твои оценки по этому отчёту?")) return;
    localStorage.removeItem(KEY);
    for (const card of cards) applyCard(card, null);
    refreshStats({{}});
  }});

  document.getElementById("btnExport").addEventListener("click", () => {{
    const votes = loadVotes();
    let ok = 0, bad = 0;
    const detail = [];
    for (const card of cards) {{
      const pin = card.getAttribute("data-pin");
      const pred = card.getAttribute("data-pred");
      const vote = votes[pin] || null;
      if (vote === "ok") ok++;
      if (vote === "bad") bad++;
      detail.push({{ pin_id: pin, pred: pred, human: vote }});
    }}
    const marked = ok + bad;
    const payload = {{
      marked, ok, bad,
      accuracy: marked ? ok / marked : null,
      votes, detail,
    }};
    const blob = new Blob([JSON.stringify(payload, null, 2)], {{
      type: "application/json",
    }});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "human_votes.json";
    a.click();
    URL.revokeObjectURL(a.href);
  }});

  init();
}})();
</script>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


def rows_from_json(path: Path) -> list[ProbeRow]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ProbeRow(**item) for item in data]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    report_only = "--report-only" in sys.argv
    t0 = time.perf_counter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("  UGC vs Pro — 50 photo probe")
    print("=" * 64)
    print(f"Out: {OUT_DIR}")

    if report_only:
        if not META_PATH.is_file():
            print(f"FAIL: нет {META_PATH} — сначала полный прогон")
            return 1
        rows = rows_from_json(META_PATH)
        write_html(rows, REPORT_PATH)
        print(f"HTML пересобран: {REPORT_PATH} ({len(rows)} карточек)")
        return 0

    harvester = PinterestHarvester(on_status=_status)
    try:
        harvester.warm_session(force=False)
        items = collect_images(harvester, target=TARGET)
    except Exception as exc:
        print(f"FAIL harvest: {exc}")
        traceback.print_exc()
        return 1
    finally:
        harvester.close()

    if len(items) < 10:
        print(f"FAIL: too few images ({len(items)})")
        return 1
    if len(items) < TARGET:
        print(f"WARNING: only {len(items)}/{TARGET} images collected")

    print("\n--- scoring ---", flush=True)
    try:
        rows = score_and_save(items)
    except Exception as exc:
        print(f"FAIL score: {exc}")
        traceback.print_exc()
        return 1

    write_html(rows, REPORT_PATH)
    META_PATH.write_text(
        json.dumps([asdict(r) for r in rows], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    live = sum(1 for r in rows if r.status_key == "live")
    stock = sum(1 for r in rows if r.status_key == "stock")
    mixed = sum(1 for r in rows if r.status_key == "mixed")
    elapsed = time.perf_counter() - t0

    print("\n" + "=" * 64)
    print(
        f"  Всего: {len(rows)} | Живой быт: {live} | "
        f"Сток/Профи: {stock} | Пограничные: {mixed}"
    )
    print(f"  HTML: {REPORT_PATH}")
    print(f"  JSON: {META_PATH}")
    print(f"  Время: {elapsed:.1f} с")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
