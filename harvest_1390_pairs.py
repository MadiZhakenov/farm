#!/usr/bin/env python3
"""
1390 — пары «одна вещь, два фото» (как в рефе: LDN + LDN, Schuze + Schuze): у каждого пина-«семени» (числовой id,
выбран глазами — брендовые джинсы крупно, вайб рефа) берём «Ещё похожее» Pinterest и ищем там второе фото ТОЙ ЖЕ вещи:
SigLIP-похожесть 0,80–0,955 (выше — тот же кадр/репин, ниже — другая вещь). Пары — кандидаты, финал глазами.

  python harvest_1390_pairs.py           # семена — SEEDS ниже → output/1390_pairs/<слот>/ + _pairs_<слот>.jpg
"""

from __future__ import annotations

import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import harvest_carousel_pool as HP  # noqa: E402
from core import harvester as hv  # noqa: E402

OUT = ROOT / "output" / "1390_pairs"
SEEDS = {
    "embroidered": ["936467316270366914", "961377851706549847", "1057149712545977817", "1020276490598948471",
                    "723109283975027994", "615867317834650748", "1038431626669533397", "696298792413511300", "831266043734636761"],
    "graphic": ["651051689927279612", "730709108296486594", "921126930051499780", "1093600722041040363", "826692075374087034",
                "657103401915485966", "709879960051070562", "1019995015638306259", "1078823285715000831"],
    "wide_dark": ["1114359501545931985", "1084804629003436695", "843017624040692963", "751538256586969647", "735423814184394237"],
    "vintage_wash": ["837599230732268336", "1116329826406902293", "979744093950229258", "246079567118171032",
                     "729935052153344720", "660410732882794507", "782922716487314359"],
    "patchwork": ["4591138454535473408", "813673857713261264", "1140395936913421332", "281543726156374", "812547957802115907",
                  "622341242280962864"],
    "cargo": ["887912882807906770", "1072630836259354659", "823736588135765994", "939563541004644888", "1030902170928611017"],
    "studded": ["1152006779713925222", "526217537736338062", "1149966086093650282", "1066297649344779048", "830210512602033219",
                "856809897908984667", "803892602262301713", "796714990352561270", "588142032618619604"],
    "raw_denim": ["342906959150361540", "992199361664166691", "757027018650393203", "603412050116108514",
                  "1072701205004857583", "730779477075338950", "1040683426396626651"],
}
LO, HI = 0.80, 0.955


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    from core.taste_embedder import get_embedder
    h = hv.PinterestHarvester()
    h.warm_session(force=False)
    emb = get_embedder()
    emb.ensure()
    cli = httpx.Client(timeout=25, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com/"})
    font = ImageFont.truetype("arial.ttf", 15)

    def get(u):
        try:
            x = cli.get(HP.url_736(u))
            return ImageOps.exif_transpose(Image.open(io.BytesIO(x.content))).convert("RGB") if x.status_code == 200 else None
        except Exception:
            return None

    for slot, seeds in SEEDS.items():
        d = OUT / slot
        d.mkdir(parents=True, exist_ok=True)
        groups = []
        for sid in seeds:
            page = h._related_from_pin_page(sid)                        # сам пин: картинка семени
            seed_meta = None
            try:
                r = h._client.get(f"https://www.pinterest.com/pin/{sid}/", headers=hv.HTML_HEADERS)
                for m in hv._extract_from_pws_html(r.text):
                    if m.pin_id == sid:
                        seed_meta = m
                        break
            except Exception:
                pass
            rel = h.fetch_related_metas(sid, limit=40)
            metas = ([seed_meta] if seed_meta else []) + rel
            with ThreadPoolExecutor(8) as ex:
                ims = list(ex.map(lambda m: get(m.image_url), metas))
            items = [(m, im) for m, im in zip(metas, ims) if im is not None and im.height / im.width >= 0.9]
            if not items:
                continue
            V = emb.embed_images([im for _, im in items])
            groups.append((sid, items, V, seed_meta is not None))
            print(f"[{slot}] {sid}: семя {'есть' if seed_meta else 'нет'}, похожих {len(items)}", flush=True)
        # пары: внутри группы — два фото с похожестью LO..HI (одна вещь, разные кадры)
        pairs, used = [], set()
        for sid, items, V, has_seed in groups:
            S = V @ V.T
            idx = range(len(items))
            cand = sorted(((float(S[i, j]), i, j) for i in idx for j in idx if i < j and LO <= S[i, j] <= HI), reverse=True)
            for s, i, j in cand:
                a, b = items[i][0].pin_id, items[j][0].pin_id
                if a in used or b in used:
                    continue
                used |= {a, b}
                pairs.append((sid, s, items[i], items[j]))
                if sum(p[0] == sid for p in pairs) >= 3:
                    break
        man = []
        for k, (sid, s, (ma, ia), (mb, ib)) in enumerate(pairs, 1):
            fa, fb = f"p{k:02d}_a_{ma.pin_id[:20]}.jpg", f"p{k:02d}_b_{mb.pin_id[:20]}.jpg"
            ia.save(d / fa, quality=92)
            ib.save(d / fb, quality=92)
            man.append({"pair": k, "seed": sid, "sim": round(s, 3), "a": fa, "b": fb, "a_pin": ma.pin_id, "b_pin": mb.pin_id,
                        "a_url": ma.orig_url, "b_url": mb.orig_url})
        (d / "pairs.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
        tw, th, cols = 200, 300, 4                                      # 4 пары в ряд, пара = 2 картинки
        rows = (len(man) + cols - 1) // cols
        sh = Image.new("RGB", (cols * (2 * tw + 16), max(1, rows) * (th + 20)), (25, 25, 25))
        dr = ImageDraw.Draw(sh)
        for k, p in enumerate(man):
            x, y = (k % cols) * (2 * tw + 16), (k // cols) * (th + 20)
            sh.paste(ImageOps.fit(Image.open(d / p["a"]), (tw, th)), (x, y + 20))
            sh.paste(ImageOps.fit(Image.open(d / p["b"]), (tw, th)), (x + tw, y + 20))
            dr.text((x + 3, y + 2), f"p{p['pair']:02d} sim {p['sim']}", fill=(255, 230, 80), font=font)
        sh.save(OUT / f"_pairs_{slot}.jpg", quality=86)
        print(f"{slot}: пар {len(man)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
