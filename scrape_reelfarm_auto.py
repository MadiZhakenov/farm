#!/usr/bin/env python3
"""
scrape_reelfarm_auto.py
=======================
Fully automatic ReelFarm database scraper.

Target: https://reel.farm/dashboard/database  (~8,249 carousels)

Strategy (in order):
  1. Playwright (headed) + persistent session (.browser_session)
  2. Network sniffer for JSON API (tRPC / REST / RSC)
  3. Parse embedded Next.js flight payload (self.__next_f) — primary path
     (the full creator/slideshow DB is SSR'd into the page HTML)
  4. If a paginated API is discovered → parallel httpx download
  5. Fallback: niche clicks + scroll, collecting DOM + network JSON

Outputs:
  - reelfarm_database.db  (SQLite table `slideshows`)
  - reelfarm_dataset.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import httpx

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
SESSION_DIR = ROOT / ".browser_session"
DB_PATH = ROOT / "reelfarm_database.db"
JSONL_PATH = ROOT / "reelfarm_dataset.jsonl"
API_DISCOVERY_PATH = ROOT / "reelfarm_api_discovery.json"
TARGET_URL = "https://reel.farm/dashboard/database"
EXPECTED_TOTAL = 8249

JSON_HINTS = (
    "slideshows",
    "items",
    "niche",
    "collectCount",
    "playCount",
    "recent_slideshows",
    "bookmarks",
    "unique_id",
    "product_medium",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ensure_playwright_browsers() -> None:
    """Install Chromium for Playwright if missing."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # Probe: launch briefly; if browser binary missing, install.
            try:
                browser = p.chromium.launch(headless=True)
                browser.close()
                return
            except Exception as exc:
                msg = str(exc).lower()
                if "executable doesn't exist" in msg or "browser" in msg:
                    print("[setup] Playwright Chromium not found - installing...")
                else:
                    print(f"[setup] Playwright launch probe failed ({exc}); installing Chromium...")
    except ImportError:
        print("[setup] playwright package missing - pip install playwright")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])

    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    print("[setup] Chromium ready.")


def progress_bar(current: int, total: int, prefix: str = "") -> None:
    total = max(total, 1)
    width = 36
    filled = int(width * min(current, total) / total)
    bar = "#" * filled + "-" * (width - filled)
    pct = 100.0 * min(current, total) / total
    sys.stdout.write(f"\r{prefix}[{bar}] {current}/{total} ({pct:5.1f}%)")
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")


