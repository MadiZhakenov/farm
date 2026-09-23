#!/usr/bin/env python3
"""
scrape_tiktok_collection.py
===========================
Скачивает все посты (photo/video carousel) из конкретной TikTok-коллекции.

Этап 1 — Playwright: скролл коллекции → уникальные URL постов
Этап 2 — Playwright + httpx: itemStruct / imagePost → слайды + meta.json

Хранение:
  curated_collection/{post_id}/1.jpg, 2.jpg, ...
  curated_collection/{post_id}/meta.json

Пример:
  python scrape_tiktok_collection.py
  python scrape_tiktok_collection.py --headed
  python scrape_tiktok_collection.py --limit 5
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import httpx

ROOT = Path(__file__).resolve().parent
SESSION_DIR = ROOT / ".browser_session"
OUT_DIR = ROOT / "curated_collection"
URLS_CHECKPOINT = OUT_DIR / "_collection_urls.json"

DEFAULT_COLLECTION_URL = (
    "https://www.tiktok.com/@user2030916120522/collection/"
    "%D0%A7%D1%83%D0%B6%D0%B0%D1%8F%20%D1%84%D0%B5%D1%80%D0%BC%D0%B0-7610866374575672084"
)


def set_out_dir(path: Path | str) -> Path:
    """Point all downloads/checkpoints at a collection-specific folder."""
    global OUT_DIR, URLS_CHECKPOINT
    OUT_DIR = Path(path)
    if not OUT_DIR.is_absolute():
        OUT_DIR = ROOT / OUT_DIR
    URLS_CHECKPOINT = OUT_DIR / "_collection_urls.json"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
POST_HREF_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@[^/]+/(?:video|photo)/(\d+)",
    re.I,
)
POST_PATH_RE = re.compile(r"/@[^/]+/(?:video|photo)/(\d+)", re.I)

# Optional converters from this repo
try:
    from vvic_to_jpg import is_vvic, vvic_to_jpg  # type: ignore
except Exception:
    def is_vvic(data: bytes) -> bool:  # type: ignore
        return len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] == b"vvic"

    def vvic_to_jpg(src, dest_jpg: Path, ffmpeg: str = "ffmpeg") -> Path:  # type: ignore
        raise RuntimeError("vvic_to_jpg unavailable")

try:
    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    HAS_HEIF = True
except Exception:
    HAS_HEIF = False
    Image = None  # type: ignore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_post_url(url: str) -> Optional[tuple[str, str]]:
    """Return (canonical_url, post_id) or None."""
    if not url:
        return None
    # absolutize relative
    if url.startswith("/"):
        url = "https://www.tiktok.com" + url
    url = url.split("?")[0].split("#")[0].rstrip("/")
    m = POST_HREF_RE.search(url) or POST_PATH_RE.search(url)
    if not m:
        return None
    post_id = m.group(1)
    # rebuild clean url from match
    full = POST_HREF_RE.search(url)
    if full:
        canonical = full.group(0)
    else:
        # path-only match — keep original host path
        pm = POST_PATH_RE.search(url)
        assert pm
        # extract @user and kind from path
        path_m = re.search(r"/(@[^/]+)/(video|photo)/(\d+)", url, re.I)
        if not path_m:
            return None
        canonical = f"https://www.tiktok.com/{path_m.group(1)}/{path_m.group(2)}/{path_m.group(3)}"
    return canonical, post_id


def url_variants(url: str) -> list[str]:
    p = urlparse(url)
    out = [url, urlunparse((p.scheme, p.netloc, p.path, "", "", ""))]
    if "tiktokcdn" in p.netloc:
        host = p.netloc.replace("-sign", "")
        out.append(urlunparse((p.scheme, host, p.path, "", "", "")))
        for h in (
            "p16-common.tiktokcdn-us.com",
            "p19-common.tiktokcdn-us.com",
            "p16.tiktokcdn.com",
        ):
            out.append(urlunparse((p.scheme, h, p.path, "", "", "")))
    seen: set[str] = set()
    uniq: list[str] = []
    for u in out:
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def is_heif(data: bytes) -> bool:
    return (
        len(data) >= 12
        and data[4:8] == b"ftyp"
        and data[8:12] in {b"heic", b"heif", b"mif1", b"msf1"}
    )


def save_as_jpg(data: bytes, dest: Path) -> None:
    """Write viewable JPEG to dest (converts VVIC/HEIC when needed)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if data[:3] == b"\xff\xd8\xff":
        dest.write_bytes(data)
        return
    if is_vvic(data):
        vvic_to_jpg(data, dest)
        return
    if is_heif(data) and HAS_HEIF and Image is not None:
        with Image.open(BytesIO(data)) as im:
            im.convert("RGB").save(dest, format="JPEG", quality=92)
        return
    # PNG/WEBP → JPEG via Pillow if available
    if Image is not None and (
        data[:8] == b"\x89PNG\r\n\x1a\n"
        or (data[:4] == b"RIFF" and b"WEBP" in data[:16])
    ):
        with Image.open(BytesIO(data)) as im:
            im.convert("RGB").save(dest, format="JPEG", quality=92)
        return
    # last resort: write raw bytes with .jpg name (may be broken)
    dest.write_bytes(data)


