#!/usr/bin/env python3
"""Постоянный присмотр за загрузкой компьютера во время партий (юзер 17.11: «постоянно следить за показателями
загрузки и чтоб видюха рил нагружалась»). Раз в 10 с: процессор, видеокарта (общая/декодер/кодер), память видеокарты,
идёт ли сборщик (build_*.py). Печатает сводку раз в --every с и сразу — тревоги:
  • идёт партия, а видеокарта < 15 % три минуты подряд — простой (сборщик завис/ждёт);
  • память видеокарты > 7.4 ГБ — риск зависания очереди;
  • идёт партия, процессор < 60 % и видеокарта < 50 % три минуты — недогруз (можно больше сборок сразу).
  python watch_load.py --every 300"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections import deque

import psutil


def gpu() -> tuple[int, int, int, int]:
    r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,utilization.decoder,utilization.encoder,memory.used",
                        "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout.strip().split(",")
    return tuple(int(float(x)) for x in r)  # type: ignore[return-value]


def builders() -> list[str]:
    out = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            cmd = p.info["cmdline"] or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if p.info["name"] and p.info["name"].lower().startswith("python") and any(
                c.endswith(".py") and c.split("\\")[-1].split("/")[-1].startswith("build_") for c in cmd):
            if "--multiprocessing-fork" not in cmd:
                out.append(next(c for c in cmd if c.endswith(".py")).split("\\")[-1].split("/")[-1])
    return sorted(set(out))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=300)
    a = ap.parse_args()
    hist: deque = deque(maxlen=18)                       # 3 минуты по 10 с
    last = 0.0
    alarm_at: dict = {}
    psutil.cpu_percent(None)
    while True:
        time.sleep(10)
        cpu = psutil.cpu_percent(None)
        g, dec, enc, mem = gpu()
        b = builders()
        hist.append((cpu, g, mem, bool(b)))
        now = time.time()

        def alarm(key: str, text: str) -> None:
            if now - alarm_at.get(key, 0) > 600:          # одна и та же тревога — не чаще раза в 10 мин
                alarm_at[key] = now
                print(f"ТРЕВОГА: {text}", flush=True)
        full = len(hist) == hist.maxlen
        if full and all(h[3] for h in hist):
            if all(h[1] < 15 for h in hist):
                alarm("idle", f"идёт {', '.join(b)}, а видеокарта < 15 % уже 3 мин (сейчас {g} %, процессор {cpu:.0f} %)")
            if all(h[0] < 60 and h[1] < 50 for h in hist):
                alarm("under", f"недогруз: процессор {cpu:.0f} %, видеокарта {g} % — можно больше сборок сразу")
        if mem > 7400:
            alarm("vram", f"память видеокарты {mem} МБ из 8192 — риск зависания очереди")
        if now - last >= a.every:
            last = now
            avg = lambda i: sum(h[i] for h in hist) / len(hist)   # noqa: E731
            print(f"нагрузка за 3 мин: процессор {avg(0):.0f} %, видеокарта {avg(1):.0f} % (декодер {dec} %, кодер {enc} %), "
                  f"память видеокарты {mem} МБ; идёт: {', '.join(b) or 'ничего'}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
