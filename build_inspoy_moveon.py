#!/usr/bin/env python3
"""
Inspoy «the EXACT day I moved on from him» (айди нет), 9:16 ~11.9 с как реф (instagram DRjoGZbDW4a):
  0–3.4 с   шокированное лицо креаторши (gw_hidden2/srcA, окно отсмотрено покадрово), подпись ТЗ белым TikTok-шрифтом
            с тонкой обводкой ниже лица;
  3.4–конец «запись экрана»: страницы Outfit Report её образов (конструктор output/inspoy_outfit_report/outfit_report.html
            из чата «ИНСПОЙ АУТФИТ», рендер Playwright + Edge 375×812 @3x → кадр 9:16 от шапки до звёзд), сначала серые
            и бежевые 40–50 %, потом яркие в цветах её сезона 85–95 %; на переломе — «the day I blocked him 🫡».
Звук — реф. nvenc cq 27, без метаданных.

  python build_inspoy_moveon.py --out output/inspoy_moveon_test
  python build_inspoy_moveon.py -n 25 --start 1 --out output/inspoy_moveon_75   # 3 параллельно: 1, 26, 51
  python build_inspoy_moveon.py --girl B --seed 11 --hook-cy 0.71 -n 25 --start 1 --out output/inspoy_moveon_B_75   # девушка B (srcB, outfits_B)
  python build_inspoy_moveon.py --short 9 -n 38 --start 1 --out output/inspoy_moveon_A_75_9s           # 9-с версии (дроп на месте)
  python build_inspoy_moveon.py --short 9 --seed 27 --rot 1 --tag yt -n 25 --start 1 --out output/inspoy_moveon_A_75_9s_yt   # YT ≠ TT
  python build_inspoy_moveon.py --girl B --hook-cy 0.71 --short 9 --seed 31 --rot 12 --tag yt -n 25 --start 1 --out output/inspoy_moveon_B_75_9s_yt
"""

from __future__ import annotations

