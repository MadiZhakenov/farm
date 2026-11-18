#!/usr/bin/env python3
"""
OneState 3 (ID 1) — «CEO в жизни → таксист / коп в игре»: 9:16, до 7 с, мемный звук, промокод STATE9CNL + логотип OneState.
Исходники — Drive 13aWhXBG… → downloads/onestate3/src (2560×1440 30 fps): Taxi_job_1 (такси), Polic_job (коп + автобус в
конце — не берём), Police_job_fight_with_Gang (коп против банды). Кадр 9:16 = вырез 810×1440 из 16:9 по центру (машина/коп
в центре; интерфейс игры по бокам уходит) → 1080×1920.
Тексты ТЗ дословно (только строки POV; «🚕 CEO → Taxi Driver» и т. п. — пометки ТЗ), переносы по смыслу, белый TikTok-шрифт
с обводкой сверху. Профессия ролика = профессия текста: 1, 3, 4 — такси, 2 — коп.
Звуки (ТЗ): «Drive» (Ryan Gosling, snap! — rhythm is a dancer) с дропа / с начала; кошачий мем (фото-пост jojx_o).
Склейки — на доли звука; до дропа «кино»-кадр (машина / подъезд копа), на дропе — геймплей. Вариант «ускоренный» — геймплей ×1.5.

  python build_onestate3_reels.py --test          # тесты → output/_work/onestate3_test
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1309_reels as B  # noqa: E402  (logo_png — логотип с тенью, banner_anim — промокод STATE9CNL с анимацией)
import build_gw_wall_reels as WL  # noqa: E402  (render_wall — белый TikTok-шрифт с обводкой)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
SRC = ROOT / "downloads" / "onestate3" / "src"
MUS = ROOT / "downloads" / "onestate3" / "music"
TEXTS = [
    ("taxi", "POV: You're a CEO\nin real life, but in this game\nyou finally get to live your dream\nof being a taxi driver 🚕😭"),
    ("cop", "POV: You're a CEO\nin real life, but in this game\nyou finally get to live your dream\nof being a cop 🚔💀"),
    ("taxi", "POV: You make six figures\nas a CEO, but your only\nsource of happiness\nis driving strangers around\nin this game 🚕😭"),
    ("taxi", "POV: Your employees think\nyou're in an important meeting,\nbut you're actually working\nyour dream job as a taxi driver\nin this game 🚕💀"),
]
# куски: (файл, от, до, центр выреза по x в исходнике 2560)
# первый кадр ролика — «кто ты»: такси крупно / подъезд полицейской машины, коп у машины
FIRST = {
    "taxi": [("Taxi_job_1", 0.15, 2.35, 1280), ("Taxi_job_1", 13.9, 15.35, 1280)],
    "cop": [("Polic_job", 0.2, 7.6, 1180), ("Polic_job", 7.7, 13.0, 1280)],
}
SECOND = {                                               # второй «кино»-кадр до дропа (drive_drop)
    "taxi": FIRST["taxi"] + [("Taxi_job_1", 15.45, 17.1, 1280)],                 # + номер ONE STATE крупно
    "cop": FIRST["cop"] + [("Police_job_fight_with_Gang", 0.05, 2.45, 980)],
}
GAME = {
    "taxi": [("Taxi_job_1", 2.5, 13.75, 1280), ("Taxi_job_1", 17.2, 27.75, 1280)],
    "cop": [("Polic_job", 13.0, 16.35, 1280), ("Polic_job", 16.45, 17.33, 1150), ("Polic_job", 17.4, 18.95, 1280),
            ("Polic_job", 19.0, 23.0, 1280), ("Police_job_fight_with_Gang", 4.35, 7.8, 1280),
            ("Police_job_fight_with_Gang", 2.5, 4.28, 1280)],
}
# звуки: файл, старт в треке, длина ролика, склейки (с от начала ролика), сколько первых кусков — «кино»
RHYTHM = MUS / "rhythm_slowed_yt_z6_ZshbfDdM.mp3"                 # вместо мема Drive (юзер 13.11, YouTube z6_ZshbfDdM)
CAT = MUS / "jojx_photo_7475022940808006934.mp3"


def variants() -> list[dict]:
    """Варианты звука из тюнера (tuner_onestate3.py → music/_cuts_manual.json; без файла — как в тестах): старт звука,
    длина ролика, склейки (с от начала ролика) и сколько первых кусков — «кино». Та же логика отрезков, что в тюнере."""
    import tuner_onestate3 as TO
    out = []
    for key, pts in TO.points().items():
        for k, pt in enumerate(sorted(pts, key=lambda q: q["t"]), 1):
            if not pt.get("on", True):
                continue
            seg = TO.segments(key, pt)
            st = seg[0][1]
            out.append(dict(name=f"{key}{k}", f=str(TO.MUS / TO.SONGS[key][1]), ss=round(st, 3),
                            total=round(round((seg[-1][2] - st) * FPS) / FPS, 3),
                            cuts=[round(a - st, 3) for _n, a, _b in seg[1:]],
                            hook=sum(1 for n, _a, _b in seg if n.startswith("кино"))))
    return out
TEXT_TOP = 230


def wall(text: str, dest: Path) -> tuple:
    n = len([ln for ln in text.split("\n") if ln.strip()])
    px = 60
    while px > 34 and (WL.wall_height(text, px) > 560 or len([x for x in WL.wall_lines(text, px) if x]) > n):
        px -= 1
    WL.render_wall(text, px, TEXT_TOP, dest)
    return Image.open(dest).getbbox()


def plan_pieces(prof: str, s: dict, speed: float, rng: random.Random) -> list[dict]:
    sound = s["name"]
    bounds = [0.0] + s["cuts"] + [s["total"]]
    pieces, used = [], set()
    for k in range(len(bounds) - 1):
        ln = round((bounds[k + 1] - bounds[k]) * FPS) / FPS
        hook = k < s["hook"]
        pool = FIRST[prof] if k == 0 else SECOND[prof] if hook else GAME[prof]
        sp = 1.0 if hook else speed
        need = ln * sp
        fits = [x for x in pool if x[2] - x[1] >= need + 0.05]
        if not fits:
            raise SystemExit(f"{prof}/{sound}: нет куска длиной {need:.2f} с")
        best = None
        for _ in range(3000):
            f, a, b, cx = rng.choice(fits)
            st = round(rng.uniform(a, b - need), 2)
            over = sum(max(0.0, min(st + need, ue) - max(st, us)) for uf, us, ue in used if uf == f)
            if best is None or over < best[0]:
                best = (over, f, st, cx)
            if over == 0:                                   # куски одного файла не пересекаются (если хватает записи)
                break
        _o, f, st, cx = best
        used.add((f, st, st + need))
        pieces.append(dict(f=f, st=st, n=round(bounds[k + 1] * FPS) - round(bounds[k] * FPS), speed=sp,
                           cx=cx + rng.randint(-50, 50)))
    return pieces


def render(job: dict) -> str:
    rng = random.Random(job["seed"])
    s = job["snd"]
    out = Path(job["out"])
    fr = ROOT / "output" / "_work" / "onestate3" / f"{out.parent.name}_{out.stem}"    # рабочие файлы — не в папке выдачи
    fr.mkdir(parents=True, exist_ok=True)
    txt, logo = fr / "text.png", fr / "logo.png"
    box = wall(TEXTS[job["text"]][1], txt)
    if bad := check_box(W, H, box):
        raise SystemExit(f"текст вне безопасной зоны {box}: {bad}")
    lx, ly, _ = B.logo_png(rng, (0, 1520), logo)
    cw, ch = B.banner_anim()
    bx, by = (W - cw) // 2, box[3] + 10                  # промокод — сразу под текстом (внизу он закрывал машину)
    inputs, fc, labels = [], [], []
    for k, p in enumerate(job["pieces"]):
        span = p["n"] / FPS * p["speed"] + 0.2
        inputs += ["-ss", f"{p['st']:.3f}", "-t", f"{span:.3f}", "-i", str(SRC / f"{p['f']}.mp4")]
        x0 = max(0, min(2560 - 810, p["cx"] - 405))
        fc.append(f"[{k}:v]setpts=(PTS-STARTPTS)/{p['speed']},fps={FPS},crop=810:1440:{x0}:0,scale={W}:{H}:flags=lanczos,"
                  f"setsar=1,tpad=stop_mode=clone:stop=4,trim=end_frame={p['n']},setpts=PTS-STARTPTS[p{k}]")
        labels.append(f"[p{k}]")
    n = len(labels)
    inputs += ["-loop", "1", "-i", str(txt), "-loop", "1", "-i", str(logo), "-i", str(B.BANNER_ANIM),
               "-ss", f"{s['ss']:.3f}", "-t", f"{s['total'] + 0.3:.2f}", "-i", s["f"]]
    it, il, ib, ia = n, n + 1, n + 2, n + 3
    fc += ["".join(labels) + f"concat=n={n}:v=1:a=0,format=yuv420p[g]",
           f"[g][{il}:v]overlay={lx}:{ly}:shortest=1[a1]",
           f"[{ib}:v]fps={FPS},format=yuva420p,setpts=PTS-STARTPTS+0.5/TB[bn]",
           f"[a1][bn]overlay={bx}:{by}:eof_action=pass[a2]",
           f"[a2][{it}:v]overlay=0:0:shortest=1,format=yuv420p[v]",
           f"[{ia}:a]atrim=0:{s['total']:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
           f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={s['total'] - 0.3:.3f}:d=0.3[aud]"]
    (fr / "graph.txt").write_text(";\n".join(fc), encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex_script", str(fr / "graph.txt"),
                    "-map", "[v]", "-map", "[aud]", "-t", f"{s['total']:.3f}", "-r", str(FPS),
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(out)], check=True)
    shutil.rmtree(fr)
    return f"{out.name}: {s['name']} x{job['speed']} " + " + ".join(f"{p['f'][:6]}@{p['st']}" for p in job["pieces"])


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--tt", type=int, default=0)
    ap.add_argument("--yt", type=int, default=0)
    ap.add_argument("--fast", type=float, default=0.0, help="доля роликов с ускоренным ×1.5 геймплеем (0 — нет)")
    a = ap.parse_args()
    B.banner_anim()
    if a.tt or a.yt:
        return batch(a)
    out = ROOT / "output" / "_work" / "onestate3_test"
    out.mkdir(parents=True, exist_ok=True)
    vs = variants()
    # по каждому варианту звука из тюнера: обычный ролик (тексты по кругу, коп — каждый второй вариант) + ускоренный
    tests = []
    for k, v in enumerate(vs):
        tests.append((k % 4, v, 1.0))
        tests.append(((k + 1) % 4, v, 1.5))
    jobs = []
    for k, (ti, v, sp) in enumerate(tests, 1):
        rng = random.Random(3000 + k)
        prof = TEXTS[ti][0]
        jobs.append(dict(text=ti, snd=v, speed=sp, seed=rng.randrange(1 << 30), pieces=plan_pieces(prof, v, sp, rng),
                         out=str(out / f"{k:02d}_{v['name']}_{prof}_t{ti + 1}{'_fast' if sp > 1 else ''}_1.mp4")))
    (out / "_plan.json").write_text(json.dumps(jobs, indent=1, ensure_ascii=False), encoding="utf-8")
    with ProcessPoolExecutor(a.jobs) as ex:
        for msg in ex.map(render, jobs):
            print(" ", msg, flush=True)
    return 0


def batch(a) -> int:
    """Партия: варианты звука из тюнера (только включённые) и 4 текста по кругу; у каждого ролика свой набор кусков
    (все наборы разные между TT и YT), своя подрезка и место логотипа. TT и YT — одним списком, по очереди."""
    vs = variants()
    n = a.tt + a.yt
    rng0 = random.Random(31313)
    seen, rows = set(), []
    for i in range(n):
        v = vs[i % len(vs)]
        ti = (i // len(vs)) % len(TEXTS)
        sp = 1.5 if a.fast and rng0.random() < a.fast else 1.0
        for _ in range(200):
            rng = random.Random(rng0.randrange(1 << 30))
            pieces = plan_pieces(TEXTS[ti][0], v, sp, rng)
            key = (v["name"], tuple((q["f"], round(q["st"], 1)) for q in pieces))
            if key not in seen:
                break
        else:
            raise SystemExit(f"ролик {i + 1}: нет нового набора кусков")
        seen.add(key)
        rows.append(dict(text=ti, snd=v, speed=sp, seed=rng.randrange(1 << 30), pieces=pieces))
    tt, yt = ROOT / "output" / f"onestate_3_TT_{a.tt}", ROOT / "output" / f"onestate_3_YT_{a.yt}"
    jobs, nt, ny = [], 0, 0
    for i, r in enumerate(rows):
        if (i % 3 == 0 and nt < a.tt) or ny >= a.yt:        # 100 TT + 200 YT вперемешку
            nt += 1
            r["out"] = str(tt / f"{nt:03d}_1.mp4")
        else:
            ny += 1
            r["out"] = str(yt / f"{ny:03d}_1.mp4")
        jobs.append(r)
    work = ROOT / "output" / "_work" / "onestate3"
    work.mkdir(parents=True, exist_ok=True)
    for d in (tt, yt):
        d.mkdir(parents=True, exist_ok=True)
        man = {Path(j["out"]).name: j for j in jobs if Path(j["out"]).parent == d}
        (work / f"manifest_{d.name}.json").write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    todo = [j for j in jobs if not Path(j["out"]).exists()]
    bad = []
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(render, j) for j in todo]
        for j, f in zip(todo, futs):
            try:
                print(" ", Path(j["out"]).parent.name, f.result(), flush=True)
            except Exception as e:                       # noqa: BLE001
                Path(j["out"]).unlink(missing_ok=True)
                bad.append(j["out"])
                print("  ОШИБКА", j["out"], e, flush=True)
    if bad:
        print("не собрались (перезапусти — доделает только их):", len(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
