#!/usr/bin/env python3
"""
Изолированный стресс-тест скачивания картинок с Pinterest CDN (Тест 1).

Запуск:
  python test_pinterest_downloader.py
  python test_pinterest_downloader.py --cleanup
  python test_pinterest_downloader.py --no-prompt
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

TARGET_COUNT = 50
CONCURRENCY = 5
REQUEST_TIMEOUT = 5.0
DOWNLOAD_DIR = Path("test_downloads")
INBOX_DIR = Path("inbox")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.pinterest.com/",
}

# 50 реальных публичных ссылок i.pinimg.com/originals/... (fallback, если inbox пуст)
HARDCODED_PINIMG_URLS: list[str] = [
    "https://i.pinimg.com/originals/03/17/bb/0317bbfc8a48c41661786e6bd1e7eb15.jpg",
    "https://i.pinimg.com/originals/03/ef/d3/03efd333fce2f1b6b7bd8fb207b19b78.jpg",
    "https://i.pinimg.com/originals/04/da/a6/04daa6ea649ac350b3a2ba7eecd83647.jpg",
    "https://i.pinimg.com/originals/07/c2/c7/07c2c75027f6364ff61d474c6e0fdba5.jpg",
    "https://i.pinimg.com/originals/0c/f0/b8/0cf0b88f3377c8f5a47a73c9cd947e89.png",
    "https://i.pinimg.com/originals/0f/2a/df/0f2adf0c7f2f87af97358a435ffbf539.jpg",
    "https://i.pinimg.com/originals/16/5b/79/165b7950a69a62e3f4d31fc2c227020a.jpg",
    "https://i.pinimg.com/originals/16/5b/79/165b7950a69a62e3f4d31fc2c227020a.png",
    "https://i.pinimg.com/originals/19/d8/77/19d877f0d7eb2af146a42c932dc7c908.png",
    "https://i.pinimg.com/originals/1e/67/1c/1e671cfe2bc7b4076b5bbe99e8320766.jpg",
    "https://i.pinimg.com/originals/20/fb/c6/20fbc6d65fcb4fa5d19c427efcc4e5f1.jpg",
    "https://i.pinimg.com/originals/24/44/51/244451547905ded271a2ebbee3e75e2e.jpg",
    "https://i.pinimg.com/originals/27/5c/fc/275cfc51e60c6e3ef11101b3890bafa8.jpg",
    "https://i.pinimg.com/originals/2b/33/3a/2b333a2b558f3bed5025479c64b887e0.jpg",
    "https://i.pinimg.com/originals/2b/e3/59/2be3591bcb02b242276c3989a839131c.png",
    "https://i.pinimg.com/originals/2e/39/67/2e3967246b0f0573c18c3ea38cabbe68.jpg",
    "https://i.pinimg.com/originals/36/aa/c6/36aac66fdcd12318a52da078da180165.jpg",
    "https://i.pinimg.com/originals/39/69/01/396901b74b625c315de597b780438fbf.jpg",
    "https://i.pinimg.com/originals/3d/06/97/3d069735f40ee97cb26a5bfb064edde7.jpg",
    "https://i.pinimg.com/originals/41/74/1b/41741bbcc900e1bd9f2330088a76c159.png",
    "https://i.pinimg.com/originals/41/bd/0e/41bd0e3907b3ccffadd8a5b89e50827d.png",
    "https://i.pinimg.com/originals/4c/06/ef/4c06efbdd740854f0d2814ab3f412ab8.png",
    "https://i.pinimg.com/originals/54/3d/57/543d57daebf4665fb136413ab8fc179a.jpg",
    "https://i.pinimg.com/originals/68/f0/cb/68f0cbbc0a989d949950a81457b1c852.png",
    "https://i.pinimg.com/originals/74/87/f7/7487f7f68ceb2bf440e79d190ec90a63.jpg",
    "https://i.pinimg.com/originals/77/a5/b3/77a5b370b6c7152cff3687ec993e4276.jpg",
    "https://i.pinimg.com/originals/7c/00/23/7c00233dcfa08128982e0c4a0d015b85.jpg",
    "https://i.pinimg.com/originals/7e/dc/5e/7edc5eef2dba5d6046244d4c6c249399.jpg",
    "https://i.pinimg.com/originals/80/2b/15/802b158e28a09a8a18b499a34dfdecc0.jpg",
    "https://i.pinimg.com/originals/81/25/a7/8125a74b2f94fc17b95ce0136f88d180.jpg",
    "https://i.pinimg.com/originals/81/e4/d8/81e4d8ad7b4c4ebcf8c10ae280533491.jpg",
    "https://i.pinimg.com/originals/83/6f/07/836f07b72efff700202a09864790a4b3.jpg",
    "https://i.pinimg.com/originals/92/a6/ac/92a6ac7bcf10ec70f4d52bdd0130af4f.jpg",
    "https://i.pinimg.com/originals/97/87/70/978770838c4b81c60757396e97fee063.jpg",
    "https://i.pinimg.com/originals/a5/34/10/a53410467aa1a6b63f8966e4a9d516be.jpg",
    "https://i.pinimg.com/originals/a7/dc/42/a7dc42c2beed91f286e660433afa4d14.jpg",
    "https://i.pinimg.com/originals/a7/dc/42/a7dc42c2beed91f286e660433afa4d14.png",
    "https://i.pinimg.com/originals/ad/3a/27/ad3a2707406a9a8a993a829c4b8e6231.jpg",
    "https://i.pinimg.com/originals/ad/3a/27/ad3a2707406a9a8a993a829c4b8e6231.png",
    "https://i.pinimg.com/originals/ae/13/2c/ae132c10893d7f407384d13083203a74.jpg",
    "https://i.pinimg.com/originals/af/b9/aa/afb9aa5fbf0dbce98c52fe246601044c.jpg",
    "https://i.pinimg.com/originals/b0/19/a9/b019a9a80e2af476e922f4029285a7aa.png",
    "https://i.pinimg.com/originals/b1/44/00/b1440002d558358dbc6134886e1b21bb.jpg",
    "https://i.pinimg.com/originals/b2/62/00/b2620061ca887c12a7fc152d92c48b41.png",
    "https://i.pinimg.com/originals/b4/b7/74/b4b7742e21e675f2fb1dbc3064a15f96.jpg",
    "https://i.pinimg.com/originals/c2/28/36/c2283641e55e4b84bc6dd34144b87568.png",
    "https://i.pinimg.com/originals/c4/86/2f/c4862fc2086b36c2256fe753639f601a.jpg",
    "https://i.pinimg.com/originals/c7/e0/a6/c7e0a69115ac7236dbcab3e92576d4dd.jpg",
    "https://i.pinimg.com/originals/c9/ec/1e/c9ec1ea9f046d50dd5ebdcbba5fbd7b7.jpg",
    "https://i.pinimg.com/originals/ca/45/0a/ca450ae148d48732f4371e44db1a2be7.jpg",
]


# ---------------------------------------------------------------------------
# Модели / метрики
# ---------------------------------------------------------------------------

@dataclass
class DownloadResult:
    index: int
    url: str
    ok: bool
    via_fallback: bool = False
    bytes_downloaded: int = 0
    status_codes: list[int] = field(default_factory=list)
    error: str | None = None
    saved_as: str | None = None


@dataclass
class Stats:
    original_ok: int = 0
    fallback_ok: int = 0
    failed: int = 0
    bytes_total: int = 0
    saw_403: bool = False
    saw_429: bool = False
    elapsed_sec: float = 0.0


# ---------------------------------------------------------------------------
# Загрузка ссылок
# ---------------------------------------------------------------------------

def _looks_like_pinimg(url: str) -> bool:
    return isinstance(url, str) and "i.pinimg.com" in url and url.startswith("http")


def _extract_image_url_orig(obj: Any, out: list[str]) -> None:
    if isinstance(obj, dict):
        val = obj.get("image_url_orig")
        if _looks_like_pinimg(val):
            out.append(val)
        for v in obj.values():
            _extract_image_url_orig(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _extract_image_url_orig(item, out)


def load_urls_from_inbox(limit: int = TARGET_COUNT) -> list[str]:
    """Достаёт уникальные image_url_orig из inbox/*.jsonl."""
    if not INBOX_DIR.is_dir():
        return []

    found: list[str] = []
    seen: set[str] = set()

    for path in sorted(INBOX_DIR.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            bucket: list[str] = []
            _extract_image_url_orig(row, bucket)
            for url in bucket:
                if url not in seen:
                    seen.add(url)
                    found.append(url)
                if len(found) >= limit:
                    return found
    return found


def corrupt_three_urls(urls: list[str]) -> list[str]:
    """Намеренно портит 3 ссылки так, чтобы они давали 404."""
    result = list(urls)
    corrupt_indices = [0, len(result) // 2, len(result) - 1]
    for i, idx in enumerate(corrupt_indices):
        parsed = urlparse(result[idx])
        # Битый путь: несуществующий hash в originals
        broken = (
            f"{parsed.scheme}://{parsed.netloc}/originals/"
            f"00/00/0{i}/deadbeef404test{i:02d}000000000000000000.jpg"
        )
        result[idx] = broken
    return result


def prepare_url_list() -> tuple[list[str], str]:
    inbox_urls = load_urls_from_inbox(TARGET_COUNT)
    if len(inbox_urls) >= TARGET_COUNT:
        source = f"inbox/*.jsonl ({len(inbox_urls)} найдено, берём {TARGET_COUNT})"
        urls = inbox_urls[:TARGET_COUNT]
    else:
        source = (
            f"hardcoded fallback "
            f"(inbox дал {len(inbox_urls)}, нужно {TARGET_COUNT})"
        )
        urls = HARDCODED_PINIMG_URLS[:TARGET_COUNT]

    if len(urls) < TARGET_COUNT:
        raise RuntimeError(
            f"Недостаточно ссылок: {len(urls)} < {TARGET_COUNT}. "
            "Добавьте inbox/*.jsonl или расширьте HARDCODED_PINIMG_URLS."
        )

    return corrupt_three_urls(urls), source


# ---------------------------------------------------------------------------
# Сетевая логика
# ---------------------------------------------------------------------------

def to_736x(url: str) -> str:
    return url.replace("/originals/", "/736x/")


def filename_for(index: int, url: str, via_fallback: bool) -> str:
    name = Path(urlparse(url).path).name or f"image_{index}.bin"
    stem = Path(name).stem
    suffix = Path(name).suffix or ".jpg"
    tag = "736x" if via_fallback else "orig"
    return f"{index:03d}_{tag}_{stem[:40]}{suffix}"


async def fetch_once(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[int | None, bytes | None, str | None]:
    """Один GET. Возвращает (status, body, error)."""
    try:
        resp = await client.get(url)
        status = resp.status_code
        if status == 200 and resp.content:
            return status, resp.content, None
        return status, None, f"HTTP {status}"
    except httpx.TimeoutException:
        return None, None, "timeout"
    except httpx.HTTPError as exc:
        return None, None, f"http_error: {exc.__class__.__name__}"


async def download_one(
    index: int,
    url: str,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    out_dir: Path,
) -> DownloadResult:
    async with sem:
        result = DownloadResult(index=index, url=url, ok=False)

        # Попытка 1: originals
        status, body, err = await fetch_once(client, url)
        if status is not None:
            result.status_codes.append(status)
        if body is not None:
            path = out_dir / filename_for(index, url, via_fallback=False)
            path.write_bytes(body)
            result.ok = True
            result.bytes_downloaded = len(body)
            result.saved_as = path.name
            return result

        # План Б только при 404 / 403 / timeout
        trigger_fallback = err == "timeout" or status in {404, 403}
        if not trigger_fallback:
            result.error = err or "unknown"
            return result

        fallback_url = to_736x(url)
        if fallback_url == url:
            result.error = f"{err}; no /originals/ to rewrite"
            return result

        status2, body2, err2 = await fetch_once(client, fallback_url)
        if status2 is not None:
            result.status_codes.append(status2)
        if body2 is not None:
            path = out_dir / filename_for(index, fallback_url, via_fallback=True)
            path.write_bytes(body2)
            result.ok = True
            result.via_fallback = True
            result.bytes_downloaded = len(body2)
            result.saved_as = path.name
            result.error = f"orig failed ({err}), saved via /736x/"
            return result

        result.error = f"orig={err}; fallback={err2}"
        return result


async def run_downloads(urls: list[str], out_dir: Path) -> tuple[list[DownloadResult], Stats]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(CONCURRENCY)
    timeout = httpx.Timeout(REQUEST_TIMEOUT)
    limits = httpx.Limits(max_connections=CONCURRENCY, max_keepalive_connections=CONCURRENCY)

    t0 = time.perf_counter()
    async with httpx.AsyncClient(
        headers=HEADERS,
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
    ) as client:
        tasks = [
            download_one(i, url, client, sem, out_dir)
            for i, url in enumerate(urls, start=1)
        ]
        results = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - t0

    stats = Stats(elapsed_sec=elapsed)
    for r in results:
        for code in r.status_codes:
            if code == 403:
                stats.saw_403 = True
            if code == 429:
                stats.saw_429 = True
        if r.ok and r.via_fallback:
            stats.fallback_ok += 1
            stats.bytes_total += r.bytes_downloaded
        elif r.ok:
            stats.original_ok += 1
            stats.bytes_total += r.bytes_downloaded
        else:
            stats.failed += 1

    return list(results), stats


# ---------------------------------------------------------------------------
# Отчёт / cleanup
# ---------------------------------------------------------------------------

def print_report(stats: Stats, source: str, total: int = TARGET_COUNT) -> None:
    mb = stats.bytes_total / (1024 * 1024)
    speed = mb / stats.elapsed_sec if stats.elapsed_sec > 0 else 0.0
    blocked = stats.saw_403 or stats.saw_429
    block_detail = []
    if stats.saw_403:
        block_detail.append("403")
    if stats.saw_429:
        block_detail.append("429")

    line = "=" * 60
    print()
    print(line)
    print("  Pinterest CDN Downloader — Тест 1 (стресс)")
    print(line)
    print(f"  Источник ссылок : {source}")
    print(f"  Параллельность  : {CONCURRENCY}")
    print(f"  Таймаут         : {REQUEST_TIMEOUT:.0f} с")
    print(f"  Папка           : {DOWNLOAD_DIR.resolve()}")
    print("-" * 60)
    print(f"  Общее время выполнения     : {stats.elapsed_sec:.2f} с")
    print(f"  Успешно оригиналов         : {stats.original_ok} / {total}")
    print(f"  Спасено через план Б /736x/: {stats.fallback_ok}")
    print(f"  Полные отказы              : {stats.failed}")
    print(
        f"  Блокировки (403/429)       : "
        f"{'ДА (' + ', '.join(block_detail) + ')' if blocked else 'нет'}"
    )
    print(f"  Скачано данных             : {mb:.2f} МБ")
    print(f"  Средняя скорость           : {speed:.2f} МБ/с")
    print(line)
    print()


def cleanup_downloads(prompt: bool, force: bool) -> None:
    if not DOWNLOAD_DIR.exists():
        print("Папка test_downloads/ отсутствует — очищать нечего.")
        return

    if force:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        print("Папка test_downloads/ удалена (--cleanup).")
        return

    if not prompt:
        print(
            "Файлы оставлены в test_downloads/. "
            "Очистка: python test_pinterest_downloader.py --cleanup"
        )
        return

    try:
        answer = input("Очистить папку test_downloads/? [y/N]: ").strip().lower()
    except EOFError:
        answer = "n"

    if answer in {"y", "yes", "д", "да"}:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        print("Папка test_downloads/ удалена.")
    else:
        print("Файлы оставлены в test_downloads/.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Стресс-тест скачивания с Pinterest CDN (Тест 1)."
    )
    p.add_argument(
        "--cleanup",
        action="store_true",
        help="Только удалить test_downloads/ и выйти (без скачивания).",
    )
    p.add_argument(
        "--no-prompt",
        action="store_true",
        help="После теста не спрашивать про очистку (файлы останутся).",
    )
    p.add_argument(
        "--cleanup-after",
        action="store_true",
        help="После теста сразу удалить test_downloads/ без вопроса.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    # Читаемый кириллический отчёт в консоли Windows
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = parse_args(argv)

    if args.cleanup:
        cleanup_downloads(prompt=False, force=True)
        return 0

    print("Готовим список из 50 ссылок (3 намеренно битые)...")
    urls, source = prepare_url_list()
    print(f"Источник: {source}")
    print(f"Стартуем {TARGET_COUNT} загрузок, concurrency={CONCURRENCY}...")

    results, stats = asyncio.run(run_downloads(urls, DOWNLOAD_DIR))
    print_report(stats, source)

    # Краткий список отказов (если есть)
    fails = [r for r in results if not r.ok]
    if fails:
        print(f"Отказы ({len(fails)}):")
        for r in fails[:10]:
            print(f"  [{r.index:02d}] {r.error} | {r.url[:80]}")
        if len(fails) > 10:
            print(f"  ... и ещё {len(fails) - 10}")
        print()

    if args.cleanup_after:
        cleanup_downloads(prompt=False, force=True)
    else:
        cleanup_downloads(prompt=not args.no_prompt, force=False)

    return 0 if stats.failed < TARGET_COUNT else 1


if __name__ == "__main__":
    sys.exit(main())
