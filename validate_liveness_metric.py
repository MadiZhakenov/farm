#!/usr/bin/env python3
"""
Проверка метрики «живости» (UGC-модель пайплайна) на ручных оценках:
data/taste_history.json — фото, отмеченные «да / нет» при ручном отборе,
картинки в data/cache/clean_photos. Насколько UGC-оценка отделяет «да» от
«нет» (AUC), и как доля «да» растёт по корзинам оценки.

Оговорка: UGC-модель частично дообучалась на этих же голосах
(train_ugc_from_taste_votes.py) — AUC может быть завышен.

  python validate_liveness_metric.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from sklearn.metrics import roc_auc_score

    from core.ugc_filter import get_ugc_filter

    hist = json.loads((DATA / "taste_history.json").read_text(encoding="utf-8"))
    yes, no = set(map(str, hist["yes"])), set(map(str, hist["no"]))
    files, labels = [], []
    for f in sorted((DATA / "cache" / "clean_photos").glob("*.jpg")):
        pid = f.name.split("_")[0]
        if pid in yes or pid in no:
            files.append(f)
            labels.append(1 if pid in yes else 0)
    print(f"размечено с картинками: {len(files)} (да {sum(labels)}, нет {len(labels) - sum(labels)})")

    filt = get_ugc_filter()
    scores: list[float] = []
    for i in range(0, len(files), 64):
        ims = [Image.open(f).convert("RGB") for f in files[i:i + 64]]
        scores += [float(x) for x in filt.get_ugc_scores(ims)]
        for im in ims:
            im.close()
    s, y = np.array(scores), np.array(labels)
    print(f"AUC живость → «да»: {roc_auc_score(y, s):.3f}")
    bins = [0, 0.3, 0.45, 0.55, 0.65, 1.01]
    print("доля «да» по живости:")
    for lo, hi in zip(bins, bins[1:]):
        m = (s >= lo) & (s < hi)
        if m.sum():
            print(f"  {lo:.2f}–{min(hi, 1):.2f}: {y[m].mean():.0%} «да» (n={m.sum()})")
    out = {"n": len(files), "auc": float(roc_auc_score(y, s)),
           "scores": scores, "labels": labels, "files": [f.name for f in files]}
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "liveness_metric_validation.json").write_text(json.dumps(out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
