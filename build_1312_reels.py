#!/usr/bin/env python3
"""
1312 — OneState «bro laughed SO HARD his mic glitched», 9:16, ровно 11 с, формат рефа (TikTok 7698373540046753046):
геймплей квадратной полосой 1080×1080 по центру (y 420–1500), сверху/снизу чёрное, подпись по середине кадра —
белый TikTok Classic с тонкой чёрной обводкой. Звук — первые 11 с звука рефа (−14 LUFS), звук футажа выключен.
Промокод STATE9CNL (версия без озвучки, анимация как в 1309) — внизу геймплея ровно по центру, логотип OneState —
левый нижний угол геймплея (как в 1309/1310).

Геймплей — микс «сочных» кусков из моментов downloads/1312/scenes (Parkour.mp4, нарезан по сценам):
у каждого момента считаем движение в кадре (локальное, не панорама), находим пики действия (прыжки, трюки),
кусок 2.4–4 с берём вокруг пика. В ролике 3–4 куска из разных моментов, соседние — не из того же места.
Квадрат вырезаем там, где движение (центр по движению за кусок, мягко к центру кадра).
Наборы кусков не повторяются, частота использования кусков выравнивается.

  python build_1312_reels.py --test                 # 6 роликов → output/1312_test
  python build_1312_reels.py --count 300 --jobs 4   # → output/1312_300/NNN_1312.mp4
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402
import build_1309_reels as B  # noqa: E402  (логотип, анимация промокода, шрифт подписи)
from core.safe_zones import check_overlay  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF, FP = B.FF, B.FP
ID = "1312"
W, H, FPS, TOTAL = 1080, 1920, 60, 11.0
BAND_Y, BAND = 420, 1080                              # как в рефе: квадрат 1080×1080, y 420–1500
D = ROOT / "downloads" / "1312"
SCENES = D / "scenes"
REF = D / "ref" / "ref_7698373540046753046.mp4"
CACHE = ROOT / "output" / "1312" / "_cache"
SOUND = CACHE / "ref_sound_0-11s_-14lufs.wav"
# подпись ТЗ дословно; переносы — по смыслу
CAPTION = ["bro laughed SO HARD", "his mic glitched", "(till the end) 🛳️🛳️🛳️"]
CAP_PX, CAP_CY = 58, 960                              # как в рефе: ~58 px, центр блока на середине кадра
# одно и то же место в разных моментах — соседними не ставим
PLACES = [{2, 17}, {3, 16}, {5, 9, 19, 20}, {6, 10, 14, 22}, {7, 23}, {11, 18}, {8, 21}, {4, 12, 15, 24}]
PIECE_MIN = 2.0


# ---------------- подпись ----------------
def caption_png(dest: Path) -> None:
    f = B.font(B.F_CAP, CAP_PX)
    stroke = 3
    adv = int(CAP_PX * 1.22)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top = CAP_CY - adv * len(CAPTION) / 2
    for i, ln in enumerate(CAPTION):
        w = B.line_w(ln, f, CAP_PX)
        x = (W - w) / 2
        base = top + i * adv + f.getmetrics()[0]
        for kind, chunk in A._tokenize_runs(ln):
            if kind == "emoji":
                e = A._apple_emoji_rgba(chunk, A._emoji_px(CAP_PX))
                if e is not None:
                    img.alpha_composite(e, (int(x), int(base - e.height * 0.84)))
            else:
                d.text((x, base), chunk, font=f, anchor="ls", fill=(255, 255, 255, 255),
                       stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
            x += A._chunk_width(chunk, kind, f, CAP_PX, 0)
    bad = check_overlay(img)
    if bad:
        raise SystemExit(f"подпись вне безопасной зоны: {bad}")
    img.save(dest)


# ---------------- звук ----------------
def sound() -> Path:
    if SOUND.exists():
        return SOUND
    CACHE.mkdir(parents=True, exist_ok=True)
    meas = subprocess.run([FF, "-hide_banner", "-nostats", "-t", f"{TOTAL}", "-i", str(REF), "-vn", "-af",
                           "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                          capture_output=True, text=True).stderr
    js = json.loads(meas[meas.rindex("{"):meas.rindex("}") + 1])
    ln = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={js['input_i']}:measured_TP={js['input_tp']}:"
          f"measured_LRA={js['input_lra']}:measured_thresh={js['input_thresh']}:offset={js['target_offset']}:linear=true")
    subprocess.run([FF, "-v", "error", "-y", "-t", f"{TOTAL}", "-i", str(REF), "-vn", "-af",
                    f"{ln},afade=t=out:st={TOTAL - 0.3}:d=0.3", "-ar", "48000", "-ac", "2", str(SOUND)], check=True)
    return SOUND


# ---------------- анализ движения (кэш) ----------------
SW, SH = 128, 72


def motion(name: str) -> tuple[np.ndarray, np.ndarray]:
    """По кадрам: оценка «действия» (локальное движение, не панорама) и профиль движения по ширине кадра."""
    c = CACHE / "motion" / (Path(name).stem + ".npz")
    if c.exists():
        z = np.load(c)
        return z["score"], z["cols"]
    raw = subprocess.run([FF, "-v", "error", "-i", str(SCENES / name), "-vf", f"scale={SW}:{SH}:flags=area", "-f",
                          "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, SH, SW).astype(np.float32)
    d = np.abs(np.diff(v, axis=0, prepend=v[:1]))
    loc = np.clip(d - np.median(d, axis=(1, 2), keepdims=True) - 4, 0, None)   # минус «общий фон» (панорама)
    score = np.percentile(loc.reshape(len(loc), -1), 97, axis=1)
    cols = loc.sum(1)
    c.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(c, score=score.astype(np.float32), cols=cols.astype(np.float32))
    return score, cols


def peaks(score: np.ndarray, dur: float) -> list[tuple[float, float]]:
    """Пики действия (время, сила): сглаживание 0.5 с, максимумы не ближе 1.6 с; кадр-всплеск на склейке срезан."""
    s = np.minimum(score, np.percentile(score, 95))
    k = int(0.5 * FPS)
    sm = np.convolve(s, np.ones(k) / k, mode="same")
    order = np.argsort(-sm)
    out: list[int] = []
    for i in order:
        if all(abs(i - j) >= 1.6 * FPS for j in out):
            out.append(int(i))
        if len(out) >= max(1, round(dur / 2.5)):
            break
    return [(i / FPS, float(sm[i])) for i in sorted(out)]


def windows() -> tuple[list[dict], list[dict]]:
    mom = json.loads((SCENES / "_index.json").read_text(encoding="utf-8"))
    win = []
    allsc = []
    for mi, m in enumerate(mom, 1):
        sc, _cols = motion(m["file"])
        for t, s in peaks(sc, m["dur"]):
            win.append({"m": mi, "file": m["file"], "dur": m["dur"], "peak": t, "score": s})
            allsc.append(s)
    th = np.percentile(allsc, 30)                     # слабые пики выкидываем, но у момента остаётся лучший
    keep = []
    for mi in range(1, len(mom) + 1):
        ws = [w for w in win if w["m"] == mi]
        good = [w for w in ws if w["score"] >= th]
        keep += good or [max(ws, key=lambda w: w["score"])]
    for i, w in enumerate(keep):
        w["id"] = i
    return mom, keep


def place(m: int) -> int:
    for k, g in enumerate(PLACES):
        if m in g:
            return k
    return 100 + m


def crop_x(name: str, a: float, b: float) -> int:
    """Левый край квадрата (в кадре 1920×1080): центр по движению за кусок, на 30 % тянем к центру кадра."""
    _sc, cols = motion(name)
    seg = cols[int(a * FPS):max(int(a * FPS) + 1, int(b * FPS))].sum(0)
    if seg.sum() < 1e-3:
        cx = 960.0
    else:
        cx = float((seg * (np.arange(SW) + 0.5)).sum() / seg.sum()) / SW * 1920
    cx = 0.7 * cx + 0.3 * 960
    return int(round(min(1920 - BAND, max(0, cx - BAND / 2)) / 2) * 2)


# ---------------- план ----------------
def plan(count: int, seed: int = 1312) -> list[dict]:
    rng = random.Random(seed)
    mom, win = windows()
    use: dict[int, int] = {}
    use_m: dict[int, int] = {}
    nwin = {m: sum(w["m"] == m for w in win) for m in {w["m"] for w in win}}
    seen: set = set()
    jobs = []
    for n in range(count):
        for _ in range(2000):
            k = rng.choice([3, 3, 4])
            lens = [TOTAL / k + rng.uniform(-0.6, 0.6) for _ in range(k)]
            lens = [x * TOTAL / sum(lens) for x in lens]
            fr = [round(x * FPS) for x in lens]
            fr[-1] = round(TOTAL * FPS) - sum(fr[:-1])
            if min(fr) < PIECE_MIN * FPS:
                continue
            pieces, ok = [], True
            for L in fr:
                Ls = L / FPS
                cand = [w for w in win if w["dur"] >= Ls and w["m"] not in {p["m"] for p in pieces}
                        and (not pieces or place(w["m"]) != place(pieces[-1]["m"]))]
                if not cand:
                    ok = False
                    break
                # выравниваем: момент с большим числом пиков берём чаще, но не пропорционально (√ числа пиков),
                # внутри момента — наименее использованный пик
                pri = {m: use_m.get(m, 0) / nwin[m] ** 0.5 for m in {w["m"] for w in cand}}
                lo = min(pri.values())
                ms = [m for m, v in pri.items() if v <= lo + 1.0]
                m = rng.choice(ms)
                cm = [w for w in cand if w["m"] == m]
                low = min(use.get(w["id"], 0) for w in cm)
                w = rng.choice([w for w in cm if use.get(w["id"], 0) == low])
                a = w["peak"] - Ls * rng.uniform(0.3, 0.55)              # пик — в первой половине куска
                a = min(max(0.0, a), w["dur"] - Ls)
                a = round(a * FPS) / FPS
                pieces.append({"m": w["m"], "id": w["id"], "file": w["file"], "a": a, "len": L})
            if not ok:
                continue
            key = tuple(p["id"] for p in pieces)
            if key in seen:
                continue
            seen.add(key)
            break
        else:
            raise SystemExit(f"не собрал ролик {n + 1}")
        for p in pieces:
            use[p["id"]] = use.get(p["id"], 0) + 1
            use_m[p["m"]] = use_m.get(p["m"], 0) + 1
            p["cx"] = crop_x(p["file"], p["a"], p["a"] + p["len"] / FPS)
        jobs.append({"n": n + 1, "pieces": pieces, "seed": rng.randint(0, 10 ** 6)})
    return jobs


# ---------------- рендер ----------------
def build(job: dict) -> str:
    work = Path(tempfile.mkdtemp(prefix="r1312_"))
    rng = random.Random(job["seed"])
    cap, logo = work / "cap.png", work / "logo.png"
    caption_png(cap)
    lx, ly, _lr = B.logo_png(rng, (BAND_Y, BAND_Y + BAND), logo)
    cw, ch = B.banner_anim()
    bx = (W - cw) // 2                                     # промокод — ровно по центру по горизонтали
    by = BAND_Y + BAND - 16 - ch + round(ch * 0.06)        # низ плашки — у нижнего края геймплея
    inputs, parts = [], []
    for k, p in enumerate(job["pieces"]):
        inputs += ["-ss", f"{p['a']:.4f}", "-t", f"{p['len'] / FPS + 0.1:.4f}", "-i", str(SCENES / p["file"])]
        parts.append(f"[{k}:v]fps={FPS},scale=1920:1080:flags=lanczos,crop={BAND}:{BAND}:{p['cx']}:0,"
                     # кусок у самого конца момента бывает короче на кадр (округление -ss) — повторяем последний
                     f"tpad=stop_mode=clone:stop=3,trim=end_frame={p['len']},setpts=PTS-STARTPTS,setsar=1[v{k}]")
    n = len(job["pieces"])
    inputs += ["-loop", "1", "-i", str(cap), "-loop", "1", "-i", str(logo), "-i", str(B.BANNER_ANIM), "-i", str(sound())]
    ic, il, ib, ia = n, n + 1, n + 2, n + 3
    bt = TOTAL / 2 - 4.0                                   # промокод 8 с — по центру ролика (1.5–9.5 с), как в 1309
    parts += [
        "".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0[g]",
        f"color=black:s={W}x{H}:r={FPS}:d={TOTAL}[bg]",
        f"[bg][g]overlay=0:{BAND_Y}:shortest=1[s1]",
        f"[s1][{il}:v]overlay={lx}:{ly}[s2]",
        f"[s2][{ic}:v]overlay=0:0:shortest=1[s3]",
        f"[{ib}:v]fps={FPS},format=yuva420p,setpts=PTS-STARTPTS+{bt:.3f}/TB[bn]",
        f"[s3][bn]overlay={bx}:{by}:eof_action=pass,format=yuv420p,{SET_SDR}[v]",
    ]
    dest = Path(job["out"]) / f"{job['n']:03d}_{ID}.mp4"
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[v]", "-map",
                    f"{ia}:a", "-t", f"{TOTAL}", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(FPS),
                    *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k", "-map_metadata", "-1", "-movflags", "+faststart",
                    str(dest)], check=True)
    return f"{dest.name}: " + " + ".join(f"{p['m']:02d}@{p['a']:.1f}s×{p['len'] / FPS:.2f}" for p in job["pieces"])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=300)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--only", help="пересобрать только эти номера (через запятую)")
    a = ap.parse_args()
    B.banner_anim()
    sound()
    jobs = plan(a.count)
    used = {}
    for j in jobs:
        for p in j["pieces"]:
            used[p["m"]] = used.get(p["m"], 0) + 1
    print(f"план: {len(jobs)} роликов; кусков 3/4: {sum(len(j['pieces']) == 3 for j in jobs)}/"
          f"{sum(len(j['pieces']) == 4 for j in jobs)}; по моментам {dict(sorted(used.items()))}", flush=True)
    if a.dry:
        return 0
    if a.test:
        jobs = jobs[:6]
    out = ROOT / "output" / (f"{ID}_test" if a.test else f"{ID}_{a.count}")
    out.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        j["out"] = str(out)
    if a.only:
        nums = {int(x) for x in a.only.split(",")}
        jobs = [j for j in jobs if j["n"] in nums]
    else:
        (out / "manifest.json").write_text(json.dumps(jobs, indent=1, ensure_ascii=False), encoding="utf-8")
    with ProcessPoolExecutor(a.jobs) as ex:
        for k, msg in enumerate(ex.map(build, jobs), 1):
            print(f"[{k}/{len(jobs)}] {msg}", flush=True)
    print("готово →", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
