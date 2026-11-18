#!/usr/bin/env python3
"""
skinive_2 (айди нет). Реф: TikTok @nicole_bonnett/7644318732617075975 (downloads/skinive2/ref/ref.mp4, 6.6 с, один план
рук с родинками, маленькая подпись «POV…» сверху весь ролик, «sonido original»). Те же кадры, что в skinive_150:
  1 часть  родинка: downloads/skinive/mole/IMG_6281_proxy.mp4 (рука, наезд 1.4–1.6 на родинки, ниже подписи), 3 с;
  2 часть  «прогоняем через приложение»: App Store → тап «Open» (IMG_0134) → фото родинки в редакторе (IMG_2697) →
           «Skinive AI verarbeitet…» → результат (шкала 100 % Gutartiger Nävus ИЛИ «Geringes Risiko»).
           Экран приложения во всю ширину, опущен на BAND px; полоса над ним — продолжение верхнего края экрана
           (fillborders smear), чтобы подпись не закрывала шапку стора/приложения.
Подпись ТЗ дословно весь ролик, сверху (правило «тайтл сверху»): белый TikTok-шрифт с обводкой, Apple-эмодзи.
В последнюю 1 с внизу, неброско: «(Ersetzt keinen Hautarzt)» — серым мелким.
Звук — музыка рефа, зациклена по сильной доле (6.25 с → 0.07 с, кроссфейд 40 мс) до длины ролика.

  python build_skinive2.py --only 1,2 --out output/_work/skinive2_test
  python build_skinive2.py -n 150 --jobs 5 --tag _tt --seed 21 --out output/skinive2_TT_150
  python build_skinive2.py -n 150 --jobs 5 --tag _yt --seed 37 --out output/skinive2_YT_150
"""

from __future__ import annotations

import argparse
import itertools
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402
import build_skinive_walls as SW  # noqa: E402  (исходники, окна родинки, тайминги приложения/стора)
from core import renderer as R  # noqa: E402
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
MUSIC = ROOT / "downloads" / "skinive2" / "ref" / "music.wav"
CAPTION = ["POV: du merkst, dass dein muttermal", "irgendwie komisch aussieht,", "lädst es bei Skinive hoch",
           "und siehst DAS 👇"]
DISCLAIMER = "(Ersetzt keinen Hautarzt)"
DISC_PX = 36
CAP_PX, CAP_TOP = 54, 214
BAND = 462                                    # насколько опущен экран приложения (под подписью)
FIT_TOP, FIT_SCALE = 470, 0.75                # fit: верх уменьшенного экрана и масштаб (1440×810)
# раскладки экранов приложения (юзер 2026-11-06): шаг → (кроп сверху в записи 1080-шир., опускание, заливка полосы)
#   band — всё опущено под подпись; фото-редактор кропается ниже (квадрат с родинкой сразу под подписью, был низко);
#   full — без опускания НИГДЕ (юзер 2026-11-06), подпись на белых плашках TikTok поверх верха экрана;
#          все шаги во весь кадр с исходного кропа.
LAYOUTS = {
    "band": dict(store=(150, BAND, "white"), photo=(600, BAND, "smear"), proc=(150, BAND, "smear"),
                 res=(150, BAND, "smear"), disc={"gauge": 1195, "erg": 1488}, plates=False),
    "full": dict(store=(150, 0, "white"), photo=(160, 0, "smear"), proc=(150, 0, "smear"),
                 res=(150, 0, "smear"), disc={"gauge": 1248, "erg": 1037}, plates=True),
}
# fit (юзер 2026-11-06: «тайтл мешает видеть, не делаем глупых ошибок»): экран приложения ЦЕЛИКОМ (кроп 1920 по
# высоте от верха без статус-бара), уменьшен до 0.75 и стоит под подписью; поля сверху/по бокам — краевой цвет экрана
# (стор — белый). Подпись нигде не перекрывает экран.
LAYOUTS["fit"] = dict(store=(150, FIT_TOP, "white"), photo=(160, FIT_TOP, "smear"), proc=(150, FIT_TOP, "smear"),
                      res=(150, FIT_TOP, "smear"), disc={"gauge": 1412, "erg": 1168}, plates=False, fit=True)
LAYOUT = "fit"
TAG = ""
T_MOLE = 3.0
# фото в редакторе — только неподвижная часть (45.52–45.75 редактор въезжает поверх светлого главного экрана → заливка
# полей давала вертикальные полосы; с 46.85 уезжает к 3D-модели — мелькал её кадр). Растягиваем до PH_LEN (кадр статичен).
PHOTO2, PH_LEN = (45.80, 46.82), 1.3
LOOP_A, LOOP_B, XF = 6.25, 0.07, 0.04         # петля музыки: конец первого прохода → сильная доля начала
GRAY = (99, 99, 102, 235)


