"""Одна партия на нескольких машинах сразу: главный ПК (папка farm) + ноутбук, который запускает те же сборщики
прямо из общей папки (\\\\WIN-22OHGHD63MT\\farm). Материалы не копируются: пути считаются от папки скрипта.

  HOST          — имя машины (FARM_HOST или имя компьютера); REMOTE — скрипт запущен из сетевой папки.
  Claims(dir)   — заявки на ролики: take(key) атомарно создаёт <key>.claim (O_EXCL; две машины один ролик не
                  возьмут), пока ролик собирается — заявка обновляется (раз в 30 с); заявка без обновления дольше
                  STALE (10 мин: машина упала/уснула) — забирается другой машиной; done(key) → <key>.done навсегда,
                  drop(key) — отказ (брак/ошибка), ролик снова свободен.
  shared_lock(path) — замок между процессами и машинами (блокировка байта файла: SMB держит её для всех клиентов,
                  падение процесса снимает) — для «сверка с банком → запись отпечатков» без гонки.
  local_dir(p)  — куда писать тяжёлые промежуточные файлы: на ноутбуке — его диск (FARM_LOCAL_WORK, по умолчанию
                  %LOCALAPPDATA%\\farm_work\\…), на главном ПК — как раньше (p). В общую папку — только готовое.
  Progress      — output/_work/_qa_progress/<pid>.json (на ноутбуке <HOST>-<pid>.json + host), обновляется раз
                  в 20 с — дашборд главного ПК показывает и сборки ноутбука.
"""

from __future__ import annotations

import contextlib
import json
import msvcrt
import os
import random
import socket
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = os.environ.get("FARM_HOST") or socket.gethostname()
REMOTE = str(ROOT).startswith("\\\\") or os.environ.get("FARM_REMOTE") == "1"
STALE = float(os.environ.get("FARM_CLAIM_STALE", "600"))
BEAT = 30.0


def local_dir(p: Path) -> Path:
    """Папка p в output/_work → на этой машине (для тяжёлых промежуточных файлов). На главном ПК — сама p."""
    base = os.environ.get("FARM_LOCAL_WORK")
    if not base and not REMOTE:
        return Path(p)
    base = Path(base or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "farm_work")
    try:
        rel = Path(p).resolve().relative_to(ROOT / "output" / "_work")
    except ValueError:
        rel = Path(Path(p).name)
    return base / rel


def server_now(d: Path) -> float:
    """Время по часам машины, где лежит папка d (у файлов в общей папке время ставит она — часы машин могут
    расходиться)."""
    f = d / f".now_{HOST}_{os.getpid()}_{threading.get_ident()}"
    try:
        with open(f, "w") as fh:
            fh.write("1")
        t = f.stat().st_mtime
        f.unlink(missing_ok=True)
        return t
    except OSError:
        return time.time()


