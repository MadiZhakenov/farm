#!/usr/bin/env python3
"""
Drops beats — мемы для карточки комментария (по одному «настроению» на ролик): короткие запросы Pinterest,
сортировка по лайкам → лист для отбора глазами. Животные / нейтральные мемы (без реальных людей и чужих
персонажей — для рекламы клиента).

  python harvest_drops_beats_memes.py      # → downloads/drops_beats/memes/<настроение>/NNN.jpg + _sheet.jpg
"""

from __future__ import annotations

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

OUT = ROOT / "downloads" / "drops_beats" / "memes"
Q = {
    "chill": ["vibing cat meme", "chill cat meme", "sleepy cat meme"],               # 1 lofi — «someone sent me this beat 👀»
    "challenge": ["determined cat meme", "challenge accepted cat", "serious cat meme"],   # 2 trap — challenge accepted
    "crying": ["crying cat meme", "sad cat meme"],                                    # 3 sad piano — crying cat
    "sweating": ["sweating cat meme", "nervous cat meme", "stressed cat meme"],       # 4 funk — sweating
    "shocked": ["shocked cat meme", "surprised cat meme", "shocked dog meme"],        # 5 napkin — surprised
}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    h = hv.PinterestHarvester()
    h.warm_session(force=False)
    cli = httpx.Client(timeout=25, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com/"})
    font = ImageFont.truetype("arial.ttf", 15)
    for mood, qs in Q.items():
        seen: dict[str, dict] = {}
        for q in qs:
            for o, m in search(h, q, pages=2):
                sig = str(o.get("image_signature") or m.image_url.rsplit("/", 1)[-1].split(".")[0])
                likes = sum(int(v) for v in (o.get("reaction_counts") or {}).values())
                if sig not in seen or seen[sig]["likes"] < likes:
                    seen[sig] = {"likes": likes, "url": HP.url_736(m.image_url)}
        rows = sorted(seen.values(), key=lambda r: -r["likes"])[:48]

        def get(r):
            try:
                x = cli.get(r["url"])
                return ImageOps.exif_transpose(Image.open(io.BytesIO(x.content))).convert("RGB") if x.status_code == 200 else None
            except Exception:
                return None
        with ThreadPoolExecutor(8) as ex:
            ims = list(ex.map(get, rows))
        d = OUT / mood
        d.mkdir(parents=True, exist_ok=True)
        keep, fps = [], []
        for r, im in zip(rows, ims):
            if im is None or min(im.size) < 300:
                continue
            fp = HP.dhash(im)
            if any(bin(fp ^ f).count("1") <= 8 for f in fps):
                continue
            fps.append(fp)
            keep.append((r, im))
        tw, th, cols = 220, 220, 8
        s = Image.new("RGB", (cols * tw, ((len(keep) + cols - 1) // cols) * (th + 20)), (25, 25, 25))
        dr = ImageDraw.Draw(s)
        for n, (r, im) in enumerate(keep, 1):
            im.save(d / f"{n:03d}.jpg", quality=92)
            x, y = ((n - 1) % cols) * tw, ((n - 1) // cols) * (th + 20)
            s.paste(ImageOps.contain(im, (tw, th)), (x, y + 20))
            dr.text((x + 3, y + 2), f"{n:03d} L{r['likes']}", fill=(255, 230, 80), font=font)
        s.save(d / "_sheet.jpg", quality=85)
        print(mood, len(keep), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
