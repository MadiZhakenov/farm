#!/usr/bin/env python3
"""
Безопасные зоны под интерфейс TikTok / Instagram / YouTube Shorts — для ВСЕХ проектов
(карусели, рилсы, фото-посты). Откуда цифры и правила — docs/SAFE_ZONES.md.

  from core.safe_zones import zone_for, check_box, draw_overlay
  z = zone_for(1080, 1440)            # рамка для холста (по пропорциям: 3:4, 4:5, 9:16)
  check_box(1080, 1440, (x0, y0, x1, y1))   # [] — ок, иначе список нарушений
  draw_overlay(img)                   # копия кадра: красное = интерфейс, зелёная рамка = текст

  python core/safe_zones.py out/_text/*.png    # проверить PNG-оверлеи с прозрачностью
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw


@dataclass(frozen=True)
class Zone:
    """Доли холста: рамка для текста (x0, y0, x1, y1) и прямоугольники интерфейса для QA."""
    name: str
    ratio: float                                    # ширина / высота
    text: tuple[float, float, float, float]
    blocked: tuple[tuple[float, float, float, float], ...]


ZONES = {
    "3:4": Zone("карусель 3:4", 3 / 4, (180 / 1080, 0.06, 900 / 1080, 0.78),
                ((926 / 1080, 0.46, 1.0, 1.0),      # колонка кнопок TikTok
                 (0.0, 0.80, 1.0, 1.0),             # подпись/точки (длинное описание, Инста, Shorts)
                 (0.86, 0.0, 1.0, 0.07))),          # счётчик «1/6» в Инсте
    "4:5": Zone("карусель 4:5", 4 / 5, (180 / 1080, 0.06, 900 / 1080, 0.78),
                ((926 / 1080, 0.46, 1.0, 1.0), (0.0, 0.80, 1.0, 1.0), (0.86, 0.0, 1.0, 0.07))),
    "9:16": Zone("рилс / фото 9:16", 9 / 16, (140 / 1080, 200 / 1920, 940 / 1080, 1540 / 1920),
                 ((0.0, 0.0, 1.0, 200 / 1920),        # вкладки TikTok / шапка Reels
                  (0.0, 1540 / 1920, 1.0, 1.0),       # ник + подпись + музыка
                  (940 / 1080, 0.45, 1.0, 1540 / 1920))),  # колонка лайк/коммент/шер
}


def zone_for(w: int, h: int) -> Zone:
    """Ближайший по пропорциям формат."""
    return min(ZONES.values(), key=lambda z: abs(z.ratio - w / h))


def text_rect(w: int, h: int) -> tuple[int, int, int, int]:
    """Рамка для текста в пикселях холста."""
    x0, y0, x1, y1 = zone_for(w, h).text
    return round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)


def check_box(w: int, h: int, box: tuple[int, int, int, int]) -> list[str]:
    """box = (x0, y0, x1, y1) текстового блока в пикселях; [] — всё внутри рамки."""
    fx0, fy0, fx1, fy1 = text_rect(w, h)
    x0, y0, x1, y1 = box
    out = []
    if y0 < fy0:
        out.append(f"сверху: y0={y0} < {fy0}")
    if y1 > fy1:
        out.append(f"снизу: y1={y1} > {fy1}")
    if x0 < fx0:
        out.append(f"слева: x0={x0} < {fx0}")
    if x1 > fx1:
        out.append(f"справа: x1={x1} > {fx1}")
    return out


def check_overlay(png: Image.Image | str | Path) -> list[str]:
    """PNG-оверлей во весь кадр с прозрачностью: проверяем рамку всех непрозрачных пикселей."""
    im = png if isinstance(png, Image.Image) else Image.open(png)
    bbox = im.convert("RGBA").getchannel("A").point(lambda a: 255 if a > 10 else 0).getbbox()
    return check_box(im.width, im.height, bbox) if bbox else []


def draw_overlay(img: Image.Image) -> Image.Image:
    """Копия кадра с зонами интерфейса (красное) и рамкой для текста (зелёная) — для QA-листов."""
    w, h = img.size
    out = img.convert("RGB").copy()
    d = ImageDraw.Draw(out, "RGBA")
    for x0, y0, x1, y1 in zone_for(w, h).blocked:
        d.rectangle([x0 * w, y0 * h, x1 * w, y1 * h], fill=(255, 0, 0, 90))
    d.rectangle(text_rect(w, h), outline=(0, 255, 0, 255), width=max(2, w // 200))
    return out


if __name__ == "__main__":
    bad = 0
    for p in sys.argv[1:]:
        v = check_overlay(p)
        if v:
            bad += 1
            print(p, "; ".join(v))
    print(f"проверено {len(sys.argv) - 1}, с нарушениями {bad}")
