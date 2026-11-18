#!/usr/bin/env python3
"""
OneState 4 (ID 1309, «ванстейт 4», 2026-11-13) — докрутка 1309 (белый фон, подпись сверху / геймплей / карточка
комментария снизу, логотип в левом нижнем углу, промокод STATE9CNL), ТЗ:
  — ролик 7 с;
  — скорость происходящего ×2–3 (каждый кусок ускорен), много экшна: куски вокруг пиков движения (погони, прыжки,
    машины) из геймплея Parkour (downloads/1312/scenes, оценка движения — build_1312_reels.windows);
  — начинаем с самого зрелищного: первый кусок — из верхней трети пиков по движению, пик в первые 0.1–0.35 с;
  — новые подписи (5) и комментарии (4) — дословно (Google Doc «ванстейт 4»), перенос по ширине, как у 1309-ремейка;
  — девушек в кадре нет (правило клиента для 1309): Parkour_10 и Parkour_22 исключены;
  — музыка Safe and Sound с 0:53 (7 с), промокод с 1 с до конца; YouTube — шрифты 1309, TikTok — TikTok Sans.
Каждый ролик — свой набор кусков (окно × скорость), между YT и TT не повторяется. NVENC, метаданные удаляются.

  python build_onestate4.py --test           # 3 YT + 3 TT → output/_work/onestate4_test
  python build_onestate4.py --jobs 4         # → output/onestate_1309_YT_200 + output/onestate_1309_TT_200
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1309_dance_reels as DR  # noqa: E402  (шрифты TikTok по OS1309_FONT, wrap_width)
import build_1312_reels as P  # noqa: E402  (сцены Parkour, оценка движения, места)
from core.ugc_color import SET_SDR  # noqa: E402

B = DR.B
ID = "1309"
B.TOTAL = 7.0
FPS = B.FPS
CAPTIONS_RAW = [
    "WAIT THIS IS ON MOBILE??? 😭",
    "nobody believes me when i say this is a phone game 💀",
    "nah i thought this was real footage 😭",
    "you're telling me this runs on a PHONE?? 😭",
    "bro downloaded real life on his phone 💀",
]
COMMENTS_RAW = [
    "bro said he's going to sleep and then started a whole new life in this game 😭",
    "my bro has a wife, 2 kids and a mortgage in this game but he's single irl 💀",
    "my friend said he's busy with work… BRO IS A TAXI DRIVER IN THIS GAME 💀🚕",
    "bro missed his actual job interview because he was late for his shift in this game 😭",
]
B.CAPTIONS = [DR.wrap_width(t, B.F_CAP, B.CAP_PX, B.X1 - B.X0) for t in CAPTIONS_RAW]
B.COMMENTS = [DR.wrap_width(t, B.F_REG, B.CMT_PX, B.X1 - B.X0) for t in COMMENTS_RAW]
NO_GIRL = (10, 22)                                    # Parkour_10 (девушка в розовом), Parkour_22 (у края)
# где в Parkour.mp4 видна девушка (абсолютное время, с запасом): начало (Kristen), площадь ×2, 10 и 22 сцены
GIRL = [(0.0, 3.6), (38.0, 41.6), (63.5, 66.7), (83.8, 86.3), (135.4, 138.6)]


FOOTAGE = os.environ.get("OS4_FOOTAGE", "mix")          # mix — 1309 + экшн-вставки; 1309 — только сцены 1309; parkour — 1312
if FOOTAGE in ("1309", "mix"):
    P.SCENES = B.SCENES                                   # downloads/1309/scenes (26 моментов), девушки разрешены
    P.CACHE = ROOT / "output" / "_work" / "onestate4" / "cache1309"
# первый кадр: танцы у граффити (03/10), сцена с танцовщицами (04), танцпол (05)
OPENERS_1309 = ("Paired_03_", "Paired_04_", "Paired_05_", "Paired_10_")
# экшн-вставки (юзер 2026-11-13: «поищи другие уан стейт видео, чтобы зрелищные кадры вставлять»): клипы работ с Drive
# клиента → 1080p-прокси; отрезки внутри одного шота (склейки — output/_work/onestate4/os3_cuts.json), o = годится в начало
OS3 = ROOT / "downloads" / "onestate3" / "proxy"
ACTION = [  # (файл, старт, конец, opener)
    ("Cars", 0.1, 5.1, True), ("Cars", 8.3, 10.3, True), ("Cars", 12.4, 25.2, True), ("Cars", 25.4, 34.2, True),
    ("Army_Protection_of_the_base", 0.3, 5.4, True), ("Army_Protection_of_the_base", 5.55, 7.55, True),
    ("Army_Protection_of_the_base", 7.7, 13.2, False), ("Army_Protection_of_the_base", 16.8, 19.25, True),
    ("Drone_drop_1", 0.0, 2.95, True), ("Drone_drop_1", 6.65, 8.45, True), ("Drone_drop_1", 8.55, 10.75, True),
    ("Medics_job_1", 4.75, 9.95, False), ("Polic_job", 15.0, 16.35, True), ("Polic_job", 19.0, 23.0, False),
    ("Police_job_1", 14.7, 18.7, False), ("Police_job_fight_with_Gang", 2.5, 4.25, True),
    ("Police_job_fight_with_Gang", 4.35, 7.8, False), ("Taxi_job_1", 5.2, 13.8, False), ("Taxi_job_1", 17.2, 27.8, False),
]


# ПЕРВЫЙ КАДР (юзер: «первые кадры должны быть прям реально захватывающими») — отобрано покадрово: событие в первые
# 0.1–0.3 с; (файл, старт, конец) в исходнике; ускорение мягче (×1.3–1.8), чтобы прыжок успели увидеть
PK1080 = ROOT / "downloads" / "1312" / "bg" / "Parkour_1080.mp4"
HOOKS = [
    (PK1080, 51.0, 52.4, "нырок через капот на камеру"), (PK1080, 59.9, 61.2, "прыжок через машину на камеру"),
    (PK1080, 98.9, 100.0, "прыжок через машину"), (PK1080, 16.8, 18.2, "прыжок со стены в камеру"),
    (PK1080, 3.9, 5.0, "прыжок через перила"), (PK1080, 119.8, 120.9, "запрыгивает на машину"),
    (OS3 / "Polic_job.mp4", 15.0, 16.3, "погоня: машина проносится мимо камеры"),
    (OS3 / "Drone_drop_1.mp4", 6.65, 8.0, "стрельба со вспышками"), (OS3 / "Drone_drop_1.mp4", 0.0, 1.4, "дрон сбрасывает ящик"),
]


def action_windows() -> list[dict]:
    return [{"m": 100 + i, "id": 1000 + i, "file": f"{f}.mp4", "path": str(OS3 / f"{f}.mp4"), "base": a, "dur": round(b - a, 3),
             "peak": 0.0, "score": 0.0, "action": True, "opener": o} for i, (f, a, b, o) in enumerate(ACTION)]


_GROUPS = [("Paired_02_", "Paired_07_"), ("Paired_03_", "Paired_10_"), ("Paired_04_", "Paired_09_")]


def place(w: dict) -> str:
    """Одно место в разных моментах — подряд не ставим."""
    if w.get("action"):
        return w["file"]
    if FOOTAGE == "parkour":
        return str(P.place(w["m"]))
    for k, g in enumerate(_GROUPS):
        if w["file"].startswith(g):
            return f"g{k}"
    return w["file"]


def girl_free(p: dict) -> bool:
    if FOOTAGE in ("1309", "mix"):
        return True
    s0 = float(p["file"].split("_")[2].split("-")[0])          # Parkour_NN_<start>-<end>s.mp4
    a, b = s0 + p["a"], s0 + p["a"] + p["frames"] / FPS * p["speed"] + 0.15
    return all(b <= g0 or a >= g1 for g0, g1 in GIRL)
MUSIC = B.D / "music" / "music_53-60s_-14lufs.wav"
BANNER_T = 1.0
WORK = ROOT / "output" / "_work" / "onestate4"


def music() -> None:
    if MUSIC.exists():
        return
    B.MUSIC = MUSIC
    DR.B.MUSIC = MUSIC
    DR.music()


def pool() -> tuple[list[dict], list[dict]]:
    """Окна вокруг пиков движения (кэш), без моментов с девушками; opener — верхняя треть по силе движения."""
    f = WORK / f"windows_{'1309' if FOOTAGE == 'mix' else FOOTAGE}.json"
    if f.exists():
        win = json.loads(f.read_text(encoding="utf-8"))
    else:
        _mom, win = P.windows()
        if FOOTAGE == "parkour":
            win = [w for w in win if w["m"] not in NO_GIRL]
        WORK.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(win), encoding="utf-8")
    if FOOTAGE == "mix":                                  # 1309 — середина; начало и вставки — экшн
        act = action_windows()
        return win + act, [w for w in act if w["opener"]]
    if FOOTAGE == "1309":                                 # самое зрелищное в футаже 1309 — массовые танцы (движение камеры
        return win, [w for w in win if w["file"].startswith(OPENERS_1309)]   # детектор путает с экшном)
    sc = sorted(w["score"] for w in win)
    th = sc[int(len(sc) * 0.66)]
    return win, [w for w in win if w["score"] >= th]


def piece(rng: random.Random, w: dict, out_len: float, first: bool) -> dict:
    sp = round(min(rng.uniform(2.0, 3.0), (w["dur"] - 0.05) / out_len), 2)   # короткая сцена — ускорение под её длину
    src = out_len * sp
    if w.get("action"):                                   # экшн-шот: движение весь шот — старт в любом месте
        a = w["base"] + rng.uniform(0.0, max(0.0, w["dur"] - src - 0.05))
    else:
        lead = rng.uniform(0.02, 0.1) * sp if first else src * rng.uniform(0.25, 0.5)   # пик — сразу в начале opener'а
        a = min(max(0.0, w["peak"] - lead), max(0.0, w["dur"] - src - 0.05))
    return {"m": w["m"], "id": w["id"], "file": w["file"], "path": w.get("path", str(P.SCENES / w["file"])),
            "a": round(a, 3), "speed": sp, "frames": round(out_len * FPS), "action": bool(w.get("action"))}


def plan(count: int, seed: int = 13094) -> list[dict]:
    rng = random.Random(seed)
    win, top = pool()
    avatars = [p for d in B.AVATAR_DIRS if d.is_dir() for p in sorted(d.glob("*.jpg")) if not p.name.startswith("_")]
    rng.shuffle(avatars)
    use: dict = {}
    seen: set = set()
    jobs = []
    hook_use: dict = {}
    for n in range(count):
        for _ in range(500):
            k = rng.choice((5, 5, 6))
            hook = None
            if FOOTAGE == "mix":                           # первый кусок — один из HOOKS, по очереди (наименее использованный)
                lo = min(hook_use.get(h, 0) for h in range(len(HOOKS)))
                hi = rng.choice([h for h in range(len(HOOKS)) if hook_use.get(h, 0) == lo])
                hp, hs, he, _ = HOOKS[hi]
                hsp = round(rng.uniform(1.3, 1.8), 2)
                hf = round((he - hs) / hsp * FPS)
                hs = max(0.0, hs + rng.uniform(-0.08, 0.12))          # свой старт у каждого ролика, событие всё равно в начале
                hook = {"m": 200 + hi, "id": 2000 + hi, "file": Path(hp).name, "path": str(hp), "a": round(hs, 3), "speed": hsp,
                        "frames": hf, "action": True, "hook": hi}
            lens = [rng.uniform(0.9, 1.6) for _ in range(k - (1 if hook else 0))]
            rest_total = B.TOTAL - (hook["frames"] / FPS if hook else 0.0)
            lens = [x * rest_total / sum(lens) for x in lens]
            fr = [round(x * FPS) for x in lens]
            fr[-1] = round(rest_total * FPS) - sum(fr[:-1])
            if hook:
                fr = [hook["frames"]] + fr
            if min(fr[1:] if hook else fr) < 0.7 * FPS or (hook and fr[0] < 0.55 * FPS):
                continue
            pieces = []
            types = None
            if FOOTAGE == "mix":                          # A = экшн, S = сцена 1309; начало — всегда A, две A подряд нельзя
                for _ in range(50):
                    na = rng.choice((2, 3)) if k == 5 else 3
                    rest = ["A"] * (na - 1) + ["S"] * (k - na)
                    rng.shuffle(rest)
                    types = ["A"] + rest
                    if all(not (x == y == "A") for x, y in zip(types, types[1:])):
                        break
            for i, L in enumerate(fr):
                if hook and i == 0:
                    pieces.append(hook)
                    continue
                pool_i = top if i == 0 else win
                if types and i:
                    pool_i = [w for w in win if bool(w.get("action")) == (types[i] == "A")]
                cand = [w for w in pool_i if w["m"] not in {p["m"] for p in pieces}
                        and w["dur"] >= L / FPS * 2.0 + 0.05
                        and (not pieces or place(w) != place(pieces[-1]))]
                if not cand:
                    break
                rng.shuffle(cand)
                cand.sort(key=lambda w: use.get(w["id"], 0))
                for w in cand:
                    pc = piece(rng, w, L / FPS, i == 0)
                    if girl_free(pc):
                        break
                else:
                    raise SystemExit("нет окна без девушки")
                pieces.append(pc)
            for pc in pieces:
                pc.update(z=round(rng.uniform(1.0, 1.15), 3), ox=round(rng.uniform(0.2, 0.8), 2), oy=round(rng.uniform(0.3, 0.7), 2),
                          mirror=rng.random() < 0.4)
            if len(pieces) < len(fr):
                continue
            key = tuple(p["id"] for p in pieces)
            if key not in seen:
                break
        seen.add(key)
        if pieces[0].get("hook") is not None:
            hook_use[pieces[0]["hook"]] = hook_use.get(pieces[0]["hook"], 0) + 1
        for p in pieces:
            use[p["id"]] = use.get(p["id"], 0) + 1
        jobs.append({"n": n + 1, "caption": n % len(B.CAPTIONS), "comment": (n // len(B.CAPTIONS)) % len(B.COMMENTS),
                     "pieces": pieces, "person": list(B.PEOPLE[(n + 41) % len(B.PEOPLE)]),
                     "avatar": str(avatars[n % len(avatars)]), "seed": rng.randint(0, 10 ** 6)})
    return jobs


def build(job: dict) -> str:
    work = Path(tempfile.mkdtemp(prefix="os4_"))
    rng = random.Random(job["seed"])
    cap_png, card, logo = work / "cap.png", work / "card.png", work / "logo.png"
    cap_bottom = B.caption_png(job["caption"], cap_png)
    card_h = B.card_png(job["comment"], tuple(job["person"]), Path(job["avatar"]), card)
    card_top = B.CARD_BOTTOM - card_h
    band = (cap_bottom + B.GAP, card_top - B.GAP)
    bh = band[1] - band[0]
    bh -= bh % 2
    lx, ly, _lr = B.logo_png(rng, (band[0], band[0] + bh), logo)
    cw, ch = B.banner_anim()
    bx = (B.W - cw) // 2
    by = band[0] + bh - 16 - ch + round(ch * 0.06)
    inputs, parts = [], []
    for k, p in enumerate(job["pieces"]):
        src = p["frames"] / FPS * p["speed"]
        inputs += ["-ss", f"{p['a']:.3f}", "-t", f"{src + 0.15:.3f}", "-i", p.get("path") or str(P.SCENES / p["file"])]
        parts.append(f"[{k}:v]setpts=(PTS-STARTPTS)/{p['speed']},fps={FPS},"
                     f"scale={round(B.W * p.get('z', 1) / 2) * 2}:{round(bh * p.get('z', 1) / 2) * 2}:flags=lanczos:force_original_aspect_ratio=increase,"
                     f"crop={B.W}:{bh}:(iw-{B.W})*{p.get('ox', 0.5)}:(ih-{bh})*{p.get('oy', 0.5)}{',hflip' if p.get('mirror') else ''},"
                     f"tpad=stop_mode=clone:stop=3,trim=end_frame={p['frames']},setpts=PTS-STARTPTS,setsar=1[v{k}]")
    n = len(job["pieces"])
    inputs += ["-loop", "1", "-i", str(cap_png), "-loop", "1", "-i", str(card), "-loop", "1", "-i", str(logo),
               "-i", str(B.BANNER_ANIM), "-i", str(MUSIC)]
    ic, ik, il, ib = n, n + 1, n + 2, n + 3
    parts += [
        "".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0[g]",
        f"color=white:s={B.W}x{B.H}:r={FPS}:d={B.TOTAL}[bg]",
        f"[bg][g]overlay=0:{band[0]}:shortest=1[s1]",
        f"[s1][{il}:v]overlay={lx}:{ly}[s2]",
        f"[s2][{ic}:v]overlay=0:0:shortest=1[s3]",
        f"[s3][{ik}:v]overlay=0:{card_top}:shortest=1[s4]",
        f"[{ib}:v]fps={FPS},format=yuva420p,setpts=PTS-STARTPTS+{BANNER_T:.3f}/TB[bn]",
        f"[s4][bn]overlay={bx}:{by}:eof_action=pass,format=yuv420p,{SET_SDR}[v]",
    ]
    dest = Path(job["out"]) / f"{job['n']:03d}_{ID}.mp4"
    subprocess.run([B.FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[v]", "-map",
                    f"{ib + 1}:a", "-t", f"{B.TOTAL}", "-r", str(FPS),
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "192k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True, timeout=300)
    for f in work.iterdir():
        f.unlink()
    work.rmdir()
    return f"{dest.name}: " + " + ".join(f"{p['m']:02d}×{p['speed']}" for p in job["pieces"])


def run(jobs: list[dict], out: Path, font: str, workers: int) -> None:
    os.environ["OS1309_FONT"] = font                    # дочерние процессы заново импортируют модули с этим шрифтом
    out.mkdir(parents=True, exist_ok=True)
    assert all(girl_free(p) for j in jobs for p in j["pieces"])
    for j in jobs:
        j["out"] = str(out)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / f"manifest_{out.name}.json").write_text(json.dumps(jobs, indent=1, ensure_ascii=False), encoding="utf-8")
    with ProcessPoolExecutor(workers) as ex:
        for k, msg in enumerate(ex.map(build, jobs), 1):
            print(f"[{font} {k}/{len(jobs)}] {msg}", flush=True)
    print("готово →", out, flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--yt", type=int, default=200)
    ap.add_argument("--tt", type=int, default=200)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--footage", choices=("mix", "1309", "parkour"), default="mix")
    a = ap.parse_args()
    if a.footage != FOOTAGE:                              # футаж выбирается при импорте (воркеры) — по переменной окружения
        os.environ["OS4_FOOTAGE"] = a.footage
        return os.spawnv(os.P_WAIT, sys.executable, [sys.executable, *sys.argv])
    B.banner_anim()
    music()
    jobs = plan(a.yt + a.tt)
    yt, tt = jobs[:a.yt], jobs[a.yt:]
    for i, j in enumerate(tt, 1):
        j["n"] = i
    if a.test:
        run(yt[:4], ROOT / "output" / "_work" / f"onestate4_test_{FOOTAGE}", "default", a.jobs)
        for j in tt[:4]:
            j["n"] += 100
        run(tt[:4], ROOT / "output" / "_work" / f"onestate4_test_{FOOTAGE}", "tiktok", a.jobs)
        return 0
    run(yt, ROOT / "output" / f"onestate_{ID}_YT_{a.yt}", "default", a.jobs)
    run(tt, ROOT / "output" / f"onestate_{ID}_TT_{a.tt}", "tiktok", a.jobs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
