#!/usr/bin/env python3
"""
Global Work, «текстовая стена» (30 роликов): 30 текстов из таблицы (колонка FULL TEXT WALL, дословно)
на 5 клипах креатора (downloads/gw_wall/src, по 6 текстов на клип). Белый TikTok-шрифт с чёрной обводкой,
блок сверху по центру внутри безопасной зоны 9:16 (docs/SAFE_ZONES.md), лицо — под текстом и не закрыто:
если блок не помещается над лицом, видео креатора сдвигается вниз (полоса сверху — размытое отражение
верха кадра), но так, чтобы глаза оставались выше нижней границы зоны (1540 px).
Кегль — максимальный (46→34), при котором всё влезает. Длинные тексты — на клипы, где над лицом больше места.
Звук и длительность — как у рефа (instagram.com/reel/DazEKzRKbxV → downloads/gw_wall/ref/ref.mp4, 6.3 с,
уже −14 LUFS): кусок клипа после включения камеры, без момента выключения. iPhone HDR → SDR.

  python build_gw_wall_reels.py
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402
from core import renderer as R  # noqa: E402
from core.safe_zones import check_overlay, text_rect  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
D = ROOT / "downloads" / "gw_wall"
SRC, SHEET, FACES, REF = D / "src", D / "sheet.csv", D / "src" / "_faces.json", D / "ref" / "ref.mp4"
OUT = ROOT / "output" / "gw_wall"
ID = "noid"
W, H = 1080, 1920
TM = ("libplacebo=w=1080:h=1920:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:"
      "tonemapping=auto:format=yuv420p,fps=30")
CLIPS = ["IMG_2920", "IMG_2921", "IMG_2982", "IMG_2983", "IMG_2984"]
X0, Y0, X1, Y1 = text_rect(W, H)          # 140, 200, 940, 1540
TEXT_TOP, GAP, PARA = Y0 + 10, 40, 0.45    # верх блока, отступ до макушки, доп. отступ между абзацами
PX_MAX, PX_MIN = 46, 34


def wall_lines(text: str, px: int) -> list[str | None]:
    """Перенос по ширине безопасной зоны; None — пустая строка между абзацами."""
    font, st = R._load_font(px), R.stroke_width_for(px)
    out: list[str | None] = []
    for para in text.strip().split("\n\n"):
        for raw in para.split("\n"):
            cur = ""
            for w in raw.split():
                c = (cur + " " + w).strip()
                if cur and A._line_width_mixed(c, font, px, st) > (X1 - X0) - 2 * st:
                    out.append(cur)
                    cur = w
                else:
                    cur = c
            if cur:
                out.append(cur)
        out.append(None)
    return out[:-1]


def wall_height(text: str, px: int) -> int:
    adv = R.line_advance_for(px)
    lines = wall_lines(text, px)
    return sum(adv if x is not None else int(adv * PARA) for x in lines)


def render_wall(text: str, px: int, top: int, dest: Path) -> None:
    font, st, adv = R._load_font(px), R.stroke_width_for(px), R.line_advance_for(px)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = top
    for ln in wall_lines(text, px):
        if ln is None:
            y += int(adv * PARA)
            continue
        lw = A._line_width_mixed(ln, font, px, st)
        A._draw_line_mixed(img, d, int((W - lw) / 2), y, ln, font, px, st)
        y += adv
    bad = check_overlay(img)
    if bad:
        raise SystemExit(f"текст вне безопасной зоны: {bad}")
    img.save(dest)


def usable_range(clip: str) -> tuple[float, float]:
    """Без включения/выключения камеры: начало — когда кадр успокоился (движение < порога 0.5 с подряд),
    конец — до финального всплеска движения (рука к камере)."""
    raw = subprocess.run([FF, "-v", "error", "-i", str(SRC / f"{clip}.MOV"), "-vf", "scale=90:160,fps=10", "-f",
                          "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, 160, 90).astype(np.int16)
    d = np.abs(np.diff(v, axis=0)).mean((1, 2))
    calm = float(np.median(d[len(d) // 4: 3 * len(d) // 4]))
    th = max(1.2, 2.5 * calm)
    start = next((i for i in range(len(d) - 5) if (d[i:i + 5] < th).all()), 0)
    start = max(start, 3)                                    # минимум 0.3 с — момент нажатия записи
    tail = d[-30:]
    hits = np.where(tail > th)[0]
    end = len(d) - 30 + int(hits[0]) - 1 if len(hits) else len(d) - 3
    return start / 10, max(end, start + 30) / 10


def capacity(face: dict) -> tuple[int, int]:
    """Сколько места под текст (px) и макс. сдвиг видео: глаза не ниже Y1, макушка ниже текста на GAP."""
    max_shift = max(0, Y1 - face["eyes_max"])
    return face["top_min"] + max_shift - GAP - TEXT_TOP, max_shift


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="gwwall_"))
    rows = [r for r in csv.reader(SHEET.open(encoding="utf-8"))][1:]
    texts = [(int(r[0]), r[4]) for r in rows if r[4].strip()]
    faces = json.loads(FACES.read_text())
    caps = {c: capacity(faces[c]) for c in CLIPS}
    # самые длинные тексты — на клипы с наибольшим местом над лицом, по 6 на клип
    order = sorted(texts, key=lambda t: -wall_height(t[1], 42))
    clips_by_cap = sorted(CLIPS, key=lambda c: -caps[c][0])
    per = len(texts) // len(CLIPS)
    plan = {num: clips_by_cap[min(i // per, len(CLIPS) - 1)] for i, (num, _t) in enumerate(order)}
    ref_dur = float(subprocess.run([FF.replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error", "-show_entries",
                                    "format=duration", "-of", "csv=p=0", str(REF)], capture_output=True, text=True).stdout)
    ranges = {}
    for c in CLIPS:
        a, b = usable_range(c)
        if b - a < ref_dur:
            raise SystemExit(f"{c}: рабочий кусок {b - a:.1f} с короче рефа {ref_dur:.1f} с")
        ranges[c] = (a, a + ref_dur)
    print("рабочие куски клипов (с):", {c: (round(a, 1), round(b, 1)) for c, (a, b) in ranges.items()})
    report = []
    for num, text in texts:
        clip = plan[num]
        room, max_shift = caps[clip]
        px = next((p for p in range(PX_MAX, PX_MIN - 1, -1) if wall_height(text, p) <= room), PX_MIN)
        h = wall_height(text, px)
        shift = max(0, TEXT_TOP + h + GAP - faces[clip]["top_min"])
        shift += shift % 2                       # чётный сдвиг: иначе yuv420 округляет и кадр выходит 1918 px
        if shift > max_shift:
            print(f"#{num}: не влезает мимо лица даже {PX_MIN}px — сдвиг {shift} > {max_shift}")
        png = work / f"t{num}.png"
        render_wall(text, px, TEXT_TOP, png)
        a0, b0 = ranges[clip]
        if shift:
            vf = (f"[0:v]{TM},trim=start={a0}:end={b0},setpts=PTS-STARTPTS,split[m][t];[t]crop=iw:{shift}:0:0,vflip,gblur=sigma=30,eq=brightness=-0.06[tb];"
                  f"[m]crop=iw:ih-{shift}:0:0[mb];[tb][mb]vstack[b]")
        else:
            vf = f"[0:v]{TM},trim=start={a0}:end={b0},setpts=PTS-STARTPTS[b]"
        dest = OUT / f"{num:02d}_{ID}.mp4"
        subprocess.run([FF, "-v", "error", "-y", "-i", str(SRC / f"{clip}.MOV"), "-i", str(png), "-i", str(REF),
                        "-filter_complex",
                        f"{vf};[b]scale={W}:{H},setsar=1[bb];[bb][1:v]overlay=0:0,format=yuv420p,{SET_SDR}[v];"
                        f"[2:a:0]atrim=end={ref_dur},asetpts=PTS-STARTPTS[a]", "-map", "[v]", "-map", "[a]",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "18", *SDR_COLOR_ARGS, "-c:a", "aac",
                        "-b:a", "160k", "-movflags", "+faststart", str(dest)], check=True)
        report.append({"file": dest.name, "row": num, "clip": clip, "px": px, "text_h": h, "shift": shift})
        print(f"{dest.name}: строка {num} → {clip}, {px}px, блок {h}px, сдвиг видео {shift}px")
    (OUT / "manifest.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
