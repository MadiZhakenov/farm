#!/usr/bin/env python3
"""
1390 — копия рефа @bad_bitch_life1 (downloads/1390/ref/ref.mp4) под его бит и звук: 9 статичных слайдов 9:16.
  1 обложка: фото во весь кадр + «clothes / i / find / extremely / swaggy / in fall» узким шрифтом по слову
    в строку (Bebas Neue, чуть жирнее и уже — как в рефе), светло-серый с мягкой тенью, слева от героини;
  2–9 виды джинсов: коллаж 2×2 из двух фото «шахматкой» (A B / B A), по центру плашка с названием из ТЗ
    (цвет плашки — из палитры фото, текст светлый на тёмной / тёмный на светлой);
  7–9 (cargo, studded, raw denim) поверх — подпись ТЗ TikTok-шрифтом с обводкой.
Склейки — на ударах 808-кика трека рефа (1,44 / 3,29 / 4,73 / 6,57 / 8,01 / 9,85 / 11,29 / 13,14): 9 слайдов в
оригинальные 14,14 с без повторов. Весь текст в безопасной рамке 9:16 (core/safe_zones).

Фото: output/1390_pick3/<слот>/pairNN_a|b.jpg — пары «одна вещь, два разных кадра» (harvest_1390_brands.py), обложка cover/*.jpg.

  python build_1390_reels.py --test                  # 2 ролика + QA-лист → output/1390_test
  python build_1390_reels.py -n 50 --id 1390         # → output/1390_<n>/NNN_1390.mp4
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1281_carousels as B  # noqa: E402  (text_block — TikTok-текст с обводкой и эмодзи)
import build_gw_pyramid_reel as P  # noqa: E402  (FF)
from core.safe_zones import check_box, draw_overlay  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF, W, H, FPS = P.FF, 1080, 1920, 30
PICK = Path(os.environ.get("PICK1390") or ROOT / "output" / "1390_pick9")      # PICK1390 — другой набор фото (pick10: новые обложки)
REF_AUDIO = ROOT / "downloads" / "1390" / "ref" / "ref_audio.wav"
FONT = ROOT / "fonts" / "bebas" / "BebasNeue-Regular.ttf"
NL = chr(10)

# склейки рефа (с) и продолжение той же сеткой до 9 слайдов
# склейка на каждый такт: трек рефа ~146,6 BPM, такт 1,637 с от первой бочки (0,012 с; бочки 3,25 / 6,54 / 9,82 / 13,11
# совпадают с сеткой) — 9 слайдов влезают в оригинальные 14,14 с трека без повторов
# сетка по анализу трека: восьмые 0,197 + 0,20522·k (≈146,2 BPM), самый слышный удар — клэп/снейр на 3-й доле такта:
# 2,660 / 5,943 / 9,227 / 12,510 → такт 1,6417 с; склейки ровно на клэп (кадр округляем вниз — не позже удара)
# склейки на ударах 808-кика (ритм у трека «ломаный»: в каждой 2-тактной фразе 3,284 с кик на +0,01 / +0,83 / +1,44 —
# берём +0,01 и +1,44, получается 1,44 / 1,84 / 1,44 / 1,84 …); точки сверены в тюнере (артефакт 3rhtdhNkyoJfrk8PdgwoVP)
KICKS = [1.443, 3.289, 4.731, 6.571, 8.011, 9.854, 11.291, 13.142]
CUTS = [0.0] + [int(k * 30) / 30 for k in KICKS]           # кадр округляем вниз — смена не позже удара
END = 14.14
# короткая версия (--short, 8 с): жёсткий бас на 5-й секунде трека (808 в 4,711 с) — ровно на ПЕРВОМ переходе
# (обложка → 1-й вид, 1,43 с ролика): трек стартует с 3,278 с. Дальше — логика массовой версии: склейки на 808-киках
# и между ними на ближайший к середине удар (5,740 / 9,023); на кадр раньше удара (иначе «отстаёт»).
# 9 слайдов в 8 с; подпись + App Store с ~5,7 с (последние ~2 с), под ними слайды продолжают меняться.
SHORT_START = 4.711 - 1.433
SHORT_HITS = [t - SHORT_START for t in (4.711, 5.740, 6.567, 7.385, 8.003, 9.023, 9.849, 10.672)]
SHORT_CUTS = [0.0] + [(round(k * 30) - 1) / 30 for k in SHORT_HITS]   # ровно 1 кадр до удара
SHORT_END = 8.0

# слот (папка в 1390_pick), текст ТЗ
SLIDES = [
    ("cover", NL.join(["clothes", "i", "find", "extremely", "swaggy", "in fall"])),
    ("embroidered", "embroidered jeans"),
    ("graphic", "graphic print jeans"),
    ("wide_dark", "wide leg dark jeans"),
    ("vintage_wash", "vintage wash jeans"),
    ("patchwork", "patchwork jeans"),
    ("cargo", "cargo jeans"),
    ("studded", "studded jeans"),
    ("raw_denim", "raw denim jeans"),
]
CAPTION = NL.join(["i put all of these together", "in Inspoy:", "Outfit Maker, Planner 🤍"])
CAPTION_FROM = 6                                    # с какого слайда (индекс) — cargo
CAPTION_PX, CAPTION_CY = 54, 0.235                  # кегль и центр подписи по высоте

# типографика рефа (замер на 576×1024): высота заглавных плашки 3,4 % H, поля 0,5 / 0,36 высоты букв,
# обложка 3,9 % H, шаг строк 1,55 высоты букв; буквы сужены и чуть утолщены относительно Bebas Neue
SQX, BOLD = 0.88, 0.022
PLATE_CAP, PAD_X, PAD_Y = 0.034, 0.5, 0.36
COVER_CAP, COVER_STEP, COVER_CX, COVER_CY = 0.039, 1.55, 0.30, 0.47
COVER_COLOR = (255, 255, 255)                        # белый (клиент), читается за счёт двойной тени
COVER_CX_R = 0.72
EXT = (".jpg", ".jpeg", ".png", ".webp")
GRADE = False          # кодовый цвет/зерно выключены: качество и цвет фото делаем ИИ-правками (Flow), output/1390_flow


def bebas(text: str, cap: int, fill: tuple[int, int, int]) -> Image.Image:
    """Одна строка заглавными: Bebas Neue, псевдо-жирность обводкой того же цвета, сжатие по ширине."""
    px = round(cap / 0.7)                            # высота заглавных Bebas = 0,7 кегля
    font = ImageFont.truetype(str(FONT), px)
    sw = max(1, round(px * BOLD))
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    b = d.textbbox((0, 0), text.upper(), font=font, stroke_width=sw)
    im = Image.new("RGBA", (b[2] - b[0] + 4, b[3] - b[1] + 4), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((2 - b[0], 2 - b[1]), text.upper(), font=font, fill=fill + (255,), stroke_width=sw,
                            stroke_fill=fill + (255,))
    return im.resize((round(im.width * SQX), im.height), Image.Resampling.LANCZOS)


def plate_colors(photos: list[Image.Image]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Цвет плашки из палитры фото (самый «характерный» насыщенный кластер; если всё серое — тёмный или
    светлый нейтральный), и цвет текста: кремовый на тёмной, тёмный того же оттенка на светлой."""
    import cv2
    px = np.concatenate([np.asarray(p.convert("RGB").resize((90, 160))).reshape(-1, 3) for p in photos]).astype(np.float32)
    _c, lab, cent = cv2.kmeans(px, 6, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5), 3,
                               cv2.KMEANS_PP_CENTERS)
    share = np.bincount(lab.ravel(), minlength=6) / len(lab)
    hsv = cv2.cvtColor(cent.reshape(1, -1, 3).astype(np.uint8), cv2.COLOR_RGB2HSV)[0].astype(float)
    sat, val = hsv[:, 1] / 255, hsv[:, 2] / 255
    score = sat * np.sqrt(share) * (val > 0.18)
    k = int(np.argmax(score))
    if sat[k] < 0.28:                                # всё нейтральное — как BAPE / ED HARDY / LANVIN в рефе
        light = float(np.average(val, weights=share)) < 0.45
        plate = (238, 234, 228) if light else (16, 15, 13)
    else:
        h, s, v = hsv[k]
        v = min(max(v, 95), 205)                     # не кислотный и не чёрный
        plate = tuple(int(c) for c in cv2.cvtColor(np.uint8([[[h, min(s, 200), v]]]), cv2.COLOR_HSV2RGB)[0, 0])
    lum = 0.299 * plate[0] + 0.587 * plate[1] + 0.114 * plate[2]
    if lum < 150:
        text = (246, 239, 221)
    else:
        hh, ss, _vv = cv2.cvtColor(np.uint8([[plate]]), cv2.COLOR_RGB2HSV)[0, 0]
        text = tuple(int(c) for c in cv2.cvtColor(np.uint8([[[hh, max(int(ss), 90), 120]]]), cv2.COLOR_HSV2RGB)[0, 0])
    return plate, text


