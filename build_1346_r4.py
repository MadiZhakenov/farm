#!/usr/bin/env python3
"""
Раунд 4 (docs/REPOST_HYPOTHESES.md): гипотезы output/xmas_r3 на 5 роликах 1346 — оригинал + озвучка chipbot (downloads/1346/vo).
Кадр целиком, куски подогнаны под фразы озвучки, родные заголовки на месте, чужие призывы стёрты (clean_1346_cta.py), без плашки UNLOCK.
  R3-3d — история голосом, без субтитров; R3-6 — та же озвучка + карточка «Reply to …'s comment» на весь ролик;
  R3-7 — трогательная история + субтитры; R3-8 — полезный обзор + субтитры.
Субтитры — текст сценария (куски через « / »), тайминг — Whisper, внизу кадра. Звук: голос −15 LUFS + музыка 12 %.

Вариант B (--variant B, папки *_B) — та же озвучка, но визуально другой: заголовки стёрты (clean_1346_titles.py) и заново наложены
своим шрифтом сверху, кадр зеркальный (кроме кусков с читаемым текстом), куски дополнительно нарезаны ~каждые 1.6 с с чередованием
крупности и смещением кадра, лёгкая обработка цвета.

  python build_1346_r4.py --only v1 --hyp R3-3d,R3-7 --out output/1346_r4_test
  python build_1346_r4.py
  python build_1346_r4.py --variant B
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_xmas_r3_vo_story as VS  # noqa: E402  (sub_png)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
SRC, CLEAN, VO = (ROOT / "downloads" / "1346" / d for d in ("src", "src_clean", "vo"))
M = ROOT / "downloads"
OUT = ROOT / "output" / "1346_r4"
FOLDER = {"R3-3d": "R3-3d_vo_original", "R3-6": "R3-6_reply", "R3-7": "R3-7_vo_heart", "R3-8": "R3-8_vo_review"}
VIDEOS = {
    "v1": dict(slug="blanket", src="Christmas Coloring Blanket with Markers.mp4", music=M / "1303/music/gZIrKXCzue8.m4a", sub_y=0.73),
    "v2": dict(slug="cauldrons", src="Glowing Halloween Fog Cauldrons.mp4", music=M / "1285/music/m3_dies_irae_6705060426427664385.m4a", sub_y=0.73),
    "v3": dict(slug="gta_lamp", src="GTA Money Stack Lamp.mp4", music=M / "1330/music/m1_fleydan_7697990020683877138.mp3", sub_y=0.73),
    "v4": dict(slug="heels", src="Light-Up Christmas Heel Boots.mp4", music=M / "1303/music/gZIrKXCzue8.m4a", sub_y=0.73),
    "v5": dict(slug="water", src="Water Jug Cabinet Dispenser.mp4", music=M / "gw_pyramid/ref/pyramid_sound.m4a", sub_y=0.73),
}
# ролик_гипотеза → фразы: (текст; куски субтитров через « / »), [(от, до) в исходнике]
S = {
    "v1_3d": [("My husband said we did NOT need a coloring blanket.", [(0, 2.5)]), ("I bought it anyway.", [(2.5, 4.0)]),
              ("It came with its own markers.", [(4.0, 5.37)]), ("Now he's on the floor every night, coloring a gingerbread man.", [(5.37, 9.0)])],
    "v1_7": [("We hadn't had a night / without our phones / in years.", [(0, 2.5)]), ("Then I brought / this blanket home.", [(2.5, 4.0)]),
             ("One gingerbread man, / a box of markers,", [(4.0, 6.2)]), ("and for the first time / in months, / we actually talked.", [(6.2, 9.0)])],
    "v1_8": [("This is a blanket / you can actually color on.", [(0.5, 1.3), (5.37, 6.9)]), ("It comes rolled up / with a full set / of markers.", [(1.3, 2.5), (4.0, 4.7)]),
             ("Spread it out, / pick a drawing / and color it in.", [(2.5, 4.0), (4.7, 5.37)]), ("Perfect for a cozy night / or a Christmas gift.", [(6.9, 9.0)])],
    "v2_3d": [("Everyone at my party asked where I got these.", [(0, 1.37), (10.07, 11.8)]), ("In the daytime they look like plain black pots.", [(1.37, 3.4)]),
              ("Then the sun goes down, and the whole table starts to glow. Yes, the neighbors came to check.", [(11.8, 16.1)])],
    "v2_7": [("My daughter / was too scared / to go trick-or-treating / last year.", [(0, 2.6)]), ("So this Halloween, / we made the magic / at home.", [(3.07, 6.47)]),
             ("We set these up together,", [(10.07, 11.8)]), ("and when they lit up, / she wasn't / scared anymore.", [(11.8, 16.1)])],
    "v2_8": [("These cauldrons / make their own fog.", [(0, 1.37), (12.0, 12.8)]), ("Drop the little mist maker / inside,", [(3.07, 5.57)]),
             ("add the filling / and stir.", [(6.93, 8.7)]), ("Once it gets dark, / they glow blue, orange / and purple.", [(11.8, 14.23)]),
             ("Amazing on a table / or a porch.", [(14.23, 16.1)])],
    "v3_3d": [("Do NOT show this to a GTA fan.", [(0, 2.3)]), ("It's a lamp that looks like a giant stack of cash, and it changes color.", [(2.3, 7.5)]),
              ("My boyfriend put it next to his monitors", [(13.03, 15.5)]), ("and now he won't leave the room.", [(15.5, 18.7)])],
    "v3_7": [("My brother saved for years / to build his gaming setup.", [(0, 3.6)]), ("He never had money / for anything nice.", [(3.6, 7.0)]),
             ("So for his birthday, / I got him this.", [(10.27, 13.03)]), ("He looked at it and said, / finally, I made it.", [(14.5, 18.7)])],
    "v3_8": [("This lamp is shaped like / a stack of / hundred dollar bills.", [(1.6, 4.6)]),
             ("It glows white, blue / or gold / and sits on its own base.", [(4.6, 6.9), (0.3, 1.6), (13.03, 14.0)]),
             ("Put it on your desk / next to your monitors / and your whole / setup changes.", [(14.0, 18.7)])],
    "v4_3d": [("I went to the store for wrapping paper and came back with these.", [(0, 2.8)]), ("Yes, they light up.", [(3.67, 5.6)]),
              ("My friends saw them and bought the other two pairs.", [(6.1, 8.93)]), ("Now we're the brightest thing at every party.", [(8.93, 12.6)])],
    "v4_7": [("My best friend had / the hardest year / of her life.", [(0, 2.8)]), ("So I got us matching boots / for Christmas.", [(2.8, 5.6)]),
             ("When the lights came on / at the party,", [(6.1, 8.93)]), ("I saw her really smile / for the first time / in months.", [(8.93, 13.7)])],
    "v4_8": [("These knee-high / Christmas heels / actually light up.", [(2.8, 5.6)]), ("You can get candy cane, / bows, / or green / with colored lights.", [(6.1, 8.93)]),
             ("They come in a box / like this, / so they're an easy gift / for any girl.", [(0, 2.8), (8.93, 10.9)])],
    "v5_3d": [("My husband got tired of carrying water from the kitchen,", [(0, 2.4)]), ("so he hid a whole water jug inside this little table.", [(2.4, 4.67)]),
              ("Now there's a dispenser right next to our bed.", [(4.67, 8.4)])],
    "v5_7": [("My grandpa can't walk / to the kitchen anymore, / and he hated asking / for water,", [(0, 3.73)]), ("so we built this / right next to his bed.", [(6.6, 8.4)]),
             ("Now he pours / his own glass, / and he smiles every time.", [(3.73, 6.6)])],
    "v5_8": [("This side table is hiding / a full-size water jug.", [(4.67, 6.6)]), ("Drop the jug in, / close the lid / and put the pump on top.", [(0, 3.73)]),
             ("Now you've got water / right next to your sofa / or your bed.", [(3.73, 4.67), (6.6, 8.4)])],
}
# R3-6: (ник, вопрос, центр x, центр y)
REPLY = {"v1": ("ashley.cozyhome", "how did you get him to do this 😭", 540, 790), "v2": ("lauren.spooky", "where are these from 😭", 540, 350),
         "v3": ("tyler_setups", "what is that thing on your desk??", 540, 640), "v4": ("madison.holiday", "where did you get those 😭", 540, 540),
         "v5": ("jake.homefix", "wait where does the water go??", 540, 360)}
REPLY_PX, REPLY_COL = 44, 15
# ---- вариант B ----
SRC_B = ROOT / "downloads" / "1346" / "src_b"
TITLES = {"v1": ['"Babe, we DON\'T', 'need that" 😒', "Me: 🤩"], "v2": ["Everyone will ask", "where these are from 👀"],
          "v3": ["DON'T show this", "to a GTA FAN 🤫"], "v4": ["The Christmas heels", "every girl needs 🎄👠"],
          "v5": ["this table is", "hiding something 👀"]}
NO_FLIP = {"v1": [(4.0, 5.37)], "v2": [], "v3": [(10.27, 18.7)], "v4": [(0.0, 3.67)], "v5": []}       # читаемый текст — не зеркалим
HEAD_TOP = {"v1": [], "v2": [(10.07, 11.8)], "v3": [], "v4": [], "v5": []}                            # лица вверху — кадр от верха
# Без ИИ: вшитый текст не стираем, а оставляем за кадром кропом (ИИ-заливка плыла на узорах). (от, до, сторона, граница доли H):
# "top" — текст сверху, кадр начинается ниже границы; "bottom" — текст снизу, кадр кончается выше границы.
CROP_B = {"v1": [(0.0, 6.9, "top", 0.339), (6.9, 8.4, "top", 0.40), (8.4, 9.1, "top", 0.339)],
          "v2": [(0.0, 1.37, "top", 0.352)],
          "v3": [(0.0, 10.3, "top", 0.245), (12.9, 18.8, "bottom", 0.88)],
          "v4": [(0.0, 9.45, "top", 0.182), (9.45, 13.8, "top", 0.224)],
          "v5": [(6.6, 8.5, "bottom", 0.60)]}
CROP_A = {"v1": [], "v2": [], "v3": [], "v4": [(9.45, 13.8, "top", 0.224)], "v5": [(6.6, 8.5, "bottom", 0.60)]}
SPLIT_AT = {"v1": [6.9, 8.4], "v2": [1.37], "v3": [10.3], "v4": [9.45], "v5": [6.6]}                    # граница кропа = граница куска
GRADE = {"v1": "eq=contrast=1.06:saturation=1.1:gamma=1.02", "v2": "eq=contrast=1.08:saturation=1.12",
         "v3": "eq=contrast=1.05:saturation=1.08:brightness=0.01", "v4": "eq=contrast=1.06:saturation=1.1",
         "v5": "colorbalance=rs=.04:bs=-.03,eq=contrast=1.05:saturation=1.08"}
ZOOMS = (1.14, 1.3)
ANCHORS = ((0.5, 0.4), (0.3, 0.55), (0.7, 0.5), (0.5, 0.65))
PIECE = 1.6
TITLE_OFF_FROM = {"v1": 8.4}                                  # одеяло: в последнем шоте лица пары попадают под заголовок
TITLE_CY = {"v1": 0.165}                                    # одеяло: три строки, выше, чтобы не лезть на лицо девушки
REPLY_B_CY, REPLY_B_PX = 430, 48
WORDS = json.loads((VO / "_words.json").read_text(encoding="utf-8"))


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9']", "", s.lower().replace("’", "'"))


def source(v: str, variant: str = "A") -> Path:
    """B и сапоги/тумба в A — исходник без ИИ (текст уходит за кадр). Лампа в A — со стёртым «Link in bio» на чёрном фоне."""
    name = VIDEOS[v]["src"]
    if variant == "A" and v == "v3" and (CLEAN / name).exists():
        return CLEAN / name
    return SRC / name


def split_at(seg: list, marks: list[float]) -> list:
    """Режем куски исходника по границам кропа, чтобы кроп не захватывал соседний кадр."""
    out = list(seg)
    for t in marks:
        cur = []
        for a, b, s0, s1 in out:
            if s0 + 0.05 < t < s1 - 0.05:
                m = a + (b - a) * (t - s0) / (s1 - s0)
                cur += [(a, m, s0, t), (m, b, t, s1)]
            else:
                cur.append((a, b, s0, s1))
        out = cur
    return out


def split_pieces(seg: list) -> list:
    """Вариант B: длинные куски режем на части ~PIECE с, чтобы склеек и смен крупности было больше."""
    out = []
    for a, b, s0, s1 in seg:
        n = max(1, round((b - a) / PIECE))
        for k in range(n):
            out.append((a + (b - a) * k / n, a + (b - a) * (k + 1) / n, s0 + (s1 - s0) * k / n, s0 + (s1 - s0) * (k + 1) / n))
    return out


def crop_need(v: str, s0: float, s1: float, table: dict) -> list:
    return [c for c in table[v] if s0 < c[1] - 0.02 and s1 > c[0] + 0.02]


def fit(z: float, need: list, ay: float) -> tuple[float, float]:
    """Минимальный зум и положение кадра, при которых вшитый текст остаётся за кадром."""
    for _, _, side, lim in need:
        z = max(z, 1 / (1 - lim) if side == "top" else 1 / lim)
    for _, _, side, lim in need:
        if side == "top":
            ay = max(ay, min(1.0, lim / (1 - 1 / z)))
        else:
            ay = min(ay, max(0.0, (lim - 1 / z) / (1 - 1 / z)))
    return z, ay


def piece_vf(v: str, i: int, s0: float, s1: float, variant: str = "B") -> str:
    if variant == "A":
        need = crop_need(v, s0, s1, CROP_A)
        if not need:
            return ""
        z, ay = fit(1.0, need, 0.5)
        return f"crop=iw/{z:.4f}:ih/{z:.4f}:(iw-iw/{z:.4f})*0.5:(ih-ih/{z:.4f})*{ay:.4f},"
    mid = (s0 + s1) / 2
    ax, ay = ANCHORS[i % 4]
    if any(a <= mid <= b for a, b in HEAD_TOP[v]):
        ay, ax = 0.0, 0.5
    need = crop_need(v, s0, s1, CROP_B)
    z, _ = fit(ZOOMS[i % 2], need, ay)
    if need and i % 2 and z < 1.45:
        z *= 1.08                                        # чередование крупности и там, где зум задан текстом
    z, ay = fit(z, need, ay)
    flip = "" if any(a <= mid <= b for a, b in NO_FLIP[v]) else "hflip,"
    return f"{flip}crop=iw/{z:.4f}:ih/{z:.4f}:(iw-iw/{z:.4f})*{ax}:(ih-ih/{z:.4f})*{ay:.4f},"


def word_times(script: list[str], key: str) -> list[float]:
    """Время начала каждого слова сценария: совпадения со словами Whisper + интерполяция между ними."""
    ww = WORDS[key]["words"]
    sm = difflib.SequenceMatcher(None, [norm(x) for x in script], [norm(w[0]) for w in ww], autojunk=False)
    hit: dict[int, float] = {}
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            hit[a + k] = float(ww[b + k][1])
    if len(hit) < 0.8 * len(script):
        raise SystemExit(f"{key}: совпало слов {len(hit)} из {len(script)} — файл не тот?")
    known = sorted(hit)
    out = []
    for i in range(len(script)):
        if i in hit:
            out.append(hit[i])
            continue
        lo = max((k for k in known if k < i), default=None)
        hi = min((k for k in known if k > i), default=None)
        if lo is None:
            out.append(0.0)
        elif hi is None:
            out.append(hit[lo] + 0.3 * (i - lo))
        else:
            out.append(hit[lo] + (hit[hi] - hit[lo]) * (i - lo) / (hi - lo))
    return out


def plan(key: str) -> tuple[list[tuple[float, float, float, float]], list[tuple[float, float, str]], float]:
    """Сегменты (VO от, до, исходник от, до) и субтитры (от, до, текст)."""
    phrases = S[key]
    script, first, chunks = [], [], []
    for text, _ in phrases:
        first.append(len(script))
        for ch in text.split(" / "):
            chunks.append((len(script), ch))
            script += ch.split()
    t = word_times(script, key)
    total = round(WORDS[key]["dur"] + 0.25, 3)
    starts = [0.0 if j == 0 else t[i] for j, i in enumerate(first)] + [total]
    seg = []
    for j, (_, ranges) in enumerate(phrases):
        a0, b0 = starts[j], starts[j + 1]
        length = sum(e - s for s, e in ranges)
        a = a0
        for s, e in ranges:
            b = a + (b0 - a0) * (e - s) / length
            seg.append((a, b, s, e))
            a = b
    subs = []
    for k, (i, text) in enumerate(chunks):
        a = t[i]
        b = t[chunks[k + 1][0]] if k + 1 < len(chunks) else total
        subs.append((a, b, text))
    return seg, subs, total


def reply_png(v: str, dest: Path, variant: str = "A") -> tuple[int, int]:
    import core.comment_sticker as CS
    nick, text, cx, cy = REPLY[v]
    if variant == "B":
        cy = REPLY_B_CY
    CS.COLUMN_MAX = REPLY_COL
    img = CS.render_reply_sticker(nick, text, body_px=REPLY_B_PX if variant == "B" else REPLY_PX, avatar_seed=nick)
    img.save(dest)
    x, y = int(cx - img.width / 2), int(cy - img.height / 2)
    x = max(140 - 12, min(x, 940 + 12 - img.width))
    if bad := check_box(W, H, (x + 14, y + 10, x + img.width - 14, y + img.height - 10)):
        raise SystemExit(f"карточка вне безопасной зоны: {v} {bad}")
    return x, y


def build(v: str, hyp: str, out: Path, work: Path, variant: str = "A") -> Path:
    h = {"R3-3d": "3d", "R3-6": "3d", "R3-7": "7", "R3-8": "8"}[hyp]
    key = f"{v}_{h}"
    seg, subs, total = plan(key)
    seg = split_at(seg, SPLIT_AT[v])
    if variant == "B":
        seg = split_pieces(seg)
    src = source(v, variant)
    inputs, fc, speeds = [], [], []
    for i, (a, b, s0, s1) in enumerate(seg):
        nfr = round(b * FPS) - round(a * FPS)
        k = (nfr / FPS) / (s1 - s0)
        speeds.append(round(1 / k, 2))
        inputs += ["-ss", f"{s0:.3f}", "-t", f"{s1 - s0 + 0.2:.3f}", "-i", str(src)]
        pre = piece_vf(v, i, s0, s1, variant)
        post = f",unsharp=5:5:0.5,{GRADE[v]}" if variant == "B" else (",unsharp=5:5:0.5" if pre else "")
        fc.append(f"[{i}:v]setpts={k:.4f}*(PTS-STARTPTS),fps={FPS},{pre}scale={W}:{H}:flags=lanczos{post},setsar=1,"
                  f"trim=end_frame={nfr},setpts=PTS-STARTPTS[t{i}]")
    n = len(seg)
    fc.append("".join(f"[t{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0,format=yuv420p[b0]")
    cur, idx = "b0", n
    tmp = []
    if variant == "B" and hyp != "R3-6":                 # свой заголовок сверху, на весь ролик
        import xmas_r3_common as XC
        XC.TITLE[v] = TITLES[v]
        XC.TITLE_CY = TITLE_CY.get(v, 0.235)
        tpng = work / f"{v}_{hyp}_title.png"
        tx, ty = XC.title_png(v, tpng)
        tmp.append(tpng)
        inputs += ["-i", str(tpng)]
        hide = [(x, y) for x, y, s0, _ in seg if s0 >= TITLE_OFF_FROM.get(v, 1e9) - 0.01]      # лица под заголовком — на этих кусках его нет
        en = (":enable='not(" + "+".join(f"between(t,{x:.3f},{y:.3f})" for x, y in hide) + ")'") if hide else ""
        fc.append(f"[{cur}][{idx}:v]overlay={tx}:{ty}{en}[ti]")
        cur, idx = "ti", idx + 1
    if hyp == "R3-6":
        card = work / f"{v}_{hyp}_reply.png"
        x, y = reply_png(v, card, variant)
        tmp.append(card)
        inputs += ["-i", str(card)]
        fc.append(f"[{cur}][{idx}:v]overlay={x}:{y}[rc]")
        cur, idx = "rc", idx + 1
    if hyp in ("R3-7", "R3-8"):
        for j, (a, b, text) in enumerate(subs):
            png = work / f"{v}_{hyp}_s{j:02d}.png"
            x, y = VS.sub_png(text, png, VIDEOS[v]["sub_y"])
            tmp.append(png)
            inputs += ["-i", str(png)]
            fc.append(f"[{cur}][{idx}:v]overlay={x}:{y}:enable='between(t,{a:.3f},{min(b, total):.3f})'[o{j}]")
            cur, idx = f"o{j}", idx + 1
    vo = VO / WORDS[key]["file"]
    inputs += ["-i", str(vo), "-stream_loop", "-1", "-i", str(VIDEOS[v]["music"])]
    fc.append(f"[{idx}:a]aresample=44100,loudnorm=I=-15:TP=-1.5:LRA=11,apad[vo];[{idx + 1}:a]aresample=44100,volume=0.12[m];"
              f"[vo][m]amix=inputs=2:normalize=0:duration=first,atrim=0:{total:.3f},afade=t=out:st={total - 0.3:.3f}:d=0.3[a]")
    tag = "_B" if variant == "B" else ""
    dest = out / f"{FOLDER[hyp]}{tag}" / f"{hyp}_{v}_{VIDEOS[v]['slug']}{tag}_noid.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
                    "-map", f"[{cur}]", "-map", "[a]", "-t", f"{total:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    for p in tmp:
        p.unlink()
    print(f"  {dest.name}  {total:.1f} с  скорость кусков {speeds}", flush=True)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--only", default="v1,v2,v3,v4,v5")
    ap.add_argument("--hyp", default="R3-3d,R3-6,R3-7,R3-8")
    ap.add_argument("--variant", default="A", choices=("A", "B"))
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = ROOT / "output" / "_work" / "1346_r4"
    work.mkdir(parents=True, exist_ok=True)
    for v in a.only.split(","):
        for hyp in a.hyp.split(","):
            build(v, hyp, a.out, work, a.variant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
