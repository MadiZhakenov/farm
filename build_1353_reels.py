#!/usr/bin/env python3
"""
1353 — текстволлы (тексты ТЗ дословно, переносы по смыслу, вопрос в конце отдельной строкой), 20 роликов:
  видео 1 (Drive 1SLxJwRTaMs-nBKDndwK11qjz6-IuF7T5 = downloads/gw_wall2/srcA, девушка «серьёзное лицо») — 10 шт,
          4 текста (3/3/2/2), каждый ролик на своём клипе (+ один клип повторно зеркально);
  видео 2 (Drive 1ZcWAxe7Kb65C7h-9XAQCP7NE2eufZVVU = downloads/gw_jump2/src, та же девушка прыгает с ноутбуком) — 10 шт,
          3 текста × 3 клипа + один зеркально; начало с показом сервиса на ноутбуке срезано — только прыжки, 1×.
Текст — как в gw_gotjob_uniq: белый TikTok-шрифт с чёрной обводкой, крупно и по центру безопасной зоны 9:16
(лицо может закрывать — так договорились для текстволлов). Звук — музыка из instagram.com/reel/DcXYq7Zt-vW
(6.85 с, уже −14 LUFS) вместо родного звука клипа; ролик обрезается по её длине.
NVENC (cq 27, ≤ 6 Мбит/с). Готовые ролики — output/1353 (только они), служебное — output/_work/1353.

  python build_1353_reels.py
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_wall_reels as WL  # noqa: E402  (рендер текстволла, безопасная зона)
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
W, H, FPS = 1080, 1920, 30
OUT = ROOT / "output" / "1353"
WORK = ROOT / "output" / "_work" / "1353"
ID = "1353"
SRC1 = ROOT / "downloads" / "gw_wall2" / "srcA"
SRC2 = ROOT / "downloads" / "gw_jump2" / "src"
MUSIC = ROOT / "downloads" / "1353" / "music" / "ref.mp4"    # звук рилса DcXYq7Zt-vW
MAX1 = 9.0                                          # видео 1: не длиннее, с
# видео 2: с какого момента идут прыжки (после показа ноутбука) и где кончаются (до того, как идёт к камере)
JUMPS = {"IMG_5675": (2.7, 9.0), "IMG_5676": (2.5, 10.0), "IMG_5708": (2.2, 8.5)}
MAX2 = 7.0

# тексты ТЗ дословно; \n — перенос по смыслу, \n\n — вопрос отдельной строкой
TEXTS1 = [
    "just found out my boyfriend\nhas a contact saved as\n“Sarah 🚫🚫🚫”\nand i’m sitting here\nwith my heart in my throat.\n"
    "he walked in, saw my face\nand said\n“oh. that’s the dog groomer.”\ni said\n“why the three red emojis??”\n"
    "he said “she charged us $140\nfor a haircut and the dog came home\nlooking like a mushroom.”\n"
    "i have never felt so relieved\nand so betrayed at the same time 😭\n\nwould you have panicked too?",
    "update: i found out how he did it.\nhe told me he was working late\nfor 4 months.\ntoday i opened find my\n"
    "on the family ipad.\nhis “work” is a house\n11 minutes from ours.\ni drove there.\nhis car is in the driveway,\n"
    "and so is a stroller 😭\ni’m sitting across the street.\ni’ve been here 40 minutes.\nthe door just opened\n\n"
    "what would you do?",
    "this is my face rn\nbecause 10 minutes ago i found out\nmy boyfriend has a contact\nsaved as “Mike (gym).”\n"
    "he doesn’t go to the gym.\ni don’t know a Mike.\nthe last message says\n“she suspects nothing, right?”\n"
    "and the profile photo\nis a girl in MY dress 🙂\nhe’s in the shower.\ni’m sitting here.\ni’m very calm\n\n"
    "should i go in?",
    "this is my face rn\nbecause 3 minutes ago\nmy boyfriend’s apple watch\nbuzzed on the nightstand\n"
    "and it said “miss you already 🥺\nsame time tomorrow?”\nfrom a contact called “Dentist.”\n"
    "he told me he hates the dentist.\nhe’s in the kitchen\nmaking me pancakes.\ni’m sitting here.\ni’m very calm 🙂\n\n"
    "should i go downstairs?",
]
TEXTS2 = [
    "this is me jumping\nbecause my husband told me\nto quit my job and\n“stay home like a normal wife.”\n"
    "i just got promoted.\nhe’s in the kitchen\nand i’m doing a victory dance\nat my desk\nwith the laptop in my hands.\n"
    "my mother-in-law just texted\n“congrats, he’s just worried.”\ni don’t care\n\nis it normal\nto want your own money?",
    "this is me jumping\nbecause it’s been 11 days\nsince i found out he cheated\nand i’ve already booked\n"
    "a new apartment, a new job\nand a flight to bali.\ni didn’t cry. i made a plan 🙂\nhe just texted “can we talk?”\n"
    "i’m typing this with one hand\nand holding my passport\nwith the other\n\nshould i answer him?",
    "this is me jumping\nbecause my boyfriend said\n“women who earn more than men\nare never satisfied.”\n"
    "i just got my first $10k month.\nhe’s looking at the screen\nwith his mouth open.\nhe asked “is that real?”\n"
    "i said “it’s called work”\nand screenshot it.\nhis mom is already\nin our group chat\n\nwho’s right here?",
]
# видео 1: (клип, текст, зеркало); видео 2: (клип, текст, зеркало)
PLAN1 = [("IMG_5663", 0, 0), ("IMG_5668", 0, 0), ("IMG_5670", 0, 0), ("IMG_5664", 1, 0), ("IMG_5669", 1, 0),
         ("IMG_5672", 1, 0), ("IMG_5665", 2, 0), ("IMG_5667", 2, 0), ("IMG_5664", 3, 1), ("IMG_5663", 3, 1)]
PLAN2 = [("IMG_5675", 0, 0), ("IMG_5676", 1, 0), ("IMG_5708", 2, 0), ("IMG_5676", 0, 0), ("IMG_5708", 1, 0),
         ("IMG_5675", 2, 0), ("IMG_5708", 0, 0), ("IMG_5675", 1, 0), ("IMG_5676", 2, 0), ("IMG_5675", 0, 1)]
WALL_CY = (WL.Y0 + WL.Y1) // 2


def wall_png(text: str, key: str) -> Path:
    """Самый крупный кегль, при котором строки не переносятся сами и весь блок влезает в безопасную зону; по центру."""
    dest = WORK / f"wall_{key}.png"
    n_lines = len([ln for ln in text.split("\n") if ln.strip()])
    px = 60
    while px > 28 and (WL.wall_height(text, px) > WL.Y1 - WL.Y0 - 8 or
                       len([x for x in WL.wall_lines(text, px) if x]) > n_lines):
        px -= 1
    top = max(WL.Y0 + 4, int(WALL_CY - WL.wall_height(text, px) / 2))
    WL.render_wall(text, px, top, dest)
    return dest


def window(src: Path, clip: str, part: int) -> tuple[float, float]:
    """Видео 1: спокойный кусок без включения/выключения камеры (как в gw_wall), ≤ 9 с; видео 2: только прыжки, ≤ 7 с."""
    if part == 2:
        a, b = JUMPS[clip]
        return a, min(b, a + MAX2)
    WL.SRC = src
    a, b = WL.usable_range(clip)
    return a, min(b, a + MAX1)


def music_len() -> float:
    out = subprocess.run([FP, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration",
                          "-of", "csv=p=0", str(MUSIC)], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def render(src: Path, clip: str, a: float, b: float, mirror: int, wall: Path, dest: Path) -> None:
    vf = (f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,scale={W}:{H}:flags=lanczos,fps={FPS},setsar=1"
          f"{',hflip' if mirror else ''}[b];[b][1:v]overlay=0:0,format=yuv420p,{SET_SDR}[v];"
          f"[2:a]atrim=end={b - a:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={max(0, b - a - 0.3):.3f}:d=0.3[a]")
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src / f"{clip}.MOV"), "-i", str(wall), "-i", str(MUSIC),
                    "-filter_complex", vf,
                    "-map", "[v]", "-map", "[a]", "-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr",
                    "-cq", "27", "-b:v", "0", "-maxrate", "6M", "-bufsize", "12M", "-profile:v", "high", *SDR_COLOR_ARGS,
                    "-c:a", "aac", "-b:a", "192k", "-t", f"{b - a:.3f}", "-movflags", "+faststart", str(dest)], check=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    walls = {f"1_{i}": wall_png(t, f"1_{i}") for i, t in enumerate(TEXTS1)}
    walls.update({f"2_{i}": wall_png(t, f"2_{i}") for i, t in enumerate(TEXTS2)})
    rows, n, mlen = [], 0, music_len()
    for part, plan, src in ((1, PLAN1, SRC1), (2, PLAN2, SRC2)):
        for clip, ti, mirror in plan:
            n += 1
            a, b = window(src, clip, part)
            b = min(b, a + mlen)                        # не длиннее музыки
            dest = OUT / f"{n:02d}_{ID}.mp4"
            render(src, clip, a, b, mirror, walls[f"{part}_{ti}"], dest)
            rows.append({"file": dest.name, "video": part, "clip": clip, "text": ti + 1, "mirror": mirror,
                         "from": round(a, 2), "to": round(b, 2), "duration": round(b - a, 2)})
            print(f"{dest.name}: видео {part}, {clip}, текст {ti + 1}{', зеркало' if mirror else ''}, {b - a:.1f} с", flush=True)
    with (WORK / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter=";")
        w.writeheader()
        w.writerows(rows)
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
