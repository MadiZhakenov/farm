#!/usr/bin/env python3
"""
Global Work, карусель «Best websites to find jobs in 2026» (реф TikTok @lil.careerhacks 7598249996072389906),
айди пока нет. 7 слайдов 1080×1440 (3:4). Тексты слайдов 1, 3–7 — дословно с рефа (те же переносы строк),
слайд 2 — Globalwork.ai (текст из ТЗ). Фото креатора: downloads/gw_carousel/src.

Стиль как в рефе (TikTok-текст): заголовок — белый на синей плашке, текст — чёрный на белых плашках по
строкам («лесенка»), обложка — чёрный на белых + жёлтая подпись с коричневой обводкой и тенью.
Всё внутри безопасной зоны 3:4 (docs/SAFE_ZONES.md) и мимо лиц.

  python build_gw_sites_carousel.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import check_box, text_rect  # noqa: E402

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

SRC = ROOT / "downloads" / "gw_carousel" / "src"
OUT = ROOT / "output" / "gw_sites_carousel"
ID = "noid"   # айди проекта пока нет; имена sort_<слайд>_<карусель>_<id>.jpg
W, H = 1080, 1440
FONT = ROOT / "fonts" / "TikTokSans-SemiBold.ttf"
FONT_YEL = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf" / "TikTokSans12pt-BlackItalic.ttf"
BLUE, YELLOW = (36, 68, 177), (254, 241, 92)
YEL_SHADOW, YEL_EDGE = (206, 92, 56), (40, 28, 10)   # замер рефа: оранжевая «тень» и тонкий тёмный контур
X0, Y0, X1, Y1 = text_rect(W, H)          # 180, 86, 900, 1123
MAX_W = X1 - X0

# (фото, кадрирование (x0, y0, x1, y1) в долях исходника или None — по центру)
PHOTOS = {
    1: ("IMG_1234.png", None),                 # лифт (как в рефе), заголовок под лицом
    2: ("IMG_2972.jpg", None),                 # ноут с открытым globalwork.ai
    3: ("IMG_2940.jpg", None),                 # рука на колене (как №3 в рефе)
    4: ("IMG_6640.jpg", None),                 # ноут (как №4)
    5: ("IMG_8661.jpg", None),                 # лифт, текст под лицом
    6: ("IMG_7354.png", (0.27, 0.0, 0.835, 1.0)),   # стол у окна (горизонтальное → 3:4)
    7: ("IMG_4333.jpg", (0.455, 0.0, 1.0, 0.545)),  # небо и башня без лица (как улица в №7)
}

COVER_TITLE = ["Best websites to find", "jobs in 2026"]
COVER_SUB = ["(before they hit", "linkedin & indeed)"]
SLIDES = {
    2: ("Globalwork.ai", None,  # текст из ТЗ дословно, переносы — автоматически
        "GlobalWork.ai makes job hunting so much easier. Instead of spending hours scrolling through LinkedIn and "
        "applying to hundreds of jobs, AI finds positions that actually match your experience, tailors your resume, "
        "and helps automate applications. You save hours of work and focus on opportunities where you have a real "
        "chance of getting hired. Definitely worth trying in 2026."),
    3: ("Wellfound (AngelList Talent)", [
        "Wellfound remains the quiet entry", "point for early-stage and Series A", "startups.",
        "Founders and small teams prefer", "posting here first because they want", "targeted applicants, not volume. This",
        "means you often see positions days,", "sometimes weeks before they", "appear on LinkedIn. If you want to",
        "break into startups, this is where the", "earliest signals show up."], None),
    4: ("InternshipsHQ.com", [
        "InternshipsHQ is one of the few", "platforms where internship listings", "aren’t buried under irrelevant jobs.",
        "Companies post here early in the hiring", "cycle, often before promoting roles on",
        "their main careers page. Students and", "early-career job seekers get access at", "the exact moment teams begin",
        "reviewing candidates.", "If you want a real shot at summer roles,", "this site gives you time no other",
        "platform does."], None),
    5: ("YC Jobs", [
        "Y Combinator companies hire", "aggressively in Q1 and Q2, posting", "roles on YC Jobs before anywhere",
        "else. These roles move fast, and", "applying early dramatically increases", "your chance of a human read. YC",
        "teams often hire based on clarity and", "speed, not pedigree, which makes",
        "early applicants especially competitive.", "If you want modern, growth-focused",
        "roles, this board is pure signal."], None),
    6: ("InterviewPal Jobs", [
        "InterviewPal’s job section is built", "differently from traditional job boards.",
        "You’re not just seeing early listings you", "can also preview role alignment",
        "through ATS scanning and pull real", "interview questions asked by recruiters", "for that job family.",
        "This makes you both early and better", "prepared than other applicants.",
        "It’s a rare combination: discover the", "role early, and walk in with insider-level", "prep."], None),
    7: ("Remotive", [
        "Remotive remains one of the most", "reliable places to find serious", "remote roles early. Distributed",
        "teams often post here first to avoid", "drowning in unqualified LinkedIn", "applications.",
        "The roles tend to be better curated,", "clearer, and more aligned with", "remote-first culture. If you’re",
        "targeting remote work in 2026, this", "platform consistently beats the", "larger boards."], None),
}
# вертикальная раскладка: (центр заголовка, верх текста, низ текста) — мимо лиц (лифт: лицо 270–650 px)
LAYOUT = {2: (300, 420, Y1), 3: (300, 420, Y1), 4: (260, 380, Y1), 5: (150, 655, Y1), 6: (300, 420, Y1),
          7: (300, 420, Y1)}
BODY_PX, HEAD_PX = 40, 48           # кегль рефа; уменьшается, если не влезает в безопасную зону
LINE, PAD, RAD = 1.32, 0.42, 0.26   # шаг строк, поле по бокам, скругление (в долях кегля)


def font(px: int, path: Path = FONT) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), px)


def plate(lines: list[str], px: int, fill, ink) -> Image.Image:
    """Строки на плашках, слитых «лесенкой» со скруглёнными углами (как фон текста в TikTok)."""
    ss = 3
    f = font(px * ss)
    lh, pad, r = int(LINE * px * ss), int(PAD * px * ss), int(RAD * px * ss)
    widths = [f.getlength(t) for t in lines]
    cw, ch = int(max(widths) + 2 * pad + 4 * r), lh * len(lines) + 4 * r
    mask = np.zeros((ch, cw), np.uint8)
    for k, w in enumerate(widths):
        x0 = int((cw - w) / 2 - pad)
        mask[2 * r + k * lh:2 * r + (k + 1) * lh, x0:x0 + int(w + 2 * pad)] = 255
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    mask = cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kern), cv2.MORPH_OPEN, kern)
    img = Image.new("RGBA", (cw, ch), fill + (0,))
    img.putalpha(Image.fromarray(mask))
    d = ImageDraw.Draw(img)
    for k, t in enumerate(lines):
        d.text((cw / 2, 2 * r + (k + 0.5) * lh), t, font=f, fill=ink + (255,), anchor="mm")
    img = img.resize((cw // ss, ch // ss), Image.Resampling.LANCZOS)
    return img.crop(img.getbbox())


def fit_plate(lines: list[str], px: int, fill, ink, max_h: int | None = None) -> Image.Image:
    while True:
        p = plate(lines, px, fill, ink)
        if (p.width <= MAX_W and (max_h is None or p.height <= max_h)) or px <= 20:
            return p
        px -= 1


def wrap(text: str, px: int, max_w: int) -> list[str]:
    """Перенос по словам с выравниванием длины строк (для текста из ТЗ)."""
    f, words = font(px), text.split()
    def greedy(limit):
        lines, cur = [], ""
        for w in words:
            cand = (cur + " " + w).strip()
            if cur and f.getlength(cand) > limit:
                lines.append(cur)
                cur = w
            else:
                cur = cand
        return lines + [cur]
    best = greedy(max_w)
    for lim in range(max_w - 10, int(max_w * 0.6), -10):
        c = greedy(lim)
        if len(c) > len(best):
            break
        best = c
    return best


def yellow(lines: list[str], px: int) -> Image.Image:
    """Жёлтая подпись как на обложке рефа: жёлтые буквы с тонким тёмным контуром, под ними сдвинутая вниз-вправо
    оранжевая копия (тоже с тонким контуром) — объёмный «3D»-эффект."""
    ss = 3
    f = font(px * ss, FONT_YEL)
    lh, sw, off = int(1.12 * px * ss), max(2, int(0.045 * px * ss)), int(0.085 * px * ss)
    cw = int(max(f.getlength(t) for t in lines) + 6 * sw + 2 * off)
    ch = lh * len(lines) + 6 * sw + 2 * off
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for layer, (dx, fill) in enumerate(((off, YEL_SHADOW), (0, YELLOW))):
        for k, t in enumerate(lines):
            x, y = cw / 2 - off / 2 + dx, 3 * sw + (k + 0.5) * lh + dx
            d.text((x, y), t, font=f, fill=fill + (255,), anchor="mm", stroke_width=sw, stroke_fill=YEL_EDGE + (255,))
    img = img.resize((cw // ss, ch // ss), Image.Resampling.LANCZOS)
    return img.crop(img.getbbox())


def background(n: int) -> Image.Image:
    name, crop = PHOTOS[n]
    im = ImageOps.exif_transpose(Image.open(SRC / name)).convert("RGB")
    if crop:
        w, h = im.size
        im = im.crop((int(crop[0] * w), int(crop[1] * h), int(crop[2] * w), int(crop[3] * h)))
    im = ImageOps.fit(im, (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    return grade(im, n)


# ---- тон «как в рефе»: светлее, мягче, приглушённые цвета (замер LAB по слайдам рефа без плашек) ----
REF_DIR = ROOT / "downloads" / "gw_carousel" / "ref"


def ref_stats(n: int) -> tuple[np.ndarray, np.ndarray]:
    r = np.asarray(Image.open(REF_DIR / f"dom_{n}.jpg").convert("RGB"))
    plates = (r.min(2) > 225) | ((r[..., 2] > 140) & (r[..., 0] < 90))
    keep = ~(cv2.dilate(plates.astype(np.uint8), np.ones((25, 25), np.uint8)) > 0)
    v = cv2.cvtColor(r, cv2.COLOR_RGB2LAB).astype(np.float32)[keep]
    return v.mean(0), v.std(0)


def grade(im: Image.Image, n: int) -> Image.Image:
    """Яркость — гаммой к средней яркости слайда рефа с тем же номером (светлые места не выбиваются),
    цвет — приглушаем разброс a/b до рефа и сдвигаем оттенок к рефу наполовину."""
    lab = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2LAB).astype(np.float32)
    (rl, ra, rb), (_sl, sa, sb) = ref_stats(n)
    L = lab[..., 0] / 255
    target = min(max(rl, lab[..., 0].mean()), 150) / 255       # только осветляем, не темним
    lo, hi = 0.3, 1.6
    for _ in range(30):                                          # подбор гаммы бинпоиском
        g = (lo + hi) / 2
        lo, hi = (g, hi) if (L ** g).mean() > target else (lo, g)
    lab[..., 0] = (L ** g) * 255
    for c, (rm, rs) in ((1, (ra, sa)), (2, (rb, sb))):
        m, sd = lab[..., c].mean(), lab[..., c].std()
        k = float(np.clip(rs / max(sd, 1e-3), 0.55, 1.0))
        lab[..., c] = (lab[..., c] - m) * k + m + (rm - m) * 0.5
    return Image.fromarray(cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB))


def put(canvas: Image.Image, block: Image.Image, cx: float, top: float, boxes: list) -> None:
    x, y = int(cx - block.width / 2), int(top)
    canvas.alpha_composite(block, (x, y))
    boxes.append((x, y, x + block.width, y + block.height))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    cx = (X0 + X1) / 2
    # единый кегль текста для всех слайдов — по самой широкой строке рефа
    ref_lines = [ln for _h, lines, _t in SLIDES.values() if lines for ln in lines]
    body_px = BODY_PX
    while plate(ref_lines, body_px, (255, 255, 255), (0, 0, 0)).width > MAX_W:
        body_px -= 1
    print("кегль текста", body_px)
    for n in range(1, 8):
        canvas = background(n).convert("RGBA")
        boxes: list = []
        if n == 1:
            t = fit_plate(COVER_TITLE, 78, (255, 255, 255), (0, 0, 0))
            put(canvas, t, cx, 585, boxes)
            # ширина подписи — как в рефе: 0.63 ширины заголовка (493 / 786 px)
            spx = int(t.height / len(COVER_TITLE) * 0.62)
            while yellow(COVER_SUB, spx).width > 0.63 * t.width and spx > 20:
                spx -= 1
            s = yellow(COVER_SUB, spx)
            put(canvas, s, cx, 585 + t.height + 30, boxes)
        else:
            head, lines, text = SLIDES[n]
            hy, top, bottom = LAYOUT[n]
            hp = fit_plate([head], HEAD_PX, BLUE, (255, 255, 255))
            put(canvas, hp, cx, hy - hp.height / 2, boxes)
            if lines is None:
                widest = max(font(body_px).getlength(ln) for ln in ref_lines)
                lines = wrap(text, body_px, int(widest))
            px = body_px
            while True:
                bp = plate(lines, px, (255, 255, 255), (0, 0, 0))
                if top + bp.height <= bottom or px <= 22:
                    break
                px -= 1
            put(canvas, bp, cx, top, boxes)
            if px != body_px:
                print(f"слайд {n}: текст уменьшен до {px}px, чтобы не закрыть лицо")
        bad = [v for b in boxes for v in check_box(W, H, b)]
        if bad:
            print(f"слайд {n}: вне безопасной зоны → {bad}")
        canvas.convert("RGB").save(OUT / f"sort_{n}_1_{ID}.jpg", quality=95)
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