import argparse
import os
import random
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_drops_band_reels as BR  # noqa: E402  (text_png: белый текст с обводкой)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
D = ROOT / "downloads" / "inspoy_moveon"
CON = ROOT / "output" / "inspoy_outfit_report"
REF = D / "ref" / "ref.mp4"
FACE = ROOT / "downloads" / "gw_hidden2" / "srcA"
# окна шокированного лица (клип, начало): 5729 — «о боже» с ладонью у щеки, 5721 — широко раскрытые глаза → «вау»
FACES = [("IMG_5729", 3.65), ("IMG_5721", 3.08)]
# сетка трека рефа: дроп (вступает бас) на 7,648 с, 95,7 BPM → доля 0,627 с. Первый большой процент — ровно на дропе,
# каждый образ — на долю: 6 серых до дропа, 7 ярких после; лицо — до первой доли «экрана».
DROP, BEAT = 7.648, 60 / 95.7
HOOK = ["the way you can see the EXACT day", "I moved on from him", "based off my outfit scores on inspoy"]
SWITCH = ["the day I blocked him 🫡"]
O = D / "dl1"
# (фото, %, оценки Color/Shape/Aesthetics/Outfit, поводы (вкл.), вердикт)
DULL = [
    (O / "x07.jpg", 41, ("Bad", "Good", "Bad", "Bad"), ("Everyday",),
     "Grey sits flat against your skin and drains your natural contrast. Your palette needs clear, saturated color near the face."),
    (O / "x05.jpg", 44, ("Bad", "Good", "Bad", "Good"), ("Everyday",),
     "Beige on beige blends into your complexion. Add one bright piece from your season to bring your face back to life."),
    (O / "x01.jpg", 48, ("Bad", "Good", "Good", "Bad"), ("Everyday", "Work"),
     "Oatmeal and khaki are too warm and muted for your coloring. Swap the cardigan for a jewel tone."),
    (O / "x04.jpg", 43, ("Bad", "Bad", "Bad", "Good"), ("Everyday",),
     "The faded greys wash you out and the loose fit hides your shape. Try one structured piece."),
    (O / "x08.jpg", 46, ("Bad", "Good", "Bad", "Good"), ("Everyday",),
     "Comfortable, but the heather grey mutes your features. Your best hues are clear and cool."),
    (D / "outfits_A" / "A01_grey_hoodie.jpg", 42, ("Bad", "Bad", "Good", "Bad"), ("Everyday",),
     "An all-grey set flattens your look and pulls color from your face. Bring in one clear, bright accent."),
]
BRIGHT = [
    (O / "x06.jpg", 92, ("Perfect", "Perfect", "Perfect", "Perfect"), ("Date Night", "Party", "Dinner"),
     "Emerald is one of your power colors. The satin and the bias cut flatter your figure beautifully."),
    (O / "x03.jpg", 89, ("Perfect", "Good", "Perfect", "Perfect"), ("Work", "Dinner"),
     "Cobalt makes your eyes pop and the tailored suit gives a confident, polished line."),
    (O / "x09.jpg", 91, ("Perfect", "Perfect", "Good", "Perfect"), ("Party", "Date Night"),
     "Fuchsia is right in your palette and the black leather keeps it sharp and balanced."),
    (O / "x12.jpg", 95, ("Perfect", "Perfect", "Perfect", "Perfect"), ("Date Night", "Dinner", "Party"),
     "True red is your signature color. The wrap shape defines your waist — this is you at your best."),
    (O / "x02.jpg", 87, ("Perfect", "Good", "Perfect", "Good"), ("Vacation", "Dinner"),
     "Royal purple against crisp white is clear and high-contrast, exactly what your coloring loves."),
    (O / "x10.jpg", 90, ("Perfect", "Perfect", "Good", "Perfect"), ("Party", "Work"),
     "Bright teal brightens your complexion and the high waist lengthens your legs."),
    (O / "x11.jpg", 93, ("Perfect", "Perfect", "Perfect", "Good"), ("Party", "Date Night"),
     "Hot pink is one of your best hues; the black blazer adds edge without dulling it."),
]
OB = D / "outfits_B"
# девушка B (gw_hidden2/srcB, HLG): оливковая кожа, тёмные волосы → тёплая насыщенная палитра. 5 серых + 5 ярких.
DULL_B = [
    (OB / "B01_beige_set.jpg", 42, ("Bad", "Good", "Bad", "Bad"), ("Everyday",),
     "Beige on beige melts into your skin tone and erases your contrast. Your coloring needs warm, saturated shades near the face."),
    (OB / "B02_oatmeal_cardigan.jpg", 47, ("Bad", "Good", "Good", "Bad"), ("Everyday", "Work"),
     "Oatmeal and khaki are too pale and dusty for you. Swap the cardigan for a rich, warm color."),
    (OB / "B03_taupe_tshirt_dress.jpg", 44, ("Bad", "Bad", "Bad", "Good"), ("Everyday",),
     "Taupe drains the warmth from your complexion and the shapeless cut hides your figure."),
    (OB / "B04_grey_tee_leggings.jpg", 45, ("Bad", "Good", "Bad", "Good"), ("Everyday",),
     "Cool grey sits flat against your olive undertone. Bring in one deep, warm piece."),
    (OB / "B05_grey_hoodie.jpg", 41, ("Bad", "Bad", "Bad", "Bad"), ("Everyday",),
     "An all-grey set mutes your features and pulls color from your face. Your best hues are warm and vivid."),
]
BRIGHT_B = [
    (OB / "B10_teal_one_shoulder.jpg", 93, ("Perfect", "Perfect", "Perfect", "Perfect"), ("Date Night", "Dinner", "Party"),
     "Deep teal makes your skin glow and the one-shoulder line is elegant and balanced."),
    (OB / "B11_mustard_leather_skirt.jpg", 89, ("Perfect", "Good", "Perfect", "Perfect"), ("Date Night", "Party"),
     "Mustard is right in your warm palette and the chocolate leather keeps it rich and polished."),
    (OB / "B12_burgundy_satin_shirt.jpg", 91, ("Perfect", "Perfect", "Good", "Perfect"), ("Work", "Dinner"),
     "Burgundy satin brings out the warmth in your skin; cream trousers keep it light and refined."),
    (OB / "B13_coral_wrap.jpg", 95, ("Perfect", "Perfect", "Perfect", "Perfect"), ("Date Night", "Dinner", "Vacation"),
     "Coral is your signature color. The wrap shape defines your waist — this is you at your best."),
    (OB / "B14_tangerine_mini.jpg", 90, ("Perfect", "Perfect", "Good", "Perfect"), ("Party", "Date Night"),
     "Tangerine lights up your complexion and the tailored mini shows off your shape."),
]
# окна лица B (покадрово): 8084 — с 0 с «о боже», рука у лица, крик-восторг до 4.2; 8079 — «чего?» → рот открыт до 3.5
GIRLS = {
    "A": dict(face=FACE, faces=FACES, hlg=False, ext=".MOV", dull=DULL, bright=BRIGHT, prefix="moveon"),
    # B: 4K HLG srcB → одноразовые прокси 1080×1920 30 fps, уже тонмаплены (downloads/gw_hidden2/proxyB, 2026-11-06)
    "B": dict(face=ROOT / "downloads" / "gw_hidden2" / "proxyB", faces=None, hlg=False, ext=".mp4",
              dull=DULL_B, bright=BRIGHT_B, prefix="moveonB"),
}
# у B в начале клипов и в моменты, когда она наклоняется к камере, лицо во весь кадр — хук (0,62–0,70 H) ложится на рот.
# Поэтому лицо B = джамп-кат из двух дублей СРЕДНЕГО плана с шоком (покадрово): хук на груди, лицо свободно.
TAKES_B = {"IMG_8079": (0.75, 2.60),   # «чего?!» рот открыт, глаза круглые (дальше наклоняется к камере)
           "IMG_8085": (0.95, 3.20),   # рот открыт → ладонь на рот → руки вверх
           "IMG_8077": (0.20, 1.45),   # ах! ладони на щеки
           "IMG_8084": (3.30, 4.40)}   # руки вверх, кричит от восторга
