#!/usr/bin/env python3
"""
Korean OneState 2 — партия 2 (18.11, ID 1): ещё 200 TT + 200 YT, схожесть ≤1 % между собой И с первой партией
(output/korean_onestate_2_TT_200 + _YT_200). Вид — как первая партия (build_korea_onestate2_batch): заголовок,
№3 Stumble Guys 3 с → №2 Among Us 3 с → №1 OneState 5 с + промо-баннер, 4 звука по очереди.

Откуда уникальность (замер 18.11, отпечаток 17×16: зум на 0.07 или сдвиг окна на ~25 px уже дают 50+ бит при пороге 40):
  - Stumble / Among Us: окно с зумом 1.0–1.4 и сдвигом 0.15–0.85 (первая партия 1.0–1.15 / 0.35–0.65);
  - №1 OneState: в основном горизонтальные записи клиента (downloads/onestate3/src, 2560×1440, 11 клипов) —
    вертикальное окно 9:16 у центра; вертикальные os_src — только зум 1.38–1.55 (первая партия 1.18–1.3);
  - реестр занятых окон: первая партия восстановлена по её зерну (61116), новое окно не берёт то же время исходника
    с похожим кадрированием;
  - каждый готовый ролик: брак (G.bad_frames_arr, зелёные куски) + покадровая сверка с исходником (каждый кадр =
    кадр исходника по плану) + отпечатки каждого кадра против принятых (в обе стороны) и первой партии
    (output/_work/korea2/old400.npz) — core.clip_batch.run, одна распаковка готового ролика на все проверки.

  python build_korea_onestate2_uniq.py --test 6
  python build_korea_onestate2_uniq.py --tt 200 --yt 200 --jobs 6
"""
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_korea_onestate2_batch as B  # noqa: E402
from core import clip_batch as CB  # noqa: E402
from core import gpu_ffmpeg as G  # noqa: E402

K = B.K
W, H, FPS = B.W, B.H, B.FPS
D, WORK, ASSET = B.D, B.WORK, B.ASSET
NF, TOT = B.NF, B.TOT
NAME, ID = "korean_onestate_2_b2", 1
LAND_DIR = ROOT / "downloads" / "onestate3" / "src"
LAND = ["Army_Protection_of_the_base", "Cars", "Crystals", "Drone_drop_1", "Mechanic_job", "Medics_job_1", "Mines_job",
        "Polic_job", "Police_job_1", "Police_job_fight_with_Gang", "Taxi_job_1"]
LW, LH = 2560, 1440
P_LAND = 0.75                                            # доля роликов с горизонтальной записью в №1
CHK_BAND = (B.K.BAND_Y + 16, B.K.BAND_Y + B.K.BAND_H - 16)   # полоса без надписей (сверка №3/№2)
CHK_OS = (1000, 1800)                                    # низ кадра OneState без надписей и баннера (сверка №1)
CS_BAND, CS_OS = (136, 72), (136, 100)
UQ = WORK / "uniq2"


# ───────────────────────── горизонтальные записи OneState: окна без сбоев записи ─────────────────────────
LAND_OK: dict = {}


def land_clean() -> None:
    cf = UQ / "land_ok.json"
    if cf.exists():
        LAND_OK.update(json.loads(cf.read_text()))
        return

    def one(f):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-i", str(LAND_DIR / f"{f}.mp4"), "-vf",
                              "crop=iw*0.32:ih:iw*0.34:0,scale=54:96", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True).stdout
        fr = np.frombuffer(raw, np.uint8).reshape(-1, 96, 54, 3).astype(np.int16)
        d = np.abs(np.diff(fr.mean(3), axis=0)).mean((1, 2))
        bad = {i + 1 for i in range(len(d)) if d[i] < 0.2 and ((i and d[i - 1] > 0.5) or (i + 1 < len(d) and d[i + 1] > 0.5))}
        n = NF[2]
        ok = [f0 for f0 in range(6, len(fr) - n - 6)
              if not any(k in bad for k in range(f0 - 3, f0 + n + 4)) and d[f0:f0 + n].mean() > 0.3]
        return f, ok
    with ThreadPoolExecutor(4) as ex:
        for f, ok in ex.map(one, LAND):
            if ok:
                LAND_OK[f] = ok
    UQ.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps(LAND_OK))


# ───────────────────────── реестр занятых окон (первая партия + новые) ─────────────────────────
REG: dict = {}
REG_LOCK = threading.Lock()


