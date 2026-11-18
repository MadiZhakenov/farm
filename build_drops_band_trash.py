#!/usr/bin/env python3
"""
Drops band — «трэш»-версия (айди нет): тот же ролик 8 с, что build_drops_band_reels.py (3 с сцены → 5 с геймплея
Drops на чёрном, музыка — где поёт голос), но первые 3 с — сгенерированные сцены «играет, а всем плевать / подстава»
(downloads/drops_band/clips_trash + dl_trash_v2), у каждой сцены свои тексты (наши, юзер разрешил придумать):
хук поверх сцены и две подписи на геймплее. Окна сцен — где событие видно целиком (отсмотрено покадрово).

  python build_drops_band_trash.py -n 5 --out output/drops_band_trash_test
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_drops_band_reels as B  # noqa: E402

TB = ROOT / "downloads" / "drops_band"
STROKE = 0.09                              # подписи: белые с чёрной обводкой (юзер: «лучше с обводкой чёрной»)
# сцена: файл, окно начала (с), центр хука по высоте (на пустом месте: потолок/стена/пол — не на людях и не на событии),
# хук, подпись над игрой, подпись под игрой
SCENES = {
    "phones": (TB / "clips_trash" / "t1_phones.mp4", (0.0, 1.5), 0.72,
               ["nobody at the party", "was listening to my song"],
               ["so i turned it into", "a game on drops"], ["now they can’t put", "their phones down"]),
    "dorm": (TB / "clips_trash" / "t7_dorm.mp4", (0.5, 0.9), 0.195,     # до 0,46 с Veo держит позу фото, потом скачок
             ["my roommate", "has an exam tomorrow", "and i have a new song"],
             ["so i turned it into", "a game on drops"], ["now he plays it", "between chapters"]),
    "bucket": (TB / "dl_trash_v2" / "t12_bucket.mp4", (0.1, 0.3), 0.155,
               ["her dad doesn’t like", "my music"],
               ["so i turned my song into", "a game on drops"], ["now he plays it", "every night"]),
    "party": (TB / "dl_trash_v2" / "t13_party.mp4", (0.5, 0.7), 0.21,
              ["every party has", "that guy with a guitar"],
              ["so i turned my song into", "a game on drops"], ["now they’re the ones", "asking for the link"]),
    "cheat": (TB / "dl_trash_v2" / "t9_cheat.mp4", (0.15, 0.3), 0.16,
              ["i wrote this song", "for her"],
              ["so i turned it into", "a game on drops"], ["she’s not getting", "the high score"]),
    "tips": (TB / "dl_trash_v2" / "t10_tips.mp4", (0.0, 0.15), 0.155,
             ["street performing", "pays great btw"],
             ["so i turned my song into", "a game on drops"], ["try stealing", "this one"]),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=5)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "drops_band_trash_test")
    ap.add_argument("--seed", type=int, default=21)
    ap.add_argument("--scenes", default=",".join(SCENES))
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    names = a.scenes.split(",")
    clips = [SCENES[s][0] for s in names]
    rows = B.plan(a.n, clips, a.seed)                    # игры, отрезки трека с голосом, зум/цвет — как в основной партии
    rng = random.Random(a.seed)
    a.out.mkdir(parents=True, exist_ok=True)
    work = a.out / "_work"
    work.mkdir(exist_ok=True)
    man = []
    for i, r in enumerate(rows, 1):
        name = names[(i - 1) % len(names)]
        path, (lo, hi), hy, hook, top, bot = SCENES[name]
        B.HOOK, B.TOP, B.BOTTOM = hook, top, bot
        B.HOOK_Y = {path.name: hy}
        B.CAP_GAP = 40                                   # строки с выносными (p, y) чуть выше — отступ меньше
        B.STROKE = STROKE
        r.update(clip=str(Path("..") / path.relative_to(TB)), clip_t=round(rng.uniform(lo, hi), 2),
                 speed=round(rng.uniform(0.98, 1.02), 3))
        m = B.build(i, r, a.out, work)
        m["scene"] = name
        man.append(m)
        print(f"  {m['video']}  {name}", flush=True)
    work.rmdir()
    (a.out / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"готово: {a.n} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