# три дубля по ~1,3 с (джамп-кат), порядок и тройки — все 24 перестановки по кругу
import itertools as _it
TRIPLES_B = list(_it.permutations(TAKES_B, 3))
random.Random(5).shuffle(TRIPLES_B)              # соседние ролики начинаются с разных дублей
HLG = "zscale=t=linear:npl=120,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,"
PRE_BEATS = 6                                  # долей «экрана» до дропа: лицо всегда до DROP − 6 долей (как у A)
CHIPS = ["Everyday", "Work", "Date Night", "Party", "Dinner", "Vacation"]
CROP_Y = 128                                   # из 2436 по высоте: без статус-бара, шапка с «Outfit Report» остаётся


def report_html(photo: Path, pct: int, ratings: tuple, chips_on: tuple, verdict: str) -> str:
    h = (CON / "outfit_report.html").read_text(encoding="utf-8")
    h = h.replace('<img src="img/outfit.jpg" alt="">', f'<img src="{photo.as_uri()}" alt="">')
    h = h.replace("<b>80</b>", f"<b>{pct}</b>")
    names = ["Color", "Shape", "Aesthetics", "Outfit"]
    arr = "[" + ", ".join(f'["{n}", "{r}"]' for n, r in zip(names, ratings)) + "]"
    h = re.sub(r"const ratings = \[.*?\];", f"const ratings = {arr};", h, flags=re.S)
    chips = "".join(f'<span class="chip{" on" if c in chips_on else ""}">{c}</span>' for c in CHIPS[:4])
    h = re.sub(r'<div class="chips">.*?</div>', f'<div class="chips">\n        {chips}\n      </div>', h, flags=re.S)
    h = re.sub(r'<p class="summary">.*?</p>', f'<p class="summary">{verdict}</p>', h, flags=re.S)
    return h


