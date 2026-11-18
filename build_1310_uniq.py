#!/usr/bin/env python3
"""
OneState 1310, уникальная версия (юзер 2026-11-13: «видео 1310 заблокированы по неоригинальности — сделай, как на
Skinive, ~1 % схожести между парами»). Формат 1310 тот же (build_1310_reels → build_1309_reels): белый фон, подпись
сверху, геймплей, карточка комментария снизу, логотип, промокод, музыка 1310, 11 с, копы в самом начале.
Почему выданные были похожи (measure_skinive_uniq.py: среднее 15 %, пар > 30 % — 28 %): у всех одно из 3 полицейских
начал по ~4 с (треть ролика) и целые моменты 1309. Теперь у КАЖДОГО ролика своё:
  • начало (3.3–4 с, полиция): участок 1309 (Interaction_01/02/03) или полиция из клипов работ (коп у машины,
    патрульные машины едут) — окно со своим стартом; выбор жадный: наименьшее пересечение с уже взятыми началами;
  • участок (Interaction_01–04) обязательно есть в ролике (если начало — не он, то кусок в середине);
  • середина — случайные отрезки сцен 1309 и клипов работ (не целые моменты), 1.2–2.4 с;
  • у каждого куска свой зум 1.0–1.3 со сдвигом, зеркало 40 %, скорость 0.9–1.15;
  • раскладка: кегль/высота подписи, отступы, низ карточки, оттенок белого фона; тон музыки ±2.5 %.
Тексты, комментаторы, аватары, логотип — как в 1310. NVENC, метаданные удаляются.

  python build_1310_uniq.py --test
  python build_1310_uniq.py --tt 100 --yt 100 --jobs 4   # → output/onestate_1310_TT_100_v2 + onestate_1310_YT_100_v2
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
import build_1310_reels as R  # noqa: E402  (тексты 1310, музыка, перенос по ширине)
from core.ugc_color import SET_SDR  # noqa: E402

B = R.B
ID = "1310"
FPS, TOTAL = B.FPS, 11.0
WORK = ROOT / "output" / "_work" / "onestate_1310_uniq"
OS3 = ROOT / "downloads" / "onestate3" / "proxy"
SCENES = B.SCENES
STATION = ("Interaction_01_", "Interaction_02_", "Interaction_03_", "Interaction_04_")
# начала (полиция), (источник, старт, конец) — внутри одного шота
OPEN = [(SCENES / "Interaction_01_00.52-04.43s.mp4", 0.0, 3.85), (SCENES / "Interaction_03_09.97-13.77s.mp4", 0.0, 3.75),
        (SCENES / "Interaction_02_04.43-09.97s.mp4", 0.0, 5.45),
        (OS3 / "Polic_job.mp4", 7.75, 13.05), (OS3 / "Police_job_1.mp4", 3.45, 8.75), (OS3 / "Police_job_1.mp4", 14.7, 18.7),
        (OS3 / "Polic_job.mp4", 19.0, 23.0)]                    # Polic_job 0–7.6 (машина вдали, копов не видно) — нет
# середина: экшн/город из клипов работ (шоты) + все сцены 1309 (кроме слишком коротких)
OS3_MID = [("Cars", 0.1, 5.1), ("Cars", 8.3, 10.3), ("Cars", 12.4, 25.2), ("Cars", 25.4, 34.2),
           ("Army_Protection_of_the_base", 0.3, 5.4), ("Army_Protection_of_the_base", 5.55, 7.55),
           ("Army_Protection_of_the_base", 7.7, 13.2), ("Drone_drop_1", 0.0, 2.95), ("Drone_drop_1", 6.65, 8.45),
           ("Drone_drop_1", 8.55, 10.75), ("Medics_job_1", 4.75, 9.95), ("Polic_job", 15.0, 16.35),
           ("Police_job_fight_with_Gang", 0.05, 2.45), ("Police_job_fight_with_Gang", 2.5, 4.25),
           ("Taxi_job_1", 5.2, 13.8), ("Taxi_job_1", 17.2, 27.8)]


def sources() -> tuple[list, list, list]:
    mom = json.loads((SCENES / "_index.json").read_text(encoding="utf-8"))
    scen = [(SCENES / m["file"], 0.0, m["dur"] - 0.03) for m in mom if m["dur"] >= 1.0]
    station = [s for s in scen if s[0].name.startswith(STATION)]
    mid = scen + [(OS3 / f"{f}.mp4", a, b) for f, a, b in OS3_MID]
    return station, mid, OPEN


def shot(rng: random.Random, src: tuple, out_len: float, speed: float) -> dict | None:
    p, a, b = src
    need = out_len * speed
    if b - a < need + 0.05:
        return None
    t = round(rng.uniform(a, b - need), 3)
    z = rng.uniform(1.0, 1.3)
    return dict(path=str(p), a=t, speed=round(speed, 3), frames=round(out_len * FPS), z=round(z, 3),
                ox=round(rng.uniform(0.1, 0.9), 2), oy=round(rng.uniform(0.2, 0.8), 2), mirror=rng.random() < 0.4)


def overlap(x: dict, y: dict) -> float:
    """Секунды одного и того же исходника при похожем окне кадра (зум ±0.1) — грубая оценка похожих кадров."""
    if x["path"] != y["path"] or abs(x["z"] - y["z"]) > 0.1:
        return 0.0
    a0, a1 = x["a"], x["a"] + x["frames"] / FPS * x["speed"]
    b0, b1 = y["a"], y["a"] + y["frames"] / FPS * y["speed"]
    return max(0.0, min(a1, b1) - max(a0, b0))


def plan(count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    station, mid, opens = sources()
    avatars = [p for d in B.AVATAR_DIRS if d.is_dir() for p in sorted(d.glob("*.jpg")) if not p.name.startswith("_")]
    rng.shuffle(avatars)
    taken: list[dict] = []                               # все куски всех роликов — для жадного выбора
    jobs = []
    for n in range(count):
        best = None
        for _ in range(25):                              # кандидаты ролика → берём наименее пересекающийся с уже взятыми
            pieces = []
            sp = rng.uniform(0.9, 1.15)
            ol = rng.uniform(3.3, 4.0)
            o = None
            while o is None:
                o = shot(rng, rng.choice(opens), ol, sp)
            pieces.append(o)
            has_station = Path(o["path"]).name.startswith(STATION)
            left = TOTAL - o["frames"] / FPS
            lens = []
            while left > 0.05:
                L = min(left, rng.uniform(1.2, 2.4))
                if left - L < 1.0:
                    L = left
                lens.append(L)
                left -= L
            st_i = None if has_station else rng.randrange(len(lens))
            ok = True
            for i, L in enumerate(lens):
                pool = station if i == st_i else mid
                for _t in range(40):
                    src = rng.choice(pool)
                    s = shot(rng, src, L, rng.uniform(0.9, 1.15))
                    if s and s["path"] != pieces[-1]["path"] and all(s["path"] != q["path"] for q in pieces[-2:]):
                        break
                else:
                    ok = False
                    break
                pieces.append(s)
            if not ok:
                continue
            fr = round(TOTAL * FPS) - sum(p["frames"] for p in pieces[:-1])
            pieces[-1]["frames"] = fr
            score = sum(overlap(a, b) for a in pieces for b in taken)              # одинаковые секунды исходника
            score += 5 * max((overlap(pieces[0], t) for t in taken), default=0.0)  # начало — особенно
            if best is None or score < best[0]:
                best = (score, pieces)
        pieces = best[1]
        taken += pieces
        jobs.append(dict(n=n + 1, caption=n % len(B.CAPTIONS), comment=(n // len(B.CAPTIONS)) % len(B.COMMENTS),
                         person=list(B.PEOPLE[(n * 7 + 3) % len(B.PEOPLE)]), avatar=str(avatars[n % len(avatars)]),
                         seed=rng.randrange(10 ** 9), pieces=pieces,
                         cap_top=rng.randint(206, 262), cap_px=rng.choice((44, 45, 46, 47, 48)), gap=rng.randint(24, 44),
                         card_lift=rng.randint(0, 70), bg=rng.choice((255, 254, 253, 252, 251)),
                         tint=rng.choice((0, 0, 1, -1, 2, -2)), pitch=round(rng.uniform(0.975, 1.025), 4)))
    return jobs


def build(job: dict) -> str:
    work = Path(tempfile.mkdtemp(prefix="r1310u_"))
    rng = random.Random(job["seed"])
    B.CAP_TOP, B.CAP_PX = job["cap_top"], job["cap_px"]
    B.CAPTIONS = [R.wrap_width(t, B.F_CAP, B.CAP_PX, B.X1 - B.X0) for t in R.CAPTIONS_RAW]
    cap_png, card, logo = work / "cap.png", work / "card.png", work / "logo.png"
    cap_bottom = B.caption_png(job["caption"], cap_png)
    card_h = B.card_png(job["comment"], tuple(job["person"]), Path(job["avatar"]), card)
    card_top = B.CARD_BOTTOM - job["card_lift"] - card_h
    band = (cap_bottom + job["gap"], card_top - job["gap"])
    bh = band[1] - band[0]
    bh -= bh % 2
    lx, ly, _lr = B.logo_png(rng, (band[0], band[0] + bh), logo)
    cw, ch = B.banner_anim()
    bx = (B.W - cw) // 2
    by = band[0] + bh - 16 - ch + round(ch * 0.06)
    inputs, parts = [], []
    for k, p in enumerate(job["pieces"]):
        src = p["frames"] / FPS * p["speed"]
        zw, zh = round(B.W * p["z"] / 2) * 2, round(bh * p["z"] / 2) * 2
        inputs += ["-ss", f"{p['a']:.3f}", "-t", f"{src + 0.2:.3f}", "-i", p["path"]]
        parts.append(f"[{k}:v]setpts=(PTS-STARTPTS)/{p['speed']},fps={FPS},"
                     f"scale={zw}:{zh}:flags=lanczos:force_original_aspect_ratio=increase,"
                     f"crop={B.W}:{bh}:(iw-{B.W})*{p['ox']}:(ih-{bh})*{p['oy']}{',hflip' if p['mirror'] else ''},"
                     f"tpad=stop_mode=clone:stop=3,trim=end_frame={p['frames']},setpts=PTS-STARTPTS,setsar=1[v{k}]")
    n = len(job["pieces"])
    inputs += ["-loop", "1", "-i", str(cap_png), "-loop", "1", "-i", str(card), "-loop", "1", "-i", str(logo),
               "-i", str(B.BANNER_ANIM), "-i", str(B.MUSIC)]
    ic, ik, il, ib, ia = n, n + 1, n + 2, n + 3, n + 4
    g = job["bg"]
    bgc = f"0x{g:02x}{min(255, g + job['tint']):02x}{min(255, g - job['tint']):02x}"
    bt = TOTAL / 2 - 4.0
    parts += [
        "".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0[g]",
        f"color={bgc}:s={B.W}x{B.H}:r={FPS}:d={TOTAL}[bg]",
        f"[bg][g]overlay=0:{band[0]}:shortest=1[s1]",
        f"[s1][{il}:v]overlay={lx}:{ly}[s2]",
        f"[s2][{ic}:v]overlay=0:0:shortest=1[s3]",
        f"[s3][{ik}:v]overlay=0:{card_top}:shortest=1[s4]",
        f"[{ib}:v]fps={FPS},format=yuva420p,setpts=PTS-STARTPTS+{bt:.3f}/TB[bn]",
        f"[s4][bn]overlay={bx}:{by}:eof_action=pass,format=yuv420p,{SET_SDR}[v]",
        f"[{ia}:a]asetrate=48000*{job['pitch']},aresample=48000,atrim=0:{TOTAL},afade=t=out:st={TOTAL - 0.3}:d=0.3[a]",
    ]
    dest = Path(job["out"]) / f"{job['n']:03d}_{ID}.mp4"
    cmd = [B.FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
                    "-t", f"{TOTAL}", "-r", str(FPS),
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "192k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)]
    for attempt in range(3):                             # 2026-11-13: ffmpeg однажды упал без сообщения — повторяем
        try:
            subprocess.run(cmd, check=True, timeout=300)
            break
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt == 2:
                raise
    for f in work.iterdir():
        f.unlink()
    work.rmdir()
    return f"{dest.name}: начало {Path(job['pieces'][0]['path']).stem[:16]}, кусков {n}"


def run(jobs: list[dict], out: Path, workers: int, manifest: bool = True) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        j["out"] = str(out)
    WORK.mkdir(parents=True, exist_ok=True)
    if manifest:
        (WORK / f"manifest_{out.name}.json").write_text(json.dumps(jobs, indent=1, ensure_ascii=False), encoding="utf-8")
    with ProcessPoolExecutor(workers) as ex:
        for k, msg in enumerate(ex.map(build, jobs), 1):
            print(f"[{out.name} {k}/{len(jobs)}] {msg}", flush=True)
    print("готово →", out, flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tt", type=int, default=100)
    ap.add_argument("--yt", type=int, default=100)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--seed", type=int, default=131013)
    ap.add_argument("--only-yt", action="store_true")
    ap.add_argument("--redo-tt", default="", help="номера TT через запятую — пересобрать")
    a = ap.parse_args()
    B.banner_anim()
    jobs = plan(a.tt + a.yt, a.seed)
    tt, yt = jobs[:a.tt], jobs[a.tt:]
    for i, j in enumerate(yt, 1):
        j["n"] = i
    if a.test:
        run(tt[:6], WORK / "test", a.jobs)
        return 0
    if a.redo_tt:
        keep = {int(x) for x in a.redo_tt.split(",")}
        run([j for j in tt if j["n"] in keep], ROOT / "output" / f"onestate_{ID}_TT_{a.tt}_v2", a.jobs, manifest=False)
    elif not a.only_yt:
        run(tt, ROOT / "output" / f"onestate_{ID}_TT_{a.tt}_v2", a.jobs)
    if not a.redo_tt:
        run(yt, ROOT / "output" / f"onestate_{ID}_YT_{a.yt}_v2", a.jobs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
