#!/usr/bin/env python3
"""
Skinive 3 + Skinive 6 (ID 1), уникальная версия (юзер 2026-11-11: «многие блокировались как неуникальные, каждый
похож на другой»). Формат тот же, что в build_skinive_overlay.py: видео без скринкаста, поверх карточка App Store
и окошко результата. Раньше на 150 роликов было 5 окон лица × 5 окон родинки, зум ≤ 6 %, один трек с нуля и одна
раскладка. Теперь у КАЖДОГО ролика своё (непрерывные случайные величины, а не перебор из списка):
  • старт лица в любом месте проверенных дублей (7 участков на 37 с), длины кусков;
  • родинка из длинных треков (make_skinive_long_tracks.py), любой старт на чистых участках, два разных участка;
  • кадрирование: доп. зум 1.08–1.45, сдвиг, поворот ±1.8°, зеркало, скорость 0.94–1.06;
  • цвет: яркость/контраст/насыщенность/гамма, цветовая температура, зерно, иногда виньетка;
  • текст: кегль ±6 %, высота; текстволл — кегль и высота;
  • карточки: App Store тёмная/светлая, ширина и высота; результат плашка/шкала, ширина, момент появления;
  • звук: старт трека в петле, тон/темп ±3 %, громкость, свой «поп».
Текст ТЗ дословно, всё в безопасной рамке. Проверка похожести: measure_skinive_uniq.py.

  python build_skinive_uniq.py --proj 3 --tag tt -n 150 --seed 3101 --out output/skinive3_TT_150_v2
  python build_skinive_uniq.py --proj 3 --tag yt -n 150 --seed 3102 --out output/skinive3_YT_150_v2
  python build_skinive_uniq.py --proj 6 --tag tt -n 100 --seed 6101 --out output/skinive6_TT_100_v2
  python build_skinive_uniq.py --proj 6 --tag yt -n 150 --seed 6102 --out output/skinive6_YT_150_v2
"""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_skinive2 as S2  # noqa: E402  (outline_text, music_loop)
import build_skinive3 as S3  # noqa: E402  (тексты skinive_3, лицо)
import build_skinive5 as S5  # noqa: E402  (текстволл skinive_6)
import build_skinive_overlay as OV  # noqa: E402  (карточки)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
WORK = ROOT / "output" / "_work" / "skinive_uniq"
LONG = ROOT / "output" / "_work" / "skinive_overlay" / "long"
FACE = S3.FACE
POPS = [ROOT / "downloads" / "drops_beats" / "sfx" / "pop" / f for f in ("pop_402323.mp3", "pop_402324.mp3", "bubble06_351337.mp3")]
# лицо: участки, где выражение подходит целиком (отсмотрено по листу 0.25 с)
FACE_SPANS = {
    # 13.11: в исходнике монтажная склейка на 18.7 с (рука у лица → палец у губ) — участок 17.75–24.6 давал «срыв»
    # внутри куска лица (юзер: «резкие срывы кадров»); теперь с 18.75
    3: [(1.25, 4.4), (7.5, 11.0), (12.25, 16.0), (18.75, 24.6), (29.25, 34.0), (34.0, 36.9)],     # смотрит/трогает кожу, тревога
    6: [(3.9, 5.6), (6.5, 8.1), (10.9, 12.7), (16.6, 18.4), (23.4, 25.0), (31.6, 33.6), (34.2, 36.0)],  # шок
}
# длинные треки родинок: чистые участки (без поворота руки и сползания трека)
MOLE_SPANS = {"c": [("c1", 0.0, 6.5)],
              "a": [("a1", 0.0, 3.1), ("a1", 4.8, 6.75), ("a2", 0.0, 3.1), ("a3", 0.0, 3.7)],
              "p": [("p1", 0.0, 12.7)]}                  # рука без маркера, мелкие родинки (только skinive_3)
ZOOM = {"c": (1.15, 1.5), "a": (1.15, 1.5), "p": (1.35, 1.65), "face": (1.08, 1.25)}
COUNTS = {3: (150, 150), 6: (100, 150)}                   # TT, YT — планируются вместе, чтобы и между ними не было похожих
MUSIC_RATE = None
GAUGE_W = {3: (460, 480, 500), 6: (460, 480, 500)}


def pick_span(rng: random.Random, spans: list, length: float, avoid: tuple | None = None):
    ok = [s for s in spans if s[-1] - s[-2] >= length + 0.05 and s != avoid]
    s = rng.choice(ok)
    return s, round(rng.uniform(s[-2], s[-1] - length), 3)


