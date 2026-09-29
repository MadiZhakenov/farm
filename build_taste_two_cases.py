#!/usr/bin/env python3
"""
Two taste-label HTML packs:

  A) random  — fresh-ish Pinterest download (Ideas/Related + random queries)
  B) system  — photos that already passed our pipeline (PASS pools, model picks,
               factory carousel slides) so you can mark false positives

Usage:
  python build_taste_two_cases.py system --n 1000
  python build_taste_two_cases.py random --n 2000
  python build_taste_two_cases.py both --n-random 2000 --n-system 1000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import shutil
import time
from datetime import datetime
from pathlib import Path

from PIL import Image

from build_taste_label_pack import load_seen_pins, pin_guess, write_html

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
CLEAN = ROOT / "data" / "cache" / "clean_photos"
AGENT = OUT / "agent_sessions"
EXTS = {".jpg", ".jpeg", ".png", ".webp"}
UGC_PASS = 0.55


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return p.name


def _copy_items(
    run_dir: Path,
    rows: list[tuple[Path, dict]],
) -> list[dict]:
    photos = run_dir / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []
    for i, (src, meta) in enumerate(rows):
        pid = str(meta.get("pin_id") or pin_guess(src))
        dest_name = f"{i:04d}_{pid}{src.suffix.lower() or '.jpg'}"
        dest = photos / dest_name
        if not dest.exists():
            shutil.copy2(src, dest)
        items.append(
            {
                "id": f"{meta.get('prefix', 'x')}_{i:04d}_{pid}",
                "carousel": meta.get("carousel") or "pack",
                "slide": i + 1,
                "topic": meta.get("topic") or "",
                "text": meta.get("text") or _rel(src),
                "query": meta.get("query") or "",
                "img": f"photos/{dest_name}",
                "ugc": meta.get("ugc"),
                "rel": meta.get("rel"),
                "mode": meta.get("mode") or "",
                "pin_id": pid,
                "src": _rel(src),
            }
        )
    return items


def _finalize(run_name: str, items: list[dict], extra: dict | None = None) -> Path:
    run_dir = OUT / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run": run_name,
        "n": len(items),
        "items": items,
        **(extra or {}),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    html_path = write_html(run_dir, run_name, items)
    print(f"wrote {html_path}  n={len(items)}")
    return html_path


# ---------------------------------------------------------------------------
# Case B — system-passed
# ---------------------------------------------------------------------------

def collect_system_candidates(seen: set[str]) -> list[tuple[Path, dict]]:
    rows: list[tuple[Path, dict]] = []
    used: set[str] = set()

    def add(path: Path, meta: dict) -> None:
        if not path.is_file() or path.suffix.lower() not in EXTS:
            return
        pid = str(meta.get("pin_id") or pin_guess(path)).strip()
        if not pid or pid in seen or pid in used:
            return
        key = str(path.resolve()).lower()
        if key in used:
            return
        used.add(pid)
        used.add(key)
        meta = {**meta, "pin_id": pid, "prefix": meta.get("prefix") or "sys"}
        rows.append((path, meta))

    # 1) Agent pool PASS / KEEP (clean backgrounds the gate let through)
    if AGENT.is_dir():
        for p in AGENT.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in EXTS:
                continue
            up = p.name.upper()
            if "PASS" not in up and "_KEEP" not in up and not up.startswith("KEEP"):
                continue
            add(
                p,
                {
                    "topic": "agent PASS",
                    "mode": "agent_pass",
                    "carousel": "agent_pass",
                    "prefix": "pass",
                    "text": _rel(p),
                },
            )

    # 2) Model picks gallery
    for mp in OUT.glob("model_picks_*/photos"):
        if not mp.is_dir():
            continue
        for p in sorted(mp.iterdir()):
            if not p.is_file() or p.suffix.lower() not in EXTS:
                continue
            ugc = None
            # filenames like 01_ugc94_PIN.jpg
            for part in p.stem.split("_"):
                if part.lower().startswith("ugc") and part[3:].isdigit():
                    ugc = int(part[3:]) / 100.0
            add(
                p,
                {
                    "topic": "model pick",
                    "mode": "model_pick",
                    "carousel": "model_picks",
                    "prefix": "mp",
                    "ugc": ugc,
                    "text": _rel(p),
                },
            )

    # 3) Factory run carousel slides (full pipeline output)
    for run in sorted(OUT.glob("run_*")):
        for meta_p in run.glob("carousel_*/meta.json"):
            car = meta_p.parent
            try:
                md = json.loads(meta_p.read_text(encoding="utf-8"))
            except Exception:
                continue
            topic = md.get("topic") or car.name
            for s in md.get("slides") or []:
                idx = int(s.get("index") or 0)
                fname = s.get("file") or f"{idx}.jpg"
                img = car / fname
                pid = str(s.get("pin_id") or "").strip() or pin_guess(img)
                add(
                    img,
                    {
                        "topic": topic,
                        "mode": s.get("selection_mode") or "factory_slide",
                        "carousel": car.name,
                        "prefix": "fac",
                        "ugc": s.get("ugc_score"),
                        "rel": s.get("text_relevance"),
                        "pin_id": pid,
                        "text": (s.get("text") or "")[:180],
                    },
                )

    return rows


def fill_high_ugc(
    rows: list[tuple[Path, dict]],
    need: int,
    seen: set[str],
) -> list[tuple[Path, dict]]:
    if need <= 0:
        return rows
    from core.ugc_classifier import get_ugc_live_classifier

    clf = get_ugc_live_classifier()
    if not clf.is_trained:
        print("ugc model not trained — cannot fill high-ugc")
        return rows

    have = {str(meta.get("pin_id") or pin_guess(p)) for p, meta in rows}
    have |= seen
    cands: list[Path] = []
    if CLEAN.is_dir():
        for p in CLEAN.iterdir():
            if p.is_file() and p.suffix.lower() in EXTS and not p.name.startswith("_"):
                if pin_guess(p) not in have:
                    cands.append(p)
    random.shuffle(cands)
    scan = cands[: max(need * 4, 800)]
    print(f"scoring {len(scan)} clean photos for ugc>={UGC_PASS} fill…")
    batch = 24
    scored: list[tuple[Path, float]] = []
    for i in range(0, len(scan), batch):
        chunk = scan[i : i + batch]
        imgs: list[Image.Image] = []
        ok: list[Path] = []
        for p in chunk:
            try:
                im = Image.open(p).convert("RGB")
                im.load()
                imgs.append(im)
                ok.append(p)
            except Exception:
                continue
        if not imgs:
            continue
        for p, sc in zip(ok, clf.predict_live_scores(imgs)):
            scored.append((p, float(sc)))
        for im in imgs:
            try:
                im.close()
            except Exception:
                pass
    scored.sort(key=lambda x: -x[1])
    added = 0
    for p, sc in scored:
        if sc < UGC_PASS:
            break
        pid = pin_guess(p)
        if pid in have:
            continue
        have.add(pid)
        rows.append(
            (
                p,
                {
                    "topic": "ugc-pass fill",
                    "mode": "ugc_pass_fill",
                    "carousel": "ugc_fill",
                    "prefix": "ugc",
                    "ugc": round(sc, 3),
                    "pin_id": pid,
                    "text": _rel(p),
                },
            )
        )
        added += 1
        if added >= need:
            break
    print(f"filled +{added} high-ugc")
    return rows


def build_system(n: int, seed: int) -> Path:
    random.seed(seed)
    seen = load_seen_pins()
    rows = collect_system_candidates(seen)
    print(f"system candidates (unseen)={len(rows)} target={n} labeled_pins={len(seen)}")
    random.shuffle(rows)
    if len(rows) < n:
        rows = fill_high_ugc(rows, n - len(rows), seen)
    random.shuffle(rows)
    rows = rows[:n]
    # prefer PASS/model_pick first in display? shuffle for labeling fairness
    random.shuffle(rows)

    run_name = f"taste_system_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = OUT / run_name
    items = _copy_items(run_dir, rows)
    modes: dict[str, int] = {}
    for it in items:
        modes[it["mode"]] = modes.get(it["mode"], 0) + 1
    print("modes:", modes)
    return _finalize(run_name, items, {"seed": seed, "case": "system", "modes": modes})


# ---------------------------------------------------------------------------
# Case A — random Pinterest harvest
# ---------------------------------------------------------------------------

def _save_clean(image: Image.Image, pin_id: str) -> Path | None:
    from taste_trainer_app import save_clean_candidate

    return save_clean_candidate(image, pin_id)


def harvest_random_pinterest(n: int, seen: set[str]) -> list[Path]:
    """Download ~n clean photos via Ideas/Related + random word queries (no taste filter)."""
    from taste_trainer_app import (
        is_blocked_image,
        is_clean_photo,
        load_history,
        synthesize_random_queries,
        title_looks_like_text,
    )
    from core.harvester import PinterestHarvester

    history = load_history()
    blocked = set(seen)
    # also hide already labeled from history
    for key in ("no", "yes", "seen"):
        blocked |= set(history.get(key) or [])

    harvester = PinterestHarvester(on_status=lambda m: print(f"  [pin] {m}"))
    saved: list[Path] = []
    saved_pids: set[str] = set()
    memory_pids: set[str] = set(blocked)

    def accept(cand) -> Path | None:
        if cand.pin_id in memory_pids or cand.pin_id in saved_pids:
            return None
        memory_pids.add(cand.pin_id)
        if not is_clean_photo(cand.image, cand.title):
            return None
        if is_blocked_image(cand.image, pin_id=cand.pin_id, history=history):
            return None
        path = _save_clean(cand.image, cand.pin_id)
        if path is None:
            return None
        saved.append(path)
        saved_pids.add(cand.pin_id)
        return path

    try:
        print("Pinterest warm…")
        try:
            harvester.warm()
        except Exception as exc:
            print(f"warm warn: {exc}")

        rounds = 0
        while len(saved) < n and rounds < 40:
            rounds += 1
            need = n - len(saved)
            print(f"\n=== feed round {rounds}  have={len(saved)}/{n} need={need} ===")
            try:
                feed = harvester.fetch_feed_metas(
                    limit=max(need + 80, 200),
                    related_seeds=16,
                    related_per_seed=20,
                )
            except Exception as exc:
                print(f"feed fail: {exc}")
                feed = []
            feed = [
                p
                for p in feed
                if p.pin_id not in memory_pids and not title_looks_like_text(p.title)
            ]
            print(f"feed metas: {len(feed)}")
            if feed:
                try:
                    kept, ai_n = harvester.filter_ai(feed)
                except Exception:
                    kept, ai_n = feed, 0
                kept = [p for p in kept if not title_looks_like_text(p.title)]
                random.shuffle(kept)
                print(f"after anti-AI: {len(kept)} (ai drop {ai_n})")
                chunk = 32
                for i in range(0, len(kept), chunk):
                    if len(saved) >= n:
                        break
                    batch = kept[i : i + chunk]
                    want = min(chunk, n - len(saved) + 8)
                    try:
                        cands, _ = asyncio.run(
                            harvester.download_candidates(
                                batch, "ideas-feed", limit=want
                            )
                        )
                    except Exception as exc:
                        print(f"dl fail: {exc}")
                        continue
                    for cand in cands:
                        if len(saved) >= n:
                            break
                        accept(cand)
                    print(f"  saved {len(saved)}/{n}")

            if len(saved) >= n:
                break

            # broad random queries
            qs = synthesize_random_queries(14)
            print(f"random queries: {len(qs)}")
            for raw_q in qs:
                if len(saved) >= n:
                    break
                try:
                    pins = harvester.search(raw_q)
                except Exception:
                    continue
                pins = [
                    p
                    for p in pins
                    if p.pin_id not in memory_pids
                    and not title_looks_like_text(p.title)
                ]
                if not pins:
                    continue
                try:
                    kept, _ = harvester.filter_ai(pins)
                except Exception:
                    kept = pins
                try:
                    cands, _ = asyncio.run(
                        harvester.download_candidates(kept[:36], raw_q, limit=12)
                    )
                except Exception:
                    continue
                for cand in cands:
                    if len(saved) >= n:
                        break
                    accept(cand)
                print(f"  q={raw_q!r} → saved {len(saved)}/{n}")

            if rounds >= 3 and len(saved) == 0:
                print("no progress — abort harvest")
                break
    finally:
        harvester.close()

    random.shuffle(saved)
    print(f"harvested {len(saved)}")
    return saved[:n]


def build_random(n: int, seed: int, *, harvest: bool = True) -> Path:
    random.seed(seed)
    seen = load_seen_pins()
    paths: list[Path] = []

    if harvest:
        paths = harvest_random_pinterest(n, seen)

    # top-up from unseen clean cache if harvest short
    if len(paths) < n and CLEAN.is_dir():
        have = {pin_guess(p) for p in paths} | seen
        local = [
            p
            for p in CLEAN.iterdir()
            if p.is_file()
            and p.suffix.lower() in EXTS
            and not p.name.startswith("_")
            and pin_guess(p) not in have
        ]
        random.shuffle(local)
        need = n - len(paths)
        paths.extend(local[:need])
        print(f"top-up from clean_photos +{min(need, len(local))} → {len(paths)}")

    random.shuffle(paths)
    paths = paths[:n]
    rows = [
        (
            p,
            {
                "topic": "random photo",
                "mode": "random_pinterest",
                "carousel": "random",
                "prefix": "rnd",
                "pin_id": pin_guess(p),
                "text": _rel(p),
            },
        )
        for p in paths
    ]

    run_name = f"taste_random_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = OUT / run_name
    items = _copy_items(run_dir, rows)
    return _finalize(
        run_name,
        items,
        {"seed": seed, "case": "random", "harvested": harvest},
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case", choices=["system", "random", "both"])
    ap.add_argument("--n", type=int, default=0, help="n for single case")
    ap.add_argument("--n-random", type=int, default=2000)
    ap.add_argument("--n-system", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--no-harvest",
        action="store_true",
        help="random case: only sample local clean cache",
    )
    args = ap.parse_args()
    seed = args.seed or (int(time.time()) % 10_000_000)

    paths: list[Path] = []
    if args.case in ("system", "both"):
        n = args.n if args.case == "system" and args.n else args.n_system
        paths.append(build_system(n, seed))
    if args.case in ("random", "both"):
        n = args.n if args.case == "random" and args.n else args.n_random
        paths.append(build_random(n, seed + 1, harvest=not args.no_harvest))

    for p in paths:
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
