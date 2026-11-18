"""Партия нарезок из длинных исходников (Матрёшка, Vibe City): кандидаты собираются в пуле потоков, каждый готовый ролик
сразу проверяется (сверка с исходником делает сам сборщик проекта), отпечатки каждого кадра (17×16, как
core.uniq_fast.real_hash по всему кадру) сравниваются с принятыми — приём, только если общих кадров ≤ max_new в ОБЕ стороны
(17.11 skinive: в одну сторону пропускало пары 3–8 кадров); с прошлыми партиями — кадры нового ролика ≤ max_old.

  run(slots, make, build, jobs=6)
    slots — [(ключ, путь готового файла)]; make(rng, ключ) → кандидат; build(кандидат, tmp.mp4, keep) → (ok, причина, h)
    h — отпечатки ±1 [кадры×2, 256] (прямые, затем зеркальные), см. hash_of.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
DEV = "cuda" if torch.cuda.is_available() else "cpu"
DT = torch.half if DEV == "cuda" else torch.float32
THR = 40


def decode(path: Path, band: tuple[int, int], w: int = 1080, q: int = 8,
           size: tuple[int, int] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Одна распаковка ролика: полоса band (y0, y1) серым в 1/q (или size) и кадры 17×16 для отпечатков."""
    y0, y1 = band
    bw, bh = size or (w // q, (y1 - y0) // q)
    with __import__("tempfile").TemporaryDirectory() as td:
        g, h = Path(td) / "g.raw", Path(td) / "h.raw"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-threads", "4", "-i", str(path), "-filter_complex",
                        f"[0:v]split=2[a][b];[a]crop={w}:{y1 - y0}:0:{y0},scale={bw}:{bh}:flags=area,format=gray[g];"
                        f"[b]scale=17:16:flags=area,format=gray[h]",
                        "-map", "[g]", "-f", "rawvideo", str(g), "-map", "[h]", "-f", "rawvideo", str(h)], capture_output=True)
        G_ = np.fromfile(g, np.uint8).reshape(-1, bh, bw).astype(np.float32)
        H_ = np.fromfile(h, np.uint8).reshape(-1, 16, 17).astype(np.int16)
    return G_, H_


def hash_of(H_: np.ndarray) -> np.ndarray:
    """±1 [кадры×2, 256]: прямые, затем зеркальные (как real_hash)."""
    h = (H_[:, :, 1:] > H_[:, :, :-1]).reshape(len(H_), -1)
    m = (H_[:, :, ::-1][:, :, 1:] > H_[:, :, ::-1][:, :, :-1]).reshape(len(H_), -1)
    return np.concatenate([h, m]).astype(np.float32) * 2 - 1


