#!/usr/bin/env python3
"""
Нейтральные текстволлы KO/PT, партия 2: сюжеты 11–20 (neutral_lang_texts2.py) × 3 версии = 30 на язык, новые люди из базы UGC:
парень (gw_gotjob), девушка в мятной комнате (gw_gotjob2 srcA, tiers2), девушка с пучком (gw_gotjob2 srcB, tiers2). У каждого сюжета — три разных человека.
Источники сначала превращаются в 1080p 30 к/с (HLG → tonemap hable npl 120), дальше только прокси. Схема рендера — build_followspy_walls.

  python build_neutral_lang_walls2.py --proxies
  python build_neutral_lang_walls2.py --lang pt --only br_11_v1,br_20_v2 --out output/_work/neutral2_test
  python build_neutral_lang_walls2.py --lang pt --jobs 4       # → output/br_neutral_30 + _youtube_meta.txt
  python build_neutral_lang_walls2.py --lang ko --jobs 4       # → output/ko_neutral_30 + _youtube_meta.txt
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
LANG = os.environ.get("NEUTRAL_LANG", "pt")
import build_followspy_walls as F  # noqa: E402
from core import renderer as R  # noqa: E402
from neutral_lang_texts2 import KO2, META_KO, META_PT, PT2  # noqa: E402

PROXY = ROOT / "downloads" / "gw_wall2" / "proxy"
F.SRC = {"A": PROXY, "B": PROXY}
F.HLG = ""
F.FOLDER = {3: ""}
D = ROOT / "downloads"
GROUPS = {
    "guy": [D / "gw_gotjob/src/IMG_2937.MOV", D / "gw_gotjob/src/IMG_2938.MOV", D / "gw_gotjob/src/IMG_2939.MOV"],
    "mint": [D / "gw_gotjob2/srcA/IMG_5704.MOV", D / "gw_gotjob2/srcA/IMG_5705.MOV", D / "gw_tiers2/srcA/IMG_5651.MOV"],
    "bun": [D / "gw_gotjob2/srcB/IMG_8111.MOV", D / "gw_gotjob2/srcB/IMG_8114.MOV", D / "gw_tiers2/srcB/IMG_8093.MOV", D / "gw_tiers2/srcB/IMG_8094.MOV"],
}
ORDER = ("guy", "mint", "bun")
VERSIONS = 3
CACHE = ROOT / "downloads" / "followspy" / "usable_ranges2.json"
HLG_VF = "zscale=t=linear:npl=120,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,"

if LANG == "ko":
    _KO = "C:/Windows/Fonts/malgunbd.ttf"
    R._load_font = lambda size: ImageFont.truetype(_KO, size)   # noqa: E731

CFG = {"ko": (KO2, "ko", ROOT / "output" / "ko_neutral_30", META_KO), "pt": (PT2, "br", ROOT / "output" / "br_neutral_30", META_PT)}


def is_hlg(p: Path) -> bool:
    return "arib-std-b67" in subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_transfer", "-of", "csv=p=0", str(p)],
                                           capture_output=True, text=True).stdout


def make_proxy(src: Path) -> str:
    dest = PROXY / f"{src.stem}.mp4"
    link = dest.with_suffix(".MOV")
    if not dest.exists():
        vf = (HLG_VF if is_hlg(src) else "") + "scale=1080:1920:flags=lanczos:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,format=yuv420p"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", vf, "-an", "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "18",
                        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", str(dest)], check=True)
    if not link.exists():
        os.link(dest, link)
    return src.stem


def proxies() -> None:
    PROXY.mkdir(parents=True, exist_ok=True)
    clips = [p for g in GROUPS.values() for p in g]
    with ThreadPoolExecutor(3) as ex:
        for name in ex.map(make_proxy, clips):
            print("  прокси", name, flush=True)
    F.WL.SRC = PROXY
    rng = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    for p in clips:
        if p.stem not in rng:
            rng[p.stem] = list(F.WL.usable_range(p.stem))
    CACHE.write_text(json.dumps(rng), encoding="utf-8")
    print(rng, flush=True)


def plan(texts: list, prefix: str) -> list[dict]:
    """10 сюжетов × 3 версии: у сюжета — три разных человека; внутри группы — наименее использованный клип, чьё окно не короче музыки.
    Повтор клипа — другое окно и зеркало."""
    usable = json.loads(CACHE.read_text(encoding="utf-8"))
    rows, uses, rnd = [], {p.stem: 0 for g in GROUPS.values() for p in g}, random.Random(1402 if prefix == "br" else 1403)
    for j, (ref, text) in enumerate(texts):
        n = 11 + j
        d = F.dur(F.REFS / f"{ref}.mp4")
        start_g = j % 3
        for k in range(VERSIONS):
            g = ORDER[(start_g + k) % 3]
            ok = [p.stem for p in GROUPS[g] if usable[p.stem][1] - usable[p.stem][0] >= d + 0.2]
            c = min(ok, key=lambda x: (uses[x], rnd.random()))
            a, b = usable[c]
            u = uses[c]
            uses[c] += 1
            room = (b - a) - d
            start = a + (room * (0.05 + 0.3 * (u % 4)) if room > 0 else 0)
            rows.append(dict(name=f"{prefix}_{n:02d}_v{k + 1}", part=3, n=n, ref=ref, text=text, group="A", clip=c, start=round(min(start, b - d - 0.05), 2), dur=round(d, 3), mirror=(u // 2) % 2))
    return rows


def _render(job: tuple[dict, str, str]) -> str:
    r, out, work = job
    return str(F.render(r, Path(out), Path(work)))


def write_meta(out: Path, prefix: str, meta: dict) -> None:
    rng = random.Random(1405)
    blocks = []
    for f in sorted(out.glob(f"{prefix}_*_v*_noid.mp4")):
        n, k = int(f.name.split("_")[1]), int(f.name.split("_v")[1].split("_")[0])
        titles, descs, hashtags, tags = meta[n]
        h, t = hashtags[:], tags[:]
        rng.shuffle(h)
        rng.shuffle(t)
        blocks.append(f"===== {f.name} =====\nTITLE: {titles[k - 1]}\n\nDESCRIPTION:\n{descs[(k + n) % len(descs)]}\n\n{' '.join(h)}\n\nTAGS: {', '.join(t)}\n")
    (out / "_youtube_meta.txt").write_text("\n".join(blocks), encoding="utf-8")
    print(len(blocks), "описаний →", out / "_youtube_meta.txt", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=sorted(CFG))
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--proxies", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.proxies:
        proxies()
        return 0
    if LANG != a.lang:
        os.environ["NEUTRAL_LANG"] = a.lang
        return os.spawnv(os.P_WAIT, sys.executable, [sys.executable, *sys.argv])
    texts, prefix, out, meta = CFG[a.lang]
    out = a.out or out
    rows = plan(texts, prefix)
    if a.only:
        keep = set(a.only.split(","))
        rows = [r for r in rows if r["name"] in keep]
    work = out / "_work"
    work.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(a.jobs) as ex:
        for dest in ex.map(_render, [(r, str(out), str(work)) for r in rows]):
            print(" ", Path(dest).name, flush=True)
    for f in work.glob("*.png"):
        f.unlink()
    work.rmdir()
    (out / "manifest.json").write_text(json.dumps([{k: v for k, v in r.items() if k != "text"} for r in rows], indent=1, ensure_ascii=False), encoding="utf-8")
    if not a.only:
        write_meta(out, prefix, meta)
    print(f"готово: {len(rows)} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
