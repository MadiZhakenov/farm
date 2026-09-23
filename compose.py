#!/usr/bin/env python3
"""
Compose — canvas.jpg + раскраска → bg_ipad.jpg (chroma key).

Качество: supersampling warp (OpenCV рекомендация)
  1. Рендер в N× разрешении
  2. warpPerspective на большом кадре
  3. Финальный downscale через INTER_AREA — пиксели усредняются, не теряются

  python compose.py
  python compose.py --all --output-dir output/results
  python compose.py --gui
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

SCRIPT_DIR = Path(__file__).resolve().parent
CANVAS = SCRIPT_DIR / "canvas.jpg"
BG = SCRIPT_DIR / "bg_ipad.jpg"
DEFAULT_INPUT = SCRIPT_DIR / "before after"
DEFAULT_OUTPUT = SCRIPT_DIR / "output" / "composed"
SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".jfif"}

JPEG_QUALITY = 100

# Край рамки iPad — warp rounded-rect; палец = skin вне green screen
SUPERSAMPLE = 4
OUTPUT_SCALE = 2.0
CORNER_EXPAND = 1.04
CORNER_RADIUS_BG = 22
GREEN_DILATE = 5
CHROMA_DILATE = 5
MASK_AA = 6
DESPILL = 0.65

ART_SCALE = 0.9


def _load_carousel():
    path = SCRIPT_DIR / "carousel-gen.py"
    spec = importlib.util.spec_from_file_location("carousel_gen", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["carousel_gen"] = mod
    spec.loader.exec_module(mod)
    return mod


def detect_drawing_area(canvas: np.ndarray) -> tuple[int, int, int, int]:
    h, w = canvas.shape[:2]
    hsv = cv2.cvtColor(canvas, cv2.COLOR_BGR2HSV)
    drawing = (hsv[:, :, 1] < 40) & (hsv[:, :, 2] > 205)
    drawing[: int(h * 0.09), :] = False
    drawing[int(h * 0.63) :, :] = False
    drawing[:, : int(w * 0.06)] = False
    drawing[:, int(w * 0.94) :] = False

    coords = cv2.findNonZero(drawing.astype(np.uint8) * 255)
    if coords is None:
        return int(w * 0.06), int(h * 0.09), int(w * 0.88), int(h * 0.54)
    return cv2.boundingRect(coords)


def crop_square(img: np.ndarray) -> np.ndarray:
    """Центральный квадрат без масштабирования — пиксели 1:1."""
    h, w = img.shape[:2]
    side = min(h, w)
    y0 = (h - side) // 2
    x0 = (w - side) // 2
    return img[y0 : y0 + side, x0 : x0 + side].copy()


def fit_artwork(img: np.ndarray, target_size: int) -> np.ndarray:
    """Подгоняет квадрат раскраски под target_size (AREA вниз, LANCZOS4 вверх)."""
    square = crop_square(img)
    side = square.shape[0]
    if side == target_size:
        return square
    interp = cv2.INTER_AREA if side > target_size else cv2.INTER_LANCZOS4
    return cv2.resize(square, (target_size, target_size), interpolation=interp)


def paste_artwork(
    canvas: np.ndarray,
    artwork: np.ndarray,
    inset: float = 0.05,
    art_scale: float = ART_SCALE,
) -> np.ndarray:
    """Вставляет раскраску на нативный canvas — UI-шаблон не меняется."""
    result = canvas.copy()
    x, y, rw, rh = detect_drawing_area(canvas)
    base_sq = int(min(rw, rh) * (1 - 2 * inset))
    target_sq = max(int(base_sq * art_scale), 50)

    art = fit_artwork(artwork, target_sq)
    ah, aw = art.shape[:2]
    cx = x + rw // 2
    cy = y + rh // 2
    x0 = cx - aw // 2
    y0 = cy - ah // 2

    x1, y1 = x0 + aw, y0 + ah
    cx0 = max(0, x0)
    cy0 = max(0, y0)
    cx1 = min(result.shape[1], x1)
    cy1 = min(result.shape[0], y1)
    if cx0 < cx1 and cy0 < cy1:
        sx0, sy0 = cx0 - x0, cy0 - y0
        result[cy0:cy1, cx0:cx1] = art[sy0 : sy0 + (cy1 - cy0), sx0 : sx0 + (cx1 - cx0)]
    return result


def upscale_canvas(canvas: np.ndarray, factor: int) -> np.ndarray:
    """Равномерное увеличение canvas (только upscale UI-рамки)."""
    if factor <= 1:
        return canvas
    h, w = canvas.shape[:2]
    return cv2.resize(canvas, (w * factor, h * factor), interpolation=cv2.INTER_LANCZOS4)


def build_screen_content(
    canvas: np.ndarray,
    artwork: np.ndarray,
    inset: float,
    render_scale: int,
    art_scale: float = ART_SCALE,
) -> np.ndarray:
    """Раскраска на нативный canvas, затем upscale всего кадра для warp."""
    screen = paste_artwork(canvas, artwork, inset=inset, art_scale=art_scale)
    return upscale_canvas(screen, render_scale)


def expand_corners(corners: np.ndarray, scale: float = CORNER_EXPAND) -> np.ndarray:
    """Расширяет quad от центра — warp перекрывает green screen с запасом."""
    c = corners.astype(np.float32)
    center = c.mean(axis=0)
    return center + (c - center) * scale


def rounded_rect(h: int, w: int, radius: int) -> np.ndarray:
    """Белый скруглённый прямоугольник — форма экрана iPad в source-space."""
    r = max(1, min(radius, w // 2 - 1, h // 2 - 1))
    img = np.zeros((h, w), dtype=np.uint8)
    cv2.rectangle(img, (r, 0), (w - r, h), 255, -1, lineType=cv2.LINE_AA)
    cv2.rectangle(img, (0, r), (w, h - r), 255, -1, lineType=cv2.LINE_AA)
    for cx, cy in ((r, r), (w - r - 1, r), (r, h - r - 1), (w - r - 1, h - r - 1)):
        cv2.circle(img, (cx, cy), r, 255, -1, lineType=cv2.LINE_AA)
    return img


def screen_alpha_from_photo(mask: np.ndarray, tw: int, th: int, aa: int = MASK_AA) -> np.ndarray:
    """Photo mask: close → supersample → downscale (углы с фото, края сглажены)."""
    m = mask.copy()
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    aa = max(1, aa)
    big = cv2.resize(m, (tw * aa, th * aa), interpolation=cv2.INTER_NEAREST)
    a = cv2.resize(big, (tw, th), interpolation=cv2.INTER_AREA)
    return np.clip(a.astype(np.float32) / 255.0, 0.0, 1.0)


def build_screen_alpha(
    h_s: int, w_s: int, M: np.ndarray,
    mask: np.ndarray, warp_w: int, warp_h: int, block: np.ndarray,
) -> np.ndarray:
    """warp × photo — углы с фото, край совпадает с контентом."""
    src_a = np.full((h_s, w_s), 255, dtype=np.uint8)
    warp_a = cv2.warpPerspective(
        src_a, M, (warp_w, warp_h),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0,
    ).astype(np.float32) / 255.0
    photo_a = screen_alpha_from_photo(mask, warp_w, warp_h)
    alpha = warp_a * photo_a
    return np.where(block, 0.0, alpha).astype(np.float32)


def finger_block(bg: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Где нельзя рисовать: левый bezel + палец (кожа вне green screen)."""
    mh, mw = bg.shape[:2]
    m = cv2.resize(mask, (mw, mh), interpolation=cv2.INTER_NEAREST)
    block = np.zeros((mh, mw), dtype=bool)
    xs = np.where(m > 127)[1]
    if xs.size:
        block[:, : int(xs.min())] = True
    hsv = cv2.cvtColor(bg, cv2.COLOR_BGR2HSV)
    skin = cv2.inRange(hsv, np.array([0, 20, 40]), np.array([25, 220, 255])) > 0
    block |= skin & (m < 128)
    return block


