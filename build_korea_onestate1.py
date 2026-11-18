#!/usr/bin/env python3
"""
Korea OneState 1 (ID 1) — нарезка корейских стримеров (Dropbox STATEDQVH → downloads/korea_onestate1/src, 20 моментов
×48–60 с, 1080×1920) на ролики 15–25 с: 100 TT + 100 YT. Юзер 16.11: «везде должна быть плашка игры с кодом видна»,
«схожесть 0–1 %».

  • Отрезок — один непрерывный кусок момента, начало и конец — в паузах речи (фраза не обрывается), скорость 1, звук
    стримера как есть (без смены тона — речь и губы в синхроне).
  • Плашка «쿠폰 코드 STATEDQVH» (вырезана из чистого чёрного кадра, output/_work/korea1/plate_STATEDQVH.png) — на
    ВСЁ время ролика, ровно на месте плашки исходника и в её масштабе (накрывает её; видна и там, где в исходнике её нет).
  • Уникальность (1100 с исходника на 4000 с роликов): у каждого ролика своё кадрирование — приближение 1.0–1.3 от
    центра плашки (плашка остаётся на месте, наша — того же размера поверх), сдвиг по горизонтали, мягкие волны
    света ±10 %. План на видеокарте (core/uniq_fast: прогноз отпечатков полосы ниже плашки), приёмка КАЖДОГО кадра
    готового файла (порог 40 из 256) против всех принятых + пустые/зелёные/фризы.
  Видеокарта по CLAUDE.md: h264_cuvid -crop -resize с -ss → кадры в памяти → слои overlay в памяти → NVENC.

  python build_korea_onestate1.py --test           # 4 ролика → output/_work/korea1/test
  python build_korea_onestate1.py --tt 100 --yt 100
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
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import gpu_ffmpeg as G  # noqa: E402
from core import uniq_fast as UF  # noqa: E402

W, H, FPS = 1080, 1920, 30
SRC = ROOT / "downloads" / "korea_onestate1" / "src"
WORK = ROOT / "output" / "_work" / "korea1"
SEGD = WORK / "seg"
PLATE = WORK / "plate_STATEDQVH.png"
PX, PY = 259, 192                                       # плашка исходника: левый верх, размер 562×145
PCX, PCY = PX + 281, PY + 72                            # её центр — точка приближения
STRIP = (400, 1900)                                     # проверка: всё ниже плашки
HFPS, THR = 6, 44                                    # приёмка с запасом к порогу итоговой проверки 40
PLAN_THR = THR + 10
SHADE_AMP = 0.10
NAME = "korea_onestate_1"
PROG = ROOT / "output" / "_work" / "_qa_progress" / f"{os.getpid()}.json"
UF.CW, UF.CH = 135, 240                                  # кадры исходников вертикальные; 135×240 — план 200 роликов
# влезает в видеопамять (270×480 × 33 000 кадров = 8.5 ГБ → память гонялась через обычную, 16.11)
SEG: dict = {}
UST = None
# 17.11 (вторая партия 100+100): в первые ~3.4 с — мем по смыслу момента стикером с «бумом» (как в Drops),
# make_korea_meme_stickers.py → downloads/korea_onestate1/memes/sticker/<s1_m01>.mov; звук бума — Drops sfx_ref/meme
MEMES = False
STK = ROOT / "downloads" / "korea_onestate1" / "memes" / "sticker"
BOOMS = sorted((ROOT / "downloads" / "drops_beats" / "sfx_ref" / "meme").glob("*.wav"))
MEME_T0 = 0.1                                            # стикер появляется на 0.1 с и держится 3.4 с


def meme_key(moment: str) -> str:
    """Streamer_01_Moment_03 → s1_m03."""
    _s, a, _m, b = moment.split("_")
    return f"s{int(a)}_m{int(b):02d}"


def meme_box(j: dict) -> tuple[int, int, int, int, int, int]:
    """Где стикер в кадре ролика: (x, y, w, h, кадр от, кадр до); размер — с масштабом j["ms"]."""
    meta = json.loads((STK / "_meta.json").read_text(encoding="utf-8"))[j["meme"]]
    w, h = G._even(meta["w"] * j.get("ms", 1.0)), G._even(meta["h"] * j.get("ms", 1.0))
    f0 = round(MEME_T0 * FPS)
    return G._even(j["mcx"] - w / 2), G._even(j["mcy"] - h / 2), w, h, f0, f0 + meta["frames"]


def text_rows(j: dict) -> np.ndarray:
    """Где в первых 3.6 с ролика вшитые субтитры: доля «текстовых» пикселей (очень светлые + резкий контраст с
    окрестностью) по строкам кадра ролика 1920, по центральной полосе x 160–920."""
    x0, y0, cw, ch = crop_of(j)
    m = SEG[j["moment"]]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{j['t0']:.3f}", "-t", "3.6", "-i", m["path"], "-vf",
                          f"fps=5,crop={cw}:{ch}:{x0}:{y0},scale=270:480,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, np.uint8).reshape(-1, 480, 270).astype(np.float32)
    if not len(a):
        return np.zeros(H, np.float32)
    from scipy.ndimage import uniform_filter
    loc = uniform_filter(a, size=(1, 7, 7))
    txt = ((a > 205) & (a - loc > 45)).astype(np.float32)[:, :, 40:230]
    row = txt.mean((0, 2))
    return np.repeat(row, 4)[:H]


def plates_seen(j: dict) -> list[tuple[int, int, int, int]]:
    """17.11: разметка плашки (TRACK) знала не все её места — в 4 роликах из 200 мем лёг на плашку посередине
    кадра. Ищем плашку прямо в кадрах первых 3.6 с ролика (шаблон, масштабы 1.0–1.35): (x, y, w, h) в кадре ролика."""
    import cv2
    x0, y0, cw, ch = crop_of(j)
    m = SEG[j["moment"]]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{j['t0']:.3f}", "-t", "3.7", "-i", m["path"], "-vf",
                          f"fps=10,crop={cw}:{ch}:{x0}:{y0},scale=540:960,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 960, 540)
    tg = np.asarray(Image.open(PLATE).convert("L"))
    out = set()
    for f in fr:
        best = (0.0, None)
        for sc in (0.8, 0.9, 1.0, 1.08, 1.16, 1.24, 1.32):
            t = cv2.resize(tg, (int(281 * sc), int(72 * sc)), interpolation=cv2.INTER_AREA)
            r = cv2.matchTemplate(f, t, cv2.TM_CCOEFF_NORMED)
            _mn, mx, _l, loc = cv2.minMaxLoc(r)
            if mx > best[0]:
                best = (mx, (loc[0] * 2, loc[1] * 2, int(562 * sc), int(145 * sc)))
        if best[0] > 0.5:
            out.add(tuple(round(v / 16) * 16 for v in best[1]))
    return sorted(out)


def place_meme(j: dict, r_: random.Random) -> None:
    """Центр и масштаб стикера: минимум перекрытия субтитров; верх ≥ 600 (плашка, лицо стримера), низ ≤ 1540
    (безопасная зона 9:16), ближе к центру и крупнее при равном перекрытии."""
    meta = json.loads((STK / "_meta.json").read_text(encoding="utf-8"))[j["meme"]]
    tr = text_rows(j)
    _x0, _y0, cw_, _ch = crop_of(j)
    ps = W / cw_
    pboxes = [(x, y, round(562 * ps), round(145 * ps)) for a_, b_, x, y in j.get("plates", [])
              if a_ < round(MEME_T0 * FPS) + meta["frames"] + 2] + plates_seen(j)
    best = None
    for sc in (1.0, 0.9, 0.8):
        h = meta["h"] * sc * 0.92                          # видимая часть (без поля под тень)
        for cy in range(700, 1460, 20):
            top, bot = cy - h / 2, cy + h / 2
            if top < 600 or bot > 1540:
                continue
            hw = meta["w"] * sc * 0.46                     # полуширина видимой карточки
            if any(px_ - 20 < 540 + 40 + hw and px_ + pw_ + 20 > 540 - 40 - hw and py_ - 20 < bot and py_ + ph_ + 20 > top
                   for px_, py_, pw_, ph_ in pboxes):
                continue                                   # плашку STATEDQVH не закрываем никогда
            cost = float(tr[int(top):int(bot)].sum()) * 12 + (1 - sc) * 1.5 + abs(cy - 1080) / 900
            if best is None or cost < best[0]:
                best = (cost, sc, cy)
    _c, sc, cy = best if best else (0, 0.8, 1080)
    j["ms"] = round(sc, 3)
    j["mcx"] = round(540 + r_.uniform(-30, 30))
    j["mcy"] = int(cy + r_.uniform(-10, 10))


def prog(stage: str, done: int = 0, total: int | None = None) -> None:
    try:
        PROG.parent.mkdir(parents=True, exist_ok=True)
        PROG.write_text(json.dumps(dict(stage=stage, done=done, total=total), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def shade_field(seed: int, w: int, h: int) -> np.ndarray:
    rng = random.Random(seed)
    x = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    ph = (rng.uniform(0, 6.28) + y * rng.uniform(-6, 6)
          + np.sin(y * rng.uniform(2, 5) + rng.uniform(0, 6.28)) * rng.uniform(0.5, 1.5))
    return (0.6 * np.sin(2 * math.pi * rng.uniform(1.2, 2.6) * x + ph)
            + 0.4 * np.sin(2 * math.pi * rng.uniform(2.5, 4.5) * x + ph * 1.7 + rng.uniform(0, 6.28)))


# ---------------- исходники ----------------
def pauses(path: Path) -> list[float]:
    """Паузы речи: минимумы громкости (окно 0.25 с) ниже 30-го перцентиля, не чаще раза в 1.2 с."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32)
    win = 2000
    n = len(a) // win
    rms = np.sqrt((a[:n * win].reshape(n, win) ** 2).mean(1) + 1)
    thr = np.percentile(rms, 30)
    out, last = [], -9.0
    for i in range(1, n - 1):
        t = i * 0.25
        if rms[i] <= thr and rms[i] <= rms[i - 1] and rms[i] <= rms[i + 1] and t - last >= 1.2:
            out.append(round(t, 2))
            last = t
    return out


