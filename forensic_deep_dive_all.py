#!/usr/bin/env python3
"""Public-data deep dive on @Endlesslove025. No login, no Studio, no bypass.

1. Content ID / monetization fields that the anonymous player actually returns.
2. Outbound URLs in descriptions and pinned comments, redirects, UTM.
3. Wayback CDX chronology and a rebrand test against the same channel ID.
4. Public mentions of the business email already printed on the channel.

The anonymous player does not contain the creator's payout ledger. Absence of
`monetizationDetails` is a finding, not a reason to invent a claim.

Install:
    python -m pip install yt-dlp httpx
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import subprocess
import sys
import time
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "endlesslove_data.csv"
REPORT_PATH = ROOT / "final_hacker_dossier.md"
EVIDENCE_PATH = ROOT / "forensic_deep_evidence.json"
CHECKPOINT_PATH = ROOT / "forensic_deep_checkpoint.jsonl"

CHANNEL_ID = "UCH8x9zAJbpfipmHosNuwu_A"
CHANNEL_HANDLE = "Endlesslove025"
CHANNEL_URL = "https://www.youtube.com/@Endlesslove025"
EMAIL = "successfrom2024@gmail.com"
SUSPECT_HANDLES = ("Asiandramavibes", "Asiandramavibes-u7c")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

PLAYER_KEYS = (
    "adSafetyReason",
    "monetizationDetails",
    "musicMetadata",
    "musicTrack",
    "soundAttributionTitle",
    "licensedContent",
    "contentId",
    "claimId",
    "rightsManagementPolicy",
)

ORIGINAL_SOUND = ("original sound", "original audio", "оригинальный звук", "оригинальное аудио")
LIBRARY_HINTS = (
    "youtube audio library",
    "shorts audio library",
    "audio library",
    "royalty free",
    "royalty-free",
)
DISCLAIMER_RE = re.compile(r"fair use|copyright|disclaimer|credits to the original|all rights", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
BARE_RE = re.compile(
    r"\b((?:t\.me|bit\.ly|tinyurl\.com|cutt\.ly|linktr\.ee|rebrand\.ly|is\.gd|"
    r"taplink\.cc|surl\.li|clck\.ru)/[^\s<>\"')\]]+)",
    re.I,
)
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
PUB_RE = re.compile(r"(?:ca-)?pub-\d{10,20}", re.I)
UTM_KEYS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "ref",
    "subid",
    "sub1",
    "sub2",
    "affiliate_id",
    "aff_id",
    "click_id",
    "offer_id",
)
SHORTENERS = (
    "bit.ly",
    "tinyurl.com",
    "cutt.ly",
    "t.co",
    "rebrand.ly",
    "is.gd",
    "goo.gl",
    "surl.li",
    "clck.ru",
    "lnkd.in",
    "ow.ly",
)
FUNNEL_HOSTS = (
    (("admitad", "clickbank", "shareasale", "awin", "impact.com", "cj.com", "hotmart", "digistore", "hasoffers", "affise"), "cpa"),
    (("play.google.com", "apps.apple.com", "onelink.me", "app.adjust.com"), "app"),
    (("gumroad.com", "stan.store", "beacons.ai", "skool.com", "teachable.com", "whop.com", "kajabi"), "infoproduct"),
    (("t.me", "telegram.", "linktr.ee", "taplink", "instagram.com", "tiktok.com", "discord.gg"), "social_hub"),
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def log(message: str) -> None:
    print(message, flush=True)


def clip(value, limit: int = 400) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def text_of(node) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float)):
        return str(node)
    if isinstance(node, dict):
        if isinstance(node.get("simpleText"), str):
            return node["simpleText"]
        if isinstance(node.get("content"), str):
            return node["content"]
        if isinstance(node.get("runs"), list):
            return "".join(text_of(part) for part in node["runs"])
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
    for pos in range(start, min(len(html), start + 8_000_000)):
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
                try:
                    return json.loads(html[start : pos + 1])
                except json.JSONDecodeError:
                    return None
    return None


def html_unescape(text: str) -> str:
    return (
        text.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#x27;", "'")
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("\\u0026", "&")
        .replace("\\/", "/")
    )


def walk_keys(node, wanted: set[str], hits: list, path: str = "$", depth: int = 0) -> None:
    if depth > 14 or len(hits) >= 30:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if key in wanted:
                hits.append({"path": f"{path}.{key}", "key": key, "value": clip(value, 500)})
            walk_keys(value, wanted, hits, f"{path}.{key}", depth + 1)
    elif isinstance(node, list):
        for index, value in enumerate(node[:40]):
            walk_keys(value, wanted, hits, f"{path}[{index}]", depth + 1)


def scan_key_strings(blob: str) -> list[dict]:
    hits = []
    if not blob:
        return hits
    text = html_unescape(blob)
    for key in PLAYER_KEYS:
        for match in re.finditer(rf'"{key}"\s*:\s*"([^"]{{0,240}})"', text):
            hits.append({"path": "html", "key": key, "value": match.group(1)})
            if len(hits) >= 30:
                return hits
        if re.search(rf'"{key}"\s*:\s*\{{', text) and not any(item["key"] == key for item in hits):
            hits.append({"path": "html", "key": key, "value": "object present, string value not inline"})
    return hits


class Net:
    def __init__(self) -> None:
        import httpx

        self.httpx = httpx
        self.client = httpx.Client(headers=HEADERS, follow_redirects=True, timeout=35)

    def close(self) -> None:
        self.client.close()

    def get(self, url: str, *, follow: bool = True, timeout: float = 35, attempts: int = 3) -> tuple[int, str, str]:
        last = "no attempt"
        for attempt in range(attempts):
            try:
                response = self.client.get(url, follow_redirects=follow, timeout=timeout)
                return response.status_code, response.text, str(response.url)
            except self.httpx.HTTPError as exc:
                last = str(exc)
                time.sleep(1.2 * (attempt + 1))
        return 0, "", last

    def post_json(self, url: str, payload: dict, timeout: float = 35) -> tuple[int, dict | str]:
        last = "no attempt"
        for attempt in range(3):
            try:
                response = self.client.post(url, json=payload, timeout=timeout)
                try:
                    return response.status_code, response.json()
                except json.JSONDecodeError:
                    return response.status_code, response.text[:400]
            except self.httpx.HTTPError as exc:
                last = str(exc)
                time.sleep(1.2 * (attempt + 1))
        return 0, last

    def get_limited(self, url: str, limit: int = 1_500_000, timeout: float = 40) -> tuple[int, str, str]:
        last = "no attempt"
        for attempt in range(2):
            try:
                with self.client.stream("GET", url, timeout=timeout) as response:
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        chunks.append(chunk)
                        total += len(chunk)
                        if total >= limit:
                            break
                    body = b"".join(chunks).decode("utf-8", errors="replace")
                    return response.status_code, body, str(response.url)
            except self.httpx.HTTPError as exc:
                last = str(exc)
                time.sleep(1.2 * (attempt + 1))
        return 0, "", last


def load_rows(path: Path) -> tuple[list[dict], list[str]]:
    import csv

    notes = []
    if not path.is_file():
        raise FileNotFoundError(str(path))
    by_id: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            video_id = (raw.get("video_id") or "").strip()
            if not video_id:
                continue
            try:
                views = int(float(raw.get("view_count") or 0))
            except ValueError:
                views = 0
            row = {
                "video_id": video_id,
                "title": raw.get("title") or "",
                "view_count": views,
                "published_time": raw.get("published_time") or raw.get("upload_date") or "",
                "description": raw.get("description") or "",
                "url": raw.get("url") or f"https://www.youtube.com/shorts/{video_id}",
            }
            previous = by_id.get(video_id)
            if previous is None or views > previous["view_count"] or len(row["description"]) > len(previous["description"]):
                if previous and previous["description"] and not row["description"]:
                    row["description"] = previous["description"]
                by_id[video_id] = row
    rows = sorted(by_id.values(), key=lambda item: item["view_count"], reverse=True)
    notes.append(f"unique_videos={len(rows)}")
    return rows, notes


def load_checkpoint() -> dict[str, dict]:
    found = {}
    if not CHECKPOINT_PATH.is_file():
        return found
    for line in CHECKPOINT_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("video_id") and row.get("kind"):
            found[f"{row['kind']}:{row['video_id']}"] = row
    return found


def append_checkpoint(row: dict) -> None:
    with CHECKPOINT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def ydl_info(video_id: str) -> dict:
    import yt_dlp

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": 25,
        "retries": 2,
        "extractor_retries": 1,
        "ignoreerrors": False,
    }
    url = f"https://www.youtube.com/shorts/{video_id}"
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    keep = (
        "id",
        "title",
        "channel",
        "channel_id",
        "license",
        "availability",
        "track",
        "artist",
        "album",
        "release_year",
        "categories",
        "duration",
        "view_count",
        "description",
    )
    return {key: info.get(key) for key in keep}


def extract_sound(html: str, video_id: str) -> dict:
    text = html_unescape(html)
    positions = [(match.start(), match.group(1)) for match in re.finditer(r'"videoId":"([A-Za-z0-9_-]{11})"', text)]
    sounds = list(re.finditer(r'soundAttributionTitle":\{"content":"([^"]+)"', text))
    title = None
    pos = None
    for match in sounds:
        prev = [item for item in positions if item[0] < match.start()]
        if prev and prev[-1][1] == video_id:
            title = match.group(1)
            pos = match.start()
            break
    if title is None and sounds:
        title = sounds[0].group(1)
        pos = sounds[0].start()
    artist = None
    if pos is not None:
        window = text[max(0, pos - 1500) : pos + 1800]
        artist_match = re.search(
            r'"(?:artistName|byArtist|subtitle|secondaryText)":\{"content":"([^"]+)"',
            window,
        )
        if artist_match:
            artist = artist_match.group(1)
    return {"track": title, "artist": artist}


def classify_audio(track: str | None, artist: str | None, blob: str) -> str:
    joined = " ".join(part for part in (track, artist, blob) if part).lower()
    if any(hint in joined for hint in LIBRARY_HINTS):
        return "library_hint"
    if track and track.strip().lower() in ORIGINAL_SOUND:
        return "original_sound"
    if track and track.strip():
        return "attributed_track"
    return "unknown"


def inner_tube_player(net: Net, video_id: str, api_key: str, client_version: str) -> tuple[dict | None, str]:
    if not api_key:
        return None, "no innertube key"
    url = f"https://www.youtube.com/youtubei/v1/player?key={api_key}&prettyPrint=false"
    payload = {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": client_version or "2.20250101.00.00",
                "hl": "en",
                "gl": "US",
            }
        },
        "videoId": video_id,
        "contentCheckOk": True,
        "racyCheckOk": True,
    }
    status, body = net.post_json(url, payload)
    if isinstance(body, dict):
        return body, f"http {status}"
    return None, f"http {status}: {clip(body, 160)}"


def page_client_config(html: str) -> tuple[str, str]:
    version = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', html or "")
    key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', html or "")
    return (key.group(1) if key else ""), (version.group(1) if version else "")


def vector_content(net: Net, rows: list[dict], top_n: int, checkpoint: dict) -> dict:
    result = {"name": "content_id", "ok": False, "errors": [], "videos": []}
    sample = rows[:top_n]
    if not sample:
        result["errors"].append("no rows")
        return result
    api_key = ""
    client_version = ""
    status, html, _final = net.get(CHANNEL_URL, timeout=30)
    if status == 200:
        api_key, client_version = page_client_config(html)
    else:
        result["errors"].append(f"channel page for innertube key: {status or 'network'}")

    for index, row in enumerate(sample, 1):
        video_id = row["video_id"]
        log(f"1/4 content {index}/{len(sample)} {video_id}")
        key = f"content:{video_id}"
        if key in checkpoint:
            result["videos"].append(checkpoint[key]["payload"])
            continue
        item = {
            "video_id": video_id,
            "title": row["title"],
            "views": row["view_count"],
            "url": row["url"],
            "errors": [],
            "ydl": {},
            "sound": {},
            "player_hits": [],
            "audio_class": "unknown",
            "ledger_present": False,
        }
        try:
            item["ydl"] = ydl_info(video_id)
        except Exception as exc:  # noqa: BLE001
            item["errors"].append(f"yt-dlp: {clip(exc, 220)}")
        page = ""
        try:
            status, page, _final = net.get(f"https://www.youtube.com/shorts/{video_id}", timeout=30)
            if status != 200:
                item["errors"].append(f"shorts page HTTP {status}")
            else:
                item["sound"] = extract_sound(page, video_id)
                player = extract_brace_object(page, "ytInitialPlayerResponse") or {}
                hits = []
                walk_keys(player, set(PLAYER_KEYS), hits)
                hits.extend(scan_key_strings(page))
                item["player_hits"].extend(hits)
        except Exception as exc:  # noqa: BLE001
            item["errors"].append(f"page: {clip(exc, 220)}")
        try:
            player, note = inner_tube_player(net, video_id, api_key, client_version)
            item["innertube_note"] = note
            if player:
                hits = []
                walk_keys(player, set(PLAYER_KEYS), hits)
                item["player_hits"].extend(hits)
                playability = (player.get("playabilityStatus") or {}).get("status")
                item["playability"] = playability
        except Exception as exc:  # noqa: BLE001
            item["errors"].append(f"innertube: {clip(exc, 220)}")

        track = item["sound"].get("track") or item["ydl"].get("track")
        artist = item["sound"].get("artist") or item["ydl"].get("artist")
        item["track"] = track
        item["artist"] = artist
        item["license"] = item["ydl"].get("license")
        blob = " ".join(hit.get("value") or "" for hit in item["player_hits"])
        item["audio_class"] = classify_audio(track, artist, blob)
        keys_found = {hit["key"] for hit in item["player_hits"]}
        item["keys_found"] = sorted(keys_found)
        item["ledger_present"] = "monetizationDetails" in keys_found or "claimId" in keys_found
        item["ad_safety_present"] = "adSafetyReason" in keys_found
        result["videos"].append(item)
        append_checkpoint({"kind": "content", "video_id": video_id, "payload": item})
        time.sleep(0.35)

    classes = Counter(item["audio_class"] for item in result["videos"])
    ledger = sum(1 for item in result["videos"] if item["ledger_present"])
    result["class_counts"] = dict(classes)
    result["ledger_present_n"] = ledger
    result["ok"] = bool(result["videos"])
    if ledger == 0:
        result["verdict"] = (
            "Публичный player response не содержит monetizationDetails / claimId. "
            "Кто получает выплату — админ, музыкант или никто — из этого слоя не видно. "
            "Объявления, которые плеер показывает зрителю, выплатой автору не являются."
        )
    else:
        result["verdict"] = (
            f"В {ledger} из {len(result['videos'])} ответов есть поле претензии или монетизации. "
            "Смотреть сырые значения в таблице, не обобщать на весь канал."
        )
    attributed = classes.get("attributed_track", 0) + classes.get("library_hint", 0)
    original = classes.get("original_sound", 0)
    if attributed and not original:
        result["audio_verdict"] = (
            "На этих роликах в шапке Shorts стоит названный трек. Это атрибуция звука, "
            "не документ Content ID. Доля дохода со звуком может уходить правообладателю или библиотеке — публичный ответ этого не подтверждает и не опровергает."
        )
    elif original and not attributed:
        result["audio_verdict"] = (
            "В шапке стоит Original Sound. Библиотечный трек с делением дохода в видимом блоке не подписан. "
            "Это не доказательство, что Content ID на картинку или на чужой звук отсутствует: Studio-клейм в анонимный плеер не попадает."
        )
    elif attributed and original:
        result["audio_verdict"] = (
            "Смесь Original Sound и названных треков. Названный трек — атрибуция, не приговор по выплате. "
            "Original Sound не доказывает, что клейма нет."
        )
    else:
        result["audio_verdict"] = "Шапка звука почти пустая. Статус лицензии по этим роликам не установлен."
    return result


def clean_url(raw: str) -> str:
    text = html_unescape(raw).strip().rstrip(".,;:)>\"'")
    if text.lower().startswith(("http://", "https://")):
        return text
    return "https://" + text.lstrip("/")


def extract_urls(text: str) -> list[str]:
    found = []
    seen = set()
    blob = text or ""
    for match in list(URL_RE.finditer(blob)) + list(BARE_RE.finditer(blob)):
        url = clean_url(match.group(0) if match.re is URL_RE else match.group(1))
        key = url.lower().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        found.append(url)
    return found


def host_of(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def is_public_http(url: str) -> tuple[bool, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False, "scheme"
    host = parsed.hostname or ""
    if not host or host in {"localhost"} or host.endswith(".local"):
        return False, "local host"
    literal = host.strip("[]")
    try:
        ip = ipaddress.ip_address(literal)
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        except socket.gaierror as exc:
            return False, f"dns: {exc}"
        ips = []
        for info in infos:
            addr = info[4][0]
            try:
                ips.append(ipaddress.ip_address(addr))
            except ValueError:
                continue
        if not ips:
            return False, "no resolved ip"
        if any(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast for ip in ips):
            return False, "private ip"
        return True, ""
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        return False, "private ip"
    return True, ""


def utm_of(url: str) -> dict[str, str]:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    found = {}
    for key in UTM_KEYS:
        if key in query and query[key]:
            found[key] = query[key][0]
    return found


def funnel_of(url: str) -> str:
    host = host_of(url)
    blob = host + urllib.parse.urlparse(url).path.lower()
    if any(host == item or host.endswith("." + item) for item in SHORTENERS):
        return "shortener_unresolved"
    for needles, label in FUNNEL_HOSTS:
        if any(needle in blob for needle in needles):
            return label
    if host in {"youtube.com", "youtu.be", "m.youtube.com"}:
        return "youtube"
    return "other" if host else "empty"


def resolve_url(net: Net, url: str) -> dict:
    hops = []
    current = url
    error = ""
    for _ in range(8):
        allowed, why = is_public_http(current)
        if not allowed:
            error = why
            break
        try:
            response = net.client.request("HEAD", current, follow_redirects=False, timeout=16)
            if response.status_code in {405, 501} or response.status_code >= 400 and response.status_code not in {301, 302, 303, 307, 308}:
                response = net.client.request("GET", current, follow_redirects=False, timeout=20)
        except net.httpx.HTTPError as exc:
            error = clip(exc, 180)
            break
        hops.append({"url": str(response.url), "status": response.status_code})
        location = response.headers.get("location")
        if response.status_code in {301, 302, 303, 307, 308} and location:
            current = urllib.parse.urljoin(str(response.url), location)
            continue
        current = str(response.url)
        break
    return {
        "start": url,
        "final": current,
        "host": host_of(current),
        "hops": hops,
        "utm": utm_of(current),
        "funnel": funnel_of(current),
        "error": error,
    }


def fetch_comments(video_id: str) -> dict:
    code = r"""