def _close(a: tuple, b: tuple, out: tuple) -> bool:
    """Два окна одного исходника дают похожие кадры: масштаб и центр почти совпадают (в пикселях готового кадра)."""
    (x1, y1, w1, h1), (x2, y2, w2, h2) = a, b
    ds = abs(math.log(w1 / w2)) / 0.045
    dx = abs((x1 + w1 / 2) - (x2 + w2 / 2)) * out[0] / w1 / 28
    dy = abs((y1 + h1 / 2) - (y2 + h2 / 2)) * out[1] / h1 / 28
    return ds * ds + dx * dx + dy * dy < 1.4


def _conflicts(key: str, t0: float, t1: float, rect: tuple, out: tuple) -> int:
    return sum(1 for a, b, r in REG.get(key, ()) if a < t1 + 0.3 and b > t0 - 0.3 and _close(rect, r, out))


def _reg(key: str, t0: float, t1: float, rect: tuple) -> None:
    REG.setdefault(key, []).append((t0, t1, rect))


def _os_rect(p: dict) -> tuple:
    if p.get("land"):
        h = G._even(LH / p["z"])
        w = G._even(h * 9 / 16)
        return G._even((LW - w) * p["ox"]), G._even((LH - h) * p["oy"]), w, h
    w, h = G._even(W / p["z"]), G._even(H / p["z"])
    return G._even((W - w) * p["ox"]), H - h, w, h


VMAP: dict = {}                                          # вертикальный клип → где он в горизонтальной записи (vmap.json)


def _os_key(p: dict) -> str:
    if not p.get("land") and p["f"] in VMAP:
        return "L:" + VMAP[p["f"]]["land"]
    return ("L:" if p.get("land") else "V:") + p["f"]


def _os_reg(p: dict) -> tuple[str, float, float, tuple]:
    """Окно №1 для реестра: время и прямоугольник в координатах горизонтальной записи (если клип из неё вырезан)."""
    t0, t1, r = p["f0"] / FPS, (p["f0"] + NF[2]) / FPS, _os_rect(p)
    if not p.get("land") and p["f"] in VMAP:
        m = VMAP[p["f"]]
        k = m["w"] / W
        x, y, w, h = r
        return _os_key(p), t0 + m["dt"], t1 + m["dt"], (m["x"] + x * k, y * k, w * k, h * k)
    return _os_key(p), t0, t1, r


def reg_job(j: dict) -> None:
    for key, dur in (("s3", K.DUR[0]), ("s2", K.DUR[1])):
        p = j[key]
        _reg(p["f"], p["t"], p["t"] + dur, B._crop_band(p["f"], p))
    _reg(*_os_reg(j["s1"]))


def old_plan() -> int:
    """Первая партия: те же пулы и то же зерно → те же окна; на случай замен — ещё 2 запасных варианта на ролик."""
    rng = random.Random(61116)
    slots = [(tag, n) for tag in ("tt", "yt") for n in range(1, 201)]
    jobs = [B.make_job(rng, n, tag, k) for k, (tag, n) in enumerate(slots)]
    cnt = 0
    for j in jobs:
        reg_job(j)
        r2 = random.Random(j["seed"])
        for _ in range(2):
            reg_job(B.make_job(r2, j["n"], j["tag"], 0))
        cnt += 3
    return cnt


# ───────────────────────── план ролика ─────────────────────────
def _pick(rng: random.Random, gen, key_of, span_of, rect_of, out, tries: int = 400) -> dict:
    best, bc = None, 10 ** 9
    for _ in range(tries):
        p = gen()
        c = _conflicts(key_of(p), *span_of(p), rect_of(p), out)
        if c < bc:
            best, bc = p, c
        if c == 0:
            break
    return best