def parse_count(value: Any) -> Optional[int]:
    """Parse '1.7M' / '88.2K' / '345' / int → int."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().replace(",", "").upper()
    if not s:
        return None
    mult = 1
    if s.endswith("K"):
        mult = 1_000
        s = s[:-1]
    elif s.endswith("M"):
        mult = 1_000_000
        s = s[:-1]
    elif s.endswith("B"):
        mult = 1_000_000_000
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def stable_slideshow_id(creator_id: Any, images: list[str], idx: int) -> str:
    seed = f"{creator_id}|{idx}|{(images or [''])[0]}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def looks_like_db_payload(obj: Any) -> bool:
    """Heuristic: JSON body that carries slideshow / creator DB rows."""
    text = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    hits = sum(1 for k in JSON_HINTS if k in text)
    if hits < 2:
        return False
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        keys = set(obj[0].keys())
        if "recent_slideshows" in keys or ("likes" in keys and "images" in keys):
            return True
        if "niche" in keys and ("id" in keys or "unique_id" in keys):
            return True
    if isinstance(obj, dict):
        for key in ("slideshows", "items", "data", "results", "creators", "accounts"):
            val = obj.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return True
    return "recent_slideshows" in text


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class Store:
    def __init__(self, db_path: Path = DB_PATH, jsonl_path: Path = JSONL_PATH):
        self.db_path = db_path
        self.jsonl_path = jsonl_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS slideshows (
                id TEXT PRIMARY KEY,
                title TEXT,
                niche TEXT,
                product_medium TEXT,
                audience_region TEXT,
                views INTEGER,
                likes INTEGER,
                saves INTEGER,
                slide_urls TEXT,
                raw_json TEXT,
                creator_id TEXT,
                creator_unique_id TEXT,
                updated_at TEXT
            )
            """
        )
        self.conn.commit()
        self._seen = {row[0] for row in self.conn.execute("SELECT id FROM slideshows")}
        self.inserted = 0

    @property
    def count(self) -> int:
        return len(self._seen)

    def upsert_row(self, row: dict[str, Any]) -> bool:
        rid = str(row["id"])
        is_new = rid not in self._seen
        self.conn.execute(
            """
            INSERT INTO slideshows (
                id, title, niche, product_medium, audience_region,
                views, likes, saves, slide_urls, raw_json,
                creator_id, creator_unique_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                niche=excluded.niche,
                product_medium=excluded.product_medium,
                audience_region=excluded.audience_region,
                views=excluded.views,
                likes=excluded.likes,
                saves=excluded.saves,
                slide_urls=excluded.slide_urls,
                raw_json=excluded.raw_json,
                creator_id=excluded.creator_id,
                creator_unique_id=excluded.creator_unique_id,
                updated_at=excluded.updated_at
            """,
            (
                rid,
                row.get("title"),
                row.get("niche"),
                row.get("product_medium"),
                row.get("audience_region"),
                row.get("views"),
                row.get("likes"),
                row.get("saves"),
                json.dumps(row.get("slide_urls") or [], ensure_ascii=False),
                json.dumps(row.get("raw_json") or {}, ensure_ascii=False),
                row.get("creator_id"),
                row.get("creator_unique_id"),
                row.get("updated_at") or time.strftime("%Y-%m-%dT%H:%M:%S"),
            ),
        )
        if is_new:
            self._seen.add(rid)
            self.inserted += 1
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return is_new

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def rewrite_jsonl_from_db(self) -> None:
        """Optional full dump sync (after bulk upserts)."""
        with open(self.jsonl_path, "w", encoding="utf-8") as f:
            for row in self.conn.execute(
                "SELECT id, title, niche, product_medium, audience_region, "
                "views, likes, saves, slide_urls, raw_json, creator_id, "
                "creator_unique_id, updated_at FROM slideshows"
            ):
                (
                    rid,
                    title,
                    niche,
                    product_medium,
                    audience_region,
                    views,
                    likes,
                    saves,
                    slide_urls,
                    raw_json,
                    creator_id,
                    creator_unique_id,
                    updated_at,
                ) = row
                rec = {
                    "id": rid,
                    "title": title,
                    "niche": niche,
                    "product_medium": product_medium,
                    "audience_region": audience_region,
                    "metrics": {"views": views, "likes": likes, "saves": saves},
                    "slide_urls": json.loads(slide_urls or "[]"),
                    "raw_json": json.loads(raw_json or "{}"),
                    "creator_id": creator_id,
                    "creator_unique_id": creator_unique_id,
                    "updated_at": updated_at,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Normalization: creators[] with recent_slideshows → flat rows
# ---------------------------------------------------------------------------


def flatten_creators(creators: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for creator in creators:
        if not isinstance(creator, dict):
            continue
        slideshows = creator.get("recent_slideshows") or []
        if not isinstance(slideshows, list):
            continue
        niche = creator.get("niche")
        product_medium = creator.get("product_medium")
        audience_region = creator.get("region") or creator.get("audience_region")
        creator_id = creator.get("id")
        unique_id = creator.get("unique_id")
        nickname = creator.get("nickname") or unique_id or ""

        for idx, ss in enumerate(slideshows):
            if not isinstance(ss, dict):
                continue
            images = ss.get("images") or ss.get("slide_urls") or []
            if not isinstance(images, list):
                images = []
            images = [str(u) for u in images if u]
            sid = (
                str(ss["id"])
                if ss.get("id") is not None
                else stable_slideshow_id(creator_id, images, idx)
            )
            title = (ss.get("prompt") or "").strip() or f"{nickname} slideshow #{idx + 1}"
            views = parse_count(ss.get("views") or ss.get("playCount") or ss.get("play_count"))
            likes = parse_count(ss.get("likes") or ss.get("diggCount") or ss.get("digg_count"))
            saves = parse_count(
                ss.get("bookmarks")
                or ss.get("saves")
                or ss.get("collectCount")
                or ss.get("collect_count")
            )
            raw = {
                "creator": {
                    k: creator.get(k)
                    for k in (
                        "id",
                        "unique_id",
                        "nickname",
                        "signature",
                        "follower_count",
                        "following_count",
                        "avatar_url",
                        "product",
                        "product_medium",
                        "link_in_bio",
                        "niche",
                        "region",
                        "audience_regions",
                        "created_at",
                        "updated_at",
                    )
                },
                "slideshow": ss,
                "slideshow_index": idx,
            }
            rows.append(
                {
                    "id": sid,
                    "title": title,
                    "niche": niche,
                    "product_medium": product_medium,
                    "audience_region": audience_region,
                    "metrics": {"views": views, "likes": likes, "saves": saves},
                    "views": views,
                    "likes": likes,
                    "saves": saves,
                    "slide_urls": images,
                    "raw_json": raw,
                    "creator_id": str(creator_id) if creator_id is not None else None,
                    "creator_unique_id": unique_id,
                    "updated_at": creator.get("updated_at"),
                }
            )
    return rows


def extract_creators_from_obj(obj: Any) -> list[dict[str, Any]]:
    """Pull creator list from various JSON shapes."""
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        if "recent_slideshows" in obj[0] or "unique_id" in obj[0]:
            return obj  # type: ignore[return-value]
        # maybe list of slideshows already
        if "images" in obj[0] and ("likes" in obj[0] or "views" in obj[0]):
            # wrap as synthetic creator
            return [{"id": "unknown", "unique_id": "unknown", "recent_slideshows": obj}]
    if isinstance(obj, dict):
        for key in ("creators", "accounts", "items", "data", "results", "slideshows"):
            val = obj.get(key)
            if isinstance(val, list) and val:
                return extract_creators_from_obj(val)
        # nested data.data
        if isinstance(obj.get("data"), dict):
            return extract_creators_from_obj(obj["data"])
    return []


def extract_creators_from_html(html: str) -> list[dict[str, Any]]:
    """Parse Next.js App Router flight payloads for the creators array."""
    # 1) Classic pages router
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    if m:
        try:
            data = json.loads(m.group(1))
            creators = extract_creators_from_obj(data)
            if creators:
                print(f"[parse] __NEXT_DATA__ -> {len(creators)} creators")
                return creators
        except json.JSONDecodeError:
            pass

    # 2) App Router: self.__next_f.push([...])
    pushes = re.findall(r"self\.__next_f\.push\((\[.*?\])\)\s*</script>", html, re.S)
    pushes.sort(key=len, reverse=True)
    for push in pushes[:5]:
        try:
            arr = json.loads(push)
        except json.JSONDecodeError:
            continue
        # Typical: [1, "<stringified chunk>"] or nested strings
        candidates: list[str] = []
        if isinstance(arr, list):
            for item in arr:
                if isinstance(item, str) and "unique_id" in item and "recent_slideshows" in item:
                    candidates.append(item)
                elif isinstance(item, list):
                    for sub in item:
                        if isinstance(sub, str) and "recent_slideshows" in sub:
                            candidates.append(sub)
        for cand in candidates:
            # Find creators array start
            mm = re.search(r'\[\{\"id\":\d+,\"unique_id\":', cand)
            if not mm:
                mm = re.search(r'\[{"id":\d+,"unique_id":', cand)
            if not mm:
                continue
            try:
                creators, _ = json.JSONDecoder().raw_decode(cand[mm.start() :])
            except json.JSONDecodeError:
                continue
            if isinstance(creators, list) and creators and isinstance(creators[0], dict):
                if "recent_slideshows" in creators[0] or "unique_id" in creators[0]:
                    print(f"[parse] __next_f flight -> {len(creators)} creators")
                    return creators  # type: ignore[return-value]
    return []


# ---------------------------------------------------------------------------
# Network discovery
# ---------------------------------------------------------------------------


@dataclass
class DiscoveredAPI:
    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    post_data: Optional[Any] = None
    pagination: dict[str, Any] = field(default_factory=dict)
    sample_body: Any = None


class NetworkSniffer:
    def __init__(self) -> None:
        self.hits: list[DiscoveredAPI] = []
        self._raw_bodies: list[tuple[str, Any]] = []
        self.lock = asyncio.Lock() if False else None  # sync playwright

    def handle_response(self, response) -> None:
        try:
            ct = (response.headers.get("content-type") or "").lower()
            url = response.url
            if "application/json" not in ct and "text/x-component" not in ct:
                # Still try RSC / flight text that embeds JSON
                if "reel.farm" not in url:
                    return
                if not any(x in url for x in ("api", "trpc", "database", "rsc", "_next")):
                    return

            body_text = None
            try:
                body_text = response.text()
            except Exception:
                return
            if not body_text or len(body_text) < 20:
                return
            if not any(h in body_text for h in JSON_HINTS):
                return

            parsed: Any = None
            try:
                parsed = json.loads(body_text)
            except json.JSONDecodeError:
                # Maybe Next.js RSC wrapped
                creators = extract_creators_from_html(
                    f"<script>self.__next_f.push({body_text!r})</script>"
                    if body_text.startswith("[")
                    else body_text
                )
                if creators:
                    parsed = creators
                else:
                    return

            if not looks_like_db_payload(parsed) and not extract_creators_from_obj(parsed):
                # keep if it still has recent_slideshows somewhere
                dump = json.dumps(parsed)[:5000]
                if "recent_slideshows" not in dump and "bookmarks" not in dump:
                    return

            req = response.request
            headers = {}
            for key in (
                "cookie",
                "authorization",
                "x-trpc-source",
                "x-trpc",
                "content-type",
                "x-nextjs-data",
                "rsc",
                "next-action",
                "next-router-state-tree",
            ):
                val = req.headers.get(key)
                if val:
                    headers[key] = val

            qs = parse_qs(urlparse(url).query)
            pagination = {}
            for k, v in qs.items():
                kl = k.lower()
                if kl in ("page", "limit", "cursor", "offset", "take", "skip", "after", "before"):
                    pagination[k] = v[0] if len(v) == 1 else v

            # Also sniff body pagination keys
            if isinstance(parsed, dict):
                for k in ("page", "limit", "cursor", "nextCursor", "offset", "total", "hasMore"):
                    if k in parsed:
                        pagination[f"body.{k}"] = parsed[k]

            api = DiscoveredAPI(
                url=url,
                method=req.method,
                headers=headers,
                post_data=None,
                pagination=pagination,
                sample_body=_shrink(parsed),
            )
            self.hits.append(api)
            self._raw_bodies.append((url, parsed))
            self._print_discovery(api)
        except Exception as exc:
            # Never break page flow because of sniffer errors
            print(f"[sniffer] warn: {exc}")

    def _print_discovery(self, api: DiscoveredAPI) -> None:
        print("\n" + "=" * 72)
        print("[DISCOVERY] Candidate database endpoint")
        print(f"  URL:     {api.url}")
        print(f"  Method:  {api.method}")
        print(f"  Headers: {json.dumps(api.headers, ensure_ascii=False)[:800]}")
        print(f"  Pagination hints: {api.pagination or '(none in query/body)'}")
        print("=" * 72 + "\n")


def _shrink(obj: Any, max_list: int = 2) -> Any:
    if isinstance(obj, list):
        return [_shrink(x) for x in obj[:max_list]] + ([f"...({len(obj)} total)"] if len(obj) > max_list else [])
    if isinstance(obj, dict):
        return {k: _shrink(v) for k, v in list(obj.items())[:40]}
    if isinstance(obj, str) and len(obj) > 200:
        return obj[:200] + "..."
    return obj


# ---------------------------------------------------------------------------
# httpx bulk download (Variant A)
# ---------------------------------------------------------------------------


def httpx_paginate(api: DiscoveredAPI, store: Store, expected: int = EXPECTED_TOTAL) -> int:
    """Best-effort pagination using discovered URL/headers."""
    print("[httpx] Attempting bulk download via discovered API...")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Referer": TARGET_URL,
    }
    headers.update({k: v for k, v in api.headers.items() if k.lower() != "content-length"})

    parsed = urlparse(api.url)
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    qs = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}

    # Guess pagination param names
    page_key = next((k for k in qs if k.lower() in ("page", "offset", "skip")), None)
    cursor_key = next((k for k in qs if k.lower() in ("cursor", "after")), None)
    limit_key = next((k for k in qs if k.lower() in ("limit", "take", "pageSize", "pagesize")), None)

    if limit_key:
        try:
            qs[limit_key] = str(max(int(qs[limit_key]), 100))
        except Exception:
            qs[limit_key] = "100"
    else:
        qs.setdefault("limit", "100")
        limit_key = "limit"

    saved_before = store.count
    with httpx.Client(headers=headers, timeout=60.0, follow_redirects=True) as client:
        page = int(qs.get(page_key or "page", 1) or 1) if page_key else 1
        cursor = qs.get(cursor_key) if cursor_key else None
        empty_streak = 0
        for _ in range(500):
            params = dict(qs)
            if page_key:
                params[page_key] = str(page)
            if cursor_key and cursor:
                params[cursor_key] = cursor

            try:
                r = client.request(api.method, base, params=params)
            except Exception as exc:
                print(f"[httpx] request failed: {exc}")
                break
            if r.status_code >= 400:
                print(f"[httpx] HTTP {r.status_code} - stopping pagination")
                break
            try:
                body = r.json()
            except Exception:
                print("[httpx] non-JSON response - stopping")
                break

            creators = extract_creators_from_obj(body)
            rows = flatten_creators(creators) if creators else []
            # Maybe response is already a page of slideshows
            if not rows and isinstance(body, dict):
                for key in ("slideshows", "items", "results"):
                    if isinstance(body.get(key), list):
                        rows = flatten_creators(
                            [{"id": "page", "unique_id": "page", "recent_slideshows": body[key]}]
                        )
                        break

            new = 0
            for row in rows:
                if store.upsert_row(row):
                    new += 1
            store.commit()
            progress_bar(store.count, expected, prefix="httpx ")

            # next page
            next_cursor = None
            if isinstance(body, dict):
                next_cursor = body.get("nextCursor") or body.get("cursor") or body.get("next")
                if isinstance(next_cursor, dict):
                    next_cursor = next_cursor.get("cursor")

            if new == 0:
                empty_streak += 1
            else:
                empty_streak = 0
            if empty_streak >= 3:
                break
            if store.count >= expected:
                break

            if cursor_key and next_cursor and next_cursor != cursor:
                cursor = next_cursor
            elif page_key:
                page += 1
            else:
                # no clear pagination - single shot
                break

    return store.count - saved_before


