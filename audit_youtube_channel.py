#!/usr/bin/env python3
"""Empirical audit of a YouTube Shorts tab. No API key.

Listing: scrapetube (newest + popular).
Exact view_count, duration, upload time, description: yt-dlp, metadata only.
Outputs: endlesslove_data.csv, channel_audit_report.md

Viral rank uses views per day, not raw views. Older videos accumulate views
without being more viral. Associations are descriptive, not causal.
A pasted disclaimer is not fair use and does not block Content ID.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import scrapetube
import yt_dlp

CHANNEL_URL = "https://www.youtube.com/@Endlesslove025/shorts"
CHANNEL_HANDLE = "Endlesslove025"
ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "endlesslove_data.csv"
REPORT_PATH = ROOT / "channel_audit_report.md"
CHECKPOINT_PATH = ROOT / "endlesslove_checkpoint.jsonl"

TARGET_N = 280
LISTING_EACH = 220
MIN_BIN_N = 12
TOP_FRAC = 0.05

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at",
    "by", "from", "is", "are", "was", "were", "be", "this", "that", "it", "its",
    "you", "your", "i", "we", "they", "he", "she", "his", "her", "them", "my",
    "me", "our", "as", "if", "but", "not", "no", "so", "just", "than", "then",
    "into", "out", "up", "about", "what", "when", "how", "who", "why", "which",
    "will", "can", "do", "did", "does", "has", "have", "had", "been", "being",
    "shorts", "short", "youtube", "video", "watch", "new", "amp",
}

TRIGGER_LEXICON = {
    "emotional": (
        "love", "cry", "crying", "tears", "heart", "sad", "happy", "miss",
        "forever", "soul", "pain", "hurt", "broken", "precious", "sweet",
        "emotional", "feel", "feeling", "beautiful", "joy", "grief",
    ),
    "curiosity": (
        "why", "how", "what", "secret", "wait", "watch", "unexpected",
        "nobody", "never", "always", "reveal", "truth", "before", "after",
        "then", "suddenly", "guess", "look", "see",
    ),
    "animals": (
        "cat", "cats", "kitten", "dog", "dogs", "puppy", "puppies", "bird",
        "birds", "duck", "ducks", "owl", "fox", "foxes", "rabbit", "bunny",
        "animal", "animals", "pet", "pets", "horse", "cow", "pig", "goat",
        "deer", "bear", "lion", "tiger", "wolf", "hamster", "parrot",
    ),
    "empathy": (
        "help", "saved", "save", "rescue", "rescued", "abandoned", "alone",
        "lonely", "poor", "kind", "kindness", "care", "caring", "adopt",
        "adoption", "shelter", "homeless", "injured", "safe", "protect",
        "mom", "dad", "baby", "mother", "father", "friend",
    ),
}

DURATION_BINS = (
    (0, 15, "0–15 с"),
    (15, 21, "15–21 с"),
    (21, 31, "21–31 с"),
    (31, 45, "31–45 с"),
    (45, 61, "45–60 с"),
    (61, 91, "61–90 с"),
    (91, 181, "91–180 с"),
)

DISCLAIMER_RE = re.compile(
    r"fair use|copyright|disclaimer|all rights|dmca|no copyright|"
    r"educational|credit|owner|infringement|contact|email|"
    r"creative commons|permission|intended for",
    re.I,
)
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\uFE0F"
    "\u200D"
    "]+",
    flags=re.UNICODE,
)
WORD_RE = re.compile(r"[A-Za-z']+|[0-9]+(?:[.,][0-9]+)?")
HASHTAG_RE = re.compile(r"#([\w]{2,40})", re.UNICODE)


def _text(node) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if "simpleText" in node:
            return str(node["simpleText"])
        if "runs" in node:
            return "".join(str(part.get("text", "")) for part in node["runs"] if isinstance(part, dict))
        access = node.get("accessibility") or node.get("accessibilityData")
        if isinstance(access, dict):
            if "label" in access:
                return str(access["label"])
            return _text(access.get("accessibilityData"))
    return ""


def parse_count(value) -> int | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).replace(",", "").replace("\xa0", " ").strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*([KMB])?", text, re.I)
    if not match:
        return None
    factor = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[match.group(2).upper() if match.group(2) else ""]
    return int(float(match.group(1)) * factor)


def parse_duration_text(value: str) -> int | None:
    text = (value or "").strip()
    if not text or not re.fullmatch(r"\d{1,2}(?::\d{2}){1,2}", text):
        return None
    parts = [int(part) for part in text.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def listing_title(item: dict) -> str:
    title = _text(item.get("title")) or _text(item.get("headline"))
    if title:
        return title.strip()
    overlay = item.get("title") or item.get("headline")
    label = _text(overlay)
    return label.split(",")[0].strip() if label else ""


def listing_views(item: dict) -> int | None:
    for key in ("viewCountText", "shortViewCountText", "viewCount"):
        parsed = parse_count(_text(item.get(key)) or item.get(key))
        if parsed is not None:
            return parsed
    label = _text(item.get("title")) + " " + _text(item.get("accessibility"))
    match = re.search(r"([\d.,]+)\s*([KMB])?\s+views", label, re.I)
    if match:
        return parse_count(match.group(0))
    return None


def listing_published(item: dict) -> str:
    return _text(item.get("publishedTimeText")).strip()


def listing_duration(item: dict) -> int | None:
    for key in ("lengthText", "thumbnailOverlays"):
        raw = item.get(key)
        if isinstance(raw, list):
            for overlay in raw:
                parsed = parse_duration_text(_text(overlay))
                if parsed is not None:
                    return parsed
        else:
            parsed = parse_duration_text(_text(raw))
            if parsed is not None:
                return parsed
    label = _text(item.get("accessibility")) or _text(item.get("title"))
    match = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)", label)
    return parse_duration_text(match.group(1)) if match else None


def collect_listing(sort_by: str, limit: int) -> list[dict]:
    rows = []
    generator = scrapetube.get_channel(
        channel_url=CHANNEL_URL,
        limit=limit,
        sleep=0.4,
        sort_by=sort_by,
        content_type="shorts",
    )
    for item in generator:
        video_id = item.get("videoId")
        if not video_id:
            continue
        rows.append(
            {
                "video_id": video_id,
                "title_listing": listing_title(item),
                "view_count_listing": listing_views(item),
                "published_text": listing_published(item),
                "duration_listing": listing_duration(item),
                "list_source": sort_by,
            }
        )
    return rows


def collect_flat(limit: int) -> list[dict]:
    """Shorts grid via yt-dlp. scrapetube shorts payloads are videoId-only,
    and the popular chip on this tab raises inside scrapetube."""
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "playlistend": limit,
        "ignoreerrors": True,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
    rows = []
    for index, entry in enumerate(info.get("entries") or []):
        if not entry or not entry.get("id"):
            continue
        rows.append(
            {
                "video_id": entry["id"],
                "title_listing": entry.get("title") or "",
                "view_count_listing": entry.get("view_count"),
                "published_text": "",
                "duration_listing": None,
                "list_source": "newest",
                "newest_rank": index,
            }
        )
    return rows


def fetch_channel_description() -> str:
    options = {"quiet": True, "no_warnings": True, "skip_download": True, "playlist_items": "0"}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/@{CHANNEL_HANDLE}", download=False)
    return (info or {}).get("description") or ""


def collect_ids(limit_each: int) -> list[dict]:
    print(f"flat-listing shorts via yt-dlp, limit={max(limit_each * 3, 600)}", flush=True)
    flat = collect_flat(max(limit_each * 3, 600))
    print(f"flat listed {len(flat)}", flush=True)

    scrapetube_ids: set[str] = set()
    try:
        print(f"scrapetube newest cross-check, limit={limit_each}", flush=True)
        listed = collect_listing("newest", limit_each)
        if not listed:
            scrapetube.scrapetube.type_property_map["shorts"] = "reelWatchEndpoint"
            listed = collect_listing("newest", limit_each)
        scrapetube_ids = {row["video_id"] for row in listed}
        print(f"scrapetube newest ids={len(scrapetube_ids)}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"scrapetube newest failed: {exc}", flush=True)

    popular_ids: set[str] = set()
    try:
        print(f"scrapetube popular, limit={limit_each}", flush=True)
        popular_ids = {row["video_id"] for row in collect_listing("popular", limit_each)}
        print(f"scrapetube popular ids={len(popular_ids)}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"scrapetube popular chip unavailable: {exc}", flush=True)

    if not flat and scrapetube_ids:
        return [{"video_id": video_id, "title_listing": "", "view_count_listing": None,
                 "published_text": "", "duration_listing": None, "list_source": "newest",
                 "newest_rank": index} for index, video_id in enumerate(scrapetube_ids)]

    by_id = {row["video_id"]: row for row in flat}
    newest_cut = flat[: min(180, len(flat))]
    if popular_ids:
        popular_rows = [by_id[video_id] for video_id in popular_ids if video_id in by_id]
        missing = [video_id for video_id in popular_ids if video_id not in by_id]
        for video_id in missing:
            popular_rows.append(
                {
                    "video_id": video_id,
                    "title_listing": "",
                    "view_count_listing": None,
                    "published_text": "",
                    "duration_listing": None,
                    "list_source": "popular",
                    "newest_rank": 10**9,
                }
            )
    else:
        popular_rows = sorted(flat, key=lambda row: row.get("view_count_listing") or 0, reverse=True)[:160]

    selected: dict[str, dict] = {}
    for row in newest_cut:
        selected[row["video_id"]] = dict(row)
        selected[row["video_id"]]["list_source"] = "newest"
    for row in popular_rows:
        current = selected.get(row["video_id"])
        if current is None:
            selected[row["video_id"]] = dict(row)
            selected[row["video_id"]]["list_source"] = "popular"
        else:
            current["list_source"] = "both"
    for video_id in scrapetube_ids:
        if video_id not in selected and len(selected) < TARGET_N + 20:
            selected[video_id] = {
                "video_id": video_id,
                "title_listing": by_id.get(video_id, {}).get("title_listing", ""),
                "view_count_listing": by_id.get(video_id, {}).get("view_count_listing"),
                "published_text": "",
                "duration_listing": None,
                "list_source": "newest",
                "newest_rank": by_id.get(video_id, {}).get("newest_rank", 10**9),
            }

    ordered = sorted(
        selected.values(),
        key=lambda row: (0 if row["list_source"] == "both" else 1 if row["list_source"] == "newest" else 2, row.get("newest_rank", 10**9)),
    )
    return ordered[:300]


def load_checkpoint() -> dict[str, dict]:
    found: dict[str, dict] = {}
    if not CHECKPOINT_PATH.exists():
        return found
    with CHECKPOINT_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("video_id"):
                found[row["video_id"]] = row
    return found


def append_checkpoint(row: dict) -> None:
    with CHECKPOINT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def fetch_one(video_id: str) -> dict:
    url = f"https://www.youtube.com/shorts/{video_id}"
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": False,
        "noplaylist": True,
        "socket_timeout": 25,
        "retries": 2,
        "extractor_retries": 2,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise RuntimeError("empty info")
    timestamp = info.get("timestamp") or info.get("release_timestamp")
    published = None
    if timestamp:
        published = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()
    elif info.get("upload_date"):
        published = datetime.strptime(info["upload_date"], "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
    return {
        "video_id": video_id,
        "title": info.get("title") or "",
        "view_count": info.get("view_count"),
        "published_time": published,
        "duration": info.get("duration"),
        "description": info.get("description") or "",
        "like_count": info.get("like_count"),
        "comment_count": info.get("comment_count"),
        "enrich_error": "",
    }


def enrich(listings: list[dict], workers: int) -> list[dict]:
    done = load_checkpoint()
    pending = [row for row in listings if row["video_id"] not in done]
    print(f"enrich {len(pending)} shorts, checkpoint={len(done)}, workers={workers}", flush=True)
    if pending:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_one, row["video_id"]): row for row in pending}
            finished = 0
            for future in as_completed(futures):
                listing = futures[future]
                finished += 1
                try:
                    payload = future.result()
                except Exception as exc:  # noqa: BLE001 — one blocked video must not abort the sample
                    payload = {
                        "video_id": listing["video_id"],
                        "title": listing.get("title_listing") or "",
                        "view_count": listing.get("view_count_listing"),
                        "published_time": None,
                        "duration": listing.get("duration_listing"),
                        "description": "",
                        "like_count": None,
                        "comment_count": None,
                        "enrich_error": str(exc)[:300],
                    }
                payload["list_source"] = listing.get("list_source")
                payload["published_text"] = listing.get("published_text") or ""
                append_checkpoint(payload)
                if finished % 15 == 0 or finished == len(pending):
                    print(f"enriched {finished}/{len(pending)}", flush=True)
                time.sleep(0.05)
        done = load_checkpoint()

    rows = []
    for listing in listings:
        payload = done.get(listing["video_id"], {})
        title = payload.get("title") or listing.get("title_listing") or ""
        views = payload.get("view_count")
        if views is None:
            views = listing.get("view_count_listing")
        duration = payload.get("duration")
        if duration is None:
            duration = listing.get("duration_listing")
        rows.append(
            {
                "video_id": listing["video_id"],
                "title": title,
                "view_count": views,
                "published_time": payload.get("published_time"),
                "duration": duration,
                "description": payload.get("description") or "",
                "like_count": payload.get("like_count"),
                "list_source": listing.get("list_source"),
                "published_text": listing.get("published_text") or payload.get("published_text") or "",
                "enrich_error": payload.get("enrich_error") or "",
                "url": f"https://www.youtube.com/shorts/{listing['video_id']}",
            }
        )
    return rows


def words(text: str) -> list[str]:
    return [token.lower() for token in WORD_RE.findall(text or "") if token.lower() not in STOPWORDS and len(token) > 2]


def emoji_count(text: str) -> int:
    return len(EMOJI_RE.findall(text or ""))


def caps_share(text: str) -> float:
    letters = [ch for ch in text or "" if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(ch.isupper() for ch in letters) / len(letters)


def median(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None and not (isinstance(value, float) and math.isnan(value))]
    if not clean:
        return None
    return float(statistics.median(clean))


def mean(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None and not (isinstance(value, float) and math.isnan(value))]
    if not clean:
        return None
    return float(statistics.fmean(clean))


def quantile(values: list[float], q: float) -> float | None:
    clean = sorted(value for value in values if value is not None and not (isinstance(value, float) and math.isnan(value)))
    if not clean:
        return None
    if len(clean) == 1:
        return float(clean[0])
    pos = (len(clean) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(clean[lo])
    return float(clean[lo] * (hi - pos) + clean[hi] * (pos - lo))


def fmt_num(value, digits: int = 0) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "н/д"
    if digits == 0:
        return f"{value:,.0f}".replace(",", " ")
    return f"{value:,.{digits}f}".replace(",", " ")


def fmt_sec(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "н/д"
    return f"{value:.0f} с" if float(value).is_integer() else f"{value:.1f} с"


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data["view_count"] = pd.to_numeric(data["view_count"], errors="coerce")
    data["duration"] = pd.to_numeric(data["duration"], errors="coerce")
    data["published_dt"] = pd.to_datetime(data["published_time"], utc=True, errors="coerce")
    now = pd.Timestamp.now(tz="UTC")
    age_days = (now - data["published_dt"]).dt.total_seconds() / 86400
    data["age_days"] = age_days.clip(lower=1 / 24)
    data["views_per_day"] = data["view_count"] / data["age_days"]
    data["title"] = data["title"].fillna("")
    data["description"] = data["description"].fillna("")
    data["title_words"] = data["title"].map(lambda text: len(WORD_RE.findall(text)))
    data["title_chars"] = data["title"].map(len)
    data["emoji_n"] = data["title"].map(emoji_count)
    data["has_emoji"] = data["emoji_n"] > 0
    data["has_question"] = data["title"].str.contains(r"\?", regex=True)
    data["caps_share"] = data["title"].map(caps_share)
    data["has_caps_word"] = data["title"].map(
        lambda text: any(token.isupper() and len(token) >= 3 for token in re.findall(r"[A-Za-z]+", text))
    )
    data["is_short"] = data["duration"].isna() | (data["duration"] <= 180)
    return data[data["is_short"]].reset_index(drop=True)


def duration_table(data: pd.DataFrame) -> list[dict]:
    rows = []
    for low, high, label in DURATION_BINS:
        subset = data[(data["duration"] >= low) & (data["duration"] < high)]
        if subset.empty:
            continue
        rows.append(
            {
                "label": label,
                "n": int(len(subset)),
                "median_views": median(subset["view_count"].tolist()),
                "median_vpd": median(subset["views_per_day"].dropna().tolist()),
            }
        )
    return rows


def best_duration_window(data: pd.DataFrame, width: int = 8, min_n: int = MIN_BIN_N) -> dict | None:
    known = data.dropna(subset=["duration", "views_per_day"])
    if len(known) < min_n:
        return None
    durations = sorted(set(int(value) for value in known["duration"]))
    best = None
    for start in durations:
        end = start + width
        subset = known[(known["duration"] >= start) & (known["duration"] < end)]
        if len(subset) < min_n:
            continue
        score = median(subset["views_per_day"].tolist())
        if best is None or score > best["median_vpd"]:
            best = {
                "start": start,
                "end": end,
                "n": int(len(subset)),
                "median_vpd": score,
                "median_views": median(subset["view_count"].tolist()),
                "median_duration": median(subset["duration"].tolist()),
            }
    return best


def posting_cadence(data: pd.DataFrame) -> dict:
    dated = data.dropna(subset=["published_dt"]).sort_values("published_dt")
    if dated.empty:
        return {"n": 0}
    days = dated["published_dt"].dt.floor("D")
    per_day = days.value_counts()
    span_days = max((dated["published_dt"].max() - dated["published_dt"].min()).total_seconds() / 86400, 1)
    weeks = dated["published_dt"].dt.tz_convert("UTC").dt.strftime("%G-W%V")
    per_week = weeks.value_counts()
    gaps = dated["published_dt"].diff().dt.total_seconds().dropna() / 3600
    return {
        "n": int(len(dated)),
        "first": dated["published_dt"].min().isoformat(),
        "last": dated["published_dt"].max().isoformat(),
        "span_days": span_days,
        "per_day_mean": len(dated) / span_days,
        "per_active_day_median": median(per_day.tolist()),
        "per_active_day_p90": quantile(per_day.tolist(), 0.9),
        "active_days": int(per_day.shape[0]),
        "per_week_median": median(per_week.tolist()),
        "per_week_mean": mean(per_week.tolist()),
        "gap_hours_median": median(gaps.tolist()) if len(gaps) else None,
    }


def token_lift(data: pd.DataFrame, top_mask: pd.Series, k: int = 20) -> list[dict]:
    def bag(mask: pd.Series) -> Counter:
        counts: Counter = Counter()
        for title in data.loc[mask, "title"]:
            counts.update(set(words(title)))
        return counts

    top_n = int(top_mask.sum())
    rest_n = int((~top_mask).sum())
    if top_n == 0 or rest_n == 0:
        return []
    top_counts = bag(top_mask)
    rest_counts = bag(~top_mask)
    scored = []
    for token, top_hits in top_counts.items():
        rest_hits = rest_counts.get(token, 0)
        p_top = (top_hits + 0.5) / (top_n + 1)
        p_rest = (rest_hits + 0.5) / (rest_n + 1)
        scored.append(
            {
                "token": token,
                "top_share": top_hits / top_n,
                "rest_share": rest_hits / rest_n,
                "lift": p_top / p_rest,
                "top_hits": top_hits,
            }
        )
    scored = [row for row in scored if row["top_hits"] >= 2 and not row["token"].replace(",", "").replace(".", "").isdigit()]
    scored.sort(key=lambda row: (row["lift"], row["top_hits"]), reverse=True)
    return scored[:k]


def title_templates(data: pd.DataFrame, k: int = 5) -> list[dict]:
    def signature(title: str) -> str:
        tokens = []
        for raw in WORD_RE.findall(title or ""):
            token = raw.lower()
            if token.isdigit() or re.fullmatch(r"\d+(?:[.,]\d+)?", token):
                tokens.append("#")
            elif token in STOPWORDS:
                continue
            else:
                tokens.append(token)
        if not tokens:
            return ""
        return " ".join(tokens[:6])

    known = data.dropna(subset=["views_per_day"]).copy()
    known["sig"] = known["title"].map(signature)
    groups = []
    for sig, subset in known.groupby("sig"):
        if not sig or len(subset) < 3:
            continue
        groups.append(
            {
                "formula": sig,
                "n": int(len(subset)),
                "median_vpd": median(subset["views_per_day"].tolist()),
                "median_views": median(subset["view_count"].tolist()),
                "median_duration": median(subset["duration"].dropna().tolist()),
                "examples": subset.nlargest(2, "views_per_day")["title"].tolist(),
            }
        )
    groups.sort(key=lambda row: (row["median_vpd"] or 0, row["n"]), reverse=True)
    return groups[:k]


def structural_patterns(data: pd.DataFrame) -> list[dict]:
    known = data.dropna(subset=["views_per_day"])
    base = median(known["views_per_day"].tolist()) or 0
    specs = (
        ("вопрос в заголовке", known["has_question"]),
        ("эмодзи в заголовке", known["has_emoji"]),
        ("слово КАПСОМ (≥3 буквы)", known["has_caps_word"]),
        ("число в заголовке", known["title"].str.contains(r"\d", regex=True)),
        ("хештег в заголовке", known["title"].str.contains(r"#\w", regex=True)),
        ("заголовок ≤ 4 слов", known["title_words"] <= 4),
        ("заголовок ≥ 8 слов", known["title_words"] >= 8),
    )
    rows = []
    for label, mask in specs:
        hit = known[mask.fillna(False)]
        miss = known[~mask.fillna(False)]
        if len(hit) < 8 or len(miss) < 8:
            continue
        hit_med = median(hit["views_per_day"].tolist())
        miss_med = median(miss["views_per_day"].tolist())
        rows.append(
            {
                "label": label,
                "n": int(len(hit)),
                "share": len(hit) / len(known),
                "median_vpd": hit_med,
                "lift_vs_rest": (hit_med / miss_med) if hit_med and miss_med else None,
                "lift_vs_all": (hit_med / base) if hit_med and base else None,
            }
        )
    rows.sort(key=lambda row: row["median_vpd"] or 0, reverse=True)
    return rows


def lexicon_rates(data: pd.DataFrame) -> list[dict]:
    rows = []
    titles = data["title"].fillna("").tolist()
    n = len(titles) or 1
    for name, vocab in TRIGGER_LEXICON.items():
        pattern = re.compile(r"\b(" + "|".join(re.escape(word) for word in vocab) + r")\b", re.I)
        hits = sum(1 for title in titles if pattern.search(title))
        rows.append({"name": name, "n": hits, "share": hits / n})
    return rows


def frequent_tokens(data: pd.DataFrame, k: int = 20) -> list[tuple[str, int]]:
    counts: Counter = Counter()
    for title in data["title"]:
        counts.update(words(title))
    return counts.most_common(k)


def hashtag_counts(data: pd.DataFrame, k: int = 15) -> list[tuple[str, int]]:
    counts: Counter = Counter()
    blob = (data["title"].fillna("") + "\n" + data["description"].fillna("")).tolist()
    for text in blob:
        counts.update(tag.lower() for tag in HASHTAG_RE.findall(text))
    return counts.most_common(k)


def disclaimer_block(data: pd.DataFrame) -> dict:
    descriptions = [text.strip() for text in data["description"].tolist() if text and text.strip()]
    if not descriptions:
        return {"n": 0, "lines": [], "emails": [], "mode": ""}
    line_counts: Counter = Counter()
    emails: Counter = Counter()
    for text in descriptions:
        seen = set()
        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if len(line) < 12 or line in seen:
                continue
            seen.add(line)
            line_counts[line] += 1
        emails.update(EMAIL_RE.findall(text))
    threshold = max(3, int(0.35 * len(descriptions)))
    common = [(line, count) for line, count in line_counts.most_common(30) if count >= threshold]
    legalish = [
        (line, count)
        for line, count in line_counts.most_common(40)
        if DISCLAIMER_RE.search(line) or EMAIL_RE.search(line)
    ]
    mode = Counter(descriptions).most_common(1)[0]
    return {
        "n": len(descriptions),
        "share": len(descriptions) / max(len(data), 1),
        "lines": common,
        "legalish": legalish[:12],
        "emails": emails.most_common(5),
        "mode_text": mode[0],
        "mode_n": mode[1],
    }


def compare_outliers(data: pd.DataFrame) -> dict:
    known = data.dropna(subset=["views_per_day"]).copy()
    if len(known) < 20:
        return {"n": int(len(known))}
    cutoff = known["views_per_day"].quantile(1 - TOP_FRAC)
    top = known[known["views_per_day"] >= cutoff]
    rest = known[known["views_per_day"] < cutoff]

    def pack(subset: pd.DataFrame) -> dict:
        return {
            "n": int(len(subset)),
            "median_views": median(subset["view_count"].tolist()),
            "median_vpd": median(subset["views_per_day"].tolist()),
            "median_duration": median(subset["duration"].dropna().tolist()),
            "mean_duration": mean(subset["duration"].dropna().tolist()),
            "p25_duration": quantile(subset["duration"].dropna().tolist(), 0.25),
            "p75_duration": quantile(subset["duration"].dropna().tolist(), 0.75),
            "median_title_words": median(subset["title_words"].tolist()),
            "median_title_chars": median(subset["title_chars"].tolist()),
            "emoji_share": float(subset["has_emoji"].mean()) if len(subset) else None,
            "question_share": float(subset["has_question"].mean()) if len(subset) else None,
            "caps_share": float(subset["has_caps_word"].mean()) if len(subset) else None,
            "median_age_days": median(subset["age_days"].tolist()),
        }

    return {
        "n": int(len(known)),
        "cutoff_vpd": float(cutoff),
        "top": pack(top),
        "rest": pack(rest),
        "lift_tokens": token_lift(known, known["views_per_day"] >= cutoff),
        "top_titles": top.nlargest(8, "views_per_day")[
            ["title", "view_count", "views_per_day", "duration", "published_time", "url"]
        ].to_dict("records"),
    }


def ascii_bars(rows: list[dict], key: str) -> list[str]:
    scores = [row.get(key) or 0 for row in rows]
    peak = max(scores) if scores else 0
    lines = []
    for row in rows:
        score = row.get(key) or 0
        width = 0 if peak <= 0 else int(round(24 * score / peak))
        lines.append(f"{row['label']:<10} n={row['n']:<4} {'█' * width} {fmt_num(score)} /день")
    return lines


def write_report(data: pd.DataFrame, raw_n: int, enrich_errors: int, channel_description: str) -> None:
    known_views = data.dropna(subset=["view_count"])
    known_dur = data.dropna(subset=["duration"])
    recent = data[data["list_source"].isin(["newest", "both"])] if "list_source" in data.columns else data
    cadence = posting_cadence(recent if len(recent) >= 30 else data)
    bins = duration_table(data.dropna(subset=["duration", "views_per_day"]))
    window = best_duration_window(data, min_n=max(MIN_BIN_N, 40))
    thin_window = best_duration_window(data, min_n=MIN_BIN_N)
    outliers = compare_outliers(data)
    templates = title_templates(data)
    patterns = structural_patterns(data)
    tokens = frequent_tokens(data)
    tags = hashtag_counts(data)
    lexicon = lexicon_rates(data)
    disclaimer = disclaimer_block(data)

    dur_med = median(known_dur["duration"].tolist())
    dur_mean = mean(known_dur["duration"].tolist())
    dur_p25 = quantile(known_dur["duration"].tolist(), 0.25)
    dur_p75 = quantile(known_dur["duration"].tolist(), 0.75)
    view_med = median(known_views["view_count"].tolist())
    view_mean = mean(known_views["view_count"].tolist())
    vpd_med = median(data["views_per_day"].dropna().tolist())

    usable_bins = [row for row in bins if row["n"] >= MIN_BIN_N and row["median_vpd"] is not None]
    best_bin = max(usable_bins, key=lambda row: row["median_vpd"]) if usable_bins else None

    top = outliers.get("top") or {}
    rest = outliers.get("rest") or {}

    lines: list[str] = []
    add = lines.append
    add("# Аудит Shorts: @Endlesslove025")
    add("")
    add(f"Источник: `{CHANNEL_URL}`. Канал Endless Love, около 11.7 млн подписчиков на момент сбора. Дата прогона: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.")
    add("")
    add("Сбор без API-ключа. `scrapetube` на вкладке Shorts отдаёт только `videoId`; чип popular на этой вкладке падает (нет `feedFilterChipBarRenderer`). Заголовки и приблизительные просмотры сетки взяты плоским плейлистом `yt-dlp` по последним 600–800 Shorts. В выборку вошли 180 самых новых и самые просматриваемые из этого окна, без дублей, потолок 300. Точные `view_count`, `duration`, `published_time` и описание ролика — полный extract `yt-dlp`, файл не скачивается. «Популярные» здесь — верх по просмотрам в окне, не отдельный чип YouTube.")
    add("")
    add("Виральность ниже — это `views / age_days`, не сырые просмотры. Сырой топ смещён к старым роликам. Все сравнения описательные: канал сам выбирает, что выкладывать, так что разница топ-5% и массы не есть причинность заголовка или секунд.")
    add("")
    add("## Общая сводка")
    add("")
    add(f"- В выборке после фильтра ≤180 с: **{len(data)}** роликов (собрано листингом {raw_n}, ошибки обогащения с откатом на листинг: {enrich_errors}).")
    add(f"- С точной датой: {int(data['published_dt'].notna().sum())}. С длительностью: {int(data['duration'].notna().sum())}. С текстом описания: {int((data['description'].str.strip() != '').sum())}.")
    add(f"- Медиана просмотров: **{fmt_num(view_med)}**. Среднее: {fmt_num(view_mean)}. Медиана просмотров/день: **{fmt_num(vpd_med)}**.")
    add(f"- Хронометраж: медиана **{fmt_sec(dur_med)}**, среднее {fmt_sec(dur_mean)}, IQR {fmt_sec(dur_p25)} – {fmt_sec(dur_p75)}.")
    if cadence.get("n"):
        add(
            f"- Окно публикаций: {cadence['first'][:10]} — {cadence['last'][:10]} "
            f"({cadence['span_days']:.0f} суток, {cadence['n']} роликов с датой)."
        )
        add(
            f"- Частота считается только по свежему срезу (newest/both, n={cadence['n']}), "
            f"без подмешанных старых хитов, иначе паузы раздуваются. "
            f"**{cadence['per_day_mean']:.2f} ролика в сутки** по окну (включая дни без постов). "
            f"В дни, когда постит: медиана {fmt_num(cadence['per_active_day_median'])} "
            f"ролика, p90 {fmt_num(cadence['per_active_day_p90'])}. "
            f"Активных дней: {cadence['active_days']}."
        )
        add(
            f"- По неделям: медиана {fmt_num(cadence['per_week_median'])}, среднее {fmt_num(cadence['per_week_mean'], 1)}. "
            f"Медианная пауза между роликами: {fmt_num(cadence['gap_hours_median'], 1)} ч."
        )
    else:
        add("- Частоту выкладки посчитать нельзя: у роликов нет точной даты публикации.")
    add("")
    add("## Золотой стандарт хронометража")
    add("")
    add("Это диапазон, где в этой выборке медиана просмотров/день максимальна при достаточном n. Это не порог YouTube и не гарантия следующего ролика.")
    add("")
    if window:
        add(
            f"- Устойчивое окно 8 секунд (n≥40, максимальная медиана views/day): "
            f"**{window['start']}–{window['end']} с** (медиана длины {fmt_sec(window['median_duration'])}, "
            f"n={window['n']}, медиана просмотров {fmt_num(window['median_views'])}, "
            f"медиана/день {fmt_num(window['median_vpd'])})."
        )
    if thin_window and (window is None or (thin_window["start"], thin_window["end"]) != (window["start"], window["end"])):
        add(
            f"- Более узкий пик при n≥{MIN_BIN_N}: {thin_window['start']}–{thin_window['end']} с "
            f"(n={thin_window['n']}, медиана/день {fmt_num(thin_window['median_vpd'])}). "
            f"n слишком мало, чтобы объявлять это стандартом."
        )
    if best_bin:
        add(
            f"- Грубый бин с тем же критерием: **{best_bin['label']}** "
            f"(n={best_bin['n']}, медиана просмотров {fmt_num(best_bin['median_views'])}, "
            f"медиана/день {fmt_num(best_bin['median_vpd'])})."
        )
    if top and rest:
        add(
            f"- Топ-5% по views/day: медиана длины {fmt_sec(top.get('median_duration'))} "
            f"(IQR {fmt_sec(top.get('p25_duration'))}–{fmt_sec(top.get('p75_duration'))}). "
            f"Остальные: медиана {fmt_sec(rest.get('median_duration'))}."
        )
    if bins:
        add("")
        add("Медиана views/day по бинам:")
        add("")
        add("```")
        lines.extend(ascii_bars(bins, "median_vpd"))
        add("```")
    add("")
    add("## Аномалии: топ-5% против остальной массы")
    add("")
    if not top:
        add("Мало роликов с views/day, сравнение не строилось.")
    else:
        add(f"Порог топ-5%: {fmt_num(outliers.get('cutoff_vpd'))} просмотров/день. n топа = {top['n']}, n остатка = {rest['n']}.")
        add("")
        add("| | Топ-5% | Остальные |")
        add("| --- | ---: | ---: |")
        add(f"| Медиана просмотров | {fmt_num(top['median_views'])} | {fmt_num(rest['median_views'])} |")
        add(f"| Медиана просмотров/день | {fmt_num(top['median_vpd'])} | {fmt_num(rest['median_vpd'])} |")
        add(f"| Медиана длины | {fmt_sec(top['median_duration'])} | {fmt_sec(rest['median_duration'])} |")
        add(f"| Медиана слов в заголовке | {fmt_num(top['median_title_words'], 1)} | {fmt_num(rest['median_title_words'], 1)} |")
        add(f"| Медиана символов заголовка | {fmt_num(top['median_title_chars'])} | {fmt_num(rest['median_title_chars'])} |")
        add(f"| Доля с эмодзи | {top['emoji_share']:.0%} | {rest['emoji_share']:.0%} |")
        add(f"| Доля с вопросом | {top['question_share']:.0%} | {rest['question_share']:.0%} |")
        add(f"| Доля со словом КАПСОМ | {top['caps_share']:.0%} | {rest['caps_share']:.0%} |")
        add(f"| Медиана возраста, дни | {fmt_num(top['median_age_days'], 1)} | {fmt_num(rest['median_age_days'], 1)} |")
        add("")
        add("Слова, которые чаще встречаются в заголовках топа, чем в остатке (lift). Это не «секретные триггеры», а относительная частота при маленьком n топа.")
        add("")
        if outliers.get("lift_tokens"):
            add("| Слово | Доля в топе | Доля в остатке | Lift |")
            add("| --- | ---: | ---: | ---: |")
            for row in outliers["lift_tokens"][:12]:
                add(
                    f"| {row['token']} | {row['top_share']:.0%} | {row['rest_share']:.0%} | {row['lift']:.2f} |"
                )
        add("")
        add("Самые быстрые по views/day:")
        add("")
        for row in outliers.get("top_titles") or []:
            add(
                f"- {row['title']} — {fmt_num(row['view_count'])} просмотров, "
                f"{fmt_num(row['views_per_day'])}/день, {fmt_sec(row.get('duration'))}. {row['url']}"
            )
    add("")
    add("## Заголовки")
    add("")
    add(
        f"- Среднее слов: **{fmt_num(mean(data['title_words'].tolist()), 1)}**, "
        f"медиана {fmt_num(median(data['title_words'].tolist()), 1)}."
    )
    add(
        f"- Среднее символов: **{fmt_num(mean(data['title_chars'].tolist()), 1)}**, "
        f"медиана {fmt_num(median(data['title_chars'].tolist()))}."
    )
    add(
        f"- Доля с эмодзи: **{data['has_emoji'].mean():.0%}**. "
        f"С вопросом: **{data['has_question'].mean():.0%}**. "
        f"Со словом КАПСОМ: **{data['has_caps_word'].mean():.0%}**. "
        f"Средняя доля заглавных букв: {data['caps_share'].mean():.0%}."
    )
    add("")
    add("Топ-20 слов в заголовках (без стоп-слов):")
    add("")
    if tokens:
        add(", ".join(f"{token} ({count})" for token, count in tokens) + ".")
    else:
        add("Токенов нет.")
    add("")
    add("Словари триггеров (фиксированные английские лексемы, доля заголовков с хотя бы одним попаданием):")
    add("")
    for row in lexicon:
        add(f"- {row['name']}: {row['n']} / {len(data)} ({row['share']:.0%})")
    add("")
    if tags:
        add("Хештеги в заголовке и описании:")
        add("")
        add(", ".join(f"#{tag} ({count})" for tag, count in tags) + ".")
        add("")
    add("### Топ-5 формул заголовков")
    add("")
    add("Формула = первые содержательные токены заголовка, числа схлопнуты в `#`. В список входят только шаблоны с n≥3, сортировка по медиане views/day.")
    add("")
    if not templates:
        add("Повторяющихся шаблонов с n≥3 нет. Ниже — структурные признаки вместо формул.")
    for index, row in enumerate(templates, start=1):
        examples = " | ".join(row["examples"][:2])
        add(
            f"{index}. `{row['formula']}` — n={row['n']}, медиана/день {fmt_num(row['median_vpd'])}, "
            f"медиана просмотров {fmt_num(row['median_views'])}, медиана длины {fmt_sec(row['median_duration'])}. "
            f"Примеры: {examples}"
        )
    if patterns:
        add("")
        add("Структурные признаки, ранжированные по медиане views/day:")
        add("")
        add("| Признак | n | Доля | Медиана/день | Lift к остальным |")
        add("| --- | ---: | ---: | ---: | ---: |")
        for row in patterns:
            lift = "н/д" if row["lift_vs_rest"] is None else f"{row['lift_vs_rest']:.2f}"
            add(f"| {row['label']} | {row['n']} | {row['share']:.0%} | {fmt_num(row['median_vpd'])} | {lift} |")
    add("")
    add("## Юридический щит")
    add("")
    add("Это текст, который канал реально вставляет в описание. Дисклеймер не создаёт fair use и не останавливает Content ID или страйк. Копировать его как защиту бессмысленно.")
    add("")
    if channel_description.strip():
        add("Текст вкладки About канала (стабильный шаблон, не обязательно совпадает с описанием каждого Short):")
        add("")
        add("```")
        add(channel_description.strip()[:4000])
        add("```")
        add("")
    if disclaimer["n"] == 0:
        add("Описания самих Shorts в выборке пустые. Пороликового дисклеймера нет: текст живёт в About канала.")
    else:
        add(f"Непустых описаний: {disclaimer['n']} ({disclaimer['share']:.0%} выборки). Точный повтор одного и того же текста: {disclaimer['mode_n']} роликов.")
        if disclaimer["emails"]:
            add("")
            add("Email в описаниях: " + ", ".join(f"{email} ({count})" for email, count in disclaimer["emails"]) + ".")
        if disclaimer["legalish"]:
            add("")
            add("Строки с маркерами disclaimer / copyright / contact:")
            add("")
            for line, count in disclaimer["legalish"]:
                add(f"- ({count}) {line}")
        if disclaimer["lines"]:
            add("")
            add("Строки, которые повторяются минимум в 35% непустых описаний:")
            add("")
            for line, count in disclaimer["lines"]:
                add(f"- ({count}) {line}")
        add("")
        add("Самый частый полный текст описания:")
        add("")
        add("```")
        add(disclaimer["mode_text"][:4000])
        add("```")
    add("")
    add("## Пошаговый рецепт для конвейера")
    add("")
    add("Рецепт повторяет наблюдаемое распределение этого канала. Он не переносится на другую нишу как формула виральности.")
    add("")
    step = 1
    if window:
        add(f"{step}. Держать хронометраж в окне **{window['start']}–{window['end']} с**, если цель — попасть в бин с максимальной медианой views/day на этой выборке. Вне окна бин либо реже, либо медленнее.")
        step += 1
    elif best_bin:
        add(f"{step}. Держать хронометраж в бине **{best_bin['label']}** — там максимальная медиана views/day при n≥{MIN_BIN_N}.")
        step += 1
    if cadence.get("n"):
        add(
            f"{step}. Частота этого канала: около {cadence['per_day_mean']:.2f} ролика в сутки по окну, "
            f"медиана {fmt_num(cadence['per_week_median'])} в неделю, пауза {fmt_num(cadence['gap_hours_median'], 1)} ч. "
            f"Конвейер, который постит на порядок реже, не повторяет их режим набора выборки."
        )
        step += 1
    add(
        f"{step}. Заголовок под их медиану: около {fmt_num(median(data['title_words'].tolist()), 1)} слов "
        f"и {fmt_num(median(data['title_chars'].tolist()))} символов. "
        f"Эмодзи сейчас у {data['has_emoji'].mean():.0%} заголовков, вопрос у {data['has_question'].mean():.0%}, "
        f"капслок-слово у {data['has_caps_word'].mean():.0%}. Копировать признак имеет смысл только если его lift в таблице выше ≥1.2 и n≥8."
    )
    step += 1
    if tokens:
        head = ", ".join(token for token, _count in tokens[:8])
        add(f"{step}. Темы в частотном хвосте заголовков: {head}. Это темы канала, не универсальные хуки.")
        step += 1
    if templates:
        add(f"{step}. Для теста заголовков брать шаблоны из раздела «Топ-5 формул» как A/B-гипотезы, не как обязательный текст. Менять один слот, не весь шаблон сразу, иначе не отделить тему от формы.")
        step += 1
    add(
        f"{step}. Описание: если у себя нет юридической причины для того же текста, не вставлять их дисклеймер «для защиты от страйков». "
        f"Он не является щитом. Имеет смысл повторить только фактические поля, которые у них стабильны (email, кредит источника), и то как контакт, не как оборону."
    )
    step += 1
    add(
        f"{step}. Не оптимизировать сырые просмотры. В своей аналитике считать views/age_days и минуты на показ в разрезе Suggested/Browse отдельно: "
        f"сырой топ этого канала тоже смещён возрастом (медиана возраста топа {fmt_num(top.get('median_age_days'), 1)} дней против {fmt_num(rest.get('median_age_days'), 1)} у остальных)."
        if top
        else f"{step}. Не оптимизировать сырые просмотры. Считать views/age_days."
    )
    add("")
    add("Сырые строки: `endlesslove_data.csv`. Промежуточные ответы yt-dlp: `endlesslove_checkpoint.jsonl`.")
    add("")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT_PATH}", flush=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Audit Endlesslove025 Shorts without an API key.")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit-each", type=int, default=LISTING_EACH)
    parser.add_argument("--skip-enrich", action="store_true")
    parser.add_argument("--from-csv", action="store_true", help="Rebuild the report from endlesslove_data.csv")
    args = parser.parse_args()

    if args.from_csv:
        if not CSV_PATH.exists():
            print(f"missing {CSV_PATH}", file=sys.stderr)
            return 1
        frame = pd.read_csv(CSV_PATH)
        if "enrich_error" not in frame.columns:
            frame["enrich_error"] = ""
        prepared = prepare(frame)
        channel_description = ""
        try:
            channel_description = fetch_channel_description()
        except Exception as exc:  # noqa: BLE001
            print(f"channel about failed: {exc}", flush=True)
        errors = int(pd.to_numeric(frame["duration"], errors="coerce").isna().sum())
        write_report(prepared, raw_n=len(frame), enrich_errors=errors, channel_description=channel_description)
        return 0

    listings = collect_ids(args.limit_each)
    if not listings:
        print("no shorts listed", file=sys.stderr)
        return 1
    if args.skip_enrich:
        rows = [
            {
                "video_id": row["video_id"],
                "title": row.get("title_listing") or "",
                "view_count": row.get("view_count_listing"),
                "published_time": None,
                "duration": row.get("duration_listing"),
                "description": "",
                "like_count": None,
                "list_source": row.get("list_source"),
                "published_text": row.get("published_text") or "",
                "enrich_error": "skipped",
                "url": f"https://www.youtube.com/shorts/{row['video_id']}",
            }
            for row in listings
        ]
    else:
        rows = enrich(listings, workers=max(1, args.workers))

    frame = pd.DataFrame(rows)
    export = frame[
        ["video_id", "title", "view_count", "published_time", "duration", "description", "like_count", "list_source", "url"]
    ].rename(columns={"duration": "duration"})
    export.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
    print(f"wrote {CSV_PATH} rows={len(export)}", flush=True)

    prepared = prepare(frame)
    errors = int((frame["enrich_error"].fillna("") != "").sum())
    channel_description = ""
    try:
        channel_description = fetch_channel_description()
    except Exception as exc:  # noqa: BLE001
        print(f"channel about failed: {exc}", flush=True)
    write_report(prepared, raw_n=len(frame), enrich_errors=errors, channel_description=channel_description)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