STROKE = 0.065                                # толщина обводки от кегля


def outline_text(lines: list[str], px: int, top: int, cy: float | None = None) -> Image.Image:
    """Белый TikTok-текст с РОВНОЙ чёрной обводкой со всех сторон (без смещённой тени core.renderer — из-за неё
    контур был толще снизу справа, юзер: «обводка неправильная»), Apple-эмодзи в строке; строки по центру."""
    font = R._load_font(px)
    st = max(2, round(px * STROKE))
    asc, desc = font.getmetrics()
    adv = R.line_advance_for(px)
    e_px = A._emoji_px(px)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        runs = [(k, c) for k, c in A._tokenize_runs(ln) if c]
        lw = sum(e_px * 1.08 if k == "emoji" else font.getlength(c) for k, c in runs)
        cx, base = (W - lw) / 2, top + i * adv + asc
        for k, c in runs:
            if k == "emoji":
                e = A._apple_emoji_rgba(c, e_px)
                if e is not None:
                    img.alpha_composite(e, (int(cx), int(base - e_px * 0.84)))
                cx += e_px * 1.08
            else:
                d.text((cx, base), c, font=font, anchor="ls", fill=(255, 255, 255, 255), stroke_width=st,
                       stroke_fill=(0, 0, 0, 255))
                cx += font.getlength(c)
    return img


def caption_png(dest: Path, dark: bool = False) -> int:
    """Подпись ТЗ — белая с ровной чёрной обводкой на всех шагах (юзер 2026-11-06: «чёрной обводкой и белый текст»).
    dark оставлен для совместимости (обе версии одинаковые)."""
    px = CAP_PX
    while True:
        font, st = R._load_font(px), max(2, round(px * STROKE))
        e_px = A._emoji_px(px)
        widest = max(sum(e_px * 1.08 if k == "emoji" else font.getlength(c) for k, c in A._tokenize_runs(ln) if c)
                     for ln in CAPTION)
        if widest + 2 * st <= 790 or px <= 36:
            break
        px -= 1
    img = outline_text(CAPTION, px, CAP_TOP)
    box = img.getbbox()
    if bad := check_box(W, H, box):
        raise SystemExit(f"подпись вне безопасной зоны: {bad}")
    img.save(dest)
    return box[3]


