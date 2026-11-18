#!/usr/bin/env python3
"""
Drops 3 карусели: скрины МОБИЛЬНОЙ версии игры Party Pop (drops.game/s/gmft9egp) для экранов телефонов на фото
(1.7 — телефон боком, 2.6 — у мамы). Headless Edge как телефон (is_mobile, touch): альбомная 844×390 и портретная 390×844
при DSF 3. Жмём Play внутри iframe, перестраиваемся стрелками, снимаем кадры каждые ~1.1 с, экран Game Over не берём.

  python capture_drops_mobile.py            # → downloads/drops_carousels3/mobile/{land,port}_NN.png
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "downloads" / "drops_carousels3" / "mobile"
URL = "https://drops.game/s/gmft9egp"
MODES = {"port": (390, 844)}


def run(p, mode: str, w: int, h: int, runs: int = 3, shots: int = 8) -> None:
    b = p.chromium.launch(channel="msedge", args=["--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=3, is_mobile=True, has_touch=True, locale="en-US")
    n = 0
    rng = random.Random(7)
    for r in range(runs):
        page = ctx.new_page()
        page.goto(URL, wait_until="load", timeout=60000)
        page.wait_for_timeout(9000)
        fr = next(f for f in page.frames if "playmusic.gg" in f.url)
        if mode == "land":                                              # в альбомной Play не виден в DOM — жмём по месту кнопки
            page.wait_for_timeout(8000)
            page.mouse.click(w * 0.5, h * 0.77)
        elif mode == "port":                                            # портрет: синяя кнопка Play в карточке (≈ 62 % высоты)
            page.wait_for_timeout(11000)
            page.mouse.click(w * 0.5, h * 0.62)
        else:
            try:
                fr.locator("text=Play").locator("visible=true").first.click(timeout=45000)
            except Exception as e:                                      # noqa: BLE001
                print(mode, "нет кнопки Play:", str(e)[:80], flush=True)
                page.close()
                continue
        page.wait_for_timeout(2500)
        for k in range(shots):
            for _ in range(rng.randint(1, 3)):
                page.keyboard.press(rng.choice(["ArrowLeft", "ArrowRight"]))
                page.wait_for_timeout(rng.randint(150, 350))
            txt = fr.evaluate("document.body.innerText").upper()
            if "GAME OVER" in txt or "CRASHED" in txt:
                print(mode, r, "game over на кадре", k, flush=True)
                break
            n += 1
            page.screenshot(path=str(OUT / f"{mode}_{n:02d}.png"))
            page.wait_for_timeout(700)
        page.close()
    print(mode, "кадров", n, flush=True)
    b.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        for mode, (w, h) in MODES.items():
            run(p, mode, w, h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
