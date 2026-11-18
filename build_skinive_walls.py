#!/usr/bin/env python3
"""
Skinive, текстволл (айди нет), 150 шт. = 2 текста ТЗ × 75, 9:16, ~10.9–11.6 с:
  0–2 с     лицо девушки из папки Влада (Drive 1wBdP49Z… → downloads/skinive/vlad/Face reactions/2 = девушка A,
            светлая кожа как у руки на видео родинки; окна отсмотрены покадрово: тревога, ладонь у рта, «хм…»);
  2–5 с     родинка: downloads/skinive/mole/IMG_6281.MOV (рука на ковре, 4K), лёгкий наезд на родинки;
  5–6.5 с   App Store (фидбек клиента 2026-11-06: обязателен скрин/скринкаст стора): страница Skinive в App Store →
            тап «Open» → приложение открывается (downloads/skinive/store/IMG_0134.MP4), 1.6–1.9 с в реальной скорости;
            фото родинки в редакторе кадрирования (её загрузили) 1.35 с; анализ 1.0–1.2 с; результат 1.9–2.2 с, статично;
  далее     приложение: запись экрана Skinive юзера со сканом кадра этой же руки (downloads/skinive/app/IMG_2697.MP4;
            начало записи — неверная точка на 3D-модели, не берём) — «Skinive AI verarbeitet…»
            3→99 % ускоренно, затем результат: шкала «Keine zusätzliche Prüfung erforderlich» с отсчётом 99 % Gutartiger
            Nävus ИЛИ экран «Ergebnis · Geringes Risiko». Без статус-бара (кроп).
Текст ТЗ дословно, переносы по смыслу, белый TikTok-шрифт с обводкой и Apple-эмодзи, по центру безопасной зоны,
на лице и родинке (0–5 с); приложение — чистое, со своими надписями. Звук — тишина (ТЗ не задаёт).

  python build_skinive_walls.py --only 1:1,2:1 --out output/skinive_test
  python build_skinive_walls.py --jobs 5                     # 150 → output/skinive_150/{text1,text2}
  python build_skinive_walls.py --yt --jobs 5 --out output/skinive_150_yt   # вторая партия для YouTube
"""

from __future__ import annotations

import argparse
import itertools
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_followspy_walls as FS  # noqa: E402  (wall_png: самый крупный кегль, влезающий в безопасную зону)

W, H, FPS = 1080, 1920, 30
D = ROOT / "downloads" / "skinive"
FACE_DIR = D / "vlad" / "Face reactions" / "2"
MOLE = D / "mole" / "IMG_6281_proxy.mp4"       # облегчённая копия 4K-исходника: 1728×3072, 30 к/с (зум 1.4–1.6 без апскейла)
APP = D / "app" / "IMG_2697.MP4"          # скан кадра НАШЕЙ руки (Fotogalerie), запись юзера 2026-11-05
CUDA = False
STORE = D / "store" / "IMG_0134.MP4"      # запись App Store от юзера 2026-11-06 (фидбек клиента: обязателен скрин/скринкаст стора)
OUT = ROOT / "output" / "skinive_150"

TEXTS = {
    1: ("bin 35 und hab beim duschen\nrandom dieses muttermal\nam arm entdeckt 🙂\nwar das schon immer da??\n"
        "hautarzt angerufen.\nnächster termin: MÄRZ\n3 nächte lang fotos gegoogelt\nund mich komplett verrückt gemacht 💀\n"
        "dann zeigt mir meine schwester skinive,\nda kann man die stelle\nwenigstens scannen\nund im blick behalten\n"
        "ersetzt keinen arzt, weiß ich\naber zum ersten mal seit tagen\nkonnte ich schlafen\ntermin im märz bleibt trotzdem 🫡"),
    2: ("Ich bin gerade 35 geworden\nund hab erst diese Woche erfahren,\ndass die Krankenkasse ab jetzt\n"
        "alle zwei Jahre\ndas Hautscreening bezahlt.\nIch war noch nie beim Screening.\nKein einziges Mal.\n"
        "Und dann seh ich\ndieses Muttermal am Arm\nund frag mich,\nseit wann das eigentlich da ist.\n"
        "Termin ist gemacht,\naber erst in drei Monaten.\nBis dahin hab ich es\nmit Skinive gescannt.\nUnd das kam raus 👇\n\n"
        "Wenn du über 35 bist\nund auch noch nie beim Screening warst:\nDas ist dein Zeichen."),
}
# окна лица (клип, начало, 2 с), покадрово: тревога/«было ли это всегда?»
FACES = [("IMG_5721", 0.25),   # морщит лоб → ладонь ко рту → тревожный взгляд
         ("IMG_5732", 0.00),   # ладонь у рта, испуганно → неловкая улыбка
         ("IMG_5733", 0.35),   # тревожно, рука у лица → неловкая улыбка
         ("IMG_5733", 4.80),   # тревожно → ладонь ко рту
         ("IMG_5737", 0.50),   # палец у подбородка «хм…» → брови вверх
         ("IMG_5737", 2.50)]   # крупно, брови домиком «ой…»
