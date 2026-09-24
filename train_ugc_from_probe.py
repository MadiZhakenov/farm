#!/usr/bin/env python3
"""
Быстрое обучение UGC live-vs-stock на разметке probe-50.

Метки: agent_verdicts.json (live/stock; mixed пропускаем).
Leave-one-out на уже посчитанных эмбеддингах + финальная модель.

Запуск:
  python train_ugc_from_probe.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.ugc_classifier import get_ugc_live_classifier  # noqa: E402
from core.taste_embedder import get_embedder  # noqa: E402

PROBE = ROOT / "out" / "ugc_probe_50"
IMG = PROBE / "images"
VERDICTS = PROBE / "agent_verdicts.json"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    t0 = time.perf_counter()
    data = json.loads(VERDICTS.read_text(encoding="utf-8"))
    detail = data["detail"]

    live_paths: list[Path] = []
    stock_paths: list[Path] = []
    for d in detail:
        label = d["agent"]
        p = IMG / d["file"]
        if not p.is_file():
            continue
        if label == "live":
            live_paths.append(p)
        elif label == "stock":
            stock_paths.append(p)

    print(f"labels: live={len(live_paths)} stock={len(stock_paths)} (mixed skipped)")
    if len(live_paths) < 2 or len(stock_paths) < 2:
        print("FAIL: not enough labels")
        return 1

    emb = get_embedder()
    emb.ensure()
    print(f"embedder: {emb.backend_id}")

    paths = live_paths + stock_paths
    y = np.array([1] * len(live_paths) + [0] * len(stock_paths), dtype=np.int32)
    print(f"embedding {len(paths)} images…")
    imgs = [Image.open(p).convert("RGB") for p in paths]
    x = emb.embed_images(imgs)
    print(f"embeddings shape={x.shape} in {time.perf_counter()-t0:.1f}s")

    # LOOCV — только логрег, эмбеддинги уже готовы
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
        if (i + 1) % 15 == 0 or i + 1 == n:
            print(f"  [{i+1}/{n}] acc={correct/(i+1):.0%}")

    print(f"LOOCV accuracy: {correct}/{n} = {correct/n:.0%}")

    live_imgs = [Image.open(p).convert("RGB") for p in live_paths]
    stock_imgs = [Image.open(p).convert("RGB") for p in stock_paths]
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
