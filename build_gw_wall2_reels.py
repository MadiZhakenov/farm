#!/usr/bin/env python3
"""
Global Work «текстовая стена», вторая партия — как output/gw_wall (build_gw_wall_reels.py): текст из таблицы
(колонка FULL TEXT WALL, дословно) сверху по центру, лицо под текстом не закрыто (при нехватке места видео
сдвигается вниз, сверху размытое отражение), длина и звук — реф DazEKzRKbxV (6.3 с, −14 LUFS), кусок клипа
без включения/выключения камеры.

  A — монтаж 1 (Drive 1SLxJwRTaMs-nBKDndwK11qjz6-IuF7T5 → downloads/gw_wall2/srcA): тексты 6–10.
      IMG_2982/2983 в папке — те же файлы, что уже были в gw_wall, их не берём.
  B — монтаж 2 (Drive 1wtPGaK242oIartvFaytBbHh5kPqzH0SP → downloads/gw_wall2/srcB): тексты 11–15.
По 5 роликов, каждый текст на своём клипе: из кандидатов — 5 клипов, где над лицом больше всего места
(тёмные вечерние и селфи в зеркале — в конце очереди); длинные тексты — на клипы с большим местом.

  python build_gw_wall2_reels.py
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_wall_reels as W  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF, FP = W.FF, W.FF.replace("ffmpeg.exe", "ffprobe.exe")
D = ROOT / "downloads" / "gw_wall2"
OUT = ROOT / "output" / "gw_wall2"
ONLY: set[int] = set()
SETS = {
    "A": (D / "srcA", range(6, 11), ["IMG_5662", "IMG_5663", "IMG_5664", "IMG_5665", "IMG_5668", "IMG_5669",
                                     "IMG_5670"], ["IMG_5667", "IMG_5672"]),
    "B": (D / "srcB", range(11, 16), ["IMG_8101", "IMG_8102", "IMG_8103", "IMG_8104", "IMG_8107", "IMG_8108"],
          ["IMG_8105"]),
}
EYES = [33, 133, 159, 145, 362, 263, 386, 374]
NO_SHIFT = set(range(6, 16))   # пользователь: без сдвига и размытой полосы сверху — видео как есть, текст поверх, даже на лице


def usable_start(path: Path, need: float) -> tuple[float, float] | None:
    """Как W.usable_range, но для любого пути: начало после включения камеры, конец до выключения."""
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-vf", "scale=90:160,fps=10", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, 160, 90).astype(np.int16)
    d = np.abs(np.diff(v, axis=0)).mean((1, 2))
    calm = float(np.median(d[len(d) // 4: 3 * len(d) // 4]))
    th = max(1.2, 2.5 * calm)
    start = max(next((i for i in range(len(d) - 5) if (d[i:i + 5] < th).all()), 0), 3)
    hits = np.where(d[-30:] > th)[0]
    end = len(d) - 30 + int(hits[0]) - 1 if len(hits) else len(d) - 3
    a, b = start / 10, max(end, start + 30) / 10
    if b - a < need:
        print(f"{path.name}: рабочий кусок {b - a:.1f} с короче рефа {need:.1f} с — пропускаем")
        return None
    return a, a + need


def face_stats(path: Path, a: float, b: float) -> dict:
    """MediaPipe по окну [a, b], 10 к/с, px из 1920: верх лица, низ глаз, подбородок, яркость кадра."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    w, h = 540, 960
    opt = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "face_landmarker.task")),
                                       running_mode=vision.RunningMode.VIDEO, num_faces=1)
    fl = vision.FaceLandmarker.create_from_options(opt)
    vf = f"{W.TM.replace('w=1080:h=1920', f'w={w}:h={h}').replace('fps=30', 'fps=10')},trim=start={a}:end={b}"
    p = subprocess.Popen([FF, "-v", "quiet", "-i", str(path), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         stdout=subprocess.PIPE)
    top, eyes, chin, lum, miss, k = [], [], [], [], 0, 0
    while True:
        buf = p.stdout.read(w * h * 3)
        if len(buf) < w * h * 3:
            break
        fr = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        lum.append(float(fr.mean()))
        r = fl.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=fr.copy()), k * 100)
        if r.face_landmarks:
            L = r.face_landmarks[0]
            ys = [pt.y for pt in L]
            top.append(min(ys) * W.H)
            eyes.append(max(L[i].y for i in EYES) * W.H)
            chin.append(max(ys) * W.H)
        else:
            miss += 1
        k += 1
    fl.close()
    return {"top_min": int(min(top)), "eyes_max": int(max(eyes)), "chin_max": int(max(chin)), "miss": miss,
            "frames": k, "lum": round(float(np.mean(lum)), 1)}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    global ONLY
    ONLY = {int(a) for a in sys.argv[1:]}      # номера текстов для пересборки, по умолчанию все
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="gwwall2_"))
    rows = [r for r in csv.reader(W.SHEET.open(encoding="utf-8"))][1:]
    sheet = {int(r[0]): r[4] for r in rows if r and r[0].strip().isdigit() and r[4].strip()}
    ref_dur = float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                    str(W.REF)], capture_output=True, text=True).stdout)
    cache = D / "_faces.json"
    faces = json.loads(cache.read_text()) if cache.exists() else {}
    report = []
    for tag, (src, nums, main_clips, spare) in SETS.items():
        for c in main_clips + spare:
            if c not in faces:
                rng = usable_start(src / f"{c}.MOV", ref_dur)
                faces[c] = {"short": True} if rng is None else                     {"start": rng[0], "end": rng[1], **face_stats(src / f"{c}.MOV", *rng)}
                cache.write_text(json.dumps(faces, indent=1))
                print(c, faces[c], flush=True)
        ok = lambda c: "short" not in faces[c] and faces[c]["miss"] <= 0.1 * faces[c]["frames"]  # noqa: E731
        pick = sorted([c for c in main_clips if ok(c)], key=lambda c: -W.capacity(faces[c])[0])
        pick += sorted([c for c in spare if ok(c)], key=lambda c: -W.capacity(faces[c])[0])
        pick = pick[:len(nums)]
        if len(pick) < len(nums):
            raise SystemExit(f"{tag}: клипов с лицом в кадре меньше, чем текстов")
        texts = sorted(nums, key=lambda n: -W.wall_height(sheet[n], 42))     # длинный текст — больше места
        plan = dict(zip(texts, pick))
        for num in nums:
            if ONLY and num not in ONLY:
                continue
            clip, text = plan[num], sheet[num]
            face = faces[clip]
            room, max_shift = W.capacity(face)
            px = next((p for p in range(W.PX_MAX, W.PX_MIN - 1, -1) if W.wall_height(text, p) <= room), W.PX_MIN)
            png = work / f"t{num}.png"
            while True:                          # строка с обводкой может выйти за зону на 1–2 px — кегль на шаг меньше
                try:
                    W.render_wall(text, px, W.TEXT_TOP, png)
                    break
                except SystemExit as e:
                    if px <= W.PX_MIN:
                        raise
                    print(f"#{num}: {px}px — {e}; беру {px - 1}px")
                    px -= 1
            h = W.wall_height(text, px)
            shift = max(0, W.TEXT_TOP + h + W.GAP - face["top_min"])
            shift += shift % 2                    # чётный сдвиг: иначе yuv420 округляет и кадр выходит 1918 px
            if num in NO_SHIFT:
                shift = 0
            elif shift > max_shift:
                print(f"#{num}: не влезает мимо лица даже {W.PX_MIN}px — сдвиг {shift} > {max_shift}")
            a0, b0 = face["start"], face["end"]
            if shift:
                vf = (f"[0:v]{W.TM},trim=start={a0}:end={b0},setpts=PTS-STARTPTS,split[m][t];"
                      f"[t]crop=iw:{shift}:0:0,vflip,gblur=sigma=30,eq=brightness=-0.06[tb];"
                      f"[m]crop=iw:ih-{shift}:0:0[mb];[tb][mb]vstack[b]")
            else:
                vf = f"[0:v]{W.TM},trim=start={a0}:end={b0},setpts=PTS-STARTPTS[b]"
            dest = OUT / f"{tag}_{num:02d}_{W.ID}.mp4"
            subprocess.run([FF, "-v", "error", "-y", "-i", str(src / f"{clip}.MOV"), "-i", str(png), "-i", str(W.REF),
                            "-filter_complex",
                            f"{vf};[b]scale={W.W}:{W.H},setsar=1[bb];[bb][1:v]overlay=0:0,format=yuv420p,{SET_SDR}[v];"
                            f"[2:a:0]atrim=end={ref_dur},asetpts=PTS-STARTPTS[a]", "-map", "[v]", "-map", "[a]",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "18", *SDR_COLOR_ARGS, "-c:a", "aac",
                            "-b:a", "160k", "-movflags", "+faststart", str(dest)], check=True)
            report.append({"file": dest.name, "row": num, "clip": clip, "src": [a0, b0], "px": px, "text_h": h,
                           "shift": shift})
            print(f"{dest.name}: строка {num} → {clip} {a0:.1f}–{b0:.1f} с, {px}px, блок {h}px, сдвиг {shift}px",
                  flush=True)
    if not ONLY:
        (OUT / "manifest.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
