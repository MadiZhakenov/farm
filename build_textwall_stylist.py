#!/usr/bin/env python3
"""
Текстволл «стилист» (ID 1, TZ 11.11): на фоне стилиста — статичный текст в стиле Instagram (белый, без плашки, мягкая тень),
цель — увести в комментарии / описание. 11 текстов ТЗ дословно × 2 ролика = 22, по 6 с.
Фон — 5 роликов стилистов (downloads/textwall_stylist/src → clean/: вшитые подписи авторов стёрты LaMa, clean_textwall_stylist.py).
Текст — под лицом (лицо и глаза не закрываем), переносы по смыслу вручную. Уникализация: разный ролик/окно у двух версий
одного текста, кроп-наезд 1.04–1.10 со сдвигом, зеркало, лёгкая цветокоррекция. Звук — родной звук исходника на этом окне.

  python build_textwall_stylist.py --sheet      # лист раскладки текста (файлы не меняются)
  python build_textwall_stylist.py              # → output/textwall_stylist_22/001_1.mp4 … 022_1.mp4
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import check_box  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402

W, H, FPS, DUR = 1080, 1920, 30, 6.0
D = ROOT / "downloads" / "textwall_stylist"
FONT = ROOT / "fonts" / "ig_lookalike" / "Figtree.ttf"
NL = chr(10)
X0, X1, Y_BOTTOM = 150, 930, 1530

# дословно из ТЗ (ORIG), LINES — переносы по смыслу; None — пустая строка между фразами
ORIG = [
    "Your outfit might only need ONE change. Check the 4 things in the caption before buying anything else. Comment STYLE for the outfit guide.",
    "STOP buying clothes for your “goal body.” Especially if you already have a wardrobe full of “maybe someday.” Read the caption before your next order.",
    "Your body changed. Your wardrobe didn’t. Getting dressed doesn’t have to be a daily argument with yourself. Start with the caption.",
    "Fits your thighs. Gaps at the waist. Size down and you can’t sit. Anyone else exhausted by this? Read the caption before blaming your body.",
    "Your saved outfits: hundreds. Your actual outfits: whatever hides you. Are you waiting for your body to change before you dress how you want? Read the caption.",
    "STOP buying an entire outfit because it looked good on her. You can copy every item and still miss what made it work. The 3 things to check are in the caption.",
    "STOP sizing down because your jeans gap at the waist. Especially if the smaller pair squeezes your thighs. Check these 3 fit details before ordering again — they’re in the caption.",
    "STOP blaming your body because the outfit looked better on her. Before buying anything else, check the 3 details that can change how it sits on YOU. The checklist is in the caption.",
    "DON’T replace your entire wardrobe because your body changed. Before another “nothing fits” shopping order, try the wardrobe reset in the caption. Start with what feels comfortable TODAY.",
    "TOP 3 FIT MISTAKES to check before blaming your body. If your outfits look good on the hanger but feel wrong on you, read the caption before buying another size.",
    "TOP 3 THINGS TO STOP BUYING if your wardrobe is full but you still have nothing to wear. Check the list in the caption before your next order.",
]
LINES = [
    ["Your outfit might only need", "ONE change.", "Check the 4 things in the caption", "before buying anything else.",
     "Comment STYLE", "for the outfit guide."],
    ["STOP buying clothes", "for your “goal body.”", "Especially if you already have", "a wardrobe full of", "“maybe someday.”",
     "Read the caption", "before your next order."],
    ["Your body changed.", "Your wardrobe didn’t.", "Getting dressed doesn’t have to", "be a daily argument", "with yourself.",
     "Start with the caption."],
    ["Fits your thighs.", "Gaps at the waist.", "Size down and you can’t sit.", "Anyone else exhausted by this?",
     "Read the caption", "before blaming your body."],
    ["Your saved outfits: hundreds.", "Your actual outfits:", "whatever hides you.", "Are you waiting for your body",
     "to change before", "you dress how you want?", "Read the caption."],
    ["STOP buying an entire outfit", "because it looked good on her.", "You can copy every item", "and still miss what made it work.",
     "The 3 things to check", "are in the caption."],
    ["STOP sizing down", "because your jeans gap", "at the waist.", None, "Especially if the smaller pair", "squeezes your thighs.", None,
     "Check these 3 fit details", "before ordering again —", "they’re in the caption."],
    ["STOP blaming your body", "because the outfit", "looked better on her.", None, "Before buying anything else,", "check the 3 details",
     "that can change", "how it sits on YOU.", None, "The checklist is in the caption."],
    ["DON’T replace", "your entire wardrobe", "because your body changed.", None, "Before another “nothing fits”", "shopping order,",
     "try the wardrobe reset", "in the caption.", None, "Start with what feels", "comfortable TODAY."],
    ["TOP 3 FIT MISTAKES", "to check before", "blaming your body.", "If your outfits look good", "on the hanger", "but feel wrong on you,",
     "read the caption", "before buying another size."],
    ["TOP 3 THINGS TO STOP BUYING", "if your wardrobe is full", "but you still have nothing to wear.", "Check the list in the caption",
     "before your next order."],
]
for o, ls in zip(ORIG, LINES):
    assert " ".join(x for x in ls if x) == o, o[:40]

C1, C2, C3, C4, C5 = ("batch2_01_ashmanmolly_7631641876743064834", "batch2_02_bossymarie_7610778660269722902",
                      "batch2_03_ronhiree_7416339063420046624", "batch2_04_lilrotini_7479940826311904558",
                      "batch2_05_ronhiree_7685748672457346336")
# клип: (сдвиг чистого ролика от исходника по звуку, верх текста — ниже подбородка с запасом)
CLIP = {C1: (0.0, 700), C2: (0.0, 560), C3: (0.0, 860), C4: (6.4, 850), C5: (0.0, 820)}
# окна (клип, старт в чистом ролике, зеркало): у двух версий одного текста — разные ролики
SLOTS = [(C1, 1.0, 0), (C2, 0.0, 0), (C3, 0.0, 0), (C4, 0.0, 0), (C5, 0.3, 0), (C1, 5.0, 1), (C4, 4.4, 1), (C5, 6.2, 1),
         (C2, 2.6, 1), (C3, 4.2, 1), (C5, 12.0, 0), (C1, 9.5, 0), (C4, 8.5, 0), (C5, 17.9, 0), (C3, 2.1, 1), (C2, 1.3, 0),
         (C1, 3.0, 1), (C4, 2.2, 1), (C5, 3.2, 1), (C1, 7.2, 0), (C4, 6.5, 0), (C5, 15.0, 1)]


def plan(seed: int = 1111) -> list[dict]:
    rng = random.Random(seed)
    n = len(LINES)
    v1, v2 = list(SLOTS[:n]), list(SLOTS[n:])
    for _ in range(10000):                                 # у двух версий одного текста — разные ролики
        rng.shuffle(v2)
        if all(a[0] != b[0] for a, b in zip(v1, v2)):
            break
    else:
        raise SystemExit("не разложить окна")
    rows = []
    for t in range(n):
        for v, (clip, st, mir) in enumerate((v1[t], v2[t])):
            rows.append(dict(i=len(rows) + 1, text=t, version=v + 1, clip=clip, start=st, mirror=mir,
                             zoom=round(rng.uniform(1.04, 1.10), 3), dx=round(rng.uniform(-0.25, 0.25), 3), dy=round(rng.uniform(-0.2, 0.2), 3),
                             bri=round(rng.uniform(-0.02, 0.02), 3), sat=round(rng.uniform(0.95, 1.06), 3)))
    return rows


TOP_MAX = 860                                              # самый низкий верх текста среди клипов — кегль общий для двух версий


def wall(lines: list, top: int) -> tuple[Image.Image, int, tuple]:
    """Белый текст Figtree SemiBold по центру, мягкая тень; кегль — максимальный (≤ 52), при котором строки не переносятся
    и блок влезает в самый тесный клип — у двух версий одного текста кегль одинаковый."""
    for px in range(52, 33, -1):
        f = ImageFont.truetype(str(FONT), px)
        f.set_variation_by_name("SemiBold")
        adv, gap = int(px * 1.25), int(px * 0.55)
        ws = [f.getlength(x) if x else 0 for x in lines]
        hh = sum(adv if x else gap for x in lines)
        if max(ws) <= X1 - X0 and max(top, TOP_MAX) + hh <= Y_BOTTOM:
            break
    img = Image.new("RGBA", (W, hh + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 0
    for x, w in zip(lines, ws):
        if not x:
            y += gap
            continue
        d.text(((W - w) / 2, y), x, font=f, fill=(255, 255, 255, 255))
        y += adv
    img = add_shadow(img, blur=5, opacity=0.8, offset=(0, 3), grow=3)
    bbox = img.getbbox()
    box = (bbox[0] - 14, top + bbox[1] - 14, bbox[2] - 14, top + bbox[3] - 14)
    return img, px, box


def render(r: dict, out: Path, work: Path) -> Path:
    off, top = CLIP[r["clip"]]
    img, px, box = wall(LINES[r["text"]], top)
    if bad := check_box(W, H, box):
        raise SystemExit(f"{r['i']}: текст вне безопасной зоны {box} — {bad}")
    png = work / f"tws_{r['i']:03d}.png"
    img.save(png)
    z = r["zoom"]
    cw, ch = int(W / z) // 2 * 2, int(H / z) // 2 * 2
    cx = (W - cw) / 2 * (1 + r["dx"])
    cy = (H - ch) / 2 * (1 + r["dy"])
    vf = (f"[0:v]trim=start={r['start']:.3f}:duration={DUR},setpts=PTS-STARTPTS,crop={cw}:{ch}:{cx:.0f}:{cy:.0f},"
          f"scale={W}:{H}:flags=lanczos,{'hflip,' if r['mirror'] else ''}eq=brightness={r['bri']}:saturation={r['sat']},setsar=1[bg];"
          f"[bg][1:v]overlay=0:{top - 14},format=yuv420p[v];"
          f"[2:a]atrim=start={r['start'] + off:.3f}:duration={DUR},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
          f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=in:d=0.05,afade=t=out:st={DUR - 0.3}:d=0.3[a]")
    dest = out / f"{r['i']:03d}_1.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(D / "clean" / f"{r['clip']}.mp4"), "-i", str(png),
                    "-i", str(D / "src" / f"{r['clip']}.mp4"), "-filter_complex", vf, "-map", "[v]", "-map", "[a]", "-t", f"{DUR}",
                    "-r", str(FPS), "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-c:a", "aac", "-b:a", "160k",
                    "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
                    "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=",
                    "-movflags", "+faststart", str(dest)], check=True)
    png.unlink()
    return dest


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "textwall_stylist_22")
    a = ap.parse_args()
    rows = plan()
    work = ROOT / "output" / "_work" / "textwall_stylist"
    work.mkdir(parents=True, exist_ok=True)
    if a.sheet:
        tiles = []
        for t in range(len(LINES)):
            img, px, box = wall(LINES[t], 700)
            bg = Image.new("RGBA", (W, H), (120, 110, 100, 255))
            bg.alpha_composite(img, (0, 700 - 14))
            ImageDraw.Draw(bg).text((20, 20), f"{t + 1}  px {px}", fill=(255, 255, 0, 255), font=ImageFont.truetype(str(FONT), 40))
            tiles.append(bg.convert("RGB").resize((360, 640)))
        sh = Image.new("RGB", (360 * 6, 640 * 2), "black")
        for k, im in enumerate(tiles):
            sh.paste(im, (k % 6 * 360, k // 6 * 640))
        sh.save(work / "text_sheet.jpg", quality=85)
        print(work / "text_sheet.jpg")
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    for r in rows:
        d = render(r, a.out, work)
        print(f"  {d.name}  текст {r['text'] + 1} v{r['version']}  {r['clip'][7:18]} {r['start']} {'зеркало' if r['mirror'] else ''}", flush=True)
    print(f"готово: {len(rows)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
