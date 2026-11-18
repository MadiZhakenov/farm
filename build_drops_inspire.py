#!/usr/bin/env python3
"""
Drops (ID 1) — «Websites that keep you inspired to make music Part 2»: 150 каруселей (TikTok, 3:4, 4 слайда) +
100 видео (YouTube, 9:16, слайды меняются на бит звука рефа). ТЗ 16.11, реф @wloverae/photo/7629723059548589320
(downloads/drops_inspire/ref): кремовый фон, строка меню, крупное узкое засечное название сайта, абзац описания,
строка поиска с адресом, белый монитор со скрином сайта и две сиреневые подписи со звёздочкой.

  1 — обложка: «Websites that keep you inspired to make music» + «Part 2» и вырезанные предметы (наушники, проигрыватель,
      гитара, ноутбук, кассета…) со звёздочками;
  2 — cratedrop, 3 — drops (продукт), 4 — radiooooo: описания из ТЗ дословно.

Текст — только в безопасной рамке core/safe_zones (3:4: x 180–900, y 6–78 %; 9:16: x 140–940, y 200–1540).

    python build_drops_inspire.py --test                 # 3 карусели + 1 видео → output/_work/drops_inspire/test
    python build_drops_inspire.py --car 150 --vid 100     # партия
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
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import safe_zones as SZ  # noqa: E402
from core.gpu_ffmpeg import CLEAN  # noqa: E402

W, H = 1080, 1440
VW, VH = 1080, 1920
D = ROOT / "downloads" / "drops_inspire"
WORK = ROOT / "output" / "_work" / "drops_inspire"
NAME, ID = "drops_inspire", 1
F_SERIF = ROOT / "fonts" / "instrument" / "InstrumentSerif-Regular.ttf"
F_REG = ROOT / "fonts" / "inter" / "Inter-Regular.ttf"
F_MED = ROOT / "fonts" / "inter" / "Inter-Medium.ttf"
F_SEMI = ROOT / "fonts" / "inter" / "Inter-SemiBold.ttf"
BG = (247, 243, 237)
BG_TONES = [(247, 243, 237), (246, 241, 233), (248, 244, 239), (245, 240, 234), (249, 245, 238), (247, 242, 236)]
INK = (44, 32, 26)
LAV, LAV_LINE = (237, 228, 252), (126, 98, 178)
SPARK = (226, 205, 250)

COVER = ["Websites that keep", "you inspired", "to make music"]   # ТЗ: «Websites that keep you inspired to make music Part 2»
PART = "Part 2"
SITES = [   # описания — ТЗ дословно
    dict(key="cratedrop", title="cratedrop", url="https://www.cratedrop.app",
         desc="Virtual crate digging. Randomly picks records from the Discogs catalog. You can search for rare jazz, "
              "funk, electronic music, and little-known releases",
         tags=("dig a random record\nfrom Discogs", "rare jazz, funk\n& electronic"), spots=(("L", 0.62), ("R", 0.30)), shots=["cratedrop_01", "cratedrop_02", "cratedrop_06"]),
    dict(key="drops", title="drops", url="https://drops.game/",
         desc="No-code platform for creating music-based video games. It lets you turn almost any song into a small "
              "interactive game, and you don't need to know how to program or design game levels manually",
         tags=("turn any song\ninto a game", "no coding\nneeded"), spots=(("R", 0.66), ("L", 0.90)), shots=["drops_01", "drops_02", "drops_03", "drops_old_01", "drops_old_02", "drops_old_03", "drops_old_04"]),
    dict(key="radiooooo", title="radiooooo", url="https://app.radiooooo.com",
         desc="A musical time machine. Pick a country and a decade (for example, 1970s Japan or 1930s France) and "
              "listen to the music of that era",
         tags=("pick a country\n& a decade", "listen to the music\nof that era"), spots=(("L", 0.30), ("R", 0.58)), shots=["radiooooo_01", "radiooooo_02", "radiooooo_04"]),
]
NAV = ("PART 2", "WEBSITES THAT KEEP YOU INSPIRED", "SAVE FOR LATER")
COVER_SIG: list = []
OBJECTS = ["headphones", "turntable_case", "guitar", "macbook", "cassette", "turntable", "guitar2"]


def font(p: Path, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(p), px)


def tracked(d: ImageDraw.ImageDraw, xy, text: str, f, fill, track: float) -> int:
    """Текст с разрядкой; возвращает ширину."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        x += f.getlength(ch) + track
    return int(x - xy[0] - track)


