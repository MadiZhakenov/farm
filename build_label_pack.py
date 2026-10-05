#!/usr/bin/env python3
"""
Пакет кадров для ручной разметки «живое / сток / ИИ-рендер».

Источник — замеры probe_query_liveness.py (pins.csv + search_cache.json):
  borderline   — живость 0.25–0.65 (здесь модель сомневается), поровну по
                 корзинам, не больше 2 кадров с одного запроса
  ai_suspect   — похожие на 3D-рендер / ИИ по zero-shot SigLIP
  pinterest_ai — пины, которые сам Pinterest пометил как ИИ (проверка метки
                 и примеры для детектора)
Картинки скачиваются крупнее превью (до 900 px).

  python build_label_pack.py --src out/query_liveness_v2 out/filler_bank_probe \\
      out/query_liveness_20261005 --n-border 260 --n-ai 100 --n-pin-ai 40
  python label_frames.py out/label_pack_<дата>      # разметка в браузере
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

AI_PROMPTS = (
    "a 3d render",
    "an AI generated image",
    "a computer generated interior visualization",
    "a digital illustration",
    "a CGI product render",
)
REAL_PROMPTS = (
    "a real photo taken with a phone",
    "an amateur snapshot",
    "a candid photograph",
)
BINS = ((0.25, 0.35), (0.35, 0.45), (0.45, 0.55), (0.55, 0.65))


def load_sources(srcs: list[Path]) -> tuple[dict, dict]:
    """pin → {ugc, search, src}; pin → мета пина (url, is_ai)."""
    frames: dict[str, dict] = {}
    metas: dict[str, dict] = {}
    for src in srcs:
        cache = src / "search_cache.json"
        if cache.exists():
            for q, pins in json.loads(cache.read_text(encoding="utf-8")).items():
                for p in pins:
                    m = metas.setdefault(str(p["pin_id"]), dict(p))
                    m.setdefault("search", q)
        pins_csv = src / "pins.csv"
        if pins_csv.exists():
            for r in csv.DictReader(pins_csv.open(encoding="utf-8")):
                pid = str(r["pin_id"])
                frames.setdefault(pid, {
                    "pin_id": pid, "ugc": float(r["ugc"]),
                    "search": r.get("search") or r.get("final") or r.get("query") or "",
                    "thumb": str(src / "thumbs" / f"{pid}.jpg"),
                })
    return frames, metas


def ai_suspect_scores(frames: dict) -> dict[str, float]:
    from core.taste_embedder import get_embedder

    emb = get_embedder()
    pids = [p for p, f in frames.items() if Path(f["thumb"]).exists()]
    ta = emb.embed_texts(list(AI_PROMPTS))
    tr = emb.embed_texts(list(REAL_PROMPTS))
    out: dict[str, float] = {}
    for i in range(0, len(pids), 256):
        chunk = pids[i:i + 256]
        ims = [Image.open(frames[p]["thumb"]).convert("RGB") for p in chunk]
        v = emb.embed_images(ims, cache_keys=chunk)
        score = (v @ ta.T).max(axis=1) - (v @ tr.T).max(axis=1)
        out.update({p: float(s) for p, s in zip(chunk, score)})
    return out


def pick(frames: dict, ai: dict, metas: dict, n_border: int, n_ai: int, n_pin_ai: int,
         rng: random.Random) -> list[dict]:
    per_search: dict[str, int] = defaultdict(int)
    chosen: list[dict] = []
    taken: set[str] = set()

    def take(f: dict, source: str) -> bool:
        if f["pin_id"] in taken or per_search[f["search"]] >= 2:
            return False
        taken.add(f["pin_id"])
        per_search[f["search"]] += 1
        chosen.append({**f, "source": source, "ai_suspect": round(ai.get(f["pin_id"], 0.0), 4)})
        return True

    pool = list(frames.values())
    rng.shuffle(pool)
    per_bin = n_border // len(BINS)
    for lo, hi in BINS:
        k = 0
        for f in pool:
            if k >= per_bin:
                break
            if lo <= f["ugc"] < hi and take(f, "borderline"):
                k += 1
    k = 0
    for f in sorted(pool, key=lambda f: -ai.get(f["pin_id"], -9)):
        if k >= n_ai:
            break
        if take(f, "ai_suspect"):
            k += 1
    flagged = [m for p, m in metas.items() if m.get("is_ai") is True and p not in taken]
    rng.shuffle(flagged)
    for m in flagged[:n_pin_ai]:
        chosen.append({"pin_id": str(m["pin_id"]), "ugc": None, "search": m.get("search", ""),
                       "thumb": "", "source": "pinterest_ai", "ai_suspect": None})
    rng.shuffle(chosen)
    return chosen


def _big_url(url: str) -> str:
    for size in ("/236x/", "/474x/", "/564x/"):
        if size in url:
            return url.replace(size, "/736x/")
    return url


async def download(chosen: list[dict], metas: dict, dest: Path) -> None:
    sem = asyncio.Semaphore(16)

    async def one(c: httpx.AsyncClient, row: dict) -> None:
        m = metas.get(row["pin_id"], {})
        urls = [u for u in (_big_url(m.get("image_url") or ""), m.get("orig_url"), m.get("image_url")) if u]
        out = dest / f"{row['pin_id']}.jpg"
        async with sem:
            for u in urls:
                try:
                    r = await c.get(u)
                    if r.status_code == 200 and r.content:
                        im = Image.open(io.BytesIO(r.content)).convert("RGB")
                        im.thumbnail((900, 900))
                        im.save(out, quality=88)
                        row["file"] = out.name
                        return
                except Exception:
                    continue
        if row.get("thumb") and Path(row["thumb"]).exists():  # запасной вариант — превью
            Image.open(row["thumb"]).convert("RGB").save(out, quality=88)
            row["file"] = out.name

    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"}) as c:
        await asyncio.gather(*(one(c, r) for r in chosen))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, nargs="+", required=True)
    ap.add_argument("--n-border", type=int, default=260)
    ap.add_argument("--n-ai", type=int, default=100)
    ap.add_argument("--n-pin-ai", type=int, default=40)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    out = args.out or ROOT / "out" / f"label_pack_{datetime.now():%Y%m%d_%H%M}"
    (out / "imgs").mkdir(parents=True, exist_ok=True)
    frames, metas = load_sources(args.src)
    print(f"кадров с живостью: {len(frames)} · пинов в кэше поиска: {len(metas)}")
    ai = ai_suspect_scores(frames)
    chosen = pick(frames, ai, metas, args.n_border, args.n_ai, args.n_pin_ai, random.Random(args.seed))
    asyncio.run(download(chosen, metas, out / "imgs"))
    chosen = [r for r in chosen if r.get("file")]
    for r in chosen:
        r.pop("thumb", None)
    (out / "pack.json").write_text(json.dumps(chosen, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter

    print(f"пакет: {len(chosen)} кадров {dict(Counter(r['source'] for r in chosen))} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
