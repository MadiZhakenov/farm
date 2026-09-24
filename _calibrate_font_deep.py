#!/usr/bin/env python3
"""Faster pixel-lock: pick best font/weight first, then refine params."""

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
TTF = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf"
VAR = (
    ROOT
    / "fonts"
    / "TikTokSans"
    / "TikTokSans-v4.000"
    / "fonts"
    / "variable"
    / "TikTokSans[opsz,slnt,wdth,wght].ttf"
)

LINES = [
    "So over hyped I didn't see",
    "any growth in my lashes,",
    "but it made my eyes super",
    "itchy and I had to stop",
    "using it after a while",
]


def load_glyph():
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
    return glyph, (y0, y1, x0, x1), arr


def score(pred, glyph):
    tp = int((pred & glyph).sum())
    fp = int((pred & ~glyph).sum())
    fn = int((~pred & glyph).sum())
    uni = tp + fp + fn
    iou = tp / uni if uni else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return f1, iou, prec, rec


def get_font(path: Path, size: int, variations: dict | None = None):
    font = ImageFont.truetype(str(path), size)
    if variations and hasattr(font, "set_variation_by_axes"):
        try:
            # axis order from font name: opsz, slnt, wdth, wght
            font.set_variation_by_axes(
                [
                    float(variations.get("opsz", 36)),
                    float(variations.get("slnt", 0)),
                    float(variations.get("wdth", 100)),
                    float(variations.get("wght", 700)),
                ]
            )
        except Exception as e:
            print("var fail", path.name, e)
    return font


def render_pred(
    fp: Path,
    size: int,
    stroke: int,
    gap: int,
    rw: int,
    rh: int,
    *,
    shadow=(0, 0),
    variations=None,
):
    font = get_font(fp, size, variations)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lhs = [
        probe.textbbox((0, 0), ln, font=font, stroke_width=stroke)[3]
        - probe.textbbox((0, 0), ln, font=font, stroke_width=stroke)[1]
        for ln in LINES
    ]
    lh = max(lhs)
    adv = lh + gap
    bh = lh * 5 + gap * 4
    layer = Image.new("L", (rw, rh), 0)
    d = ImageDraw.Draw(layer)
    y = (rh - bh) // 2
    cx = rw // 2
    sdx, sdy = shadow
    for ln in LINES:
        bb = probe.textbbox((0, 0), ln, font=font, stroke_width=stroke)
        x = cx - (bb[2] - bb[0]) // 2 - bb[0]
        yy = y - bb[1]
        if sdx or sdy:
            d.text(
                (x + sdx, yy + sdy),
                ln,
                font=font,
                fill=255,
                stroke_width=stroke,
                stroke_fill=255,
            )
        d.text(
            (x, yy), ln, font=font, fill=255, stroke_width=stroke, stroke_fill=255
        )
        y += adv
    return np.asarray(layer) > 40


def best_roll(pred, glyph, dy_range=range(-10, 11), dx_range=(-4, -2, 0, 2, 4)):
    best = None
    for dy in dy_range:
        for dx in dx_range:
            shifted = np.roll(np.roll(pred, dy, 0), dx, 1)
            f1, iou, prec, rec = score(shifted, glyph)
            t = (f1, iou, dx, dy, prec, rec, shifted)
            if best is None or t[:2] > best[:2]:
                best = t
    return best


