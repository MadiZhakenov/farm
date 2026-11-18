#!/usr/bin/env python3
"""
Раунд 3 (docs/REPOST_HYPOTHESES.md) — монтаж «под удержание» с озвучкой юзера (после отзыва 2026-11-05: белая плашка
огромная и неэстетичная; «с каждой секундой должен быть ризон смотреть дальше»).

  - чужая вшитая подпись убрана КАДРИРОВАНИЕМ: кадр 9:16 вырезан из части исходника без полосы подписи
    (подпись сверху → кроп снизу, снизу → кроп сверху), апскейл lanczos + лёгкая резкость; без плашек и размытия;
  - 0–1 с самый сильный кадр (вау/юмор), склейки ~1 с, чередование крупности (punch-in 1.00/1.10);
  - звук: озвучка + тихая музыка + свои эффекты — «вжух» на склейках, нарастание перед раскрытием,
    удар на раскрытии (проекция), «дзынь» на финальной шутке;
  - субтитры 1–3 слова белым TikTok-шрифтом с обводкой, ключевые слова жёлтым, ниже центра.

  python build_xmas_r3_retention.py --only v2 --out output/xmas_r3/_t_ret
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import renderer as R  # noqa: E402
from core.safe_zones import check_box  # noqa: E402

W, H, FPS, SR = 1080, 1920, 30, 44100
SRC = ROOT / "downloads" / "xmas_proj" / "src"
VO = ROOT / "downloads" / "xmas_proj" / "vo"
MUSIC = ROOT / "downloads" / "1303" / "music" / "gZIrKXCzue8.m4a"
YELLOW = (255, 224, 64, 255)

# полоса вшитой подписи (доли высоты исходника) и где она есть по времени исходника
CAP = {"v1": ("top", 0.285, None), "v2": ("bottom", 0.655, 9.3), "v3": ("top", 0.30, 10.25)}
# сегменты: (VO от, VO до, src от, src до, фокус x (0..1), punch 1.0|1.1)
VIDS = {
    "v1": dict(src="DcNWKlfAbOo.mp4", vo="vo_v1.mp3", total=12.55, reveal=5.36, riser=None, ding=11.3,
               seg=[(0.0, 1.1, 0.25, 1.35, 0.32, 1.0), (1.1, 2.26, 1.35, 2.6, 0.42, 1.1), (2.26, 3.3, 2.7, 3.8, 0.5, 1.0),
                    (3.3, 4.2, 3.8, 4.7, 0.5, 1.1), (4.2, 5.33, 4.85, 6.35, 0.5, 1.0), (5.33, 6.5, 6.6, 7.8, 0.45, 1.0),
                    (6.5, 7.8, 8.75, 10.0, 0.45, 1.1), (7.8, 9.73, 10.55, 12.45, 0.45, 1.0), (9.73, 11.0, 12.6, 13.9, 0.45, 1.1),
                    (11.0, 12.55, 7.0, 8.55, 0.45, 1.0)],
               subs=[(0.0, 0.58, "So my mom"), (0.58, 1.26, "went to"), (1.26, 2.26, "*Costco* for milk…"),
                     (2.26, 3.6, "and came back with"), (3.6, 4.2, "*THIS.*"), (4.2, 5.33, "It's a projector."),
                     (5.36, 6.58, "And now *Santa's sleigh*"), (6.58, 7.8, "literally flies around"),
                     (7.8, 8.68, "our living room"), (8.68, 9.73, "every night."), (9.76, 10.78, "My dad already"),
                     (10.78, 12.55, "wants a *second one.*")]),
    "v2": dict(src="DdGwGMEx-Uj.mp4", vo="vo_v2.mp3", total=12.55, reveal=7.85, riser=(6.55, 7.85), ding=11.2, boom0=True,
               seg=[(0.0, 0.84, 9.5, 10.34, 0.5, 1.0), (0.84, 1.94, 0.3, 1.6, 0.45, 1.0), (1.94, 2.6, 1.6, 2.65, 0.45, 1.1),
                    (2.6, 4.14, 2.75, 4.3, 0.5, 1.0), (4.14, 5.5, 5.0, 6.4, 0.5, 1.1), (5.5, 6.5, 7.35, 8.4, 0.55, 1.0),
                    (6.5, 7.8, 8.5, 9.32, 0.6, 1.1), (7.8, 9.2, 9.4, 10.5, 0.5, 1.0), (9.2, 10.7, 10.5, 11.58, 0.5, 1.1),
                    (10.7, 12.55, 11.62, 13.2, 0.5, 1.0)],
               subs=[(0.0, 0.84, "Okay,"), (0.84, 1.94, "do *NOT* show this"), (1.94, 3.2, "to anyone obsessed"),
                     (3.2, 4.14, "with *Christmas.*"), (4.16, 5.5, "You plug this little tree"), (5.5, 6.5, "into the wall,"),
                     (6.5, 7.8, "turn off the lights…"), (7.8, 8.74, "and your whole ceiling"),
                     (8.74, 10.7, "turns into a *snowstorm.*"), (10.7, 12.55, "My mom bought *three.*")]),
    "v3": dict(src="DdZ5O2bR39c.mp4", vo="vo_v3.mp3", total=9.85, reveal=6.6, riser=(5.6, 6.6), ding=3.9, boom0=False,
               seg=[(0.0, 1.18, 0.9, 2.4, 0.5, 1.0), (1.18, 2.18, 2.4, 3.4, 0.55, 1.1), (2.18, 3.56, 2.6, 3.5, 0.55, 1.0),
                    (3.56, 4.74, 2.95, 3.5, 0.6, 1.1), (4.74, 5.6, 3.6, 4.38, 0.5, 1.0), (5.6, 6.56, 5.15, 6.15, 0.55, 1.1),
                    (6.56, 7.8, 7.3, 8.5, 0.5, 1.0), (7.8, 9.85, 8.5, 10.2, 0.5, 1.1)],
               subs=[(0.0, 1.18, "Last year, my husband"), (1.18, 2.18, "tried to fix"), (2.18, 2.9, "the tree topper"), (2.9, 3.56, "himself…"),
                     (3.56, 4.74, "and *the tree won.*"), (4.74, 5.6, "This year, we just"), (5.6, 6.56, "plugged this in,"),
                     (6.56, 7.8, "and the kids haven't"), (7.8, 8.8, "left the living room"), (8.8, 9.85, "*since.*")]),
}
SUB_PX, SUB_Y = 76, 0.66


def src_wh(p: Path) -> tuple[int, int]:
    o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip().split(",")
    return int(o[0]), int(o[1])


def crop_box(key: str, s0: float, fx: float, punch: float, sw: int, sh: int) -> tuple[int, int, int, int]:
    """Кроп 9:16 без полосы подписи. Подпись сверху — берём низ кадра, снизу — верх; вне времени подписи — весь кадр."""
    side, edge, until = CAP[key]
    if until is not None and s0 >= until:
        ch = sh / punch
        y = (sh - ch) / 2
    elif side == "top":
        ch = sh * (1 - edge) / punch
        y = sh - ch
    else:
        ch = sh * edge / punch
        y = 0
    cw = ch * 9 / 16
    x = min(max(0, fx * sw - cw / 2), sw - cw)
    return int(cw) // 2 * 2, int(ch) // 2 * 2, int(x), int(y)


def sub_png(text: str, dest: Path) -> tuple[int, int]:
    """Белый TikTok-текст с чёрной обводкой; *слово* — жёлтым."""
    font = R._load_font(SUB_PX)
    st = R.stroke_width_for(SUB_PX)
    parts, hl = [], False
    for chunk in text.split("*"):
        if chunk:
            parts.append((chunk, hl))
        hl = not hl
    tw = sum(font.getlength(c) for c, _ in parts)
    img = Image.new("RGBA", (int(tw) + 4 * st + 8, int(SUB_PX * 1.5) + 2 * st), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = 2 * st + 4
    for c, h in parts:
        d.text((x, st), c, font=font, fill=YELLOW if h else (255, 255, 255, 255), stroke_width=st,
               stroke_fill=(0, 0, 0, 255))
        x += font.getlength(c)
    img = img.crop(img.getbbox())
    img.save(dest)
    px, py = (W - img.width) // 2, int(H * SUB_Y - img.height / 2)
    if bad := check_box(W, H, (px, py, px + img.width, py + img.height)):
        raise SystemExit(f"субтитр вне безопасной зоны: {text} {bad}")
    return px, py


def sfx_track(v: dict, dest: Path) -> None:
    total = v["total"]
    mix = np.zeros(int(SR * (total + 1)), np.float32)
    rng = np.random.default_rng(3)

    def add(t: float, snd: np.ndarray) -> None:
        i = int(t * SR)
        n = min(len(snd), len(mix) - i)
        if n > 0:
            mix[i:i + n] += snd[:n]

    def whoosh(d=0.22, vol=0.16):
        n = int(SR * d)
        x = np.convolve(rng.normal(size=n), np.ones(24) / 24, mode="same")
        return (x * np.sin(np.linspace(0, np.pi, n)) ** 2 * vol * 4).astype(np.float32)

    def boom(d=0.9, vol=0.55):
        t = np.arange(int(SR * d)) / SR
        f = 70 * np.exp(-t * 3) + 38
        ph = 2 * np.pi * np.cumsum(f) / SR
        return (np.sin(ph) * np.exp(-t * 4.5) * vol).astype(np.float32)

    def riser(d, vol=0.18):
        t = np.arange(int(SR * d)) / SR
        f = 220 + 900 * (t / d) ** 2
        ph = 2 * np.pi * np.cumsum(f) / SR
        noise = np.convolve(rng.normal(size=len(t)), np.ones(8) / 8, mode="same") * 0.5
        return ((np.sin(ph) * 0.5 + noise) * (t / d) ** 1.5 * vol).astype(np.float32)

    def ding(vol=0.28):
        t = np.arange(int(SR * 0.8)) / SR
        return ((np.sin(2 * np.pi * 1568 * t) + 0.5 * np.sin(2 * np.pi * 2352 * t)) * np.exp(-t * 6) * vol).astype(np.float32)

    for seg in v["seg"][1:]:
        add(max(0, seg[0] - 0.08), whoosh())
    if v.get("boom0"):
        add(0.0, boom())
    if v.get("riser"):
        a, b = v["riser"]
        add(a, riser(b - a))
    add(v["reveal"], boom())
    add(v["ding"], ding())
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())


def build(key: str, out: Path, work: Path) -> Path:
    v = VIDS[key]
    total = v["total"]
    src = SRC / v["src"]
    sw, sh = src_wh(src)
    inputs, fc = [], []
    for i, (a, b, s0, s1, fx, punch) in enumerate(v["seg"]):
        cw, ch, x, y = crop_box(key, s0, fx, punch, sw, sh)
        inputs += ["-ss", f"{s0:.3f}", "-t", f"{s1 - s0 + 0.15:.3f}", "-i", str(src)]   # запас: trim режет ровно
        nfr = round(b * FPS) - round(a * FPS)             # границы по сетке кадров — без накопленного сдвига
        k = (nfr / FPS) / (s1 - s0)
        fc.append(f"[{i}:v]setpts={k:.4f}*(PTS-STARTPTS),fps={FPS},crop={cw}:{ch}:{x}:{y},"
                  f"scale={W}:{H}:flags=lanczos,unsharp=5:5:0.7:5:5:0.0,setsar=1,"
                  f"trim=end_frame={nfr},setpts=PTS-STARTPTS[t{i}]")
    n = len(v["seg"])
    fc.append("".join(f"[t{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0,format=yuv420p[b0]")
    cur, idx = "b0", n
    for k, (a, b, text) in enumerate(v["subs"]):
        png = work / f"ret_{key}_s{k:02d}.png"
        px, py = sub_png(text, png)
        inputs += ["-i", str(png)]
        fc.append(f"[{cur}][{idx}:v]overlay={px}:{py}:enable='between(t,{a:.3f},{b:.3f})'[o{k}]")
        cur, idx = f"o{k}", idx + 1
    wav = work / f"ret_{key}_sfx.wav"
    sfx_track(v, wav)
    inputs += ["-i", str(VO / v["vo"]), "-i", str(wav), "-stream_loop", "-1", "-i", str(MUSIC)]
    fc.append(f"[{idx}:a]aresample={SR},loudnorm=I=-15:TP=-1.5:LRA=11,apad[vo];[{idx + 1}:a]aresample={SR}[fx];"
              f"[{idx + 2}:a]aresample={SR},volume=0.10[m];[vo][fx][m]amix=inputs=3:normalize=0:duration=first,"
              f"alimiter=limit=0.95,atrim=0:{total:.3f}[a]")
    dest = out / f"R3-ret_{key}_noid.mp4"
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
                    "-map", f"[{cur}]", "-map", "[a]", "-t", f"{total:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    for p in work.glob(f"ret_{key}_s*.png"):
        p.unlink()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
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
