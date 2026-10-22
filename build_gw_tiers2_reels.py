#!/usr/bin/env python3
"""
Global Work «bad / good / amazing», вторая партия — как output/gw_tiers (build_gw_tiers_reels.py): название
категории моноширинным шрифтом сверху, на каждое слово всплывает логотип с подписью (5 категорий из ТЗ),
единый симметричный ряд, шаг подобран под то, куда она показывает; паузы между тройками вырезаны;
голос −14 LUFS; всё в безопасной зоне 9:16.

  A  — монтаж 1 (Drive 1B7EiInURz7YM1_4VW0WE9dQpZ2Jpj3Wy → downloads/gw_tiers2/srcA/IMG_5651): 13 троек
       в двух обстановках; берём первые 5 подряд (комната с зелёной стеной, полный набор категорий).
  B1 — монтаж 2 (Drive 1hS7RvmbBsJz5cE60wF2ECLCU1S9uAlcG → srcB/IMG_8093): 5 троек.
  B2 — srcB/IMG_8094: фальстарт «bad» + 5 троек.
Моменты слов — по отрезкам речи (огибающая звука, 1 отрезок = 1 слово); Whisper на этих клипах пропускает
половину повторов. Если ряд логотипов наезжает на лицо (голова высоко в кадре), видео сдвигается вниз,
сверху — размытое отражение верха кадра (как в gw_wall); глаза остаются в безопасной зоне.

  python build_gw_tiers2_reels.py [A B1 B2]
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_tiers_reels as T  # noqa: E402
from core.safe_zones import check_box, text_rect  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF, W, H, FPS = T.FF, T.W, T.H, T.FPS
D = ROOT / "downloads" / "gw_tiers2"
OUT = ROOT / "output" / "gw_tiers2"
ID = "noid"
VIDEOS = {
    "A": [("srcA/IMG_5651", i) for i in range(5)],
    "B1": [("srcB/IMG_8093", i) for i in range(5)],
    "B2": [("srcB/IMG_8094", i) for i in range(5)],
}
FLIP = {"A"}        # зеркалим видео (она показывает справа налево) — тогда логотипы идут слева направо
GAP = 30            # отступ от подписей логотипов до верха лица, px
EYES = [33, 133, 159, 145, 362, 263, 386, 374]


def triplets(clip: Path) -> list[list[float]]:
    """Тройки bad/good/amazing по отрезкам речи. Лишние отрезки в начале (фальстарт) отбрасываем: считаем
    тройки с конца. Проверка: внутри тройки паузы короче, чем до соседних троек."""
    bs = T.bursts(T.envelope(clip))
    bs = bs[len(bs) % 3:]
    out = []
    for i in range(0, len(bs), 3):
        (b0, e0), (b1, e1), (b2, _e2) = bs[i:i + 3]
        inner = max(b1 - e0, b2 - e1)
        before = b0 - bs[i - 1][1] if i else 9
        if inner >= before:
            print(f"  {clip.stem}: тройка {i // 3 + 1} — пауза внутри {inner:.2f} ≥ до неё {before:.2f}, проверь")
        out.append([b0, b1, b2])
    return out


def face_band(video: Path) -> dict:
    """Верх лица (самая высокая точка сетки) и низ глаз по всему ролику, px из 1920 (10 к/с)."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    w, h = 540, 960
    opt = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "face_landmarker.task")),
                                       running_mode=vision.RunningMode.VIDEO, num_faces=1)
    fl = vision.FaceLandmarker.create_from_options(opt)
    p = subprocess.Popen([FF, "-v", "error", "-i", str(video), "-vf", f"scale={w}:{h},fps=10", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    top, eyes, k = [], [], 0
    while True:
        buf = p.stdout.read(w * h * 3)
        if len(buf) < w * h * 3:
            break
        r = fl.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                                         data=np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()), k * 100)
        if r.face_landmarks:
            L = r.face_landmarks[0]
            top.append(min(pt.y for pt in L) * H)
            eyes.append(max(L[i].y for i in EYES) * H)
        k += 1
    fl.close()
    return {"top_min": int(min(top)), "eyes_max": int(max(eyes))}


