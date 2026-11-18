#!/usr/bin/env python3
"""
1332 — UNO! Mobile «pov: you're 25+ and literally everyone is getting married…»: 6 с = два кадра по 3 с из
исходников Katherine (downloads/dropbox_1zn15wxb/src): первый — IMG_6001 (девушка в кровати с собакой, неон) с
действием — потягивается, гладит собаку, поправляет волосы, двигает рукой (старты проверены глазами, ACTION);
второй — IMG_5993 (телефон с игрой над головой собаки, меню/загрузка вырезаны, телефон не опускается к тексту).
200 TikTok + 200 YouTube, все пары кадров разные (между папками тоже), лёгкий случайный зум.

Текст ТЗ дословно, TikTok-шрифт белый с обводкой (как 1303/1325), переносы по смыслу, нижняя половина кадра под
лицом девушки и под телефоном, внутри безопасной зоны 9:16. Музыка — TikTok «Blood» (та же, что m2 в 1285), с начала,
−14 LUFS.

  python build_1332_reels.py --test
  python build_1332_reels.py --count 200 --jobs 4
"""

from __future__ import annotations

import argparse
import json
import random
import re
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
ID = "1332"
SRC = B.SRC
D = ROOT / "downloads" / "1332"
SHOT = 3.0
MUSIC_SRC = ROOT / "downloads" / "1285" / "music" / "m2_blood_7542977955581004599.m4a"
MUSIC = D / "blood_6s_-14lufs.wav"
# IMG_6001: старты с действием в первую секунду (проверено по листу кадров), со сдвигами ±0.3 с
ACTION = [3.3, 38.4, 38.7, 39.0, 42.2, 42.5, 54.0, 54.3, 54.6, 69.2, 69.5, 71.8, 72.1, 81.9, 82.2, 117.3,
          117.6, 122.2, 122.5, 124.8, 125.1, 139.4, 139.7, 140.0]
# IMG_5993: игра; меню и загрузка вырезаны; низ экрана телефона не ниже PHONE_MAX (иначе текст на экране)
GAME = ("IMG_5993", (2.0, 148.0), [(82.0, 111.2)])
PHONE_MAX = 940
STEP = 0.5
NL = chr(10)
TEXT = NL.join([
    "pov: you're 25+ and literally everyone",
    "is getting married, having babies",
    "and buying houses",
    "meanwhile i got a dog",
    "and we open UNO! Mobile every night.",
    "lowkey the best decision ever 💅",
    "who else chose the dog fr??",
])
B.BAND = (990, 1534)                  # под лицом (IMG_6001) и под телефоном (IMG_5993), до низа безопасной зоны
B.PX_MAX, B.PX_MIN = 50, 32
ZOOM = (1.0, 1.05)
FOLDERS = ["TT", "YT"]