def graded(photo: Path, rng: random.Random, dest: Path) -> Path:
    """Фото Flow тусклые и «иишные» — цвет как у дальнобойщика (DT.vivid: сочнее, контрастнее, чуть теплее/холоднее)
    + лёгкий зум и сдвиг; у каждого ролика свои значения."""
    import build_dad_trucker_carousels as DT
    DT.vivid(DT.frame(photo, rng), rng).save(dest, quality=94)
    return dest


def ascending_pcts(pages: list, rng: random.Random) -> list:
    """Проценты по возрастанию (юзер 2026-11-06: «поч не по возрастанию?»): серые — растут внутри 40–50, яркие —
    внутри 85–95, без повторов; порядок фото остаётся случайным (уникальность), меняются только числа."""
    dull = [i for i, pg in enumerate(pages) if pg[1] < 70]
    bright = [i for i, pg in enumerate(pages) if pg[1] >= 70]
    out = list(pages)
    for idx, (lo, hi) in ((dull, (40, 50)), (bright, (85, 95))):
        vals = sorted(rng.sample(range(lo, hi + 1), len(idx)))
        for i, v in zip(idx, vals):
            out[i] = (pages[i][0], v) + tuple(pages[i][2:])
    return out


def render_reports(pages: list, work: Path, rng: random.Random, jitter: bool = True) -> list[Path]:
    """Каждый отчёт → PNG 375×812 @3x (как скрин iPhone) → кадр 1080×1920 от шапки до блока оценок."""
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        pg = b.new_page(viewport={"width": 375, "height": 812}, device_scale_factor=3)
        for k, (photo, pct, ratings, chips, verdict) in enumerate(pages):
            if jitter:
                lo, hi = (40, 50) if pct < 70 else (85, 95)      # свой процент у каждого ролика, в пределах ТЗ
                pct = min(hi, max(lo, pct + rng.randint(-2, 2)))
            html = CON / f"_tmp_{os.getpid()}_{k:02d}.html"   # рядом с fonts/ и img/; pid — для параллельных запусков
            photo = graded(photo, rng, work / f"photo_{k:02d}.jpg")
            html.write_text(report_html(photo.resolve(), pct, ratings, chips, verdict), encoding="utf-8")
            pg.goto(html.as_uri())
            pg.wait_for_load_state("networkidle")
            pg.evaluate("document.fonts.ready")
            png = work / f"report_{k:02d}.png"
            box = pg.locator("#phone").bounding_box()
            pg.screenshot(path=str(png), clip={"x": box["x"], "y": 0, "width": 375, "height": 812})
            html.unlink()
            im = Image.open(png).convert("RGB")
            ch = round(im.width * H / W)
            im.crop((0, CROP_Y, im.width, CROP_Y + ch)).resize((W, H), Image.Resampling.LANCZOS).save(png)
            out.append(png)
        b.close()
    return out


