#!/usr/bin/env python3
"""
Drops band «трэш», YT +200 (реф youtube 8uV5pz9m4vo, партия output/drops_band_trash_final): всё как в build_drops_band_trash.py,
но первый кадр игры стоит ровно на дропе песни. Точки — map_drops_band_drops.py (скачок громкости и низа на сильной доле),
отобраны те, где перед дропом поёт голос. Вместо loudnorm — постоянное усиление на весь ролик, иначе дроп сглаживается.

  python build_drops_band_drop.py --test --out output/drops_band_drop_test     # по ролику на каждую точку каждой песни
  python build_drops_band_drop.py -n 200 --range 1-50 --out output/drops_band_trash_YT_200
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_drops_band_trash as TR  # noqa: E402

B = TR.B
B.PAIRS["MP2_Get_Out_Of_My_Head"] = "2 Get Out of My Head.mp3"       # в первых партиях этой песни не было
POINTS = {                                  # уточнено по 0,35-с окнам: момент наибольшего скачка всего сигнала и низа, затем пик атаки
    "MP1_Get_Back": [137.358, 168.664],
    "MP2_Get_Out_Of_My_Head": [92.746],
    "MP3_The_Best_Bad_Idea": [134.072, 53.923, 37.634],
    "MP4_Were_Not_Going_Home": [95.115, 129.956, 30.302, 49.650],
    "MP5_Your_Coat_On_The_Chair": [78.135, 86.326],
}
MANUAL = B.D / "music" / "_drops_manual.json"              # точки из тюнера (tuner_drops_band.py) важнее найденных автоматически
if MANUAL.exists():
    _saved = json.loads(MANUAL.read_text(encoding="utf-8"))
    POINTS = {g: sorted(p["t"] for p in _saved.get(g, []) if p["on"]) for g in POINTS}
    POINTS = {g: ts for g, ts in POINTS.items() if ts}
TARGET_DB = -15.5
SHORT = {"MP1_Get_Back": "get_back", "MP2_Get_Out_Of_My_Head": "get_out", "MP3_The_Best_Bad_Idea": "best_bad_idea",
         "MP4_Were_Not_Going_Home": "not_going_home", "MP5_Your_Coat_On_The_Chair": "your_coat"}


def link_screencast() -> None:
    dst = B.D / "screencasts" / "MP2_Get_Out_Of_My_Head.mp4"
    if not dst.exists():
        os.link(ROOT / "downloads" / "drops_beats" / "screencasts" / dst.name, dst)


def gain(track: Path, start: float) -> float:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-ss", f"{start:.3f}", "-t", "8", "-i", str(track), "-af", "volumedetect",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    return round(TARGET_DB - float(re.search(r"mean_volume: (-?[\d.]+) dB", err).group(1)), 2)


def render(i: int, r: dict, scene: str, out: Path, work: Path, t_band: float) -> dict:
    path, (lo, hi), hy, hook, top, bot = TR.SCENES[scene]
    B.HOOK, B.TOP, B.BOTTOM, B.HOOK_Y, B.CAP_GAP, B.STROKE = hook, top, bot, {path.name: hy}, 40, TR.STROKE
    B.T_BAND, B.T_GAME = t_band, round(8.0 - t_band, 3)
    r["clip"] = str(Path("..") / path.relative_to(TR.TB))
    B.AUDIO_GAIN = gain(B.D / "music" / B.PAIRS[r["game"]], r["track_t"])
    m = B.build(i, r, out, work)
    m.update(scene=scene, t_band=t_band, gain=B.AUDIO_GAIN)
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=200)
    ap.add_argument("--range", default="")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "drops_band_drop_test")
    ap.add_argument("--seed", type=int, default=73)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    link_screencast()
    names = list(TR.SCENES)
    clips = [TR.SCENES[s][0] for s in names]
    a.out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "output" / "_work" / f"drops_band_drop_{a.range or 'test'}"
    work.mkdir(parents=True, exist_ok=True)
    jobs = [(g, t) for g, ts in POINTS.items() for t in ts]
    n = len(jobs) if a.test else a.n
    rows = B.plan(n, clips, a.seed)
    rng = random.Random(a.seed)
    lo, hi = map(int, a.range.split("-")) if a.range else (1, n)
    man = []
    cursor = {g: 0 for g in POINTS}
    games = list(POINTS)
    for i, r in enumerate(rows, 1):
        scene = names[(i - 1) % len(names)]
        _, (a0, b0), *_ = TR.SCENES[scene]
        if a.test:
            g, t, t_band = *jobs[i - 1], 3.0
        else:
            g = games[((i - 1) // len(names)) % len(games)]
            t = POINTS[g][cursor[g] % len(POINTS[g])]
            cursor[g] += 1
            t_band = round(rng.uniform(2.85, 3.15) * 30) / 30                 # склейка строго на кадре, начало трека у роликов разное
        clip_t, speed = round(rng.uniform(a0, b0), 2), round(rng.uniform(0.98, 1.02), 3)
        game_t = round(rng.uniform(3.5, B.dur(B.D / "screencasts" / f"{g}.mp4") - 6.0), 2)
        if not lo <= i <= hi:
            continue
        r.update(game=g, track_t=round(t - t_band, 3), clip_t=clip_t, speed=speed, game_t=game_t)
        m = render(i, r, scene, a.out, work, t_band)
        m["drop_t"] = t
        if a.test:
            name = f"{SHORT[g]}_{t:.2f}_noid.mp4"
            (a.out / m["video"]).replace(a.out / name)
            m["video"] = name
        man.append(m)
        print(f"  {m['video']}  {SHORT[g]} {t}  {scene}", flush=True)
    (work / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"готово: {len(man)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
