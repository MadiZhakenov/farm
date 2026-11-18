#!/usr/bin/env python3
"""
1380 «male gaze vs female gaze» — маленький пул с Pinterest под 8 образов коллажей + фон-девушка для слайда 3:
по 2–3 коротких запроса на слот (как ищут люди) → поиск на 2 страницы с лайками → 736px, отсев повторов,
SigLIP-метка «девушка в полный рост в образе» → лист лучших по лайкам. Отбор глазами, потом правки во Flow.

  python harvest_1380.py m_mini m_corset …     # → output/1380_pool/<слот>/ + manifest.json + _sheet_NN.jpg
"""

from __future__ import annotations

import io
import json
import re
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

OUT = ROOT / "output" / "1380_pool"
Q = {
    # слайд 1 — male gaze
    "m_mini": ["mini dress and heels outfit", "mini dress heels", "going out mini dress"],
    "m_corset": ["corset dress outfit", "corset dress"],
    "m_sheer": ["sheer dress outfit", "sheer dress"],
    "m_backless": ["black backless dress", "backless dress outfit"],
    # слайд 2 — female gaze
    "f_satin": ["satin midi dress ballet flats", "satin skirt ballet flats outfit"],
    "f_blazer": ["blazer dress outfit", "blazer dress"],
    "f_knit": ["knit dress boots outfit", "oversized sweater dress boots"],
    "f_slip": ["slip dress leather jacket", "slip dress leather jacket outfit"],
    # слайд 3 — девушка на фоне под скрин приложения
    "s3_girl": ["outfit inspo girl", "pinterest girl aesthetic outfit"],
    # добор живых фото (первый пул по f_* — во многом ИИ-подборки «30 … outfit ideas»)
    "f_satin_r": ["satin skirt ootd", "satin skirt street style", "satin midi skirt mirror selfie"],
    "f_blazer_r": ["blazer dress mirror selfie", "blazer dress ootd", "blazer dress street style"],
    "f_knit_r": ["sweater dress mirror selfie", "sweater dress ootd", "sweater dress street style"],
}
# заголовки ИИ-ферм и статей-подборок: «30 Best …», «… Outfit Ideas …», «How to Style …»
LISTICLE = re.compile(r"^\s*\d+\s|outfit ideas|how to (style|wear)|ideas for|best .* for", re.I)
KINDS = ["a full body photo of a young woman wearing an outfit, mirror selfie or street photo",
         "a clothing product photo on a plain background or a flat lay, no person",
         "a close up of a face, shoes, a bag or another detail",
         "a collage, a drawing, text or a screenshot"]
SHEET = 35   # сколько лучших показывать на листе


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    from core.taste_embedder import get_embedder
    h = hv.PinterestHarvester()
    h.warm_session(force=False)
    emb = get_embedder()
    emb.ensure()
    T = emb.embed_texts(KINDS)
    cli = httpx.Client(timeout=25, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com/"})
    font = ImageFont.truetype("arial.ttf", 16)
    for slot in sys.argv[1:] or list(Q):
        seen: dict[str, dict] = {}
        for q in Q[slot]:
            for o, m in search(h, q, pages=2):
                sig = str(o.get("image_signature") or m.image_url.rsplit("/", 1)[-1].split(".")[0])
                likes = sum(int(v) for v in (o.get("reaction_counts") or {}).values())
                if LISTICLE.search(o.get("grid_title") or o.get("title") or ""):
                    continue
                if sig in seen:
                    seen[sig]["likes"] = max(seen[sig]["likes"], likes)
                    continue
                seen[sig] = {"pin_id": m.pin_id, "likes": likes, "query": q, "url": HP.url_736(m.image_url),
                             "title": (o.get("grid_title") or o.get("title") or "")[:60]}
            print(f"[{slot}] {q!r}: всего {len(seen)}", flush=True)
        rows = sorted(seen.values(), key=lambda r: -r["likes"])

        def get(r):
            try:
                x = cli.get(r["url"])
                return ImageOps.exif_transpose(Image.open(io.BytesIO(x.content))).convert("RGB") if x.status_code == 200 else None
            except Exception:
                return None
        with ThreadPoolExecutor(8) as ex:
            ims = list(ex.map(get, rows))
        keep, fps = [], []
        for r, im in zip(rows, ims):
            if im is None or im.height / im.width < 1.15 or im.width < 600:
                continue
            fp = HP.dhash(im)
            if any(bin(fp ^ f).count("1") <= 8 for f in fps):
                continue
            fps.append(fp)
            keep.append((r, im))
        kind = (emb.embed_images([im for _, im in keep]) @ T.T).argmax(1) if keep else []
        order = sorted(range(len(keep)), key=lambda i: (kind[i] != 0, -keep[i][0]["likes"]))   # сначала люди в образе
        d = OUT / slot
        d.mkdir(parents=True, exist_ok=True)
        man = []
        for n, i in enumerate(order, 1):
            r, im = keep[i]
            name = f"{n:03d}_{r['pin_id'][:24]}.jpg"
            im.save(d / name, quality=92)
            man.append({**r, "file": name, "kind": ["person", "product", "detail", "other"][kind[i]], "px": list(im.size)})
        (d / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
        tw, th, cols = 240, 320, 7
        part = [r for r in man if r["kind"] == "person"][:SHEET]
        s = Image.new("RGB", (cols * tw, ((len(part) + cols - 1) // cols) * (th + 22)), (25, 25, 25))
        dr = ImageDraw.Draw(s)
        for j, r in enumerate(part):
            x, y = (j % cols) * tw, (j // cols) * (th + 22)
            s.paste(ImageOps.fit(Image.open(d / r["file"]), (tw, th)), (x, y + 22))
            dr.text((x + 3, y + 2), f"{r['file'][:3]} L{r['likes']} {r['px'][0]}", fill=(255, 230, 80), font=font)
        s.save(d / "_sheet.jpg", quality=86)
        print(f"{slot}: {len(rows)} пинов → {len(man)} картинок (люди в образе: {sum(1 for r in man if r['kind'] == 'person')})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