def already_downloaded(folder: Path, min_slides: int = 1) -> bool:
    if not folder.is_dir():
        return False
    meta = folder / "meta.json"
    if not meta.is_file():
        return False
    slides = list(folder.glob("*.jpg")) + list(folder.glob("*.jpeg")) + list(folder.glob("*.webp"))
    numbered = [p for p in slides if p.stem.isdigit()]
    return len(numbered) >= min_slides


def find_post_folder(post_id: str) -> Optional[Path]:
    """Find existing folder by exact id name or meta.post_id."""
    direct = OUT_DIR / post_id
    if direct.is_dir():
        return direct
    for p in OUT_DIR.iterdir():
        if not p.is_dir() or p.name.startswith("_"):
            continue
        meta_path = p / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(meta.get("post_id") or "") == str(post_id):
            return p
    return None


def slugify_title(desc: str, max_len: int = 48) -> str:
    text = re.sub(r"https?://\S+", "", desc or "")
    text = re.sub(r"\s+", " ", text).strip()
    # captions that are only hashtags → use tag words
    plain = re.sub(r"#\w+", "", text).strip(" -_|")
    if len(plain) < 3:
        tags = re.findall(r"#(\w+)", desc or "")
        text = " ".join(tags[:5]) if tags else "carousel"
    else:
        text = plain
    # strip emoji / non-filename-friendly symbols, keep letters/digits/_-
    text = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "", text)
    text = re.sub(r"[^\w\s\-]+", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"_+", "_", text).strip("._")
    if len(text) > max_len:
        text = text[:max_len].rstrip("_")
    return text or "carousel"


def fmt_count(n: int) -> str:
    n = int(n or 0)
    if n >= 1_000_000:
        s = f"{n/1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}M"
    if n >= 1_000:
        s = f"{n/1_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}K"
    return str(n)


def make_folder_name(meta: dict[str, Any], post_id: str) -> str:
    author = str((meta.get("author") or {}).get("unique_id") or "unknown")
    author = re.sub(r'[<>:"/\\|?*\s]+', "_", author).strip("._") or "unknown"
    title = slugify_title(str(meta.get("desc") or ""))
    metrics = meta.get("metrics") or {}
    saves = fmt_count(metrics.get("saves") or 0)
    views = fmt_count(metrics.get("views") or 0)
    short = post_id[-8:] if len(post_id) >= 8 else post_id
    name = f"@{author}_{title}_{saves}saves_{views}views_{short}"
    # Windows MAX_PATH safety for folder component
    if len(name) > 120:
        title = slugify_title(str(meta.get("desc") or ""), max_len=28)
        name = f"@{author}_{title}_{saves}saves_{views}views_{short}"
    return name


