"""Сборка видео на видеокарте (RTX 3070, наш ffmpeg) — общие куски для всех сборщиков и всех чатов.

Юзер 2026-11-13: «переведи на видюху… чтобы в любом чате когда работал видюха была», потом «фризит, лагает,
зелёное иногда выходит — найди причину».

!!! ГЛАВНОЕ (замер 13.11, diag_gpu_frames.py — каждый кадр против эталона на процессоре):
  кадры видео, распакованные cuvid и ОСТАВЛЕННЫЕ в памяти видеокарты (-hwaccel_output_format cuda), портятся, если
  дальше их держат фильтры (trim/fps/tpad/overlay-склейка): распаковщик переиспользует свою память, и в ролик идут
  чужие кадры — из 1924 кадров 1713 со сдвигом на 3–8 кадров (фризы, лаги) и 30 мусорных (зелёные).
  ТАК НЕЛЬЗЯ. Правильно и проверено (1924 из 1924 верных):

  1. распаковка — видеокарта, обрезка и масштаб — прямо в распаковщике, кадры в ОБЫЧНУЮ память:
       gpu_input(src, crop=(x, y, w, h), resize=(1080, 1920))  →  -c:v h264_cuvid -crop … -resize … -i src
     (без -hwaccel_output_format cuda; все числа чётные — нечётный сдвиг меняет местами цвета);
  2. время, склейка — обычные фильтры (trim/setpts/fps/tpad/concat/pad), они почти ничего не стоят;
  3. hwupload_cuda ОДИН раз — основа ролика уже собрана (размер точно 1080×1920, без выравнивания 1088);
  4. слои (подпись, осветление, карточки) — layer() + overlay_cuda на видеокарте;
  5. кодирование — NVENC (список NVENC ниже: без -pix_fmt и -colorspace, цвет помечается в потоке).

Ещё про наш ffmpeg:
  • scale_cuda=…:format=yuv420p при ТОМ ЖЕ размере даёт зелёный кадр (только вместе со сменой размера);
  • yuva420p накладывается только на yuv420p (не на nv12) — основу загружать после format=yuv420p;
  • выходные -pix_fmt / -colorspace / -color_primaries / -color_trc возвращают кадр на процессор и ломают граф;
  • -ss на входе с кадрами в памяти видеокарты ломает граф (для пути 1–5 не нужно: -ss перед -i работает);
  • rotate/hflip/eq/noise/vignette/colortemperature/fillborders — только процессор: на коротком куске или RGBA-слоем;
  • исходники без B-кадров (-bf 0) надёжнее; cut_segment() так и пишет;
  • картинки-слои: «-i png» + loop-фильтр (layer()), НЕ «-loop 1» (распаковывает PNG на каждом кадре);
  • готовый ролик — bad_frames(): пустые/чёрные кадры и одиночные повторы посреди движения → пересобрать;
  • одновременно — через core.gpu_slots.gpu_slot() (лимит видеопамяти).

Пример: build_skinive3_v3.render, build_skinive2_uniq.render_gpu. Проверка рецепта — diag_gpu_frames.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from core import hw as _hw

HW_MODE = _hw.install()          # без NVIDIA (ноутбук): команды ffmpeg ниже переводятся на Quick Sync/процессор

# цвет bt709 помечаем в самом потоке (h264_metadata): выходные «-colorspace/-color_primaries/-color_trc» вставляют
# перевод цвета на процессоре и ломают сборку на видеокарте (проверено 13.11)
NVENC = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
         "-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1"]
CLEAN = ["-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
         "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=",
         "-movflags", "+faststart"]


def _even(x: float) -> int:
    return int(round(x / 2)) * 2


def probe(path: Path) -> tuple[str, int, int]:
    """(кодек, ширина, высота) первой видеодорожки."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=codec_name,width,height", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip().split(",")
    return out[0], int(out[1]), int(out[2])


def gpu_input(path: Path, crop: tuple[int, int, int, int] | None = None, resize: tuple[int, int] | None = None,
              ss: float | None = None) -> list:
    """Вход: видеокарта распаковывает и сразу (в распаковщике) режет crop=(x, y, w, h) и масштабирует resize=(W, H);
    кадры идут в ОБЫЧНУЮ память (не держим их на видеокарте — см. «ГЛАВНОЕ» в описании модуля)."""
    codec, sw, sh = probe(path)
    dec = {"h264": "h264_cuvid", "hevc": "hevc_cuvid"}.get(codec)
    if dec is None:
        raise ValueError(f"{path.name}: кодек {codec} — нет распаковщика cuvid, сделай заготовку h264 (cut_segment)")
    args = ["-c:v", dec]
    if crop:
        x, y, w, h = (_even(v) for v in crop)
        args += ["-crop", f"{y}x{sh - y - h}x{x}x{sw - x - w}"]
    if resize:
        args += ["-resize", f"{_even(resize[0])}x{_even(resize[1])}"]
    if ss:
        args += ["-ss", f"{ss:.3f}"]
    return args + ["-i", str(path)]


def cut_segment(src: Path, t0: float, t1: float, dest: Path, fps: int = 30) -> Path:
    """Один раз: кусок исходника [t0, t1] → короткая h264-заготовка с частыми ключевыми кадрами (читается с нуля
    на видеокарте; 60 к/с → fps)."""
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-hwaccel", "cuda",
                        "-i", str(src), "-vf", f"fps={fps}", "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                        "-cq", "16", "-g", "15", "-bf", "0", "-an", "-map_metadata", "-1", str(dest)], check=True)
    return dest