def plate(label: str, photos: list[Image.Image]) -> Image.Image:
    bg, fg = plate_colors(photos)
    cap = round(PLATE_CAP * H)
    t = bebas(label, cap, fg)
    px_, py_ = round(cap * PAD_X), round(cap * PAD_Y)
    out = Image.new("RGBA", (t.width + 2 * px_, cap + 2 * py_ + 4), bg + (255,))
    out.alpha_composite(t, (px_, (out.height - t.height) // 2))
    return out


def fit_hq(src: Path, size: tuple[int, int], centering: tuple[float, float] = (0.5, 0.45)) -> Image.Image:
    """Кадр в размер с подтяжкой качества: мелкий исходник — сначала мягкий денойз (JPEG-кубики Pinterest),
    потом Lanczos и резкость; затем свой цвет (grade)."""
    import cv2
    im = src if isinstance(src, Image.Image) else ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    scale = max(size[0] / im.width, size[1] / im.height)
    if scale > 1.05:
        a = cv2.fastNlMeansDenoisingColored(np.asarray(im), None, 3, 3, 5, 15)
        im = Image.fromarray(a)
    im = ImageOps.fit(im, size, Image.Resampling.LANCZOS, centering=centering)
    im = im.filter(ImageFilter.UnsharpMask(radius=1.6, percent=70 if scale > 1.05 else 45, threshold=2))
    return grade(im) if GRADE else im


def grade(im: Image.Image) -> Image.Image:
    """Свой вечерний цвет на все кадры: мягкая S-кривая, тени чуть в холодный, света в тёплый янтарь,
    насыщенность +6 % — пары из разных пинов выглядят как одна серия."""
    a = np.asarray(im).astype(np.float32) / 255
    a = a + 0.10 * (a - 0.5) * (1 - np.abs(2 * a - 1))            # S-кривая
    lum = (0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2])[..., None]
    sh, hi = np.clip(1 - lum * 2, 0, 1), np.clip(lum * 2 - 1, 0, 1)
    a = a + sh * np.array([-0.012, 0.004, 0.022]) + hi * np.array([0.03, 0.012, -0.022])
    a = lum + (a - lum) * 1.06
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))


