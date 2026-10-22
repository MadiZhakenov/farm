#!/usr/bin/env python3
"""
1285, гипотеза 1: заменить звук готовых роликов на один из трёх TikTok-звуков поровну (родной звук убираем).

  m1 «sonido original» (43 с) · m2 «Blood» — Michael C. Hall (22.4 с) · m3 «Messa da Requiem: II. Dies irae» (60 с,
  первые 1.0 с тишины обрезаем). Звук каждого ролика — трек с начала на всю длину ролика: трек короче ролика не
  ставим (длинные ролики — на m1/m3), остальное распределяем случайно так, чтобы у каждого трека было поровну.
  Громкость: трек заранее −14 LUFS, затем отрезок каждого ролика ещё раз двухпроходно до −14 LUFS (пики ≤ −1.5 dB),
  в конце затухание 0.3 с. Видео копируется без перекодирования.

  python set_1285_music.py output/1285_500_h1 output/1285_500_h1_10s
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
MUS = ROOT / "downloads" / "1285" / "music"
TRACKS = [  # (ключ, файл, с какой секунды трека)
    ("m1_sonido_original", MUS / "m1_sonido_original_7101932530202462982.m4a", 0.0),
    ("m2_blood", MUS / "m2_blood_7542977955581004599.m4a", 0.0),
    ("m3_dies_irae", MUS / "m3_dies_irae_6705060426427664385.m4a", 1.0),
]
LOUD = "loudnorm=I=-14:TP=-1.5:LRA=11"
FADE = 0.3


def dur_of(p: Path) -> float:
    return float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)


def loudnorm_args(src: list[str], pre: str = "") -> str:
    """Фильтр второго прохода loudnorm по замеру первого (src — входные аргументы ffmpeg)."""
    log = subprocess.run([FF, "-hide_banner", *src, "-af", (pre + "," if pre else "") + LOUD + ":print_format=json",
                          "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = json.loads(log[log.rfind("{"):log.rfind("}") + 1])
    return (f"{LOUD}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
            f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")


def masters(work: Path) -> dict[str, tuple[Path, float]]:
    out = {}
    for key, src, start in TRACKS:
        dest = work / f"{key}.wav"
        inp = ["-ss", f"{start:.3f}", "-i", str(src)]
        subprocess.run([FF, "-v", "error", "-y", *inp, "-af", loudnorm_args(inp) + ",aresample=48000",
                        "-ac", "2", "-c:a", "pcm_s16le", str(dest)], check=True)
        out[key] = (dest, dur_of(dest))
    return out


def assign(files: list[tuple[Path, float]], tr: dict[str, tuple[Path, float]], rng: np.random.Generator) -> dict:
    """Поровну по трекам, трек не короче ролика. Сначала ролики, которым подходят не все треки."""
    keys = list(tr)
    n = len(files)
    quota = {k: n // len(keys) + (1 if i < n % len(keys) else 0) for i, k in enumerate(keys)}
    fits = {f: [k for k in keys if tr[k][1] >= d + 0.05] for f, d in files}
    order = sorted(files, key=lambda fd: (len(fits[fd[0]]), rng.random()))
    out = {}
    for f, _d in order:
        ok = [k for k in fits[f] if quota[k] > 0]
        if not ok:
            raise SystemExit(f"{f.name}: нет подходящего трека с запасом квоты")
        k = max(ok, key=lambda x: (quota[x], rng.random()))     # туда, где больше свободных мест
        out[f] = k
        quota[k] -= 1
    return out


def remux(f: Path, d: float, master: Path) -> None:
    tmp = f.with_name(f.stem + ".part.mp4")
    seg = f.with_name(f.stem + ".seg.wav")
    subprocess.run([FF, "-v", "error", "-y", "-i", str(master), "-t", f"{d:.3f}", "-c:a", "pcm_s16le", str(seg)],
                   check=True)
    flt = loudnorm_args(["-i", str(seg)])
    subprocess.run([FF, "-v", "error", "-y", "-i", str(f), "-i", str(seg), "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-af", f"{flt},afade=t=out:st={max(0, d - FADE):.3f}:d={FADE},aresample=48000",
                    "-c:a", "aac", "-b:a", "192k", "-t", f"{d:.3f}", "-map_metadata", "-1",
                    "-movflags", "+faststart", str(tmp)], check=True)
    seg.unlink()
    tmp.replace(f)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = Path(tempfile.mkdtemp(prefix="m1285_"))
    tr = masters(work)
    print("треки:", {k: round(v[1], 1) for k, v in tr.items()}, flush=True)
    for i, d in enumerate(sys.argv[1:]):
        folder = ROOT / d
        files = sorted(p for p in folder.glob("*.mp4") if not p.name.endswith((".part.mp4",)))
        with ThreadPoolExecutor(8) as ex:
            durs = list(ex.map(dur_of, files))
        rng = np.random.default_rng(1285 + i)
        plan = assign(list(zip(files, durs)), tr, rng)
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(lambda fd: remux(fd[0], fd[1], tr[plan[fd[0]]][0]), zip(files, durs)))
        rep = [{"file": f.name, "duration": round(dd, 2), "music": plan[f]} for f, dd in zip(files, durs)]
        (folder / "manifest_music.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
        cnt = {k: sum(1 for r in rep if r["music"] == k) for k in tr}
        print(f"{folder.name}: {len(rep)} роликов, по трекам {cnt}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
