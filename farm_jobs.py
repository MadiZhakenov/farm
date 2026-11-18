#!/usr/bin/env python3
"""Задания для помощников на других машинах (farm_worker.py на ноутбуке) — ставятся с главного ПК.

  python farm_jobs.py run build_inspoy_moveon_v2.py --run 2m --yt 40 --jobs 6      # всем помощникам
  python farm_jobs.py run --hosts LAPTOP-X --copies 2 build_matryoshka.py --redo output/x
  python farm_jobs.py ls                                                            # помощники и задания
  python farm_jobs.py stop <id> | all
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JOBS = ROOT / "output" / "_work" / "_farm_jobs"
LOAD = ROOT / "output" / "_work" / "_node_load"


def run(argv: list[str]) -> str:
    hosts, copies = ["*"], 1
    while argv and argv[0] in ("--hosts", "--copies"):
        if argv[0] == "--hosts":
            hosts = argv[1].split(",")
        else:
            copies = int(argv[1])
        argv = argv[2:]
    script, args = argv[0], argv[1:]
    if not re.match(r"^[A-Za-z0-9_]+\.py$", script) or not (ROOT / script).is_file():
        raise SystemExit(f"нет скрипта {script} в корне {ROOT}")
    jid = f"{time.strftime('%m%d_%H%M%S')}{int(time.time() * 1000) % 1000:03d}_{Path(script).stem}"
    JOBS.mkdir(parents=True, exist_ok=True)
    (JOBS / f"{jid}.json").write_text(json.dumps(dict(script=script, args=args, hosts=hosts, copies=copies,
                                                      created=time.time()), ensure_ascii=False), encoding="utf-8")
    return jid


def ls() -> None:
    now = time.time()
    for f in sorted(LOAD.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        s = d.get("now", {})
        age = now - s.get("t", 0)
        print(f"помощник {d.get('host')}: {'на связи' if age < 15 else f'нет связи {age / 60:.0f} мин'} · "
              f"процессор {s.get('cpu', '?')} % · видеоядро {max([s.get(k, 0) for k in ('g3d', 'gcomp', 'vdec', 'venc')])} %")
    for f in sorted(JOBS.glob("*.json")):
        j = json.loads(f.read_text(encoding="utf-8"))
        st = [json.loads(p.read_text(encoding="utf-8")) for p in JOBS.glob(f"{f.stem}.*.state")]
        sts = ", ".join(f"{s['host']}: {s['state']}" for s in st) or "никто не взял"
        stop = " [стоп]" if (JOBS / f"{f.stem}.stop").exists() else ""
        print(f"{f.stem}{stop}: {j['script']} {' '.join(j['args'])} → {sts}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    if not a or a[0] == "ls":
        ls()
    elif a[0] == "run":
        print(run(a[1:]))
    elif a[0] == "stop":
        ids = [f.stem for f in JOBS.glob("*.json")] if a[1] == "all" else a[1:]
        for i in ids:
            (JOBS / f"{i}.stop").write_text("stop", encoding="utf-8")
            print("стоп:", i)
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
