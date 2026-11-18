"""Проверка похожести роликов партии по парам (для «худшая пара ≈ 0–1 %», как Skinive / OneState).

Каждый кадр (fps к/с) → dHash 16×16 по выбранным полосам кадра (только геймплей: общий фон/подпись/карточку
не сравниваем), плюс зеркальный хэш. Ролик A «узнаётся» в B на кадре, если у B есть кадр (как есть или зеркально)
ближе thr бит из 256. sim(A,B) = max(доля кадров A, узнаваемых в B; и наоборот). Расстояния — на видеокарте (torch).
Декод готовых коротких роликов — процессором в потоках (так быстрее, правило MAIN).

    from core.uniq_check import similarity, bad_set
    pair, vs = similarity(files, refs=[], strips=[(540, 800), (1140, 1380)], fps=6, thr=40, cache=Path(...))
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import os

import numpy as np


def vhash(path: Path, strips: list[tuple[int, int]] | None, fps: float) -> np.ndarray:
    if strips:
        n = len(strips)
        fc = f"[0:v]fps={fps},split={n}" + "".join(f"[s{i}]" for i in range(n)) + ";"
        fc += ";".join(f"[s{i}]crop=iw:{b - a}:0:{a}[c{i}]" for i, (a, b) in enumerate(strips)) + ";"
        fc += "".join(f"[c{i}]" for i in range(n)) + (f"vstack=inputs={n}," if n > 1 else "") + "scale=17:16:flags=area,format=gray[o]"
        if n == 1:
            fc = fc.replace("[c0]scale", "[c0]null,scale").replace("[c0]null", "[c0]copy")
        args = ["-filter_complex", fc, "-map", "[o]"]
    else:
        args = ["-vf", f"fps={fps},scale=17:16:flags=area,format=gray"]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), *args, "-f", "rawvideo", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 16, 17).astype(np.int16)
    h = (fr[:, :, 1:] > fr[:, :, :-1]).reshape(len(fr), -1)
    m = (fr[:, :, ::-1][:, :, 1:] > fr[:, :, ::-1][:, :, :-1]).reshape(len(fr), -1)
    return np.stack([h, m], 1)


def hashes(files: list[Path], strips, fps: float, cache: Path | None) -> dict:
    data = dict(np.load(cache, allow_pickle=True)["d"].item()) if cache and cache.exists() else {}
    todo = [f for f in files if data.get(str(f), (None, 0))[1] != f.stat().st_mtime]
    with ThreadPoolExecutor(8) as ex:
        for f, h in zip(todo, ex.map(lambda f: vhash(f, strips, fps), todo)):
            data[str(f)] = (h, f.stat().st_mtime)
    if cache and todo:                     # пишем только новое и атомарно: два процесса читают один кэш одновременно
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_name(f"{cache.stem}.{os.getpid()}.tmp.npz")
        np.savez(tmp, d=np.array(data, dtype=object))
        os.replace(tmp, cache)
    return {str(f): data[str(f)][0] for f in files}


def similarity(own: list[Path], refs: list[Path] | None = None, strips=None, fps: float = 6, thr: int = 40,
               cache: Path | None = None) -> tuple[np.ndarray, np.ndarray]:
    import torch
    refs = refs or []
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    H = hashes(own + refs, strips, fps, cache)
    X = [H[str(f)] for f in own + refs]
    vid = np.concatenate([np.full(len(x), i) for i, x in enumerate(X)])
    A = torch.tensor(np.concatenate([x[:, 0] for x in X]), dtype=torch.float32, device=dev)
    M = torch.tensor(np.concatenate([x[:, 1] for x in X]), dtype=torch.float32, device=dev)
    vid_t = torch.tensor(vid, device=dev)
    nv, no = len(X), len(own)
    sa, sm = A.sum(1), M.sum(1)
    rows = torch.nonzero(vid_t < no).squeeze(1)
    hit = torch.zeros((len(rows), nv), device=dev)
    for c in range(0, len(rows), 1024):
        r = rows[c:c + 1024]
        d = torch.minimum(sa[r][:, None] + sa[None, :] - 2 * (A[r] @ A.T), sa[r][:, None] + sm[None, :] - 2 * (A[r] @ M.T))
        m = torch.full((len(r), nv), 1e9, device=dev)
        m.scatter_reduce_(1, vid_t[None, :].expand(len(r), -1), d, reduce="amin")
        hit[c:c + len(r)] = (m <= thr).float()
    own_vid = vid_t[rows]
    cnt = torch.bincount(own_vid, minlength=no).float()
    S = torch.zeros((no, nv), device=dev)
    S.index_add_(0, own_vid, hit)
    S = S / cnt[:, None]
    S[torch.arange(no), torch.arange(no)] = 0
    S = S.cpu().numpy()
    return np.maximum(S[:, :no], S[:, :no].T), S[:, no:]


def bad_set(pair: np.ndarray, vs: np.ndarray | None = None) -> list[int]:
    """Жадно — минимальный набор роликов, после пересборки которых общих кадров не останется."""
    E = {(int(i), int(j)) for i, j in zip(*np.nonzero(np.triu(pair > 0, 1)))}
    bad = {i for i in range(len(pair)) if vs is not None and vs.shape[1] and (vs[i] > 0).any()}
    E = {(i, j) for i, j in E if i not in bad and j not in bad}
    while E:
        deg: dict = {}
        for i, j in E:
            deg[i] = deg.get(i, 0) + 1
            deg[j] = deg.get(j, 0) + 1
        v = max(deg, key=deg.get)
        bad.add(v)
        E = {(i, j) for i, j in E if v not in (i, j)}
    return sorted(bad)