def tracked_w(text: str, f, track: float) -> float:
    return sum(f.getlength(c) for c in text) + track * (len(text) - 1)


def balanced_wrap(text: str, f, maxw: int) -> list[str]:
    """Абзац ровными строками (не «жадно»): минимальное число строк, длины выровнены."""
    words = text.split()
    n = 1
    while True:
        best = None
        target = f.getlength(text) / n
        lines, cur = [], []
        for w in words:
            t = " ".join(cur + [w])
            if cur and (f.getlength(t) > maxw or (f.getlength(t) > target * 1.08 and len(lines) < n - 1)):
                lines.append(" ".join(cur))
                cur = [w]
            else:
                cur.append(w)
        lines.append(" ".join(cur))
        if len(lines) <= n and all(f.getlength(l) <= maxw for l in lines):
            best = lines
        if best:
            return best
        n += 1


def nav(img: Image.Image, y: int) -> list:
    d = ImageDraw.Draw(img)
    f = font(F_MED, 17)
    x0, _, x1, _ = SZ.text_rect(W, H)
    boxes = []
    for i, t in enumerate(NAV):
        tw = tracked_w(t, f, 1.6)
        x = x0 if i == 0 else (x1 - tw if i == 2 else (W - tw) / 2)
        tracked(d, (x, y), t, f, INK, 1.6)
        boxes.append((int(x), y, int(x + tw), y + 22))
    return boxes


def magnifier(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int, w: int) -> None:
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=INK, width=w)
    a = math.radians(45)
    x1, y1 = cx + r * math.cos(a), cy + r * math.sin(a)
    d.line((x1, y1, x1 + r * 0.9, y1 + r * 0.9), fill=INK, width=w + 1)


