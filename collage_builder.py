#!/usr/bin/env python3
"""
Clean Girl Scrapbook collage — asymmetric Lemon8 / Pinterest moodboard.

Compositor: core.scrapbook_builder
Prompts:    data/nano_banana_prompts_hair_protocol.json
Refs:       python fetch_collage_refs.py  → data/collage_references/

Usage:
  python collage_builder.py
  python collage_builder.py img_silk.jpg img_scalp.jpg img_gummies.jpg img_mirror.jpg
  python collage_builder.py --dir E:\\Users\\Desktop\\download
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from core.scrapbook_builder import (  # noqa: E402
    SLOT_HINTS,
    build_scrapbook,
)

DEFAULT_SRC = Path(r"E:\Users\Desktop\download")
OUT_PATH = ROOT / "out" / "collages" / "collage_hair_protocol.jpg"
PROMPTS_PATH = ROOT / "data" / "nano_banana_prompts_hair_protocol.json"
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _list_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
    ]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def auto_pick_images(folder: Path) -> list[Path]:
    """Map 4 images → [silk, scalp, gummies, hero_mirror]."""
    files = _list_images(folder)
    if len(files) < 4:
        raise FileNotFoundError(
            f"Need 4 images in {folder}, found {len(files)}. "
            "Pass paths: silk scalp gummies mirror"
        )

    slots: list[Path | None] = [None, None, None, None]
    remaining = list(files)

    for slot, hints in SLOT_HINTS:
        for path in remaining:
            name = path.stem.lower()
            if any(h in name for h in hints):
                slots[slot] = path
                remaining.remove(path)
                break

    for i in range(4):
        if slots[i] is None and remaining:
            slots[i] = remaining.pop(0)

    if any(s is None for s in slots):
        raise FileNotFoundError(f"Could not resolve 4 images from {folder}")

    return [s for s in slots if s is not None]  # type: ignore[misc]


def build_collage(image_paths: list[Path], out_path: Path = OUT_PATH) -> Path:
    if len(image_paths) != 4:
        raise ValueError(f"Expected exactly 4 images, got {len(image_paths)}")

    t0 = time.perf_counter()
    imgs: list[Image.Image] = []
    for p in image_paths:
        with Image.open(p) as im:
            imgs.append(im.convert("RGB").copy())

    canvas = build_scrapbook(imgs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(
        out_path, "JPEG", quality=95, optimize=True, subsampling=0
    )

    elapsed = time.perf_counter() - t0
    print(f"Built in {elapsed:.2f}s")
    print(f"Saved -> {out_path.resolve()}")
    labels = ("silk", "scalp", "gummies", "hero")
    for lab, p in zip(labels, image_paths):
        print(f"  [{lab}] {p.name}")
    return out_path


def print_prompts() -> None:
    if not PROMPTS_PATH.is_file():
        print(f"(no prompts file at {PROMPTS_PATH})")
        return
    data = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    print("\nNano Banana prompts (Clean Girl):")
    for block in data.get("blocks", []):
        print(f"  #{block['id']} [{block['role']}]")
        print(f"     {block['prompt']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build asymmetric Clean Girl scrapbook collage (1080x1440)."
    )
    p.add_argument(
        "images",
        nargs="*",
        type=Path,
        help="4 paths: silk, scalp, gummies, mirror-hero",
    )
    p.add_argument("--dir", type=Path, default=DEFAULT_SRC)
    p.add_argument("-o", "--output", type=Path, default=OUT_PATH)
    p.add_argument(
        "--show-prompts",
        action="store_true",
        help="Print Nano Banana Clean Girl prompts and exit",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.show_prompts:
        print_prompts()
        return 0

    if len(args.images) == 4:
        paths = [p.resolve() for p in args.images]
        for p in paths:
            if not p.is_file():
                print(f"ERROR: file not found: {p}", file=sys.stderr)
                return 1
    elif len(args.images) == 0:
        try:
            paths = auto_pick_images(args.dir)
            print(f"Auto-picked from {args.dir}:")
            for lab, p in zip(("silk", "scalp", "gummies", "hero"), paths):
                print(f"  [{lab}] {p.name}")
        except FileNotFoundError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
    else:
        print("ERROR: pass exactly 4 images, or none to auto-pick.", file=sys.stderr)
        return 1

    build_collage(paths, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