def caption_plate_png(dest: Path) -> int:
    """Подпись на белых плашках «лесенкой» с чёрным текстом (фон текста TikTok, build_1307.plate_block)."""
    import build_1307_carousels as P
    px = CAP_PX
    while True:
        blk = P.plate_block(CAPTION, px)
        if blk.width <= 860 or px <= 36:
            break
        px -= 1
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.alpha_composite(blk, ((W - blk.width) // 2, CAP_TOP - 12))
    pad = int(0.42 * px)
    box = img.getbbox()
    if bad := check_box(W, H, (box[0] + pad, box[1] + pad // 2, box[2] - pad, box[3] - pad // 2)):
        raise SystemExit(f"подпись вне безопасной зоны: {bad}")
    img.save(dest)
    return box[3]


DISC_Y = {"gauge": 1195, "erg": 1488}          # пустые места последнего экрана: шкала — между «erforderlich» и
                                              # карточкой; «Geringes Risiko» — низ фото над карточкой


def disclaimer_png(dest: Path, end: str) -> None:
    """«(Ersetzt keinen Hautarzt)» — белым с ровной чёрной обводкой, тем же шрифтом, что подпись, мельче
    (юзер 2026-11-06), внизу безопасной зоны."""
    img = outline_text([DISCLAIMER], DISC_PX, LAYOUTS[LAYOUT]["disc"][end])
    if bad := check_box(W, H, img.getbbox()):
        raise SystemExit(f"дисклеймер вне безопасной зоны: {bad}")
    img.save(dest)


def music_loop(dest: Path, total: float) -> None:
    """Первый проход до LOOP_A, дальше снова с LOOP_B — сколько нужно; стыки — кроссфейд XF."""
    parts = [(0.0, LOOP_A)]
    have = LOOP_A
    while have < total + 0.5:
        parts.append((LOOP_B, LOOP_A))
        have += LOOP_A - LOOP_B - XF
    inputs, fc = [], []
    for i, (a, b) in enumerate(parts):
        inputs += ["-ss", f"{a:.3f}", "-t", f"{b - a + XF:.3f}", "-i", str(MUSIC)]
    cur = "[0:a]"
    for i in range(1, len(parts)):
        fc.append(f"{cur}[{i}:a]acrossfade=d={XF}:c1=tri:c2=tri[x{i}]")
        cur = f"[x{i}]"
    fc.append(f"{cur}atrim=0:{total:.3f},afade=t=out:st={total - 0.35:.3f}:d=0.35[a]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[a]",
                    "-ar", "44100", str(dest)], check=True)


def plan(n: int, seed: int = 21) -> list[dict]:
    """Уникальные сочетания (окно родинки, зеркало, финал), затем — свои сдвиги/зум/цвет у каждого ролика."""
    rng = random.Random(seed)
    combos = list(itertools.product(range(len(SW.MOLES)), (0, 1), ("gauge", "erg")))
    rows = []
    for k in range(1, n + 1):
        if k % len(combos) == 1:
            rng.shuffle(combos)
        mole, mirror, end = combos[(k - 1) % len(combos)]
        rows.append(dict(n=k, mole=mole, mirror=mirror, end=end, m_off=round(rng.uniform(0, 0.3), 2),
                         zoom=round(rng.uniform(1.4, 1.6), 3), s0=round(rng.uniform(8.0, 8.3), 2),
                         p_len=round(rng.uniform(1.0, 1.2), 2), r_len=round(rng.uniform(1.9, 2.2), 2),
                         bri=round(rng.uniform(-0.02, 0.03), 3), sat=round(rng.uniform(1.0, 1.1), 3)))
    return rows


def render(r: dict, out: Path, work: Path) -> Path:
    name = f"skinive2{TAG}_{r['n']:03d}"
    m0, mx, my = SW.MOLES[r["mole"]]
    m0 += r["m_off"]
    z = r["zoom"]
    zw, zh = round(W * z / 2) * 2, round(H * z / 2) * 2
    cx = min(max(0, round(mx * zw - SW.MOLE_AT[0] * W)), zw - W)
    cy = min(max(0, round(my * zh - 0.70 * H)), zh - H)          # родинки на 0.70 H — под подписью
    s0 = r["s0"]
    s_len = SW.STORE_END - s0
    ph0, ph1 = PHOTO2
    p0, p1 = SW.PROC
    r0, r1 = SW.GAUGE if r["end"] == "gauge" else SW.ERG
    p_speed = (p1 - p0) / r["p_len"]
    r_speed = (r1 - r0) / r["r_len"] if r["end"] == "gauge" else 1.0
    r_hold = max(0.0, r["r_len"] - (r1 - r0) / r_speed)
    nres = round(r["r_len"] * FPS)
    total = T_MOLE + s_len + PH_LEN + r["p_len"] + nres / FPS
    grade = f"eq=brightness={r['bri']}:saturation={r['sat']}"
    hb = H - BAND

    L = LAYOUTS[LAYOUT]

    def app(step: str) -> str:
        """Экран приложения во всю ширину, опущен на band px. Полоса сверху: smear — продолжение верхней строки экрана
        (кроп ниже «островка» iPhone, иначе он тянется вверх чёрной полосой), white — ровный белый (стор: в анимации
        открытия у окна приложения есть статус-бар, smear дал бы полосы)."""
        crop_y, band, fill = L[step]
        if L.get("fit"):
            fw, fh = round(W * FIT_SCALE / 2) * 2, round(H * FIT_SCALE / 2) * 2
            x0 = (W - fw) // 2
            if fill == "white":
                return (f"scale={W}:-2:flags=lanczos,crop={W}:{H}:0:{crop_y},scale={fw}:{fh}:flags=lanczos,"
                        f"pad={W}:{H}:{x0}:{band}:color=white,setsar=1")
            return (f"scale={W}:-2:flags=lanczos,crop={W}:{H}:0:{crop_y},scale={fw}:{fh}:flags=lanczos,"
                    # yuv444p: на yuv420p fillborders не заливает правое поле (оставалось чёрным, 2026-11-06)
                    f"pad={W}:{H}:{x0}:{band},format=yuv444p,fillborders=left={x0}:right={W - fw - x0}:top={band}:"
                    f"bottom={H - band - fh}:mode=smear,format=yuv420p,setsar=1")
        if band == 0:
            return f"scale={W}:-2:flags=lanczos,crop={W}:{H}:0:{crop_y},setsar=1"
        tail = f"fillborders=top={band}:mode=smear," if fill == "smear" else ""
        color = "white" if fill == "white" else "black"
        return (f"scale={W}:-2:flags=lanczos,crop={W}:{H - band}:0:{crop_y},"
                f"pad={W}:{H}:0:{band}:color={color},{tail}setsar=1")

    disc, mus = work / f"{name}_disc.png", work / f"{name}.wav"
    cap_w, cap_b = work / "cap_white.png", work / "cap_black.png"     # готовятся в main() до потоков
    disclaimer_png(disc, r["end"])
    t1 = T_MOLE                                   # конец родинки (тёмное) → стор (светлое)
    t2 = t1 + s_len                               # → фото в редакторе (тёмное)
    t3 = t2 + PH_LEN                              # → анализ и результат (светлое)
    music_loop(mus, total)
    fc = (f"[0:v]trim=start={m0:.3f}:duration={T_MOLE},setpts=PTS-STARTPTS,fps={FPS},scale={zw}:{zh}:flags=lanczos,"
          f"crop={W}:{H}:{cx}:{cy},{grade}{',hflip' if r['mirror'] else ''},setsar=1[m];"
          f"[1:v]trim=start=1:duration={s_len:.3f},setpts=PTS-STARTPTS,fps={FPS},{app('store')}[s];"
          f"[2:v]trim=start=1:duration={ph1 - ph0:.3f},setpts={PH_LEN / (ph1 - ph0):.4f}*(PTS-STARTPTS),fps={FPS},"
          f"{app('photo')},trim=duration={PH_LEN},setpts=PTS-STARTPTS[ph];"
          f"[3:v]trim=start=1:duration={p1 - p0:.3f},setpts=(PTS-STARTPTS)/{p_speed:.4f},fps={FPS},"
          f"{app('proc')}[p];"
          f"[4:v]trim=start=1:duration={r1 - r0:.3f},setpts=(PTS-STARTPTS)/{r_speed:.4f},fps={FPS},"
          f"tpad=stop_mode=clone:stop_duration={r_hold + 0.2:.3f},{app('res')},"
          f"trim=end_frame={nres},setpts=PTS-STARTPTS[r];"
          f"[m][s][ph][p][r]concat=n=5:v=1:a=0[b];"
          + (f"[b][9:v]overlay=0:0[b2];" if L["plates"] else
             f"[b][5:v]overlay=0:0:enable='lt(t,{t1:.3f})+between(t,{t2:.3f},{t3:.3f})'[b1];"
             f"[b1][8:v]overlay=0:0:enable='between(t,{t1:.3f},{t2:.3f})+gte(t,{t3:.3f})'[b2];") +
          f"[b2][6:v]overlay=0:0:enable='gte(t,{total - 1.0:.3f})',format=yuv420p[v]")
    dest = out / f"{name}_noid.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(SW.MOLE),
                    "-ss", f"{s0 - 1:.3f}", "-i", str(SW.STORE), "-ss", f"{ph0 - 1:.3f}", "-i", str(SW.APP),
                    "-ss", str(p0 - 1), "-i", str(SW.APP), "-ss", str(r0 - 1), "-i", str(SW.APP),
                    "-i", str(cap_w), "-i", str(disc), "-i", str(mus), "-i", str(cap_b), "-i", str(work / "cap_plate.png"),
                    "-filter_complex", fc, "-map", "[v]", "-map", "7:a", "-t", f"{total:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    for p in (disc, mus):
        p.unlink()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("--only", default="", help="номера через запятую")
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "_work" / "skinive2_test")
    ap.add_argument("--layout", choices=sorted(LAYOUTS), default="fit")
    ap.add_argument("--seed", type=int, default=21, help="TT — 21, YT — другой (свои сдвиги/зум/цвет)")
    ap.add_argument("--tag", default="", help="добавка к имени файла: _tt / _yt")
    a = ap.parse_args()
    global LAYOUT, TAG
    LAYOUT, TAG = a.layout, a.tag
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = plan(max(a.n, max(map(int, a.only.split(","))) if a.only else 0), seed=a.seed)
    if a.only:
        keep = set(map(int, a.only.split(",")))
        rows = [r for r in rows if r["n"] in keep]
    a.out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "output" / "_work" / "skinive2"
    work.mkdir(parents=True, exist_ok=True)
    caption_png(work / "cap_white.png")
    caption_png(work / "cap_black.png", dark=True)
    print("плашки до y", caption_plate_png(work / "cap_plate.png"))
    with ThreadPoolExecutor(a.jobs) as ex:
        for dest in ex.map(lambda r: render(r, a.out, work), rows):
            print(f"  {dest.name}", flush=True)
    print(f"готово: {len(rows)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