def asterisk(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    for k in range(6):
        a = math.radians(90 + k * 60)
        d.line((cx, cy, cx + r * math.cos(a), cy - r * math.sin(a)), fill=INK, width=4)


def callout(img: Image.Image, text: str, x: int, y: int, star_left: bool) -> tuple:
    d = ImageDraw.Draw(img)
    f = font(F_MED, 21)
    lines = text.split("\n")
    tw = max(f.getlength(l) for l in lines)
    w, h = int(tw + 44), 22 + 27 * len(lines)
    d.rounded_rectangle((x, y, x + w, y + h), radius=12, fill=LAV, outline=LAV_LINE, width=2)
    for i, l in enumerate(lines):
        d.text((x + (w - f.getlength(l)) / 2, y + 10 + i * 27), l, font=f, fill=INK)
    asterisk(d, x + (26 if star_left else w - 26), y - 2, 15)
    return (x, y - 17, x + w, y + h)


def monitor(img: Image.Image, shot: Path, top: int, width: int) -> tuple[int, int, int, int]:
    """Белый монитор на подставке со скрином; возвращает прямоугольник корпуса."""
    sh = Image.open(shot).convert("RGB")
    sw = width - 28
    shh = round(sw * sh.height / sh.width)
    sh = sh.resize((sw, shh), Image.Resampling.LANCZOS)
    x0 = (W - width) // 2
    body = (x0, top, x0 + width, top + shh + 28)
    shadow = Image.new("L", img.size, 0)
    ImageDraw.Draw(shadow).rounded_rectangle((body[0] + 6, body[1] + 14, body[2] + 6, body[3] + 18), radius=18, fill=70)
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    img.paste((0, 0, 0), (0, 0), Image.eval(shadow, lambda v: int(v * 0.35)))
    d = ImageDraw.Draw(img)
    cx = W // 2                                        # подставка
    nb = body[3]
    d.polygon([(cx - 46, nb), (cx + 46, nb), (cx + 34, nb + 70), (cx - 34, nb + 70)], fill=(232, 232, 234))
    d.rounded_rectangle((cx - 120, nb + 66, cx + 120, nb + 80), radius=7, fill=(222, 222, 225))
    d.rounded_rectangle(body, radius=18, fill=(250, 250, 251), outline=(214, 214, 218), width=2)
    img.paste(sh, (x0 + 14, top + 14))
    return body


def site_slide(site: dict, rng: random.Random, shot: Path) -> tuple[Image.Image, list]:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = SZ.text_rect(W, H)
    boxes = nav(img, 108)
    px = 210                                           # название — крупное узкое засечное
    f = font(F_SERIF, px)
    while f.getlength(site["title"]) > (x1 - x0) and px > 120:
        px -= 6
        f = font(F_SERIF, px)
    tb = d.textbbox((0, 0), site["title"], font=f)
    ty = 190
    tx = (W - (tb[2] - tb[0])) / 2 - tb[0]
    d.text((tx, ty - tb[1]), site["title"], font=f, fill=INK)
    boxes.append((int(tx + tb[0]), ty, int(tx + tb[2]), ty + tb[3] - tb[1]))
    fb = font(F_REG, 29)                               # описание
    lines = balanced_wrap(site["desc"], fb, 700)
    yy = ty + (tb[3] - tb[1]) + 46
    for l in lines:
        lw = fb.getlength(l)
        d.text(((W - lw) / 2, yy), l, font=fb, fill=INK)
        boxes.append((int((W - lw) / 2), yy, int((W + lw) / 2), yy + 34))
        yy += 41
    fu = font(F_SEMI, 25)                              # строка поиска
    uw = fu.getlength(site["url"])
    pw = int(min(x1 - x0, max(520, uw + 130)))
    py = yy + 34
    pxl = (W - pw) // 2
    d.rounded_rectangle((pxl, py, pxl + pw, py + 70), radius=35, outline=INK, width=3, fill=BG)
    d.text((pxl + 34, py + 20), site["url"], font=fu, fill=INK)
    magnifier(d, pxl + pw - 48, py + 33, 13, 4)
    boxes.append((pxl, py, pxl + pw, py + 70))
    mt = py + 70 + 54                                  # монитор со скрином
    body = monitor(img, shot, mt, rng.choice((740, 750, 760)))
    fl = font(F_MED, 21)

    def size(t):
        ls = t.split(chr(10))
        return int(max(fl.getlength(l) for l in ls) + 44), 22 + 27 * len(ls)
    bh = body[3] - body[1]
    for t, (side, fy) in zip(site["tags"], site["spots"]):
        w_, h_ = size(t)
        y = int(body[1] + bh * (fy + rng.uniform(-0.04, 0.04)) - h_ / 2)
        y = max(body[1] + 20, min(y, y1 - h_))
        x = x0 + rng.randint(0, 16) if side == "L" else x1 - w_ - rng.randint(0, 16)
        boxes.append(callout(img, t, x, y, side == "L"))
    return img, boxes


def sparkle(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    pts = []
    for k in range(8):
        a = math.radians(k * 45)
        rr = r if k % 2 == 0 else r * 0.28
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=fill)


def cover_slide(rng: random.Random) -> tuple[Image.Image, list]:
    img = Image.new("RGBA", (W, H), BG + (255,))
    x0, y0, x1, y1 = SZ.text_rect(W, H)
    px = 128
    while max(font(F_SERIF, px).getlength(l) for l in COVER) > (x1 - x0) - 10:
        px -= 2
    f = font(F_SERIF, px)
    step = int(px * 0.93)
    th = step * len(COVER)
    ty = rng.randint(650, 690) - th // 2               # текст по центру, между полосами предметов
    text_box = (x0, ty - 10, x1, ty + th + 70)
    d = ImageDraw.Draw(img)
    # предметы — по краям, мимо текста
    groups = {}                                        # по одному предмету каждого вида (не две гитары)
    for o in OBJECTS:
        groups.setdefault(o.rstrip("2").replace("_case", ""), []).append(o)
    objs = [rng.choice(groups[g]) for g in rng.sample(sorted(groups), 4)]
    slots = [(-40, -20, 500, 470), (580, -30, 1120, 460), (-60, 900, 500, 1470), (580, 890, 1130, 1470)]
    rng.shuffle(slots)
    COVER_SIG[:] = ["|".join(objs), "|".join(str(x[0]) + "," + str(x[1]) for x in slots[:4])]
    for name, (a, b, c, e) in zip(objs, slots):
        im = Image.open(D / "objects" / f"{name}.png").convert("RGBA")
        s = rng.uniform(0.82, 0.98) * min((c - a) / im.width, (e - b) / im.height)
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.Resampling.LANCZOS)
        im = im.rotate(rng.uniform(-10, 10), expand=True, resample=Image.Resampling.BICUBIC)
        px, py = int(a + (c - a - im.width) * rng.uniform(0.2, 0.8)), int(b + (e - b - im.height) * rng.uniform(0.2, 0.8))
        for _ in range(2):                             # звёздочки за предметом
            sparkle(d, px + im.width * rng.uniform(0.1, 0.9), py + im.height * rng.uniform(0.1, 0.9), rng.uniform(40, 80), SPARK + (255,))
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        sh.putalpha(im.getchannel("A").point(lambda v: int(v * 0.25)))
        sh = sh.filter(ImageFilter.GaussianBlur(10))
        img.alpha_composite(sh, (px + 8, py + 14))
        img.alpha_composite(im, (px, py))
    # мягкая подложка под текст, чтобы предмет у края не спорил с буквами
    veil = Image.new("L", (W, H), 0)
    ImageDraw.Draw(veil).rounded_rectangle((text_box[0] - 20, text_box[1] - 10, text_box[2] + 20, text_box[3] + 10), radius=60, fill=150)
    veil = veil.filter(ImageFilter.GaussianBlur(40))
    img.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", (W, H), BG).split(), veil)))
    d = ImageDraw.Draw(img)
    boxes = []
    for i, l in enumerate(COVER):
        lw = f.getlength(l)
        d.text(((W - lw) / 2, ty + i * step), l, font=f, fill=INK + (255,))
        boxes.append((int((W - lw) / 2), ty + i * step + 20, int((W + lw) / 2), ty + i * step + step))
    fp = font(F_MED, 26)
    pw = tracked_w(PART.upper(), fp, 3)
    tracked(d, ((W - pw) / 2, ty + th + 26), PART.upper(), fp, INK + (255,), 3)
    boxes.append((int((W - pw) / 2), ty + th + 26, int((W + pw) / 2), ty + th + 56))
    for k in range(3):
        sparkle(d, rng.choice((x0 + 10, x1 - 10)), ty + rng.randint(-60, th + 40), rng.uniform(16, 26), (190, 160, 236, 255))
    return img.convert("RGB"), boxes


