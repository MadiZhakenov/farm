#!/usr/bin/env python3
"""
Строгое расследование: реально ли Pinterest CDN троттлит / отдаёт 403
при 10–12 потоках, или виноваты битые ссылки / домашний интернет.

Запуск:
  python test_skeptic_cdn.py
"""

from __future__ import annotations

import asyncio
import json
import platform
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

INBOX_DIR = Path("inbox")
LIVE_NEEDED = 60
PROBE_CONCURRENCY = 8
ROUND_SIZE = 30
ROUND1_WORKERS = 4
ROUND2_WORKERS = 12
REQUEST_TIMEOUT = 10.0
PROBE_TIMEOUT = 6.0
PING_HOST = "1.1.1.1"
PING_SAMPLES = 5

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

# Проверенные публичные хэши → кандидаты 736x / 474x (до фильтрации живых)
_PINIMG_HASHES: list[str] = [
    "03/17/bb/0317bbfc8a48c41661786e6bd1e7eb15.jpg",
    "03/ef/d3/03efd333fce2f1b6b7bd8fb207b19b78.jpg",
    "04/da/a6/04daa6ea649ac350b3a2ba7eecd83647.jpg",
    "07/c2/c7/07c2c75027f6364ff61d474c6e0fdba5.jpg",
    "0c/f0/b8/0cf0b88f3377c8f5a47a73c9cd947e89.png",
    "0f/2a/df/0f2adf0c7f2f87af97358a435ffbf539.jpg",
    "16/5b/79/165b7950a69a62e3f4d31fc2c227020a.jpg",
    "19/d8/77/19d877f0d7eb2af146a42c932dc7c908.png",
    "1e/67/1c/1e671cfe2bc7b4076b5bbe99e8320766.jpg",
    "20/fb/c6/20fbc6d65fcb4fa5d19c427efcc4e5f1.jpg",
    "24/44/51/244451547905ded271a2ebbee3e75e2e.jpg",
    "27/5c/fc/275cfc51e60c6e3ef11101b3890bafa8.jpg",
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
    "6b/34/d2/6b34d2d5e043dcc2be3e524c8c16c9b0.jpg",
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
    "ad/3a/27/ad3a2707406a9a8a993a829c4b8e6231.jpg",
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


# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------

@dataclass
class PingStats:
    host: str
    method: str
    samples_ms: list[float] = field(default_factory=list)
    ok: int = 0
    failed: int = 0

    @property
    def avg_ms(self) -> float:
        return statistics.mean(self.samples_ms) if self.samples_ms else 0.0

    @property
    def min_ms(self) -> float:
        return min(self.samples_ms) if self.samples_ms else 0.0

    @property
    def max_ms(self) -> float:
        return max(self.samples_ms) if self.samples_ms else 0.0


@dataclass
class ItemResult:
    url: str
    ok: bool
    status: int | None = None
    bytes_len: int = 0
    elapsed: float = 0.0
    error: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body_preview: str = ""


@dataclass
class RoundReport:
    name: str
    workers: int
    total: int
    success: int = 0
    failed: int = 0
    count_403: int = 0
    count_429: int = 0
    count_timeout: int = 0
    other_errors: int = 0
    bytes_total: int = 0
    elapsed_sec: float = 0.0
    mbps: float = 0.0
    items: list[ItemResult] = field(default_factory=list)
    forbidden_samples: list[ItemResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Inbox + кандидаты
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


def load_inbox_candidates() -> list[str]:
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
            bucket: list[Any] = []
            for key in ("image_url_orig", "image_url", "url"):
                _walk_collect(row, key, bucket)
            for val in bucket:
                if (
                    isinstance(val, str)
                    and val.startswith("http")
                    and "i.pinimg.com" in val
                    and val not in seen
                ):
                    seen.add(val)
                    found.append(val)
    return found


def build_candidate_pool() -> tuple[list[str], str]:
    inbox = load_inbox_candidates()
    hardcoded: list[str] = []
    for tier in ("736x", "474x"):
        for h in _PINIMG_HASHES:
            hardcoded.append(f"https://i.pinimg.com/{tier}/{h}")

    merged: list[str] = []
    seen: set[str] = set()
    for u in inbox + hardcoded:
        if u not in seen:
            seen.add(u)
            merged.append(u)

    source = f"inbox={len(inbox)}, hardcoded={len(hardcoded)}, pool={len(merged)}"
    return merged, source


# ---------------------------------------------------------------------------
# Шаг 1: отбор 60 живых ссылок
# ---------------------------------------------------------------------------

async def _probe_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    url: str,
) -> str | None:
    """Живая = HTTP 200 и хотя бы ~1 КБ тела (или полный маленький файл)."""
    async with sem:
        # 1) HEAD (если CDN отдаёт осмысленный статус)
        try:
            head = await client.head(url)
            if head.status_code in {403, 404, 410}:
                return None
        except httpx.HTTPError:
            pass

        # 2) GET первых ~1 КБ (Range) — надёжнее HEAD на pinimg
        try:
            resp = await client.get(
                url,
                headers={**CDN_HEADERS, "Range": "bytes=0-1023"},
            )
            # 200 (полный) или 206 (partial) считаем живыми
            if resp.status_code in {200, 206} and len(resp.content) > 0:
                ctype = (resp.headers.get("content-type") or "").lower()
                if "image" in ctype or len(resp.content) >= 64:
                    return url
            if resp.status_code in {403, 404, 429}:
                return None
        except httpx.HTTPError:
            return None

        # 3) fallback: обычный GET без Range
        try:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) >= 64:
                return url
        except httpx.HTTPError:
            return None
        return None


