#!/usr/bin/env python3
"""
Drops3 мем-карусель, слайд 1 «just releasing music<<boring»: пул мем-картинок «скука» с Pinterest — короткие
запросы, как ищут люди, 2 страницы, сортировка по лайкам → лист для отбора глазами (без надписей берём потом сами).

  python harvest_drops3_memes.py      # → output/drops3_pool/meme/NNN_<pin>.jpg + manifest.json + _sheet.jpg
"""

from __future__ import annotations

import io
import json
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

OUT = ROOT / "output" / "drops3_pool" / "meme"
QUERIES = ["bored meme", "boring meme", "bored reaction meme", "so bored meme", "bored cat meme", "bored dog meme",
           "unimpressed meme", "sleepy meme"]
SHEET = 63


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    h = hv.PinterestHarvester()
    h.warm_session(force=False)
    seen: dict[str, dict] = {}
    for q in QUERIES:
        for o, m in search(h, q, pages=2):
            sig = str(o.get("image_signature") or m.image_url.rsplit("/", 1)[-1].split(".")[0])
            likes = sum(int(v) for v in (o.get("reaction_counts") or {}).values())
            if sig in seen:
                seen[sig]["likes"] = max(seen[sig]["likes"], likes)
                continue
            seen[sig] = {"pin_id": m.pin_id, "likes": likes, "query": q, "url": HP.url_736(m.image_url),
                         "title": (o.get("grid_title") or o.get("title") or "")[:60]}
        print(f"{q!r}: всего {len(seen)}", flush=True)
    rows = sorted(seen.values(), key=lambda r: -r["likes"])
    cli = httpx.Client(timeout=25, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com/"})

    def get(r):
        try:
            x = cli.get(r["url"])
            return ImageOps.exif_transpose(Image.open(io.BytesIO(x.content))).convert("RGB") if x.status_code == 200 else None
        except Exception:
            return None
    with ThreadPoolExecutor(8) as ex:
        ims = list(ex.map(get, rows))
    OUT.mkdir(parents=True, exist_ok=True)
    keep, fps = [], []
    for r, im in zip(rows, ims):
        if im is None or im.width < 400:
            continue
        fp = HP.dhash(im)
        if any(bin(fp ^ f).count("1") <= 8 for f in fps):
            continue
        fps.append(fp)
        keep.append((r, im))
    man = []
    for n, (r, im) in enumerate(keep, 1):
        name = f"{n:03d}_{r['pin_id'][:24]}.jpg"
        im.save(OUT / name, quality=92)
        man.append({**r, "file": name, "px": list(im.size)})
    (OUT / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    font = ImageFont.truetype("arial.ttf", 15)
    tw, th, cols = 220, 260, 9
    part = man[:SHEET]
    s = Image.new("RGB", (cols * tw, ((len(part) + cols - 1) // cols) * (th + 20)), (25, 25, 25))
    d = ImageDraw.Draw(s)
    for j, r in enumerate(part):
        x, y = (j % cols) * tw, (j // cols) * (th + 20)
        s.paste(ImageOps.contain(Image.open(OUT / r["file"]), (tw, th)), (x, y + 20))
        d.text((x + 3, y + 2), f"{r['file'][:3]} L{r['likes']}", fill=(255, 230, 80), font=font)
    s.save(OUT / "_sheet.jpg", quality=86)
    print(f"{len(rows)} пинов → {len(man)} картинок")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