def prep() -> None:
    SEGD.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC.glob("*.mp4"))

    def one(p: Path):
        k = p.stem.replace("OneState_KO_", "").replace("_STATEDQVH", "")
        dest = SEGD / f"{k}.mp4"
        if not dest.exists():                              # 30 к/с, без B-кадров, ключевые кадры часто (для -ss)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(p), "-c:v", "h264_nvenc", "-preset", "p5", "-rc",
                            "vbr", "-cq", "16", "-g", "15", "-bf", "0", "-c:a", "aac", "-b:a", "192k",
                            "-map_metadata", "-1", str(dest)], check=True)
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                    str(dest)], capture_output=True, text=True).stdout)
        return k, dict(path=str(dest), dur=dur, n=int(dur * FPS) - 2, pauses=pauses(dest))
    with ThreadPoolExecutor(6) as ex:
        for k, m in ex.map(one, files):
            SEG[k] = m


# ---------------- план ----------------
def crop_of(j: dict) -> tuple[int, int, int, int]:
    z = j["z"]
    w, h = G._even(W / z), G._even(H / z)
    return G._even(j["x0"]), G._even(j["y0"]), w, h


def plate_box(j: dict) -> tuple[int, int, float]:
    """Где плашка исходника оказывается в кадре ролика (левый верх) и масштаб — туда же наша."""
    x0, y0, w, h = crop_of(j)
    s = W / w
    return round((PX - x0) * s), round((PY - y0) * s), s


ASR: dict = {}                                          # момент → [(начало, конец, текст)] (Whisper, output/_work/korea1/asr.json)
FINAL = tuple("요다죠까네지야어아.?!~") 


def sent_ok(t: str) -> bool:
    """Законченная фраза: корейское окончание предложения, знак конца или смех."""
    t = t.strip()
    return bool(t) and (t.endswith(FINAL) or "ㅋ" in t[-4:] or "하하" in t[-4:])


