#!/usr/bin/env python3
"""
OneState «bro laughed SO HARD his mic glitched» (ID 1) — реф TikTok @newalexia31/video/7700105393057434910 = формат 1312:
квадрат геймплея 1080×1080 (y 420–1500) на чёрном, подпись посередине кадра, промокод STATE9CNL / $10,000 внизу
геймплея, логотип слева снизу, звук — первые 11 с рефа. Юзер 16.11: 200 TT + 200 YT, концепт тот же, но материал
не только паркур (сцены Parkour 1312 + записи OneState: погоня, такси, дроп дрона, армия, медики, машины), кадры
должны подходить по смыслу (берём живые куски с действием); схожесть 0–1 % — как OneState 5: план по отпечаткам
кадров до сборки + приёмка КАЖДОГО кадра готового файла против всех принятых и прошлой партии 1312_300.
Сборка — шаблон OneState 5 (cuvid → память → overlay → NVENC, frame_check каждого кадра, bad_frames).

  python build_onestate_mic.py --test                 # 5 тестовых → output/_work/onestate_mic/test
  python build_onestate_mic.py --tt 200 --yt 200      # → output/onestate_mic_TT_200 + output/onestate_mic_YT_200
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
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import gpu_ffmpeg as G  # noqa: E402
from core.uniq_check import hashes, vhash  # noqa: E402
from core import uniq_fast as UF  # noqa: E402

ID, NAME = "1", "onestate_mic"
W, H, FPS, TOTAL = 1080, 1920, 30, 11.0
NF = round(TOTAL * FPS)
Q = 8                                                  # масштаб расчёта до рендера (кадр 135×240)
CW, CH = 240, 135                                      # кэш исходников: серые 240×135, 30 к/с
STRIP = (450, 852)                                     # полоса проверки: геймплей выше подписи
HFPS, THR, PLAN_THR = 6, 40, 52
SHADE_AMP = 0.10
SP = "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
WORK = ROOT / "output" / "_work" / "onestate_mic"
SEGD = WORK / "seg"
FONT = {"tt": "tiktok", "yt": "default"}
D1309 = ROOT / "downloads" / "1309" / "scenes"
OS3 = ROOT / "downloads" / "onestate3" / "src"         # записи 2560×1440 30 к/с (запас по зуму)
REF = ROOT / "downloads" / "newalexia_ref" / "ref.mp4"
MUSIC = WORK / "sound_11s.wav"                           # первые 11 с звука рефа, −14 LUFS
D1312 = ROOT / "downloads" / "1312" / "scenes"
B0, BH = 420, 1080                                     # квадрат геймплея, как в рефе
CAP_TOP = 852                                          # верх подписи (frame_check — только выше)
BANNER_T = TOTAL / 2 - 4.0                              # промокод 8 с по центру ролика (1.5–9.5 с), как 1312
OV = "cpu"                                             # слои: gpu (overlay_cuda) | cpu (overlay в памяти)
DEC = "cuvid"                                          # распаковка кусков: cuvid | cuvid32 | nvdec (см. --dec)
# прошлые партии OneState в той же раскладке/с тем же футажом — с ними тоже 0 общих кадров
REFS = ["1312_300"]                                    # прошлая партия этого формата (паркур)

COMMENTS_RAW: list = []

# ---------------- куски исходников (внутри одного шота) ----------------
# (вид, файл, начало, конец, место, правило кадра): mid — по центру; hud — интерфейс сверху: окно ниже, зум больше
SPANS = {
    "tx_k1": ("os3", "Taxi_job_1", 0.15, 2.35, "taxi_k", "mid"),
    "tx_g1": ("os3", "Taxi_job_1", 2.5, 13.75, "taxi_g", "hud"),
    "tx_g2": ("os3", "Taxi_job_1", 17.2, 27.75, "taxi_g", "hud"),
    "cp_car": ("os3", "Polic_job", 0.2, 7.6, "cop_car", "mid"),
    "cp_stop": ("os3", "Polic_job", 7.7, 13.0, "cop_stop", "hud"),
    "ch_1": ("os3", "Polic_job", 13.0, 16.35, "chase", "hud"),
    "ch_3": ("os3", "Polic_job", 19.0, 23.0, "chase", "hud"),
    # Police_job_1 (коп стоит у машины, сверху текст интерфейса) — без действия, не берём (тест 16.11)
    "car_1": ("os3", "Cars", 0.1, 5.1, "cars_1", "mid"),
    "car_2": ("os3", "Cars", 12.4, 25.2, "cars_2", "mid"),
    "car_3": ("os3", "Cars", 25.35, 34.2, "cars_3", "mid"),
    "dr_1": ("os3", "Drone_drop_1", 0.1, 4.05, "drone", "hud"),
    "dr_2": ("os3", "Drone_drop_1", 4.15, 18.0, "drone", "hud"),
    "ar_1": ("os3", "Army_Protection_of_the_base", 0.1, 5.45, "army_1", "mid"),
    "ar_2": ("os3", "Army_Protection_of_the_base", 7.65, 19.3, "army_2", "mid"),
    "md_1": ("os3", "Medics_job_1", 0.1, 4.6, "medic", "hud"),
    "md_2": ("os3", "Medics_job_1", 4.7, 10.0, "medic", "hud"),
    "md_3": ("os3", "Medics_job_1", 10.1, 18.6, "medic", "hud"),
}
OTHER = list(SPANS)                                     # не паркур
PK_PLACES = [{2, 17}, {3, 16}, {5, 9, 19, 20}, {6, 10, 14, 22}, {7, 23}, {11, 18}, {8, 21}, {4, 12, 15, 24}]   # 1312
PARKOUR = []
for _e in json.loads((D1312 / "_index.json").read_text(encoding="utf-8")):
    _m = int(_e["file"].split("_")[1])
    if _e.get("hud") or _e["dur"] < 2.6:
        continue
    _pl = next((f"pk_g{i}" for i, g in enumerate(PK_PLACES) if _m in g), f"pk_{_m}")
    SPANS[f"pk_{_m:02d}"] = ("pk", _e["file"][:-4], 0.0, round(_e["dur"] - 0.05, 3), _pl, "mid")
    PARKOUR.append(f"pk_{_m:02d}")

SEG: dict = {}        # ключ → dict(path, sw, sh, n, bad: set кадров-повторов)
SRC: dict = {}        # ключ → кадры 240×135
TABLE: dict = {}      # шрифт → {номер комментария: высота карточки}
PROG = ROOT / "output" / "_work" / "_qa_progress" / f"{os.getpid()}.json"     # дашборд localhost:8767 («Сейчас идёт»)


def prog(stage: str, done: int = 0, total: int | None = None) -> None:
    """Что делает сборщик сейчас — для дашборда (этап, сделано, всего)."""
    try:
        PROG.parent.mkdir(parents=True, exist_ok=True)
        PROG.write_text(json.dumps(dict(stage=stage, done=done, total=total), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def vname(job: dict) -> str:
    return f"{NAME}_{job['tag']}_{job['n']:03d}_{ID}.mp4"


# ---------------- воркеры (шрифт задаётся ДО импорта build_1309_*: TT — TikTok Sans, YT — шрифты 1309) ----------------
_M: dict = {}


def _init_font(font: str) -> None:
    os.environ["OS1309_FONT"] = font
    import build_1309_dance_reels as DR
    B = DR.B
    B.COMMENTS = [DR.wrap_width(t, B.F_REG, B.CMT_PX, B.X1 - B.X0) for t in COMMENTS_RAW]
    _M.update(B=B, DR=DR)


def _table() -> dict:
    import tempfile
    B = _M["B"]
    tmp = Path(tempfile.mkdtemp(prefix="os5t_"))
    av = next(p for d in B.AVATAR_DIRS if d.is_dir() for p in sorted(d.glob("*.jpg")))
    out = {str(k): B.card_png(k, tuple(B.PEOPLE[0]), av, tmp / "k.png") for k in range(len(COMMENTS_RAW))}
    out["lines"] = {str(k): len(B.COMMENTS[k]) for k in range(len(COMMENTS_RAW))}
    shutil.rmtree(tmp, ignore_errors=True)
    out["card_bottom"] = B.CARD_BOTTOM
    return out


def layout(rng: random.Random, tag: str, comment: int) -> dict | None:
    """Квадрат геймплея 1080×1080 на y 420 (как реф)."""
    return dict(b0=B0, bh=BH)


def src_rect(p: dict, bh: int) -> tuple[float, float, float, float]:
    """Окно исходника: «заполнить полосу» с зумом z, положение ox/oy (0.5 — центр)."""
    sw, sh = SEG[p["k"]]["sw"], SEG[p["k"]]["sh"]
    s = max(W * p["z"] / sw, bh * p["z"] / sh)
    cw, ch = W / s, bh / s
    return (sw - cw) * p["ox"], (sh - ch) * p["oy"], cw, ch


def shade_field(seed: int, w: int, h: int) -> np.ndarray:
    """Мягкие волны освещения (как Skinive 2 / OneState 4): v<0 — светлее, v>0 — темнее, сила |v|·AMP."""
    rng = random.Random(seed)
    x = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    ph = (rng.uniform(0, 6.28) + y * rng.uniform(-6, 6)
          + np.sin(y * rng.uniform(2, 5) + rng.uniform(0, 6.28)) * rng.uniform(0.5, 1.5))
    return (0.6 * np.sin(2 * math.pi * rng.uniform(1.2, 2.6) * x + ph)
            + 0.4 * np.sin(2 * math.pi * rng.uniform(2.5, 4.5) * x + ph * 1.7 + rng.uniform(0, 6.28)))


# ---------------- рендер (видеокарта) ----------------
class _Res:
    def __init__(self, code: int, err: str):
        self.returncode, self.stderr = code, err


def _run_ff(cmd: list, errf: Path, timeout: float = 120) -> _Res:
    """ffmpeg без каналов (stderr в файл): зависшую сборку на видеокарте прерываем."""
    with open(errf, "w", encoding="utf-8", errors="replace") as fe:
        pr = subprocess.Popen(cmd[:1] + ["-nostdin"] + cmd[1:], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=fe)
        try:
            code = pr.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pr.kill()
            try:
                pr.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass
            code = -9
    err = errf.read_text(encoding="utf-8", errors="replace")
    return _Res(code, err + (chr(10) + f"timeout {timeout:.0f} s" if code == -9 else ""))


def build(job: dict) -> str:
    import tempfile
    from core.gpu_slots import gpu_slot
    B = _M["B"]
    SEG.update(job["segs"])
    tmp = Path(tempfile.mkdtemp(prefix="osm_"))
    rng = random.Random(job["seed"])
    b0, bh = job["b0"], job["bh"]
    import build_1312_reels as R                          # подпись 1312 (Figtree, обводка, эмодзи Apple)
    R.caption_png(tmp / "cap.png")
    bgc = "0x000000"
    lx, ly, _ = B.logo_png(rng, (b0, b0 + bh), tmp / "logo.png")
    v = shade_field(job["shade"], W, H)[b0:b0 + bh]
    lay = np.zeros((H, W, 4), np.uint8)
    lay[b0:b0 + bh, :, :3] = np.where(v < 0, 255, 0)[..., None]
    lay[b0:b0 + bh, :, 3] = (np.abs(v) * SHADE_AMP * 255).astype(np.uint8)
    layer = Image.fromarray(lay, "RGBA")
    layer.alpha_composite(Image.open(tmp / "logo.png").convert("RGBA"), (lx, ly))
    layer.alpha_composite(Image.open(tmp / "cap.png").convert("RGBA"), (0, 0))
    layer.save(tmp / "layer.png", compress_level=1)
    cw_, ch_ = B.banner_anim()
    bx = G._even((W - cw_) // 2)
    by = G._even(b0 + bh - 16 - ch_ + round(ch_ * 0.06))
    ins = ["-i", str(tmp / "layer.png"), "-i", str(B.BANNER_ANIM), "-i", str(MUSIC),
           "-f", "lavfi", "-i", f"color=c={bgc}:s={W}x{H}:r={FPS}:d={TOTAL}"]
    ov = os.environ.get("OSM_OV", OV)
    if ov == "gpu":
        fc = [G.layer(0, 0, NF, "ly", FPS).replace("format=yuva420p,hwupload_cuda", f"format=yuva420p,{SP},hwupload_cuda"),
              f"[1:v]fps={FPS},format=yuva420p,{SP},hwupload_cuda,setpts=PTS-STARTPTS+{BANNER_T:.3f}/TB[bn]",
              f"[3:v]format=yuv420p,{SP},hwupload_cuda[c]"]
    else:                                                 # слои — обычным overlay в памяти, NVENC берёт готовый кадр
        fc = [f"[0:v]loop=loop={NF - 1}:size=1:start=0,settb=1/{FPS},setpts=N,format=yuva420p[ly]",
              f"[1:v]fps={FPS},format=yuva420p,setpts=PTS-STARTPTS+{BANNER_T:.3f}/TB[bn]",
              "[3:v]format=yuv420p[c]"]
    for j, p in enumerate(job["pieces"]):
        x, y, cw, ch = (G._even(t) for t in src_rect(p, bh))
        sg = SEG[p["k"]]
        mode = os.environ.get("OSM_DEC", DEC)
        if mode == "cpu":                                 # эталон: распаковка процессором
            ins += ["-i", sg["path"]]
            geo_f = f"crop={cw}:{ch}:{x}:{y},scale={W}:{bh}:flags=bicubic,"
        elif mode == "nvdec":                               # распаковка nvdec → кадр в обычную память, обрезка/масштаб — процессор
            ins += ["-hwaccel", "cuda", "-i", sg["path"]]
            geo_f = f"crop={cw}:{ch}:{x}:{y},scale={W}:{bh}:flags=bicubic,"
        else:                                             # h264_cuvid режет и масштабирует сам
            # распаковка С НУЖНОГО МЕСТА (-ss до -i: ближайший ключевой кадр заготовки, их каждые 15, лишнее отбрасывается
            # точно по времени) — иначе распаковщик гонит кусок с начала заготовки (замер 16.11: NVDEC 96 %, половина впустую)
            ss = ["-ss", f"{(p['f0'] - 0.5) / FPS:.4f}"] if p["f0"] > 0 else []
            ins += ["-c:v", "h264_cuvid", *(["-surfaces", "32"] if mode == "cuvid32" else []),
                    "-crop", f"{y}x{sg['sh'] - y - ch}x{x}x{sg['sw'] - x - cw}", "-resize", f"{W}x{bh}", *ss, "-i", sg["path"]]
            geo_f = ""
        f0 = 0 if mode not in ("cpu", "nvdec") else p["f0"]
        fc.append(f"[{4 + j}:v]trim=start_frame={f0}:end_frame={f0 + p['frames']},setpts=PTS-STARTPTS,"
                  f"{geo_f}setsar=1,format=yuv420p,tpad=stop_mode=clone:stop=3,trim=end_frame={p['frames']},"
                  f"setpts=PTS-STARTPTS[p{j}]")
    n = len(job["pieces"])
    if ov == "gpu":
        fc += ["".join(f"[p{j}]" for j in range(n)) + f"concat=n={n}:v=1:a=0,{SP},hwupload_cuda[g]",
               f"[c][g]overlay_cuda=0:{b0}[gg]",
               "[gg][ly]overlay_cuda=0:0[d]",
               f"[d][bn]overlay_cuda={bx}:{by}:eof_action=pass[v]"]
    else:
        fc += ["".join(f"[p{j}]" for j in range(n)) + f"concat=n={n}:v=1:a=0[g]",
               f"[c][g]overlay=0:{b0}:format=yuv420[gg]",
               "[gg][ly]overlay=0:0:format=yuv420[d]",
               f"[d][bn]overlay={bx}:{by}:eof_action=pass:format=yuv420,format=yuv420p,{SP}[v]"]
    fc += [
           f"[2:a]asetrate=48000*{job['pitch']},aresample=48000,atrim=0:{TOTAL},afade=t=out:st={TOTAL - 0.3}:d=0.3[a]"]
    dest = Path(job["dest"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
           "-frames:v", str(NF), "-t", f"{TOTAL}", *G.NVENC, "-c:a", "aac", "-b:a", "192k", *G.CLEAN, str(dest)]
    with gpu_slot():
        for attempt in range(3):
            r = _run_ff(cmd, tmp / f"err{attempt}.txt")
            if r.returncode == 0:
                break
            if attempt == 2 or ("Invalid argument" in r.stderr and attempt == 0):
                (WORK / f"fail_{dest.stem}.txt").write_text(subprocess.list2cmdline(cmd) + 2 * chr(10) + r.stderr,
                                                           encoding="utf-8")
                raise RuntimeError(f"{dest.name}: {r.stderr[-600:]}")
            time.sleep(3)
    shutil.rmtree(tmp, ignore_errors=True)
    return dest.name


# ---------------- исходники ----------------
def prep_segments() -> None:
    """Каждый кусок SPANS → короткая h264-заготовка 30 к/с без B-кадров (читается с нуля на видеокарте), её кадры
    240×135 для расчёта и список кадров-повторов (сбой записи игры: такой кадр посреди движения = микрофриз)."""
    SEGD.mkdir(parents=True, exist_ok=True)

    def one(k):
        kind, name, t0, t1, _pl, _r = SPANS[k]
        src = {"1309": D1309, "pk": D1312}.get(kind, OS3) / f"{name}.mp4"
        dest = SEGD / f"{k}.mp4"
        G.cut_segment(src, t0, t1, dest, 30)
        _c, sw, sh = G.probe(dest)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(dest), "-vf", f"scale={CW}:{CH}:flags=area,format=gray",
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        a = np.frombuffer(raw, np.uint8).reshape(-1, CH, CW)
        d = np.abs(np.diff(a.astype(np.int16), axis=0)).mean((1, 2))
        bad = set()
        for i in range(1, len(d)):                         # кадр i+1 = повтор кадра i посреди движения
            if d[i] < 0.12 and (d[i - 1] > 0.5 or (i + 1 < len(d) and d[i + 1] > 0.5)):
                bad.add(i + 1)
        if len(d) and d[0] < 0.12 and len(d) > 1 and d[1] > 0.5:
            bad.add(1)
        return k, dict(path=str(dest), sw=sw, sh=sh, n=len(a), bad=sorted(bad)), a
    with ThreadPoolExecutor(6) as ex:
        for k, meta, a in ex.map(one, list(SPANS)):
            SEG[k] = meta
            SRC[k] = a


# ---------------- план ----------------
def geo(rng: random.Random, rule: str, big: bool) -> dict:
    """Кадр по центру: зум от центра; у геймплея с интерфейсом окно чуть ниже (машина внизу), зум больше.
    big — исходник 2560×1440 (запас по зуму до 1.75 без увеличения)."""
    zmax = 1.75 if big else 1.52                          # 1920-исходники: до 1.52 (увеличение ≤ 1.1×) — квартира упиралась в разброс
    if rule == "hud":
        return dict(z=round(rng.uniform(1.2, zmax), 3), ox=round(rng.uniform(0.42, 0.58), 3),
                    oy=round(rng.uniform(0.55, 0.78), 3))
    return dict(z=round(rng.uniform(1.04, zmax), 3), ox=round(rng.uniform(0.42, 0.58), 3),
                oy=round(rng.uniform(0.42, 0.58), 3))


def piece(rng: random.Random, k: str, frames: int) -> dict | None:
    sg = SEG[k]
    if frames > sg["n"] - 2:
        return None
    bad = set(sg["bad"])
    for _ in range(12):
        f0 = rng.randint(0, sg["n"] - frames - 1)
        if not any(f in bad for f in range(f0, f0 + frames + 1)):
            p = dict(k=k, f0=f0, frames=frames)
            p.update(geo(rng, SPANS[k][5], sg["sw"] > 2000))
            return p
    return None


def split(rng: random.Random, parts: int, lo: float, hi: float) -> list[int]:
    """Длины частей в кадрах (сумма = NF), каждая в [lo, hi] секунд."""
    for _ in range(50):
        xs = [rng.uniform(lo, hi) for _ in range(parts)]
        s = sum(xs)
        fr = [round(x * TOTAL / s * FPS) for x in xs]
        fr[-1] = NF - sum(fr[:-1])
        if all(lo * FPS - 2 <= f <= hi * FPS + 2 for f in fr):
            return fr
    return []


def candidate(rng: random.Random, kind: str) -> list[dict] | None:
    """3–4 куска по 2–4 с: каждый — один непрерывный кусок шота; соседние — из разных мест; хотя бы один не паркур
    (юзер 16.11: «чтобы не только паркур»)."""
    n = rng.choice((3, 3, 4))
    fr = split(rng, n, 2.0, 4.2)
    if not fr:
        return None
    keys: list[str] = []
    for _ in range(n):
        pool = PARKOUR if rng.random() < 0.5 else OTHER
        opts = [k for k in pool if k not in keys and (not keys or SPANS[k][4] != SPANS[keys[-1]][4])]
        if not opts:
            return None
        keys.append(rng.choice(opts))
    if all(k in PARKOUR for k in keys):
        i = rng.randrange(n)
        opts = [k for k in OTHER if (i == 0 or SPANS[k][4] != SPANS[keys[i - 1]][4]) and
                (i == n - 1 or SPANS[k][4] != SPANS[keys[i + 1]][4])]
        keys[i] = rng.choice(opts)
    out = []
    for k, f in zip(keys, fr):
        p = piece(rng, k, f)
        if p is None:
            return None
        out.append(p)
    return out


def make_job(n: int, tag: str, comment: int, rng: random.Random, avatars: list, people: list) -> dict | None:
    pcs = None
    for _ in range(40):
        pcs = candidate(rng, "mix")
        if pcs:
            break
    if not pcs:
        return None
    return dict(n=n, tag=tag, comment=0, kind="mix", pieces=pcs, seed=rng.randrange(10 ** 9),
                shade=rng.randrange(10 ** 9), pitch=round(rng.uniform(0.975, 1.025), 4), b0=B0, bh=BH)


UST = None                                             # core.uniq_fast.FrameStore — кадры заготовок 480×270 (main)


def frames_of(jobs: list[dict], every: bool = False):
    """Кадры роликов для прогноза отпечатков (core.uniq_fast): 6 к/с (как проверка: кадр 5i+2) или каждый кадр."""
    fr = np.arange(NF) if every else np.array([min(NF - 1, round(i * FPS / HFPS) + 2) for i in range(round(TOTAL * HFPS))])
    idx, box, scale, A, C = [], [], [], [], []
    for job in jobs:
        starts = np.cumsum([0] + [p["frames"] for p in job["pieces"]])
        j = np.searchsorted(starts, fr, side="right") - 1
        pb = [UF.strip_box(tuple(G._even(t) for t in src_rect(p, job["bh"])), job["b0"], job["bh"], STRIP)
              for p in job["pieces"]]
        idx.append(np.array([UST.off[job["pieces"][q]["k"]] + job["pieces"][q]["f0"] for q in j]) + fr - starts[j])
        box.append(np.array([pb[q] for q in j], np.float32))
        scale.append(np.array([UF.CW / SEG[job["pieces"][q]["k"]]["sw"] for q in j], np.float32))
        sh = shade_field(job["shade"], W // 4, H // 4)[STRIP[0] // 4:STRIP[1] // 4]
        a, c = UF.shade_cells(sh, SHADE_AMP)
        A.append(np.repeat(a[None], len(fr), 0))
        C.append(np.repeat(c[None], len(fr), 0))
    return UF.Frames(np.concatenate(idx), np.concatenate(box), np.concatenate(scale), np.concatenate(A),
                     np.concatenate(C), len(fr))


def predict(job: dict):
    """Прогноз отпечатков одного ролика (6 к/с) — (H, M) half на видеокарте [кадров, 256]."""
    H_, M_ = UF.predict(UST, frames_of([job]))
    return H_[0], M_[0]


Bank = UF.Bank


def plan_jobs(slots: list[tuple[str, int, int]], bank, rng: random.Random, avatars, people, tries: int,
              label: str, out_dir) -> list[dict]:
    """Ролик за роликом: варианты пачками по 24 (прогноз и расстояние — одним расчётом на видеокарте), берётся самый
    далёкий от уже взятых и прошлых партий; хватило запаса PLAN_THR — дальше не перебираем."""
    import torch
    jobs, worst, t0 = [], [], time.time()
    for k, (tag, n, comment) in enumerate(slots, 1):
        best = None
        for _ in range(0, tries, 24):
            cands = [c for c in (make_job(n, tag, comment, rng, avatars, people) for _ in range(24)) if c]
            if not cands:
                continue
            Hh, Mm = UF.predict(UST, frames_of(cands))
            d = bank.min_dist(Hh)
            i = int(torch.argmax(d))
            if best is None or float(d[i]) > best[0]:
                best = (float(d[i]), cands[i], Hh[i], Mm[i])
            if best[0] > PLAN_THR:
                break
        d, j, Hh, Mm = best
        j["plan_dist"] = round(d, 1)
        bank.add(Hh, Mm)
        j["dest"] = str(out_dir(tag) / vname(j))
        jobs.append(j)
        worst.append(d)
        if len(slots) > 1:
            prog(f"{label}: варианты роликов по отпечаткам", k, len(slots))
        if k % 50 == 0:
            print(f"  {label}: {k}/{len(slots)}, у последнего ближайший чужой кадр {d:.0f} бит, {time.time() - t0:.0f} с",
                  flush=True)
    w = sorted(worst)
    print(f"{label}: {len(jobs)} роликов за {time.time() - t0:.0f} с; ближайший чужой кадр — минимум {w[0]:.0f} бит, "
          f"медиана {w[len(w) // 2]:.0f}; ≤ {THR} бит: {sum(x <= THR for x in w)}, ≤ {PLAN_THR}: {sum(x <= PLAN_THR for x in w)}",
          flush=True)
    return jobs


# ---------------- приёмка по настоящим файлам ----------------
def real_hash(path: Path) -> np.ndarray:
    """КАЖДЫЙ кадр готового ролика (30 к/с): (кадры, 2, 256) — обычный и зеркальный отпечаток."""
    h, m = UF.real_hash(path, STRIP)
    return np.stack([h, m], 1)


def frame_check(job: dict, path: Path, margin: float = 0.8, junk: float = 14.0) -> list:
    """КАЖДЫЙ кадр ролика против того кадра исходника, который должен стоять (юзер 13.11: «фризит, лагает, зелёное»):
    полоса геймплея (выше промокода/логотипа) сравнивается с кадрами исходника k−3…k+3 (та же обрезка и волны света).
    Плохо: ближе другой кадр исходника (повтор = фриз, пропуск = рывок) или ни один не похож (мусор/зелёный)."""
    b0, bh = job["b0"], job["bh"]
    rows = (CAP_TOP - b0) - (CAP_TOP - b0) % Q                # выше подписи (подпись — посередине геймплея)
    w8, h8, rh = W // Q, rows // Q, max(1, round(bh / Q))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                          f"crop={W}:{rows}:0:{b0},scale={w8}:{h8}:flags=area,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    out = np.frombuffer(raw, np.uint8).reshape(-1, h8, w8).astype(np.float32)
    v = shade_field(job["shade"], W // Q, H // Q)[round(b0 / Q):round(b0 / Q) + h8]
    sa, sc = np.abs(v) * SHADE_AMP, np.where(v < 0, 255.0, 0.0)
    starts = np.cumsum([0] + [p["frames"] for p in job["pieces"]])
    cache: dict = {}

    def expect(p: dict, k: int) -> np.ndarray:
        key = (p["k"], k, p["z"], p["ox"], p["oy"])
        if key not in cache:
            sg = SEG[p["k"]]
            sx, sy = CW / sg["sw"], CH / sg["sh"]
            x, y, cw, ch = src_rect(p, bh)
            im = Image.fromarray(SRC[p["k"]][k]).resize((w8, rh), Image.Resampling.BILINEAR,
                                                        box=(x * sx, y * sy, (x + cw) * sx, (y + ch) * sy))
            cache[key] = np.asarray(im, np.float32)[:h8] * (1 - sa) + sc * sa
        return cache[key]
    flags = []
    if len(out) != NF:
        return [("кадров", len(out))]
    for f in range(NF):
        j = int(np.searchsorted(starts, f, side="right")) - 1
        p = job["pieces"][j]
        k = p["f0"] + f - starts[j]
        n = len(SRC[p["k"]])
        d = {dk: float(np.abs(out[f] - expect(p, k + dk)).mean()) for dk in range(-3, 4) if 0 <= k + dk < n}
        best = min(d, key=d.get)
        if d[best] > junk:
            flags.append((f, "мусор", round(d[best], 1)))
        elif best != 0 and d[0] - d[best] > margin:
            flags.append((f, best, round(d[0] - d[best], 2)))
    return flags


def check_one(job: dict) -> tuple:
    path = Path(job["dest"])
    return real_hash(path), G.bad_frames(path), frame_check(job, path)


def render_accept(jobs: list[dict], bank: Bank, pools: dict, ctx: dict, max_fail: int = 8) -> None:
    """Все ролики сразу в очередь видеокарты; каждый готовый сразу проверяется (потоки) и попадает в папку, только
    если: ни один его кадр (6 и 3 к/с) не ближе THR к принятым и прошлым партиям; нет пустых/зелёных кадров и
    повторов посреди движения (bad_frames); КАЖДЫЙ кадр — ровно тот кадр исходника, что в плане (frame_check).
    Иначе — новый вариант этого слота (план с учётом принятых и ещё собирающихся)."""
    from concurrent.futures import FIRST_COMPLETED, wait
    import torch
    fails: dict = {}
    done, rej, t0 = 0, 0, time.time()
    cand_dir = WORK / f"cand_{os.getpid()}"
    segs = {k: SEG[k] for k in SPANS}
    pending: dict = {}                                    # слот → предсказанные хэши ещё не принятого ролика
    chk = ThreadPoolExecutor(8)
    building, checking = {}, {}

    def submit(j: dict) -> None:
        key = (j["tag"], j["n"])
        j["final"] = j.get("final") or j["dest"]
        j["dest"] = str(cand_dir / f"{j['tag']}_{j['n']:03d}_{fails.get(key, 0)}.mp4")
        j["segs"] = segs
        pending[key] = predict(j)
        building[pools[j["tag"]].submit(build, j)] = j
    for j in jobs:
        submit(j)
    while building or checking:
        fin, _ = wait(list(building) + list(checking), return_when=FIRST_COMPLETED)
        for fu in fin:
            if fu in building:
                j = building.pop(fu)
                fu.result()
                checking[chk.submit(check_one, j)] = j
                continue
            j = checking.pop(fu)
            h, bad, fr = fu.result()
            j.pop("segs", None)
            key = (j["tag"], j["n"])
            d = float(bank.min_dist(torch.tensor(h[:, 0])[None])[0])
            if d > THR and not bad and not fr:
                bank.add(h[:, 0], h[:, 1])
                pending.pop(key, None)
                Path(j["final"]).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(j["dest"], j["final"])
                j["dest"] = j.pop("final")
                j["min_dist"] = d
                ctx["hash30"][str(Path(j["dest"]))] = h
                ctx["accepted"].append(j)
                done += 1
                ctx["tick"](done, rej)
                if done % 25 == 0:
                    print(f"  принято {done}, заменено {rej}, {time.time() - t0:.0f} с", flush=True)
                continue
            rej += 1
            why = f"bad_frames {bad[:6]}" if bad else f"кадры не те {fr[:6]}" if fr else f"ближайший чужой кадр {d:.0f} бит"
            print(f"  замена {vname(j)}: {why}", flush=True)
            ctx["tick"](done, rej)
            fails[key] = fails.get(key, 0) + 1
            Path(j["dest"]).unlink(missing_ok=True)
            if fails[key] > max_fail:
                raise SystemExit(f"{vname(j)}: {max_fail} вариантов подряд не прошли — нужен шире разброс")
            pending.pop(key, None)
            b2 = bank.copy()
            for Hh, Mm in pending.values():
                b2.add(Hh, Mm)
            nj = plan_jobs([(j["tag"], j["n"], j["comment"])], b2, ctx["rng"], ctx["avatars"], ctx["people"],
                           ctx["tries"], f"  новый вариант {vname(j)}", ctx["out_dir"])[0]
            nj["final"] = nj["dest"] = j["final"]
            del b2
            torch.cuda.empty_cache()                      # память расчёта не держим: иначе очередь видеокарты не пустит сборки
            submit(nj)
    chk.shutdown()
    print(f"  принято {done}, заменено {rej}, {time.time() - t0:.0f} с", flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--prep", action="store_true", help="только подготовка: заготовки, хэши прошлых партий, план")
    ap.add_argument("--dec", default=DEC, choices=("cuvid", "cuvid32", "nvdec"))
    ap.add_argument("--tt", type=int, default=0)
    ap.add_argument("--yt", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=51116)
    ap.add_argument("--tries", type=int, default=600)
    ap.add_argument("--thr", type=int, default=48, help="приёмка: ни один кадр не ближе стольких бит из 256 (запас к 40)")
    a = ap.parse_args()
    global THR, PLAN_THR, UST
    THR, PLAN_THR = a.thr, a.thr + 10                   # план с запасом: ошибка прогноза ~7 бит (95 % ≤ 12)
    WORK.mkdir(parents=True, exist_ok=True)
    _init_font("default")
    if not MUSIC.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-t", f"{TOTAL}", "-i", str(REF), "-map", "0:a:0", "-af",
                        f"loudnorm=I=-14:TP=-1.5,afade=t=out:st={TOTAL - 0.3}:d=0.3", "-ar", "48000", "-ac", "2", str(MUSIC)],
                       check=True)
    B = _M["B"]
    B.banner_anim()
    t0 = time.time()
    prep_segments()
    UST = UF.FrameStore()
    UST.load({k: Path(v["path"]) for k, v in SEG.items()})
    print(f"исходники: {len(SEG)} кусков, повторов кадров: "
          f"{ {k: len(v['bad']) for k, v in SEG.items() if v['bad']} }, {time.time() - t0:.0f} с", flush=True)
    os.environ["OSM_DEC"] = a.dec                       # воркеры наследуют способ распаковки
    pools = {tag: ProcessPoolExecutor(a.jobs, initializer=_init_font, initargs=(FONT[tag],)) for tag in ("tt", "yt")}
    avatars, people = [], []

    ref_dirs = REFS[:4] if a.test else REFS              # тест: только партии с готовыми хэшами (OneState 4, 1310_v2)
    refs = [f for d in ref_dirs if (ROOT / "output" / d).exists() for f in sorted((ROOT / "output" / d).glob("*.mp4"))]
    bank = Bank()
    for fps in (6, 3):
        R = hashes(refs, [STRIP], fps, WORK / f"refs{fps}.npz")
        for f in refs:
            bank.add(R[str(f)][:, 0], R[str(f)][:, 1])
    print(f"прошлые партии в сравнении: {len(refs)} роликов, {time.time() - t0:.0f} с", flush=True)

    rng = random.Random(a.seed)
    if a.test:
        out_dir = lambda tag: WORK / "test"           # noqa: E731
        slots = [("tt" if c % 2 == 0 else "yt", c + 1, 0) for c in range(5)]
    else:
        out = {"tt": ROOT / "output" / f"{NAME}_TT_{a.tt}", "yt": ROOT / "output" / f"{NAME}_YT_{a.yt}"}
        out_dir = lambda tag: out[tag]                 # noqa: E731
        slots = [(tag, n, 0)
                 for tag, cnt in (("tt", a.tt), ("yt", a.yt)) for n in range(1, cnt + 1)]
    pf = WORK / f"plan_{a.seed}_{'test' if a.test else f'{a.tt}_{a.yt}'}.json"
    if pf.exists():
        jobs = json.loads(pf.read_text(encoding="utf-8"))
    else:
        jobs = plan_jobs(slots, bank.copy(), rng, avatars, people, a.tries, "план", out_dir)
        pf.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    if a.prep:
        print(f"ПЛАН ГОТОВ: {len(jobs)} роликов → {pf}", flush=True)
        for p_ in pools.values():
            p_.shutdown()
        return 0
    todo = [j for j in jobs if not Path(j["dest"]).exists()]
    have = [Path(j["dest"]) for j in jobs if Path(j["dest"]).exists()]
    hcf = WORK / f"hash30_{a.seed}_{a.tt}_{a.yt}.npz"    # отпечатки каждого кадра готовых роликов (кэш: путь → (h, mtime))
    hc = dict(np.load(hcf, allow_pickle=True)["d"].item()) if hcf.exists() else {}
    hash30 = {}

    def get30(f: Path):
        c = hc.get(str(f))
        return c[0] if c is not None and c[1] == f.stat().st_mtime else real_hash(f)
    with ThreadPoolExecutor(8) as ex:                    # готовые ролики (перезапуск) — из кэша или в потоках
        for i, (f, h) in enumerate(zip(have, ex.map(get30, have)), 1):
            hash30[str(f)] = h
            bank.add(h[:, 0], h[:, 1])
            if i % 5 == 0 or i == len(have):
                prog("отпечатки готовых роликов (каждый кадр)", i, len(have))
    if have:
        print(f"готовых роликов в сравнении: {len(have)}, {time.time() - t0:.0f} с", flush=True)
    progf = WORK / "progress.json"
    total = len(jobs)

    def tick(done: int, rej: int = 0) -> None:
        progf.write_text(json.dumps(dict(done=total - len(todo) + done, total=total)), encoding="utf-8")
        prog(f"сборка + проверка каждого ролика (заменено {rej})", total - len(todo) + done, total)
    tick(0)
    ctx = dict(accepted=[], rng=random.Random(a.seed + 7), avatars=avatars, people=people, tries=a.tries,
               out_dir=out_dir, tick=tick, hash30=hash30)
    render_accept(todo, bank, pools, ctx)
    (WORK / f"accepted_{pf.stem}.json").write_text(json.dumps(ctx["accepted"], ensure_ascii=False), encoding="utf-8")
    np.savez(hcf, d=np.array({k: (v, Path(k).stat().st_mtime) for k, v in hash30.items() if Path(k).exists()}, dtype=object))
    err = []
    for j in ctx["accepted"]:
        p = predict(j)[0].float().cpu().numpy()
        r = vhash(Path(j["dest"]), [STRIP], 6)[:, 0].astype(np.float32)
        m = min(len(p), len(r))
        err.append(np.abs(p[:m] - r[:m]).sum(1))
    if err:
        e = np.concatenate(err)
        print(f"ошибка расчёта до рендера, бит на кадр: среднее {e.mean():.1f}, 95 % {np.percentile(e, 95):.0f}", flush=True)
    prog("итоговая проверка: каждый кадр всех пар (отдельный процесс check_uniq_allframes)", 0, None)
    subprocess.run([sys.executable, str(ROOT / "check_uniq_allframes.py"), *{str(Path(j["dest"]).parent) for j in jobs},
                    "--strip", str(STRIP[0]), str(STRIP[1]), "--refs-cache", str(WORK / "refs6.npz"), "--hash-cache", str(hcf)])
    for p in pools.values():
        p.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
