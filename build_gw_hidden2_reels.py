#!/usr/bin/env python3
"""
Global Work «THIS is hidden from you…», вторая партия — как output/gw_hidden (build_gw_hidden_reels.py): реакция
(~3 с, как в рефе) + запись экрана globalwork.ai, текст из ТЗ над лицом/на лбу, музыка рефа −14 LUFS, длина рефа.
Новые реакции длиннее (4–8 с, в каждой несколько выражений), поэтому из каждой берём самый выразительный кусок
HOOK с: окно с наибольшим отклонением мимики (MediaPipe blendshapes) от спокойного лица, лицо в кадре всё окно.
Белый текст — с мягкой тенью (core/text_shadow.py), чтобы не сливался.

  A — downloads/gw_hidden2/srcA (Drive 1LNSPJAiFyF3QRfHxunq0a0jA_DmVTTmw, 12 реакций, SDR)
  B — downloads/gw_hidden2/srcB (Drive 1QPEXHcQfzp17iQyKpHt8H-vlQt8QdfEo, 5 реакций, iPhone HLG)

  python build_gw_hidden2_reels.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_hidden_reels as G  # noqa: E402
from core.safe_zones import text_rect  # noqa: E402
from core.text_shadow import shadow_full_frame  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF, D = G.FF, ROOT / "downloads" / "gw_hidden2"
OUT = ROOT / "output" / "gw_hidden2"
SETS = {"A": D / "srcA", "B": D / "srcB"}
HOOK = 3.2
EXPR = ["browInnerUp", "browDownLeft", "browDownRight", "browOuterUpLeft", "browOuterUpRight", "eyeWideLeft",
        "eyeWideRight", "eyeSquintLeft", "eyeSquintRight", "jawOpen", "mouthSmileLeft", "mouthSmileRight",
        "mouthFrownLeft", "mouthFrownRight", "mouthPucker", "mouthFunnel", "mouthPressLeft", "mouthPressRight",
        "cheekSquintLeft", "cheekSquintRight", "noseSneerLeft", "noseSneerRight"]


def scan(clip: Path) -> list:
    """10 к/с: на каждый кадр (мимика, верх лица, брови, подбородок в px из 1920) или None, если лица нет."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    w, h = 540, 960
    opt = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "face_landmarker.task")),
                                       running_mode=vision.RunningMode.VIDEO, num_faces=1, output_face_blendshapes=True)
    fl = vision.FaceLandmarker.create_from_options(opt)
    vf = G.TM.replace("w=1080:h=1920", f"w={w}:h={h}").replace("fps=30", "fps=10")
    p = subprocess.Popen([FF, "-v", "quiet", "-i", str(clip), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         stdout=subprocess.PIPE)
    rows, k = [], 0
    while True:
        buf = p.stdout.read(w * h * 3)
        if len(buf) < w * h * 3:
            break
        r = fl.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                                         data=np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()), k * 100)
        if r.face_landmarks and r.face_blendshapes:
            L = r.face_landmarks[0]
            ys = [pt.y for pt in L]
            b = {x.category_name: x.score for x in r.face_blendshapes[0]}
            rows.append(([b.get(n, 0.0) for n in EXPR], min(ys) * G.H, min(L[i].y for i in G.BROW) * G.H,
                         max(ys) * G.H))
        else:
            rows.append(None)
        k += 1
    fl.close()
    return rows


def text_height(px: int) -> int:
    x0, _, x1, _ = text_rect(G.W, G.H)
    return G.R.line_advance_for(px) * len(G.wrap(G.TEXT, G.R._load_font(px), x1 - x0))


def best_window(rows: list) -> dict | None:
    """Самое выразительное окно HOOK с, где лицо в кадре и текст встаёт над бровями или под подбородком
    (по всему окну) — глаза и брови не закрываем. Сначала кегль как в gw_hidden, потом чуть меньше."""
    _, y0, _, y1 = text_rect(G.W, G.H)
    ok = [r[0] for r in rows if r is not None]
    base = np.median(np.array(ok), axis=0)
    n = int(HOOK * 10)
    for px in (G.PX, 58, 52):
        bh = text_height(px)
        best = None
        for i in range(0, max(1, len(rows) - n + 1)):
            win = [r for r in rows[i:i + n] if r is not None]
            if len(win) < 0.9 * n:                       # лицо пропадает — не берём
                continue
            face = {"top_min": int(min(r[1] for r in win)), "brow_min": int(min(r[2] for r in win)),
                    "chin_max": int(max(r[3] for r in win))}
            if face["brow_min"] - G.GAP - bh < y0 and face["chin_max"] + G.GAP + bh > y1:
                continue
            sc = float(np.mean([np.abs(np.array(r[0]) - base).sum() for r in win]))
            if best is None or sc > best["score"]:
                best = {"start": i / 10, "score": round(sc, 3), "face": face, "px": px}
        if best:
            return best
    return None


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="gwhidden2_"))
    ref_len = G.probe_dur(G.REF)
    cache = D / "_windows.json"
    meta = json.loads(cache.read_text()) if cache.exists() else {}
    for tag, src in SETS.items():
        for n, clip in enumerate(sorted(src.glob("IMG_*.MOV")), 1):
            key = f"{tag}/{clip.name}"
            if key not in meta:
                meta[key] = best_window(scan(clip))
                if meta[key] is None:
                    raise SystemExit(f"{key}: нет окна, где текст встаёт мимо глаз")
                cache.write_text(json.dumps(meta, indent=1))
            m = meta[key]
            G.PX = m["px"]
            screen = min(G.SCREEN_MAX, ref_len - HOOK - 0.05)
            total = HOOK + screen
            png = work / f"{tag}{n}.png"
            top = G.text_png(m["face"], png)
            shadow_full_frame(Image.open(png).convert("RGBA")).save(png)
            fc = (f"[0:v]{G.TM},trim=duration={HOOK:.3f},setpts=PTS-STARTPTS[h0];[h0][2:v]overlay=0:0[h];"
                  f"[1:v]fps=30,trim=duration={screen:.3f},setpts=PTS-STARTPTS,setsar=1[s];"
                  f"[h][s]concat=n=2:v=1:a=0,format=yuv420p,{SET_SDR}[v];[3:a]{G.audio_filter(total)}[a]")
            dest = OUT / f"{tag}_{n:02d}_{G.ID}.mp4"
            subprocess.run([FF, "-v", "error", "-y", "-ss", f"{m['start']:.2f}", "-i", str(clip), "-i", str(G.SCREEN),
                            "-i", str(png), "-i", str(G.REF), "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "18", *SDR_COLOR_ARGS, "-c:a", "aac",
                            "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(dest)], check=True)
            print(f"{dest.name}: {clip.name} с {m['start']:.1f} с (мимика {m['score']}), текст с y={top}", flush=True)
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