def candidate(rng: random.Random, moment: str) -> dict | None:
    m = SEG[moment]
    if ASR.get(moment):                                    # по смыслу: начало фразы → конец законченной фразы
        segs = ASR[moment]
        starts = [round(a_, 2) for a_, _b, _t in segs if a_ < m["dur"] - 15.5]
        ends_all = [round(b_ + 0.25, 2) for _a, b_, t in segs if sent_ok(t)]
        for _ in range(30):
            if not starts:
                break
            s = rng.choice(starts)
            ends = [e for e in ends_all if 15.0 <= e - s <= 25.0 and e < m["dur"] - 0.6]
            if not ends:
                continue
            bad = m.get("bad", [])
            cnt = {e: sum(1 for b_ in bad if round(s * FPS) - 1 <= b_ <= round(e * FPS) + 1) for e in ends}
            lo = min(cnt.values())
            e = rng.choice([x for x in ends if cnt[x] == lo])
            if CLEAN or LIGHT:
                k0_, k1_ = round(s * FPS), round(e * FPS)
                tr = TRACK.get(moment, [])
                vis = sum(1 for sc_, _x, _y in tr[k0_:k1_] if sc_ > 0.75) / max(1, k1_ - k0_)
                if vis < 0.97:
                    continue
                t0_ = round(max(0.0, s - 0.1), 3)
                if CLEAN:
                    return dict(moment=moment, t0=t0_, dur=round(e - t0_, 3), z=1.0, x0=0.0, y0=0.0, shade=0, bright=1.0)
                lj = light_geo(rng, tr[k0_:k1_])
                if lj:
                    return dict(moment=moment, t0=t0_, dur=round(e - t0_, 3), shade=0, **lj)
                continue
    ps = [0.4] + [p for p in m["pauses"] if p < m["dur"] - 15.5]
    for _ in range(30):
        s = rng.choice(ps)
        ends = [p for p in m["pauses"] if 15.0 <= p - s <= 25.0 and p < m["dur"] - 1.0]
        if not ends:
            continue
        bad = m.get("bad", [])                             # повторы кадров в исходнике клиента — отрезок их обходит
        cnt = {p: sum(1 for b in bad if round(s * FPS) - 1 <= b <= round(p * FPS) + 1) for p in ends}
        lo = min(cnt.values())                             # чистого нет — с наименьшим числом повторов
        e = rng.choice([p for p in ends if cnt[p] == lo])
        if CLEAN or LIGHT:                                 # юзер 16.11: «каша, промокод в двух местах» — как в исходнике
            k0_, k1_ = round(s * FPS), round(e * FPS)
            tr = TRACK.get(moment, [])
            vis = sum(1 for sc_, _x, _y in tr[k0_:k1_] if sc_ > 0.75) / max(1, k1_ - k0_)
            if vis < 0.97:
                continue
            if CLEAN:
                return dict(moment=moment, t0=round(s, 3), dur=round(e - s, 3), z=1.0, x0=0.0, y0=0.0,
                            shade=0, bright=1.0)
            lj = light_geo(rng, tr[k0_:k1_])
            if lj:
                return dict(moment=moment, t0=round(s, 3), dur=round(e - s, 3), shade=0, **lj)
            continue
        z = round(rng.uniform(1.0, 1.3), 3)
        w, h = W / z, H / z
        # приближение «от плашки»: по вертикали плашка остаётся у верха; по горизонтали — сдвиг в пределах кадра
        x0 = rng.uniform(max(0.0, PCX - w * 0.62), min(W - w, PCX - w * 0.38))
        y0 = rng.uniform(0.0, (PCY - PCY / z))
        j = dict(moment=moment, t0=round(s, 3), dur=round(e - s, 3), z=z, x0=round(x0, 1), y0=round(y0, 1),
                 shade=rng.randrange(1 << 30), bright=round(rng.uniform(0.97, 1.03), 3))
        _px, py, sc = plate_box(j)
        if py < 60:                                        # плашка не должна уехать под верх кадра
            continue
        return j
    return None


def light_geo(rng: random.Random, tr: list) -> dict | None:
    """Юзер 16.11 (Korea 1): несхожесть без «каши» — мягкий зум 1.0–1.2 со сдвигом, яркость ±3 %; плашка исходника
    (все её места в отрезке) целиком в кадре с запасом 12 px; своей плашки и волн света нет."""
    pos = {(round(x / 16) * 16, round(y / 16) * 16) for sc_, x, y in tr if sc_ > 0.75} or {(PX, PY)}
    for _ in range(20):
        z = round(rng.uniform(1.0, float(os.environ.get("KOS_ZMAX", "1.2"))), 3)
        w, h = W / z, H / z
        lo_x = max(0.0, max(x + 562 + 12 - w for x, _y in pos))
        hi_x = min(W - w, min(x - 12 for x, _y in pos))
        lo_y = max(0.0, max(y + 145 + 12 - h for _x, y in pos))
        hi_y = min(H - h, min(y - 12 for _x, y in pos))
        if lo_x > hi_x or lo_y > hi_y:
            continue
        return dict(z=z, x0=round(rng.uniform(lo_x, hi_x), 1), y0=round(rng.uniform(lo_y, hi_y), 1),
                    bright=round(rng.uniform(0.97, 1.03), 3))
    return None


TRACK: dict = {}
LIGHT = False                                            # --light: мягкий зум/сдвиг/яркость, без нашей плашки и света
CLEAN = False                                            # --clean: без зума/света/нашей плашки                                        # момент → [(уверенность, x, y)] плашки исходника по кадрам


