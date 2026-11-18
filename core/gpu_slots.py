"""Общий лимит распаковки видео на видеокарте — для ВСЕХ сборок и всех чатов сразу.

Правило: декодируем на видеокарте по умолчанию (-hwaccel cuda или h264_cuvid). 13.11 юзер: «давай нагружать сильно
видюху, забей на лимит» → до 8 ffmpeg с CUDA одновременно (GPU_SLOTS в окружении меняет), но новый ffmpeg ждёт, пока
занято видеопамяти > 6 ГБ из 8 (старты — с паузой 1.5 с, чтобы замер успевал): синий экран 2026-11-06 был именно от переполнения (40 CUDA-декодеров 4K, VRAM 7.9/8 ГБ).
Слоты — файловые блокировки в output/_work/_gpu_slots, общие для всех процессов; при падении процесса Windows снимает
блокировку сама.

    from core.gpu_slots import gpu_slot
    with gpu_slot() as hw:                 # ждёт свободный слот; hw = ["-hwaccel", "cuda"]
        subprocess.run(["ffmpeg", *hw, "-i", src, ...])
    with gpu_slot(wait=False) as hw:       # без ожидания: hw = [] → этот ffmpeg распаковывает на процессоре
        ...
"""

from __future__ import annotations

import contextlib
import msvcrt
import os
import subprocess
import time
from pathlib import Path

SLOTS = int(os.environ.get("GPU_SLOTS", "8"))
VRAM_MAX_MB = int(os.environ.get("GPU_VRAM_MAX_MB", "5500"))   # + ~1.5 ГБ на сборку из 2560×1440 → потолок ~7.5 из 8
STAGGER = float(os.environ.get("GPU_STAGGER", "1.5"))   # с между стартами CUDA-ffmpeg (память занимается не сразу)
_vram = {"t": 0.0, "mb": 0}


def vram_used_mb() -> int:
    """Занято видеопамяти, МБ (nvidia-smi, кэш 1 с); при ошибке — 0 (не блокируем)."""
    if time.time() - _vram["t"] > 1.0:
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=5)
            _vram["mb"] = int(r.stdout.split()[0])
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            _vram["mb"] = 0
        _vram["t"] = time.time()
    return _vram["mb"]


DIR = Path(__file__).resolve().parent.parent / "output" / "_work" / "_gpu_slots"
HW = ["-hwaccel", "cuda"]


@contextlib.contextmanager
def gpu_slot(wait: bool = True, poll: float = 0.2):
    DIR.mkdir(parents=True, exist_ok=True)
    while True:
        if vram_used_mb() > VRAM_MAX_MB:                     # видеопамять почти полная — ждём, а не роняем драйвер
            if not wait:
                yield []
                return
            time.sleep(poll * 5)
            continue
        for k in range(SLOTS):
            f = open(DIR / f"slot_{k}.lock", "a+")
            f.seek(0)
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                f.close()
                continue
            last = DIR / "last_start"                          # пауза между стартами (общая для всех процессов)
            try:
                gap = time.time() - last.stat().st_mtime
            except OSError:
                gap = STAGGER
            if gap < STAGGER:
                time.sleep(STAGGER - gap)
            _vram["t"] = 0.0
            if vram_used_mb() > VRAM_MAX_MB:                 # за паузу память заняли — отдаём слот и ждём
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                f.close()
                break
            last.touch()
            try:
                yield list(HW)
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                f.close()
            return
        if not wait:
            yield []
            return
        time.sleep(poll)


def busy() -> int:
    """Сколько слотов занято сейчас (для дашборда/проверок)."""
    DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for k in range(SLOTS):
        with open(DIR / f"slot_{k}.lock", "a+") as f:
            f.seek(0)
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                n += 1
    return n
