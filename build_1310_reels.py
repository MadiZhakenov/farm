#!/usr/bin/env python3
"""
1310 — OneState, как финальный 1309 (build_1309_reels.py: белый фон, подпись сверху / геймплей / карточка комментария
снизу без анимации, логотип в левом нижнем углу с тенью, промокод без озвучки внизу геймплея по центру, музыка
0:53–1:08, 15 с), но:
  — в каждом ролике обязательно полицейский участок: минимум один из моментов Interaction_01–04 (тир/дверь,
    кабинет с флагами, комната с мониторами, кадеты на лекции), в случайном месте ролика; остальное — любые моменты;
  — 3 новых комментария про полицию (дословно; «Верх:» во 2-м — пометка клиента, не текст).

  python build_1310_reels.py --test
  python build_1310_reels.py --count 500 --jobs 6
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1309_reels as B  # noqa: E402

ID = "1310"
B.ID = ID
B.MUSIC = B.D / "music" / "1310_music_11s_-14lufs.wav"   # своя музыка 1310 (ReelAudio-26071.mp3), 0:00–0:11, −14 LUFS
# тексты ТЗ дословно, БЕЗ логических переносов (клиент): сплошной текст, перенос по ширине колонки, как в твите
CAPTIONS_RAW = [                                      # новые подписи клиента 2026-10-20, дословно (с «(till the end)»)
    "people online lost it after seeing the new graphics in this game 🔥👀(till the end)",
    "nobody expected a mobile game to look like this (till the end)",
    "this update broke the comment section (till the end)",
    "people can’t believe this is running on a phone 👀",
    "nobody believes me when I say this is a phone game",
]
COMMENTS_RAW = [
    "real job: 9 to 5 and nobody says thank you. OneState job: I arrest my best friend for speeding 💀",
    "POV: it’s your first day at the police station and you have no idea what you’re doing",
    "“what do you wanna be when you grow up?” me, 6: “a police officer” me, 24: “I’m doing it on my phone” 💀",
]


def wrap_width(text: str, path: Path, px: int, max_w: int) -> list[str]:
    """Обычный перенос по ширине (слово не влезает — на новую строку)."""
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


B.CAP_PX = 48                                        # при 48 px все 5 подписей — в 2 строки (эмодзи не висят отдельно)
B.CAPTIONS = [wrap_width(t, B.F_CAP, B.CAP_PX, B.X1 - B.X0) for t in CAPTIONS_RAW]
B.COMMENTS = [wrap_width(t, B.F_REG, B.CMT_PX, B.X1 - B.X0) for t in COMMENTS_RAW]
POLICE = ("Interaction_01_", "Interaction_02_", "Interaction_03_", "Interaction_04_")
# клиент: копы — В САМОМ НАЧАЛЕ, 3–4 с одним моментом: дверь/тир (3.9 с), комната с мониторами (3.8 с) целиком,
# кабинет с флагами (5.5 с) — первые 4 с; кадеты (1.4 с) в начало не годятся
OPENERS = {"Interaction_01_": None, "Interaction_03_": None, "Interaction_02_": 4.0}


NEW_VIDEO_FROM = 0       # с этого номера видеоряд не повторяет ни один из предыдущих роликов (доп. партии)


def plan(count: int) -> list[dict]:
    """Ролик начинается с полицейского момента 3–4 с (OPENERS, по очереди), дальше любые моменты до 11 с."""
    rng = random.Random(1310)
    mom = B.moments()
    police = [i for i, m in enumerate(mom) if m["file"].startswith(tuple(OPENERS))]
    open_dur = {i: OPENERS[next(k for k in OPENERS if mom[i]["file"].startswith(k))] or mom[i]["dur"] for i in police}
    avatars = [p for d in B.AVATAR_DIRS if d.is_dir() for p in sorted(d.glob("*.jpg")) if not p.name.startswith("_")]
    rng.shuffle(avatars)
    use: dict = {}
    seen: set = set()
    seen_video: set = set()
    jobs = []
    for n in range(count):
        cap, cmt = n % len(B.CAPTIONS), (n // len(B.CAPTIONS)) % len(B.COMMENTS)
        for _ in range(500):
            p = min(police, key=lambda i: use.get(i, 0) + rng.random() * 2)
            seq, total = [], open_dur[p]
            order = sorted((i for i in range(len(mom)) if i != p), key=lambda i: use.get(i, 0) + rng.random() * 3)
            for i in order:
                rem = B.TOTAL - total
                d = mom[i]["dur"]
                if d < rem - 1e-6:
                    if rem - d < B.MIN_LAST:
                        continue
                    seq.append([i, d])
                    total += d
                elif rem >= B.MIN_LAST:
                    seq.append([i, round(rem, 3)])
                    total = B.TOTAL
                    break
            if abs(total - B.TOTAL) > 1e-3 or not seq:
                continue
            seq.insert(0, [p, open_dur[p]])                               # копы — первыми
            key = (cap, cmt, tuple(tuple(x) for x in seq))
            vkey = tuple(tuple(x) for x in seq)
            if key not in seen and not (NEW_VIDEO_FROM and n >= NEW_VIDEO_FROM and vkey in seen_video):
                break
        seen.add(key)
        seen_video.add(tuple(tuple(x) for x in seq))
        for i, _d in seq:
            use[i] = use.get(i, 0) + 1
        jobs.append({"n": n + 1, "caption": cap, "comment": cmt,
                     "moments": [[mom[i]["file"], d] for i, d in seq],
                     "person": list(B.PEOPLE[(n + 17) % len(B.PEOPLE)]), "avatar": str(avatars[n % len(avatars)]),
                     "seed": rng.randint(0, 10 ** 6)})
    return jobs


# 12.11.2026 клиент: ещё 100 TT + 100 YT, но ПЕРВЫЙ клип — танец. Танцы в футаже (downloads/1309/scenes): брейк у граффити
# (Paired_03 2.1 с, Paired_10 4.6 с), девушки на сцене (Paired_04 1.7 с), танцпол клуба (Paired_05 7.2 с — первые 3.5 с),
# двое парней у синей лошади (Paired_07 2.1 с). Сразу после танца — копы (полицейский момент обязателен в 1310), дальше
# любые моменты до 11 с. Все прошлые партии (1310_500, 1310_YT_500, onestate_1310_TT/YT_100) начинаются с копов —
# танцевальные видеоряды новые по определению; дополнительно сверяем, что ни один не совпадает с прошлыми.
# Paired_07 (двое у синей лошади) — НЕ танец (юзер 12.11), убран
DANCE = {"Paired_03_": None, "Paired_04_": None, "Paired_05_": 3.5, "Paired_10_": None}
POLICE_DUR = {"Interaction_01_": None, "Interaction_02_": 4.0, "Interaction_03_": None, "Interaction_04_": None}
PREV_MANIFESTS = [ROOT / "output" / "1310_500" / "manifest.json", ROOT / "output" / "1310_YT_500" / "manifest.json",
                  ROOT / "output" / "_work" / "onestate_new" / "manifest_onestate_1310_TT_100.json",
                  ROOT / "output" / "_work" / "onestate_new" / "manifest_onestate_1310_YT_100.json"]


def plan_dance(count: int, first_n: int) -> list[dict]:
    rng = random.Random(13102)
    mom = B.moments()
    pick = lambda pref: [i for i, m in enumerate(mom) if m["file"].startswith(tuple(pref))]   # noqa: E731
    dances, police = pick(DANCE), pick(POLICE_DUR)
    dur_of = lambda i, table: next((table[k] for k in table if mom[i]["file"].startswith(k)), None) or mom[i]["dur"]  # noqa: E731
    prev = set()
    for mp in PREV_MANIFESTS:
        if mp.exists():
            prev |= {tuple(tuple(x) for x in j["moments"]) for j in json.loads(mp.read_text(encoding="utf-8"))}
    avatars = [p for d in B.AVATAR_DIRS if d.is_dir() for p in sorted(d.glob("*.jpg")) if not p.name.startswith("_")]
    rng.shuffle(avatars)
    use: dict = {}
    seen: set = set()
    jobs = []
    for k in range(count):
        n = first_n + k
        cap, cmt = k % len(B.CAPTIONS), (k // len(B.CAPTIONS)) % len(B.COMMENTS)
        d0 = dances[k % len(dances)]                                   # танцы по кругу — поровну
        for _ in range(2000):
            pol = min(police, key=lambda i: use.get(i, 0) + rng.random() * 2)
            seq = [[d0, dur_of(d0, DANCE)], [pol, dur_of(pol, POLICE_DUR)]]
            total = sum(x[1] for x in seq)
            order = sorted((i for i in range(len(mom)) if i not in (d0, pol)), key=lambda i: use.get(i, 0) + rng.random() * 3)
            for i in order:
                rem = B.TOTAL - total
                d = mom[i]["dur"]
                if d < rem - 1e-6:
                    if rem - d < B.MIN_LAST:
                        continue
                    seq.append([i, d])
                    total += d
                elif rem >= B.MIN_LAST:
                    seq.append([i, round(rem, 3)])
                    total = B.TOTAL
                    break
            if abs(total - B.TOTAL) > 1e-3:
                continue
            vkey = tuple((mom[i]["file"], d) for i, d in seq)
            if vkey not in seen and vkey not in prev:
                break
        else:
            raise SystemExit(f"ролик {n}: не нашлось нового видеоряда")
        seen.add(vkey)
        for i, _d in seq:
            use[i] = use.get(i, 0) + 1
        jobs.append({"n": n, "caption": cap, "comment": cmt, "moments": [[mom[i]["file"], d] for i, d in seq],
                     "person": list(B.PEOPLE[(n + 17) % len(B.PEOPLE)]), "avatar": str(avatars[n % len(avatars)]),
                     "seed": rng.randint(0, 10 ** 6)})
    return jobs


def build(job: dict) -> str:
    return B.build(job)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=500)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--from", dest="start", type=int, default=0, help="собрать только ролики с номером > N (доп. партия)")
    ap.add_argument("--out", default=None, help="папка в output/")
    ap.add_argument("--dance", nargs=2, metavar=("TT", "YT"), type=int,
                    help="первый клип — танец: TT и YT штук → output/onestate_1310_dance_TT_N / _YT_N (номера с 1201)")
    args = ap.parse_args()
    B.banner_anim()
    if args.dance:
        tt, yt = args.dance
        jobs = plan_dance(tt + yt, 1201)
        work = ROOT / "output" / "_work" / "onestate_1310_dance"
        work.mkdir(parents=True, exist_ok=True)
        todo = []
        for part, folder in ((jobs[:tt], f"onestate_1310_dance_TT_{tt}"), (jobs[tt:], f"onestate_1310_dance_YT_{yt}")):
            out = ROOT / "output" / folder
            out.mkdir(parents=True, exist_ok=True)
            for j in part:
                j["out"] = str(out)
            (work / f"manifest_{folder}.json").write_text(json.dumps(part, indent=1, ensure_ascii=False), encoding="utf-8")
            todo += [j for j in part if not (out / f"{j['n']:03d}_{ID}.mp4").exists()]
        if args.test:
            todo = todo[:3] + todo[tt:tt + 2]
        with ProcessPoolExecutor(args.jobs) as ex:
            for k, msg in enumerate(ex.map(build, todo), 1):
                print(f"[{k}/{len(todo)}] {msg}", flush=True)
        print("готово")
        return 0
    global NEW_VIDEO_FROM
    NEW_VIDEO_FROM = args.start
    jobs = plan(args.count)
    if args.start:
        jobs = [j for j in jobs if j["n"] > args.start]
    assert all(j["moments"][0][0].startswith(tuple(OPENERS)) and 3.5 <= j["moments"][0][1] <= 4.0 for j in jobs)
    if args.test:
        jobs = [j for j in jobs if j["n"] in (1, 7, 13, 4, 10, 15)]
    out = ROOT / "output" / (args.out or (f"{ID}_test" if args.test else f"{ID}_{args.count}"))
    out.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        j["out"] = str(out)
    if not args.test:
        (out / "manifest.json").write_text(json.dumps(jobs, indent=1, ensure_ascii=False), encoding="utf-8")
    done = [j for j in jobs if not (out / f"{j['n']:03d}_{ID}.mp4").exists()]
    with ProcessPoolExecutor(args.jobs) as ex:
        for k, msg in enumerate(ex.map(build, done), 1):
            print(f"[{k}/{len(done)}] {msg}", flush=True)
    print("готово →", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