def plate_segments(j: dict) -> list[tuple[int, int, int, int]]:
    """Где плашка исходника в каждом кадре ролика: (кадр от, кадр до, x, y) в кадре ролика. Нет плашки в исходнике —
    берём ближайшее место, где она была (наша плашка видна всегда). Места — к ближайшему из «домов» момента."""
    tr = TRACK[j["moment"]]
    k0, nf = round(j["t0"] * FPS), int(j["dur"] * FPS)
    vis = [(i, x, y) for i, (sc, x, y) in enumerate(tr) if sc > 0.75]
    homes = sorted({(round(x / 16) * 16, round(y / 16) * 16) for _i, x, y in vis})
    hx = {}
    for _i, x, y in vis:
        key = (round(x / 16) * 16, round(y / 16) * 16)
        hx.setdefault(key, []).append((x, y))
    hpos = {kk: (int(np.median([a for a, _ in v])), int(np.median([b for _, b in v]))) for kk, v in hx.items()}
    vidx = np.array([i for i, _, _ in vis])
    x0, y0, cw, ch = crop_of(j)
    sc_ = W / cw
    per = []
    for f in range(nf):
        k = k0 + f
        if len(vidx):
            i = int(vidx[np.argmin(np.abs(vidx - k))])
            _s, x, y = tr[i]
            per.append(hpos[(round(x / 16) * 16, round(y / 16) * 16)])
        else:
            per.append((PX, PY))
    # сглаживание: место меняется, только если держится ≥ 15 кадров (ошибки поиска не дёргают плашку)
    sm = list(per)
    for f in range(nf):
        win = per[max(0, f - 7):f + 8]
        sm[f] = max(set(win), key=win.count)
    segs, cur = [], None
    for f in range(nf):
        o = (round((sm[f][0] - x0) * sc_), round((sm[f][1] - y0) * sc_))
        if cur and cur[2:] == o:
            cur[1] = f + 1
        else:
            cur = [f, f + 1, *o]
            segs.append(cur)
    while len(segs) > 1 and min(b - a for a, b, _x, _y in segs) < 15:      # короткие куски — к соседу
        i = min(range(len(segs)), key=lambda q: segs[q][1] - segs[q][0])
        nb = i - 1 if i > 0 else i + 1
        lo, hi = min(segs[i][0], segs[nb][0]), max(segs[i][1], segs[nb][1])
        keep = segs[nb]
        segs[nb] = [lo, hi, keep[2], keep[3]]
        del segs[i]
    return [tuple(c) for c in segs]


