#!/usr/bin/env python3
"""Прогресс генерации: локальная страница со всеми проектами, которые сейчас пишутся в output/.
  - «Сейчас идёт»: запущенные build_/redo_/make_-скрипты: цель (-n / --range / число в имени папки), сколько готово за этот запуск,
    скорость за последние 3 мин, сколько ждать;
  - «Папки за сутки»: все папки output/, куда писали за последние 24 ч, с прогрессом к числу в имени (…_100 → 100).
Единица — ролик (mp4), карусель (подпапка с картинками) или карусель из плоских слайдов (sort_<слайд>_<номер>_…).
  python progress_server.py          # http://localhost:8767
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
PORT = 8767

# ---------------------------------------------------------------- загрузка компьютера (раз в 2 с, история 10 мин)
SYS_EVERY, SYS_KEEP = 2.0, 300
SYS_HIST: deque = deque(maxlen=SYS_KEEP)
SYS_INFO: dict = {}


def gpu_now() -> dict:
    """nvidia-smi: загрузка видеокарты, блоки сборки (кодирования) и чтения (декодирования) видео, память, температура."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,utilization.encoder,utilization.decoder,"
                            "memory.used,memory.total,temperature.gpu", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        name, g, enc, dec, mu, mt, temp = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
        SYS_INFO.update(gpu_name=name, vram_total=round(float(mt) / 1024, 1))
        return dict(gpu=float(g), enc=float(enc), dec=float(dec), vram=round(float(mu) / 1024, 2), temp=float(temp))
    except Exception:                                   # noqa: BLE001 — нет видеокарты/драйвера: просто без этих графиков
        return {}


def sampler() -> None:
    psutil.cpu_percent(interval=None)
    while True:
        time.sleep(SYS_EVERY)
        vm = psutil.virtual_memory()
        SYS_INFO["ram_total"] = round(vm.total / 2 ** 30, 1)
        g = gpu_now()
        if g and g["vram"] < 0.05 and SYS_HIST and "vram" in SYS_HIST[-1]:
            # драйвер иногда отдаёт все нули разом (память видеокарты 0 — так не бывает): берём прошлый замер
            g = {k: SYS_HIST[-1][k] for k in ("gpu", "enc", "dec", "vram", "temp")}
        SYS_HIST.append(dict(t=round(time.time(), 1), cpu=psutil.cpu_percent(interval=None),
                             ram=round((vm.total - vm.available) / 2 ** 30, 2)) | g)
VID = {".mp4", ".mov"}
IMG = {".jpg", ".jpeg", ".png", ".webp"}
SKIP = {"_work", "_old"}
_recent_cache: dict = {"t": 0.0, "dirs": []}


def walk(d: Path, depth: int = 3) -> list[tuple[Path, float]]:
    out = []
    try:
        with os.scandir(d) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False):
                    if depth > 0:
                        out += walk(Path(e.path), depth - 1)
                elif os.path.splitext(e.name)[1].lower() in VID | IMG:
                    out.append((Path(e.path), e.stat().st_mtime))
    except OSError:
        pass
    return out


def target_of(name: str) -> int | None:
    m = re.search(r"_(\d{2,4})(?:_[a-z0-9]+)?$", name)
    return int(m.group(1)) if m else None


def units(folder: Path, files: list[tuple[Path, float]]) -> dict:
    """Сколько единиц готово: ролики, карусели-подпапки или плоские слайды."""
    vids = [f for f in files if f[0].suffix.lower() in VID]
    imgs = [f for f in files if f[0].suffix.lower() in IMG]
    if vids:
        return dict(kind="видео", done=len(vids), per=1, files=len(vids))
    if not imgs:
        return dict(kind="—", done=0, per=1, files=0)
    groups: dict = {}
    for p, _ in imgs:
        groups.setdefault(p.parent, []).append(p)
    if len(groups) > 3 and all(g != folder for g in groups):
        per = max(len(v) for v in groups.values())
        full = sum(1 for v in groups.values() if len(v) >= per)
        return dict(kind="карусели", done=full, per=per, files=len(imgs))
    toks = [re.findall(r"\d+", p.stem) for p, _ in imgs]
    n = min(len(t) for t in toks)
    per = 1
    if n:
        distinct = sorted(len({t[k] for t in toks}) for k in range(n))
        small = [x for x in distinct if 1 < x <= 12]
        per = small[0] if small and len(imgs) > 12 else 1
    return dict(kind="карусели" if per > 1 else "картинки", done=round(len(imgs) / per, 1), per=per, files=len(imgs))


def recent_dirs() -> list[Path]:
    if time.time() - _recent_cache["t"] < 30:
        return _recent_cache["dirs"]
    lim = time.time() - 24 * 3600
    res = []
    for e in os.scandir(OUT):
        if not e.is_dir() or e.name in SKIP:
            continue
        if e.stat().st_mtime >= lim:                     # только время самой папки: обход вложенных — десятки секунд
            res.append(Path(e.path))
    _recent_cache.update(t=time.time(), dirs=res)
    return res


