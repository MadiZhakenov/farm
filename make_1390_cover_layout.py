#!/usr/bin/env python3
"""1390: раскладка новых обложек (output/1390_pick10/cover) — где столбик текста «clothes i find extremely swaggy in fall»
и как кадрировать фото, чтобы текст лёг на пустую сторону. Рамки размечены по сетке вручную (доли исходника 3:4):
лицо и джинсы закрывать нельзя (большой штраф), остальное тело — нежелательно. Перебор: зум z, сдвиг окна ox/oy,
сторона и высота текста cy, кегль s (≤ −15 %); человек целиком в кадре, текст в безопасной рамке.
Пишет output/1390_pick10/cover/_layout.json ({имя: {"v": {...}, "c": {...}}}).
  python make_1390_cover_layout.py"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("PICK1390", str(ROOT / "output" / "1390_pick10"))
sys.path.insert(0, str(ROOT))

# body — весь человек (целиком в кадре), face, jeans; extra — руки/сумки/стаканы
BOXES = {
    "cover2_01": dict(body=(0.08, 0.55, 0.02, 0.97), face=(0.28, 0.50, 0.10, 0.28), jeans=(0.15, 0.48, 0.52, 0.92), extra=[(0.30, 0.70, 0.0, 0.25)]),
    "cover2_02": dict(body=(0.30, 0.68, 0.30, 0.96), face=(0.40, 0.52, 0.30, 0.40), jeans=(0.36, 0.58, 0.55, 0.93)),
    "cover2_03": dict(body=(0.38, 0.70, 0.10, 0.97), face=(0.42, 0.56, 0.12, 0.25), jeans=(0.40, 0.65, 0.48, 0.95)),
    "cover2_05": dict(body=(0.36, 0.62, 0.40, 0.99), face=(0.42, 0.54, 0.42, 0.50), jeans=(0.40, 0.60, 0.60, 0.97)),
    "cover2_06": dict(body=(0.35, 0.65, 0.25, 0.99), face=(0.42, 0.55, 0.27, 0.37), jeans=(0.38, 0.63, 0.55, 0.97)),
    "cover2_07": dict(body=(0.25, 0.86, 0.15, 0.93), face=(0.62, 0.75, 0.17, 0.27), jeans=(0.28, 0.62, 0.50, 0.90)),
    "cover2_08": dict(body=(0.40, 0.78, 0.07, 0.98), face=(0.52, 0.66, 0.08, 0.22), jeans=(0.40, 0.72, 0.55, 0.97)),
    "cover2_09": dict(body=(0.36, 0.71, 0.37, 0.98), face=(0.45, 0.56, 0.38, 0.47), jeans=(0.40, 0.62, 0.62, 0.97)),
    "cover2_10": dict(body=(0.28, 0.70, 0.18, 0.89), face=(0.36, 0.48, 0.18, 0.30), jeans=(0.33, 0.70, 0.45, 0.88)),
    "cover2_11": dict(body=(0.39, 0.85, 0.17, 0.91), face=(0.55, 0.75, 0.17, 0.40), jeans=(0.40, 0.82, 0.55, 0.88)),
    "cover2_13": dict(body=(0.28, 0.70, 0.0, 0.96), face=(0.40, 0.55, 0.0, 0.15), jeans=(0.38, 0.68, 0.45, 0.96)),
}
SAFE = {"v": (140, 940, 200, 1540), "c": (180, 900, 0.06 * 1440, 0.78 * 1440)}
WEIGHT = {"face": 12.0, "jeans": 6.0, "body": 1.0, "extra": 1.0}


def block(fmt: str) -> tuple[int, int, int, int]:
    """Размер столбика текста (без полей тени) при s = 1 и W/H кадра — как в cover() сборщиков."""
    import build_1390_reels as R
    R = importlib.reload(R)
    if fmt == "c":                                  # модуль каруселей сам масштабирует кегль (R.COVER_CAP *= K) — ровно один раз
        if "build_1390_carousels" in sys.modules:
            importlib.reload(sys.modules["build_1390_carousels"])
        else:
            import build_1390_carousels  # noqa: F401
    text = dict(R.SLIDES)["cover"]
    cap = round(R.COVER_CAP * R.H)
    lines = [R.bebas(ln, cap, R.COVER_COLOR) for ln in text.split(R.NL)]
    step = round(cap * R.COVER_STEP)
    return max(ln.width for ln in lines), step * (len(lines) - 1) + lines[-1].height, R.W, R.H


def solve(name: str, fmt: str, geo) -> dict:
    bw0, bh0, W, H = geo
    sx0, sx1, sy0, sy1 = SAFE[fmt]
    fw = (W / H) / (3 / 4)                         # доля ширины исходника в кадре при z = 1 (ролик 0.75, карусель 1)
    bx = BOXES[name]
    boxes = [("face", bx["face"]), ("jeans", bx["jeans"]), ("body", bx["body"])] + [("extra", e) for e in bx.get("extra", [])]
    best = None
    for z in [1.0 + 0.025 * k for k in range(9)]:
        vw, vh = fw / z, 1 / z
        for ox in [k / 8 for k in range(9)]:
            for oy in (0.0, 0.25, 0.45, 0.75, 1.0):
                offx, offy = ox * (1 - vw), oy * (1 - vh)
                fb = lambda b: ((b[0] - offx) / vw, (b[1] - offx) / vw, (b[2] - offy) / vh, (b[3] - offy) / vh)   # noqa: E731
                body = fb(bx["body"])
                if body[0] < 0.01 or body[1] > 0.99 or body[2] < -0.02 or body[3] > 0.995:
                    continue
                fbs = [(kind, fb(b)) for kind, b in boxes]
                for s in (1.0, 0.925, 0.85):
                    bw, bh = bw0 * s, bh0 * s
                    for cxp in range(int(sx0), int(sx1 - bw) + 1, 10):
                        for cyc in [k / 100 for k in range(28, 50, 2)]:
                            ty0, ty1 = cyc - bh / 2 / H, cyc + bh / 2 / H
                            if ty0 * H < sy0 or ty1 * H > sy1:
                                continue
                            tx0, tx1 = cxp / W, (cxp + bw) / W
                            pen, gap = 0.0, 1.0
                            for kind, (x0, x1, y0, y1) in fbs:
                                ix = max(0.0, min(tx1, x1) - max(tx0, x0))
                                iy = max(0.0, min(ty1, y1) - max(ty0, y0))
                                pen += WEIGHT[kind] * ix * iy
                                if kind == "body" and iy > 0:
                                    gap = min(gap, max(x0 - tx1, tx0 - x1))
                            score = round(pen * 1000) + (z - 1) * 40 + (1 - s) * 60 + abs(cyc - 0.40) * 10 - min(gap, 0.06) * 30
                            if best is None or score < best[0]:
                                best = (score, dict(z=round(z, 3), ox=ox, oy=oy, cx=round((cxp + bw / 2) / W, 3), cy=cyc, s=s,
                                                    pen=round(pen, 4), gap=round(gap, 3)))
    return best[1]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    geo_v = block("v")
    geo_c = block("c")
    lay = {}
    for name in BOXES:
        lay[name] = {"v": solve(name, "v", geo_v), "c": solve(name, "c", geo_c)}
        print(name, "ролик", lay[name]["v"], "| карусель", lay[name]["c"], flush=True)
    out = Path(os.environ["PICK1390"]) / "cover" / "_layout.json"
    out.write_text(json.dumps(lay, indent=1), encoding="utf-8")
    print("→", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
