#!/usr/bin/env python3
"""
Референсы позы для обложек (Flow: «Image 2 — только поза и ракурс»): популярные зеркальные селфи с Pinterest,
сортировка по лайкам, без повторов → лист для отбора глазами. Запросы — короткие живые («mirror selfie / ootd»),
без листиклов (там AI-фермы).

  python harvest_pose_refs.py --out downloads/thanksgiving_outfits/pose --q "turtleneck trousers mirror selfie" ...
"""

from __future__ import annotations

import argparse
import io
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import harvest_carousel_pool as HP  # noqa: E402
from core import harvester as hv  # noqa: E402
from harvest_1390_brands import search  # noqa: E402

LISTICLE = ("ideas", "outfits for", "best ", " ways", "how to", "tips", "inspo for", "looks for")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--q", nargs="+", required=True)
    ap.add_argument("--keep", type=int, default=48)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    h = hv.PinterestHarvester()
    h.warm_session(force=False)
    seen: dict[str, dict] = {}
    for q in a.q:
        for o, m in search(h, q, pages=3):
            title = f"{o.get('title') or ''} {o.get('grid_title') or ''}".lower()
            if any(w in title for w in LISTICLE):
                continue
            sig = str(o.get("image_signature") or m.image_url.rsplit("/", 1)[-1].split(".")[0])
            likes = sum(int(v) for v in (o.get("reaction_counts") or {}).values())
            saves = int((o.get("aggregated_pin_data") or {}).get("aggregated_stats", {}).get("saves") or 0)
            score = saves or likes
            if sig not in seen or seen[sig]["score"] < score:
                seen[sig] = {"score": score, "url": HP.url_736(m.image_url)}
    rows = sorted(seen.values(), key=lambda r: -r["score"])[:a.keep * 2]
    cli = httpx.Client(timeout=25, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com/"})

    def get(r):
        try:
            x = cli.get(r["url"])
            return ImageOps.exif_transpose(Image.open(io.BytesIO(x.content))).convert("RGB") if x.status_code == 200 else None
        except Exception:
            return None
    with ThreadPoolExecutor(8) as ex:
        ims = list(ex.map(get, rows))
    a.out.mkdir(parents=True, exist_ok=True)
    keep, fps = [], []
    for r, im in zip(rows, ims):
        if im is None or min(im.size) < 400 or im.height < im.width * 1.15:      # только вертикальные
            continue
        fp = HP.dhash(im)
        if any(bin(fp ^ f).count("1") <= 8 for f in fps):
            continue
        fps.append(fp)
        keep.append((r, im))
        if len(keep) >= a.keep:
            break
    font = ImageFont.truetype("arial.ttf", 16)
    tw, th, cols = 200, 300, 8
    s = Image.new("RGB", (cols * tw, ((len(keep) + cols - 1) // cols) * (th + 20)), (25, 25, 25))
    d = ImageDraw.Draw(s)
    for n, (r, im) in enumerate(keep, 1):
        im.save(a.out / f"{n:03d}.jpg", quality=92)
        x, y = ((n - 1) % cols) * tw, ((n - 1) // cols) * (th + 20)
        s.paste(ImageOps.fit(im, (tw, th)), (x, y + 20))
        d.text((x + 3, y + 2), f"{n:03d} {r['score']}", fill=(255, 230, 80), font=font)
    s.save(a.out / "_sheet.jpg", quality=85)
    print(len(keep), "→", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
