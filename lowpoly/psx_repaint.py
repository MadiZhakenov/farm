"""Repaint a Characters_psx atlas ("it's just a model with a picture on it, so we can repaint it" — Mr omi).
  python lowpoly/psx_repaint.py OUT.png [--base Character_06] [--pants black] [--long-sleeves red]
All male characters of the pack share one UV layout, so other atlases give the masks:
  pants  = denim pixels of Character_07 (jeans),
  sleeves = shirt pixels of Character_05 (long-sleeve shirt) that are bare skin on the base character.
Shading (folds, seams) is kept from the source pixels' luminance.
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

FARM = Path(__file__).resolve().parent.parent
TEX = FARM / "downloads/lowpoly_ref/assets/psx/characters_psx/source/Characters_psx/Characters_psx/Textures"


def load(name):
    return np.asarray(Image.open(TEX / f"{name}.png").convert("RGB")).astype(np.float32) / 255


def lum(a):
    return a @ np.array([0.299, 0.587, 0.114], np.float32)


def grow(mask, px=2):
    im = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * px + 1))
    return np.asarray(im) > 127


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--base", default="Character_06")
    ap.add_argument("--pants", default="0.09,0.09,0.10")
    ap.add_argument("--long-sleeves", default="from-torso")
    a = ap.parse_args()
    base = load(a.base)
    jeans, shirt = load("Character_07"), load("Character_05")
    out = base.copy()
    # pants: denim in the jeans atlas
    r, g, b = jeans[..., 0], jeans[..., 1], jeans[..., 2]
    pants = grow((b > r + 0.06) & (b >= g) & (lum(jeans) > 0.08), 2)
    L = lum(base)
    Ln = L / max(1e-3, float(np.median(L[pants])))
    col = np.array([float(v) for v in a.pants.split(",")], np.float32)
    out[pants] = np.clip(col[None, :] * (0.55 + 0.45 * Ln[pants, None]), 0, 1)
    # long sleeves: where the long-sleeve atlas has shirt and the base shows skin
    sr, sg, sb = shirt[..., 0], shirt[..., 1], shirt[..., 2]
    shirt_px = (sb > sr + 0.04) & (lum(shirt) > 0.45)
    br, bg_, bb = base[..., 0], base[..., 1], base[..., 2]
    skin = (br > bg_ + 0.04) & (bg_ > bb) & (br > 0.45) & (br - bb < 0.45)
    sleeve = grow(shirt_px & skin, 2) & ~pants
    if a.long_sleeves == "from-torso":
        red = (br > 0.45) & (bg_ < 0.25) & (bb < 0.25)
        tcol = np.median(base[red], axis=0) if red.any() else np.array([0.8, 0.1, 0.1], np.float32)
    else:
        tcol = np.array([float(v) for v in a.long_sleeves.split(",")], np.float32)
    Ls = lum(shirt)
    Lsn = Ls / max(1e-3, float(np.median(Ls[sleeve]))) if sleeve.any() else Ls
    out[sleeve] = np.clip(tcol[None, :] * (0.6 + 0.4 * Lsn[sleeve, None]), 0, 1)
    Image.fromarray((out * 255).astype(np.uint8)).save(a.out)
    print("pants px", int(pants.sum()), "sleeve px", int(sleeve.sum()), "->", a.out)


if __name__ == "__main__":
    main()
