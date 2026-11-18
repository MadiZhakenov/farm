#!/usr/bin/env python3
"""
Korean OneState 2 (ID 1) — «топ-3 игр, которые закончат вашу дружбу», 1-е место — наш OneState. ТЗ 16.11:
  заголовок сверху (дословно): «친구랑 하면 우정 박살나는 모바일 게임» / «TOP 3 (1위는 끝까지)»;
  №3 Stumble Guys (스텀블 가이즈) 3 с → №2 Among Us (어몽어스) 3 с → №1 OneState (원스테이트.) 5 с + сверху промокод
  (баннер клиента OneState_PromoBanner_V2_Loop_NoAmount_KO_04_STATEDQVH.mov).
Вид — как примеры клиента (downloads/korea_onestate2/example, OneState_KO_top3_v19–24): чужие игры — полоса 16:9 по
центру на размытом фоне, над ней «N위 — название»; OneState — вертикально на весь экран (исходники 9x16), плашка сверху.
Игры: официальные трейлеры (Stumble Guys — геймплейные куски без заставок, Among Us — геймплейный трейлер Innersloth).
Звук — звук кусков. 200 TT + 200 YT.

  python build_korea_onestate2.py --test            # 5 → output/_work/korea2/test
"""

from __future__ import annotations

import argparse
import random
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import gpu_ffmpeg as G  # noqa: E402

W, H, FPS = 1080, 1920, 30
D = ROOT / "downloads" / "korea_onestate2"
WORK = ROOT / "output" / "_work" / "korea2"
FONT = Path(r"C:\Windows\Fonts\malgunbd.ttf")
BANNER = D / "banner" / "banner.mov"
TITLE = [("친구랑 하면 우정 박살나는", (255, 255, 255)), ("모바일 게임", (255, 255, 255)),
         ("TOP 3 (1위는 끝까지)", (255, 214, 10))]
LABELS = ["3위 — 스텀블 가이즈", "2위 — 어몽어스", "1위 — 원스테이트."]
DUR = [3.0, 3.0, 5.0]
BAND_H = 608
BAND_Y = (H - BAND_H) // 2 + 60                         # полоса чуть ниже центра: сверху заголовок и подпись места
# геймплейные куски трейлеров (без заставок/титров), секунды
STUMBLE = [("stumble_pqXx6V7XSiM", a, b) for a, b in ((0.3, 7.5), (9.2, 21.5), (23.2, 29.6), (32.0, 39.5), (43.0, 47.5))] + \
          [("stumble_wSlpZ96N5aM", a, b) for a, b in ((2.2, 5.5), (8.2, 25.5))]
AMONG = [("amongus_0YKjFoGxbec", a, b) for a, b in ((0.2, 5.6), (8.0, 17.4), (18.0, 31.0))]
OS = ["Army_job", "Police_job_1", "Police_fighting_with_gang", "Mechanic_job_1"]
OS_ALL = OS + ["Crystals", "Mines_job_1"]   # партия: только окна без сбоев записи   # зрелищные; шахта/кристаллы — скучно


def motion_windows(name: str, dur: float = 3.2) -> list[tuple[str, float, float]]:
    """Геймплейные отрезки no-copyright видео: секунды с заметным движением (меню, ожидание, чат голосования —
    почти неподвижны). Кэш в WORK."""
    import json
    import numpy as np
    cf = WORK / f"mot_{name}.json"
    if cf.exists():
        return [tuple(x) for x in json.loads(cf.read_text())]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-i", str(D / "games" / f"{name}.mp4"), "-vf",
                          "fps=4,scale=96:54", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    rgb = np.frombuffer(raw, np.uint8).reshape(-1, 54, 96, 3).astype(np.float32)
    a = rgb.mean(3)
    d = np.abs(np.diff(a, axis=0)).mean((1, 2))
    n = len(d) // 4
    sec = np.array([d[i * 4:(i + 1) * 4].mean() for i in range(n)])
    good = sec > np.percentile(sec, 45)
    # не геймплей: чат/голосование (большая светло-серая панель), карта (большие ровные насыщенные области),
    # чёрные заставки (Impostor, «was not the Impostor»), меню ожидания
    for i in range(n):
        f = rgb[i * 4:(i + 1) * 4].reshape(-1, 3)
        mx, mn = f.max(1), f.min(1)
        gray_light = ((mx - mn < 18) & (mx > 150)).mean()
        sat = ((mx - mn) > 90).mean()
        dark = (mx < 30).mean()
        if gray_light > 0.25 or dark > 0.6 or (name.startswith("nc_amongus") and sat > 0.35):
            good[i] = False
    out, i = [], 0
    while i < len(good):
        if good[i]:
            j = i
            while j < len(good) and good[j]:
                j += 1
            if j - i >= dur + 0.5:
                out.append((name, i + 0.3, j - 0.3))
            i = j
        i += 1
    WORK.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps(out))
    return out


