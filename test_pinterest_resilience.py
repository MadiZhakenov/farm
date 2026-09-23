#!/usr/bin/env python3
"""
Глубокая проверка устойчивости Pinterest (Тест А: стресс CDN + Тест Б: воскрешение pin_id).

Запуск:
  python test_pinterest_resilience.py
"""

from __future__ import annotations

import asyncio
import json
import re
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

INBOX_DIR = Path("inbox")
CDN_TARGET_MIN = 150
CDN_TARGET_MAX = 200
CDN_CONCURRENCY = 10
CDN_TIMEOUT = 8.0
PIN_TARGET = 5
PIN_TIMEOUT = 20.0

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

CDN_HEADERS = {
    "User-Agent": CHROME_UA,
    "Referer": "https://www.pinterest.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

PAGE_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.pinterest.com/",
    "Upgrade-Insecure-Requests": "1",
}

# Реальные публичные pin_id (проверены: отдают og:image без loginwall)
HARDCODED_PIN_IDS: list[str] = [
    "158259374379943925",
    "340936634317338069",
    "9922061675589894",
    "26388347813800004",
    "260505159692582028",
    "899664463056209065",
    "34832597116688634",
    "151855818681651786",
    "2111131073949384",
    "10062799164698488",
]

# Хэши публичных CDN-картинок; разворачиваются в несколько size-tiers → 150–200 URL
_PINIMG_HASHES: list[str] = [
    "03/17/bb/0317bbfc8a48c41661786e6bd1e7eb15.jpg",
    "03/ef/d3/03efd333fce2f1b6b7bd8fb207b19b78.jpg",
    "04/da/a6/04daa6ea649ac350b3a2ba7eecd83647.jpg",
    "07/c2/c7/07c2c75027f6364ff61d474c6e0fdba5.jpg",
    "0c/f0/b8/0cf0b88f3377c8f5a47a73c9cd947e89.png",
    "0f/2a/df/0f2adf0c7f2f87af97358a435ffbf539.jpg",
    "16/5b/79/165b7950a69a62e3f4d31fc2c227020a.jpg",
    "16/5b/79/165b7950a69a62e3f4d31fc2c227020a.png",
    "19/d8/77/19d877f0d7eb2af146a42c932dc7c908.png",
    "1e/67/1c/1e671cfe2bc7b4076b5bbe99e8320766.jpg",
    "20/fb/c6/20fbc6d65fcb4fa5d19c427efcc4e5f1.jpg",
    "24/44/51/244451547905ded271a2ebbee3e75e2e.jpg",
    "2b/33/3a/2b333a2b558f3bed5025479c64b887e0.jpg",
    "2b/e3/59/2be3591bcb02b242276c3989a839131c.png",
    "2e/39/67/2e3967246b0f0573c18c3ea38cabbe68.jpg",
    "36/aa/c6/36aac66fdcd12318a52da078da180165.jpg",
    "39/69/01/396901b74b625c315de597b780438fbf.jpg",
    "3d/06/97/3d069735f40ee97cb26a5bfb064edde7.jpg",
    "41/74/1b/41741bbcc900e1bd9f2330088a76c159.png",
    "41/bd/0e/41bd0e3907b3ccffadd8a5b89e50827d.png",
    "4c/06/ef/4c06efbdd740854f0d2814ab3f412ab8.png",
    "54/3d/57/543d57daebf4665fb136413ab8fc179a.jpg",
    "68/f0/cb/68f0cbbc0a989d949950a81457b1c852.png",
    "74/87/f7/7487f7f68ceb2bf440e79d190ec90a63.jpg",
    "77/a5/b3/77a5b370b6c7152cff3687ec993e4276.jpg",
    "7c/00/23/7c00233dcfa08128982e0c4a0d015b85.jpg",
    "7e/dc/5e/7edc5eef2dba5d6046244d4c6c249399.jpg",
    "80/2b/15/802b158e28a09a8a18b499a34dfdecc0.jpg",
    "81/25/a7/8125a74b2f94fc17b95ce0136f88d180.jpg",
    "81/e4/d8/81e4d8ad7b4c4ebcf8c10ae280533491.jpg",
    "83/6f/07/836f07b72efff700202a09864790a4b3.jpg",
    "92/a6/ac/92a6ac7bcf10ec70f4d52bdd0130af4f.jpg",
    "97/87/70/978770838c4b81c60757396e97fee063.jpg",
    "a5/34/10/a53410467aa1a6b63f8966e4a9d516be.jpg",
    "a7/dc/42/a7dc42c2beed91f286e660433afa4d14.jpg",
    "a7/dc/42/a7dc42c2beed91f286e660433afa4d14.png",
    "ad/3a/27/ad3a2707406a9a8a993a829c4b8e6231.jpg",
    "ad/3a/27/ad3a2707406a9a8a993a829c4b8e6231.png",
    "ae/13/2c/ae132c10893d7f407384d13083203a74.jpg",
    "af/b9/aa/afb9aa5fbf0dbce98c52fe246601044c.jpg",
    "b0/19/a9/b019a9a80e2af476e922f4029285a7aa.png",
    "b1/44/00/b1440002d558358dbc6134886e1b21bb.jpg",
    "b2/62/00/b2620061ca887c12a7fc152d92c48b41.png",
    "b4/b7/74/b4b7742e21e675f2fb1dbc3064a15f96.jpg",
    "c2/28/36/c2283641e55e4b84bc6dd34144b87568.png",
    "c4/86/2f/c4862fc2086b36c2256fe753639f601a.jpg",
    "c7/e0/a6/c7e0a69115ac7236dbcab3e92576d4dd.jpg",
    "c9/ec/1e/c9ec1ea9f046d50dd5ebdcbba5fbd7b7.jpg",
    "ca/45/0a/ca450ae148d48732f4371e44db1a2be7.jpg",
    "cf/78/a4/cf78a41911e36f2f75ae3942ac27fd26.jpg",
    "d1/31/76/d13176f9a5ed82aa6b8216a2310fd160.jpg",
    "d5/3b/01/d53b014d86a6b6761bf649a0ed813c2b.png",
    "d7/eb/ed/d7ebedcc76a4cd8c16917e2cb58bfef0.jpg",
    "da/0d/06/da0d0600684d25c98c8386c6d423fb00.jpg",
    "e0/00/a9/e000a96b64a4a776bf3654f3b92ead30.jpg",
    "e7/0f/4f/e70f4fd572be056dc1f18fde432cebd3.jpg",
    "e9/00/ee/e900ee24f79f79224075e1cde5d01011.jpg",
    "ea/0b/9f/ea0b9f9dfab773d47cd2ea912f4f77ac.jpg",
    "ec/df/d3/ecdfd3f190902a685134b2daa79b33d8.jpg",
]