# окна родинки (начало 3-с окна, центр группы родинок x, y в долях кадра — найден детектором тёмных пятен на коже):
# наезд 1,4–1,6× ставит родинки под текст (y ≈ 0,76 H) — стена их не закрывает
MOLES = [(0.2, 0.30, 0.545), (2.2, 0.29, 0.545), (3.6, 0.31, 0.55), (20.4, 0.35, 0.59)]
MOLE_AT = (0.5, 0.76)
PROC, GAUGE, ERG = (53.4, 83.6), (84.0, 87.8), (88.82, 89.31)   # 1→100 %, шкала с отсчётом, «Geringes Risiko» (после въезда экрана 88.3–88.8, до свайпа 89.33)
APP_Y = 120                                    # кроп записи 1080×2340 → 1920: без статус-бара и полоски «домой»
# стор (1206×2622 → 1080×2348): страница приложения после прокрутки вверх (оседает к 8.05 с), статично до тапа «Open»
# в 9.40, анимация открытия до 9.90 (главный экран «Guten Tag»). Кроп y 150: без статус-бара с красной точкой записи
# и без нижней панели App Store.
STORE_END, STORE_Y = 9.90, 150
# юзер 2026-11-06: «всё резко, непонятно» → каждый шаг дольше и шаг «загрузила фото родинки» между стором и анализом:
# редактор кадрирования с НАШЕЙ родинкой (IMG_2697: въезд 45.55, статично до тапа «Fertig» в 46.87)
PHOTO = (45.55, 46.90)
T_FACE, T_MOLE = 2.0, 3.0


def plan(seed: int = 3, avoid: set | None = None) -> list[dict]:
    """По 75 на текст: уникальные комбинации (лицо, окно родинки, финал приложения, зеркало родинки),
    сначала наименее использованные лица и окна. avoid — комбинации прошлой партии: их берём в последнюю очередь
    (для YT-партии, чтобы она отличалась от TT-партии)."""
    avoid = avoid or set()
    rng = random.Random(seed)
    rows = []
    for t in TEXTS:
        combos = list(itertools.product(range(len(FACES)), range(len(MOLES)), ("gauge", "erg"), (0, 1)))
        rng.shuffle(combos)
        uf, um, ue = [0] * len(FACES), [0] * len(MOLES), {"gauge": 0, "erg": 0}
        for n in range(1, 76):
            c = min(combos, key=lambda x: ((t,) + x in avoid, uf[x[0]], um[x[1]], ue[x[2]]))
            combos.remove(c)
            uf[c[0]] += 1
            um[c[1]] += 1
            ue[c[2]] += 1
            rows.append(dict(t=t, n=n, face=c[0], mole=c[1], end=c[2], mirror=c[3],
                             f_off=round(rng.uniform(-0.1, 0.1), 2), m_off=round(rng.uniform(0, 0.3), 2),
                             zoom=round(rng.uniform(1.4, 1.6), 3), p_len=round(rng.uniform(1.0, 1.2), 2),
                             s0=round(rng.uniform(8.0, 8.3), 2),
                             r_len=round(rng.uniform(1.9, 2.2), 2), bri=round(rng.uniform(-0.02, 0.03), 3),
                             sat=round(rng.uniform(1.0, 1.1), 3)))
    return rows


