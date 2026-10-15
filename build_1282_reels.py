#!/usr/bin/env python3
"""
1282 — 5 роликов TikTok (женщины 50–65 тренируются, downloads/1282/src) × 4 пары текста = 20 роликов по 7 с.

  — сверху надпись с 0 с, снизу вторая — появляется на 3-й секунде (дословно из ТЗ, с эмодзи);
  — текст на белой подложке в стиле TikTok: если в ролике свой вшитый текст — наша подложка встаёт поверх него
    (верхняя — на верхний, нижняя — на средний); до 3 с средний вшитый текст размываем;
  — две нарезки: 3 с из одного места ролика + 4 с из другого (склейка = появление второй надписи), куски без
    склеек оригинала и так, чтобы лица как можно меньше уходили под подложки; у каждой пары своя нарезка;
  — звук во всех роликах — только трек из TikTok @amandaaguilar.simple 7676979641445387534 («original sound»,
    тот же ролик, что v3) с начала, родной звук убран; трек заранее выровнен до −14 LUFS (двухпроходно).
    Текст подложек — внутри безопасной зоны 9:16 (docs/SAFE_ZONES.md).

  python build_1282_reels.py                                   # 20 (по 1 нарезке)
  python build_1282_reels.py --count 100 --out output/1282_100  # 100: поровну, короткие ролики — сколько дают
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402  (эмодзи Apple)
from core.safe_zones import check_box  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
SRC = ROOT / "downloads" / "1282" / "src"
OUT = ROOT / "output" / "1282_20"
ID = "1282"
W, H, FPS = 1080, 1920, 30
LEN_A, LEN_B = 3.0, 4.0
FONT = ROOT / "fonts" / "TikTokSans-SemiBold.ttf"
PX, PAD_X, PAD_Y, M, MAX_W = 56, 34, 20, 14, 740
TOP_DEFAULT, BOT_DEFAULT = 270, 1330          # верх подложки / центр нижней, если вшитого текста нет
FACE_MAX = 0.3                                # доля лица под подложками — больше не берём
MUSIC = ROOT / "downloads" / "1282" / "music" / "amanda_original_sound.mp3"   # звук для всех роликов (ТЗ)

PAIRS = [
    ("i’m 65 and i feel better than most people in their 25", "here’s why (read the post) 👇"),
    ("i’m 65 and my energy beats most 25 year olds", "my 5 rules are in the post 👇"),
    ("65 and feeling better than I did at 25 😳", "read the post to see why"),
    ("i’m a grandma and i feel better than most people in their 25", "here’s why (read the post) 👇"),
]


# ---------------- текст ----------------
def runs_width(line: str, font: ImageFont.FreeTypeFont, px: int) -> float:
    w = 0.0
    for kind, ch in A._tokenize_runs(line):
        w += A._emoji_px(px) + px // 16 if kind == "emoji" else font.getlength(ch)
    return w


def wrap(text: str, font: ImageFont.FreeTypeFont, px: int, limit: float) -> list[str]:
    def greedy(lim: float) -> list[str]:
        out, cur = [], ""
        for w in text.split():
            c = (cur + " " + w).strip()
            if cur and runs_width(c, font, px) > lim:
                out.append(cur)
                cur = w
            else:
                cur = c
        return out + [cur]

    lines = greedy(limit)
    lo, hi = 150.0, limit                     # то же число строк, но ровнее
    while hi - lo > 2:
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if len(greedy(mid)) <= len(lines) else (mid, hi)
    return greedy(hi)


def plate(text: str, under: list[int] | None, top: float | None, center: float | None) -> tuple[Image.Image, list[int]]:
    """Белая скруглённая подложка с чёрным текстом (и эмодзи) на полном кадре. under — вшитый текст, который
    надо закрыть (подложка встаёт по его центру и с запасом его накрывает)."""
    ss = 2
    font = ImageFont.truetype(str(FONT), PX * ss)
    lines = wrap(text, font, PX * ss, MAX_W * ss)
    adv = int(PX * 1.24)
    tw = max(runs_width(x, font, PX * ss) for x in lines) / ss
    th = adv * len(lines)
    pw, ph = tw + 2 * PAD_X, th + 2 * PAD_Y
    if under:
        cy = (under[1] + under[3]) / 2
        pw = max(pw, under[2] - under[0] + 2 * M)
        ph = max(ph, under[3] - under[1] + 2 * M)
    else:
        cy = center if center is not None else top + ph / 2
    pw = min(pw, W - 32)
    x0, x1, y0, y1 = W / 2 - pw / 2, W / 2 + pw / 2, cy - ph / 2, cy + ph / 2
    if under:                                  # подложка симметрична по центру кадра — расширяем, чтобы накрыть
        half = min(max(W / 2 - (under[0] - M), (under[2] + M) - W / 2, pw / 2), W / 2 - 16)
        x0, x1 = W / 2 - half, W / 2 + half
    img = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0 * ss, y0 * ss, x1 * ss, y1 * ss], radius=24 * ss, fill=(255, 255, 255, 255))
    ty = (y0 + y1) / 2 - th / 2
    for i, ln in enumerate(lines):
        lw = runs_width(ln, font, PX * ss)
        x = W / 2 * ss - lw / 2
        yc = (ty + (i + 0.5) * adv) * ss
        for kind, ch in A._tokenize_runs(ln):
            if kind == "emoji":
                ep = A._emoji_px(PX * ss)
                em = A._apple_emoji_rgba(ch, ep)
                if em is not None:
                    img.alpha_composite(em, (int(x), int(yc - em.height / 2)))
                x += ep + (PX * ss) // 16
            else:
                d.text((x, yc), ch, font=font, fill=(0, 0, 0, 255), anchor="lm")
                x += font.getlength(ch)
    img = img.resize((W, H), Image.Resampling.LANCZOS)
    tbox = (int(W / 2 - tw / 2), int(ty), int(W / 2 + tw / 2), int(ty + th))
    bad = check_box(W, H, tbox)
    if bad:
        raise SystemExit(f"текст «{text}» вне безопасной зоны: {bad}")
    return img, [int(x0), int(y0), int(x1), int(y1)]


# ---------------- анализ роликов ----------------
def probe(p: Path) -> float:
    return float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)


def scene_cuts(p: Path) -> list[float]:
    raw = subprocess.run([FF, "-v", "error", "-i", str(p), "-vf", f"fps={FPS},scale=54:96", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, 96, 54).astype(np.float32)
    v = v.reshape(len(v), -1)
    v = (v - v.mean(1, keepdims=True)) / (v.std(1, keepdims=True) + 1e-6)
    c = (v[1:] * v[:-1]).mean(1)
    return [round((i + 1) / FPS, 3) for i in np.where(c < 0.45)[0]]


def burned(ocr: list) -> tuple[list[int] | None, list[tuple[float, float, list[int]]]]:
    """Вшитый текст: верхний — рамка (весь ролик), средние — (с, по, рамка)."""
    top = [r for r in ocr if (r[2] + r[4]) / 2 < 700]
    mid = [r for r in ocr if (r[2] + r[4]) / 2 >= 700]
    tb = None
    if top:
        tb = [min(r[1] for r in top), min(r[2] for r in top), max(r[3] for r in top), max(r[4] for r in top)]
    mids = []
    if mid:
        box = [min(r[1] for r in mid), min(r[2] for r in mid), max(r[3] for r in mid), max(r[4] for r in mid)]
        mids.append((min(r[0] for r in mid) - 0.5, max(r[0] for r in mid) + 0.5, box))
    return tb, mids


def overlap(face: list[int], rect: list[int]) -> float:
    ix = max(0, min(face[2], rect[2]) - max(face[0], rect[0]))
    iy = max(0, min(face[3], rect[3]) - max(face[1], rect[1]))
    fa = max(1, (face[2] - face[0]) * (face[3] - face[1]))
    return ix * iy / fa


def plan(vid: str, dur: float, cuts: list[float], faces: list, top_r: list[int], bot_r: list[int],
         mids: list, rng: np.random.Generator, used: list) -> tuple[float, float, float]:
    """Лучшие куски A (3 с) и B (4 с): без склеек оригинала, лица мимо подложек, не как у прошлых пар."""
    def clean(a: float, L: float) -> bool:
        return a >= 0 and a + L <= dur - 0.05 and not any(a + 0.05 < c < a + L - 0.05 for c in cuts)

    def face_cost(a: float, L: float, rects: list) -> float:
        fs = [f for f in faces if a <= f[0] <= a + L]
        return sum(max(overlap(f[1:], r) for r in rects) for f in fs) / max(1, L * 5)

    def blur_cost(a: float) -> float:
        return sum(1 for t0, t1, _b in mids if t0 < a + LEN_A and a < t1) * 0.05

    grid = np.arange(0, max(0.01, dur - min(LEN_A, LEN_B)), 0.25)
    best = []
    for a in grid:
        if not clean(a, LEN_A):
            continue
        ca = face_cost(a, LEN_A, [top_r]) + blur_cost(a)
        for b in grid:
            if not clean(b, LEN_B) or abs(a - b) < 3.0 or (a < b + LEN_B and b < a + LEN_A) or abs(b - (a + LEN_A)) < 0.5:
                continue
            if any(abs(a - ua) < 1.5 and abs(b - ub) < 1.5 for ua, ub in used):
                continue
            cost = ca + face_cost(b, LEN_B, [top_r, bot_r]) + rng.uniform(0, 0.02)
            best.append((cost, float(a), float(b)))
    best = [x for x in best if x[0] <= FACE_MAX]
    if not best:
        return None
    best.sort()
    cost, a, b = best[0]
    used.append((a, b))
    return a, b, cost


# ---------------- рендер ----------------
def music_master(work: Path) -> Path:
    """Трек ТЗ, выровненный до −14 LUFS (двухпроходный loudnorm, пики ≤ −1.5 dB)."""
    flt = "loudnorm=I=-14:TP=-1.5:LRA=11"
    log = subprocess.run([FF, "-hide_banner", "-i", str(MUSIC), "-af", flt + ":print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = json.loads(log[log.rfind("{"):log.rfind("}") + 1])
    dest = work / "music_-14.wav"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(MUSIC), "-af",
                    f"{flt}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
                    f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample=48000",
                    "-c:a", "pcm_s16le", str(dest)], check=True)
    return dest


def render(src: Path, a: float, b: float, top_png: Path, bot_png: Path, blur_a: list[list[int]], music: Path,
           dest: Path) -> None:
    sc = f"fps={FPS},scale={W}:{H}:flags=lanczos:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    fc = [f"[0:v]{sc},setpts=PTS-STARTPTS[va0]", f"[1:v]{sc},setpts=PTS-STARTPTS[vb]"]
    cur = "va0"
    for i, (x0, y0, x1, y1) in enumerate(blur_a):            # вшитый средний текст до 3 с — размыть
        x0, y0 = max(0, x0 - 12) // 2 * 2, max(0, y0 - 12) // 2 * 2
        w, h = (min(W, x1 + 12) - x0) // 2 * 2, (min(H, y1 + 12) - y0) // 2 * 2
        fc.append(f"[{cur}]split[s{i}][t{i}];[t{i}]crop={w}:{h}:{x0}:{y0},gblur=sigma=16[bl{i}];"
                  f"[s{i}][bl{i}]overlay={x0}:{y0}[va{i + 1}]")
        cur = f"va{i + 1}"
    fc.append(f"[{cur}][vb]concat=n=2:v=1:a=0[cv]")
    fc.append(f"[cv][2:v]overlay=0:0[o1];[o1][3:v]overlay=0:0:enable='gte(t,{LEN_A})',format=yuv420p,{SET_SDR}[v]")
    total = LEN_A + LEN_B
    fc.append(f"[4:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={total - 0.3:.3f}:d=0.3[a]")
    args = [FF, "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{LEN_A:.3f}", "-i", str(src),
            "-ss", f"{b:.3f}", "-t", f"{LEN_B:.3f}", "-i", str(src), "-i", str(top_png), "-i", str(bot_png),
            "-i", str(music), "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k",
            "-map_metadata", "-1", "-movflags", "+faststart", str(dest)]
    subprocess.run(args, check=True)


def main() -> int:
    import argparse
    from concurrent.futures import ThreadPoolExecutor
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=1, help="нарезок на каждую пару «ролик + текст» (5 видео × 4 пары × per)")
    ap.add_argument("--count", type=int, default=0, help="сколько всего роликов (квоты по запасу нарезок)")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--jobs", type=int, default=6)
    args = ap.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="r1282_"))
    ocr = json.loads((SRC / "_ocr.json").read_text(encoding="utf-8"))
    faces = json.loads((SRC / "_faces.json").read_text())
    rng = np.random.default_rng(1282)
    music = music_master(work)
    total_n = args.count or len(list(SRC.glob("v*.mp4"))) * len(PAIRS) * args.per
    digits = 2 if total_n < 100 else 3
    # 1) все различимые нарезки каждого ролика (пары текста по кругу), 2) квоты: поровну, недостачу коротких
    #    роликов добирают длинные
    vids = []
    for src in sorted(SRC.glob("v*.mp4")):
        vid = src.stem.split("_")[0]
        dur = probe(src)
        cuts = scene_cuts(src)
        tb, mids = burned(ocr[src.stem])
        mid_box = mids[0][2] if mids else None
        fc = faces[src.stem]
        plates = []
        for k, (top_t, bot_t) in enumerate(PAIRS, 1):
            top_img, top_r = plate(top_t, tb, TOP_DEFAULT, None)
            bot_img, bot_r = plate(bot_t, mid_box, None, BOT_DEFAULT)
            if bot_r[1] < top_r[3] + 20:
                raise SystemExit(f"{vid}: подложки налезают друг на друга")
            tp, bp = work / f"{vid}_{k}_top.png", work / f"{vid}_{k}_bot.png"
            top_img.save(tp)
            bot_img.save(bp)
            plates.append((top_t, bot_t, top_r, bot_r, tp, bp))
        used: list = []                                   # нарезки ролика — без повторов на все пары
        plans = []
        while len(plans) < total_n:
            k = len(plans) % len(PAIRS)
            top_t, bot_t, top_r, bot_r, tp, bp = plates[k]
            got = plan(vid, dur, cuts, fc, top_r, bot_r, mids, rng, used)
            if got is None:
                break
            a, b, cost = got
            plans.append((k + 1, a, b, cost))
        vids.append((src, vid, mids, plates, plans))
        print(f"{vid}: различимых нарезок {len(plans)}", flush=True)
    quota = {v[1]: 0 for v in vids}
    left = total_n
    while left > 0:                                       # по одному по кругу, пока у ролика есть запас
        moved = False
        for _src, vid, _m, _p, plans in vids:
            if left and quota[vid] < len(plans):
                quota[vid] += 1
                left -= 1
                moved = True
        if not moved:
            break
    print("квоты:", quota, flush=True)
    rep, jobs, n = [], [], 0
    for src, vid, mids, plates, plans in vids:
        for k, a, b, cost in plans[:quota[vid]]:
            top_t, bot_t, top_r, bot_r, tp, bp = plates[k - 1]
            n += 1
            blur_a = [box for t0, t1, box in mids if t0 < a + LEN_A and a < t1]
            dest = out / f"{n:0{digits}d}_{ID}.mp4"
            jobs.append((src, a, b, tp, bp, blur_a, music, dest))
            rep.append({"file": dest.name, "video": vid, "pair": k, "top": top_t, "bottom": bot_t,
                        "cut_a": [round(a, 2), round(a + LEN_A, 2)], "cut_b": [round(b, 2), round(b + LEN_B, 2)],
                        "top_plate": top_r, "bottom_plate": bot_r, "blur_before_3s": blur_a,
                        "face_under_plates": round(cost, 3)})
    with ThreadPoolExecutor(args.jobs) as ex:
        list(ex.map(lambda j: render(*j), jobs))
    (out / "manifest.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"готово: {len(rep)} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
