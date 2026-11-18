#!/usr/bin/env python3
"""
1346 uniq — 20 по-настоящему новых роликов из 5 товарных видео (одна гипотеза = один ролик).
Софтовая уникализация (TikFusion: зум/шум/цвет/скорость) не дала охвата — даже у контроля (оригинал без правок),
значит TikTok узнаёт сам ролик (чужая нарезка + вшитые подписи + родной звук). Поэтому в КАЖДОМ ролике:
  * чужих подписей нет: вырезаны кадрированием по «чистой полосе» кадра или временем (не размытием);
  * родного звука нет: новая музыка (громкость −14 LUFS); монтаж заново — свой порядок, длины кадров, скорости;
  * свой хук (текст) + CTA ТЗ дословно последние 3 с; цветокор + зерно;
и своя структура-гипотеза: сплит-экран, рамка-шаблон, текстволл, реверс-сторителлинг, слоу-мо, луп, джамп-зумы,
вопрос-вовлечение, до/после, подборка 3 товаров. Текст — в безопасной рамке 9:16 (check_overlay).

  python build_1346_uniq.py            # все 20 → output/1346_uniq (только ролики), служебное → output/_work/1346_uniq
  python build_1346_uniq.py 03 07      # только эти номера
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1346_reels as B  # noqa: E402  (text_layer: TikTok-подпись / плашки, Apple-эмодзи)
import build_gw_wall_reels as WL  # noqa: E402  (текстволл)
from core.safe_zones import check_overlay  # noqa: E402

FF, FP = B.FF, B.FP
SRC = ROOT / "downloads" / "1346" / "src"
OUT = ROOT / "output" / "1346_uniq"
WORK = ROOT / "output" / "_work" / "1346_uniq"
W, H, FPS = 1080, 1920, 30
TT = B.TT / "TikTokSans36pt-SemiBold.ttf"
CTA = B.LINES[:]                                      # comment "UNLOCK" / and i'll send you / the secret link 🔗

FILES = {"blanket": "Christmas Coloring Blanket with Markers", "halloween": "Glowing Halloween Fog Cauldrons",
         "gta": "GTA Money Stack Lamp", "heels": "Light-Up Christmas Heel Boots", "water": "Water Jug Cabinet Dispenser"}
# «чистая полоса» по высоте (доли кадра): вне её — чужие подписи (blanket «Babe…/Me:», gta «DON'T show…» и
# «Link in bio», heels «The Christmas heels…»/«Comment HEELS»); halloween (подпись до 1.1 с) и water
# («Comment DIY» с 6.6 с) чистятся временем
BAND = {"blanket": (0.35, 1.0), "gta": (0.245, 0.905), "heels": (0.19, 1.0), "halloween": (0.0, 1.0),
        "water": (0.0, 1.0)}
M = ROOT / "downloads"
MUSIC = {
    "snow": M / "1303/music/gZIrKXCzue8.m4a", "katusha": M / "1311/music/callmekatushas_7667964296802487072.mp3",
    "slowed": M / "gw_gotjob/ref/music.mp3", "funny": M / "1285/music/funny_gold-tiger_-14lufs.wav",
    "fleydan": M / "1330/music/m1_fleydan_7697990020683877138.mp3",
    "nyxae": M / "1330/music/m2_nyxae_7680271803985464081.mp3", "reel": M / "1309/music/1310_ReelAudio-26071.mp3",
    "cynx": M / "1312/ref/sound_original_cynx_7407463812342745889.mp3",
    "blood": M / "1285/music/m2_blood_7542977955581004599.m4a",
    "dies": M / "1285/music/m3_dies_irae_6705060426427664385.m4a", "pyramid": M / "gw_pyramid/ref/pyramid_sound.m4a",
    "joey": M / "1308/music/joey_photo_sound.mp3", "ig": M / "1309/music/ig_audio_423866028123501.mp3",
    "sonido": M / "1285/music/m1_sonido_original_7101932530202462982.m4a",
    "inspoy": M / "inspoy_found/music/ref_sound.mp3", "bfo": M / "1303/music/bfoMNx0P0aE.m4a",
    "rcc": M / "1303/music/RccecfkDWGM.m4a",
}
GRADE = {
    "warm": "eq=contrast=1.06:saturation=1.18:gamma=0.98,colorbalance=rs=0.05:gs=0.01:bs=-0.05",
    "cool": "eq=contrast=1.08:saturation=1.08,colorbalance=rs=-0.04:bs=0.06",
    "pop": "eq=contrast=1.12:saturation=1.30:brightness=0.01",
    "moody": "eq=contrast=1.15:saturation=0.95:brightness=-0.03:gamma=0.95",
    "soft": "eq=contrast=0.96:saturation=1.10:brightness=0.03",
    "night": "eq=contrast=1.10:saturation=1.25:brightness=-0.02,colorbalance=bs=0.05:rs=0.02",
}


def S(src: str, t0: float, t1: float, sp: float = 1.0, z: float = 1.0, cx: float = 0.5, cy: float | None = None,
      mir: bool = False, rev: bool = False) -> dict:
    """Кусок: источник, время, скорость, доп. зум внутри чистой полосы, центр кадра, зеркало, реверс."""
    return dict(src=src, t0=t0, t1=t1, sp=sp, z=z, cx=cx, cy=cy, mir=mir, rev=rev)


def T(lines: list[str], t0: float, t1: float | None, cy: int, px: int = 74, mode: str = "caption") -> dict:
    """Текст: строки, с/по (None = до CTA), центр по y, кегль (подгоняется под рамку), caption | plate | wall."""
    return dict(lines=lines, t0=t0, t1=t1, cy=cy, px=px, mode=mode)


# ------------------------------- 20 гипотез -------------------------------
SPECS = [
    # --- 4 × одеяло-раскраска
    dict(n=1, name="blanket_him", hyp="Мем-формат «him: … / us 2 hours later» (две подписи-этапа, история за 8 с)",
         layout="full", music=("snow", 0), grade="warm",
         segs=[S("blanket", 0.2, 2.4, 0.9, z=1.05), S("blanket", 2.55, 3.95, z=1.15), S("blanket", 4.05, 5.3, z=1.2),
               S("blanket", 5.42, 6.85, z=1.1), S("blanket", 6.96, 8.35), S("blanket", 8.45, 9.0, 0.8)],
         texts=[T(["him: “babe, we don't", "need a coloring blanket”"], 0, 4.0, 400, 70, "plate"),
                T(["us 2 hours later 😭"], 4.0, None, 400, 72, "plate")],
         cta_cy=1330),
    dict(n=2, name="blanket_wall", hyp="Текстволл-история поверх замедленного видео (досматривают, чтобы дочитать)",
         layout="full", music=("slowed", 8), grade="soft",
         segs=[S("blanket", 5.37, 6.9, 0.75, z=1.05), S("blanket", 6.9, 8.4, 0.75), S("blanket", 2.5, 4.0, 0.8),
               S("blanket", 8.4, 9.0, 0.75), S("blanket", 4.0, 5.36, 0.8, z=1.1)],
         texts=[T(["he said “we don't need", "a coloring blanket”", "", "3 nights later", "he won't let me",
                   "color his side 😭"], 0, None, 870, 60, "wall")],
         cta_cy=1330),
    dict(n=3, name="blanket_reverse", hyp="Реверс-сторителлинг: сначала итог (пара раскрашивает), потом как дошли",
         layout="full", music=("katusha", 0), grade="pop",
         segs=[S("blanket", 8.4, 9.0, 0.6, z=1.05), S("blanket", 6.9, 8.4, z=1.1), S("blanket", 0.1, 2.4),
               S("blanket", 2.5, 4.0, z=1.15), S("blanket", 5.37, 6.9, z=1.2), S("blanket", 4.0, 5.36)],
         texts=[T(["POV: the weirdest gift", "became our new", "christmas tradition"], 0, None, 400, 70)],
         cta_cy=1330),
    dict(n=4, name="blanket_jumpzoom", hyp="Джамп-монтаж: короткие кадры 0.5–0.9 с, зеркало, чередование крупности",
         layout="full", music=("funny", 12), grade="warm",
         segs=[S("blanket", 6.0, 6.8, z=1.25, mir=True), S("blanket", 2.6, 3.4, mir=True),
               S("blanket", 4.1, 4.9, z=1.3, mir=True), S("blanket", 7.0, 7.8, mir=True),
               S("blanket", 0.4, 1.3, z=1.2, mir=True), S("blanket", 5.4, 6.0, mir=True),
               S("blanket", 7.8, 8.4, z=1.25, mir=True), S("blanket", 8.4, 9.0, mir=True),
               S("blanket", 3.4, 4.0, z=1.25, mir=True), S("blanket", 4.9, 5.36, mir=True),
               S("blanket", 1.4, 2.4, 0.8, z=1.15, mir=True)],
         texts=[T(["christmas date night idea", "you'll actually do 🎄"], 0, None, 400, 72)],
         cta_cy=1330),
    # --- 4 × лампа-пачка денег
    dict(n=5, name="gta_herofirst", hyp="Хук-кадр первым: золотая лампа в тёмной комнате в первую секунду",
         layout="full", music=("fleydan", 0), grade="moody",
         segs=[S("gta", 14.6, 16.2, z=1.05), S("gta", 1.2, 3.5, z=1.1), S("gta", 10.4, 12.8),
               S("gta", 5.0, 7.4, z=1.15), S("gta", 16.4, 18.4, z=1.2)],
         texts=[T(["every GTA fan's room", "needs this 💵"], 0, None, 400, 76)],
         cta_cy=1300),
    dict(n=6, name="gta_frame", hyp="Шаблон-рамка: видео в рамке на размытом фоне + крупный заголовок (как новостной пост)",
         layout="frame", music=("nyxae", 0), grade="pop", fy=470,
         segs=[S("gta", 13.2, 15.6), S("gta", 0.1, 1.1), S("gta", 1.2, 3.5), S("gta", 10.3, 12.4), S("gta", 16.0, 18.5)],
         texts=[T(["this lamp is", "a stack of cash 💵"], 0, None, 300, 78, "plate")],
         cta_cy=1330),
    dict(n=7, name="gta_slowmo", hyp="Слоу-мо 0.5× на включении света + «wait for it» (досмотр до вспышки)",
         layout="full", music=("reel", 2), grade="night",
         segs=[S("gta", 10.3, 11.6, z=1.1), S("gta", 11.6, 12.9, 0.5, z=1.2), S("gta", 0.1, 1.1, 0.5, z=1.15),
               S("gta", 13.1, 14.4, z=1.05), S("gta", 15.0, 17.2, 0.8, z=1.1)],
         texts=[T(["wait for it… 💡"], 0, 2.6, 420, 84), T(["the money lamp", "every gamer wants 💵"], 2.6, None, 420, 74)],
         cta_cy=1300),
    dict(n=8, name="gta_loop_rate", hyp="Бесшовный луп + вопрос «rate 1–10» (повторные просмотры и комментарии)",
         layout="full", music=("cynx", 22), grade="cool",
         segs=[S("gta", 15.6, 18.4, z=1.08), S("gta", 10.3, 12.6, z=1.15), S("gta", 5.0, 6.6, z=1.2),
               S("gta", 13.1, 15.6, z=1.08)],
         texts=[T(["rate this setup", "1–10 👇"], 0, None, 400, 80, "plate")],
         cta_cy=1300),
    # --- 4 × хэллоуин-котлы
    dict(n=9, name="halloween_nightfirst", hyp="Ночь первой: финальный неоновый кадр в начале, потом как сделано",
         layout="full", music=("blood", 0), grade="night",
         segs=[S("halloween", 14.3, 16.0), S("halloween", 11.9, 14.1, z=1.1), S("halloween", 1.2, 3.6, z=1.15),
               S("halloween", 4.0, 6.8, z=1.05)],
         texts=[T(["my halloween table", "after dark 🖤"], 0, None, 400, 78)],
         cta_cy=1330),
    dict(n=10, name="halloween_daynight", hyp="До/после: те же котлы днём, затем ночью (подписи этапов)",
         layout="full", music=("dies", 4), grade="moody",
         segs=[S("halloween", 7.0, 9.6, z=1.1), S("halloween", 2.15, 3.0, z=1.2), S("halloween", 3.9, 5.5, z=1.1),
               S("halloween", 11.85, 12.8, z=1.05), S("halloween", 12.9, 14.18), S("halloween", 14.28, 16.05)],
         texts=[T(["same cauldrons.", "day vs night 🧙‍♀️"], 0, None, 400, 72, "plate"),
                T(["day"], 0, 4.9, 1180, 62, "plate"), T(["night"], 5.0, -3, 1180, 62, "plate")],
         cta_cy=1330),
    dict(n=11, name="halloween_slow", hyp="ASMR-замедление крупных планов тумана + короткий вопрос-удивление",
         layout="full", music=("pyramid", 0), grade="soft",
         segs=[S("halloween", 4.4, 6.0, 0.75, z=1.35, cy=0.6), S("halloween", 6.0, 7.8, 0.75, z=1.3, cy=0.62),
               S("halloween", 2.0, 3.6, 0.75, z=1.25, cy=0.55), S("halloween", 12.0, 13.6, 0.8, z=1.2)],
         texts=[T(["no way", "this is just water 😳"], 0, None, 400, 82)],
         cta_cy=1330),
    dict(n=12, name="halloween_montage", hyp="Быстрый монтаж-хайп 0.6–0.9 с + зеркало + «party hack»",
         layout="full", music=("joey", 0), grade="pop",
         segs=[S("halloween", 14.3, 15.1, mir=True), S("halloween", 1.3, 2.1, z=1.2, mir=True),
               S("halloween", 4.4, 5.2, z=1.3, mir=True), S("halloween", 12.0, 12.8, mir=True),
               S("halloween", 6.4, 7.2, z=1.2, mir=True), S("halloween", 15.1, 16.0, mir=True),
               S("halloween", 9.6, 10.4, z=1.15, mir=True), S("halloween", 2.2, 3.0, z=1.25, mir=True),
               S("halloween", 7.4, 8.2, mir=True), S("halloween", 12.9, 14.1, z=1.1, mir=True)],
         texts=[T(["halloween party hack", "nobody talks about 🎃"], 0, None, 400, 74)],
         cta_cy=1330),
    # --- 4 × светящиеся сапоги
    dict(n=13, name="heels_partyfirst", hyp="Вечеринка первой (результат), потом коробка из магазина (реверс)",
         layout="full", music=("ig", 32), grade="night",
         segs=[S("heels", 7.3, 8.9, z=1.05), S("heels", 10.2, 11.3), S("heels", 0.05, 1.2), S("heels", 2.8, 3.6),
               S("heels", 3.7, 5.3, z=1.1), S("heels", 8.95, 10.15, z=1.1), S("heels", 11.4, 12.6)],
         texts=[T(["the heels everyone", "asked about", "at the christmas party 👠✨"], 0, None, 420, 68)],
         cta_cy=1330),
    dict(n=14, name="heels_slowmo", hyp="Слоу-мо 0.5× на свечении (60 fps) + POV-хук",
         layout="full", music=("sonido", 6), grade="warm",
         segs=[S("heels", 7.3, 8.6, 0.5, z=1.1), S("heels", 11.4, 12.6, 0.6, z=1.05), S("heels", 9.0, 10.1, 0.5, z=1.15),
               S("heels", 5.4, 6.4, 0.7)],
         texts=[T(["POV: your heels", "light up the room ✨"], 0, None, 420, 78)],
         cta_cy=1330),
    dict(n=15, name="heels_split", hyp="Сплит «в коробке / на вечеринке» с подписями панелей",
         layout="split", music=("inspoy", 0), grade="pop",
         top=[S("heels", 0.05, 1.2, 0.62, cy=0.5), S("heels", 1.95, 2.75, 0.62, cy=0.55),
              S("heels", 2.8, 3.62, 0.62, cy=0.55), S("heels", 3.7, 5.3, 0.62, cy=0.58)],
         bottom=[S("heels", 5.4, 6.9, 0.92, cy=0.6), S("heels", 7.3, 8.88, 0.92, cy=0.62),
                 S("heels", 8.96, 10.13, 0.92, cy=0.62), S("heels", 10.2, 11.28, 0.92, cy=0.7),
                 S("heels", 11.36, 12.55, 0.92, cy=0.65)],
         texts=[T(["christmas heels", "but make it glow 🎄"], 0, None, 330, 72, "plate"),
                T(["in the box"], 0, -3, 860, 60, "plate"), T(["at the party"], 0, -3, 1060, 60, "plate")],
         cta_cy=960),
    dict(n=16, name="heels_question", hyp="Вопрос-вовлечение «yes or no» + зеркало сцен без надписей",
         layout="full", music=("funny", 48), grade="cool",
         segs=[S("heels", 9.0, 10.15, mir=True), S("heels", 5.4, 7.2, z=1.08, mir=True), S("heels", 3.7, 5.3, z=1.1),
               S("heels", 11.4, 13.4, mir=True), S("heels", 7.3, 8.8, z=1.15, mir=True)],
         texts=[T(["would you wear these", "to the christmas party?", "yes or no 👇"], 0, None, 420, 68, "plate")],
         cta_cy=1330),
    # --- 3 × тумба-диспенсер
    dict(n=17, name="water_beforeafter", hyp="До/после: голая тумба → бутыль исчезает → стакан воды (подписи этапов)",
         layout="full", music=("bfo", 0), grade="soft",
         segs=[S("water", 0.0, 2.7, 0.8, z=1.05), S("water", 2.8, 4.6, 0.8, z=1.15), S("water", 4.7, 6.55, 0.8)],
         texts=[T(["this side table", "hides a water jug 🤯"], 0, None, 400, 78),
                T(["before"], 0.2, 3.1, 1180, 64, "plate"), T(["after"], 3.3, 5.2, 1180, 64, "plate")],
         cta_cy=1330),
    dict(n=18, name="water_frame", hyp="Шаблон-рамка с заголовком-фактом (выглядит как обзор, а не репост)",
         layout="frame", music=("rcc", 0), grade="cool", fy=450, fw=860, band=(0.06, 0.8),
         segs=[S("water", 0.0, 2.7, 0.8), S("water", 2.8, 4.6, 0.8), S("water", 4.7, 6.55, 0.8)],
         texts=[T(["this side table is", "secretly a water dispenser 💧"], 0, None, 320, 64, "plate")],
         cta_cy=1330),
    dict(n=19, name="water_loop", hyp="Луп: стакан → бутыль падает внутрь → снова стакан + «watch it disappear»",
         layout="full", music=("katusha", 1), grade="pop",
         segs=[S("water", 5.3, 6.55, z=1.1), S("water", 0.0, 2.7, 0.8, z=1.1), S("water", 2.8, 4.6, 0.85, z=1.2),
               S("water", 4.7, 5.3, 0.85, z=1.1)],
         texts=[T(["watch the bottle", "disappear 👀"], 0, None, 400, 80)],
         cta_cy=1330),
    # --- подборка
    dict(n=20, name="compilation_gifts", hyp="Подборка «3 подарка, которые реально стоят того» (новый формат, 3 товара)",
         layout="full", music=("fleydan", 5), grade="warm",
         segs=[S("blanket", 5.4, 6.9, z=1.1), S("blanket", 8.4, 9.0), S("blanket", 4.0, 5.0, z=1.15),
               S("heels", 7.3, 8.9, z=1.05), S("heels", 11.4, 12.4), S("gta", 14.6, 16.6, z=1.05), S("gta", 10.4, 11.6)],
         texts=[T(["christmas gifts", "that are actually", "worth it 🎁"], 0, None, 400, 72),
                T(["1. coloring blanket"], 0, 3.1, 640, 60, "plate"), T(["2. light-up heels"], 3.1, 5.7, 640, 60, "plate"),
                T(["3. money lamp"], 5.7, "end", 640, 60, "plate")],
         cta_cy=1330),
]


# ------------------------------- текст -------------------------------
def text_png(t: dict, key: str) -> Path:
    dest = WORK / f"txt_{key}.png"
    if t["mode"] == "wall":
        text = "\n".join(t["lines"])
        px = t["px"]
        while px > 30:
            if WL.wall_height(text, px) <= WL.Y1 - WL.Y0 - 8 and len([x for x in WL.wall_lines(text, px) if x]) <= \
                    len([x for x in t["lines"] if x]):
                break
            px -= 1
        top = max(WL.Y0 + 4, int(t["cy"] - WL.wall_height(text, px) / 2))
        WL.render_wall(text, px, top, dest)
        return dest
    px = t["px"]
    while True:
        B.LINES = t["lines"]
        st = dict(font=TT, px=px, fx="stroke", cy=t["cy"], plate=(255, 255, 255), ink=(0, 0, 0))
        im = B.text_layer(st, "plate" if t["mode"] == "plate" else "caption")
        if not check_overlay(im) or px <= 40:
            break
        px -= 2
    B.LINES = CTA
    bad = check_overlay(im)
    if bad:
        raise SystemExit(f"{key}: текст вне безопасной зоны — {bad}")
    im.save(dest)
    return dest


def round_mask(w: int, h: int, r: int, dest: Path) -> Path:
    m = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * 4 - 1, h * 4 - 1), r * 4, fill=255)
    m.resize((w, h), Image.Resampling.LANCZOS).save(dest)
    return dest


# ------------------------------- видео -------------------------------
def crop_for(seg: dict, ow: int, oh: int, band: tuple[float, float]) -> tuple[int, int, int, int]:
    """Кадр нужной пропорции внутри чистой полосы (нормированный 1080×1920 источник), с доп. зумом и центром."""
    y0, y1 = band[0] * H, band[1] * H
    ar = ow / oh
    ch = min(y1 - y0, W / ar) / seg["z"]
    cw = ch * ar
    cy = (seg["cy"] if seg["cy"] is not None else (band[0] + band[1]) / 2) * H
    top = min(max(cy - ch / 2, y0), y1 - ch)
    left = min(max(seg["cx"] * W - cw / 2, 0), W - cw)
    cw, ch = int(cw) // 2 * 2, int(ch) // 2 * 2
    return cw, ch, int(left), int(top)


CUTS = {k: [float(x) for x in v.split()] for k, v in
        (ln.split(" ", 1) for ln in (WORK / "cuts.txt").read_text(encoding="utf-8").splitlines() if " " in ln)}     if (WORK / "cuts.txt").exists() else {}
MIN_PIECE = 0.15                                      # обрывок чужого плана короче — это «вспышка»


def snap(seg: dict) -> dict:
    """Границы куска не режут план на обрывки < 0.15 с (иначе на стыке мелькает соседний кадр исходника)."""
    cuts = [c for c in CUTS.get(seg["src"], []) if seg["t0"] < c < seg["t1"]]
    t0, t1 = seg["t0"], seg["t1"]
    if cuts and cuts[0] - t0 < MIN_PIECE:
        t0 = cuts[0] + 0.035
    if cuts and t1 - cuts[-1] < MIN_PIECE:
        t1 = cuts[-1] - 0.035
    return {**seg, "t0": t0, "t1": t1}


def audit(spec: dict) -> list[str]:
    """Повторы кадров внутри ролика (в т.ч. одно и то же сверху и снизу в сплите) и внутренние вспышки."""
    segs = [snap(x) for tr in ([spec["top"], spec["bottom"]] if spec["layout"] == "split" else [spec["segs"]])
            for x in tr]
    out = []
    for a_i, a in enumerate(segs):
        for b in segs[a_i + 1:]:
            ov = min(a["t1"], b["t1"]) - max(a["t0"], b["t0"])
            if a["src"] == b["src"] and ov > 0.1:
                out.append(f"повтор {a['src']} {max(a['t0'], b['t0']):.2f}–{min(a['t1'], b['t1']):.2f}")
        cuts = [a["t0"]] + [c for c in CUTS.get(a["src"], []) if a["t0"] < c < a["t1"]] + [a["t1"]]
        for x, y in zip(cuts, cuts[1:]):
            if y - x < 0.12:
                out.append(f"вспышка {a['src']} {x:.2f}–{y:.2f}")
    return out


def seg_chain(i: int, seg: dict, ow: int, oh: int, band: tuple[float, float]) -> str:
    seg = snap(seg)
    cw, ch, x, y = crop_for(seg, ow, oh, band)
    d = seg["t1"] - seg["t0"]
    return (f"[{i}:v]trim=duration={d:.3f},setpts=PTS-STARTPTS{',reverse' if seg['rev'] else ''},"
            f"setpts=PTS/{seg['sp']},scale={W}:{H}:flags=lanczos,setsar=1,crop={cw}:{ch}:{x}:{y},"
            f"scale={ow}:{oh}:flags=lanczos,setsar=1{',hflip' if seg['mir'] else ''},fps={FPS},format=yuv420p[s{i}]")


def build(spec: dict) -> dict:
    key = f"{spec['n']:02d}_{spec['name']}"
    ins, chains = [], []
    nin = [0]                                          # счётчик входов ffmpeg

    def add(args: list[str]) -> int:
        ins.extend(args)
        nin[0] += 1
        return nin[0] - 1
    lay = spec["layout"]
    tracks = [spec["top"], spec["bottom"]] if lay == "split" else [spec["segs"]]
    if lay == "split":
        size = (W, 954)
    elif lay == "frame":
        b = spec.get("band", BAND[spec["segs"][0]["src"]])
        fw = spec.get("fw", 940)
        size = (fw, int(fw * (b[1] - b[0]) * H / W) // 2 * 2)
    else:
        size = (W, H)
    durs, labels = [], []
    for tr in tracks:
        lab = []
        tr = [snap(x) for x in tr]
        for seg in tr:
            i = add(["-ss", f"{seg['t0']:.3f}", "-t", f"{seg['t1'] - seg['t0'] + 0.2:.3f}", "-i",
                     str(SRC / f"{FILES[seg['src']]}.mp4")])
            band = spec.get("band", BAND[seg["src"]])
            chains.append(seg_chain(i, seg, size[0], size[1], band))
            lab.append(f"[s{i}]")
        durs.append(sum((s["t1"] - s["t0"]) / s["sp"] for s in tr))
        labels.append(lab)
    D = round(min(durs), 3)
    for k, lab in enumerate(labels):
        chains.append(f"{''.join(lab)}concat=n={len(lab)}:v=1:a=0,trim=duration={D}[t{k}]")
    if lay == "split":
        chains.append(f"[t0]pad={W}:966:0:0:white[tp];[tp][t1]vstack[base]")
    elif lay == "frame":
        mask = round_mask(size[0], size[1], 34, WORK / f"mask_{key}.png")
        mi = add(["-loop", "1", "-t", f"{D + 0.5:.3f}", "-i", str(mask)])
        chains.append(f"[t0]split[f1][f2];[f2]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                      f"gblur=sigma=34,eq=brightness=-0.13:saturation=1.1[bg];[{mi}:v]format=gray[mk];"
                      f"[f1][mk]alphamerge[fm];[bg][fm]overlay=(W-w)/2:{spec['fy']}:shortest=1[base]")
    else:
        chains.append("[t0]null[base]")
    chains.append(f"[base]crop={W - 8}:{H - 8}:4:4,scale={W}:{H}:flags=lanczos,setsar=1,{GRADE[spec['grade']]},"
                  f"format=yuv420p,noise=alls=4:allf=t,format=yuv420p[g0]")   # noise на gbrp (после colorbalance) чернит край
    # тексты: хук(и) до CTA, CTA последние 3 с
    layers = []
    for j, t in enumerate(spec["texts"]):
        if t["t1"] == "end":                           # остаётся и под CTA (подпись не пересекается с ним)
            layers.append((text_png(t, f"{key}_{j}"), t["t0"], D))
            continue
        t1 = D - 3 if t["t1"] is None else (D + t["t1"] if t["t1"] < 0 else t["t1"])
        layers.append((text_png(t, f"{key}_{j}"), t["t0"], min(t1, D - 3)))
    cta = dict(lines=CTA, t0=D - 3, t1=D, cy=spec["cta_cy"], px=76, mode="plate")
    layers.append((text_png(cta, f"{key}_cta"), D - 3, D))
    cur = "g0"
    for j, (png, a, b) in enumerate(layers):
        li = add(["-loop", "1", "-t", f"{D + 0.5:.3f}", "-i", str(png)])
        fade = f",fade=t=in:st={a:.3f}:d=0.2:alpha=1" if j == len(layers) - 1 else ""
        chains.append(f"[{li}:v]format=rgba{fade}[L{j}];[{cur}][L{j}]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'"
                      f"[o{j}]")
        cur = f"o{j}"
    # музыка
    mk, off = spec["music"]
    ai = add(["-ss", str(off), "-i", str(MUSIC[mk])])
    chains.append(f"[{ai}:a]atrim=duration={D},asetpts=PTS-STARTPTS,afade=t=in:d=0.05,"
                  f"afade=t=out:st={max(0, D - 0.5):.3f}:d=0.5,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[a]")
    dest = OUT / f"{key}_1346.mp4"
    cmd = [FF, "-v", "error", "-y", *ins, "-filter_complex", ";".join(chains), "-map", f"[{cur}]", "-map", "[a]",
           "-t", f"{D}", "-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "27", "-b:v", "0",
           "-maxrate", "6M", "-bufsize", "12M", "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dest)]
    (WORK / f"cmd_{key}.txt").write_text("\n".join(cmd), encoding="utf-8")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        (WORK / f"err_{key}.txt").write_text(" ".join(cmd) + "\n\n" + r.stderr, encoding="utf-8")
        raise SystemExit(f"{key}: ffmpeg упал — {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ''}")
    return dict(file=dest.name, hypothesis=spec["hyp"], layout=lay, music=mk, duration=D,
                products="+".join(sorted({s["src"] for tr in tracks for s in tr})))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    rows = []
    for spec in SPECS:
        bad = audit(spec)
        if bad:
            print(f"! {spec['n']:02d} {spec['name']}: " + "; ".join(bad), flush=True)
        if only and f"{spec['n']:02d}" not in only:
            continue
        row = build(spec)
        rows.append(row)
        print(f"✓ {row['file']}  {row['duration']:.1f} с  {row['hypothesis']}", flush=True)
    if rows and not only:
        with (WORK / "hypotheses.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter=";")
            w.writeheader()
            w.writerows(rows)
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
