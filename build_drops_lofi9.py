#!/usr/bin/env python3
"""
Drops lofi 9 с (айди нет): концепт lofi из drops_beats (реф-ролик youtube YhzhWyz0q6k, 11,9 с), правки ТЗ:
  — звук с первого кадра, чтобы зацепить внимание (--hook ping | whoosh | stutter), без бита;
  — озвучка коммента сразу, без тишины в начале (тишина в файле голоса срезана, старт с 0 с вместо 0,5 с);
  — финал короче: ровно 9 с, геймплей и CTA укорочены, смена на CTA — на долю бита.
Всё остальное — как в build_drops_beats_reels.py (импорт). План 300 роликов: все сочетания разные.

  python build_drops_lofi9.py --only 1,2,3 --tag test --out output/drops_lofi9_test --qa
  python build_drops_lofi9.py --range 1-100 --tag tt --out output/drops_lofi9_TT_100
  python build_drops_lofi9.py --range 101-300 --tag yt --out output/drops_lofi9_YT_200
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_drops_beats_reels as B  # noqa: E402

CONCEPT = "lofi"
TOTAL = 9.0
HOOK = ROOT / "downloads" / "drops_beats2" / "hook"
VO_TIGHT = "adam_lofi_tight.wav"
VO_STUTTER = "adam_lofi_stutter.wav"


def run(*a: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)


def prepare() -> dict[str, Path]:
    """Голос без тишины в начале и варианты первого звука (без бита — юзер):
    ping — двойной «дзынь» нового коммента; whoosh — яркий свист; stutter — заикание первого слова «tr-tr-tr-try»."""
    src = B.VOICE / B.CONCEPTS[CONCEPT]["vo"]
    tight = B.VOICE / VO_TIGHT
    if not tight.exists():
        run("-i", str(src), "-af", "silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0,afade=t=in:d=0.004",
            str(tight))
    stut = B.VOICE / VO_STUTTER
    if not stut.exists():
        cut = "atrim=0.02:0.15,asetpts=PTS-STARTPTS,afade=t=in:d=0.005,afade=t=out:st=0.125:d=0.005"
        run("-i", str(tight), "-filter_complex",
            f"[0:a]asplit=4[a][b][c][d];[a]{cut}[a1];[b]{cut}[b1];[c]{cut}[c1];[a1][b1][c1][d]concat=n=4:v=0:a=1[o]",
            "-map", "[o]", str(stut))
    HOOK.mkdir(parents=True, exist_ok=True)
    sfx = B.D / "sfx"
    fmt = "aresample=44100,aformat=channel_layouts=stereo"
    ping, whoosh = HOOK / "ping.wav", HOOK / "whoosh.wav"
    if not ping.exists():
        run("-i", str(sfx / "pop" / "minimal_467466.mp3"), "-filter_complex",
            f"[0:a]{fmt},silenceremove=start_periods=1:start_threshold=-40dB:start_silence=0,atrim=end=0.35,asetpts=PTS-STARTPTS,asplit[a][b];"
            f"[b]asetrate=55566,aresample=44100,adelay=130|130[c];[a][c]amix=inputs=2:normalize=0,volume=4dB[o]",
            "-map", "[o]", str(ping))
    if not whoosh.exists():
        run("-i", str(sfx / "whoosh" / "swing_487667.mp3"), "-af",
            f"{fmt},atrim=start=0.12:end=0.82,asetpts=PTS-STARTPTS,afade=t=in:d=0.008,afade=t=out:st=0.35:d=0.35,volume=-4dB", str(whoosh))
    return {"ping": ping, "whoosh": whoosh}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="номера плана через запятую (тест)")
    ap.add_argument("--range", default="", help="a-b: номера плана (1–300); в файле — нумерация с 1 внутри партии")
    ap.add_argument("--tag", default="test")
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "drops_lofi9_test")
    ap.add_argument("--qa", action="store_true")
    ap.add_argument("--hook", default="ping", choices=["ping", "whoosh", "stutter"], help="звук с первого кадра")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    hooks = prepare()
    B.CONCEPTS[CONCEPT]["vo"] = VO_STUTTER if a.hook == "stutter" else VO_TIGHT
    B.VO_AT, B.VO_GAIN, B.REV_GAP, B.TARGET_TOTAL = 0.0, 0, -0.06, TOTAL
    # сцены короче, чтобы геймплею осталось больше 4 с: мем раньше, лицо с J-cut, загрузка с момента, когда файл тащат
    B.MEME_AFTER, B.CARD_AFTER, B.UPLOAD_LEN, B.FACE_MIN, B.JCUT_MAX, B.UP_T0 = 0.7, 1.75, 0.9, 1.2, 0.35, 0.95
    for t in B.CONCEPTS[CONCEPT]["music"]:
        B._beats(t)
    plan = B.variants(CONCEPT, 300, 29)
    for k, v in enumerate(plan):
        if a.hook in hooks:
            v["fx_hook"] = hooks[a.hook]
        v["fx_flash"] = B.SFX_REF / "flash" / "b1_v2.wav"            # единственная плотная вспышка: у остальных 0,2 с тишины и тихий щелчок
    rows = list(enumerate(plan, 1))
    if a.only:
        keep = set(map(int, a.only.split(",")))
        rows = [r for r in rows if r[0] in keep]
    elif a.range:
        lo, hi = map(int, a.range.split("-"))
        rows = [r for r in rows if lo <= r[0] <= hi]
    a.out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "output" / "_work" / f"drops_lofi9_{a.tag}"
    work.mkdir(parents=True, exist_ok=True)

    def one(row: tuple[int, tuple[int, dict]]) -> dict:
        n, (i, v) = row
        m = B.build(i, CONCEPT, v, a.out, work)
        name = f"drops_lofi9_{a.tag}_{(n if a.range else i):03d}_noid.mp4"
        (a.out / m["video"]).replace(a.out / name)
        m["video"] = name
        return m

    with ThreadPoolExecutor(a.jobs) as ex:
        man = []
        for m in ex.map(one, enumerate(rows, 1)):
            man.append(m)
            print(f"  {m['video']}  {m['total']} с", flush=True)
    shutil.rmtree(work / "_x", ignore_errors=True)
    (a.out if a.qa else work).joinpath("manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    if a.qa:
        B.qa_sheet([a.out / m["video"] for m in man], a.out / "_qa.jpg")
    print(f"готово: {len(man)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