def carousel(rng: random.Random, sig: list | None = None) -> tuple[list[Image.Image], list]:
    """sig (если передан) — сюда пишется набор выборов карусели: оттенок, предметы обложки, скрины."""
    global BG
    tone = rng.randrange(len(BG_TONES))
    BG = BG_TONES[tone]
    out, qa = [], []
    im, bx = cover_slide(rng)
    out.append(im)
    qa.append(bx)
    shots = []
    for s in SITES:
        sh = rng.choice(s["shots"])
        shots.append(sh)
        im, bx = site_slide(s, rng, D / "shots" / f"{sh}.png")
        out.append(im)
        qa.append(bx)
    if sig is not None:
        sig.extend([tone, *COVER_SIG, *shots])
    return out, qa


def check(qa: list) -> list[str]:
    errs = []
    for k, bxs in enumerate(qa, 1):
        for b in bxs:
            e = SZ.check_box(W, H, b)
            if e:
                errs.append(f"слайд {k}: {b} {e}")
    return errs


def video(slides: list[Image.Image], dest: Path, beats: list[float]) -> None:
    """9:16: слайд 3:4 по центру на том же кремовом фоне, смена на долях (обложка до 4-й доли, дальше через 4)."""
    tmp = Path(tempfile.mkdtemp(prefix="dri_"))
    sw, shh = 1080, 1440
    y0 = (VH - shh) // 2
    sv = D / "music" / "_start.json"                   # тюнер: tuner_drops_inspire.py (старт песни, смены, конец)
    if sv.exists():
        st = json.loads(sv.read_text(encoding="utf-8"))
        a0, times = st["start"], [0.0] + [t - st["start"] for t in st["cuts"]] + [st["end"] - st["start"]]
    else:
        a0, times = 0.0, [0.0, beats[4], beats[8], beats[12], beats[16]]
    lst = []
    for i, s in enumerate(slides):
        fr = Image.new("RGB", (VW, VH), BG)
        fr.paste(s, (0, y0))
        p = tmp / f"s{i}.png"
        fr.save(p)
        lst.append(f"file '{p.as_posix()}'\nduration {times[i + 1] - times[i]:.3f}\n")
    lst.append(f"file '{(tmp / f's{len(slides) - 1}.png').as_posix()}'\n")
    (tmp / "l.txt").write_text("".join(lst), encoding="utf-8")
    T = times[-1]
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "l.txt"),
                        "-i", str(D / "music" / "sound.mp3"), "-vf", "fps=30,format=yuv420p", "-af",
                        f"atrim={a0:.3f}:{a0 + T:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={T - 0.4:.3f}:d=0.4,loudnorm=I=-14:TP=-1.5",
                        "-t", f"{T:.3f}", "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "27", "-c:a", "aac", "-b:a", "192k",
                        *CLEAN, str(dest)],
                       capture_output=True, text=True)
    shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])


