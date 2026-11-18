#!/usr/bin/env python3
"""
Колибри 5 (Idle Bank Tycoon, ID 1) — «I thought my boyfriend was cheating» 💀: storytime-карусель 8 слайдов ×100 (TikTok)
+ 150 видео YouTube из тех же слайдов. Схема build_kolibri4 (белый TikTok-шрифт с мягкой тенью, текст ТЗ дословно,
переносы по смыслу), все слайды — фото Flow: output/kolibri5/slides/s<k>/*.jpg (3:4).
Уникальность (урок skinive): у каждой карусели/видео своё сочетание кадров (4 на слайд), свой наезд 1.00–1.10 со сдвигом,
яркость/цвет/тепло и зерно; YouTube — другой seed, чем TikTok. Видео кодирует NVENC, слайды рисуются в 6 процессах.

  python build_kolibri5.py --test                      # 4 карусели + 4 видео → output/_work/kolibri5_test
  python build_kolibri5.py -n 100 --carousels          # → output/kolibri5_carousels_100 + плоско output/kolibri5_100
  python build_kolibri5.py -n 150 --video              # → output/kolibri5_YT_150
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_kolibri4 as K4  # noqa: E402  (caption — белый TikTok-текст с тенью; треки музыки)
import strip_jpeg_meta  # noqa: E402
from core.safe_zones import check_box  # noqa: E402

W = 1080
SL = ROOT / "output" / "kolibri5" / "slides"
WORK = ROOT / "output" / "_work" / "kolibri5"
TEXTS = [
    ("I genuinely thought my boyfriend", "was cheating on me for 3 weeks", "and the truth was somehow", "MORE embarrassing 😭"),
    ("He started hiding his phone", "every time I walked into the room.", "Like SIR???"),
    ("Then he started waking up at 3AM", "and whispering 'just one more'", "to himself 💀"),
    ("I asked who he was talking to", "and he said 'it's complicated' ...", "COMPLICATED HOW???"),
    ("Yesterday I finally caught him", "smiling at his phone and saying", "'she's doing so well' 😭"),
    ("I was fully prepared", "to end a 2-year relationship", "over this."),
    ("THE 'OTHER WOMAN'", "WAS A VIRTUAL BANK MANAGER", "IN HIS PHONE GAME."),
    ("I almost became single", "because this man is emotionally", "attached to a cartoon bank employee.", "I'm actually done 💀"),
]
# центр текста по высоте (доля кадра): стена над головой / футболка — мимо лиц, часов 3:07 и экрана игры
CY = {"c": [0.17, 0.18, 0.15, 0.62, 0.2, 0.36, 0.21, 0.16], "v": [0.19, 0.2, 0.18, 0.62, 0.21, 0.36, 0.22, 0.19]}
MUSIC = K4.MUSIC
DUR = [3.0, 2.6, 2.6, 2.6, 2.6, 2.3, 2.6, 3.2]          # секунд на слайд: успеть прочитать, ~21.5 с


def pools() -> list[list[Path]]:
    return [sorted((SL / f"s{k}").glob("*.jpg")) for k in range(1, 9)]


def plan(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    ps = [p for p in pools()]
    rows, seen = [], set()
    while len(rows) < n:
        pick = [rng.choice(p).name if p else None for p in ps]
        if tuple(pick) in seen:
            continue
        seen.add(tuple(pick))
        rows.append({"i": len(rows) + 1, "pick": pick, "seed": rng.randrange(1 << 30)})
    return rows


def photo(p: Path, w: int, h: int, rng: random.Random) -> Image.Image:
    """Фото под кадр: наезд 1.00–1.10 со сдвигом, яркость/контраст/цвет/тепло и лёгкое зерно — своё у каждого."""
    im = Image.open(p).convert("RGB")
    z = rng.uniform(1.0, 1.10)
    cw, ch = im.width / z, im.height / z
    x0, y0 = rng.uniform(0, im.width - cw), rng.uniform(0, im.height - ch)
    im = im.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch)))
    im = ImageOps.fit(im, (w, h), Image.Resampling.LANCZOS, centering=(rng.uniform(0.44, 0.56), 0.45))
    im = ImageEnhance.Brightness(im).enhance(rng.uniform(0.96, 1.05))
    im = ImageEnhance.Contrast(im).enhance(rng.uniform(0.96, 1.06))
    im = ImageEnhance.Color(im).enhance(rng.uniform(0.94, 1.08))
    a = np.asarray(im).astype(np.float32)
    warm = rng.uniform(-6, 6)
    a[..., 0] += warm
    a[..., 2] -= warm
    a += np.random.default_rng(rng.randrange(1 << 30)).normal(0, rng.uniform(1.5, 3.5), a.shape[:2])[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def slides(r: dict, mode: str) -> list[tuple[Image.Image, list[tuple]]]:
    h = 1440 if mode == "c" else 1920
    rng = random.Random(r["seed"] + (0 if mode == "c" else 7))
    out = []
    for k in range(8):
        if not r["pick"][k]:
            continue
        im = photo(SL / f"s{k + 1}" / r["pick"][k], W, h, rng).convert("RGBA")
        cy = CY[mode][k] + rng.uniform(-0.012, 0.012)
        boxes = K4.caption(im, TEXTS[k], cy, h, 720 if mode == "c" else 780, px=rng.choice((54, 56, 58)))
        out.append((im.convert("RGB"), boxes))
    return out


def save_carousel(r: dict, out: str, flat: str | None, suffix: str) -> str:
    d = Path(out) / f"{r['i']:03d}"
    d.mkdir(parents=True, exist_ok=True)
    for k, (im, boxes) in enumerate(slides(r, "c"), 1):
        for b in boxes:
            if bad := check_box(W, 1440, b):
                raise SystemExit(f"{r['i']:03d} слайд {k}: текст вне безопасной зоны {b} — {bad}")
        im.save(d / f"{k}.jpg", quality=93)
        if flat:
            Path(flat).mkdir(parents=True, exist_ok=True)
            shutil.copy2(d / f"{k}.jpg", Path(flat) / f"sort_{k}_{r['i']}_{suffix}.jpg")
    (d / "plan.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
    return d.name


def save_video(r: dict, out: str, music: str, suffix: str) -> str:
    fr = WORK / f"v{r['i']:03d}"
    fr.mkdir(parents=True, exist_ok=True)
    rng = random.Random(r["seed"] * 3 + 1)
    ins, fc, labels = [], [], []
    ks = [k for k in range(8) if r["pick"][k]]
    for j, (k, (im, boxes)) in enumerate(zip(ks, slides(r, "v"))):
        for b in boxes:
            if bad := check_box(W, 1920, b):
                raise SystemExit(f"{r['i']:03d} кадр {k + 1}: текст вне безопасной зоны {b} — {bad}")
        p = fr / f"{k + 1}.png"
        im.save(p, compress_level=1)
        n = round(DUR[k] * rng.uniform(0.95, 1.06) * 30)
        ins += ["-i", str(p)]
        fc.append(f"[{j}:v]format=yuv420p,loop=loop={n - 1}:size=1:start=0,settb=1/30,setpts=N[s{j}]")
        labels.append((f"[s{j}]", n))
    total = sum(n for _, n in labels) / 30
    fc.append("".join(x for x, _ in labels) + f"concat=n={len(labels)}:v=1:a=0[v]")
    ss = rng.uniform(0.0, 4.0)
    ins += ["-ss", f"{ss:.2f}", "-t", f"{total + 0.3:.2f}", "-i", music]
    fc.append(f"[{len(labels)}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
              f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=in:d=0.3,afade=t=out:st={total - 1.0:.3f}:d=1.0[a]")
    dest = Path(out) / f"{r['i']:03d}_{suffix}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
                    "-t", f"{total:.3f}", "-r", "30", "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27",
                    "-maxrate", "6M", "-bufsize", "12M", "-pix_fmt", "yuv420p",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-c:a", "aac", "-b:a", "160k",
                    "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
                    "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=",
                    "-movflags", "+faststart", str(dest)], check=True, timeout=300)
    shutil.rmtree(fr)
    return dest.name


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--carousels", action="store_true")
    ap.add_argument("--video", action="store_true")
    ap.add_argument("--seed", type=int, default=5501)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--suffix", default="1")
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    track = lambda i: str(MUSIC[(i - 1) % len(MUSIC)])          # noqa: E731
    with ProcessPoolExecutor(a.jobs) as ex:
        if a.test:
            out = ROOT / "output" / "_work" / "kolibri5_test"
            rows = plan(4, a.seed)
            fs = [ex.submit(save_carousel, r, str(out / "carousels"), None, a.suffix) for r in rows]
            fs += [ex.submit(save_video, r, str(out), track(r["i"]), a.suffix) for r in rows]
            for f in fs:
                print(" ", f.result(), flush=True)
            return 0
        if a.carousels:
            out, flat = ROOT / "output" / "kolibri5_carousels_100", ROOT / "output" / "kolibri5_100"
            rows = plan(a.n, a.seed)
            for f in [ex.submit(save_carousel, r, str(out), str(flat), a.suffix) for r in rows]:
                print(" ", f.result(), flush=True)
            sys.argv = ["strip", str(out), str(flat)]
            strip_jpeg_meta.main()
        if a.video:
            out = ROOT / "output" / f"kolibri5_YT_{a.n}"
            out.mkdir(parents=True, exist_ok=True)
            rows = plan(a.n, a.seed + 1000)                     # другой seed: видео ≠ карусели TikTok
            for f in [ex.submit(save_video, r, str(out), track(r["i"]), a.suffix) for r in rows]:
                print(" ", f.result(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
