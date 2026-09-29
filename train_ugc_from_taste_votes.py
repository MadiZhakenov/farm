#!/usr/bin/env python3
"""
Train UGC live-vs-stock from taste_votes HTML export.

Labels:
  keep  → live  (carousel-worthy phone vibe)
  stock → stock
  wrong → stock  (wrong scene still trains "not keep")

Merges with existing probe human_votes, backups previous pkl.

Usage:
  python train_ugc_from_taste_votes.py c:/Users/User/Downloads/taste_votes_run_20260925_155018.json
  python train_ugc_from_taste_votes.py out/run_20260925_155018/taste_votes_....json
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.ugc_classifier import MODEL_PATH, get_ugc_live_classifier  # noqa: E402
from train_ugc_from_probe import collect_samples  # noqa: E402

OUT = ROOT / "out"
# SigLIP input is 224; keep a little headroom without holding full-res JPEGs.
_THUMB = 384


def _load_thumb(fpath: Path) -> Image.Image:
    im = Image.open(fpath).convert("RGB")
    im.load()
    im.thumbnail((_THUMB, _THUMB), Image.Resampling.BICUBIC)
    return im


def load_taste_votes(path: Path) -> tuple[list[Image.Image], list[Image.Image], dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    run_name = str(data.get("run") or "")
    run_dir = OUT / run_name if run_name else path.parent
    if not run_dir.is_dir():
        # votes file may live in Downloads — run is under out/
        alt = OUT / run_name
        if alt.is_dir():
            run_dir = alt
        else:
            raise SystemExit(f"run dir not found for {run_name!r}")

    live: list[Image.Image] = []
    stock: list[Image.Image] = []
    skipped = 0
    for row in data.get("detail") or []:
        human = (row.get("human") or "").strip().lower()
        if human not in ("keep", "stock", "wrong"):
            skipped += 1
            continue
        rel = str(row.get("img") or "")
        fpath = run_dir / rel
        if not fpath.is_file():
            print(f"  miss {rel}")
            skipped += 1
            continue
        try:
            im = _load_thumb(fpath)
        except Exception as exc:
            print(f"  bad image {rel}: {exc}")
            skipped += 1
            continue
        if human == "keep":
            live.append(im)
        else:
            stock.append(im)  # stock + wrong
    stats = {
        "run_dir": str(run_dir),
        "live": len(live),
        "stock": len(stock),
        "skipped": skipped,
        "marked": data.get("marked"),
    }
    return live, stock, stats


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python train_ugc_from_taste_votes.py <taste_votes.json>")
        return 2
    votes_path = Path(sys.argv[1]).expanduser().resolve()
    if not votes_path.is_file():
        print(f"not found: {votes_path}")
        return 2

    # copy into run for archive
    live, stock, st = load_taste_votes(votes_path)
    print(
        f"[taste] keep/live={st['live']} stock+wrong={st['stock']} "
        f"skip={st['skipped']} run={st['run_dir']}"
    )
    dest = Path(st["run_dir"]) / votes_path.name
    if dest.resolve() != votes_path.resolve():
        try:
            shutil.copy2(votes_path, dest)
            print(f"[taste] archived → {dest}")
        except Exception as exc:
            print(f"[taste] archive skip: {exc}")

    # merge earlier taste_votes JSONs under out/ (carousel + random rounds)
    extra_live = 0
    extra_stock = 0
    seen_names = {votes_path.name, Path(st["run_dir"]).name}
    for votes_extra in sorted(OUT.glob("**/taste_votes_*.json")):
        if votes_extra.name in seen_names:
            continue
        if votes_extra.resolve() == votes_path.resolve():
            continue
        try:
            el, es, _ = load_taste_votes(votes_extra)
        except SystemExit:
            continue
        except Exception as exc:
            print(f"[merge] skip {votes_extra.name}: {exc}")
            continue
        live.extend(el)
        stock.extend(es)
        extra_live += len(el)
        extra_stock += len(es)
        seen_names.add(votes_extra.name)
        print(f"[merge] {votes_extra.name}: +keep={len(el)} +stock={len(es)}")
    if extra_live or extra_stock:
        print(f"[merge] total +keep={extra_live} +stock={extra_stock}")

    # merge probe labels
    probe_live = 0
    probe_stock = 0
    try:
        samples = collect_samples()
        for s in samples:
            try:
                im = _load_thumb(Path(s.file))
            except Exception:
                continue
            if s.label == "live":
                live.append(im)
                probe_live += 1
            elif s.label == "stock":
                stock.append(im)
                probe_stock += 1
        print(f"[probe] +live={probe_live} +stock={probe_stock}")
    except Exception as exc:
        print(f"[probe] skip: {exc}")

    print(f"[train] total live={len(live)} stock={len(stock)}")
    if len(live) < 10 or len(stock) < 10:
        print("need at least 10 per class")
        return 1

    if MODEL_PATH.is_file():
        bak = MODEL_PATH.with_suffix(
            f".pkl.bak_{time.strftime('%Y%m%d_%H%M%S')}"
        )
        shutil.copy2(MODEL_PATH, bak)
        print(f"[backup] {bak.name}")

    t0 = time.perf_counter()
    payload = get_ugc_live_classifier().train(live, stock)
    dt = time.perf_counter() - t0
    print(
        f"[ok] trained in {dt:.1f}s → {MODEL_PATH}\n"
        f"     n_live={payload.get('n_live')} n_stock={payload.get('n_stock')} "
        f"backend={payload.get('embed_backend')}"
    )

    # quick sanity on a few keep vs stock from this vote file
    clf = get_ugc_live_classifier()
    data = json.loads(votes_path.read_text(encoding="utf-8"))
    run_dir = Path(st["run_dir"])
    keep_scores = []
    stock_scores = []
    for row in data.get("detail") or []:
        human = row.get("human")
        fpath = run_dir / str(row.get("img") or "")
        if not fpath.is_file():
            continue
        try:
            im = _load_thumb(fpath)
        except Exception:
            continue
        sc = clf.predict_live_score(im)
        if human == "keep":
            keep_scores.append(sc)
        elif human in ("stock", "wrong"):
            stock_scores.append(sc)
    if keep_scores and stock_scores:
        import numpy as np

        print(
            f"[sanity] keep mean P(live)={float(np.mean(keep_scores)):.3f} "
            f"stock mean={float(np.mean(stock_scores)):.3f}"
        )
        # accuracy at 0.5
        ok = sum(1 for s in keep_scores if s >= 0.5) + sum(
            1 for s in stock_scores if s < 0.5
        )
        acc = ok / (len(keep_scores) + len(stock_scores))
        print(f"[sanity] train-set acc@0.5={acc:.0%} "
              f"(keep n={len(keep_scores)} stock n={len(stock_scores)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
