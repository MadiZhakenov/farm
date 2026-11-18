#!/usr/bin/env python3
"""
Inspoy — «hot christmas costumes» (ID 1) как видео 9:16: 7 слайдов листаются свайпом влево, как фото-карусель
в TikTok (наш пост @isabellakerriganxo 7706411237940219167), под звук этого поста (Winter Wonderland,
downloads/xmas_video/music). Кадры — те же Flow-кадры карусели (output/xmas_costumes/slides/s1..s7), тексты ТЗ
дословно, как в карусели: s1 белый TikTok-текст на платье, s2–s6 чёрное название с белой обводкой на стене над
кроватью, s7 текст + карточка Inspoy из App Store. Всё в безопасной рамке 9:16 (x 140–940, y 200–1540).
Свайпы на долях (129 BPM): обложка 5 долей, образы по 4, финал 8 — ~15.5 с. Старт звука — одна из 5 долей.
TT и YT — одним списком: все сочетания кадров разные между обеими папками.

  python build_xmas_video.py -n 3 --out output/_work/inspoy_xmas_video_test
  python build_xmas_video.py --yt 150 --tt 100           # → output/inspoy_xmas_video_YT_150 + _TT_100
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1319_carousels as K  # noqa: E402  (block — белый TikTok-текст, label_block — чёрный с обводкой, app_card)
import build_xmas_costumes_carousels as X  # noqa: E402  (SLIDES — тексты ТЗ, SL — кадры)
import swipe_video as SV  # noqa: E402
from core.safe_zones import check_box, text_rect  # noqa: E402

W, H = SV.W, SV.H
X0, Y0, X1, Y1 = text_rect(W, H)
MUSIC = ROOT / "downloads" / "xmas_video" / "music" / "winter_wonderland_6754260567562651650.mp3"
BEATS = [0.16, 0.65, 1.14, 1.63, 2.09, 2.53, 3.02, 3.51, 4.02, 4.53, 5.09, 5.55, 6.01, 6.48, 6.92, 7.38, 7.85, 8.31, 8.78,
         9.24, 9.73, 10.19, 10.66, 11.12, 11.59, 12.05, 12.54, 13.03, 13.49, 13.91, 14.35, 14.81, 15.28, 15.74, 16.21,
         16.7, 17.21, 17.74, 18.25, 18.72, 19.13, 19.57, 20.11, 20.57, 21.06, 21.52, 21.97, 22.38, 22.83, 23.27, 23.73,
         24.2, 24.66, 25.12, 25.61, 26.12, 26.61, 27.1, 27.54, 28.0, 28.49, 28.98, 29.44, 29.91, 30.39, 30.88, 31.35,
         31.79, 32.3, 32.81, 33.3, 33.76, 34.23, 34.69, 35.16, 35.62, 36.11, 36.62, 37.11, 37.62, 38.08, 38.52, 38.99,
         39.43, 39.92, 40.38, 40.87, 41.33, 41.8, 42.31, 42.77, 43.26, 43.72, 44.19, 44.65, 45.12, 45.58, 46.07, 46.53,
         47.02, 47.53, 48.04, 48.51, 48.97, 49.44, 49.88, 50.36, 50.85, 51.32, 51.78, 52.27, 52.73, 53.22, 53.71]
HOLDS = [5, 4, 4, 4, 4, 4, 8]                           # долей на слайд (последний — текст + карточка)
STARTS = [0, 8, 16, 24, 32]                             # доля старта звука — у каждого видео своя
CX = [0.5, 0.42, 0.42, 0.42, 0.42, 0.42, 0.5]           # 9:16 режет бока: образы на кровати чуть левее центра
COVER_BAND = (0.53, 0.72)                               # s1: текст на платье ниже рук с телефоном (доли высоты)
WALL = [(0.30, 0.25), (0.0, 0.25)]                      # s2–s6: стена над кроватью — правее ёлки, иначе вся ширина
APP_TOP = 0.36                                          # s7: верх блока «текст + карточка» — под телефоном
GAP = 16


def timing(b0: int) -> tuple[float, list[float], float]:
    return SV.beat_timing(BEATS, b0, HOLDS)


def frame916(src: Path, rng: random.Random, cx: float) -> Image.Image:
    """Кадр 3:4 → 9:16: бока режем (центр cx ± немного), зум 1.5–5 % и сдвиг — свои у каждого видео."""
    im = Image.open(src).convert("RGB")
    z = rng.uniform(1.015, 1.05)
    ch = im.height / z
    cw = ch * W / H
    x = (im.width - cw) * cx + rng.uniform(-0.025, 0.025) * im.width
    x = max(0.0, min(im.width - cw, x))
    y = rng.uniform(0, im.height - ch)
    im = im.crop((round(x), round(y), round(x + cw), round(y + ch))).resize((W, H), Image.Resampling.LANCZOS)
    return im.filter(ImageFilter.UnsharpMask(radius=1.4, percent=55, threshold=2))


def place(k: int) -> tuple[Image.Image, tuple]:
    texts, mode, max_px = X.SLIDES[k]
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if mode == "low":
        top, bottom = int(COVER_BAND[0] * H), int(COVER_BAND[1] * H)
        px = max_px
        b = K.block(texts[0], px)
        while (b.width > X1 - X0 or b.height > bottom - top) and px > K.LABEL_MIN_PX:
            px -= 2
            b = K.block(texts[0], px)
        x, y = (W - b.width) // 2, top + (bottom - top - b.height) // 2
    elif mode == "top":
        boxes = [(max(X0, int(a * W)), Y0, X1, int(c * H)) for a, c in WALL]
        fits = [(f, bx) for bx in boxes if (f := K.fit_label(texts, max_px, bx))]
        good = [v for v in fits if v[0][0] >= X.TITLE_OK_PX]
        (px, t), bx = good[0] if good else max(fits, key=lambda v: v[0][0])
        b = K.label_block(t, px)
        x, y = (bx[0] + bx[2] - b.width) // 2, (bx[1] + bx[3] - b.height) // 2
    else:                                               # app: текст ТЗ и под ним карточка App Store
        top = int(APP_TOP * H)
        for px in range(max_px, K.LABEL_MIN_PX - 1, -2):
            b, c = K.block(texts[0], px), K.app_card(min(X1 - X0, round(px * 12.5)))
            h = b.height + GAP + c.height
            if b.width <= X1 - X0 and h <= Y1 - top:
                break
        y = top + (Y1 - top - h) // 3
        layer.alpha_composite(b, ((W - b.width) // 2, y))
        layer.alpha_composite(c, ((W - c.width) // 2, y + b.height + GAP))
        x0 = min((W - b.width) // 2, (W - c.width) // 2)
        return layer, (x0, y, W - x0, y + h)
    layer.alpha_composite(b, (x, y))
    return layer, (x, y, x + b.width, y + b.height)


def render(picks: list[Path], seed: int, b0: int, out: Path, work: Path) -> Path:
    rng = random.Random(seed)
    ss, ends, total = timing(b0)
    fr = work / f"{out.parent.name}_{out.stem}"         # своя папка у TT и YT с одним номером
    fr.mkdir(parents=True, exist_ok=True)
    pngs = []
    for k, src in enumerate(picks):
        bg = frame916(src, rng, CX[k]).convert("RGBA")
        layer, box = place(k)
        if bad := check_box(W, H, box):
            raise SystemExit(f"{out.name} слайд {k + 1}: вне безопасной зоны {box} — {bad}")
        p = fr / f"{k + 1}.png"
        Image.alpha_composite(bg, layer).convert("RGB").save(p, compress_level=1)
        pngs.append(p)
    SV.encode(pngs, ends, total, MUSIC, ss, out, fr)
    shutil.rmtree(fr)
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=3)
    ap.add_argument("--out", type=Path, help="тест: -n видео в одну папку")
    ap.add_argument("--yt", type=int, default=0)
    ap.add_argument("--tt", type=int, default=0)
    ap.add_argument("--seed", type=int, default=7706)
    ap.add_argument("--suffix", default="1")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    pools = [sorted((X.SL / f"s{k}").glob("*.jpg")) for k in range(1, 8)]
    total_n = a.yt + a.tt if (a.yt or a.tt) else a.n
    picks = SV.plan_unique(pools, total_n, a.seed)
    rows = [(i, pk, a.seed * 1000 + i, STARTS[(i - 1) // 2 % len(STARTS)]) for i, pk in enumerate(picks, 1)]
    jobs = []                                           # (папка, номер в папке, строка плана)
    if a.yt or a.tt:
        yt, tt = ROOT / "output" / f"inspoy_xmas_video_YT_{a.yt}", ROOT / "output" / f"inspoy_xmas_video_TT_{a.tt}"
        ny = nt = 0
        for r in rows:                                  # по очереди YT / TT, пока не набрали каждую
            if (r[0] % 2 == 1 and ny < a.yt) or nt >= a.tt:
                ny += 1
                jobs.append((yt, ny, r))
            else:
                nt += 1
                jobs.append((tt, nt, r))
    else:
        jobs = [(a.out, r[0], r) for r in rows]
    work = ROOT / "output" / "_work" / "xmas_video"
    work.mkdir(parents=True, exist_ok=True)
    man: dict = {}
    for d, n, r in jobs:
        d.mkdir(parents=True, exist_ok=True)
        ss, ends, total = timing(r[3])
        man.setdefault(d.name, {})[f"{n:03d}_{a.suffix}.mp4"] = dict(ends=ends, total=total, start=ss,
                                                                     picks=[p.name for p in r[1]])
    for name, m in man.items():
        (work / f"manifest_{name}.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    todo = [j for j in jobs if not (j[0] / f"{j[1]:03d}_{a.suffix}.mp4").exists()]
    bad = []
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(render, r[1], r[2], r[3], d / f"{n:03d}_{a.suffix}.mp4", work) for d, n, r in todo]
        for (d, n, r), f in zip(todo, futs):
            try:
                print(" ", d.name, f.result().name, [p.name for p in r[1]], "start", BEATS[r[3]], flush=True)
            except Exception as e:                      # noqa: BLE001 — не роняем партию, недоделанное удаляем
                (d / f"{n:03d}_{a.suffix}.mp4").unlink(missing_ok=True)
                bad.append(f"{d.name}/{n:03d}")
                print("  ОШИБКА", d.name, n, e, flush=True)
    if bad:
        print("не собрались (перезапусти ту же команду — доделает только их):", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
