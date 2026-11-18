#!/usr/bin/env python3
"""Тайтлы / описания / хэштеги / теги для ko_neutral_50 и br_neutral_50 (формат как de_neutral_50/_youtube_meta.txt):
у каждого ролика свой тайтл (5 на историю) и описание, хэштеги и теги в разном порядке.
  python make_neutral_lang_meta.py"""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

from neutral_lang_meta_texts import KO, PT  # noqa: E402  (тайтлы/описания «жиза»)

from neutral_de_texts import META as DE  # noqa: E402

TARGETS = [(ROOT / "output" / "ko_neutral_50", "ko", KO), (ROOT / "output" / "br_neutral_50", "br", PT),
           (ROOT / "output" / "de_neutral_120", "de", DE)]


def main() -> int:
    for d, prefix, meta in TARGETS:
        if len(sys.argv) > 1 and prefix not in sys.argv[1:]:
            continue
        rng = random.Random(1351)
        files = sorted(d.glob(f"{prefix}_*_v*_noid.mp4"))
        out = []
        for f in files:
            n, k = int(f.name.split("_")[1]), int(f.name.split("_v")[1].split("_")[0])
            titles, descs, hashtags, tags = meta[n]
            h, t = hashtags[:], tags[:]
            rng.shuffle(h)
            rng.shuffle(t)
            out.append(f"===== {f.name} =====\nTITLE: {titles[k - 1]}\n\nDESCRIPTION:\n{descs[(k + n) % len(descs)]}\n\n"
                       f"{' '.join(h)}\n\nTAGS: {', '.join(t)}\n")
        (d / "_youtube_meta.txt").write_text("\n".join(out), encoding="utf-8")
        print(len(out), "→", d / "_youtube_meta.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
