#!/usr/bin/env python3
"""
Global Work «BAD / GOOD / AMAZING» (gw_bga2, креаторы A и B) — уникализация: по N непохожих роликов на креатора.
Собираем заново из дублей (как build_gw_bga2_reels.py), а не перекодируем готовые mp4. Каждый ролик — своё сочетание:
  формат v1 (логотипы весь ролик) / v2 (окно с записью сайта после слова уровня),
  доска с логотипами (4 стиля, 2 расстановки, 3 анимации появления; в зеркальных — BAD справа, AMAZING слева),
  субтитры (4 стиля, ВЕРХНИЙ регистр / как в ТЗ, 1–3 или 1–2 слова),
  склейки (3 схемы наездов), зеркало, скорость 0.97/1.0/1.03, цвет (5), лёгкое зерно,
  окно сайта в v2 (2 размера, 2 рамки, 3 участка записи).
Набор вариантов на креатора выбирается жадно по максимуму различий (у любых двух — несколько крупных отличий).
Тексты ТЗ дословно, раскладка по лицу креатора, всё в безопасной зоне 9:16, кодирование NVENC.

  python build_gw_bga2_uniq.py --test                  # 6 вариантов A → output/gw_bga2_uniq/_test
  python build_gw_bga2_uniq.py -n 35 --jobs 4          # A и B → output/gw_bga2_uniq/{A,B} + manifest.csv
  python build_gw_bga2_uniq.py -n 35 --tags G          # парень (output/gw_bga) → output/gw_bga_uniq
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import random
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_bga_reel as G  # noqa: E402
import build_gw_bga2_reels as B2  # noqa: E402
from core.safe_zones import check_box, text_rect  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

T = G.T
FF, W, H, FPS = G.FF, G.W, G.H, G.FPS
TAKES = B2.TAKES
G.SRC = TAKES
OUT = ROOT / "output" / "gw_bga2_uniq"
# G — первый креатор (парень, output/gw_bga): дубли IMG_2926/2930/2936 (iPhone HDR) в downloads/gw_bga/src
SRC_OF = {"A": TAKES, "B": TAKES, "G": ROOT / "downloads" / "gw_bga" / "src"}
MONTAGES = {**B2.MONTAGES, "G": ["IMG_2926", "IMG_2930", "IMG_2936"]}
OUT_OF = {"G": ROOT / "output" / "gw_bga_uniq"}
CACHE = OUT / "_cache"
TIERS = ("BAD", "GOOD", "AMAZING")
TT = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf"
JAK = ROOT / "fonts" / "ig_lookalike" / "PlusJakartaSans.ttf"
TIER_RGB = [(255, 77, 77), (255, 194, 51), (61, 220, 132)]
X0, Y0, X1, Y1 = text_rect(W, H)

# крупные измерения (по ним считаем различия) и их веса
DIMS = {"fmt": ["v1", "v2"], "board": ["mono", "color", "pills", "card"], "subs": ["mono", "stroke", "plate", "jakarta"],
        "cut": ["a", "b", "c"], "mirror": [0, 1], "speed": [0.97, 1.0, 1.03],
        "grade": ["none", "warm", "cool", "punchy", "soft"]}
WEIGHT = {"fmt": 2.0, "board": 1.5, "subs": 1.5, "cut": 1.0, "mirror": 1.0, "speed": 1.0, "grade": 1.0}
CUTS = {"a": (1.12, 0), "b": (1.10, 1), "c": (1.16, 0)}       # крупность наезда, с какого куска начинается наезд
GRADES = {"none": "", "warm": "colorbalance=rs=0.04:bs=-0.04:rm=0.03:bm=-0.03",
          "cool": "colorbalance=rs=-0.03:bs=0.04:rm=-0.02:bm=0.03", "punchy": "eq=contrast=1.07:saturation=1.12",
          "soft": "eq=contrast=0.94:saturation=0.94:brightness=0.015"}
SPREAD = {"wide": (270, 540, 810), "narrow": (300, 540, 780)}
PANELS = {"700": (700, 394), "640": (640, 360)}
PANEL_TOP, GAP = 210, 25


# ---------------- тайминги (как в build_gw_bga_reel.main, крупность — параметр) ----------------
def timeline(tag: str, cut: str) -> dict:
    zoom, z0 = CUTS[cut]
    script = [(c, t, B2.TEXT[t]) for c, t in zip(MONTAGES[tag], TIERS)]
    segs, takes, take_words, reveal, t_out, zi = [], [], [], [], 0.0, z0
    for clip, tier, text in script:
        take_start = t_out
        spoken = G.words_timed(clip)
        tier_on = spoken[0][1]
        env = T.envelope(G.SRC / f"{clip}.MOV")
        speech_end = T.bursts(env)[-1][1]
        tail = G.TAIL_LAST if clip == script[-1][0] else G.TAIL
        end = min(speech_end + tail, G.motion_onset(clip, speech_end) - 0.05, T.duration(G.SRC / f"{clip}.MOV"))
        keep = []
        for a0, b0 in T.bursts(env):
            a0, b0 = max(a0 - G.PAD_IN, tier_on - 0.15), min(b0 + G.PAD_OUT, end)
            if b0 <= tier_on - 0.15 or a0 >= end:
                continue
            if keep and a0 - keep[-1][1] < G.MAX_GAP:
                keep[-1] = (keep[-1][0], b0)
            else:
                keep.append((a0, b0))
        keep[-1] = (keep[-1][0], end)
        mapping = []
        for a0, b0 in keep:
            mapping.append((a0, b0, t_out))
            segs.append((clip, a0, b0, zoom if zi % 2 else 1.0))
            zi += 1
            t_out += b0 - a0

        def to_out(t: float, m=mapping) -> float:
            for a0, b0, o in m:
                if t < a0:
                    return o
                if t <= b0:
                    return o + t - a0
            return m[-1][2] + m[-1][1] - m[-1][0]
        words = [(tier, spoken[0][1], spoken[0][2])] + G.align(text, spoken[1:])
        take_words.append([(w, to_out(a), to_out(b)) for w, a, b in words])
        reveal.append(to_out(tier_on))
        takes.append((take_start, t_out))
    return {"segs": segs, "takes": takes, "words": take_words, "reveal": reveal, "dur": t_out, "zoom": zoom}


def chunks(words: list, max_chars: int, upper: bool) -> list[tuple[str, float, float]]:
    """G.chunks с выбором регистра (ВЕРХНИЙ или как в ТЗ) и длины куска."""
    norm = G.norm
    words = [w for w in words if norm(w[0])]
    out, cur = [[words[0]]], []
    for w in words[1:]:
        cand = " ".join(x[0] for x in cur + [w])
        if cur and (len(cand) > max_chars or len(cur) >= 3):
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[,.;:!?]$", w[0]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    for k in range(2, len(out)):
        if len(out[k]) == 1 and len(norm(out[k][0][0])) <= 4 and len(out[k - 1]) >= 3:
            out[k].insert(0, out[k - 1].pop())
    weak = {"on", "in", "is", "a", "the", "with", "of", "for", "and", "to", "your", "you"}
    for k in range(1, len(out) - 1):
        last, nxt = out[k][-1][0], out[k + 1]
        if (len(out[k]) >= 3 and norm(last) in weak and not re.search(r"[,.;:!?]$", last)
                and len(nxt) <= 2 and len(" ".join(x[0] for x in [out[k][-1]] + nxt)) <= max_chars):
            nxt.insert(0, out[k].pop())
    out = [c for c in out if c]
    res = []
    for k, c in enumerate(out):
        end = out[k + 1][0][1] if k + 1 < len(out) else c[-1][2] + 0.4
        txt = " ".join(x[0] for x in c).rstrip(".,;:!?—–-")
        res.append((txt.upper() if upper else txt, c[0][1], end))
    return res


# ---------------- графика ----------------
def tt(px: int, weight: str = "Bold", opt: str = "36pt") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(TT / f"TikTokSans{opt}-{weight}.ttf"), px)


def jak(px: int, wght: int = 800) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(JAK), px)
    f.set_variation_by_axes([wght])
    return f


def plain_text(lines: list[str], font, fill=(255, 255, 255, 255), spacing: float = 1.2, stroke: int = 0,
               colors: list | None = None) -> Image.Image:
    lh = int(font.size * spacing)
    w = int(max(font.getlength(t) for t in lines)) + 2 * stroke + 40
    h = lh * len(lines) + 2 * stroke + 40
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for k, t in enumerate(lines):
        d.text((w / 2, 20 + stroke + (k + 0.5) * lh), t, font=font, fill=(colors[k] if colors else fill), anchor="mm",
               stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    return im.crop(im.getbbox())


def shadowed(im: Image.Image, blur: float = 6, opacity: float = 0.7) -> Image.Image:
    out = add_shadow(im, blur=blur, opacity=opacity, offset=(0, 3), grow=2)
    return out.crop(out.getbbox())


def pill(text: str, color: tuple, font) -> Image.Image:
    tw = int(font.getlength(text))
    l, t, r, b = font.getbbox(text)
    ph = int(font.size * 1.5)
    im = Image.new("RGBA", (tw + 2 * 22, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, im.width - 1, ph - 1], radius=ph // 2, fill=color + (255,))
    d.text((im.width / 2, ph / 2), text, font=font, fill=(255, 255, 255, 255), anchor="mm")
    return im


def ringed(icon: Image.Image, ring: int = 5) -> Image.Image:
    s = icon.width + 2 * ring
    base = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(base).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.24), fill=(255, 255, 255, 255))
    base.alpha_composite(icon, (ring, ring))
    return base


def board_assets(style: str, spread: str) -> dict:
    cols = SPREAD[spread]
    icon_px = {"mono": 132, "color": 140, "pills": 120, "card": 124}[style]
    head_top = {"mono": 205, "color": 205, "pills": 208, "card": 232}[style]
    icons = [T.rounded(Image.open(p).convert("RGBA").resize((icon_px, icon_px), Image.Resampling.LANCZOS))
             for _n, p in G.APPS]
    if style == "pills":
        icons = [ringed(i) for i in icons]
    labels = None
    if style == "mono":
        heads = [T.glow_text([w], T.mono(G.HEAD_PX)) for w in TIERS]
        labels = [T.glow_text([n], T.mono(G.LABEL_PX, "Bold"), 1.1) for n, _p in G.APPS]
    elif style == "color":
        heads = [shadowed(plain_text([w], tt(50, "ExtraBold"), c + (255,))) for w, c in zip(TIERS, TIER_RGB)]
        labels = [shadowed(plain_text([n], tt(24, "SemiBold", "12pt")), 4, 0.8) for n, _p in G.APPS]
    elif style == "pills":
        heads = [pill(w, c, tt(34, "Bold")) for w, c in zip(TIERS, TIER_RGB)]
    else:
        heads = [plain_text([w], tt(42, "Bold")) for w in TIERS]
        labels = [plain_text([n], tt(22, "Medium", "12pt")) for n, _p in G.APPS]
    ic_h = icons[0].height
    icon_top = head_top + max(h.height for h in heads) + 14
    label_top = icon_top + ic_h + 8
    bottom = label_top + (max(l.height for l in labels) if labels else 0)
    a = {"cols": cols, "heads": heads, "icons": icons, "labels": labels, "icon": ic_h, "head_top": head_top,
         "icon_top": icon_top, "label_top": label_top, "bottom": bottom, "card": None,
         "blurred": [G.blur(i, 9) for i in icons], "blur_labels": [G.blur(l, 6) for l in labels] if labels else None}
    if style == "card":
        x0 = max(150, cols[0] - ic_h // 2 - 70)
        x1 = min(930, cols[2] + ic_h // 2 + 70)
        y0, y1 = head_top - 24, bottom + 18
        card = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
        ImageDraw.Draw(card).rounded_rectangle([0, 0, card.width - 1, card.height - 1], radius=30, fill=(0, 0, 0, 105))
        a["card"], a["card_xy"] = card, (x0, y0)
        a["bottom"] = y1
    return a


def board_layer(layer: Image.Image, a: dict, t: float, reveal: list[float], anim: str) -> None:
    if a["card"] is not None:
        layer.alpha_composite(a["card"], a["card_xy"])
    for j, cx in enumerate(a["cols"]):
        G.paste_center(layer, a["heads"][j], cx, a["head_top"])
        u = float(np.clip((t - reveal[j]) / G.REVEAL, 0, 1))
        bi = a["blurred"][j]
        G.paste_center(layer, bi, cx, a["icon_top"] - (bi.height - a["icon"]) / 2, 1 - u)
        if a["labels"]:
            bl = a["blur_labels"][j]
            G.paste_center(layer, bl, cx, a["label_top"] - (bl.height - a["labels"][j].height) / 2, 1 - u)
        if u <= 0:
            continue
        if anim == "pop":
            s, dy, al = 0.85 + 0.15 * u, 0.0, u
        elif anim == "bounce":
            s, dy, al = 1 + 0.18 * math.sin(math.pi * u), 0.0, min(1.0, 2 * u)
        else:
            s, dy, al = 1.0, 36 * (1 - u), u
        ic = a["icons"][j]
        if s != 1:
            ic = ic.resize((int(ic.width * s), int(ic.height * s)), Image.Resampling.BILINEAR)
        G.paste_center(layer, ic, cx, a["icon_top"] + (a["icon"] - ic.height) / 2 + dy, al)
        if a["labels"]:
            G.paste_center(layer, a["labels"][j], cx, a["label_top"] + dy, al)


def sub_image(style: str, text: str, tier: bool) -> Image.Image:
    if style == "mono":
        f = T.mono(G.SUB_PX)
        return T.glow_text(T.wrap(text, f, 760), f)
    if style == "stroke":
        f = tt(64, "Bold")
        return plain_text(T.wrap(text, f, 760), f, stroke=6)
    if style == "plate":
        f = tt(52, "SemiBold", "12pt")
        rows = []
        for ln in T.wrap(text, f, 680):
            l, t_, r, b = f.getbbox(ln)
            ph = int(f.size * 1.45)
            row = Image.new("RGBA", (int(f.getlength(ln)) + 48, ph), (0, 0, 0, 0))
            d = ImageDraw.Draw(row)
            d.rounded_rectangle([0, 0, row.width - 1, ph - 1], radius=16, fill=(255, 255, 255, 255))
            d.text((row.width / 2, ph / 2), ln, font=f, fill=(17, 17, 17, 255), anchor="mm")
            rows.append(row)
        im = Image.new("RGBA", (max(r.width for r in rows), sum(r.height for r in rows) + 6 * (len(rows) - 1)), (0, 0, 0, 0))
        y = 0
        for r in rows:
            im.alpha_composite(r, ((im.width - r.width) // 2, y))
            y += r.height + 6
        return im
    f = jak(62)
    lines = T.wrap(text, f, 760)
    col = (255, 212, 0, 255) if tier else (255, 255, 255, 255)
    return shadowed(plain_text(lines, f, col), 6, 0.75)


def panel_assets(size: str, frame: str) -> dict:
    pw, ph = PANELS[size]
    r, border = (22, 0) if frame == "plain" else (40, 6)
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, pw - 1, ph - 1], radius=r, fill=255)
    sh = Image.new("RGBA", (pw + 80, ph + 80), (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", (pw, ph), (0, 0, 0, 120)), (40, 46), mask)
    from PIL import ImageFilter
    sh = sh.filter(ImageFilter.GaussianBlur(16))
    ring = None
    if border:
        ring = Image.new("RGBA", (pw + 2 * border, ph + 2 * border), (0, 0, 0, 0))
        ImageDraw.Draw(ring).rounded_rectangle([0, 0, ring.width - 1, ring.height - 1], radius=r + border,
                                               fill=(255, 255, 255, 255))
    return {"w": pw, "h": ph, "mask": mask, "shadow": sh, "ring": ring}


def panel_layer(layer: Image.Image, p: dict, frame_rgb: bytes, u: float) -> None:
    pan = Image.frombuffer("RGB", (p["w"], p["h"]), frame_rgb).convert("RGBA")
    pan.putalpha(p["mask"])
    if p["ring"] is not None:
        r = p["ring"].copy()
        r.alpha_composite(pan, ((r.width - pan.width) // 2, (r.height - pan.height) // 2))
        pan = r
    sh = p["shadow"]
    s_ = 0.92 + 0.08 * u
    if s_ < 1:
        pan = pan.resize((int(pan.width * s_), int(pan.height * s_)), Image.Resampling.BILINEAR)
        sh = sh.resize((int(sh.width * s_), int(sh.height * s_)), Image.Resampling.BILINEAR)
    cy = PANEL_TOP + p["h"] / 2
    G.paste_center(layer, sh, W / 2, cy - sh.height / 2, u)
    G.paste_center(layer, pan, W / 2, cy - pan.height / 2, u)


# ---------------- выбор вариантов ----------------
def pick_specs(n: int, rng: random.Random) -> list[dict]:
    keys = list(DIMS)
    combos = [dict(zip(keys, v)) for v in itertools.product(*(DIMS[k] for k in keys))]
    orig = {"fmt": "v1", "board": "mono", "subs": "mono", "cut": "a", "mirror": 0, "speed": 1.0, "grade": "none"}
    combos = [c for c in combos if any(c[k] != orig[k] for k in ("board", "subs", "mirror", "speed", "grade"))]
    rng.shuffle(combos)
    use = {k: {v: 0 for v in DIMS[k]} for k in keys}

    def dist(x, y):
        return sum(WEIGHT[k] for k in keys if x[k] != y[k])

    picked = [combos[0]]
    for k in keys:
        use[k][combos[0][k]] += 1
    while len(picked) < n:
        best = max(combos, key=lambda c: (min(dist(c, p) for p in picked),
                                          -sum(use[k][c[k]] for k in keys), rng.random()))
        picked.append(best)
        for k in keys:
            use[k][best[k]] += 1
    out = []
    for i, c in enumerate(picked):
        c = dict(c)
        c["anim"] = ("pop", "bounce", "slide")[i % 3]
        c["upper"] = c["subs"] == "mono" or rng.random() < 0.5
        c["maxch"] = 15                                     # 11 даёт куски вроде «filters but»
        c["grain"] = int(rng.random() < 0.4)
        c["spread"] = rng.choice(["wide", "narrow"])
        c["panel"] = rng.choice(list(PANELS))
        c["pframe"] = rng.choice(["plain", "ring"])
        c["poff"] = rng.choice([0.0, 0.8, 1.6])
        out.append(c)
    return out


# ---------------- раскладка, основа ----------------
def faces(tag: str) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"faces_{tag}.json"
    if p.exists():
        return json.loads(p.read_text())
    import build_gw_wall2_reels as W2
    st = [W2.face_stats(G.SRC / f"{c}.MOV", 0, 60) for c in MONTAGES[tag]]
    d = {"top": min(s["top_min"] for s in st), "chin": max(s["chin_max"] for s in st)}
    p.write_text(json.dumps(d))
    return d


def layout(spec: dict, face: dict, subs: list) -> dict:
    zoom = CUTS[spec["cut"]][0]
    c = (H - H / zoom) * G.ZOOM_Y
    chin_z = max(face["chin"], (face["chin"] - c) * zoom)
    if spec["fmt"] == "v1":
        bottom = board_assets(spec["board"], spec["spread"])["bottom"]
        shift = max(0, bottom + 30 - face["top"])
    else:
        shift = max(0, PANEL_TOP + PANELS[spec["panel"]][1] + GAP - face["top"])
    shift = int(shift) + int(shift) % 2
    sub_h = max(sub_image(spec["subs"], s, False).height for s, _a, _b in subs)
    sub_top = int(min(chin_z + shift + GAP, Y1 - sub_h - 4))
    return {"shift": shift, "sub_top": sub_top}


def build_base(tag: str, tl: dict, cut: str, shift: int) -> Path:
    dest = CACHE / f"base_{tag}_{cut}_{shift}.mov"
    if dest.exists():
        return dest
    segs = tl["segs"]
    clips = list(dict.fromkeys(c for c, *_ in segs))
    inputs, parts = [], []
    for ci, clip in enumerate(clips):
        inputs += ["-i", str(G.SRC / f"{clip}.MOV")]
        mine = [n for n, sg in enumerate(segs) if sg[0] == clip]
        parts.append(f"[{ci}:v]{G.TM},split={len(mine)}" + "".join(f"[sv{n}]" for n in mine))
        parts.append(f"[{ci}:a:0]asplit={len(mine)}" + "".join(f"[sa{n}]" for n in mine))
    for n, (clip, a0, b0, z) in enumerate(segs):
        cw, ch = int(W / z / 2) * 2, int(H / z / 2) * 2             # чётные целые — иначе на краю тёмная/синяя полоска
        zf = "" if z == 1.0 else (f",crop={cw}:{ch}:{(W - cw) // 2}:{int((H - ch) * G.ZOOM_Y)},"
                                  f"scale={W}:{H}:flags=lanczos")
        if shift:
            parts.append(f"[sv{n}]trim=start={a0:.3f}:end={b0:.3f},setpts=PTS-STARTPTS{zf},setsar=1,split[m{n}][t{n}];"
                         f"[t{n}]crop=iw:{shift}:0:0,vflip,gblur=sigma=28,eq=brightness=-0.05[tb{n}];"
                         f"[m{n}]crop=iw:ih-{shift}:0:0[mb{n}];[tb{n}][mb{n}]vstack[v{n}]")
        else:
            parts.append(f"[sv{n}]trim=start={a0:.3f}:end={b0:.3f},setpts=PTS-STARTPTS{zf},setsar=1[v{n}]")
        parts.append(f"[sa{n}]atrim=start={a0:.3f}:end={b0:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d=0.01,afade=t=out:st={max(0.0, b0 - a0 - 0.012):.3f}:d=0.012[a{n}]")
    cat = "".join(f"[v{n}][a{n}]" for n in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=1[v][a]"
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts) + ";" + cat, "-map", "[v]",
                    "-map", "[a]", "-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "14", "-b:v", "0",
                    "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", str(dest)], check=True)
    return dest


# ---------------- рендер одного ролика (воркер) ----------------
def render(job: dict) -> str:
    spec, dest = job["spec"], Path(job["dest"])
    a = board_assets(spec["board"], spec["spread"])
    if spec["mirror"]:                       # видео отражено → и доска зеркально: BAD справа, AMAZING слева (палец туда же)
        a["cols"] = a["cols"][::-1]
    p = panel_assets(spec["panel"], spec["pframe"]) if spec["fmt"] == "v2" else None
    subs, reveal, takes, panel_on = job["subs"], job["reveal"], job["takes"], job["panel_on"]
    tier_idx = set(job["tier_subs"])
    sub_cache: dict = {}
    # зерно — до цветокора, на yuv (noise после colorbalance/gbrp портит правый край: синие колонки)
    vf = [x for x in ("hflip" if spec["mirror"] else "", "noise=alls=4:allf=t+u" if spec["grain"] else "",
                      GRADES[spec["grade"]]) if x]
    dec = subprocess.Popen([FF, "-v", "error", "-i", job["base"], "-vf", ",".join(vf + ["format=rgb24"]),
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    sp = spec["speed"]
    enc = subprocess.Popen([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                            "-i", "-", "-i", job["base"], "-filter_complex",
                            f"[0:v]setpts=PTS/{sp},fps={FPS},format=yuv420p,{SET_SDR}[v];"
                            f"[1:a]atempo={sp},{job['afilter']}[a]",
                            "-map", "[v]", "-map", "[a]", "-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq",
                            "-rc", "vbr", "-cq", "19", "-b:v", "0", "-profile:v", "high", *SDR_COLOR_ARGS,
                            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(dest)],
                           stdin=subprocess.PIPE)
    screen_pipe, screen_k, last_screen, f = None, -1, None, 0
    while True:
        buf = dec.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        t = f / FPS
        si = next((i for i, s in enumerate(subs) if s[1] <= t < s[2]), None)
        frame = Image.frombuffer("RGB", (W, H), buf).convert("RGBA")
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        k = max(i for i, tk in enumerate(takes) if tk[0] <= t + 1e-6)
        if p is not None and t >= panel_on[k]:
            if screen_k != k:
                if screen_pipe:
                    screen_pipe.kill()
                screen_pipe = subprocess.Popen([FF, "-v", "error", "-ss", str(G.SCREEN_SKIP[k] + spec["poff"]), "-i",
                                                str(G.SCREENS[k]), "-vf", f"fps={FPS},scale={p['w']}:{p['h']}:flags=lanczos",
                                                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
                screen_k = k
            sb = screen_pipe.stdout.read(p["w"] * p["h"] * 3)
            last_screen = sb if len(sb) == p["w"] * p["h"] * 3 else last_screen
            if last_screen:
                panel_layer(layer, p, last_screen, min(1.0, (t - panel_on[k]) / 0.15))
        else:
            board_layer(layer, a, t, reveal, spec["anim"])
        if si is not None:
            if si not in sub_cache:
                sub_cache[si] = sub_image(spec["subs"], subs[si][0], si in tier_idx)
            G.paste_center(layer, sub_cache[si], W / 2, job["sub_top"])
        frame.alpha_composite(layer)
        enc.stdin.write(frame.convert("RGB").tobytes())
        f += 1
    if screen_pipe:
        screen_pipe.kill()
    enc.stdin.close()
    enc.wait()
    dec.wait()
    if enc.returncode:
        raise RuntimeError(f"ffmpeg {dest.name}: {enc.returncode}")
    return str(dest)


def prepare(tag: str, specs: list[dict], out_dir: Path) -> list[dict]:
    G.SRC = SRC_OF[tag]
    face = faces(tag)
    tls = {c: timeline(tag, c) for c in sorted({s["cut"] for s in specs})}
    jobs, afilters = [], {}
    for i, spec in enumerate(specs, 1):
        tl = tls[spec["cut"]]
        subs, tier_subs = [], []
        for words in tl["words"]:
            ch = chunks(words, spec["maxch"], spec["upper"])
            tier_subs.append(len(subs))
            subs += ch
        lay = layout(spec, face, subs)
        # проверка зоны: самая широкая/высокая строка субтитров + доска
        a = board_assets(spec["board"], spec["spread"])
        widest = max((sub_image(spec["subs"], s, False) for s, _a, _b in subs), key=lambda im: im.width)
        for box in ((int(W / 2 - widest.width / 2), lay["sub_top"], int(W / 2 + widest.width / 2), lay["sub_top"] + widest.height),
                    (int(a["cols"][0] - 110), a["head_top"], int(a["cols"][2] + 110), a["head_top"] + max(h.height for h in a["heads"]))):
            bad = check_box(W, H, box)
            if bad:
                raise SystemExit(f"{tag} #{i}: вне безопасной зоны {bad} {box} {spec}")
        base = build_base(tag, tl, spec["cut"], lay["shift"])
        if str(base) not in afilters:
            afilters[str(base)] = T.audio_filter(base)
        panel_on = [subs[j][2] for j in tier_subs]
        jobs.append({"spec": spec, "dest": str(out_dir / f"bga_{tag}_{i:02d}.mp4"), "base": str(base),
                     "afilter": afilters[str(base)], "subs": subs, "tier_subs": tier_subs, "reveal": tl["reveal"],
                     "takes": tl["takes"], "panel_on": panel_on, "sub_top": lay["sub_top"], "shift": lay["shift"]})
    return jobs


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=35)
    ap.add_argument("--tags", nargs="+", default=["A", "B"])
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--test", action="store_true", help="6 вариантов A → _test")
    ap.add_argument("--only-mirror", action="store_true", help="перерендерить только зеркальные варианты")
    a = ap.parse_args()
    tags, n = (["A"], 6) if a.test else (a.tags, a.n)
    all_jobs, rows = [], []
    for tag in tags:
        out_dir = (OUT / "_test") if a.test else (OUT_OF[tag] if tag in OUT_OF else OUT / tag)
        out_dir.mkdir(parents=True, exist_ok=True)
        specs = pick_specs(n, random.Random(f"{a.seed}-{tag}"))
        jobs = prepare(tag, specs, out_dir)
        all_jobs += [j for j in jobs if j["spec"]["mirror"] or not a.only_mirror]
        for j in jobs:
            rows.append({"root": str(OUT_OF.get(tag, OUT)), "file": Path(j["dest"]).name, **j["spec"],
                         "shift": j["shift"], "sub_top": j["sub_top"]})
        print(f"{tag}: {len(jobs)} вариантов готово к рендеру", flush=True)
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(render, j) for j in all_jobs]
        for k, fu in enumerate(as_completed(futs), 1):
            print(f"  {k}/{len(futs)} {Path(fu.result()).name}", flush=True)
    for root in sorted({r["root"] for r in rows}):
        mine = [{k: v for k, v in r.items() if k != "root"} for r in rows if r["root"] == root]
        man = (OUT / "_test" if a.test else Path(root)) / ("manifest_G.csv" if Path(root) == OUT and "G" in tags
                                                          else "manifest.csv")
        with man.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(mine[0]), delimiter=";")
            w.writeheader()
            w.writerows(mine)
    print(f"готово: {len(all_jobs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
