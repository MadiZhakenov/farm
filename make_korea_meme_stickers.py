"""Korea OneState 1 (мем-версия): мемы Tenor → готовые стикеры 3.4 с (RGBA .mov): чёрные поля обрезаны, скруглённые
углы, белая рамка, мягкая тень, «выскакивание» 0.55→1.08→1.0 за 5 кадров и сжатие в конце (как мем-бум в Drops).
  python make_korea_meme_stickers.py   → downloads/korea_onestate1/memes/sticker/<момент>.mov"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent
D = ROOT / "downloads" / "korea_onestate1" / "memes"
PICK = json.loads((D / "pick" / "_pick.json").read_text(encoding="utf-8"))
OUT = D / "sticker"
FPS, DUR, MAXS, BORDER, RAD = 30, 3.4, 560, 10, 30
POP_IN = [0.55, 0.85, 1.08, 1.03, 1.0]
POP_OUT = [0.92, 0.7, 0.42, 0.12]


def frames(p: Path) -> list[np.ndarray]:
    w, h = map(int, subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "stream=width,height", "-of", "csv=p=0", str(p)], capture_output=True,
                                   text=True).stdout.strip().split(",")[:2])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vf", f"fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-"], capture_output=True).stdout
    return list(np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3))


def trim_black(fr: list[np.ndarray]) -> tuple[int, int, int, int]:
    a = np.stack(fr[:: max(1, len(fr) // 12)]).astype(np.float32).mean(0).mean(2)
    rows = np.where(a.mean(1) > 14)[0]
    cols = np.where(a.mean(0) > 14)[0]
    return int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1


def card(img: Image.Image) -> Image.Image:
    """Мем → карточка: скругление, белая рамка, тень (на прозрачном поле с запасом под тень)."""
    w, h = img.size
    cw, ch = w + 2 * BORDER, h + 2 * BORDER
    pad = 28
    out = Image.new("RGBA", (cw + 2 * pad, ch + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("L", out.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((pad, pad + 8, pad + cw, pad + ch + 8), RAD + BORDER, fill=110)
    out.putalpha(sh.filter(ImageFilter.GaussianBlur(12)))
    out = Image.composite(Image.new("RGBA", out.size, (0, 0, 0, 255)), Image.new("RGBA", out.size, (0, 0, 0, 0)),
                          sh.filter(ImageFilter.GaussianBlur(12)))
    white = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(white).rounded_rectangle((0, 0, cw - 1, ch - 1), RAD + BORDER, fill=255)
    out.paste(Image.new("RGBA", (cw, ch), (255, 255, 255, 255)), (pad, pad), white)
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), RAD, fill=255)
    out.paste(img.convert("RGBA"), (pad + BORDER, pad + BORDER), m)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {}
    for key in PICK:
        src = D / "pick" / f"{key}.mp4"
        fr = frames(src)
        y0, y1, x0, x1 = trim_black(fr)
        fr = [f[y0:y1, x0:x1] for f in fr]
        h, w = fr[0].shape[:2]
        s = MAXS / max(w, h)
        w2, h2 = round(w * s / 2) * 2, round(h * s / 2) * 2
        n = round(DUR * FPS)
        cards = []
        for i in range(n):
            im = Image.fromarray(fr[i % len(fr)]).resize((w2, h2), Image.Resampling.LANCZOS)
            cards.append(card(im))
        cw, ch = cards[0].size
        big = (round(cw * 1.1 / 2) * 2, round(ch * 1.1 / 2) * 2)          # холст под «выскакивание» ×1.08
        tmp = OUT / f"_{key}"
        tmp.mkdir(exist_ok=True)
        for i, c in enumerate(cards):
            k = POP_IN[i] if i < len(POP_IN) else POP_OUT[i - (n - len(POP_OUT))] if i >= n - len(POP_OUT) else 1.0
            canvas = Image.new("RGBA", big, (0, 0, 0, 0))
            cc = c.resize((max(2, round(cw * k)), max(2, round(ch * k))), Image.Resampling.BICUBIC)
            canvas.alpha_composite(cc, ((big[0] - cc.width) // 2, (big[1] - cc.height) // 2))
            canvas.save(tmp / f"{i:04d}.png", compress_level=1)
        dest = OUT / f"{key}.mov"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", str(tmp / "%04d.png"), "-c:v", "qtrle",
                        "-pix_fmt", "argb", str(dest)], check=True)
        for p in tmp.glob("*.png"):
            p.unlink()
        tmp.rmdir()
        meta[key] = dict(w=big[0], h=big[1], frames=n)
        print(key, big, f"кадров {len(fr)} исходника", flush=True)
    (OUT / "_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