# ---------------------------------------------------------------------------
# Main Playwright flow
# ---------------------------------------------------------------------------


def wait_for_login_if_needed(page, timeout_sec: int = 300) -> None:
    """If redirected to login / paywall, wait for user to authenticate."""
    url = page.url
    content = ""
    try:
        content = page.content()
    except Exception:
        pass
    needs_login = any(
        x in url.lower()
        for x in ("login", "signin", "sign-in", "auth", "signup")
    ) or (
        "sign in" in content.lower()[:5000]
        and "unique_id" not in content
        and "recent_slideshows" not in content
    )
    if not needs_login:
        # also check for lock / gated database
        if "recent_slideshows" in content or "unique_id" in content:
            return
        # soft check: niche list visible is enough (public SSR)
        if "Browse by Niche" in content or "self improvement" in content:
            return

    print(
        "\n[auth] Login / subscription may be required.\n"
        "       Log in manually in the opened Chromium window.\n"
        f"       Waiting up to {timeout_sec}s for database content...\n"
    )
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            html = page.content()
        except Exception:
            time.sleep(2)
            continue
        if "recent_slideshows" in html or html.count("unique_id") > 10:
            print("[auth] Database content detected - continuing.")
            return
        if "Browse by Niche" in html and "self improvement" in html:
            # Public SSR dump may already be present
            if "recent_slideshows" in html:
                print("[auth] Public database payload detected.")
                return
        time.sleep(2)
    print("[auth] Timeout waiting for login - will still try to parse whatever is on the page.")