def shot(rng: random.Random, src_spans: list, length: float, sp: float, taken: list, target_y, zk: str) -> dict:
    """Один шот: участок длинного трека (не пересекается с уже взятыми в этом ролике) + своя геометрия."""
    for _ in range(40):
        ok = [x for x in src_spans if x[2] - x[1] >= length * sp + 0.05]
        sid, a, b = rng.choice(ok)
        t = round(rng.uniform(a, b - length * sp), 3)
        if all(not (o[0] == sid and o[1] < t + length * sp and t < o[1] + o[2]) for o in taken):
            break
    taken.append((sid, t, length * sp))
    g = geo(rng, *ZOOM[zk], target_y)
    return dict(src=sid, t=t, len=round(length, 3), g=g)


def split(rng: random.Random, length: float, p2: float) -> list[float]:
    if rng.random() < p2:
        a = round(length * rng.uniform(0.4, 0.6), 3)
        return [a, round(length - a, 3)]
    return [length]


def candidate(proj: int, rng: random.Random) -> dict:
    sp = round(rng.uniform(0.94, 1.06), 3)
    face_spans = [("face", a, b) for a, b in FACE_SPANS[proj]]
    taken: list = []
    if proj == 3:
        L = [round(rng.uniform(2.6, 3.2), 2), round(rng.uniform(2.7, 3.2), 2), round(rng.uniform(2.9, 3.4), 2)]
        grp = rng.choice(("c", "a", "p", "p"))
        segs = [[shot(rng, face_spans, x, sp, taken, None, "face") for x in split(rng, L[0], 0.3)],
                [shot(rng, MOLE_SPANS[grp], x, sp, taken, rng.uniform(0.42, 0.62), grp) for x in split(rng, L[1], 0.65)],
                [shot(rng, MOLE_SPANS[grp], x, sp, taken, rng.uniform(0.53, 0.58), grp) for x in split(rng, L[2], 0.5)]]
    else:
        L = [round(rng.uniform(1.9, 2.2), 2), round(rng.uniform(1.5, 1.8), 2), round(rng.uniform(2.8, 3.3), 2)]
        segs = [[shot(rng, MOLE_SPANS["a"], x, sp, taken, rng.uniform(0.38, 0.48), "a") for x in split(rng, L[0], 0.4)],
                [shot(rng, face_spans, L[1], sp, taken, None, "face")],
                [shot(rng, MOLE_SPANS["a"], x, sp, taken, rng.uniform(0.43, 0.47), "a") for x in split(rng, L[2], 0.55)]]
    L = [round(sum(x["len"] for x in seg), 3) for seg in segs]
    return dict(L=L, speed=sp, segs=segs, mirror=rng.random() < 0.5,
                card=rng.choice(("plate", "gauge")), theme=rng.choice(("dark", "dark", "light")), seed=rng.randrange(10 ** 9))


def _rect(g: dict) -> tuple:
    w = 1 / g["z"]
    cx, cy = 0.5 + g["dx"], 0.5 + g["dy"]
    return cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def overlap(A: dict, B: dict) -> float:
    """Оценка доли кадров A, похожих на кадры B: те же секунды исходника при похожем окне кадра."""
    m = 0.0
    for sa in (x for seg in A["segs"] for x in seg):
        for sb in (x for seg in B["segs"] for x in seg):
            if sa["src"] != sb["src"]:
                continue
            a0, a1 = sa["t"], sa["t"] + sa["len"] * A["speed"]
            b0, b1 = sb["t"], sb["t"] + sb["len"] * B["speed"]
            ov = max(0.0, min(a1, b1) - max(a0, b0))
            if ov > 0 and _iou(_rect(sa["g"]), _rect(sb["g"])) > 0.5:
                m += ov / A["speed"]
    return m / sum(A["L"])


def plan(proj: int, seed: int, tries: int = 30) -> list[dict]:
    """TT + YT одним списком: каждый следующий ролик — самый непохожий из tries кандидатов на всё уже выбранное."""
    f = WORK / f"plan_{proj}_v3_{seed}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    rng = random.Random(seed)
    rows: list = []
    for k in range(sum(COUNTS[proj])):
        best = None
        for _ in range(tries):
            c = candidate(proj, rng)
            sc = max((max(overlap(c, r), overlap(r, c)) for r in rows), default=0.0)
            if best is None or sc < best[0]:
                best = (sc, c)
        best[1]["score"] = round(best[0], 3)
        rows.append(best[1])
    for i, r in enumerate(rows):
        tt = i < COUNTS[proj][0]
        r["tag"], r["n"] = ("tt", i + 1) if tt else ("yt", i + 1 - COUNTS[proj][0])
    WORK.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rows), encoding="utf-8")
    sc = sorted(r["score"] for r in rows)
    print(f"план {proj}: {len(rows)} роликов, похожесть на ближайший: медиана {sc[len(sc) // 2]:.2f}, макс {sc[-1]:.2f}")
    return rows


