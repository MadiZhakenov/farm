#!/usr/bin/env python3
"""
1322 — Inspoy, квиз-карусель «какой у тебя цветотип»: 8 слайдов 9:16 (1080×1920), полная копия концепта
@helen.mayn3 (downloads/1322/ref/slide1–8.jpg): светлый розово-серый градиент, тёмный текст с засечками
(Newsreader — ближайший к рефу), круглые фото, карточки с мягкой тенью, палитры квадратиками.

Вёрстка — в координатах рефа (1080×1920), потом весь контент одним масштабом S вписывается в безопасную рамку
9:16 (core/safe_zones: x 140–940, y 200–1540) — у рефа края на x 115–968, низ палитр на y 1600.
Тексты — дословно из ТЗ; подписи под картинками — как в рефе. Картинки (портреты, запястья, волосы, глаза) —
вырезки из рефа (001) или свои (--set папка: <слот>.jpg — кадр по лицу, круг/карточка с ободком
и тенью как в рефе); палитры и точки рисуем сами цветами рефа. Финал — текст ТЗ + карточка App Store (1319).

  python build_1322_carousels.py --out output/carousels_1322_test
  python build_1322_carousels.py --out output/carousels_1322_test --set output/1322_pick/002
  python build_1322_carousels.py -n 100 --out output/carousels_1322 --flat output/1322_100     # партия из 1322_lib
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402  (Apple-эмодзи)
import build_1319_carousels as C1319  # noqa: E402  (app_card)
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402

W, H = 1080, 1920
X0, Y0, X1, Y1 = text_rect(W, H)
SS = 2                                                # суперсэмплинг вёрстки
REF = ROOT / "downloads" / "1322" / "ref"
FONT = ROOT / "fonts" / "serif" / "Newsreader[opsz,wght].ttf"
INK = (28, 26, 27)
BG_TOP, BG_BOT = (240, 234, 237), (231, 225, 225)
# контент рефа занимает x 115–968, y 204–1600 → вписываем в рамку
S = 0.93
REF_TOP, TOP = 204, 205


def font(px: float, wght: int = 600) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT), max(1, round(px * SS)))
    f.set_variation_by_axes([wght, min(72, max(6, px))])
    return f


# ---------------- вырезки из рефа ----------------
def ref_img(i: int) -> Image.Image:
    return Image.open(REF / f"slide{i}.jpg").convert("RGB")


def cut_circle(i: int, box: tuple[int, int, int, int], pad: int = 16) -> Image.Image:
    """Круглое фото с ободком/тенью рефа: альфа — круг с мягким краем за тенью."""
    x, y, w, h = box
    im = ref_img(i).crop((x - pad, y - pad, x + w + pad, y + h + pad)).convert("RGBA")
    cx, cy, r = im.width / 2, im.height / 2, max(w, h) / 2
    yy, xx = np.mgrid[0:im.height, 0:im.width]
    d = np.hypot(xx + 0.5 - cx, yy + 0.5 - cy)
    a = np.clip((r + pad - d) / (pad - 4), 0, 1) * 255
    im.putalpha(Image.fromarray(a.astype(np.uint8)))
    return im


def cut_rect(i: int, box: tuple[int, int, int, int], pad: int = 18) -> Image.Image:
    """Прямоугольная вырезка с растушёванным краем (фон рефа = наш фон)."""
    x, y, w, h = box
    im = ref_img(i).crop((x - pad, y - pad, x + w + pad, y + h + pad)).convert("RGBA")
    a = Image.new("L", im.size, 0)
    ImageDraw.Draw(a).rectangle((pad // 2, pad // 2, im.width - pad // 2 - 1, im.height - pad // 2 - 1), fill=255)
    im.putalpha(a.filter(ImageFilter.GaussianBlur(pad / 3)))
    return im


def sample(i: int, cx: int, cy: int, r: int = 6) -> tuple[int, int, int]:
    a = np.asarray(ref_img(i))[cy - r:cy + r, cx - r:cx + r].reshape(-1, 3)
    return tuple(int(v) for v in np.median(a, axis=0))


# ---------------- свои картинки: кадр по лицу + оформление как в рефе ----------------
_FL = None


def face_box(im: Image.Image) -> tuple[float, float, float, float, list] | None:
    """(x0, y0, x1, y1, точки) лица в пикселях или None."""
    global _FL
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    if _FL is None:
        _FL = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "face_landmarker.task")), num_faces=1,
            min_face_detection_confidence=0.3, min_face_presence_confidence=0.3))
    r = None
    for side in (1024, 640, 1600):                    # крупные/мелкие кадры детектор видит через раз — пробуем масштабы
        k = min(1.0, side / max(im.size))
        small = im.convert("RGB").resize((round(im.width * k), round(im.height * k)))
        r = _FL.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(small).copy()))
        if r.face_landmarks:
            break
    if not r.face_landmarks:
        return None
    pts = [(q.x * im.width, q.y * im.height) for q in r.face_landmarks[0]]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys), pts


def crop_box(im: Image.Image, cx: float, cy: float, w: float, h: float) -> Image.Image:
    """Кадр w×h с центром (cx, cy), сдвинутый внутрь картинки (при нехватке — уменьшенный)."""
    k = min(1.0, im.width / w, im.height / h)
    w, h = w * k, h * k
    x0 = min(max(cx - w / 2, 0), im.width - w)
    y0 = min(max(cy - h / 2, 0), im.height - h)
    return im.crop((round(x0), round(y0), round(x0 + w), round(y0 + h)))


def crop_pad(im: Image.Image, cx: float, cy: float, w: float, h: float) -> Image.Image:
    """Кадр w×h с центром (cx, cy); где кадр выходит за фото — однотонный фон фото тянется краем и размывается
    (студийный портрет: голова целиком, без обрезанной макушки)."""
    import cv2
    x0, y0 = round(cx - w / 2), round(cy - h / 2)
    y0 -= max(0, y0 + round(h) - im.height)          # снизу не достраиваем (там тело) — сдвигаем кадр вверх
    l, t = max(0, -x0), max(0, -y0)
    r, b = max(0, x0 + round(w) - im.width), max(0, y0 + round(h) - im.height)
    a = np.asarray(im.convert("RGB"))
    if l or t or r or b:
        pad = np.pad(a, ((t, b), (l, r), (0, 0)), mode="edge")
        blur = cv2.GaussianBlur(pad, (0, 0), 25)
        m = np.zeros(pad.shape[:2], np.float32)
        m[t:t + a.shape[0], l:l + a.shape[1]] = 1
        m = cv2.GaussianBlur(m, (0, 0), 6)[..., None]
        a = (pad * m + blur * (1 - m)).astype(np.uint8)
        x0, y0 = x0 + l, y0 + t
    return Image.fromarray(a).crop((x0, y0, x0 + round(w), y0 + round(h)))


def frame_portrait(src: Path, w: int, h: int, zoom: float = 2.5, drop: float = 0.28, pad: bool = False) -> Image.Image:
    """Портрет: лицо по центру, голова+плечи (zoom — во сколько раз кадр выше лица)."""
    im = Image.open(src).convert("RGB")
    fb = face_box(im)
    if fb is None:
        c = crop_box(im, im.width / 2, im.height * 0.42, im.width, im.width * h / w)
    else:
        x0, y0, x1, y1, _ = fb
        fh = y1 - y0
        ch = fh * zoom
        fn = crop_pad if pad else crop_box
        c = fn(im, (x0 + x1) / 2, (y0 + y1) / 2 + fh * drop, ch * w / h, ch)
    return c.resize((w, h), Image.Resampling.LANCZOS)


_EYE_CASCADE = None


def eye_span(im: Image.Image) -> tuple[float, float, float, float] | None:
    """(x левого края левого глаза, x правого края правого глаза, y центра глаз, высота глаза) — по точкам лица,
    а на крупных планах без лица — по каскаду Хаара (пара глаз примерно одного размера на одной высоте)."""
    import cv2
    global _EYE_CASCADE
    fb = face_box(im)
    if fb:
        pts = fb[4]
        le, re = [33, 133, 159, 145], [263, 362, 386, 374]
        xs = [pts[i][0] for i in le + re]
        ys = [pts[i][1] for i in le + re]
        return min(xs), max(xs), sum(ys) / len(ys), (max(ys) - min(ys)) * 1.6
    if _EYE_CASCADE is None:
        _EYE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    best = None
    for side in (700, 1100):
        k = min(1.0, side / max(im.size))
        g = cv2.cvtColor(np.asarray(im.convert("RGB").resize((round(im.width * k), round(im.height * k)))),
                         cv2.COLOR_RGB2GRAY)
        g = cv2.equalizeHist(g)
        found = _EYE_CASCADE.detectMultiScale(g, 1.05, 3, minSize=(int(g.shape[1] * 0.07),) * 2,
                                              maxSize=(int(g.shape[1] * 0.45),) * 2)
        for i in range(len(found)):
            for j in range(len(found)):
                x1, y1, w1, h1 = found[i]
                x2, y2, w2, h2 = found[j]
                if x2 <= x1:
                    continue
                if abs((y1 + h1 / 2) - (y2 + h2 / 2)) > 0.3 * max(h1, h2) or not 0.7 < w1 / w2 < 1.4:
                    continue
                gap = x2 - (x1 + w1)                    # между глазами ~ ширина глаза (переносица)
                if not 0.35 * max(w1, w2) < gap < 1.9 * max(w1, w2):
                    continue
                if (x2 + w2 - x1) > 0.97 * g.shape[1]:
                    continue
                score = (w1 + w2) / g.shape[1]
                if best is None or score > best[0]:
                    best = (score, x1 / k, (x2 + w2) / k, (y1 + h1 / 2 + y2 + h2 / 2) / 2 / k, max(h1, h2) / k)
    if best is None:
        return None
    _, xl, xr, yc, eh = best
    return xl, xr, yc, eh * 0.75


def frame_eyes(src: Path, w: int, h: int) -> Image.Image | None:
    """Полоска с обоими глазами целиком: ширина = от края до края глаз + поля 16 %, по центру глаз.
    None — глаза не нашлись или пара не влезает в кадр целиком (такое фото не берём)."""
    im = Image.open(src).convert("RGB")
    sp = eye_span(im)
    if sp is None:
        return None
    xl, xr, yc, eh = sp
    cw = (xr - xl) * 1.32
    ch = cw * h / w
    if ch < eh * 1.6:                                   # глаза высокие (крупно) — расширяем, чтобы влезли по высоте
        ch = eh * 1.6
        cw = ch * w / h
    if cw > im.width or ch > im.height:                 # глаза на всю ширину фото — поля меньше, но оба глаза целиком
        k = min(im.width / cw, im.height / ch)
        cw, ch = cw * k, ch * k
        if cw < (xr - xl) * 1.04 or ch < eh * 1.15:
            return None
    c = crop_box(im, (xl + xr) / 2, yc, cw, ch)
    return c.resize((w, h), Image.Resampling.LANCZOS)


def framed(photo: Image.Image, shape: str, radius: int = 0, pad: int = 26) -> Image.Image:
    """Фото в круге / скруглённом прямоугольнике + светлый ободок и мягкая тень, как в рефе."""
    w, h = photo.size
    m = Image.new("L", (w * 4, h * 4), 0)
    dm = ImageDraw.Draw(m)
    if shape == "circle":
        dm.ellipse((0, 0, w * 4 - 1, h * 4 - 1), fill=255)
    else:
        dm.rounded_rectangle((0, 0, w * 4 - 1, h * 4 - 1), radius=radius * 4, fill=255)
    m = m.resize((w, h), Image.Resampling.LANCZOS)
    size = (w + 2 * pad, h + 2 * pad)
    sh = Image.new("L", size, 0)
    sh.paste(m, (pad, pad + 6))
    sh = sh.filter(ImageFilter.GaussianBlur(11)).point(lambda v: int(v * 0.22))
    out = Image.new("RGBA", size, (90, 70, 75, 0))
    out.putalpha(sh)
    ring = Image.new("RGBA", (w + 8, h + 8), (250, 247, 248, 0))
    ring.putalpha(m.resize((w + 8, h + 8), Image.Resampling.LANCZOS).point(lambda v: int(v * 0.7)))
    out.alpha_composite(ring, (pad - 4, pad - 4))
    ph = photo.convert("RGBA")
    ph.putalpha(m)
    out.alpha_composite(ph, (pad, pad))
    return out


# ---------------- рисование в координатах рефа ----------------
class Slide:
    def __init__(self) -> None:
        self.im = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)
        self.text_boxes: list[tuple[float, float, float, float]] = []

    def paste(self, el: Image.Image, x: float, y: float) -> None:
        """el в масштабе рефа, (x, y) — левый верх в рефе."""
        e = el.resize((round(el.width * SS), round(el.height * SS)), Image.Resampling.LANCZOS)
        self.im.alpha_composite(e, (round(x * SS), round(y * SS)))

    def text(self, cx: float, top: float, s: str, px: float, wght: int = 600, emoji: str = "") -> float:
        """Строка по центру cx, верх букв (cap) — top; эмодзи Apple в конце. Возвращает низ (baseline+desc)."""
        f = font(px, wght)
        tw = f.getlength(s)
        epx = round(px * 1.05 * SS)
        e = A._apple_emoji_rgba(emoji, epx) if emoji else None
        gap = px * 0.28 * SS if e is not None else 0
        total = tw + gap + (e.width if e is not None else 0)
        x = cx * SS - total / 2
        base = top * SS + 0.72 * px * SS
        self.d.text((x, base), s, font=f, fill=INK, anchor="ls")
        if e is not None:
            self.im.alpha_composite(e, (round(x + tw + gap), round(base - e.height * 0.82)))
        bb = self.d.textbbox((x, base), s, font=f, anchor="ls")
        self.text_boxes.append((x / SS, bb[1] / SS, (x + total) / SS, bb[3] / SS))
        return bb[3] / SS

    def squares(self, x: float, y: float, colors: list, size: float, gap: float, cols: int, radius: float = 0) -> None:
        for k, c in enumerate(colors):
            sx, sy = x + (k % cols) * (size + gap), y + (k // cols) * (size + gap)
            self.d.rounded_rectangle((sx * SS, sy * SS, (sx + size) * SS - 1, (sy + size) * SS - 1),
                                     radius=radius * SS, fill=c)

    def dots(self, x: float, y: float, colors: list, dia: float, gap: float) -> None:
        for k, c in enumerate(colors):
            sx = x + k * (dia + gap)
            self.d.ellipse((sx * SS, y * SS, (sx + dia) * SS, (y + dia) * SS), fill=c)

    def render(self) -> tuple[Image.Image, list[tuple[int, int, int, int]]]:
        bg = Image.new("RGB", (1, H))
        for yy in range(H):
            t = yy / (H - 1)
            bg.putpixel((0, yy), tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT)))
        bg = bg.resize((W, H)).convert("RGBA")
        cw, ch = round(W * S), round(H * S)
        layer = self.im.resize((cw, ch), Image.Resampling.LANCZOS)
        ox, oy = round(540 - 540 * S), round(TOP - REF_TOP * S)
        bg.alpha_composite(layer, (ox, oy))
        boxes = [(round(ox + a * S), round(oy + b * S), round(ox + c * S), round(oy + d * S))
                 for a, b, c, d in self.text_boxes]
        return bg.convert("RGB"), boxes


# ---------------- слайды ----------------
SEASONS = [("Winter", (119, 384, 363, 368), (300, 774)), ("Spring", (600, 385, 368, 368), (784, 774)),
           ("Summer", (115, 1084, 364, 368), (297, 1472)), ("Autumn", (602, 1083, 366, 367), (785, 1472))]
PAL1 = {"Winter": (210, 832), "Spring": (694, 832), "Summer": (208, 1530), "Autumn": (694, 1530)}


SET: dict[str, Path] = {}                             # слот → своя картинка; пусто — вырезка из рефа
# кадр портрета в круге — как у той же звезды в рефе (замер: сторона круга / высота лица, сдвиг центра в лицах)
CIRCLE_FRAME = {"winter": (3.22, 0.59), "spring": (2.3, 0.13), "summer": (2.53, 0.09), "autumn": (2.4, 0.1)}


def circle_frame(src: Path, season: str) -> tuple[float, float] | None:
    """Кадр круга под конкретное фото: зум сезона из рефа, если влезает; иначе ближе (до 2.05 высоты лица — голова
    целиком), низ не выходит за фото (снизу не достраиваем), бока — максимум на 8 %. None — фото не годится."""
    im = Image.open(src)
    fb = face_box(im)
    if fb is None:
        return None
    x0, y0, x1, y1, _ = fb
    fh = y1 - y0
    zoom, drop = CIRCLE_FRAME[season]
    xc, yc = (x0 + x1) / 2, (y0 + y1) / 2
    def fits(z: float, d: float) -> bool:
        side = z * fh
        return yc + d * fh + side / 2 <= im.height + 1 and side / 2 <= min(xc, im.width - xc) * 1.08             and max(0.0, side / 2 - (yc + d * fh)) <= 0.18 * side
    if fits(zoom, drop):
        return zoom, drop
    for z in np.arange(min(zoom, 3.0), 2.04, -0.05):
        if fits(z, 0.12):
            return round(float(z), 2), 0.12
    return None


def ref_grade(photo: Image.Image, ref_box: tuple[int, int, int, int], ref_slide: int, k: float = 0.35) -> Image.Image:
    """Вайб рефа: перенос цвета (среднее/разброс в Lab) с той же ячейки рефа, сила k."""
    import cv2
    x, y, w, h = ref_box
    r = np.asarray(ref_img(ref_slide).crop((x + w * 0.15, y + h * 0.15, x + w * 0.85, y + h * 0.85)).convert("RGB"))
    a = np.asarray(photo.convert("RGB"))
    lr = cv2.cvtColor(r, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
    la = cv2.cvtColor(a, cv2.COLOR_RGB2LAB).astype(np.float32)
    mu_s, sd_s = la.reshape(-1, 3).mean(0), la.reshape(-1, 3).std(0) + 1e-3
    mu_t, sd_t = lr.mean(0), lr.std(0)
    out = (la - mu_s) / sd_s * sd_t + mu_t
    out = la + (out - la) * k
    return Image.fromarray(cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB))


def slide1() -> Slide:
    sl = Slide()
    sl.text(540, 210, "Let's find out your personal color", 49, 600, emoji="✨")
    sl.text(540, 282, "(results in the last slides)", 34, 450)
    for name, box, (cx, ty) in SEASONS:
        if name.lower() in SET:
            zoom, drop = circle_frame(SET[name.lower()], name.lower()) or CIRCLE_FRAME[name.lower()]
            ph = ref_grade(frame_portrait(SET[name.lower()], 352, 352, zoom, drop, pad=True), box, 1)
            sl.paste(framed(ph, "circle"), box[0] + 6 - 26, box[1] + 6 - 26)
        else:
            sl.paste(cut_circle(1, box), box[0] - 16, box[1] - 16)
        sl.text(cx, ty, name, 47, 600)
        px, py = PAL1[name]
        cols = [sample(1, px + 18 + c * 36, py + 18 + r * 36) for r in range(2) for c in range(5)]
        sl.squares(px + 2, py + 2, cols, 32, 4, 5)
    return sl


WRISTS = [("A. Warm", "Greenish veins", (143, 637, 230, 555), 151),
          ("B. Neutral", "Blue-green veins", (437, 637, 229, 555), 466),
          ("C. Cool", "Blue-purple veins", (727, 636, 229, 556), 798)]


def slide2() -> Slide:
    sl = Slide()
    sl.text(540, 210, "What's your Undertone?", 49, 600)
    for lab, sub, box, dx in WRISTS:
        slot = "wrist_" + lab[0].lower()
        if slot in SET:                               # вырезанный кулак (PNG с альфой) — прямо на фон, низ по рефу
            ph = Image.open(SET[slot]).convert("RGBA")
            k = min((box[2] + 40) / ph.width, box[3] / ph.height)
            ph = ph.resize((round(ph.width * k), round(ph.height * k)), Image.Resampling.LANCZOS)
            sl.paste(ph, box[0] + (box[2] - ph.width) / 2, box[1] + box[3] - ph.height)
        else:
            sl.paste(cut_rect(2, box), box[0] - 18, box[1] - 18)
        cx = box[0] + box[2] / 2
        sl.text(cx, 1273, lab, 40, 600)
        sl.text(cx, 1330, sub, 26, 600)
        cols = [sample(2, dx + 17 + round(k * 39.5), 1386, 5) for k in range(3)]
        sl.dots(cx - (3 * 34 + 2 * 5.5) / 2, 1369, cols, 34, 5.5)          # точки — по центру под подписью
    return sl


HAIR = [("A. Ginger", (120, 458, 368, 371), (304, 847)), ("B. Brown", (599, 460, 361, 369), (780, 847)),
        ("C. Blonde", (120, 1098, 368, 369), (304, 1487)), ("D. Black", (598, 1097, 362, 370), (780, 1487))]


def slide3() -> Slide:
    sl = Slide()
    sl.text(540, 210, "What's your hair color?", 49, 600)
    for lab, box, (cx, ty) in HAIR:
        slot = "hair_" + lab[0].lower()
        if slot in SET:
            ph = Image.open(SET[slot]).convert("RGB")
            side = min(ph.size)
            ph = crop_box(ph, ph.width / 2, ph.height / 2, side, side).resize((356, 356), Image.Resampling.LANCZOS)
            sl.paste(framed(ph, "circle"), box[0] + 6 - 26, box[1] + 6 - 26)
        else:
            sl.paste(cut_circle(3, box), box[0] - 16, box[1] - 16)
        sl.text(cx, ty, lab, 47, 600)
    return sl


EYES = [("A. Blue", 448, 624), ("B. Brown", 751, 925), ("C. Green", 1052, 1226), ("D. Hazel", 1352, 1527)]


def slide4() -> Slide:
    sl = Slide()
    sl.text(540, 210, "What's your eye color?", 49, 600)
    for lab, y, ty in EYES:
        slot = "eyes_" + lab[0].lower()
        if slot in SET:
            sl.paste(framed(frame_eyes(SET[slot], 415, 142), "rect", 14), 332 - 26, y + 4 - 26)
        else:
            sl.paste(cut_rect(4, (326, y, 427, 154)), 326 - 18, y - 18)
        sl.text(540, ty, lab, 47, 600)
    return sl


RESULTS = [(5, "CBA · CBC", "true summer", "TRUE SUMMER"),
           (6, "BCC · BCA", "light summer", "LIGHT SUMMER"),
           (7, "BBD · BBC", "soft summer", "SOFT SUMMER")]


def slide_result(i: int, code: str, low: str, caps: str) -> Slide:
    sl = Slide()
    sl.text(540, 215, code, 65, 600)
    sl.text(540, 300, low, 47, 500)
    if f"card_{i}" in SET:
        sl.paste(framed(frame_portrait(SET[f"card_{i}"], 812, 834, 2.3, 0.22), "rect", 34), 134 - 26, 410 - 26)
    else:
        sl.paste(cut_rect(i, (120, 404, 840, 864)), 120 - 18, 404 - 18)
    sl.text(540, 1387, caps, 65, 600)
    xs = [119, 264, 408, 551, 695, 839]
    cols = [sample(i, x + 61, 1539, 12) for x in xs]
    for x, c in zip(xs, cols):
        sl.squares(x, 1478, [c], 122, 0, 1)
    return sl


def slide8() -> Slide:
    sl = Slide()
    y = 600
    for ln in ("Your code", "isn't here?"):
        y = sl.text(540, y, ln, 90, 700) + 30
    y += 40
    for ln in ("Inspoy finds your season", "from one selfie"):
        y = sl.text(540, y, ln, 48, 500) + 18
    card = C1319.app_card(700)
    sl.paste(card, 540 - card.width / 2, y + 90)
    return sl


def build_all() -> list[tuple[Image.Image, list]]:
    slides = [slide1(), slide2(), slide3(), slide4()] + [slide_result(*r) for r in RESULTS] + [slide8()]
    return [sl.render() for sl in slides]


# ---------------- партия: библиотека картинок по слотам ----------------
LIB = ROOT / "output" / "1322_lib"                   # <слот>/<человек>__<n>.jpg; один человек — раз на карусель
SLOTS = ["winter", "spring", "summer", "autumn", "wrist_a", "wrist_b", "wrist_c", "hair_a", "hair_b", "hair_c",
         "hair_d", "eyes_a", "eyes_b", "eyes_c", "eyes_d", "card_5", "card_6", "card_7"]
EXTS = (".jpg", ".jpeg", ".png", ".webp")


def person(p: Path) -> str:
    return p.stem.split("__")[0]


def plan_lib(n: int, seed: int) -> list[dict[str, Path]]:
    """n уникальных наборов: в каждом слоте — реже всего использованная картинка (с шумом), человек не повторяется."""
    import random
    rng = random.Random(seed)
    lib = {sl: sorted(f for f in (LIB / sl).iterdir() if f.suffix.lower() in EXTS) for sl in SLOTS}
    empty = [sl for sl, v in lib.items() if not v]
    if empty:
        raise SystemExit(f"пустые слоты: {empty}")
    use: dict[Path, int] = {}
    seen, out = set(), []
    for _ in range(n):
        for _try in range(500):
            pick, people = {}, set()
            for sl in sorted(SLOTS, key=lambda x: len(lib[x])):
                cand = [f for f in lib[sl] if not (person(f) in people and "__" in f.stem)]
                f = min(cand, key=lambda f: use.get(f, 0) + rng.random() * 0.9)
                pick[sl] = f
                if "__" in f.stem:
                    people.add(person(f))
            key = tuple(pick[sl] for sl in SLOTS)
            if key not in seen:
                break
        else:
            raise SystemExit("не хватает уникальных комбинаций")
        seen.add(key)
        for f in key:
            use[f] = use.get(f, 0) + 1
        out.append(pick)
    return out


def render_one(job: tuple[int, dict, str, str | None, str]) -> str:
    i, pick, out, flat, flat_id = job
    SET.clear()
    SET.update({k: Path(v) for k, v in pick.items()})
    d = Path(out) / f"{i:03d}"
    d.mkdir(parents=True, exist_ok=True)
    for k, (im, boxes) in enumerate(build_all(), 1):
        for b in boxes:
            bad = check_box(W, H, b)
            if bad:
                raise SystemExit(f"{i:03d} слайд {k}: текст вне безопасной зоны {b} — {bad}")
        im.save(d / f"{k}.jpg", quality=95)
        if flat:
            im.save(Path(flat) / f"sort_{k}_{i}_{flat_id}.jpg", quality=95)
    return d.name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--set", type=Path, help="папка своих картинок: <слот>.jpg (winter, wrist_a, hair_b, eyes_c, card_5…)")
    ap.add_argument("-n", type=int, default=0, help="партия из библиотеки output/1322_lib (уникальные наборы)")
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_<id>.jpg")
    ap.add_argument("--flat-id", default="1322")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1322)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if args.n:
        import json
        from collections import Counter
        from concurrent.futures import ProcessPoolExecutor
        picks = plan_lib(args.n, args.seed)
        args.out.mkdir(parents=True, exist_ok=True)
        if args.flat:
            args.flat.mkdir(parents=True, exist_ok=True)
        (args.out / "manifest.json").write_text(json.dumps(
            [{"carousel": f"{i:03d}", **{k: v.name for k, v in p.items()}} for i, p in enumerate(picks, 1)],
            indent=1, ensure_ascii=False), encoding="utf-8")
        for sl in SLOTS:
            c = Counter(p[sl].name for p in picks)
            print(f"{sl}: {len(c)} картинок, повторов {min(c.values())}–{max(c.values())}")
        jobs = [(i, {k: str(v) for k, v in p.items()}, str(args.out), str(args.flat) if args.flat else None,
                 args.flat_id) for i, p in enumerate(picks, 1)]
        with ProcessPoolExecutor(args.jobs) as ex:
            for k, name in enumerate(ex.map(render_one, jobs), 1):
                print(f"[{k}/{len(jobs)}] {name}", flush=True)
        print(f"готово: {len(jobs)} → {args.out}")
        return 0
    name = "001"
    if args.set:
        SET.update({p.stem: p for p in args.set.iterdir() if p.suffix.lower() in EXTS})
        name = args.set.name
    d = args.out / name
    d.mkdir(parents=True, exist_ok=True)
    qa = []
    for k, (im, boxes) in enumerate(build_all(), 1):
        for b in boxes:
            bad = check_box(W, H, b)
            if bad:
                raise SystemExit(f"слайд {k}: текст вне безопасной зоны {b} — {bad}")
        im.save(d / f"{k}.jpg", quality=95)
        q = draw_overlay(im.copy())
        dr = ImageDraw.Draw(q)
        for b in boxes:
            dr.rectangle(b, outline=(255, 200, 0), width=3)
        qa.append(q.resize((270, 480)))
    sheet = Image.new("RGB", (270 * len(qa), 480), "white")
    for k, q in enumerate(qa):
        sheet.paste(q, (k * 270, 0))
    sheet.save(args.out / f"_qa_{name}.jpg", quality=86)
    print(f"готово → {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
