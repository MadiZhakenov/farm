#!/usr/bin/env python3
"""
Раунд 3, гипотеза R3-3 «наш креатор + голос» (docs/REPOST_HYPOTHESES.md): сплит 9:16 —
сверху (1080×960) чужой товар, кроп без вшитых подписей, нарезка под фразы озвучки;
снизу (1080×960) реакции нашей девушки A (папка Влада, Face reactions/2), окна отсмотрены покадрово под смысл фразы;
по центру на шве — субтитры по словам (белый TikTok-шрифт с обводкой), текст = сценарий озвучки (не Whisper),
тайминг — Whisper по словам. Звук: озвучка chipbot (downloads/xmas_proj/vo/vo_vN.mp3) + тихая музыка.

  python build_xmas_r3_voice.py --out output/xmas_r3/R3-3_voice
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_drops_band_reels as BR  # noqa: E402  (text_png: белый текст с чёрной обводкой)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS, HALF = 1080, 1920, 30, 960
SRC = ROOT / "downloads" / "xmas_proj" / "src"
FACE = ROOT / "downloads" / "skinive" / "vlad" / "Face reactions" / "2"
VO = ROOT / "downloads" / "xmas_proj" / "vo"
MUSIC = ROOT / "downloads" / "1303" / "music" / "gZIrKXCzue8.m4a"

# top: (VO_начало, VO_конец, src_начало, src_конец, y_кропа) — кусок исходника растягивается на фразу;
# кроп 720×640 из 720×1280 начиная с доли y (ниже/выше вшитых подписей)
# face: (клип, начало, длительность) подряд — сумма = длина ролика
VIDS = {
    "v1": dict(src="DcNWKlfAbOo.mp4", vo="vo_v1.mp3", total=12.55,
               top=[(0.0, 2.26, 0.0, 2.3, 0.29), (2.26, 4.2, 2.6, 4.5, 0.30), (4.2, 5.33, 4.9, 6.2, 0.30),
                    (5.33, 7.7, 6.6, 8.65, 0.28), (7.7, 9.73, 10.55, 12.45, 0.28), (9.73, 12.55, 12.6, 14.85, 0.28)],
               face=[("IMG_5724", 0.2, 2.26), ("IMG_5721", 2.95, 1.6), ("IMG_5726", 5.7, 1.44),
                     ("IMG_5729", 4.1, 3.4), ("IMG_5721", 5.95, 1.03), ("IMG_5722", 3.3, 1.85), ("IMG_5728", 1.55, 0.97)],
               subs=[(0.0, 1.08, "So my mom went"), (1.08, 2.26, "to Costco for milk…"), (2.26, 3.6, "and came back with"),
                     (3.6, 4.2, "THIS."), (4.2, 5.3, "It's a projector."), (5.36, 6.58, "And now Santa's sleigh"),
                     (6.58, 7.8, "literally flies around"), (7.8, 9.7, "our living room every night."),
                     (9.76, 10.78, "My dad already"), (10.78, 12.4, "wants a second one.")]),
    "v2": dict(src="DdGwGMEx-Uj.mp4", vo="vo_v2.mp3", total=12.55,
               top=[(0.0, 2.6, 0.0, 2.65, 0.10), (2.6, 4.15, 2.8, 4.85, 0.14), (4.15, 5.5, 5.0, 6.5, 0.16),
                    (5.5, 6.5, 7.35, 8.45, 0.16), (6.5, 7.8, 8.55, 9.35, 0.08), (7.8, 10.7, 9.42, 11.55, 0.22),
                    (10.7, 12.55, 11.65, 13.2, 0.22)],
               face=[("IMG_5724", 0.2, 4.15), ("IMG_5721", 2.95, 1.7), ("IMG_5729", 4.1, 1.95),
                     ("IMG_5729", 6.05, 1.5), ("IMG_5726", 5.75, 1.35), ("IMG_5728", 1.5, 1.9)],
               subs=[(0.0, 0.84, "Okay,"), (0.84, 1.94, "do NOT show this"), (1.94, 3.2, "to anyone obsessed"),
                     (3.2, 4.14, "with Christmas."), (4.16, 5.5, "You plug this little tree"), (5.5, 6.5, "into the wall,"),
                     (6.5, 7.8, "turn off the lights…"), (7.8, 8.74, "and your whole ceiling"),
                     (8.74, 10.7, "turns into a snowstorm."), (10.7, 12.4, "My mom bought three.")]),
    "v3": dict(src="DdZ5O2bR39c.mp4", vo="vo_v3.mp3", total=9.85,
               top=[(0.0, 4.74, 0.0, 3.5, 0.30), (4.74, 5.6, 3.6, 4.38, 0.30), (5.6, 6.56, 5.15, 6.15, 0.30),
                    (6.56, 9.85, 7.3, 10.2, 0.30)],
               face=[("IMG_5723", 0.1, 2.0), ("IMG_5723", 3.7, 2.74), ("IMG_5721", 2.95, 1.82), ("IMG_5729", 4.1, 3.29)],
               subs=[(0.0, 1.18, "Last year, my husband"), (1.18, 2.18, "tried to fix"), (2.18, 3.56, "the tree topper himself…"),
                     (3.56, 4.74, "and the tree won."), (4.74, 5.6, "This year, we just"), (5.6, 6.56, "plugged this in,"),
                     (6.56, 7.8, "and the kids haven't"), (7.8, 9.7, "left the living room since.")]),
}
SUB_PX = 72


def sub_png(text: str, dest: Path) -> tuple[int, int]:
    BR.STROKE = 0.09
    BR.text_png([text], SUB_PX, dest, False)
    im = Image.open(dest)
    x, y = (W - im.width) // 2, HALF - im.height // 2
    if bad := check_box(W, H, (x + 8, y + 8, x + im.width - 8, y + im.height - 8)):
        raise SystemExit(f"субтитр вне безопасной зоны: {text} {bad}")
    return x, y


_FACE_Y: dict = {}


def face_cy(clip: str, s0: float, d: float) -> float:
    """Центр лица по высоте (доля кадра 9:16) — Haar по 3 кадрам окна; нужен, чтобы глаза в нижней половине
    стояли на ~0.7 H, а не уходили под подпись TikTok у самого низа."""
    key = (clip, s0, d)
    if key in _FACE_Y:
        return _FACE_Y[key]
    import cv2
    import numpy as np
    det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    ys = []
    for t in (s0 + d * 0.2, s0 + d * 0.5, s0 + d * 0.8):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(FACE / f"{clip}.MOV"), "-frames:v", "1",
                              "-vf", "scale=360:640", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
        if len(raw) < 360 * 640:
            continue
        g = np.frombuffer(raw[:360 * 640], np.uint8).reshape(640, 360)
        f = det.detectMultiScale(g, 1.1, 5, minSize=(80, 80))
        if len(f):
            x, y, w, h = max(f, key=lambda r: r[2] * r[3])
            ys.append((y + h * 0.45) / 640)               # линия глаз ≈ 0.45 высоты рамки лица
    cy = float(np.median(ys)) if ys else 0.36
    _FACE_Y[key] = cy
    return cy


def build(key: str, out: Path, work: Path) -> Path:
    v = VIDS[key]
    total = v["total"]
    assert abs(sum(f[2] for f in v["face"]) - total) < 0.02, (key, sum(f[2] for f in v["face"]))
    inputs, fc = [], []
    # верх: куски исходника, растянутые на фразы
    src = SRC / v["src"]
    for i, (a, b, s0, s1, yf) in enumerate(v["top"]):
        inputs += ["-ss", f"{s0:.3f}", "-t", f"{s1 - s0:.3f}", "-i", str(src)]
        k = (b - a) / (s1 - s0)
        fc.append(f"[{i}:v]setpts={k:.4f}*(PTS-STARTPTS),fps={FPS},crop=iw:iw*8/9:0:ih*{yf},scale={W}:{HALF}:flags=lanczos,"
                  f"setsar=1,trim=duration={b - a:.3f},setpts=PTS-STARTPTS[t{i}]")
    nt = len(v["top"])
    fc.append("".join(f"[t{i}]" for i in range(nt)) + f"concat=n={nt}:v=1:a=0[top]")
    # низ: реакции — кроп 1080×960 из 9:16 так, чтобы линия глаз была на ~0.70 H
    base = len(inputs) // 6
    for j, (clip, s0, d) in enumerate(v["face"]):
        inputs += ["-ss", f"{s0:.3f}", "-t", f"{d + 0.1:.3f}", "-i", str(FACE / f"{clip}.MOV")]
        yoff = min(0.5, max(0.0, face_cy(clip, s0, d) - 0.40 * 0.5))   # глаза на 0.40 нижней половины ≈ 0.70 H
        fc.append(f"[{base + j}:v]fps={FPS},scale={W}:-2:flags=lanczos,crop={W}:{HALF}:0:ih*{yoff:.3f},setsar=1,"
                  f"trim=duration={d:.3f},setpts=PTS-STARTPTS[f{j}]")
    nf = len(v["face"])
    fc.append("".join(f"[f{j}]" for j in range(nf)) + f"concat=n={nf}:v=1:a=0[bot]")
    fc.append("[top][bot]vstack=inputs=2,format=yuv420p[st]")
    # субтитры
    cur = "st"
    idx = base + nf
    for k, (a, b, text) in enumerate(v["subs"]):
        png = work / f"{key}_sub{k:02d}.png"
        x, y = sub_png(text, png)
        inputs += ["-i", str(png)]
        fc.append(f"[{cur}][{idx}:v]overlay={x}:{y}:enable='between(t,{a:.3f},{b:.3f})'[s{k}]")
        cur = f"s{k}"
        idx += 1
    inputs += ["-i", str(VO / v["vo"]), "-stream_loop", "-1", "-i", str(MUSIC)]
    fc.append(f"[{idx}:a]aresample=44100,loudnorm=I=-15:TP=-1.5:LRA=11,apad[vo];"
              f"[{idx + 1}:a]aresample=44100,volume=0.10[m];[vo][m]amix=inputs=2:normalize=0:duration=first,"
              f"atrim=0:{total:.3f}[a]")
    dest = out / f"R3-3_voice_{key}_noid.mp4"
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
                    "-map", f"[{cur}]", "-map", "[a]", "-t", f"{total:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    for p in work.glob(f"{key}_sub*.png"):
        p.unlink()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "xmas_r3" / "R3-3_voice")
    ap.add_argument("--only", default="v1,v2,v3")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = ROOT / "output" / "_work" / "xmas_r3"
    work.mkdir(parents=True, exist_ok=True)
    for key in a.only.split(","):
        print("  ", build(key, a.out, work), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
