#!/usr/bin/env python3
"""
Рилсы «5 signs …» (формат «5 habits that separate pro drivers…»): 3 с девушка →
2 с геймплей. Заголовок — белый с чёрной обводкой сверху, весь ролик; у 1252
ещё подпись снизу с 3 с. Больше текста нет (всё — в описании поста).

  1252 — Magic Sort, «5 signs someone actually likes you.» + «most people miss #3»
  1253 — Cozy Home, «5 signs you were forced to grow up too early»

Шрифт: tiktok (TikTok Sans, белый с обводкой, как во всех рилсах), ig (Insta-стиль:
чёрный текст на белой плашке, Figtree Bold — свободный
аналог Instagram Sans, сам он закрытый) или both → <out>/tiktok и <out>/insta
с одинаковыми роликами.

  python build_signs_reels.py --project 1253 -n 5 --font both --out output/1253_test
  python build_signs_reels.py --project 1252 -n 100 --out output/1252_100 --audio-dir downloads/music_signs --suffix 1252
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR, vf_scale_crop_fps_sdr  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
W, H, FPS = 1080, 1920, 30
FACE_DUR, PLAY_DUR = 3.0, 2.0
TOTAL = FACE_DUR + PLAY_DUR
# Figtree Bold (OFL) — ближайший свободный аналог Instagram Sans
IG_FONT = ROOT / "fonts" / "ig_lookalike" / "Figtree.ttf"
TEXT_FONT: Path | None = None  # None = TikTok Sans (R._load_font)

CLIPS = ROOT / "output"
# title_cy / caption_cy — центр блока в долях высоты; заголовок не закрывает лицо
PROJECTS = {
    # 1252 v2 (2026-10-08): только IMG_9758 — 3 с игры + 2 с игры из далёкого момента (склейка),
    # min_gap — мин. зазор в исходнике между кусками, с
    "1252": {
        "face": CLIPS / "clips_1252" / "IMG_9758_play_3s",
        "play": CLIPS / "clips_1252" / "IMG_9758_play_2s",
        "min_gap": 6.0,
        "title": ["5 signs someone", "actually likes you."], "title_px": 56, "title_cy": 0.14,
        "caption": "most people miss #3", "caption_px": 52, "caption_cy": 0.50,  # середина экрана (обе версии)
    },
    # первая версия 1252: девушка 3 с + игра 2 с (уже собрано 100 шт. TT)
    "1252_girl": {
        "face": CLIPS / "clips_proj5" / "MyResultVideo_face_3s",
        "play": CLIPS / "clips_proj5" / "IMG_9758_play_2s",
        "title": ["5 signs someone", "actually likes you."], "title_px": 56, "title_cy": 0.14,  # вариант C
        "caption": "most people miss #3", "caption_px": 52, "caption_cy": 0.86,  # ниже планшета
        "caption_cy_ig": 0.50,
    },
    "1253": {
        "face": CLIPS / "clips_1253" / "IMG_9761_face_3s",
        "play": CLIPS / "clips_1253" / "IMG_9753_play_2s",
        "title": ["5 signs you were forced", "to grow up too early"], "title_px": 58, "title_cy": 0.095,  # вариант B
        "caption": None,
    },
}


def plate_ig(lines: list[str], px: int) -> Image.Image:
    """Instagram-стиль: чёрный жирный текст на белой плашке. У каждой строки своя плашка по
    ширине, плашки сливаются в одну фигуру: внешние углы скруглены, внутренние стыки — плавные."""
    import cv2
    import numpy as np

    ss = 3  # суперсэмплинг для гладких краёв
    font = ImageFont.truetype(str(IG_FONT), px * ss)
    font.set_variation_by_name("Bold")
    # шаг строк поплотнее (фидбек: «строчки далеко друг от друга»), плашки строк всё ещё сливаются
    line_h, pad_x, r = int(1.12 * px * ss), int(0.30 * px * ss), int(0.20 * px * ss)
    widths = [font.getlength(t) for t in lines]
    cw = int(max(widths) + 2 * pad_x + 4 * r)
    ch = line_h * len(lines) + 4 * r
    mask = np.zeros((ch, cw), np.uint8)
    for k, w in enumerate(widths):
        x0 = int((cw - w) / 2 - pad_x)
        mask[2 * r + k * line_h:2 * r + (k + 1) * line_h, x0:x0 + int(w + 2 * pad_x)] = 255
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kern)  # плавные внутренние стыки строк
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kern)   # скруглённые внешние углы
    img = Image.new("RGBA", (cw, ch), (255, 255, 255, 0))
    img.putalpha(Image.fromarray(mask))
    d = ImageDraw.Draw(img)
    for k, t in enumerate(lines):
        d.text((cw / 2, 2 * r + (k + 0.5) * line_h), t, font=font, fill=(0, 0, 0, 255), anchor="mm")
    img = img.resize((cw // ss, ch // ss), Image.Resampling.LANCZOS)
    return img.crop(img.getbbox())


def plate(lines: list[str], px: int) -> Image.Image:
    """Наш обычный стиль: белый текст с чёрной обводкой (как во всех рилсах).
    Для Insta-версии (TEXT_FONT = IG_FONT) — чёрный текст на белой плашке, см. plate_ig."""
    import assemble_ugc_reels as A
    from core import renderer as R

    if TEXT_FONT == IG_FONT:
        return plate_ig(lines, px)
    if TEXT_FONT:
        font = ImageFont.truetype(str(TEXT_FONT), px)
        try:
            font.set_variation_by_name("Bold")
        except Exception:
            pass
    else:
        font = R._load_font(px)
    stroke = R.stroke_width_for(px)
    adv = R.line_advance_for(px)
    widths = [A._line_width_mixed(t, font, px, stroke) for t in lines]
    img = Image.new("RGBA", (W, adv * len(lines) + 4 * stroke), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 2 * stroke
    for t, w in zip(lines, widths):
        A._draw_line_mixed(img, d, int((W - w) // 2), y, t, font, px, stroke)
        y += adv
    return img.crop(img.getbbox())


def overlay_png(block: Image.Image, cy: float, dest: Path) -> None:
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(block, ((W - block.width) // 2, int(cy * H - block.height / 2)))
    canvas.save(dest)


def clip_start(p: Path) -> float:
    m = re.search(r"_([\d.]+)s\.mp4$", p.name)
    return float(m.group(1)) if m else 0.0


def plan(n: int, faces: list[Path], plays: list[Path], rng: random.Random,
         min_gap: float | None = None) -> list[tuple[Path, Path]]:
    """Уникальные пары, клипы расходуются поровну. min_gap — оба куска из одного исходника:
    между ними в исходнике не меньше min_gap с (не соседи); при равенстве берём пару подальше."""
    pairs = list(itertools.product(range(len(faces)), range(len(plays))))
    gap = {}
    if min_gap is not None:
        for f, q in pairs:
            a, b = clip_start(faces[f]), clip_start(plays[q])
            gap[(f, q)] = b - (a + FACE_DUR) if b > a else a - (b + PLAY_DUR)
        pairs = [pq for pq in pairs if gap[pq] >= min_gap]
    if n > len(pairs):
        raise SystemExit(f"нужно {n}, а уникальных пар только {len(pairs)}")
    rng.shuffle(pairs)
    use_f, use_p, out = Counter(), Counter(), []
    for _ in range(n):
        best = min(pairs, key=lambda p: (use_f[p[0]] + use_p[p[1]], -gap.get(p, 0), use_f[p[0]], use_p[p[1]]))
        pairs.remove(best)
        use_f[best[0]] += 1
        use_p[best[1]] += 1
        out.append((faces[best[0]], plays[best[1]]))
    return out


def build(face: Path, play: Path, title_png: Path, cap_png: Path | None, audio: Path | None,
          audio_start: float, dest: Path, work: Path) -> None:
    lst = work / "concat.txt"
    lst.write_text(f"file '{face.resolve().as_posix()}'\nfile '{play.resolve().as_posix()}'\n", encoding="utf-8")
    cmd = [FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(title_png)]
    if cap_png:
        cmd += ["-i", str(cap_png)]
    a_idx = 3 if cap_png else 2
    if audio:
        cmd += ["-ss", f"{audio_start:.3f}", "-i", str(audio)]
    fc = f"[0:v]{vf_scale_crop_fps_sdr(W, H, FPS)}[b];[b][1:v]overlay=0:0"
    if cap_png:
        fc += f"[t];[t][2:v]overlay=0:0:enable='gte(t,{FACE_DUR})'"
    fc += f",format=yuv420p,{SET_SDR}[v]"
    if audio:
        fc += (f";[{a_idx}:a]atrim=0:{TOTAL},asetpts=PTS-STARTPTS,afade=t=in:d=0.08,"
               f"afade=t=out:st={TOTAL - 0.35:.2f}:d=0.35[a]")
    cmd += ["-filter_complex", fc, "-map", "[v]"]
    cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"] if audio else ["-an"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", *SDR_COLOR_ARGS,
            "-t", f"{TOTAL:.2f}", "-movflags", "+faststart", str(dest)]
    subprocess.run(cmd, stdin=subprocess.DEVNULL, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", choices=sorted(PROJECTS), required=True)
    ap.add_argument("-n", type=int, default=5)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--audio-dir", type=Path, help="папка звуков — поровну по роликам")
    ap.add_argument("--starts", type=Path, help="json {имя_файла_без_расширения: старт, с}")
    ap.add_argument("--suffix", default="", help="в конец имени файла, напр. 1260")
    ap.add_argument("--font", choices=["tiktok", "ig", "both"], default="tiktok")
    args = ap.parse_args()
    global TEXT_FONT
    pj = PROJECTS[args.project]
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    faces = sorted(pj["face"].glob("*.mp4"))
    plays = sorted(pj["play"].glob("*.mp4"))
    rng = random.Random(args.seed)
    pairs = plan(args.n, faces, plays, rng, pj.get("min_gap"))
    sounds = sorted(args.audio_dir.glob("*.*")) if args.audio_dir else []
    starts = json.loads(args.starts.read_text(encoding="utf-8")) if args.starts and args.starts.exists() else {}
    order = [i % len(sounds) for i in range(args.n)] if sounds else []
    rng.shuffle(order)
    print(f"девушка {len(faces)} · игра {len(plays)} → {len(faces) * len(plays)} пар · звуков {len(sounds)}", flush=True)

    fonts = {"tiktok": [("tiktok", None)], "ig": [("insta", IG_FONT)],
             "both": [("tiktok", None), ("insta", IG_FONT)]}[args.font]
    for sub, font in fonts:
        TEXT_FONT = font
        out = args.out / sub if args.font == "both" else args.out
        out.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="signs_"))
        manifest = []
        try:
            title_png, cap_png = work / "title.png", None
            overlay_png(plate(pj["title"], pj["title_px"]), pj["title_cy"], title_png)
            if pj["caption"]:
                cap_png = work / "cap.png"
                cy = pj.get("caption_cy_ig", pj["caption_cy"]) if font == IG_FONT else pj["caption_cy"]
                overlay_png(plate([pj["caption"]], pj["caption_px"]), cy, cap_png)
            for i, (face, play) in enumerate(pairs, 1):
                snd = sounds[order[i - 1]] if sounds else None
                st = float(starts.get(snd.stem, 0.0)) if snd else 0.0
                name = f"{i:03d}{'_' + args.suffix if args.suffix else ''}.mp4"
                build(face, play, title_png, cap_png, snd, st, out / name, work)
                manifest.append({"file": name, "clips": [face.name, play.name],
                                 "audio": snd.name if snd else None, "audio_start": st})
                if i % 10 == 0 or i == args.n:
                    print(f"[{sub} {i}/{args.n}]", flush=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"готово: {len(manifest)} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