def beats() -> list[float]:
    cf = WORK / "beats.json"
    if cf.exists():
        return json.loads(cf.read_text())
    import librosa
    y, sr = librosa.load(str(D / "music" / "sound.mp3"), sr=22050)
    _, b = librosa.beat.beat_track(y=y, sr=sr)
    bt = [round(float(t), 3) for t in librosa.frames_to_time(b, sr=sr)]
    WORK.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps(bt))
    return bt


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--car", type=int, default=150)
    ap.add_argument("--vid", type=int, default=100)
    ap.add_argument("--seed", type=int, default=71116)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    bt = beats()
    if a.test:
        out = WORK / "test"
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        sheet = []
        for n in range(1, 4):
            sl, qa = carousel(rng)
            errs = check(qa)
            if errs:
                print("ВНЕ РАМКИ:", errs, flush=True)
            for k, im in enumerate(sl, 1):
                im.save(out / f"sort_{k}_{n}_{ID}.jpg", quality=92)
                sheet.append(SZ.draw_overlay(im.copy()) if n == 1 else im)
        sl, _ = carousel(rng)
        video(sl, out / f"{NAME}_yt_001_{ID}.mp4", bt)
        S = 360
        sh = Image.new("RGB", (S * 4, 480 * 3), "white")
        for i, im in enumerate(sheet):
            sh.paste(im.resize((S, 480)), ((i % 4) * S, (i // 4) * 480))
        sh.save(out / "_sheet.jpg", quality=88)
        print("ТЕСТ:", out, flush=True)
        return 0
    from concurrent.futures import ProcessPoolExecutor
    car_dir = ROOT / "output" / f"{NAME}_carousels_{a.car}"
    vid_dir = ROOT / "output" / f"{NAME}_YT_{a.vid}"
    jobs = [("car", n) for n in range(1, a.car + 1)] + [("vid", n) for n in range(1, a.vid + 1)]
    seen, done, t0 = set(), 0, __import__("time").time()
    man = []
    with ProcessPoolExecutor(8) as ex:
        todo = [(kind, n, 0) for kind, n in jobs]
        while todo:
            futs = [(ex.submit(make_one, kind, n, a.seed + 7919 * att, str(car_dir), str(vid_dir)), att) for kind, n, att in todo]
            todo = []
            for f, att in futs:
                kind, n, sig, errs = f.result()
                if errs or tuple(sig) in seen:              # текст вне рамки / такой же набор уже есть — другой вариант
                    print(f"  {kind} {n}: {'вне рамки ' + str(errs) if errs else 'повтор набора'} — пересобираю", flush=True)
                    todo.append((kind, n, att + 1))
                    continue
                seen.add(tuple(sig))
                man.append(dict(kind=kind, n=n, sig=sig))
                done += 1
                if done % 25 == 0 or done == len(jobs):
                    print(f"  {done}/{len(jobs)}, {__import__('time').time() - t0:.0f} с", flush=True)
    (WORK / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    combos = {tuple(m["sig"][3:]) for m in man}
    print(f"ГОТОВО: {a.car} каруселей → {car_dir}, {a.vid} видео → {vid_dir}; разных наборов скринов {len(combos)}, "
          f"все {len(seen)} наборов разные", flush=True)
    if a.car:
        subprocess.run([sys.executable, str(ROOT / "strip_jpeg_meta.py"), str(car_dir)])
    return 0


def make_one(kind: str, n: int, seed: int, car_dir: str, vid_dir: str):
    rng = random.Random(seed * 1000 + (n if kind == "car" else 5000 + n))
    sig: list = []
    sl, qa = carousel(rng, sig)
    errs = check(qa)
    if kind == "car":
        out = Path(car_dir)
        out.mkdir(parents=True, exist_ok=True)
        for k, im in enumerate(sl, 1):
            im.save(out / f"sort_{k}_{n}_{ID}.jpg", quality=93)
    else:
        video(sl, Path(vid_dir) / f"{NAME}_yt_{n:03d}_{ID}.mp4", beats())
    return kind, n, sig, errs


if __name__ == "__main__":
    raise SystemExit(main())
