#!/usr/bin/env python3
"""
Screen Extract — извлекает экран телефона/планшета из фото.

Простой pipeline: Canny → 4 угла → perspective warp → лёгкий auto-deskew.

Примеры:
  python screen-extract.py photo.jpg -o screen.png
  python screen-extract.py photo.jpg --gui
  python screen-extract.py ./photos/ -o ./screens/
"""

from __future__ import annotations

import argparse
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

SCRIPT_DIR = Path(__file__).resolve().parent
SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".jfif"}
CORNER_LABELS = ["TL", "TR", "BR", "BL"]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def order_points(pts: np.ndarray) -> np.ndarray:
    pts = np.array(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).flatten()
    return np.float32([
        pts[np.argmin(s)],
        pts[np.argmin(diff)],
        pts[np.argmax(s)],
        pts[np.argmax(diff)],
    ])


def output_size(corners: np.ndarray) -> tuple[int, int]:
    tl, tr, br, bl = order_points(corners)
    width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    return max(width, 50), max(height, 50)


def score_quadrilateral(pts: np.ndarray, img_w: int, img_h: int) -> float:
    area = cv2.contourArea(pts.astype(np.float32))
    img_area = img_w * img_h
    area_ratio = area / img_area
    if area_ratio < 0.05 or area_ratio > 0.92:
        return 0.0

    tl, tr, br, bl = order_points(pts)
    ow, oh = output_size(order_points(pts))
    if oh == 0:
        return 0.0

    aspect = ow / oh
    if 0.42 <= aspect <= 0.82:
        aspect_score = 1.0 - abs(aspect - 0.75) * 0.8
    elif 1.2 <= aspect <= 2.4:
        aspect_score = 1.0 - abs(aspect - 1.78) * 0.15
    else:
        aspect_score = 0.2

    return area_ratio * aspect_score


# ---------------------------------------------------------------------------
# Detection (оригинальный Canny-метод — давал лучший результат)
# ---------------------------------------------------------------------------

@dataclass
class ScreenDetection:
    corners: np.ndarray
    score: float
    method: str


