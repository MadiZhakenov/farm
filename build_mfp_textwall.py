#!/usr/bin/env python3
"""
MyFitnessPal — текстволлы (ID 1): 20 роликов ≤ 7 с, энергичный вайб. 6 текстов ТЗ дословно (переносы по смыслу),
белый TikTok-шрифт с обводкой по центру (как FollowSpy-стены: build_gw_wall_reels.render_wall), без плашки.
Фоны — 4 TikTok-видео из ТЗ (downloads/mfp_textwall/bg): на видео с готовкой больше роликов
(bg2 танцует и готовит ×7, bg3 повар ×6, bg4 девушки в машине ×4, bg1 лицо ×3). Звук — RAYE «original sound»
из ТЗ (downloads/mfp_textwall/music), с 0 с.
Энергия: фон режется в такт (каждые 2 доли, 112 BPM) с чередующимся наездом; текст стоит.
Уникальность: своё окно клипа, скорость, зум/сдвиг, зеркало, цвет, кегль и высота текста; пары «текст + фон» не повторяются.
bg1: внизу вшита надпись «facecard» (y ≈ 0.80) — кадр всегда обрезан выше неё.

  python build_mfp_textwall.py --out output/myfitnesspal_textwall_20
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

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_wall_reels as WL  # noqa: E402  (render_wall, wall_height, wall_lines — TikTok-шрифт с обводкой)

W, H, FPS = 1080, 1920, 30
SRC = ROOT / "downloads" / "mfp_textwall"
MUSIC = SRC / "music" / "raye_original_sound_7544842099927403286.mp3"
BEATS = [0.07, 0.6, 1.11, 1.63, 2.16, 2.69, 3.23, 3.76, 4.27, 4.78, 5.29, 5.8, 6.34, 6.87]
T_MAX = 6.9                                             # «все ролики до 7 с»

# клип: файл, полезный отрезок (с), сколько роликов, ограничение кадра по высоте (низ окна ≤ доли кадра)
BG = {
    "bg2": dict(f="bg2_7658360530997890311_adapt_lowest_1080_1.mp4", span=(0.0, 16.8), n=7, ymax=1.0),
    "bg3": dict(f="bg3_7563153550042287382_normal_540_0.mp4", span=(0.0, 6.55), n=6, ymax=1.0),
    "bg4": dict(f="bg4_7562580690718526722_adapt_lowest_1080_1.mp4", span=(0.0, 10.8), n=4, ymax=1.0),
    "bg1": dict(f="bg1_7370114787059027206_adapt_lowest_1080_1.mp4", span=(0.0, 7.35), n=3, ymax=0.785),
}

ORIG = [
    "my bf laughed at me for using MyFitnessPal while cooking and said i was \"doing too much.\" three days later i caught "
    "him tracking his ex's location on snap maps. apparently I'M the one who's obsessed with tracking things 😭",
    "my ex said i had ZERO discipline so after we broke up i started cooking instead of ordering takeout every night 😭 "
    "downloaded MyFitnessPal, started tracking my meals and now i'm literally meal prepping on sundays??? he texted me "
    "yesterday. babe i'm busy making salmon 💅",
    "my ex dumped me because i was \"too lazy\" 😭 and honestly i was a mess after that. so i started cooking every night "
    "and tracking my meals on MyFitnessPal just to feel like i had my life together. 3 months later he texted \"i miss us\". "
    "sir you miss the girl who couldn't boil pasta??? 💀",
    "he told me i had no discipline and needed to get my life together. so we broke up, i started cooking and tracking my "
    "meals on MyFitnessPal. two months later he asked me to meal prep for him. sir we're not even together anymore??? 💀",
    "his mom asked how i learned to cook because apparently he told her i couldn't even make eggs. meanwhile i've been "
    "making us dinner every night and logging my recipes on MyFitnessPal. so i sent her my recipes. and told her to ask "
    "her son who actually cooked them 😭",
    "he told me to stop posting my cooking videos because they were \"embarrassing.\" then i found out he was secretly "
    "following my food account from THREE different profiles. babe just ask for the MyFitnessPal recipe like everyone "
    "else 💀",
]
# переносы по смыслу: строка — фраза; пустая строка — пауза между частями истории
WALLS = [
    "my bf laughed at me\nfor using MyFitnessPal\nwhile cooking and said\ni was \"doing too much.\"\n\n"
    "three days later i caught him\ntracking his ex's location\non snap maps.\n\n"
    "apparently I'M the one\nwho's obsessed\nwith tracking things 😭",
    "my ex said i had ZERO discipline\nso after we broke up\ni started cooking instead of\nordering takeout every night 😭\n\n"
    "downloaded MyFitnessPal,\nstarted tracking my meals\nand now i'm literally\nmeal prepping on sundays???\n\n"
    "he texted me yesterday.\nbabe i'm busy making salmon 💅",
    "my ex dumped me\nbecause i was \"too lazy\" 😭\nand honestly\ni was a mess after that.\n\n"
    "so i started cooking every night\nand tracking my meals\non MyFitnessPal\njust to feel like\ni had my life together.\n\n"
    "3 months later\nhe texted \"i miss us\".\nsir you miss the girl\nwho couldn't boil pasta??? 💀",
    "he told me i had no discipline\nand needed to get\nmy life together.\n\n"
    "so we broke up,\ni started cooking\nand tracking my meals\non MyFitnessPal.\n\n"
    "two months later\nhe asked me to meal prep for him.\n\nsir we're not even\ntogether anymore??? 💀",
    "his mom asked how i learned to cook\nbecause apparently he told her\ni couldn't even make eggs.\n\n"
    "meanwhile i've been making us\ndinner every night\nand logging my recipes\non MyFitnessPal.\n\n"
    "so i sent her my recipes.\nand told her to ask her son\nwho actually cooked them 😭",
    "he told me to stop posting\nmy cooking videos\nbecause they were \"embarrassing.\"\n\n"
    "then i found out\nhe was secretly following\nmy food account\nfrom THREE different profiles.\n\n"
    "babe just ask\nfor the MyFitnessPal recipe\nlike everyone else 💀",
]
for _o, _w in zip(ORIG, WALLS):                          # текст клиента дословно — меняются только переносы
    assert " ".join(_w.split()) == " ".join(_o.split()), _w


def plan(seed: int) -> list[dict]:
    rng = random.Random(seed)
    slots = [b for b, c in BG.items() for _ in range(c["n"])]
    rng.shuffle(slots)
    used_pair, used_text = set(), [0] * len(WALLS)
    rows = []
    for i, b in enumerate(slots, 1):
        free = [t for t in range(len(WALLS)) if (t, b) not in used_pair] or list(range(len(WALLS)))  # bg2 ×7 > 6 текстов
        ti = min(free, key=lambda t: (used_text[t], rng.random()))
        used_pair.add((ti, b))
        used_text[ti] += 1
        rows.append(dict(i=i, bg=b, text=ti, seed=rng.randrange(1 << 30)))
    return rows


def wall_png(text: str, px_max: int, dy: int, dest: Path) -> int:
    """Самый крупный кегль ≤ px_max, при котором строки не переносятся сами и блок влезает; центр ± dy."""
    n_lines = len([ln for ln in text.split("\n") if ln.strip()])
    px = px_max
    while px > 26 and (WL.wall_height(text, px) > WL.Y1 - WL.Y0 - 8 or
                       len([x for x in WL.wall_lines(text, px) if x]) > n_lines):
        px -= 1
    h = WL.wall_height(text, px)
    cy = (WL.Y0 + WL.Y1) // 2 + dy
    top = max(WL.Y0 + 4, min(WL.Y1 - 4 - h, int(cy - h / 2)))
    WL.render_wall(text, px, top, dest)
    return px


def segments(r: dict) -> tuple[float, list[tuple[float, float, float]], dict]:
    """Окна клипа под каждый кусок (в такт музыке) + зум/сдвиг/цвет. Возвращает длину ролика и куски (src_a, src_b, zoom)."""
    rng = random.Random(r["seed"])
    c = BG[r["bg"]]
    a0, b0 = c["span"]
    total = min(T_MAX, round((b0 - a0 - 0.05) * FPS) / FPS)  # короткий клип (bg3) — ролик короче, без замедления
    speed = rng.uniform(0.94, min(1.03, (b0 - a0 - 0.03) / total))   # короткий клип — не быстрее, чем он длится
    first = rng.choice([2, 3])                          # режем каждые 2 доли, начиная с доли 2 или 3
    cuts = [0.0] + [BEATS[k] for k in range(first, len(BEATS), 2) if BEATS[k] < total - 0.4] + [total]
    need = total * speed
    slack = max(0.0, (b0 - a0) - need)
    skips = [rng.uniform(0.04, 0.3) for _ in cuts[1:-1]]
    if sum(skips) > slack * 0.7:
        skips = [s * slack * 0.7 / sum(skips) for s in skips]
    start = a0 + rng.uniform(0, max(0.0, slack - sum(skips)))
    segs, t = [], start
    for k in range(len(cuts) - 1):
        d = (cuts[k + 1] - cuts[k]) * speed
        nfr = round(cuts[k + 1] * FPS) - round(cuts[k] * FPS)       # ровно столько кадров у куска — в сумме = длина
        segs.append((round(t, 3), round(t + d, 3), 1.0 if k % 2 == 0 else rng.uniform(1.08, 1.13), nfr))
        t += d + (skips[k] if k < len(skips) else 0)
    if t - (skips[-1] if skips else 0) > b0 + 0.05:
        raise SystemExit(f"{r['i']}: не хватает клипа {r['bg']}")
    look = dict(z=rng.uniform(1.28, 1.36) if c["ymax"] < 1 else rng.uniform(1.06, 1.18), px=rng.uniform(0.3, 0.7),
                py=rng.uniform(0.3, 0.7), flip=rng.random() < 0.5, br=rng.uniform(-0.05, 0.0), ct=rng.uniform(1.0, 1.07),
                sat=rng.uniform(1.0, 1.16), speed=speed, px_max=rng.randint(50, 56), dy=rng.randint(-60, 60))
    return total, segs, look


def render(r: dict, out: Path, work: Path) -> Path:
    total, segs, L = segments(r)
    c = BG[r["bg"]]
    fr = work / out.stem
    fr.mkdir(parents=True, exist_ok=True)
    wall = fr / "wall.png"
    r["px"] = wall_png(WALLS[r["text"]], L["px_max"], L["dy"], wall)
    n = len(segs)
    fc = [f"[0:v]fps={FPS},split={n}" + "".join(f"[r{k}]" for k in range(n))]
    for k, (a, b, zk, nfr) in enumerate(segs):
        z = L["z"] * zk
        # окно зума: по ширине — сдвиг px, по высоте — py, но низ окна не ниже ymax (bg1: надпись «facecard»)
        ymax = c["ymax"]
        y_hi = f"max(0,{ymax}*ih-ih/{z:.4f})"
        # кусок с запасом, растянут по скорости, затем ровно nfr кадров (иначе округления теряли до 7 кадров на ролик)
        fc.append(f"[r{k}]trim=start={a}:end={b + 0.15:.3f},setpts=(PTS-STARTPTS)/{L['speed']:.4f},fps={FPS},"
                  f"tpad=stop_mode=clone:stop=6,trim=end_frame={nfr},setpts=PTS-STARTPTS,"
                  f"crop=w=iw/{z:.4f}:h=ih/{z:.4f}:x=(iw-iw/{z:.4f})*{L['px']:.3f}:y='{y_hi}*{L['py']:.3f}',"
                  f"scale={W}:{H}:flags=lanczos,setsar=1[s{k}]")
    post = ",hflip" if L["flip"] else ""
    fc.append("".join(f"[s{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0,fps={FPS},"
              f"eq=brightness={L['br']:.3f}:contrast={L['ct']:.3f}:saturation={L['sat']:.3f}{post},format=yuv420p[bg]")
    fc.append("[bg][1:v]overlay=0:0:format=auto,format=yuv420p[v]")
    fc.append(f"[2:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
              f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={total - 0.3:.3f}:d=0.3[a]")
    (fr / "graph.txt").write_text(";\n".join(fc), encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(SRC / "bg" / c["f"]), "-i", str(wall), "-i", str(MUSIC),
                    "-filter_complex_script", str(fr / "graph.txt"), "-map", "[v]", "-map", "[a]",
                    "-t", f"{total:.3f}", "-r", str(FPS), "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27",
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
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=2011)
    ap.add_argument("--suffix", default="1")
    ap.add_argument("--only", type=int, nargs="*", help="только эти номера (тест)")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    rows = plan(a.seed)
    if a.only:
        rows = [r for r in rows if r["i"] in a.only]
    a.out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "output" / "_work" / "mfp_textwall"
    work.mkdir(parents=True, exist_ok=True)
    man = {f"{r['i']:03d}_{a.suffix}.mp4": dict(r, total=segments(r)[0], segs=segments(r)[1]) for r in rows}
    (work / f"manifest_{a.out.name}.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(render, r, a.out / f"{r['i']:03d}_{a.suffix}.mp4", work): r for r in rows}
        for f, r in futs.items():
            print(" ", f.result().name, r["bg"], "текст", r["text"] + 1, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