def grain(im: Image.Image, seed: int = 0, amount: float = 3.2) -> Image.Image:
    """Общее мелкое зерно поверх всего кадра — сшивает фото разного качества в один «телефонный» вид."""
    rng = np.random.default_rng(seed)
    a = np.asarray(im.convert("RGB")).astype(np.float32)
    n = rng.normal(0, amount, a.shape[:2])[..., None]
    return Image.fromarray(np.clip(a + n, 0, 255).astype(np.uint8))


JIT = random.Random(0)                               # на ролик: лёгкий зум/сдвиг кадров — ролики не совпадают пиксель в пиксель


CLOSE_P = 0.6                                         # доля плиток, где полный рост заменяем крупным планом джинсов


def close_up(src: Path) -> Image.Image | Path:
    """Крупный план как в рефе: от талии вниз, по центру фигуры — рамка из PICK/_close.json [cx, top, ширина]
    (доли кадра); у фото без рамки или с вероятностью 1 − CLOSE_P — кадр целиком."""
    f = PICK / "_close.json"
    box = json.loads(f.read_text(encoding="utf-8")).get(f"{src.parent.name}/{src.stem}") if f.exists() else None
    if not box or JIT.random() >= CLOSE_P:
        return src
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    cx, top, wf = box
    w = wf * im.width
    h = min(w * H / W, im.height * (1 - top))
    w = h * W / H
    x0 = min(max(0, cx * im.width - w / 2), im.width - w)
    return im.crop((round(x0), round(top * im.height), round(x0 + w), round(top * im.height + h)))


