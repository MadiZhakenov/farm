#!/usr/bin/env python3
"""
1390 — брендовые пины под слайды: короткие запросы по трендовым брендам/моделям (как в рефе: Jaded London, Schuze,
Ed Hardy) → поиск Pinterest на 3 страницы с лайками → картинки 736px, отсев повторов, SigLIP-метка «что на фото»
(джинсы крупно / человек в полный рост / другое) — для сортировки листов, отбор пар глазами.
Дальше: «Ещё похожее» у выбранных глазами пинов — во встроенном браузере (там числовые id и сохранения).

  python harvest_1390_brands.py embroidered graphic …     # → output/1390_pool2/<слот>/ + manifest.json + _sheet_NN.jpg
"""

from __future__ import annotations

import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import harvest_carousel_pool as HP  # noqa: E402
from core import harvester as hv  # noqa: E402

OUT = ROOT / "output" / "1390_pool2"
Q = {
    "cover": ["denim on denim outfit night", "baggy denim outfit flash", "canadian tuxedo baggy", "double denim streetwear girl",
              "baggy jeans outfit night"],
    "embroidered": ["schuze jeans", "evisu jeans", "true religion jeans", "embroidered jeans", "robins jeans"],
    "graphic": ["ed hardy jeans", "jaded london jeans", "christian audigier jeans", "graphic print jeans", "von dutch jeans"],
    "wide_dark": ["jnco jeans", "jaded london colossus", "polar big boy jeans", "baggy dark jeans", "wide leg dark jeans"],
    "vintage_wash": ["vintage levis baggy", "diesel jeans vintage", "acne studios jeans", "vintage wash jeans", "ksubi jeans"],
    "patchwork": ["kapital patchwork jeans", "who decides war jeans", "patchwork jeans", "jaded london patchwork", "patchwork denim"],
    "cargo": ["jaded london cargo jeans", "bape cargo jeans", "cargo jeans", "baggy cargo jeans", "denim cargo pants"],
    "studded": ["affliction jeans", "miss me jeans", "rock revival jeans", "chrome hearts jeans", "studded jeans"],
    "raw_denim": ["evisu raw denim", "kapital jeans", "raw denim jeans", "selvedge denim baggy", "raw denim"],
}
KINDS = ["a close up photo of jeans: back pockets, print or embroidery on the denim, filling the frame",
         "a full body photo of a person wearing an outfit, mirror selfie or street photo",
         "jeans laid out flat or hanging, product photo",
         "something else: shoes, jacket, hoodie, accessories, a room, a drawing"]


def search(h, q: str, pages: int = 3) -> list[tuple[dict, hv.PinMeta]]:
    source = f"/search/pins/?q={hv.quote_plus(q)}"
    page_url = f"https://www.pinterest.com{source}"
    h._client.get(page_url, headers=hv.HTML_HEADERS)
    h._csrf = h._client.cookies.get("csrftoken") or h._csrf
    out, bm = [], None
    for _ in range(pages):
        opts = {"query": q, "scope": "pins", "page_size": 25, "bookmarks": [bm] if bm else []}
        r = h._client.post("https://www.pinterest.com/resource/BaseSearchResource/get/", headers=h._api_headers(page_url),
                           data={"source_url": source, "data": json.dumps({"options": opts, "context": {}})})
        if r.status_code != 200 or r.content[:1] != b"{":
            break
        js = r.json()
        raw: list[dict] = []
        hv._walk_collect_pins(js, raw)
        for o in raw:
            if o.get("type") != "pin" or o.get("is_promoted") or o.get("videos"):
                continue
            m = hv._pin_from_obj(o)
            if m and m.is_ai is not True:
                out.append((o, m))
        bm = (js.get("resource_response") or {}).get("bookmark")
        if not bm or bm == "-end-":
            break
        time.sleep(0.3)
    return out


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
    for slot in sys.argv[1:]:
        seen: dict[str, dict] = {}
        for q in Q[slot]:
            for o, m in search(h, q):
                sig = str(o.get("image_signature") or m.image_url.rsplit("/", 1)[-1].split(".")[0])
                likes = sum(int(v) for v in (o.get("reaction_counts") or {}).values())
                if sig in seen:
                    seen[sig]["likes"] = max(seen[sig]["likes"], likes)
                    continue
                seen[sig] = {"pin_id": m.pin_id, "likes": likes, "query": q, "url": HP.url_736(m.image_url),
                             "title": (o.get("grid_title") or o.get("title") or "")[:60]}
            print(f"[{slot}] {q!r}: всего {len(seen)}", flush=True)
        rows = list(seen.values())

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
            if im is None or im.height / im.width < 0.9:
                continue
            fp = HP.dhash(im)
            if any(bin(fp ^ f).count("1") <= 8 for f in fps):
                continue
            fps.append(fp)
            keep.append((r, im))
        kind = (emb.embed_images([im for _, im in keep]) @ T.T).argmax(1)
        order = sorted(range(len(keep)), key=lambda i: (kind[i] != 0, -keep[i][0]["likes"]))   # сначала «джинсы крупно»
        d = OUT / slot
        d.mkdir(parents=True, exist_ok=True)
        man = []
        for n, i in enumerate(order, 1):
            r, im = keep[i]
            name = f"{n:03d}_{r['pin_id'][:24]}.jpg"
            im.save(d / name, quality=90)
            man.append({**r, "file": name, "kind": ["closeup", "person", "flat", "other"][kind[i]], "px": list(im.size)})
        (d / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
        tw, th, cols, per = 240, 360, 7, 28
        for k in range(0, len(man), per):
            part = man[k:k + per]
            s = Image.new("RGB", (cols * tw, ((len(part) + cols - 1) // cols) * (th + 22)), (25, 25, 25))
            dr = ImageDraw.Draw(s)
            for j, r in enumerate(part):
                x, y = (j % cols) * tw, (j // cols) * (th + 22)
                s.paste(ImageOps.fit(Image.open(d / r["file"]), (tw, th)), (x, y + 22))
                dr.text((x + 3, y + 2), f"{r['file'][:3]} L{r['likes']} {r['kind'][:5]}", fill=(255, 230, 80), font=font)
            s.save(d / f"_sheet_{k // per + 1:02d}.jpg", quality=86)
        print(f"{slot}: {len(rows)} пинов → {len(man)} картинок (крупно джинсы: {int((kind == 0).sum())})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