def unique_folder_path(desired: Path) -> Path:
    if not desired.exists():
        return desired
    # same post already there
    meta_path = desired / "meta.json"
    if meta_path.is_file():
        return desired
    i = 2
    while True:
        alt = desired.with_name(f"{desired.name}_{i}")
        if not alt.exists():
            return alt
        i += 1


def rename_post_folder(folder: Path, meta: dict[str, Any], post_id: str) -> Path:
    """Rename folder to @author_title_saves_views_id8 and update meta.folder."""
    target = unique_folder_path(OUT_DIR / make_folder_name(meta, post_id))
    if folder.resolve() != target.resolve():
        if target.exists():
            # collision with different content — keep numeric suffix path
            target = unique_folder_path(OUT_DIR / (make_folder_name(meta, post_id) + "_x"))
        folder.rename(target)
        folder = target
    meta["folder_name"] = folder.name
    meta["folder"] = str(folder.relative_to(ROOT)).replace("\\", "/")
    (folder / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return folder


def deep_find_item_structs(obj: Any, out: list[dict] | None = None) -> list[dict]:
    if out is None:
        out = []
    if isinstance(obj, dict):
        # typical itemStruct
        if "id" in obj and ("imagePost" in obj or "video" in obj) and "author" in obj:
            out.append(obj)
        if "itemStruct" in obj and isinstance(obj["itemStruct"], dict):
            out.append(obj["itemStruct"])
        for v in obj.values():
            deep_find_item_structs(v, out)
    elif isinstance(obj, list):
        for v in obj:
            deep_find_item_structs(v, out)
    return out


def extract_images_from_item(item: dict) -> list[str]:
    urls: list[str] = []
    image_post = item.get("imagePost") or {}
    images = image_post.get("images") or item.get("images") or []
    for img in images:
        if not isinstance(img, dict):
            continue
        # imageURL.urlList  OR  imageURL: [..]  OR  urlList
        candidates: list[Any] = []
        image_url = img.get("imageURL") or img.get("imageUrl") or {}
        if isinstance(image_url, dict):
            candidates.extend(image_url.get("urlList") or image_url.get("url_list") or [])
        elif isinstance(image_url, list):
            candidates.extend(image_url)
        candidates.extend(img.get("urlList") or img.get("url_list") or [])
        if img.get("url"):
            candidates.append(img["url"])
        for u in candidates:
            if isinstance(u, str) and u.startswith("http"):
                urls.append(u)
                break  # one best url per slide
    # dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def extract_meta_from_item(item: dict, post_url: str) -> dict[str, Any]:
    author = item.get("author") or {}
    stats = item.get("stats") or item.get("statsV2") or {}
    # statsV2 values sometimes strings
    def num(key_variants: list[str]) -> int:
        for k in key_variants:
            v = stats.get(k)
            if v is None:
                continue
            try:
                return int(float(str(v).replace(",", "")))
            except (TypeError, ValueError):
                continue
        return 0

    return {
        "post_id": str(item.get("id") or ""),
        "url": post_url,
        "author": {
            "unique_id": author.get("uniqueId") or author.get("unique_id") or "",
            "nickname": author.get("nickname") or "",
            "id": str(author.get("id") or ""),
        },
        "desc": item.get("desc") or item.get("description") or "",
        "create_time": item.get("createTime") or item.get("create_time"),
        "metrics": {
            "views": num(["playCount", "play_count", "play"]),
            "likes": num(["diggCount", "digg_count", "digg"]),
            "saves": num(["collectCount", "collect_count", "collect"]),
            "shares": num(["shareCount", "share_count", "share"]),
            "comments": num(["commentCount", "comment_count", "comment"]),
        },
        "is_photo": bool(item.get("imagePost") or item.get("images")),
        "scraped_at": utc_now(),
    }


def parse_universal_data(html: str) -> Optional[dict]:
    # <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">...</script>
    m = re.search(
        r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        html,
        re.S | re.I,
    )
    if not m:
        # SIGI_STATE fallback (older)
        m = re.search(
            r'<script[^>]+id="SIGI_STATE"[^>]*>(.*?)</script>',
            html,
            re.S | re.I,
        )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def pick_item_for_post(data: dict, post_id: str) -> Optional[dict]:
    structs = deep_find_item_structs(data)
    for it in structs:
        if str(it.get("id") or "") == str(post_id):
            return it
    return structs[0] if structs else None


# ---------------------------------------------------------------------------
# Stage 1 — collect URLs from collection page
# ---------------------------------------------------------------------------

def collect_post_urls_from_page(page) -> list[tuple[str, str]]:
    """Return ordered unique list of (url, post_id)."""
    hrefs = page.eval_on_selector_all(
        'a[href*="/video/"], a[href*="/photo/"]',
        "els => els.map(e => e.href || e.getAttribute('href') || '')",
    )
    # TikTok sometimes keeps ids only in data attributes / nested links
    extra = page.evaluate(
        """() => {
          const out = [];
          for (const a of document.querySelectorAll('a[href]')) {
            const h = a.href || '';
            if (h.includes('/video/') || h.includes('/photo/')) out.push(h);
          }
          // card wrappers
          for (const el of document.querySelectorAll('[href*="/video/"], [href*="/photo/"]')) {
            const h = el.getAttribute('href') || '';
            if (h) out.push(h);
          }
          return out;
        }"""
    )
    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href in list(hrefs or []) + list(extra or []):
        norm = normalize_post_url(href)
        if not norm:
            continue
        url, pid = norm
        if pid in seen:
            continue
        seen.add(pid)
        ordered.append((url, pid))
    return ordered


def read_collection_total(page) -> Optional[int]:
    """Try to read '87 posts' style counter from the collection header."""
    try:
        text = page.inner_text("body")
    except Exception:
        return None
    # prefer explicit collection counters near top of page text
    patterns = [
        r"(\d+)\s*posts?\b",
        r"(\d+)\s*videos?\b",
        r"(\d+)\s*items?\b",
        r"(\d+)\s*видео\b",
        r"(\d+)\s*публикац",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 5000:
                return n
    return None


def scroll_collection(
    page,
    max_idle_rounds: int = 18,
    max_scrolls: int = 600,
    expected_total: Optional[int] = None,
) -> list[tuple[str, str]]:
    print("[1/2] Открываю коллекцию и скроллю до конца…")
    if expected_total is None:
        expected_total = read_collection_total(page)
    if expected_total:
        print(f"  счётчик на странице: ~{expected_total}")

    last_count = 0
    idle = 0
    stable_at_bottom = 0
    for i in range(1, max_scrolls + 1):
        posts = collect_post_urls_from_page(page)
        count = len(posts)
        tip = f"/{expected_total}" if expected_total else ""
        print(f"\r  скролл {i}: найдено постов={count}{tip}", end="", flush=True)

        # scroll to absolute bottom (lazy grids often need this)
        page.evaluate(
            """() => {
              const se = document.scrollingElement || document.documentElement;
              window.scrollTo(0, se.scrollHeight);
              // also nudge inner feed containers
              for (const el of document.querySelectorAll('div')) {
                try {
                  if (el.scrollHeight > el.clientHeight + 200 && el.clientHeight > 300) {
                    el.scrollTop = el.scrollHeight;
                  }
                } catch (e) {}
              }
            }"""
        )
        page.wait_for_timeout(random.randint(900, 1600))

        try:
            btn = page.locator(
                'button:has-text("Load more"), button:has-text("Загрузить ещё"), '
                '[data-e2e="load-more"], [class*="LoadMore"]'
            )
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=2000)
                page.wait_for_timeout(1500)
        except Exception:
            pass

        if expected_total and count >= expected_total:
            # confirm with a couple more scrolls
            stable_at_bottom += 1
            if stable_at_bottom >= 3:
                break
        else:
            stable_at_bottom = 0

        if count == last_count:
            idle += 1
        else:
            idle = 0
            last_count = count

        # if we know target and still short, don't stop on short idle
        if idle >= max_idle_rounds:
            if expected_total and count < expected_total:
                # one more aggressive wait cycle before giving up
                if idle >= max_idle_rounds + 10:
                    print(f"\n  ! остановились на {count} из ~{expected_total}")
                    break
            else:
                break

    page.wait_for_timeout(2000)
    # jump top→bottom once more to force reflow
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(800)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1500)

    posts = collect_post_urls_from_page(page)
    print(f"\n[1/2] Итого уникальных постов: {len(posts)}"
          + (f" (ожидали ~{expected_total})" if expected_total else ""))
    return posts


