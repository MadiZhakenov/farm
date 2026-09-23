#!/usr/bin/env python3
"""
Pixabay Music Downloader — скачивает royalty-free музыку без логина.

Как это работает:
  - Официальный Pixabay API поддерживает только фото и видео, НЕ музыку.
  - Страницы /music/ за Cloudflare — обычный requests получает 403.
  - Playwright открывает страницу поиска, достаёт track-объекты из React props.
  - MP3 лежат на cdn.pixabay.com — их можно качать напрямую без авторизации.

Примеры:
  python pixabay-music.py search lofi --limit 5
  python pixabay-music.py search chill --pages 2 --out output/music
  python pixabay-music.py search --genre Lofi --mood Calm --limit 10
  python pixabay-music.py download https://pixabay.com/music/lofi-lofi-lofi-music-587176/
  python pixabay-music.py
  python pixabay-music.py --gui
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import quote, urljoin

import httpx

BASE = "https://pixabay.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Достаём track-объекты из React fiber tree (CSS-классы Pixabay часто меняет).
HARVEST_JS = """
() => {
  const seen = new Map();
  const isTrack = (t) => t && typeof t === 'object' && t.sources &&
    typeof t.sources.src === 'string' &&
    t.sources.src.includes('.mp3');

  const roots = [];
  for (const el of document.querySelectorAll('*')) {
    for (const k in el) {
      if (k.startsWith('__reactContainer$')) { roots.push(el[k]); break; }
    }
    if (roots.length) break;
  }
  if (!roots.length) {
    for (const el of document.querySelectorAll('*')) {
      for (const k in el) {
        if (k.startsWith('__reactFiber$')) { roots.push(el[k]); break; }
      }
      if (roots.length >= 40) break;
    }
  }

  const visit = (fiber, depth) => {
    let n = 0;
    while (fiber && n++ < 20000) {
      const p = fiber.memoizedProps;
      if (p && isTrack(p.track) && !seen.has(p.track.id)) seen.set(p.track.id, p.track);
      if (fiber.child) visit(fiber.child, depth + 1);
      fiber = fiber.sibling;
      if (depth === 0) break;
    }
  };
  roots.forEach(r => { try { visit(r, 1); } catch (e) {} });

  return [...seen.values()].map(t => ({
    id: t.id,
    name: t.name,
    href: t.href,
    src: t.sources.src,
    downloadUrl: t.sources.downloadUrl || null,
    filename: t.sources.filename || null,
    duration: t.duration,
    tags: (t.tagList || []).map(x => x[0]),
    likes: t.likeCount,
  }));
}
"""

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUT = SCRIPT_DIR / "output" / "music"

# Все жанры Pixabay Music (фильтр Genre).
PIXABAY_GENRES = [
    "Action",
    "Alternative Hip Hop",
    "Arabic",
    "Beats",
    "Cartoons",
    "Flamenco",
    "France",
    "Funk",
    "Lofi",
    "Metal",
    "Modern Classical",
    "Nostalgia",
    "Old School Hip Hop",
    "Orchestral",
    "Phonk",
    "Pop",
    "Punk",
    "Reggaeton",
    "Salsa",
    "Solo Piano",
]

# Все настроения Pixabay Music (фильтр Mood).
PIXABAY_MOODS = [
    "Euphoric",
    "Happy",
    "Dark",
    "Eccentric",
    "Scary",
    "Sad",
    "Angry",
    "Funny",
    "Weird",
    "Sexy",
    "Emotional",
    "Groovy",
    "Celebration",
    "Chill",
]

# Все movement Pixabay Music (фильтр Movement).
PIXABAY_MOVEMENTS = [
    "Chasing",
    "Elegant",
    "Floating",
    "Smooth",
    "Running",
    "Fast",
    "Medium Fast",
    "Heavy & Ponderous",
    "Slow",
    "Busy & Frantic",
    "Sneaking",
    "Marching",
    "Changing Tempo",
    "Very Fast",
]


def build_search_url(
    query: str | None = None,
    *,
    genre: str | None = None,
    mood: str | None = None,
    movement: str | None = None,
    page: int = 1,
) -> str:
    """Собрать URL страницы поиска Pixabay Music."""
    if genre:
        path = f"/music/search/genre/{quote(genre.title())}/"
    elif mood:
        path = f"/music/search/mood/{quote(mood.title())}/"
    elif movement:
        path = f"/music/search/movement/{quote(movement.title())}/"
    elif query:
        path = f"/music/search/{quote(query.lower().strip())}/"
    else:
        path = "/music/search/"

    url = urljoin(BASE, path)
    if page > 1:
        url += f"?pagi={page}"
    return url


def sanitize_filename(name: str, track_id: int) -> str:
    safe = re.sub(r'[<>:"/\\|?*]+', "_", name).strip(" .")
    safe = re.sub(r"\s+", " ", safe)
    if not safe:
        safe = f"track-{track_id}"
    if not safe.lower().endswith(".mp3"):
        safe += ".mp3"
    return safe


def format_duration(seconds: int | None) -> str:
    if not isinstance(seconds, int):
        return "?"
    return f"{seconds // 60}:{seconds % 60:02d}"


class PixabayMusicScraper:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw = None
        self._browser = None
        self._ctx = None
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled", "--mute-audio"],
        )
        self._ctx = await self._browser.new_context(
            user_agent=UA,
            viewport={"width": 1440, "height": 2200},
            locale="en-US",
        )
        # Блокируем картинки/шрифты/mp3 при скрейпе — быстрее.
        await self._ctx.route(
            re.compile(r"\.(png|jpe?g|gif|webp|svg|woff2?|mp3)($|\?)"),
            lambda route: route.abort(),
        )
        return self

    async def __aexit__(self, *exc):
        for closer in (self._ctx, self._browser):
            if closer:
                await closer.close()
        if self._pw:
            await self._pw.stop()

    async def fetch_page_tracks(self, url: str) -> list[dict]:
        async with self._lock:
            page = await self._ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                try:
                    await page.wait_for_function(
                        "() => document.querySelectorAll('a[href^=\"/music/\"]').length > 3",
                        timeout=20000,
                    )
                except Exception:
                    pass
                await page.wait_for_timeout(600)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(400)
                return await page.evaluate(HARVEST_JS)
            finally:
                await page.close()

    async def search(
        self,
        query: str | None = None,
        *,
        genre: str | None = None,
        mood: str | None = None,
        movement: str | None = None,
        pages: int | None = None,
        limit: int | None = None,
        log=None,
        on_progress=None,
    ) -> list[dict]:
        """pages=None — все страницы, пока Pixabay отдаёт новые треки."""
        merged: dict[int, dict] = {}
        page_num = 1

        while True:
            if pages is not None and page_num > pages:
                break

            url = build_search_url(
                query, genre=genre, mood=mood, movement=movement, page=page_num,
            )
            if log:
                log(f"Страница {page_num}: {url}")
            else:
                print(f"  scrape: {url}")

            batch = await self.fetch_page_tracks(url)
            if not batch:
                break

            new_count = 0
            for i, track in enumerate(batch):
                if track["id"] not in merged:
                    new_count += 1
                track["page"] = page_num
                track["rank"] = (page_num - 1) * 20 + i
                merged.setdefault(track["id"], track)

            if on_progress:
                on_progress(page_num, len(merged))

            if new_count == 0:
                break
            if limit and len(merged) >= limit:
                break

            page_num += 1

        tracks = list(merged.values())
        if limit:
            tracks = tracks[:limit]
        return tracks


async def download_track(
    track: dict,
    out_dir: Path,
    client: httpx.AsyncClient,
    log=None,
) -> Path | None:
    src = track.get("src")
    if not src:
        return None

    filename = track.get("filename") or sanitize_filename(track.get("name", "track"), track["id"])
    dest = out_dir / filename
    if dest.exists() and dest.stat().st_size > 10_000:
        msg = f"Уже есть: {dest.name}"
        if log:
            log(msg)
        else:
            print(f"  skip (exists): {dest.name}")
        return dest

    try:
        resp = await client.get(src, headers={"User-Agent": UA})
        if resp.status_code != 200 or len(resp.content) < 10_000:
            msg = f"Ошибка {track.get('name')}: HTTP {resp.status_code}"
            if log:
                log(msg)
            else:
                print(f"  fail: {track.get('name')} -> HTTP {resp.status_code}")
            return None
        dest.write_bytes(resp.content)
        size_mb = len(resp.content) / (1024 * 1024)
        msg = f"Сохранено: {dest.name} ({size_mb:.1f} MB)"
        if log:
            log(msg)
        else:
            print(f"  saved: {dest.name} ({size_mb:.1f} MB, {track.get('duration', '?')}s)")
        return dest
    except Exception as exc:
        msg = f"Ошибка {track.get('name')}: {exc}"
        if log:
            log(msg)
        else:
            print(f"  error: {track.get('name')}: {exc}")
        return None


async def cmd_search(args: argparse.Namespace) -> int:
    pages = None if args.pages <= 0 else args.pages
    limit = None if args.limit <= 0 else args.limit

    async with PixabayMusicScraper(headless=not args.show_browser) as scraper:
        tracks = await scraper.search(
            args.query,
            genre=args.genre,
            mood=args.mood,
            movement=args.movement,
            pages=pages,
            limit=limit,
        )

    if not tracks:
        print("Треки не найдены.")
        return 1

    print(f"\nНайдено: {len(tracks)}")
    for t in tracks:
        dur = t.get("duration")
        dur_s = f"{dur // 60}:{dur % 60:02d}" if isinstance(dur, int) else "?"
        print(f"  [{t['id']}] {t['name']} ({dur_s})")
        print(f"       {t['src']}")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(tracks, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON: {out}")

    if args.download:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nСкачивание в {out_dir}...")
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            for track in tracks:
                await download_track(track, out_dir, client)

    return 0


async def cmd_download_url(args: argparse.Namespace) -> int:
    """Скачать один трек по URL страницы трека."""
    page_url = args.url.rstrip("/") + "/"
    async with PixabayMusicScraper(headless=not args.show_browser) as scraper:
        tracks = await scraper.fetch_page_tracks(page_url)

    if not tracks:
        print("Не удалось найти track на странице.")
        return 1

    track = tracks[0]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        result = await download_track(track, out_dir, client)
    return 0 if result else 1


class AsyncRunner:
    """Фоновый asyncio-цикл — браузер не перезапускается каждый раз."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def run(self, coro, *, timeout: float | None = 180):
        if self._loop is None:
            raise RuntimeError("Async loop not ready")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def shutdown(self) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)


class PixabayMusicApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Pixabay Music")
        self.geometry("980x700")
        self.minsize(820, 520)

        self.query = tk.StringVar(value="lofi")
        self.genre = tk.StringVar(value="")
        self.mood = tk.StringVar(value="")
        self.movement = tk.StringVar(value="")
        self.limit = tk.IntVar(value=0)
        self.out_dir = tk.StringVar(value=str(DEFAULT_OUT))
        self.show_browser = tk.BooleanVar(value=False)

        self.tracks: list[dict] = []
        self._busy = False
        self._async = AsyncRunner()
        self._scraper: PixabayMusicScraper | None = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(main, width=300)
        right = ttk.Frame(main)
        main.add(left, weight=0)
        main.add(right, weight=1)

        pad = {"padx": 6, "pady": 4}

        ttk.Label(left, text="Pixabay Music", font=("", 12, "bold")).pack(anchor=tk.W, **pad)
        ttk.Label(
            left,
            text="Royalty-free MP3 без логина",
            foreground="#666",
        ).pack(anchor=tk.W, **pad)

        ttk.Label(left, text="Поиск:").pack(anchor=tk.W, padx=6)
        ttk.Entry(left, textvariable=self.query).pack(fill=tk.X, **pad)

        ttk.Label(left, text="Жанр (опционально):").pack(anchor=tk.W, padx=6)
        self.genre_box = ttk.Combobox(
            left,
            textvariable=self.genre,
            values=[""] + PIXABAY_GENRES,
        )
        self.genre_box.pack(fill=tk.X, **pad)

        ttk.Label(left, text="Настроение (опционально):").pack(anchor=tk.W, padx=6)
        self.mood_box = ttk.Combobox(
            left,
            textvariable=self.mood,
            values=[""] + PIXABAY_MOODS,
        )
        self.mood_box.pack(fill=tk.X, **pad)

        ttk.Label(left, text="Movement (опционально):").pack(anchor=tk.W, padx=6)
        self.movement_box = ttk.Combobox(
            left,
            textvariable=self.movement,
            values=[""] + PIXABAY_MOVEMENTS,
        )
        self.movement_box.pack(fill=tk.X, **pad)

        nums = ttk.Frame(left)
        nums.pack(fill=tk.X, **pad)
        ttk.Label(nums, text="Лимит треков:").pack(side=tk.LEFT)
        ttk.Spinbox(nums, from_=0, to=99999, textvariable=self.limit, width=7).pack(side=tk.LEFT, padx=4)
        ttk.Label(nums, text="(0 = все)", foreground="#888").pack(side=tk.LEFT)

        ttk.Label(
            left,
            text="«Найти» загружает все страницы (~20 треков/стр.)",
            foreground="#888",
            wraplength=280,
        ).pack(anchor=tk.W, **pad)

        ttk.Label(
            left,
            text="Приоритет: жанр → настроение → movement → текст",
            foreground="#888",
            wraplength=280,
        ).pack(anchor=tk.W, **pad)

        self._dir_row(left, "Папка MP3:", self.out_dir, self._pick_out_dir)

        ttk.Checkbutton(left, text="Показать браузер", variable=self.show_browser).pack(anchor=tk.W, **pad)

        ttk.Separator(left).pack(fill=tk.X, pady=8)

        ttk.Button(left, text="Найти", command=self._search).pack(fill=tk.X, **pad)

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, **pad)
        ttk.Button(btn_row, text="Скачать выбранные", command=self._download_selected).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Скачать все", command=self._download_all).pack(side=tk.LEFT, padx=6)

        ttk.Button(left, text="Открыть папку", command=self._open_out_dir).pack(fill=tk.X, **pad)

        self.progress = ttk.Progressbar(left, mode="determinate")
        self.progress.pack(fill=tk.X, **pad)

        self.status = ttk.Label(left, text="", foreground="#228822", wraplength=280)
        self.status.pack(anchor=tk.W, **pad)

        ttk.Label(right, text="Результаты", font=("", 11, "bold")).pack(anchor=tk.W)

        tree_wrap = ttk.Frame(right)
        tree_wrap.pack(fill=tk.BOTH, expand=True, pady=4)

        cols = ("name", "duration", "id", "status")
        self.tree = ttk.Treeview(tree_wrap, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("name", text="Название")
        self.tree.heading("duration", text="Длина")
        self.tree.heading("id", text="ID")
        self.tree.heading("status", text="Статус")
        self.tree.column("name", width=320, stretch=True)
        self.tree.column("duration", width=70, anchor=tk.CENTER)
        self.tree.column("id", width=80, anchor=tk.CENTER)
        self.tree.column("status", width=120, anchor=tk.CENTER)

        scroll = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(right, text="Лог", font=("", 10, "bold")).pack(anchor=tk.W, pady=(8, 0))
        log_wrap = ttk.Frame(right)
        log_wrap.pack(fill=tk.BOTH, expand=False, pady=4)
        self.log_box = tk.Text(log_wrap, height=8, wrap=tk.WORD, state=tk.DISABLED, bg="#1e1e1e", fg="#ddd")
        log_scroll = ttk.Scrollbar(log_wrap, orient=tk.VERTICAL, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=log_scroll.set)
        self.log_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _on_close(self) -> None:
        if self._scraper is not None:
            try:
                self._async.run(self._scraper.__aexit__(None, None, None), timeout=30)
            except Exception:
                pass
        self._async.shutdown()
        self.destroy()

    def _get_scraper(self) -> PixabayMusicScraper:
        if self._scraper is None:
            raise RuntimeError("Scraper not initialized")
        return self._scraper

    async def _ensure_scraper(self) -> PixabayMusicScraper:
        headless = not self.show_browser.get()
        if self._scraper is None or self._scraper.headless != headless:
            if self._scraper is not None:
                await self._scraper.__aexit__(None, None, None)
            self._scraper = PixabayMusicScraper(headless=headless)
            await self._scraper.__aenter__()
        return self._scraper

    def _dir_row(self, parent, label: str, var: tk.StringVar, cmd) -> None:
        ttk.Label(parent, text=label).pack(anchor=tk.W, padx=6)
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=6, pady=2)
        ttk.Entry(row, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="…", width=3, command=cmd).pack(side=tk.LEFT, padx=4)

    def _pick_out_dir(self) -> None:
        path = filedialog.askdirectory(initialdir=self.out_dir.get())
        if path:
            self.out_dir.set(path)

    def _open_out_dir(self) -> None:
        out = Path(self.out_dir.get())
        out.mkdir(parents=True, exist_ok=True)
        os_startfile(out)

    def _log(self, msg: str) -> None:
        def append() -> None:
            self.log_box.configure(state=tk.NORMAL)
            self.log_box.insert(tk.END, msg + "\n")
            self.log_box.see(tk.END)
            self.log_box.configure(state=tk.DISABLED)

        self.after(0, append)

    def _set_status(self, msg: str, *, error: bool = False) -> None:
        self.status.config(text=msg, foreground="#cc3333" if error else "#228822")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy

    def _get_search_params(self) -> tuple[str | None, str | None, str | None, str | None]:
        query = self.query.get().strip() or None
        genre = self.genre.get().strip() or None
        mood = self.mood.get().strip() or None
        movement = self.movement.get().strip() or None
        if not query and not genre and not mood and not movement:
            raise ValueError("Укажите поиск, жанр, настроение или movement")
        return query, genre, mood, movement

    def _search(self) -> None:
        if self._busy:
            return
        try:
            self._get_search_params()
        except ValueError as exc:
            messagebox.showwarning("Поиск", str(exc))
            return

        self._set_busy(True)
        self._set_status("Поиск…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        threading.Thread(target=self._search_worker, daemon=True).start()

    def _on_search_progress(self, page_num: int, total: int) -> None:
        msg = f"Страница {page_num}, найдено {total}…"
        self.after(0, lambda m=msg: self._set_status(m))

    def _search_worker(self) -> None:
        err_msg = ""
        try:
            query, genre, mood, movement = self._get_search_params()
            tracks = self._async.run(
                self._async_search(query, genre, mood, movement),
                timeout=None,
            )
            self.after(0, lambda t=tracks: self._on_search_done(t))
        except Exception as exc:
            err_msg = str(exc) or exc.__class__.__name__
            if "Executable doesn't exist" in err_msg or "playwright install" in err_msg.lower():
                err_msg = (
                    "Playwright/Chromium не установлен.\n"
                    "Выполните: python -m playwright install chromium"
                )
            self.after(0, lambda m=err_msg: messagebox.showerror("Ошибка поиска", m))
            self.after(0, lambda m=err_msg: self._set_status(m, error=True))
            self.after(0, lambda m=err_msg: self._log(f"Ошибка: {m}"))
        finally:
            self.after(0, self._finish_progress)
            self.after(0, lambda: self._set_busy(False))

    async def _async_search(
        self,
        query: str | None,
        genre: str | None,
        mood: str | None,
        movement: str | None,
    ) -> list[dict]:
        scraper = await self._ensure_scraper()
        limit_val = self.limit.get()
        limit = None if limit_val <= 0 else limit_val
        return await scraper.search(
            query,
            genre=genre,
            mood=mood,
            movement=movement,
            pages=None,
            limit=limit,
            log=self._log,
            on_progress=self._on_search_progress,
        )

    def _on_search_done(self, tracks: list[dict]) -> None:
        self.tracks = tracks
        for item in self.tree.get_children():
            self.tree.delete(item)

        for track in tracks:
            self.tree.insert(
                "",
                tk.END,
                iid=str(track["id"]),
                values=(
                    track.get("name", "?"),
                    format_duration(track.get("duration")),
                    track.get("id", ""),
                    "",
                ),
            )

        if tracks:
            pages = max(t.get("page", 1) for t in tracks)
            self._set_status(f"Найдено: {len(tracks)} (страниц: {pages})")
            self._log(f"Готово: {len(tracks)} треков за {pages} стр.")
        else:
            self._set_status("Ничего не найдено", error=True)
            self._log("Треки не найдены")

    def _selected_tracks(self) -> list[dict]:
        ids = {int(iid) for iid in self.tree.selection()}
        if not ids:
            return []
        return [t for t in self.tracks if t["id"] in ids]

    def _download_selected(self) -> None:
        tracks = self._selected_tracks()
        if not tracks:
            messagebox.showinfo("Скачивание", "Выберите треки в списке")
            return
        self._start_download(tracks)

    def _download_all(self) -> None:
        if not self.tracks:
            messagebox.showinfo("Скачивание", "Сначала выполните поиск")
            return
        self._start_download(self.tracks)

    def _start_download(self, tracks: list[dict]) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._set_status(f"Скачивание 0/{len(tracks)}…")
        self.progress.configure(mode="determinate", maximum=len(tracks), value=0)
        threading.Thread(target=self._download_worker, args=(tracks,), daemon=True).start()

    def _download_worker(self, tracks: list[dict]) -> None:
        out_dir = Path(self.out_dir.get())
        out_dir.mkdir(parents=True, exist_ok=True)
        ok = 0

        async def run() -> int:
            nonlocal ok
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                for i, track in enumerate(tracks, 1):
                    result = await download_track(track, out_dir, client, log=self._log)
                    if result:
                        ok += 1
                        status = "OK"
                    else:
                        status = "FAIL"
                    self.after(0, lambda tid=str(track["id"]), s=status: self.tree.set(tid, "status", s))
                    self.after(0, lambda v=i: self.progress.configure(value=v))
                    self.after(0, lambda v=i, n=len(tracks): self._set_status(f"Скачивание {v}/{n}…"))
            return ok

        try:
            saved = self._async.run(run())
            summary = f"Готово: {saved}/{len(tracks)} в {out_dir}"
            self.after(0, lambda s=summary: self._set_status(s))
            self.after(0, lambda s=summary: self._log(s))
        except Exception as exc:
            err_msg = str(exc) or exc.__class__.__name__
            self.after(0, lambda m=err_msg: messagebox.showerror("Ошибка скачивания", m))
            self.after(0, lambda m=err_msg: self._set_status(m, error=True))
            self.after(0, lambda m=err_msg: self._log(f"Ошибка: {m}"))
        finally:
            self.after(0, lambda: self._set_busy(False))

    def _finish_progress(self) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)


