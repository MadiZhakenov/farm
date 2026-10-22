#!/usr/bin/env python3
"""
1325 — UNO! Mobile «pov: my dog couldn't fall asleep last night 😭»: 6 с = два кадра по 3 с из исходников
Katherine (downloads/dropbox_1zn15wxb/src): IMG_5992 и IMG_5993 — телефон с игрой над головой собаки, по одному
куску из каждого, порядок любой. Первый кадр начинается с движения на экране телефона (ход картой, вихрь, раздача):
окна, где в первую секунду содержимое экрана меняется сильнее всего (downloads/1325/screen_motion.json — экран
трекается по цвету, сравниваются кропы экрана). Меню и загрузочные экраны (красный логотип UNO) вырезаны.

Текст ТЗ дословно, текстволлом посередине — белый TikTok-шрифт с обводкой (как 1303), переносы по смыслу,
в полосе под телефоном (экран не закрываем), внутри безопасной рамки 9:16. Без музыки: в исходниках звука нет —
тихая дорожка.

  python build_1325_reels.py --test
  python build_1325_reels.py --count 100 --jobs 4
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1303_reels as B  # noqa: E402  (text_png — белый TikTok-текст с обводкой, «UNO! Mobile» не рвётся)
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF, W, H, FPS = B.FF, B.W, B.H, B.FPS
ID = "1325"
SRC = B.SRC
D = ROOT / "downloads" / "1325"
SHOT = 3.0
# клип: рабочая часть, вырезать (меню + загрузка)
CLIPS = {"IMG_5992": ((2.0, 178.0), [(82.0, 114.6)]), "IMG_5993": ((2.0, 148.0), [(82.0, 111.2)])}
NL = chr(10)
TEXT = NL.join([
    "pov: my dog couldn't fall asleep last night 😭",
    "he followed me from room to room",
    "and just stared at me",
    "like i owed him something.",
    "so i sat down, opened UNO! Mobile",
    "and played a few rounds.",
    "he got quiet, put his head on my knee",
    "and watched the screen",
    "like he knew every rule.",
    "somewhere around my last card",
    "he was finally asleep.",
    "now i can't play without him next to me 🥹",
    "does your pet watch you play too? 👇",
])
B.BAND = (920, 1534)                  # под телефоном, до низа безопасной зоны
PHONE_MAX = 900                       # окна, где низ экрана телефона ниже этой линии (px из 1920), не берём
B.PX_MAX, B.PX_MIN = 46, 28
# первый кадр — раздача карт в начале партии (карты разлетаются игрокам; пользователь: «в 006 самый динамичный»):
# по 2 раздачи в клипе (начало файла и новая партия), старт за ~0.2 с до вылета карт и вариант на 0.3 с позже
DYN_STARTS = {"IMG_5992": [3.8, 4.0, 4.3, 118.7, 118.9, 119.2], "IMG_5993": [1.2, 1.4, 1.7, 116.1, 116.3, 116.6]}
ZOOM = (1.0, 1.06)                    # лёгкий случайный зум кадра (уникальность при повторе раздач)
STEP = 0.5


def screen_motion() -> dict[str, np.ndarray]:
    """Движение на экране по времени (10 к/с): [t, score]."""
    data = json.loads((D / "screen_motion.json").read_text(encoding="utf-8"))
    return {c: np.array([[r[0], r[1], r[3] * H / 480] for r in rows]) for c, rows in data.items()}


def windows() -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """Все 3-с окна игры по клипам и динамичные старты (DYN_STARTS, если окно проходит фильтры)."""
    mot = screen_motion()
    every, dyn = {}, {}
    for clip, ((a, b), cut) in CLIPS.items():
        ts = np.arange(a, b - SHOT + 1e-6, STEP)
        ts = [round(float(t), 2) for t in ts if not any(t < ce and t + SHOT > cs for cs, ce in cut)]
        m = mot[clip]
        ts = [t for t in ts if m[(m[:, 0] >= t) & (m[:, 0] < t + SHOT), 2].max() <= PHONE_MAX]   # текст не на экране
        every[clip] = ts
        dyn[clip] = DYN_STARTS[clip]
        low = [t for t in dyn[clip] if m[(m[:, 0] >= t) & (m[:, 0] < t + SHOT), 2].max() > PHONE_MAX]
        if low:
            print(f"  ! {clip}: на стартах {low} телефон ниже линии текста")
    return every, dyn


def plan(count: int) -> list[dict]:
    """Кадр 1 — динамичный старт из одного клипа, кадр 2 — любое окно другого; клипы первым чередуем;
    пары не повторяются, окна используются равномерно, соседние старты одного клипа ≥ 1.5 с врозь."""
    rng = random.Random(1325)
    every, dyn = windows()
    use: dict[tuple[str, float], int] = {}
    seen: set = set()
    jobs = []
    clips = list(CLIPS)
    for n in range(count):
        first = clips[n % 2]
        second = clips[1 - n % 2]
        for _try in range(400):
            a = min(dyn[first], key=lambda t: use.get((first, t), 0) + rng.random() * 0.9)
            b = min(every[second], key=lambda t: use.get((second, t), 0) + rng.random() * 0.9)
            key = ((first, a), (second, b))
            if key not in seen:
                break
        seen.add(key)
        for k in key:
            use[k] = use.get(k, 0) + 1
        jobs.append({"n": n + 1, "shots": [list(key[0]), list(key[1])], "zoom": round(rng.uniform(*ZOOM), 3)})
    return jobs


def build(job: dict) -> str:
    out = Path(job["out"])
    dest = out / f"{job['n']:03d}_{ID}.mp4"
    png = D / "_text.png"
    inputs, parts = [], []
    for k, (clip, t0) in enumerate(job["shots"]):
        inputs += ["-ss", f"{t0:.3f}", "-t", f"{SHOT + 0.2:.3f}", "-i", str(SRC / f"{clip}.MOV")]
        zw, zh = round(W * job["zoom"] / 2) * 2, round(H * job["zoom"] / 2) * 2
        parts.append(f"[{k}:v]scale={zw}:{zh}:flags=lanczos,crop={W}:{H},fps={FPS},trim=duration={SHOT},"
                     f"setpts=PTS-STARTPTS,setsar=1[v{k}]")
    fc = (";".join(parts) + f";[v0][v1]concat=n=2:v=1:a=0[c];[c][2:v]overlay=0:0,format=yuv420p,{SET_SDR}[v];"
          f"anullsrc=r=48000:cl=stereo,atrim=duration={2 * SHOT}[a]")
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-i", str(png), "-filter_complex", fc, "-map", "[v]",
                    "-map", "[a]", "-t", f"{2 * SHOT:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dest)], check=True)
    return dest.name


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--test", action="store_true", help="6 роликов → output/1325_test")
    ap.add_argument("--out", default=None, help="папка в output/")
    args = ap.parse_args()
    D.mkdir(parents=True, exist_ok=True)
    print(f"текст: {B.text_png(TEXT, D / '_text.png')} px", flush=True)
    every, dyn = windows()
    print("окон:", {c: (len(every[c]), len(dyn[c])) for c in CLIPS}, flush=True)
    jobs = plan(6 if args.test else args.count)
    out = ROOT / "output" / (args.out or (f"{ID}_test" if args.test else f"{ID}_{args.count}"))
    out.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        j["out"] = str(out)
    (out / "manifest.json").write_text(json.dumps(jobs, indent=1), encoding="utf-8")
    todo = [j for j in jobs if not (out / f"{j['n']:03d}_{ID}.mp4").exists()]
    print(f"собрать {len(todo)} из {len(jobs)}", flush=True)
    with ProcessPoolExecutor(args.jobs) as ex:
        for k, name in enumerate(ex.map(build, todo), 1):
            print(f"[{k}/{len(todo)}] {name}", flush=True)
    print("готово →", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
