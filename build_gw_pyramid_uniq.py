#!/usr/bin/env python3
"""
Global Work «пирамида» (ранкинг сайтов) — уникализация: по N непохожих роликов на креатора.
  G  — парень (build_gw_pyramid_reel.py, downloads/gw_pyramid/src/IMG_2907.MOV, звук без сдвига после CUT);
  P1 — девушка, жёлтые стикеры (build_gw_pyramid2_reels.py, песня с 4.37 с ролика — подобрано по губам);
  P2 — девушка, розовые стикеры (песня в самом ролике — сдвиг по звуку).
Ролик — лип-синк под песню, поэтому куски не переставляем: меняем оформление и кадр, синхрон сохраняется.
Каждый ролик — своё сочетание:
  зеркало (плитки встают на отражённые места стикеров — логотип там, где она снимает стикер; текст не отражён),
  кадр 1.00 / 1.06 / 1.12 (плитки едут вместе с доской), заголовок (4 стиля, 2 высоты, текст дословно),
  плитки (4 стиля), появление плиток (сразу / проявление / подъезд), цвет (5), скорость 0.98 / 1.00 / 1.02
  (видео и песня вместе — губы не уезжают), срез начала 0 / 0.3 / 0.6 с, лёгкое зерно.
Набор вариантов на креатора — жадно по максимуму различий. Заголовок — в безопасной зоне 9:16; нижний ряд
плиток, как и в исходных роликах, лежит там, где доска (в зоне подписи). Кодирование NVENC.

  python build_gw_pyramid_uniq.py --test          # по 2 варианта на креатора (оба зеркальные/нет) → _test
  python build_gw_pyramid_uniq.py -n 35 --jobs 4  # G, P1, P2 → output/gw_pyramid_uniq/{G,P1,P2} + manifest.csv
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import random
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_pyramid_reel as P  # noqa: E402  (плитки, подписи, заголовок, звук)
import build_gw_pyramid2_reels as P2  # noqa: E402
from core import renderer as R  # noqa: E402
from core.safe_zones import check_overlay  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF, W, H, FPS = P.FF, P.W, P.H, P.FPS
OUT = ROOT / "output" / "gw_pyramid_uniq"
CACHE = OUT / "_cache"
SONG = P2.dur_of(P.SOUND)
P1_START = 4.37                     # P1 без звука: начало песни подобрано по губам (output/gw_pyramid2/tuner_P1.html)

DIMS = {"mirror": [0, 1], "zoom": [1.0, 1.06, 1.12], "title": ["plates", "dark", "stroke", "shadow"],
        "tiles": ["ref", "ring", "pill", "shadow"], "grade": ["none", "warm", "cool", "punchy", "soft"],
        "speed": [0.98, 1.0, 1.02], "anim": ["cut", "fade", "slide"], "trim": [0.0, 0.3, 0.6]}
WEIGHT = {"mirror": 1.5, "zoom": 1.0, "title": 1.5, "tiles": 1.5, "grade": 1.0, "speed": 1.0, "anim": 0.5, "trim": 0.5}
GRADES = {"none": "", "warm": "colorbalance=rs=0.04:bs=-0.04:rm=0.03:bm=-0.03",
          "cool": "colorbalance=rs=-0.03:bs=0.04:rm=-0.02:bm=0.03", "punchy": "eq=contrast=1.07:saturation=1.12",
          "soft": "eq=contrast=0.94:saturation=0.94:brightness=0.015"}
ZOOM_Y = 0.5        # наезд по центру: лицо уходит вверх ровно настолько, чтобы нижний ряд остался в кадре
ANIM_D = 0.2


# ---------------- исходники: основа, места стикеров, моменты снятия ----------------
def creator(tag: str) -> dict:
    """Центры стикеров (1080×1920), размер плитки, ширина подписи, сайт по стикеру, момент снятия в секундах
    основы (основа = кусок ролика ровно под песню, t=0 — начало песни)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"creator_{tag}.json"
    if p.exists():
        return json.loads(p.read_text())
    if tag == "G":
        sm = np.load(P.SIM)
        gone = json.loads(P.SIM.with_suffix(".json").read_text(encoding="utf-8"))["gone"]
        med = np.median(sm, axis=0)
        scale = float(np.sqrt(abs(np.linalg.det(med[:, :2]))))
        sizes = [min(x1 - x0, y1 - y0) for x0, y0, x1, y1 in P.SLOTS[1:]]
        cen = [((np.float32([(x0 + x1) / 2, (y0 + y1) / 2]) @ med[:, :2].T + med[:, 2]) * 2).tolist()
               for x0, y0, x1, y1 in P.SLOTS]
        brand = [list(P.BRANDS[j]) for j in range(6)]
        start, pop = P.CUT[0], [g - 0.15 - P.CUT[0] for g in gone]
        src, tm = P.SRC, True
    else:
        cfg = P2.CLIPS[tag]
        src, tm, scale = P2.SRC / cfg["file"], False, 1.0
        c = json.loads((P2.SRC / f"{tag}_track.json").read_text())
        slots, gone = [tuple(s) for s in c["slots"]], c["gone"]
        sizes = [min(x1 - x0, y1 - y0) for x0, y0, x1, y1 in slots[1:]]
        cen = [[v * 2 for v in q] for q in c["cen"]]
        for row in ([0], [1, 2], [3, 4, 5]):             # ровные ряды, как в build_gw_pyramid2_reels
            y = float(np.mean([cen[j][1] for j in row]))
            for j in row:
                cen[j][1] = y
        order = sorted(range(6), key=lambda j: gone[j])
        brand = [None] * 6
        for k, j in enumerate(order):
            brand[j] = list(P2.ORDER[k])
        start = P1_START if tag == "P1" else P2.song_start(src)
        pop = [g - start for g in gone]
    pitch_v = min(abs(cen[1][1] - cen[0][1]), abs(cen[3][1] - cen[1][1]))
    pitch_h = min(abs(cen[2][0] - cen[1][0]), abs(cen[4][0] - cen[3][0]), abs(cen[5][0] - cen[4][0]))
    side = int(min(np.median(sizes) * 2 * scale * 0.82, (pitch_v - 14) / 1.17, pitch_h - 20))
    d = {"src": str(src), "tm": tm, "start": round(float(start), 3), "cen": cen, "side": side,
         "lab_w": int(pitch_h - 12), "brand": brand, "pop": [round(float(x), 3) for x in pop]}
    p.write_text(json.dumps(d, ensure_ascii=False))
    return d


