#!/usr/bin/env python3
"""
1388 Drops — скрины готовых игр с drops.game для слайда 4 («and it turned my track into a game»).
Игры из витрины drops.game/showcase, экран iPhone 390×844 @3x (как настоящий скрин 1170×2532):
заставка игры с кнопкой Play + кадры геймплея через несколько секунд (жмём стрелки — счёт растёт).

  python capture_1388d_games.py            # → downloads/1388d/games/<game>_<NN>.png
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "downloads" / "1388d" / "games"
GAMES = [
    "17bd5eb4-dedc-44c7-95f3-824c3bac4e7e", "0ae512db-7797-46f8-93d6-98afab282d53",
    "53b485c2-938b-4b9f-92c2-6d66f362b405", "d550b193-aff1-45d5-b409-7d387f424ac9",
    "4ccb2c35-e9c6-452b-9374-f33c169b24a3", "6b76a012-4b5e-4a08-9bd7-c1f5eae63ea1",
    "2b225588-c815-4292-8afc-c50b0adc2d22", "0c37d38f-1355-4df1-a864-82ca98924794",
]
SHOTS_AT = (2.5, 6, 10, 15, 21, 28)
KEYS = ("ArrowLeft", "ArrowRight", "ArrowUp", "Space", "ArrowDown")


def run(only: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(5)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", args=["--autoplay-policy=no-user-gesture-required",
                                                      "--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist"])
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, locale="en-US",
                            is_mobile=False, has_touch=False)
        for gi, gid in enumerate(GAMES):
            if only and gid[:8] not in only:
                continue
            tag = f"g{gi + 1}_{gid[:8]}"
            page = ctx.new_page()
            try:
                print(tag, flush=True)
                page.goto(f"https://drops.game/play/{gid}", wait_until="domcontentloaded", timeout=60000)
                btn = None                                   # игра — в iframe, кнопка Play внутри него
                t_end = time.time() + 150
                while btn is None and time.time() < t_end:
                    for fr in page.frames:
                        loc = fr.get_by_text("Play", exact=True)
                        try:
                            if loc.count() and loc.first.is_visible():
                                btn = loc.first
                                break
                        except Exception:
                            pass
                    time.sleep(1)
                if btn is None:
                    raise RuntimeError("нет кнопки Play")
                time.sleep(1.5)
                page.screenshot(path=str(OUT / f"{tag}_00_title.png"))
                btn.click()
                t0 = time.time()
                k = 1
                for at in SHOTS_AT:
                    while time.time() - t0 < at:
                        if rng.random() < 0.6:
                            page.keyboard.press(rng.choice(KEYS))
                        time.sleep(0.35)
                    page.screenshot(path=str(OUT / f"{tag}_{k:02d}.png"))
                    k += 1
                print("   ok", flush=True)
            except Exception as e:
                print("   сбой:", str(e).splitlines()[0][:150], flush=True)
            finally:
                page.close()
        b.close()


if __name__ == "__main__":
    run(sys.argv[1:])
