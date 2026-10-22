#!/usr/bin/env python3
"""
Global Work «I just got job offer (war is over)», вторая партия — как output/gw_jump (build_gw_jump_reel.py --slow),
только сразу в слоу-мо: показ ноутбука с globalwork.ai в 1×, затем плавный переход и прыжки/танец в 0.5×;
длина = трек рефа (15.03 с). Текст дословно из ТЗ, белый TikTok-шрифт без обводки, звук рефа −14 LUFS.

Исходники downloads/gw_jump2/src (девушка, iPhone SDR):
  IMG_5708 — 60 к/с (0.5× без повторов кадров); IMG_5675 (в заголовке 120, на деле ~29 к/с, переменная частота)
  и IMG_5676 (~29 к/с) — для 0.5× выравниваем до 30 к/с и дорисовываем промежуточные кадры (minterpolate, 60 к/с),
  иначе каждый кадр повторяется дважды и замедление дёргается.

  python build_gw_jump2_reels.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_jump_reel as J  # noqa: E402  (текст, звук рефа)
from core.text_shadow import shadow_full_frame  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402
from PIL import Image  # noqa: E402

FF = J.FF
SRC = ROOT / "downloads" / "gw_jump2" / "src"
SRC3 = ROOT / "downloads" / "gw_jump3" / "src"      # монтаж 3 (Drive 1vv1fHqV1xvTFOPMM0Xjnnqjubb2IeM_A), iPhone HLG 4K
OUT = ROOT / "output" / "gw_jump2"
ID = "noid"
TRACK = 15.03                         # длина трека рефа
RAMP = [(0.1, 0.85), (0.1, 0.7), (0.1, 0.6)]
# клип: (начало, конец показа ноутбука в 1×, к/с исходника[, конец]) — с конца ноутбука плавный переход и 0.5×
# до длины трека. Начало — после того, как камеру поставили; конец замедления — до момента, когда она идёт к камере
# выключать. Если клип короткий, задаём конец: замедление тогда чуть сильнее 0.5×, чтобы ровно заполнить трек.
CLIPS = {
    "IMG_5675": (0.50, 2.60, 30),
    "IMG_5676": (0.75, 2.40, 30),
    "IMG_5708": (0.00, 2.10, 60),
    "IMG_8076": (0.00, 2.00, 60, 7.85),     # монтаж 3: с 8.0 с идёт к камере
}
HDR_PRE = ("libplacebo=w=1080:h=1920:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:"
           "tonemapping=auto:format=yuv420p")


def plan(start: float, lap_end: float, end: float | None = None) -> list[tuple[float, float, float]]:
    segs, t = [(start, lap_end, 1.0)], lap_end
    for d, sp in RAMP:
        segs.append((t, t + d, sp))
        t += d
    used = sum((b - a) / sp for a, b, sp in segs)
    if end is None:
        segs.append((t, t + (TRACK - used) * 0.5, 0.5))
    else:
        segs.append((t, end, (end - t) / (TRACK - used)))
    return segs


def src_path(name: str) -> Path:
    return next(p for p in (SRC / f"{name}.MOV", SRC3 / f"{name}.MOV") if p.exists())


def is_hdr(path: Path) -> bool:
    return "arib-std-b67" in subprocess.run([FF.replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error", "-select_streams",
                                             "v:0", "-show_entries", "stream=color_transfer", "-of", "csv=p=0",
                                             str(path)], capture_output=True, text=True).stdout


def build(name: str, png: Path) -> dict:
    start, lap_end, fps, *end = CLIPS[name]
    segs = plan(start, lap_end, end[0] if end else None)
    dur = sum((b - a) / sp for a, b, sp in segs)
    interp = lambda sp: sp < 1 and min(fps, 60) * sp < 29.5          # noqa: E731  реальных кадров меньше 30/с
    if interp(segs[-1][2]):         # интерполяция съедает пару кадров на стыках — берём запас, обрезаем по -t
        a0, b0, sp0 = segs[-1]
        segs[-1] = (a0, b0 + 0.15, sp0)
    src = src_path(name)
    pre = f"{HDR_PRE if is_hdr(src) else f'scale={J.W}:{J.H}:flags=lanczos'},setsar=1,fps={min(fps, 60)}"
    mi = "minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:scd=none"
    parts = [f"[0:v]{pre},split={len(segs)}" + "".join(f"[s{i}]" for i in range(len(segs)))]
    for i, (a, b, sp) in enumerate(segs):
        # 30 к/с: замедленный кусок дорисовываем до 30 к/с промежуточными кадрами (иначе кадры повторяются)
        z = f",{mi}" if interp(sp) else ""
        parts.append(f"[s{i}]trim=start={a:.3f}:end={b:.3f},setpts=(PTS-STARTPTS)/{sp}{z}[p{i}]")
    parts.append("".join(f"[p{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0,fps=30[b]")
    fc = (";".join(parts) + f";[b][1:v]overlay=0:0,format=yuv420p,{SET_SDR}[v];"
          f"[2:a]{J.audio_filter(0.0, dur)}[a]")
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"gw_jump2_{name[4:]}_slowmo_{ID}.mp4"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-i", str(png), "-i", str(J.REF),
                    "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "18", *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.2f}",
                    "-movflags", "+faststart", str(dest)], check=True)
    return {"file": dest.name, "duration": round(dur, 2), "source": [segs[0][0], round(segs[-1][1], 2)],
            "laptop_1x": [start, lap_end]}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    png = Path(tempfile.mkdtemp(prefix="gwjump2_")) / "text.png"
    J.text_png(png)
    shadow_full_frame(Image.open(png).convert("RGBA")).save(png)     # мягкая тень под текстом
    only = sys.argv[1:]
    for name in [c for c in CLIPS if not only or any(o in c for o in only)]:
        print(build(name, png), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
