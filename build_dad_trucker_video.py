#!/usr/bin/env python3
"""
Папа-дальнобойщик (Inspoy, ID 1) — карусель как видео: 7 слайдов 9:16 листаются свайпом влево, как фото-карусель
в TikTok (пост @simplyalice10 7705294784352488717), под звук этого поста. Кадры — те же Flow-кадры карусели
(output/dad_trucker_slides/final/s1..s7, по 4 на слайд), тексты ТЗ дословно тем же TikTok-шрифтом с обводкой,
только в безопасной рамке 9:16 (x 140–940, y 200–1540). s7 — карточка Inspoy из App Store, как в карусели.
Свайп заканчивается на доле, смена слайда через 2 доли. Звук стартует с одной из долей 4.81–9.47 с
(первые ~5 с трека почти тишина) — у каждого видео свой старт, длительность 16.9–17.2 с.
Партия TT+YT планируется одним списком: все сочетания кадров разные между обеими папками (нечётные → TT, чётные → YT).

  python build_dad_trucker_video.py -n 3 --out output/_work/inspoy_dad_trucker_video_test
  python build_dad_trucker_video.py --tt 150 --yt 150     # → output/inspoy_dad_trucker_video_TT_150 + _YT_150
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_dad_trucker_carousels as D  # noqa: E402  (vivid, store_card, SLIDES — тексты ТЗ, C.block_for)
from core.safe_zones import check_box, text_rect  # noqa: E402

W, H, FPS = 1080, 1920, 30
X0, Y0, X1, Y1 = text_rect(W, H)
MUSIC = ROOT / "downloads" / "dad_trucker_video" / "music" / "post_7705294784352488717.m4a"
# доли звука поста (librosa beat_track), с
BEATS = [0.49, 1.53, 2.55, 3.58, 4.81, 6.04, 7.24, 8.36, 9.47, 10.59, 11.7, 12.82, 13.96, 15.07, 16.25, 17.32, 18.41,
         19.55, 20.71, 21.8, 22.89, 24.01, 25.1, 26.12, 27.21, 28.33, 29.54, 30.58, 31.7, 32.79, 33.9, 35.02, 36.08, 37.15]
STARTS = [4, 5, 6, 7, 8]                                # индекс доли старта (4 = 4.81 с — тест)
SWIPE = 0.32                                            # длительность свайпа, ease-out (палец толкает и отпускает)


def timing(b0: int) -> tuple[float, list[float], float]:
    """Старт звука, концы 6 свайпов (каждые 2 доли) и длина видео (3 доли после последнего свайпа — карточка App Store)."""
    ss = BEATS[b0] - 0.05
    ends = [round(BEATS[b0 + 2 * j] - ss, 3) for j in range(1, 7)]
    return ss, ends, round(round((BEATS[b0 + 15] - ss) * FPS) / FPS, 3)
# центр и высота полосы текста (доля высоты 9:16): s1 — под лицами, остальные — верхняя полоса над головой/объектом
BAND = [(0.665, 0.15), (0.165, 0.12), (0.17, 0.13), (0.17, 0.13), (0.17, 0.13), (0.165, 0.12), (0.17, 0.13)]
CARD_CY = 0.62


def frame916(src: Path, rng: random.Random) -> Image.Image:
    """Кадр 3:4 → 9:16 (бока режем по центру ± немного), лёгкий зум и сдвиг — свои у каждого видео."""
    im = Image.open(src).convert("RGB")
    z = rng.uniform(1.0, 1.05)
    ch = im.height / z
    cw = ch * W / H
    x = (im.width - cw) / 2 + rng.uniform(-0.03, 0.03) * im.width
    x = max(0.0, min(im.width - cw, x))
    y = rng.uniform(0, im.height - ch)
    return im.crop((round(x), round(y), round(x + cw), round(y + ch))).resize((W, H), Image.Resampling.LANCZOS)


def caption(k: int, rng: random.Random) -> tuple[Image.Image, tuple]:
    text = D.SLIDES[k][0]
    cy, mh = BAND[k]
    cy += rng.uniform(-0.006, 0.006)
    top, bottom = max(int((cy - mh / 2) * H), Y0), min(int((cy + mh / 2) * H), Y1)
    block = D.C.block_for(text, bottom - top, X1 - X0)
    x = max(X0, min(X1 - block.width, int(W / 2 - block.width / 2 + rng.randint(-12, 12))))
    y = max(Y0, min(Y1 - block.height, int((top + bottom) / 2 - block.height / 2)))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.alpha_composite(block, (x, y))
    return layer, (x, y, x + block.width, y + block.height)


def slide(k: int, src: Path, rng: random.Random) -> Image.Image:
    im = D.vivid(frame916(src, rng), rng).convert("RGBA")
    layer, box = caption(k, rng)
    if bad := check_box(W, H, box):
        raise SystemExit(f"слайд {k + 1}: текст вне безопасной зоны {box} — {bad}")
    if k == 6:
        card = D.store_card()
        cx, cy = (W - card.width) // 2, round(CARD_CY * H - card.height / 2)
        im.alpha_composite(card, (cx, cy))
        pad = (card.width - D.CARD_W) // 2
        if bad := check_box(W, H, (cx + pad, cy + pad, cx + card.width - pad, cy + card.height - pad)):
            raise SystemExit(f"карточка App Store вне безопасной зоны — {bad}")
    return Image.alpha_composite(im, layer).convert("RGB")


def xexpr(k: int, ends: list[float], total: float) -> tuple[str, float, float]:
    """x(t) слайда k: въезжает справа (ease-out) и уезжает влево; плюс окно, когда он виден."""
    a_in = ends[k - 1] - SWIPE if k > 0 else -1.0
    a_out = ends[k] - SWIPE if k < len(ends) else 1e6
    e = (f"{W}*pow(1-clip((t-{a_in:.4f})/{SWIPE},0,1),3)"
         f"-{W}*(1-pow(1-clip((t-{a_out:.4f})/{SWIPE},0,1),3))")
    return e, a_in, min(a_out + SWIPE, total + 1)


def render(picks: list[Path], seed: int, b0: int, out: Path, work: Path) -> Path:
    rng = random.Random(seed)
    SS, ends, TOTAL = timing(b0)
    fr = work / f"{out.parent.name}_{out.stem}"           # своя папка у TT и YT с одним номером
    fr.mkdir(parents=True, exist_ok=True)
    n = round(TOTAL * FPS)
    # быстро: 13 кусков подряд — стоп-кадр слайда (картинка декодирована один раз, кадры размножает loop) и свайп
    # (два слайда бок о бок, окно 1080 px едет вправо с ease-out). Наложение 7 слоёв на каждый кадр было в 4 раза медленнее.
    m = round(SWIPE * FPS)
    e_fr = [round(x * FPS) for x in ends]                   # кадр, с которого новый слайд стоит целиком
    ins, fc = [], []
    for k, src in enumerate(picks):
        p = fr / f"{k + 1}.png"
        slide(k, src, rng).save(p, compress_level=1)
        ins += ["-i", str(p)]
        outs = [f"h{k}"] + ([f"i{k}"] if k > 0 else []) + ([f"o{k}"] if k < 6 else [])
        fc.append(f"[{k}:v]format=yuv420p,split={len(outs)}" + "".join(f"[{o}]" for o in outs))
    segs = []
    for k in range(7):
        a = e_fr[k - 1] if k > 0 else 0
        b = e_fr[k] - m if k < 6 else n
        fc.append(f"[h{k}]loop=loop={b - a - 1}:size=1:start=0,settb=1/{FPS},setpts=N[H{k}]")
        segs.append(f"[H{k}]")
        if k < 6:
            fc.append(f"[o{k}][i{k + 1}]hstack=inputs=2,loop=loop={m - 1}:size=1:start=0,settb=1/{FPS},setpts=N,"
                      f"crop=w={W}:h={H}:y=0:x='floor({W}*(1-pow(1-n/{m},3))/2)*2'[T{k}]")
            segs.append(f"[T{k}]")
    fc.append("".join(segs) + f"concat=n={len(segs)}:v=1:a=0[v]")
    ins += ["-ss", f"{SS:.2f}", "-t", f"{TOTAL + 0.3:.2f}", "-i", str(MUSIC)]
    fc.append(f"[7:a]atrim=0:{TOTAL:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
              f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=in:d=0.15,afade=t=out:st={TOTAL - 0.8:.3f}:d=0.8[a]")
    script = fr / "graph.txt"
    script.write_text(";\n".join(fc), encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex_script", str(script), "-map", "[v]", "-map", "[a]",
                    "-t", f"{TOTAL:.3f}", "-r", str(FPS), "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27",
                    "-maxrate", "6M", "-bufsize", "12M", "-pix_fmt", "yuv420p",
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
    ap.add_argument("--out", type=Path, help="тест: -n видео в одну папку")
    ap.add_argument("--tt", type=int, default=0)
    ap.add_argument("--yt", type=int, default=0)
    ap.add_argument("--seed", type=int, default=7705)
    ap.add_argument("--suffix", default="1")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    pools = [sorted((D.SL / f"s{k}").glob("*.jpg")) for k in range(1, 8)]
    prng = random.Random(a.seed)
    combos = list(itertools.product(*[range(len(p)) for p in pools]))
    prng.shuffle(combos)
    used: dict = {}
    total_n = a.tt + a.yt if (a.tt or a.yt) else a.n
    rows = []
    for i in range(1, total_n + 1):                     # сочетание с наименее использованными кадрами
        best = min(combos[:3000], key=lambda c: (sum(used.get((k, j), 0) for k, j in enumerate(c)), prng.random()))
        combos.remove(best)
        for k, j in enumerate(best):
            used[(k, j)] = used.get((k, j), 0) + 1
        rows.append([i, [pools[k][j] for k, j in enumerate(best)], a.seed * 1000 + i, STARTS[(i - 1) // 2 % len(STARTS)]])
    jobs = []                                           # (папка, номер в папке, строка плана)
    if a.tt or a.yt:
        tt, yt = ROOT / "output" / f"inspoy_dad_trucker_video_TT_{a.tt}", ROOT / "output" / f"inspoy_dad_trucker_video_YT_{a.yt}"
        nt = ny = 0
        for r in rows:                                  # по очереди TT / YT, пока не набрали каждую
            if (r[0] % 2 == 1 and nt < a.tt) or ny >= a.yt:
                nt += 1
                jobs.append((tt, nt, r))
            else:
                ny += 1
                jobs.append((yt, ny, r))
    else:
        jobs = [(a.out, r[0], r) for r in rows]
    work = ROOT / "output" / "_work" / "dad_trucker_video"
    work.mkdir(parents=True, exist_ok=True)
    for d in {j[0] for j in jobs}:
        d.mkdir(parents=True, exist_ok=True)
    jobs = [j for j in jobs if not (j[0] / f"{j[1]:03d}_{a.suffix}.mp4").exists()]
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(render, r[1], r[2], r[3], d / f"{n:03d}_{a.suffix}.mp4", work) for d, n, r in jobs]
        bad = []
        for (d, n, r), f in zip(jobs, futs):
            try:
                print(" ", d.name, f.result().name, [p.name for p in r[1]], "start", BEATS[r[3]], flush=True)
            except Exception as e:                      # noqa: BLE001 — не роняем партию, недоделанное удаляем
                (d / f"{n:03d}_{a.suffix}.mp4").unlink(missing_ok=True)
                bad.append(f"{d.name}/{n:03d}")
                print("  ОШИБКА", d.name, n, e, flush=True)
    plan = [[r[0], [p.name for p in r[1]], r[2], r[3]] for r in rows]
    (work / f"plan_{'tt%d_yt%d' % (a.tt, a.yt) if (a.tt or a.yt) else a.out.name}.json").write_text(
        json.dumps(plan, indent=1), encoding="utf-8")
    if bad:
        print("не собрались (перезапусти ту же команду — доделает только их):", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
