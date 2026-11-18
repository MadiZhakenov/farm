#!/usr/bin/env python3
"""
Calibri (Idle Bank Tycoon, ТЗ downloads/calibri/tz.pdf): вертикальные 12–14 с, только геймплей, ускорение ×4, склейка каждые 0.5–1 с,
зумы на числа, в конце новый банк или крупная сумма. Текст ТЗ дословно, TikTok-шрифт, статичным блоком в верхней трети (как реф @adsbutsmart).
Монтаж: хук с ростом денег → новый аккаунт (суммы маленькие) → bank-03 (M) → bank-06 (T) → bank-11 (ad) — сумма растёт на глазах.
Звук: мем-звук ТЗ + тихий звук игры. Библиотека кусков — по признакам кадров (downloads/calibri/feat.json).

  python build_calibri_reels.py --lib                    # окна → downloads/calibri/lib.json
  python build_calibri_reels.py --test                   # 5 роликов → output/calibri_test
  python build_calibri_reels.py -n 100 --tag tt --out output/calibri_TT_100 --seed 7101
  python build_calibri_reels.py -n 100 --tag yt --out output/calibri_YT_100 --seed 7202
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_followspy_walls as F  # noqa: E402  (текстволл TikTok-шрифтом)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
D = ROOT / "downloads" / "calibri"
SRC, SOUNDS = D / "src", D / "sounds"
NEW, B03, B06, B11 = "IBT_new-account.mp4.mp4", "IBT_bank-03.mp4", "IBT_bank-06.mp4", "IBT_bank-11.mp4"
AUDIT = ["IBT_audit-01.mp4", "IBT_audit-02.mp4", "IBT_audit-03.mp4"]
RANGES = {NEW: (185, 820), B03: (32, 595), B06: (18, 860), B11: (12, 690)}     # без логотипа, обучения, экрана телефона
SPEED = 4.0
WIN = 2.5                                                                      # длина окна библиотеки, с исходника
TEXTS = [
    "pov: you downloaded that bank game\nfrom an ad ironically\nand now you're managing 6 branches\nlike your family's depending on it\n(or maybe it actually is 😭)",
    "day 12 of playing those games from ads\nand i fear the economy\ndepends on me now",
    "my therapist told me\nto find something i can control\nso now i own 7 banks\nand have a personal beef\nwith an auditor",
    "started playing this game to relax\nand now i'm screaming\nat a fictional manager\nfor underperforming",
    "day 9 of playing ad games\nand i'm starting to understand\nwhy billionaires are like that",
]
AUDITOR_TEXT = 2
TOP, BOTTOM = 440, 705
# звук: (файл, от, до, режим) — full: на весь ролик; hit: в начале и в финале (и в середине, если короткий)
SFX = {"amrich": ("amrich.mp3", 10.0 if os.environ.get("KOLIBRI_SHORT") == "1" else 0.35, 17.3, "full"), "cher": ("cher.mp3", 25.75, 29.15, "hit"),
       "ohmygod": ("ohmygod.mp3", 3.3, 4.95, "hit3"), "omg": ("omg.mp3", 2.45, 3.95, "hit3"),
       # Daffy Duck «I'm rich!» — ссылка из ТЗ (youtu.be/4YZNXwjfq6g) недоступна, тот же клип с другой загрузки RZzpw0ndQEk
       "daffy": ("daffy_RZzpw0ndQEk.mp3", 0.0, 9.6, "full")}
SFX_ORDER = list(SFX)
LEVEL_UP = [(NEW, 826.4), (B06, 438.4)]
# финалы: куски (файл, от, до, скорость, зум, центр x, центр y)
FINALS = {
    "new_bank": [(NEW, 844.0, 845.6, 2.0, 1.0, .5, .5), (NEW, 849.4, 854.2, 3.2, 1.08, .5, .46)],
    "m220": [(B03, 602.2, 605.6, 2.0, 1.18, .46, .42)],
    "t139": [(B06, 435.2, 437.6, 1.6, 1.12, .55, .3), (B06, 438.4, 440.6, 2.2, 1.0, .5, .5)],
}
FINAL_ORDER = ["new_bank", "m220", "new_bank", "t139"]
# версия ≤ 7 с (фидбек 2026-11-10): короче финалы, склейки 0.5–0.8 с, текст — чёрный TikTok-шрифт на белых плашках
SHORT = os.environ.get("KOLIBRI_SHORT") == "1"           # --short; через окружение, чтобы видели и процессы-воркеры
FINALS_SHORT = {
    "new_bank": [(NEW, 844.4, 845.6, 2.4, 1.0, .5, .5), (NEW, 849.6, 854.0, 4.0, 1.08, .5, .46)],
    "m220": [(B03, 602.4, 605.0, 2.0, 1.18, .46, .42)],
    "t139": [(B06, 435.4, 437.2, 1.8, 1.12, .55, .3), (B06, 438.6, 440.2, 2.0, 1.0, .5, .5)],
}


def build_lib() -> None:
    feat = {r["name"]: r for r in json.loads((D / "feat.json").read_text(encoding="utf-8"))}
    lib: dict[str, list] = {}
    for name, (a, b) in RANGES.items():
        r = feat[name]
        full, navy, up, diff, green = (np.array(r[k], np.float32) for k in ("full", "navy", "up", "diff", "green"))
        n = int(WIN * 2)
        out = {"world": [], "panel": []}
        for i in range(int(a * 2), min(int(b * 2), len(full) - n)):
            w = (navy[i:i + n] < .15).all() and (full[i:i + n] > 68).all() and (up[i:i + n] > 68).all()
            p = (navy[i:i + n] > .4).all() and (up[i:i + n] > 72).all() and (full[i:i + n] > 42).all()
            if w or p:
                out["world" if w else "panel"].append((float(green[i:i + n].mean() * 40 + diff[i:i + n].mean()), i / 2))
        lib[name] = {}
        for st, cand in out.items():
            cand.sort(reverse=True)
            kept: list = []
            for s, t in cand:
                if all(abs(t - k[0]) >= 3.5 for k in kept):
                    kept.append((t, round(s, 2)))
                if len(kept) >= 90:
                    break
            lib[name][st] = sorted(kept)
            print(name[:18], st, len(kept), flush=True)
    audit = []
    for name in AUDIT:
        n = feat[name]["n"] / 2
        audit += [(name, float(t)) for t in np.arange(12, n - 12, 4.0)]
    lib["audit"] = audit
    (D / "lib.json").write_text(json.dumps(lib), encoding="utf-8")


def wall(text: str, dest: Path) -> None:
    n_lines = len([ln for ln in text.split("\n") if ln.strip()])
    px = 56
    while px > 28 and (F.WL.wall_height(text, px) > 620 or len([x for x in F.WL.wall_lines(text, px) if x]) > n_lines):
        px -= 1
    h = F.WL.wall_height(text, px)
    F.WL.render_wall(text, px, min(TOP, BOTTOM - h), dest)     # ниже плашек заданий игры, выше панели улучшений


def plate(text: str, dest: Path) -> tuple[int, int, int, int]:
    """Чёрный TikTok-шрифт на белых плашках (как нативный текст TikTok), строки по смыслу из ТЗ; блок по центру, ниже плашек игры."""
    P = F.P
    from PIL import Image
    clean = lambda t: P.C.B.A.sanitize_overlay_text(P.C.B.R._normalize_text(t))  # noqa: E731
    lines = [clean(ln) for ln in text.split(chr(10))]
    for px in range(52, 26, -1):
        blk = P.plate_block(lines, px)
        if blk.width - 2 * int(0.42 * px) <= 790 and blk.height <= 360:
            break
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    top = min(TOP, BOTTOM - blk.height)
    x = (W - blk.width) // 2
    img.alpha_composite(blk, (x, top))
    img.save(dest)
    pad = int(0.42 * px)
    return (x + pad, top + pad // 2, x + blk.width - pad, top + blk.height - pad // 2)


# ≤ 7 с по структуре ТЗ (фидбек: «структура не сохранилась, как будто срезал на 7 с»):
#   хук ~1.1 с — накопление денег (хранилище bank-03: зелёные пачки + всплывающие суммы), ×4;
#   середина — склейки 0.5–0.75 с: апгрейд (панель с кнопкой UPGRADE, зум на доход) ↔ рост суммы (всплывающие суммы),
#   банки по порядку, чтобы сумма росла (M → T → ad); без Level Up, статистики, матч-3;
#   финал — открытие нового банка (NEXT BANK → карта) или крупная сумма (220.15M / 657.43ad), число не под текстом.
# Окна — analyze_kolibri_money.py → downloads/calibri/lib7.json.
FINALS7 = {
    "new_bank": [(NEW, 844.4, 845.6, 2.4, 1.0, .5, .5), (NEW, 849.6, 854.0, 4.0, 1.08, .5, .46)],
    "m220": [(B03, 602.6, 604.6, 1.5, 1.45, .345, .345)],
    "ad657": [(B11, 559.3, 562.1, 2.0, 1.15, .42, .56)],
}
PROGRESSION = {"new_bank": [(B03, 150, 600), (B06, 25, 860), (B11, 25, 690)], "m220": [(B03, 150, 598)],
               "ad657": [(B03, 150, 600), (B06, 25, 860), (B11, 25, 555)]}          # начала файлов — логотип и загрузка
FINAL7_ORDER = ["new_bank", "m220", "new_bank", "ad657"]


def plan_short(n: int, seed: int) -> list[dict]:
    lib = json.loads((D / "lib7.json").read_text(encoding="utf-8"))
    rng = random.Random(seed)
    hooks = [h for h in lib["money"][B03] if h["score"] >= 5 and 88 <= h["t"] <= 146]   # только хранилище с пачками денег
    world = {f: [w for w in lib["world"][f] if f != B06 or w["t"] < 100] for f in (B03, B06, B11)}
    panel = {f: lib["panel"][f] for f in (B03, B06, B11)}
    uses: dict = {}
    rows, seen = [], set()

    def least(pool: list, key: str, lo: float, hi: float, k: int) -> list:
        cand = [q for q in pool if lo <= q["t"] <= hi]
        cand.sort(key=lambda q: uses.get((key, q["t"]), 0) + rng.random() * 1.3)
        out = sorted(cand[:k], key=lambda q: q["t"])
        for q in out:
            uses[(key, q["t"])] = uses.get((key, q["t"]), 0) + 1
        return out

    for i in range(n):
        final = FINAL7_ORDER[i % len(FINAL7_ORDER)]
        fin = FINALS7[final]
        fin_len = sum(round((e - s_) / sp * FPS) / FPS for _, s_, e, sp, *_ in fin)
        for _ in range(300):
            total = rng.uniform(6.5, 6.9)
            hook = min(hooks, key=lambda h: uses.get(("hook", h["t"]), 0) + rng.random() * 1.3)
            hook_len = round(rng.uniform(1.0, 1.2) * FPS) / FPS
            mid_len = total - hook_len - fin_len
            durs: list[float] = []
            while mid_len - sum(durs) >= .5:
                durs.append(round(min(rng.uniform(.5, .75), mid_len - sum(durs)) * FPS) / FPS)
            prog = PROGRESSION[final]
            per = [len(durs) // len(prog) + (1 if j < len(durs) % len(prog) else 0) for j in range(len(prog))]
            seq = []
            kind = "panel"
            for (f, lo, hi), k in zip(prog, per):
                lo = max(lo, hook["t"] + 6) if f == B03 else lo
                hi = hi if f != B03 or hook["t"] < lo else hi
                need_p = (k + (kind == "panel")) // 2
                need_w = k - need_p
                ps = least(panel[f], f + "p", lo, hi, need_p)
                ws = least(world[f], f + "w", lo, hi, need_w)
                if len(ws) < need_w:                                  # мало кадров с суммами — добираем апгрейдами
                    ps = least(panel[f], f + "p", lo, hi, k - len(ws))
                items = sorted([(f, q, "panel") for q in ps] + [(f, q, "world") for q in ws], key=lambda z: z[1]["t"])
                kind = "world" if k % 2 and kind == "panel" else ("panel" if k % 2 else kind)
                seq += items                                          # строго по времени игры — сумма только растёт
            key = (hook["t"],) + tuple((f, q["t"]) for f, q, _ in seq)
            if key not in seen and len(seq) == len(durs):
                seen.add(key)
                uses[("hook", hook["t"])] = uses.get(("hook", hook["t"]), 0) + 1
                break
        pieces = []
        z = rng.uniform(1.08, 1.16)
        pieces.append(dict(file=B03, start=round(hook["t"] + rng.uniform(0, .8), 3), src=round(hook_len * SPEED, 3), dur=hook_len, speed=SPEED,
                           z=round(z, 3), cx=round(min(max(hook["cx"], .35), .65), 3), cy=round(max(hook["cy"], .52), 3)))
        for (f, q, st), d in zip(seq, durs):
            if st == "panel":
                zz, (cx, cy) = rng.uniform(1.35, 1.5), rng.choice([(.3, .48), (.5, .69), (.32, .485)])
            else:
                zz, cx, cy = rng.uniform(1.06, 1.15), min(max(q["cx"], .35), .65), max(q["cy"], .5)
            pieces.append(dict(file=f, start=round(q["t"] + rng.uniform(0, max(0.0, 2.4 - d * SPEED)), 3), src=round(d * SPEED, 3), dur=d,
                               speed=SPEED, z=round(zz, 3), cx=round(cx, 3), cy=round(cy, 3)))
        for f, s_, e, sp, zz, cx, cy in fin:
            jit = rng.uniform(0, .1)
            pieces.append(dict(file=f, start=round(s_ + jit, 3), src=round(e - s_ - jit, 3), dur=round((e - s_ - jit) / sp * FPS) / FPS, speed=sp,
                               z=zz, cx=cx, cy=cy))
        rows.append(dict(i=i + 1, text=i % len(TEXTS), sound=SFX_ORDER[(i // len(TEXTS)) % len(SFX_ORDER)], final=final, pieces=pieces,
                         bed=(rng.choice([B03, B06, B11]), round(rng.uniform(60, 500), 1))))
    return rows


def plan(n: int, seed: int) -> list[dict]:
    if SHORT:
        return plan_short(n, seed)
    lib = json.loads((D / "lib.json").read_text(encoding="utf-8"))
    rng = random.Random(seed)
    uses: dict = {}
    rows, seen = [], set()

    def take(pool: list, key_name: str, k: int) -> list:
        """k наименее использованных окон (с шумом), по времени — сумма растёт вперёд."""
        ranked = sorted(pool, key=lambda p: uses.get((key_name, p[0]), 0) + rng.random() * 1.4)
        chosen = sorted(ranked[:k], key=lambda p: p[0])
        for p in chosen:
            uses[(key_name, p[0])] = uses.get((key_name, p[0]), 0) + 1
        return chosen

    for i in range(n):
        for _ in range(200):
            total = rng.uniform(6.2, 6.9) if SHORT else rng.uniform(12.0, 14.2)
            final = FINAL_ORDER[i % len(FINAL_ORDER)]
            fins = FINALS_SHORT if SHORT else FINALS
            fin_len = sum((e - s) / sp for _, s, e, sp, *_ in fins[final])
            durs: list[float] = []
            while sum(durs) < total - fin_len - (.25 if SHORT else 0):
                durs.append(round(rng.uniform(.5, .8 if SHORT else 1.0) * FPS) / FPS)
            if SHORT:                                               # жёстко ≤ 7 с: лишнее снимаем с последних склеек (не короче 0.5 с)
                k = len(durs) - 1
                while sum(durs) + fin_len > 6.9 and k >= 0:
                    durs[k] = max(.5, round((durs[k] - (sum(durs) + fin_len - 6.9)) * FPS) / FPS)
                    k -= 1
            hook_pool = [(name, *p) for name in (B03, B06, B11) for p in lib[name]["world"]]
            hook_pool.sort(key=lambda z: -z[2])
            hook = rng.choice(hook_pool[:40])
            n_mid = len(durs) - 1
            per = [n_mid // 4 + (1 if j < n_mid % 4 else 0) for j in range(4)]
            seq = [(hook[0], hook[1], "world")]
            first_state = rng.choice(("world", "panel"))
            for name, k in zip((NEW, B03, B06, B11), per):
                worlds, panels = (k + 1) // 2, k // 2
                if first_state == "panel":
                    worlds, panels = panels, worlds
                w, p = take(lib[name]["world"], name, worlds), take(lib[name]["panel"], name, panels)
                items = [(name, x[0], "world") for x in w] + [(name, x[0], "panel") for x in p]
                items.sort(key=lambda z: z[1])
                seq += items
            ti = i % len(TEXTS)
            if ti == AUDITOR_TEXT:                                  # текст про аудитора — кадры режима Audit
                a = rng.sample(lib["audit"], 2)
                seq[len(seq) // 2] = (a[0][0], a[0][1], "audit")
                if not SHORT and len(seq) // 2 + 2 < len(seq):
                    seq[len(seq) // 2 + 2] = (a[1][0], a[1][1], "audit")
            if len(seq) >= 7 and rng.random() < (.3 if SHORT else .55):
                nm, t = rng.choice(LEVEL_UP)
                seq[rng.randint(4, len(seq) - 3)] = (nm, t, "level")
            key = tuple((s[0], s[1]) for s in seq)
            if key not in seen:
                seen.add(key)
                break
        pieces = []
        for j, ((name, t, st), d) in enumerate(zip(seq, durs)):
            src_len = d * SPEED
            start = t + rng.uniform(0, max(0.0, WIN - src_len)) if st in ("world", "panel") else t
            if st == "level":
                speed, src_len = 1.6, d * 1.6
            else:
                speed = SPEED
            z, cx, cy = 1.0, .5, .5
            if st == "panel" and rng.random() < .62:                # зум на число дохода / уровень улучшения
                z, (cx, cy) = rng.uniform(1.4, 1.55), rng.choice([(.3, .48), (.5, .69), (.32, .485)])
            elif st == "world" and j % 2:
                z, cx, cy = rng.uniform(1.08, 1.18), rng.uniform(.42, .58), rng.uniform(.42, .6)
            pieces.append(dict(file=name, start=round(start, 3), src=round(src_len, 3), dur=d, speed=speed, z=round(z, 3), cx=round(cx, 3), cy=round(cy, 3)))
        for name, s, e, sp, z, cx, cy in (FINALS_SHORT if SHORT else FINALS)[final]:
            jitter = rng.uniform(0, .12)
            pieces.append(dict(file=name, start=round(s + jitter, 3), src=round(e - s - jitter, 3), dur=round((e - s - jitter) / sp * FPS) / FPS, speed=sp, z=z, cx=cx, cy=cy))
        rows.append(dict(i=i + 1, text=i % len(TEXTS), sound=SFX_ORDER[(i // len(TEXTS)) % len(SFX_ORDER)], final=final, pieces=pieces,
                         bed=(rng.choice([B03, B06, B11]), round(rng.uniform(60, 500), 1))))
    return rows


def crop(z: float, cx: float, cy: float) -> str:
    if z <= 1.001:
        return ""
    w, h = 1 / z, 1 / z
    x = min(max(cx - w / 2, 0), 1 - w)
    y = min(max(cy - h / 2, 0), 1 - h)
    return f"crop=iw*{w:.4f}:ih*{h:.4f}:iw*{x:.4f}:ih*{y:.4f},"


def render(job: tuple[dict, str, str]) -> str:
    r, out, tag = job
    out = Path(out)
    dest = out / f"kolibri_{tag}_{r['i']:03d}_noid.mp4"
    work = out / "_work"
    work.mkdir(parents=True, exist_ok=True)
    png = work / f"t{r['text']}.png"
    if not png.exists():
        (plate if SHORT else wall)(TEXTS[r["text"]], png)
    inputs, fc = [], []
    frames = 0
    for k, p in enumerate(r["pieces"]):
        nfr = max(2, round(p["dur"] * FPS))
        frames += nfr
        inputs += ["-ss", f"{p['start']:.3f}", "-t", f"{p['src'] + .25:.3f}", "-i", str(SRC / p["file"])]
        sharp = "unsharp=5:5:0.45," if p["z"] > 1.2 else ""
        fc.append(f"[{k}:v]setpts=PTS/{p['speed']},fps={FPS},{crop(p['z'], p['cx'], p['cy'])}scale={W}:{H}:flags=lanczos,{sharp}setsar=1,trim=end_frame={nfr},setpts=PTS-STARTPTS[v{k}]")
    n = len(r["pieces"])
    total = frames / FPS
    fc.append("".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0,format=yuv420p[b]")
    inputs += ["-i", str(png)]
    fc.append(f"[b][{n}:v]overlay=0:0,format=yuv420p[v]")
    idx = n + 1
    fname, a, b, mode = SFX[r["sound"]]
    src = str(SOUNDS / fname)
    bed_file, bed_t = r["bed"]
    inputs += ["-ss", f"{bed_t}", "-t", f"{total + 1:.2f}", "-i", str(SRC / bed_file)]
    fc.append(f"[{idx}:a]aresample=44100,volume=0.11,afade=t=out:st={max(0, total - .3):.3f}:d=0.3[bed]")
    idx += 1
    mix = ["[bed]"]
    if mode == "full":
        end = min(b, a + total)
        inputs += ["-i", src]
        fc.append(f"[{idx}:a]atrim={a}:{end},asetpts=PTS-STARTPTS,aresample=44100,loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={max(0, total - .3):.3f}:d=0.3[s0]")
        mix.append("[s0]")
    else:
        L = b - a
        if mode == "hit":
            marks = [0.0, total - L - .05] if total >= 2 * L + .1 else [max(0.0, total - L - .05)]   # коротко: одна реплика под финал
        else:
            marks = [0.0, max(0.0, total / 2 - L / 2), max(0.0, total - L - .05)]
        inputs += ["-i", src]
        split = "".join(f"[h{j}]" for j in range(len(marks)))
        fc.append(f"[{idx}:a]atrim={a}:{b},asetpts=PTS-STARTPTS,aresample=44100,loudnorm=I=-14:TP=-1.5:LRA=11,asplit={len(marks)}{split}")
        for j, t in enumerate(marks):
            fc.append(f"[h{j}]adelay={int(t * 1000)}:all=1[s{j}]")
            mix.append(f"[s{j}]")
    fc.append("".join(mix) + f"amix=inputs={len(mix)}:normalize=0:duration=first,atrim=0:{total:.3f},alimiter=limit=0.89[a]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
                    "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    return dest.name


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("-n", type=int, default=5)
    ap.add_argument("--tag", default="tt")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--seed", type=int, default=7101)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--short", action="store_true", help="≤ 7 с, текст на белых плашках")
    a = ap.parse_args()
    global SHORT
    if a.short:
        os.environ["KOLIBRI_SHORT"] = "1"
        SHORT = True
    if a.lib:
        build_lib()
        return 0
    out = a.out or ROOT / "output" / "calibri_test"
    out.mkdir(parents=True, exist_ok=True)
    (out / "_work").mkdir(exist_ok=True)
    for t, txt in enumerate(TEXTS):
        p = out / "_work" / f"t{t}.png"
        if SHORT:
            box = plate(txt, p)
        else:
            wall(txt, p)
            from PIL import Image
            box = Image.open(p).getbbox()
        if bad := check_box(W, H, box):
            raise SystemExit(f"текст {t + 1} вне безопасной зоны {box}: {bad}")
        print(f"текст {t + 1}: блок {box}", flush=True)
    rows = plan(a.n, a.seed)
    with ProcessPoolExecutor(a.jobs) as ex:
        for name in ex.map(render, [(r, str(out), a.tag) for r in rows]):
            print(" ", name, flush=True)
    for f in (out / "_work").glob("*.png"):
        f.unlink()
    (out / "_work").rmdir()
    (out / "manifest.json").write_text(json.dumps(rows, indent=0, ensure_ascii=False), encoding="utf-8")
    print(f"готово: {len(rows)} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
