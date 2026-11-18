#!/usr/bin/env python3
"""
Drops 2 (ID 1) — «THE GAME IS HARDER THAN THE BEAT», 8–10 с:
  0–2 с   удивлённое лицо + хук (текст ТЗ дословно, белый TikTok-шрифт с обводкой, сверху)
  2–8 с   непрерывный геймплей Drops — самый напряжённый кусок (окно с максимумом движения)
  8–9.4 с повтор реакции («не могу пройти»: рука на лбу / у рта)
Монтаж: 2 склейки, обе на долю трека; без доп. графики. Звук — выбранный трендовый трек (downloads/drops2/music_cand)
с самого энергичного места (как в превью), громкость −14 LUFS.
ЛИЦО: в ТЗ — парень; своих клипов с удивлённым парнем нет → в тестах временно реакции девушки из drops_react
(отсмотренные окна REACT из build_drops_beats_reels). Заменить на клипы парня: FACES_IN / FACES_OUT.

  python build_drops2_reels.py --test       # 5 тестов — по одному на каждый трек → output/_work/drops2_test
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_wall_reels as WL  # noqa: E402  (render_wall — белый TikTok-шрифт с обводкой, перенос по строкам)

W, H, FPS = 1080, 1920, 30
FACE_DIR = ROOT / "downloads" / "drops_react" / "faces"
GAME_DIR = ROOT / "output" / "drops_react" / "gameplay"
MUSIC_DIR = ROOT / "downloads" / "drops2" / "beats_upload"     # 16.11: свободные биты Pixabay, выбор юзера 1 2 3 6
HOOKS = [
    "I TURNED MY OWN SONG\nINTO A GAME\nAND NOW I CAN'T\nEVEN BEAT IT 😭💀",
    "BRO I MADE A GAME\nOUT OF MY OWN BEAT\nAND WHY IS IT\nACTUALLY SO HARD 😭",
]
# (клип, начало, длина): удивление / задумался — для начала; «не могу» (рука на лбу, у рта) — для конца
FACES_IN = [("IMG_5721", 3.0, 2.0), ("IMG_5729", 4.0, 2.0), ("IMG_5733", 0.0, 2.0), ("IMG_5737", 0.45, 1.8)]
FACES_OUT = [("IMG_5723", 0.3, 1.4), ("IMG_5723", 1.6, 1.4), ("IMG_5729", 0.5, 1.4), ("IMG_5721", 0.5, 1.4)]
GAMES = ["rhythm_dock_3", "runner_forest_3", "shooter_ariavale_12", "drift_graveyard_3", "shooter_partypop_5",
         "platformer_rooftop_3", "flight_meltdown_3"]
# трек → старт самого энергичного места (с), как в превью output/_work/drops2/music_previews
TRACKS = {"jersey_rush.mp3": 48.5, "night_drift.mp3": 11.5, "jungle_garden.mp3": 63.5, "bitwise_fast.mp3": 80.5}
# запись Drops 1210×2100: сверху жёлтая полоса страницы (название игры, «Share») до y≈132, снизу меню Ranks/Info с y≈1852 —
# оставляем только поле игры и режем бока до 9:16
GAME_CROP = "963:1712:123:136"
T_FACE, T_GAME_END = 2.0, 8.0                           # ориентиры склеек по ТЗ — подтягиваем к ближайшей доле


def beats(track: Path, ss: float, dur: float) -> list[float]:
    import librosa
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{ss:.2f}", "-t", f"{dur:.2f}", "-i", str(track), "-ac", "1",
                          "-ar", "22050", "-f", "f32le", "-"], capture_output=True).stdout
    y = np.frombuffer(raw, np.float32)
    _, b = librosa.beat.beat_track(y=y, sr=22050)
    return [float(t) for t in librosa.frames_to_time(b, sr=22050)]


def snap(t: float, bs: list[float], lo: float, hi: float) -> float:
    c = [b for b in bs if lo <= b <= hi]
    return min(c, key=lambda b: abs(b - t)) if c else t


def tense_window(game: str, dur: float) -> float:
    """Начало окна dur с максимумом движения (самый напряжённый момент) в живой части записи."""
    runs = json.loads((GAME_DIR / "_runs.json").read_text(encoding="utf-8"))
    f = GAME_DIR / f"{game}.mp4"
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                 capture_output=True, text=True).stdout)
    lo, hi = runs.get(game, [2.5, total - 2.5])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{lo:.2f}", "-t", f"{hi - lo:.2f}", "-i", str(f), "-vf",
                          "fps=10,scale=90:160", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, 160, 90).astype(np.int16)
    m = np.abs(np.diff(v, axis=0)).mean(axis=(1, 2))
    n = int(dur * 10)
    if len(m) <= n:
        return lo
    s = np.convolve(m, np.ones(n), "valid")
    return lo + float(np.argmax(s)) / 10


def render(i: int, hook: str, face_in, face_out, game: str, track: str, out: Path, work: Path, seed: int) -> Path:
    rng = random.Random(seed)
    ss = TRACKS[track]
    tr = MUSIC_DIR / track
    bs = beats(tr, ss, 11.0)
    c1 = snap(T_FACE, bs, 1.6, 2.4)
    c2 = snap(T_GAME_END, bs, 7.6, 8.4)
    t_out = face_out[2]
    total = round((c2 + t_out) * FPS) / FPS
    g_dur = c2 - c1
    g0 = tense_window(game, g_dur)
    fr = work / out.stem
    fr.mkdir(parents=True, exist_ok=True)
    wall = fr / "hook.png"
    px = 64
    while px > 40 and WL.wall_height(hook, px) > 520:
        px -= 2
    WL.render_wall(hook, px, 250, wall)
    z1, z2 = rng.uniform(1.0, 1.06), rng.uniform(1.06, 1.12)
    face_vf = (lambda z: f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
               f"scale=iw*{z:.3f}:-2,crop={W}:{H},setsar=1,format=yuv420p")
    n1, n2, n3 = round(c1 * FPS), round(c2 * FPS) - round(c1 * FPS), round(total * FPS) - round(c2 * FPS)
    fc = [f"[0:v]{face_vf(z1)},trim=end_frame={n1},setpts=PTS-STARTPTS[a]",
          f"[1:v]fps={FPS},crop={GAME_CROP},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,"
          f"format=yuv420p,"
          f"trim=end_frame={n2},setpts=PTS-STARTPTS[b]",
          f"[2:v]{face_vf(z2)},trim=end_frame={n3},setpts=PTS-STARTPTS[c]",
          "[a][b][c]concat=n=3:v=1:a=0[v0]", "[v0][3:v]overlay=0:0[v]",
          f"[4:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
          f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={total - 0.3:.3f}:d=0.3[aud]"]
    (fr / "graph.txt").write_text(";\n".join(fc), encoding="utf-8")
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-ss", f"{face_in[1]:.2f}", "-t", f"{c1 + 0.3:.2f}", "-i", str(FACE_DIR / f"{face_in[0]}.MOV"),
           "-ss", f"{g0:.2f}", "-t", f"{g_dur + 0.3:.2f}", "-i", str(GAME_DIR / f"{game}.mp4"),
           "-ss", f"{face_out[1]:.2f}", "-t", f"{t_out + 0.3:.2f}", "-i", str(FACE_DIR / f"{face_out[0]}.MOV"),
           "-i", str(wall), "-ss", f"{ss:.2f}", "-t", f"{total + 0.3:.2f}", "-i", str(tr),
           "-filter_complex_script", str(fr / "graph.txt"), "-map", "[v]", "-map", "[aud]", "-t", f"{total:.3f}",
           "-r", str(FPS), "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M",
           "-bufsize", "12M", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
           "-color_trc", "bt709", "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact",
           "-flags:v", "+bitexact", "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=",
           "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    shutil.rmtree(fr)
    print(f"  {out.name}: {track[:22]} cuts {c1:.2f}/{c2:.2f} total {total:.2f} game {game}@{g0:.1f}", flush=True)
    return out


# ======================= партия 16.11: 200 YT + 100 TT, без повторов между платформами =======================
# Каждый ролик — своя связка (хук, трек, игра, лицо в начале, лицо в конце); YT и TT берут РАЗНЫЕ связки.
# Сборка по CLAUDE.md: лица — один раз в h264-заготовки, распаковка h264_cuvid (обрезка/масштаб в распаковщике) →
# кадры в обычной памяти → concat/overlay обычными фильтрами → NVENC; gpu_slot; каждый ролик сразу покадрово сверяется
# с исходником и проверяется на чёрные кадры; этап и прогресс — в _qa_progress для дашборда.
import itertools  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

from core import gpu_ffmpeg as G  # noqa: E402
from core.gpu_slots import gpu_slot  # noqa: E402

BWORK = ROOT / "output" / "_work" / "drops2_batch"
BOUT = {"yt": ROOT / "output" / "drops2_YT_200", "tt": ROOT / "output" / "drops2_TT_100"}
# drift_graveyard_3: 72 % кадров записи — повторы (дёрганая запись), покадровая сверка на ней неоднозначна → не берём
BGAMES = [g for g in GAMES if g != "drift_graveyard_3"]
PROG = ROOT / "output" / "_work" / "_qa_progress" / f"{os.getpid()}.json"
GX, GY, GW, GH = 123, 136, 963, 1712                     # = GAME_CROP: только поле игры
TW8, TH8, MASK = 54, 96, 40                             # миниатюры для сверки; строки < MASK — под хуком, не сравниваем


def prog(stage: str, done: int = 0, total: int | None = None) -> None:
    try:
        PROG.parent.mkdir(parents=True, exist_ok=True)
        PROG.write_text(json.dumps(dict(stage=stage, done=done, total=total), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def face_proxy(face) -> Path:
    clip, t0, dur = face
    with gpu_slot():
        return G.cut_segment(FACE_DIR / f"{clip}.MOV", t0, t0 + dur + 0.5, BWORK / "faces" / f"{clip}_{t0:.2f}.mp4")


def track_starts(track: str, n: int = 3, win: float = 11.0) -> list[float]:
    """n самых плотных по ударам окон трека (разнесены ≥ 8 с) — старт музыки меняется от ролика к ролику."""
    import librosa
    y, sr = librosa.load(MUSIC_DIR / track, sr=22050, mono=True)
    on = librosa.onset.onset_detect(y=y, sr=sr, units="time")
    dur = len(y) / sr
    sc = [(int(((on >= t) & (on < t + win)).sum()), float(t)) for t in np.arange(2.0, dur - win - 0.5, 0.5)]
    sc.sort(reverse=True)
    out: list[float] = [TRACKS[track]]
    for _, t in sc:
        if len(out) >= n:
            break
        if all(abs(t - u) >= 8 for u in out):
            out.append(t)
    return out


def game_windows(game: str, dur: float = 6.6) -> list[float]:
    """Старты окон с движением ≥ 85 % от самого напряжённого (разнесены ≥ 1 с)."""
    runs = json.loads((GAME_DIR / "_runs.json").read_text(encoding="utf-8"))
    f = GAME_DIR / f"{game}.mp4"
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                 capture_output=True, text=True).stdout)
    lo, hi = runs.get(game, [2.5, total - 2.5])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{lo:.2f}", "-t", f"{hi - lo:.2f}", "-i", str(f), "-vf",
                          "fps=10,scale=90:160", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, 160, 90).astype(np.int16)
    m = np.abs(np.diff(v, axis=0)).mean(axis=(1, 2))
    n = int(dur * 10)
    if len(m) <= n:
        return [lo]
    sc = np.convolve(m, np.ones(n), "valid")
    ok = [lo + i / 10 for i in np.argsort(-sc) if sc[i] >= 0.85 * sc.max()]
    out: list[float] = []
    for t in ok:
        if all(abs(t - u) >= 1.0 for u in out):
            out.append(round(float(t), 1))
    return out[:12]


def plan_batch(n_yt: int, n_tt: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    combos = list(itertools.product(range(len(HOOKS)), list(TRACKS), BGAMES, range(len(FACES_IN)), range(len(FACES_OUT))))
    rng.shuffle(combos)
    use: dict = {}
    jobs: list[dict] = []
    left = combos
    for plat, n in (("yt", n_yt), ("tt", n_tt)):
        for k in range(n):                                  # ровно по связкам: меньше всего использованные первыми
            c = min(left[:400], key=lambda c: sum(use.get((i, v), 0) for i, v in enumerate(c)))
            left.remove(c)
            for i, v in enumerate(c):
                use[(i, v)] = use.get((i, v), 0) + 1
            jobs.append(dict(plat=plat, n=k + 1, hook=c[0], track=c[1], game=c[2], fin=c[3], fout=c[4],
                             seed=rng.randrange(1 << 30)))
    return jobs


def thumbs(cmd_in: list, vf: str) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", *cmd_in, "-vf", f"{vf},scale={TW8}:{TH8}:flags=area,format=gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, TH8, TW8).astype(np.float32)


def _t(args: list, dur: float) -> list:
    """Вставить -t перед -i в аргументы gpu_input."""
    return args[:-2] + ["-t", f"{dur:.2f}"] + args[-2:]


def render_b(job: dict, ctx: dict) -> dict:
    rng = random.Random(job["seed"])
    track = job["track"]
    ss = rng.choice(ctx["starts"][track]) + rng.uniform(-0.2, 0.2)
    tr = MUSIC_DIR / track
    bs = beats(tr, ss, 11.0)
    c1 = snap(T_FACE, bs, 1.6, 2.4)
    c2 = snap(T_GAME_END, bs, 7.6, 8.4)
    fin, fout = FACES_IN[job["fin"]], FACES_OUT[job["fout"]]
    t_out = fout[2]
    n1, n2 = round(c1 * FPS), round(c2 * FPS) - round(c1 * FPS)
    n3 = round(t_out * FPS)
    total = (n1 + n2 + n3) / FPS
    g0 = rng.choice(ctx["wins"][job["game"]]) + rng.uniform(0, 0.4)
    z1, z2 = rng.uniform(1.0, 1.06), rng.uniform(1.06, 1.12)
    pin, pout = ctx["proxy"][fin], ctx["proxy"][fout]
    dest = BOUT[job["plat"]] / f"drops2_{job['plat']}_{job['n']:03d}_1.mp4"
    tmp = BWORK / "cand" / dest.name
    tmp.parent.mkdir(parents=True, exist_ok=True)

    def zc(z):                                          # приближение = обрезка центра в распаковщике видеокарты
        cw, ch = int(W / z) // 2 * 2, int(H / z) // 2 * 2
        return ((W - cw) // 4 * 2, (H - ch) // 4 * 2, cw, ch)

    game = GAME_DIR / f"{job['game']}.mp4"
    TR = (TW8 * 4, TH8 * 4)                             # миниатюры для сверки — тем же распаковщиком, что и сборка
    gin = _t(G.gpu_input(game, crop=(GX, GY, GW, GH), resize=(W, H), ss=g0), n2 / FPS + 0.4)
    fin_in = _t(G.gpu_input(pin, crop=zc(z1), resize=(W, H)), c1 + 0.4)
    fout_in = _t(G.gpu_input(pout, crop=zc(z2), resize=(W, H)), t_out + 0.4)
    fc = [f"[0:v]fps={FPS},setsar=1,format=yuv420p,trim=end_frame={n1},setpts=PTS-STARTPTS[a]",
          f"[1:v]fps={FPS},setsar=1,format=yuv420p,trim=end_frame={n2},setpts=PTS-STARTPTS[b]",
          f"[2:v]fps={FPS},setsar=1,format=yuv420p,trim=end_frame={n3},setpts=PTS-STARTPTS[c]",
          "[a][b][c]concat=n=3:v=1:a=0[v0]", "[v0][3:v]overlay=0:0,format=yuv420p[v]",
          f"[4:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
          f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={total - 0.3:.3f}:d=0.3[aud]"]
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", *fin_in, *gin, *fout_in, "-i", str(ctx["hook"][job["hook"]]),
           "-ss", f"{ss:.2f}", "-t", f"{total + 0.3:.2f}", "-i", str(tr), "-filter_complex", ";".join(fc),
           "-map", "[v]", "-map", "[aud]", "-frames:v", str(n1 + n2 + n3), "-r", str(FPS), *G.NVENC,
           "-c:a", "aac", "-b:a", "160k", *G.CLEAN, str(tmp)]
    with gpu_slot():
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            return dict(job, err="timeout")
    if r.returncode:
        return dict(job, err=r.stderr[-400:])
    # покадровая сверка: каждый кадр = кадр исходника по плану (k−3…k+3), строки под хуком не сравниваем
    with gpu_slot():
        out = thumbs(G.gpu_input(tmp, resize=TR), "null")
        ea = thumbs(_t(G.gpu_input(pin, crop=zc(z1), resize=TR), c1 + 0.4), f"fps={FPS}")[:n1]
        eb = thumbs(_t(G.gpu_input(game, crop=(GX, GY, GW, GH), resize=TR, ss=g0), n2 / FPS + 0.4), f"fps={FPS}")[:n2]
        ec = thumbs(_t(G.gpu_input(pout, crop=zc(z2), resize=TR), t_out + 0.4), f"fps={FPS}")[:n3]
    flags: list = []
    if len(out) != n1 + n2 + n3 or len(ea) < n1 or len(eb) < n2 or len(ec) < n3:
        flags.append(("кадров", len(out), len(ea), len(eb), len(ec)))
    else:
        segs = [(0, ea), (n1, eb), (n1 + n2, ec)]
        for f in range(len(out)):
            s0, e = [x for x in segs if x[0] <= f][-1]
            k = f - s0
            d = {dk: float(np.abs(out[f, MASK:] - e[k + dk, MASK:]).mean()) for dk in range(-3, 4)
                 if 0 <= k + dk < len(e)}
            best = min(d, key=d.get)
            if d[best] > 14:
                flags.append((f, "мусор", round(d[best], 1)))
            # не тот кадр — только если он явно ближе к соседнему, а соседний заметно отличается от нужного
            # (на вспышках ритм-игры сжатие даёт ~2 единицы шума и «перетягивает» кадр к почти одинаковому соседу)
            elif best != 0 and d[0] - d[best] > max(1.0, 0.6 * float(np.abs(e[k, MASK:] - e[k + best, MASK:]).mean())):
                flags.append((f, best, round(d[0] - d[best], 2)))
        lum = out.mean(axis=(1, 2))
        flags += [(f, "чёрный") for f in range(len(out)) if lum[f] < 6]
    res = dict(job, ss=round(ss, 2), g0=round(g0, 2), c1=round(c1, 3), c2=round(c2, 3), total=round(total, 3),
               flags=flags[:6])
    if not flags:
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, dest)
    return res


def run_batch(n_yt: int, n_tt: int, seed: int, workers: int, only: int = 0) -> int:
    t_start = time.time()
    BWORK.mkdir(parents=True, exist_ok=True)
    prog("подготовка: заготовки лиц, окна треков и игр", 0, n_yt + n_tt)
    faces = sorted(set(FACES_IN + FACES_OUT))
    with ThreadPoolExecutor(8) as ex:
        fp = ex.map(face_proxy, faces)
        gw = ex.map(game_windows, BGAMES)
        proxy = dict(zip(faces, fp))
        wins = dict(zip(BGAMES, gw))
    starts = {t: track_starts(t) for t in TRACKS}
    hook = {}
    for i, h in enumerate(HOOKS):
        px = 64
        while px > 40 and WL.wall_height(h, px) > 520:
            px -= 2
        hook[i] = BWORK / f"hook_{i}.png"
        WL.render_wall(h, px, 250, hook[i])
    ctx = dict(proxy=proxy, wins=wins, starts=starts, hook=hook)
    print("окна треков:", {k: [round(x, 1) for x in v] for k, v in starts.items()}, flush=True)
    print("окна игр:", {k: len(v) for k, v in wins.items()}, flush=True)
    jobs = plan_batch(n_yt, n_tt, seed)
    for b in BOUT.values():
        b.mkdir(parents=True, exist_ok=True)
    todo = [j for j in jobs if not (BOUT[j["plat"]] / f"drops2_{j['plat']}_{j['n']:03d}_1.mp4").exists()]
    if only:
        todo = todo[:only]
    done, log, lock = len(jobs) - len(todo), [], threading.Lock()
    print(f"план {len(jobs)} (YT {n_yt} + TT {n_tt}), осталось {len(todo)}; подготовка {time.time() - t_start:.0f} с",
          flush=True)

    def work(j):
        nonlocal done
        r = {}
        for attempt in range(3):
            r = render_b(dict(j, seed=j["seed"] + attempt), ctx)
            if not r.get("err") and not r.get("flags"):
                break
            print(f"  {r['plat']}_{r['n']:03d} попытка {attempt + 1}: {r.get('err') or r.get('flags')}", flush=True)
        with lock:
            done += 1
            log.append(r)
            prog("сборка + покадровая проверка", done, len(jobs))
            if done % 25 == 0:
                print(f"  готово {done}/{len(jobs)}  {time.time() - t_start:.0f} с", flush=True)
        return r

    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(work, todo))
    bad = [r for r in res if r.get("err") or r.get("flags")]
    (BWORK / f"manifest_{seed}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    keys = [(j["hook"], j["track"], j["game"], j["fin"], j["fout"]) for j in jobs]
    print(f"ГОТОВО за {time.time() - t_start:.0f} с: связок {len(set(keys))} из {len(keys)} уникальны; "
          f"с ошибкой {len(bad)}", flush=True)
    for r in bad:
        print("  ОШИБКА", r["plat"], r["n"], r.get("err") or r.get("flags"), flush=True)
    prog("готово", len(jobs), len(jobs))
    return 1 if bad else 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--yt", type=int, default=0)
    ap.add_argument("--tt", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1116)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only", type=int, default=0, help="собрать только первые N из плана (проба)")
    a = ap.parse_args()
    if a.yt or a.tt:
        return run_batch(a.yt, a.tt, a.seed, a.workers, a.only)
    out = ROOT / "output" / "_work" / "drops2_test_beats"
    out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "output" / "_work" / "drops2"
    work.mkdir(parents=True, exist_ok=True)
    for k, track in enumerate(TRACKS):
        render(k + 1, HOOKS[k % 2], FACES_IN[k % len(FACES_IN)], FACES_OUT[k % len(FACES_OUT)], GAMES[k % len(GAMES)],
               track, out / f"{k + 1:02d}_{Path(track).stem.split('_7')[0]}_1.mp4", work, 2000 + k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