def font(px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), px)


def text_png(lines: list[tuple[str, tuple]], px: int, cy: int, dest: Path, stroke: float = 0.09) -> None:
    """Белый (и жёлтый) жирный корейский текст с чёрной обводкой, по центру, середина блока на cy; ширина ≤ 800."""
    while max(font(px).getlength(t) for t, _ in lines) > 800 - 2 * px * stroke and px > 30:
        px -= 2
    f = font(px)
    step = int(px * 1.22)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top = cy - step * len(lines) // 2
    for i, (t, col) in enumerate(lines):
        d.text(((W - f.getlength(t)) / 2, top + i * step), t, font=f, fill=col + (255,),
               stroke_width=max(3, round(px * stroke)), stroke_fill=(0, 0, 0, 255))
    img.save(dest)


def job(rng: random.Random, n: int, tag: str) -> dict:
    def win(pool, dur):
        f, a, b = rng.choice([p for p in pool if p[2] - p[1] >= dur + 0.2])
        return dict(f=f, t=round(rng.uniform(a, b - dur - 0.1), 2))
    osf = rng.choice(OS)
    osd = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(D / "os_src" / f"{osf}.mp4")], capture_output=True, text=True).stdout)
    return dict(n=n, tag=tag, s3=win(STUMBLE, DUR[0]), s2=win(AMONG, DUR[1]),
                s1=dict(f=osf, t=round(rng.uniform(0.3, osd - DUR[2] - 0.3), 2)),
                z=round(rng.uniform(1.0, 1.12), 3), zo=round(rng.uniform(1.18, 1.3), 3))


