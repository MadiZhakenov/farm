#!/usr/bin/env python3
"""
Drops 3 карусели (build_drops_c3.py, 1.8): рейтинг игры рассказчика (noah) — Tyler №1. Основа — capture_drops_ghost_ranks.py.
Drops ID 1 (build_drops_ghost.py): кадр-переход «он играет в мою игру» — вкладка Ranks её игры Party Pop - Neon Arcade (автор Aria Vale)
в мобильной вёрстке, на первом месте — он (имя, крупный счёт), она второй, у игры больше прослушиваний. Таблица внутри iframe playmusic.gg,
правим текст в нём через Playwright и снимаем экран (headless Edge, 360×640 @3 → 1080×1920, зум панели 1.2).

  python capture_drops_ghost_ranks.py      # → downloads/drops_ghost/ranks/ranks_<name>.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "downloads" / "drops_carousels3" / "ranks"
CREATOR = "noah"
URL = "https://drops.game/s/gmft9egp"
VARIANTS = [("tyler", "14,820", "57"), ("tyler", "12,460", "43"), ("tyler", "16,300", "71"), ("tyler", "11,940", "38"),
            ("tyler", "13,580", "64"), ("tyler", "15,210", "52")]

JS = """([name, score, plays]) => {
  const leaves = [...document.querySelectorAll('body *')].filter(e => e.childElementCount === 0);
  const me = leaves.find(e => e.textContent.trim() === 'Aria Vale' && e.closest('li, [role=row], div') && e.getBoundingClientRect().top > 250);
  if (!me) return 'no row';
  let row = me.parentElement;
  while (row && !row.textContent.includes('300')) row = row.parentElement;
  const copy = row.cloneNode(true);
  for (const e of copy.querySelectorAll('*')) {
    if (e.childElementCount) continue;
    const t = e.textContent.trim();
    if (t === 'Aria Vale') e.textContent = name;
    else if (t === '300') e.textContent = score;
  }
  for (const e of row.querySelectorAll('*')) if (!e.childElementCount && e.textContent.trim() === '1') e.textContent = '2';
  row.parentElement.insertBefore(copy, row);
  for (const e of leaves) if (e.textContent.trim() === '3' && e.getBoundingClientRect().top < 250) e.textContent = plays;
  return 'ok';
}"""


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        ctx = b.new_context(viewport={"width": 360, "height": 640}, device_scale_factor=3, is_mobile=True, has_touch=True, locale="en-US")
        for name, score, plays in VARIANTS:
            page = ctx.new_page()
            page.goto(URL, wait_until="load", timeout=60000)
            page.wait_for_timeout(9000)
            fr = next(f for f in page.frames if "playmusic.gg" in f.url)
            fr.locator("text=Ranks").locator("visible=true").first.click(timeout=15000)
            page.wait_for_timeout(2500)
            res = fr.evaluate(JS, [name, score, plays])
            fr.evaluate("document.documentElement.style.zoom = '1.2'")          # крупнее: строки рейтинга читаются в ролике
            fr.evaluate("""() => {  // плашка «You / Sign up to rank» закрывала второе место
              const both = [...document.querySelectorAll('body *')].filter(x => x.textContent.includes('Sign up to rank') && x.textContent.includes('You'));
              both.sort((a, b) => a.textContent.length - b.textContent.length);
              let c = both[0];
              while (c && c.parentElement && c.parentElement.getBoundingClientRect().height < 140) c = c.parentElement;
              if (c) c.style.visibility = 'hidden';
              // строка «ARIA VALE / Game creator» ровно под текстом ролика — прячем (она и так видна вторым местом в рейтинге)
              const gc = [...document.querySelectorAll('body *')].find(x => x.childElementCount === 0 && x.textContent.trim() === 'Game creator');
              let h = gc;
              while (h && h.parentElement && h.parentElement.getBoundingClientRect().height < 110) h = h.parentElement;
              if (h) h.style.visibility = 'hidden';
              return c ? c.tagName + ' ' + Math.round(c.getBoundingClientRect().height) : 'none'; }""")
            page.wait_for_timeout(500)
            fr.evaluate("""(c) => { for (const e of document.querySelectorAll('body *')) if (!e.childElementCount) {
                const t = e.textContent.trim(); if (t === 'Aria Vale') e.textContent = c; else if (t === 'ARIA VALE') e.textContent = c.toUpperCase(); else if (t === 'A') e.textContent = c[0].toUpperCase(); } }""", CREATOR)
            page.wait_for_timeout(300)
            page.screenshot(path=str(OUT / f"ranks_{name}_{score.replace(',', '')}.png"))
            print(name, res, flush=True)
            page.close()
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
