#!/usr/bin/env python3
"""
1380 v2 — видео «male gaze vs female gaze» (Inspoy, ID 1) из фото каруселей (output/1380v2/slides, Flow-рефрейм ближе).
  «when she dresses for the male gaze 🙄» — 4 фото male gaze (из 14: A — ближе, B — деталь со смыслом) по одному на весь экран, смена на каждый бит;
  «when she dress for the ✨ female gaze ✨» — 10 фото (из 16 female A+B и 2 девушек слайда App Store, тоже female-gaze образы);
  с 7-го фото female gaze вместо заголовка — «looking for looks like these? search heeere girls 🤍» + карточка Inspoy
  из App Store (как в карусели) до конца; последнее фото держится лишний бит.
Звук — звук поста-референса (TikTok 7498507974513806085, «Do I Wanna Know?»), склейки ровно на его биты.
Текст — белый TikTok-шрифт с мягкой тенью по центру кадра (как заголовок карусели), тексты ТЗ дословно.
У каждого ролика свои 4 фото male gaze и свой порядок, свой порядок female gaze, свой масштаб (1.00–1.07) и сдвиг кадра — статично, без наезда.

  python build_1380_video.py --test                      # 4 → output/_work/1380v2_video_test
  python build_1380_video.py -n 100 --out output/inspoy_1380_v2_video_100
Смены фото и кусок песни можно подвинуть тюнером: python tuner_1380_video.py (сохраняет downloads/1380/music/_tuner.json).
Вариант 7 с (--variant 7s): фото на каждой полудоле (между битами), CTA + App Store только на последнем фото, ≤ 1.5 с;
  тюнер: python tuner_1380_video.py --variant 7s (сохраняет _tuner_7s.json).
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1380_carousels as C  # noqa: E402  (white_line, store_card — как в карусели)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
SL = ROOT / "output" / "1380v2" / "slides"
MUSIC = ROOT / "downloads" / "1380" / "music" / "do_i_wanna_know_7498507974513806085.mp3"
BEATS = [0.07, 0.77, 1.51, 2.25, 3.07, 3.9, 4.71, 5.55, 6.39, 7.22, 8.08, 8.89, 9.71, 10.54, 11.38, 12.21, 13.05, 13.89]
T0 = BEATS[0]                                          # звук с первого бита — первая смена фото ровно на бите
N_MALE, N_FEMALE, CTA_FROM = 4, 10, 7                  # CTA — с 7-го фото female gaze
TITLE_M = ("when she dresses for the", "male gaze 🙄")         # две строки, как у female — крупнее и читается
TITLE_F = ("when she dress for the", "✨ female gaze ✨")
CTA = ("looking for looks like these?", "search heeere girls 🤍")
TUNE = MUSIC.parent / "_tuner.json"                   # из tuner_1380_video.py: старт звука, смены, конец (время песни)
VARIANT = ""
CTA_MAX, TARGET = None, None                           # для 7 с: CTA не дольше 1.5 с, ролик ~7 с


def set_variant(name: str) -> None:
    global VARIANT, TUNE, CTA_FROM, CTA_MAX, TARGET
    VARIANT = name
    if name == "7s":
        TUNE, CTA_FROM, CTA_MAX, TARGET = MUSIC.parent / "_tuner_7s.json", N_FEMALE, 1.5, 7.0


def defaults() -> dict:
    """Смены по умолчанию (время песни). 7 с: старт как в основном тюнере, смена на каждой полудоле, CTA 1.5 с."""
    n = N_MALE + N_FEMALE
    if VARIANT == "7s":
        main = MUSIC.parent / "_tuner.json"
        start = json.loads(main.read_text(encoding="utf-8"))["start"] if main.exists() else BEATS[4]
        grid = json.loads((MUSIC.parent / "_beats.json").read_text(encoding="utf-8"))["beats"]   # ~0.42 с — доли и полудоли
        cuts = [t for t in grid if t > start + 0.3][:n - 1]
        return {"start": start, "cuts": cuts, "end": round(cuts[-1] + CTA_MAX, 3)}
    return {"start": BEATS[0], "cuts": BEATS[1:n], "end": round(BEATS[n] + (BEATS[n] - BEATS[n - 1]), 3)}


def timing() -> tuple[float, list[float], list[float]]:
    """Старт звука в песне, начала фото и их концы от начала ролика."""
    n = N_MALE + N_FEMALE
    d = json.loads(TUNE.read_text(encoding="utf-8")) if TUNE.exists() else defaults()
    start = d["start"]
    cuts = [0.0] + [c - start for c in d["cuts"]]
    end = d["end"] - start
    assert len(cuts) == n and all(b - a > 0.1 for a, b in zip(cuts, cuts[1:] + [end])), cuts
    return start, cuts, cuts[1:] + [end]


def text_block(lines: tuple, cy: int, px: int = 58, gap: int = 16) -> tuple[Image.Image, list]:
    """Строки белым TikTok-шрифтом с тенью, блок по центру кадра на высоте cy → полный кадр RGBA + рамки текста."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hs = [C.white_line(ln, 780, px)[1][1] for ln in lines]
    y = cy - (sum(hs) + gap * (len(lines) - 1)) // 2
    boxes = []
    for ln, h in zip(lines, hs):
        blk, (tw, th) = C.white_line(ln, 780, px)
        ox, oy = (blk.width - tw) // 2, (blk.height - th) // 2
        x = (W - blk.width) // 2
        im.alpha_composite(blk, (x, y - oy))
        boxes.append((x + ox, y, x + ox + tw, y + th))
        y += h + gap
    return im, boxes


