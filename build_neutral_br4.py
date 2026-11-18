#!/usr/bin/env python3
"""
BR «жиза», партия 4 (айди 10001, ещё 30 отдельно): тексты neutral_br4_texts.py, по одному ролику на текст, номера 101–130
(продолжают партию 3). Формат как в build_neutral_br3 (спокойный UGC-клип, белый TikTok-текст по центру, списки плашками,
музыка рефа, длина = длина рефа), но кадр собирается ЦЕЛИКОМ на видеокарте (CLAUDE.md, core/gpu_ffmpeg.py):
  h264_cuvid с обрезкой 1–4 % (у каждого ролика свой лёгкий зум и сдвиг) → trim → scale_cuda в yuv420p →
  overlay_cuda текста (RGBA-слой, PNG распакован один раз) → NVENC; одновременно — через core.gpu_slots.gpu_slot().
После overlay_cuda кадр копируется в память (hwdownload) — иначе наш ffmpeg кодирует ширину 1088 вместо 1080
(контекст кадров после наложения на основу из h264_cuvid; проверено 13.11). Зеркало и eq на видеокарте не делаются — поэтому без зеркала и без тёмных клипов 5664/5668 (им нужен eq).

  python build_neutral_br4.py --only 101,128 --out output/_work/br4_test
  python build_neutral_br4.py --jobs 3        # → output/br_neutral_10001_30 + _youtube_meta.txt
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_followspy_walls as F  # noqa: E402
from core import gpu_ffmpeg as G  # noqa: E402
from core.gpu_slots import gpu_slot  # noqa: E402
from neutral_br4_texts import REFS, STORIES  # noqa: E402

ID = "10001"
N0 = 101                                               # номера продолжают партию 3 (br_001…br_100)
W, H, FPS = 1080, 1920, 30
PROXY = ROOT / "downloads" / "gw_wall2" / "proxy"
OUT = ROOT / "output" / f"br_neutral_{ID}_30"
WORK = ROOT / "output" / "_work" / "br_neutral_br4"
PEOPLE = {
    "girlA": ["IMG_5663", "IMG_5665", "IMG_5669", "IMG_5670"],
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
    rnd = random.Random(10004)
    uses = {c: 0 for cl in PEOPLE.values() for c in cl}
    pu = {p: 0 for p in PEOPLE}
    rows, last = [], None
    for j, (s, ref) in enumerate(zip(STORIES, REFS)):
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
        start = a + (room * rnd.uniform(0.05, 0.95) if room > 0 else 0)
        n = N0 + j
        rows.append(dict(name=f"br_{n:03d}", n=n, k=j, ref=ref, text=s["text"], person=p, clip=c,
                         start=round(min(start, b - d - 0.05), 2), dur=round(d, 3),
                         zoom=round(rnd.uniform(1.01, 1.04), 4), px=round(rnd.random(), 3), py=round(rnd.random(), 3)))
    return rows


def render_gpu(r: dict, out: Path) -> Path:
    dest = out / f"{r['name']}_{ID}.mp4"
    if dest.exists():
        return dest
    tmp = WORK / r["name"]
    tmp.mkdir(parents=True, exist_ok=True)
    wall = tmp / "wall.png"
    (F.plates_png if isinstance(r["text"], list) else F.wall_png)(r["text"], wall)
    cw, ch = W / r["zoom"], H / r["zoom"]                     # лёгкий зум: обрезка в распаковщике (чётные числа)
    crop = ((W - cw) * r["px"], (H - ch) * r["py"], cw, ch)
    nf = round(r["dur"] * FPS)
    d = r["dur"]
    # 13.11: кадры видео — в обычной памяти (gpu_input режет и масштабирует в распаковщике), на видеокарту — один раз
    # перед overlay_cuda (держать распакованные кадры на видеокарте нельзя — core/gpu_ffmpeg.py, «ГЛАВНОЕ»)
    fc = (f"[0:v]trim=start={r['start']:.3f}:duration={d:.3f},setpts=PTS-STARTPTS,setsar=1,format=yuv420p,hwupload_cuda[b];"
          f"{G.layer(1, 0, nf, 'w')};[b][w]overlay_cuda=0:0,hwdownload,format=yuv420p[v];"
          f"[2:a]atrim=end={d:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={max(0, d - 0.3):.3f}:d=0.3,"
          f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[a]")
    part = tmp / "part.mp4"
    with gpu_slot():
        subprocess.run(["ffmpeg", "-v", "error", "-y", *G.gpu_input(PROXY / f"{r['clip']}.mp4", crop=crop, resize=(W, H)),
                        "-i", str(wall), "-i", str(F.REFS / f"{r['ref']}.mp4"),
                        "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-frames:v", str(nf), "-t", f"{d:.3f}",
                        *G.NVENC, "-c:a", "aac", "-b:a", "160k", *G.CLEAN, str(part)], check=True)
    part.replace(dest)
    wall.unlink()
    tmp.rmdir()
    return dest


def _render(job: tuple[dict, str]) -> str:
    r, out = job
    return str(render_gpu(r, Path(out)))


def write_meta(out: Path, rows: list[dict]) -> None:
    rng = random.Random(10005)
    blocks = []
    for r in rows:
        s = STORIES[r["k"]]
        f = out / f"{r['name']}_{ID}.mp4"
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
    ap.add_argument("--only", default="", help="номера через запятую: 101,128")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--plan", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = plan()
    if a.plan:
        for r in rows:
            print(r["name"], r["person"], r["clip"], r["ref"], r["start"], r["dur"], r["zoom"])
        return 0
    if a.only:
        keep = {int(x) for x in a.only.split(",")}
        rows = [r for r in rows if r["n"] in keep]
    a.out.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(min(a.jobs, 3)) as ex:
        for dest in ex.map(_render, [(r, str(a.out)) for r in rows]):
            print(" ", Path(dest).name, flush=True)
    (WORK / f"manifest_{a.out.name}.json").write_text(json.dumps([{k: v for k, v in r.items() if k != "text"} for r in rows],
                                                                 indent=1, ensure_ascii=False), encoding="utf-8")
    write_meta(a.out, rows)
    print(f"готово: {len(rows)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
