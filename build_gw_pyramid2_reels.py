#!/usr/bin/env python3
"""
Global Work «пирамида», вторая партия (как build_gw_pyramid_reel.py / output/gw_pyramid): девушки снимают 6 стикеров
(пирамида 1-2-3) под звук «On the bottom of the pyramid», под каждым снятым стикером — плитка сайта с подписью,
сверху заголовок «Ranking job application / platforms». Порядок сайтов — по порядку снятия:
LinkedIn → Indeed → Glassdoor → Handshake → Google jobs → Globalwork.

  P1 — downloads/gw_pyramid2/src/P1_IMG_5752.MOV (жёлтые стикеры на серой доске, без звука, 36.7 с, 60 к/с);
  P2 — downloads/gw_pyramid2/src/P2_9bbcddf4.mov (розовые на бежевой, со звуком песни — сдвиг находим по звуку).

Плитки — ровные, статичные, на средних позициях стикеров (как в рефе), появляются, когда стикер снят.
Звук — чистый трек рефа (downloads/gw_pyramid/ref/pyramid_sound.m4a), −14 LUFS; видео режется по длине песни.

  python build_gw_pyramid2_reels.py              # оба
  python build_gw_pyramid2_reels.py P1 --start 3.2   # P1 с ручным сдвигом (песня начинается на 3.2 с ролика)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_pyramid_reel as P  # noqa: E402  (плитки, подписи, заголовок, звук)
from core.safe_zones import check_overlay  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = P.FF
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
SRC = ROOT / "downloads" / "gw_pyramid2" / "src"
OUT = ROOT / "output" / "gw_pyramid2"
SOUND = P.SOUND
W, H, FPS = 1080, 1920, 30
ID = "noid"
ORDER = [("linkedin", "LinkedIn"), ("indeed", "Indeed"), ("glassdoor", "Glassdoor"), ("handshake", "Handshake"),
         ("google", "Google jobs"), ("globalwork", "Globalwork")]
# имена в песне (Whisper, с): на каждом имени снимают очередной стикер — для проверки сдвига без звука
NAMES = [1.5, 6.4, 10.2, 12.4, 18.4, 27.5]
CLIPS = {
    "P1": {"file": "P1_IMG_5752.MOV", "note": ((26, 45, 190), (40, 120, 255)), "board": ((17, 30, 120), (29, 70, 200))},
    "P2": {"file": "P2_9bbcddf4.mov", "note": ((148, 40, 185), (178, 115, 255)), "board": ((6, 35, 140), (22, 95, 210))},
}


def dur_of(p: Path) -> float:
    return float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)


def frames(src: Path, w: int, h: int):
    p = subprocess.Popen([FF, "-v", "quiet", "-i", str(src), "-vf", f"scale={w}:{h},fps={FPS}", "-f", "rawvideo",
                          "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    try:
        while True:
            buf = p.stdout.read(w * h * 3)
            if len(buf) < w * h * 3:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    finally:
        p.kill()


def masks(bgr: np.ndarray, cfg: dict, top: int) -> tuple[np.ndarray, np.ndarray]:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    note = cv2.inRange(hsv, *cfg["note"])
    board = cv2.inRange(hsv, *cfg["board"])
    note[:top] = 0
    board[:top] = 0
    return note, board


def find_slots(src: Path, cfg: dict) -> list[tuple[int, int, int, int]]:
    """6 стикеров на первом кадре (540×960): верх, середина л/п, низ л/ц/п."""
    bgr = next(frames(src, 540, 960))
    note, _ = masks(bgr, cfg, 400)
    note = cv2.morphologyEx(note, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, _lab, st, _c = cv2.connectedComponentsWithStats(note)
    comps = sorted([st[i] for i in range(1, n)], key=lambda s: -s[4])[:6]
    if len(comps) < 6:
        raise SystemExit(f"{src.name}: на первом кадре найдено {len(comps)} стикеров из 6")
    boxes = [(int(x), int(y), int(x + w), int(y + h)) for x, y, w, h, _a in comps]
    boxes.sort(key=lambda b: b[1])
    top, mid, bot = boxes[:1], sorted(boxes[1:3]), sorted(boxes[3:])
    return top + mid + bot


def track(src: Path, cfg: dict, slots: list) -> tuple[list[list[float]], list[float]]:
    """Каждый стикер ведём по кадрам (пятна цвета стикера, ближайшее к предсказанию с учётом общего сдвига доски).
    Снят — после последнего момента, когда его видно ≥ 0.2 с подряд (рука перед стикером — не снятие).
    Возвращает медианные центры стикеров (540×960) и время снятия."""
    area0 = float(np.median([(x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in slots]))
    pos = np.array([[(x0 + x1) / 2, (y0 + y1) / 2] for x0, y0, x1, y1 in slots], np.float64)
    run, last, hist = np.zeros(6, int), np.zeros(6), [[] for _ in range(6)]
    half = int(0.4 * np.sqrt(area0))
    board_frac = []                                  # доля цвета доски на месте каждого стикера, по кадрам
    for i, bgr in enumerate(frames(src, 540, 960)):
        note, board = masks(bgr, cfg, 380)
        note = cv2.morphologyEx(note, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        n, _l, st, c = cv2.connectedComponentsWithStats(note)
        cs = np.array([c[k] for k in range(1, n) if 0.45 * area0 <= st[k][4] <= 1.6 * area0]).reshape(-1, 2)
        shift = np.zeros(2)
        if len(cs):
            d = np.array([cs[np.argmin(np.linalg.norm(cs - q, axis=1))] - q for q in pos])
            near = np.linalg.norm(d, axis=1) < 60
            if near.any():
                shift = np.median(d[near], axis=0)
        pred, used = pos + shift, set()
        for j in range(6):
            dist = np.linalg.norm(cs - pred[j], axis=1) if len(cs) else np.array([])
            k = int(np.argmin(dist)) if len(dist) else -1
            if k >= 0 and dist[k] < 35 and k not in used:
                used.add(k)
                pos[j] = cs[k]
                run[j] += 1
                hist[j].append(cs[k].tolist())
                if run[j] >= 6:
                    last[j] = (i + 1) / FPS
            else:
                pos[j] = pred[j]
                run[j] = 0
        bf = []
        for j in range(6):
            x, y = int(pos[j][0]), int(pos[j][1])
            win = board[max(0, y - half):y + half, max(0, x - half):x + half]
            bf.append(float((win > 0).mean()) if win.size else 0.0)
        board_frac.append(bf)
    cen = [np.median(np.array(h), axis=0).tolist() for h in hist]
    # снят = место стикера стало доской (стикер оторван и рука убрана), держится ≥ 0.3 с; раньше, пока она
    # только берётся за стикер, логотип не показываем
    B = np.array(board_frac)
    gone = []
    for j in range(6):
        k0 = int(last[j] * FPS) - 6
        ok = B[:, j] >= 0.55
        k = next((i for i in range(max(0, k0), len(ok) - 9) if ok[i:i + 9].all()), int(last[j] * FPS))
        gone.append(round(k / FPS, 3))
    return cen, gone


def song_start(src: Path) -> float | None:
    """С какой секунды ролика играет песня (по звуку ролика); None — звука нет или это не песня."""
    def load(p, extra=()):
        return np.frombuffer(subprocess.run([FF, "-v", "error", "-i", str(p), *extra, "-vn", "-ac", "1", "-ar", "8000",
                                             "-f", "f32le", "-"], capture_output=True).stdout, np.float32).astype(np.float64)
    a, s = load(src), load(SOUND)
    if len(a) < 8000:
        return None
    n = 1 << int(np.ceil(np.log2(len(a) + len(s))))
    c = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(s, n)), n)
    lag = int(np.argmax(np.abs(c)))
    lag = lag - n if lag > n // 2 else lag
    if lag < 0:
        return None
    seg = a[lag:lag + len(s)]
    m = min(len(seg), len(s))
    r = float(np.corrcoef(seg[:m], s[:m])[0, 1]) if m > 8000 else 0.0
    return lag / 8000 if r > 0.5 else None


def mouth_start(src: Path, lo: float, hi: float) -> tuple[float, float]:
    """Без звука: сдвиг, при котором открытие рта (MediaPipe jawOpen) лучше всего совпадает с речью песни."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    opt = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "face_landmarker.task")),
                                       running_mode=vision.RunningMode.VIDEO, num_faces=1, output_face_blendshapes=True)
    fl = vision.FaceLandmarker.create_from_options(opt)
    jaw = []
    for k, bgr in enumerate(frames(src, 360, 640)):
        r = fl.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)),
                                int(k * 1000 / FPS))
        if r.face_blendshapes:
            jaw.append(next(b.score for b in r.face_blendshapes[0] if b.category_name == "jawOpen"))
        else:
            jaw.append(np.nan)
    fl.close()
    jaw = np.array(jaw)
    jaw = np.where(np.isnan(jaw), np.nanmedian(jaw), jaw)
    a = np.frombuffer(subprocess.run([FF, "-v", "error", "-i", str(SOUND), "-ac", "1", "-ar", "16000", "-af",
                                      "highpass=f=200,lowpass=f=4000", "-f", "f32le", "-"], capture_output=True).stdout,
                      np.float32)
    hop = 16000 // FPS
    env = np.array([np.sqrt(np.mean(a[i:i + hop] ** 2)) for i in range(0, len(a) - hop, hop)])
    env = (env - env.mean()) / (env.std() + 1e-9)
    jz = (jaw - jaw.mean()) / (jaw.std() + 1e-9)
    best = (-9.0, lo)
    for k in range(int(lo * FPS), int(hi * FPS) + 1):
        seg = jz[k:k + len(env)]
        if len(seg) < len(env) * 0.9:
            continue
        c = float(np.mean(seg * env[:len(seg)]))
        best = max(best, (c, k / FPS))
    return best[1], best[0]


