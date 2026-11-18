#!/usr/bin/env python3
"""Drops «Websites that keep you inspired to make music Part 2» — скрины сайтов для экрана монитора (headless Edge,
временный профиль без входа). → downloads/drops_inspire/shots/{cratedrop,drops,radiooooo}_NN.png (1120×700 @2x)"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "downloads" / "drops_inspire" / "shots"
VW, VH = 1120, 700
DECLINE = ("Do not consent", "Reject all", "Reject All", "Decline", "Only necessary", "Necessary only", "Disagree", "Refuse")


def decline(page) -> None:
    for label in DECLINE:
        try:
            b = page.get_by_role("button", name=label, exact=False).first
            if b.is_visible(timeout=300):
                b.click(timeout=1500)
                time.sleep(1)
                return
        except Exception:
            pass


def shot(page, name: str) -> None:
    time.sleep(0.5)
    page.screenshot(path=str(OUT / f"{name}.png"))
    print("  ", name, flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        ctx = b.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=2, locale="en-US")
        page = ctx.new_page()
        for name, url, scrolls in (("cratedrop", "https://www.cratedrop.app", (0, 500, 1000)),
                                   ("drops", "https://drops.game/", (0, 700, 1400)),
                                   ("radiooooo", "https://app.radiooooo.com", (0,))):
            try:
                page.goto(url, wait_until="load", timeout=60000)
                time.sleep(6)
                decline(page)
                for i, y in enumerate(scrolls, 1):
                    page.evaluate(f"window.scrollTo(0, {y})")
                    time.sleep(1.5)
                    shot(page, f"{name}_{i:02d}")
            except Exception as e:
                print("   сбой", name, str(e).splitlines()[0][:120], flush=True)
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