def tile(src: Path) -> Image.Image:
    z = 1 + JIT.uniform(0, 0.07)
    big = fit_hq(close_up(src), (round(W / 2 * z), round(H / 2 * z)))
    x, y = JIT.randint(0, big.width - W // 2), JIT.randint(0, big.height - H // 2)
    return big.crop((x, y, x + W // 2, y + H // 2))


def cover_layout(src: Path, fmt: str) -> dict:
    """Раскладка обложки из PICK/cover/_layout.json: {имя: {"v"|"c": {"cx": центр текста, "ox": сдвиг кадра 0…1, "z": зум}}}
    (v — ролик 9:16, c — карусель 3:4), чтобы текст лёг на пустую сторону и не закрывал человека и джинсы."""
    f = src.parent / "_layout.json"
    if not f.exists():
        return {}
    return json.loads(f.read_text(encoding="utf-8")).get(src.stem, {}).get(fmt, {})


def cover_bg(src: Path, fmt: str) -> Image.Image:
    """Фон обложки: окно кадра с зумом z и сдвигом ox/oy (0 — левый/верхний край исходника, 1 — правый/нижний)."""
    lay = cover_layout(src, fmt)
    z, ox, oy = lay.get("z", 1.0), lay.get("ox", 0.5), lay.get("oy", 0.45)
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    sc = max(W / im.width, H / im.height) * z
    cw, ch = W / sc, H / sc
    x0, y0 = ox * (im.width - cw), oy * (im.height - ch)
    return fit_hq(im.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch))), (W, H))