def detect_screen(img: np.ndarray) -> ScreenDetection | None:
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    best_score = 0.0
    best_pts: np.ndarray | None = None

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < h * w * 0.05 or area > h * w * 0.85:
            continue

        peri = cv2.arcLength(contour, True)
        for eps in (0.01, 0.015, 0.02, 0.025, 0.03):
            approx = cv2.approxPolyDP(contour, eps * peri, True)
            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue

            pts = order_points(approx.reshape(4, 2))
            score = score_quadrilateral(pts, w, h)
            weighted = score * area
            if weighted > best_score:
                best_score = weighted
                best_pts = pts

    if best_pts is None or best_score < h * w * 0.01:
        return None

    return ScreenDetection(corners=best_pts, score=best_score, method="canny")


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def auto_deskew(img: np.ndarray, max_angle: float = 5.0) -> np.ndarray:
    """Лёгкая коррекция наклона — несколько градусов, не больше."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=max(80, w // 5),
        minLineLength=w // 4,
        maxLineGap=15,
    )
    if lines is None:
        return img

    angles: list[float] = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx = x2 - x1
        if abs(dx) < 40:
            continue
        angle = float(np.degrees(np.arctan2(y2 - y1, dx)))
        if abs(angle) < 8:
            angles.append(angle)

    if len(angles) < 5:
        return img

    correction = float(np.median(angles))
    if abs(correction) < 0.15:
        return img

    correction = float(np.clip(correction, -max_angle, max_angle))

    center = (w / 2, h / 2)
    M = cv2.getRotationMatrix2D(center, correction, 1.0)
    return cv2.warpAffine(
        img, M, (w, h),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REPLICATE,
    )


def extract_screen(
    img: np.ndarray,
    corners: np.ndarray,
    deskew: bool = True,
) -> np.ndarray:
    """Perspective warp + опциональный лёгкий deskew. Без обрезок и inset."""
    pts = order_points(corners)
    w, h = output_size(pts)

    dst = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    M = cv2.getPerspectiveTransform(pts, dst)
    warped = cv2.warpPerspective(img, M, (w, h), flags=cv2.INTER_LANCZOS4)

    if deskew:
        warped = auto_deskew(warped)
    return warped


def draw_overlay(img: np.ndarray, corners: np.ndarray) -> np.ndarray:
    vis = img.copy()
    pts = order_points(corners).astype(int)
    cv2.polylines(vis, [pts], True, (0, 255, 0), 3)
    for pt, lbl in zip(pts, CORNER_LABELS):
        cv2.circle(vis, tuple(pt), 10, (0, 0, 255), -1)
        cv2.putText(vis, lbl, (pt[0] + 12, pt[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return vis


def load_image(path: Path) -> np.ndarray | None:
    return cv2.imread(str(path), cv2.IMREAD_COLOR)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def process_file(
    input_path: Path,
    output_path: Path,
    corners: np.ndarray | None = None,
    deskew: bool = True,
) -> bool:
    img = load_image(input_path)
    if img is None:
        print(f"  [FAIL] ne udalos zagruzit: {input_path}", file=sys.stderr)
        return False

    if corners is None:
        det = detect_screen(img)
        if det is None:
            print(f"  [FAIL] ekran ne nayden: {input_path.name}", file=sys.stderr)
            return False
        corners = det.corners

    result = extract_screen(img, corners, deskew=deskew)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), result, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return True


def run_cli(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    deskew = not args.no_deskew

    if input_path.is_dir():
        out_dir = Path(args.output) if args.output else input_path / "screens"
        out_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(
            f for f in input_path.iterdir()
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXT
        )
        ok = 0
        for f in files:
            out = out_dir / f"{f.stem}_screen.jpg"
            if process_file(f, out, deskew=deskew):
                print(f"  [OK] {f.name} -> {out.name}")
                ok += 1
        print(f"\nGotovo: {ok}/{len(files)} -> {out_dir}")
        return 0 if ok else 1

    if not input_path.is_file():
        print(f"Fayl ne nayden: {input_path}", file=sys.stderr)
        return 1

    out = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_screen.jpg")
    if process_file(input_path, out, deskew=deskew):
        print(f"[OK] {out}")
        return 0
    return 1


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class ScreenExtractApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Screen Extract")
        self.geometry("1200x800")
        self.minsize(900, 600)

        self.deskew = tk.BooleanVar(value=True)
        self.show_extracted = tk.BooleanVar(value=False)
        self.calib_mode = tk.BooleanVar(value=False)

        self.source_image: np.ndarray | None = None
        self.corners: list[list[float]] = []
        self.detection: ScreenDetection | None = None
        self.extracted: np.ndarray | None = None

        self._canvas_scale = 1.0
        self._canvas_offset = (0.0, 0.0)
        self._photo: ImageTk.PhotoImage | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(main, width=300)
        right = ttk.Frame(main)
        main.add(left, weight=0)
        main.add(right, weight=1)

        pad = {"padx": 6, "pady": 4}

        ttk.Label(left, text="Screen Extract", font=("", 12, "bold")).pack(anchor=tk.W, **pad)
        ttk.Button(left, text="Открыть фото", command=self._open_image).pack(fill=tk.X, **pad)
        ttk.Button(left, text="Открыть папку (batch)", command=self._batch_folder).pack(fill=tk.X, **pad)

        ttk.Separator(left).pack(fill=tk.X, pady=8)
        ttk.Button(left, text="Авто-детекция", command=self._auto_detect).pack(fill=tk.X, **pad)

        calib_row = ttk.Frame(left)
        calib_row.pack(fill=tk.X, **pad)
        ttk.Checkbutton(calib_row, text="Ручная правка", variable=self.calib_mode).pack(side=tk.LEFT)
        ttk.Button(calib_row, text="Сброс", command=self._clear_corners).pack(side=tk.LEFT, padx=4)

        ttk.Checkbutton(left, text="Auto-deskew (~градусы)", variable=self.deskew,
                        command=self._update_extracted).pack(anchor=tk.W, **pad)
        ttk.Checkbutton(left, text="Показать результат", variable=self.show_extracted,
                        command=self._redraw_canvas).pack(anchor=tk.W, **pad)

        ttk.Button(left, text="Сохранить экран", command=self._save).pack(fill=tk.X, **pad)

        self.corner_status = ttk.Label(left, text="Углы: не заданы", foreground="#888")
        self.corner_status.pack(anchor=tk.W, **pad)
        self.detect_info = ttk.Label(left, text="", foreground="#444", wraplength=280)
        self.detect_info.pack(anchor=tk.W, **pad)
        self.status = ttk.Label(left, text="", foreground="#228822", wraplength=280)
        self.status.pack(anchor=tk.W, **pad)

        ttk.Label(right, text="Предпросмотр", font=("", 11, "bold")).pack(anchor=tk.W)
        self.canvas = tk.Canvas(right, bg="#2b2b2b", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, pady=4)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Configure>", lambda _: self._redraw_canvas())

    def _open_image(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp"), ("All", "*.*")],
            initialdir=str(SCRIPT_DIR),
        )
        if not path:
            return
        self.source_image = load_image(Path(path))
        if self.source_image is None:
            messagebox.showerror("Ошибка", "Не удалось загрузить изображение")
            return
        self.corners.clear()
        self.extracted = None
        self.show_extracted.set(False)
        self._auto_detect()

    def _auto_detect(self) -> None:
        if self.source_image is None:
            return
        self.detection = detect_screen(self.source_image)
        if self.detection is None:
            self.detect_info.config(text="Экран не найден — отметьте 4 угла вручную.")
            self.calib_mode.set(True)
            self._update_corner_status()
            self._redraw_canvas()
            return

        self.corners = self.detection.corners.tolist()
        self.detect_info.config(text=f"Метод: {self.detection.method}")
        self._update_corner_status()
        self._update_extracted()
        self._redraw_canvas()

    def _clear_corners(self) -> None:
        self.corners.clear()
        self.extracted = None
        self._update_corner_status()
        self._redraw_canvas()

    def _get_corners(self) -> np.ndarray | None:
        return np.float32(self.corners) if len(self.corners) == 4 else None

    def _update_corner_status(self) -> None:
        n = len(self.corners)
        self.corner_status.config(
            text=f"Углы: {n}/4" + (" OK" if n == 4 else ""),
            foreground="#228822" if n == 4 else "#888",
        )

    def _update_extracted(self) -> None:
        corners = self._get_corners()
        if self.source_image is None or corners is None:
            self.extracted = None
            return
        self.extracted = extract_screen(self.source_image, corners, deskew=self.deskew.get())

    def _on_click(self, event) -> None:
        if not self.calib_mode.get() or self.source_image is None or len(self.corners) >= 4:
            return
        ox, oy = self._canvas_offset
        ix = (event.x - ox) / self._canvas_scale
        iy = (event.y - oy) / self._canvas_scale
        h, w = self.source_image.shape[:2]
        self.corners.append([
            float(np.clip(ix, 0, w - 1)),
            float(np.clip(iy, 0, h - 1)),
        ])
        self._update_corner_status()
        if len(self.corners) == 4:
            self._update_extracted()
        self._redraw_canvas()

    def _redraw_canvas(self) -> None:
        self.canvas.delete("all")
        if self.show_extracted.get() and self.extracted is not None:
            display = self.extracted
        elif self.source_image is not None:
            display = self.source_image.copy()
            corners = self._get_corners()
            if corners is not None:
                display = draw_overlay(display, corners)
        else:
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

    def _save(self) -> None:
        self._update_extracted()
        if self.extracted is None:
            messagebox.showwarning("Углы", "Сначала найдите или отметьте 4 угла.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".jpg",
            initialfile="screen.jpg",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png")],
        )
        if path:
            cv2.imwrite(path, self.extracted, [cv2.IMWRITE_JPEG_QUALITY, 95])
            self.status.config(text=f"Сохранено: {path}")

    def _batch_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=str(SCRIPT_DIR))
        if not folder:
            return
        out_dir = Path(folder) / "screens"
        out_dir.mkdir(exist_ok=True)
        files = [f for f in Path(folder).iterdir() if f.suffix.lower() in SUPPORTED_EXT]
        ok = sum(
            1 for f in files
            if process_file(f, out_dir / f"{f.stem}_screen.jpg", deskew=self.deskew.get())
        )
        messagebox.showinfo("Готово", f"Обработано: {ok}/{len(files)}\n{out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Извлечение экрана из фото")
    parser.add_argument("input", nargs="?", help="Фото или папка")
    parser.add_argument("-o", "--output", help="Выходной файл или папка")
    parser.add_argument("--no-deskew", action="store_true", help="Без коррекции наклона")
    parser.add_argument("--gui", action="store_true", help="Открыть GUI")
    args = parser.parse_args()

    if args.gui or not args.input:
        ScreenExtractApp().mainloop()
        return

    sys.exit(run_cli(args))


if __name__ == "__main__":
    main()
