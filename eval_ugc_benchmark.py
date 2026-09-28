#!/usr/bin/env python3
"""
Frozen UGC live-vs-stock benchmarks from human votes.

Suites (v1):
  carousel   — taste keep/stock on batch carousels (IN TRAIN)
  random     — random clean photos (IN TRAIN)
  midband    — ambiguous P≈0.45–0.65 (IN TRAIN)
  pack1k     — 1000 pack (IN TRAIN)
  picks100   — model top-picks YES/NO (HOLDOUT — not used in train)
  probes     — early ugc_probe human_votes (IN TRAIN)

Usage:
  python eval_ugc_benchmark.py --freeze          # build out/benchmarks/ugc_v1/manifest.json
  python eval_ugc_benchmark.py                  # eval current model
  python eval_ugc_benchmark.py --compare        # current + key backups
  python eval_ugc_benchmark.py --floors 0.50 0.55 0.60 0.65
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
DATA = ROOT / "data"
BENCH_DIR = OUT / "benchmarks" / "ugc_v1"
MANIFEST = BENCH_DIR / "manifest.json"
DEFAULT_FLOORS = (0.50, 0.55, 0.60, 0.65)


@dataclass
class Sample:
    suite: str
    label: str  # live | stock
    path: str  # absolute
    rel: str
    pin_id: str = ""
    source: str = ""
    in_train: bool = True
    meta: dict[str, Any] | None = None


def _pin_from_name(name: str) -> str:
    for part in Path(name).stem.replace("-", "_").split("_"):
        if part.isdigit() and len(part) >= 6:
            return part
    return Path(name).stem


def _load_taste(votes_path: Path, suite: str, *, in_train: bool) -> list[Sample]:
    data = json.loads(votes_path.read_text(encoding="utf-8"))
    run = OUT / str(data.get("run") or "")
    out: list[Sample] = []
    for row in data.get("detail") or []:
        human = (row.get("human") or "").strip().lower()
        if human not in ("keep", "stock", "wrong"):
            continue
        rel = str(row.get("img") or "")
        fp = run / rel
        if not fp.is_file():
            continue
        label = "live" if human == "keep" else "stock"
        out.append(
            Sample(
                suite=suite,
                label=label,
                path=str(fp.resolve()),
                rel=f"{run.name}/{rel}".replace("\\", "/"),
                pin_id=str(row.get("pin_id") or _pin_from_name(rel)),
                source=str(votes_path.relative_to(ROOT)).replace("\\", "/"),
                in_train=in_train,
                meta={"human": human, "ugc_at_label": row.get("ugc")},
            )
        )
    return out


def _load_picks(votes_path: Path, suite: str) -> list[Sample]:
    data = json.loads(votes_path.read_text(encoding="utf-8"))
    run = OUT / str(data.get("run") or "model_picks_20260928_101407")
    out: list[Sample] = []
    for row in data.get("detail") or []:
        human = (row.get("human") or "").strip().lower()
        if human not in ("yes", "no"):
            continue
        rel = str(row.get("img") or "")
        fp = run / rel
        if not fp.is_file():
            # try photos/ from picks
            alt = run / "photos" / Path(rel).name
            fp = alt if alt.is_file() else fp
        if not fp.is_file():
            continue
        label = "live" if human == "yes" else "stock"
        out.append(
            Sample(
                suite=suite,
                label=label,
                path=str(fp.resolve()),
                rel=f"{run.name}/{rel}".replace("\\", "/"),
                pin_id=str(row.get("pin_id") or ""),
                source=str(votes_path.relative_to(ROOT)).replace("\\", "/"),
                in_train=False,  # holdout
                meta={
                    "human": human,
                    "ugc_at_pick": row.get("ugc"),
                    "rank": row.get("rank"),
                    "batch": row.get("batch"),
                },
            )
        )
    return out


def _load_probes() -> list[Sample]:
    from train_ugc_from_probe import collect_samples

    out: list[Sample] = []
    for s in collect_samples():
        fp = Path(s.file)
        if not fp.is_file():
            continue
        label = "live" if s.label == "live" else "stock"
        if s.label not in ("live", "stock"):
            continue
        out.append(
            Sample(
                suite="probes",
                label=label,
                path=str(fp.resolve()),
                rel=str(fp.relative_to(ROOT)).replace("\\", "/")
                if fp.is_relative_to(ROOT)
                else fp.name,
                pin_id=_pin_from_name(fp.name),
                source="probe_human_votes",
                in_train=True,
                meta={},
            )
        )
    return out


def build_manifest() -> dict[str, Any]:
    suites: dict[str, list[Sample]] = {
        "carousel": _load_taste(
            OUT / "run_20260925_155018" / "taste_votes_run_20260925_155018.json",
            "carousel",
            in_train=True,
        ),
        "random": _load_taste(
            OUT
            / "taste_random_20260925_164628"
            / "taste_votes_taste_random_20260925_164628.json",
            "random",
            in_train=True,
        ),
        "midband": _load_taste(
            OUT
            / "taste_midband_20260925_165715"
            / "taste_votes_taste_midband_20260925_165715.json",
            "midband",
            in_train=True,
        ),
        "pack1k": _load_taste(
            OUT
            / "taste_pack_20260928_091303"
            / "taste_votes_taste_pack_20260928_091303.json",
            "pack1k",
            in_train=True,
        ),
        "picks100": _load_picks(
            OUT
            / "model_picks_20260928_101407"
            / "model_picks_votes_model_picks_20260928_101407.json",
            "picks100",
        ),
        "probes": _load_probes(),
    }

    # dedupe within suite by path
    frozen: dict[str, list[dict]] = {}
    totals = {}
    for name, samples in suites.items():
        seen: set[str] = set()
        rows = []
        for s in samples:
            key = s.path.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(asdict(s))
        frozen[name] = rows
        n_live = sum(1 for r in rows if r["label"] == "live")
        n_stock = sum(1 for r in rows if r["label"] == "stock")
        totals[name] = {
            "n": len(rows),
            "live": n_live,
            "stock": n_stock,
            "in_train": bool(rows[0]["in_train"]) if rows else False,
        }

    payload = {
        "version": "ugc_v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "notes": (
            "picks100 is HOLDOUT (YES/NO on model top-picks, not used in train). "
            "Other suites were merged into ugc_live_model training — metrics there "
            "are optimistic. Primary decision metric: picks100 precision@floor."
        ),
        "suites": totals,
        "samples": frozen,
    }
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def load_manifest() -> dict[str, Any]:
    if not MANIFEST.is_file():
        return build_manifest()
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _metrics(
    y_true: np.ndarray,
    scores: np.ndarray,
    floors: tuple[float, ...],
) -> dict[str, Any]:
    """y_true: 1=live, 0=stock. scores: P(live)."""
    pos = scores[y_true == 1]
    neg = scores[y_true == 0]
    out: dict[str, Any] = {
        "n": int(len(y_true)),
        "n_live": int((y_true == 1).sum()),
        "n_stock": int((y_true == 0).sum()),
        "live_mean": float(pos.mean()) if len(pos) else None,
        "stock_mean": float(neg.mean()) if len(neg) else None,
        "gap": float(pos.mean() - neg.mean()) if len(pos) and len(neg) else None,
    }
    try:
        from sklearn.metrics import roc_auc_score

        if len(pos) and len(neg):
            out["auroc"] = float(roc_auc_score(y_true, scores))
    except Exception:
        out["auroc"] = None

    by_floor = {}
    for thr in floors:
        pred = (scores >= thr).astype(np.int32)
        tp = int(((pred == 1) & (y_true == 1)).sum())
        fp = int(((pred == 1) & (y_true == 0)).sum())
        tn = int(((pred == 0) & (y_true == 0)).sum())
        fn = int(((pred == 0) & (y_true == 1)).sum())
        prec = tp / (tp + fp) if (tp + fp) else None
        rec = tp / (tp + fn) if (tp + fn) else None
        f1 = (
            (2 * prec * rec / (prec + rec))
            if prec is not None and rec is not None and (prec + rec)
            else None
        )
        acc = (tp + tn) / len(y_true) if len(y_true) else None
        stock_leak = fp / (fp + tn) if (fp + tn) else None  # stock passed as live
        by_floor[f"{thr:.2f}"] = {
            "acc": acc,
            "precision": prec,
            "recall": rec,
            "f1": f1,
            "stock_leak": stock_leak,
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
        }
    out["by_floor"] = by_floor
    return out


def eval_model(
    model_path: Path,
    manifest: dict[str, Any],
    floors: tuple[float, ...],
    *,
    batch: int = 24,
) -> dict[str, Any]:
    from core.ugc_classifier import UGCLiveClassifier

    clf = UGCLiveClassifier(model_path)
    if not clf.is_trained:
        raise SystemExit(f"model not trained: {model_path}")

    suite_results = {}
    for suite, rows in (manifest.get("samples") or {}).items():
        paths: list[Path] = []
        labels: list[int] = []
        missing = 0
        for r in rows:
            fp = Path(r["path"])
            if not fp.is_file():
                missing += 1
                continue
            paths.append(fp)
            labels.append(1 if r["label"] == "live" else 0)
        if not paths:
            suite_results[suite] = {"error": "no images", "missing": missing}
            continue

        scores_list: list[float] = []
        keep_labels: list[int] = []
        for i in range(0, len(paths), batch):
            chunk_paths = paths[i : i + batch]
            chunk_labels = labels[i : i + batch]
            imgs: list[Image.Image] = []
            labs: list[int] = []
            for p, lab in zip(chunk_paths, chunk_labels):
                try:
                    im = Image.open(p).convert("RGB")
                    im.load()
                    imgs.append(im)
                    labs.append(lab)
                except Exception:
                    continue
            if not imgs:
                continue
            sc = clf.predict_live_scores(imgs)
            scores_list.extend(sc)
            keep_labels.extend(labs)

        y = np.array(keep_labels, dtype=np.int32)
        s = np.array(scores_list, dtype=np.float64)
        m = _metrics(y, s, floors)
        m["missing_files"] = missing
        m["in_train"] = bool(rows[0].get("in_train")) if rows else True
        suite_results[suite] = m

    # harvester floor snapshot
    try:
        from core import harvester as H

        hard = float(H.UGC_HARD_FLOOR)
    except Exception:
        hard = 0.55

    return {
        "model": str(model_path),
        "model_name": model_path.name,
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "harvester_ugc_hard_floor": hard,
        "floors": list(floors),
        "suites": suite_results,
    }


def _fmt_pct(x: float | None) -> str:
    if x is None:
        return "  — "
    return f"{x:5.0%}"


def print_report(results: list[dict[str, Any]], primary_floor: float = 0.55) -> None:
    thr = f"{primary_floor:.2f}"
    print()
    print(
        f"{'model':<22} {'suite':<10} {'hold':>4} {'n':>5} {'gap':>6} "
        f"{'AUROC':>5} {'P@'+thr:>6} {'R@'+thr:>6} {'leak':>5} {'acc':>5}"
    )
    print("-" * 90)
    for res in results:
        name = res["model_name"]
        for suite, m in (res.get("suites") or {}).items():
            if "error" in m:
                print(f"{name:<22} {suite:<10} ERR {m['error']}")
                continue
            bf = (m.get("by_floor") or {}).get(thr) or {}
            hold = "no" if m.get("in_train") else "YES"
            auroc = m.get("auroc")
            auroc_s = f"{auroc:.2f}" if auroc is not None else "  — "
            gap = m.get("gap")
            gap_s = f"{gap:6.3f}" if gap is not None else "   — "
            print(
                f"{name:<22} {suite:<10} {hold:>4} {m.get('n',0):5d} {gap_s} "
                f"{auroc_s:>5} {_fmt_pct(bf.get('precision'))} "
                f"{_fmt_pct(bf.get('recall'))} {_fmt_pct(bf.get('stock_leak'))} "
                f"{_fmt_pct(bf.get('acc'))}"
            )
        print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true", help="rebuild manifest")
    ap.add_argument("--compare", action="store_true", help="eval current + backups")
    ap.add_argument(
        "--floors",
        nargs="+",
        type=float,
        default=list(DEFAULT_FLOORS),
    )
    ap.add_argument(
        "--model",
        type=Path,
        default=DATA / "ugc_live_model.pkl",
    )
    args = ap.parse_args()
    floors = tuple(float(x) for x in args.floors)

    if args.freeze or not MANIFEST.is_file():
        man = build_manifest()
        print(f"[freeze] {MANIFEST}")
        for k, v in (man.get("suites") or {}).items():
            flag = "HOLD" if not v.get("in_train") else "train"
            print(
                f"  {k:<10} n={v['n']:4d} live={v['live']:3d} "
                f"stock={v['stock']:3d} [{flag}]"
            )
    else:
        man = load_manifest()
        print(f"[manifest] {MANIFEST} ({man.get('version')})")

    models: list[Path] = [args.model]
    if args.compare:
        for p in [
            DATA / "ugc_live_model.pkl.bak",
            DATA / "ugc_live_model.pkl.bak_20260925_170114",
            DATA / "ugc_live_model.pkl.bak_20260928_095306",
            DATA / "ugc_live_model.pkl",
        ]:
            if p.is_file() and p not in models:
                models.append(p)
        # unique preserve order, current last for readability
        seen: set[str] = set()
        ordered = []
        for p in [
            DATA / "ugc_live_model.pkl.bak",
            DATA / "ugc_live_model.pkl.bak_20260928_095306",
            DATA / "ugc_live_model.pkl",
        ]:
            if p.is_file() and str(p) not in seen:
                ordered.append(p)
                seen.add(str(p))
        models = ordered

    results = []
    t0 = time.perf_counter()
    for mp in models:
        print(f"[eval] {mp.name} …")
        results.append(eval_model(mp, man, floors))
    print(f"[done] {time.perf_counter()-t0:.0f}s")

    print_report(results, primary_floor=0.55)
    print_report(results, primary_floor=0.60)

    # highlight holdout
    print("=== HOLDOUT picks100 (not in train) ===")
    for res in results:
        m = (res.get("suites") or {}).get("picks100") or {}
        if not m or "error" in m:
            continue
        print(f"  {res['model_name']}:")
        for thr, bf in (m.get("by_floor") or {}).items():
            print(
                f"    @{thr}: P={_fmt_pct(bf.get('precision')).strip()} "
                f"R={_fmt_pct(bf.get('recall')).strip()} "
                f"leak={_fmt_pct(bf.get('stock_leak')).strip()} "
                f"acc={_fmt_pct(bf.get('acc')).strip()}"
            )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = BENCH_DIR / f"results_{stamp}.json"
    latest = BENCH_DIR / "results_latest.json"
    payload = {
        "manifest": str(MANIFEST),
        "manifest_version": man.get("version"),
        "results": results,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n[saved] {out_path}")
    print(f"[saved] {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
