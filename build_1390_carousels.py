#!/usr/bin/env python3
"""
1390 «clothes i find extremely swaggy in fall» — карусельная версия ролика (build_1390_reels): 9 слайдов 3:4
(1080×1440) из тех же фото output/1390_pick9 — обложка + 8 видов джинсов (2×2 пара одной вещи + плашка по центру).
Как в ТЗ: с cargo — подпись «i put all of these together in Inspoy…», на последнем слайде ещё карточка App Store.
Плашки и обложка — в пропорции видео (кегль от 1920), всё в безопасной рамке каруселей (x 180–900, y 6–78 %).

  python build_1390_carousels.py -n 4 --out output/carousels_1390_test
  python build_1390_carousels.py -n 300 --out output/carousels_1390 --flat output/1390_300_car
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1390_reels as R  # noqa: E402
import strip_jpeg_meta  # noqa: E402
from core.safe_zones import check_box, draw_overlay  # noqa: E402

K = 1920 / 1440                       # кегли ролика считались от H = 1920 — сохраняем их размер в пикселях
R.W, R.H = 1080, 1440
R.PLATE_CAP *= K
R.COVER_CAP *= K
R.CAPTION_CY = 0.22


def cover(src: Path, text: str):
    """Обложка как в ролике (R.cover), но блок текста прижат к рамке карусели x 180–900, а не 140–940."""
    im = R.cover_bg(src, "c").convert("RGBA")
    lay = R.cover_layout(src, "c")
    cap = round(R.COVER_CAP * R.H * lay.get("s", 1.0))
    lines = [R.bebas(ln, cap, R.COVER_COLOR) for ln in text.split(R.NL)]
    step = round(cap * R.COVER_STEP)
    blk = Image.new("RGBA", (max(l.width for l in lines), step * (len(lines) - 1) + lines[-1].height), (0, 0, 0, 0))
    for k, ln in enumerate(lines):
        blk.alpha_composite(ln, ((blk.width - ln.width) // 2, k * step))
    blk = R.add_shadow(R.add_shadow(blk, blur=2.5, opacity=0.8, offset=(0, 2), grow=1),
                       blur=18, opacity=0.55, offset=(0, 0), grow=10)
    pad = R.add_shadow(Image.new("RGBA", (4, 4)), blur=18, grow=10).width // 2 - 2     # поля тени — не текст
    cx = R.cover_layout(src, "c").get("cx") or (R.COVER_CX_R if src.stem.endswith("_R") else R.COVER_CX)
    x = min(max(180 - pad, round(cx * R.W - blk.width / 2)), 900 + pad - blk.width)
    y = round(lay.get("cy", R.COVER_CY) * R.H - blk.height / 2)
    im.alpha_composite(blk, (x, y))
    return im.convert("RGB"), [(x + pad, y + pad, x + blk.width - pad, y + blk.height - pad)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=4)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_1390.jpg")
    ap.add_argument("--seed", type=int, default=1390)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ps = R.pools()
    a.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, v in enumerate(R.plan(a.n, ps, random.Random(a.seed)), 1):
        R.JIT = random.Random(a.seed * 1000 + i)
        d = a.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        last = len(R.SLIDES) - 1
        for k, ((slot, text), photos) in enumerate(zip(R.SLIDES, v)):
            if k == 0:
                im, boxes = cover(photos[0], text)
            else:
                im, boxes = R.collage(photos[0], photos[1], text, k >= R.CAPTION_FROM, card=k == last)
            for b in boxes:
                if bad := check_box(R.W, R.H, b):
                    raise SystemExit(f"{i:03d} слайд {k + 1}: текст вне безопасной зоны {b} — {bad}")
            im.save(d / f"{k + 1}.jpg", quality=93)
            if i <= 2:
                q = draw_overlay(im)
                for b in boxes:
                    ImageDraw.Draw(q).rectangle(b, outline=(255, 200, 0), width=4)
                qd = ROOT / "output" / "_work" / "carousels_1390_qa" / a.out.name / d.name     # проверочные листы — не в выдачу
                qd.mkdir(parents=True, exist_ok=True)
                q.save(qd / f"_qa_{k + 1}.jpg", quality=80)
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d / f"{k + 1}.jpg", a.flat / f"sort_{k + 1}_{i}_1390.jpg")
        manifest.append({"carousel": d.name, "slides": [[p.name for p in t] for t in v]})
        print(f"  {d.name}", flush=True)
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    sys.argv = ["strip", str(a.out)] + ([str(a.flat)] if a.flat else [])
    strip_jpeg_meta.main()
    print(f"готово: {a.n} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
