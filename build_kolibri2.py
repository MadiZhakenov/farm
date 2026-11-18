#!/usr/bin/env python3
"""
Колибри 2 (Idle Bank Tycoon, ID 1), B3 «Movie scene vs the actual game» (реф TikTok @realbigc 7688329616204795149):
  начало — трейлерная нарезка самых эффектных планов одного фильма (3–5 планов, каждый на пике: взрыв, луч, удар, портал;
  без оружия, крови, лиц-разговоров, титров), кадр 1:1 на чёрном, звук — эпичный (трек рефа или родной звук сцены) →
  жёсткая склейка на ударе → спокойная реальная игра (сырые записи Idle Bank Tycoon из Колибри 1) и финал с деньгами / новым банком,
  звук игры. Тексты ТЗ дословно на белых плашках; в конце «…and i still can't put it down». TikTok ≤ 9 с, YouTube 10–12 с.
Планы — из make_kolibri2_shots.py, окна каждого плана проверены покадрово (make_kolibri2_montage_ok.py → montage_ok.json:
ни одного кадра соседней сцены). Игра — только куски, где каждый кадр прошёл детектор (make_kolibri2_gamecheck.py →
game_pool.json: вид мира с BOOST, без Пункта управления iPhone, окон, панелей); готовый ролик проверяется ещё раз
покадрово (qa): не прошёл → output/_work/kolibri2/qa_failed, а не в выдачу.

  python build_kolibri2.py --test --out output/kolibri2_test3
  python build_kolibri2.py --tag tt -n 100 --out output/kolibri2_TT_100
  python build_kolibri2.py --tag yt -n 200 --out output/kolibri2_YT_200
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_calibri_reels as K  # noqa: E402  (сырые записи игры, библиотека окон, финалы, crop)
import build_drops_beats_reels as DB  # noqa: E402  (plate — белая TikTok-плашка с эмодзи)
import make_kolibri2_gamecheck as G  # noqa: E402  (покадровый детектор чистой игры)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
MOV = ROOT / "downloads" / "calibri2" / "movies"
REF_SOUND = ROOT / "downloads" / "calibri2" / "ref" / "ref_sound.mp3"
REF_HITS = {"tt": 4.14, "yt": 4.85}           # сильные доли трека рефа: склейка на игру ровно на ударе (старт трека 0.09)
REF_T0 = 0.09
BAND = 1080                                   # кадр фильма 1:1 → 1080×1080
BAND_Y = 545
HOOK_CY, END_CY = 448, 668                    # хук над кадром фильма; на игре — ниже плашек заданий, выше панели улучшений
END_LEN = 1.8
# трейлерные нарезки: (название, видео, [(старт, длина)]) — планы на пике действия, последний — самый сильный удар
MONTAGES = [
    ("endgame", "4WGMhicoCa8", [(96.9, 1.3), (53.7, 1.0), (197.4, 0.8), (198.5, 1.5)]),
    ("godzilla", "cgLbRQK_Rg4", [(26.7, 1.0), (84.6, 1.2), (88.5, 0.9), (163.8, 1.3), (165.3, 1.4)]),
    ("kong", "cgLbRQK_Rg4", [(4.0, 1.4), (36.8, 1.0), (195.5, 1.1), (167.9, 1.5)]),
    ("jaeger", "fRKviUgMP4o", [(38.2, 0.7), (81.3, 0.9), (130.3, 0.7), (131.0, 1.6), (169.8, 0.7)]),
    ("highway", "ET9SHYzMz_4", [(41.0, 1.3), (45.9, 1.3), (57.0, 0.6), (68.0, 1.3), (100.2, 1.5)]),
    ("robots", "ET9SHYzMz_4", [(175.4, 1.2), (190.6, 1.0), (208.5, 1.2), (209.8, 1.5)]),
    ("hulk", "ooOSFvBa55w", [(46.0, 1.3), (51.3, 0.6), (63.5, 0.8), (72.2, 1.0), (99.8, 1.2), (104.4, 0.7), (130.1, 1.2), (177.4, 1.0)]),
    ("fury_road", "jBRN0NLZ4HI", [(198.7, 1.4), (111.6, 0.6), (115.2, 1.4), (200.3, 1.6)]),
    ("mirror", "pjl3XN_HIdA", [(85.1, 1.4), (106.9, 1.0), (113.8, 1.3), (119.6, 1.3), (124.8, 1.6)]),
    ("inception", "BhF7G3EDtzs", [(165.2, 1.0), (183.4, 1.1), (324.3, 1.6), (187.8, 1.4), (177.3, 1.5)]),
    ("man_of_steel", "bwe1vu1L2k0", [(59.9, 0.8), (61.8, 1.1), (77.0, 0.9), (81.2, 1.2), (90.9, 1.3)]),
]
CONCEPTS = [
    ("pov: mobile game ads\nvs the actual gameplay", None),
    ("the ad:", "the game:"),
    ("what the ad promised\nvs what i got 😭", None),
]
ENDING = "…and i still can't put it down"
GAME_SPEED = 1.25                             # «спокойная реальная игра»: почти реальная скорость


def cut_shots(shots: list[tuple[float, float]], length: float, rng: random.Random) -> list[tuple[float, float]]:
    """Нарезка длиной length из проверенных окон (старт, макс. длина) из montage_ok.json: каждый план внутри своей сцены
    (≥ 0,45 с, ≤ своего окна), лишние средние планы выкидываются, последний (самый сильный удар) остаётся; сдвиг старта —
    только внутри окна."""
    sel = list(shots)
    frames_of = lambda xs: sum(int(m * FPS) for _, m in xs)               # noqa: E731
    while len(sel) > 3 and (len(sel) > 5 or length / sum(m for _, m in sel) < 0.55):          # ≤ 5 планов, каждый ≥ ~55 % окна
        j = len(sel) // 2
        if frames_of(sel[:j] + sel[j + 1:]) < round(length * FPS):
            break
        sel.pop(j)
    if frames_of(sel) < round(length * FPS):
        raise ValueError(f"нарезка короче {length:.2f} с")
    lo_k, hi_k = 0.0, 4.0
    for _ in range(60):                                       # k: сумма clip(m·k, min(0.45, m), m) = length
        k = (lo_k + hi_k) / 2
        tot = sum(min(m, max(min(0.45, m), m * k)) for _, m in sel)
        lo_k, hi_k = (k, hi_k) if tot < length else (lo_k, k)
    d = [min(m, max(min(0.45, m), m * hi_k)) for _, m in sel]
    fr = [min(int(m * FPS), max(1, round(x * FPS))) for x, (_, m) in zip(d, sel)]
    need = round(length * FPS) - sum(fr)
    for j in sorted(range(len(sel)), key=lambda j: -(sel[j][1] * FPS - fr[j])):
        while need > 0 and fr[j] < int(sel[j][1] * FPS):
            fr[j] += 1
            need -= 1
        while need < 0 and fr[j] > 14:
            fr[j] -= 1
            need += 1
    if need:
        raise ValueError("не уложить нарезку в окна")
    out = []
    for (t, m), f in zip(sel, fr):
        slack = m - f / FPS - 0.01
        out.append((t + (rng.uniform(0, min(0.25, slack)) if slack > 0 else 0.0), f / FPS))
    return out


def load_ok() -> tuple[dict, list[dict]]:
    """Проверенные окна планов (make_kolibri2_montage_ok.py) и куски чистой игры (make_kolibri2_gamecheck.py --pool)."""
    mok = json.loads((ROOT / "downloads" / "calibri2" / "montage_ok.json").read_text(encoding="utf-8"))
    pool = json.loads((ROOT / "downloads" / "calibri2" / "game_pool.json").read_text(encoding="utf-8"))
    pool = [g for g in pool if K.RANGES[g["file"]][0] <= g["start"] and g["start"] + g["max_src"] <= K.RANGES[g["file"]][1]]
    return mok, pool


def plan(n: int, tag: str, seed: int, audio: str) -> list[dict]:
    mok, pool = load_ok()
    rng = random.Random(seed)
    rng.shuffle(pool)
    rows = []
    tt = tag != "yt"
    gi = 0

    def take(src: float, avoid: str = "") -> dict:
        nonlocal gi
        for k in range(len(pool)):
            g = pool[(gi + k) % len(pool)]
            if g["max_src"] >= src + 0.05 and g["file"] != avoid:
                gi = (gi + k + 1) % len(pool)
                return g
        raise ValueError("нет куска игры нужной длины")

    for i in range(n):
        mv = MONTAGES[(i * 5 + (0 if tt else 2)) % len(MONTAGES)]
        shots_ok = [tuple(x) for x in mok[mv[0]]]
        cap = (sum(int(m * FPS) for _, m in shots_ok) - 1) / FPS
        concept = i % len(CONCEPTS)
        final = K.FINAL_ORDER[(i // len(CONCEPTS)) % len(K.FINAL_ORDER)]
        fin = [dict(file=f, start=s, src=e - s, dur=round((e - s) / sp * FPS) / FPS, speed=sp, z=z, cx=cx, cy=cy, final=1)
               for f, s, e, sp, z, cx, cy in K.FINALS[final]]
        fin_len = sum(p["dur"] for p in fin)
        if audio == "ref":
            hit = REF_HITS[tag] if REF_HITS[tag] - REF_T0 <= cap else REF_HITS["tt"]      # удар рефа, до которого хватает нарезки
            m_len = round((hit - REF_T0) * FPS) / FPS
        else:
            m_len = round(min(cap, rng.uniform(3.7, 4.2) if tt else rng.uniform(4.8, 5.6)) * FPS) / FPS
        shots = cut_shots(shots_ok, m_len, rng)
        if tt:
            lens = [max(1.2, min(2.2, 8.9 - m_len - fin_len))]
        else:
            lens = [rng.uniform(2.3, 3.0), rng.uniform(1.2, 1.5)]
            over = m_len + sum(lens) + fin_len - 12.0
            if over > 0:
                lens[0] -= over
        pieces, used = [], ""
        for ln in lens:
            d = round(ln * FPS) / FPS
            src = round(d * GAME_SPEED, 3)
            g = take(src, used)
            used = g["file"]
            off = rng.uniform(0, g["max_src"] - src - 0.05)
            pieces.append(dict(file=g["file"], start=round(g["start"] + off, 3), src=src, dur=d, speed=GAME_SPEED, z=1.0, cx=.5, cy=.5))
        pieces += fin
        rows.append(dict(i=i + 1, movie=mv[0], fid=mv[1], shots=[(round(t, 3), round(d, 4)) for t, d in shots], m_len=m_len,
                         concept=concept, final=final, pieces=pieces, audio=audio,
                         mirror=int(rng.random() < 0.5), zoom=round(rng.uniform(1.03, 1.07), 3), cx=round(rng.uniform(0.45, 0.55), 3)))
    return rows


def qa(dest: Path, r: dict) -> list[str]:
    """Покадровая проверка готового ролика. Для каждого куска игры (без финалов): (1) весь отрезок исходника, из которого взяты
    кадры, лежит внутри чистого интервала game_ok.json (там каждый кадр 30 к/с прошёл детектор: BOOST, полосы интерфейса,
    без Пункта управления и окон); (2) в каждом кадре ролика видна кнопка BOOST; (3) внутри куска нет резкой смены картинки.
    Плюс число кадров ролика."""
    ok = G.load_ok()
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(dest), "-vf", f"scale={G.SW}:{G.SH}:flags=area", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, G.SH, G.SW, 3)
    errs = []
    f0 = round(r["m_len"] * FPS)
    for k, p in enumerate(r["pieces"]):
        n = max(2, round(p["dur"] * FPS))
        if not p.get("final"):
            if not G.is_clean(ok, p["file"], p["start"], p["start"] + p["src"] + 0.05):
                errs.append(f"кусок игры {k}: исходник {p['file']} {p['start']}+{p['src']} вне чистых интервалов")
            seg = v[f0:f0 + n]
            boost = G.boost_frac(seg)
            g = seg.astype(np.float32).mean(3)
            fd = np.abs(np.diff(g, axis=0)).mean((1, 2))
            bad = sorted({f0 + int(j) for j in np.nonzero(boost < G.BOOST_MIN)[0]} | {f0 + 1 + int(j) for j in np.nonzero(fd > G.FDIFF_MAX)[0]})
            if bad:
                errs.append(f"кусок игры {k}: плохие кадры {bad[:8]}")
        f0 += n
    if abs(len(v) - f0) > 1:
        errs.append(f"кадров {len(v)}, ожидалось {f0}")
    return errs


def plate_png(text: str, dest: Path, px: int = 58) -> tuple[int, int, int, int]:
    pl, q = DB.plate(text, px)
    pl.save(dest)
    return pl.width, pl.height, q, int(0.42 * q)


def render(r: dict, out: Path, work: Path, tag: str, suffix: str = "") -> Path:
    name = f"kolibri2_{tag}_{r['i']:03d}{suffix}_1"
    hook_t, game_t = CONCEPTS[r["concept"]]
    ins, fc, boxes, labels = [], [], [], []
    m_len, z, mir = r["m_len"], r["zoom"], ",hflip" if r["mirror"] else ""
    src = str(MOV / f"{r['fid']}.mp4")
    k = 0
    for t, d in r["shots"]:
        ins += ["-ss", f"{t:.3f}", "-t", f"{d + 0.3:.3f}", "-i", src]
        nfr = round(d * FPS)
        x = f"(iw-ih)*{r['cx']:.3f}"
        fc.append(f"[{k}:v]fps={FPS},crop=ih:ih:{x}:0{mir},scale=w='{BAND}*(1+{z - 1:.3f}*t/{d:.2f})':h=-2:eval=frame:flags=bicubic,"
                  f"crop={BAND}:{BAND},pad={W}:{H}:0:{BAND_Y}:black,setsar=1,trim=end_frame={nfr},setpts=PTS-STARTPTS[m{k}]")
        labels.append(f"[m{k}]")
        k += 1
    frames = round(m_len * FPS)
    for p in r["pieces"]:
        nfr = max(2, round(p["dur"] * FPS))
        frames += nfr
        ins += ["-ss", f"{p['start']:.3f}", "-t", f"{p['src'] + .25:.3f}", "-i", str(K.SRC / p["file"])]
        fc.append(f"[{k}:v]setpts=PTS/{p['speed']},fps={FPS},{K.crop(p['z'], p['cx'], p['cy'])}scale={W}:{H}:flags=lanczos,setsar=1,"
                  f"trim=end_frame={nfr},setpts=PTS-STARTPTS[g{k}]")
        labels.append(f"[g{k}]")
        k += 1
    total = frames / FPS
    fc.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0,format=yuv420p[b]")
    cur, n_in, pngs = "b", k, []
    for key, txt, cy, a, b in (("hook", hook_t, HOOK_CY, 0, m_len if game_t else total),
                               ("game", game_t, HOOK_CY, m_len, total), ("end", ENDING, END_CY, total - END_LEN, total)):
        if not txt:
            continue
        png = work / f"{name}_{key}.png"
        pw, ph, q, pad = plate_png(txt, png, 52 if key == "end" else 58)
        x, y = (W - pw) // 2, cy - ph // 2
        boxes.append((x + pad, y + pad // 2, x + pw - pad, y + ph - pad // 2))
        ins += ["-i", str(png)]
        fc.append(f"[{cur}][{n_in}:v]overlay={x}:{y}:enable='between(t,{a:.3f},{b:.3f})'[o{n_in}]")
        cur, n_in = f"o{n_in}", n_in + 1
        pngs.append(png)
    for bx in boxes:
        if bad := check_box(W, H, bx):
            raise SystemExit(f"{name}: текст вне безопасной зоны {bx} — {bad}")
    p0 = r["pieces"][0]
    g_len = total - m_len
    if r["audio"] == "ref":
        ins += ["-ss", f"{REF_T0:.3f}", "-t", f"{m_len + 0.3:.3f}", "-i", str(REF_SOUND)]
    else:
        ins += ["-ss", f"{r['shots'][0][0]:.3f}", "-t", f"{m_len + 0.3:.3f}", "-i", src]      # родной звук сцены без разрывов
    fc.append(f"[{n_in}:a]atrim=0:{m_len:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
              f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={m_len - 0.04:.3f}:d=0.04[ma]")
    ins += ["-ss", f"{p0['start']:.3f}", "-t", f"{g_len + 0.5:.3f}", "-i", str(K.SRC / p0["file"])]
    fc.append(f"[{n_in + 1}:a]atrim=0:{g_len:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
              f"loudnorm=I=-17:TP=-1.5:LRA=11,afade=t=out:st={max(0, g_len - 0.3):.3f}:d=0.3[ga]")
    fc.append("[ma][ga]concat=n=2:v=0:a=1,alimiter=limit=0.89[a]")
    dest = out / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fc), "-map", f"[{cur}]", "-map", "[a]",
                    "-t", f"{total:.3f}", "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-c:a", "aac", "-b:a", "160k",
                    "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
                    "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=",
                    "-movflags", "+faststart", str(dest)], check=True)
    for p in pngs:
        p.unlink()
    if errs := qa(dest, r):
        bad_dir = work / "qa_failed"
        bad_dir.mkdir(exist_ok=True)
        dest.replace(bad_dir / dest.name)
        raise SystemExit(f"{name}: QA — " + "; ".join(errs))
    return dest


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="tt", choices=["tt", "yt"])
    ap.add_argument("-n", type=int, default=6)
    ap.add_argument("--audio", default="ref", choices=["ref", "movie"])
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--range", default="")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "kolibri2_test3")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "output" / "_work" / "kolibri2"
    work.mkdir(parents=True, exist_ok=True)
    jobs = []
    if a.test:                                     # каждая нарезка по разу: TikTok с треком рефа, YouTube с родным звуком сцены
        for tag, audio, seed in (("tt", "ref", 2101), ("yt", "movie", 2202)):
            rows = plan(len(MONTAGES), tag, seed, audio)
            jobs += [(r, tag, "") for r in rows[:6]]
    else:
        rows = plan(a.n, a.tag, 2101 if a.tag == "tt" else 2202, a.audio)
        lo, hi = map(int, a.range.split("-")) if a.range else (1, a.n)
        jobs = [(r, a.tag, "") for r in rows if lo <= r["i"] <= hi]
        (work / f"plan_{a.tag}.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    def safe(j):
        try:
            return render(j[0], a.out, work, j[1], j[2]), ""
        except BaseException as e:                                  # QA или ffmpeg: ролик не в выдаче, партия идёт дальше
            return None, str(e)

    failed = []
    with ThreadPoolExecutor(a.jobs) as ex:
        for (r, tag, _), (dest, err) in zip(jobs, ex.map(safe, jobs)):
            if dest is None:
                failed.append(r["i"])
                print(f"  !! {tag} {r['i']:03d}: {err}", flush=True)
            else:
                print(f"  {dest.name}  {r['movie']}  {r['audio']}  concept {r['concept']}  {r['final']}", flush=True)
    print(f"готово: {len(jobs) - len(failed)} из {len(jobs)} → {a.out}" + (f"; не прошли: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
