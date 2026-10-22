#!/usr/bin/env python3
"""Каждому видео из папки — случайный трек из папки музыки (поровну, без повторов подряд).
Видео копируется без перекодирования, своё аудио заменяется музыкой: с 0 с, зацикливается, если короче ролика,
громкость −14 LUFS, затухание 0.3 с в конце.

  python add_random_music.py downloads/dropbox_zzpzlok1/src downloads/music_petsplay --out output/petsplay_music
"""
import argparse
import json
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin"
VID = {".mp4", ".mov", ".m4v"}
AUD = {".mp3", ".m4a", ".aac", ".wav"}


def duration(p: Path) -> float:
    out = subprocess.run([f"{FF}\\ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def render(video: Path, track: Path, out: Path) -> None:
    d = duration(video)
    af = f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={max(0.0, d - 0.3):.3f}:d=0.3"
    subprocess.run([f"{FF}\\ffmpeg", "-y", "-v", "error", "-i", str(video), "-stream_loop", "-1", "-i", str(track),
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-t", f"{d:.3f}", "-movflags", "+faststart", str(out)], check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", type=Path)
    ap.add_argument("music", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    vids = sorted((p for p in a.videos.iterdir() if p.suffix.lower() in VID),
                  key=lambda p: (len(p.stem), p.stem))
    tracks = sorted(p for p in a.music.iterdir() if p.suffix.lower() in AUD)
    rnd = random.Random(a.seed)
    pool: list[Path] = []
    while len(pool) < len(vids):                         # поровну: каждый трек по разу, затем по второму кругу…
        batch = tracks[:]
        rnd.shuffle(batch)
        if pool and batch[0] == pool[-1]:
            batch.append(batch.pop(0))
        pool += batch
    order = vids[:]
    rnd.shuffle(order)
    plan = dict(zip(order, pool))
    a.out.mkdir(parents=True, exist_ok=True)
    jobs = [(v, plan[v], a.out / f"{v.stem}.mp4") for v in vids]
    with ThreadPoolExecutor(a.jobs) as ex:
        list(ex.map(lambda j: render(*j), jobs))
    manifest = {v.name: t.name for v, t, _ in jobs}
    (a.out / "music_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    for v, t, _ in jobs:
        print(f"{v.name} -> {t.name}")
    print(f"готово: {len(jobs)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