def click_niches_and_scroll(page, sniffer: NetworkSniffer, store: Store, expected: int) -> None:
    """Variant B: interact with UI to force API / hydrate more rows."""
    print("[dom] Variant B - clicking niches / scrolling to trigger loads...")
    # Click niche chips if present
    try:
        chips = page.locator("a, button, div, span").filter(has_text=re.compile(r"\(\d+\)"))
        n = min(chips.count(), 40)
        for i in range(n):
            try:
                chips.nth(i).click(timeout=2000)
                page.wait_for_timeout(800)
            except Exception:
                continue
            # After each click, try parse HTML
            html = page.content()
            creators = extract_creators_from_html(html)
            if creators:
                rows = flatten_creators(creators)
                for row in rows:
                    store.upsert_row(row)
                store.commit()
                progress_bar(store.count, expected, prefix="dom  ")
    except Exception as exc:
        print(f"[dom] niche click warn: {exc}")

    # Scroll main page
    for _ in range(30):
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(400)
        # ingest any sniffer bodies
        for url, body in list(sniffer._raw_bodies):
            creators = extract_creators_from_obj(body)
            if not creators:
                continue
            for row in flatten_creators(creators):
                store.upsert_row(row)
        store.commit()
        progress_bar(store.count, expected, prefix="dom  ")
        if store.count >= expected:
            break


