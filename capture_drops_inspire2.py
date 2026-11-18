#!/usr/bin/env python3
"""Drops inspire: пересъём CrateDrop (без баннера, результаты DIG) и Radiooooo (баннер cookies скрыт, разные десятилетия)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "downloads" / "drops_inspire" / "shots"
VW, VH = 1120, 700
HIDE_COOKIES = """for (const el of document.querySelectorAll('div,section,aside')) {
  const t = (el.innerText || '').toLowerCase();
  if ((t.includes('cookies') || t.includes('analytics')) && t.length < 400 && el.getBoundingClientRect().width < 900) el.style.display = 'none';
}"""


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
            page.goto("https://www.cratedrop.app", wait_until="load", timeout=60000); time.sleep(5)
            for lab in ("No thanks", "Decline"):
                try:
                    page.get_by_role("button", name=lab).first.click(timeout=2000); time.sleep(1); break
                except Exception:
                    pass
            page.evaluate(HIDE_COOKIES)
            shot(page, "cratedrop_01")
            for i in range(2, 6):
                try:
                    page.get_by_role("button", name="DIG", exact=False).first.click(timeout=3000)
                except Exception:
                    page.get_by_text("DIG", exact=True).first.click(timeout=3000)
                time.sleep(6)
                page.evaluate(HIDE_COOKIES)
                shot(page, f"cratedrop_{i:02d}")
                page.goto("https://www.cratedrop.app", wait_until="load", timeout=60000); time.sleep(4)
                page.evaluate(HIDE_COOKIES)
        except Exception as e:
            print("   сбой cratedrop", str(e).splitlines()[0][:150], flush=True)
        try:
            page.goto("https://app.radiooooo.com", wait_until="load", timeout=60000); time.sleep(8)
            page.evaluate(HIDE_COOKIES)
            shot(page, "radiooooo_01")
            for i, dec in enumerate(("1970", "1930", "1960", "1990", "1950"), 2):
                try:
                    page.get_by_text(dec, exact=True).first.click(timeout=3000); time.sleep(5)
                    page.evaluate(HIDE_COOKIES)
                    shot(page, f"radiooooo_{i:02d}")
                except Exception as e:
                    print("   десятилетие", dec, str(e).splitlines()[0][:100], flush=True)
        except Exception as e:
            print("   сбой radiooooo", str(e).splitlines()[0][:150], flush=True)
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