def detect_chroma_green(bg: np.ndarray, dilate: int = 0) -> np.ndarray:
    """Только neon green screen (как в carousel-gen), не зелень в рисунке/фоне."""
    hsv = cv2.cvtColor(bg, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([35, 80, 80]), np.array([85, 255, 255]))
    if dilate > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate | 1, dilate | 1))
        green = cv2.dilate(green, k, iterations=1)
    return green > 0


def chroma_fill_mask(mask: np.ndarray, tw: int, th: int, dilate: int = CHROMA_DILATE) -> np.ndarray:
    """Маска экрана с фото (dilated) — зона полной замены."""
    m = cv2.resize(mask, (tw, th), interpolation=cv2.INTER_NEAREST)
    if dilate > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate | 1, dilate | 1))
        m = cv2.dilate(m, k, iterations=1)
    return m > 127


def downscale_aa(img: np.ndarray, tw: int, th: int) -> np.ndarray:
    """Пошаговый INTER_AREA — каждый шаг ~25%, без лесенки на диагоналях."""
    h, w = img.shape[:2]
    while w > tw + 4 or h > th + 4:
        nw = max(tw, (w * 3) // 4)
        nh = max(th, (h * 3) // 4)
        if nw >= w - 1 and nh >= h - 1:
            break
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
    return cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)


def despill_green(img: np.ndarray, alpha: np.ndarray, amount: float = DESPILL) -> np.ndarray:
    """Убирает зелёный spill в области экрана (классический chroma despill)."""
    if amount <= 0:
        return img
    b, g, r = cv2.split(img.astype(np.float32))
    max_rb = np.maximum(r, b)
    spill = np.maximum(0.0, g - max_rb)
    g = g - spill * amount
    out = cv2.merge([b, g, r])
    out = np.clip(out, 0, 255).astype(np.uint8)
    a = alpha if alpha.ndim == 2 else alpha[..., 0]
    mask = (a > 0.05)[..., np.newaxis]
    return np.where(mask, out, img)


def composite_chroma_supersample(
    bg: np.ndarray,
    screen_content: np.ndarray,
    corners: np.ndarray,
    mask: np.ndarray,
    ss: int = SUPERSAMPLE,
    output_scale: float = OUTPUT_SCALE,
    corner_expand: float = CORNER_EXPAND,
) -> np.ndarray:
    """
    Chroma key = замена только внутри маски green screen на фото.
    Зелень в рисунке/UI/фоне не трогаем.
    """
    h, w = bg.shape[:2]
    ss = max(1, ss)
    out_w = max(1, int(round(w * output_scale)))
    out_h = max(1, int(round(h * output_scale)))

    warp_w, warp_h = w * ss, h * ss
    bg_hi = cv2.resize(bg, (warp_w, warp_h), interpolation=cv2.INTER_LINEAR)
    corners_hi = expand_corners(corners.astype(np.float32) * ss, corner_expand)
    block = finger_block(bg_hi, mask)

    h_s, w_s = screen_content.shape[:2]
    pts_src = np.float32([[0, 0], [w_s, 0], [w_s, h_s], [0, h_s]])
    M = cv2.getPerspectiveTransform(pts_src, corners_hi)

    warped = cv2.warpPerspective(
        screen_content, M, (warp_w, warp_h),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
    )

    alpha = build_screen_alpha(h_s, w_s, M, mask, warp_w, warp_h, block)

    # край = только smooth alpha из warp (не jagged chroma mask)
    alpha_3 = alpha[..., np.newaxis]
    result_hi = np.clip(
        bg_hi.astype(np.float32) * (1 - alpha_3) + warped.astype(np.float32) * alpha_3,
        0, 255,
    ).astype(np.uint8)

    # hard replace neon-green только внутри screen mask
    screen = chroma_fill_mask(mask, warp_w, warp_h) & ~block
    fringe = detect_chroma_green(bg_hi, GREEN_DILATE) & screen
    result_hi[fringe] = warped[fringe]
    leftover = detect_chroma_green(bg_hi) & detect_chroma_green(result_hi) & screen & ~block
    result_hi[leftover] = warped[leftover]

    result_hi = despill_green(result_hi, alpha)

    if (warp_w, warp_h) == (out_w, out_h):
        return result_hi
    return downscale_aa(result_hi, out_w, out_h)


def find_color_images(folder: Path) -> list[tuple[Path, str]]:
    found: dict[str, Path] = {}
    for f in folder.iterdir():
        if not f.is_file() or f.suffix.lower() not in SUPPORTED:
            continue
        m = re.match(r"^(.+)-1$", f.stem, re.I)
        if m:
            found[m.group(1)] = f
    for f in folder.iterdir():
        if not f.is_file() or f.suffix.lower() not in SUPPORTED:
            continue
        if f.stem.endswith("_color_raster_back"):
            found.setdefault(f.stem.replace("_color_raster_back", ""), f)

    def sort_key(k: str) -> tuple:
        return (0, int(k)) if k.isdigit() else (1, k)

    return [(found[k], k) for k in sorted(found, key=sort_key)]


def save_image(path: Path, img: np.ndarray, png: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if png or path.suffix.lower() == ".png":
        cv2.imwrite(str(path.with_suffix(".png")), img)
    else:
        cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])