def os_startfile(path: Path) -> None:
    import os
    import subprocess

    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except AttributeError:
        subprocess.Popen(["xdg-open", str(path)])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Скачивание музыки с Pixabay без логина")
    sub = p.add_subparsers(dest="cmd", required=True)

    search = sub.add_parser("search", help="Поиск и опционально скачивание")
    search.add_argument("query", nargs="?", help="Поисковый запрос, напр. lofi, chill, epic")
    search.add_argument("--genre", help="Жанр (Lofi, Beats...)")
    search.add_argument("--mood", help="Настроение (Happy, Chill...)")
    search.add_argument("--movement", help="Movement (Fast, Slow, Chasing...)")
    search.add_argument("--pages", type=int, default=0, help="Страниц (0 = все)")
    search.add_argument("--limit", type=int, default=0, help="Макс. треков (0 = все)")
    search.add_argument("--download", action="store_true", help="Сразу скачать найденные треки")
    search.add_argument("--out", default=str(DEFAULT_OUT), help="Папка для MP3")
    search.add_argument("--json", help="Сохранить метаданные в JSON")
    search.add_argument("--show-browser", action="store_true", help="Показать браузер (отладка)")

    dl = sub.add_parser("download", help="Скачать один трек по URL страницы")
    dl.add_argument("url", help="https://pixabay.com/music/...")
    dl.add_argument("--out", default=str(DEFAULT_OUT))
    dl.add_argument("--show-browser", action="store_true")

    return p


def main() -> int:
    if len(sys.argv) == 1 or "--gui" in sys.argv:
        PixabayMusicApp().mainloop()
        return 0

    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "search":
        if not args.query and not args.genre and not args.mood and not args.movement:
            parser.error("Укажите query, --genre, --mood или --movement")
        return asyncio.run(cmd_search(args))
    if args.cmd == "download":
        return asyncio.run(cmd_download_url(args))
    return 1


if __name__ == "__main__":
    sys.exit(main())
