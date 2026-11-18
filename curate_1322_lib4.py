#!/usr/bin/env python3
"""
1322 партия 601–900: листы кандидатов для новой библиотеки output/1322_lib4 из пулов output/1322_pool5.
Для каждого фото звезды — как оно ляжет в слот (круг сезона 352 px / карточка результата 812×834) + флаги:
  TEXT — на полном оригинале нашлась надпись/водяной знак (RapidOCR, верх/низ и всё фото);
  PAD  — круг пришлось бы достраивать размытым фоном сверху (≥ 3 % кадра; юзер такое запретил);
  NOFIT — голова не помещается в круг; NOFACE — лицо не найдено; PALE — блёклое/выцветшее фото.
Отбор — глазами по листу: номера оставленных → --keep, копируются в lib4/<слот>/<звезда>__<n>.jpg.

  python curate_1322_lib4.py --sheets                      # листы output/1322_cand4/<слот>.jpg + flags.json
  python curate_1322_lib4.py --keep winter katy_perry 3,7,12
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1322_carousels as B  # noqa: E402
import harvest_carousel_pool as H  # noqa: E402

POOL = ROOT / "output" / "1322_pool5"
LIB = ROOT / "output" / "1322_lib4"
CAND = ROOT / "output" / "1322_cand4"
SEASON_SLOTS = ("winter", "spring", "summer", "autumn")
_OCR = None


def slot_of() -> dict[str, str]:
    return {n.lower().replace(" ", "_").replace("-", "_"): slot for slot, names in H.CQ5_STARS.items() for n in names}


def ocr_text(im: Image.Image) -> str:
    """Надписи на фото: RapidOCR по всему кадру (уменьшенному) и отдельно по верхней/нижней полосе ×2."""
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    rgb = im.convert("RGB")
    found = []
    k = 1400 / max(rgb.size)
    parts = [rgb.resize((round(rgb.width * k), round(rgb.height * k)))] if k < 1 else [rgb]
    h = rgb.height
    for y0, y1 in ((0, 0.16), (0.84, 1.0)):
        band = rgb.crop((0, round(h * y0), rgb.width, round(h * y1)))
        parts.append(band.resize((band.width * 2, band.height * 2)))
    for p in parts:
        res, _ = _OCR(np.asarray(p))
        for _box, txt, conf in res or []:
            t = "".join(ch for ch in txt if ch.isalnum())
            if len(t) >= 2 and float(conf) > 0.6:
                found.append(t)
    return " ".join(found)


def top_pad(src: Path, season: str) -> tuple[float | None, float]:
    """Доля кадра круга, которую crop_pad достроил бы сверху (0 — не нужно)."""
    fr = B.circle_frame(src, season)
    if fr is None:
        return None, 1.0
    zoom, drop = fr
    im = Image.open(src)
    x0, y0, x1, y1, _ = B.face_box(im)
    fh = y1 - y0
    side = zoom * fh
    cy = (y0 + y1) / 2 + drop * fh
    t = cy - side / 2
    b = cy + side / 2
    t -= max(0.0, b - im.height)                     # crop_pad сдвигает кадр вверх, если не влезает снизу
    return zoom, max(0.0, -t) / side


def pale(im: Image.Image) -> bool:
    a = np.asarray(im.convert("HSV").resize((200, 200))).astype(np.float32)
    return a[..., 1].mean() < 38 or a[..., 2].std() < 30


def star_flags(job: tuple[str, str]) -> tuple[str, str, list]:
    """Флаги всех фото одной звезды (отдельный процесс; OCR — только тем, кто прошёл лицо/круг)."""
    star, slot = job
    rows = []
    for f in sorted((POOL / star / "_full").glob("*.jpg")):
        n = int(f.name.split("_")[0])
        fl = []
        im = Image.open(f)
        fb = B.face_box(im)
        if fb is None:
            fl.append("NOFACE")
        if slot in SEASON_SLOTS and fb is not None:
            zoom, pad = top_pad(f, slot)
            if zoom is None:
                fl.append("NOFIT")
            elif pad >= 0.03:
                fl.append(f"PAD{round(pad * 100)}")
        if not fl:
            t = ocr_text(im)
            if t:
                fl.append("TEXT:" + t[:18])
            if pale(im):
                fl.append("PALE")
        rows.append((n, str(f), fl))
    (CAND / "_flags").mkdir(parents=True, exist_ok=True)
    (CAND / "_flags" / f"{star}.json").write_text(json.dumps(rows), encoding="utf-8")
    return star, slot, rows


def sheets(jobs: int = 8) -> None:
    import os
    from concurrent.futures import ProcessPoolExecutor
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    CAND.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype("arial.ttf", 20)
    by_slot: dict[str, list] = {}
    todo = [(st, sl) for st, sl in slot_of().items() if (POOL / st / "_full").is_dir()]
    flags = {}
    with ProcessPoolExecutor(jobs) as ex:
        for star, slot, rows in ex.map(star_flags, todo):
            for n, f, fl in rows:
                flags[f"{star}/{n}"] = fl
                by_slot.setdefault(slot, []).append((star, n, Path(f), fl))
            print(star, "ok", flush=True)
    (CAND / "flags.json").write_text(json.dumps(flags, indent=1, ensure_ascii=False), encoding="utf-8")
    for slot, items in by_slot.items():
        tw, th = (230, 230) if slot in SEASON_SLOTS else (230, 236)
        cols = 10
        rows = (len(items) + cols - 1) // cols
        s = Image.new("RGB", (cols * tw, rows * (th + 26)), (25, 25, 25))
        d = ImageDraw.Draw(s)
        for k, (star, n, f, fl) in enumerate(items):
            x, y = (k % cols) * tw, (k // cols) * (th + 26)
            try:
                if slot in SEASON_SLOTS and "NOFIT" not in fl and "NOFACE" not in fl:
                    zoom, drop = B.circle_frame(f, slot)
                    ph = B.frame_portrait(f, 352, 352, zoom, drop, pad=True)
                else:
                    ph = B.frame_portrait(f, 812, 834, 2.3, 0.22)
                s.paste(ph.resize((tw - 6, th - 6)), (x + 3, y + 26 + 3))
            except Exception as e:                                      # noqa: BLE001
                d.text((x + 4, y + 60), str(e)[:30], fill=(255, 80, 80), font=font)
            col = (255, 90, 90) if fl else (120, 255, 120)
            d.text((x + 3, y + 2), f"{star[:9]} {n}", fill=(255, 230, 0), font=font)
            if fl:
                d.text((x + 3, y + th + 2), ",".join(fl)[:22], fill=col, font=font)
        s.save(CAND / f"{slot}.jpg", quality=84)
        print("sheet", slot, len(items))


def keep(slot: str, star: str, nums: str) -> None:
    out = LIB / slot
    out.mkdir(parents=True, exist_ok=True)
    for n in (int(x) for x in nums.split(",") if x):
        src = next((POOL / star / "_full").glob(f"{n:03d}_*.jpg"))
        shutil.copy2(src, out / f"{star}__{n}.jpg")
    print(slot, star, "→", len(list(out.glob(f'{star}__*'))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", action="store_true")
    ap.add_argument("--keep", nargs=3, metavar=("SLOT", "STAR", "NUMS"))
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.sheets:
        sheets()
    if a.keep:
        keep(*a.keep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
