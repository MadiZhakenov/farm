#!/usr/bin/env python3
"""
1346 — готовые товарные ролики (downloads/1346/src, из Telegram «видосы для 1346»): за 3 с до конца каждого
появляется призыв из ТЗ (дословно, переносы по смыслу):
    comment "UNLOCK" / and i'll send you / the secret link 🔗
Стиль — как у подписей самого ролика: тот же шрифт (ближайший свободный), кегль, белый цвет и эффект
(обводка у TikTok-шрифта, мягкая тень у засечек / узкого / курсива). Два варианта:
  caption — ровно как их подписи (без подложки);  plate — тот же шрифт на «ступенчатой» плашке TikTok.
Чужие призывы стираем (дорисовываем фон по маске неподвижного текста, cv2.inpaint): у GTA «Link 🔗 in bio» внизу,
у каблуков «Comment "HEELS" for the link» сверху, у диспенсера «Comment DIY for more info» — наш текст встаёт на его место.
Кадр 1080×1920, fps и звук исходника, всё в безопасной зоне 9:16, NVENC (cq 27, ≤ 6 Мбит/с).

  python build_1346_reels.py      # → output/1346/{caption,plate}/<имя исходника>.mp4 + output/1346/_preview.jpg
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402  (эмодзи Apple)
from core.safe_zones import check_overlay  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
SRC = ROOT / "downloads" / "1346" / "src"
OUT = ROOT / "output" / "1346"
W, H = 1080, 1920
LEAD, FADE = 3.0, 0.2
TT = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf"
MF = ROOT / "fonts" / "match1346"
LINES = ["comment \"UNLOCK\"", "and i'll send you", "the secret link 🔗"]

# шрифт (+ оси вариативного), кегль, эффект, центр блока по y, цвета плашки; erase — чужой призыв:
# рамка поиска, правило «пиксель текста», расширение маски (обводка/тень)
STYLES = {
    "Christmas Coloring Blanket with Markers": dict(font=TT / "TikTokSans36pt-SemiBold.ttf", px=80, fx="stroke", cy=1395,
                                                    plate=(255, 255, 255), ink=(0, 0, 0)),
    "Glowing Halloween Fog Cauldrons": dict(font=MF / "Fraunces.ttf", axes=[72, 800, 50, 0], px=76, fx="shadow", cy=1330,
                                            plate=(255, 255, 255), ink=(0, 0, 0)),
    "GTA Money Stack Lamp": dict(font=MF / "BarlowSemiCondensed-SemiBold.ttf", px=88, fx="shadow", cy=380,
                                 plate=(255, 255, 255), ink=(0, 0, 0),
                                 erase=dict(box=(290, 1730, 790, 1880), rule=("max", 45), detect=("max", 110), grow=10)),
    "Light-Up Christmas Heel Boots": dict(font=TT / "TikTokSans36pt-SemiBold.ttf", px=82, fx="stroke", cy=372,
                                          plate=(255, 255, 255), ink=(0, 0, 0),
                                          erase=dict(box=(150, 95, 930, 325), rule=("min", 215), grow=8)),
    "Water Jug Cabinet Dispenser": dict(font=MF / "Montserrat-Italic.ttf", axes=[800], px=82, fx="shadow", cy=1326,
                                        plate=(255, 255, 255), ink=(0, 0, 0),
                                        erase=dict(box=(230, 1160, 850, 1495), rule=("min", 225), grow=8)),
}


# ---------------- текст ----------------
def font_of(st: dict, ss: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(st["font"]), st["px"] * ss)
    if "axes" in st:
        f.set_variation_by_axes(st["axes"])
    return f


def line_runs(font, line: str, e_px: int) -> list[tuple[str, str, float]]:
    return [(k, c, e_px * 1.08 if k == "emoji" else font.getlength(c)) for k, c in A._tokenize_runs(line)]


def text_layer(st: dict, mode: str) -> Image.Image:
    """Блок из трёх строк по центру кадра на высоте cy: caption — белый с эффектом их подписей, plate — плашки TikTok."""
    ss = 3
    font = font_of(st, ss)
    px = st["px"] * ss
    e_px = int(px * 1.12)
    runs = [line_runs(font, ln, e_px) for ln in LINES]
    widths = [sum(r[2] for r in rr) for rr in runs]
    lh = int(px * (1.34 if mode == "plate" else 1.2))
    pad = int(px * 0.8)
    cw, ch = int(max(widths)) + 2 * pad, lh * len(LINES) + 2 * pad
    ink = st["ink"] if mode == "plate" else (255, 255, 255)
    txt = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(txt)
    stroke = int(px * 0.075) if (mode == "caption" and st["fx"] == "stroke") else 0
    emojis = []
    for k, (rr, w) in enumerate(zip(runs, widths)):
        x, yc = (cw - w) / 2, pad + (k + 0.5) * lh
        for kind, chunk, cwid in rr:
            if kind == "emoji":
                emojis.append((chunk, int(x + e_px * 0.04), int(yc - e_px * 0.55)))
            else:
                d.text((x, yc), chunk, font=font, fill=ink + (255,), anchor="lm", stroke_width=stroke,
                       stroke_fill=(0, 0, 0, 255))
            x += cwid
    out = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    if mode == "plate":
        r = int(px * 0.26)
        mask = np.zeros((ch, cw), np.uint8)
        for k, w in enumerate(widths):
            x0 = int((cw - w) / 2 - px * 0.42)
            mask[pad - r + k * lh + r:pad + (k + 1) * lh + r - r, max(0, x0):x0 + int(w + px * 0.84)] = 255
        kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        mask = cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kern), cv2.MORPH_OPEN, kern)
        plate = Image.new("RGBA", (cw, ch), st["plate"] + (0,))
        plate.putalpha(Image.fromarray(mask))
        out.alpha_composite(plate)
    elif st["fx"] == "shadow":                       # мягкая тёмная тень, как у их подписей
        a = txt.getchannel("A").filter(ImageFilter.MaxFilter(3 * ss // 2 * 2 + 1)).filter(ImageFilter.GaussianBlur(4 * ss))
        sh = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        sh.putalpha(a.point(lambda v: int(v * 0.72)))
        out.alpha_composite(sh, (0, 2 * ss))
    out.alpha_composite(txt)
    for chunk, ex, ey in emojis:
        em = A._apple_emoji_rgba(chunk, e_px)
        if em is not None:
            out.alpha_composite(em, (ex, ey))
    out = out.resize((cw // ss, ch // ss), Image.Resampling.LANCZOS)
    out = out.crop(out.getbbox())
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(out, ((W - out.width) // 2, int(st["cy"] - out.height / 2)))
    return canvas


# ---------------- стирание чужого призыва ----------------
def frames(src: Path):
    p = subprocess.Popen([FF, "-v", "error", "-i", str(src), "-vf", f"scale={W}:{H}:flags=lanczos", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    try:
        while True:
            buf = p.stdout.read(W * H * 3)
            if len(buf) < W * H * 3:
                break
            yield np.frombuffer(buf, np.uint8).reshape(H, W, 3)
    finally:
        p.kill()


def text_hits(reg: np.ndarray, rule: tuple[str, int]) -> np.ndarray:
    op, thr = rule
    return (reg.max(axis=2) if op == "max" else reg.min(axis=2)) > thr


def erase_plan(src: Path, er: dict, fps: float) -> tuple[np.ndarray, int]:
    """Маска неподвижного текста (пиксели «текста» в ≥ 85 % кадров последней секунды — фон движется, текст нет)
    и первый кадр, где он появляется."""
    x0, y0, x1, y1 = er["box"]
    regs = [f[y0:y1, x0:x1].copy() for f in frames(src)]
    tail = regs[-int(fps):]
    core = np.mean([text_hits(r, er["rule"]) for r in tail], axis=0) >= 0.85
    core = cv2.morphologyEx(core.astype(np.uint8) * 255, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    # момент появления — по строгому порогу (мягкий ловит и светлый фон до надписи)
    det = er.get("detect", er["rule"])
    dcore = np.mean([text_hits(r, det) for r in tail], axis=0) >= 0.85
    # надпись есть, когда буквы светлые, а кольцо фона вокруг них — нет (светлый стол целиком не считается)
    dc = dcore.astype(np.uint8)
    ring = (cv2.dilate(dc, np.ones((19, 19), np.uint8)) > 0) & ~(cv2.dilate(dc, np.ones((7, 7), np.uint8)) > 0)
    share = [float(text_hits(r, det)[dcore].mean() - text_hits(r, det)[ring].mean()) for r in regs]
    first = next(i for i in range(len(share)) if all(s > 0.2 for s in share[i:i + 5]))    # с начала проявления
    mask = cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * er["grow"] + 1,) * 2))
    return mask, max(0, first - 2)


# ---------------- сборка ----------------
def probe(p: Path) -> tuple[float, str]:
    out = subprocess.run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate:format=duration",
                          "-of", "default=nw=1", str(p)], capture_output=True, text=True).stdout
    vals = dict(line.split("=", 1) for line in out.split())
    return float(vals["duration"]), vals["r_frame_rate"]


def render(src: Path, st: dict, layers: dict, fps_s: str, dur: float) -> dict:
    num, den = (int(v) for v in fps_s.split("/"))
    fps = num / den
    er = st.get("erase")
    mask, first = erase_plan(src, er, fps) if er else (None, 10 ** 9)
    t0 = max(0.0, dur - LEAD)
    encs = {}
    for mode in layers:
        dest = OUT / mode / f"{src.stem}.mp4"
        dest.parent.mkdir(parents=True, exist_ok=True)
        encs[mode] = subprocess.Popen(
            [FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", fps_s, "-i", "-",
             "-i", str(src), "-map", "0:v", "-map", "1:a?", "-vf", f"format=yuv420p,{SET_SDR}", "-c:v", "h264_nvenc",
             "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "27", "-b:v", "0", "-maxrate", "6M", "-bufsize", "12M",
             "-profile:v", "high", *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
             str(dest)], stdin=subprocess.PIPE)
    arr = {m: np.asarray(l).astype(np.float32) for m, l in layers.items()}
    for i, f in enumerate(frames(src)):
        img = f.copy()
        if mask is not None and i >= first:
            x0, y0, x1, y1 = er["box"]
            img[y0:y1, x0:x1] = cv2.inpaint(np.ascontiguousarray(img[y0:y1, x0:x1]), mask, 7, cv2.INPAINT_TELEA)
        t = i / fps
        for mode, enc in encs.items():
            out = img
            if t >= t0:
                a = arr[mode][..., 3:] / 255 * min(1.0, (t - t0) / FADE)
                out = (img * (1 - a) + arr[mode][..., :3] * a).astype(np.uint8)
            enc.stdin.write(np.ascontiguousarray(out).tobytes())
    for enc in encs.values():
        enc.stdin.close()
        enc.wait()
    return {"t0": t0, "erase_from": round(first / fps, 2) if er else None}


def still(path: Path, t: float) -> Image.Image:
    b = subprocess.run([FF, "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=300:533",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return Image.frombuffer("RGB", (300, 533), b)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = {"caption": [], "plate": []}
    only = [a.lower() for a in sys.argv[1:]]              # python build_1346_reels.py gta — только этот ролик
    for src in sorted(SRC.glob("*.mp4")):
        if only and not any(o in src.stem.lower() for o in only):
            continue
        st = STYLES[src.stem]
        dur, fps_s = probe(src)
        layers = {}
        for mode in rows:
            # в рамку: сначала сдвигаем блок по y внутрь зоны, если не помогает — уменьшаем кегль
            px = st["px"]
            while True:
                s2 = dict(st, px=px)
                lay = text_layer(s2, mode)
                bb = lay.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox()
                if bb[3] > 1540 or bb[1] < 200:
                    s2["cy"] = st["cy"] - max(0, bb[3] - 1536) + max(0, 204 - bb[1])
                    lay = text_layer(s2, mode)
                if not check_overlay(lay):
                    break
                px -= 2
                if px < 40:
                    raise SystemExit(f"{src.stem} [{mode}]: не влезает в безопасную зону")
            layers[mode] = lay
        info = render(src, st, layers, fps_s, dur)
        print(f"{src.stem}: {dur:.2f} с, призыв с {info['t0']:.2f} с, чужой призыв стёрт с {info['erase_from']}", flush=True)
        for mode in rows:
            rows[mode].append(still(OUT / mode / f"{src.stem}.mp4", dur - 0.8))
    n = len(rows["caption"])
    sheet = Image.new("RGB", (300 * n, 533 * 2 + 10), "white")
    for r, mode in enumerate(rows):
        for i, im in enumerate(rows[mode]):
            sheet.paste(im, (300 * i, r * 543))
    sheet.save(OUT / ("_preview.jpg" if not only else f"_preview_{'_'.join(only)}.jpg"), quality=90)
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