def harvest_urls_from_responses(buffer: list[str], body: str) -> None:
    """Pull post urls/ids from JSON API bodies into buffer list of raw strings."""
    if not body or len(body) < 20:
        return
    for m in POST_HREF_RE.finditer(body):
        buffer.append(m.group(0))
    for m in POST_PATH_RE.finditer(body):
        buffer.append(m.group(0))
    # structured collection / item list payloads
    try:
        data = json.loads(body)
    except Exception:
        return
    harvest_items_from_obj(data, buffer)


def harvest_items_from_obj(obj: Any, buffer: list[str]) -> None:
    """Walk JSON and reconstruct /@user/photo|video/id links when possible."""
    if isinstance(obj, dict):
        item_id = obj.get("id") or obj.get("aweme_id") or obj.get("awemeId")
        author = obj.get("author") or {}
        unique = ""
        if isinstance(author, dict):
            unique = author.get("uniqueId") or author.get("unique_id") or ""
        if item_id and unique:
            is_photo = bool(
                obj.get("imagePost")
                or obj.get("image_post_info")
                or obj.get("imagePostInfo")
                or (obj.get("contentType") == "photo")
            )
            kind = "photo" if is_photo else "video"
            # if image list present under alternate keys
            if not is_photo and (obj.get("images") or obj.get("image_list")):
                kind = "photo"
            buffer.append(f"https://www.tiktok.com/@{unique}/{kind}/{item_id}")
        for v in obj.values():
            harvest_items_from_obj(v, buffer)
    elif isinstance(obj, list):
        for v in obj:
            harvest_items_from_obj(v, buffer)


