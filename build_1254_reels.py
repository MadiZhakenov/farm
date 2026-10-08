#!/usr/bin/env python3
"""
1254 — «мой парень всё успевает, секрет — Magic Sort» (реф: UNO-рилс): 5 вставок
подряд, 6 с: машина 1.1 → зал 0.9 → ноутбук 1.0 → руки с телефоном 1.5 →
экран крупно 1.5. Один длинный текст на весь ролик по центру (белый с тонкой
обводкой, как обычно); кегль подбирается, чтобы блок влез. Пустая строка в
тексте — отступ между абзацами, одиночный перенос — новая строка.

  python build_1254_reels.py --test --out output/1254_test          # по ролику на каждый текст
  python build_1254_reels.py -n 100 --out output/1254_100 --audio-dir downloads/music_1254 --suffix 1254

1256 — то же, но парень о своей девушке, игра Cozy Home; вставки — её глазами (руки на руле,
ноги на дорожке, руки на клавиатуре), кадр 4 — она играет (со спины):
  python build_1254_reels.py --project 1256 -n 200 --out output/1256_200 --audio-dir downloads/1254/music --suffix 1256
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402
from core import renderer as R  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
W, H, FPS = 1080, 1920, 30
B = ROOT / "downloads" / "1254"
SHOTS = [  # (папка, длительность)
    (B / "broll" / "car" / "clips_1.1s", 1.1),
    (B / "broll" / "gym_pov" / "clips_0.9s", 0.9),  # зал от первого лица, без чужих лиц
    (B / "broll" / "laptop" / "clips_1s", 1.0),
    (B / "phone" / "wide_1.5s", 1.5),     # кадр 4: парень виден целиком (сзади), не зум
    (B / "phone" / "screen_1.5s", 1.5),
]
TOTAL = sum(d for _p, d in SHOTS)
PHONE_GAP = 10       # руки и экран — из моментов игры минимум на 10 кусков (15 с) врозь
TEXT_MAX_W = 860     # ширина колонки текста
TEXT_CY, TEXT_MAX_H = 0.60, 0.56  # центр блока и макс. высота (доли кадра) — как в рефе 0.35–0.85
PX_MAX, PX_MIN = 46, 30
PARA_GAP = 0.6       # пустая строка = отступ в долях шага строки

TEXTS = [
    "my boyfriend works two jobs, runs a side business, hits the gym at 6am and somehow speaks four "
    "languages. so obviously i assumed he had some insane productivity system.\n\n"
    "i asked. his answer was embarrassingly simple.\n"
    "whenever his brain starts melting, he plays one quick round of Magic Sort. 2-3 minutes. then back to "
    "work. no 40-minute \"break\". no productivity app with 17 dashboards. just sort some colors and keep going.\n"
    "i tried it for a week and unfortunately it works, which means i can never make fun of him again 😭🧪",

    "my boyfriend is building a startup, sleeps five hours a night, and has never once complained to me. "
    "i've been quietly watching him for months like a nature documentary, waiting for the meltdown.\n"
    "nothing. calm. kind. making me tea.\n"
    "i finally broke and asked how. he shrugged and said \"i sort tubes.\"\n"
    "i said WHAT. he opened Magic Sort and played one level in front of me like it was nothing. 2 minutes. "
    "he looked like a different person after.\n"
    "i've been doing it every time i feel overwhelmed. i hate how much it helps. i also hate that he was "
    "right 🧪💛",

    "my boyfriend runs a startup, trains for a marathon, cooks every meal and somehow still answers texts "
    "in 2 minutes so obviously i assumed he had some secret system.\n"
    "i asked. his answer was honestly kind of insulting.\n"
    "every time his brain starts melting in the middle of the day he plays one quick Magic Sort level. "
    "2-3 minutes max. then back to it. no scrolling. no \"reset day\".\n"
    "no notion template with 12 tabs. just a dopamine snack and continue.\n"
    "i tried it for a week and it works. which means i can never roll my eyes at him again 🧪",
]


B_1256 = ROOT / "downloads" / "1256"
SHOTS_1256 = [
    (B_1256 / "broll" / "car" / "clips_1.1s", 1.1),
    (B_1256 / "broll" / "gym" / "clips_0.9s", 0.9),
    (B_1256 / "broll" / "laptop" / "clips_1s", 1.0),
    (B_1256 / "phone" / "wide_1.5s", 1.5),    # она играет, видна со спины
    (B_1256 / "phone" / "screen_1.5s", 1.5),
]
TEXTS_1256 = [
    "my girlfriend has two jobs, a side business, goes to the gym at 6am and somehow speaks four languages "
    "so obviously i assumed she had some insane productivity system.\n"
    "i asked. her answer was embarrassingly stupid.\n"
    "every time her brain starts melting between 30 tasks she decorates one tiny room in Cozy Home. "
    "literally 2-3 minutes. then back to work. no 40 minute \"break\".\n"
    "no productivity app with 17 dashboards. just rearrange a cozy corner and continue.\n"
    "i tried it for a week and unfortunately it works which means i can never make fun of her again 🧸",

    "my girlfriend runs a startup, trains for a marathon, cooks every meal and somehow still answers texts "
    "in 2 minutes so obviously i assumed she had some secret system.\n"
    "i asked. her answer was honestly kind of insulting.\n"
    "every time her brain starts melting in the middle of the day she plays one quick Cozy Home session. "
    "2-3 minutes max. then back to it. no scrolling. no \"reset day\".\n"
    "no notion template with 12 tabs. just a dopamine snack and continue.\n"
    "i tried it for a week and it works. which means i can never roll my eyes at her again 🍂",

    "my girlfriend works 12-hour days, still reads before bed and somehow never looks stressed so obviously "
    "i assumed she had some insane morning routine.\n"
    "i asked. her answer was embarrassingly simple.\n"
    "whenever her brain starts melting she decorates one little room in Cozy Home. literally 2-3 minutes. "
    "then right back to work. no 40 minute \"reset\".\n"
    "no app with 17 widgets. just place a few cute things and keep going.\n"
    "i tried it for a week and unfortunately it works which means i have no more jokes about her phone 🧸",
]
PROJECTS = {"1254": (B, SHOTS, TEXTS), "1256": (B_1256, SHOTS_1256, TEXTS_1256)}


def balanced_wrap(line: str, font, px: int, stroke: int) -> list[str]:
    """Перенос без «висящего» слова: столько же строк, что и жадный, но колонка максимально узкая."""
    best = A._wrap_mixed(line, font, px, TEXT_MAX_W, stroke)
    for w in range(TEXT_MAX_W - 10, int(TEXT_MAX_W * 0.55), -10):
        cand = A._wrap_mixed(line, font, px, w, stroke)
        if len(cand) > len(best):
            break
        best = cand
    return best


def text_block(text: str) -> Image.Image:
    """Белый текст с обводкой: перенос по ширине колонки, кегль — самый крупный, что влезает."""
    paras = [[A.sanitize_overlay_text(R._normalize_text(ln)) for ln in p.split("\n")] for p in text.split("\n\n")]
    for px in range(PX_MAX, PX_MIN - 1, -1):
        font, stroke, adv = R._load_font(px), R.stroke_width_for(px), R.line_advance_for(px)
        lines = [[w for ln in p for w in balanced_wrap(ln, font, px, stroke)] for p in paras]
        h = sum(len(p) for p in lines) * adv + int((len(lines) - 1) * adv * PARA_GAP)
        if h <= TEXT_MAX_H * H:
            break
    img = Image.new("RGBA", (W, h + 4 * stroke + adv), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 2 * stroke
    for k, p in enumerate(lines):
        for ln in p:
            lw = int(round(A._line_width_mixed(ln, font, px, stroke)))
            A._draw_line_mixed(img, d, (W - lw) // 2, y, ln, font, px, stroke)
            y += adv
        if k < len(lines) - 1:
            y += int(adv * PARA_GAP)
    return img.crop(img.getbbox())


def overlay(block: Image.Image, dest: Path) -> None:
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(block, ((W - block.width) // 2, int(TEXT_CY * H - block.height / 2)))
    canvas.save(dest)


def pick(rng: random.Random, pools: list[list[Path]]) -> list[Path]:
    clips = [rng.choice(p) for p in pools[:3]]
    hands = rng.choice(pools[3])
    far = [s for s in pools[4] if abs(int(s.name[:3]) - int(hands.name[:3])) >= PHONE_GAP]
    return clips + [hands, rng.choice(far or pools[4])]


def build(clips: list[Path], text_png: Path, audio: Path | None, audio_start: float, dest: Path) -> None:
    cmd = [FF, "-v", "error", "-y"]
    for c in clips:
        cmd += ["-i", str(c)]
    cmd += ["-i", str(text_png)]
    if audio:
        cmd += ["-ss", f"{audio_start:.3f}", "-i", str(audio)]
    n = len(clips)
    fc = "".join(f"[{i}:v]trim=0:{SHOTS[i][1]},setpts=PTS-STARTPTS,setsar=1,fps={FPS},format=yuv420p[v{i}];"
                 for i in range(n))
    fc += "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[cat];"
    fc += f"[cat][{n}:v]overlay=0:0,format=yuv420p,{SET_SDR}[v]"
    if audio:
        fc += (f";[{n + 1}:a]atrim=0:{TOTAL},asetpts=PTS-STARTPTS,apad=whole_dur={TOTAL},afade=t=in:d=0.05,"
               f"afade=t=out:st={TOTAL - 0.35:.2f}:d=0.35[a]")
    cmd += ["-filter_complex", fc, "-map", "[v]"]
    cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"] if audio else ["-an"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", *SDR_COLOR_ARGS,
            "-t", f"{TOTAL:.2f}", "-movflags", "+faststart", str(dest)]
    subprocess.run(cmd, stdin=subprocess.DEVNULL, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", choices=sorted(PROJECTS), default="1254")
    ap.add_argument("-n", type=int, default=3)
    ap.add_argument("--test", action="store_true", help="по одному ролику на каждый текст")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--audio-dir", type=Path)
    ap.add_argument("--starts", type=Path, help="json {имя_звука: старт, с}")
    ap.add_argument("--suffix", default="")
    ap.add_argument("--jobs", type=int, default=4, help="сколько роликов собирать параллельно")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    global B, SHOTS, TEXTS, TOTAL
    B, SHOTS, TEXTS = PROJECTS[args.project]
    TOTAL = sum(d for _p, d in SHOTS)
    pools = [sorted(p.glob("*.mp4")) for p, _d in SHOTS]
    print("кусков: " + " · ".join(f"{p.parent.name}/{p.name} {len(c)}" for (p, _d), c in zip(SHOTS, pools)),
          flush=True)
    rng = random.Random(args.seed)
    n = len(TEXTS) if args.test else args.n
    texts = list(range(len(TEXTS))) if args.test else [i % len(TEXTS) for i in range(n)]
    sounds = sorted(args.audio_dir.glob("*.*")) if args.audio_dir else []
    starts = json.loads(args.starts.read_text(encoding="utf-8")) if args.starts and args.starts.exists() else {}

    args.out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="r1254_"))
    manifest, used = [], set()
    try:
        pngs = []
        for i, t in enumerate(TEXTS):
            pngs.append(work / f"text_{i}.png")
            overlay(text_block(t), pngs[-1])
        jobs = []
        for k in range(n):
            for _ in range(200):  # без повторов набора кадров
                clips = pick(rng, pools)
                if tuple(clips) not in used:
                    break
            used.add(tuple(clips))
            snd = sounds[k % len(sounds)] if sounds else None
            st = float(starts.get(snd.stem, 0.0)) if snd else 0.0
            name = f"{k + 1:03d}_text{texts[k] + 1}{'_' + args.suffix if args.suffix else ''}.mp4"
            jobs.append((clips, pngs[texts[k]], snd, st, args.out / name))
            manifest.append({"file": name, "text": texts[k] + 1, "clips": [str(c.relative_to(B)) for c in clips],
                             "audio": snd.name if snd else None, "audio_start": st})
        done = 0
        with ThreadPoolExecutor(args.jobs) as ex:  # ffmpeg — отдельные процессы, параллелятся
            for _ in ex.map(lambda j: build(*j), jobs):
                done += 1
                if done % 10 == 0 or done == n:
                    print(f"[{done}/{n}]", flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"готово: {len(manifest)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
