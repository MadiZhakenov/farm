#!/usr/bin/env python3
"""
Inspoy, ID 1 — полная карусель 7 слайдов 3:4: s1/s6/s7 — кадры Flow (downloads/inspoy_thumb/flow3), s2–s5 — колёса ткани
(build_inspoy_thumb). Текст ТЗ дословно, переносы по смыслу, TikTok-шрифт с обводкой, только в безопасной рамке; лицо и экран
телефона не закрываем. На s7 — карточка Inspoy из App Store (экран Soft Summer пока не выбран клиентом).

  python build_inspoy_thumb_full.py -n 2 --out output/inspoy_thumb_test/full
  python build_inspoy_thumb_full.py -n 100 --out output/carousels_inspoy_thumb_100 --flat output/inspoy_thumb_100
"""

from __future__ import annotations

import argparse
import itertools
import random
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_dad_trucker_carousels as DT  # noqa: E402  (vivid, frame, store_card, C.block_for)
import build_1307_carousels as P1307  # noqa: E402  (plate_block — белая плашка TikTok)
import build_inspoy_thumb as T  # noqa: E402
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402

W, H = 1080, 1440
X0, Y0, X1, Y1 = text_rect(W, H)
FLOW = ROOT / "downloads" / "inspoy_thumb" / "flow3"
NL = chr(10)
PHOTOS = {  # слайд: (файл, текст по строкам, кегль) — блок сверху безопасной рамки, тот же стиль, что у «summer?»
    1: ("Editing_photo_details_and_hand_ac46cfec.jpg",
        ["place your thumb", "on each palette and swipe.", "your skin will tell you", "your season 👇"], 50),
    6: ("Edit_photo_hand_details_805a0273.jpg",
        ["I was SO sure", "I was an autumn.", "I’ve been wearing camel", "for 5 years"], 56),
    7: ("Edit_woman_photo_appearance_98f37771.jpg",
        ["one selfie in inspoy:", "soft summer.", "the beige was washing me out", "the whole time"], 46),
}
FLOW4 = ROOT / "downloads" / "inspoy_thumb" / "flow4"
POOLS = {   # основной кадр + 3 серийных (flow4): карусели чередуют все 4 × 4 × 4 сочетания
    1: [FLOW / PHOTOS[1][0], FLOW4 / "Camera_shift_in_burst_mode_f253004c.jpg", FLOW4 / "Camera_shifted_in_burst_mode_2c901c60.jpg",
        FLOW4 / "Camera_shifted_in_burst_mode_fc58859e.jpg"],
    6: [FLOW / PHOTOS[6][0], FLOW4 / "Camera_burst_shot_variation_85eaeb15.jpg", FLOW4 / "Camera_shift_in_burst_mode_923c7ec3.jpg",
        FLOW4 / "Camera_shifting_in_burst_mode_42eb468e.jpg"],
    7: [FLOW / PHOTOS[7][0], FLOW4 / "Burst_mode_scene_camera_shift_6d228b80.jpg", FLOW4 / "Camera_shift_in_burst_mode_589bbd7e.jpg",
        FLOW4 / "Camera_shifting_in_burst_mode_1e26fd9e.jpg"],
}
CARD_CY = 0.681
DT.CARD_W = 640
EMOJI = ROOT / "assets" / "emoji_apple_64" / "1f447.png"


