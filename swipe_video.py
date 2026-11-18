#!/usr/bin/env python3
"""Общий движок «карусель → видео 9:16 со свайпами» (как листают фото-карусель в TikTok).
Слайды — готовые PNG 1080×1920. Стоп-кадр каждого слайда декодируется один раз (кадры размножает loop),
свайп — два слайда бок о бок и окно 1080 px едет вправо с ease-out (кубик). Свайп кончается на заданном времени
(доле музыки). Кодирование — видеокартой (h264_nvenc, cq 27, maxrate 6M), метаданные вычищены.

Используют: build_xmas_video.py (и такие же сборщики дальше). План для QA пишется рядом с партией:
output/_work/<проект>/manifest_<папка>.json — {файл: {ends, total, picks, start}} → qa_swipe_video.py.
"""

from __future__ import annotations

import itertools
import random
import subprocess
from pathlib import Path

W, H, FPS = 1080, 1920, 30
SWIPE = 0.32


def beat_timing(beats: list[float], b0: int, holds: list[int]) -> tuple[float, list[float], float]:
    """Старт звука (чуть раньше доли b0), концы свайпов и длина видео по числу долей на каждый слайд (holds)."""
    ss = max(0.0, beats[b0] - 0.05)
    ends, acc = [], b0
    for h in holds[:-1]:
        acc += h
        ends.append(round(beats[acc] - ss, 3))
    total = beats[b0 + sum(holds)] - ss
    return round(ss, 3), ends, round(round(total * FPS) / FPS, 3)


def plan_unique(pools: list[list[Path]], n: int, seed: int) -> list[list[Path]]:
    """n сочетаний кадров, все разные; каждый раз берём сочетание из наименее использованных кадров."""
    rng = random.Random(seed)
    combos = list(itertools.product(*[range(len(p)) for p in pools]))
    if n > len(combos):
        raise SystemExit(f"кадров не хватает: сочетаний {len(combos)}, нужно {n}")
    rng.shuffle(combos)
    used: dict = {}
    out = []
    for _ in range(n):
        best = min(combos[:3000], key=lambda c: (sum(used.get((k, j), 0) for k, j in enumerate(c)), rng.random()))
        combos.remove(best)
        for k, j in enumerate(best):
            used[(k, j)] = used.get((k, j), 0) + 1
        out.append([pools[k][j] for k, j in enumerate(best)])
    return out


def encode(pngs: list[Path], ends: list[float], total: float, music: Path, ss: float, out: Path, work: Path) -> Path:
    """Склейка слайдов со свайпами + звук с ss, длина total. work — своя папка этого видео (graph.txt)."""
    k_n = len(pngs)
    n = round(total * FPS)
    m = round(SWIPE * FPS)
    e_fr = [round(x * FPS) for x in ends]                   # кадр, с которого новый слайд стоит целиком
    ins, fc = [], []
    for k, p in enumerate(pngs):
        ins += ["-i", str(p)]
        outs = [f"h{k}"] + ([f"i{k}"] if k > 0 else []) + ([f"o{k}"] if k < k_n - 1 else [])
        fc.append(f"[{k}:v]format=yuv420p,split={len(outs)}" + "".join(f"[{o}]" for o in outs))
    segs = []
    for k in range(k_n):
        a = e_fr[k - 1] if k > 0 else 0
        b = e_fr[k] - m if k < k_n - 1 else n
        fc.append(f"[h{k}]loop=loop={b - a - 1}:size=1:start=0,settb=1/{FPS},setpts=N[H{k}]")
        segs.append(f"[H{k}]")
        if k < k_n - 1:
            fc.append(f"[o{k}][i{k + 1}]hstack=inputs=2,loop=loop={m - 1}:size=1:start=0,settb=1/{FPS},setpts=N,"
                      f"crop=w={W}:h={H}:y=0:x='floor({W}*(1-pow(1-n/{m},3))/2)*2'[T{k}]")
            segs.append(f"[T{k}]")
    fc.append("".join(segs) + f"concat=n={len(segs)}:v=1:a=0[v]")
    ins += ["-ss", f"{ss:.3f}", "-t", f"{total + 0.3:.2f}", "-i", str(music)]
    fc.append(f"[{k_n}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
              f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=in:d=0.15,afade=t=out:st={total - 0.8:.3f}:d=0.8[a]")
    script = work / "graph.txt"
    script.write_text(";\n".join(fc), encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex_script", str(script), "-map", "[v]", "-map", "[a]",
                    "-t", f"{total:.3f}", "-r", str(FPS), "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27",
                    "-maxrate", "6M", "-bufsize", "12M", "-pix_fmt", "yuv420p",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-c:a", "aac", "-b:a", "160k",
                    "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
                    "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=",
                    "-movflags", "+faststart", str(out)], check=True)
    return out
