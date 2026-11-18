#!/usr/bin/env python3
"""
skinive_3 (ID 1), v3 — ещё 100 TikTok (юзер 2026-11-13: «в тт после правок в тень улетело меньше 50 % — давай ещё
пачку зауникалим на тикток 100… со схожестью добей до 0 %… дай тесты»; «очень важно, чтобы skinive 3 не был схож
со skinive 2»). Формат — как skinive3 v2 (build_skinive_uniq.py --proj 3): лицо → родинка → родинка крупно,
4 текста ТЗ сверху, карточка App Store всплывает и результат (плашка или шкала), музыка рефа + «поп».

Отличия v3:
  • кадр целиком собирает видеокарта (core/gpu_ffmpeg.py): обрезка/зум в распаковщике h264_cuvid, масштаб scale_cuda,
    склейка наложением (seq_overlay), слои и карточки — overlay_cuda, кодирование NVENC. Поворот/зеркало/eq/
    colortemperature/vignette/noise на видеокарте нет → «вид» ролика = RGBA-слой: свой оттенок, иногда виньетка,
    мягкие волны осветления ±5 % и ещё ±10 % (по ним ролики не «узнаются» друг в друге);
  • руки — только «c» (кружки маркером) и «a» (тату-рука); «p» (IMG_6281) — та же рука, что в skinive2, не берём;
  • приём по одному: ролик попадает в выдачу, только если НИ ОДНОГО общего кадра (3 к/с, dHash 16×16 ≤ 40, с
    зеркалом — как measure_skinive_uniq) ни с одним принятым, ни со всеми skinive3 (v1/v2, TT/YT), ни со всеми
    skinive2 (старые 300 + TT 100 v2). Повторных кругов нет.

  python build_skinive3_v3.py --test           # 6 проб → output/_work/skinive3_v3/test
  python build_skinive3_v3.py --probe 20       # замер: доля пар проб с общими кадрами
  python build_skinive3_v3.py -n 100 --jobs 4  # → output/skinive3_TT_100_v3 (skinive3_tt_NNN_1.mp4)
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import random
import subprocess
import sys
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_skinive_overlay as OV  # noqa: E402
import build_skinive_uniq as U  # noqa: E402
import measure_skinive_uniq as M  # noqa: E402
from core import gpu_ffmpeg as G  # noqa: E402
from core.gpu_slots import gpu_slot  # noqa: E402
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
WORK = ROOT / "output" / "_work" / "skinive3_v3"
OUT = ROOT / "output" / "skinive3_TT_100_v3"
OLD = [ROOT / "output" / d for d in ("skinive3_TT_150", "skinive3_YT_150", "skinive3_TT_150_v2", "skinive3_YT_150_v2",
                                     "skinive2_TT_100", "skinive2_YT_200", "skinive2_TT_100_v2")]
# руки — стабилизированные треки (make_skinive_long_tracks_stab.py; юзер 13.11 «почему рука дрожит»): дрожь участка
# с родинкой меньше на 18–57 %, окно — с точностью до долей пикселя
LONG_STAB = ROOT / "output" / "_work" / "skinive_overlay" / "long_stab"
# лицо — только отрезки без скачков: в исходнике монтажные склейки (6.07, 6.73, 11.87, 18.7, 24.8 с) и очень резкие
# движения головы (3.97/4.17, 10.6–10.9, у 29–34 с), которые в ролике выглядят как «срыв» (юзер 13.11). Порог —
# разница кадров > 14 при медиане 4 (output/_work/skinive3_v3/clean_spans.json, расчёт в истории сессии 13.11)
FACE_SPANS = [(7.5, 10.53), (12.25, 16.0), (18.75, 24.6), (34.0, 36.9)]
# рабочие отрезки рук — как build_skinive_uniq.MOLE_SPANS, но без резких рывков руки у краёв (замер 13.11:
# a1 4.73–5.03 с, a2 3.07–3.10 с — скачок окна 30–40 px за кадр, «срыв»)
MOLE_SPANS = {"c": [("c1", 0.0, 6.5)],
              "a": [("a1", 0.0, 3.1), ("a1", 5.15, 6.75), ("a2", 0.0, 2.95), ("a3", 0.0, 3.7)]}
LOCK = threading.Lock()                                # core.renderer (тексты) — не потокобезопасен
SHADE, SHADE_X = 0.05, 0.10                            # волны осветления: ±5 % и ещё ±10 %
U.ZOOM["face3"] = (1.12, 1.35)                         # лицо: шире зум, чем в v2 (1.08–1.25) — кадры лица реже совпадают со старыми


def candidate(rng: random.Random) -> dict:
    """Части ролика без «срывов» (юзер 13.11: «резкие срывы кадров одного и того же видео как-то не очень»):
      • лицо — ОДИН непрерывный кусок;
      • родинка → родинка крупно — одна непрерывная запись: крупный план идёт сразу следом по времени с наездом
        (читается как приближение); если запись коротка — крупный план из ДРУГОЙ записи руки, но никогда из той же
        записи в другой момент. Склейки только между частями. Руки — c/a (не p: она же в skinive2).
    Скорость 1 (иначе повторы/пропуски кадров), поворота/зеркала нет (на видеокарте их нет)."""
    rng.uniform(0.94, 1.06)                               # (бывшая скорость — вызов оставлен, чтобы не сдвигать случайности)
    sp = 1.0
    L = [round(rng.uniform(2.6, 3.2), 2), round(rng.uniform(2.6, 3.1), 2), round(rng.uniform(2.6, 3.2), 2)]
    a, b = rng.choice(FACE_SPANS)
    while b - a < L[0] + 0.05:
        a, b = rng.choice(FACE_SPANS)
    t = round(rng.uniform(a, b - L[0] - 0.05), 3)
    g = U.geo(rng, *U.ZOOM["face3"], None)
    g.update(ang=0.0, dx=max(-0.05, min(0.05, g["dx"])), dy=max(-0.05, min(0.05, g["dy"])))
    face = dict(src="face", t=t, len=L[0], g=g)
    grp = rng.choice(("c", "a"))
    spans = MOLE_SPANS[grp]
    whole = [sp_ for sp_ in spans if sp_[2] - sp_[1] >= L[1] + L[2] + 0.1]      # обе части подряд из одной записи
    g2 = U.geo(rng, *U.ZOOM[grp], rng.uniform(0.42, 0.62))
    g2["ang"] = 0.0
    rng.random()                                          # (бывший выбор «наезда» — вызов оставлен)
    if whole:
        # одна запись (c1) — вся часть с рукой ОДНИМ непрерывным куском, тот же кадр (без наезда-скачка, юзер 13.11)
        sid, a, b = rng.choice(whole)
        t2 = round(rng.uniform(a, b - L[1] - L[2] - 0.05), 3)
        t3, sid3 = round(t2 + L[1], 3), sid
        rng.uniform(1.18, 1.32)
        U.geo(rng, 1.2, 1.2, 0.55)
        g3 = dict(g2)
    else:
        sid, a, b = rng.choice([sp_ for sp_ in spans if sp_[2] - sp_[1] >= L[1] + 0.05])
        t2 = round(rng.uniform(a, b - L[1] - 0.05), 3)
        other = [sp_ for sp_ in spans if sp_[0] != sid and sp_[2] - sp_[1] >= L[2] + 0.05]
        if not other:                                     # другой записи нет — продолжение той же, тот же кадр
            L[2] = round(min(L[2], b - t2 - L[1] - 0.05), 2)
            sid3, t3 = sid, round(t2 + L[1], 3)
            g3 = dict(g2)
        else:                                             # другая запись руки — обычная монтажная склейка
            sid3, a3, b3 = rng.choice(other)
            t3 = round(rng.uniform(a3, b3 - L[2] - 0.05), 3)
            g3 = U.geo(rng, *U.ZOOM[grp], rng.uniform(0.53, 0.58))
    g3["ang"] = 0.0
    segs = [[face], [dict(src=sid, t=t2, len=L[1], g=g2)], [dict(src=sid3, t=t3, len=L[2], g=g3)]]
    return dict(speed=sp, segs=segs, L=[round(sum(x["len"] for x in s_), 3) for s_ in segs],
                card=rng.choice(("plate", "gauge")), theme=rng.choice(("dark", "dark", "light")),
                seed=rng.randrange(10 ** 9))


def crop_of(g: dict) -> tuple[int, int, int, int]:
    cw, ch = round(W / g["z"] / 2) * 2, round(H / g["z"] / 2) * 2
    x0 = min(max(0, round((W - cw) / 2 + g["dx"] * W)), W - cw) // 2 * 2
    y0 = min(max(0, round((H - ch) / 2 + g["dy"] * H)), H - ch) // 2 * 2
    return x0, y0, cw, ch


def look_png(rng: random.Random, dest: Path) -> None:
    """«Вид» ролика вместо eq/colortemperature/vignette (на видеокарте их нет): оттенок, иногда виньетка и мягкие
    волны осветления (белым/чёрным с прозрачностью) — у каждого ролика свои."""
    x = np.linspace(0, 1, W, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None]

    def wave() -> np.ndarray:
        ph = (rng.uniform(0, 6.28) + y * rng.uniform(-6, 6)
              + np.sin(y * rng.uniform(2, 5) + rng.uniform(0, 6.28)) * rng.uniform(0.5, 1.5))
        return (0.6 * np.sin(2 * math.pi * rng.uniform(1.2, 2.6) * x + ph)
                + 0.4 * np.sin(2 * math.pi * rng.uniform(2.5, 4.5) * x + ph * 1.7 + rng.uniform(0, 6.28)))

    v = wave() * SHADE + wave() * SHADE_X                 # >0 — темнее, <0 — светлее
    rgb = np.where(v[..., None] > 0, 0.0, 255.0) * np.ones((1, 1, 3), np.float32)
    a = np.abs(v)
    tint = np.array((255, 170, 90) if rng.random() < 0.5 else (90, 150, 255), np.float32)
    ta = rng.uniform(0.0, 0.06)                           # оттенок: тёплый/холодный
    rgb = (rgb * a[..., None] + tint * ta) / np.maximum(a + ta, 1e-6)[..., None]
    a = a + ta - a * ta
    if rng.random() < 0.4:                                # виньетка
        r2 = ((x - 0.5) / 0.5) ** 2 + ((y - 0.5) / 0.5) ** 2
        va = np.clip((r2 - 0.5) / 1.5, 0, 1) * rng.uniform(0.12, 0.25)
        rgb = (rgb * a[..., None]) * (1 - va[..., None]) / np.maximum(a + va - a * va, 1e-6)[..., None]
        a = a + va - a * va
    img = np.dstack([np.clip(rgb, 0, 255), np.clip(a * 255, 0, 255)]).astype(np.uint8)
    Image.fromarray(img, "RGBA").save(dest, compress_level=1)


FACE_X = 0.12                                          # доп. волны осветления на кадрах лица (замер 13.11)


def face_wave_png(rng: random.Random, dest: Path, amp: float) -> None:
    """Только волны осветления (без оттенка/виньетки) — ещё один слой на кадры лица."""
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


def card_seq(frames: list[Image.Image], dy: int, nd: int, dest: Path) -> tuple[int, int]:
    """Всплытие карточки заранее: кадры PNG (выезд на dy px + проявление за nd кадров; у шкалы — её анимация).
    Холст = карточка + ход выезда; возвращает (сдвиг холста по y относительно места карточки, число кадров)."""
    dest.mkdir(parents=True, exist_ok=True)
    cw, ch = frames[0].size
    cw2, ch2 = cw + cw % 2, ch + abs(dy) + (ch + abs(dy)) % 2
    top0 = min(0, dy)
    n = max(nd + 1, len(frames))
    for i in range(n):
        k = min(1.0, i / nd)
        f = frames[min(i, len(frames) - 1)]
        if k < 1:
            f = f.copy()
            f.putalpha(f.getchannel("A").point(lambda p, k=k: int(p * k)))
        can = Image.new("RGBA", (cw2, ch2), (0, 0, 0, 0))
        can.alpha_composite(f, (0, int(round(dy * (1 - k))) - top0))
        can.save(dest / f"{i:03d}.png", compress_level=1)
    return top0, n


def render(r: dict, dest: Path) -> Path:
    rng = random.Random(r["seed"])
    tmp = WORK / f"t_{dest.stem}"
    tmp.mkdir(parents=True, exist_ok=True)
    sp = r["speed"]
    shots = [x for seg in r["segs"] for x in seg]
    nfr = [round(x["len"] * FPS) for x in shots]
    nf = sum(nfr)
    total = nf / FPS
    L = [sum(round(x["len"] * FPS) for x in seg) / FPS for seg in r["segs"]]
    t_end = L[0] + L[1]

    # кадры видео: видеокарта распаковывает, режет и масштабирует (cuvid -crop/-resize), кадры — в обычную память;
    # время и склейка — обычные фильтры; на видеокарту — один раз, дальше слои overlay_cuda и NVENC. НЕ держать
    # распакованные кадры на видеокарте через trim/склейку: замер 13.11 — 89 % кадров чужие (фризы, лаги, зелёные)
    inputs, fc = [], []
    for i, x in enumerate(shots):
        src = U.FACE if x["src"] == "face" else LONG_STAB / f"{x['src']}.mp4"
        inputs += G.gpu_input(src, crop=crop_of(x["g"]), resize=(W, H))
        fc.append(f"[{i}:v]trim=start={x['t']:.3f}:duration={x['len'] * sp + 0.05:.3f},setpts=(PTS-STARTPTS)/{sp:.4f},"
                  f"fps={FPS},setsar=1,format=yuv420p,tpad=stop_mode=clone:stop={nfr[i] + 2},"
                  f"trim=end_frame={nfr[i]},setpts=PTS-STARTPTS[s{i}]")
    fc.append("".join(f"[s{i}]" for i in range(len(shots))) + f"concat=n={len(shots)}:v=1:a=0,hwupload_cuda[b0]")
    idx = len(shots)
    cur = "b0"

    def add_layer(png: Path, a0: int, n: int) -> None:
        nonlocal cur, idx
        inputs.extend(["-i", str(png)])
        fc.append(G.layer(idx, a0, n, f"l{idx}"))
        fc.append(f"[{cur}][l{idx}]overlay_cuda=0:0:eof_action=pass[o{idx}]")
        cur, idx = f"o{idx}", idx + 1

    look_png(rng, tmp / "look.png")
    add_layer(tmp / "look.png", 0, nf)
    if FACE_X > 0:                                         # лицо — то же видео, что в v2: ещё волны ±FACE_X только на нём
        n_face = sum(round(x["len"] * FPS) for x in r["segs"][0])
        face_wave_png(rng, tmp / "face.png", FACE_X)
        add_layer(tmp / "face.png", 0, n_face)
    with LOCK:
        texts, txt_bottom = U.text_layers(3, rng, tmp, L, total)
    for png, a, b in texts:
        a0, b0 = round(a * FPS), min(nf, round(b * FPS))
        add_layer(png, a0, max(1, b0 - a0))

    t_app = t_end + rng.uniform(0.05, 0.35)
    t_res = t_app + rng.uniform(0.6, 0.9)

    def place(card: Image.Image, top: int | None = None, bottom: int | None = None, jx: int = 0) -> tuple[int, int]:
        cw, chh = card.width - 2 * OV.SHADOW, card.height - 2 * OV.SHADOW
        x = max(141, min(939 - cw, (W - cw) // 2 + jx))
        y = top if top is not None else bottom - chh
        if bad := check_box(W, H, (x, y, x + cw, y + chh)):
            raise SystemExit(f"{dest.name}: карточка вне безопасной зоны: {bad}")
        return x - OV.SHADOW, y - OV.SHADOW

    def pop(frames: list[Image.Image], name: str, x: int, y: int, t0: float) -> None:
        nonlocal cur, idx
        dy = rng.choice((40, 30, -30))
        nd = max(3, round(rng.uniform(0.15, 0.24) * FPS))
        top0, _ = card_seq(frames, dy, nd, tmp / name)
        inputs.extend(["-framerate", str(FPS), "-i", str(tmp / name / "%03d.png")])
        f0 = round(t0 * FPS)
        fc.append(f"[{idx}:v]format=yuva420p,hwupload_cuda,setpts=PTS-STARTPTS+{f0}/{FPS}/TB[l{idx}]")
        fc.append(f"[{cur}][l{idx}]overlay_cuda={x // 2 * 2}:{(y + top0) // 2 * 2}[o{idx}]")
        cur, idx = f"o{idx}", idx + 1

    app = OV.app_card(r["theme"], rng.randrange(560, 682, 2))
    ax, ay = place(app, bottom=rng.randint(1480, 1530), jx=rng.randint(-30, 30))
    pop([app], "app", ax, ay, t_app)
    if r["card"] == "plate":
        card = OV.plate_card(3, rng.randrange(700, 800, 2))
        rx, ry = place(card, top=txt_bottom + rng.randint(30, 70), jx=rng.randint(-20, 20))
        pop([card], "res", rx, ry, t_res)
    else:
        gd = OV.gauge_frames(3, rng.choice(U.GAUGE_W[3]))
        gfr = [Image.open(p).convert("RGBA") for p in sorted(gd.glob("*.png"))]
        rx, ry = place(gfr[0], top=txt_bottom + rng.randint(25, 50), jx=rng.randint(-30, 30))
        pop(gfr, "res", rx, ry, t_res)
    vlab = cur

    mus = tmp / "music.wav"
    U.music(mus, total, rng)
    p1, p2 = rng.choice(U.POPS), rng.choice(U.POPS)
    pv = rng.uniform(0.4, 0.6)
    ai = idx
    inputs += ["-i", str(mus), "-i", str(p1), "-i", str(p2)]
    fc.append(f"[{ai + 1}:a]volume={pv:.2f},adelay=delays={round(t_app * 1000)}:all=1[p1]")
    fc.append(f"[{ai + 2}:a]volume={pv:.2f},adelay=delays={round(t_res * 1000)}:all=1[p2]")
    fc.append(f"[{ai}:a][p1][p2]amix=inputs=3:normalize=0:duration=first,atrim=0:{total:.3f}[a]")
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", f"[{vlab}]", "-map", "[a]",
           "-frames:v", str(nf), "-r", str(FPS), *G.NVENC, "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.3f}",
           *G.CLEAN, str(dest)]
    with gpu_slot():
        for attempt in range(2):
            try:
                subprocess.run(cmd, check=True, timeout=300)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                if attempt == 1:
                    raise
    for p in sorted(tmp.rglob("*"), reverse=True):
        p.rmdir() if p.is_dir() else p.unlink()
    tmp.rmdir()
    return dest


bad_frames = G.bad_frames                              # проверка каждого кадра — общая (core/gpu_ffmpeg.py)


# ---------------------------------------------------------------- похожесть: «банк» кадров и проверка одним махом
def bank_of(hs: list[np.ndarray]) -> np.ndarray:
    """Кадры всех роликов (и зеркальные) → матрица ±1 для быстрого Хэмминга через умножение матриц."""
    if not hs:
        return np.zeros((0, 256), np.float32)
    return np.concatenate([h.reshape(-1, 256) for h in hs]).astype(np.float32) * 2 - 1


def shares(h: np.ndarray, bank: np.ndarray) -> bool:
    """Есть ли у ролика h хоть один кадр (как есть или зеркальный) ближе 40 бит к любому кадру банка."""
    if not len(bank):
        return False
    q = h.reshape(-1, 256).astype(np.float32) * 2 - 1      # и прямые, и зеркальные кадры ролика
    for i in range(0, len(bank), 40000):
        d = (256 - q @ bank[i:i + 40000].T) / 2            # Хэмминг
        if (d <= M.THR).any():
            return True
    return False


def old_bank() -> np.ndarray:
    f = WORK / "old_hashes.pkl"
    files = [v for d in OLD if d.exists() for v in sorted(d.glob("*.mp4"))]
    cache = pickle.load(open(f, "rb")) if f.exists() else {}
    todo = [v for v in files if str(v) not in cache]
    if todo:
        print(f"хэши старых роликов: {len(todo)} …", flush=True)
        with ThreadPoolExecutor(8) as ex:
            for v, h in zip(todo, ex.map(M.hashes, todo)):
                cache[str(v)] = h
        WORK.mkdir(parents=True, exist_ok=True)
        pickle.dump(cache, open(f, "wb"))
    return bank_of([cache[str(v)] for v in files])


def accept_batch(a) -> int:
    import qa_batch as Q
    OUT.mkdir(parents=True, exist_ok=True)
    cand = WORK / "cand"
    cand.mkdir(parents=True, exist_ok=True)
    bank_old = old_bank()
    man_f = WORK / f"manifest_{OUT.name}.json"
    man = json.loads(man_f.read_text(encoding="utf-8")) if man_f.exists() else {}
    acc = {f.name: M.hashes(f) for f in sorted(OUT.glob("*.mp4"))}
    man = {k: v for k, v in man.items() if k in acc}
    bank_new = bank_of(list(acc.values()))
    rng = random.Random(a.seed + len(acc) * 7919)
    Q._state.update(done=len(acc), total=a.n)
    Q.tick("skinive3 v3: сборка с проверкой — принят только ролик без общих кадров со всеми")
    tried = rejected = 0

    def make(c: dict, tmp: Path):
        render(c, tmp)
        if bad := bad_frames(tmp):
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"пустые кадры {bad[:5]} — кандидат отброшен")
        return c, tmp, M.hashes(tmp)

    with ThreadPoolExecutor(a.jobs) as ex:
        live: set = set()
        while len(acc) < a.n or live:
            while len(live) < a.jobs and len(acc) + len(live) < a.n + a.jobs and len(acc) < a.n:
                tried += 1
                live.add(ex.submit(make, candidate(rng), cand / f"c{tried:04d}.mp4"))
            done, live = wait(live, return_when=FIRST_COMPLETED)
            for f in done:
                try:
                    c, tmp, h = f.result()
                except Exception as e:                       # noqa: BLE001
                    print("  ОШИБКА сборки кандидата:", e, flush=True)
                    continue
                if len(acc) >= a.n or shares(h, bank_new) or shares(h, bank_old):
                    rejected += 1
                    tmp.unlink(missing_ok=True)
                    continue
                name = f"skinive3_tt_{len(acc) + 1:03d}_1.mp4"
                tmp.replace(OUT / name)
                acc[name], man[name] = h, c
                bank_new = np.concatenate([bank_new, bank_of([h])])
                man_f.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
                Q.tick()
                print(f"  ✓ {name} (собрано {tried}, отсеяно {rejected})", flush=True)
    print(f"ИТОГ: {len(acc)} роликов → {OUT}; общих кадров нет ни между собой, ни со skinive3 v1/v2 и skinive2 "
          f"(по построению); собрано {tried}, отсеяно {rejected}")
    Q.PROG.unlink(missing_ok=True)
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=3301)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--probe", type=int, default=0)
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    OV.app_card("dark")                                    # кэш карточек — до потоков
    OV.app_card("light")
    OV.plate_card(3, 700)
    for gw in U.GAUGE_W[3]:
        OV.gauge_frames(3, gw)
    if a.test or a.probe:
        n = a.probe or 6
        d = WORK / ("probe" if a.probe else "test")
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.mp4"):
            f.unlink()
        rng = random.Random(a.seed + (99 if a.probe else 0))
        cs = [candidate(rng) for _ in range(n)]
        def one(ic):
            dst = d / f"skinive3_tt_test_{ic[0] + 1:03d}.mp4"
            c, r2 = ic[1], random.Random(a.seed + 7 * ic[0])
            for _ in range(6):                             # пустой/повторный кадр — другой вариант (как в партии)
                render(c, dst)
                if not bad_frames(dst):
                    return dst
                c = candidate(r2)
            raise RuntimeError(f"{dst.name}: пустые кадры 6 раз подряд")
        with ThreadPoolExecutor(a.jobs) as ex:
            fs = list(ex.map(one, enumerate(cs)))
        print(f"готово {len(fs)} → {d}")
        hs = [M.hashes(f) for f in fs]
        pairs = [(i, j) for i in range(n) for j in range(i + 1, n) if shares(hs[i], bank_of([hs[j]]))]
        bo = old_bank()
        vs_old = sum(shares(h, bo) for h in hs)
        print(f"пар проб с общими кадрами: {len(pairs)} из {n * (n - 1) // 2}; проб с общими кадрами со старыми "
              f"skinive3/skinive2: {vs_old} из {n}")
        return 0
    return accept_batch(a)


if __name__ == "__main__":
    raise SystemExit(main())
