#!/usr/bin/env python3
"""
Carousel Generator — накладывает before/after на зелёный экран iPad (chroma key).

Автоматически находит зелёную область, вычисляет перспективу и подставляет фото.

Запуск: python carousel-gen.py
"""

from __future__ import annotations

import json
import re
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_BG = SCRIPT_DIR / "bg_ipad.jpg"
DEFAULT_INPUT = SCRIPT_DIR / "beforeafter"
DEFAULT_SETTINGS = SCRIPT_DIR / "settings.json"
SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


# ---------------------------------------------------------------------------
# Chroma key detection & compositing
# ---------------------------------------------------------------------------

@dataclass
class ChromaScreen:
    """Обнаруженная зелёная область экрана iPad."""

    mask: np.ndarray          # uint8, 255 = зелёный экран
    corners: np.ndarray       # float32 [4, 2]: TL, TR, BR, BL
    width: int                # ширина «плоского» экрана
    height: int               # высота «плоского» экрана


def order_points(pts: np.ndarray) -> np.ndarray:
    """Упорядочивает 4 точки: TL, TR, BR, BL."""
    pts = np.array(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).flatten()
    return np.float32([
        pts[np.argmin(s)],
        pts[np.argmin(diff)],
        pts[np.argmax(s)],
        pts[np.argmax(diff)],
    ])


def screen_dimensions(corners: np.ndarray) -> tuple[int, int]:
    tl, tr, br, bl = corners
    width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    return max(width, 50), max(height, 50)


def detect_chroma_screen(
    bg: np.ndarray,
    h_min: int = 35,
    h_max: int = 85,
    s_min: int = 80,
    v_min: int = 80,
    morph_size: int = 5,
) -> ChromaScreen | None:
    """
    Находит зелёный chroma key на фоне:
    1. HSV-маска зелёного
    2. Морфология для очистки
    3. Контур экрана → 4 угла
    """
    hsv = cv2.cvtColor(bg, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([h_min, s_min, v_min]), np.array([h_max, 255, 255]))

    k = max(3, morph_size | 1)  # нечётный
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < 5000:
        return None

    # 4 угла через approxPolyDP; fallback — minAreaRect
    peri = cv2.arcLength(contour, True)
    corners = None
    for eps in (0.02, 0.03, 0.015, 0.04, 0.05):
        approx = cv2.approxPolyDP(contour, eps * peri, True)
        if len(approx) == 4:
            corners = order_points(approx.reshape(4, 2))
            break

    if corners is None:
        rect = cv2.minAreaRect(contour)
        corners = order_points(cv2.boxPoints(rect))

    # Уточнённая маска: только крупнейший контур (сохраняет скругления)
    clean_mask = np.zeros_like(mask)
    cv2.drawContours(clean_mask, [contour], -1, 255, -1)

    w, h = screen_dimensions(corners)
    return ChromaScreen(mask=clean_mask, corners=corners, width=w, height=h)


def composite_chroma(
    bg: np.ndarray,
    screen_content: np.ndarray,
    screen: ChromaScreen,
    feather: int = 3,
) -> np.ndarray:
    """
    Накладывает содержимое на chroma key:
    - perspective warp по 4 углам
    - маска зелёного экрана (включая скруглённые углы)
    - мягкие края через Gaussian blur
    """
    h_s, w_s = screen_content.shape[:2]
    pts_src = np.float32([[0, 0], [w_s, 0], [w_s, h_s], [0, h_s]])
    M = cv2.getPerspectiveTransform(pts_src, screen.corners)

    warped = cv2.warpPerspective(
        screen_content, M, (bg.shape[1], bg.shape[0]), flags=cv2.INTER_LANCZOS4
    )

    if feather > 0:
        k = feather | 1
        alpha = cv2.GaussianBlur(screen.mask.astype(np.float32), (k, k), 0) / 255.0
    else:
        alpha = (screen.mask > 127).astype(np.float32)

    alpha_3 = alpha[..., np.newaxis]
    result = bg.astype(np.float32) * (1 - alpha_3) + warped.astype(np.float32) * alpha_3
    return np.clip(result, 0, 255).astype(np.uint8)


