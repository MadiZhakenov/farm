#!/usr/bin/env python3
"""
Video Splitter — превью + зум-таймлайн + Split в папку.

Запуск: python video-splitter.py
"""

from __future__ import annotations

import json
import math
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "output" / "clips"

VIDEO_FILETYPES = [
    ("MP4", "*.mp4"),
    ("MOV", "*.mov"),
    ("AVI", "*.avi"),
    ("MKV", "*.mkv"),
    ("WebM", "*.webm"),
    ("M4V", "*.m4v"),
    ("All files", "*.*"),
]

C_BG = "#0f0f0f"
C_PANEL = "#1a1a1a"
C_TRACK = "#252525"
C_TRACK_FILL = "#3a3a3a"
C_TEXT = "#e8e8e8"
C_MUTED = "#888888"
C_ACCENT = "#00d4aa"
C_PLAYHEAD = "#ff4466"
C_CUT = "#ffffff"
C_TRIM = "#00d4aa"
C_LOOP = "#ffb020"
C_CLIP_COLORS = ("#2a4a3e", "#2e3a5a", "#4a3a2e", "#3a2e4a", "#2e4a4a")
TL_H = 56
TL_PAD = 10
TL_ZOOM_MIN = 1.0
TL_ZOOM_MAX = 80.0
TL_REBUILD_MIN_INTERVAL = 0.15
PREVIEW_MAX_PLAY_PX = 1280
DECODER_QUEUE_SIZE = 4
MIN_CLIP_DURATION = 0.05
TRIM_HANDLE_PX = 6

def find_clip_at_time(clips: list[list[float]], t: float) -> int | None:
    for i, seg in enumerate(clips):
        if seg[0] < t < seg[1]:
            return i
    return None


def can_split_clip(clips: list[list[float]], t: float) -> tuple[bool, str]:
    idx = find_clip_at_time(clips, t)
    if idx is None:
        return False, "Playhead на границе — сдвиньте внутрь клипа"
    lo, hi = clips[idx][0], clips[idx][1]
    if t - lo < MIN_CLIP_DURATION:
        return False, f"Слишком близко к началу клипа ({fmt_time(lo, 2)})"
    if hi - t < MIN_CLIP_DURATION:
        return False, f"Слишком близко к концу клипа ({fmt_time(hi, 2)})"
    return True, ""


def clamp_clip_start(start: float, end: float, t: float) -> float:
    return max(0.0, min(round(t, 3), end - MIN_CLIP_DURATION))


def clamp_clip_end(start: float, end: float, t: float, duration: float) -> float:
    return max(start + MIN_CLIP_DURATION, min(round(t, 3), duration))


def fmt_time(sec: float, decimals: int = 1) -> str:
    sec = max(0.0, sec)
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if decimals <= 0:
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    scale = 10 ** decimals
    frac = int(round((sec % 1) * scale)) % scale
    frac_s = f".{frac:0{decimals}d}"
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}{frac_s}"
    return f"{m:02d}:{s:02d}{frac_s}"


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def find_ffprobe() -> str | None:
    return shutil.which("ffprobe")


def parse_fps(rate: str) -> float:
    if not rate or rate in ("0/0", "N/A"):
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        den_f = float(den)
        return float(num) / den_f if den_f else 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def probe_video(path: Path) -> tuple[float, float, int, int] | None:
    ffprobe = find_ffprobe()
    if ffprobe is None:
        return None

    cmd = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0 or not result.stdout.strip():
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    stream = streams[0] if streams else {}

    duration = float(fmt.get("duration") or 0.0)
    if duration <= 0:
        return None

    fps = resolve_playback_fps(stream, duration)

    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    return duration, fps, width, height


def resolve_playback_fps(stream: dict, duration: float) -> float:
    avg = parse_fps(stream.get("avg_frame_rate") or "")
    r_fps = parse_fps(stream.get("r_frame_rate") or "")
    nb_frames = int(stream.get("nb_frames") or 0)
    from_count = nb_frames / duration if nb_frames > 0 and duration > 0 else 0.0

    # avg_frame_rate — лучший выбор для тайминга; r_frame_rate иногда = timebase (1000/1)
    if avg > 0.5:
        if avg > 240 and r_fps > 0.5:
            return r_fps
        return avg
    if from_count > 0.5:
        return from_count
    if r_fps > 0.5 and r_fps <= 240:
        return r_fps
    return 25.0


def refine_fps(probed_fps: float, cap: cv2.VideoCapture) -> float:
    cap_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if cap_fps <= 0.5:
        return probed_fps
    if probed_fps <= 0.5:
        return cap_fps
    # OpenCV иногда округляет 29.97 → 30; если близко — оставляем probed
    if abs(cap_fps - probed_fps) <= 1.5:
        return probed_fps
    return cap_fps


def probe_video_opencv(path: Path) -> tuple[float, float, int, int] | None:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = frames / fps if fps > 0 and frames > 0 else 0.0
    cap.release()

    if duration <= 0:
        return None
    return duration, fps, width, height


def nice_tick_interval(visible_sec: float) -> float:
    if visible_sec <= 0:
        return 1.0
    raw = visible_sec / 8.0
    exp = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    for m in (1, 2, 5, 10):
        step = m * exp
        if step >= raw:
            return step
    return exp * 10


def tick_label(t: float, visible: float) -> str:
    if visible < 3:
        return f"{t:.2f}s"
    if visible < 30:
        return fmt_time(t, 2)[:8]
    return fmt_time(t, 1)[:5]


@dataclass
class VideoInfo:
    path: Path
    duration: float
    fps: float
    width: int
    height: int

    @property
    def frame_duration(self) -> float:
        return 1.0 / self.fps if self.fps > 0 else 1.0 / 25.0


def clips_from_cuts(duration: float, cuts: list[float]) -> list[tuple[float, float]]:
    points = sorted({round(c, 3) for c in cuts if MIN_CLIP_DURATION < c < duration - MIN_CLIP_DURATION})
    bounds = [0.0] + points + [duration]
    clips: list[tuple[float, float]] = []
    for i in range(len(bounds) - 1):
        start, end = bounds[i], bounds[i + 1]
        if end - start >= MIN_CLIP_DURATION:
            clips.append((start, end))
    return clips


def build_ffmpeg_cmd(
    ffmpeg: str,
    video_path: Path,
    start: float,
    end: float,
    out_file: Path,
    accurate: bool,
) -> list[str]:
    if accurate:
        duration = end - start
        return [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-ss", f"{start:.3f}",
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(out_file),
        ]
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
        "-i", str(video_path),
        "-c", "copy", "-avoid_negative_ts", "make_zero",
        str(out_file),
    ]


FramePacket = tuple[str, np.ndarray | None, float]


