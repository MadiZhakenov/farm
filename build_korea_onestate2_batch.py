#!/usr/bin/env python3
"""
Korean OneState 2 (ID 1) — партия 200 TT + 200 YT в виде одобренных тестов (build_korea_onestate2.py):
заголовок, №3 Stumble Guys 3 с → №2 Among Us 3 с → №1 OneState 5 с + баннер-промокод; звук — 4 звука Карины
по очереди (s1–s4, по 100 роликов), звук игр выключен. Юзер 16.11: схожесть НЕ считаем (долго, не для этого проекта).

Быстрее тестов: распаковка + обрезка + масштаб на видеокарте (h264_cuvid -crop -resize → кадры в обычной памяти),
размытый фон — из маленького кадра 320×180, надписи/баннер/звук готовятся один раз, слои — обычный overlay,
кодирование NVENC. Каждый готовый ролик — G.bad_frames (пустые/зелёные/чёрные кадры, повторы посреди движения),
плохой — пересобрать другим вариантом.

Строже тестов по кускам: Stumble — без заставки канала, пролёта «Cannon Climb», «Waiting for players / Next up»,
наблюдения после вылета; у Stumble обрезаны чёрные поля сверху/снизу; Among Us — только где видна кнопка SABOTAGE
(output/_work/korea2/gp_*.json, gp_detect.py) и нет карты/красной тревоги на весь экран.

    python build_korea_onestate2_batch.py --tt 200 --yt 200
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_korea_onestate2 as K  # noqa: E402
from core import gpu_ffmpeg as G  # noqa: E402

W, H, FPS = K.W, K.H, K.FPS
D, WORK = K.D, K.WORK
ASSET = WORK / "batch_assets"
NAME, ID = "korean_onestate_2", 1
NF = [round(d * FPS) for d in K.DUR]                    # 90, 90, 150
TOT = sum(NF)
SOUNDS = ["s1", "s2", "s3", "s4"]
STUMBLE_SRC = "nc_stumble_NY4gI6vO0Vw"
AMONG_SRC = "nc_amongus_p0aHDT8wwrw"          # 30 к/с без повторов (If9X — 50 к/с, каждый 2–3-й кадр повтор)
STUMBLE_BAD = {0, 1, 9, 20, 22, 23, 24}                  # окна mot_*: заставка, пролёт уровня, ожидание/Next up, наблюдение
CONTENT = {STUMBLE_SRC: (0, 108, 1920, 864), AMONG_SRC: (0, 0, 1918, 1080)}            # x, y, w, h картинки без чёрных полей
PROG = ROOT / "output" / "_work" / "_qa_progress" / f"{os.getpid()}.json"


def prog(stage: str, done: int = 0, total: int | None = None) -> None:
    try:
        PROG.parent.mkdir(parents=True, exist_ok=True)
        PROG.write_text(json.dumps(dict(stage=stage, done=done, total=total), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def stumble_windows() -> list[tuple[str, float, float]]:
    w = json.loads((WORK / f"mot_{STUMBLE_SRC}.json").read_text())
    return [tuple(x) for i, x in enumerate(w) if i not in STUMBLE_BAD]


def _frame96(src: Path, t: float) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", "-vf",
                          "scale=96:54", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(54, 96, 3).astype(np.int16)


def map_like(a: np.ndarray) -> bool:
    """Карта саботажа / красная тревога: большие очень насыщенные области."""
    return bool(((a.max(2) - a.min(2)) > 150).mean() > 0.15)


def among_windows() -> list[tuple[str, float, float]]:
    cf = WORK / f"gpwin_{AMONG_SRC}.json"
    if cf.exists():
        return [tuple(x) for x in json.loads(cf.read_text())]
    g = json.loads((WORK / f"gp_{AMONG_SRC}.json").read_text())
    runs, i = [], 0
    while i < len(g):
        if g[i][1] >= 0.75:
            j = i
            while j < len(g) and g[j][1] >= 0.75:
                j += 1
            a, b = g[i][0] + 0.25, g[j - 1][0] + 0.25
            if b - a >= 3.4:
                runs.append((a, b))
            i = j
        else:
            i += 1
    src = D / "games" / f"{AMONG_SRC}.mp4"
    ts = [(a, b, t) for a, b in runs for t in np.arange(a + 0.2, b, 1.0)]
    with ThreadPoolExecutor(4) as ex:
        bad = list(ex.map(lambda x: map_like(_frame96(src, x[2])), ts))
    out = []
    for a, b in runs:
        s = a
        for (ra, rb, t), bd in zip(ts, bad):
            if (ra, rb) != (a, b) or not bd:
                continue
            if t - 0.6 - s >= 3.4:
                out.append((AMONG_SRC, round(s, 2), round(t - 0.6, 2)))
            s = t + 0.6
        if b - s >= 3.4:
            out.append((AMONG_SRC, round(s, 2), round(b, 2)))
    cf.write_text(json.dumps(out))
    return out


def assets() -> None:
    """Один раз: слои (заголовок + подпись места), маленький баннер с прозрачностью, 4 звука по 11 с."""
    ASSET.mkdir(parents=True, exist_ok=True)
    tmp = ASSET
    if not (tmp / "layer2.png").exists():
        K.text_png(K.TITLE, 70, 300, tmp / "title.png")
        for i, lab in enumerate(K.LABELS):
            K.text_png([(lab, (255, 255, 255))], 64, K.BAND_Y - 70 if i < 2 else 720, tmp / f"lab{i}.png")
            im = Image.open(tmp / "title.png").convert("RGBA")
            im.alpha_composite(Image.open(tmp / f"lab{i}.png").convert("RGBA"))
            im.save(tmp / f"layer{i}.png")
    for i in range(3):                                    # обрезка слоя до надписей (чётные края)
        im = Image.open(tmp / f"layer{i}.png").convert("RGBA")
        x0, y0, x1, y1 = im.getbbox()
        x0, y0 = x0 // 2 * 2, y0 // 2 * 2
        x1, y1 = min(W, (x1 + 1) // 2 * 2), min(H, (y1 + 1) // 2 * 2)
        im.crop((x0, y0, x1, y1)).save(tmp / f"layerc{i}.png")
        LAYER_XY[i] = (x0, y0)
    bn = tmp / "banner_small.mov"
    if not bn.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(K.BANNER), "-vf",
                        f"fps={FPS},crop={W}:300:0:810,scale=760:-2,format=argb", "-c:v", "qtrle", str(bn)], check=True)
    T = TOT / FPS
    for s in SOUNDS:
        o = tmp / f"snd_{s}.wav"
        if not o.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(D / "sounds" / f"{s}.mp3"), "-af",
                            f"atrim=0:{T},asetpts=PTS-STARTPTS,aresample=48000,afade=t=out:st={T - 0.4}:d=0.4,"
                            f"loudnorm=I=-14:TP=-1.5", "-ar", "48000", "-ac", "2", str(o)], check=True)


NFR: dict = {}                                          # клип OneState → кадров


def _kept_from(dl: set, start: int, need: int, limit: int) -> int | None:
    """Сколько кадров исходника от start нужно пройти, чтобы набрать need кадров без повторов (None — не хватает)."""
    k, got = start, 0
    while k < limit:
        if k not in dl:
            got += 1
            if got == need:
                return k - start + 1
        k += 1
    return None


OS_OK: dict = {}                                        # клип → начала окон 150 кадров без повторов


def os_clean() -> None:
    """Окна OneState без сбоев записи (повтор кадра посреди движения — как G.bad_frames): клипы без такого окна не берём."""
    for f in K.OS_ALL:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(D / "os_src" / f"{f}.mp4"), "-vf", "scale=54:96",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        fr = np.frombuffer(raw, np.uint8).reshape(-1, 96, 54, 3).astype(np.int16)
        d = np.abs(np.diff(fr.mean(3), axis=0)).mean((1, 2))
        bad = {i + 1 for i in range(len(d)) if d[i] < 0.2 and ((i and d[i - 1] > 0.5) or (i + 1 < len(d) and d[i + 1] > 0.5))}
        ok = [f0 for f0 in range(6, len(fr) - NF[2] - 6) if not any(k in bad for k in range(f0 - 3, f0 + NF[2] + 4))]
        if ok:
            OS_OK[f] = ok
    print("OneState без сбоев:", {f: len(v) for f, v in OS_OK.items()}, flush=True)


STALL: dict = {}                                        # исходник → времена, где игра «замирает» (повтор кадра)


def stall_times(name: str, wins: list) -> list[float]:
    """Где в окнах исходника стоит повтор кадра посреди движения (на 30 к/с ролика: шаг L = родная частота / 30).
    Окна роликов такие места обходят — иначе G.bad_frames бракует ролик и он собирается заново (замер 16.11: ~50 %)."""
    cf = WORK / f"stall_{name}.json"
    if cf.exists():
        return json.loads(cf.read_text())
    src = D / "games" / f"{name}.mp4"
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                          "-of", "csv=p=0", str(src)], capture_output=True, text=True).stdout.strip().split("/")
    fps = float(out[0]) / float(out[1] if len(out) > 1 else 1)
    L = max(1, round(fps / FPS))

    def one(w):
        _, a, b = w
        raw = subprocess.run(["ffmpeg", "-v", "error", "-threads", "2", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(src),
                              "-vf", "scale=96:54,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        f = np.frombuffer(raw, np.uint8).reshape(-1, 54, 96).astype(np.int16)
        if len(f) <= 3 * L:
            return []
        d = np.abs(f[L:] - f[:-L]).mean((1, 2))
        bad = []
        for k in range(len(d)):
            near = d[max(0, k - 3 * L):k + 3 * L + 1]
            if d[k] < 0.2 and (near > 0.5).sum() >= 2:
                bad.append(round(a + k / fps, 3))
        return bad
    with ThreadPoolExecutor(6) as ex:
        res = [t for r in ex.map(one, wins) for t in r]
    cf.write_text(json.dumps(res))
    return res


def make_job(rng: random.Random, n: int, tag: str, k: int) -> dict:
    def win(pool, dur):
        for _ in range(200):                              # окно без «замираний» исходника (stall_times)
            f, a, b = rng.choice([p for p in pool if p[2] - p[1] >= dur + 0.4])
            t = round(rng.uniform(a, b - dur - 0.1), 2)
            if not any(t - 0.15 <= x <= t + dur + 0.15 for x in STALL.get(f, ())):
                break
        return dict(f=f, t=t, z=round(rng.uniform(1.0, 1.15), 3),
                    ox=round(rng.uniform(0.35, 0.65), 3), oy=round(rng.uniform(0.35, 0.65), 3))
    f = rng.choice(sorted(OS_OK))
    f0 = rng.choice(OS_OK[f])
    return dict(n=n, tag=tag, s3=win(STUMBLE, K.DUR[0]), s2=win(AMONG, K.DUR[1]),
                s1=dict(f=f, f0=f0, z=round(rng.uniform(1.18, 1.3), 3), ox=round(rng.uniform(0.4, 0.6), 3)),
                snd=SOUNDS[k % len(SOUNDS)], seed=rng.randrange(10 ** 9))


def _drop(dl: list, start: int, span: int) -> str:
    rel = [x - start for x in dl if start <= x < start + span]
    return ("select='not(" + "+".join(f"eq(n,{r})" for r in rel) + ")'," if rel else "")


def _crop_band(name: str, p: dict) -> tuple[int, int, int, int]:
    """Окно 16:9 (как полоса 1080×608) внутри картинки исходника, зум z, положение ox/oy."""
    cx, cy, cw, ch = CONTENT.get(name, (0, 0, 1920, 1080))
    asp = W / K.BAND_H
    bw, bh = (ch * asp, ch) if cw / ch > asp else (cw, cw / asp)
    w, h = bw / p["z"], bh / p["z"]
    x, y = cx + (cw - w) * p["ox"], cy + (ch - h) * p["oy"]
    return G._even(x), G._even(y), G._even(w), G._even(h)


def _cuvid(src: Path, crop: tuple, resize: tuple, sw: int, sh: int, ss: float) -> list:
    x, y, w, h = crop
    dec = {"av1": "av1_cuvid", "hevc": "hevc_cuvid"}.get(G.probe(src)[0], "h264_cuvid")
    return ["-c:v", dec, "-crop", f"{y}x{sh - y - h}x{x}x{sw - x - w}", "-resize", f"{resize[0]}x{resize[1]}",
            "-ss", f"{ss:.3f}", "-i", str(src)]


def build(j: dict, dest: Path) -> None:
    from core.gpu_slots import gpu_slot
    ins, fc = [], []
    for i, key in enumerate(("s3", "s2")):                # чужие игры: полоса 16:9 на размытом фоне
        p = j[key]
        src = D / "games" / f"{p['f']}.mp4"
        cx, cy, cw, ch = CONTENT.get(p["f"], (0, 0, 1920, 1080))
        ins += _cuvid(src, _crop_band(p["f"], p), (W, K.BAND_H), *G.probe(src)[1:], p["t"])
        a = i
        # Among Us — запись ~30 к/с в контейнере 50 к/с (каждый 2–3-й кадр — повтор): повторы выкидываем и играем
        # оставшиеся кадры по 30 к/с (иначе fps=30 попадает на повторы — «дёргается», bad_frames); Stumble 60 → 30
        # Among Us — запись ~30 к/с в контейнере 50 к/с (каждый 2–3-й кадр — повтор): повторы выкидывает mpdecimate
        # (max=2 — в тихих местах не «съедает» всё подряд), кадры идут по 30 к/с; fps=30 — частота в описании потока,
        # иначе ffmpeg на выходе сам вставляет повторы (замер 16.11). Stumble 60 → 30.
        rate = f"setpts=N/30/TB,fps={FPS}" if "amongus" in p["f"] else f"fps={FPS}"   # 29.97 → ровно 30, без повторов
        # размытый фон — из той же картинки, уменьшенной (без второй распаковки: маленький -resize у cuvid даёт
        # зелёные полосы, замер 16.11)
        fc.append(f"[{a}:v]{rate},trim=end_frame={NF[i]},setpts=PTS-STARTPTS,setsar=1,split[fg{i}][s{i}];"
                  f"[s{i}]scale=192:108,crop=61:108,boxblur=6:2,scale={W}:{H},eq=brightness=-0.12,setsar=1[bg{i}];"
                  f"[bg{i}][fg{i}]overlay=0:{K.BAND_Y}[c{i}]")
    p = j["s1"]                                           # OneState: приближение к низу — верхний интерфейс за краем
    src = D / "os_src" / f"{p['f']}.mp4"
    w, h = G._even(W / p["z"]), G._even(H / p["z"])
    x, y = G._even((W - w) * p["ox"]), H - h
    ins += _cuvid(src, (x, y, w, h), (W, H), W, H, (p["f0"] - 0.5) / FPS)   # полкадра раньше — первый кадр ровно f0
    # в записях клиента бывают повторы кадра (сбой записи, Army 16 на 21 с) — выкидываем по номерам
    fc.append(f"[2:v]fps={FPS},trim=end_frame={NF[2]},setpts=PTS-STARTPTS,setsar=1[c2]")   # окно без сбоев (os_clean)
    for i in range(3):
        ins += ["-i", str(ASSET / f"layerc{i}.png")]
    ins += ["-i", str(ASSET / "banner_small.mov"), "-i", str(ASSET / f"snd_{j['snd']}.wav")]
    for i in range(3):
        lx, ly = LAYER_XY[i]
        fc.append(f"[{3 + i}:v]loop=loop={NF[i] - 1}:size=1:start=0,setpts=N/{FPS}/TB,format=yuva420p[l{i}];"
                  f"[c{i}][l{i}]overlay={lx}:{ly}:format=yuv420[d{i}]")
    fc.append(f"[6:v]fps={FPS},setpts=PTS-STARTPTS,format=yuva420p[bn];"
              f"[d2][bn]overlay=(W-w)/2:430:eof_action=repeat:format=yuv420[e2];"
              f"[d0][d1][e2]concat=n=3:v=1:a=0,format=yuv420p[v]")
    tmp = Path(tempfile.mkdtemp(prefix="kos2b_"))
    (tmp / "g.txt").write_text(";".join(fc), encoding="utf-8")
    part = dest.with_name(dest.stem + ".part.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-nostdin", *ins, "-filter_complex_script", str(tmp / "g.txt"),
           "-map", "[v]", "-map", "7:a", "-frames:v", str(TOT), "-t", f"{TOT / FPS}", *G.NVENC,
           "-c:a", "aac", "-b:a", "192k", *G.CLEAN, str(part)]
    try:
        with gpu_slot():
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode:
            raise RuntimeError(r.stderr[-1200:])
        part.replace(dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        part.unlink(missing_ok=True)


def dup_list(src: Path, fps: float, t0: float = 0.0, dur: float | None = None) -> list[int]:
    """Номера кадров (от t0, родная частота) — точный повтор предыдущего посреди движения (сбой записи / запись 30 к/с
    в контейнере 50 к/с). Неподвижные места не трогаем: повтор = почти 0 при движении в соседних кадрах."""
    cf = WORK / f"dups2_{src.stem}_{t0:.2f}_{dur}.json"
    if cf.exists():
        return json.loads(cf.read_text())
    ss = max(0.0, t0 - 0.5 / fps)                         # на полкадра раньше: первый кадр — ровно кадр t0
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{ss:.4f}", *(["-t", f"{dur:.3f}"] if dur else []), "-i", str(src),
                          "-vf", "scale=96:54,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.uint8).reshape(-1, 54, 96).astype(np.int16)
    d = np.abs(np.diff(a, axis=0)).mean((1, 2))
    mov = np.convolve((d > 0.5).astype(float), np.ones(7), "same") >= 2      # рядом есть движение
    out = [int(i + 1) for i in range(len(d)) if d[i] < 0.15 and mov[i]]
    cf.write_text(json.dumps(out))
    return out


def green_parts(path: Path) -> list:
    """Кадры с зелёными кусками (пустые места кадра видеокарты: Y=U=V=0 → RGB ≈ 0,135,0) — bad_frames ловит только
    целиком зелёный кадр."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "scale=54:96", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 96, 54, 3).astype(np.int16)
    g = (fr[..., 1] > 100) & (fr[..., 1] < 175) & (fr[..., 0] < 25) & (fr[..., 2] < 25)
    return [f"зелёное {i}" for i in np.nonzero(g.mean((1, 2)) > 0.03)[0][:5]]


