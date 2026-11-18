#!/usr/bin/env python3
"""
Раунд 3, гипотеза R3-4 «чат-обёртка» (docs/REPOST_HYPOTHESES.md): чужой товарный ролик приходит в переписке iMessage.
Экран телефона (тёмная тема, наш рендер render_imessage) вставкой 0.8× внутри безопасной зоны на размытом фоне:
  0.0  шапка «Sis», время, первое сообщение;
  0.6  пузырь-видео — ролик играет внутри (кроп без чужих подписей);
  1.7  второе сообщение;
  2.8  «тап» → ролик на весь экран телефона (плеер iOS) ~3 с — самый сильный момент;
  5.8  снова чат, ответы появляются по одному;  ~10 с конец.
Звук: свои синтезированные «дзынь»/«вжух» сообщений + тихая музыка (при заливке лучше трендовый звук в TikTok).
Своё в кадре ≈ 60–75 % площади/времени, чужие кадры — только внутри пузыря и в плеере.

  python build_xmas_r3_chat.py --out output/xmas_r3/R3-4_chat
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_text_story as T  # noqa: E402  (шрифт SF, эмодзи Apple)
import render_imessage as RI  # noqa: E402  (статус-бар, шапка, хвостики, строка ввода — тёмная тема)

W, H, FPS = 1080, 1920, 30
SRC = ROOT / "downloads" / "xmas_proj" / "src"
MUSIC = ROOT / "downloads" / "1303" / "music" / "gZIrKXCzue8.m4a"
SS = 2                       # рендер чата в 2× и уменьшение
CH = 1700                    # логическая высота экрана телефона (обрезанный скрин), ширина 1080
SCALE, X0, Y0 = 0.8, 108, 196   # вставка 864×1360: текст пузырей внутри x 140–940, y 200–1556
VW = 600                     # ширина пузыря-видео (логическая)

# crop — доли кадра исходника без чужих подписей; inline/full — секунды исходника (в пузыре / в плеере)
VIDEOS = {
    "v1": dict(src="DcNWKlfAbOo.mp4", crop=(0.0, 0.30, 1.0, 1.0), inline=(0.0, 3.2), full=(6.6, 9.6),
               name="Sis", time="Today 7:42 PM",
               msgs=[("them", "mom went to costco for milk"), ("them", "VIDEO"), ("them", "she came back with THIS 😭"),
                     ("TAP", ""), ("me", "NO WAY 😭"), ("me", "is that santa flying around the living room??"),
                     ("them", "dad already wants a second one"), ("me", "ok i'm going tomorrow")]),
    "v2": dict(src="DdGwGMEx-Uj.mp4", crop=(0.0, 0.0, 1.0, 0.64), inline=(2.75, 5.95), full=(9.4, 12.4),
               full_crop=(0.0, 0.0, 1.0, 1.0),
               name="Sis", time="Today 9:18 PM",
               msgs=[("them", "DO NOT show this to mom 😭"), ("them", "VIDEO"), ("them", "she'll put one in every room"),
                     ("TAP", ""), ("me", "too late i already sent it to her"), ("them", "WHY 😭😭"),
                     ("me", "she ordered 3"), ("them", "i'm moving out")]),
    "v3": dict(src="DdZ5O2bR39c.mp4", crop=(0.0, 0.30, 1.0, 1.0), inline=(0.0, 3.4), full=(7.3, 10.2),
               name="Sis", time="Today 6:05 PM",
               msgs=[("them", "remember dad and the tree last year 💀"), ("them", "VIDEO"),
                     ("them", "this year we're doing THIS instead"), ("TAP", ""), ("me", "LMAOOO the tree 😭"),
                     ("me", "wait the ceiling is so pretty"), ("them", "the kids won't leave the room"),
                     ("me", "ordering one rn")]),
}
T_MSG = [0.0, 0.6, 1.7]           # первые три (текст, видео, текст)
T_TAP, FULL_LEN = 2.8, 3.0
T_AFTER = [0.6, 1.4, 2.2, 3.0]    # после возврата из плеера
END_PAD = 1.0


def probe_wh(p: Path) -> tuple[int, int]:
    o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip().split(",")
    return int(o[0]), int(o[1])


def read_frames(src: Path, t0: float, t1: float, crop: tuple, size: tuple[int, int]) -> list[Image.Image]:
    sw, sh = probe_wh(src)
    cx0, cy0, cx1, cy1 = crop
    cw, ch = int(sw * (cx1 - cx0)) // 2 * 2, int(sh * (cy1 - cy0)) // 2 * 2
    w, h = size
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", str(src),
                          "-vf", f"crop={cw}:{ch}:{int(sw * cx0)}:{int(sh * cy0)},fps={FPS},scale={w}:{h}:flags=lanczos",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    return [Image.frombuffer("RGB", (w, h), raw[i * w * h * 3:(i + 1) * w * h * 3]) for i in range(n)]


def layout(rows: list, vid_h: int) -> list[dict]:
    """Позиции пузырей в логических px (ширина 1080) без прокрутки."""
    out, y, prev = [], RI.STATUS_H + RI.HEADER_H + 26, None
    px = RI.FONT_PX
    for i, (kind, text) in enumerate(rows):
        if kind == "time":
            out.append(dict(kind="time", text=text, y=y))
            y += 64
            prev = None
            continue
        who = kind
        if prev is not None:
            y += RI.GAP_SAME if prev == who else RI.GAP_SWITCH
        if text == "VIDEO":
            bw, bh = VW, vid_h
            out.append(dict(kind="video", who=who, x0=RI.SIDE, y=y, w=bw, h=bh))
        else:
            lines = T.wrap(text, px, RI.MAX_W - 2 * RI.PAD_X)
            lh = round(px * RI.LINE_GAP)
            bw = int(max(T.text_w(ln, px) for ln in lines) + 2 * RI.PAD_X)
            bh = int(lh * len(lines) + 2 * RI.PAD_Y)
            x0 = W - RI.SIDE - bw if who == "me" else RI.SIDE
            out.append(dict(kind="text", who=who, x0=x0, y=y, w=bw, h=bh, lines=lines, lh=lh))
        y += bh
        prev = who
    for i, b in enumerate(out):                       # хвостик — у последнего пузыря подряд от одного автора
        if b["kind"] == "time":
            continue
        nxt = next((o for o in out[i + 1:] if o["kind"] != "time"), None)
        b["tail"] = nxt is None or nxt["who"] != b["who"]
    return out


def chat_image(bubbles: list[dict], name: str, scroll: int) -> tuple[Image.Image, tuple | None]:
    """Экран чата 1080×CH (в SS×) с прозрачным окном под видео; возвращает картинку и окно (x, y, w, h) логически."""
    s = SS
    img = Image.new("RGBA", (W * s, CH * s), RI.C_BG)
    d = ImageDraw.Draw(img)
    hole = None
    px = RI.FONT_PX * s
    for b in bubbles:
        y = (b["y"] - scroll) * s
        if b["kind"] == "time":
            spx = 30 * s
            T.draw_text(img, W * s / 2 - T.text_w(b["text"], spx) / 2, y + 10 * s, b["text"], spx, fill=RI.C_GRAY)
            continue
        x0, bw, bh = b["x0"] * s, b["w"] * s, b["h"] * s
        if b["kind"] == "video":
            r = 34 * s
            d.rounded_rectangle((x0, y, x0 + bw, y + bh), radius=r, fill=(0, 0, 0, 0))
            hole = (b["x0"], b["y"] - scroll, b["w"], b["h"])
            continue
        right = b["who"] == "me"
        color = RI.C_ME if right else RI.C_THEM
        r = int(min(bh / 2 - 2, (px * RI.LINE_GAP + 2 * RI.PAD_Y * s) / 2 - 2))
        corners = (True, True, not (b["tail"] and right), not (b["tail"] and not right))
        d.rounded_rectangle((x0, y, x0 + bw, y + bh), radius=r, corners=corners, fill=color)
        if b["tail"]:
            RI.tail(d, x0 + bw if right else x0, y + bh, right, color, s, r)
        ty = y + RI.PAD_Y * s
        for ln in b["lines"]:
            T.draw_text(img, x0 + RI.PAD_X * s, ty, ln, px)
            ty += b["lh"] * s
    RI.input_bar(img, s, CH)
    RI.header(img, s, name)
    d.rectangle((0, 0, W * s, RI.STATUS_H * s), fill=RI.C_HEADER)
    RI.status_bar(img, s, "9:41")
    return img.resize((W, CH), Image.Resampling.LANCZOS), hole


def player_image(frame: Image.Image) -> Image.Image:
    """Плеер iOS на весь экран телефона: чёрный фон, видео по ширине, крестик и полоса прокрутки."""
    img = Image.new("RGB", (W, CH), (0, 0, 0))
    fw, fh = frame.size
    k = min(W / fw, (CH - 300) / fh)
    fr = frame.resize((int(fw * k), int(fh * k)), Image.Resampling.LANCZOS)
    img.paste(fr, ((W - fr.width) // 2, (CH - fr.height) // 2))
    d = ImageDraw.Draw(img)
    d.ellipse((40, 70, 120, 150), fill=(44, 44, 46))
    d.line((64, 94, 96, 126), fill=(230, 230, 230), width=6)
    d.line((96, 94, 64, 126), fill=(230, 230, 230), width=6)
    d.rounded_rectangle((60, CH - 120, W - 60, CH - 112), radius=4, fill=(90, 90, 94))
    return img


def round_mask(w: int, h: int, r: int) -> Image.Image:
    m = Image.new("L", (w * 2, h * 2), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * 2 - 1, h * 2 - 1), radius=r * 2, fill=255)
    return m.resize((w, h), Image.Resampling.LANCZOS)


def blip(freqs, dur, sr=44100, vol=0.35):
    t = np.arange(int(sr * dur)) / sr
    env = np.exp(-t * 18)
    sig = sum(np.sin(2 * math.pi * f * t) * (0.6 ** k) for k, f in enumerate(freqs))
    return (sig * env * vol).astype(np.float32)


def swoosh(dur=0.22, sr=44100, vol=0.25):
    n = int(sr * dur)
    noise = np.random.default_rng(1).normal(size=n).astype(np.float32)
    k = np.linspace(0, 1, n)
    f = np.convolve(noise, np.ones(30) / 30, mode="same")
    return (f * np.sin(np.pi * k) * vol * 3).astype(np.float32)


def audio_track(events: list[tuple[float, str]], total: float, dest: Path) -> None:
    sr = 44100
    mix = np.zeros(int(sr * (total + 0.5)), np.float32)
    for t, kind in events:
        snd = blip((1318.5, 1760.0), 0.35) if kind == "them" else swoosh()
        i = int(t * sr)
        mix[i:i + len(snd)] += snd[: len(mix) - i]
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())


def build(key: str, out: Path, work: Path) -> Path:
    v = VIDEOS[key]
    src = SRC / v["src"]
    sw, sh = probe_wh(src)
    cx0, cy0, cx1, cy1 = v["crop"]
    vid_h = int(VW * (sh * (cy1 - cy0)) / (sw * (cx1 - cx0)))
    rows = [("time", v["time"])] + [(k, t) for k, t in v["msgs"] if k != "TAP"]
    bubbles = layout(rows, vid_h)
    texts = [b for b in bubbles if b["kind"] != "time"]
    # когда появляется каждый пузырь
    t_full_end = T_TAP + FULL_LEN
    appear = T_MSG + [t_full_end + x for x in T_AFTER]
    total = appear[-1] + END_PAD
    inline = read_frames(src, *v["inline"], v["crop"], (int(VW * SCALE), int(vid_h * SCALE)))
    fcrop = v.get("full_crop", v["crop"])             # в плеере — тот же кроп без чужих подписей
    fh = int(W * (sh * (fcrop[3] - fcrop[1])) / (sw * (fcrop[2] - fcrop[0]))) // 2 * 2
    full = read_frames(src, *v["full"], fcrop, (W, fh))
    bg_src = full[len(full) // 2].resize((W, int(W * full[0].height / full[0].width)))
    bg = bg_src.resize((W, H)).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.45)
    pw, ph = int(W * SCALE), int(CH * SCALE)
    pmask = round_mask(pw, ph, 44)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((X0 - 6, Y0 - 6, X0 + pw + 6, Y0 + ph + 6), radius=50, fill=(0, 0, 0, 150))
    bg = Image.alpha_composite(bg.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(14))).convert("RGB")

    # состояния чата: число видимых пузырей и прокрутка (низ последнего — над строкой ввода)
    states = {}
    bottom_limit = CH - 230 - 20

    def state(n):
        if n not in states:
            last = texts[n - 1]
            scroll = max(0, last["y"] + last["h"] - bottom_limit)
            vis = [b for b in bubbles if b["kind"] == "time"] + texts[:n]
            img, hole = chat_image(vis, v["name"], scroll)
            states[n] = (img.resize((pw, ph), Image.Resampling.LANCZOS), hole)
        return states[n]

    dest = out / f"R3-4_chat_{key}_noid.mp4"
    out.mkdir(parents=True, exist_ok=True)
    wav = work / f"{key}_sfx.wav"
    events = [(appear[i], texts[i]["who"]) for i in range(len(texts))]
    audio_track(events, total, wav)
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-i", str(wav), "-stream_loop", "-1", "-i", str(MUSIC),
         "-filter_complex", f"[2:a]atrim=0:{total:.3f},volume=0.18[m];[1:a][m]amix=inputs=2:normalize=0,"
                            f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100[a]",
         "-map", "0:v", "-map", "[a]", "-t", f"{total:.3f}",
         "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
         "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
         "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
         "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
         "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], stdin=subprocess.PIPE)
    n_frames = int(total * FPS)
    for fi in range(n_frames):
        t = fi / FPS
        canvas = bg.copy()
        if T_TAP <= t < t_full_end:
            k = min(len(full) - 1, int((t - T_TAP) * FPS))
            scr = player_image(full[k]).resize((pw, ph), Image.Resampling.LANCZOS)
            canvas.paste(scr, (X0, Y0), pmask)
        else:
            n = sum(1 for a in appear if a <= t + 1e-6)
            img, hole = state(max(1, n))
            screen = Image.new("RGB", (pw, ph), (0, 0, 0))
            if hole:
                if t < T_TAP:
                    k = min(len(inline) - 1, int(max(0.0, t - appear[1]) * FPS))
                else:                                    # после плеера — в пузыре стоп-кадр с кнопкой play
                    k = len(inline) // 2
                fr = inline[k]
                hx, hy = int(hole[0] * SCALE), int(hole[1] * SCALE)
                screen.paste(fr, (hx, hy))
                if t >= T_TAP:
                    dd = ImageDraw.Draw(screen)
                    cx, cy = hx + fr.width // 2, hy + fr.height // 2
                    dd.ellipse((cx - 44, cy - 44, cx + 44, cy + 44), fill=(30, 30, 30))
                    dd.polygon([(cx - 14, cy - 22), (cx - 14, cy + 22), (cx + 24, cy)], fill=(255, 255, 255))
            screen.paste(img, (0, 0), img)
            canvas.paste(screen, (X0, Y0), pmask)
        enc.stdin.write(canvas.tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise SystemExit(f"ffmpeg упал на {key}")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "xmas_r3" / "R3-4_chat")
    ap.add_argument("--only", default="v1,v2,v3")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = ROOT / "output" / "_work" / "xmas_r3"
    work.mkdir(parents=True, exist_ok=True)
    for key in a.only.split(","):
        print("  ", build(key, a.out, work), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
