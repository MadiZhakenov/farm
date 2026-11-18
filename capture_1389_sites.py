#!/usr/bin/env python3
"""
1389 — скрины сайтов для экрана iMac (отдельный headless Edge через Playwright, свой временный профиль): по несколько
кадров на сайт (разные состояния / прокрутка / нажатия) — для уникальности 200 каруселей.

  python capture_1389_sites.py            # → downloads/1389/shots/<site>_NN.png (1600×900 @1.5x)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "downloads" / "1389" / "shots"
VW, VH = 1600, 900


def shot(page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"))
    print("  ", name, flush=True)


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", args=["--autoplay-policy=no-user-gesture-required", "--use-angle=swiftshader",
                                                      "--enable-unsafe-swiftshader"])
        ctx = b.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=1.5, locale="en-US")
        page = ctx.new_page()

        try:
            print("neal.fun", flush=True)
            page.goto("https://neal.fun/", wait_until="load", timeout=60000); time.sleep(2)
            for i, y in enumerate((0, 700, 1400, 2100)):
                page.evaluate(f"window.scrollTo(0, {y})"); time.sleep(1.2); shot(page, f"neal_{i + 1:02d}")
        except Exception as e:
            print('   сбой:', str(e).splitlines()[0][:120], flush=True)
        try:
            print("radio.garden", flush=True)
            page.goto("https://radio.garden/", wait_until="domcontentloaded", timeout=60000); time.sleep(10)
            shot(page, "radio_01")
            for i in range(2):
                page.mouse.move(VW * 0.65, VH * 0.5); page.mouse.down(); page.mouse.move(VW * 0.35, VH * 0.45, steps=20); page.mouse.up()
                time.sleep(5); shot(page, f"radio_{i + 2:02d}")
        except Exception as e:
            print('   сбой:', str(e).splitlines()[0][:120], flush=True)
        try:
            print("window-swap", flush=True)
            page.goto("https://www.window-swap.com/", wait_until="domcontentloaded", timeout=60000); time.sleep(8)
            shot(page, "window_01")
            for i in range(3):
                try:
                    page.get_by_text("open a new window", exact=False).first.click(timeout=4000)
                except Exception:
                    page.mouse.click(VW / 2, VH / 2)
                time.sleep(7); shot(page, f"window_{i + 2:02d}")
        except Exception as e:
            print('   сбой:', str(e).splitlines()[0][:120], flush=True)
        try:
            print("drops.game", flush=True)
            page.goto("https://drops.game/", wait_until="load", timeout=60000); time.sleep(4)
            for i, y in enumerate((0, 800, 1600, 2400)):
                page.evaluate(f"window.scrollTo(0, {y})"); time.sleep(1.5); shot(page, f"drops_{i + 1:02d}")
        except Exception as e:
            print('   сбой:', str(e).splitlines()[0][:120], flush=True)
        try:
            print("patatap", flush=True)
            page.goto("https://patatap.com/", wait_until="domcontentloaded", timeout=60000); time.sleep(6)
            shot(page, "patatap_01")
            page.mouse.click(VW / 2, VH / 2); time.sleep(1)
            for i, keys in enumerate(("a", "s", "k", "j", "f")):
                page.keyboard.press(keys); time.sleep(0.25); page.keyboard.press(chr(ord(keys) + 1)); time.sleep(0.35)
                shot(page, f"patatap_{i + 2:02d}")
        except Exception as e:
            print('   сбой:', str(e).splitlines()[0][:120], flush=True)
        b.close()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    run()
