#!/usr/bin/env python3
"""
1304 — Global Work, тест 100 роликов по 6 с без музыки: «текст пластом» шрифтом TikTok поверх видео (2 текста ТЗ,
дословно). Фон — дубли креатора из Drive 1wtPGaK242oIartvFaytBbHh5kPqzH0SP (= downloads/gw_wall2/srcB, IMG_8101…8108:
серьёзное лицо в камеру, 10–17 с, iPhone HLG 4K).

  — ролик = ОДИН клип: из его рабочей части (без включения/выключения камеры) режем куски по 3 с и склеиваем два
    разных куска в любом порядке (джамп-кат внутри одного дубля — одежда и фон не скачут);
  — текст про «this face», поэтому лицо не закрываем: блок — под подбородком (самый низкий подбородок обоих кусков,
    MediaPipe 10 к/с) до низа безопасной зоны 9:16 (y 1540), кегль — самый крупный 42→30, что влезает;
    белый TikTok-шрифт с чёрной обводкой (как gw_wall), по центру; кадр не сдвигаем;
  — звук — родной фон дубля (голоса и музыки нет), без нормализации, короткий фейд на склейке; iPhone HDR → SDR.

  python build_1304_reels.py --count 100 [--jobs 3]
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_wall_reels as WL  # noqa: E402  (wall_lines / wall_height / render_wall — шрифт TikTok с обводкой)
from core.safe_zones import text_rect  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = WL.FF
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
SRC = ROOT / "downloads" / "gw_wall2" / "srcB"
CACHE = ROOT / "downloads" / "1304" / "clips.json"
ID = "1304"
W, H = 1080, 1920
X0, Y0, X1, Y1 = text_rect(W, H)
PIECE, GAP = 3.0, 30                     # длина куска, отступ текста от подбородка, px
PX_MAX, PX_MIN = 48, 40
STEP = 1.5                               # шаг начала кусков (куски одного ролика не перекрываются)
EXCLUDE: set[str] = set()
NL = chr(10)
TEXTS = [                                # дословно из ТЗ; строки — короткие фразы по смыслу, кегль крупный
    NL.join([
        'you see this face?',
        'it’s the face of a woman',
        'who fed her whole family',
        'for 2 years with no job.',
        'everyone told me “just wait,”',
        '“be patient,” “isn’t that his job.”',
        'i didn’t say a word,',
        'i just opened globalwork.ai,',
        'which matches jobs to my experience',
        'and tailors my resume for each role',
        '(i approve every application,',
        'obviously).',
        'and now?',
        'looks like tomorrow i go to work.',
        'still the same face tho 😭',
        'who is supposed to provide',
        'in a family?? 👇',
    ]),
    NL.join([
        'this is the face i make',
        'when someone says',
        '“that’s the husband’s job.”',
        'i provide for my family.',
        'i lost my job this year.',
        'and i did NOT stop.',
        'i found globalwork.ai',
        '(it matches roles to your background',
        'and tailors your resume,',
        'and you approve every application),',
        'and honestly it made me feel',
        'like i was in control again.',
        'so, yeah, looks like',
        'tomorrow is my first day.',
        'still not smiling,',
        'i’m just built like this.',
        'who’s supposed to provide',
        'in a family?? 👇',
    ]),
]


def usable(path: Path) -> tuple[float, float]:
    """Рабочая часть дубля: после того как камеру поставили, до того как к ней тянутся (как в gw_wall)."""
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-vf", "scale=90:160,fps=10", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, 160, 90).astype(np.int16)
    d = np.abs(np.diff(v, axis=0)).mean((1, 2))
    calm = float(np.median(d[len(d) // 4: 3 * len(d) // 4]))
    th = max(1.2, 2.5 * calm)
    start = max(next((i for i in range(len(d) - 5) if (d[i:i + 5] < th).all()), 0), 3)
    hits = np.where(d[-30:] > th)[0]
    end = len(d) - 30 + int(hits[0]) - 1 if len(hits) else len(d) - 3
    return start / 10, end / 10


def chins(path: Path) -> list[float | None]:
    """Низ лица (подбородок) по кадрам 10 к/с, px из 1920."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    w, h = 540, 960
    fl = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "face_landmarker.task")),
        running_mode=vision.RunningMode.VIDEO, num_faces=1))
    p = subprocess.Popen([FF, "-v", "quiet", "-i", str(path), "-vf",
                          WL.TM.replace("w=1080:h=1920", f"w={w}:h={h}").replace("fps=30", "fps=10"),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    out, k = [], 0
    while True:
        buf = p.stdout.read(w * h * 3)
        if len(buf) < w * h * 3:
            break
        r = fl.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                                         data=np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()), k * 100)
        out.append(max(q.y for q in r.face_landmarks[0]) * H if r.face_landmarks else None)
        k += 1
    fl.close()
    return out


def clip_info() -> dict:
    info = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    for path in sorted(p for p in SRC.glob("IMG_*.MOV") if p.stem not in EXCLUDE):
        if path.stem in info:
            continue
        a, b = usable(path)
        ch = chins(path)
        wins = []
        t = a
        while t + PIECE <= b + 1e-6:
            seg = [c for c in ch[int(t * 10):int((t + PIECE) * 10)] if c is not None]
            if len(seg) >= 0.9 * PIECE * 10:                # лицо в кадре почти всё время
                wins.append({"start": round(t, 2), "chin": int(max(seg))})
            t += STEP
        info[path.stem] = {"usable": [a, b], "windows": wins}
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(info, indent=1))
        print(path.stem, info[path.stem], flush=True)
    return info


