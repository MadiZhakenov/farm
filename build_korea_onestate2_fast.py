#!/usr/bin/env python3
"""
Korean OneState 2 — партия 2 (18.11, ID 1), БЫСТРЫЙ сборщик по рецепту build_inspoy_moveon_v2 (юзер через MAIN:
«СКАЖИ ЕМУ КАК ДЕЛАТЬ БЫСТРО И ПУСТЬ ДЕЛАЕТ»). 200 TT + 200 YT, ≤1 % между собой и с первой партией (400).
Вид — как первая партия (build_korea_onestate2_batch): заголовок, №3 Stumble 3 с → №2 Among Us 3 с → №1 OneState 5 с
+ промо-баннер, 4 звука по очереди. Добавлено «поле света» (волны + клетки сетки отпечатка) у каждого ролика.

  1. --prep (один раз): заготовки исходников 30 к/с с опорным кадром каждые 10 (-g 10) + серые 1/6 для прогноза.
  2. План ролика — на видеокарте: кадры склеиваются в torch (обрезка roi_align, размытый фон, полоса, надписи, баннер,
     поле), отпечатки 17×16 каждого кадра → против банка (первая партия + принятые, прямые и зеркальные, в обе
     стороны); меняются только совпавшие куски, до 80 кругов.
  3. Сборка — только принятый вариант (ffmpeg: куски через cuvid crop/resize, слои сырыми кадрами, NVENC).
  4. Проверка — одна распаковка видеодекодером: брак, покадровая сверка с эталоном из шага 2, отпечатки → банк.

  python build_korea_onestate2_fast.py --prep
  python build_korea_onestate2_fast.py --capacity
  python build_korea_onestate2_fast.py --test 6
  python build_korea_onestate2_fast.py --tt 200 --yt 200
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
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_korea_onestate2_batch as B  # noqa: E402
from core import gpu_ffmpeg as G  # noqa: E402

K = B.K
W, H, FPS = B.W, B.H, B.FPS
D, WORK, ASSET = B.D, B.WORK, B.ASSET
NF, TOT = B.NF, B.TOT                                   # 90, 90, 150 → 330
NAME, ID = "korean_onestate_2_b2", 1
FAST = WORK / "fast"
PX = FAST / "px"
LAND_DIR = ROOT / "downloads" / "onestate3" / "src"
LAND = ["Army_Protection_of_the_base", "Cars", "Crystals", "Drone_drop_1", "Mechanic_job", "Medics_job_1", "Mines_job",
        "Polic_job", "Police_job_1", "Police_job_fight_with_Gang", "Taxi_job_1"]
PX_ENC = ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "19", "-g", "10", "-bf", "0"]
Q = 6                                                     # серые заготовки для прогноза — 1/6


# ───────────────────────── 1. заготовки ─────────────────────────
def _dec(src: Path) -> str:
    return {"av1": "av1_cuvid", "hevc": "hevc_cuvid"}.get(G.probe(src)[0], "h264_cuvid")


def _px_one(job: dict) -> dict:
    """Одна заготовка: кадры 30 к/с (обрезка до картинки) → px/<id>.mp4 (-g 10) + серые 1/6 → px/<id>.npy."""
    out, npy = PX / f"{job['id']}.mp4", PX / f"{job['id']}.npy"
    if out.exists() and npy.exists():
        a = np.load(npy, mmap_mode="r")
        return dict(job, n=len(a), small=list(a.shape[1:]))
    src = job["src"]
    _, sw, sh = G.probe(src)
    x, y, w, h = job["crop"]
    inp = ["-c:v", _dec(src)]
    if (x, y, w, h) != (0, 0, sw, sh):
        inp += ["-crop", f"{y}x{sh - y - h}x{x}x{sw - x - w}"]
    if job.get("ss") is not None:
        inp += ["-ss", f"{job['ss']:.3f}", "-t", f"{job['t']:.3f}"]
    sw_, sh_ = G._even(w / Q), G._even(h / Q)
    raw = PX / f"{job['id']}.raw"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *inp, "-i", str(src), "-filter_complex",
                        f"[0:v]{job['rate']},split[p][s];[s]scale={sw_}:{sh_}:flags=area,format=gray[g]",
                        "-map", "[p]", "-an", *PX_ENC, str(out), "-map", "[g]", "-f", "rawvideo", str(raw)],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{job['id']}: {r.stderr[-600:]}")
    a = np.fromfile(raw, np.uint8).reshape(-1, sh_, sw_)
    np.save(npy, a)
    raw.unlink()
    return dict(job, n=len(a), small=[sh_, sw_])


def prep() -> dict:
    """Все заготовки (кэш FAST/sources.json): окна Stumble/Among Us первой партии, клипы OneState (верт. и гориз.)."""
    PX.mkdir(parents=True, exist_ok=True)
    B.STUMBLE[:] = B.stumble_windows()
    B.AMONG[:] = B.among_windows()
    jobs = []
    for i, (f, a, b) in enumerate(B.STUMBLE):
        jobs.append(dict(id=f"st{i:02d}", kind="st", f=f, a=a, src=D / "games" / f"{f}.mp4", ss=a, t=b - a,
                         crop=B.CONTENT[f], rate=f"fps={FPS}"))
    for i, (f, a, b) in enumerate(B.AMONG):
        jobs.append(dict(id=f"am{i:02d}", kind="am", f=f, a=a, src=D / "games" / f"{f}.mp4", ss=a, t=b - a,
                         crop=B.CONTENT[f], rate=f"setpts=N/30/TB,fps={FPS}"))
    for f in K.OS_ALL:
        jobs.append(dict(id=f"ov_{f}", kind="ov", f=f, a=0.0, src=D / "os_src" / f"{f}.mp4", ss=None, t=None,
                         crop=(0, 0, W, H), rate=f"fps={FPS}"))
    for f in LAND:
        src = LAND_DIR / f"{f}.mp4"
        jobs.append(dict(id=f"ol_{f}", kind="ol", f=f, a=0.0, src=src, ss=None, t=None, crop=(0, 0, 2560, 1440),
                         rate=f"fps={FPS}"))
    t0 = time.time()
    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(_px_one, jobs))
    meta = {}
    for r in res:
        a = np.load(PX / f"{r['id']}.npy", mmap_mode="r").astype(np.int16)
        d = np.abs(np.diff(a, axis=0)).mean((1, 2))
        # повтор кадра посреди движения (сбой записи / «замирание» игры) — кусок через него не берём
        bad = [i + 1 for i in range(len(d)) if d[i] < 0.25 and ((i and d[i - 1] > 0.6) or (i + 1 < len(d) and d[i + 1] > 0.6))]
        meta[r["id"]] = dict(kind=r["kind"], f=r["f"], a=r["a"], n=r["n"], small=r["small"], crop=list(r["crop"]),
                             bad=bad, motion=[round(float(v), 2) for v in d])
    (FAST / "sources.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"заготовки: {len(meta)} за {time.time() - t0:.0f} с; кадров "
          f"{ {k: sum(m['n'] for m in meta.values() if m['kind'] == k) for k in ('st', 'am', 'ov', 'ol')} }", flush=True)
    return meta


# ───────────────────────── 2. прогноз на видеокарте ─────────────────────────
import torch  # noqa: E402
import torch.nn.functional as TF  # noqa: E402
from PIL import Image  # noqa: E402
from torchvision.ops import roi_align  # noqa: E402

GDEV = "cuda" if torch.cuda.is_available() else "cpu"
BDT = torch.half if GDEV == "cuda" else torch.float32
GPU_SEM = threading.BoundedSemaphore(3)                  # склеек на видеокарте одновременно (память)
BANK_LOCK = threading.Lock()
CW, CH = W // 4, H // 4                                  # склейка в 1/4: 270×480
BY4, BH4 = K.BAND_Y // 4, K.BAND_H // 4                  # полоса 179..331
THR_PRED, THR, ACC_MAX = 44, 40, 2
FIELD = (float(os.environ.get("KF_WAVE", "0.04")), float(os.environ.get("KF_CELL", "0.06")))
BAND_Z = (1.0, 1.4)
BAND_O = (0.15, 0.85)
P_LAND = 0.75
CHK8_BAND = (92, 162)                                    # сверка в 1/8: строки полосы (без надписей)
CHK8_OS = (125, 230)                                     # сверка в 1/8: низ кадра OneState (без баннера и надписей)
EQ_B = -34.0                                             # eq=brightness=-0.12 размытого фона в серой шкале 0–255


def wave_field(rng: random.Random) -> np.ndarray:
    """Как build_inspoy_moveon_v2 / build_skinive10: волны в 1/4 кадра."""
    x = np.linspace(0, 1, CW, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, CH, dtype=np.float32)[:, None]
    ph = (rng.uniform(0, 6.28) + y * rng.uniform(-6, 6)
          + np.sin(y * rng.uniform(2, 5) + rng.uniform(0, 6.28)) * rng.uniform(0.5, 1.5))
    return (0.6 * np.sin(2 * math.pi * rng.uniform(1.2, 2.6) * x + ph)
            + 0.4 * np.sin(2 * math.pi * rng.uniform(2.5, 4.5) * x + ph * 1.7 + rng.uniform(0, 6.28))).astype(np.float32)


def cell_field(rng: random.Random) -> np.ndarray:
    r = np.random.default_rng(rng.randrange(2 ** 32)).random((16, 17), dtype=np.float32)
    im = Image.fromarray(r, "F").resize((CW, CH), Image.Resampling.BICUBIC)
    return np.clip(np.asarray(im, np.float32), 0, 1)


def field_v(seed: int) -> torch.Tensor:
    rng = random.Random(seed)
    v = FIELD[0] * wave_field(rng) + FIELD[1] * (cell_field(rng) * 2 - 1)
    return torch.from_numpy(v).to(GDEV)


def _rgba_down(path_or_arr, box=None) -> tuple[torch.Tensor, torch.Tensor]:
    """RGBA полного кадра → (1−α, α·яркость) в 1/4 (площадью)."""
    a = np.asarray(path_or_arr, np.float32) if not isinstance(path_or_arr, (str, Path)) else \
        np.asarray(Image.open(path_or_arr).convert("RGBA"), np.float32)
    t = torch.from_numpy(a).to(GDEV)
    al = t[..., 3] / 255
    lu = (t[..., 0] * 0.299 + t[..., 1] * 0.587 + t[..., 2] * 0.114) * al
    st = torch.stack([1 - al, lu])[None]
    st = TF.avg_pool2d(st, 4)[0]
    return st[0], st[1]


class Assets:
    def __init__(self, meta: dict):
        self.meta = meta
        self.fr = {}                                      # заготовка → серые кадры 1/6 на видеокарте (uint8)
        for sid, m in meta.items():
            self.fr[sid] = torch.from_numpy(np.load(PX / f"{sid}.npy")).to(GDEV)
        self.lay = [_rgba_down(ASSET / f"layer{i}.png") for i in range(3)]
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(ASSET / "banner_small.mov"), "-vf", f"fps={FPS}",
                              "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True).stdout
        bw, bh = 760, 212
        bn = np.frombuffer(raw, np.uint8).reshape(-1, bh, bw, 4)
        x0, y0 = (W - bw) // 2, 430
        self.bn = []                                      # кадр баннера → (строки 1/4, 1−α, α·яркость) на полосе 1/4
        r0, r1 = y0 // 4, (y0 + bh + 3) // 4
        for i in range(NF[2]):
            f = bn[min(i, len(bn) - 1)]
            can = np.zeros((r1 * 4 - r0 * 4, W, 4), np.float32)
            can[y0 - r0 * 4:y0 - r0 * 4 + bh, x0:x0 + bw] = f
            a, c = _rgba_down(can)
            self.bn.append((a, c))
        self.bn_rows = (r0, r1)
        self.ids = {k: [s for s, m in meta.items() if m["kind"] == k] for k in ("st", "am", "ov", "ol")}
        self.ok = {}                                      # заготовка → начала кусков без сбоев (и не стоячие)
        for sid, m in meta.items():
            n = NF[2] if m["kind"] in ("ov", "ol") else NF[0]
            bad = set(m["bad"])
            mo = np.asarray(m["motion"])
            self.ok[sid] = [k for k in range(3, m["n"] - n - 3)
                            if not any(b in bad for b in range(k - 1, k + n + 2)) and mo[k:k + n].mean() > 0.3]
        for k in ("st", "am", "ov", "ol"):
            self.ids[k] = [s for s in self.ids[k] if len(self.ok[s]) > 0]


# ── куски: выбор и прямоугольник в координатах заготовки ──
def roll_band(rng: random.Random, A: Assets, kind: str, sid: str | None = None) -> dict:
    ids = A.ids[kind]
    if sid is None:
        sid = rng.choices(ids, weights=[len(A.ok[s]) for s in ids])[0]
    return dict(sid=sid, kf=rng.choice(A.ok[sid]), z=round(rng.uniform(*BAND_Z), 3),
                ox=round(rng.uniform(*BAND_O), 3), oy=round(rng.uniform(*BAND_O), 3))


def roll_os(rng: random.Random, A: Assets, sid: str | None = None) -> dict:
    if sid is None:
        kind = "ol" if rng.random() < P_LAND else "ov"
        sid = rng.choices(A.ids[kind], weights=[len(A.ok[s]) for s in A.ids[kind]])[0]
    if A.meta[sid]["kind"] == "ol":
        return dict(sid=sid, kf=rng.choice(A.ok[sid]), z=round(rng.uniform(1.08, 1.3), 3),
                    ox=round(rng.uniform(0.36, 0.64), 3), oy=round(rng.uniform(0.55, 1.0), 3))
    return dict(sid=sid, kf=rng.choice(A.ok[sid]), z=round(rng.uniform(1.38, 1.55), 3), ox=round(rng.uniform(0.2, 0.8), 3))


def band_rect(A: Assets, p: dict) -> tuple:
    """Окно 16:9 (как полоса 1080×608) в заготовке (она уже обрезана до картинки), зум z, положение ox/oy."""
    cw, ch = A.meta[p["sid"]]["crop"][2:]
    asp = W / K.BAND_H
    bw, bh = (ch * asp, ch) if cw / ch > asp else (cw, cw / asp)
    w, h = bw / p["z"], bh / p["z"]
    return G._even((cw - w) * p["ox"]), G._even((ch - h) * p["oy"]), G._even(w), G._even(h)


def os_rect(A: Assets, p: dict) -> tuple:
    if A.meta[p["sid"]]["kind"] == "ol":
        h = G._even(1440 / p["z"])
        w = G._even(h * 9 / 16)
        return G._even((2560 - w) * p["ox"]), G._even((1440 - h) * p["oy"]), w, h
    w, h = G._even(W / p["z"]), G._even(H / p["z"])
    return G._even((W - w) * p["ox"]), H - h, w, h


def _crop_frames(A: Assets, p: dict, rect: tuple, n: int, size: tuple) -> torch.Tensor:
    """Кадры куска из серых заготовок → (n, h, w) float: обрезка + масштаб roi_align (≈ площадью)."""
    m = A.meta[p["sid"]]
    arr = A.fr[p["sid"]][p["kf"]:p["kf"] + n].float()[:, None]
    sh, sw = m["small"]
    fx, fy = sw / m["crop"][2], sh / m["crop"][3]
    x, y, w, h = rect
    b = torch.tensor([x * fx, y * fy, (x + w) * fx, (y + h) * fy], dtype=torch.float32, device=GDEV)
    bx = torch.cat([torch.arange(n, device=GDEV, dtype=torch.float32)[:, None], b[None].expand(n, 4)], 1)
    return roi_align(arr, bx, size, spatial_scale=1.0, sampling_ratio=2, aligned=True)[:, 0]


def _blur13(x: torch.Tensor) -> torch.Tensor:
    x = TF.pad(x[:, None], (6, 6, 6, 6), mode="replicate")
    return TF.avg_pool2d(x, 13, stride=1)[:, 0]


def seg_frames(A: Assets, pl: dict, key: str) -> torch.Tensor:
    """Склейка куска в 1/4 (серый 0–255): полоса на размытом фоне (№3/№2) или OneState на весь кадр (№1) + надписи,
    баннер, поле света — как в ffmpeg."""
    p = pl[key]
    i = ("s3", "s2", "s1").index(key)
    n = NF[i]
    if key in ("s3", "s2"):
        r = band_rect(A, p)
        fg = _crop_frames(A, p, r, n, (BH4, CW))
        sm = _crop_frames(A, p, r, n, (108, 192))[:, :, 65:126]
        bg = _blur13(_blur13(sm))
        bg = TF.interpolate(bg[:, None], size=(CH, CW), mode="bilinear", align_corners=False)[:, 0]
        x = (bg + EQ_B).clamp(0, 255)
        x[:, BY4:BY4 + BH4] = fg
    else:
        x = _crop_frames(A, p, os_rect(A, p), n, (CH, CW))
    a, c = A.lay[i]
    x = x * a + c
    if key == "s1":
        r0, r1 = A.bn_rows
        ab = torch.stack([A.bn[j][0] for j in range(n)])
        cb = torch.stack([A.bn[j][1] for j in range(n)])
        x[:, r0:r1] = x[:, r0:r1] * ab + cb
    v = pl["_v"]
    fa = v.abs().clamp(0, 1)
    x = x * (1 - fa) + fa * (v < 0).float() * 255
    return x


def seg_pred(A: Assets, pl: dict, key: str) -> None:
    x = seg_frames(A, pl, key)
    pl["_c"][key] = TF.adaptive_avg_pool2d(x[:, None], (16, 17))[:, 0]
    pl["_r"][key] = TF.avg_pool2d(x[:, None], 2)[:, 0]         # эталон сверки 1/8
    del x


def bits_t(cells: torch.Tensor) -> torch.Tensor:
    h = (cells[:, :, 1:] > cells[:, :, :-1]).reshape(len(cells), -1)
    fl = cells.flip(2)
    m = (fl[:, :, 1:] > fl[:, :, :-1]).reshape(len(cells), -1)
    return torch.cat([h, m]).to(BDT) * 2 - 1


def near_mask_t(hb: torch.Tensor, bank: torch.Tensor, thr: int) -> tuple[torch.Tensor, int]:
    """Кадры кандидата (прямые ИЛИ зеркальные) ближе thr к банку + сколько кадров банка рядом с кандидатом."""
    n = len(hb) // 2
    hit = torch.zeros(n, dtype=torch.bool, device=GDEV)
    rev = 0
    with torch.no_grad():
        for i in range(0, len(bank), 32768):
            m = (256 - hb @ bank[i:i + 32768].T) / 2 <= thr
            hit |= m[:n].any(1) | m[n:].any(1)
            rev += int(m.any(0).sum())
    return hit, rev


class Bank:
    def __init__(self):
        self.t = torch.zeros((0, 256), dtype=BDT, device=GDEV)

    def add(self, h: torch.Tensor | np.ndarray) -> None:
        h = torch.as_tensor(np.asarray(h, np.float32) if isinstance(h, np.ndarray) else h, device=GDEV).to(BDT)
        self.t = torch.cat([self.t, h])


def load_old(bank: Bank) -> int:
    d = np.load(WORK / "old400.npz", allow_pickle=True)["d"].item()
    hm = np.concatenate([np.asarray(v[0], np.uint8) for v in d.values()]).astype(np.float32)   # (кадры, 2, 256)
    bank.add(np.concatenate([hm[:, 0], hm[:, 1]]) * 2 - 1)
    return len(d)


SEGS = (("s3", 0, NF[0]), ("s2", NF[0], NF[0] + NF[1]), ("s1", NF[0] + NF[1], TOT))


def plan(A: Assets, seed: int, snd: str) -> dict:
    rng = random.Random(seed)
    return dict(seed=seed, fseed=rng.randrange(10 ** 9), snd=snd,
                s3=roll_band(rng, A, "st"), s2=roll_band(rng, A, "am"), s1=roll_os(rng, A))


def converge(A: Assets, pl: dict, bank: Bank, stat: dict, rounds: int = 80) -> bool:
    """Прогноз → банк → меняем только совпавшие куски (3–4 неудачи подряд — другой исходник; часто все — новое поле)."""
    rng = random.Random(pl["seed"] * 7 + 1)
    pl["_v"] = field_v(pl["fseed"])
    pl["_c"], pl["_r"] = {}, {}
    for k, _, _ in SEGS:
        seg_pred(A, pl, k)
    fails = {k: 0 for k, _, _ in SEGS}
    allbad = 0
    for _ in range(rounds):
        cells = torch.cat([pl["_c"][k] for k, _, _ in SEGS])
        with BANK_LOCK:
            bank_t = bank.t
        hit, rev = near_mask_t(bits_t(cells), bank_t, THR_PRED)
        nh = int(hit.sum())
        if max(nh, rev) <= ACC_MAX:
            return True
        bad = [k for k, a, b in SEGS if bool(hit[a:b].any())] or [k for k, _, _ in SEGS]
        allbad = allbad + 1 if len(bad) == 3 else 0
        if allbad >= 3:                                   # всё совпадает разом — другое поле света
            pl["fseed"] = rng.randrange(10 ** 9)
            pl["_v"] = field_v(pl["fseed"])
            allbad = 0
            bad = [k for k, _, _ in SEGS]
            stat["field"] = stat.get("field", 0) + 1
        for k in bad:
            fails[k] += 1
            stat[k] = stat.get(k, 0) + 1
            sid = pl[k]["sid"] if fails[k] < 4 else None  # 4 неудачи подряд — другой исходник
            if fails[k] >= 4:
                fails[k] = 0
            pl[k] = roll_band(rng, A, "st" if k == "s3" else "am", sid) if k != "s1" else roll_os(rng, A, sid)
            seg_pred(A, pl, k)
        stat["rounds"] = stat.get("rounds", 0) + 1
    return False


def pred_bits(pl: dict) -> torch.Tensor:
    return bits_t(torch.cat([pl["_c"][k] for k, _, _ in SEGS]))


# ───────────────────────── 3. сборка ─────────────────────────
def write_field(pl: dict, keep: Path) -> None:
    v = TF.interpolate(pl["_v"][None, None], size=(H, W), mode="bilinear", align_corners=False)[0, 0]
    rgba = torch.zeros((H, W, 4), dtype=torch.uint8, device=GDEV)
    rgba[..., :3] = ((v < 0).to(torch.uint8) * 255)[..., None]
    rgba[..., 3] = (v.abs().clamp(0, 1) * 255).round().to(torch.uint8)
    rgba.cpu().numpy().tofile(keep / "field.rgba")


def render(A: Assets, pl: dict, keep: Path, dest: Path) -> None:
    from core.gpu_slots import gpu_slot
    ins, fc = [], []
    for i, key in enumerate(("s3", "s2")):
        p = pl[key]
        ins += G.gpu_input(PX / f"{p['sid']}.mp4", crop=band_rect(A, p), resize=(W, K.BAND_H),
                           ss=max(0.0, (p["kf"] - 0.5) / FPS))
        fc.append(f"[{i}:v]fps={FPS},trim=end_frame={NF[i]},setpts=PTS-STARTPTS,setsar=1,split[fg{i}][s{i}];"
                  f"[s{i}]scale=192:108,crop=61:108,boxblur=6:2,scale={W}:{H},eq=brightness=-0.12,setsar=1[bg{i}];"
                  f"[bg{i}][fg{i}]overlay=0:{K.BAND_Y}[c{i}]")
    p = pl["s1"]
    ins += G.gpu_input(PX / f"{p['sid']}.mp4", crop=os_rect(A, p), resize=(W, H), ss=max(0.0, (p["kf"] - 0.5) / FPS))
    fc.append(f"[2:v]fps={FPS},trim=end_frame={NF[2]},setpts=PTS-STARTPTS,setsar=1[c2]")
    for i in range(3):
        ins += ["-i", str(ASSET / f"layerc{i}.png")]
    ins += ["-i", str(ASSET / "banner_small.mov")]
    ins += ["-f", "rawvideo", "-video_size", f"{W}x{H}", "-pixel_format", "rgba", "-framerate", str(FPS),
            "-i", str(keep / "field.rgba")]
    ins += ["-i", str(ASSET / f"snd_{pl['snd']}.wav")]
    for i in range(3):
        lx, ly = B.LAYER_XY[i]
        fc.append(f"[{3 + i}:v]loop=loop={NF[i] - 1}:size=1:start=0,setpts=N/{FPS}/TB,format=yuva420p[l{i}];"
                  f"[c{i}][l{i}]overlay={lx}:{ly}:format=yuv420[d{i}]")
    fc.append(f"[6:v]fps={FPS},setpts=PTS-STARTPTS,format=yuva420p[bn];"
              f"[d2][bn]overlay=(W-w)/2:430:eof_action=repeat:format=yuv420[e2];"
              f"[d0][d1][e2]concat=n=3:v=1:a=0,format=yuv420p[vc];"
              f"[7:v]format=yuva420p,loop=loop={TOT - 1}:size=1:start=0,settb=1/{FPS},setpts=N[fl];"
              f"[vc][fl]overlay=0:0:format=yuv420:shortest=1,format=yuv420p[v]")
    (keep / "g.txt").write_text(";".join(fc), encoding="utf-8")
    part = dest.with_name(dest.stem + ".part.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-nostdin", *ins, "-filter_complex_script", str(keep / "g.txt"),
           "-map", "[v]", "-map", "8:a", "-frames:v", str(TOT), "-t", f"{TOT / FPS}", *G.NVENC,
           "-c:a", "aac", "-b:a", "192k", *G.CLEAN, str(part)]
    with gpu_slot():
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode:
        part.unlink(missing_ok=True)
        raise RuntimeError(r.stderr[-1200:])
    part.replace(dest)


# ───────────────────────── 4. проверка готового ─────────────────────────
def decode_checks(path: Path, keep: Path) -> tuple:
    g, r, h = keep / "g.raw", keep / "r.raw", keep / "h.raw"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-hwaccel", "cuda", "-i", str(path), "-filter_complex",
                    f"[0:v]split=3[a][b][c];[a]scale={W // 8}:{H // 8}:flags=area,format=gray[g];"
                    f"[b]scale=54:96,format=rgb24[r];[c]scale=17:16:flags=area,format=gray[h]",
                    "-map", "[g]", "-f", "rawvideo", str(g), "-map", "[r]", "-f", "rawvideo", str(r),
                    "-map", "[h]", "-f", "rawvideo", str(h)], capture_output=True)
    return (np.fromfile(g, np.uint8).reshape(-1, H // 8, W // 8).astype(np.float32),
            np.fromfile(r, np.uint8).reshape(-1, 96, 54, 3),
            np.fromfile(h, np.uint8).reshape(-1, 16, 17).astype(np.int16))


def frame_check(out: np.ndarray, ref: dict, margin: float = 1.0, junk: float = 30.0) -> tuple[list, list]:
    """Каждый кадр готового = кадр плана (ближайший из ±3 своего куска; общий сдвиг куска на кадр — безвреден,
    скачок от него — флаг). Сравниваем места без надписей: полосу №3/№2 и низ кадра №1."""
    if len(out) != TOT:
        return [("кадров", len(out), TOT)], []
    flags, offs = [], []
    for k, a, b in SEGS:
        r0, r1 = CHK8_OS if k == "s1" else CHK8_BAND
        o = out[a:b, r0:r1]
        s = ref[k][:, r0:r1]
        n = b - a
        ds = [{dk: float(np.abs(o[j] - s[j + dk]).mean()) for dk in range(-3, 4) if 0 <= j + dk < n} for j in range(n)]
        g = min((-1, 0, 1), key=lambda dk: sum(d.get(dk, 1e3) for d in ds[3:n - 3]))
        offs.append(g)
        for j, d in enumerate(ds):
            if g not in d:
                continue
            best = min(d, key=d.get)
            if d[best] > junk:
                flags.append((a + j, "мусор", round(d[best], 1)))
            elif best != g and d[g] - d[best] > margin:
                flags.append((a + j, best - g, round(d[g] - d[best], 2)))
    return flags, offs


def green_arr(rr: np.ndarray) -> list:
    fr = rr.astype(np.int16)
    gm = (fr[..., 1] > 100) & (fr[..., 1] < 175) & (fr[..., 0] < 25) & (fr[..., 2] < 25)
    return [f"зелёное {i}" for i in np.nonzero(gm.mean((1, 2)) > 0.03)[0][:5]]


def hash_of(H_: np.ndarray) -> np.ndarray:
    h = (H_[:, :, 1:] > H_[:, :, :-1]).reshape(len(H_), -1)
    m = (H_[:, :, ::-1][:, :, 1:] > H_[:, :, ::-1][:, :, :-1]).reshape(len(H_), -1)
    return np.concatenate([h, m]).astype(np.float32) * 2 - 1


# ───────────────────────── партия ─────────────────────────
PROG = ROOT / "output" / "_work" / "_qa_progress" / f"{os.getpid()}.json"


def prog(stage: str, done: int = 0, total: int | None = None) -> None:
    try:
        PROG.parent.mkdir(parents=True, exist_ok=True)
        PROG.write_text(json.dumps(dict(stage=stage, done=done, total=total), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


class Ctx:
    def __init__(self, A: Assets, bank: Bank, acc: Path):
        self.A, self.bank, self.acc = A, bank, acc
        self.lock = threading.Lock()
        self.stat: dict = {}
        self.done = 0


def build_one(ctx: Ctx, tag: str, n: int, k: int, dest: Path, base_seed: int) -> str:
    A = ctx.A
    keep = FAST / "jobs" / f"{tag}_{n:03d}"
    for att in range(12):
        shutil.rmtree(keep, ignore_errors=True)
        keep.mkdir(parents=True, exist_ok=True)
        st: dict = {}
        pl = plan(A, base_seed + ({"tt": 1, "yt": 2}[tag] * 1000 + n) * 100 + att, B.SOUNDS[k % len(B.SOUNDS)])
        with GPU_SEM, torch.no_grad():
            ok = converge(A, pl, ctx.bank, st)
            if ok:
                write_field(pl, keep)
                ref = {kk: pl["_r"][kk].cpu().numpy() for kk, _, _ in SEGS}
            for kk in ("_c", "_r", "_v"):
                pl.pop(kk, None)
            torch.cuda.empty_cache()
        with ctx.lock:
            for kk, v in st.items():
                ctx.stat[kk] = ctx.stat.get(kk, 0) + v
        if not ok:
            with ctx.lock:
                ctx.stat["no_conv"] = ctx.stat.get("no_conv", 0) + 1
            print(f"  {dest.name} попытка {att}: прогноз не сошёлся", flush=True)
            continue
        tmp = keep / "out.mp4"
        try:
            render(A, pl, keep, tmp)
        except Exception as e:                            # noqa: BLE001
            print(f"  {dest.name} попытка {att}: ffmpeg {str(e)[-300:]}", flush=True)
            continue
        G_, R_, H_ = decode_checks(tmp, keep)
        bad = G.bad_frames_arr(R_) + green_arr(R_)
        fr, offs = frame_check(G_, ref)
        if bad or fr:
            with ctx.lock:
                ctx.stat["bad" if bad else "fr"] = ctx.stat.get("bad" if bad else "fr", 0) + 1
            print(f"  {dest.name} попытка {att}: брак {bad[:4]} сверка {len(fr)} {fr[:4]} сдвиги {offs}", flush=True)
            continue
        hr = hash_of(H_)
        hb = torch.from_numpy(hr).to(GDEV).to(BDT)
        with BANK_LOCK:
            hit, rev = near_mask_t(hb, ctx.bank.t, THR)
            nn = max(int(hit.sum()), rev)
            if nn > ACC_MAX:
                ctx.stat["real"] = ctx.stat.get("real", 0) + 1
                print(f"  {dest.name} попытка {att}: готовый похож ({nn} кадров; "
                      f"{[int(hit[a:b].sum()) for _, a, b in SEGS]})", flush=True)
                continue
            ctx.bank.add(hb)
            ctx.acc.mkdir(parents=True, exist_ok=True)
            np.save(ctx.acc / f"{dest.name}.npy", np.packbits(hr > 0, axis=1))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp), str(dest))
        (keep / "plan.json").write_text(json.dumps({kk: v for kk, v in pl.items() if not kk.startswith("_")},
                                                   ensure_ascii=False), encoding="utf-8")
        for f in keep.iterdir():
            if f.name != "plan.json":
                f.unlink()
        with ctx.lock:
            ctx.done += 1
        return f"{dest.name} (попытка {att}, сдвиги {offs})"
    raise RuntimeError(f"{dest.name}: 12 попыток без приёмки")


def capacity(A: Assets, n: int) -> None:
    """Ёмкость без сборки: n роликов подряд по прогнозу (принятые идут в банк прогнозом) — сколько кругов и где."""
    global FIELD
    for wave, cell in ((0.0, 0.0), FIELD):
        FIELD = (wave, cell)
        bank = Bank()
        load_old(bank)
        t0, st, fails = time.time(), {}, 0
        for i in range(n):
            pl = plan(A, 900000 + i, "s1")
            with torch.no_grad():
                if converge(A, pl, bank, st):
                    bank.add(pred_bits(pl))
                else:
                    fails += 1
            for kk in ("_c", "_r", "_v"):
                pl.pop(kk, None)
        torch.cuda.empty_cache()
        print(f"поле {wave}/{cell}: {n} роликов за {time.time() - t0:.0f} с, не сошлось {fails}, "
              f"кругов {st.get('rounds', 0)} (№3 {st.get('s3', 0)}, №2 {st.get('s2', 0)}, №1 {st.get('s1', 0)}, "
              f"новых полей {st.get('field', 0)})", flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--prep", action="store_true")
    ap.add_argument("--capacity", type=int, default=0)
    ap.add_argument("--tt", type=int, default=0)
    ap.add_argument("--yt", type=int, default=0)
    ap.add_argument("--test", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    t0 = time.time()
    prog("подготовка: заготовки исходников")
    meta = prep()
    if a.prep:
        return 0
    B.assets()                                            # слои надписей, баннер, звуки (готовы с первой партии)
    A = Assets(meta)
    print(f"в видеокарте: {sum(t.numel() for t in A.fr.values()) / 1e6:.0f} МБ кадров; "
          f"кусков: { {k: sum(len(A.ok[s]) for s in v) for k, v in A.ids.items()} }; {time.time() - t0:.0f} с", flush=True)
    if a.capacity:
        capacity(A, a.capacity)
        return 0
    bank = Bank()
    n_old = load_old(bank)
    if a.test:
        out = {"tt": FAST / "test", "yt": FAST / "test"}
        cnt, acc = (("tt", (a.test + 1) // 2), ("yt", a.test // 2)), FAST / "acc_test"
        shutil.rmtree(acc, ignore_errors=True)
    else:
        out = {"tt": ROOT / "output" / f"{NAME}_TT_{a.tt}", "yt": ROOT / "output" / f"{NAME}_YT_{a.yt}"}
        cnt, acc = (("tt", a.tt), ("yt", a.yt)), FAST / "acc"
    slots = [(tag, n) for tag, c in cnt for n in range(1, c + 1)]
    todo = []
    for k, (tag, n) in enumerate(slots):
        dest = out[tag] / f"{NAME}_{tag}_{n:03d}_{ID}.mp4"
        if dest.exists() and (acc / f"{dest.name}.npy").exists():
            bank.add(np.unpackbits(np.load(acc / f"{dest.name}.npy"), axis=1)[:, :256].astype(np.float32) * 2 - 1)
        else:
            todo.append((tag, n, k, dest))
    print(f"банк: первая партия {n_old} роликов ({len(bank.t)} строк); собрать {len(todo)} из {len(slots)}", flush=True)
    ctx = Ctx(A, bank, acc)
    total, done0, tb = len(slots), len(slots) - len(todo), time.time()
    prog("сборка + проверка каждого кадра", done0, total)
    with ThreadPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(build_one, ctx, tag, n, k, dest, a.seed * 7919): dest for tag, n, k, dest in todo}
        for i, fu in enumerate(as_completed(futs), 1):
            try:
                fu.result()
            except Exception as e:                        # noqa: BLE001
                print(f"  СБОЙ {futs[fu].name}: {str(e)[-300:]}", flush=True)
            prog("сборка + проверка каждого кадра", done0 + ctx.done, total)
            if i % 10 == 0 or i == len(todo):
                el = time.time() - tb
                print(f"  ✓ {done0 + ctx.done}/{total} за {el:.0f} с ({ctx.done / el * 60:.1f}/мин); {ctx.stat}", flush=True)
    PROG.unlink(missing_ok=True)
    print(f"ГОТОВО: {done0 + ctx.done}/{total} за {time.time() - t0:.0f} с → {sorted({str(v) for v in out.values()})}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
