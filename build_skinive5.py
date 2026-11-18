#!/usr/bin/env python3
"""
skinive_5 (айди нет), текстволл по классической схеме «видео + скринкаст», до 8 с — 100 TT + 150 YT, все уникальные
(юзер 2026-11-06):
  0–~2 с    тату-рука, родинка в круге со стрелкой — трекинг, родинка под текстволлом (make_skinive5_tattoo.py);
  ~2–3.6   её лицо — шок-дубль (downloads/skinive3/proxy/copy_C9D09E69…mp4), лёгкий наезд;
            поверх обоих — текстволл ТЗ дословно (белый TikTok + обводка) В НИЖНЕЙ части безопасной зоны (верх ≥ 1060,
            низ = 1532): лицо/глаза и тату с родинкой (на 0.45 H) текстом не закрыты;
  далее     чисто: App Store (страница видна 1.9 с, тап «Open») → фото ЗЛОКАЧЕСТВЕННОЙ родинки в редакторе → «Skinive AI verarbeitet…» →
            шкала Melanom 98 % и/или «Hohes Risiko». Скан — ТОЛЬКО downloads/skinive4/IMG_2706.MP4 (как skinive_4).
Звук — как skinive_3/4 (реф skinive_2 по кругу, S2.music_loop).

  python make_skinive5_tattoo.py                     # один раз: кэш тату-крупняков
  python build_skinive5.py --only 1,2,3 --out output/_work/skinive5_test
  python build_skinive5.py --range 1-100 --tag tt --out output/skinive5_TT_100
  python build_skinive5.py --range 101-250 --tag yt --out output/skinive5_YT_150
"""

from __future__ import annotations

import argparse
import itertools
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_wall_reels as WL  # noqa: E402  (wall_lines / wall_height / render_wall, безопасная зона)
import build_skinive2 as S2  # noqa: E402  (music_loop — звук skinive_3)

W, H, FPS = 1080, 1920, 30
FACE = ROOT / "downloads" / "skinive3" / "proxy" / "copy_C9D09E69-1675-4B0B-86B4-24EF5AAF998F.mp4"
TAT = ROOT / "output" / "_work" / "skinive5" / "tattoo"
REC = ROOT / "downloads" / "skinive4" / "IMG_2706.MP4"
STORE = ROOT / "downloads" / "skinive" / "store" / "IMG_0134.MP4"
TEXT = ("WAIT GUYS 😭\nhabt ihr eigentlich Muttermale\nneben euren Tattoos?!\nCheckt das mal kurz!\n\n"
        "Wenn ja, müsst ihr unbedingt\ndiese App ausprobieren\nund schauen,\nwas sie euch dazu sagt 👀")
TATTOOS = ["t1", "t2", "t3"]                  # тату-рука: 6381@0.3, 6382@0.5, 6382@6.8 (спокойные окна)
SHOCK = [4.6, 16.8, 23.8, 31.8]               # ладонь ко рту / широко раскрытые глаза / «о» / тревожный взгляд
EDIT = (13.15, 14.30)                         # редактор: фото злокачественной родинки
PROC = (20.25, 50.55)                         # анализ с тепловой картой
GAUGE = (50.80, 55.15)                        # 72 % → 98 % Melanom
RISK = {"photo": (55.55, 57.10), "heat": (61.60, 62.10)}
STORE_B = 9.85                                # стор: страница неподвижна ~7.9–9.35 → тап «Open» (9.38) → открытие
STORE_TAP = 9.38
STORE_PAGE = 1.9                              # юзер: «кадр с аппкой в сторе слишком быстрый» — страница видна 1.9 с
APP_Y, STORE_Y = 120, 150
MAX_T = 8.0
WALL_TOP_MIN = 1060                           # ниже подбородка на лице, ниже родинки на тату


def wall_low(dest: Path) -> None:
    """Крупнейший кегль (≤ 56) без авто-переносов, при котором блок помещается между WALL_TOP_MIN и низом зоны."""
    n = len([ln for ln in TEXT.splitlines() if ln.strip()])
    px = 56
    while px > 30 and (WL.wall_height(TEXT, px) > WL.Y1 - 8 - WALL_TOP_MIN or
                       len([x for x in WL.wall_lines(TEXT, px) if x]) > n):
        px -= 1
    WL.render_wall(TEXT, px, WL.Y1 - 8 - WL.wall_height(TEXT, px), dest)


def plan(n: int, seed: int = 55) -> list[dict]:
    """Тату × лицо × финал (шкала+риск / только риск, фото / тепловая карта) × зеркало = 96 сочетаний по кругу;
    плюс свои сдвиги, длины, наезд и цвет у каждого ролика."""
    rng = random.Random(seed)
    combos = list(itertools.product(range(len(TATTOOS)), range(len(SHOCK)),
                                    ("gauge_photo", "gauge_heat", "photo", "heat"), (0, 1)))
    rows = []
    for k in range(1, n + 1):
        if (k - 1) % len(combos) == 0:
            rng.shuffle(combos)
        t, s, end, mirror = combos[(k - 1) % len(combos)]
        rows.append(dict(n=k, tat=t, shock=s, end=end, mirror=mirror,
                         t_off=round(rng.uniform(0, 0.25), 2), t_len=round(rng.uniform(1.9, 2.1), 2),
                         s_off=round(rng.uniform(0, 0.3), 2), f_len=round(rng.uniform(1.5, 1.7), 2),
                         zoom=round(rng.uniform(1.0, 1.06), 3), bri=round(rng.uniform(-0.02, 0.03), 3),
                         sat=round(rng.uniform(1.0, 1.1), 3), store0=round(rng.uniform(7.95, 8.1), 2),
                         e0=round(rng.uniform(13.2, 13.7), 2), p_len=round(rng.uniform(0.7, 0.8), 2),
                         total=round(rng.uniform(7.85, 8.0), 2)))
    return rows


