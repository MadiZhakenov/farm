"""June's Journey 4 (ID 1): слайдшоу-копия рефа @livingdeadd0lll «rare aesthetic: 2000s hidden objects games».

7 скриншотов June's Journey × 2 с (появление 0.5 с, держится 1 с, уход 0.5 с — в рефе в чёрный, у нас до 35 %
яркости: полностью чёрные кадры с одной и той же подписью совпали бы во всех роликах), картинка 4:3 на всю
ширину по центру 9:16, подпись из рефа дословно (Cormorant Garamond, мягкая тень), на последней секунде снизу
«June’s journey btw». Звук рефа (−14 LUFS), тон у каждого ролика свой.

Уникальность (как June's Journey 2/3, OneState 4): до сборки расчёт хэшей каждого слайда (полоса картинки
y 555–1365, dHash 16×16, с подписью и затемнениями) — кадрирование принимается, только если дальше PLAN_THR от
всех принятых; после сборки — хэши настоящего файла при 6 и 3 к/с, ролик в папку только при 0 общих кадров
(порог 40) со всеми принятыми и с June's Journey 2/3.

Кадры собирает torch на видеокарте → yuv420p по трубе → NVENC (обычные кадры, без распаковки на видеокарте).

    python build_jj4.py --plan-only        # расчёт плана
    python build_jj4.py --test             # 3 TT + 3 YT в output/_work/jj4/test
    python build_jj4.py --jobs 3           # 200 TT + 200 YT
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import gpu_ffmpeg as G  # noqa: E402
from core.gpu_slots import gpu_slot  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402
from core.uniq_check import hashes, vhash  # noqa: E402

W, H, FPS, NS, SF = 1080, 1920, 30, 7, 60            # ролик 9:16; 7 слайдов × 2 с
NF = NS * SF
TOTAL = NF / FPS
BW, BH = 1080, 608                                    # юзер 16.11: картинка игры 16:9 на всю ширину ролика 9:16
BY = (H - BH) // 2                                    # 656
STRIP = (BY, BY + BH)
FADE, KMIN = 15, 0.35
BTW_T = TOTAL - 1.0
CAP_Y = BY + BH // 2 + 3                              # подпись ПОВЕРХ игры по центру картинки, как в рефе (середина блока 50.5 %)
BTW_Y = BY + BH + 70                                  # «June’s journey btw» — под игрой (не на панели предметов)
HFPS, THR, PLAN_THR = 6, 40, 48
SW_, SH_ = 2340, 1080

WORK = ROOT / "output" / "_work" / "jj4"
STILLS = WORK / "stills"
OUT = {"tt": ROOT / "output" / "junes_journey_4_TT_200", "yt": ROOT / "output" / "junes_journey_4_YT_200"}
REFS = [ROOT / "output" / d for d in ("junes_journey_2_TT_100", "junes_journey_2_YT_150",
                                       "junes_journey_3_TT_100", "junes_journey_3_YT_150")]
REF_STRIP = (520, 1400)
AUDIO = ROOT / "downloads" / "junes_journey_4" / "ref" / "ref_audio.wav"
FONT = ROOT / "fonts" / "cormorant" / "CormorantGaramond[wght].ttf"
CAP = ["rare aesthetic: 2000s hidden", "objects games"]
BTW = "June’s journey btw"

# пул скриншотов: (файл, уровень, разрешённая область x0, y0, x1, y1 — без чёрных краёв артов и полосы «Bonus»)
_C1, _C2, _ART = WORK / "cand", WORK / "cand2", WORK / "art"
FULL = (0, 0, SW_, SH_)
NOTOP = (0, 70, SW_, SH_)
ARTR = (214, 0, 2124, SH_)
# 16.11 юзер убрал с листа 1–4 (весь пляж), 7 (коттедж c005), 21 (гостиная c022)
POOL = ([(_C2 / f"c{i:03d}.png", 2, NOTOP if i in (4, 7) else FULL) for i in (3, 4, 7, 8, 9, 10)]
        + [(_C2 / f"c{i:03d}.png", 3, FULL) for i in (12, 13, 15, 16, 17, 18, 19, 20, 21, 23)]
        + [(_C2 / f"c{i:03d}.png", 4, FULL) for i in (27, 28, 29, 30, 31, 32, 33, 34, 35)]
        + [(_C2 / f"c{i:03d}.png", 5, FULL) for i in (40, 41, 42)] + [(_C1 / "c032.png", 5, NOTOP)]
        + [(_C1 / "c034.png", 6, FULL)])
ZMAX = 1.35                                           # видно ≥ 74 % сцены (ровно целиком — 30 разных слайдов на 2800)


def vname(tag: str, n: int) -> str:
    return f"junes_journey_4_{tag}_{n:03d}_1.mp4"


# ---------------- подпись ----------------
def _font(px: int, wght: int = 560) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT), px)
    try:
        f.set_variation_by_axes([wght])
    except Exception:
        pass
    return f


def cap_px() -> int:
    """Как в рефе (960×720): первая строка = 72 % ширины картинки."""
    for px in range(40, 160):
        if _font(px).getlength(CAP[0]) > 0.72 * BW:
            return px - 1
    return 80


def text_layer(lines: list[str], px: int, cy: int) -> Image.Image:
    """Полный кадр RGBA: строки по центру, середина блока на высоте cy, мягкая тень (core/text_shadow)."""
    f = _font(px)
    lh = int(px * 1.12)
    asc, desc = f.getmetrics()
    blk = Image.new("RGBA", (W, lh * len(lines) + desc + 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(blk)
    for i, s in enumerate(lines):
        d.text(((W - f.getlength(s)) / 2, i * lh), s, font=f, fill=(255, 255, 255, 255))
    blk = add_shadow(blk, blur=4.0, opacity=0.85, offset=(0, 2), grow=2)
    full = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    full.alpha_composite(blk, (-((blk.width - W) // 2), cy - blk.height // 2))
    return full


# ---------------- огибающая затемнения ----------------
def env(f: int) -> float:
    e = min(1.0, (f + 0.5) / FADE, (SF - f - 0.5) / FADE)
    e = e * e * (3 - 2 * e)
    return KMIN + (1 - KMIN) * e


DIMS = (KMIN, 0.5, 0.7, 1.0)                           # уровни затемнения для расчёта (настоящие кадры — при приёмке)


# ---------------- расчёт хэшей до сборки ----------------
class Pred:
    """Хэши полосы картинки для кадрирования: torch на видеокарте, скриншоты в 1/4 размера."""

    def __init__(self, cap_px_: int):
        import torch
        self.t = torch
        self.dev = "cuda"
        self.S = [torch.tensor(np.asarray(Image.open(p).convert("RGB").resize((SW_ // 4, SH_ // 4), Image.BOX)),
                               dtype=torch.float32, device=self.dev).permute(2, 0, 1) for p, _, _ in POOL]
        self.lay = {}
        for key, lines, px, cy in (("cap", CAP, cap_px_, CAP_Y), ("btw", [BTW], int(cap_px_ * 0.82), BTW_Y)):
            a = np.asarray(text_layer(lines, px, cy).crop((0, BY, W, BY + BH)).resize((136, 128), Image.BOX), np.float32)
            self.lay[key] = (torch.tensor(a[..., :3].mean(2), device=self.dev), torch.tensor(a[..., 3] / 255, device=self.dev))

    def bands(self, idx: list[int], win: list[tuple], grade: tuple) -> "torch.Tensor":
        t = self.t
        out = []
        for i, (x, y, w, h) in zip(idx, win):
            c = self.S[i][:, y // 4:(y + h) // 4, x // 4:(x + w) // 4][None]
            out.append(t.nn.functional.interpolate(c, size=(128, 136), mode="bilinear", antialias=True, align_corners=False)[0])
        b = t.stack(out)                                                     # n,3,128,136
        gr = t.tensor(grade_gains(grade), device=self.dev, dtype=t.float32)[None, :, None, None]
        b = (b * gr).clamp(0, 255)
        return 16 + 219 / 255 * (0.2126 * b[:, 0] + 0.7152 * b[:, 1] + 0.0722 * b[:, 2])

    def hash(self, Y: "torch.Tensor", last: bool = False) -> "torch.Tensor":
        """Y n,128,136 (яркость при k=1) → хэши n × len(DIMS)(+1) × 2 × 256 (как есть, зеркально)."""
        t = self.t
        cy, ca = self.lay["cap"]
        frames = []
        for k in DIMS:
            v = 16 + (Y - 16) * k
            frames.append(v * (1 - ca) + (16 + 219 / 255 * cy) * ca)
        if last:
            by, ba = self.lay["btw"]
            v = frames[-1]
            frames.append(v * (1 - ba) + (16 + 219 / 255 * by) * ba)
        F = t.stack(frames, 1)                                               # n,d,128,136
        F = t.nn.functional.interpolate(F, size=(16, 17), mode="area")
        hb = (F[..., 1:] > F[..., :-1]).flatten(2)
        Fm = F.flip(-1)
        hm = (Fm[..., 1:] > Fm[..., :-1]).flatten(2)
        return t.stack([hb, hm], 2).float()                                  # n,d,2,256


def grade_gains(g: tuple) -> list[float]:
    br, warm = g
    return [br * (1 + warm), br, br * (1 - warm)]


class Bank:
    """Отпечатки в half (0/1 и суммы ≤256 — точно), расстояния кусками ≤ ~32 МБ (CLAUDE.md 16.11: большие временные
    таблицы переполняют видеопамять → Windows гонит её через обычную память, очередь gpu_slot встаёт)."""
    CHUNK_BYTES = 32 << 20

    def __init__(self):
        import torch
        self.t = torch
        self.A = torch.zeros((0, 256), dtype=torch.float16, device="cuda")
        self.M = torch.zeros((0, 256), dtype=torch.float16, device="cuda")
        self.owner = torch.zeros((0,), dtype=torch.long, device="cuda")
        self.sa = torch.zeros((0,), dtype=torch.float32, device="cuda")
        self.sm = torch.zeros((0,), dtype=torch.float32, device="cuda")

    def add(self, h, m, owner: int):
        t = self.t
        h = t.as_tensor(h, device="cuda").reshape(-1, 256).to(t.float16)
        m = t.as_tensor(m, device="cuda").reshape(-1, 256).to(t.float16)
        self.A = t.cat([self.A, h])
        self.M = t.cat([self.M, m])
        self.sa = t.cat([self.sa, h.float().sum(1)])
        self.sm = t.cat([self.sm, m.float().sum(1)])
        self.owner = t.cat([self.owner, t.full((len(h),), owner, dtype=t.long, device="cuda")])

    def dist(self, h, skip: int = -999) -> "torch.Tensor":
        """h k×256 → минимальное расстояние каждого до чужих (как есть и зеркально)."""
        t = self.t
        h = t.as_tensor(h, device="cuda").reshape(-1, 256)
        k = len(h)
        best = t.full((k,), 256.0, device="cuda")
        if not len(self.A):
            return best
        hh = h.to(t.float16)
        sh = h.float().sum(1)
        c = max(256, self.CHUNK_BYTES // (4 * max(k, 1)))
        for i in range(0, len(self.A), c):
            A, M = self.A[i:i + c], self.M[i:i + c]
            d = t.minimum(sh[:, None] + self.sa[None, i:i + c] - 2 * (hh @ A.T).float(),
                          sh[:, None] + self.sm[None, i:i + c] - 2 * (hh @ M.T).float())
            d[:, self.owner[i:i + c] == skip] = 1e9
            best = t.minimum(best, d.min(1).values)
            del d
        return best


# ---------------- план ----------------
def rand_window(rng: random.Random, i: int) -> tuple:
    x0, y0, x1, y1 = POOL[i][2]
    zmin = max(1.0, SH_ / (y1 - y0), SH_ * BW / BH / (x1 - x0))          # окно 16:9 (как картинка в ролике)
    z = rng.uniform(zmin, ZMAX)
    h = int(SH_ / z) // 4 * 4
    w = min(int(h * BW / BH) // 4 * 4, (x1 - x0) // 4 * 4)
    x = rng.randint(x0 // 4, (x1 - w) // 4) * 4
    y = rng.randint(y0 // 4, (y1 - h) // 4) * 4
    return (x, y, w, h)


def pick_stills(rng: random.Random, use: dict) -> list[int]:
    """7 разных скриншотов: ≤ 2 с уровня, один уровень не подряд, реже использованные — чаще."""
    for _ in range(200):
        seq: list[int] = []
        lv: dict = {}
        ok = True
        for s in range(NS):
            cand = [i for i in range(len(POOL)) if i not in seq and lv.get(POOL[i][1], 0) < 2
                    and (not seq or POOL[seq[-1]][1] != POOL[i][1])]
            if not cand:
                ok = False
                break
            m = min(use.get(i, 0) for i in cand)
            cand = [i for i in cand if use.get(i, 0) <= m + 1]
            i = rng.choice(cand)
            seq.append(i)
            lv[POOL[i][1]] = lv.get(POOL[i][1], 0) + 1
        if ok:
            return seq
    raise RuntimeError("не собрать 7 скриншотов")


def plan_one(tag: str, n: int, owner: int, rng: random.Random, bank: Bank, pred: Pred, use: dict, tries: int,
             base_px: int) -> tuple[dict, list, float]:
    t = pred.t
    best = None
    for attempt in range(6):
        seq = pick_stills(rng, use)
        grade = (rng.uniform(0.96, 1.05), rng.uniform(-0.03, 0.03))
        wins, hs, mins = [], [], []
        ok = True
        for s, i in enumerate(seq):
            cands = [rand_window(rng, i) for _ in range(tries)]
            Y = pred.bands([i] * tries, cands, grade)
            Hh = pred.hash(Y, last=(s == NS - 1))                            # tries,d,2,256
            d = bank.dist(Hh[:, :, 0].reshape(-1, 256)).reshape(tries, -1).min(1).values
            # и не ближе к уже выбранным слайдам ЭТОГО ролика нет требования; берём лучший из подходящих
            k = int(t.argmax(d))
            if float(d[k]) <= PLAN_THR:
                ok = False
                mins.append(float(d[k]))
                break
            wins.append(cands[k])
            hs.append(Hh[k])
            mins.append(float(d[k]))
        if ok:
            job = dict(tag=tag, n=n, slides=[[i, *w] for i, w in zip(seq, wins)], grade=list(grade),
                       px=base_px - rng.randint(0, 2), pitch=round(rng.uniform(0.965, 1.0), 4))
            return job, hs, min(mins)
        if best is None or min(mins) > best:
            best = min(mins)
    raise RuntimeError(f"{tag}_{n:03d}: не нашлось кадрирований дальше {PLAN_THR} бит (лучшее {best:.0f})")


def plan(slots: list[tuple], bank: Bank, pred: Pred, rng: random.Random, use: dict, tries: int, base_px: int,
         label: str, owner0: int) -> list[dict]:
    jobs = []
    t0 = time.time()
    worst = []
    for k, (tag, n) in enumerate(slots):
        owner = owner0 + k
        job, hs, mn = plan_one(tag, n, owner, rng, bank, pred, use, tries, base_px)
        for h in hs:
            bank.add(h[:, 0], h[:, 1], owner)
        for s in job["slides"]:
            use[s[0]] = use.get(s[0], 0) + 1
        jobs.append(job)
        worst.append(mn)
        if (k + 1) % 25 == 0 or k + 1 == len(slots):
            print(f"  {label}: {k + 1}/{len(slots)}, у последнего ближайший чужой слайд {mn:.0f} бит, "
                  f"{time.time() - t0:.0f} с", flush=True)
    print(f"{label}: {len(jobs)} роликов; ближайший чужой — минимум {min(worst):.0f} бит, медиана {np.median(worst):.0f}",
          flush=True)
    return jobs


# ---------------- сборка ----------------
_R: dict = {}


def _init_render():
    import torch
    _R["t"] = torch
    _R["S"] = {}
    _R["lay"] = {}


def _still(i: int):
    t = _R["t"]
    if i not in _R["S"]:
        _R["S"][i] = t.tensor(np.asarray(Image.open(POOL[i][0]).convert("RGB")), device="cuda").permute(2, 0, 1)  # uint8: 7.6 МБ
    return _R["S"][i]


def _layer(key: str, lines: list[str], px: int, cy: int):
    t = _R["t"]
    k = (key, px)
    if k not in _R["lay"]:
        a = np.asarray(text_layer(lines, px, cy), np.float32)
        y0 = int(np.nonzero(a[..., 3].max(1))[0][0]) // 2 * 2
        y1 = (int(np.nonzero(a[..., 3].max(1))[0][-1]) + 2) // 2 * 2
        rgb = t.tensor(a[y0:y1, :, :3], device="cuda").permute(2, 0, 1)
        al = t.tensor(a[y0:y1, :, 3] / 255, device="cuda")[None]
        _R["lay"][k] = (y0, y1, rgb, al)
    return _R["lay"][k]


def _yuv(fr):
    """fr 3,H,W float 0..255 → байты yuv420p BT.709, ограниченный диапазон."""
    t = _R["t"]
    r, g, b = fr[0], fr[1], fr[2]
    y = 16 + (0.2126 * r + 0.7152 * g + 0.0722 * b) * 219 / 255
    u = 128 + (-0.1146 * r - 0.3854 * g + 0.5 * b) * 224 / 255
    v = 128 + (0.5 * r - 0.4542 * g - 0.0458 * b) * 224 / 255
    u = t.nn.functional.avg_pool2d(u[None, None], 2)[0, 0]
    v = t.nn.functional.avg_pool2d(v[None, None], 2)[0, 0]
    return t.cat([y.flatten(), u.flatten(), v.flatten()]).round().clamp(0, 255).to(t.uint8).cpu().numpy().tobytes()


def build(job: dict) -> str:
    t = _R["t"]
    dest = Path(job["dest"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    gains = t.tensor(grade_gains(tuple(job["grade"])), device="cuda")[:, None, None]
    bands = []
    for i, x, y, w, h in job["slides"]:
        c = _still(i)[:, y:y + h, x:x + w][None].float()
        b = t.nn.functional.interpolate(c, size=(BH, BW), mode="bilinear", antialias=True, align_corners=False)[0]
        bands.append((b * gains).clamp(0, 255))
    cap = _layer("cap", CAP, job["px"], CAP_Y)
    btw = _layer("btw", [BTW], int(job["px"] * 0.82), BTW_Y)
    a_f = (f"asetrate=48000*{job['pitch']},aresample=48000,volume=4dB,atrim=0:{TOTAL},"
           f"afade=t=in:st=0:d=0.15,afade=t=out:st={TOTAL - 0.4}:d=0.4")
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-i", str(AUDIO), "-map", "0:v", "-map", "1:a", "-af", a_f,
           "-frames:v", str(NF), *G.NVENC, "-c:a", "aac", "-b:a", "192k", "-t", f"{TOTAL}", *G.CLEAN, str(dest)]
    errf = dest.with_suffix(".err.txt")
    with gpu_slot(), open(errf, "w", encoding="utf-8", errors="replace") as fe:
        pr = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=fe)
        canvas = t.zeros((3, H, W), device="cuda")
        try:
            prev = None
            thumbs = []
            th = None
            for f in range(NF):
                s, fs = divmod(f, SF)
                k = env(fs)
                bt = 0.0 if f / FPS < BTW_T else min(1.0, (f / FPS - BTW_T) / 0.2)
                key = (s, round(k, 4), round(bt, 3))
                if key != prev:
                    canvas.zero_()
                    canvas[:, BY:BY + BH] = bands[s] * k
                    for (y0, y1, rgb, al), mult in ((cap, 1.0), (btw, bt)):
                        if mult > 0:
                            a = al * mult
                            canvas[:, y0:y1] = canvas[:, y0:y1] * (1 - a) + rgb * a
                    buf = _yuv(canvas)
                    g = 0.2126 * canvas[0] + 0.7152 * canvas[1] + 0.0722 * canvas[2]
                    th = t.nn.functional.avg_pool2d(g[None, None], 8)[0, 0].cpu().numpy().astype(np.float32)
                    prev = key
                pr.stdin.write(buf)
                thumbs.append(th)
            pr.stdin.close()
            code = pr.wait(timeout=120)
        except Exception:
            pr.kill()
            raise
    if code != 0:
        raise RuntimeError(f"{dest.name}: {errf.read_text(encoding='utf-8', errors='replace')[-600:]}")
    errf.unlink(missing_ok=True)
    np.save(dest.with_suffix(".exp.npy"), np.stack(thumbs).astype(np.float16))
    return dest.name


# ---------------- приёмка на настоящих файлах ----------------
def frame_check(p: Path, margin: float = 0.8, junk: float = 12.0) -> list:
    """КАЖДЫЙ кадр ролика против того, что должно стоять (CLAUDE.md 16.11): уменьшенные копии кадров, сохранённые при
    сборке. Плохо: ближе соседний кадр (повтор/скачок) или ни один не похож (мусор/зелёный)."""
    exp = np.load(p.with_suffix(".exp.npy")).astype(np.float32)
    h8, w8 = exp.shape[1:]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vf", f"scale={w8}:{h8}:flags=area,format=gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    out = np.frombuffer(raw, np.uint8).reshape(-1, h8, w8).astype(np.float32)
    if len(out) != len(exp):
        return [("кадров", len(out))]
    ey = exp                                       # format=gray у ffmpeg уже растягивает до полного диапазона 0–255
    flags = []
    for f in range(len(out)):
        d = {k: float(np.abs(out[f] - ey[f + k]).mean()) for k in range(-3, 4) if 0 <= f + k < len(out)}
        best = min(d, key=d.get)
        if d[best] > junk:
            flags.append((f, "мусор", round(d[best], 1)))
        elif best != 0 and d[0] - d[best] > margin:
            flags.append((f, best, round(d[0] - d[best], 2)))
    return flags


def real_hash(p: Path) -> np.ndarray:
    return np.concatenate([vhash(p, [STRIP], 6), vhash(p, [STRIP], 3)])



def render_accept(jobs: list[dict], bank: Bank, pool: ProcessPoolExecutor, ctx: dict, wave: int = 12,
                  max_fail: int = 6) -> None:
    q = list(jobs)
    fails: dict = {}
    done, rej, t0 = 0, 0, time.time()
    cand = WORK / f"cand_render_{int(time.time())}"
    while q:
        cur, q = q[:wave], q[wave:]
        for j in cur:
            j["final"] = j.get("final") or j["dest"]
            j["dest"] = str(cand / f"{j['tag']}_{j['n']:03d}_{fails.get((j['tag'], j['n']), 0)}.mp4")
        for f in [pool.submit(build, j) for j in cur]:
            f.result()
        with ThreadPoolExecutor(8) as ex:
            hs = list(ex.map(lambda j: real_hash(Path(j["dest"])), cur))
            fcs = list(ex.map(lambda j: frame_check(Path(j["dest"])), cur))
        for j, h, fc in zip(cur, hs, fcs):
            key = (j["tag"], j["n"])
            Path(j["dest"]).with_suffix(".exp.npy").unlink(missing_ok=True)
            if fc:                                          # кадр не тот — тот же план собрать заново
                fails[key] = fails.get(key, 0) + 1
                Path(j["dest"]).unlink(missing_ok=True)
                print(f"  {vname(*key)}: кадры не по плану {fc[:4]} — пересборка", flush=True)
                if fails[key] > max_fail:
                    raise SystemExit(f"{vname(*key)}: {max_fail} сборок подряд с ошибкой кадров")
                q.append(j)
                continue
            d = float(bank.dist(h[:, 0]).min())
            if d > THR:
                bank.add(h[:, 0], h[:, 1], 10_000 + len(ctx["accepted"]))
                Path(j["final"]).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(j["dest"], j["final"])
                j["dest"] = j.pop("final")
                ctx["accepted"].append(j)
                done += 1
            else:
                rej += 1
                fails[key] = fails.get(key, 0) + 1
                Path(j["dest"]).unlink(missing_ok=True)
                if fails[key] > max_fail:
                    raise SystemExit(f"{vname(*key)}: {max_fail} вариантов подряд совпадают")
                nj = plan([key], ctx["pbank"], ctx["pred"], ctx["rng"], ctx["use"], ctx["tries"], ctx["px"],
                          f"  замена {vname(*key)} (было {d:.0f} бит)", 50_000 + done + rej)[0]
                nj["dest"], nj["final"] = j["final"], j["final"]
                q.append(nj)
        print(f"  принято {done}, заменено {rej}, {time.time() - t0:.0f} с", flush=True)
    shutil.rmtree(cand, ignore_errors=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--seed", type=int, default=51604)
    ap.add_argument("--tries", type=int, default=160)
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    px = cap_px()
    print(f"подпись {px} px, скриншотов {len(POOL)}", flush=True)
    pred = Pred(px)
    refs = [f for d in REFS if d.exists() for f in sorted(d.glob("*.mp4"))]
    R6 = hashes(refs, [REF_STRIP], 6, WORK / "refs6.npz")
    R3 = hashes(refs, [REF_STRIP], 3, WORK / "refs3.npz")
    pbank, rbank = Bank(), Bank()                       # pbank — расчётные хэши слайдов, rbank — настоящие файлы
    ra = np.concatenate([R[str(f)][:, 0] for f in refs for R in (R6, R3)])
    rm = np.concatenate([R[str(f)][:, 1] for f in refs for R in (R6, R3)])
    _, ui = np.unique(ra, axis=0, return_index=True)          # одинаковые кадры прошлых партий — одной строкой
    pbank.add(ra[ui], rm[ui], -1)
    rbank.add(ra[ui], rm[ui], -1)
    print(f"June's Journey 2/3: {len(refs)} роликов в сравнении", flush=True)
    rng = random.Random(a.seed)
    use: dict = {}
    slots = [(tag, n) for n in range(1, 201) for tag in ("tt", "yt")]
    pf = WORK / f"plan_{a.seed}.json"
    if a.test:
        slots = slots[:6]
    if pf.exists() and not a.test:
        jobs = json.loads(pf.read_text(encoding="utf-8"))
        for j in jobs:                                   # расчётные хэши принятого плана — в банк для замен
            Y = pred.bands([s[0] for s in j["slides"]], [tuple(s[1:]) for s in j["slides"]], tuple(j["grade"]))
            for s in range(NS):
                h = pred.hash(Y[s:s + 1], last=(s == NS - 1))[0]
                pbank.add(h[:, 0], h[:, 1], 0)
            for s in j["slides"]:
                use[s[0]] = use.get(s[0], 0) + 1
    else:
        tjf = WORK / "test_jobs.json"
        fixed = {(j["tag"], j["n"]): j for j in json.loads(tjf.read_text(encoding="utf-8"))} if tjf.exists() and not a.test else {}
        part = pf.with_suffix(".part.json")                       # продолжение прерванного плана с того же места
        if part.exists() and not a.test:
            fixed.update({(j["tag"], j["n"]): j for j in json.loads(part.read_text(encoding="utf-8"))})
            print(f"  продолжаю план: готово {len(fixed)}", flush=True)
        jobs = []
        for k, (tag, n) in enumerate(slots):
            if (tag, n) in fixed:
                j = fixed[(tag, n)]
                Y = pred.bands([s[0] for s in j["slides"]], [tuple(s[1:]) for s in j["slides"]], tuple(j["grade"]))
                for s in range(NS):
                    h = pred.hash(Y[s:s + 1], last=(s == NS - 1))[0]
                    pbank.add(h[:, 0], h[:, 1], k)
                for s in j["slides"]:
                    use[s[0]] = use.get(s[0], 0) + 1
                jobs.append(j)
            else:
                jobs.append(plan_one_add(tag, n, k, rng, pbank, pred, use, a.tries, px))
            if (k + 1) % 25 == 0 or k + 1 == len(slots):
                print(f"  план {k + 1}/{len(slots)}", flush=True)
                if not a.test:
                    part.write_text(json.dumps(jobs), encoding="utf-8")
        if not a.test:
            pf.write_text(json.dumps(jobs), encoding="utf-8")
            part.unlink(missing_ok=True)
    print(f"план готов: {len(jobs)} роликов; использование скриншотов: мин {min(use.values())}, макс {max(use.values())}",
          flush=True)
    if a.plan_only:
        return 0
    ctx = dict(accepted=[], pbank=pbank, pred=pred, rng=random.Random(a.seed + 7), use=use, tries=a.tries, px=px)
    for j in jobs:
        j["dest"] = str((WORK / "test" if a.test else OUT[j["tag"]]) / vname(j["tag"], j["n"]))
    todo = [j for j in jobs if not Path(j["dest"]).exists()]
    for j in jobs:
        if Path(j["dest"]).exists():
            h = real_hash(Path(j["dest"]))
            rbank.add(h[:, 0], h[:, 1], 9_000)
    with ProcessPoolExecutor(a.jobs, initializer=_init_render) as pool:
        render_accept(todo, rbank, pool, ctx, wave=a.jobs * 3)
    if a.test:
        (WORK / "test_jobs.json").write_text(json.dumps([{k: v for k, v in j.items() if k not in ("dest", "final")}
                                                         for j in ctx["accepted"]]), encoding="utf-8")
        return 0
    final = [OUT[j["tag"]] / vname(j["tag"], j["n"]) for j in jobs]
    from core.uniq_check import similarity
    for fps in (6, 3):
        pair, _ = similarity([f for f in final if f.exists()], None, strips=[STRIP], fps=fps, thr=THR,
                             cache=WORK / f"final{fps}.npz")
        tri = pair[np.triu_indices(len(pair), 1)]
        print(f"ПРОВЕРКА ({fps} к/с, полоса {STRIP[0]}–{STRIP[1]}, порог {THR}): худшая пара {tri.max() * 100:.1f} %, "
              f"пар с общими кадрами {int((tri > 0).sum())} из {len(tri)}", flush=True)
    return 0


def plan_one_add(tag, n, owner, rng, bank, pred, use, tries, px) -> dict:
    job, hs, mn = plan_one(tag, n, owner, rng, bank, pred, use, tries, px)
    for h in hs:
        bank.add(h[:, 0], h[:, 1], owner)
    for s in job["slides"]:
        use[s[0]] = use.get(s[0], 0) + 1
    job["plan_min"] = round(mn, 1)
    return job


if __name__ == "__main__":
    raise SystemExit(main())
