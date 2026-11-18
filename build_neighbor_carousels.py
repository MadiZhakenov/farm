#!/usr/bin/env python3
"""
Inspoy — соседка 62 и первое свидание (айди нет): 7 слайдов 3:4 по методу дальнобойщика
(build_dad_trucker_carousels: яркий цвет, лёгкий зум/сдвиг, TikTok-текст с обводкой, тексты ТЗ дословно).
Кадры Flow — output/neighbor_slides/s<k>/*.jpg. Лица только на s1.
  s6 — скриншот iMessage (тёмная тема): соседка прислала фото букета (s6/s6_photo.jpg) + сообщение; подпись ТЗ —
       в полосе между шапкой и перепиской.
  s7 — платье на двери + карточка Inspoy из App Store (без тени).

  python build_neighbor_carousels.py -n 4 --out output/neighbor_test
  python build_neighbor_carousels.py -n 150 --out output/carousels_neighbor --flat output/neighbor_150
  # +100 (11.11): новые кадры юзера (output/neighbor_slides_v2, 7–8 на слайд), весь текст посередине, равномерное использование кадров
  python build_neighbor_carousels.py -n 100 --slides output/neighbor_slides_v2 --mid --balanced --suffix 1       --out output/carousels_neighbor_v2_100 --flat output/neighbor_v2_100
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_dad_trucker_carousels as DT  # noqa: E402  (vivid, frame, store_card, C.block_for)
import render_imessage as IM  # noqa: E402
import strip_jpeg_meta  # noqa: E402
from core.safe_zones import check_box, draw_overlay  # noqa: E402

W, H = DT.W, DT.H
X0, Y0, X1, Y1 = DT.X0, DT.Y0, DT.X1, DT.Y1
C = DT.C
SL = ROOT / "output" / "neighbor_slides"

# посередине (+100, 11.11): центр блока; s1 — чуть ниже лиц, s7 — чуть выше, чтобы под ним поместилась карточка App Store;
# s6 (переписка) — подпись под шапкой, как раньше, иначе закрывает фото букета
MID = [0.56, 0.5, 0.5, 0.5, 0.5, None, 0.46]
# текст ТЗ дословно (переносы по смыслу); (текст, центр блока по высоте, макс. высота) — None для s6 (чат)
SLIDES = [
    ("my 62-year-old neighbor\nknocked on my door\nand asked if i could help her\npick an outfit for a date", 0.68, 0.2),
    ("she hadn’t been on one\nin 20 years. she said\n“i don’t know\nwhat women wear now”", 0.155, 0.2),
    ("her closet was full of clothes\nshe bought “for later”", 0.12, 0.12),
    ("we tried on six outfits.\nshe kept saying\n“this is too much.”\ni kept saying\n“no, this is you”", 0.175, 0.24),
    ("she stood in front of the mirror\nfor a full minute\nand didn’t say anything.\nthen she said\n“i forgot i liked how i look”",
     0.66, 0.24),
    ("she wore the green dress.\nhe showed up with flowers,\nshe texted me a photo of them", None, None),
    ("i built every look in Inspoy\nbefore we tried anything on.\nshe asked me\nto show her how", 0.155, 0.2),
]
NAMES = ["Linda", "Carol", "Diane", "Susan", "Patricia", "Debbie", "Karen M", "Barbara"]
HER_MSG = ["he brought flowers 🥹", "look what he brought 🥹💐", "he showed up with these 😭", "FLOWERS 🥹",
           "he brought me flowers!!"]
MY_MSG = ["STOP 😭😭", "omg 🥹🥹", "i’m crying", "told you the green one 💚", "SCREAMING"]


def caption(text: str, cy: float, mh: float, rng: random.Random) -> tuple[Image.Image, tuple]:
    cy += rng.uniform(-0.008, 0.008)
    top, bottom = max(int((cy - mh / 2) * H), Y0), min(int((cy + mh / 2) * H), Y1)
    block = C.block_for(text, bottom - top, X1 - X0)
    x = max(X0, min(X1 - block.width, int(W / 2 - block.width / 2 + rng.randint(-14, 14))))
    y = max(Y0, min(Y1 - block.height, int((top + bottom) / 2 - block.height / 2)))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.alpha_composite(block, (x, y))
    return layer, (x, y, x + block.width, y + block.height)


def imessage(photo: Path, rng: random.Random) -> tuple[Image.Image, tuple]:
    """Скрин iMessage 1080×1440: шапка с именем соседки, время, её фото букета (пузырь-картинка), её сообщение,
    мой ответ. Сверху между шапкой и перепиской — подпись ТЗ."""
    s = IM.SS
    img = Image.new("RGBA", (W * s, H * s), IM.C_BG)
    d = ImageDraw.Draw(img)
    top_cap = IM.STATUS_H + IM.HEADER_H + 20
    y = 600 * s                                                       # переписка ниже полосы подписи
    tpx = 30 * s
    when = f"Today {rng.randint(6, 9)}:{rng.randint(10, 59):02d} PM"
    IM.T.draw_text(img, W * s / 2 - IM.T.text_w(when, tpx) / 2, y, when, tpx, fill=IM.C_GRAY)
    y += 56 * s
    pw = rng.randint(420, 450)                                        # фото-пузырь
    ph = round(pw * 1200 / 896)
    pim = ImageOps.fit(DT.vivid(Image.open(photo).convert("RGB"), rng), (pw * s, ph * s), Image.Resampling.LANCZOS)
    m = Image.new("L", pim.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, pim.width - 1, pim.height - 1), radius=36 * s, fill=255)
    img.paste(pim, (IM.SIDE * s, y), m)
    y += ph * s + IM.GAP_SAME * s
    for kind, text in (("them", rng.choice(HER_MSG)),):          # только её сообщение — мой ответ уходил за край
        px = IM.FONT_PX * s
        lines = IM.T.wrap(text, px, IM.MAX_W * s - 2 * IM.PAD_X * s)
        lh = round(px * IM.LINE_GAP)
        bw = int(max(IM.T.text_w(ln, px) for ln in lines) + 2 * IM.PAD_X * s)
        bh = int(lh * len(lines) + 2 * IM.PAD_Y * s)
        right = kind == "me"
        if right:
            y += IM.GAP_SWITCH * s
        bx1 = (W - IM.SIDE) * s if right else IM.SIDE * s + bw
        bx0 = bx1 - bw
        color = IM.C_ME if right else IM.C_THEM
        r = int(bh // 2) - 1
        corners = (True, True, not right, right)
        d.rounded_rectangle((bx0, y, bx1, y + bh), radius=r, corners=corners, fill=color)
        IM.tail(d, bx1 if right else bx0, y + bh, right, color, s, r)
        ty = y + IM.PAD_Y * s
        for ln in lines:
            IM.T.draw_text(img, bx0 + IM.PAD_X * s, ty, ln, px)
            ty += lh
        y += bh
    IM.header(img, s, rng.choice(NAMES))
    d.rectangle((0, 0, W * s, IM.STATUS_H * s), fill=IM.C_HEADER)
    IM.status_bar(img, s, f"{rng.randint(6, 9)}:{rng.randint(10, 59):02d}")
    chat = img.resize((W, H), Image.Resampling.LANCZOS)
    layer, box = caption(SLIDES[5][0], (top_cap + 585) / 2 / H, (585 - top_cap) / H, rng)
    return Image.alpha_composite(chat, layer).convert("RGB"), box


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=4)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_noid.jpg")
    ap.add_argument("--seed", type=int, default=62)
    ap.add_argument("--qa", action="store_true")
    ap.add_argument("--slides", type=Path, default=SL, help="папка с пулами s1…s7")
    ap.add_argument("--mid", action="store_true", help="весь текст посередине")
    ap.add_argument("--balanced", action="store_true", help="каждый кадр пула — поровну раз, сочетания не повторяются")
    ap.add_argument("--suffix", default="noid", help="хвост имени во flat-папке: sort_<слайд>_<номер>_<suffix>.jpg")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sl = a.slides
    pools = [sorted(f for f in (sl / f"s{k}").glob("*.jpg") if f.stem != "s6_photo") or [sl / "s6" / "s6_photo.jpg"]
             for k in range(1, 8)]
    if a.balanced:                                             # по каждому слайду — кадры по кругу в своём случайном порядке
        r0 = random.Random(a.seed)
        for _ in range(1000):
            seqs = []
            for pl in pools:
                seq = []
                while len(seq) < a.n:
                    q = list(range(len(pl)))
                    r0.shuffle(q)
                    seq += q
                seqs.append(seq[:a.n])
            combos = list(zip(*seqs))
            if len(set(combos)) == len(combos):
                break
    else:
        combos = list(itertools.product(*[range(len(pl)) for pl in pools]))
        random.Random(a.seed).shuffle(combos)
    a.out.mkdir(parents=True, exist_ok=True)
    manifest, qa = [], []
    for i in range(1, a.n + 1):
        rng = random.Random(a.seed * 1000 + i)
        pick = [pools[k][j] for k, j in enumerate(combos[(i - 1) % len(combos)])]
        d = a.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        for k, (text, cy, mh) in enumerate(SLIDES):
            if a.mid and MID[k] is not None:
                cy = MID[k]
            if k == 5:
                out, box = imessage(pick[5], rng)
                boxes = [box]
            else:
                im = DT.vivid(DT.frame(pick[k], rng), rng).convert("RGBA")
                layer, box = caption(text, cy, mh, rng)
                boxes = [box]
                if k == 6:                                     # карточка ниже — платье на двери видно
                    DT.CARD_W = 640
                    card = DT.store_card()
                    cx_, cy_ = (W - card.width) // 2, Y1 - card.height - 6
                    im.alpha_composite(card, (cx_, cy_))
                    boxes.append((cx_, cy_, cx_ + card.width, cy_ + card.height))
                out = Image.alpha_composite(im, layer).convert("RGB")
            for b in boxes:
                if bad := check_box(W, H, b):
                    raise SystemExit(f"{i:03d} слайд {k + 1}: вне безопасной зоны {b} — {bad}")
            out.save(d / f"{k + 1}.jpg", quality=93)
            if a.qa and i <= 2:
                q = draw_overlay(out)
                for b in boxes:
                    ImageDraw.Draw(q).rectangle(b, outline=(255, 220, 0), width=5)
                qa.append(q)
            if a.flat:
                a.flat.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d / f"{k + 1}.jpg", a.flat / f"sort_{k + 1}_{i}_{a.suffix}.jpg")
        manifest.append({"carousel": d.name, "frames": [p.name for p in pick]})
        print(f"  {d.name}", flush=True)
    if qa:
        tw, th = 300, 400
        sheet = Image.new("RGB", (7 * tw, (len(qa) // 7) * th), (30, 30, 30))
        for j, q in enumerate(qa):
            sheet.paste(q.resize((tw, th)), ((j % 7) * tw, (j // 7) * th))
        sheet.save(a.out / "_qa.jpg", quality=86)
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    sys.argv = ["strip", str(a.out)] + ([str(a.flat)] if a.flat else [])
    strip_jpeg_meta.main()
    print(f"готово: {a.n} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
