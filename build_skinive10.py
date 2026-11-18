#!/usr/bin/env python3
"""
Skinive 10 + Skinive 11 (ID 1) — 200 TikTok + 200 YouTube каждый, схожесть 0–1 % между собой И со всеми прошлыми
skinive-роликами (юзер 17.11, ночная очередь: «дублируем залетный ролик» youtube TkTSJoZLunA = наш skinive2_YT).

Формат хита (skinive2, раскладка fit): начало ~3 с (одна непрерывная запись) + подпись сверху на ВЕСЬ ролик →
App Store (тап «Open») → фото родинки в редакторе → «Skinive AI verarbeitet…» → результат (шкала «Gutartiger Nävus»
или «Geringes Risiko»); «(Ersetzt keinen Hautarzt)» — последняя секунда; музыка хита (петля music.wav).
  • 10: начало — новые записи руки/плеча с родинками (Drive 1EsU4uSe…: IMG_6984/85/88/89/91/92/93), подпись — одна
    из 3 POV-вариаций ТЗ (дословно);
  • 11: «текстволлы» — начало — девушка делает селфи в кафе (IMG_6994), сверху стена текста — один из 5 текстов ТЗ
    (дословно), на весь ролик, как подпись хита.

Уникальность у КАЖДОГО ролика (непрерывные случайные величины): кусок записи и его кадрирование (зум, сдвиг, зеркало),
масштаб/место/обрезка экранов приложения, длины шагов, кегль и высота текста, мягкие волны освещения (5 % на всём,
+12 % на начале — свой рисунок), звук (старт петли, тон ±3 %, громкость).
По CLAUDE.md: видеокарта распаковывает, режет и масштабирует (cuvid -crop -resize) → кадры в обычной памяти → склейка,
поля, слои — обычными фильтрами/overlay → NVENC. Приём ролика: bad_frames + сверка КАЖДОГО кадра с исходником по плану
+ ни одного общего кадра (каждый кадр, 30 к/с, весь кадр, dHash ≤ 40, с зеркалом) ни с одним принятым (10 и 11
вместе) и ни с одним прошлым skinive (output/_work/skinive10/old30.npz, hash_old_skinive.py).

  python build_skinive10.py --test 4                   # по 4 пробы 10 и 11 → output/_work/skinive10/test
  python build_skinive10.py --probe 12 --proj 11       # замер: доля пар с общими кадрами у N кандидатов
  python build_skinive10.py --n 200 --jobs 4           # → output/skinive10_TT_200, _YT_200, skinive11_TT_200, _YT_200
"""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_skinive2 as S2  # noqa: E402
import build_skinive2_uniq as S2U  # noqa: E402  (заготовки стора/приложения, волны освещения, места дисклеймера)
import build_skinive_walls as SW  # noqa: E402
U = S2U.U                                                # build_skinive_uniq: music
from core import gpu_ffmpeg as G  # noqa: E402
from core import renderer as R  # noqa: E402
from core.gpu_slots import gpu_slot  # noqa: E402
from core.safe_zones import check_box  # noqa: E402
from core import uniq_fast as UF  # noqa: E402

W, H, FPS = 1080, 1920, 30
WORK = ROOT / "output" / "_work" / "skinive10"
CLIPS = WORK / "clips"                                   # 1080×1920 30 к/с заготовки 4K-исходников (proxy.sh)
OLD30 = WORK / "old30.npz"
THR = 40
PRED_THR, PRED_MAXF = 44, 8                              # прогноз начала: ближе 44 бит больше 8 кадров — не собирать
NEW_MAX = int(__import__("os").environ.get("SK_NEW_MAX", "2"))                                              # кадров, похожих на новые ролики (≤ 0.7 % ролика; ТЗ 0–1 %)
OLD_MAX = 2                                              # кадров, похожих на прошлые skinive (из ~280, ≤ 0.7 %)
Q8 = 8
# одно общее подключение к видеокарте на сборку (17.11): без этого каждый распаковщик куска, загрузка слоёв и кодировщик
# открывали своё (6–7 на ролик, ~130 МБ каждое, драйвер создаёт их по очереди) — память ~1 ГБ на сборку и очереди
SHAREDEV = __import__("os").environ.get("SK_SHAREDEV", "1") == "1"
HWLOOP = __import__("os").environ.get("SK_HWLOOP", "1") == "1"
SHARE_PRE = ["-init_hw_device", "cuda=gpu:0", "-filter_hw_device", "gpu"]
SHARE_IN = ["-hwaccel", "cuda", "-hwaccel_device", "gpu"]   # кадры всё равно идут в обычную память (нет hwaccel_output_format)
OV = __import__("os").environ.get("SK_OV", "cpu")       # слои: cpu (overlay в памяти) | gpu (overlay_cuda) — --ov
TEXT_LOCK = threading.Lock()                             # core.renderer — глобальные шрифты, текст по очереди
HWSEM = threading.BoundedSemaphore(4)                    # распаковки сверки на видеодекодере одновременно

# ТЗ дословно, переносы по смыслу
CAP10 = [
    ["POV: du merkst, dass dein muttermal", "irgendwie komisch aussieht,", "lädst es bei Skinive hoch", "und siehst DAS 👇"],
    ["POV: du willst nur kurz", "dein Muttermal bei Skinive checken", "und dann kommt DAS 👇"],
    ["POV: du machst ein süßes selfie,", "zoomst auf dein muttermal", "und plötzlich geht’s", "nicht mehr ums selfie 😭"],
]
CAP11 = [
    ["POV: du machst ein süßes selfie,", "zoomst auf dein muttermal", "und plötzlich geht’s", "nicht mehr ums selfie 😭"],
    ["meine freundin wollte", "nur ein süßes selfie machen.", "dann hat sie", "auf ihr muttermal gezoomt",
     "und das selfie war erstmal egal 😭"],
    ["meine freundin wollte", "ihr selfie bearbeiten", "und hat stattdessen", "20 minuten lang",
     "ihr muttermal angezoomt 😭"],
    ["meine freundin:", "„welches selfie soll ich posten?“", "fünf minuten später", "checken wir ihr muttermal",
     "bei Skinive 💀"],
    ["wir wollten das beste selfie", "von meiner freundin aussuchen.", "jetzt haben wir 14 screenshots",
     "von ihrem muttermal 😭"],
]
# куски записей (файл, от, до) — только где в кадре рука/плечо с родинками (листы кадров 1 к/с, 17.11)
SPANS10 = [("IMG_6984", 0.8, 10.2), ("IMG_6984", 15.0, 20.0), ("IMG_6985", 0.2, 13.3), ("IMG_6988", 0.2, 4.4),
           ("IMG_6989", 0.2, 14.8), ("IMG_6991", 2.2, 7.4), ("IMG_6992", 1.8, 7.4), ("IMG_6993", 0.9, 8.1)]
