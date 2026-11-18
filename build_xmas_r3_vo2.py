#!/usr/bin/env python3
"""
Раунд 3 (docs/REPOST_HYPOTHESES.md), замены после отзыва юзера 2026-11-05 («лица другие, мимика не та; ИИ-пересъёмка
не масштабируется; озвучка топ»). Обе собираются автоматически из любого ролика + одной озвучки:

  --mode full    R3-3b «голос поверх ролика»: ролик на весь экран, перемонтирован под фразы озвучки;
                 чужая вшитая подпись закрыта НАШЕЙ плашкой-субтитром (белая, чёрный TikTok-текст) ровно поверх её полосы.
  --mode stills  R3-2b «стоп-кадры + голос»: те же фразы, но вместо движущегося видео — по стоп-кадру на фразу
                 с медленным наездом/отъездом (движущихся чужих кадров 0 с), та же плашка.
Звук: озвучка chipbot (downloads/xmas_proj/vo) + тихая музыка. Сегменты и субтитры — из build_xmas_r3_voice.VIDS.

  python build_xmas_r3_vo2.py --mode full   --out output/xmas_r3/R3-3b_vo_full
  python build_xmas_r3_vo2.py --mode stills --out output/xmas_r3/R3-2b_vo_stills
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_xmas_r3_voice as V  # noqa: E402  (VIDS: сегменты под фразы, субтитры, озвучка)
from core import renderer as R  # noqa: E402  (TikTok Sans)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
# полоса вшитой подписи в кадре 1080×1920 (x0, y0, x1, y1) с запасом — плашка её полностью закрывает
# замер: статичные белые пиксели во всех кадрах (V1 204–876×384–520, V2 68–1008×1276–1428, V3 108–888×440–556) + запас 30–40 px
BAND = {"v1": (168, 350, 912, 556), "v2": (36, 1244, 1044, 1462), "v3": (76, 408, 1004, 590)}
TXT_PX, TXT_MAX_W = 62, 740
ZMAX = 1.07                                          # наезд стоп-кадров


def wrap(text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        c = (cur + " " + w).strip()
        if cur and font.getlength(c) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = c
    return lines + [cur] if cur else lines


def plate_png(text: str, band: tuple, dest: Path) -> None:
    x0, y0, x1, y1 = band
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(band, radius=30, fill=(255, 255, 255, 255))
    font = R._load_font(TXT_PX)
    lines = wrap(text, font, min(TXT_MAX_W, x1 - x0 - 80))
    adv = int(TXT_PX * 1.22)
    th = adv * len(lines)
    cx, ty = (x0 + x1) / 2, (y0 + y1) / 2 - th / 2
    for ln in lines:
        lw = font.getlength(ln)
        tx = cx - lw / 2
        d.text((tx, ty), ln, font=font, fill=(0, 0, 0, 255))
        if bad := check_box(W, H, (int(tx), int(ty), int(tx + lw), int(ty + adv))):
            raise SystemExit(f"текст плашки вне безопасной зоны: {text} {bad}")
        ty += adv
    img.save(dest)


def build(key: str, mode: str, out: Path, work: Path) -> Path:
    v = V.VIDS[key]
    total = v["total"]
    src = V.SRC / v["src"]
    inputs, fc = [], []
    for i, (a, b, s0, s1, _yf) in enumerate(v["top"]):
        dur = b - a
        if mode == "full":
            inputs += ["-ss", f"{s0:.3f}", "-t", f"{s1 - s0:.3f}", "-i", str(src)]
            k = dur / (s1 - s0)
            fc.append(f"[{i}:v]setpts={k:.4f}*(PTS-STARTPTS),fps={FPS},scale={W}:{H}:flags=lanczos,setsar=1,"
                      f"trim=duration={dur:.3f},setpts=PTS-STARTPTS[t{i}]")
        else:                                            # стоп-кадр из середины куска + медленный наезд/отъезд
            tm = s0 + (s1 - s0) * 0.5
            inputs += ["-ss", f"{tm:.3f}", "-i", str(src)]
            n = int(round(dur * FPS))
            z0, z1 = (1.0, ZMAX) if i % 2 == 0 else (ZMAX, 1.0)
            fc.append(f"[{i}:v]trim=end_frame=1,scale={W * 2}:{H * 2}:flags=lanczos,setsar=1,"
                      f"zoompan=z='{z0}+({z1}-{z0})*on/{max(1, n - 1)}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                      f"d={n}:s={W}x{H}:fps={FPS},trim=duration={dur:.3f},setpts=PTS-STARTPTS[t{i}]")
    nt = len(v["top"])
    fc.append("".join(f"[t{i}]" for i in range(nt)) + f"concat=n={nt}:v=1:a=0,format=yuv420p[b0]")
    subs = v["subs"]
    band = BAND[key]
    if mode == "stills":                               # наезд до 1.07 от центра раздвигает подпись — плашка шире/выше
        z = ZMAX + 0.01
        xs = [W / 2 + (band[0] - W / 2) * z, W / 2 + (band[2] - W / 2) * z]
        ys = [H / 2 + (band[1] - H / 2) * zz for zz in (1.0, z)] + [H / 2 + (band[3] - H / 2) * zz for zz in (1.0, z)]
        band = (max(0, int(min(xs))), int(min(ys)), min(W, int(max(xs))), int(max(ys)))
    cur, idx = "b0", nt
    for k, (a, _b, text) in enumerate(subs):
        b = subs[k + 1][0] if k + 1 < len(subs) else total + 1      # без пустых промежутков: плашка всегда закрывает полосу
        png = work / f"{key}_{mode}_plate{k:02d}.png"
        plate_png(text, band, png)
        inputs += ["-i", str(png)]
        fc.append(f"[{cur}][{idx}:v]overlay=0:0:enable='between(t,{a if k else 0:.3f},{b:.3f})'[p{k}]")
        cur, idx = f"p{k}", idx + 1
    inputs += ["-i", str(V.VO / v["vo"]), "-stream_loop", "-1", "-i", str(V.MUSIC)]
    fc.append(f"[{idx}:a]aresample=44100,loudnorm=I=-15:TP=-1.5:LRA=11,apad[vo];"
              f"[{idx + 1}:a]aresample=44100,volume=0.10[m];[vo][m]amix=inputs=2:normalize=0:duration=first,"
              f"atrim=0:{total:.3f}[a]")
    tag = "R3-3b_vo_full" if mode == "full" else "R3-2b_vo_stills"
    dest = out / f"{tag}_{key}_noid.mp4"
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
                    "-map", f"[{cur}]", "-map", "[a]", "-t", f"{total:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    for p in work.glob(f"{key}_{mode}_plate*.png"):
        p.unlink()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("full", "stills"), required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", default="v1,v2,v3")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = ROOT / "output" / "_work" / "xmas_r3"
    work.mkdir(parents=True, exist_ok=True)
    for key in a.only.split(","):
        print("  ", build(key, a.mode, a.out, work), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
