#!/usr/bin/env python3
"""
1390 — пины Pinterest под слайды. Сбор — во встроенном браузере под входом пользователя: 2–4 коротких запроса на слайд
(название слайда + популярные модели из веб-поиска), «похожие» у лучших находок, у каждого пина лайки и сохранения
(/v3/pins/); отсеяны видео, метка ИИ, повторы картинки, мелкие и горизонтальные. Браузер отдаёт частями строки
«id|лайки|сохранения|хеш картинки» по убыванию сохранений → output/1390_pins/<слот>.txt.

Здесь: качаем картинки (736x для отсева и листов, оригинал — для кадра), отсеиваем мусор — надписи на фото, коллажи,
каталог на белом, почти-дубли (dHash), не по теме слайда («похожие» уводят в часы / худи / браслеты: SigLIP-метка
должна быть «джинсы» / «девушка в джинсах», не «мужчина в джинсах» — реф женский, а выдача под аккаунтом
пользователя мужская; для обложки — «девушка в дениме»; на порядок не влияет) — и рисуем листы для отбора глазами (L — лайки, S — сохранения).

  python harvest_1390_pins.py graphic cover …        # → output/1390_pins/<слот>/NNN_<id>.jpg + _full/ + manifest.json + _sheet_*.jpg
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
import harvest_carousel_pool as HP  # noqa: E402  (dhash)

OUT = ROOT / "output" / "1390_pins"
TILE = (540, 960)
MAX_TEXT = 12
OTHER = ["a wrist watch", "a hoodie or sweatshirt", "a jacket", "a baseball cap", "sunglasses", "jewelry or bracelets",
         "sneakers or shoes", "a t-shirt", "a handbag", "nails manicure", "a skirt", "a dress", "a room interior",
         "a woman's face portrait", "a car", "a man wearing jeans", "a guy's outfit, menswear"]
JEANS = ["a photo of jeans", "a woman wearing jeans", "jeans laid out flat", "a close up of jeans"]
COVER = ["a woman wearing baggy jeans, full outfit photo", "a girl in a denim outfit"]          # реф женский


def is_collage(im: Image.Image) -> bool:
    """Коллаж: сквозной прямой шов во всю высоту или ширину в средней части кадра."""
    g = np.asarray(im.convert("L").resize((240, 320)), dtype=np.float32)
    for a in (g, g.T):
        straight = (np.abs(np.diff(a, axis=1)) > 18).mean(axis=0)
        n = straight.size
        if straight[int(n * 0.2):int(n * 0.8)].max() > 0.82:
            return True
    return False


def is_catalog(im: Image.Image) -> bool:
    """Каталог / товар на белом: рамка кадра почти вся белая."""
    a = np.asarray(im.convert("RGB").resize((200, 266)), dtype=np.int16)
    b = np.concatenate([a[:8].reshape(-1, 3), a[-8:].reshape(-1, 3), a[:, :8].reshape(-1, 3), a[:, -8:].reshape(-1, 3)])
    return ((b.min(1) > 225) & (b.max(1) - b.min(1) < 18)).mean() > 0.6


def decode(line: str) -> tuple[str, str, str, str, str]:
    """«id|L|S|sig» (текущий формат, по убыванию сохранений) или старый «id36,sig64,L,S,ext» → (id, sig, L, S, ext);
    ext "" — расширение оригинала неизвестно, перебираем."""
    if "|" in line:
        pid, likes, saves, sig = line.split("|")
        return pid, sig, likes, saves, ""
    import base64
    i36, s64, likes, saves, ext = (line.split(",") + [""])[:5]
    sig = base64.urlsafe_b64decode(s64 + "=" * (-len(s64) % 4)).hex()
    return str(int(i36, 36)), sig, likes, saves, ext or "jpg"


def original(cli: httpx.Client, sig: str, ext: str) -> Image.Image | None:
    for e in ([ext] if ext else ["jpg", "png", "webp"]):
        im = fetch(cli, url(sig, "originals", e))
        if im is not None:
            return im
    return None


def url(sig: str, size: str, ext: str = "jpg") -> str:
    return f"https://i.pinimg.com/{size}/{sig[:2]}/{sig[2:4]}/{sig[4:6]}/{sig}.{ext}"


def fetch(cli: httpx.Client, u: str) -> Image.Image | None:
    try:
        r = cli.get(u)
        return ImageOps.exif_transpose(Image.open(io.BytesIO(r.content))).convert("RGB") if r.status_code == 200 else None
    except Exception:
        return None


def sheets(out: Path, rows: list[dict], per: int = 24) -> None:
    tw, th, cols = 270, 480, 6
    font = ImageFont.truetype("arial.ttf", 18)
    for k in range(0, len(rows), per):
        part = rows[k:k + per]
        s = Image.new("RGB", (cols * tw, ((len(part) + cols - 1) // cols) * (th + 24)), (25, 25, 25))
        d = ImageDraw.Draw(s)
        for i, r in enumerate(part):
            x, y = (i % cols) * tw, (i // cols) * (th + 24)
            s.paste(Image.open(out / r["file"]).resize((tw, th)), (x, y + 24))
            d.text((x + 4, y + 3), f"{r['file'][:3]} L{r['likes']} S{r['saves']}", fill=(255, 230, 80), font=font)
        s.save(out / f"_sheet_{k // per + 1:02d}.jpg", quality=86)


def on_topic(emb, ims: list[Image.Image], slot: str) -> list[bool]:
    pos = COVER if slot == "cover" else JEANS
    tv = emb.embed_texts(pos + OTHER)
    best = (emb.embed_images(ims) @ tv.T).argmax(axis=1)
    return [int(b) < len(pos) for b in best]


def run(slot: str, ocr, emb) -> None:
    rows_in = [decode(ln) for ln in (OUT / f"{slot}.txt").read_text(encoding="utf-8").split()]
    cli = httpx.Client(timeout=25, follow_redirects=True,
                       headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com/"})
    with ThreadPoolExecutor(8) as ex:
        ims = list(ex.map(lambda r: fetch(cli, url(r[1], "736x")), rows_in))
    out = OUT / slot
    (out / "_full").mkdir(parents=True, exist_ok=True)
    ok = iter(on_topic(emb, [im for im in ims if im is not None], slot))
    topic = [next(ok) if im is not None else False for im in ims]
    why: dict[str, int] = {}
    kept, fps = [], []
    for (pid, sig, likes, saves, ext), im, good in zip(rows_in, ims, topic):
        reason = None
        if im is None:
            reason = "download"
        elif not good:
            reason = "off-topic"
        elif is_collage(im):
            reason = "collage"
        elif is_catalog(im):
            reason = "catalog"
        else:
            fp = HP.dhash(im)
            if any(bin(fp ^ f).count("1") <= HP.DUP_HAMMING for f in fps):
                reason = "dup"
            else:
                small = im.copy()
                small.thumbnail((640, 640))
                chars = sum(len(t.strip()) for _b, t, c in ocr.readtext(np.asarray(small), detail=1) if c >= 0.45)
                if chars > MAX_TEXT:
                    reason = "text"
                else:
                    fps.append(fp)
        if reason:
            why[reason] = why.get(reason, 0) + 1
            continue
        full = original(cli, sig, ext) or im
        name = f"{len(kept) + 1:03d}_{pid}.jpg"
        ImageOps.fit(full, TILE, Image.Resampling.LANCZOS, centering=(0.5, 0.45)).save(out / name, quality=92)
        full.save(out / "_full" / name, quality=95)
        kept.append({"file": name, "pin_id": pid, "pin_url": f"https://www.pinterest.com/pin/{pid}/", "likes": int(likes),
                     "saves": int(saves), "source_px": list(full.size)})
    (out / "manifest.json").write_text(json.dumps(kept, indent=1, ensure_ascii=False), encoding="utf-8")
    sheets(out, kept)
    print(f"{slot}: {len(rows_in)} → {len(kept)} (от 300 лайков: {sum(r['likes'] >= 300 for r in kept)}) · отсеяно {why}",
          flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import easyocr
    from core.taste_embedder import get_embedder
    ocr = easyocr.Reader(["en"], gpu=True, verbose=False)
    emb = get_embedder()
    emb.ensure()
    for slot in sys.argv[1:]:
        run(slot, ocr, emb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
