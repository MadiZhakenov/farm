#!/usr/bin/env python3
"""
skinive_4 (айди нет), текстволл «WAIT, Leute?!» — 100 TT + 200 YT, все уникальные (юзер 2026-11-06), как skinive_150:
  0–6 с     девушка находит что-то на лице (downloads/skinive3/proxy/copy_C9D09E69…mp4, её ролик лица):
            дубль-реакция «WAIT» 3 с + дубль «разглядывает / трогает / отмечает пятно» 3 с, джамп-кат;
            поверх — текстволл ТЗ дословно (FS.wall_png: белый TikTok + обводка, крупнейший кегль в безопасной зоне);
  далее     чисто, без текста: App Store (страница Skinive → тап «Open», обязательный кадр стора) →
            заставка Skinive из записи юзера → фото ЗЛОКАЧЕСТВЕННОЙ родинки в редакторе → «Skinive AI verarbeitet…»
            с тепловой картой → результат: шкала (Melanom 98 %, «Erforderliche Zusatzprüfung») и/или «Hohes Risiko».
Скан — ТОЛЬКО из downloads/skinive4/IMG_2706.MP4 (юзер: «я загрузил злокачественную родинку — используй только этот видос»).
Звук — как skinive_3 (реф skinive_2 по кругу, S2.music_loop; юзер 2026-11-06). Исходники 1080p (лицо — прокси).

  python build_skinive4.py --only 1,2,3 --out output/_work/skinive4_test
  python build_skinive4.py --range 1-100 --tag tt --out output/skinive4_TT_100
  python build_skinive4.py --range 101-300 --tag yt --out output/skinive4_YT_200
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
import build_followspy_walls as FS  # noqa: E402  (wall_png)
import build_skinive2 as S2  # noqa: E402  (music_loop — звук skinive_3)

W, H, FPS = 1080, 1920, 30
FACE = ROOT / "downloads" / "skinive3" / "proxy" / "copy_C9D09E69-1675-4B0B-86B4-24EF5AAF998F.mp4"
REC = ROOT / "downloads" / "skinive4" / "IMG_2706.MP4"
STORE = ROOT / "downloads" / "skinive" / "store" / "IMG_0134.MP4"
TEXT = ("WAIT, Leute?!\nIch habe gerade eine Muttermal\nauf meinem Gesicht entdeckt,\ndie ich legit noch nie\n"
        "bewusst wahrgenommen habe.\nHab sie bei Skinive gescannt\nund das Ergebnis\nhat mich erstmal stoppen lassen.\n\n"
        "Checkt mal eure eigenen Muttermale.\nIhr wisst nie, was euch auffällt. 😭\n\n(Ersetzt keinen Hautarzt.)")
# дубли лица (старт, 3 с), отсмотрены покадрово
SHOCK = [4.6, 16.8, 23.8, 31.8]               # ладонь ко рту / широко раскрытые глаза / «о» / тревожный взгляд
LOOK = [1.5, 12.5, 26.0]                      # разглядывает щёку / палец на щеке / отмечает пятно ручкой
T_TAKE = 3.0
# запись скана (886×1920 → 1080×2340, кроп y 120): заставка, редактор с родинкой, анализ, шкала, «Hohes Risiko»
SPLASH = (1.62, 2.30)
EDIT = (13.15, 14.30)
PROC = (20.25, 50.55)
GAUGE = (50.80, 55.15)                        # 72 % → 98 % Melanom
RISK = {"photo": (55.55, 57.10), "heat": (61.60, 62.10)}   # heat — после прокрутки вверх (до 61.55)
STORE_A, STORE_B = 8.70, 9.90                 # стор: страница → тап «Open» → открытие
APP_Y, STORE_Y = 120, 150


def plan(n: int, seed: int = 44) -> list[dict]:
    """Сочетания: реакция × разглядывание × финал (шкала+риск / только риск, фото / тепловая карта) × зеркало лица;
    плюс свои сдвиги, длины и цвет у каждого ролика."""
    rng = random.Random(seed)
    combos = list(itertools.product(range(len(SHOCK)), range(len(LOOK)), ("gauge_photo", "gauge_heat", "photo", "heat"),
                                    (0, 1)))
    rows = []
    for k in range(1, n + 1):
        if (k - 1) % len(combos) == 0:
            rng.shuffle(combos)
        s, l, end, mirror = combos[(k - 1) % len(combos)]
        rows.append(dict(n=k, shock=s, look=l, end=end, mirror=mirror,
                         s_off=round(rng.uniform(0, 0.3), 2), l_off=round(rng.uniform(0, 0.3), 2),
                         zoom=round(rng.uniform(1.0, 1.06), 3), bri=round(rng.uniform(-0.02, 0.03), 3),
                         sat=round(rng.uniform(1.0, 1.1), 3), p_len=round(rng.uniform(1.8, 2.2), 2),
                         r_len=round(rng.uniform(1.6, 2.0), 2), store0=round(rng.uniform(8.6, 8.9), 2)))
    return rows


def render(r: dict, out: Path, work: Path, tag: str) -> Path:
    name = f"skinive4_{tag}_{r['out_n']:03d}"
    wall = work / f"{name}.png"
    FS.wall_png(TEXT, wall)
    grade = f"eq=brightness={r['bri']}:saturation={r['sat']}"
    z = r["zoom"]
    zw, zh = round(W * z / 2) * 2, round(H * z / 2) * 2
    mir = ",hflip" if r["mirror"] else ""
    s_len = STORE_B - r["store0"]
    sp_len = SPLASH[1] - SPLASH[0]
    ed_len = EDIT[1] - EDIT[0]
    p_speed = (PROC[1] - PROC[0]) / r["p_len"]
    app = f"scale={W}:-2:flags=lanczos,crop={W}:{H}:0:{APP_Y},setsar=1"
    parts = [
        f"[0:v]trim=start={SHOCK[r['shock']] + r['s_off']:.3f}:duration={T_TAKE},setpts=PTS-STARTPTS,fps={FPS},"
        f"scale={zw}:{zh},crop={W}:{H},{grade}{mir},setsar=1[f1]",
        f"[1:v]trim=start={LOOK[r['look']] + r['l_off']:.3f}:duration={T_TAKE},setpts=PTS-STARTPTS,fps={FPS},"
        f"scale={round(zw * 1.06 / 2) * 2}:{round(zh * 1.06 / 2) * 2},crop={W}:{H},{grade}{mir},setsar=1[f2]",
        f"[2:v]trim=start=1:duration={s_len:.3f},setpts=PTS-STARTPTS,fps={FPS},scale={W}:-2:flags=lanczos,"
        f"crop={W}:{H}:0:{STORE_Y},setsar=1[st]",
        f"[3:v]trim=start=1:duration={sp_len:.3f},setpts=PTS-STARTPTS,fps={FPS},{app}[sp]",
        f"[4:v]trim=start=1:duration={ed_len:.3f},setpts=PTS-STARTPTS,fps={FPS},{app}[ed]",
        f"[5:v]trim=start=1:duration={PROC[1] - PROC[0]:.3f},setpts=(PTS-STARTPTS)/{p_speed:.4f},fps={FPS},{app}[pr]",
    ]
    seq = ["f1", "f2", "st", "sp", "ed", "pr"]
    inputs = ["-ss", f"{r['store0'] - 1:.3f}", "-i", str(STORE), "-ss", f"{SPLASH[0] - 1:.3f}", "-i", str(REC),
              "-ss", f"{EDIT[0] - 1:.3f}", "-i", str(REC), "-ss", f"{PROC[0] - 1:.3f}", "-i", str(REC)]
    idx = 6
    risk_key = "heat" if r["end"].endswith("heat") else "photo"
    r_len = r["r_len"]
    if r["end"].startswith("gauge"):
        g_len = 0.9
        g_speed = (GAUGE[1] - GAUGE[0]) / g_len
        parts.append(f"[{idx}:v]trim=start=1:duration={GAUGE[1] - GAUGE[0]:.3f},setpts=(PTS-STARTPTS)/{g_speed:.4f},"
                     f"fps={FPS},{app}[ga]")
        inputs += ["-ss", f"{GAUGE[0] - 1:.3f}", "-i", str(REC)]
        seq.append("ga")
        idx += 1
        r_len = max(1.2, r_len - 0.5)
    a, b = RISK[risk_key]
    nres = round(r_len * FPS)
    parts.append(f"[{idx}:v]trim=start=1:duration={b - a:.3f},setpts=PTS-STARTPTS,fps={FPS},"
                 f"tpad=stop_mode=clone:stop_duration={max(0.0, r_len - (b - a)) + 0.2:.3f},{app},"
                 f"trim=end_frame={nres},setpts=PTS-STARTPTS[rk]")
    inputs += ["-ss", f"{a - 1:.3f}", "-i", str(REC)]
    seq.append("rk")
    idx += 1
    parts.append("".join(f"[{x}]" for x in seq) + f"concat=n={len(seq)}:v=1:a=0[b]")
    parts.append(f"[b][{idx}:v]overlay=0:0:enable='lt(t,{2 * T_TAKE:.3f})',format=yuv420p[v]")
    total = 2 * T_TAKE + s_len + sp_len + ed_len + r["p_len"] + (0.9 if r["end"].startswith("gauge") else 0) + nres / FPS
    dest = out / f"{name}_noid.mp4"
    mus = work / f"{name}.wav"
    S2.music_loop(mus, total)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(FACE), "-i", str(FACE), *inputs, "-i", str(wall),
                    "-i", str(mus),
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
    ap.add_argument("--range", default="", help="a-b: номера плана (1–300); в файле — нумерация с 1 внутри партии")
    ap.add_argument("--tag", default="test")
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "_work" / "skinive4_test")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = plan(300)
    if a.only:
        keep = set(map(int, a.only.split(",")))
        rows = [r for r in rows if r["n"] in keep]
    elif a.range:
        lo, hi = map(int, a.range.split("-"))
        rows = [r for r in rows if lo <= r["n"] <= hi]
    for i, r in enumerate(rows, 1):
        r["out_n"] = i if a.range else r["n"]
    a.out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "output" / "_work" / "skinive4"
    work.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(a.jobs) as ex:
        for dest in ex.map(lambda r: render(r, a.out, work, a.tag), rows):
            print(f"  {dest.name}", flush=True)
    print(f"готово: {len(rows)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
