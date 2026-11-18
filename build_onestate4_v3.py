#!/usr/bin/env python3
"""
OneState 4 (ID 1309) v3 — 200 TT + 200 YT × 7 с с ГАРАНТИЕЙ 0 общих кадров (юзер 2026-11-13: «до генерации гарантию
в 0 проц схожести дай, покажи тестовые и потом генерим»). Содержание — как build_onestate4_uniq: захватывающее начало
(20 начал HOOKS), сцены 1309 + экшн-вставки ×2–3, новые подписи/комментарии, баннер, логотип, музыка.

ЧТО ГАРАНТИРУЕТ 0 %:
  1) ПЛАН ДО РЕНДЕРА: каждый кадр каждого ролика (6 к/с) заранее считается тем же способом, что и проверка
     (dHash 16×16 полосы y 450–930, с зеркалом) по уменьшенным кадрам исходников; ролик берётся в план, только если ни
     один его кадр не ближе PLAN_THR (52) бит ни к одному кадру уже взятых и onestate_1310_*_v2 (тот же футаж);
  2) ПРИЁМКА ПО НАСТОЯЩИМ ФАЙЛАМ: собранный ролик хэшируется (6 и 3 к/с) и попадает в папку, только если ни один его
     кадр не ближе 40 бит ни к одному кадру принятых роликов и 1310_v2; иначе — новый вариант этого слота. Поэтому в
     папке не может оказаться пары с общими кадрами — без «кругов» после сборки.
Рычаги различия (кадр всегда ПО ЦЕНТРУ): секунды исходника, скорость, зум 1.0–1.4 от центра, высота полосы (раскладка),
мягкие волны освещения ±10 % поверх геймплея (свой рисунок у ролика), оттенок фона, тон музыки.
ВСЁ НА ВИДЕОКАРТЕ (core/gpu_ffmpeg): распаковка с обрезкой/масштабом в h264_cuvid, scale_cuda, overlay_cuda, NVENC;
процессор — только картинки-слои (подпись, карточка, логотип, волны) и звук.

  python build_onestate4_v3.py --prep        # заготовки, кэш исходников, хэши 1310_v2, план (≈ 3–5 мин)
  python build_onestate4_v3.py --test        # 3 TT + 3 YT → output/_work/onestate4_v3/test
  python build_onestate4_v3.py               # → output/onestate_4_TT_200 + output/onestate_4_YT_200
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

ID, NAME = "1309", "onestate_4"
# 30 к/с (юзер 2026-11-13: «резкие срывы кадров»): при дробном шаге по кадрам записи (60 к/с ×2.4, 30 к/с ×2.5 в ролике
# 60 к/с) кадры шли через 2-3-2-3 / 1-1-2 — движение дёргалось. В ролике 30 к/с все скорости дают РОВНЫЙ шаг:
# запись 60 к/с ×1.5/2/2.5/3 → каждый 3/4/5/6-й кадр, запись 30 к/с ×2/3 → каждый 2/3-й
W, H, FPS, TOTAL = 1080, 1920, 30, 7.0
SPEEDS = {60: (2.0, 2.5, 3.0), 30: (2.0, 3.0)}
NF = round(TOTAL * FPS)
SW, SH = 1920, 1080                                    # все исходники 1920×1080 h264
Q = 8                                                  # масштаб предрасчёта (кадр 135×240)
CW, CH, CFPS = SW // Q, SH // Q, 30                    # кэш исходников: 240×135 серые, 30 к/с
STRIP = (450, 930)                                     # проверка: полоса y 450–930 (геймплей; подпись — если опустилась)
HFPS, THR, PLAN_THR = 6, 40, 52
SHADE_AMP = 0.10
# у заготовок OneState 3 нет меток цвета, у сцен 1309 — bt709: новый ffmpeg вставляет перевод цвета (на процессоре) перед
# overlay_cuda и падает — все потоки помечаем одинаково (только метки, пиксели не трогаются)
SP = "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
REF_TOP = 230
SHIFT = (0.0, 0.083)                                   # поправка времени расчёта: замер по тестам (ошибка 47 → 17 бит)
WORK = ROOT / "output" / "_work" / "onestate4_v3"
SEG = WORK / "seg"
CLEAN = WORK / "clean"                                 # исходники без повторов кадров (см. clean_src)
OUT = {"tt": ROOT / "output" / f"{NAME}_TT_200", "yt": ROOT / "output" / f"{NAME}_YT_200"}
REFS = [ROOT / "output" / "onestate_1310_TT_100_v2", ROOT / "output" / "onestate_1310_YT_100_v2"]
FONT = {"tt": "tiktok", "yt": "default"}
TABLE: dict = {}
SRC: dict = {}
STATIC: dict = {}                                      # исходник → [кадр 30 к/с без движения относительно следующего]


def vname(job: dict) -> str:
    return f"{NAME}_{job['tag']}_{job['n']:03d}_{ID}.mp4"


# ---------------- воркеры (шрифт задаётся ДО импорта build_1309_*: TT — TikTok Sans, YT — шрифты 1309) ----------------
_M: dict = {}


def _init_font(font: str) -> None:
    os.environ["OS1309_FONT"] = font
    import build_onestate4 as O
    O.FPS = FPS                                           # куски считаются в кадрах ролика (30 к/с)
    _M.update(O=O, B=O.B, DR=O.DR)


def _table() -> dict:
    """Высоты подписи/карточки и подпись в масштабе 1/8 — для расчёта кадров до рендера."""
    import tempfile
    O, B, DR = _M["O"], _M["B"], _M["DR"]
    tmp = Path(tempfile.mkdtemp(prefix="os4t_"))
    capoff, capA, cardh = {}, {}, {}
    for px in (44, 45, 46, 47, 48):
        B.CAP_TOP, B.CAP_PX = REF_TOP, px
        B.CAPTIONS = [DR.wrap_width(t, B.F_CAP, B.CAP_PX, B.X1 - B.X0) for t in O.CAPTIONS_RAW]
        for k in range(len(O.CAPTIONS_RAW)):
            bot = B.caption_png(k, tmp / "c.png")
            capoff[f"{k}_{px}"] = bot - REF_TOP
            a = Image.open(tmp / "c.png").getchannel("A").resize((W // Q, H // Q), Image.Resampling.BOX)
            capA[f"{k}_{px}"] = (np.asarray(a, np.float32) / 255).tolist()
    av = next(p for d in B.AVATAR_DIRS if d.is_dir() for p in sorted(d.glob("*.jpg")))
    for k in range(len(O.COMMENTS_RAW)):
        cardh[str(k)] = B.card_png(k, tuple(B.PEOPLE[0]), av, tmp / "k.png")
    shutil.rmtree(tmp, ignore_errors=True)
    return dict(capoff=capoff, capA=capA, cardh=cardh, card_bottom=B.CARD_BOTTOM)


def band(job: dict) -> tuple[int, int, int]:
    """(верх полосы геймплея, высота, верх карточки) — те же формулы, что при рендере (верх полосы чётный)."""
    T = TABLE[FONT[job["tag"]]]
    b0 = job["cap_top"] + T["capoff"][f"{job['caption']}_{job['cap_px']}"] + job["gap"]
    b0 += b0 % 2
    card_top = T["card_bottom"] - job["card_lift"] - T["cardh"][str(job["comment"])]
    bh = card_top - job["gap"] - b0
    return b0, bh - bh % 2, card_top


def src_rect(p: dict, bh: int) -> tuple[float, float, float, float]:
    """Окно исходника для куска: «заполнить полосу» с зумом z от центра (ox/oy 0.44–0.56)."""
    s = max(W * p["z"] / SW, bh * p["z"] / SH)
    cw, ch = W / s, bh / s
    return (SW - cw) * p["ox"], (SH - ch) * p["oy"], cw, ch


def shade_field(seed: int, w: int, h: int) -> np.ndarray:
    """Мягкие волны освещения (как Skinive 2): v<0 — светлее (белый), v>0 — темнее (чёрный), сила |v|·AMP."""
    rng = random.Random(seed)
    x = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    ph = (rng.uniform(0, 6.28) + y * rng.uniform(-6, 6)
          + np.sin(y * rng.uniform(2, 5) + rng.uniform(0, 6.28)) * rng.uniform(0.5, 1.5))
    return (0.6 * np.sin(2 * math.pi * rng.uniform(1.2, 2.6) * x + ph)
            + 0.4 * np.sin(2 * math.pi * rng.uniform(2.5, 4.5) * x + ph * 1.7 + rng.uniform(0, 6.28)))


# ---------------- рендер (видеокарта) ----------------
def _cuvid(p: dict, bh: int) -> list:
    """Распаковка на видеокарте с обрезкой и масштабом прямо в распаковщике; кадры — в ОБЫЧНУЮ память.
    MAIN 2026-11-13 (diag_gpu_frames.py): если кадры cuvid оставить на видеокарте и гнать через trim/fps/tpad/склейку,
    распаковщик переиспользует свою память — в ролик попадают чужие кадры (сдвиг 3–8 = «фризы/лаги») и мусор (зелёные)."""
    x, y, cw, ch = src_rect(p, bh)
    x, y, cw, ch = (G._even(v) for v in (x, y, cw, ch))
    return ["-c:v", "h264_cuvid", "-crop", f"{y}x{SH - y - ch}x{x}x{SW - x - cw}", "-resize", f"{W}x{bh}", "-i", p["seg"]]


class _Res:
    def __init__(self, code: int, err: str):
        self.returncode, self.stderr = code, err


def _run_ff(cmd: list, errf: Path, timeout: float = 120) -> _Res:
    """ffmpeg без каналов (stderr в файл, stdin закрыт): зависшую сборку на видеокарте прерываем и не ждём бесконечно."""
    with open(errf, "w", encoding="utf-8", errors="replace") as fe:
        pr = subprocess.Popen(cmd[:1] + ["-nostdin"] + cmd[1:], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=fe)
        try:
            code = pr.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pr.kill()
            try:
                pr.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass                                    # процесс застрял в драйвере — бросаем и собираем заново
            code = -9
    err = errf.read_text(encoding="utf-8", errors="replace")
    if code == -9:
        err += f"{chr(10)}timeout {timeout:.0f} s"
    return _Res(code, err)


def build(job: dict) -> str:
    import tempfile
    from core.gpu_slots import gpu_slot
    O, B, DR = _M["O"], _M["B"], _M["DR"]
    tmp = Path(tempfile.mkdtemp(prefix="os4v3_"))
    rng = random.Random(job["seed"])
    B.CAP_TOP, B.CAP_PX = job["cap_top"], job["cap_px"]
    B.CAPTIONS = [DR.wrap_width(t, B.F_CAP, B.CAP_PX, B.X1 - B.X0) for t in O.CAPTIONS_RAW]
    cap_bottom = B.caption_png(job["caption"], tmp / "cap.png")
    card_h = B.card_png(job["comment"], tuple(job["person"]), Path(job["avatar"]), tmp / "card.png")
    b0 = cap_bottom + job["gap"]
    b0 += b0 % 2
    card_top = B.CARD_BOTTOM - job["card_lift"] - card_h
    bh = card_top - job["gap"] - b0
    bh -= bh % 2
    if (b0, bh) != tuple(job["band"][:2]):
        raise RuntimeError(f"{vname(job)}: полоса {b0},{bh} ≠ плану {job['band']}")
    bgv, tint = job["bg"], job["tint"]
    bgc = f"0x{bgv:02X}{min(255, bgv + tint):02X}{min(255, bgv - tint):02X}"
    lx, ly, _ = B.logo_png(rng, (b0, b0 + bh), tmp / "logo.png")
    v = shade_field(job["shade"], W, H)[b0:b0 + bh]
    lay = np.zeros((H, W, 4), np.uint8)
    lay[b0:b0 + bh, :, :3] = np.where(v < 0, 255, 0)[..., None]
    lay[b0:b0 + bh, :, 3] = (np.abs(v) * SHADE_AMP * 255).astype(np.uint8)
    layer = Image.fromarray(lay, "RGBA")
    layer.alpha_composite(Image.open(tmp / "logo.png").convert("RGBA"), (lx, ly))
    layer.alpha_composite(Image.open(tmp / "cap.png").convert("RGBA"))
    layer.alpha_composite(Image.open(tmp / "card.png").convert("RGBA"), (0, card_top))
    layer.save(tmp / "layer.png", compress_level=1)
    cw_, ch_ = B.banner_anim()
    bx = G._even((W - cw_) // 2)
    by = G._even(b0 + bh - 16 - ch_ + round(ch_ * 0.06))

    # Видеоряд: распаковка cuvid (обрезка/масштаб) → кадры в обычной памяти → trim/скорость/fps/склейка обычными
    # фильтрами → ОДИН hwupload_cuda → поверх ровного фона (overlay_cuda), слои и баннер — overlay_cuda, NVENC.
    ins = ["-i", str(tmp / "layer.png"), "-i", str(B.BANNER_ANIM), "-i", str(O.MUSIC),
           "-f", "lavfi", "-i", f"color=c={bgc}:s={W}x{H}:r={FPS}:d={TOTAL}"]
    fc = [G.layer(0, 0, NF, "ly", FPS).replace("format=yuva420p,hwupload_cuda", f"format=yuva420p,{SP},hwupload_cuda"),
          f"[1:v]fps={FPS},format=yuva420p,{SP},hwupload_cuda,setpts=PTS-STARTPTS+{O.BANNER_T:.3f}/TB[bn]",
          f"[3:v]format=yuv420p,{SP},hwupload_cuda[c]"]
    for j, p in enumerate(job["pieces"]):
        ins += _cuvid(p, bh)
        src = p["frames"] / FPS * p["speed"]
        fc.append(f"[{4 + j}:v]setpts=PTS-STARTPTS,trim=start={p['a'] - p['seg_t0']:.3f}:duration={src + 0.08:.3f},"
                  f"setpts=(PTS-STARTPTS)/{p['speed']},fps={FPS},setsar=1,format=yuv420p,"
                  f"tpad=stop_mode=clone:stop=4,trim=end_frame={p['frames']},setpts=PTS-STARTPTS[p{j}]")
    n = len(job["pieces"])
    fc += ["".join(f"[p{j}]" for j in range(n)) + f"concat=n={n}:v=1:a=0,{SP},hwupload_cuda[g]",
           f"[c][g]overlay_cuda=0:{b0}[gg]"]
    cur = "gg"
    fc += [f"[{cur}][ly]overlay_cuda=0:0[d]",
           f"[d][bn]overlay_cuda={bx}:{by}:eof_action=pass[v]",
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
            if "Invalid argument" in r.stderr and attempt == 0:      # ошибка графа — повтор не поможет
                (WORK / f"fail_{dest.stem}.txt").write_text(subprocess.list2cmdline(cmd) + 2 * chr(10) + r.stderr, encoding="utf-8")
                raise RuntimeError(f"{dest.name}: {r.stderr[-600:]}")
            if attempt == 2:
                (WORK / f"fail_{dest.stem}.txt").write_text(subprocess.list2cmdline(cmd) + 2 * chr(10) + r.stderr, encoding="utf-8")
                raise RuntimeError(f"{dest.name}: {r.stderr[-600:]}")
            time.sleep(3)
    shutil.rmtree(tmp, ignore_errors=True)
    return dest.name


# ---------------- исходники для расчёта до рендера ----------------
def segments(win: list, hooks: list) -> dict:
    """Экшн-окна и начала — короткие h264-заготовки (на видеокарте нельзя -ss); сцены 1309 — свои файлы целиком."""
    segs = {}
    for w in win:
        if w.get("action"):
            segs[f"act_{w['m']}"] = (w["path"], w["base"], w["base"] + w["dur"] + 0.1, 30)
    for i, (hp, hs, he, _) in enumerate(hooks):
        segs[f"hook_{i}"] = (str(hp), max(0.0, hs - 0.15), he + 0.35, 60 if "Parkour" in str(hp) else 30)
    return segs


def cut_all(segs: dict, scenes: list[str]) -> dict:
    """Заготовки + чистые копии; возвращает {путь чистой копии: K/fps}."""
    def one(kv):
        k, (src, t0, t1, fps) = kv
        G.cut_segment(Path(src), t0, t1, SEG / f"{k}.mp4", fps)
        return str(CLEAN / f"{k}.mp4"), clean_src(SEG / f"{k}.mp4", CLEAN / f"{k}.mp4")
    with ThreadPoolExecutor(4) as ex:
        meta = dict(ex.map(one, segs.items()))
        meta.update(ex.map(lambda f: (str(CLEAN / f"scn_{Path(f).stem}.mp4"),
                                      clean_src(Path(f), CLEAN / f"scn_{Path(f).stem}.mp4")), scenes))
    return meta


def cut_raw(segs: dict) -> None:
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda kv: G.cut_segment(Path(kv[1][0]), kv[1][1], kv[1][2], SEG / f"{kv[0]}.mp4", kv[1][3]),
                    segs.items()))


def clean_windows(win: list, hooks: list, segs: dict, meta: dict) -> tuple[list, list]:
    """Окна/начала → время чистых копий: seg — файл, base/a — от его начала."""
    w2 = []
    for w in win:
        if w.get("action"):
            cp = str(CLEAN / f"act_{w['m']}.mp4")
            m = meta[cp]
            w2.append(dict(w, base=0.0, dur=round(remap(m, w["dur"]), 3), seg=cp))
        else:
            cp = str(CLEAN / f"scn_{Path(w['file']).stem}.mp4")
            m = meta[cp]
            w2.append(dict(w, dur=round(len(m["K"]) / m["fps"], 3), peak=round(remap(m, w["peak"]), 3), seg=cp))
    h2 = []
    for i, (hp, hs, he, desc) in enumerate(hooks):
        cp = str(CLEAN / f"hook_{i}.mp4")
        m, t0 = meta[cp], segs[f"hook_{i}"][1]
        h2.append((cp, round(remap(m, hs - t0), 3), round(remap(m, he - t0), 3), desc))
    return w2, h2


def clean_src(src: Path, dest: Path) -> dict:
    """Юзер 2026-11-13: «фризит… исходники не были такими». В записях OneState 3 (30 к/с) ~4–7 % кадров — точные
    повторы предыдущего (сбой записи: Army 7 из 168 уже в оригинале 2560×1440, прокси и вырезка добавили ещё). При
    ускорении в ролике 60 к/с каждый такой повтор — подвисание на быстром движении. Один раз на исходник: выкидываем
    только ТОЧНЫЕ повторы (средняя разница с предыдущим оставленным < 0.12 на 480×270), частота прежняя.
    Возвращает K — время оставленных кадров в исходнике (для пересчёта отрезков) и частоту."""
    side = dest.with_suffix(".json")
    if dest.exists() and side.exists():
        return json.loads(side.read_text(encoding="utf-8"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    rate = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                           "-of", "csv=p=0", str(src)], capture_output=True, text=True).stdout.strip()
    num, den = rate.split("/")
    fps = round(int(num) / int(den))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vf", "scale=480:270,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, np.uint8).reshape(-1, 270, 480)[:, :256].astype(np.int16)
    keep, last = [0], a[0]
    for i in range(1, len(a)):
        if np.abs(a[i] - last).mean() >= 0.12:
            keep.append(i)
            last = a[i]
    ks = set(keep)
    fs = SW * SH * 3 // 2
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(src), "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{SW}x{SH}",
                            "-r", str(fps), "-i", "-", "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "16",
                            "-g", "15", "-an", "-map_metadata", "-1", str(dest)], stdin=subprocess.PIPE)
    for i in range(len(a)):
        buf = dec.stdout.read(fs)
        if len(buf) < fs:
            break
        if i in ks:
            enc.stdin.write(buf)
    dec.stdout.close()
    dec.wait()
    enc.stdin.close()
    enc.wait()
    meta = dict(K=[i / fps for i in keep], fps=fps, n=len(a))
    side.write_text(json.dumps(meta), encoding="utf-8")
    return meta


def remap(meta: dict, t: float) -> float:
    """Время в исходнике → время в «чистой» копии (кадры без движения выкинуты)."""
    return float(np.searchsorted(np.asarray(meta["K"]), t - 1e-6)) / meta["fps"]


def src_cache(files: list[str]) -> None:
    f = WORK / "src_cache.npz"
    if f.exists():
        d = np.load(f, allow_pickle=True)["d"].item()
        SRC.update(d)
    todo = [p for p in files if p not in SRC]

    def one(p):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-vf", f"fps={CFPS},scale={CW}:{CH}:flags=area,format=gray",
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        return p, np.frombuffer(raw, np.uint8).reshape(-1, CH, CW)
    if todo:
        with ThreadPoolExecutor(8) as ex:
            for p, a in ex.map(one, todo):
                SRC[p] = a
        np.savez(f, d=np.array(dict(SRC), dtype=object))
    for p, a in SRC.items():
        STATIC[p] = np.abs(np.diff(a.astype(np.int16), axis=0)).mean((1, 2)) < 0.4


def predict(job: dict) -> tuple[np.ndarray, np.ndarray]:
    """dHash 16×16 полосы STRIP на 6 к/с — как core.uniq_check, без рендера (кадр 135×240)."""
    b0, bh, _ = job["band"]
    T = TABLE[FONT[job["tag"]]]
    capA = np.roll(np.asarray(T["capA"][f"{job['caption']}_{job['cap_px']}"], np.float32), round((job["cap_top"] - REF_TOP) / Q), 0)
    r0, rh = round(b0 / Q), max(1, round(bh / Q))
    v = shade_field(job["shade"], W // Q, H // Q)[r0:r0 + rh]
    sa = np.abs(v) * SHADE_AMP
    sc = np.where(v < 0, 255.0, 0.0)
    starts = np.cumsum([0] + [p["frames"] for p in job["pieces"]])
    out, mir = [], []
    for i in range(round(TOTAL * HFPS)):
        f = round(i * FPS / HFPS)
        j = min(int(np.searchsorted(starts, f, side="right")) - 1, len(job["pieces"]) - 1)
        p = job["pieces"][j]
        arr = SRC[p["seg"]]
        # сдвиг 0.017 + 0.05·скорость с — замер по тестам (сборка на видеокарте берёт кадр исходника чуть позже)
        k = min(len(arr) - 1, max(0, round(((p["a"] - p["seg_t0"]) + SHIFT[0] + SHIFT[1] * p["speed"]
                                            + (f - starts[j]) / FPS * p["speed"]) * CFPS)))
        x, y, cw, ch = src_rect(p, bh)
        im = Image.fromarray(arr[k]).resize((W // Q, rh), Image.Resampling.BILINEAR,
                                            box=(x / Q, y / Q, (x + cw) / Q, (y + ch) / Q))
        cv = np.full((H // Q, W // Q), float(job["bg"]), np.float32)
        g = np.asarray(im, np.float32)
        cv[r0:r0 + rh] = g[:H // Q - r0] * (1 - sa) + sc * sa
        cv = cv * (1 - capA)
        s = cv[STRIP[0] // Q:STRIP[1] // Q]
        h = np.asarray(Image.fromarray(np.clip(s, 0, 255).astype(np.uint8)).resize((17, 16), Image.Resampling.BOX)).astype(np.int16)
        out.append((h[:, 1:] > h[:, :-1]).ravel())
        hm = h[:, ::-1]
        mir.append((hm[:, 1:] > hm[:, :-1]).ravel())
    return np.array(out, np.float32), np.array(mir, np.float32)


# ---------------- план ----------------
HOOK30: set = set()
HOOK_FAM: dict = {}                                    # начало → исходное видео (Parkour_1080 / файл OneState 3)


def family(w: dict) -> str:
    """Исходное видео окна: сцены 1309 — Interaction / Interaction2 / Paired; экшн — файл OneState 3."""
    return Path(w["path"]).stem if w.get("action") else w["file"].split("_")[0]


def candidate(rng: random.Random, win: list, hooks: list, hook_use: dict, O) -> dict | None:
    k = rng.choice((5, 5, 6))
    lo = min(hook_use.get(h, 0) for h in range(len(hooks)))
    hi = rng.choice([h for h in range(len(hooks)) if hook_use.get(h, 0) <= lo + 2])
    hp, hs0, he, _ = hooks[hi]
    src30 = "hook_" in str(hp) and int(Path(hp).stem.split("_")[1]) in HOOK30   # OneState 3 — записи 30 к/с
    # «ФРИЗ» (юзер 2026-11-13): запись 30 к/с медленнее ×2 в ролике 60 к/с = кадр повторяется через раз — на слежении
    # камеры это видно как подвисания. 30 к/с → ровно ×2 (каждый кадр ролика — новый кадр записи); 60 к/с → ×1.3–1.8
    hsp = 2.0 if src30 else 1.5                           # ровный шаг: 30 к/с → каждый 2-й кадр, 60 к/с → каждый 3-й
    hs = max(0.0, hs0 + rng.uniform(-0.08, 0.12))
    hf = round(min(he - hs, 1.25) / hsp * FPS)
    hook = dict(m=200 + hi, id=2000 + hi, file=Path(hp).name, path=str(hp), a=round(hs, 3), speed=hsp, frames=hf,
                action=True, hook=hi, seg=str(hp), seg_t0=0.0)
    rest_total = TOTAL - hf / FPS
    lens = [rng.uniform(0.9, 1.6) for _ in range(k - 1)]
    lens = [x * rest_total / sum(lens) for x in lens]
    fr = [round(x * FPS) for x in lens]
    fr[-1] = NF - hf - sum(fr[:-1])
    fr = [hf] + fr
    if min(fr[1:]) < 0.7 * FPS or hf < 0.55 * FPS:
        return None
    na = rng.choice((2, 3)) if k == 5 else 3
    for _t in range(50):
        rest = ["A"] * (na - 1) + ["S"] * (k - na)
        rng.shuffle(rest)
        types = ["A"] + rest
        if all(not (x == y == "A") for x, y in zip(types, types[1:])):
            break
    pieces = [hook]
    # юзер 2026-11-13: «резкие срывы кадров одного и того же видео — неочень» → в ролике каждое исходное видео
    # не больше одного раза (никаких склеек двух моментов одной записи)
    used = {HOOK_FAM.get(hi, "")}
    for i in range(1, len(fr)):
        L = fr[i]
        pool_i = [w for w in win if bool(w.get("action")) == (types[i] == "A")]
        cand = [w for w in pool_i if w["m"] not in {p["m"] for p in pieces} and w["dur"] >= L / FPS * 2.0 + 0.05
                and family(w) not in used]
        if not cand:
            return None
        w = rng.choice(cand)
        used.add(family(w))
        pc = O.piece(rng, w, L / FPS, False)
        pc.update(seg=w["seg"], seg_t0=0.0)              # чистые копии: время от их начала (base = 0)
        lim0, lim1 = w.get("base", 0.0) if w.get("action") else 0.0, (w.get("base", 0.0) if w.get("action") else 0.0) + w["dur"]
        sfps = 30 if w.get("action") else 60
        ok = [x for x in SPEEDS[sfps] if pc["frames"] / FPS * x <= (lim1 - lim0) - 0.15]
        if not ok:
            return None
        pc["speed"] = rng.choice(ok)
        src = pc["frames"] / FPS * pc["speed"]
        if pc["a"] + src > lim1 - 0.1:                    # запас в конце: иначе tpad держит последний кадр = стоп-кадр
            pc["a"] = round(max(lim0, lim1 - src - 0.1), 3)
        if pc["speed"] < 2.0 or pc["a"] + src > lim1 - 0.02:
            return None
        pieces.append(pc)
    for pc in pieces:                                     # «фриз»: в куске не должно быть ≥ 2 кадров записи подряд без движения
        s0 = pc["a"] - pc["seg_t0"]
        st = STATIC.get(pc["seg"])
        if st is not None:
            m = st[int(s0 * CFPS):int((s0 + pc["frames"] / FPS * pc["speed"]) * CFPS) + 1]
            if (m[1:] & m[:-1]).any():
                return None
    for j, pc in enumerate(pieces):
        pc.update(z=round(rng.uniform(1.05 if j == 0 else 1.0, 1.4), 3), ox=round(rng.uniform(0.44, 0.56), 3),
                  oy=round(rng.uniform(0.42, 0.58), 3))
    return dict(hook=hi, pieces=pieces)


def make_job(n: int, tag: str, rng: random.Random, win: list, hooks: list, hook_use: dict, avatars: list, O) -> dict | None:
    c = None
    for _ in range(80):
        c = candidate(rng, win, hooks, hook_use, O)
        if c:
            break
    if not c:
        return None
    B = O.B
    job = dict(n=n, tag=tag, caption=rng.randrange(len(O.CAPTIONS_RAW)), comment=rng.randrange(len(O.COMMENTS_RAW)),
               pieces=c["pieces"], hook=c["hook"], person=list(B.PEOPLE[rng.randrange(len(B.PEOPLE))]),
               avatar=str(rng.choice(avatars)), seed=rng.randrange(10 ** 9), shade=rng.randrange(10 ** 9),
               cap_top=rng.randint(206, 262), cap_px=rng.choice((44, 45, 46, 47, 48)), gap=rng.randint(24, 46),
               card_lift=rng.randint(0, 70), bg=rng.choice((255, 254, 253, 252, 251)),
               tint=rng.choice((0, 0, 1, -1, 2, -2)), pitch=round(rng.uniform(0.975, 1.025), 4))
    job["band"] = list(band(job))
    job["dest"] = str(OUT[tag] / vname(job))
    return job


class Bank:
    """Принятые кадры (видеокарта): обычные + зеркальные; расстояние кандидата — минимум по всем."""

    def __init__(self):
        import torch
        self.t = torch
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        self.A = torch.zeros((0, 256), device=self.dev)
        self.M = torch.zeros((0, 256), device=self.dev)

    def add(self, h: np.ndarray, m: np.ndarray) -> None:
        t = self.t
        h = t.tensor(np.asarray(h, np.float32), device=self.dev)
        m = t.tensor(np.asarray(m, np.float32), device=self.dev)
        self.A, self.M = t.cat([self.A, h]), t.cat([self.M, m])

    def copy(self) -> "Bank":
        b = Bank.__new__(Bank)
        b.t, b.dev, b.A, b.M = self.t, self.dev, self.A.clone(), self.M.clone()
        return b

    def dist(self, c: np.ndarray) -> float:
        if not len(self.A):
            return 256.0
        c = self.t.tensor(np.asarray(c, np.float32), device=self.dev)
        sc = c.sum(1)[:, None]
        d1 = sc + self.A.sum(1)[None] - 2 * c @ self.A.T
        d2 = sc + self.M.sum(1)[None] - 2 * c @ self.M.T
        return float(min(d1.min(), d2.min()))


def plan_jobs(slots: list[tuple[str, int]], bank: "Bank", rng: random.Random, win, hooks, hook_use, avatars, O,
              tries: int, label: str, fixed: dict | None = None) -> list[dict]:
    jobs, worst, t0 = [], [], time.time()
    for k, (tag, n) in enumerate(slots, 1):
        best = None
        if fixed and (tag, n) in fixed:                   # одобренные тесты — в план как есть
            j = fixed[(tag, n)]
            Hh, Mm = predict(j)
            best = (bank.dist(Hh), j, Hh, Mm)
        for _ in range(0 if best else tries):
            j = make_job(n, tag, rng, win, hooks, hook_use, avatars, O)
            if j is None or j["band"][0] > STRIP[1] - 200:
                continue
            Hh, Mm = predict(j)
            d = bank.dist(Hh)
            if best is None or d > best[0]:
                best = (d, j, Hh, Mm)
            if d > PLAN_THR:
                break
        d, j, Hh, Mm = best
        bank.add(Hh, Mm)
        hook_use[j["hook"]] = hook_use.get(j["hook"], 0) + 1
        jobs.append(j)
        worst.append(d)
        if k % 25 == 0:
            print(f"  {label}: {k}/{len(slots)}, у последнего ближайший чужой кадр {d:.0f} бит, {time.time() - t0:.0f} с", flush=True)
    w = sorted(worst)
    print(f"{label}: {len(jobs)} роликов; ближайший чужой кадр — минимум {w[0]:.0f} бит, медиана {w[len(w) // 2]:.0f}; "
          f"≤ {THR} бит: {sum(x <= THR for x in w)}", flush=True)
    return jobs


# ---------------- приёмка по настоящим файлам ----------------
def real_hash(path: Path) -> np.ndarray:
    return np.concatenate([vhash(path, [STRIP], 6), vhash(path, [STRIP], 3)])        # (кадры, 2, 256)


def render_accept(jobs: list[dict], bank: Bank, pools: dict, ctx: dict, wave: int = 12, max_fail: int = 6) -> None:
    """Рендер волнами; ролик попадает в папку, только если ни один его кадр (6 и 3 к/с) не ближе THR к принятым."""
    q = list(jobs)
    fails: dict = {}
    done, rej, t0 = 0, 0, time.time()
    cand_dir = WORK / f"cand_{os.getpid()}"                  # своя папка на запуск: файл зависшего ffmpeg может быть занят
    while q:
        cur, q = q[:wave], q[wave:]
        for j in cur:
            j["final"] = j.get("final") or j["dest"]
            j["dest"] = str(cand_dir / f"{j['tag']}_{j['n']:03d}_{fails.get((j['tag'], j['n']), 0)}.mp4")
        futs = [pools[j["tag"]].submit(build, j) for j in cur]
        for f in futs:
            f.result()
        with ThreadPoolExecutor(8) as ex:
            hs = list(ex.map(lambda j: real_hash(Path(j["dest"])), cur))
        for j, h in zip(cur, hs):
            d = bank.dist(h[:, 0])
            key = (j["tag"], j["n"])
            if d > THR:
                bank.add(h[:, 0], h[:, 1])
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
                    raise SystemExit(f"{vname(j)}: {max_fail} вариантов подряд совпадают — нужен шире разброс")
                nj = plan_jobs([key], bank.copy(), ctx["rng"], ctx["win"], ctx["hooks"], ctx["hook_use"],
                               ctx["avatars"], ctx["O"], ctx["tries"], f"  замена {vname(j)}")[0]
                if ctx.get("test_dir"):
                    nj["dest"] = str(ctx["test_dir"] / vname(nj))
                q.append(nj)
        print(f"  принято {done}, заменено {rej}, {time.time() - t0:.0f} с", flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--prep", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--seed", type=int, default=71309)
    ap.add_argument("--tries", type=int, default=120)
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    _init_font("default")
    O, B = _M["O"], _M["B"]
    import build_onestate4_uniq as U
    B.banner_anim()
    O.music()
    win, _ = O.pool()
    win = [w for w in win if not (w.get("action") and w["file"].startswith("Police_job_fight") and w["base"] > 4)]
    hooks = U.HOOKS
    avatars = [p for d in B.AVATAR_DIRS if d.is_dir() for p in sorted(d.glob("*.jpg")) if not p.name.startswith("_")]
    segs = segments(win, hooks)
    scenes = sorted({str(B.SCENES / w["file"]) for w in win if not w.get("action")})
    t0 = time.time()
    meta = cut_all(segs, scenes)
    HOOK30.update(i for i, h in enumerate(hooks) if "Parkour" not in str(h[0]))
    HOOK_FAM.update({i: Path(h[0]).stem for i, h in enumerate(hooks)})
    win, hooks = clean_windows(win, hooks, segs, meta)
    files = sorted(meta)
    src_cache(files)
    print(f"исходники: {len(files)} файлов, {time.time() - t0:.0f} с", flush=True)
    pools = {}
    for tag in ("tt", "yt"):
        pools[tag] = ProcessPoolExecutor(a.jobs, initializer=_init_font, initargs=(FONT[tag],))
    tf = WORK / "layout.json"
    if tf.exists():
        TABLE.update(json.loads(tf.read_text(encoding="utf-8")))
    else:
        for tag in ("tt", "yt"):
            TABLE[FONT[tag]] = pools[tag].submit(_table).result()
        tf.write_text(json.dumps(TABLE), encoding="utf-8")
    refs = [f for d in REFS if d.exists() for f in sorted(d.glob("*.mp4"))]
    R6 = hashes(refs, [STRIP], 6, WORK / "refs6.npz")
    R3 = hashes(refs, [STRIP], 3, WORK / "refs3.npz")
    bank = Bank()
    for f in refs:
        for R in (R6, R3):
            bank.add(R[str(f)][:, 0], R[str(f)][:, 1])
    print(f"1310_v2: {len(refs)} роликов в сравнении", flush=True)
    rng = random.Random(a.seed)
    hook_use: dict = {}
    pf = WORK / f"plan_{a.seed}.json"
    if pf.exists():
        jobs = json.loads(pf.read_text(encoding="utf-8"))
    else:
        slots = [(tag, n) for n in range(1, 201) for tag in ("tt", "yt")]
        if a.test:                                        # план детерминирован: первые 6 слотов = те же, что в полном
            slots = slots[:6]
        tjf = WORK / "test_jobs.json"
        fixed = {(j["tag"], j["n"]): dict(j, dest=str(OUT[j["tag"]] / vname(j)))
                 for j in json.loads(tjf.read_text(encoding="utf-8"))} if tjf.exists() and not a.test else None
        jobs = plan_jobs(slots, bank.copy(), rng, win, hooks, hook_use, avatars, O, a.tries, "план", fixed)
        if not a.test:
            pf.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
        hook_use.clear()
    for j in jobs:
        hook_use[j["hook"]] = hook_use.get(j["hook"], 0) + 1
    if a.prep:
        return 0
    ctx = dict(accepted=[], rng=random.Random(a.seed + 7), win=win, hooks=hooks, hook_use=hook_use, avatars=avatars,
               O=O, tries=a.tries)

    if a.test:
        ctx["test_dir"] = WORK / "test"
        tj = [dict(j, dest=str(WORK / "test" / vname(j))) for j in jobs if j["n"] <= 3]
        for j in tj:
            j["final"] = j["dest"]
        render_accept(tj, bank, pools, ctx)
        (WORK / "test_jobs.json").write_text(json.dumps(ctx["accepted"], ensure_ascii=False), encoding="utf-8")
        err = []
        for j in ctx["accepted"]:
            p = predict(j)[0]
            r = vhash(Path(j["dest"]), [STRIP], 6)[:, 0].astype(np.float32)
            m = min(len(p), len(r))
            err.append(np.abs(p[:m] - r[:m]).sum(1))
        e = np.concatenate(err)
        print(f"ТЕСТ: {len(ctx['accepted'])} роликов; ошибка расчёта до рендера, бит на кадр: среднее {e.mean():.1f}, "
              f"95 % {np.percentile(e, 95):.0f}", flush=True)
        return 0
    todo = [j for j in jobs if not Path(j["dest"]).exists()]
    for j in jobs:
        if Path(j["dest"]).exists():
            h = real_hash(Path(j["dest"]))
            bank.add(h[:, 0], h[:, 1])
    render_accept(todo, bank, pools, ctx)
    (WORK / "accepted.json").write_text(json.dumps(ctx["accepted"], ensure_ascii=False), encoding="utf-8")
    final = [OUT[j["tag"]] / vname(j) for j in jobs]
    from core.uniq_check import similarity
    for fps in (6, 3):
        pair, vs = similarity([f for f in final if f.exists()], refs, strips=[STRIP], fps=fps, thr=THR,
                              cache=WORK / f"final{fps}.npz")
        tri = pair[np.triu_indices(len(pair), 1)]
        print(f"ПРОВЕРКА ({fps} к/с, полоса {STRIP[0]}–{STRIP[1]}, порог {THR}): худшая пара {tri.max() * 100:.1f} %, "
              f"пар с общими кадрами {int((tri > 0).sum())} из {len(tri)}; с 1310_v2 худшая {vs.max() * 100:.1f} %", flush=True)
    for p in pools.values():
        p.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
