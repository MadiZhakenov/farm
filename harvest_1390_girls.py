#!/usr/bin/env python3
"""
1390 — доводка слайдов 4–9 до уровня 1–3 (Robin's Jean / LDN): строки из встроенного браузера (поиск по популярной модели +
«Ещё похожее») → картинки, остаются только «девушка в этих джинсах, тёмное живое фото с телефона» (SigLIP) и тёмные
(яркость ≤ 0,5), без каталога и коллажей; листы по убыванию популярности для отбора пар глазами.
Вход: output/1390_girls/rows_<слот>.txt — «id|лайки|сохранения|хеш» через «;».

  python harvest_1390_girls.py wide_dark cargo …     # → output/1390_girls/<слот>/ + _sheet_<слот>.jpg
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
from harvest_1390_pins import is_catalog, is_collage  # noqa: E402

OUT = ROOT / "output" / "1390_girls"
LABELS = ["a dark candid phone photo of a girl wearing jeans, from behind or a mirror selfie, night or dim room",
          "a close up phone photo of the back pocket or print of jeans worn on a body, dim light",
          "a catalog or stock photo of jeans or a model on a plain background",
          "a man wearing jeans", "a collage, a pile of jeans, shoes, a jacket or other items"]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from core.taste_embedder import get_embedder
    emb = get_embedder()
    emb.ensure()
    T = emb.embed_texts(LABELS)
    cli = httpx.Client(timeout=25, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com/"})
    font = ImageFont.truetype("arial.ttf", 14)
    for slot in sys.argv[1:]:
        rows = []
        for s in (OUT / f"rows_{slot}.txt").read_text(encoding="utf-8").strip().split(";"):
            pid, likes, saves, h = s.split("|")
            rows.append({"pin_id": pid, "likes": int(likes), "saves": int(saves), "img": h})

        def get(r):
            h = r["img"].split(".")[0]
            try:
                x = cli.get(f"https://i.pinimg.com/736x/{h[:2]}/{h[2:4]}/{h[4:6]}/{h}.jpg")
                return ImageOps.exif_transpose(Image.open(io.BytesIO(x.content))).convert("RGB") if x.status_code == 200 else None
            except Exception:
                return None
        with ThreadPoolExecutor(8) as ex:
            ims = list(ex.map(get, rows))
        keep, fps = [], []
        for r, im in zip(rows, ims):
            if im is None or im.height / im.width < 1.0 or is_catalog(im) or is_collage(im):
                continue
            if float(np.asarray(im.convert("L").resize((64, 64))).mean()) / 255 > 0.5:
                continue
            fp = HP.dhash(im)
            if any(bin(fp ^ f).count("1") <= 8 for f in fps):
                continue
            fps.append(fp)
            keep.append((r, im))
        cls = (emb.embed_images([im for _, im in keep]) @ T.T).argmax(1) if keep else []
        good = [i for i in range(len(keep)) if cls[i] in (0, 1)]
        good.sort(key=lambda i: -(keep[i][0]["saves"] or keep[i][0]["likes"] * 8))
        d = OUT / slot
        d.mkdir(parents=True, exist_ok=True)
        man = []
        for n, i in enumerate(good, 1):
            r, im = keep[i]
            name = f"{n:03d}_{r['pin_id']}.jpg"
            im.save(d / name, quality=92)
            man.append({**r, "file": name})
        (d / "manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
        tw, th, cols = 160, 240, 12
        top = man[:72]
        sh = Image.new("RGB", (cols * tw, max(1, (len(top) + cols - 1) // cols) * (th + 16)), (20, 20, 20))
        dr = ImageDraw.Draw(sh)
        for j, r in enumerate(top):
            x, y = (j % cols) * tw, (j // cols) * (th + 16)
            sh.paste(ImageOps.fit(Image.open(d / r["file"]), (tw, th)), (x, y + 16))
            dr.text((x + 2, y + 1), f"{r['file'][:3]} S{r['saves']} L{r['likes']}", fill=(255, 230, 80), font=font)
        sh.save(OUT / f"_sheet_{slot}.jpg", quality=86)
        print(f"{slot}: {len(rows)} → {len(man)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
