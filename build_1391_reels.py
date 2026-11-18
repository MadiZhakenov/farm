#!/usr/bin/env python3
"""
1391 — видео 9:16 по шаблону 1389 («top 5 websites [to cure your] boredom (#4 is my favorite)», Drops = #4):
обложка до первого «бац» трека, потом слайды 2–6 (neal.fun / radio.garden / window-swap / drops.game / patatap) сменяются на бит.
Элементы и тексты — из build_1389_carousels (адресная строка, iMac, меню Copy/Select All, карточка, курсор, звёзды),
фон новый — небо с облаками (output/1391_pool/bg_sky), цвет iMac и меток подбирается под фон.

Музыка: оригинальный звук leaf (TikTok sound 7614584514043890454) → downloads/1391/music/sound.mp3, 23.3 с.
Обложка до «бац» (1.61 с, после «feel like a brand new»), дальше смена на сильной доле каждого такта (--bars 1)
или через такт (--bars 2).

  python build_1391_reels.py --test                      # 3 видео + лист кадров → output/1391_test
  python build_1391_reels.py -n 100 --out output/1391_100
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1389_carousels as B  # noqa: E402
from core.safe_zones import check_box, draw_overlay  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402

W, H = 1080, 1920
FPS = 30
BG = ROOT / "output" / "1391_pool" / "bg_pick"
MUSIC = ROOT / "downloads" / "1391" / "music" / "sound.mp3"
# сильные доли тактов (152 BPM, такт 1.579 с), замер по пикам атаки: 1.61 — «бац» после «feel like a brand new»
DOWNBEATS = [1.610, 3.176, 4.767, 6.344, 7.925, 9.492, 11.083, 12.655, 14.241, 15.812, 17.404, 18.985]


# 1-я и 3-я доли каждого такта (3-я — снейр), тоже замер по пикам
BEATS13 = [1.610, 2.403, 3.176, 3.974, 4.767, 5.551, 6.344, 7.135, 7.925]


def timing(bars: int, half: bool = False) -> tuple[list[float], float]:
    """Обложка до «бац», дальше смена каждые `bars` тактов на сильную долю, либо (half) 2 раза за такт —
    на 1-й и 3-й долях (округление до кадра)."""
    marks = [round(t * FPS) / FPS for t in (BEATS13 if half else DOWNBEATS[::bars])]
    return [0.0] + marks[:5], marks[5]
SCALE = 1.22          # элементы 1389 чуть крупнее под высокий кадр
# цвет iMac/меток: по тону неба (B.bg_palettes), но на розово-сиреневых и золотых облаках — без розового/персика
PAL_OVERRIDE = {"003": ["sky", "pink", "lilac"], "021": ["sky", "butter"], "025": ["sky", "butter", "lilac"]}


def palettes(bg: Path) -> list[str]:
    return PAL_OVERRIDE.get(bg.name[:3]) or B.bg_palettes(bg)


def background(src: Path, rng: random.Random) -> Image.Image:
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    if rng.random() < 0.5:
        im = ImageOps.mirror(im)
    return ImageOps.fit(im, (W, H), Image.Resampling.LANCZOS,
                        centering=(rng.uniform(0.4, 0.6), rng.uniform(0.4, 0.6))).convert("RGBA")


def site_layer(k: int, shot: Path) -> tuple[Image.Image, list, tuple]:
    """Связка 1389 (строка → iMac → меню → карточка → курсор) на прозрачном слое, в масштабе SCALE.
    Возвращает слой, боксы текста и общий бокс (для звёзд) в координатах слоя."""
    key, domain, title, desc = B.SITES[k]
    bar, mac, pill = B.address_bar(domain), B.imac(shot), B.menu_pill()
    cd, cboxes = B.card(title, desc)
    lw = mac.width + 60
    bx, by = (lw - bar.width) // 2, 40
    mx, my = (lw - mac.width) // 2, by + bar.height + 36
    px_, py_ = mx + mac.width - pill.width - 4, my + 383 + 32 + 22
    x0f = (W - lw * SCALE) / 2                                    # слой встанет ровно по центру кадра
    cx_ = int(min(lw - cd.width - 4, lw // 2 + 30, (930 - x0f) / SCALE - cboxes[0][2]))   # текст карточки ≤ x 930
    cy_ = my + 383 + 32 + 22 + 46 + 10
    lh = cy_ + cd.height + 60
    L = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    for el, (x, y), sh in ((bar, (bx, by), (10, 0.2, 4)), (mac, (mx, my), (18, 0.35, 10)),
                           (pill, (px_, py_), (8, 0.25, 3)), (cd, (cx_, cy_), (18, 0.3, 10))):
        s, p = B.shadowed(el, blur=sh[0], opacity=sh[1], offset=(0, sh[2]))
        L.alpha_composite(s, (x - p, y - p))
    cur = B.cursor()
    L.alpha_composite(cur, (cx_ + cd.width - 44, cy_ + cd.height - 44))
    boxes = [(bx + 60, by + 8, bx + bar.width - 60, by + bar.height - 8)]
    boxes += [(cx_ + a, cy_ + b, cx_ + c, cy_ + d) for a, b, c, d in cboxes]
    L = L.resize((round(lw * SCALE), round(lh * SCALE)), Image.Resampling.LANCZOS)
    boxes = [tuple(round(v * SCALE) for v in b) for b in boxes]
    return L, boxes, (0, 0, L.width, L.height)


def slide_site(k: int, shot: Path, bg: Path, rng: random.Random) -> tuple[Image.Image, list]:
    im = background(bg, rng)
    L, boxes, _ = site_layer(k, shot)
    x0 = (W - L.width) // 2                                        # iMac и адресная строка — ровно по центру
    y0 = int(880 - L.height / 2)                                   # центр безопасной зоны 200–1540
    avoid = [(x0, y0 + 30, x0 + L.width, y0 + L.height - 40)]
    B.stars(im, rng, avoid, rng.randint(12, 17))
    im.alpha_composite(L, (x0, y0))
    return im.convert("RGB"), [(a + x0, b + y0, c + x0, d + y0) for a, b, c, d in boxes]


def slide_cover(bg: Path, rng: random.Random) -> tuple[Image.Image, list]:
    """Обложка 1389 в 9:16: «top 5» / «websites» / [to cure your] / «boredom» / (#4 is my favorite) / save for later!
    Блок по центру безопасной зоны; под светлым небом — мягкое затемнение, двойная тень."""
    im = background(bg, rng)
    white = (255, 255, 255, 255)
    big = B.font(B.F_BOLD, 168)
    w1 = B.text_img("websites", big, white, track=-0.045)
    w2 = B.text_img("boredom", big, white, track=-0.045)
    while max(w1.width, w2.width) > 760:
        big = B.font(B.F_BOLD, big.size - 4)
        w1, w2 = B.text_img("websites", big, white, track=-0.045), B.text_img("boredom", big, white, track=-0.045)
    top = B.text_img("top 5", B.font(B.F_SEMI, 62), white, track=-0.02)
    fav = B.text_img("(#4 is my favorite)", B.font(B.F_SEMI, 44), white, track=-0.01)
    save = B.text_img("save for later!", B.font(B.F_SEMI, 38), white)
    tg = B.tag("to cure your", 38)
    cx = W // 2
    hsum = top.height + 18 + w1.height + 6 + tg.height + 4 + w2.height + 26 + fav.height + 30 + save.height
    y = int(840 - hsum / 2)
    els = []
    x1 = cx - w1.width // 2
    els.append((top, x1 + 6, y)); y += top.height + 18
    els.append((w1, x1, y)); y += w1.height + 6
    els.append((tg, x1 + 88, y - 10)); y += tg.height + 4
    els.append((w2, cx - w2.width // 2, y)); y += w2.height + 26
    els.append((fav, cx - fav.width // 2, y)); y += fav.height + 30
    els.append((save, cx - save.width // 2, y))
    x0 = min(e[1] for e in els); y0 = min(e[2] for e in els)
    x1_ = max(e[1] + e[0].width for e in els); y1_ = max(e[2] + e[0].height for e in els)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for e, x, yy in els:
        if e is not tg:
            layer.alpha_composite(e, (x, yy))
    B.stars(im, rng, [(x0, y0, x1_, y1_)], rng.randint(14, 19))
    lum = float(np.asarray(im.convert("L").crop((x0, y0, x1_, y1_)), dtype=np.float32).mean()) / 255
    k = min(max((lum - 0.42) * 1.3, 0.0), 0.38)
    if k > 0:
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).ellipse((x0 - 90, y0 - 80, x1_ + 90, y1_ + 80), fill=int(255 * k))
        dim = Image.new("RGBA", (W, H), (20, 40, 70, 0))
        dim.putalpha(m.filter(ImageFilter.GaussianBlur(80)))
        im.alpha_composite(dim)
    sh = add_shadow(layer, blur=3, opacity=0.55, offset=(0, 2), grow=1, pad=0)
    sh = add_shadow(sh, blur=22, opacity=0.4, offset=(0, 0), grow=8, pad=0)
    im.alpha_composite(sh)
    im.alpha_composite(add_shadow(tg, blur=6, opacity=0.3, offset=(0, 2), grow=1, pad=20),
                       (els[2][1] - 20, els[2][2] - 20))
    return im.convert("RGB"), [(x0, y0, x1_, y1_)]


def libs() -> tuple[list[Path], dict[str, list[Path]]]:
    bgs = sorted(f for f in BG.glob("*") if f.suffix.lower() in B.EXT and not f.name.startswith("_"))
    shots = {k: sorted(f for f in B.SHOTS.glob(f"{k}_*") if f.suffix.lower() in B.EXT) for k, *_ in B.SITES}
    return bgs, shots


def music(work: Path, end: float) -> Path:
    out = work / f"1391_music_{end:.3f}.wav"
    if not out.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(MUSIC), "-t", f"{end:.3f}",
                        "-af", f"afade=t=out:st={end - 0.25:.3f}:d=0.25,loudnorm=I=-14:TP=-1.5:LRA=11",
                        "-ar", "44100", "-ac", "2", str(out)], check=True)
    return out


def render(frames: list[Path], wav: Path, out: Path, cuts: list[float], end: float) -> None:
    lst = out.with_suffix(".txt")
    durs = [b - a for a, b in zip(cuts, cuts[1:] + [end])]
    lines = []
    for f, d in zip(frames, durs):
        lines += [f"file '{f.as_posix()}'", f"duration {d:.4f}"]
    lines.append(f"file '{frames[-1].as_posix()}'")
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(wav),
                    "-vf", f"fps={FPS},format=yuv420p", "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                    "-cq", "27", "-b:v", "0", "-maxrate", "6M", "-bufsize", "12M", "-c:a", "aac", "-b:a", "160k",
                    "-t", f"{end:.3f}", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=",
                    "-movflags", "+faststart", str(out)], check=True)
    lst.unlink()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=3)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--seed", type=int, default=1391)
    ap.add_argument("--bars", type=int, default=1, help="смена слайда каждые N тактов (1 такт = 1.58 с)")
    ap.add_argument("--half", action="store_true", help="смена 2 раза за такт — на 1-й и 3-й долях (видео ~5.5 с)")
    ap.add_argument("--exclude", type=Path, action="append", default=[],
                    help="manifest.json уже выданной партии — её сочетания не повторяем (можно несколько)")
    ap.add_argument("--start", type=int, default=1, help="номер первого ролика (продолжение нумерации прошлой партии)")
    a = ap.parse_args()
    bgs, shots = libs()
    if not bgs or not all(shots.values()):
        raise SystemExit(f"нет фонов ({len(bgs)}) или скринов")
    out = a.out or ROOT / "output" / ("1391_test" if a.test else f"1391_{a.n}")
    out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "output" / "_work" / "1391_frames"
    work.mkdir(parents=True, exist_ok=True)
    cuts, end = timing(a.bars, a.half)
    wav = music(ROOT / "output" / "_work", end)
    pals = {bg: palettes(bg) for bg in bgs}
    rng = random.Random(a.seed)
    seen = {(m["bg"], m["palette"], *m["shots"]) for f in a.exclude for m in json.loads(f.read_text(encoding="utf-8"))}
    manifest = []
    print(f"смены: {[round(c, 3) for c in cuts]} конец {end:.3f}")
    for i in range(a.start, a.start + a.n):
        for _ in range(500):
            bg = rng.choice(bgs)
            pal = rng.choice(pals[bg])
            pick = tuple(rng.choice(shots[k]) for k, *_ in B.SITES)
            key = (bg.name, pal) + tuple(p.name for p in pick)
            if key not in seen:
                break
        else:
            raise SystemExit("не нашлось нового сочетания за 500 попыток")
        seen.add(key)
        B.PAL = B.PALETTES[pal]
        r = random.Random(a.seed * 10000 + i)
        slides = [slide_cover(bg, r)] + [slide_site(k, pick[k], bg, r) for k in range(len(B.SITES))]
        fr = []
        for k, (im, boxes) in enumerate(slides, 1):
            for b in boxes:
                bad = check_box(W, H, b)
                if bad:
                    raise SystemExit(f"{i:03d} слайд {k}: текст вне безопасной зоны {b} — {bad}")
            p = work / f"{i:03d}_{k}.png"
            im.save(p)
            fr.append(p)
        mp4 = out / f"{i:03d}_1391.mp4"
        render(fr, wav, mp4, cuts, end)
        if a.test:
            sheet = Image.new("RGB", (270 * len(slides), 480))
            for k, (im, boxes) in enumerate(slides):
                q = draw_overlay(im)
                for b in boxes:
                    ImageDraw.Draw(q).rectangle(b, outline=(255, 200, 0), width=5)
                sheet.paste(q.resize((270, 480)), (270 * k, 0))
            sheet.save(out / f"_qa_{i:03d}.jpg", quality=85)
        manifest.append({"video": mp4.name, "bg": bg.name, "palette": pal, "shots": [p.name for p in pick]})
        print(f"  {mp4.name}", flush=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    print(f"готово: {a.n} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