class Bank:
    """Отпечатки принятых роликов на видеокарте (half): прямые и зеркальные кадры."""

    def __init__(self) -> None:
        self.t = torch.zeros((0, 256), dtype=DT, device=DEV)

    def add(self, h: np.ndarray) -> None:
        self.t = torch.cat([self.t, torch.from_numpy(np.asarray(h, np.float32)).to(DEV).to(DT)])

    def near(self, h: np.ndarray, both: bool = True, thr: int = THR) -> int:
        """Сколько кадров кандидата близко к банку; both — и сколько кадров банка близко к кандидату (берём больше)."""
        if not len(self.t):
            return 0
        q = torch.from_numpy(np.asarray(h[: len(h) // 2], np.float32)).to(DEV).to(DT)
        fwd = torch.zeros(len(q), dtype=torch.bool, device=DEV)
        rev = 0
        with torch.no_grad():
            for i in range(0, len(self.t), 131072):
                m = (256 - q @ self.t[i:i + 131072].T) / 2 <= thr
                fwd |= m.any(1)
                if both:
                    rev += int(m.any(0).sum())
        return max(int(fwd.sum()), rev) if both else int(fwd.sum())


def run(slots: list, make, build, jobs: int = 6, max_new: int = 2, old: Bank | None = None, max_old: int = 2,
        seed: int = 0, work: Path | None = None, label: str = "партия", log=print) -> int:
    """Главный цикл: держит jobs кандидатов в работе, принимает по одному (банк растёт сразу), брак/похожие — заново."""
    work = work or (ROOT / "output" / "_work" / "clip_batch")
    cand = work / "cand"
    cand.mkdir(parents=True, exist_ok=True)
    hc = work / "h30"
    hc.mkdir(parents=True, exist_ok=True)
    bank = Bank()
    todo = []
    for key, dest in slots:
        dest = Path(dest)
        if dest.exists() and (hc / f"{dest.name}.npy").exists():
            bank.add(np.unpackbits(np.load(hc / f"{dest.name}.npy"), axis=1)[:, :256].astype(np.float32) * 2 - 1)
        else:
            todo.append((key, dest))
    done, total = len(slots) - len(todo), len(slots)
    rng = random.Random(seed + done * 7919 + int(time.time()))
    prog = ROOT / "output" / "_work" / "_qa_progress" / f"{os.getpid()}.json"
    prog.parent.mkdir(parents=True, exist_ok=True)

    def tick(stage: str) -> None:
        try:
            prog.write_text(json.dumps(dict(stage=stage, done=done, total=total), ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    log(f"{label}: готовых {done}, собрать {len(todo)}")
    tried = rej_b = rej_u = 0
    t_start = time.time()

    def one(key, k):
        c = make(rng, key)
        keep = cand / f"c{k:05d}"
        if keep.exists():
            shutil.rmtree(keep)
        keep.mkdir(parents=True)
        tmp = keep.with_suffix(".mp4")
        try:
            ok, why, h = build(c, tmp, keep)
        except Exception as e:                                # noqa: BLE001
            ok, why, h = False, f"ошибка: {str(e)[-300:]}", None
        finally:
            shutil.rmtree(keep, ignore_errors=True)
        return key, tmp, ok, why, h
    queue = list(todo)
    live = {}
    with ThreadPoolExecutor(jobs) as ex:
        while queue or live:
            while queue and len(live) < jobs:
                key, dest = queue.pop(0)
                tried += 1
                live[ex.submit(one, key, tried)] = (key, dest)
            fin, _ = wait(list(live), timeout=2.0, return_when=FIRST_COMPLETED)
            for fu in fin:
                key, dest = live.pop(fu)
                _, tmp, ok, why, h = fu.result()
                if not ok:
                    rej_b += 1
                    log(f"  брак {tmp.name} ({key}): {why}")
                    tmp.unlink(missing_ok=True)
                    tmp.with_suffix(".json").unlink(missing_ok=True)
                    queue.insert(0, (key, dest))
                    continue
                nn = bank.near(h, both=True)
                no = old.near(h, both=False) if old is not None and nn <= max_new else 0
                if nn > max_new or no > max_old:
                    rej_u += 1
                    log(f"  похож {tmp.name} ({key}): кадров рядом с новыми {nn}, с прошлыми {no}")
                    tmp.unlink(missing_ok=True)
                    tmp.with_suffix(".json").unlink(missing_ok=True)
                    queue.insert(0, (key, dest))
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp.replace(dest)
                side = tmp.with_suffix(".json")                  # план варианта (для досборки звука утром)
                if side.exists():
                    (work / "meta").mkdir(exist_ok=True)
                    side.replace(work / "meta" / f"{dest.name}.json")
                np.save(hc / f"{dest.name}.npy", np.packbits(h > 0, axis=1))
                bank.add(h)
                done += 1
                tick(f"{label}: сборка + проверка каждого кадра")
                if done % 10 == 0 or not queue and not live:
                    rate = (done - (total - len(todo))) / max(1e-6, (time.time() - t_start) / 60)
                    log(f"  ✓ {done}/{total} (кандидатов {tried}, похожих {rej_u}, брак {rej_b}; {rate:.1f}/мин)")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    log(f"ИТОГ {label}: {done}/{total}; собрано {tried}, похожих {rej_u}, брак {rej_b}")
    prog.unlink(missing_ok=True)
    return done
