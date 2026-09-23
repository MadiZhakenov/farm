#!/usr/bin/env python3
"""
Симуляция полного боевого дня: ровно 1 200 скачиваний с Pinterest CDN.

Проверяет:
  1) деградацию скорости к концу дистанции;
  2) появление 429 / 403 / таймаутов;
  3) утечку оперативной памяти.

Запуск:
  python test_full_day_soak.py
"""

from __future__ import annotations

import asyncio
import gc
import json
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psutil

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

INBOX_DIR = Path("inbox")
TOTAL_DOWNLOADS = 1200
QUARTER = 300  # 4 × 300 = 1200
WORKERS = 12
REQUEST_TIMEOUT = 7.0
JITTER_MIN = 0.05
JITTER_MAX = 0.15
PROBE_CONCURRENCY = 8
PROBE_TIMEOUT = 6.0
LIVE_POOL_TARGET = 60
LIVE_POOL_MIN = 20

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

# Тот же пул хэшей, что в test_skeptic_cdn.py
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
class Hit:
    index: int  # 1..1200
    ok: bool
    status: int | None = None
    bytes_len: int = 0
    elapsed: float = 0.0
    error: str | None = None


@dataclass
class QuarterStats:
    number: int
    start_idx: int
    end_idx: int
    success: int = 0
    failed: int = 0
    count_200: int = 0
    count_403: int = 0
    count_429: int = 0
    count_timeout: int = 0
    other_errors: int = 0
    bytes_total: int = 0
    wall_sec: float = 0.0
    imgs_per_sec: float = 0.0
    mbps: float = 0.0
    rss_mb: float = 0.0


@dataclass
class SoakReport:
    pool_size: int = 0
    pool_source: str = ""
    total: int = TOTAL_DOWNLOADS
    success: int = 0
    failed: int = 0
    count_200: int = 0
    count_403: int = 0
    count_429: int = 0
    count_timeout: int = 0
    other_errors: int = 0
    bytes_total: int = 0
    elapsed_sec: float = 0.0
    imgs_per_sec: float = 0.0
    mbps: float = 0.0
    rss_start_mb: float = 0.0
    rss_end_mb: float = 0.0
    rss_peak_mb: float = 0.0
    quarters: list[QuarterStats] = field(default_factory=list)
    verdict: str = ""


# ---------------------------------------------------------------------------
# Источник ссылок
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


def load_inbox_urls() -> list[str]:
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


def build_candidates() -> tuple[list[str], str]:
    inbox = load_inbox_urls()
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
    source = f"inbox={len(inbox)} + skeptic-like pool={len(hardcoded)}"
    return merged, source


async def _probe_live(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    url: str,
) -> str | None:
    async with sem:
        try:
            resp = await client.get(
                url,
                headers={**CDN_HEADERS, "Range": "bytes=0-1023"},
            )
            if resp.status_code in {200, 206} and len(resp.content) >= 64:
                return url
            if resp.status_code in {403, 404, 429}:
                return None
        except httpx.HTTPError:
            return None
        try:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) >= 64:
                return url
        except httpx.HTTPError:
            return None
        return None


async def collect_live_pool(candidates: list[str]) -> list[str]:
    """Отбирает живые URL (как в test_skeptic_cdn.py)."""
    sem = asyncio.Semaphore(PROBE_CONCURRENCY)
    live: list[str] = []
    checked = 0
    async with httpx.AsyncClient(
        headers=CDN_HEADERS,
        timeout=httpx.Timeout(PROBE_TIMEOUT),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=PROBE_CONCURRENCY),
    ) as client:
        i = 0
        batch = PROBE_CONCURRENCY * 3
        while i < len(candidates) and len(live) < LIVE_POOL_TARGET:
            chunk = candidates[i : i + batch]
            i += batch
            results = await asyncio.gather(
                *[_probe_live(client, sem, u) for u in chunk]
            )
            checked += len(chunk)
            for u in results:
                if u and u not in live:
                    live.append(u)
                if len(live) >= LIVE_POOL_TARGET:
                    break
            print(
                f"  probe: {checked}/{len(candidates)} проверено, "
                f"живых {len(live)}/{LIVE_POOL_TARGET}",
                flush=True,
            )
    return live


def cycle_to_n(pool: list[str], n: int = TOTAL_DOWNLOADS) -> list[str]:
    if not pool:
        raise RuntimeError("Пустой пул ссылок")
    return [pool[i % len(pool)] for i in range(n)]


# ---------------------------------------------------------------------------
# RAM
# ---------------------------------------------------------------------------

