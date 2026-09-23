#!/usr/bin/env python3
"""
download_all_carousels.py
=========================
Mass-download all carousel slides from reelfarm_database.db into downloaded_carousels/.

Examples:
  python download_all_carousels.py --limit 5
  python download_all_carousels.py --niche "self improvement"
  python download_all_carousels.py --min-saves 1000
  python download_all_carousels.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "reelfarm_database.db"
OUT_ROOT = ROOT / "downloaded_carousels"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://reel.farm/",
}

CONCURRENCY = 15
TIMEOUT_SEC = 10.0
RETRIES = 2  # retries after first failure => up to 3 attempts total
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}


@dataclass
class Carousel:
    id: str
    title: str
    niche: str
    product_medium: str
    views: Optional[int]
    likes: Optional[int]
    saves: Optional[int]
    slide_urls: list[str]
    audience_region: Optional[str] = None
    creator_unique_id: Optional[str] = None


@dataclass
class Stats:
    carousels_done: int = 0
    carousels_skipped: int = 0
    carousels_failed: int = 0
    images_ok: int = 0
    images_fail: int = 0
    bytes_ok: int = 0
    t0: float = 0.0

    def rate_img(self) -> float:
        dt = max(time.time() - self.t0, 1e-6)
        return self.images_ok / dt

    def rate_mib(self) -> float:
        dt = max(time.time() - self.t0, 1e-6)
        return (self.bytes_ok / (1024 * 1024)) / dt


def ext_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in (".jpeg", ".jpg", ".webp", ".png", ".gif", ".avif"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


def ext_from_content_type(ct: Optional[str], fallback: str) -> str:
    if not ct:
        return fallback
    ct = ct.split(";")[0].strip().lower()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/avif": ".avif",
    }
    return mapping.get(ct, fallback)


def load_carousels(
    db_path: Path,
    *,
    limit: Optional[int],
    niche: Optional[str],
    min_saves: Optional[int],
) -> list[Carousel]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    sql = """
        SELECT id, title, niche, product_medium, audience_region,
               views, likes, saves, slide_urls, creator_unique_id
        FROM slideshows
        WHERE 1=1
    """
    params: list[Any] = []
    if niche:
        sql += " AND lower(niche) = lower(?)"
        params.append(niche)
    if min_saves is not None:
        sql += " AND COALESCE(saves, 0) >= ?"
        params.append(min_saves)
    sql += " ORDER BY COALESCE(saves, 0) DESC, COALESCE(views, 0) DESC, id"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    out: list[Carousel] = []
    for r in rows:
        try:
            urls = json.loads(r["slide_urls"] or "[]")
        except json.JSONDecodeError:
            urls = []
        if not isinstance(urls, list):
            urls = []
        urls = [str(u).strip() for u in urls if u]
        if not urls:
            continue
        out.append(
            Carousel(
                id=str(r["id"]),
                title=r["title"] or "",
                niche=r["niche"] or "",
                product_medium=r["product_medium"] or "",
                views=r["views"],
                likes=r["likes"],
                saves=r["saves"],
                slide_urls=urls,
                audience_region=r["audience_region"],
                creator_unique_id=r["creator_unique_id"],
            )
        )
    return out


def slide_path(folder: Path, index: int, ext: str) -> Path:
    # User contract: 1.jpg, 2.jpg, ...
    return folder / f"{index}{ext}"


def existing_slide_files(folder: Path) -> dict[int, Path]:
    found: dict[int, Path] = {}
    if not folder.is_dir():
        return found
    for p in folder.iterdir():
        if not p.is_file():
            continue
        stem, suffix = p.stem, p.suffix.lower()
        if not stem.isdigit() or suffix not in IMAGE_EXTS and suffix != ".jpg":
            continue
        if p.stat().st_size <= 0:
            continue
        found[int(stem)] = p
    return found


def carousel_complete(folder: Path, n_slides: int) -> bool:
    if n_slides <= 0:
        return False
    existing = existing_slide_files(folder)
    meta = folder / "meta.json"
    if not meta.is_file():
        return False
    return all(i in existing for i in range(1, n_slides + 1))


def write_meta(folder: Path, car: Carousel) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": car.id,
        "title": car.title,
        "niche": car.niche,
        "product_medium": car.product_medium,
        "audience_region": car.audience_region,
        "creator_unique_id": car.creator_unique_id,
        "metrics": {
            "views": car.views,
            "likes": car.likes,
            "saves": car.saves,
            "bookmarks": car.saves,
        },
        "bookmarks": car.saves,
        "saves": car.saves,
        "slide_count": len(car.slide_urls),
        "slide_urls": car.slide_urls,
    }
    (folder / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def download_one(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    sem: asyncio.Semaphore,
) -> tuple[bool, int]:
    """Download a single image with retries. Returns (ok, bytes)."""
    fallback_ext = ext_from_url(url)
    # Prefer writing to final path with guessed ext; may rename after Content-Type.
    attempts = 1 + RETRIES
    last_err: Optional[BaseException] = None

    async with sem:
        for attempt in range(1, attempts + 1):
            try:
                async with client.stream("GET", url) as resp:
                    if resp.status_code >= 400:
                        raise httpx.HTTPStatusError(
                            f"HTTP {resp.status_code}",
                            request=resp.request,
                            response=resp,
                        )
                    ct = resp.headers.get("content-type")
                    ext = ext_from_content_type(ct, fallback_ext)
                    # Dest may have been created with a different ext — normalize.
                    final = dest.with_suffix(ext)
                    tmp = final.with_suffix(final.suffix + ".part")
                    size = 0
                    with open(tmp, "wb") as f:
                        async for chunk in resp.aiter_bytes(64 * 1024):
                            f.write(chunk)
                            size += len(chunk)
                    if size <= 0:
                        tmp.unlink(missing_ok=True)
                        raise IOError("empty body")
                    tmp.replace(final)
                    # Clean sibling numbered files with other extensions
                    for other in final.parent.glob(f"{final.stem}.*"):
                        if other == final or other.name.endswith(".part"):
                            continue
                        if other.suffix.lower() in IMAGE_EXTS or other.suffix.lower() == ".jpg":
                            if other.stem == final.stem:
                                other.unlink(missing_ok=True)
                    return True, size
            except (httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
                last_err = exc
                if attempt < attempts:
                    await asyncio.sleep(0.4 * attempt)
                continue
    return False, 0


def format_eta(seconds: float) -> str:
    if seconds < 0 or seconds != seconds or seconds == float("inf"):
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def print_progress(
    stats: Stats,
    carousel_i: int,
    carousel_total: int,
    car_id: str,
    status: str,
) -> None:
    done = stats.carousels_done + stats.carousels_skipped
    remaining = max(carousel_total - done, 0)
    # ETA based on finished carousels (incl. skips for wall time fairness use done rate)
    elapsed = max(time.time() - stats.t0, 1e-6)
    per = elapsed / max(done, 1)
    eta = format_eta(per * remaining)
    line = (
        f"\r[{carousel_i}/{carousel_total}] {status} {car_id[:12]}… "
        f"imgs={stats.images_ok} fail={stats.images_fail} skip={stats.carousels_skipped} "
        f"{stats.rate_img():5.1f} img/s  {stats.rate_mib():5.2f} MiB/s  ETA {eta}   "
    )
    sys.stdout.write(line[:140].ljust(140))
    sys.stdout.flush()


async def process_carousel(
    client: httpx.AsyncClient,
    car: Carousel,
    out_root: Path,
    sem: asyncio.Semaphore,
    stats: Stats,
    index: int,
    total: int,
) -> None:
    folder = out_root / car.id
    n = len(car.slide_urls)

    if carousel_complete(folder, n):
        stats.carousels_skipped += 1
        write_meta(folder, car)  # refresh meta
        print_progress(stats, index, total, car.id, "SKIP")
        return

    folder.mkdir(parents=True, exist_ok=True)
    existing = existing_slide_files(folder)

    tasks = []
    plan: list[tuple[int, str, Path]] = []
    for i, url in enumerate(car.slide_urls, start=1):
        if i in existing:
            continue
        ext = ext_from_url(url)
        dest = slide_path(folder, i, ext)
        plan.append((i, url, dest))

    # Download missing slides concurrently (global semaphore limits total)
    results = await asyncio.gather(
        *[download_one(client, url, dest, sem) for _, url, dest in plan],
        return_exceptions=True,
    )

    failed_any = False
    for (i, url, dest), result in zip(plan, results):
        if isinstance(result, Exception):
            stats.images_fail += 1
            failed_any = True
            continue
        ok, nbytes = result
        if ok:
            stats.images_ok += 1
            stats.bytes_ok += nbytes
        else:
            stats.images_fail += 1
            failed_any = True

    # Count already-present slides as progress visually once
    # (do not inflate images_ok repeatedly on resume)

    write_meta(folder, car)

    if carousel_complete(folder, n):
        stats.carousels_done += 1
        print_progress(stats, index, total, car.id, "OK  ")
    else:
        stats.carousels_failed += 1
        print_progress(stats, index, total, car.id, "FAIL")


async def run_download(
    carousels: list[Carousel],
    out_root: Path,
    concurrency: int = CONCURRENCY,
) -> Stats:
    out_root.mkdir(parents=True, exist_ok=True)
    stats = Stats(t0=time.time())
    sem = asyncio.Semaphore(concurrency)
    timeout = httpx.Timeout(TIMEOUT_SEC, connect=TIMEOUT_SEC)
    limits = httpx.Limits(max_connections=concurrency + 5, max_keepalive_connections=concurrency)

    async with httpx.AsyncClient(
        headers=HEADERS,
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
        http2=False,
    ) as client:
        total = len(carousels)
        # Process carousels with bounded in-flight carousel tasks so we don't
        # schedule 8k gather at once — pipeline of ~concurrency carousels.
        # Simpler & clearer: sequential carousels, parallel slides inside.
        # For speed across many small carousels, use a worker pool.
        queue: asyncio.Queue[Optional[tuple[int, Carousel]]] = asyncio.Queue()
        for i, car in enumerate(carousels, start=1):
            await queue.put((i, car))
        for _ in range(concurrency):
            await queue.put(None)

        async def worker() -> None:
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    return
                idx, car = item
                try:
                    await process_carousel(client, car, out_root, sem, stats, idx, total)
                except Exception as exc:
                    stats.carousels_failed += 1
                    print_progress(stats, idx, total, car.id, "ERR ")
                    # keep going
                    _ = exc
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
        await queue.join()
        for w in workers:
            await w

    sys.stdout.write("\n")
    return stats


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Download ReelFarm carousel slides to disk")
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Download only first N carousels (after filters). Default: all.",
    )
    p.add_argument(
        "--niche",
        type=str,
        default=None,
        help='Filter by niche, e.g. --niche "self improvement"',
    )
    p.add_argument(
        "--min-saves",
        type=int,
        default=None,
        dest="min_saves",
        help="Only carousels with saves/bookmarks >= N",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help=f"Path to SQLite DB (default: {DB_PATH.name})",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=OUT_ROOT,
        help=f"Output root (default: {OUT_ROOT.name})",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=CONCURRENCY,
        help=f"Max parallel image downloads (default: {CONCURRENCY})",
    )
    return p


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = build_argparser().parse_args()
    carousels = load_carousels(
        args.db,
        limit=args.limit,
        niche=args.niche,
        min_saves=args.min_saves,
    )
    if not carousels:
        print("No carousels matched filters.")
        return 1

    total_imgs = sum(len(c.slide_urls) for c in carousels)
    print(
        f"Queued {len(carousels)} carousels / {total_imgs} slides "
        f"(concurrency={args.concurrency})"
    )
    if args.niche:
        print(f"  niche filter: {args.niche!r}")
    if args.min_saves is not None:
        print(f"  min-saves: {args.min_saves}")
    if args.limit is not None:
        print(f"  limit: {args.limit}")
    print(f"  out: {args.out}")

    stats = asyncio.run(run_download(carousels, args.out, concurrency=args.concurrency))

    elapsed = max(time.time() - stats.t0, 1e-6)
    print("=" * 64)
    print(
        f"Done in {elapsed:.1f}s | "
        f"ok={stats.carousels_done} skip={stats.carousels_skipped} "
        f"fail_car={stats.carousels_failed} | "
        f"imgs_ok={stats.images_ok} imgs_fail={stats.images_fail} | "
        f"{stats.bytes_ok / (1024 * 1024):.1f} MiB | "
        f"{stats.rate_img():.1f} img/s"
    )
    print(f"Root: {args.out}")
    print("=" * 64)
    return 0 if stats.carousels_failed == 0 or stats.carousels_done + stats.carousels_skipped > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
