#!/usr/bin/env python3
"""
Раунд 4: стирание текста без «плывущего» ИИ. LaMa по кадрам рисует каждый кадр заново, узоры дрожат. Здесь — как в видео-инпейнтинге:
  1. оптический поток DIS (OpenCV) по кадрам, внутри маски поток достраивается от окружения;
  2. пиксели под текстом берутся НАСТОЯЩИЕ из соседних кадров того же шота (вперёд/назад по потоку, с проверкой вперёд-назад),
     где это место не закрыто текстом;
  3. что не открылось ни разу (статичный фон) — один ключевой кадр LaMa на шот, переносится потоком: детали стабильны во времени,
     общий цвет и свет — от текущего кадра;
  4. края маски смягчаются. Старая LaMa — только исходник для шага 3.

Вход: downloads/1346/src, src_clean_lama / src_b_lama (или src_clean / src_b). Выход — --out-root (по умолчанию тест downloads/1346/flow_test).

  python clean_1346_flow.py --only water,blanket            # тест, боевые файлы не меняются
  python clean_1346_flow.py --apply                         # старые → *_lama, новые на их место
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import clean_1346_cta as C  # noqa: E402
import clean_1346_titles as T  # noqa: E402

BASE = ROOT / "downloads" / "1346"
FPS = 30
K = 45                     # на сколько кадров вперёд/назад искать настоящий пиксель
PAD = 150
FB_TOL = 1.5               # допуск проверки вперёд-назад, px
STILL_PX = 30              # ключевой кадр переносим только на малые сдвиги
JOBS = [("cta", n) for n in C.CFG] + [("title", n) for n in T.CFG]


def probe(p: Path) -> tuple[int, int]:
    return C.size(p)


def load(p: Path, roi: tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = roi
    w, h = x1 - x0, y1 - y0
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vf", f"fps={FPS},crop={w}:{h}:{x0}:{y0}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def shots(fr: np.ndarray) -> list[int]:
    """Начала шотов по резкому изменению кадра; на всякий случай и по ROI."""
    small = np.stack([cv2.resize(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY), (64, 32), interpolation=cv2.INTER_AREA) for f in fr]).astype(np.int16)
    d = np.abs(np.diff(small, axis=0)).mean((1, 2))
    med = max(1.0, float(np.median(d)))
    cuts = [0] + [i + 1 for i in range(len(d)) if d[i] > max(28, 7 * med)] + [len(fr)]
    return sorted(set(cuts))


def complete(flow: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Поток внутри маски — взвешенное среднее окружения (движение под текстом считаем плавным)."""
    keep = (m == 0).astype(np.float32)
    out = flow.copy()
    for s in (25, 60):
        w = cv2.GaussianBlur(keep, (0, 0), s) + 1e-4
        est = np.dstack([cv2.GaussianBlur(flow[..., c] * keep, (0, 0), s) / w for c in range(2)])
        if s == 25:
            res = est
            conf = w
        else:
            low = conf < 0.15
            res[low] = est[low]
    out[m > 0] = res[m > 0]
    return out


def sample(img: np.ndarray, pos: np.ndarray) -> np.ndarray:
    n, c = len(pos), 4096                      # cv2.remap: не больше 32767 в ширину — точки укладываем в сетку
    r = (n + c - 1) // c
    mx, my = np.zeros((r, c), np.float32), np.zeros((r, c), np.float32)
    mx.flat[:n], my.flat[:n] = pos[:, 0], pos[:, 1]
    return cv2.remap(img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).reshape(r * c, -1)[:n]