def layer(idx: int, start_frame: int, n_frames: int, label: str, fps: int = 30) -> str:
    """RGBA-картинка (вход idx, «-i png» без -loop) → слой видеокарты на кадры [start, start+n)."""
    return (f"[{idx}:v]loop=loop={n_frames - 1}:size=1:start=0,settb=1/{fps},setpts=N+{start_frame},"
            f"format=yuva420p,hwupload_cuda[{label}]")


def canvas(idx: int, n_frames: int, label: str, fps: int = 30) -> str:
    """(Старый путь «всё на видеокарте» — не использовать для кадров видео, см. описание модуля.) Вход idx — чёрная картинка W×H («-i png»): один раз загрузить в видеокарту и размножить на n кадров.
    Это основа для seq_overlay — гарантирует точный размер ролика (без выравнивания 1088)."""
    return (f"[{idx}:v]format=yuv420p,hwupload_cuda,loop=loop={n_frames - 1}:size=1:start=0,settb=1/{fps},"
            f"setpts=N[{label}]")


def seq_overlay(base: str, pieces: list[tuple[str, int]], out: str, fps: int = 30) -> list[str]:
    """НЕ для распакованных кадров видео (их склеивать concat в обычной памяти) — только для загруженных картинок.
    Склейка на видеокарте: pieces = [(метка куска, кадр начала)], кусок уже 1080×1920 той же раскладки.
    Возвращает строки графа: каждый кусок сдвигается на свой старт и накладывается на основу."""
    fc, cur = [], base
    for j, (lab, start) in enumerate(pieces):
        nxt = out if j == len(pieces) - 1 else f"_sq{j}_{out}"
        fc.append(f"[{lab}]setpts=PTS-STARTPTS+{start}/{fps}/TB[_sh{j}_{out}]")
        fc.append(f"[{cur}][_sh{j}_{out}]overlay_cuda=0:0:eof_action=pass[{nxt}]")
        cur = nxt
    return fc


def selftest(tmp: Path) -> bool:
    """Быстрая проверка рецепта: распаковка cuvid с обрезкой/масштабом в память → склейка → hwupload → слой
    overlay_cuda → NVENC. True — ролик собрался и в нём нет пустых кадров/фризов."""
    tmp.mkdir(parents=True, exist_ok=True)
    src = tmp / "gpu_selftest_src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=3",
                    "-c:v", "h264_nvenc", "-g", "15", "-bf", "0", str(src)], check=True)
    lay = tmp / "gpu_selftest_layer.png"
    from PIL import Image
    im = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    im.paste((255, 0, 0, 120), (100, 200, 980, 400))
    im.save(lay)
    out = tmp / "gpu_selftest.mp4"
    fc = ("[0:v]trim=start=0.5:duration=1,setpts=PTS-STARTPTS,fps=30,setsar=1,format=yuv420p[a];"
          "[1:v]trim=start=1.5:duration=1,setpts=PTS-STARTPTS,fps=30,setsar=1,format=yuv420p[b];"
          "[a][b]concat=n=2:v=1:a=0,hwupload_cuda[base];" + layer(2, 0, 60, "l") + ";[base][l]overlay_cuda=0:0[v]")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *gpu_input(src, crop=(100, 60, 400, 600), resize=(1080, 1920)),
                        *gpu_input(src, resize=(1080, 1920)), "-i", str(lay), "-filter_complex", fc, "-map", "[v]",
                        "-frames:v", "60", *NVENC, str(out)], capture_output=True, text=True)
    return r.returncode == 0 and out.exists() and not bad_frames(out)


def bad_frames(path: Path) -> list[int]:
    """Проверка КАЖДОГО кадра готового ролика: пустой кадр видеокарты (весь зелёный, Y=U=V=0), чёрный, или точный
    повтор соседнего посреди движения («фриз»; пауза в кадре даёт 0.3–0.5, повтор — около 0). Пусто — ролик ок."""
    import os
    hw = ["-hwaccel", "cuda"] if os.environ.get("GF_HWDEC") else []   # распаковка видеодекодером (побитно та же)
    raw = subprocess.run(["ffmpeg", "-v", "error", *hw, "-i", str(path), "-vf", "scale=54:96", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    if not raw and hw:                                                # видеодекодер не создался — процессором
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "scale=54:96", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return bad_frames_arr(np.frombuffer(raw, np.uint8).reshape(-1, 96, 54, 3))


def bad_frames_arr(fr: np.ndarray) -> list[int]:
    """То же по уже распакованным кадрам RGB 54×96 (одна распаковка ролика на все проверки)."""
    fr = fr.astype(np.int16)
    m = fr.mean(axis=(1, 2))
    bad = [i for i, (r_, g_, b_) in enumerate(m) if (g_ > 50 and r_ < 12 and b_ < 12) or (r_ + g_ + b_) / 3 < 8]
    d = np.abs(np.diff(fr.mean(axis=3), axis=0)).mean(axis=(1, 2))
    # фриз = одиночный повтор ПОСРЕДИ движения (кадр до и после меняется заметно); неподвижный экран (стор,
    # результат) даёт длинные ряды повторов — это норма, не фриз
    rep = [i + 1 for i in range(1, len(d) - 1) if d[i] < 0.12 and d[i - 1] > 0.8 and d[i + 1] > 0.8]
    return bad + rep