def text_block(lines: list[str], px: int) -> Image.Image:
    """Белый TikTok-текст с ровной чёрной обводкой, как подписи сезонов; 👇 — Apple-эмодзи в строке."""
    f = ImageFont.truetype(str(T.FONT), px)
    sw, lh = round(px * 0.085), round(px * 1.13)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    emoji = Image.open(EMOJI).convert("RGBA").resize((round(px * 1.08), round(px * 1.08)), Image.Resampling.LANCZOS)
    parts = [(s[:-1].rstrip(), True) if s.endswith("👇") else (s, False) for s in lines]
    widths = [probe.textlength(t, font=f) + (emoji.width + round(px * 0.22) if e else 0) for t, e in parts]
    im = Image.new("RGBA", (int(max(widths)) + 4 * sw, lh * len(lines) + 4 * sw), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for k, (t, e) in enumerate(parts):
        x = (im.width - widths[k]) / 2
        base = 2 * sw + k * lh + round(px * 0.95)
        d.text((x, base), t, font=f, fill=(255, 255, 255, 255), anchor="ls", stroke_width=sw, stroke_fill=(0, 0, 0, 255))
        if e:
            im.alpha_composite(emoji, (round(x + probe.textlength(t, font=f) + px * 0.22), base - round(px * 0.92)))
    return im.crop(im.getbbox())


def real_life(im: Image.Image, rng: random.Random) -> Image.Image:
    """Цвет как в жизни: убираем серо-зелёный сдвиг по белым стенам, чуть светлее, лёгкий контраст и немного насыщенности.
    Без эффекта HDR и оранжевых тонов (юзер: «цвета живыми, рил лайф»). Цвета колёс s2–s5 не трогаем."""
    a = np.asarray(im).astype(np.float32) / 255
    lum, spread = a.mean(2), a.max(2) - a.min(2)
    m = (lum > 0.55) & (spread < 0.12)
    if m.sum() > 500:
        c = a[m].mean(0)
        a *= 1 + (c.mean() / c - 1) * 0.75
    w = rng.uniform(0.0, 0.008)
    a[..., 0] *= 1 + w
    a[..., 2] *= 1 - w
    a = np.clip(a, 0, 1) ** rng.uniform(0.92, 0.95)
    a += (a * a * (3 - 2 * a) - a) * rng.uniform(0.1, 0.16)
    hsv = cv2.cvtColor(np.clip(a, 0, 1), cv2.COLOR_RGB2HSV)
    sat, hue = hsv[..., 1], hsv[..., 0]
    k = rng.uniform(0.3, 0.4) * np.where((hue < 26) | (hue > 345), 0.6, 1.0)
    t = np.clip((sat - 0.05) / 0.17, 0, 1)                         # белые стены остаются белыми, без желтизны
    hsv[..., 1] = np.clip(sat * (1 + k * (1 - sat) * t * t * (3 - 2 * t)) * (1 + 0.02 * t), 0, 1)
    out = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8))


def frame_top(src: Path, rng: random.Random) -> Image.Image:
    """Кадр 3:4 с лёгким зумом; верх закреплён, чтобы телефон и голова не уезжали вверх под текст."""
    im = Image.open(src).convert("RGB")
    z = rng.uniform(1.0, 1.04)
    w, h = im.width / z, im.height / z
    x = rng.uniform(0, im.width - w)
    return im.crop((round(x), 0, round(x + w), round(h))).resize((W, H), Image.Resampling.LANCZOS)


def plate(lines: list[str], px: int) -> Image.Image:
    im = P1307.plate_block(lines, px)
    return im.crop(im.getbbox())


def photo_slide(k: int, src: Path, rng: random.Random) -> tuple[Image.Image, list]:
    _, lines, px = PHOTOS[k]
    im = real_life(frame_top(src, rng), rng).convert("RGBA")
    block = plate(lines, px) if k == 1 else text_block(lines, px)   # s1: чёрный текст на белой плашке (юзер)
    x, y = (W - block.width) // 2, Y0 + 6
    boxes = [(x, y, x + block.width, y + block.height)]
    if k == 7:
        card = DT.store_card()
        cx, cy_ = (W - card.width) // 2, round(CARD_CY * H - card.height / 2)
        im.alpha_composite(card, (cx, cy_))
        boxes.append((cx, cy_, cx + card.width, cy_ + card.height))
    im.alpha_composite(block, (x, y))
    return im.convert("RGB"), boxes


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "inspoy_thumb_test" / "full")
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_1.jpg")
    a = ap.parse_args()
    combos = list(itertools.product(*(POOLS[k] for k in (1, 6, 7))))
    random.Random(1701).shuffle(combos)
    for i in range(1, a.n + 1):
        pick = dict(zip((1, 6, 7), combos[(i - 1) % len(combos)]))
        rng = random.Random(4100 + i)
        d = a.out / f"{i:03d}"
        d.mkdir(parents=True, exist_ok=True)
        qa = []
        for k in range(1, 8):
            if k in PHOTOS:
                im, boxes = photo_slide(k, pick[k], rng)
            else:
                season = list(T.SEASONS)[k - 2]
                text, base = T.SEASONS[season]
                seed = 7100 + i * 13 + k
                colors = base[:]
                random.Random(seed).shuffle(colors)
                rgba = T.wheel(colors, seed)
                T.paper_circle(rgba, seed)
                boxes = [T.label(rgba, text)]
                im = rgba.convert("RGB")
            for b in boxes:
                if bad := check_box(W, H, b):
                    raise SystemExit(f"{i:03d} слайд {k}: вне безопасной зоны {b} — {bad}")
            im.save(d / f"{k}.jpg", quality=94)
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d / f"{k}.jpg", a.flat / f"sort_{k}_{i}_1.jpg")
            q = draw_overlay(im.copy())
            for b in boxes:
                ImageDraw.Draw(q).rectangle(b, outline=(255, 200, 0), width=4)
            qa.append(q.resize((285, 380)))
        sheet = Image.new("RGB", (285 * 7, 380))
        for k, q in enumerate(qa):
            sheet.paste(q, (k * 285, 0))
        sheet.save(a.out / f"_qa_{i:03d}.jpg", quality=86)
        print(f"  {i:03d}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
