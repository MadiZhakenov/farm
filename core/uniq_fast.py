"""Быстрая и строгая уникальность роликов «геймплей в полосе» (OneState и похожие форматы) — юзер 2026-11-16.

Отпечаток кадра — как core.uniq_check.vhash: полоса кадра (строки strip) → 17×16 средних (ffmpeg scale flags=area,
серый) → dHash 16×16 (клетка правее светлее?) = 256 бит, плюс зеркальный.

ПРОГНОЗ ДО СБОРКИ — тем же способом, а не «картинкой в миниатюре»: каждая из 17×16 клеток отпечатка = среднее
по своему прямоугольнику ИСХОДНИКА (roi_align на видеокарте по кадрам исходника 480×270), волны света — средним по
клетке. Все варианты всех роликов — одной пачкой на видеокарте (план 400 роликов — секунды, не минуты).

Bank — принятые отпечатки (half, обычные + зеркальные), расстояние до пачки кандидатов — одним умножением матриц.

    st = FrameStore(); st.load({"key": Path(...)})            # кадры исходников 480×270, серые
    F = Frames(...)                                           # описание кадров кандидатов (см. класс)
    H, M = predict(st, F)                                     # [кандидатов, кадров, 256] на видеокарте
    d = bank.min_dist(H)                                      # ближайший чужой кадр каждого кандидата, бит
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import os

import torch
from torchvision.ops import roi_align

DEV = os.environ.get("UF_DEV") or ("cuda" if torch.cuda.is_available() else "cpu")
# на процессоре half медленный/не везде есть — там float32 (расстояния те же: целые ≤ 512)
DT = torch.half if DEV == "cuda" else torch.float32
CW, CH = 480, 270                                       # кадры исходников для прогноза


class FrameStore:
    """Кадры исходников (серые, CW×CH) в обычной памяти; на видеокарту — только нужные для пачки."""

    def __init__(self, cw: int = CW, ch: int = CH):
        self.cw, self.ch = cw, ch
        self.parts: list[np.ndarray] = []
        self.off: dict[str, int] = {}                     # ключ → номер первого кадра в общем массиве
        self.n: dict[str, int] = {}
        self.size: dict[str, tuple[int, int]] = {}        # ключ → (ширина, высота) исходника
        self.all: np.ndarray | None = None

    def load(self, files: dict[str, Path], threads: int = 6) -> None:
        def one(kv):
            k, p = kv
            out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                  "stream=width,height", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
            sw, sh = (int(v) for v in out.stdout.strip().split(",")[:2])
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vf",
                                  f"scale={self.cw}:{self.ch}:flags=area,format=gray", "-f", "rawvideo", "-"],
                                 capture_output=True).stdout
            return k, (sw, sh), np.frombuffer(raw, np.uint8).reshape(-1, self.ch, self.cw)
        todo = [(k, p) for k, p in files.items() if k not in self.off]
        with ThreadPoolExecutor(threads) as ex:
            for k, size, a in ex.map(one, todo):
                self.off[k] = sum(len(x) for x in self.parts)
                self.n[k] = len(a)
                self.size[k] = size
                self.parts.append(a)
        self.all = np.concatenate(self.parts) if self.parts else None
        self._gpu = None

    def gpu(self) -> torch.Tensor:
        """Все кадры на видеокарте одним тензором half [N, 1, CH, CW] (~0.26 МБ на кадр) — без копирования на каждую пачку."""
        if self._gpu is None or len(self._gpu) != len(self.all):
            self._gpu = torch.from_numpy(self.all).to(DEV).to(DT)[:, None]
        return self._gpu

    def free(self) -> None:
        self._gpu = None
        torch.cuda.empty_cache()


@dataclass
class Frames:
    """Кадры пачки кандидатов (плоско, B = кандидатов × кадров, кадры кандидата подряд):
    idx  — номер кадра в FrameStore.all;
    box  — прямоугольник ИСХОДНИКА (пиксели исходника), который в ролике занимает полосу проверки: x0, y0, x1, y1;
    scale — пиксели исходника → пиксели FrameStore (CW / ширина исходника);
    a, c — волны света по клеткам [B, 16, 17]: клетка = клетка·a + c (a = 1 − альфа, c = 255·альфа для белого);
    per  — кадров на кандидата."""
    idx: np.ndarray
    box: np.ndarray
    scale: np.ndarray
    a: np.ndarray
    c: np.ndarray
    per: int


def strip_box(crop: tuple[float, float, float, float], b0: int, bh: int, strip: tuple[int, int]) -> tuple:
    """Обрезка исходника crop=(x, y, w, h) растянута на полосу ролика высотой bh с верхом b0 (во всю ширину кадра) →
    прямоугольник исходника, попадающий в строки strip ролика."""
    x, y, w, h = crop
    r0, r1 = (strip[0] - b0) / bh, (strip[1] - b0) / bh
    return x, y + r0 * h, x + w, y + r1 * h


def shade_cells(v_strip: np.ndarray, amp: float) -> tuple[np.ndarray, np.ndarray]:
    """Волны света (поле v на строках полосы проверки, любой масштаб) → a, c по клеткам 16×17 (среднее по клетке)."""
    t = torch.tensor(v_strip, dtype=torch.float32)[None, None]
    al = (t.abs() * amp)
    wht = (t < 0).float()
    a = torch.nn.functional.adaptive_avg_pool2d(1 - al, (16, 17))[0, 0].numpy()
    c = torch.nn.functional.adaptive_avg_pool2d(al * wht * 255.0, (16, 17))[0, 0].numpy()
    return a, c


def predict(st: FrameStore, F: Frames, chunk: int = 20000) -> tuple[torch.Tensor, torch.Tensor]:
    """Отпечатки кадров пачки: ([кандидатов, кадров, 256], зеркальные) — half на видеокарте."""
    B = len(F.idx)
    img = st.gpu()
    cells = torch.empty((B, 16, 17), device=DEV)
    gi = torch.tensor(F.idx, dtype=torch.long, device=DEV)
    bx = torch.tensor(F.box, dtype=torch.float32, device=DEV) * torch.tensor(F.scale, dtype=torch.float32, device=DEV)[:, None]
    # half точно хранит целые только до 2048 → кадры берём частями по 2048 с местными номерами
    for c0 in range(0, len(img), 2048):
        sel = torch.nonzero((gi >= c0) & (gi < c0 + 2048)).flatten()
        for s in range(0, len(sel), chunk):
            q = sel[s:s + chunk]
            boxes = torch.cat([(gi[q] - c0).float()[:, None], bx[q]], 1).to(img.dtype)
            cells[q] = roi_align(img[c0:c0 + 2048], boxes, (16, 17), spatial_scale=1.0, sampling_ratio=-1,
                                 aligned=True)[:, 0].float()
    cells = cells * torch.tensor(F.a, device=DEV) + torch.tensor(F.c, device=DEV)
    h = (cells[:, :, 1:] > cells[:, :, :-1]).reshape(B, 256)
    fl = cells.flip(2)
    m = (fl[:, :, 1:] > fl[:, :, :-1]).reshape(B, 256)
    n = B // F.per
    return h.to(DT).reshape(n, F.per, 256), m.to(DT).reshape(n, F.per, 256)


class Bank:
    """Принятые отпечатки (half на видеокарте), обычные + зеркальные. Добавления копятся и сливаются разом."""

    def __init__(self):
        self.A = torch.zeros((0, 256), dtype=DT, device=DEV)
        self.M = torch.zeros((0, 256), dtype=DT, device=DEV)
        self.pa: list = []
        self.pm: list = []
        self.sa = self.sm = None

    def add(self, h, m) -> None:
        self.pa.append(torch.as_tensor(np.asarray(h, np.float16) if not torch.is_tensor(h) else h).to(DEV).to(DT).reshape(-1, 256))
        self.pm.append(torch.as_tensor(np.asarray(m, np.float16) if not torch.is_tensor(m) else m).to(DEV).to(DT).reshape(-1, 256))

    def _flush(self) -> None:
        if self.pa:
            self.A = torch.cat([self.A] + self.pa)
            self.M = torch.cat([self.M] + self.pm)
            self.pa, self.pm = [], []
        self.sa = self.A.float().sum(1)
        self.sm = self.M.float().sum(1)

    def __len__(self) -> int:
        return len(self.A) + sum(len(x) for x in self.pa)

    def copy(self) -> "Bank":
        self._flush()
        b = Bank()
        b.A, b.M, b.sa, b.sm = self.A.clone(), self.M.clone(), self.sa, self.sm
        return b

    def min_dist(self, H: torch.Tensor, chunk: int = 1024, bank_chunk: int = 32768) -> torch.Tensor:
        """H [кандидатов, кадров, 256] → ближайший чужой кадр каждого кандидата (бит).
        Всё в half (расстояния — целые ≤ 512, half хранит их точно), куски ≤ 1024×32768 (~64 МБ): большие временные
        таблицы переполняют видеопамять, Windows гонит её через обычную память — расчёт ползёт (замер 16.11)."""
        if self.pa or self.sa is None:
            self._flush()
        n, per = H.shape[:2]
        Hf = H.reshape(-1, 256).to(DEV).to(DT)
        best = torch.full((len(Hf),), 256.0, device=DEV, dtype=DT)
        if len(self.A):
            hs = Hf.sum(1)
            sa, sm = self.sa.to(DT), self.sm.to(DT)
            for s in range(0, len(Hf), chunk):
                q, qs = Hf[s:s + chunk], hs[s:s + chunk, None]
                for b in range(0, len(self.A), bank_chunk):
                    for X, sx in ((self.A, sa), (self.M, sm)):
                        d = torch.addmm(qs + sx[None, b:b + bank_chunk], q, X[b:b + bank_chunk].T, alpha=-2)
                        best[s:s + chunk] = torch.minimum(best[s:s + chunk], d.min(1).values)
        return best.float().reshape(n, per).min(1).values


_HWDEC = __import__("threading").BoundedSemaphore(max(1, int(os.environ.get("UF_HWDEC", "0") or 0)))
_HWDEC_ON = int(os.environ.get("UF_HWDEC", "0") or 0) > 0


def real_hash(path: Path, strip: tuple[int, int], fps: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Отпечатки готового ролика (как core.uniq_check.vhash; fps=None — КАЖДЫЙ кадр).
    UF_HWDEC=N — распаковка видеодекодером (N одновременно; h264 распаковывается побитно так же, кадры — в память,
    уменьшение — процессором), процессор свободен для сборки (юзер 17.11: «чтоб видюха рил нагружалась»)."""
    vf = f"crop=iw:{strip[1] - strip[0]}:0:{strip[0]},scale=17:16:flags=area,format=gray"
    if fps:
        vf = f"fps={fps}," + vf
    raw = b""
    if _HWDEC_ON and _HWDEC.acquire(blocking=False):
        try:
            raw = subprocess.run(["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-i", str(path), "-vf", vf, "-f", "rawvideo",
                                  "-"], capture_output=True).stdout
        finally:
            _HWDEC.release()
    for attempt in range(3):                              # 17.11: разовый сбой распаковки (пусто) ронял всю партию
        if raw:
            break
        if attempt:
            __import__("time").sleep(1.0 * attempt)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", vf, "-f", "rawvideo", "-"],
                             capture_output=True).stdout
    if not raw:
        raise RuntimeError(f"{path}: не распаковался (3 попытки)")
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 16, 17).astype(np.int16)
    h = (fr[:, :, 1:] > fr[:, :, :-1]).reshape(len(fr), -1)
    m = (fr[:, :, ::-1][:, :, 1:] > fr[:, :, ::-1][:, :, :-1]).reshape(len(fr), -1)
    return h.astype(np.float16), m.astype(np.float16)