def make(rng: random.Random, key) -> dict:
    tag, n, k = key

    def win(pool, dur):
        def gen():
            for _ in range(200):
                f, a, b = rng.choice([p for p in pool if p[2] - p[1] >= dur + 0.4])
                t = round(rng.uniform(a, b - dur - 0.1), 2)
                if not any(t - 0.15 <= x <= t + dur + 0.15 for x in B.STALL.get(f, ())):
                    break
            return dict(f=f, t=t, z=round(rng.uniform(1.0, 1.4), 3),
                        ox=round(rng.uniform(0.15, 0.85), 3), oy=round(rng.uniform(0.15, 0.85), 3))
        return _pick(rng, gen, lambda p: p["f"], lambda p: (p["t"], p["t"] + dur),
                     lambda p: B._crop_band(p["f"], p), (W, K.BAND_H))

    def os_gen():
        if rng.random() < P_LAND and LAND_OK:
            f = rng.choice(sorted(LAND_OK))
            return dict(land=True, f=f, f0=rng.choice(LAND_OK[f]), z=round(rng.uniform(1.08, 1.3), 3),
                        ox=round(rng.uniform(0.36, 0.64), 3), oy=round(rng.uniform(0.55, 1.0), 3))
        f = rng.choice(sorted(B.OS_OK))
        return dict(land=False, f=f, f0=rng.choice(B.OS_OK[f]), z=round(rng.uniform(1.38, 1.55), 3),
                    ox=round(rng.uniform(0.2, 0.8), 3))
    with REG_LOCK:
        j = dict(n=n, tag=tag, s3=win(B.STUMBLE, K.DUR[0]), s2=win(B.AMONG, K.DUR[1]),
                 s1=_pick(rng, os_gen, lambda p: _os_reg(p)[0], lambda p: _os_reg(p)[1:3], lambda p: _os_reg(p)[3], (W, H)),
                 snd=B.SOUNDS[k % len(B.SOUNDS)], seed=rng.randrange(10 ** 9))
        reg_job(j)                                        # занимаем сразу (кандидаты идут параллельно)
    return j


# ───────────────────────── сборка (как первая партия; №1 — ещё и горизонтальные записи) ─────────────────────────
def _rate(name: str) -> str:
    return f"setpts=N/30/TB,fps={FPS}" if "amongus" in name else f"fps={FPS}"


def _os_src(p: dict) -> tuple[Path, int, int]:
    return (LAND_DIR / f"{p['f']}.mp4", LW, LH) if p.get("land") else (D / "os_src" / f"{p['f']}.mp4", W, H)


def render(j: dict, dest: Path) -> None:
    from core.gpu_slots import gpu_slot
    ins, fc = [], []
    for i, key in enumerate(("s3", "s2")):
        p = j[key]
        src = D / "games" / f"{p['f']}.mp4"
        ins += B._cuvid(src, B._crop_band(p["f"], p), (W, K.BAND_H), *G.probe(src)[1:], p["t"])
        fc.append(f"[{i}:v]{_rate(p['f'])},trim=end_frame={NF[i]},setpts=PTS-STARTPTS,setsar=1,split[fg{i}][s{i}];"
                  f"[s{i}]scale=192:108,crop=61:108,boxblur=6:2,scale={W}:{H},eq=brightness=-0.12,setsar=1[bg{i}];"
                  f"[bg{i}][fg{i}]overlay=0:{K.BAND_Y}[c{i}]")
    p = j["s1"]
    src, sw, sh = _os_src(p)
    ins += B._cuvid(src, _os_rect(p), (W, H), sw, sh, (p["f0"] - 0.5) / FPS)
    fc.append(f"[2:v]fps={FPS},trim=end_frame={NF[2]},setpts=PTS-STARTPTS,setsar=1[c2]")
    for i in range(3):
        ins += ["-i", str(ASSET / f"layerc{i}.png")]
    ins += ["-i", str(ASSET / "banner_small.mov"), "-i", str(ASSET / f"snd_{j['snd']}.wav")]
    for i in range(3):
        lx, ly = B.LAYER_XY[i]
        fc.append(f"[{3 + i}:v]loop=loop={NF[i] - 1}:size=1:start=0,setpts=N/{FPS}/TB,format=yuva420p[l{i}];"
                  f"[c{i}][l{i}]overlay={lx}:{ly}:format=yuv420[d{i}]")
    fc.append(f"[6:v]fps={FPS},setpts=PTS-STARTPTS,format=yuva420p[bn];"
              f"[d2][bn]overlay=(W-w)/2:430:eof_action=repeat:format=yuv420[e2];"
              f"[d0][d1][e2]concat=n=3:v=1:a=0,format=yuv420p[v]")
    tmp = Path(tempfile.mkdtemp(prefix="kos2u_"))
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


