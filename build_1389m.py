#!/usr/bin/env python3
"""
1389m — «top 5 websites every music lover needs to know (#4 is actually insane)»: формат 1389/1391, тексты ТЗ дословно (переносы по смыслу),
сайты для музыкантов, Drops = #4. Карусели 3:4 — фон вода, видео 9:16 — небо, смены на долях трека 1391 (--seven: 7.1 с, как 1389b).
Скрины: downloads/1389/shots (capture_1389m_sites.py), drops_03 не берём (там «coming soon»).

  python build_1389m.py --test                                    # 2 карусели → output/1389m_test
  python build_1389m.py --test --video                            # 2 видео → output/1389m_test
  python build_1389m.py -n 200 --flat output/1389m_200
  python build_1389m.py -n 100 --video --out output/1389m_video_100
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1389b as M  # noqa: E402  (звёзды, QA-лист, тайминг 7 с)
B = M.B
V = M.V
from core.safe_zones import check_box  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402

B.SITES = [
    ("radio", "radio.garden", "1. Radio Garden", "spin the globe and discover\nradio stations from literally\nanywhere in the world"),
    ("musicmap", "music-map.com", "2. Music-Map", "type in your favorite artist\nand find other musicians\nwith a similar vibe"),
    ("everynoise", "everynoise.com", "3. Every Noise at Once", "explore hundreds of music genres\nyou probably didn't even\nknow existed"),
    ("drops", "drops.game", "4. Drops", "upload any song and turn it\ninto an actual playable game.\nyou can literally play\nyour favorite music"),
    ("musicca", "musicca.com", "5. Musicca", "free music theory lessons\nand ear training exercises\nthat are actually useful"),
]
_wrap = B.wrap


def wrap_by_meaning(s: str, f, width: int) -> list[str]:
    """Переносы заданы в тексте по смыслу; если строка не влезла — ошибка, а не перенос по ширине."""
    if "\n" not in s:
        return _wrap(s, f, width)
    lines = s.split("\n")
    for ln in lines:
        if f.getlength(ln) > width:
            raise SystemExit(f"строка шире карточки: {ln}")
    return lines


B.wrap = wrap_by_meaning


def cover(bg: Path, rng: random.Random, video: bool) -> tuple[Image.Image, list]:
    """top 5 / websites / [every music lover] / needs to know / (#4 is actually insane) / save for later!"""
    W, H = (V.W, V.H) if video else (B.W, B.H)
    k = 1.14 if video else 1.0
    im = (V.background if video else B.background)(bg, rng)
    white = (255, 255, 255, 255)
    limit = 760 if video else 690
    px = round(170 * k)
    while True:
        w1 = B.text_img("websites", B.font(B.F_BOLD, px), white, track=-0.045)
        if w1.width <= limit:
            break
        px -= 4
    px2 = px
    while True:
        w2 = B.text_img("needs to know", B.font(B.F_BOLD, px2), white, track=-0.04)
        if w2.width <= w1.width:
            break
        px2 -= 2
    top = B.text_img("top 5", B.font(B.F_SEMI, round(58 * k)), white, track=-0.02)
    fav = B.text_img("(#4 is actually insane)", B.font(B.F_SEMI, round(42 * k)), white, track=-0.01)
    save = B.text_img("save for later!", B.font(B.F_SEMI, round(34 * k)), white)
    tag_px = round(64 * k)                                       # метка крупно (фидбек клиента: «мало видно»), почти на ширину «websites»
    while B.tag("every music lover", tag_px).width > w1.width:
        tag_px -= 1
    tg = B.tag("every music lover", tag_px)
    cx = W // 2
    gap = round(6 * k)
    hsum = top.height + 18 + w1.height + gap + tg.height + 18 + w2.height + 30 + fav.height + 30 + save.height
    y = int((840 if video else 600) - hsum / 2)
    els = []
    x1 = cx - w1.width // 2
    els.append((top, x1 + 6, y)); y += top.height + 18
    els.append((w1, x1, y)); y += w1.height + gap
    els.append((tg, cx - tg.width // 2, y + 8)); y += tg.height + 18
    els.append((w2, cx - w2.width // 2, y + 6)); y += w2.height + 30
    els.append((fav, cx - fav.width // 2, y)); y += fav.height + 30
    els.append((save, cx - save.width // 2, y))
    x0 = min(e[1] for e in els); y0 = min(e[2] for e in els)
    x1_ = max(e[1] + e[0].width for e in els); y1_ = max(e[2] + e[0].height for e in els)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for e, x, yy in els:
        if e is not tg:
            layer.alpha_composite(e, (x, yy))
    M.stars(im, rng, [(x0, y0, x1_, y1_)], rng.randint(14, 19) if video else rng.randint(12, 16), W, H)
    lum = float(np.asarray(im.convert("L").crop((x0, y0, x1_, y1_)), dtype=np.float32).mean()) / 255
    d = min(max((lum - 0.42) * 1.3, 0.0), 0.38)
    if d > 0:
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).ellipse((x0 - 90, y0 - 75, x1_ + 90, y1_ + 75), fill=int(255 * d))
        dim = Image.new("RGBA", (W, H), (20, 40, 70, 0) if video else (8, 30, 40, 0))
        dim.putalpha(m.filter(ImageFilter.GaussianBlur(75)))
        im.alpha_composite(dim)
    sh = add_shadow(layer, blur=3, opacity=0.55, offset=(0, 2), grow=1, pad=0)
    sh = add_shadow(sh, blur=22, opacity=0.4, offset=(0, 0), grow=8, pad=0)
    im.alpha_composite(sh)
    im.alpha_composite(add_shadow(tg, blur=6, opacity=0.3, offset=(0, 2), grow=1, pad=20), (els[2][1] - 20, els[2][2] - 20))
    return im.convert("RGB"), [(x0, y0, x1_, y1_)]


def libs(video: bool) -> tuple[list[Path], list[list[Path]]]:
    bgs = M.images(V.BG if video else B.BG)
    pools = [[f for f in M.images(B.SHOTS, f"{key}_*") if f.stem != "drops_03"] for key, *_ in B.SITES]
    return bgs, pools


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--video", action="store_true")
    ap.add_argument("--flat", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--seed", type=int, default=13893)
    a = ap.parse_args()
    bgs, pools = libs(a.video)
    if not bgs or not all(pools):
        raise SystemExit(f"пустые библиотеки: фонов {len(bgs)}, пулы {[len(p) for p in pools]}")
    W, H = (V.W, V.H) if a.video else (B.W, B.H)
    out = a.out or ROOT / "output" / ("1389m_test" if a.test else f"{'video' if a.video else 'carousels'}_1389m_{a.n}")
    out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "output" / "_work" / "1389m_frames"
    if a.video:
        work.mkdir(parents=True, exist_ok=True)
        cuts, end = [0.0] + [round(t * V.FPS) / V.FPS for t in M.SEVEN_MARKS], round(M.SEVEN_END * V.FPS) / V.FPS
        wav = V.music(ROOT / "output" / "_work", end)
        print(f"смены: {[round(c, 3) for c in cuts]} конец {end:.3f}")
    pals = {bg: (V.palettes(bg) if a.video else B.bg_palettes(bg)) for bg in bgs}
    rng = random.Random(a.seed + (1 if a.video else 0))
    seen, manifest = set(), []
    slide_fn = V.slide_site if a.video else B.slide_site
    for i in range(1, a.n + 1):
        for _ in range(500):
            bg, pick = rng.choice(bgs), tuple(rng.choice(p) for p in pools)
            pal = rng.choice(pals[bg])
            key = (bg.name, pal) + tuple(p.name for p in pick)
            if key not in seen:
                break
        else:
            raise SystemExit("не нашлось нового сочетания")
        seen.add(key)
        B.PAL = B.PALETTES[pal]
        r = random.Random(a.seed * 10000 + i + (500000 if a.video else 0))
        slides = [cover(bg, r, a.video)] + [slide_fn(k, pick[k], bg, r) for k in range(5)]
        for k, (im, boxes) in enumerate(slides, 1):
            for b in boxes:
                if bad := check_box(W, H, b):
                    raise SystemExit(f"{i:03d} слайд {k}: текст вне безопасной зоны {b} — {bad}")
        if a.video:
            fr = []
            for k, (im, _) in enumerate(slides, 1):
                p = work / f"{i:03d}_{k}.png"
                im.save(p)
                fr.append(p)
            mp4 = out / f"{i:03d}_1389.mp4"
            V.render(fr, wav, mp4, cuts, end)
            for p in fr:
                p.unlink()
            manifest.append({"video": mp4.name, "bg": bg.name, "palette": pal, "shots": [p.name for p in pick]})
        else:
            d = out / f"{i:03d}"
            d.mkdir(exist_ok=True)
            for k, (im, _) in enumerate(slides, 1):
                im.save(d / f"{k}.jpg", quality=94)
                if a.flat:
                    a.flat.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(d / f"{k}.jpg", a.flat / f"sort_{k}_{i}_1389.jpg")
            manifest.append({"carousel": d.name, "bg": bg.name, "palette": pal, "shots": [p.name for p in pick]})
        if a.test:
            M.qa_sheet(slides, out / f"_qa_{'v' if a.video else 'c'}_{i:03d}.jpg", a.video)
        print(f"  {i:03d}", flush=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    if a.video:
        shutil.rmtree(work, ignore_errors=True)
    print(f"готово: {a.n} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