def build(name: str, start_override: float | None) -> dict:
    cfg = CLIPS[name]
    src = SRC / cfg["file"]
    cache = SRC / f"{name}_track.json"
    if cache.exists():
        c = json.loads(cache.read_text())
        slots, med_c, gone = [tuple(s) for s in c["slots"]], c["cen"], c["gone"]
    else:
        slots = find_slots(src, cfg)
        med_c, gone = track(src, cfg, slots)
        cache.write_text(json.dumps({"slots": slots, "cen": med_c, "gone": gone}))
    print(name, "слоты", slots, "сняты", [round(g, 2) for g in gone], flush=True)
    order = sorted(range(6), key=lambda j: gone[j])                 # порядок снятия → сайты
    brand = {j: ORDER[k] for k, j in enumerate(order)}
    snd = dur_of(SOUND)
    vd = dur_of(src)
    how = "вручную"
    start = start_override
    if start is None:
        start = song_start(src)
        how = "по звуку ролика"
    if start is None:                       # звука нет: грубо — по снятиям стикеров на именах, точно — по губам
        est = float(np.median(np.array(sorted(gone)) - np.array(NAMES)))
        start, score = mouth_start(src, max(0.0, est - 1.0), min(vd - snd, est + 1.0))
        how = f"по губам (корр. {score:.2f}; по стикерам ≈ {est:.2f})"
    peel = sorted(gone)
    check = [round(p - start - n, 2) for p, n in zip(peel, NAMES)]
    # статичные плитки на средних позициях стикеров
    scale = 1.0
    sizes = [min(x1 - x0, y1 - y0) for x0, y0, x1, y1 in slots[1:]]
    cen = [np.float32(c) * 2 for c in med_c]
    # ровная пирамида, как в рефе: у плиток одного ряда одна высота (доска бывает наклонена — нижние стикеры
    # на разной высоте, и плитки налезали подписями на ряд выше)
    for row in ([0], [1, 2], [3, 4, 5]):
        y = float(np.mean([cen[j][1] for j in row]))
        for j in row:
            cen[j] = np.float32([cen[j][0], y])
    pitch_v = min(abs(cen[1][1] - cen[0][1]), abs(cen[3][1] - cen[1][1]))
    pitch_h = min(abs(cen[2][0] - cen[1][0]), abs(cen[4][0] - cen[3][0]), abs(cen[5][0] - cen[4][0]))
    side = int(min(np.median(sizes) * 2 * scale * 0.82, (pitch_v - 14) / 1.17, pitch_h - 20))
    lab_w = int(pitch_h - 12)
    work = OUT / f"_tiles_{name}"
    work.mkdir(parents=True, exist_ok=True)
    inputs, chain = ["-i", str(src)], [f"[0:v]scale={W}:{H}:flags=lanczos,fps={FPS},setsar=1[v0]"]
    for n, j in enumerate(range(6), 1):
        key, text = brand[j]
        lab = P.label(text, lab_w, max(16, int(side * 0.24)))
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        cx, cy = float(cen[j][0]), float(cen[j][1])
        top = int(cy - (side + lab.height * 0.55) / 2)
        canvas.alpha_composite(P.tile(key, side), (int(cx - side / 2), top))
        canvas.alpha_composite(lab, (int(cx - lab.width / 2), int(top + side - lab.height * 0.45)))
        png = work / f"slot{j}.png"
        canvas.save(png)
        inputs += ["-i", str(png)]
        chain.append(f"[v{n - 1}][{n}:v]overlay=0:0:enable='gte(t,{gone[j]:.2f})'[v{n}]")
    tpng = work / "title.png"
    P.title_png(tpng)
    bad = check_overlay(tpng)
    if bad:
        raise SystemExit(f"заголовок вне безопасной зоны: {bad}")
    inputs += ["-i", str(tpng)]
    chain.append(f"[v6][7:v]overlay=0:0[v7]")
    end = min(vd, start + snd)
    chain.append(f"[v7]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,format=yuv420p,{SET_SDR}[v]")
    inputs += ["-i", str(SOUND)]
    chain.append(f"[8:a]atrim=0:{end - start:.3f},asetpts=PTS-STARTPTS,{P.audio_filter()}[a]")
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"gw_pyramid_{name}_{ID}.mp4"
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18", *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(dest)], check=True)
    return {"file": dest.name, "start": round(start, 2), "how": how, "duration": round(end - start, 2),
            "peel": [round(g, 2) for g in gone], "brand_by_slot": {j: brand[j][1] for j in range(6)},
            "peel_minus_name": check, "tile": side}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="*", default=list(CLIPS))
    ap.add_argument("--start", type=float, help="ручной сдвиг: на какой секунде ролика начинается песня")
    a = ap.parse_args()
    for name in a.clips:
        r = build(name, a.start)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