# ───────────────────────── проверки: одна распаковка готового ролика ─────────────────────────
def decode_checks(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    (a0, a1), (b0, b1) = CHK_BAND, CHK_OS
    with tempfile.TemporaryDirectory() as td:
        o = [Path(td) / f"{k}.raw" for k in ("g1", "g2", "h", "r")]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-threads", "4", "-i", str(path), "-filter_complex",
                        f"[0:v]split=4[a][b][c][d];"
                        f"[a]crop={W}:{a1 - a0}:0:{a0},scale={CS_BAND[0]}:{CS_BAND[1]}:flags=area,format=gray[g1];"
                        f"[b]crop={W}:{b1 - b0}:0:{b0},scale={CS_OS[0]}:{CS_OS[1]}:flags=area,format=gray[g2];"
                        f"[c]scale=17:16:flags=area,format=gray[h];[d]scale=54:96,format=rgb24[r]",
                        "-map", "[g1]", "-f", "rawvideo", str(o[0]), "-map", "[g2]", "-f", "rawvideo", str(o[1]),
                        "-map", "[h]", "-f", "rawvideo", str(o[2]), "-map", "[r]", "-f", "rawvideo", str(o[3])],
                       capture_output=True)
        g1 = np.fromfile(o[0], np.uint8).reshape(-1, CS_BAND[1], CS_BAND[0]).astype(np.float32)
        g2 = np.fromfile(o[1], np.uint8).reshape(-1, CS_OS[1], CS_OS[0]).astype(np.float32)
        hh = np.fromfile(o[2], np.uint8).reshape(-1, 16, 17).astype(np.int16)
        rr = np.fromfile(o[3], np.uint8).reshape(-1, 96, 54, 3)
    return g1, g2, hh, rr


def _src_read(src: Path, rect: tuple, sub: tuple, out_hw: tuple, size: tuple, ss: float, rate: str, n: int) -> np.ndarray:
    """Исходник тем же распаковщиком, что в сборке: окно rect, из него — часть sub=(y0, y1) готового кадра (out_hw)."""
    from core.gpu_slots import gpu_slot
    x, y, w, h = rect
    sy0, sy1 = sub
    cr = (x, y + sy0 * h / out_hw[1], w, (sy1 - sy0) * h / out_hw[1])
    _, sw, sh = G.probe(src)
    with gpu_slot():
        raw = subprocess.run(["ffmpeg", "-v", "error", *B._cuvid(src, tuple(G._even(v) for v in cr), size, sw, sh, ss),
                              "-vf", f"{rate},format=gray", "-frames:v", str(n + 4), "-f", "rawvideo", "-"],
                             capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, size[1], size[0]).astype(np.float32)


def frame_check(j: dict, g1: np.ndarray, g2: np.ndarray, margin: float = 1.5, junk: float = 22.0) -> list:
    """Каждый кадр готового ролика = кадр исходника по плану (не соседний): №3/№2 — полоса, №1 — низ кадра."""
    if len(g1) != TOT or len(g2) != TOT:
        return [("кадров", len(g1), TOT)]
    flags, off = [], 0
    parts = []
    for i, key in enumerate(("s3", "s2")):
        p = j[key]
        src = D / "games" / f"{p['f']}.mp4"
        y0 = CHK_BAND[0] - K.BAND_Y
        y1 = CHK_BAND[1] - K.BAND_Y
        parts.append((g1, _src_read(src, B._crop_band(p["f"], p), (y0, y1), (W, K.BAND_H), CS_BAND, p["t"],
                                    _rate(p["f"]), NF[i]), NF[i]))
    p = j["s1"]
    src, _, _ = _os_src(p)
    parts.append((g2, _src_read(src, _os_rect(p), CHK_OS, (W, H), CS_OS, (p["f0"] - 0.5) / FPS, f"fps={FPS}", NF[2]),
                  NF[2]))
    for out, s, n in parts:
        if len(s) < n:
            flags.append(("исходник короче", off, len(s)))
            off += n
            continue
        ds = [{dk: float(np.abs(out[off + k] - s[k + dk]).mean()) for dk in range(-3, 4) if 0 <= k + dk < len(s)}
              for k in range(n)]
        g = min(range(-2, 3), key=lambda dk: sum(d.get(dk, 1e3) for d in ds[3:n - 3]))
        for k, d in enumerate(ds):
            if g not in d:
                continue
            best = min(d, key=d.get)
            if d[best] > junk:
                flags.append((off + k, "мусор", round(d[best], 1)))
            elif best != g and d[g] - d[best] > margin:
                flags.append((off + k, best - g, round(d[g] - d[best], 2)))
        off += n
    return flags


