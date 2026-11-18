#!/usr/bin/env python3
"""Drops inspire: ещё скрины для уникальности — Radiooooo (страна × десятилетие), CrateDrop (другие разделы)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "downloads" / "drops_inspire" / "shots"
VW, VH = 1120, 700
HIDE = """for (const el of document.querySelectorAll('div,section,aside')) {
  const t = (el.innerText || '').toLowerCase();
  const r = el.getBoundingClientRect();
  if (((t.includes('cookies') || t.includes('analytics')) && t.length < 400 && r.width < 900) ||
      (t.includes('free week') && r.width < 600)) el.style.display = 'none';
}
for (const el of document.querySelectorAll('div')) {           // тёмная подложка окна
  const s = getComputedStyle(el); const r = el.getBoundingClientRect();
  if ((s.position === 'fixed' || s.position === 'absolute') && r.width > 1000 && r.height > 600 && s.backgroundColor.includes('rgba') && !el.querySelector('canvas,svg,img')) el.style.display = 'none';
}"""
COUNTRY = {"uk": (515, 186), "italy": (683, 398), "spain": (482, 466), "germany": (650, 220), "poland": (773, 186), "france": (549, 320)}
DECADE_X = {"1930": 343, "1950": 467, "1960": 529, "1970": 591, "1980": 653, "1990": 715}


def shot(page, name: str) -> None:
    time.sleep(0.6)
    page.screenshot(path=str(OUT / f"{name}.png"))
    print("  ", name, flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        ctx = b.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=2, locale="en-US")
        page = ctx.new_page()
        try:
            page.goto("https://app.radiooooo.com", wait_until="load", timeout=60000); time.sleep(8)
            page.evaluate(HIDE)
            for i, (c, dec) in enumerate((("italy", "1950"), ("spain", "1980"), ("germany", "1990"),
                                          ("poland", "1970"), ("france", "1930"), ("uk", "1960")), 5):
                page.mouse.click(*COUNTRY[c]); time.sleep(2.5)
                page.keyboard.press("Escape"); page.evaluate(HIDE)
                page.mouse.click(DECADE_X[dec], 549); time.sleep(3.5)
                for _ in range(2):                         # окно регистрации — крестик
                    try:
                        page.mouse.click(728, 110); time.sleep(0.8)
                    except Exception:
                        pass
                page.evaluate(HIDE)
                shot(page, f"radiooooo_{i:02d}")
        except Exception as e:
            print("   сбой radiooooo", str(e).splitlines()[0][:150], flush=True)
        for i, u in enumerate((), 6):
            try:
                page.goto(f"https://www.cratedrop.app/{u}", wait_until="load", timeout=60000); time.sleep(6)
                for lab in ("No thanks", "Decline"):
                    try:
                        page.get_by_role("button", name=lab).first.click(timeout=1500); time.sleep(1); break
                    except Exception:
                        pass
                page.evaluate(HIDE)
                shot(page, f"cratedrop_{i:02d}")
            except Exception as e:
                print("   сбой cratedrop", u, str(e).splitlines()[0][:120], flush=True)
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
