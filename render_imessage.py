#!/usr/bin/env python3
"""
«Скриншот» переписки iMessage (тёмная тема iOS) для слайдов каруселей.

  python render_imessage.py --script chat.txt --out chat.png [--h 1440]

Сценарий:
  @ Linda               имя контакта в шапке
  # Today 6:12 PM       строка времени по центру
  me: текст             синий справа
  them: текст           серый слева
  ! Read 6:15 PM        подпись под последним своим сообщением
Ширина 1080 (как скрин iPhone, ужатый до 1080), высота по --h (обрезка снизу,
как обрезанный скриншот).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw

import build_text_story as T

W = 1080
SS = 4  # рисуем в 4x и уменьшаем — гладкие изгибы хвостиков
FONT_PX = 47          # 17 pt @ 3x, ужато до 1080
PAD_X, PAD_Y = 33, 19
LINE_GAP = 1.2
GAP_SAME, GAP_SWITCH = 6, 22
SIDE = 26
MAX_W = 0.70 * W
STATUS_H, HEADER_H = 150, 230
C_BG = (0, 0, 0, 255)
C_HEADER = (22, 22, 24, 255)
C_ME = (10, 132, 255, 255)
C_THEM = (38, 38, 41, 255)
C_TEXT = (255, 255, 255, 255)
C_GRAY = (142, 142, 147, 255)
C_BLUE = (10, 132, 255, 255)


def parse(path: Path):
    name, rows = "Contact", []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("@"):
            name = line[1:].strip()
        elif line.startswith("#"):
            rows.append(("time", line[1:].strip()))
        elif line.startswith("!"):
            rows.append(("receipt", line[1:].strip()))
        else:
            m = re.match(r"(?i)^(me|them)\s*:\s*(.+)$", line)
            if not m:
                raise SystemExit(f"не понял строку: {raw!r}")
            rows.append((m.group(1).lower(), m.group(2).strip()))
    return name, rows


def status_bar(img: Image.Image, s: int, clock: str) -> None:
    d = ImageDraw.Draw(img)
    T.draw_text(img, 96 * s, 52 * s, clock, 44 * s)
    x, y = (W - 240) * s, 66 * s
    for i, h in enumerate((12, 18, 24, 30)):  # сигнал
        d.rounded_rectangle((x + i * 15 * s, y + (30 - h) * s, x + i * 15 * s + 10 * s, y + 30 * s), radius=2 * s, fill=C_TEXT)
    wx, wy = x + 85 * s, y + 31 * s  # wi-fi
    for r, wd in ((30, 6), (19, 6), (8, 8)):
        d.arc((wx - r * s, wy - r * s - 6 * s, wx + r * s, wy + r * s - 6 * s), 225, 315, fill=C_TEXT, width=wd * s)
    bx = x + 130 * s  # батарея
    d.rounded_rectangle((bx, y + 2 * s, bx + 56 * s, y + 30 * s), radius=8 * s, outline=(120, 120, 124, 255), width=3 * s)
    d.rounded_rectangle((bx + 5 * s, y + 7 * s, bx + 38 * s, y + 25 * s), radius=4 * s, fill=C_TEXT)
    d.rounded_rectangle((bx + 59 * s, y + 11 * s, bx + 63 * s, y + 21 * s), radius=2 * s, fill=(120, 120, 124, 255))


def header(img: Image.Image, s: int, name: str) -> None:
    d = ImageDraw.Draw(img)
    d.rectangle((0, STATUS_H * s, W * s, (STATUS_H + HEADER_H) * s), fill=C_HEADER)
    d.line((0, (STATUS_H + HEADER_H) * s, W * s, (STATUS_H + HEADER_H) * s), fill=(48, 48, 52, 255), width=2 * s)
    cx, cy = W * s / 2, (STATUS_H + 78) * s
    av = 120 * s
    a = Image.new("RGBA", (av, av), (0, 0, 0, 0))
    ga = ImageDraw.Draw(a)
    for yy in range(av):
        t = yy / av
        c = tuple(int(p + (q - p) * t) for p, q in zip((168, 170, 178), (120, 122, 130))) + (255,)
        ga.line((0, yy, av, yy), fill=c)
    m = Image.new("L", (av, av), 0)
    ImageDraw.Draw(m).ellipse((0, 0, av - 1, av - 1), fill=255)
    circ = Image.new("RGBA", (av, av), (0, 0, 0, 0))
    circ.paste(a, (0, 0), m)
    img.alpha_composite(circ, (int(cx - av / 2), int(cy - av / 2)))
    init = name.strip()[0].upper()
    ipx = 58 * s
    T.draw_text(img, cx - T.text_w(init, ipx) / 2, cy - ipx * 0.62, init, ipx)
    npx = 34 * s
    nw = T.text_w(name, npx)
    ny = (STATUS_H + 150) * s
    T.draw_text(img, cx - nw / 2 - 8 * s, ny, name, npx)
    gx, gy = cx + nw / 2 + 4 * s, ny + npx * 0.62
    d.line([(gx, gy - 9 * s), (gx + 7 * s, gy), (gx, gy + 9 * s)], fill=C_GRAY, width=3 * s)
    bx, by = 40 * s, cy
    d.line([(bx + 20 * s, by - 26 * s), (bx, by), (bx + 20 * s, by + 26 * s)], fill=C_BLUE, width=7 * s, joint="curve")
    vx1 = (W - 44) * s
    vx0 = vx1 - 66 * s
    d.rounded_rectangle((vx0, cy - 19 * s, vx0 + 44 * s, cy + 19 * s), radius=8 * s, outline=C_BLUE, width=5 * s)
    d.polygon([(vx0 + 48 * s, cy - 4 * s), (vx1, cy - 16 * s), (vx1, cy + 16 * s), (vx0 + 48 * s, cy + 4 * s)],
              outline=C_BLUE, width=5 * s)


def tail(d: ImageDraw.ImageDraw, x: float, yb: float, right: bool, color, s: int, r: float) -> None:
    """Хвостик iMessage (как в CSS-вёрстке): цветная капля у угла + вырез цветом фона.
    Высота не больше радиуса угла пузыря — иначе у однострочного пузыря
    капля залезает на закругление верхнего угла и даёт уступ."""
    f = 2.4 * s
    th = min(25 * f, r)
    if right:
        d.rounded_rectangle((x - 13 * f, yb - th, x + 7 * f, yb), radius=16 * f,
                            corners=(False, False, False, True), fill=color)
        d.rounded_rectangle((x + 1, yb - th, x + 26 * f, yb), radius=10 * f,
                            corners=(False, False, False, True), fill=C_BG)
    else:
        d.rounded_rectangle((x - 7 * f, yb - th, x + 13 * f, yb), radius=16 * f,
                            corners=(False, False, True, False), fill=color)
        d.rounded_rectangle((x - 26 * f, yb - th, x - 1, yb), radius=10 * f,
                            corners=(False, False, True, False), fill=C_BG)


def input_bar(img: Image.Image, s: int, height: int) -> None:
    """Низ экрана iOS: «+», поле «iMessage» с микрофоном, полоска «домой»."""
    d = ImageDraw.Draw(img)
    top = (height - 230) * s
    d.rectangle((0, top, W * s, height * s), fill=C_BG)
    cy = top + 70 * s
    # кнопка «+»
    d.ellipse((30 * s, cy - 42 * s, 114 * s, cy + 42 * s), fill=(44, 44, 46, 255))
    d.line((72 * s, cy - 18 * s, 72 * s, cy + 18 * s), fill=(152, 152, 157, 255), width=6 * s)
    d.line((54 * s, cy, 90 * s, cy), fill=(152, 152, 157, 255), width=6 * s)
    # поле ввода
    d.rounded_rectangle((136 * s, cy - 46 * s, (W - 30) * s, cy + 46 * s), radius=46 * s,
                        outline=(58, 58, 60, 255), width=3 * s, fill=C_BG)
    ppx = 44 * s
    T.draw_text(img, 170 * s, cy - ppx * 0.6, "iMessage", ppx, fill=(99, 99, 102, 255))
    # микрофон
    mx = (W - 82) * s
    d.rounded_rectangle((mx - 10 * s, cy - 24 * s, mx + 10 * s, cy + 6 * s), radius=10 * s, fill=(99, 99, 102, 255))
    d.arc((mx - 18 * s, cy - 14 * s, mx + 18 * s, cy + 18 * s), 0, 180, fill=(99, 99, 102, 255), width=4 * s)
    d.line((mx, cy + 18 * s, mx, cy + 26 * s), fill=(99, 99, 102, 255), width=4 * s)
    # полоска «домой»
    hb = (height - 30) * s
    d.rounded_rectangle(((W / 2 - 140) * s, hb - 6 * s, (W / 2 + 140) * s, hb + 6 * s), radius=6 * s,
                        fill=(255, 255, 255, 255))


def render(script: Path, out: Path, height: int, clock: str, full: bool = False) -> None:
    s = SS
    name, rows = parse(script)
    img = Image.new("RGBA", (W * s, height * s), C_BG)
    d = ImageDraw.Draw(img)
    y = (STATUS_H + HEADER_H + 26) * s
    msgs = [i for i, r in enumerate(rows) if r[0] in ("me", "them")]
    prev = None
    for i, (kind, text) in enumerate(rows):
        if kind == "time":
            spx = 30 * s
            label = text
            T.draw_text(img, W * s / 2 - T.text_w(label, spx) / 2, y + 10 * s, label, spx, fill=C_GRAY)
            y += 64 * s
            prev = None
            continue
        if kind == "receipt":
            rpx = 30 * s
            T.draw_text(img, (W - SIDE - 8) * s - T.text_w(text, rpx), y + 6 * s, text, rpx, fill=C_GRAY)
            y += 48 * s
            continue
        px = FONT_PX * s
        lines = T.wrap(text, px, MAX_W * s - 2 * PAD_X * s)
        lh = round(px * LINE_GAP)
        bw = int(max(T.text_w(ln, px) for ln in lines) + 2 * PAD_X * s)
        bh = int(lh * len(lines) + 2 * PAD_Y * s)
        if prev is not None:
            y += (GAP_SAME if prev == kind else GAP_SWITCH) * s
        right = kind == "me"
        bx1 = (W - SIDE) * s if right else SIDE * s + bw
        bx0 = bx1 - bw
        color = C_ME if right else C_THEM
        nxt = next((rows[j][0] for j in range(i + 1, len(rows)) if rows[j][0] in ("me", "them", "time")), None)
        r = min(bh / 2, (px * LINE_GAP + 2 * PAD_Y * s) / 2)
        has_tail = nxt != kind
        # угол под хвостиком прямой — одна фигура, без шва
        corners = (True, True, not (has_tail and right), not (has_tail and not right))
        d.rounded_rectangle((bx0, y, bx1, y + bh), radius=r, corners=corners, fill=color)
        if has_tail:
            tail(d, bx1 if right else bx0, y + bh, right, color, s, r)
        ty = y + PAD_Y * s
        for ln in lines:
            T.draw_text(img, bx0 + PAD_X * s, ty, ln, px)
            ty += lh
        y += bh
        prev = kind
    # шапка и статус-бар поверх (как в iOS — сообщения уходят под них)
    if full:
        input_bar(img, s, height)
    header(img, s, name)
    d.rectangle((0, 0, W * s, STATUS_H * s), fill=C_HEADER)
    status_bar(img, s, clock)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.resize((W, height), Image.Resampling.LANCZOS).convert("RGB").save(out, quality=95)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--h", type=int, default=1440)
    ap.add_argument("--clock", default="6:21")
    ap.add_argument("--full", action="store_true", help="весь экран iPhone 1080×2340 со строкой ввода")
    a = ap.parse_args()
    render(a.script, a.out, 2340 if a.full else a.h, a.clock, a.full)
    print("готово →", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
