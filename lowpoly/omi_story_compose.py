"""Assemble the 'Elevator cable' short: PSX post per shot -> concat -> subtitles + graphics -> VO.
  python lowpoly/omi_story_compose.py OUT.mp4
Subtitles: 2-3 words from the VO word times (yellow mono with black outline, Mr omi / ref style), at y = 66 %
(inside the 9:16 safe frame, core/safe_zones.py). Big graphics: '-10 km/h', cable counter, '1854'.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FARM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FARM))
from core.safe_zones import check_box  # noqa: E402

STORY = FARM / "output/_work/lowpoly/omi/story"
VO = FARM / "downloads/omi_story/vo.mp3"
WORDS = json.load(open(FARM / "downloads/omi_story/words.json"))
FONT = FARM / "fonts/courierprime/CourierPrime-Bold.ttf"
W, H, FPS = 1080, 1920, 30
SHOTS = ["s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08", "s09", "s10", "s11", "s12"]
# big graphics: text, start, end, centre y, size, colour
GFX = [("-10 km/h", 7.1, 9.1, 0.36, 150, (250, 232, 40)),
       ("1854", 22.2, 24.0, 0.30, 230, (250, 232, 40))]
COUNTER = [(t, str(i + 1)) for i, t in enumerate((16.54, 16.85, 17.14, 17.3, 17.45, 17.6, 17.75, 17.9))]


def phrases():
    """group words into 2-3 word captions, break on punctuation."""
    out, cur = [], []
    for w, a, b in WORDS:
        cur.append((w, a, b))
        if len(cur) == 3 or re.search(r"[,.!?]$", w) or (len(cur) == 2 and len(w) > 7):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    res = []
    for i, ph in enumerate(out):
        txt = " ".join(re.sub(r"[,.!?]", "", w) for w, _, _ in ph).lower()
        st = ph[0][1]
        en = out[i + 1][0][1] if i + 1 < len(out) else ph[-1][2] + 0.4
        res.append((txt, st, en))
    return res


def text_png(txt, size, fill, path, stroke):
    f = ImageFont.truetype(str(FONT), size)
    im = Image.new("RGBA", (W, int(size * 1.5)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    tw = d.textlength(txt, font=f)
    x = (W - tw) / 2
    d.text((x, size * 0.2), txt, font=f, fill=(*fill, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    im.save(path)
    return x, tw, im.size[1]


def main():
    out = Path(sys.argv[1])
    tmp = Path(tempfile.mkdtemp())
    post = tmp / "post"
    for s in SHOTS:
        subprocess.run([sys.executable, str(FARM / "lowpoly/psx_post.py"), str(STORY / s), str(post / s)], check=True)
    lst = tmp / "frames.txt"
    with open(lst, "w") as fh:
        for s in SHOTS:
            for p in sorted((post / s).glob("f_*.png")):
                fh.write(f"file '{p.as_posix()}'\nduration {1 / FPS:.6f}\n")
    inputs = ["-f", "concat", "-safe", "0", "-i", str(lst)]
    filt, last, k = ["[0:v]fps=30,setsar=1[v0]"], "v0", 1
    items = [(t, a, b, 0.66, 66, (250, 232, 40), 5) for t, a, b in phrases()]
    items += [(t, a, b, y, sz, c, 9) for t, a, b, y, sz, c in GFX]
    for i, (t, a) in enumerate(COUNTER):
        b = COUNTER[i + 1][0] if i + 1 < len(COUNTER) else 18.5
        items.append((a, t, b, 0.30, 220, (250, 232, 40), 9))
    for txt, a, b, yc, sz, col, stroke in items:
        p = tmp / f"t{k}.png"
        x, tw, h = text_png(txt, sz, col, p, stroke)
        y = int(H * yc - h / 2)
        bad = check_box(W, H, (int(x), y + int(sz * 0.2), int(x + tw), y + int(sz * 1.2)))
        if bad:
            print("SAFE ZONE", repr(txt), bad)
        inputs += ["-i", str(p)]
        filt.append(f"[{last}][{k}:v]overlay=0:{y}:enable='between(t,{a:.3f},{b - 0.001:.3f})'[v{k}]")
        last, k = f"v{k}", k + 1
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-i", str(VO), "-filter_complex", ";".join(filt),
           "-map", f"[{last}]", "-map", f"{k}:a", "-c:v", "h264_nvenc", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", "-map_metadata", "-1", str(out)]
    subprocess.run(cmd, check=True)
    print("OUT", out)


if __name__ == "__main__":
    main()
