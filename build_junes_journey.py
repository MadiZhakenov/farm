#!/usr/bin/env python3
"""
June's Journey (ID 1, 2026-11-13, срочно): 100 TikTok + 150 YouTube × 7 с.
  — самые уютные/эстетичные моменты игры (поиск предметов в комнатах, заставка на закате) — отрезки SPANS,
    отобраны по листам кадров; меню, счёт, загрузки, реклама, экраны iPhone исключены;
  — горизонтальная запись → полоса 5:4 (1080×864) по центру кадра 9:16 на чёрном, как в OneState 1312;
    окно кадра по центру (сдвиг ≤ ~±50 px), лёгкий зум 1.0–1.12;
  — посередине одна статичная подпись на весь ролик (3 варианта ТЗ, дословно, переносы по смыслу), TikTok-шрифт,
    белый с ровной чёрной обводкой;
  — звук: уютная музыка (из референсов: Autumn Leaves — Timothy Cole, Venus and Flower) + звук игры тише
    (щелчки/звон находок; в записи игры под ними её собственная музыка);
  — 3 отрезка из разных уровней; каждый ролик берёт наименее использованные секунды исходников; цвет, старт
    музыки, раскладка — свои. Декод — на видеокарте через общий core.gpu_slots (≤ 3 одновременно), NVENC.

  python build_junes_journey.py --test
  python build_junes_journey.py --tt 100 --yt 150 --jobs 3   # → output/junesjourney_TT_100 + junesjourney_YT_150
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

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_skinive2 as S2  # noqa: E402  (outline_text — TikTok-шрифт с ровной обводкой)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS, TOTAL = 1080, 1920, 30, 7.0
BW, BH = 1080, 864                                   # 5:4
BY = (H - BH) // 2                                    # 528
D = ROOT / "downloads" / "junes_journey"
PROXY = D / "proxy"
WORK = ROOT / "output" / "_work" / "junes_journey"
SPANS = {  # (уровень, старт, конец) — поиск предметов / заставка; поля по 1 с от границ
    "01": [(42.0, 49.0), (96.5, 106.5)],
    "02": [(29.5, 60.0), (125.5, 196.0)],
    "03": [(77.0, 212.0)],
    "04": [(116.0, 268.0)],
    "05": [(21.0, 106.0)],
    "06": [(16.0, 200.0)],
}
FILES = {k: next(PROXY.glob(f"JJ_level-{k}_*.mp4")) for k in SPANS}
CAPTIONS = [
    ["they don't make games", "like this anymore", "btw i found smth like that"],
    ["does anyone remember", "games like these?", "nothing beats those old", "hidden-object games"],
    ["i wish games still felt", "like they did in 2005", "btw i found smth like that"],
]
MUSIC = [D / "music" / "autumn_leaves_timothy_cole.mp3", D / "music" / "venus_and_flower.mp3"]
TAKEN: list = []
STRIPS = [(540, 1500)]                                # полоса с игрой при любом dy (подпись над ней не сравниваем)


# ---------------- подписи ----------------
def caption_png(k: int, px: int, cy: int) -> Path:
    p = WORK / "text" / f"cap{k}_{px}_{cy}.png"
    if p.exists():
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    from core import renderer as R
    adv = R.line_advance_for(px)
    lines = CAPTIONS[k]
    img = S2.outline_text(lines, px, round(cy - adv * len(lines) / 2))
    if bad := check_box(W, H, img.getbbox()):
        raise SystemExit(f"подпись {k + 1} вне безопасной зоны: {bad}")
    img.save(p)
    return p


def caption_px() -> int:
    """Самый крупный кегль, при котором самая широкая строка всех трёх подписей ≤ 780 px."""
    from core import renderer as R
    import assemble_ugc_reels as A
    for px in range(64, 36, -1):
        font, st = R._load_font(px), max(2, round(px * S2.STROKE))
        widest = max(sum(font.getlength(c) for k, c in A._tokenize_runs(ln) if c) for cap in CAPTIONS for ln in cap)
        if widest + 2 * st <= 780:
            return px
    return 36


# ---------------- план ----------------
# Раскладка (юзер 2026-11-13, вариант 2): полоса 5:4 1080×864 на чёрном; внутри — игра ЦЕЛИКОМ по ширине (кадр 2.17:1,
# ничего не обрезано), сверху/снизу — её размытая затемнённая копия; подпись — на чёрном НАД полосой.
# Уникальность без обрезки игры: у ролика своя высота полосы (dy 0…110), ширина игры в полосе (sw 0.9–1.0, по бокам
# размытая копия), сдвиг игры внутри полосы (gy ±55), участок для размытого фона (bx), цвет, музыка.
def _gy_abs(p: dict) -> float:
    gh = 498 * p["sw"]
    return p["dy"] + (BH - gh) / 2 + p["gy"]


def _ov(x: dict, y: dict) -> float:
    """Сцены поиска предметов почти неподвижны: похожесть кадров решает не секунда, а уровень + размер/место игры."""
    if x["lvl"] != y["lvl"] or abs(x["sw"] - y["sw"]) > 0.025 or abs(_gy_abs(x) - _gy_abs(y)) > 22:
        return 0.0
    return 1.0 + max(0.0, min(x["a"] + x["len"], y["a"] + y["len"]) - max(x["a"], y["a"]))


def make_job(n: int, tag: str, rng: random.Random, px0: int, tries: int = 60) -> dict:
    from core import renderer as R
    cap = n % len(CAPTIONS)
    px = px0 - rng.randint(0, 3)
    adv = R.line_advance_for(px)
    gap = rng.randint(36, 60)
    dy_min = max(0, round(206 + adv * len(CAPTIONS[cap]) + gap - BY))      # подпись над полосой не выше y 206
    best = None
    for _ in range(tries):
        sw, dy, gy = round(rng.uniform(0.9, 1.0), 3), rng.randint(dy_min, 120), rng.randint(-55, 55)
        lv = rng.sample(sorted(SPANS), 3)
        lens = [rng.uniform(2.0, 2.7) for _ in range(3)]
        lens = [x * TOTAL / sum(lens) for x in lens]
        fr = [round(x * FPS) for x in lens]
        fr[-1] = round(TOTAL * FPS) - sum(fr[:-1])
        pieces = []
        for k, L in zip(lv, fr):
            span = rng.choice([sp for sp in SPANS[k] if sp[1] - sp[0] >= L / FPS + 0.2])
            a = round(rng.uniform(span[0], span[1] - L / FPS - 0.1), 3)
            pieces.append(dict(lvl=k, a=a, len=round(L / FPS, 3), frames=L, sw=sw, dy=dy, gy=gy,
                               bx=round(rng.uniform(0.15, 0.85), 3)))
        sc = sum(_ov(x, y) for x in pieces for y in TAKEN)
        if best is None or sc < best[0]:
            best = (sc, pieces, sw, dy, gy)
    _, pieces, sw, dy, gy = best
    TAKEN.extend(pieces)
    m = rng.randrange(len(MUSIC))
    cy = round(BY + dy - gap - adv * len(CAPTIONS[cap]) / 2)               # низ подписи — над полосой
    return dict(n=n, tag=tag, pieces=pieces, sw=sw, dy=dy, gy=gy, caption=cap, px=px, cy=cy,
                music=m, mus_ss=round(rng.uniform(5, 150 if m == 0 else 45), 2),
                game_vol=round(rng.uniform(0.28, 0.4), 3), br=round(rng.uniform(-0.02, 0.03), 3),
                ct=round(rng.uniform(0.97, 1.06), 3), sat=round(rng.uniform(0.98, 1.12), 3),
                warm=round(rng.uniform(-0.04, 0.05), 3))


# ---------------- рендер ----------------
def music_norm(i: int) -> Path:
    p = WORK / f"music{i}_-14lufs.wav"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(MUSIC[i]), "-af", "loudnorm=I=-15:TP=-1.5:LRA=11",
                        "-ar", "48000", "-ac", "2", str(p)], check=True)
    return p


def build(job: dict) -> str:
    from core.gpu_slots import gpu_slot
    out = Path(job["out"])
    dest = out / f"{job['n']:03d}_1.mp4"
    cap = caption_png(job["caption"], job["px"], job["cy"])
    inputs, parts, alab = [], [], []
    for k, p in enumerate(job["pieces"]):
        inputs += ["HW", "-ss", f"{p['a']:.3f}", "-t", f"{p['len'] + 0.2:.3f}", "-i", str(FILES[p["lvl"]])]
        cut = p["lvl"] == "01" and p["a"] >= 90                         # заставка 16:9 с чёрными полями в исходнике
        srcw = 1920 if cut else 2340                                    # поля x 0–210 и 2130–2340 срезаем
        gw = round(BW * p["sw"] / 2) * 2
        gh = round(gw * 1080 / srcw / 2) * 2
        gx, gyy = (BW - gw) // 2, round((BH - gh) / 2 + p["gy"])
        # фон полосы: участок 5:4 той же игры → 96 px → boxblur → обратно (дёшево), затемнён; поверх — игра целиком
        bxo = round((2340 - 1350) * p["bx"] / 2) * 2                    # чётный сдвиг (nv12 с видеокарты: нечётный — зелень)
        parts.append(f"[{k}:v]fps={FPS},format=yuv420p,split[f{k}][b{k}];"
                     f"[b{k}]crop=1350:1080:{bxo}:0,scale=96:76:flags=area,boxblur=3:1,"
                     f"scale={BW}:{BH}:flags=bilinear,eq=brightness=-0.12:saturation=0.9[bb{k}];"
                     f"[f{k}]{'crop=1920:1080:210:0,' if cut else ''}scale={gw}:{gh}:flags=lanczos[gg{k}];"
                     f"[bb{k}][gg{k}]overlay={gx}:{gyy},"
                     f"tpad=stop_mode=clone:stop=3,trim=end_frame={p['frames']},setpts=PTS-STARTPTS,setsar=1[v{k}]")
        parts.append(f"[{k}:a]atrim=0:{p['len']:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
                     f"afade=t=in:d=0.05,afade=t=out:st={p['len'] - 0.06:.3f}:d=0.06[ga{k}]")
        alab.append(f"[ga{k}]")
    n = len(job["pieces"])
    inputs += ["-loop", "1", "-i", str(cap), "-ss", f"{job['mus_ss']:.2f}", "-t", f"{TOTAL + 0.5}", "-i", str(music_norm(job["music"]))]
    ic, im = n, n + 1
    g = 1 + job["warm"]
    parts += [
        "".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0,"
        f"eq=brightness={job['br']}:contrast={job['ct']}:saturation={job['sat']}:gamma_r={g:.3f}:gamma_b={2 - g:.3f}[g]",
        f"color=black:s={W}x{H}:r={FPS}:d={TOTAL}[bg]",
        f"[bg][g]overlay=0:{BY + job['dy']}:shortest=1[s1]",
        f"[s1][{ic}:v]overlay=0:0:shortest=1,tpad=stop_mode=clone:stop=3,format=yuv420p[v]",
        "".join(alab) + f"concat=n={n}:v=0:a=1,volume={job['game_vol']}[game]",
        f"[{im}:a]atrim=0:{TOTAL},asetpts=PTS-STARTPTS,afade=t=in:d=0.3[mus]",
        f"[mus][game]amix=inputs=2:normalize=0:duration=first,atrim=0:{TOTAL},afade=t=out:st={TOTAL - 0.4}:d=0.4[a]",
    ]
    with gpu_slot() as hw:
        args = []
        for x in inputs:
            args += hw if x == "HW" else [x]
        cmd = ["ffmpeg", "-v", "error", "-y", *args, "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
               "-frames:v", str(round(TOTAL * FPS)), "-t", f"{TOTAL}", "-r", str(FPS),
               "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
               "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
               "-c:a", "aac", "-b:a", "192k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
               "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
               "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)]
        for attempt in range(3):
            try:
                subprocess.run(cmd, check=True, timeout=300)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                if attempt == 2:
                    raise
    return f"{job['tag']} {dest.name}: " + " + ".join(f"L{p['lvl']}@{p['a']:.0f}s" for p in job["pieces"])


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
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--seed", type=int, default=6262)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--iters", type=int, default=6)
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    for i in range(len(MUSIC)):
        music_norm(i)
    px = caption_px()
    rng = random.Random(a.seed)
    jobs = [make_job(i, "tt", rng, px) for i in range(1, a.tt + 1)] + [make_job(i, "yt", rng, px) for i in range(1, a.yt + 1)]
    for j in jobs:                                     # подписи готовим заранее (до пула)
        caption_png(j["caption"], j["px"], j["cy"])
    (WORK / "plan.json").write_text(json.dumps(jobs, indent=0), encoding="utf-8")
    if a.test:
        tj = jobs[:2] + [dict(j, n=j["n"] + 100) for j in jobs[a.tt:a.tt + 2]]
        run(tj, WORK / "test", a.jobs)
        return 0
    outs = {"tt": ROOT / "output" / f"junesjourney_TT_{a.tt}", "yt": ROOT / "output" / f"junesjourney_YT_{a.yt}"}
    for tag in ("tt", "yt"):
        run([j for j in jobs if j["tag"] == tag], outs[tag], a.jobs)
    from core.uniq_check import similarity, bad_set
    import numpy as np
    files = lambda: [outs[j["tag"]] / f"{j['n']:03d}_1.mp4" for j in jobs]   # noqa: E731
    for it in range(1, a.iters + 1):
        pair, _vs = similarity(files(), strips=STRIPS, fps=6, thr=40, cache=WORK / "hash_strips6.npz")
        tri = pair[np.triu_indices(len(jobs), 1)]
        bad = bad_set(pair)
        print(f"проверка {it}: худшая пара {tri.max() * 100:.1f} %, среднее {tri.mean() * 100:.3f} %, пар с общими кадрами "
              f"{int((tri > 0).sum())} → пересобираю {len(bad)}", flush=True)
        if not bad:
            break
        rng = random.Random(a.seed + it * 7919)
        for i in bad:
            for pc in jobs[i]["pieces"]:
                if pc in TAKEN:
                    TAKEN.remove(pc)
            old = jobs[i]
            jobs[i] = make_job(old["n"], old["tag"], rng, px)
            caption_png(jobs[i]["caption"], jobs[i]["px"], jobs[i]["cy"])
        (WORK / "plan.json").write_text(json.dumps(jobs, indent=0), encoding="utf-8")
        for tag in ("tt", "yt"):
            js = [jobs[i] for i in bad if jobs[i]["tag"] == tag]
            if js:
                run(js, outs[tag], a.jobs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
