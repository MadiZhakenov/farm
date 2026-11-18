#!/usr/bin/env python3
"""
1390 — пул «одна узнаваемая модель на слайд» (как LDN в рефе): строки из встроенного браузера
(поиск по модели + «Ещё похожее» популярных и пина-образца) → картинки, SigLIP-метка «девушка в этих джинсах, живое
эстетичное фото» против «каталог / сток / мужчина / раскладка / коллаж» — для сортировки, отбор пар глазами.
Вход: output/1390_hero/rows_<слот>.txt — «id|лайки|сохранения|хеш.ext» через «;».

  python harvest_1390_hero.py graphic embroidered …     # → output/1390_hero/<слот>/ + manifest.json + _sheet.jpg
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
from harvest_1390_pins import is_catalog, is_collage  # noqa: E402

OUT = ROOT / "output" / "1390_hero"
GOOD = "an aesthetic candid phone photo of a girl wearing baggy jeans, mirror selfie or from behind, face hidden or cropped, cozy evening light"
BAD = ["a catalog product photo of jeans on a white background", "a stock photo of a fashion model posing in a studio",
       "a man wearing jeans, menswear outfit", "a collage of many photos or a pile of many jeans",
       "jeans laid out flat on the floor, product photo"]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from core.taste_embedder import get_embedder
    emb = get_embedder()
    emb.ensure()
    T = emb.embed_texts([GOOD] + BAD)
    cli = httpx.Client(timeout=25, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com/"})
    font = ImageFont.truetype("arial.ttf", 15)
    for slot in sys.argv[1:]:
        rows = []
        for s in (OUT / f"rows_{slot}.txt").read_text(encoding="utf-8").strip().split(";"):
            pid, likes, saves, h = s.split("|")
            rows.append({"pin_id": pid, "likes": int(likes), "saves": int(saves), "img": h})

        def get(r):
            stem = r["img"].rsplit(".", 1)[0]
            try:
                x = cli.get(f"https://i.pinimg.com/736x/{stem[:2]}/{stem[2:4]}/{stem[4:6]}/{stem}.jpg")
                return ImageOps.exif_transpose(Image.open(io.BytesIO(x.content))).convert("RGB") if x.status_code == 200 else None
            except Exception:
                return None
        with ThreadPoolExecutor(8) as ex:
            ims = list(ex.map(get, rows))
        keep, fps = [], []
        for r, im in zip(rows, ims):
            if im is None or im.height / im.width < 1.0 or is_catalog(im) or is_collage(im):
                continue
            fp = HP.dhash(im)
            if any(bin(fp ^ f).count("1") <= 8 for f in fps):
                continue
            fps.append(fp)
            keep.append((r, im))
        S = emb.embed_images([im for _, im in keep]) @ T.T
        good = [i for i in range(len(keep)) if S[i].argmax() == 0]
        good.sort(key=lambda i: -(keep[i][0]["saves"] or keep[i][0]["likes"] * 8))
        d = OUT / slot
        d.mkdir(parents=True, exist_ok=True)
        man = []
        for n, i in enumerate(good, 1):
            r, im = keep[i]
            name = f"{n:03d}_{r['pin_id']}.jpg"
            im.save(d / name, quality=92)
            man.append({**r, "file": name, "pin_url": f"https://www.pinterest.com/pin/{r['pin_id']}/"})
        (d / "manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
        tw, th, cols = 170, 255, 10
        top = man[:70]
        sh = Image.new("RGB", (cols * tw, max(1, (len(top) + cols - 1) // cols) * (th + 18)), (25, 25, 25))
        dr = ImageDraw.Draw(sh)
        for j, r in enumerate(top):
            x, y = (j % cols) * tw, (j // cols) * (th + 18)
            sh.paste(ImageOps.fit(Image.open(d / r["file"]), (tw, th)), (x, y + 18))
            dr.text((x + 2, y + 1), f"{r['file'][:3]} S{r['saves']} L{r['likes']}", fill=(255, 230, 80), font=font)
        sh.save(OUT / f"_sheet_{slot}.jpg", quality=86)
        print(f"{slot}: {len(rows)} → {len(man)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
