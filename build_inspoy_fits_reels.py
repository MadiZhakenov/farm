#!/usr/bin/env python3
"""
Inspoy (ID 1) — «this style.» по рефу TikTok @.ajzi21 7607918384553921825: быстрая нарезка образов в стиле 90s streetwear
(смена фото каждые ~0.24 с, ровно как в рефе, до самого конца), по центру мелкое белое «this style.», звук рефа (cacao oasis «original sound»
7462499912400096005, с 6.43 с — как в рефе). Последние 2.23 с (клиент: 2–2.5 с) — «the way i found all these fits on inspoy 😭» + карточка Inspoy
из App Store поверх фото, которые продолжают меняться. 9:16, до 7 с.
Фото — Pinterest (downloads/inspoy_fits/pins, отбор глазами 2026-11-12: девушки в полный рост, живые места, без раскладок,
коллажей, надписей, парней и знаменитостей). Каждый ролик: 11 своих фото по кругу (как в рефе — 10 фото по кругу),
своя подрезка/цвет, финальное фото с текстом; старт звука — один из 3 отрезков того же ритма (+16 смен фото).
TT и YT — одним списком: наборы фото у всех роликов разные.

  python build_inspoy_fits_reels.py -n 3 --out output/_work/inspoy_fits_test
  python build_inspoy_fits_reels.py --tt 100 --yt 150     # → output/inspoy_fits_TT_100 + output/inspoy_fits_YT_150
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1380_carousels as C  # noqa: E402  (white_line — белый TikTok-шрифт с мягкой тенью и эмодзи Apple)
import build_dad_trucker_carousels as D  # noqa: E402  (store_card — карточка Inspoy из App Store, скруглённая)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
SRC = ROOT / "downloads" / "inspoy_fits"
MUSIC = ROOT / "downloads" / "inspoy_fits_ref" / "music" / "cacao_oasis_7462499912400096005.mp3"
REF_SS = 6.43                                           # с этого места трека звучит реф
PERIOD = 0.2433                                         # смена фото в рефе
# смены фото в рефе (с) — копия, кадр в кадр
REF_CUTS = [0.2333, 0.4833, 0.7167, 0.9667, 1.2333, 1.4833, 1.7167, 1.9667, 2.2167, 2.45, 2.6833, 2.9333, 3.1667, 3.4167,
            3.6833, 3.9333, 4.1667, 4.4167, 4.6667, 4.9, 5.1333, 5.3833, 5.6167, 5.8667, 6.1333, 6.3833, 6.6167]
# клиент: скрин Inspoy — на последних 2–2.5 с, а не только на последнем слайде. С этой смены (2.23 с до конца) на каждом
# фото — текст ТЗ + карточка App Store, а нарезка фото под ними продолжается в ритме рефа до самого конца
CARD_AT = 4.6667
TOTAL = 6.9
SS_OPTS = [REF_SS, REF_SS + 16 * PERIOD, REF_SS + 32 * PERIOD]
DROP = {8, 29, 40, 42, 44, 69, 251, 273, 362, 589}     # раскладки/коллаж/обрезанная голова/ник TikTok/наклейка — не берём
WM_BOTTOM = {49, 63, 196, 264, 339, 455, 520}           # «© www.sewmamasew.com» внизу — срезаем низ 4.5 %
N_PHOTOS = 11
STYLE_TXT, STYLE_PX, STYLE_CY = "this style.", 40, 0.52
END_TXT = ["the way i found all these fits", "on inspoy 😭"]   # ТЗ дословно, перенос по смыслу
END_PX, END_CY = 58, 0.40


EDITED = SRC / "edited"                                  # фото после правки в Flow (9:16, без надписей) — только они


def pool() -> list[Path]:
    """Отредаченные фото: edited/<NN>_pNNN….jpg (по одному на номер; новые закачки просто докладываются туда)."""
    by_no: dict[str, Path] = {}
    for p in sorted(EDITED.glob("*.jpg")):
        by_no.setdefault(p.name[:2], p)
    return [by_no[k] for k in sorted(by_no)]


def fit916(p: Path, rng: random.Random) -> Image.Image:
    """Фото → 9:16: по центру ± немного, лёгкий зум, свой цвет; у фото с адресом сайта срезаем низ."""
    im = Image.open(p).convert("RGB")
    z = rng.uniform(1.015, 1.06)                       # не меньше 1.5 % — одинаковое фото не совпадёт побайтово
    cw, ch = im.width / z, im.height / z
    x0, y0 = (im.width - cw) * rng.uniform(0.3, 0.7), (im.height - ch) * rng.uniform(0.2, 0.6)
    im = im.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch)))
    im = ImageOps.fit(im, (W, H), Image.Resampling.LANCZOS, centering=(rng.uniform(0.45, 0.55), 0.45))
    im = ImageEnhance.Brightness(im).enhance(rng.uniform(0.97, 1.04))
    im = ImageEnhance.Color(im).enhance(rng.uniform(0.98, 1.12))
    return ImageEnhance.Contrast(im).enhance(rng.uniform(1.0, 1.06))


def put(im: Image.Image, text: str, cy: float, px: int) -> tuple[int, int, int, int]:
    blk, (tw, th) = C.white_line(text, 800, px)
    x, y = (W - blk.width) // 2, int(cy * H - blk.height / 2)
    im.alpha_composite(blk, (x, y))
    ox, oy = (blk.width - tw) // 2, (blk.height - th) // 2
    return x + ox, y + oy, x + ox + tw, y + oy + th


def slide(p: Path, rng: random.Random) -> Image.Image:
    im = fit916(p, rng).convert("RGBA")
    box = put(im, STYLE_TXT, STYLE_CY, STYLE_PX)
    if bad := check_box(W, H, box):
        raise SystemExit(f"«this style.» вне безопасной зоны {box} — {bad}")
    return im.convert("RGB")


def end_slide(p: Path, rng: random.Random) -> Image.Image:
    im = fit916(p, rng).convert("RGBA")
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 40))     # чуть темнее, чтобы текст и карточка читались
    im.alpha_composite(shade)
    gap = int(END_PX * 1.25)
    boxes = [put(im, ln, END_CY + (k - (len(END_TXT) - 1) / 2) * gap / H, END_PX) for k, ln in enumerate(END_TXT)]
    card = D.store_card()
    cy = boxes[-1][3] + 44
    im.alpha_composite(card, ((W - card.width) // 2, cy))
    pad = (card.width - D.CARD_W) // 2
    boxes.append(((W - card.width) // 2 + pad, cy + pad, (W + card.width) // 2 - pad, cy + card.height - pad))
    for b in boxes:
        if bad := check_box(W, H, b):
            raise SystemExit(f"финал вне безопасной зоны {b} — {bad}")
    return im.convert("RGB")


def plan(n: int, seed: int) -> list[dict]:
    """n роликов: у каждого свои 11 фото (наименее использованные, набор не повторяется) + своё финальное фото."""
    rng = random.Random(seed)
    ps = pool()
    used = {p.name: 0 for p in ps}
    seen, rows = set(), []
    for i in range(1, n + 1):
        while True:
            order = sorted(ps, key=lambda p: (used[p.name] + rng.random() * 1.5))
            pick = order[:N_PHOTOS]
            key = frozenset(p.name for p in pick)
            if key not in seen:
                break
        seen.add(key)
        rng.shuffle(pick)
        final = order[N_PHOTOS]                          # финальное фото — ещё одно, не из нарезки
        for p in pick + [final]:
            used[p.name] += 1
        rows.append(dict(i=i, photos=[p.name for p in pick], final=final.name, seed=rng.randrange(1 << 30),
                         ss=SS_OPTS[(i - 1) // 2 % len(SS_OPTS)]))
    return rows


def render(r: dict, out: Path, work: Path) -> Path:
    rng = random.Random(r["seed"])
    fr = work / f"{out.parent.name}_{out.stem}"
    fr.mkdir(parents=True, exist_ok=True)
    names = r["photos"] + [r["final"]]                  # 12 фото по кругу
    bounds = [0.0] + REF_CUTS
    fb = [round(b * FPS) for b in bounds] + [round(TOTAL * FPS)]
    made: dict = {}

    def png(k: int) -> Path:
        """Фото отрезка k: до CARD_AT — с «this style.», дальше — с текстом ТЗ и карточкой App Store."""
        end = bounds[k] >= CARD_AT - 1e-6
        key = (k % len(names), end)
        if key not in made:
            p = fr / f"{'e' if end else 's'}{key[0]:02d}.png"
            (end_slide if end else slide)(EDITED / names[key[0]], rng).save(p, compress_level=1)
            made[key] = p
        return made[key]

    segs = [(png(k), fb[k + 1] - fb[k]) for k in range(len(bounds))]
    uniq = list(dict.fromkeys(p for p, _ in segs))
    uses = {p: sum(1 for q, _ in segs if q == p) for p in uniq}
    ins, fc, labels, ctr = [], [], [], {p: 0 for p in uniq}
    for j, p in enumerate(uniq):
        ins += ["-i", str(p)]
        fc.append(f"[{j}:v]format=yuv420p,split={uses[p]}" + "".join(f"[u{j}_{t}]" for t in range(uses[p])))
    for k, (p, nfr) in enumerate(segs):
        j = uniq.index(p)
        fc.append(f"[u{j}_{ctr[p]}]loop=loop={nfr - 1}:size=1:start=0,settb=1/{FPS},setpts=N[g{k}]")
        ctr[p] += 1
        labels.append(f"[g{k}]")
    fc.append("".join(labels) + f"concat=n={len(segs)}:v=1:a=0[v]")
    ins += ["-ss", f"{r['ss']:.3f}", "-t", f"{TOTAL + 0.3:.2f}", "-i", str(MUSIC)]
    fc.append(f"[{len(uniq)}:a]atrim=0:{TOTAL:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
              f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={TOTAL - 0.35:.3f}:d=0.35[a]")
    (fr / "graph.txt").write_text(";\n".join(fc), encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex_script", str(fr / "graph.txt"), "-map", "[v]",
                    "-map", "[a]", "-t", f"{TOTAL:.3f}", "-r", str(FPS), "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                    "-cq", "27", "-maxrate", "6M", "-bufsize", "12M", "-pix_fmt", "yuv420p",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-c:a", "aac", "-b:a", "160k",
                    "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
                    "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=",
                    "-movflags", "+faststart", str(out)], check=True)
    shutil.rmtree(fr)
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=3)
    ap.add_argument("--out", type=Path, help="тест: -n роликов в одну папку")
    ap.add_argument("--tt", type=int, default=0)
    ap.add_argument("--yt", type=int, default=0)
    ap.add_argument("--seed", type=int, default=7607)
    ap.add_argument("--suffix", default="1")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    total_n = a.tt + a.yt if (a.tt or a.yt) else a.n
    rows = plan(total_n, a.seed)
    jobs = []
    if a.tt or a.yt:
        tt, yt = ROOT / "output" / f"inspoy_fits_TT_{a.tt}", ROOT / "output" / f"inspoy_fits_YT_{a.yt}"
        nt = ny = 0
        for r in rows:                                  # по очереди TT / YT, пока не набрали каждую
            if (r["i"] % 2 == 1 and nt < a.tt) or ny >= a.yt:
                nt += 1
                jobs.append((tt, nt, r))
            else:
                ny += 1
                jobs.append((yt, ny, r))
    else:
        jobs = [(a.out, r["i"], r) for r in rows]
    work = ROOT / "output" / "_work" / "inspoy_fits"
    work.mkdir(parents=True, exist_ok=True)
    man: dict = {}
    for d, n, r in jobs:
        d.mkdir(parents=True, exist_ok=True)
        man.setdefault(d.name, {})[f"{n:03d}_{a.suffix}.mp4"] = dict(r, total=TOTAL)
    for name, m in man.items():
        (work / f"manifest_{name}.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    todo = [j for j in jobs if not (j[0] / f"{j[1]:03d}_{a.suffix}.mp4").exists()]
    bad = []
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(render, r, d / f"{n:03d}_{a.suffix}.mp4", work) for d, n, r in todo]
        for (d, n, r), f in zip(todo, futs):
            try:
                print(" ", d.name, f.result().name, "ss", r["ss"], flush=True)
            except Exception as e:                      # noqa: BLE001
                (d / f"{n:03d}_{a.suffix}.mp4").unlink(missing_ok=True)
                bad.append(f"{d.name}/{n:03d}")
                print("  ОШИБКА", d.name, n, e, flush=True)
    if bad:
        print("не собрались (перезапусти — доделает только их):", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