async def collect_live_urls(candidates: list[str], needed: int = LIVE_NEEDED) -> list[str]:
    sem = asyncio.Semaphore(PROBE_CONCURRENCY)
    timeout = httpx.Timeout(PROBE_TIMEOUT)
    live: list[str] = []
    checked = 0

    async with httpx.AsyncClient(
        headers=CDN_HEADERS,
        timeout=timeout,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=PROBE_CONCURRENCY),
    ) as client:
        # батчами, пока не наберём needed
        i = 0
        batch_size = PROBE_CONCURRENCY * 3
        while i < len(candidates) and len(live) < needed:
            batch = candidates[i : i + batch_size]
            i += batch_size
            results = await asyncio.gather(
                *[_probe_one(client, sem, u) for u in batch]
            )
            checked += len(batch)
            for u in results:
                if u and u not in live:
                    live.append(u)
                if len(live) >= needed:
                    break
            print(
                f"  probe: проверено {checked}/{len(candidates)}, "
                f"живых {len(live)}/{needed}",
                flush=True,
            )

    return live[:needed]


# ---------------------------------------------------------------------------
# Шаг 2 / 4: пинг / задержка
# ---------------------------------------------------------------------------

def _parse_windows_ping(output: str) -> list[float]:
    # time=12ms  или  время=12мс
    vals = re.findall(r"(?:time|время)[=<>]\s*(\d+)\s*m?s", output, re.I)
    return [float(v) for v in vals]


def _parse_unix_ping(output: str) -> list[float]:
    vals = re.findall(r"time[=]([\d.]+)\s*ms", output, re.I)
    return [float(v) for v in vals]


