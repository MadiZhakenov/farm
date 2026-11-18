#!/usr/bin/env python3
"""
Раунд 3, гипотеза R3-5 «фото-карусель» (docs/REPOST_HYPOTHESES.md): тот же сюжет, что в озвучке, но фотоформатом
TikTok (photo mode) — слайды 3:4 1080×1440 из стоп-кадров ролика, история белым TikTok-текстом с обводкой
(Apple-эмодзи), по одной мысли на слайд. Стоп-кадры вырезаны из части кадра без вшитых подписей (кроп не сильнее
~1.7×, без апскейла видео). Когда будут ИИ-кадры R3-1, обложку можно заменить ими.

  python build_xmas_r3_carousel.py --out output/xmas_r3/R3-5_carousel
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402  (строка с Apple-эмодзи)
from core import renderer as R  # noqa: E402
from core.safe_zones import check_box  # noqa: E402

W, H = 1080, 1440
SRC = ROOT / "downloads" / "xmas_proj" / "src"
# зона без вшитой подписи (доли высоты исходника): (y_от, y_до); после времени until — весь кадр
CLEAN = {"v1": ((0.29, 1.0), None), "v2": ((0.0, 0.655), 9.3), "v3": ((0.30, 1.0), 10.25)}
# (секунда исходника, фокус по высоте внутри чистой зоны 0..1, текст, позиция текста top|bottom)
SLIDES = {
    "v1": ("DcNWKlfAbOo.mp4", [
        (0.9, 0.0, "my mom went to costco\nfor milk…", "bottom"),
        (3.9, 0.3, "and came back with\nTHIS 😭", "top"),
        (5.6, 0.4, "it's a projector", "top"),
        (7.4, 0.3, "now santa's sleigh flies\naround our living room\nevery night", "bottom"),
        (11.2, 0.3, "my dad already wants\na second one 💀", "bottom")]),
    "v2": ("DdGwGMEx-Uj.mp4", [
        (9.9, 0.5, "do NOT show this to anyone\nobsessed with christmas 😭", "bottom"),
        (4.0, 0.5, "it's this little tree…", "top"),
        (7.9, 0.5, "you plug it into the wall", "top"),
        (8.9, 0.5, "turn off the lights…", "top"),
        (11.0, 0.5, "and your whole ceiling\nturns into a snowstorm", "bottom"),
        (12.6, 0.5, "my mom bought three 💀", "bottom")]),
    "v3": ("DdZ5O2bR39c.mp4", [
        (1.5, 0.2, "last year my husband\ntried to fix the tree topper\nhimself…", "top"),
        (3.2, 0.3, "the tree won 💀", "top"),
        (4.0, 0.5, "this year we just\nplugged this in", "top"),
        (8.7, 0.3, "and the kids haven't left\nthe living room since", "top"),
        (10.2, 0.4, "best christmas decor\nwe ever bought 🎄", "top")]),
}
TXT_PX = 62
POS_Y = {"top": 0.17, "bottom": 0.70}


def frame(src: Path, t: float) -> Image.Image:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1",
                          "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
    from io import BytesIO
    return Image.open(BytesIO(raw)).convert("RGB")


def crop34(im: Image.Image, key: str, t: float, focus: float) -> Image.Image:
    (y0f, y1f), until = CLEAN[key]
    if until is not None and t >= until:
        y0f, y1f = 0.0, 1.0
    sw, sh = im.size
    zy0, zy1 = int(sh * y0f), int(sh * y1f)
    zh = zy1 - zy0
    ch = min(zh, int(sw * H / W))                  # 3:4 по высоте зоны
    cw = int(ch * W / H)
    y = zy0 + int((zh - ch) * focus)
    x = (sw - cw) // 2
    return im.crop((x, y, x + cw, y + ch)).resize((W, H), Image.Resampling.LANCZOS)


def draw_text(img: Image.Image, text: str, pos: str) -> None:
    lines = text.split("\n")
    px = TXT_PX
    while True:
        font, st = R._load_font(px), R.stroke_width_for(px)
        if max(A._line_width_mixed(ln, font, px, st) for ln in lines) <= 700 or px <= 40:
            break
        px -= 2
    adv = R.line_advance_for(px)
    th = adv * len(lines)
    top = int(H * POS_Y[pos] - th / 2)
    d = ImageDraw.Draw(img)
    y = top
    for ln in lines:
        lw = A._line_width_mixed(ln, font, px, st)
        A._draw_line_mixed(img, d, int((W - lw) / 2), y, ln, font, px, st)
        if bad := check_box(W, H, (int((W - lw) / 2), y, int((W + lw) / 2), y + adv)):
            raise SystemExit(f"текст вне безопасной зоны 3:4: {ln} {bad}")
        y += adv


def build(key: str, out: Path) -> Path:
    name, slides = SLIDES[key]
    src = SRC / name
    d = out / key
    d.mkdir(parents=True, exist_ok=True)
    for i, (t, focus, text, pos) in enumerate(slides, 1):
        im = crop34(frame(src, t), key, t, focus).convert("RGBA")
        draw_text(im, text, pos)
        im.convert("RGB").save(d / f"{i:02d}_noid.jpg", quality=95)
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "xmas_r3" / "R3-5_carousel")
    ap.add_argument("--only", default="v1,v2,v3")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for key in a.only.split(","):
        print("  ", build(key, a.out), flush=True)
    subprocess.run([sys.executable, str(ROOT / "strip_jpeg_meta.py"), str(a.out)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