def green_arr(rr: np.ndarray) -> list:
    fr = rr.astype(np.int16)
    g = (fr[..., 1] > 100) & (fr[..., 1] < 175) & (fr[..., 0] < 25) & (fr[..., 2] < 25)
    return [f"зелёное {i}" for i in np.nonzero(g.mean((1, 2)) > 0.03)[0][:5]]


def build(j: dict, tmp: Path, keep: Path) -> tuple[bool, str, np.ndarray | None]:
    tmp.with_suffix(".json").write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    render(j, tmp)
    g1, g2, hh, rr = decode_checks(tmp)
    bad = G.bad_frames_arr(rr) + green_arr(rr)
    if bad:
        return False, f"брак {bad[:5]}", None
    fl = frame_check(j, g1, g2)
    if fl:
        return False, f"сверка {len(fl)}: {fl[:4]}", None
    if OLD:
        parts = [OLD[0].near(CB.hash_of(hh[a:b]), both=False) for a, b in ((0, NF[0]), (NF[0], NF[0] + NF[1]), (NF[0] + NF[1], TOT))]
        if sum(parts) > 2:
            return False, f"похож на первую партию: №3 {parts[0]}, №2 {parts[1]}, №1 {parts[2]} ({j['s1']['f']})", None
    return True, "", CB.hash_of(hh)


# ───────────────────────── партия ─────────────────────────
OLD: list = []


def old_bank() -> CB.Bank:
    d = np.load(WORK / "old400.npz", allow_pickle=True)["d"].item()
    bank = CB.Bank()
    rows = []
    for arr, _ in d.values():
        a = np.asarray(arr, np.uint8)                         # кадры × (прямой, зеркальный) × 256
        rows.append(np.concatenate([a[:, 0], a[:, 1]]).astype(np.float32) * 2 - 1)
    bank.add(np.concatenate(rows))
    return bank


def setup() -> None:
    t0 = time.time()
    B.STUMBLE[:] = B.stumble_windows()
    B.AMONG[:] = B.among_windows()
    B.assets()
    B.os_clean()
    B.STALL[B.STUMBLE_SRC] = B.stall_times(B.STUMBLE_SRC, B.STUMBLE)
    B.STALL[B.AMONG_SRC] = B.stall_times(B.AMONG_SRC, B.AMONG)
    land_clean()
    vm = UQ / "vmap.json"
    if vm.exists():
        VMAP.update(json.loads(vm.read_text()))
    n = old_plan()
    print(f"подготовка {time.time() - t0:.0f} с: горизонтальные OneState {({f: len(v) for f, v in LAND_OK.items()})}, "
          f"окон первой партии в реестре {n}", flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tt", type=int, default=200)
    ap.add_argument("--yt", type=int, default=200)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--seed", type=int, default=181118)
    ap.add_argument("--test", type=int, default=0, help="N роликов в output/_work/korea2/uniq2/test")
    a = ap.parse_args()
    setup()
    if a.test:
        out = {"tt": UQ / "test", "yt": UQ / "test"}
        cnt = (("tt", (a.test + 1) // 2), ("yt", a.test // 2))
        work = UQ / "work_test"
    else:
        out = {"tt": ROOT / "output" / f"{NAME}_TT_{a.tt}", "yt": ROOT / "output" / f"{NAME}_YT_{a.yt}"}
        cnt = (("tt", a.tt), ("yt", a.yt))
        work = UQ / "work"
    keys = [(tag, n) for tag, c in cnt for n in range(1, c + 1)]
    slots = [((tag, n, k), out[tag] / f"{NAME}_{tag}_{n:03d}_{ID}.mp4") for k, (tag, n) in enumerate(keys)]
    for key, dest in slots:                                # уже готовые — в реестр по их плану
        mj = work / "meta" / f"{dest.name}.json"
        if dest.exists() and mj.exists():
            reg_job(json.loads(mj.read_text(encoding="utf-8")))
    old = old_bank()
    OLD.append(old)
    print(f"банк первой партии: {len(old.t)} кадров", flush=True)
    CB.run(slots, make, build, jobs=a.jobs, max_new=2, old=old, max_old=2, seed=a.seed, work=work,
           label=f"Korean OneState 2 партия 2{' (тест)' if a.test else ''}",
           log=lambda s: print(s, flush=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
