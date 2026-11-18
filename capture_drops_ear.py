#!/usr/bin/env python3
"""Drops «whimsical websites to train your ear» — скрины сайтов для экрана iMac (headless Edge, временный профиль без входа).
→ downloads/drops_ear/shots/{musicmap,whosampled,samplette}_NN.png (1120×630 @2x). Скрины Drops — только из Dropbox клиента
(make_drops_ear_frames в build_drops_ear.py), здесь не снимаем."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "downloads" / "drops_ear" / "shots"
VW, VH = 1120, 630
DECLINE = ("Do not consent", "Reject all", "Reject All", "Decline", "Only necessary", "Necessary only", "Disagree",
           "Refuse", "Deny", "I do not accept")
HIDE_ADS = """for (const s of ['iframe','ins','[id*="google_ads"]','[class*="adsbygoogle"]','[id*="ad-"]','[class*="ad-slot"]',
 '[class*="cookie"]','[id*="cookie"]','[class*="consent"]','[id*="consent"]','#onetrust-banner-sdk','.fc-consent-root'])
 document.querySelectorAll(s).forEach(e => e.style.setProperty('display','none','important'));"""


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
    try:
        page.evaluate(HIDE_ADS)
    except Exception:
        pass
    time.sleep(0.6)
    page.screenshot(path=str(OUT / f"{name}.png"))
    print("  ", name, flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    plan = [
        ("musicmap", "https://musicmap.info/", [("scroll", 0), ("scroll", 700), ("scroll", 1500), ("scroll", 2400)]),
        ("whosampled", "https://www.whosampled.com/", [("scroll", 0), ("scroll", 650)]),
        ("whosampled", "https://www.whosampled.com/Daft-Punk/Harder,-Better,-Faster,-Stronger/", [("scroll", 0), ("scroll", 500)]),
        ("whosampled", "https://www.whosampled.com/Kanye-West/Stronger/", [("scroll", 0)]),
        ("samplette", "https://samplette.io/", [("scroll", 0), ("wait", 8), ("scroll", 400)]),
    ]
    n: dict = {}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        ctx = b.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=2, locale="en-US")
        page = ctx.new_page()
        for name, url, steps in plan:
            try:
                page.goto(url, wait_until="load", timeout=60000)
                time.sleep(7)
                decline(page)
                for kind, v in steps:
                    if kind == "scroll":
                        page.evaluate(f"window.scrollTo(0, {v})")
                        time.sleep(1.5)
                    else:
                        time.sleep(v)
                    n[name] = n.get(name, 0) + 1
                    shot(page, f"{name}_{n[name]:02d}")
            except Exception as e:
                print("   сбой", name, url, str(e).splitlines()[0][:140], flush=True)
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
