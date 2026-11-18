#!/usr/bin/env python3
"""Помощник на ноутбуке: запустить ОДИН раз из общей папки — дальше главный ПК ставит ему задания сам.

  \\\\192.168.11.39\\farm\\two_machines_laptop.cmd farm_worker.py              # окно не закрывать
  \\\\192.168.11.39\\farm\\two_machines_laptop.cmd farm_worker.py --autostart  # + сам запускается при входе в Windows

Что делает:
  • раз в 3 с пишет загрузку ноутбука (output/_work/_node_load/<МАШИНА>.json) — дашборд главного ПК её рисует;
  • берёт задания из output/_work/_farm_jobs/<id>.json (их ставит главный ПК: python farm_jobs.py run …),
    запускает сборщик из общей папки (лог — output/_work/_node_logs/<МАШИНА>_<id>.log), состояние пишет в
    <id>.<МАШИНА>.state; <id>.stop — остановить. Запускаются только .py из корня папки farm, без командной строки.
  • новая версия farm_worker.py в общей папке — перезапускается сам, когда свободен.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import farm_node as NODE  # noqa: E402

JOBS = ROOT / "output" / "_work" / "_farm_jobs"
LOGS = ROOT / "output" / "_work" / "_node_logs"
SAFE = re.compile(r"^[A-Za-z0-9_]+\.py$")


def say(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def state(jid: str, **kw) -> None:
    p = JOBS / f"{jid}.{NODE.HOST}.state"
    d = dict(host=NODE.HOST, t=time.time(), **kw)
    try:
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def autostart() -> Path:
    """Ярлык в «Автозагрузке» этого пользователя (без прав администратора)."""
    d = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    p = d / "farm_worker.cmd"
    cmd = ROOT / "two_machines_laptop.cmd"
    p.write_text(f'@echo off\r\nstart "farm worker" /min cmd /c ""{cmd}" farm_worker.py"\r\n', encoding="cp866")
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--autostart", action="store_true", help="запускаться при входе в Windows")
    a = ap.parse_args()
    for st in (sys.stdout, sys.stderr):                    # вывод в файл/окно — без падений на символах
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if a.autostart:
        say(f"автозапуск: {autostart()}")
    from core import hw
    say(f"помощник {NODE.HOST}: папка {ROOT}, видео — {hw.mode()}, torch — {hw.device()}, python {sys.version.split()[0]}")
    JOBS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    NODE.start_load_reporter()
    me = Path(__file__).resolve()
    my_mtime = me.stat().st_mtime
    running: dict[str, list] = {}                          # id → [Popen…]
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", FARM_NO_TEE="1", PYTHONFAULTHANDLER="1",
               PYTHONPYCACHEPREFIX=str(Path(os.environ.get("LOCALAPPDATA", ".")) / "farm_pycache"))
    say("жду задания от главного ПК (output/_work/_farm_jobs)")
    while True:
        try:
            # 1) закончились/остановлены
            for jid, procs in list(running.items()):
                if (JOBS / f"{jid}.stop").exists():
                    for p in procs:
                        kill_tree(p.pid)
                    state(jid, state="stopped")
                    say(f"{jid}: остановлено с главного ПК")
                    del running[jid]
                    continue
                codes = [p.poll() for p in procs]
                if all(c is not None for c in codes):
                    ok = all(c == 0 for c in codes)
                    state(jid, state="done" if ok else "error", codes=codes)
                    say(f"{jid}: {'готово' if ok else f'ошибка, коды {codes}'}")
                    del running[jid]
            # 2) новые задания
            for f in sorted(JOBS.glob("*.json")):
                jid = f.stem
                if jid in running or (JOBS / f"{jid}.{NODE.HOST}.state").exists() or (JOBS / f"{jid}.stop").exists():
                    continue
                try:
                    job = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                hosts = job.get("hosts") or ["*"]
                if "*" not in hosts and NODE.HOST not in hosts:
                    continue
                if time.time() - job.get("created", 0) > 24 * 3600:
                    continue
                script, args = str(job.get("script", "")), [str(x) for x in job.get("args", [])]
                if not SAFE.match(script) or not (ROOT / script).is_file():
                    state(jid, state="refused", why=f"не скрипт из папки farm: {script!r}")
                    continue
                procs = []
                for c in range(max(1, int(job.get("copies", 1)))):
                    log = open(LOGS / f"{NODE.HOST}_{jid}_{c}.log", "a", encoding="utf-8")
                    jenv = dict(env, **{k: str(v) for k, v in (job.get("env") or {}).items() if re.match(r"^(FARM|MV|MR|CB|GPU)_[A-Z0-9_]+$", k)})
                    procs.append(subprocess.Popen([sys.executable, str(ROOT / script), *args], cwd=str(ROOT), env=jenv,
                                                  stdout=log, stderr=subprocess.STDOUT,
                                                  creationflags=subprocess.CREATE_NEW_PROCESS_GROUP))
                running[jid] = procs
                state(jid, state="running", pids=[p.pid for p in procs])
                say(f"{jid}: запущено {script} {' '.join(args)} (копий {len(procs)})")
            # 3) новая версия помощника — перезапуск, когда свободен
            if not running and me.stat().st_mtime != my_mtime:
                say("новая версия помощника — перезапускаюсь")
                subprocess.Popen([sys.executable, str(me)], env=os.environ.copy())
                return 0
        except OSError as e:                               # сеть моргнула — не падаем
            say(f"нет доступа к общей папке: {e}")
        time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
