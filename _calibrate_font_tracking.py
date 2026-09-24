#!/usr/bin/env python3
"""Fine pixel-lock: SemiBold + tracking + shadow vs ammyeyelash."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
SRC = (
    ROOT
    / "competitors_collection"
    / "@ammyeyelash_eyelashes_lashes_lashserum_explore_fyp_15.2Ksaves_832.5Kviews_49583373"
    / "3.jpg"
)
OUT = ROOT / "out"
FONT = ROOT / "fonts" / "TikTokSans-SemiBold.ttf"

LINES = [
    "So over hyped I didn't see",
    "any growth in my lashes,",
    "but it made my eyes super",
    "itchy and I had to stop",
    "using it after a while",
]


def load_masks():
    arr = np.asarray(Image.open(SRC).convert("RGB"))
    y0, y1, x0, x1 = 940, 1340, 190, 980
    r, g, b = [arr[y0:y1, x0:x1, i].astype(np.int16) for i in range(3)]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    white = (lum > 215) & (np.abs(r - g) < 28) & (np.abs(g - b) < 28)
    black = (r < 50) & (g < 50) & (b < 50)
    near = (
        np.asarray(
            Image.fromarray((white.astype(np.uint8) * 255)).filter(
                ImageFilter.MaxFilter(9)
            )
        )
        > 0
    )
    glyph = near & (white | black)
    return arr, (y0, y1, x0, x1), white, glyph


def score(pred, target):
    tp = int((pred & target).sum())
    fp = int((pred & ~target).sum())
    fn = int((~pred & target).sum())
    uni = tp + fp + fn
    iou = tp / uni if uni else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return f1, iou, prec, rec


def measure_line(font, text, stroke, tracking):
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    if abs(tracking) < 0.01:
        bb = probe.textbbox((0, 0), text, font=font, stroke_width=stroke)
        return bb[2] - bb[0], bb
    total = 0.0
    for i, ch in enumerate(text):
        total += font.getlength(ch)
        if i < len(text) - 1:
            total += tracking
    bb = probe.textbbox((0, 0), text, font=font, stroke_width=stroke)
    return int(round(total + 2 * stroke)), bb


def render_mask(size, stroke, gap, tracking, shadow, rw, rh, y_off=0, x_off=0):
    font = ImageFont.truetype(str(FONT), size)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    heights = []
    for ln in LINES:
        bb = probe.textbbox((0, 0), ln, font=font, stroke_width=stroke)
        heights.append(bb[3] - bb[1])
    lh = max(heights)
    adv = lh + gap
    bh = lh * len(LINES) + gap * (len(LINES) - 1)
    layer = Image.new("L", (rw, rh), 0)
    d = ImageDraw.Draw(layer)
    y = (rh - bh) // 2 + y_off
    cx = rw // 2 + x_off
    sdx, sdy = shadow

    def draw_line(draw, text, x, yy, fill=255):
        if abs(tracking) < 0.01:
            draw.text(
                (x, yy),
                text,
                font=font,
                fill=fill,
                stroke_width=stroke,
                stroke_fill=fill,
            )
            return
        cur = float(x)
        for ch in text:
            draw.text(
                (int(round(cur)), yy),
                ch,
                font=font,
                fill=fill,
                stroke_width=stroke,
                stroke_fill=fill,
            )
            cur += font.getlength(ch) + tracking

    for ln in LINES:
        lw, bb = measure_line(font, ln, stroke, tracking)
        if abs(tracking) < 0.01:
            x = cx - lw // 2 - bb[0]
            yy = y - bb[1]
        else:
            x = cx - lw // 2
            yy = y - bb[1]
        if sdx or sdy:
            draw_line(d, ln, x + sdx, yy + sdy)
        draw_line(d, ln, x, yy)
        y += adv
    return np.asarray(layer) > 40, lh, adv


def main():
    OUT.mkdir(exist_ok=True)
    arr, box, fill, glyph = load_masks()
    rh, rw = glyph.shape
    print("glyph", int(glyph.sum()), "fill", int(fill.sum()))

    best = None
    n = 0
    for size in range(64, 72):
        for stroke in (2, 3, 4):
            for gap in range(6, 14):
                for tracking in (-2.0, -1.5, -1.0, -0.5, 0.0, 0.5):
                    for shadow in ((0, 0), (0, 1), (1, 1), (1, 2), (2, 2)):
                        pred, lh, adv = render_mask(
                            size, stroke, gap, tracking, shadow, rw, rh
                        )
                        for dy in range(-6, 8):
                            for dx in (-2, -1, 0, 1, 2):
                                sh = np.roll(np.roll(pred, dy, 0), dx, 1)
                                f1g, ioug, pg, rg = score(sh, glyph)
                                f1f, iouf, pf, rf = score(sh, fill)
                                # prioritize fill (stem weight) then glyph
                                key = (f1f, f1g, ioug)
                                t = (
                                    key,
                                    f1f,
                                    f1g,
                                    ioug,
                                    size,
                                    stroke,
                                    gap,
                                    tracking,
                                    shadow,
                                    dx,
                                    dy,
                                    lh,
                                    adv,
                                    sh,
                                    pf,
                                    rf,
                                    pg,
                                    rg,
                                )
                                n += 1
                                if best is None or key > best[0]:
                                    best = t
    assert best is not None
    (
        _,
        f1f,
        f1g,
        ioug,
        size,
        stroke,
        gap,
        tracking,
        shadow,
        dx,
        dy,
        lh,
        adv,
        pred,
        pf,
        rf,
        pg,
        rg,
    ) = best
    print("trials", n)
    print(
        "BEST",
        {
            "fill_f1": round(f1f, 4),
            "glyph_f1": round(f1g, 4),
            "glyph_iou": round(ioug, 4),
            "size": size,
            "stroke": stroke,
            "gap": gap,
            "tracking": tracking,
            "shadow": shadow,
            "align": (dx, dy),
            "lh": lh,
            "adv": adv,
            "fill_prec_rec": (round(pf, 3), round(rf, 3)),
            "glyph_prec_rec": (round(pg, 3), round(rg, 3)),
        },
    )

    # fine around best
    best2 = best
    for size2 in range(size - 1, size + 2):
        for stroke2 in range(max(2, stroke - 1), stroke + 2):
            for gap2 in range(max(4, gap - 2), gap + 3):
                for tr in [tracking + d for d in (-0.25, 0, 0.25, -0.5, 0.5)]:
                    for sh in [
                        (max(0, shadow[0] + a), max(0, shadow[1] + b))
                        for a in (-1, 0, 1)
                        for b in (-1, 0, 1)
                    ]:
                        pred2, lh2, adv2 = render_mask(
                            size2, stroke2, gap2, tr, sh, rw, rh
                        )
                        for dy2 in range(dy - 2, dy + 3):
                            for dx2 in range(dx - 2, dx + 3):
                                rolled = np.roll(np.roll(pred2, dy2, 0), dx2, 1)
                                f1f2, _, pf2, rf2 = score(rolled, fill)
                                f1g2, ioug2, pg2, rg2 = score(rolled, glyph)
                                key = (f1f2, f1g2, ioug2)
                                t = (
                                    key,
                                    f1f2,
                                    f1g2,
                                    ioug2,
                                    size2,
                                    stroke2,
                                    gap2,
                                    tr,
                                    sh,
                                    dx2,
                                    dy2,
                                    lh2,
                                    adv2,
                                    rolled,
                                    pf2,
                                    rf2,
                                    pg2,
                                    rg2,
                                )
                                if key > best2[0]:
                                    best2 = t

    (
        _,
        f1f,
        f1g,
        ioug,
        size,
        stroke,
        gap,
        tracking,
        shadow,
        dx,
        dy,
        lh,
        adv,
        pred,
        pf,
        rf,
        pg,
        rg,
    ) = best2
    print(
        "FINE",
        {
            "fill_f1": round(f1f, 4),
            "glyph_f1": round(f1g, 4),
            "size": size,
            "stroke": stroke,
            "gap": gap,
            "tracking": tracking,
            "shadow": shadow,
            "align": (dx, dy),
            "lh": lh,
            "adv": adv,
        },
    )

    # overlays at orig crop
    y0, y1, x0, x1 = box
    crop = Image.fromarray(arr[y0:y1, x0:x1]).convert("RGBA")
    font = ImageFont.truetype(str(FONT), size)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    heights = [
        probe.textbbox((0, 0), ln, font=font, stroke_width=stroke)[3]
        - probe.textbbox((0, 0), ln, font=font, stroke_width=stroke)[1]
        for ln in LINES
    ]
    lh = max(heights)
    adv = lh + gap
    bh = lh * 5 + gap * 4
    ours = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
    d = ImageDraw.Draw(ours)
    y = (rh - bh) // 2 + dy
    cx = rw // 2 + dx
    sdx, sdy = shadow

    def draw_colored(text, x, yy, fill, stroke_fill):
        if abs(tracking) < 0.01:
            d.text(
                (x, yy),
                text,
                font=font,
                fill=fill,
                stroke_width=stroke,
                stroke_fill=stroke_fill,
            )
            return
        cur = float(x)
        for ch in text:
            d.text(
                (int(round(cur)), yy),
                ch,
                font=font,
                fill=fill,
                stroke_width=stroke,
                stroke_fill=stroke_fill,
            )
            cur += font.getlength(ch) + tracking

    for ln in LINES:
        lw, bb = measure_line(font, ln, stroke, tracking)
        if abs(tracking) < 0.01:
            x = cx - lw // 2 - bb[0]
        else:
            x = cx - lw // 2
        yy = y - bb[1]
        if sdx or sdy:
            draw_colored(ln, x + sdx, yy + sdy, (0, 0, 0, 240), (0, 0, 0, 240))
        draw_colored(ln, x, yy, (255, 40, 40, 210), (0, 0, 0, 255))
        y += adv

    faded = crop.copy()
    faded.putalpha(180)
    bg = Image.new("RGBA", (rw, rh), (30, 20, 40, 255))
    Image.alpha_composite(Image.alpha_composite(bg, faded), ours).convert("RGB").save(
        OUT / "_font_pixel_overlay_red.jpg", quality=95
    )

    diff = Image.fromarray(
        np.stack(
            [
                np.where(pred & ~glyph, 255, 0).astype(np.uint8),
                np.where(glyph & ~pred, 255, 0).astype(np.uint8),
                np.where(pred & glyph, 200, 0).astype(np.uint8),
            ],
            axis=-1,
        )
    )
    diff.save(OUT / "_font_pixel_diff.jpg", quality=95)

    W = arr.shape[1]
    scale = 1080 / W
    size1080 = int(round(size * scale))
    stroke1080 = max(2, int(round(stroke * scale)))
    gap1080 = max(1, int(round(gap * scale)))
    track1080 = tracking * scale
    sh1080 = (int(round(shadow[0] * scale)), int(round(shadow[1] * scale)))

    lock = {
        "font": "TikTokSans-SemiBold.ttf",
        "size_orig": size,
        "stroke_orig": stroke,
        "gap_orig": gap,
        "tracking_orig": tracking,
        "shadow_dx": shadow[0],
        "shadow_dy": shadow[1],
        "align_dx": dx,
        "align_dy": dy,
        "lh_orig": lh,
        "advance_orig": adv,
        "size_1080": size1080,
        "stroke_1080": stroke1080,
        "gap_1080": gap1080,
        "tracking_1080": round(track1080, 3),
        "shadow_dx_1080": sh1080[0],
        "shadow_dy_1080": sh1080[1],
        "LINE_ADVANCE_RATIO": round(adv / size, 6),
        "fill_f1": round(float(f1f), 4),
        "glyph_f1": round(float(f1g), 4),
        "glyph_iou": round(float(ioug), 4),
    }
    (OUT / "_font_lock.json").write_text(json.dumps(lock, indent=2), encoding="utf-8")
    print("LOCK", json.dumps(lock, indent=2))


if __name__ == "__main__":
    main()
