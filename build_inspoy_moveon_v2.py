#!/usr/bin/env python3
"""
Inspoy «the EXACT day I moved on from him» v2 (18.11, «максимальный уник»): 200 YT + 100 TT по 9 с, общих кадров
0–1 % со всеми новыми и со всеми 450 сданными (output/_work/moveon_v2/old_bank.npz). Формат прежний
(build_inspoy_moveon.py --short 9): шок-лицо с хуком → страницы Outfit Report: 6 серых 40–50 % по полдоли, первый
яркий — на дропе трека вместе с «the day I blocked him 🫡», дальше яркие 85–95 % по доле. Проценты по возрастанию.

Что нового (рецепт build_skinive10.py):
- пул образов: старые 23 + новые 24 (downloads/inspoy_moveon/v2, промпты output/inspoy_moveon/PROMPTS_outfits_v2.md);
- страница отчёта рисуется браузером ОДИН раз на образ (окно фото прозрачное) и плашка «NN % Match» — один раз на
  процент; фото ролика (своё кадрирование, зеркало, цвет) вклеивается под страницу в памяти;
- лицо — джамп-кат из 3 дублей: A — 9 отсмотренных окон (downloads/gw_hidden2/proxyA, 1080×1920 30 к/с),
  B — 4 окна proxyB; у ролика свой зум, сдвиг, зеркало;
- «поле света» у каждого ролика (волны + клетки сетки отпечатка 17×16) на лице и на страницах;
- прогноз отпечатков ДО сборки (страницы — картинки, лицо — тем же фильтром в памяти), похожие не собираются;
- после сборки одна распаковка: отпечатки каждого кадра, bad_frames, покадровая сверка с планом;
  принимается, если ≤ 2 кадров ближе 40 бит к банку (в обе стороны).

  python build_inspoy_moveon_v2.py --test 4                    # → output/inspoy_moveon_v2_test
  python build_inspoy_moveon_v2.py --yt 200 --tt 100 --jobs 6  # → output/inspoy_moveon_1_YT_200, _TT_100
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_inspoy_moveon as BM  # noqa: E402
import build_dad_trucker_carousels as DT  # noqa: E402
import core.gpu_ffmpeg as G  # noqa: E402
from core.gpu_slots import gpu_slot  # noqa: E402

W, H, FPS = 1080, 1920, 30
D = BM.D
V2 = D / "v2"
WORK = ROOT / "output" / "_work" / "moveon_v2"
TPL = WORK / "tpl"
ACC = WORK / "acc"                                       # отпечатки принятых роликов (перезапуск без пересчёта)
OLD_BANK = WORK / "old_bank.npz"
PROG = ROOT / "output" / "_work" / "_qa_progress" / f"{os.getpid()}.json"
TOTAL_S = 9.0
NF = int(TOTAL_S * FPS)
THR, ACC_MAX = 40, 2
Q8 = 8

# ---------------- образы ----------------
# (фото, %, оценки Color/Shape/Aesthetics/Outfit, поводы, вердикт) — старые из build_inspoy_moveon + новые v2
NEW_A_DULL = [
    ("A21", ("Bad", "Bad", "Good", "Bad"), ("Everyday",),
     "Heather grey from head to toe flattens your contrast. A clear jewel tone near your face would wake the whole look up."),
    ("A22", ("Bad", "Good", "Bad", "Bad"), ("Everyday",),
     "Beige and taupe are too warm and dusty for your cool coloring. The layers add bulk without adding life."),
    ("A23", ("Bad", "Good", "Good", "Bad"), ("Everyday", "Work"),
     "Khaki sits muddy against your skin. Keep the relaxed shape but switch to a crisp, cool shade."),
    ("A24", ("Bad", "Bad", "Good", "Bad"), ("Everyday",),
     "Cozy, but oatmeal on oatmeal melts into your complexion. Your palette needs clear color and contrast."),
    ("A25", ("Bad", "Bad", "Bad", "Good"), ("Everyday",),
     "Stone grey mutes your features and the baggy overall hides your shape. Try one fitted, vivid piece."),
    ("A26", ("Bad", "Good", "Bad", "Bad"), ("Everyday", "Work"),
     "Camel and grey together drain your natural brightness. A cool, saturated coat would do much more for you."),
]
NEW_A_BRIGHT = [
    ("A27", ("Perfect", "Perfect", "Perfect", "Perfect"), ("Work", "Dinner", "Date Night"),
     "Sapphire is one of your power colors, and the gold belt defines your waist beautifully."),
    ("A28", ("Perfect", "Perfect", "Good", "Perfect"), ("Work", "Party"),
     "Cherry red is your signature shade. The cropped blazer and flared trousers give a confident, long line."),
    ("A29", ("Perfect", "Good", "Perfect", "Perfect"), ("Date Night", "Dinner"),
     "Icy lavender against black is clear and high-contrast, exactly what your cool coloring loves."),
    ("A30", ("Perfect", "Perfect", "Perfect", "Good"), ("Party", "Date Night"),
     "Magenta lights up your face and the puff sleeves balance your frame. Playful and polished."),
    ("A31", ("Perfect", "Perfect", "Perfect", "Perfect"), ("Work", "Dinner", "Party"),
     "Crisp bright white is right in your palette, and the black belt sharpens your silhouette."),
    ("A32", ("Perfect", "Good", "Perfect", "Perfect"), ("Dinner", "Party", "Date Night"),
     "Deep emerald brings out your eyes, and the velvet adds richness without overpowering you."),
]
NEW_B_DULL = [
    ("B21", ("Bad", "Bad", "Bad", "Good"), ("Everyday",),
     "Cool grey sits flat on your olive skin and hides your shape. Your coloring needs warm, saturated shades."),
    ("B22", ("Bad", "Good", "Good", "Bad"), ("Everyday",),
     "Sand beige blends right into your skin tone. Keep the soft layers, but add one rich, warm color."),
    ("B23", ("Bad", "Bad", "Good", "Bad"), ("Everyday",),
     "Greige drains the warmth from your complexion and the loose fit swallows your frame."),
    ("B24", ("Bad", "Bad", "Bad", "Bad"), ("Everyday",),
     "Taupe mutes your features and the hoodie dress has no shape. Bring in a deep, warm piece near the face."),
    ("B25", ("Bad", "Good", "Bad", "Good"), ("Everyday", "Work"),
     "All-grey layers pull the glow from your skin. A warm accent would bring your face back to life."),
    ("B26", ("Bad", "Good", "Bad", "Bad"), ("Everyday",),
     "Oatmeal is too pale and dusty for your warm coloring. Swap it for terracotta, olive or camel."),
]
NEW_B_BRIGHT = [
    ("B27", ("Perfect", "Perfect", "Perfect", "Perfect"), ("Date Night", "Party", "Dinner"),
     "Rust is one of your best colors. The satin glows against your skin and the gold jewelry finishes it."),
    ("B28", ("Perfect", "Perfect", "Good", "Perfect"), ("Work", "Dinner"),
     "Olive is right in your warm palette, and the cream camisole keeps the suit soft and elegant."),
    ("B29", ("Perfect", "Good", "Perfect", "Perfect"), ("Date Night", "Dinner"),
     "Terracotta makes your skin glow, and the matching set gives you one long, flattering line."),
    ("B30", ("Perfect", "Perfect", "Perfect", "Good"), ("Work", "Dinner"),
     "Golden mustard with chocolate brown is rich and warm, exactly what your coloring loves."),
    ("B31", ("Perfect", "Perfect", "Perfect", "Perfect"), ("Dinner", "Date Night", "Party"),
     "Deep teal brightens your complexion, and the camel trench adds a polished, warm frame."),
    ("B32", ("Perfect", "Good", "Perfect", "Perfect"), ("Vacation", "Date Night"),
     "Warm coral is your signature color, and the off-shoulder line shows off your neck and shoulders."),
]


def _new(rows, pct):
    return [(V2 / f"{k}.jpg", pct, r, c, v) for k, r, c, v in rows]


POOLS = {
    "A": dict(dull=BM.DULL + _new(NEW_A_DULL, 45), bright=BM.BRIGHT + _new(NEW_A_BRIGHT, 90)),
    "B": dict(dull=BM.DULL_B + _new(NEW_B_DULL, 45), bright=BM.BRIGHT_B + _new(NEW_B_BRIGHT, 90)),
}


def ekey(e) -> str:
    return Path(e[0]).stem


# ---------------- лицо ----------------
PA, PB = ROOT / "downloads" / "gw_hidden2" / "proxyA", ROOT / "downloads" / "gw_hidden2" / "proxyB"
# окна шока (отсмотрено 18.11 по листу 0.5 с): клип, начало, конец
TAKES = {
    "A": [(PA / "IMG_5721.mp4", 0.35, 1.45),   # ладонь у рта
          (PA / "IMG_5721.mp4", 2.90, 4.00),   # глаза круглые (крупно)
          (PA / "IMG_5721.mp4", 5.85, 6.95),   # «вау», рот открыт
          (PA / "IMG_5729.mp4", 3.55, 5.00),   # «о боже», ладонь у щеки
          (PA / "IMG_5729.mp4", 5.20, 6.40),   # рот открыт, руки у щёк
          (PA / "IMG_5732.mp4", 0.00, 1.50),   # ладонь у рта
          (PA / "IMG_5737.mp4", 3.00, 4.60),   # брови вверх, «вот это да»
          (PA / "IMG_5724.mp4", 0.00, 1.20),   # рот открыт, восторг
          (PA / "IMG_5723.mp4", 3.50, 5.30),   # ладонь у рта, «не может быть»
          (PA / "IMG_5733.mp4", 5.40, 6.60)],  # ладонь у рта
    # B (лист 0.33 с, 18.11): прежние 4 окна разбиты на 8 моментов шока
    "B": [(PB / "IMG_8077.mp4", 0.25, 1.25),   # руки вверх, рот открыт
          (PB / "IMG_8077.mp4", 1.35, 3.40),   # ладони на щеках
          (PB / "IMG_8079.mp4", 0.75, 2.55),   # «чего?!» глаза круглые
          (PB / "IMG_8079.mp4", 2.55, 3.45),   # рот открыт
          (PB / "IMG_8084.mp4", 0.25, 1.50),   # рот открыт, рука у лица
          (PB / "IMG_8084.mp4", 3.30, 4.40),   # руки вверх, кричит
          (PB / "IMG_8085.mp4", 0.95, 2.40),   # ладонь у рта
          (PB / "IMG_8085.mp4", 2.40, 3.40)],  # руки вверх, рот открыт
}
DUR: dict[str, float] = {}


def dur(p: Path) -> float:
    k = str(p)
    if k not in DUR:
        DUR[k] = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                       str(p)], capture_output=True, text=True).stdout)
    return DUR[k]


# ---------------- время ----------------
BEAT, DROP = BM.BEAT, BM.DROP
PRE = 6
STEP = BEAT / 2
T_FACE = DROP - BEAT * PRE
T_SWITCH = T_FACE + STEP * PRE
A_OFF = DROP - T_SWITCH
_b = [T_FACE + k * STEP for k in range(PRE + 1)] + [T_SWITCH + k * BEAT for k in range(1, 5)] + [TOTAL_S]
FB = [round(t * FPS) for t in _b]
N_FACE = FB[0]
N_PAGES = [b - a for a, b in zip(FB, FB[1:])]           # 6 серых + 5 ярких, кадров на страницу
assert len(N_PAGES) == 11 and sum(N_PAGES) + N_FACE == NF, (N_FACE, N_PAGES)


def prog(stage: str, done: int = 0, total: int | None = None) -> None:
    try:
        PROG.parent.mkdir(parents=True, exist_ok=True)
        PROG.write_text(json.dumps(dict(stage=stage, done=done, total=total), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ---------------- шаблоны страниц (браузер — один раз) ----------------
def _shots(pg, html_text: str, bg: str, hide_badge: bool):
    html = BM.CON / f"_tmp_v2_{os.getpid()}_{threading.get_ident()}.html"
    css = (f"<style>.photoWrapper{{background:{bg}!important}}.photoWrapper img{{visibility:hidden!important}}"
           + (".matchBlock{visibility:hidden!important}" if hide_badge else "") + "</style>")
    html.write_text(html_text.replace("</head>", css + "</head>", 1), encoding="utf-8")
    pg.goto(html.as_uri())
    pg.wait_for_load_state("networkidle")
    pg.evaluate("document.fonts.ready")
    box = pg.locator("#phone").bounding_box()
    pb = pg.locator(".photoWrapper").bounding_box()
    png = pg.screenshot(clip={"x": box["x"], "y": 0, "width": 375, "height": 812})
    html.unlink()
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), np.float32), (pb["x"] - box["x"], pb["y"], pb["width"], pb["height"])


def _rgba_from(s0: np.ndarray, s1: np.ndarray) -> Image.Image:
    """Две съёмки (под окном фото чёрный и белый) → RGBA: прозрачно там, где было окно фото."""
    a = np.clip(1 - (s1 - s0).mean(2) / 255.0, 0, 1)
    col = np.where(a[..., None] > 1e-3, s0 / np.maximum(a[..., None], 1e-3), 0)
    out = np.dstack([np.clip(col, 0, 255), a * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def _to_frame(im: Image.Image) -> Image.Image:
    """1125×2436 (скрин @3x) → кадр 1080×1920 от шапки, как build_inspoy_moveon.render_reports (с учётом прозрачности)."""
    ch = round(im.width * H / W)
    im = im.crop((0, BM.CROP_Y, im.width, BM.CROP_Y + ch))
    return im.convert("RGBa").resize((W, H), Image.Resampling.LANCZOS).convert("RGBA")


def build_templates() -> dict:
    """Шаблон страницы на каждый образ (без фото и плашки) + плашка на каждый процент; окно фото в координатах кадра."""
    TPL.mkdir(parents=True, exist_ok=True)
    meta_p = TPL / "_meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    entries = {ekey(e): e for g in POOLS.values() for e in g["dull"] + g["bright"]}
    pcts = list(range(40, 51)) + list(range(85, 96))
    todo = [k for k in entries if not (TPL / f"{k}.png").exists()] + \
           [p for p in pcts if not (TPL / f"badge_{p}.png").exists()]
    if todo:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge", headless=True)
            pg = b.new_page(viewport={"width": 375, "height": 812}, device_scale_factor=3)
            for k in todo:
                if isinstance(k, str):
                    ph, pct, rt, ch, vd = entries[k]
                    h = BM.report_html(Path(ph).resolve(), pct, rt, ch, vd)
                    s0, pb = _shots(pg, h, "#000", True)
                    s1, _ = _shots(pg, h, "#fff", True)
                    _to_frame(_rgba_from(s0, s1)).save(TPL / f"{k}.png")
                else:
                    e = next(iter(entries.values()))
                    h = BM.report_html(Path(e[0]).resolve(), k, e[2], e[3], e[4])
                    s0, pb = _shots(pg, h, "#000", False)
                    s1, _ = _shots(pg, h, "#fff", False)
                    # плашка = то, что внутри окна фото
                    x, y, w, hh = (round(v * 3) for v in pb)
                    m = np.zeros(s0.shape[:2], bool)
                    m[y:y + hh, x:x + w] = True
                    rg = np.asarray(_rgba_from(s0, s1)).copy()
                    rg[~m] = 0
                    # внутри окна фото непрозрачное = сама плашка (в окне больше ничего не рисуется)
                    _to_frame(Image.fromarray(rg, "RGBA")).save(TPL / f"badge_{k}.png")
                meta["photo_css"] = pb
            b.close()
        meta_p.write_text(json.dumps(meta), encoding="utf-8")
    x, y, w, hh = meta["photo_css"]
    k = W / 1125                                           # 1125 → 1080 (и 2000 → 1920)
    meta["box"] = (round(x * 3 * k), round((y * 3 - BM.CROP_Y) * k), round(w * 3 * k), round(hh * 3 * k))
    return meta


# ---------------- «поле света» (как build_skinive10) ----------------
FQ = 4


def wave_field(rng: random.Random) -> np.ndarray:
    w4, h4 = W // FQ, H // FQ
    x = np.linspace(0, 1, w4, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, h4, dtype=np.float32)[:, None]
    ph = (rng.uniform(0, 6.28) + y * rng.uniform(-6, 6)
          + np.sin(y * rng.uniform(2, 5) + rng.uniform(0, 6.28)) * rng.uniform(0.5, 1.5))
    return (0.6 * np.sin(2 * math.pi * rng.uniform(1.2, 2.6) * x + ph)
            + 0.4 * np.sin(2 * math.pi * rng.uniform(2.5, 4.5) * x + ph * 1.7 + rng.uniform(0, 6.28))).astype(np.float32)


def cell_field(rng: random.Random) -> np.ndarray:
    r = np.random.default_rng(rng.randrange(2 ** 32)).random((16, 17), dtype=np.float32)
    im = Image.fromarray(r, "F").resize((W // FQ, H // FQ), Image.Resampling.BICUBIC)
    return np.clip(np.asarray(im, np.float32), 0, 1)


def _up(a: np.ndarray) -> np.ndarray:
    return np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((W, H), Image.Resampling.BILINEAR), np.float32)


def rgba_field(alpha: np.ndarray, colour: int) -> Image.Image:
    img = np.full((H, W, 4), colour, np.uint8)
    img[..., 3] = np.clip(_up(alpha) * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(img, "RGBA")


def rgba_signed(v: np.ndarray) -> Image.Image:
    u = _up(v)
    img = np.zeros((H, W, 4), np.uint8)
    img[..., :3] = np.where(u < 0, 255, 0)[..., None]
    img[..., 3] = np.clip(np.abs(u) * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(img, "RGBA")


# ---------------- текст ----------------
TEXT_LOCK = threading.Lock()
HOOK_CY = (0.69, 0.70, 0.71, 0.72, 0.73)               # хук ниже лица (у A крупные планы — рот около 0.6 H)
SW_CY = (0.60, 0.61, 0.62, 0.63, 0.64)
_TXT: dict = {}


def text_img(kind: str, cy: float) -> tuple[Image.Image, int, int]:
    key = (kind, round(cy, 3))
    with TEXT_LOCK:
        if key not in _TXT:
            dest = WORK / "txt" / f"{kind}_{key[1]:.3f}_{os.getpid()}.png"   # свой файл у процесса (параллельные части)
            dest.parent.mkdir(parents=True, exist_ok=True)
            x, y, _, _ = BM.text_layer(BM.HOOK if kind == "hook" else BM.SWITCH, cy, dest)
            _TXT[key] = (Image.open(dest).convert("RGBA"), x, y)
        return _TXT[key]


# ---------------- план ролика ----------------
# 18.11 замер (30 вариантов на образ): кадрирование фото 1–1.16 + поле — 4 % пар одного образа ближе 40 бит;
# + зум всей страницы 1–1.12 и кадрирование фото 1–1.4 — 0.1 %. Берём зум страницы 1–1.10 (шапка цела), фото 1–1.35.
PH_Z, PG_Z, FACE_Z = (1.0, 1.35), (1.0, 1.07), (1.08, 1.45)   # лицо: замер ёмкости окна 18.11 — шире зум ×2
CLOSE = {("A", 1), ("A", 2)}                         # крупные планы A: зум ≤ 1.10 (хук не на рот)
THR_PRED = 44                                          # прогноз строже приёмки (40): сжатие сдвигает отпечаток на 1–4 бита


def wpick(rng: random.Random, pool: list, k: int) -> list:
    """k образов без повторов; новые (v2) вдвое чаще — старые 23 уже есть во всех 450 сданных роликах."""
    w = [3.0 if "v2" in Path(e[0]).parts else 0.4 for e in pool]   # старые — в 450 сданных: сталкиваются чаще
    keys = sorted(range(len(pool)), key=lambda i: -rng.random() ** (1 / w[i]))
    return [pool[i] for i in keys[:k]]


def roll_page(rng: random.Random, p: dict) -> dict:
    p.update(mirror=rng.random() < 0.5, z=rng.uniform(*PH_Z), ox=rng.uniform(0.15, 0.85), oy=rng.uniform(0.2, 0.8),
             gseed=rng.randrange(10 ** 9), pz=rng.uniform(*PG_Z), px=rng.uniform(0.35, 0.65), py=rng.uniform(0.0, 0.2))
    return p


def roll_face(rng: random.Random, girl: str, f: dict) -> dict:
    clip, a, b = TAKES[girl][f["take"]]
    ln = f["n"] / FPS
    st = rng.uniform(a, max(a, b - ln))
    st = max(0.0, min(st, dur(clip) - ln - 0.15))
    f["kf"] = round(st * FPS)
    st = f["kf"] / FPS
    z = (rng.uniform(1.04, 1.12) if (girl, f["take"]) in CLOSE      # A: лица крупные — хук не на рот
         else rng.uniform(FACE_Z[0], 1.28 if girl == "A" else FACE_Z[1]))
    cw, ch = G._even(W / z), G._even(H / z)
    x = G._even((W - cw) * rng.uniform(0.15, 0.85))
    y = G._even((H - ch) * rng.uniform(0.55 if girl == "A" else 0.4, 1.0))   # лицо выше, хуку место под подбородком
    f.update(clip=str(clip), st=round(st, 3), crop=(x, y, cw, ch))
    return f


def plan(girl: str, seed: int) -> dict:
    rng = random.Random(seed)
    P = POOLS[girl]
    pages = BM.ascending_pcts(wpick(rng, P["dull"], PRE) + wpick(rng, P["bright"], 5), rng)
    pv = [roll_page(rng, dict(key=ekey(e), photo=str(e[0]), pct=e[1])) for e in pages]
    wt = [0.4 if (girl, t) in CLOSE else 1.0 for t in range(len(TAKES[girl]))]
    takes = sorted(range(len(wt)), key=lambda t: -rng.random() ** (1 / wt[t]))[:3]
    span = sum(TAKES[girl][t][2] - TAKES[girl][t][1] for t in takes)
    ns = [round(N_FACE * (TAKES[girl][t][2] - TAKES[girl][t][1]) / span) for t in takes]
    ns[-1] = N_FACE - sum(ns[:-1])
    face = [roll_face(rng, girl, dict(take=t, n=n)) for t, n in zip(takes, ns)]
    return dict(girl=girl, seed=seed, pages=pv, face=face, mirror=rng.random() < 0.5,
                hook_cy=rng.choice(HOOK_CY), sw_cy=rng.choice(SW_CY), fseed=rng.randrange(10 ** 9))


def face_layer(pl: dict, keep: Path) -> None:
    rng = random.Random(pl["fseed"] + 1)
    wv2, cf2 = wave_field(rng), cell_field(rng)
    hook, hx, hy = text_img("hook", pl["hook_cy"])
    face_l = rgba_signed(0.035 * wv2 + 0.035 * (cf2 * 2 - 1))
    face_l.alpha_composite(hook, (hx, hy))
    face_l.save(keep / "face_layer.png", compress_level=0)


def page_field(pl: dict) -> Image.Image:
    if "_field" not in pl:
        rng = random.Random(pl["fseed"])
        pl["_field"] = rgba_field(0.03 * (0.5 + 0.5 * wave_field(rng)) + 0.035 * cell_field(rng), 0)
    return pl["_field"]


_TPL_MEM: dict = {}
_TPL_LOCK = threading.Lock()


def tpl_img(name: str) -> Image.Image:
    with _TPL_LOCK:
        if name not in _TPL_MEM:
            im = Image.open(TPL / f"{name}.png")
            im.load()
            _TPL_MEM[name] = im
        return _TPL_MEM[name]


def page_png(pl: dict, k: int, meta: dict, keep: Path | None) -> None:
    """Страница k: фото (кадрирование, зеркало, цвет) + шаблон + плашка + поле → зум страницы → текст поверх.
    keep=None — только в памяти (pl["_pimg"][k]) для прогноза; файл пишется после приёмки варианта."""
    p = pl["pages"][k]
    bx, by, bw, bh = meta["box"]
    ph = Image.open(p["photo"]).convert("RGB")
    if p["mirror"]:
        ph = ImageOps.mirror(ph)
    s_ = max(bw / ph.width, bh / ph.height) * p["z"]
    x0 = (ph.width * s_ - bw) * p["ox"] / s_
    y0 = (ph.height * s_ - bh) * p["oy"] / s_
    ph = ph.crop((round(x0), round(y0), round(x0 + bw / s_), round(y0 + bh / s_))).resize((bw, bh), Image.Resampling.LANCZOS)
    ph = DT.vivid(ph, random.Random(p["gseed"]))
    im = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    im.paste(ph, (bx, by))
    im.alpha_composite(tpl_img(p["key"]))
    im.alpha_composite(tpl_img(f"badge_{p['pct']}"))
    im.alpha_composite(page_field(pl))
    if p["pz"] > 1.001:
        cw, ch = W / p["pz"], H / p["pz"]
        x, y = (W - cw) * p["px"], (H - ch) * p["py"]
        im = im.crop((round(x), round(y), round(x + cw), round(y + ch))).resize((W, H), Image.Resampling.BICUBIC)
    t, tx, ty = text_img("hook", pl["hook_cy"]) if k < PRE else text_img("switch", pl["sw_cy"])
    im.alpha_composite(t, (tx, ty))
    rgb = im.convert("RGB")
    pl.setdefault("_pimg", {})[k] = rgb
    if keep is not None:
        rgb.save(keep / f"page_{k:02d}.png", compress_level=0)


def mem_hash(im: Image.Image) -> np.ndarray:
    """17×16 клеток яркости (как ffmpeg scale=17:16:flags=area по Y) — для перебора без ffmpeg."""
    import cv2
    a = np.asarray(im, np.float32)
    y = a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
    return cv2.resize(y, (17, 16), interpolation=cv2.INTER_AREA)


def make_layers(pl: dict, meta: dict, keep: Path) -> None:
    face_layer(pl, keep)
    for k in range(len(pl["pages"])):
        page_png(pl, k, meta, None)


# ======================= ВИДЕОКАРТА (18.11: «нагружай видюху») =======================
# Страницы склеиваются и хэшируются на видеокарте (шаблоны, плашки, фото, тексты загружены один раз), лицо —
# из окон шока, распакованных заранее (серые 1/4) → отпечатки и эталон сверки roi_align. ffmpeg — только сборка
# (кадры страниц сырыми rgb24, без PNG) и одна распаковка готового ролика видеодекодером.
import torch.nn.functional as TF  # noqa: E402
from torchvision.ops import roi_align  # noqa: E402

import torch  # noqa: E402
GDEV = "cuda" if torch.cuda.is_available() else "cpu"
GPU_SEM = threading.BoundedSemaphore(3)                # склеек на видеокарте одновременно (память)


def _tt(im: Image.Image) -> torch.Tensor:
    return torch.from_numpy(np.asarray(im, np.uint8).copy()).permute(2, 0, 1).contiguous().to(GDEV)


class Assets:
    def __init__(self, meta: dict):
        self.box = meta["box"]
        self.tpl, self.photo, self.badge, self.text = {}, {}, {}, {}
        for g in POOLS.values():
            for e in g["dull"] + g["bright"]:
                k = ekey(e)
                if k not in self.tpl:
                    self.tpl[k] = _tt(Image.open(TPL / f"{k}.png").convert("RGBA"))
                    self.photo[k] = _tt(Image.open(e[0]).convert("RGB"))
        for pct in list(range(40, 51)) + list(range(85, 96)):
            im = Image.open(TPL / f"badge_{pct}.png").convert("RGBA")
            bb = im.getchannel("A").getbbox()
            self.badge[pct] = (_tt(im.crop(bb)), bb[0], bb[1])
        for kind, cys in (("hook", HOOK_CY), ("switch", SW_CY)):
            for cy in cys:
                im, x, y = text_img(kind, cy)
                self.text[(kind, cy)] = (_tt(im), x, y)
        # окна шока: серые 1/4 (270×480), с запасом 2.4 с от начала окна
        self.face: dict = {}
        for girl, takes in TAKES.items():
            for t, (clip, a, b) in enumerate(takes):
                f0 = max(0, int(min(a, dur(clip) - 2.6) * FPS) - 2)   # кусок у конца клипа начинается раньше окна
                n = min(int(dur(clip) * FPS) - f0, int(max(b, a + 2.4) * FPS) - f0 + 6)
                ss = ["-ss", f"{(f0 - 0.5) / FPS:.4f}"] if f0 else []
                raw = subprocess.run(["ffmpeg", "-v", "error", *ss, "-i", str(clip), "-frames:v", str(n), "-vf",
                                      f"scale={W // 4}:{H // 4}:flags=area,format=gray", "-f", "rawvideo", "-"],
                                     capture_output=True).stdout
                arr = np.frombuffer(raw, np.uint8).reshape(-1, H // 4, W // 4)
                self.face[(girl, t)] = (f0, torch.from_numpy(arr.copy()).to(GDEV))


def _over(base: torch.Tensor, rgba: torch.Tensor, x: int = 0, y: int = 0) -> None:
    h, w = rgba.shape[1:]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    src = rgba[:, y0 - y:y1 - y, x0 - x:x1 - x].float() / 255
    a = src[3:4]
    base[:, y0:y1, x0:x1] = base[:, y0:y1, x0:x1] * (1 - a) + src[:3] * a


def _vivid(x: torch.Tensor, rng: random.Random) -> torch.Tensor:
    """DT.vivid на видеокарте (те же случайности по порядку): сочнее, контрастнее, светлее, тёплый/холодный сдвиг."""
    fc, fk, fb, warm = rng.uniform(1.22, 1.32), rng.uniform(1.06, 1.10), rng.uniform(1.03, 1.07), rng.uniform(-3, 5)
    L = x[0] * 0.299 + x[1] * 0.587 + x[2] * 0.114
    x = (L[None] + (x - L[None]) * fc).clamp(0, 255)
    m = (x[0] * 0.299 + x[1] * 0.587 + x[2] * 0.114).mean()
    x = (m + (x - m) * fk).clamp(0, 255)
    x = (x * fb).clamp(0, 255)
    x[0] += warm
    x[2] -= warm
    return x.clamp(0, 255)


def _up_t(a: np.ndarray) -> torch.Tensor:
    t = torch.from_numpy(np.ascontiguousarray(a, np.float32)).to(GDEV)[None, None]
    return TF.interpolate(t, size=(H, W), mode="bilinear", align_corners=False)[0, 0]


def fields_t(pl: dict) -> None:
    """Поле страниц (затемнение) и слой лица (поле со знаком + хук): на видеокарте, в плане (_fd, _la, _lc)."""
    rng = random.Random(pl["fseed"])
    pl["_fd"] = _up_t(0.03 * (0.5 + 0.5 * wave_field(rng)) + 0.035 * cell_field(rng))
    rng = random.Random(pl["fseed"] + 1)
    wv2, cf2 = wave_field(rng), cell_field(rng)
    v = _up_t(0.04 * wv2 + 0.06 * (cf2 * 2 - 1))
    a = v.abs().clamp(0, 1)
    col = (v < 0).float()                                  # белый — осветление, чёрный — затемнение
    t, tx, ty = pl["_A"].text[("hook", pl["hook_cy"])]
    h, w = t.shape[1:]
    ta = t[3].float() / 255
    tc = t[:3].float().mean(0) / 255
    sl = (slice(ty, ty + h), slice(tx, tx + w))
    a_old = a[sl].clone()
    a[sl] = ta + a_old * (1 - ta)
    col[sl] = torch.where(a[sl] > 0, (tc * ta + col[sl] * a_old * (1 - ta)) / a[sl].clamp(min=1e-6), col[sl])
    pl["_la"], pl["_lc"] = a, col                          # для прогноза лица (серый)
    rgba = torch.zeros((H, W, 4), dtype=torch.uint8, device=GDEV)
    rgba[..., :3] = (col * 255).round().to(torch.uint8)[..., None]
    rgba[..., 3] = (a * 255).round().to(torch.uint8)
    rgb_t = t[:3].permute(1, 2, 0).float()
    m = ta[..., None] > 0
    blend = torch.where(m, rgb_t, rgba[sl][..., :3].float())    # цвет текста там, где текст есть
    rgba[sl[0], sl[1], :3] = blend.round().to(torch.uint8)
    pl["_layer_rgba"] = rgba


def page_t(pl: dict, k: int) -> torch.Tensor:
    A = pl["_A"]
    p = pl["pages"][k]
    bx, by, bw, bh = A.box
    ph = A.photo[p["key"]].float()
    if p["mirror"]:
        ph = ph.flip(-1)
    h, w = ph.shape[1:]
    s_ = max(bw / w, bh / h) * p["z"]
    x0 = (w * s_ - bw) * p["ox"] / s_
    y0 = (h * s_ - bh) * p["oy"] / s_
    crop = ph[:, round(y0):round(y0 + bh / s_), round(x0):round(x0 + bw / s_)]
    crop = TF.interpolate(crop[None], size=(bh, bw), mode="bicubic", align_corners=False)[0].clamp(0, 255)
    crop = _vivid(crop, random.Random(p["gseed"]))
    can = torch.ones((3, H, W), device=GDEV)
    can[:, by:by + bh, bx:bx + bw] = crop / 255
    _over(can, A.tpl[p["key"]])
    b, bxx, byy = A.badge[p["pct"]]
    _over(can, b, bxx, byy)
    can *= (1 - pl["_fd"])[None]
    if p["pz"] > 1.001:
        cw, ch = W / p["pz"], H / p["pz"]
        x, y = round((W - cw) * p["px"]), round((H - ch) * p["py"])
        can = TF.interpolate(can[None, :, y:y + round(ch), x:x + round(cw)], size=(H, W), mode="bicubic",
                             align_corners=False)[0].clamp(0, 1)
    t, tx, ty = A.text[("hook", pl["hook_cy"])] if k < PRE else A.text[("switch", pl["sw_cy"])]
    _over(can, t, tx, ty)
    return can


def _gray(can: torch.Tensor) -> torch.Tensor:
    return (can[0] * 0.299 + can[1] * 0.587 + can[2] * 0.114) * 255


def pages_pred(pl: dict, ks) -> None:
    """Страницы ks → (_pg: картинки на видеокарте, _pc: клетки 16×17, _pr: эталон 1/8)."""
    for k in ks:
        can = page_t(pl, k)
        g = _gray(can)[None, None]
        pl["_pg"][k] = can
        pl["_pc"][k] = TF.adaptive_avg_pool2d(g, (16, 17))[0, 0]
        pl["_pr"][k] = TF.adaptive_avg_pool2d(g, (H // Q8, W // Q8))[0, 0]


def face_pred(pl: dict) -> None:
    """Лицо: клетки 16×17 и эталон 1/8 из заранее распакованных окон (обрезка/масштаб — roi_align, зеркало, слой)."""
    A = pl["_A"]
    frs, boxes = [], []
    for f in pl["face"]:
        f0, arr = A.face[(pl["girl"], f["take"])]
        i0 = f["kf"] - f0
        sel = arr[i0:i0 + f["n"]]
        if len(sel) < f["n"]:                              # конец клипа — добиваем последним кадром
            sel = torch.cat([sel, sel[-1:].expand(f["n"] - len(sel), -1, -1)])
        x, y, cw, ch = f["crop"]
        frs.append(sel)
        boxes += [(x / 4, y / 4, (x + cw) / 4, (y + ch) / 4)] * f["n"]
    img = torch.cat(frs).float()[:, None]
    bx = torch.tensor([[i, *b] for i, b in enumerate(boxes)], dtype=torch.float32, device=GDEV)
    cells = roi_align(img, bx, (16, 17), spatial_scale=1.0, sampling_ratio=-1, aligned=True)[:, 0]
    ref = roi_align(img, bx, (H // Q8, W // Q8), spatial_scale=1.0, sampling_ratio=2, aligned=True)[:, 0]
    if pl["mirror"]:
        cells, ref = cells.flip(-1), ref.flip(-1)
    a, c = pl["_la"][None, None], (pl["_la"] * pl["_lc"] * 255)[None, None]
    a16, c16 = TF.adaptive_avg_pool2d(1 - a, (16, 17))[0, 0], TF.adaptive_avg_pool2d(c, (16, 17))[0, 0]
    a8, c8 = TF.adaptive_avg_pool2d(1 - a, (H // Q8, W // Q8))[0, 0], TF.adaptive_avg_pool2d(c, (H // Q8, W // Q8))[0, 0]
    pl["_fc"] = cells * a16 + c16
    pl["_fr"] = ref * a8 + c8


RP = torch.from_numpy(np.repeat(np.arange(11), N_PAGES))


def all_cells(pl: dict) -> torch.Tensor:
    pc = torch.stack([pl["_pc"][k] for k in range(11)])
    return torch.cat([pl["_fc"], pc[RP.to(pc.device)]])


def bits_t(cells: torch.Tensor) -> torch.Tensor:
    """Клетки (N,16,17) → ±1 (2N,256) half: прямые и зеркальные (как hash_of)."""
    h = (cells[:, :, 1:] > cells[:, :, :-1]).reshape(len(cells), -1)
    fl = cells.flip(2)
    m = (fl[:, :, 1:] > fl[:, :, :-1]).reshape(len(cells), -1)
    return (torch.cat([h, m]).to(BDT) * 2 - 1)


def near_mask_t(hb: torch.Tensor, bank: torch.Tensor, thr: int) -> tuple[np.ndarray, int]:
    n = len(hb) // 2                                       # прямые + зеркальные кандидата
    hit = torch.zeros(n, dtype=torch.bool, device=GDEV)
    rev = 0
    if len(bank):
        with torch.no_grad():
            for i in range(0, len(bank), 131072):
                m = (256 - hb @ bank[i:i + 131072].T) / 2 <= thr
                hit |= m[:n].any(1) | m[n:].any(1)
                rev += int(m.any(0).sum())
    return hit.cpu().numpy(), rev


def write_inputs(pl: dict, keep: Path) -> None:
    """Принятый вариант → сырые кадры для ffmpeg: страницы rgb24, слой лица rgba (без PNG)."""
    for k in range(11):
        (pl["_pg"][k].clamp(0, 1) * 255).round().to(torch.uint8).permute(1, 2, 0).contiguous().cpu().numpy() \
            .tofile(keep / f"page_{k:02d}.rgb")
    pl["_layer_rgba"].cpu().numpy().tofile(keep / "face_layer.rgba")


def _raw(cmd: list[str]) -> bytes:
    r = subprocess.run(cmd, capture_output=True)
    return r.stdout


def predict(pl: dict, keep: Path, face: bool = True, pages: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Ожидаемые кадры ролика (серые 1/8 — для сверки, 17×16 — отпечатки) тем же путём через ffmpeg, но в памяти:
    лицо — кусками proxy (тот же -ss, обрезка, масштаб, зеркало) + слой; страницы — картинки."""
    if face or "_face_g" not in pl:
        pl["_face_g"], pl["_face_h"] = _predict_face(pl, keep)
    if pages or "_pages_g" not in pl:
        pl["_pages_g"], pl["_pages_h"] = _predict_pages(keep)
    rp = np.repeat(np.arange(11), N_PAGES)
    return (np.concatenate([pl["_face_g"], pl["_pages_g"][rp]]),
            np.concatenate([pl["_face_h"], pl["_pages_h"][rp]]))