def render(r: dict, out: Path, work: Path) -> Path:
    name = f"skinive{r.get('tag', '')}_t{r['t']}_{r['n']:03d}"
    wall = work / f"{name}.png"
    FS.wall_png(TEXTS[r["t"]], wall)
    clip, f0 = FACES[r["face"]]
    f0 = max(0.0, f0 + r["f_off"])
    m0, mx, my = MOLES[r["mole"]]
    m0 += r["m_off"]
    z = r["zoom"]
    zw, zh = round(W * z / 2) * 2, round(H * z / 2) * 2
    cx = min(max(0, round(mx * zw - MOLE_AT[0] * W)), zw - W)
    cy = min(max(0, round(my * zh - MOLE_AT[1] * H)), zh - H)
    s0 = r["s0"]
    s_len = STORE_END - s0                            # стор в реальной скорости: оседание страницы → тап «Open» → открытие
    ph0, ph1 = PHOTO
    p0, p1 = PROC
    r0, r1 = GAUGE if r["end"] == "gauge" else ERG
    p_speed = (p1 - p0) / r["p_len"]
    r_speed = (r1 - r0) / r["r_len"] if r["end"] == "gauge" else 1.0     # «Geringes Risiko» — как есть + удержание
    r_hold = max(0.0, r["r_len"] - (r1 - r0) / r_speed)
    nres = round(r["r_len"] * FPS)
    grade = f"eq=brightness={r['bri']}:saturation={r['sat']}"
    t_txt = T_FACE + T_MOLE
    fc = (f"[0:v]trim=start={f0:.3f}:duration={T_FACE},setpts=PTS-STARTPTS,fps={FPS},scale={W}:{H}:flags=lanczos:"
          f"force_original_aspect_ratio=increase,crop={W}:{H},{grade},setsar=1[f];"
          f"[1:v]trim=start={m0:.3f}:duration={T_MOLE},setpts=PTS-STARTPTS,fps={FPS},scale={zw}:{zh}:flags=lanczos:"
          f"force_original_aspect_ratio=increase,crop={W}:{H}:{cx}:{cy},{grade}"
          f"{',hflip' if r['mirror'] else ''},setsar=1[m];"
          f"[2:v]trim=start=1:duration={p1 - p0:.3f},setpts=(PTS-STARTPTS)/{p_speed:.4f},fps={FPS},"
          f"scale={W}:-2:flags=lanczos,crop={W}:{H}:0:{APP_Y},setsar=1[p];"
          f"[3:v]trim=start=1:duration={r1 - r0:.3f},setpts=(PTS-STARTPTS)/{r_speed:.4f},fps={FPS},"
          f"scale={W}:-2:flags=lanczos,crop={W}:{H}:0:{APP_Y},setsar=1,tpad=stop_mode=clone:stop_duration={r_hold + 0.2:.3f},"
          # без наезда: zoompan сдвигает кадр по целым пикселям — юзер увидел «тряску» (2026-11-06)
          f"trim=end_frame={nres},setpts=PTS-STARTPTS[r];"
          f"[6:v]trim=start=1:duration={s_len:.3f},setpts=PTS-STARTPTS,fps={FPS},"
          f"scale={W}:-2:flags=lanczos,crop={W}:{H}:0:{STORE_Y},setsar=1[s];"
          f"[7:v]trim=start=1:duration={ph1 - ph0:.3f},setpts=PTS-STARTPTS,fps={FPS},"
          f"scale={W}:-2:flags=lanczos,crop={W}:{H}:0:{APP_Y + 40},setsar=1[ph];"   # +40: край «островка» в редакторе
          f"[f][m][s][ph][p][r]concat=n=6:v=1:a=0[b];"
          f"[b][4:v]overlay=0:0:enable='lt(t,{t_txt})',format=yuv420p[v]")
    total = T_FACE + T_MOLE + s_len + (ph1 - ph0) + r["p_len"] + nres / FPS
    dest = out / f"text{r['t']}" / f"{name}_noid.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    # декод на видеокарте только для двух 4K-исходников и только с --cuda: 8 процессов × 5 CUDA-декодеров заняли всю
    # видеопамять (7.9/8 ГБ) → nvlddmkm event 13 → синий экран 0x119 VIDEO_SCHEDULER_INTERNAL_ERROR (2026-11-06)
    hw4k = ["-hwaccel", "cuda"] if CUDA else []
    hw = []
    subprocess.run(["ffmpeg", "-v", "error", "-y", *hw4k, "-i", str(FACE_DIR / f"{clip}.MOV"), *hw4k, "-i", str(MOLE),
                    *hw, "-ss", str(p0 - 1), "-i", str(APP), *hw, "-ss", str(r0 - 1), "-i", str(APP), "-i", str(wall),
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", *hw, "-ss", f"{s0 - 1:.3f}", "-i", str(STORE),
                    *hw, "-ss", f"{ph0 - 1:.3f}", "-i", str(APP),
                    "-filter_complex", fc,
                    "-map", "[v]", "-map", "5:a", "-t", f"{total:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "96k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    wall.unlink()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--only", default="", help="текст:номер через запятую, напр. 1:1,2:1")
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--cuda", action="store_true", help="декод 4K-исходников на видеокарте (тогда --jobs ≤ 3)")
    ap.add_argument("--yt", action="store_true", help="вторая партия (YT): другой сид, сначала комбинации, которых не было в TT")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    global CUDA
    CUDA = a.cuda
    if CUDA and a.jobs > 3:
        raise SystemExit("--cuda: не больше 3 процессов (видеопамять 8 ГБ; 8 процессов уронили систему 2026-11-06)")
    if a.yt:
        used = {(r["t"], r["face"], r["mole"], r["end"], r["mirror"]) for r in plan()}
        rows = plan(seed=17, avoid=used)
        for r in rows:
            r["tag"] = "_yt"
    else:
        rows = plan()
    if a.only:
        keep = {tuple(map(int, x.split(":"))) for x in a.only.split(",")}
        rows = [r for r in rows if (r["t"], r["n"]) in keep]
    work = a.out / "_work"
    work.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(a.jobs) as ex:
        for dest, r in zip(ex.map(lambda r: render(r, a.out, work), rows), rows):
            print(f"  {dest.relative_to(a.out)}  {FACES[r['face']][0]}  mole@{MOLES[r['mole']][0]}  {r['end']}", flush=True)
    work.rmdir()
    print(f"готово: {len(rows)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
