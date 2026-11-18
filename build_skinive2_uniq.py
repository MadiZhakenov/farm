#!/usr/bin/env python3
"""
skinive_2 (ID 1), уникальная версия (юзер 2026-11-13: ролик youtube TkTSJoZLunA = skinive2_YT_200 — «+100 штук
уникальных по тому же 1 проценту»). Старые skinive2 почти одинаковые (16 сочетаний окно × зеркало × финал) — у многих
пар 100 % общих кадров. Формат тот же (build_skinive2.py, раскладка fit):
  родинка (та же рука IMG_6281, длинный трек p1) → App Store → фото родинки в редакторе → «Skinive AI verarbeitet…» →
  результат (шкала Gutartiger Nävus или «Geringes Risiko»); подпись ТЗ сверху весь ролик, «(Ersetzt keinen Hautarzt)»
  в последнюю секунду. У КАЖДОГО ролика своё (непрерывные случайные величины):
  • родинка: 1–2 шота из любого места трека p1 (0–12.7 с), зум 1.35–1.65, поворот ±1.8°, сдвиг, зеркало, скорость;
  • экраны приложения: масштаб 0.62–0.74 (было ровно 0.75), высота и сдвиг вбок, обрезка сверху, длины шагов;
  • подпись: кегль и высота; дисклеймер — в пустом месте последнего экрана с учётом масштаба;
  • цвет (eq: яркость/контраст/насыщенность/гамма, тёплый/холодный через gamma_r/gamma_b) и зерно по яркости;
  • звук: старт петли, тон/темп ±3 %, громкость.
Распаковка — на видеокарте (core.gpu_slots), кодирование NVENC, метаданные вычищены.

  python build_skinive2_uniq.py --test                 # 6 проб → output/_work/skinive2_uniq/test
  python build_skinive2_uniq.py -n 100 --tag tt --ver v3 --jobs 4   # → output/skinive2_TT_100_v3 (skinive2_tt_NNN_1.mp4):
                                                       #   кадр собирает видеокарта (render_gpu); --cpu — старая сборка;
                                                       #   принимается только ролик без общих кадров со всеми (1 проход)
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_skinive2 as S2  # noqa: E402
import build_skinive_uniq as U  # noqa: E402  (shot/geo/vf_geo/overlap/music, длинные треки родинок)
import build_skinive_walls as SW  # noqa: E402
from core import renderer as R  # noqa: E402
from core import gpu_ffmpeg as G  # noqa: E402
from core.gpu_slots import gpu_slot  # noqa: E402
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
WORK = ROOT / "output" / "_work" / "skinive2_uniq"
OUT = ROOT / "output" / "skinive2_TT_100_v2"           # задаётся в main(): skinive2_{TT|YT}_{n}_v{версия}
TAG = "tt"
RENDER = None                                          # render_gpu (по умолчанию) или render (--cpu)
MOLE_SPANS = [("p1", 0.0, 12.7)]                       # та же рука, что в skinive2 (IMG_6281), трек без маркера
# пустые места последнего экрана в координатах экрана (fit: y на экране = top + rel·scale; rel — от кропа 150)
TEXT_LOCK = threading.Lock()                           # core.renderer держит глобальное состояние шрифтов — текст по очереди
DISC_REL = {"gauge": (1412 - 470) / 0.75, "erg": (1168 - 470) / 0.75}


U.ZOOM["p2"] = (1.3, 1.85)                             # родинка: шире зум, чем в skinive_3 (все ролики — одна запись руки)
SHADE_AMP = 0.05                                       # мягкая неравномерность освещения: ±5 % яркости, свой рисунок
SHADE_INTRO = 0.12                                     # на руке (все ролики — одна запись руки) — ещё ±12 %: замер 13.11
                                                       # 16 проб: без неё 17 % пар с общими кадрами, с ней — 0 из 120


def shade_png(rng: random.Random, dest: Path, amp: float = SHADE_AMP) -> None:
    """Едва заметная неравномерность освещения со своим случайным рисунком (полосы-волны с плывущей фазой): в одних
    местах чуть светлее (белый с прозрачностью), в других чуть темнее (чёрный). Глазу — мягкий свет на экране,
    а у почти белых экранов приложения и тёмного редактора перепады яркости у каждого ролика свои — иначе по ним
    ролики «узнавались» друг в друге (замер 13.11: 15–60 % общих кадров у 6 проб без этого)."""
    import math
    import numpy as np
    x = np.linspace(0, 1, W, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    ph = (rng.uniform(0, 6.28) + y * rng.uniform(-6, 6)
          + np.sin(y * rng.uniform(2, 5) + rng.uniform(0, 6.28)) * rng.uniform(0.5, 1.5))
    v = (0.6 * np.sin(2 * math.pi * rng.uniform(1.2, 2.6) * x + ph)
         + 0.4 * np.sin(2 * math.pi * rng.uniform(2.5, 4.5) * x + ph * 1.7 + rng.uniform(0, 6.28)))
    img = np.zeros((H, W, 4), np.uint8)
    img[..., :3] = np.where(v < 0, 255, 0)[..., None]
    img[..., 3] = (np.abs(v) * amp * 255).astype(np.uint8)
    Image.fromarray(img, "RGBA").save(dest, compress_level=1)


PX = WORK / "proxy"
PROC_K = 20                                            # «Skinive AI verarbeitet…» 30.2 с записи → заготовка ×20 (1.51 с)
# отрезки записей для сборки на видеокарте: (из какой заготовки, от, до) — с запасом под случайный старт стора
SEGS = {"store_s": ("store", 7.9, 9.95), "photo_s": ("app", 45.80, 46.85), "gauge_s": ("app", 84.0, 87.85),
        "erg_s": ("app", 88.82, 89.36)}
# поля вокруг уменьшенного экрана — ровным цветом края экрана (на видеокарте нет «продолжения края»), замер 13.11
PAD = {"store": "0xFFFFFF", "photo": "0x231F22", "proc": "0xC7D7FF", "gauge": "0xF4F6FF", "erg": "0xEEF2FF"}
SRC_WH = {"store": (1206, 2622), "app": (886, 1920)}


def ensure_proxies() -> dict:
    """Один раз: записи стора и приложения (HEVC 60 к/с) → 30 к/с с частыми ключевыми кадрами, и кусок обработки
    PROC (30.2 с) — заранее ускоренным ×20. Раньше каждый ролик распаковывал ~1800 кадров обработки ради 1 секунды
    и перегонял их из памяти видеокарты — это и тормозило партию (замер 13.11)."""
    PX.mkdir(parents=True, exist_ok=True)
    out = {"store": PX / "store30.mp4", "app": PX / "app30.mp4", "proc": PX / "proc20.mp4"}
    enc = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "16", "-g", "15", "-an", "-map_metadata", "-1"]
    if not out["store"].exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-hwaccel", "cuda", "-i", str(SW.STORE), "-vf", "fps=30",
                        *enc, str(out["store"])], check=True)
    if not out["app"].exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-hwaccel", "cuda", "-i", str(SW.APP), "-vf", "fps=30",
                        *enc, str(out["app"])], check=True)
    for key, (src, t0, t1) in SEGS.items():                # короткие отрезки с нуля: на видеокарте вход с -ss не работает
        out[key] = PX / f"{key}_seg.mp4"
        if not out[key].exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t0), "-t", str(t1 - t0), "-i", str(out[src]),
                            *enc, str(out[key])], check=True)
    if not out["proc"].exists():
        p0, p1 = SW.PROC
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-hwaccel", "cuda", "-ss", str(p0), "-t", str(p1 - p0),
                        "-i", str(SW.APP), "-vf", f"setpts=(PTS-STARTPTS)/{PROC_K},fps=30", *enc, str(out["proc"])], check=True)
    return out


def geo6(rng: random.Random, zmin: float, zmax: float, target_y: float) -> dict:
    """Как build_skinive_uniq.geo, но поворот до ±6° (рука одна и та же у всех — нужен разный наклон),
    зум не меньше, чем нужно, чтобы после поворота не было чёрных углов."""
    import math
    ang = rng.uniform(-6.0, 6.0)
    a = math.radians(abs(ang))
    need = math.cos(a) + (H / W) * math.sin(a)
    z = rng.uniform(max(zmin, need * 1.04), max(zmax, need * 1.1))
    free = max(0.0, (1 - need / z) / 2)
    dx = rng.uniform(-free, free) * 0.85
    dy = max(-free, min(free, (0.5 - target_y) / z + rng.uniform(-0.015, 0.015)))
    return dict(z=z, ang=ang, dx=dx, dy=dy)


def candidate(rng: random.Random) -> dict:
    rng.uniform(0.9, 1.1)                                 # (бывшая скорость — вызов оставлен)
    sp = 1.0                                              # скорость ≠ 1 давала повторы/пропуски кадров («фризы»)
    t_mole = round(rng.uniform(2.7, 3.3), 2)
    taken: list = []
    rng.random()                                          # (бывший выбор нарезки — вызов оставлен, чтобы не сдвигать случайности)
    # рука — ОДИН непрерывный кусок (юзер 13.11: «резкие срывы кадров одного и того же видео как-то не очень»)
    shots = [U.shot(rng, MOLE_SPANS, t_mole, sp, taken, rng.uniform(0.56, 0.74), "p2")]
    for x in shots:                                        # свой наклон ±6° вместо ±1.8°
        x["g"] = geo6(rng, *U.ZOOM["p2"], rng.uniform(0.56, 0.74))
    end = rng.choice(("gauge", "erg"))
    c = dict(speed=sp, segs=[shots], L=[sum(x["len"] for x in shots)], mirror=rng.random() < 0.5, end=end,
             scale=round(rng.uniform(0.62, 0.74), 3), crop_dy=rng.randint(0, 30), xj=rng.uniform(-1, 1),
             yj=rng.random(), s0=round(rng.uniform(7.9, 8.5), 2), ph_len=round(rng.uniform(1.1, 1.5), 2),
             p_len=round(rng.uniform(0.9, 1.3), 2), r_len=round(rng.uniform(1.8, 2.4), 2),
             cap_k=round(rng.uniform(0.92, 1.0), 3), cap_top=rng.randint(204, 236), seed=rng.randrange(10 ** 9))
    # ровные скорости экранов (юзер 13.11 «фризит, лагает»): растяжка редактора фото 1.02 → 1.1–1.5 с повторяла кадры,
    # нецелое ускорение обработки/шкалы выкидывало кадры неравномерно. Теперь: фото — как есть, обработка — заготовка
    # ×20 как есть, шкала — ровно ×2 (каждый второй кадр); «Geringes Risiko» — статичный, держится сколько нужно
    ph0, ph1 = S2.PHOTO2
    p0, p1 = SW.PROC
    c["ph_len"] = round(ph1 - ph0, 3)
    c["p_len"] = round((p1 - p0) / PROC_K, 3)
    if end == "gauge":
        g0, g1 = SW.GAUGE
        c["r_len"] = round((g1 - g0) / 2, 3)
    return c


def plan(n: int, seed: int, tries: int = 30) -> list[dict]:
    f = WORK / f"plan_{n}_{seed}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    rng = random.Random(seed)
    rows: list = []
    for k in range(n):
        best = None
        for _ in range(tries):
            c = candidate(rng)
            sc = max((max(U.overlap(c, r), U.overlap(r, c)) for r in rows), default=0.0)
            if best is None or sc < best[0]:
                best = (sc, c)
        best[1].update(score=round(best[0], 3), n=k + 1)
        rows.append(best[1])
    WORK.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def caption(dest: Path, k: float, top: int) -> int:
    """Подпись ТЗ дословно (как в skinive2): белый TikTok-шрифт с ровной обводкой, кегль — автоподбор × k."""
    px = S2.CAP_PX
    while True:
        font, st = R._load_font(px), max(2, round(px * S2.STROKE))
        e_px = S2.A._emoji_px(px)
        widest = max(sum(e_px * 1.08 if t == "emoji" else font.getlength(c) for t, c in S2.A._tokenize_runs(ln) if c)
                     for ln in S2.CAPTION)
        if widest + 2 * st <= 790 or px <= 36:
            break
        px -= 1
    img = S2.outline_text(S2.CAPTION, max(36, round(px * k)), top)
    box = img.getbbox()
    if bad := check_box(W, H, box):
        raise SystemExit(f"подпись вне безопасной зоны: {bad}")
    img.save(dest)
    return box[3]


def render(r: dict, dest: Path) -> Path:
    rng = random.Random(r["seed"])
    tmp = WORK / f"t_{dest.stem}"
    tmp.mkdir(parents=True, exist_ok=True)
    sp = r["speed"]
    with TEXT_LOCK:
        cap_bottom = caption(tmp / "cap.png", r["cap_k"], r["cap_top"])
    s = r["scale"]
    fw, fh = round(W * s / 2) * 2, round(H * s / 2) * 2
    top_min = cap_bottom + 16
    # дисклеймер (36 px) должен остаться в безопасной зоне (низ ≤ 1540): ограничиваем, насколько низко опускать экран
    disc_rel = DISC_REL[r["end"]] - r["crop_dy"]
    top_max = min(H - fh, int(1540 - 50 - disc_rel * s))
    top = int(top_min + r["yj"] * max(0, top_max - top_min)) // 2 * 2
    side = (W - fw) // 2
    x0 = int(side + r["xj"] * min(70, side)) // 2 * 2
    disc_y = int(top + disc_rel * s)
    with TEXT_LOCK:
        disc = S2.outline_text([S2.DISCLAIMER], S2.DISC_PX, disc_y)
    if bad := check_box(W, H, disc.getbbox()):
        raise SystemExit(f"дисклеймер вне безопасной зоны: {bad}")
    disc.save(tmp / "disc.png")

    def app(crop_y: int, fill: str) -> str:
        cy = crop_y + r["crop_dy"]
        base = f"scale={W}:-2:flags=lanczos,crop={W}:{H}:0:{cy},scale={fw}:{fh}:flags=lanczos,"
        if fill == "white":
            return base + f"pad={W}:{H}:{x0}:{top}:color=white,setsar=1"
        # низ — ровным цветом (продолжение нижней строки экрана давало вертикальные полосы под «Geringes Risiko»),
        # верх и бока — продолжение края экрана; редактор фото тёмный, остальные экраны светлые
        col = "0x101010" if fill == "dark" else "0xF7F8FC"
        return (base + f"pad={W}:{H}:{x0}:{top}:color={col},format=yuv444p,"
                f"fillborders=left={x0}:right={W - fw - x0}:top={top}:mode=smear,format=yuv420p,setsar=1")

    s0 = r["s0"]
    s_len = SW.STORE_END - s0
    ph0, ph1 = S2.PHOTO2
    p0, p1 = SW.PROC
    r0, r1 = SW.GAUGE if r["end"] == "gauge" else SW.ERG
    p_speed = (p1 - p0) / r["p_len"]
    r_speed = (r1 - r0) / r["r_len"] if r["end"] == "gauge" else 1.0
    r_hold = max(0.0, r["r_len"] - (r1 - r0) / r_speed)
    nres = round(r["r_len"] * FPS)
    nph = round(r["ph_len"] * FPS)
    shots = r["segs"][0]
    n_mole = sum(round(x["len"] * FPS) for x in shots)
    nf = n_mole + round(s_len * FPS) + nph + round(r["p_len"] * FPS) + nres
    total = nf / FPS
    warm = rng.uniform(-0.05, 0.05)
    grade = (f"eq=brightness={rng.uniform(-0.03, 0.04):.3f}:contrast={rng.uniform(0.95, 1.08):.3f}:"
             f"saturation={rng.uniform(0.95, 1.15):.3f}:gamma={rng.uniform(0.94, 1.06):.3f}:"
             f"gamma_r={1 + warm:.3f}:gamma_b={1 - warm:.3f},noise=c0s={rng.randint(3, 8)}:c0f=t")

    with gpu_slot() as hw:
        inputs, fc, labels = [], [], []
        for i, x in enumerate(shots):
            inputs += [*hw, "-i", str(U.LONG / f"{x['src']}.mp4")]
            fc.append(f"[{i}:v]trim=start={x['t']:.3f}:duration={x['len'] * sp + 0.05:.3f},setpts=(PTS-STARTPTS)/{sp:.4f},"
                      f"fps={FPS},{U.vf_geo(x['g'], r['mirror'])},trim=end_frame={round(x['len'] * FPS)},"
                      f"setpts=PTS-STARTPTS[m{i}]")
            labels.append(f"[m{i}]")
        k = len(shots)
        PXS = ensure_proxies()
        inputs += [*hw, "-ss", f"{s0 - 1:.3f}", "-i", str(PXS["store"]), *hw, "-ss", f"{ph0 - 1:.3f}", "-i", str(PXS["app"]),
                   *hw, "-i", str(PXS["proc"]), *hw, "-ss", str(r0 - 1), "-i", str(PXS["app"])]
        fc += [f"[{k}:v]trim=start=1:duration={s_len:.3f},setpts=PTS-STARTPTS,fps={FPS},{app(150, 'white')},"
               f"trim=end_frame={round(s_len * FPS)}[s]",
               f"[{k + 1}:v]trim=start=1:duration={ph1 - ph0:.3f},setpts={r['ph_len'] / (ph1 - ph0):.4f}*(PTS-STARTPTS),"
               f"fps={FPS},{app(160, 'dark')},tpad=stop_mode=clone:stop=3,trim=end_frame={nph},setpts=PTS-STARTPTS[ph]",
               f"[{k + 2}:v]trim=start=0:duration={(p1 - p0) / PROC_K:.3f},setpts=(PTS-STARTPTS)/{p_speed / PROC_K:.4f},fps={FPS},"
               f"{app(150, 'smear')},tpad=stop_mode=clone:stop=3,trim=end_frame={round(r['p_len'] * FPS)},setpts=PTS-STARTPTS[p]",
               f"[{k + 3}:v]trim=start=1:duration={r1 - r0:.3f},setpts=(PTS-STARTPTS)/{r_speed:.4f},fps={FPS},"
               f"tpad=stop_mode=clone:stop_duration={r_hold + 0.2:.3f},{app(150, 'smear')},"
               f"trim=end_frame={nres},setpts=PTS-STARTPTS[r]",
               "".join(labels) + f"[s][ph][p][r]concat=n={k + 4}:v=1:a=0,{grade}[b0]",
               # слои — по одному разу распакованная картинка (loop-фильтр, не «-loop 1», который распаковывает PNG на
               # каждом кадре и грузит процессор); подпись + осветление склеены заранее: на руке — свой слой с ±12 %
               f"[{k + 4}:v]loop=loop={nf}:size=1:start=0,settb=1/{FPS},setpts=N[la]",
               f"[{k + 7}:v]loop=loop={nf}:size=1:start=0,settb=1/{FPS},setpts=N[lb]",
               f"[{k + 5}:v]loop=loop={nf}:size=1:start=0,settb=1/{FPS},setpts=N[ld]",
               f"[b0][lb]overlay=0:0:enable='lt(t,{n_mole / FPS:.3f})'[b1]",
               f"[b1][la]overlay=0:0:enable='gte(t,{n_mole / FPS:.3f})'[b2]",
               f"[b2][ld]overlay=0:0:enable='gte(t,{total - 1.0:.3f})',format=yuv420p[v]"]
        mus = tmp / "music.wav"
        U.music(mus, total, rng)
        shade_png(rng, tmp / "shade.png")
        shade_png(rng, tmp / "shade_i.png", SHADE_INTRO)
        cap = Image.open(tmp / "cap.png")
        sh = Image.open(tmp / "shade.png")
        main_l = Image.alpha_composite(sh, cap)                        # экраны: осветление ±5 % + подпись
        intro_l = Image.alpha_composite(Image.alpha_composite(sh, Image.open(tmp / "shade_i.png")), cap)
        main_l.save(tmp / "layer_main.png", compress_level=1)
        intro_l.save(tmp / "layer_intro.png", compress_level=1)
        inputs += ["-i", str(tmp / "layer_main.png"), "-i", str(tmp / "disc.png"), "-i", str(mus),
                   "-i", str(tmp / "layer_intro.png")]
        cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
                        "-map", "[v]", "-map", f"{k + 6}:a", "-t", f"{total:.3f}", "-r", str(FPS),
                        "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                        "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                        "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                        "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                        "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)]
        for attempt in range(3):                       # временная ошибка видеокарты (занята другой сборкой) — повтор,
            try:                                       # в последний раз — распаковка на процессоре
                subprocess.run(cmd, check=True, timeout=300)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                if attempt == 2:
                    raise
                if attempt == 1:
                    cmd = [c for i, c in enumerate(cmd) if not (c == "-hwaccel" or (i and cmd[i - 1] == "-hwaccel"))]
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    return dest


def render_gpu(r: dict, dest: Path) -> Path:
    """То же, что render(), но кадр собирает видеокарта (юзер 13.11: «переведи на видюху»):
      • экраны приложения: распаковка с обрезкой (h264_cuvid -crop), масштаб в yuv420p (scale_cuda — только вместе с
        настоящим изменением размера: «тот же размер + format» в нашем ffmpeg даёт зелёный кадр), поля pad_cuda ровным
        цветом края экрана;
      • склейка — не concat (на видеокарте не работает), а наложение overlay_cuda каждого куска с его момента
        (setpts +старт) поверх основы, eof_action=pass;
      • подпись/осветление/дисклеймер — RGBA-слои, распакованы один раз, загружены в видеокарту (yuva420p на yuv420p);
      • процессор: только ~90 кадров руки (поворот ±6° и зеркало — на видеокарте таких фильтров нет);
      • цвет eq и зерно убраны (на видеокарте их нет; похожесть держат осветление-волны и раскладка)."""
    rng = random.Random(r["seed"])
    tmp = WORK / f"t_{dest.stem}"
    tmp.mkdir(parents=True, exist_ok=True)
    sp = r["speed"]
    PXS = ensure_proxies()
    with TEXT_LOCK:
        cap_bottom = caption(tmp / "cap.png", r["cap_k"], r["cap_top"])
    s = r["scale"]
    fw, fh = round(W * s / 2) * 2, round(H * s / 2) * 2
    top_min = cap_bottom + 16
    disc_rel = DISC_REL[r["end"]] - r["crop_dy"]
    top_max = min(H - fh, int(1540 - 50 - disc_rel * s))
    top = int(top_min + r["yj"] * max(0, top_max - top_min)) // 2 * 2
    side = (W - fw) // 2
    x0 = int(side + r["xj"] * min(70, side)) // 2 * 2
    with TEXT_LOCK:
        disc = S2.outline_text([S2.DISCLAIMER], S2.DISC_PX, int(top + disc_rel * s))
    if bad := check_box(W, H, disc.getbbox()):
        raise SystemExit(f"дисклеймер вне безопасной зоны: {bad}")
    disc.save(tmp / "disc.png")

    s0 = r["s0"]
    s_len = SW.STORE_END - s0
    ph0, ph1 = S2.PHOTO2
    p0, p1 = SW.PROC
    end = r["end"]
    r0, r1 = SW.GAUGE if end == "gauge" else SW.ERG
    p_speed = (p1 - p0) / r["p_len"]
    r_speed = (r1 - r0) / r["r_len"] if end == "gauge" else 1.0
    shots = r["segs"][0]
    n_mole = sum(round(x["len"] * FPS) for x in shots)
    n_s, n_ph, n_p, n_r = round(s_len * FPS), round(r["ph_len"] * FPS), round(r["p_len"] * FPS), round(r["r_len"] * FPS)
    nf = n_mole + n_s + n_ph + n_p + n_r
    total = nf / FPS

    def cuvid(src: Path, kind: str, crop_y: int) -> list:
        """Экран приложения: видеокарта распаковывает, режет и сразу уменьшает до fw×fh; кадры — в обычную память
        (на видеокарте их держать нельзя — замер 13.11: чужие/пустые кадры)."""
        sw_, sh_ = SRC_WH[kind]
        f = sw_ / W
        y0 = round((crop_y + r["crop_dy"]) * f / 2) * 2
        hs = round(H * f / 2) * 2
        return G.gpu_input(src, crop=(0, y0, sw_, hs), resize=(fw, fh))

    inputs, fc, labels = [], [], []
    for i, x in enumerate(shots):                          # рука: процессор, только эти ~90 кадров
        inputs += ["-hwaccel", "cuda", "-i", str(U.LONG / f"{x['src']}.mp4")]
        fc.append(f"[{i}:v]trim=start={x['t']:.3f}:duration={x['len'] * sp + 0.05:.3f},setpts=(PTS-STARTPTS)/{sp:.4f},"
                  f"fps={FPS},{U.vf_geo(x['g'], r['mirror']).replace('flags=lanczos', 'flags=bilinear')},"
                  f"trim=end_frame={round(x['len'] * FPS)},setpts=PTS-STARTPTS[m{i}]")
        labels.append(f"[m{i}]")
    k = len(shots)
    fc.append("".join(labels) + f"concat=n={k}:v=1:a=0,format=yuv420p,setsar=1[intro]")
    inputs += (cuvid(PXS["store_s"], "store", 150) + cuvid(PXS["photo_s"], "app", 160)
               + cuvid(PXS["proc"], "app", 150) + cuvid(PXS[f"{end}_s"], "app", 150))
    geo_ = f"format=yuv420p,pad={W}:{H}:{x0}:{top}:color="
    starts = [n_mole, n_mole + n_s, n_mole + n_s + n_ph, n_mole + n_s + n_ph + n_p]
    rr0 = SEGS[f"{end}_s"][1]
    steps = [
        (f"trim=start={s0 - SEGS['store_s'][1]:.3f}:duration={s_len:.3f},setpts=PTS-STARTPTS,fps={FPS},", "store", n_s),
        (f"trim=start={ph0 - SEGS['photo_s'][1]:.3f}:duration={ph1 - ph0:.3f},"
         f"setpts={r['ph_len'] / (ph1 - ph0):.4f}*(PTS-STARTPTS),fps={FPS},", "photo", n_ph),
        (f"trim=duration={(p1 - p0) / PROC_K:.3f},setpts=(PTS-STARTPTS)/{p_speed / PROC_K:.4f},fps={FPS},", "proc", n_p),
        (f"trim=start={r0 - rr0:.3f}:duration={r1 - r0:.3f},setpts=(PTS-STARTPTS)/{r_speed:.4f},fps={FPS},", end, n_r),
    ]
    for j, (head, kind, n) in enumerate(steps):
        fc.append(f"[{k + j}:v]{head}{geo_}{PAD[kind]},setsar=1,tpad=stop_mode=clone:stop={n + 2},trim=end_frame={n},"
                  f"setpts=PTS-STARTPTS[s{j}]")
    fc.append("[intro]" + "".join(f"[s{j}]" for j in range(len(steps))) +
              f"concat=n={len(steps) + 1}:v=1:a=0,hwupload_cuda[base]")
    cur = "base"
    # слои: осветление ±5 % + подпись на экранах, на руке — ещё ±12 %; дисклеймер — последняя секунда
    shade_png(rng, tmp / "shade.png")
    shade_png(rng, tmp / "shade_i.png", SHADE_INTRO)
    cap, sh = Image.open(tmp / "cap.png"), Image.open(tmp / "shade.png")
    Image.alpha_composite(sh, cap).save(tmp / "layer_main.png", compress_level=1)
    Image.alpha_composite(Image.alpha_composite(sh, Image.open(tmp / "shade_i.png")), cap).save(
        tmp / "layer_intro.png", compress_level=1)
    li = k + 4
    inputs += ["-i", str(tmp / "layer_intro.png"), "-i", str(tmp / "layer_main.png"), "-i", str(tmp / "disc.png")]
    for j, (a0, n) in enumerate(((0, n_mole), (n_mole, nf - n_mole), (nf - FPS, FPS))):
        out_l = "v" if j == 2 else f"o{j}"
        fc.append(f"[{li + j}:v]loop=loop={n - 1}:size=1:start=0,settb=1/{FPS},setpts=N+{a0},format=yuva420p,"
                  f"hwupload_cuda[l{j}]")
        fc.append(f"[{cur}][l{j}]overlay_cuda=0:0:eof_action=pass[{out_l}]")
        cur = out_l
    mus = tmp / "music.wav"
    U.music(mus, total, rng)
    inputs += ["-i", str(mus)]
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
           "-map", "[v]", "-map", f"{li + 3}:a", "-frames:v", str(nf), "-r", str(FPS),
           *G.NVENC, "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.3f}", "-map_metadata", "-1", "-fflags", "+bitexact",
           "-flags:v", "+bitexact", "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0",
           "handler_name=", "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)]
    with gpu_slot():
        for attempt in range(2):
            try:
                subprocess.run(cmd, check=True, timeout=300)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                if attempt == 1:
                    raise
    for f_ in tmp.iterdir():
        f_.unlink()
    tmp.rmdir()
    return dest


def accept_batch(a) -> int:
    """Один проход с гарантией: кандидат собирается во временную папку, хэшируется (как measure_skinive_uniq: 3 к/с,
    dHash 16×16, ≤ 40 бит, с зеркалом) и попадает в выдачу, только если НИ ОДНОГО общего кадра нет ни с одним уже
    принятым роликом и ни с одним из старых skinive2 (300). Иначе — сразу следующий кандидат. Похожих пар в выдаче
    не может быть по построению — повторных кругов нет."""
    import pickle
    from concurrent.futures import FIRST_COMPLETED, wait
    import measure_skinive_uniq as M
    import qa_batch as Q

    def sim(x, y) -> float:
        return max(M.match(x, y), M.match(y, x))

    OUT.mkdir(parents=True, exist_ok=True)
    cand_dir = WORK / "cand"
    cand_dir.mkdir(parents=True, exist_ok=True)
    # старые: все skinive2 (вкл. прошлую сборку TT_100_v2 из draft) и все skinive3 (v1/v2/v3) — юзер 13.11: skinive 3
    # не должен быть похож на skinive 2 (и наоборот); кэш хэшей по файлам
    old_dirs = [ROOT / "output" / d for d in ("skinive2_TT_100", "skinive2_YT_200", "skinive3_TT_150", "skinive3_YT_150",
                                             "skinive3_TT_150_v2", "skinive3_YT_150_v2", "skinive3_TT_100_v3")]
    old_dirs += [d for d in (WORK / "draft").glob("*") if d.is_dir()]
    files = [v for d in old_dirs if d.exists() and d.resolve() != OUT.resolve() for v in sorted(d.glob("*.mp4"))]
    cache_f = WORK / "old_hashes_by_file.pkl"
    cache = pickle.load(open(cache_f, "rb")) if cache_f.exists() else {}
    todo = [v for v in files if str(v) not in cache]
    if todo:
        print(f"хэши старых роликов: {len(todo)} …", flush=True)
        with ThreadPoolExecutor(8) as ex:
            for v, h in zip(todo, ex.map(M.hashes, todo)):
                cache[str(v)] = h
        pickle.dump(cache, open(cache_f, "wb"))
    HO = [cache[str(v)] for v in files]
    print(f"старых роликов в проверке: {len(HO)}", flush=True)
    import build_skinive3_v3 as V3
    bank_old = V3.bank_of(HO)
    man_f = WORK / f"manifest_{OUT.name}.json"
    man = json.loads(man_f.read_text(encoding="utf-8")) if man_f.exists() else {}
    acc = {f.name: M.hashes(f) for f in sorted(OUT.glob("*.mp4"))}          # продолжение после остановки
    bank_new = V3.bank_of(list(acc.values()))
    man = {k: v for k, v in man.items() if k in acc}
    rng = random.Random(a.seed + len(acc) * 7919)
    Q._state.update(done=len(acc), total=a.n)
    Q.tick("skinive2: сборка с проверкой — принят только ролик без общих кадров со всеми")
    tried = rejected = 0

    def make(c: dict, tmp: Path):
        RENDER(c, tmp)
        if bad := G.bad_frames(tmp):                       # пустой кадр видеокарты или повтор — не принимаем
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"пустые/повторные кадры {bad[:5]} — кандидат отброшен")
        return c, tmp, M.hashes(tmp)

    def new_candidate() -> dict:
        best = None
        rows = list(man.values())
        for _ in range(12):                                   # из 12 — самый непохожий по плану на принятые
            c = candidate(rng)
            sc = max((max(U.overlap(c, r), U.overlap(r, c)) for r in rows), default=0.0)
            if best is None or sc < best[0]:
                best = (sc, c)
        return best[1]

    with ThreadPoolExecutor(a.jobs) as ex:
        live = set()
        while len(acc) < a.n or live:
            while len(acc) + len(live) < a.n + a.jobs and len(live) < a.jobs and len(acc) < a.n:
                tried += 1
                live.add(ex.submit(make, new_candidate(), cand_dir / f"c{tried:04d}.mp4"))
            done, live = wait(live, return_when=FIRST_COMPLETED)
            for f in done:
                try:
                    c, tmp, h = f.result()
                except Exception as e:                       # noqa: BLE001
                    print("  ОШИБКА сборки кандидата:", e, flush=True)
                    continue
                if len(acc) >= a.n or V3.shares(h, bank_new) or V3.shares(h, bank_old):   # проверка одним махом (умножение матриц)
                    rejected += 1
                    tmp.unlink(missing_ok=True)
                    continue
                name = f"skinive2_{TAG}_{len(acc) + 1:03d}_1.mp4"
                tmp.replace(OUT / name)
                c["n"] = len(acc) + 1
                acc[name], man[name] = h, c
                bank_new = np.concatenate([bank_new, V3.bank_of([h])])
                man_f.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
                Q.tick()
                print(f"  ✓ {name} (собрано {tried}, отсеяно {rejected})", flush=True)
    names = sorted(acc)
    worst = max((sim(acc[x], acc[y]) for i, x in enumerate(names) for y in names[i + 1:]), default=0.0)
    worst_old = max((sim(acc[x], o) for x in names for o in HO), default=0.0)
    print(f"ИТОГ: {len(acc)} роликов → {OUT}; худшая пара между новыми {worst * 100:.1f} %, "
          f"худшая со старыми skinive2 {worst_old * 100:.1f} %; собрано кандидатов {tried}, отсеяно {rejected}")
    Q.PROG.unlink(missing_ok=True)
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=2201)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--probe", type=int, default=0, help="замер: N кандидатов → доля пар с общими кадрами")
    ap.add_argument("--tag", choices=("tt", "yt"), default="tt")
    ap.add_argument("--ver", default="v2", help="суффикс папки: skinive2_TT_100_v2 уже сдана — новой партии v3 и т.д.")
    ap.add_argument("--cpu", action="store_true", help="старая сборка кадра на процессоре (render)")
    a = ap.parse_args()
    global OUT, TAG, RENDER
    TAG = a.tag
    OUT = ROOT / "output" / f"skinive2_{a.tag.upper()}_{a.n}_{a.ver}"
    RENDER = render if a.cpu else render_gpu
    if a.probe:
        import measure_skinive_uniq as M
        d = WORK / "probe"
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.mp4"):
            f.unlink()
        rng = random.Random(a.seed + 99)
        cs = [candidate(rng) for _ in range(a.probe)]
        with ThreadPoolExecutor(a.jobs) as ex:
            fs = list(ex.map(lambda ic: RENDER(ic[1], d / f"p{ic[0]:03d}.mp4"), enumerate(cs)))
        with ThreadPoolExecutor(6) as ex:
            hs = list(ex.map(M.hashes, fs))
        pairs = [(i, j, max(M.match(hs[i], hs[j]), M.match(hs[j], hs[i]))) for i in range(len(hs)) for j in range(i + 1, len(hs))]
        hit = [p for p in pairs if p[2] > 0]
        print(f"замер: {len(fs)} кандидатов, пар {len(pairs)}, с общими кадрами {len(hit)} "
              f"({100 * len(hit) / len(pairs):.2f} %): {[(i, j, round(m * 100, 1)) for i, j, m in hit][:12]}")
        return 0
    ensure_proxies()
    if not a.test:
        return accept_batch(a)
    rows = plan(6, a.seed)
    out = WORK / "test"
    out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(a.jobs) as ex:
        for d in ex.map(lambda r: RENDER(r, out / f"skinive2_{TAG}_{r['n']:03d}_1.mp4"), rows):
            print(" ", d.name, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
