#!/usr/bin/env python3
"""
Обучение UGC live-vs-stock на human_votes со всех probe-раундов.

Метка:
  pred=live  + ok  → live
  pred=stock + ok  → stock
  pred=live  + bad → stock  (ложное живое)
  pred=stock + bad → live   (ложный сток)
  pred=mixed → пропуск

Запуск:
  python train_ugc_from_probe.py
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.ugc_classifier import MODEL_PATH, get_ugc_live_classifier  # noqa: E402
from core.taste_embedder import get_embedder  # noqa: E402

OUT = ROOT / "out"


@dataclass
class LabeledSample:
    pin_id: str
    probe: str
    file: Path
    label: str  # live | stock
    pred: str
    human: str


def _resolve_label(pred: str, human: str) -> str | None:
    pred = (pred or "").strip().lower()
    human = (human or "").strip().lower()
    if human not in ("ok", "bad"):
        return None
    if pred == "live":
        return "live" if human == "ok" else "stock"
    if pred == "stock":
        return "stock" if human == "ok" else "live"
    return None  # mixed / unknown


def collect_samples() -> list[LabeledSample]:
    by_pin: dict[str, LabeledSample] = {}
    probes = sorted(OUT.glob("ugc_probe_*"))
    for probe_dir in probes:
        votes_path = probe_dir / "human_votes.json"
        results_path = probe_dir / "results.json"
        if not votes_path.is_file() or not results_path.is_file():
            continue
        results = {
            str(r["pin_id"]): r
            for r in json.loads(results_path.read_text(encoding="utf-8"))
            if r.get("pin_id")
        }
        votes = json.loads(votes_path.read_text(encoding="utf-8"))
        detail = votes.get("detail") or []
        if not detail:
            # fallback: votes map + results pred
            for pid, human in (votes.get("votes") or {}).items():
                r = results.get(str(pid))
                if not r:
                    continue
                detail.append(
                    {
                        "pin_id": pid,
                        "human": human,
                        "pred": r.get("status_key"),
                    }
                )

        n_ok = 0
        for d in detail:
            pid = str(d.get("pin_id") or "")
            if not pid:
                continue
            r = results.get(pid)
            if not r:
                continue
            pred = str(d.get("pred") or r.get("status_key") or "")
            human = str(d.get("human") or "")
            label = _resolve_label(pred, human)
            if label is None:
                continue
            fpath = probe_dir / "images" / str(r.get("file") or "")
            if not fpath.is_file():
                continue
            by_pin[pid] = LabeledSample(
                pin_id=pid,
                probe=probe_dir.name,
                file=fpath,
                label=label,
                pred=pred,
                human=human,
            )
            n_ok += 1
        print(f"  {probe_dir.name}: {n_ok} usable labels from human_votes")

    return list(by_pin.values())


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    t0 = time.perf_counter()
    print("=" * 64)
    print("  Train UGC live-model from all probe human_votes")
    print("=" * 64)

    samples = collect_samples()
    live = [s for s in samples if s.label == "live"]
    stock = [s for s in samples if s.label == "stock"]
    corr = sum(1 for s in samples if s.human == "bad")
    print(
        f"unique pins: {len(samples)}  "
        f"live={len(live)} stock={len(stock)}  "
        f"(human corrections={corr})"
    )
    if len(live) < 2 or len(stock) < 2:
        print("FAIL: not enough labels")
        return 1

    emb = get_embedder()
    emb.ensure()
    print(f"embedder: {emb.backend_id}")

    paths = [s.file for s in live + stock]
    y = np.array([1] * len(live) + [0] * len(stock), dtype=np.int32)
    print(f"embedding {len(paths)} images…")
    imgs = [Image.open(p).convert("RGB") for p in paths]
    x = emb.embed_images(imgs)
    print(f"embeddings shape={x.shape} in {time.perf_counter()-t0:.1f}s")

    correct = 0
    n = len(paths)
    print(f"LOOCV on {n}…")
    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        x_tr, y_tr = x[mask], y[mask]
        if y_tr.sum() < 2 or (len(y_tr) - y_tr.sum()) < 2:
            continue
        clf = LogisticRegression(
            C=1.0, max_iter=2000, solver="lbfgs", class_weight="balanced"
        )
        clf.fit(x_tr, y_tr)
        proba = clf.predict_proba(x[i : i + 1])[0]
        col = list(clf.classes_).index(1)
        pred = 1 if float(proba[col]) >= 0.5 else 0
        if pred == int(y[i]):
            correct += 1
        if (i + 1) % 20 == 0 or i + 1 == n:
            print(f"  [{i+1}/{n}] acc={correct/(i+1):.0%}")

    print(f"LOOCV accuracy: {correct}/{n} = {correct/n:.0%}")

    if MODEL_PATH.is_file():
        bak = MODEL_PATH.with_suffix(".pkl.bak")
        shutil.copy2(MODEL_PATH, bak)
        print(f"backup -> {bak}")

    live_imgs = [Image.open(p).convert("RGB") for p in [s.file for s in live]]
    stock_imgs = [Image.open(p).convert("RGB") for p in [s.file for s in stock]]
    clf = get_ugc_live_classifier()
    payload = clf.train(live_imgs, stock_imgs)
    print(
        f"saved {clf.model_path}  "
        f"live={payload['n_live']} stock={payload['n_stock']}  "
        f"backend={payload['embed_backend']}"
    )
    print(f"done in {time.perf_counter()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