def geo(rng: random.Random, zmin: float, zmax: float, target_y: float | None) -> dict:
    """Доп. зум, поворот и сдвиг окна. target_y — где должна стоять родинка (доля высоты; в длинном треке она в центре)."""
    z = rng.uniform(zmin, zmax)
    ang = rng.uniform(-1.8, 1.8)
    a = math.radians(abs(ang))
    need = math.cos(a) + (H / W) * math.sin(a)                 # зум, чтобы после поворота не было чёрных углов
    free = max(0.0, (1 - need / z) / 2)                         # запас сдвига (доля кадра) с каждой стороны
    dx = rng.uniform(-free, free) * 0.85
    if target_y is None:
        dy = rng.uniform(-free, free) * 0.85
    else:
        dy = (0.5 - target_y) / z + rng.uniform(-0.015, 0.015)  # окно сдвигаем так, чтобы родинка встала на target_y
        dy = max(-free, min(free, dy))
    return dict(z=z, ang=ang, dx=dx, dy=dy)


def vf_geo(g: dict, mirror: bool) -> str:
    cw, ch = round(W / g["z"] / 2) * 2, round(H / g["z"] / 2) * 2
    x0 = round((W - cw) / 2 + g["dx"] * W)
    y0 = round((H - ch) / 2 + g["dy"] * H)
    return (f"rotate={g['ang']:.3f}*PI/180:ow=iw:oh=ih:fillcolor=black,crop={cw}:{ch}:{x0}:{y0},"
            f"scale={W}:{H}:flags=lanczos{',hflip' if mirror else ''},setsar=1")


def text_layers(proj: int, rng: random.Random, tmp: Path, L: list[float], total: float) -> tuple[list, int]:
    """PNG-слои текста ТЗ: [(png, t0, t1)], и нижняя граница последнего текста (для skinive_3)."""
    import assemble_ugc_reels as A
    from core import renderer as R
    out = []
    if proj == 3:
        px = S3.CAP_PX
        while True:                                     # как в build_skinive3: самая широкая строка ≤ 790
            font, st = R._load_font(px), max(2, round(px * S2.STROKE))
            e_px = A._emoji_px(px)
            widest = max(sum(e_px * 1.08 if k == "emoji" else font.getlength(c) for k, c in A._tokenize_runs(ln) if c)
                         for lines, _, _ in S3.TEXTS for ln in lines)
            if widest + 2 * st <= 790 or px <= 36:
                break
            px -= 1
        px = round(px * rng.uniform(0.92, 1.0))
        top = rng.randint(205, 290)
        times = [(0, L[0]), (L[0], L[0] + L[1] / 2), (L[0] + L[1] / 2, L[0] + L[1]), (L[0] + L[1], total)]
        bottom = 0
        for i, ((lines, _, _), (a, b)) in enumerate(zip(S3.TEXTS, times)):
            img = S2.outline_text(lines, px, top)
            if bad := check_box(W, H, img.getbbox()):
                raise SystemExit(f"текст вне безопасной зоны: {lines} {bad}")
            p = tmp / f"t{i}.png"
            img.save(p)
            out.append((p, a, b))
            bottom = img.getbbox()[3]
        return out, bottom
    WL = S5.WL
    n = len([ln for ln in S5.TEXT.splitlines() if ln.strip()])
    px = 56
    while px > 30 and (WL.wall_height(S5.TEXT, px) > WL.Y1 - 8 - S5.WALL_TOP_MIN or
                       len([x for x in WL.wall_lines(S5.TEXT, px) if x]) > n):
        px -= 1
    px -= rng.randint(0, 4)
    top = WL.Y1 - 8 - WL.wall_height(S5.TEXT, px) - rng.randint(0, 40)
    p = tmp / "wall.png"
    WL.render_wall(S5.TEXT, px, top, p)
    if bad := check_box(W, H, Image.open(p).getbbox()):
        raise SystemExit(f"текстволл вне безопасной зоны: {bad}")
    out.append((p, 0.0, L[0] + L[1]))
    return out, 0


