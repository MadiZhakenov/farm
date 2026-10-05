#!/usr/bin/env python3
"""
Дообучение модели живости (data/ugc_live_model.pkl: SigLIP + LogisticRegression)
на новой ручной разметке без потери старых знаний.

Данные (исходных разметок старой модели на этой машине нет):
  A  новая разметка label_frames.py: live → 1, stock / ai → 0 (unclear — мимо)
  B  data/taste_history.json: «да» → 1, «нет» → 0 (картинки data/cache/clean_photos)
  C  пины с ИИ-меткой Pinterest (fetch_pinterest_ai_pins.py) → 0
  D  опора на старую модель: её уверенные ответы на кадрах замеров
     (P(live) > 0.85 → 1, < 0.10 → 0) — чтобы не забыть выученное

Честная проверка: 5 фолдов по A (и отдельно по B); модель каждого фолда учится
на всём остальном. Сравнение со старой моделью и с итоговой оценкой
пайплайна (смесь модели, zero-shot и эвристик) на тех же метках.
Модель сохраняется (старая — в .bak), только если на A и на B не хуже.

  python train_liveness_v2.py --pack out/label_pack_20261005 --ai out/pinterest_ai_pins \\
      --anchors out/query_liveness_v2 out/filler_bank_probe [--save]
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"


def embed(paths: list[Path], keys: list[str]) -> np.ndarray:
    from core.taste_embedder import get_embedder

    emb = get_embedder()
    out = []
    for i in range(0, len(paths), 64):
        ims = [Image.open(p).convert("RGB") for p in paths[i:i + 64]]
        out.append(emb.embed_images(ims, cache_keys=keys[i:i + 64]))
        for im in ims:
            im.close()
    return np.vstack(out) if out else np.zeros((0, 768), dtype=np.float32)


def load_a(pack: Path) -> tuple[np.ndarray, np.ndarray, list[Path]]:
    rows = {r["pin_id"]: r for r in json.loads((pack / "pack.json").read_text(encoding="utf-8"))}
    votes = json.loads((pack / "votes.json").read_text(encoding="utf-8"))
    paths, keys, y = [], [], []
    for pid, v in votes.items():
        if v == "unclear" or pid not in rows:
            continue
        paths.append(pack / "imgs" / rows[pid]["file"])
        keys.append(f"labelpack:{pid}")
        y.append(1 if v == "live" else 0)
    return embed(paths, keys), np.array(y), paths


def load_b() -> tuple[np.ndarray, np.ndarray, list[Path]]:
    hist = json.loads((DATA / "taste_history.json").read_text(encoding="utf-8"))
    yes, no = set(map(str, hist["yes"])), set(map(str, hist["no"]))
    paths, y = [], []
    for f in sorted((DATA / "cache" / "clean_photos").glob("*.jpg")):
        pid = f.name.split("_")[0]
        if pid in yes or pid in no:
            paths.append(f)
            y.append(1 if pid in yes else 0)
    return embed(paths, [f"clean:{p.stem}" for p in paths]), np.array(y), paths


def load_c(ai_dir: Path) -> np.ndarray:
    rows = json.loads((ai_dir / "pins.json").read_text(encoding="utf-8"))
    paths = [ai_dir / "imgs" / r["file"] for r in rows]
    return embed(paths, [f"pinai:{r['pin_id']}" for r in rows])


def load_d(dirs: list[Path], old, n_each: int, rng: random.Random) -> tuple[np.ndarray, np.ndarray]:
    import csv

    paths, keys = [], []
    seen = set()
    for d in dirs:
        for r in csv.DictReader((d / "pins.csv").open(encoding="utf-8")):
            pid = r["pin_id"]
            f = d / "thumbs" / f"{pid}.jpg"
            if pid not in seen and f.exists():
                seen.add(pid)
                paths.append(f)
                keys.append(pid)
    x = embed(paths, keys)
    p = np.asarray(old.predict_live_scores_from_vecs(x))
    pos = [i for i in np.where(p > 0.85)[0]]
    neg = [i for i in np.where(p < 0.10)[0]]
    rng.shuffle(pos)
    rng.shuffle(neg)
    idx = pos[:n_each] + neg[:n_each]
    return x[idx], np.array([1] * len(pos[:n_each]) + [0] * len(neg[:n_each]))


def fit(x, y, w):
    from sklearn.linear_model import LogisticRegression

    clf = LogisticRegression(C=1.0, max_iter=3000, solver="lbfgs", class_weight="balanced")
    clf.fit(x, y, sample_weight=w)
    return clf


def cv_scores(target_x, target_y, rest_x, rest_y, rest_w, w_target, k=5, seed=0):
    """Предсказания для target по фолдам; учимся на rest + остальных фолдах target."""
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(target_y))
    folds = np.array_split(order, k)
    pred = np.zeros(len(target_y))
    for f in folds:
        tr = np.setdiff1d(order, f)
        x = np.vstack([rest_x, target_x[tr]])
        y = np.concatenate([rest_y, target_y[tr]])
        w = np.concatenate([rest_w, np.full(len(tr), w_target)])
        clf = fit(x, y, w)
        pred[f] = clf.predict_proba(target_x[f])[:, list(clf.classes_).index(1)]
    return pred


def pipeline_score(sup: np.ndarray, details: list[dict]) -> np.ndarray:
    from core.ugc_filter import _combine_signals

    return np.array([
        _combine_signals(supervised=float(s), zero_shot=d["zero_shot"], margin=d["margin"], penalty=d["penalty"])[0]
        for s, d in zip(sup, details)
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", type=Path, required=True)
    ap.add_argument("--ai", type=Path, required=True)
    ap.add_argument("--anchors", type=Path, nargs="*", default=[])
    ap.add_argument("--n-anchor", type=int, default=400)
    ap.add_argument("--w-new", type=float, default=3.0)
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from sklearn.metrics import roc_auc_score

    from core.ugc_classifier import MODEL_PATH, get_ugc_live_classifier
    from core.ugc_filter import get_ugc_filter

    old = get_ugc_live_classifier()
    t0 = time.perf_counter()
    xa, ya, pa = load_a(args.pack)
    xb, yb, pb = load_b()
    xc = load_c(args.ai)
    xd, yd = load_d(args.anchors, old, args.n_anchor, random.Random(1)) if args.anchors else (np.zeros((0, xa.shape[1])), np.zeros(0))
    print(f"A новая разметка: {len(ya)} (живых {ya.sum()}) · B старые да/нет: {len(yb)} (да {yb.sum()}) · "
          f"C ИИ-пины: {len(xc)} · D опора: {len(yd)} (живых {int(yd.sum())}) · {time.perf_counter() - t0:.0f} с")

    filt = get_ugc_filter()

    def details_for(paths, x):
        ims = [Image.open(p).convert("RGB") for p in paths]
        d = filt.score_details(ims, image_vecs=x)
        for im in ims:
            im.close()
        return d

    da, db = details_for(pa, xa), details_for(pb, xb)
    old_sup_a = np.asarray(old.predict_live_scores_from_vecs(xa))
    old_sup_b = np.asarray(old.predict_live_scores_from_vecs(xb))
    old_pipe_a = np.array([d["score"] for d in da])
    old_pipe_b = np.array([d["score"] for d in db])
    old_c = np.asarray(old.predict_live_scores_from_vecs(xc)) if len(xc) else np.zeros(0)

    variants = {
        "без опоры (A+B+C)": dict(use_d=False, w_new=args.w_new),
        "с опорой (A+B+C+D)": dict(use_d=True, w_new=args.w_new),
        "с опорой, A вес 1": dict(use_d=True, w_new=1.0),
    }
    print("\nAUC (насколько оценка отделяет «живое» от «не живого»; 0.5 — монетка):")
    print(f"  {'вариант':26s} {'A модель':>9s} {'A пайплайн':>11s} {'B модель':>9s} {'B пайплайн':>11s}  ИИ-пины ≥0.55")
    print(f"  {'старая модель':26s} {roc_auc_score(ya, old_sup_a):9.3f} {roc_auc_score(ya, old_pipe_a):11.3f} "
          f"{roc_auc_score(yb, old_sup_b):9.3f} {roc_auc_score(yb, old_pipe_b):11.3f}  "
          f"{(old_c >= 0.55).mean():.0%}")
    best = None
    for name, v in variants.items():
        rest_x = [xc] + ([xd] if v["use_d"] else [])
        rest_y = [np.zeros(len(xc))] + ([yd] if v["use_d"] else [])
        rest_w = [np.ones(len(xc))] + ([np.full(len(yd), 0.5)] if v["use_d"] else [])
        # A по фолдам (B целиком в обучении), B по фолдам (A целиком)
        pa_ = cv_scores(xa, ya, np.vstack(rest_x + [xb]), np.concatenate(rest_y + [yb]),
                        np.concatenate(rest_w + [np.ones(len(yb))]), v["w_new"])
        pb_ = cv_scores(xb, yb, np.vstack(rest_x + [xa]), np.concatenate(rest_y + [ya]),
                        np.concatenate(rest_w + [np.full(len(ya), v["w_new"])]), 1.0)
        # ИИ-пины: по фолдам
        pc_ = cv_scores(xc, np.zeros(len(xc)), np.vstack(rest_x[1:] + [xa, xb]) if len(rest_x) > 1 else np.vstack([xa, xb]),
                        np.concatenate(rest_y[1:] + [ya, yb]) if len(rest_y) > 1 else np.concatenate([ya, yb]),
                        np.concatenate(rest_w[1:] + [np.full(len(ya), v["w_new"]), np.ones(len(yb))]) if len(rest_w) > 1
                        else np.concatenate([np.full(len(ya), v["w_new"]), np.ones(len(yb))]), 1.0)
        r = (roc_auc_score(ya, pa_), roc_auc_score(ya, pipeline_score(pa_, da)),
             roc_auc_score(yb, pb_), roc_auc_score(yb, pipeline_score(pb_, db)), (pc_ >= 0.55).mean())
        print(f"  {name:26s} {r[0]:9.3f} {r[1]:11.3f} {r[2]:9.3f} {r[3]:11.3f}  {r[4]:.0%}")
        if best is None or r[1] + r[3] > best[1][1] + best[1][3]:
            best = (name, r, v, pa_)

    name, r, v, pa_ = best
    print(f"\nлучший вариант: {name}")
    # порог: доля «живых» среди прошедших и сколько живых теряем — старая vs новая (по фолдам)
    pipe_new = pipeline_score(pa_, da)
    for thr in (0.30, 0.45, 0.55):
        for lab, s in (("старая", old_pipe_a), ("новая", pipe_new)):
            m = s >= thr
            prec = ya[m].mean() if m.any() else float("nan")
            rec = (m & (ya == 1)).sum() / max(1, ya.sum())
            print(f"  порог {thr:.2f} {lab}: проходит {m.sum():3d} · из них живых {prec:.0%} · находит живых {rec:.0%}")

    ok = r[1] >= roc_auc_score(ya, old_pipe_a) and r[3] >= roc_auc_score(yb, old_pipe_b) - 0.01
    if args.save and ok:
        x = np.vstack([xa, xb, xc] + ([xd] if v["use_d"] else []))
        y = np.concatenate([ya, yb, np.zeros(len(xc))] + ([yd] if v["use_d"] else []))
        w = np.concatenate([np.full(len(ya), v["w_new"]), np.ones(len(yb)), np.ones(len(xc))]
                           + ([np.full(len(yd), 0.5)] if v["use_d"] else []))
        clf = fit(x, y, w)
        import joblib

        bak = MODEL_PATH.with_name(f"ugc_live_model.pkl.bak_{time.strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(MODEL_PATH, bak)
        joblib.dump({
            "model": clf, "calibration": "logistic_predict_proba", "label_positive": "live",
            "label_negative": "stock", "embed_backend": old._backend or "google/siglip-base-patch16-224",
            "embed_dim": int(x.shape[1]), "n_live": int(y.sum()), "n_stock": int(len(y) - y.sum()),
            "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "sources": {"label_pack": str(args.pack), "taste_history": len(yb), "pinterest_ai": len(xc),
                        "anchors": len(yd) if v["use_d"] else 0, "variant": name},
            "cv": {"A_pipeline_auc": r[1], "B_pipeline_auc": r[3]},
        }, MODEL_PATH)
        print(f"сохранено → {MODEL_PATH} (старая → {bak.name})")
    elif args.save:
        print("НЕ сохранено: новая модель не лучше старой")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