def base(tag: str, c: dict) -> Path:
    """Кусок ролика ровно под песню, 1080×1920, 30 к/с, SDR, без звука (кэш)."""
    dest = CACHE / f"base_{tag}.mp4"
    if dest.exists():
        return dest
    vf = (P.TM.format(w=W, h=H) if c["tm"] else f"scale={W}:{H}:flags=lanczos,fps={FPS}") + \
        f",trim=start={c['start']:.3f}:duration={SONG:.3f},setpts=PTS-STARTPTS,setsar=1"
    subprocess.run([FF, "-v", "error", "-y", "-i", c["src"], "-vf", vf, "-an", "-c:v", "h264_nvenc", "-preset", "p5",
                    "-rc", "vbr", "-cq", "14", "-b:v", "0", "-pix_fmt", "yuv420p", str(dest)], check=True)
    return dest


def eyes(tag: str, b: Path) -> dict:
    """Самое высокое положение глаз за ролик (верх век, px из 1920) — чтобы при наезде заголовок не лёг на глаза."""
    p = CACHE / f"eyes_{tag}.json"
    if p.exists():
        return json.loads(p.read_text())
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    opt = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "face_landmarker.task")),
                                       running_mode=vision.RunningMode.VIDEO, num_faces=1)
    fl = vision.FaceLandmarker.create_from_options(opt)
    ys = []
    for k, bgr in enumerate(P2.frames(b, 540, 960)):
        if k % 6:
            continue
        r = fl.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)),
                                int(k * 1000 / FPS))
        if r.face_landmarks:
            ys.append(min(r.face_landmarks[0][i].y for i in (159, 386, 33, 263)) * H)
    fl.close()
    d = {"eyes_top": float(np.percentile(ys, 2))}
    p.write_text(json.dumps(d))
    return d


