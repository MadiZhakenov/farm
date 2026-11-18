#!/usr/bin/env python3
"""
OneState 3 (ID 1) — партия 100 TT + 200 YT с похожестью пар ~1 % (как skinive: measure_skinive_uniq.py, dHash 3 к/с).
Монтаж и звук — как в build_onestate3_reels.py (варианты из тюнера: склейки на долях, «кино» → геймплей, тексты ТЗ,
промокод под текстом, логотип). Уникальность каждого ролика:
  • своё окно кадра в исходнике 2560×1440: зум 1.08–1.45, сдвиг по ширине/высоте, поворот ±1.8° (без чёрных углов);
  • своя скорость геймплея 0.94–1.06; свой цвет (яркость/контраст/насыщенность/гамма/температура), зерно, иногда виньетка;
  • звук ±3 % по тону и темпу (asetrate) — склейки пересчитаны, остаются на долях;
  • текст: свой кегль и высота; промокод — свой зазор и сдвиг; логотип — свой размер/отступ;
  • видеоряд выбирается жадно: из 24 кандидатов — самый непохожий на все уже выбранные (те же секунды исходника
    при похожем окне кадра = похожие кадры). Зеркало не используем: в кадре номера ONE STATE и интерфейс игры
    (а метрика всё равно ловит зеркальные кадры).

  python build_onestate3_uniq.py --tt 100 --yt 200 [--only N]     # → output/onestate_3_TT_100 + output/onestate_3_YT_200
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_onestate3_reels as R  # noqa: E402
from core.gpu_slots import gpu_slot  # noqa: E402
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = R.W, R.H, R.FPS
SW, SH = 2560, 1440
MARGIN = 30
WORK = ROOT / "output" / "_work" / "onestate3"


# куски исходников со своей рамкой (юзер 13.11: «не по центру, сбоку берёшь — разве это смотрибельно»):
# (файл, от, до, центр героя по x, рамка): mid — «кино» без интерфейса, окно по центру;
# lowN — геймплей с интерфейсом сверху (строки заданий, деньги, меню): верх окна не выше N px исходника;
# high — крупный план колеса в драке, коп стреляет в верхней части кадра: окно у верхнего края.
# Начало драки (0–2 с: коп у левого края, мини-карта, джойстик) не берём.
POOL_FIRST = {
    "taxi": [("Taxi_job_1", 0.15, 2.35, 1280, "mid"), ("Taxi_job_1", 13.9, 15.35, 1280, "mid")],
    "cop": [("Polic_job", 0.2, 7.6, 1220, "mid"), ("Polic_job", 7.7, 13.0, 1260, "low340")],
}
POOL_SECOND = {
    "taxi": POOL_FIRST["taxi"] + [("Taxi_job_1", 15.45, 17.1, 1280, "mid")],
    "cop": POOL_FIRST["cop"] + [("Police_job_fight_with_Gang", 2.0, 3.9, 1200, "mid")],
}
POOL_GAME = {
    "taxi": [("Taxi_job_1", 2.5, 13.75, 1280, "low200"), ("Taxi_job_1", 17.2, 27.75, 1280, "low200")],
    "cop": [("Polic_job", 13.0, 16.35, 1300, "low340"), ("Polic_job", 16.45, 17.33, 1200, "low340"),
            ("Polic_job", 17.4, 18.95, 1200, "mid"), ("Polic_job", 19.0, 23.0, 1280, "low340"),
            ("Police_job_fight_with_Gang", 2.0, 3.95, 1200, "mid")],
    # драка 4.35–7.8 (крупно колесо, коп стреляет вверху кадра — под нашей подписью его не видно) не берём
}


def geo(rng: random.Random, cx: int, pan: int, frame: str = "mid") -> dict:
    """Окно 9:16 по центру на герое (сдвиг ≤ ±pan), зум и высота — по рамке куска (см. POOL_*)."""
    if frame.startswith("low"):
        top = int(frame[3:])
        z = rng.uniform(max(1.2, SH / (SH - top) + 0.01), 1.45)       # окно помещается ниже интерфейса
    else:
        z = rng.uniform(1.10, 1.35)
    ch = int(SH / z) // 2 * 2
    cw = int(ch * 9 / 16) // 2 * 2
    x0 = int(cx + rng.uniform(-pan, pan) - cw / 2)
    x0 = max(MARGIN, min(SW - cw - MARGIN, x0)) // 2 * 2
    if frame.startswith("low"):
        y0 = int(rng.uniform(top, SH - ch))
    elif frame == "high":
        y0 = int(rng.uniform(0, 60))
    else:
        y0 = int(SH / 2 + rng.uniform(-40, 40) - ch / 2)
    y0 = max(0, min(SH - ch, y0)) // 2 * 2
    return dict(x0=x0, y0=y0, cw=cw, ch=ch, ang=0.0)


def candidate(rng: random.Random, prof: str, v: dict) -> dict:
    rng.uniform(0.94, 1.06)                               # (бывшая скорость — вызов оставлен)
    sp = 1.0                                              # юзер 13.11 «фризит»: скорость ≠ 1 давала повторы/пропуски кадров
    p = round(rng.uniform(0.97, 1.03), 3)                  # тон/темп звука
    cuts = [c / p for c in v["cuts"]]                      # доли в ролике сдвигаются вместе со звуком
    bounds = [0.0] + cuts + [v["total"]]
    pieces, used = [], []
    for k in range(len(bounds) - 1):
        n = round(bounds[k + 1] * FPS) - round(bounds[k] * FPS)
        hook = k < v["hook"]
        pool = POOL_FIRST[prof] if k == 0 else POOL_SECOND[prof] if hook else POOL_GAME[prof]
        need = n / FPS * sp
        fits = [x for x in pool if x[2] - x[1] >= need + 0.05]
        best = None
        for _ in range(60):
            f, a, b, cx, fr_ = rng.choice(fits)
            st = round(rng.uniform(a, b - need), 2)
            over = sum(max(0.0, min(st + need, ue) - max(st, us)) for uf, us, ue in used if uf == f)
            if used and used[-1][0] == f and abs(st - used[-1][2]) < 2.0:
                over += 10.0                              # соседний кусок того же файла рядом по времени = «скачок»
            if best is None or over < best[0]:
                best = (over, f, st, cx, fr_)
            if over == 0:
                break
        _o, f, st, cx, fr_ = best
        used.append((f, st, st + need))
        pan = 60                                           # было 160/300/210 — машина уезжала к краю кадра
        pieces.append(dict(f=f, st=st, n=n, speed=sp, g=geo(rng, cx, pan, fr_)))
    return dict(prof=prof, pitch=p, speed=sp, pieces=pieces, seed=rng.randrange(1 << 30))


def _iou(a: dict, b: dict) -> float:
    ix = max(0, min(a["x0"] + a["cw"], b["x0"] + b["cw"]) - max(a["x0"], b["x0"]))
    iy = max(0, min(a["y0"] + a["ch"], b["y0"] + b["ch"]) - max(a["y0"], b["y0"]))
    inter = ix * iy
    return inter / (a["cw"] * a["ch"] + b["cw"] * b["ch"] - inter)


def overlap(A: dict, B: dict) -> float:
    """Доля секунд ролика A, похожих на кадры B: те же секунды исходника при похожем окне кадра (IoU > 0.35)."""
    m = 0.0
    for pa in A["pieces"]:
        a0, a1 = pa["st"], pa["st"] + pa["n"] / FPS * pa["speed"]
        for pb in B["pieces"]:
            if pa["f"] != pb["f"]:
                continue
            b0, b1 = pb["st"], pb["st"] + pb["n"] / FPS * pb["speed"]
            ov = min(a1, b1) - max(a0, b0)
            if ov > 0 and _iou(pa["g"], pb["g"]) > 0.35:
                m += ov / pa["speed"]
    return m / (sum(p["n"] for p in A["pieces"]) / FPS)


def plan(n: int, seed: int, tries: int = 24) -> list[dict]:
    f = WORK / f"uniq_plan_{n}_{seed}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    vs = R.variants()
    rng = random.Random(seed)
    rows: list = []
    for i in range(n):
        v = vs[i % len(vs)]
        ti = (i // len(vs)) % len(R.TEXTS)
        prof = R.TEXTS[ti][0]
        same = [r for r in rows if r["prof"] == prof]          # такси с копом не пересекаются по исходникам
        best = None
        for _ in range(tries):
            c = candidate(rng, prof, v)
            sc = max((max(overlap(c, r), overlap(r, c)) for r in same), default=0.0)
            if best is None or sc < best[0]:
                best = (sc, c)
        c = best[1]
        c.update(i=i + 1, text=ti, snd=v, score=round(best[0], 3))
        rows.append(c)
        if (i + 1) % 25 == 0:
            print(f"  план {i + 1}/{n}", flush=True)
    WORK.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rows), encoding="utf-8")
    sc = sorted(r["score"] for r in rows)
    print(f"план: {n} роликов, похожесть на ближайший (оценка): медиана {sc[n // 2]:.3f}, макс {sc[-1]:.3f}")
    return rows


def text_png(text: str, rng: random.Random, dest: Path) -> tuple:
    top = rng.randint(212, 300)
    n = len([ln for ln in text.split("\n") if ln.strip()])
    px = rng.randint(56, 62)
    while px > 34 and (R.WL.wall_height(text, px) > 560 or len([x for x in R.WL.wall_lines(text, px) if x]) > n):
        px -= 1
    R.WL.render_wall(text, px, top, dest)
    return Image.open(dest).getbbox()


def render(job: dict) -> str:
    rng = random.Random(job["seed"])
    s = job["snd"]
    out = Path(job["out"])
    fr = WORK / f"u_{out.parent.name}_{out.stem}"
    fr.mkdir(parents=True, exist_ok=True)
    txt, logo = fr / "text.png", fr / "logo.png"
    box = text_png(R.TEXTS[job["text"]][1], rng, txt)
    if bad := check_box(W, H, box):
        raise SystemExit(f"текст вне безопасной зоны {box}: {bad}")
    lx, ly, _ = R.B.logo_png(rng, (0, rng.randint(1500, 1540)), logo)
    cw, ch = R.B.banner_anim()
    bx, by = (W - cw) // 2 + rng.randint(-24, 24), box[3] + rng.randint(4, 26)
    total = sum(p["n"] for p in job["pieces"]) / FPS
    # цвет — один eq (тёплый/холодный оттенок через gamma_r/gamma_b вместо colortemperature) + зерно только по яркости:
    # colortemperature/vignette/цветное зерно на 1080×1920 съедали процессор (замер 13.11: vignette +13 с на 4 с ролика)
    warm = rng.uniform(-0.05, 0.05)
    grade = (f"eq=brightness={rng.uniform(-0.04, 0.04):.3f}:contrast={rng.uniform(0.94, 1.1):.3f}:"
             f"saturation={rng.uniform(0.9, 1.2):.3f}:gamma={rng.uniform(0.93, 1.07):.3f}:"
             f"gamma_r={1 + warm:.3f}:gamma_b={1 - warm:.3f},noise=c0s={rng.randint(3, 9)}:c0f=t")
    inputs, fc, labels = [], [], []
    for k, p in enumerate(job["pieces"]):
        g = p["g"]
        span = p["n"] / FPS * p["speed"] + 0.2
        # 2560×1440 исходники распаковывает видеокарта (NVDEC), кадры возвращаются в память для crop/rotate — процессор
        # свободен; при CUDA — не больше 3 параллельных ffmpeg (правило после сбоя драйвера)
        # видеокарта сама распаковывает, вырезает окно и масштабирует до 1080×1920 (h264_cuvid -crop/-resize) —
        # процессору остаются только склейка и цвет; поворот (только на CPU) больше не делаем — хватает зума/сдвига
        # отступы только чётные: в nv12 цвет хранится парами U/V, нечётный сдвиг по x меняет их местами
        # (жёлтое такси становится голубым)
        x0, y0 = g["x0"] // 2 * 2, g["y0"] // 2 * 2
        crop = f"{y0}x{SH - y0 - g['ch']}x{x0}x{SW - x0 - g['cw']}"
        inputs += ["-c:v", "h264_cuvid", "-crop", crop, "-resize", f"{W}x{H}",
                   "-ss", f"{p['st']:.3f}", "-t", f"{span:.3f}", "-i", str(R.SRC / f"{p['f']}.mp4")]
        fc.append(f"[{k}:v]format=yuv420p,setpts=(PTS-STARTPTS)/{p['speed']},fps={FPS},setsar=1,"   # nv12 из cuvid → yuv420p
                  f"tpad=stop_mode=clone:stop=4,trim=end_frame={p['n']},setpts=PTS-STARTPTS[p{k}]")
        labels.append(f"[p{k}]")
    n = len(labels)
    pitch = job["pitch"]
    inputs += ["-loop", "1", "-i", str(txt), "-loop", "1", "-i", str(logo), "-i", str(R.B.BANNER_ANIM),
               "-ss", f"{s['ss']:.3f}", "-t", f"{total * pitch + 0.4:.2f}", "-i", s["f"]]
    it, il, ib, ia = n, n + 1, n + 2, n + 3
    fc += ["".join(labels) + f"concat=n={n}:v=1:a=0,{grade},format=yuv420p[g]",
           f"[g][{il}:v]overlay={lx}:{ly}:shortest=1[a1]",
           f"[{ib}:v]fps={FPS},format=yuva420p,setpts=PTS-STARTPTS+{rng.uniform(0.3, 0.8):.2f}/TB[bn]",
           f"[a1][bn]overlay={bx}:{by}:eof_action=pass[a2]",
           f"[a2][{it}:v]overlay=0:0:shortest=1,format=yuv420p[v]",
           f"[{ia}:a]aresample=44100,asetrate={44100 * pitch:.0f},aresample=44100,atrim=0:{total:.3f},"
           f"asetpts=PTS-STARTPTS,aformat=channel_layouts=stereo,loudnorm=I=-14:TP=-1.5:LRA=11,"
           f"afade=t=out:st={total - 0.3:.3f}:d=0.3[aud]"]
    (fr / "graph.txt").write_text(";\n".join(fc), encoding="utf-8")
    with gpu_slot():                                        # общий лимит: ≤ 3 CUDA-ffmpeg на весь компьютер (core/gpu_slots.py)
      subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex_script", str(fr / "graph.txt"),
                    "-map", "[v]", "-map", "[aud]", "-t", f"{total:.3f}", "-r", str(FPS),
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(out)], check=True)
    shutil.rmtree(fr)
    return out.name


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tt", type=int, default=100)
    ap.add_argument("--yt", type=int, default=200)
    ap.add_argument("--seed", type=int, default=31340)   # 31337 — сдвиг вбок, 31338/39 — пробы рамки
    ap.add_argument("--only", type=int, default=0, help="собрать только первые N роликов плана (замер похожести)")
    ap.add_argument("--jobs", type=int, default=3)          # CUDA-распаковка → не больше 3
    a = ap.parse_args()
    R.B.banner_anim()
    rows = plan(a.tt + a.yt, a.seed)
    tt, yt = ROOT / "output" / f"onestate_3_TT_{a.tt}", ROOT / "output" / f"onestate_3_YT_{a.yt}"
    nt = ny = 0
    for r in rows:                                          # 1 из 3 — в TT, пока не набрали
        if (r["i"] % 3 == 1 and nt < a.tt) or ny >= a.yt:
            nt += 1
            r["out"] = str(tt / f"{nt:03d}_1.mp4")
        else:
            ny += 1
            r["out"] = str(yt / f"{ny:03d}_1.mp4")
    for d in (tt, yt):
        d.mkdir(parents=True, exist_ok=True)
        man = {Path(r["out"]).name: r for r in rows if Path(r["out"]).parent == d}
        (WORK / f"manifest_{d.name}.json").write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    todo = [r for r in rows[:a.only or None] if not Path(r["out"]).exists()]
    bad = []
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(render, r) for r in todo]
        for r, f in zip(todo, futs):
            try:
                print(" ", Path(r["out"]).parent.name, f.result(), flush=True)
            except Exception as e:                       # noqa: BLE001
                Path(r["out"]).unlink(missing_ok=True)
                bad.append(r["out"])
                print("  ОШИБКА", r["out"], e, flush=True)
    if bad:
        print("не собрались (перезапусти — доделает только их):", len(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