def rss_mb() -> float:
    return psutil.Process().memory_info().rss / (1024 * 1024)


# ---------------------------------------------------------------------------
# Скачивание
# ---------------------------------------------------------------------------

async def download_one(
    index: int,
    url: str,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> Hit:
    # микро-джиттер до захвата слота — реалистичный разброс старта
    await asyncio.sleep(random.uniform(JITTER_MIN, JITTER_MAX))
    async with sem:
        t0 = time.perf_counter()
        try:
            resp = await client.get(url)
            body = resp.content  # in-memory
            nbytes = len(body) if body else 0
            status = resp.status_code
            # сразу отпускаем байты
            del body
            elapsed = time.perf_counter() - t0
            if status == 200 and nbytes > 0:
                return Hit(
                    index=index,
                    ok=True,
                    status=200,
                    bytes_len=nbytes,
                    elapsed=elapsed,
                )
            return Hit(
                index=index,
                ok=False,
                status=status,
                bytes_len=0,
                elapsed=elapsed,
                error=f"HTTP {status}",
            )
        except httpx.TimeoutException:
            return Hit(
                index=index,
                ok=False,
                error="timeout",
                elapsed=time.perf_counter() - t0,
            )
        except httpx.HTTPError as exc:
            return Hit(
                index=index,
                ok=False,
                error=f"http_error:{exc.__class__.__name__}",
                elapsed=time.perf_counter() - t0,
            )


def finalize_quarter(
    q: QuarterStats,
    hits: list[Hit],
    wall_sec: float,
    rss: float,
) -> None:
    q.wall_sec = wall_sec
    q.rss_mb = rss
    for h in hits:
        if h.ok:
            q.success += 1
            q.count_200 += 1
            q.bytes_total += h.bytes_len
        else:
            q.failed += 1
            if h.status == 403:
                q.count_403 += 1
            elif h.status == 429:
                q.count_429 += 1
            elif h.error == "timeout":
                q.count_timeout += 1
            else:
                q.other_errors += 1
    n = q.end_idx - q.start_idx + 1
    q.imgs_per_sec = n / wall_sec if wall_sec > 0 else 0.0
    mb = q.bytes_total / (1024 * 1024)
    q.mbps = mb / wall_sec if wall_sec > 0 else 0.0


def print_quarter_progress(q: QuarterStats, done_total: int) -> None:
    bar_filled = done_total * 20 // TOTAL_DOWNLOADS
    bar = "█" * bar_filled + "░" * (20 - bar_filled)
    print()
    print(
        f"  ┌─ Четверть {q.number}/4  "
        f"[{q.start_idx}–{q.end_idx}]  "
        f"прогресс [{bar}] {done_total}/{TOTAL_DOWNLOADS}"
    )
    print(
        f"  │  OK {q.success}/{q.end_idx - q.start_idx + 1}  |  "
        f"{q.imgs_per_sec:.1f} img/s  |  {q.mbps:.2f} МБ/с  |  "
        f"{q.wall_sec:.1f} с"
    )
    print(
        f"  │  Ошибки: 403={q.count_403}  429={q.count_429}  "
        f"timeout={q.count_timeout}  other={q.other_errors}"
    )
    print(f"  └─ RAM процесса: {q.rss_mb:.1f} МБ")
    print(flush=True)


async def run_soak(urls: list[str]) -> SoakReport:
    assert len(urls) == TOTAL_DOWNLOADS
    timeout = httpx.Timeout(REQUEST_TIMEOUT)
    limits = httpx.Limits(
        max_connections=WORKERS,
        max_keepalive_connections=WORKERS,
    )

    report = SoakReport(rss_start_mb=rss_mb())
    report.rss_peak_mb = report.rss_start_mb
    all_hits: list[Hit] = []

    async with httpx.AsyncClient(
        headers=CDN_HEADERS,
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
    ) as client:
        global_t0 = time.perf_counter()
        done_total = 0

        for qn in range(1, 5):
            start_idx = (qn - 1) * QUARTER + 1
            end_idx = qn * QUARTER
            chunk = urls[start_idx - 1 : end_idx]
            sem = asyncio.Semaphore(WORKERS)

            print(
                f"\n  ▶ Старт четверти {qn}/4  "
                f"(картинки {start_idx}–{end_idx})…",
                flush=True,
            )
            q_t0 = time.perf_counter()

            async def one(
                local_i: int,
                url: str,
                _start: int = start_idx,
                _sem: asyncio.Semaphore = sem,
            ) -> Hit:
                global_index = _start + local_i
                hit = await download_one(global_index, url, client, _sem)
                if global_index % 100 == 0:
                    gc.collect()
                return hit

            # прогресс внутри четверти
            pending = [
                asyncio.create_task(one(i, u)) for i, u in enumerate(chunk)
            ]
            hits: list[Hit] = []
            for fut in asyncio.as_completed(pending):
                hit = await fut
                hits.append(hit)
                done_total += 1
                peak = rss_mb()
                if peak > report.rss_peak_mb:
                    report.rss_peak_mb = peak
                finished_in_q = len(hits)
                if finished_in_q % 50 == 0 or finished_in_q == QUARTER:
                    pct = done_total * 100 // TOTAL_DOWNLOADS
                    print(
                        f"  … Q{qn} {finished_in_q}/{QUARTER}  |  "
                        f"всего {done_total}/{TOTAL_DOWNLOADS} ({pct}%)  |  "
                        f"RAM={peak:.0f} МБ",
                        flush=True,
                    )

            wall = time.perf_counter() - q_t0
            qs = QuarterStats(
                number=qn,
                start_idx=start_idx,
                end_idx=end_idx,
            )
            finalize_quarter(qs, hits, wall, rss_mb())
            report.quarters.append(qs)
            all_hits.extend(hits)
            print_quarter_progress(qs, done_total)

        report.elapsed_sec = time.perf_counter() - global_t0

    for h in all_hits:
        if h.ok:
            report.success += 1
            report.count_200 += 1
            report.bytes_total += h.bytes_len
        else:
            report.failed += 1
            if h.status == 403:
                report.count_403 += 1
            elif h.status == 429:
                report.count_429 += 1
            elif h.error == "timeout":
                report.count_timeout += 1
            else:
                report.other_errors += 1

    report.rss_end_mb = rss_mb()
    report.imgs_per_sec = (
        TOTAL_DOWNLOADS / report.elapsed_sec if report.elapsed_sec > 0 else 0.0
    )
    mb = report.bytes_total / (1024 * 1024)
    report.mbps = mb / report.elapsed_sec if report.elapsed_sec > 0 else 0.0
    report.verdict = make_verdict(report)
    return report


def make_verdict(report: SoakReport) -> str:
    q1 = next((q for q in report.quarters if q.number == 1), None)
    q4 = next((q for q in report.quarters if q.number == 4), None)

    throttle = False
    reasons: list[str] = []

    if report.count_429 > 0:
        throttle = True
        reasons.append(f"429×{report.count_429}")
    if report.count_403 >= 10:
        throttle = True
        reasons.append(f"403×{report.count_403}")
    if report.count_timeout >= 20:
        throttle = True
        reasons.append(f"timeout×{report.count_timeout}")

    if q1 and q4 and q1.imgs_per_sec > 0:
        drop = (q1.imgs_per_sec - q4.imgs_per_sec) / q1.imgs_per_sec
        if drop >= 0.35:
            throttle = True
            reasons.append(f"скорость −{drop * 100:.0f}% Q1→Q4")
        # также по МБ/с
        if q1.mbps > 0.2:
            drop_mb = (q1.mbps - q4.mbps) / q1.mbps
            if drop_mb >= 0.40:
                throttle = True
                reasons.append(f"МБ/с −{drop_mb * 100:.0f}% Q1→Q4")

    # ошибки нарастают к концу
    if q1 and q4 and q4.failed > q1.failed + 5:
        throttle = True
        reasons.append("рост ошибок к Q4")

    ram_growth = report.rss_end_mb - report.rss_start_mb
    # утечка сама по себе не = троттлинг CDN, но влияет на вердикт стабильности
    leaky = ram_growth > 150 and report.rss_end_mb > report.rss_start_mb * 1.8

    if throttle:
        return "Зафиксировано замедление/троттлинг" + (
            f" ({', '.join(reasons)})" if reasons else ""
        )
    if leaky:
        return (
            "Зафиксировано замедление/троттлинг "
            f"(рост RAM +{ram_growth:.0f} МБ — возможна утечка)"
        )
    return "Система стабильно держит дневную норму 1 200 фото"


def format_duration(sec: float) -> str:
    m = int(sec // 60)
    s = sec - m * 60
    if m <= 0:
        return f"{s:.1f} с"
    return f"{m} мин {s:.1f} с"


def print_final_report(report: SoakReport) -> None:
    line = "=" * 72
    print()
    print(line)
    print("  Full-Day Soak — 1 200 скачиваний (боевой день)")
    print(line)
    print(f"  Пул живых URL     : {report.pool_size} ({report.pool_source})")
    print(f"  Параллельность    : {WORKERS}")
    print(f"  Джиттер           : {JITTER_MIN:.2f}–{JITTER_MAX:.2f} с")
    print(f"  Общее время       : {format_duration(report.elapsed_sec)}")
    print(
        f"  Средняя скорость  : {report.imgs_per_sec:.1f} img/s  |  "
        f"{report.mbps:.2f} МБ/с"
    )
    print(
        f"  Скачано данных    : {report.bytes_total / (1024 * 1024):.1f} МБ "
        f"(сразу освобождались)"
    )
    print()

    print("  ЧЕТВЕРТИ")
    print("  " + "-" * 68)
    print(
        f"  {'Q':<4} {'Диапазон':<12} {'OK':<10} "
        f"{'img/s':<10} {'МБ/с':<10} {'Ошибки':<22} {'RAM'}"
    )
    print(
        f"  {'-'*4} {'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*22} {'-'*8}"
    )
    for q in report.quarters:
        err = (
            f"403={q.count_403} 429={q.count_429} t/o={q.count_timeout}"
        )
        rng = f"{q.start_idx}-{q.end_idx}"
        ok = f"{q.success}/{QUARTER}"
        print(
            f"  Q{q.number:<3} {rng:<12} {ok:<10} "
            f"{q.imgs_per_sec:<10.1f} {q.mbps:<10.2f} {err:<22} "
            f"{q.rss_mb:.0f} МБ"
        )

    q1 = next((q for q in report.quarters if q.number == 1), None)
    q4 = next((q for q in report.quarters if q.number == 4), None)
    print()
    print("  СРАВНЕНИЕ Q1 vs Q4")
    print("  " + "-" * 68)
    if q1 and q4:
        if q1.imgs_per_sec > 0:
            delta_pct = (q4.imgs_per_sec - q1.imgs_per_sec) / q1.imgs_per_sec * 100
        else:
            delta_pct = 0.0
        print(
            f"  Q1: {q1.imgs_per_sec:.1f} img/s  ({q1.mbps:.2f} МБ/с)   →   "
            f"Q4: {q4.imgs_per_sec:.1f} img/s  ({q4.mbps:.2f} МБ/с)   "
            f"Δ {delta_pct:+.1f}%"
        )
        slowed = delta_pct <= -35.0
        print(
            f"  Замедление к 1000-й+: {'ДА' if slowed else 'нет'}"
        )

    print()
    print("  ОШИБКИ (весь прогон)")
    print("  " + "-" * 68)
    print(f"  200 OK     : {report.count_200}")
    print(f"  403        : {report.count_403}")
    print(f"  429        : {report.count_429}")
    print(f"  timeouts   : {report.count_timeout}")
    print(f"  other      : {report.other_errors}")
    print(f"  Итого FAIL : {report.failed} / {report.total}")

    print()
    print("  ПАМЯТЬ (RSS процесса)")
    print("  " + "-" * 68)
    print(f"  Старт      : {report.rss_start_mb:.1f} МБ")
    print(f"  Пик        : {report.rss_peak_mb:.1f} МБ")
    print(f"  Финиш      : {report.rss_end_mb:.1f} МБ")
    print(f"  Δ (end−start): {report.rss_end_mb - report.rss_start_mb:+.1f} МБ")

    print()
    print(line)
    print(f"  ВЕРДИКТ: {report.verdict}")
    print(line)
    print()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def async_main() -> int:
    print("=" * 72)
    print("  Full-Day Soak · подготовка")
    print("=" * 72)
    print("Собираем живой пул ссылок (inbox / skeptic CDN pool)…")
    candidates, cand_source = build_candidates()
    print(f"  кандидаты: {len(candidates)} ({cand_source})")
    live = await collect_live_pool(candidates)
    if len(live) < LIVE_POOL_MIN:
        print(
            f"ОШИБКА: живых ссылок слишком мало ({len(live)} < {LIVE_POOL_MIN})."
        )
        return 2

    urls = cycle_to_n(live, TOTAL_DOWNLOADS)
    print(
        f"  ✓ пул {len(live)} живых → зациклено до {len(urls)} запросов"
    )
    print()
    print(
        f"Старт soak: {TOTAL_DOWNLOADS} загрузок, "
        f"workers={WORKERS}, timeout={REQUEST_TIMEOUT:.0f}s, "
        f"jitter={JITTER_MIN}-{JITTER_MAX}s"
    )
    print(f"RAM до старта: {rss_mb():.1f} МБ")
    print("-" * 72)

    report = await run_soak(urls)
    report.pool_size = len(live)
    report.pool_source = cand_source
    print_final_report(report)
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