def compose_one(
    artwork_path: Path,
    canvas: np.ndarray,
    bg: np.ndarray,
    chroma,
    inset: float = 0.05,
    render_scale: int = SUPERSAMPLE,
    warp_ss: int = SUPERSAMPLE,
    output_scale: float = OUTPUT_SCALE,
    art_scale: float = ART_SCALE,
) -> np.ndarray | None:
    art = cv2.imread(str(artwork_path), cv2.IMREAD_COLOR)
    if art is None:
        return None

    screen = build_screen_content(canvas, art, inset, render_scale, art_scale)
    return composite_chroma_supersample(
        bg, screen, chroma.corners, chroma.mask, ss=warp_ss, output_scale=output_scale
    )


def run_batch(
    input_dir: Path,
    output_dir: Path,
    limit: int | None = 5,
    inset: float = 0.05,
    render_scale: int = SUPERSAMPLE,
    warp_ss: int = SUPERSAMPLE,
    output_scale: float = OUTPUT_SCALE,
    art_scale: float = ART_SCALE,
    png: bool = False,
    on_progress=None,
) -> int:
    cg = _load_carousel()
    canvas = cv2.imread(str(CANVAS), cv2.IMREAD_COLOR)
    bg = cv2.imread(str(BG), cv2.IMREAD_COLOR)
    if canvas is None or bg is None:
        print("[FAIL] canvas.jpg / bg_ipad.jpg", file=sys.stderr)
        return 0

    chroma = cg.detect_chroma_screen(bg)
    if chroma is None:
        print("[FAIL] chroma key ne nayden", file=sys.stderr)
        return 0

    ch, cw = canvas.shape[:2]
    print(f"Render canvas: {cw}x{ch} x{render_scale} = {cw*render_scale}x{ch*render_scale}")
    print(f"Canvas native, art x{art_scale} on slot, then render x{render_scale}")

    images = find_color_images(input_dir)
    if limit:
        images = images[:limit]
    if not images:
        print(f"[FAIL] net raskrasok v {input_dir}", file=sys.stderr)
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    ext = ".png" if png else ".jpg"
    ok = 0

    for i, (path, name) in enumerate(images):
        result = compose_one(
            path, canvas, bg, chroma, inset, render_scale, warp_ss, output_scale, art_scale
        )
        if result is None:
            print(f"  [FAIL] {path.name}")
            if on_progress:
                on_progress(i + 1, len(images), path.name, False)
            continue
        safe = re.sub(r'[<>:"/\\|?*]', "_", name)
        out = output_dir / f"{safe}{ext}"
        save_image(out, result, png=png)
        print(f"  [OK] {path.name} -> {out.name} ({result.shape[1]}x{result.shape[0]})")
        ok += 1
        if on_progress:
            on_progress(i + 1, len(images), path.name, True)

    print(f"\nGotovo: {ok} -> {output_dir}")
    return ok


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class ComposeApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Compose — Canvas + iPad")
        self.geometry("1100x720")
        self.minsize(900, 560)

        self.input_dir = tk.StringVar(value=str(DEFAULT_INPUT))
        self.output_dir = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.limit = tk.IntVar(value=5)
        self.process_all = tk.BooleanVar(value=False)
        self.art_scale = tk.DoubleVar(value=ART_SCALE)
        self.supersample = tk.IntVar(value=SUPERSAMPLE)
        self.png_out = tk.BooleanVar(value=False)

        self.preview_image: np.ndarray | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._busy = False

        self._build_ui()
        self._update_count()

    def _build_ui(self) -> None:
        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(main, width=320)
        right = ttk.Frame(main)
        main.add(left, weight=0)
        main.add(right, weight=1)

        pad = {"padx": 6, "pady": 4}

        ttk.Label(left, text="Compose", font=("", 12, "bold")).pack(anchor=tk.W, **pad)
        ttk.Label(
            left,
            text="canvas.jpg + раскраска → bg_ipad.jpg",
            foreground="#666",
        ).pack(anchor=tk.W, **pad)

        self._dir_row(left, "Папка раскрасок:", self.input_dir, self._pick_input)
        self._dir_row(left, "Папка результата:", self.output_dir, self._pick_output)

        ttk.Separator(left).pack(fill=tk.X, pady=8)

        limit_row = ttk.Frame(left)
        limit_row.pack(fill=tk.X, **pad)
        ttk.Label(limit_row, text="Лимит:").pack(side=tk.LEFT)
        ttk.Spinbox(limit_row, from_=1, to=999, textvariable=self.limit, width=6).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Checkbutton(
            limit_row, text="Все", variable=self.process_all, command=self._update_count
        ).pack(side=tk.LEFT, padx=8)

        self._slider_row(left, "Art scale:", self.art_scale, 0.3, 2.0, "")
        self._slider_row(left, "Supersample:", self.supersample, 1, 8, "×", int_val=True)

        ttk.Checkbutton(left, text="Сохранять PNG", variable=self.png_out).pack(anchor=tk.W, **pad)

        self.count_label = ttk.Label(left, text="", foreground="#444")
        self.count_label.pack(anchor=tk.W, **pad)

        ttk.Separator(left).pack(fill=tk.X, pady=8)

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, **pad)
        ttk.Button(btn_row, text="Предпросмотр", command=self._preview).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Сгенерировать", command=self._generate).pack(side=tk.LEFT, padx=6)

        self.progress = ttk.Progressbar(left, mode="determinate")
        self.progress.pack(fill=tk.X, **pad)

        self.status = ttk.Label(left, text="", foreground="#228822", wraplength=290)
        self.status.pack(anchor=tk.W, **pad)

        ttk.Label(right, text="Предпросмотр", font=("", 11, "bold")).pack(anchor=tk.W)
        self.canvas = tk.Canvas(right, bg="#2b2b2b", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, pady=4)
        self.canvas.bind("<Configure>", lambda _: self._redraw_canvas())

    def _dir_row(self, parent, label: str, var: tk.StringVar, cmd) -> None:
        ttk.Label(parent, text=label).pack(anchor=tk.W, padx=6)
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=6, pady=2)
        ttk.Entry(row, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="…", width=3, command=cmd).pack(side=tk.LEFT, padx=4)

    def _slider_row(
        self, parent, label: str, var, lo, hi, suffix: str, int_val: bool = False,
    ) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=6, pady=2)
        ttk.Label(frame, text=label, width=14).pack(side=tk.LEFT)
        scale = ttk.Scale(
            frame, from_=lo, to=hi, variable=var,
            command=lambda _: None,
        )
        scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        fmt = "{:.0f}" if int_val else "{:.2f}"
        ttk.Label(frame, textvariable=var, width=5).pack(side=tk.LEFT, padx=4)

    def _pick_input(self) -> None:
        path = filedialog.askdirectory(initialdir=self.input_dir.get())
        if path:
            self.input_dir.set(path)
            self._update_count()

    def _pick_output(self) -> None:
        path = filedialog.askdirectory(initialdir=self.output_dir.get())
        if path:
            self.output_dir.set(path)

    def _update_count(self) -> None:
        images = find_color_images(Path(self.input_dir.get()))
        n = len(images)
        if self.process_all.get():
            self.count_label.config(text=f"Найдено: {n} раскрасок")
        else:
            lim = max(1, self.limit.get())
            self.count_label.config(text=f"Найдено: {n}, будет: {min(n, lim)}")

    def _check_assets(self) -> bool:
        if not CANVAS.is_file() or not BG.is_file():
            messagebox.showerror(
                "Ошибка",
                f"Нужны файлы в папке проекта:\n{CANVAS.name}\n{BG.name}",
            )
            return False
        return True

    def _load_chroma(self):
        cg = _load_carousel()
        bg = cv2.imread(str(BG), cv2.IMREAD_COLOR)
        chroma = cg.detect_chroma_screen(bg)
        if chroma is None:
            messagebox.showerror("Chroma key", "Зелёный экран не найден на bg_ipad.jpg")
            return None, None, None
        canvas = cv2.imread(str(CANVAS), cv2.IMREAD_COLOR)
        if canvas is None:
            messagebox.showerror("Ошибка", f"Не удалось загрузить {CANVAS.name}")
            return None, None, None
        return canvas, bg, chroma

    def _preview(self) -> None:
        if not self._check_assets():
            return
        images = find_color_images(Path(self.input_dir.get()))
        if not images:
            messagebox.showwarning("Нет файлов", "Положите N-1.png или *_color_raster_back в папку")
            return
        canvas, bg, chroma = self._load_chroma()
        if chroma is None:
            return
        ss = int(self.supersample.get())
        result = compose_one(
            images[0][0], canvas, bg, chroma, 0.05, ss, ss,
            OUTPUT_SCALE, float(self.art_scale.get()),
        )
        if result is None:
            messagebox.showerror("Ошибка", f"Не удалось обработать {images[0][0].name}")
            return
        self.preview_image = result
        self._redraw_canvas()
        self._set_status(f"Предпросмотр: {images[0][0].name}")

    def _generate(self) -> None:
        if self._busy:
            return
        if not self._check_assets():
            return
        self._busy = True
        threading.Thread(target=self._generate_worker, daemon=True).start()

    def _generate_worker(self) -> None:
        input_dir = Path(self.input_dir.get())
        output_dir = Path(self.output_dir.get())
        limit = None if self.process_all.get() else max(1, self.limit.get())
        ss = int(self.supersample.get())
        images = find_color_images(input_dir)
        if limit:
            total = min(len(images), limit)
        else:
            total = len(images)

        if total == 0:
            self.after(0, lambda: messagebox.showwarning(
                "Нет файлов", "Положите N-1.png или *_color_raster_back в папку"
            ))
            self._busy = False
            return

        self.after(0, lambda: self.progress.configure(maximum=total, value=0))
        self.after(0, lambda: self._set_status("Генерация…"))

        def on_progress(done: int, _total: int, name: str, ok: bool) -> None:
            status = f"{'OK' if ok else 'FAIL'}: {name} ({done}/{total})"
            self.after(0, lambda: self.progress.configure(value=done))
            self.after(0, lambda s=status: self._set_status(s))

        ok = run_batch(
            input_dir, output_dir, limit, 0.05, ss, ss,
            OUTPUT_SCALE, float(self.art_scale.get()), self.png_out.get(),
            on_progress=on_progress,
        )

        msg = f"Готово: {ok} → {output_dir}"
        self.after(0, lambda: self._set_status(msg))
        self.after(0, lambda: messagebox.showinfo("Готово", msg))
        self.after(0, lambda: self.progress.configure(value=0))
        self._busy = False

    def _redraw_canvas(self) -> None:
        self.canvas.delete("all")
        if self.preview_image is None:
            return
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        img = cv2.cvtColor(self.preview_image, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(img)
        pil.thumbnail((cw, ch), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(pil)
        x = (cw - self._photo.width()) // 2
        y = (ch - self._photo.height()) // 2
        self.canvas.create_image(x, y, anchor=tk.NW, image=self._photo)

    def _set_status(self, text: str) -> None:
        self.status.config(text=text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Canvas + iPad compositor (supersampling)")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--inset", type=float, default=0.05)
    parser.add_argument("--supersample", type=int, default=SUPERSAMPLE,
                        help="SS для render canvas и warp (default 4)")
    parser.add_argument("--output-scale", type=float, default=OUTPUT_SCALE,
                        help="Финал = bg × scale; SS/scale ≥ 2 даёт настоящий AA (default 2)")
    parser.add_argument("--art-scale", type=float, default=ART_SCALE,
                        help="Множитель размера раскраски (default 1.5)")
    parser.add_argument("--png", action="store_true")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--gui", action="store_true", help="Открыть GUI")
    args = parser.parse_args()

    if args.gui or len(sys.argv) == 1:
        ComposeApp().mainloop()
        return

    limit = None if args.all else args.limit
    ss = args.supersample

    if args.input:
        cg = _load_carousel()
        canvas = cv2.imread(str(CANVAS), cv2.IMREAD_COLOR)
        bg = cv2.imread(str(BG), cv2.IMREAD_COLOR)
        chroma = cg.detect_chroma_screen(bg)
        result = compose_one(
            args.input, canvas, bg, chroma, args.inset, ss, ss, args.output_scale, args.art_scale
        )
        out = args.output or DEFAULT_OUTPUT / "single.jpg"
        save_image(out, result, png=args.png)
        print(f"[OK] {out}")
        return

    run_batch(
        args.input_dir, args.output_dir, limit, args.inset, ss, ss,
        args.output_scale, args.art_scale, args.png,
    )


if __name__ == "__main__":
    main()