class Claims:
    """Заявки на ролики одной партии в папке d (общей для всех машин)."""

    def __init__(self, d: Path, stale: float = STALE):
        self.d = Path(d)
        self.d.mkdir(parents=True, exist_ok=True)
        self.stale = stale
        self.held: set[str] = set()
        self.lock = threading.Lock()
        threading.Thread(target=self._beat, daemon=True).start()

    def _p(self, key: str, ext: str = ".claim") -> Path:
        return self.d / f"{key}{ext}"

    def is_done(self, key: str) -> bool:
        return self._p(key, ".done").exists()

    def owner(self, key: str) -> dict | None:
        try:
            return json.loads(self._p(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _create(self, key: str) -> bool:
        try:
            fd = os.open(self._p(key), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        except PermissionError:                            # Windows: файл как раз удаляют/переименовывают
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(dict(host=HOST, pid=os.getpid(), t=time.time())))
        return True

    def take(self, key: str) -> bool:
        """True — ролик наш (никто другой его не собирает и он не готов)."""
        if self.is_done(key):
            return False
        ok = self._create(key)
        if not ok:
            p = self._p(key)
            try:
                age = server_now(self.d) - p.stat().st_mtime
            except OSError:                                # заявку как раз сняли — попробовать ещё раз
                age = None
            own = self.owner(key)
            if age is not None and own and own.get("host") == HOST and own.get("pid") != os.getpid() \
                    and not _alive(int(own.get("pid", 0))):
                age = self.stale + 1                       # процесс этой же машины упал/остановлен — не ждать 10 мин
            if age is None:
                ok = self._create(key)
            elif age > self.stale:                         # хозяин молчит > STALE: забираем (переименование — одно на всех)
                gone = p.with_name(f"{p.name}.stale_{HOST}_{os.getpid()}_{random.randrange(10 ** 6)}")
                try:
                    os.rename(p, gone)
                    gone.unlink(missing_ok=True)
                    ok = self._create(key)
                except OSError:
                    ok = False
        if ok and self.is_done(key):                       # успели закончить, пока мы смотрели
            self._p(key).unlink(missing_ok=True)
            return False
        if ok:
            with self.lock:
                self.held.add(key)
        return ok

    def done(self, key: str) -> None:
        with self.lock:
            self.held.discard(key)
        try:
            os.replace(self._p(key), self._p(key, ".done"))
        except OSError:
            self._p(key, ".done").write_text(json.dumps(dict(host=HOST, t=time.time())), encoding="utf-8")

    def drop(self, key: str) -> None:
        with self.lock:
            self.held.discard(key)
        self._p(key).unlink(missing_ok=True)

    def busy_elsewhere(self, key: str) -> bool:
        """Ролик сейчас собирает другая живая заявка (не наша и не протухшая)."""
        p = self._p(key)
        try:
            age = server_now(self.d) - p.stat().st_mtime
        except OSError:
            return False
        return key not in self.held and age <= self.stale

    def _beat(self) -> None:
        while True:
            time.sleep(BEAT)
            with self.lock:
                keys = list(self.held)
            for k in keys:
                try:                                       # запись меняет время файла по часам общей папки
                    with open(self._p(k), "r+", encoding="utf-8") as fh:
                        d = json.loads(fh.read() or "{}")
                        d["beat"] = time.time()
                        fh.seek(0)
                        fh.write(json.dumps(d))
                        fh.truncate()
                except (OSError, ValueError):
                    pass


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259                          # STILL_ACTIVE


@contextlib.contextmanager
def shared_lock(path: Path, poll: float = 0.05, timeout: float = 120.0):
    """Замок для всех процессов всех машин (блокировка первого байта файла path)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")
    t0 = time.time()
    try:
        while True:
            try:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.time() - t0 > timeout:
                    raise TimeoutError(f"замок {path} занят > {timeout:.0f} с")
                time.sleep(poll)
        try:
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        f.close()


def save_atomic(path: Path, write) -> None:
    """write(tmp_path) → переименование: соседняя машина не прочтёт недописанный файл."""
    path = Path(path)
    tmp = path.with_name(path.name + f".part_{HOST}_{os.getpid()}")
    write(tmp)
    os.replace(tmp, path)


# ---------------- загрузка машины для дашборда главного ПК ----------------
class _Pdh:
    """Счётчики Windows по английским именам (PdhAddEnglishCounter — работает и на русской Windows):
    загрузка блоков видеоядра (3D, Compute, VideoDecode/Encode — Quick Sync) и его общая память."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        self.pdh = ctypes.windll.pdh
        self._open()

    def _open(self):
        ct = self.ct
        self.q = ct.c_void_p()
        if self.pdh.PdhOpenQueryW(None, 0, ct.byref(self.q)):
            raise OSError("PdhOpenQuery")
        self.c = {}
        for k, path in (("eng", r"\GPU Engine(*)\Utilization Percentage"),
                        ("shared", r"\GPU Adapter Memory(*)\Shared Usage")):
            h = ct.c_void_p()
            if not self.pdh.PdhAddEnglishCounterW(self.q, ct.c_wchar_p(path), 0, ct.byref(h)):
                self.c[k] = h
        self.pdh.PdhCollectQueryData(self.q)
        self.t_open = time.time()

    def _array(self, h) -> list[tuple[str, float]]:
        ct = self.ct

        class V(ct.Structure):
            _fields_ = [("status", ct.c_ulong), ("v", ct.c_double)]

        class Item(ct.Structure):
            _fields_ = [("name", ct.c_wchar_p), ("val", V)]
        size, cnt = self.wt.DWORD(0), self.wt.DWORD(0)
        self.pdh.PdhGetFormattedCounterArrayW(h, 0x200, ct.byref(size), ct.byref(cnt), None)
        if not size.value:
            return []
        buf = (ct.c_byte * size.value)()
        if self.pdh.PdhGetFormattedCounterArrayW(h, 0x200, ct.byref(size), ct.byref(cnt), buf):
            return []
        arr = ct.cast(buf, ct.POINTER(Item))
        return [(arr[i].name, arr[i].val.v) for i in range(cnt.value) if arr[i].val.status in (0, 1)]

    def sample(self) -> dict:
        if time.time() - self.t_open > 30:                 # новые процессы — новые экземпляры счётчиков
            self.pdh.PdhCloseQuery(self.q)
            self._open()
            time.sleep(0.5)
        self.pdh.PdhCollectQueryData(self.q)
        out: dict = {}
        if "eng" in self.c:
            per: dict = {}
            for name, v in self._array(self.c["eng"]):     # pid_…_luid_…_phys_0_eng_3_engtype_VideoDecode
                m = name.split("_engtype_")
                if len(m) == 2:
                    luid = name.split("_luid_")[1].split("_phys")[0] if "_luid_" in name else ""
                    key = (luid, m[1].split("_")[0])
                    per[key] = per.get(key, 0.0) + v
            for (luid, eng), v in per.items():             # по видеоядру с наибольшей нагрузкой — как диспетчер задач
                k = {"3D": "g3d", "Compute": "gcomp", "VideoDecode": "vdec", "VideoEncode": "venc"}.get(eng)
                if k:
                    out[k] = round(max(out.get(k, 0.0), min(100.0, v)), 1)
        if "shared" in self.c:
            vals = [v for _, v in self._array(self.c["shared"])]
            if vals:
                out["gmem"] = round(max(vals) / 2 ** 30, 2)
        return out


def _cpu_name() -> str:
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
    except OSError:
        return ""


def _gpu_names() -> list[str]:
    import winreg
    names = []
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    for i in range(8):
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{base}\\{i:04d}")
            n = winreg.QueryValueEx(k, "DriverDesc")[0].strip()
            if n and "Basic" not in n and "Virtual" not in n and n not in names:
                names.append(n)
        except OSError:
            continue
    return names


_LOAD_STARTED: list = []


def start_load_reporter(every: float = 3.0) -> None:
    """Раз в every с: output/_work/_node_load/<МАШИНА>.json — процессор, память, видеоядро (3D/Compute и
    Quick Sync), общая память видеоядра. Дашборд главного ПК рисует по ним плитки этой машины."""
    if _LOAD_STARTED:
        return
    _LOAD_STARTED.append(1)

    def loop():
        try:
            import psutil
        except ImportError:
            psutil = None
        try:
            pdh = _Pdh()
        except Exception:  # noqa: BLE001
            pdh = None
        p = ROOT / "output" / "_work" / "_node_load" / f"{HOST}.json"
        try:
            gpus = _gpu_names()
        except OSError:
            gpus = []
        info = dict(host=HOST, cpu_name=_cpu_name(), gpu_name=", ".join(gpus), every=every)
        if psutil:
            psutil.cpu_percent(interval=None)
            info["ram_total"] = round(psutil.virtual_memory().total / 2 ** 30, 1)
        while True:
            time.sleep(every)
            s = dict(t=round(time.time(), 1))
            if psutil:
                vm = psutil.virtual_memory()
                s.update(cpu=psutil.cpu_percent(interval=None), ram=round((vm.total - vm.available) / 2 ** 30, 2))
            if pdh:
                try:
                    s.update(pdh.sample())
                except Exception:  # noqa: BLE001
                    pass
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_name(p.name + f".part_{os.getpid()}")
                tmp.write_text(json.dumps(dict(info, now=s), ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, p)
            except OSError:
                pass
    threading.Thread(target=loop, daemon=True).start()


class _Tee:
    def __init__(self, a, b):
        self.a, self.b = a, b

    def write(self, s):
        self.a.write(s)
        try:
            self.b.write(s)
            self.b.flush()
        except (OSError, ValueError):
            pass
        return len(s)

    def flush(self):
        self.a.flush()

    def __getattr__(self, k):
        return getattr(self.a, k)


def tee_remote_log(script: str) -> Path | None:
    """На ноутбуке: вывод сборщика ещё и в общую папку output/_work/_node_logs/<МАШИНА>_<скрипт>_<pid>.log —
    главный ПК видит, что там идёт."""
    import sys
    if not REMOTE or os.environ.get("FARM_NO_TEE") == "1":    # farm_worker сам пишет вывод в _node_logs
        return None
    d = ROOT / "output" / "_work" / "_node_logs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{HOST}_{Path(script).stem}_{os.getpid()}.log"
    fh = open(p, "a", encoding="utf-8")
    sys.stdout = _Tee(sys.stdout, fh)
    sys.stderr = _Tee(sys.stderr, fh)
    return p


def _stacks(every: float = 30.0) -> None:
    """Ноутбук: раз в every с — где стоит каждый поток (_node_logs/<МАШИНА>_stacks_<pid>.txt), чтобы с ПК было видно
    зависание без доступа к ноутбуку."""
    import sys
    import traceback
    p = ROOT / "output" / "_work" / "_node_logs" / f"{HOST}_stacks_{os.getpid()}.txt"
    while True:
        time.sleep(every)
        names = {t.ident: t.name for t in threading.enumerate()}
        out = [time.strftime("%H:%M:%S")]
        for tid, fr in sys._current_frames().items():
            out.append(f"--- {names.get(tid, tid)}")
            out += [ln.rstrip() for ln in traceback.format_stack(fr)[-6:]]
        try:
            p.write_text("\n".join(out), encoding="utf-8")
        except OSError:
            pass


class Progress:
    """Этап и счёт для дашборда (output/_work/_qa_progress); на ноутбуке файл с именем машины."""

    def __init__(self, label: str = ""):
        name = f"{os.getpid()}.json" if not REMOTE else f"{HOST}-{os.getpid()}.json"
        self.p = ROOT / "output" / "_work" / "_qa_progress" / name
        self.label = label
        self.st = dict(stage="", done=0, total=None)
        self.t0 = time.time()
        threading.Thread(target=self._beat, daemon=True).start()
        if REMOTE:
            start_load_reporter()                          # загрузка ноутбука — на дашборд главного ПК
            threading.Thread(target=_stacks, daemon=True).start()

    def __call__(self, stage: str, done: int = 0, total: int | None = None) -> None:
        self.st = dict(stage=stage, done=done, total=total)
        self._write()

    def _write(self) -> None:
        st = dict(self.st)
        if REMOTE:
            st.update(host=HOST, script=self.label, started=self.t0, beat=time.time())
            st["stage"] = f"[{HOST}] {st['stage']}"
        try:
            self.p.parent.mkdir(parents=True, exist_ok=True)
            self.p.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _beat(self) -> None:
        while True:
            time.sleep(20)
            self._write()

    def close(self) -> None:
        self.p.unlink(missing_ok=True)
