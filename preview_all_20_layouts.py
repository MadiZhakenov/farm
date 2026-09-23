#!/usr/bin/env python3
"""
Render all editorial layouts to out/layouts_preview/layout_XX.jpg.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.collage_layouts import (  # noqa: E402
    DEFAULT_CAPTIONS,
    LAYOUT_NAMES,
    LAYOUT_REGISTRY,
    layout_key,
    render_layout,
)

OUT_DIR = ROOT / "out" / "layouts_preview"
ASSETS = ROOT / "assets"
DOWNLOAD = Path(r"E:\Users\Desktop\download")


def _load_four() -> list[Image.Image]:
    paths: list[Path] = []
    for cat in ("pillows", "brushes", "products", "hairlines"):
        for folder in (ASSETS / cat, DOWNLOAD / cat):
            if not folder.is_dir():
                continue
            files = sorted(
                p
                for p in folder.iterdir()
                if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            )
            if files:
                paths.append(files[0])
                break
    if len(paths) < 4:
        for folder in (DOWNLOAD, ASSETS, ROOT / "out" / "collages"):
            if not folder.is_dir():
                continue
            files = sorted(
                p
                for p in folder.rglob("*")
                if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
            )[:4]
            if len(files) >= 4:
                paths = files[:4]
                break
    if len(paths) < 4:
        raise FileNotFoundError("Need 4 images under assets/ or download/")

    imgs: list[Image.Image] = []
    for p in paths[:4]:
        with Image.open(p) as im:
            imgs.append(im.convert("RGB").copy())
        print(f"  {p}")
    return imgs


def main() -> int:
    print("Loading source images…")
    imgs = _load_four()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # wipe stale previews from removed layouts
    for old in OUT_DIR.glob("layout_*.jpg"):
        old.unlink()

    title = "the daily routine that saved my hair"
    for n in sorted(LAYOUT_REGISTRY):
        key = layout_key(n)
        name = LAYOUT_NAMES[n]
        print(f"[{n:02d}] {key} — {name}")
        canvas = render_layout(n, imgs, DEFAULT_CAPTIONS, title=title)
        out = OUT_DIR / f"{key}.jpg"
        canvas.convert("RGB").save(out, "JPEG", quality=92, optimize=True, subsampling=0)
        canvas.close()
        print(f"  → {out}")

    print(f"\nDone. {len(LAYOUT_REGISTRY)} previews in {OUT_DIR.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
