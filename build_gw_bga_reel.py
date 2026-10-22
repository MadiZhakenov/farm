#!/usr/bin/env python3
"""
Global Work, «BAD / GOOD / AMAZING» с размытыми логотипами + субтитры (реф Instagram reel DcBd6RBuhA7),
айди пока нет. 3 дубля креатора (BAD IMG_2926 → GOOD IMG_2930 → AMAZING IMG_2936) склеены подряд.
Как в рефе: сверху строка BAD · GOOD · AMAZING, под ней логотипы LinkedIn / Indeed / Global Work: уже
названные — чёткие с подписью, будущие — размыты (подпись тоже); на слово уровня логотип «проявляется».
Субтитры — моноширинный белый со свечением, по 1–3 слова, текст дословно из ТЗ, тайминг по речи.
Лицо в кадре выше, чем в рефе, поэтому шапка с логотипами — компактно над головой, субтитры — под подбородком.
Всё в безопасной зоне 9:16. Звук — голос креатора, −14 LUFS. iPhone HDR → SDR.

  python build_gw_bga_reel.py          # вариант 1: логотипы весь ролик
  python build_gw_bga_reel.py --v2     # вариант 2: окна 16:9 с записями сайтов
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_tiers_reels as T  # noqa: E402  (шрифт, свечение, иконки, огибающая, тонмаппинг)
from core.safe_zones import check_box  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF, W, H, FPS, TM = T.FF, T.W, T.H, T.FPS, T.TM
D = ROOT / "downloads" / "gw_bga"
SRC = D / "src"
OUT = ROOT / "output" / "gw_bga"
ID = "noid"
PLOGOS = ROOT / "downloads" / "gw_pyramid" / "logos"

# дословно из ТЗ
SCRIPT = [
    ("IMG_2926", "BAD", "Every job is on linkedin, along with 1,000 applicants in the first hour."),
    ("IMG_2930", "GOOD", "More jobs on Indeed, better filters — but you’re still searching and applying one by one"),
    ("IMG_2936", "AMAZING", "GlobalWork finds your best-match jobs with AI, tailors your resume, and applies for you."),
]
APPS = [("LINKEDIN", PLOGOS / "png_linkedin.png"), ("INDEED", PLOGOS / "gs_indeed.com.png"),
        ("GLOBAL WORK", PLOGOS / "gs_globalwork.ai.png")]
COLS = (270, 540, 810)
HEAD_TOP, HEAD_PX, ICON, LABEL_PX = 205, 44, 132, 25
SUB_TOP, SUB_PX = 1110, 66          # субтитры под подбородком (подбородок ≤ 1063 px во всех дублях)
REVEAL = 0.3                         # проявление логотипа, с
MAX_GAP, PAD_IN, PAD_OUT = 0.22, 0.06, 0.10   # паузы длиннее MAX_GAP вырезаются (джамп-кат)
TAIL, TAIL_LAST = 0.12, 0.35         # хвост после последнего слова дубля / всего ролика, с
ZOOM, ZOOM_Y = 1.12, 0.12            # крупность на чётных склейках; кроп снизу — голова не лезет к логотипам
# вариант 2 (как в рефе): после слова уровня вместо логотипов — окно 16:9 с записью сайта.
# Лицо в кадре высоко → видео креатора сдвигаем вниз на SHIFT (низ со столом уходит), полосу сверху
# заполняем размытым отражением верха кадра; субтитры — ниже подбородка.
SCREENS = [D / "screens" / "linkedin_169.mp4", D / "screens" / "indeed_169.mp4", D / "screens" / "globalwork_169.mp4"]
SCREEN_SKIP = [0.5, 0.5, 0.6]        # пропуск начала записи (стоит на месте), с
SHIFT, PANEL_W, PANEL_H, PANEL_TOP, PANEL_R = 260, 760, 428, 210, 22
SUB_TOP_V2 = 1445
SHIFT_V1 = 0                         # сдвиг видео вниз и в варианте 1 (если голова высоко — для других креаторов)


# ---------------- тайминги ----------------
def words_timed(clip: str) -> list[tuple[str, float, float]]:
    """Слова Whisper со сдвигом по огибающей: начало первого слова (уровня) и первого слова фразы —
    по отрезкам речи (у Whisper первое слово начинается с 0 и тянется на 2+ с)."""
    w = [(t, a, b) for t, a, b in json.loads((SRC / "words.json").read_text())[clip]]
    bs = T.bursts(T.envelope(SRC / f"{clip}.MOV"))
    tier_on = bs[0][0]
    phrase_on = next((a for a, _b in bs[1:] if a > bs[0][1] - 0.05), w[1][1])
    shift = phrase_on - w[1][1]
    out = [(w[0][0], tier_on, bs[0][1])] + [(t, a + shift, b + shift) for t, a, b in w[1:]]
    return out


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def align(script: str, spoken: list[tuple[str, float, float]]) -> list[tuple[str, float, float]]:
    """Слова ТЗ ↔ сказанные слова (difflib); несовпавшие куски — время делится пропорционально."""
    sw = script.split()
    sp = [x[0] for x in spoken]
    sm = difflib.SequenceMatcher(a=[norm(x) for x in sw], b=[norm(x) for x in sp], autojunk=False)
    out: list = [None] * len(sw)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out[i1 + k] = (sw[i1 + k], spoken[j1 + k][1], spoken[j1 + k][2])
        elif i2 > i1:
            a = spoken[j1][1] if j1 < len(spoken) else spoken[-1][2]
            b = spoken[j2 - 1][2] if j2 > j1 else a + 0.25 * (i2 - i1)
            step = (b - a) / (i2 - i1)
            for k in range(i2 - i1):
                out[i1 + k] = (sw[i1 + k], a + k * step, a + (k + 1) * step)
    return out


def chunks(words: list[tuple[str, float, float]], max_chars: int = 15) -> list[tuple[str, float, float]]:
    """По 1–3 слова (как в рефе): слово уровня (BAD/GOOD/AMAZING) — отдельно, разрыв после знаков препинания,
    одинокое короткое слово в конце фразы забирает себе последнее слово предыдущего куска."""
    words = [w for w in words if norm(w[0])]                       # тире и пр. — не слова
    out, cur = [[words[0]]], []
    for w in words[1:]:
        cand = " ".join(x[0] for x in cur + [w])
        if cur and (len(cand) > max_chars or len(cur) >= 3):
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[,.;:!?]$", w[0]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    for k in range(2, len(out)):
        if len(out[k]) == 1 and len(norm(out[k][0][0])) <= 4 and len(out[k - 1]) >= 3:
            out[k].insert(0, out[k - 1].pop())
    # кусок не заканчивается служебным словом («on», «your»…) — переносим его к следующему, если тот не раздуется
    weak = {"on", "in", "is", "a", "the", "with", "of", "for", "and", "to", "your", "you"}
    for k in range(1, len(out) - 1):
        last = out[k][-1][0]
        nxt = out[k + 1]
        if (len(out[k]) >= 3 and norm(last) in weak and not re.search(r"[,.;:!?]$", last)
                and len(nxt) <= 2 and len(" ".join(x[0] for x in [out[k][-1]] + nxt)) <= max_chars):
            nxt.insert(0, out[k].pop())
    res = []
    for k, c in enumerate(out):
        end = out[k + 1][0][1] if k + 1 < len(out) else c[-1][2] + 0.4
        res.append((" ".join(x[0] for x in c).upper().rstrip(".,;:!?"), c[0][1], end))
    return res


def motion_onset(clip: str, after: float) -> float:
    """Первый момент после `after`, когда в кадре резко растёт движение (тянется выключить камеру)."""
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{after:.3f}", "-i", str(SRC / f"{clip}.MOV"), "-vf",
                          "scale=90:160,fps=30", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, 160, 90).astype(np.int16)
    d = np.abs(np.diff(v, axis=0)).mean((1, 2))
    base = float(np.median(d[:6])) if len(d) >= 6 else 1.0
    hit = np.where(d > max(3.0, 3 * base))[0]
    return after + (hit[0] / 30 if len(hit) else len(d) / 30)


# ---------------- графика ----------------
def header_assets() -> dict:
    hf = T.mono(HEAD_PX)
    heads = [T.glow_text([w], hf) for w in ("BAD", "GOOD", "AMAZING")]
    icons, labels, blurred, blur_labels = [], [], [], []
    for name, path in APPS:
        ic = T.rounded(Image.open(path).convert("RGBA").resize((ICON, ICON), Image.Resampling.LANCZOS))
        lf = T.mono(LABEL_PX, "Bold")
        lab = T.glow_text([name], lf, 1.1)
        icons.append(ic)
        labels.append(lab)
        blurred.append(blur(ic, 9))
        blur_labels.append(blur(lab, 6))
    return {"heads": heads, "icons": icons, "labels": labels, "blurred": blurred, "blur_labels": blur_labels}


def blur(im: Image.Image, r: float) -> Image.Image:
    pad = int(r * 3)
    big = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    big.alpha_composite(im, (pad, pad))
    return big.filter(ImageFilter.GaussianBlur(r))


def paste_center(layer: Image.Image, im: Image.Image, cx: float, top: float, alpha: float = 1.0) -> None:
    if alpha < 1:
        im = im.copy()
        im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
    layer.alpha_composite(im, (int(cx - im.width / 2), int(top)))


def frame_layer(a: dict, t: float, reveal: list[float], sub: str | None, sub_top: int = SUB_TOP) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for j, cx in enumerate(COLS):
        paste_center(layer, a["heads"][j], cx, HEAD_TOP)
    icon_top = HEAD_TOP + max(h.height for h in a["heads"]) + 14
    for j, cx in enumerate(COLS):
        u = float(np.clip((t - reveal[j]) / REVEAL, 0, 1))
        bi, bl = a["blurred"][j], a["blur_labels"][j]
        paste_center(layer, bi, cx, icon_top - (bi.height - ICON) / 2, 1 - u)
        paste_center(layer, bl, cx, icon_top + ICON + 8 - (bl.height - a["labels"][j].height) / 2, 1 - u)
        if u > 0:
            s = 0.85 + 0.15 * u
            ic = a["icons"][j].resize((int(ICON * s), int(ICON * s)), Image.Resampling.BILINEAR)
            paste_center(layer, ic, cx, icon_top + (ICON - ic.height) / 2, u)
            paste_center(layer, a["labels"][j], cx, icon_top + ICON + 8, u)
    if sub:
        sf = T.mono(SUB_PX)
        paste_center(layer, T.glow_text(T.wrap(sub, sf, 760), sf), W / 2, sub_top)
    return layer


def panel_mask() -> Image.Image:
    m = Image.new("L", (PANEL_W, PANEL_H), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, PANEL_W - 1, PANEL_H - 1], radius=PANEL_R, fill=255)
    return m


def panel_layer(frame_rgb: bytes, u: float) -> Image.Image:
    """Окно с записью сайта: скруглённые углы, мягкая тень, появление (масштаб 0.92→1 + прозрачность) за 0.15 с."""
    pan = Image.frombuffer("RGB", (PANEL_W, PANEL_H), frame_rgb).convert("RGBA")
    pan.putalpha(PANEL_MASK)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh = Image.new("RGBA", (PANEL_W + 80, PANEL_H + 80), (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 120)), (40, 46), PANEL_MASK)
    sh = sh.filter(ImageFilter.GaussianBlur(16))
    s_ = 0.92 + 0.08 * u
    if s_ < 1:
        pan = pan.resize((int(PANEL_W * s_), int(PANEL_H * s_)), Image.Resampling.BILINEAR)
        sh = sh.resize((int(sh.width * s_), int(sh.height * s_)), Image.Resampling.BILINEAR)
    cy = PANEL_TOP + PANEL_H / 2
    paste_center(layer, sh, W / 2, cy - sh.height / 2, u)
    paste_center(layer, pan, W / 2, cy - pan.height / 2, u)
    return layer


def main() -> int:
    global PANEL_MASK
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2", action="store_true", help="вариант 2: окна 16:9 с записями сайтов, как в рефе")
    args = ap.parse_args()
    PANEL_MASK = panel_mask()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="gwbga_"))
    # джамп-каты как в рефе: внутри дубля оставляем только речь (паузы > MAX_GAP вырезаем),
    # на каждой склейке чередуем крупность кадра (100 % / ZOOM), чтобы стык не «прыгал»
    segs, subs, reveal, t_out, zoom_i = [], [], [], 0.0, 0
    takes = []                                               # (начало, конец) дубля в ролике
    for clip, tier, text in SCRIPT:
        take_start = t_out
        spoken = words_timed(clip)
        tier_on = spoken[0][1]
        # конец — по последнему отрезку речи (Whisper тянет последнее слово на 1+ с), но до того, как он
        # тянется к камере; последнему дублю — чуть больше «воздуха»
        speech_end = T.bursts(T.envelope(SRC / f"{clip}.MOV"))[-1][1]
        tail = TAIL_LAST if clip == SCRIPT[-1][0] else TAIL
        end = min(speech_end + tail, motion_onset(clip, speech_end) - 0.05, T.duration(SRC / f"{clip}.MOV"))
        keep = []
        for a0, b0 in T.bursts(T.envelope(SRC / f"{clip}.MOV")):
            a0, b0 = max(a0 - PAD_IN, tier_on - 0.15), min(b0 + PAD_OUT, end)
            if b0 <= tier_on - 0.15 or a0 >= end:
                continue
            if keep and a0 - keep[-1][1] < MAX_GAP:
                keep[-1] = (keep[-1][0], b0)
            else:
                keep.append((a0, b0))
        keep[-1] = (keep[-1][0], end)
        mapping = []                                         # (src_a, src_b, out_a)
        for a0, b0 in keep:
            mapping.append((a0, b0, t_out))
            segs.append((clip, a0, b0, ZOOM if zoom_i % 2 else 1.0))
            zoom_i += 1
            t_out += b0 - a0

        def to_out(t: float, m=mapping) -> float:
            for a0, b0, o in m:
                if t < a0:
                    return o
                if t <= b0:
                    return o + t - a0
            return m[-1][2] + m[-1][1] - m[-1][0]
        words = [(tier, spoken[0][1], spoken[0][2])] + align(text, spoken[1:])
        for txt, a, b in chunks(words):
            subs.append((txt, to_out(a), to_out(b)))
        reveal.append(to_out(tier_on))
        takes.append((take_start, t_out))
    for s in subs:
        print(f"  {s[1]:5.2f}–{s[2]:5.2f}  {s[0]}")
    print(f"склеек: {len(segs) - 1}, длина {t_out:.2f} с")
    # база: куски речи из 3 дублей подряд
    clips = list(dict.fromkeys(c for c, *_ in segs))
    inputs, parts = [], []
    for ci, clip in enumerate(clips):
        inputs += ["-i", str(SRC / f"{clip}.MOV")]
        mine = [n for n, sg in enumerate(segs) if sg[0] == clip]
        parts.append(f"[{ci}:v]{TM},split={len(mine)}" + "".join(f"[sv{n}]" for n in mine))
        parts.append(f"[{ci}:a:0]asplit={len(mine)}" + "".join(f"[sa{n}]" for n in mine))
    for n, (clip, a0, b0, z) in enumerate(segs):
        zf = "" if z == 1.0 else f",crop=iw/{z}:ih/{z}:(iw-iw/{z})/2:(ih-ih/{z})*{ZOOM_Y},scale={W}:{H}:flags=lanczos"
        if args.v2:
            parts.append(f"[sv{n}]trim=start={a0:.3f}:end={b0:.3f},setpts=PTS-STARTPTS{zf},setsar=1,split[m{n}][t{n}];"
                         f"[t{n}]crop=iw:{SHIFT}:0:0,vflip,gblur=sigma=28,eq=brightness=-0.05[tb{n}];"
                         f"[m{n}]crop=iw:ih-{SHIFT}:0:0[mb{n}];[tb{n}][mb{n}]vstack[v{n}]")
        elif SHIFT_V1:
            parts.append(f"[sv{n}]trim=start={a0:.3f}:end={b0:.3f},setpts=PTS-STARTPTS{zf},setsar=1,split[m{n}][t{n}];"
                         f"[t{n}]crop=iw:{SHIFT_V1}:0:0,vflip,gblur=sigma=28,eq=brightness=-0.05[tb{n}];"
                         f"[m{n}]crop=iw:ih-{SHIFT_V1}:0:0[mb{n}];[tb{n}][mb{n}]vstack[v{n}]")
        else:
            parts.append(f"[sv{n}]trim=start={a0:.3f}:end={b0:.3f},setpts=PTS-STARTPTS{zf},setsar=1[v{n}]")
        parts.append(f"[sa{n}]atrim=start={a0:.3f}:end={b0:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d=0.01,afade=t=out:st={max(0.0, b0 - a0 - 0.012):.3f}:d=0.012[a{n}]")
    cat = "".join(f"[v{n}][a{n}]" for n in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=1[v][a]"
    base = work / "base.mov"
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts) + ";" + cat, "-map", "[v]",
                    "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-c:a", "pcm_s16le", str(base)],
                   check=True)
    a = header_assets()
    sub_top = SUB_TOP_V2 if args.v2 else SUB_TOP
    full = frame_layer(a, 1e9, [0, 0, 0], max((s[0] for s in subs), key=len), sub_top)
    bad = check_box(W, H, full.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox())
    if bad:
        raise SystemExit(f"вне безопасной зоны: {bad}")
    dest = OUT / (f"bga_v2_{ID}.mp4" if args.v2 else f"bga_{ID}.mp4")
    # окно сайта: с конца слова уровня до конца дубля
    panel_on = [next(e for txt, a0, e in subs if txt == tier and tk[0] - 0.01 <= a0 < tk[1])
                for (_c, tier, _x), tk in zip(SCRIPT, takes)]
    if args.v2:
        print("окна сайтов:", [(round(p, 2), round(tk[1], 2)) for p, tk in zip(panel_on, takes)])
    screen_pipe, screen_k, last_screen = None, -1, None
    dec = subprocess.Popen([FF, "-v", "error", "-i", str(base), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                            "-i", "-", "-i", str(base), "-filter_complex",
                            f"[0:v]format=yuv420p,{SET_SDR}[v];[1:a]{T.audio_filter(base)}[a]", "-map", "[v]", "-map", "[a]",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "18", *SDR_COLOR_ARGS, "-c:a", "aac",
                            "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(dest)], stdin=subprocess.PIPE)
    f = 0
    while True:
        buf = dec.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        t = f / FPS
        sub = next((s[0] for s in subs if s[1] <= t < s[2]), None)
        frame = Image.frombuffer("RGB", (W, H), buf).convert("RGBA")
        k = max(i for i, tk in enumerate(takes) if tk[0] <= t + 1e-6)
        if args.v2 and t >= panel_on[k]:
            if screen_k != k:
                if screen_pipe:
                    screen_pipe.kill()
                screen_pipe = subprocess.Popen([FF, "-v", "error", "-ss", str(SCREEN_SKIP[k]), "-i", str(SCREENS[k]), "-vf",
                                                f"fps={FPS},scale={PANEL_W}:{PANEL_H}:flags=lanczos", "-f", "rawvideo",
                                                "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
                screen_k = k
            sb = screen_pipe.stdout.read(PANEL_W * PANEL_H * 3)
            last_screen = sb if len(sb) == PANEL_W * PANEL_H * 3 else last_screen
            frame.alpha_composite(panel_layer(last_screen, min(1.0, (t - panel_on[k]) / 0.15)))
            lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            if sub:
                sf = T.mono(SUB_PX)
                paste_center(lay, T.glow_text(T.wrap(sub, sf, 760), sf), W / 2, sub_top)
            frame.alpha_composite(lay)
        else:
            frame.alpha_composite(frame_layer(a, t, reveal, sub, sub_top))
        enc.stdin.write(frame.convert("RGB").tobytes())
        f += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()
    print(f"готово: {t_out:.2f} с → {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
