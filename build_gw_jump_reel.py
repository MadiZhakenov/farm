#!/usr/bin/env python3
"""
Global Work, «I just got a job offer (war is over)» (реф TikTok @chloeabigailc 7609069400838245646),
айди пока нет. Исходник downloads/gw_jump/src/IMG_2922.MOV: показывает globalwork.ai на ноуте, закрывает,
прыгает. Монтаж как в рефе: белый TikTok-текст без обводки и тени по центру весь ролик, звук — трек
из рефа (Happy Xmas (War Is Over)), громкость −14 LUFS. HDR iPhone → SDR (libplacebo), сырые края срезаны.

  python build_gw_jump_reel.py                                            # вариант 1
  python build_gw_jump_reel.py --slow --out output/gw_jump/gw_jump_v2_slow.mp4  # вариант 2
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import renderer as R  # noqa: E402
from core.safe_zones import check_overlay  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
D = ROOT / "downloads" / "gw_jump"
SRC, REF = D / "src" / "IMG_2922.MOV", D / "ref" / "ref_7609069400838245646.mp4"
W, H = 1080, 1920
TM = ("libplacebo=w=1080:h=1920:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:"
      "tonemapping=auto:format=yuv420p")
# вариант 2 — замедление как в рефе: показ ноутбука в 1×, с момента прыжков 0.5× с плавным разгоном вниз.
# Исходник 60 к/с → при 0.5× на выходе 30 настоящих кадров/с, без повторов и рывков (интерполяция не нужна).
# (начало, конец, скорость) в секундах исходника; итог ≈ 15 с — как реф и его трек
SLOW = [(1.1, 3.1, 1.0), (3.1, 3.2, 0.85), (3.2, 3.3, 0.7), (3.3, 3.4, 0.6), (3.4, 9.7, 0.5)]
# срез: до 1.1 с ставит камеру и заходит в кадр, после 9.7 с идёт к камере выключать
CUT = (1.1, 9.7)
# текст как в рефе: замер — строка «I just got a job offer» ≈ 490 px на 1080, центр блока ≈ 55 % высоты
LINES = ["I just got job offer", "(war is over)", "thx to global work"]   # дословно из ТЗ
PX, CY = 56, 0.55


def text_png(dest: Path) -> None:
    font = R._load_font(PX)
    adv = R.line_advance_for(PX)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    top = CY * H - adv * len(LINES) / 2
    for k, t in enumerate(LINES):
        d.text((W / 2, top + (k + 0.5) * adv), t, font=font, fill=(255, 255, 255, 255), anchor="mm")
    bad = check_overlay(canvas)
    if bad:
        raise SystemExit(f"текст вне безопасной зоны: {bad}")
    canvas.save(dest)


def audio_filter(start: float, dur: float) -> str:
    loud = "loudnorm=I=-14:TP=-1.5:LRA=11"
    base = f"atrim=start={start}:duration={dur},asetpts=PTS-STARTPTS,afade=t=out:st={dur - 0.4:.2f}:d=0.4"
    log = subprocess.run([FF, "-hide_banner", "-i", str(REF), "-af", f"{base},{loud}:print_format=json", "-f", "null",
                          "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log).group(0))
    return (f"{base},{loud}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
            f"measured_thresh={m['input_thresh']}:offset={m['target_offset']},aresample=48000")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "gw_jump" / "gw_jump_v1.mp4")
    ap.add_argument("--audio-start", type=float, default=0.0, help="с какой секунды брать трек рефа")
    ap.add_argument("--slow", action="store_true", help="вариант 2: замедление как в рефе")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    png = Path(tempfile.mkdtemp(prefix="gwjump_")) / "text.png"
    text_png(png)
    if args.slow:
        segs = SLOW
        dur = sum((b - a) / sp for a, b, sp in segs)
        parts = [f"[0:v]{TM},split={len(segs)}" + "".join(f"[s{i}]" for i in range(len(segs)))]
        for i, (a, b, sp) in enumerate(segs):
            parts.append(f"[s{i}]trim=start={a}:end={b},setpts=(PTS-STARTPTS)/{sp}[p{i}]")
        parts.append("".join(f"[p{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0,fps=30[b]")
        base = ";".join(parts)
    else:
        dur = CUT[1] - CUT[0]
        base = f"[0:v]{TM},fps=30,trim=start={CUT[0]}:end={CUT[1]},setpts=PTS-STARTPTS[b]"
    fc = (f"{base};[b][1:v]overlay=0:0,format=yuv420p,{SET_SDR}[v];"
          f"[2:a]{audio_filter(args.audio_start, dur)}[a]")
    subprocess.run([FF, "-v", "error", "-y", "-i", str(SRC), "-i", str(png), "-i", str(REF), "-filter_complex", fc,
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18", *SDR_COLOR_ARGS,
                    "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.2f}", "-movflags", "+faststart", str(args.out)],
                   check=True)
    print("готово →", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
