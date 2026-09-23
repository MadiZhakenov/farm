#!/usr/bin/env python3
"""
repair_broken_slides.py
=======================
Find missing / corrupt / VVIC (non-viewable) slides and repair them:
  - re-download from meta/DB/reel.farm URLs
  - convert VVIC (TikTok HEIF+VVC) -> JPEG via vvic_to_jpg + ffmpeg
  - validate with Pillow

Usage:
  python repair_broken_slides.py
  python repair_broken_slides.py --refresh-urls
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import httpx
from PIL import Image, ImageFile, UnidentifiedImageError

from vvic_to_jpg import is_vvic, vvic_to_jpg

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HAS_HEIF = True
except Exception:
    HAS_HEIF = False

ImageFile.LOAD_TRUNCATED_IMAGES = False

ROOT = Path(__file__).resolve().parent
ALL_DIR = ROOT / "downloaded_carousels" / "_all"
DB_PATH = ROOT / "reelfarm_database.db"
REPORT_PATH = ROOT / "broken_slides_report.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Referer": "https://reel.farm/",
}
CONCURRENCY = 12
TIMEOUT = 20.0
RETRIES = 3
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".vvic", ".heic", ".heif"}
MIN_BYTES = 500


@dataclass
class BrokenItem:
    folder: str
    carousel_id: str
    slide_index: int
    reason: str
    url: Optional[str] = None
    path: Optional[str] = None


@dataclass
class Stats:
    scanned_files: int = 0
    missing: int = 0
    corrupt: int = 0
    vvic_need_convert: int = 0
    fixed_download: int = 0
    fixed_convert: int = 0
    fail: int = 0


def ext_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in (".jpeg", ".jpg", ".webp", ".png", ".gif", ".avif"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


def ext_from_ct(ct: Optional[str], data: bytes, fallback: str) -> str:
    if data and is_vvic(data):
        return ".vvic"
    if ct:
        ct = ct.split(";")[0].strip().lower()
        mapping = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/vvic": ".vvic",
            "image/heif": ".heif",
            "image/heic": ".heic",
        }
        if ct in mapping:
            return mapping[ct]
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and b"WEBP" in data[:16]:
        return ".webp"
    return fallback


def list_slide_files(folder: Path) -> dict[int, Path]:
    out: dict[int, Path] = {}
    for p in folder.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        if not p.stem.isdigit():
            continue
        out[int(p.stem)] = p
    return out


def is_heif_ftyp(data: bytes) -> bool:
    if len(data) < 12 or data[4:8] != b"ftyp":
        return False
    brand = data[8:12]
    return brand in {b"heic", b"heif", b"mif1", b"msf1", b"avif"}


def heic_to_jpg(data: bytes, dest: Path) -> Path:
    if not HAS_HEIF:
        raise RuntimeError("pillow_heif not installed")
    from io import BytesIO

    with Image.open(BytesIO(data)) as im:
        im.convert("RGB").save(dest, format="JPEG", quality=92)
    return dest


def pillow_ok(path: Path) -> tuple[bool, str]:
    try:
        size = path.stat().st_size
    except OSError as e:
        return False, f"stat:{e}"
    if size < MIN_BYTES:
        return False, f"too_small:{size}"
    try:
        head = path.read_bytes()[:16]
    except OSError as e:
        return False, f"read:{e}"
    if len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] == b"vvic":
        return False, "vvic"
    # HEIC/AVIF without opener still counts as broken for viewers that expect jpg
    if len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in {b"heic", b"heif", b"mif1", b"msf1"}:
        if path.suffix.lower() != ".jpg":
            return False, "heic"
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            im.load()
            if im.size[0] < 8 or im.size[1] < 8:
                return False, "tiny_dims"
        return True, "ok"
    except UnidentifiedImageError:
        try:
            raw = path.read_bytes()
            if is_vvic(raw):
                return False, "vvic"
            if is_heif_ftyp(raw):
                return False, "heic"
        except OSError:
            pass
        return False, "unidentified"
    except Exception as e:
        return False, f"{type(e).__name__}"


def load_meta(folder: Path) -> dict[str, Any]:
    p = folder / "meta.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def carousel_id_of(folder: Path, meta: dict) -> str:
    return str(meta.get("original_id") or meta.get("id") or folder.name)


def scan_all(all_dir: Path) -> tuple[list[BrokenItem], Stats]:
    stats = Stats()
    broken: list[BrokenItem] = []
    folders = [p for p in all_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
    total = len(folders)
    for i, folder in enumerate(folders, 1):
        meta = load_meta(folder)
        urls = meta.get("slide_urls") or []
        if not isinstance(urls, list):
            urls = []
        n = int(meta.get("slide_count") or len(urls) or 0)
        files = list_slide_files(folder)
        cid = carousel_id_of(folder, meta)
        expected = max(n, max(files) if files else 0)
        for idx in range(1, expected + 1):
            url = urls[idx - 1] if idx - 1 < len(urls) else None
            path = files.get(idx)
            if path is None:
                stats.missing += 1
                broken.append(BrokenItem(folder.name, cid, idx, "missing", url=url))
                continue
            stats.scanned_files += 1
            ok, reason = pillow_ok(path)
            if ok:
                continue
            if reason == "vvic":
                stats.vvic_need_convert += 1
            else:
                stats.corrupt += 1
            broken.append(
                BrokenItem(folder.name, cid, idx, reason, url=url, path=str(path))
            )
        if i % 400 == 0 or i == total:
            print(
                f"\rscan {i}/{total} broken={len(broken)} "
                f"(miss={stats.missing} vvic={stats.vvic_need_convert} corrupt={stats.corrupt})",
                end="",
                flush=True,
            )
    print()
    return broken, stats


def load_db_urls() -> dict[str, list[str]]:
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(str(DB_PATH))
    out: dict[str, list[str]] = {}
    for cid, su in conn.execute("SELECT id, slide_urls FROM slideshows"):
        try:
            urls = json.loads(su or "[]")
        except json.JSONDecodeError:
            urls = []
        out[str(cid)] = [str(u) for u in urls if u]
    conn.close()
    return out


def extract_creators_from_html(html: str) -> list[dict]:
    pushes = re.findall(r"self\.__next_f\.push\((\[.*?\])\)\s*</script>", html, re.S)
    pushes.sort(key=len, reverse=True)
    for push in pushes[:5]:
        try:
            arr = json.loads(push)
        except json.JSONDecodeError:
            continue
        for item in arr if isinstance(arr, list) else []:
            if not (isinstance(item, str) and "recent_slideshows" in item):
                continue
            m = re.search(r'\[\{"id":\d+,"unique_id":', item)
            if not m:
                continue
            try:
                creators, _ = json.JSONDecoder().raw_decode(item[m.start() :])
            except json.JSONDecodeError:
                continue
            if isinstance(creators, list) and creators:
                return creators
    return []


def refresh_urls_from_reelfarm() -> dict[str, list[str]]:
    import hashlib

    print("Refreshing URLs from reel.farm ...")
    with httpx.Client(headers=HEADERS, timeout=120.0, follow_redirects=True) as client:
        r = client.get("https://reel.farm/dashboard/database")
        r.raise_for_status()
        creators = extract_creators_from_html(r.text)
    out: dict[str, list[str]] = {}
    for creator in creators:
        cid = creator.get("id")
        for idx, ss in enumerate(creator.get("recent_slideshows") or []):
            images = ss.get("images") or []
            if not images:
                continue
            seed = f"{cid}|{idx}|{images[0]}"
            sid = hashlib.sha1(seed.encode()).hexdigest()[:16]
            out[sid] = [str(u) for u in images]
    print(f"  refreshed slideshows={len(out)}")
    return out


def resolve_url(item: BrokenItem, overrides: dict[str, list[str]], db_urls: dict[str, list[str]]) -> Optional[str]:
    for urls in (
        overrides.get(item.carousel_id),
        db_urls.get(item.carousel_id),
        load_meta(ALL_DIR / item.folder).get("slide_urls"),
    ):
        if isinstance(urls, list) and item.slide_index - 1 < len(urls):
            return str(urls[item.slide_index - 1])
    return item.url


def url_variants(url: str) -> list[str]:
    """Try unsigned / alternate TikTok CDN hosts when signed URLs 403."""
    p = urlparse(url)
    out: list[str] = [url]
    bare = urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    out.append(bare)
    if "tiktokcdn" in p.netloc:
        host = p.netloc.replace("-sign", "")
        out.append(urlunparse((p.scheme, host, p.path, "", "", "")))
        # regional / mirror hosts with same object path
        for h in (
            "p16-common.tiktokcdn-us.com",
            "p19-common.tiktokcdn-us.com",
            "p16.tiktokcdn.com",
            "p16-sign.tiktokcdn-us.com",
            "p19-sign.tiktokcdn-us.com",
        ):
            out.append(urlunparse((p.scheme, h, p.path, "", "", "")))
    seen: set[str] = set()
    uniq: list[str] = []
    for u in out:
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


async def fetch_bytes(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> tuple[Optional[bytes], str, Optional[str]]:
    last = "unknown"
    ct = None
    candidates = url_variants(url)
    async with sem:
        for cand in candidates:
            for attempt in range(1, RETRIES + 1):
                try:
                    r = await client.get(cand)
                    ct = r.headers.get("content-type")
                    if r.status_code >= 400:
                        last = f"http_{r.status_code}"
                        await asyncio.sleep(0.15 * attempt)
                        continue
                    if len(r.content) < MIN_BYTES:
                        last = f"too_small:{len(r.content)}"
                        continue
                    return r.content, "ok", ct
                except Exception as e:
                    last = f"{type(e).__name__}:{e}"
                    await asyncio.sleep(0.15 * attempt)
            # next candidate after retries on this URL
    return None, last, ct


def save_as_viewable(folder: Path, idx: int, data: bytes, ct: Optional[str], url: str) -> tuple[bool, str]:
    """Save bytes as a Pillow-openable JPEG (converting VVIC/HEIC if needed)."""
    # wipe old index.*
    for p in folder.glob(f"{idx}.*"):
        if p.suffix.lower() in IMAGE_EXTS or p.name.endswith(".part"):
            p.unlink(missing_ok=True)

    if is_vvic(data):
        tmp = folder / f"{idx}.vvic"
        tmp.write_bytes(data)
        dest = folder / f"{idx}.jpg"
        try:
            vvic_to_jpg(data, dest)
            tmp.unlink(missing_ok=True)
            ok, reason = pillow_ok(dest)
            return ok, ("converted_vvic" if ok else reason)
        except Exception as e:
            return False, f"vvic_convert:{type(e).__name__}:{e}"

    if is_heif_ftyp(data) or (ct and "heic" in ct.lower()) or ".heic" in url.lower():
        dest = folder / f"{idx}.jpg"
        try:
            heic_to_jpg(data, dest)
            ok, reason = pillow_ok(dest)
            return ok, ("converted_heic" if ok else reason)
        except Exception as e:
            # fall through to raw save
            heic_err = f"heic_convert:{type(e).__name__}:{e}"
        else:
            heic_err = None
    else:
        heic_err = None

    ext = ext_from_ct(ct, data, ext_from_url(url))
    if ext in {".vvic", ".heic", ".heif"}:
        tmp = folder / f"{idx}{ext}"
        tmp.write_bytes(data)
        dest = folder / f"{idx}.jpg"
        try:
            if ext == ".vvic" or is_vvic(data):
                vvic_to_jpg(data, dest)
            else:
                heic_to_jpg(data, dest)
            tmp.unlink(missing_ok=True)
            ok, reason = pillow_ok(dest)
            return ok, ("converted" if ok else reason)
        except Exception as e:
            return False, heic_err or f"convert:{e}"

    dest = folder / f"{idx}{ext}"
    dest.write_bytes(data)
    ok, reason = pillow_ok(dest)
    if ok:
        return True, "downloaded"
    if is_vvic(data):
        try:
            vvic_to_jpg(data, folder / f"{idx}.jpg")
            dest.unlink(missing_ok=True)
            ok2, reason2 = pillow_ok(folder / f"{idx}.jpg")
            return ok2, ("converted_vvic" if ok2 else reason2)
        except Exception as e:
            return False, f"vvic_convert:{e}"
    if is_heif_ftyp(data):
        try:
            heic_to_jpg(data, folder / f"{idx}.jpg")
            dest.unlink(missing_ok=True)
            ok2, reason2 = pillow_ok(folder / f"{idx}.jpg")
            return ok2, ("converted_heic" if ok2 else reason2)
        except Exception as e:
            return False, heic_err or f"heic_convert:{e}"
    return False, reason


async def repair(broken: list[BrokenItem], overrides: dict[str, list[str]], db_urls: dict[str, list[str]], stats: Stats) -> list[dict]:
    sem = asyncio.Semaphore(CONCURRENCY)
    results: list[dict] = []
    timeout = httpx.Timeout(TIMEOUT, connect=TIMEOUT)

    async with httpx.AsyncClient(headers=HEADERS, timeout=timeout, follow_redirects=True) as client:
        total = len(broken)

        async def one(item: BrokenItem) -> None:
            folder = ALL_DIR / item.folder
            folder.mkdir(parents=True, exist_ok=True)

            # If local VVIC/HEIC exists, convert without re-download first
            local = Path(item.path) if item.path else None
            if local and local.exists():
                raw = local.read_bytes()
                if is_vvic(raw) or item.reason == "vvic" or is_heif_ftyp(raw) or item.reason == "heic":
                    ok, reason = await asyncio.to_thread(
                        save_as_viewable, folder, item.slide_index, raw, None, item.url or ""
                    )
                    if ok:
                        if "convert" in reason:
                            stats.fixed_convert += 1
                        else:
                            stats.fixed_download += 1
                        results.append({**item.__dict__, "fix": reason})
                        return

            url = resolve_url(item, overrides, db_urls)
            if not url:
                stats.fail += 1
                results.append({**item.__dict__, "fix": "no_url"})
                return

            data, status, ct = await fetch_bytes(client, url, sem)
            if data is None:
                stats.fail += 1
                results.append({**item.__dict__, "fix": status, "url": url})
                return

            ok, reason = await asyncio.to_thread(save_as_viewable, folder, item.slide_index, data, ct, url)
            if ok:
                if "convert" in reason:
                    stats.fixed_convert += 1
                else:
                    stats.fixed_download += 1
                results.append({**item.__dict__, "fix": reason, "url": url})
            else:
                stats.fail += 1
                results.append({**item.__dict__, "fix": reason, "url": url})

            done = stats.fixed_convert + stats.fixed_download + stats.fail
            if done % 25 == 0 or done == total:
                print(
                    f"\rrepair {done}/{total} ok_dl={stats.fixed_download} "
                    f"ok_conv={stats.fixed_convert} fail={stats.fail}",
                    end="",
                    flush=True,
                )

        await asyncio.gather(*(one(b) for b in broken))
    print()
    return results


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-urls", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--scan-only", action="store_true")
    ap.add_argument(
        "--from-report",
        action="store_true",
        help="Skip full disk scan; repair items still broken from broken_slides_report.json",
    )
    args = ap.parse_args()

    if not ALL_DIR.is_dir():
        print(f"Missing {ALL_DIR}")
        return 1

    t0 = time.time()
    stats = Stats()
    broken: list[BrokenItem] = []

    if args.from_report and REPORT_PATH.is_file():
        prev = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        print(f"Loading {REPORT_PATH} ...")
        for row in prev.get("broken") or []:
            folder = ALL_DIR / row["folder"]
            files = list_slide_files(folder)
            idx = int(row["slide_index"])
            p = files.get(idx)
            if p is not None:
                ok, reason = pillow_ok(p)
                if ok:
                    continue
                broken.append(
                    BrokenItem(
                        folder=row["folder"],
                        carousel_id=row.get("carousel_id") or "",
                        slide_index=idx,
                        reason=reason,
                        url=row.get("url"),
                        path=str(p),
                    )
                )
                if reason == "vvic":
                    stats.vvic_need_convert += 1
                else:
                    stats.corrupt += 1
            else:
                broken.append(
                    BrokenItem(
                        folder=row["folder"],
                        carousel_id=row.get("carousel_id") or "",
                        slide_index=idx,
                        reason="missing",
                        url=row.get("url"),
                        path=None,
                    )
                )
                stats.missing += 1
        print(
            f"Still broken from report: {len(broken)} "
            f"(missing={stats.missing}, vvic={stats.vvic_need_convert}, corrupt={stats.corrupt})"
        )
    else:
        print(f"Scanning {ALL_DIR} ...")
        broken, stats = scan_all(ALL_DIR)
        print(
            f"Broken: {len(broken)} (missing={stats.missing}, vvic={stats.vvic_need_convert}, corrupt={stats.corrupt})"
        )

    report: dict[str, Any] = {
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "broken_count": len(broken),
        "stats": stats.__dict__,
        "broken": [b.__dict__ for b in broken],
    }

    if args.scan_only or not broken:
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {REPORT_PATH}")
        return 0

    overrides: dict[str, list[str]] = {}
    if args.refresh_urls:
        try:
            overrides = refresh_urls_from_reelfarm()
        except Exception as e:
            print(f"refresh failed: {e}")

    db_urls = load_db_urls()
    todo = broken[: args.limit] if args.limit else broken
    print(f"Repairing {len(todo)} ...")
    results = asyncio.run(repair(todo, overrides, db_urls, stats))
    report["repair_results"] = results
    report["stats"] = stats.__dict__

    # verify affected
    still = []
    for name in {b.folder for b in todo}:
        folder = ALL_DIR / name
        meta = load_meta(folder)
        urls = meta.get("slide_urls") or []
        n = int(meta.get("slide_count") or len(urls) or 0)
        files = list_slide_files(folder)
        for idx in range(1, n + 1):
            p = files.get(idx)
            if p is None:
                still.append({"folder": name, "slide": idx, "reason": "still_missing"})
                continue
            ok, reason = pillow_ok(p)
            if not ok:
                still.append({"folder": name, "slide": idx, "reason": reason, "path": str(p)})

    report["still_broken_after_repair"] = still
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 64)
    print(f"Done in {time.time() - t0:.1f}s")
    print(f"  fixed_download={stats.fixed_download}")
    print(f"  fixed_convert={stats.fixed_convert}")
    print(f"  fail={stats.fail}")
    print(f"  still_broken={len(still)}")
    print(f"  report={REPORT_PATH}")
    print("=" * 64)
    return 0 if not still else 2


if __name__ == "__main__":
    raise SystemExit(main())