LAYER_XY: dict = {}
STUMBLE: list = []
AMONG: list = []


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tt", type=int, default=200)
    ap.add_argument("--yt", type=int, default=200)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--seed", type=int, default=61116)
    ap.add_argument("--test", type=int, default=0, help="N роликов в output/_work/korea2/batch_test")
    a = ap.parse_args()
    t0 = time.time()
    prog("подготовка: куски геймплея, надписи, баннер, звуки")
    STUMBLE[:] = stumble_windows()
    AMONG[:] = among_windows()
    assets()
    os_clean()
    STALL[STUMBLE_SRC] = stall_times(STUMBLE_SRC, STUMBLE)
    STALL[AMONG_SRC] = stall_times(AMONG_SRC, AMONG)
    print(f"замирания исходников: Stumble {len(STALL[STUMBLE_SRC])}, Among Us {len(STALL[AMONG_SRC])}", flush=True)
    for f in K.OS:
        NFR[f] = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames",
                                     "-of", "csv=p=0", str(D / "os_src" / f"{f}.mp4")], capture_output=True, text=True).stdout)
    print(f"куски: Stumble {len(STUMBLE)} ({sum(b - a_ for _, a_, b in STUMBLE):.0f} с), "
          f"Among Us {len(AMONG)} ({sum(b - a_ for _, a_, b in AMONG):.0f} с); подготовка {time.time() - t0:.0f} с", flush=True)
    rng = random.Random(a.seed)
    if a.test:
        out = {"tt": WORK / "batch_test", "yt": WORK / "batch_test"}
        slots = [("tt" if i % 2 == 0 else "yt", i + 1) for i in range(a.test)]
    else:
        out = {"tt": ROOT / "output" / f"{NAME}_TT_{a.tt}", "yt": ROOT / "output" / f"{NAME}_YT_{a.yt}"}
        slots = [(tag, n) for tag, cnt in (("tt", a.tt), ("yt", a.yt)) for n in range(1, cnt + 1)]
    jobs = [make_job(rng, n, tag, k) for k, (tag, n) in enumerate(slots)]
    total, done, rej, failed = len(jobs), [0], [0], []

    def one(j: dict) -> str:
        dest = out[j["tag"]] / f"{NAME}_{j['tag']}_{j['n']:03d}_{ID}.mp4"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            done[0] += 1
            return dest.name
        r2 = random.Random(j["seed"])
        for attempt in range(8):
            try:
                build(j, dest)
                bad = G.bad_frames(dest) + green_parts(dest)
            except Exception as e:                        # noqa: BLE001
                bad = [f"ошибка: {str(e)[-300:]}"]
            if not bad:
                done[0] += 1
                prog(f"сборка (заменено {rej[0]})", done[0], total)
                return dest.name
            rej[0] += 1
            print(f"  замена {dest.name}: {bad[:5]}", flush=True)
            dest.unlink(missing_ok=True)
            j = dict(make_job(r2, j["n"], j["tag"], SOUNDS.index(j["snd"])), snd=j["snd"])
        print(f"  ПРОПУСК {dest.name}: 8 вариантов подряд с ошибкой", flush=True)
        failed.append(dest.name)
        return ""

    prog("сборка", 0, total)
    with ThreadPoolExecutor(a.workers) as ex:
        for i, _ in enumerate(ex.map(one, jobs), 1):
            if i % 25 == 0 or i == total:
                el = time.time() - t0
                print(f"  {i}/{total}, заменено {rej[0]}, {el:.0f} с ({i / el * 60:.0f}/мин)", flush=True)
    if failed:
        print(f"НЕ СОБРАНЫ ({len(failed)}): {failed}", flush=True)
    prog(f"готово (заменено {rej[0]})", total, total)
    print(f"ГОТОВО: {total} роликов за {time.time() - t0:.0f} с → {sorted({str(v) for v in out.values()})}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
