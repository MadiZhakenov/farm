#!/usr/bin/env python3
"""
BR «жиза», партия 3 (айди 10001): 100 новых текстволлов на португальском без продукта (neutral_br3_texts.py), по одному
ролику на текст. Схема рендера — build_followspy_walls (спокойный UGC-клип, белый TikTok-текст по центру, списки —
плашками, музыка рефа, длина = длина рефа). Кадры не уникализируем: у каждого ролика свой отрезок клипа и зеркало.
Люди — все 5 из базы (девушка A, девушка B, парень, девушка в мятной комнате, девушка с пучком), соседние ролики —
разные люди; тексты в женском роде — только на девушках. Источники — 1080p-прокси downloads/gw_wall2/proxy.

  python build_neutral_br3.py --only 1,52,93 --out output/_work/br3_test
  python build_neutral_br3.py --jobs 5        # → output/br_neutral_10001_100 + _youtube_meta.txt
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_followspy_walls as F  # noqa: E402
from neutral_br3_texts import REFS, STORIES  # noqa: E402

ID = "10001"
PROXY = ROOT / "downloads" / "gw_wall2" / "proxy"
F.SRC = {"A": PROXY, "B": PROXY}                      # прокси уже 1080p 30 к/с и SDR (HLG снят при создании)
F.HLG = ""
F.FOLDER = {3: ""}
OUT = ROOT / "output" / f"br_neutral_{ID}_100"
PEOPLE = {
    "girlA": ["IMG_5663", "IMG_5664", "IMG_5665", "IMG_5668", "IMG_5669", "IMG_5670"],
    "girlB": ["IMG_8101", "IMG_8102", "IMG_8103", "IMG_8104", "IMG_8105", "IMG_8107", "IMG_8108"],
    "guy": ["IMG_2937", "IMG_2938", "IMG_2939"],
    "mint": ["IMG_5704", "IMG_5705", "IMG_5651"],
    "bun": ["IMG_8111", "IMG_8114", "IMG_8093", "IMG_8094"],
}
CACHES = [ROOT / "downloads" / "followspy" / "usable_ranges.json", ROOT / "downloads" / "followspy" / "usable_ranges2.json"]
COMMON_HASH = ["#humor", "#quemnunca", "#vidareal", "#brasil"]
COMMON_TAGS = ["humor", "quem nunca", "vida real", "relatable", "shorts", "brasil"]


def plan() -> list[dict]:
    usable = {}
    for c in CACHES:
        usable.update(json.loads(c.read_text(encoding="utf-8")))
    rnd = random.Random(10001)
    uses = {c: 0 for cl in PEOPLE.values() for c in cl}
    pu = {p: 0 for p in PEOPLE}
    rows, last = [], None
    for j, (s, ref) in enumerate(zip(STORIES, REFS), 1):
        d = F.dur(F.REFS / f"{ref}.mp4")
        fits = {p: [c for c in cl if usable[c][1] - usable[c][0] >= d + 0.2] for p, cl in PEOPLE.items()}
        cand = [p for p in PEOPLE if fits[p] and p != last and not (s["g"] == "f" and p == "guy")]
        p = min(cand, key=lambda x: (pu[x] / len(PEOPLE[x]), rnd.random()))
        c = min(fits[p], key=lambda x: (uses[x], rnd.random()))
        a, b = usable[c]
        u = uses[c]
        uses[c] += 1
        pu[p] += 1
        last = p
        room = (b - a) - d
        start = a + (room * (0.05 + 0.3 * (u % 4)) if room > 0 else 0)
        rows.append(dict(name=f"br_{j:03d}", part=3, n=j, ref=ref, text=s["text"], group="A", person=p, clip=c,
                         start=round(min(start, b - d - 0.05), 2), dur=round(d, 3), mirror=u % 2))
    return rows


def _render(job: tuple[dict, str, str]) -> str:
    r, out, work = job
    src = F.render(r, Path(out), Path(work))
    dest = src.with_name(f"{r['name']}_{ID}.mp4")
    src.replace(dest)
    return str(dest)


def write_meta(out: Path) -> None:
    rng = random.Random(10002)
    blocks = []
    for j, s in enumerate(STORIES, 1):
        f = out / f"br_{j:03d}_{ID}.mp4"
        if not f.exists():
            continue
        h = [s["tag"]] + rng.sample([x for x in COMMON_HASH if x != s["tag"]], 2)
        rng.shuffle(h)
        t = list(dict.fromkeys(s["tags"] + COMMON_TAGS))
        rng.shuffle(t)
        blocks.append(f"===== {f.name} =====\nTITLE: {s['title']}\n\nDESCRIPTION:\n{s['desc']}\n\n{' '.join(h + ['#shorts'])}\n\n{ID}\n\n"
                      f"TAGS: {', '.join(t)}\n")
    (out / "_youtube_meta.txt").write_text("\n".join(blocks), encoding="utf-8")
    print(len(blocks), "описаний →", out / "_youtube_meta.txt", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="номера через запятую: 1,52,93")
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--plan", action="store_true", help="только показать раскладку")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = plan()
    if a.plan:
        for r in rows:
            print(r["name"], r["person"], r["clip"], r["ref"], r["start"], r["dur"], "зеркало" if r["mirror"] else "")
        return 0
    if a.only:
        keep = {int(x) for x in a.only.split(",")}
        rows = [r for r in rows if r["n"] in keep]
    work = a.out / "_work"
    work.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(a.jobs) as ex:
        for dest in ex.map(_render, [(r, str(a.out), str(work)) for r in rows]):
            print(" ", Path(dest).name, flush=True)
    for f in work.glob("*.png"):
        f.unlink()
    work.rmdir()
    (a.out / "manifest.json").write_text(json.dumps([{k: v for k, v in r.items() if k != "text"} for r in rows], indent=1,
                                                   ensure_ascii=False), encoding="utf-8")
    write_meta(a.out)
    print(f"готово: {len(rows)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