def music(dest: Path, total: float, rng: random.Random) -> None:
    global MUSIC_RATE
    if MUSIC_RATE is None:
        MUSIC_RATE = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=sample_rate",
                                         "-of", "csv=p=0", str(S2.MUSIC)], capture_output=True, text=True).stdout.split()[0])
    off, p, vol = rng.uniform(0.0, 3.0), rng.uniform(0.97, 1.03), rng.uniform(0.85, 1.0)
    raw = dest.with_suffix(".raw.wav")
    S2.music_loop(raw, (total + 0.5) * p + off)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af",
                    f"atrim=start={off:.3f},asetpts=PTS-STARTPTS,asetrate={MUSIC_RATE * p:.0f},aresample={MUSIC_RATE},"
                    f"volume={vol:.3f},atrim=0:{total:.3f},afade=t=out:st={total - 0.35:.3f}:d=0.35",
                    str(dest)], check=True)
    raw.unlink()


def render(proj: int, r: dict, out: Path, tag: str) -> Path:
    rng = random.Random(r["seed"])
    name = f"skinive{proj}_{tag}_{r['n']:03d}"
    tmp = WORK / name
    tmp.mkdir(parents=True, exist_ok=True)
    sp, mir = r["speed"], r["mirror"]
    ct = rng.uniform(5200, 7600)
    grade = (f"eq=brightness={rng.uniform(-0.03, 0.04):.3f}:contrast={rng.uniform(0.95, 1.08):.3f}:"
             f"saturation={rng.uniform(0.95, 1.15):.3f}:gamma={rng.uniform(0.94, 1.06):.3f},"
             f"colortemperature=temperature={ct:.0f}:mix={rng.uniform(0.3, 0.7):.2f},"
             f"noise=alls={rng.randint(3, 8)}:allf=t")
    if rng.random() < 0.4:
        grade += f",vignette=angle={rng.uniform(0.35, 0.6):.2f}"
    inputs, parts, labels = [], [], []
    for x in (x for seg in r["segs"] for x in seg):
        src = FACE if x["src"] == "face" else LONG / f"{x['src']}.mp4"
        i = len(labels)
        inputs += ["-i", str(src)]
        parts.append(f"[{i}:v]trim=start={x['t']:.3f}:duration={x['len'] * sp + 0.05:.3f},setpts=(PTS-STARTPTS)/{sp:.4f},"
                     f"fps={FPS},{vf_geo(x['g'], mir)},trim=end_frame={round(x['len'] * FPS)},setpts=PTS-STARTPTS[s{i}]")
        labels.append(f"[s{i}]")
    total = round(sum(round(x["len"] * FPS) for seg in r["segs"] for x in seg) / FPS, 3)
    L = [sum(round(x["len"] * FPS) for x in seg) / FPS for seg in r["segs"]]
    t_end = L[0] + L[1]
    parts.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0,{grade}[b0]")
    texts, txt_bottom = text_layers(proj, rng, tmp, L, total)
    idx, cur = len(labels), "b0"
    for i, (png, a, b) in enumerate(texts):
        inputs += ["-i", str(png)]
        parts.append(f"[{cur}][{idx}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'[o{i}]")
        cur, idx = f"o{i}", idx + 1

    t_app = t_end + rng.uniform(0.05, 0.35)
    t_res = t_app + rng.uniform(0.6, 0.9)

    def place(card: Image.Image, top: int | None = None, bottom: int | None = None, jx: int = 0) -> tuple[int, int]:
        cw, chh = card.width - 2 * OV.SHADOW, card.height - 2 * OV.SHADOW
        x = (W - cw) // 2 + jx
        x = max(141, min(939 - cw, x))
        y = top if top is not None else bottom - chh
        if bad := check_box(W, H, (x, y, x + cw, y + chh)):
            raise SystemExit(f"{name}: карточка вне безопасной зоны: {bad}")
        return x - OV.SHADOW, y - OV.SHADOW

    def pop(src: str, label: str, x: int, y: int, t0: float, seq: bool) -> None:
        nonlocal cur
        dy = rng.choice((40, 30, -30))                    # выезд снизу или сверху
        dur = rng.uniform(0.15, 0.24)
        if seq:
            pre = (f"[{src}:v]format=rgba,tpad=stop_mode=clone:stop_duration={total:.3f},trim=duration={total - t0:.3f},"
                   f"setpts=PTS-STARTPTS+{t0:.3f}/TB,")
        else:
            pre = f"[{src}:v]format=rgba,trim=duration={total:.3f},"
        parts.append(f"{pre}fade=t=in:st={t0:.3f}:d={dur:.3f}:alpha=1[{label}]")
        parts.append(f"[{cur}][{label}]overlay=x={x}:y='{y}+{dy}*max(0,1-(t-{t0:.3f})/{dur:.3f})':"
                     f"enable='gte(t,{t0:.3f})':eof_action=pass[{label}o]")
        cur = f"{label}o"

    app = OV.app_card(r["theme"], rng.randrange(560, 682, 2))
    app_p = tmp / "app.png"
    app.save(app_p)
    ax, ay = place(app, bottom=rng.randint(1480 if proj == 3 else 1440, 1530), jx=rng.randint(-30, 30))
    inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(app_p)]
    pop(str(idx), "ap", ax, ay, t_app, False)
    idx += 1
    if r["card"] == "plate":
        card = OV.plate_card(proj, rng.randrange(700, 800, 2))
        res_top = (txt_bottom + rng.randint(30, 70)) if proj == 3 else rng.randint(240, 360)
        cp = tmp / "plate.png"
        card.save(cp)
        rx, ry = place(card, top=res_top, jx=rng.randint(-20, 20))
        inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(cp)]
        pop(str(idx), "rs", rx, ry, t_res, False)
    else:
        gw = rng.choice(GAUGE_W[proj])
        gd = OV.gauge_frames(proj, gw)
        g0 = Image.open(gd / "001.png")
        res_top = (txt_bottom + rng.randint(25, 50)) if proj == 3 else rng.randint(220, 250)
        rx, ry = place(g0, top=res_top, jx=rng.randint(-30, 30))
        inputs += ["-framerate", str(FPS), "-i", str(gd / "%03d.png")]
        pop(str(idx), "rs", rx, ry, t_res, True)
    idx += 1
    parts.append(f"[{cur}]format=yuv420p,trim=duration={total:.3f}[v]")
    mus = tmp / "music.wav"
    music(mus, total, rng)
    p1, p2 = rng.choice(POPS), rng.choice(POPS)
    pv = rng.uniform(0.4, 0.6)
    inputs += ["-i", str(mus), "-i", str(p1), "-i", str(p2)]
    parts.append(f"[{idx + 1}:a]volume={pv:.2f},adelay=delays={round(t_app * 1000)}:all=1[p1]")
    parts.append(f"[{idx + 2}:a]volume={pv:.2f},adelay=delays={round(t_res * 1000)}:all=1[p2]")
    parts.append(f"[{idx}:a][p1][p2]amix=inputs=3:normalize=0:duration=first,atrim=0:{total:.3f}[a]")
    dest = out / f"{name}_1.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
           "-t", f"{total:.3f}", *OV.enc_args(dest)]
    for attempt in range(3):                            # один ffmpeg однажды завис на минуты — таймаут и повтор
        try:
            subprocess.run(cmd, check=True, timeout=120)
            break
        except subprocess.TimeoutExpired:
            print(f"  {name}: ffmpeg завис, повтор {attempt + 1}", flush=True)
    else:
        raise RuntimeError(f"{name}: ffmpeg не справился за 3 попытки")
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proj", type=int, choices=(3, 6), required=True)
    ap.add_argument("-n", type=int, default=6)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--tag", default="test")
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--only", default="", help="номера через запятую")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "_work" / "skinive_uniq_test")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = plan(a.proj, a.seed)
    rows = [r for r in rows if r["tag"] == a.tag] if a.tag in ("tt", "yt") else rows[:a.n]
    if a.only:                                          # пересобрать отдельные номера (план тот же — seed)
        keep = {int(x) for x in a.only.split(",")}
        rows = [r for r in rows if r["n"] in keep]
    a.out.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    OV.app_card("dark")                                # кэш кадров стора/приложения и шкал — до потоков (без гонок)
    OV.plate_card(a.proj, 700)
    for gw in GAUGE_W[a.proj]:
        OV.gauge_frames(a.proj, gw)
    done = 0
    with ThreadPoolExecutor(a.jobs) as ex:
        for dest in ex.map(lambda r: render(a.proj, r, a.out, a.tag), rows):
            done += 1
            print(f"  [{done}/{len(rows)}] {dest.name}", flush=True)
    print(f"готово: {len(rows)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