import json, sys
import yt_dlp
video_id = sys.argv[1]
opts = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "getcomments": True,
    "socket_timeout": 25,
    "retries": 1,
    "extractor_retries": 1,
    "extractor_args": {"youtube": {"max_comments": ["25"], "comment_sort": ["top"]}},
}
url = "https://www.youtube.com/watch?v=" + video_id
try:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False) or {}
except Exception as exc:
    print(json.dumps({"error": str(exc)[:300], "comments": []}))
    raise SystemExit(0)
rows = []
for item in (info.get("comments") or [])[:25]:
    if not isinstance(item, dict):
        continue
    rows.append({
        "text": (item.get("text") or "")[:500],
        "author": item.get("author") or "",
        "author_id": item.get("author_id") or "",
        "is_pinned": bool(item.get("is_pinned")),
        "author_is_uploader": bool(item.get("author_is_uploader")),
        "like_count": item.get("like_count"),
    })
print(json.dumps({"error": "", "comments": rows}))
"""
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code, video_id],
            capture_output=True,
            text=True,
            timeout=110,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"error": "timeout 110s", "comments": []}
    except OSError as exc:
        return {"error": str(exc), "comments": []}
    blob = (completed.stdout or "").strip().splitlines()
    if not blob:
        err = (completed.stderr or "").strip().splitlines()
        return {"error": clip(err[-1] if err else f"exit {completed.returncode}", 220), "comments": []}
    try:
        return json.loads(blob[-1])
    except json.JSONDecodeError:
        return {"error": "comment worker returned non-json", "comments": []}


def vector_links(net: Net, rows: list[dict], top_comments: int, checkpoint: dict) -> dict:
    result = {"name": "links", "ok": False, "errors": [], "from_descriptions": [], "from_comments": [], "resolved": []}
    by_source: dict[str, dict] = {}

    def add(url: str, source: str, video_id: str, title: str) -> None:
        key = url.lower().rstrip("/")
        slot = by_source.setdefault(
            key,
            {"url": url, "sources": [], "video_ids": [], "funnel_guess": funnel_of(url)},
        )
        if source not in slot["sources"]:
            slot["sources"].append(source)
        if video_id not in slot["video_ids"]:
            slot["video_ids"].append(video_id)
        slot["example_title"] = title

    descriptions_with_text = 0
    disclaimer_n = 0
    emails = Counter()
    for row in rows:
        text = row.get("description") or ""
        if text.strip():
            descriptions_with_text += 1
        if DISCLAIMER_RE.search(text):
            disclaimer_n += 1
        for email in EMAIL_RE.findall(text):
            emails[email.lower()] += 1
        for url in extract_urls(text):
            add(url, "description", row["video_id"], row["title"])
    result["descriptions_with_text"] = descriptions_with_text
    result["disclaimer_n"] = disclaimer_n
    result["emails_in_descriptions"] = emails.most_common(12)
    result["rows"] = len(rows)

    sample = rows[:top_comments]
    for index, row in enumerate(sample, 1):
        video_id = row["video_id"]
        log(f"2/4 comments {index}/{len(sample)} {video_id}")
        cached = checkpoint.get(f"comments:{video_id}")
        if cached:
            payload = cached["payload"]
        else:
            payload = fetch_comments(video_id)
            append_checkpoint({"kind": "comments", "video_id": video_id, "payload": payload})
            time.sleep(0.3)
        if payload.get("error"):
            result["errors"].append(f"{video_id}: {payload['error']}")
        comments = payload.get("comments") or []
        pinned = [item for item in comments if item.get("is_pinned") or item.get("author_is_uploader")]
        result["from_comments"].append(
            {
                "video_id": video_id,
                "title": row["title"],
                "views": row["view_count"],
                "comment_n": len(comments),
                "pinned_n": len(pinned),
                "pinned": pinned[:4],
            }
        )
        for item in pinned or comments[:3]:
            for url in extract_urls(item.get("text") or ""):
                add(url, "pinned_or_top_comment", video_id, row["title"])

    result["from_descriptions"] = list(by_source.values())
    external = [
        item
        for item in by_source.values()
        if funnel_of(item["url"]) != "youtube"
    ]
    for item in external[:25]:
        log(f"2/4 resolve {item['url']}")
        try:
            resolved = resolve_url(net, item["url"])
        except Exception as exc:  # noqa: BLE001
            resolved = {"start": item["url"], "error": clip(exc, 180), "hops": [], "utm": {}, "funnel": "error"}
        resolved["sources"] = item["sources"]
        resolved["video_ids"] = item["video_ids"][:8]
        result["resolved"].append(resolved)

    funnels = Counter(item.get("funnel") or "empty" for item in result["resolved"])
    result["funnel_counts"] = dict(funnels)
    offplatform = [item for item in result["resolved"] if item.get("funnel") not in {"youtube", "empty", "error", "shortener_unresolved"}]
    if not external:
        result["verdict"] = (
            "Внешних ссылок в описаниях выборки и в закреплённых/авторских комментариях топа нет. "
            "CPA-сеть, приложение, инфопродукт и link-in-bio по этим текстам не видны. Воронка — сам YouTube, либо ссылки стоят там, куда публичный текст не достаёт."
        )
    elif offplatform:
        result["verdict"] = (
            f"Есть {len(offplatform)} размотанных внешних посадок. Смотреть таблицу хостов и UTM. "
            "Это карта ссылок, не доказательство, что оффер ещё платит."
        )
    else:
        result["verdict"] = (
            "Ссылки нашлись, но после редиректа остались YouTube, неразмотанный сокращатель или ошибка. "
            "Арбитражный оффер по финальному домену не установлен."
        )
    result["ok"] = True
    return result


def cdx_fetch(net: Net, url_pattern: str) -> tuple[list[dict], str]:
    query = urllib.parse.urlencode(
        {
            "url": url_pattern,
            "output": "json",
            "fl": "timestamp,original,statuscode,mimetype",
            "filter": "statuscode:200",
            "collapse": "digest",
            "limit": "180",
        }
    )
    status, body, note = net.get(f"https://web.archive.org/cdx/search/cdx?{query}", timeout=50, attempts=2)
    if status != 200:
        return [], f"HTTP {status or note}"
    try:
        rows = json.loads(body)
    except json.JSONDecodeError:
        return [], "cdx not json"
    parsed = []
    for row in rows[1:]:
        if not isinstance(row, list) or len(row) < 3:
            continue
        stamp = str(row[0])
        parsed.append(
            {
                "timestamp": stamp,
                "date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}" if len(stamp) >= 8 else stamp,
                "original": row[1],
                "status": row[2],
                "mimetype": row[3] if len(row) > 3 else "",
            }
        )
    return parsed, "ok"


def snapshot_extract(html: str) -> dict:
    title_match = re.search(r"<title>(.*?)</title>", html or "", flags=re.I | re.S)
    title = html_unescape(re.sub(r"\s+", " ", title_match.group(1))).strip() if title_match else ""
    title = re.sub(r"\s+-\s+YouTube$", "", title).strip()
    subs = ""
    sub_match = re.search(
        r"(\d[\d.,]*\s*[KMB]?\s+subscribers|\d[\d\s.,]*\s+подписчик\w*)",
        html or "",
        flags=re.I,
    )
    if sub_match:
        subs = re.sub(r"\s+", " ", sub_match.group(1)).strip()
    avatar = ""
    og = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html or "", flags=re.I)
    if og:
        avatar = html_unescape(og.group(1))
    if not avatar:
        yt = re.search(r"https://yt3\.(?:ggpht|googleusercontent)\.com/[^\"'\s]+", html or "")
        if yt:
            avatar = yt.group(0)
    mentions = []
    lowered = (html or "").lower()
    for needle in ("asiandramavibes", "asian drama vibes", "endless love", "endlesslove025"):
        if needle in lowered:
            mentions.append(needle)
    return {"title": title[:180], "subscribers": subs, "avatar": avatar[:400], "mentions": mentions, "bytes": len(html or "")}


def channel_id_from_html(html: str) -> str:
    for pattern in (r'"externalId":"(UC[\w-]{22})"', r'"channelId":"(UC[\w-]{22})"', r'"browseId":"(UC[\w-]{22})"'):
        match = re.search(pattern, html or "")
        if match:
            return match.group(1)
    return ""


def vector_wayback(net: Net) -> dict:
    result = {"name": "wayback", "ok": False, "errors": [], "feeds": {}, "samples": [], "handle_ids": {}}
    patterns = {
        "channel_id": f"youtube.com/channel/{CHANNEL_ID}*",
        "handle": "youtube.com/@Endlesslove025*",
        "suspect": "youtube.com/@Asiandramavibes*",
        "suspect_u7c": "youtube.com/@Asiandramavibes-u7c*",
    }
    all_rows: list[dict] = []
    for name, pattern in patterns.items():
        log(f"3/4 wayback {name}")
        try:
            rows, note = cdx_fetch(net, pattern)
        except Exception as exc:  # noqa: BLE001
            rows, note = [], clip(exc, 180)
        if note != "ok":
            result["errors"].append(f"{name}: {note}")
        result["feeds"][name] = {
            "pattern": pattern,
            "n": len(rows),
            "earliest": rows[0]["date"] if rows else "",
            "latest": rows[-1]["date"] if rows else "",
            "rows": rows[:40],
        }
        for row in rows:
            row = dict(row)
            row["feed"] = name
            all_rows.append(row)

    interesting = [row for row in all_rows if row["feed"] in {"channel_id", "handle"}]
    interesting.sort(key=lambda item: item["timestamp"])
    picked = []
    if interesting:
        picked.append(interesting[0])
        picked.append(interesting[len(interesting) // 2])
        picked.append(interesting[-1])
        early = [row for row in interesting if row["date"] <= "2024-12-31"]
        for row in early[:6]:
            picked.append(row)
    seen = set()
    unique = []
    for row in picked:
        if row["timestamp"] in seen:
            continue
        seen.add(row["timestamp"])
        unique.append(row)
    for row in unique[:8]:
        original = row["original"]
        if not original.startswith("http"):
            original = "https://" + original.lstrip("/")
        stamp_url = f"https://web.archive.org/web/{row['timestamp']}id_/{original}"
        log(f"3/4 snapshot {row['date']}")
        status, html, final = net.get_limited(stamp_url, limit=1_200_000, timeout=45)
        extracted = snapshot_extract(html if status == 200 else "")
        extracted.update(
            {
                "date": row["date"],
                "timestamp": row["timestamp"],
                "feed": row["feed"],
                "archive_url": stamp_url,
                "status": status,
                "final": final,
            }
        )
        if status != 200:
            extracted["error"] = f"HTTP {status}"
        result["samples"].append(extracted)
        time.sleep(0.4)

    for handle in (CHANNEL_HANDLE, *SUSPECT_HANDLES):
        log(f"3/4 live handle @{handle}")
        status, html, final = net.get(f"https://www.youtube.com/@{handle}", timeout=30)
        result["handle_ids"][handle] = {
            "status": status,
            "final_url": final,
            "channel_id": channel_id_from_html(html) if status == 200 else "",
        }

    own_id = CHANNEL_ID
    suspect_ids = {
        handle: slot.get("channel_id") or ""
        for handle, slot in result["handle_ids"].items()
        if handle != CHANNEL_HANDLE
    }
    same = [handle for handle, cid in suspect_ids.items() if cid and cid == own_id]
    other = [f"@{handle} → {cid}" for handle, cid in suspect_ids.items() if cid and cid != own_id]
    mentions = []
    for sample in result["samples"]:
        for token in sample.get("mentions") or []:
            if "asian" in token:
                mentions.append(f"{sample['date']}: {token} in {sample['feed']}")
    titles = [(sample["date"], sample.get("title") or "") for sample in result["samples"] if sample.get("title")]
    title_changes = []
    previous = None
    for date, title in titles:
        if previous and title and title != previous[1]:
            title_changes.append(f"{previous[0]} «{previous[1]}» → {date} «{title}»")
        previous = (date, title)

    if same:
        result["rebrand"] = (
            f"Сейчас @{', @'.join(same)} резолвится в тот же {own_id}. Это сильный признак смены хэндла, не отдельного канала."
        )
        result["rebrand_supported"] = True
    elif mentions:
        result["rebrand"] = (
            "В снимках этого channel ID есть строка Asian/Asiandramavibes: " + "; ".join(mentions[:6])
        )
        result["rebrand_supported"] = True
    elif other:
        result["rebrand"] = (
            "Ребрендинг из @Asiandramavibes в этот канал не подтверждён. "
            "Живые подозреваемые хэндлы — другие channel ID: "
            + "; ".join(other)
            + ". Совпадение в поиске по почте само по себе не доказывает, что это прошлое имя UCH8x9zAJbpfipmHosNuwu_A."
        )
        result["rebrand_supported"] = False
    else:
        result["rebrand"] = (
            "CDX и живые страницы не дали общего channel ID и не показали Asiandramavibes в снимках UCH8…. "
            "Момент ребрендинга зафиксировать нельзя."
        )
        result["rebrand_supported"] = False
    result["title_changes"] = title_changes
    result["ok"] = any(slot["n"] for slot in result["feeds"].values()) or bool(result["handle_ids"])
    return result


def ddg_search(net: Net, query: str) -> tuple[list[dict], str]:
    try:
        response = net.client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            timeout=35,
            follow_redirects=True,
        )
    except net.httpx.HTTPError as exc:
        return [], str(exc)
    if "anomaly" in response.text.lower() and "result__a" not in response.text:
        return [], f"HTTP {response.status_code} bot check"
    hits = []
    for match in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', response.text, flags=re.S):
        href = match.group(1)
        parsed = urllib.parse.urlparse(href)
        query_map = urllib.parse.parse_qs(parsed.query)
        if "uddg" in query_map:
            href = urllib.parse.unquote(query_map["uddg"][0])
        title = html_unescape(re.sub(r"<[^>]+>", "", match.group(2)))
        title = re.sub(r"\s+", " ", title).strip()
        if href.startswith("http"):
            hits.append({"title": title[:180], "url": href, "query": query})
    return hits[:12], f"HTTP {response.status_code}"


def github_search(net: Net, url: str) -> tuple[dict | None, str]:
    status, body, note = net.get(url, timeout=25, attempts=2)
    if status == 0:
        return None, note
    if status in {401, 403, 422}:
        return None, f"HTTP {status} (поиск кода GitHub без токена закрыт или упёрся в лимит)"
    if status != 200:
        return None, f"HTTP {status}"
    try:
        return json.loads(body), "HTTP 200"
    except json.JSONDecodeError:
        return None, f"HTTP {status} not json"


def vector_email(net: Net, rows: list[dict], extra_blobs: list[str]) -> dict:
    result = {
        "name": "email",
        "ok": False,
        "errors": [],
        "email": EMAIL,
        "web_hits": [],
        "youtube_channels": [],
        "github": [],
        "adsense_ids": [],
    }
    corpus = [EMAIL, *(row.get("description") or "" for row in rows), *extra_blobs]
    pubs = sorted({match.group(0) for blob in corpus for match in PUB_RE.finditer(blob or "")})
    result["adsense_ids_in_local_corpus"] = pubs

    queries = [
        f'"{EMAIL}"',
        f"{EMAIL} site:github.com",
        f"{EMAIL} pub-",
        "successfrom2024",
    ]
    for query in queries:
        log(f"4/4 search {query}")
        try:
            hits, note = ddg_search(net, query)
        except Exception as exc:  # noqa: BLE001
            hits, note = [], clip(exc, 160)
        if not hits and "HTTP 200" not in note:
            result["errors"].append(f"ddg {query!r}: {note}")
        result["web_hits"].extend(hits)
        time.sleep(0.8)

    log("4/4 youtube search")
    status, html, _final = net.get(
        "https://www.youtube.com/results?search_query=" + urllib.parse.quote(EMAIL),
        timeout=30,
    )
    result["youtube_status"] = status
    initial = extract_brace_object(html, "ytInitialData") or {}
    if status and status != 200:
        result["errors"].append(f"youtube search HTTP {status}")
    seen = set()
    for key in ("channelRenderer", "videoRenderer"):
        nodes = []
        stack: list = [initial]
        while stack and len(nodes) < 30:
            node = stack.pop()
            if isinstance(node, dict):
                renderer = node.get(key)
                if isinstance(renderer, dict):
                    nodes.append(renderer)
                stack.extend(value for value in node.values() if isinstance(value, (dict, list)))
            elif isinstance(node, list):
                stack.extend(node[:40])
        for renderer in nodes:
            title = text_of(renderer.get("title"))
            channel_id = str(renderer.get("channelId") or "")
            video_id = str(renderer.get("videoId") or "")
            browse = ((renderer.get("navigationEndpoint") or {}).get("browseEndpoint") or {}).get("canonicalBaseUrl") or ""
            url = ""
            if browse:
                url = "https://www.youtube.com" + browse
            elif channel_id.startswith("UC"):
                url = f"https://www.youtube.com/channel/{channel_id}"
            elif video_id:
                url = f"https://www.youtube.com/watch?v={video_id}"
            marker = url or title
            if not marker or marker in seen:
                continue
            seen.add(marker)
            result["youtube_channels"].append(
                {"kind": key, "title": title, "channel_id": channel_id, "url": url}
            )

    github_jobs = (
        ("issues", f"https://api.github.com/search/issues?q={urllib.parse.quote(EMAIL)}&per_page=5"),
        ("repos", f"https://api.github.com/search/repositories?q={urllib.parse.quote(EMAIL)}&per_page=5"),
        ("users", "https://api.github.com/search/users?q=successfrom2024&per_page=5"),
        ("code", f"https://api.github.com/search/code?q={urllib.parse.quote(EMAIL)}&per_page=5"),
    )
    for label, url in github_jobs:
        log(f"4/4 github {label}")
        try:
            payload, note = github_search(net, url)
        except Exception as exc:  # noqa: BLE001
            payload, note = None, clip(exc, 160)
        result["github"].append({"label": label, "note": note, "total": (payload or {}).get("total_count")})
        if payload and payload.get("items"):
            for item in payload["items"][:5]:
                result["github"].append(
                    {
                        "label": label,
                        "title": item.get("full_name") or item.get("login") or item.get("title") or item.get("name"),
                        "url": item.get("html_url"),
                    }
                )
        if note and not note.startswith("HTTP 200"):
            result["errors"].append(f"github {label}: {note}")
        time.sleep(1.1)

    joined = "\n".join(
        f"{hit.get('title', '')} {hit.get('url', '')}" for hit in result["web_hits"]
    )
    result["adsense_ids"] = sorted(set(pubs) | set(PUB_RE.findall(joined)))
    year_in_local = "2024" in EMAIL.split("@", 1)[0]
    result["mailbox_year"] = (
        "В локальной части есть 2024. Это выбранное имя, не штамп регистрации Gmail. "
        "Дата создания ящика из адреса не выводится."
        if year_in_local
        else "Года в локальной части нет."
    )
    other_channels = [
        item
        for item in result["youtube_channels"]
        if item.get("kind") == "channelRenderer" and item.get("channel_id") not in {"", CHANNEL_ID}
    ]
    if result["adsense_ids"]:
        adsense_line = "В открытом тексте нашлись pub-идентификаторы: " + ", ".join(result["adsense_ids"])
    else:
        adsense_line = "Идентификаторов AdSense (pub- / ca-pub-) в описаниях, снимках и выдаче нет."
    result["verdict"] = (
        f"{result['mailbox_year']} {adsense_line} "
        + (
            "Другие channelRenderer в выдаче YouTube по адресу перечислены отдельно; попадание в поиск не равно владению."
            if other_channels
            else "Другого channel ID в выдаче по точному адресу нет, либо поиск отдал только этот канал и видео без карточки."
        )
    )
    result["ok"] = True
    return result


def md_cell(value) -> str:
    return str(value or "—").replace("|", "/").replace("\n", " ")


def render(payload: dict) -> str:
    content = payload["content"]
    links = payload["links"]
    wayback = payload["wayback"]
    email = payload["email"]
    lines = [
        "# Финальное досье: @Endlesslove025",
        "",
        f"Снято: {payload['generated_at']}. Channel ID `{CHANNEL_ID}`.",
        "Только публичные ответы плеера, описания, комментарии, Wayback и открытый поиск. "
        "Это не доступ к YouTube Studio, не проверка ящика и не установление личности.",
        "",
        "## 1. Вердикт по деньгам",
        "",
        content.get("verdict") or "Вектор не снят.",
        "",
        content.get("audio_verdict") or "",
        "",
    ]
    if content.get("errors"):
        lines.append("- Сбои: " + "; ".join(content["errors"][:8]))
    counts = content.get("class_counts") or {}
    if counts:
        lines.append(
            "- Классы звука: "
            + ", ".join(f"{key}={value}" for key, value in counts.items())
            + f". Полей монетизации/клейма в ответах: {content.get('ledger_present_n', 0)}."
        )
    if content.get("videos"):
        lines.extend(
            [
                "",
                "| views | id | звук | artist | ключи плеера | license |",
                "|---:|---|---|---|---|---|",
            ]
        )
        for item in content["videos"]:
            lines.append(
                "| {views} | `{vid}` | {track} | {artist} | {keys} | {lic} |".format(
                    views=item.get("views") or 0,
                    vid=item.get("video_id"),
                    track=md_cell(item.get("track") or item.get("audio_class")),
                    artist=md_cell(item.get("artist")),
                    keys=md_cell(", ".join(item.get("keys_found") or []) or "нет"),
                    lic=md_cell(item.get("license")),
                )
            )
        missing = [
            item["video_id"]
            for item in content["videos"]
            if item.get("errors")
        ]
        if missing:
            lines.append("")
            lines.append("Частичные сбои по роликам: " + ", ".join(f"`{item}`" for item in missing[:10]))

    lines.extend(["", "## 2. Карта внешних ссылок", "", links.get("verdict") or "Вектор не снят.", ""])
    if links.get("ok"):
        lines.append(
            f"- Описаний непустых: {links.get('descriptions_with_text')} / {links.get('rows')}. "
            f"С маркером copyright/fair use/credits: {links.get('disclaimer_n')}."
        )
        if links.get("emails_in_descriptions"):
            lines.append(
                "- Почты в описаниях: "
                + ", ".join(f"{addr} ×{count}" for addr, count in links["emails_in_descriptions"])
            )
    if links.get("resolved"):
        lines.extend(["", "| старт | финал | воронка | utm |", "|---|---|---|---|"])
        for item in links["resolved"]:
            utm = ", ".join(f"{key}={value}" for key, value in (item.get("utm") or {}).items()) or "—"
            lines.append(
                f"| {md_cell(item.get('start'))} | {md_cell(item.get('final'))} | {md_cell(item.get('funnel'))} | {md_cell(utm)} |"
            )
    elif links.get("ok"):
        lines.append("- Размотанных внешних URL нет.")
    pinned_hits = [item for item in links.get("from_comments") or [] if item.get("pinned_n")]
    lines.append(
        f"- Роликов топа, где yt-dlp пометил закреп или комментарий автора: {len(pinned_hits)} / {len(links.get('from_comments') or [])}."
    )
    if links.get("errors"):
        lines.append("- Сбои комментариев: " + "; ".join(links["errors"][:8]))

    lines.extend(["", "## 3. История канала по Wayback", "", wayback.get("rebrand") or "Вектор не снят.", ""])
    if wayback.get("title_changes"):
        lines.append("- Смена `<title>` на снятых кадрах:")
        for change in wayback["title_changes"]:
            lines.append(f"  - {change}")
    for name, feed in (wayback.get("feeds") or {}).items():
        lines.append(
            f"- `{feed.get('pattern')}`: снимков {feed.get('n')}, "
            f"ранний {feed.get('earliest') or '—'}, поздний {feed.get('latest') or '—'}."
        )
    if wayback.get("handle_ids"):
        lines.append("- Живые хэндлы:")
        for handle, slot in wayback["handle_ids"].items():
            lines.append(
                f"  - @{handle}: id `{slot.get('channel_id') or 'не извлечён'}`, HTTP {slot.get('status')}, {slot.get('final_url') or '—'}"
            )
    if wayback.get("samples"):
        lines.extend(["", "| дата | feed | title | подписчики | упоминания | аватар |", "|---|---|---|---|---|---|"])
        for sample in wayback["samples"]:
            lines.append(
                "| {date} | {feed} | {title} | {subs} | {mentions} | {avatar} |".format(
                    date=sample.get("date"),
                    feed=sample.get("feed"),
                    title=md_cell(sample.get("title")),
                    subs=md_cell(sample.get("subscribers")),
                    mentions=md_cell(", ".join(sample.get("mentions") or [])),
                    avatar=md_cell(sample.get("avatar")),
                )
            )
    if wayback.get("errors"):
        lines.append("")
        lines.append("- Сбои CDX: " + "; ".join(wayback["errors"][:8]))

    lines.extend(["", "## 4. Профиль по публичному следу", "", email.get("verdict") or "Вектор не снят.", ""])
    lines.append(f"- Адрес `{EMAIL}` уже стоит в описании канала как контакт для чужих клипов.")
    if email.get("web_hits"):
        lines.extend(["", "| выдача | url |", "|---|---|"])
        seen = set()
        for hit in email["web_hits"]:
            if hit.get("url") in seen:
                continue
            seen.add(hit.get("url"))
            lines.append(f"| {md_cell(hit.get('title'))} | {md_cell(hit.get('url'))} |")
            if len(seen) >= 15:
                break
    else:
        lines.append("- Веб-выдача по адресу пустая или отсечена антиботом.")
    yt_channels = [item for item in email.get("youtube_channels") or [] if item.get("kind") == "channelRenderer"]
    if yt_channels:
        lines.append("- Карточки каналов в поиске YouTube:")
        for item in yt_channels[:8]:
            same = "тот же ID" if item.get("channel_id") == CHANNEL_ID else "другой ID"
            lines.append(f"  - {item.get('title') or '—'} `{item.get('channel_id') or '—'}` ({same}) {item.get('url') or ''}")
    if email.get("github"):
        lines.append("- GitHub:")
        for item in email["github"]:
            if item.get("url"):
                lines.append(f"  - {item.get('label')}: {item.get('title')} — {item.get('url')}")
            else:
                lines.append(f"  - {item.get('label')}: {item.get('note')}, total={item.get('total')}")
    if email.get("adsense_ids"):
        lines.append("- AdSense: " + ", ".join(f"`{item}`" for item in email["adsense_ids"]))
    else:
        lines.append("- AdSense `pub-` в открытых текстах нет.")
    if email.get("errors"):
        lines.append("- Сбои поиска: " + "; ".join(email["errors"][:8]))

    lines.extend(["", "## Стоит ли копировать модель", ""])
    lines.append(copy_verdict(payload))
    lines.extend(
        [
            "",
            "## Чего в этом досье нет",
            "",
            "- Получателя денег. Пока `monetizationDetails` и claim ID не появились в анонимном ответе, фраза «доход заблокирован» или «админ получает выплаты» была бы выдумкой.",
            "- Даты создания Gmail. Цифра 2024 в адресе — часть имени.",
            "- Ребрендинга, если Wayback и живой channel ID не совпали. Другой хэндл из поиска — не прошлая жизнь этого UC.",
            "- Имени, города и платёжного аккаунта владельца. Их в этих источниках нет, и скрипт их не додумывает.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def copy_verdict(payload: dict) -> str:
    links = payload.get("links") or {}
    content = payload.get("content") or {}
    wayback = payload.get("wayback") or {}
    disclaimer = int(links.get("disclaimer_n") or 0)
    rows = int(links.get("rows") or 0)
    external = len(links.get("resolved") or [])
    attributed = int((content.get("class_counts") or {}).get("attributed_track") or 0)
    library = int((content.get("class_counts") or {}).get("library_hint") or 0)
    parts = []
    if rows and disclaimer:
        parts.append(
            f"В описаниях {disclaimer} роликов из {rows} есть fair use / copyright / credits. "
            "Это след перезаливки чужих клипов, не производственный стек, который стоит клонировать."
        )
    if not external:
        parts.append("Арбитражной посадки нет: копировать CPA-воронку нечего, её в публичных текстах нет.")
    else:
        parts.append("Внешние ссылки есть, но это не инструкция, как повторить оффер. Смотреть таблицу, не схему заработка.")
    if library or attributed:
        parts.append(
            "Названный звук или намёк на библиотеку означает, что аудио не ваше. "
            "Повторять чужой трек в расчёте получить его долю — плохая ставка: получатель выплаты отсюда не виден."
        )
    if wayback.get("rebrand_supported"):
        parts.append("Смена имени подтверждена только в той мере, что указана в разделе Wayback. Само по себе это не секрет модели.")
    else:
        parts.append("История «родился как @Asiandramavibes» этим прогоном не доказана. Строить стратегию на чужом хэндле нельзя.")
    parts.append(
        "Копировать имеет смысл только частоту и формат, если ролики свои. "
        "Модель чужих клипов, дисклеймера и невидимого Content ID копировать не стоит: риск авторских прав сидит на том, кто перезаливает, а не в досье."
    )
    return " ".join(parts)


def run(args: argparse.Namespace) -> dict:
    selected = set(args.only) if args.only else {"content", "links", "wayback", "email"}
    rows, notes = load_rows(args.csv)
    checkpoint = load_checkpoint()
    payload = {
        "generated_at": _now(),
        "csv": str(args.csv),
        "csv_notes": notes,
        "content": {"ok": False, "errors": ["skipped"], "videos": []},
        "links": {"ok": False, "errors": ["skipped"], "resolved": [], "from_comments": []},
        "wayback": {"ok": False, "errors": ["skipped"], "feeds": {}, "samples": []},
        "email": {"ok": False, "errors": ["skipped"]},
    }
    net = Net()
    try:
        if "content" in selected:
            payload["content"] = vector_content(net, rows, args.top_content, checkpoint)
        if "links" in selected:
            payload["links"] = vector_links(net, rows, args.top_comments, checkpoint)
        if "wayback" in selected:
            payload["wayback"] = vector_wayback(net)
        if "email" in selected:
            extra = []
            for sample in payload["wayback"].get("samples") or []:
                extra.append(" ".join(sample.get("mentions") or []))
                extra.append(sample.get("title") or "")
            payload["email"] = vector_email(net, rows, extra)
    finally:
        net.close()
    return payload


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Public deep dive on @Endlesslove025")
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE_PATH)
    parser.add_argument("--top-content", type=int, default=10)
    parser.add_argument("--top-comments", type=int, default=20)
    parser.add_argument(
        "--only",
        nargs="+",
        choices=("content", "links", "wayback", "email"),
        help="run a subset; default is all four",
    )
    args = parser.parse_args()
    payload = run(args)
    args.evidence.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.report.write_text(render(payload), encoding="utf-8")
    log(f"wrote {args.report}")
    log(f"wrote {args.evidence}")


if __name__ == "__main__":
    main()