def filter_photos_only(posts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    photos = [(u, pid) for u, pid in posts if "/photo/" in u]
    videos = len(posts) - len(photos)
    if videos:
        print(f"[filter] пропускаю {videos} видео — остаются {len(photos)} photo-каруселей")
    return photos

# ---------------------------------------------------------------------------
# Stage 2 — download each post
# ---------------------------------------------------------------------------

def download_bytes(client: httpx.Client, url: str) -> Optional[bytes]:
    last_err = None
    for cand in url_variants(url):
        try:
            r = client.get(cand)
            if r.status_code >= 400:
                last_err = f"http_{r.status_code}"
                continue
            if len(r.content) < 400:
                last_err = f"too_small:{len(r.content)}"
                continue
            return r.content
        except Exception as e:
            last_err = str(e)
            continue
    if last_err:
        print(f"    ! download fail: {last_err}")
    return None


def scrape_post_page(page, post_url: str, post_id: str) -> Optional[dict]:
    """Open post page and return itemStruct dict."""
    intercepted: list[dict] = []

    def on_response(resp) -> None:
        try:
            ct = (resp.headers.get("content-type") or "").lower()
            url = resp.url
            if "application/json" not in ct and "javascript" not in ct and "json" not in ct:
                # still try item/detail endpoints
                if not any(x in url for x in ("item", "detail", "aweme", "post")):
                    return
            body = resp.text()
            if not body or "imagePost" not in body and '"id"' not in body:
                # cheap filter
                if post_id not in body:
                    return
            data = json.loads(body)
            for it in deep_find_item_structs(data):
                if str(it.get("id") or "") == post_id:
                    intercepted.append(it)
        except Exception:
            return

    page.on("response", on_response)
    try:
        page.goto(post_url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(1800)
        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:
            pass

        html = page.content()
        data = parse_universal_data(html)
        if data:
            item = pick_item_for_post(data, post_id)
            if item:
                return item

        if intercepted:
            return intercepted[-1]

        # JS fallback: dig window.__UNIVERSAL_DATA_FOR_REHYDRATION__
        item = page.evaluate(
            """(pid) => {
              const u = window.__UNIVERSAL_DATA_FOR_REHYDRATION__;
              if (!u) return null;
              const stack = [u];
              while (stack.length) {
                const cur = stack.pop();
                if (!cur || typeof cur !== 'object') continue;
                if (cur.id && String(cur.id) === String(pid) && (cur.imagePost || cur.video)) return cur;
                if (cur.itemStruct && String(cur.itemStruct.id) === String(pid)) return cur.itemStruct;
                for (const v of Object.values(cur)) {
                  if (v && typeof v === 'object') stack.push(v);
                }
              }
              return null;
            }""",
            post_id,
        )
        return item
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass


def process_post(
    page,
    client: httpx.Client,
    post_url: str,
    post_id: str,
    index: int,
    total: int,
) -> str:
    existing = find_post_folder(post_id)
    if existing and already_downloaded(existing):
        # ensure nice name even for previously downloaded id-folders
        try:
            meta = json.loads((existing / "meta.json").read_text(encoding="utf-8"))
            rename_post_folder(existing, meta, post_id)
        except Exception:
            pass
        print(f"Карусель {index} / {total}: {post_id} — уже скачано, пропускаю")
        return "skip"

    print(f"Карусель {index} / {total}: открываю {post_url}")
    item = scrape_post_page(page, post_url, post_id)
    if not item:
        print(f"  ! не удалось извлечь itemStruct для {post_id}")
        return "fail_parse"

    image_urls = extract_images_from_item(item)
    meta = extract_meta_from_item(item, post_url)
    meta["slide_urls"] = image_urls
    meta["slide_count"] = len(image_urls)

    if not image_urls:
        # Shouldn't happen for /photo/ — treat as fail, don't keep empty video stubs
        print(f"Карусель {index} / {total}: нет слайдов imagePost — пропуск")
        return "no_images"

    # download into temp id folder, then rename to titled folder
    folder = existing or (OUT_DIR / post_id)
    folder.mkdir(parents=True, exist_ok=True)
    ok = 0
    for i, img_url in enumerate(image_urls, 1):
        data = download_bytes(client, img_url)
        if not data:
            print(f"  ! слайд {i} не скачался")
            continue
        dest = folder / f"{i}.jpg"
        try:
            save_as_jpg(data, dest)
            ok += 1
        except Exception as e:
            print(f"  ! слайд {i} convert/save: {e}")
            dest.write_bytes(data)

        print(
            f"\rКарусель {index} / {total}: скачано {ok} слайдов…",
            end="",
            flush=True,
        )

    print()
    meta["downloaded_slides"] = ok
    if ok == 0:
        (folder / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return "fail_download"

    folder = rename_post_folder(folder, meta, post_id)
    print(
        f"Карусель {index} / {total}: готово — {ok}/{len(image_urls)} слайдов → {folder.name}/"
    )
    return "ok"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Download TikTok collection photo posts")
    ap.add_argument("--url", default=DEFAULT_COLLECTION_URL, help="Collection URL")
    ap.add_argument(
        "--out",
        default="curated_collection",
        help="Output folder under project root (default: curated_collection)",
    )
    ap.add_argument("--headed", action="store_true", help="Show browser window")
    ap.add_argument("--headless", action="store_true", help="Force headless (default: headed)")
    ap.add_argument("--limit", type=int, default=None, help="Max posts to download")
    ap.add_argument("--skip-collect", action="store_true", help="Reuse _collection_urls.json")
    ap.add_argument(
        "--include-videos",
        action="store_true",
        help="Also process /video/ posts (default: only /photo/ carousels)",
    )
    ap.add_argument("--expect", type=int, default=None, help="Expected total posts in collection (e.g. 87)")
    ap.add_argument("--pause-min", type=float, default=1.0)
    ap.add_argument("--pause-max", type=float, default=2.0)
    args = ap.parse_args()

    headed = True
    if args.headless:
        headed = False
    if args.headed:
        headed = True

    set_out_dir(args.out)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    posts: list[tuple[str, str]] = []

    with sync_playwright() as p:
        print(f"[browser] persistent session → {SESSION_DIR}")
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=not headed,
            viewport={"width": 1440, "height": 960},
            locale="en-US",
            user_agent=UA,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()

        # Stage 1
        if args.skip_collect and URLS_CHECKPOINT.is_file():
            raw = json.loads(URLS_CHECKPOINT.read_text(encoding="utf-8"))
            for row in raw.get("posts") or []:
                posts.append((row["url"], row["post_id"]))
            print(f"[1/2] Загружено из чекпоинта: {len(posts)} постов")
        else:
            api_bits: list[str] = []

            def on_coll_resp(resp) -> None:
                try:
                    url = resp.url
                    if "tiktok.com" not in url:
                        return
                    if resp.status != 200:
                        return
                    ct = (resp.headers.get("content-type") or "").lower()
                    if "json" in ct or "api" in url or "item" in url or "collection" in url:
                        harvest_urls_from_responses(api_bits, resp.text())
                except Exception:
                    return

            page.on("response", on_coll_resp)
            page.goto(args.url, wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_timeout(2500)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass

            posts = scroll_collection(page, expected_total=args.expect)
            # merge API-found urls
            for raw_u in api_bits:
                norm = normalize_post_url(raw_u)
                if not norm:
                    continue
                if all(pid != norm[1] for _, pid in posts):
                    posts.append(norm)

            try:
                page.remove_listener("response", on_coll_resp)
            except Exception:
                pass

            URLS_CHECKPOINT.write_text(
                json.dumps(
                    {
                        "collection_url": args.url,
                        "scraped_at": utc_now(),
                        "count": len(posts),
                        "photo_count": sum(1 for u, _ in posts if "/photo/" in u),
                        "video_count": sum(1 for u, _ in posts if "/video/" in u),
                        "posts": [{"url": u, "post_id": pid} for u, pid in posts],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"[1/2] Чекпоинт → {URLS_CHECKPOINT}")

        if not args.include_videos:
            posts = filter_photos_only(posts)

        if args.limit is not None:
            posts = posts[: args.limit]

        if not posts:
            print("Посты не найдены. Войди в TikTok в .browser_session и повтори.")
            context.close()
            return 1

        # Stage 2
        print(f"[2/2] Скачиваю {len(posts)} постов → {OUT_DIR}")
        headers = {
            "User-Agent": UA,
            "Referer": "https://www.tiktok.com/",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        stats = {"ok": 0, "skip": 0, "fail": 0, "no_images": 0}

        with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
            for i, (post_url, post_id) in enumerate(posts, 1):
                try:
                    status = process_post(page, client, post_url, post_id, i, len(posts))
                except Exception as e:
                    print(f"  ! ошибка поста {post_id}: {e}")
                    status = "fail"
                if status == "ok":
                    stats["ok"] += 1
                elif status == "skip":
                    stats["skip"] += 1
                elif status == "no_images":
                    stats["no_images"] += 1
                else:
                    stats["fail"] += 1

                if i < len(posts) and status != "skip":
                    pause = random.uniform(args.pause_min, args.pause_max)
                    time.sleep(pause)

        context.close()

    print("=" * 60)
    print(
        f"Готово: ok={stats['ok']} skip={stats['skip']} "
        f"no_images={stats['no_images']} fail={stats['fail']}"
    )
    print(f"Папка: {OUT_DIR}")
    print("=" * 60)
    return 0 if stats["fail"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