def _predict_face(pl: dict, keep: Path):
    inputs, fc = [], []
    for i, f in enumerate(pl["face"]):
        x, y, cw, ch = f["crop"]
        inputs += ["-ss", f"{f['st']:.3f}", "-i", f["clip"]]
        fc.append(f"[{i}:v]crop={cw}:{ch}:{x}:{y},scale={W}:{H}:flags=bilinear,fps={FPS},trim=end_frame={f['n']},"
                  f"setpts=PTS-STARTPTS,format=yuv420p" + (",hflip" if pl["mirror"] else "") + f",setsar=1[f{i}]")
    n = len(pl["face"])
    inputs += ["-i", str(keep / "face_layer.png")]
    fc.append(f"[{n}:v]format=yuva420p,loop=loop={N_FACE - 1}:size=1:start=0,settb=1/{FPS},setpts=N[lay]")
    fc.append("".join(f"[f{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[fc]")
    fc.append(f"[fc][lay]overlay=0:0:format=yuv420:shortest=1,trim=end_frame={N_FACE},format=yuv420p,split=2[a][b]")
    fc.append(f"[a]scale={W // Q8}:{H // Q8}:flags=area,format=gray[g];[b]scale=17:16:flags=area,format=gray[h]")
    g, h = keep / "pf_g.raw", keep / "pf_h.raw"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-threads", "2", *inputs, "-filter_complex", ";".join(fc),
                    "-map", "[g]", "-f", "rawvideo", str(g), "-map", "[h]", "-f", "rawvideo", str(h)],
                   capture_output=True, check=True)
    Gf = np.fromfile(g, np.uint8).reshape(-1, H // Q8, W // Q8).astype(np.float32)
    Hf = np.fromfile(h, np.uint8).reshape(-1, 16, 17).astype(np.int16)
    if len(Gf) != N_FACE:
        raise RuntimeError(f"прогноз: лицо {len(Gf)}/{N_FACE}")
    return Gf, Hf


def _predict_pages(keep: Path):
    gp, hp = keep / "pp_g.raw", keep / "pp_h.raw"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(keep / "page_%02d.png"), "-filter_complex",
                    f"[0:v]format=yuv420p,split=2[a][b];[a]scale={W // Q8}:{H // Q8}:flags=area,format=gray[g];"
                    f"[b]scale=17:16:flags=area,format=gray[h]",
                    "-map", "[g]", "-f", "rawvideo", str(gp), "-map", "[h]", "-f", "rawvideo", str(hp)],
                   capture_output=True, check=True)
    Gp = np.fromfile(gp, np.uint8).reshape(-1, H // Q8, W // Q8).astype(np.float32)
    Hp = np.fromfile(hp, np.uint8).reshape(-1, 16, 17).astype(np.int16)
    if len(Gp) != 11:
        raise RuntimeError(f"прогноз: страниц {len(Gp)}")
    return Gp, Hp


def hash_of(H_: np.ndarray) -> np.ndarray:
    H_ = np.asarray(H_, np.float32)
    h = (H_[:, :, 1:] > H_[:, :, :-1]).reshape(len(H_), -1)
    m = (H_[:, :, ::-1][:, :, 1:] > H_[:, :, ::-1][:, :, :-1]).reshape(len(H_), -1)
    return np.concatenate([h, m]).astype(np.float32) * 2 - 1


# ---------------- банк (видеокарта, half) ----------------
import torch  # noqa: E402

BDEV = "cuda" if torch.cuda.is_available() else "cpu"
BDT = torch.half if BDEV == "cuda" else torch.float32
BANK_LOCK = threading.Lock()


class Bank:
    def __init__(self):
        self.t = torch.zeros((0, 256), dtype=BDT, device=BDEV)

    def add(self, h: np.ndarray) -> None:
        self.t = torch.cat([self.t, torch.from_numpy(np.asarray(h, np.float32)).to(BDEV).to(BDT)])


def near(h: np.ndarray, bank: torch.Tensor, thr: int = THR) -> int:
    """Кадры кандидата (прямые) ближе thr к банку (прямые+зеркальные) и кадры банка рядом с кандидатом — максимум."""
    if not len(bank):
        return 0
    q = torch.from_numpy(np.asarray(h, np.float32)).to(BDEV).to(BDT)     # прямые + зеркальные
    n = len(q) // 2
    hit = torch.zeros(n, dtype=torch.bool, device=BDEV)
    rev = 0
    with torch.no_grad():
        for i in range(0, len(bank), 131072):
            m = (256 - q @ bank[i:i + 131072].T) / 2 <= thr
            hit |= m[:n].any(1) | m[n:].any(1)
            rev += int(m.any(0).sum())
    return max(int(hit.sum()), rev)


def near_mask(h: np.ndarray, bank: torch.Tensor, thr: int = THR) -> tuple[np.ndarray, int]:
    """Какие кадры кандидата ближе thr к банку (маска) и сколько кадров банка рядом с кандидатом."""
    q = torch.from_numpy(np.asarray(h[: len(h) // 2], np.float32)).to(BDEV).to(BDT)
    hit = torch.zeros(len(q), dtype=torch.bool, device=BDEV)
    rev = 0
    if len(bank):
        with torch.no_grad():
            for i in range(0, len(bank), 131072):
                m = (256 - q @ bank[i:i + 131072].T) / 2 <= thr
                hit |= m.any(1)
                rev += int(m.any(0).sum())
    return hit.cpu().numpy(), rev


def load_old(bank: Bank) -> int:
    d = np.load(OLD_BANK, allow_pickle=True)["d"].item()
    hm = np.concatenate([v[0] for v in d.values()]).astype(np.float32)      # (кадры, 2, 256) 0/1
    bank.add(np.concatenate([hm[:, 0], hm[:, 1]]) * 2 - 1)
    return len(d)


# ---------------- сборка ----------------
AUDIO = WORK / "audio_9s.m4a"


def make_audio() -> None:
    if AUDIO.exists():
        return
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(BM.REF), "-vn", "-af",
                    f"atrim=start={A_OFF:.4f}:duration={TOTAL_S},asetpts=PTS-STARTPTS,afade=t=out:st={TOTAL_S - 0.3}:d=0.3,"
                    f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100", "-c:a", "aac", "-b:a", "160k", str(AUDIO)], check=True)


def render(pl: dict, keep: Path, dest: Path) -> None:
    inputs, fc = [], []
    for i, f in enumerate(pl["face"]):
        inputs += G.gpu_input(Path(f["clip"]), crop=f["crop"], resize=(W, H), ss=max(0.0, (f["kf"] - 0.5) / FPS))
        fc.append(f"[{i}:v]fps={FPS},trim=end_frame={f['n']},setpts=PTS-STARTPTS,format=yuv420p"
                  + (",hflip" if pl["mirror"] else "") + f",setsar=1[f{i}]")
    n = len(pl["face"])
    RAW = ["-f", "rawvideo", "-video_size", f"{W}x{H}", "-framerate", str(FPS)]
    inputs += [*RAW, "-pixel_format", "rgba", "-i", str(keep / "face_layer.rgba")]
    fc.append(f"[{n}:v]format=yuva420p,loop=loop={N_FACE - 1}:size=1:start=0,settb=1/{FPS},setpts=N[lay]")
    fc.append("".join(f"[f{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[fc]")
    fc.append(f"[fc][lay]overlay=0:0:format=yuv420:shortest=1,trim=end_frame={N_FACE},setpts=PTS-STARTPTS,format=yuv420p[face]")
    for k in range(11):
        inputs += [*RAW, "-pixel_format", "rgb24", "-i", str(keep / f"page_{k:02d}.rgb")]
        fc.append(f"[{n + 1 + k}:v]format=yuv420p,loop=loop={N_PAGES[k] - 1}:size=1:start=0,settb=1/{FPS},setpts=N,"
                  f"setsar=1[p{k}]")
    fc.append("[face]" + "".join(f"[p{k}]" for k in range(11)) + "concat=n=12:v=1:a=0,format=yuv420p[v]")
    inputs += ["-i", str(AUDIO)]
    (keep / "graph.txt").write_text(";".join(fc), encoding="utf-8")
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex_script", str(keep / "graph.txt"),
           "-map", "[v]", "-map", f"{n + 12}:a", "-frames:v", str(NF), "-r", str(FPS), *G.NVENC, "-c:a", "copy",
           "-t", f"{TOTAL_S:.3f}", *G.CLEAN, str(dest)]
    with gpu_slot():
        for attempt in range(2):
            try:
                subprocess.run(cmd, check=True, timeout=300, capture_output=True)
                return
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                if attempt == 1:
                    raise RuntimeError(f"ffmpeg: {getattr(e, 'stderr', b'')[-500:]!r}")


def decode_checks(path: Path, keep: Path) -> tuple:
    """ОДНА распаковка готового ролика: серые 1/8 (сверка), RGB 54×96 (пустые/повторы), 17×16 (отпечатки)."""
    g, r, h = keep / "g.raw", keep / "r.raw", keep / "h.raw"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-hwaccel", "cuda", "-i", str(path), "-filter_complex",
                    f"[0:v]split=3[a][b][c];[a]scale={W // Q8}:{H // Q8}:flags=area,format=gray[g];"
                    f"[b]scale=54:96,format=rgb24[r];[c]scale=17:16:flags=area,format=gray[h]",
                    "-map", "[g]", "-f", "rawvideo", str(g), "-map", "[r]", "-f", "rawvideo", str(r),
                    "-map", "[h]", "-f", "rawvideo", str(h)], capture_output=True)
    return (np.fromfile(g, np.uint8).reshape(-1, H // Q8, W // Q8).astype(np.float32),
            np.fromfile(r, np.uint8).reshape(-1, 96, 54, 3),
            np.fromfile(h, np.uint8).reshape(-1, 16, 17).astype(np.int16))


def frame_check(out: np.ndarray, ref: np.ndarray, pl: dict, margin: float = 0.8, junk: float = 14.0) -> list:
    """КАЖДЫЙ кадр против плана: лицо — ближайший из ±3 кадров ожидаемого ряда должен быть «свой»; страница —
    ближе всего своя страница (не соседняя) и не мусор."""
    if len(out) != NF:
        return [("кадров", len(out), NF)]
    flags = []
    for j in range(N_FACE):
        d = {dk: float(np.abs(out[j] - ref[j + dk]).mean()) for dk in range(-3, 4) if 0 <= j + dk < N_FACE}
        best = min(d, key=d.get)
        if d[best] > junk:
            flags.append((j, "лицо", "мусор", round(d[best], 1)))
        elif best != 0 and d[0] - d[best] > margin:
            flags.append((j, "лицо", best, round(d[0] - d[best], 2)))
    Gp = pl["_pages_g"]
    j = N_FACE
    for k, n in enumerate(N_PAGES):
        for t in range(n):
            d = {kk: float(np.abs(out[j] - Gp[kk]).mean()) for kk in (k - 1, k, k + 1) if 0 <= kk < 11}
            best = min(d, key=d.get)
            if best != k or d[k] > junk:
                flags.append((j, f"стр{k}", best, round(d[k], 1)))
            j += 1
    return flags


class Ctx:
    def __init__(self, meta: dict, bank: Bank, out_dirs: dict, test: bool):
        self.meta, self.bank, self.out, self.test = meta, bank, out_dirs, test
        self.loaded: set[str] = set()                     # принятые (свои и соседних процессов), уже в банке
        self.done = 0
        self.stat = dict(pred_rej=0, real_rej=0, bad=0, fr=0)
        self.lock = threading.Lock()

    def sync(self) -> None:
        """Подтянуть в банк ролики, принятые соседними процессами (acc/*.npy) — уникальность между процессами."""
        if not ACC.exists():
            return
        for f in ACC.glob("*.npy"):
            if f.name not in self.loaded:
                try:
                    self.bank.add(np.unpackbits(np.load(f), axis=1)[:, :256].astype(np.float32) * 2 - 1)
                    self.loaded.add(f.name)
                except (OSError, ValueError):
                    pass


def build_one(ctx: Ctx, tag: str, i: int, girl: str) -> str:
    name = f"inspoy_moveon_{tag}_{i:03d}_1.mp4"
    dest = ctx.out[tag] / name
    keep = WORK / "jobs" / f"{tag}_{i:03d}"
    for att in range(int(os.environ.get("MV_ATT", "16"))):
        if keep.exists():
            shutil.rmtree(keep, ignore_errors=True)
        keep.mkdir(parents=True, exist_ok=True)
        seed = ({"yt": 1, "tt": 2, "test": 3}[tag] * 100000 + i) * 100 + att + int(os.environ.get("MV_SEED", "0")) * 7919
        pl = plan(girl, seed)
        pl["_A"] = ctx.A
        rr = random.Random(seed * 7 + 1)
        ok = False
        with GPU_SEM, torch.no_grad():
            fields_t(pl)
            pl["_pg"], pl["_pc"], pl["_pr"] = {}, {}, {}
            pages_pred(pl, range(11))
            face_pred(pl)
            fails, ffails = [0] * 11, [0] * 3
            for _rnd in range(80):                         # прогноз (миллисекунды на видеокарте): перебор совпавшего
                with BANK_LOCK:
                    ctx.sync()
                    bank = ctx.bank.t
                hit, rev = near_mask_t(bits_t(all_cells(pl)), bank, THR_PRED)
                if max(int(hit.sum()), rev) <= ACC_MAX:
                    ok = True
                    break
                bad_pg = [k for k in range(11) if hit[FB[k]:FB[k + 1]].any()]
                f0, bad_fc = 0, []
                for j, f in enumerate(pl["face"]):
                    if hit[f0:f0 + f["n"]].any():
                        bad_fc.append(j)
                    f0 += f["n"]
                if not bad_pg and not bad_fc:
                    bad_fc = list(range(len(pl["face"])))
                for k in bad_pg:
                    fails[k] += 1
                    if fails[k] >= 3:                      # образ не проходит — другой образ того же типа
                        P = POOLS[girl]["dull" if k < PRE else "bright"]
                        used = {pg["key"] for pg in pl["pages"]}
                        free = [e for e in P if ekey(e) not in used]
                        if free:
                            e = wpick(rr, free, 1)[0]
                            pl["pages"][k].update(key=ekey(e), photo=str(e[0]))
                        fails[k] = 0
                    roll_page(rr, pl["pages"][k])
                for j in bad_fc:
                    ffails[j] += 1
                    if ffails[j] >= 4:
                        used = {f["take"] for f in pl["face"]}
                        free = [t for t in range(len(TAKES[girl])) if t not in used]
                        if free:
                            pl["face"][j]["take"] = rr.choice(free)
                        ffails[j] = 0
                    roll_face(rr, girl, pl["face"][j])
                with ctx.lock:
                    ctx.stat["pred_rej"] += 1
                    ctx.stat["pg"] = ctx.stat.get("pg", 0) + len(bad_pg)
                    ctx.stat["face"] = ctx.stat.get("face", 0) + len(bad_fc)
                if bad_pg:
                    pages_pred(pl, bad_pg)
                if bad_fc:
                    face_pred(pl)
            if ok:
                write_inputs(pl, keep)
                refg = torch.cat([pl["_fr"], torch.stack([pl["_pr"][k] for k in range(11)])[RP.to(GDEV)]]).cpu().numpy()
                pl["_pages_g"] = torch.stack([pl["_pr"][k] for k in range(11)]).cpu().numpy()
        for k_ in ("_pg", "_pc", "_pr", "_fd", "_la", "_lc", "_layer_rgba", "_fc", "_fr"):
            pl.pop(k_, None)
        if GDEV == "cuda":                                 # кэш перебора не держим: при > лимита gpu_slot ждёт вечно
            torch.cuda.empty_cache()                       # (18.11: 7,5 ГБ у одного добора — сборка встала)
        if not ok:
            print(f"  {name} попытка {att}: прогноз не сошёлся за 80 кругов", flush=True)
            continue
        tmp = keep / "out.mp4"
        render(pl, keep, tmp)
        G_, R_, H_ = decode_checks(tmp, keep)
        bad = G.bad_frames_arr(R_)
        fr = frame_check(G_, refg, pl)
        if bad or fr:
            with ctx.lock:
                ctx.stat["bad" if bad else "fr"] += 1
            print(f"  {name} попытка {att}: bad {bad[:4]} кадры {fr[:4]}", flush=True)
            continue
        hr = hash_of(H_)
        with BANK_LOCK:
            ctx.sync()
            nn = near(hr, ctx.bank.t)
            if nn > ACC_MAX and not ctx.test:
                with ctx.lock:
                    ctx.stat["real_rej"] += 1
                print(f"  {name} попытка {att}: готовый похож ({nn} кадров)", flush=True)
                continue
            ctx.bank.add(hr)
            ACC.mkdir(parents=True, exist_ok=True)
            np.save(ACC / f"{name}.npy", np.packbits(hr > 0, axis=1))
            ctx.loaded.add(f"{name}.npy")
        shutil.move(str(tmp), str(dest))
        (keep / "plan.json").write_text(json.dumps({k: v for k, v in pl.items() if not k.startswith("_")},
                                                   ensure_ascii=False), encoding="utf-8")
        for f in keep.iterdir():
            if f.name != "plan.json":
                f.unlink()
        with ctx.lock:
            ctx.done += 1
        return f"{name} (попытка {att}, похожих кадров {nn})"
    if girl == "A" and os.environ.get("MV_FALLBACK_B"):   # окна лица A исчерпаны — этот ролик на девушке B
        return build_one(ctx, tag, i, "B")
    raise RuntimeError(f"{name}: попытки кончились без приёмки")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--yt", type=int, default=0)
    ap.add_argument("--tt", type=int, default=0)
    ap.add_argument("--test", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--part", default="0/1", help="i/n: этот процесс собирает каждый n-й ролик со сдвигом i")
    a = ap.parse_args()
    t0 = time.time()
    prog("подготовка: шаблоны страниц", 0, None)
    meta = build_templates()
    make_audio()
    for cy in HOOK_CY:                                    # заранее: текст вне безопасной зоны — сразу ошибка, а не в потоке
        text_img("hook", cy)
    for cy in SW_CY:
        text_img("switch", cy)
    print(f"шаблоны готовы, окно фото {meta['box']}, лицо {N_FACE} кадров, страницы {N_PAGES} ({time.time() - t0:.0f} с)",
          flush=True)
    bank = Bank()
    jobs: list[tuple[str, int, str]] = []
    if a.test:
        out = {"test": ROOT / "output" / "inspoy_moveon_v2_test"}
        jobs = [("test", k, "AB"[(k - 1) % 2]) for k in range(1, a.test + 1)]
        print(f"тест с банком прошлых: {load_old(bank)} роликов", flush=True)   # как в партии: с отбором
    else:
        prog("подготовка: банк прошлых 450", 0, None)
        print(f"прошлых роликов: {load_old(bank)}, кадров в банке {len(bank.t)}", flush=True)
        out = {"yt": ROOT / "output" / f"inspoy_moveon_1_YT_{a.yt}", "tt": ROOT / "output" / f"inspoy_moveon_1_TT_{a.tt}"}
        for tag, n in (("yt", a.yt), ("tt", a.tt)):
            jobs += [(tag, k, "AB"[(k - 1) % 2]) for k in range(1, n + 1)]
        # уже готовые (перезапуск) — пропустить; их отпечатки (и соседних процессов) банк берёт из acc/ (ctx.sync)
        pi, pn = (int(v) for v in a.part.split("/"))
        jobs = jobs[pi::pn]
        left = [(tag, k, g) for tag, k, g in jobs
                if not ((out[tag] / f"inspoy_moveon_{tag}_{k:03d}_1.mp4").exists()
                        and (ACC / f"inspoy_moveon_{tag}_{k:03d}_1.mp4.npy").exists())]
        print(f"готово раньше: {len(jobs) - len(left)}, собрать: {len(left)}", flush=True)
        jobs = left
    for d in out.values():
        d.mkdir(parents=True, exist_ok=True)
    ctx = Ctx(meta, bank, out, False)
    t1 = time.time()
    ctx.A = Assets(meta)
    print(f"видеокарта: шаблоны, фото, тексты, окна лица загружены ({time.time() - t1:.0f} с)", flush=True)
    if not a.test:
        ctx.sync()
        print(f"в банке с принятыми: {len(bank.t)} кадров", flush=True)
    total = len(jobs)
    errors = []
    last_ec = time.time()
    with ThreadPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(build_one, ctx, *j): j for j in jobs}
        for f in as_completed(futs):
            j = futs[f]
            try:
                msg = f.result()
                el = time.time() - t0
                print(f"  [{ctx.done}/{total}] {msg}  {el / 60:.1f} мин, {ctx.done / max(el / 60, 0.01):.1f}/мин  "
                      f"{ctx.stat}", flush=True)
            except Exception as e:  # noqa: BLE001
                errors.append((j, repr(e)))
                print(f"  ОШИБКА {j}: {e}\n{traceback.format_exc()[-800:]}", flush=True)
            prog(f"сборка + проверка {ctx.stat}", ctx.done, total)
            if time.time() - last_ec > 10 and BDEV == "cuda":
                torch.cuda.empty_cache()
                last_ec = time.time()
    prog("готово", ctx.done, total)
    print(f"ГОТОВО: {ctx.done} из {total}, ошибок {len(errors)}, {time.time() - t0:.0f} с, {ctx.stat}", flush=True)
    for e in errors:
        print("  ", e)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
