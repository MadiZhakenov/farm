#!/usr/bin/env python3
"""
Текстволл ID 1 (реф instagram DfaBBiJxuGp = наш формат FollowSpy/ig_Dcib): 10 историй ТЗ дословно, по-русски, переносы по смыслу,
белый TikTok-шрифт с обводкой по центру кадра поверх лица; фон — клипы из нашей базы под настроение истории
(спокойная девушка / удивлённая / bitch face / статичное лицо / спокойный парень); музыка и длина — треки рефов FollowSpy.
2 версии на историю = 20: разные клипы и треки.

  python build_textwall1.py --only v1 --out output/textwall1_test      # тест: по одному на историю
  python build_textwall1.py --out output/textwall1_20
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_followspy_walls as F  # noqa: E402  (WL — стена текста, REFS — треки рефов)
from textwall1_texts import TEXTS  # noqa: E402

WL = F.WL
DL = ROOT / "downloads"
W, H, FPS = 1080, 1920, 30
PX_MAX = 45
HLG = F.HLG
CLIP = {  # имя: (файл, тон)
    "A5663": (DL / "gw_wall2/proxy/IMG_5663.mp4", ""), "A5664": (DL / "gw_wall2/proxy/IMG_5664.mp4", "eq=gamma=1.35:saturation=1.06,"),
    "A5665": (DL / "gw_wall2/proxy/IMG_5665.mp4", ""), "A5668": (DL / "gw_wall2/proxy/IMG_5668.mp4", "eq=gamma=1.15:saturation=1.04,"),
    "A5669": (DL / "gw_wall2/proxy/IMG_5669.mp4", ""), "A5670": (DL / "gw_wall2/proxy/IMG_5670.mp4", ""),
    "B8101": (DL / "gw_wall2/proxy/IMG_8101.mp4", ""), "B8102": (DL / "gw_wall2/proxy/IMG_8102.mp4", ""),
    "B8107": (DL / "gw_wall2/proxy/IMG_8107.mp4", ""), "B8108": (DL / "gw_wall2/proxy/IMG_8108.mp4", ""),
    "B8079": (DL / "gw_hidden2/proxyB/IMG_8079.mp4", ""), "B8084": (DL / "gw_hidden2/proxyB/IMG_8084.mp4", ""),
    "B8085": (DL / "gw_hidden2/proxyB/IMG_8085.mp4", ""),
    "R5725": (DL / "drops_react/faces/IMG_5725.MOV", ""), "R5729": (DL / "drops_react/faces/IMG_5729.MOV", ""),
    "R5732": (DL / "drops_react/faces/IMG_5732.MOV", ""),
    "G2982": (DL / "gw_wall2/srcA/IMG_2982.MOV", HLG), "G2983": (DL / "gw_wall2/srcA/IMG_2983.MOV", HLG),
    "G2984": (DL / "gw_wall/src/IMG_2984.MOV", HLG + "eq=gamma=1.2:saturation=1.05,"),
}
# история: [(версия, клип, старт, трек рефа, зеркало)] — окна отсмотрены по кадрам: выражение лица под настроение истории
PLAN = {
    1: [("v1", "A5665", 1.0, "tt_sofiia", 0), ("v2", "A5669", 1.3, "ig_DYBG", 0)],             # спокойная девушка
    2: [("v1", "B8079", 0.0, "tt_cat", 0), ("v2", "R5732", 0.4, "ig_Dcib", 0)],                 # удивлённая
    3: [("v1", "A5663", 0.3, "tt_roxanne", 0), ("v2", "A5664", 0.6, "tt_milana", 0)],          # спокойная
    4: [("v1", "B8107", 1.1, "tt_sofiia", 0), ("v2", "B8108", 1.2, "tt_roxanne", 0)],          # bitch face
    5: [("v1", "B8102", 3.0, "tt_roxanne", 0), ("v2", "B8101", 1.2, "tt_sofiia", 0)],          # статичное лицо
    6: [("v1", "G2983", 0.5, "tt_milana", 0), ("v2", "G2984", 0.5, "tt_sofiia", 0)],           # спокойный парень
    7: [("v1", "B8085", 0.0, "tt_kia", 0), ("v2", "R5729", 0.85, "ig_DVt8", 0)],                # удивлённая
    8: [("v1", "A5668", 2.0, "ig_DYBG", 0), ("v2", "A5670", 0.3, "tt_bridget", 0)],            # спокойная
    9: [("v1", "G2982", 0.5, "tt_roxanne", 0), ("v2", "G2983", 6.0, "ig_DYBG", 1)],            # спокойный парень
    10: [("v1", "B8084", 0.0, "tt_kia", 0), ("v2", "R5725", 0.3, "ig_Dcib", 0)],               # удивлённая
}


def wall(text: str, dest: Path) -> tuple[int, tuple]:
    """Крупнейший кегль ≤ PX_MAX без авто-переносов, блок по центру безопасной зоны."""
    n = len([x for x in text.split("\n") if x.strip()])
    px = PX_MAX
    while px > 26 and (WL.wall_height(text, px) > WL.Y1 - WL.Y0 - 8 or len([x for x in WL.wall_lines(text, px) if x]) > n):
        px -= 1
    h = WL.wall_height(text, px)
    top = max(WL.Y0 + 4, int(F.WALL_CY - h / 2))
    WL.render_wall(text, px, top, dest)
    return px, (WL.X0, top, WL.X1, top + h)


def render(n: int, ver: str, clip: str, start: float, ref: str, mirror: int, out: Path, work: Path, name: str) -> Path:
    src, tone = CLIP[clip]
    d = F.dur(F.REFS / f"{ref}.mp4")
    if start + d > F.dur(src) - 0.05:
        raise SystemExit(f"{name}: клип {clip} короче трека {ref} ({start}+{d:.2f} > {F.dur(src):.2f})")
    png = work / f"{name}.png"
    wall(TEXTS[n], png)
    fc = (f"[0:v]trim=start={start:.3f}:duration={d:.3f},setpts=PTS-STARTPTS,{tone}scale={W}:{H}:flags=lanczos:"
          f"force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1{',hflip' if mirror else ''}[b];"
          f"[b][1:v]overlay=0:0,format=yuv420p[v];"
          f"[2:a]atrim=end={d:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={max(0, d - 0.3):.3f}:d=0.3,"
          f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[a]")
    dest = out / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-i", str(png), "-i", str(F.REFS / f"{ref}.mp4"),
                    "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{d:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    png.unlink()
    return dest


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="v1 или v2 — только эта версия (тест)")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "textwall1_test")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "output" / "_work" / "textwall1"
    work.mkdir(parents=True, exist_ok=True)
    jobs = []
    for n, rows in PLAN.items():
        for ver, clip, start, ref, mirror in rows:
            if a.only and ver != a.only:
                continue
            k = (n - 1) * 2 + (1 if ver == "v1" else 2)
            name = f"{n:02d}_{ver}_1" if a.only else f"{k:03d}_1"
            jobs.append((n, ver, clip, start, ref, mirror, a.out, work, name))
    with ThreadPoolExecutor(a.jobs) as ex:
        for dest in ex.map(lambda j: render(*j), jobs):
            print(" ", dest.name, flush=True)
    print(f"готово: {len(jobs)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
