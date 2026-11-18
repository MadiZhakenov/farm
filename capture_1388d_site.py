#!/usr/bin/env python3
"""
1388 Drops — слайд 3 без аккаунта: главная drops.game на экране iPhone Pro Max (430×932 @3x → 1290×2796):
в этой ширине кнопки Get started / Upload a song стоят в ряд и первый экран целиком влезает в 3:4.
Загрузка трека открывается только после входа (Upload → /signin), поэтому снимаем то, что видно без него:
верх главной («DROP A SONG. get a playable game.» + Upload a song) и блок «THREE MOVES / 01 UPLOAD».
Баннер cookie не принимаем — просто убираем его из кадра.

  python capture_1388d_site.py            # → downloads/1388d/site/<name>.png
"""

from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "downloads" / "1388d" / "site"
HIDE = """
for (const el of document.querySelectorAll('[class^="cky-"], [class*=" cky-"], [id^="cky"], [class*=cookieyes]')) el.remove();
"""


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", args=["--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist"])
        ctx = b.new_context(viewport={"width": 430, "height": 932}, device_scale_factor=3, locale="en-US")
        page = ctx.new_page()
        page.goto("https://drops.game/", wait_until="networkidle", timeout=90000)
        time.sleep(3)
        page.evaluate(HIDE)
        page.screenshot(path=str(OUT / "home_top.png"))
        for i, y in enumerate((120, 260)):
            page.evaluate(f"window.scrollTo(0, {y})")
            time.sleep(1.2)
            page.evaluate(HIDE)
            page.screenshot(path=str(OUT / f"home_scroll{i + 1}.png"))
        moves = page.get_by_text("THREE MOVES.", exact=False).first
        moves.scroll_into_view_if_needed()
        page.evaluate("window.scrollBy(0, -90)")
        time.sleep(1.5)
        page.evaluate(HIDE)
        page.screenshot(path=str(OUT / "home_moves.png"))
        btn = page.get_by_text("Upload a song", exact=False).first
        btn.scroll_into_view_if_needed()
        page.evaluate("window.scrollBy(0, -420)")
        time.sleep(1)
        btn.hover()
        time.sleep(0.6)
        page.evaluate(HIDE)
        page.screenshot(path=str(OUT / "home_upload_hover.png"))
        b.close()
    print("готово:", OUT)


if __name__ == "__main__":
    run()
