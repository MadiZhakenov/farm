#!/usr/bin/env python3
"""
1330 — OneState «DLSS off / DLSS 5 on»: 300 YouTube + 300 TikTok, 9:16, до 9 с. Исходники — 12 готовых роликов
клиента (Drive 13Ol4lWMBNZbhSud29nkqh2kSN73r6h2j → downloads/1330/src, 1080×1920, 24/25 к/с, без звука): лого OneState
и промокод STATE9CNL уже вшиты сверху, внизу плашка «DLSS Off» / «DLSS 5 On» + «UPDATE 1.3». Каждый исходник —
3–6 пар «off → шторка → on» (разметка downloads/1330/struct.json, границы пар — склейки, уточнены по кадрам).
Ролик = 2–3 пары из РАЗНЫХ исходников подряд, 6–9 с; наборы пар не повторяются ни в одной из 600.

Текст — одна из 4 фраз ТЗ дословно, TikTok-шрифт белый с обводкой, переносы по смыслу, посередине (между промокодом
и плашкой DLSS), внутри безопасной зоны 9:16; фразы поровну. Музыка — один из 2 звуков TikTok (поровну), с первого
звука (тишина в начале срезана), −14 LUFS, затухание 0.3 с.

  python build_1330_reels.py --test
  python build_1330_reels.py --count 300 --jobs 4
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
import build_1303_reels as T  # noqa: E402  (text_png — белый TikTok-текст с обводкой в полосе BAND)
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = T.FF
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
ID = "1330"
W, H, FPS = 1080, 1920, 25
D = ROOT / "downloads" / "1330"
SRC = D / "src"
MAX_LEN, MIN_LEN = 9.0, 6.0
NL = chr(10)
TEXTS = [
    NL.join(["dlss off / dlss 5 on 🔁", "same phone btw", "till the end"]),
    NL.join(["dlss off / dlss 5 on 🔁", "my phone doesn't even have dlss", "so why does it look like this 😭"]),
    NL.join(["dlss off vs dlss 5 on,", "which one would you pick?", "same phone btw", "till the end", "👇"]),
    NL.join(["is it dlss", "or is it just the 1.3 update?? 💀", "till the end"]),
]
T.BAND = (560, 1360)                                  # между промокодом (низ ~420) и плашкой DLSS (верх ~1395)
T.PX_MAX, T.PX_MIN = 64, 36
MUSIC = [D / "music" / "m1_fleydan_7697990020683877138.mp3", D / "music" / "m2_nyxae_7680271803985464081.mp3"]
FOLDERS = ["TT", "YT"]


def src_file(key: str) -> Path:
    return next(SRC.glob(f"UGC_Ninja_OneState5.1_DLSS_{key}_*.mp4"))


def refine_cut(path: Path, t: float) -> float:
    """Точная склейка у t (±0.2 с): кадр с наибольшей разницей с предыдущим, время в секундах исходника."""
    fps = eval(subprocess.run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                               "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip())
    t0 = max(0.0, t - 0.25)
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{t0:.3f}", "-i", str(path), "-t", "0.5", "-vf",
                          "scale=54:96,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.uint8).reshape(-1, 96 * 54).astype(np.float32)
    if len(a) < 2:
        return t
    d = np.abs(np.diff(a, axis=0)).mean(1)
    k = int(np.argmax(d)) + 1
    return round(round((t0 + k / fps) * fps) / fps, 4)


def pairs() -> list[dict]:
    """Пары «off → on» из разметки: от начала off до следующего off (или конца исходника)."""
    cache = D / "pairs.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    st = json.loads((D / "struct.json").read_text(encoding="utf-8"))
    out = []
    for key, v in st.items():
        key = key.strip()
        path = src_file(key)
        dur = float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                   capture_output=True, text=True).stdout)
        offs = [r[1] for r in v["runs"] if r[0] == "off"]
        bounds = [0.0] + [refine_cut(path, t) for t in offs[1:]] + [dur - 0.04]
        for a, b in zip(bounds[:-1], bounds[1:]):
            out.append({"src": key, "a": round(a, 4), "b": round(b, 4), "dur": round(b - a, 4)})
    cache.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def music_prep() -> list[tuple[Path, float]]:
    """Трек −14 LUFS целиком + начало первого звука (тишина в начале срезается)."""
    res = []
    for m in MUSIC:
        norm = m.with_name(m.stem + "_-14lufs.wav")
        if not norm.exists():
            log = subprocess.run([FF, "-hide_banner", "-i", str(m), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                                  "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8",
                                 errors="replace").stderr
            j = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log).group(0))
            subprocess.run([FF, "-v", "error", "-y", "-i", str(m), "-af",
                            f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:"
                            f"measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}:"
                            "linear=true,aresample=48000", "-ac", "2", "-c:a", "pcm_s16le", str(norm)], check=True)
        log = subprocess.run([FF, "-hide_banner", "-i", str(norm), "-af", "silencedetect=n=-45dB:d=0.1", "-f", "null",
                              "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
        ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", log)]
        starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", log)]
        start = ends[0] if starts and starts[0] < 0.05 and ends else 0.0
        res.append((norm, round(max(0.0, start - 0.05), 3)))
    return res


def plan(count: int) -> list[dict]:
    """count роликов в каждую папку; 2–3 пары из разных исходников, 6–9 с; набор пар не повторяется нигде;
    пары, фразы и треки — поровну."""
    rng = random.Random(1330)
    ps = pairs()
    use: dict = {}
    seen: set = set()
    jobs = []
    n_all = 0
    for plat in FOLDERS:
        for n in range(count):
            for _ in range(3000):
                order = sorted(range(len(ps)), key=lambda i: use.get(i, 0) + rng.random() * 2.5)
                seq, total, used = [], 0.0, set()
                for i in order:
                    p = ps[i]
                    if p["src"] in used or total + p["dur"] > MAX_LEN:
                        continue
                    seq.append(i)
                    used.add(p["src"])
                    total += p["dur"]
                    if total >= MIN_LEN and (len(seq) == 3 or rng.random() < 0.6):
                        break
                if MIN_LEN <= total <= MAX_LEN and 2 <= len(seq) <= 3 and tuple(seq) not in seen:
                    break
            seen.add(tuple(seq))
            for i in seq:
                use[i] = use.get(i, 0) + 1
            jobs.append({"plat": plat, "n": n + 1, "pairs": [ps[i] for i in seq], "dur": round(total, 3),
                         "text": n_all % len(TEXTS), "music": (n_all // len(TEXTS)) % len(MUSIC)})
            n_all += 1
    return jobs


def build(job: dict) -> str:
    out = Path(job["out"])
    dest = out / f"{job['plat'].lower()}_{job['n']:03d}_{ID}.mp4"
    music, mstart = music_prep()[job["music"]]
    inputs, parts = [], []
    for k, p in enumerate(job["pairs"]):
        inputs += ["-ss", f"{p['a']:.4f}", "-t", f"{p['dur'] + 0.2:.4f}", "-i", str(src_file(p["src"]))]
        parts.append(f"[{k}:v]fps={FPS},trim=duration={p['dur']:.4f},setpts=PTS-STARTPTS,setsar=1[v{k}]")
    n = len(job["pairs"])
    dur = job["dur"]
    inputs += ["-i", str(D / f"_text{job['text'] + 1}.png"), "-ss", f"{mstart:.3f}", "-i", str(music)]
    parts += ["".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0[c]",
              f"[c][{n}:v]overlay=0:0,format=yuv420p,{SET_SDR}[v]",
              f"[{n + 1}:a]atrim=duration={dur:.3f},afade=t=out:st={dur - 0.3:.3f}:d=0.3,asetpts=PTS-STARTPTS[a]"]
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
                    "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(FPS),
                    *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dest)], check=True)
    return dest.name


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=300, help="роликов в каждую папку (TT и YT)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--test", action="store_true", help="по 4 ролика на папку → output/1330_test")
    args = ap.parse_args()
    for i, t in enumerate(TEXTS, 1):
        print(f"текст {i}: {T.text_png(t, D / f'_text{i}.png')} px", flush=True)
    print(f"пар: {len(pairs())}, музыка: {music_prep()}", flush=True)
    jobs = plan(args.count)
    if args.test:
        jobs = [j for j in jobs if j["n"] <= 4]
    for j in jobs:
        out = ROOT / "output" / ("1330_test" if args.test else f"{ID}_{j['plat']}_{args.count}")
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
