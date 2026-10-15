#!/usr/bin/env python3
"""
1265 — сплит-скрин: сверху клип из папки --top, снизу геймплей Magic Sort из --bottom
(скринкаст, 30 с, ×1.5 без пауз — output/clips_1265/gameplay_30s). Длина ролика = длине
верхнего клипа, но не больше --max-dur (30 с); звук — верхнего клипа, геймплей без звука.
Пары верх×низ уникальны, клипы обеих папок расходуются поровну. Права на верхние клипы —
на том, кто их подкладывает.

  python build_1265_reels.py --top <папка_клипов> --bottom output/clips_1265/gameplay_30s -n 200 --out output/1265_200 --suffix 1265
  python build_1265_reels.py --top <папка> --bottom output/clips_1265/gameplay_30s -n 5 --out output/1265_test
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
W, H, FPS = 1080, 1920, 30
EXTS = (".mp4", ".mov", ".m4v", ".webm")


def probe(path: Path) -> tuple[float, bool]:
    js = json.loads(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                                    "-of", "json", str(path)], capture_output=True, text=True).stdout or "{}")
    dur = float(js.get("format", {}).get("duration") or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in js.get("streams", []))
    return dur, has_audio


def plan(n: int, tops: list[Path], bottoms: list[Path], rng: random.Random) -> list[tuple[Path, Path]]:
    pairs = list(itertools.product(range(len(tops)), range(len(bottoms))))
    if n > len(pairs):
        raise SystemExit(f"нужно {n}, а уникальных пар только {len(pairs)} ({len(tops)}×{len(bottoms)})")
    rng.shuffle(pairs)
    use_t, use_b, out = Counter(), Counter(), []
    for _ in range(n):
        best = min(pairs, key=lambda p: (use_t[p[0]] + use_b[p[1]], use_t[p[0]], use_b[p[1]]))
        pairs.remove(best)
        use_t[best[0]] += 1
        use_b[best[1]] += 1
        out.append((tops[best[0]], bottoms[best[1]]))
    return out


def build(top: Path, bottom: Path, dest: Path, max_dur: float, split: float) -> float:
    dur, has_audio = probe(top)
    dur = min(dur, max_dur)
    th = int(H * split) // 2 * 2  # высота верхней части
    bh = H - th
    fc = (f"[0:v]scale={W}:{th}:force_original_aspect_ratio=increase,crop={W}:{th},setsar=1,fps={FPS}[t];"
          f"[1:v]scale={W}:-2,crop={W}:{bh},setsar=1,fps={FPS}[b];"
          f"[t][b]vstack=inputs=2,format=yuv420p,{SET_SDR}[v]")
    cmd = [FF, "-v", "error", "-y", "-i", str(top), "-stream_loop", "-1", "-i", str(bottom)]
    if has_audio:
        fc += f";[0:a]atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={max(0.0, dur - 0.3):.2f}:d=0.3[a]"
    cmd += ["-filter_complex", fc, "-map", "[v]"]
    cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"] if has_audio else ["-an"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", *SDR_COLOR_ARGS,
            "-t", f"{dur:.3f}", "-movflags", "+faststart", str(dest)]
    subprocess.run(cmd, stdin=subprocess.DEVNULL, check=True)
    return dur


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=Path, required=True, help="папка верхних клипов")
    ap.add_argument("--bottom", type=Path, required=True, help="папка геймплея")
    ap.add_argument("-n", type=int, default=5)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-dur", type=float, default=30.0)
    ap.add_argument("--split", type=float, default=0.5, help="доля высоты под верхний клип")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--suffix", default="")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    tops = sorted(p for p in args.top.iterdir() if p.suffix.lower() in EXTS)
    bottoms = sorted(p for p in args.bottom.iterdir() if p.suffix.lower() in EXTS)
    print(f"верх {len(tops)} · низ {len(bottoms)} → пар {len(tops) * len(bottoms)}", flush=True)
    pairs = plan(args.n, tops, bottoms, random.Random(args.seed))
    args.out.mkdir(parents=True, exist_ok=True)
    names = [f"{i:03d}{'_' + args.suffix if args.suffix else ''}.mp4" for i in range(1, len(pairs) + 1)]

    def job(k: int) -> dict:
        top, bottom = pairs[k]
        d = build(top, bottom, args.out / names[k], args.max_dur, args.split)
        return {"file": names[k], "top": top.name, "bottom": bottom.name, "dur": round(d, 2)}

    manifest = []
    with ThreadPoolExecutor(args.jobs) as ex:
        for i, row in enumerate(ex.map(job, range(len(pairs))), 1):
            manifest.append(row)
            if i % 10 == 0 or i == len(pairs):
                print(f"[{i}/{len(pairs)}]", flush=True)
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"готово: {len(manifest)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