JOB_DIRS: dict = {}                                       # (pid, старт) → папки выдачи, куда писали её ffmpeg


def ffmpeg_out_dirs(pid: int) -> set:
    """Папки выдачи (output/<папка>), куда сейчас пишут ffmpeg-потомки процесса: последний аргумент ffmpeg = файл."""
    res = set()
    try:
        kids = psutil.Process(pid).children(recursive=True)
    except psutil.Error:
        return res
    outroot = ROOT / "output"
    for c in kids:
        try:
            if not (c.name() or "").lower().startswith("ffmpeg"):
                continue
            out = Path(c.cmdline()[-1])
        except (psutil.Error, IndexError):
            continue
        if out.suffix.lower() not in VID | IMG:
            continue
        if not out.is_absolute():
            out = ROOT / out
        try:
            rel = out.resolve().relative_to(outroot.resolve())
        except ValueError:
            continue
        if len(rel.parts) >= 2 and not rel.parts[0].startswith("_"):     # output/_work — рабочие файлы, не выдача
            res.add(outroot / rel.parts[0])
    return res


def jobs() -> list[dict]:
    seen: dict = {}
    for p in psutil.process_iter(["name"]):              # cmdline только у python: у всех процессов — ~25 с на Windows
        try:
            if "python" not in (p.info["name"] or "").lower():
                continue
            p.info["cmdline"], p.info["create_time"], p.info["pid"] = p.cmdline(), p.create_time(), p.pid
            cmd = p.info["cmdline"] or []
            scr = next((c for c in cmd if c.endswith(".py")), None)
            if not scr:
                continue
            base = Path(scr).name
            if base == Path(__file__).name or base.startswith("tuner_"):
                continue
            key = " ".join(cmd[cmd.index(scr):])
            if key not in seen or p.info["create_time"] < seen[key]["start"]:
                seen[key] = dict(script=base, args=cmd[cmd.index(scr) + 1:], start=p.info["create_time"], pid=p.info["pid"],
                                 build=bool(re.match(r"(build_|redo|make_|render_|qa_)", base)))
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            continue
    out = []
    for j in seen.values():
        a = j["args"]
        cpu = tree_cpu(j["pid"])
        # прогресс из output/_work/_qa_progress/<pid>.json (qa_batch.tick): у проверок всегда, у сборок/пересборок —
        # если скрипт его пишет (иначе считаем файлы в папках)
        # .venv\Scripts\python.exe — лаунчер: настоящий python (он пишет <pid>.json) — его дочерний процесс
        pids = [j["pid"]]
        try:
            pids += [c.pid for c in psutil.Process(j["pid"]).children(recursive=True)]
        except psutil.Error:
            pass
        pf = next((f for f in (ROOT / "output" / "_work" / "_qa_progress" / f"{q}.json" for q in pids) if f.exists()),
                  ROOT / "output" / "_work" / "_qa_progress" / f"{j['pid']}.json")
        if j["script"].startswith("qa_") or pf.exists():
            st = json.loads(pf.read_text(encoding="utf-8")) if pf.exists() else {"done": 0, "total": None, "stage": ""}
            el = max(time.time() - j["start"], 1) / 60
            rate = st["done"] / el
            remain = (st["total"] or 0) - st["done"]
            out.append(dict(script=j["script"], args=st.get("stage", ""), stage=st.get("stage", ""), started=j["start"],
                            dirs=[Path(x).name for x in a if not x.startswith("-")], done=st["done"], target=st["total"],
                            rate=round(rate, 1), eta_min=round(remain / rate, 1) if rate > 0 and st["total"] else None,
                            last=pf.stat().st_mtime if pf.exists() else None, cpu=cpu, pid=j["pid"]))
            continue
        if not j["build"]:                              # проверки, распознавание, вспомогательные — без счёта файлов
            out.append(dict(kind="other", script=j["script"], args=" ".join(Path(x).name if ("/" in x or "\\" in x) else x
                                                                             for x in a)[:160],
                            started=j["start"], cpu=cpu, pid=j["pid"], dirs=[], done=0, target=None, rate=0,
                            eta_min=None, last=None))
            continue
        get = lambda k: a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else None   # noqa: E731
        outd = get("--out")
        n = get("-n")
        rng = get("--range")
        target = int(n) if n and n.isdigit() else None
        if rng and re.match(r"^\d+-\d+$", rng):
            lo, hi = map(int, rng.split("-"))
            target = hi - lo + 1
        key = (j["pid"], j["start"])
        JOB_DIRS.setdefault(key, set()).update(ffmpeg_out_dirs(j["pid"]))
        dirs = [ROOT / outd] if outd else sorted(JOB_DIRS[key])
        precise = bool(dirs)
        if not dirs:                                    # без --out и без замеченных ffmpeg: папки, куда писал этот запуск,
            taken = {d for k, v in JOB_DIRS.items() if k != key for d in v}      # кроме точно чужих
            for d in recent_dirs():
                if d not in taken and any(m >= j["start"] for _, m in walk(d, 2)):
                    dirs.append(d)
        written, mts = 0, []
        for d in dirs:
            fs = [f for f in walk(d) if f[1] >= j["start"]]
            u = units(d, fs)
            written += u["done"]
            mts += [m for _, m in fs]
            if target is None and outd:                  # цель из имени папки (…_100) — только если папка задана явно
                target = target_of(d.name)
        if target is None and precise and not outd and dirs and all(target_of(d.name) for d in dirs):
            target = sum(target_of(d.name) for d in dirs)  # папки точно этой сборки: TT_100 + YT_150 → 250
        now = time.time()
        rate = sum(1 for m in mts if m >= now - 180) / 3.0
        if rate == 0 and mts:
            span = (max(mts) - j["start"]) / 60
            rate = len(mts) / span if span > 0.2 else 0
        remain = max(0, (target or 0) - written)
        out.append(dict(script=j["script"], args=" ".join(a), started=j["start"], dirs=[d.name for d in dirs], done=written, target=target,
                        precise=precise, cpu=cpu, pid=j["pid"],
                        rate=round(rate, 1), eta_min=round(remain / rate, 1) if rate > 0 and target else None,
                        last=max(mts) if mts else None))
    py_tree = set()
    for j in seen.values():
        try:
            py_tree |= {c.pid for c in psutil.Process(j["pid"]).children(recursive=True)} | {j["pid"]}
        except psutil.Error:
            pass
    lone = []
    for q in psutil.process_iter(["name", "create_time"]):
        try:
            if (q.info["name"] or "").lower().startswith("ffmpeg") and q.pid not in py_tree:
                lone.append(q)
        except psutil.Error:
            continue
    if lone:
        out.append(dict(kind="other", script=f"ffmpeg без сборщика × {len(lone)}", args="запущены из командной строки/цепочек",
                        started=min(q.info["create_time"] for q in lone), cpu=sum(tree_cpu(q.pid) for q in lone),
                        pid=lone[0].pid, dirs=[], done=0, target=None, rate=0, eta_min=None, last=None))
    out.sort(key=lambda x: x["started"])
    return out


