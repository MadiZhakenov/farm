#!/usr/bin/env python3
"""
Global Work «I got the job» × вставка прыжков, с текстволлами — уникализация (output/gw_gotjob → N роликов).
Концепция (ТЗ): ролик gotjob (парень говорит в камеру, @alexsmith4694 7701209419048144159) соединяем со вставкой
gw_jump (ноутбук с globalwork.ai, закрывает, празднует, @alexsmith4694 7699438056482376991): звук весь ролик —
как был (голос + тихий трек рефа), посреди рассказа вместо лица идёт вставка, а возвращается он ровно на «Thank you…».
Вставка — цельное действие, а не обрывок: «ноутбук» (показал сайт → закрыл → поднял над головой) или «празднование»
(ноутбук над головой → разворот, руки вверх); после закрытия ноутбука — слоу-мо, длина подгоняется силой замедления
и началом показа, а не обрезанием действия. Начало вставки — на начале фразы (после паузы), конец — на «Thank».
Весь ролик ускорен в 1.30–1.40× (голос без «бурундука» — atempo).
Поверх всего — текстволл (3 текста ТЗ, дословно, переносы по смыслу): белый TikTok-шрифт с чёрной обводкой,
крупно и по центру безопасной зоны, как типичные текстволлы (лицо может закрывать — так договорились).
Собираем из исходников (downloads/gw_gotjob/src, downloads/gw_jump/src), старых надписей нет.
Отличия роликов: дубль (3), текст (3), вставка (2), наезд на склейках, зеркало (текст накладывается после — читается),
цвет, скорость 1.30/1.35/1.40, зерно. Набор — жадно по максимуму различий.

  python build_gw_gotjob_uniq.py --test        # 3 ролика (по одному на текст) → output/gw_gotjob_uniq/_test
  python build_gw_gotjob_uniq.py -n 35         # → output/gw_gotjob_uniq/{G,A,B}/ только ролики (кэш, списки — output/_work)
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import random
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_gotjob_reels as G  # noqa: E402  (куски речи, громкость, трек рефа)
import build_gw_wall_reels as WL  # noqa: E402  (рендер текстволла: белый TikTok-шрифт с обводкой, эмодзи)
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF, W, H, FPS = G.FF, G.W, G.H, G.FPS
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
OUT = ROOT / "output" / "gw_gotjob_uniq"                     # здесь только готовые ролики
WORK = ROOT / "output" / "_work" / "gw_gotjob_uniq"          # служебное: кэш, тесты, списки
CACHE = WORK / "_cache"
ID = "noid"

# тексты ТЗ дословно; переносы по смыслу (\n), абзацы — пустая строка; строки короткие, чтобы кегль был крупнее
TEXTS = [
    "i was unemployed for 11 months\nand my whole personality became\n“yeah i’m working on something”.\n"
    "my girlfriend stopped asking.\nmy mom started sending me\njob posts like love letters.\n"
    "i sent the same cv to 400 jobs\nlike a man firing a shotgun\nin the dark.\n\n"
    "then my cousin sent me\nGlobal Work.\nit matches jobs and rewrites\nyour cv for each one,\nyou just approve.\n"
    "i opened it at 2am\nout of pure spite.\na few weeks later\ni’m explaining to my mom\nthat no,\n"
    "it’s not a pyramid scheme,\ni have a contract 💀",
    "i was a “head of” something\nfor 6 years\nand after the layoff my calendar\nhad exactly one event: “gym.”\n"
    "my girlfriend asked\nwhat i do all day\nand i said “networking.”\ni hadn’t talked to anyone\n"
    "except the delivery guy.\n\n"
    "then i found Global Work,\nwhich finds senior roles\nand adapts your resume\nfor each one.\n"
    "you approve every application\nyourself.\nthe first time a recruiter wrote\n“we’d love to chat”\n"
    "i read it out loud\nto my girlfriend\nlike it was a love letter.\nshe said “so you’re back?”\n"
    "i said “i’m in the process”\nand she hugged me anyway 🥲",
    "every recruiter i spoke to\nthis year said the same thing:\n“we’ll get back to you.”\n14 times.\n"
    "i started keeping a spreadsheet\nof people who will\n“get back to me.”\nit has a column for “likelihood”\n"
    "and it’s all zeros.\n\n"
    "a friend from my old team\ntold me about Global Work.\nit picks roles at your level\n"
    "and rewrites your cv\nfor each vacancy,\nyou hit approve.\nthe 15th recruiter\nactually got back to me.\n"
    "i almost didn’t recognize\nthe feeling.\ni now have a new spreadsheet.\nit’s called “offers” 📊",
]
WALL_CY = (WL.Y0 + WL.Y1) // 2                      # центр безопасной зоны 9:16 (870)
WALL_PX_MAX = 60

# креаторы: дубли gotjob (папка, имена), точка наезда по y, ролики с прыжками (gw_jump*)
D2 = ROOT / "downloads"
CREATORS = {
    "G": dict(src=D2 / "gw_gotjob" / "src", takes=["IMG_2937", "IMG_2938", "IMG_2939"], zoom_cy=G.ZOOM_CY,
              jumps=["IMG_2922"]),
    "A": dict(src=D2 / "gw_gotjob2" / "srcA", takes=["IMG_5700", "IMG_5704", "IMG_5705"], zoom_cy=G.ZOOM_CY,
              jumps=["IMG_5708"]),   # 5675/5676 ~29 к/с: слоу-мо с дорисовкой кадров глючит на быстром движении
    "B": dict(src=D2 / "gw_gotjob2" / "srcB", takes=["IMG_8111", "IMG_8114"], zoom_cy=240, jumps=["IMG_8076"]),
}
# ролик с прыжками: файл, к/с, показ ноутбука в 1× (начало, конец = закрыл/опустил), празднование (начало, конец).
# IMG_2922: 1.0–2.5 показывает сайт, 2.75–3.3 закрывает, 4.0–7.25 празднует с ноутбуком над головой.
JUMPS = {
    "IMG_2922": dict(path=D2 / "gw_jump" / "src" / "IMG_2922.MOV", fps=60, show=(1.0, 3.3), cel=(4.0, 7.25)),
    "IMG_5675": dict(path=D2 / "gw_jump2" / "src" / "IMG_5675.MOV", fps=29, show=(0.5, 2.6), cel=(3.1, 9.0)),
    "IMG_5676": dict(path=D2 / "gw_jump2" / "src" / "IMG_5676.MOV", fps=29, show=(0.75, 2.4), cel=(2.9, 10.0)),
    "IMG_5708": dict(path=D2 / "gw_jump2" / "src" / "IMG_5708.MOV", fps=60, show=(0.0, 2.1), cel=(2.6, 8.5)),
    "IMG_8076": dict(path=D2 / "gw_jump3" / "src" / "IMG_8076.MOV", fps=60, show=(0.0, 2.0), cel=(2.5, 7.85)),
}
# Прыжки/празднование — только слоу-мо.
INSERT_KINDS = ["laptop", "celebrate"]
SLOW = 0.5
MIN_INSERT, MAX_INSERT = 3.8, 5.0                    # длина вставки в основе (до ускорения), с
DIMS = {"take": None, "jump": None, "text": [0, 1, 2], "insert": INSERT_KINDS, "mirror": [0, 1],
        "zoom": [1.06, 1.10, 1.14], "grade": ["none", "warm", "cool", "punchy", "soft"], "speed": [1.30, 1.35, 1.40]}
WEIGHT = {"take": 1.5, "jump": 1.0, "text": 2.0, "insert": 1.5, "mirror": 1.0, "zoom": 1.0, "grade": 1.0, "speed": 1.0}
GRADES = {"none": "", "warm": "colorbalance=rs=0.04:bs=-0.04:rm=0.03:bm=-0.03",
          "cool": "colorbalance=rs=-0.03:bs=0.04:rm=-0.02:bm=0.03", "punchy": "eq=contrast=1.07:saturation=1.12",
          "soft": "eq=contrast=0.94:saturation=0.94:brightness=0.015"}


def dur_of(p: Path) -> float:
    return float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)


# ---------------- основа: говорящая голова (джамп-каты + наезд), голос + трек ----------------
def use_creator(tag: str) -> dict:
    c = CREATORS[tag]
    G.SRC, G.ZOOM_CY = c["src"], c["zoom_cy"]
    return c


def base(take: str, zoom: float, zfirst: int) -> tuple[Path, list]:
    """Склейка кусков речи, наезд `zoom` на каждом втором куске (с zfirst), звук как в gotjob (голос −16 + трек −25 → −14).
    Папка дублей и точка наезда — из use_creator()."""
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / f"base_{take}_{zoom}_{zfirst}.mp4"
    segs = G.segments(take)
    if dest.exists():
        return dest, segs
    src = G.SRC / f"{take}.MOV"
    k = len(segs)
    zw, zh = round(W * zoom / 2) * 2, round(H * zoom / 2) * 2
    zy = int(G.ZOOM_CY * zoom - G.ZOOM_CY)
    vf = [f"[0:v]{G.TM},fps={FPS},split={k}" + "".join(f"[s{i}]" for i in range(k))]
    af = [f"[0:a:0]asplit={k}" + "".join(f"[t{i}]" for i in range(k))]
    for i, (a, b) in enumerate(segs):
        z = f",scale={zw}:{zh},crop={W}:{H}:{(zw - W) // 2}:{zy}" if i % 2 == zfirst else ""
        vf.append(f"[s{i}]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS{z},setsar=1[v{i}]")
        af.append(f"[t{i}]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,"
                  f"afade=t=in:d=0.01,afade=t=out:st={max(0, b - a - 0.012):.3f}:d=0.012[a{i}]")
    total = sum(b - a for a, b in segs)
    fc = ";".join(vf + af) + ";" + "".join(f"[v{i}][a{i}]" for i in range(k)) + f"concat=n={k}:v=1:a=1[v][a]"
    work = CACHE / f"w_{take}_{zoom}_{zfirst}"
    work.mkdir(exist_ok=True)
    raw = work / "raw.mp4"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "14", "-b:v", "0", "-pix_fmt", "yuv420p",
                    "-c:a", "pcm_s16le", str(raw)], check=True)
    voice, music, tmp, mix, fin = (work / f"{n}.wav" for n in ("voice", "music", "music_raw", "mix", "final"))
    G.loudnorm(raw, voice, G.VOICE_I, "highpass=f=80")
    subprocess.run([FF, "-v", "error", "-y", "-i", str(G.MUSIC), "-t", f"{total:.3f}", "-af",
                    f"afade=t=out:st={max(0, total - 0.6):.3f}:d=0.6", str(tmp)], check=True)
    G.loudnorm(tmp, music, G.MUSIC_I)
    subprocess.run([FF, "-v", "error", "-y", "-i", str(voice), "-i", str(music), "-filter_complex",
                    "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[m]", "-map", "[m]", str(mix)], check=True)
    G.loudnorm(mix, fin, G.FINAL_I)
    subprocess.run([FF, "-v", "error", "-y", "-i", str(raw), "-i", str(fin), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "pcm_s16le", "-shortest", str(dest)], check=True)
    return dest, segs


def insert_window(take: str, segs: list) -> tuple[float, float]:
    """Вставка: конец — на первом «Thank/Thanks» (креатор возвращается в кадр на благодарности), начало — на начале
    фразы (слово после паузы ≥ 0.2 с или начало куска) так, чтобы длина была 3.8–5 с (иначе ровно 3.8 с). Время основы."""
    words = json.loads((G.SRC / "words.json").read_text(encoding="utf-8"))[take]
    thank = next(t for w, t, *_ in words if w.lower().startswith("thank") and t > 5)

    def to_out(t: float) -> float:
        acc = 0.0
        for s0, s1 in segs:
            if t < s0:
                return acc
            if t <= s1:
                return acc + t - s0
            acc += s1 - s0
        return acc
    t2 = to_out(thank) - 0.06
    starts = []
    for k, (w, t, e) in enumerate(words):
        prev_end = words[k - 1][2] if k else -9
        seg_start = any(abs(t - s0) < 0.25 for s0, _s1 in segs)
        if t - prev_end >= 0.2 or seg_start:
            starts.append(to_out(t) - 0.06)
    ok = [s for s in starts if MIN_INSERT <= t2 - s <= MAX_INSERT]
    t1 = max(ok) if ok else t2 - MIN_INSERT
    return round(max(0.0, t1), 2), round(t2, 2)


def insert_plan(jump: str, kind: str, L: float) -> list[tuple[float, float, float]]:
    """Куски ролика с прыжками (начало, конец, скорость), в сумме ровно L с: цельное действие, празднование — слоу-мо.
    «ноутбук»: показ сайта в 1× (сколько влезет, ≥ 0.8 с) → плавное торможение → празднование в слоу-мо;
    «празднование»: только празднование в слоу-мо (если его мало — замедляем чуть сильнее, а не режем)."""
    j = JUMPS[jump]
    s0, lap = j["show"]
    c0, c1 = j["cel"]
    ramp = [(lap, lap + 0.1, 0.8), (lap + 0.1, lap + 0.2, 0.65)]   # плавное торможение в слоу-мо
    if kind == "laptop":
        rl = sum((b - a) / sp for a, b, sp in ramp)
        # сайт показываем столько, чтобы после торможения осталось ≈ 1 с праздника в слоу-мо
        show = min(lap - s0, max(0.8, L - rl - (min(c0 + 1.0, c1) - lap - 0.2) / SLOW))
        rest = L - rl - show
        end, sp = lap + 0.2 + rest * SLOW, SLOW
        if end > c1:                                                  # праздника не хватает — замедляем сильнее
            end, sp = c1, (c1 - lap - 0.2) / rest
        return [(round(lap - show, 3), lap, 1.0), *ramp, (round(lap + 0.2, 3), round(end, 3), round(sp, 4))]
    span = min(c1 - c0, L * SLOW)
    return [(c0, round(c0 + span, 3), round(span / L, 4))]


def insert_clip(jump: str, kind: str, L: float) -> Path:
    """Вставка ровно L с, 1080×1920 30 к/с, без звука (кэш). HDR iPhone → SDR; где после замедления меньше 30 настоящих
    кадров/с (исходник ~29 к/с), дорисовываем промежуточные кадры (minterpolate), как в gw_jump2."""
    dest = CACHE / f"ins3_{jump}_{kind}_{L:.2f}.mp4"
    if dest.exists():
        return dest
    j = JUMPS[jump]
    segs = insert_plan(jump, kind, L)
    hdr = "arib-std-b67" in subprocess.run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                            "stream=color_transfer", "-of", "csv=p=0", str(j["path"])],
                                           capture_output=True, text=True).stdout
    pre = (G.TM if hdr else f"scale={W}:{H}:flags=lanczos") + f",setsar=1,fps={min(j['fps'], 60)}"
    mi = "minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:scd=none"
    parts = [f"[0:v]{pre},split={len(segs)}" + "".join(f"[s{i}]" for i in range(len(segs)))]
    for i, (a, b, sp) in enumerate(segs):
        interp = sp < 1 and j["fps"] * sp < 29.5
        b2 = b + (0.15 if interp else 0)                              # интерполяция съедает кадры на стыке
        parts.append(f"[s{i}]trim=start={a}:end={b2},setpts=(PTS-STARTPTS)/{sp}{',' + mi if interp else ''}[p{i}]")
    parts.append("".join(f"[p{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0,fps={FPS},"
                 f"trim=duration={L:.3f},setpts=PTS-STARTPTS,setsar=1[v]")
    subprocess.run([FF, "-v", "error", "-y", "-i", str(j["path"]), "-filter_complex", ";".join(parts), "-map", "[v]", "-an",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "14", "-b:v", "0", "-pix_fmt", "yuv420p",
                    str(dest)], check=True)
    return dest


# ---------------- текстволл ----------------
def wall_png(text: int) -> Path:
    """Самый крупный кегль, при котором строки не переносятся сами и весь блок влезает в безопасную зону;
    блок — по центру зоны."""
    dest = CACHE / f"wall2_{text}.png"
    if dest.exists():
        return dest
    t = TEXTS[text]
    n_lines = len([ln for ln in t.split("\n") if ln.strip()])
    room = WL.Y1 - WL.Y0 - 8
    px = WALL_PX_MAX
    while px > 28 and (WL.wall_height(t, px) > room or len([x for x in WL.wall_lines(t, px) if x]) > n_lines):
        px -= 1
    top = max(WL.Y0 + 4, int(WALL_CY - WL.wall_height(t, px) / 2))
    WL.render_wall(t, px, top, dest)
    print(f"текст {text + 1}: {px} px, строк {n_lines}, верх {top}", flush=True)
    return dest


# ---------------- выбор вариантов ----------------
def pick_specs(n: int, rng: random.Random, c: dict) -> list[dict]:
    dims = dict(DIMS, take=c["takes"], jump=c["jumps"])
    keys = list(dims)
    combos = [dict(zip(keys, v)) for v in itertools.product(*(dims[k] for k in keys))]
    rng.shuffle(combos)
    use = {k: {v: 0 for v in dims[k]} for k in keys}

    def dist(x, y):
        return sum(WEIGHT[k] for k in keys if x[k] != y[k])

    picked = [combos[0]]
    for k in keys:
        use[k][combos[0][k]] += 1
    while len(picked) < n:
        best = max(combos, key=lambda c: (min(dist(c, p) for p in picked), -sum(use[k][c[k]] for k in keys), rng.random()))
        picked.append(best)
        for k in keys:
            use[k][best[k]] += 1
    for c in picked:
        c["zfirst"] = rng.choice([0, 1])
        c["grain"] = int(rng.random() < 0.4)
    return picked


# ---------------- сборка ролика ----------------
def render(job: dict) -> str:
    sp, spec = job["spec"]["speed"], job["spec"]
    t1, t2, total = job["t1"], job["t2"], job["total"]
    pre = [x for x in ("hflip" if spec["mirror"] else "", "noise=alls=4:allf=t+u" if spec["grain"] else "",
                       GRADES[spec["grade"]]) if x]
    fc = (f"[0:v]split=2[x][y];[x]trim=0:{t1:.3f},setpts=PTS-STARTPTS[p1];"
          f"[y]trim=start={t2:.3f},setpts=PTS-STARTPTS[p3];[1:v]setpts=PTS-STARTPTS[p2];"
          f"[p1][p2][p3]concat=n=3:v=1:a=0,{','.join(pre + ['format=yuv420p'])}[c];"
          f"[c][2:v]overlay=0:0,setpts=PTS/{sp},fps={FPS},format=yuv420p,{SET_SDR}[v];"
          f"[0:a]atempo={sp}[a]")
    r = subprocess.run([FF, "-v", "error", "-y", "-i", job["base"], "-i", job["insert"], "-i", job["wall"],
                        "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "h264_nvenc", "-preset", "p6",
                        "-tune", "hq", "-rc", "vbr", "-cq", "27", "-b:v", "0", "-maxrate", "6M", "-bufsize", "12M",
                        "-profile:v", "high", *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k",
                        "-t", f"{total / sp:.3f}", "-movflags", "+faststart", job["dest"]], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{job['dest']}: {r.stderr[-600:]}")
    return job["dest"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=35)
    ap.add_argument("--tags", nargs="+", default=list(CREATORS))
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--test", action="store_true", help="по одному ролику на креатора → _test")
    a = ap.parse_args()
    jobs, rows = [], []
    for ti, tag in enumerate(a.tags):
        c = use_creator(tag)
        specs = pick_specs(a.n, random.Random(f"{a.seed}-{tag}"), c)
        if a.test:
            specs = [dict(specs[0], text=ti % 3, insert=INSERT_KINDS[ti % 2])]
        out = WORK / "_test" if a.test else OUT / tag
        out.mkdir(parents=True, exist_ok=True)
        for i, s in enumerate(specs, 1):
            b, segs = base(s["take"], s["zoom"], s["zfirst"])
            t1, t2 = insert_window(s["take"], segs)
            total = dur_of(b)
            name = f"{tag}_{i:02d}_{ID}.mp4"
            jobs.append({"spec": s, "base": str(b), "insert": str(insert_clip(s["jump"], s["insert"], round(t2 - t1, 2))),
                         "wall": str(wall_png(s["text"])), "t1": t1, "t2": t2, "total": total, "dest": str(out / name)})
            rows.append({"file": name, "creator": tag, **s, "text": s["text"] + 1, "insert_from": t1, "insert_to": t2,
                         "duration": round(total / s["speed"], 2)})
    with ProcessPoolExecutor(a.jobs) as ex:
        for k, fu in enumerate(as_completed([ex.submit(render, j) for j in jobs]), 1):
            print(f"  {k}/{len(jobs)} {Path(fu.result()).name}", flush=True)
    for tag in a.tags:
        mine = [r for r in rows if r["creator"] == tag]
        with (WORK / f"manifest_{tag}{'_test' if a.test else ''}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(mine[0]), delimiter=";")
            w.writeheader()
            w.writerows(mine)
    print(f"готово: {len(jobs)} → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
