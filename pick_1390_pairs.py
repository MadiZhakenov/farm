#!/usr/bin/env python3
"""
1390 — итоговые кандидаты по листам _pairs_all.jpg (rank_1390_pins.py): на слайд 3–4 ПАРЫ — две фото одних и тех же
(или той же модели) джинсов, как шахматка в рефе (LDN + LDN, blossom + blossom). Обложка — одиночные кадры: девушка
в мешковатом дениме ночью со вспышкой, лицо отвёрнуто / закрыто.
Метки как на листах: «S2» — затравка строки 2, «2.4» — 4-й «похожий» в строке 2.

  python pick_1390_pairs.py            # → output/1390_pick2/<слот>/ (оригиналы) + _pairs_overview.jpg + sigs.txt
  python pick_1390_pairs.py --ids output/1390_pick2/ids.txt   # + id пинов (из браузера) → PICKS.md со ссылками
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
PINS = ROOT / "output" / "1390_pins"
OUT = ROOT / "output" / "1390_pick2"

COVER = ["0.2", "S0", "0.3", "0.6", "2.4"]
PAIRS = {
    "embroidered": [("S0", "S1", "Schuze blossom (как в рефе)"), ("S6", "6.2", "Evisu"),
                    ("S5", "5.6", "True Religion"), ("S3", "3.1", "сакура на тёмных")],
    "graphic": [("S0", "0.1", "Jaded London LDN (как в рефе)"), ("S6", "6.1", "Christian Audigier"),
                ("S4", "4.1", "Ed Hardy, белая надпись"), ("S5", "5.1", "Ed Hardy, тату-принт")],
    "wide_dark": [("S1", "1.1", "тёмные широкие"), ("2.5", "2.2", "тёмные широкие, по пояс"),
                  ("S0", "0.2", "чёрные широкие")],
    "vintage_wash": [("S0", "0.4", "Levi's, карманы сзади"), ("S2", "2.2", "Levi's 501 сзади"),
                     ("S1", "1.2", "винтажная варка")],
    "patchwork": [("S2", "2.1", "заплатки-звёзды"), ("S4", "4.8", "полоса пейсли сбоку"),
                  ("S1", "1.3", "заплатки на карманах")],
    "cargo": [("S2", "2.4", "денимные карго"), ("S0", "2.1", "чёрные карго"), ("S3", "S1", "карго с карманами")],
    "studded": [("S0", "0.1", "кресты из заклёпок"), ("S3", "3.1", "Union Jack + заклёпки"),
                ("1.8", "0.4", "череп из заклёпок"), ("S5", "5.1", "Miss Me")],
    "raw_denim": [("S3", "3.1", "тот же человек, те же джинсы"), ("S2", "2.1", "разложены на полу"),
                  ("S1", "1.1", "тёмные сырые, ночь"), ("S0", "0.6", "карман крупно")],
}
LABEL = {"cover": "1 обложка", "embroidered": "2 embroidered", "graphic": "3 graphic print", "wide_dark": "4 wide leg dark",
         "vintage_wash": "5 vintage wash", "patchwork": "6 patchwork", "cargo": "7 cargo", "studded": "8 studded",
         "raw_denim": "9 raw denim"}


def resolve(slot: str, lab: str) -> dict:
    summ = json.loads((PINS / slot / "pairs.json").read_text(encoding="utf-8"))
    seeds = list(summ)
    rank_ = {r["pin_id"]: r for r in json.loads((PINS / slot / "rank.json").read_text(encoding="utf-8"))}
    if lab.startswith("S"):
        r = rank_[seeds[int(lab[1:])]]
        return {"label": lab, "pin_id": r["pin_id"], "likes": r["likes"], "saves": r["saves"], "sig": r["sig"]}
    row, n = map(int, lab.split("."))
    it = next(i for i in summ[seeds[row]] if i["n"] == n)
    return {"label": lab, **it}


def original(cli: httpx.Client, sig: str) -> Image.Image:
    for ext in ("jpg", "png", "webp"):
        try:
            r = cli.get(f"https://i.pinimg.com/originals/{sig[:2]}/{sig[2:4]}/{sig[4:6]}/{sig}.{ext}")
            if r.status_code == 200:
                return ImageOps.exif_transpose(Image.open(io.BytesIO(r.content))).convert("RGB")
        except Exception:
            pass
    return Image.open(PINS / "_thumbs" / f"{sig}.jpg").convert("RGB")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", type=Path, help="строки «первые 10 знаков хеша|id» из браузера")
    a = ap.parse_args()
    ids = {}
    if a.ids:
        ids = dict(ln.split("|") for ln in a.ids.read_text(encoding="utf-8").split())
    plan = {"cover": [[resolve("cover", lab)] for lab in COVER]}
    for slot, prs in PAIRS.items():
        plan[slot] = [[resolve(slot, x), resolve(slot, y), note] for x, y, note in prs]
    if OUT.exists() and not a.ids:
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    cli = httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    sigs = []
    md = ["# 1390 — кандидаты: пары фото одних джинсов (как шахматка в рефе), обложка — одиночные", ""]
    for slot, groups in plan.items():
        (OUT / slot).mkdir(exist_ok=True)
        md += [f"## {LABEL[slot]}", "", "| № | фото | лайки | сохранения | что |", "|---|---|---|---|---|"]
        for k, g in enumerate(groups, 1):
            note = g[-1] if isinstance(g[-1], str) else ""
            for j, it in enumerate(x for x in g if isinstance(x, dict)):
                sigs.append(it["sig"])
                name = f"{k}{'ab'[j] if slot != 'cover' else ''}.jpg"
                f = OUT / slot / name
                if not f.exists():
                    original(cli, it["sig"]).save(f, quality=95)
                pid = it.get("pin_id") or ids.get(it["sig"][:10], "")
                link = f"[{pid}](https://www.pinterest.com/pin/{pid}/)" if pid else it["sig"][:10]
                md.append(f"| {k}{'ab'[j] if slot != 'cover' else ''} | {link} | {it['likes']} | {it['saves']} | {note} |")
        md.append("")
    (OUT / "PICKS.md").write_text("\n".join(md), encoding="utf-8")
    (OUT / "sigs.txt").write_text(" ".join(dict.fromkeys(sigs)), encoding="utf-8")
    (OUT / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")

    # лист: строка на слайд; пары — две фото вплотную, между парами зазор
    tw, th, gap, top = 132, 235, 18, 34
    font = ImageFont.truetype("arial.ttf", 13)
    fb = ImageFont.truetype("arialbd.ttf", 19)
    W = 4 * (2 * tw + gap) + 10
    s = Image.new("RGB", (W, len(plan) * (th + top + 22)), (20, 20, 20))
    d = ImageDraw.Draw(s)
    y = 0
    for slot, groups in plan.items():
        d.text((6, y + 6), LABEL[slot], fill=(255, 255, 255), font=fb)
        y += top
        x = 4
        for k, g in enumerate(groups, 1):
            items = [it for it in g if isinstance(it, dict)]
            for j, it in enumerate(items):
                im = Image.open(OUT / slot / f"{k}{'ab'[j] if slot != 'cover' else ''}.jpg").convert("RGB")
                s.paste(ImageOps.fit(im, (tw - 2, th), centering=(0.5, 0.45)), (x, y))
                d.rectangle((x, y + th - 17, x + tw - 2, y + th), fill=(0, 0, 0))
                d.text((x + 3, y + th - 16), f"L{it['likes']} S{it['saves'] // 1000}k", fill=(255, 230, 80), font=font)
                x += tw
            if slot != "cover":
                d.text((x - 2 * tw + 2, y + th + 3), f"{k}. {g[-1]}"[:34], fill=(170, 220, 255), font=font)
                x += gap
        y += th + 22
    s.save(OUT / "_pairs_overview.jpg", quality=88)
    print(f"готово → {OUT}  (фото {len(set(sigs))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
