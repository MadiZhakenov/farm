#!/usr/bin/env python3
"""
Global Work, «THIS is hidden from you…» (реф TikTok @soph.pics 7670966231867936031), айди пока нет.
Как в рефе: реакция-хук (лицо, ~2–3.5 с) с белым текстом TikTok без обводки → запись экрана телефона
(главная globalwork.ai, плавный скролл, record_site_scroll.py). 8 реакций → 8 роликов.
Текст — дословно из ТЗ, только на хуке (как в рефе), ставится мимо лица (MediaPipe: лоб–подбородок по всему
клипу) и внутри безопасной зоны 9:16. Звук — трек рефа (музыка), −14 LUFS. iPhone HDR → SDR (libplacebo).

  python build_gw_hidden_reels.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import renderer as R  # noqa: E402
from core.safe_zones import check_overlay, text_rect  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
D = ROOT / "downloads" / "gw_hidden"
SRC, SCREEN, REF = D / "src", D / "screen" / "globalwork_scroll.mp4", D / "ref" / "ref_7670966231867936031.mp4"
OUT = ROOT / "output" / "gw_hidden"
ID = "noid"
W, H, FPS = 1080, 1920, 30
TM = ("libplacebo=w=1080:h=1920:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:"
      "tonemapping=auto:format=yuv420p,fps=30")
TEXT = "THIS is hidden from you not to find the job in 2026"   # дословно из ТЗ
PX = 64                    # реф ≈ 70 px (строка ≈ 900 px на 1080); 64 — две строки в ширину 800 безопасной зоны
SCREEN_MAX = 8.0           # длина записи экрана
GAP = 25                   # отступ текста от лица/бровей, px
FACES = D / "src" / "_faces2.json"


def probe_dur(p: Path) -> float:
    return float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)


BROW = [70, 63, 105, 66, 107, 336, 296, 334, 293, 300]


def face_band(clip: Path) -> dict:
    """По всем кадрам клипа (MediaPipe FaceLandmarker, 10 к/с), px из 1920: самый высокий верх лица (линия
    волос), самые высокие брови, самый низкий подбородок."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    w, h = 540, 960
    opt = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "face_landmarker.task")),
                                       running_mode=vision.RunningMode.VIDEO, num_faces=1)
    lm = vision.FaceLandmarker.create_from_options(opt)
    p = subprocess.Popen([FF, "-v", "error", "-i", str(clip), "-vf",
                          TM.replace("w=1080:h=1920", f"w={w}:h={h}").replace("fps=30", "fps=10"),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    top, brow, chin, k = [], [], [], 0
    while True:
        buf = p.stdout.read(w * h * 3)
        if len(buf) < w * h * 3:
            break
        r = lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                                         data=np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()), k * 100)
        if r.face_landmarks:
            L = r.face_landmarks[0]
            ys = [pt.y for pt in L]
            top.append(min(ys) * H)
            brow.append(min(L[i].y for i in BROW) * H)
            chin.append(max(ys) * H)
        k += 1
    lm.close()
    return {"top_min": int(min(top)), "brow_min": int(min(brow)), "chin_max": int(max(chin))}


def wrap(text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if cur and font.getlength(cand) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    return lines + [cur]


def text_png(face: dict, dest: Path) -> int:
    """Белый TikTok-текст без обводки и тени, как в рефе. Ставим над лицом (над линией волос); если места нет —
    над бровями, на лоб (как в рефе), глаза и брови открыты; иначе под подбородком."""
    x0, y0, x1, y1 = text_rect(W, H)
    font = R._load_font(PX)
    lines = wrap(TEXT, font, x1 - x0)
    adv = R.line_advance_for(PX)
    bh = adv * len(lines)
    top = None
    for limit in (face["top_min"], face["brow_min"]):
        if limit - GAP - bh >= y0:
            top = limit - GAP - bh
            break
    if top is None and face["chin_max"] + GAP + bh <= y1:
        top = face["chin_max"] + GAP
    if top is None:
        raise SystemExit("текст не помещается мимо глаз — нужен меньший кегль")
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    for k, t in enumerate(lines):
        d.text((W / 2, top + (k + 0.5) * adv), t, font=font, fill=(255, 255, 255, 255), anchor="mm")
    bad = check_overlay(canvas)
    if bad:
        raise SystemExit(f"текст вне безопасной зоны: {bad}")
    canvas.save(dest)
    return int(top)


def audio_filter(dur: float) -> str:
    loud = "loudnorm=I=-14:TP=-1.5:LRA=11"
    base = f"atrim=duration={dur:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={dur - 0.3:.3f}:d=0.3"
    log = subprocess.run([FF, "-hide_banner", "-i", str(REF), "-af", f"{base},{loud}:print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log).group(0))
    return (f"{base},{loud}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
            f"measured_thresh={m['input_thresh']}:offset={m['target_offset']},aresample=48000")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="gwhidden_"))
    clips = sorted(SRC.glob("IMG_*.MOV"))
    bands = json.loads(FACES.read_text()) if FACES.exists() else {}
    ref_len = probe_dur(REF)
    for n, clip in enumerate(clips, 1):
        if clip.name not in bands:
            bands[clip.name] = face_band(clip)
            FACES.write_text(json.dumps(bands, indent=1))
        hook = probe_dur(clip)
        screen = min(SCREEN_MAX, ref_len - hook - 0.05)
        total = hook + screen
        png = work / f"t{n}.png"
        top = text_png(bands[clip.name], png)
        fc = (f"[0:v]{TM},trim=duration={hook:.3f},setpts=PTS-STARTPTS[h0];[h0][2:v]overlay=0:0[h];"
              f"[1:v]fps=30,trim=duration={screen:.3f},setpts=PTS-STARTPTS,setsar=1[s];"
              f"[h][s]concat=n=2:v=1:a=0,format=yuv420p,{SET_SDR}[v];[3:a]{audio_filter(total)}[a]")
        dest = OUT / f"{n:02d}_{ID}.mp4"
        subprocess.run([FF, "-v", "error", "-y", "-i", str(clip), "-i", str(SCREEN), "-i", str(png), "-i", str(REF),
                        "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
                        "-crf", "18", *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}",
                        "-movflags", "+faststart", str(dest)], check=True)
        print(f"{dest.name}: реакция {clip.name} {hook:.2f} с + экран {screen:.2f} с, лицо {bands[clip.name]}, текст с y={top}")
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