def chain(t: int, pts: np.ndarray, step: int, end: int, fw: list, bw: list, orig: np.ndarray, masked: np.ndarray, active: np.ndarray, hw: tuple[int, int]):
    """Идём по потоку из кадра t, пока точка не выйдет из-под текста; возвращает цвет, число шагов (0 — не нашлось)."""
    n = len(pts)
    col, steps = np.zeros((n, 3), np.float32), np.zeros(n, np.int32)
    pos, alive = pts.astype(np.float32).copy(), np.arange(n)
    h, w = hw
    k = t
    for s in range(1, K + 1):
        nxt = k + step
        if len(alive) == 0 or (step > 0 and nxt >= end) or (step < 0 and nxt < end):
            break
        F, B = (fw[k], bw[nxt]) if step > 0 else (bw[k], fw[nxt])
        d = sample(F, pos[alive])
        new = pos[alive] + d
        inside = (new[:, 0] >= 1) & (new[:, 0] < w - 2) & (new[:, 1] >= 1) & (new[:, 1] < h - 2)
        alive, new, d = alive[inside], new[inside], d[inside]
        if len(alive) == 0:
            break
        back = sample(B, new)
        ok = np.abs(d + back).sum(1) < FB_TOL
        alive, new = alive[ok], new[ok]
        pos[alive] = new
        if len(alive) == 0:
            break
        under = sample(masked.astype(np.float32), new).ravel() > 0.01 if active[nxt] else np.zeros(len(alive), bool)
        done = ~under
        if done.any():
            idx = alive[done]
            col[idx] = sample(orig[nxt].astype(np.float32), new[done])
            steps[idx] = s
            alive = alive[~done]
        k = nxt
    return col, steps