def icmp_ping(host: str = PING_HOST, count: int = PING_SAMPLES) -> PingStats | None:
    system = platform.system().lower()
    try:
        if system == "windows":
            cmd = ["ping", "-n", str(count), host]
        else:
            cmd = ["ping", "-c", str(count), host]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        samples = (
            _parse_windows_ping(out) if system == "windows" else _parse_unix_ping(out)
        )
        if not samples:
            return None
        return PingStats(
            host=host,
            method="ICMP ping",
            samples_ms=samples,
            ok=len(samples),
            failed=max(0, count - len(samples)),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


async def tcp_latency(
    host: str = PING_HOST,
    port: int = 443,
    samples: int = PING_SAMPLES,
) -> PingStats:
    stats = PingStats(host=f"{host}:{port}", method="TCP connect")
    for _ in range(samples):
        t0 = time.perf_counter()
        try:
            conn = asyncio.open_connection(host, port)
            reader, writer = await asyncio.wait_for(conn, timeout=5.0)
            ms = (time.perf_counter() - t0) * 1000.0
            stats.samples_ms.append(ms)
            stats.ok += 1
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            del reader
        except Exception:
            stats.failed += 1
        await asyncio.sleep(0.15)
    return stats


async def measure_baseline_latency() -> PingStats:
    icmp = icmp_ping(PING_HOST, PING_SAMPLES)
    if icmp and icmp.samples_ms:
        return icmp
    print("  ICMP ping недоступен — fallback на TCP connect к 1.1.1.1:443")
    return await tcp_latency(PING_HOST, 443, PING_SAMPLES)


async def latency_monitor(
    stop_event: asyncio.Event,
    interval: float = 0.25,
) -> PingStats:
    """Фоновый замер задержки во время раунда 2."""
    stats = PingStats(host=f"{PING_HOST}:443", method="TCP connect (во время R2)")

    async def one_sample() -> None:
        t0 = time.perf_counter()
        try:
            conn = asyncio.open_connection(PING_HOST, 443)
            reader, writer = await asyncio.wait_for(conn, timeout=3.0)
            ms = (time.perf_counter() - t0) * 1000.0
            stats.samples_ms.append(ms)
            stats.ok += 1
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            del reader
        except Exception:
            stats.failed += 1

    # сразу несколько параллельных проб — даже сверхбыстрый R2 даст статистику
    await asyncio.gather(*[one_sample() for _ in range(3)])
    while not stop_event.is_set():
        await one_sample()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    # финальный замер после стопа
    await one_sample()
    return stats


# ---------------------------------------------------------------------------
# Раунды скачивания (in-memory)
# ---------------------------------------------------------------------------

async def _download_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    url: str,
    capture_403: bool,
) -> ItemResult:
    async with sem:
        t0 = time.perf_counter()
        try:
            resp = await client.get(url)
            elapsed = time.perf_counter() - t0
            headers = {k: v for k, v in resp.headers.items()}
            if resp.status_code == 200 and resp.content:
                return ItemResult(
                    url=url,
                    ok=True,
                    status=200,
                    bytes_len=len(resp.content),
                    elapsed=elapsed,
                    headers=headers,
                )

            body_preview = ""
            if resp.status_code == 403 and capture_403:
                raw = resp.content[:1500]
                try:
                    body_preview = raw.decode("utf-8", errors="replace")
                except Exception:
                    body_preview = repr(raw[:200])

            return ItemResult(
                url=url,
                ok=False,
                status=resp.status_code,
                bytes_len=0,
                elapsed=elapsed,
                error=f"HTTP {resp.status_code}",
                headers=headers,
                body_preview=body_preview,
            )
        except httpx.TimeoutException:
            return ItemResult(
                url=url,
                ok=False,
                error="timeout",
                elapsed=time.perf_counter() - t0,
            )
        except httpx.HTTPError as exc:
            return ItemResult(
                url=url,
                ok=False,
                error=f"http_error:{exc.__class__.__name__}",
                elapsed=time.perf_counter() - t0,
            )


