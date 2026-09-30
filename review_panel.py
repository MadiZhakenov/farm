#!/usr/bin/env python3
"""
Carousel Strip Matrix — быстрый отсмотр run_*/carousel_* строками.

Виртуализованный Canvas: на экране только видимые ряды (~8–12),
LRU-кэш миниатюр — 100 каруселей скроллятся без раздувания памяти.
Клик по слайду → панель alts + query + «Ещё варианты» (Pinterest).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import tkinter as tk
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from PIL import Image, ImageTk

from core.renderer import render_slide

BG = "#1a1b1e"
PANEL = "#24262b"
PANEL2 = "#2c2f36"
FG = "#f2f2f2"
MUTED = "#9aa0a6"
ACCENT = "#3ddc97"
BORDER = "#3a3f48"
DANGER = "#e74c3c"
ROW_ALT = "#1f2126"
POPOVER_BG = "#12141a"

# Геометрия ряда / миниатюр (3:4) + подпись query
THUMB_W = 130
THUMB_H = 170
THUMB_GAP = 8
QUERY_LABEL_H = 28
ROW_PAD_Y = 8
ROW_H = THUMB_H + QUERY_LABEL_H + ROW_PAD_Y * 2 + 10
LEFT_W = 220
RIGHT_W = 130
MAX_SLIDES = 9
THUMB_CACHE_MAX = 96
ALT_THUMB_W = 78
ALT_THUMB_H = 104
FETCH_MORE_N = 4  # сколько новых за один клик «Ещё»
FETCH_FIND_N = 8  # «Найти» — свежий пул под новый query
MAX_ALTS_SHOWN = 16
ALT_COLS = 4  # сетка: 4 фото в ряд, рост вниз

def _img_fingerprint(path: Path) -> str:
    """Грубый отпечаток файла — ловить визуальные дубли без pin_id."""
    import hashlib

    try:
        with Image.open(path) as im:
            tiny = im.convert("RGB").resize((16, 16), Image.Resampling.BILINEAR)
            return hashlib.md5(tiny.tobytes()).hexdigest()
    except Exception:
        try:
            return hashlib.md5(path.read_bytes()[:8192]).hexdigest()
        except OSError:
            return ""


def _pil_fingerprint(im: Image.Image) -> str:
    import hashlib

    try:
        tiny = im.convert("RGB").resize((16, 16), Image.Resampling.BILINEAR)
        return hashlib.md5(tiny.tobytes()).hexdigest()
    except Exception:
        return ""


def _carousel_key(folder: Path) -> str:
    """Тот же ключ, что пишет batch_factory в учёт серии."""
    try:
        return str(folder.resolve())
    except OSError:
        return str(folder)


def _own_pins(meta: dict) -> set[str]:
    """Все pin_id этой карусели: финалы и сохранённые варианты."""
    out: set[str] = set()
    for sl in meta.get("slides") or []:
        if not isinstance(sl, dict):
            continue
        if sl.get("pin_id"):
            out.add(str(sl["pin_id"]))
        out |= {str(p) for p in (sl.get("alt_pin_ids") or []) if p}
        out |= {str(p) for p in (sl.get("alt_pins") or {}).values() if p}
    return out


def _series_used_index(folder: Path, meta: dict | None = None):
    """Фото, стоящие в ДРУГИХ каруселях серии (или None, если учёт недоступен)."""
    try:
        from core.photo_vault import get_photo_vault

        return get_photo_vault().used_index(
            exclude_carousel=_carousel_key(folder),
            exclude_pins=_own_pins(meta or {}),
        )
    except Exception as exc:
        print(f"[review] учёт серии недоступен: {exc}")
        return None


def _carousel_gender(meta: dict, folder: Path) -> str | None:
    """
    Пол карусели: из character_dna, иначе по фото 1-го слайда
    (только если на нём виден человек). Кэшируется в meta['gender_lock'].
    """
    cached = str(meta.get("gender_lock") or "").lower()
    if cached in ("female", "male", "none"):
        return None if cached == "none" else cached
    dna = meta.get("character_dna") or {}
    g = str(dna.get("gender") or "").lower() if isinstance(dna, dict) else ""
    if g not in ("female", "male"):
        g = ""
        try:
            from core.harvester import image_has_visible_person, infer_carousel_gender

            slides = meta.get("slides") or []
            sel = int((slides[0] or {}).get("selected_alt") or 0) if slides else 0
            src = folder / "alts" / f"1_{sel}.jpg"
            if not src.is_file():
                src = folder / "alts" / "1_0.jpg"
            if src.is_file():
                with Image.open(src) as im0:
                    im0 = im0.convert("RGB")
                    if image_has_visible_person(im0):
                        g = infer_carousel_gender(im0)
        except Exception as exc:
            print(f"[review] gender infer skip: {exc}")
    meta["gender_lock"] = g or "none"
    return g or None


def _gender_clash(image: Image.Image, gender: str | None, title: str = "") -> bool:
    """Та же проверка пола, что в автоподборе (gender_mismatches_lock)."""
    if gender not in ("female", "male"):
        return False
    try:
        from core.harvester import gender_mismatches_lock, image_has_visible_person

        if not image_has_visible_person(image):
            return False
        return bool(gender_mismatches_lock(image, gender, title))
    except Exception as exc:
        print(f"[review] gender check skip: {exc}")
        return False


def _slide_photo_role(meta: dict, slide_idx: int) -> str:
    roles = meta.get("photo_roles") or []
    if 0 <= slide_idx < len(roles) and roles[slide_idx]:
        return str(roles[slide_idx])
    slides = meta.get("slides") or []
    if 0 <= slide_idx < len(slides) and isinstance(slides[slide_idx], dict):
        return str(slides[slide_idx].get("photo_role") or "scene")
    return "scene"


def _carousel_place_mess(meta: dict, exclude_slide_idx: int) -> tuple[Any, int, bool]:
    """Места и грязь на ДРУГИХ слайдах текущей карусели (из meta)."""
    from collections import Counter

    from core.carousel_rules import LIMITED_PLACES

    places: Counter[str] = Counter()
    mess_used = 0
    for i, s in enumerate(meta.get("slides") or []):
        if i == exclude_slide_idx or not isinstance(s, dict):
            continue
        pl = str(s.get("place") or "other")
        if pl in LIMITED_PLACES:
            places[pl] += 1
        if s.get("is_mess"):
            mess_used += 1
    return places, mess_used, bool(meta.get("heavy_topic"))


def _alt_breaks_rules(
    image: Image.Image,
    meta: dict,
    slide_idx: int,
    *,
    classifier: Any = None,
) -> str:
    """
    Почему alt не подходит под правила карусели (пустая строка = ок).
    Финал: никогда грязь. Лимит грязи / одного места — как в автоподборе.
    """
    try:
        from core.carousel_rules import (
            LIMITED_PLACES,
            MAX_MESS_HEAVY,
            MAX_MESS_NORMAL,
            MAX_SAME_PLACE,
            ROLE_FINAL,
            _cand_features,
            get_photo_classifier,
        )

        role = _slide_photo_role(meta, slide_idx)
        places, mess_used, heavy = _carousel_place_mess(meta, slide_idx)
        budget = MAX_MESS_HEAVY if heavy else MAX_MESS_NORMAL
        n = len(meta.get("slides") or [])
        is_final = role == ROLE_FINAL or (n > 1 and slide_idx == n - 1)

        class _Cand:
            pass

        c = _Cand()
        c.image = image
        c.pin_id = ""
        f = _cand_features(c, classifier or get_photo_classifier())
        if is_final and f.is_mess:
            return "грязь на финале"
        if f.is_mess and mess_used >= budget:
            return f"лимит грязи ({mess_used}/{budget})"
        if f.place in LIMITED_PLACES and places[f.place] >= MAX_SAME_PLACE:
            return f"место «{f.place}» уже {places[f.place]}×"
        return ""
    except Exception as exc:
        print(f"[review] rules check skip: {exc}")
        return ""


def _role_query_hint(meta: dict, slide_idx: int, slide_text: str = "") -> str:
    """Для neutral/final подсказать спокойный запрос, если текущий пустой."""
    role = _slide_photo_role(meta, slide_idx)
    if role not in ("neutral", "final"):
        return ""
    try:
        from core.carousel_rules import neutral_plan

        plan = neutral_plan(
            role,
            topic=str(meta.get("topic") or ""),
            slide_text=slide_text,
            slide_index=slide_idx,
            heavy=bool(meta.get("heavy_topic")),
            seed=f"review:{slide_idx}",
        )
        return str(getattr(plan, "query", "") or "")
    except Exception:
        return ""


_VK_DELETE = 46
_VK_BACK = 8
_VK_A = 65
_VK_O = 79
_VK_ESCAPE = 27


def _btn(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None],
    *,
    bg: str = PANEL2,
    fg: str = FG,
    font_size: int = 10,
    padx: int = 12,
    pady: int = 8,
) -> tk.Button:
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=bg,
        activeforeground=fg,
        relief=tk.FLAT,
        font=("Segoe UI", font_size, "bold"),
        padx=padx,
        pady=pady,
        cursor="hand2",
        bd=0,
        highlightthickness=0,
    )


def _make_thumb(path: Path, w: int = THUMB_W, h: int = THUMB_H) -> Image.Image:
    img = Image.open(path).convert("RGB")
    src_w, src_h = img.size
    scale = max(w / src_w, h / src_h)
    nw, nh = max(1, int(src_w * scale)), max(1, int(src_h * scale))
    img = img.resize((nw, nh), Image.Resampling.BILINEAR)
    left = max(0, (nw - w) // 2)
    top = max(0, (nh - h) // 2)
    return img.crop((left, top, left + w, top + h))


@dataclass
class CarouselRow:
    path: Path
    number: str
    topic: str
    slides: list[Path] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    approved: bool = False


class _ThumbCache:
    """LRU PhotoImage cache — не держим 600 превью в RAM."""

    def __init__(self, max_items: int = THUMB_CACHE_MAX) -> None:
        self.max_items = max_items
        self._store: OrderedDict[str, ImageTk.PhotoImage] = OrderedDict()

    def get(self, path: Path, w: int, h: int) -> ImageTk.PhotoImage | None:
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            return None
        key = f"{path}|{mtime}|{w}x{h}"
        hit = self._store.get(key)
        if hit is not None:
            self._store.move_to_end(key)
            return hit
        try:
            pil = _make_thumb(path, w, h)
            photo = ImageTk.PhotoImage(pil)
            del pil
        except Exception:
            return None
        self._store[key] = photo
        self._store.move_to_end(key)
        while len(self._store) > self.max_items:
            self._store.popitem(last=False)
        return photo

    def invalidate_prefix(self, path: Path) -> None:
        prefix = str(path)
        dead = [k for k in self._store if k.startswith(prefix)]
        for k in dead:
            del self._store[k]

    def clear(self) -> None:
        self._store.clear()


class ReviewPanel(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_status: Callable[[str], None] | None = None,
        harvester: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.on_status = on_status or (lambda _s: None)
        self._harvester = harvester
        self.run_dir: Path | None = None
        self.rows: list[CarouselRow] = []
        self.total_in_run = 0
        self.approved = 0
        self.rejected = 0
        self._active = False
        self._selected = 0
        self._thumb_cache = _ThumbCache()
        self._row_windows: dict[int, int] = {}
        self._row_frames: dict[int, tk.Frame] = {}
        self._popover: tk.Toplevel | None = None
        self._popover_photos: list[ImageTk.PhotoImage] = []
        self._popover_ctx: dict[str, Any] = {}
        self._fetch_busy = False
        self._scroll_job: str | None = None
        self._query_var = tk.StringVar(value="")

        self._build()

    def _get_harvester(self) -> Any:
        if self._harvester is not None:
            return self._harvester
        from core.harvester import PinterestHarvester

        self._harvester = PinterestHarvester(on_status=self.on_status)
        return self._harvester

    @staticmethod
    def _slide_query(row: CarouselRow, slide_idx: int) -> str:
        slides = row.meta.get("slides") or []
        if 0 <= slide_idx < len(slides):
            return str(slides[slide_idx].get("query") or "").strip()
        return ""

    @staticmethod
    def _list_alts(folder: Path, slide_n: int) -> list[Path]:
        def _idx(p: Path) -> int:
            try:
                return int(p.stem.split("_", 1)[1])
            except (IndexError, ValueError):
                return 0

        return sorted(folder.glob(f"alts/{slide_n}_*.jpg"), key=_idx)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        top = tk.Frame(self, bg=PANEL2)
        top.pack(fill=tk.X)

        _btn(
            top,
            "📂 Выбрать run_…",
            self.pick_run_dir,
            bg=ACCENT,
            fg="#102018",
        ).pack(side=tk.LEFT, padx=(10, 6), pady=8)

        self.path_var = tk.StringVar(value="Папка не выбрана")
        tk.Label(
            top,
            textvariable=self.path_var,
            bg=PANEL2,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=4)

        _btn(
            top,
            "📁 Экспорт готовых",
            self.export_ready,
            bg="#4f8cff",
            fg="#0a1220",
            font_size=9,
            padx=10,
            pady=7,
        ).pack(side=tk.RIGHT, padx=10, pady=8)

        self.stats_var = tk.StringVar(
            value="Всего в запуске: 0 | Просмотрено: 0 | Отбраковано: 0"
        )
        tk.Label(
            top,
            textvariable=self.stats_var,
            bg=PANEL2,
            fg=ACCENT,
            font=("Segoe UI", 10, "bold"),
        ).pack(side=tk.RIGHT, padx=8)

        hint = tk.Frame(self, bg=PANEL)
        hint.pack(fill=tk.X)
        tk.Label(
            hint,
            text=(
                "Клик по слайду → alts + query · «Ещё варианты» догружает с Pinterest · "
                "✓ Одобрено · 🗑 В брак · A / X/Del · Esc"
            ),
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
            pady=3,
        ).pack(anchor=tk.W, padx=12)

        body = tk.Frame(self, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        self.canvas = tk.Canvas(
            body,
            bg=BG,
            highlightthickness=0,
            bd=0,
        )
        self.scrollbar = ttk.Scrollbar(
            body, orient=tk.VERTICAL, command=self.canvas.yview
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)
        self.canvas.bind("<Button-5>", self._on_mousewheel)
        self.canvas.bind("<Button-1>", lambda _e: self._close_popover())
        # колесо на всём виджете панели (без bind_all — без утечек)
        self.bind("<MouseWheel>", self._on_mousewheel)
        self.bind("<Button-4>", self._on_mousewheel)
        self.bind("<Button-5>", self._on_mousewheel)

    # ----------------------------------------------------------- lifecycle
    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            try:
                self.canvas.focus_set()
            except tk.TclError:
                pass

    def pick_run_dir(self) -> None:
        start = Path(__file__).resolve().parent / "out"
        if not start.is_dir():
            start = Path(__file__).resolve().parent
        chosen = filedialog.askdirectory(
            title="Выберите папку запуска out/run_…",
            initialdir=str(start),
        )
        if not chosen:
            return
        self.load_run(Path(chosen))

    def load_run(self, run_dir: Path) -> None:
        run_dir = Path(run_dir)
        if not run_dir.is_dir():
            messagebox.showerror("Отсмотр", f"Нет папки: {run_dir}")
            return
        self._close_popover()
        self._clear_rows()
        self._thumb_cache.clear()

        (run_dir / "rejected").mkdir(exist_ok=True)
        (run_dir / "approved").mkdir(exist_ok=True)
        self.run_dir = run_dir
        self.path_var.set(run_dir.name)

        folders = sorted(
            [
                p
                for p in run_dir.iterdir()
                if p.is_dir()
                and p.name.startswith("carousel_")
                and (p / "1.jpg").is_file()
            ],
            key=lambda p: p.name,
        )
        self.rows = [self._build_row(p) for p in folders]
        self.rejected = len(
            [p for p in (run_dir / "rejected").glob("carousel_*") if p.is_dir()]
        )
        self.approved = len(
            [p for p in (run_dir / "approved").glob("carousel_*") if p.is_dir()]
        )
        self.total_in_run = len(self.rows) + self.approved + self.rejected
        self._selected = 0

        self._update_stats()
        self._relayout(force=True)
        self.on_status(
            f"Strip Matrix: {len(self.rows)} каруселей в {run_dir.name}"
        )

    def _build_row(self, folder: Path) -> CarouselRow:
        slides = sorted(
            [p for p in folder.glob("[0-9]*.jpg") if p.stem.isdigit()],
            key=lambda p: int(p.stem),
        )[:MAX_SLIDES]
        meta: dict[str, Any] = {}
        meta_path = folder / "meta.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
        topic = str(meta.get("topic") or folder.name)
        num = folder.name.split("_")[1] if "_" in folder.name else "???"
        if num.isdigit():
            number = f"#{int(num):03d}"
        else:
            number = f"#{folder.name[-3:]}"
        return CarouselRow(
            path=folder, number=number, topic=topic, slides=slides, meta=meta
        )

    # ------------------------------------------------------ virtual scroll
    def _on_canvas_configure(self, _event: tk.Event | None = None) -> None:
        self._schedule_relayout()

    def _schedule_relayout(self) -> None:
        if self._scroll_job is not None:
            try:
                self.after_cancel(self._scroll_job)
            except tk.TclError:
                pass
        self._scroll_job = self.after(16, lambda: self._relayout(force=False))

    def _on_mousewheel(self, event: tk.Event) -> str | None:  # type: ignore[type-arg]
        if not self.rows:
            return None
        delta = 0
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        elif getattr(event, "delta", 0):
            delta = -1 if event.delta > 0 else 1
        if delta:
            self.canvas.yview_scroll(delta, "units")
            self._schedule_relayout()
        return "break"

    def _scrollregion_h(self) -> int:
        return max(1, len(self.rows) * ROW_H)

    def _relayout(self, *, force: bool) -> None:
        self._scroll_job = None
        n = len(self.rows)
        total_h = self._scrollregion_h()
        canvas_w = max(400, self.canvas.winfo_width() or 900)
        canvas_h = max(200, self.canvas.winfo_height() or 600)
        self.canvas.configure(scrollregion=(0, 0, canvas_w, total_h))

        if n == 0:
            self._clear_rows()
            self.canvas.delete("empty")
            self.canvas.create_text(
                canvas_w // 2,
                canvas_h // 2,
                text="Выберите папку out/run_…",
                fill=MUTED,
                font=("Segoe UI", 14),
                tags="empty",
            )
            return
        self.canvas.delete("empty")

        top = self.canvas.canvasy(0)
        bot = top + canvas_h
        first = max(0, int(top // ROW_H) - 1)
        last = min(n - 1, int(bot // ROW_H) + 1)

        # убрать уехавшие за окно
        for idx in list(self._row_frames.keys()):
            if idx < first or idx > last:
                self._destroy_row_widget(idx)

        for idx in range(first, last + 1):
            if idx in self._row_frames and not force:
                # обновить ширину
                fr = self._row_frames[idx]
                fr.configure(width=canvas_w)
                self.canvas.itemconfigure(self._row_windows[idx], width=canvas_w)
                continue
            if idx in self._row_frames:
                self._destroy_row_widget(idx)
            self._mount_row(idx, canvas_w)

    def _clear_rows(self) -> None:
        for idx in list(self._row_frames.keys()):
            self._destroy_row_widget(idx)

    def _destroy_row_widget(self, idx: int) -> None:
        win = self._row_windows.pop(idx, None)
        fr = self._row_frames.pop(idx, None)
        if win is not None:
            try:
                self.canvas.delete(win)
            except tk.TclError:
                pass
        if fr is not None:
            try:
                fr.destroy()
            except tk.TclError:
                pass

    def _mount_row(self, idx: int, canvas_w: int) -> None:
        row = self.rows[idx]
        bg = PANEL if idx % 2 == 0 else ROW_ALT
        if idx == self._selected:
            bg = "#2a3340"

        fr = tk.Frame(self.canvas, bg=bg, height=ROW_H, width=canvas_w)
        fr.pack_propagate(False)

        left = tk.Frame(fr, bg=bg, width=LEFT_W)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 4), pady=ROW_PAD_Y)
        left.pack_propagate(False)

        tk.Label(
            left,
            text=row.number,
            bg=bg,
            fg=ACCENT,
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        topic = row.topic if len(row.topic) <= 42 else row.topic[:40] + "…"
        tk.Label(
            left,
            text=topic,
            bg=bg,
            fg=FG,
            font=("Segoe UI", 8),
            anchor="nw",
            justify=tk.LEFT,
            wraplength=LEFT_W - 8,
        ).pack(fill=tk.X, pady=(2, 6))
        _btn(
            left,
            "🗑 В брак",
            lambda i=idx: self.reject_row(i),
            bg=DANGER,
            fg="#fff",
            font_size=8,
            padx=8,
            pady=4,
        ).pack(anchor=tk.W)

        mid = tk.Frame(fr, bg=bg)
        mid.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=ROW_PAD_Y)

        for s_i, slide_path in enumerate(row.slides):
            photo = self._thumb_cache.get(slide_path, THUMB_W, THUMB_H)
            cell = tk.Frame(mid, bg=bg)
            cell.pack(side=tk.LEFT, padx=(0, THUMB_GAP))
            frame = tk.Frame(cell, bg=BORDER, padx=1, pady=1)
            frame.pack()
            lbl = tk.Label(frame, bg="#0d0e10", width=THUMB_W, height=THUMB_H)
            if photo is not None:
                lbl.configure(image=photo)
                lbl.image = photo  # type: ignore[attr-defined]
            else:
                lbl.configure(text="?", fg=MUTED)
            lbl.pack()
            q = self._slide_query(row, s_i)
            q_short = q if len(q) <= 22 else q[:20] + "…"
            q_lbl = tk.Label(
                cell,
                text=q_short or f"slide {s_i + 1}",
                bg=bg,
                fg=MUTED if q else "#666",
                font=("Segoe UI", 7),
                wraplength=THUMB_W,
                justify=tk.CENTER,
            )
            q_lbl.pack(fill=tk.X, pady=(2, 0))
            for w in (lbl, frame, cell, q_lbl):
                w.bind(
                    "<Button-1>",
                    lambda e, i=idx, s=s_i: self._on_slide_click(i, s, e),
                )

        right = tk.Frame(fr, bg=bg, width=RIGHT_W)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 10), pady=ROW_PAD_Y)
        right.pack_propagate(False)
        _btn(
            right,
            "✓ Одобрено",
            lambda i=idx: self.approve_row(i),
            bg=ACCENT,
            fg="#102018",
            font_size=9,
            padx=8,
            pady=10,
        ).pack(expand=True)

        # клик по ряду = выбрать
        for w in (fr, left, mid, right):
            w.bind("<Button-1>", lambda _e, i=idx: self._select_row(i))

        y = idx * ROW_H
        win = self.canvas.create_window(
            0, y, anchor="nw", window=fr, width=canvas_w, height=ROW_H
        )
        self._row_frames[idx] = fr
        self._row_windows[idx] = win
        self._bind_wheel_recursive(fr)

    def _bind_wheel_recursive(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel)
        widget.bind("<Button-4>", self._on_mousewheel)
        widget.bind("<Button-5>", self._on_mousewheel)
        for child in widget.winfo_children():
            self._bind_wheel_recursive(child)

    def _select_row(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.rows):
            return
        old = self._selected
        self._selected = idx
        if old in self._row_frames:
            self._destroy_row_widget(old)
            self._mount_row(old, max(400, self.canvas.winfo_width() or 900))
        if idx in self._row_frames:
            self._destroy_row_widget(idx)
            self._mount_row(idx, max(400, self.canvas.winfo_width() or 900))

    # ---------------------------------------------------- click-to-swap
    def _on_slide_click(self, row_idx: int, slide_idx: int, event: tk.Event) -> None:  # type: ignore[type-arg]
        self._selected = row_idx
        self._open_alt_popover(row_idx, slide_idx, event)

    def _close_popover(self) -> None:
        if self._popover is not None:
            try:
                self._popover.destroy()
            except tk.TclError:
                pass
            self._popover = None
        self._popover_photos.clear()
        self._popover_ctx.clear()

    def _open_alt_popover(
        self, row_idx: int, slide_idx: int, event: tk.Event | None = None
    ) -> None:  # type: ignore[type-arg]
        self._close_popover()
        if row_idx < 0 or row_idx >= len(self.rows):
            return
        row = self.rows[row_idx]
        if slide_idx < 0 or slide_idx >= len(row.slides):
            return
        slide_n = int(row.slides[slide_idx].stem)
        query = self._slide_query(row, slide_idx)
        self._query_var.set(query)

        pop = tk.Toplevel(self)
        pop.title(f"Слайд {slide_n} · замена фона")
        pop.configure(bg=POPOVER_BG)
        pop.transient(self.winfo_toplevel())
        pop.attributes("-topmost", True)
        self._popover = pop
        self._popover_ctx = {
            "row_idx": row_idx,
            "slide_idx": slide_idx,
            "slide_n": slide_n,
            "strip": None,
            "status": None,
        }

        head = tk.Frame(pop, bg=POPOVER_BG)
        head.pack(fill=tk.X, padx=10, pady=(10, 4))
        tk.Label(
            head,
            text=f"{row.number} · слайд {slide_n}",
            bg=POPOVER_BG,
            fg=ACCENT,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor=tk.W)

        q_row = tk.Frame(pop, bg=POPOVER_BG)
        q_row.pack(fill=tk.X, padx=10, pady=(2, 6))
        tk.Label(
            q_row, text="Query:", bg=POPOVER_BG, fg=MUTED, font=("Segoe UI", 8)
        ).pack(side=tk.LEFT)
        entry = tk.Entry(
            q_row,
            textvariable=self._query_var,
            bg="#1e2025",
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            font=("Consolas", 10),
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6), ipady=4)
        entry.bind("<Return>", lambda _e: self._fetch_more_alts(replace_query=True))

        btn_row = tk.Frame(pop, bg=POPOVER_BG)
        btn_row.pack(fill=tk.X, padx=10, pady=(0, 6))
        _btn(
            btn_row,
            "🔍 Найти",
            lambda: self._fetch_more_alts(replace_query=True),
            bg="#4f8cff",
            fg="#0a1220",
            font_size=8,
            padx=10,
            pady=5,
        ).pack(side=tk.LEFT, padx=(0, 6))
        _btn(
            btn_row,
            f"＋ Ещё {FETCH_MORE_N}",
            lambda: self._fetch_more_alts(replace_query=False),
            bg=ACCENT,
            fg="#102018",
            font_size=8,
            padx=10,
            pady=5,
        ).pack(side=tk.LEFT, padx=(0, 6))
        _btn(
            btn_row,
            "Закрыть",
            self._close_popover,
            font_size=8,
            padx=10,
            pady=5,
        ).pack(side=tk.RIGHT)

        status = tk.Label(
            pop,
            text="Клик по превью = заменить фон и перерендерить JPEG",
            bg=POPOVER_BG,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        )
        status.pack(fill=tk.X, padx=10, pady=(0, 4))
        self._popover_ctx["status"] = status

        # Сетка 4 в ряд + вертикальный скролл
        wrap = tk.Frame(pop, bg=POPOVER_BG)
        wrap.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 10))
        canvas = tk.Canvas(wrap, bg=POPOVER_BG, highlightthickness=0)
        vbar = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        strip = tk.Frame(canvas, bg=POPOVER_BG)
        win = canvas.create_window((0, 0), window=strip, anchor="nw")
        self._popover_ctx["strip"] = strip
        self._popover_ctx["alt_canvas"] = canvas
        self._popover_ctx["alt_win"] = win

        def _on_strip_configure(_e: tk.Event | None = None) -> None:  # type: ignore[type-arg]
            canvas.configure(scrollregion=canvas.bbox("all"))
            try:
                canvas.itemconfigure(win, width=canvas.winfo_width())
            except tk.TclError:
                pass

        def _on_canvas_configure(e: tk.Event) -> None:  # type: ignore[type-arg]
            try:
                canvas.itemconfigure(win, width=e.width)
            except tk.TclError:
                pass

        def _on_mousewheel(e: tk.Event) -> None:  # type: ignore[type-arg]
            delta = int(-1 * (e.delta / 120)) if getattr(e, "delta", 0) else 0
            if delta:
                canvas.yview_scroll(delta, "units")

        strip.bind("<Configure>", _on_strip_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        self._render_alt_strip(row_idx, slide_idx)

        pop.update_idletasks()
        # ширина под 4 колонки
        grid_w = ALT_COLS * (ALT_THUMB_W + 14) + 36
        n_alts = len(self._list_alts(row.path, slide_n))
        n_rows = max(1, (min(n_alts, MAX_ALTS_SHOWN) + ALT_COLS - 1) // ALT_COLS)
        grid_h = min(420, max(160, n_rows * (ALT_THUMB_H + 28) + 8))
        win_h = 130 + grid_h
        if event is not None:
            x = max(8, min(event.x_root - 40, pop.winfo_screenwidth() - grid_w - 20))
            y = max(8, min(event.y_root + 8, pop.winfo_screenheight() - win_h - 20))
        else:
            x, y = 120, 120
        pop.geometry(f"{grid_w}x{win_h}+{x}+{y}")
        pop.bind("<Escape>", lambda _e: self._close_popover())
        try:
            entry.focus_set()
            entry.icursor(tk.END)
        except tk.TclError:
            pass

    def _render_alt_strip(self, row_idx: int, slide_idx: int) -> None:
        strip = self._popover_ctx.get("strip")
        if strip is None or not isinstance(strip, tk.Frame):
            return
        for child in strip.winfo_children():
            child.destroy()
        self._popover_photos.clear()

        row = self.rows[row_idx]
        slide_n = int(row.slides[slide_idx].stem)
        alts = self._list_alts(row.path, slide_n)
        meta_slides = row.meta.get("slides") or []
        selected_alt = 0
        if slide_idx < len(meta_slides):
            selected_alt = int(meta_slides[slide_idx].get("selected_alt") or 0)

        if not alts:
            tk.Label(
                strip,
                text="Нет alts — нажми «Найти» или «Ещё»",
                bg=POPOVER_BG,
                fg=MUTED,
                font=("Segoe UI", 9),
            ).grid(row=0, column=0, padx=12, pady=20)
        else:
            for col in range(ALT_COLS):
                strip.grid_columnconfigure(col, weight=1, minsize=ALT_THUMB_W + 8)
            for i, alt_path in enumerate(alts[:MAX_ALTS_SHOWN]):
                try:
                    alt_i = int(alt_path.stem.split("_", 1)[1])
                except (IndexError, ValueError):
                    alt_i = 0
                photo = self._thumb_cache.get(
                    alt_path, ALT_THUMB_W, ALT_THUMB_H
                )
                border = ACCENT if alt_i == selected_alt else BORDER
                cell = tk.Frame(strip, bg=border, padx=2, pady=2)
                r, c = divmod(i, ALT_COLS)
                cell.grid(row=r, column=c, padx=4, pady=4, sticky="n")
                lbl = tk.Label(
                    cell, bg="#0d0e10", width=ALT_THUMB_W, height=ALT_THUMB_H
                )
                if photo is not None:
                    lbl.configure(image=photo)
                    self._popover_photos.append(photo)
                else:
                    lbl.configure(text=str(alt_i), fg=MUTED)
                lbl.pack()
                tk.Label(
                    cell,
                    text=f"#{alt_i}",
                    bg=border,
                    fg=MUTED,
                    font=("Segoe UI", 7),
                ).pack()
                for w in (lbl, cell):
                    w.bind(
                        "<Button-1>",
                        lambda _e, r=row_idx, s=slide_idx, a=alt_i, p=alt_path: self._apply_alt(
                            r, s, a, p
                        ),
                    )

        status = self._popover_ctx.get("status")
        if isinstance(status, tk.Label):
            status.configure(
                text=f"Альтернатив: {len(alts)} · клик = заменить · query: "
                f"{self._query_var.get() or '—'}"
            )
        canvas = self._popover_ctx.get("alt_canvas")
        if isinstance(canvas, tk.Canvas):
            canvas.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))
            try:
                canvas.itemconfigure(
                    self._popover_ctx.get("alt_win"),
                    width=canvas.winfo_width(),
                )
            except (tk.TclError, TypeError):
                pass

    def _fetch_more_alts(self, *, replace_query: bool) -> None:
        if self._fetch_busy:
            return
        ctx = self._popover_ctx
        if not ctx:
            return
        row_idx = int(ctx["row_idx"])
        slide_idx = int(ctx["slide_idx"])
        slide_n = int(ctx["slide_n"])
        if row_idx < 0 or row_idx >= len(self.rows):
            return
        row = self.rows[row_idx]
        query = self._query_var.get().strip()
        meta_slides = row.meta.setdefault("slides", [])
        while len(meta_slides) <= slide_idx:
            meta_slides.append({})
        entry0 = meta_slides[slide_idx] if slide_idx < len(meta_slides) else {}
        if not query:
            # neutral/final: подставить спокойный запрос под роль слайда
            hint = _role_query_hint(
                row.meta,
                slide_idx,
                str((entry0 or {}).get("text") or ""),
            )
            if hint:
                query = hint
                self._query_var.set(hint)
            else:
                messagebox.showinfo("Query", "Введи Pinterest-запрос (2–3 слова).")
                return

        # сохранить query в meta
        meta_slides[slide_idx]["query"] = query
        try:
            (row.path / "meta.json").write_text(
                json.dumps(row.meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

        status = ctx.get("status")
        if isinstance(status, tk.Label):
            status.configure(text=f"Ищу «{query}»…")
        self._fetch_busy = True
        self.on_status(f"Отсмотр: поиск «{query}»…")

        def _worker() -> None:
            err = ""
            added = 0
            skipped_dup = 0
            skipped_series = 0
            skipped_gender = 0
            skipped_rules = 0
            downloaded = 0
            hq = query
            auto_retried = False
            tried_n = 1
            try:
                from core.harvester import finalize_photo_query

                hq = finalize_photo_query(query, slide_text="") or query
                harv = self._get_harvester()
                existing = self._list_alts(row.path, slide_n)
                entry = meta_slides[slide_idx] if slide_idx < len(meta_slides) else {}
                alts_dir = row.path / "alts"
                alts_dir.mkdir(exist_ok=True)

                # «Найти» = новый query → сбросить старые alts слайда (не копить шлак)
                if replace_query and existing:
                    for p in existing:
                        try:
                            p.unlink(missing_ok=True)
                        except OSError:
                            pass
                    existing = []
                    entry["alt_pin_ids"] = []
                    entry["alt_count"] = 0
                    try:
                        (row.path / "meta.json").write_text(
                            json.dumps(row.meta, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    except OSError:
                        pass

                # Бан только текущий финал (+ уже показанные, если «Ещё»)
                exclude: set[str] = set()
                if entry.get("pin_id"):
                    exclude.add(str(entry["pin_id"]))
                for pid in entry.get("alt_pin_ids") or []:
                    if pid:
                        exclude.add(str(pid))
                # Фото других слайдов этой же карусели тоже не предлагаем
                for other in meta_slides:
                    if isinstance(other, dict) and other.get("pin_id"):
                        exclude.add(str(other["pin_id"]))
                known_fps = {
                    fp
                    for fp in (_img_fingerprint(p) for p in existing)
                    if fp
                }
                # Серия: фото из других каруселей не предлагаем (фидбек 2026-09-29)
                series_used = _series_used_index(row.path, row.meta)
                series_pins = set(series_used.pins) if series_used else set()
                # Пол: та же проверка, что в автоподборе
                gender_lock = _carousel_gender(row.meta, row.path)
                # Правила карусели: роль / грязь / место (как в автоподборе)
                photo_role = _slide_photo_role(row.meta, slide_idx)
                try:
                    from core.carousel_rules import get_photo_classifier

                    rules_clf = get_photo_classifier()
                except Exception:
                    rules_clf = None

                want_n = FETCH_FIND_N if replace_query else FETCH_MORE_N
                slide_text = str(entry.get("text") or "")
                visual_scene = str(
                    entry.get("visual_scene")
                    or entry.get("scene")
                    or ""
                )
                topic = str(
                    row.meta.get("topic")
                    or row.meta.get("title")
                    or ""
                )

                def _harvest_ranked(q_try: str) -> tuple[list, int]:
                    fl = max(want_n * 5, want_n + len(exclude) + 8)
                    raw_local, _p = harv.harvest_for_query(
                        q_try,
                        limit=fl,
                        exclude_ids=exclude | series_pins,
                        slide_text=slide_text,
                        slide_index=slide_idx,
                        ignore_used=True,
                        apply_score=False,
                        allow_broaden=False,
                        _allow_emergency=False,
                        visual_scene=visual_scene,
                    )
                    ranked_local = harv.rank_review_alternatives(
                        raw_local,
                        query=q_try,
                        slide_text=slide_text,
                        visual_scene=visual_scene or q_try,
                        limit=want_n,
                    )
                    return ranked_local, len(raw_local)

                # 1) primary query
                tried: list[str] = []
                cands, downloaded = _harvest_ranked(hq or query)
                tried.append(hq or query)
                used_q = hq or query

                # 2) if thin/empty — auto chain from slide text (broaden → rescue → pivot)
                min_ok = max(2, want_n // 2)
                if len(cands) < min_ok:
                    from core.harvester import smart_broaden_queries
                    from core.query_forge import (
                        style_pivot_queries,
                        vibe_rescue_queries,
                    )

                    avoid = {t.lower() for t in tried}
                    auto_qs: list[str] = []
                    auto_qs.extend(
                        smart_broaden_queries(hq or query, max_alts=2)
                    )
                    auto_qs.extend(
                        vibe_rescue_queries(
                            slide_text=slide_text,
                            visual_scene=visual_scene,
                            topic=topic,
                            avoid=avoid,
                            max_n=3,
                            include_style_pivot=False,
                        )
                    )
                    auto_qs.extend(
                        style_pivot_queries(
                            avoid=avoid,
                            max_n=3,
                            seed_text=hq or query,
                            slide_text=slide_text,
                            visual_scene=visual_scene,
                            topic=topic,
                        )
                    )
                    # de-dupe preserve order
                    seen_q: set[str] = set(avoid)
                    chain: list[str] = []
                    for aq in auto_qs:
                        low = (aq or "").strip().lower()
                        if not low or low in seen_q:
                            continue
                        seen_q.add(low)
                        chain.append(aq.strip())

                    if isinstance(status, tk.Label):
                        self.after(
                            0,
                            lambda: status.configure(
                                text=f"Пусто/мало — пробую {len(chain)} "
                                f"запросов под текст…"
                            ),
                        )

                    merged: list = list(cands)
                    seen_pins = {
                        str(getattr(c, "pin_id", "") or "")
                        for c in merged
                        if getattr(c, "pin_id", None)
                    }
                    for aq in chain:
                        if len(merged) >= want_n:
                            break
                        print(
                            f"[review-alts] auto-try «{aq}» "
                            f"(have {len(merged)}/{want_n})",
                            flush=True,
                        )
                        more, n_raw = _harvest_ranked(aq)
                        downloaded += n_raw
                        tried.append(aq)
                        if more:
                            used_q = aq
                        for c in more:
                            pid = str(getattr(c, "pin_id", "") or "")
                            if pid and pid in seen_pins:
                                continue
                            if pid:
                                seen_pins.add(pid)
                            merged.append(c)
                            if len(merged) >= want_n:
                                break
                    # re-rank merged by combined_score if present
                    merged.sort(
                        key=lambda c: float(
                            getattr(c, "combined_score", 0) or 0
                        ),
                        reverse=True,
                    )
                    cands = merged[:want_n]
                    auto_retried = len(tried) > 1
                    tried_n = len(tried)
                    if auto_retried:
                        print(
                            f"[review-alts] chain tried={tried} "
                            f"→ kept={len(cands)} used_q=«{used_q}»",
                            flush=True,
                        )

                hq = used_q
                if not cands and downloaded:
                    print(
                        f"[review-alts] 0 pass after chain "
                        f"tried={tried} raw≈{downloaded}",
                        flush=True,
                    )

                next_i = 0
                if existing:
                    try:
                        next_i = (
                            max(
                                int(p.stem.split("_", 1)[1])
                                for p in existing
                            )
                            + 1
                        )
                    except ValueError:
                        next_i = len(existing)

                alt_pin_ids = [
                    str(p) for p in (entry.get("alt_pin_ids") or []) if p
                ]
                alt_pins = dict(entry.get("alt_pins") or {})
                from core.carousel_rules import image_fingerprint

                for cand in cands:
                    if added >= want_n:
                        break
                    pid = str(getattr(cand, "pin_id", "") or "")
                    if pid and pid in exclude:
                        skipped_dup += 1
                        continue
                    fp = _pil_fingerprint(cand.image)
                    if fp and fp in known_fps:
                        skipped_dup += 1
                        continue
                    if series_used is not None and series_used.is_used(
                        pid, image_fingerprint(cand.image)
                    ):
                        skipped_series += 1
                        continue
                    if _gender_clash(
                        cand.image, gender_lock, str(getattr(cand, "title", "") or "")
                    ):
                        skipped_gender += 1
                        continue
                    rule_why = _alt_breaks_rules(
                        cand.image,
                        row.meta,
                        slide_idx,
                        classifier=rules_clf,
                    )
                    if rule_why:
                        skipped_rules += 1
                        print(
                            f"[review-alts] skip rules ({rule_why}) "
                            f"pin={pid or '?'} role={photo_role}",
                            flush=True,
                        )
                        continue
                    out = alts_dir / f"{slide_n}_{next_i}.jpg"
                    cand.image.convert("RGB").save(
                        out, quality=88, optimize=True
                    )
                    if pid:
                        alt_pins[str(next_i)] = pid
                    next_i += 1
                    added += 1
                    if pid:
                        exclude.add(pid)
                        alt_pin_ids.append(pid)
                    if fp:
                        known_fps.add(fp)

                if replace_query or added:
                    meta_slides[slide_idx]["alt_count"] = len(
                        self._list_alts(row.path, slide_n)
                    )
                    meta_slides[slide_idx]["query"] = hq or query
                    meta_slides[slide_idx]["alt_pin_ids"] = alt_pin_ids
                    meta_slides[slide_idx]["alt_pins"] = alt_pins
                    (row.path / "meta.json").write_text(
                        json.dumps(row.meta, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            except Exception as exc:
                err = str(exc)

            def _done() -> None:
                self._fetch_busy = False
                if err:
                    if isinstance(status, tk.Label):
                        status.configure(text=f"Ошибка: {err[:80]}")
                    messagebox.showerror("Поиск", err)
                    return
                if added == 0:
                    msg = "0 новых"
                    if auto_retried:
                        msg += f" (после {tried_n} запросов под текст)"
                    if downloaded:
                        msg += (
                            f" · скачано {downloaded}, "
                            "все ниже UGC/taste/rel или дубли"
                        )
                    elif skipped_dup:
                        msg += f" (дублей отсеяно {skipped_dup})"
                    if skipped_series or skipped_gender or skipped_rules:
                        msg += (
                            f" (в других каруселях {skipped_series}, "
                            f"другой пол {skipped_gender}, "
                            f"правила {skipped_rules})"
                        )
                    msg += " — смени query"
                    if isinstance(status, tk.Label):
                        status.configure(text=msg)
                    self.on_status(f"Отсмотр: 0 новых для «{query}»")
                else:
                    extra = f", дублей −{skipped_dup}" if skipped_dup else ""
                    if skipped_series:
                        extra += f", уже в других каруселях −{skipped_series}"
                    if skipped_gender:
                        extra += f", другой пол −{skipped_gender}"
                    if skipped_rules:
                        extra += f", правила −{skipped_rules}"
                    chain_note = (
                        f" · auto×{tried_n}" if auto_retried else ""
                    )
                    self.on_status(
                        f"Отсмотр: +{added} alts слайд {slide_n}"
                        f"{extra}{chain_note}"
                    )
                    if isinstance(status, tk.Label):
                        status.configure(
                            text=(
                                f"+{added} ranked{chain_note} · "
                                f"query: {hq or query}"
                            )
                        )
                if self._popover is not None:
                    self._query_var.set(
                        str(meta_slides[slide_idx].get("query") or query)
                    )
                    self._render_alt_strip(row_idx, slide_idx)
                if row_idx in self._row_frames:
                    self._destroy_row_widget(row_idx)
                    self._mount_row(
                        row_idx,
                        max(400, self.canvas.winfo_width() or 900),
                    )

            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _maybe_close_popover(self) -> None:
        # оставляем панель открытой — закрытие только Esc / кнопкой
        return

    def _apply_alt(
        self, row_idx: int, slide_idx: int, alt_i: int, alt_path: Path
    ) -> None:
        if row_idx < 0 or row_idx >= len(self.rows):
            self._close_popover()
            return
        row = self.rows[row_idx]
        if slide_idx < 0 or slide_idx >= len(row.slides):
            self._close_popover()
            return
        slide_path = row.slides[slide_idx]
        slide_n = int(slide_path.stem)
        meta_slides = row.meta.get("slides") or []
        text = ""
        entry: dict[str, Any] | None = None
        if slide_idx < len(meta_slides):
            entry = meta_slides[slide_idx]
            text = str(entry.get("text") or "")
        alt_pin = ""
        if entry is not None:
            alt_pin = str((entry.get("alt_pins") or {}).get(str(alt_i)) or "")
            if not alt_pin:
                ids = [str(p) for p in (entry.get("alt_pin_ids") or []) if p]
                if 0 <= alt_i < len(ids):
                    alt_pin = ids[alt_i]
        try:
            bg = Image.open(alt_path).convert("RGB")
            # Проверки как в автоподборе: пол и «одно фото — одна карусель»
            from core.carousel_rules import image_fingerprint

            gender_lock = _carousel_gender(row.meta, row.path)
            if _gender_clash(bg, gender_lock) and not messagebox.askyesno(
                "Другой пол",
                "На этом фото, похоже, человек другого пола, чем в карусели "
                f"({'женский' if gender_lock == 'female' else 'мужской'}).\n"
                "Всё равно поставить?",
            ):
                return
            series_used = _series_used_index(row.path, row.meta)
            if series_used is not None and series_used.is_used(
                alt_pin, image_fingerprint(bg)
            ) and not messagebox.askyesno(
                "Фото уже используется",
                "Это фото уже стоит в другой карусели серии.\n"
                "Всё равно поставить?",
            ):
                return
            rule_why = _alt_breaks_rules(bg, row.meta, slide_idx)
            if rule_why and not messagebox.askyesno(
                "Правила карусели",
                f"Это фото ломает правило: {rule_why}.\n"
                f"Роль слайда: {_slide_photo_role(row.meta, slide_idx)}.\n"
                "Всё равно поставить?",
            ):
                return
            # обновить place/mess в meta после выбора
            try:
                from core.carousel_rules import _cand_features, get_photo_classifier

                class _Cand:
                    pass

                c = _Cand()
                c.image = bg
                c.pin_id = alt_pin
                feat = _cand_features(c, get_photo_classifier())
            except Exception:
                feat = None
            rendered, rmeta = render_slide(bg, text)
            rendered.save(slide_path, quality=92, optimize=True)
            try:
                from core.photo_vault import get_photo_vault

                get_photo_vault().register_usage(
                    _carousel_key(row.path), slide_n, pin_id=alt_pin, image=bg
                )
            except Exception as exc:
                print(f"[review] usage register skip: {exc}")
            del rendered, bg
            if entry is not None:
                entry["selected_alt"] = alt_i
                entry["slot"] = getattr(rmeta, "slot", None)
                if alt_pin:
                    entry["pin_id"] = alt_pin
                if feat is not None:
                    entry["photo_role"] = _slide_photo_role(row.meta, slide_idx)
                    entry["is_mess"] = bool(feat.is_mess)
                    entry["mess_score"] = round(float(feat.mess), 4)
                    entry["place"] = str(feat.place or "other")
                meta_path = row.path / "meta.json"
                meta_path.write_text(
                    json.dumps(row.meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except Exception as exc:
            messagebox.showerror("Замена фона", str(exc))
            return

        self._thumb_cache.invalidate_prefix(slide_path)
        # обновить превью в strip (акцент) и в ряду — панель не закрываем
        if self._popover is not None:
            self._render_alt_strip(row_idx, slide_idx)
        if row_idx in self._row_frames:
            self._destroy_row_widget(row_idx)
            self._mount_row(
                row_idx, max(400, self.canvas.winfo_width() or 900)
            )
        self.on_status(f"{row.number} слайд {slide_n} → alt {alt_i}")

    # ------------------------------------------------ approve / reject
    def _update_stats(self) -> None:
        reviewed = self.approved + self.rejected
        self.stats_var.set(
            f"Всего в запуске: {self.total_in_run} | "
            f"Просмотрено: {reviewed} | Отбраковано: {self.rejected}"
        )

    def approve_row(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.rows) or not self.run_dir:
            return
        self._close_popover()
        row = self.rows[idx]
        dest_root = self.run_dir / "approved"
        dest_root.mkdir(exist_ok=True)
        dest = dest_root / row.path.name
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        try:
            shutil.move(str(row.path), str(dest))
        except OSError as exc:
            messagebox.showerror("Одобрено", str(exc))
            return
        self.rows.pop(idx)
        self.approved += 1
        if self._selected >= len(self.rows):
            self._selected = max(0, len(self.rows) - 1)
        self._update_stats()
        self._clear_rows()
        self._relayout(force=True)
        self.on_status(f"Одобрено: {row.number} {row.topic[:40]}")

    def reject_row(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.rows) or not self.run_dir:
            return
        self._close_popover()
        row = self.rows[idx]
        dest_root = self.run_dir / "rejected"
        dest_root.mkdir(exist_ok=True)
        dest = dest_root / row.path.name
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        try:
            shutil.move(str(row.path), str(dest))
        except OSError as exc:
            messagebox.showerror("Reject", str(exc))
            return
        self.rows.pop(idx)
        self.rejected += 1
        if self._selected >= len(self.rows):
            self._selected = max(0, len(self.rows) - 1)
        self._update_stats()
        self._clear_rows()
        self._relayout(force=True)
        self.on_status(f"В брак: {row.number}")

    def approve_current(self) -> None:
        if self.rows:
            self.approve_row(self._selected)

    def reject_current(self) -> None:
        if self.rows:
            self.reject_row(self._selected)

    def export_ready(self) -> None:
        if not self.run_dir:
            messagebox.showinfo("Экспорт", "Сначала выберите папку run_…")
            return
        approved_dir = self.run_dir / "approved"
        approved_dir.mkdir(exist_ok=True)
        items = sorted(
            [
                p
                for p in approved_dir.iterdir()
                if p.is_dir() and p.name.startswith("carousel_")
            ]
        )
        if not items:
            messagebox.showinfo(
                "Экспорт",
                "Пока нет одобренных каруселей.\n"
                "Нажмите «✓ Одобрено» на готовых строках.",
            )
            return
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out = Path(__file__).resolve().parent / "out" / f"export_{stamp}"
        out.mkdir(parents=True, exist_ok=True)
        for src in items:
            dest = out / src.name
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(src, dest)
        self.on_status(f"Экспорт: {len(items)} → {out}")
        try:
            subprocess.Popen(["explorer", str(out)])
        except Exception:
            pass
        messagebox.showinfo("Экспорт", f"Скопировано {len(items)} каруселей:\n{out}")

    def open_folder(self) -> None:
        if not self.rows:
            if self.run_dir:
                subprocess.Popen(["explorer", str(self.run_dir)])
            return
        folder = self.rows[self._selected].path
        try:
            subprocess.Popen(["explorer", str(folder)])
        except Exception as exc:
            messagebox.showerror("Open", str(exc))

    # ----------------------------------------------------------- hotkeys
    def handle_key(self, event: tk.Event) -> str | None:  # type: ignore[type-arg]
        if not self._active:
            return None
        code = int(event.keycode)
        keysym = (event.keysym or "").lower()

        if keysym == "escape" or code == _VK_ESCAPE:
            self._close_popover()
            return "break"
        if not self.rows:
            return None
        if code in (_VK_X, _VK_DELETE, _VK_BACK) or keysym in (
            "delete",
            "backspace",
        ):
            self.reject_current()
            return "break"
        if code == _VK_A or keysym == "a":
            self.approve_current()
            return "break"
        if code == _VK_O:
            self.open_folder()
            return "break"
        if keysym in ("down", "j"):
            self._selected = min(len(self.rows) - 1, self._selected + 1)
            self._ensure_selected_visible()
            self._relayout(force=True)
            return "break"
        if keysym in ("up", "k"):
            self._selected = max(0, self._selected - 1)
            self._ensure_selected_visible()
            self._relayout(force=True)
            return "break"
        return None

    def _ensure_selected_visible(self) -> None:
        if not self.rows:
            return
        y0 = self._selected * ROW_H
        y1 = y0 + ROW_H
        top = self.canvas.canvasy(0)
        bot = top + max(200, self.canvas.winfo_height() or 600)
        total = self._scrollregion_h()
        if y0 < top:
            self.canvas.yview_moveto(y0 / total)
        elif y1 > bot:
            self.canvas.yview_moveto(max(0, (y1 - (bot - top)) / total))