_SIZE_TIERS = ("736x", "474x", "236x")


def build_hardcoded_cdn_urls(limit: int = CDN_TARGET_MAX) -> list[str]:
    urls: list[str] = []
    for tier in _SIZE_TIERS:
        for h in _PINIMG_HASHES:
            urls.append(f"https://i.pinimg.com/{tier}/{h}")
            if len(urls) >= limit:
                return urls
    return urls


# ---------------------------------------------------------------------------
# Inbox parsers
# ---------------------------------------------------------------------------

def _walk_collect(obj: Any, key: str, out: list[Any]) -> None:
    if isinstance(obj, dict):
        if key in obj and obj[key] is not None:
            out.append(obj[key])
        for v in obj.values():
            _walk_collect(v, key, out)
    elif isinstance(obj, list):
        for item in obj:
            _walk_collect(item, key, out)


def _looks_pinimg(url: Any) -> bool:
    return isinstance(url, str) and url.startswith("http") and "i.pinimg.com" in url


def _normalize_pin_id(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if re.fullmatch(r"\d{8,20}", s):
        return s
    m = re.search(r"/pin/(\d{8,20})", s)
    return m.group(1) if m else None


def load_inbox_rows() -> list[dict[str, Any]]:
    if not INBOX_DIR.is_dir():
        return []
    rows: list[dict[str, Any]] = []
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
            if isinstance(row, dict):
                rows.append(row)
    return rows


def load_cdn_urls_from_inbox(limit: int = CDN_TARGET_MAX) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for row in load_inbox_rows():
        bucket: list[Any] = []
        _walk_collect(row, "image_url_orig", bucket)
        _walk_collect(row, "image_url", bucket)
        _walk_collect(row, "url", bucket)
        for val in bucket:
            if not _looks_pinimg(val):
                continue
            if val not in seen:
                seen.add(val)
                found.append(val)
            if len(found) >= limit:
                return found
    return found


def load_pin_ids_from_inbox(limit: int = PIN_TARGET) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for row in load_inbox_rows():
        bucket: list[Any] = []
        for key in ("pin_id", "id", "pinId", "pin"):
            _walk_collect(row, key, bucket)
        # также из URL пина, если есть
        for key in ("pin_url", "link", "url"):
            _walk_collect(row, key, bucket)
        for val in bucket:
            pid = _normalize_pin_id(val)
            if pid and pid not in seen:
                seen.add(pid)
                found.append(pid)
            if len(found) >= limit:
                return found
    return found


def prepare_cdn_urls() -> tuple[list[str], str]:
    inbox = load_cdn_urls_from_inbox(CDN_TARGET_MAX)
    if len(inbox) >= CDN_TARGET_MIN:
        urls = inbox[:CDN_TARGET_MAX]
        return urls, f"inbox/*.jsonl ({len(inbox)} доступно, берём {len(urls)})"

    hardcoded = build_hardcoded_cdn_urls(CDN_TARGET_MAX)
    # inbox + добор до 150–200
    merged: list[str] = []
    seen: set[str] = set()
    for u in inbox + hardcoded:
        if u not in seen:
            seen.add(u)
            merged.append(u)
        if len(merged) >= CDN_TARGET_MAX:
            break
    if len(merged) < CDN_TARGET_MIN:
        # цикл добора (редкий случай)
        while len(merged) < CDN_TARGET_MIN:
            merged.append(hardcoded[len(merged) % len(hardcoded)])
    source = (
        f"inbox={len(inbox)} + hardcoded CDN tiers "
        f"(итого {len(merged)})"
    )
    return merged, source


def prepare_pin_ids() -> tuple[list[str], str]:
    inbox = load_pin_ids_from_inbox(PIN_TARGET)
    if len(inbox) >= PIN_TARGET:
        return inbox[:PIN_TARGET], f"inbox/*.jsonl ({len(inbox)} найдено)"
    merged: list[str] = []
    seen: set[str] = set()
    for pid in inbox + HARDCODED_PIN_IDS:
        if pid not in seen:
            seen.add(pid)
            merged.append(pid)
        if len(merged) >= PIN_TARGET:
            break
    return merged[:PIN_TARGET], f"inbox={len(inbox)} + hardcoded pins"


# ---------------------------------------------------------------------------
# ТЕСТ А — CDN stress (in-memory)
# ---------------------------------------------------------------------------

@dataclass
class CdnItemResult:
    index: int
    url: str
    ok: bool
    status: int | None = None
    bytes_len: int = 0
    elapsed: float = 0.0
    error: str | None = None
    completed_at: float = 0.0  # monotonic since batch start


@dataclass
class CdnReport:
    total: int = 0
    success: int = 0
    failed: int = 0
    count_403: int = 0
    count_429: int = 0
    bytes_total: int = 0
    elapsed_sec: float = 0.0
    avg_mbps: float = 0.0
    first_half_mbps: float = 0.0
    second_half_mbps: float = 0.0
    speed_drop_pct: float = 0.0
    source: str = ""
    verdict: str = ""
    items: list[CdnItemResult] = field(default_factory=list)


async def _cdn_fetch(
    index: int,
    url: str,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    t0: float,
) -> CdnItemResult:
    async with sem:
        started = time.perf_counter()
        try:
            resp = await client.get(url)
            body = resp.content  # in-memory only; не пишем на диск
            elapsed = time.perf_counter() - started
            ok = resp.status_code == 200 and bool(body)
            return CdnItemResult(
                index=index,
                url=url,
                ok=ok,
                status=resp.status_code,
                bytes_len=len(body) if ok else 0,
                elapsed=elapsed,
                error=None if ok else f"HTTP {resp.status_code}",
                completed_at=time.perf_counter() - t0,
            )
        except httpx.TimeoutException:
            return CdnItemResult(
                index=index,
                url=url,
                ok=False,
                error="timeout",
                elapsed=time.perf_counter() - started,
                completed_at=time.perf_counter() - t0,
            )
        except httpx.HTTPError as exc:
            return CdnItemResult(
                index=index,
                url=url,
                ok=False,
                error=f"http_error:{exc.__class__.__name__}",
                elapsed=time.perf_counter() - started,
                completed_at=time.perf_counter() - t0,
            )


def _half_speed(items: list[CdnItemResult], start_i: int, end_i: int) -> float:
    """МБ/с по подмножеству завершённых запросов (по порядку завершения)."""
    slice_items = items[start_i:end_i]
    if not slice_items:
        return 0.0
    ok = [x for x in slice_items if x.ok]
    if not ok:
        return 0.0
    bytes_sum = sum(x.bytes_len for x in ok)
    t_min = min(x.completed_at - x.elapsed for x in ok)
    t_max = max(x.completed_at for x in ok)
    wall = max(t_max - t_min, 1e-6)
    return (bytes_sum / (1024 * 1024)) / wall


async def run_test_a(urls: list[str], source: str) -> CdnReport:
    sem = asyncio.Semaphore(CDN_CONCURRENCY)
    timeout = httpx.Timeout(CDN_TIMEOUT)
    limits = httpx.Limits(
        max_connections=CDN_CONCURRENCY,
        max_keepalive_connections=CDN_CONCURRENCY,
    )

    t0 = time.perf_counter()
    async with httpx.AsyncClient(
        headers=CDN_HEADERS,
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
    ) as client:
        tasks = [
            _cdn_fetch(i, url, client, sem, t0)
            for i, url in enumerate(urls, start=1)
        ]
        results = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - t0

    items = sorted(results, key=lambda r: r.completed_at)
    report = CdnReport(
        total=len(items),
        source=source,
        elapsed_sec=elapsed,
        items=list(results),
    )
    for r in results:
        if r.ok:
            report.success += 1
            report.bytes_total += r.bytes_len
        else:
            report.failed += 1
        if r.status == 403:
            report.count_403 += 1
        if r.status == 429:
            report.count_429 += 1

    mb = report.bytes_total / (1024 * 1024)
    report.avg_mbps = mb / elapsed if elapsed > 0 else 0.0

    mid = max(len(items) // 2, 1)
    report.first_half_mbps = _half_speed(items, 0, mid)
    report.second_half_mbps = _half_speed(items, mid, len(items))
    if report.first_half_mbps > 0:
        report.speed_drop_pct = (
            (report.first_half_mbps - report.second_half_mbps)
            / report.first_half_mbps
            * 100.0
        )
    else:
        report.speed_drop_pct = 0.0

    blocked = report.count_429 > 0 or report.count_403 >= max(5, report.total // 10)
    sharp_drop = report.speed_drop_pct >= 45.0 and report.first_half_mbps > 0.2
    success_rate = report.success / report.total if report.total else 0.0

    if blocked or sharp_drop or success_rate < 0.7:
        report.verdict = "Нужна ротация прокси / снижение потоков"
    else:
        report.verdict = "CDN держит нагрузку"

    return report


# ---------------------------------------------------------------------------
# ТЕСТ Б — воскрешение по pin_id
# ---------------------------------------------------------------------------

@dataclass
class PinItemResult:
    pin_id: str
    ok: bool
    final_url: str = ""
    status: int | None = None
    login_wall: bool = False
    captcha: bool = False
    image_url: str | None = None
    source_tag: str | None = None  # og:image | __PWS_DATA__
    error: str | None = None


@dataclass
class PinReport:
    total: int = 0
    resurrected: int = 0
    login_hits: int = 0
    captcha_hits: int = 0
    source: str = ""
    verdict: str = ""
    items: list[PinItemResult] = field(default_factory=list)


def _normalize_html(text: str) -> str:
    return (
        text.replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\/", "/")
    )


def _extract_og_image(html: str) -> str | None:
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I)
        if m and "pinimg.com" in m.group(1):
            return m.group(1)
    return None


def _extract_from_pws_data(html: str) -> str | None:
    m = re.search(
        r'<script[^>]+id=["\']__PWS_DATA__["\'][^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    )
    if not m:
        # иногда данные в __PWS_INITIAL_PROPS__ / соседних скриптах
        m = re.search(
            r'<script[^>]+id=["\']__PWS_INITIAL_PROPS__["\'][^>]*>(.*?)</script>',
            html,
            re.I | re.S,
        )
    if not m:
        return None

    raw = m.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # fallback: regex по pinimg внутри блока
        found = re.findall(
            r"https://i\.pinimg\.com/(?:originals|\d+x)/[0-9a-f/]+\.(?:jpg|jpeg|png|webp)",
            raw,
            re.I,
        )
        return found[0] if found else None

    # предпочитаем originals / крупные размеры
    candidates: list[str] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and "i.pinimg.com" in v:
                    candidates.append(v)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    if not candidates:
        return None

    def score(u: str) -> tuple[int, int]:
        path = urlparse(u).path
        tier = 0
        if "/originals/" in path:
            tier = 3
        elif "/736x/" in path:
            tier = 2
        elif "/474x/" in path:
            tier = 1
        return (tier, len(u))

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def parse_pin_html(html: str, final_url: str) -> tuple[str | None, str | None, bool, bool]:
    low = html.lower()
    captcha = (
        "just a moment" in low
        or "cf-browser-verification" in low
        or ("cloudflare" in low and "challenge" in low)
    )
    login = "/login" in final_url.lower() or (
        'action="/login"' in low and "og:image" not in low
    )

    og = _extract_og_image(html)
    if og:
        return og, "og:image", login, captcha

    pws = _extract_from_pws_data(html)
    if pws:
        return pws, "__PWS_DATA__", login, captcha

    return None, None, login, captcha


async def _fetch_pin(
    client: httpx.AsyncClient,
    pin_id: str,
) -> PinItemResult:
    url = f"https://www.pinterest.com/pin/{pin_id}/"
    try:
        resp = await client.get(url)
    except httpx.TimeoutException:
        return PinItemResult(pin_id=pin_id, ok=False, error="timeout")
    except httpx.HTTPError as exc:
        return PinItemResult(
            pin_id=pin_id,
            ok=False,
            error=f"http_error:{exc.__class__.__name__}",
        )

    final_url = str(resp.url)
    html = _normalize_html(resp.text)
    image_url, source_tag, login, captcha = parse_pin_html(html, final_url)

    # редирект на логин даже при follow
    if "/login" in final_url.lower():
        login = True

    ok = bool(image_url) and not login and not captcha and resp.status_code == 200
    return PinItemResult(
        pin_id=pin_id,
        ok=ok,
        final_url=final_url,
        status=resp.status_code,
        login_wall=login,
        captcha=captcha,
        image_url=image_url,
        source_tag=source_tag,
        error=None if ok else ("login" if login else "captcha" if captcha else "no_image"),
    )


async def run_test_b(pin_ids: list[str], source: str) -> PinReport:
    timeout = httpx.Timeout(PIN_TIMEOUT)
    async with httpx.AsyncClient(
        headers=PAGE_HEADERS,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        # последовательно — меньше шансов словить challenge на HTML
        items: list[PinItemResult] = []
        for pid in pin_ids:
            items.append(await _fetch_pin(client, pid))
            await asyncio.sleep(0.35)

    report = PinReport(total=len(items), source=source, items=items)
    for it in items:
        if it.ok:
            report.resurrected += 1
        if it.login_wall:
            report.login_hits += 1
        if it.captcha:
            report.captcha_hits += 1

    if report.resurrected >= max(1, (report.total + 1) // 2) and report.captcha_hits == 0:
        report.verdict = "Воскрешение без браузера работает"
    else:
        report.verdict = "Нужен headless-браузер / прокси"

    return report


# ---------------------------------------------------------------------------
# Отчёт
# ---------------------------------------------------------------------------

def _yn(flag: bool) -> str:
    return "ДА" if flag else "нет"


def print_final_report(cdn: CdnReport, pins: PinReport) -> None:
    line = "=" * 72
    print()
    print(line)
    print("  Pinterest Resilience — итоговый отчёт")
    print(line)

    print()
    print("  ТЕСТ А · Стресс CDN (in-memory, concurrency=10)")
    print("  " + "-" * 68)
    print(f"  Источник ссылок     : {cdn.source}")
    print(f"  Запросов            : {cdn.success} / {cdn.total} успешно")
    print(f"  Отказы              : {cdn.failed}")
    print(f"  HTTP 429            : {cdn.count_429}  ({_yn(cdn.count_429 > 0)})")
    print(f"  HTTP 403            : {cdn.count_403}  ({_yn(cdn.count_403 > 0)})")
    print(f"  Время               : {cdn.elapsed_sec:.2f} с")
    print(f"  Средняя скорость    : {cdn.avg_mbps:.2f} МБ/с")
    print(
        f"  Скорость 1-я/2-я пол.: "
        f"{cdn.first_half_mbps:.2f} → {cdn.second_half_mbps:.2f} МБ/с "
        f"(Δ {cdn.speed_drop_pct:+.1f}%)"
    )
    print(f"  Вердикт             : {cdn.verdict}")

    print()
    print("  ТЕСТ Б · Воскрешение по pin_id (чистый HTTP)")
    print("  " + "-" * 68)
    print(f"  Источник pin_id     : {pins.source}")
    print(f"  Воскрешено          : {pins.resurrected} / {pins.total}")
    print(f"  Login wall          : {_yn(pins.login_hits > 0)} ({pins.login_hits})")
    print(f"  Cloudflare/captcha  : {_yn(pins.captcha_hits > 0)} ({pins.captcha_hits})")
    for it in pins.items:
        status = "OK" if it.ok else "FAIL"
        detail = it.image_url[:64] + "…" if it.ok and it.image_url and len(it.image_url) > 64 else (
            it.image_url if it.ok else it.error
        )
        tag = f" [{it.source_tag}]" if it.source_tag else ""
        print(f"    · {it.pin_id}: {status}{tag} — {detail}")
    print(f"  Вердикт             : {pins.verdict}")

    print()
    print(line)
    print("  СВОДКА")
    print(line)
    a_res = f"{cdn.success}/{cdn.total} ok, {cdn.avg_mbps:.1f}MB/s"
    b_res = f"{pins.resurrected}/{pins.total} parsed"
    print(f"  {'Тест':<28} {'Результат':<28} {'Вердикт'}")
    print(f"  {'-'*28} {'-'*28} {'-'*40}")
    print(f"  {'A CDN stress':<28} {a_res:<28} {cdn.verdict}")
    print(f"  {'B pin_id resurrection':<28} {b_res:<28} {pins.verdict}")
    print(line)
    print()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def async_main() -> int:
    print("Подготовка данных…")
    cdn_urls, cdn_source = prepare_cdn_urls()
    pin_ids, pin_source = prepare_pin_ids()
    print(f"  CDN URL : {len(cdn_urls)} ({cdn_source})")
    print(f"  pin_id  : {len(pin_ids)} ({pin_source})")

    print()
    print(f"[A] Стресс CDN: {len(cdn_urls)} загрузок, semaphore={CDN_CONCURRENCY}, in-memory…")
    cdn_report = await run_test_a(cdn_urls, cdn_source)
    print(
        f"[A] Готово: {cdn_report.success}/{cdn_report.total} ok, "
        f"429={cdn_report.count_429}, 403={cdn_report.count_403}, "
        f"{cdn_report.avg_mbps:.2f} МБ/с"
    )

    print()
    print(f"[B] Воскрешение pin_id: {len(pin_ids)} штук…")
    pin_report = await run_test_b(pin_ids, pin_source)
    print(f"[B] Готово: {pin_report.resurrected}/{pin_report.total} воскрешено")

    print_final_report(cdn_report, pin_report)
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
