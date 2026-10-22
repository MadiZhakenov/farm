#!/usr/bin/env python3
"""
1300 — UNO Mobile, «Микс всех папок»: ролик 7 с из кусков роликов клиента (исходники 1285,
downloads/dropbox_8k3sofvt) из РАЗНЫХ локаций — 2 куска по 3.5 с или 3 по 2.33 с; в одном ролике каждая
локация (Airport / Office / Restaurant / Subway) не больше одного раза, порядок локаций случайный.

Текст — один из 3 текстов ТЗ (дословно, поровну) на белой плашке как в h2 1285: плашка по размеру текста
закрывает вшитые тексты кусков (берём только куски, чей вшитый текст под неё влезает); «UNO! Mobile» не рвём.
Звук — «sonido original» (TikTok 7101932530202462982) с начала, −14 LUFS, родной звук убран.
Наборы (текст + ролики по порядку) не повторяются; использование роликов выравниваем.

  python build_1300_mix.py --count 2 --out output/1300_test
  python build_1300_mix.py --count 500 --out output/Mix_1300 --jobs 5
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402
import build_1285_remix as R  # noqa: E402
from core.safe_zones import check_box  # noqa: E402

ID = "1300"
W, H, FPS = R.W, R.H, R.FPS
LOCS = ["Airport", "Office", "Restaurant", "Subway"]
TOTAL = 7.0
TEXTS = [
    "POV: you can’t go anywhere without someone playing UNO! Mobile",
    "POV: you start seeing people play UNO! Mobile in every single place you go 😭",
    "POV: you’re at the office, at dinner, on the subway and at the airport, and everyone is on UNO! Mobile",
]
MUSIC = ROOT / "downloads" / "1285" / "music" / "m1_sonido_original_7101932530202462982.m4a"
WORK = ROOT / "output" / "1300"
NBSP = " "


# ---------------- плашка (как R.plate_png, но с эмодзи и неразрывным «UNO! Mobile») ----------------
def _runs_width(line: str, font: ImageFont.FreeTypeFont, px: int) -> float:
    w = 0.0
    for kind, chunk in A._tokenize_runs(line):
        w += A._emoji_px(px) + max(1, px // 16) if kind == "emoji" else font.getlength(chunk)
    return w


def plate_layout(text: str, max_w: float = 740) -> tuple[list[str], float, int, list[float], int]:
    text = text.replace("UNO! Mobile", f"UNO!{NBSP}Mobile")
    ss, px = 2, R.PLATE_PX
    font = ImageFont.truetype(str(R.FONT), px * ss)

    def greedy(limit: float) -> list[str]:
        out, cur = [], ""
        for w in text.split(" "):
            c = (cur + " " + w).strip()
            if cur and _runs_width(c, font, px * ss) > limit:
                out.append(cur)
                cur = w
            else:
                cur = c
        return out + [cur]

    n = len(greedy(max_w * ss))
    lo, hi = 150.0 * ss, max_w * ss                     # то же число строк, но ровнее
    while hi - lo > 2:
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if len(greedy(mid)) <= n else (mid, hi)
    lines = greedy(hi)
    tw = max(_runs_width(x, font, px * ss) for x in lines) / ss
    th = int(px * 1.24) * len(lines)
    rect = [W / 2 - tw / 2 - R.PAD_X, R.PLATE_TOP, W / 2 + tw / 2 + R.PAD_X, R.PLATE_TOP + th + 2 * R.PAD_Y]
    return lines, tw, th, rect, px


def plate_png(text: str, under: list[list[int]], dest: Path) -> dict:
    ss = 2
    lines, tw, th, (x0, y0, x1, y1), px = plate_layout(text)
    font = ImageFont.truetype(str(R.FONT), px * ss)
    adv, m = int(px * 1.24), R.FIT_M
    if under:
        ux0, uy0 = min(b[0] for b in under), min(b[1] for b in under)
        ux1, uy1 = max(b[2] for b in under), max(b[3] for b in under)
        x0, x1 = min(x0, ux0 - m), max(x1, ux1 + m)
        half = min(max(W / 2 - x0, x1 - W / 2), W / 2 - 16)
        x0, x1 = W / 2 - half, W / 2 + half
        y0, y1 = min(y0, uy0 - m), max(y1, uy1 + m)
    ty = (y0 + y1) / 2 - th / 2
    img = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0 * ss, y0 * ss, x1 * ss, y1 * ss], radius=24 * ss, fill=(255, 255, 255, 255))
    e_px = A._emoji_px(px * ss)
    for i, ln in enumerate(lines):
        lw = _runs_width(ln, font, px * ss)
        cx = W / 2 * ss - lw / 2
        mid = (ty + (i + 0.5) * adv) * ss
        for kind, chunk in A._tokenize_runs(ln):
            if kind == "emoji":
                em = A._apple_emoji_rgba(chunk, e_px)
                if em is not None:
                    img.alpha_composite(em, (int(round(cx)), int(round(mid - e_px * 0.55))))
                cx += e_px + max(1, (px * ss) // 16)
            else:
                d.text((cx, mid), chunk.replace(NBSP, " "), font=font, fill=(0, 0, 0, 255), anchor="lm")
                cx += font.getlength(chunk)
    img.resize((W, H), Image.Resampling.LANCZOS).save(dest)
    tbox = (int(W / 2 - tw / 2), int(ty), int(W / 2 + tw / 2), int(ty + th))
    bad = check_box(W, H, tbox)
    if bad:
        raise SystemExit(f"текст плашки вне безопасной зоны: {bad}")
    if under and not (x0 <= ux0 - 6 and x1 >= ux1 + 6 and y0 <= uy0 - 6 and y1 >= uy1 + 6):
        raise SystemExit("плашка не закрывает вшитый текст")
    return {"plate": [int(x0), int(y0), int(x1), int(y1)], "text_box": list(tbox), "lines": lines, "px": px}


# ---------------- звук ----------------
def music_master() -> Path:
    """Первые 7 с трека, двухпроходный loudnorm −14 LUFS, затухание 0.3 с — один файл на все ролики."""
    dest = WORK / "sonido_original_7s_-14lufs.wav"
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    meas = subprocess.run([R.FF, "-hide_banner", "-nostats", "-t", f"{TOTAL}", "-i", str(MUSIC),
                           "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                          capture_output=True, text=True).stderr
    js = json.loads(meas[meas.rindex("{"):meas.rindex("}") + 1])
    ln = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={js['input_i']}:measured_TP={js['input_tp']}:"
          f"measured_LRA={js['input_lra']}:measured_thresh={js['input_thresh']}:offset={js['target_offset']}:linear=true")
    subprocess.run([R.FF, "-v", "error", "-y", "-t", f"{TOTAL}", "-i", str(MUSIC), "-af",
                    f"{ln},afade=t=out:st={TOTAL - 0.3}:d=0.3", "-ar", "48000", "-ac", "2", str(dest)], check=True)
    return dest


# ---------------- план ----------------
def plan(count: int, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    cat = R.catalog()
    canon = R.same_video_text(cat)
    keys = sorted(k for k in set(canon.values()) if cat[k].loc in LOCS)
    _links, foot = R.footage_links(cat, keys)
    dur = {k: len(R.thumbs(cat[k].path)) / FPS for k in keys}
    rects = [plate_layout(t)[3] for t in TEXTS]
    use: Counter = Counter()                 # сколько раз взят видеоряд — берём наименее использованные
    used: set = set()
    fr = lambda k, t: R.thumbs(cat[k].path)[min(len(R.thumbs(cat[k].path)) - 1, max(0, int(round(t * FPS))))]  # noqa: E731
    out = []
    for n in range(count):
        ti = n % len(TEXTS)
        got = None
        for _attempt in range(500):
            nclip = int(rng.choice([2, 3]))
            nf = round(TOTAL * FPS / nclip)
            locs = [LOCS[i] for i in rng.permutation(len(LOCS))[:nclip]]
            clips = []
            for loc in locs:
                pool = [k for k in keys if cat[k].loc == loc and dur[k] * FPS >= nf
                        and R.fits_plate(cat[k].box, rects[ti])]
                if not pool:
                    break
                low = min(use[foot[k]] for k in pool)
                cand = [k for k in pool if use[foot[k]] <= low + 1]
                for _t in range(60):
                    k = cand[int(rng.integers(len(cand)))]
                    a = int(rng.integers(0, round(dur[k] * FPS) - nf + 1)) / FPS
                    if clips and R.frame_corr(fr(clips[-1][0], clips[-1][2] - 1 / FPS), fr(k, a)) > 0.5:
                        continue                                       # стык — заметная склейка
                    clips.append((k, a, a + nf / FPS))
                    break
                else:
                    break
            if len(clips) != nclip:
                continue
            combo = (ti, tuple(foot[c[0]] for c in clips))
            if combo in used:
                continue
            used.add(combo)
            got = clips
            break
        if got is None:
            raise SystemExit(f"не собрал ролик {n + 1}")
        for k, _a, _b in got:
            use[foot[k]] += 1
        out.append({"n": n + 1, "text": TEXTS[ti], "parts": [[k, round(a, 3), round(b, 3)] for k, a, b in got],
                    "locs": [cat[k].loc for k, _a, _b in got], "boxes": [cat[k].box for k, _a, _b in got],
                    "paths": [str(cat[k].path) for k, _a, _b in got]})
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=2)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "1300_test")
    ap.add_argument("--seed", type=int, default=1300)
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--dry", action="store_true", help="только план и статистика")
    a = ap.parse_args()
    rep = plan(a.count, a.seed)
    print(f"план: {len(rep)} роликов; 2 куска {sum(len(r['parts']) == 2 for r in rep)}, 3 куска "
          f"{sum(len(r['parts']) == 3 for r in rep)}; тексты {dict(Counter(TEXTS.index(r['text']) + 1 for r in rep))}; "
          f"локации {dict(Counter(l for r in rep for l in r['locs']))}", flush=True)
    if a.dry:
        return 0
    mus = music_master()
    a.out.mkdir(parents=True, exist_ok=True)
    pngdir = WORK / "_png" / a.out.name
    pngdir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(a.seed + 7)
    R.JOBS.clear()
    for r in rep:
        dest = a.out / f"mix_{r['n']:03d}_{ID}.mp4"
        png = pngdir / f"mix_{r['n']:03d}.png"
        r.update(plate_png(r["text"], r["boxes"], png))
        R.JOBS.append(([(Path(p), s, e) for p, (_k, s, e) in zip(r["paths"], r["parts"])], (mus, TOTAL), png, dest,
                       R.jitter(rng)))
        r["file"] = dest.name
    R.run_jobs(a.jobs)
    man = WORK / f"manifest_{a.out.name}.json"
    man.write_text(json.dumps([{k: v for k, v in r.items() if k not in ("paths",)} for r in rep], indent=1,
                              ensure_ascii=False), encoding="utf-8")
    print("готово →", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
