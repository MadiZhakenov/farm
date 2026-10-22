#!/usr/bin/env python3
"""
OneState мем-ролики (ID пока нет → noid): 8 с (= мем с котятами), 1080×1920. Фон — игровой процесс OneState во весь кадр: целые
моменты (нарезка 1309, downloads/1309/scenes/_index.json) из вертикальных версий тех же роликов
(downloads/meme_os/vert — таймлайн совпадает с горизонтальными кадр в кадр), подряд, последний обрезан до конца ролика.
Сверху — мем (зелёный экран с котятами, downloads/meme_os/meme/IMG_5430.MOV): зелёный вырезаем, водяной знак
TikTok (мелкие отдельные пятна текста) убираем, котята плавно перемещаются над текстом внутри безопасной зоны (свой путь у ролика). Посередине — текст ТЗ
дословно, TikTok-шрифт белый с обводкой, переносы по смыслу, внутри безопасной зоны 9:16. Звук — звук мема.
Тексты 1 и 2 — поровну.

  python build_os_meme_reels.py --test
  python build_os_meme_reels.py --count 200 --jobs 4
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1303_reels as B  # noqa: E402  (text_png — белый TikTok-текст с обводкой в полосе BAND)
import build_1309_reels as L  # noqa: E402  (логотип OneState, анимация промокода STATE9CNL)

FF = B.FF
W, H, FPS = 1080, 1920, 30
ID = "1324"
TOTAL = 8.0                                           # клиент: длина = мем с котятами (8 с)
D = ROOT / "downloads" / "meme_os"
SCENES = ROOT / "downloads" / "1309" / "scenes"
VERT = {"OS_VP_Paired_Animation_02_1920x1080_34s_1": "OS_VP_Paired_Animation_02_1080x1920_33s",
        "OS_VP_World_Interaction2_02_1920x1080_37s": "OS_VP_World_Interaction2_02_1080x1920_37s",
        "OS_VP_World_Interaction_02_1920x1080_31s": "OS_VP_World_Interaction_02_1080x1920_30s"}
MEME_SRC = D / "meme" / "IMG_5430.MOV"
MEME = D / "_meme_keyed.mov"
MEME_W = 520                                          # ширина котят в кадре (меньше — есть куда двигаться)
SAFE_X0, SAFE_X1, SAFE_Y0, SAFE_Y1 = 140, 940, 200, 1540   # безопасная зона 9:16 (core/safe_zones)
TEXT_GAP = 30                                         # зазор между котятами и текстом
MEME_TOP = 230                                        # верх котят (ниже вкладок TikTok)
AUDIO = D / "_meme_audio_8s.wav"
MEME_FRAMES = 240                                     # котята — 0–8.0 с (кадры 0–239), потом заставка TikTok
MEME_LEN = MEME_FRAMES / FPS
MIN_LAST = 1.5
NL = chr(10)
TEXTS = [
    NL.join(["me and my friend dropping everything", "the moment we both get online",
             "to drive around the city", "pretending we have jobs 💀"]),
    NL.join(["me and the bro the second we’re both free:", "notifications off, hop on a call,",
             "start our business on our phones", "and cruise in top cars", "instead of actually working.",
             "who cares tho 😭🚗"]),
]
B.PX_MAX, B.PX_MIN = 54, 34


# ---------------- мем: зелёный → прозрачность, без водяного знака ----------------
_MEME_SIZE: tuple[int, int] | None = None


def meme_size() -> tuple[int, int]:
    """Размер котят — из готового .mov (быстро), иначе один раз собрать."""
    global _MEME_SIZE
    if _MEME_SIZE is None:
        if MEME.exists():
            r = subprocess.run([FF.replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=width,height", "-of", "csv=p=0", str(MEME)],
                               capture_output=True, text=True).stdout.strip().split(",")
            _MEME_SIZE = int(r[0]), int(r[1])
        else:
            _MEME_SIZE = meme_keyed()
    return _MEME_SIZE


def meme_keyed() -> tuple[int, int]:
    """Один раз: кадры мема с мягкой альфой (котята), обрезка по общему контуру котят, масштаб под MEME_W → .mov.
    Альфа — по «зелёности» G − max(R, B) с плавным переходом (без ступенек), считается на ×2 апскейле;
    водяной знак TikTok убран (мелкие отдельные пятна), зелёная кайма подавлена."""
    raw = subprocess.run([FF, "-v", "error", "-i", str(MEME_SRC), "-vf", f"fps={FPS}", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    fw, fh = 464, 848
    frames = np.frombuffer(raw, np.uint8).reshape(-1, fh, fw, 3)[:MEME_FRAMES]   # дальше — заставка TikTok
    big, alphas = [], []
    for f in frames:
        up = cv2.resize(f, (fw * 2, fh * 2), interpolation=cv2.INTER_CUBIC).astype(np.float32)
        gness = up[..., 1] - np.maximum(up[..., 0], up[..., 2])
        a = np.clip((150 - gness) / 90, 0, 1)                    # фон ~ +240, котята < +40
        hard = (a > 0.5).astype(np.uint8)
        hard[:6], hard[-6:], hard[:, :6], hard[:, -6:] = 0, 0, 0, 0
        # тонкие буквы водяного знака бывают вплотную к котёнку: размыкаем «открытием», берём тела котят,
        # и возвращаем только ближний к телу край (шерсть), дальше 4 px — отрезано
        body = cv2.morphologyEx(hard, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
        n, lab, st, _ = cv2.connectedComponentsWithStats(body, 8)
        keep = np.isin(lab, [i for i in range(1, n) if st[i, 4] > 10000]).astype(np.uint8)
        keep = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
        # водяной знак «TikTok @igreenscreenthings» слева у ног котёнка (исходник x 0–150, y 395–485): белые
        # ненасыщенные буквы (шерсть котят теплее) + их кайма — вырезаем
        wy0, wy1, wx1 = 790, 970, 300
        hsv = cv2.cvtColor(up[wy0:wy1, :wx1].clip(0, 255).astype(np.uint8), cv2.COLOR_RGB2HSV)
        txt = ((hsv[..., 1] < 32) & (hsv[..., 2] > 200)).astype(np.uint8)
        txt = cv2.dilate(txt, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
        keep[wy0:wy1, :wx1][txt > 0] = 0
        a = cv2.erode(a * keep, np.ones((3, 3), np.uint8))       # срезать полупрозрачный зелёный ободок
        a = cv2.GaussianBlur(a, (0, 0), 0.9)
        hard2 = (a > 0.25).astype(np.uint8)            # остатки каймы букв — мелкие отдельные пятна
        n2, lab2, st2, _ = cv2.connectedComponentsWithStats(hard2, 8)
        big2 = np.isin(lab2, [i for i in range(1, n2) if st2[i, 4] > 8000]).astype(np.uint8)
        a = a * cv2.dilate(big2, np.ones((5, 5), np.uint8))
        rgb = up.copy()
        rgb[..., 1] = np.minimum(rgb[..., 1], np.maximum(rgb[..., 0], rgb[..., 2]) + 6)   # despill
        big.append(rgb)
        alphas.append(a)
    union = np.max(np.stack(alphas), axis=0) > 0.3
    ys, xs = np.where(union)
    x0, y0, x1, y1 = xs.min() - 6, ys.min() - 6, xs.max() + 7, ys.max() + 7
    k = MEME_W / (x1 - x0)
    cw, ch = MEME_W // 2 * 2, round((y1 - y0) * k / 2) * 2
    if MEME.exists():
        return cw, ch
    enc = subprocess.Popen([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{cw}x{ch}", "-r",
                            str(FPS), "-i", "-", "-c:v", "png", str(MEME)], stdin=subprocess.PIPE)
    for rgb, a in zip(big, alphas):
        pm = rgb * a[..., None]                                  # премультипликация — без тёмной каймы при ресайзе
        rgba = np.dstack([pm, a * 255])[y0:y1, x0:x1].astype(np.float32)
        r = cv2.resize(rgba, (cw, ch), interpolation=cv2.INTER_AREA)
        al = r[..., 3:4] / 255
        col = np.where(al > 1e-3, r[..., :3] / np.maximum(al, 1e-3), 0)
        out = np.dstack([col, r[..., 3]]).clip(0, 255).astype(np.uint8)
        enc.stdin.write(out.tobytes())
    enc.stdin.close()
    enc.wait()
    return cw, ch


def text_top(i: int) -> int:
    """Верх текста ТЗ i (по альфе готового PNG)."""
    return Image.open(D / f"_text{i + 1}.png").getchannel("A").getbbox()[1]


def path_expr(rng: random.Random, cw: int, ch: int, text_i: int) -> tuple[str, str]:
    """Плавный путь котят: две синусоиды по каждой оси (Лиссажу) со своими частотами и фазами у каждого ролика.
    Котята всегда целиком внутри безопасной зоны 9:16 (x 140–940, от y 200) и НАД текстом — под текст не заходят."""
    xmin, xmax = SAFE_X0, SAFE_X1 - cw
    ymin, ymax = SAFE_Y0, text_top(text_i) - TEXT_GAP - ch
    if ymax < ymin or xmax < xmin:
        raise SystemExit(f"котятам нет места над текстом: x {xmin}–{xmax}, y {ymin}–{ymax}")
    cx, ax = (xmin + xmax) / 2, (xmax - xmin) / 2
    cy, ay = (ymin + ymax) / 2, (ymax - ymin) / 2
    f1, f2 = rng.uniform(0.07, 0.13), rng.uniform(0.17, 0.26)
    g1, g2 = rng.uniform(0.06, 0.11), rng.uniform(0.15, 0.24)
    p = [rng.uniform(0, 6.283) for _ in range(4)]
    x = f"{cx:.1f}+{ax * 0.7:.1f}*sin(2*PI*{f1:.4f}*t+{p[0]:.3f})+{ax * 0.3:.1f}*sin(2*PI*{f2:.4f}*t+{p[1]:.3f})"
    y = f"{cy:.1f}+{ay * 0.7:.1f}*sin(2*PI*{g1:.4f}*t+{p[2]:.3f})+{ay * 0.3:.1f}*sin(2*PI*{g2:.4f}*t+{p[3]:.3f})"
    return x, y


def meme_audio() -> Path:
    """Звук котят 0–8 с (если ролик длиннее мема — снова с начала, склейка 0.15 с)."""
    if not AUDIO.exists() and TOTAL <= MEME_LEN:
        subprocess.run([FF, "-v", "error", "-y", "-i", str(MEME_SRC), "-af",
                        f"atrim=0:{TOTAL},afade=t=out:st={TOTAL - 0.3}:d=0.3,loudnorm=I=-14:TP=-1.5:LRA=11,"
                        "aresample=48000", "-ac", "2", "-c:a", "pcm_s16le", str(AUDIO)], check=True)
    if not AUDIO.exists():
        xf = 0.15
        fc = (f"[0:a]atrim=0:{MEME_LEN},asetpts=PTS-STARTPTS[a1];"
              f"[0:a]atrim=0:{TOTAL - MEME_LEN + xf + 0.1},asetpts=PTS-STARTPTS[a2];"
              f"[a1][a2]acrossfade=d={xf}[a];[a]atrim=0:{TOTAL},afade=t=out:st={TOTAL - 0.4}:d=0.4,"
              "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[o]")
        subprocess.run([FF, "-v", "error", "-y", "-i", str(MEME_SRC), "-filter_complex", fc, "-map", "[o]", "-ac", "2",
                        "-c:a", "pcm_s16le", str(AUDIO)], check=True)
    return AUDIO


# ---------------- план: целые моменты ----------------
# в вертикальных версиях финальная заставка с логотипом начинается на 0.3–0.5 с раньше, чем в горизонтальных
# (склейки совпадают кадр в кадр) — последний момент каждого ролика обрезаем до заставки
VERT_END = {"OS_VP_Paired_Animation_02_1920x1080_34s_1": 30.20, "OS_VP_World_Interaction2_02_1920x1080_37s": 34.00,
            "OS_VP_World_Interaction_02_1920x1080_31s": 27.48}


def moments() -> list[dict]:
    mom = json.loads((SCENES / "_index.json").read_text(encoding="utf-8"))
    for m in mom:
        m["dur"] = round(min(m["dur"], VERT_END[m["source"]] - m["start"]), 3)
    return mom


def plan(count: int) -> list[dict]:
    rng = random.Random(1332)
    mom = moments()
    use: dict = {}
    seen: set = set()
    jobs = []
    for n in range(count):
        text = n % len(TEXTS)
        for _ in range(500):
            order = sorted(range(len(mom)), key=lambda i: use.get(i, 0) + rng.random() * 3)
            seq, total = [], 0.0
            for i in order:
                rem = TOTAL - total
                d = mom[i]["dur"]
                if d < rem - 1e-6:
                    if rem - d < MIN_LAST:
                        continue
                    seq.append([i, d])
                    total += d
                elif rem >= MIN_LAST:
                    seq.append([i, round(rem, 3)])
                    total = TOTAL
                    break
            if abs(total - TOTAL) > 1e-3:
                continue
            key = tuple(tuple(x) for x in seq)
            if key not in seen:
                break
        seen.add(key)
        for i, _d in seq:
            use[i] = use.get(i, 0) + 1
        px, py = path_expr(rng, *meme_size(), text)
        jobs.append({"n": n + 1, "text": text, "path": [px, py],
                     "moments": [[VERT[mom[i]["source"]], mom[i]["start"], d] for i, d in seq]})
    return jobs


# ---------------- рендер ----------------
def build(job: dict) -> str:
    out = Path(job["out"])
    dest = out / f"{job['n']:03d}_{ID}.mp4"
    inputs, parts = [], []
    for k, (src, t0, d) in enumerate(job["moments"]):
        inputs += ["-ss", f"{t0:.3f}", "-t", f"{d + 0.3:.3f}", "-i", str(D / "vert" / f"{src}.mp4")]
        parts.append(f"[{k}:v]scale={W}:{H}:flags=lanczos,fps={FPS},trim=duration={d:.4f},setpts=PTS-STARTPTS,"
                     f"setsar=1[v{k}]")
    nm = len(job["moments"])
    # клиент: лого и промокод как в 1309/1312 — лого в левом нижнем углу (над интерфейсом TikTok),
    # промокод внизу по центру над ним; низ — граница безопасной зоны 9:16 (y 1540)
    work = Path(tempfile.mkdtemp(prefix="r1324_"))
    lx, ly, _lr = L.logo_png(random.Random(job["n"] * 7919 + 1324), (0, SAFE_Y1), work / "logo.png")
    bw, bh = L.banner_anim()
    bx, by = (W - bw) // 2, SAFE_Y1 - 16 - bh + round(bh * 0.06)
    im, it, ia, il, ib = nm, nm + 1, nm + 2, nm + 3, nm + 4
    inputs += ["-stream_loop", "-1", "-i", str(MEME), "-i", str(D / f"_text{job['text'] + 1}.png"),
               "-i", str(meme_audio()), "-loop", "1", "-i", str(work / "logo.png"), "-i", str(L.BANNER_ANIM)]
    bt = max(0.0, TOTAL / 2 - 4.0)
    parts += ["".join(f"[v{k}]" for k in range(nm)) + f"concat=n={nm}:v=1:a=0[g]",
              f"[g][{il}:v]overlay={lx}:{ly}:shortest=1[g1]",
              f"[{ib}:v]fps={FPS},format=yuva420p,setpts=PTS-STARTPTS+{bt:.3f}/TB[bn]",
              f"[g1][bn]overlay={bx}:{by}:eof_action=pass[g2]",
              f"[{im}:v]format=rgba,setpts=PTS-STARTPTS[mm]",
              f"[g2][mm]overlay=x='{job['path'][0]}':y='{job['path'][1]}':eval=frame:shortest=1[s1]",
              f"[s1][{it}:v]overlay=0:0,format=yuv420p[v]"]
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[v]",
                    "-map", f"{ia}:a", "-t", f"{TOTAL}", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dest)], check=True)
    return dest.name


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    cw, ch = meme_size()
    print(f"мем {cw}×{ch}", flush=True)
    B.BAND = (900, 1400)                              # текст посередине; котята ходят над ним
    for i, t in enumerate(TEXTS, 1):
        print(f"текст {i}: {B.text_png(t, D / f'_text{i}.png')} px", flush=True)
    meme_audio()
    jobs = plan(args.count)
    if args.test:
        jobs = jobs[:4]
    out = ROOT / "output" / (args.out or (f"meme_os_test" if args.test else f"meme_os_{args.count}"))
    out.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        j["out"] = str(out)
    (out / "manifest.json").write_text(json.dumps(jobs, indent=1), encoding="utf-8")
    todo = [j for j in jobs if not (out / f"{j['n']:03d}_{ID}.mp4").exists()]
    print(f"собрать {len(todo)} из {len(jobs)}", flush=True)
    with ProcessPoolExecutor(args.jobs) as ex:
        for k, name in enumerate(ex.map(build, todo), 1):
            print(f"[{k}/{len(todo)}] {name}", flush=True)
    print("готово →", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
