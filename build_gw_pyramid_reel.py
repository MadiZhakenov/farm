#!/usr/bin/env python3
"""
Global Work, «рейтинг сайтов для поиска работы — пирамида» (реф TikTok @paige.sp4mmmm 7664783274207628557),
айди пока нет. Исходник: downloads/gw_pyramid/src/IMG_2907.MOV — парень держит доску с 6 стикерами
(пирамида 1-2-3) и снимает их под звук «On the bottom of the pyramid». Как в рефе: под каждым снятым
стикером появляется логотип сайта с подписью (белый TikTok-шрифт с чёрной обводкой).

Порядок (снизу вверх, как снимает): низ-право LinkedIn · низ-центр Indeed · низ-лево Glassdoor ·
середина-право Handshake · середина-лево Google Jobs · верх Global Work.
Логотипы — как в рефе: ровные статичные плитки поверх кадра на средних позициях стикеров, появляются,
когда стикер снят (время снятия — трекингом по стикерам). Звук — из рефа (downloads/gw_pyramid/ref/pyramid_sound.m4a),
громкость −14 LUFS; видео по длине звука. HDR iPhone → SDR через libplacebo.

  python build_gw_pyramid_reel.py                 # видео без звука + output/gw_pyramid/tuner.html
  python build_gw_pyramid_reel.py --offset -0.35  # итог со сдвигом звука из tuner.html
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402
from core import renderer as R  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
D = ROOT / "downloads" / "gw_pyramid"
SRC, SOUND, LOGOS = D / "src" / "IMG_2907.MOV", D / "ref" / "pyramid_sound.m4a", D / "logos"
SIM = D / "src" / "sim.npy"
W, H, FPS = 1080, 1920, 30
TM = ("libplacebo=w={w}:h={h}:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:"
      "tonemapping=auto:format=yuv420p,fps=30")

# слоты стикеров на кадре 0 в координатах 540×960: верх, середина л/п, низ л/ц/п
SLOTS = [(176, 564, 286, 642), (100, 662, 222, 764), (247, 662, 366, 766),
         (36, 771, 160, 898), (174, 770, 298, 902), (312, 772, 439, 904)]
# слот → (логотип, подпись)
BRANDS = {5: ("linkedin", "LinkedIn"), 4: ("indeed", "Indeed"), 3: ("glassdoor", "Glassdoor"),
          2: ("handshake", "Handshake"), 1: ("google", "Google jobs"), 0: ("globalwork", "Globalwork")}
LEAD = 0.6   # логотип «включается» за 0.6 с до полного снятия стикера (дальше его открывает сам стикер)
# срез исходника, с: рот начинает двигаться на 0.57 с, заканчивает на 28.33 с (MediaPipe jawOpen);
# после среза губы совпадают со звуком без сдвига (пользователь подобрал +0.45 на несрезанном)
CUT = (0.45, 28.50)


# ---------------- трекинг доски ----------------
def _masks(bgr: np.ndarray, top: int) -> tuple[np.ndarray, np.ndarray]:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    yel = cv2.inRange(hsv, (18, 60, 140), (40, 255, 255))
    cyan = cv2.inRange(hsv, (80, 25, 110), (105, 255, 255))
    yel[:top] = 0
    cyan[:top] = 0
    return yel, cyan


def track() -> tuple[np.ndarray, list[float]]:
    """Подобие кадр0→кадр k (540×960) по центрам видимых стикеров; без стикеров — фазовая корреляция
    маски доски. Возвращает сглаженные матрицы и время снятия каждого стикера."""
    w, h = 540, 960
    q0 = [np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]) for x0, y0, x1, y1 in SLOTS]
    c0 = np.float32([q.mean(0) for q in q0])
    p = subprocess.Popen([FF, "-v", "error", "-i", str(SRC), "-vf", TM.format(w=w, h=h), "-f", "rawvideo",
                          "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    T = np.float32([[1, 0, 0], [0, 1, 0]])
    prev, Ts, ratios = None, [], []
    while True:
        buf = p.stdout.read(w * h * 3)
        if len(buf) < w * h * 3:
            break
        yel, cyan = _masks(np.frombuffer(buf, np.uint8).reshape(h, w, 3), int(h * 0.45))
        s = float(np.sqrt(abs(np.linalg.det(T[:, :2]))))
        src, dst, rr = [], [], []
        for j, q in enumerate(q0):
            qq = q @ T[:, :2].T + T[:, 2]
            c = qq.mean(0)
            m = np.zeros((h, w), np.uint8)
            cv2.fillConvexPoly(m, ((qq - c) * 1.15 + c).astype(np.int32), 255)
            ys, xs = np.nonzero((yel > 0) & (m > 0))
            r = len(xs) / (cv2.contourArea(q) * s * s)
            rr.append(r)
            if 0.85 <= r <= 1.35:
                src.append(c0[j])
                dst.append([xs.mean(), ys.mean()])
        if len(src) >= 2:
            M, _ = cv2.estimateAffinePartial2D(np.float32(src), np.float32(dst), method=cv2.LMEDS)
            if M is not None:
                T = M.astype(np.float32)
        elif len(src) == 1:
            T = T.copy()
            T[:, 2] += np.float32(dst[0]) - (np.float32(src[0]) @ T[:, :2].T + T[:, 2])
        elif prev is not None:
            (dx, dy), resp = cv2.phaseCorrelate(prev, cv2.GaussianBlur((cyan > 0).astype(np.float32), (0, 0), 4))
            if resp > 0.05 and abs(dx) < 40 and abs(dy) < 40:
                T = T.copy()
                T[:, 2] += (dx, dy)
        prev = cv2.GaussianBlur((cyan > 0).astype(np.float32), (0, 0), 4)
        Ts.append(T.copy())
        ratios.append(rr)
    Ts = np.array(Ts)
    sm = Ts.copy()
    for a in range(2):
        for b in range(3):
            sm[:, a, b] = np.convolve(np.pad(Ts[:, a, b], 2, mode="edge"), np.ones(5) / 5, mode="valid")
    gone = []
    for j in range(len(SLOTS)):
        r = np.array([x[j] for x in ratios])
        k = next((i for i in range(len(r)) if (r[i:i + 15] < 0.15).all()), len(r))
        gone.append(k / FPS)
    return sm, gone


# ---------------- плитки логотипов ----------------
def _rounded(img: Image.Image, r: float = 0.2) -> Image.Image:
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=int(img.width * r), fill=255)
    out = img.convert("RGBA")
    out.putalpha(Image.fromarray(np.minimum(np.asarray(out.getchannel("A")), np.asarray(m))))
    return out


def tile(key: str, side: int) -> Image.Image:
    """Квадратная иконка приложения (как в рефе)."""
    def fit(path: str, pad: float = 0.0) -> Image.Image:
        im = Image.open(LOGOS / path).convert("RGBA")
        inner = int(side * (1 - 2 * pad))
        im.thumbnail((inner, inner), Image.Resampling.LANCZOS)
        if im.width < inner and im.height < inner:
            k = inner / max(im.size)
            im = im.resize((int(im.width * k), int(im.height * k)), Image.Resampling.LANCZOS)
        return im

    if key in ("linkedin", "indeed", "handshake", "globalwork"):
        src = {"linkedin": "png_linkedin.png", "indeed": "gs_indeed.com.png",
               "handshake": "gs_joinhandshake.com.png", "globalwork": "gs_globalwork.ai.png"}[key]
        im = Image.open(LOGOS / src).convert("RGBA").resize((side, side), Image.Resampling.LANCZOS)
        return _rounded(im)
    card = Image.new("RGBA", (side, side), (255, 255, 255, 255))
    if key == "glassdoor":
        mark = fit("png_glassdoor.png", 0.10)
        card.alpha_composite(mark, ((side - mark.width) // 2, (side - mark.height) // 2))
    else:  # google jobs: слово Google + «for Jobs», как в рефе
        mark = fit("png_google.png", 0.12)
        y = int(side * 0.36 - mark.height / 2)
        card.alpha_composite(mark, ((side - mark.width) // 2, y))
        f = ImageFont.truetype(str(ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf" /
                                   "TikTokSans12pt-Regular.ttf"), int(side * 0.13))
        ImageDraw.Draw(card).text((side / 2, y + mark.height + side * 0.12), "for Jobs", font=f,
                                  fill=(95, 99, 104, 255), anchor="mm")
    return _rounded(card)


def label(text: str, max_w: int, px: int) -> Image.Image:
    """Подпись как в рефе: белый TikTok-шрифт с чёрной обводкой."""
    while px > 14:
        font, stroke = R._load_font(px), R.stroke_width_for(px)
        w = A._line_width_mixed(text, font, px, stroke)
        if w <= max_w:
            break
        px -= 1
    img = Image.new("RGBA", (int(w) + 8 * stroke, int(px * 1.6) + 4 * stroke), (0, 0, 0, 0))
    A._draw_line_mixed(img, ImageDraw.Draw(img), 4 * stroke, 2 * stroke, text, font, px, stroke)
    return img.crop(img.getbbox())


# заголовок как в рефе: TikTok-шрифт, чёрный текст на белых плашках по строкам («лесенка» со скруглениями);
# замер рефа (1080×1920): плашка 706×161, верх на 250 px, по центру
TITLE = ["Ranking job application", "platforms"]
TITLE_PX, TITLE_TOP = 62, 250


def title_png(dest: Path) -> None:
    ss = 3
    font = R._load_font(TITLE_PX * ss)
    line_h, pad_x, r = int(1.30 * TITLE_PX * ss), int(0.52 * TITLE_PX * ss), int(0.22 * TITLE_PX * ss)
    widths = [font.getlength(t) for t in TITLE]
    cw = int(max(widths) + 2 * pad_x + 4 * r)
    ch = line_h * len(TITLE) + 4 * r
    mask = np.zeros((ch, cw), np.uint8)
    for k, w in enumerate(widths):
        x0 = int((cw - w) / 2 - pad_x)
        mask[2 * r + k * line_h:2 * r + (k + 1) * line_h, x0:x0 + int(w + 2 * pad_x)] = 255
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kern)   # плавные внутренние стыки строк
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kern)    # скруглённые внешние углы
    plate = Image.new("RGBA", (cw, ch), (255, 255, 255, 0))
    plate.putalpha(Image.fromarray(mask))
    d = ImageDraw.Draw(plate)
    for k, t in enumerate(TITLE):
        d.text((cw / 2, 2 * r + (k + 0.5) * line_h), t, font=font, fill=(0, 0, 0, 255), anchor="mm")
    plate = plate.resize((cw // ss, ch // ss), Image.Resampling.LANCZOS)
    plate = plate.crop(plate.getbbox())
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(plate, ((W - plate.width) // 2, TITLE_TOP))
    canvas.save(dest)


def static_png(j: int, center: tuple[float, float], side: int, lab_w: int, dest: Path) -> None:
    """Как в рефе: ровная плитка (без наклона/перспективы) + подпись под ней, на весь кадр."""
    key, text = BRANDS[j]
    lab = label(text, lab_w, max(16, int(side * 0.24)))
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cx, cy = center
    top = int(cy - (side + lab.height * 0.55) / 2)
    canvas.alpha_composite(tile(key, side), (int(cx - side / 2), top))
    canvas.alpha_composite(lab, (int(cx - lab.width / 2), int(top + side - lab.height * 0.45)))
    canvas.save(dest)


# ---------------- звук ----------------
def audio_filter() -> str:
    loud = "loudnorm=I=-14:TP=-1.5:LRA=11"
    log = subprocess.run([FF, "-hide_banner", "-i", str(SOUND), "-af", f"{loud}:print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log).group(0))
    return (f"{loud}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
            f"measured_thresh={m['input_thresh']}:offset={m['target_offset']},aresample=48000")


def mux(video: Path, out: Path, offset: float) -> None:
    """Звук рефа поверх видео; offset > 0 — звук позже, < 0 — раньше (подбирается в tuner.html)."""
    shift = f"adelay={int(offset * 1000)}:all=1" if offset > 0 else f"atrim=start={-offset},asetpts=PTS-STARTPTS"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(video), "-i", str(SOUND), "-filter_complex",
                    f"[1:a]{shift},{audio_filter()}[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)], check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "gw_pyramid" / "gw_pyramid_v5.mp4")
    ap.add_argument("--offset", type=float, help="сдвиг звука, с (из tuner.html); без него — только видео + страница")
    ap.add_argument("--retrack", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    out_dir = args.out.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    video = out_dir / "gw_pyramid_video.mp4"   # без звука, для подбора сдвига

    meta = SIM.with_suffix(".json")
    if args.retrack or not SIM.exists() or not meta.exists():
        sm, gone = track()
        np.save(SIM, sm)
        meta.write_text(json.dumps({"gone": gone}), encoding="utf-8")
    sm, gone = np.load(SIM), json.loads(meta.read_text(encoding="utf-8"))["gone"]
    print("стикеры сняты, с:", {BRANDS[j][1]: round(g, 2) for j, g in enumerate(gone)})

    if args.offset is None or not video.exists():
        # статичные плитки на средних позициях стикеров за ролик; одинаковый размер, ровная пирамида
        med = np.median(sm, axis=0)
        scale = float(np.sqrt(abs(np.linalg.det(med[:, :2]))))
        sizes = [min(x1 - x0, y1 - y0) for x0, y0, x1, y1 in SLOTS[1:]]
        cen = [(np.float32([(x0 + x1) / 2, (y0 + y1) / 2]) @ med[:, :2].T + med[:, 2]) * 2 for x0, y0, x1, y1 in SLOTS]
        # плитка + подпись (≈1.17·side) не должны залезать на ряд ниже, подписи в ряду — друг на друга
        pitch_v = min(abs(cen[1][1] - cen[0][1]), abs(cen[3][1] - cen[1][1]))
        pitch_h = min(abs(cen[2][0] - cen[1][0]), abs(cen[4][0] - cen[3][0]), abs(cen[5][0] - cen[4][0]))
        side = int(min(np.median(sizes) * 2 * scale * 0.82, (pitch_v - 14) / 1.17, pitch_h - 20))
        lab_w = int(pitch_h - 12)
        print(f"плитка {side}px, шаг рядов {pitch_v:.0f}px, в ряду {pitch_h:.0f}px")
        work = out_dir / "_tiles"
        work.mkdir(exist_ok=True)
        inputs, chain = ["-i", str(SRC)], [f"[0:v]{TM.format(w=W, h=H)}[v0]"]
        for n, j in enumerate(range(len(SLOTS)), 1):
            c = cen[j]
            png = work / f"slot{j}.png"
            static_png(j, (float(c[0]), float(c[1])), side, lab_w, png)
            inputs += ["-i", str(png)]
            chain.append(f"[v{n - 1}][{n}:v]overlay=0:0:enable='gte(t,{gone[j] - 0.15:.2f})'[v{n}]")
        tpng = work / "title.png"
        title_png(tpng)
        from core.safe_zones import check_overlay
        bad = check_overlay(tpng)
        if bad:
            raise SystemExit(f"заголовок вне безопасной зоны: {bad}")
        inputs += ["-i", str(tpng)]
        n = len(SLOTS) + 1
        chain.append(f"[v{n - 1}][{n}:v]overlay=0:0[v{n}]")
        # срез сырых краёв: до первого слова он ещё смотрит вниз, после последнего — тянется выключить
        chain.append(f"[v{n}]trim=start={CUT[0]}:end={CUT[1]},setpts=PTS-STARTPTS,format=yuv420p,{SET_SDR}[v]")
        subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", "[v]", "-an",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "18", *SDR_COLOR_ARGS,
                        "-movflags", "+faststart", str(video)], check=True)
        shutil.copy2(SOUND, out_dir / SOUND.name)
        print("видео без звука →", video)
    if args.offset is not None:
        mux(video, args.out, args.offset)
        print(f"готово (сдвиг звука {args.offset:+.2f} с) →", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
