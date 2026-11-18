#!/usr/bin/env python3
"""
June's Journey — «найди виноград» (ID 1, ТЗ 2026-11-13): 100 TikTok + 150 YouTube × 7 с.
  — заставить искать предмет: гостиная уровня 03 в 1:21 (комната целиком, игрок ещё не зумит; кадр неподвижен);
  — виноград спрятан у окна (синяя гроздь на ручке двери, x≈990, y≈245 в кадре 2340×1080) — комната видна ЦЕЛИКОМ,
    поэтому виноград всегда в кадре;
  — раскладка как одобренный June's Journey 1 (юзер: «как у journey 1 — 5 на 4, но вся ширина видна»): полоса 5:4
    1080×864 на чёрном, в ней комната по всей ширине, сверху/снизу её размытая затемнённая копия; подпись над полосой
    TikTok-шрифтом (3 варианта ТЗ дословно, переносы по смыслу);
  — музыка: уютные треки из референсов (cozy games): Autumn Leaves, Venus and Flower, Stardew (Mori, оригинал).
БЫСТРО: сцена неподвижна → видео не декодируем: кадры собираются из одного кадра комнаты в Python и идут в NVENC.
У каждого ролика своё медленное движение комнаты внутри полосы (размер 86–100 % ширины → вся комната всегда видна;
сдвиг по высоте), высота полосы, размытый фон, цвет, музыка/старт.
УНИКАЛЬНОСТЬ ЗАРАНЕЕ: хэши кадров (6 к/с) считаются при планировании тем же способом, что и проверка; ролик
принимается, только если ни один его кадр не близок ни к одному кадру принятых — пересборок после нет.

  python build_junes_grapes.py --test                       # 6 тестов → output/_work/junes_grapes/test
  python build_junes_grapes.py --tt 100 --yt 150 --jobs 5   # → output/junesjourney_grapes_TT_100 + _YT_150 (~5–8 мин)
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_skinive2 as S2  # noqa: E402  (outline_text — TikTok-шрифт с ровной обводкой, эмодзи Apple)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS, TOTAL = 1080, 1920, 30, 7.0
NF = round(TOTAL * FPS)
BW, BH, BY = 1080, 864, 528
D = ROOT / "downloads" / "junes_journey"
SRC = D / "proxy" / "JJ_level-03_living_room.mp4"
STILL_T = 81.0                                        # 1:21 — комната целиком
WORK = ROOT / "output" / "_work" / "junes_grapes"
CAPTIONS = [
    ["Only 1% of people can find", "the hidden grapes", "in 7 seconds 🍇👀"],
    ["99% of people can't find", "the grapes in this picture 🍇"],
    ["Only 1 in 100 people", "can spot the grapes", "without help 🔎"],
]
MUSIC = [D / "music" / "autumn_leaves_timothy_cole.mp3", D / "music" / "venus_and_flower.mp3",
         D / "music" / "stardew_mori_original.mp3"]
STRIP = (650, 1500)                                   # проверка: полоса с комнатой ниже любой подписи
THR, PLAN_THR = 40, 56                                 # проверка / запас при планировании
_STILL_Q = None


# ---------------- исходный кадр ----------------
def still_rgb() -> Image.Image:
    p = WORK / "still_81.png"
    if not p.exists():
        WORK.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(STILL_T), "-i", str(SRC), "-frames:v", "1", str(p)], check=True)
    return Image.open(p).convert("RGB")


# ---------------- подписи ----------------
def caption_px() -> int:
    from core import renderer as R
    import assemble_ugc_reels as A
    for px in range(66, 36, -1):
        font, st = R._load_font(px), max(2, round(px * S2.STROKE))
        e_px = A._emoji_px(px)
        widest = max(sum(e_px * 1.08 if k == "emoji" else font.getlength(c) for k, c in A._tokenize_runs(ln) if c)
                     for cap in CAPTIONS for ln in cap)
        if widest + 2 * st <= 790:
            return px
    return 36


def caption_png(k: int, px: int, cy: int) -> Path:
    p = WORK / "text" / f"cap{k}_{px}_{cy}.png"
    if p.exists():
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    from core import renderer as R
    adv = R.line_advance_for(px)
    img = S2.outline_text(CAPTIONS[k], px, round(cy - adv * len(CAPTIONS[k]) / 2))
    if bad := check_box(W, H, img.getbbox()):
        raise SystemExit(f"подпись {k + 1} вне безопасной зоны: {bad}")
    img.save(p)
    return p


# ---------------- кадр ролика ----------------
def path_at(job: dict, t: float) -> tuple[float, float]:
    """Ширина комнаты (доля 1080) и сдвиг по высоте внутри полосы в момент t — плавно (ease in-out)."""
    u = t / TOTAL
    u = u * u * (3 - 2 * u)
    return job["s0"] + (job["s1"] - job["s0"]) * u, job["g0"] + (job["g1"] - job["g0"]) * u


def grade(im: Image.Image, job: dict) -> Image.Image:
    a = np.asarray(im).astype(np.float32)
    a = (a - 128) * job["ct"] + 128 + job["br"] * 255
    gray = a.mean(2, keepdims=True)
    a = gray + (a - gray) * job["sat"]
    a[..., 0] *= 1 + job["warm"]
    a[..., 2] *= 1 - job["warm"]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def band_bg(still: Image.Image, job: dict, q: int = 1) -> Image.Image:
    ww = round(1350 * still.width / 2340)
    x = round((still.width - ww) * job["bx"])
    win = still.crop((x, 0, x + ww, still.height))
    bg = win.resize((96, 76), Image.Resampling.BOX).filter(ImageFilter.BoxBlur(3)).resize((BW // q, BH // q), Image.Resampling.BILINEAR)
    return Image.eval(bg, lambda v: int(v * 0.78))


def frames(job: dict, q: int = 1, fps: float = FPS):
    """Кадры ролика (RGB 1080×1920 при q=1; при q=4 — уменьшенные, для предрасчёта хэшей)."""
    still = still_rgb() if q == 1 else _STILL_Q
    master = grade(still.resize((BW // q, round(BW / q * 1080 / 2340)), Image.Resampling.LANCZOS), job)
    base = Image.new("RGB", (W // q, H // q), (0, 0, 0))
    base.paste(grade(band_bg(still, job, q), job), (0, (BY + job["dy"]) // q))
    if q == 1:
        cap = Image.open(caption_png(job["caption"], job["px"], job["cy"])).convert("RGBA")
        base.paste(cap, (0, 0), cap)
    for i in range(round(TOTAL * fps)):
        s, g = path_at(job, i / fps)
        gw = max(2, round(BW * s / q / 2) * 2)
        gh = max(2, round(gw * 1080 / 2340 / 2) * 2)
        fr = base.copy()
        fr.paste(master.resize((gw, gh), Image.Resampling.BILINEAR),
                 ((W // q - gw) // 2, round((BY + job["dy"]) / q + (BH / q - gh) / 2 + g / q)))
        yield fr


def predict(job: dict) -> tuple[np.ndarray, np.ndarray]:
    """dHash 16×16 полосы STRIP кадров ролика на 6 к/с — так же, как core.uniq_check (без рендера, в масштабе ×¼)."""
    global _STILL_Q
    q = 4
    if _STILL_Q is None:
        s = still_rgb()
        _STILL_Q = s.resize((s.width // q, s.height // q), Image.Resampling.BOX)
    hs, ms = [], []
    for fr in frames(job, q=q, fps=6):
        a = np.asarray(fr.convert("L").crop((0, STRIP[0] // q, W // q, STRIP[1] // q)).resize((17, 16), Image.Resampling.BOX)).astype(np.int16)
        hs.append((a[:, 1:] > a[:, :-1]).ravel())
        ms.append((a[:, ::-1][:, 1:] > a[:, ::-1][:, :-1]).ravel())
    return np.array(hs, np.float32), np.array(ms, np.float32)


# ---------------- план ----------------
def make_job(n: int, tag: str, rng: random.Random, px0: int) -> dict:
    from core import renderer as R
    cap = n % len(CAPTIONS)
    px = px0 - rng.randint(0, 3)
    adv = R.line_advance_for(px)
    gap = rng.randint(36, 60)
    dy_min = max(0, round(206 + adv * len(CAPTIONS[cap]) + gap - BY))
    dy = rng.randint(dy_min, 120)
    s0 = rng.uniform(0.86, 1.0)
    s1 = min(1.0, max(0.86, s0 + rng.choice((-1, 1)) * rng.uniform(0.03, 0.09)))
    g0 = rng.uniform(-60, 60)
    g1 = max(-60, min(60, g0 + rng.choice((-1, 1)) * rng.uniform(10, 45)))
    m = rng.randrange(len(MUSIC))
    return dict(n=n, tag=tag, caption=cap, px=px, cy=round(BY + dy - gap - adv * len(CAPTIONS[cap]) / 2), dy=dy,
                s0=round(s0, 4), s1=round(s1, 4), g0=round(g0, 1), g1=round(g1, 1), bx=round(rng.uniform(0.1, 0.9), 3),
                music=m, mus_ss=round(rng.uniform(3, {0: 150, 1: 45, 2: 20}[m]), 2),
                br=round(rng.uniform(-0.02, 0.03), 3), ct=round(rng.uniform(0.97, 1.06), 3),
                sat=round(rng.uniform(0.98, 1.12), 3), warm=round(rng.uniform(-0.035, 0.045), 3))


def plan(tt: int, yt: int, seed: int, tries: int) -> list[dict]:
    rng = random.Random(seed)
    px0 = caption_px()
    acc: list = []
    jobs, worst = [], []
    for tag, cnt in (("tt", tt), ("yt", yt)):
        for i in range(1, cnt + 1):
            best = None
            A = np.concatenate(acc) if acc else None
            sa = A.sum(1) if acc else None
            for _ in range(tries):
                j = make_job(i, tag, rng, px0)
                Hh, Mm = predict(j)
                if acc:
                    d = min((Hh.sum(1)[:, None] + sa[None, :] - 2 * Hh @ A.T).min(),
                            (Mm.sum(1)[:, None] + sa[None, :] - 2 * Mm @ A.T).min())
                else:
                    d = 256.0
                if best is None or d > best[0]:
                    best = (d, j, Hh)
                if d > PLAN_THR:
                    break
            d, j, Hh = best
            jobs.append(j)
            acc.append(Hh)
            worst.append(float(d))
            caption_png(j["caption"], j["px"], j["cy"])
    w = sorted(worst[1:])
    print(f"план: {len(jobs)} роликов; ближайший кадр к чужому ролику — минимум {w[0]:.0f} бит, медиана {w[len(w) // 2]:.0f} "
          f"(проверка считает совпадением ≤ {THR}); роликов ≤ {THR}: {sum(x <= THR for x in w)}", flush=True)
    return jobs


# ---------------- рендер (без декода: кадры → NVENC) ----------------
def music_norm(i: int) -> Path:
    p = WORK / f"music{i}_-15lufs.wav"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(MUSIC[i]), "-af", "loudnorm=I=-15:TP=-1.5:LRA=11",
                        "-ar", "48000", "-ac", "2", str(p)], check=True)
    return p


def build(job: dict) -> str:
    dest = Path(job["out"]) / f"{job['n']:03d}_1.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-ss", f"{job['mus_ss']:.2f}", "-t", f"{TOTAL + 0.5}", "-i", str(music_norm(job["music"])),
           "-filter_complex", f"[1:a]atrim=0:{TOTAL},asetpts=PTS-STARTPTS,afade=t=in:d=0.3,afade=t=out:st={TOTAL - 0.4}:d=0.4[a]",
           "-map", "0:v", "-map", "[a]", "-frames:v", str(NF), "-t", f"{TOTAL}",
           "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
           "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-c:a", "aac", "-b:a", "192k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
           "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
           "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fr in frames(job):
        pr.stdin.write(fr.tobytes())
    pr.stdin.close()
    if pr.wait() != 0:
        raise RuntimeError(f"{dest.name}: ffmpeg {pr.returncode}")
    return f"{job['tag']} {dest.name}: ширина {job['s0']:.2f}→{job['s1']:.2f}, высота полосы +{job['dy']}"


def run(jobs: list[dict], out: Path, workers: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        j["out"] = str(out)
    with ProcessPoolExecutor(workers) as ex:
        for k, msg in enumerate(ex.map(build, jobs), 1):
            print(f"  [{out.name} {k}/{len(jobs)}] {msg}", flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tt", type=int, default=100)
    ap.add_argument("--yt", type=int, default=150)
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--seed", type=int, default=7373)
    ap.add_argument("--tries", type=int, default=80)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--plan-only", action="store_true")
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    still_rgb()
    for i in range(len(MUSIC)):
        music_norm(i)
    pf = WORK / f"plan_{a.tt}_{a.yt}_{a.seed}.json"
    if pf.exists():
        jobs = json.loads(pf.read_text(encoding="utf-8"))
        for j in jobs:
            caption_png(j["caption"], j["px"], j["cy"])
    else:
        jobs = plan(a.tt, a.yt, a.seed, a.tries)
        pf.write_text(json.dumps(jobs, indent=0), encoding="utf-8")
    if a.plan_only:
        return 0
    if a.test:
        tj = jobs[:3] + [dict(j, n=j["n"] + 100) for j in jobs[a.tt:a.tt + 3]]
        run(tj, WORK / "test", a.jobs)
        return 0
    outs = {"tt": ROOT / "output" / f"junesjourney_grapes_TT_{a.tt}", "yt": ROOT / "output" / f"junesjourney_grapes_YT_{a.yt}"}
    for tag in ("tt", "yt"):
        run([j for j in jobs if j["tag"] == tag], outs[tag], a.jobs)
    from core.uniq_check import similarity
    files = [outs[j["tag"]] / f"{j['n']:03d}_1.mp4" for j in jobs]
    pair, _ = similarity(files, strips=[STRIP], fps=6, thr=THR, cache=WORK / "hash_check.npz")
    tri = pair[np.triu_indices(len(files), 1)]
    print(f"ПРОВЕРКА: худшая пара {tri.max() * 100:.1f} %, среднее {tri.mean() * 100:.3f} %, пар с общими кадрами "
          f"{int((tri > 0).sum())} из {len(tri)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