# ---------------- графика ----------------
def label_img(text: str, max_w: int, px: int, style: str) -> Image.Image:
    if style in ("ref", "ring"):                          # как в рефе: белый TikTok-шрифт с чёрной обводкой
        return P.label(text, max_w, px)
    font = R._load_font(px)
    while font.getlength(text) > max_w - (36 if style == "pill" else 0) and px > 14:
        px -= 1
        font = R._load_font(px)
    tw = int(font.getlength(text))
    if style == "pill":                                   # чёрный текст на белой «таблетке»
        ph = int(px * 1.45)
        im = Image.new("RGBA", (tw + 36, ph), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, im.width - 1, ph - 1], radius=ph // 2, fill=(255, 255, 255, 245))
        d.text((im.width / 2, ph / 2), text, font=font, fill=(17, 17, 17, 255), anchor="mm")
        return im
    im = Image.new("RGBA", (tw + 20, int(px * 1.6)), (0, 0, 0, 0))   # белый с мягкой тенью
    ImageDraw.Draw(im).text((im.width / 2, im.height / 2), text, font=font, fill=(255, 255, 255, 255), anchor="mm")
    im = add_shadow(im.crop(im.getbbox()), blur=4, opacity=0.8, offset=(0, 2), grow=2)
    return im.crop(im.getbbox())


def tile_img(key: str, side: int, style: str) -> Image.Image:
    t = P.tile(key, side)
    if style == "ring":                                   # белая рамка
        ring = 6
        out = Image.new("RGBA", (side + 2 * ring, side + 2 * ring), (0, 0, 0, 0))
        ImageDraw.Draw(out).rounded_rectangle([0, 0, out.width - 1, out.height - 1], radius=int(side * 0.2) + ring,
                                              fill=(255, 255, 255, 255))
        out.alpha_composite(t, (ring, ring))
        t = out
    if style in ("ring", "shadow"):
        t = add_shadow(t, blur=7, opacity=0.55, offset=(0, 5), grow=1)
    return t


def tile_canvas(c: dict, j: int, style: str, mirror: bool) -> Image.Image:
    """Плитка j + подпись на прозрачном кадре. В зеркальном ролике — на отражённом месте стикера
    (сам логотип и подпись не отражаем)."""
    key, text = c["brand"][j]
    side = c["side"]
    lab = label_img(text, c["lab_w"], max(16, int(side * 0.24)), style)
    t = tile_img(key, side, style)
    cx, cy = c["cen"][j]
    if mirror:
        cx = W - cx
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    top = int(cy - (side + lab.height * 0.55) / 2)
    canvas.alpha_composite(t, (int(cx - t.width / 2), int(top + side / 2 - t.height / 2)))
    gap = 0.45 if style in ("ref", "ring") else 0.2       # обводка рефа заходит на плитку, остальные — под ней
    canvas.alpha_composite(lab, (int(cx - lab.width / 2), int(top + side - lab.height * gap)))
    return canvas


