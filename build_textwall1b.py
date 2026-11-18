#!/usr/bin/env python3
"""
Текстволл ID 1, вторая группа: 16 английских историй (textwall1b_texts.py, дословно, переносы по смыслу) в том же формате,
что build_textwall1.py: стена текста по центру поверх лица, клипы из нашей базы, музыка и длина — треки рефов FollowSpy.
2 версии на историю = 32: v1 — свой клип, v2 — другой клип той же группы, другой отрезок, зеркально, другой трек.
Рабочие истории от лица без пола (1, 5, 11) — парень, остальные — девушки.

  python build_textwall1b.py --out output/textwall1_group2_32
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_textwall1 as B  # noqa: E402
from textwall1b_texts import TEXTS  # noqa: E402

B.TEXTS = TEXTS
DL = ROOT / "downloads"
B.CLIP.update({"B8103": (DL / "gw_wall2/proxy/IMG_8103.mp4", ""), "B8104": (DL / "gw_wall2/proxy/IMG_8104.mp4", ""),
               "B8105": (DL / "gw_wall2/proxy/IMG_8105.mp4", "")})
USABLE = json.loads((DL / "followspy" / "usable_ranges.json").read_text(encoding="utf-8"))
GIRLS = ["B8107", "A5664", "B8103", "B8101", "A5665", "B8108", "A5663", "B8102", "A5668", "B8104", "A5669", "B8105", "A5670"]
GUYS = ["G2983", "G2982", "G2984"]
GUY_STORIES = (1, 5, 11)
TRACKS = ["tt_sofiia", "tt_milana", "tt_roxanne", "ig_DYBG", "tt_bridget"]


def window(clip: str) -> tuple[float, float]:
    if clip.startswith("G"):
        return 0.5, B.F.dur(B.CLIP[clip][0]) - 0.6
    return tuple(USABLE[f"IMG_{clip[1:]}"])


def plan() -> list[tuple]:
    rows, gi, ui = [], 0, 0
    for n in range(1, 17):
        if n in GUY_STORIES:
            c1, c2 = GUYS[ui], GUYS[(ui + 1) % len(GUYS)]
            ui += 1
        else:
            c1, c2 = GIRLS[gi], GIRLS[(gi + 5) % len(GIRLS)]
            gi += 1
        for k, (ver, clip, mirror) in enumerate((("v1", c1, 0), ("v2", c2, 1))):
            a, b = window(clip)
            order = TRACKS[(n + 2 * k) % len(TRACKS):] + TRACKS[:(n + 2 * k) % len(TRACKS)]
            ref = next(t for t in order if B.F.dur(B.F.REFS / f"{t}.mp4") <= b - a - 0.1)
            d = B.F.dur(B.F.REFS / f"{ref}.mp4")
            start = a if ver == "v1" else a + (b - a - d) * 0.85
            rows.append((n, ver, clip, round(start, 2), ref, mirror))
    return rows


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "textwall1_group2_32")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "output" / "_work" / "textwall1b"
    work.mkdir(parents=True, exist_ok=True)
    jobs = []
    for n, ver, clip, start, ref, mirror in plan():
        k = (n - 1) * 2 + (1 if ver == "v1" else 2)
        jobs.append((n, ver, clip, start, ref, mirror, a.out, work, f"{k:03d}_1"))
        print(f"{k:03d} story {n:2d} {ver} {clip} {start:5.2f} {ref} mirror={mirror}")
    with ThreadPoolExecutor(a.jobs) as ex:
        for dest in ex.map(lambda j: B.render(*j), jobs):
            print(" ", dest.name, flush=True)
    print(f"готово: {len(jobs)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
