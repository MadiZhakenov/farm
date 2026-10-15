#!/usr/bin/env python3
"""
Запись экрана сайта как с телефона (вертикально 1080×1920, 30 к/с): Edge через Playwright, мобильная эмуляция
360×640 @3x, плавный скролл с паузами. Кадры — скриншоты по шагам (ровно, без рывков записи), CSS-анимации
сайта замедляются под реальное время съёмки кадра, чтобы на видео шли с нормальной скоростью.

  python record_site_scroll.py https://globalwork.ai/en --out downloads/gw_hidden/screen/globalwork_scroll.mp4
  python record_site_scroll.py https://globalwork.ai/en --desktop --plan 1.2:0,2.0:520,1.0:520,2.0:1150,1.0:1150 --out x.mp4
"""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
FPS = 30
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
      "Version/17.5 Mobile/15E148 Safari/604.1")
# сценарий: (длительность, с; скролл до, css px) — пауза = тот же y
PLAN = [(1.6, 0), (2.2, 760), (0.9, 760), (2.2, 1560), (1.1, 1560)]


def ease(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * t)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--desktop", action="store_true", help="16:9 как с ноутбука: 1280×720 @1.5 → 1920×1080")
    ap.add_argument("--plan", help="сценарий 'длит:y,длит:y,…' (с, css px), по умолчанию — PLAN")
    args = ap.parse_args()
    plan = [tuple(float(x) for x in st.split(":")) for st in args.plan.split(",")] if args.plan else PLAN
    args.out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="scroll_"))
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        if args.desktop:
            ctx = b.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5, locale="en-US")
        else:
            ctx = b.new_context(viewport={"width": 360, "height": 640}, device_scale_factor=3, is_mobile=True,
                                has_touch=True, user_agent=UA, locale="en-US")
        pg = ctx.new_page()
        pg.goto(args.url, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(2500)
        pg.add_style_tag(content="::-webkit-scrollbar{display:none} html{scroll-behavior:auto!important}")
        # замер времени одного скриншота → замедление CSS-анимаций до реального темпа
        t0 = time.perf_counter()
        for _ in range(3):
            pg.screenshot(path=str(work / "probe.png"))
        shot = (time.perf_counter() - t0) / 3
        cdp = ctx.new_cdp_session(pg)
        cdp.send("Animation.enable")
        cdp.send("Animation.setPlaybackRate", {"playbackRate": max(0.05, (1 / FPS) / shot)})
        k, y_prev = 0, 0
        for dur, y_to in plan:
            n = int(round(dur * FPS))
            for i in range(n):
                y = y_prev + (y_to - y_prev) * ease((i + 1) / n)
                pg.evaluate(f"window.scrollTo(0, {y:.1f})")
                pg.screenshot(path=str(work / f"f{k:05d}.png"))
                k += 1
            y_prev = y_to
        b.close()
    subprocess.run([FF, "-v", "error", "-y", "-framerate", str(FPS), "-i", str(work / "f%05d.png"),
                    "-vf", ("scale=1920:1080" if args.desktop else "scale=1080:1920") + ":flags=lanczos,format=yuv420p", "-c:v", "libx264", "-preset", "slow",
                    "-crf", "16", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                    str(args.out)], check=True)
    shutil.rmtree(work, ignore_errors=True)
    print(f"кадров {k}, скриншот {shot * 1000:.0f} мс → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