def layout(text: str, chin: int) -> tuple[int, int]:
    """Кегль и верх блока: самый крупный, при котором ни одна строка не переносится и блок влезает в зону;
    блок по центру безопасной зоны (лицо можно закрывать — пользователь: мелкий шрифт хуже)."""
    def fits(p: int) -> bool:
        font, st = WL.R._load_font(p), WL.R.stroke_width_for(p)
        return (all(WL.A._line_width_mixed(ln, font, p, st) <= (X1 - X0) - 2 * st for ln in text.split(NL))
                and WL.wall_height(text, p) <= (Y1 - 6) - (Y0 + 10))
    px = next((p for p in range(PX_MAX, PX_MIN - 1, -1) if fits(p)), PX_MIN)
    h = WL.wall_height(text, px)
    return px, int((Y0 + Y1) / 2 - h / 2)


def plan(count: int, info: dict) -> list[dict]:
    """Пары кусков из одного клипа (оба порядка, сначала не подряд идущие), клипы и тексты — поровну."""
    rng = random.Random(1304)
    per_clip = {}
    for clip, d in info.items():
        st = [w["start"] for w in d["windows"]]
        cont = lambda p: abs(st[p[1]] - st[p[0]] - PIECE) < 0.01   # noqa: E731  «как снято»: второй сразу за первым
        pairs = [p for p in itertools.permutations(range(len(st)), 2) if abs(st[p[0]] - st[p[1]]) >= PIECE - 0.01]
        rng.shuffle(pairs)
        pairs.sort(key=cont)                                 # «как снято» — в конец
        per_clip[clip] = [(p, t) for p in pairs for t in range(len(TEXTS))]
        rng.shuffle(per_clip[clip])
        per_clip[clip].sort(key=lambda x: cont(x[0]))
    cap = sum(len(v) for v in per_clip.values())
    if count > cap:
        raise SystemExit(f"уникальных комбинаций только {cap}")
    jobs, k = [], 0
    clips = sorted(per_clip)
    while len(jobs) < count:
        clip = clips[k % len(clips)]
        k += 1
        if not per_clip[clip]:
            continue
        (i, j), t = per_clip[clip].pop(0)
        wins = info[clip]["windows"]
        chin = max(wins[i]["chin"], wins[j]["chin"])
        px, top = layout(TEXTS[t], chin)
        jobs.append({"clip": clip, "pieces": [wins[i]["start"], wins[j]["start"]], "text": t, "px": px, "top": top,
                     "chin": chin})
    jobs.sort(key=lambda j: (j["text"], j["clip"]))
    rng.shuffle(jobs)
    for n, j in enumerate(jobs, 1):
        j["n"] = n
    return jobs


def build(job: dict) -> str:
    work = Path(tempfile.mkdtemp(prefix="r1304_"))
    png = work / "text.png"
    WL.render_wall(TEXTS[job["text"]], job["px"], job["top"], png)
    a, b = job["pieces"]
    fc = (f"[0:v]{WL.TM},split=2[x0][x1];"
          f"[x0]trim=start={a:.3f}:duration={PIECE},setpts=PTS-STARTPTS,setsar=1[v0];"
          f"[x1]trim=start={b:.3f}:duration={PIECE},setpts=PTS-STARTPTS,setsar=1[v1];"
          f"[0:a:0]asplit=2[y0][y1];"
          f"[y0]atrim=start={a:.3f}:duration={PIECE},asetpts=PTS-STARTPTS,afade=t=out:st={PIECE - 0.03}:d=0.03[a0];"
          f"[y1]atrim=start={b:.3f}:duration={PIECE},asetpts=PTS-STARTPTS,afade=t=in:d=0.03[a1];"
          f"[v0][a0][v1][a1]concat=n=2:v=1:a=1[cv][ca];[cv][1:v]overlay=0:0,format=yuv420p,{SET_SDR}[v]")
    out = ROOT / "output" / job["out"]
    dest = out / f"{job['n']:03d}_{ID}.mp4"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(SRC / f"{job['clip']}.MOV"), "-i", str(png),
                    "-filter_complex", fc, "-map", "[v]", "-map", "[ca]", "-t", f"{2 * PIECE:.3f}",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18", *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(dest)], check=True)
    return f"{dest.name}: {job['clip']} куски {a}/{b}, текст {job['text'] + 1}, {job['px']}px с y={job['top']}"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    info = clip_info()
    print("кусков по клипам:", {c: len(d["windows"]) for c, d in info.items()}, flush=True)
    out = args.out or f"{ID}_{args.count}"
    jobs = plan(args.count, info)
    for j in jobs:
        j["out"] = out
    (ROOT / "output" / out).mkdir(parents=True, exist_ok=True)
    (ROOT / "output" / out / "manifest.json").write_text(json.dumps(jobs, indent=1, ensure_ascii=False), encoding="utf-8")
    def done(j: dict) -> bool:                              # готовый целый файл (moov есть) — не пересобираем
        f = ROOT / "output" / out / f"{j['n']:03d}_{ID}.mp4"
        return f.exists() and subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                              str(f)], capture_output=True, text=True).stdout.strip() != ""
    todo = [j for j in jobs if not done(j)]
    print(f"собрать {len(todo)} из {len(jobs)}", flush=True)
    with ProcessPoolExecutor(args.jobs) as ex:
        for k, msg in enumerate(ex.map(build, todo), 1):
            print(f"[{k}/{len(todo)}] {msg}", flush=True)
    print("готово →", ROOT / "output" / out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
