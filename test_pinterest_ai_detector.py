#!/usr/bin/env python3
"""
Поиск и реверс-инжиниринг встроенных меток ИИ на Pinterest.

Цель: найти точные JSON-ключи / CSS-селекторы бейджа
«AI modified» / «Created with AI» / GenAI для фильтра в AdsPower.

Запуск:
  python test_pinterest_ai_detector.py
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

INBOX_DIR = Path("inbox")
TARGET_PINS = 8
REQUEST_TIMEOUT = 25.0

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.pinterest.com/",
    "Upgrade-Insecure-Requests": "1",
}

# Известные публичные pin_id (включая подтверждённый AI-бейдж)
SEED_PIN_IDS: list[str] = [
    "340936634317338069",  # подтверждён: AI modified + digitalMediaSourceType=11
    "158259374379943925",
    "9922061675589894",
    "26388347813800004",
    "260505159692582028",
    "899664463056209065",
    "34832597116688634",
    "151855818681651786",
    "2111131073949384",
    "10062799164698488",
]

SEARCH_QUERIES = [
    "3D fantasy interior AI",
    "cyberpunk room",
    "AI portrait",
    "AI generated art",
]

# Ключи / паттерны, которые ищем в JSON-дереве
AI_KEY_HINTS = (
    "is_gen_ai",
    "gen_ai",
    "genai",
    "ai_modified",
    "ai_generated",
    "aigenerated",
    "aimodified",
    "created_with_ai",
    "disclosure_type",
    "digitalmediasourcetype",
    "genaitopics",
    "synthetic",
    "ai_disclosure",
)

AI_TEXT_PATTERNS = (
    "AI modified",
    "Created with AI",
    "Show fewer AI Pins",
    "AI-generated",
    "Made with AI",
)
# «GenAI» / «AI generated» слишком шумные (эксперименты, имена полей) — не используем как DOM-сигнал

# Эмпирически подтверждено этим скриптом / forensics:
# digitalMediaSourceType == 11  ↔  бейдж «AI modified»
CONFIRMED_AI_SOURCE_TYPE = 11
CONFIRMED_DOM_SELECTOR = '[data-test-id="ai-generated-label"]'


# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------

@dataclass
class JsonHit:
    path: str
    key: str
    value_preview: str


@dataclass
class DomHit:
    selector: str
    text: str
    classes: str
    data_attrs: dict[str, str] = field(default_factory=dict)


@dataclass
class PinAnalysis:
    pin_id: str
    url: str
    http_status: int | None = None
    has_og_image: bool = False
    is_ai: bool = False
    signals: list[str] = field(default_factory=list)
    json_hits: list[JsonHit] = field(default_factory=list)
    dom_hits: list[DomHit] = field(default_factory=list)
    digital_media_source_type: int | None | str = None
    gen_ai_topics: Any = None
    best_key: str = "—"
    best_selector: str = "—"
    error: str | None = None


# ---------------------------------------------------------------------------
# Inbox / выборка pin_id
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


def _normalize_pin_id(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if re.fullmatch(r"\d{8,20}", s):
        return s
    m = re.search(r"/pin/(\d{8,20})", s)
    return m.group(1) if m else None


def load_pin_ids_from_inbox(limit: int = TARGET_PINS) -> list[str]:
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
            for key in ("pin_id", "id", "pinId", "pin", "pin_url", "url", "link"):
                _walk_collect(row, key, bucket)
            for val in bucket:
                pid = _normalize_pin_id(val)
                if pid and pid not in seen:
                    seen.add(pid)
                    found.append(pid)
                if len(found) >= limit:
                    return found
    return found


def normalize_html(html: str) -> str:
    return (
        html.replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\/", "/")
        .replace("\\u003c", "<")
        .replace("\\u003e", ">")
        .replace("\\u0022", '"')
    )


def extract_pin_ids_from_html(html: str) -> list[str]:
    html = normalize_html(html)
    ids: list[str] = []
    for pat in (
        r"/pin/(\d{10,20})",
        r'"id"\s*:\s*"(\d{14,20})"',
        r"(?<!\d)(\d{15,19})(?!\d)",
    ):
        for m in re.findall(pat, html):
            if m not in ids:
                ids.append(m)
    return ids


def prepare_pin_ids(client: httpx.Client) -> tuple[list[str], str]:
    inbox = load_pin_ids_from_inbox(TARGET_PINS)
    collected: list[str] = []
    seen: set[str] = set()

    def add(pid: str | None) -> None:
        if pid and pid not in seen:
            seen.add(pid)
            collected.append(pid)

    for pid in inbox:
        add(pid)
    for pid in SEED_PIN_IDS:
        add(pid)

    # добираем с поисковых страниц (AI-запросы)
    for q in SEARCH_QUERIES:
        if len(collected) >= TARGET_PINS + 6:
            break
        url = f"https://www.pinterest.com/search/pins/?q={quote_plus(q)}"
        try:
            r = client.get(url)
            for pid in extract_pin_ids_from_html(r.text):
                add(pid)
                if len(collected) >= TARGET_PINS + 10:
                    break
        except httpx.HTTPError:
            continue

    source = f"inbox={len(inbox)}, seeds+search → pool={len(collected)}"
    return collected, source


# ---------------------------------------------------------------------------
# Парсинг PWS / DOM
# ---------------------------------------------------------------------------

def extract_script_json(html: str, script_id: str) -> Any | None:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id=script_id)
    if not tag or not tag.string:
        # fallback regex (иногда tree ломается на огромных страницах)
        m = re.search(
            rf'<script[^>]+id=["\']{re.escape(script_id)}["\'][^>]*>(.*?)</script>',
            html,
            re.I | re.S,
        )
        if not m:
            return None
        raw = m.group(1).strip()
    else:
        raw = tag.string.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _preview(value: Any, limit: int = 160) -> str:
    if isinstance(value, (dict, list)):
        try:
            s = json.dumps(value, ensure_ascii=False)
        except TypeError:
            s = str(value)
    else:
        s = str(value)
    s = re.sub(r"\s+", " ", s)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def walk_ai_json(obj: Any, path: str = "$", out: list[JsonHit] | None = None, depth: int = 0) -> list[JsonHit]:
    if out is None:
        out = []
    if depth > 28 or len(out) > 80:
        return out

    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            kl = str(k).lower()
            interesting_key = any(h in kl for h in AI_KEY_HINTS)
            # отсекаем A/B experiment flags (*genai*_exp) — это не метка контента пина
            if interesting_key and ("_exp" in kl or "experiment" in kl):
                interesting_key = False
            interesting_val = False
            if isinstance(v, str):
                vl = v.lower()
                if "exp" in kl or "experiment" in path.lower():
                    interesting_val = False
                else:
                    interesting_val = any(h in vl for h in AI_KEY_HINTS) or any(
                        t.lower() in vl for t in AI_TEXT_PATTERNS
                    )
            elif isinstance(v, (int, float)) and "digitalmediasource" in kl:
                interesting_key = True
            if interesting_key or interesting_val:
                out.append(JsonHit(path=p, key=str(k), value_preview=_preview(v)))
            if isinstance(v, (dict, list)):
                walk_ai_json(v, p, out, depth + 1)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if i > 60:
                break
            walk_ai_json(item, f"{path}[{i}]", out, depth + 1)
    return out


def extract_field_from_html(html: str, field: str) -> list[str]:
    """Достаёт значения поля даже если они вне корневого PWS (дубли в SSR)."""
    return re.findall(rf'"{re.escape(field)}"\s*:\s*(null|\d+|true|false|\[[^\[\]]*\])', html)


def parse_digital_media_source_type(html: str) -> int | None | str:
    vals = extract_field_from_html(html, "digitalMediaSourceType")
    if not vals:
        return None
    # предпочитаем числовой 11, если есть
    uniq = list(dict.fromkeys(vals))
    for v in uniq:
        if v.isdigit():
            return int(v)
    if "null" in uniq:
        return None
    return uniq[0]


def parse_gen_ai_topics(html: str) -> Any:
    # сначала короткий массив / null
    m = re.search(r'"genAiTopics"\s*:\s*(null|\[(?:[^\[\]]|\[(?:[^\[\]])*\])*\])', html)
    if not m:
        return None
    raw = m.group(1)
    if raw == "null":
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def analyze_dom(html: str) -> list[DomHit]:
    soup = BeautifulSoup(html, "html.parser")
    hits: list[DomHit] = []

    # 1) стабильный data-test-id (главный селектор)
    for el in soup.select(CONFIRMED_DOM_SELECTOR):
        hits.append(
            DomHit(
                selector=CONFIRMED_DOM_SELECTOR,
                text=(el.get_text(" ", strip=True) or el.get("title") or "")[:80],
                classes=" ".join(el.get("class", [])),
                data_attrs={
                    k: v for k, v in el.attrs.items() if k.startswith("data-") or k == "title"
                },
            )
        )

    # 2) текстовые плашки
    for text in AI_TEXT_PATTERNS:
        for el in soup.find_all(string=re.compile(re.escape(text), re.I)):
            parent = el.parent
            if parent is None:
                continue
            classes = " ".join(parent.get("class", [])) if hasattr(parent, "get") else ""
            # подняться к ближайшему с data-test-id
            node = parent
            selector = None
            data_attrs: dict[str, str] = {}
            for _ in range(5):
                if node is None or not hasattr(node, "get"):
                    break
                tid = node.get("data-test-id")
                if tid:
                    selector = f'[data-test-id="{tid}"]'
                    data_attrs = {
                        k: str(v)
                        for k, v in node.attrs.items()
                        if k.startswith("data-") or k in {"title", "aria-label"}
                    }
                    classes = " ".join(node.get("class", []))
                    break
                node = node.parent
            if selector is None:
                # CSS по классам родителя (хрупко — только как доп. сигнал)
                if classes:
                    selector = "." + ".".join(classes.split()[:3])
                else:
                    selector = f'//*[contains(text(),"{text}")]'
            hit = DomHit(
                selector=selector,
                text=text,
                classes=classes,
                data_attrs=data_attrs,
            )
            # дедуп
            if not any(h.selector == hit.selector and h.text == hit.text for h in hits):
                hits.append(hit)

    return hits


def analyze_pin(client: httpx.Client, pin_id: str) -> PinAnalysis:
    url = f"https://www.pinterest.com/pin/{pin_id}/"
    result = PinAnalysis(pin_id=pin_id, url=url)
    try:
        resp = client.get(url)
    except httpx.HTTPError as exc:
        result.error = f"http_error:{exc.__class__.__name__}"
        return result

    result.http_status = resp.status_code
    html = normalize_html(resp.text)
    result.has_og_image = bool(
        re.search(r'<meta[^>]+property=["\']og:image["\']', html, re.I)
    )

    # JSON деревья
    for sid in ("__PWS_DATA__", "__PWS_INITIAL_PROPS__"):
        data = extract_script_json(html, sid)
        if data is not None:
            result.json_hits.extend(walk_ai_json(data, path=f"${sid}"))

    # Надёжные поля из SSR (даже если walk по дереву их пропустил из-за структуры)
    dmst = parse_digital_media_source_type(html)
    topics = parse_gen_ai_topics(html)
    result.digital_media_source_type = dmst
    result.gen_ai_topics = topics

    if dmst == CONFIRMED_AI_SOURCE_TYPE:
        result.signals.append(f"digitalMediaSourceType={dmst}")
        result.json_hits.insert(
            0,
            JsonHit(
                path="$.pin.digitalMediaSourceType",
                key="digitalMediaSourceType",
                value_preview=str(dmst),
            ),
        )
    if isinstance(topics, list) and len(topics) > 0:
        result.signals.append("genAiTopics=[...]")
        result.json_hits.insert(
            0,
            JsonHit(
                path="$.pin.genAiTopics",
                key="genAiTopics",
                value_preview=_preview(topics),
            ),
        )

    # DOM
    result.dom_hits = analyze_dom(html)
    if any(h.selector == CONFIRMED_DOM_SELECTOR for h in result.dom_hits):
        result.signals.append(CONFIRMED_DOM_SELECTOR)
    for h in result.dom_hits:
        if h.text and h.text not in result.signals:
            # не дублируем длинные селекторы в signals
            if h.text.lower() in {t.lower() for t in AI_TEXT_PATTERNS}:
                result.signals.append(f'text:"{h.text}"')

    # Вердикт
    result.is_ai = bool(
        dmst == CONFIRMED_AI_SOURCE_TYPE
        or (isinstance(topics, list) and len(topics) > 0)
        or any(h.selector == CONFIRMED_DOM_SELECTOR for h in result.dom_hits)
    )

    if result.is_ai:
        result.best_key = (
            f"digitalMediaSourceType == {CONFIRMED_AI_SOURCE_TYPE}"
            if dmst == CONFIRMED_AI_SOURCE_TYPE
            else "genAiTopics (non-empty array)"
        )
        result.best_selector = CONFIRMED_DOM_SELECTOR
    else:
        result.best_key = (
            f"digitalMediaSourceType={dmst!r}, genAiTopics={_preview(topics, 40)}"
        )
        result.best_selector = "—"

    return result


# ---------------------------------------------------------------------------
# Отчёт + сниппеты для AdsPower
# ---------------------------------------------------------------------------

def print_adspower_snippets() -> None:
    print()
    print("  ГОТОВЫЕ ПРОВЕРКИ ДЛЯ AdsPower / парсера")
    print("  " + "-" * 68)
    print(
        """
  # Python (httpx + JSON/HTML пина или карточки в ленте)
  import re

  def is_pinterest_ai_pin(html_or_json: str) -> bool:
      if 'data-test-id="ai-generated-label"' in html_or_json:
          return True
      if re.search(r'"digitalMediaSourceType"\\s*:\\s*11\\b', html_or_json):
          return True
      if re.search(r'"genAiTopics"\\s*:\\s*\\[\\s*\\{', html_or_json):
          return True
      return False
  # True  → скипать пин (AI)
  # False → оставлять
