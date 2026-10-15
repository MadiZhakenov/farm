#!/usr/bin/env python3
"""
1275 — «NO WOMAN HAS ALL 5 of these» (реф Instagram CwA7tTpOcMw): 6-секундные клипы UGC-креаторов
(output/clips_1275, первые 6 с каждого исходника, родной звук) + 2 текста в Insta-стиле, как в рефе:
чёрный жирный шрифт (Figtree Bold — свободный аналог Instagram Sans) на белой скруглённой плашке.
  заголовок — весь ролик, верхний край на 25% высоты;
  «read below…» — с 4-й секунды, центр на 50% высоты.
Эмодзи — Apple PNG (assemble_ugc_reels). 11 клипов × 25 текстов: пары уникальны, тексты и клипы
расходуются поровну.

  python build_1275_reels.py -n 3 --out output/1275_test
  python build_1275_reels.py -n 250 --out output/1275_250 --suffix 1275
  python build_1275_reels.py -n 250 --out output/1275_250_tiktok --suffix 1275 --style tiktok
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
W, H, DUR = 1080, 1920, 6.0
CLIPS = ROOT / "output" / "clips_1275"
IG_FONT = ROOT / "fonts" / "ig_lookalike" / "Figtree.ttf"
# MAX_W — ширина блока по центру (x 140–940): правее ~140 px колонка лайк/коммент/шер TikTok/Reels/Shorts
TITLE_PX, SUB_PX, MAX_W = 60, 50, 800
TITLE_TOP, SUB_CY, SUB_T = 0.25, 0.50, 4.0
# плашка «потолще», как в рефе: больше белого вокруг букв, шрифт жирнее
WEIGHT, LINE_H, PAD_X, RADIUS = "ExtraBold", 1.42, 0.45, 0.28

TEXTS = [
    ("NO WOMAN HAS ALL 5 of these", "read below and tell me how many you've got"),
    ("NO GIRL HAS ALL 5 of these", "read below, how many do you have? 👇"),
    ("I bet you don't have all 5 of these", "read below and count yours"),
    ("Only 1 in 100 girls has all 5 of these", "read below, are you the 1? 😳"),
    ("NO WOMAN HAS ALL 5 of these 😳", "read below and be honest, how many?"),
    ("Girls, how many of these 5 do you have?", "read below and comment your number"),
    ("NO ONE has all 5 of these", "read below and prove me wrong 👇"),
    ("Let's see if you have all 5 of these", "read below, I'll wait"),
    ("NO WOMAN HAS ALL 5 of these (try me)", "read below and tell me your score"),
    ("It's rare to have all 5 of these 😮‍💨", "read below, how many do you have?"),
    ("NO GIRL HAS ALL 5 of these, change my mind", "read below and tell me your number"),
    ("5 things, and no woman has all of them", "read below, how many did you get?"),
    ("NO WOMAN HAS ALL 5 of these 🤭", "read below and tell me in the comments"),
    ("POV: you think you have all 5 of these", "read below and count again 😳"),
    ("Bet you can't say yes to all 5", "read below, how many do you have?"),
    ("NO WOMAN HAS ALL 5 of these, I'll wait 👀", "read below and tell me how many you've got"),
    ("5 things every girl wants (nobody has all of them)", "read below, what's your number?"),
    ("NO WOMAN HAS ALL 5 of these 🫣", "read below, I need to know your score"),
    ("How many of these 5 do you have?", "read below, no lying 😭"),
    ("NO WOMAN HAS ALL 5 of these, ask me how I know", "read below and tell me how many you've got"),
    ("Only the luckiest girl has all 5 of these", "read below, is it you?"),
    ("NO WOMAN HAS ALL 5 of these 🥲", "read below and comment your score"),
    ("Rate yourself: how many of these 5?", "read below and tell me your number"),
    ("NO GIRL HAS ALL 5 of these (prove me wrong)", "read below, I'll check the comments"),
    ("NO WOMAN HAS ALL 5 of these 😳", "read below, tell me how many you've got, I'll go first"),
]


def _font(px: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(IG_FONT), px)
    f.set_variation_by_name(WEIGHT)
    return f


def _runs_width(runs: list[tuple[str, str]], font, px: int) -> float:
    return sum(font.getlength(s) if k == "text" else px * 1.15 for k, s in runs)


def wrap(text: str, font, px: int, max_w: int) -> list[str]:
    """Перенос по словам; строки выравниваются по длине (без «висящего» слова)."""
    words = text.split()

    def greedy(limit: float) -> list[str]:
        lines, cur = [], ""
        for w in words:
            cand = (cur + " " + w).strip()
            if cur and _runs_width(A._tokenize_runs(cand), font, px) > limit:
                lines.append(cur)
                cur = w
            else:
                cur = cand
        return lines + [cur]

    best = greedy(max_w)
    for lim in range(max_w - 20, int(max_w * 0.5), -20):
        cand = greedy(lim)
        if len(cand) > len(best):
            break
        best = cand
    return best


def plate(text: str, px: int) -> Image.Image:
    """Чёрный текст на одной белой плашке — ровный скруглённый прямоугольник по самой широкой строке
    (фидбек: без «лесенки» у многострочных), строки по центру; эмодзи — Apple PNG."""
    ss = 3
    P = px * ss
    font = _font(P)
    lines = wrap(text, _font(px), px, MAX_W - 2 * int(PAD_X * px))   # плашка с полями ≤ MAX_W
    line_h, pad_x, r = int(LINE_H * P), int(PAD_X * P), int(RADIUS * P)
    runs = [A._tokenize_runs(t) for t in lines]
    widths = [_runs_width(rr, font, P) for rr in runs]
    cw = int(max(widths) + 2 * pad_x)
    ch = line_h * len(lines)
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw - 1, ch - 1], radius=r, fill=255)
    img = Image.new("RGBA", (cw, ch), (255, 255, 255, 0))
    img.putalpha(mask)
    d = ImageDraw.Draw(img)
    for k, (rr, w) in enumerate(zip(runs, widths)):
        x = (cw - w) / 2
        cy = (k + 0.5) * line_h
        for kind, s in rr:
            if kind == "text":
                d.text((x, cy), s, font=font, fill=(0, 0, 0, 255), anchor="lm")
                x += font.getlength(s)
            else:
                e = A._apple_emoji_rgba(s, int(P * 1.05))
                if e is not None:
                    img.alpha_composite(e, (int(x + P * 0.05), int(cy - e.height / 2)))
                x += P * 1.15
    img = img.resize((cw // ss, ch // ss), Image.Resampling.LANCZOS)
    return img.crop(img.getbbox())


def plate_tt(text: str, px: int) -> Image.Image:
    """TikTok-стиль (как во всех наших рилсах): белый TikTok Sans с чёрной обводкой, без плашки,
    строки по центру; перенос и эмодзи — как в Insta-версии."""
    from core import renderer as R

    font = R._load_font(px)
    stroke, adv = R.stroke_width_for(px), R.line_advance_for(px)
    lines = wrap(text, font, px, MAX_W)
    img = Image.new("RGBA", (W, adv * len(lines) + 4 * stroke), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 2 * stroke
    for t in lines:
        w = A._line_width_mixed(t, font, px, stroke)
        A._draw_line_mixed(img, d, int((W - w) // 2), y, t, font, px, stroke)
        y += adv
    return img.crop(img.getbbox())


def overlay(block: Image.Image, dest: Path, y: int) -> None:
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(block, ((W - block.width) // 2, int(y)))
    canvas.save(dest)


# ---- лицо не закрываем (фидбек): по каждому клипу полоса лица, плашки ставим вне её ----
# интерфейс приложений (9:16, 1080×1920): сверху вкладки TikTok / шапка Reels (~200 px), снизу ник+подпись+музыка
# (TikTok ~334, Shorts 300–360, Reels — столько же) → текст только в полосе 200–1540 px
SAFE_TOP, SAFE_BOT, MARGIN = 200, 1540, 30
FACES = CLIPS / "_faces_v2.json"
# рамка Haar кончается на губах, а не на подбородке (повторная проверка: в клипе 28 вторая плашка легла
# на подбородок) → низ лица = низ рамки + CHIN·высота; полоса — по всем кадрам (после отсева ложных рамок)
CHIN = 0.12


def face_bands(clips: list[Path]) -> dict:
    """Полоса лица (Haar, 10 к/с): лоб–подбородок по всему ролику и с 4-й секунды. Ложные рамки (грудь,
    принт на футболке) отсекаем по расстоянию от скользящей медианы ±1 с."""
    cache = json.loads(FACES.read_text(encoding="utf-8")) if FACES.exists() else {}
    det = [cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / n))
           for n in ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml")]
    for clip in clips:
        if clip.name in cache:
            continue
        raw = subprocess.run([FF, "-v", "error", "-i", str(clip), "-vf", "fps=10,scale=540:960", "-f", "rawvideo",
                              "-pix_fmt", "gray", "-"], capture_output=True).stdout
        frs = np.frombuffer(raw, np.uint8).reshape(-1, 960, 540)
        boxes = []
        for i, g in enumerate(frs):
            f = list(det[0].detectMultiScale(g, 1.1, 5, minSize=(60, 60))) or \
                list(det[1].detectMultiScale(g, 1.1, 4, minSize=(60, 60)))
            if f:
                x, y, w, h = max(f, key=lambda b: b[2] * b[3])
                boxes.append((i / 10, 2 * (x + w / 2), 2 * (y + h / 2), 2 * h))
        keep = []
        for t, cx, cy, h in boxes:
            near = [b for b in boxes if abs(b[0] - t) <= 1.0]
            mcx, mcy, mh = (float(np.median([b[k] for b in near])) for k in (1, 2, 3))
            if abs(cx - mcx) <= 0.5 * mh and abs(cy - mcy) <= 0.5 * mh and h >= 0.6 * mh:
                keep.append((t, cy - h / 2, cy + h / 2 + CHIN * h))

        def band(rows):
            return [int(min(r[1] for r in rows)), int(max(r[2] for r in rows))]
        late = [b for b in keep if b[0] >= SUB_T] or keep
        cache[clip.name] = {"all": band(keep), "late": band(late)}
    FACES.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return cache


def layout(band: dict, th: int, sh: int) -> tuple[int, int]:
    """Заголовок: на 25% (ТЗ), если там не лицо; иначе прямо над лбом; если сверху места нет — под
    подбородком. Вторая строка: по центру (50%), если не на лице; иначе под подбородком / под заголовком,
    иначе над лицом."""
    f0, f1 = band["all"]
    l0, l1 = band["late"]
    ty = int(TITLE_TOP * H)
    if ty + th > f0 - MARGIN:
        ty = f0 - MARGIN - th
        if ty < SAFE_TOP:
            ty = min(f1 + MARGIN, SAFE_BOT - th)
    t_below = ty > f0
    sy = int(SUB_CY * H - sh / 2)

    def clear(y: int) -> bool:
        return (y + sh <= l0 - MARGIN or y >= l1 + MARGIN) and (y + sh <= ty - MARGIN or y >= ty + th + MARGIN)
    if not clear(sy):
        below = max(l1, ty + th if t_below else 0) + MARGIN
        above = l0 - MARGIN - sh
        if below + sh <= SAFE_BOT:
            sy = below
        elif above >= max(SAFE_TOP, ty + th + MARGIN if not t_below else SAFE_TOP):
            sy = above
        else:
            sy = SAFE_BOT - sh
    return ty, sy


def fits(band: dict, th: int, sh: int, ty: int, sy: int) -> bool:
    """Раскладка годится: оба блока внутри полосы интерфейса, заголовок не на лице (весь ролик),
    вторая строка не на лице (с 4 с) и не налезает на заголовок."""
    f0, f1 = band["all"]
    l0, l1 = band["late"]
    inside = all(SAFE_TOP <= y and y + h <= SAFE_BOT for y, h in ((ty, th), (sy, sh)))
    t_face = ty < f1 and ty + th > f0
    s_face = sy < l1 and sy + sh > l0
    overlap = sy < ty + th + MARGIN // 2 and sy + sh > ty - MARGIN // 2
    return inside and not t_face and not s_face and not overlap


def plan(n: int, n_clips: int, n_texts: int, rng: random.Random,
         allowed: set[tuple[int, int]] | None = None) -> list[tuple[int, int]]:
    pairs = [p for p in itertools.product(range(n_clips), range(n_texts)) if allowed is None or p in allowed]
    if n > len(pairs):
        raise SystemExit(f"нужно {n}, а уникальных пар {len(pairs)}")
    rng.shuffle(pairs)
    uc, ut, out = Counter(), Counter(), []
    for _ in range(n):
        best = min(pairs, key=lambda p: (ut[p[1]], uc[p[0]]))
        pairs.remove(best)
        uc[best[0]] += 1
        ut[best[1]] += 1
        out.append(best)
    return out


def build(clip: Path, title_png: Path, sub_png: Path, dest: Path) -> None:
    fc = (f"[0:v][1:v]overlay=0:0[t];[t][2:v]overlay=0:0:enable='gte(t,{SUB_T})',"
          f"format=yuv420p,{SET_SDR}[v]")
    subprocess.run([FF, "-v", "error", "-y", "-i", str(clip), "-i", str(title_png), "-i", str(sub_png),
                    "-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-c:a", "copy",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", *SDR_COLOR_ARGS,
                    "-t", f"{DUR:.2f}", "-movflags", "+faststart", str(dest)], stdin=subprocess.DEVNULL, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=250)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--suffix", default="")
    ap.add_argument("--style", choices=["ig", "tiktok"], default="ig",
                    help="ig — чёрный на белой плашке (как реф), tiktok — белый TikTok Sans с обводкой")
    ap.add_argument("--texts", help="только эти номера текстов (1..25) через запятую — для тестов")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--all-clips", action="store_true", help="тест: все клипы × тексты из --texts")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    clips = sorted(CLIPS.glob("*.mp4"))
    tidx = [int(x) - 1 for x in args.texts.split(",")] if args.texts else list(range(len(TEXTS)))
    args.out.mkdir(parents=True, exist_ok=True)
    pngs = args.out / "_text"
    pngs.mkdir(exist_ok=True)
    mk = plate_tt if args.style == "tiktok" else plate
    blocks = {i: (mk(TEXTS[i][0], TITLE_PX), mk(TEXTS[i][1], SUB_PX)) for i in tidx}
    bands = face_bands(clips)
    # пары, где текст помещается мимо лица и интерфейса (у крупных планов длинные тексты не влезают)
    allowed = set()
    for c, clip in enumerate(clips):
        for j, t in enumerate(tidx):
            tb, sb = blocks[t]
            if fits(bands[clip.name], tb.height, sb.height, *layout(bands[clip.name], tb.height, sb.height)):
                allowed.add((c, j))
    skipped = Counter(clips[c].name for c in range(len(clips)) for j in range(len(tidx)) if (c, j) not in allowed)
    if skipped:
        print(f"не влезают мимо лица и интерфейса (пары исключены): {dict(skipped)}")
    if args.all_clips:  # тест: каждый клип × выбранные тексты
        pairs = [(c, t) for c in range(len(clips)) for t in tidx]
    else:
        pairs = [(c, tidx[t]) for c, t in plan(args.n, len(clips), len(tidx), random.Random(args.seed), allowed)]
    names = [f"{k:03d}{'_' + args.suffix if args.suffix else ''}.mp4" for k in range(1, len(pairs) + 1)]

    def job(k: int) -> dict:
        c, t = pairs[k]
        tb, sb = blocks[t]
        ty, sy = layout(bands[clips[c].name], tb.height, sb.height)
        tp, sp = pngs / f"{k:03d}_t.png", pngs / f"{k:03d}_s.png"
        overlay(tb, tp, ty)
        overlay(sb, sp, sy)
        build(clips[c], tp, sp, args.out / names[k])
        return {"file": names[k], "clip": clips[c].name, "text": t + 1, "title_y": ty, "sub_y": sy}

    with ThreadPoolExecutor(args.jobs) as ex:
        manifest = list(ex.map(job, range(len(pairs))))
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"клипы: {dict(Counter(m['clip'] for m in manifest))}")
    print(f"тексты: {dict(sorted(Counter(m['text'] for m in manifest).items()))}")
    print(f"готово: {len(manifest)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