def process(kind: str, name: str, out_root: Path, base_clean: Path, base_b: Path) -> Path:
    if kind == "cta":
        win, box, grow, thr, t_min, extra = C.CFG[name]
        orig_p = C.SRC / name
        lama_p = base_clean / name
        core, m = C.mask_of(orig_p, win, box, grow, thr)
        if extra:
            m[extra[1]:extra[3], extra[0]:extra[2]] = 255
        t_a, t_b = t_min, 1e9
        dest = out_root / "src_clean" / name
    else:
        win, box, grow, thr, t_max, rects = T.CFG[name]
        fresh = out_root / "src_clean" / name
        orig_p = fresh if fresh.exists() else (C.OUT / name if (C.OUT / name).exists() else C.SRC / name)
        if not fresh.exists() and name in C.CFG and (BASE / "src_clean_lama" / name).exists():
            orig_p = C.OUT / name
        lama_p = base_b / name
        core, m = C.mask_of(orig_p, win, box, grow, thr)
        for a in rects:
            m[a[1]:a[3], a[0]:a[2]] = 255
        t_a, t_b = 0.0, t_max
        dest = out_root / "src_b" / name
    W, H = probe(orig_p)
    ys, xs = np.where(m > 0)
    roi = (max(0, int(xs.min()) - PAD) & ~1, max(0, int(ys.min()) - PAD) & ~1, min(W, int(xs.max()) + PAD) & ~1, min(H, int(ys.max()) + PAD) & ~1)
    x0, y0, x1, y1 = roi
    M = m[y0:y1, x0:x1]
    orig, lama = load(orig_p, roi), load(lama_p, roi)
    n = min(len(orig), len(lama))
    orig, lama = orig[:n], lama[:n]
    hw = M.shape
    active = np.array([(t_a <= i / FPS <= t_b) for i in range(n)])
    if kind == "cta":                                   # начало надписи — по ядру маски
        c = core[y0:y1, x0:x1] > 0
        vis = np.array([(f.min(2)[c] > thr - 20).mean() for f in orig])
        first = next((i for i in range(n) if vis[i] > 0.45 and i / FPS >= t_a), n)
        active = np.arange(n) >= max(0, first - 1)
    cuts = shots(lama)
    print(f"{kind} {name[:24]}: ROI {x1 - x0}×{y1 - y0}, активных кадров {int(active.sum())}, шоты {[round(c / FPS, 2) for c in cuts]}", flush=True)
    gray = [cv2.cvtColor(f, cv2.COLOR_RGB2GRAY) for f in lama]
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    fw, bw = [None] * n, [None] * n
    for s0, s1 in zip(cuts[:-1], cuts[1:]):
        for i in range(s0, s1 - 1):
            fw[i] = complete(dis.calc(gray[i], gray[i + 1], None), M).astype(np.float32)
            bw[i + 1] = complete(dis.calc(gray[i + 1], gray[i], None), M).astype(np.float32)
    for i in range(n):
        h0, w0 = hw
        fw[i] = fw[i] if fw[i] is not None else np.zeros((h0, w0, 2), np.float32)
        bw[i] = bw[i] if bw[i] is not None else np.zeros((h0, w0, 2), np.float32)
    pys, pxs = np.where(M > 0)
    pts = np.stack([pxs, pys], 1).astype(np.float32)
    result = orig.copy()
    stats = [0, 0, 0]
    masked = (cv2.dilate(M, np.ones((5, 5), np.uint8)) > 0).astype(np.uint8)
    blur = lambda im: cv2.GaussianBlur(im, (0, 0), 12)  # noqa: E731
    alpha = cv2.GaussianBlur((M > 0).astype(np.float32), (0, 0), 2.2)[..., None]
    for s0, s1 in zip(cuts[:-1], cuts[1:]):
        act = [i for i in range(s0, s1) if active[i]]
        if not act:
            continue
        key = act[len(act) // 2]
        key_img = lama[key].astype(np.float32)
        key_hi = key_img - blur(key_img)
        for t in act:
            f_col, f_s = chain(t, pts, +1, s1, fw, bw, orig, masked, active, hw)
            b_col, b_s = chain(t, pts, -1, s0, fw, bw, orig, masked, active, hw)
            cur = lama[t].astype(np.float32)
            fill = cur.copy()
            use_f = (f_s > 0) & ((b_s == 0) | (f_s <= b_s))
            use_b = (b_s > 0) & ~use_f
            vals = np.zeros((len(pts), 3), np.float32)
            vals[use_f], vals[use_b] = f_col[use_f], b_col[use_b]
            real = use_f | use_b
            rest = np.where(~real)[0]
            cur_lo = blur(cur)
            kept = np.zeros(len(pts), bool)
            if len(rest):
                pos = pts[rest].copy()
                ok = np.ones(len(rest), bool)
                total = np.zeros(len(rest), np.float32)
                k, stp = t, (1 if key > t else -1)
                while k != key:
                    d = sample(fw[k] if stp > 0 else bw[k], pos)
                    pos += d
                    total += np.abs(d).sum(1)
                    k += stp
                ok = (total < STILL_PX) & (pos[:, 0] >= 0) & (pos[:, 0] < hw[1] - 1) & (pos[:, 1] >= 0) & (pos[:, 1] < hw[0] - 1)
                if ok.any():
                    idx = rest[ok]
                    vals[idx] = sample(key_hi, pos[ok]) + cur_lo[pys[idx], pxs[idx]]
                    kept[idx] = True
            lama_only = ~(real | kept)
            vals[lama_only] = cur[pys[lama_only], pxs[lama_only]]
            fill[pys, pxs] = np.clip(vals, 0, 255)
            stats[0] += int(real.sum()); stats[1] += int(kept.sum()); stats[2] += int(lama_only.sum())
            result[t] = np.clip(alpha * fill + (1 - alpha) * orig[t], 0, 255).astype(np.uint8)
    tot = max(1, sum(stats))
    print(f"   настоящие пиксели {stats[0] / tot * 100:.0f}%, ключевой кадр {stats[1] / tot * 100:.0f}%, LaMa по кадрам {stats[2] / tot * 100:.0f}%", flush=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(orig_p), "-vf", f"fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-an", "-c:v", "h264_nvenc", "-preset", "p6",
                            "-rc", "vbr", "-cq", "14", "-pix_fmt", "yuv420p", str(dest)], stdin=subprocess.PIPE)
    sz, i = W * H * 3, 0
    while True:
        buf = dec.stdout.read(sz)
        if len(buf) < sz:
            break
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        if i < n:
            fr[y0:y1, x0:x1] = result[i]
        enc.stdin.write(fr.tobytes())
        i += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()
    print(f"   → {dest.relative_to(ROOT)}", flush=True)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    keys = [k.lower() for k in a.only.split(",") if k]
    jobs = [j for j in JOBS if not keys or any(k in j[1].lower() for k in keys)]
    lama_clean, lama_b = BASE / "src_clean_lama", BASE / "src_b_lama"
    if a.apply:
        for live, bak in ((BASE / "src_clean", lama_clean), (BASE / "src_b", lama_b)):
            if not bak.exists():
                shutil.copytree(live, bak)
        out_root = BASE
    else:
        out_root = BASE / "flow_test"
    base_clean = lama_clean if lama_clean.exists() else BASE / "src_clean"
    base_b = lama_b if lama_b.exists() else BASE / "src_b"
    for kind, name in jobs:
        process(kind, name, out_root, base_clean, base_b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