def render(r: dict, out: Path, work: Path, tag: str) -> Path:
    name = f"skinive5_{tag}_{r['out_n']:03d}"
    wall = work / f"{name}.png"
    wall_low(wall)
    grade = f"eq=brightness={r['bri']}:saturation={r['sat']}"
    z = r["zoom"]
    zw, zh = round(W * z / 2) * 2, round(H * z / 2) * 2
    mir = ",hflip" if r["mirror"] else ""
    hold = max(0.0, STORE_PAGE - (STORE_TAP - r["store0"]))   # первый (неподвижный) кадр страницы держим дольше
    s_len = STORE_B - r["store0"] + hold
    ed_len = 0.4
    p_speed = (PROC[1] - PROC[0]) / r["p_len"]
    app = f"scale={W}:-2:flags=lanczos,crop={W}:{H}:0:{APP_Y},setsar=1"
    t_wall = r["t_len"] + r["f_len"]
    parts = [
        f"[0:v]trim=start={r['t_off']:.3f}:duration={r['t_len']:.3f},setpts=PTS-STARTPTS,fps={FPS},{grade}{mir},setsar=1[t1]",
        f"[1:v]trim=start={SHOCK[r['shock']] + r['s_off']:.3f}:duration={r['f_len']:.3f},setpts=PTS-STARTPTS,fps={FPS},"
        f"scale={zw}:{zh},crop={W}:{H},{grade}{mir},setsar=1[f1]",
        f"[2:v]trim=start=1:duration={STORE_B - r['store0']:.3f},setpts=PTS-STARTPTS,fps={FPS},"
        f"tpad=start_mode=clone:start_duration={hold:.3f},scale={W}:-2:flags=lanczos,"
        f"crop={W}:{H}:0:{STORE_Y},setsar=1[st]",
        f"[3:v]trim=start=1:duration={ed_len:.3f},setpts=PTS-STARTPTS,fps={FPS},{app}[ed]",
        f"[4:v]trim=start=1:duration={PROC[1] - PROC[0]:.3f},setpts=(PTS-STARTPTS)/{p_speed:.4f},fps={FPS},{app}[pr]",
    ]
    seq = ["t1", "f1", "st", "ed", "pr"]
    inputs = ["-i", str(TAT / f"{TATTOOS[r['tat']]}.mp4"), "-i", str(FACE),
              "-ss", f"{r['store0'] - 1:.3f}", "-i", str(STORE), "-ss", f"{r['e0'] - 1:.3f}", "-i", str(REC),
              "-ss", f"{PROC[0] - 1:.3f}", "-i", str(REC)]
    idx = 5
    used = t_wall + s_len + ed_len + r["p_len"]
    risk_key = "heat" if r["end"].endswith("heat") else "photo"
    if r["end"].startswith("gauge"):
        g_len = 0.45
        g_speed = (GAUGE[1] - GAUGE[0]) / g_len
        parts.append(f"[{idx}:v]trim=start=1:duration={GAUGE[1] - GAUGE[0]:.3f},setpts=(PTS-STARTPTS)/{g_speed:.4f},"
                     f"fps={FPS},{app}[ga]")
        inputs += ["-ss", f"{GAUGE[0] - 1:.3f}", "-i", str(REC)]
        seq.append("ga")
        idx += 1
        used += g_len
    r_len = max(0.4, min(MAX_T, r["total"]) - used)
    a, b = RISK[risk_key]
    nres = round(r_len * FPS)
    parts.append(f"[{idx}:v]trim=start=1:duration={b - a:.3f},setpts=PTS-STARTPTS,fps={FPS},"
                 f"tpad=stop_mode=clone:stop_duration={max(0.0, r_len - (b - a)) + 0.2:.3f},{app},"
                 f"trim=end_frame={nres},setpts=PTS-STARTPTS[rk]")
    inputs += ["-ss", f"{a - 1:.3f}", "-i", str(REC)]
    seq.append("rk")
    idx += 1
    parts.append("".join(f"[{x}]" for x in seq) + f"concat=n={len(seq)}:v=1:a=0[b]")
    parts.append(f"[b][{idx}:v]overlay=0:0:enable='lt(t,{t_wall:.3f})',format=yuv420p[v]")
    total = min(MAX_T, used + nres / FPS)
    dest = out / f"{name}_noid.mp4"
    mus = work / f"{name}.wav"
    S2.music_loop(mus, total)
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-i", str(wall), "-i", str(mus),
                    "-filter_complex", ";".join(parts), "-map", "[v]", "-map", f"{idx + 1}:a", "-t", f"{total:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    wall.unlink()
    mus.unlink()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="номера плана через запятую (тест)")
    ap.add_argument("--range", default="", help="a-b: номера плана (1–250); в файле — нумерация с 1 внутри партии")
    ap.add_argument("--tag", default="test")
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "_work" / "skinive5_test")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = plan(250)
    if a.only:
        keep = set(map(int, a.only.split(",")))
        rows = [r for r in rows if r["n"] in keep]
    elif a.range:
        lo, hi = map(int, a.range.split("-"))
        rows = [r for r in rows if lo <= r["n"] <= hi]
    for i, r in enumerate(rows, 1):
        r["out_n"] = i if a.range else r["n"]
    a.out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "output" / "_work" / "skinive5"
    work.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(a.jobs) as ex:
        for dest in ex.map(lambda r: render(r, a.out, work, a.tag), rows):
            print(f"  {dest.name}", flush=True)
    print(f"готово: {len(rows)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
