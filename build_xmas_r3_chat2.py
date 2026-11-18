#!/usr/bin/env python3
"""
Раунд 3, R3-4 v2 «чат-скетч» (docs/REPOST_HYPOTHESES.md) — после отзыва юзера 2026-11-05 на v1: «базово, без шарма,
не окончено — начали с темы и закончили непонятно чем, посмотрел с 0 эмоций».

Каждый ролик — мини-скетч в iMessage (тёмная тема, вставка экрана 0.8× в безопасной зоне на размытом фоне):
персонаж-контакт (Mom 🎄 / Sis 💅 / Hubby ❤️) → интрига → «печатает…» (три точки) → видео в пузыре →
«тап», и развязка во весь экран плеера → ответы с нарастанием → панчлайн → реакция 😂 на последнее сообщение.
Звук — только музыка (синтезированные эффекты юзер забраковал).

  python build_xmas_r3_chat2.py --out output/xmas_r3/R3-4_chat
  python build_xmas_r3_chat2.py --voice --out output/xmas_r3/R3-4v_chat_voice
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_text_story as T  # noqa: E402
import build_xmas_r3_chat as C  # noqa: E402  (кадры, плеер iOS, маска, фон, константы вставки)
import render_imessage as RI  # noqa: E402

W, H, FPS = C.W, C.H, C.FPS
SS, CH, SCALE, X0, Y0, VW = C.SS, C.CH, C.SCALE, C.X0, C.Y0, C.VW
MUSIC = ROOT / "downloads" / "1311" / "music" / "callmekatushas_7667964296802487072_-14lufs.wav"
MUSIC_VOICE = None               # трек под голосовую версию; None — только голоса (прошлый трек юзер забраковал)

# сценарий: (кто, текст | VIDEO, время появления); TAP = (начало плеера, длина); REACT = (эмодзи, время); END
SCRIPTS = {
    "v1": dict(src="DcNWKlfAbOo.mp4", name="Mom 🎄", time="Today 6:47 PM",
               crop=(0.0, 0.30, 1.0, 1.0), inline=0.2, full=(6.6, 9.6),
               msgs=[("me", "did you get the milk?", 0.0), ("them", "about that…", 1.3), ("them", "VIDEO", 2.2),
                     ("me", "MOM", 7.9), ("me", "WHERE IS THE MILK", 8.5),
                     ("them", "santa doesn't drink milk anymore 🎅", 10.0), ("me", "i'm crying 😭😭😭", 10.9),
                     ("them", "also your dad hasn't moved from the couch in 3 hours", 12.4)],
               tap=(4.6, 3.0), react=("😂", 13.5), end=15.2),
    "v2": dict(src="DdGwGMEx-Uj.mp4", name="Sis 💅", time="Today 2:47 AM",
               crop=(0.0, 0.0, 1.0, 0.64), inline=7.3, full=(9.4, 12.6), full_crop=(0.0, 0.0, 1.0, 1.0),
               msgs=[("me", "why is my ceiling snowing at 3am??", 0.0), ("them", "don't be mad", 1.3),
                     ("them", "VIDEO", 2.2), ("me", "you put one in MY room??", 8.1),
                     ("them", "i put one in every room 🎄", 9.5), ("me", "even the bathroom??", 10.4),
                     ("them", "ESPECIALLY the bathroom", 11.8)],
               tap=(4.6, 3.2), react=("😂", 12.9), end=14.6),
    "v3": dict(src="DdZ5O2bR39c.mp4", name="Hubby ❤️", time="Today 4:12 PM",
               crop=(0.0, 0.30, 1.0, 1.0), inline=0.3, full=(7.3, 10.2),
               msgs=[("me", "babe the tree fell again", 0.0), ("them", "ON WHO??", 1.3), ("me", "VIDEO", 2.1),
                     ("them", "wait where's the tree", 8.0), ("me", "we don't need a tree anymore 🎄", 8.9),
                     ("them", "i literally just bought a new one 😭", 10.4)],
               tap=(4.5, 2.9), react=("😂", 11.5), end=13.2),
}
TYPING = 0.7                      # «печатает…» перед каждым ответом собеседника

# озвучка ElevenLabs (юзер 2026-11-05): А — «я» (Eve), мама — Jessica, сестра — Eve, муж — Adam;
# (файл, начало, конец по Whisper — конец потом подрезается по тишине)
VO_DIR = ROOT / "downloads" / "xmas_proj" / "chat_vo"
VO_LINES = {
    "v1": [("eve_1307.mp3", 0.0, 1.56), ("jessica_1308.mp3", 0.0, 1.24), None, ("eve_1307.mp3", 1.56, 3.16),
           ("eve_1307.mp3", 3.16, 5.12), ("jessica_1308.mp3", 1.24, 3.88), ("eve_1307.mp3", 5.12, 7.24),
           ("jessica_1308.mp3", 3.88, 7.55)],
    "v2": [("eve_1307.mp3", 7.24, 10.54), ("eve_130937.mp3", 0.0, 1.2), None, ("eve_1307.mp3", 10.54, 13.1),
           ("eve_130937.mp3", 1.2, 3.3), ("eve_1307.mp3", 13.1, 15.1), ("eve_130937.mp3", 3.3, 5.57)],
    "v3": [("eve_1307.mp3", 15.1, 17.26), ("adam_1309.mp3", 0.0, 1.24), None, ("adam_1309.mp3", 1.24, 3.48),
           ("eve_1307.mp3", 17.26, 19.34), ("adam_1309.mp3", 3.48, 5.49)],
}
INLINE_LEN, GAP, TAIL = 2.0, 0.2, 1.4
SR = 44100


def load_clip(name: str, a: float, b: float):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(VO_DIR / name),
                          "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.float32).copy()
    env = np.convolve(np.abs(x), np.ones(441) / 441, mode="same")     # 10 мс
    on = np.where(env > max(0.01, env.max() * 0.04))[0]
    if len(on):
        x = x[max(0, on[0] - 441): min(len(x), on[-1] + 2205)]        # без тишины по краям (+50 мс хвост)
    return x


def voice_plan(key: str):
    """Время появления каждого сообщения = начало его реплики; перед репликой собеседника — «печатает…»;
    видео: пузырь играет INLINE_LEN, затем плеер; реакция после последней реплики."""
    import numpy as np
    v = SCRIPTS[key]
    clips = [load_clip(*ln) if ln else None for ln in VO_LINES[key]]
    t, msgs, track, tap = 0.0, [], [], None
    for i, ((who, text, _), clip) in enumerate(zip(v["msgs"], clips)):
        if text == "VIDEO":
            msgs.append((who, text, t))
            tap = (t + INLINE_LEN, v["tap"][1])
            t = tap[0] + tap[1] + 0.35
            continue
        if who == "them" and i > 0:
            t += TYPING
        msgs.append((who, text, t))
        track.append((t, clip))
        t += len(clip) / SR + GAP
    react_t = t + 0.1
    end = react_t + TAIL
    mix = np.zeros(int(SR * (end + 0.5)), np.float32)
    for ta, clip in track:
        k = int(ta * SR)
        mix[k:k + len(clip)] += clip
    return msgs, tap, react_t, end, mix


def layout(rows, vid_h, react_last=False):
    out, y, prev = [], RI.STATUS_H + RI.HEADER_H + 26, None
    px = RI.FONT_PX
    last_text = max((i for i, (k, t) in enumerate(rows) if k != "time" and t not in ("VIDEO", "TYPING")), default=-1)
    for i, (kind, text) in enumerate(rows):
        if react_last and i == last_text:
            y += 46                                     # место под кружок реакции
        if kind == "time":
            out.append(dict(kind="time", text=text, y=y))
            y += 64
            prev = None
            continue
        if prev is not None:
            y += RI.GAP_SAME if prev == kind else RI.GAP_SWITCH
        if text == "VIDEO":
            x0 = W - RI.SIDE - VW if kind == "me" else RI.SIDE
            out.append(dict(kind="video", who=kind, x0=x0, y=y, w=VW, h=vid_h))
            y += vid_h
        elif text == "TYPING":
            out.append(dict(kind="typing", who=kind, x0=RI.SIDE, y=y, w=150, h=94))
            y += 94
        else:
            lines = T.wrap(text, px, RI.MAX_W - 2 * RI.PAD_X)
            lh = round(px * RI.LINE_GAP)
            bw = int(max(T.text_w(ln, px) for ln in lines) + 2 * RI.PAD_X)
            bh = int(lh * len(lines) + 2 * RI.PAD_Y)
            x0 = W - RI.SIDE - bw if kind == "me" else RI.SIDE
            out.append(dict(kind="text", who=kind, x0=x0, y=y, w=bw, h=bh, lines=lines, lh=lh))
            y += bh
        prev = kind
    for i, b in enumerate(out):
        if b["kind"] == "time":
            continue
        nxt = next((o for o in out[i + 1:] if o["kind"] != "time"), None)
        b["tail"] = nxt is None or nxt["who"] != b["who"]
    return out


def chat_image(bubbles, name, scroll, dots=-1, react=None):
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
            d.rounded_rectangle((x0, y, x0 + bw, y + bh), radius=34 * s, fill=(0, 0, 0, 0))
            hole = (b["x0"], b["y"] - scroll, b["w"], b["h"])
            continue
        right = b["who"] == "me"
        color = RI.C_ME if right else RI.C_THEM
        r = int(min(bh / 2 - 2, (px * RI.LINE_GAP + 2 * RI.PAD_Y * s) / 2 - 2))
        if b["kind"] == "typing":                       # серый пузырь с тремя точками
            d.rounded_rectangle((x0, y, x0 + bw, y + bh), radius=r, fill=color)
            for k in range(3):
                cx, cy = x0 + (42 + k * 33) * s, y + bh / 2
                c = 200 if k == dots % 3 else 120
                d.ellipse((cx - 11 * s, cy - 11 * s, cx + 11 * s, cy + 11 * s), fill=(c, c, c + 4, 255))
            continue
        corners = (True, True, not (b["tail"] and right), not (b["tail"] and not right))
        d.rounded_rectangle((x0, y, x0 + bw, y + bh), radius=r, corners=corners, fill=color)
        if b["tail"]:
            RI.tail(d, x0 + bw if right else x0, y + bh, right, color, s, r)
        ty = y + RI.PAD_Y * s
        for ln in b["lines"]:
            T.draw_text(img, x0 + RI.PAD_X * s, ty, ln, px)
            ty += b["lh"] * s
    if react:                                           # tapback на последнем сообщении: кружок с эмодзи у угла
        emo, b = react
        y = (b["y"] - scroll) * s
        right = b["who"] == "me"
        cx = (b["x0"] + (8 if right else b["w"] - 8)) * s
        cy = y - 6 * s
        rr = 56 * s
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=RI.C_ME if not right else RI.C_THEM,
                  outline=RI.C_BG, width=6 * s)
        T.draw_text(img, cx - 37 * s, cy - 47 * s, emo, 72 * s)
    RI.input_bar(img, s, CH)
    RI.header(img, s, name)
    d.rectangle((0, 0, W * s, RI.STATUS_H * s), fill=RI.C_HEADER)
    RI.status_bar(img, s, "9:41")
    return img.resize((W, CH), Image.Resampling.LANCZOS), hole


def build(key: str, out: Path, work: Path, voice: bool = False) -> Path:
    v = dict(SCRIPTS[key])
    vo_wav = None
    if voice:
        import wave
        import numpy as np
        msgs_v, tap_v, react_t, end_v, mix = voice_plan(key)
        v.update(msgs=msgs_v, tap=tap_v, react=(v["react"][0], react_t), end=end_v)
        vo_wav = work / f"chatvo_{key}.wav"
        with wave.open(str(vo_wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())
    src = C.SRC / v["src"]
    sw, sh = C.probe_wh(src)
    cx0, cy0, cx1, cy1 = v["crop"]
    vid_h = int(VW * (sh * (cy1 - cy0)) / (sw * (cx1 - cx0)))
    msgs = v["msgs"]
    t_vid = next(t for _, txt, t in msgs if txt == "VIDEO")
    tap0, tap_len = v["tap"]
    inline = C.read_frames(src, v["inline"], v["inline"] + (tap0 - t_vid) + 0.2, v["crop"],
                           (int(VW * SCALE), int(vid_h * SCALE)))
    fcrop = v.get("full_crop", v["crop"])
    fh = int(W * (sh * (fcrop[3] - fcrop[1])) / (sw * (fcrop[2] - fcrop[0]))) // 2 * 2
    full = C.read_frames(src, *v["full"], fcrop, (W, fh))
    bg_src = full[len(full) // 2]
    bg = bg_src.resize((W, H)).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.45)
    pw, ph = int(W * SCALE), int(CH * SCALE)
    pmask = C.round_mask(pw, ph, 44)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((X0 - 6, Y0 - 6, X0 + pw + 6, Y0 + ph + 6), radius=50, fill=(0, 0, 0, 150))
    bg = Image.alpha_composite(bg.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(14))).convert("RGB")

    bottom_limit = CH - 230 - 20
    cache = {}

    def state(n, typing, phase, react):
        key_ = (n, typing, phase if typing else 0, react)
        if key_ in cache:
            return cache[key_]
        rows = [("time", v["time"])] + [(w, t) for w, t, _ in msgs[:n]]
        if typing:
            rows.append(("them", "TYPING"))
        bubbles = layout(rows, vid_h, react_last=react)
        last = [b for b in bubbles if b["kind"] != "time"][-1]
        scroll = max(0, last["y"] + last["h"] - bottom_limit)
        rb = None
        if react:
            rb = (v["react"][0], [b for b in bubbles if b["kind"] == "text"][-1])
        img, hole = chat_image(bubbles, v["name"], scroll, dots=phase if typing else -1, react=rb)
        cache[key_] = (img.resize((pw, ph), Image.Resampling.LANCZOS), hole)
        return cache[key_]

    dest = out / f"R3-4{'v' if voice else ''}_chat_{key}_noid.mp4"
    out.mkdir(parents=True, exist_ok=True)
    total = v["end"]
    if voice and MUSIC_VOICE is None:                  # только голоса (юзер: музыка не подходит; трек добавить в TikTok)
        a_in = ["-i", str(vo_wav)]
        a_fc = f"[1:a]aresample=44100,loudnorm=I=-15:TP=-1.5:LRA=11,apad,atrim=0:{total:.3f}[a]"
    elif voice:                                         # голоса громко, выбранный трек подложкой
        a_in = ["-i", str(vo_wav), "-stream_loop", "-1", "-i", str(MUSIC_VOICE)]
        a_fc = (f"[1:a]aresample=44100,loudnorm=I=-15:TP=-1.5:LRA=11,apad[vo];[2:a]aresample=44100,volume=0.10[m];"
                f"[vo][m]amix=inputs=2:normalize=0:duration=first,atrim=0:{total:.3f},"
                f"afade=t=out:st={total - 0.5:.3f}:d=0.5[a]")
    else:
        a_in = ["-stream_loop", "-1", "-i", str(MUSIC)]
        a_fc = (f"[1:a]atrim=0:{total:.3f},afade=t=out:st={total - 0.6:.3f}:d=0.6,"
                f"loudnorm=I=-15:TP=-1.5:LRA=11,aresample=44100[a]")
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         *a_in,
         "-filter_complex", a_fc,
         "-map", "0:v", "-map", "[a]", "-t", f"{total:.3f}",
         "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
         "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
         "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
         "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
         "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], stdin=subprocess.PIPE)
    for fi in range(int(total * FPS)):
        t = fi / FPS
        canvas = bg.copy()
        if tap0 <= t < tap0 + tap_len:
            k = min(len(full) - 1, int((t - tap0) * FPS))
            canvas.paste(C.player_image(full[k]).resize((pw, ph), Image.Resampling.LANCZOS), (X0, Y0), pmask)
        else:
            n = sum(1 for _, _, ta in msgs if ta <= t + 1e-6)
            nxt = msgs[n] if n < len(msgs) else None
            typing = bool(nxt and nxt[0] == "them" and nxt[2] - TYPING <= t and n > 0
                          and not (tap0 <= nxt[2] - TYPING < tap0 + tap_len and t < tap0 + tap_len))
            react = t >= v["react"][1]
            img, hole = state(max(1, n), typing, int(t * 4) % 3, react)
            screen = Image.new("RGB", (pw, ph), (0, 0, 0))
            if hole:
                if t < tap0:
                    kk = min(len(inline) - 1, int(max(0.0, t - t_vid) * FPS))
                    fr = inline[kk]
                else:
                    fr = inline[min(len(inline) - 1, int(0.6 * FPS))]
                hx, hy = int(hole[0] * SCALE), int(hole[1] * SCALE)
                screen.paste(fr, (hx, hy))
                if t >= tap0:
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
    ap.add_argument("--voice", action="store_true", help="озвучка двумя голосами ElevenLabs, тайминг по репликам")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = ROOT / "output" / "_work" / "xmas_r3"
    work.mkdir(parents=True, exist_ok=True)
    for key in a.only.split(","):
        print("  ", build(key, a.out, work, a.voice), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
