#!/usr/bin/env python3
"""
«Текстовая история» (формат @digital_bard): чёрная карточка iMessage сверху
на фоне геймплея, сообщения появляются по одному синхронно с озвучкой.

  python build_text_story.py --script story.txt --bg gameplay.mp4 --audio voice.mp3 --out story.mp4
  python build_text_story.py --script story.txt --voice-dir voice/ --bg-dir clips/ -n 5 --out out_dir/

--voice-dir: реплики отдельными файлами NN_<кто>.wav по порядку сценария;
сообщение появляется ровно когда начинается его реплика, между репликами
пауза --gap. --cut-at: обрыв последней реплики на этой секунде внутри неё
(ролик кончается на полуслове). --bg-dir: на каждый ролик свой фон.

Сценарий (UTF-8):
  === Crush ❤️          новый экран с шапкой контакта
  ---                   новый экран без шапки
  me: Hayaaa!           синий пузырь справа
  them: Umm who?        серый пузырь слева
Первое сообщение стоит на экране с первого кадра; остальные — когда их
начинают читать (Whisper по озвучке) или по темпу чтения без --audio.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR, vf_scale_crop_fps_sdr  # noqa: E402

W, H, FPS = 1080, 1920, 30
SS = 2
FONT_VAR = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "variable" / "TikTokSans[opsz,slnt,wdth,wght].ttf"
FONT_AXES = (36, 99, 400, 0)  # opsz, wdth, wght, slnt

CARD_X0, CARD_X1, CARD_TOP = 142, 939, 208
CARD_R = 42
SHADOW_BLUR, SHADOW_ALPHA = 14, 0.45
MAX_CARD_H = 700
HEADER_H = 172
AVATAR_D = 98
FONT_PX = 33
NAME_PX = 21
PAD_X, PAD_Y = 36, 19
LINE_GAP = 1.18
BUBBLE_MAX_W = 0.80
GAP_SAME, GAP_SWITCH = 8, 19
TOP_PAD, BOTTOM_PAD = 21, 14
SIDE_ME, SIDE_THEM = 25, 22

C_HEADER = (30, 30, 30, 255)
C_BODY = (0, 0, 0, 255)
C_ME = (10, 114, 246, 255)
C_THEM = (38, 38, 40, 255)
C_TEXT = (255, 255, 255, 255)
C_ICON = (10, 132, 255, 255)
C_AVATAR_TOP, C_AVATAR_BOT = (160, 160, 166), (118, 118, 124)


@dataclass
class Msg:
    who: str
    text: str
    screen: int
    header: str | None
    t: float = 0.0


def parse_script(path: Path) -> list[Msg]:
    msgs: list[Msg] = []
    screen, header, pending_new = -1, None, True
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("==="):
            screen, header, pending_new = screen + 1, line.lstrip("=").strip() or "Unknown", False
            continue
        if line.startswith("---"):
            screen, header, pending_new = screen + 1, None, False
            continue
        m = re.match(r"(?i)^(me|them|я|он|она)\s*:\s*(.+)$", line)
        if not m:
            raise SystemExit(f"Не понял строку сценария: {raw!r}")
        if pending_new:
            screen, pending_new = screen + 1, False
        who = "me" if m.group(1).lower() in ("me", "я") else "them"
        msgs.append(Msg(who, m.group(2).strip(), screen, header))
    if not msgs:
        raise SystemExit("В сценарии нет сообщений")
    return msgs


_fonts: dict[int, ImageFont.FreeTypeFont] = {}


def font(px: int) -> ImageFont.FreeTypeFont:
    if px not in _fonts:
        f = ImageFont.truetype(str(FONT_VAR), px)
        f.set_variation_by_axes(list(FONT_AXES))
        _fonts[px] = f
    return _fonts[px]


def text_w(text: str, px: int) -> float:
    w = 0.0
    for kind, chunk in A._tokenize_runs(text):
        w += px * 1.08 if kind == "emoji" else font(px).getlength(chunk)
    return w


def draw_text(img: Image.Image, x: float, y_top: float, text: str, px: int, fill=C_TEXT) -> None:
    d = ImageDraw.Draw(img)
    f = font(px)
    asc, _ = f.getmetrics()
    base = y_top + asc
    cx = x
    for kind, chunk in A._tokenize_runs(text):
        if kind == "emoji":
            e = A._apple_emoji_rgba(chunk, int(px * 1.0))
            if e is not None:
                img.alpha_composite(e, (int(round(cx + px * 0.04)), int(round(base - px * 0.86))))
            cx += px * 1.08
        else:
            d.text((cx, base), chunk, font=f, fill=fill, anchor="ls")
            cx += f.getlength(chunk)


def wrap(text: str, px: int, max_w: float) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and text_w(trial, px) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + ([cur] if cur else [])


def bubble_size(text: str, s: int) -> tuple[list[str], int, int]:
    px = FONT_PX * s
    max_text = (CARD_X1 - CARD_X0) * BUBBLE_MAX_W * s - 2 * PAD_X * s
    lines = wrap(text, px, max_text)
    lh = int(round(px * LINE_GAP))
    w = int(max(text_w(ln, px) for ln in lines) + 2 * PAD_X * s)
    h = int(lh * len(lines) + 2 * PAD_Y * s)
    return lines, w, h


def _bez(p0, c, p1, n=16):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t ** 2 * p1[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t ** 2 * p1[1])
            for t in (i / n for i in range(n + 1))]


def draw_tail(d: ImageDraw.ImageDraw, x_edge: float, y_bot: float, right: bool, color, s: int) -> None:
    sg = 1 if right else -1
    X = lambda dx: x_edge + sg * dx * s  # noqa: E731
    Y = lambda dy: y_bot + dy * s  # noqa: E731
    outer = _bez((X(0), Y(-30)), (X(1), Y(-4)), (X(13), Y(1)))
    inner = _bez((X(13), Y(1)), (X(1), Y(2)), (X(-16), Y(-6)))
    d.polygon(outer + inner + [(X(-16), Y(-30))], fill=color)


def draw_avatar(img: Image.Image, cx: float, cy: float, d_px: int) -> None:
    av = Image.new("RGBA", (d_px, d_px), (0, 0, 0, 0))
    g = ImageDraw.Draw(av)
    for y in range(d_px):
        t = y / max(1, d_px - 1)
        c = tuple(int(a + (b - a) * t) for a, b in zip(C_AVATAR_TOP, C_AVATAR_BOT)) + (255,)
        g.line([(0, y), (d_px, y)], fill=c)
    head = d_px * 0.19
    g.ellipse((d_px / 2 - head, d_px * 0.38 - head, d_px / 2 + head, d_px * 0.38 + head), fill=(255, 255, 255, 255))
    g.ellipse((d_px * 0.18, d_px * 0.66, d_px * 0.82, d_px * 1.12), fill=(255, 255, 255, 255))
    mask = Image.new("L", (d_px, d_px), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, d_px - 1, d_px - 1), fill=255)
    out = Image.new("RGBA", (d_px, d_px), (0, 0, 0, 0))
    out.paste(av, (0, 0), mask)
    img.alpha_composite(out, (int(cx - d_px / 2), int(cy - d_px / 2)))


def draw_header(img: Image.Image, top: int, name: str, s: int) -> None:
    d = ImageDraw.Draw(img)
    x0, x1 = CARD_X0 * s, CARD_X1 * s
    cy = top + 77 * s
    draw_avatar(img, (x0 + x1) / 2, cy, AVATAR_D * s)
    npx = NAME_PX * s
    nw = text_w(name, npx)
    chev = npx * 0.55
    nx = (x0 + x1) / 2 - (nw + chev) / 2
    ny = top + 136 * s
    draw_text(img, nx, ny, name, npx)
    gx, gy = nx + nw + npx * 0.25, ny + npx * 0.62
    d.line([(gx, gy - npx * 0.28), (gx + npx * 0.22, gy), (gx, gy + npx * 0.28)], fill=(140, 140, 146, 255), width=max(1, s))
    bx = x0 + 28 * s
    d.line([(bx + 21 * s, cy - 20 * s), (bx, cy), (bx + 21 * s, cy + 20 * s)], fill=C_ICON, width=6 * s, joint="curve")
    for px_, py_ in ((bx + 21 * s, cy - 20 * s), (bx, cy), (bx + 21 * s, cy + 20 * s)):
        d.ellipse((px_ - 3 * s, py_ - 3 * s, px_ + 3 * s, py_ + 3 * s), fill=C_ICON)
    vx1 = x1 - 48 * s
    vx0 = vx1 - 56 * s
    d.rounded_rectangle((vx0, cy - 16 * s, vx0 + 38 * s, cy + 16 * s), radius=6 * s, outline=C_ICON, width=5 * s)
    d.polygon([(vx0 + 41 * s, cy - 3 * s), (vx1, cy - 13 * s), (vx1, cy + 13 * s), (vx0 + 41 * s, cy + 3 * s)],
              outline=C_ICON, fill=None, width=5 * s)


def card_height(msgs: list[Msg], header: bool) -> int:
    h = (HEADER_H if header else 0) + TOP_PAD
    prev = None
    for m in msgs:
        _, _, bh = bubble_size(m.text, 1)
        if prev is not None:
            h += GAP_SAME if prev == m.who else GAP_SWITCH
        h += bh
        prev = m.who
    return h + BOTTOM_PAD


def render_card(msgs: list[Msg], header: str | None) -> Image.Image:
    s = SS
    full = Image.new("RGBA", (W * s, H * s), (0, 0, 0, 0))
    ch = card_height(msgs, header is not None) * s
    x0, x1, top = CARD_X0 * s, CARD_X1 * s, CARD_TOP * s
    card = Image.new("RGBA", (W * s, H * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((x0, top, x1, top + ch), radius=CARD_R * s, fill=C_BODY)
    y = top
    if header is not None:
        d.rounded_rectangle((x0, top, x1, top + HEADER_H * s), radius=CARD_R * s, fill=C_HEADER)
        d.rectangle((x0, top + HEADER_H * s - CARD_R * s, x1, top + HEADER_H * s), fill=C_HEADER)
        draw_header(card, top, header, s)
        y += HEADER_H * s
    y += TOP_PAD * s
    for i, m in enumerate(msgs):
        if i:
            y += (GAP_SAME if msgs[i - 1].who == m.who else GAP_SWITCH) * s
        lines, bw, bh = bubble_size(m.text, s)
        right = m.who == "me"
        bx1 = x1 - SIDE_ME * s if right else x0 + SIDE_THEM * s + bw
        bx0 = bx1 - bw
        color = C_ME if right else C_THEM
        if i == len(msgs) - 1 or msgs[i + 1].who != m.who:
            draw_tail(d, bx1 if right else bx0, y + bh, right, color, s)
        r = min(bh / 2, (FONT_PX * LINE_GAP + 2 * PAD_Y) * s / 2)
        d.rounded_rectangle((bx0, y, bx1, y + bh), radius=r, fill=color)
        ty = y + PAD_Y * s
        for ln in lines:
            draw_text(card, bx0 + PAD_X * s, ty, ln, FONT_PX * s)
            ty += round(FONT_PX * s * LINE_GAP)
        y += bh
    a = card.getchannel("A").point(lambda v: int(v * SHADOW_ALPHA))
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    shadow.putalpha(a.filter(ImageFilter.GaussianBlur(SHADOW_BLUR * s)))
    full.alpha_composite(shadow, (0, 4 * s))
    full.alpha_composite(card)
    return full.resize((W, H), Image.Resampling.LANCZOS)


def paginate(msgs: list[Msg]) -> list[list[Msg]]:
    screens: list[list[Msg]] = []
    for i, m in enumerate(msgs):
        if not screens or screens[-1][0].screen != m.screen:
            screens.append([m])
            continue
        cur = screens[-1]
        if card_height(cur + [m], cur[0].header is not None) > MAX_CARD_H:
            msgs[i] = Msg(m.who, m.text, m.screen, None, m.t)
            screens.append([msgs[i]])
        else:
            cur.append(m)
    return screens


def media_duration(path: Path) -> float:
    ffprobe = str(Path(A.find_ffmpeg()).with_name("ffprobe.exe"))
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return float(r.stdout.strip())


def _norm(word: str) -> str:
    return re.sub(r"[^a-z0-9']", "", word.lower().replace("’", "'"))


def asr_words(audio: Path) -> list[tuple[str, float, float]]:
    import numpy as np
    import torch
    from transformers import pipeline

    raw = subprocess.run([A.find_ffmpeg(), "-v", "error", "-i", str(audio), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, stdin=subprocess.DEVNULL).stdout
    wav = np.frombuffer(raw, np.float32)
    cuda = torch.cuda.is_available()
    asr = pipeline("automatic-speech-recognition", model="openai/whisper-small", device=0 if cuda else -1,
                   torch_dtype=torch.float16 if cuda else torch.float32)
    out = asr({"raw": wav, "sampling_rate": 16000}, chunk_length_s=30, batch_size=8,
              return_timestamps="word", generate_kwargs={"language": "en"})
    words = []
    for c in out["chunks"]:
        a, b = c["timestamp"]
        w = _norm(c["text"])
        if w and a is not None:
            words.append((w, float(a), float(b if b is not None else a)))
    return words


def align(msgs: list[Msg], words: list[tuple[str, float, float]], total: float) -> None:
    script, owner = [], []
    for i, m in enumerate(msgs):
        for w in m.text.split():
            n = _norm(w)
            if n:
                script.append(n)
                owner.append(i)
    sm = difflib.SequenceMatcher(None, script, [w for w, _, _ in words], autojunk=False)
    hit: dict[int, int] = {}
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            hit[a + k] = b + k
    starts: list[float | None] = []
    for i in range(len(msgs)):
        idx = [j for j, o in enumerate(owner) if o == i]
        t = None
        for pos, j in enumerate(idx):
            if j in hit:
                t = words[hit[j]][1] - 0.28 * pos
                break
        starts.append(t)
    known = [(i, t) for i, t in enumerate(starts) if t is not None]
    if not known:
        raise SystemExit("Не удалось сопоставить сценарий с озвучкой — проверьте текст или задайте --timings")
    for i, t in enumerate(starts):
        if t is None:
            prev = max((k for k in known if k[0] < i), default=(-1, 0.0), key=lambda k: k[0])
            nxt = min((k for k in known if k[0] > i), default=(len(msgs), total), key=lambda k: k[0])
            starts[i] = prev[1] + (nxt[1] - prev[1]) * (i - prev[0]) / (nxt[0] - prev[0])
    t_prev = -1.0
    for m, t in zip(msgs, starts):
        m.t = max(0.0, t - 0.05, t_prev + 0.25 if t_prev >= 0 else 0.0)
        t_prev = m.t


def pace(msgs: list[Msg]) -> float:
    t = 0.0
    for m in msgs:
        m.t = t
        t += 0.45 + 0.062 * len(m.text)
    return t + 1.0


def squeeze_pauses(a, sr: int, max_pause: float):
    """Паузы внутри реплики длиннее max_pause сжать до max_pause; края — до 20 мс."""
    import numpy as np

    hop = sr // 100
    n = len(a) // hop
    if n == 0:
        return a
    x = a[: n * hop].astype(np.float32).reshape(n, hop)
    db = 20 * np.log10(np.sqrt((x ** 2).mean(1)) / 32768 + 1e-9)
    loud = db > db.max() - 38
    idx = np.where(loud)[0]
    if not len(idx):
        return a
    first, last = idx[0], idx[-1]
    keep = np.zeros(n, bool)
    keep[max(0, first - 2): last + 3] = True
    lim = max(1, int(max_pause * 100))
    run = []
    for i in range(first, last + 1):
        if not loud[i]:
            run.append(i)
        else:
            if len(run) > lim:
                keep[run[lim // 2: len(run) - (lim - lim // 2)]] = False
            run = []
    return x[keep].reshape(-1).astype(np.int16)


def build_voice(files: list[Path], gap: float, cut_at: float | None, dest: Path,
                max_pause: float | None = None, tempo: float = 1.0) -> tuple[list[float], float]:
    """Склеить реплики с паузами в один wav; вернуть старты реплик и длину."""
    import wave

    import numpy as np

    sr = 44100
    parts = []
    for f in files:
        raw = subprocess.run([A.find_ffmpeg(), "-v", "error", "-i", str(f), "-ac", "1", "-ar", str(sr),
                              "-f", "s16le", "-"], capture_output=True, stdin=subprocess.DEVNULL).stdout
        parts.append(np.frombuffer(raw, np.int16))
    if cut_at is not None:
        n = int(cut_at * sr)
        last = parts[-1][:n].astype(np.float32)
        k = int(0.012 * sr)  # 12 мс, чтобы не щёлкало
        last[-k:] *= np.linspace(1, 0, k)
        parts[-1] = last.astype(np.int16)
    if max_pause is not None:
        parts = [squeeze_pauses(a, sr, max_pause) for a in parts]
    if abs(tempo - 1.0) > 1e-3:
        sped = []
        for a in parts:
            r = subprocess.run([A.find_ffmpeg(), "-v", "error", "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "-",
                                "-af", f"atempo={tempo}", "-f", "s16le", "-"], input=a.tobytes(), capture_output=True)
            sped.append(np.frombuffer(r.stdout, np.int16))
        parts = sped
    starts, chunks, t = [], [], 0.0
    pad = np.zeros(int(gap * sr), np.int16)
    for i, a in enumerate(parts):
        starts.append(t)
        chunks.append(a)
        t += len(a) / sr
        if i < len(parts) - 1:
            chunks.append(pad)
            t += gap
    audio = np.concatenate(chunks)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(audio.tobytes())
    return starts, len(audio) / sr


def mix_music(voice: Path, music: Path, total: float, rel_db: float, start: float | None, seed_from: Path) -> Path:
    """Музыка под голос: уровень относительно голоса, свой кусок трека на каждый ролик."""
    import random
    import wave

    import numpy as np

    sr = 44100

    def load(path: Path, ss: float = 0.0, t: float | None = None):
        cmd = [A.find_ffmpeg(), "-v", "error"]
        cmd += ["-stream_loop", "-1"] if t else []
        cmd += ["-ss", f"{ss:.3f}", "-i", str(path)]
        cmd += ["-t", f"{t:.3f}"] if t else []
        cmd += ["-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
        return np.frombuffer(subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL).stdout, np.float32)

    v = load(voice)
    mdur = media_duration(music)
    if start is None:
        start = random.Random(str(seed_from)).uniform(0, max(0.0, mdur - total - 1))
    m = load(music, start, total + 0.1)[: len(v)]
    m = np.pad(m, (0, len(v) - len(m)))
    rms = lambda x: float(np.sqrt(np.mean(x[np.abs(x) > 1e-4] ** 2))) if np.any(np.abs(x) > 1e-4) else 1e-9  # noqa: E731
    m *= (rms(v) * 10 ** (rel_db / 20)) / rms(m)
    fade = int(0.3 * sr)
    m[:fade] *= np.linspace(0, 1, fade)
    mix = np.clip(v + m, -1, 1)
    out = voice.with_name("voice_music.wav")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())
    print(f"музыка: {music.name} с {start:.1f} с, {rel_db:+.0f} дБ к голосу", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="iMessage text story over gameplay")
    ap.add_argument("--script", type=Path, required=True)
    ap.add_argument("--bg", type=Path)
    ap.add_argument("--bg-dir", type=Path, help="папка фонов: каждому ролику свой")
    ap.add_argument("-n", type=int, default=1, help="сколько роликов (с --bg-dir)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--audio", type=Path)
    ap.add_argument("--voice-dir", type=Path, help="реплики отдельными файлами по порядку")
    ap.add_argument("--gap", type=float, default=0.05, help="пауза между репликами, с")
    ap.add_argument("--max-pause", type=float, default=0.12, help="паузы внутри реплики не длиннее, с")
    ap.add_argument("--tempo", type=float, default=1.0, help="ускорение речи без смены тона")
    ap.add_argument("--music", type=Path, help="фоновая музыка под голосом")
    ap.add_argument("--music-db", type=float, default=-7.0, help="музыка тише голоса на столько дБ")
    ap.add_argument("--music-start", type=float, help="с какой секунды трека (по умолчанию — случайно)")
    ap.add_argument("--cut-at", type=float, help="обрыв последней реплики на этой секунде")
    ap.add_argument("--timings", type=Path, help="готовые времена сообщений (json из прошлого запуска)")
    ap.add_argument("--bg-start", type=float, default=0.0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    msgs = parse_script(args.script)
    if args.bg_dir:
        import random

        bgs = sorted(args.bg_dir.glob("*.mp4"))
        random.Random(args.seed).shuffle(bgs)
        args.out.mkdir(parents=True, exist_ok=True)
        base = [a for a in sys.argv[1:]]
        for k, bg in enumerate(bgs[: args.n], 1):
            dest = args.out / f"story_{k:03d}.mp4"
            cmd = [sys.executable, __file__] + _strip(base, ("--bg-dir", "-n", "--out", "--seed")) + [
                "--bg", str(bg), "--out", str(dest)]
            print(f"[{k}/{args.n}] фон {bg.name}", flush=True)
            r = subprocess.run(cmd)
            if r.returncode != 0:
                return r.returncode
        return 0
    if not args.bg:
        raise SystemExit("нужен --bg или --bg-dir")
    voice_tmp = None
    if args.voice_dir:
        files = sorted(args.voice_dir.glob("*.wav"))
        if len(files) != len(msgs):
            raise SystemExit(f"реплик {len(files)}, а сообщений в сценарии {len(msgs)}")
        voice_tmp = Path(tempfile.mkdtemp(prefix="voice_")) / "voice.wav"
        starts, total = build_voice(files, args.gap, args.cut_at, voice_tmp, args.max_pause, args.tempo)
        if args.music:
            voice_tmp = mix_music(voice_tmp, args.music, total, args.music_db, args.music_start, args.out)
        for m, t in zip(msgs, starts):
            m.t = t
        args.audio = voice_tmp
    if not args.voice_dir:
        total = media_duration(args.audio) if args.audio else 0.0
    if args.voice_dir:
        pass
    elif args.timings:
        ts = json.loads(args.timings.read_text(encoding="utf-8"))
        for m, row in zip(msgs, ts):
            m.t = float(row["t"])
        total = total or msgs[-1].t + 2.0
    elif args.audio:
        print("распознаю озвучку (Whisper)…", flush=True)
        align(msgs, asr_words(args.audio), total)
    else:
        total = pace(msgs)
    msgs[0].t = 0.0  # первое сообщение — сразу с первого кадра
    screens = paginate(msgs)
    print(f"сообщений {len(msgs)} · экранов {len(screens)} · {total:.1f} с", flush=True)

    work = Path(tempfile.mkdtemp(prefix="textstory_"))
    try:
        events: list[tuple[float, Path]] = []
        n = 0
        for scr in screens:
            hdr = scr[0].header
            for k in range(len(scr)):
                n += 1
                p = work / f"s{n:04d}.png"
                render_card(scr[: k + 1], hdr).save(p)
                events.append((scr[k].t, p))
        rows = []
        for i, (t, p) in enumerate(events):
            end = events[i + 1][0] if i + 1 < len(events) else total
            rows += [f"file '{p.as_posix()}'", f"duration {max(0.04, end - t):.3f}"]
        rows.append(f"file '{events[-1][1].as_posix()}'")
        lst = work / "overlay.txt"
        lst.write_text("\n".join(rows) + "\n", encoding="utf-8")

        args.out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [A.find_ffmpeg(), "-y", "-stream_loop", "-1", "-ss", f"{args.bg_start:.3f}", "-i", str(args.bg),
               "-f", "concat", "-safe", "0", "-i", str(lst)]
        if args.audio:
            cmd += ["-i", str(args.audio)]
        fc = (f"[0:v]{vf_scale_crop_fps_sdr(W, H, FPS)}[bg];[1:v]fps={FPS},format=rgba[ov];"
              f"[bg][ov]overlay=0:0:format=auto,format=yuv420p,{SET_SDR}[v]")
        cmd += ["-filter_complex", fc, "-map", "[v]"]
        cmd += ["-map", "2:a", "-c:a", "aac", "-b:a", "192k"] if args.audio else ["-an"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", *SDR_COLOR_ARGS,
                "-t", f"{total:.3f}", "-movflags", "+faststart", str(args.out)]
        r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise SystemExit(r.stderr[-1500:])
    finally:
        shutil.rmtree(work, ignore_errors=True)

    tpath = args.out.with_suffix(".timings.json")
    tpath.write_text(json.dumps([{"t": round(m.t, 2), "who": m.who, "text": m.text} for m in msgs],
                                indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"готово → {args.out} (тайминги: {tpath.name})")
    return 0


def _strip(argv: list[str], names: tuple[str, ...]) -> list[str]:
    """argv без опций names и их значений."""
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a in names:
            skip = True
            continue
        if any(a.startswith(n + "=") for n in names):
            continue
        out.append(a)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
