#!/usr/bin/env python3
"""Проверка схожести по КАЖДОМУ кадру (30 к/с) всех пар партии + сравнение с прошлыми партиями (их кэш 6 и 3 к/с).
Отпечаток — core.uniq_fast.real_hash (полоса strip, dHash 16×16 + зеркало). Пара «узнаётся» на кадре, если у
другого ролика есть кадр ближе thr бит. Итог: худшая и средняя схожесть пар (доля кадров A, узнаваемых в B), число пар
с общими кадрами — при порогах 40 и 48.

  python check_uniq_allframes.py output/onestate_5_TT_200 output/onestate_5_YT_200 --strip 450 930 --refs-cache output/_work/onestate5/refs6.npz
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.uniq_fast import DEV, real_hash  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--strip", nargs=2, type=int, default=(450, 930))
    ap.add_argument("--refs-cache", nargs="*", default=[])
    ap.add_argument("--pairs-out", default=None, help="json: пары с общими кадрами (порог 40) и ролики, совпавшие с прошлыми")
    ap.add_argument("--hash-cache", default=None, help="готовые отпечатки каждого кадра: npz {путь: ((кадры, 2, 256), mtime)}")
    a = ap.parse_args()
    files = [f.resolve() for d in a.dirs for f in sorted(Path(d).glob("*.mp4"))]   # абсолютные: ключи кэша
    import json
    import os
    pf = ROOT / "output" / "_work" / "_qa_progress" / f"{os.getpid()}.json"      # дашборд localhost:8767

    def prog(stage, done, total):
        try:
            pf.parent.mkdir(parents=True, exist_ok=True)
            pf.write_text(json.dumps(dict(stage=stage, done=done, total=total), ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    hc = dict(np.load(a.hash_cache, allow_pickle=True)["d"].item()) if a.hash_cache and Path(a.hash_cache).exists() else {}

    def one(f):
        c = hc.get(str(f))
        if c is not None and c[1] == f.stat().st_mtime:
            return c[0][:, 0], c[0][:, 1]
        return real_hash(f, tuple(a.strip))
    R = []
    with ThreadPoolExecutor(8) as ex:
        for i, r in enumerate(ex.map(one, files), 1):
            R.append(r)
            if i % 5 == 0 or i == len(files):
                prog("отпечатки каждого кадра", i, len(files))
    prog("сравнение всех пар (видеокарта)", len(files), len(files))
    vid = np.concatenate([np.full(len(h), i) for i, (h, _) in enumerate(R)])
    A = torch.tensor(np.concatenate([h for h, _ in R]), dtype=torch.half, device=DEV)
    M = torch.tensor(np.concatenate([m for _, m in R]), dtype=torch.half, device=DEV)
    V = torch.tensor(vid, device=DEV)
    sa, sm = A.sum(1), M.sum(1)                               # half: расстояния — целые ≤ 512, хранятся точно
    n = len(files)
    print(f"роликов {n}, кадров {len(A)} (каждый кадр)", flush=True)
    near = torch.full((len(A),), 999.0, device=DEV, dtype=torch.half)     # ближайший кадр ДРУГОГО ролика
    near_v = torch.full((len(A),), -1, dtype=torch.long, device=DEV)
    RC, CC = 1024, 32768                                      # куски ~64 МБ: большие таблицы переполняют видеопамять
    for s in range(0, len(A), RC):
        q, qs, qv = A[s:s + RC], sa[s:s + RC, None], V[s:s + RC, None]
        for c in range(0, len(A), CC):
            for X, sx in ((A, sa), (M, sm)):
                d = torch.addmm(qs + sx[None, c:c + CC], q, X[c:c + CC].T, alpha=-2)
                d.masked_fill_(qv == V[None, c:c + CC], 999)
                mn, ix = d.min(1)
                upd = mn < near[s:s + RC]
                near[s:s + RC] = torch.where(upd, mn, near[s:s + RC])
                near_v[s:s + RC] = torch.where(upd, V[c + ix], near_v[s:s + RC])
        if (s // RC) % 10 == 0:
            prog("сравнение всех пар (видеокарта)", min(s + RC, len(A)), len(A))
    near = near.float()
    near, near_v = near.cpu().numpy(), near_v.cpu().numpy()
    out_pairs = {}
    for thr in (40, 48):
        hit = near <= thr
        pairs = {}
        for i in np.nonzero(hit)[0]:
            key = (min(vid[i], near_v[i]), max(vid[i], near_v[i]))
            pairs.setdefault(key, set()).add(i)
        per = np.bincount(vid, minlength=n)
        sims = [len(fr) / min(per[x], per[y]) for (x, y), fr in pairs.items()]
        worst = max(sims) if sims else 0.0
        mean = sum(sims) / (n * (n - 1) / 2)
        if thr == 40:
            out_pairs["pairs"] = [[str(files[x]), str(files[y]), len(fr)] for (x, y), fr in pairs.items()]
        print(f"порог {thr}: пар с общими кадрами {len(pairs)} из {n * (n - 1) // 2}; худшая пара {worst * 100:.2f} %, "
              f"средняя {mean * 100:.4f} %; кадров, узнаваемых в другом ролике: {int(hit.sum())}", flush=True)
    for rc in a.refs_cache:
        d = np.load(rc, allow_pickle=True)["d"].item()
        RA = torch.tensor(np.concatenate([v[0][:, 0] for v in d.values()]), dtype=torch.half, device=DEV)
        RM = torch.tensor(np.concatenate([v[0][:, 1] for v in d.values()]), dtype=torch.half, device=DEV)
        ra, rm = RA.sum(1), RM.sum(1)
        best = torch.full((len(A),), 999.0, device=DEV, dtype=torch.half)
        for s in range(0, len(A), RC):
            q, qs = A[s:s + RC], sa[s:s + RC, None]
            for c in range(0, len(RA), CC):
                for X, sx in ((RA, ra), (RM, rm)):
                    dd = torch.addmm(qs + sx[None, c:c + CC], q, X[c:c + CC].T, alpha=-2)
                    best[s:s + RC] = torch.minimum(best[s:s + RC], dd.min(1).values)
        prog("сравнение с прошлыми партиями", len(A), len(A))
        best = best.float()
        b = best.cpu().numpy()
        out_pairs["vs_refs"] = sorted(set(out_pairs.get("vs_refs", [])) | {str(files[v]) for v in vid[b <= 40]})
        print(f"против прошлых партий ({Path(rc).name}, {len(d)} роликов): ближайший кадр {b.min():.0f} бит; "
              f"кадров ≤ 40: {int((b <= 40).sum())}, ≤ 48: {int((b <= 48).sum())}", flush=True)
    if a.pairs_out:
        Path(a.pairs_out).write_text(json.dumps(out_pairs, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
