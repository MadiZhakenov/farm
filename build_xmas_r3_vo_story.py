#!/usr/bin/env python3
"""
Раунд 3 (docs/REPOST_HYPOTHESES.md) — «оригинал + голос с историей» с субтитрами, в ключе, который зашёл юзеру
(R3-3d / R3-6): исходный ролик в исходном порядке кадров, родные вшитые подписи остаются, куски растянуты/сжаты
под фразы озвучки (медленнее — для трогательной истории), под голосом тихо «Let It Snow».
Субтитры — текст СЦЕНАРИЯ (не Whisper), тайминг — Whisper по словам; белый TikTok-шрифт с обводкой, 2–4 слова,
в части кадра без их подписи (V1/V3 — ниже середины, V2 — выше).

  python build_xmas_r3_vo_story.py --hyp R3-7 --out output/xmas_r3/R3-7_vo_heart
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import renderer as R  # noqa: E402
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
SRC = ROOT / "downloads" / "xmas_proj" / "src"
MUSIC = ROOT / "downloads" / "1303" / "music" / "gZIrKXCzue8.m4a"      # «Let It Snow» (юзер: этот подходит)
SRC_NAME = {"v1": "DcNWKlfAbOo.mp4", "v2": "DdGwGMEx-Uj.mp4", "v3": "DdZ5O2bR39c.mp4"}
SUB_Y = {"v1": 0.72, "v2": 0.72, "v3": 0.73}                            # субтитры ВНИЗУ, заголовок сверху (юзер)
SUB_PX = 66

# гипотеза → ролик → озвучка, сценарий, сегменты (VO от, VO до, src от, src до) в порядке оригинала
HYP = {
    "R3-7": {   # трогательная история (юзер озвучил chipbot, 2026-11-05)
        "dir": ROOT / "downloads" / "xmas_proj" / "vo7",
        "v1": dict(vo="13_20_12.mp3", total=12.9,
                   text="My grandma / hasn't decorated / since grandpa passed. / So I brought this over / and turned off the lights. / When Santa's sleigh / flew around / her living room, / she cried. / She asked me / to leave it on / all night.",
                   seg=[(0.0, 3.3, 4.85, 6.45), (3.3, 6.3, 6.55, 8.7), (6.3, 9.0, 8.75, 10.5), (9.0, 12.9, 10.55, 14.85)]),
        "v2": dict(vo="13_20_30.mp3", total=11.7,
                   text="My little brother / was always / scared of the dark. / Last night / I plugged this / into his wall / and turned off the lights. / His ceiling / turned into a snowstorm, / and he asked me / to keep the lights off.",
                   seg=[(0.0, 3.24, 2.75, 4.9), (3.24, 4.3, 5.6, 6.9), (4.3, 5.28, 7.35, 8.45), (5.28, 7.0, 8.45, 9.37),
                        (7.0, 9.2, 9.4, 11.55), (9.2, 11.7, 11.6, 13.2)]),
        "v3": dict(vo="13_20_45.mp3", total=10.65,
                   text="Last year / our tree fell / right before Christmas, / and my kids thought / Christmas was cancelled. / This year / we just plugged this in, / and they fell asleep / right under / the snowflakes.",
                   seg=[(0.0, 5.44, 0.0, 3.52), (5.44, 6.3, 3.6, 4.4), (6.3, 7.4, 5.15, 6.25), (7.4, 10.65, 7.3, 10.2)]),
    },
    "R3-8": {   # полезный обзор (юзер озвучил chipbot, 2026-11-05)
        "dir": ROOT / "downloads" / "xmas_proj" / "vo8",
        "v1": dict(vo="13_21_20.mp3", total=11.6,
                   text="If you love Christmas, / you need this. / It's a projector / that makes Santa's sleigh / fly around your room. / Just plug it in / and turn off the lights. / My parents watch it / every single night.",
                   seg=[(0.0, 2.64, 0.0, 2.6), (2.64, 4.4, 4.85, 6.45), (4.4, 6.12, 6.55, 8.6), (6.12, 8.64, 8.75, 10.5),
                        (8.64, 11.6, 12.6, 14.85)]),
        "v2": dict(vo="13_21_28.mp3", total=14.0,
                   text="This tiny tree / plugs into any outlet. / No batteries, / no setup. / Turn off the lights / and your ceiling turns / into snowflakes / and stars, / then Santa and snowmen. / The easiest / Christmas decor ever.",
                   seg=[(0.0, 1.6, 2.75, 4.3), (1.6, 2.92, 7.35, 8.45), (2.92, 5.08, 5.0, 7.25), (5.08, 6.3, 8.45, 9.37),
                        (6.3, 9.26, 9.4, 11.55), (9.26, 11.16, 11.6, 13.2), (11.16, 14.0, 0.0, 2.7)]),
        "v3": dict(vo="13_21_33.mp3", total=12.75,
                   text="Stop fighting / with your tree / every year. / This plugs into the wall / and fills your room / with snowflakes / in seconds. / No ladders, / no falling trees, / no mess. / My kids literally / sleep under it now.",
                   seg=[(0.0, 2.58, 0.4, 3.4), (2.58, 3.82, 5.15, 6.2), (3.82, 4.6, 6.2, 6.87), (4.6, 6.62, 9.3, 10.25),
                        (6.62, 9.12, 2.3, 3.5), (9.12, 12.75, 7.3, 9.3)]),
    },
}


def chunks(text: str, words: list) -> list[tuple[float, float, str]]:
    """Куски субтитров заданы в сценарии через « / » (по смыслу, не по ширине); слова сценария ↔ слова Whisper
    по порядку; кусок стоит от начала своего первого слова до начала следующего куска."""
    groups = [g.split() for g in text.split(" / ")]
    n = sum(len(g) for g in groups)
    if n != len(words):
        raise SystemExit(f"число слов сценария {n} ≠ Whisper {len(words)} — сверить вручную")
    out, i = [], 0
    for g in groups:
        out.append((float(words[i][1]), " ".join(g)))
        i += len(g)
    return [(a, out[k + 1][0] if k + 1 < len(out) else a + 2.5, t) for k, (a, t) in enumerate(out)]


def sub_png(text: str, dest: Path, cy: float) -> tuple[int, int]:
    font, st = R._load_font(SUB_PX), R.stroke_width_for(SUB_PX)
    img = Image.new("RGBA", (int(font.getlength(text)) + 4 * st + 8, int(SUB_PX * 1.5) + 2 * st), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((2 * st + 4, st), text, font=font, fill=(255, 255, 255, 255), stroke_width=st,
                             stroke_fill=(0, 0, 0, 255))
    img = img.crop(img.getbbox())
    img.save(dest)
    x, y = (W - img.width) // 2, int(H * cy - img.height / 2)
    if bad := check_box(W, H, (x, y, x + img.width, y + img.height)):
        raise SystemExit(f"субтитр вне безопасной зоны: {text} {bad}")
    return x, y


def build(hyp: str, key: str, out: Path, work: Path) -> Path:
    cfg = HYP[hyp]
    v = cfg[key]
    vo = cfg["dir"] / v["vo"]
    words = json.load(open(cfg["dir"] / "_words.json", encoding="utf-8"))[v["vo"]]
    subs = chunks(v["text"], words)
    import xmas_r3_common as XC
    src = XC.source(key)                                # V2 — очищенный от нижней подписи (LaMa)
    inputs, fc = [], []
    for i, (a, b, s0, s1) in enumerate(v["seg"]):
        nfr = round(b * FPS) - round(a * FPS)
        k = (nfr / FPS) / (s1 - s0)
        inputs += ["-ss", f"{s0:.3f}", "-t", f"{s1 - s0 + 0.15:.3f}", "-i", str(src)]
        fc.append(f"[{i}:v]setpts={k:.4f}*(PTS-STARTPTS),fps={FPS},scale={W}:{H}:flags=lanczos,setsar=1,"
                  f"trim=end_frame={nfr},setpts=PTS-STARTPTS[t{i}]")
    n = len(v["seg"])
    fc.append("".join(f"[t{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0,format=yuv420p[b0]")
    cur, idx = "b0", n
    tp = XC.title_png(key, work / f"{hyp}_{key}_title.png")
    if tp:                                              # V2: их заголовок — сверху
        inputs += ["-i", str(work / f"{hyp}_{key}_title.png")]
        fc.append(f"[{cur}][{idx}:v]overlay={tp[0]}:{tp[1]}[ti]")
        cur, idx = "ti", idx + 1
    for j, (a, b, text) in enumerate(subs):
        png = work / f"{hyp}_{key}_s{j:02d}.png"
        x, y = sub_png(text, png, SUB_Y[key])
        inputs += ["-i", str(png)]
        fc.append(f"[{cur}][{idx}:v]overlay={x}:{y}:enable='between(t,{a:.3f},{min(b, v['total']):.3f})'[o{j}]")
        cur, idx = f"o{j}", idx + 1
    inputs += ["-i", str(vo), "-stream_loop", "-1", "-i", str(MUSIC)]
    fc.append(f"[{idx}:a]aresample=44100,loudnorm=I=-15:TP=-1.5:LRA=11,apad[vo];[{idx + 1}:a]aresample=44100,volume=0.12[m];"
              f"[vo][m]amix=inputs=2:normalize=0:duration=first,atrim=0:{v['total']:.3f},"
              f"afade=t=out:st={v['total'] - 0.4:.3f}:d=0.4[a]")
    dest = out / f"{hyp}_{key}_noid.mp4"
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
                    "-map", f"[{cur}]", "-map", "[a]", "-t", f"{v['total']:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    for p in list(work.glob(f"{hyp}_{key}_s*.png")) + list(work.glob(f"{hyp}_{key}_title.png")):
        p.unlink()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hyp", required=True, choices=sorted(HYP))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", default="v1,v2,v3")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = ROOT / "output" / "_work" / "xmas_r3"
    work.mkdir(parents=True, exist_ok=True)
    for key in a.only.split(","):
        print("  ", build(a.hyp, key, a.out, work), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