def overlays(work: Path) -> dict[str, Path]:
    """Три слоя текста (общие для всех роликов): male, female, CTA + карточка App Store."""
    work.mkdir(parents=True, exist_ok=True)
    out = {}
    for key, lines in (("male", TITLE_M), ("female", TITLE_F)):
        im, boxes = text_block(lines, H // 2)
        for b in boxes:
            if bad := check_box(W, H, b):
                raise SystemExit(f"{key}: текст вне безопасной зоны {b} — {bad}")
        out[key] = work / f"ov_{key}.png"
        im.save(out[key])
    im, boxes = text_block(CTA, 760)
    card = C.store_card(700)
    cx, cy = (W - card.width) // 2, 900
    im.alpha_composite(card, (cx, cy))
    boxes.append((cx + 20, cy + 20, cx + card.width - 20, cy + card.height - 20))
    for b in boxes:
        if bad := check_box(W, H, b):
            raise SystemExit(f"cta: вне безопасной зоны {b} — {bad}")
    out["cta"] = work / "ov_cta.png"
    im.save(out["cta"])
    return out


def plan(n: int, seed: int) -> list[dict]:
    rnd = random.Random(seed)
    male = sorted((SL / "s1").glob("*.jpg"))
    female = sorted((SL / "s2").glob("*.jpg")) + sorted(p for p in (SL / "s3").glob("*.jpg") if not p.stem.endswith("_B"))  # s3 _B — почти дубли
    assert len(male) >= N_MALE and len(female) >= N_FEMALE, (len(male), len(female))
    rows, seen = [], set()
    while len(rows) < n:
        m = rnd.sample(male, N_MALE)
        f = rnd.sample(female, N_FEMALE)
        key = tuple(p.name for p in m + f)
        if key in seen:
            continue
        seen.add(key)
        shots = [dict(photo=str(p.relative_to(ROOT)), z0=round(rnd.uniform(1.0, 1.07), 3), z1=0,
                      cx=round(rnd.uniform(0.44, 0.56), 3), cy=round(rnd.uniform(0.40, 0.48), 3)) for p in m + f]
        rows.append(dict(i=len(rows) + 1, shots=shots))
    return rows


def render(r: dict, ov: dict, out: Path) -> Path:
    start, cuts, ends = timing()                      # 0, 0.70, 1.44 … — начало каждого фото
    n = len(r["shots"])
    ins, fc, labels = [], [], []
    for k, s in enumerate(r["shots"]):
        a, b = cuts[k], ends[k]
        d = b - a
        nfr = round(b * FPS) - round(a * FPS)
        ins += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d + 0.2:.3f}", "-i", str(ROOT / s["photo"])]
        z0, z1 = s["z0"], s["z1"]
        # статичный кадр (наезд с eval=frame дрожал: размер и сдвиг кадра округлялись по-разному на каждом кадре)
        sw = round(1434 * z0 / 2) * 2
        sh = round(sw * 1200 / 896 / 2) * 2
        x, y = round((sw - W) * s["cx"]), round((sh - H) * s["cy"])
        fc.append(f"[{k}:v]scale={sw}:{sh}:flags=lanczos,crop={W}:{H}:{x}:{y},setsar=1,format=yuv420p,"
                  f"trim=end_frame={nfr},setpts=PTS-STARTPTS[p{k}]")
        labels.append(f"[p{k}]")
    total = ends[-1]
    fc.append("".join(labels) + f"concat=n={n}:v=1:a=0[b]")
    t_f = cuts[N_MALE]
    t_cta = cuts[N_MALE + CTA_FROM - 1]
    k = n
    cur = "b"
    for key, a, b in (("male", 0, t_f), ("female", t_f, t_cta), ("cta", t_cta, total + 1)):
        ins += ["-i", str(ov[key])]
        fa, fb = round(a * FPS) / FPS - 0.5 / FPS, round(b * FPS) / FPS - 0.5 / FPS      # ровно по кадру склейки, без кадра старого текста
        fc.append(f"[{cur}][{k}:v]overlay=0:0:enable='between(t,{max(0.0, fa):.4f},{fb:.4f})'[o{k}]")
        cur, k = f"o{k}", k + 1
    ins += ["-ss", f"{start:.3f}", "-t", f"{total + 0.3:.3f}", "-i", str(MUSIC)]
    fc.append(f"[{k}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
              f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={total - 0.35:.3f}:d=0.35[a]")
    dest = out / f"{r['i']:03d}_1.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fc), "-map", f"[{cur}]", "-map", "[a]",
                    "-t", f"{total:.3f}", "-r", str(FPS), "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27",
                    "-maxrate", "6M", "-bufsize", "12M", "-pix_fmt", "yuv420p",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-c:a", "aac", "-b:a", "160k",
                    "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
                    "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=",
                    "-movflags", "+faststart", str(dest)], check=True)
    return dest


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--seed", type=int, default=13803)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--variant", default="", choices=["", "7s"])
    a = ap.parse_args()
    set_variant(a.variant)
    a.out = a.out or ROOT / "output" / ("inspoy_1380_v2_video_7s_100" if a.variant == "7s" else "inspoy_1380_v2_video_100")
    work = ROOT / "output" / "_work" / "1380v2_video"
    ov = overlays(work)
    rows = plan(a.n, a.seed)
    if a.test:
        a.out = ROOT / "output" / "_work" / "1380v2_video_test"
        rows = rows[:4]
    a.out.mkdir(parents=True, exist_ok=True)
    (work / "plan.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    with ThreadPoolExecutor(a.jobs) as ex:
        for d in ex.map(lambda r: render(r, ov, a.out), rows):
            print(" ", d.name, flush=True)
    print(f"готово: {len(rows)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