def title_canvas(style: str, top: int) -> Image.Image:
    lines, px = P.TITLE, P.TITLE_PX
    if style in ("plates", "dark"):
        tmp = CACHE / "_title_plates.png"
        P.TITLE_TOP = top
        P.title_png(tmp)
        im = Image.open(tmp).convert("RGBA")
        if style == "dark":                               # инверсия: белый текст на чёрных плашках
            a = np.asarray(im).copy()
            rgb = 255 - a[..., :3]
            a[..., :3] = rgb
            im = Image.fromarray(a)
        return im
    font = R._load_font(px)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    y = top
    for ln in lines:
        if style == "stroke":
            im = P.label(ln, 900, px)
        else:
            im = Image.new("RGBA", (int(font.getlength(ln)) + 20, int(px * 1.5)), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((im.width / 2, im.height / 2), ln, font=font, fill=(255, 255, 255, 255), anchor="mm")
            im = add_shadow(im.crop(im.getbbox()), blur=6, opacity=0.8, offset=(0, 3), grow=3)
            im = im.crop(im.getbbox())
        canvas.alpha_composite(im, ((W - im.width) // 2, y))
        y += int(px * 1.22)
    return canvas


# ---------------- выбор вариантов ----------------
def pick_specs(n: int, rng: random.Random) -> list[dict]:
    keys = list(DIMS)
    combos = [dict(zip(keys, v)) for v in itertools.product(*(DIMS[k] for k in keys))]
    orig = {"mirror": 0, "zoom": 1.0, "title": "plates", "tiles": "ref", "grade": "none", "speed": 1.0}
    combos = [c for c in combos if sum(c[k] != v for k, v in orig.items()) >= 2]
    rng.shuffle(combos)
    use = {k: {v: 0 for v in DIMS[k]} for k in keys}

    def dist(x, y):
        return sum(WEIGHT[k] for k in keys if x[k] != y[k])

    picked = [combos[0]]
    for k in keys:
        use[k][combos[0][k]] += 1
    while len(picked) < n:
        best = max(combos, key=lambda c: (min(dist(c, p) for p in picked),
                                          -sum(use[k][c[k]] for k in keys), rng.random()))
        picked.append(best)
        for k in keys:
            use[k][best[k]] += 1
    out = []
    for c in picked:
        c = dict(c)
        c["grain"] = int(rng.random() < 0.4)
        c["title_y"] = rng.choice([215, 250])
        out.append(c)
    return out


# ---------------- рендер одного ролика ----------------
def frame_for(z0: float, tiles_box: tuple, title_bottom: int, eyes_top: float) -> tuple[float, int, int]:
    """Кадр наезда: все плитки целиком в кадре (с запасом), глаза ниже заголовка; иначе наезд меньше.
    Окно сдвигаем от центра ровно настолько, насколько нужно."""
    bx0, by0, bx1, by1 = tiles_box
    m = 12
    z = z0
    while z > 1.0 + 1e-6:
        cw, ch = int(W / z / 2) * 2, int(H / z / 2) * 2
        xlo, xhi = max(0, bx1 + m - cw), min(W - cw, bx0 - m)
        ylo = max(0, by1 + m - ch)
        yhi = min(H - ch, by0 - m, int(eyes_top - (title_bottom + 20) * ch / H))
        if xlo <= xhi and ylo <= yhi:
            ox = int(min(max((W - cw) // 2, xlo), xhi)) // 2 * 2
            oy = int(min(max(int((H - ch) * ZOOM_Y), ylo), yhi)) // 2 * 2
            return round(z, 3), ox, oy
        z -= 0.01
    return 1.0, 0, 0


def prepare(tag: str, spec: dict, dest: Path) -> dict:
    c = creator(tag)
    b = base(tag, c)
    work = CACHE / "png" / dest.stem
    work.mkdir(parents=True, exist_ok=True)
    tiles, boxes = [], []
    for j in range(6):
        im = tile_canvas(c, j, spec["tiles"], bool(spec["mirror"]))
        boxes.append(im.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox())
        im.save(work / f"tile{j}.png")
        tiles.append(str(work / f"tile{j}.png"))
    box = (min(q[0] for q in boxes), min(q[1] for q in boxes), max(q[2] for q in boxes), max(q[3] for q in boxes))
    if box[0] < 0 or box[2] > W or box[3] > H:
        raise SystemExit(f"{dest.name}: плитки выходят за кадр {box}")
    ti = title_canvas(spec["title"], spec["title_y"])
    bad = check_overlay(ti)
    if bad:
        raise SystemExit(f"{dest.name}: заголовок вне безопасной зоны: {bad}")
    ti.save(work / "title.png")
    tb = ti.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox()[3]
    z, ox, oy = frame_for(spec["zoom"], box, tb, eyes(tag, b)["eyes_top"])
    return {"tag": tag, "spec": spec, "dest": str(dest), "base": str(b), "tiles": tiles,
            "title": str(work / "title.png"), "pop": c["pop"], "z": z, "ox": ox, "oy": oy}


def render(job: dict) -> str:
    spec, dest = job["spec"], Path(job["dest"])
    z, sp, s0 = job["z"], spec["speed"], spec["trim"]
    inputs = ["-i", job["base"]]
    for t in job["tiles"]:
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{SONG:.3f}", "-i", t]
    inputs += ["-i", job["title"], "-i", str(P.SOUND)]
    pre = [x for x in ("hflip" if spec["mirror"] else "", "noise=alls=4:allf=t+u" if spec["grain"] else "",
                       GRADES[spec["grade"]]) if x]           # зерно до цветокора (иначе синие колонки по краю)
    ch = [f"[0:v]{','.join(pre + ['format=yuv420p'])}[v0]"]
    for j in range(6):
        t0 = max(0.0, job["pop"][j])
        k = j + 1
        if spec["anim"] == "fade":
            ch.append(f"[{k}:v]format=rgba,fade=t=in:st={t0:.3f}:d={ANIM_D}:alpha=1[t{j}]")
            ch.append(f"[v{j}][t{j}]overlay=0:0:enable='gte(t,{t0:.3f})'[v{k}]")
        elif spec["anim"] == "slide":
            ch.append(f"[v{j}][{k}:v]overlay=x=0:y='max(0,({t0 + ANIM_D:.3f}-t)/{ANIM_D}*45)':"
                      f"enable='gte(t,{t0:.3f})'[v{k}]")
        else:
            ch.append(f"[v{j}][{k}:v]overlay=0:0:enable='gte(t,{t0:.3f})'[v{k}]")
    cw, chh = int(W / z / 2) * 2, int(H / z / 2) * 2
    zf = "" if z == 1.0 else f",crop={cw}:{chh}:{job['ox']}:{job['oy']},scale={W}:{H}:flags=bicubic"
    ch.append(f"[v6]null{zf}[vz]")
    ch.append(f"[vz][7:v]overlay=0:0,trim=start={s0}:duration={SONG - s0:.3f},setpts=(PTS-STARTPTS)/{sp},fps={FPS},"
              f"format=yuv420p,{SET_SDR}[v]")
    ch.append(f"[8:a]atrim=start={s0}:duration={SONG - s0:.3f},asetpts=PTS-STARTPTS,atempo={sp},{job['afilter']}[a]")
    r = subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(ch), "-map", "[v]", "-map", "[a]",
                        "-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "27", "-b:v", "0",
                        "-maxrate", "6M", "-bufsize", "12M", "-profile:v", "high", *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k", "-shortest",
                        "-movflags", "+faststart", str(dest)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{dest.name}: {r.stderr[-800:]}")
    return str(dest)


def sheet(paths: list[Path], at: list[float], dest: Path) -> None:
    """Контакт-лист: строка на ролик, кадры в моменты at (с) — проверка, что плитка там, где снят стикер."""
    rows = []
    for p in paths:
        cells = []
        for t in at:
            b = subprocess.run([FF, "-v", "error", "-ss", f"{t:.2f}", "-i", str(p), "-frames:v", "1", "-vf", "scale=240:426",
                                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
            cells.append(Image.frombuffer("RGB", (240, 426), b) if len(b) == 240 * 426 * 3 else Image.new("RGB", (240, 426)))
        row = Image.new("RGB", (240 * len(cells), 426 + 22), "white")
        for i, im in enumerate(cells):
            row.paste(im, (240 * i, 22))
        ImageDraw.Draw(row).text((6, 4), p.name, fill=(0, 0, 0))
        rows.append(row)
    out = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)), "white")
    y = 0
    for r in rows:
        out.paste(r, (0, y))
        y += r.height
    out.save(dest, quality=88)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=35)
    ap.add_argument("--tags", nargs="+", default=["G", "P1", "P2"])
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    afilter = P.audio_filter()
    jobs, rows = [], []
    for tag in a.tags:
        c = creator(tag)
        print(f"{tag}: начало песни {c['start']} с, плитка {c['side']} px, снятия (с основы) {c['pop']}", flush=True)
        specs = pick_specs(a.n, random.Random(f"{a.seed}-{tag}"))
        if a.test:
            specs = [next(s for s in specs if s["mirror"] == m) for m in (1, 0)]
        out_dir = OUT / ("_test" if a.test else tag)
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, spec in enumerate(specs, 1):
            job = prepare(tag, spec, out_dir / f"pyr_{tag}_{i:02d}.mp4")
            job["afilter"] = afilter
            jobs.append(job)
            rows.append({"file": Path(job["dest"]).name, "creator": tag, **spec, "zoom_used": job["z"]})
    print(f"к рендеру: {len(jobs)}", flush=True)
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(render, j) for j in jobs]
        for k, fu in enumerate(as_completed(futs), 1):
            print(f"  {k}/{len(futs)} {Path(fu.result()).name}", flush=True)
    root = OUT / "_test" if a.test else OUT
    with (root / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter=";")
        w.writeheader()
        w.writerows(rows)
    if a.test:
        sheet([Path(j["dest"]) for j in jobs], [3.0, 11.5, 20.5, 27.0], root / "_sheet.jpg")
    print(f"готово: {len(jobs)} → {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