def build(j: dict, dest: Path) -> str:
    tmp = Path(tempfile.mkdtemp(prefix="kos2_"))
    text_png(TITLE, 70, 300, tmp / "title.png")
    for i, lab in enumerate(LABELS):
        text_png([(lab, (255, 255, 255))], 64, BAND_Y - 70 if i < 2 else 720, tmp / f"lab{i}.png")
    s3, s2, s1 = j["s3"], j["s2"], j["s1"]
    ins = ["-ss", f"{s3['t']}", "-t", f"{DUR[0] + 0.2}", "-i", str(D / "games" / f"{s3['f']}.mp4"),
           "-ss", f"{s2['t']}", "-t", f"{DUR[1] + 0.2}", "-i", str(D / "games" / f"{s2['f']}.mp4"),
           "-ss", f"{s1['t']}", "-t", f"{DUR[2] + 0.2}", "-i", str(D / "os_src" / f"{s1['f']}.mp4"),
           "-i", str(tmp / "title.png"), "-i", str(tmp / "lab0.png"), "-i", str(tmp / "lab1.png"), "-i", str(tmp / "lab2.png"),
           "-i", str(BANNER)]
    z = j["z"]
    nf = [round(d * FPS) for d in DUR]
    fc = []
    for i, k in enumerate((0, 1)):                      # чужие игры: полоса 16:9 на размытом фоне
        fc.append(f"[{k}:v]fps={FPS},scale=1920:1080,setsar=1,trim=end_frame={nf[i]},setpts=PTS-STARTPTS,split[a{i}][b{i}];"
                  f"[a{i}]scale=-2:{H},crop={W}:{H},boxblur=28:2,eq=brightness=-0.12[bg{i}];"
                  f"[b{i}]crop=iw/{z}:ih/{z},scale={W}:{BAND_H}[fg{i}];"
                  f"[bg{i}][fg{i}]overlay=0:{BAND_Y}[c{i}];"
                  f"[{4 + i}:v]loop=loop={nf[i] - 1}:size=1:start=0,setpts=N/{FPS}/TB[l{i}];"
                  f"[c{i}][l{i}]overlay=0:0,setsar=1,format=yuv420p[v{i}]")
    zo = j["zo"]                                       # OneState: приближение к низу — верхний интерфейс игры за краем
    fc.append(f"[2:v]fps={FPS},scale={W}:{H},setsar=1,crop=iw/{zo}:ih/{zo}:(iw-iw/{zo})/2:ih-ih/{zo},scale={W}:{H},"
              f"trim=end_frame={nf[2]},"
              f"setpts=PTS-STARTPTS[c2];"
              f"[6:v]loop=loop={nf[2] - 1}:size=1:start=0,setpts=N/{FPS}/TB[l2];"
              f"[7:v]fps={FPS},crop={W}:300:0:810,scale=760:-2,format=yuva420p,setpts=PTS-STARTPTS[bn];"
              f"[c2][l2]overlay=0:0[c2b];[c2b][bn]overlay=(W-w)/2:430:eof_action=repeat,setsar=1,format=yuv420p[v2]")
    tot = sum(nf)
    fc.append(f"[v0][v1][v2]concat=n=3:v=1:a=0[cv];"
              f"[3:v]loop=loop={tot - 1}:size=1:start=0,setpts=N/{FPS}/TB[tl];"
              f"[cv][tl]overlay=0:0,format=yuv420p[v]")
    snd = j.get("snd")
    if snd:                                            # юзер 16.11: звук из TikTok, игры — 0
        ins += ["-i", str(D / "sounds" / f"{snd}.mp3")]
        T = sum(DUR)
        fc.append(f"[8:a]atrim=0:{T},asetpts=PTS-STARTPTS,aresample=48000,"
                  f"afade=t=out:st={T - 0.4}:d=0.4,loudnorm=I=-14:TP=-1.5[a]")
    else:
        fc.append("".join(f"[{k}:a]atrim=0:{DUR[i]},asetpts=PTS-STARTPTS,aresample=48000,"
                          f"afade=t=in:st=0:d=0.08,afade=t=out:st={DUR[i] - 0.12}:d=0.12,dynaudnorm=f=150[a{i}];"
                          for i, k in enumerate((0, 1, 2))) + "[a0][a1][a2]concat=n=3:v=0:a=1,loudnorm=I=-14:TP=-1.5[a]")
    dest.parent.mkdir(parents=True, exist_ok=True)
    (tmp / "g.txt").write_text(";".join(fc), encoding="utf-8")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex_script", str(tmp / "g.txt"), "-map", "[v]",
                        "-map", "[a]", "-frames:v", str(tot), *G.NVENC, "-c:a", "aac", "-b:a", "192k", *G.CLEAN, str(dest)],
                       capture_output=True, text=True)
    shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode:
        raise RuntimeError(r.stderr[:1500])
    return dest.name


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--sounds", action="store_true", help="тест: один ролик под каждый звук s1–s4")
    a = ap.parse_args()
    global STUMBLE, AMONG                                   # юзер 16.11: no-copyright геймплей лучше трейлеров
    STUMBLE = motion_windows("nc_stumble_NY4gI6vO0Vw")
    AMONG = motion_windows("nc_amongus_If9Xq6w191s")
    print(f"отрезков геймплея: Stumble {len(STUMBLE)} ({sum(b - a for _, a, b in STUMBLE):.0f} с), "
          f"Among Us {len(AMONG)} ({sum(b - a for _, a, b in AMONG):.0f} с)", flush=True)
    rng = random.Random(21116)
    jobs = [job(rng, i + 1, "tt" if i % 2 == 0 else "yt") for i in range(5)]
    out = WORK / "test"
    if a.sounds:
        jobs = [dict(jobs[0], snd=f"s{k}", n=k) for k in range(1, 5)]
        out = WORK / "test_sounds"
    with ThreadPoolExecutor(5) as ex:
        print(list(ex.map(lambda j: build(j, out / (f"korean_onestate_2_sound{j['n']}_1.mp4" if j.get("snd")
                                                            else f"korean_onestate_2_{j['tag']}_{j['n']:03d}_1.mp4")), jobs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
