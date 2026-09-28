#!/usr/bin/env python3
"""
Докинуть hard negatives/positives из production-каруселей в UGC-обучение.

Берёт финальные слайды из указанного run (или всех run_*),
скорит supervised UGC, кладёт низкий UGC → stock, высокий → live,
мержит с probe human_votes и переучивает data/ugc_live_model.pkl.

Запуск:
  python train_ugc_from_carousels.py out/run_20260925_094803
  python train_ugc_from_carousels.py   # все run_* + probes
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.ugc_classifier import MODEL_PATH, get_ugc_live_classifier  # noqa: E402
from core.taste_embedder import get_embedder  # noqa: E402
from train_ugc_from_probe import collect_samples, LabeledSample  # noqa: E402

OUT = ROOT / "out"
HARD_DIR = OUT / "ugc_carousel_labels"
STOCK_FLOOR = 0.55  # ниже = сток (как probe live threshold)
LIVE_FLOOR = 0.62  # выше = живое


def _resolve_label(pred: str, human: str) -> str | None:
    pred = (pred or "").strip().lower()
    human = (human or "").strip().lower()
    if human not in ("ok", "bad"):
        return None
    if pred == "live":
        return "live" if human == "ok" else "stock"
    if pred == "stock":
        return "stock" if human == "ok" else "live"
    return None


def harvest_carousel_run(run_dir: Path) -> list[tuple[Path, str, float]]:
    """[(image_path, label, ugc), ...] from finals using meta ugc_score."""
    rows: list[tuple[Path, str, float]] = []
    for cdir in sorted(run_dir.glob("carousel_*")):
        meta_path = cdir / "meta.json"
        if not meta_path.is_file():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for s in meta.get("slides") or []:
            fname = str(s.get("file") or "")
            fpath = cdir / fname
            if not fpath.is_file():
                idx = s.get("index")
                if idx:
                    fpath = cdir / f"{idx}.jpg"
            if not fpath.is_file():
                continue
            ugc_raw = s.get("ugc_score")
            if ugc_raw is None:
                continue
            ugc = float(ugc_raw)
            if ugc < STOCK_FLOOR:
                label = "stock"
            elif ugc >= LIVE_FLOOR:
                label = "live"
            else:
                continue
            rows.append((fpath, label, ugc))
            print(
                f"  {cdir.name[-24:]} #{s.get('index')} "
                f"ugc={ugc:.0%} -> {label}"
            )
    return rows


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    t0 = time.perf_counter()
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        runs = [Path(a) if Path(a).is_absolute() else ROOT / a for a in args]
    else:
        runs = sorted(OUT.glob("run_20260925_094803"))
        if not runs:
            runs = sorted(OUT.glob("run_*"))[-3:]

    print("=" * 64)
    print("  Train UGC from probes + carousel hard labels")
    print("=" * 64)

    # 1) probe human labels
    samples = collect_samples()
    by_pin: dict[str, LabeledSample] = {s.pin_id: s for s in samples}
    print(f"probe human: {len(by_pin)}")

    # 2) carousel auto labels -> copy into HARD_DIR
    HARD_DIR.mkdir(parents=True, exist_ok=True)
    (HARD_DIR / "live").mkdir(exist_ok=True)
    (HARD_DIR / "stock").mkdir(exist_ok=True)
    carousel_added = {"live": 0, "stock": 0}
    for run in runs:
        if not run.is_dir():
            print(f"SKIP missing {run}")
            continue
        print(f"\nHarvest {run.name}…")
        for fpath, label, ugc in harvest_carousel_run(run):
            dest = HARD_DIR / label / f"{run.name}_{fpath.parent.name}_{fpath.name}"
            if not dest.is_file():
                shutil.copy2(fpath, dest)
            # synthetic pin id for dedupe
            pid = f"car_{dest.stem}"
            by_pin[pid] = LabeledSample(
                pin_id=pid,
                probe=run.name,
                file=dest,
                label=label,
                pred="stock" if label == "stock" else "live",
                human="ok",
            )
            carousel_added[label] += 1
            print(f"    saved {dest.name} ugc={ugc:.0%}")

    print(
        f"\ncarousel labels added: live={carousel_added['live']} "
        f"stock={carousel_added['stock']}"
    )

    # also load any previously saved hard labels
    for label in ("live", "stock"):
        for p in (HARD_DIR / label).glob("*.jpg"):
            pid = f"car_{p.stem}"
            if pid in by_pin:
                continue
            by_pin[pid] = LabeledSample(
                pin_id=pid,
                probe="ugc_carousel_labels",
                file=p,
                label=label,
                pred=label,
                human="ok",
            )

    all_s = list(by_pin.values())
    live = [s for s in all_s if s.label == "live"]
    stock = [s for s in all_s if s.label == "stock"]
    print(f"TOTAL unique: {len(all_s)}  live={len(live)} stock={len(stock)}")
    if len(live) < 2 or len(stock) < 2:
        print("FAIL: not enough labels")
        return 1

    emb = get_embedder()
    emb.ensure()
    paths = [s.file for s in live + stock]
    y = np.array([1] * len(live) + [0] * len(stock), dtype=np.int32)
    print(f"embedding {len(paths)}…")
    imgs = [Image.open(p).convert("RGB") for p in paths]
    x = emb.embed_images(imgs)

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
        if (i + 1) % 30 == 0 or i + 1 == n:
            print(f"  [{i+1}/{n}] acc={correct/(i+1):.0%}")
    print(f"LOOCV: {correct}/{n} = {correct/n:.0%}")

    if MODEL_PATH.is_file():
        bak = MODEL_PATH.with_suffix(".pkl.bak")
        shutil.copy2(MODEL_PATH, bak)
        print(f"backup -> {bak}")

    # clear singleton so fresh model loads
    import core.ugc_classifier as uc

    with uc._LOCK:
        uc._CLF = None

    payload = get_ugc_live_classifier().train(
        [Image.open(p).convert("RGB") for p in [s.file for s in live]],
        [Image.open(p).convert("RGB") for p in [s.file for s in stock]],
    )
    print(
        f"saved {MODEL_PATH} live={payload['n_live']} stock={payload['n_stock']}"
    )
    print(f"done in {time.perf_counter()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
