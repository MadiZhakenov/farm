#!/usr/bin/env python3
"""
Вкладка «Библиотека фото» — галерея approved + перманентный blacklist.

Оптимизации:
  - пагинация (PAGE_SIZE карточек, не все 1000+)
  - блок без полной перерисовки страницы
  - debounce поиска
  - лёгкие превью (BILINEAR, без лишнего canvas)
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from typing import Callable

from PIL import Image, ImageTk

from core.photo_vault import PhotoVault, get_photo_vault

BG = "#1a1b1e"
PANEL = "#24262b"
PANEL2 = "#2c2f36"
FG = "#f2f2f2"
MUTED = "#9aa0a6"
ACCENT = "#3ddc97"
DANGER = "#e85d5d"
BORDER = "#3a3f48"
CARD_BG = "#2a2d34"

# Крупные превью 3:4 — реально видно содержимое
THUMB_W = 168
THUMB_H = 224
COLS = 5
PAGE_SIZE = 20  # 4 ряда × 5 колонок
SEARCH_DEBOUNCE_MS = 350


class PhotoLibraryPanel(tk.Frame):
    """Пагинированная сетка одобренных фото с кнопками Блок / Оставить."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_status: Callable[[str], None] | None = None,
        vault: PhotoVault | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(master, bg=BG, **kwargs)  # type: ignore[arg-type]
        self._on_status = on_status or (lambda _s: None)
        self.vault = vault or get_photo_vault()
        self._photo_refs: list[ImageTk.PhotoImage] = []
        self._card_frames: dict[str, tk.Frame] = {}
        self._page_photos: list[dict] = []
        self._search_var = tk.StringVar()
        self._stats_var = tk.StringVar(
            value="В библиотеке: 0 | В черном списке: 0"
        )
        self._page_var = tk.StringVar(value="стр 1 / 1")
        self._page = 0
        self._total = 0
        self._search_after: str | None = None
        self._build()

    def _build(self) -> None:
        top = tk.Frame(self, bg=PANEL, height=56)
        top.pack(fill=tk.X)
        top.pack_propagate(False)

        tk.Label(
            top,
            text="🖼️ Библиотека фото",
            bg=PANEL,
            fg=FG,
            font=("Segoe UI", 12, "bold"),
        ).pack(side=tk.LEFT, padx=14, pady=12)

        self._stats_lbl = tk.Label(
            top,
            textvariable=self._stats_var,
            bg=PANEL,
            fg=ACCENT,
            font=("Segoe UI", 9, "bold"),
        )
        self._stats_lbl.pack(side=tk.LEFT, padx=(8, 14), pady=12)

        tk.Button(
            top,
            text="Обновить",
            command=self.refresh,
            bg=PANEL2,
            fg=FG,
            activebackground=BORDER,
            activeforeground=FG,
            relief=tk.FLAT,
            padx=10,
            pady=4,
            font=("Segoe UI", 9),
            cursor="hand2",
        ).pack(side=tk.RIGHT, padx=(0, 14), pady=10)

        tk.Button(
            top,
            text="📥 Импорт из out/",
            command=self._import_from_out,
            bg="#1e3a2f",
            fg=ACCENT,
            activebackground="#2a5a45",
            activeforeground=ACCENT,
            relief=tk.FLAT,
            padx=10,
            pady=4,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        ).pack(side=tk.RIGHT, padx=(0, 8), pady=10)

        tk.Button(
            top,
            text="🔍 Крупные превью",
            command=self._regen_thumbs,
            bg=PANEL2,
            fg=FG,
            activebackground=BORDER,
            activeforeground=FG,
            relief=tk.FLAT,
            padx=10,
            pady=4,
            font=("Segoe UI", 9),
            cursor="hand2",
        ).pack(side=tk.RIGHT, padx=(0, 8), pady=10)

        search = tk.Entry(
            top,
            textvariable=self._search_var,
            font=("Segoe UI", 10),
            bg="#1e2025",
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            width=28,
        )
        search.pack(side=tk.RIGHT, padx=8, pady=12, ipady=4)
        search.bind("<KeyRelease>", self._on_search_key)
        tk.Label(
            top,
            text="Поиск:",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(side=tk.RIGHT, pady=12)

        # pager bar
        pager = tk.Frame(self, bg=PANEL2, height=36)
        pager.pack(fill=tk.X)
        pager.pack_propagate(False)

        tk.Button(
            pager,
            text="◀ Назад",
            command=self._prev_page,
            bg=PANEL,
            fg=FG,
            relief=tk.FLAT,
            padx=10,
            font=("Segoe UI", 9),
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(14, 6), pady=4)

        tk.Label(
            pager,
            textvariable=self._page_var,
            bg=PANEL2,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, pady=4)

        tk.Button(
            pager,
            text="Вперёд ▶",
            command=self._next_page,
            bg=PANEL,
            fg=FG,
            relief=tk.FLAT,
            padx=10,
            font=("Segoe UI", 9),
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=6, pady=4)

        # scrollable canvas (только текущая страница — короткий скролл)
        body = tk.Frame(self, bg=BG)
        body.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(body, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._grid = tk.Frame(self._canvas, bg=BG)
        self._win = self._canvas.create_window(
            (0, 0), window=self._grid, anchor="nw"
        )
        self._grid.bind(
            "<Configure>",
            lambda _e: self._canvas.configure(
                scrollregion=self._canvas.bbox("all")
            ),
        )
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        # только когда курсор над панелью — не bind_all
        self._canvas.bind("<Enter>", self._bind_wheel)
        self._canvas.bind("<Leave>", self._unbind_wheel)

    def _bind_wheel(self, _event: object | None = None) -> None:
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_wheel(self, _event: object | None = None) -> None:
        self._canvas.unbind_all("<MouseWheel>")

    def _on_canvas_configure(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self._canvas.itemconfigure(self._win, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        if not self.winfo_ismapped():
            return
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_search_key(self, _event: object | None = None) -> None:
        if self._search_after is not None:
            try:
                self.after_cancel(self._search_after)
            except Exception:
                pass
        self._search_after = self.after(SEARCH_DEBOUNCE_MS, self._search_go)

    def _search_go(self) -> None:
        self._search_after = None
        self._page = 0
        self._render_page()

    def _pages_total(self) -> int:
        return max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)

    def _prev_page(self) -> None:
        if self._page <= 0:
            return
        self._page -= 1
        self._render_page()

    def _next_page(self) -> None:
        if self._page + 1 >= self._pages_total():
            return
        self._page += 1
        self._render_page()

    def _import_from_out(self) -> None:
        self._on_status("Импорт фото из out/…")

        def work() -> None:
            try:
                stats = self.vault.import_from_exports()
            except Exception as exc:
                self.after(0, lambda: self._on_status(f"Импорт fail: {exc}"))
                return

            def done() -> None:
                self.refresh()
                self._on_status(
                    f"Импорт: +{stats['added']} фото "
                    f"(пропущено {stats['skipped']}, "
                    f"каруселей {stats['scanned']})"
                )

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _regen_thumbs(self) -> None:
        self._on_status("Пересборка крупных превью из out/…")

        def work() -> None:
            try:
                stats = self.vault.regenerate_thumbs_from_exports()
            except Exception as exc:
                self.after(0, lambda: self._on_status(f"Превью fail: {exc}"))
                return

            def done() -> None:
                self.refresh()
                self._on_status(
                    f"Превью обновлены: {stats['updated']} "
                    f"(нет исходника: {stats['missing']})"
                )

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _update_stats(self) -> None:
        st = self.vault.stats()
        self._stats_var.set(
            f"В библиотеке: {st['approved']} | "
            f"В черном списке: {st['blacklisted']}"
        )

    def _update_page_label(self) -> None:
        self._page_var.set(
            f"стр {self._page + 1} / {self._pages_total()}  ·  "
            f"{self._total} фото"
        )

    def refresh(self) -> None:
        """Полная перезагрузка текущей страницы (кнопка Обновить)."""
        self._page = min(self._page, max(0, self._pages_total() - 1))
        self._render_page()

    def _clear_grid(self) -> None:
        for child in list(self._grid.winfo_children()):
            child.destroy()
        self._photo_refs.clear()
        self._card_frames.clear()
        self._page_photos = []

    def _render_page(self) -> None:
        """Нарисовать только PAGE_SIZE карточек."""
        search = self._search_var.get().strip()
        self._total = self.vault.count_approved(search=search)
        pages = self._pages_total()
        if self._page >= pages:
            self._page = max(0, pages - 1)

        self._update_stats()
        self._update_page_label()
        self._clear_grid()

        photos = self.vault.get_approved_photos(
            search=search,
            limit=PAGE_SIZE,
            offset=self._page * PAGE_SIZE,
        )
        self._page_photos = photos

        if not photos:
            tk.Label(
                self._grid,
                text=(
                    "Ничего не найдено."
                    if search
                    else "Библиотека пуста — экспортни карусель "
                    "или нажми «Импорт из out/»."
                ),
                bg=BG,
                fg=MUTED,
                font=("Segoe UI", 10),
            ).grid(row=0, column=0, padx=24, pady=40, sticky="w")
            self._canvas.yview_moveto(0)
            return

        for i, photo in enumerate(photos):
            r, c = divmod(i, COLS)
            card = self._make_card(photo)
            card.grid(row=r, column=c, padx=8, pady=10, sticky="n")
            self._card_frames[str(photo["pin_id"])] = card

        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._canvas.yview_moveto(0)

    def _load_thumb(self, path: str) -> ImageTk.PhotoImage | None:
        """Cover-crop ровно под THUMB_W×THUMB_H — без пустых полей."""
        if not path:
            return None
        p = Path(path)
        if not p.is_file():
            return None
        try:
            img = Image.open(p).convert("RGB")
            tw, th = THUMB_W, THUMB_H
            # scale to cover
            scale = max(tw / max(img.width, 1), th / max(img.height, 1))
            nw = max(tw, int(round(img.width * scale)))
            nh = max(th, int(round(img.height * scale)))
            img = img.resize((nw, nh), Image.Resampling.BILINEAR)
            left = (nw - tw) // 2
            top = (nh - th) // 2
            img = img.crop((left, top, left + tw, top + th))
            ph = ImageTk.PhotoImage(img)
            self._photo_refs.append(ph)
            return ph
        except Exception:
            return None

    def _make_card(self, photo: dict) -> tk.Frame:
        pid = str(photo.get("pin_id") or "")
        card = tk.Frame(
            self._grid,
            bg=CARD_BG,
            highlightthickness=1,
            highlightbackground=BORDER,
            width=THUMB_W + 16,
        )

        thumb_holder = tk.Frame(
            card, bg=CARD_BG, width=THUMB_W, height=THUMB_H
        )
        thumb_holder.pack(padx=8, pady=(8, 4))
        thumb_holder.pack_propagate(False)

        ph = self._load_thumb(str(photo.get("thumb_abs") or ""))
        if ph is not None:
            lbl = tk.Label(thumb_holder, image=ph, bg=CARD_BG)
            lbl.image = ph  # type: ignore[attr-defined]
            lbl.pack(fill=tk.BOTH, expand=True)
        else:
            tk.Label(
                thumb_holder,
                text="нет\nпревью",
                bg="#1e2025",
                fg=MUTED,
                font=("Segoe UI", 8),
            ).pack(fill=tk.BOTH, expand=True)

        q = str(photo.get("query") or "")[:28]
        tk.Label(
            card,
            text=q or pid[:14],
            bg=CARD_BG,
            fg=MUTED,
            font=("Segoe UI", 7),
            wraplength=THUMB_W,
            justify=tk.CENTER,
        ).pack(padx=4)

        btns = tk.Frame(card, bg=CARD_BG)
        btns.pack(fill=tk.X, padx=4, pady=(2, 8))

        tk.Button(
            btns,
            text="🚫 Блок",
            command=lambda p=pid: self._on_block(p),
            bg="#3a2222",
            fg=DANGER,
            activebackground="#5a3030",
            activeforeground="#ffb0b0",
            relief=tk.FLAT,
            font=("Segoe UI", 8, "bold"),
            padx=4,
            pady=2,
            cursor="hand2",
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))

        tk.Button(
            btns,
            text="✅ Оставить",
            command=lambda p=pid: self._on_keep(p),
            bg="#1e3a2f",
            fg=ACCENT,
            activebackground="#2a5a45",
            activeforeground=ACCENT,
            relief=tk.FLAT,
            font=("Segoe UI", 8, "bold"),
            padx=4,
            pady=2,
            cursor="hand2",
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

        return card

    def _reflow_page_cards(self) -> None:
        """Переставить оставшиеся карточки в сетке без пересоздания."""
        alive = [
            self._card_frames[str(p["pin_id"])]
            for p in self._page_photos
            if str(p["pin_id"]) in self._card_frames
        ]
        for i, card in enumerate(alive):
            r, c = divmod(i, COLS)
            card.grid(row=r, column=c, padx=8, pady=10, sticky="n")
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_block(self, pin_id: str) -> None:
        ok = self.vault.blacklist_pin(pin_id)
        if not ok:
            self._on_status(f"Не удалось заблокировать {pin_id}")
            return

        card = self._card_frames.pop(pin_id, None)
        if card is not None:
            try:
                card.destroy()
            except Exception:
                pass
        self._page_photos = [
            p for p in self._page_photos if str(p.get("pin_id")) != pin_id
        ]
        self._total = max(0, self._total - 1)
        self._update_stats()
        self._update_page_label()
        self._reflow_page_cards()
        self._on_status(f"🚫 Пин {pin_id} → чёрный список")

        # если страница опустела — подтянуть следующую / предыдущую
        if not self._page_photos and self._total > 0:
            if self._page >= self._pages_total():
                self._page = max(0, self._pages_total() - 1)
            self._render_page()

    def _on_keep(self, pin_id: str) -> None:
        if self.vault.set_status(pin_id, "approved"):
            self._on_status(f"✅ Пин {pin_id} оставлен в библиотеке")
        else:
            self._on_status(f"Пин {pin_id}: нет записи в библиотеке")
        self._update_stats()