def music() -> Path:
    if MUSIC.exists():
        return MUSIC
    total = 2 * SHOT
    base = f"atrim=duration={total},asetpts=PTS-STARTPTS,afade=t=out:st={total - 0.3}:d=0.3"
    loud = "loudnorm=I=-14:TP=-1.5:LRA=11"
    log = subprocess.run([FF, "-hide_banner", "-i", str(MUSIC_SRC), "-af", f"{base},{loud}:print_format=json", "-f",
                          "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log).group(0))
    subprocess.run([FF, "-v", "error", "-y", "-i", str(MUSIC_SRC), "-af",
                    f"{base},{loud}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
                    f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample=48000",
                    "-ac", "2", "-c:a", "pcm_s16le", str(MUSIC)], check=True)
    return MUSIC


def game_windows() -> list[float]:
    """3-с окна IMG_5993 без меню/загрузки, где телефон не опускается к тексту (screen_motion.json из 1325)."""
    clip, (a, b), cut = GAME
    rows = json.loads((ROOT / "downloads" / "1325" / "screen_motion.json").read_text(encoding="utf-8"))[clip]
    m = np.array([[r[0], r[3] * H / 480] for r in rows])
    out = []
    for t in np.arange(a, b - SHOT + 1e-6, STEP):
        t = round(float(t), 2)
        if any(t < ce and t + SHOT > cs for cs, ce in cut):
            continue
        if m[(m[:, 0] >= t) & (m[:, 0] < t + SHOT), 1].max() <= PHONE_MAX:
            out.append(t)
    return out


def plan(count: int) -> list[dict]:
    """count роликов в каждую папку; пара (старт 6001, окно 5993) не повторяется нигде; окна — равномерно."""
    rng = random.Random(1332)
    games = game_windows()
    use: dict = {}
    seen: set = set()
    jobs = []
    for plat in FOLDERS:
        for n in range(count):
            for _ in range(500):
                a = min(ACTION, key=lambda t: use.get(("a", t), 0) + rng.random() * 0.9)
                b = min(games, key=lambda t: use.get(("g", t), 0) + rng.random() * 0.9)
                if (a, b) not in seen:
                    break
            seen.add((a, b))
            use[("a", a)] = use.get(("a", a), 0) + 1
            use[("g", b)] = use.get(("g", b), 0) + 1
            jobs.append({"plat": plat, "n": n + 1, "shots": [["IMG_6001", a], [GAME[0], b]],
                         "zoom": round(rng.uniform(*ZOOM), 3)})
    return jobs


def build(job: dict) -> str:
    out = Path(job["out"])
    dest = out / f"{job['plat'].lower()}_{job['n']:03d}_{ID}.mp4"
    inputs, parts = [], []
    zw, zh = round(W * job["zoom"] / 2) * 2, round(H * job["zoom"] / 2) * 2
    for k, (clip, t0) in enumerate(job["shots"]):
        inputs += ["-ss", f"{t0:.3f}", "-t", f"{SHOT + 0.2:.3f}", "-i", str(SRC / f"{clip}.MOV")]
        parts.append(f"[{k}:v]scale={zw}:{zh}:flags=lanczos,crop={W}:{H},fps={FPS},trim=duration={SHOT},"
                     f"setpts=PTS-STARTPTS,setsar=1[v{k}]")
    fc = ";".join(parts) + f";[v0][v1]concat=n=2:v=1:a=0[c];[c][2:v]overlay=0:0,format=yuv420p,{SET_SDR}[v]"
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-i", str(D / "_text.png"), "-i", str(music()),
                    "-filter_complex", fc, "-map", "[v]", "-map", "3:a", "-t", f"{2 * SHOT:.3f}",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19", *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(dest)], check=True)
    return dest.name


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=200, help="роликов в каждую папку (TT и YT)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--test", action="store_true", help="по 3 ролика на папку → output/1332_test")
    args = ap.parse_args()
    D.mkdir(parents=True, exist_ok=True)
    print(f"текст: {B.text_png(TEXT, D / '_text.png')} px", flush=True)
    music()
    print(f"старты 6001: {len(ACTION)}, окна 5993: {len(game_windows())}", flush=True)
    jobs = plan(args.count)
    if args.test:
        jobs = [j for j in jobs if j["n"] <= 3]
    for j in jobs:
        out = ROOT / "output" / ("1332_test" if args.test else f"{ID}_{j['plat']}_{args.count}")
        out.mkdir(parents=True, exist_ok=True)
        j["out"] = str(out)
    if not args.test:
        for plat in FOLDERS:
            part = [j for j in jobs if j["plat"] == plat]
            (Path(part[0]["out"]) / "manifest.json").write_text(json.dumps(part, indent=1), encoding="utf-8")
    todo = [j for j in jobs if not (Path(j["out"]) / f"{j['plat'].lower()}_{j['n']:03d}_{ID}.mp4").exists()]
    print(f"собрать {len(todo)} из {len(jobs)}", flush=True)
    with ProcessPoolExecutor(args.jobs) as ex:
        for k, name in enumerate(ex.map(build, todo), 1):
            print(f"[{k}/{len(todo)}] {name}", flush=True)
    print("готово")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
