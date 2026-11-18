#!/usr/bin/env python3
"""
1309 (2026-10-23) — как output/1309_500 (build_1309_reels.py: белый фон, подпись сверху / геймплей / карточка
комментария снизу, логотип в левом нижнем углу, промокод без озвучки внизу геймплея по центру), но:
  — 8 с; в начале ВСЕГДА один из моментов с двумя парнями (Paired_01/02/03/06/07, по очереди, целиком);
  — моментов «парень с девушкой» нет вообще (Interaction2_01/02/03/04/06/07/08);
  — новые подписи (3) и комментарии (5) — дословно, без переносов по смыслу: перенос по ширине, как в твите (1310);
  — комментарий статичный с первого кадра (без анимации);
  — музыка — та же Safe and Sound (IG audio 423866028123501) с 0:53, 8 с;
  — YouTube 200 (шрифты как в 1309) и TikTok 200 (все шрифты — TikTok Sans), видеоряды не повторяются между ними.

  python build_1309_dance_reels.py --test
  python build_1309_dance_reels.py --jobs 3      # → output/1309_YT_200 (1001…1200) + output/1309_TT_200 (1201…1400)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1309_reels as B  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

ID = "1309"
B.ID = ID
B.TOTAL = 8.0
TT_FONTS = B.FONTS                                     # fonts/TikTokSans/…/ttf
if os.environ.get("OS1309_FONT") == "tiktok":          # TikTok-версия: все шрифты — TikTok Sans
    B.F_CAP = B.F_MED = TT_FONTS / "TikTokSans12pt-SemiBold.ttf"
    B.F_REG = TT_FONTS / "TikTokSans12pt-Regular.ttf"
    B.F_BOLD = TT_FONTS / "TikTokSans12pt-Bold.ttf"
    from PIL import ImageFont
    B.font = lambda path, px: ImageFont.truetype(str(path), px)   # статичные файлы, без осей вариативного шрифта
SRC_MUSIC = B.D / "music" / "ig_audio_423866028123501.mp3"
B.MUSIC = B.D / "music" / "music_53-61s_-14lufs.wav"   # Safe and Sound, 0:53–1:01, −14 LUFS
# комментарий — статичный с первого кадра (клиент 2026-10-23: без анимации)
BANNER_T = 1.0                                          # промокод с 1-й с до конца ролика
# в начало ролика — только эти моменты (клиент 2026-10-23), по очереди поровну
OPENERS = ("Paired_01_", "Paired_02_", "Paired_06_", "Paired_07_")   # Paired_03 убран: у края девушка
# одно и то же место в разных моментах — подряд не ставим (лошадь, граффити, сцена)
SAME_PLACE = [("Paired_02_", "Paired_07_"), ("Paired_03_", "Paired_10_"), ("Paired_04_", "Paired_09_")]
# ВСЕ моменты, где в кадре есть девушка (клиент 2026-10-23): «парень с девушкой» (Interaction2_*), танцпол (Paired_05),
# граффити с девушкой у края (Paired_03/10), сцена с танцовщицами (Paired_04), клуб со столиками (Paired_08),
# кадеты (Interaction_04), ресепшен (Interaction_05), больница (Interaction_06), аудитория медиков (Interaction_08)
NO_GIRL = tuple(f"Interaction2_0{k}_" for k in (1, 2, 3, 4, 6, 7, 8)) + (
    "Paired_03_", "Paired_04_", "Paired_05_", "Paired_08_", "Paired_10_",
    "Interaction_04_", "Interaction_05_", "Interaction_06_", "Interaction_08_")

CAPTIONS_RAW = [
    "guys someone just did THIS in a mobile game and then left this comment 😭",
    "guys someone just did this in a MOBILE game and then left this comment 💀",
    "guys look what someone did in a mobile game and what they wrote in the comments 👀 I CAN'T",
]
COMMENTS_RAW = [
    "i just wanted to check this game for 5 minutes. a random guy waved at me from his car, i got in, and we drove "
    "around the city for 3 hours talking about life. he's from brazil. i have work tomorrow",
    "a random guy in this game honked at me, so i got in. he drove me around the whole city like a tour guide. then "
    "said \"gotta go, mom is calling me for dinner\"",
    "i was driving like an idiot and a cop pulled me over and said \"kid, you good?\" then let me go. i've been a good "
    "driver ever since",
    "a guy gave me a free outfit and said \"you looked sad\". i wasn't, i was just AFK. wore it all day anyway",
    "met my friend here 3 years ago and lost contact. yesterday i walked into a bar and he was sitting there. i said "
    "\"bro\". he said \"bro\". i'm crying",
]


def wrap_width(text: str, path: Path, px: int, max_w: int) -> list[str]:
    """Обычный перенос по ширине (слово не влезает — на новую строку), как в 1310."""
    f = B.font(path, px)
    lines, cur = [], ""
    for w in text.split():
        cand = f"{cur} {w}" if cur else w
        if cur and B.line_w(cand, f, px) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    return lines + [cur]


B.CAP_PX = 48
B.CAPTIONS = [wrap_width(t, B.F_CAP, B.CAP_PX, B.X1 - B.X0) for t in CAPTIONS_RAW]
B.COMMENTS = [wrap_width(t, B.F_REG, B.CMT_PX, B.X1 - B.X0) for t in COMMENTS_RAW]


def music() -> None:
    if B.MUSIC.exists():
        return
    meas = subprocess.run([B.FF, "-hide_banner", "-nostats", "-ss", "53", "-t", f"{B.TOTAL}", "-i", str(SRC_MUSIC),
                           "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                          capture_output=True, text=True).stderr
    js = json.loads(meas[meas.rindex("{"):meas.rindex("}") + 1])
    ln = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={js['input_i']}:measured_TP={js['input_tp']}:"
          f"measured_LRA={js['input_lra']}:measured_thresh={js['input_thresh']}:offset={js['target_offset']}:linear=true")
    subprocess.run([B.FF, "-v", "error", "-y", "-ss", "53", "-t", f"{B.TOTAL}", "-i", str(SRC_MUSIC), "-af",
                    f"{ln},afade=t=in:d=0.05,afade=t=out:st={B.TOTAL - 0.4}:d=0.4", "-ar", "48000", "-ac", "2",
                    str(B.MUSIC)], check=True)


# ---------------- план ----------------
def plan(count: int) -> list[dict]:
    """Ролик = один из OPENERS целиком (по очереди) + другие моменты подряд (без «парень с девушкой»), последний
    обрезан → ровно 8 с; одно место подряд не повторяется. Видеоряды всех роликов (YT и TT вместе) не повторяются."""
    rng = random.Random(13092)
    mom = B.moments()
    ops, allseq = sequences(mom, rng)
    avatars = [p for d in B.AVATAR_DIRS if d.is_dir() for p in sorted(d.glob("*.jpg")) if not p.name.startswith("_")]
    rng.shuffle(avatars)
    use: dict = {}
    jobs = []
    for n in range(count):
        cap, cmt = n % len(B.CAPTIONS), (n // len(B.CAPTIONS)) % len(B.COMMENTS)
        o = ops[n % len(ops)]                                   # начала — по очереди, поровну
        seq = pick(allseq[o], use, rng)
        jobs.append({"n": n + 1, "caption": cap, "comment": cmt, "moments": [[mom[i]["file"], d, st] for i, d, st in seq],
                     "person": list(B.PEOPLE[(n + 29) % len(B.PEOPLE)]), "avatar": str(avatars[n % len(avatars)]),
                     "seed": rng.randint(0, 10 ** 6)})
    return jobs


def pick(cand: list, use: dict, rng: random.Random) -> list:
    """Наименее использованные моменты (по сумме, второй момент — с весом); выбранный ряд убираем из кандидатов."""
    if not cand:
        raise SystemExit("кончились варианты видеоряда")
    k = min(range(len(cand)), key=lambda q: sum(use.get(x[0], 0) for x in cand[q][1:])
            + 2 * use.get(("second", cand[q][1][0]), 0) + rng.random())
    seq = cand.pop(k)
    for x in seq[1:]:
        use[x[0]] = use.get(x[0], 0) + 1
    use[("second", seq[1][0])] = use.get(("second", seq[1][0]), 0) + 1
    return seq


def sequences(mom: list, rng: random.Random) -> tuple[list[int], dict[int, list]]:
    """Все возможные видеоряды по каждому началу: целые моменты подряд, последний обрезан до остатка (≥ MIN_LAST) —
    его кусок берём с начала, из середины или с конца момента. Элемент ряда: [момент, длина, начало внутри момента]."""
    ops = [i for i, m in enumerate(mom) if m["file"].startswith(OPENERS)]
    assert len(ops) == len(OPENERS)
    pool = [i for i, m in enumerate(mom) if not m["file"].startswith(NO_GIRL)]
    place = {}
    for g, names in enumerate(SAME_PLACE):
        for i, m in enumerate(mom):
            if m["file"].startswith(names):
                place[i] = g
    near = lambda a, b: a in place and place.get(b) == place[a]  # noqa: E731
    allseq: dict[int, list[list[list]]] = {o: [] for o in ops}

    def dfs(o: int, seq: list, rem: float) -> None:
        for i in pool:
            if any(i == s[0] for s in seq) or near(seq[-1][0], i):
                continue
            d = mom[i]["dur"]
            if d < rem - 1e-6:
                if rem - d >= B.MIN_LAST:
                    dfs(o, seq + [[i, d, 0.0]], rem - d)
            elif rem >= B.MIN_LAST:
                    spare = d - rem
                    starts = [0.0] + ([spare / 2] if spare >= 1.5 else []) + ([spare] if spare >= 0.6 else [])
                    for st in starts:
                        allseq[o].append(seq + [[i, round(rem, 3), round(int(st * B.FPS) / B.FPS, 3)]])

    for o in ops:
        dfs(o, [[o, mom[o]["dur"], 0.0]], B.TOTAL - mom[o]["dur"])
        rng.shuffle(allseq[o])
    print("вариантов видеоряда по началу:", {mom[o]["file"][:9]: len(v) for o, v in allseq.items()}, flush=True)
    return ops, allseq


def fix(workers: int) -> None:
    """Ролики, где есть запрещённый момент (NO_GIRL), — новый видеоряд с тем же началом (подпись, комментарий,
    автор, логотип — прежние), не повторяющий ни один ряд из обеих папок; пересобираем только их."""
    mom = B.moments()
    idx = {m["file"]: i for i, m in enumerate(mom)}
    rng = random.Random(13093)
    ops, allseq = sequences(mom, rng)
    folders = {"default": ROOT / "output" / f"{ID}_YT_200", "tiktok": ROOT / "output" / f"{ID}_TT_200"}
    mans = {f: json.loads((p / "manifest.json").read_text(encoding="utf-8")) for f, p in folders.items()}
    alljobs = [j for m in mans.values() for j in m]
    bad = [j for j in alljobs if any(x[0].startswith(NO_GIRL) for x in j["moments"])]
    good = [j for j in alljobs if j not in bad]
    taken = {tuple((idx[x[0]], x[1], x[2] if len(x) > 2 else 0.0) for x in j["moments"]) for j in good}
    use: dict = {}
    for j in good:
        for x in j["moments"][1:]:
            use[idx[x[0]]] = use.get(idx[x[0]], 0) + 1
    for o in ops:
        allseq[o] = [s for s in allseq[o] if tuple(tuple(x) for x in s) not in taken]
    for j in bad:
        o = idx[j["moments"][0][0]]
        seq = pick(allseq[o], use, rng)
        j["moments"] = [[mom[i]["file"], d, st] for i, d, st in seq]
    print(f"пересобираю {len(bad)} роликов: " + ", ".join(str(j["n"]) for j in bad), flush=True)
    for font, p in folders.items():
        (p / "manifest.json").write_text(json.dumps(mans[font], indent=1, ensure_ascii=False), encoding="utf-8")
        todo = [j for j in bad if j in mans[font]]
        if todo:
            run(todo, p, font, workers, manifest=False)


# ---------------- рендер (как B.build, но комментарий выезжает, 8 с, промокод с 1 с) ----------------
def build(job: dict) -> str:
    work = Path(tempfile.mkdtemp(prefix="r1309d_"))
    rng = random.Random(job["seed"])
    cap_png, card, logo = work / "cap.png", work / "card.png", work / "logo.png"
    cap_bottom = B.caption_png(job["caption"], cap_png)
    card_h = B.card_png(job["comment"], tuple(job["person"]), Path(job["avatar"]), card)
    card_top = B.CARD_BOTTOM - card_h
    band = (cap_bottom + B.GAP, card_top - B.GAP)
    bh = band[1] - band[0]
    bh -= bh % 2
    lx, ly, _lr = B.logo_png(rng, (band[0], band[0] + bh), logo)
    cw, ch = B.banner_anim()
    bx = (B.W - cw) // 2
    by = band[0] + bh - 16 - ch + round(ch * 0.06)
    inputs, parts = [], []
    for k, mm in enumerate(job["moments"]):
        name, d = mm[0], mm[1]
        sf = round((mm[2] if len(mm) > 2 else 0.0) * B.FPS)
        inputs += ["-i", str(B.SCENES / name)]
        parts.append(f"[{k}:v]fps={B.FPS},scale={B.W}:{bh}:flags=lanczos:force_original_aspect_ratio=increase,crop={B.W}:{bh},tpad=stop_mode=clone:stop=3,"
                     f"trim=start_frame={sf}:end_frame={sf + round(d * B.FPS)},setpts=PTS-STARTPTS,setsar=1[v{k}]")
    nm = len(job["moments"])
    inputs += ["-loop", "1", "-i", str(cap_png), "-loop", "1", "-i", str(card), "-loop", "1", "-i", str(logo),
               "-i", str(B.BANNER_ANIM), "-i", str(B.MUSIC)]
    ic, ik, il, ib = nm, nm + 1, nm + 2, nm + 3
    parts += [
        "".join(f"[v{k}]" for k in range(nm)) + f"concat=n={nm}:v=1:a=0[g]",
        f"color=white:s={B.W}x{B.H}:r={B.FPS}:d={B.TOTAL}[bg]",
        f"[bg][g]overlay=0:{band[0]}:shortest=1[s1]",
        f"[s1][{il}:v]overlay={lx}:{ly}[s2]",
        f"[s2][{ic}:v]overlay=0:0:shortest=1[s3]",
        f"[s3][{ik}:v]overlay=0:{card_top}:shortest=1[s4]",
        f"[{ib}:v]fps={B.FPS},format=yuva420p,setpts=PTS-STARTPTS+{BANNER_T:.3f}/TB[bn]",
        f"[s4][bn]overlay={bx}:{by}:eof_action=pass,format=yuv420p,{SET_SDR}[v]",
    ]
    dest = Path(job["out"]) / f"{job['n']:04d}_{ID}.mp4"
    subprocess.run([B.FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[v]", "-map",
                    f"{ib + 1}:a", "-t", f"{B.TOTAL}", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r",
                    str(B.FPS), *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k", "-map_metadata", "-1", "-movflags",
                    "+faststart", str(dest)], check=True)
    return f"{dest.name}: подпись {job['caption'] + 1}, комм. {job['comment'] + 1}, моментов {nm}"


def run(jobs: list[dict], out: Path, font: str, workers: int, manifest: bool = True) -> None:
    os.environ["OS1309_FONT"] = font                    # дочерние процессы заново импортируют модуль с этим шрифтом
    out.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        j["out"] = str(out)
        j["font"] = font
    if manifest:
        (out / "manifest.json").write_text(json.dumps(jobs, indent=1, ensure_ascii=False), encoding="utf-8")
    with ProcessPoolExecutor(workers) as ex:
        for k, msg in enumerate(ex.map(build, jobs), 1):
            print(f"[{font} {k}/{len(jobs)}] {msg}", flush=True)
    print("готово →", out, flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--yt", type=int, default=200)
    ap.add_argument("--tt", type=int, default=200)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--fix", action="store_true", help="пересобрать только ролики с запрещёнными моментами")
    a = ap.parse_args()
    B.banner_anim()
    music()
    if a.fix:
        fix(a.jobs)
        return 0
    jobs = plan(a.yt + a.tt)
    for j in jobs:
        j["n"] += 1000                                   # 1001… — не пересекается с прошлыми 1309 (1…1000)
    yt, tt = jobs[:a.yt], jobs[a.yt:]
    assert all(j["moments"][0][0].startswith(OPENERS) for j in jobs)
    assert not any(m[0].startswith(NO_GIRL) for j in jobs for m in j["moments"])
    if a.test:
        run(yt[:3], ROOT / "output" / "1309_dance_test", "default", a.jobs)
        run(tt[:3], ROOT / "output" / "1309_dance_test", "tiktok", a.jobs)
        return 0
    run(yt, ROOT / "output" / f"{ID}_YT_{a.yt}", "default", a.jobs)
    run(tt, ROOT / "output" / f"{ID}_TT_{a.tt}", "tiktok", a.jobs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
