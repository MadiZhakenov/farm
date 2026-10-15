#!/usr/bin/env python3
"""
Global Work, «где искать удалёнку» (реф TikTok @lnwmediagroup 7571963544812490014), айди пока нет.
Исходник: downloads/gw_niche/src/IMG_2901.MOV (говорящая голова, 17 с). Монтаж как в рефе: короткие
белые подписи-тезисы (наш обычный TikTok Sans SemiBold, без обводки и тени) и названия сайтов рядом с пальцем на каждом
«this one». Тайминги — по словам Whisper (downloads/gw_niche/src/words.json). Всё внутри безопасной зоны
9:16 (docs/SAFE_ZONES.md); подписи — на футболке, т. к. над головой места нет.

  python build_gw_niche_reel.py --out output/gw_niche/gw_niche_v1.mp4
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import check_overlay  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
SRC = ROOT / "downloads" / "gw_niche" / "src" / "IMG_2901.MOV"
# наш обычный TikTok-шрифт (как во всех рилсах, core.renderer), только без обводки;
# кегль замерен по кадрам рефа: тезисы ≈ 60 px, сайты крупнее ≈ 64 px (на 1080)
FONT = ROOT / "fonts" / "TikTokSans-SemiBold.ttf"
W, H, PX_CAP, PX_SITE = 1080, 1920, 60, 64
LINE = 1.18           # шаг строк в долях кегля
# iPhone HLG (bt2020) → SDR bt709 тонмаппингом libplacebo; простая перемаркировка давала бледную картинку
TONEMAP = ("libplacebo=w=1080:h=1920:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:"
           "tonemapping=auto:format=yuv420p")

# (текст, начало, конец, центр x, центр y) — подписи-тезисы на футболке, сайты у пальца
CAPTIONS = [
    ("Quickest way to find\na remote job", 0.0, 4.86, 540, 1240),
    ("LinkedIn & Indeed", 4.86, 8.08, 540, 1240),
    ("Way too saturated", 8.08, 10.30, 540, 1240),
    ("Niche websites ->", 10.30, 12.96, 540, 1240),
    ("globalwork.ai", 13.05, 14.14, 345, 440),     # палец вверх-влево (кончик ≈ 340, 520)
    ("careerhound.io", 14.14, 15.52, 740, 240),    # палец вверх-вправо (кончик ≈ 770, 300)
    ("builtin.com", 15.52, 99.0, 770, 1370),       # палец вниз (кончик ≈ 780, 1240–1300)
]


def text_png(text: str, cx: int, cy: int) -> Image.Image:
    """Чисто белый текст как в рефе: без обводки и тени, строки по центру. Если блок вылезает за
    безопасную зону по x — сдвигаем внутрь."""
    from core.safe_zones import text_rect
    px = PX_CAP if " " in text else PX_SITE
    font = ImageFont.truetype(str(FONT), px)
    lines = text.split("\n")
    widths = [font.getlength(t) for t in lines]
    x0, _y0, x1, _y1 = text_rect(W, H)
    cx = min(max(cx, x0 + max(widths) / 2 + 4), x1 - max(widths) / 2 - 4)
    step = px * LINE
    top = cy - step * len(lines) / 2
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    for k, t in enumerate(lines):
        d.text((cx, top + (k + 0.5) * step), t, font=font, fill=(255, 255, 255, 255), anchor="mm")
    return canvas


# громкость: −14 LUFS (норма TikTok/Reels/Shorts), пик ≤ −1.5 dBTP; срез гула ниже 80 Гц; два прохода loudnorm
LOUD = "highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11"


def audio_filter() -> str:
    """Первый проход loudnorm меряет исходник, второй применяет точные значения."""
    import json
    import re
    log = subprocess.run([FF, "-hide_banner", "-i", str(SRC), "-map", "0:a:0", "-af", f"{LOUD}:print_format=json",
                          "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log).group(0))
    return (f"{LOUD}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
            f"measured_thresh={m['input_thresh']}:offset={m['target_offset']},aresample=48000")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "gw_niche" / "gw_niche_v4.mp4")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="gwniche_"))
    inputs, chain, last = ["-i", str(SRC)], [], f"[0:v]{TONEMAP},fps=30,setsar=1[v0]"
    chain.append(last)
    for k, (text, t0, t1, cx, cy) in enumerate(CAPTIONS, 1):
        png = work / f"c{k}.png"
        img = text_png(text, cx, cy)
        bad = check_overlay(img)
        if bad:
            raise SystemExit(f"«{text}» вне безопасной зоны: {bad}")
        img.save(png)
        inputs += ["-i", str(png)]
        chain.append(f"[v{k - 1}][{k}:v]overlay=0:0:enable='between(t,{t0},{t1})'[v{k}]")
    chain.append(f"[v{len(CAPTIONS)}]format=yuv420p,{SET_SDR}[v]")
    chain.append(f"[0:a:0]{audio_filter()}[a]")
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chain),
                    "-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "192k",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18", *SDR_COLOR_ARGS,
                    "-movflags", "+faststart", str(args.out)], check=True)
    print("готово →", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
