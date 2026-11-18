#!/usr/bin/env python3
"""
Drops react — отдельный Edge с постоянным профилем (вход в drops.game сохраняется) и портом отладки 9333:
к нему по CDP подключаются шаги сценария (connect_over_cdp) и фоновая запись экрана (drops_screenrec.py).

  python drops_browser.py login        # обычное окно — пользователь сам входит в drops.game (один раз)
  python drops_browser.py phone        # без окна, «телефон» 432×936 при DSF 2.5 (кадры ~1080×2340) — для записи
  python drops_browser.py stop
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EDGE = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
PROFILE = ROOT / "output" / "_work" / "drops_profile"
PORT = 9333
GPU = ["--use-angle=d3d11", "--ignore-gpu-blocklist", "--force_high_performance_gpu", "--enable-gpu-rasterization"]


def stop() -> None:
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
                    f"Where-Object {{ $_.CommandLine -like '*drops_profile*' }} | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
                   check=False)
    time.sleep(1.5)


def start(mode: str) -> None:
    PROFILE.mkdir(parents=True, exist_ok=True)
    args = [str(EDGE), f"--user-data-dir={PROFILE}", f"--remote-debugging-port={PORT}", "--no-first-run",
            "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required", *GPU]
    if mode == "login":
        args += ["--window-size=1100,900", "https://drops.game/signin"]
    else:
        args += ["--headless=new", "--force-device-scale-factor=2.5", "--window-size=432,936",
                 "--hide-scrollbars", "https://drops.game/create"]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Edge ({mode}) -> port {PORT}, profile {PROFILE}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "phone"
    stop()
    if cmd != "stop":
        start(cmd)
