#!/usr/bin/env python3
"""Диагностика «фризит / лагает / зелёное» (юзер 2026-11-13): сборка кусков на видеокарте против эталона.

Для N вариантов skinive3 v3 собирает ТОЛЬКО видеоряд (куски → холст, без слоёв и карточек) тем же графом, что
build_skinive3_v3.render, и сравнивает КАЖДЫЙ кадр с эталоном: тот же кадр исходника, распакованный на процессоре,
та же обрезка. Для каждого кадра ищется, какому кадру исходника он на самом деле соответствует (±8 кадров):
  ok        — нужный кадр;
  сдвиг k   — показан кадр исходника на k раньше/позже (повтор = «фриз», пропуск = «рывок»);
  мусор     — не похож ни на один соседний (пустой/зелёный/битый).

  python diag_gpu_frames.py [--n 8] [--mode cuvid|nvdec|cpu]
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_skinive3_v3 as B  # noqa: E402
import build_skinive_uniq as U  # noqa: E402
from core import gpu_ffmpeg as G  # noqa: E402

W, H, FPS = 1080, 1920, 30
SW, SH = 270, 480
OUT = B.WORK / "diag"
_src: dict = {}


def src_frames(path: Path) -> np.ndarray:
    """Исходник целиком, процессор, серый 540×960."""
    if path not in _src:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "scale=540:960,format=gray",
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        _src[path] = np.frombuffer(raw, np.uint8).reshape(-1, 960, 540)
    return _src[path]


def ref_frame(path: Path, k: int, crop: tuple) -> np.ndarray:
    fr = src_frames(path)
    x, y, w, h = (v // 2 for v in crop)
    f = fr[min(max(k, 0), len(fr) - 1)][y:y + h, x:x + w]
    return np.asarray(Image.fromarray(f).resize((SW, SH), Image.BILINEAR), np.float32)


def build(c: dict, dest: Path, mode: str) -> None:
    shots = [x for seg in c["segs"] for x in seg]
    nfr = [round(x["len"] * FPS) for x in shots]
    nf = sum(nfr)
    inputs, fc, starts, acc = [], [], [], 0
    for i, x in enumerate(shots):
        src = U.FACE if x["src"] == "face" else B.LONG_STAB / f"{x['src']}.mp4"
        cx, cy, cw, ch = B.crop_of(x["g"])
        if mode == "cuvid":
            inputs += G.gpu_input(src, crop=(cx, cy, cw, ch))
            chain = f"scale_cuda={W}:{H}:format=yuv420p,"
        elif mode in ("nvdec", "hybrid"):                  # распаковка nvdec в память, обрезка/масштаб — процессор
            inputs += ["-hwaccel", "cuda", "-i", str(src)]
            chain = f"crop={cw}:{ch}:{cx}:{cy},scale={W}:{H}:flags=bilinear,setsar=1,format=yuv420p,"
        elif mode == "cuvidram2":                          # cuvid режет И масштабирует, кадры в память → слой на видеокарте
            _c, sw_, sh_ = G.probe(src)
            inputs += ["-c:v", "h264_cuvid", "-crop", f"{cy}x{sh_ - cy - ch}x{cx}x{sw_ - cx - cw}", "-resize", f"{W}x{H}", "-i", str(src)]
            chain = "setsar=1,format=yuv420p,"
        elif mode == "cuvidram":                           # cuvid режет сам, кадры сразу в память (как OneState 3)
            _c, sw_, sh_ = G.probe(src)
            inputs += ["-c:v", "h264_cuvid", "-crop", f"{cy}x{sh_ - cy - ch}x{cx}x{sw_ - cx - cw}", "-i", str(src)]
            chain = f"scale={W}:{H}:flags=bilinear,setsar=1,format=yuv420p,"
        else:
            inputs += ["-i", str(src)]
            chain = f"crop={cw}:{ch}:{cx}:{cy},scale={W}:{H}:flags=bilinear,setsar=1,format=yuv420p,"
        fc.append(f"[{i}:v]trim=start={x['t']:.3f}:duration={x['len'] + 0.05:.3f},setpts=PTS-STARTPTS,fps={FPS},"
                  f"{chain}tpad=stop_mode=clone:stop={nfr[i] + 2},trim=end_frame={nfr[i]}"
                  + (f"[s{i}]" if mode == "cuvid" else f",setpts=PTS-STARTPTS[s{i}]"))
        starts.append(acc)
        acc += nfr[i]
    if mode == "cuvid":
        idx = len(shots)
        black = B.WORK / "black_1080x1920.png"
        if not black.exists():
            Image.new("RGB", (W, H), (0, 0, 0)).save(black)
        inputs += ["-i", str(black)]
        fc.append(f"[{idx}:v]format=yuv420p,hwupload_cuda,loop=loop={nf - 1}:size=1:start=0,settb=1/{FPS},setpts=N[canvas]")
        fc += G.seq_overlay("canvas", [(f"s{i}", starts[i]) for i in range(len(shots))], "v")
        enc = G.NVENC
    elif mode in ("hybrid", "cuvidram2"):                                 # куски в памяти → в видеокарту → слой overlay_cuda → NVENC
        idx = len(shots)
        lay = B.WORK / "empty_layer.png"
        if not lay.exists():
            Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(lay)
        inputs += ["-i", str(lay)]
        fc.append("".join(f"[s{i}]" for i in range(len(shots))) + f"concat=n={len(shots)}:v=1:a=0,hwupload_cuda[b0]")
        fc.append(G.layer(idx, 0, nf, "l0"))
        fc.append("[b0][l0]overlay_cuda=0:0:eof_action=pass[v]")
        enc = G.NVENC
    else:
        fc.append("".join(f"[s{i}]" for i in range(len(shots))) + f"concat=n={len(shots)}:v=1:a=0[v]")
        enc = G.NVENC
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]",
                    "-frames:v", str(nf), "-r", str(FPS), *enc, "-an", str(dest)], check=True, timeout=300)


def check(c: dict, dest: Path) -> dict:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(dest), "-vf", f"scale={SW}:{SH},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    out = np.frombuffer(raw, np.uint8).reshape(-1, SH, SW).astype(np.float32)
    shots = [x for seg in c["segs"] for x in seg]
    res = dict(frames=len(out), ok=0, shift=[], junk=[])
    n = 0
    for x in shots:
        src = U.FACE if x["src"] == "face" else B.LONG_STAB / f"{x['src']}.mp4"
        crop = B.crop_of(x["g"])
        k0 = int(np.ceil(x["t"] * FPS - 1e-6))             # первый кадр с временем ≥ t
        for j in range(round(x["len"] * FPS)):
            if n >= len(out):
                break
            d = {dk: float(np.abs(out[n] - ref_frame(src, k0 + j + dk, crop)).mean()) for dk in range(-8, 9)}
            best = min(d, key=d.get)
            if d[best] > 12:
                res["junk"].append((n, round(d[best], 1)))
            elif best != 0 and d[0] - d[best] > 0.6:
                res["shift"].append((n, best))
            else:
                res["ok"] += 1
            n += 1
    return res


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--mode", default="cuvid")
    ap.add_argument("--seed", type=int, default=555)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    tot = dict(frames=0, ok=0, shift=0, junk=0)
    for i in range(a.n):
        c = B.candidate(rng)
        dest = OUT / f"{a.mode}_{i:02d}.mp4"
        build(c, dest, a.mode)
        r = check(c, dest)
        parts = [(x["src"], x["t"], round(x["len"] * FPS)) for seg in c["segs"] for x in seg]
        print(f"{a.mode} {i:02d}: кадров {r['frames']}, верных {r['ok']}, сдвинутых {len(r['shift'])} {r['shift'][:12]}, "
              f"мусор {r['junk'][:8]} | куски {parts}", flush=True)
        tot["frames"] += r["frames"]; tot["ok"] += r["ok"]; tot["shift"] += len(r["shift"]); tot["junk"] += len(r["junk"])
    print(f"ИТОГ {a.mode}: {tot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
