#!/usr/bin/env python3
"""
1390 — пины, собранные во встроенном браузере (поиск по брендам → «Ещё похожее» у похожих на реф), → картинки и листы.
Вход: output/1390_pool2/rows_<слот>.txt — строки «id|лайки|сохранения|хеш.ext|хеши страниц через запятую|заголовок»
(страницы — фото того же пина-карусели: готовая пара «одна вещь, два ракурса», как в рефе).
Выход: output/1390_pool2/<слот>/NNN_<id>.jpg (736px) + manifest.json + _sheet_NN.jpg (L лайки, S сохранения, P страниц).

  python harvest_1390_web.py embroidered graphic …
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
import harvest_carousel_pool as HP  # noqa: E402  (dhash)

OUT = ROOT / "output" / "1390_pool2"
CLI = httpx.Client(timeout=25, follow_redirects=True,
                   headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com/"})


def url(h: str, size: str = "736x") -> str:
    stem = h.rsplit(".", 1)[0]
    return f"https://i.pinimg.com/{size}/{stem[:2]}/{stem[2:4]}/{stem[4:6]}/{stem}.jpg"


def get(h: str, size: str = "736x") -> Image.Image | None:
    for u in (url(h, size), f"https://i.pinimg.com/originals/{h[:2]}/{h[2:4]}/{h[4:6]}/{h}"):
        try:
            r = CLI.get(u)
            if r.status_code == 200:
                return ImageOps.exif_transpose(Image.open(io.BytesIO(r.content))).convert("RGB")
        except Exception:
            pass
    return None


def run(slot: str) -> None:
    rows = []
    for ln in (OUT / f"rows_{slot}.txt").read_text(encoding="utf-8").split(";"):
        if ln.strip():
            pid, likes, saves, img, pages, title = (ln.split("|") + [""] * 6)[:6]
            rows.append({"pin_id": pid, "likes": int(likes or 0), "saves": int(saves or 0), "img": img,
                         "pages": [p for p in pages.split(",") if p], "title": title})
    with ThreadPoolExecutor(8) as ex:
        ims = list(ex.map(lambda r: get(r["img"]), rows))
    d = OUT / slot
    d.mkdir(parents=True, exist_ok=True)
    keep, fps = [], []
    for r, im in zip(rows, ims):
        if im is None or im.height / im.width < 0.9:
            continue
        fp = HP.dhash(im)
        if any(bin(fp ^ f).count("1") <= 8 for f in fps):              # тот же кадр другим пином
            continue
        fps.append(fp)
        keep.append((r, im))
    keep.sort(key=lambda t: -(t[0]["saves"] or t[0]["likes"] * 8))
    man = []
    for i, (r, im) in enumerate(keep, 1):
        name = f"{i:03d}_{r['pin_id']}.jpg"
        im.save(d / name, quality=90)
        man.append({**r, "file": name, "pin_url": f"https://www.pinterest.com/pin/{r['pin_id']}/", "px": list(im.size)})
    (d / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    font = ImageFont.truetype("arial.ttf", 16)
    tw, th, cols, per = 240, 360, 7, 28
    for k in range(0, len(man), per):
        part = man[k:k + per]
        s = Image.new("RGB", (cols * tw, ((len(part) + cols - 1) // cols) * (th + 22)), (25, 25, 25))
        dr = ImageDraw.Draw(s)
        for i, r in enumerate(part):
            x, y = (i % cols) * tw, (i // cols) * (th + 22)
            s.paste(ImageOps.fit(Image.open(d / r["file"]), (tw, th)), (x, y + 22))
            lab = f"{r['file'][:3]} L{r['likes']} S{r['saves']}" + (f" P{len(r['pages'])}" if len(r["pages"]) > 1 else "")
            dr.text((x + 3, y + 2), lab, fill=(255, 230, 80), font=font)
        s.save(d / f"_sheet_{k // per + 1:02d}.jpg", quality=86)
    print(f"{slot}: {len(rows)} строк → {len(man)} картинок")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for s in sys.argv[1:]:
        run(s)
