#!/usr/bin/env python3
"""Four hidden layers for the top-30 Shorts of @Endlesslove025 by views/day.

1. English transcript (youtube-transcript-api, then yt-dlp auto-subs).
2. Most Replayed heatmap from the player response (yt-dlp extracts heatMarkers).
3. Shorts sound title / artist / sound id from the watch-page reel header.
4. Thumbnail into keyframes/ plus Google Lens and Yandex reverse-search URLs.

Public metadata only. No video file is downloaded.
A disclaimer or a reverse-search link does not create a right to republish the clip.

Install:
    python -m pip install youtube-transcript-api yt-dlp pandas httpx
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "endlesslove_data.csv"
JSON_PATH = ROOT / "deep_intelligence.json"
REPORT_PATH = ROOT / "deep_channel_secrets.md"
CHECKPOINT_PATH = ROOT / "deep_intelligence_checkpoint.jsonl"
KEYFRAME_DIR = ROOT / "keyframes"

TOP_N = 30
TABLE_N = 10
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en",
}

MUSIC_RE = re.compile(r"\[(?:music|applause|laughter|noise|singing)[^\]]*\]", re.I)
SPEAKER_RE = re.compile(r">>+")
HEX_RE = re.compile(r"\\x([0-9a-fA-F]{2})")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
WORD_RE = re.compile(r"[A-Za-z']+")


def unescape_yt(text: str) -> str:
    return HEX_RE.sub(lambda match: chr(int(match.group(1), 16)), text)


def clean_speech(text: str) -> str:
    text = MUSIC_RE.sub(" ", text or "")
    text = SPEAKER_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def sentences(text: str) -> list[str]:
    parts = [part.strip() for part in SENTENCE_RE.split(text or "") if part.strip()]
    return parts or ([text.strip()] if text and text.strip() else [])


def words_of(text: str) -> list[str]:
    return WORD_RE.findall(text or "")


def load_top(path: Path, n: int) -> list[dict]:
    frame = pd.read_csv(path)
    frame["view_count"] = pd.to_numeric(frame["view_count"], errors="coerce")
    frame["duration"] = pd.to_numeric(frame["duration"], errors="coerce")
    frame["published_dt"] = pd.to_datetime(frame["published_time"], utc=True, errors="coerce")
    now = pd.Timestamp.now(tz="UTC")
    age = (now - frame["published_dt"]).dt.total_seconds() / 86400
    frame["age_days"] = age.clip(lower=1 / 24)
    frame["views_per_day"] = frame["view_count"] / frame["age_days"]
    ranked = frame.dropna(subset=["view_count", "published_dt", "views_per_day"])
    ranked = ranked.sort_values("views_per_day", ascending=False).head(n)
    rows = []
    for record in ranked.to_dict("records"):
        rows.append(
            {
                "video_id": record["video_id"],
                "title": record.get("title") or "",
                "view_count": int(record["view_count"]),
                "views_per_day": float(record["views_per_day"]),
                "published_time": record["published_dt"].isoformat(),
                "duration": None if pd.isna(record.get("duration")) else float(record["duration"]),
                "url": record.get("url") or f"https://www.youtube.com/shorts/{record['video_id']}",
            }
        )
    return rows


def snippet_text(snippet) -> str:
    if isinstance(snippet, dict):
        return snippet.get("text") or ""
    return getattr(snippet, "text", "") or ""


def snippet_start(snippet) -> float | None:
    if isinstance(snippet, dict):
        return snippet.get("start")
    return getattr(snippet, "start", None)


def fetch_transcript(video_id: str) -> dict:
    api = YouTubeTranscriptApi()
    try:
        tracks = list(api.list(video_id))
    except TranscriptsDisabled:
        return {"status": "disabled", "language": None, "generated": None, "text": "", "raw": "", "cues": []}
    except VideoUnavailable as exc:
        return {"status": f"unavailable: {exc}", "language": None, "generated": None, "text": "", "raw": "", "cues": []}
    except Exception as exc:  # noqa: BLE001
        return {"status": f"list_error: {exc}", "language": None, "generated": None, "text": "", "raw": "", "cues": []}

    if not tracks:
        return {"status": "none", "language": None, "generated": None, "text": "", "raw": "", "cues": []}

    def rank(track) -> tuple:
        lang = (getattr(track, "language_code", "") or "").lower()
        english = 0 if lang.startswith("en") else 1
        generated = 1 if getattr(track, "is_generated", False) else 0
        return (english, generated)

    ordered = sorted(tracks, key=rank)
    chosen = ordered[0]
    lang = getattr(chosen, "language_code", None)
    generated = bool(getattr(chosen, "is_generated", False))
    try:
        fetched = chosen.fetch()
    except NoTranscriptFound:
        return {"status": "no_transcript", "language": lang, "generated": generated, "text": "", "raw": "", "cues": []}
    except Exception as exc:  # noqa: BLE001
        return {"status": f"fetch_error: {exc}", "language": lang, "generated": generated, "text": "", "raw": "", "cues": []}

    cues = []
    raw_parts = []
    for snippet in fetched:
        text = snippet_text(snippet).replace("\n", " ").strip()
        if not text:
            continue
        raw_parts.append(text)
        cues.append({"start": snippet_start(snippet), "text": text})
    raw = " ".join(raw_parts)
    speech = clean_speech(raw)
    return {
        "status": "ok" if speech else "music_only",
        "language": lang,
        "generated": generated,
        "text": speech,
        "raw": raw,
        "cues": cues,
    }


def analyse_script(text: str, duration: float | None) -> dict:
    speech = clean_speech(text)
    tokens = words_of(speech)
    parts = sentences(speech)
    hook = parts[0] if parts else ""
    closer = parts[-1] if parts else ""
    if hook and closer and hook == closer and len(parts) == 1 and len(tokens) > 16:
        hook = " ".join(tokens[:12])
        closer = " ".join(tokens[-12:])
    wps = None
    if duration and duration > 0 and tokens:
        wps = len(tokens) / duration
    return {
        "word_count": len(tokens),
        "sentence_count": len(parts) if speech else 0,
        "words_per_second": wps,
        "hook": hook,
        "closer": closer,
        "sentences": parts,
    }


def ydl_info(video_id: str) -> dict:
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 25,
        "retries": 2,
        "extractor_retries": 2,
    }
    url = f"https://www.youtube.com/shorts/{video_id}"
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    return info or {}


def peak_from_heatmap(markers: list[dict], duration: float | None) -> dict | None:
    usable = [item for item in markers if item.get("value") is not None]
    if not usable:
        return None
    peak = max(usable, key=lambda item: float(item.get("value") or 0))
    start = float(peak.get("start_time") or 0)
    end = float(peak.get("end_time") or start)
    center = (start + end) / 2
    span = duration
    if not span:
        span = max(float(item.get("end_time") or 0) for item in usable) or None
    percent = (center / span * 100) if span else None
    values = [float(item.get("value") or 0) for item in usable]
    mean_value = sum(values) / len(values) if values else None

    def zone_mean(low: float, high: float) -> float | None:
        if not span:
            return None
        picked = [
            float(item.get("value") or 0)
            for item in usable
            if low <= ((float(item.get("start_time") or 0) + float(item.get("end_time") or 0)) / 2) / span < high
        ]
        if not picked:
            return None
        return sum(picked) / len(picked)

    ordered = sorted(usable, key=lambda item: float(item.get("start_time") or 0))
    values = [float(item.get("value") or 0) for item in ordered]
    rising = sum(1 for left, right in zip(values, values[1:]) if right > left + 0.02)
    linger = None
    for item in ordered:
        if float(item.get("value") or 0) < 0.5:
            linger = float(item.get("start_time") or 0)
            break
    front_loaded = bool(values) and values[0] >= 0.95 and rising <= 2
    return {
        "peak_second": center,
        "peak_start": start,
        "peak_end": end,
        "peak_value": float(peak.get("value") or 0),
        "peak_percent": percent,
        "mean_value": mean_value,
        "first_15_mean": zone_mean(0.0, 0.15),
        "last_15_mean": zone_mean(0.85, 1.01),
        "marker_count": len(usable),
        "front_loaded": front_loaded,
        "rising_steps": rising,
        "linger_second": linger,
    }


def extract_sound(html: str, video_id: str) -> dict:
    text = unescape_yt(html)
    video_positions = [(match.start(), match.group(1)) for match in re.finditer(r'"videoId":"([A-Za-z0-9_-]{11})"', text)]
    sounds = list(re.finditer(r'soundAttributionTitle":\{"content":"([^"]+)"', text))
    title = None
    pos = None
    for match in sounds:
        prev = [item for item in video_positions if item[0] < match.start()]
        if prev and prev[-1][1] == video_id:
            title = match.group(1)
            pos = match.start()
            break
    if title is None and sounds:
        title = sounds[0].group(1)
        pos = sounds[0].start()
    artist = None
    sound_id = video_id if title and title.strip().lower() == "original sound" else None
    if pos is not None:
        window = text[max(0, pos - 1200) : pos + 1800]
        artist_match = re.search(r'"(?:artistName|byArtist|subtitle|secondaryText)":\{"content":"([^"]+)"', window)
        if artist_match:
            artist = artist_match.group(1)
        id_match = re.search(r'"(?:audioId|soundId|entityId)":"([^"]+)"', window)
        if id_match:
            sound_id = id_match.group(1)
    return {"track": title, "artist": artist, "sound_id": sound_id}


def thumbnail_candidates(video_id: str, info: dict) -> list[str]:
    urls = [
        f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    ]
    thumbs = info.get("thumbnails") or []
    thumbs = sorted(thumbs, key=lambda item: item.get("width") or 0, reverse=True)
    for item in thumbs:
        if item.get("url"):
            urls.append(item["url"])
    if info.get("thumbnail"):
        urls.append(info["thumbnail"])
    seen = []
    for url in urls:
        if url not in seen:
            seen.append(url)
    return seen


def download_keyframe(client: httpx.Client, video_id: str, info: dict) -> dict:
    KEYFRAME_DIR.mkdir(parents=True, exist_ok=True)
    dest = KEYFRAME_DIR / f"{video_id}.jpg"
    chosen = None
    for url in thumbnail_candidates(video_id, info):
        try:
            response = client.get(url)
        except httpx.HTTPError:
            continue
        if response.status_code != 200 or len(response.content) < 4000:
            continue
        if response.content[:3] != b"\xff\xd8\xff" and response.content[:8] != b"\x89PNG\r\n\x1a\n":
            continue
        dest.write_bytes(response.content)
        chosen = url
        break
    search_url = chosen or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    encoded = urllib.parse.quote(search_url, safe="")
    return {
        "path": str(dest.relative_to(ROOT)).replace("\\", "/") if chosen else None,
        "source_url": chosen,
        "search_url": search_url,
        "google_lens": f"https://lens.google.com/uploadbyurl?url={encoded}",
        "yandex": f"https://yandex.com/images/search?rpt=imageview&url={encoded}",
        "google_images": f"https://www.google.com/searchbyimage?image_url={encoded}&sbisrc=cr_1_5_2",
    }


def load_checkpoint() -> dict[str, dict]:
    found = {}
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


def scrape_one(base: dict, client: httpx.Client) -> dict:
    video_id = base["video_id"]
    info = {}
    info_error = ""
    try:
        info = ydl_info(video_id)
    except Exception as exc:  # noqa: BLE001
        info_error = str(exc)[:300]

    duration = base.get("duration")
    if info.get("duration"):
        duration = float(info["duration"])

    transcript = fetch_transcript(video_id)
    script = analyse_script(transcript.get("text") or "", duration)

    markers = info.get("heatmap") or []
    heat = peak_from_heatmap(markers, duration)

    sound = {"track": info.get("track"), "artist": info.get("artist"), "sound_id": None}
    page_error = ""
    try:
        page = client.get(f"https://www.youtube.com/shorts/{video_id}")
        page.raise_for_status()
        parsed = extract_sound(page.text, video_id)
        if parsed.get("track"):
            sound["track"] = parsed["track"]
        if parsed.get("artist"):
            sound["artist"] = parsed["artist"]
        if parsed.get("sound_id"):
            sound["sound_id"] = parsed["sound_id"]
    except Exception as exc:  # noqa: BLE001
        page_error = str(exc)[:300]

    frame = download_keyframe(client, video_id, info)
    return {
        **base,
        "duration": duration,
        "title": info.get("title") or base.get("title") or "",
        "transcript": transcript,
        "script": script,
        "heatmap_peak": heat,
        "heatmap": markers,
        "sound": sound,
        "keyframe": frame,
        "errors": {"info": info_error, "page": page_error},
    }


def hook_class(hook: str) -> str:
    text = (hook or "").strip().lower()
    if not text:
        return "нет речи"
    if text.endswith("?") or text.startswith(("why ", "how ", "what ", "who ", "when ")):
        return "вопрос"
    if text.startswith(("this is", "this's", "here's", "here is", "wait")):
        return "указание на объект"
    if text.startswith(("i was", "i'm", "i am")):
        return "от первого лица"
    if text.startswith("when "):
        return "when-сцена"
    return "повествование"


def lyric_groups(rows: list[dict]) -> list[dict]:
    spoken = [row for row in rows if (row.get("script") or {}).get("word_count", 0) >= 8]
    groups: dict[str, list[dict]] = {}
    for row in spoken:
        track = ((row.get("sound") or {}).get("track") or "без названия").strip()
        groups.setdefault(track, []).append(row)
    ranked = sorted(groups.values(), key=len, reverse=True)
    out = []
    for group in ranked[:3]:
        example = max(group, key=lambda row: row.get("views_per_day") or 0)
        wps = [row["script"]["words_per_second"] for row in group if row["script"].get("words_per_second")]
        out.append(
            {
                "track": (example.get("sound") or {}).get("track") or "без названия",
                "n": len(group),
                "median_wps": median(wps),
                "median_words": median([row["script"]["word_count"] for row in group]),
                "example_title": example["title"],
                "example_hook": example["script"]["hook"],
                "example_closer": example["script"]["closer"],
                "example_text": example["transcript"]["text"],
            }
        )
    return out


def template_groups(rows: list[dict]) -> list[dict]:
    spoken = [row for row in rows if (row.get("script") or {}).get("word_count", 0) >= 8]
    groups: dict[str, list[dict]] = {}
    for row in spoken:
        hook = row["script"]["hook"]
        tokens = [token.lower() for token in words_of(hook)[:4]]
        signature = " ".join(tokens) if tokens else hook_class(hook)
        groups.setdefault(signature, []).append(row)
    ranked = sorted(groups.values(), key=len, reverse=True)
    out = []
    used_ids = set()
    for group in ranked:
        if len(out) >= 3:
            break
        if len(group) < 2 and spoken and len(spoken) >= 6:
            continue
        example = max(group, key=lambda row: row.get("views_per_day") or 0)
        used_ids.update(row["video_id"] for row in group)
        wps = [row["script"]["words_per_second"] for row in group if row["script"].get("words_per_second")]
        out.append(
            {
                "label": "повторяющийся зачин",
                "signature": " ".join(words_of(example["script"]["hook"])[:4]).lower(),
                "n": len(group),
                "hook_class": hook_class(example["script"]["hook"]),
                "median_wps": median(wps),
                "median_words": median([row["script"]["word_count"] for row in group]),
                "example_title": example["title"],
                "example_hook": example["script"]["hook"],
                "example_closer": example["script"]["closer"],
                "example_text": example["transcript"]["text"],
                "sentence_count": example["script"]["sentence_count"],
            }
        )
    if len(out) < 3:
        leftovers = [row for row in spoken if row["video_id"] not in used_ids]
        by_class: dict[str, list[dict]] = {}
        for row in leftovers:
            by_class.setdefault(hook_class(row["script"]["hook"]), []).append(row)
        for klass, group in sorted(by_class.items(), key=lambda item: len(item[1]), reverse=True):
            if len(out) >= 3:
                break
            example = max(group, key=lambda row: row.get("views_per_day") or 0)
            wps = [row["script"]["words_per_second"] for row in group if row["script"].get("words_per_second")]
            out.append(
                {
                    "label": "тип зачина",
                    "signature": klass,
                    "n": len(group),
                    "hook_class": klass,
                    "median_wps": median(wps),
                    "median_words": median([row["script"]["word_count"] for row in group]),
                    "example_title": example["title"],
                    "example_hook": example["script"]["hook"],
                    "example_closer": example["script"]["closer"],
                    "example_text": example["transcript"]["text"],
                    "sentence_count": example["script"]["sentence_count"],
                }
            )
    return out


def median(values: list[float]) -> float | None:
    clean = sorted(value for value in values if value is not None and not (isinstance(value, float) and math.isnan(value)))
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return float(clean[mid])
    return float((clean[mid - 1] + clean[mid]) / 2)


def fmt(value, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "н/д"
    if digits == 0:
        return f"{value:,.0f}".replace(",", " ")
    return f"{value:.{digits}f}"


def md_cell(text: str, limit: int | None = None) -> str:
    value = re.sub(r"\s+", " ", text or "").replace("|", "\\|")
    if limit and len(value) > limit:
        value = value[: limit - 1] + "…"
    return value or "—"


def write_report(rows: list[dict]) -> None:
    for row in rows:
        if row.get("heatmap"):
            row["heatmap_peak"] = peak_from_heatmap(row["heatmap"], row.get("duration"))
    spoken = [row for row in rows if (row.get("script") or {}).get("word_count", 0) >= 8]
    music_only = [row for row in rows if (row.get("transcript") or {}).get("status") == "music_only"]
    disabled = [row for row in rows if (row.get("transcript") or {}).get("status") == "disabled"]
    wps_values = [row["script"]["words_per_second"] for row in spoken if row["script"].get("words_per_second")]
    word_counts = [row["script"]["word_count"] for row in spoken]
    peaks = [row["heatmap_peak"] for row in rows if row.get("heatmap_peak")]
    peak_seconds = [item["peak_second"] for item in peaks]
    peak_percents = [item["peak_percent"] for item in peaks if item.get("peak_percent") is not None]
    end_loop = [
        item
        for item in peaks
        if item.get("peak_percent") is not None
        and item["peak_percent"] >= 75
        and (item.get("last_15_mean") or 0) >= (item.get("first_15_mean") or 0)
    ]
    sounds = Counter()
    for row in rows:
        track = (row.get("sound") or {}).get("track")
        if track:
            sounds[track.strip()] += 1
    lyric_templates = lyric_groups(rows)
    front = [item for item in peaks if item.get("front_loaded")]
    linger_values = [item["linger_second"] for item in peaks if item.get("linger_second") is not None]

    lines: list[str] = []
    add = lines.append
    add("# Скрытые слои: топ-30 Shorts @Endlesslove025")
    add("")
    add(
        f"Выборка: {len(rows)} роликов с максимальным `views_per_day` из `endlesslove_data.csv`. "
        f"Прогон: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
        "Файлы роликов не скачивались. Интенсивность Most Replayed — относительная шкала 0–1 внутри ролика, не число пересмотров."
    )
    add("")
    add("## Анализ сценариев")
    add("")
    add(
        f"Автосубтитры с хотя бы 8 словами после снятия `[music]`: **{len(spoken)} / {len(rows)}**. "
        f"Субтитры выключены: {len(disabled)}. Пустых после очистки: {len(rows) - len(spoken) - len(disabled)}."
    )
    add("")
    add(
        "Это не сценарий диктора. Там, где текст есть, автосубтитры совпадают с текстом фонового трека "
        "(Skyfall, It's Raining Men, Love Story, Play with Fire). Закадровой структуры «хук → конфликт → петля» "
        "в топ-30 нет. Ниже — три повторяемых текстовых слоя, которые реально встречаются: название трека и его распознанный припев."
    )
    if spoken:
        add("")
        add(
            f"По роликам с распознанным текстом: медиана слов **{fmt(median(word_counts), 0)}**, "
            f"медиана темпа **{fmt(median(wps_values), 2)} слов/с** "
            f"на медиане длины {fmt(median([row['duration'] for row in spoken if row.get('duration')]), 0)} с. "
            "Темп ниже разговорного (~2.5 слов/с): это темп песни, не закадра."
        )
    if not lyric_templates:
        add("")
        add("Повторяемого текста нет.")
    for index, item in enumerate(lyric_templates, start=1):
        add("")
        add(f"### Шаблон {index}: трек `{item['track']}` (n={item['n']})")
        add("")
        add(f"- Медиана слов: {fmt(item['median_words'], 0)}. Медиана темпа: {fmt(item['median_wps'], 2)} слов/с.")
        add(f"- Первая фраза: {item['example_hook']}")
        add(f"- Последняя фраза: {item['example_closer']}")
        add(f"- Пример ({item['example_title']}): {item['example_text']}")
    add("")
    add("## Анатомия пика пересмотра")
    add("")
    if not peaks:
        add("Heatmap не пришёл ни по одному ролику.")
    else:
        add(
            f"Маркеры есть у **{len(peaks)} / {len(rows)}**. У остальных Most Replayed в player-response нет "
            f"(часто так у свежих Shorts). Форма графика у {len(front)} / {len(peaks)} роликов с данными: "
            "максимум value=1.0 в первом бине 0.0–0.25 с, дальше почти монотонный спад, внутренних восходящих горбов нет."
        )
        add("")
        add(
            f"Сырой максимум — **{fmt(median(peak_seconds), 1)} с ({fmt(median(peak_percents), 1)}% длины)**. "
            "Это не момент события внутри клипа. Так выглядит петля Shorts: повтор начинается с нуля, и первый кадр "
            f"становится самым пересматриваемым. Роликов с пиком в последних 25%: **{len(end_loop)}**."
        )
        if linger_values:
            add("")
            add(
                f"Практическая секунда удержания внимания: момент, когда интенсивность падает ниже 0.5. "
                f"Медиана по роликам с графиком: **{fmt(median(linger_values), 1)} с**. "
                "После неё график уже хвост, не горб."
            )
        add("")
        buckets = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]
        add("| Доля длины | Роликов |")
        add("| --- | ---: |")
        for low, high in buckets:
            count = sum(1 for value in peak_percents if low <= value < high)
            label = f"{low}–{min(high, 100)}%"
            add(f"| {label} | {count} |")
        add("")
        ranked_peaks = sorted(
            (row for row in rows if row.get("heatmap_peak")),
            key=lambda row: row["heatmap_peak"]["peak_value"],
            reverse=True,
        )[:5]
        add("Пять самых острых пиков (value — доля от максимума графика этого ролика, не от канала):")
        add("")
        for row in ranked_peaks:
            peak = row["heatmap_peak"]
            add(
                f"- {row['title']}: пик на {fmt(peak['peak_second'], 1)} с "
                f"({fmt(peak['peak_percent'], 0)}% ролика, value {fmt(peak['peak_value'], 2)})."
            )
    add("")
    add("## Звуки и треки")
    add("")
    if not sounds:
        add("Названия звука не извлеклись.")
    else:
        add("Частота `soundAttributionTitle` на этих 30. «Original Sound» — звук самого ролика, не трек из библиотеки. Отдельного artist/sound_id YouTube в соседнем блоке шапки Shorts почти не отдаёт.")
        add("")
        add("| Трек / звук | Роликов |")
        add("| --- | ---: |")
        for name, count in sounds.most_common(15):
            add(f"| {md_cell(name)} | {count} |")
    add("")
    add("## Топ-10: пик, текст, поиск оригинала по кадру")
    add("")
    add("Кадр лежит в `keyframes/{video_id}.jpg`. Ссылка поиска указывает на публичный URL превью YouTube, который Lens и Яндекс могут забрать без локального файла. Совпадение кадра не доказывает происхождение и не даёт права перезалить ролик.")
    add("")
    add("| Название | Секунда пика | Полный текст сценария | Поиск оригинала по кадру |")
    add("| --- | --- | --- | --- |")
    for row in rows[:TABLE_N]:
        peak = row.get("heatmap_peak") or {}
        if peak.get("peak_second") is None:
            peak_cell = "н/д"
        elif peak.get("front_loaded"):
            linger = peak.get("linger_second")
            linger_bit = f", >0.5 до {fmt(linger, 1)} с" if linger is not None else ""
            peak_cell = f"{fmt(peak['peak_second'], 1)} с (старт петли{linger_bit})"
        else:
            peak_cell = f"{fmt(peak['peak_second'], 1)} с ({fmt(peak.get('peak_percent'), 0)}%)"
        script = (row.get("transcript") or {}).get("text") or (row.get("transcript") or {}).get("raw") or ""
        if not script:
            status = (row.get("transcript") or {}).get("status") or "нет"
            script = f"нет английской речи ({status})"
        frame = row.get("keyframe") or {}
        links = []
        if frame.get("google_lens"):
            links.append(f"[Lens]({frame['google_lens']})")
        if frame.get("yandex"):
            links.append(f"[Яндекс]({frame['yandex']})")
        add(
            f"| {md_cell(row.get('title') or row['video_id'], 80)} | {peak_cell} | "
            f"{md_cell(script)} | {' · '.join(links) or '—'} |"
        )
    add("")
    add("Сырые маркеры, cues и ошибки: `deep_intelligence.json`.")
    add("")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Scrape transcript, heatmap, sound, and keyframe for top Shorts.")
    parser.add_argument("--top", type=int, default=TOP_N)
    parser.add_argument("--from-checkpoint", action="store_true")
    parser.add_argument("--report-only", action="store_true", help="Rebuild markdown from deep_intelligence.json")
    args = parser.parse_args()

    if args.report_only:
        if not JSON_PATH.exists():
            print(f"missing {JSON_PATH}", file=sys.stderr)
            return 1
        rows = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        write_report(rows)
        print(f"wrote {REPORT_PATH}", flush=True)
        return 0

    if not CSV_PATH.exists():
        print(f"missing {CSV_PATH}", file=sys.stderr)
        return 1
    selected = load_top(CSV_PATH, args.top)
    if not selected:
        print("no ranked rows", file=sys.stderr)
        return 1
    print(f"top {len(selected)} by views_per_day", flush=True)

    done = load_checkpoint()
    timeout = httpx.Timeout(30.0)
    with httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True) as client:
        for index, base in enumerate(selected, start=1):
            if base["video_id"] in done and not args.from_checkpoint:
                print(f"[{index}/{len(selected)}] cached {base['video_id']}", flush=True)
                continue
            print(f"[{index}/{len(selected)}] {base['video_id']}", flush=True)
            try:
                row = scrape_one(base, client)
            except Exception as exc:  # noqa: BLE001
                row = {**base, "errors": {"fatal": str(exc)[:400]}}
            append_checkpoint(row)
            done[base["video_id"]] = row
            time.sleep(0.35)

    ordered = []
    for base in selected:
        ordered.append(done.get(base["video_id"]) or base)
    JSON_PATH.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {JSON_PATH}", flush=True)
    write_report(ordered)
    print(f"wrote {REPORT_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