class FrameDecoder:
    """Фоновое чтение кадров — декод не блокирует UI."""

    def __init__(self) -> None:
        self._cap: cv2.VideoCapture | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue[FramePacket] = queue.Queue(maxsize=DECODER_QUEUE_SIZE)
        self._seek_sec: float | None = None
        self._frame_idx = 0
        self.fps = 25.0

    def open(self, path: Path, fps: float, start_sec: float = 0.0) -> bool:
        self.close()
        cap = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
        if not cap.isOpened():
            return False
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except cv2.error:
            pass

        self._cap = cap
        self.fps = fps
        self._stop.clear()
        self._seek_sec = start_sec
        self._frame_idx = max(0, int(round(start_sec * fps)))
        self._drain_queue()
        self._thread = threading.Thread(target=self._loop, name="frame-decoder", daemon=True)
        self._thread.start()
        return True

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._drain_queue()

    def seek(self, sec: float) -> None:
        with self._lock:
            self._seek_sec = sec
            self._frame_idx = max(0, int(round(sec * self.fps)))
        self._drain_queue()

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                cap = self._cap
                if cap is None:
                    break
                if self._seek_sec is not None:
                    sec = self._seek_sec
                    self._seek_sec = None
                    idx = max(0, int(round(sec * self.fps)))
                    self._frame_idx = idx
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ok, frame = cap.read()
                if ok and frame is not None:
                    idx = self._frame_idx
                    self._frame_idx += 1
                else:
                    ok = False

            if not ok:
                try:
                    self._queue.put(("eof", None, 0.0), timeout=0.05)
                except queue.Full:
                    pass
                time.sleep(0.005)
                continue

            pos = idx / self.fps
            packet: FramePacket = ("frame", frame, pos)
            while not self._stop.is_set():
                try:
                    self._queue.put(packet, timeout=0.1)
                    break
                except queue.Full:
                    continue

    def pop_frame(self) -> FramePacket | None:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def wait_frame(self, timeout: float = 0.05) -> FramePacket | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None


class VideoSplitterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Video Splitter")
        self.geometry("1024x700")
        self.minsize(860, 560)
        self.configure(bg=C_BG)

        self.video: VideoInfo | None = None
        self.cap: cv2.VideoCapture | None = None
        self._decoder = FrameDecoder()
        self.position = 0.0
        self._clips: list[list[float]] = []
        self._edit_history: list[list[list[float]]] = []
        self._selected_clip: int | None = None
        self.playing = False
        self._play_job: str | None = None
        self._play_ui_counter = 0
        self._dragging = False
        self._trim_drag: tuple[str, int] | None = None
        self._panning = False
        self._pan_anchor_x = 0.0
        self._pan_anchor_start = 0.0
        self._tl_nav_updating = False
        self._ui_ready = False
        self._closing = False
        self._split_running = False
        self._worker_queue: queue.Queue = queue.Queue()
        self._last_tl_rebuild = 0.0

        self.tl_zoom = 1.0
        self.tl_view_start = 0.0

        self.preview_photo: ImageTk.PhotoImage | None = None
        self._preview_item: int | None = None
        self._preview_dims: tuple[int, int, int, int] | None = None
        self._preview_bgr: np.ndarray | None = None
        self._preview_rgb: np.ndarray | None = None
        self._playhead_line: int | None = None
        self._playhead_tri: int | None = None

        self._build_ui()
        self._ui_ready = True
        self._poll_worker_queue()
        self.bind_all("<KeyPress-space>", self._on_space_key)
        self.bind_all("s", self._on_cut_key)
        self.bind_all("S", self._on_cut_key)
        self.bind_all("<Control-z>", self._on_undo_key)
        self.bind_all("<Control-Z>", self._on_undo_key)
        self.bind_all("l", self._on_loop_key)
        self.bind_all("L", self._on_loop_key)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        toolbar = tk.Frame(self, bg=C_PANEL, height=52)
        toolbar.pack(fill=tk.X)
        toolbar.pack_propagate(False)

        tk.Button(
            toolbar, text="  Открыть  ", bg=C_TRACK, fg=C_TEXT,
            activebackground="#333", activeforeground=C_TEXT,
            relief=tk.FLAT, command=self._pick_video,
        ).pack(side=tk.LEFT, padx=(12, 8), pady=10)

        self.cut_btn = tk.Button(
            toolbar, text="  Разрезать здесь  ", bg="#2d4a3e", fg=C_TEXT,
            activebackground="#3d6a5e", font=("", 9, "bold"),
            relief=tk.FLAT, command=self._add_cut_here, state=tk.DISABLED,
        )
        self.cut_btn.pack(side=tk.LEFT, padx=(0, 6), pady=10)

        tk.Button(
            toolbar, text="Отменить", bg=C_TRACK, fg=C_MUTED,
            activebackground="#333", relief=tk.FLAT, command=self._undo_edit,
        ).pack(side=tk.LEFT, padx=(0, 16), pady=10)

        split_box = tk.Frame(toolbar, bg=C_PANEL)
        split_box.pack(side=tk.RIGHT, padx=(0, 4), pady=10)

        self.split_btn = tk.Button(
            split_box, text="  SPLIT  ", bg=C_ACCENT, fg="#000",
            activebackground="#00b894", font=("", 10, "bold"),
            relief=tk.FLAT, command=self._split, state=tk.DISABLED,
        )
        self.split_btn.pack(side=tk.RIGHT, padx=(8, 0))

        self.accurate_split = tk.BooleanVar(value=True)
        tk.Checkbutton(
            split_box, text="Точный split", variable=self.accurate_split,
            bg=C_PANEL, fg=C_MUTED, selectcolor=C_TRACK,
            activebackground=C_PANEL, activeforeground=C_TEXT,
            highlightthickness=0, anchor=tk.W,
        ).pack(side=tk.RIGHT)

        self.info_label = tk.Label(
            toolbar, text="Нет видео", bg=C_PANEL, fg=C_MUTED, anchor=tk.W,
        )
        self.info_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        preview_wrap = tk.Frame(self, bg=C_BG)
        preview_wrap.pack(fill=tk.BOTH, expand=True, padx=12, pady=(10, 0))

        self.preview = tk.Canvas(preview_wrap, bg="#000", highlightthickness=0, height=380)
        self.preview.pack(fill=tk.BOTH, expand=True)
        self.preview.create_text(
            480, 190, text="Откройте видео", fill=C_MUTED, font=("", 14), tags="placeholder",
        )
        self.preview.bind("<Configure>", self._on_preview_resize)

        transport = tk.Frame(self, bg=C_BG)
        transport.pack(fill=tk.X, padx=12, pady=6)

        self.time_label = tk.Label(
            transport, text="00:00.0 / 00:00.0", bg=C_BG, fg=C_TEXT, font=("Consolas", 11),
        )
        self.time_label.pack(side=tk.LEFT)

        self.play_btn = tk.Button(
            transport, text="▶", width=3, bg=C_PANEL, fg=C_TEXT,
            activebackground=C_TRACK, relief=tk.FLAT,
            command=self._toggle_play, state=tk.DISABLED,
        )
        self.play_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._loop_clip = tk.BooleanVar(value=False)
        self.loop_btn = tk.Checkbutton(
            transport, text="↻ Loop", variable=self._loop_clip,
            bg=C_BG, fg=C_MUTED, selectcolor=C_TRACK,
            activebackground=C_BG, activeforeground=C_LOOP,
            highlightthickness=0, state=tk.DISABLED,
            command=self._on_loop_toggle,
        )
        self.loop_btn.pack(side=tk.LEFT, padx=(0, 12))

        self.clips_label = tk.Label(transport, text="", bg=C_BG, fg=C_MUTED)
        self.clips_label.pack(side=tk.RIGHT)

        tl_wrap = tk.Frame(self, bg=C_BG)
        tl_wrap.pack(fill=tk.X, padx=12, pady=(0, 6))

        tl_header = tk.Frame(tl_wrap, bg=C_BG)
        tl_header.pack(fill=tk.X)
        tk.Label(tl_header, text="Таймлайн", bg=C_BG, fg=C_MUTED).pack(side=tk.LEFT)

        zoom_box = tk.Frame(tl_header, bg=C_BG)
        zoom_box.pack(side=tk.RIGHT)
        tk.Button(
            zoom_box, text="−", width=2, bg=C_PANEL, fg=C_TEXT,
            relief=tk.FLAT, command=lambda: self._zoom_by(1 / 1.35),
        ).pack(side=tk.LEFT, padx=2)
        self.zoom_label = tk.Label(zoom_box, text="1.0×", bg=C_BG, fg=C_MUTED, width=6)
        self.zoom_label.pack(side=tk.LEFT)
        tk.Button(
            zoom_box, text="+", width=2, bg=C_PANEL, fg=C_TEXT,
            relief=tk.FLAT, command=lambda: self._zoom_by(1.35),
        ).pack(side=tk.LEFT, padx=2)
        tk.Button(
            zoom_box, text="Сброс", bg=C_PANEL, fg=C_MUTED,
            relief=tk.FLAT, command=self._zoom_reset,
        ).pack(side=tk.LEFT, padx=(6, 0))

        tk.Label(
            tl_wrap,
            text="Клик — playhead  ·  drag края клипа — in/out отдельно  ·  S — разрез  ·  L — loop",
            bg=C_BG, fg="#555", anchor=tk.W,
        ).pack(fill=tk.X, pady=(2, 0))

        self.timeline = tk.Canvas(
            tl_wrap, bg=C_TRACK, height=TL_H + 24,
            highlightthickness=1, highlightbackground="#333", cursor="crosshair",
        )
        self.timeline.pack(fill=tk.X, pady=(4, 0))
        self.timeline.bind("<Button-1>", self._on_tl_down)
        self.timeline.bind("<B1-Motion>", self._on_tl_drag)
        self.timeline.bind("<ButtonRelease-1>", self._on_tl_up)
        self.timeline.bind("<Motion>", self._on_tl_motion)
        self.timeline.bind("<Leave>", self._on_tl_leave)
        self.timeline.bind("<Button-2>", self._on_tl_pan_start)
        self.timeline.bind("<B2-Motion>", self._on_tl_pan_move)
        self.timeline.bind("<ButtonRelease-2>", self._on_tl_pan_end)
        self.timeline.bind("<MouseWheel>", self._on_tl_wheel)
        self.timeline.bind("<Shift-MouseWheel>", self._on_tl_wheel_shift)
        self.timeline.bind("<Button-4>", lambda e: self._on_tl_wheel_linux(1))
        self.timeline.bind("<Button-5>", lambda e: self._on_tl_wheel_linux(-1))
        self.timeline.bind("<Shift-Button-4>", lambda e: self._on_tl_scroll_shift(1))
        self.timeline.bind("<Shift-Button-5>", lambda e: self._on_tl_scroll_shift(-1))
        self.timeline.bind("<Configure>", lambda e: self._rebuild_timeline())

        self.tl_nav = tk.Scale(
            tl_wrap, from_=0.0, to=1.0, orient=tk.HORIZONTAL, resolution=0.01,
            showvalue=False, bg=C_BG, troughcolor=C_TRACK, highlightthickness=0,
            activebackground=C_ACCENT, sliderrelief=tk.FLAT, length=200,
            command=self._on_tl_nav_change,
        )

        bottom = tk.Frame(self, bg=C_BG)
        bottom.pack(fill=tk.X, padx=12, pady=(0, 10))

        self.progress = tk.Canvas(bottom, bg=C_TRACK, height=4, highlightthickness=0)
        self.progress.pack(fill=tk.X, pady=(0, 6))
        self.progress.bind("<Configure>", self._draw_progress_bar)

        self.status_label = tk.Label(
            bottom, text="Отметьте разрезы → SPLIT экспортирует клипы в папку",
            bg=C_BG, fg=C_MUTED, anchor=tk.W,
        )
        self.status_label.pack(fill=tk.X)

    # ------------------------------------------------------------------ Worker queue

    def _poll_worker_queue(self) -> None:
        if self._closing:
            return
        try:
            while True:
                msg = self._worker_queue.get_nowait()
                self._handle_worker_msg(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_worker_queue)

    def _handle_worker_msg(self, msg: tuple) -> None:
        if self._closing:
            return
        kind = msg[0]
        if kind == "progress":
            self._set_progress(msg[1])
        elif kind == "status":
            self._set_status(msg[1])
        elif kind == "done":
            ok, total, out_dir, errors, accurate = msg[1], msg[2], msg[3], msg[4], msg[5]
            self._split_running = False
            self._set_progress(0)
            self._update_split_btn_state()
            self._show_split_result(ok, total, out_dir, errors, accurate)
        elif kind == "error":
            self._split_running = False
            self._set_progress(0)
            self._update_split_btn_state()
            messagebox.showerror("Split", msg[1])

    def _show_split_result(
        self,
        ok: int,
        total: int,
        out_dir: Path,
        errors: list[str],
        accurate: bool,
    ) -> None:
        mode = "точный" if accurate else "быстрый (copy)"
        if ok == total:
            self._set_status(f"Готово: {ok}/{total} клипов ({mode})")
            messagebox.showinfo("Split", f"Готово: {ok} клипов ({mode})\n\n{out_dir}")
            return

        self._set_status(f"Готово частично: {ok}/{total} клипов")
        err_text = "\n".join(errors[:8])
        if len(errors) > 8:
            err_text += f"\n... и ещё {len(errors) - 8}"
        messagebox.showwarning(
            "Split",
            f"Экспортировано {ok} из {total} клипов ({mode}).\n\n"
            f"Папка:\n{out_dir}\n\nОшибки:\n{err_text}",
        )

    # ------------------------------------------------------------------ Video

    def _pick_video(self) -> None:
        path = filedialog.askopenfilename(
            title="Выберите видео",
            filetypes=VIDEO_FILETYPES,
            initialdir=str(SCRIPT_DIR),
        )
        if path:
            self._load_video(Path(path))

    def _load_video(self, path: Path) -> None:
        self._stop_play()
        self._decoder.close()

        if self.cap is not None:
            self.cap.release()
            self.cap = None

        probed = probe_video(path) or probe_video_opencv(path)
        if probed is None:
            messagebox.showerror("Ошибка", f"Не удалось определить параметры:\n{path}")
            return

        duration, fps, width, height = probed

        cap = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
        if not cap.isOpened():
            messagebox.showerror("Ошибка", f"Не удалось открыть:\n{path}")
            return
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except cv2.error:
            pass

        fps = refine_fps(fps, cap)
        self.cap = cap
        self.video = VideoInfo(path=path, duration=duration, fps=fps, width=width, height=height)
        self.position = 0.0
        self._clips = [[0.0, duration]]
        self._edit_history = []
        self._loop_clip.set(False)
        self._selected_clip = None
        self.tl_zoom = 1.0
        self.tl_view_start = 0.0
        self._preview_item = None
        self._preview_dims = None
        self._preview_bgr = None
        self._preview_rgb = None

        size_mb = path.stat().st_size / (1024 * 1024)
        fps_label = f"{fps:.3f}".rstrip("0").rstrip(".")
        self.info_label.config(
            text=f"{path.name}  ·  {width}×{height}  ·  {fps_label} fps  ·  {size_mb:.0f} MB",
        )
        self.play_btn.config(state=tk.NORMAL)
        self.cut_btn.config(state=tk.NORMAL)
        self.loop_btn.config(state=tk.NORMAL)
        self._update_cuts_label()
        self._update_split_btn_state()
        self._update_zoom_label()
        self.preview.delete("placeholder")
        self._show_frame_at(0.0)
        self._rebuild_timeline()
        self._update_tl_nav()
        self._set_status("Shift+drag или ползунок — прокрутка при зуме  ·  S — разрез")

    def _seek_capture(self, sec: float) -> tuple[bool, np.ndarray | None]:
        if self.cap is None or self.video is None:
            return False, None

        sec = max(0.0, min(sec, self.video.duration))
        frame_idx = max(0, int(round(sec * self.video.fps)))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = self.cap.read()
        if ok and frame is not None:
            pos_msec = self.cap.get(cv2.CAP_PROP_POS_MSEC)
            if pos_msec > 0:
                self.position = pos_msec / 1000.0
            else:
                self.position = frame_idx / self.video.fps
            return True, frame

        self.cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000.0)
        ok, frame = self.cap.read()
        if ok and frame is not None:
            pos_msec = self.cap.get(cv2.CAP_PROP_POS_MSEC)
            self.position = pos_msec / 1000.0 if pos_msec > 0 else sec
            return True, frame
        return False, None

    def _on_preview_resize(self, _event=None) -> None:
        self._preview_dims = None

    def _preview_target_size(self, fw: int, fh: int, *, fast: bool) -> tuple[int, int, int, int]:
        cw = max(self.preview.winfo_width(), 400)
        ch = max(self.preview.winfo_height(), 200)
        scale = min(cw / fw, ch / fh)
        nw = max(1, int(fw * scale))
        nh = max(1, int(fh * scale))
        if fast and max(nw, nh) > PREVIEW_MAX_PLAY_PX:
            downscale = PREVIEW_MAX_PLAY_PX / max(nw, nh)
            nw = max(1, int(nw * downscale))
            nh = max(1, int(nh * downscale))
        return cw, ch, nw, nh

    def _ensure_preview_buffers(self, nw: int, nh: int) -> None:
        if (
            self._preview_bgr is not None
            and self._preview_rgb is not None
            and self._preview_bgr.shape[0] == nh
            and self._preview_bgr.shape[1] == nw
        ):
            return
        self._preview_bgr = np.empty((nh, nw, 3), dtype=np.uint8)
        self._preview_rgb = np.empty((nh, nw, 3), dtype=np.uint8)

    def _show_frame_at(self, sec: float) -> None:
        if self.cap is None or self.video is None:
            return

        sec = max(0.0, min(sec, self.video.duration))
        ok, frame = self._seek_capture(sec)
        if not ok or frame is None:
            return

        self._render_preview(frame, fast=False)
        self.time_label.config(text=self._format_time_label())
        self._update_playhead()

    def _render_preview(self, frame: np.ndarray, *, fast: bool) -> None:
        fh, fw = frame.shape[:2]
        cw, ch, nw, nh = self._preview_target_size(fw, fh, fast=fast)
        dims = (cw, ch, nw, nh)

        if self._preview_dims != dims:
            self._preview_dims = dims
            self._ensure_preview_buffers(nw, nh)

        assert self._preview_bgr is not None and self._preview_rgb is not None
        interp = cv2.INTER_LINEAR if fast else cv2.INTER_AREA
        cv2.resize(frame, (nw, nh), dst=self._preview_bgr, interpolation=interp)
        cv2.cvtColor(self._preview_bgr, cv2.COLOR_BGR2RGB, dst=self._preview_rgb)

        self.preview_photo = ImageTk.PhotoImage(Image.fromarray(self._preview_rgb))

        if self._preview_item is None:
            self._preview_item = self.preview.create_image(
                cw // 2, ch // 2, image=self.preview_photo, tags="frame",
            )
        else:
            self.preview.itemconfig(self._preview_item, image=self.preview_photo)
            if not fast:
                self.preview.coords(self._preview_item, cw // 2, ch // 2)

    # ------------------------------------------------------------------ Keyboard

    def _on_space_key(self, event) -> str | None:
        if self._is_text_input(event.widget):
            return None
        self._toggle_play()
        return "break"

    def _on_cut_key(self, event) -> str | None:
        if self._is_text_input(event.widget):
            return None
        self._add_cut_here()
        return "break"

    @staticmethod
    def _is_text_input(widget) -> bool:
        return widget.winfo_class() in ("Entry", "TEntry", "Text")

    def _clip_index_at_time(self, t: float) -> int | None:
        for i, (s, e) in enumerate(self._get_clips()):
            if s <= t <= e:
                return i
        return None

    def _loop_target(self) -> tuple[float, float, int] | None:
        if not self._loop_clip.get() or self.video is None:
            return None
        clips = self._get_clips()
        if not clips:
            return None
        if self._selected_clip is not None and 0 <= self._selected_clip < len(clips):
            s, e = clips[self._selected_clip]
            return s, e, self._selected_clip
        idx = self._clip_index_at_time(self.position)
        if idx is not None and idx < len(clips):
            s, e = clips[idx]
            return s, e, idx
        return None

    def _on_loop_toggle(self) -> None:
        if not self._loop_clip.get():
            self._rebuild_timeline()
            self._set_status("Loop выключен")
            return
        target = self._loop_target()
        if target is None:
            idx = self._clip_index_at_time(self.position)
            if idx is not None:
                self._selected_clip = idx
                target = self._loop_target()
        if target is None:
            self._loop_clip.set(False)
            self._set_status("Loop: кликни клип или поставь playhead внутрь")
            return
        start, end, clip_i = target
        self._selected_clip = clip_i
        self._rebuild_timeline()
        self._set_status(f"Loop клипа #{clip_i + 1}: {fmt_time(start, 2)} – {fmt_time(end, 2)}")

    def _on_loop_key(self, event) -> str | None:
        if self._is_text_input(event.widget):
            return None
        self._loop_clip.set(not self._loop_clip.get())
        self._on_loop_toggle()
        return "break"

    def _sync_playback_clock(self, pos: float) -> None:
        self._play_wall_t0 = time.perf_counter()
        self._play_pos_t0 = pos
        self._play_frame_n = 0

    def _seek_playback(self, sec: float) -> None:
        if self.video is None:
            return
        sec = max(0.0, min(sec, self.video.duration))
        self._decoder.close()
        self._decoder.open(self.video.path, self.video.fps, sec)
        self.position = sec
        self._sync_playback_clock(sec)

    def _format_time_label(self) -> str:
        if self.video is None:
            return "00:00.0 / 00:00.0"
        loop = self._loop_target()
        if loop and self._loop_clip.get():
            ls, le, ci = loop
            rel = max(0.0, self.position - ls)
            dur = le - ls
            return f"{fmt_time(rel)} / {fmt_time(dur)}  ·  ↻#{ci + 1}"
        return f"{fmt_time(self.position)} / {fmt_time(self.video.duration)}"

    # ------------------------------------------------------------------ Playback

    def _toggle_play(self) -> None:
        if self.video is None:
            return
        if self.playing:
            self._stop_play()
        else:
            self._start_play()

    def _start_play(self) -> None:
        if self.video is None or self.cap is None:
            return

        loop = self._loop_target()
        if loop:
            loop_start, loop_end, clip_i = loop
            self._selected_clip = clip_i
            if self.position < loop_start or self.position >= loop_end - 0.02:
                self.position = loop_start
        elif self.position >= self.video.duration - 0.05:
            self.position = 0.0

        if not self._decoder.open(self.video.path, self.video.fps, self.position):
            messagebox.showerror("Ошибка", "Не удалось запустить воспроизведение.")
            return

        self.playing = True
        self._play_ui_counter = 0
        self._sync_playback_clock(self.position)
        self.play_btn.config(text="⏸")
        self._rebuild_timeline()
        self._play_tick()

    def _stop_play(self) -> None:
        was_playing = self.playing
        self.playing = False
        self.play_btn.config(text="▶")
        if self._play_job is not None:
            self.after_cancel(self._play_job)
            self._play_job = None
        if was_playing:
            self._decoder.close()
            if self.cap is not None and self.video is not None:
                self._seek_capture(self.position)

    def _take_playback_frame(self, target_pos: float) -> FramePacket | None:
        """Один кадр за тик; устаревшие (>2 кадра) отбрасываем."""
        if self.video is None:
            return None

        stale_limit = self.video.frame_duration * 2.0
        best: FramePacket | None = None

        while True:
            nxt = self._decoder.pop_frame()
            if nxt is None:
                break
            if nxt[0] == "eof":
                return nxt
            if nxt[2] < target_pos - stale_limit:
                continue
            if nxt[2] <= target_pos + self.video.frame_duration:
                best = nxt
            elif best is None:
                best = nxt
                break
            else:
                break

        if best is not None:
            return best
        return self._decoder.wait_frame(timeout=0.04)

    def _play_tick(self) -> None:
        if not self.playing or self.video is None:
            return

        now = time.perf_counter()
        target_pos = self._play_pos_t0 + (now - self._play_wall_t0)

        loop = self._loop_target()
        if loop:
            loop_start, loop_end, _clip_i = loop
            if target_pos >= loop_end - self.video.frame_duration * 0.5:
                self._seek_playback(loop_start)
                self._play_job = self.after(1, self._play_tick)
                return
            target_pos = min(target_pos, loop_end)
        elif target_pos >= self.video.duration - 0.05:
            self._stop_play()
            self._show_frame_at(0.0)
            return

        item = self._take_playback_frame(target_pos)

        if item is None:
            self._play_frame_n += 1
            next_at = self._play_wall_t0 + self._play_frame_n * self.video.frame_duration
            delay_ms = max(1, int((next_at - time.perf_counter()) * 1000))
            self._play_job = self.after(delay_ms, self._play_tick)
            return

        kind, frame, _pos = item
        if kind == "eof" or frame is None:
            if loop:
                self._seek_playback(loop[0])
                self._play_job = self.after(1, self._play_tick)
                return
            self._stop_play()
            self._show_frame_at(0.0)
            return

        self.position = min(target_pos, loop[1] if loop else self.video.duration)
        self._render_preview(frame, fast=True)

        self._play_ui_counter += 1
        if self._play_ui_counter % 2 == 0:
            self._update_playhead()
        if self._play_ui_counter % 5 == 0:
            self.time_label.config(text=self._format_time_label())
            self._ensure_playhead_visible()

        self._play_frame_n += 1
        next_at = self._play_wall_t0 + self._play_frame_n * self.video.frame_duration
        delay_ms = max(1, int((next_at - time.perf_counter()) * 1000))
        self._play_job = self.after(delay_ms, self._play_tick)

    # ------------------------------------------------------------------ Timeline

    def _visible_duration(self) -> float:
        if self.video is None:
            return 1.0
        return self.video.duration / self.tl_zoom

    def _max_view_start(self) -> float:
        if self.video is None:
            return 0.0
        return max(0.0, self.video.duration - self._visible_duration())

    def _set_view_start(self, start: float) -> None:
        self.tl_view_start = self._clamp_view_start(start)
        self._update_tl_nav()
        self._rebuild_timeline()

    def _update_tl_nav(self) -> None:
        if not self._ui_ready or self.video is None:
            return
        if self.tl_zoom <= 1.0:
            self.tl_nav.pack_forget()
            return
        max_start = self._max_view_start()
        if max_start <= 0.001:
            self.tl_nav.pack_forget()
            return
        if not self.tl_nav.winfo_ismapped():
            self.tl_nav.pack(fill=tk.X, pady=(2, 0))
        self._tl_nav_updating = True
        self.tl_nav.config(from_=0.0, to=max_start)
        self.tl_nav.set(min(max(0.0, self.tl_view_start), max_start))
        self._tl_nav_updating = False

    def _on_tl_nav_change(self, value: str) -> None:
        if self._tl_nav_updating or self.video is None:
            return
        self.tl_view_start = self._clamp_view_start(float(value))
        self._rebuild_timeline()

    def _scroll_timeline(self, direction: float) -> None:
        """direction: +1 = вправо по времени, -1 = влево (к 0 сек)."""
        if self.video is None or self.tl_zoom <= 1.0:
            return
        step = self._visible_duration() * 0.12 * direction
        self._set_view_start(self.tl_view_start + step)

    def _clamp_view_start(self, start: float) -> float:
        if self.video is None:
            return 0.0
        return max(0.0, min(start, self._max_view_start()))

    def _time_to_x(self, t: float, w: int) -> float:
        pad = TL_PAD
        inner = max(1, w - pad * 2)
        visible = self._visible_duration()
        if visible <= 0:
            return pad
        ratio = (t - self.tl_view_start) / visible
        return pad + ratio * inner

    def _x_to_time(self, x: float, w: int) -> float:
        if self.video is None:
            return 0.0
        pad = TL_PAD
        inner = max(1, w - pad * 2)
        visible = self._visible_duration()
        ratio = max(0.0, min(1.0, (x - pad) / inner))
        t = self.tl_view_start + ratio * visible
        return max(0.0, min(t, self.video.duration))

    def _seek_timeline(self, x: float) -> None:
        w = self.timeline.winfo_width()
        t = self._x_to_time(x, w)
        self._show_frame_at(t)

    def _get_clips(self) -> list[tuple[float, float]]:
        if not self._clips:
            return []
        out: list[tuple[float, float]] = []
        for seg in self._clips:
            if len(seg) < 2:
                continue
            s, e = round(seg[0], 3), round(seg[1], 3)
            if e - s >= MIN_CLIP_DURATION:
                out.append((s, e))
        return out

    def _is_trimmed_from_full(self) -> bool:
        if self.video is None or not self._clips:
            return False
        clips = self._get_clips()
        if len(clips) > 1:
            return True
        if len(clips) == 1:
            s, e = clips[0]
            return (
                s > MIN_CLIP_DURATION
                or e < self.video.duration - MIN_CLIP_DURATION
            )
        return False

    def _push_history(self) -> None:
        self._edit_history.append([seg[:] for seg in self._clips])
        if len(self._edit_history) > 50:
            self._edit_history.pop(0)

    def _undo_edit(self) -> None:
        if not self._edit_history:
            self._set_status("Нечего отменять")
            return
        self._stop_play()
        self._clips = self._edit_history.pop()
        self._selected_clip = None
        self._update_cuts_label()
        self._update_split_btn_state()
        self._rebuild_timeline()
        self._set_status(f"Отмена  ·  {len(self._get_clips())} клип(ов)")

    def _on_undo_key(self, event) -> str | None:
        if self._is_text_input(event.widget):
            return None
        self._undo_edit()
        return "break"

    def _hit_test_trim(self, x: float, w: int) -> tuple[str, int] | None:
        if self.video is None:
            return None
        best: tuple[str, int] | None = None
        best_dist = TRIM_HANDLE_PX + 1
        for i, (start, end) in enumerate(self._get_clips()):
            for side, t in (("left", start), ("right", end)):
                dist = abs(x - self._time_to_x(t, w))
                if dist <= TRIM_HANDLE_PX and dist < best_dist:
                    best = (side, i)
                    best_dist = dist
        return best

    def _clip_index_at_x(self, x: float, w: int) -> int | None:
        if self.video is None:
            return None
        for i, (start, end) in enumerate(self._get_clips()):
            x1 = self._time_to_x(start, w)
            x2 = self._time_to_x(end, w)
            if x1 + TRIM_HANDLE_PX <= x <= x2 - TRIM_HANDLE_PX:
                return i
        return None

    def _set_clip_edge(self, clip_i: int, side: str, t: float) -> None:
        if self.video is None or clip_i < 0 or clip_i >= len(self._clips):
            return
        s, e = self._clips[clip_i][0], self._clips[clip_i][1]
        if side == "left":
            new_t = clamp_clip_start(s, e, t)
            if abs(new_t - s) >= 1e-6:
                self._clips[clip_i][0] = new_t
        else:
            new_t = clamp_clip_end(s, e, t, self.video.duration)
            if abs(new_t - e) >= 1e-6:
                self._clips[clip_i][1] = new_t

    def _add_cut_at(self, t: float) -> bool:
        if self.video is None:
            return False
        self._stop_play()
        t = round(t, 3)
        ok, msg = can_split_clip(self._clips, t)
        if not ok:
            self._set_status(msg)
            return False
        idx = find_clip_at_time(self._clips, t)
        assert idx is not None
        s, e = self._clips[idx][0], self._clips[idx][1]
        self._push_history()
        self._clips[idx : idx + 1] = [[s, t], [t, e]]
        self._selected_clip = idx
        self._update_cuts_label()
        self._update_split_btn_state()
        self._rebuild_timeline()
        self._set_status(
            f"Разрез на {fmt_time(t, 2)}  →  {len(self._get_clips())} клипа",
        )
        return True

    def _apply_trim_drag(self, x: float) -> None:
        if self._trim_drag is None or self.video is None:
            return
        side, clip_i = self._trim_drag
        w = max(self.timeline.winfo_width(), 200)
        t = self._x_to_time(x, w)
        self._set_clip_edge(clip_i, side, t)
        self._rebuild_timeline()
        self._update_cuts_label()
        clips = self._get_clips()
        if 0 <= clip_i < len(clips):
            start, end = clips[clip_i]
            edge = "in" if side == "left" else "out"
            self._set_status(
                f"Клип {clip_i + 1} {edge}: {fmt_time(start, 2)} – {fmt_time(end, 2)}",
            )

    def _on_tl_motion(self, event) -> None:
        if self.video is None:
            return
        w = max(self.timeline.winfo_width(), 200)
        if (event.state & 0x1) and self.tl_zoom > 1.0:
            self.timeline.config(cursor="fleur")
        elif self._hit_test_trim(event.x, w) is not None:
            self.timeline.config(cursor="sb_h_double_arrow")
        elif self._clip_index_at_x(event.x, w) is not None:
            self.timeline.config(cursor="hand2")
        elif not self._trim_drag:
            self.timeline.config(cursor="crosshair")

    def _on_tl_leave(self, _event) -> None:
        if not self._trim_drag:
            self.timeline.config(cursor="crosshair")

    def _on_tl_down(self, event) -> None:
        if self.video is None:
            return
        w = max(self.timeline.winfo_width(), 200)

        if event.state & 0x1 and self.tl_zoom > 1.0:
            self._panning = True
            self._pan_anchor_x = event.x
            self._pan_anchor_start = self.tl_view_start
            self._dragging = False
            self._trim_drag = None
            self._stop_play()
            return

        if event.state & 0x4:
            self._trim_drag = None
            self._dragging = False
            t = self._x_to_time(event.x, w)
            if self._add_cut_at(t):
                self._show_frame_at(t)
            return

        hit = self._hit_test_trim(event.x, w)
        if hit is not None:
            self._push_history()
            self._trim_drag = hit
            self._dragging = False
            self._stop_play()
            self._apply_trim_drag(event.x)
            return

        self._trim_drag = None
        self._dragging = True
        self._stop_play()
        self._selected_clip = self._clip_index_at_x(event.x, w)
        self._seek_timeline(event.x)
        if self._loop_clip.get() and self._selected_clip is not None:
            clips = self._get_clips()
            if self._selected_clip < len(clips):
                s, e = clips[self._selected_clip]
                self._set_status(
                    f"Loop клипа #{self._selected_clip + 1}: {fmt_time(s, 2)} – {fmt_time(e, 2)}",
                )
            self._rebuild_timeline()

    def _on_tl_drag(self, event) -> None:
        if self._panning:
            self._on_tl_pan_move(event)
        elif self._trim_drag is not None:
            self._apply_trim_drag(event.x)
        elif self._dragging:
            self._seek_timeline(event.x)

    def _on_tl_up(self, _event) -> None:
        if self._panning:
            self._panning = False
        if self._trim_drag is not None:
            clips = self._get_clips()
            if clips:
                self._set_status(
                    f"{len(clips)} клип(ов)  ·  "
                    + "  ·  ".join(
                        f"#{i + 1} {fmt_time(s, 2)}–{fmt_time(e, 2)}"
                        for i, (s, e) in enumerate(clips)
                    ),
                )
        self._trim_drag = None
        self._dragging = False
        self._update_split_btn_state()

    def _on_tl_pan_start(self, event) -> None:
        if self.video is None or self.tl_zoom <= 1.0:
            return
        self._panning = True
        self._pan_anchor_x = event.x
        self._pan_anchor_start = self.tl_view_start
        self._dragging = False
        self._trim_drag = None

    def _on_tl_pan_move(self, event) -> None:
        if not self._panning or self.video is None:
            return
        w = max(self.timeline.winfo_width(), 200)
        inner = max(1, w - TL_PAD * 2)
        visible = self._visible_duration()
        dt = (self._pan_anchor_x - event.x) / inner * visible
        self._set_view_start(self._pan_anchor_start + dt)

    def _on_tl_pan_end(self, _event) -> None:
        self._panning = False

    def _on_tl_wheel(self, event) -> None:
        if self.video is None:
            return
        factor = 1.25 if event.delta > 0 else 1 / 1.25
        self._zoom_at(factor, anchor_x=event.x)

    def _on_tl_wheel_shift(self, event) -> None:
        if event.delta > 0:
            self._on_tl_scroll_shift(-1)
        else:
            self._on_tl_scroll_shift(1)

    def _on_tl_scroll_shift(self, direction: int) -> None:
        self._scroll_timeline(float(direction))

    def _on_tl_wheel_linux(self, direction: int) -> None:
        if self.video is None:
            return
        factor = 1.25 if direction > 0 else 1 / 1.25
        self._zoom_at(factor, anchor_x=self.timeline.winfo_width() // 2)

    def _zoom_by(self, factor: float) -> None:
        w = max(self.timeline.winfo_width(), 200)
        self._zoom_at(factor, anchor_x=w // 2)

    def _zoom_at(self, factor: float, anchor_x: float) -> None:
        if self.video is None:
            return

        w = max(self.timeline.winfo_width(), 200)
        anchor_time = self._x_to_time(anchor_x, w)
        new_zoom = max(TL_ZOOM_MIN, min(TL_ZOOM_MAX, self.tl_zoom * factor))

        if abs(new_zoom - self.tl_zoom) < 1e-6:
            return

        pad = TL_PAD
        inner = max(1, w - pad * 2)
        new_visible = self.video.duration / new_zoom
        ratio = max(0.0, min(1.0, (anchor_x - pad) / inner))
        self.tl_view_start = self._clamp_view_start(anchor_time - ratio * new_visible)
        self.tl_zoom = new_zoom

        if self.tl_zoom <= 1.0:
            self.tl_view_start = 0.0

        self._update_zoom_label()
        self._update_tl_nav()
        self._rebuild_timeline()

    def _zoom_reset(self) -> None:
        self.tl_zoom = 1.0
        self.tl_view_start = 0.0
        self._update_zoom_label()
        self._update_tl_nav()
        self._rebuild_timeline()

    def _update_zoom_label(self) -> None:
        self.zoom_label.config(text=f"{self.tl_zoom:.1f}×")

    def _schedule_timeline_rebuild(self) -> None:
        now = time.monotonic()
        if self.playing:
            if now - self._last_tl_rebuild < TL_REBUILD_MIN_INTERVAL:
                self._update_playhead()
                return
            self._last_tl_rebuild = now
        self._rebuild_timeline()

    def _ensure_playhead_visible(self) -> None:
        if self.video is None or self.tl_zoom <= 1.0:
            return
        visible = self._visible_duration()
        vs = self.tl_view_start
        ve = vs + visible
        margin = visible * 0.05
        if self.position < vs + margin:
            self.tl_view_start = self._clamp_view_start(self.position - margin)
            self._update_tl_nav()
            self._schedule_timeline_rebuild()
        elif self.position > ve - margin:
            self.tl_view_start = self._clamp_view_start(self.position - visible + margin)
            self._update_tl_nav()
            self._schedule_timeline_rebuild()

    def _seek_timeline(self, x: float) -> None:
        w = self.timeline.winfo_width()
        t = self._x_to_time(x, w)
        self._show_frame_at(t)

    def _rebuild_timeline(self) -> None:
        c = self.timeline
        c.delete("all")
        self._playhead_line = None
        self._playhead_tri = None

        w = max(c.winfo_width(), 200)
        h = TL_H + 24
        pad = TL_PAD
        y0 = 8
        bar_h = TL_H - 8

        c.create_rectangle(0, 0, w, h, fill=C_TRACK, outline="", tags="static")

        if self.video is None:
            c.create_text(w // 2, h // 2, text="Таймлайн", fill=C_MUTED, tags="static")
            return

        inner_w = w - pad * 2
        visible = self._visible_duration()
        view_end = min(self.video.duration, self.tl_view_start + visible)

        c.create_rectangle(pad, y0, pad + inner_w, y0 + bar_h, fill="#141414", outline="#333", tags="static")

        clips = self._get_clips()
        loop_target = self._loop_target()
        loop_idx = loop_target[2] if loop_target else None
        for i, (start, end) in enumerate(clips):
            x1 = self._time_to_x(start, w)
            x2 = self._time_to_x(end, w)
            if x2 <= pad or x1 >= pad + inner_w:
                continue
            x1c = max(pad, x1)
            x2c = min(pad + inner_w, x2)
            color = C_CLIP_COLORS[i % len(C_CLIP_COLORS)]
            if i == loop_idx and self._loop_clip.get():
                outline = C_LOOP
                width = 3
            elif i == self._selected_clip:
                outline = C_ACCENT
                width = 2
            else:
                outline = "#555"
                width = 1
            c.create_rectangle(
                x1c, y0 + 2, x2c, y0 + bar_h - 2,
                fill=color, outline=outline, width=width, tags="static",
            )
            mid_x = (x1c + x2c) / 2
            label = str(i + 1)
            if i == loop_idx and self._loop_clip.get():
                label = f"↻{i + 1}"
            if x2c - x1c > 28:
                c.create_text(
                    mid_x, y0 + bar_h / 2, text=label,
                    fill="#ffffff", font=("", 9, "bold"), tags="static",
                )
            for edge_t in (start, end):
                bx = self._time_to_x(edge_t, w)
                if bx < pad - TRIM_HANDLE_PX or bx > pad + inner_w + TRIM_HANDLE_PX:
                    continue
                c.create_line(
                    bx, y0 - 3, bx, y0 + bar_h + 3,
                    fill=C_TRIM, width=3, tags="static",
                )
                c.create_polygon(
                    bx - 5, y0 - 3, bx + 5, y0 - 3, bx, y0 - 11,
                    fill=C_TRIM, outline="", tags="static",
                )
                c.create_polygon(
                    bx - 5, y0 + bar_h + 3, bx + 5, y0 + bar_h + 3, bx, y0 + bar_h + 11,
                    fill=C_TRIM, outline="", tags="static",
                )

        step = nice_tick_interval(visible)
        t0 = math.ceil(self.tl_view_start / step) * step
        t = t0
        while t <= view_end + step * 0.01:
            x = self._time_to_x(t, w)
            if pad <= x <= pad + inner_w:
                c.create_line(x, y0 + bar_h, x, y0 + bar_h + 6, fill="#666", tags="static")
                c.create_text(
                    x, y0 + bar_h + 16, text=tick_label(t, visible),
                    fill=C_MUTED, font=("", 8), tags="static",
                )
            t += step

        self._update_playhead()

    def _update_playhead(self) -> None:
        if self.video is None:
            return

        c = self.timeline
        w = max(c.winfo_width(), 200)
        pad = TL_PAD
        y0 = 8
        bar_h = TL_H - 8
        ph = self._time_to_x(self.position, w)

        if ph < pad - 2 or ph > w - pad + 2:
            c.delete("playhead")
            self._playhead_line = None
            self._playhead_tri = None
            return

        if self._playhead_line is None or not c.find_withtag("playhead"):
            c.delete("playhead")
            self._playhead_line = c.create_line(
                ph, y0 - 4, ph, y0 + bar_h + 4,
                fill=C_PLAYHEAD, width=2, tags="playhead",
            )
            self._playhead_tri = c.create_polygon(
                ph - 6, y0 - 4, ph + 6, y0 - 4, ph, y0 - 12,
                fill=C_PLAYHEAD, outline="", tags="playhead",
            )
        else:
            c.coords(self._playhead_line, ph, y0 - 4, ph, y0 + bar_h + 4)
            c.coords(self._playhead_tri, ph - 6, y0 - 4, ph + 6, y0 - 4, ph, y0 - 12)

    def _add_cut_here(self) -> None:
        if self.video is None:
            return
        self._add_cut_at(self.position)

    def _undo_cut(self) -> None:
        self._undo_edit()

    def _update_cuts_label(self) -> None:
        if not self._ui_ready:
            return
        if self.video is None:
            self.clips_label.config(text="")
            return
        clips = self._get_clips()
        if not clips:
            self.clips_label.config(text="нет клипов")
        elif len(clips) == 1:
            self.clips_label.config(text="1 клип  ·  in/out независимо")
        else:
            self.clips_label.config(text=f"{len(clips)} клипа  ·  trim отдельно")

    def _update_split_btn_state(self) -> None:
        if not self._ui_ready:
            return
        if self._split_running:
            self.split_btn.config(state=tk.DISABLED)
            return
        if self.video is not None and self._get_clips() and self._is_trimmed_from_full():
            self.split_btn.config(state=tk.NORMAL)
        else:
            self.split_btn.config(state=tk.DISABLED)

    # ------------------------------------------------------------------ Split

    def _split(self) -> None:
        if self.video is None:
            messagebox.showwarning("Split", "Сначала откройте видео.")
            return
        if not self._get_clips() or not self._is_trimmed_from_full():
            messagebox.showwarning(
                "Split",
                "Сначала отметьте разрезы или подрежьте клип.\n\n"
                "S — разрез  ·  drag края клипа на таймлайне — trim.",
            )
            return
        if not find_ffmpeg():
            messagebox.showerror("ffmpeg", "ffmpeg не найден в PATH.")
            return

        accurate = self.accurate_split.get()
        if not accurate:
            if not messagebox.askyesno(
                "Быстрый split",
                "Быстрый режим (copy) режет только по ключевым кадрам — "
                "клипы могут не совпасть с разметкой.\n\n"
                "Продолжить?",
            ):
                return

        clips = self._get_clips()
        if not clips:
            return

        stem = re.sub(r'[<>:"/\\|?*]', "_", self.video.path.stem)
        out_dir = DEFAULT_OUTPUT / f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        out_dir.mkdir(parents=True, exist_ok=True)

        self._stop_play()
        self._split_running = True
        self.split_btn.config(state=tk.DISABLED)
        mode = "точный" if accurate else "быстрый"
        self._set_status(f"Split ({mode}): 0/{len(clips)}...")
        threading.Thread(
            target=self._split_worker,
            args=(clips, out_dir, accurate),
            daemon=True,
        ).start()

    def _split_worker(self, clips: list[tuple[float, float]], out_dir: Path, accurate: bool) -> None:
        assert self.video is not None
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            self._worker_queue.put(("error", "ffmpeg не найден в PATH."))
            return

        ext = ".mp4" if accurate else (self.video.path.suffix or ".mp4")
        total = len(clips)
        ok = 0
        errors: list[str] = []

        for i, (start, end) in enumerate(clips):
            if self._closing:
                return

            out_file = out_dir / f"clip_{i + 1:04d}{ext}"
            cmd = build_ffmpeg_cmd(ffmpeg, self.video.path, start, end, out_file, accurate)
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=600)
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append(f"clip_{i + 1:04d}: {exc}")
                self._worker_queue.put(("progress", (i + 1) / total))
                self._worker_queue.put(("status", f"Split: {i + 1}/{total}"))
                continue

            if result.returncode == 0 and out_file.is_file():
                ok += 1
            else:
                err = (result.stderr or result.stdout or "неизвестная ошибка").strip()
                err_line = err.splitlines()[-1] if err else "неизвестная ошибка"
                errors.append(f"clip_{i + 1:04d} ({fmt_time(start, 2)}–{fmt_time(end, 2)}): {err_line}")

            self._worker_queue.put(("progress", (i + 1) / total))
            self._worker_queue.put(("status", f"Split: {i + 1}/{total}"))

        if not self._closing:
            self._worker_queue.put(("done", ok, total, out_dir, errors, accurate))

    # ------------------------------------------------------------------ Helpers

    def _set_progress(self, ratio: float) -> None:
        self._progress_ratio = max(0.0, min(1.0, ratio))
        self._draw_progress_bar()

    def _draw_progress_bar(self, _event=None) -> None:
        c = self.progress
        c.delete("all")
        w = max(c.winfo_width(), 1)
        c.create_rectangle(0, 0, w, 4, fill=C_TRACK, outline="")
        ratio = getattr(self, "_progress_ratio", 0.0)
        if ratio > 0:
            c.create_rectangle(0, 0, w * ratio, 4, fill=C_ACCENT, outline="")

    def _set_status(self, text: str) -> None:
        self.status_label.config(text=text)

    def _on_close(self) -> None:
        self._closing = True
        self._stop_play()
        self._decoder.close()
        if self.cap is not None:
            self.cap.release()
        self.destroy()


def main() -> None:
    VideoSplitterApp().mainloop()


if __name__ == "__main__":
    main()
