#!/usr/bin/env python3
"""
Quick Trim — тяни края выделения, проставь на всех роликах, один общий экспорт.

Запуск:
  python quick_trim.py
  python quick_trim.py "E:/Users/Desktop/farm/yandex_videos"

Хоткеи:
  Space          play / pause (луп куска)
  E / Enter      экспорт текущего
  Ctrl+E         экспорт ВСЕХ с метками
  N / B          след / пред
  ← →            ±0.1 с   |  Shift+← →  ±1 с
  колесо         зум таймлайна
  R              сброс куска на всё видео
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parent
DEFAULT_DIR = ROOT / "yandex_videos"
CLIPS_DIRNAME = "clips"
MARKS_FILE = "_trim_marks.json"
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}

PREVIEW_MAX_W = 720
PREVIEW_UI_FPS = 30
HANDLE_PX = 10
HIT_PX = 14
MIN_LEN = 0.05
TL_ZOOM_MIN = 1.0
TL_ZOOM_MAX = 60.0
MAX_CACHE_FRAMES = 900  # ~30с при 30fps

C_BG = "#0f0f0f"
C_PANEL = "#1a1a1a"
C_TRACK = "#2a2a2a"
C_TEXT = "#e8e8e8"
C_MUTED = "#888888"
C_ACCENT = "#00d4aa"
C_PLAY = "#ff4466"
C_RANGE = "#1a5c4a"
C_HANDLE = "#00d4aa"
C_DONE = "#3d8b6e"
C_MARKED = "#7ec8b0"


def fmt(t: float) -> str:
    t = max(0.0, t)
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def list_videos(folder: Path) -> list[Path]:
    files = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    ]
    return sorted(files, key=lambda p: p.name.lower())


def probe(path: Path) -> tuple[float, float, int, int]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        r = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate",
                "-show_entries", "format=duration",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            fmt_d = data.get("format") or {}
            st = (data.get("streams") or [{}])[0]
            dur = float(fmt_d.get("duration") or 0)
            w = int(st.get("width") or 0)
            h = int(st.get("height") or 0)
            rate = st.get("avg_frame_rate") or st.get("r_frame_rate") or "25/1"
            fps = 25.0
            if "/" in rate:
                a, b = rate.split("/", 1)
                den = float(b) or 1.0
                fps = float(a) / den
            if dur > 0 and fps > 0.5:
                return dur, fps, w, h

    cap = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    if not cap.isOpened():
        raise RuntimeError(f"Не открывается: {path.name}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    dur = n / fps if fps > 0 and n > 0 else 0.0
    cap.release()
    if dur <= 0:
        raise RuntimeError(f"Нет длительности: {path.name}")
    return dur, fps if fps > 0.5 else 25.0, w, h


def downscale_bgr(frame: np.ndarray, max_w: int = PREVIEW_MAX_W) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= max_w:
        return frame
    nh = max(1, int(h * (max_w / w)))
    return cv2.resize(frame, (max_w, nh), interpolation=cv2.INTER_LINEAR)


class QuickTrim(tk.Tk):
    def __init__(self, folder: Path) -> None:
        super().__init__()
        self.title("Quick Trim")
        self.geometry("1180x760")
        self.minsize(960, 620)
        self.configure(bg=C_BG)

        self.folder = folder
        self.out_dir = folder / CLIPS_DIRNAME
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.videos = list_videos(folder)
        self.idx = 0

        self.marks: dict[str, tuple[float, float]] = {}
        self._load_marks_file()

        self.cap: cv2.VideoCapture | None = None
        self.duration = 0.0
        self.fps = 25.0
        self.pos = 0.0
        self.mark_in = 0.0
        self.mark_out = 0.0
        self.playing = False
        self._play_job: str | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._frame_queue: list[tuple[float, np.ndarray]] = []
        self._decode_stop = False
        self._decode_thread: threading.Thread | None = None
        self._play_wall_start = 0.0
        self._play_pos_start = 0.0
        self._drag_mode: str | None = None
        self._last_bgr: np.ndarray | None = None
        self.exported: set[str] = set()
        self._exporting = False
        self._ignore_list_select = False

        # timeline zoom/pan
        self.tl_zoom = 1.0
        self.tl_view0 = 0.0
        self._pan_anchor_x = 0.0
        self._pan_anchor_view0 = 0.0

        self._scan_exported()
        self._build()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self._close)

        if not self.videos:
            messagebox.showwarning("Пусто", f"Нет видео в:\n{folder}")
        else:
            self._load(0)

    # ------------------------------------------------------------------ marks persist

    def _marks_path(self) -> Path:
        return self.folder / MARKS_FILE

    def _load_marks_file(self) -> None:
        p = self._marks_path()
        if not p.is_file():
            return
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            for k, v in (raw or {}).items():
                if isinstance(v, (list, tuple)) and len(v) == 2:
                    self.marks[k] = (float(v[0]), float(v[1]))
        except Exception:
            pass

    def _save_marks_file(self) -> None:
        try:
            data = {k: [round(a, 3), round(b, 3)] for k, (a, b) in self.marks.items()}
            self._marks_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _is_trimmed(self, a: float, b: float, duration: float) -> bool:
        return a > 0.02 or b < duration - 0.02

    def _save_current_marks(self) -> None:
        if not self.videos or self.duration <= 0:
            return
        name = self.videos[self.idx].name
        a, b = round(self.mark_in, 3), round(self.mark_out, 3)
        if self._is_trimmed(a, b, self.duration):
            self.marks[name] = (a, b)
            self._save_marks_file()
        elif name in self.marks:
            self.marks.pop(name, None)
            self._save_marks_file()

    def _restore_marks(self, name: str, duration: float) -> None:
        if name in self.marks:
            a, b = self.marks[name]
            self.mark_in = max(0.0, min(a, duration - MIN_LEN))
            self.mark_out = max(self.mark_in + MIN_LEN, min(b, duration))
        else:
            self.mark_in = 0.0
            self.mark_out = duration

    # ------------------------------------------------------------------ UI

    def _build(self) -> None:
        top = tk.Frame(self, bg=C_PANEL, height=48)
        top.pack(fill=tk.X)
        top.pack_propagate(False)

        tk.Button(
            top, text="Папка…", bg=C_TRACK, fg=C_TEXT, relief=tk.FLAT,
            command=self._pick_folder,
        ).pack(side=tk.LEFT, padx=(10, 6), pady=10)

        self.path_lbl = tk.Label(top, text=str(self.folder), bg=C_PANEL, fg=C_MUTED, anchor=tk.W)
        self.path_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.fast_copy = tk.BooleanVar(value=True)
        tk.Checkbutton(
            top, text="быстрый copy", variable=self.fast_copy,
            bg=C_PANEL, fg=C_MUTED, selectcolor=C_TRACK,
            activebackground=C_PANEL, highlightthickness=0,
        ).pack(side=tk.RIGHT, padx=(0, 10))

        body = tk.Frame(self, bg=C_BG)
        body.pack(fill=tk.BOTH, expand=True)

        side = tk.Frame(body, bg=C_PANEL, width=270)
        side.pack(side=tk.LEFT, fill=tk.Y)
        side.pack_propagate(False)
        tk.Label(side, text="Видео  (● = есть метка)", bg=C_PANEL, fg=C_MUTED).pack(
            anchor=tk.W, padx=10, pady=(8, 4),
        )
        self.listbox = tk.Listbox(
            side, bg="#121212", fg=C_TEXT, selectbackground=C_ACCENT,
            selectforeground="#000", activestyle="none",
            highlightthickness=0, borderwidth=0, font=("Consolas", 9),
            takefocus=False,  # предотвращает перехват Space
        )
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)
        self._refresh_list()

        main = tk.Frame(body, bg=C_BG)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.preview = tk.Canvas(main, bg="#000", highlightthickness=0)
        self.preview.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 4))
        self.preview.bind("<Configure>", lambda _e: self._paint_last())

        tr = tk.Frame(main, bg=C_BG)
        tr.pack(fill=tk.X, padx=10, pady=4)
        self.time_lbl = tk.Label(tr, text="00:00.00", bg=C_BG, fg=C_TEXT, font=("Consolas", 12))
        self.time_lbl.pack(side=tk.LEFT)
        tk.Button(tr, text="▶", width=3, bg=C_PANEL, fg=C_TEXT, relief=tk.FLAT, command=self._toggle).pack(
            side=tk.LEFT, padx=8,
        )
        self.sel_lbl = tk.Label(tr, text="", bg=C_BG, fg=C_MUTED, font=("Consolas", 11))
        self.sel_lbl.pack(side=tk.LEFT, padx=8)
        self.status_lbl = tk.Label(tr, text="", bg=C_BG, fg=C_ACCENT)
        self.status_lbl.pack(side=tk.RIGHT)

        marks = tk.Frame(main, bg=C_BG)
        marks.pack(fill=tk.X, padx=10, pady=4)
        for text, cmd, bg in (
            ("Сброс куска [R]", self._reset_marks, C_TRACK),
            ("Экспорт этот [E]", self._export_one, "#2a6a58"),
            ("ЭКСПОРТ ВСЕХ", self._export_all, C_ACCENT),
            ("← Prev [B]", self._prev, C_TRACK),
            ("Next [N] →", self._next, C_TRACK),
            ("Зум к куску", self._zoom_to_sel, C_TRACK),
        ):
            fg = "#000" if bg == C_ACCENT else C_TEXT
            tk.Button(marks, text=text, bg=bg, fg=fg, relief=tk.FLAT, font=("", 9, "bold"), command=cmd).pack(
                side=tk.LEFT, padx=(0, 6), pady=2, ipady=5, ipadx=8,
            )

        tl_hdr = tk.Frame(main, bg=C_BG)
        tl_hdr.pack(fill=tk.X, padx=10)
        tk.Label(tl_hdr, text="Тяни зелёные края куска  ·  клик/drag середины — playhead  ·  колесо — зум",
                 bg=C_BG, fg=C_MUTED, font=("", 8)).pack(side=tk.LEFT)
        self.zoom_lbl = tk.Label(tl_hdr, text="1.0×", bg=C_BG, fg=C_MUTED, width=6)
        self.zoom_lbl.pack(side=tk.RIGHT)

        self.tl = tk.Canvas(main, bg=C_BG, height=64, highlightthickness=0, cursor="sb_h_double_arrow")
        self.tl.pack(fill=tk.X, padx=10, pady=(2, 12))
        self.tl.bind("<Button-1>", self._tl_down)
        self.tl.bind("<B1-Motion>", self._tl_drag)
        self.tl.bind("<ButtonRelease-1>", self._tl_up)
        self.tl.bind("<MouseWheel>", self._tl_wheel)
        self.tl.bind("<Button-4>", lambda e: self._tl_wheel_dir(1))
        self.tl.bind("<Button-5>", lambda e: self._tl_wheel_dir(-1))

    def _bind_keys(self) -> None:
        self.bind("<space>", self._on_space)
        self.bind("<KeyPress-space>", self._on_space)
        self.bind("e", lambda e: self._export_one())
        self.bind("E", lambda e: self._export_one())
        self.bind("<Return>", lambda e: self._export_one())
        self.bind("<Control-e>", lambda e: self._export_all())
        self.bind("<Control-E>", lambda e: self._export_all())
        self.bind("n", lambda e: self._next())
        self.bind("N", lambda e: self._next())
        self.bind("b", lambda e: self._prev())
        self.bind("B", lambda e: self._prev())
        self.bind("r", lambda e: self._reset_marks())
        self.bind("R", lambda e: self._reset_marks())
        self.bind("<Left>", lambda e: self._nudge(-0.1))
        self.bind("<Right>", lambda e: self._nudge(0.1))
        self.bind("<Shift-Left>", lambda e: self._nudge(-1.0))
        self.bind("<Shift-Right>", lambda e: self._nudge(1.0))
        self.focus_set()

    def _on_space(self, _e=None):
        self._toggle()
        return "break"

    # ------------------------------------------------------------------ list

    def _has_custom_mark(self, name: str) -> bool:
        return name in self.marks

    def _scan_exported(self) -> None:
        self.exported.clear()
        if not self.out_dir.is_dir():
            return
        vids = self.videos or list_videos(self.folder)
        for p in self.out_dir.iterdir():
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                for v in vids:
                    if p.name.startswith(v.stem):
                        self.exported.add(v.name)

    def _refresh_list(self) -> None:
        self._ignore_list_select = True
        sel_idx = self.idx
        self.listbox.delete(0, tk.END)
        for i, p in enumerate(self.videos):
            done = "✓" if p.name in self.exported else " "
            marked = "●" if self._has_custom_mark(p.name) else " "
            self.listbox.insert(tk.END, f"{done}{marked} {i + 1:02d}  {p.name}")
            if p.name in self.exported:
                self.listbox.itemconfig(i, fg=C_DONE)
            elif self._has_custom_mark(p.name):
                self.listbox.itemconfig(i, fg=C_MARKED)
        if self.videos:
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(sel_idx)
            self.listbox.see(sel_idx)
        self._ignore_list_select = False

    def _on_list_select(self, _e=None) -> None:
        if self._ignore_list_select:
            return
        sel = self.listbox.curselection()
        if not sel:
            return
        i = int(sel[0])
        if i != self.idx:
            self._load(i)

    def _pick_folder(self) -> None:
        self._save_current_marks()
        d = filedialog.askdirectory(initialdir=str(self.folder))
        if not d:
            return
        self.folder = Path(d)
        self.out_dir = self.folder / CLIPS_DIRNAME
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.videos = list_videos(self.folder)
        self.marks = {}
        self._load_marks_file()
        self.path_lbl.config(text=str(self.folder))
        self._scan_exported()
        self._refresh_list()
        if self.videos:
            self._load(0)

    def _load(self, idx: int) -> None:
        if self.videos and self.cap is not None:
            self._save_current_marks()
        self._stop_play()
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if not self.videos:
            return
        self.idx = max(0, min(idx, len(self.videos) - 1))
        path = self.videos[self.idx]
        try:
            self.duration, self.fps, _w, _h = probe(path)
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return

        self._restore_marks(path.name, self.duration)
        self.tl_zoom = 1.0
        self.tl_view0 = 0.0

        self.cap = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
        if not self.cap.isOpened():
            messagebox.showerror("Ошибка", f"Не открывается: {path.name}")
            self.cap = None
            return

        self.pos = self.mark_in
        self._last_bgr = None
        self.title(f"Quick Trim — {path.name}  ({self.idx + 1}/{len(self.videos)})")
        self.status_lbl.config(text="")
        self._seek_and_show(self.mark_in)
        self._draw_tl()
        self._update_labels()
        self._refresh_list()
        self.focus_set()

    # ------------------------------------------------------------------ preview

    def _seek_and_show(self, t: float) -> None:
        if self.cap is None:
            return
        t = max(0.0, min(t, self.duration - 0.01))
        self.cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = self.cap.read()
        if ok and frame is not None:
            self.pos = float(self.cap.get(cv2.CAP_PROP_POS_MSEC) or 0) / 1000.0
            small = downscale_bgr(frame)
            self._last_bgr = small
            self._paint(small)
        self._update_labels()
        self._draw_tl()

    def _paint(self, bgr: np.ndarray) -> None:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        cw = max(self.preview.winfo_width(), 2)
        ch = max(self.preview.winfo_height(), 2)
        h, w = rgb.shape[:2]
        scale = min(cw / w, ch / h, 1.0)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        if (nw, nh) != (w, h):
            rgb = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR)
        self._photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.preview.delete("all")
        self.preview.create_image(cw // 2, ch // 2, image=self._photo)

    def _paint_last(self) -> None:
        if self._last_bgr is not None:
            self._paint(self._last_bgr)

    def _update_labels(self) -> None:
        self.time_lbl.config(text=f"{fmt(self.pos)}  /  {fmt(self.duration)}")
        length = max(0.0, self.mark_out - self.mark_in)
        self.sel_lbl.config(
            text=f"IN {fmt(self.mark_in)}   OUT {fmt(self.mark_out)}   |  len {length:.2f}s"
        )
        n_marked = len(self.marks)
        self.status_lbl.config(text=f"меток: {n_marked}/{len(self.videos)}")

    # ------------------------------------------------------------------ timeline zoom

    def _visible_span(self) -> float:
        return max(self.duration / max(self.tl_zoom, 1.0), 0.2)

    def _clamp_view(self) -> None:
        span = self._visible_span()
        self.tl_view0 = max(0.0, min(self.tl_view0, max(0.0, self.duration - span)))

    def _zoom_by(self, factor: float, center_t: float | None = None) -> None:
        if self.duration <= 0:
            return
        if center_t is None:
            center_t = self.pos
        old_span = self._visible_span()
        rel = 0.5 if old_span <= 0 else (center_t - self.tl_view0) / old_span
        self.tl_zoom = max(TL_ZOOM_MIN, min(TL_ZOOM_MAX, self.tl_zoom * factor))
        new_span = self._visible_span()
        self.tl_view0 = center_t - rel * new_span
        self._clamp_view()
        self.zoom_lbl.config(text=f"{self.tl_zoom:.1f}×")
        self._draw_tl()

    def _zoom_to_sel(self) -> None:
        if self.duration <= 0:
            return
        span = max(self.mark_out - self.mark_in, 0.5)
        pad = span * 0.35
        want = span + 2 * pad
        self.tl_zoom = max(TL_ZOOM_MIN, min(TL_ZOOM_MAX, self.duration / want))
        self.tl_view0 = self.mark_in - pad
        self._clamp_view()
        self.zoom_lbl.config(text=f"{self.tl_zoom:.1f}×")
        self._draw_tl()

    def _tl_wheel(self, e) -> None:
        center = self._x_to_t(e.x)
        self._zoom_by(1.25 if e.delta > 0 else 1 / 1.25, center)

    def _tl_wheel_dir(self, direction: int) -> None:
        self._zoom_by(1.25 if direction > 0 else 1 / 1.25)

    # ------------------------------------------------------------------ timeline draw / hit

    def _tl_geom(self) -> tuple[int, int, int, int]:
        w = max(self.tl.winfo_width(), 2)
        pad = 14
        return pad, 20, w - pad, 48

    def _t_to_x(self, t: float) -> float:
        x0, _, x1, _ = self._tl_geom()
        span = self._visible_span()
        if span <= 0:
            return x0
        return x0 + ((t - self.tl_view0) / span) * (x1 - x0)

    def _x_to_t(self, x: float) -> float:
        x0, _, x1, _ = self._tl_geom()
        span = self._visible_span()
        if x1 <= x0 or span <= 0:
            return 0.0
        t = self.tl_view0 + (x - x0) / (x1 - x0) * span
        return max(0.0, min(self.duration, t))

    def _draw_tl(self) -> None:
        self.tl.delete("all")
        x0, y0, x1, y1 = self._tl_geom()
        self.tl.create_rectangle(x0, y0, x1, y1, fill=C_TRACK, outline="")
        if self.duration <= 0:
            return

        xa = max(x0, min(x1, self._t_to_x(self.mark_in)))
        xb = max(x0, min(x1, self._t_to_x(self.mark_out)))
        if xb > xa:
            self.tl.create_rectangle(xa, y0, xb, y1, fill=C_RANGE, outline="")

        for hx in (xa, xb):
            self.tl.create_rectangle(
                hx - HANDLE_PX / 2, y0 - 2, hx + HANDLE_PX / 2, y1 + 2,
                fill=C_HANDLE, outline="#003d30", width=1,
            )
            cy = (y0 + y1) / 2
            self.tl.create_line(hx - 2, cy - 8, hx - 2, cy + 8, fill="#003d30")
            self.tl.create_line(hx + 2, cy - 8, hx + 2, cy + 8, fill="#003d30")

        xp = self._t_to_x(self.pos)
        if x0 <= xp <= x1:
            self.tl.create_line(xp, 4, xp, y1 + 10, fill=C_PLAY, width=2)
            self.tl.create_polygon(xp - 5, 4, xp + 5, 4, xp, 12, fill=C_PLAY, outline="")

        self.tl.create_text(x0, 8, text=fmt(self.tl_view0), fill=C_MUTED, anchor=tk.W, font=("", 8))
        self.tl.create_text(
            x1, 8, text=fmt(self.tl_view0 + self._visible_span()), fill=C_MUTED, anchor=tk.E, font=("", 8),
        )

    def _hit(self, x: float) -> str:
        xa = self._t_to_x(self.mark_in)
        xb = self._t_to_x(self.mark_out)
        if abs(x - xa) <= HIT_PX:
            return "in"
        if abs(x - xb) <= HIT_PX:
            return "out"
        return "playhead"

    def _tl_down(self, e) -> None:
        if e.state & 0x0001:
            self._drag_mode = "pan"
            self._pan_anchor_x = e.x
            self._pan_anchor_view0 = self.tl_view0
            return
        self._drag_mode = self._hit(e.x)
        self._tl_apply(e.x)

    def _tl_drag(self, e) -> None:
        if self._drag_mode == "pan":
            x0, _, x1, _ = self._tl_geom()
            span = self._visible_span()
            dx = e.x - self._pan_anchor_x
            dt = -dx / max(x1 - x0, 1) * span
            self.tl_view0 = self._pan_anchor_view0 + dt
            self._clamp_view()
            self._draw_tl()
            return
        self._tl_apply(e.x)

    def _tl_up(self, _e) -> None:
        if self._drag_mode in ("in", "out"):
            self._save_current_marks()
            self._refresh_list()
        self._drag_mode = None

    def _tl_apply(self, x: float) -> None:
        t = self._x_to_t(x)
        mode = self._drag_mode or "playhead"
        if mode == "in":
            self.mark_in = max(0.0, min(t, self.mark_out - MIN_LEN))
            self._stop_play()
            self._seek_and_show(self.mark_in)
        elif mode == "out":
            self.mark_out = min(self.duration, max(t, self.mark_in + MIN_LEN))
            self._stop_play()
            self._seek_and_show(self.mark_out)
        else:
            self._stop_play()
            self._seek_and_show(t)

    # ------------------------------------------------------------------ play (threaded sequential decode)

    def _toggle(self) -> None:
        if self.playing:
            self._stop_play()
        else:
            self._start_play()

    def _start_play(self) -> None:
        if self.cap is None:
            return
        # seek to mark_in if outside range
        if self.pos < self.mark_in or self.pos >= self.mark_out - 0.02:
            self.cap.set(cv2.CAP_PROP_POS_MSEC, self.mark_in * 1000.0)
            self.pos = self.mark_in
        self._frame_queue: list[tuple[float, np.ndarray]] = []
        self._decode_stop = False
        self._decode_thread = threading.Thread(target=self._decode_loop, daemon=True)
        self._decode_thread.start()
        self.playing = True
        self.focus_set()
        self._play_wall_start = time.perf_counter()
        self._play_pos_start = self.pos
        self._tick()

    def _decode_loop(self) -> None:
        """Background thread: read frames sequentially into queue."""
        while not self._decode_stop and self.cap is not None:
            if len(self._frame_queue) > 8:
                time.sleep(0.005)
                continue
            ok, frame = self.cap.read()
            if not ok:
                # loop
                self.cap.set(cv2.CAP_PROP_POS_MSEC, self.mark_in * 1000.0)
                continue
            pos = float(self.cap.get(cv2.CAP_PROP_POS_MSEC) or 0) / 1000.0
            if pos >= self.mark_out:
                self.cap.set(cv2.CAP_PROP_POS_MSEC, self.mark_in * 1000.0)
                continue
            small = downscale_bgr(frame)
            self._frame_queue.append((pos, small))

    def _stop_play(self) -> None:
        self.playing = False
        self._decode_stop = True
        if self._play_job is not None:
            try:
                self.after_cancel(self._play_job)
            except Exception:
                pass
            self._play_job = None

    def _tick(self) -> None:
        if not self.playing:
            return

        # grab latest frame from queue
        if self._frame_queue:
            pos, frame = self._frame_queue.pop(0)
            self.pos = pos
            self._last_bgr = frame
            self._paint(frame)
            self._update_labels()
            self._draw_tl()

        delay = max(1, int(1000 / min(self.fps, 30)))
        self._play_job = self.after(delay, self._tick)

    # ------------------------------------------------------------------ nav / marks

    def _reset_marks(self) -> None:
        self._stop_play()
        self.mark_in = 0.0
        self.mark_out = self.duration
        if self.videos:
            self.marks.pop(self.videos[self.idx].name, None)
            self._save_marks_file()
        self._refresh_list()
        self._draw_tl()
        self._update_labels()
        self.status_lbl.config(text="кусок = всё видео")

    def _nudge(self, dt: float) -> None:
        self._stop_play()
        self._seek_and_show(self.pos + dt)

    def _next(self) -> None:
        if self.idx + 1 < len(self.videos):
            self._load(self.idx + 1)

    def _prev(self) -> None:
        if self.idx > 0:
            self._load(self.idx - 1)

    # ------------------------------------------------------------------ export

    def _ffmpeg_cut(self, src: Path, start: float, end: float, out_path: Path) -> str | None:
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return "ffmpeg не найден в PATH"
        if self.fast_copy.get():
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                "-i", str(src),
                "-c", "copy", "-avoid_negative_ts", "make_zero",
                str(out_path),
            ]
        else:
            dur = end - start
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{dur:.3f}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(out_path),
            ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except Exception as e:
            return str(e)
        if r.returncode != 0 or not out_path.exists():
            return r.stderr[-800:] or "ошибка ffmpeg"
        return None

    def _export_one(self) -> None:
        if not self.videos or self.cap is None or self._exporting:
            return
        self._save_current_marks()
        src = self.videos[self.idx]
        start, end = self.mark_in, self.mark_out
        if end - start < MIN_LEN:
            messagebox.showinfo("Коротко", "Кусок слишком короткий — потяни края")
            return
        out_name = f"{src.stem}__{start:.2f}-{end:.2f}.mp4"
        out_path = self.out_dir / out_name
        self.status_lbl.config(text="экспорт…")
        self.update_idletasks()
        err = self._ffmpeg_cut(src, start, end, out_path)
        if err:
            messagebox.showerror("Экспорт", err)
            return
        self.exported.add(src.name)
        self._refresh_list()
        self.status_lbl.config(text=f"✓ {out_name}")

    def _export_all(self) -> None:
        if self._exporting:
            return
        self._save_current_marks()
        jobs: list[tuple[Path, float, float]] = []
        for p in self.videos:
            if p.name not in self.marks:
                continue
            a, b = self.marks[p.name]
            if b - a < MIN_LEN:
                continue
            jobs.append((p, a, b))

        if not jobs:
            messagebox.showinfo(
                "Нет меток",
                "Потяни края куска хотя бы на одном видео и перелистывай дальше.\n"
                "Метки сохраняются автоматически (● в списке).",
            )
            return

        if not messagebox.askyesno("Экспорт всех", f"Экспортировать {len(jobs)} клип(ов) в\n{self.out_dir}?"):
            return

        self._exporting = True
        self._stop_play()
        ok = 0
        fail: list[str] = []
        for i, (src, start, end) in enumerate(jobs):
            out_name = f"{src.stem}__{start:.2f}-{end:.2f}.mp4"
            out_path = self.out_dir / out_name
            self.status_lbl.config(text=f"экспорт {i + 1}/{len(jobs)}…")
            self.update_idletasks()
            err = self._ffmpeg_cut(src, start, end, out_path)
            if err:
                fail.append(f"{src.name}: {err[:120]}")
            else:
                ok += 1
                self.exported.add(src.name)

        self._exporting = False
        self._refresh_list()
        self.status_lbl.config(text=f"готово: {ok}/{len(jobs)}")
        if fail:
            messagebox.showwarning("Готово с ошибками", f"OK: {ok}\n\n" + "\n".join(fail[:8]))
        else:
            messagebox.showinfo("Готово", f"Экспортировано {ok} клип(ов)\n{self.out_dir}")

    def _close(self) -> None:
        self._save_current_marks()
        self._stop_play()
        if self.cap is not None:
            self.cap.release()
        self.destroy()


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    if not folder.is_dir():
        folder = DEFAULT_DIR
    # второй аргумент = папка экспорта; если режем уже clips/ — пишем в clips_fixed
    if len(sys.argv) > 2:
        out = Path(sys.argv[2])
    elif folder.name.lower() == "clips":
        out = folder.parent / "clips_fixed"
    else:
        out = folder / CLIPS_DIRNAME
    out.mkdir(parents=True, exist_ok=True)
    app = QuickTrim(folder)
    app.out_dir = out
    app.mainloop()


if __name__ == "__main__":
    main()