def build(name: str, plan: list[tuple[str, int]]) -> None:
    work = Path(tempfile.mkdtemp(prefix="gwtiers2_"))
    clips = {c: D / f"{c}.MOV" for c, _ in plan}
    trip = {c: triplets(p) for c, p in clips.items()}
    segs, t_out = [], 0.0                          # (клип, начало, конец, [моменты слов в выходном ролике])
    for k, (clip, i) in enumerate(plan):
        tr = trip[clip]
        b, g, am = tr[i]
        start = max(0.0, b - T.PRE)
        nxt = tr[i + 1][0] - T.PRE if i + 1 < len(tr) and k + 1 < len(plan) and plan[k + 1] == (clip, i + 1) else 1e9
        end = min(nxt, am + T.POST, T.duration(clips[clip]))
        segs.append((clip, start, end, [t_out + (x - start) for x in (b, g, am)]))
        t_out += end - start
    assets = [T.row_assets(k) for k in range(len(T.ROWS))]
    row_bottom = max(a["icon_top"] + T.ICON_SIDE + 10 + max(lab.height for _ic, lab, _cx in a["items"]) for a in assets)

    def make_base(shift: int) -> Path:
        inputs, parts = [], []
        for n, (clip, s, e, _p) in enumerate(segs):
            inputs += ["-i", str(clips[clip])]
            parts.append(f"[{n}:v]{T.TM},trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS,"
                         f"{'hflip,' if name in FLIP else ''}setsar=1[v{n}];"
                         f"[{n}:a:0]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{n}]")
        cat = "".join(f"[v{n}][a{n}]" for n in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=1[c][a]"
        sh = (f";[c]split[m][t];[t]crop=iw:{shift}:0:0,vflip,gblur=sigma=30,eq=brightness=-0.06[tb];"
              f"[m]crop=iw:ih-{shift}:0:0[mb];[tb][mb]vstack,scale={W}:{H},setsar=1[v]" if shift else ";[c]null[v]")
        out = work / f"base_{shift}.mov"
        subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts) + ";" + cat + sh,
                        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
                        "-c:a", "pcm_s16le", str(out)], check=True)
        return out

    base = make_base(0)
    face = face_band(base)
    _x0, _y0, _x1, y1 = text_rect(W, H)
    shift = max(0, row_bottom + GAP - face["top_min"])
    shift = min(shift + shift % 2, max(0, y1 - face["eyes_max"]) // 2 * 2)   # чётный; глаза не ниже зоны
    print(f"{name}: верх лица {face['top_min']}, низ глаз {face['eyes_max']}, низ ряда логотипов {row_bottom} → "
          f"сдвиг видео {shift}px", flush=True)
    if shift:
        base = make_base(shift)
    tips = T.fingertips(base, [x for *_r, p in segs for x in p])
    halves = [[max(T.ICON_SIDE, lab.width) / 2 + 4 for _ic, lab, _cx in a["items"]] for a in assets]
    x0, _y0, x1, _y1 = text_rect(W, H)
    # ряд симметричный (центр 540, одинаковый шаг); если она показывает «bad» справа, а «amazing» слева —
    # порядок зеркальный: bad справа, amazing слева, чтобы логотип появлялся там, куда указывает палец
    d_max = min(min(540 - x0, x1 - 540) - max(h[0], h[2]) for h in halves)
    d_min = max(max(h[0], h[1]) + max(h[1], h[2]) for h in halves) / 2 + 20
    side = [abs(x - 540) for j, x in enumerate(tips) if x is not None and j % 3 != 1]
    ideal = float(np.mean(side)) if side else T.COLS[2] - 540
    step = float(np.clip(ideal, d_min, d_max))
    bad_x = [x for j, x in enumerate(tips) if x is not None and j % 3 == 0]
    am_x = [x for j, x in enumerate(tips) if x is not None and j % 3 == 2]
    mirror = bool(bad_x and am_x and np.mean(bad_x) > np.mean(am_x))
    cols = [540 + step, 540, 540 - step] if mirror else [540 - step, 540, 540 + step]
    print(f"{name}: палец x по словам", [None if x is None else int(x) for x in tips],
          f"→ идеальный шаг {ideal:.0f}, взят {step:.0f}; {'зеркально (bad справа)' if mirror else 'bad слева'}; "
          f"колонки {[int(v) for v in cols]}", flush=True)
    for k in range(len(T.ROWS)):
        lay = T.frame_layer(assets[k], 1e9, [0, 0, 0], cols)
        bad = check_box(W, H, lay.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox())
        if bad:
            raise SystemExit(f"ряд {k + 1} вне безопасной зоны: {bad}")
    dest = OUT / f"gw_tiers2_{name}_{ID}.mp4"
    dec = subprocess.Popen([FF, "-v", "error", "-i", str(base), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r",
                            str(FPS), "-i", "-", "-i", str(base), "-filter_complex",
                            f"[0:v]format=yuv420p,{SET_SDR}[v];[1:a]{T.audio_filter(base)}[a]", "-map", "[v]", "-map",
                            "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18", *SDR_COLOR_ARGS, "-c:a", "aac",
                            "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(dest)], stdin=subprocess.PIPE)
    starts = [sum(e - s for _c, s, e, _p in segs[:k]) for k in range(len(segs))]
    f = 0
    while True:
        buf = dec.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        t = f / FPS
        k = max(i for i in range(len(segs)) if starts[i] <= t + 1e-6)
        frame = Image.frombuffer("RGB", (W, H), buf).convert("RGBA")
        frame.alpha_composite(T.frame_layer(assets[k], t, segs[k][3], cols))
        enc.stdin.write(frame.convert("RGB").tobytes())
        f += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()
    print(f"{dest.name}: {t_out:.2f} с; куски:",
          [(c.split("/")[-1], round(s, 2), round(e, 2)) for c, s, e, _p in segs], flush=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1:]
    for name, plan in VIDEOS.items():
        if not only or name in only:
            build(name, plan)
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
