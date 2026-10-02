#!/usr/bin/env python3
"""
Добавить заголовок сверху в готовые breakup-ролики: пересборка из тех же
клипов и звука (по manifest.json), без двойного пережатия готового mp4.
Высота заголовка чуть гуляет от ролика к ролику.

  python retitle_breakup.py --src output/breakup --out output/breakup_titled
  python retitle_breakup.py ... --limit 3          # тест
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

import assemble_ugc_reels as A
import assemble_ugc_reels_3part as M
from core import renderer as R

ROOT = Path(__file__).resolve().parent
TITLE = "day 2 after the breakup"
TITLE_SIZE = 60
TITLE_Y = (230, 400)  # верх заголовка: ниже интерфейса TikTok, выше основного текста


def title_layer(y: int) -> Image.Image:
    img = Image.new("RGBA", (M.W, M.H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = R._load_font(TITLE_SIZE)
    stroke = R.stroke_width_for(TITLE_SIZE)
    text = A.sanitize_overlay_text(R._normalize_text(TITLE))
    lw = int(round(A._line_width_mixed(text, font, TITLE_SIZE, stroke)))
    A._draw_line_mixed(img, draw, (M.W - lw) // 2, y, text, font, TITLE_SIZE, stroke)
    return img


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=ROOT / "output" / "breakup")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "breakup_titled")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    lib = {f.name: f for f, _ in M.SOUND_LIB.values()}
    for k in (1, 2):
        M.use_preset(f"breakup{k}")
        src, out = args.src / f"text{k}", args.out / f"text{k}"
        out.mkdir(parents=True, exist_ok=True)
        manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
        if args.limit:
            manifest = manifest[: args.limit]
        work_root = Path(tempfile.mkdtemp(prefix="retitle_"))
        try:
            for i, v in enumerate(manifest, 1):
                y = random.Random(v["file"]).randint(*TITLE_Y)
                v["title"], v["title_y"] = TITLE, y
                dest = out / v["file"]
                if not (dest.is_file() and dest.stat().st_size > 10_000):
                    png = work_root / "text.png"
                    M.render_text_png(M.HOOKS[v["hook"] - 1], png)
                    layer = Image.open(png)
                    layer.alpha_composite(title_layer(y))
                    layer.save(png)
                    clips = [d / name for d, name in zip(M.CLIP_DIRS, v["clips"])]
                    sound = {"file": lib[v["audio"]], "start": v["audio_start"]}
                    silent = work_root / "silent.mp4"
                    M.concat_three(clips, silent, work_root)
                    M.burn_single(silent, png, sound, dest)
                print(f"[text{k} {i}/{len(manifest)}] {v['file']} y={y}", flush=True)
        finally:
            shutil.rmtree(work_root, ignore_errors=True)
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"готово → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