def text_layer(lines: list[str], cy: float, dest: Path) -> tuple[int, int, int, int]:
    """Белый текст с тонкой обводкой (как в рефе), по центру на высоте cy; эмодзи в конце строки — Apple-эмодзи
    рядом с текстом, в том же стиле."""
    import render_igdm as RI
    BR.STROKE = 0.07
    emo = [ln.rsplit(" ", 1)[1] if any(ord(c) > 0x2FFF for c in ln) else "" for ln in lines]
    plain = [ln.rsplit(" ", 1)[0] if e else ln for ln, e in zip(lines, emo)]
    BR.text_png(plain, 58, dest, False)
    im = Image.open(dest).convert("RGBA")
    if emo[-1]:
        e = RI.emoji(emo[-1], int(im.height / len(lines) * 0.95))
        if e is not None:
            canvas = Image.new("RGBA", (im.width + e.width + 14, max(im.height, e.height)), (0, 0, 0, 0))
            canvas.alpha_composite(im, (0, 0))
            canvas.alpha_composite(e, (im.width + 14, canvas.height - e.height))
            im = canvas
    im.save(dest)
    w, h = im.size
    x, y = (W - w) // 2, int(H * cy - h / 2)
    if bad := check_box(W, H, (x + 8, y + 8, x + w - 8, y + h - 8)):
        raise SystemExit(f"текст вне безопасной зоны: {bad}")
    return x, y, w, h


def face_takes(g: dict, i: int, t_face: float, work: Path, rng: random.Random) -> Path:
    """Лицо из трёх дублей СРЕДНЕГО плана: тройка по кругу, длины пропорциональны отсмотренным окнам, начала случайны
    внутри окон — у каждого ролика свои. Средний дубль чуть крупнее (наезд 1,06–1,10). Промежуточный файл почти без потерь."""
    takes = TRIPLES_B[(i - 1) % len(TRIPLES_B)]
    wins = [TAKES_B[t] for t in takes]
    span = sum(w1 - w0 for w0, w1 in wins)
    lens = [t_face * (w1 - w0) / span for w0, w1 in wins]
    lens[-1] += 0.1                                    # запас, чтобы лицо не кончилось раньше T_FACE
    base = f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},{HLG if g['hlg'] else ''}setsar=1,format=yuv420p"
    parts, args = [], []
    for k, ((w0, w1), ln, t) in enumerate(zip(wins, lens, takes)):
        st = rng.uniform(w0, max(w0, w1 - ln))
        zoom = ""
        if k == 1:
            z = rng.uniform(1.06, 1.10)
            zoom = f",scale={round(W * z / 2) * 2}:{round(H * z / 2) * 2},crop={W}:{H},setsar=1"
        parts.append(f"[{k}:v]trim=start={st:.3f}:duration={ln:.3f},setpts=PTS-STARTPTS,{base}{zoom}[t{k}]")
        args += ["-i", str(g["face"] / f"{t}{g['ext']}")]
    fc = ";".join(parts) + ";[t0][t1][t2]concat=n=3:v=1:a=0[v]"
    dest = work / "face.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args, "-filter_complex", fc, "-map", "[v]", "-an",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "16", str(dest)], check=True)
    return dest


