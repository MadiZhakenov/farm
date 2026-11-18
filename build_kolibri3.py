#!/usr/bin/env python3
"""
Колибри 3 (Idle Bank Tycoon, ID 1), C1 «мем, как будто чел играет в игру» — по примеру клиента IBT_3B_04_bank6:
  сверху — хук ТЗ (дословно, белая TikTok-плашка), в середине — полоса игры 1080×600 на ×4, склейка каждые 0,5–0,9 с,
  наезды на суммы, большой зелёный счётчик денег поверх полосы; снизу — стример с зелёного фона (вырезан) на размытом
  фоне той же игры. Счётчик растёт и на «скачке» (финал игры: 657.43ad / 220.15M / новый банк) прыгает к числу из игры —
  в этот же момент склейка на реакцию стримера (кричит LET'S GO / MOMENT IN HISTORY / sheesh или мем-звук).
  Хук совпадает с игрой: «вселенная/экономика/планеты» → 657.43ad, «купить весь магазин» → 220.15M, «города/империя» →
  новый банк. Звук: «hello chat gpt, how to be rich» (или CaseOh «we are absolutely cooked») до скачка, потом крик
  стримера или мем (am rich, OOOH MY GOD, OMG, Cher, Daffy). TikTok 10–10,8 с, YouTube 12–12,6 с.
  Игра — только куски, где каждый кадр прошёл детектор Колибри 2 (game_ok.json), готовый ролик проверяется ещё раз (qa).

  python build_kolibri3.py --prep                     # ключ зелёного и рамки людей в реакциях → downloads/calibri3/react.json
  python build_kolibri3.py --test                     # 6 TT + 6 YT → output/kolibri3_test
  python build_kolibri3.py --tag tt -n 100 --out output/kolibri3_TT_100
  python build_kolibri3.py --tag yt -n 200 --out output/kolibri3_YT_200
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_calibri_reels as K  # noqa: E402  (сырые записи игры, lib7, crop)
import build_drops_beats_reels as DB  # noqa: E402  (plate — белая TikTok-плашка с эмодзи)
import make_kolibri2_gamecheck as G  # noqa: E402  (покадровый детектор чистой игры)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
D3 = ROOT / "downloads" / "calibri3"
RX = D3 / "react"
PROXY = K.D / "proxy30"                         # make: ffmpeg -hwaccel cuda -i src -an -vf fps=30 -c:v h264_nvenc -cq 18 -g 15 -bf 0
BAND_Y, BAND_H = 650, 600
PLATE_CY, PLATE_MAX_BOTTOM = 430, 628
COUNTER_CY = 712
SPEED = 4.0
FONT_NUM = ROOT / "fonts" / "lilita" / "LilitaOne-Regular.ttf"

TEXTS = [
    "MY RENT IS DUE TOMORROW\nBUT AT LEAST I OWN\nHALF THE UNIVERSE\nIN THIS GAME 💀",
    "MY BANK ACCOUNT IRL\nIS ON LIFE SUPPORT\nBUT IN THIS GAME\nI'M LITERALLY THE ECONOMY 😭",
    "CAN'T AFFORD GROCERIES IRL\nBUT SOMEHOW I'M BUYING\nENTIRE PLANETS\nIN THIS GAME 💀",
    "MY LANDLORD WANTS RENT\nAND I'M BUSY BECOMING\nTHE MOST POWERFUL PERSON\nIN THIS GAME 😭",
    "I HAVE $4.72 TO MY NAME IRL\nBUT THIS GAME GOT ME ACTING\nLIKE I OWN THE SOLAR SYSTEM 💀",
    "MY CARD GOT DECLINED\nAT THE STORE\nBUT IN THIS GAME\nI CAN BUY THE WHOLE STORE 😭",
    "ME IGNORING MY UNPAID BILLS\nWHILE MY EMPIRE IN THIS GAME\nKEEPS GETTING BIGGER 💀",
    "I CAN'T EVEN AFFORD\nA PARKING SPOT IRL\nBUT I'M OUT HERE\nOWNING ENTIRE CITIES 😭",
    "MY FRIDGE IS EMPTY\nBUT MY INVENTORY IN THIS GAME\nLOOKS LIKE\nA BILLIONAIRE'S GARAGE 💀",
    "MY REAL LIFE IS JUST\nBILLS AND STRESS\nBUT THIS GAME HAS ME\nRUNNING AN ENTIRE EMPIRE 😭",
]
# хук ↔ игра: что показывает финал
TEXT_FINAL = ["ad657", "ad657", "ad657", "ad657", "ad657", "m220", "new_bank", "new_bank", "ad657", "new_bank"]
START_VALUE = {4: 4.72}                        # «$4.72 to my name» — счётчик стартует ровно с $4.72

# финалы: куски (файл, от, до, скорость, зум, cx, cy полосы), момент скачка в исходнике, число в игре
FINALS = {
    "ad657": dict(pieces=[(K.B11, 559.5, 562.9, 1.0, 1.0, .5, .47)], hit=(0, 560.3), value=657.43e24),
    "m220": dict(pieces=[(K.B03, 601.6, 605.6, 1.0, 1.0, .5, .38)], hit=(0, 601.9), value=220_150_000),
    "new_bank": dict(pieces=[(K.NEW, 844.4, 845.6, 1.0, 1.0, .5, .44), (K.NEW, 851.6, 854.8, 0.8, 1.0, .5, .47)], hit=(1, 852.8),   # замок ломается 852.7–853.0; после 854.9 — белая вспышка и загрузка
                     value=None),
}
PROGRESSION = {"new_bank": [(K.B03, 150, 600), (K.B06, 25, 860), (K.B11, 25, 690)], "m220": [(K.B03, 150, 598)],
               "ad657": [(K.B03, 150, 600), (K.B06, 25, 860), (K.B11, 25, 555)]}

# реакции: окна клипов (проверены покадрово) и звук
REACT_WIN = {
    "speed_think": ("4D0o8exrcAk", 0.2, 8.4),
    "speed_shock": ("4D0o8exrcAk", 8.5, 11.9),
    "speed_letsgo": ("FFFH30GKrUA", 0.0, 3.4),
    "caseoh_cooked": ("DQbiS0L5ilQ", 0.0, 13.134),
    "caseoh_history": ("XztI-6fAUcI", 4.6, 8.6),
    "speed_kai": ("jYT9h04L-3M", 1.0, 4.6),
    "xqc_sheesh": ("HQJZKBwJ_rI", 0.5, 3.8),
    "shocked_guy": ("DxYgkPGiBhM", 0.6, 3.4),
}
# CaseOh «we are cooked» — один клип на весь ролик: ролик длится ровно как его видео, без второй реакции и мема (фидбек 10.11);
# скачок в игре попадает на «we are absolutely cooked, chat» (9.3–11.7 с клипа)
SOLO = {"caseoh_cooked": round(13.134 * 30) / 30}
REACT_EQ = {"caseoh_cooked": "eq=brightness=0.04:gamma=1.45:saturation=1.05,"}    # снят в тёмной комнате
# сценарии: (разгон, скачок, звук разгона, звук скачка: own = свой голос, meme = мем-звук)
SCRIPTS = [
    ("speed_think", "speed_letsgo", "gpt", "own"),
    ("caseoh_cooked", "caseoh_history", "own", "own"),
    ("speed_think", "speed_shock", "gpt", "meme"),
    ("speed_think", "speed_kai", "gpt", "own"),
    ("caseoh_cooked", "shocked_guy", "own", "meme"),
    ("speed_think", "xqc_sheesh", "gpt", "own"),
]
GPT = (RX / "gpt_7531303562517695233.mp3", [2.9, 3.6, 5.9, 7.6, 9.2])   # «hello chat gpt, how to be rich? very rich…» — концы фраз
MEMES = {"amrich": (RX / "amrich.mp3", 10.4, 14.0), "ohmygod": (RX / "ohmygod.mp3", 2.2, 5.1), "omg": (RX / "omg.mp3", 2.3, 4.2),
         "cher": (RX / "cher.mp3", 26.9, 29.5), "daffy": (RX / "daffy_RZzpw0ndQEk.mp3", 5.5, 8.7)}
MEME_ORDER = list(MEMES)
SUFFIX = ["", "K", "M", "B", "T", "aa", "ab", "ac", "ad", "ae"]


# ------------------------------------------------------------------ подготовка реакций
def key_color(v: np.ndarray) -> np.ndarray:
    c = np.concatenate([v[:, :8, :8].reshape(-1, 3), v[:, :8, -8:].reshape(-1, 3)])
    return np.median(c, axis=0)


def prep() -> None:
    out = {}
    for name, (clip, a, b) in REACT_WIN.items():
        p = RX / f"{clip}.mp4"
        wh = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(p)],
                            capture_output=True, text=True).stdout.strip().split(",")
        cw, ch = int(wh[0]), int(wh[1])
        sw, sh = 192, int(192 * ch / cw)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a}", "-t", f"{b - a}", "-i", str(p), "-vf", f"fps=5,scale={sw}:{sh}",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        v = np.frombuffer(raw, np.uint8).reshape(-1, sh, sw, 3).astype(np.float32)
        kc = key_color(v)
        fg = np.linalg.norm(v - kc, axis=3) > 90
        bd = max(2, int(sw * 0.02))
        fg[:, :, :bd] = fg[:, :, -bd:] = False                  # края кадра — рамки/виньетка, не человек
        fg[:, :bd] = False
        m = fg.mean(0) > 0.15                                   # где человек бывает хотя бы 15 % времени
        ys, xs = np.nonzero(m)
        box = [float(np.percentile(xs, 3) / sw), float(np.percentile(ys, 1) / sh), float(np.percentile(xs, 97) / sw), float((ys.max() + 1) / sh)]
        out[name] = dict(clip=clip, a=a, b=b, w=cw, h=ch, key="0x%02X%02X%02X" % tuple(int(x) for x in kc), box=[round(x, 3) for x in box])
        print(name, out[name], flush=True)
    (D3 / "react.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


def react_geom(r: dict) -> tuple[int, int, int]:
    """Масштаб и позиция клипа: человек внизу кадра, голова ~ на 1290, по центру, не шире кадра."""
    x0, y0, x1, y1 = r["box"]
    ph = (y1 - y0) * r["h"]
    pw = (x1 - x0) * r["w"]
    s = min(660 / ph, 1060 / pw)
    sh = int(round(r["h"] * s / 2) * 2)
    sw = int(round(r["w"] * s / 2) * 2)
    x = int(540 - (x0 + x1) / 2 * sw)
    y = int(H - y1 * sh) if y1 > 0.97 else int(H - 40 - y1 * sh)
    return sw, sh, x, y


# ------------------------------------------------------------------ счётчик
def fmt_money(v: float) -> str:
    if v < 1000:
        return f"${v:,.2f}"
    if v < 1e12:
        return f"${v:,.0f}"
    k = min(len(SUFFIX) - 1, int(math.log10(v) // 3))
    return f"${v / 10 ** (3 * k):.2f}{SUFFIX[k]}"


def text_img(s: str, px: int, fill: tuple, stroke: tuple, sw: int) -> Image.Image:
    f = ImageFont.truetype(str(FONT_NUM), px)
    l, t, r, b = f.getbbox(s, stroke_width=sw)
    im = Image.new("RGBA", (r - l + 8, b - t + 14), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((4 - l, 10 - t), s, font=f, fill=(0, 0, 0, 120), stroke_width=sw, stroke_fill=(0, 0, 0, 120))   # мягкая тень
    im2 = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(im2).text((4 - l, 4 - t), s, font=f, fill=fill, stroke_width=sw, stroke_fill=stroke)
    im.alpha_composite(im2)
    return im


def counter_frames(r: dict, total_f: int, dest, boxes: list | None = None):
    """PNG-кадры счётчика (1080×300 сверху полосы): экспонента до скачка, на скачке — число из игры с «попом»,
    у нового банка — надпись NEW BANK UNLOCKED!. → рамки текста для проверки безопасной зоны."""
    if isinstance(dest, Path):
        dest.mkdir(parents=True, exist_ok=True)
    hit_f = round(r["t_hit"] * FPS)
    boxes = [] if boxes is None else boxes
    label = None
    if r["final"] == "new_bank":
        a = text_img("NEW BANK", 92, (255, 214, 64, 255), (40, 24, 0, 255), 7)
        b = text_img("UNLOCKED!", 92, (255, 255, 255, 255), (30, 30, 30, 255), 7)
        label = Image.new("RGBA", (max(a.width, b.width), a.height + b.height - 18), (0, 0, 0, 0))
        label.alpha_composite(a, ((label.width - a.width) // 2, 0))
        label.alpha_composite(b, ((label.width - b.width) // 2, a.height - 18))
    for i in range(total_f):
        im = Image.new("RGBA", (W, 420), (0, 0, 0, 0))
        tt = i / FPS
        kn = r["knots"]
        if r["cfin"] and i >= hit_f:
            v = r["cfin"]
        elif r["cfin"] or i < hit_f:
            v = 10 ** float(np.interp(min(tt, r["t_hit"]), [a for a, _ in kn], [b for _, b in kn]))
        else:
            v = 10 ** kn[-1][1] * (1 + 0.04 * (tt - kn[-1][0]))
        sc = 1.0
        if i >= hit_f and r["cfin"]:
            dt = (i - hit_f) / FPS
            sc = 1.0 + 0.3 * math.exp(-dt * 7) * abs(math.cos(dt * 18)) if dt < 0.7 else 1.0
        boxes_skip = r["final"] == "new_bank" and tt >= r.get("t_fin", 1e9)      # окно NEXT BANK и карта — свой текст игры
        t = text_img(fmt_money(v), int(84 * sc), (88, 236, 92, 255), (8, 48, 12, 255), max(5, int(6 * sc)))
        if t.width > 790:
            f2 = 84 * sc * 790 / t.width
            t = text_img(fmt_money(v), int(f2), (88, 236, 92, 255), (8, 48, 12, 255), max(5, int(6 * f2 / 84)))
        x, y = (W - t.width) // 2, 60 - (t.height - 100) // 2
        if not boxes_skip:
            im.alpha_composite(t, (x, max(0, y)))
            boxes.append((x, COUNTER_CY - 60 + max(0, y), x + t.width, COUNTER_CY - 60 + max(0, y) + t.height))
        if label is not None and i >= hit_f:
            dt = (i - hit_f) / FPS
            ls = min(1.0, 0.55 + dt * 4) if dt < 0.25 else 1.0 + 0.06 * math.exp(-(dt - 0.25) * 6)
            lab = label.resize((int(label.width * ls), int(label.height * ls)), Image.LANCZOS)
            lx, ly = (W - lab.width) // 2, 230 - lab.height // 2 + 20
            im.alpha_composite(lab, (lx, ly))
            boxes.append((lx, COUNTER_CY - 60 + ly, lx + lab.width, COUNTER_CY - 60 + ly + lab.height))
        if isinstance(dest, Path):
            im.save(dest / f"c_{i:04d}.png", compress_level=1)
        else:
            dest.write(im.tobytes())                            # сырые RGBA прямо в ffmpeg: PNG на диск — самое медленное место
    return boxes


# ------------------------------------------------------------------ план
def plan(n: int, tag: str, seed: int) -> list[dict]:
    lib = json.loads((K.D / "lib7.json").read_text(encoding="utf-8"))
    ok = G.load_ok()
    rng = random.Random(seed)
    tt = tag == "tt"
    clean = lambda f, s, ln: G.is_clean(ok, f, s - 0.05, s + ln + 0.1)                     # noqa: E731
    hooks = [dict(h, offs=[o for o in np.arange(0, 0.85, 0.1) if clean(K.B03, h["t"] + o, 1.1 * SPEED)])
             for h in lib["money"][K.B03] if 88 <= h["t"] <= 146 and h["score"] >= 5]
    hooks = [h for h in hooks if h["offs"]]                                                # хранилище с пачками денег, весь кусок чистый
    gpool = json.loads((ROOT / "downloads" / "calibri2" / "game_pool.json").read_text(encoding="utf-8"))     # чистые куски Колибри 2
    pool = {f: sorted([dict(q, kind="money") for q in lib["money"][f]] + [dict(q, kind="world") for q in lib["world"][f]]
                      + [dict(t=g["start"], cx=.5, cy=.5, score=0, kind="pool") for g in gpool if g["file"] == f], key=lambda q: q["t"])
            for f in (K.B03, K.B06, K.B11)}
    uses: dict = {}
    rows, seen = [], set()
    for i in range(n):
        ti = i % len(TEXTS)
        final = TEXT_FINAL[ti]
        fin = FINALS[final]
        fps_pieces = [dict(file=f, start=s, src=round(e - s, 3), dur=round((e - s) / sp * FPS) / FPS, speed=sp, z=z, cx=cx, cy=cy, final=1)
                      for f, s, e, sp, z, cx, cy in fin["pieces"]]
        hk, hs = fin["hit"]
        hit_off = sum(p["dur"] for p in fps_pieces[:hk]) + (hs - fps_pieces[hk]["start"]) / fps_pieces[hk]["speed"]
        fin_len = sum(p["dur"] for p in fps_pieces)
        script = SCRIPTS[(i // len(TEXTS) + i) % len(SCRIPTS)]
        for _ in range(400):
            total = round((rng.uniform(10.0, 10.8) if tt else rng.uniform(12.0, 12.6)) * FPS) / FPS
            total = SOLO.get(script[0], total)
            build = total - fin_len
            hook = min(hooks, key=lambda h: uses.get(("hook", h["t"]), 0) + rng.random() * 1.3)
            hook_len = round(rng.uniform(0.9, 1.1) * FPS) / FPS
            durs: list[float] = []
            while build - hook_len - sum(durs) >= 0.5:
                durs.append(round(min(rng.uniform(.5, .9), build - hook_len - sum(durs)) * FPS) / FPS)
            if build - hook_len - sum(durs) > 1e-6:
                durs[-1] = round((durs[-1] + build - hook_len - sum(durs)) * FPS) / FPS
            prog = PROGRESSION[final]
            per = [len(durs) // len(prog) + (1 if j < len(durs) % len(prog) else 0) for j in range(len(prog))]
            seq, dj, okp = [], 0, True
            for (f, lo, hi), k in zip(prog, per):
                lo2 = max(lo, hook["t"] + 8) if f == K.B03 else lo
                cand = [q for q in pool[f] if lo2 <= q["t"] <= hi]
                rng.shuffle(cand)
                cand.sort(key=lambda q: uses.get((f, q["t"]), 0) + {"money": 0, "world": .5, "pool": .9}[q["kind"]] + rng.random())
                pick = []
                for q in cand:
                    if len(pick) == k:
                        break
                    src = max(durs[dj:dj + k]) * SPEED          # после сортировки по времени кусок может получить любую длину блока
                    st = None
                    for off in (0.0, 0.4, 0.8, 1.2):
                        if clean(f, q["t"] + off, src):
                            st = q["t"] + off
                            break
                    if st is None or any(abs(st - p[1]) < 2.5 for p in pick):
                        continue
                    pick.append((q, st))
                if len(pick) < k:
                    okp = False
                    break
                pick.sort(key=lambda z: z[1])
                for q, st in pick:
                    seq.append((f, q, st, durs[dj]))
                    dj += 1
            hook_st = hook["t"] + float(rng.choice(hook["offs"]))
            if not okp or not clean(K.B03, hook_st, hook_len * SPEED):
                continue
            key = (round(hook_st), ) + tuple((f, round(st)) for f, _, st, _ in seq)
            if key in seen:
                continue
            seen.add(key)
            break
        else:
            raise SystemExit(f"ролик {i + 1}: не собрать чистую игру")
        uses[("hook", hook["t"])] = uses.get(("hook", hook["t"]), 0) + 1
        for f, q, _, _ in seq:
            uses[(f, q["t"])] = uses.get((f, q["t"]), 0) + 1
        pieces = [dict(file=K.B03, start=round(hook_st, 3), src=round(hook_len * SPEED, 3), dur=hook_len, speed=SPEED, z=round(rng.uniform(1.0, 1.1), 3),
                       cx=round(min(max(hook["cx"], .3), .7), 3), cy=round(min(max(hook["cy"], .3), .7), 3))]
        for j, (f, q, st, d) in enumerate(seq):
            if q["kind"] == "money" and j % 2 == 0:            # наезд на сумму
                z, cx, cy = rng.uniform(1.3, 1.5), min(max(q["cx"], .3), .7), min(max(q["cy"], .3), .7)
            else:
                z, cx, cy = rng.uniform(1.0, 1.12), .5, min(max(q.get("cy", .5), .35), .65)
            pieces.append(dict(file=f, start=round(st, 3), src=round(d * SPEED, 3), dur=d, speed=SPEED, z=round(z, 3), cx=round(cx, 3), cy=round(cy, 3)))
        pieces += fps_pieces
        t_hit = round((sum(p["dur"] for p in pieces) - fin_len + hit_off) * FPS) / FPS
        c0 = START_VALUE.get(ti, rng.uniform(1200, 9800))
        cfin = fin["value"]
        # счётчик не меньше сумм, что всплывают в игре: банк 3 — миллионы…сотни миллионов, банк 6 — триллионы (5.17T), банк 11 — ac…ad
        span = {K.B03: (6.2, 8.15), K.B06: (13.3, 15.2), K.B11: (21.0, 26.3)}
        knots = [(0.0, math.log10(c0)), (pieces[0]["dur"], rng.uniform(6.0, 6.4))]
        t = pieces[0]["dur"]
        blocks: dict = {}
        for pc in pieces[1:len(pieces) - len(fps_pieces)]:
            blocks.setdefault(pc["file"], [t, t])
            t += pc["dur"]
            blocks[pc["file"]][1] = t
        for f, (ta, tb) in blocks.items():
            lo_, hi_ = span[f]
            if final == "m220":
                lo_, hi_ = 6.4, math.log10(cfin / rng.uniform(1.3, 1.6))
            knots += [(ta + 0.25, max(knots[-1][1], lo_)), (tb, max(lo_ + 0.3, hi_ - rng.uniform(0, .3)))]
        if not cfin:
            knots += [(t_hit, knots[-1][1] + 0.3)]
        if cfin:
            knots += [(t_hit - 1 / FPS, min(knots[-1][1] + 0.4, math.log10(cfin) - 0.25)), (t_hit, math.log10(cfin))]
        c1 = 0
        rows.append(dict(i=i + 1, text=ti, final=final, pieces=pieces, total=round(sum(p["dur"] for p in pieces), 3), t_hit=t_hit,
                         t_fin=round(sum(p["dur"] for p in pieces) - fin_len, 3),
                         script=list(script), meme=MEME_ORDER[(i // len(SCRIPTS)) % len(MEME_ORDER)],
                         c0=round(c0, 2), c1=c1, cfin=cfin, knots=[(round(a, 3), round(b, 4)) for a, b in knots], mirror_bg=int(rng.random() < .5),
                         bed=(rng.choice([K.B03, K.B06, K.B11]), round(rng.uniform(150, 500), 1))))
    return rows


# ------------------------------------------------------------------ рендер
def gain_to(path: Path, ss: float, t: float, target: float) -> float:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-ss", f"{ss:.3f}", "-t", f"{t:.3f}", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.search(r"max_volume: (-?[\d.]+) dB", err)
    mv = re.search(r"mean_volume: (-?[\d.]+) dB", err)
    if not mv:
        return 0.0
    g = target - float(mv.group(1))
    return round(min(g, -1.0 - float(m.group(1)) + 6), 2) if m else round(g, 2)


def fit_crop(sw: int, sh: int, x: int, y: int, rh: int = H) -> str:
    """Часть клипа, попадающая в область W×rh, и подкладка до неё (pad не умеет отрицательные сдвиги)."""
    x0, x1 = max(0, -x), min(sw, W - x)
    y0, y1 = max(0, -y), min(sh, rh - y)
    cw, chh = (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2
    return f"crop={cw}:{chh}:{x0}:{y0},pad={W}:{rh}:{max(0, x)}:{max(0, y)}:color=black@0"


def band_crop(z: float, cx: float, cy: float) -> str:
    cw, chh = W / z, BAND_H / z
    x = min(max(cx * W - cw / 2, 0), W - cw)
    y = min(max(cy * H - chh / 2, 0), H - chh)
    return f"crop={cw:.0f}:{chh:.0f}:{x:.0f}:{y:.0f}"


def render(r: dict, out: Path, work: Path, tag: str) -> Path:
    name = f"kolibri3_{tag}_{r['i']:03d}_1"
    rj = json.loads((D3 / "react.json").read_text(encoding="utf-8"))
    ins, fc = [], []
    k = 0
    bands, bgs = [], []
    for p in r["pieces"]:
        nfr = max(2, round(p["dur"] * FPS))
        srcp = PROXY / p["file"] if not p.get("final") and (PROXY / p["file"]).exists() else K.SRC / p["file"]
        ins += ["-ss", f"{p['start']:.3f}", "-t", f"{p['src'] + .3:.3f}", "-i", str(srcp)]
        fc.append(f"[{k}:v]setpts=PTS/{p['speed']},fps={FPS},trim=end_frame={nfr},setpts=PTS-STARTPTS,split[s{k}a][s{k}b]")
        fc.append(f"[s{k}a]{band_crop(p['z'], p['cx'], p['cy'])},scale={W}:{BAND_H}:flags=bicubic,setsar=1[bd{k}]")
        fc.append(f"[s{k}b]crop=1080:1080:0:{int(min(max(p['cy'] * H - 540, 0), H - 1080))},scale=96:96:flags=area,boxblur=3:2"
                  f"{',hflip' if r['mirror_bg'] else ''},eq=brightness=-0.04:saturation=0.9,scale={W}:{H}:flags=bilinear,setsar=1[bg{k}]")
        bands.append(f"[bd{k}]")
        bgs.append(f"[bg{k}]")
        k += 1
    n = len(bands)
    total = sum(max(2, round(p["dur"] * FPS)) for p in r["pieces"]) / FPS
    fc.append("".join(bands) + f"concat=n={n}:v=1:a=0[band]")
    fc.append("".join(bgs) + f"concat=n={n}:v=1:a=0[bgall]")
    fc.append(f"[bgall][band]overlay=0:{BAND_Y}[v0]")
    # реакция: разгон до скачка, потом скачок
    rlab = []
    build_n, pay_n = r["script"][0], r["script"][1]
    solo = build_n in SOLO
    parts = [(build_n, total)] if solo else [(build_n, r["t_hit"]), (pay_n, total - r["t_hit"])]
    for nm, a_len in parts:
        rc = rj[nm]
        win = rc["b"] - rc["a"]
        sp = max(0.8, min(1.25, win / a_len)) if a_len > win else 1.0              # окно короче нужного — чуть замедляем
        src_len = min(win, a_len * sp)
        sw, sh, x, y = react_geom(rc)
        ins += ["-ss", f"{rc['a']:.3f}", "-t", f"{src_len + .3:.3f}", "-i", str(RX / f"{rc['clip']}.mp4")]
        fc.append(f"[{k}:v]setpts=PTS/{sp:.4f},fps={FPS},trim=end_frame={round(a_len * FPS)},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=1,"
                  f"trim=end_frame={round(a_len * FPS)},scale={sw}:{sh},chromakey={rc['key']}:0.16:0.06,despill=type=green:mix=0.6:expand=0.1,"
                  f"{REACT_EQ.get(nm, '')}"
                  f"format=yuva420p,{fit_crop(sw, sh, x, y - (BAND_Y + BAND_H), H - BAND_Y - BAND_H)},setsar=1[r{k}]")
        rlab.append(f"[r{k}]")
        k += 1
    fc.append("".join(rlab) + f"concat=n={len(rlab)}:v=1:a=0[rx]")
    fc.append(f"[v0][rx]overlay=0:{BAND_Y + BAND_H}[v1]")
    # плашка хука
    pl, q = DB.plate(TEXTS[r["text"]], 54)
    py = min(PLATE_CY - pl.height // 2, PLATE_MAX_BOTTOM - pl.height)
    px_ = (W - pl.width) // 2
    plate_png = work / f"{name}_plate.png"
    pl.save(plate_png)
    boxes = [DB.plate_box(pl, px_, py, q)]
    ins += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(plate_png)]
    fc.append(f"[v1][{k}:v]overlay={px_}:{py}[v2]")
    k += 1
    ins += ["-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x420", "-framerate", str(FPS), "-i", "pipe:0"]
    fc.append(f"[v2][{k}:v]overlay=0:{COUNTER_CY - 60}:eof_action=pass,format=yuv420p[v]")
    k += 1
    for bx in boxes:
        if bad := check_box(W, H, bx):
            raise SystemExit(f"{name}: текст вне безопасной зоны {bx} — {bad}")
    cboxes: list = []
    # звук: разгон (gpt / голос CaseOh) → скачок (свой крик / мем) + фон игры
    th = r["t_hit"]
    a_parts = []
    if solo:                                                     # весь ролик — свой голос клипа, до самого конца
        rc = rj[build_n]
        g = gain_to(RX / f"{rc['clip']}.mp4", rc["a"], total, -17)
        ins += ["-ss", f"{rc['a']:.3f}", "-t", f"{total + .3:.3f}", "-i", str(RX / f"{rc['clip']}.mp4")]
        fc.append(f"[{k}:a]asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,volume={g}dB,apad=whole_dur={total:.3f},"
                  f"atrim=0:{total:.3f},afade=t=out:st={total - .15:.3f}:d=0.15[voice]")
        k += 1
    elif r["script"][2] == "gpt":
        path, ends = GPT
        e = max([x for x in ends if x <= th - 0.15] or [ends[0]])
        g = gain_to(path, 0, e, -17)
        ins += ["-t", f"{e + .2:.3f}", "-i", str(path)]
        fc.append(f"[{k}:a]atrim=0:{e + .12:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,volume={g}dB,"
                  f"afade=t=out:st={e:.3f}:d=0.12,apad=whole_dur={th:.3f},atrim=0:{th:.3f}[ab]")
    else:
        rc = rj[build_n]
        g = gain_to(RX / f"{rc['clip']}.mp4", rc["a"], th, -18)
        ins += ["-ss", f"{rc['a']:.3f}", "-t", f"{th + .3:.3f}", "-i", str(RX / f"{rc['clip']}.mp4")]
        fc.append(f"[{k}:a]atrim=0:{th:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,volume={g}dB,"
                  f"afade=t=out:st={th - .05:.3f}:d=0.05,apad=whole_dur={th:.3f},atrim=0:{th:.3f}[ab]")
    if not solo:
        a_parts.append("[ab]")
        k += 1
    pay = total - th
    if solo:
        pass
    elif r["script"][3] == "own":
        rc = rj[pay_n]
        g = gain_to(RX / f"{rc['clip']}.mp4", rc["a"], min(pay, rc["b"] - rc["a"]), -16)
        ins += ["-ss", f"{rc['a']:.3f}", "-t", f"{pay + .3:.3f}", "-i", str(RX / f"{rc['clip']}.mp4")]
    else:
        mp, ms, me = MEMES[r["meme"]]
        g = gain_to(mp, ms, me - ms, -16)
        ins += ["-ss", f"{ms:.3f}", "-t", f"{me - ms:.3f}", "-i", str(mp)]
    if not solo:
        fc.append(f"[{k}:a]asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,volume={g}dB,apad=whole_dur={pay:.3f},atrim=0:{pay:.3f},"
                  f"afade=t=out:st={pay - .25:.3f}:d=0.25[ap]")
        a_parts.append("[ap]")
        k += 1
        fc.append("".join(a_parts) + "concat=n=2:v=0:a=1[voice]")
    bf, bt = r["bed"]
    gb = gain_to(K.SRC / bf, bt, total, -31)
    ins += ["-ss", f"{bt:.3f}", "-t", f"{total + .3:.3f}", "-i", str(K.SRC / bf)]
    fc.append(f"[{k}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,volume={gb}dB[bed]")
    k += 1
    fc.append("[voice][bed]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89[a]")
    dest = out / f"{name}.mp4"
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
                    "-t", f"{total:.3f}", "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-c:a", "aac", "-b:a", "160k",
                    "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
                    "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=",
                    "-movflags", "+faststart", str(dest)], stdin=subprocess.PIPE)
    try:
        counter_frames(r, round(total * FPS), proc.stdin, cboxes)
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    if proc.wait() != 0:
        raise SystemExit(f"{name}: ffmpeg {proc.returncode}")
    plate_png.unlink()
    for bx in cboxes:
        if bad := check_box(W, H, bx):
            dest.unlink(missing_ok=True)
            raise SystemExit(f"{name}: счётчик вне безопасной зоны {bx} — {bad}")
    return dest


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--prep", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--tag", default="tt", choices=["tt", "yt"])
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("--range", default="")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "kolibri3_test")
    a = ap.parse_args()
    if a.prep:
        prep()
        return 0
    work = ROOT / "output" / "_work" / "kolibri3"
    work.mkdir(parents=True, exist_ok=True)
    a.out.mkdir(parents=True, exist_ok=True)
    if a.test:
        jobs = [(r, "tt") for r in plan(12, "tt", 3101)[:6]] + [(r, "yt") for r in plan(12, "yt", 3202)[6:12]]
    else:
        rows = plan(a.n, a.tag, 3101 if a.tag == "tt" else 3202)
        (work / f"plan_{a.tag}.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
        lo, hi = map(int, a.range.split("-")) if a.range else (1, a.n)
        jobs = [(r, a.tag) for r in rows if lo <= r["i"] <= hi]

    def safe(j):
        try:
            return render(j[0], a.out, work, j[1]), ""
        except BaseException as e:
            return None, str(e)[-400:]

    failed = []
    with ThreadPoolExecutor(a.jobs) as ex:
        for (r, tag), (dest, err) in zip(jobs, ex.map(safe, jobs)):
            if dest is None:
                failed.append(r["i"])
                print(f"  !! {tag} {r['i']:03d}: {err}", flush=True)
            else:
                print(f"  {dest.name}  text {r['text'] + 1}  {r['final']}  {r['script'][0]}→{r['script'][1]}  "
                      f"{r['meme'] if r['script'][3] == 'meme' else r['script'][3]}  {r['total']:.2f}s hit {r['t_hit']:.2f}", flush=True)
    print(f"готово: {len(jobs) - len(failed)} из {len(jobs)} → {a.out}" + (f"; не прошли: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
