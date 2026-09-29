#!/usr/bin/env python3
"""
Carousel Factory — поиск живых фото Pinterest + типографика + выбор фона.

Локальная генерация текстов: Google Gemini (gemini-3.1-flash-lite, core/llm_engine.py).
Ключ: GEMINI_API_KEY в .env

Зависимости: tkinter, Pillow, httpx, google-genai
Запуск:  python carousel_factory_app.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from core.batch_factory import run_batch
from core.caption_engine import generate_caption
from core.usage_meter import UsageEvent, UsageSnapshot, get_meter
from core.color_matcher import (
    get_color_profile,
    get_harmony_score,
)
from core.harvester import (
    CandidateImage,
    PinterestHarvester,
    dedupe_carousel_pools,
    finalize_photo_query,
)
from core.preference_learner import PreferenceLearner
from core.visual_judge import combined_rank_score
from dotenv import load_dotenv

from core.llm_engine import (
    DEFAULT_GEMINI_MODEL,
    OllamaGenerator,
    OllamaUnavailable,
    UGC_QUERY_MARKERS,
)
from core.renderer import render_preview, render_slide
from photo_library_panel import PhotoLibraryPanel
from review_panel import ReviewPanel
from ui_hotkeys import enable_edit_hotkeys
from core.photo_vault import get_photo_vault
# ---------------------------------------------------------------------------
# Константы UI
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "out"
SESSION_TMP = ROOT / "data" / "cache" / "sessions" / "current"
MIN_SLIDES = 6
MAX_SLIDES = 9
CANDIDATES = 10         # единый бюджет с batch_factory
MIN_KEEP = 3
MAX_ALTS_SAVED = 6

MAIN_PREVIEW_W = 270
MAIN_PREVIEW_H = 360  # 3:4
THUMB_W = 72
THUMB_H = 96

BG = "#1a1b1e"
PANEL = "#24262b"
PANEL2 = "#2c2f36"
FG = "#f2f2f2"
MUTED = "#9aa0a6"
ACCENT = "#3ddc97"
ACCENT_DARK = "#2bb67a"
BORDER = "#3a3f48"


# ---------------------------------------------------------------------------
# Генерация поисковых запросов
# ---------------------------------------------------------------------------

def _strip_emoji(text: str) -> str:
    return re.sub(
        r"[\U00010000-\U0010ffff\u2600-\u27bf\ufe0f]",
        "",
        text,
    ).strip()


def _has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text))


def parse_topics_input(raw_text: str) -> list[str]:
    """
    Smart parser: одна тема или список (по строке / 1. тема / - тема).
    """
    topics: list[str] = []
    seen: set[str] = set()
    for line in (raw_text or "").splitlines():
        cleaned = re.sub(r"^\s*(\d+[\.\)]|\-|\*)\s*", "", line).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        topics.append(cleaned)
    return topics


def aesthetic_query_for_slide(text: str, index: int) -> str:
    """
    Фоллбэк Pinterest-запрос: human situation/pose (3–4 слова).
    Без keyword→object (coffee cups / steering wheel / notebook desk запрещены).
    """
    from core.harvester import situation_query_for_slide

    return situation_query_for_slide(_strip_emoji(text or ""), index)


def _ensure_profiles(slide: SlideState) -> None:
    """Кэширует цветовые профили кандидатов (быстро, 64×64)."""
    if len(slide.color_profiles) == len(slide.candidates) and slide.color_profiles:
        return
    slide.color_profiles = [
        get_color_profile(c.image) for c in slide.candidates
    ]


def _reorder_slide(slide: SlideState, order: list[int], scores_orig: list[float]) -> None:
    """Переставляет candidates/profiles/scores по order; selected → 0."""
    if not order:
        slide.harmony_scores = []
        slide.selected = 0
        slide.preview_cache.clear()
        return
    slide.candidates = [slide.candidates[i] for i in order]
    if slide.color_profiles and len(slide.color_profiles) == len(order):
        slide.color_profiles = [slide.color_profiles[i] for i in order]
    slide.harmony_scores = [scores_orig[i] for i in order]
    slide.selected = 0
    slide.preview_cache.clear()
    slide.thumb_photos.clear()


def _apply_combined_ranking(slide: SlideState) -> None:
    """
    Ранг: rel×0.40 + taste×0.35 + ugc×0.25.
    Лучший кандидат → selected=0.
    """
    if not slide.candidates:
        return
    n = len(slide.candidates)
    if len(slide.harmony_scores) != n:
        slide.harmony_scores = [
            float(getattr(c, "harmony_score", 100.0) or 100.0)
            for c in slide.candidates
        ]
    scored: list[tuple[float, int]] = []
    for i, cand in enumerate(slide.candidates):
        rel = float(getattr(cand, "text_relevance", 0.5) or 0.5)
        ugc = float(getattr(cand, "ugc_score", 0.5) or 0.5)
        taste = (
            float(cand.taste_score)
            if getattr(cand, "taste_scored", False)
            else 0.5
        )
        harm = float(slide.harmony_scores[i] if i < len(slide.harmony_scores) else 0)
        cand.harmony_score = harm
        combined = combined_rank_score(
            ugc, taste=taste, harmony=harm, relevance=rel
        )
        cand.combined_score = combined
        scored.append((combined, i))
    scored.sort(key=lambda x: x[0], reverse=True)
    order = [i for _, i in scored]
    scores_orig = list(slide.harmony_scores)
    _reorder_slide(slide, order, scores_orig)


def _relevance_ugc_harmony_label(
    cand: CandidateImage | None, harmony: float | None
) -> str:
    """Бейдж: Смысл · Вкус · UGC · Гармония."""
    if cand is None:
        return "🎯 Смысл: — · ✨ Вкус: — · 📱 UGC: — · 🎨 Гармония: —"
    if getattr(cand, "text_relevance_scored", False):
        rel_part = f"🎯 Смысл: {float(cand.text_relevance):.0%}"
    else:
        rel_part = "🎯 Смысл: —"
    if getattr(cand, "taste_scored", False):
        taste_part = f"✨ Вкус: {float(cand.taste_score):.0%}"
    else:
        taste_part = "✨ Вкус: —"
    if getattr(cand, "ugc_scored", False):
        ugc_part = f"📱 UGC: {float(cand.ugc_score):.0%}"
    else:
        ugc_part = "📱 UGC: —"
    if harmony is None:
        harm_part = "🎨 Гармония: —"
    else:
        h01 = float(harmony) / 100.0 if float(harmony) > 1.0 else float(harmony)
        harm_part = f"🎨 Гармония: {h01:.0%}"
    return f"{rel_part} · {taste_part} · {ugc_part} · {harm_part}"


def _ugc_harmony_label(cand: CandidateImage | None, harmony: float | None) -> str:
    """Совместимость: полный бейдж смысла/UGC/гармонии."""
    return _relevance_ugc_harmony_label(cand, harmony)


def _taste_harmony_label(cand: CandidateImage | None, harmony: float | None) -> str:
    """Совместимость: полный бейдж смысла/UGC/гармонии."""
    return _relevance_ugc_harmony_label(cand, harmony)


def _taste_label(cand: CandidateImage | None) -> str:
    """Короткий бейдж вкуса (под главным превью)."""
    if cand is None or not getattr(cand, "taste_scored", False):
        return "✨ Вкус: —"
    pct = int(round(float(cand.taste_score) * 100))
    return f"✨ Вкус: {pct}%"


def _apply_color_harmony(slides: list[SlideState]) -> None:
    """
    Слайд 1 = якорь. Гармония к якорю + смысл + UGC → combined rank.
    """
    if not slides:
        return

    for slide in slides:
        if slide.candidates:
            _ensure_profiles(slide)

    anchor_slide = slides[0]
    if not anchor_slide.candidates:
        return

    _ensure_profiles(anchor_slide)
    # для якоря гармония к самому себе = 100
    anchor_slide.harmony_scores = [100.0] * len(anchor_slide.candidates)
    for c in anchor_slide.candidates:
        c.harmony_score = 100.0
    _apply_combined_ranking(anchor_slide)

    anchor = anchor_slide.color_profiles[anchor_slide.selected]
    for slide in slides[1:]:
        if not slide.candidates:
            slide.harmony_scores = []
            continue
        _ensure_profiles(slide)
        scores_orig = [
            get_harmony_score(anchor, p) for p in slide.color_profiles
        ]
        slide.harmony_scores = scores_orig
        for c, h in zip(slide.candidates, scores_orig):
            c.harmony_score = float(h)
        _apply_combined_ranking(slide)


def _rerank_followers(slides: list[SlideState]) -> None:
    """Переранжировать слайды 2–N под текущий выбранный фон слайда 1."""
    if len(slides) < 2 or not slides[0].candidates:
        return
    anchor_slide = slides[0]
    _ensure_profiles(anchor_slide)
    anchor = anchor_slide.selected_profile()
    if not anchor:
        return
    anchor_slide.harmony_scores = [
        get_harmony_score(anchor, p) for p in anchor_slide.color_profiles
    ]
    for slide in slides[1:]:
        if not slide.candidates:
            continue
        _ensure_profiles(slide)
        slide.harmony_scores = [
            get_harmony_score(anchor, p) for p in slide.color_profiles
        ]
        _apply_combined_ranking(slide)


# ---------------------------------------------------------------------------
# Модель слайда
# ---------------------------------------------------------------------------

@dataclass
class SlideState:
    index: int
    text: str
    query: str = ""
    candidates: list[CandidateImage] = field(default_factory=list)
    selected: int = 0
    color_profiles: list[dict[str, Any]] = field(default_factory=list)
    harmony_scores: list[float] = field(default_factory=list)
    main_photo: ImageTk.PhotoImage | None = field(default=None, repr=False)
    thumb_photos: list[ImageTk.PhotoImage] = field(default_factory=list, repr=False)
    preview_cache: dict[int, Image.Image] = field(default_factory=dict, repr=False)

    def selected_candidate(self) -> CandidateImage | None:
        if not self.candidates:
            return None
        idx = max(0, min(self.selected, len(self.candidates) - 1))
        return self.candidates[idx]

    def selected_harmony(self) -> float | None:
        if not self.harmony_scores:
            return None
        idx = max(0, min(self.selected, len(self.harmony_scores) - 1))
        return self.harmony_scores[idx]

    def selected_profile(self) -> dict[str, Any] | None:
        if not self.color_profiles:
            return None
        idx = max(0, min(self.selected, len(self.color_profiles) - 1))
        return self.color_profiles[idx]


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class CarouselFactoryApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Carousel Factory — Batch + Review")
        self.root.geometry("1280x860")
        self.root.minsize(1020, 700)
        self.root.configure(bg=BG)

        self.harvester = PinterestHarvester(on_status=self._set_status)
        self.llm = OllamaGenerator()
        try:
            from core.query_patterns import get_query_pattern_manager

            mgr = get_query_pattern_manager()
            print(
                f"✓ Загружено вирусных паттернов: {mgr.n_tags} тегов "
                f"из data/viral_query_patterns.json"
            )
        except Exception as exc:
            print(f"⚠ viral_query_patterns не загружены: {exc}")
        self._busy = False
        self._batch_stop = False
        self._last_run_dir: Path | None = None
        self._slides: list[SlideState] = []
        # Явные алиасы сессии (полная изоляция между темами)
        self.candidates: dict[int, list] = {}
        self.selected_backgrounds: dict[int, Any] = {}
        self.current_anchor: CandidateImage | None = None
        self._llm_queries: list[str] | None = None
        self._llm_query_fingerprint: tuple[str, ...] | None = None
        self._quality_meta: dict[str, Any] = {}
        self._last_export: Path | None = None
        self._photo_refs: list[ImageTk.PhotoImage] = []
        self._slide_frames: list[tk.Frame] = []
        self._quality_badge: tk.Label | None = None
        self._learner = PreferenceLearner()
        self._teacher_photos: list[ImageTk.PhotoImage] = []
        self._teacher_side_a: dict[str, Any] = {}
        self._teacher_side_b: dict[str, Any] = {}
        self._teacher_busy = False
        self._teacher_ready = False
        self._teacher_round_id = 0
        self._teacher_topic = ""
        self._related_busy = False
        self._style_anchor_pin: str | None = None
        self._style_related_cache: list[CandidateImage] = []

        self._build_style()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self._warm, daemon=True).start()

    # -- style / layout -----------------------------------------------------

    def _build_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background=PANEL, foreground=FG)
        style.configure(
            "Muted.TLabel",
            background=PANEL,
            foreground=MUTED,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Title.TLabel",
            background=PANEL,
            foreground=FG,
            font=("Segoe UI", 12, "bold"),
        )
        style.configure(
            "Status.TLabel",
            background=PANEL2,
            foreground=MUTED,
            font=("Segoe UI", 9),
        )

    def _build_ui(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        factory = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(factory, text="  Фабрика  ")

        review_host = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(review_host, text="  👀 Быстрый отсмотр  ")
        self.review = ReviewPanel(
            review_host,
            on_status=self._set_status,
            harvester=self.harvester,
        )
        self.review.pack(fill=tk.BOTH, expand=True)

        teacher_host = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(teacher_host, text="  🎓 Обучение (Teacher Mode)  ")
        self._build_teacher_tab(teacher_host)

        vault_host = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(vault_host, text="  🖼️ Библиотека фото  ")
        self.photo_library = PhotoLibraryPanel(
            vault_host,
            on_status=self._set_status,
            vault=get_photo_vault(),
        )
        self.photo_library.pack(fill=tk.BOTH, expand=True)

        # LEFT
        left = tk.Frame(factory, bg=PANEL, width=300)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)

        ttk.Label(left, text="Тема карусели", style="Title.TLabel").pack(
            anchor=tk.W, padx=14, pady=(14, 4)
        )
        ttk.Label(
            left,
            text=f"Gemini {DEFAULT_GEMINI_MODEL} · RAG few-shot (playbook)",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, padx=14, pady=(0, 6))

        self._topic_ph = (
            "Введи 1 тему для генерации вариаций, ИЛИ список тем "
            "(по одной на строку / 1. тема, 2. тема...)"
        )
        self.topic_text = tk.Text(
            left,
            height=5,
            font=("Segoe UI", 10),
            bg="#1e2025",
            fg=MUTED,
            insertbackground=FG,
            relief=tk.FLAT,
            wrap=tk.WORD,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            padx=8,
            pady=6,
        )
        self.topic_text.pack(fill=tk.X, padx=14, pady=(0, 4))
        self.topic_text.insert("1.0", self._topic_ph)
        self.topic_text.bind("<FocusIn>", self._topic_focus_in)
        self.topic_text.bind("<FocusOut>", self._topic_focus_out)
        self.topic_text.bind("<KeyRelease>", self._on_topic_changed)
        enable_edit_hotkeys(self.topic_text)

        self.topic_mode_var = tk.StringVar(value="🎯 Режим: 1 тема")
        self.topic_mode_label = tk.Label(
            left,
            textvariable=self.topic_mode_var,
            bg=PANEL,
            fg=ACCENT,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
            justify=tk.LEFT,
            wraplength=270,
        )
        self.topic_mode_label.pack(fill=tk.X, padx=14, pady=(0, 8))

        ttk.Label(left, text="Продукт / Решение (опционально)", style="Title.TLabel").pack(
            anchor=tk.W, padx=14, pady=(4, 4)
        )
        self.product_var = tk.StringVar()
        self.product_entry = tk.Entry(
            left,
            textvariable=self.product_var,
            font=("Segoe UI", 10),
            bg="#1e2025",
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.product_entry.pack(fill=tk.X, padx=14, pady=(0, 4), ipady=6)
        # placeholder через insert+focus (tk.Entry на Win без native placeholder)
        self._product_ph = "Приложение FocusFlow: лимит 3 задачи в день"
        self.product_entry.insert(0, self._product_ph)
        self.product_entry.configure(fg=MUTED)
        self.product_entry.bind("<FocusIn>", self._product_focus_in)
        self.product_entry.bind("<FocusOut>", self._product_focus_out)
        enable_edit_hotkeys(self.product_entry)

        self.gen_btn = tk.Button(
            left,
            text="🤖 Сгенерировать через Gemini",
            bg=ACCENT,
            fg="#102018",
            activebackground=ACCENT_DARK,
            activeforeground="#102018",
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=9,
            cursor="hand2",
            command=self.start_llm_generate,
        )
        self.gen_btn.pack(fill=tk.X, padx=14, pady=(8, 8))

        batch_row = tk.Frame(left, bg=PANEL)
        batch_row.pack(fill=tk.X, padx=14, pady=(0, 4))
        ttk.Label(batch_row, text="Количество каруселей", style="Muted.TLabel").pack(
            anchor=tk.W
        )
        self.batch_count = tk.IntVar(value=10)
        self._batch_spin = tk.Spinbox(
            batch_row,
            from_=1,
            to=50,
            textvariable=self.batch_count,
            width=6,
            font=("Segoe UI", 11),
            bg="#1e2025",
            fg=FG,
            buttonbackground=PANEL2,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=BORDER,
            command=self._refresh_topic_mode_badge,
        )
        self._batch_spin.pack(anchor=tk.W, pady=(4, 0))
        self.batch_count.trace_add(
            "write", lambda *_a: self._refresh_topic_mode_badge()
        )

        self.batch_btn = tk.Button(
            left,
            text="🚀 Запустить фабрику (Batch Run)",
            bg="#4f8cff",
            fg="#0a1220",
            activebackground="#3a6fd8",
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=10,
            cursor="hand2",
            command=self.start_batch,
        )
        self.batch_btn.pack(fill=tk.X, padx=14, pady=(8, 6))

        self.stop_batch_btn = tk.Button(
            left,
            text="⏹ Стоп после текущей",
            bg=PANEL2,
            fg=FG,
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            padx=10,
            pady=6,
            cursor="hand2",
            state=tk.DISABLED,
            command=self.stop_batch,
        )
        self.stop_batch_btn.pack(fill=tk.X, padx=14, pady=(0, 10))
        self.root.after(50, self._refresh_topic_mode_badge)

        ttk.Separator(left, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=14, pady=(0, 10))

        ttk.Label(left, text="Слайды (5–9)", style="Title.TLabel").pack(
            anchor=tk.W, padx=14, pady=(0, 4)
        )
        ttk.Label(
            left,
            text="Каждая строка — текст одного слайда",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, padx=14, pady=(0, 8))

        self.slides_text = tk.Text(
            left,
            wrap=tk.WORD,
            font=("Segoe UI", 11),
            bg="#1e2025",
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            padx=8,
            pady=8,
            height=10,
            undo=True,
        )
        self.slides_text.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 10))
        self.slides_text.insert(
            "1.0",
            "7 habits that quietly freeze your potential\n"
            "You don't lack discipline — you lack a container\n"
            "One rule beats a motivational spiral every time\n"
            "I keep the day to three moves, nothing else\n"
            "Save this for tomorrow morning",
        )
        enable_edit_hotkeys(self.slides_text)

        self.find_btn = tk.Button(
            left,
            text="Найти фото и собрать превью",
            bg=ACCENT,
            fg="#102018",
            activebackground=ACCENT_DARK,
            activeforeground="#102018",
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=10,
            cursor="hand2",
            command=self.start_harvest,
        )
        self.find_btn.pack(fill=tk.X, padx=14, pady=(0, 8))

        self.taste_btn = tk.Button(
            left,
            text="✨ Обучить фильтр вкуса",
            bg=PANEL2,
            fg=ACCENT,
            activebackground=BORDER,
            activeforeground=FG,
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=8,
            cursor="hand2",
            command=self.open_taste_trainer,
        )
        self.taste_btn.pack(fill=tk.X, padx=14, pady=(0, 12))

        # CENTER + BOTTOM
        right = tk.Frame(factory, bg=BG)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        header = tk.Frame(right, bg=PANEL2)
        header.pack(fill=tk.X, side=tk.TOP)
        self.status_var = tk.StringVar(value="Готов. Batch или одиночная генерация.")
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel").pack(
            anchor=tk.W, padx=12, pady=(8, 2)
        )
        self.cost_var = tk.StringVar(
            value="API $0.0000 · in 0 · out 0 · calls 0  |  log: out/usage/"
        )
        tk.Label(
            header,
            textvariable=self.cost_var,
            bg=PANEL2,
            fg=ACCENT,
            font=("Consolas", 9, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=12, pady=(0, 4))
        self.progress = ttk.Progressbar(header, mode="determinate", maximum=100)
        self.progress.pack(fill=tk.X, padx=12, pady=(0, 8))

        bottom = tk.Frame(right, bg=PANEL, height=64)
        bottom.pack(fill=tk.X, side=tk.BOTTOM)
        bottom.pack_propagate(False)

        self.export_btn = tk.Button(
            bottom,
            text="Экспорт карусели",
            bg=ACCENT,
            fg="#102018",
            activebackground=ACCENT_DARK,
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=16,
            pady=8,
            cursor="hand2",
            state=tk.DISABLED,
            command=self.start_export,
        )
        self.export_btn.pack(side=tk.LEFT, padx=14, pady=12)

        self.open_btn = tk.Button(
            bottom,
            text="Открыть папку",
            bg=PANEL2,
            fg=FG,
            activebackground=BORDER,
            relief=tk.FLAT,
            font=("Segoe UI", 10),
            padx=14,
            pady=8,
            cursor="hand2",
            command=self.open_export_folder,
        )
        self.open_btn.pack(side=tk.LEFT, padx=(0, 14), pady=12)

        self.export_info = tk.Label(
            bottom,
            text="",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.export_info.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 14))

        # usage log strip (above export bar)
        log_wrap = tk.Frame(right, bg=PANEL2)
        log_wrap.pack(fill=tk.X, side=tk.BOTTOM)
        log_hdr = tk.Frame(log_wrap, bg=PANEL2)
        log_hdr.pack(fill=tk.X, padx=8, pady=(6, 0))
        tk.Label(
            log_hdr,
            text="Usage log (1× Gemini text · images $0)",
            bg=PANEL2,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Button(
            log_hdr,
            text="Открыть лог",
            bg=PANEL,
            fg=FG,
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            padx=8,
            cursor="hand2",
            command=self.open_usage_folder,
        ).pack(side=tk.RIGHT)
        self.usage_log = tk.Text(
            log_wrap,
            height=5,
            bg="#12131a",
            fg="#c8d0c0",
            insertbackground=FG,
            relief=tk.FLAT,
            font=("Consolas", 8),
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.usage_log.pack(fill=tk.X, padx=8, pady=(4, 8))

        body = tk.Frame(right, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.feed = tk.Frame(self.canvas, bg=BG)
        self._canvas_win = self.canvas.create_window((0, 0), window=self.feed, anchor="nw")
        self.feed.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        get_meter().add_listener(self._on_usage_event)
        self._append_usage_line(
            "session ready · 1 Gemini call/carousel (text) · images local $0"
        )

        # горячие клавиши отсмотра
        self.root.bind_all("<Key>", self._on_global_key)

    # -- Teacher Mode (Continuous Active Learning Arena) --------------------

    def _build_teacher_tab(self, host: tk.Frame) -> None:
        self._teacher_busy = False
        self._teacher_ready = False
        self._teacher_round_id = 0
        self._teacher_topic = ""

        top = tk.Frame(host, bg=PANEL, padx=14, pady=10)
        top.pack(fill=tk.X)

        tk.Label(
            top,
            text="Continuous Arena — Чемпион vs Претендент",
            bg=PANEL,
            fg=FG,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor=tk.W)

        self.teacher_info_var = tk.StringVar(value=self._learner.status_line())
        tk.Label(
            top,
            textvariable=self.teacher_info_var,
            bg=PANEL,
            fg=ACCENT,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(6, 4))

        tk.Label(
            top,
            text=(
                "1 / A / ←  Чемпион   ·   2 / B / →  Претендент   ·   "
                "Space  Оба хорошие   ·   X / 0  Оба плохие"
            ),
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(anchor=tk.W)

        topic_row = tk.Frame(top, bg=PANEL)
        topic_row.pack(fill=tk.X, pady=(10, 0))
        tk.Label(
            topic_row,
            text="Тема раунда:",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT)
        self.teacher_topic_var = tk.StringVar(value="Загрузка…")
        tk.Label(
            topic_row,
            textvariable=self.teacher_topic_var,
            bg=PANEL,
            fg=FG,
            font=("Segoe UI", 10),
            wraplength=900,
            justify=tk.LEFT,
            anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        self.teacher_status = tk.StringVar(value="Открой вкладку — первая пара подгрузится сама.")
        tk.Label(
            top,
            textvariable=self.teacher_status,
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill=tk.X, pady=(6, 0))

        # совместимость со старыми ссылками
        self.teacher_weights_var = self.teacher_info_var
        self.teacher_compare_btn = None  # type: ignore[assignment]

        arena = tk.Frame(host, bg=BG)
        arena.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._teacher_col_a = self._make_teacher_column(
            arena, "Чемпион (A) · Exploit", "A"
        )
        self._teacher_col_a.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        self._teacher_col_b = self._make_teacher_column(
            arena, "Претендент (B) · Explore", "B"
        )
        self._teacher_col_b.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

    def _make_teacher_column(self, parent: tk.Frame, title: str, side: str) -> tk.Frame:
        col = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        tk.Label(
            col,
            text=title,
            bg=PANEL,
            fg=FG,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor=tk.W, padx=10, pady=(10, 2))

        query_var = tk.StringVar(value="—")
        tk.Label(
            col,
            textvariable=query_var,
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
            wraplength=420,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=10, pady=(0, 8))

        thumbs = tk.Frame(col, bg=PANEL)
        thumbs.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        pick_btn = tk.Button(
            col,
            text=f"Выбрать {side}  [{'1' if side == 'A' else '2'}]",
            bg=PANEL2,
            fg=FG,
            activebackground=BORDER,
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=8,
            cursor="hand2",
            state=tk.DISABLED,
            command=lambda s=side: self._teacher_pick(s),
        )
        pick_btn.pack(fill=tk.X, padx=10, pady=(0, 12))

        if side == "A":
            self._teacher_query_a = query_var
            self._teacher_thumbs_a = thumbs
            self._teacher_pick_a = pick_btn
        else:
            self._teacher_query_b = query_var
            self._teacher_thumbs_b = thumbs
            self._teacher_pick_b = pick_btn
        return col

    def _refresh_teacher_info(self) -> None:
        self.teacher_info_var.set(self._learner.status_line())

    def _teacher_start_round(self, *, skipped: bool = False) -> None:
        """Следующая тема + чемпион/претендент — сразу в фоне."""
        if self._teacher_busy:
            return
        self._teacher_busy = True
        self._teacher_ready = False
        self._teacher_round_id += 1
        round_id = self._teacher_round_id
        topic = self._learner.get_next_training_topic()
        self._teacher_topic = topic
        query_a, query_b = self._learner.generate_competing_queries(topic)

        self.teacher_topic_var.set(topic)
        self._teacher_query_a.set(query_a)
        self._teacher_query_b.set(query_b)
        self._teacher_pick_a.configure(state=tk.DISABLED)
        self._teacher_pick_b.configure(state=tk.DISABLED)
        for host in (self._teacher_thumbs_a, self._teacher_thumbs_b):
            for w in host.winfo_children():
                w.destroy()
            tk.Label(
                host, text="Загрузка…", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)
            ).pack(anchor=tk.W)

        status = "Оба хорошие → следующий раунд…" if skipped else "Ищем UGC-пару…"
        self.teacher_status.set(status)
        self._refresh_teacher_info()

        threading.Thread(
            target=self._teacher_compare_worker,
            args=(topic, query_a, query_b, round_id),
            daemon=True,
        ).start()

    def _teacher_compare_worker(
        self,
        slide_text: str,
        query_a: str,
        query_b: str,
        round_id: int,
    ) -> None:
        try:
            # отдельный клиент не обязателен — сброс used между раундами
            self.harvester.reset_used()
            cands_a, _ = self.harvester.harvest_for_query(
                query_a, limit=3, slide_text=slide_text
            )
            cands_b, _ = self.harvester.harvest_for_query(
                query_b, limit=3, slide_text=slide_text
            )
            err = None
        except Exception as exc:
            cands_a, cands_b, err = [], [], str(exc)
        self.root.after(
            0,
            lambda: self._teacher_compare_done(
                cands_a, cands_b, query_a, query_b, err, round_id
            ),
        )

    def _teacher_compare_done(
        self,
        cands_a: list[CandidateImage] | None,
        cands_b: list[CandidateImage] | None,
        query_a: str,
        query_b: str,
        error: str | None,
        round_id: int,
    ) -> None:
        if round_id != self._teacher_round_id:
            return  # устаревший раунд
        self._teacher_busy = False
        if error:
            self.teacher_status.set(f"Ошибка: {error} · Space — ещё раз")
            self._teacher_ready = True
            return
        cands_a = cands_a or []
        cands_b = cands_b or []
        self._teacher_side_a = {"query": query_a, "cands": cands_a}
        self._teacher_side_b = {"query": query_b, "cands": cands_b}
        self._teacher_query_a.set(query_a)
        self._teacher_query_b.set(query_b)
        self._teacher_photos.clear()
        self._fill_teacher_thumbs(self._teacher_thumbs_a, cands_a)
        self._fill_teacher_thumbs(self._teacher_thumbs_b, cands_b)
        self._teacher_pick_a.configure(state=tk.NORMAL if cands_a else tk.DISABLED)
        self._teacher_pick_b.configure(state=tk.NORMAL if cands_b else tk.DISABLED)
        self._teacher_ready = True
        if not cands_a and not cands_b:
            self.teacher_status.set("Пусто · Space — следующий раунд")
        else:
            self.teacher_status.set(
                f"A={len(cands_a)} · B={len(cands_b)} · жми 1/2 или ←/→"
            )
        self._refresh_teacher_info()

    def _fill_teacher_thumbs(
        self, host: tk.Frame, cands: list[CandidateImage]
    ) -> None:
        for w in host.winfo_children():
            w.destroy()
        if not cands:
            tk.Label(
                host, text="Нет фото", bg=PANEL, fg="#c0392b", font=("Segoe UI", 10)
            ).pack(anchor=tk.W)
            return
        row = tk.Frame(host, bg=PANEL)
        row.pack(anchor=tk.W)
        for cand in cands[:3]:
            try:
                thumb = self._make_thumb(cand.image)
                thumb = thumb.resize((110, 146), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(thumb)
            except Exception:
                continue
            self._teacher_photos.append(photo)
            lbl = tk.Label(row, image=photo, bg=PANEL2)
            lbl.pack(side=tk.LEFT, padx=(0, 8), pady=4)

    def _teacher_pick(self, side: str) -> None:
        if not self._teacher_ready or self._teacher_busy:
            return
        a = self._teacher_side_a
        b = self._teacher_side_b
        if not a.get("query") or not b.get("query"):
            return
        if side == "A":
            if not a.get("cands"):
                return
            winner, loser, label = a["query"], b["query"], "А"
        else:
            if not b.get("cands"):
                return
            winner, loser, label = b["query"], a["query"], "B"

        self._teacher_ready = False
        self._learner.log_choice(winner, loser)
        self._refresh_teacher_info()
        self.teacher_status.set(f"Выбор {label} учтён → следующий раунд…")
        # без пауз и без модалок — сразу новый раунд
        self._teacher_start_round()

    def _teacher_skip(self) -> None:
        """Space = оба хорошие: лёгкий плюс обеим стратегиям, затем следующий раунд."""
        if self._teacher_busy:
            return
        a = self._teacher_side_a
        b = self._teacher_side_b
        if self._teacher_ready and a.get("query") and b.get("query"):
            self._learner.log_both_good(str(a["query"]), str(b["query"]))
            self._refresh_teacher_info()
            self.teacher_status.set("Оба хорошие (+0.5) → следующий раунд…")
        self._teacher_ready = False
        self._teacher_start_round(skipped=True)

    def _teacher_both_bad(self) -> None:
        """X / 0 = оба плохие: штраф обеим стратегиям, затем следующий раунд."""
        if self._teacher_busy:
            return
        a = self._teacher_side_a
        b = self._teacher_side_b
        if self._teacher_ready and a.get("query") and b.get("query"):
            self._learner.log_both_bad(str(a["query"]), str(b["query"]))
            self._refresh_teacher_info()
            self.teacher_status.set("Оба плохие (−0.5) → следующий раунд…")
        self._teacher_ready = False
        self._teacher_start_round(skipped=True)

    def _teacher_on_key(self, event: tk.Event) -> str | None:  # type: ignore[type-arg]
        """Горячие клавиши: 1/a/Left, 2/b/Right, Space=оба ок, X/0=оба плохие."""
        key = (event.keysym or "").lower()
        char = (event.char or "").lower()
        if key in ("1", "left", "a") or char in ("1", "a"):
            self._teacher_pick("A")
            return "break"
        if key in ("2", "right", "b") or char in ("2", "b"):
            self._teacher_pick("B")
            return "break"
        if key in ("space",):
            self._teacher_skip()
            return "break"
        if key in ("x", "0") or char in ("x", "0"):
            self._teacher_both_bad()
            return "break"
        return None

    def _on_tab_changed(self, _event: object | None = None) -> None:
        try:
            tab = self.notebook.index(self.notebook.select())
        except Exception:
            tab = 0
        self.review.set_active(tab == 1)
        # Teacher Mode = 3-я вкладка (index 2)
        if tab == 2:
            self._refresh_teacher_info()
            if not self._teacher_busy and self._teacher_round_id == 0:
                self.root.after(80, self._teacher_start_round)
            elif not self._teacher_busy and not self._teacher_ready and self._teacher_round_id > 0:
                pass
            elif not self._teacher_busy and self._teacher_round_id > 0 and not self._teacher_side_a.get("cands"):
                self.root.after(80, self._teacher_start_round)
        # Библиотека фото = 4-я вкладка (index 3)
        if tab == 3:
            self.root.after(40, self.photo_library.refresh)

    def _on_global_key(self, event: tk.Event) -> str | None:  # type: ignore[type-arg]
        try:
            tab = self.notebook.index(self.notebook.select())
        except Exception:
            tab = 0

        # Teacher arena — клавиши работают даже если фокус не на кнопке
        if tab == 2:
            w = event.widget
            cls = w.winfo_class() if w else ""
            # не мешать обычному набору, если вдруг есть Text (legacy)
            if cls in ("Entry", "Text", "TEntry", "Spinbox"):
                return None
            handled = self._teacher_on_key(event)
            if handled:
                return handled

        # Review hotkeys
        w = event.widget
        cls = w.winfo_class() if w else ""
        if cls in ("Entry", "Text", "TEntry", "Spinbox"):
            return None
        return self.review.handle_key(event)

    def _on_canvas_configure(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self.canvas.itemconfigure(self._canvas_win, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # -- helpers ------------------------------------------------------------

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_var.set(text))

    def _on_usage_event(self, ev: UsageEvent, snap: UsageSnapshot) -> None:
        def apply() -> None:
            self.cost_var.set(
                f"{snap.line()}  |  session {get_meter().session_id}"
            )
            # Картинки локальные — в лог расходов не пишем.
            if ev.kind in ("judge_local", "judge_gemini", "session"):
                if ev.kind == "session":
                    self._append_usage_line(f"{ev.ts}  RESET  {ev.note}")
                return
            # Одна строка на текстовый вызов Gemini
            if ev.kind in ("gemini_text_gen", "carousel"):
                self._append_usage_line(
                    f"gemini_text_gen ${ev.cost_usd:.4f}"
                )
                return
            # caption/critic и прочее — не показываем (должны быть отключены)
            return

        self.root.after(0, apply)

    def _append_usage_line(self, line: str) -> None:
        try:
            self.usage_log.configure(state=tk.NORMAL)
            self.usage_log.insert(tk.END, line + "\n")
            # keep last ~200 lines
            total = int(self.usage_log.index("end-1c").split(".")[0])
            if total > 220:
                self.usage_log.delete("1.0", f"{total - 200}.0")
            self.usage_log.see(tk.END)
            self.usage_log.configure(state=tk.DISABLED)
        except Exception:
            pass

    def open_usage_folder(self) -> None:
        folder = get_meter().log_dir
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(folder))  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showinfo("Usage log", f"{folder}\n{exc}")

    def _set_busy(self, busy: bool) -> None:
        def apply() -> None:
            self._busy = busy
            state = tk.DISABLED if busy else tk.NORMAL
            self.find_btn.configure(state=state)
            self.gen_btn.configure(state=state)
            self.batch_btn.configure(state=state)
            if busy:
                self.export_btn.configure(state=tk.DISABLED)
                self.stop_batch_btn.configure(state=tk.NORMAL)
            else:
                self.stop_batch_btn.configure(state=tk.DISABLED)
                if self._slides:
                    self.export_btn.configure(state=tk.NORMAL)

        self.root.after(0, apply)

    def _set_progress(self, value: float, maximum: float = 100.0) -> None:
        def apply() -> None:
            self.progress.configure(maximum=max(1.0, maximum))
            self.progress["value"] = value

        self.root.after(0, apply)

    def _warm(self) -> None:
        try:
            self.harvester.warm()
            self._set_status("Готов. Введите 3–8 слайдов и нажмите поиск.")
        except Exception as exc:
            self._set_status(f"Сессия Pinterest: предупреждение ({exc.__class__.__name__})")

    def _parse_slides(self) -> list[str] | None:
        raw = self.slides_text.get("1.0", "end-1c")
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if len(lines) < MIN_SLIDES:
            messagebox.showwarning(
                "Мало слайдов",
                f"Нужно минимум {MIN_SLIDES} слайда, сейчас {len(lines)}.",
            )
            return None
        if len(lines) > MAX_SLIDES:
            messagebox.showwarning(
                "Много слайдов",
                f"Максимум {MAX_SLIDES} слайдов, сейчас {len(lines)}.",
            )
            return None
        return lines

    # -- Gemini generate ----------------------------------------------------

    def _product_focus_in(self, _event: tk.Event | None = None) -> None:  # type: ignore[type-arg]
        if self.product_entry.get() == self._product_ph:
            self.product_entry.delete(0, tk.END)
            self.product_entry.configure(fg=FG)

    def _product_focus_out(self, _event: tk.Event | None = None) -> None:  # type: ignore[type-arg]
        if not self.product_entry.get().strip():
            self.product_entry.insert(0, self._product_ph)
            self.product_entry.configure(fg=MUTED)

    def _product_value(self) -> str:
        raw = self.product_entry.get().strip()
        if not raw or raw == self._product_ph:
            return ""
        return raw

    def _topic_is_placeholder(self) -> bool:
        raw = self.topic_text.get("1.0", "end").strip()
        return (not raw) or raw == self._topic_ph

    def _topic_raw(self) -> str:
        if self._topic_is_placeholder():
            return ""
        return self.topic_text.get("1.0", "end").strip()

    def _topics_from_ui(self) -> list[str]:
        return parse_topics_input(self._topic_raw())

    def _topic_focus_in(self, _event: tk.Event | None = None) -> None:  # type: ignore[type-arg]
        if self._topic_is_placeholder():
            self.topic_text.delete("1.0", tk.END)
            self.topic_text.configure(fg=FG)

    def _topic_focus_out(self, _event: tk.Event | None = None) -> None:  # type: ignore[type-arg]
        if not self.topic_text.get("1.0", "end").strip():
            self.topic_text.insert("1.0", self._topic_ph)
            self.topic_text.configure(fg=MUTED)
        self._refresh_topic_mode_badge()

    def _on_topic_changed(self, _event: tk.Event | None = None) -> None:  # type: ignore[type-arg]
        self._refresh_topic_mode_badge()

    def _refresh_topic_mode_badge(self) -> None:
        topics = self._topics_from_ui()
        n = len(topics)
        try:
            variations = max(1, int(self.batch_count.get()))
        except (TypeError, ValueError):
            variations = 10
        if n > 1:
            self.topic_mode_var.set(
                f"📋 Режим: Мульти-темы ({n} шт. — по 1 карусели на тему)"
            )
            self.topic_mode_label.configure(fg="#7ec8ff")
            if getattr(self, "_batch_spin", None) is not None:
                self._batch_spin.configure(state=tk.DISABLED)
        elif n == 1:
            self.topic_mode_var.set(
                f"🎯 Режим: 1 тема ({variations} вариаций)"
            )
            self.topic_mode_label.configure(fg=ACCENT)
            if getattr(self, "_batch_spin", None) is not None:
                self._batch_spin.configure(state=tk.NORMAL)
        else:
            self.topic_mode_var.set("🎯 Режим: введи тему или список тем")
            self.topic_mode_label.configure(fg=MUTED)
            if getattr(self, "_batch_spin", None) is not None:
                self._batch_spin.configure(state=tk.NORMAL)

    def _clear_session_tmpdir(self) -> None:
        """Полностью очистить временную папку текущей сессии (без пересечений тем)."""
        import shutil

        try:
            if SESSION_TMP.exists():
                shutil.rmtree(SESSION_TMP, ignore_errors=True)
            SESSION_TMP.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            print(f"[WARNING] не удалось очистить session tmp: {exc}")

    def _reset_generation_session(self, *, keep_llm_queries: bool = False) -> None:
        """
        Полная изоляция между темами: RAM-кандидаты, якорь стиля, tmp.
        Не трогаем тексты в UI — только фото/кэш сессии.
        """
        self.candidates = {}
        self.selected_backgrounds = {}
        self.current_anchor = None
        self._slides = []
        self._style_related_cache = []
        self._style_anchor_pin = None
        self._quality_meta = {}
        if not keep_llm_queries:
            self._llm_queries = None
            self._llm_query_fingerprint = None
        self.harvester.reset_used()
        self._clear_session_tmpdir()
        print("[session] RAM + tmp сброшены — новая тема без чужого кэша картинок")

    def start_llm_generate(self) -> None:
        if self._busy:
            return
        topics = self._topics_from_ui()
        if not topics:
            messagebox.showwarning("Тема", "Введите тему карусели.")
            return
        topic = topics[0]
        if len(topics) > 1:
            # одиночная генерация — только первая; batch для списка
            self._set_status(
                f"Gemini: берём 1-ю из {len(topics)} тем "
                f"(для всех — Batch Run)…"
            )
        if not self.llm.is_available():
            messagebox.showinfo(
                "Gemini API",
                "Задайте GEMINI_API_KEY в файле .env:\n"
                "  GEMINI_API_KEY=your_key_here",
            )
            return
        product = self._product_value()
        n_ex = len(self.llm.examples)
        self._reset_generation_session(keep_llm_queries=False)
        self.root.after(0, self._clear_feed)
        self._set_busy(True)
        self._set_status(
            f"Gemini + {n_ex} viral few-shot → «{topic}»…"
            + (f" · продукт: {product[:40]}" if product else "")
        )
        threading.Thread(
            target=self._llm_worker,
            args=(topic, product),
            daemon=True,
        ).start()

    def _llm_worker(self, topic: str, product: str = "") -> None:
        try:
            result = self.llm.generate_carousel(topic, product_name=product)
        except OllamaUnavailable:
            self.root.after(
                0,
                lambda: messagebox.showinfo(
                    "Gemini API",
                    "Задайте GEMINI_API_KEY в файле .env:\n"
                    "  GEMINI_API_KEY=your_key_here",
                ),
            )
            self._set_busy(False)
            self._set_status("GEMINI_API_KEY не задан.")
            return
        except Exception as exc:
            err = str(exc)
            self._set_busy(False)
            self._set_status(f"Gemini ошибка: {err}")
            self.root.after(
                0,
                lambda e=err: messagebox.showerror("Gemini", e),
            )
            return

        slides = result.get("slides") or []
        texts = [str(s.get("text") or "").strip() for s in slides if s.get("text")]
        queries = [
            str(s.get("search_query") or "").strip() for s in slides if s.get("text")
        ]
        # clamp to factory limits
        if len(texts) > MAX_SLIDES:
            texts = texts[:MAX_SLIDES]
            queries = queries[:MAX_SLIDES]
        if len(texts) < MIN_SLIDES:
            self._set_busy(False)
            self._set_status("Gemini вернула слишком мало слайдов.")
            self.root.after(
                0,
                lambda: messagebox.showwarning(
                    "Gemini",
                    f"Нужно минимум {MIN_SLIDES} слайда, получено {len(texts)}.",
                ),
            )
            return

        model = str(result.get("model") or "")
        few = int(result.get("few_shot_count") or 0)
        quality = dict(result.get("quality") or {})
        if not quality.get("archetype") and result.get("dna_archetype"):
            quality["archetype"] = result.get("dna_archetype")
        self.root.after(
            0,
            lambda: self._on_llm_done(texts, queries, model, few, quality),
        )

    def _on_llm_done(
        self,
        texts: list[str],
        queries: list[str],
        model: str,
        few_shot_count: int = 0,
        quality: dict[str, Any] | None = None,
    ) -> None:
        self.slides_text.delete("1.0", tk.END)
        self.slides_text.insert("1.0", "\n".join(texts))
        self._llm_queries = queries
        self._llm_query_fingerprint = tuple(texts)
        self._quality_meta = dict(quality or {})
        score = self._quality_meta.get("score")
        arch = self._quality_meta.get("archetype") or "—"
        q_txt = ""
        if score is not None:
            q_txt = f" · QC {score}/10 · {arch}"
        self._set_status(
            f"Gemini ({model}, {few_shot_count} few-shot){q_txt}: "
            f"{len(texts)} слайдов → ищем фото…"
        )
        # сразу harvest с LLM-запросами (busy уже True)
        self.root.after(0, self._clear_feed)
        threading.Thread(
            target=self._harvest_worker,
            args=(texts, queries),
            daemon=True,
        ).start()

    # -- harvest ------------------------------------------------------------

    def open_taste_trainer(self) -> None:
        """Отдельное окно разметки: downloaded_carousels + локальный SigLIP."""
        script = ROOT / "taste_trainer_app.py"
        if not script.is_file():
            messagebox.showerror("Вкус", f"Не найден {script.name}")
            return
        subprocess.Popen([sys.executable, str(script)], cwd=str(ROOT))
        self._set_status("Открыта галерея разметки вкуса.")

    def start_harvest(self) -> None:
        if self._busy:
            return
        lines = self._parse_slides()
        if not lines:
            return
        # Запросы Gemini — только если тексты слайдов не менялись (тот же fingerprint).
        # Иначе чужие search_query прошлой темы не подмешиваем.
        fp = tuple(lines)
        queries = None
        if (
            self._llm_queries
            and self._llm_query_fingerprint == fp
            and len(self._llm_queries) == len(lines)
        ):
            queries = list(self._llm_queries)
        else:
            self._llm_queries = None
            self._llm_query_fingerprint = None

        self._reset_generation_session(keep_llm_queries=bool(queries))
        if queries:
            self._llm_queries = queries
            self._llm_query_fingerprint = fp

        self._set_busy(True)
        self._set_status("Старт поиска…")
        self.root.after(0, self._clear_feed)
        threading.Thread(
            target=self._harvest_worker,
            args=(lines, queries),
            daemon=True,
        ).start()

    def _clear_feed(self) -> None:
        for fr in self._slide_frames:
            fr.destroy()
        self._slide_frames.clear()
        self._photo_refs.clear()
        self._slides.clear()
        self.candidates = {}
        self.selected_backgrounds = {}
        self.current_anchor = None
        self._quality_badge = None
        self.export_info.configure(text="")

    def _quality_badge_text(self) -> str:
        q = self._quality_meta or {}
        score = q.get("score")
        arch = q.get("archetype") or "—"
        if score is None:
            return ""
        rewritten = " · исправлен" if q.get("rewritten") else ""
        return (
            f"Контроль качества: {float(score):.1f}/10 · "
            f"Архетип: {arch} · Проверен критиком{rewritten}"
        )

    def _harvest_worker(
        self,
        lines: list[str],
        queries: list[str] | None = None,
    ) -> None:
        t0 = time.perf_counter()
        self.harvester.reset_used()
        slides: list[SlideState] = []
        total_ai = 0
        total_bytes = 0

        try:
            for i, text in enumerate(lines):
                if queries and i < len(queries) and queries[i].strip():
                    query = finalize_photo_query(
                        queries[i].strip(), i, slide_text=text
                    )
                else:
                    query = aesthetic_query_for_slide(text, i)
                self._set_status(
                    f"Слайд {i + 1}/{len(lines)} · запрос: {query}"
                )
                anchor_img = None
                if slides and slides[0].candidates:
                    seed = slides[0].selected_candidate()
                    if seed is not None:
                        anchor_img = seed.image
                # Цепочка альтернатив: пустой слайд недопустим
                cands, prog, used_q = self.harvester.harvest_until_filled(
                    query,
                    slide_text=text,
                    slide_index=i,
                    limit=CANDIDATES,
                    min_keep=max(1, MIN_KEEP),
                    anchor_image=anchor_img,
                )
                total_ai += prog.ai_rejected
                total_bytes += prog.bytes_total
                if used_q and used_q != query:
                    print(
                        f"[Слайд {i + 1}] итоговый запрос: '{query}' → '{used_q}'"
                    )
                    query = used_q

                # Пустой после гейтов — soft download + emergency rank
                if not cands:
                    print(
                        f"[WARNING] Слайд {i + 1}: пусто после гейтов — "
                        f"emergency download без hard-reject…"
                    )
                    raw, prog2, used2 = self.harvester.harvest_until_filled(
                        query,
                        slide_text=text,
                        slide_index=i,
                        limit=CANDIDATES,
                        min_keep=1,
                        anchor_image=None,
                        max_attempts=1,
                        apply_score=False,
                    )
                    total_ai += prog2.ai_rejected
                    total_bytes += prog2.bytes_total
                    if raw:
                        cands = self.harvester.rank_pool_emergency(
                            raw,
                            slide_text=text,
                            query=used2 or query,
                            limit=CANDIDATES,
                        )
                        if used2:
                            query = used2

                if not cands:
                    g_kept, g_q = self.harvester.guarantee_at_least_one(
                        slide_text=text,
                        slide_index=i,
                        preferred_query=query,
                        limit=max(1, MIN_KEEP),
                    )
                    if g_kept:
                        cands = g_kept
                        if g_q:
                            query = g_q

                slides.append(
                    SlideState(
                        index=i,
                        text=text,
                        query=query,
                        candidates=cands[:CANDIDATES],
                        selected=0,
                    )
                )

            # Дедуп pin_id между слайдами (иначе один кадр на двух слайдах)
            pools = [list(s.candidates) for s in slides]
            deduped = dedupe_carousel_pools(pools, selected_index=0)
            for slide, pool in zip(slides, deduped):
                if not pool:
                    continue
                before = slide.candidates[0].pin_id if slide.candidates else None
                slide.candidates = pool
                slide.selected = 0
                after = pool[0].pin_id
                if before and after and before != after:
                    print(
                        f"[dedupe] GUI слайд {slide.index + 1}: "
                        f"{before} → {after}"
                    )

            # Вкус уже отсортировал кадры; гармония — тай-брейк.
            self._set_status("Смысл + UGC + Color Matcher ranking…")
            _apply_color_harmony(slides)
        except Exception as exc:
            self._set_status(f"Ошибка: {exc}")
            self._set_busy(False)
            return

        elapsed = time.perf_counter() - t0
        mb = total_bytes / (1024 * 1024)
        speed = mb / elapsed if elapsed > 0 else 0.0

        # пререндер превью в фоне (уже в гармоничном порядке)
        self._set_status("Рендер превью…")
        for slide in slides:
            slide.preview_cache.clear()
            for ci, cand in enumerate(slide.candidates):
                try:
                    preview = render_preview(
                        cand.image, slide.text, MAIN_PREVIEW_W, MAIN_PREVIEW_H
                    )
                    slide.preview_cache[ci] = preview
                except Exception:
                    continue

        ok_slides = sum(1 for s in slides if s.candidates)
        self.root.after(
            0,
            lambda: self._on_harvest_done(
                slides, total_ai, elapsed, speed, ok_slides
            ),
        )

    def _on_harvest_done(
        self,
        slides: list[SlideState],
        ai_rejected: int,
        elapsed: float,
        speed: float,
        ok_slides: int,
    ) -> None:
        self._slides = slides
        self.candidates = {s.index: list(s.candidates) for s in slides}
        self.selected_backgrounds = {
            s.index: s.selected_candidate() for s in slides if s.candidates
        }
        self.current_anchor = (
            slides[0].selected_candidate() if slides and slides[0].candidates else None
        )
        self._render_feed()
        avg_h = []
        for s in slides[1:]:
            h = s.selected_harmony()
            if h is not None:
                avg_h.append(h)
        harm_txt = (
            f" · гармония ~{sum(avg_h)/len(avg_h):.0f}%" if avg_h else ""
        )
        self.status_var.set(
            f"Готово: {ok_slides}/{len(slides)} слайдов · "
            f"отсеяно ИИ: {ai_rejected} · "
            f"{elapsed:.1f} с · {speed:.2f} МБ/с{harm_txt}"
        )
        self._set_busy(False)
        if ok_slides == 0:
            messagebox.showerror(
                "Нет фото",
                "Не удалось скачать живые фото. Проверьте сеть / доступ к Pinterest.",
            )

    def _render_feed(self) -> None:
        for fr in self._slide_frames:
            fr.destroy()
        self._slide_frames.clear()
        self._photo_refs.clear()

        badge_txt = self._quality_badge_text()
        if badge_txt:
            badge = tk.Label(
                self.feed,
                text=badge_txt,
                bg="#1e3a2f",
                fg=ACCENT,
                font=("Segoe UI", 9, "bold"),
                anchor="w",
                padx=10,
                pady=6,
            )
            badge.pack(fill=tk.X, padx=6, pady=(4, 2))
            self._quality_badge = badge
            self._slide_frames.append(badge)

        for slide in self._slides:
            frame = self._make_slide_row(slide)
            frame.pack(fill=tk.X, padx=6, pady=8)
            self._slide_frames.append(frame)

        self.canvas.yview_moveto(0)

    def _make_slide_row(self, slide: SlideState) -> tk.Frame:
        row = tk.Frame(
            self.feed,
            bg=PANEL,
            highlightthickness=1,
            highlightbackground=BORDER,
        )

        head = tk.Frame(row, bg=PANEL)
        head.pack(fill=tk.X, padx=12, pady=(10, 4))
        tk.Label(
            head,
            text=f"Слайд {slide.index + 1}",
            bg=PANEL,
            fg=FG,
            font=("Segoe UI", 11, "bold"),
        ).pack(side=tk.LEFT)
        tk.Label(
            head,
            text=f"  ·  {slide.query}",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(side=tk.LEFT)

        body = tk.Frame(row, bg=PANEL)
        body.pack(fill=tk.X, padx=12, pady=(0, 12))

        # main preview
        main_wrap = tk.Frame(body, bg=PANEL2)
        main_wrap.pack(side=tk.LEFT, padx=(0, 16))

        main_lbl = tk.Label(
            main_wrap,
            bg="#111",
            width=MAIN_PREVIEW_W,
            height=MAIN_PREVIEW_H,
        )
        main_lbl.pack()
        slide._main_lbl = main_lbl  # type: ignore[attr-defined]

        taste_badge = tk.Label(
            main_wrap,
            text=_taste_label(slide.selected_candidate()),
            bg="#1e3a2f",
            fg=ACCENT,
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=4,
        )
        taste_badge.pack(fill=tk.X)
        slide._taste_badge = taste_badge  # type: ignore[attr-defined]

        # alternatives
        alts = tk.Frame(body, bg=PANEL)
        alts.pack(side=tk.LEFT, fill=tk.Y)

        tk.Label(
            alts,
            text="Альтернативы (клик = фон)",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor=tk.W, pady=(0, 6))

        thumbs_row = tk.Frame(alts, bg=PANEL)
        thumbs_row.pack(anchor=tk.W)
        slide._thumb_labels = []  # type: ignore[attr-defined]

        for ci, cand in enumerate(slide.candidates):
            thumb_frame = tk.Frame(
                thumbs_row,
                bg=PANEL2,
                highlightthickness=2,
                highlightbackground=ACCENT if ci == slide.selected else BORDER,
                cursor="hand2",
            )
            thumb_frame.pack(side=tk.LEFT, padx=(0, 8))

            # миниатюра фона без текста — быстрее визуально сравнивать
            thumb_img = self._make_thumb(cand.image)
            photo = ImageTk.PhotoImage(thumb_img)
            self._photo_refs.append(photo)
            slide.thumb_photos.append(photo)

            lbl = tk.Label(thumb_frame, image=photo, bg=PANEL2)
            lbl.pack()

            harm = (
                float(slide.harmony_scores[ci])
                if ci < len(slide.harmony_scores)
                else 0.0
            )
            thumb_badge = tk.Label(
                thumb_frame,
                text=_relevance_ugc_harmony_label(cand, harm),
                bg="#1a1b1e",
                fg=ACCENT if float(getattr(cand, "ugc_score", 0) or 0) >= 0.55 else "#e0a060",
                font=("Segoe UI", 7, "bold"),
                wraplength=THUMB_W + 48,
                justify=tk.CENTER,
                pady=2,
            )
            thumb_badge.pack(fill=tk.X)
            slide._thumb_labels.append((thumb_frame, ci))  # type: ignore[attr-defined]

            def on_click(
                _e: object | None = None,
                s: SlideState = slide,
                idx: int = ci,
            ) -> None:
                self._select_candidate(s, idx)

            thumb_frame.bind("<Button-1>", on_click)
            lbl.bind("<Button-1>", on_click)
            thumb_badge.bind("<Button-1>", on_click)

            related_btn = tk.Button(
                thumb_frame,
                text="🔍 Похожие",
                bg=PANEL2,
                fg=ACCENT,
                activebackground=BORDER,
                activeforeground=FG,
                relief=tk.FLAT,
                bd=0,
                font=("Segoe UI", 7, "bold"),
                cursor="hand2",
                padx=2,
                pady=1,
                command=lambda s=slide, idx=ci: self._start_related_for_thumb(s, idx),
            )
            related_btn.pack(fill=tk.X, pady=(0, 2))

        if not slide.candidates:
            tk.Label(
                alts,
                text="Нет кандидатов",
                bg=PANEL,
                fg="#c0392b",
                font=("Segoe UI", 10),
            ).pack(anchor=tk.W)

        # Локальные бейджи: смысл + UGC + гармония
        harm = slide.selected_harmony()
        sel = slide.selected_candidate()
        badge_text = _relevance_ugc_harmony_label(sel, harm)
        if slide.index == 0:
            mood = (slide.selected_profile() or {}).get("mood", "—")
            badge_text = f"{badge_text} · якорь · {mood}"
        ugc_ok = bool(
            sel and getattr(sel, "ugc_scored", False) and float(sel.ugc_score) >= 0.55
        )
        rel_ok = bool(
            sel
            and (
                not getattr(sel, "text_relevance_scored", False)
                or float(sel.text_relevance) >= 0.12
            )
        )
        good = (harm is not None and harm >= 55) and (ugc_ok or sel is None) and rel_ok
        badge = tk.Label(
            alts,
            text=badge_text,
            bg="#1e3a2f" if good else "#3a2a1e",
            fg=ACCENT if good else "#e0a060",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=3,
        )
        badge.pack(anchor=tk.W, pady=(8, 0))
        slide._harmony_badge = badge  # type: ignore[attr-defined]

        # Якорь стиля — только под слайдом 1
        if slide.index == 0 and slide.candidates:
            style_btn = tk.Button(
                alts,
                text="🎨 Применить этот вайб ко всем слайдам",
                bg="#2a3a48",
                fg=ACCENT,
                activebackground=ACCENT_DARK,
                activeforeground="#0b1a12",
                relief=tk.FLAT,
                bd=0,
                font=("Segoe UI", 9, "bold"),
                cursor="hand2",
                padx=10,
                pady=6,
                command=self._start_apply_style_anchor,
            )
            style_btn.pack(anchor=tk.W, pady=(8, 0))

        text_box = tk.Label(
            alts,
            text=slide.text,
            bg=PANEL,
            fg=FG,
            font=("Segoe UI", 10),
            wraplength=360,
            justify=tk.LEFT,
            anchor="nw",
        )
        text_box.pack(anchor=tk.W, pady=(10, 0))

        self._update_main_preview(slide)
        return row

    def _make_thumb(self, image: Image.Image) -> Image.Image:
        img = image.convert("RGB")
        scale = max(THUMB_W / img.width, THUMB_H / img.height)
        nw, nh = max(1, int(img.width * scale)), max(1, int(img.height * scale))
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        left = (nw - THUMB_W) // 2
        top = (nh - THUMB_H) // 2
        return img.crop((left, top, left + THUMB_W, top + THUMB_H))

    def _update_harmony_badge(self, slide: SlideState) -> None:
        badge = getattr(slide, "_harmony_badge", None)
        if badge is None:
            return
        harm = slide.selected_harmony()
        sel = slide.selected_candidate()
        text = _relevance_ugc_harmony_label(sel, harm)
        if slide.index == 0:
            mood = (slide.selected_profile() or {}).get("mood", "—")
            text = f"{text} · якорь · {mood}"
        ugc_ok = bool(
            sel and getattr(sel, "ugc_scored", False) and float(sel.ugc_score) >= 0.55
        )
        rel_ok = bool(
            sel
            and (
                not getattr(sel, "text_relevance_scored", False)
                or float(sel.text_relevance) >= 0.12
            )
        )
        good = (harm is not None and harm >= 55) and (ugc_ok or sel is None) and rel_ok
        badge.configure(
            text=text,
            bg="#1e3a2f" if good else "#3a2a1e",
            fg=ACCENT if good else "#e0a060",
        )

    def _replace_slide_candidates(
        self,
        slide: SlideState,
        new_cands: list[CandidateImage],
        *,
        selected: int = 0,
    ) -> None:
        """Подменить альтернативы слайда и сбросить кэши превью."""
        if not new_cands:
            return
        slide.candidates = list(new_cands)
        slide.selected = max(0, min(selected, len(slide.candidates) - 1))
        slide.color_profiles = []
        slide.harmony_scores = []
        slide.preview_cache.clear()
        slide.thumb_photos.clear()
        slide.main_photo = None
        _ensure_profiles(slide)

    def _start_related_for_thumb(self, slide: SlideState, cand_idx: int) -> None:
        if self._busy or self._related_busy:
            return
        if cand_idx < 0 or cand_idx >= len(slide.candidates):
            return
        cand = slide.candidates[cand_idx]
        pin_id = str(cand.pin_id or "").strip()
        if not re.fullmatch(r"\d{6,20}", pin_id):
            messagebox.showinfo(
                "Похожие",
                "У этого кадра нет настоящего pin_id — Related Pins недоступны.",
            )
            return
        # сначала выбрать эту миниатюру как текущий фон
        if cand_idx != slide.selected:
            self._select_candidate(slide, cand_idx)
        self._related_busy = True
        self._set_status(f"🔍 Ищу похожие для пина {pin_id}…")
        threading.Thread(
            target=self._related_worker,
            args=(slide.index, pin_id, slide.text, cand.query),
            daemon=True,
        ).start()

    def _related_worker(
        self,
        slide_index: int,
        pin_id: str,
        slide_text: str,
        seed_query: str,
    ) -> None:
        err = ""
        related: list[CandidateImage] = []
        try:
            exclude = {
                c.pin_id
                for s in self._slides
                for c in s.candidates
                if c.pin_id
            }
            related = self.harvester.get_related_pins(
                pin_id,
                limit=8,
                slide_text=slide_text,
                exclude_ids=exclude,
                query=seed_query or f"related:{pin_id}",
                judge=bool(slide_text.strip()),
            )
        except Exception as exc:
            err = str(exc)
        self.root.after(
            0,
            lambda: self._on_related_done(slide_index, pin_id, related, err),
        )

    def _on_related_done(
        self,
        slide_index: int,
        pin_id: str,
        related: list[CandidateImage],
        err: str,
    ) -> None:
        self._related_busy = False
        if err:
            self._set_status(f"Related Pins ошибка: {err}")
            messagebox.showerror("Похожие", err)
            return
        if slide_index < 0 or slide_index >= len(self._slides):
            return
        slide = self._slides[slide_index]
        if not related:
            self._set_status(f"Похожих не найдено для {pin_id}")
            messagebox.showinfo("Похожие", "Pinterest не вернул похожих пинов.")
            return

        # seed оставляем первым, близнецы — рядом
        seed = slide.selected_candidate()
        merged: list[CandidateImage] = []
        seen: set[str] = set()
        if seed is not None:
            merged.append(seed)
            seen.add(seed.pin_id)
        for c in related:
            if c.pin_id in seen:
                continue
            merged.append(c)
            seen.add(c.pin_id)
            if len(merged) >= 8:
                break

        scroll = self.canvas.yview()
        self._replace_slide_candidates(slide, merged, selected=0)
        if slide.index == 0 and len(self._slides) > 1:
            _rerank_followers(self._slides)
        elif slide.index > 0 and self._slides:
            anchor = self._slides[0].selected_profile()
            if anchor:
                slide.harmony_scores = [
                    get_harmony_score(anchor, p) for p in slide.color_profiles
                ]
                _apply_combined_ranking(slide)

        # кэш для якоря стиля
        if slide.index == 0:
            self._style_anchor_pin = pin_id
            self._style_related_cache = list(related)

        self._render_feed()
        try:
            self.canvas.yview_moveto(scroll[0])
        except Exception:
            pass
        self._set_status(
            f"🔍 Слайд {slide_index + 1}: {len(merged)} визуальных близнецов"
        )

    def _start_apply_style_anchor(self) -> None:
        if self._busy or self._related_busy:
            return
        if not self._slides:
            return
        anchor_slide = self._slides[0]
        seed = anchor_slide.selected_candidate()
        if seed is None:
            messagebox.showinfo("Стиль", "Сначала выберите фото на Слайде 1.")
            return
        pin_id = str(seed.pin_id or "").strip()
        if not re.fullmatch(r"\d{6,20}", pin_id):
            messagebox.showinfo(
                "Стиль",
                "У выбранного кадра нет pin_id — нельзя собрать ветку похожих.",
            )
            return
        self._related_busy = True
        need = max(8, (len(self._slides) - 1) * 3)
        self._set_status(
            f"🎨 Собираю вайб-серию из Related Pins ({pin_id})…"
        )
        threading.Thread(
            target=self._style_anchor_worker,
            args=(pin_id, need, seed.query),
            daemon=True,
        ).start()

    def _style_anchor_worker(
        self, pin_id: str, need: int, seed_query: str
    ) -> None:
        err = ""
        related: list[CandidateImage] = []
        try:
            # кэш Related только внутри текущей сессии / того же pin_id
            if (
                self._style_anchor_pin == pin_id
                and len(self._style_related_cache) >= max(6, need // 2)
            ):
                related = list(self._style_related_cache)
            else:
                exclude = {pin_id}
                related = self.harvester.get_related_pins(
                    pin_id,
                    limit=need,
                    exclude_ids=exclude,
                    query=seed_query or f"style:{pin_id}",
                    judge=False,
                )
                self._style_anchor_pin = pin_id
                self._style_related_cache = list(related)
                ids = ", ".join(c.pin_id for c in related[:8]) or "—"
                print(
                    f"[Стиль] Related Pins для {pin_id} -> "
                    f"{len(related)} НОВЫХ картинок (IDs: {ids})"
                )
        except Exception as exc:
            err = str(exc)
        self.root.after(0, lambda: self._on_style_anchor_done(related, err))

    def _on_style_anchor_done(
        self, related: list[CandidateImage], err: str
    ) -> None:
        self._related_busy = False
        if err:
            self._set_status(f"Стиль-якорь ошибка: {err}")
            messagebox.showerror("Стиль", err)
            return
        if not related:
            messagebox.showinfo(
                "Стиль",
                "Не удалось набрать похожие пины для якоря Слайда 1.",
            )
            self._set_status("Стиль: Related Pins пусто")
            return
        if len(self._slides) < 2:
            self._set_status("Стиль: только один слайд — нечего распределять")
            return

        anchor_slide = self._slides[0]
        anchor_cand = anchor_slide.selected_candidate()
        if anchor_cand is None:
            return
        _ensure_profiles(anchor_slide)
        anchor_prof = anchor_slide.selected_profile()
        if not anchor_prof:
            anchor_prof = get_color_profile(anchor_cand.image)

        pool = [c for c in related if c.pin_id != anchor_cand.pin_id]
        used: set[str] = {anchor_cand.pin_id}

        for slide in self._slides[1:]:
            if not pool:
                break
            scored: list[tuple[float, CandidateImage]] = []
            for c in pool:
                if c.pin_id in used:
                    continue
                try:
                    prof = get_color_profile(c.image)
                    harm = float(get_harmony_score(anchor_prof, prof))
                except Exception:
                    harm = 0.0
                ugc = float(getattr(c, "ugc_score", 0.5) or 0.5)
                rel = float(getattr(c, "text_relevance", 0.5) or 0.5)
                taste = (
                    float(c.taste_score)
                    if getattr(c, "taste_scored", False)
                    else 0.5
                )
                scored.append(
                    (
                        combined_rank_score(
                            ugc, taste=taste, harmony=harm, relevance=rel
                        ),
                        c,
                    )
                )
            if not scored:
                break
            scored.sort(key=lambda x: x[0], reverse=True)
            best = scored[0][1]
            used.add(best.pin_id)

            # альтернативы: лучший combined (rel×0.50 + ugc×0.30 + harm×0.20)
            alts = [best]
            for _, c in scored[1:]:
                if c.pin_id in used and c.pin_id != best.pin_id:
                    continue
                if c.pin_id == best.pin_id:
                    continue
                alts.append(c)
                if len(alts) >= CANDIDATES:
                    break
            # добить неиспользованными
            for c in pool:
                if len(alts) >= CANDIDATES:
                    break
                if c.pin_id in {a.pin_id for a in alts}:
                    continue
                alts.append(c)

            self._replace_slide_candidates(slide, alts, selected=0)
            pool = [c for c in pool if c.pin_id != best.pin_id]

        _rerank_followers(self._slides)
        scroll = self.canvas.yview()
        self._render_feed()
        try:
            self.canvas.yview_moveto(scroll[0])
        except Exception:
            pass
        mood = (anchor_slide.selected_profile() or {}).get("mood", "—")
        self._set_status(
            f"🎨 Вайб якоря применён ко всей карусели ({mood}, {len(related)} related)"
        )

    def _select_candidate(self, slide: SlideState, idx: int) -> None:
        if idx < 0 or idx >= len(slide.candidates):
            return
        if idx == slide.selected:
            return
        slide.selected = idx
        for frame, ci in getattr(slide, "_thumb_labels", []):
            frame.configure(
                highlightbackground=ACCENT if ci == idx else BORDER
            )
        self._update_main_preview(slide)
        self._update_harmony_badge(slide)

        # смена якоря (слайд 1) → переранжировать остальные в фоне UI
        if slide.index == 0 and len(self._slides) > 1:
            self._set_status("Color Matcher: переранжирование под новый якорь…")
            self.root.after(10, self._rerank_after_anchor_change)

    def _rerank_after_anchor_change(self) -> None:
        scroll = self.canvas.yview()
        _rerank_followers(self._slides)
        # лёгкий пререндер главных превью для новых #1
        for slide in self._slides[1:]:
            if not slide.candidates:
                continue
            if 0 not in slide.preview_cache:
                cand = slide.candidates[0]
                try:
                    slide.preview_cache[0] = render_preview(
                        cand.image, slide.text, MAIN_PREVIEW_W, MAIN_PREVIEW_H
                    )
                except Exception:
                    pass
        self._render_feed()
        try:
            self.canvas.yview_moveto(scroll[0])
        except Exception:
            pass
        mood = (self._slides[0].selected_profile() or {}).get("mood", "—")
        self._set_status(f"Палитра пересобрана под якорь ({mood})")

    def _update_main_preview(self, slide: SlideState) -> None:
        lbl = getattr(slide, "_main_lbl", None)
        if lbl is None:
            return
        if slide.selected not in slide.preview_cache:
            cand = slide.selected_candidate()
            if cand is None:
                lbl.configure(image="", text="нет фото", fg=MUTED)
                taste_badge = getattr(slide, "_taste_badge", None)
                if taste_badge is not None:
                    taste_badge.configure(text="✨ Вкус: —", bg="#2a2c31", fg=MUTED)
                return
            slide.preview_cache[slide.selected] = render_preview(
                cand.image, slide.text, MAIN_PREVIEW_W, MAIN_PREVIEW_H
            )
        preview = slide.preview_cache[slide.selected]
        photo = ImageTk.PhotoImage(preview)
        self._photo_refs.append(photo)
        slide.main_photo = photo
        lbl.configure(image=photo, text="")
        taste_badge = getattr(slide, "_taste_badge", None)
        if taste_badge is not None:
            cand = slide.selected_candidate()
            scored = bool(cand and getattr(cand, "taste_scored", False))
            hot = scored and float(cand.taste_score) >= 0.90
            taste_badge.configure(
                text=_taste_label(cand),
                bg="#1e3a2f" if hot or scored else "#2a2c31",
                fg=ACCENT if hot or scored else MUTED,
            )

    # -- export -------------------------------------------------------------

    def start_export(self) -> None:
        if self._busy or not self._slides:
            return
        missing = [s.index + 1 for s in self._slides if not s.candidates]
        if missing:
            messagebox.showwarning(
                "Неполные слайды",
                f"Нет фото для слайдов: {', '.join(map(str, missing))}",
            )
            return
        self._set_busy(True)
        self._set_status("Экспорт…")
        threading.Thread(target=self._export_worker, daemon=True).start()

    def _export_worker(self) -> None:
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = OUT_DIR / f"carousel_{stamp}"
            out.mkdir(parents=True, exist_ok=True)

            meta: dict[str, Any] = {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "slide_count": len(self._slides),
                "format": {"width": 1080, "height": 1440, "ratio": "3:4"},
                "slides": [],
            }

            for slide in self._slides:
                cand = slide.selected_candidate()
                assert cand is not None
                rendered, render_meta = render_slide(cand.image, slide.text)
                path = out / f"{slide.index + 1}.jpg"
                rendered.save(path, quality=92, optimize=True)
                harm = slide.selected_harmony()
                prof = slide.selected_profile() or {}
                meta["slides"].append(
                    {
                        "index": slide.index + 1,
                        "text": slide.text,
                        "query": slide.query,
                        "pin_id": cand.pin_id,
                        "source_url": cand.source_url,
                        "file": path.name,
                        "font_size": render_meta.font_size,
                        "stroke_width": render_meta.stroke_width,
                        "text_area_ratio": round(render_meta.text_area_ratio, 4),
                        "within_24pct": render_meta.within_scientific_limit,
                        "style": "tiktok_outline",
                        "via_fallback": cand.via_fallback,
                        "text_relevance": (
                            round(float(cand.text_relevance), 4)
                            if getattr(cand, "text_relevance_scored", False)
                            else None
                        ),
                        "taste_score": (
                            round(float(cand.taste_score), 4)
                            if getattr(cand, "taste_scored", False)
                            else None
                        ),
                        "ugc_score": (
                            round(float(cand.ugc_score), 4)
                            if getattr(cand, "ugc_scored", False)
                            else None
                        ),
                        "combined_score": round(
                            float(getattr(cand, "combined_score", 0) or 0), 4
                        ),
                        "is_anchor": slide.index == 0,
                        "harmony_score": harm,
                        "color_mood": prof.get("mood"),
                        "color_profile": {
                            "luminance": round(float(prof["luminance"]), 2)
                            if prof
                            else None,
                            "warmth": round(float(prof["warmth"]), 4)
                            if prof
                            else None,
                            "saturation": round(float(prof["saturation"]), 4)
                            if prof
                            else None,
                        },
                    }
                )

            meta_path = out / "meta.json"
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            texts = [s.text for s in self._slides]
            caption = generate_caption(
                texts,
                (self._topics_from_ui() or [""])[0],
                self._product_value(),
            )
            (out / "caption.txt").write_text(caption + "\n", encoding="utf-8")
            self._last_export = out

            # PhotoVault: финальные фото -> библиотека
            try:
                vault_items: list[dict[str, Any]] = []
                for slide in self._slides:
                    cand = slide.selected_candidate()
                    if cand is None or not cand.pin_id:
                        continue
                    vault_items.append(
                        {
                            "pin_id": str(cand.pin_id),
                            "image": cand.image,
                            "query": slide.query,
                            "image_url": getattr(cand, "source_url", "") or "",
                            "tags": (self._topics_from_ui() or [""])[0],
                        }
                    )
                if vault_items:
                    n = get_photo_vault().register_selected(vault_items)
                    if n:
                        self.root.after(
                            0,
                            lambda: self._set_status(
                                f"Экспорт OK · +{n} фото в библиотеку"
                            ),
                        )
            except Exception as exc:
                print(f"[vault] export register skip: {exc}")

            # освобождаем тяжёлый кэш превью / кандидатов после экспорта
            self.root.after(0, self._release_ram_keep_ui)

            self.root.after(
                0,
                lambda: self._on_export_done(out),
            )
        except Exception as exc:
            self._set_status(f"Ошибка экспорта: {exc}")
            self._set_busy(False)

    def _release_ram_keep_ui(self) -> None:
        """Оставляет UI-превью, чистит полноразмерные PIL-изображения кандидатов."""
        for slide in self._slides:
            for cand in slide.candidates:
                # заменяем полноразмер на уже уменьшенный preview, если есть
                try:
                    if cand.image is not None and (
                        cand.image.width > MAIN_PREVIEW_W * 2
                        or cand.image.height > MAIN_PREVIEW_H * 2
                    ):
                        cand.image = cand.image.resize(
                            (MAIN_PREVIEW_W * 2, MAIN_PREVIEW_H * 2),
                            Image.Resampling.LANCZOS,
                        )
                except Exception:
                    pass

    def _on_export_done(self, out: Path) -> None:
        self.export_info.configure(text=str(out))
        self.status_var.set(f"Экспортировано → {out}")
        self._set_busy(False)
        messagebox.showinfo("Готово", f"Карусель сохранена:\n{out}")

    def open_export_folder(self) -> None:
        target = self._last_export if self._last_export and self._last_export.is_dir() else OUT_DIR
        target.mkdir(parents=True, exist_ok=True)
        path = str(target.resolve())
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror("Ошибка", f"Не удалось открыть папку:\n{exc}")

    def _on_close(self) -> None:
        self._batch_stop = True
        try:
            get_meter().write_summary()
        except Exception:
            pass
        try:
            self.harvester.close()
        except Exception:
            pass
        self.root.destroy()

    # -- batch factory ------------------------------------------------------

    def stop_batch(self) -> None:
        self._batch_stop = True
        self._set_status("Стоп: дождитесь окончания текущей карусели…")

    def start_batch(self) -> None:
        if self._busy:
            return
        topics = self._topics_from_ui()
        if not topics:
            messagebox.showwarning("Тема", "Введите тему для batch.")
            return
        if not self.llm.is_available():
            messagebox.showinfo(
                "Gemini API",
                "Задайте GEMINI_API_KEY в файле .env:\n"
                "  GEMINI_API_KEY=your_key_here",
            )
            return
        try:
            n = int(self.batch_count.get())
        except (TypeError, ValueError):
            n = 10
        n = max(1, min(50, n))
        product = self._product_value()
        multi = len(topics) > 1
        total = len(topics) if multi else n
        self._batch_stop = False
        self._set_busy(True)
        self._set_progress(0, total)
        if multi:
            get_meter().reset_session(label=f"multi-topic x{total}")
            self._set_status(
                f"Batch multi-topic: {total} тем · по 1 карусели…"
            )
        else:
            get_meter().reset_session(label=f"batch x{n}")
            self._set_status(f"Batch start: {n} вариаций «{topics[0][:40]}»…")
        threading.Thread(
            target=self._batch_worker,
            args=(topics, product, n, multi),
            daemon=True,
        ).start()

    def _batch_worker(
        self,
        topics: list[str],
        product: str,
        n: int,
        multi: bool,
    ) -> None:
        total = len(topics) if multi else n

        def on_done(i: int, tot: int, folder: Path) -> None:
            self._set_progress(i, tot)
            self._last_run_dir = folder.parent
            if multi and i <= len(topics):
                title = topics[i - 1][:50]
                self._set_status(
                    f"Сборка темы {i} / {tot}: «{title}» | "
                    f"Собрано каруселей: {i}"
                )
            else:
                self._set_status(
                    f"Собрано: {i} / {tot} · последняя {folder.name}"
                )

        try:
            if multi:
                result = run_batch(
                    topics=topics,
                    product=product,
                    count=1,
                    out_root=OUT_DIR,
                    llm=self.llm,
                    harvester=self.harvester,
                    on_status=self._set_status,
                    on_carousel_done=on_done,
                    should_stop=lambda: self._batch_stop,
                )
            else:
                result = run_batch(
                    topic=topics[0],
                    product=product,
                    count=n,
                    out_root=OUT_DIR,
                    llm=self.llm,
                    harvester=self.harvester,
                    on_status=self._set_status,
                    on_carousel_done=on_done,
                    should_stop=lambda: self._batch_stop,
                )
        except Exception as exc:
            self._set_busy(False)
            self._set_status(f"Batch fail: {exc}")
            self.root.after(0, lambda: messagebox.showerror("Batch", str(exc)))
            return

        self._last_run_dir = result.run_dir
        self._last_export = result.run_dir
        self._set_busy(False)
        self._set_progress(result.made, total)
        mode = "мульти-темы" if multi else "вариации"
        msg = (
            f"Batch готов ({mode}): {result.made}/{total} ок, "
            f"fail={result.failed}\n{result.run_dir}"
        )
        if result.failed:
            msg += (
                "\n\nНеполные карусели не сохраняются (partial wipe). "
                "Перезапусти fail-темы — completion-fill подтянет фото."
            )
        self._set_status(msg.replace("\n", " · "))

        def finish() -> None:
            self.export_info.configure(text=str(result.run_dir))
            try:
                self.photo_library.refresh()
            except Exception:
                pass
            title = "Batch готов" if not result.failed else "Batch с пропусками"
            if messagebox.askyesno(
                title,
                msg + "\n\nОткрыть вкладку «Быстрый отсмотр»?",
            ):
                self.review.load_run(result.run_dir)
                self.notebook.select(1)

        self.root.after(0, finish)

def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    load_dotenv(ROOT / ".env")
    root = tk.Tk()
    CarouselFactoryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
