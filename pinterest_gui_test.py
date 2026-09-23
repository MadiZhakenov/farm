#!/usr/bin/env python3
"""
Pinterest GUI Test — живой поиск картинок (Tkinter + Pillow + httpx).

Запуск:
  python pinterest_gui_test.py
"""

from __future__ import annotations

import io
import json
import re
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, quote_plus

import httpx
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

DEFAULT_QUERY = "cozy coffee desk aesthetic"
PREVIEW_W = 180
PREVIEW_H = 240  # 3:4
COLS = 4
CARD_PAD = 10
CARD_W = PREVIEW_W + 16
CARD_H = PREVIEW_H + 42
DOWNLOAD_WORKERS = 12
AI_CHECK_WORKERS = 10
MAX_PINS = 40
AI_SOURCE_TYPE = 11

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

HTML_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.pinterest.com/",
    "Upgrade-Insecure-Requests": "1",
}

CDN_HEADERS = {
    "User-Agent": CHROME_UA,
    "Referer": "https://www.pinterest.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

API_HEADERS_BASE = {
    "User-Agent": CHROME_UA,
    "Accept": "application/json, text/javascript, */*, q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "X-Pinterest-AppState": "active",
    "Origin": "https://www.pinterest.com",
    "Content-Type": "application/x-www-form-urlencoded",
}

PLACEHOLDER_COLOR = "#2b2b2b"
BG = "#1e1e1e"
PANEL_BG = "#2a2a2a"
FG = "#f0f0f0"
ACCENT = "#2ecc71"
ACCENT_DARK = "#27ae60"
BADGE_PHOTO = "#1e8449"
BADGE_AI = "#c0392b"
MUTED = "#9a9a9a"


# ---------------------------------------------------------------------------
# Данные
# ---------------------------------------------------------------------------

@dataclass
class PinItem:
    pin_id: str
    title: str
    image_url: str
    orig_url: str
    is_ai: bool | None = None  # None = ещё не проверено
    photo: ImageTk.PhotoImage | None = field(default=None, repr=False)
    error: str | None = None


# ---------------------------------------------------------------------------
# Сеть: поиск + ИИ + превью
# ---------------------------------------------------------------------------

def _normalize_html(html: str) -> str:
    return (
        html.replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\/", "/")
    )


def _pick_image_url(images: dict[str, Any] | None) -> tuple[str, str]:
    """Возвращает (preview_736x_or_best, originals_or_best)."""
    if not isinstance(images, dict):
        return "", ""
    order_preview = ("736x", "564x", "474x", "236x", "orig", "originals")
    order_orig = ("orig", "originals", "736x", "564x", "474x")

    def url_of(key: str) -> str:
        node = images.get(key)
        if isinstance(node, dict):
            return str(node.get("url") or "")
        if isinstance(node, str):
            return node
        return ""

    preview = next((url_of(k) for k in order_preview if url_of(k)), "")
    orig = next((url_of(k) for k in order_orig if url_of(k)), preview)
    # upgrade size segment if only smaller found
    if preview and "/originals/" in preview:
        preview = preview.replace("/originals/", "/736x/")
    return preview, orig


def _walk_collect_pins(obj: Any, out: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > 28 or len(out) >= MAX_PINS * 2:
        return
    if isinstance(obj, dict):
        pid = obj.get("id") or obj.get("entityId")
        images = obj.get("images")
        if pid and isinstance(images, dict):
            out.append(obj)
        for v in obj.values():
            _walk_collect_pins(v, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj[:100]:
            _walk_collect_pins(item, out, depth + 1)


def _pin_from_obj(obj: dict[str, Any]) -> PinItem | None:
    pid = str(obj.get("id") or obj.get("entityId") or "").strip()
    if not re.fullmatch(r"\d{6,20}", pid):
        return None
    preview, orig = _pick_image_url(obj.get("images"))
    if not preview:
        # иногда url лежит плоско
        for key in ("image_large_url", "image_medium_url", "image_square_url"):
            if obj.get(key):
                preview = str(obj[key])
                orig = preview
                break
    if not preview or "pinimg.com" not in preview:
        return None
    title = (
        obj.get("title")
        or obj.get("grid_title")
        or obj.get("gridTitle")
        or obj.get("description")
        or ""
    )
    title = re.sub(r"\s+", " ", str(title)).strip()[:80]
    dmst = obj.get("digitalMediaSourceType")
    if dmst is None:
        dmst = obj.get("digital_media_source_type")
    topics = obj.get("genAiTopics") or obj.get("gen_ai_topics")
    is_ai = None
    if dmst == AI_SOURCE_TYPE or dmst == str(AI_SOURCE_TYPE):
        is_ai = True
    elif isinstance(topics, list) and len(topics) > 0:
        is_ai = True
    return PinItem(
        pin_id=pid,
        title=title or f"pin {pid}",
        image_url=preview,
        orig_url=orig or preview,
        is_ai=is_ai,
    )


def _dedupe_pins(items: list[PinItem]) -> list[PinItem]:
    seen: set[str] = set()
    out: list[PinItem] = []
    for p in items:
        if p.pin_id in seen:
            continue
        seen.add(p.pin_id)
        out.append(p)
        if len(out) >= MAX_PINS:
            break
    return out


def _extract_from_pws_html(html: str) -> list[PinItem]:
    html = _normalize_html(html)
    items: list[PinItem] = []
    for sid in ("__PWS_DATA__", "__PWS_INITIAL_PROPS__"):
        m = re.search(
            rf'<script[^>]+id=["\']{re.escape(sid)}["\'][^>]*>(.*?)</script>',
            html,
            re.I | re.S,
        )
        if not m:
            continue
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        raw: list[dict[str, Any]] = []
        _walk_collect_pins(data, raw)
        for obj in raw:
            pin = _pin_from_obj(obj)
            if pin:
                items.append(pin)
    # regex fallback: pinimg URLs
    if len(items) < 8:
        urls = re.findall(
            r"https://i\.pinimg\.com/(?:736x|originals|474x)/"
            r"([0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{32}\.(?:jpg|jpeg|png|webp))",
            html,
            re.I,
        )
        for i, path in enumerate(dict.fromkeys(urls)):
            preview = f"https://i.pinimg.com/736x/{path}"
            orig = f"https://i.pinimg.com/originals/{path}"
            items.append(
                PinItem(
                    pin_id=f"img{i:03d}",
                    title=path.split("/")[-1][:24],
                    image_url=preview,
                    orig_url=orig,
                )
            )
    return _dedupe_pins(items)


class PinterestClient:
    def __init__(self) -> None:
        self._client = httpx.Client(timeout=httpx.Timeout(25.0), follow_redirects=True)
        self._csrf = ""

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def warm(self) -> None:
        self._client.get("https://www.pinterest.com/", headers=HTML_HEADERS)
        self._csrf = self._client.cookies.get("csrftoken") or ""

    def _api_headers(self, referer: str) -> dict[str, str]:
        h = dict(API_HEADERS_BASE)
        h["Referer"] = referer
        if self._csrf:
            h["X-CSRFToken"] = self._csrf
        return h

    def search(self, query: str) -> list[PinItem]:
        q = query.strip() or DEFAULT_QUERY
        source = f"/search/pins/?q={quote_plus(q)}"
        page_url = f"https://www.pinterest.com{source}"

        # 1) HTML (cookies + возможный PWS)
        page = self._client.get(page_url, headers=HTML_HEADERS)
        self._csrf = self._client.cookies.get("csrftoken") or self._csrf
        html_pins = _extract_from_pws_html(page.text)

        # 2) BaseSearchResource POST (основной источник)
        data = {
            "options": {
                "query": q,
                "scope": "pins",
                "page_size": min(MAX_PINS, 25),
                "bookmarks": [],
            },
            "context": {},
        }
        api_pins: list[PinItem] = []
        try:
            resp = self._client.post(
                "https://www.pinterest.com/resource/BaseSearchResource/get/",
                headers=self._api_headers(page_url),
                data={
                    "source_url": source,
                    "data": json.dumps(data, separators=(",", ":")),
                },
            )
            if resp.status_code == 200 and resp.content[:1] == b"{":
                raw: list[dict[str, Any]] = []
                _walk_collect_pins(resp.json(), raw)
                for obj in raw:
                    pin = _pin_from_obj(obj)
                    if pin:
                        api_pins.append(pin)
        except httpx.HTTPError:
            pass

        merged = _dedupe_pins(api_pins + html_pins)
        return merged

    def check_ai(self, pin_id: str) -> bool:
        """True если пин помечен как GenAI (digital_media_source_type == 11)."""
        if not re.fullmatch(r"\d{6,20}", pin_id):
            return False
        source = f"/pin/{pin_id}/"
        data = {
            "options": {
                "id": pin_id,
                "field_set_key": "detailed_with_board",
            },
            "context": {},
        }
        try:
            resp = self._client.post(
                "https://www.pinterest.com/resource/PinResource/get/",
                headers=self._api_headers(f"https://www.pinterest.com{source}"),
                data={
                    "source_url": source,
                    "data": json.dumps(data, separators=(",", ":")),
                },
            )
            if resp.status_code != 200 or resp.content[:1] != b"{":
                return False
            pin = resp.json().get("resource_response", {}).get("data") or {}
            dmst = pin.get("digital_media_source_type")
            if dmst is None:
                dmst = pin.get("digitalMediaSourceType")
            topics = pin.get("genAiTopics") or pin.get("gen_ai_topics")
            if dmst == AI_SOURCE_TYPE or dmst == str(AI_SOURCE_TYPE):
                return True
            if isinstance(topics, list) and len(topics) > 0:
                return True
            # fallback: сырой текст ответа
            text = resp.text
            if re.search(r'"digital_media_source_type"\s*:\s*11\b', text):
                return True
            if re.search(r'"digitalMediaSourceType"\s*:\s*11\b', text):
                return True
            if re.search(r'"genAiTopics"\s*:\s*\[\s*\{', text):
                return True
        except httpx.HTTPError:
            return False
        return False

    def download_preview(self, url: str) -> Image.Image | None:
        try:
            resp = self._client.get(url, headers=CDN_HEADERS, timeout=10.0)
            if resp.status_code != 200 or not resp.content:
                # план Б: 736x ↔ originals
                alt = url
                if "/originals/" in url:
                    alt = url.replace("/originals/", "/736x/")
                elif "/736x/" in url:
                    alt = url.replace("/736x/", "/474x/")
                if alt != url:
                    resp = self._client.get(alt, headers=CDN_HEADERS, timeout=10.0)
            if resp.status_code != 200 or not resp.content:
                return None
            img = Image.open(io.BytesIO(resp.content))
            img = img.convert("RGB")
            # cover 3:4
            tw, th = PREVIEW_W, PREVIEW_H
            scale = max(tw / img.width, th / img.height)
            nw, nh = max(1, int(img.width * scale)), max(1, int(img.height * scale))
            img = img.resize((nw, nh), Image.Resampling.LANCZOS)
            left = (nw - tw) // 2
            top = (nh - th) // 2
            img = img.crop((left, top, left + tw, top + th))
            return img
        except Exception:
            return None


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class PlaceholderEntry(tk.Entry):
    """Обычный tk.Entry — корректно принимает кириллицу на Windows (в отличие от ttk.Entry)."""

    def __init__(self, master: tk.Misc, placeholder: str, **kwargs: Any) -> None:
        kwargs.setdefault("font", ("Segoe UI", 11))
        kwargs.setdefault("bg", "#333333")
        kwargs.setdefault("fg", FG)
        kwargs.setdefault("insertbackground", FG)
        kwargs.setdefault("relief", tk.FLAT)
        kwargs.setdefault("highlightthickness", 1)
        kwargs.setdefault("highlightbackground", "#444444")
        kwargs.setdefault("highlightcolor", ACCENT)
        kwargs.setdefault("insertwidth", 2)
        super().__init__(master, **kwargs)
        self.placeholder = placeholder
        self._has_placeholder = False
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<KeyPress>", self._on_key)
        self.bind("<<Paste>>", self._on_paste)
        self._add_placeholder()

    def _on_focus_in(self, _event: object | None = None) -> None:
        if self._has_placeholder:
            self.delete(0, tk.END)
            self._has_placeholder = False
            self.configure(fg=FG)

    def _on_focus_out(self, _event: object | None = None) -> None:
        if not self.get().strip():
            self._add_placeholder()

    def _on_key(self, _event: object | None = None) -> None:
        # Срабатывает и для кириллицы / IME
        if self._has_placeholder:
            self.delete(0, tk.END)
            self._has_placeholder = False
            self.configure(fg=FG)

    def _on_paste(self, _event: object | None = None) -> None:
        if self._has_placeholder:
            self.delete(0, tk.END)
            self._has_placeholder = False
            self.configure(fg=FG)

    def _add_placeholder(self) -> None:
        if not self.get():
            self.insert(0, self.placeholder)
            self._has_placeholder = True
            self.configure(fg=MUTED)

    def real_value(self) -> str:
        if self._has_placeholder:
            return self.placeholder
        value = self.get().strip()
        return value or self.placeholder


class PinterestGuiApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Pinterest GUI Test — живой поиск")
        self.root.geometry("860x720")
        self.root.minsize(720, 560)
        self.root.configure(bg=BG)

        self.client = PinterestClient()
        self._search_lock = threading.Lock()
        self._busy = False
        self._pins: list[PinItem] = []
        self._photo_refs: list[ImageTk.PhotoImage] = []  # GC guard
        self._card_widgets: list[tk.Frame] = []

        self._build_style()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # прогрев сессии в фоне
        threading.Thread(target=self._warm_session, daemon=True).start()

    def _build_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL_BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Panel.TLabel", background=PANEL_BG, foreground=FG)
        style.configure("Status.TLabel", background=PANEL_BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("TCheckbutton", background=PANEL_BG, foreground=FG)
        style.map("TCheckbutton", background=[("active", PANEL_BG)])
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#102010",
            font=("Segoe UI", 10, "bold"),
            padding=(16, 6),
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_DARK), ("disabled", "#555")],
        )

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, style="Panel.TFrame", padding=(12, 10))
        top.pack(fill=tk.X)

        row = ttk.Frame(top, style="Panel.TFrame")
        row.pack(fill=tk.X)

        self.query_entry = PlaceholderEntry(
            row,
            placeholder=DEFAULT_QUERY,
            width=48,
        )
        self.query_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), ipady=4)
        self.query_entry.bind("<Return>", lambda _e: self.start_search())

        self.search_btn = tk.Button(
            row,
            text="Найти",
            bg=ACCENT,
            fg="#102010",
            activebackground=ACCENT_DARK,
            activeforeground="#102010",
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=18,
            pady=6,
            cursor="hand2",
            command=self.start_search,
        )
        self.search_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.filter_ai = tk.BooleanVar(value=True)
        self.ai_chk = ttk.Checkbutton(
            row,
            text="Отсекать ИИ",
            variable=self.filter_ai,
        )
        self.ai_chk.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Готов к поиску")
        ttk.Label(top, textvariable=self.status_var, style="Status.TLabel").pack(
            anchor=tk.W, pady=(8, 0)
        )

        # scrollable canvas
        body = ttk.Frame(self.root, style="TFrame")
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.grid_frame = tk.Frame(self.canvas, bg=BG)
        self._canvas_window = self.canvas.create_window(
            (0, 0), window=self.grid_frame, anchor="nw"
        )

        self.grid_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_frame_configure(self, _event: object | None = None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self.canvas.itemconfigure(self._canvas_window, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_var.set(text))

    def _set_busy(self, busy: bool) -> None:
        def apply() -> None:
            self._busy = busy
            state = tk.DISABLED if busy else tk.NORMAL
            self.search_btn.configure(state=state)

        self.root.after(0, apply)

    def _warm_session(self) -> None:
        try:
            self.client.warm()
            self._set_status("Готов к поиску")
        except Exception as exc:
            self._set_status(f"Сессия: предупреждение ({exc.__class__.__name__})")

    def start_search(self) -> None:
        if self._busy:
            return
        query = self.query_entry.real_value()
        filter_ai = bool(self.filter_ai.get())
        self._set_busy(True)
        self._set_status(f"Ищем и качаем ({DOWNLOAD_WORKERS} потоков)…")
        self.root.after(0, self._clear_grid)
        threading.Thread(
            target=self._search_worker,
            args=(query, filter_ai),
            daemon=True,
        ).start()

    def _clear_grid(self) -> None:
        for w in self._card_widgets:
            w.destroy()
        self._card_widgets.clear()
        self._photo_refs.clear()
        self._pins.clear()

    def _search_worker(self, query: str, filter_ai: bool) -> None:
        t0 = time.perf_counter()
        ai_rejected = 0
        try:
            with self._search_lock:
                pins = self.client.search(query)
        except Exception as exc:
            self._set_status(f"Ошибка поиска: {exc}")
            self._set_busy(False)
            return

        if not pins:
            elapsed = time.perf_counter() - t0
            self._set_status(f"Ничего не найдено | Время: {elapsed:.1f} с")
            self._set_busy(False)
            return

        # AI-проверка (если нужно пометить или отсеять)
        need_ai_check = [p for p in pins if p.is_ai is None]
        if need_ai_check:
            self._set_status(
                f"Проверка ИИ-меток ({len(need_ai_check)} пинов)…"
            )

            def check_one(p: PinItem) -> tuple[str, bool]:
                return p.pin_id, self.client.check_ai(p.pin_id)

            with ThreadPoolExecutor(max_workers=AI_CHECK_WORKERS) as pool:
                futures = {pool.submit(check_one, p): p for p in need_ai_check}
                for fut in as_completed(futures):
                    try:
                        pid, is_ai = fut.result()
                    except Exception:
                        continue
                    for p in pins:
                        if p.pin_id == pid:
                            p.is_ai = is_ai
                            break

        kept: list[PinItem] = []
        for p in pins:
            if p.is_ai is True and filter_ai:
                ai_rejected += 1
                continue
            if p.is_ai is None:
                p.is_ai = False
            kept.append(p)

        if not kept:
            elapsed = time.perf_counter() - t0
            self._set_status(
                f"Найдено: 0 | Отсеяно ИИ: {ai_rejected} | Время: {elapsed:.1f} с"
            )
            self._set_busy(False)
            return

        self._set_status(
            f"Ищем и качаем ({DOWNLOAD_WORKERS} потоков)… "
            f"пинов: {len(kept)}"
        )

        # параллельная загрузка превью в RAM
        previews: dict[str, Image.Image] = {}

        def dl(p: PinItem) -> tuple[str, Image.Image | None]:
            return p.pin_id, self.client.download_preview(p.image_url)

        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
            futs = [pool.submit(dl, p) for p in kept]
            for fut in as_completed(futs):
                try:
                    pid, img = fut.result()
                except Exception:
                    continue
                if img is not None:
                    previews[pid] = img

        elapsed = time.perf_counter() - t0
        self.root.after(
            0,
            lambda: self._render_results(kept, previews, ai_rejected, elapsed),
        )

    def _render_results(
        self,
        pins: list[PinItem],
        previews: dict[str, Image.Image],
        ai_rejected: int,
        elapsed: float,
    ) -> None:
        self._clear_grid()
        self._pins = pins

        for idx, pin in enumerate(pins):
            row, col = divmod(idx, COLS)
            card = self._make_card(pin, previews.get(pin.pin_id))
            card.grid(
                row=row,
                column=col,
                padx=CARD_PAD // 2,
                pady=CARD_PAD // 2,
                sticky="n",
            )
            self._card_widgets.append(card)

        shown = len(pins)
        self.status_var.set(
            f"Найдено: {shown} | Отсеяно ИИ: {ai_rejected} | Время: {elapsed:.1f} с"
        )
        self._set_busy(False)
        self.canvas.yview_moveto(0)

    def _make_card(self, pin: PinItem, image: Image.Image | None) -> tk.Frame:
        card = tk.Frame(
            self.grid_frame,
            bg=PANEL_BG,
            width=CARD_W,
            height=CARD_H,
            highlightthickness=1,
            highlightbackground="#3a3a3a",
            cursor="hand2",
        )
        card.grid_propagate(False)

        img_label = tk.Label(card, bg=PLACEHOLDER_COLOR, width=PREVIEW_W, height=PREVIEW_H)
        img_label.pack(padx=8, pady=(8, 4))

        if image is not None:
            photo = ImageTk.PhotoImage(image)
            self._photo_refs.append(photo)
            pin.photo = photo
            img_label.configure(image=photo, width=PREVIEW_W, height=PREVIEW_H)
        else:
            img_label.configure(
                text="нет\nпревью",
                fg=MUTED,
                font=("Segoe UI", 9),
                width=22,
                height=12,
            )

        is_ai = bool(pin.is_ai)
        badge_text = "⚠ ИИ" if is_ai else "Фото"
        badge_bg = BADGE_AI if is_ai else BADGE_PHOTO

        meta = tk.Frame(card, bg=PANEL_BG)
        meta.pack(fill=tk.X, padx=8, pady=(0, 8))

        id_lbl = tk.Label(
            meta,
            text=pin.pin_id[:14],
            bg=PANEL_BG,
            fg=MUTED,
            font=("Consolas", 8),
            anchor="w",
        )
        id_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        badge = tk.Label(
            meta,
            text=badge_text,
            bg=badge_bg,
            fg="white",
            font=("Segoe UI", 8, "bold"),
            padx=6,
            pady=1,
        )
        badge.pack(side=tk.RIGHT)

        def open_pin(_event: object | None = None, p: PinItem = pin) -> None:
            # оригинал картинки; если pin_id настоящий — можно и страницу пина
            url = p.orig_url or p.image_url
            if re.fullmatch(r"\d{6,20}", p.pin_id):
                # по ТЗ — оригинал картинки
                url = p.orig_url or p.image_url
            webbrowser.open(url)

        for w in (card, img_label, id_lbl, badge, meta):
            w.bind("<Button-1>", open_pin)

        return card

    def _on_close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    PinterestGuiApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
