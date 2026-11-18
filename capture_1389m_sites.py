#!/usr/bin/env python3
"""
1389m (сайты для музыкантов) — скрины новых сайтов для экрана iMac: headless Edge через Playwright, временный профиль без входа.
Баннеры согласия закрываем отказом. → downloads/1389/shots/{musicmap,everynoise,musicca}_NN.png (1120×630 @2x, текст крупнее на экране iMac)

  python capture_1389m_sites.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "downloads" / "1389" / "shots"
VW, VH = 1120, 630
HIDE_ADS = "ins,iframe,.adsbygoogle,[id*=google_ads],[class*=adsense],[id*=ad-],[class*=ad-container]{display:none!important}"
DECLINE = ("Do not consent", "Reject all", "Reject All", "Decline", "Only necessary", "Necessary only", "Disagree")


def shot(page, name: str) -> None:
    page.add_style_tag(content=HIDE_ADS)
    time.sleep(0.4)
    page.screenshot(path=str(OUT / f"{name}.png"))
    print("  ", name, flush=True)


def decline(page) -> None:
    for frame in page.frames:
        for label in DECLINE:
            try:
                b = frame.get_by_role("button", name=label, exact=False).first
                if b.is_visible(timeout=300):
                    b.click(timeout=1500)
                    print("   отказ в баннере:", label, flush=True)
                    time.sleep(1)
                    return
            except Exception:
                pass


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        ctx = b.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=2, locale="en-US")
        page = ctx.new_page()
        for i, a in enumerate(("taylor+swift", "the+weeknd", "billie+eilish", "arctic+monkeys", "tame+impala", "frank+ocean"), 1):
            try:
                page.goto(f"https://www.music-map.com/{a}", wait_until="load", timeout=45000); time.sleep(5)
                if i == 1:
                    decline(page); time.sleep(1)
                shot(page, f"musicmap_{i:02d}")
            except Exception as e:
                print("   сбой music-map", a, str(e).splitlines()[0][:100], flush=True)
        try:
            page.goto("https://everynoise.com/", wait_until="load", timeout=60000); time.sleep(4)
            decline(page)
            for i, y in enumerate((2500, 5000, 7000, 9500, 12000, 14500), 1):
                page.evaluate(f"window.scrollTo(0, {y})"); time.sleep(1.2); shot(page, f"everynoise_{i:02d}")
        except Exception as e:
            print("   сбой everynoise", str(e).splitlines()[0][:100], flush=True)
        for i, u in enumerate(("", "exercises/notes", "exercises/intervals", "piano", "guitar", "exercises/chords"), 1):
            try:
                page.goto(f"https://www.musicca.com/{u}", wait_until="load", timeout=45000); time.sleep(3)
                decline(page); time.sleep(1)
                shot(page, f"musicca_{i:02d}")
            except Exception as e:
                print("   сбой musicca", u, str(e).splitlines()[0][:100], flush=True)
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