def run(args: argparse.Namespace) -> int:
    ensure_playwright_browsers()
    from playwright.sync_api import sync_playwright

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    # Fresh JSONL only if empty DB requested
    store = Store()
    if args.fresh:
        store.conn.execute("DELETE FROM slideshows")
        store.conn.commit()
        store._seen.clear()
        JSONL_PATH.write_text("", encoding="utf-8")
        print("[store] Cleared previous DB/JSONL.")

    sniffer = NetworkSniffer()
    creators: list[dict[str, Any]] = []

    print(f"[browser] Persistent context -> {SESSION_DIR}")
    print(f"[browser] Opening {TARGET_URL} (headless={args.headless})")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=args.headless,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.on("response", sniffer.handle_response)

        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(2500)
        wait_for_login_if_needed(page, timeout_sec=args.login_timeout)

        # Give SPA a moment to fetch client-side JSON
        page.wait_for_timeout(2000)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass

        html = page.content()
        creators = extract_creators_from_html(html)

        # Also drain sniffer bodies
        if not creators:
            for url, body in sniffer._raw_bodies:
                creators = extract_creators_from_obj(body)
                if creators:
                    print(f"[sniffer] Using body from {url}")
                    break

        if creators:
            rows = flatten_creators(creators)
            print(f"[parse] Flattened {len(rows)} slideshows from {len(creators)} creators")
            for i, row in enumerate(rows, 1):
                store.upsert_row(row)
                if i % 50 == 0 or i == len(rows):
                    progress_bar(store.count, max(EXPECTED_TOTAL, len(rows)), prefix="save ")
            store.commit()
        else:
            print("[parse] No embedded creators found yet - trying UI interaction / APIs...")

        # Variant A: if API discovered and we still miss rows
        if store.count < args.min_ok and sniffer.hits:
            API_DISCOVERY_PATH.write_text(
                json.dumps([api.__dict__ for api in sniffer.hits], ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            print(f"[discovery] Saved {len(sniffer.hits)} endpoints -> {API_DISCOVERY_PATH}")
            # Prefer largest sample bodies
            best = sniffer.hits[0]
            httpx_paginate(best, store, expected=EXPECTED_TOTAL)

        # Variant B
        if store.count < args.min_ok:
            click_niches_and_scroll(page, sniffer, store, EXPECTED_TOTAL)
            html = page.content()
            more = extract_creators_from_html(html)
            if more:
                for row in flatten_creators(more):
                    store.upsert_row(row)
                store.commit()

        # Keep browser open briefly so user can see result
        if not args.headless and args.keep_open > 0:
            print(f"[browser] Keeping window open {args.keep_open}s...")
            page.wait_for_timeout(args.keep_open * 1000)

        context.close()

    # Final JSONL rewrite for consistency
    store.rewrite_jsonl_from_db()
    total = store.count
    store.close()

    print("\n" + "=" * 72)
    print(f"DONE. Slideshows stored: {total}")
    print(f"  SQLite: {DB_PATH}")
    print(f"  JSONL:  {JSONL_PATH}")
    if sniffer.hits:
        print(f"  API discovery log: {API_DISCOVERY_PATH} ({len(sniffer.hits)} hits)")
    if total < EXPECTED_TOTAL:
        print(
            f"  NOTE: expected ~{EXPECTED_TOTAL}, got {total}. "
            "Re-run after logging in if the page was gated."
        )
    else:
        print(f"  Full database captured (>={EXPECTED_TOTAL}).")
    print("=" * 72)
    return 0 if total >= args.min_ok else 2


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Auto-scrape reel.farm slideshow database")
    p.add_argument("--headless", action="store_true", help="Run Chromium headless (default: visible)")
    p.add_argument("--fresh", action="store_true", help="Wipe SQLite/JSONL before scrape")
    p.add_argument("--login-timeout", type=int, default=300, help="Seconds to wait for manual login")
    p.add_argument("--keep-open", type=int, default=5, help="Seconds to keep browser open at end")
    p.add_argument(
        "--min-ok",
        type=int,
        default=1000,
        help="Minimum rows for exit code 0 (default 1000; full set ~8249)",
    )
    return p


if __name__ == "__main__":
    # Avoid Windows console encoding crashes on niche emoji / nicknames
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(run(build_argparser().parse_args()))