def draw_detection_overlay(bg: np.ndarray, screen: ChromaScreen) -> np.ndarray:
    """Рисует контур и углы для предпросмотра детекции."""
    vis = bg.copy()
    cv2.drawContours(vis, [screen.mask], -1, (0, 255, 255), 2)

    labels = ["TL", "TR", "BR", "BL"]
    colors = [(0, 255, 0), (0, 165, 255), (0, 0, 255), (255, 0, 255)]
    for i, (pt, lbl, col) in enumerate(zip(screen.corners, labels, colors)):
        x, y = int(pt[0]), int(pt[1])
        cv2.circle(vis, (x, y), 8, col, -1)
        cv2.circle(vis, (x, y), 8, (255, 255, 255), 2)
        cv2.putText(vis, lbl, (x + 10, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)

    return vis


# ---------------------------------------------------------------------------
# Before/after pairs
# ---------------------------------------------------------------------------

def find_before_after_pairs(folder: Path) -> list[tuple[Path, Path, str]]:
    if not folder.is_dir():
        return []

    pairs: list[tuple[Path, Path, str]] = []

    before_sub = folder / "before"
    after_sub = folder / "after"
    if before_sub.is_dir() and after_sub.is_dir():
        for bf in sorted(before_sub.iterdir()):
            if bf.suffix.lower() not in SUPPORTED_EXT:
                continue
            af = after_sub / bf.name
            if af.is_file():
                pairs.append((bf, af, bf.stem))
        if pairs:
            return pairs

    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_EXT]
    before_map: dict[str, Path] = {}
    after_map: dict[str, Path] = {}

    for f in files:
        stem = f.stem.lower()
        if re.search(r"before", stem):
            key = re.sub(r"[_\-.]?before.*$", "", stem).strip("_-.")
            before_map[key or f.stem] = f
        elif re.search(r"after", stem):
            key = re.sub(r"[_\-.]?after.*$", "", stem).strip("_-.")
            after_map[key or f.stem] = f

    for key in sorted(set(before_map) & set(after_map)):
        name = key or before_map[key].stem
        pairs.append((before_map[key], after_map[key], name))

    return pairs


def load_image(path: Path) -> np.ndarray | None:
    return cv2.imread(str(path), cv2.IMREAD_COLOR)