# селфи: общий план (девушка в нижней половине, сверху окна — место для стены); крупные планы 16–17, 24–25, 34–36 — нет
SPANS11 = [("IMG_6994", 0.3, 15.4), ("IMG_6994", 18.2, 23.6), ("IMG_6994", 26.2, 33.6)]
PROJ = {10: dict(spans=SPANS10, texts=CAP10, zoom=(1.08, 1.45), oy=(0.0, 1.0)),
        11: dict(spans=SPANS11, texts=CAP11, zoom=(1.0, 1.3), oy=(0.55, 1.0))}


def clip(name: str) -> Path:
    return CLIPS / f"{name}_proxy.mp4"


# ---------------- план ролика ----------------
def candidate(rng: random.Random, proj: int, text: int) -> dict:
    P = PROJ[proj]
    L = round(rng.uniform(2.7, 3.3), 2)
    spans = [s for s in P["spans"] if s[2] - s[1] >= L + 0.1]
    wts = [s[2] - s[1] - L for s in spans]
    name, a, b = rng.choices(spans, weights=wts)[0]
    z = rng.uniform(*P["zoom"])
    intro = dict(src=name, t=round(rng.uniform(a, b - L), 3), len=L, z=round(z, 4),
                 fx=round(rng.uniform(0.1, 0.9), 4), fy=round(rng.uniform(*P["oy"]), 4), mirror=rng.random() < 0.5)
    end = rng.choice(("gauge", "erg"))
    c = dict(proj=proj, text=text, intro=intro, end=end, scale=round(rng.uniform(0.62, 0.74), 3),
             crop_dy=rng.randint(0, 30), xj=round(rng.uniform(-1, 1), 3), yj=round(rng.random(), 3),
             s0=round(rng.uniform(7.9, 8.5), 2), r_len=round(rng.uniform(1.8, 2.4), 2),
             cap_k=round(rng.uniform(0.9, 1.0), 3), cap_top=rng.randint(204, 236), seed=rng.randrange(10 ** 9))
    if end == "gauge":
        g0, g1 = SW.GAUGE
        c["r_len"] = round((g1 - g0) / 2, 3)                 # шкала — ровно ×2 (каждый второй кадр)
    return c


def caption_png(lines: list[str], k: float, top: int, dest: Path) -> tuple[int, int]:
    """Белый TikTok-текст с ровной чёрной обводкой (skinive2), кегль — самый крупный, где строки ≤ 790 px, × k."""
    px = S2.CAP_PX
    while True:
        font, st = R._load_font(px), max(2, round(px * S2.STROKE))
        e_px = S2.A._emoji_px(px)
        widest = max(sum(e_px * 1.08 if t == "emoji" else font.getlength(c) for t, c in S2.A._tokenize_runs(ln) if c)
                     for ln in lines)
        if widest + 2 * st <= 790 or px <= 34:
            break
        px -= 1
    img = S2.outline_text(lines, max(34, round(px * k)), top)
    box = img.getbbox()
    if bad := check_box(W, H, box):
        raise SystemExit(f"подпись вне безопасной зоны: {bad}")
    img.save(dest)
    return box[1], box[3]


def intro_crop(x: dict) -> tuple[int, int, int, int]:
    """Окно записи 1080×1920 под зум z: (x, y, w, h), чётные; fx/fy — место окна (0 — левый/верхний край)."""
    cw, ch = G._even(W / x["z"]), G._even(H / x["z"])
    return G._even((W - cw) * x["fx"]), G._even((H - ch) * x["fy"]), cw, ch


APPX = WORK / "appx"                                     # экраны приложения шириной 800 (в кадре они ≤ 800): распаковщик
_APP: tuple | None = None                                # на видеокарте вдвое легче → больше сборок в лимит памяти (17.11)


def app_proxies() -> tuple[dict, dict]:
    """Заготовки экранов приложения и их размеры: облегчённые 800-px (appx), если есть, иначе исходные skinive2."""
    global _APP
    if _APP is None:
        pxs, wh = dict(S2U.ensure_proxies()), dict(S2U.SRC_WH)
        # стор — исходная запись: облегчённая давала «кадры не те» на сторе (17.11, 4 из 5 браков); остальные — 800 px
        names = {"photo_s": "photo_s_seg", "proc": "proc20", "gauge_s": "gauge_s_seg", "erg_s": "erg_s_seg"}
        if all((APPX / f"{v}.mp4").exists() for v in names.values()):
            pxs.update({k: APPX / f"{v}.mp4" for k, v in names.items()})
            wh = {"store": S2U.SRC_WH["store"], "app": G.probe(APPX / "photo_s_seg.mp4")[1:]}
        _APP = (pxs, wh)
    return _APP


def pieces_of(c: dict, top: int, x0: int, fw: int, fh: int, PXS: dict) -> list[dict]:
    """Куски ролика: откуда, с какого места, сколько кадров, во сколько раз быстрее, окно, размер, место."""
    s = c["scale"]
    ph0, ph1 = S2.PHOTO2
    p0, p1 = SW.PROC
    r0, r1 = SW.GAUGE if c["end"] == "gauge" else SW.ERG
    WH = app_proxies()[1]

    def app(kind: str, crop_y: int) -> tuple:
        sw_, sh_ = WH["store" if kind == "store" else "app"]
        f = sw_ / W
        y0 = round((crop_y + c["crop_dy"]) * f / 2) * 2
        return (0, y0, sw_, round(H * f / 2) * 2)
    x = c["intro"]
    n_in = round(x["len"] * FPS)
    s_len = SW.STORE_END - c["s0"]
    out = [dict(kind="intro", src=str(clip(x["src"])), t=x["t"], n=n_in, rate=1, crop=intro_crop(x), size=(W, H),
                pos=(0, 0), mirror=x["mirror"], pad=None),
           dict(kind="store", src=str(PXS["store_s"]), t=round(c["s0"] - S2U.SEGS["store_s"][1], 3), n=round(s_len * FPS),
                rate=1, crop=app("store", 150), size=(fw, fh), pos=(x0, top), mirror=False, pad=S2U.PAD["store"]),
           dict(kind="photo", src=str(PXS["photo_s"]), t=round(ph0 - S2U.SEGS["photo_s"][1], 3),
                n=round((ph1 - ph0) * FPS), rate=1, crop=app("app", 160), size=(fw, fh), pos=(x0, top), mirror=False,
                pad=S2U.PAD["photo"]),
           dict(kind="proc", src=str(PXS["proc"]), t=0.0, n=round((p1 - p0) / S2U.PROC_K * FPS), rate=1,
                crop=app("app", 150), size=(fw, fh), pos=(x0, top), mirror=False, pad=S2U.PAD["proc"]),
           dict(kind=c["end"], src=str(PXS[f"{c['end']}_s"]), t=round(r0 - S2U.SEGS[f"{c['end']}_s"][1], 3),
                n=round(c["r_len"] * FPS), rate=2 if c["end"] == "gauge" else 1, crop=app("app", 150), size=(fw, fh),
                pos=(x0, top), mirror=False, pad=S2U.PAD[c["end"]], src_n=round((r1 - r0) * FPS))]
    return out


