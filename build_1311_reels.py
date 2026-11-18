#!/usr/bin/env python3
"""
1311 — OneState «смена образов под бит»: 250 TikTok + 250 YouTube, 9:16, 8.0 с. Исходники — 5 почти готовых роликов
клиента (Drive 1PoVesasSSqoNqGq1bdxtvEW8RReynAbw → downloads/1311/src, 1080×1920 30 к/с): 3 образа персонажа
(смена — склейка/наплыв или зум-блюр) → концовка с промокодом STATE9CNL / $10,000 и CTA снизу; подпись сверху
белыми капсом, лого OneState под игровой полосой.

Структуру не меняем: образ 1 → образ 2 → образ 3 → концовка с кодом, только укорачиваем до 8 с так, чтобы каждая
смена образа (и переход в концовку) попадала на бит нового трека (TikTok «original sound» callmekatushas,
downloads/1311/music; сетка битов 0.3727 с от 0.1435 с, подъём громкости ~4.98 с = бит 13). Переход в концовку
ставим на бит 13 трека («дроп»), трек начинается с бита j (0–3), образы — по 3–6 битов.

Подпись сверху — та же фраза дословно, но нашей плашкой: исходный текст стираем (removelogo по маске статичных
белых пикселей с раздувом на тень + доразмытие полосы над игрой), сверху белые плашки TikTok с чёрным текстом; только
на образах (в концовке сверху баннер с кодом).
Код и лого уже вшиты в исходники (код — в концовке, её всегда ≥ 3 с). Нижний текст концовки («download …») стираем так
же (removelogo + доразмытие полосы под игрой), вместо него — карточка TikTok «Reply to <ник>'s comment» с одним из 3
комментариев ТЗ (поровну), ник и аватарка (без лица) — из пула 1309; карточка «выскакивает» на бите перехода в концовку.

Уникализация каждого ролика (UNIQ, своё зерно на ролик): зум 100–106 % со сдвигом кадра, яркость/контраст/
насыщенность/гамма/оттенок чуть в стороны, лёгкое зерно, скорость исходника 0.98–1.02 (длины отрезков в кадрах ролика
те же — смены остаются на битах; отрезки, примыкающие к смене, растягиваются/сжимаются от неё). Чистка подписей —
до зума, наши плашка и карточка — после (стоят ровно в безопасной зоне). Чистка — на полосе в 1/LOW разрешения
(полоса и так размыта, а removelogo в полном размере ~30 с на ролик); кодирование — h264_nvenc (RTX 3070).

Склейки (P1 — по умолчанию): образ 1 = [c1 − a, c1) → образ 2 = [c1, c1 + b) непрерывно (переход исходника целиком),
на бите — жёсткая склейка в образ 3 = [c3 − c, c3) → концовка [c3, …) непрерывно. P2: образ 1 = [δ, δ + a) →
склейка на бите в образ 2 = [c2 − b, c2) → образ 3 = [c2, c2 + c) непрерывно → склейка на бите в концовку [c3, …).

  python build_1311_reels.py --test
  python build_1311_reels.py --count 250 --jobs 4
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import check_box  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
ID = "1311"
W, H, FPS = 1080, 1920, 30
TOTAL = 240                                    # 8.0 с
D = ROOT / "downloads" / "1311"
MUSIC = D / "music" / "callmekatushas_7667964296802487072.mp3"
B0, P = 0.1435, 0.37265                        # сетка битов трека (МНК по пикам спектрального потока)
DROP = 13                                      # бит подъёма (~4.98 с)
FOLDERS = ["TT", "YT"]
NL = chr(10)
# смены образов (первый кадр нового образа), длина разгона перехода до смены и «проявления» после
SOURCES = {
    "m1": {"c": [77, 145, 214], "ramp": 3, "settle": 2, "text": "POV: PAYDAY IN ONESTATE"},
    "m2": {"c": [75, 167, 259], "ramp": 11, "settle": 4, "text": NL.join(["FROM BROKE", "TO DRIP IN ONE BEAT"])},
    "m3": {"c": [81, 157, 230], "ramp": 3, "settle": 2, "text": NL.join(["RATE MY ONESTATE", "GLOW-UP 1-10"])},
    "w1": {"c": [103, 235, 369], "ramp": 3, "settle": 2, "text": NL.join(["STARTED WITH NOTHING,", "ENDED WITH THIS"])},
    "w2": {"c": [134, 206, 279], "ramp": 11, "settle": 4,
           "text": NL.join(["MY CHARACTER’S CLOSET", "AFTER ONE WEEK IN ONESTATE"])},
}
CAP = (40, 230, 1040, 450)                     # область исходной подписи (x0, y0, x1, y1)
CTA = (40, 1488, 1040, 1760)                   # область нижнего текста концовки «download …» — стираем
BAND2 = (1488, H)                              # полоса под игрой в концовке, доразмываем после removelogo
# комментарии ТЗ дословно (переносы по смыслу) — карточка «Reply to …'s comment» TikTok в концовке вместо CTA
COMMENTS = [
    NL.join(["i can't believe this is", "a PHONE game 😭"]),
    NL.join(["i opened it for 5 minutes.", "it's been 3 hours 😭"]),
    NL.join(["my friend sent me this", "and now i'm stuck here too"]),
]
CARD_PX = 40
CARD_BOTTOM = 1532                             # низ карточки (с хвостиком) — внутри безопасной зоны 9:16 (≤ 1540)
POP = (0.8, 0.94, 1.03)                        # масштаб карточки в первые 3 кадра концовки
GAME_TOP = 428                                 # игровая полоса начинается с y ≈ 431–436 — маску и размытие не пускаем ниже
BAND = (200, GAME_TOP)                         # полоса над игрой, которую после removelogo доразмываем (убирает тень текста)
PX_MAX, PX_MIN = 58, 40
SAFE_X0, SAFE_X1 = 140, 940


def src(name: str) -> Path:
    return D / "src" / f"Onestate_Format5_{name}_v2.mp4"


def nframes(name: str) -> int:
    out = subprocess.run([FF.replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error", "-count_packets", "-select_streams",
                          "v:0", "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(src(name))],
                         capture_output=True, text=True).stdout
    return int(out.strip())


def frame(name: str, n: int) -> np.ndarray:
    raw = subprocess.run([FF, "-v", "error", "-i", str(src(name)), "-vf", f"select=eq(n\\,{n})", "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3)


def cap_mask(name: str) -> tuple[Path, tuple[int, int, int, int]]:
    """Маска исходной подписи: пиксели, светлые во всех трёх образах (фон под текстом разный), + раздув ~16 px
    на тёмную тень букв; ниже GAME_TOP не заходит."""
    out = D / "masks" / f"{name}.png"
    meta = out.with_suffix(".json")
    if out.exists() and meta.exists():
        return out, tuple(json.loads(meta.read_text()))
    c = SOURCES[name]["c"]
    picks = [c[0] // 2, (c[0] + c[1]) // 2, (c[1] + c[2]) // 2]
    x0, y0, x1, y1 = CAP
    m = np.ones((y1 - y0, x1 - x0), bool)
    for n in picks:
        f = frame(name, n)[y0:y1, x0:x1].astype(int)
        m &= (f.min(2) > 175) & (f.max(2) - f.min(2) < 60)
    full = np.zeros((H, W), np.uint8)
    full[y0:y1, x0:x1] = m * 255
    im = Image.fromarray(full)
    for k in (9, 9, 9, 7):
        im = im.filter(ImageFilter.MaxFilter(k))
    arr = np.array(im)
    arr[GAME_TOP:] = 0
    im = Image.fromarray(arr)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    ys, xs = np.nonzero(np.array(im))
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    meta.write_text(json.dumps(bbox))
    return out, bbox


def cta_mask(name: str) -> Path:
    """Маска нижнего текста концовки: светлые, ненасыщенные и заметно ярче размытого фона во всех трёх кадрах
    концовки (текст статичен с первого кадра), + раздув на тень; выше игровой полосы не заходит."""
    out = D / "masks" / f"{name}_cta.png"
    if out.exists():
        return out
    c3 = SOURCES[name]["c"][2]
    x0, y0, x1, y1 = CTA
    m = None
    for n in (c3 + 20, c3 + 60, c3 + 100):
        a = frame(name, n)[y0:y1, x0:x1].astype(np.float32)
        g = a.mean(2)
        bg = np.array(Image.fromarray(g.astype(np.uint8)).filter(ImageFilter.GaussianBlur(14))).astype(np.float32)
        t = (a.min(2) > 170) & (a.max(2) - a.min(2) < 60) & (g - bg > 25)
        m = t if m is None else m & t
    full = np.zeros((H, W), np.uint8)
    full[y0:y1, x0:x1] = m * 255
    im = Image.fromarray(full)
    for k in (9, 9, 9, 7):
        im = im.filter(ImageFilter.MaxFilter(k))
    arr = np.array(im)
    arr[:BAND2[0]] = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr).save(out)
    return out


def card_png(job: dict, dest: Path) -> tuple[int, int, int, int]:
    """Карточка TikTok «Reply to <ник>'s comment» (core/comment_sticker) с живой аватаркой без лица (пул 1309);
    строки — по смыслу, как в COMMENTS. Низ — CARD_BOTTOM, по центру."""
    import core.comment_sticker as CS
    from PIL import ImageDraw, ImageOps
    if not getattr(CS, "_nl_wrap", False):
        orig = CS._wrap
        CS._wrap = lambda text, font, e, w: [ln for par in text.split(NL) for ln in orig(par, font, e, w)]
        CS._nl_wrap = True
        CS.COLUMN_MAX = 40

        def _avatar(d: int, seed: str) -> Image.Image:
            im = ImageOps.fit(Image.open(seed).convert("RGB"), (d, d), Image.Resampling.LANCZOS).convert("RGBA")
            mask = Image.new("L", (d, d), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, d - 1, d - 1), fill=255)
            im.putalpha(mask)
            return im
        CS._avatar = _avatar
    img = CS.render_reply_sticker(job["nick"], COMMENTS[job["comment"]], body_px=CARD_PX, avatar_seed=job["avatar"])
    canvas = Image.new("RGBA", img.size, (0, 0, 0, 0))
    canvas.alpha_composite(img)
    canvas.save(dest)
    x, y = (W - img.width) // 2, CARD_BOTTOM - img.height
    return x, y, x + img.width, y + img.height


LOW = 4                                        # чистка подписей — на полосе, уменьшенной в LOW раз (removelogo дорогой)
PAD1, PAD2 = (120, 520), (1380, H)             # полосы с запасом: окно removelogo не должно выходить за край кадра


def low_size(band: tuple[int, int]) -> tuple[int, int]:
    """Размер уменьшенной полосы — чётный (yuv420p: нечётная высота даёт цветной ореол)."""
    return W // LOW // 2 * 2, -(-(band[1] - band[0]) // (LOW * 2)) * 2


def small_mask(mask: Path, band: tuple[int, int]) -> Path:
    """Маска полосы band в уменьшенном масштабе: пиксель занят, если занят хоть один исходный; +1 px раздува."""
    out = mask.with_name(mask.stem + "_low.png")
    if not out.exists():
        m = Image.open(mask).convert("L").crop((0, band[0], W, band[1]))
        m = m.resize(low_size(band), Image.Resampling.BOX).point(lambda v: 255 if v else 0)
        m.filter(ImageFilter.MaxFilter(3)).save(out)
    return out


def ramp_png() -> Path:
    """Альфа для доразмытой полосы: плавный вход сверху 50 px, снизу — граница игровой полосы."""
    out = D / "masks" / "_band_ramp.png"
    if not out.exists():
        r = np.full((BAND[1] - BAND[0], W), 255, np.uint8)
        r[:50] = np.linspace(0, 255, 50)[:, None].astype(np.uint8)
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(r).save(out)
    return out


def plate_png(name: str) -> tuple[Path, tuple[int, int, int, int]]:
    """Та же фраза на наших белых плашках TikTok (чёрный текст), по центру исходной подписи."""
    import build_1321_carousels as R
    out = D / "plates" / f"{name}.png"
    _m, bb = cap_mask(name)
    px = PX_MAX
    b = R.plates(SOURCES[name]["text"], px)
    while b.width > SAFE_X1 - SAFE_X0 and px > PX_MIN:
        px -= 2
        b = R.plates(SOURCES[name]["text"], px)
    cy = (bb[1] + bb[3]) // 2
    x, y = (W - b.width) // 2, max(200, cy - b.height // 2)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(b, (x, y))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out, (x, y, x + b.width, y + b.height)


def music_prep() -> Path:
    norm = MUSIC.with_name(MUSIC.stem + "_-14lufs.wav")
    if not norm.exists():
        log = subprocess.run([FF, "-hide_banner", "-i", str(MUSIC), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                              "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
        j = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log).group(0))
        subprocess.run([FF, "-v", "error", "-y", "-i", str(MUSIC), "-af",
                        f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:"
                        f"measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}:"
                        "linear=true,aresample=48000", "-ac", "2", "-c:a", "pcm_s16le", str(norm)], check=True)
    return norm


def beat_frame(k: int) -> int:
    """Кадр ролика, на который приходится k-й бит от начала ролика (трек стартует ровно на бите)."""
    return round(k * P * FPS)


def segments(name: str, pat: str, j: int, split: tuple[int, int, int], delta: int, nf: int) -> list[tuple[int, int]] | None:
    """Отрезки исходника [s, e) по кадрам; None — не влезает в удержания образов."""
    s = SOURCES[name]
    c1, c2, c3 = s["c"]
    ramp, settle = s["ramp"], s["settle"]
    a, b, c = split
    f1, f2, f3 = beat_frame(a), beat_frame(a + b), beat_frame(a + b + c)
    la, lb, lc, le = f1, f2 - f1, f3 - f2, TOTAL - f3
    if pat == "P1":
        seg = [(c1 - la, c1), (c1, c1 + lb), (c3 - lc, c3), (c3, c3 + le)]
        ok = c1 - la >= 0 and c1 + lb <= c2 - ramp and c3 - lc >= c2 + settle
    else:
        seg = [(delta, delta + la), (c2 - lb, c2), (c2, c2 + lc), (c3, c3 + le)]
        ok = delta + la <= c1 - ramp and c2 - lb >= c1 + settle and c2 + lc <= c3 - ramp
    ok = ok and c3 + le <= nf
    return seg if ok else None


ANCHOR = {"P1": ["end", "start", "end", "start"], "P2": ["start", "end", "start", "start"]}


def speed_segs(name: str, pat: str, segs: list[tuple[int, int]], sp: float, nf: int) -> list[tuple[int, int]] | None:
    """Отрезки исходника под скорость sp: длина round(L·sp), край у смены образа остаётся на месте."""
    s = SOURCES[name]
    c1, c2, c3 = s["c"]
    out = []
    for (a, b), anc in zip(segs, ANCHOR[pat]):
        n = round((b - a) * sp)
        out.append((b - n, b) if anc == "end" else (a, a + n))
    if pat == "P1":
        ok = out[0][0] >= 0 and out[1][1] <= c2 - s["ramp"] and out[2][0] >= c2 + s["settle"]
    else:
        ok = out[0][0] >= 0 and out[0][1] <= c1 - s["ramp"] and out[1][0] >= c1 + s["settle"] and out[2][1] <= c3 - s["ramp"]
    return out if ok and out[3][1] <= nf else None


def uniq(rng: random.Random) -> dict:
    return {"zoom": round(rng.uniform(1.0, 1.06), 4), "fx": round(rng.random(), 3), "fy": round(rng.random(), 3),
            "br": round(rng.uniform(-0.025, 0.025), 4), "ct": round(rng.uniform(0.97, 1.05), 4),
            "sat": round(rng.uniform(0.94, 1.10), 4), "gam": round(rng.uniform(0.97, 1.03), 4),
            "hue": round(rng.uniform(-4, 4), 2), "noise": rng.randint(2, 4), "speed": round(rng.uniform(0.98, 1.02), 4)}


def plan(count: int, names: list[str]) -> list[dict]:
    """count роликов в каждую папку; исходники поровну; наборы (исходник, схема, j, разбивка, δ) не повторяются."""
    rng = random.Random(1311)
    nfs = {n: nframes(n) for n in names}
    variants = {n: [] for n in names}
    for n in names:
        for j in range(4):
            N = DROP - j
            for a in range(3, 7):
                for b in range(3, 7):
                    c = N - a - b
                    if not 3 <= c <= 6:
                        continue
                    if segments(n, "P1", j, (a, b, c), 0, nfs[n]):
                        variants[n].append(("P1", j, (a, b, c), 0))
                    for dl in range(0, 200, 9):
                        if segments(n, "P2", j, (a, b, c), dl, nfs[n]):
                            variants[n].append(("P2", j, (a, b, c), dl))
        rng.shuffle(variants[n])
        # P1 (переход исходника целиком) — вперёд
        variants[n].sort(key=lambda v: v[0] != "P1")
    from build_1309_reels import AVATAR_DIRS, PEOPLE
    nicks = [p[1] for p in PEOPLE]
    avatars = sorted(str(p) for d in AVATAR_DIRS for p in d.glob("*.jpg"))
    rng.shuffle(nicks)
    rng.shuffle(avatars)
    jobs, k = [], 0
    for plat in FOLDERS:
        for i in range(count):
            n = names[k % len(names)]
            pat, j, split, dl = variants[n][k // len(names)]
            segs = segments(n, pat, j, split, dl, nfs[n])
            u = uniq(rng)
            src_segs = speed_segs(n, pat, segs, u["speed"], nfs[n])
            if src_segs is None:
                u["speed"], src_segs = 1.0, segs
            jobs.append({"plat": plat, "n": i + 1, "src": n, "pat": pat, "j": j, "split": list(split), "delta": dl,
                         "segs": segs, "src_segs": src_segs, "uniq": u, "comment": k % len(COMMENTS),
                         "nick": nicks[k % len(nicks)], "avatar": avatars[k % len(avatars)]})
            k += 1
    return jobs


def build(job: dict) -> str:
    out = Path(job["out"])
    dest = out / f"{job['plat'].lower()}_{job['n']:03d}_{ID}.mp4"
    name = job["src"]
    mask, _bb = cap_mask(name)
    plate, _pb = plate_png(name)
    music = music_prep()
    cta = cta_mask(name)
    tmp = out / "_tmp"
    tmp.mkdir(exist_ok=True)
    card = tmp / f"{dest.stem}_card.png"
    cx0, _cy0, cx1, cy1 = card_png(job, card)
    full = Image.open(card)
    pops = []                                  # «выскакивание» карточки на бите: 3 кадра масштаба, потом 1.0
    for i, sc in enumerate(POP):
        im = Image.new("RGBA", full.size, (0, 0, 0, 0))
        sm = full.resize((max(1, round(full.width * sc)), max(1, round(full.height * sc))), Image.Resampling.LANCZOS)
        if sm.width > full.width:
            sm = sm.crop(((sm.width - full.width) // 2, sm.height - full.height, (sm.width + full.width) // 2, sm.height))
        im.alpha_composite(sm, ((full.width - sm.width) // 2, (full.height - sm.height) // 2))
        pp = tmp / f"{dest.stem}_pop{i}.png"
        im.save(pp)
        pops.append(pp)
    segs, u = job["segs"], job["uniq"]
    f3 = sum(e - s for s, e in segs[:3])
    parts = [f"[0:v]trim=start_frame={a}:end_frame={b},setpts=(PTS-STARTPTS)/{u['speed']},fps={FPS},"
             f"tpad=stop_mode=clone:stop=3,trim=end_frame={e - s},setpts=PTS-STARTPTS[v{i}]"
             for i, ((s, e), (a, b)) in enumerate(zip(segs, job["src_segs"]))]
    zw, zh = round(W * u["zoom"] / 2) * 2, round(H * u["zoom"] / 2) * 2
    zx, zy = round((zw - W) * u["fx"]), round((zh - H) * u["fy"])
    t3 = f3 / FPS - 0.5 / FPS
    dur = TOTAL / FPS
    en = f"enable='lt(t,{t3:.4f})'"
    en2 = f"enable='gte(t,{t3:.4f})'"
    cta_f = cta.as_posix().replace(":", chr(92) + ":")
    b2h = BAND2[1] - BAND2[0]
    pop_chain = []
    last = "g2"
    for i in range(len(POP) + 1):
        a, b = t3 + i / FPS, t3 + (i + 1) / FPS
        cond = f"between(t,{a:.4f},{b - 0.001:.4f})" if i < len(POP) else f"gte(t,{a:.4f})"
        pop_chain.append(f"[{last}][{4 + i}:v]overlay={cx0}:{cy1 - full.height}:enable='{cond}'[p{i}]")
        last = f"p{i}"
    esc = lambda q: q.as_posix().replace(":", chr(92) + ":")  # noqa: E731
    m_cap, m_cta = esc(small_mask(mask, PAD1)), esc(small_mask(cta, PAD2))
    bh = BAND[1] - BAND[0]
    ls1, ls2 = low_size(PAD1), low_size(PAD2)
    p1h, p2h = PAD1[1] - PAD1[0], PAD2[1] - PAD2[0]
    parts += ["".join(f"[v{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0[c]",
              "[c]split[r][rb]",
              f"[rb]crop={W}:{p1h}:0:{PAD1[0]},scale={ls1[0]}:{ls1[1]}:flags=area,removelogo=f='{m_cap}',"
              f"gblur=sigma=3,scale={W}:{p1h}:flags=bicubic,crop={W}:{bh}:0:{BAND[0] - PAD1[0]},format=rgba[bb]",
              "[3:v]format=gray[rm]", "[bb][rm]alphamerge[bl]",
              f"[r][bl]overlay=0:{BAND[0]}:{en}[r2]",
              "[r2]split[e][eb]",
              f"[eb]crop={W}:{p2h}:0:{PAD2[0]},scale={ls2[0]}:{ls2[1]}:flags=area,removelogo=f='{m_cta}',"
              f"gblur=sigma=3,scale={W}:{p2h}:flags=bicubic,crop={W}:{b2h}:0:{BAND2[0] - PAD2[0]}[b2]",
              f"[e][b2]overlay=0:{BAND2[0]}:{en2}[e3]",
              f"[e3]scale={zw}:{zh}:flags=lanczos,crop={W}:{H}:{zx}:{zy},"
              f"eq=brightness={u['br']}:contrast={u['ct']}:saturation={u['sat']}:gamma={u['gam']},"
              f"hue=h={u['hue']},noise=alls={u['noise']}:allf=t,format=yuv420p,format=rgb24[g]",
              f"[g][1:v]overlay=0:0:{en}[g2]",
              *pop_chain, f"[{last}]format=yuv420p[v]",
              f"[2:a]atrim=duration={dur:.3f},afade=t=out:st={dur - 0.3:.3f}:d=0.3,asetpts=PTS-STARTPTS[a]"]
    m0 = B0 + job["j"] * P
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src(name)), "-i", str(plate), "-ss", f"{m0:.4f}", "-i", str(music),
                    "-loop", "1", "-i", str(ramp_png()),
                    *[x for pp in pops + [card] for x in ("-loop", "1", "-framerate", str(FPS), "-i", str(pp))],
                    "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]", "-frames:v", str(TOTAL),
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0", "-profile:v", "high",
                    "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(dest)], check=True)
    for pp in pops + [card]:
        pp.unlink(missing_ok=True)
    return dest.name


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=250, help="роликов в каждую папку (TT и YT)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--test", action="store_true", help="по одному ролику на исходник → output/1311_test")
    args = ap.parse_args()
    names = list(SOURCES)
    for n in names:
        _m, bb = cap_mask(n)
        _p, pb = plate_png(n)
        bad = check_box(W, H, pb)
        print(f"{n}: подпись {bb}, плашка {pb}{'  ВНЕ ЗОНЫ ' + str(bad) if bad else ''}", flush=True)
        if bad:
            return 1
    jobs = plan(5 if args.test else args.count, names)
    for k in range(len(COMMENTS)):
        cb = card_png({"nick": "x" * 16, "comment": k, "avatar": jobs[0]["avatar"]}, D / "plates" / f"_card{k}.png")
        if check_box(W, H, cb):
            print(f"карточка {k} вне зоны: {cb}")
            return 1
    if args.test:
        jobs = [j for j in jobs if j["plat"] == "TT"]
    for j in jobs:
        out = ROOT / "output" / ("1311_test" if args.test else f"{ID}_{j['plat']}_{args.count}")
        out.mkdir(parents=True, exist_ok=True)
        j["out"] = str(out)
    if not args.test:
        for plat in FOLDERS:
            part = [j for j in jobs if j["plat"] == plat]
            (Path(part[0]["out"]) / "manifest.json").write_text(json.dumps(part, indent=1), encoding="utf-8")
    todo = [j for j in jobs if not (Path(j["out"]) / f"{j['plat'].lower()}_{j['n']:03d}_{ID}.mp4").exists()]
    print(f"собрать {len(todo)} из {len(jobs)}", flush=True)
    with ProcessPoolExecutor(args.jobs) as ex:
        for k, nm in enumerate(ex.map(build, todo), 1):
            print(f"[{k}/{len(todo)}] {nm}", flush=True)
    print("готово")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
