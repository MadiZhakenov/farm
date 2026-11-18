#!/usr/bin/env python3
"""
June's Journey — оба проекта, раскладка B (юзер 2026-11-13: «со второй фотки, где по центру, и шрифт поменьше»):
  полоса 16:9 (1080×608, видно 82 % ширины игры) по центру экрана на чёрном, подпись ПОСЕРЕДИНЕ поверх игры,
  TikTok-шрифт с ровной обводкой, мельче прежнего.
    cozy   — уютные моменты 6 уровней (3 куска по ~2.3 с), подписи «they don't make games…» и т. д.;
    grapes — «найди виноград»: гостиная уровня 03 в 1:21 целиком (неподвижный кадр), виноград у окна всегда в кадре.
УНИКАЛЬНОСТЬ ГАРАНТИРУЕТСЯ ДО СБОРКИ (юзер: «без миллиона кругов»): каждый кадр каждого ролика (6 к/с) заранее
считается тем же способом, что и проверка — dHash 16×16 ВСЕГО кадра 1080×1920 (как видит платформа), с зеркалом;
ролик принимается в план, только если ни один его кадр не ближе PLAN_THR (52) бит ни к одному кадру уже принятых.
Проверка после сборки — один проход (core.uniq_check, порог 40, 6 к/с). Рычаги различия: время (cozy), окно
кадра (зум 1.0–1.12, сдвиг ≤ ±60 px — объект по центру), размер полосы (90–100 %), высота полосы (±90 px), подпись,
цвет, музыка; у grapes ещё медленный наезд/сдвиг окна в каждом ролике.

  python build_junes_v3.py --proj grapes --test
  python build_junes_v3.py --proj cozy   --tt 100 --yt 150 --jobs 5   # → output/junes_journey_2_TT_100 + _YT_150
  python build_junes_v3.py --proj grapes --tt 100 --yt 150 --jobs 5   # → output/junes_journey_3_TT_100 + _YT_150
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
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_skinive2 as S2  # noqa: E402  (outline_text — TikTok-шрифт с ровной обводкой, эмодзи Apple)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS, TOTAL = 1080, 1920, 30, 7.0
NF = round(TOTAL * FPS)
SW, SH = 2340, 1080                                   # кадр прокси
Q = 8                                                  # масштаб предрасчёта (135×240)
HFPS, THR, PLAN_THR = 6, 40, 52
STRIP = (520, 1400)                                    # хэш/проверка — полоса с игрой при любой высоте (чёрные поля
                                                       # одинаковы у всех роликов: по всему кадру различимы лишь ~80 бит из 256)
D = ROOT / "downloads" / "junes_journey"
PROXY = D / "proxy"
MUSIC = [D / "music" / "autumn_leaves_timothy_cole.mp3", D / "music" / "venus_and_flower.mp3",
         D / "music" / "stardew_mori_original.mp3"]
PROJ = {
    "cozy": dict(
        work=ROOT / "output" / "_work" / "junes_v3_cozy", out="junes_journey_2",
        captions=[["they don't make games", "like this anymore", "btw i found smth like that"],
                  ["does anyone remember", "games like these?", "nothing beats those old", "hidden-object games"],
                  ["i wish games still felt", "like they did in 2005", "btw i found smth like that"]],
        spans={"01": [(42.0, 49.0), (96.5, 106.5)], "02": [(29.5, 60.0), (125.5, 196.0)], "03": [(77.0, 212.0)],
               "04": [(116.0, 268.0)], "05": [(21.0, 106.0)], "06": [(16.0, 200.0)]},
        game_audio=True),
    "grapes": dict(
        work=ROOT / "output" / "_work" / "junes_v3_grapes", out="junes_journey_3",
        captions=[["Only 1% of people can find", "the hidden grapes", "in 7 seconds 🍇👀"],
                  ["99% of people can't find", "the grapes in this picture 🍇"],
                  ["Only 1 in 100 people", "can spot the grapes", "without help 🔎"]],
        still=(PROXY / "JJ_level-03_living_room.mp4", 81.0), game_audio=False),
}
P: dict = {}
LV_FILE = {k: next(PROXY.glob(f"JJ_level-{k}_*.mp4")) for k in ("01", "02", "03", "04", "05", "06")}


# ---------------- подпись ----------------
def caption_px() -> int:
    """Кегль подписи: −30 % от прежнего (юзер 2026-11-13): cozy было 64 → 45, grapes было 62 → 43."""
    return {"junes_journey_2": 45, "junes_journey_3": 43}[P["out"]]


def caption_png(k: int, px: int, cy: int) -> Path:
    p = P["work"] / "text" / f"cap{k}_{px}_{cy}.png"
    if p.exists():
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    from core import renderer as R
    adv = R.line_advance_for(px)
    img = S2.outline_text(P["captions"][k], px, round(cy - adv * len(P["captions"][k]) / 2))
    if bad := check_box(W, H, img.getbbox()):
        raise SystemExit(f"подпись {k + 1} вне безопасной зоны: {bad}")
    img.save(p)
    return p


_CAP_SMALL: dict = {}


def caption_small(k: int, px: int, cy: int) -> tuple[np.ndarray, np.ndarray]:
    """Подпись в масштабе 1/8: рисуется один раз на (вариант, кегль) при cy=960, для другой высоты — сдвиг строк."""
    key = (k, px)
    if key not in _CAP_SMALL:
        im = Image.open(caption_png(k, px, H // 2)).convert("RGBA")
        a = np.asarray(im.getchannel("A").resize((W // Q, H // Q), Image.Resampling.BOX)).astype(np.float32) / 255
        lum = Image.new("L", im.size, 0)
        lum.paste(im.convert("L"), (0, 0), im.getchannel("A"))
        L = np.asarray(lum.resize((W // Q, H // Q), Image.Resampling.BOX)).astype(np.float32)
        _CAP_SMALL[key] = (L / np.maximum(a, 1e-3), a)
    L, a = _CAP_SMALL[key]
    sh = round((cy - H // 2) / Q)
    return np.roll(L, sh, 0), np.roll(a, sh, 0)


# ---------------- геометрия ----------------
def window(z: float, px: float, py: float) -> tuple[float, float, float, float]:
    """Окно 16:9 в кадре прокси: зум z, сдвиг центра px/py (px ограничен — объект по центру)."""
    ww, wh = 1920 / z, 1080 / z
    x0 = min(max(0.0, (SW - ww) / 2 + px), SW - ww)
    y0 = min(max(0.0, (SH - wh) / 2 + py), SH - wh)
    return x0, y0, ww, wh


def band_box(job: dict) -> tuple[int, int, int, int]:
    bw = round(W * job["s"] / 2) * 2
    bh = round(bw * 9 / 16 / 2) * 2
    return (W - bw) // 2, round(H / 2 + job["dy"] - bh / 2), bw, bh


def geo_at(job: dict, t: float) -> tuple[float, float, float]:
    u = t / TOTAL
    u = u * u * (3 - 2 * u)
    return (job["z0"] + (job["z1"] - job["z0"]) * u, job["px0"] + (job["px1"] - job["px0"]) * u,
            job["py0"] + (job["py1"] - job["py0"]) * u)


# ---------------- исходники для предрасчёта (×1/8, 6 к/с) ----------------
_SRC: dict = {}


def src_small(lvl: str) -> tuple[float, np.ndarray]:
    """Кадры отрезков уровня 6 к/с, 292×135 серые — кэш на диске."""
    if lvl not in _SRC:
        f = P["work"] / f"src_{lvl}.npz"
        if not f.exists():
            spans = P["spans"][lvl]
            t0, t1 = min(a for a, _ in spans), max(b for _, b in spans)
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0 + 1:.3f}", "-i", str(LV_FILE[lvl]),
                                  "-vf", f"fps={HFPS},scale={SW // Q}:{SH // Q}:flags=area,format=gray", "-f", "rawvideo", "-"],
                                 capture_output=True).stdout
            arr = np.frombuffer(raw, np.uint8).reshape(-1, SH // Q, SW // Q)
            f.parent.mkdir(parents=True, exist_ok=True)
            np.savez(f, t0=t0, a=arr)
        d = np.load(f)
        _SRC[lvl] = (float(d["t0"]), d["a"])
    return _SRC[lvl]


_STILL: dict = {}


def still_img(small: bool) -> Image.Image:
    if small not in _STILL:
        p = P["work"] / "still.png"
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            src, t = P["still"]
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", str(src), "-frames:v", "1", str(p)], check=True)
        im = Image.open(p).convert("RGB")
        _STILL[small] = im.convert("L").resize((SW // Q, SH // Q), Image.Resampling.BOX) if small else im
    return _STILL[small]


def predict(job: dict) -> tuple[np.ndarray, np.ndarray]:
    """dHash 16×16 всего кадра на 6 к/с (как core.uniq_check с strips=None) — без рендера, в масштабе 1/8."""
    bx, by, bw, bh = band_box(job)
    capL, capA = caption_small(job["caption"], job["px"], job["cy"])
    hs, ms = [], []
    for i in range(round(TOTAL * HFPS)):
        t = i / HFPS
        if "pieces" in job:                                  # cozy: кусок, в который попадает t
            acc = 0.0
            for pc in job["pieces"]:
                if t < acc + pc["len"] or pc is job["pieces"][-1]:
                    break
                acc += pc["len"]
            t0, arr = src_small(pc["lvl"])
            fi = min(len(arr) - 1, max(0, round((pc["a"] + (t - acc) - t0) * HFPS)))
            src = Image.fromarray(arr[fi])
            z, px_, py_ = pc["z"], pc["px"], pc["py"]
            cw = 1920 if pc.get("cut") else SW
            x0, y0, ww, wh = window(z, px_, py_) if not pc.get("cut") else ((SW - 1920 / z) / 2, (SH - 1080 / z) / 2, 1920 / z, 1080 / z)
            del cw
        else:                                               # grapes: неподвижный кадр, окно плывёт
            src = still_img(True)
            z, px_, py_ = geo_at(job, t)
            x0, y0, ww, wh = window(z, px_, py_)
        crop = src.crop((round(x0 / Q), round(y0 / Q), round((x0 + ww) / Q), round((y0 + wh) / Q)))
        band = crop.resize((max(1, round(bw / Q)), max(1, round(bh / Q))), Image.Resampling.BOX)
        cv = Image.new("L", (W // Q, H // Q), 0)
        cv.paste(band, (round(bx / Q), round(by / Q)))
        a = np.asarray(cv).astype(np.float32)
        a = a * (1 - capA) + capL * capA
        a = a[STRIP[0] // Q:STRIP[1] // Q]
        h = np.asarray(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).resize((17, 16), Image.Resampling.BOX)).astype(np.int16)
        hs.append((h[:, 1:] > h[:, :-1]).ravel())
        ms.append((h[:, ::-1][:, 1:] > h[:, ::-1][:, :-1]).ravel())
    return np.array(hs, np.float32), np.array(ms, np.float32)


# ---------------- план ----------------
def make_job(proj: str, n: int, tag: str, rng: random.Random, px0: int) -> dict:
    from core import renderer as R
    cap = n % len(P["captions"])
    px = px0 - rng.randint(0, 2)
    s = 1.0                                              # полоса во всю ширину — без чёрных полей по бокам (юзер)
    dy = rng.randint(-130, 130)
    job = dict(n=n, tag=tag, caption=cap, px=px, cy=round(H / 2 + dy + rng.randint(-45, 45)), s=s, dy=dy,
               music=(m := rng.randrange(len(MUSIC))), mus_ss=round(rng.uniform(3, {0: 150, 1: 45, 2: 20}[m]), 2),
               br=round(rng.uniform(-0.02, 0.03), 3), ct=round(rng.uniform(0.97, 1.06), 3),
               sat=round(rng.uniform(0.98, 1.12), 3), warm=round(rng.uniform(-0.035, 0.045), 3))
    del R
    if proj == "cozy":
        lv = rng.sample(sorted(P["spans"]), 3)
        lens = [rng.uniform(2.0, 2.7) for _ in range(3)]
        lens = [x * TOTAL / sum(lens) for x in lens]
        fr = [round(x * FPS) for x in lens]
        fr[-1] = NF - sum(fr[:-1])
        pieces = []
        for k, L in zip(lv, fr):
            span = rng.choice([sp for sp in P["spans"][k] if sp[1] - sp[0] >= L / FPS + 0.2])
            cut = k == "01" and span[0] >= 90                     # заставка: картинка 16:9 ровно по центру (поля срезаны)
            pieces.append(dict(lvl=k, a=round(rng.uniform(span[0], span[1] - L / FPS - 0.1), 3), len=round(L / FPS, 4),
                               frames=L, z=(z := round(rng.uniform(1.0, 1.2), 3)),
                               px=0.0 if cut else round(rng.uniform(-1, 1) * (SW - 1920 / z) / 2, 1),
                               py=round(rng.uniform(-1, 1) * (SH - 1080 / z) / 2, 1), cut=cut))
        job["pieces"] = pieces
        job["game_vol"] = round(rng.uniform(0.28, 0.4), 3)
    else:
        # окно: зум 1.0–1.25, гроздь (x 945–1035, y 190–295 в кадре 2340×1080) всегда целиком в кадре и в верхней трети
        # окна; место окна вокруг грозди — любое допустимое → у каждого ролика свой ракурс комнаты; дрейф за 7 с мал
        from core import renderer as R
        adv = R.line_advance_for(px)
        nl = len(P["captions"][cap])
        for _ in range(60):
            z0 = rng.uniform(1.0, 1.25)
            z1 = min(1.25, max(1.0, z0 + rng.choice((-1, 1)) * rng.uniform(0.005, 0.015)))
            ww, wh = 1920 / max(z0, z1), 1080 / max(z0, z1)
            xlo, xhi = max(0.0, 1035 + 70 - ww), min(SW - ww, 945 - 70)
            ylo, yhi = max(0.0, 295 + 14 - wh * 0.40), min(SH - wh, 190 - wh * 0.05)
            if xlo > xhi or ylo > yhi:
                continue
            x0, y0 = rng.uniform(xlo, xhi), rng.uniform(ylo, yhi)
            px0, py0 = x0 - (SW - ww) / 2, y0 - (SH - wh) / 2
            job.update(z0=round(z0, 4), z1=round(z1, 4), px0=round(px0, 1), px1=round(px0 + rng.uniform(-10, 10), 1),
                       py0=round(py0, 1), py1=round(py0 + rng.uniform(-6, 6), 1))
            # подписью виноград не закрываем: верх подписи — ниже грозди, низ — внутри полосы
            bx, by, bw, bh = band_box(job)
            gb = max(by + (295 - window(z, x, y)[1]) / window(z, x, y)[3] * bh
                     for z, x, y in ((job["z0"], job["px0"], job["py0"]), (job["z1"], job["px1"], job["py1"])))
            cy = max(job["cy"], round(gb + 24 + adv * nl / 2))
            if cy + adv * nl / 2 < by + bh - 12:
                job["cy"] = cy
                break
        else:
            raise RuntimeError("не нашёл окно с виноградом")
    return job


def _retry(f, *a):
    """Память компьютера иногда кончается из-за чужих сборок (ffmpeg на 20+ ГБ) — ждём и повторяем, план не роняем."""
    import time
    for k in range(120):
        try:
            return f(*a)
        except MemoryError:
            time.sleep(3)
    return f(*a)


def plan(proj: str, tt: int, yt: int, seed: int, tries: int) -> list[dict]:
    rng = random.Random(seed)
    px0 = caption_px()
    acc: list = []
    jobs, worst = [], []
    for tag, cnt in (("tt", tt), ("yt", yt)):
        for i in range(1, cnt + 1):
            A = _retry(np.concatenate, acc) if acc else None
            sa = A.sum(1) if acc else None
            best = None
            for _ in range(tries):
                j = make_job(proj, i, tag, rng, px0)
                Hh, Mm = _retry(predict, j)
                d = 256.0 if not acc else _retry(lambda: float(min((Hh.sum(1)[:, None] + sa[None, :] - 2 * Hh @ A.T).min(),
                                                                   (Mm.sum(1)[:, None] + sa[None, :] - 2 * Mm @ A.T).min())))
                if best is None or d > best[0]:
                    best = (d, j, Hh)
                if d > PLAN_THR:
                    break
            d, j, Hh = best
            jobs.append(j)
            acc.append(Hh)
            worst.append(d)
            if len(jobs) % 25 == 0:
                print(f"  план {proj}: {len(jobs)}/{tt + yt}, у последнего ближайший чужой кадр {d:.0f} бит", flush=True)
    for j in jobs:
        caption_png(j["caption"], j["px"], j["cy"])
    w = sorted(worst[1:])
    print(f"план {proj}: {len(jobs)} роликов; ближайший кадр к чужому ролику — минимум {w[0]:.0f} бит, медиана "
          f"{w[len(w) // 2]:.0f}; роликов ≤ {THR} бит (совпадение): {sum(x <= THR for x in w)}", flush=True)
    return jobs


# ---------------- рендер ----------------
def music_norm(i: int) -> Path:
    p = ROOT / "output" / "_work" / "junes_v3_music" / f"music{i}_-15lufs.wav"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(MUSIC[i]), "-af", "loudnorm=I=-15:TP=-1.5:LRA=11",
                        "-ar", "48000", "-ac", "2", str(p)], check=True)
    return p


ENC = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
       "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
       "-c:a", "aac", "-b:a", "192k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
       "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
       "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart"]


def grade_expr(job: dict) -> str:
    g = 1 + job["warm"]
    return f"eq=brightness={job['br']}:contrast={job['ct']}:saturation={job['sat']}:gamma_r={g:.3f}:gamma_b={2 - g:.3f}"


def caption_crop(cap: Path) -> tuple[Path, int, int]:
    out = cap.with_name(cap.stem + "_crop.png")
    im = Image.open(cap).convert("RGBA")
    x0, y0, x1, y1 = im.getbbox()
    x0, y0 = x0 // 2 * 2, y0 // 2 * 2
    if not out.exists():
        im.crop((x0, y0, x1 + (x1 - x0) % 2, y1 + (y1 - y0) % 2)).save(out)
    return out, x0, y0


def vname(job: dict) -> str:
    """Имя ролика (юзер 2026-11-13): junes_journey_2_tt_001_1.mp4 — проект, площадка, номер, ID 1."""
    return f"{P['out']}_{job['tag']}_{job['n']:03d}_1.mp4"


def build(job: dict) -> str:
    from core.gpu_slots import gpu_slot
    dest = Path(job["out"]) / vname(job)
    cap, cx, cy = caption_crop(caption_png(job["caption"], job["px"], job["cy"]))
    bx, by, bw, bh = band_box(job)
    mus = ["-ss", f"{job['mus_ss']:.2f}", "-t", f"{TOTAL + 0.5}", "-i", str(music_norm(job["music"]))]
    if "pieces" in job:
        ins, parts, alab = [], [], []
        for k, p in enumerate(job["pieces"]):
            x0, y0, ww, wh = window(p["z"], p["px"], p["py"]) if not p["cut"] else                 ((SW - 1920 / p["z"]) / 2, (SH - 1080 / p["z"]) / 2, 1920 / p["z"], 1080 / p["z"])
            L, T = round(x0 / 2) * 2, round(y0 / 2) * 2
            R_, B_ = SW - L - round(ww / 2) * 2, SH - T - round(wh / 2) * 2
            ins += ["-c:v", "h264_cuvid", "-crop", f"{T}x{max(0, B_)}x{L}x{max(0, R_)}", "-resize", f"{bw}x{bh}",
                    "-ss", f"{p['a']:.3f}", "-t", f"{p['len'] + 0.2:.3f}", "-i", str(LV_FILE[p["lvl"]])]
            parts.append(f"[{k}:v]fps={FPS},format=yuv420p,setsar=1,tpad=stop_mode=clone:stop=3,"
                         f"trim=end_frame={p['frames']},setpts=PTS-STARTPTS[v{k}]")
            parts.append(f"[{k}:a]atrim=0:{p['len']:.3f},asetpts=PTS-STARTPTS,aresample=48000,afade=t=in:d=0.05,"
                         f"afade=t=out:st={p['len'] - 0.06:.3f}:d=0.06[ga{k}]")
            alab.append(f"[ga{k}]")
        n = len(job["pieces"])
        parts += ["".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0,{grade_expr(job)},format=yuv420p,"
                  f"pad={W}:{H}:{bx}:{by}:black[s1]",
                  f"[s1][{n}:v]overlay={cx}:{cy}:shortest=1,tpad=stop_mode=clone:stop=3,format=yuv420p[v]",
                  "".join(alab) + f"concat=n={n}:v=0:a=1,volume={job['game_vol']}[game]",
                  f"[{n + 1}:a]atrim=0:{TOTAL},asetpts=PTS-STARTPTS,afade=t=in:d=0.3[mus]",
                  f"[mus][game]amix=inputs=2:normalize=0:duration=first,atrim=0:{TOTAL},afade=t=out:st={TOTAL - 0.4}:d=0.4[a]"]
        with gpu_slot():                                    # общий лимит видеокарты (≤ 3 ffmpeg на машину)
            cmd = ["ffmpeg", "-v", "error", "-y", *ins, "-loop", "1", "-i", str(cap), *mus, "-filter_complex", ";".join(parts),
                   "-map", "[v]", "-map", "[a]", "-frames:v", str(NF), "-t", f"{TOTAL}", "-r", str(FPS), *ENC, str(dest)]
            subprocess.run(cmd, check=True, timeout=300)
        return f"cozy {job['tag']} {dest.name}"
    # grapes: на ВИДЕОКАРТЕ (torch) только полоса — вырез окна + масштаб; в ffmpeg идёт кадр полосы (1.6 МБ, не 6),
    # ffmpeg ставит её на чёрный (pad) и кладёт подпись, NVENC; декода нет
    import torch
    import torch.nn.functional as F
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    st = torch.from_numpy(np.array(still_img(False))).to(dev).permute(2, 0, 1)[None].float()
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{bw}x{bh}", "-r", str(FPS), "-i", "-",
           "-loop", "1", "-i", str(cap), *mus,
           "-filter_complex", f"[0:v]{grade_expr(job)},format=yuv420p,pad={W}:{H}:{bx}:{by}:black[b];"
           f"[b][1:v]overlay={cx}:{cy}:shortest=1,format=yuv420p[v];"
           f"[2:a]atrim=0:{TOTAL},asetpts=PTS-STARTPTS,afade=t=in:d=0.3,afade=t=out:st={TOTAL - 0.4}:d=0.4[a]",
           "-map", "[v]", "-map", "[a]", "-frames:v", str(NF), "-t", f"{TOTAL}", *ENC, str(dest)]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    with torch.no_grad():
        for i in range(NF):
            z, px_, py_ = geo_at(job, i / FPS)
            x0, y0, ww, wh = window(z, px_, py_)
            crop = st[:, :, round(y0):round(y0 + wh), round(x0):round(x0 + ww)]
            band = F.interpolate(crop, size=(bh, bw), mode="bilinear", align_corners=False, antialias=True)[0]
            pr.stdin.write(band.clamp(0, 255).round().to(torch.uint8).permute(1, 2, 0).contiguous().cpu().numpy().data)
    pr.stdin.close()
    if pr.wait() != 0:
        raise RuntimeError(f"{dest.name}: ffmpeg {pr.returncode}")
    return f"grapes {job['tag']} {dest.name}"


def _init(proj: str) -> None:
    P.clear()
    P.update(PROJ[proj])


def _build(args: tuple) -> str:
    import time
    proj, job = args
    _init(proj)
    for k in range(4):                     # видеокарта занята чужими сборками (кодировщик/память) — ждём и повторяем
        try:
            return build(job)
        except Exception:                  # noqa: BLE001
            if k == 3:
                raise
            time.sleep(5 + 5 * k)


def run(proj: str, jobs: list[dict], out: Path, workers: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        j["out"] = str(out)
    with ProcessPoolExecutor(workers) as ex:
        for k, msg in enumerate(ex.map(_build, [(proj, j) for j in jobs]), 1):
            print(f"  [{out.name} {k}/{len(jobs)}] {msg}", flush=True)


def fix(proj: str, jobs: list[dict], files: list[Path], seed: int, workers: int, rounds: int = 8) -> None:
    """Гарантия по НАСТОЯЩИМ файлам: хэши готовых роликов → минимальный набор роликов с общими кадрами → для каждого
    кандидат (из 40 вариантов — с наибольшим расчётным отличием) → рендер → хэш файла → принят, только если ни один его
    кадр не ближе THR ни к одному кадру остальных роликов (с зеркалом). Иначе — следующий кандидат. Остальные не трогаем."""
    import shutil
    from concurrent.futures import ThreadPoolExecutor
    from core.uniq_check import bad_set, hashes, similarity, vhash
    FPSS = (6, 3)                                                  # обе проверки: строгая 6 к/с и «как Skinive» 3 к/с
    pair = np.maximum(*[similarity(files, strips=[STRIP], fps=f, thr=THR, cache=P["work"] / f"hash_full{f}.npz")[0]
                        for f in FPSS])
    pend = bad_set(pair)
    print(f"фикс {proj}: роликов с общими кадрами (минимальный набор) — {len(pend)}", flush=True)
    if not pend:
        return
    Hd = {f: hashes(files, [STRIP], f, P["work"] / f"hash_full{f}.npz") for f in FPSS}
    act = {i: np.concatenate([Hd[f][str(x)] for f in FPSS]) for i, x in enumerate(files)}   # кадры 6 и 3 к/с вместе
    rng = random.Random(seed * 7 + 13)
    px0 = caption_px()
    tmp = P["work"] / "fix"
    tmp.mkdir(parents=True, exist_ok=True)

    def mind(C: np.ndarray, others: list[int]) -> float:
        A = np.concatenate([act[k][:, 0] for k in others]).astype(np.float32)
        M = np.concatenate([act[k][:, 1] for k in others]).astype(np.float32)
        C = C.astype(np.float32)
        sc = C.sum(1)[:, None]
        return float(min((sc + A.sum(1)[None] - 2 * C @ A.T).min(), (sc + M.sum(1)[None] - 2 * C @ M.T).min()))

    for r in range(1, rounds + 1):
        ok_set = [k for k in range(len(files)) if k not in pend]
        cand = []
        for i in pend:
            best = None
            for _ in range(40):
                j = make_job(proj, jobs[i]["n"], jobs[i]["tag"], rng, px0)
                d = mind(predict(j)[0], ok_set)
                if best is None or d > best[0]:
                    best = (d, j)
            j = dict(best[1], out=str(tmp / f"r{r}_{jobs[i]['tag']}"))
            cand.append((i, j))
        for _, j in cand:
            Path(j["out"]).mkdir(parents=True, exist_ok=True)
        with ProcessPoolExecutor(workers) as ex:
            list(ex.map(_build, [(proj, j) for _, j in cand]))
        outs = [Path(j["out"]) / vname(j) for _, j in cand]
        with ThreadPoolExecutor(8) as ex:
            hs = list(ex.map(lambda f: np.concatenate([vhash(f, [STRIP], q) for q in FPSS]), outs))
        still = []
        for (i, j), f, h in zip(cand, outs, hs):
            others = [k for k in range(len(files)) if k != i and (k not in pend or act.get(("ok", k)))]
            if mind(h[:, 0], others) > THR:
                shutil.move(str(f), str(files[i]))
                act[i] = h
                act[("ok", i)] = True
                jobs[i] = {kk: vv for kk, vv in j.items() if kk != "out"}
            else:
                still.append(i)
        print(f"  фикс {proj}, круг {r}: заменено {len(pend) - len(still)}, осталось {len(still)}", flush=True)
        pend = still
        if not pend:
            break


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--proj", choices=sorted(PROJ), required=True)
    ap.add_argument("--tt", type=int, default=100)
    ap.add_argument("--yt", type=int, default=150)
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--seed", type=int, default=9191)
    ap.add_argument("--tries", type=int, default=160)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--fix", action="store_true", help="только заменить ролики с общими кадрами (по готовым файлам)")
    a = ap.parse_args()
    _init(a.proj)
    P["work"].mkdir(parents=True, exist_ok=True)
    for i in range(len(MUSIC)):
        music_norm(i)
    pf = P["work"] / f"plan_{a.tt}_{a.yt}_{a.seed}.json"
    if pf.exists():
        jobs = json.loads(pf.read_text(encoding="utf-8"))
        for j in jobs:
            caption_png(j["caption"], j["px"], j["cy"])
    else:
        jobs = plan(a.proj, a.tt, a.yt, a.seed, a.tries)
        pf.write_text(json.dumps(jobs, indent=0), encoding="utf-8")
    if a.plan_only:
        return 0
    if a.test:
        tj = jobs[:3] + [dict(j, n=j["n"] + 100) for j in jobs[a.tt:a.tt + 3]]
        run(a.proj, tj, P["work"] / "test", a.jobs)
        return 0
    outs = {"tt": ROOT / "output" / f"{P['out']}_TT_{a.tt}", "yt": ROOT / "output" / f"{P['out']}_YT_{a.yt}"}
    if not a.fix:
        for tag in ("tt", "yt"):
            run(a.proj, [j for j in jobs if j["tag"] == tag], outs[tag], a.jobs)
    from core.uniq_check import similarity
    files = [outs[j["tag"]] / vname(j) for j in jobs]
    fix(a.proj, jobs, files, a.seed, a.jobs)
    pf.write_text(json.dumps(jobs, indent=0), encoding="utf-8")
    for fps, name in ((6, "строгая, 6 к/с"), (3, "как замер Skinive, 3 к/с")):
        pair, _ = similarity(files, strips=[STRIP], fps=fps, thr=THR, cache=P["work"] / f"hash_full{fps}.npz")
        tri = pair[np.triu_indices(len(files), 1)]
        print(f"ПРОВЕРКА ({name}, полоса с игрой, порог {THR}): худшая пара {tri.max() * 100:.1f} %, среднее {tri.mean() * 100:.3f} %, "
              f"пар с общими кадрами {int((tri > 0).sum())} из {len(tri)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