""".rstrip()
    )
    print()
    print(
        """
  // JavaScript (AdsPower / Puppeteer / расширение) — фильтр при скролле ленты
  function isPinterestAiPin(root = document) {
    // 1) видимый бейдж на карточке / closeup
    if (root.querySelector('[data-test-id="ai-generated-label"]')) return true;
    // 2) запасной текстовый сигнал
    const t = (root.innerText || '');
    if (/\\bAI modified\\b/i.test(t) || /\\bCreated with AI\\b/i.test(t)) return true;
    return false;
  }

  // пример: выкинуть AI-карточки из сетки
  document.querySelectorAll('[data-test-id="pin"], [data-test-id="pinWrapper"]').forEach(card => {
    if (isPinterestAiPin(card)) card.remove(); // или card.style.display = 'none'
  });
""".rstrip()
    )
    print()
    print(
        "  JSON-ключ (API/SSR):  pin.digitalMediaSourceType === 11\n"
        "  JSON-ключ (доп.):     Array.isArray(pin.genAiTopics) && pin.genAiTopics.length > 0\n"
        "  CSS-селектор:         [data-test-id=\"ai-generated-label\"]"
    )


def print_report(results: list[PinAnalysis], pool_source: str) -> None:
    line = "=" * 78
    ai_count = sum(1 for r in results if r.is_ai)
    print()
    print(line)
    print("  Pinterest AI Detector — реверс меток GenAI")
    print(line)
    print(f"  Источник pin_id : {pool_source}")
    print(f"  Проверено       : {len(results)}")
    print(f"  С меткой ИИ     : {ai_count}")
    print()
    print("  ТАБЛИЦА")
    print("  " + "-" * 74)
    print(
        f"  {'PIN ID':<22} {'AI?':<6} {'Ключ / селектор'}"
    )
    print(f"  {'-'*22} {'-'*6} {'-'*44}")
    for r in results:
        mark = "ДА" if r.is_ai else "нет"
        detail = r.best_selector if r.is_ai else r.best_key
        if r.is_ai:
            detail = f"{r.best_key}  |  {r.best_selector}"
        if r.error:
            detail = r.error
        print(f"  {r.pin_id:<22} {mark:<6} {detail}")

    print()
    print("  ДЕТАЛИ ПО СИГНАЛАМ")
    print("  " + "-" * 74)
    for r in results:
        print(f"  · {r.pin_id}  og={r.has_og_image}  status={r.http_status}")
        print(
            f"      digitalMediaSourceType={r.digital_media_source_type!r}  "
            f"genAiTopics={_preview(r.gen_ai_topics, 70)}"
        )
        if r.signals:
            print(f"      signals: {', '.join(dict.fromkeys(r.signals))}")
        if r.dom_hits:
            h = r.dom_hits[0]
            print(
                f"      DOM: {h.selector}  text={h.text!r}  "
                f"data={h.data_attrs}"
            )
        for jh in r.json_hits[:3]:
            print(f"      JSON: {jh.key} = {jh.value_preview}  ({jh.path})")

    print()
    print("  ВЫВОД РЕВЕРСА")
    print("  " + "-" * 74)
    print(
        f"  Надёжный маркер ИИ: digitalMediaSourceType == {CONFIRMED_AI_SOURCE_TYPE}"
    )
    print("  Доп. маркер:        genAiTopics — непустой массив GenAIInterestData")
    print(f"  DOM-бейдж:          {CONFIRMED_DOM_SELECTOR}  (текст «AI modified»)")
    print(
        "  Хрупко:             хеш-классы (ADXRXN, BVzdUh…) — не использовать в проде"
    )

    print_adspower_snippets()
    print()
    print(line)
    print()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("Pinterest AI Detector — подготовка выборки…")
    results: list[PinAnalysis] = []

    with httpx.Client(
        headers=HEADERS,
        timeout=httpx.Timeout(REQUEST_TIMEOUT),
        follow_redirects=True,
    ) as client:
        pool, source = prepare_pin_ids(client)
        print(f"  пул кандидатов: {len(pool)} ({source})")

        # анализируем, пока не наберём TARGET_PINS валидных (с og:image) или пул кончится
        for pid in pool:
            print(f"  analyze {pid} …", flush=True)
            analysis = analyze_pin(client, pid)
            if analysis.error:
                print(f"    ! {analysis.error}")
                continue
            # пропускаем совсем пустые soft-404 без og и без полей
            if not analysis.has_og_image and analysis.digital_media_source_type is None:
                print("    skip (нет og:image / не пин)")
                continue
            results.append(analysis)
            mark = "AI" if analysis.is_ai else "ok"
            print(
                f"    → {mark}  dmst={analysis.digital_media_source_type!r}  "
                f"label={any(h.selector == CONFIRMED_DOM_SELECTOR for h in analysis.dom_hits)}"
            )
            if len(results) >= TARGET_PINS:
                break

    if not results:
        print("Не удалось проанализировать ни одного пина.")
        return 2

    print_report(results, source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
