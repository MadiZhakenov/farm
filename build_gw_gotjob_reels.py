#!/usr/bin/env python3
"""
Global Work «I got the job» (ID пока нет): 3 ролика — по одному на каждый дубль креатора (downloads/gw_gotjob/src).
Реф TikTok @chloechedester 7684121698836303118: селфи, эмоционально говорит в камеру, под голосом тихо играет
«Jacob and the Stone SLOWED» (с начала трека, ~7 дБ ниже голоса), сверху маленький белый жирный текст на груди.

  — паузы вырезаем (джамп-каты), на склейках чередуем лёгкий наезд 100 % / 110 % (лицо остаётся на месте);
  — начало/конец — по речи, без включения и выключения камеры;
  — текст поверх всего ролика дословно из ТЗ: «i got the job on global work ai», белый, без обводки, TikTok Sans Bold,
    на груди под лицом, внутри безопасной зоны 9:16 (docs/SAFE_ZONES.md);
  — звук: голос (−16 LUFS) + трек рефа с 0 тише голоса на ~9 дБ, итог −14 LUFS; iPhone HLG → SDR.

  python build_gw_gotjob_reels.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import check_overlay  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
D = ROOT / "downloads" / "gw_gotjob"
SRC, MUSIC = D / "src", D / "ref" / "music.mp3"
OUT = ROOT / "output" / "gw_gotjob"
TAKES = ["IMG_2937", "IMG_2938", "IMG_2939"]
ID = "noid"
W, H, FPS = 1080, 1920, 30
TM = ("libplacebo=w=1080:h=1920:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:"
      "tonemapping=auto:format=yuv420p")
TEXT = "i got the job on global work ai"          # дословно из ТЗ
FONT = ROOT / "fonts" / "TikTokSans-Bold.ttf"
TEXT_PX, TEXT_CY = 46, 1512                       # на груди, низ блока ≈ 1534 (граница безопасной зоны 1540)
GAP, PRE, POST = 0.35, 0.08, 0.14                 # паузы длиннее GAP вырезаем; запас до/после речи
ZOOM, ZOOM_CY = 1.10, 1450                        # наезд на нечётных кусках — от точки под подбородком:
                                                  # лицо при наезде уходит вверх, а не на текст
CHIN_GAP = 14                                     # подбородок не ниже верха текста минус запас
VOICE_I, MUSIC_I, FINAL_I = -16.0, -25.0, -14.0


def chin_shift(clip: str, text_top: int) -> int:
    """На сколько поднять весь кадр, чтобы самый низкий подбородок дубля (с учётом наезда) был над текстом.
    Лица — MediaPipe по исходнику 10 к/с (src/_faces.json: время, лоб, подбородок, оценка макушки)."""
    rows = json.loads((SRC / "_faces.json").read_text())[clip]
    chin = max(max(c, ZOOM_CY + (c - ZOOM_CY) * ZOOM) for _t, _top, c, _hair in rows)
    sh = max(0, int(np.ceil(chin - (text_top - CHIN_GAP))))
    return sh + sh % 2


def text_png(dest: Path) -> list[int]:
    font = ImageFont.truetype(str(FONT), TEXT_PX)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((W / 2, TEXT_CY), TEXT, font=font, fill=(255, 255, 255, 255), anchor="mm")
    bad = check_overlay(img)
    if bad:
        raise SystemExit(f"текст вне безопасной зоны: {bad}")
    img.save(dest)
    return list(img.getbbox())


def speech_bursts(path: Path) -> list[tuple[float, float]]:
    """Речь по уровню над шумом комнаты (полоса 200–4000 Гц, гистерезис +18/+12 дБ над 10-м перцентилем).
    Порог от максимума (T.bursts) тут не годится: громкие восклицания «съедают» тихие эмоциональные фразы."""
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-af",
                          "highpass=f=200,lowpass=f=4000", "-f", "f32le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.float32)
    hop = 160
    e = np.array([np.sqrt(np.mean(a[i:i + hop] ** 2)) + 1e-7 for i in range(0, len(a) - hop, hop)])
    db = 20 * np.log10(np.convolve(e, np.ones(5) / 5, mode="same"))
    floor = float(np.percentile(db, 10))
    out, on, st = [], False, 0
    for i, v in enumerate(db):
        if not on and v > floor + 18:
            on, st = True, i
        elif on and v < floor + 12:
            on = False
            if i - st >= 8:
                out.append((st / 100, i / 100))
    if on:
        out.append((st / 100, len(db) / 100))
    return out


def segments(clip: str) -> list[tuple[float, float]]:
    """Куски с речью: отрезки речи, паузы короче GAP оставляем, длиннее — вырезаем."""
    path = SRC / f"{clip}.MOV"
    bs = speech_bursts(path)
    dur = float(subprocess.run([FF.replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error", "-show_entries",
                                "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout)
    segs: list[list[float]] = []
    for a, b in bs:
        a, b = max(0.0, a - PRE), min(dur, b + POST)
        if segs and a - segs[-1][1] < GAP:
            segs[-1][1] = b
        else:
            segs.append([a, b])
    return [(round(a * FPS) / FPS, round(b * FPS) / FPS) for a, b in segs if b - a >= 0.25]


def loudnorm(src: Path, dest: Path, target: float, extra: str = "") -> None:
    """Двухпроходная нормализация громкости."""
    flt = f"loudnorm=I={target}:TP=-1.5:LRA=11"
    log = subprocess.run([FF, "-hide_banner", "-i", str(src), "-af", (extra + "," if extra else "") + flt + ":print_format=json",
                          "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log).group(0))
    flt2 = (f"{flt}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
            f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-af", (extra + "," if extra else "") + flt2 + ",aresample=48000",
                    "-c:a", "pcm_s16le", str(dest)], check=True)


def build(clip: str, n: int, png: Path, work: Path, text_top: int) -> dict:
    segs = segments(clip)
    shift = chin_shift(clip, text_top)
    src = SRC / f"{clip}.MOV"
    k = len(segs)
    zw, zh = round(W * ZOOM / 2) * 2, round(H * ZOOM / 2) * 2
    zy = int(ZOOM_CY * ZOOM - ZOOM_CY)                       # точка ZOOM_CY остаётся на месте
    vf = [f"[0:v]{TM},fps={FPS},split={k}" + "".join(f"[s{i}]" for i in range(k))]
    af = [f"[0:a:0]asplit={k}" + "".join(f"[t{i}]" for i in range(k))]
    for i, (a, b) in enumerate(segs):
        z = f",scale={zw}:{zh},crop={W}:{H}:{(zw - W) // 2}:{zy}" if i % 2 else ""
        vf.append(f"[s{i}]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS{z},setsar=1[v{i}]")
        af.append(f"[t{i}]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,"
                  f"afade=t=in:d=0.01,afade=t=out:st={max(0, b - a - 0.012):.3f}:d=0.012[a{i}]")
    total = sum(b - a for a, b in segs)
    fc = ";".join(vf + af) + ";" + "".join(f"[v{i}][a{i}]" for i in range(k)) + f"concat=n={k}:v=1:a=1[cv][ca]"
    if shift:                                            # кадр выше, снизу — размытое отражение низа (футболка)
        fc += (f";[cv]split[cm][cb];[cm]crop={W}:{H - shift}:0:{shift}[ct];[cb]crop={W}:{shift}:0:{H - shift},"
               f"vflip,gblur=sigma=18[cbb];[ct][cbb]vstack[cv2]")
    else:
        fc += ";[cv]null[cv2]"
    fc += f";[cv2][1:v]overlay=0:0,format=yuv420p,{SET_SDR}[v]"
    raw = work / f"{clip}_raw.mp4"
    voice = work / f"{clip}_voice.wav"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-i", str(png), "-filter_complex", fc, "-map", "[v]",
                    "-map", "[ca]", "-c:v", "libx264", "-preset", "medium", "-crf", "18", *SDR_COLOR_ARGS,
                    "-c:a", "pcm_s16le", str(raw)], check=True)
    loudnorm(raw, voice, VOICE_I, "highpass=f=80")
    music = work / f"{clip}_music.wav"
    tmp = work / f"{clip}_music_raw.wav"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(MUSIC), "-t", f"{total:.3f}", "-af",
                    f"afade=t=out:st={max(0, total - 0.6):.3f}:d=0.6", str(tmp)], check=True)
    loudnorm(tmp, music, MUSIC_I)
    mix = work / f"{clip}_mix.wav"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(voice), "-i", str(music), "-filter_complex",
                    "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[m]", "-map", "[m]", str(mix)], check=True)
    final_a = work / f"{clip}_final.wav"
    loudnorm(mix, final_a, FINAL_I)
    dest = OUT / f"gotjob_{n}_{ID}.mp4"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(raw), "-i", str(final_a), "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(dest)],
                   check=True)
    return {"file": dest.name, "take": clip, "segments": [[round(a, 2), round(b, 2)] for a, b in segs],
            "duration": round(total, 2), "cuts": k - 1, "shift_up": shift}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="gotjob_"))
    png = work / "text.png"
    box = text_png(png)
    print("текст:", box)
    rep = []
    for n, clip in enumerate(TAKES, 1):
        r = build(clip, n, png, work, box[1])
        rep.append(r)
        print(f"{r['file']}: {clip}, {r['duration']} с, склеек {r['cuts']}, кадр выше на {r['shift_up']} px", flush=True)
    (OUT / "manifest.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