def frames_of(jobs: list[dict]) -> "UF.Frames":
    idx, box, scale, A, C = [], [], [], [], []
    per = None
    for j in jobs:
        nf = int(j["dur"] * FPS)
        # 17.11: прогноз ВСЕГО ролика (было — первые 15 с: совпадения в 15–25 с ловились только после сборки,
        # к концу партии 9 из 10 вариантов шли в брак); короче 25 с — добиваем последним кадром (min не меняется)
        fr = np.array([min(nf - 1, round(i * FPS / HFPS) + 2) for i in range(int(25.5 * HFPS))])
        per = len(fr)
        k0 = round(j["t0"] * FPS)
        idx.append(UST.off[j["moment"]] + np.minimum(k0 + fr, UST.n[j["moment"]] - 1))
        b = UF.strip_box(crop_of(j), 0, H, STRIP)
        box.append(np.tile(np.array(b, np.float32), (len(fr), 1)))
        scale.append(np.full(len(fr), UF.CW / W, np.float32))
        sh = shade_field(j["shade"], W // 4, H // 4)[STRIP[0] // 4:STRIP[1] // 4]
        a, c = UF.shade_cells(sh, SHADE_AMP)
        A.append(np.repeat(a[None], len(fr), 0))
        C.append(np.repeat(c[None], len(fr), 0))
    return UF.Frames(np.concatenate(idx), np.concatenate(box), np.concatenate(scale), np.concatenate(A),
                     np.concatenate(C), per)


def plan(slots: list[tuple[str, int, str]], bank, rng: random.Random, tries: int, label: str) -> list[dict]:
    import torch
    jobs, worst, t0 = [], [], time.time()
    for k, (tag, n, moment) in enumerate(slots, 1):
        best = None
        for _ in range(0, tries, 24):
            cands = [c for c in (candidate(rng, moment) for _ in range(24)) if c]
            if not cands:
                continue
            Hh, Mm = UF.predict(UST, frames_of(cands))
            d = bank.min_dist(Hh)
            i = int(torch.argmax(d))
            if best is None or float(d[i]) > best[0]:
                best = (float(d[i]), cands[i], Hh[i], Mm[i])
            if best[0] > PLAN_THR:
                break
        if best is None:
            raise LookupError(moment)
        d, j, Hh, Mm = best
        j.update(tag=tag, n=n, plan_dist=round(d, 1))
        bank.add(Hh, Mm)
        jobs.append(j)
        worst.append(d)
        if len(slots) > 1:
            prog(f"{label}: варианты по отпечаткам", k, len(slots))
    w = sorted(worst)
    print(f"{label}: {len(jobs)} за {time.time() - t0:.0f} с; ближайший чужой кадр — мин {w[0]:.0f}, медиана "
          f"{w[len(w) // 2]:.0f}; ≤ {THR}: {sum(x <= THR for x in w)}, ≤ {PLAN_THR}: {sum(x <= PLAN_THR for x in w)}",
          flush=True)
    return jobs


# ---------------- сборка ----------------
def build(job: dict) -> str:
    import tempfile
    from core.gpu_slots import gpu_slot
    SEG.update(job["segs"])
    tmp = Path(tempfile.mkdtemp(prefix="kos1_"))
    m = SEG[job["moment"]]
    x0, y0, cw, ch = crop_of(job)
    px, py, sc = plate_box(job)
    pl = Image.open(PLATE).convert("RGBA")
    pl = pl.resize((round(pl.width * sc), round(pl.height * sc)), Image.Resampling.LANCZOS)
    v = shade_field(job["shade"], W, H)
    lay = np.zeros((H, W, 4), np.uint8)
    lay[..., :3] = np.where(v < 0, 255, 0)[..., None]
    lay[..., 3] = (np.abs(v) * SHADE_AMP * 255).astype(np.uint8)
    base_lay = Image.fromarray(lay, "RGBA")
    psegs = job["plates"] if not job.get("clean") else []
    for i, (_a, _b, x, y) in enumerate(psegs):
        L = base_lay.copy()
        L.alpha_composite(pl, (x, y))
        L.save(tmp / f"layer{i}.png", compress_level=1)
    nf = int(job["dur"] * FPS)
    k0 = round(job["t0"] * FPS)
    noss = os.environ.get("KOS_NOSS") == "1"                 # распаковка с начала момента + trim (без -ss)
    ss = ["-ss", f"{(k0 - 0.5) / FPS:.4f}"] if k0 > 0 and not noss else []
    f0 = k0 if noss else 0
    ins = ["-c:v", "h264_cuvid", "-crop", f"{y0}x{H - y0 - ch}x{x0}x{W - x0 - cw}", "-resize", f"{W}x{H}", *ss,
           "-i", m["path"]]
    for i in range(len(psegs)):
        ins += ["-i", str(tmp / f"layer{i}.png")]
    mm = job.get("meme")
    if mm:
        mx, my, _mw, _mh, _f0, _f1 = meme_box(job)
        ins += ["-i", str(STK / f"{mm}.mov"), "-i", job["boom"]]
        im_v, im_a = 1 + len(psegs), 2 + len(psegs)
    fc = (f"[0:v]trim=start_frame={f0}:end_frame={f0 + nf},setpts=PTS-STARTPTS,setsar=1,format=yuv420p,eq=brightness={job['bright'] - 1:.3f},"
          f"tpad=stop_mode=clone:stop=3,trim=end_frame={nf}[v0];"
          + "".join(f"[{1 + i}:v]format=yuva420p,loop=loop={b - a - 1}:size=1:start=0,settb=1/{FPS},setpts=N[s{i}];"
                    for i, (a, b, _x, _y) in enumerate(psegs))
          + ("".join(f"[s{i}]" for i in range(len(psegs))) + f"concat=n={len(psegs)}:v=1:a=0,setpts=N[ly];"
             + "[v0][ly]overlay=0:0:format=yuv420,format=yuv420p[vb];" if psegs else "[v0]format=yuv420p[vb];")
          + (f"[{im_v}:v]scale={_mw}:{_mh},setpts=PTS-STARTPTS+{MEME_T0}/TB[mm];[vb][mm]overlay={mx}:{my}:eof_action=pass:format=yuv420,"
             f"format=yuv420p[v];" if mm else "[vb]null[v];")
          + f"[0:a]atrim={f0 / FPS:.4f}:{f0 / FPS + job['dur']:.4f},asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.12,"
          f"afade=t=out:st={job['dur'] - 0.25:.3f}:d=0.25" + ("[a0];" if mm else "[a]")
          + (f"[{im_a}:a]aresample=48000,adelay={round((MEME_T0 + 0.07) * 1000)}:all=1,volume=0.9[bm];"
             f"[a0]aresample=48000[a1];[a1][bm]amix=inputs=2:duration=first:normalize=0[a]" if mm else ""))
    dest = Path(job["dest"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    (tmp / "graph.txt").write_text(fc, encoding="utf-8")                # граф файлом: длинная команда не влезает
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", *ins, "-filter_complex_script", str(tmp / "graph.txt"),
           "-map", "[v]", "-map", "[a]",
           "-frames:v", str(nf), *G.NVENC, "-c:a", "aac", "-b:a", "192k", *G.CLEAN, str(dest)]
    with gpu_slot():
        for attempt in range(3):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
            if r.returncode == 0:
                break
            if attempt == 2:
                raise RuntimeError(f"{dest.name}: {r.stderr[-500:]}")
            time.sleep(2)
    shutil.rmtree(tmp, ignore_errors=True)
    return dest.name


# ---------------- приёмка ----------------
def frame_check(job: dict, path: Path, margin: float = 0.8, junk: float = 14.0) -> list:
    """Каждый кадр — тот кадр исходника, что в плане (полоса ниже плашки, ±3 соседа)."""
    w8, h8 = W // 8, (STRIP[1] - STRIP[0]) // 8
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                          f"crop={W}:{STRIP[1] - STRIP[0]}:0:{STRIP[0]},scale={w8}:{h8}:flags=area,format=gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    out = np.frombuffer(raw, np.uint8).reshape(-1, h8, w8).astype(np.float32)
    nf = int(job["dur"] * FPS)
    if len(out) != nf:
        return [("кадров", len(out))]
    x0, y0, cw, ch = crop_of(job)
    sx = UF.CW / W
    bx = (x0 * sx, (y0 + STRIP[0] * ch / H) * sx, (x0 + cw) * sx, (y0 + STRIP[1] * ch / H) * sx)
    v = shade_field(job["shade"], W // 8, H // 8)[STRIP[0] // 8:STRIP[0] // 8 + h8]
    sa, sc = np.abs(v) * SHADE_AMP, np.where(v < 0, 255.0, 0.0)
    base = UST.off[job["moment"]]
    k0 = round(job["t0"] * FPS)
    cache: dict = {}

    def exp(k):
        if k not in cache:
            im = Image.fromarray(UST.all[base + k]).resize((w8, h8), Image.Resampling.BILINEAR, box=bx)
            cache[k] = np.asarray(im, np.float32) * job["bright"] * (1 - sa) + sc * sa
        return cache[k]
    flags = []
    n = UST.n[job["moment"]]
    pw, ph = round(562 * (W / cw) / 8) + 4, round(145 * (W / cw) / 8) + 4
    masks = {}
    for a_, b_, x, y in job["plates"]:
        mk = np.ones((h8, w8), np.float32)
        r0 = (y - STRIP[0]) // 8 - 2
        mk[max(0, r0):max(0, r0 + ph), max(0, x // 8 - 2):max(0, x // 8 - 2 + pw)] = 0
        masks[(a_, b_)] = mk
    mmask, mf0, mf1 = None, 0, -1
    if job.get("meme"):
        mx, my, mw, mh, mf0, mf1 = meme_box(job)
        mmask = np.ones((h8, w8), np.float32)
        r0 = (my - STRIP[0]) // 8 - 2
        mmask[max(0, r0):max(0, r0 + mh // 8 + 4), max(0, mx // 8 - 2):max(0, mx // 8 + mw // 8 + 2)] = 0
    for f in range(nf):
        k = k0 + f
        mk = next(v for (a_, b_), v in masks.items() if a_ <= f < b_)
        if mmask is not None and mf0 <= f <= mf1:
            mk = mk * mmask
        wsum = mk.sum()
        d = {dk: float((np.abs(out[f] - exp(k + dk)) * mk).sum() / wsum) for dk in range(-3, 4) if 0 <= k + dk < n}
        best = min(d, key=d.get)
        if d[best] > junk:
            flags.append((f, "мусор", round(d[best], 1)))
        elif best != 0 and d[0] - d[best] > margin:
            flags.append((f, best, round(d[0] - d[best], 2)))
    return flags


def blank_frames(path: Path) -> list[int]:
    """Пустые/зелёные/чёрные кадры (как первая часть G.bad_frames). Повторы кадров здесь не считаем: у стримов клиента
    повторы есть в самой записи; что каждый кадр ролика = кадр исходника по плану, проверяет frame_check."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "scale=54:96", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 96, 54, 3).astype(np.int16)
    m = fr.mean(axis=(1, 2))
    return [i for i, (r_, g_, b_) in enumerate(m) if (g_ > 50 and r_ < 12 and b_ < 12) or (r_ + g_ + b_) / 3 < 8]


def decode_checks(path: Path) -> tuple:
    """17.11 рецепт Skinive: ОДНА распаковка готового ролика на все проверки (было три по 6–10 с под нагрузкой —
    98 собранных роликов ждали проверки, принято 3): полоса STRIP 1/8 серым (сверка), RGB 54×96 (пустые кадры),
    17×16 полосы (отпечатки — тем же фильтром, что UF.real_hash)."""
    import tempfile
    w8, h8 = W // 8, (STRIP[1] - STRIP[0]) // 8
    d = Path(tempfile.mkdtemp(prefix="kchk_"))
    g, r, hh = d / "g.raw", d / "r.raw", d / "h.raw"
    sh = STRIP[1] - STRIP[0]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-threads", "4", "-i", str(path), "-filter_complex",
                    f"[0:v]split=3[a][b][c];[a]crop={W}:{sh}:0:{STRIP[0]},scale={w8}:{h8}:flags=area,format=gray[g];"
                    f"[b]scale=54:96,format=rgb24[r];[c]crop=iw:{sh}:0:{STRIP[0]},scale=17:16:flags=area,format=gray[h]",
                    "-map", "[g]", "-f", "rawvideo", str(g), "-map", "[r]", "-f", "rawvideo", str(r),
                    "-map", "[h]", "-f", "rawvideo", str(hh)], capture_output=True)
    G_ = np.fromfile(g, np.uint8).reshape(-1, h8, w8).astype(np.float32)
    R_ = np.fromfile(r, np.uint8).reshape(-1, 96, 54, 3).astype(np.int16)
    H_ = np.fromfile(hh, np.uint8).reshape(-1, 16, 17).astype(np.int16)
    shutil.rmtree(d, ignore_errors=True)
    m = R_.mean(axis=(1, 2))
    blank = [i for i, (r_, g_, b_) in enumerate(m) if (g_ > 50 and r_ < 12 and b_ < 12) or (r_ + g_ + b_) / 3 < 8]
    h = (H_[:, :, 1:] > H_[:, :, :-1]).reshape(len(H_), -1).astype(np.float16)
    mm = (H_[:, :, ::-1][:, :, 1:] > H_[:, :, ::-1][:, :, :-1]).reshape(len(H_), -1).astype(np.float16)
    return G_, blank, np.stack([h, mm], 1)


def frame_check_fast(job: dict, out: np.ndarray, margin: float = 0.8, junk: float = 14.0) -> list:
    """Та же сверка, что frame_check, но разом на видеокарте: кадры исходника по плану (окно, масштаб) через
    roi_align из FrameStore, все сдвиги ±3 и все кадры одной операцией, маски плашки и стикера."""
    import torch
    from torchvision.ops import roi_align
    w8, h8 = W // 8, (STRIP[1] - STRIP[0]) // 8
    nf = int(job["dur"] * FPS)
    if len(out) != nf:
        return [("кадров", len(out))]
    x0, y0, cw, ch = crop_of(job)
    sx = UF.CW / W
    bx = (x0 * sx, (y0 + STRIP[0] * ch / H) * sx, (x0 + cw) * sx, (y0 + STRIP[1] * ch / H) * sx)
    base, n = UST.off[job["moment"]], UST.n[job["moment"]]
    k0 = round(job["t0"] * FPS)
    ks = np.clip(np.arange(k0 - 3, k0 + nf + 3), 0, n - 1)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    src = torch.from_numpy(np.ascontiguousarray(UST.all[base + ks])).to(dev).float()[:, None]
    boxes = torch.tensor([[0, *bx]], device=dev, dtype=torch.float32).repeat(len(ks), 1)
    boxes[:, 0] = torch.arange(len(ks), device=dev, dtype=torch.float32)
    exp = roi_align(src, boxes, (h8, w8), 1.0, 2, True)[:, 0] * job["bright"]
    M = torch.ones((nf, h8, w8), device=dev)
    pw, ph = round(562 * (W / cw) / 8) + 4, round(145 * (W / cw) / 8) + 4
    for a_, b_, x, y in job["plates"]:
        r0 = (y - STRIP[0]) // 8 - 2
        M[a_:b_, max(0, r0):max(0, r0 + ph), max(0, x // 8 - 2):max(0, x // 8 - 2 + pw)] = 0
    if job.get("meme"):
        mx, my, mw, mh, mf0, mf1 = meme_box(job)
        r0 = (my - STRIP[0]) // 8 - 2
        M[mf0:mf1 + 1, max(0, r0):max(0, r0 + mh // 8 + 4), max(0, mx // 8 - 2):max(0, mx // 8 + mw // 8 + 2)] = 0
    o = torch.from_numpy(out).to(dev)
    ws = M.sum((1, 2)).clamp(min=1)
    D = torch.stack([(torch.abs(o - exp[3 + dk:3 + dk + nf]) * M).sum((1, 2)) / ws for dk in range(-3, 4)], 1)
    kk = torch.arange(nf, device=dev)[:, None] + k0 + torch.arange(-3, 4, device=dev)[None]
    D[(kk < 0) | (kk >= n)] = 1e9
    best = D.argmin(1)
    dmin = D.gather(1, best[:, None])[:, 0]
    d0 = D[:, 3]
    flags = []
    for f in torch.nonzero((dmin > junk) | ((best != 3) & (d0 - dmin > margin))).flatten().tolist():
        if float(dmin[f]) > junk:
            flags.append((f, "мусор", round(float(dmin[f]), 1)))
        else:
            flags.append((f, int(best[f]) - 3, round(float(d0[f] - dmin[f]), 2)))
    return flags


def check_one(job: dict) -> tuple:
    p = Path(job["dest"])
    G_, blank, hm = decode_checks(p)
    fr = frame_check_fast(job, G_)
    if fr and not blank:                                   # сомнение — прежняя точная сверка
        fr = frame_check(job, p)
    return hm, blank, fr


ACC_THR, ACC_MAX = 40, 2                                 # приёмка (как Skinive 17.11): ≤ 2 кадров ближе 40 бит


def near_count(bank, h: np.ndarray, thr: int = ACC_THR) -> int:
    """Сколько кадров похожи (ближе thr бит) — в обе стороны: кадры кандидата рядом с банком и кадры банка рядом
    с кандидатом (неподвижный кусок принятого ролика иначе прятался за 1–2 кадрами нового)."""
    import torch
    if bank.pa or bank.sa is None:
        bank._flush()
    if not len(bank.A):
        return 0
    q = torch.as_tensor(np.asarray(h, np.float16)).to(UF.DEV).to(UF.DT).reshape(-1, 256)
    qs = q.float().sum(1)
    fwd = torch.zeros(len(q), dtype=torch.bool, device=UF.DEV)
    rev = 0
    for b in range(0, len(bank.A), 32768):
        hit_b = torch.zeros(min(32768, len(bank.A) - b), dtype=torch.bool, device=UF.DEV)
        for X, sx in ((bank.A, bank.sa), (bank.M, bank.sm)):
            d = qs[:, None] + sx[None, b:b + 32768].float() - 2 * (q @ X[b:b + 32768].T).float()
            m = d <= thr
            fwd |= m.any(1)
            hit_b |= m.any(0)
        rev += int(hit_b.sum())
    return max(int(fwd.sum()), rev)


def vname(j: dict) -> str:
    return f"{NAME}_{j['tag']}_{j['n']:03d}_1.mp4"


def old_bank_add(bank, dirs: list[str]) -> int:
    """Прошлые партии (каждый кадр, полоса STRIP) — в банк, чтобы новая партия не повторяла их (кэш npz)."""
    cache = WORK / "old_hashes.npz"
    d = dict(np.load(cache, allow_pickle=True)["d"].item()) if cache.exists() else {}
    files = [f for dd in dirs for f in sorted((ROOT / "output" / dd).glob("*.mp4"))]
    todo = [f for f in files if str(f) not in d]
    with ThreadPoolExecutor(8) as ex:
        for f, (h_, m_) in zip(todo, ex.map(lambda f: UF.real_hash(f, STRIP), todo)):
            d[str(f)] = (np.asarray(h_, np.uint8), np.asarray(m_, np.uint8))
    if todo:
        np.savez(cache, d=np.array(d, dtype=object))
    for f in files:
        h_, m_ = d[str(f)]
        bank.add(h_.astype(np.float16), m_.astype(np.float16))
    return len(files)


def main() -> int:
    global UST, NAME, MEMES
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--tt", type=int, default=100)
    ap.add_argument("--yt", type=int, default=100)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--seed", type=int, default=91116)
    ap.add_argument("--tries", type=int, default=480)
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--light", action="store_true", help="мягкий зум 1.0–1.2 + сдвиг + яркость, без нашей плашки")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--name", default=NAME)
    ap.add_argument("--memes", action="store_true", help="мем-стикер в первые 3.4 с (вторая партия 17.11)")
    ap.add_argument("--avoid", nargs="*", default=[], help="папки прошлых партий в output/ — не повторять их кадры")
    a = ap.parse_args()
    NAME, MEMES = a.name, a.memes
    import torch
    global CLEAN, SHADE_AMP, LIGHT
    if a.clean:
        CLEAN, SHADE_AMP = True, 0.0
    if a.light:
        LIGHT, SHADE_AMP = True, 0.0
    t0 = time.time()
    prog("подготовка исходников")
    prep()
    UST = UF.FrameStore(UF.CW, UF.CH)
    UST.load({k: Path(v["path"]) for k, v in SEG.items()})
    TRACK.update(json.loads((WORK / "plate_track.json").read_text(encoding="utf-8")))
    if (WORK / "asr.json").exists():
        ASR.update({k: [tuple(x) for x in v] for k, v in json.loads((WORK / "asr.json").read_text(encoding="utf-8")).items()})
    for k in SEG:                                          # повторы кадров посреди движения (как bad_frames)
        arr = UST.all[UST.off[k]:UST.off[k] + UST.n[k]].astype(np.float32).reshape(-1, UF.CH // 5, 5, UF.CW // 5, 5).mean((2, 4))
        d = np.abs(np.diff(arr, axis=0)).mean((1, 2))
        SEG[k]["bad"] = [i + 1 for i in range(1, len(d) - 1) if d[i] < 0.3 and d[i - 1] > 0.6 and d[i + 1] > 0.6]
    print(f"исходники: {len(SEG)} моментов, {sum(v['dur'] for v in SEG.values()):.0f} с, пауз "
          f"{sum(len(v['pauses']) for v in SEG.values())}, {time.time() - t0:.0f} с", flush=True)
    moments = sorted(SEG)
    if MEMES:                                              # только моменты, к которым подобран мем
        moments = [m_ for m_ in moments if (STK / f"{meme_key(m_)}.mov").exists()]
    rng = random.Random(a.seed)
    if a.test:
        slots = [("tt", 1, moments[0]), ("yt", 1, moments[10]), ("tt", 2, moments[3]), ("yt", 2, moments[14]),
                 ("tt", 3, moments[6]), ("yt", 3, moments[8])]
        tdir = "test_meme" if MEMES else "test_light" if LIGHT else "test"
        out_dir = {"tt": WORK / tdir, "yt": WORK / tdir}
    else:
        if CLEAN or LIGHT:                                 # моменты, где есть отрезки с родной плашкой ≥ 97 % времени
            ok = []
            for m_ in moments:
                r_ = random.Random(7)
                if any(candidate(r_, m_) for _ in range(40)):
                    ok.append(m_)
            print(f"моменты с чистыми отрезками: {len(ok)} из {len(moments)}; без: {sorted(set(moments) - set(ok))}", flush=True)
            moments = ok
        order = [m for _ in range(20) for m in moments]
        slots = [("tt", n, order[n - 1]) for n in range(1, a.tt + 1)] + \
                [("yt", n, order[a.tt + n - 1]) for n in range(1, a.yt + 1)]
        out_dir = {"tt": ROOT / "output" / f"{NAME}_TT_{a.tt}", "yt": ROOT / "output" / f"{NAME}_YT_{a.yt}"}
    bank = UF.Bank()
    if a.avoid:
        prog("отпечатки прошлых партий (каждый кадр)", 0, None)
        print(f"прошлые партии в сравнении: {old_bank_add(bank, a.avoid)} роликов", flush=True)
    pf = WORK / f"plan_{a.seed}_{'L' if LIGHT else ''}{'M' if MEMES else ''}{'test' if a.test else f'{a.tt}_{a.yt}'}.json"
    if pf.exists():
        jobs = json.loads(pf.read_text(encoding="utf-8"))
    else:
        jobs = plan(slots, bank.copy(), rng, a.tries, "план")
        pf.write_text(json.dumps(jobs), encoding="utf-8")
    if a.plan_only:
        print(f"ПЛАН ГОТОВ: {len(jobs)} → {pf}", flush=True)
        return 0
    for j in jobs:
        j["dest"] = str(out_dir[j["tag"]] / vname(j))
    todo = [j for j in jobs if not Path(j["dest"]).exists()]
    have = [Path(j["dest"]) for j in jobs if Path(j["dest"]).exists()]
    if have:
        prog("отпечатки готовых роликов (каждый кадр)", 0, len(have))
        with ThreadPoolExecutor(8) as ex_:
            for h_, m_ in ex_.map(lambda f: UF.real_hash(f, STRIP), have):
                bank.add(h_, m_)
        print(f"готовых роликов в сравнении: {len(have)}", flush=True)
    segs = dict(SEG)
    pool = ProcessPoolExecutor(a.jobs)
    chk = ThreadPoolExecutor(6)
    building, checking, pending, fails = {}, {}, {}, {}
    cand = WORK / f"cand_{os.getpid()}"
    done, rej, total = len(jobs) - len(todo), 0, len(jobs)

    def submit(j):
        key = (j["tag"], j["n"])
        j["final"] = j.get("final") or j["dest"]
        j["dest"] = str(cand / f"{j['tag']}_{j['n']:03d}_{fails.get(key, 0)}.mp4")
        j["segs"] = segs
        j["plates"] = plate_segments(j)
        j["clean"] = CLEAN or LIGHT
        if MEMES:
            r_ = random.Random(hash((j["tag"], j["n"], fails.get(key, 0))) & 0xFFFFFFF)
            j["meme"] = meme_key(j["moment"])
            place_meme(j, r_)
            j["boom"] = str(r_.choice(BOOMS))
        pending[key] = UF.predict(UST, frames_of([j]))
        building[pool.submit(build, j)] = j
    # 17.11: все 200 сразу в очередь сборки → 98 собранных ждали проверки и отнимали процессор у проверок;
    # теперь в работе не больше LIMIT (сборка + проверка), следующий — по мере приёмки
    LIMIT = a.jobs * 2 + 4
    queue_ = list(todo)

    def feed():
        while queue_ and len(building) + len(checking) < LIMIT:
            submit(queue_.pop(0))
    feed()
    prog(f"сборка + проверка каждого кадра (заменено {rej})", done, total)
    while building or checking or queue_:
        feed()
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
            nn = near_count(bank, h[:, 0])
            d = nn
            if nn <= ACC_MAX and not bad and not fr:
                bank.add(h[:, 0], h[:, 1])
                pending.pop(key, None)
                Path(j["final"]).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(j["dest"], j["final"])
                j["dest"] = j.pop("final")
                done += 1
                prog(f"сборка + проверка каждого кадра (заменено {rej})", done, total)
                continue
            rej += 1
            why = f"bad_frames {bad[:4]}" if bad else f"кадры {fr[:4]}" if fr else f"похожих кадров {d} (ближе {ACC_THR} бит)"
            print(f"  замена {vname(j)}: {why}", flush=True)
            if bad:                                        # повтор в самом исходнике — запомнить, следующий отрезок обойдёт
                k0b = round(j["t0"] * FPS)
                SEG[j["moment"]].setdefault("bad", []).extend(k0b + f for f in bad)
            fails[key] = fails.get(key, 0) + 1
            Path(j["dest"]).unlink(missing_ok=True)
            if fails[key] > 24:
                raise SystemExit(f"{vname(j)}: 24 варианта подряд не прошли")
            if fails[key] > 3:                             # момент исчерпан — отрезок из другого момента
                j["moment"] = rng.choice(moments)
            pending.pop(key, None)
            b2 = bank.copy()
            for Hh, Mm in pending.values():
                b2.add(Hh[0], Mm[0])
            for _try in range(8):
                try:
                    nj = plan([(j["tag"], j["n"], j["moment"])], b2, rng, a.tries, f"  новый вариант {vname(j)}")[0]
                    break
                except LookupError:
                    j["moment"] = rng.choice(moments)
            del b2
            torch.cuda.empty_cache()
            nj["final"] = j["final"]
            submit(nj)
            prog(f"сборка + проверка каждого кадра (заменено {rej})", done, total)
    pool.shutdown()
    chk.shutdown()
    shutil.rmtree(cand, ignore_errors=True)
    print(f"ГОТОВО: {done} из {total}, заменено {rej}, {time.time() - t0:.0f} с", flush=True)
    if not a.test:
        prog("итоговая проверка: каждый кадр всех пар", 0, None)
        subprocess.run([sys.executable, str(ROOT / "check_uniq_allframes.py"), *{str(out_dir[t]) for t in ("tt", "yt")},
                        "--strip", str(STRIP[0]), str(STRIP[1])])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
