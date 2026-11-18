#!/usr/bin/env python3
"""
1346 — чистые версии пяти роликов БЕЗ ТЕКСТА (для TikFusion: гипотезы №5 Allow Flip и №17 Flip only). После уникализации
тексты накладываем заново сами — в зеркальных копиях они так читаются нормально.
Стираем всё: их подписи в начале и их призывы (Comment HEELS / Comment DIY / Link in bio); нашу плашку не ставим.
Маска надписи: в окне, где она висит, — неподвижные пиксели (медиана кадров, малое отклонение), белые или цветные (эмодзи)
рядом с белым текстом, расширенные на обводку/тень; время появления/ухода — по контрасту букв с кольцом фона вокруг.
Закрашиваем cv2.inpaint только в кадрах, где надпись есть. Кадр 1080×1920, fps и звук исходника, NVENC (качество выше
обычного — TikFusion потом перекодирует).

  python make_1346_clean.py      # → output/1346_clean/<имя>.mp4 + captions.json (где и когда были надписи)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
SRC = ROOT / "downloads" / "1346" / "src"
OUT = ROOT / "output" / "1346_clean"
W, H = 1080, 1920
# надписи: рамка поиска (x0, y0, x1, y1) и примерное окно (с), где она висит (замер по кадрам)
CAPTIONS = {
    "Christmas Coloring Blanket with Markers": [("hook", (80, 240, 1000, 680), 0.0, 99.0)],    # + «Me: 🤩»
    "Glowing Halloween Fog Cauldrons": [("hook", (120, 480, 960, 720), 0.0, 1.3)],
    "GTA Money Stack Lamp": [("hook", (120, 240, 960, 520), 0.0, 10.6), ("cta", (290, 1730, 790, 1880), 12.8, 99.0)],
    "Light-Up Christmas Heel Boots": [("hook", (100, 80, 980, 380), 0.0, 9.9), ("cta", (100, 80, 980, 380), 10.1, 99.0)],
    "Water Jug Cabinet Dispenser": [("cta", (200, 1120, 880, 1520), 6.4, 99.0)],
}


def probe(p: Path) -> tuple[float, str]:
    out = subprocess.run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate:format=duration",
                          "-of", "default=nw=1", str(p)], capture_output=True, text=True).stdout
    vals = dict(line.split("=", 1) for line in out.split())
    return float(vals["duration"]), vals["r_frame_rate"]


def frames(src: Path):
    p = subprocess.Popen([FF, "-v", "error", "-i", str(src), "-vf", f"scale={W}:{H}:flags=lanczos", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    try:
        while True:
            buf = p.stdout.read(W * H * 3)
            if len(buf) < W * H * 3:
                break
            yield np.frombuffer(buf, np.uint8).reshape(H, W, 3)
    finally:
        p.kill()


def plan(crops: list[np.ndarray], fps: float, t0: float, t1: float) -> tuple[np.ndarray, int, int, dict]:
    """Маска надписи в рамке и первый/последний кадр, где она есть."""
    idx = [i for i in range(len(crops)) if t0 <= i / fps <= t1]
    sample = np.stack([crops[i] for i in idx[::max(1, len(idx) // 40)]]).astype(np.int16)
    tmpl = np.median(sample, axis=0)
    dev = np.median(np.abs(sample - tmpl).max(axis=3), axis=0)     # медиана: кадры до/после надписи не мешают
    static = dev < 16
    white = (tmpl.min(axis=2) > 200) & static
    near = cv2.dilate(white.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (71, 71))) > 0
    hsv = cv2.cvtColor(tmpl.astype(np.uint8), cv2.COLOR_RGB2HSV)
    # эмодзи: неподвижные цветные пиксели рядом с текстом (и серые, если фон тёмный — 🔗 на тёмном столе)
    emoji = static & near & (((hsv[..., 1] > 70) & (hsv[..., 2] > 60)) | (hsv[..., 2] > 90))
    core = (white | emoji).astype(np.uint8)
    core = cv2.morphologyEx(core, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    mask = cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
    wc = white.astype(np.uint8)
    ring = (cv2.dilate(wc, np.ones((19, 19), np.uint8)) > 0) & ~(cv2.dilate(wc, np.ones((7, 7), np.uint8)) > 0)
    wb = white
    share = []
    for c in crops:
        hit = c.min(axis=2) > 200
        share.append(float(hit[wb].mean() - hit[ring].mean()) if wb.any() else 0.0)
    on = [i for i in range(len(crops)) if share[i] > 0.25 and t0 - 0.5 <= i / fps <= t1 + 0.5]
    first, last = (min(on), max(on)) if on else (idx[0], idx[-1])
    ys, xs = np.nonzero(core)
    bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None
    return mask, max(0, first - 2), min(len(crops) - 1, last + 2), {"bbox_in_box": bbox}


def text_mask_at(j: int, full: list) -> np.ndarray:
    m = np.zeros((H, W), np.uint8)
    for mm, i0, i1 in full:
        if i0 <= j <= i1:
            m |= mm
    return m


_orb = cv2.ORB_create(1500)
_feat: dict = {}


def feats(j: int, frame: np.ndarray, excl: np.ndarray):
    """Точки ORB кадра (½ размера) вне рамок надписей — кэш на кадр."""
    if j not in _feat:
        g = cv2.cvtColor(cv2.resize(frame, (W // 2, H // 2)), cv2.COLOR_RGB2GRAY)
        _feat[j] = _orb.detectAndCompute(g, excl)
    return _feat[j]


def motion(i: int, j: int, buf: dict, excl: np.ndarray) -> np.ndarray | None:
    """Аффинное движение кадра j → кадр i (полный размер) по точкам вне надписей; None — не нашли."""
    ka, da = feats(i, buf[i], excl)
    kb, db = feats(j, buf[j], excl)
    if da is None or db is None or len(ka) < 30 or len(kb) < 30:
        return None
    mt = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(db, da)
    if len(mt) < 30:
        return None
    pb = np.float32([kb[m.queryIdx].pt for m in mt]) * 2
    pa = np.float32([ka[m.trainIdx].pt for m in mt]) * 2
    M, inl = cv2.estimateAffinePartial2D(pb, pa, method=cv2.RANSAC, ransacReprojThreshold=4.0)
    if M is None or inl is None or int(inl.sum()) < 25:
        return None
    return M


OFFSETS = (2, 4, 6, 9, 13, 18, 24, 30)


def fill(i: int, buf: dict, hole: np.ndarray, full: list, excl: np.ndarray) -> np.ndarray:
    """Дыру на месте надписи заполняем фоном из соседних кадров (подогнанных по движению камеры): берём ближайший
    кадр, где это место фона не закрыто надписью; что нигде не видно — дорисовываем (inpaint)."""
    img = buf[i].copy()
    left = hole.copy()
    for d in OFFSETS:
        for j in (i - d, i + d):
            if j not in buf or not left.any():
                continue
            M = motion(i, j, buf, excl)
            if M is None or np.abs(M[:, 2]).max() < 1.5:     # камера стоит — фон под надписью тот же
                continue
            warped = cv2.warpAffine(buf[j], M, (W, H), flags=cv2.INTER_LINEAR)
            ok = cv2.warpAffine(((text_mask_at(j, full) == 0) * 255).astype(np.uint8), M, (W, H), borderValue=0) > 250
            use = (left > 0) & ok
            img[use] = warped[use]
            left[use] = 0
        if not left.any():
            break
    if left.any():
        ys, xs = np.nonzero(left)
        y0, y1, x0, x1 = max(0, ys.min() - 12), min(H, ys.max() + 13), max(0, xs.min() - 12), min(W, xs.max() + 13)
        img[y0:y1, x0:x1] = cv2.inpaint(np.ascontiguousarray(img[y0:y1, x0:x1]), left[y0:y1, x0:x1], 7, cv2.INPAINT_TELEA)
    return img


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    report = {}
    for src in sorted(SRC.glob("*.mp4")):
        dur, fps_s = probe(src)
        num, den = (int(v) for v in fps_s.split("/"))
        fps = num / den
        caps = CAPTIONS[src.stem]
        crops = {k: [] for k in range(len(caps))}
        for f in frames(src):
            for k, (_n, (x0, y0, x1, y1), _a, _b) in enumerate(caps):
                crops[k].append(f[y0:y1, x0:x1].copy())
        plans = []
        for k, (name, box, a, b) in enumerate(caps):
            mask, i0, i1, info = plan(crops[k], fps, a, b)
            plans.append((box, mask, i0, i1))
            bb = info["bbox_in_box"]
            report.setdefault(src.stem, []).append({
                "kind": name, "from": round(i0 / fps, 2), "to": round(i1 / fps, 2),
                "bbox": [bb[0] + box[0], bb[1] + box[1], bb[2] + box[0], bb[3] + box[1]] if bb else None})
        del crops
        dest = OUT / f"{src.stem}.mp4"
        enc = subprocess.Popen([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", fps_s,
                                "-i", "-", "-i", str(src), "-map", "0:v", "-map", "1:a?", "-vf", f"format=yuv420p,{SET_SDR}",
                                "-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "19", "-b:v", "0",
                                "-maxrate", "14M", "-bufsize", "28M", "-profile:v", "high", *SDR_COLOR_ARGS,
                                "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(dest)], stdin=subprocess.PIPE)
        full = []                                         # полные маски надписей по кадрам (экранные координаты)
        for (x0, y0, x1, y1), mask, i0, i1 in plans:
            m = np.zeros((H, W), np.uint8)
            m[y0:y1, x0:x1] = mask
            full.append((m, i0, i1))
        K = OFFSETS[-1]                                   # соседи ±30 кадров
        _feat.clear()
        excl = np.full((H // 2, W // 2), 255, np.uint8)      # точки ищем вне рамок надписей
        for _n, (x0, y0, x1, y1), _a, _b in caps:
            excl[y0 // 2:y1 // 2, x0 // 2:x1 // 2] = 0
        buf: dict[int, np.ndarray] = {}
        it = frames(src)
        n_total = int(round(dur * fps)) + 5
        nxt = 0
        for i in range(n_total):
            while nxt <= i + K:
                f = next(it, None)
                if f is None:
                    break
                buf[nxt] = f.copy()
                nxt += 1
            if i not in buf:
                break
            img = buf[i].copy()
            hole = np.zeros((H, W), np.uint8)
            for m, i0, i1 in full:
                if i0 <= i <= i1:
                    hole |= m
            if hole.any():
                img = fill(i, buf, hole, full, excl)
            enc.stdin.write(np.ascontiguousarray(img).tobytes())
            buf.pop(i - K, None)
            _feat.pop(i - K, None)
        enc.stdin.close()
        enc.wait()
        print(f"{dest.name}: " + "; ".join(f"{r['kind']} {r['from']}–{r['to']} с" for r in report[src.stem]), flush=True)
    (OUT / "captions.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
