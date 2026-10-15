#!/usr/bin/env python3
"""
Global Work, «bad / good / amazing» по категориям (реф Instagram reel DcsrWNeuiYo), айди пока нет.
Креатор говорит «bad, good, amazing» 5 раз и показывает пальцем вверх; как в рефе, сверху — название
категории моноширинным шрифтом, под ним на каждое слово всплывает логотип сервиса с подписью.
2 ролика: в машине (дубли IMG_2917 ×3 + IMG_2918 ×2) и в комнате (IMG_2924 ×5).
Моменты появления — по словам (Whisper, downloads/gw_tiers/src/words.json) с уточнением по огибающей звука.
Всё в безопасной зоне 9:16. Звук — голос креатора, −14 LUFS. iPhone HDR → SDR (libplacebo).

  python build_gw_tiers_reels.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import check_box, text_rect  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
D = ROOT / "downloads" / "gw_tiers"
SRC, LOGOS, PLOGOS = D / "src", D / "logos", ROOT / "downloads" / "gw_pyramid" / "logos"
OUT = ROOT / "output" / "gw_tiers"
ID = "noid"
W, H, FPS = 1080, 1920, 30
TM = ("libplacebo=w=1080:h=1920:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:"
      "tonemapping=auto:format=yuv420p,fps=30")
MONO = ROOT / "fonts" / "jetbrains" / "JetBrainsMono[wght].ttf"

# табличка из ТЗ: категория → (BAD, GOOD, AMAZING)
ROWS = [
    ("Tracking job applications", ("Google Sheets", "Notion", "Teal")),
    ("Writing cover letters", ("Google Docs", "ChatGPT", "Kickresume")),
    ("Autofilling job applications", ("Chrome Autofill", "Teal", "Simplify")),
    ("Automating job applications", ("LinkedIn", "LoopCV", "Global Work")),
    ("All-in-one AI job search", ("Indeed", "Teal", "Global Work")),
]
ICON = {"Google Sheets": "gsheets", "Notion": "notion", "Teal": "teal", "Google Docs": "gdocs", "ChatGPT": "chatgpt",
        "Kickresume": "kickresume", "Chrome Autofill": "chrome", "Simplify": "simplify", "LinkedIn": "linkedin",
        "LoopCV": "loopcv", "Global Work": "globalwork", "Indeed": "indeed"}
# ролик → список (клип, номер тройки «bad good amazing» в клипе)
VIDEOS = {
    "car": [("IMG_2917", 0), ("IMG_2917", 1), ("IMG_2917", 2), ("IMG_2918", 0), ("IMG_2918", 1)],
    "room": [("IMG_2924", 0), ("IMG_2924", 1), ("IMG_2924", 2), ("IMG_2924", 3), ("IMG_2924", 4)],
}
# раскладка (замер рефа: заголовок ≈ 64 px моно, иконки ≈ 166 px, центры 230/540/830)
TITLE_PX, TITLE_TOP, ICON_SIDE, LABEL_PX = 62, 230, 170, 26
COLS = (270, 540, 810)
POP = 0.18          # длительность «всплытия» логотипа, с
PRE, POST = 0.35, 1.0


# ---------------- тайминги ----------------
def envelope(clip: Path) -> np.ndarray:
    a = np.frombuffer(subprocess.run([FF, "-v", "error", "-i", str(clip), "-map", "0:a:0", "-ac", "1", "-ar", "16000",
                                      "-f", "f32le", "-"], capture_output=True).stdout, np.float32)
    hop = 160
    return np.array([np.sqrt(np.mean(a[i:i + hop] ** 2)) for i in range(0, len(a) - hop, hop)])


def bursts(env: np.ndarray) -> list[tuple[float, float]]:
    """Отрезки речи по огибающей (гистерезис, слияние пауз < 0.12 с). Whisper на этих клипах смещает слова
    на 0.5–0.8 с, а отрезки речи совпадают со словами один в один."""
    sm = np.convolve(env, np.ones(5) / 5, mode="same")
    floor = float(np.percentile(sm, 20))
    hi, lo = floor + 0.12 * (sm.max() - floor), floor + 0.06 * (sm.max() - floor)
    out, on, st = [], False, 0
    for i, v in enumerate(sm):
        if not on and v > hi:
            on, st = True, i
        elif on and v < lo:
            on = False
            if i - st >= 8:
                out.append((st / 100, i / 100))
    if on:
        out.append((st / 100, len(sm) / 100))
    merged: list[tuple[float, float]] = []
    for b in out:
        if merged and b[0] - merged[-1][1] < 0.12:
            merged[-1] = (merged[-1][0], b[1])
        else:
            merged.append(b)
    return merged


def triplets(clip: str) -> list[list[float]]:
    """Моменты слов bad/good/amazing тройками. Каждое слово = отрезок речи по порядку; если перед словом
    сказано «this is» (одним отрезком), слово — во второй половине отрезка."""
    words = json.loads((SRC / "words.json").read_text())[clip]
    seq, prefixed = [], []
    for k, (w, _t, _e) in enumerate(words):
        if w in ("bad", "good", "amazing"):
            seq.append(w)
            prefixed.append(k >= 2 and words[k - 2][0] == "this" and words[k - 1][0] == "is")
    bs = bursts(envelope(SRC / f"{clip}.MOV"))
    if len(bs) != len(seq):
        raise SystemExit(f"{clip}: отрезков речи {len(bs)}, слов {len(seq)} — проверь вручную")
    times = [a + 0.55 * (b - a) if pre else a for (a, b), pre in zip(bs, prefixed)]
    return [times[i:i + 3] for i in range(0, len(times) - 2, 3) if seq[i:i + 3] == ["bad", "good", "amazing"]]


def duration(p: Path) -> float:
    return float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)


# ---------------- графика ----------------
def mono(px: int, weight: str = "ExtraBold") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(MONO), px)
    f.set_variation_by_name(weight)
    return f


def glow_text(lines: list[str], font, spacing: float = 1.25) -> Image.Image:
    """Белый моно-текст с мягкой тёмной тенью вокруг (как в рефе)."""
    lh = int(font.size * spacing)
    w = int(max(font.getlength(t) for t in lines)) + 60
    h = lh * len(lines) + 60
    txt = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(txt)
    for k, t in enumerate(lines):
        d.text((w / 2, 30 + (k + 0.5) * lh), t, font=font, fill=(255, 255, 255, 255), anchor="mm")
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sh.putalpha(txt.getchannel("A").filter(ImageFilter.GaussianBlur(font.size * 0.18)).point(lambda v: int(v * 0.75)))
    out = Image.alpha_composite(sh, txt)
    return out.crop(out.getbbox())


def wrap(text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        c = (cur + " " + w).strip()
        if cur and font.getlength(c) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = c
    return lines + [cur]


def rounded(img: Image.Image, r: float = 0.22) -> Image.Image:
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=int(img.width * r), fill=255)
    out = img.convert("RGBA")
    out.putalpha(Image.fromarray(np.minimum(np.asarray(out.getchannel("A")), np.asarray(m))))
    return out


def icon(name: str, side: int) -> Image.Image:
    """Квадратная иконка приложения: цветные — как есть, знаки без фона — на белом скруглённом квадрате."""
    key = ICON[name]
    if key == "simplify":
        card = Image.new("RGBA", (side, side), (44, 178, 208, 255))
        mark = Image.open(LOGOS / "simplify_mark.png").convert("L")
        mark.thumbnail((int(side * 0.62), int(side * 0.62)), Image.Resampling.LANCZOS)
        card.paste(Image.new("RGBA", mark.size, (255, 255, 255, 255)), ((side - mark.width) // 2, (side - mark.height) // 2), mark)
        return rounded(card)
    full = {"linkedin": PLOGOS / "png_linkedin.png", "globalwork": PLOGOS / "gs_globalwork.ai.png",
            "chatgpt": LOGOS / "png_chatgpt.png", "teal": LOGOS / "gs_tealhq.com.png",
            "indeed": PLOGOS / "gs_indeed.com.png"}
    if key in full:
        return rounded(Image.open(full[key]).convert("RGBA").resize((side, side), Image.Resampling.LANCZOS))
    src = {"gsheets": "png_gsheets.png", "gdocs": "png_gdocs.png", "chrome": "png_chrome.png", "notion": "png_notion.png",
           "kickresume": "gs_kickresume.com.png", "loopcv": "gs_loopcv.pro.png"}[key]
    mark = Image.open(LOGOS / src).convert("RGBA")
    inner = int(side * 0.70)
    mark.thumbnail((inner, inner), Image.Resampling.LANCZOS)
    if max(mark.size) < inner:
        k = inner / max(mark.size)
        mark = mark.resize((int(mark.width * k), int(mark.height * k)), Image.Resampling.LANCZOS)
    card = Image.new("RGBA", (side, side), (255, 255, 255, 255))
    card.alpha_composite(mark, ((side - mark.width) // 2, (side - mark.height) // 2))
    return rounded(card)


def row_assets(k: int) -> dict:
    x0, y0, x1, y1 = text_rect(W, H)
    title_font = mono(TITLE_PX)
    # −40: запас на свечение вокруг букв
    title = glow_text(wrap(ROWS[k][0].upper(), title_font, x1 - x0 - 40), title_font)
    icon_top = TITLE_TOP + title.height + 45
    items = []
    for j, name in enumerate(ROWS[k][1]):
        lf = mono(LABEL_PX, "Bold")
        lab = glow_text(wrap(name, lf, ICON_SIDE + 20), lf, 1.1)   # узкие подписи → шире разводка колонок
        items.append((icon(name, ICON_SIDE), lab, COLS[j]))
    return {"title": title, "icon_top": icon_top, "items": items}


def fingertips(video: Path, pops: list[float]) -> list[float | None]:
    """x кончика указательного пальца (самая высокая точка) в окне [момент слова, +0.6 с], px из 1080."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    w, h = 540, 960
    opt = vision.HandLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "hand_landmarker.task")),
                                       running_mode=vision.RunningMode.VIDEO, num_hands=2, min_hand_detection_confidence=0.3)
    lm = vision.HandLandmarker.create_from_options(opt)
    p = subprocess.Popen([FF, "-v", "error", "-i", str(video), "-vf", f"scale={w}:{h},fps=30", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    tips, k = [], 0
    while True:
        buf = p.stdout.read(w * h * 3)
        if len(buf) < w * h * 3:
            break
        r = lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                                         data=np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()), int(k * 1000 / FPS))
        hands = [(hl[8].x * W, hl[8].y * H) for hl in r.hand_landmarks]
        tips.append(min(hands, key=lambda q: q[1]) if hands else None)
        k += 1
    lm.close()
    out = []
    for t in pops:
        win = [q for q in tips[int(t * FPS):int((t + 0.6) * FPS)] if q]
        out.append(min(win, key=lambda q: q[1])[0] if win else None)
    return out


