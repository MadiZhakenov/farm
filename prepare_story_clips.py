#!/usr/bin/env python3
"""
Фоновые клипы для текстовых историй Magic Sort (30 с, 1080×1920, SDR).

screen — запись экрана VCIY4029: только игровые куски (меню / «PERFECT» /
         реклама вырезаны, склейка встык), паузы без движения выброшены
         (mpdecimate), остальное ×1.5; экспозиция −0.45, контраст 1.3.
phone  — съёмка телефона в руке IMG_2225: те же окна, что раньше; экспозиция
         −0.75, контраст 1.3, скорость обычная.

Карты «где игра» — из сканов (scan_game / clf_cam): --screen-feats, --phone-wins.

  python prepare_story_clips.py --out output/magicsort_story_clips_v2
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.ugc_color import SDR_COLOR_ARGS, vf_scale_crop_fps_sdr  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
CLIP = 30.0
SCREEN = {"exposure": -0.45, "contrast": 1.3, "speed": 1.5, "src_fps": 60}
PHONE = {"exposure": -0.75, "contrast": 1.3}
DECIMATE = "mpdecimate=hi=64*16:lo=64*6:frac=0.33"


def grade(p: dict) -> str:
    return f"exposure=exposure={p['exposure']},eq=contrast={p['contrast']}"


def encode(src: Path, dest: Path, vf: str, ss: float | None = None, t: float | None = None) -> None:
    cmd = [FF, "-v", "error", "-y"]
    if ss is not None:
        cmd += ["-ss", f"{ss:.3f}"]
    if t is not None:
        cmd += ["-t", f"{t:.3f}"]
    cmd += ["-i", str(src), "-an", "-vf", vf, "-t", f"{CLIP:.3f}", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "18", *SDR_COLOR_ARGS, "-movflags", "+faststart", str(dest)]
    subprocess.run(cmd, stdin=subprocess.DEVNULL, check=True)


def screen_jobs(feats: np.ndarray, n: int, need_active: float, step: float = 0.5) -> list[list[tuple[float, float]]]:
    """n наборов игровых интервалов, в каждом ≥ need_active секунд с движением.
    Игра = фон поля, резко, с отступом 1.5 с от меню / «PERFECT» / рекламы."""
    t, navy, _pur, sharp, diff = feats[:, 0], feats[:, 1], feats[:, 2], feats[:, 3], feats[:, 4]
    game = navy >= 0.5
    near = np.zeros_like(game)
    for i in np.where(~game)[0]:
        near[max(0, i - 3): i + 4] = True
    ok = game & ~near & (sharp >= 1000)
    active = ok & (diff >= 0.3)
    act_idx = np.where(active)[0]
    need = int(round(need_active / step))
    starts = np.linspace(0, len(act_idx) - need - 1, n).astype(int)
    jobs = []
    for s0 in starts:
        i0, i1 = act_idx[s0], act_idx[min(len(act_idx) - 1, s0 + need)]
        seg, run = [], None
        for i in range(i0, i1 + 1):
            if ok[i] and run is None:
                run = t[i]
            if not ok[i] and run is not None:
                seg.append((run, t[i]))
                run = None
        if run is not None:
            seg.append((run, t[i1] + step))
        jobs.append([(a, b) for a, b in seg if b - a >= 1.0])
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen-src", type=Path, default=Path(r"C:\Users\user\Downloads\VCIY4029.MP4"))
    ap.add_argument("--phone-src", type=Path, default=ROOT / "downloads" / "IMG_2225.MOV")
    ap.add_argument("--screen-feats", type=Path, required=True, help="npz из scan_game (feats)")
    ap.add_argument("--phone-wins", type=Path, required=True, help="npy стартов окон съёмки")
    ap.add_argument("-n", type=int, default=50)
    ap.add_argument("--only", choices=("screen", "phone"))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    tasks = []
    if args.only != "phone":
        feats = np.load(args.screen_feats)["feats"]
        need = CLIP * SCREEN["speed"] * 1.35  # секунд с движением + запас
        for k, seg in enumerate(screen_jobs(feats, args.n, need), 1):
            sel = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in seg)
            span0, span1 = seg[0][0], seg[-1][1]
            vf = (f"select='{sel}',{DECIMATE},setpts=N/({SCREEN['src_fps'] * SCREEN['speed']}*TB),"
                  f"{grade(SCREEN)},{vf_scale_crop_fps_sdr(1080, 1920, 30)}")
            name = f"screen_{k:02d}_{int(span0 // 60):02d}m{int(span0 % 60):02d}s.mp4"
            # -ss до -i сдвигает время к 0 — интервалы пересчитываем от span0
            sel0 = "+".join(f"between(t,{a - span0:.2f},{b - span0:.2f})" for a, b in seg)
            vf = vf.replace(sel, sel0)
            tasks.append((args.screen_src, args.out / name, vf, span0, span1 - span0 + 1))
    if args.only != "screen":
        for k, t0 in enumerate(np.load(args.phone_wins), 1):
            name = f"phone_{k:02d}_{int(t0 // 60):02d}m{int(t0 % 60):02d}s.mp4"
            vf = f"{grade(PHONE)},{vf_scale_crop_fps_sdr(1080, 1920, 30)}"
            tasks.append((args.phone_src, args.out / name, vf, float(t0), CLIP + 1))

    def run(task):
        src, dest, vf, ss, t = task
        if not dest.exists():
            encode(src, dest, vf, ss, t)
        return dest

    with ThreadPoolExecutor(3) as ex:
        for i, d in enumerate(ex.map(run, tasks), 1):
            if i % 10 == 0 or i == len(tasks):
                print(f"[{i}/{len(tasks)}] {d.name}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
