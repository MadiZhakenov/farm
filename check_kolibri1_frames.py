#!/usr/bin/env python3
"""Колибри 1: покадровая проверка уже собранных роликов по их manifest.json. Для каждого куска игры берутся признаки каждого кадра
исходника (30 к/с, make_kolibri2_gamecheck.py): куски мира (зум < 1,3) должны быть видом мира с кнопкой BOOST, у любых кусков —
без всплесков интерфейса (Пункт управления, всплывающие окна, переходы) и без резких скачков картинки. Финалы и аудитор не трогаем
(финалы проверены покадрово отдельно). → список роликов с плохими кадрами.
  python check_kolibri1_frames.py output/kolibri_TT_100 output/kolibri_YT_100"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_calibri_reels as K  # noqa: E402
import make_kolibri2_gamecheck as G  # noqa: E402

FINAL_KEYS = {(f, s) for segs in list(K.FINALS.values()) + list(K.FINALS_SHORT.values()) for f, s, *_ in segs}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ft = {f: dict(np.load(G.WORK / f"gamecheck_{f[:12]}.npz")) for f in G.FILES}
    total_bad = 0
    for folder in sys.argv[1:]:
        man = json.loads((Path(folder) / "manifest.json").read_text(encoding="utf-8"))
        present = {p.name for p in Path(folder).glob("*.mp4")}
        bad_videos = []
        for r in man:
            name = next((n for n in present if f"_{r['i']:03d}_" in n), None)
            if not name:
                continue
            issues = []
            for k, p in enumerate(r["pieces"]):
                f = p["file"]
                if f not in ft or any(abs(p["start"] - s) < 1.0 and f == ff for ff, s in FINAL_KEYS):
                    continue
                a, b = int(p["start"] * G.FPS_A), int((p["start"] + p["src"]) * G.FPS_A) + 1
                x = {key: v[a:b] for key, v in ft[f].items()}
                world = p["z"] < 1.3
                bad = (x["dloc"] > G.DLOC_MAX) | (x["fdiff"] > G.FDIFF_MAX)
                if world:
                    bad |= x["boost"] < G.BOOST_MIN
                if bad.any():
                    t_bad = [round(p["start"] + j / G.FPS_A, 1) for j in np.nonzero(bad)[0]]
                    issues.append(f"кусок {k} {'мир' if world else 'панель'} {f[4:-4]} {p['start']}: {len(t_bad)} к. ({t_bad[0]}–{t_bad[-1]})")
            if issues:
                bad_videos.append((name, issues))
        total_bad += len(bad_videos)
        print(f"{folder}: роликов {len(present)}, с плохими кадрами {len(bad_videos)}")
        for name, iss in bad_videos:
            print("  ", name, "|", "; ".join(iss))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