def fit_cover(img: np.ndarray, width: int, height: int) -> np.ndarray:
    h, w = img.shape[:2]
    scale = max(width / w, height / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    x0 = (new_w - width) // 2
    y0 = (new_h - height) // 2
    return resized[y0 : y0 + height, x0 : x0 + width]


def create_before_after(
    before: np.ndarray,
    after: np.ndarray,
    width: int,
    height: int,
    split_ratio: float = 0.5,
    divider_width: int = 4,
) -> np.ndarray:
    b = fit_cover(before, width, height)
    a = fit_cover(after, width, height)

    split_x = int(width * np.clip(split_ratio, 0.05, 0.95))
    composite = b.copy()
    composite[:, split_x:] = a[:, split_x:]

    if divider_width > 0:
        cv2.line(composite, (split_x, 0), (split_x, height), (255, 255, 255), divider_width)
        cv2.line(
            composite,
            (split_x - 1, 0),
            (split_x - 1, height),
            (0, 0, 0),
            max(1, divider_width // 3),
        )

    return composite


def _sort_name_key(name: str) -> tuple:
    return (0, int(name)) if name.isdigit() else (1, name)


def find_color_images(folder: Path) -> list[tuple[Path, str]]:
    """Находит раскрашенные изображения (after / N-1 / *_color_raster_back)."""
    if not folder.is_dir():
        return []

    found: dict[str, Path] = {}

    for f in folder.iterdir():
        if not f.is_file() or f.suffix.lower() not in SUPPORTED_EXT:
            continue

        m = re.match(r"^(.+)-1$", f.stem, re.I)
        if m:
            found[m.group(1)] = f
            continue

        if f.stem.endswith("_color_raster_back"):
            found[f.stem.replace("_color_raster_back", "")] = f
            continue

        stem = f.stem.lower()
        if re.search(r"after", stem) and not re.search(r"before", stem):
            key = re.sub(r"[_\-.]?after.*$", "", stem).strip("_-.") or f.stem
            found[key] = f

    after_sub = folder / "after"
    if after_sub.is_dir():
        for f in sorted(after_sub.iterdir()):
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXT:
                found.setdefault(f.stem, f)

    for _, af, name in find_before_after_pairs(folder):
        found.setdefault(name, af)

    return [(found[k], k) for k in sorted(found, key=_sort_name_key)]


def prepare_screen_content(
    after: np.ndarray,
    width: int,
    height: int,
    before: np.ndarray | None = None,
    mode: str = "color",
    split_ratio: float = 0.5,
    divider_width: int = 4,
) -> np.ndarray:
    if mode == "split" and before is not None:
        return create_before_after(before, after, width, height, split_ratio, divider_width)
    return fit_cover(after, width, height)


def process_image(
    bg: np.ndarray,
    screen: ChromaScreen,
    color_path: Path,
    feather: int,
    before_path: Path | None = None,
    mode: str = "color",
    split_ratio: float = 0.5,
    divider_width: int = 4,
) -> np.ndarray | None:
    after = load_image(color_path)
    if after is None:
        return None

    before = load_image(before_path) if before_path and mode == "split" else None
    content = prepare_screen_content(
        after, screen.width, screen.height, before, mode, split_ratio, divider_width
    )
    return composite_chroma(bg, content, screen, feather)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class CarouselGeneratorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Carousel Generator — Chroma Key iPad")
        self.geometry("1200x780")
        self.minsize(900, 600)

        self.bg_path = tk.StringVar(value=str(DEFAULT_BG))
        self.input_path = tk.StringVar(value=str(DEFAULT_INPUT))
        self.output_path = tk.StringVar(value=str(SCRIPT_DIR / "output"))

        self.display_mode = tk.StringVar(value="color")
        self.split_ratio = tk.DoubleVar(value=0.5)
        self.divider_width = tk.IntVar(value=4)
        self.feather = tk.IntVar(value=3)

        # Chroma key HSV
        self.h_min = tk.IntVar(value=35)
        self.h_max = tk.IntVar(value=85)
        self.s_min = tk.IntVar(value=80)
        self.v_min = tk.IntVar(value=80)
        self.morph_size = tk.IntVar(value=5)

        self.show_detection = tk.BooleanVar(value=False)

        self.bg_image: np.ndarray | None = None
        self.chroma_screen: ChromaScreen | None = None
        self.preview_image: np.ndarray | None = None

        self._canvas_scale = 1.0
        self._canvas_offset = (0, 0)
        self._photo: ImageTk.PhotoImage | None = None

        self._build_ui()
        self._load_settings()
        self._reload_background()

    def _build_ui(self) -> None:
        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(main, width=340)
        right = ttk.Frame(main)
        main.add(left, weight=0)
        main.add(right, weight=1)

        self._build_settings(left)
        self._build_canvas(right)

    def _build_settings(self, parent: ttk.Frame) -> None:
        pad = {"padx": 6, "pady": 4}

        ttk.Label(parent, text="Настройки", font=("", 11, "bold")).pack(anchor=tk.W, **pad)

        self._file_row(parent, "Фон (chroma key):", self.bg_path, self._pick_bg)
        self._file_row(parent, "Папка before/after:", self.input_path, self._pick_input)
        self._file_row(parent, "Папка результата:", self.output_path, self._pick_output)

        ttk.Separator(parent).pack(fill=tk.X, pady=8)

        ttk.Label(parent, text="Chroma key (HSV)", font=("", 10, "bold")).pack(anchor=tk.W, **pad)
        ttk.Label(
            parent,
            text="Экран iPad должен быть зелёным.\nДетекция автоматическая при загрузке фона.",
            foreground="#666",
        ).pack(anchor=tk.W, **pad)

        self._slider_row(parent, "Hue min:", self.h_min, 0, 179, "", int_val=True)
        self._slider_row(parent, "Hue max:", self.h_max, 0, 179, "", int_val=True)
        self._slider_row(parent, "Sat min:", self.s_min, 0, 255, "", int_val=True)
        self._slider_row(parent, "Val min:", self.v_min, 0, 255, "", int_val=True)
        self._slider_row(parent, "Морфология:", self.morph_size, 3, 15, "px", int_val=True)
        self._slider_row(parent, "Смягчение краёв:", self.feather, 0, 11, "px", int_val=True)

        chroma_btns = ttk.Frame(parent)
        chroma_btns.pack(fill=tk.X, **pad)
        ttk.Button(chroma_btns, text="Пересчитать маску", command=self._redetect).pack(side=tk.LEFT)
        ttk.Checkbutton(
            chroma_btns, text="Показать детекцию", variable=self.show_detection,
            command=self._redraw_canvas,
        ).pack(side=tk.LEFT, padx=8)

        self.detect_status = ttk.Label(parent, text="Детекция: —", foreground="#888")
        self.detect_status.pack(anchor=tk.W, **pad)

        ttk.Separator(parent).pack(fill=tk.X, pady=8)

        ttk.Label(parent, text="Содержимое экрана", font=("", 10, "bold")).pack(
            anchor=tk.W, **pad
        )
        mode_frame = ttk.Frame(parent)
        mode_frame.pack(fill=tk.X, **pad)
        ttk.Radiobutton(
            mode_frame, text="Только раскраска", variable=self.display_mode,
            value="color", command=self._on_mode_change,
        ).pack(anchor=tk.W)
        ttk.Radiobutton(
            mode_frame, text="Before + After (split)", variable=self.display_mode,
            value="split", command=self._on_mode_change,
        ).pack(anchor=tk.W)

        self.split_frame = ttk.Frame(parent)
        self._slider_row(self.split_frame, "Разделитель:", self.split_ratio, 0.1, 0.9, "%")
        self._slider_row(self.split_frame, "Толщина линии:", self.divider_width, 0, 12, "px", int_val=True)

        ttk.Separator(parent).pack(fill=tk.X, pady=8)

        ttk.Button(parent, text="Предпросмотр", command=self._preview).pack(fill=tk.X, **pad)
        ttk.Button(parent, text="Сгенерировать все", command=self._generate_all).pack(
            fill=tk.X, **pad
        )

        self.progress = ttk.Progressbar(parent, mode="determinate")
        self.progress.pack(fill=tk.X, **pad)

        self.status = ttk.Label(parent, text="Готово", foreground="#444", wraplength=300)
        self.status.pack(anchor=tk.W, **pad)

        pairs_frame = ttk.LabelFrame(parent, text="Найденные изображения")
        pairs_frame.pack(fill=tk.BOTH, expand=True, **pad)
        self.pairs_list = tk.Listbox(pairs_frame, height=6, font=("Consolas", 9))
        self.pairs_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        ttk.Button(pairs_frame, text="Обновить список", command=self._refresh_pairs).pack(pady=4)

        self._on_mode_change()

    def _file_row(self, parent, label, var, cmd) -> None:
        ttk.Label(parent, text=label).pack(anchor=tk.W, padx=6)
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=6, pady=2)
        ttk.Entry(row, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="...", width=3, command=cmd).pack(side=tk.LEFT, padx=2)

    def _slider_row(self, parent, label, var, from_, to, suffix, int_val=False) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=6, pady=2)
        ttk.Label(frame, text=label, width=16).pack(side=tk.LEFT)
        scale = ttk.Scale(
            frame, from_=from_, to=to, variable=var, orient=tk.HORIZONTAL,
            command=lambda _: self._on_chroma_param_change(),
        )
        scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        val_label = ttk.Label(frame, width=5)

        def update_label(*_) -> None:
            v = var.get()
            if int_val:
                val_label.config(text=f"{int(v)}{suffix}")
            elif suffix == "%":
                val_label.config(text=f"{int(v * 100)}%")
            else:
                val_label.config(text=f"{v:.2f}")

        var.trace_add("write", update_label)
        update_label()
        val_label.pack(side=tk.LEFT)

    def _build_canvas(self, parent) -> None:
        ttk.Label(parent, text="Предпросмотр", font=("", 11, "bold")).pack(anchor=tk.W)
        canvas_frame = ttk.Frame(parent)
        canvas_frame.pack(fill=tk.BOTH, expand=True, pady=4)

        self.canvas = tk.Canvas(canvas_frame, bg="#2b2b2b", highlightthickness=0)
        v_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda _: self._redraw_canvas())

    # --- Chroma detection ---

    def _detect_chroma(self) -> bool:
        if self.bg_image is None:
            return False

        self.chroma_screen = detect_chroma_screen(
            self.bg_image,
            h_min=self.h_min.get(),
            h_max=self.h_max.get(),
            s_min=self.s_min.get(),
            v_min=self.v_min.get(),
            morph_size=self.morph_size.get(),
        )

        if self.chroma_screen is None:
            self.detect_status.config(
                text="Детекция: не найдена ✗",
                foreground="#cc3333",
            )
            return False

        s = self.chroma_screen
        px = int(np.count_nonzero(s.mask))
        self.detect_status.config(
            text=f"Детекция: ✓  {s.width}×{s.height} px, {px:,} px маски",
            foreground="#228822",
        )
        return True

    def _redetect(self) -> None:
        if self._detect_chroma():
            self.preview_image = None
            self._redraw_canvas()
            self._set_status("Chroma key пересчитан")

    def _on_chroma_param_change(self) -> None:
        if self.bg_image is not None:
            self._detect_chroma()
            if self.preview_image is not None:
                self._preview()

    # --- Canvas ---

    def _redraw_canvas(self) -> None:
        self.canvas.delete("all")

        if self.preview_image is not None:
            display = self.preview_image
        elif self.show_detection.get() and self.chroma_screen and self.bg_image is not None:
            display = draw_detection_overlay(self.bg_image, self.chroma_screen)
        else:
            display = self.bg_image

        if display is None:
            return

        canvas_w = max(self.canvas.winfo_width(), 400)
        canvas_h = max(self.canvas.winfo_height(), 400)
        img_h, img_w = display.shape[:2]

        scale = min(canvas_w / img_w, canvas_h / img_h, 1.0)
        self._canvas_scale = scale
        disp_w, disp_h = int(img_w * scale), int(img_h * scale)
        self._canvas_offset = ((canvas_w - disp_w) // 2, (canvas_h - disp_h) // 2)

        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb).resize((disp_w, disp_h), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(pil)

        ox, oy = self._canvas_offset
        self.canvas.create_image(ox, oy, anchor=tk.NW, image=self._photo)
        self.canvas.configure(scrollregion=(0, 0, canvas_w, canvas_h))

    # --- Settings persistence ---

    def _on_mode_change(self) -> None:
        if self.display_mode.get() == "split":
            self.split_frame.pack(fill=tk.X)
        else:
            self.split_frame.pack_forget()
        self._refresh_pairs()
        if self.preview_image is not None:
            self._preview()

    def _save_settings(self) -> None:
        data = {
            "display_mode": self.display_mode.get(),
            "split_ratio": self.split_ratio.get(),
            "divider_width": self.divider_width.get(),
            "feather": self.feather.get(),
            "h_min": self.h_min.get(),
            "h_max": self.h_max.get(),
            "s_min": self.s_min.get(),
            "v_min": self.v_min.get(),
            "morph_size": self.morph_size.get(),
        }
        DEFAULT_SETTINGS.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_settings(self) -> None:
        if not DEFAULT_SETTINGS.is_file():
            return
        try:
            data = json.loads(DEFAULT_SETTINGS.read_text(encoding="utf-8"))
            for key, var in [
                ("display_mode", self.display_mode),
                ("split_ratio", self.split_ratio),
                ("divider_width", self.divider_width),
                ("feather", self.feather),
                ("h_min", self.h_min),
                ("h_max", self.h_max),
                ("s_min", self.s_min),
                ("v_min", self.v_min),
                ("morph_size", self.morph_size),
            ]:
                if key in data:
                    var.set(data[key])
            self._on_mode_change()
        except (json.JSONDecodeError, OSError):
            pass

    # --- Actions ---

    def _pick_bg(self) -> None:
        path = filedialog.askopenfilename(
            title="Выберите фон с chroma key",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp"), ("All", "*.*")],
            initialdir=str(SCRIPT_DIR),
        )
        if path:
            self.bg_path.set(path)
            self._reload_background()

    def _pick_input(self) -> None:
        path = filedialog.askdirectory(title="Папка before/after", initialdir=str(SCRIPT_DIR))
        if path:
            self.input_path.set(path)
            self._refresh_pairs()

    def _pick_output(self) -> None:
        path = filedialog.askdirectory(title="Папка результата", initialdir=str(SCRIPT_DIR))
        if path:
            self.output_path.set(path)

    def _reload_background(self) -> None:
        path = Path(self.bg_path.get())
        self.bg_image = load_image(path)
        if self.bg_image is None:
            self._set_status(f"Не удалось загрузить фон: {path}")
            return

        self.preview_image = None
        if not self._detect_chroma():
            self._set_status("Фон загружен, но зелёный экран не найден — настройте HSV")
        else:
            self._set_status("Фон загружен, chroma key обнаружен автоматически")

        self._redraw_canvas()
        self._refresh_pairs()

    def _get_items(self) -> list[tuple[Path, str, Path | None]]:
        """(color_path, name, before_path|None)"""
        folder = Path(self.input_path.get())
        if self.display_mode.get() == "split":
            return [(af, name, bf) for bf, af, name in find_before_after_pairs(folder)]

        return [(path, name, None) for path, name in find_color_images(folder)]

    def _refresh_pairs(self) -> None:
        self.pairs_list.delete(0, tk.END)
        items = self._get_items()
        for color_path, name, before_path in items:
            if before_path:
                self.pairs_list.insert(tk.END, f"{name}  ←  {before_path.name} + {color_path.name}")
            else:
                self.pairs_list.insert(tk.END, f"{name}  ←  {color_path.name}")
        self._set_status(f"Найдено: {len(items)}")

    def _preview(self) -> None:
        if self.bg_image is None:
            messagebox.showerror("Ошибка", "Фон не загружен.")
            return
        if self.chroma_screen is None:
            messagebox.showwarning(
                "Chroma key",
                "Зелёный экран не обнаружен.\nНастройте параметры HSV или проверьте фон.",
            )
            return

        screen = self.chroma_screen
        items = self._get_items()

        if not items:
            test = np.zeros((screen.height, screen.width, 3), dtype=np.uint8)
            for x in range(0, screen.width, 40):
                for y in range(0, screen.height, 40):
                    c = (80, 80, 200) if ((x // 40) + (y // 40)) % 2 == 0 else (200, 80, 80)
                    test[y : y + 40, x : x + 40] = c
            cv2.putText(
                test, "PREVIEW", (20, screen.height // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2,
            )
            self.preview_image = composite_chroma(
                self.bg_image, test, screen, self.feather.get()
            )
        else:
            color_path, _, before_path = items[0]
            result = process_image(
                self.bg_image, screen, color_path, self.feather.get(),
                before_path=before_path,
                mode=self.display_mode.get(),
                split_ratio=self.split_ratio.get(),
                divider_width=self.divider_width.get(),
            )
            if result is None:
                messagebox.showerror("Ошибка", f"Не удалось обработать {color_path.name}")
                return
            self.preview_image = result

        self._save_settings()
        self._redraw_canvas()
        self._set_status("Предпросмотр обновлён")

    def _generate_all(self) -> None:
        threading.Thread(target=self._generate_worker, daemon=True).start()

    def _generate_worker(self) -> None:
        if self.bg_image is None or self.chroma_screen is None:
            self.after(0, lambda: messagebox.showwarning(
                "Ошибка", "Загрузите фон с зелёным экраном iPad."
            ))
            return

        items = self._get_items()
        if not items:
            self.after(0, lambda: messagebox.showwarning(
                "Изображения не найдены",
                f"Положите раскраски в папку:\n{self.input_path.get()}\n\n"
                "  1-1.png, 2-1.png …\n"
                "  photo_after.jpg\n"
                "  или N_color_raster_back.png",
            ))
            return

        self._save_settings()
        screen = self.chroma_screen
        out_base = Path(self.output_path.get())
        out_dir = out_base / datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir.mkdir(parents=True, exist_ok=True)

        self.after(0, lambda: self.progress.configure(maximum=len(items), value=0))

        ok, fail = 0, 0
        for i, (color_path, name, before_path) in enumerate(items):
            result = process_image(
                self.bg_image, screen, color_path, self.feather.get(),
                before_path=before_path,
                mode=self.display_mode.get(),
                split_ratio=self.split_ratio.get(),
                divider_width=self.divider_width.get(),
            )
            if result is None:
                fail += 1
            else:
                safe = re.sub(r'[<>:"/\\|?*]', "_", name)
                cv2.imwrite(str(out_dir / f"{safe}.jpg"), result, [cv2.IMWRITE_JPEG_QUALITY, 95])
                ok += 1

            idx = i + 1
            self.after(0, lambda v=idx: self.progress.configure(value=v))

        msg = f"Готово: {ok} файлов → {out_dir}"
        if fail:
            msg += f" ({fail} ошибок)"
        self.after(0, lambda: self._set_status(msg))
        self.after(0, lambda: messagebox.showinfo("Генерация завершена", msg))

    def _set_status(self, text: str) -> None:
        self.status.config(text=text)


def main() -> None:
    app = CarouselGeneratorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
