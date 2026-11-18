#!/usr/bin/env python3
"""en_neutral_100: переименовать en_NN_v1_noid.mp4 → en_NNN_1.mp4 (айди 1) и написать _youtube_meta.txt
(у каждого ролика свой тайтл по сюжету, описание из набора, хэштеги и теги в разном порядке).
  python make_en_neutral_meta.py"""

from __future__ import annotations

import random
from pathlib import Path

from neutral_en_texts import TITLES

D = Path(__file__).resolve().parent / "output" / "en_neutral_100"
DESCS = ["just me? 👇", "tell me i'm not the only one 👇", "be honest, how many times? 👇", "tag someone who does this 😂",
         "save this for later 📌", "which one are you? 👇", "this is literally me 🙂", "who else? 👇", "relatable or just me? 😭",
         "send this to your friend who does this 👀"]
HASH = ["#relatable", "#shorts", "#funny", "#reallife", "#mood", "#fyp"]
TAGS = ["relatable", "funny", "shorts", "real life", "mood", "everyday life", "relatable memes", "funny shorts", "so true", "daily life"]


def main() -> int:
    rng = random.Random(4101)
    for f in sorted(D.glob("en_*_v1_noid.mp4")):
        n = int(f.name.split("_")[1])
        f.rename(D / f"en_{n:03d}_1.mp4")
    out = []
    for f in sorted(D.glob("en_*_1.mp4")):
        n = int(f.name.split("_")[1])
        h, t = HASH[:], TAGS[:]
        rng.shuffle(h)
        rng.shuffle(t)
        title = TITLES[n - 1]
        out.append(f"===== {f.name} =====\nTITLE: {title}\n\nDESCRIPTION:\n{title} {rng.choice(DESCS)}\n\n"
                   f"{' '.join(h[:4])}\n\nTAGS: {', '.join(t[:7])}\n")
    (D / "_youtube_meta.txt").write_text("\n".join(out), encoding="utf-8")
    print(len(out), "→", D / "_youtube_meta.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
