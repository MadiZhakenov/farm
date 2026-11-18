#!/usr/bin/env python3
"""
ESSENHERB (Bubble Essence) — карусель 7 слайдов 3:4 (1080×1440) по рефу @emma_teatips/photo/7614604795164364045
(«things I did to finally have that “glow up”»): слайды 1–2 — фото девушки «до/после» с маленьким белым текстом
TikTok с чёрной обводкой; 3–6 — пастельный «крашеный» фон (розовый сверху → бежевый снизу, мазки кисти), на нём
вырезанные предметы и фото-карточки, текст рядом; 7 — фото (флакон у зеркала, героиня на заднем плане).
Тексты ТЗ — дословно, переносы по смыслу; текст — только в безопасной рамке 3:4 (core.safe_zones).

Картинки: downloads/essenherb/items (предметы на белом фоне → вырезка заливкой от краёв), product (флакон),
photos/ (кадры Flow: s1_before, s2_after, s6_palm, s7_final — когда будут), placeholder/ (заглушки для теста).

  python build_essenherb.py --test 3          # → output/_work/essenherb/test (+ _cutouts.jpg, _test.jpg)
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from scipy import ndimage

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402  (Apple-эмодзи в строке)
from core import renderer as R  # noqa: E402  (шрифт TikTok)
from core.safe_zones import check_box  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402

W, H = 1080, 1440
D = ROOT / "downloads" / "essenherb"
ITEMS, PHOTOS, PLACE = D / "items", D / "photos", D / "placeholder"
WORK = ROOT / "output" / "_work" / "essenherb"

# ТЗ дословно, переносы по смыслу
TEXTS = {
    1: ["things I did to finally have that", "“glow up”"],
    2: ["trust me, I know ball."],
    3: ["washing my makeup brushes", "instead of pretending", "they’re “still clean” 😭"],
    4: ["a simple hairstyle + tiny earrings.", "suddenly the whole look", "makes sense."],
    5: ["giving my skincare a minute", "before going straight in", "with foundation.", "less rushing,",
        "more getting ready."],
    6: ["the little bubble step", "before makeup 🤍", "ESSENHERB Bubble Essence"],
    7: ["the goal: feeling good", "before i even leave the house."],
}
# предметы: файл → (кроп в долях кадра или None, белый порог для фона)
CUT = {
    "brushes": [("brushes_1.jpg", None)],
    "towel": [("towel_1.jpg", None)],
    "comb": [("comb_1.jpg", None)],
    "earrings": [("earrings_1.jpg", (0.1, 0.3, 0.9, 0.85), True)],      # True — убрать фон и внутри колец
    "mirror": [("mirror_61WPTvuAuqS.jpg", None), ("mirror_71YojYNOLlL._AC_UF894,1000_QL80_.jpg", None)],
    "sponge": [("sponge_2.png", None)],
    "timer": [("hourglass_51x1S5l-bfL.jpg", None)],                     # песочные часы: у таймера был логотип
    "bottle": [("bottle_off2.jpg", None, False, 1)],                    # фон ровно 248 — допуск 1, иначе съедает белую помпу
}
CARDS = {"hair": ["hair_1.jpg", "hair_2.jpg"], "palm": ["palm_1.jpg"]}


# ---------------- картинки ----------------
def cutout(path: Path, crop=None, holes: bool = False, tol: int = 10) -> Image.Image:
    """Предмет на (почти) ровном светлом фоне → RGBA: фон = связная с краями область цвета фона (±tol), края мягкие;
    holes — и замкнутые участки цвета фона крупнее 0.2 % кадра (внутри колец серёг)."""
    im = Image.open(path)
    if im.mode == "RGBA" and im.getextrema()[3][0] < 250:
        out = im
    else:
        im = ImageOps.exif_transpose(im).convert("RGB")
        if crop:
            w, h = im.size
            im = im.crop((int(crop[0] * w), int(crop[1] * h), int(crop[2] * w), int(crop[3] * h)))
        a = np.asarray(im, np.int16)
        edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
        bgc = np.median(edge, axis=0)
        near = (np.abs(a - bgc).max(-1) <= tol)
        lab, _ = ndimage.label(near)
        border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
        bg = np.isin(lab, list(border))
        if holes:                                    # внутри колец фон в тени — светлый серый, а не цвет края
            light = (a.min(-1) > 200) & (a.max(-1) - a.min(-1) < 18) & ~bg
            hl, _ = ndimage.label(light)
            sizes = ndimage.sum(light, hl, index=np.arange(hl.max() + 1))
            bg |= np.isin(hl, [i for i in np.nonzero(sizes > 0.002 * light.size)[0] if i != 0])
        fg = ndimage.binary_opening(~bg, iterations=1)
        fl, nfl = ndimage.label(fg)                  # мелкие обрывки (край листьев и т. п.) — прочь
        if nfl > 1:
            sz = ndimage.sum(fg, fl, index=np.arange(nfl + 1))
            fg = np.isin(fl, [i for i in range(1, nfl + 1) if sz[i] >= 0.002 * fg.size])   # тонкие кисти — оставить
        alpha = fg.astype(np.uint8) * 255
        am = Image.fromarray(alpha).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
        out = im.convert("RGBA")
        out.putalpha(am)
    bb = out.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    return out.crop(bb) if bb else out


def card(path: Path, size: tuple[int, int], rng: random.Random, radius: int = 28) -> Image.Image:
    """Фото-карточка: кроп по центру под размер, скруглённые углы."""
    im = ImageOps.fit(ImageOps.exif_transpose(Image.open(path)).convert("RGB"), size, Image.Resampling.LANCZOS,
                      centering=(0.5, rng.uniform(0.35, 0.5)))
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    out = im.convert("RGBA")
    out.putalpha(m)
    return out


def background(rng: random.Random) -> Image.Image:
    """Пастельный «крашеный» фон рефа: розовый сверху → бежевый снизу, горизонтальные мазки кисти."""
    top = np.array([rng.uniform(238, 248), rng.uniform(160, 182), rng.uniform(172, 192)])
    mid = np.array([rng.uniform(242, 250), rng.uniform(196, 210), rng.uniform(196, 208)])
    bot = np.array([rng.uniform(222, 232), rng.uniform(218, 226), rng.uniform(186, 200)])
    y = np.linspace(0, 1, H)[:, None]
    k = rng.uniform(0.5, 0.65)
    col = np.where(y < k, top + (mid - top) * (y / k), mid + (bot - mid) * ((y - k) / (1 - k)))
    img = np.repeat(col[:, None, :], W, axis=1)
    # мазки кисти: длинные горизонтальные полосы разной светлоты (шум, растянутый по горизонтали и размытый),
    # мягко — без «помех» (тест 17.11: частые полосы выглядели как сбой картинки)
    g = np.random.default_rng(rng.randrange(10 ** 9))
    for rows, cols, amp in ((H // 22, 5, 5.0), (H // 9, 9, 2.2)):
        n = g.normal(0, 1, (rows, cols)).astype(np.float32)
        n = ndimage.gaussian_filter(np.asarray(Image.fromarray(n, "F").resize((W, H), Image.Resampling.BICUBIC)), 3)
        img += n[..., None] * amp
    img += g.normal(0, 1.2, (H, W, 1))                         # лёгкое зерно бумаги
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def text_layer(lines: list[str], px: int, cx: int, top: int) -> Image.Image:
    """Белый TikTok-текст с ровной тонкой чёрной обводкой (как в рефе), строки по центру cx, эмодзи Apple."""
    font = R._load_font(px)
    st = max(2, round(px * 0.07))
    asc, _ = font.getmetrics()
    adv = round(px * 1.18)
    e_px = A._emoji_px(px)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        runs = [(k, c) for k, c in A._tokenize_runs(ln) if c]
        lw = sum(e_px * 1.08 if k == "emoji" else font.getlength(c) for k, c in runs)
        x, base = cx - lw / 2, top + i * adv + asc
        for k, c in runs:
            if k == "emoji":
                e = A._apple_emoji_rgba(c, e_px)
                if e is not None:
                    img.alpha_composite(e, (int(x), int(base - e_px * 0.84)))
                x += e_px * 1.08
            else:
                d.text((x, base), c, font=font, anchor="ls", fill=(255, 255, 255, 255), stroke_width=st,
                       stroke_fill=(0, 0, 0, 255))
                x += font.getlength(c)
    return img


def place_text(im: Image.Image, lines: list[str], px: int, cx: int, top: int, slide: int) -> tuple:
    lay = text_layer(lines, px, cx, top)
    box = lay.getbbox()
    while box[2] - box[0] > 712 and px > 30:                         # шире рамки — мельче
        px -= 2
        lay = text_layer(lines, px, cx, top)
        box = lay.getbbox()
    dx = max(0, 184 - box[0]) - max(0, box[2] - 896)                 # сдвиг внутрь рамки x 180–900 (с запасом 4)
    dy = max(0, 90 - box[1]) - max(0, box[3] - round(H * 0.78) + 4)  # и y 6–78 %
    if dx or dy:
        cx += dx
        top += dy
        lay = text_layer(lines, px, cx, top)
        box = lay.getbbox()
    if bad := check_box(W, H, box):
        raise SystemExit(f"слайд {slide}: текст вне безопасной зоны {box}: {bad}")
    im.alpha_composite(add_shadow(lay, blur=4, opacity=0.25, offset=(0, 2), grow=1, pad=0))
    return box


def put(im: Image.Image, obj: Image.Image, cx: int, cy: int, max_side: int, rng: random.Random, rot: float = 8.0,
        shadow: bool = True) -> tuple:
    """Предмет: масштаб по большей стороне, лёгкий наклон, мягкая тень; центр (cx, cy)."""
    s = max_side / max(obj.size)
    o = obj.resize((max(1, round(obj.width * s)), max(1, round(obj.height * s))), Image.Resampling.LANCZOS)
    o = o.rotate(rng.uniform(-rot, rot), Image.Resampling.BICUBIC, expand=True)
    x, y = cx - o.width // 2, cy - o.height // 2
    if shadow:
        sh = add_shadow(o, blur=14, opacity=0.28, offset=(0, 10), grow=1, pad=40)
        im.alpha_composite(sh, (x - 40, y - 40))
    else:
        im.alpha_composite(o, (x, y))
    return x, y, x + o.width, y + o.height


# ---------------- слайды ----------------
def photo_slide(path: Path, slide: int, rng: random.Random) -> Image.Image:
    im = ImageOps.fit(ImageOps.exif_transpose(Image.open(path)).convert("RGB"), (W, H), Image.Resampling.LANCZOS,
                      centering=(0.5, 0.4)).convert("RGBA")
    lines = TEXTS[slide]
    px = 40
    top = rng.randint(930, 990) - (len(lines) - 1) * 24
    place_text(im, lines, px, W // 2 + rng.randint(-10, 10), top, slide)
    return im


def collage(slide: int, rng: random.Random, cut: dict) -> Image.Image:
    im = background(rng)
    j = lambda v: v + rng.randint(-25, 25)                               # noqa: E731
    lines = TEXTS[slide]
    if slide == 3:                       # кисти сверху слева, полотенце снизу справа, текст между
        put(im, cut["brushes"], j(360), j(380), 660, rng, rot=6)
        put(im, cut["towel"], j(720), j(1130), 600, rng, rot=5)
        place_text(im, lines, 44, j(560), j(760), slide)
    elif slide == 4:                     # расчёска, фото причёски, серьги; текст посередине
        hair = card(ITEMS / rng.choice(CARDS["hair"]), (420, 560), rng)
        put(im, hair, j(760), j(390), 560, rng, rot=4)
        put(im, cut["comb"], j(290), j(380), 560, rng, rot=12)
        put(im, cut["earrings"], j(540), j(1150), 440, rng, rot=6)
        place_text(im, lines, 44, j(540), j(800), slide)
    elif slide == 5:                     # зеркало сверху, текст под ним, спонж и песочные часы внизу по краям
        put(im, cut["mirror"], j(540), j(340), 560, rng, rot=3)
        put(im, cut["sponge"], j(270), j(1190), 330, rng, rot=15)
        put(im, cut["timer"], j(820), 1185 + rng.randint(0, 25), 400, rng, rot=4)
        place_text(im, lines, 44, j(540), 665 + rng.randint(-10, 10), slide)
    elif slide == 6:                     # флакон слева крупно, пузырьки на ладони — карточка справа, текст снизу
        put(im, cut["bottle"], j(320), j(500), 780, rng, rot=4)
        palm = card(PHOTOS / "s6_palm.jpg" if (PHOTOS / "s6_palm.jpg").exists() else ITEMS / CARDS["palm"][0],
                    (440, 560), rng)
        put(im, palm, j(790), j(470), 560, rng, rot=5)
        place_text(im, lines, 44, j(560), j(960), slide)
    return im


# ---------------- фото-коллаж (юзер 17.11: вырезки «неэстетичные» → живые эстетичные фото, мудборд) ----------------
PINS = D / "pins"
# живые фото (Pinterest/Pexels/Unsplash, без ИИ-рендеров и водяных знаков): слайд → места → варианты (файл, центр кропа y)
POOLS = {
    3: {"a": [("brush_mc.jpg", 0.5)], "b": [("towel_b1.jpg", 0.5)]},
    4: {"a": [("bun_0b.jpg", 0.25)], "b": [("comb_pexels.jpg", 0.5)], "c": [("ear_ee.jpg", 0.55)]},
    5: {"a": [("mirror_px4.jpg", 0.35)], "b": [("sponge_px1.jpg", 0.55)], "c": [("hg_px1.jpg", 0.5)]},
}


def soft_bg(rng: random.Random) -> Image.Image:
    """Мягкий фон без полос: розовато-кремовый сверху → тёплый бежевый снизу, лёгкое зерно бумаги."""
    top = np.array([247, 226, 226]) + np.array([rng.uniform(-4, 4) for _ in range(3)])
    bot = np.array([241, 232, 220]) + np.array([rng.uniform(-4, 4) for _ in range(3)])
    y = np.linspace(0, 1, H)[:, None, None]
    img = np.repeat(top + (bot - top) * y, W, axis=1)
    img = img + np.random.default_rng(rng.randrange(10 ** 9)).normal(0, 1.4, (H, W, 1))
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def framed(path: Path, size: tuple[int, int], cy: float = 0.45, border: int = 14, radius: int = 22) -> Image.Image:
    """Фото в белой рамке со скруглёнными углами (как распечатанная карточка в мудборде)."""
    iw, ih = size[0] - 2 * border, size[1] - 2 * border
    im = ImageOps.fit(ImageOps.exif_transpose(Image.open(path)).convert("RGB"), (iw, ih), Image.Resampling.LANCZOS,
                      centering=(0.5, cy))
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    out.paste(Image.new("RGBA", size, (255, 255, 255, 255)), (0, 0), m)
    mi = Image.new("L", (iw, ih), 0)
    ImageDraw.Draw(mi).rounded_rectangle((0, 0, iw - 1, ih - 1), radius - border // 2, fill=255)
    out.paste(im, (border, border), mi)
    return out


def collage_photo(slide: int, rng: random.Random, cut: dict) -> Image.Image:
    im = soft_bg(rng)
    j = lambda v, d=20: v + rng.randint(-d, d)                           # noqa: E731
    pick = {k: rng.choice(v) for k, v in POOLS.get(slide, {}).items()}
    f = lambda k, size: framed(PINS / pick[k][0], size, pick[k][1])      # noqa: E731
    lines = TEXTS[slide]
    if slide == 3:                       # кисти сверху (широкая), полотенца снизу, текст в полосе между
        put(im, f("a", (700, 520)), j(450), j(350), 700, rng, rot=3)
        put(im, f("b", (520, 440)), j(600), j(1110), 520, rng, rot=3)
        place_text(im, lines, 46, j(540, 10), j(690, 8), slide)
    elif slide == 4:                     # пучок + расчёска сверху, ухо с серьгами снизу
        put(im, f("a", (470, 640)), j(320), j(410), 640, rng, rot=3)
        put(im, f("b", (400, 560)), j(790), j(360), 560, rng, rot=3)
        put(im, f("c", (520, 420)), j(560), 1175 + rng.randint(-10, 10), 520, rng, rot=3)
        place_text(im, lines, 46, j(540, 10), 745 + rng.randint(-6, 4), slide)
    elif slide == 5:                     # зеркало крупно слева, спонж и песочные часы справа столбиком, текст внизу
        put(im, f("a", (500, 660)), j(320, 12), 420 + rng.randint(-10, 10), 660, rng, rot=3)
        put(im, f("b", (330, 400)), j(800, 12), 285 + rng.randint(-8, 8), 400, rng, rot=4)
        put(im, f("c", (330, 380)), j(790, 12), 630 + rng.randint(-6, 4), 380, rng, rot=4)
        place_text(im, lines, 42, j(540, 10), 868, slide)
    elif slide == 6:                     # настоящий флакон (вырезка) + карточка пузырьков на ладони, текст снизу
        put(im, cut["bottle"], j(320), j(500), 780, rng, rot=3)
        palm = PHOTOS / "s6_palm.jpg" if (PHOTOS / "s6_palm.jpg").exists() else ITEMS / CARDS["palm"][0]
        put(im, framed(palm, (440, 580), 0.5), j(790), j(470), 580, rng, rot=3)
        place_text(im, lines, 44, j(560, 10), j(960, 8), slide)
    return im


def photo_of(name: str, fallback: str) -> Path:
    p = PHOTOS / name
    return p if p.exists() else PLACE / fallback


def vanity_placeholder(rng: random.Random, bottle: Image.Image) -> Image.Image:
    """Заглушка слайда 7 до кадра Flow: фото туалетного столика + наш флакон на столешнице."""
    im = ImageOps.fit(Image.open(PLACE / "s7_vanity.jpg").convert("RGB"), (W, H), Image.Resampling.LANCZOS).convert("RGBA")
    put(im, bottle, rng.randint(720, 790), rng.randint(640, 690), 340, rng, rot=0)
    return im


def carousel(rng: random.Random, cut_all: dict) -> list[Image.Image]:
    """Юзер 17.11: «надо генерить в основном — коллаж лишь на определённые»: 1, 2, 5, 6, 7 — кадры Flow во весь слайд,
    3 и 4 — коллажи (в ТЗ так и написано «Коллаж»). Пока кадров Flow нет — заглушки."""
    cut = {k: rng.choice(v) for k, v in cut_all.items()}
    s1 = photo_slide(photo_of("s1_before.jpg", "s1_before.jpg"), 1, rng)
    s2 = photo_slide(photo_of("s2_after.jpg", "s2_after.jpg"), 2, rng)
    make = collage_photo if STYLE == "photo" else collage
    s3, s4 = make(3, rng, cut), make(4, rng, cut)
    s5p = PHOTOS / "s5_vanity.jpg"
    s5 = photo_slide(s5p if s5p.exists() else PINS / "mirror_px4.jpg", 5, rng)
    s6p = PHOTOS / "s6_bubbles.jpg"
    if s6p.exists():
        s6 = photo_slide(s6p, 6, rng)
    else:                                                # заглушка: пена + наш флакон поверх
        s6 = ImageOps.fit(Image.open(ITEMS / CARDS["palm"][0]).convert("RGB"), (W, H), Image.Resampling.LANCZOS,
                          centering=(0.6, 0.5)).convert("RGBA")
        put(s6, cut["bottle"], 300, 520, 700, rng, rot=0)
        place_text(s6, TEXTS[6], 40, W // 2, 960, 6)
    s7p = PHOTOS / "s7_final.jpg"
    if s7p.exists():
        s7 = photo_slide(s7p, 7, rng)
    else:
        s7 = vanity_placeholder(rng, cut["bottle"])
        place_text(s7, TEXTS[7], 40, W // 2, rng.randint(940, 990), 7)
    return [s1, s2, s3, s4, s5, s6, s7]


STYLE = "photo"                                          # photo — фото-коллаж (по умолчанию), cut — вырезки как в рефе


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1711)
    ap.add_argument("--style", choices=("photo", "cut"), default="photo")
    a = ap.parse_args()
    global STYLE
    STYLE = a.style
    out = WORK / "test"
    out.mkdir(parents=True, exist_ok=True)
    cut_all = {k: [cutout(ITEMS / f, c, *rest) for f, c, *rest in v] for k, v in CUT.items()}
    # лист вырезок на розовом — проверка краёв
    sheet = Image.new("RGBA", (300 * sum(len(v) for v in cut_all.values()), 320), (240, 185, 195, 255))
    x = 0
    for v in cut_all.values():
        for o in v:
            t = o.copy()
            t.thumbnail((290, 300))
            sheet.alpha_composite(t, (x + 5, 10))
            x += 300
    sheet.convert("RGB").save(WORK / "_cutouts.jpg", quality=88)
    rng = random.Random(a.seed)
    rows = []
    for n in range(1, a.test + 1):
        slides = carousel(rng, cut_all)
        for k, s in enumerate(slides, 1):
            s.convert("RGB").save(out / f"sort_{k}_{n}_1.jpg", quality=94)
        rows.append(slides)
    S = Image.new("RGB", (270 * 7, 360 * len(rows)), "white")
    for r, slides in enumerate(rows):
        for k, s in enumerate(slides):
            S.paste(s.convert("RGB").resize((270, 360)), (270 * k, 360 * r))
    S.save(WORK / "_test.jpg", quality=88)
    print(f"тест: {a.test} каруселей → {out}; листы {WORK / '_test.jpg'}, {WORK / '_cutouts.jpg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
