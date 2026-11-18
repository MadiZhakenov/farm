#!/usr/bin/env python3
"""June's Journey 4 (ID 1): юзер 16.11 «до 7 секунд надо, ускорять показ слайдов не нужно, просто лимит до 7 с».
Готовые 14-с ролики (уже проверены: 0 общих кадров между всеми парами по каждому кадру) → первые 7 с: слайды в том же
темпе (3 полных + 4-й появляется), «June’s journey btw» под игрой на последней секунде (6–7 с, появление 0.2 с),
звук ролика (его тон) — первые 7 с с затуханием 0.4 с. Кадры и порядок не меняются (обрезка + надпись в чёрной
полосе, вне картинки игры) → уникальность сохраняется; проверка каждого кадра — после.

  python trim_jj4_7s.py
"""
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_jj4 as J  # noqa: E402
from core import gpu_ffmpeg as G  # noqa: E402

T, NF = 7.0, 210
OLD = ROOT / "output" / "_work" / "jj4" / "_14s"
btw = J.WORK / "btw_7s.png"
J.text_layer([J.BTW], int(J.cap_px() * 0.82), J.BTW_Y).save(btw)


def one(src: Path, dst: Path) -> str:
    fc = (f"[0:v]trim=end_frame={NF},setpts=PTS-STARTPTS[v0];"
          f"[1:v]format=rgba,fade=t=in:st=0:d=0.2:alpha=1,setpts=PTS-STARTPTS+6/TB[b];"
          f"[v0][b]overlay=0:0:eof_action=pass:format=yuv420,format=yuv420p[v];"
          f"[0:a]atrim=0:{T},asetpts=PTS-STARTPTS,afade=t=out:st={T - 0.4}:d=0.4[a]")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-loop", "1", "-framerate", "30", "-t", "1",
                        "-i", str(btw), "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-frames:v", str(NF),
                        "-t", str(T), *G.NVENC, "-c:a", "aac", "-b:a", "192k", *G.CLEAN, str(dst)],
                       capture_output=True, text=True)
    return "" if r.returncode == 0 else f"{src.name}: {r.stderr[-300:]}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    jobs = []
    for d in ("junes_journey_4_TT_200", "junes_journey_4_YT_200"):
        src_d, tmp_d = ROOT / "output" / d, ROOT / "output" / "_work" / "jj4" / f"_7s_{d}"
        tmp_d.mkdir(parents=True, exist_ok=True)
        jobs += [(f, tmp_d / f.name) for f in sorted(src_d.glob("*.mp4"))]
    with ThreadPoolExecutor(8) as ex:
        errs = [e for e in ex.map(lambda a: one(*a), jobs) if e]
    if errs:
        print("ОШИБКИ:", errs[:5])
        return 1
    with ThreadPoolExecutor(8) as ex:
        bad = [(d.name, b) for d, b in zip([j[1] for j in jobs], ex.map(lambda j: G.bad_frames(j[1]), jobs)) if b]
    print(f"обрезано {len(jobs)}, с пустыми/зелёными/фризами: {len(bad)} {bad[:5]}")
    if bad:
        return 1
    OLD.mkdir(parents=True, exist_ok=True)
    for d in ("junes_journey_4_TT_200", "junes_journey_4_YT_200"):
        shutil.move(str(ROOT / "output" / d), str(OLD / d))                     # 14-с версии — в архив
        shutil.move(str(ROOT / "output" / "_work" / "jj4" / f"_7s_{d}"), str(ROOT / "output" / d))
    print("готово: 7-с версии в output/junes_journey_4_TT_200 и _YT_200, 14-с — в", OLD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