async def run_round(
    name: str,
    urls: list[str],
    workers: int,
) -> RoundReport:
    sem = asyncio.Semaphore(workers)
    timeout = httpx.Timeout(REQUEST_TIMEOUT)
    limits = httpx.Limits(max_connections=workers, max_keepalive_connections=workers)

    t0 = time.perf_counter()
    async with httpx.AsyncClient(
        headers=CDN_HEADERS,
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(
            *[_download_one(client, sem, u, capture_403=True) for u in urls]
        )
    elapsed = time.perf_counter() - t0

    report = RoundReport(
        name=name,
        workers=workers,
        total=len(urls),
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
                if r.body_preview or r.headers:
                    report.forbidden_samples.append(r)
            elif r.status == 429:
                report.count_429 += 1
            elif r.error == "timeout":
                report.count_timeout += 1
            else:
                report.other_errors += 1

    mb = report.bytes_total / (1024 * 1024)
    report.mbps = mb / elapsed if elapsed > 0 else 0.0
    return report


# ---------------------------------------------------------------------------
# Анализ 403 + вердикт
# ---------------------------------------------------------------------------

def classify_403(sample: ItemResult) -> str:
    body = (sample.body_preview or "").lower()
    server = (sample.headers.get("server") or sample.headers.get("Server") or "").lower()
    via = (sample.headers.get("via") or "").lower()
    cf = any(
        k.lower().startswith("cf-") or k.lower() == "cf-ray"
        for k in sample.headers
    )

    if "cloudflare" in body or "cf-ray" in sample.headers or cf or "cloudflare" in server:
        return "похоже на Cloudflare WAF / edge block"
    if "accessdenied" in body.replace(" ", "") or "access denied" in body:
        return "ответ хранилища (S3-like AccessDenied), не обязательно бан IP"
    if "just a moment" in body:
        return "Cloudflare challenge page"
    if "akamai" in server or "akamai" in via:
        return "Akamai/edge отказ"
    return "неопознанный 403 — смотрите тело/заголовки ниже"


def print_403_forensics(rounds: list[RoundReport]) -> None:
    samples: list[ItemResult] = []
    for r in rounds:
        samples.extend(r.forbidden_samples)
    if not samples:
        print("  403 не зафиксированы — forensics не требуется.")
        return

    print(f"  Найдено 403: {len(samples)}. Разбор первого образца:")
    s = samples[0]
    print(f"  URL     : {s.url}")
    print(f"  Вердикт : {classify_403(s)}")
    print("  Заголовки:")
    interesting = [
        "server",
        "via",
        "cf-ray",
        "cf-cache-status",
        "x-cache",
        "x-amz-request-id",
        "x-amz-id-2",
        "content-type",
        "content-length",
        "www-authenticate",
    ]
    shown = set()
    for key in interesting:
        for hk, hv in s.headers.items():
            if hk.lower() == key:
                print(f"    {hk}: {hv}")
                shown.add(hk.lower())
    # остальные заголовки кратко
    extras = [f"{k}={v}" for k, v in s.headers.items() if k.lower() not in shown]
    if extras:
        print(f"    … ещё {len(extras)}: " + "; ".join(extras[:8]))
    print("  Тело ответа (до 1500 байт):")
    print("  " + "-" * 60)
    body = s.body_preview.strip() or "(пусто)"
    for line in body.splitlines()[:40]:
        print(f"  {line}")
    print("  " + "-" * 60)


def make_verdict(
    r1: RoundReport,
    r2: RoundReport,
    baseline: PingStats,
    during: PingStats | None,
) -> str:
    # просадка домашнего канала?
    isp_lag = False
    if during and during.samples_ms and baseline.samples_ms:
        if during.avg_ms > baseline.avg_ms * 2.5 and during.avg_ms > 80:
            isp_lag = True
        if during.failed >= max(2, during.ok):
            isp_lag = True

    r2_err_rate = r2.failed / r2.total if r2.total else 0.0
    r1_err_rate = r1.failed / r1.total if r1.total else 0.0
    throttle_signals = 0

    # ошибки только во 2-м раунде
    if r2.count_429 > 0:
        throttle_signals += 2
    if r2.count_403 > 0 and r1.count_403 == 0:
        throttle_signals += 2
    elif r2.count_403 > r1.count_403 + 1:
        throttle_signals += 1
    if r2.count_timeout > r1.count_timeout + 1:
        throttle_signals += 1

    # скорость упала при большем параллелизме (ожидали рост или хотя бы паритет)
    if r1.mbps > 0.15 and r2.mbps < r1.mbps * 0.55:
        throttle_signals += 1
    if r2_err_rate >= 0.15 and r2_err_rate > r1_err_rate + 0.05:
        throttle_signals += 1

    if isp_lag and throttle_signals <= 2:
        return (
            "Ограничений нет, виноваты были кривые ссылки, можно смело качать в 12 потоков"
            " (но во время R2 просел домашний канал — перепроверьте на стабильном Wi‑Fi/Ethernet)"
        )

    if throttle_signals >= 2 and not (r2.count_403 and all(
        "accessdenied" in (s.body_preview or "").lower().replace(" ", "")
        or "access denied" in (s.body_preview or "").lower()
        for s in r2.forbidden_samples
    ) and r2.count_429 == 0 and r2_err_rate < 0.5 and r1.success == r1.total):
        # если 403 = AccessDenied на битых — это не троттлинг; но мы уже на живых URL
        if r2.count_429 > 0 or (r2.count_403 > 0 and r1.count_403 == 0):
            return "Pinterest действительно троттлит при 12 потоках"
        if r2.mbps < r1.mbps * 0.55 and r2_err_rate > r1_err_rate:
            return "Pinterest действительно троттлит при 12 потоках"

    # чистый датасет, ошибки ~равны, скорость не рухнула
    if r1.success == r1.total and r2.success == r2.total and r2.count_429 == 0:
        return "Ограничений нет, виноваты были кривые ссылки, можно смело качать в 12 потоков"

    if r2.count_429 == 0 and r2_err_rate <= 0.05 and r2.mbps >= r1.mbps * 0.7:
        return "Ограничений нет, виноваты были кривые ссылки, можно смело качать в 12 потоков"

    if throttle_signals >= 2:
        return "Pinterest действительно троттлит при 12 потоках"

    return "Ограничений нет, виноваты были кривые ссылки, можно смело качать в 12 потоков"


def print_report(
    pool_source: str,
    live_count: int,
    baseline: PingStats,
    during: PingStats | None,
    r1: RoundReport,
    r2: RoundReport,
) -> None:
    line = "=" * 72
    print()
    print(line)
    print("  Skeptic CDN — расследование троттлинга Pinterest")
    print(line)
    print(f"  Пул кандидатов : {pool_source}")
    print(f"  Живых URL      : {live_count} (строго 200/206 на пробе)")
    print()
    print("  BASELINE сеть")
    print("  " + "-" * 68)
    print(
        f"  {baseline.method} → {baseline.host}: "
        f"avg={baseline.avg_ms:.1f} ms  "
        f"min={baseline.min_ms:.1f}  max={baseline.max_ms:.1f}  "
        f"ok={baseline.ok} fail={baseline.failed}"
    )
    if during is not None:
        print(
            f"  Во время R2     : avg={during.avg_ms:.1f} ms  "
            f"min={during.min_ms:.1f}  max={during.max_ms:.1f}  "
            f"ok={during.ok} fail={during.failed}"
        )
        if baseline.samples_ms and during.samples_ms:
            delta = during.avg_ms - baseline.avg_ms
            print(f"  Δ пинга R2−base : {delta:+.1f} ms")

    print()
    print("  403 FORENSICS")
    print("  " + "-" * 68)
    print_403_forensics([r1, r2])

    verdict = make_verdict(r1, r2, baseline, during)

    def err_cell(r: RoundReport) -> str:
        parts = []
        if r.count_403:
            parts.append(f"403×{r.count_403}")
        if r.count_429:
            parts.append(f"429×{r.count_429}")
        if r.count_timeout:
            parts.append(f"timeout×{r.count_timeout}")
        if r.other_errors:
            parts.append(f"other×{r.other_errors}")
        return ", ".join(parts) if parts else "0"

    print()
    print("  СРАВНИТЕЛЬНАЯ ТАБЛИЦА")
    print("  " + "-" * 68)
    print(
        f"  {'Раунд':<28} {'Потоки':<8} {'OK':<10} "
        f"{'МБ/с':<10} {'Время':<10} {'Ошибки'}"
    )
    print(
        f"  {'-'*28} {'-'*8} {'-'*10} {'-'*10} {'-'*10} {'-'*20}"
    )
    for r in (r1, r2):
        ok_cell = f"{r.success}/{r.total}"
        print(
            f"  {r.name:<28} {r.workers:<8} "
            f"{ok_cell:<10} {r.mbps:<10.2f} "
            f"{r.elapsed_sec:<10.2f} {err_cell(r)}"
        )

    print()
    print("  ПИНГ")
    print("  " + "-" * 68)
    print(f"  До теста (baseline) : {baseline.avg_ms:.1f} ms ({baseline.method})")
    if during is not None:
        print(f"  Во время R2         : {during.avg_ms:.1f} ms ({during.method})")
        lag = (
            "провайдер подлагивал"
            if during.avg_ms > baseline.avg_ms * 2.5 and during.avg_ms > 80
            else "канал стабилен"
        )
        print(f"  Оценка канала       : {lag}")
    print()
    print(line)
    print(f"  ФИНАЛЬНЫЙ ВЫВОД: {verdict}")
    print(line)
    print()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def async_main() -> int:
    print("Шаг 1 · Сбор пула 100% живых ссылок…")
    candidates, pool_source = build_candidate_pool()
    print(f"  кандидаты: {pool_source}")
    live = await collect_live_urls(candidates, LIVE_NEEDED)
    if len(live) < LIVE_NEEDED:
        print(
            f"ОШИБКА: удалось подтвердить только {len(live)}/{LIVE_NEEDED} живых URL. "
            "Добавьте inbox/*.jsonl или расширьте пул."
        )
        return 2
    print(f"  ✓ отобрано ровно {len(live)} живых ссылок")

    print()
    print(f"Шаг 2 · Baseline задержки до {PING_HOST} ({PING_SAMPLES} замеров)…")
    baseline = await measure_baseline_latency()
    print(
        f"  ✓ {baseline.method}: avg={baseline.avg_ms:.1f} ms "
        f"(min={baseline.min_ms:.1f}, max={baseline.max_ms:.1f})"
    )

    round1_urls = live[:ROUND_SIZE]
    round2_urls = live[ROUND_SIZE : ROUND_SIZE * 2]

    print()
    print(f"Шаг 3 · Раунд 1 «спокойный» — {ROUND_SIZE} картинок, {ROUND1_WORKERS} потока…")
    r1 = await run_round("R1 спокойный (4 потока)", round1_urls, ROUND1_WORKERS)
    print(
        f"  ✓ {r1.success}/{r1.total} ok | {r1.mbps:.2f} МБ/с | "
        f"{r1.elapsed_sec:.2f} с | err={r1.failed}"
    )

    print()
    print(
        f"Шаг 4 · Раунд 2 «агрессивный» — {ROUND_SIZE} картинок, "
        f"{ROUND2_WORKERS} потоков + пинг…"
    )
    stop = asyncio.Event()
    monitor_task = asyncio.create_task(latency_monitor(stop, interval=0.2))
    # дать монитору сделать стартовые пробы до/в начале нагрузки
    await asyncio.sleep(0.05)
    r2 = await run_round("R2 агрессивный (12 потоков)", round2_urls, ROUND2_WORKERS)
    stop.set()
    during = await monitor_task
    print(
        f"  ✓ {r2.success}/{r2.total} ok | {r2.mbps:.2f} МБ/с | "
        f"{r2.elapsed_sec:.2f} с | err={r2.failed}"
    )
    print(
        f"  ✓ пинг во время R2: avg={during.avg_ms:.1f} ms "
        f"(samples={len(during.samples_ms)})"
    )

    print()
    print("Шаг 5 · Анализ 403 (если были) + итоговый вердикт…")
    print_report(pool_source, len(live), baseline, during, r1, r2)
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
