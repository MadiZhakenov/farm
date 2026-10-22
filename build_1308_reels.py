#!/usr/bin/env python3
"""
1308 «rating foods and I'm RIGHT about everything» — концепция как output/gw_tiers2 (она говорит «bad, good, amazing»
и показывает; на каждое слово всплывает картинка там, куда она указывает). Исходник — Drive
1hS7RvmbBsJz5cE60wF2ECLCU1S9uAlcG (= downloads/gw_tiers2/srcB: IMG_8093, IMG_8094, по 5 троек в каждом).

  — 3 тройки на ролик = 3 раунда: пицца → макароны → салат/завтрак; картинки еды без подписей
    (downloads/1308/food/<блюдо>/*.jpg, Pinterest, отобраны вручную);
  — заголовок сверху весь ролик дословно из ТЗ, TikTok Sans Bold, белый с чёрной обводкой (без тени);
  — ряд картинок симметричный (центр 540, шаг под то, куда она показывает), всё в безопасной зоне 9:16;
    кадр не сдвигаем (без размытых полос); у IMG_8093 лицо выше — лёгкий наезд ×1.12 от верхнего края,
    чтобы брови ушли ниже картинок;
  — тройки в ролике — из одного клипа (не скачет одежда), порядок любой; паузы между тройками вырезаны;
  — звук: голос −15 LUFS + звук из поста @joey.growth/photo/7657520466344561933 еле слышно, итог −14 LUFS.

  python build_1308_reels.py --count 50 [--jobs 3]
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_gotjob_reels as GJ  # noqa: E402  (loudnorm)
import build_gw_tiers_reels as T  # noqa: E402  (TM, duration)
from core.safe_zones import check_box, text_rect  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF, W, H, FPS = T.FF, T.W, T.H, T.FPS
D = ROOT / "downloads" / "1308"
SRC = ROOT / "downloads" / "gw_tiers2" / "srcB"
FOOD, MUSIC, INFO = D / "food", D / "music" / "joey_photo_sound.mp3", D / "clip_info.json"
ID = "1308"
TITLE = "rating foods and I’m RIGHT about everything"          # дословно из ТЗ
TITLE_FONT, TITLE_PX, TITLE_TOP = ROOT / "fonts" / "TikTokSans-Bold.ttf", 46, 205
STROKE = 4                                        # белый текст с чёрной обводкой, без тени (пользователь)
ROUNDS = [("pizza_bad", "pizza_good", "pizza_amazing"), ("pasta_bad", "pasta_good", "pasta_amazing"),
          ("brk_bad", "brk_good", "brk_amazing")]
SIDE, GAP_TOP, RAD = 200, 22, 26                 # картинка, отступ от заголовка, скругление
STEP = 280                                        # шаг ряда: палец ~310–350 от центра → упор в зону (с тенью)
ZOOM = {"IMG_8093": 1.12}                         # наезд от верхнего края: брови ниже картинок
PRE, POST, POP = 0.35, 1.0, 0.18
VOICE_I, MUSIC_I, FINAL_I = -15.0, -33.0, -14.0   # музыка ~18 дБ тише голоса — «еле слышно»


def title_layer() -> tuple[Image.Image, int]:
    f = ImageFont.truetype(str(TITLE_FONT), TITLE_PX)
    lines = ["rating foods and I’m RIGHT", "about everything"]
    lh = int(TITLE_PX * 1.22)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for k, t in enumerate(lines):
        d.text((W / 2, TITLE_TOP + (k + 0.5) * lh), t, font=f, fill=(255, 255, 255, 255), anchor="mm",
               stroke_width=STROKE, stroke_fill=(0, 0, 0, 255))
    return img, img.getbbox()[3]


def food_card(path: Path) -> Image.Image:
    im = Image.open(path).convert("RGB").resize((SIDE, SIDE), Image.Resampling.LANCZOS)
    m = Image.new("L", (SIDE, SIDE), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, SIDE - 1, SIDE - 1], radius=RAD, fill=255)
    card = im.convert("RGBA")
    card.putalpha(m)
    pad = 18                                         # мягкая тень, чтобы картинка не сливалась с фоном
    out = Image.new("RGBA", (SIDE + 2 * pad, SIDE + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", (SIDE, SIDE), (0, 0, 0, 110)), (pad, pad + 5), m)
    out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(9)))
    out.alpha_composite(card, (pad, pad))
    return out


def overlay(base: Image.Image, cards: list[Image.Image], cols: list[float], top: int, t: float,
            pops: list[float]) -> Image.Image:
    layer = base.copy()
    for card, cx, tp in zip(cards, cols, pops):
        if t < tp:
            continue
        u = min(1.0, (t - tp) / POP)
        s = 0.55 + 0.55 * u if u < 0.75 else 1.0 + 0.1 * (1 - u) / 0.25      # 0.55 → 1.1 → 1.0, как в gw_tiers
        a = min(1.0, u * 2.5)
        side = max(2, int(card.width * s))
        im = card.resize((side, side), Image.Resampling.BILINEAR)
        if a < 1:
            im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
        cy = top + SIDE / 2
        layer.alpha_composite(im, (int(cx - side / 2), int(cy - side / 2)))
    return layer


def plan(count: int) -> list[dict]:
    """Ролик = клип + упорядоченные 3 тройки из его 5 (порядок любой) + картинки. Клипы чередуем."""
    info = json.loads(INFO.read_text())
    rng = random.Random(1308)
    orders = {}
    for clip in info:
        perms = list(itertools.permutations(range(len(info[clip])), 3))
        chrono = [p for p in perms if list(p) == sorted(p)]
        rest = [p for p in perms if list(p) != sorted(p)]
        rng.shuffle(chrono)
        rng.shuffle(rest)
        orders[clip] = chrono + rest
    pools = {k: sorted(p for p in (FOOD / k).glob("*.jpg") if not p.name.startswith("_"))
             for r in ROUNDS for k in r}
    for k, v in pools.items():
        if not v:
            raise SystemExit(f"нет картинок: {FOOD / k}")
    clips = list(info)
    out, used = [], set()
    for n in range(count):
        clip = clips[n % len(clips)]
        order = orders[clip][n // len(clips)]
        pics = []
        for r, keys in enumerate(ROUNDS):
            row = []
            for j, k in enumerate(keys):
                pool = pools[k]
                row.append(str(pool[(n * (3 + 2 * j) + 7 * r + j) % len(pool)]))
            pics.append(row)
        key = (clip, order, tuple(map(tuple, pics)))
        assert key not in used
        used.add(key)
        out.append({"n": n + 1, "clip": clip, "triplets": [info[clip][i]["t"] for i in order], "order": list(order),
                    "pics": pics})
    return out


def build(job: dict) -> str:
    work = Path(tempfile.mkdtemp(prefix="r1308_"))
    clip, src = job["clip"], SRC / f"{job['clip']}.MOV"
    dur = T.duration(src)
    segs, t_out = [], 0.0
    for b, g, am in job["triplets"]:
        s, e = max(0.0, b - PRE), min(am + POST, dur)
        segs.append((s, e, [t_out + (x - s) for x in (b, g, am)]))
        t_out += e - s
    z = ZOOM.get(clip, 1.0)
    zf = f",scale={round(W * z / 2) * 2}:{round(H * z / 2) * 2},crop={W}:{H}:(iw-{W})/2:0" if z != 1.0 else ""
    parts = [f"[0:v]{T.TM},split=3[s0][s1][s2]", "[0:a:0]asplit=3[t0][t1][t2]"]
    for i, (s, e, _p) in enumerate(segs):
        parts.append(f"[s{i}]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS{zf},setsar=1[v{i}]")
        parts.append(f"[t{i}]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d=0.01,afade=t=out:st={max(0, e - s - 0.012):.3f}:d=0.012[a{i}]")
    base = work / "base.mov"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-filter_complex",
                    ";".join(parts) + ";[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-c:a", "pcm_s16le", str(base)], check=True)
    # звук: голос + еле слышная музыка
    voice, music_raw, music, mix, fin = (work / f"{x}.wav" for x in ("voice", "music_raw", "music", "mix", "final"))
    GJ.loudnorm(base, voice, VOICE_I, "highpass=f=80")
    subprocess.run([FF, "-v", "error", "-y", "-i", str(MUSIC), "-t", f"{t_out:.3f}", "-af",
                    f"afade=t=out:st={max(0, t_out - 0.6):.3f}:d=0.6", str(music_raw)], check=True)
    GJ.loudnorm(music_raw, music, MUSIC_I)
    subprocess.run([FF, "-v", "error", "-y", "-i", str(voice), "-i", str(music), "-filter_complex",
                    "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[m]", "-map", "[m]", str(mix)], check=True)
    GJ.loudnorm(mix, fin, FINAL_I)
    # графика
    tl, tbottom = title_layer()
    top = tbottom + GAP_TOP
    cols = [540 - STEP, 540, 540 + STEP]
    cards = [[food_card(Path(p)) for p in row] for row in job["pics"]]
    full = overlay(tl, cards[0], cols, top, 1e9, [0, 0, 0])
    bad = check_box(W, H, full.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox())
    if bad:
        raise SystemExit(f"вне безопасной зоны: {bad}")
    starts = [sum(e - s for s, e, _p in segs[:k]) for k in range(3)]
    out_dir = ROOT / "output" / job["out"]
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{job['n']:03d}_{ID}.mp4"
    dec = subprocess.Popen([FF, "-v", "error", "-i", str(base), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r",
                            str(FPS), "-i", "-", "-i", str(fin), "-map", "0:v", "-map", "1:a", "-vf",
                            f"format=yuv420p,{SET_SDR}", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                            *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
                            str(dest)], stdin=subprocess.PIPE)
    f = 0
    while True:
        buf = dec.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        t = f / FPS
        k = max(i for i in range(3) if starts[i] <= t + 1e-6)
        frame = Image.frombuffer("RGB", (W, H), buf).convert("RGBA")
        frame.alpha_composite(overlay(tl, cards[k], cols, top, t, segs[k][2]))
        enc.stdin.write(frame.convert("RGB").tobytes())
        f += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()
    return f"{dest.name}: {clip} тройки {job['order']}, {t_out:.2f} с"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--out", default=None, help="папка в output/ (по умолчанию 1308_<count>)")
    args = ap.parse_args()
    out = args.out or f"{ID}_{args.count}"
    jobs = plan(args.count)
    for j in jobs:
        j["out"] = out
    (ROOT / "output" / out).mkdir(parents=True, exist_ok=True)
    (ROOT / "output" / out / "manifest.json").write_text(json.dumps(jobs, indent=1, ensure_ascii=False), encoding="utf-8")
    with ProcessPoolExecutor(args.jobs) as ex:
        for k, msg in enumerate(ex.map(build, jobs), 1):
            print(f"[{k}/{len(jobs)}] {msg}", flush=True)
    print("готово →", ROOT / "output" / out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
