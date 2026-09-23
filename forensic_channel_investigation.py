#!/usr/bin/env python3
"""Public-data deconstruction of a YouTube channel. No login, no bypass.

Four independent investigations:
  1. Publish-time histogram from a local CSV (timezone / cron / sleep gap).
  2. Channel passport via yt-dlp and the public InnerTube browse payload.
  3. OSINT on a business email already published on the channel.
  4. ffprobe of one downloaded Short (delivery encode, not the edit master).

Outputs: forensic_dossier.md, forensic_evidence.json

Install:
    python -m pip install yt-dlp pandas httpx
Also on PATH for investigation 4: ffmpeg, ffprobe
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import subprocess
import sys
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "endlesslove_data.csv"
REPORT_PATH = ROOT / "forensic_dossier.md"
EVIDENCE_PATH = ROOT / "forensic_evidence.json"
TMP_DIR = ROOT / "forensic_tmp"

CHANNEL_URL = "https://www.youtube.com/@Endlesslove025"
CHANNEL_HANDLE = "Endlesslove025"
EMAIL = "successfrom2024@gmail.com"
VIDEO_ID = "z3FjecFvGVs"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Offset is not a country. Candidates are the common places that keep that
# civil clock in winter or year-round. DST can move a zone by one hour.
OFFSET_CANDIDATES = {
    -12: ["Baker Island (UTC−12)"],
    -11: ["American Samoa", "Niue"],
    -10: ["Hawaii", "Tahiti"],
    -9: ["Alaska (winter)", "French Polynesia (Marquesas is −9:30)"],
    -8: ["US/Canada Pacific (winter)", "Baja California"],
    -7: ["US/Canada Mountain (winter)", "Arizona (no DST)"],
    -6: ["US/Canada Central (winter)", "Mexico City", "Costa Rica"],
    -5: ["US/Canada Eastern (winter)", "Colombia", "Peru", "Ecuador"],
    -4: ["Atlantic (winter)", "Venezuela", "Bolivia", "Chile (varies)"],
    -3: ["Argentina", "Brazil (Brasília, no DST)", "Uruguay"],
    -2: ["South Georgia"],
    -1: ["Azores (winter)", "Cape Verde"],
    0: ["UK/Ireland (winter)", "Portugal", "Morocco", "Ghana", "Iceland"],
    1: ["Central Europe (winter)", "Nigeria", "Algeria", "UK/Ireland (summer)"],
    2: ["Eastern Europe (winter)", "South Africa", "Egypt", "Israel (winter)", "Central Europe (summer)"],
    3: ["Moscow", "Turkey", "Saudi Arabia", "Kenya", "Iraq", "Eastern Europe (summer)"],
    4: ["UAE", "Oman", "Azerbaijan", "Mauritius", "Georgia", "Samara"],
    5: ["Pakistan", "Uzbekistan", "Maldives", "Yekaterinburg"],
    6: ["Bangladesh", "Kazakhstan (most)", "Omsk", "Kyrgyzstan"],
    7: ["Thailand", "Vietnam", "Indonesia (west)", "Novosibirsk / Krasnoyarsk"],
    8: ["China", "Singapore", "Malaysia", "Philippines", "Western Australia", "Irkutsk"],
    9: ["Japan", "South Korea", "Yakutsk"],
    10: ["Eastern Australia (winter)", "Vladivostok", "Papua New Guinea"],
    11: ["Solomon Islands", "Magadan", "Eastern Australia (summer)"],
    12: ["New Zealand (winter)", "Fiji", "Kamchatka"],
    13: ["Tonga", "Samoa", "New Zealand (summer)"],
    14: ["Kiribati (Line Islands)"],
}

QUARTER_MINUTES = {0, 15, 30, 45}
ENCODER_MARKS = (
    ("capcut", "CapCut"),
    ("bytedance", "CapCut / ByteDance"),
    ("premiere", "Adobe Premiere"),
    ("adobe", "Adobe"),
    ("handbrake", "HandBrake"),
    ("lavf", "FFmpeg (Lavf)"),
    ("lavc", "FFmpeg (Lavc)"),
    ("libx264", "x264 / FFmpeg"),
    ("x264", "x264"),
    ("google", "Google / YouTube delivery"),
    ("youtube", "YouTube delivery"),
    ("inshot", "InShot"),
    ("vn ", "VN Video Editor"),
    ("kinemaster", "KineMaster"),
    ("imovie", "iMovie"),
    ("final cut", "Final Cut"),
    ("davinci", "DaVinci Resolve"),
    ("obs", "OBS"),
    ("shutter", "Shutter Encoder"),
)

SHORTS_CANVASES = (
    (1080, 1920),
    (720, 1280),
    (1080, 1080),
    (720, 720),
    (1920, 1080),
    (1280, 720),
    (608, 1080),
    (405, 720),
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    return str(value)


def walk_key(node, key: str, hits: list | None = None) -> list:
    hits = hits if hits is not None else []
    if isinstance(node, dict):
        if key in node:
            hits.append(node[key])
        for value in node.values():
            walk_key(value, key, hits)
    elif isinstance(node, list):
        for value in node:
            walk_key(value, key, hits)
    return hits


def text_of(node) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float)):
        return str(node)
    if isinstance(node, dict):
        if "simpleText" in node:
            return str(node["simpleText"])
        if "content" in node and not isinstance(node["content"], (dict, list)):
            return str(node["content"])
        if "runs" in node and isinstance(node["runs"], list):
            return "".join(text_of(part) for part in node["runs"])
        if "content" in node:
            return text_of(node["content"])
    return ""


def extract_brace_object(html: str, marker: str) -> dict | None:
    index = html.find(marker)
    if index < 0:
        return None
    start = html.find("{", index)
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for pos in range(start, len(html)):
        char = html[pos]
        if in_str:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_str = False
            continue
        if char == '"':
            in_str = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                blob = html[start : pos + 1]
                try:
                    return json.loads(blob)
                except json.JSONDecodeError:
                    return None
    return None


def http_get(url: str, timeout: float = 40.0) -> tuple[int, str]:
    import httpx

    response = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=timeout)
    return response.status_code, response.text


def http_post_json(url: str, payload: dict, timeout: float = 40.0) -> tuple[int, dict | str]:
    import httpx

    response = httpx.post(
        url,
        headers={**HEADERS, "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    try:
        return response.status_code, response.json()
    except json.JSONDecodeError:
        return response.status_code, response.text[:500]


def chi_square(observed: list[int]) -> float:
    total = sum(observed)
    if total <= 0 or not observed:
        return 0.0
    expected = total / len(observed)
    if expected <= 0:
        return 0.0
    return sum((count - expected) ** 2 / expected for count in observed)


def circular_window(counts: list[int], length: int) -> dict:
    best = None
    for start in range(24):
        hours = [(start + offset) % 24 for offset in range(length)]
        total = sum(counts[hour] for hour in hours)
        candidate = {"start": start, "length": length, "hours": hours, "posts": total}
        if best is None or total < best["posts"] or (
            total == best["posts"] and length > best["length"]
        ):
            best = candidate
    return best or {"start": 0, "length": length, "hours": [], "posts": 0}


def wrap_offset(hours: int) -> int:
    hours = hours % 24
    if hours > 14:
        hours -= 24
    if hours < -12:
        hours += 24
    return hours


def fmt_offset(hours: int) -> str:
    sign = "+" if hours >= 0 else "−"
    return f"UTC{sign}{abs(hours)}"


def spark(counts: list[int]) -> str:
    blocks = " ▁▂▃▄▅▆▇█"
    peak = max(counts) if counts else 0
    if peak <= 0:
        return "░" * len(counts)
    return "".join(blocks[min(8, int(round(8 * count / peak)))] or " " for count in counts)


def load_times(csv_path: Path) -> tuple[list[datetime], list[str]]:
    import pandas as pd

    frame = pd.read_csv(csv_path)
    column = None
    for name in ("published_time", "upload_date", "published", "timestamp"):
        if name in frame.columns:
            column = name
            break
    if column is None:
        raise SystemExit(f"no time column in {csv_path}: {list(frame.columns)}")
    notes = [f"column={column}", f"rows={len(frame)}"]
    parsed = pd.to_datetime(frame[column], utc=True, errors="coerce")
    times = [value.to_pydatetime() for value in parsed.dropna()]
    dropped = int(parsed.isna().sum())
    if dropped:
        notes.append(f"unparsed={dropped}")
    return times, notes


def investigate_schedule(csv_path: Path) -> dict:
    result = {"name": "timezone_cron", "ok": False, "errors": [], "notes": []}
    try:
        times, notes = load_times(csv_path)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(str(exc))
        return result
    result["notes"].extend(notes)
    if len(times) < 8:
        result["errors"].append(f"too few timestamps: {len(times)}")
        return result

    minute_counts = [0] * 60
    second_counts = [0] * 60
    hour_counts = [0] * 24
    weekday_counts = [0] * 7
    for stamp in times:
        minute_counts[stamp.minute] += 1
        second_counts[stamp.second] += 1
        hour_counts[stamp.hour] += 1
        weekday_counts[stamp.weekday()] += 1

    n = len(times)
    quarter = sum(minute_counts[minute] for minute in QUARTER_MINUTES)
    top_minutes = Counter({minute: count for minute, count in enumerate(minute_counts) if count})
    top_minute, top_minute_n = top_minutes.most_common(1)[0]
    minute_chi = chi_square(minute_counts)
    # Uniform 60-bin chi-square: critical value ~79 at p=0.05, ~88 at p=0.01.
    quarter_share = quarter / n
    top_share = top_minute_n / n
    autopost = quarter_share >= 0.45 or top_share >= 0.35
    if top_share >= 0.6 and top_minute in QUARTER_MINUTES:
        autopost_label = "сильный признак планировщика"
        autopost_conf = "high"
    elif autopost:
        autopost_label = "умеренный признак слотов :00/:15/:30/:45"
        autopost_conf = "medium"
    else:
        autopost_label = "кучкования по четвертям часа нет"
        autopost_conf = "low"

    second_mode, second_mode_n = Counter(stamp.second for stamp in times).most_common(1)[0]
    narrow_seconds = sum(1 for stamp in times if stamp.second <= 40) / n

    zero_hours = [hour for hour, count in enumerate(hour_counts) if count == 0]
    windows = {length: circular_window(hour_counts, length) for length in (6, 7, 8)}
    empty = [item for item in windows.values() if item["posts"] == 0]
    if empty:
        quiet = max(empty, key=lambda item: item["length"])
        quiet_kind = "полное отсутствие постов"
    else:
        quiet = min(windows.values(), key=lambda item: (item["posts"] / item["length"], -item["length"]))
        quiet_kind = "самая пустая полоса, не нулевая"
    expected_quiet = n * quiet["length"] / 24
    quiet_ratio = (quiet["posts"] / expected_quiet) if expected_quiet else 1.0
    # A sleep gap is a hole, not the short side of a flat histogram.
    has_sleep_gap = quiet["posts"] == 0 or quiet_ratio <= 0.25

    # Two sleep hypotheses. A scheduler that posts on the hour invalidates both.
    hypotheses = []
    quiet_start = quiet["start"]
    quiet_len = quiet["length"]
    for local_start, label in ((0, "сон примерно 00:00–0{n} local"), (23, "сон примерно 23:00 local")):
        offset = wrap_offset(local_start - quiet_start)
        end_local = (local_start + quiet_len) % 24
        hypotheses.append(
            {
                "label": label.format(n=quiet_len),
                "offset_hours": offset,
                "offset": fmt_offset(offset),
                "local_window": f"{local_start:02d}:00–{end_local:02d}:00",
                "candidates": OFFSET_CANDIDATES.get(offset, []),
            }
        )

    month_hours: dict[str, list[int]] = {}
    for stamp in times:
        key = stamp.strftime("%Y-%m")
        month_hours.setdefault(key, [0] * 24)
        month_hours[key][stamp.hour] += 1
    month_quiet = {}
    for key, counts in sorted(month_hours.items()):
        if sum(counts) < 8:
            continue
        slot = circular_window(counts, 7)
        month_quiet[key] = {"start": slot["start"], "posts": slot["posts"], "n": sum(counts)}
    starts = [item["start"] for item in month_quiet.values()]
    dst_shift = (max(starts) - min(starts)) if len(starts) >= 2 else 0
    month_windows_are_gaps = bool(month_quiet) and all(
        item["posts"] <= max(1, 0.25 * item["n"] * 7 / 24) for item in month_quiet.values()
    )

    gaps_h = []
    ordered = sorted(times)
    for left, right in zip(ordered, ordered[1:]):
        gaps_h.append((right - left).total_seconds() / 3600)
    median_gap = statistics.median(gaps_h) if gaps_h else None

    if not has_sleep_gap:
        tz_conf = "none"
        tz_note = (
            f"Окна сна нет: в самой пустой полосе {quiet['length']} ч "
            f"{quiet['posts']} постов при ~{expected_quiet:.0f}, если бы сетка была ровной "
            f"(ratio {quiet_ratio:.2f}). Смещение UTC из этого не выводится."
        )
    elif autopost_conf == "high":
        tz_conf = "low"
        tz_note = (
            "Пустая полоса есть, но минута слота фиксирована. Это может быть пауза "
            "планировщика, а не сон. Смещение ниже — гипотеза, не страна."
        )
    else:
        tz_conf = "medium"
        tz_note = "Нулевая полоса 6+ часов совместима со сном, но смещение — гипотеза, не страна."

    result.update(
        {
            "ok": True,
            "n": n,
            "span": {
                "first": ordered[0].isoformat(),
                "last": ordered[-1].isoformat(),
            },
            "minute_counts": minute_counts,
            "hour_counts": hour_counts,
            "weekday_counts": weekday_counts,
            "top_minutes": top_minutes.most_common(8),
            "quarter_share": round(quarter_share, 4),
            "top_minute": top_minute,
            "top_minute_share": round(top_share, 4),
            "minute_chi_square": round(minute_chi, 1),
            "autopost": autopost,
            "autopost_label": autopost_label,
            "autopost_confidence": autopost_conf,
            "second_mode": second_mode,
            "second_mode_share": round(second_mode_n / n, 4),
            "seconds_le_40_share": round(narrow_seconds, 4),
            "zero_hours_utc": zero_hours,
            "quiet": quiet,
            "quiet_kind": quiet_kind,
            "quiet_ratio": round(quiet_ratio, 3),
            "has_sleep_gap": has_sleep_gap,
            "hypotheses": hypotheses if has_sleep_gap else [],
            "timezone_confidence": tz_conf,
            "timezone_note": tz_note,
            "month_quiet_start_utc": month_quiet,
            "month_quiet_start_spread": dst_shift if month_windows_are_gaps else None,
            "month_quiet_usable": month_windows_are_gaps,
            "median_gap_hours": None if median_gap is None else round(median_gap, 2),
            "hour_spark": spark(hour_counts),
        }
    )
    return result


def _innertube_context(client_version: str) -> dict:
    return {
        "client": {
            "clientName": "WEB",
            "clientVersion": client_version or "2.20250101.00.00",
            "hl": "en",
            "gl": "US",
        }
    }


def _about_blobs(initial: dict) -> list[dict]:
    blobs = []
    for key in ("aboutChannelViewModel", "channelAboutFullMetadataRenderer", "channelMetadataRenderer"):
        blobs.extend(item for item in walk_key(initial, key) if isinstance(item, dict))
    return blobs


def _header_blobs(initial: dict) -> list[dict]:
    blobs = []
    for key in (
        "c4TabbedHeaderRenderer",
        "pageHeaderViewModel",
        "channelHeaderViewModel",
        "carouselHeaderRenderer",
    ):
        blobs.extend(item for item in walk_key(initial, key) if isinstance(item, dict))
    return blobs


def _best_thumbnail(node) -> str:
    thumbs = []
    if isinstance(node, dict):
        sources = node.get("thumbnails") or node.get("sources") or []
        if isinstance(sources, list):
            thumbs = sources
        avatar = node.get("avatar") or node.get("image") or {}
        if isinstance(avatar, dict):
            sources = avatar.get("thumbnails") or avatar.get("sources") or []
            if isinstance(sources, list):
                thumbs = sources or thumbs
    if not thumbs:
        return ""
    ranked = sorted(
        (item for item in thumbs if isinstance(item, dict) and item.get("url")),
        key=lambda item: int(item.get("width") or 0),
    )
    return str(ranked[-1]["url"]) if ranked else ""


def _parse_joined(text: str) -> str:
    cleaned = re.sub(r"^(joined|signed up)\s+", "", (text or "").strip(), flags=re.I)
    for fmt in ("%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return cleaned


def _collect_declared_links(initial: dict, own_id: str) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()

    def add(kind: str, title: str, url: str, channel_id: str = "") -> None:
        key = (channel_id or url or title).strip()
        if not key or key in seen:
            return
        if channel_id and channel_id == own_id:
            return
        seen.add(key)
        found.append(
            {
                "kind": kind,
                "title": title.strip(),
                "url": url.strip(),
                "channel_id": channel_id,
            }
        )

    for blob in walk_key(initial, "channelExternalLinkViewModel"):
        if not isinstance(blob, dict):
            continue
        link = blob.get("link") or {}
        url = text_of(link) or str(link.get("content") or "")
        add("about_link", text_of(blob.get("title")), url)

    for blob in walk_key(initial, "channelFeaturedContentRenderer"):
        if not isinstance(blob, dict):
            continue
        title = text_of(blob.get("title"))
        for item in blob.get("items") or []:
            renderer = item.get("channelRenderer") if isinstance(item, dict) else None
            if not isinstance(renderer, dict):
                continue
            cid = str(renderer.get("channelId") or "")
            nav = ((renderer.get("navigationEndpoint") or {}).get("browseEndpoint") or {})
            url = str(nav.get("canonicalBaseUrl") or "")
            add("featured", text_of(renderer.get("title")) or title, url, cid)

    return found


def _keywords_from(blobs: list[dict], ydl_info: dict) -> list[str]:
    raw = []
    for blob in blobs:
        value = blob.get("keywords")
        if isinstance(value, str) and value.strip():
            raw.append(value)
        if isinstance(value, list):
            raw.extend(str(item) for item in value)
    tags = ydl_info.get("tags") or []
    if isinstance(tags, list):
        raw.extend(str(item) for item in tags if item)
    words: list[str] = []
    seen: set[str] = set()
    for chunk in raw:
        parts = re.findall(r'"[^"]+"|\S+', chunk)
        for part in parts:
            token = part.strip().strip('"')
            key = token.lower()
            if token and key not in seen:
                seen.add(key)
                words.append(token)
    return words


def investigate_channel(url: str) -> dict:
    result = {
        "name": "channel_fingerprint",
        "ok": False,
        "errors": [],
        "url": url,
        "declared_links": [],
        "keywords": [],
    }
    html = ""
    initial: dict = {}
    try:
        status, html = http_get(url)
        result["page_status"] = status
        if status >= 400:
            result["errors"].append(f"channel page HTTP {status}")
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"channel page: {exc}")

    if html:
        initial = extract_brace_object(html, "ytInitialData") or {}
        result["initial_data"] = bool(initial)

    client_version = ""
    api_key = ""
    if html:
        version_match = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', html)
        key_match = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', html)
        client_version = version_match.group(1) if version_match else ""
        api_key = key_match.group(1) if key_match else ""
        result["client_version"] = client_version

    channel_ids = [item for item in walk_key(initial, "externalId") if isinstance(item, str) and item.startswith("UC")]
    channel_ids += [item for item in walk_key(initial, "channelId") if isinstance(item, str) and item.startswith("UC")]
    own_id = channel_ids[0] if channel_ids else ""

    about_params = []
    for tab in walk_key(initial, "tabRenderer"):
        if not isinstance(tab, dict):
            continue
        title = text_of(tab.get("title")).lower()
        endpoint = ((tab.get("endpoint") or {}).get("browseEndpoint") or {})
        params = endpoint.get("params")
        if title in {"about", "о канале"} and params:
            about_params.append(params)
    if own_id and api_key and about_params:
        browse_url = f"https://www.youtube.com/youtubei/v1/browse?key={api_key}&prettyPrint=false"
        try:
            status, payload = http_post_json(
                browse_url,
                {
                    "context": _innertube_context(client_version),
                    "browseId": own_id,
                    "params": about_params[0],
                },
            )
            result["about_status"] = status
            if isinstance(payload, dict):
                initial = {"header": initial, "about": payload}
            else:
                result["errors"].append("about browse returned non-JSON")
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"about browse: {exc}")

    blobs = _about_blobs(initial)
    headers = _header_blobs(initial)
    about = next((blob for blob in blobs if "country" in blob or "joinedDateText" in blob or "joinedDate" in blob), blobs[0] if blobs else {})
    meta = next((blob for blob in blobs if blob.get("keywords") or blob.get("avatar")), {})

    joined_raw = text_of(about.get("joinedDateText")) or text_of(about.get("joinedDate")) or ""
    country = str(about.get("country") or about.get("countryText") or "")
    if isinstance(about.get("country"), dict):
        country = text_of(about.get("country"))

    banner = ""
    avatar = _best_thumbnail(meta) or _best_thumbnail(about)
    for header in headers:
        banner = banner or _best_thumbnail(header.get("banner") or header.get("bannerImage") or {})
        avatar = avatar or _best_thumbnail(header.get("avatar") or {})
        if not banner:
            for key in ("banner", "image", "contentImage"):
                banner = banner or _best_thumbnail(header.get(key) or {})

    handle = ""
    for source in (walk_key(initial, "canonicalChannelUrl"), walk_key(initial, "channelHandleText")):
        for item in source:
            text = text_of(item) if not isinstance(item, str) else item
            match = re.search(r"@([\w.\-]+)", text or "")
            if match:
                handle = match.group(1)
                break
        if handle:
            break

    title = ""
    for key in ("title", "channelTitle"):
        for item in walk_key(initial, key):
            text = text_of(item) if not isinstance(item, str) else item
            if text and len(text) < 120 and "subscribers" not in text.lower():
                title = text
                break
        if title:
            break

    description = text_of(about.get("description")) or str(about.get("description") or "")
    subscriber_text = text_of(about.get("subscriberCountText"))
    view_text = text_of(about.get("viewCountText"))
    video_text = text_of(about.get("videoCountText"))

    ydl_info: dict = {}
    try:
        import yt_dlp

        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
            "playlistend": 1,
            "ignoreerrors": True,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False) or {}
        keep = (
            "id",
            "channel_id",
            "channel",
            "channel_url",
            "uploader",
            "uploader_id",
            "uploader_url",
            "description",
            "tags",
            "channel_follower_count",
            "view_count",
            "playlist_count",
            "thumbnails",
        )
        ydl_info = {key: info.get(key) for key in keep}
        if not own_id:
            own_id = str(info.get("channel_id") or info.get("uploader_id") or "")
        title = title or str(info.get("channel") or info.get("uploader") or "")
        handle = handle or str(info.get("uploader_id") or "").lstrip("@")
        description = description or str(info.get("description") or "")
        if not avatar and info.get("thumbnails"):
            avatar = _best_thumbnail({"thumbnails": info.get("thumbnails")})
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"yt-dlp: {exc}")

    emails = sorted(set(re.findall(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", description or "", flags=re.I)))
    links = _collect_declared_links(initial, own_id)
    keywords = _keywords_from(blobs + [meta], ydl_info)

    wayback = []
    try:
        cdx = (
            "https://web.archive.org/cdx/search/cdx?url="
            + urllib.parse.quote(f"youtube.com/@{handle or CHANNEL_HANDLE}")
            + "&output=json&fl=timestamp,original,statuscode&filter=statuscode:200&limit=8"
        )
        status, body = http_get(cdx, timeout=25)
        result["wayback_status"] = status
        if status == 200 and body.startswith("["):
            rows = json.loads(body)
            for row in rows[1:]:
                if len(row) >= 2:
                    wayback.append({"timestamp": row[0], "url": row[1]})
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"wayback: {exc}")

    joined = _parse_joined(joined_raw) if joined_raw else ""
    rebrand_notes = []
    display = title.strip()
    if handle and display and handle.lower().replace(".", "") not in display.lower().replace(" ", ""):
        if display.lower().replace(" ", "") not in handle.lower():
            rebrand_notes.append(
                f"отображаемое имя «{display}» не совпадает с хэндлом @{handle} — само по себе это не ребрендинг"
            )
    if wayback:
        first = wayback[0]["timestamp"]
        first_day = f"{first[:4]}-{first[4:6]}-{first[6:8]}"
        rebrand_notes.append(f"первый снимок Wayback хэндла @{handle or CHANNEL_HANDLE}: {first_day}")
        if joined and first_day > joined and (datetime.fromisoformat(first_day) - datetime.fromisoformat(joined)).days > 120:
            rebrand_notes.append(
                "хэндл в архиве появляется заметно позже даты создания — возможен поздний @handle или смена адреса, не доказанный ребрендинг"
            )
    else:
        rebrand_notes.append("снимков Wayback по хэндлу нет — историю имени подтвердить нельзя")
    if not joined:
        rebrand_notes.append("дата создания с About не извлечена")

    result.update(
        {
            "ok": bool(own_id or title or description),
            "channel_id": own_id,
            "handle": handle,
            "title": title,
            "country": country or "",
            "country_note": (
                "страна регистрации с вкладки About"
                if country
                else "страна на About не указана; availableCountryCodes — это гео-доступность, не регистрация, и в отчёт не берётся"
            ),
            "joined_raw": joined_raw,
            "joined": joined,
            "description": description,
            "emails_in_about": emails,
            "subscriber_text": subscriber_text,
            "view_text": view_text,
            "video_text": video_text,
            "subscriber_count": ydl_info.get("channel_follower_count"),
            "avatar_url": avatar,
            "banner_url": banner,
            "keywords": keywords,
            "declared_links": links,
            "wayback": wayback,
            "rebrand_notes": rebrand_notes,
            "yt_dlp": {key: value for key, value in ydl_info.items() if key != "thumbnails"},
        }
    )
    return result


def _decode_ddg(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query:
        return urllib.parse.unquote(query["uddg"][0])
    return url


def _handles_from_text(text: str) -> list[str]:
    return sorted(set(re.findall(r"@([A-Za-z0-9._]{3,40})", text or "")))


def investigate_email(email: str, own_handle: str) -> dict:
    result = {
        "name": "email_osint",
        "ok": False,
        "errors": [],
        "email": email,
        "queries": [],
        "youtube_hits": [],
        "web_hits": [],
        "other_handles": [],
    }
    local = email.split("@", 1)[0]
    queries = [
        f'"{email}"',
        f"{email} site:youtube.com",
        local,
    ]
    result["queries"] = queries

    yt_queries = [email, local]
    handles: set[str] = set()
    try:
        import httpx
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"httpx: {exc}")
        return result

    for query in yt_queries:
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
        try:
            status, html = http_get(url)
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"youtube search {query!r}: {exc}")
            continue
        initial = extract_brace_object(html, "ytInitialData") or {}
        hits = []
        for renderer_name in ("videoRenderer", "channelRenderer", "reelItemRenderer"):
            for renderer in walk_key(initial, renderer_name):
                if not isinstance(renderer, dict):
                    continue
                title = text_of(renderer.get("title"))
                owner = renderer.get("ownerText") or renderer.get("shortBylineText") or {}
                owner_text = text_of(owner)
                video_id = str(renderer.get("videoId") or "")
                channel_id = str(renderer.get("channelId") or "")
                url_path = ""
                nav = renderer.get("navigationEndpoint") or {}
                browse = (nav.get("browseEndpoint") or {}).get("canonicalBaseUrl") or ""
                if video_id:
                    url_path = f"https://www.youtube.com/watch?v={video_id}"
                elif browse:
                    url_path = "https://www.youtube.com" + browse
                elif channel_id:
                    url_path = f"https://www.youtube.com/channel/{channel_id}"
                if not (title or owner_text or url_path):
                    continue
                hit = {
                    "query": query,
                    "kind": renderer_name,
                    "title": title,
                    "owner": owner_text,
                    "url": url_path,
                    "channel_id": channel_id,
                }
                hits.append(hit)
                blob = f"{title} {owner_text} {url_path}"
                handles.update(_handles_from_text(blob))
        result["youtube_hits"].extend(hits[:12])
        result.setdefault("youtube_search_status", {})[query] = status
        if "consent" in html.lower() and "ytInitialData" not in html:
            result["errors"].append(f"youtube search {query!r} looks like a consent wall")

    google_url = "https://www.google.com/search?gbv=1&num=10&q=" + urllib.parse.quote(f'"{email}"')
    try:
        status, body = http_get(google_url, timeout=25)
        result["google_status"] = status
        blocked = status in {429, 503} or "unusual traffic" in body.lower() or "/sorry/" in body
        result["google_blocked"] = blocked
        if not blocked:
            for match in re.finditer(r'<a href="/url\?q=([^"&]+)[^"]*"[^>]*>(.*?)</a>', body, flags=re.S):
                href = urllib.parse.unquote(match.group(1))
                title = html_unescape(re.sub(r"<[^>]+>", "", match.group(2)))
                title = re.sub(r"\s+", " ", title).strip()
                if not href.startswith("http"):
                    continue
                result["web_hits"].append({"title": title or href, "url": href, "query": f"google:{email}"})
                handles.update(_handles_from_text(title + " " + href))
        else:
            result["errors"].append("Google search bot-wall; web hits fall back to DuckDuckGo")
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"google: {exc}")

    ddg_url = "https://html.duckduckgo.com/html/"
    try:
        response = httpx.post(
            ddg_url,
            headers=HEADERS,
            data={"q": f'"{email}"', "b": ""},
            timeout=40,
            follow_redirects=True,
        )
        result["ddg_status"] = response.status_code
        body = response.text
        for match in re.finditer(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            body,
            flags=re.S,
        ):
            href = _decode_ddg(html_unescape(match.group(1)))
            title = re.sub(r"<[^>]+>", "", match.group(2))
            title = html_unescape(re.sub(r"\s+", " ", title)).strip()
            if not href or href.startswith("/"):
                continue
            result["web_hits"].append({"title": title, "url": href, "query": email})
            handles.update(_handles_from_text(title + " " + href))
        if not result["web_hits"] and "anomaly" in body.lower():
            result["errors"].append("DuckDuckGo returned a bot check, web hits empty")
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"duckduckgo: {exc}")

    own = (own_handle or CHANNEL_HANDLE).lower()
    others = sorted(handle for handle in handles if handle.lower() not in {own, "gmail", "youtube"})
    result["other_handles"] = others
    result["ok"] = True
    result["conclusion"] = (
        "другие каналы с этой почтой в выдаче не всплыли"
        if not others and not result["web_hits"]
        else "есть следы вне исходного хэндла — смотреть список, это не доказательство владения"
    )
    return result


def html_unescape(text: str) -> str:
    return (
        text.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#x27;", "'")
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
    )


def _classify_encoder(blob: str) -> list[str]:
    lowered = blob.lower()
    hits = []
    for needle, label in ENCODER_MARKS:
        if needle in lowered and label not in hits:
            hits.append(label)
    return hits


def _frac_fps(rate: str) -> float | None:
    if not rate or rate in {"0/0", "N/A"}:
        return None
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            den_f = float(den)
            return None if den_f == 0 else float(num) / den_f
        except ValueError:
            return None
    try:
        return float(rate)
    except ValueError:
        return None


def _nearest_fps(value: float | None) -> str:
    if value is None:
        return "unknown"
    named = (24, 25, 30, 50, 60, 23.976, 29.97, 59.94)
    best = min(named, key=lambda item: abs(item - value))
    if abs(best - value) < 0.08:
        return f"{best:g} fps (measured {value:.3f})"
    return f"{value:.3f} fps (не стандарт 24/25/30/60)"


def download_video(video_id: str, dest: Path) -> Path:
    import yt_dlp

    dest.mkdir(parents=True, exist_ok=True)
    existing = list(dest.glob(f"{video_id}.*"))
    ready = [path for path in existing if path.suffix.lower() in {".mp4", ".webm", ".mkv"} and path.stat().st_size > 100_000]
    if ready:
        return ready[0]
    options = {
        "quiet": True,
        "no_warnings": True,
        "outtmpl": str(dest / "%(id)s.%(ext)s"),
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "noprogress": True,
    }
    url = f"https://www.youtube.com/shorts/{video_id}"
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
        if path.suffix.lower() != ".mp4":
            merged = path.with_suffix(".mp4")
            if merged.is_file():
                return merged
        if path.is_file():
            return path
    found = list(dest.glob(f"{video_id}.*"))
    if not found:
        raise RuntimeError("download finished but file is missing")
    return found[0]


def probe_file(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe not on PATH")
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-print_format",
        "json",
        str(path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"ffprobe exit {completed.returncode}")
    return json.loads(completed.stdout or "{}")


def cropdetect(path: Path) -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return ""
    command = [
        ffmpeg,
        "-hide_banner",
        "-i",
        str(path),
        "-vf",
        "cropdetect=24:2:0",
        "-frames:v",
        "90",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    crops = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", completed.stderr or "")
    if not crops:
        return ""
    return "crop=" + ":".join(Counter(crops).most_common(1)[0][0])


def investigate_media(video_id: str, dest: Path) -> dict:
    result = {
        "name": "ffprobe",
        "ok": False,
        "errors": [],
        "video_id": video_id,
        "url": f"https://www.youtube.com/shorts/{video_id}",
    }
    try:
        path = download_video(video_id, dest)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"download: {exc}")
        return result
    result["file"] = str(path)
    result["bytes"] = path.stat().st_size
    try:
        probe = probe_file(path)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(str(exc))
        return result

    fmt = probe.get("format") or {}
    streams = probe.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    tags = {}
    tags.update(fmt.get("tags") or {})
    tags.update(video.get("tags") or {})
    tags.update(audio.get("tags") or {})
    tag_blob = " ".join(f"{key}={value}" for key, value in tags.items())
    encoders = _classify_encoder(tag_blob)
    handler = str(tags.get("handler_name") or video.get("tags", {}).get("handler_name") or "")
    youtube_delivery = any(
        needle in (tag_blob + " " + handler).lower()
        for needle in ("google", "youtube", "iso media file produced by google")
    )
    if youtube_delivery and "Google / YouTube delivery" not in encoders:
        encoders.insert(0, "Google / YouTube delivery")

    fps = _frac_fps(str(video.get("avg_frame_rate") or video.get("r_frame_rate") or ""))
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    side = video.get("side_data_list") or []
    matrix = []
    for item in side:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("side_data_type") or "")
        if kind == "Display Matrix" or "matrix" in json.dumps(item).lower():
            matrix.append(item)
    rotation = video.get("tags", {}).get("rotate") if isinstance(video.get("tags"), dict) else None

    crop = ""
    try:
        crop = cropdetect(path)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"cropdetect: {exc}")
    crop_note = "cropdetect не дал строки"
    micro_zoom = "нет файлового признака"
    if crop:
        match = re.fullmatch(r"crop=(\d+):(\d+):(\d+):(\d+)", crop)
        if match and width and height:
            cw, ch, cx, cy = (int(part) for part in match.groups())
            inset_x = width - cw
            inset_y = height - ch
            if inset_x >= 8 or inset_y >= 8 or cx > 2 or cy > 2:
                micro_zoom = (
                    f"cropdetect видит поля/обрезку {crop} против кадра {width}x{height} — "
                    "возможны letterbox или burned-in crop, не доказанный «микро-зум против дублей»"
                )
            else:
                micro_zoom = f"кадр заполнен ({crop}); микро-зум после масштабирования YouTube так не виден"

    canvas_delta = None
    if width and height:
        canvas_delta = min(
            abs(width - cw) + abs(height - ch) for cw, ch in SHORTS_CANVASES
        )
    odd_size = bool(width and height and (width % 2 or height % 2 or canvas_delta and canvas_delta > 16))

    mirror = "в контейнере нет displaymatrix с отражением"
    matrix_text = json.dumps(matrix)
    if rotation not in (None, "0", 0):
        mirror = f"есть rotate={rotation}; это поворот, не обязательно зеркало"
    if re.search(r"-\d", matrix_text) and "rotation" in matrix_text.lower():
        mirror = "displaymatrix содержит отрицательную компоненту — проверить вручную, это редкий признак flip"

    sample_rate = audio.get("sample_rate")
    result.update(
        {
            "ok": True,
            "format_name": fmt.get("format_name"),
            "duration": fmt.get("duration"),
            "bit_rate": int(fmt.get("bit_rate") or 0) or None,
            "video_codec": video.get("codec_name"),
            "video_profile": video.get("profile"),
            "width": width,
            "height": height,
            "fps": None if fps is None else round(fps, 3),
            "fps_label": _nearest_fps(fps),
            "r_frame_rate": video.get("r_frame_rate"),
            "avg_frame_rate": video.get("avg_frame_rate"),
            "pix_fmt": video.get("pix_fmt"),
            "video_bit_rate": int(video.get("bit_rate") or 0) or None,
            "sar": video.get("sample_aspect_ratio"),
            "dar": video.get("display_aspect_ratio"),
            "audio_codec": audio.get("codec_name"),
            "sample_rate": int(sample_rate) if sample_rate else None,
            "audio_channels": audio.get("channels"),
            "audio_bit_rate": int(audio.get("bit_rate") or 0) or None,
            "tags": {str(key): str(value) for key, value in tags.items()},
            "encoder_hits": encoders,
            "youtube_delivery_encode": youtube_delivery or not encoders,
            "cropdetect": crop or crop_note,
            "micro_zoom": micro_zoom,
            "mirror": mirror,
            "odd_size": odd_size,
            "production_note": (
                "Скачанный файл — транскод выдачи YouTube. Теги CapCut / Premiere / HandBrake "
                "на этом шаге почти всегда уже сняты. fps, разрешение и 44100 vs 48000 — "
                "слабые прокси, не паспорт монтажки."
                if youtube_delivery or "Lavf" not in " ".join(encoders)
                else "Теги энкодера сохранились; всё равно сверять с тем, что YouTube мог перепаковать контейнер."
            ),
        }
    )
    return result


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def _bar_table(counts: list[int], labels: list[str], head: str) -> list[str]:
    peak = max(counts) if counts else 1
    lines = [f"| {head} | n | |", "|---:|---:|---|"]
    for label, count in zip(labels, counts):
        width = 0 if peak == 0 else int(round(24 * count / peak))
        lines.append(f"| {label} | {count} | {'▇' * width} |")
    return lines


def render_report(payload: dict) -> str:
    schedule = payload["schedule"]
    channel = payload["channel"]
    email = payload["email"]
    media = payload["media"]
    lines = [
        "# Forensic dossier: @Endlesslove025",
        "",
        f"Снято: {payload['generated_at']}. Источник времен: `{payload['csv']}`.",
        "Только публичные метаданные и один скачанный Short. Это не доступ к аккаунту и не установление личности.",
        "",
        "## Профиль админа",
        "",
    ]

    if not schedule.get("ok"):
        lines.append("Расписание не посчитано: " + "; ".join(schedule.get("errors") or ["unknown"]))
    else:
        quiet = schedule["quiet"]
        hours = ", ".join(f"{hour:02d}" for hour in quiet["hours"])
        lines.extend(
            [
                f"- Постов в выборке: **{schedule['n']}**, интервал {schedule['span']['first']} → {schedule['span']['last']} (UTC).",
                f"- Автопостинг: **{schedule['autopost_label']}** (уверенность {schedule['autopost_confidence']}).",
                f"  Минута-мода **:{schedule['top_minute']:02d}** занимает {_pct(schedule['top_minute_share'])}; четверти часа (:00/:15/:30/:45) — {_pct(schedule['quarter_share'])}.",
                f"  χ² по 60 минутам = {schedule['minute_chi_square']} (равномерное распределение было бы около 59; сотни и выше — слот, не рука).",
                f"  Секунды ≤ 40: {_pct(schedule['seconds_le_40_share'])}. Мода секунды: :{schedule['second_mode']:02d} ({_pct(schedule['second_mode_share'])}). Планировщик YouTube часто открывает ролик через несколько секунд после слота.",
                f"- Тепловая карта UTC `00–23`: `{schedule['hour_spark']}`",
                f"- Самая пустая полоса {quiet['length']} ч ({quiet_kind(schedule)}): UTC {hours}. Постов внутри: {quiet['posts']}"
                + (
                    f", ratio к ровной сетке {schedule.get('quiet_ratio', '—')}."
                    if not schedule.get("has_sleep_gap")
                    else "."
                ),
                f"- Часовой пояс: уверенность **{schedule['timezone_confidence']}**. {schedule['timezone_note']}",
            ]
        )
        for hypo in schedule["hypotheses"]:
            places = ", ".join(hypo["candidates"][:6]) or "нет короткого списка"
            lines.append(
                f"  - Если {hypo['label']}, смещение **{hypo['offset']}** ({hypo['local_window']}). Кандидаты, не приговор: {places}."
            )
        if schedule.get("month_quiet_usable"):
            spread = schedule.get("month_quiet_start_spread") or 0
            lines.append(
                f"- Сдвиг пустого окна по месяцам: {spread} ч. "
                + (
                    "Окно стабильно — не похоже на летнее время в UTC-слоте."
                    if spread <= 1
                    else "Окно смещается больше чем на час — это не типичный DST, сетка менялась."
                )
            )
        else:
            lines.append(
                "- Помесячный сдвиг не считается: в месяцах нет настоящей дыры, "
                "argmin плоской гистограммы прыгает сам по себе и на DST не похож."
            )
        if schedule.get("median_gap_hours") is not None:
            lines.append(f"- Медианный зазор между роликами: {schedule['median_gap_hours']} ч.")
        lines.extend(["", "### Минуты часа", ""])
        notable = [(minute, count) for minute, count in enumerate(schedule["minute_counts"]) if count]
        notable.sort(key=lambda item: (-item[1], item[0]))
        lines.append("| минута | n | доля |")
        lines.append("|---:|---:|---:|")
        for minute, count in notable[:12]:
            lines.append(f"| :{minute:02d} | {count} | {_pct(count / schedule['n'])} |")
        lines.extend(["", "### Часы UTC", ""])
        lines.extend(_bar_table(schedule["hour_counts"], [f"{hour:02d}" for hour in range(24)], "час"))

    lines.extend(["", "## Возраст и происхождение", ""])
    if not channel.get("ok"):
        lines.append("Паспорт канала не собран: " + "; ".join(channel.get("errors") or ["unknown"]))
    else:
        lines.extend(
            [
                f"- Имя: **{channel.get('title') or '—'}**, хэндл @{channel.get('handle') or CHANNEL_HANDLE}.",
                f"- Channel ID: `{channel.get('channel_id') or 'не извлечён'}`.",
                f"- Дата создания: **{channel.get('joined') or channel.get('joined_raw') or 'не указана на About'}**.",
                f"- Страна регистрации: **{channel.get('country') or 'не указана'}**. {channel.get('country_note', '')}",
                f"- Подписчики (yt-dlp): {channel.get('subscriber_count') if channel.get('subscriber_count') is not None else channel.get('subscriber_text') or '—'}.",
                f"- Просмотры / ролики (About): {channel.get('view_text') or '—'} / {channel.get('video_text') or '—'}.",
                f"- Аватар: {channel.get('avatar_url') or '—'}",
                f"- Баннер: {channel.get('banner_url') or '—'}",
                f"- Ключевые слова: {', '.join(channel.get('keywords') or []) or 'нет'}",
                f"- Почта в тексте About: {', '.join(channel.get('emails_in_about') or []) or 'нет'}",
            ]
        )
        lines.append("- Ребрендинг:")
        for note in channel.get("rebrand_notes") or ["нет данных"]:
            lines.append(f"  - {note}")
        if channel.get("errors"):
            lines.append("- Частичные сбои: " + "; ".join(channel["errors"]))

    lines.extend(["", "## Почта successfrom2024@gmail.com", ""])
    lines.append(
        "Это адрес из публичного описания канала (приём чужих клипов), не взлом почтового ящика. "
        "Поиск — открытая выдача YouTube и DuckDuckGo."
    )
    if email.get("errors"):
        lines.append("- Сбои поиска: " + "; ".join(email["errors"]))
    lines.append(f"- Запросы: {', '.join(f'`{item}`' for item in email.get('queries') or [])}")
    lines.append(f"- Вывод: {email.get('conclusion') or 'поиск не завершён'}.")
    others = email.get("other_handles") or []
    lines.append(
        "- Другие хэндлы в выдаче: " + (", ".join(f"@{item}" for item in others) if others else "не найдены.")
    )
    web_hits = email.get("web_hits") or []
    if web_hits:
        lines.extend(["", "| источник | url |", "|---|---|"])
        for hit in web_hits[:15]:
            title = (hit.get("title") or "—").replace("|", "/")
            lines.append(f"| {title} | {hit.get('url')} |")
    else:
        lines.append("- Веб-выдача по точному адресу пустая или отсечена антиботом.")
    yt_hits = email.get("youtube_hits") or []
    if yt_hits:
        lines.extend(["", "YouTube search, первые совпадения (выдача шумная, попасть в неё ≠ совпадение почты):", ""])
        lines.extend(["| запрос | тип | заголовок | url |", "|---|---|---|---|"])
        for hit in yt_hits[:12]:
            title = (hit.get("title") or hit.get("owner") or "—").replace("|", "/")
            lines.append(
                f"| `{hit.get('query')}` | {hit.get('kind')} | {title} | {hit.get('url') or '—'} |"
            )

    lines.extend(["", "## Стек производства", ""])
    if not media.get("ok"):
        lines.append("Экспертиза файла не снята: " + "; ".join(media.get("errors") or ["unknown"]))
    else:
        kbps = f"{media['bit_rate'] / 1000:.0f} kbps" if media.get("bit_rate") else "—"
        v_kbps = f"{media['video_bit_rate'] / 1000:.0f} kbps" if media.get("video_bit_rate") else "—"
        a_kbps = f"{media['audio_bit_rate'] / 1000:.0f} kbps" if media.get("audio_bit_rate") else "—"
        lines.extend(
            [
                f"- Файл: `{media.get('file')}` ({media.get('bytes', 0) / 1e6:.1f} MB), Short `{media.get('video_id')}`.",
                f"- Это **выдача YouTube**, не мастер монтажа. {media.get('production_note')}",
                f"- Контейнер: {media.get('format_name')}, общий битрейт {kbps}, длительность {media.get('duration')} с.",
                f"- Видео: {media.get('video_codec')} {media.get('video_profile') or ''}, {media.get('width')}×{media.get('height')}, {media.get('fps_label')}, битрейт {v_kbps}, SAR {media.get('sar')}, DAR {media.get('dar')}, {media.get('pix_fmt')}.",
                f"- Аудио: {media.get('audio_codec') or 'нет'}, {media.get('sample_rate') or '—'} Hz, каналов {media.get('audio_channels') or '—'}, {a_kbps}.",
                f"- Теги энкодера: {', '.join(media.get('encoder_hits') or []) or 'нет распознанных меток'}.",
                f"- Зеркало: {media.get('mirror')}.",
                f"- Микро-зум / обрезка: {media.get('micro_zoom')}. cropdetect: `{media.get('cropdetect')}`.",
            ]
        )
        if media.get("tags"):
            lines.extend(["", "Теги контейнера:", ""])
            for key, value in list(media["tags"].items())[:20]:
                lines.append(f"- `{key}`: {value}")

    lines.extend(["", "## Сетка команды", ""])
    links = channel.get("declared_links") or []
    if links:
        lines.append("Заявленные ссылки и featured-полка (это единственное, что можно считать сеткой):")
        lines.append("")
        lines.extend(["| тип | имя | url | id |", "|---|---|---|---|"])
        for item in links:
            lines.append(
                f"| {item.get('kind')} | {item.get('title') or '—'} | {item.get('url') or '—'} | {item.get('channel_id') or '—'} |"
            )
    else:
        lines.append(
            "Заявленных featured-каналов и внешних ссылок в About не найдено. "
            "Рекомендации YouTube в сетку команды не засчитываются: это алгоритм, не подпись админа."
        )
    if others:
        lines.append(
            "Хэндлы из поиска почты перечислены выше. Совпадение строки в выдаче не доказывает общий аккаунт."
        )

    lines.extend(["", "## Что скрипт сознательно не утверждает", ""])
    lines.extend(
        [
            "- Смещение UTC не равно стране. Список кандидатов — часовые зоны, не геолокация человека.",
            "- При автопостинге «окно сна» может быть пустым слотом сетки.",
            "- Почта `successfrom2024@gmail.com` опубликована каналом как контакт для клипов. Других ящиков скрипт не ищет и ящик не проверяет.",
            "- Зеркало и микро-зум, запечённые в пиксели и затем растянутые YouTube до 1080×1920, по тегам файла не восстанавливаются.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def quiet_kind(schedule: dict) -> str:
    return schedule.get("quiet_kind") or ""


def run(args: argparse.Namespace) -> dict:
    selected = set(args.only) if args.only else {"schedule", "channel", "email", "media"}
    payload = {
        "generated_at": _now(),
        "csv": str(args.csv),
        "channel_url": args.channel,
        "email_query": args.email,
        "video_id": args.video,
        "schedule": {"ok": False, "errors": ["skipped"]},
        "channel": {"ok": False, "errors": ["skipped"], "handle": CHANNEL_HANDLE},
        "email": {"ok": False, "errors": ["skipped"]},
        "media": {"ok": False, "errors": ["skipped"]},
    }
    if "schedule" in selected:
        print("1/4 schedule", flush=True)
        payload["schedule"] = investigate_schedule(args.csv)
    if "channel" in selected:
        print("2/4 channel", flush=True)
        payload["channel"] = investigate_channel(args.channel)
    if "email" in selected:
        print("3/4 email", flush=True)
        own = payload["channel"].get("handle") or CHANNEL_HANDLE
        payload["email"] = investigate_email(args.email, own)
    if "media" in selected:
        print("4/4 ffprobe", flush=True)
        payload["media"] = investigate_media(args.video, args.tmp)
    return payload


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Public forensic pass on @Endlesslove025")
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    parser.add_argument("--channel", default=CHANNEL_URL)
    parser.add_argument("--email", default=EMAIL)
    parser.add_argument("--video", default=VIDEO_ID)
    parser.add_argument("--tmp", type=Path, default=TMP_DIR)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE_PATH)
    parser.add_argument(
        "--only",
        nargs="+",
        choices=("schedule", "channel", "email", "media"),
        help="run a subset; default is all four",
    )
    args = parser.parse_args()
    payload = run(args)
    args.evidence.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    report = render_report(payload)
    args.report.write_text(report, encoding="utf-8")
    print(f"wrote {args.report}", flush=True)
    print(f"wrote {args.evidence}", flush=True)


if __name__ == "__main__":
    main()