def place_columns(xs: list[float | None], halves: list[float]) -> list[float]:
    """Центры трёх логотипов: под пальцем, но внутри безопасной зоны (с учётом ширины своей подписи)
    и не налезая друг на друга."""
    x0, _y0, x1, _y1 = text_rect(W, H)
    lo = [x0 + h for h in halves]
    hi = [x1 - h for h in halves]
    c = [min(hi[j], max(lo[j], x)) if x is not None else COLS[j] for j, x in enumerate(xs)]
    gap = lambda a, b: max(halves[a], ICON_SIDE / 2) + max(halves[b], ICON_SIDE / 2) + 20  # noqa: E731
    c[1] = min(max(c[1], lo[1], c[0] + gap(0, 1)), hi[1], c[2] - gap(1, 2))
    c[0] = max(lo[0], min(c[0], c[1] - gap(0, 1)))
    c[2] = min(hi[2], max(c[2], c[1] + gap(1, 2)))
    return c


def frame_layer(assets: dict, t: float, pops: list[float], cols: list[float] | None = None) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ti = assets["title"]
    boxes = [((W - ti.width) // 2, TITLE_TOP)]
    layer.alpha_composite(ti, boxes[0])
    for j, ((ic, lab, cx), tp) in enumerate(zip(assets["items"], pops)):
        if cols:
            cx = cols[j]
        if t < tp:
            continue
        u = min(1.0, (t - tp) / POP)
        s = 0.55 + 0.55 * u if u < 0.75 else 1.0 + 0.1 * (1 - u) / 0.25   # 0.55 → 1.1 → 1.0
        a = min(1.0, u * 2.5)
        side = max(2, int(ICON_SIDE * s))
        im = ic.resize((side, side), Image.Resampling.BILINEAR)
        if a < 1:
            im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
        cy = assets["icon_top"] + ICON_SIDE / 2
        layer.alpha_composite(im, (int(cx - side / 2), int(cy - side / 2)))
        if u >= 0.75:
            layer.alpha_composite(lab, (int(cx - lab.width / 2), assets["icon_top"] + ICON_SIDE + 10))
    return layer


def audio_filter(src: Path) -> str:
    loud = "highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11"
    log = subprocess.run([FF, "-hide_banner", "-i", str(src), "-map", "0:a:0", "-af", f"{loud}:print_format=json", "-f",
                          "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log).group(0))
    return (f"{loud}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
            f"measured_thresh={m['input_thresh']}:offset={m['target_offset']},aresample=48000")


def build(name: str, plan: list[tuple[str, int]]) -> None:
    work = Path(tempfile.mkdtemp(prefix="gwtiers_"))
    trip = {c: triplets(c) for c in {c for c, _ in plan}}
    segs = []                                     # (клип, начало, конец, [моменты слов в выходном ролике])
    t_out = 0.0
    for k, (clip, i) in enumerate(plan):
        tr = trip[clip]
        b, g, am = tr[i]
        start = max(0.0, b - PRE)
        nxt = tr[i + 1][0] - PRE if i + 1 < len(tr) and k + 1 < len(plan) and plan[k + 1] == (clip, i + 1) else 1e9
        end = min(nxt, am + POST, duration(SRC / f"{clip}.MOV"))
        segs.append((clip, start, end, [t_out + (x - start) for x in (b, g, am)]))
        t_out += end - start
    # 1) база: склейка кусков + тонмаппинг + звук
    inputs, parts = [], []
    for n, (clip, s, e, _p) in enumerate(segs):
        inputs += ["-i", str(SRC / f"{clip}.MOV")]
        parts.append(f"[{n}:v]{TM},trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS,setsar=1[v{n}];"
                     f"[{n}:a:0]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{n}]")
    cat = "".join(f"[v{n}][a{n}]" for n in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=1[v][a]"
    base = work / "base.mp4"
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts) + ";" + cat, "-map", "[v]",
                    "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-c:a", "pcm_s16le",
                    str(base.with_suffix(".mov"))], check=True)
    base = base.with_suffix(".mov")
    # 2) графика поверх, покадрово
    assets = [row_assets(k) for k in range(len(ROWS))]
    tips = fingertips(base, [x for *_r, p in segs for x in p])
    # единая симметричная раскладка: центр 540, одинаковый шаг D. D подбираем так, чтобы левый/правый логотипы
    # были как можно ближе к тому, куда он показывает (среднее по всем рядам), но в безопасной зоне.
    halves = [[max(ICON_SIDE, lab.width) / 2 + 4 for _ic, lab, _cx in a["items"]] for a in assets]
    x0, _y0, x1, _y1 = text_rect(W, H)
    d_max = min(min(540 - x0 - h[0], x1 - 540 - h[2]) for h in halves)
    d_min = max(max(h[0], h[1]) + max(h[1], h[2]) for h in halves) / 2 + 20
    side = [abs(x - 540) for j, x in enumerate(tips) if x is not None and j % 3 != 1]
    ideal = float(np.mean(side)) if side else COLS[2] - 540
    D = float(np.clip(ideal, d_min, d_max))
    cols = [[540 - D, 540, 540 + D]] * len(segs)
    print(f"{name}: палец x по словам", [None if x is None else int(x) for x in tips],
          f"→ идеальный шаг {ideal:.0f}, взят {D:.0f} (предел зоны {d_max:.0f}); колонки {[int(v) for v in cols[0]]}")
    for k in range(len(ROWS)):                     # проверка безопасной зоны по полностью заполненному ряду
        lay = frame_layer(assets[k], 1e9, [0, 0, 0], cols[0])
        bad = check_box(W, H, lay.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox())
        if bad:
            raise SystemExit(f"ряд {k + 1} вне безопасной зоны: {bad}")
    dest = OUT / f"{name}_{ID}.mp4"
    dec = subprocess.Popen([FF, "-v", "error", "-i", str(base), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                            "-i", "-", "-i", str(base), "-filter_complex",
                            f"[0:v]format=yuv420p,{SET_SDR}[v];[1:a]{audio_filter(base)}[a]", "-map", "[v]", "-map", "[a]",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "18", *SDR_COLOR_ARGS, "-c:a", "aac",
                            "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(dest)], stdin=subprocess.PIPE)
    starts = [sum(e - s for _c, s, e, _p in segs[:k]) for k in range(len(segs))]
    f = 0
    while True:
        buf = dec.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        t = f / FPS
        k = max(i for i in range(len(segs)) if starts[i] <= t + 1e-6)
        frame = Image.frombuffer("RGB", (W, H), buf).convert("RGBA")
        frame.alpha_composite(frame_layer(assets[k], t, segs[k][3], cols[k]))
        enc.stdin.write(frame.convert("RGB").tobytes())
        f += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()
    print(f"{dest.name}: {t_out:.2f} с; ряды:",
          [(c, round(s, 2), round(e, 2), [round(x, 2) for x in p]) for c, s, e, p in segs])


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, plan in VIDEOS.items():
        build(name, plan)
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
