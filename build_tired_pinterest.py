#!/usr/bin/env python3
"""
Карусели «always tired this fall» из отобранных фото:
  слайд 1 — девушка в кровати (output/tired_pool/s1, Pinterest)
  слайд 2 — её жизнь: ресторан / кафе / дом (output/tired_pool/s2)
  слайд 3 — руки + планшет с Cozy Home (сгенерированные, --s3)
  слайд 4 — (позже)
Подбор по output/tired_pool/pairing.json: тон кожи девушки и ногти
сочетаются со сценой рук слайда 3. Текст и вёрстка — как build_tired_carousels.

  python build_tired_pinterest.py -n 2 --out output/tired_test
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps

import build_tired_carousels as T

ROOT = Path(__file__).resolve().parent
POOL = ROOT / "output" / "tired_pool"
S3_DEFAULT = Path(r"C:\Users\user\Downloads\3 slide")


def plan(n: int, pairing: dict, s1: Path, s2: Path, s3: Path, rng: random.Random) -> list[list[Path]]:
    girls = [g for g in pairing["s1"] if (s1 / g).is_file() and pairing["s1"][g]["slide3_groups"]]
    rest = [f.name for f in sorted(s2.glob("*.jpg")) if not f.name.startswith("_")]
    hands = [h for h in pairing["s3"] if (s3 / h).is_file()]
    use = [Counter(), Counter(), Counter()]
    seen: set[tuple[str, str, str]] = set()
    out = []
    for _ in range(n):
        for attempt in range(3000):
            slack = 0 if attempt < 1000 else 1
            low = min(use[0][g] for g in girls)
            g = rng.choice([x for x in girls if use[0][x] <= low + slack])
            ok = [h for h in hands if pairing["s3"][h] in pairing["s1"][g]["slide3_groups"]]
            low3 = min(use[2][h] for h in ok)
            h = rng.choice([x for x in ok if use[2][x] <= low3 + slack])
            low2 = min(use[1][r] for r in rest)
            r = rng.choice([x for x in rest if use[1][x] <= low2 + slack])
            if (g, r, h) not in seen:
                break
        seen.add((g, r, h))
        for k, x in enumerate((g, r, h)):
            use[k][x] += 1
        out.append([s1 / g, s2 / r, s3 / h])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=50)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--s3", type=Path, default=S3_DEFAULT)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    pairing = json.loads((POOL / "pairing.json").read_text(encoding="utf-8"))
    carousels = plan(args.n, pairing, POOL / "s1", POOL / "s2", args.s3, random.Random(args.seed))
    layers = [T.render_text(t) for t in T.SLIDES[:3]]
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, combo in enumerate(carousels, 1):
        d = args.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, (src, layer) in enumerate(zip(combo, layers), 1):
            bg = ImageOps.fit(Image.open(src).convert("RGB"), (T.W, T.H), Image.Resampling.LANCZOS)
            Image.alpha_composite(bg.convert("RGBA"), layer).convert("RGB").save(d / f"{k}.jpg", quality=95)
        manifest.append({
            "carousel": d.name,
            "frames": [p.name for p in combo],
            "skin": pairing["s1"][combo[0].name]["tone"],
            "hands_scene": pairing["s3"][combo[2].name],
        })
        print(f"{d.name}: {manifest[-1]['skin']} · {manifest[-1]['hands_scene']}")
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"готово: {len(manifest)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