def main():
    glyph, box, arr = load_glyph()
    rh, rw = glyph.shape
    print("glyph", int(glyph.sum()))

    fonts: list[tuple[str, Path, dict | None]] = [
        ("root-Bold", ROOT / "fonts" / "TikTokSans-Bold.ttf", None),
        ("root-SemiBold", ROOT / "fonts" / "TikTokSans-SemiBold.ttf", None),
    ]
    for opsz in (12, 16, 36):
        for w in ("SemiBold", "Bold", "ExtraBold", "Black"):
            p = TTF / f"TikTokSans{opsz}pt-{w}.ttf"
            if p.is_file():
                fonts.append((f"{opsz}-{w}", p, None))
    if VAR.is_file():
        for wght in (650, 700, 750, 800, 850, 900):
            for opsz in (14, 18, 24, 36):
                fonts.append(
                    (f"var-{opsz}-{wght}", VAR, {"opsz": opsz, "wght": wght})
                )

    # Phase 1: font bake-off at known-good 64/4/11
    print("Phase1 fonts", len(fonts))
    phase1 = []
    for label, fp, var in fonts:
        pred = render_pred(fp, 64, 4, 11, rw, rh, variations=var)
        f1, iou, dx, dy, prec, rec, _ = best_roll(pred, glyph)
        phase1.append((f1, iou, label, fp, var, dx, dy, prec, rec))
        print(f"  {label:20s} f1={f1:.4f} iou={iou:.4f}")
    phase1.sort(reverse=True)
    print("TOP5", [(round(x[0], 4), x[2]) for x in phase1[:5]])

    # Phase 2: refine top 3 fonts
    best = None
    for _, _, label, fp, var, _, _, _, _ in phase1[:3]:
        for size in range(60, 69):
            for stroke in (3, 4, 5, 6):
                for gap in range(8, 15):
                    for shadow in ((0, 0), (1, 1), (2, 2), (2, 3), (3, 3), (1, 2)):
                        pred = render_pred(
                            fp, size, stroke, gap, rw, rh, shadow=shadow, variations=var
                        )
                        f1, iou, dx, dy, prec, rec, shifted = best_roll(
                            pred, glyph, range(-8, 9), (-2, 0, 2)
                        )
                        t = (
                            f1,
                            iou,
                            label,
                            size,
                            stroke,
                            gap,
                            shadow,
                            dx,
                            dy,
                            fp,
                            var,
                            prec,
                            rec,
                            shifted,
                        )
                        if best is None or t[:2] > best[:2]:
                            best = t
                            print(
                                "new",
                                round(f1, 4),
                                label,
                                size,
                                stroke,
                                gap,
                                shadow,
                            )

    assert best is not None
    # Phase 3: fine
    label, size, stroke, gap, shadow, fp, var = (
        best[2],
        best[3],
        best[4],
        best[5],
        best[6],
        best[9],
        best[10],
    )
    best2 = best
    for size2 in range(size - 1, size + 2):
        for stroke2 in range(max(2, stroke - 1), stroke + 2):
            for gap2 in range(max(5, gap - 2), gap + 3):
                for sh in [
                    (shadow[0] + a, shadow[1] + b)
                    for a in (-1, 0, 1)
                    for b in (-1, 0, 1)
                    if shadow[0] + a >= 0 and shadow[1] + b >= 0
                ]:
                    pred = render_pred(
                        fp, size2, stroke2, gap2, rw, rh, shadow=sh, variations=var
                    )
                    f1, iou, dx, dy, prec, rec, shifted = best_roll(
                        pred, glyph, range(-6, 7), range(-3, 4)
                    )
                    t = (
                        f1,
                        iou,
                        label,
                        size2,
                        stroke2,
                        gap2,
                        sh,
                        dx,
                        dy,
                        fp,
                        var,
                        prec,
                        rec,
                        shifted,
                    )
                    if t[:2] > best2[:2]:
                        best2 = t

    best = best2
    (
        f1,
        iou,
        label,
        size,
        stroke,
        gap,
        shadow,
        dx,
        dy,
        fp,
        var,
        prec,
        rec,
        pred,
    ) = best
    print(
        "FINAL",
        {
            "f1": round(f1, 4),
            "iou": round(iou, 4),
            "prec": round(prec, 4),
            "rec": round(rec, 4),
            "label": label,
            "size": size,
            "stroke": stroke,
            "gap": gap,
            "shadow": shadow,
            "align": (dx, dy),
        },
    )

    # visuals
    OUT.mkdir(exist_ok=True)
    Image.fromarray(
        np.stack(
            [
                np.where(pred & ~glyph, 255, 0).astype(np.uint8),
                np.where(glyph & ~pred, 255, 0).astype(np.uint8),
                np.where(pred & glyph, 200, 0).astype(np.uint8),
            ],
            axis=-1,
        )
    ).save(OUT / "_font_pixel_diff.jpg", quality=95)

    y0, y1, x0, x1 = box
    W = arr.shape[1]
    scale = 1080 / W
    size1080 = int(round(size * scale))
    stroke1080 = max(4, int(round(stroke * scale))) if stroke >= 4 else max(3, int(round(stroke * scale)))
    gap1080 = max(1, int(round(gap * scale)))
    sh1080 = (int(round(shadow[0] * scale)), int(round(shadow[1] * scale)))

    # red overlay
    crop = Image.fromarray(arr[y0:y1, x0:x1]).convert("RGBA")
    font = get_font(fp, size, var)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lhs = [
        probe.textbbox((0, 0), ln, font=font, stroke_width=stroke)[3]
        - probe.textbbox((0, 0), ln, font=font, stroke_width=stroke)[1]
        for ln in LINES
    ]
    lh = max(lhs)
    adv = lh + gap
    bh = lh * 5 + gap * 4
    ours = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
    d = ImageDraw.Draw(ours)
    y = (rh - bh) // 2 + dy
    cx = rw // 2 + dx
    for ln in LINES:
        bb = probe.textbbox((0, 0), ln, font=font, stroke_width=stroke)
        x = cx - (bb[2] - bb[0]) // 2 - bb[0]
        yy = y - bb[1]
        if shadow[0] or shadow[1]:
            d.text(
                (x + shadow[0], yy + shadow[1]),
                ln,
                font=font,
                fill=(0, 0, 0, 230),
                stroke_width=stroke,
                stroke_fill=(0, 0, 0, 230),
            )
        d.text(
            (x, yy),
            ln,
            font=font,
            fill=(255, 40, 40, 200),
            stroke_width=stroke,
            stroke_fill=(0, 0, 0, 255),
        )
        y += adv
    faded = crop.copy()
    faded.putalpha(170)
    bg = Image.new("RGBA", (rw, rh), (25, 18, 35, 255))
    Image.alpha_composite(Image.alpha_composite(bg, faded), ours).convert("RGB").save(
        OUT / "_font_pixel_overlay_red.jpg", quality=95
    )

    from core.renderer import SLIDE_H, SLIDE_W, cover_resize

    orig = Image.open(SRC).convert("RGB")
    base = cover_resize(orig).convert("RGBA")
    canvas = Image.new("RGBA", (SLIDE_W, SLIDE_H), (25, 25, 35, 255))
    faded_full = base.copy()
    faded_full.putalpha(150)
    canvas = Image.alpha_composite(canvas, faded_full)
    font2 = get_font(fp, size1080, var)
    layer2 = Image.new("RGBA", (SLIDE_W, SLIDE_H), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(layer2)
    probe2 = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lhs = [
        probe2.textbbox((0, 0), ln, font=font2, stroke_width=stroke1080)[3]
        - probe2.textbbox((0, 0), ln, font=font2, stroke_width=stroke1080)[1]
        for ln in LINES
    ]
    lh = max(lhs)
    adv = lh + gap1080
    y = int(SLIDE_H * ((y0 + (rh - bh) // 2 + dy) / arr.shape[0]))
    for ln in LINES:
        bb = probe2.textbbox((0, 0), ln, font=font2, stroke_width=stroke1080)
        x = SLIDE_W // 2 - (bb[2] - bb[0]) // 2 - bb[0]
        if sh1080[0] or sh1080[1]:
            d2.text(
                (x + sh1080[0], y - bb[1] + sh1080[1]),
                ln,
                font=font2,
                fill=(0, 0, 0, 255),
                stroke_width=stroke1080,
                stroke_fill=(0, 0, 0, 255),
            )
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

    try:
        rel = str(fp.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        rel = str(fp)
    lock = {
        "label": label,
        "font_path": rel,
        "variations": var,
        "size_orig": size,
        "stroke_orig": stroke,
        "gap_orig": gap,
        "shadow_dx": shadow[0],
        "shadow_dy": shadow[1],
        "align_dx": dx,
        "align_dy": dy,
        "size_1080": size1080,
        "stroke_1080": stroke1080,
        "gap_1080": gap1080,
        "shadow_dx_1080": sh1080[0],
        "shadow_dy_1080": sh1080[1],
        "LINE_HEIGHT_RATIO": round(1.0 + gap / size, 4),
        "LINE_HEIGHT_RATIO_1080": round(1.0 + gap1080 / max(1, size1080), 4),
        "f1": round(float(f1), 4),
        "iou": round(float(iou), 4),
        "prec": round(float(prec), 4),
        "rec": round(float(rec), 4),
    }
    (OUT / "_font_lock.json").write_text(json.dumps(lock, indent=2), encoding="utf-8")
    print("LOCK", json.dumps(lock, indent=2))


if __name__ == "__main__":
    main()
