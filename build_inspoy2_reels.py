#!/usr/bin/env python3
"""
Инспой 2 (ID 1) — копия ролика TikTok @girlyvibez96 7611196616871283991: доски образов «clean & classy» (вырезанные вещи на
белом) сменяются каждые ~0.4 с на каждую долю трека (клиент: «по биту»), по центру мелкий белый текст «the definition of clean & classy:» (ТЗ: «текст
центральный» — копируем). Звук рефа (buteravfx «son original» 7581918415426702102, с 0 с — корреляция 0.99).
Последние ~2.25 с (как у прошлого Inspoy, клиент: скрин на последних 2–2.5 с): «inspoy really gets my pinterest brain 😭» +
карточка Inspoy из App Store, доски под ними продолжают меняться. 9:16, ~7.67 с (ТЗ: до 8 с).
Доски — отредаченные в Flow кадры рефа (downloads/inspoy2/edited, по 2 на кадр рефа). В каждом ролике 19 своих досок,
TT и YT — одним списком, наборы и порядок у всех разные.

  python build_inspoy2_reels.py -n 2 --out output/_work/inspoy2_test --boards downloads/inspoy_found/gen51   # проверка формата
  python build_inspoy2_reels.py --tt 150 --yt 150          # → output/inspoy2_TT_150 + output/inspoy2_YT_150
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

from PIL import Image, ImageChops, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1380_carousels as C  # noqa: E402  (mixed_line — TikTok-шрифт с Apple-эмодзи)
import build_dad_trucker_carousels as D  # noqa: E402  (store_card — карточка Inspoy из App Store)
from core.safe_zones import check_box  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402

W, H, FPS = 1080, 1920, 30
MUSIC = ROOT / "downloads" / "inspoy2" / "music" / "buteravfx_son_original_7581918415426702102.mp3"
BOARDS = ROOT / "downloads" / "inspoy2" / "edited"
# смены досок в рефе (с), дальше — тот же шаг 0.4 с
# клиент: «по биту» — доска меняется на каждую долю трека (librosa, 132.5 BPM, шаг ~0.453 с)
BEATS = [0.093, 0.546, 0.998, 1.451, 1.881, 2.357, 2.81, 3.262, 3.715, 4.168, 4.609, 5.074, 5.515, 5.979, 6.432, 6.885,
         7.326, 7.767, 8.243, 8.696, 9.137, 9.59, 10.043, 10.495, 10.948, 11.389, 11.865]
N_CUTS = 16                                              # 17 досок, ролик ~7.67 с (ТЗ: до 8 с)
CARD_CUT = 11                                            # с 12-й смены — подпись + App Store (последние ~2.25 с)
SS_OPTS = [0.0, BEATS[2] - BEATS[0], BEATS[4] - BEATS[0]]   # старт звука: с 0 или на 2/4 доли позже — сетка та же


def timing(ss: float) -> tuple[list[float], float, float]:
    """Смены досок (с от начала ролика) на долях трека, длина ролика (до следующей доли) и начало финала."""
    rel = [round(b - ss, 3) for b in BEATS if b - ss > 0.3]
    cuts = rel[:N_CUTS]
    return cuts, rel[N_CUTS], cuts[CARD_CUT]


REF_TXT = ["the definition of clean &", "classy:"]       # центральный текст рефа, переносы как в рефе
REF_PX, REF_CY = 44, 0.465
END_TXT = ["inspoy really gets", "my pinterest brain 😭"]  # ТЗ дословно, перенос по смыслу
END_PX, END_CY = 58, 0.36


def text_block(text: str, px: int) -> Image.Image:
    """Белый TikTok-текст с тонкой тёмной каймой и мягкой тенью — читается и на белом фоне досок, и на чёрных вещах."""
    raw = C.mixed_line(text, C.B.R._load_font(px), (255, 255, 255), int(px * 1.05))
    pad = 6
    big = Image.new("RGBA", (raw.width + 2 * pad, raw.height + 2 * pad), (0, 0, 0, 0))
    big.alpha_composite(raw, (pad, pad))
    edge = big.getchannel("A").filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(0.8))
    rim = Image.new("RGBA", big.size, (20, 20, 20, 0))
    rim.putalpha(ImageChops.multiply(edge, Image.new("L", big.size, 150)))
    rim.alpha_composite(big)
    return add_shadow(rim, blur=6, opacity=0.35, offset=(0, 3), grow=2)


def put_lines(im: Image.Image, lines: list[str], cy: float, px: int) -> list[tuple]:
    blocks = [text_block(t, px) for t in lines]
    step = int(px * 1.22)
    y0 = int(cy * H - step * (len(lines) - 1) / 2)
    boxes = []
    for k, b in enumerate(blocks):
        x, y = (W - b.width) // 2, y0 + k * step - b.height // 2
        im.alpha_composite(b, (x, y))
        bb = b.getchannel("A").point(lambda v: 255 if v > 120 else 0).getbbox()
        boxes.append((x + bb[0], y + bb[1], x + bb[2], y + bb[3]))
    return boxes


def board(p: Path, rng: random.Random) -> Image.Image:
    """Доска на белом 9:16: вписана целиком, свой небольшой масштаб и сдвиг (у каждого ролика свои)."""
    im = Image.open(p).convert("RGB")
    if rng.random() < 0.5:                              # зеркало — вещи без надписей, раскладка остаётся «живой»
        im = ImageOps.mirror(im)
    s = rng.uniform(0.86, 0.94)
    im = ImageOps.contain(im, (int(W * s), int(H * s)), Image.Resampling.LANCZOS)
    bg = Image.new("RGB", (W, H), (255, 255, 255))
    x = (W - im.width) // 2 + rng.randint(-14, 14)
    y = (H - im.height) // 2 + rng.randint(-24, 24)
    bg.paste(im, (x, y))
    return bg


def frame_main(p: Path, rng: random.Random) -> Image.Image:
    im = board(p, rng).convert("RGBA")
    for b in put_lines(im, REF_TXT, REF_CY, REF_PX):
        if bad := check_box(W, H, b):
            raise SystemExit(f"текст вне безопасной зоны {b} — {bad}")
    return im.convert("RGB")


def frame_end(p: Path, rng: random.Random) -> Image.Image:
    im = board(p, rng).convert("RGBA")
    boxes = put_lines(im, END_TXT, END_CY, END_PX)
    card = D.store_card()
    cy = boxes[-1][3] + 46
    im.alpha_composite(card, ((W - card.width) // 2, cy))
    pad = (card.width - D.CARD_W) // 2
    boxes.append(((W - card.width) // 2 + pad, cy + pad, (W + card.width) // 2 - pad, cy + card.height - pad))
    for b in boxes:
        if bad := check_box(W, H, b):
            raise SystemExit(f"финал вне безопасной зоны {b} — {bad}")
    return im.convert("RGB")


def pool(d: Path) -> list[Path]:
    return sorted(p for p in d.glob("*.*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))


def plan(n: int, seed: int, boards: Path) -> list[dict]:
    """n роликов: у каждого 19 досок (наименее использованные), набор+порядок не повторяются; первая доска — по кругу."""
    rng = random.Random(seed)
    ps = pool(boards)
    k = N_CUTS + 1
    used = {p.name: 0 for p in ps}
    seen, rows = set(), []
    for i in range(1, n + 1):
        while True:
            order = sorted(ps, key=lambda p: used[p.name] + rng.random() * 1.5)[:k]
            rng.shuffle(order)
            while len(order) < k:                       # досок меньше, чем смен: повтор, но не ближе чем через 6
                order.append(rng.choice([p for p in ps if p not in order[-6:]]))
            key = tuple(p.name for p in order)
            if key not in seen:
                break
        seen.add(key)
        for p in order:
            used[p.name] += 1
        rows.append(dict(i=i, boards=list(key), seed=rng.randrange(1 << 30), ss=SS_OPTS[(i - 1) // 2 % len(SS_OPTS)]))
    return rows


def render(r: dict, boards: Path, out: Path, work: Path) -> Path:
    rng = random.Random(r["seed"])
    fr = work / f"{out.parent.name}_{out.stem}"
    fr.mkdir(parents=True, exist_ok=True)
    cuts, TOTAL, CARD_AT = timing(r["ss"])
    bounds = [0.0] + cuts
    fb = [round(b * FPS) for b in bounds] + [round(TOTAL * FPS)]
    ins, fc, labels = [], [], []
    for k, name in enumerate(r["boards"]):
        end = bounds[k] >= CARD_AT - 1e-6
        p = fr / f"{k:02d}.png"
        (frame_end if end else frame_main)(boards / name, rng).save(p, compress_level=1)
        ins += ["-i", str(p)]
        fc.append(f"[{k}:v]format=yuv420p,loop=loop={fb[k + 1] - fb[k] - 1}:size=1:start=0,settb=1/{FPS},setpts=N[g{k}]")
        labels.append(f"[g{k}]")
    n = len(labels)
    fc.append("".join(labels) + f"concat=n={n}:v=1:a=0[v]")
    ins += ["-ss", f"{r['ss']:.3f}", "-t", f"{TOTAL + 0.3:.2f}", "-i", str(MUSIC)]
    fc.append(f"[{n}:a]atrim=0:{TOTAL:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
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
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("--out", type=Path, help="тест: -n роликов в одну папку")
    ap.add_argument("--tt", type=int, default=0)
    ap.add_argument("--yt", type=int, default=0)
    ap.add_argument("--boards", type=Path, default=BOARDS)
    ap.add_argument("--seed", type=int, default=7611)
    ap.add_argument("--suffix", default="1")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    boards = a.boards if a.boards.is_absolute() else ROOT / a.boards
    rows = plan(a.tt + a.yt if (a.tt or a.yt) else a.n, a.seed, boards)
    jobs = []
    if a.tt or a.yt:
        tt, yt = ROOT / "output" / f"inspoy2_TT_{a.tt}", ROOT / "output" / f"inspoy2_YT_{a.yt}"
        nt = ny = 0
        for r in rows:                                  # по очереди TT / YT
            if (r["i"] % 2 == 1 and nt < a.tt) or ny >= a.yt:
                nt += 1
                jobs.append((tt, nt, r))
            else:
                ny += 1
                jobs.append((yt, ny, r))
    else:
        jobs = [(a.out, r["i"], r) for r in rows]
    work = ROOT / "output" / "_work" / "inspoy2"
    work.mkdir(parents=True, exist_ok=True)
    man: dict = {}
    for d, n, r in jobs:
        d.mkdir(parents=True, exist_ok=True)
        man.setdefault(d.name, {})[f"{n:03d}_{a.suffix}.mp4"] = r
    for name, m in man.items():
        (work / f"manifest_{name}.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    todo = [j for j in jobs if not (j[0] / f"{j[1]:03d}_{a.suffix}.mp4").exists()]
    bad = []
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(render, r, boards, d / f"{n:03d}_{a.suffix}.mp4", work) for d, n, r in todo]
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
