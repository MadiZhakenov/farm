#!/usr/bin/env python3
"""
Drops (ID 1) «whimsical websites to train your ear» — наш удачный формат 1389 (вода/небо, адресная строка, пастельный iMac,
меню Copy/Select All, белая карточка с номером) + обложка как у рефа @cowsites.net (маленькие картинки про музыку вокруг надписи).
Тексты ТЗ дословно, переносы по смыслу. Drops = слайд 3 (сайт №2); кадры Drops — ТОЛЬКО из Dropbox клиента
(downloads/drops_ear/shots/drops_*: записи сайта и геймплея), остальные сайты — скрины во встроенном браузере.

Карусели 3:4 1080×1440 (фон — вода 1389), видео 9:16 (фон — небо 1391), трек 1391, смены на долях:
обложка 0–1.61, musicmap → 2.40, drops → 3.97, whosampled → 5.55, samplette → 7.13 с.
Уникальность: у каждой карусели/видео своё сочетание фон × цвет iMac × скрины × картинки обложки + свой кроп фона.

  python build_drops_ear.py --test                 # 3 карусели + 3 видео → output/_work/drops_ear/test
  python build_drops_ear.py -n 200                 # → output/drops_ear_TT_200 (sort_<слайд>_<n>_1.jpg)
  python build_drops_ear.py -n 200 --video         # → output/drops_ear_YT_200 (drops_ear_yt_NNN_1.mp4)
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1389b as M  # noqa: E402
B = M.B
V = M.V
from core.safe_zones import check_box  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402

SHOTS = ROOT / "downloads" / "drops_ear" / "shots"
OBJ = ROOT / "downloads" / "drops_inspire" / "objects"          # вырезанные музыкальные предметы (rembg)
WORK = ROOT / "output" / "_work" / "drops_ear"
COVER = ("whimsical", "websites", "to train your", "ear")       # «whimsical websites to train your ear» дословно
SITES = [  # (ключ скринов, адрес, заголовок, описание ТЗ дословно — строки по смыслу)
    ("musicmap", "musicmap.info", "1. Musicmap", [
        "Interactive genealogy of music.",
        "It shows how genres emerged,",
        "which movements influenced each other,",
        "and how musical styles developed"]),
    ("drops", "drops.game", "2. Drops", [
        "An interactive music game builder",
        "that turns your song into a small video game.",
        "It creates a game world inspired",
        "by the rhythm and mood of the selected track.",
        "No programming skills required.",
        "Upload your songs and play",
        "with other users’ tracks"]),
    ("whosampled", "whosampled.com", "3. WhoSampled", [
        "Explore where samples came from,",
        "how old recordings were turned into new compositions,",
        "and which songs were reimagined",
        "by different artists"]),
    ("samplette", "samplette.io", "4. Samplette", [
        "Musical roulette.",
        "Serves up random tracks from YouTube,",
        "and you can set filters by genre,",
        "tempo, key, and popularity"]),
]
CUTS = [0.0, V.BEATS13[0], V.BEATS13[1], V.BEATS13[3], V.BEATS13[5]]   # 0, 1.61, 2.40, 3.97, 5.55
END = V.BEATS13[7]                                                        # 7.135


def card(title: str, lines: list[str]) -> tuple[Image.Image, list]:
    """Белое окно 1389: светофор, номер розовой меткой, имя сайта, описание ТЗ (строки по смыслу). Ширина — по тексту."""
    num, name = title.split(" ", 1)
    pad = 28
    fd = B.font(B.F_REG, 22)
    lh = 30
    tw = max(fd.getlength(s) for s in lines)
    ft = B.font(B.F_BOLD, 60)
    width = int(max(430, min(660, max(tw, ft.getlength(name)) + 2 * pad + 6)))
    if tw > width - 2 * pad:
        raise SystemExit(f"строка шире карточки: {max(lines, key=fd.getlength)}")
    t_img = B.text_img(name, ft, B.INK + (255,), track=-0.035)
    tg = B.tag(num, 28)
    h = pad + 26 + tg.height + 6 + t_img.height + 16 + lh * len(lines) + pad + 2
    c = B.rounded((width, h), 22, (255, 255, 255, 255))
    d = ImageDraw.Draw(c)
    for k, col in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
        d.ellipse((pad + k * 20, pad - 2, pad + k * 20 + 11, pad + 9), fill=col)
    y = pad + 26
    c.alpha_composite(tg, (pad - 4, y))
    y += tg.height + 6
    c.alpha_composite(t_img, (pad - 2, y))
    y += t_img.height + 16
    for ln in lines:
        d.text((pad, y), ln, font=fd, fill=B.INK2)
        y += lh
    return c, [(pad - 4, pad + 26, width - pad, h - pad)]


def site_layer(k: int, shot: Path, rng: random.Random) -> tuple[Image.Image, list]:
    """Адресная строка → iMac → меню → карточка (заходит на подставку) → курсор, на прозрачном слое 760 px."""
    key, domain, title, lines = SITES[k]
    bar, mac, pill = B.address_bar(domain), B.imac(shot), B.menu_pill()
    cd, cboxes = card(title, lines)
    lw = 780
    bx, by = (lw - bar.width) // 2, 0
    mx, my = (lw - mac.width) // 2, by + bar.height + 30
    px_, py_ = mx + mac.width - pill.width - 4, my + 383 + 32 + 22
    cx_ = (lw - cd.width) // 2 + rng.randint(-24, 24) + (30 if cd.width < 560 else 0)
    cx_ = max(0, min(lw - cd.width, cx_))
    cy_ = my + 383 + 32 + 22 + 46 + 12
    lh = cy_ + cd.height + 40
    L = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    for el, (x, y), sh in ((bar, (bx, by), (10, 0.2, 4)), (mac, (mx, my), (18, 0.35, 10)),
                           (pill, (px_, py_), (8, 0.25, 3)), (cd, (cx_, cy_), (18, 0.3, 10))):
        s, p = B.shadowed(el, blur=sh[0], opacity=sh[1], offset=(0, sh[2]))
        L.alpha_composite(s, (x - p, y - p))
    L.alpha_composite(B.cursor(), (cx_ + cd.width - 44, cy_ + cd.height - 44))
    boxes = [(bx + 60, by + 8, bx + bar.width - 60, by + bar.height - 8)]
    boxes += [(cx_ + a, cy_ + b, cx_ + c, cy_ + d) for a, b, c, d in cboxes]
    return L, boxes


def background(bg: Path, rng: random.Random, video: bool) -> Image.Image:
    """Фон 1389/1391 со своим кропом на каждый ролик: зеркало, приближение 1.0–1.25, сдвиг."""
    W, H = (V.W, V.H) if video else (B.W, B.H)
    im = ImageOps.exif_transpose(Image.open(bg)).convert("RGB")
    if rng.random() < 0.5:
        im = ImageOps.mirror(im)
    z = rng.uniform(1.0, 1.25)
    cw, ch = im.width / z, im.height / z
    x0, y0 = rng.uniform(0, im.width - cw), rng.uniform(0, im.height - ch)
    im = im.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))
    return ImageOps.fit(im, (W, H), Image.Resampling.LANCZOS).convert("RGBA")


def slide_site(k: int, shot: Path, bg: Path, rng: random.Random, video: bool) -> tuple[Image.Image, list]:
    W, H = (V.W, V.H) if video else (B.W, B.H)
    im = background(bg, rng, video)
    L, boxes = site_layer(k, shot, rng)
    # у каждого слайда свой масштаб и место (иначе ролики с тем же фоном и тем же скрином дают общие кадры — замер 16.11)
    s = rng.uniform(1.0, 1.16) if video else rng.uniform(0.92, 1.03)
    L = L.resize((round(L.width * s), round(L.height * s)), Image.Resampling.LANCZOS)
    boxes = [tuple(round(v * s) for v in b) for b in boxes]
    bx0, by0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    bx1, by1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    if video:
        xl, xr, yt, yb = 150, 930, 210, 1530
    else:
        xl, xr, yt, yb = 188, 892, 92, 1116
    xs = (max(xl - bx0, (W - L.width) // 2 - 50), min(xr - bx1, (W - L.width) // 2 + 50))
    ys = (yt - by0, yb - by1)
    if xs[0] > xs[1] or ys[0] > ys[1]:
        raise SystemExit(f"слайд {k + 2}: блок не помещается в безопасную зону при масштабе {s:.2f}")
    x0, y0 = rng.randint(*xs), rng.randint(*ys)
    M.stars(im, rng, [(x0, y0 + 20, x0 + L.width, y0 + L.height - 30)], rng.randint(10, 14) if not video else rng.randint(12, 17), W, H)
    im.alpha_composite(L, (x0, y0))
    return im.convert("RGB"), [(a + x0, b + y0, c + x0, d + y0) for a, b, c, d in boxes]


def place_objects(im: Image.Image, rng: random.Random, objs: list[Path], text_box: tuple, video: bool) -> None:
    """Маленькие картинки про музыку (как у рефа): по углам вокруг надписи, не на тексте, лёгкий наклон и тень."""
    W, H = im.size
    x0, y0, x1, y1 = text_box
    side = (310, 400) if video else (270, 350)
    slots = [("tl", 40, 70 if not video else 150), ("tr", None, 70 if not video else 150),
             ("bl", 40, None), ("br", None, None)]
    rng.shuffle(slots)
    for (pos, _x, _y), f in zip(slots, objs):
        o = Image.open(f).convert("RGBA")
        bb = o.getbbox()
        if bb:
            o = o.crop(bb)
        s = rng.randint(*side) / max(o.size)
        o = o.resize((max(1, round(o.width * s)), max(1, round(o.height * s))), Image.Resampling.LANCZOS)
        o = o.rotate(rng.uniform(-14, 14), Image.Resampling.BICUBIC, expand=True)
        top_lim = y0 - 30 - o.height                      # над надписью
        bot_lim = y1 + 30                                 # под надписью
        if pos[0] == "t":
            y = rng.randint(max(40, min(top_lim, (150 if video else 60))), max(40, top_lim)) if top_lim > 40 else 40
        else:
            y = rng.randint(bot_lim, max(bot_lim, H - o.height - (150 if video else 60)))
        if pos[1] == "l":
            x = rng.randint(30, 150)
        else:
            x = W - o.width - rng.randint(30, 150)
        sh = add_shadow(o, blur=10, opacity=0.35, offset=(0, 8), grow=1, pad=30)
        im.alpha_composite(sh, (x - 30, y - 30))


def cover(bg: Path, rng: random.Random, video: bool, objs: list[Path]) -> tuple[Image.Image, list]:
    """«whimsical» / «websites» / [to train your] / «ear» — шрифты и тени обложки 1389, по углам — музыкальные предметы."""
    W, H = (V.W, V.H) if video else (B.W, B.H)
    k = 1.14 if video else 1.0
    im = background(bg, rng, video)
    white = (255, 255, 255, 255)
    limit = 760 if video else 700
    px = round(176 * k)
    while True:
        w1 = B.text_img(COVER[1], B.font(B.F_BOLD, px), white, track=-0.045)
        if w1.width <= limit:
            break
        px -= 4
    w2 = B.text_img(COVER[3], B.font(B.F_BOLD, px), white, track=-0.045)
    top = B.text_img(COVER[0], B.font(B.F_SEMI, round(64 * k)), white, track=-0.02)
    tg = B.tag(COVER[2], round(48 * k))
    cx = W // 2 + rng.randint(-8, 8)
    hsum = top.height + 16 + w1.height + 4 + tg.height + 4 + w2.height
    y = int((860 if video else 690) - hsum / 2) + rng.randint(-12, 12)
    x1 = cx - w1.width // 2
    els = [(top, x1 + 8, y)]
    y += top.height + 16
    els.append((w1, x1, y)); y += w1.height + 4
    els.append((tg, x1 + round(70 * k), y - 6)); y += tg.height + 4
    els.append((w2, x1 + w1.width - w2.width - round(10 * k), y))
    bx0 = min(e[1] for e in els); by0 = min(e[2] for e in els)
    bx1 = max(e[1] + e[0].width for e in els); by1 = max(e[2] + e[0].height for e in els)
    M.stars(im, rng, [(bx0, by0, bx1, by1)], rng.randint(10, 14) if not video else rng.randint(12, 16), W, H)
    lum = float(np.asarray(im.convert("L").crop((bx0, by0, bx1, by1)), dtype=np.float32).mean()) / 255
    d = min(max((lum - 0.42) * 1.3, 0.0), 0.38)
    if d > 0:
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).ellipse((bx0 - 90, by0 - 75, bx1 + 90, by1 + 75), fill=int(255 * d))
        dim = Image.new("RGBA", (W, H), (20, 40, 70, 0) if video else (8, 30, 40, 0))
        dim.putalpha(m.filter(ImageFilter.GaussianBlur(75)))
        im.alpha_composite(dim)
    place_objects(im, rng, objs, (bx0, by0, bx1, by1), video)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for e, x, yy in els:
        if e is not tg:
            layer.alpha_composite(e, (x, yy))
    sh = add_shadow(layer, blur=3, opacity=0.55, offset=(0, 2), grow=1, pad=0)
    sh = add_shadow(sh, blur=22, opacity=0.4, offset=(0, 0), grow=8, pad=0)
    im.alpha_composite(sh)
    im.alpha_composite(add_shadow(tg, blur=6, opacity=0.3, offset=(0, 2), grow=1, pad=20), (els[2][1] - 20, els[2][2] - 20))
    return im.convert("RGB"), [(bx0, by0, bx1, by1)]


def libs(video: bool):
    bgs = M.images(V.BG if video else B.BG)
    pools = [sorted(SHOTS.glob(f"{key}_*.png")) for key, *_ in SITES]
    objs = sorted(OBJ.glob("*.png"))
    return bgs, pools, objs


def plan(n: int, video: bool, seed: int) -> list[dict]:
    """Сочетания без повторов: фон × цвет iMac × скрин каждого сайта × набор картинок обложки; скрины — по кругу,
    чтобы каждый использовался поровну."""
    bgs, pools, objs = libs(video)
    if not bgs or not all(pools) or len(objs) < 4:
        raise SystemExit(f"пустые библиотеки: фонов {len(bgs)}, пулы {[len(p) for p in pools]}, картинок {len(objs)}")
    rng = random.Random(seed + (1 if video else 0))
    pals = {bg: (V.palettes(bg) if video else B.bg_palettes(bg)) for bg in bgs}
    decks = [[] for _ in pools]
    seen, jobs = set(), []
    for i in range(1, n + 1):
        for _ in range(500):
            pick = []
            for d, p in zip(decks, pools):
                if not d:
                    d.extend(rng.sample(p, len(p)))
                pick.append(d[-1])
            bg = bgs[(i - 1) % len(bgs)] if i <= len(bgs) else rng.choice(bgs)
            pal = rng.choice(pals[bg])
            ob = rng.sample(objs, 4)
            key = (bg.name, pal) + tuple(p.name for p in pick)
            if key not in seen:
                for d in decks:
                    d.pop()
                break
            for d, p in zip(decks, pools):
                rng.shuffle(d)
        else:
            raise SystemExit("не нашлось нового сочетания")
        seen.add(key)
        jobs.append(dict(i=i, bg=str(bg), pal=pal, shots=[str(p) for p in pick], objs=[str(o) for o in ob],
                         seed=seed * 10000 + i + (500000 if video else 0)))
    return jobs


def slide_hash(im: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """Отпечаток кадра как у check_uniq_allframes (весь кадр → 17×16 серых, dHash 256 бит) и зеркальный."""
    a = np.asarray(im.convert("L").resize((17, 16), Image.Resampling.BOX), np.int16)
    h = (a[:, 1:] > a[:, :-1]).reshape(-1)
    m = (a[:, ::-1][:, 1:] > a[:, ::-1][:, :-1]).reshape(-1)
    return h, m


def render_slides(job: dict, video: bool, cand: str) -> tuple:
    """Слайды одного ролика/карусели → файлы-кандидаты (PNG для видео, JPEG для карусели) + отпечатки слайдов."""
    W, H = (V.W, V.H) if video else (B.W, B.H)
    B.PAL = B.PALETTES[job["pal"]]
    r = random.Random(job["seed"])
    bg = Path(job["bg"])
    slides = [cover(bg, r, video, [Path(o) for o in job["objs"]])]
    slides += [slide_site(k, Path(job["shots"][k]), bg, r, video) for k in range(len(SITES))]
    for k, (_im, boxes) in enumerate(slides, 1):
        for b in boxes:
            if bad := check_box(W, H, b):
                raise SystemExit(f"{job['i']:03d} слайд {k}: текст вне безопасной зоны {b} — {bad}")
    cand = Path(cand)
    paths, hs = [], []
    for k, (im, _) in enumerate(slides, 1):
        f = cand / f"{job['i']:03d}_{job['seed']}_{k}.{'png' if video else 'jpg'}"
        if video:
            im.save(f)
        else:
            im.save(f, quality=94)
        paths.append(str(f))
        hs.append(slide_hash(im))
    return job, paths, hs


TIMING = ROOT / "downloads" / "drops_ear" / "_start.json"      # тюнер: tuner_drops_ear.py (старт песни, смены, конец)


def timing() -> tuple[float, list[float], float]:
    """(старт песни, смены от начала ролика с 0, конец) — из тюнера, иначе как в первой партии; смены — по кадрам."""
    if TIMING.exists():
        st = json.loads(TIMING.read_text(encoding="utf-8"))
        a0, cuts, end = st["start"], [0.0] + [t - st["start"] for t in st["cuts"]], st["end"] - st["start"]
    else:
        a0, cuts, end = 0.0, CUTS, END
    return a0, [round(t * V.FPS) / V.FPS for t in cuts], round(end * V.FPS) / V.FPS


def music(a0: float, end: float) -> Path:
    out = WORK / f"ear_music_{a0:.3f}_{end:.3f}.wav"
    if not out.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a0:.3f}", "-i", str(V.MUSIC), "-t", f"{end:.3f}",
                        "-af", f"afade=t=out:st={end - 0.25:.3f}:d=0.25,loudnorm=I=-14:TP=-1.5:LRA=11",
                        "-ar", "44100", "-ac", "2", str(out)], check=True)
    return out


def encode(paths: list[str], dest: str) -> str:
    a0, cuts, end = timing()
    V.render([Path(p) for p in paths], music(a0, end), Path(dest), cuts, end)
    for p in paths:
        Path(p).unlink(missing_ok=True)
    return Path(dest).name


def new_job(i: int, video: bool, rng: random.Random, seen: set) -> dict:
    """Новое сочетание (замена похожего): случайный фон, цвет, скрины, картинки обложки, своё зерно."""
    bgs, pools, objs = libs(video)
    for _ in range(1000):
        bg = rng.choice(bgs)
        pal = rng.choice(V.palettes(bg) if video else B.bg_palettes(bg))
        pick = [rng.choice(p) for p in pools]
        key = (bg.name, pal) + tuple(p.name for p in pick)
        if key not in seen:
            seen.add(key)
            return dict(i=i, bg=str(bg), pal=pal, shots=[str(p) for p in pick], objs=[str(o) for o in rng.sample(objs, 4)],
                        seed=rng.randrange(10 ** 9))
    raise SystemExit("не нашлось нового сочетания")


def reencode(a) -> int:
    """Принятые видео заново: слайды по тем же зёрнам (уникальность та же), песня и смены — из тюнера."""
    from concurrent.futures import ThreadPoolExecutor
    jobs = json.loads(a.reencode.read_text(encoding="utf-8"))
    out = a.out or ROOT / "output" / "_work" / "drops_ear" / "reenc"
    out.mkdir(parents=True, exist_ok=True)
    cand = WORK / "cand_r"
    cand.mkdir(parents=True, exist_ok=True)
    a0, cuts, end = timing()
    music(a0, end)
    print(f"песня с {a0:.3f} с, смены {cuts}, конец {end:.3f} с → {out}", flush=True)
    done = 0
    with ProcessPoolExecutor(a.jobs) as ex, ThreadPoolExecutor(3) as enc:
        encs = []
        for job, paths, _ in ex.map(render_slides, jobs, [True] * len(jobs), [str(cand)] * len(jobs)):
            encs.append(enc.submit(encode, paths, str(out / f"drops_ear_yt_{job['i']:03d}_{a.id}.mp4")))
        for f in encs:
            f.result()
            done += 1
            if done % 25 == 0:
                print(f"  {done}/{len(jobs)}", flush=True)
    print(f"готово: {done} видео → {out}")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=3)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--video", action="store_true")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--seed", type=int, default=16111)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--thr", type=int, default=48, help="приёмка: ни один слайд не ближе стольких бит к слайдам принятых")
    ap.add_argument("--reencode", type=Path, help="manifest_video_*.json принятой партии: те же слайды, смены из тюнера")
    ap.add_argument("--id", default="1", help="окончание имён файлов (ID)")
    a = ap.parse_args()
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    WORK.mkdir(parents=True, exist_ok=True)
    if a.reencode:
        return reencode(a)
    out = a.out or (WORK / "test" if a.test else ROOT / "output" / f"drops_ear_{'YT' if a.video else 'TT'}_{a.n}")
    out.mkdir(parents=True, exist_ok=True)
    cand = WORK / ("cand_v" if a.video else "cand_c")
    cand.mkdir(parents=True, exist_ok=True)
    for f in cand.glob("*"):
        f.unlink()
    jobs = plan(a.n, a.video, a.seed)
    seen = {(Path(j["bg"]).name, j["pal"]) + tuple(Path(p).name for p in j["shots"]) for j in jobs}
    rng = random.Random(a.seed + 99)
    if a.video:
        t0, _, t1 = timing()
        music(t0, t1)                                              # общий трек — заранее, не в каждом процессе
    bank = np.zeros((0, 256), np.float32)                          # ±1: прямые и зеркальные отпечатки принятых слайдов
    accepted, rej = [], 0

    def near(hs) -> bool:
        if not len(bank):
            return False
        q = np.stack([h for h, _ in hs]).astype(np.float32) * 2 - 1
        d = (256 - q @ bank.T) / 2
        return bool((d <= a.thr).any())
    enc = ThreadPoolExecutor(3)
    encs = []
    with ProcessPoolExecutor(min(a.jobs, a.n)) as ex:
        live = {ex.submit(render_slides, j, a.video, str(cand)) for j in jobs}
        while live:
            done, live = wait(live, return_when=FIRST_COMPLETED)
            for fu in done:
                job, paths, hs = fu.result()
                if near(hs):
                    rej += 1
                    for p in paths:
                        Path(p).unlink(missing_ok=True)
                    live.add(ex.submit(render_slides, new_job(job["i"], a.video, rng, seen), a.video, str(cand)))
                    continue
                add = np.concatenate([np.stack([h for h, _ in hs]), np.stack([m for _, m in hs])]).astype(np.float32) * 2 - 1
                bank = np.concatenate([bank, add])
                accepted.append(job)
                i = job["i"]
                if a.video:
                    encs.append(enc.submit(encode, paths, str(out / f"drops_ear_yt_{i:03d}_1.mp4")))
                else:
                    for k, pth in enumerate(paths, 1):
                        Path(pth).replace(out / f"sort_{k}_{i}_1.jpg")
                if len(accepted) % 20 == 0:
                    print(f"  принято {len(accepted)}/{a.n}, заменено похожих {rej}", flush=True)
    for f in encs:
        f.result()
    enc.shutdown()
    (WORK / (f"manifest_{'video' if a.video else 'carousels'}_{'test' if a.test else a.n}.json")).write_text(
        json.dumps(sorted(accepted, key=lambda j: j["i"]), indent=1, ensure_ascii=False), encoding="utf-8")
    if not a.video and not a.test:
        subprocess.run([sys.executable, str(ROOT / "strip_jpeg_meta.py"), str(out)], check=False)
    print(f"готово: {a.n} {'видео' if a.video else 'каруселей'} → {out}; заменено похожих {rej}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
