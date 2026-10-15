"""Зелёный экран телефона на фото → настоящий скрин игры (перспектива по 4 углам, пальцы/вырез сохраняются).

  python composite_phone_screen.py IMG_OR_DIR --screens output/VCIY4029_screens --pick 031,037 --out DIR [--debug]
"""
import argparse
import random
from pathlib import Path

import cv2
import numpy as np

EXT = {".jpg", ".jpeg", ".png", ".webp"}


def load(p):
    return cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)


def save(img, p):
    cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tofile(str(p))


def green_key(img):
    """0..1: насколько пиксель «хромакейно-зелёный» (g сильно больше r и b)."""
    f = img.astype(np.float32)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    d = g - np.maximum(r, b)
    return np.clip((d - 40) / 60, 0, 1)


def order(pts):
    pts = np.asarray(pts, np.float32)
    s, d = pts.sum(1), pts[:, 1] - pts[:, 0]
    return np.float32([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]])


def find_screen(img):
    """Самая большая зелёная область → (маска области, 4 угла TL TR BR BL)."""
    hard = (green_key(img) > 0.5).astype(np.uint8) * 255
    hard = cv2.morphologyEx(hard, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(hard)
    if n < 2:
        raise ValueError("зелёный экран не найден")
    k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    comp = (lab == k).astype(np.uint8) * 255
    cnt = max(cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)
    hull = cv2.convexHull(cnt)  # вырез/палец не ломают форму
    region = np.zeros(img.shape[:2], np.uint8)
    cv2.fillPoly(region, [hull], 255)
    # точки края области (плотно) → по прямой на каждую сторону, углы = пересечения прямых
    # (approxPolyDP на скруглённых углах цепляет точки дуг → перекошенный четырёхугольник)
    edge = max(cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0],
               key=cv2.contourArea).reshape(-1, 2).astype(np.float32)
    quad = order(cv2.boxPoints(cv2.minAreaRect(hull)))
    for _ in range(3):
        lines = []
        for s in range(4):
            a, b = quad[s], quad[(s + 1) % 4]
            v = b - a
            L = np.linalg.norm(v)
            u, nrm = v / L, np.float32([-v[1], v[0]]) / L
            t = (edge - a) @ u
            d = np.abs((edge - a) @ nrm)
            # только прямая часть стороны: без 18 % у каждого угла (скругления) и близко к линии
            sel = edge[(t > 0.18 * L) & (t < 0.82 * L) & (d < 0.06 * L + 3)]
            vx, vy, x0, y0 = cv2.fitLine(sel, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
            lines.append((np.float32([x0, y0]), np.float32([vx, vy])))
        quad = np.float32([_cross(lines[s - 1], lines[s]) for s in range(4)])
    return region, order(quad), hull


def _cross(l1, l2):
    (p, r), (q, s) = l1, l2
    cr = lambda a, b: a[0] * b[1] - a[1] * b[0]
    t = cr(q - p, s) / cr(r, s)
    return p + t * r


def expand(q, px):
    c = q.mean(0)
    v = q - c
    return c + v * (1 + px / np.linalg.norm(v, axis=1, keepdims=True))


def composite(bg, shot, seed=0):
    region, q, hull = find_screen(bg)
    H, W = bg.shape[:2]
    # углы = пересечения сторон зелёного → скрин ровно по экрану (+1.5 px под мягкий край)
    qe = expand(q, 1.5)
    sh, sw = shot.shape[:2]
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [sw, 0], [sw, sh], [0, sh]]), qe)
    # экран мелкий → сначала уменьшаем скрин до размера экрана (INTER_AREA), иначе мерцание/алиасинг
    scale = max(np.linalg.norm(qe[0] - qe[3]) / sh, np.linalg.norm(qe[0] - qe[1]) / sw)
    if scale < 0.9:
        small = cv2.resize(shot, (max(2, int(sw * scale * 1.6)), max(2, int(sh * scale * 1.6))),
                           interpolation=cv2.INTER_AREA)
        M = cv2.getPerspectiveTransform(np.float32([[0, 0], [small.shape[1], 0], [small.shape[1], small.shape[0]],
                                                    [0, small.shape[0]]]), qe)
        shot = small
    warped = cv2.warpPerspective(shot, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    # экран светится, но в ночном кадре не «выжжен»: чуть мягче контраст + подогнать под яркость зелёного
    f = warped.astype(np.float32)
    f = 18 + f * 0.93
    # блик: лёгкий диагональный градиент
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    c = q.mean(0)
    diag = ((xx - c[0]) * 0.6 - (yy - c[1])) / (np.linalg.norm(q[0] - q[2]) + 1)
    f += np.clip(0.5 - np.abs(diag + 0.15) * 2.2, 0, 1)[..., None] * 22
    # зерно как у фото
    rng = np.random.default_rng(seed)
    f += rng.normal(0, 3.2, (H, W, 1)).astype(np.float32)
    warped = np.clip(f, 0, 255)

    # альфа = мягкий ключ зелёного, только внутри области экрана (+ пара px), вырез и пальцы остаются
    key = green_key(bg)
    zone = cv2.dilate(region, np.ones((7, 7), np.uint8))
    # кайму между зелёным и рамкой закрываем: ключ расширяем на ~2 px (зелёный переход уходит под скрин)
    grow = max(2, int(0.012 * np.linalg.norm(q[0] - q[1])))
    a = cv2.dilate(key, np.ones((2 * grow + 1, 2 * grow + 1), np.uint8)) * (zone > 0)
    a = cv2.GaussianBlur(a, (3, 3), 0)
    # внутри экрана дыры от шума/бликов закрываем, но не вырез (он тёмный и не зелёный — key=0, остаётся)
    out = bg.astype(np.float32) * (1 - a[..., None]) + warped * a[..., None]

    # despill: зелёная кайма/отсвет на пальцах и рамке рядом с экраном
    ring = cv2.dilate(region, np.ones((41, 41), np.uint8)) > 0
    b_, g_, r_ = out[..., 0], out[..., 1], out[..., 2]
    lim = np.maximum(r_, b_) + 2
    spill = ring & (g_ > lim) & (a < 0.98)
    out[..., 1] = np.where(spill, lim, g_)
    return np.clip(out, 0, 255).astype(np.uint8), q, hull


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--screens", default="output/VCIY4029_screens")
    ap.add_argument("--pick", default="", help="префиксы скринов через запятую (031,037); пусто = случайные")
    ap.add_argument("--out", required=True)
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    src = Path(a.src)
    imgs = [src] if src.is_file() else sorted(p for p in src.iterdir() if p.suffix.lower() in EXT)
    shots = sorted(p for p in Path(a.screens).iterdir() if p.suffix.lower() in EXT)
    if a.pick:
        pre = [x.strip() for x in a.pick.split(",")]
        shots = [p for p in shots if any(p.name.startswith(x) for x in pre)]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(42)
    for i, p in enumerate(imgs):
        bg = load(p)
        for j, s in enumerate(shots if a.pick else [rnd.choice(shots)]):
            res, q, hull = composite(bg, load(s), seed=i * 100 + j)
            name = f"{p.stem}__{s.stem[:3]}.jpg"
            save(res, out / name)
            print(name)
            if a.debug:
                x, y, w, h = cv2.boundingRect(hull)
                m = int(max(w, h) * 0.6)
                crop = res[max(0, y - m):y + h + m, max(0, x - m):x + w + m]
                save(cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC), out / f"_zoom_{name}")


if __name__ == "__main__":
    main()