def build(i: int, out: Path, work: Path, rng: random.Random, girl: str = "A", hook_cy: float = 0.66,
          short: float = 0.0, tag: str = "", rot: int = 0) -> Path:
    """short > 0 (юзер 2026-11-06: «ускорить до 9 с, не теряя появление на дропе»): лицо прежней длины, серые образы
    по полдоли (вдвое быстрее), первый яркий — ровно на дропе трека (звук рефа начинается позже на столько, на сколько
    раньше наступает дроп), дальше яркие по доле до конца ролика."""
    g = GIRLS[girl]
    if g["faces"]:
        clip, f0 = g["faces"][(i - 1 + rot) % len(g["faces"])]
        f0 = round(max(0.0, f0 - rng.uniform(0, 0.2)), 2)    # своё окно реакции (клипы кончаются сразу после окна)
    dull, bright = g["dull"][:], g["bright"][:]
    rng.shuffle(dull)
    rng.shuffle(bright)
    pre = max(PRE_BEATS, len(dull))
    T_FACE = DROP - BEAT * pre                            # лицо до первой доли «экрана»
    a_off = 0.0
    if short:
        step = BEAT / 2                                    # серые — по полдоли
        t_switch = T_FACE + step * pre                     # первый яркий — на дропе
        a_off = DROP - t_switch                            # звук рефа сдвинут: дроп трека = t_switch
        total = short
        n_br = max(1, min(len(bright), int((total - t_switch) / BEAT)))
        bright = bright[:n_br]
        durs = ([step * (1 + pre - len(dull))] + [step] * (len(dull) - 1)
                + [BEAT] * (n_br - 1) + [total - t_switch - BEAT * (n_br - 1)])
    else:
        total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                      str(REF)], capture_output=True, text=True).stdout)
        t_switch = DROP                                    # первый большой процент — на дропе
        # серых меньше 6 → первая страница держится дольше (лишние доли), остальные — по доле
        durs = ([BEAT * (1 + pre - len(dull))] + [BEAT] * (len(dull) + len(bright) - 2)
                + [total - DROP - BEAT * (len(bright) - 1)])
    pages = ascending_pcts(dull + bright, rng)
    shots = render_reports(pages, work, rng, jitter=False)
    t_scr = total - T_FACE
    hx, hy, _, _ = text_layer(HOOK, hook_cy, work / "hook.png")
    sx, sy, _, _ = text_layer(SWITCH, 0.62, work / "switch.png")
    lst = work / "screens.txt"
    lst.write_text("".join(f"file '{s.resolve().as_posix()}'\nduration {d:.4f}\n" for s, d in zip(shots, durs))
                   + f"file '{shots[-1].resolve().as_posix()}'\n", encoding="utf-8")
    tone = HLG if g["hlg"] else ""                     # iPhone HLG (srcB) → SDR, иначе бледно
    if g["faces"]:
        face_in = g["face"] / f"{clip}{g['ext']}"
    else:                                              # два дубля (джамп-кат), второй — с лёгким наездом
        face_in, f0, tone = face_takes(g, i + rot, T_FACE, work, rng), 0, ""
    fc = (f"[0:v]trim=start={f0}:duration={T_FACE:.3f},setpts=PTS-STARTPTS,fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},{tone}setsar=1,format=yuv420p[f];"
          f"[1:v]fps={FPS},scale={W}:{H},setsar=1,format=yuv420p,trim=duration={t_scr:.3f},setpts=PTS-STARTPTS[s];"
          f"[f][s]concat=n=2:v=1:a=0[b];"
          f"[b][2:v]overlay={hx}:{hy}:enable='lt(t,{t_switch:.3f})'[b1];"
          f"[b1][3:v]overlay={sx}:{sy}:enable='gte(t,{t_switch:.3f})',format=yuv420p[v];"
          f"[4:a]atrim=start={a_off:.3f}:duration={total:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={total - 0.3:.3f}:d=0.3,"
          f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[a]")
    dest = out / f"{g['prefix']}{'_' + tag if tag else ''}_{i:03d}_noid.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(face_in), "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-i", str(work / "hook.png"), "-i", str(work / "switch.png"), "-i", str(REF),
                    "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("--start", type=int, default=1, help="с какого номера (для параллельных запусков)")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "inspoy_moveon_test")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--girl", choices=sorted(GIRLS), default="A")
    ap.add_argument("--hook-cy", type=float, default=0.66, help="центр хука по высоте (доля кадра)")
    ap.add_argument("--short", type=float, default=0.0, help="длина ролика (напр. 9): серые вдвое быстрее, дроп сохраняется")
    ap.add_argument("--tag", default="", help="в имени файла: moveon_<tag>_NNN (напр. yt)")
    ap.add_argument("--rot", type=int, default=0, help="сдвиг выбора лица/дублей (YT ≠ TT при том же номере)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a.out.mkdir(parents=True, exist_ok=True)
    for i in range(a.start, a.start + a.n):
        work = a.out / f"_work_{i:03d}"
        work.mkdir(exist_ok=True)
        dest = build(i, a.out, work, random.Random(a.seed * 1000 + i), a.girl, a.hook_cy, a.short,
                     a.tag, a.rot)
        print(f"  {dest.name}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
