"""Assemble ref-cat shots (rendered PNG frames) into a 9:16 clip with ref-style subtitles and pop-ups.
  python lowpoly/refcat_compose.py OUT.mp4 [--audio file] [--until SECONDS]
Subtitles: yellow Courier Prime Bold, thin black outline, centre y = 66 % (inside the 9:16 safe zone y 200-1540).
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FARM = Path(__file__).resolve().parent.parent
import os
ANIM = Path(os.environ.get("ANIM_DIR", str(FARM / "output/_work/lowpoly/ref_cat/anim")))
FONT = FARM / "fonts/courierprime/CourierPrime-Bold.ttf"
W, H, FPS = 1080, 1920, 30

SHOTS = ["s1", "s2", "s3", "s4", "s5"]                 # rendered so far, in order
SUBS = [("if your cat keeps", 0.00), ("staring at you", 0.74), ("up close", 1.44), ("it's probably", 2.08),
        ("just trying to", 2.54), ("get your attention", 3.28), ("but if it's staring", 4.08),
        ("from across the room", 4.78), ("it's actually", 5.92), ("checking", 6.40), ("for threats", 6.84)]
POPS = [("!", 3.60, 4.10, (330, 720), 230)]            # text, start, end, centre xy, size


def text_png(txt, size, fill, path, stroke=4):
    f = ImageFont.truetype(str(FONT), size)
    im = Image.new("RGBA", (W, int(size * 1.6)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    tw = d.textlength(txt, font=f)
    d.text(((W - tw) / 2, size * 0.25), txt, font=f, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    im.save(path)
    return im.size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--audio")
    ap.add_argument("--until", type=float, default=None)
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp())
    lst = tmp / "frames.txt"
    n = 0
    with open(lst, "w", encoding="utf-8") as fh:
        for s in SHOTS:
            for p in sorted((ANIM / s).glob("f_*.png")):
                fh.write(f"file '{p.as_posix()}'\nduration {1 / FPS:.6f}\n")
                n += 1
    dur = n / FPS if a.until is None else min(a.until, n / FPS)
    inputs, filt, last = ["-f", "concat", "-safe", "0", "-i", str(lst)], [], "0:v"
    filt.append(f"[0:v]fps={FPS},scale={W}:{H}:flags=bilinear,setsar=1[v0]")
    last = "v0"
    k = 1
    subs = [(t, s) for t, s in SUBS if s < dur]
    for i, (txt, st) in enumerate(subs):
        en = subs[i + 1][1] if i + 1 < len(subs) else dur
        p = tmp / f"sub{i}.png"
        _, h = text_png(txt, 80, (250, 232, 40, 255), p, stroke=5)
        inputs += ["-i", str(p)]
        y = int(H * 0.66 - h / 2)
        filt.append(f"[{last}][{k}:v]overlay=0:{y}:enable='between(t,{st:.3f},{en - 0.001:.3f})'[v{k}]")
        last, k = f"v{k}", k + 1
    for txt, st, en, (cx, cy), size in POPS:
        if st >= dur:
            continue
        p = tmp / f"pop{k}.png"
        _, h = text_png(txt, size, (220, 20, 30, 255), p, stroke=8)
        inputs += ["-i", str(p)]
        filt.append(f"[{last}][{k}:v]overlay={cx - W // 2}:{cy - h // 2}:enable='between(t,{st:.3f},{en:.3f})'[v{k}]")
        last, k = f"v{k}", k + 1
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs]
    if a.audio:
        cmd += ["-i", a.audio]
    cmd += ["-filter_complex", ";".join(filt), "-map", f"[{last}]"]
    if a.audio:
        cmd += ["-map", f"{k}:a", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-t", f"{dur:.3f}", "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "23", "-pix_fmt", "yuv420p",
            "-map_metadata", "-1", "-fflags", "+bitexact", a.out]
    subprocess.run(cmd, check=True)
    print("OUT", a.out, f"{dur:.2f}s", n, "frames")


if __name__ == "__main__":
    main()