def cover(src: Path, text: str) -> tuple[Image.Image, list]:
    im = cover_bg(src, "v").convert("RGBA")
    lay = cover_layout(src, "v")
    cap = round(COVER_CAP * H * lay.get("s", 1.0))
    lines = [bebas(ln, cap, COVER_COLOR) for ln in text.split(NL)]
    step = round(cap * COVER_STEP)
    blk = Image.new("RGBA", (max(l.width for l in lines), step * (len(lines) - 1) + lines[-1].height), (0, 0, 0, 0))
    for k, l in enumerate(lines):
        blk.alpha_composite(l, ((blk.width - l.width) // 2, k * step))
    blk = add_shadow(add_shadow(blk, blur=2.5, opacity=0.8, offset=(0, 2), grow=1),    # чёткая тень у букв
                     blur=18, opacity=0.55, offset=(0, 0), grow=10)                     # мягкий тёмный ореол
    cx = cover_layout(src, "v").get("cx") or (COVER_CX_R if src.stem.endswith("_R") else COVER_CX)   # «_R» — текст справа
    x = min(max(140, round(cx * W - blk.width / 2)), 940 - blk.width)
    y = round(lay.get("cy", COVER_CY) * H - blk.height / 2)
    im.alpha_composite(blk, (x, y))
    return (grain(im) if GRADE else im.convert("RGB")), [(x, y, x + blk.width, y + blk.height)]


CARD_W, CARD_CY = 700, 0.665                           # карточка App Store на последнем слайде: ширина, центр по высоте


def store_card() -> Image.Image:
    """Скрин карточки Inspoy из App Store (C1319.app_card) со скруглёнными углами и мягкой тенью."""
    import build_1319_carousels as C1319
    c = C1319.app_card(CARD_W)
    m = Image.new("L", (c.width * 4, c.height * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, c.width * 4 - 1, c.height * 4 - 1), radius=round(c.height * 4 * 0.1), fill=255)
    c.putalpha(m.resize(c.size, Image.Resampling.LANCZOS))
    return add_shadow(c, blur=14, opacity=0.55, offset=(0, 6), grow=2)


def collage(a: Path, b: Path, label: str, caption: bool, card: bool = False) -> tuple[Image.Image, list]:
    ta, tb = tile(a), tile(b)
    im = Image.new("RGBA", (W, H))
    for (x, y), t in zip(((0, 0), (W // 2, 0), (0, H // 2), (W // 2, H // 2)), (ta, tb, tb, ta)):
        im.paste(t, (x, y))
    p = plate(label, [ta, tb])
    x, y = (W - p.width) // 2, (H - p.height) // 2
    im.alpha_composite(p, (x, y))
    boxes = [(x, y, x + p.width, y + p.height)]
    if caption:
        c = B.text_block(CAPTION, H, CAPTION_PX)
        cx, cy = (W - c.width) // 2, round(CAPTION_CY * H - c.height / 2)
        im.alpha_composite(c, (cx, cy))
        boxes.append((cx, cy, cx + c.width, cy + c.height))
    if card:                                        # в короткой версии — вместе с подписью на последних ~2 с
        s = store_card()
        sx, sy = (W - s.width) // 2, round(CARD_CY * H - s.height / 2)
        im.alpha_composite(s, (sx, sy))
        pad = (s.width - CARD_W) // 2
        boxes.append((sx + pad, sy + pad, sx + s.width - pad, sy + s.height - pad))
    return (grain(im) if GRADE else im.convert("RGB")), boxes


def pools() -> list[list[Path]]:
    out = []
    for slot, _t in SLIDES:
        d = PICK / slot
        fs = sorted(f for f in d.iterdir() if f.suffix.lower() in EXT and not f.name.startswith("_")) if d.exists() else []
        need = 1 if slot == "cover" else 2
        if len(fs) < need:
            raise SystemExit(f"{d}: {len(fs)} фото, нужно ≥ {need}")
        pairs = sorted({f.stem[:-2] for f in fs if f.stem.endswith(("_a", "_b"))})
        if slot != "cover" and (d / "_pairs.txt").exists():   # пары заданы списком
            fs = [tuple(d / n for n in ln.split()) for ln in (d / "_pairs.txt").read_text(encoding="utf-8").split(NL) if ln.strip()]
        elif slot != "cover" and pairs and len(pairs) * 2 == len(fs):   # пары «одна вещь, два разных кадра» (pairNN_a / pairNN_b)
            fs = [(d / f"{p}_a.jpg", d / f"{p}_b.jpg") for p in pairs]
        elif slot != "cover":                            # одна модель на всех фото слота — любые два разных кадра
            fs = [(a, b) for i, a in enumerate(fs) for b in fs[i + 1:]]
        out.append(fs)
    return out


def combo_key(slides) -> tuple:
    """Набор ролика по именам файлов; порядок A/B внутри пары не важен — перестановка не считается новым роликом."""
    return tuple(frozenset(getattr(f, "name", f) for f in t) for t in slides)


def plan(n: int, ps: list[list[Path]], rng: random.Random, exclude: set | None = None) -> list[list[tuple[Path, ...]]]:
    """n уникальных роликов: обложка и пары (A, B) берём реже всего использованные; пары не повторяются в слоте,
    пока есть новые; наборы целиком не повторяются — ни между собой, ни с уже выданными (exclude)."""
    use: dict = {}
    seen, out = set(exclude or ()), []
    for _ in range(n):
        for _try in range(200):
            v = []
            for k, fs in enumerate(ps):
                if k == 0:
                    v.append((min(fs, key=lambda f: use.get(f, 0) + rng.random()),))
                    continue
                if isinstance(fs[0], tuple):                # готовые пары: реже всего использованная, A/B иногда меняем местами
                    a, b = min(fs, key=lambda t: use.get(t, 0) + rng.random())
                    v.append((a, b) if rng.random() < 0.5 else (b, a))
                    continue
                a = min(fs, key=lambda f: use.get(f, 0) + rng.random())
                b = min((f for f in fs if f != a), key=lambda f: use.get((a, f), 0) * 3 + use.get(f, 0) + rng.random())
                v.append((a, b))
            key = combo_key(v)
            if key not in seen:
                break
        else:
            raise SystemExit("не нашлось нового сочетания за 200 попыток")
        seen.add(key)
        for k, t in enumerate(v):
            for f in t:
                use[f] = use.get(f, 0) + 1
            if len(t) == 2:
                use[t] = use.get(t, 0) + 1
                use[(t[1], t[0])] = use.get((t[1], t[0]), 0) + 1
        out.append(v)
    return out


def music(dest: Path, start: float = 0.0) -> Path:
    """Трек рефа с начала до END (14,14 с или 7,995 с в --short), без повторов; громкость −14 LUFS."""
    if dest.exists():
        return dest
    fc = (f"[0:a]atrim={start}:{start + END},asetpts=PTS-STARTPTS,afade=t=out:st={END - 0.08}:d=0.08,"
          f"loudnorm=I=-14:TP=-1.5:LRA=11[o]")
    subprocess.run([FF, "-v", "error", "-y", "-i", str(REF_AUDIO), "-filter_complex", fc,
                    "-map", "[o]", "-ar", "44100", "-c:a", "pcm_s16le", str(dest)], check=True)
    return dest


def render(frames: list[Path], sound: Path, dest: Path) -> None:
    """Каждый слайд — ровно своё число кадров (склейка точно в кадр удара, без дрейфа concat-демультиплексора)."""
    marks = [round(t * FPS) for t in CUTS] + [round(END * FPS)]
    ins, fc = [], []
    for k, f in enumerate(frames):
        ins += ["-loop", "1", "-framerate", str(FPS), "-i", str(f)]
        fc.append(f"[{k}:v]trim=end_frame={marks[k + 1] - marks[k]},setpts=PTS-STARTPTS[s{k}]")
    n = len(frames)
    fc.append("".join(f"[s{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0,format=yuv420p,{SET_SDR}[v]")
    subprocess.run([FF, "-v", "error", "-y", *ins, "-i", str(sound), "-filter_complex", ";".join(fc),
                    "-map", "[v]", "-map", f"{n}:a", "-c:a", "aac", "-b:a", "192k",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "27", "-maxrate", "6M",
                    "-bufsize", "12M", "-profile:v", "high", *SDR_COLOR_ARGS, "-t", str(END), "-movflags", "+faststart",
                    "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
                    "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=",
                    str(dest)], check=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("--id", default="noid")
    ap.add_argument("--seed", type=int, default=1390)
    ap.add_argument("--test", action="store_true", help="2 ролика + QA-лист в output/1390_test")
    ap.add_argument("--short", action="store_true", help="≤ 8 с: все слайды на доли 2/4, подпись + App Store на последних ~2 с")
    ap.add_argument("--exclude", type=Path, action="append", default=[],
                    help="manifest.json уже выданной партии — её сочетания не повторяем (можно несколько)")
    ap.add_argument("--start", type=int, default=1, help="номер первого ролика (продолжение нумерации прошлой партии)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    global CUTS, END
    if a.short:
        CUTS, END = SHORT_CUTS, SHORT_END
    ps = pools()
    n = 2 if a.test else a.n
    out = a.out or ROOT / "output" / (("1390_test" if a.test else f"1390_{n}") + ("_8s" if a.short else ""))
    exclude = {combo_key(m["slides"]) for f in a.exclude for m in json.loads(f.read_text(encoding="utf-8"))}
    work = out / "_frames"
    work.mkdir(parents=True, exist_ok=True)
    sound = (music(ROOT / "output" / "_work" / "1390_music_8s_bass1st.wav", SHORT_START) if a.short
             else music(ROOT / "output" / "_work" / "1390_music_bars.wav"))
    manifest = []
    global JIT
    for i, v in enumerate(plan(n, ps, random.Random(a.seed), exclude), a.start):
        JIT = random.Random(a.seed * 1000 + i)
        frames, qa = [], []
        for k, ((slot, text), photos) in enumerate(zip(SLIDES, v)):
            im, boxes = cover(photos[0], text) if k == 0 else collage(photos[0], photos[1], text, k >= CAPTION_FROM,
                                                                                    card=k >= CAPTION_FROM if a.short
                                                                                    else k == len(SLIDES) - 1)
            for b in boxes:
                bad = check_box(W, H, b)
                if bad:
                    raise SystemExit(f"{i:03d} слайд {k + 1}: текст вне безопасной зоны {b} — {bad}")
            f = work / f"{i:03d}_{k + 1}.png"
            im.save(f)
            frames.append(f)
            if a.test:
                q = draw_overlay(im.copy())
                for b in boxes:
                    ImageDraw.Draw(q).rectangle(b, outline=(255, 200, 0), width=4)
                qa.append(q.resize((270, 480)))
        dest = out / f"{i:03d}_{a.id}.mp4"
        render(frames, sound, dest)
        manifest.append({"video": dest.name, "slides": [[p.name for p in t] for t in v]})
        if a.test:
            sheet = Image.new("RGB", (270 * len(qa), 480), "white")
            for k, q in enumerate(qa):
                sheet.paste(q, (k * 270, 0))
            sheet.save(out / f"_qa_{i:03d}.jpg", quality=86)
        print(f"  {dest.name}", flush=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"готово: {n} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
