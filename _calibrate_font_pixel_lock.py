#!/usr/bin/env python3
"""Pixel-lock TikTok typography vs ammyeyelash reference 3.jpg."""

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

LINES = [
    "So over hyped I didn't see",
    "any growth in my lashes,",
    "but it made my eyes super",
    "itchy and I had to stop",
    "using it after a while",
]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    orig = Image.open(SRC).convert("RGB")
    W, H = orig.size
    print("orig", W, H)
    arr = np.asarray(orig)

    y0, y1 = 940, 1340
    x0, x1 = 190, 980
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
    print("glyph px", int(glyph.sum()))

    rh, rw = glyph.shape

    fonts = [
        ROOT / "fonts" / "TikTokSans-Bold.ttf",
        ROOT
        / "fonts"
        / "TikTokSans"
        / "TikTokSans-v4.000"
        / "fonts"
        / "ttf"
        / "TikTokSans36pt-Bold.ttf",
        ROOT
        / "fonts"
        / "TikTokSans"
        / "TikTokSans-v4.000"
        / "fonts"
        / "ttf"
        / "TikTokSans24pt-Bold.ttf",
        ROOT
        / "fonts"
        / "TikTokSans"
        / "TikTokSans-v4.000"
        / "fonts"
        / "ttf"
        / "TikTokSans18pt-Bold.ttf",
        ROOT
        / "fonts"
        / "TikTokSans"
        / "TikTokSans-v4.000"
        / "fonts"
        / "ttf"
        / "TikTokSans12pt-Bold.ttf",
        ROOT / "fonts" / "Montserrat-Bold.ttf",
    ]
    fonts = [f for f in fonts if f.is_file()]
    print("fonts", [f.name for f in fonts])

    def score_render(
        font_path: Path,
        size: int,
        stroke: int,
        gap: int,
        y_off: int = 0,
        x_off: int = 0,
    ):
        font = ImageFont.truetype(str(font_path), size)
        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        line_hs: list[int] = []
        line_ws: list[int] = []
        for ln in LINES:
            bb = probe.textbbox((0, 0), ln, font=font, stroke_width=stroke)
            line_ws.append(bb[2] - bb[0])
            line_hs.append(bb[3] - bb[1])
        lh = max(line_hs)
        advance = lh + gap
        block_h = lh * len(LINES) + gap * (len(LINES) - 1)
        layer = Image.new("L", (rw, rh), 0)
        d = ImageDraw.Draw(layer)
        y = (rh - block_h) // 2 + y_off
        cx = rw // 2 + x_off
        for ln in LINES:
            bb = probe.textbbox((0, 0), ln, font=font, stroke_width=stroke)
            lw = bb[2] - bb[0]
            x = cx - lw // 2 - bb[0]
            d.text(
                (x, y - bb[1]),
                ln,
                font=font,
                fill=255,
                stroke_width=stroke,
                stroke_fill=255,
            )
            y += advance
        pred = np.asarray(layer) > 40
        tp = int((pred & glyph).sum())
        fp = int((pred & ~glyph).sum())
        fn = int((~pred & glyph).sum())
        uni = tp + fp + fn
        iou = tp / uni if uni else 0.0
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        return f1, iou, prec, rec, pred

    best = None
    for fp in fonts:
        for size in range(56, 73):
            for stroke in (3, 4, 5, 6):
                for gap in range(6, 16):
                    for y_off in range(-20, 25, 5):
                        f1, iou, prec, rec, pred = score_render(
                            fp, size, stroke, gap, y_off=y_off
                        )
                        tup = (f1, iou, prec, rec, size, stroke, gap, y_off, 0, fp, pred)
                        if best is None or tup[:2] > best[:2]:
                            best = tup

    assert best is not None
    print(
        "COARSE",
        dict(
            zip(
                ["f1", "iou", "prec", "rec", "size", "stroke", "gap", "y_off", "x_off", "font"],
                [*best[:9], best[9].name],
            )
        ),
    )

    bf1, biou, bp, br, bsz, bst, bgap, by, bx, bfp, bpred = best
    best2 = best
    for size in range(bsz - 2, bsz + 3):
        for stroke in range(max(2, bst - 1), bst + 2):
            for gap in range(max(4, bgap - 2), bgap + 3):
                for y_off in range(by - 4, by + 5):
                    for x_off in range(-6, 7, 2):
                        f1, iou, prec, rec, pred = score_render(
                            bfp, size, stroke, gap, y_off=y_off, x_off=x_off
                        )
                        tup = (
                            f1,
                            iou,
                            prec,
                            rec,
                            size,
                            stroke,
                            gap,
                            y_off,
                            x_off,
                            bfp,
                            pred,
                        )
                        if tup[:2] > best2[:2]:
                            best2 = tup

    f1, iou, prec, rec, size, stroke, gap, y_off, x_off, fp, pred = best2
    print(
        "FINE",
        dict(
            zip(
                ["f1", "iou", "prec", "rec", "size", "stroke", "gap", "y_off", "x_off", "font"],
                [f1, iou, prec, rec, size, stroke, gap, y_off, x_off, fp.name],
            )
        ),
    )

    # red overlay on crop
    crop_rgb = orig.crop((x0, y0, x1, y1)).convert("RGBA")
    ours = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
    font = ImageFont.truetype(str(fp), size)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    line_hs = []
    for ln in LINES:
        bb = probe.textbbox((0, 0), ln, font=font, stroke_width=stroke)
        line_hs.append(bb[3] - bb[1])
    lh = max(line_hs)
    advance = lh + gap
    block_h = lh * len(LINES) + gap * (len(LINES) - 1)
    d = ImageDraw.Draw(ours)
    y = (rh - block_h) // 2 + y_off
    cx = rw // 2 + x_off
    for ln in LINES:
        bb = probe.textbbox((0, 0), ln, font=font, stroke_width=stroke)
        lw = bb[2] - bb[0]
        x = cx - lw // 2 - bb[0]
        d.text(
            (x, y - bb[1]),
            ln,
            font=font,
            fill=(255, 40, 40, 230),
            stroke_width=stroke,
            stroke_fill=(0, 0, 0, 255),
        )
        y += advance
    bg = Image.new("RGBA", (rw, rh), (40, 30, 50, 255))
    faded = crop_rgb.copy()
    faded.putalpha(160)
    comp = Image.alpha_composite(Image.alpha_composite(bg, faded), ours)
    comp.convert("RGB").save(OUT / "_font_pixel_overlay_red.jpg", quality=95)

    # diff map: red=ours only, green=ref only, blue=overlap
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

    # full 1080 overlay
    from core.renderer import SLIDE_H, SLIDE_W, cover_resize

    base = cover_resize(orig).convert("RGBA")
    canvas = Image.new("RGBA", (SLIDE_W, SLIDE_H), (25, 25, 35, 255))
    faded_full = base.copy()
    faded_full.putalpha(150)
    canvas = Image.alpha_composite(canvas, faded_full)

    scale = 1080 / W
    size1080 = max(1, int(round(size * scale)))
    # stroke often needs to stay integer-thick; prefer measured round
    stroke1080 = max(1, int(round(stroke * scale)))
    if stroke1080 < 3 and stroke >= 4:
        stroke1080 = 4  # keep readable outline at 1080
    gap1080 = max(1, int(round(gap * scale)))
    print("scaled1080", size1080, stroke1080, gap1080)

    font2 = ImageFont.truetype(str(fp), size1080)
    layer2 = Image.new("RGBA", (SLIDE_W, SLIDE_H), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(layer2)
    probe2 = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lhs = []
    for ln in LINES:
        bb = probe2.textbbox((0, 0), ln, font=font2, stroke_width=stroke1080)
        lhs.append(bb[3] - bb[1])
    lh = max(lhs)
    adv = lh + gap1080
    y = int(SLIDE_H * 0.62)
    cx = SLIDE_W // 2
    for ln in LINES:
        bb = probe2.textbbox((0, 0), ln, font=font2, stroke_width=stroke1080)
        lw = bb[2] - bb[0]
        x = cx - lw // 2 - bb[0]
        d2.text(
            (x, y - bb[1]),
            ln,
            font=font2,
            fill=(255, 255, 255, 255),
            stroke_width=stroke1080,
            stroke_fill=(0, 0, 0, 255),
        )
        y += adv
    Image.alpha_composite(canvas, layer2).convert("RGB").save(
        OUT / "_font_pixel_overlay_1080.jpg", quality=95
    )

    lock = {
        "font": fp.name,
        "font_path": str(fp.relative_to(ROOT)).replace("\\", "/"),
        "orig_res": [W, H],
        "size_orig": size,
        "stroke_orig": stroke,
        "gap_orig": gap,
        "y_off": y_off,
        "x_off": x_off,
        "size_1080": size1080,
        "stroke_1080": stroke1080,
        "gap_1080": gap1080,
        "LINE_HEIGHT_RATIO": round(1.0 + gap / size, 4),
        "LINE_HEIGHT_RATIO_1080": round(1.0 + gap1080 / max(1, size1080), 4),
        "f1": round(float(f1), 4),
        "iou": round(float(iou), 4),
        "prec": round(float(prec), 4),
        "rec": round(float(rec), 4),
    }
    (OUT / "_font_lock.json").write_text(
        json.dumps(lock, indent=2), encoding="utf-8"
    )
    print("LOCK", json.dumps(lock, indent=2))


if __name__ == "__main__":
    main()
