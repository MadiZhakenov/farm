#!/usr/bin/env python3
"""
1303 — UNO! Mobile «играю с собакой»: 6 с = 3 кадра по 2 с, текст TikTok-шрифтом на весь ролик, музыка из ТЗ.
Исходники — Dropbox 1zn15wxbxl632nqvx6bep («Katherine - dog content», downloads/dropbox_1zn15wxb/src):

  лицо (сидит с собакой): IMG_5997, IMG_5995 — селфи с собакой крупно; IMG_5987 — тёмная комната, играет с собакой
                          на коленях (IMG_6001 не берём: внизу кадра голова собаки и телефон — текст бы их закрыл);
  игра: IMG_5992, IMG_5993 — телефон с UNO! Mobile из-за плеча, под ним голова собаки (меню/загрузка вырезаны).

  концепт 1: лицо → игра → лицо (первый кадр всегда лицо; в половине роликов — крупное селфи), 5 текстов;
  концепт 2: игра → лицо → игра, 2 текста.
  Папки по 500: YouTube и TikTok для каждого концепта (одинаковый формат, наборы кадров не пересекаются).

Текст — дословно из ТЗ, белый с обводкой (как 1254), «UNO! Mobile» не рвём; блок в нижней полосе y 960–1530 внутри
безопасной зоны 9:16: в кадрах игры телефон вверху, в селфи и тёмной комнате лица выше 950 px — ничего не закрываем.
Музыка — 4 трека ТЗ (YouTube Shorts; KIYtBFle42w в ТЗ дважды) поровну, с начала, 6 с, −14 LUFS; родной звук убран.
Уникальность: набор из 3 кусков (клип + время) не повторяется во всех 2000 роликах; два куска одного типа в ролике —
из разных клипов или минимум 20 с врозь.

  python build_1303_reels.py --test           # по 1 ролику на концепт/платформу → output/1303_test
  python build_1303_reels.py --jobs 6         # все 4 папки по 500
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402
from core import renderer as R  # noqa: E402
from core.safe_zones import check_overlay  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
W, H, FPS = 1080, 1920, 30
ID = "1303"
SRC = ROOT / "downloads" / "dropbox_1zn15wxb" / "src"
D = ROOT / "downloads" / "1303"
SHOT = 2.0
NBSP = "\u00a0"

# клип: (тип, рабочая часть, вырезать, шаг окон)
CLIPS = {
    "IMG_5997": ("selfie", (0.3, 9.3), [], 0.5),
    "IMG_5995": ("selfie", (0.2, 2.85), [], 0.5),
    "IMG_5987": ("face", (2.0, 302.0), [], 2.0),
    "IMG_5992": ("game", (2.0, 179.0), [(82.0, 112.0)], 2.0),     # 85–110 с — меню и загрузка, не игра
    "IMG_5993": ("game", (2.0, 149.0), [(82.0, 108.0)], 2.0),
}
# тексты ТЗ дословно; переносы — по смыслу (одна фраза — одна строка), «UNO! Mobile» не рвём
NL = chr(10)
TEXTS = {
    1: [
        NL.join([
            'POV: you start playing UNO! Mobile',
            'with your dog',
            'and she takes it WAY too seriously.',
            'she watches everything,',
            'she judges every move,',
            'and when i’m about to lose',
            'she looks at me like “are you serious?” 😭',
            'i have a coach now',
        ]),
        NL.join([
            'POV: your dog is your',
            'UNO! Mobile COACH now.',
            'she stares at the screen,',
            'tilts her head when you make a bad move,',
            'and somehow she knows which card to pick.',
            'guys, how long have we been',
            'missing out on this?',
        ]),
        NL.join([
            'POV: you try to play UNO! Mobile alone',
            'but your dog sits down next to you like',
            '“i’ll take it from here” 🐾',
            'she watches EVERYTHING',
            'and every time i listen to her, i win.',
            'i don’t ask questions',
        ]),
        NL.join([
            'POV: nobody told you',
            'the best UNO! Mobile partner EVER',
            'would be your dog.',
            'she doesn’t blink, doesn’t get distracted,',
            'and looks at the screen',
            'like she’s planning your next move 👀',
            'how long are we gonna stay QUIET about this?',
        ]),
        NL.join([
            'nobody told me the best partner EVER',
            'would be my dog.',
            'she doesn’t blink, doesn’t get distracted,',
            'and looks at my UNO! Mobile screen',
            'like she’s planning my next move 👀',
            'how long are we gonna stay QUIET about this?',
        ]),
    ],
    2: [
        NL.join([
            'POV: you play UNO! Mobile with your dog',
            'and it turns into',
            'the most wholesome game night 🥹',
            'she watches every card,',
            'gives you better advice than your friends,',
            'and never loses focus.',
            'tell me i’m not the only one',
            'who plays with my pet',
        ]),
        NL.join([
            'guys, i need to tell you something:',
            'i play with my dog',
            'and she takes it WAY too seriously 🐶',
            'she sits right next to me,',
            'watches every card on UNO! Mobile,',
            'and gives me hints on what to play.',
            'i’ve never won this much 😭',
        ]),
    ],
}
ORDER = {1: ["face", "game", "face"], 2: ["game", "face", "game"]}
MUSIC = ["gZIrKXCzue8", "bfoMNx0P0aE", "KIYtBFle42w", "RccecfkDWGM"]
FOLDERS = [(1, "YT"), (1, "TT"), (2, "YT"), (2, "TT")]
BAND = (960, 1530)                     # полоса текста по высоте
TEXT_MAX_W, PX_MAX, PX_MIN = 790, 46, 30          # 780 + обводка ≤ 800 (зона x 140–940)
MIN_APART = 20.0


# ---------------- текст ----------------
def wrap(words: list[str], font, px: int, stroke: int, max_w: int) -> list[str]:
    lines, cur = [], ""
    for w in words:
        cand = f"{cur} {w}" if cur else w
        if cur and A._line_width_mixed(cand, font, px, stroke) > max_w - 2 * stroke:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    return lines + [cur]


def balanced_wrap(line: str, font, px: int, stroke: int) -> list[str]:
    """Перенос без «висящего» слова (как 1254); «UNO! Mobile» — одно слово, не рвём."""
    words = []
    for w in line.split(" "):
        if w == "Mobile" and words and words[-1].endswith("UNO!"):
            words[-1] += " Mobile"
        elif w:
            words.append(w)
    best = wrap(words, font, px, stroke, TEXT_MAX_W)
    for mw in range(TEXT_MAX_W - 10, int(TEXT_MAX_W * 0.55), -10):
        cand = wrap(words, font, px, stroke, mw)
        if len(cand) > len(best):
            break
        best = cand
    return best


def text_png(text: str, dest: Path) -> int:
    """Белый TikTok-текст с обводкой в полосе BAND, кегль — самый крупный, что влезает; «UNO! Mobile» не рвётся."""
    raw = [A.sanitize_overlay_text(R._normalize_text(ln)) for ln in text.split(NL)]
    for px in range(PX_MAX, PX_MIN - 1, -1):
        font, stroke, adv = R._load_font(px), R.stroke_width_for(px), R.line_advance_for(px)
        # строки ТЗ по смыслу; переносим внутри строки, только если она шире колонки (тогда кегль меньше)
        if any(A._line_width_mixed(ln, font, px, stroke) > TEXT_MAX_W - 2 * stroke for ln in raw):
            continue
        lines = raw
        if len(lines) * adv + 4 * stroke <= BAND[1] - BAND[0]:
            break
    else:
        lines = [w for ln in raw for w in balanced_wrap(ln, font, px, stroke)]
    h = len(lines) * adv
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    y = (BAND[0] + BAND[1]) // 2 - h // 2
    for ln in lines:
        lw = int(round(A._line_width_mixed(ln, font, px, stroke)))
        A._draw_line_mixed(canvas, d, (W - lw) // 2, y, ln, font, px, stroke)
        y += adv
    bad = check_overlay(canvas)
    if bad:
        raise SystemExit(f"текст вне безопасной зоны: {bad}")
    canvas.save(dest)
    return px


# ---------------- музыка ----------------
def music_wav(track: str) -> Path:
    out = D / "music" / f"{track}_6s_-14lufs.wav"
    if out.exists():
        return out
    src = D / "music" / f"{track}.m4a"
    total = 3 * SHOT
    base = f"atrim=duration={total},asetpts=PTS-STARTPTS,afade=t=out:st={total - 0.3}:d=0.3"
    loud = "loudnorm=I=-14:TP=-1.5:LRA=11"
    log = subprocess.run([FF, "-hide_banner", "-i", str(src), "-af", f"{base},{loud}:print_format=json", "-f", "null",
                          "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log).group(0))
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-af",
                    f"{base},{loud}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
                    f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample=48000",
                    "-c:a", "pcm_s16le", str(out)], check=True)
    return out


# ---------------- план ----------------
def windows() -> dict[str, list[tuple[str, float]]]:
    """Куски по типам: (клип, начало)."""
    out: dict[str, list[tuple[str, float]]] = {"selfie": [], "face": [], "game": []}
    for clip, (kind, (a, b), cut, step) in CLIPS.items():
        t = a
        while t + SHOT <= b + 1e-6:
            if not any(t < ce and t + SHOT > cs for cs, ce in cut):
                out[kind].append((clip, round(t, 2)))
            t += step
    return out


def apart(x: tuple[str, float], y: tuple[str, float]) -> bool:
    return x[0] != y[0] or abs(x[1] - y[1]) >= MIN_APART


def plan(count: int) -> list[dict]:
    rng = random.Random(1303)
    win = windows()
    faces = win["selfie"] + win["face"]
    use: dict[tuple[str, float], int] = {}
    seen: set = set()

    def pick(pool: list, avoid: list) -> tuple[str, float]:
        cand = [w for w in pool if all(apart(w, a) for a in avoid)]
        rng.shuffle(cand)
        cand.sort(key=lambda w: use.get(w, 0))             # реже использованные — первыми
        return cand[0] if cand else rng.choice(pool)

    jobs = []
    for concept, plat in FOLDERS:
        texts = TEXTS[concept]
        for n in range(count):
            for _try in range(200):
                shots: list[tuple[str, float]] = []
                for k, kind in enumerate(ORDER[concept]):
                    if kind == "game":
                        pool = win["game"]
                    elif concept == 1 and k == 0:
                        pool = win["selfie"] if n % 2 == 0 else win["face"]   # первый кадр: половина — селфи
                    else:
                        pool = faces
                    shots.append(pick(pool, [s for s in shots if s[0] in {w[0] for w in pool}]))
                key = tuple(shots)
                if key not in seen:
                    break
            else:
                raise SystemExit("не хватает уникальных наборов")
            seen.add(key)
            for s in shots:
                use[s] = use.get(s, 0) + 1
            jobs.append({"concept": concept, "plat": plat, "n": n + 1, "shots": [list(s) for s in shots],
                         "text": n % len(texts), "music": MUSIC[n % len(MUSIC)]})
    return jobs


# ---------------- рендер ----------------
def folder(concept: int, plat: str, count: int) -> Path:
    return ROOT / "output" / f"{ID}_C{concept}_{plat}_{count}"


def build(job: dict) -> str:
    out = Path(job["out"])
    dest = out / f"c{job['concept']}_{job['plat'].lower()}_{job['n']:03d}_{ID}.mp4"
    png = D / "_png" / f"c{job['concept']}_t{job['text'] + 1}.png"
    inputs, parts = [], []
    for k, (clip, t0) in enumerate(job["shots"]):
        inputs += ["-ss", f"{t0:.3f}", "-t", f"{SHOT + 0.2:.3f}", "-i", str(SRC / f"{clip}.MOV")]
        parts.append(f"[{k}:v]scale={W}:{H}:flags=lanczos,fps={FPS},trim=duration={SHOT},setpts=PTS-STARTPTS,setsar=1[v{k}]")
    fc = ";".join(parts) + ";[v0][v1][v2]concat=n=3:v=1:a=0[c];[c][3:v]overlay=0:0,format=yuv420p," + SET_SDR + "[v]"
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-i", str(png), "-i", str(music_wav(job["music"])),
                    "-filter_complex", fc, "-map", "[v]", "-map", "4:a", "-t", f"{3 * SHOT:.3f}",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19", *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(dest)], check=True)
    return dest.name


def done(p: Path) -> bool:
    return p.exists() and subprocess.run([FF.replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error", "-show_entries",
                                          "format=duration", "-of", "csv=p=0", str(p)],
                                         capture_output=True, text=True).stdout.strip() != ""


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=500)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--test", action="store_true", help="по 1 ролику на папку → output/1303_test")
    args = ap.parse_args()
    (D / "_png").mkdir(parents=True, exist_ok=True)
    for c, texts in TEXTS.items():
        for i, t in enumerate(texts, 1):
            print(f"концепт {c}, текст {i}: {text_png(t, D / '_png' / f'c{c}_t{i}.png')}px", flush=True)
    for m in MUSIC:
        music_wav(m)
    win = windows()
    print("кусков:", {k: len(v) for k, v in win.items()}, flush=True)
    jobs = plan(args.count)
    if args.test:
        jobs = [j for j in jobs if j["n"] in (1, 2)]
    for j in jobs:
        out = ROOT / "output" / f"{ID}_test" if args.test else folder(j["concept"], j["plat"], args.count)
        out.mkdir(parents=True, exist_ok=True)
        j["out"] = str(out)
    if not args.test:
        for c, p in FOLDERS:
            part = [j for j in jobs if j["concept"] == c and j["plat"] == p]
            (folder(c, p, args.count) / "manifest.json").write_text(json.dumps(part, indent=1), encoding="utf-8")
    todo = [j for j in jobs if not done(Path(j["out"]) / f"c{j['concept']}_{j['plat'].lower()}_{j['n']:03d}_{ID}.mp4")]
    print(f"собрать {len(todo)} из {len(jobs)}", flush=True)
    with ProcessPoolExecutor(args.jobs) as ex:
        for k, name in enumerate(ex.map(build, todo), 1):
            print(f"[{k}/{len(todo)}] {name}", flush=True)
    print("готово")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
