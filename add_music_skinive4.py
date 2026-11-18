#!/usr/bin/env python3
"""skinive_4: заменить тишину на трек как в skinive_3 (реф skinive_2 по кругу, S2.music_loop) — видео копируется без
перекодирования, звук AAC 160k, метаданные чистятся.
  python add_music_skinive4.py output/skinive4_TT_100 output/skinive4_YT_200"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_skinive2 as S2  # noqa: E402

WORK = ROOT / "output" / "_work" / "skinive4_music"


def dur(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)


def one(f: Path) -> str:
    wav = WORK / f"{f.stem}.wav"
    S2.music_loop(wav, dur(f))
    tmp = f.with_suffix(".tmp.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(f), "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "160k", "-shortest", "-map_metadata", "-1", "-fflags", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=",
                    "-movflags", "+faststart", str(tmp)], check=True)
    tmp.replace(f)
    wav.unlink()
    return f.name


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    files = [f for d in sys.argv[1:] for f in sorted(Path(d).glob("*_noid.mp4"))]
    with ThreadPoolExecutor(6) as ex:
        for k, name in enumerate(ex.map(one, files), 1):
            if k % 25 == 0:
                print(k, name, flush=True)
    print("готово:", len(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
