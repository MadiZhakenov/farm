#!/usr/bin/env python3
"""
Кадры «игра на телефоне» без лица (1254, кадры 4–5 рефа): из 4K-исходников, где
парень играет снятый через плечо, режем куски по --len и вырезаем окно вокруг
светящегося экрана телефона — голова остаётся за кадром.

  hands  — руки с телефоном (кадр 4): окно 0.5 ширины кадра (из 4K = родные 1080×1920)
  screen — экран крупно (кадр 5): окно 0.32 ширины, телефон по центру

Экран ищем как самое яркое насыщенное сине-фиолетовое пятно (сцена тёмная).
Окно сдвигается от головы: SOURCES[...]["head"] — с какой стороны от телефона голова.

  python cut_phone_clips.py --out downloads/1254/phone --len 1.5
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
RAW = ROOT / "downloads"
# «магик сорт и реакция вика»: парень играет, снято через плечо. head — где голова относительно
# телефона; roi — где вообще бывает телефон (x0, y0, x1, y1 в долях кадра): синий диван вне её не путаем с экраном
SOURCES = {
    "IMG_6418.mov": {"head": "right", "roi": (0.22, 0.38, 0.62, 0.68)},
    "IMG_6419 (2).mov": {"head": "left", "roi": (0.40, 0.25, 1.00, 0.75)},
    "IMG_6419 (3).mov": {"head": "left", "roi": (0.35, 0.25, 1.00, 0.75)},
    "IMG_6419.mov": {"head": "left", "roi": (0.35, 0.25, 1.00, 0.75)},
    "IMG_6426.mov": {"head": "right", "roi": (0.00, 0.40, 0.50, 0.90)},
}
# 1256 — «кози хом и реакция дима»: ДЕВУШКА играет, снято со спины. Экран белый (Cozy Home) → screen="white".
# t0/t1 — отрезок исходника: в IMG_6429 (1) она в середине пересаживается (голова то слева, то справа)
SOURCES_1256 = [
    {"file": "IMG_6428.mov", "head": "left", "roi": (0.25, 0.10, 0.85, 0.70), "screen": "white"},
    {"file": "IMG_6429.mov", "head": "left", "roi": (0.25, 0.10, 0.85, 0.70), "screen": "white"},
    {"file": "IMG_6429 (1).mov", "head": "left", "roi": (0.05, 0.05, 0.70, 0.60), "screen": "white",
     "t0": 0, "t1": 37},
    {"file": "IMG_6429 (1).mov", "head": "right", "roi": (0.00, 0.10, 0.75, 0.65), "screen": "white",
     "t0": 48, "t1": None},
]
SETS = {"1254": [{"file": k, **v} for k, v in SOURCES.items()], "1256": SOURCES_1256}
AW, AH, AFPS = 270, 480, 6          # кадры для анализа
CROPS = {  # ширина окна (доля ширины кадра), где телефон в окне по x (от стороны головы) и по y
    "hands": {"w": 0.50, "px": 0.30, "py": 0.40},
    "screen": {"w": 0.32, "px": 0.50, "py": 0.47},
}
COVER_MIN = 0.85     # доля кадров куска, где экран внутри окна
W, H, FPS = 1080, 1920, 30


def probe(path: Path) -> tuple[float, int, int]:
    """Длительность и размер кадра ПОСЛЕ автоповорота (iPhone .mov пишет rotation=-90)."""
    js = json.loads(subprocess.run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "format=duration:stream=width,height:stream_side_data=rotation",
                                    "-of", "json", str(path)], capture_output=True, text=True).stdout)
    st = js["streams"][0]
    w, h = st["width"], st["height"]
    rot = next((sd.get("rotation") for sd in st.get("side_data_list", []) if "rotation" in sd), 0)
    if abs(int(rot)) % 180 == 90:
        w, h = h, w
    return float(js["format"]["duration"]), w, h


def analysis_frames(path: Path) -> np.ndarray:
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-vf", f"fps={AFPS},scale={AW}:{AH}",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, AH, AW, 3)


def phone_center(fr: np.ndarray, roi: tuple = (0, 0, 1, 1),
                 screen: str = "violet") -> tuple[float, float, float] | None:
    """(x, y) центра экрана в долях кадра + площадь; None — экрана не видно.
    screen: violet — сине-фиолетовый Magic Sort; white — светлый экран (Cozy Home), почти без насыщенности."""
    hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    if screen == "white":
        m = ((v > 215) & (hsv[..., 1] < 70)).astype(np.uint8)
    else:
        m = ((v > 140) & (hsv[..., 1] > 70) & (hsv[..., 0] >= 110) & (hsv[..., 0] <= 140)).astype(np.uint8)
    keep = np.zeros_like(m)
    keep[int(roi[1] * AH):int(roi[3] * AH), int(roi[0] * AW):int(roi[2] * AW)] = 1
    m &= keep
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, stats, cents = cv2.connectedComponentsWithStats(m)
    best, best_score = None, 0.0
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a / (AW * AH) < 0.0015:
            continue
        fill = a / (w * h)                  # экран — компактный прямоугольник, не размазанный блик
        if fill < 0.35 or not (0.25 <= h / max(w, 1) <= 4.0):
            continue
        bright = float(v[lab == i].mean()) / 255
        score = a * fill * bright ** 4      # яркость важнее всего: экран ярче подсвеченной ткани
        if score > best_score:
            best, best_score = (cents[i][0] / AW, cents[i][1] / AH, a / (AW * AH)), score
    return best


def box(cx: float, cy: float, kind: str, head: str, fw: int, fh: int) -> tuple[int, int, int, int]:
    c = CROPS[kind]
    cw = int(c["w"] * fw) // 2 * 2
    ch = int(cw * 16 / 9) // 2 * 2
    px = c["px"] if head == "left" else 1 - c["px"]  # телефон ближе к стороне головы → голова за краем
    x = int(cx * fw - px * cw)
    y = int(cy * fh - c["py"] * ch)
    x = max(0, min(fw - cw, x))
    y = max(0, min(fh - ch, y))
    return x, y, cw, ch


def export(src: Path, start: float, length: float, boxes: dict[str, tuple], dests: dict[str, Path]) -> None:
    kinds = list(boxes)
    fc = f"[0:v]split={len(kinds)}" + "".join(f"[s{i}]" for i in range(len(kinds))) + ";"
    fc += ";".join(f"[s{i}]crop={boxes[k][2]}:{boxes[k][3]}:{boxes[k][0]}:{boxes[k][1]},"
                   f"scale={W}:{H}:flags=lanczos,fps={FPS},format=yuv420p,{SET_SDR}[o{i}]"
                   for i, k in enumerate(kinds))
    cmd = [FF, "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(src),
           "-filter_complex", fc]
    for i, k in enumerate(kinds):
        cmd += ["-map", f"[o{i}]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                *SDR_COLOR_ARGS, "-movflags", "+faststart", str(dests[k])]
    subprocess.run(cmd, stdin=subprocess.DEVNULL, check=True)


def face_flags(clip: Path, cascades: list) -> int:
    """Сколько из 3 кадров клипа с найденным лицом (анфас / профиль в обе стороны)."""
    hits = 0
    for t in (0.1, 0.75, 1.4):
        raw = subprocess.run([FF, "-v", "error", "-ss", f"{t:.2f}", "-i", str(clip), "-frames:v", "1",
                              "-vf", "scale=540:960", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             capture_output=True).stdout
        if len(raw) != 540 * 960:
            continue
        g = np.frombuffer(raw, np.uint8).reshape(960, 540)
        found = False
        for cc in cascades:
            for im in (g, cv2.flip(g, 1)):
                if len(cc.detectMultiScale(im, 1.1, 6, minSize=(70, 70))):
                    found = True
        hits += found
    return hits


def sheet(clips: list[Path], dest: Path, length: float) -> None:
    FW, FH, COLS = 108, 192, 8
    font = ImageFont.truetype("arial.ttf", 20)
    rows = (len(clips) + COLS - 1) // COLS
    img = Image.new("RGB", (COLS * (FW * 3 + 8), rows * (FH + 6)), "white")
    d = ImageDraw.Draw(img)
    for i, c in enumerate(clips):
        x0, y0 = (i % COLS) * (FW * 3 + 8), (i // COLS) * (FH + 6)
        for j, t in enumerate((0.05, length / 2, length - 0.08)):
            raw = subprocess.run([FF, "-v", "error", "-ss", f"{t:.2f}", "-i", str(c), "-frames:v", "1",
                                  "-vf", f"scale={FW}:{FH}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                 capture_output=True).stdout
            if len(raw) == FW * FH * 3:
                img.paste(Image.frombuffer("RGB", (FW, FH), raw), (x0 + j * FW, y0))
        d.rectangle([x0, y0, x0 + 44, y0 + 24], fill="black")
        d.text((x0 + 3, y0 + 1), c.name[:3], fill="yellow", font=font)
    img.save(dest, quality=88)


def export_wide(out: Path, length: float, keep_dir: Path) -> None:
    """Те же моменты, что остались в keep_dir после отбора, но полным кадром (виден парень) → wide_<len>s/."""
    manifest = {m["n"]: m for m in json.loads((out / "manifest.json").read_text(encoding="utf-8"))}
    dest_dir = out / f"wide_{length:g}s"
    dest_dir.mkdir(parents=True, exist_ok=True)
    clips = sorted(keep_dir.glob("*.mp4"))
    for c in clips:
        m = manifest[int(c.name[:3])]
        subprocess.run([FF, "-v", "error", "-y", "-ss", f"{m['start']:.3f}", "-t", f"{length:.3f}",
                        "-i", str(RAW / m["src"]), "-vf",
                        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                        f"fps={FPS},format=yuv420p,{SET_SDR}",
                        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", *SDR_COLOR_ARGS,
                        "-movflags", "+faststart", str(dest_dir / c.name)], stdin=subprocess.DEVNULL, check=True)
    sheet(sorted(dest_dir.glob("*.mp4")), dest_dir / "_sheet.jpg", length)
    print(f"wide: {len(clips)} клипов → {dest_dir}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--len", type=float, default=1.5)
    ap.add_argument("--wide-from", type=Path, help="папка отобранных клипов: выгрузить те же моменты полным кадром")
    ap.add_argument("--set", choices=sorted(SETS), default="1254", help="набор исходников")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if args.wide_from:
        export_wide(args.out, args.len, args.wide_from)
        return 0
    dirs = {k: args.out / f"{k}_{args.len:g}s" for k in CROPS}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    cascades = [cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / n)) for n in
                ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml",
                 "haarcascade_profileface.xml")]
    manifest, k = [], 0
    frames_cache: dict[str, np.ndarray] = {}
    for cfg in SETS[args.set]:
        name = cfg["file"]
        src = RAW / name
        dur, fw, fh = probe(src)
        if name not in frames_cache:
            frames_cache[name] = analysis_frames(src)
        frs = frames_cache[name]
        cents = [phone_center(f, cfg["roi"], cfg.get("screen", "violet")) for f in frs]
        win = int(round(args.len * AFPS))
        s0 = int((cfg.get("t0") or 0) * AFPS)
        s1 = len(frs) if cfg.get("t1") is None else min(len(frs), int(cfg["t1"] * AFPS))
        kept = 0
        for s in range(s0, s1 - win + 1, win):
            pts = [c for c in cents[s:s + win] if c]
            if len(pts) < 0.8 * win:
                continue  # экран не виден / погас
            cx, cy = float(np.median([p[0] for p in pts])), float(np.median([p[1] for p in pts]))
            boxes, ok = {}, True
            for kind in CROPS:
                x, y, cw, ch = box(cx, cy, kind, cfg["head"], fw, fh)
                inside = sum(x <= p[0] * fw <= x + cw and y <= p[1] * fh <= y + ch for p in pts) / win
                if inside < COVER_MIN:
                    ok = False
                boxes[kind] = (x, y, cw, ch)
            if not ok:
                continue
            k += 1
            start = s / AFPS
            stem = f"{k:03d}_{Path(name).stem.replace(' ', '').replace('(', '_').replace(')', '')}_{start:.1f}s"
            dests = {kind: dirs[kind] / f"{stem}.mp4" for kind in CROPS}
            export(src, start, args.len, boxes, dests)
            manifest.append({"n": k, "src": name, "start": start, "phone": [round(cx, 3), round(cy, 3)],
                             "boxes": boxes})
            kept += 1
        print(f"{name} [{cfg.get('t0') or 0}–{cfg.get('t1') or round(dur)} с]: кусков {kept}", flush=True)
    # лица: клипы, где каскады что-то нашли — сразу в _face/ (потом глазами)
    for kind, d in dirs.items():
        (d / "_face").mkdir(exist_ok=True)
        flagged = 0
        for c in sorted(d.glob("*.mp4")):
            if face_flags(c, cascades) >= 1:
                c.rename(d / "_face" / c.name)
                flagged += 1
        sheet(sorted(d.glob("*.mp4")), d / "_sheet.jpg", args.len)
        print(f"{kind}: {len(list(d.glob('*.mp4')))} клипов, с лицом (каскады) → _face: {flagged}", flush=True)
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