CPU_PREV: dict = {}


def tree_cpu(pid: int) -> float:
    """Процессор дерева процесса (сам + дочерние ffmpeg) в % всей машины с прошлого опроса."""
    try:
        pr = psutil.Process(pid)
        procs = [pr] + pr.children(recursive=True)
        tot = 0.0
        for q in procs:
            try:
                ct = q.cpu_times()
                tot += ct.user + ct.system
            except psutil.Error:
                pass
    except psutil.Error:
        return 0.0
    now = time.time()
    prev = CPU_PREV.get(pid)
    CPU_PREV[pid] = (now, tot)
    if not prev or now - prev[0] < 0.5:
        return 0.0
    return round(max(0.0, (tot - prev[1]) / (now - prev[0]) / (psutil.cpu_count() or 1) * 100), 1)


FOLDER_OLD: dict = {}                                     # (папка, старт сборки) → имена файлов, что были до неё


def folders(active: dict) -> list[dict]:
    """active: имя папки → время старта сборки, которая её сейчас пишет. Пересборка поверх (сборка заменяет файлы,
    которые уже были) — считаем только файлы этого запуска, с нуля, и помечаем redo. Досборка недостающих
    (новые имена) — считаем все файлы папки, как обычно."""
    res = []
    for d in recent_dirs():
        fs = walk(d)
        if not fs:
            continue
        st = active.get(d.name)
        redo = False
        if st is not None:
            old = FOLDER_OLD.setdefault((d.name, st), {f.name for f, m in fs if m < st})
            redo = any(m >= st and f.name in old for f, m in fs)
        u = units(d, [f for f in fs if f[1] >= st] if redo else fs)
        last = max(m for _, m in fs)
        res.append(dict(name=d.name, **u, target=target_of(d.name), last=last, redo=redo,
                        active=d.name in active or time.time() - last < 120))
    res.sort(key=lambda x: -x["last"])
    return res


def status() -> dict:
    js = jobs()
    active: dict = {}
    for j in js:                                          # папка → самый поздний старт пишущей её сборки
        for n in j["dirs"]:
            active[n] = max(active.get(n, 0), j["started"])
    ff = sum(1 for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower().startswith("ffmpeg"))
    cpu = SYS_HIST[-1]["cpu"] if SYS_HIST else 0.0
    return dict(now=time.time(), cpu=cpu, ffmpeg=ff, jobs=js, folders=folders(active),
                sys=dict(SYS_INFO, every=SYS_EVERY, hist=list(SYS_HIST)))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/status"):
            body = json.dumps(status(), ensure_ascii=False).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        else:
            body = (ROOT / "progress_dashboard.html").read_bytes()
            ctype = "text/html; charset=utf-8"
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass                                        # вкладку закрыли/обновили посреди ответа — не страшно


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    threading.Thread(target=sampler, daemon=True).start()
    print(f"прогресс: http://localhost:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