# ---------------- «поле света» ----------------
AMP_W, AMP_C, AMP_CP, AMP_CI = 0.03, 0.035, 0.04, 0.03    # волны; поле на светлых экранах; на фото (осветление); на начале (±)
FQ = 4                                                   # поля считаются в 1/4 размера и растягиваются (они плавные)


def wave_field(rng: random.Random) -> np.ndarray:
    """Волны как в skinive2 (shade_png): значения −1…1, размер кадра/4."""
    w4, h4 = W // FQ, H // FQ
    x = np.linspace(0, 1, w4, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, h4, dtype=np.float32)[:, None]
    ph = (rng.uniform(0, 6.28) + y * rng.uniform(-6, 6)
          + np.sin(y * rng.uniform(2, 5) + rng.uniform(0, 6.28)) * rng.uniform(0.5, 1.5))
    return (0.6 * np.sin(2 * math.pi * rng.uniform(1.2, 2.6) * x + ph)
            + 0.4 * np.sin(2 * math.pi * rng.uniform(2.5, 4.5) * x + ph * 1.7 + rng.uniform(0, 6.28))).astype(np.float32)


def cell_field(rng: random.Random) -> np.ndarray:
    """Случайное мягкое поле 0…1: свои значения в клетках сетки отпечатка (17×16), плавно растянуто до кадра/4."""
    r = np.random.default_rng(rng.randrange(2 ** 32)).random((16, 17), dtype=np.float32)
    im = Image.fromarray(r, "F").resize((W // FQ, H // FQ), Image.Resampling.BICUBIC)
    return np.clip(np.asarray(im, np.float32), 0, 1)


def _up(a: np.ndarray) -> np.ndarray:
    return np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((W, H), Image.Resampling.BILINEAR), np.float32)


def rgba_field(alpha: np.ndarray, colour: int) -> Image.Image:
    """Слой одного цвета (0 — затемнение, 255 — осветление) с прозрачностью alpha (0…1, кадр/4)."""
    img = np.full((H, W, 4), colour, np.uint8)
    img[..., 3] = np.clip(_up(alpha) * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(img, "RGBA")


def rgba_signed(v: np.ndarray) -> Image.Image:
    """Слой со знаком: v < 0 — светлее (белый), v > 0 — темнее (чёрный), сила |v| (кадр/4)."""
    u = _up(v)
    img = np.zeros((H, W, 4), np.uint8)
    img[..., :3] = np.where(u < 0, 255, 0)[..., None]
    img[..., 3] = np.clip(np.abs(u) * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(img, "RGBA")


# ---------------- сборка ----------------
def prepare(c: dict, keep: Path) -> dict:
    """Раскладка, текст, дисклеймер, слои волн и звук ролика (те же случайности, что и в сборке) — без видео.
    По этому прогнозируются отпечатки до сборки (17.11: собирать только заведомо непохожие)."""
    rng = random.Random(c["seed"])
    texts = PROJ[c["proj"]]["texts"]
    with TEXT_LOCK:
        cap_top, cap_bottom = caption_png(texts[c["text"]], c["cap_k"], c["cap_top"], keep / "cap.png")
    s = c["scale"]
    fw, fh = round(W * s / 2) * 2, round(H * s / 2) * 2
    top_min = cap_bottom + 16
    disc_rel = S2U.DISC_REL[c["end"]] - c["crop_dy"]
    top_max = min(H - fh, int(1540 - 50 - disc_rel * s))
    if top_max < top_min:
        raise RuntimeError(f"экран не помещается под текстом: {top_min}–{top_max}")
    top = int(top_min + c["yj"] * (top_max - top_min)) // 2 * 2
    side = (W - fw) // 2
    x0 = int(side + c["xj"] * min(70, side)) // 2 * 2
    with TEXT_LOCK:
        disc = S2.outline_text([S2.DISCLAIMER], S2.DISC_PX, int(top + disc_rel * s))
    dbox = disc.getbbox()
    if bad := check_box(W, H, dbox):
        raise RuntimeError(f"дисклеймер вне безопасной зоны: {bad}")
    disc.save(keep / "disc.png")
    PXS = app_proxies()[0]
    pcs = pieces_of(c, top, x0, fw, fh, PXS)
    nf = sum(p["n"] for p in pcs)
    total = nf / FPS
    n_in = pcs[0]["n"]

    # слои (17.11, замер sk_field_sim): у каждого ролика своё «поле света» — волны + случайное мягкое поле по сетке
    # отпечатка 17×16. На светлых экранах приложения — только затемнением (на белом осветление не видно, половина
    # рисунка пропадала), на тёмном редакторе фото — осветлением. При ОДИНАКОВОЙ раскладке экранов: было 0.1–0.5 % пар
    # с общими кадрами, стало 0 из 1.1 млн (ближайшая пара 50+ бит) — экраны приложения больше не сталкиваются.
    cap = Image.open(keep / "cap.png")
    wv, wv_i = wave_field(rng), wave_field(rng)
    cf, cf_p, cf_i = cell_field(rng), cell_field(rng), cell_field(rng)
    a_main = AMP_W * (0.5 + 0.5 * wv) + AMP_C * cf
    Image.alpha_composite(rgba_field(a_main, 0), cap).save(keep / "layer_main.png", compress_level=1)
    a_ph = AMP_W * (0.5 + 0.5 * wv) + AMP_CP * cf_p
    ph = rgba_field(a_ph, 255)
    cb = cap.getbbox()
    if cb:                                                # подпись не осветляем
        ph.paste((0, 0, 0, 0), (0, max(0, cb[1] - 8), W, min(H, cb[3] + 8)))
    ph.save(keep / "layer_photo.png", compress_level=1)
    v_i = 0.05 * wv + S2U.SHADE_INTRO * wv_i + AMP_CI * (cf_i * 2 - 1)   # начало: со знаком (как было) + поле
    Image.alpha_composite(rgba_signed(v_i), cap).save(keep / "layer_intro.png", compress_level=1)
    return dict(pieces=pcs, nf=nf, n_in=n_in, total=total, cap=(cap_top, cap_bottom), disc=dbox)


def render(c: dict, dest: Path, keep: Path, pp: dict | None = None) -> dict:
    pp = pp or prepare(c, keep)
    pcs, nf, n_in, total = pp["pieces"], pp["nf"], pp["n_in"], pp["total"]
    inputs, fc = [], []
    for i, p in enumerate(pcs):
        gi = G.gpu_input(Path(p["src"]), crop=p["crop"], resize=p["size"])
        inputs += (SHARE_IN + gi) if SHAREDEV else gi
        head = (f"[{i}:v]trim=start={p['t']:.4f}:duration={(p['n'] * p['rate'] + 4) / FPS:.4f},setpts=PTS-STARTPTS,"
                + (f"setpts=PTS/{p['rate']}," if p["rate"] != 1 else "") + f"fps={FPS},format=yuv420p,")
        if p["mirror"]:
            head += "hflip,"
        if p["pad"]:
            head += f"pad={W}:{H}:{p['pos'][0]}:{p['pos'][1]}:color={p['pad']},"
        fc.append(head + f"setsar=1,tpad=stop_mode=clone:stop={p['n'] + 2},trim=end_frame={p['n']},setpts=PTS-STARTPTS[s{i}]")
    fc.append("".join(f"[s{i}]" for i in range(len(pcs))) + f"concat=n={len(pcs)}:v=1:a=0,format=yuv420p[b0]")
    idx, cur = len(pcs), "b0"
    gpu_ov = OV == "gpu"                                  # слои на видеокарте (юзер 17.11 «всё что можно — на видеокарте»);
    if gpu_ov:                                            # каждый кадр всё равно сверяется — сбитый ролик пересобирается
        fc.append("[b0]hwupload_cuda[b0g]")
        cur = "b0g"
    a_ph, n_ph = n_in + pcs[1]["n"], pcs[2]["n"]
    for png, a0, n in ((keep / "layer_intro.png", 0, n_in), (keep / "layer_main.png", n_in, nf - n_in),
                       (keep / "layer_photo.png", a_ph, n_ph), (keep / "disc.png", nf - FPS, FPS)):
        inputs += ["-i", str(png)]
        # format ДО loop: картинка слоя перекодируется один раз, а не на каждом из ~280 кадров (17.11: это съедало
        # несколько секунд процессора на ролик)
        if gpu_ov and HWLOOP:                              # слой загружается на видеокарту ОДИН раз и повторяется там
            fc.append(f"[{idx}:v]format=yuva420p,hwupload_cuda,loop=loop={n - 1}:size=1:start=0,settb=1/{FPS},"
                      f"setpts=N+{a0}[l{idx}]")
            fc.append(f"[{cur}][l{idx}]overlay_cuda=0:0:eof_action=pass[o{idx}]")
        elif gpu_ov:
            fc.append(f"[{idx}:v]format=yuva420p,loop=loop={n - 1}:size=1:start=0,settb=1/{FPS},setpts=N+{a0},"
                      f"hwupload_cuda[l{idx}]")
            fc.append(f"[{cur}][l{idx}]overlay_cuda=0:0:eof_action=pass[o{idx}]")
        else:
            fc.append(f"[{idx}:v]format=yuva420p,loop=loop={n - 1}:size=1:start=0,settb=1/{FPS},setpts=N+{a0}[l{idx}]")
            fc.append(f"[{cur}][l{idx}]overlay=0:0:eof_action=pass:format=yuv420[o{idx}]")
        cur, idx = f"o{idx}", idx + 1
    fc.append(f"[{cur}]null[v]" if gpu_ov else f"[{cur}]format=yuv420p[v]")
    mus = keep / "music.wav"
    U.music(mus, total, random.Random(c["seed"] + 1))        # звук — здесь: у отброшенных по прогнозу его не делаем
    inputs += ["-i", str(mus)]
    (keep / "graph.txt").write_text(";".join(fc), encoding="utf-8")
    cmd = ["ffmpeg", "-v", "error", "-y", *(SHARE_PRE if SHAREDEV else []), *inputs, "-filter_complex_script",
           str(keep / "graph.txt"), "-map", "[v]",
           "-map", f"{idx}:a", "-frames:v", str(nf), "-r", str(FPS), *G.NVENC, "-c:a", "aac", "-b:a", "160k",
           "-t", f"{total:.3f}", *G.CLEAN, str(dest)]
    t0 = time.time()
    with gpu_slot():
        t1 = time.time()
        for attempt in range(2):
            try:
                subprocess.run(cmd, check=True, timeout=300, capture_output=True)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                if attempt == 1:
                    raise RuntimeError(f"ffmpeg: {getattr(e, 'stderr', b'')[-400:]!r}")
    pp["_t"] = dict(wait=t1 - t0, ff=time.time() - t1)
    return pp


# ---------------- проверка кадров ----------------
def _gray(cmd: list[str], w: int, h: int) -> np.ndarray:
    """Распаковка для сверки: SK_HWDEC=1 — видеодекодером (h264 распаковывается побитно так же), иначе процессором."""
    raw = b""
    if __import__("os").environ.get("SK_HWDEC") and cmd[0] == "ffmpeg" and HWSEM.acquire(blocking=False):
        try:                                             # не больше 4 распаковок на видеокарте сразу (память)
            raw = subprocess.run(cmd[:3] + ["-hwaccel", "cuda"] + cmd[3:], capture_output=True).stdout
        finally:
            HWSEM.release()
    if not raw:
        raw = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)


def rect_of(p: dict, pp: dict, last: bool) -> tuple[int, int, int, int] | None:
    """Полоса сверки куска: внутри картинки куска, ниже текста, выше/ниже дисклеймера (последний кусок); кратно 8."""
    x0, y0 = p["pos"]
    x1, y1 = x0 + p["size"][0], y0 + p["size"][1]
    y0 = max(y0, pp["cap"][1] + 16)
    y1 = min(y1, H)
    if last:
        dt, db = pp["disc"][1] - 12, pp["disc"][3] + 12
        y1 = min(y1, dt) if dt - y0 >= 96 else y1
        y0 = y0 if dt - y0 >= 96 else max(y0, db)
    x0, x1 = (x0 + 8) // 8 * 8, (x1 - 8) // 8 * 8
    y0, y1 = (y0 + 7) // 8 * 8, y1 // 8 * 8
    return (x0, y0, x1, y1) if x1 - x0 >= 64 and y1 - y0 >= 64 else None


def decode_checks(path: Path, keep: Path) -> tuple:
    """ОДНА распаковка готового ролика на все проверки (17.11: было три распаковки + пять чтений исходников с начала
    файла — 31 ядро-секунда на ролик из 45): серые кадры 1/8 (сверка с исходником), RGB 54×96 (пустые/повторы),
    17×16 (отпечатки — тем же фильтром, что core.uniq_fast.real_hash)."""
    g, r, h = keep / "g.raw", keep / "r.raw", keep / "h.raw"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-threads", "4", "-i", str(path), "-filter_complex",
                    f"[0:v]split=3[a][b][c];[a]scale={W // Q8}:{H // Q8}:flags=area,format=gray[g];"
                    f"[b]scale=54:96,format=rgb24[r];[c]scale=17:16:flags=area,format=gray[h]",
                    "-map", "[g]", "-f", "rawvideo", str(g), "-map", "[r]", "-f", "rawvideo", str(r),
                    "-map", "[h]", "-f", "rawvideo", str(h)], capture_output=True)
    G_ = np.fromfile(g, np.uint8).reshape(-1, H // Q8, W // Q8).astype(np.float32)
    R_ = np.fromfile(r, np.uint8).reshape(-1, 96, 54, 3)
    H_ = np.fromfile(h, np.uint8).reshape(-1, 16, 17).astype(np.int16)
    return G_, R_, H_


def hash_of(H_: np.ndarray) -> np.ndarray:
    """Отпечатки из кадров 17×16 (как real_hash): ±1 [кадры×2, 256] — прямые и зеркальные."""
    h = (H_[:, :, 1:] > H_[:, :, :-1]).reshape(len(H_), -1)
    m = (H_[:, :, ::-1][:, :, 1:] > H_[:, :, ::-1][:, :, :-1]).reshape(len(H_), -1)
    return np.concatenate([h, m]).astype(np.float32) * 2 - 1


def frame_check(pp: dict, path: Path, keep: Path, margin: float = 0.8, junk: float = 16.0, full: np.ndarray | None = None,
                fast: bool = True) -> list:
    """КАЖДЫЙ кадр ролика против того кадра исходника, что стоит по плану (с теми же окном, масштабом, зеркалом,
    местом и слоями света): ближе другой кадр исходника — повтор/пропуск, ни один не похож — мусор.
    fast: исходник читается сразу с нужного места (-ss) и уменьшается напрямую до 1/8 полосы сверки (окно полосы
    пересчитано в координаты исходника) — без увеличения до полного кадра; fast=False — прежний точный путь."""
    flags, f = [], 0
    lays = {"intro": Image.open(keep / "layer_intro.png"), "main": Image.open(keep / "layer_main.png"),
            "photo": Image.open(keep / "layer_photo.png")}
    if full is None:
        full = _gray(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={W // Q8}:{H // Q8}:flags=area,format=gray",
                      "-f", "rawvideo", "-"], W // Q8, H // Q8)
    if len(full) != pp["nf"]:
        return [("кадров", len(full), pp["nf"])]
    for i, p in enumerate(pp["pieces"]):
        n = p["n"]
        rc = rect_of(p, pp, i == len(pp["pieces"]) - 1)
        if rc is None:
            f += n
            continue
        rx0, ry0, rx1, ry1 = rc
        w8, h8 = (rx1 - rx0) // Q8, (ry1 - ry0) // Q8
        out = full[f:f + n, ry0 // Q8:ry1 // Q8, rx0 // Q8:rx1 // Q8]
        cx, cy, cw, ch = p["crop"]
        pre = min(3, int(p["t"] * FPS))
        ts = p["t"] - pre / FPS
        px_, py_ = p["pos"]
        if fast:
            # окно полосы (в кадре ролика) → окно в исходнике: кусок = crop(cx, cy, cw, ch) → size, [зеркало], место pos
            kx, ky = cw / p["size"][0], ch / p["size"][1]
            u0, u1 = rx0 - px_, rx1 - px_
            if p["mirror"]:
                u0, u1 = p["size"][0] - u1, p["size"][0] - u0
            sx0, sy0 = cx + u0 * kx, cy + (ry0 - py_) * ky
            sw_, sh_ = (u1 - u0) * kx, (ry1 - ry0) * ky
            vf = (f"fps={FPS},crop={max(2, round(sw_))}:{max(2, round(sh_))}:{round(sx0)}:{round(sy0)},"
                  f"scale={w8}:{h8}:flags=area," + ("hflip," if p["mirror"] else "") + "format=gray")
            src = _gray(["ffmpeg", "-v", "error", "-threads", "2", "-ss", f"{ts:.4f}", "-i", p["src"],
                         "-t", f"{(n * p['rate'] + pre + 8) / FPS:.4f}", "-vf", vf, "-f", "rawvideo", "-"], w8, h8)
        else:
            vf = (f"trim=start={ts:.4f}:duration={(n * p['rate'] + pre + 8) / FPS:.4f},setpts=PTS-STARTPTS,fps={FPS},"
                  f"crop={cw}:{ch}:{cx}:{cy},scale={p['size'][0]}:{p['size'][1]}:flags=bicubic,"
                  + ("hflip," if p["mirror"] else "")
                  + f"crop={rx1 - rx0}:{ry1 - ry0}:{rx0 - px_}:{ry0 - py_},scale={w8}:{h8}:flags=area,format=gray")
            src = _gray(["ffmpeg", "-v", "error", "-i", p["src"], "-vf", vf, "-f", "rawvideo", "-"], w8, h8)
        for key in (["intro"] if p["kind"] == "intro" else ["main", "photo"] if p["kind"] == "photo" else ["main"]):
            im = lays[key].crop((rx0, ry0, rx1, ry1)).resize((w8, h8), Image.Resampling.BOX)
            a = np.asarray(im, np.float32)
            al = a[..., 3] / 255
            g = a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
            src = src * (1 - al) + g * al
        last_src = len(src) - 1
        if last_src < 0:
            return [("исходник не прочитался", p["kind"])]
        for j in range(n):
            k = min(pre + j * p["rate"], last_src)
            d = {dk: float(np.abs(out[j] - src[k + dk]).mean()) for dk in range(-3, 4) if 0 <= k + dk <= last_src}
            best = min(d, key=d.get)
            if d[best] > junk:
                flags.append((f + j, p["kind"], "мусор", round(d[best], 1)))
            elif best != 0 and d[0] - d[best] > margin:
                flags.append((f + j, p["kind"], best, round(d[0] - d[best], 2)))
        f += n
    return flags


# ---------------- уникальность ----------------
def h30_of(path: Path) -> np.ndarray:
    h, m = UF.real_hash(path, (0, H))
    return np.concatenate([np.asarray(h, np.float32), np.asarray(m, np.float32)]) * 2 - 1


import torch  # noqa: E402

BDEV = "cuda" if torch.cuda.is_available() else "cpu"   # сверка с банками — на видеокарте (half, куски по 128 тыс.):
BDT = torch.half if BDEV == "cuda" else torch.float32    # на процессоре 1.2 млн кадров × кандидат ели все ядра (17.11)


HC = WORK / "h30"                                        # кэш отпечатков принятых роликов (перезапуск за секунды, не минуты)


def h30_save(name: str, h: np.ndarray) -> None:
    HC.mkdir(parents=True, exist_ok=True)
    np.save(HC / f"{name}.npy", np.packbits(h > 0, axis=1))


def h30_cached(f: Path) -> np.ndarray:
    c = HC / f"{f.name}.npy"
    if c.exists() and c.stat().st_mtime >= f.stat().st_mtime:
        return np.unpackbits(np.load(c), axis=1)[:, :256].astype(np.float32) * 2 - 1
    h = h30_of(f)
    h30_save(f.name, h)
    return h


def old_bank() -> torch.Tensor:
    """Все прошлые skinive (каждый кадр): ±1 [кадры×2, 256] — прямые и зеркальные, на видеокарте (~0.6 ГБ)."""
    d = np.load(OLD30, allow_pickle=True)["d"].item()
    hm = np.concatenate([v[0] for v in d.values()]).astype(np.float16)       # (кадры, 2, 256) 0/1
    print(f"прошлые skinive: {len(d)} роликов, {len(hm)} кадров", flush=True)
    return torch.from_numpy(np.concatenate([hm[:, 0], hm[:, 1]]) * 2 - 1).to(BDEV).to(BDT)


def as_bank(x) -> torch.Tensor:
    return x if isinstance(x, torch.Tensor) else torch.from_numpy(np.asarray(x, np.float32)).to(BDEV).to(BDT)


def near(h: np.ndarray, bank, thr: int = THR) -> int:
    """Сколько кадров кандидата (прямых) ближе thr бит к какому-нибудь кадру банка (прямому или зеркальному).
    ±1-векторы: расстояние = (256 − скалярное)/2, целые ≤ 256 — в half хранятся точно."""
    bank = as_bank(bank)
    if not len(bank):
        return 0
    q = as_bank(h[: len(h) // 2])
    hit = torch.zeros(len(q), dtype=torch.bool, device=BDEV)
    rev = 0
    with torch.no_grad():
        for i in range(0, len(bank), 131072):
            m = (256 - q @ bank[i:i + 131072].T) / 2 <= thr
            hit |= m.any(1)
            rev += int(m.any(0).sum())
    # 17.11 финальная проверка: считали только кадры кандидата — 1–2 его кадра совпадали с НЕПОДВИЖНЫМ куском
    # принятого ролика (42 кадра, 16 % пары). Теперь и в обратную сторону: кадры банка рядом с кандидатом.
    return max(int(hit.sum()), rev)


def build_one(c: dict, tmp: Path, keep: Path | None = None, pp: dict | None = None) -> tuple:
    keep = keep or tmp.with_suffix("")
    keep.mkdir(parents=True, exist_ok=True)
    try:
        pp = render(c, tmp, keep, pp)
        ta = time.time()
        G_, R_, H_ = decode_checks(tmp, keep)             # одна распаковка на все проверки
        bad = G.bad_frames_arr(R_)
        tb = time.time()
        fr = [] if bad else frame_check(pp, tmp, keep, full=G_)
        if fr:                                            # сомнение — перепроверка прежним точным путём
            fr = frame_check(pp, tmp, keep, full=G_, fast=False)
        tc = time.time()
        h = hash_of(H_) if not bad and not fr else None
        TIMES.append((pp["_t"]["wait"], pp["_t"]["ff"], tb - ta, tc - tb, time.time() - tc))
    finally:
        for f in keep.glob("*"):
            f.unlink()
        keep.rmdir()
    return c, tmp, h, bad, fr


TIMES: list = []                                         # (ожидание очереди, сборка, bad_frames, сверка, отпечатки), с


# ---------------- прогноз отпечатков до сборки (видеокарта) ----------------
class Predictor:
    """Кадры исходников в 1/8 (серые, как Y) на видеокарте: вступления 135×240, экраны приложения 100×~217 (~0.3 ГБ).
    predict(pp, keep): каждый кадр будущего ролика — обрезка/масштаб/зеркало/место кусков (roi_align), поля цветом
    края, слои волн+текст+дисклеймер из тех же PNG, что пойдут в сборку → dHash 16×17 (как real_hash, весь кадр)."""

    def __init__(self) -> None:
        self.src: dict = {}
        self.full: dict = {}

    def _load(self, path: str, w8: int, h8: int):
        if path not in self.src:
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={w8}:{h8}:flags=area,format=gray",
                                  "-f", "rawvideo", "-"], capture_output=True).stdout
            a = np.frombuffer(raw, np.uint8).reshape(-1, h8, w8)
            self.src[path] = torch.from_numpy(a.copy()).to(BDEV).to(torch.float32)
        return self.src[path]

    def prewarm(self) -> None:
        names = {n for P in PROJ.values() for n, _, _ in P["spans"]}
        for n in sorted(names):
            self.source(str(clip(n)))

    def source(self, path: str):
        if path not in self.full:
            _c, sw, sh = G.probe(Path(path))
            self.full[path] = (sw, sh)
        sw, sh = self.full[path]
        return self._load(path, max(2, round(sw / Q8)), max(2, round(sh / Q8))), sw, sh

    @staticmethod
    def _layer(png: Path):
        im = Image.open(png).convert("RGBA").resize((W // Q8, H // Q8), Image.Resampling.BOX)
        a = np.asarray(im, np.float32)
        al = a[..., 3] / 255
        g = 16 + (a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114) * 219 / 255   # как Y (tv)
        return torch.from_numpy(al).to(BDEV), torch.from_numpy(g).to(BDEV)

    def predict_intro(self, pp: dict, keep: Path):
        """Только начало ролика (рука/селфи): прямые отпечатки ±1 [кадры, 256] — для отсева до сборки."""
        one = dict(pp, pieces=pp["pieces"][:1], nf=pp["n_in"])
        from torchvision.ops import roi_align  # noqa: F401
        return self.predict(one, keep, intro_only=True)

    def predict(self, pp: dict, keep: Path, frames_out: bool = False, intro_only: bool = False):
        from torchvision.ops import roi_align
        h8, w8 = H // Q8, W // Q8
        frames = []
        for p in pp["pieces"]:
            S, sw, sh = self.source(p["src"])
            n = p["n"]
            k0 = math.ceil(p["t"] * FPS - 1e-6)                 # trim=start берёт первый кадр с pts ≥ t (замер 17.11)
            idx = torch.clamp(torch.arange(n, device=BDEV) * p["rate"] + k0, max=len(S) - 1)
            cx, cy, cw, ch = p["crop"]
            sx, sy = S.shape[2] / sw, S.shape[1] / sh
            oh, ow = max(1, round(p["size"][1] / Q8)), max(1, round(p["size"][0] / Q8))
            boxes = torch.tensor([[cx * sx, cy * sy, (cx + cw) * sx, (cy + ch) * sy]], device=BDEV).repeat(n, 1)
            boxes = torch.cat([torch.arange(n, device=BDEV, dtype=torch.float32)[:, None], boxes], 1)
            crop = roi_align(S[idx][:, None], boxes, (oh, ow), 1.0, 2, True)[:, 0]
            if p["mirror"]:
                crop = crop.flip(-1)
            if p["pad"]:
                col = int(p["pad"], 16)
                r, g, b = (col >> 16) & 255, (col >> 8) & 255, col & 255
                fill = 16 + (0.299 * r + 0.587 * g + 0.114 * b) * 219 / 255
                cv = torch.full((n, h8, w8), fill, device=BDEV)
                y0, x0 = round(p["pos"][1] / Q8), round(p["pos"][0] / Q8)
                hh, ww = min(oh, h8 - y0), min(ow, w8 - x0)
                cv[:, y0:y0 + hh, x0:x0 + ww] = crop[:, :hh, :ww]
                crop = cv
            frames.append(crop)
        F_ = torch.cat(frames)
        n_in, nf = pp["n_in"], pp["nf"]
        if intro_only:
            lays = ((keep / "layer_intro.png", 0, n_in),)
        else:
            a_ph = n_in + pp["pieces"][1]["n"]
            lays = ((keep / "layer_intro.png", 0, n_in), (keep / "layer_main.png", n_in, nf),
                    (keep / "layer_photo.png", a_ph, a_ph + pp["pieces"][2]["n"]), (keep / "disc.png", nf - FPS, nf))
        for png, a0, a1 in lays:
            al, g = self._layer(png)
            F_[a0:a1] = F_[a0:a1] * (1 - al) + g * al
        x = torch.nn.functional.adaptive_avg_pool2d(F_[:, None], (16, 17))[:, 0]
        h = (x[..., 1:] > x[..., :-1]).reshape(nf, -1)
        xm = x.flip(-1)
        m = (xm[..., 1:] > xm[..., :-1]).reshape(nf, -1)
        if frames_out:
            return (h.to(BDT) * 2 - 1), (m.to(BDT) * 2 - 1), F_
        return (h.to(BDT) * 2 - 1), (m.to(BDT) * 2 - 1)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0, help="сколько TT и сколько YT у каждого проекта")
    ap.add_argument("--proj", type=int, nargs="*", default=[10, 11])
    ap.add_argument("--test", type=int, default=0)
    ap.add_argument("--probe", type=int, default=0)
    ap.add_argument("--seed", type=int, default=17111)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--ov", choices=("cpu", "gpu"), default=None, help="слои: cpu (overlay в памяти) | gpu (overlay_cuda)")
    ap.add_argument("--ab", type=int, default=0, help="замер: N одинаковых кандидатов со слоями на процессоре и на видеокарте")
    ap.add_argument("--pcheck", type=int, default=0, help="замер точности прогноза отпечатков на N роликах")
    a = ap.parse_args()
    global OV
    if a.ov:
        OV = a.ov
    import qa_batch as Q
    WORK.mkdir(parents=True, exist_ok=True)
    S2U.ensure_proxies()
    rng = random.Random(a.seed)
    if a.pcheck:
        P = Predictor()
        d = WORK / "pcheck"
        d.mkdir(parents=True, exist_ok=True)
        errs = []
        for i in range(a.pcheck):
            c = candidate(rng, a.proj[i % len(a.proj)], i % len(PROJ[a.proj[i % len(a.proj)]]["texts"]))
            keep = d / f"k{i}"
            keep.mkdir(parents=True, exist_ok=True)
            try:
                pp = prepare(c, keep)
            except RuntimeError as e:
                print("  пропуск:", e)
                continue
            ph, _ = P.predict(pp, keep)
            _, tmp, h, bad, fr = build_one(c, d / f"p{i}.mp4", keep, pp)
            hr = torch.from_numpy(h30_of(tmp)[: pp["nf"]]).to(BDEV).to(BDT) if h is None else as_bank(h[: pp["nf"]])
            n = min(len(ph), len(hr))
            e = ((ph[:n] != hr[:n]).sum(1)).float().cpu().numpy()
            errs.append(e)
            print(f"  {i}: {c['proj']} {c['end']} ошибка прогноза, бит на кадр: среднее {e.mean():.1f}, 95 % {np.percentile(e, 95):.0f}, макс {e.max():.0f}", flush=True)
        e = np.concatenate(errs)
        print(f"ИТОГ прогноза: среднее {e.mean():.1f} бит, 95 % {np.percentile(e, 95):.0f}, 99 % {np.percentile(e, 99):.0f}", flush=True)
        return 0
    if a.ab:
        import time as _t
        cs = [candidate(rng, p, i % len(PROJ[p]["texts"])) for i in range(a.ab) for p in a.proj][:a.ab]
        d = WORK / "ab"
        d.mkdir(parents=True, exist_ok=True)
        for mode in ("cpu", "gpu"):
            OV = mode
            for f in d.glob(f"{mode}_*"):
                f.unlink()
            t0 = _t.time()
            with ThreadPoolExecutor(a.jobs) as ex:
                res = list(ex.map(lambda ic: build_one(ic[1], d / f"{mode}_{ic[0]:02d}.mp4"), enumerate(cs)))
            dt = _t.time() - t0
            badn = sum(1 for _, _, _, b, fr in res if b or fr)
            print(f"{mode}: {len(cs)} роликов за {dt:.0f} с ({dt / len(cs):.1f} с на ролик при {a.jobs} сразу), "
                  f"с браком {badn}: {[(Path(t).name, (b or fr)[:3]) for _, t, _, b, fr in res if b or fr]}", flush=True)
        return 0
    if a.test or a.probe:
        out = WORK / ("test" if a.test else "probe")
        out.mkdir(parents=True, exist_ok=True)
        for f in out.glob("*.mp4"):
            f.unlink()
        k = a.test or a.probe
        cs = [candidate(rng, p, i % len(PROJ[p]["texts"])) for p in a.proj for i in range(k)]
        cand = WORK / "cand_t"
        cand.mkdir(parents=True, exist_ok=True)
        res = []
        with ThreadPoolExecutor(a.jobs) as ex:
            for c, tmp, h, bad, fr in ex.map(lambda ic: build_one(ic[1], cand / f"t{ic[0]:03d}.mp4"), enumerate(cs)):
                dst = out / f"skinive{c['proj']}_text{c['text'] + 1}_{len(res) + 1:03d}.mp4"
                tmp.replace(dst)
                print(f"  {dst.name}: {c['intro']['src']} @{c['intro']['t']} z{c['intro']['z']}, {c['end']}, "
                      f"брак {bad[:4] if bad else ''}{fr[:4] if fr else ''}", flush=True)
                res.append((dst, h))
        hs = [h for _, h in res if h is not None]
        pairs = hit = 0
        for i in range(len(hs)):
            for j in range(i + 1, len(hs)):
                pairs += 1
                hit += near(hs[i], hs[j]) > 0
        print(f"пар {pairs}, с общими кадрами {hit}", flush=True)
        if a.probe or a.test:
            ob = old_bank()
            for dst, h in res:
                if h is not None:
                    print(f"  {dst.name}: кадров, узнаваемых в прошлых skinive: {near(h, ob)}", flush=True)
        return 0

    outs = {(p, t): ROOT / "output" / f"skinive{p}_{t.upper()}_{a.n}" for p in a.proj for t in ("tt", "yt")}
    for d in outs.values():
        d.mkdir(parents=True, exist_ok=True)
    name = lambda p, t, n: outs[(p, t)] / f"skinive{p}_{t}_{n:03d}_1.mp4"   # noqa: E731
    queues = {(p, t): [n for n in range(1, a.n + 1) if not name(p, t, n).exists()] for p in a.proj for t in ("tt", "yt")}
    have = [name(p, t, n) for p in a.proj for t in ("tt", "yt") for n in range(1, a.n + 1) if name(p, t, n).exists()]
    bank_old = old_bank()
    with ThreadPoolExecutor(8) as ex:
        hh = list(ex.map(h30_cached, have))
    bank = as_bank(np.concatenate(hh) if hh else np.zeros((0, 256), np.float32))
    total = len(have) + sum(len(q) for q in queues.values())
    print(f"готовых: {len(have)}, собрать: {total - len(have)}", flush=True)
    man_f = WORK / "manifest.json"
    man = json.loads(man_f.read_text(encoding="utf-8")) if man_f.exists() else {}
    cand = WORK / "cand"
    cand.mkdir(parents=True, exist_ok=True)
    done = len(have)
    Q._state.update(done=done, total=total)
    Q.tick("skinive 10/11: сборка + проверка каждого кадра — принят только ролик без общих кадров со всеми")
    tried = rej_u = rej_f = 0
    order = [k for k in queues]
    turn = 0

    def next_slot():
        nonlocal turn
        for _ in range(len(order)):
            key = order[turn % len(order)]
            turn += 1
            if queues[key]:
                return key
        return None
    # 17.11: новое зерно на каждый запуск — с тем же зерном после перезапуска шли копии уже принятых роликов
    rng = random.Random(a.seed + len(have) * 7919 + int(time.time()))
    texts_turn = {p: 0 for p in a.proj}
    PRED = Predictor()
    PRED.prewarm()
    pend_h: dict = {}
    rej_p = 0
    # 17.11: подготовка кандидата (подпись, слои, прогноз начала) шла в главном потоке по одному — 6 сборщиков и
    # видеокарта ждали его. Теперь кандидаты готовит свой пул потоков впрок, главный поток только решает и раздаёт.
    from collections import deque
    PREP_N = 4                                            # готовых кандидатов впрок на проект

    def prep_one(c: dict, kp: Path):
        kp.mkdir(parents=True, exist_ok=True)
        try:
            pp = prepare(c, kp)
            return c, kp, pp, PRED.predict_intro(pp, kp)[0]
        except RuntimeError:
            for f_ in kp.glob("*"):
                f_.unlink()
            kp.rmdir()
            return None

    def drop(kp: Path) -> None:
        for f_ in kp.glob("*"):
            f_.unlink()
        kp.rmdir()
    last_ec = time.time()
    with ThreadPoolExecutor(a.jobs) as ex, ThreadPoolExecutor(4) as prep:
        live: dict = {}
        prepq = {p: deque() for p in a.proj}
        while any(queues.values()) or live:
            for p in a.proj:                              # пополнить запас готовых кандидатов
                open_p = sum(len(queues[k]) for k in queues if k[0] == p)
                while open_p and len(prepq[p]) < PREP_N:
                    tried += 1
                    c = candidate(rng, p, texts_turn[p] % len(PROJ[p]["texts"]))
                    texts_turn[p] += 1
                    prepq[p].append(prep.submit(prep_one, c, cand / f"c{tried:05d}"))
            progressed = True
            while len(live) < a.jobs and progressed:
                progressed = False
                for _ in range(len(order)):
                    key = order[turn % len(order)]
                    turn += 1
                    q = prepq[key[0]]
                    if (not queues[key] or sum(1 for v in live.values() if v == key) >= len(queues[key])
                            or not q or not q[0].done()):
                        continue
                    res = q.popleft().result()
                    progressed = True
                    if res is None:
                        break
                    c, kp, pp, pi = res
                    # прогноз начала ролика: похоже на принятые или на ещё собирающиеся — не собираем
                    pend = torch.cat(list(pend_h.values())) if pend_h else None
                    hit = int(((256 - pi @ bank.T) / 2 <= PRED_THR).any(1).sum()) if len(bank) else 0
                    if pend is not None:
                        hit += int(((256 - pi @ pend.T) / 2 <= PRED_THR).any(1).sum())
                    if hit > PRED_MAXF:
                        rej_p += 1
                        drop(kp)
                        break
                    fu_ = ex.submit(build_one, c, kp.with_suffix(".mp4"), kp, pp)
                    live[fu_] = key
                    pend_h[fu_] = pi
                    break
            heads = [q[0] for q in prepq.values() if q and not q[0].done()]
            if not live and not heads and not any(queues.values()):
                break
            fin, _ = wait(list(live) + heads, timeout=1.0, return_when=FIRST_COMPLETED)
            # 17.11 14:06: кэш видеопамяти прогноза рос до ~3.5 ГБ, память > GPU_VRAM_MAX_MB без единой сборки —
            # очередь gpu_slot ждала вечно. Раз в 10 с отдаём неиспользуемый кэш.
            if time.time() - last_ec > 10 and torch.cuda.is_available():
                torch.cuda.empty_cache()
                last_ec = time.time()
            fin = [f for f in fin if f in live]
            for fu in fin:
                key = live.pop(fu)
                pend_h.pop(fu, None)
                try:
                    c, tmp, h, bad, fr = fu.result()
                except Exception as e:                       # noqa: BLE001
                    print("  ОШИБКА сборки кандидата:", str(e)[:300], flush=True)
                    continue
                if bad or fr:
                    rej_f += 1
                    print(f"  брак {tmp.name}: {('bad_frames ' + str(bad[:5])) if bad else ('кадры не те ' + str(fr[:4]))}",
                          flush=True)
                    tmp.unlink(missing_ok=True)
                    continue
                nn = near(h, bank) if queues[key] else 0
                no = near(h, bank_old) if queues[key] and not nn else 0
                # ТЗ «0–1 % даже с тем что было»: с прошлыми допускаем ≤ OLD_MAX кадров (≤ 0.7 %), между новыми — 0
                if not queues[key] or nn > NEW_MAX or no > OLD_MAX:
                    rej_u += 1
                    print(f"  похож {tmp.name} (s{c['proj']} {c['intro']['src']}): кадров рядом с новыми {nn}, с прошлыми {no}",
                          flush=True)
                    tmp.unlink(missing_ok=True)
                    continue
                n = queues[key].pop(0)
                dst = name(key[0], key[1], n)
                tmp.replace(dst)
                h30_save(dst.name, h)
                man[dst.name] = c
                bank = torch.cat([bank, as_bank(h)])
                man_f.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
                done += 1
                Q._state.update(done=done)
                Q.tick()
                if done % 10 == 0 and TIMES:
                    tm = np.mean(np.array(TIMES[-40:]), 0)
                    print(f"    время на ролик: очередь {tm[0]:.1f} с, сборка {tm[1]:.1f}, bad_frames {tm[2]:.1f}, сверка {tm[3]:.1f}, "
                          f"отпечатки {tm[4]:.1f}", flush=True)
                if done % 10 == 0:
                    print(f"  ✓ {done}/{total} (кандидатов {tried}, отброшено по прогнозу {rej_p}, похожих после сборки {rej_u}, брак {rej_f})", flush=True)
    for q_ in prepq.values():                             # неиспользованные заготовки кандидатов — убрать
        for fu_ in q_:
            try:
                r_ = fu_.result()
                if r_:
                    drop(r_[1])
            except Exception:                              # noqa: BLE001
                pass
    print(f"ИТОГ: {done}/{total} → {', '.join(str(d) for d in outs.values())}; собрано {tried}, похожих отсеяно {rej_u}, "
          f"брак {rej_f}", flush=True)
    Q.PROG.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
