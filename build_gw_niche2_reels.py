#!/usr/bin/env python3
"""
Global Work «где искать удалёнку», вторая партия (айди нет): как gw_niche (build_gw_niche_reel.py), но новые
материалы — downloads/gw_niche2/src (A — белая футболка 16.5 с, B — чёрная майка 24 с, 4K), по ролику на дубль.

  1) монтаж: паузы > GAP вырезаем (отрезки речи по уровню над шумом), на склейках чередуем наезд 100 % / 108 %;
  2) на смонтированном видео ищем лицо (MediaPipe Face) и указательный палец (MediaPipe Hand) по кадрам;
  3) поверх — тезисы (белый TikTok Sans SemiBold 60 px, без обводки/тени, на груди под лицом) и названия сайтов
     у кончика пальца на каждом «this one» (64 px): globalwork.ai → careerhound.io → builtin.com по кругу;
  4) звук −14 LUFS двухпроходно, срез гула < 80 Гц. Всё внутри безопасной зоны 9:16 (docs/SAFE_ZONES.md).

  python build_gw_niche2_reels.py          # все клипы
  python build_gw_niche2_reels.py C        # только клип C
  python build_gw_niche2_reels.py --clean  # ролики без подписей сайтов → output/gw_niche2/tuner (tuner.html)
  python build_gw_niche2_reels.py --layout output/gw_niche2/tuner/layout.json   # раскладка из tuner.html
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import check_overlay, text_rect  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
SRC = ROOT / "downloads" / "gw_niche2" / "src"
OUT = ROOT / "output" / "gw_niche2"
CLIPS = ["A_891EA56C", "B_DE1131C3", "C_IMG_8092"]
# iPhone HLG (bt2020) → SDR bt709 тонмаппингом (как в gw_niche; простая перемаркировка даёт бледную картинку)
TONEMAP = ("libplacebo=w=1080:h=1920:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:"
           "tonemapping=auto:format=yuv420p")
# тезисы под речь клипа: (текст, слово, с которого он начинается); по умолчанию — как в A/B
CAPS = {
    "C_IMG_8092": [("Quickest way to find\na remote job", None), ("LinkedIn & Indeed", "most"),
                   ("Very oversaturated", "problem"), ("Niche websites ->", "what")],
}


def src_of(clip: str) -> Path:
    return next(p for p in sorted(SRC.glob(f"{clip}.*")) if p.suffix.lower() in (".mp4", ".mov"))


def is_hlg(path: Path) -> bool:
    out = subprocess.run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_transfer",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    return "arib-std-b67" in out or "smpte2084" in out
ID = "noid"
W, H, FPS = 1080, 1920, 30
FONT = ROOT / "fonts" / "TikTokSans-SemiBold.ttf"
PX_CAP, PX_SITE, LINE = 60, 64, 1.18
SITES = ["globalwork.ai", "careerhound.io", "builtin.com"]
GAP, PRE, POST = 0.3, 0.06, 0.12
# ручные места подписей сайтов (центр, px 1080×1920) по жестам — № «this one» с 0; остальные — от кончика пальца.
# Палец вверх у лица → над головой со стороны пальца; руки внизу → на груди.
MANUAL: dict = {}
# Жесты на «this one», расписанные по кадрам смонтированного ролика (шаг 0.1 с): (начало жеста, центр x, центр y,
# кегль, что за жест). Подпись появляется вместе с жестом и стоит у кончика того пальца, который показывает;
# глаза/нос/рот не закрываем. Автопоиск руки путал руки (две руки в кадре, палец у края) — здесь вручную.
GESTURES = {
    "A_891EA56C": [                       # раскладка клиента (tuner.html)
        (11.75, 743, 1388, 64, "ладонь на груди"),
        (12.30, 361, 1120, 64, "правая рука, палец вверх-влево"),
        (12.95, 569, 358, 64, "оба указательных вверх — над головой"),
    ],
    "B_DE1131C3": [
        (13.60, 762, 640, 58, "правый указательный вверх у щеки (≈ 950, 880) — над ним, выше брови"),
        (14.60, 361, 538, 64, "левый указательный высоко вверх (≈ 70, 630) — над кончиком"),
        (15.85, 773, 400, 64, "правый указательный высоко вверх (≈ 970, 430) — над кончиком"),
        (16.50, 736, 1240, 64, "правый указательный вверх у самого края (≈ 1050, 1150) — рядом слева, на уровне кончика"),
        (17.60, 361, 680, 64, "левый указательный вверх (≈ 100, 970) — над ним, выше брови"),
        (19.15, 413, 300, 64, "левая рука поднята в верхний левый угол — справа от руки"),
    ],
    # C: одной рукой показывает на поднятую ладонь другой — подпись над кончиками пальцев поднятой ладони
    "C_IMG_8092": [
        (16.70, 762, 770, 58, "левая ладонь поднята справа (пальцы ≈ y 850), правая показывает на неё — над пальцами"),
        (17.50, 290, 790, 48, "правая ладонь поднята слева (пальцы ≈ y 830), левая показывает на неё — над пальцами; "
                              "справа лицо, поэтому кегль 48"),
        (18.10, 540, 1255, 64, "верхняя рука вытянута пальцами влево (≈ y 1325) — над ней, по центру кадра (просьба клиента)"),
    ],
}
# где трекер руки ошибается — кончик и направление пальца по кадрам вручную: {клип: {№ «this one»: (tip, dir)}}
TIP = {
    "A_891EA56C": {0: ((700, 1450), (0.9, -0.4), (380, 1380, 760, 1700)),   # ладонь на груди, пальцы вправо
                   2: ((80, 765), (0.0, -1.0))},      # левый указательный вверх у самого края кадра
    "B_DE1131C3": {5: ((90, 300), (0.0, -1.0))},      # левая рука поднята в верхний левый угол
}
ZOOM = 1.08
LOUD = "highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11"
X0, Y0, X1, Y1 = text_rect(W, H)


# ---------------- монтаж ----------------
def speech(path: Path) -> list[tuple[float, float]]:
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-af",
                          "highpass=f=200,lowpass=f=4000", "-f", "f32le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.float32)
    hop = 160
    e = np.array([np.sqrt(np.mean(a[i:i + hop] ** 2)) + 1e-7 for i in range(0, len(a) - hop, hop)])
    db = 20 * np.log10(np.convolve(e, np.ones(5) / 5, mode="same"))
    floor = float(np.percentile(db, 10))
    out, on, st = [], False, 0
    for i, v in enumerate(db):
        if not on and v > floor + 18:
            on, st = True, i
        elif on and v < floor + 12:
            on = False
            if i - st >= 8:
                out.append((st / 100, i / 100))
    if on:
        out.append((st / 100, len(db) / 100))
    return out


def segments(path: Path, dur: float) -> list[tuple[float, float]]:
    segs: list[list[float]] = []
    for a, b in speech(path):
        a, b = max(0.0, a - PRE), min(dur, b + POST)
        if segs and a - segs[-1][1] < GAP:
            segs[-1][1] = b
        else:
            segs.append([a, b])
    return [(round(a * FPS) / FPS, round(b * FPS) / FPS) for a, b in segs if b - a >= 0.25]


def to_cut(t: float, segs: list[tuple[float, float]]) -> float | None:
    """Время исходника → время смонтированного ролика (None — вырезано)."""
    acc = 0.0
    for a, b in segs:
        if a <= t <= b:
            return acc + t - a
        if t < a:
            return acc                                   # в вырезанной паузе — к началу следующего куска
        acc += b - a
    return acc


def montage(src: Path, segs: list[tuple[float, float]], dest: Path, zflags: list[bool] | None = None) -> None:
    k = len(segs)
    zflags = zflags or [i % 2 == 1 for i in range(k)]
    zw, zh = round(W * ZOOM / 2) * 2, round(H * ZOOM / 2) * 2
    sc = (f"{TONEMAP},fps={FPS},setsar=1" if is_hlg(src) else f"scale={W}:{H}:flags=lanczos,fps={FPS},setsar=1")
    vf = [f"[0:v]{sc},split={k}" + "".join(f"[s{i}]" for i in range(k))]
    af = [f"[0:a:0]asplit={k}" + "".join(f"[t{i}]" for i in range(k))]
    for i, (a, b) in enumerate(segs):
        z = f",scale={zw}:{zh},crop={W}:{H}:{(zw - W) // 2}:{int((zh - H) * 0.35)}" if zflags[i] else ""
        vf.append(f"[s{i}]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS{z},setsar=1[v{i}]")
        af.append(f"[t{i}]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.01,"
                  f"afade=t=out:st={max(0, b - a - 0.012):.3f}:d=0.012[a{i}]")
    fc = ";".join(vf + af) + ";" + "".join(f"[v{i}][a{i}]" for i in range(k)) + f"concat=n={k}:v=1:a=1[v][a]"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-c:a", "pcm_s16le", str(dest)], check=True)


# ---------------- лицо и палец ----------------
def track(video: Path) -> list[dict]:
    """По кадрам (15 к/с): рамка лица и указательный палец (кончик, направление) каждой руки, px 1080×1920."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    w, h = 540, 960
    fo = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "face_landmarker.task")),
                                      running_mode=vision.RunningMode.VIDEO, num_faces=1)
    ho = vision.HandLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "hand_landmarker.task")),
                                      running_mode=vision.RunningMode.VIDEO, num_hands=2,
                                      min_hand_detection_confidence=0.3)
    fl, hl = vision.FaceLandmarker.create_from_options(fo), vision.HandLandmarker.create_from_options(ho)
    p = subprocess.Popen([FF, "-v", "error", "-i", str(video), "-vf", f"scale={w}:{h},fps=30", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    rows, k = [], 0
    while True:
        buf = p.stdout.read(w * h * 3)
        if len(buf) < w * h * 3:
            break
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy())
        ts = int(k * 1000 / 30)
        fr = fl.detect_for_video(img, ts)
        hr = hl.detect_for_video(img, ts)
        face = None
        if fr.face_landmarks:
            xs = [q.x * W for q in fr.face_landmarks[0]]
            ys = [q.y * H for q in fr.face_landmarks[0]]
            hh = max(ys) - min(ys)
            face = [min(xs), min(ys) - 0.35 * hh, max(xs), max(ys)]          # с волосами
            L0 = fr.face_landmarks[0]
            brow = min(L0[i].y for i in (70, 63, 105, 66, 107, 336, 296, 334, 293, 300)) * H
            ex = sorted([L0[33].x * W, L0[263].x * W])
            feat = [ex[0] - 15, brow - 15, ex[1] + 15, L0[152].y * H]
        else:
            feat = None
        hands = []
        for L in hr.hand_landmarks:
            P = np.array([[q.x * W, q.y * H] for q in L])
            size = float(np.linalg.norm(P[9] - P[0])) + 1e-6
            ext = float(np.linalg.norm(P[8] - P[5])) / size                      # указательный вытянут
            oth = float(np.mean([np.linalg.norm(P[i] - P[0]) for i in (12, 16, 20)])) / size   # остальные согнуты
            d = P[8] - P[6]
            hands.append({"tip": P[8].tolist(), "dir": (d / (np.linalg.norm(d) + 1e-6)).tolist(), "ext": ext,
                          "oth": oth, "point": ext > 0.75 and oth < 1.35, "box": [*P.min(0).tolist(), *P.max(0).tolist()]})
        rows.append({"t": k / 30, "face": face, "feat": feat, "hands": hands})
        k += 1
    fl.close()
    hl.close()
    return rows


# ---------------- текст ----------------
def text_img(text: str, px: int) -> Image.Image:
    font = ImageFont.truetype(str(FONT), px)
    lines = text.split("\n")
    wd = int(max(font.getlength(t) for t in lines)) + 8
    step = px * LINE
    ht = int(step * len(lines)) + 8
    im = Image.new("RGBA", (wd, ht), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, t in enumerate(lines):
        d.text((wd / 2, (i + 0.5) * step + 4), t, font=font, fill=(255, 255, 255, 255), anchor="mm")
    return add_shadow(im)                    # мягкая тень: белый текст не сливается со светлым фоном


def full_frame(im: Image.Image, cx: float, cy: float) -> tuple[Image.Image, list[int]]:
    x = int(min(max(cx - im.width / 2, X0), X1 - im.width))
    y = int(min(max(cy - im.height / 2, Y0), Y1 - im.height))
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(im, (x, y))
    bad = check_overlay(canvas)
    if bad:
        raise SystemExit(f"текст вне безопасной зоны: {bad}")
    return canvas, [x, y, x + im.width, y + im.height]


def overlap(a: list[float], b: list[float]) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy


def site_spot(rows: list[dict], t0: float, t1: float, name: str, manual_tip=None) -> tuple[Image.Image, float, float, dict]:
    """Подпись сайта у кончика указывающего пальца: жест — рука с вытянутым указательным и согнутыми остальными
    (самая долгая в окне слова); место — вплотную к кончику по направлению пальца, внутри безопасной зоны, не на
    чертах лица и не на самой руке; если рядом не помещается — кегль меньше (64 → 48)."""
    win = [r for r in rows if t0 - 0.1 <= r["t"] <= t1 + 0.1]
    pts = [(r["t"], h) for r in win for h in r["hands"] if h["point"]]
    if manual_tip:                                               # кончик задан вручную
        hb = manual_tip[2] if len(manual_tip) > 2 else (manual_tip[0][0] - 1, manual_tip[0][1] - 1,
                                                          manual_tip[0][0] + 1, manual_tip[0][1] + 1)
        pts = [(t0, {"tip": list(manual_tip[0]), "dir": list(manual_tip[1]), "box": list(hb)})]
    if not pts:                                                  # нет явного жеста — самая вытянутая рука
        pts = [(r["t"], max(r["hands"], key=lambda h: h["ext"])) for r in win if r["hands"]]
    feats = [r["feat"] for r in win if r["feat"]]
    feat = np.median(np.array(feats), axis=0).tolist() if feats else None
    if not pts:
        im = text_img(name, PX_SITE)
        return im, W / 2, 1385, {"tip": None}
    # группируем по положению кончика, берём самую длинную группу
    groups: list[list] = []
    for t, h in pts:
        for g in groups:
            if np.hypot(*(np.array(h["tip"]) - np.array(g[-1][1]["tip"]))) < 160:
                g.append((t, h))
                break
        else:
            groups.append([(t, h)])
    g = max(groups, key=len)
    tip = np.median(np.array([h["tip"] for _t, h in g]), axis=0)
    d = np.median(np.array([h["dir"] for _t, h in g]), axis=0)
    d = d / (np.linalg.norm(d) + 1e-6)
    hand = np.median(np.array([h["box"] for _t, h in g]), axis=0).tolist()
    best = None
    for px in (64, 58, 52, 48):
        im = text_img(name, px)
        hw, hh = im.width / 2, im.height / 2
        for cy in range(int(Y0 + hh), int(Y1 - hh) + 1, 10):
            for cx in range(int(X0 + hw), int(X1 - hw) + 1, 10):
                box = [cx - hw, cy - hh, cx + hw, cy + hh]
                if feat and overlap(box, feat) > 0.04 * im.width * im.height:
                    continue                                     # черты лица — допускаем только касание краем
                if overlap(box, [hand[0], hand[1] + 0.25 * (hand[3] - hand[1]), hand[2], hand[3]]) > 0.15 * im.width * im.height:
                    continue                                     # не на ладони (кончик пальца можно задеть краем)
                if box[0] - 12 <= tip[0] <= box[2] + 12 and box[1] - 12 <= tip[1] <= box[3] + 12:
                    continue                                     # сам кончик пальца не закрываем
                nx, ny = min(max(tip[0], box[0]), box[2]), min(max(tip[1], box[1]), box[3])
                gap = float(np.hypot(nx - tip[0], ny - tip[1]))  # от кончика до ближайшей точки подписи
                v = np.array([cx, cy]) - tip
                cosang = float(v @ d / (np.linalg.norm(v) + 1e-6))
                score = gap + (1 - cosang) * 120 + (64 - px) * 6 + (30 if gap < 15 else 0)
                if best is None or score < best[0]:
                    best = (score, px, cx, cy)
    if best is None:
        im = text_img(name, PX_SITE)
        return im, W / 2, 1385, {"tip": tip.round().tolist()}
    _s, px, cx, cy = best
    return text_img(name, px), cx, cy, {"tip": tip.round().tolist(), "dir": d.round(2).tolist(), "px": px,
                                        "gesture": [round(g[0][0], 2), round(g[-1][0], 2)]}


def captions(words: list, segs: list, clip: str = "") -> tuple[list[tuple[str, float, float]], list[tuple[float, float]]]:
    """Тезисы как в gw_niche + моменты «this one» (время смонтированного ролика)."""
    ws = [(re.sub(r"[^a-z']", "", w.lower()), to_cut(a, segs), to_cut(b if b else a + 0.3, segs)) for w, a, b in words]
    idx = lambda word, start=0: next(i for i in range(start, len(ws)) if ws[i][0].startswith(word))  # noqa: E731
    if clip in CAPS:
        starts, k = [], 0
        for text, word in CAPS[clip]:
            if word is None:
                starts.append((text, 0.0))
            else:
                k = idx(word, k)
                starts.append((text, ws[k][1]))
        i_like = idx("like", k)
        caps = [(t, a, starts[j + 1][1] if j + 1 < len(starts) else ws[i_like][1]) for j, (t, a) in enumerate(starts)]
        ones = [i for i in range(i_like, len(ws)) if ws[i][0] == "this"]
        total = sum(b - a for a, b in segs)
        return caps, [(ws[i][1], ws[ones[j + 1]][1] if j + 1 < len(ones) else total) for j, i in enumerate(ones)]
    i_every = idx("everybody")
    i_these = next(i for i in range(i_every + 1, len(ws)) if ws[i][0] in ("but", "these"))
    i_instead = idx("instead")
    i_like = idx("like", i_instead)
    order = [w for w, *_ in ws[i_every:i_these]]
    li = "LinkedIn & Indeed" if order.index(next(w for w in order if w.startswith("linked"))) < order.index(
        next(w for w in order if w.startswith("indeed"))) else "Indeed & LinkedIn"
    caps = [("Quickest way to find\na remote job", 0.0, ws[i_every][1]),
            (li, ws[i_every][1], ws[i_these][1]),
            ("Way too saturated", ws[i_these][1], ws[i_instead][1]),
            ("Niche websites ->", ws[i_instead][1], ws[i_like][1])]
    ones = [i for i in range(i_like, len(ws)) if ws[i][0] == "this"]
    total = sum(b - a for a, b in segs)
    spots = [(ws[i][1], ws[ones[j + 1]][1] if j + 1 < len(ones) else total) for j, i in enumerate(ones)]
    return caps, spots


# B: «this one» 6 раз, а сайтов 3 — по решению клиента ролик заканчивается после 3-го жеста: перед «like this one»
# (начало следующей фразы по огибающей речи — 16.47 с смонтированного ролика)
# A: «this one» 4 раза — клиент: оставить первые 3, ролик заканчивается после 3-й фразы (речь до 13.69 с,
# 4-я «and this one» с 13.94 с смонтированного ролика)
TRIM_END = {"B_DE1131C3": 16.42, "A_891EA56C": 13.60}   # A: клиент срезал ещё 0.2 с
REMOVE_SRC: dict = {}          # вырезать фразы из середины: {клип: [(с, по) в секундах исходника]}
CLEAN = False          # --clean: ролик без подписей сайтов (для tuner.html), output/gw_niche2/tuner/<A|B|C>.mp4


def load_layout(path: Path) -> None:
    """Раскладка из tuner.html (layout.json: {клип: [[начало, cx, cy, кегль], …]}) поверх GESTURES."""
    lay = json.loads(path.read_text(encoding="utf-8"))
    for clip in CLIPS:
        rows = lay.get(clip) or lay.get(clip[0])
        if rows:
            GESTURES[clip] = [(float(t), float(cx), float(cy), int(px), "tuner") for t, cx, cy, px in rows]


def build(clip: str, work: Path) -> dict:
    src = src_of(clip)
    dur = float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                               capture_output=True, text=True).stdout)
    segs = segments(src, dur)
    zflags = [i % 2 == 1 for i in range(len(segs))]              # наезд — как в исходной нарезке (места подписей)
    if clip in REMOVE_SRC:                                        # вырезанные по просьбе клиента фразы
        keep = [i for i, (a, b) in enumerate(segs)
                if not any(a < r1 and r0 < b for r0, r1 in REMOVE_SRC[clip])]
        segs, zflags = [segs[i] for i in keep], [zflags[i] for i in keep]
    cut = work / f"{clip}_cut.mkv"
    montage(src, segs, cut, zflags)
    rows = track(cut)
    words = json.loads((SRC / "words.json").read_text(encoding="utf-8"))[clip]
    caps, spots = captions(words, segs, clip)
    total = sum(b - a for a, b in segs)
    layers, info = [], {"captions": [], "sites": []}
    plan = GESTURES.get(clip)
    if clip in TRIM_END:
        total = TRIM_END[clip]
        if plan:
            plan = [g for g in plan if g[0] < total - 0.3][:len(SITES)]
        spots = [(a, min(b, total)) for a, b in spots if a < total - 0.3][:len(SITES)]
    if plan:                                                         # последний тезис — до первого жеста
        caps[-1] = (caps[-1][0], caps[-1][1], plan[0][0])
        spots = [(g[0], plan[i + 1][0] if i + 1 < len(plan) else total) for i, g in enumerate(plan)]
    for text, t0, t1 in caps:                                        # тезисы — на груди под лицом
        im = text_img(text, PX_CAP)
        fs = [r["face"] for r in rows if t0 <= r["t"] <= t1 and r["face"]]
        chin = max(f[3] for f in fs) if fs else 1100
        canvas, box = full_frame(im, W / 2, chin + 70 + im.height / 2)
        layers.append((canvas, t0, t1))
        info["captions"].append({"text": text, "t": [round(t0, 2), round(t1, 2)], "box": box})
    for j, (t0, t1) in enumerate(spots):
        name = SITES[j % len(SITES)]
        if plan:                                                     # раскладка по жестам, проверенная по кадрам
            _g0, cx, cy, px, note = plan[j]
            im, dbg = text_img(name, px), {"manual": note}
        else:
            im, cx, cy, dbg = site_spot(rows, t0, t1, name, TIP.get(clip, {}).get(j))
        if j in MANUAL.get(clip, {}):
            im = text_img(name, PX_SITE)
            cx, cy = MANUAL[clip][j]
            dbg["manual"] = True
        canvas, box = full_frame(im, cx, cy)
        if not CLEAN:
            layers.append((canvas, t0, t1))
        info["sites"].append({"site": name, "t": [round(t0, 2), round(t1, 2)], "box": box,
                              "cx": (box[0] + box[2]) / 2, "cy": (box[1] + box[3]) / 2,
                              "px": plan[j][3] if plan else PX_SITE, **dbg})
    args, chain = ["-i", str(cut)], ["[0:v]null[v0]"]
    for k, (canvas, t0, t1) in enumerate(layers, 1):
        png = work / f"{clip}_{k}.png"
        canvas.save(png)
        args += ["-i", str(png)]
        chain.append(f"[v{k - 1}][{k}:v]overlay=0:0:enable='between(t,{t0:.3f},{t1:.3f})'[v{k}]")
    chain.append(f"[v{len(layers)}]format=yuv420p,{SET_SDR}[v]")
    log = subprocess.run([FF, "-hide_banner", "-i", str(cut), "-af", f"{LOUD}:print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = json.loads(log[log.rfind("{"):log.rfind("}") + 1])
    af = (f"{LOUD}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample=48000")
    if clip in TRIM_END:                                             # обрезка конца + короткое затухание звука
        chain[-1] = chain[-1].replace("[v]", f",trim=0:{total:.3f}[v]")
        chain.append(f"[0:a]atrim=0:{total:.3f},afade=t=out:st={total - 0.06:.3f}:d=0.06,{af}[a]")
    else:
        chain.append(f"[0:a]{af}[a]")
    dest = OUT / f"gw_niche2_{clip[0]}_{ID}.mp4"
    crf = "18"
    if CLEAN:
        dest = OUT / "tuner" / f"{clip[0]}.mp4"
        dest.parent.mkdir(parents=True, exist_ok=True)
        chain[-2] = chain[-2].replace("format=yuv420p", "scale=540:960,format=yuv420p")
        crf = "23"
    subprocess.run([FF, "-v", "error", "-y", *args, "-filter_complex", ";".join(chain), "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "medium", "-crf", crf, *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(dest)], check=True)
    return {"file": dest.name, "clip": clip, "duration": round(total, 2), "cuts": len(segs) - 1, **info}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="gwn2_"))
    rep = []
    global CLEAN
    args = sys.argv[1:]
    CLEAN = "--clean" in args
    if "--layout" in args:
        load_layout(Path(args[args.index("--layout") + 1]))
        args = [a for i, a in enumerate(args) if a != "--layout" and (i == 0 or args[i - 1] != "--layout")]
    only = [a for a in args if not a.startswith("-")]
    for clip in [c for c in CLIPS if not only or any(c.startswith(o) for o in only)]:
        r = build(clip, work)
        rep.append(r)
        print(f"{r['file']}: {r['duration']} с, склеек {r['cuts']}, сайты "
              f"{[(s['site'], s['t'], s.get('tip')) for s in r['sites']]}", flush=True)
    if CLEAN:
        (OUT / "tuner" / "start.json").write_text(json.dumps(
            {r["clip"][0]: {"duration": r["duration"], "captions": r["captions"],
                            "sites": [{k: s[k] for k in ("site", "t", "cx", "cy", "px")} for s in r["sites"]]}
             for r in rep}, ensure_ascii=False), encoding="utf-8")
        print("tuner →", OUT / "tuner")
        return 0
    man = OUT / "manifest.json"
    old = json.loads(man.read_text(encoding="utf-8")) if man.exists() else []
    done = {r["clip"] for r in rep}
    man.write_text(json.dumps([r for r in old if r["clip"] not in done] + rep, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
