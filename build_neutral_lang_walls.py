#!/usr/bin/env python3
"""
Нейтральные текстволлы «жиза» (айди нет, срочно 2026-11-06) на корейском (KO) и бразильском португальском (PT):
бытовые узнаваемые ситуации без продуктов (FollowSpy-истории юзер забраковал как не нейтральные), схема
build_de_neutral_walls (10 сюжетов × 5 версий, клипы девушек A/B, музыка и длина рефов followspy по порядку),
переносы по смыслу. Исходники — 1080p-прокси downloads/gw_wall2/proxy (B уже тонмаплен из HLG) — быстро.
Корейский — шрифт Malgun Gothic Bold (в TikTok Sans нет хангыля).

  python build_neutral_lang_walls.py --lang ko --jobs 5   # → output/ko_neutral_50/ko_NN_vK_noid.mp4
  python build_neutral_lang_walls.py --lang pt --jobs 5   # → output/br_neutral_50/br_NN_vK_noid.mp4
  python build_neutral_lang_walls.py --lang de --jobs 5   # → output/de_neutral_120/de_NN_vK_noid.mp4 (20 сюжетов × 6)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
LANG = os.environ.get("NEUTRAL_LANG", "pt")
import build_followspy_walls as F  # noqa: E402
import build_de_neutral_walls as DN  # noqa: E402
from core import renderer as R  # noqa: E402

PROXY = ROOT / "downloads" / "gw_wall2" / "proxy"
F.SRC = {"A": PROXY, "B": PROXY}
F.HLG = ""                                          # B в прокси уже тонмаплен


def link_proxies() -> None:
    """F.render берёт <clip>.MOV из F.SRC — даём прокси .mp4 имя .MOV (жёсткая ссылка, один раз до пула)."""
    for src in PROXY.glob("*.mp4"):
        link = src.with_suffix(".MOV")
        if not link.exists():
            os.link(src, link)


if LANG == "ko":
    _KO = "C:/Windows/Fonts/malgunbd.ttf"
    R._load_font = lambda size: ImageFont.truetype(_KO, size)   # noqa: E731

from neutral_lang_texts import KO, PT  # noqa: E402  («жиза», 10 сюжетов KO/PT)
from neutral_de_texts import DE as DE_NEUTRAL  # noqa: E402  («жиза», 20 сюжетов × 6 версий)
from neutral_en_texts import EN as EN_NEUTRAL  # noqa: E402  («жиза», 100 сюжетов × 1 версия)
CFG = {"ko": (KO, "ko", ROOT / "output" / "ko_neutral_50"), "pt": (PT, "br", ROOT / "output" / "br_neutral_50"),
       "de": (DE_NEUTRAL, "de", ROOT / "output" / "de_neutral_120"),
       "en": (EN_NEUTRAL, "en", ROOT / "output" / "en_neutral_100")}


def _render(job: tuple[dict, str, str]) -> str:
    r, out, work = job
    return str(F.render(r, Path(out), Path(work)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=sorted(CFG), required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    if LANG != a.lang:                                  # шрифт ставится при импорте (воркеры) — по переменной окружения
        os.environ["NEUTRAL_LANG"] = a.lang
        return os.spawnv(os.P_WAIT, sys.executable, [sys.executable, *sys.argv])
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    link_proxies()
    texts, prefix, out = CFG[a.lang]
    out = a.out or out
    DN.DE = texts
    DN.VERSIONS = {"de": 6, "en": 1}.get(a.lang, 5)
    rows = DN.plan()
    for r in rows:
        r["name"] = r["name"].replace("de_", f"{prefix}_", 1)
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
    print(f"готово: {len(rows)} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
