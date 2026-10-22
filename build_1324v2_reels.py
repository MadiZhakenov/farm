#!/usr/bin/env python3
"""
1324 v2 — OneState, 300 роликов 9:16 (1080×1920, 8 с): геймплей горизонтальных исходников (Drive
13o1u8TcAs5ri5KC62Ac-mrUlZ4XpYN4J = downloads/1309/footage, уже нарезанные моменты downloads/1309/scenes) —
квадратом 1080×1080 посередине кадра на чёрном, как 1312; логотип в левом нижнем углу геймплея и промокод
STATE9CNL внизу геймплея по центру — как в 1309/1312. Только моменты с людьми в кадре, первым — момент с двумя
парнями. Текст ТЗ дословно, TikTok-шрифт белый с обводкой, посередине, переносы по смыслу, три текста поровну.
Сверху котята из мема 1324 v1 ходят над текстом; длина и звук — мема (8 с).

  python build_1324v2_reels.py --test
  python build_1324v2_reels.py --count 300 --jobs 3
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

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1303_reels as T  # noqa: E402  (text_png — белый TikTok-текст с обводкой в полосе BAND)
import build_1309_reels as B  # noqa: E402  (logo_png, banner_anim)
import build_os_meme_reels as M  # noqa: E402  (котята: вырезанный мем, звук мема, путь по экрану)
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = B.FF
ID = "1324"
W, H, FPS, TOTAL = 1080, 1920, 60, 8.0              # клиент: длина = мем с котятами (8 с)
BAND_Y, BAND = 420, 1080                              # квадрат геймплея y 420–1500, как 1312
SCENES = ROOT / "downloads" / "1309" / "scenes"
MUSIC = ROOT / "downloads" / "1309" / "music" / "music_53-64s_-14lufs.wav"
D = ROOT / "downloads" / "1324v2"
MIN_LAST = 1.5
# моменты (индексы _index.json), проверено глазами по листу кадров
TWO_GUYS = [0, 1, 5, 6]                               # двое парней крупно: разговор, рукопожатие, с маскотом
PEOPLE = TWO_GUYS + [2, 4, 7, 9, 10, 11, 15, 16, 17, 23]   # люди в кадре: танцы, вечеринка, пары, клиника
NL = chr(10)
TEXTS = [
    NL.join(["boss: “where are you?”", "me and my bro cruising in top cars", "on our phones", "and running our business 😭"]),
    NL.join(["POV: it’s 2am,", "you and your bro are in the city", "doing absolutely nothing",
             "and it’s the best part of your day 😭"]),
    NL.join(["POV: me and my bro logging in", "“for a minute” and ending up", "chilling till sunrise 😭"]),
]
T.BAND = (720, 1300)                                  # посередине, над промокодом
T.PX_MAX, T.PX_MIN = 54, 34


def moments() -> list[dict]:
    return json.loads((SCENES / "_index.json").read_text(encoding="utf-8"))


def vkey(moments_: list) -> tuple:
    """Ключ видеоряда: моменты, длительности и сдвиг начала (если есть)."""
    return tuple((m[0], round(float(m[1]), 3), round(float(m[2]), 2) if len(m) > 2 else 0.0) for m in moments_)


def plan(count: int, seed: int = 1324, avoid: set | None = None) -> list[dict]:
    """Первый — момент с двумя парнями, дальше целые моменты с людьми до конца ролика (последний обрезан ≥ 1.5 с);
    моменты используются равномерно, видеоряд не повторяется. avoid — видеоряды уже сданных партий: их не берём,
    а когда новые наборы моментов кончаются, обрезанный последний момент берём с другого места (сдвиг)."""
    rng = random.Random(seed)
    mom = moments()
    use: dict = {}
    seen: set = set(avoid or ())
    base_seen = {tuple(x[:2] for x in k) for k in seen}
    jobs = []
    for n in range(count):
        key = None
        for attempt in range(1500):
            first = min(TWO_GUYS, key=lambda i: use.get(i, 0) + rng.random() * 2)
            seq, total = [[first, mom[first]["dur"]]], mom[first]["dur"]
            for i in sorted((i for i in PEOPLE if i != first), key=lambda i: use.get(i, 0) + rng.random() * 3):
                rem = TOTAL - total
                d = mom[i]["dur"]
                if d < rem - 1e-6:
                    if rem - d < MIN_LAST:
                        continue
                    seq.append([i, d])
                    total += d
                elif rem >= MIN_LAST:
                    seq.append([i, round(rem, 3)])
                    total = TOTAL
                    break
            if abs(total - TOTAL) > 1e-3:
                continue
            ms = [[mom[i]["file"], round(d, 3)] for i, d in seq]
            last_full = mom[seq[-1][0]]["dur"]
            if attempt >= 300 and last_full - seq[-1][1] > 0.3:     # новых наборов нет — сдвиг обрезанного хвоста
                ms[-1].append(round(rng.uniform(0.2, last_full - seq[-1][1]), 2))
            k = vkey(ms)
            if k in seen or (attempt < 300 and tuple(x[:2] for x in k) in base_seen):
                continue
            key = k
            break
        if key is None:
            raise SystemExit(f"не хватает уникальных видеорядов на ролик {n + 1}")
        seen.add(key)
        base_seen.add(tuple(x[:2] for x in key))
        for i, _d in seq:
            use[i] = use.get(i, 0) + 1
        jobs.append({"n": n + 1, "text": n % len(TEXTS), "moments": ms,
                     "seed": rng.randint(0, 10 ** 6), "path": kitten_path(rng, n % len(TEXTS))})
    return jobs


def text_top(i: int) -> int:
    return Image.open(D / f"_text{i + 1}.png").getchannel("A").getbbox()[1]


def kitten_path(rng: random.Random, text_i: int) -> list[str]:
    """Котята плавно ходят над текстом внутри безопасной зоны (как в 1324 v1), свой путь у ролика."""
    cw, ch = M.meme_size()
    xmin, xmax, ymin = M.SAFE_X0, M.SAFE_X1 - cw, M.SAFE_Y0
    ymax = text_top(text_i) - M.TEXT_GAP - ch
    cx, ax, cy, ay = (xmin + xmax) / 2, (xmax - xmin) / 2, (ymin + ymax) / 2, (ymax - ymin) / 2
    f1, f2, g1, g2 = rng.uniform(.07, .13), rng.uniform(.17, .26), rng.uniform(.06, .11), rng.uniform(.15, .24)
    p = [rng.uniform(0, 6.283) for _ in range(4)]
    return [f"{cx:.1f}+{ax * .7:.1f}*sin(2*PI*{f1:.4f}*t+{p[0]:.3f})+{ax * .3:.1f}*sin(2*PI*{f2:.4f}*t+{p[1]:.3f})",
            f"{cy:.1f}+{ay * .7:.1f}*sin(2*PI*{g1:.4f}*t+{p[2]:.3f})+{ay * .3:.1f}*sin(2*PI*{g2:.4f}*t+{p[3]:.3f})"]


def build(job: dict) -> str:
    work = Path(tempfile.mkdtemp(prefix="r1324_"))
    rng = random.Random(job["seed"])
    logo = work / "logo.png"
    lx, ly, _lr = B.logo_png(rng, (BAND_Y, BAND_Y + BAND), logo)
    cw, ch = B.banner_anim()
    bx = (W - cw) // 2
    by = BAND_Y + BAND - 16 - ch + round(ch * 0.06)
    inputs, parts = [], []
    for k, mo in enumerate(job["moments"]):
        name, d = mo[0], mo[1]
        off = mo[2] if len(mo) > 2 else 0.0           # обрезанный момент можно брать не с начала (уникальность)
        inputs += (["-ss", f"{off:.3f}"] if off else []) + ["-i", str(SCENES / name)]
        parts.append(f"[{k}:v]fps={FPS},scale=1920:1080:flags=lanczos,crop={BAND}:{BAND}:{(1920 - BAND) // 2}:0,"
                     f"tpad=stop_mode=clone:stop=3,trim=duration={d:.4f},setpts=PTS-STARTPTS,setsar=1[v{k}]")
    n = len(job["moments"])
    inputs += ["-loop", "1", "-i", str(D / f"_text{job['text'] + 1}.png"), "-loop", "1", "-i", str(logo),
               "-i", str(B.BANNER_ANIM), "-i", str(M.MEME), "-i", str(M.meme_audio())]
    it, il, ib, im, ia = n, n + 1, n + 2, n + 3, n + 4
    bt = TOTAL / 2 - 4.0                              # промокод 8 с — по центру ролика
    parts += [
        "".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0[g]",
        f"color=black:s={W}x{H}:r={FPS}:d={TOTAL}[bg]",
        f"[bg][g]overlay=0:{BAND_Y}:shortest=1[s1]",
        f"[s1][{il}:v]overlay={lx}:{ly}[s2]",
        f"[{ib}:v]fps={FPS},format=yuva420p,setpts=PTS-STARTPTS+{bt:.3f}/TB[bn]",
        f"[s2][bn]overlay={bx}:{by}:eof_action=pass[s3]",
        f"[{im}:v]fps={FPS},format=rgba,setpts=PTS-STARTPTS[mm]",
        f"[s3][mm]overlay=x='{job['path'][0]}':y='{job['path'][1]}':eval=frame:eof_action=repeat[s4]",
        f"[s4][{it}:v]overlay=0:0:shortest=1,format=yuv420p,{SET_SDR}[v]",
    ]
    dest = Path(job["out"]) / f"{job['n']:03d}_{ID}.mp4"
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[v]", "-map",
                    f"{ia}:a", "-t", f"{TOTAL}", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(FPS),
                    *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k", "-map_metadata", "-1", "-movflags", "+faststart",
                    str(dest)], check=True)
    return dest.name


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=300)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--resume", action="store_true", help="собрать недостающие файлы по manifest.json папки")
    ap.add_argument("--avoid", action="append", default=[], help="папка сданной партии: её видеоряды не повторять")
    ap.add_argument("--seed", type=int, default=1324)
    args = ap.parse_args()
    D.mkdir(parents=True, exist_ok=True)
    for i, t in enumerate(TEXTS, 1):
        print(f"текст {i}: {T.text_png(t, D / f'_text{i}.png')} px", flush=True)
    B.banner_anim()
    M.meme_size()
    M.meme_audio()
    out = ROOT / "output" / (args.out or (f"{ID}v2_test" if args.test else f"{ID}v2_{args.count}"))
    if args.resume:
        jobs = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        todo = [j for j in jobs if not (out / f"{j['n']:03d}_{ID}.mp4").exists()]
        print(f"дособрать {len(todo)} из {len(jobs)}", flush=True)
        with ProcessPoolExecutor(args.jobs) as ex:
            for k, name in enumerate(ex.map(build, todo), 1):
                print(f"[{k}/{len(todo)}] {name}", flush=True)
        return 0
    avoid = set()
    for a in args.avoid:
        avoid |= {vkey(j["moments"]) for j in json.loads((ROOT / "output" / a / "manifest.json").read_text(encoding="utf-8"))}
    jobs = plan(args.count, args.seed, avoid)
    if avoid:
        print(f"повторов видеоряда со сданными: {sum(vkey(j['moments']) in avoid for j in jobs)}", flush=True)
    if args.test:
        jobs = jobs[:6]
    out = ROOT / "output" / (args.out or (f"{ID}v2_test" if args.test else f"{ID}v2_{args.count}"))
    out.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        j["out"] = str(out)
    (out / "manifest.json").write_text(json.dumps(jobs, indent=1, ensure_ascii=False), encoding="utf-8")
    todo = [j for j in jobs if not (out / f"{j['n']:03d}_{ID}.mp4").exists()]
    print(f"собрать {len(todo)} из {len(jobs)}", flush=True)
    with ProcessPoolExecutor(args.jobs) as ex:
        for k, name in enumerate(ex.map(build, todo), 1):
            print(f"[{k}/{len(todo)}] {name}", flush=True)
    print("готово →", out)
    return 0


def fix_dupes(out: Path) -> list[dict]:
    """Ролики с тем же видеорядом и текстом, что у более раннего: новый видеоряд — последний (обрезанный) момент
    берётся с другого места (середина/конец) или другой набор моментов. Возвращает задания на пересборку."""
    rng = random.Random(13242)
    mom = moments()
    by = {m["file"]: k for k, m in enumerate(mom)}
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    key = lambda j: (tuple(tuple(x) for x in j["moments"]), j["text"])
    seen, redo = set(), []
    for j in man:
        if key(j) not in seen:
            seen.add(key(j))
            continue
        for _ in range(2000):
            mo = [list(x[:2]) for x in j["moments"]]
            last = mo[-1]
            full = mom[by[last[0]]]["dur"]
            if full - last[1] > 0.3:
                last.append(round(rng.uniform(0.2, full - last[1]), 2))
            else:                                     # последний взят целиком — другой момент с людьми того же хвоста
                used = {x[0] for x in mo}
                alt = [mom[i] for i in PEOPLE if mom[i]["file"] not in used and mom[i]["dur"] >= last[1]]
                if alt:
                    m2 = rng.choice(alt)
                    mo[-1] = [m2["file"], last[1], round(rng.uniform(0, m2["dur"] - last[1]), 2)]
            cand = dict(j, moments=mo)
            if key(cand) not in seen:
                break
        seen.add(key(cand))
        j.update(moments=cand["moments"])
        redo.append(j)
    (out / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    return redo


if __name__ == "__main__":
    raise SystemExit(main())
