#!/usr/bin/env python3
"""Отпечатки КАЖДОГО кадра (30 к/с, весь кадр, dHash 16×16 + зеркало) всех прошлых skinive-роликов (output/skinive*)
→ npz для check_uniq_allframes --refs-cache и приёмки skinive 10/11: {путь: (кадры×2×256 float16, mtime)}.
Дописывает только новые файлы.
  python hash_old_skinive.py [--out output/_work/skinive10/old30.npz] [--skip-prefix skinive10 skinive11]"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.uniq_fast import real_hash  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "_work" / "skinive10" / "old30.npz")
    ap.add_argument("--skip-prefix", nargs="*", default=["skinive10", "skinive11"])
    a = ap.parse_args()
    # и папки, переименованные юзером с ID впереди (17.11: 1542_skinive3_7s_TT_100)
    dirs = sorted(d for d in (ROOT / "output").glob("*skinive*")
                  if d.is_dir() and not any(d.name.split("_", 1)[-1].startswith(p) or d.name.startswith(p)
                                            for p in a.skip_prefix))
    files = [f.resolve() for d in dirs for f in sorted(d.glob("*.mp4"))]
    d = dict(np.load(a.out, allow_pickle=True)["d"].item()) if a.out.exists() else {}
    todo = [f for f in files if str(f) not in d or d[str(f)][1] != f.stat().st_mtime]
    print(f"папок {len(dirs)}, роликов {len(files)}, посчитать {len(todo)}", flush=True)

    def one(f: Path):
        h, m = real_hash(f, (0, 1920))
        return f, np.stack([h, m], 1).astype(np.float16), f.stat().st_mtime
    with ThreadPoolExecutor(8) as ex:
        for i, (f, hm, mt) in enumerate(ex.map(one, todo), 1):
            if not len(hm):
                print("  НЕ РАСПАКОВАЛСЯ", f, flush=True)
                continue
            d[str(f)] = (hm, mt)
            if i % 200 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
    d = {k: v for k, v in d.items() if Path(k) in set(files)}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(a.out, d=np.array(d, dtype=object))
    print(f"готово: {len(d)} роликов, кадров {sum(len(v[0]) for v in d.values())} → {a.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
