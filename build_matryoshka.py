"""Матрёшка РП — «Жизнь в Матрёшке»: смешные сцены из войс-чата игроков, 9:16, хук сверху, субтитры снизу,
1–2 ИИ-фразы кента (ElevenLabs, эффект войс-чата), промокод OTDUSHI перебивкой ближе к концу (не в конце).

ТЗ 17.11 (250 TT + 250 YT), реф youtube.com/shorts/1XqujrRPQZc. Партия 1 — тема «первая работа и бабки»:
сессия лесопилки (Gameplay + Voice chat Artem.mp4); следующие партии — другие локации (gta_video.mp4: город, машины).

Сборка (CLAUDE.md): cuvid обрезает окно 9:16 вокруг героя и увеличивает до 1080×1920 → кадры в памяти → select
кусков речи (склейка без пауз, скорость 1) → через кусок «наезд» камеры (×ZOOM2) → стоп-кадр под промокод (loop) →
слои (хук, субтитры, фраза кента, плашка промокода) обычным overlay → NVENC. Звук собирается в numpy по тем же кускам:
войс-чат + фраза кента (полоса 250–3800 Гц, сжатие) с приглушением, писк на мате, whoosh/pop на промокоде.

  python build_matryoshka.py --test                # 4 тестовых ролика → output/matryoshka_test
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import gpu_ffmpeg as G  # noqa: E402
from core.safe_zones import check_box  # noqa: E402

W, H, FPS, SR = 1080, 1920, 30, 48000
D = ROOT / "downloads" / "matryoshka"
SRC = D / "src" / "Gameplay + Voice chat Artem.mp4"
SW, SH = 2346, 1080
WORK = ROOT / "output" / "_work" / "matryoshka"
VO = D / "vo"
SFX = ROOT / "downloads" / "drops_beats" / "sfx"
FONT = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf" / "TikTokSans12pt-Black.ttf"
FONT_B = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf" / "TikTokSans12pt-ExtraBold.ttf"

# хуки — ДОСЛОВНО из ТЗ (кэпшн сверху)
HOOKS = ["ЧЕЕЕ ТУТ ПРОИСХОДИТ АХАХАХ", "ЧТО У ВАС НА СЕРВЕРЕ ТВОРИТСЯ", "САМЫЙ СПОКОЙНЫЙ ДЕНЬ В МАТРЁШКЕ",
         "Я ПРОСТО ЗАШЁЛ ПОИГРАТЬ…", "ПАЦАНЫ, ЭТО ВООБЩЕ НОРМАЛЬНО?", "КУДА Я ПОПАЛ АХАХАХ",
         "ТУТ ВООБЩЕ БЫВАЕТ СПОКОЙНО?", "КТО ВСЕХ ЭТИХ ЛЮДЕЙ СОБРАЛ", "НУ С ТАКИМИ КЕНТАМИ НЕ СОСКУЧИШЬСЯ",
         "КАЖДЫЙ РАЗ ДУМАЮ, ЧТО ВИДЕЛ УЖЕ ВСЁ", "ОБЫЧНЫЙ ДВИЖ НА НАШЕМ СЕРВЕРЕ", "А НАЧИНАЛОСЬ ВСЁ НОРМАЛЬНО",
         "МЫ ВРОДЕ ПРОСТО ПОКАТАТЬСЯ СОБИРАЛИСЬ", "КТО-НИБУДЬ ОБЪЯСНИТ, ЧТО ЩАС БЫЛО?", "ЗАШЁЛ НА ПЯТЬ МИНУТ, ГОВОРИЛИ ОНИ"]
# логичные переносы хуков (смысл по строкам, не по ширине)
HOOK_LINES = {
    "ЧЕЕЕ ТУТ ПРОИСХОДИТ АХАХАХ": ["ЧЕЕЕ ТУТ ПРОИСХОДИТ", "АХАХАХ"],
    "ЧТО У ВАС НА СЕРВЕРЕ ТВОРИТСЯ": ["ЧТО У ВАС", "НА СЕРВЕРЕ ТВОРИТСЯ"],
    "САМЫЙ СПОКОЙНЫЙ ДЕНЬ В МАТРЁШКЕ": ["САМЫЙ СПОКОЙНЫЙ ДЕНЬ", "В МАТРЁШКЕ"],
    "Я ПРОСТО ЗАШЁЛ ПОИГРАТЬ…": ["Я ПРОСТО ЗАШЁЛ", "ПОИГРАТЬ…"],
    "ПАЦАНЫ, ЭТО ВООБЩЕ НОРМАЛЬНО?": ["ПАЦАНЫ,", "ЭТО ВООБЩЕ НОРМАЛЬНО?"],
    "КУДА Я ПОПАЛ АХАХАХ": ["КУДА Я ПОПАЛ", "АХАХАХ"],
    "ТУТ ВООБЩЕ БЫВАЕТ СПОКОЙНО?": ["ТУТ ВООБЩЕ", "БЫВАЕТ СПОКОЙНО?"],
    "КТО ВСЕХ ЭТИХ ЛЮДЕЙ СОБРАЛ": ["КТО ВСЕХ ЭТИХ ЛЮДЕЙ", "СОБРАЛ"],
    "НУ С ТАКИМИ КЕНТАМИ НЕ СОСКУЧИШЬСЯ": ["НУ С ТАКИМИ КЕНТАМИ", "НЕ СОСКУЧИШЬСЯ"],
    "КАЖДЫЙ РАЗ ДУМАЮ, ЧТО ВИДЕЛ УЖЕ ВСЁ": ["КАЖДЫЙ РАЗ ДУМАЮ,", "ЧТО ВИДЕЛ УЖЕ ВСЁ"],
    "ОБЫЧНЫЙ ДВИЖ НА НАШЕМ СЕРВЕРЕ": ["ОБЫЧНЫЙ ДВИЖ", "НА НАШЕМ СЕРВЕРЕ"],
    "А НАЧИНАЛОСЬ ВСЁ НОРМАЛЬНО": ["А НАЧИНАЛОСЬ ВСЁ", "НОРМАЛЬНО"],
    "МЫ ВРОДЕ ПРОСТО ПОКАТАТЬСЯ СОБИРАЛИСЬ": ["МЫ ВРОДЕ ПРОСТО", "ПОКАТАТЬСЯ СОБИРАЛИСЬ"],
    "КТО-НИБУДЬ ОБЪЯСНИТ, ЧТО ЩАС БЫЛО?": ["КТО-НИБУДЬ ОБЪЯСНИТ,", "ЧТО ЩАС БЫЛО?"],
    "ЗАШЁЛ НА ПЯТЬ МИНУТ, ГОВОРИЛИ ОНИ": ["ЗАШЁЛ НА ПЯТЬ МИНУТ,", "ГОВОРИЛИ ОНИ"],
}
VO_MAP = json.loads((WORK / "vo_map.json").read_text(encoding="utf-8")) if (WORK / "vo_map.json").exists() else {}

# мат: в субтитрах звёздочки, в звуке писк
BAD = [(r"^ху[её]?ли", "х*ли"), (r"^бля(дь|ть)?", "б**ть"), (r"^гондон", "г*ндон"), (r"^ебан", "е*ан"),
       (r"^нахер", "на*ер"), (r"^сука", "с*ка"), (r"^пизд", "п*зд")]


def censor(word: str) -> tuple[str, bool]:
    m = re.match(r"^([«\"(]*)(.*?)([.,!?…»\")]*)$", word)
    pre, core_, post = m.groups()
    for pat, rep in BAD:
        if re.match(pat, core_.lower()):
            rep = rep.capitalize() if core_[:1].isupper() else rep
            if rep.startswith("б**ть") and core_.lower() in ("бля", "блять", "блядь"):
                rep = "б**" if core_.lower() == "бля" else rep
            return pre + rep + post, True
    return word, False


# ---------------- сцены (партия 1: лесопилка / первая работа) ----------------
# lines: (начало, конец, текст субтитра) по времени исходника; keep: куски исходника (с, с) — что остаётся в ролике;
# ai: (файл кента, время в исходнике, куда встаёт фраза — в естественную паузу или в конец)
SCENES = {
    "malo": dict(
        keep=[(313.95, 316.0), (319.75, 342.0)],
        words="malo",
        fix={"Хули": "Х*ли", "блядь.": "б**ть.", "блядь": "б**ть", "что": "чё", "Что": "Чё"},
        drop_words=(312.0, 313.9),
        ai=("mr_06_A.mp3", 324.75),
        promo_after=336.1,
        hook="ПАЦАНЫ, ЭТО ВООБЩЕ НОРМАЛЬНО?",
        cx=0.5),
    "sbila": dict(
        keep=[(144.1, 151.15), (152.7, 155.55), (160.05, 161.45), (164.0, 166.6), (167.7, 178.2)],
        words="sbila",
        fix={"Попет": "Мопед", "Гондон?": "г*ндон!", "Бердал.": "", "помню.": "понял.", "машу.": "машу...",
             "хочу...": ""},
        ai=("mr_02_A.mp3", 177.35),
        promo_after=171.95,
        hook="ЧТО У ВАС НА СЕРВЕРЕ ТВОРИТСЯ",
        cx=0.5),
    "shtany": dict(
        keep=[(484.25, 487.05), (491.95, 494.0), (496.0, 510.4), (517.45, 519.6)],
        words="shtany",
        fix={"Ебан,": "Е*ан,", "Тигарь,": "", "шурму": "шаурму", "свекобой.": "свэгбой.", "ба.": "", "Елки,": "Ёлки,",
             "порвал.": "порвал!"},
        ai=("mr_13_A.mp3", 519.55),
        promo_after=508.8,
        hook="А НАЧИНАЛОСЬ ВСЁ НОРМАЛЬНО",
        cx=0.5),
    "mashina": dict(
        keep=[(1107.55, 1118.1), (1119.45, 1123.4), (1140.75, 1145.0)],
        lines=[(1107.7, 1109.5, "О, стой, я выйду."), (1110.6, 1112.5, "Пацаны, здорово!"),
               (1112.8, 1115.5, "А чё это? Можно тут где-то на права сдать?"),
               (1115.8, 1118.0, "Знаете, где здесь на права сдать?"),
               (1119.6, 1123.3, "Ребятки, подскажите, пожалуйста."),
               (1140.9, 1142.6, "Короче,"), (1142.6, 1144.9, "мне нужна твоя машина, пацан.")],
        ai=("mr_14_B.mp3", 1144.95),
        promo_after=1123.35,
        hook="КУДА Я ПОПАЛ АХАХАХ",
        cx=0.5),
}

# фразы кента v2 (PHRASES_v2_dialogue.md): файлы vo2/<сцена>_<k>.wav появятся после нарезки утренней генерации
def _v2(scene: str, at) -> list:
    return [(f"../vo2/{scene}_{k}.wav", at) for k in (1, 2)]


SCENES.update({
    "smena": dict(
        keep=[(88.35, 109.0)], words="smena", fix={"шурмы": "шаурмы", "трех": "трёх"},
        ai=("mr_05_B.mp3", 96.55), hook="ОБЫЧНЫЙ ДВИЖ НА НАШЕМ СЕРВЕРЕ", cx=0.5),
    "kach": dict(
        keep=[(263.0, 278.0)], words="kach", fix={},
        ai=("mr_09_A.mp3", 277.75), hook="Я ПРОСТО ЗАШЁЛ ПОИГРАТЬ…", cx=0.5),
    "shaur": dict(
        keep=[(524.3, 549.4)],
        lines=[(524.3, 525.3, "Так, шаурма."), (525.4, 527.0, "Пойдём похаваем шаурмы."),
               (527.1, 528.9, "А тут пицца нарисована."), (530.5, 533.0, "Братанчик, я возьму себе за 150 рублей."),
               (533.3, 535.5, "Так, съесть. Две штуки."), (535.7, 536.2, "Я съел."),
               (536.4, 539.2, "И я съел на три соточки, похавал нормально, братан."),
               (539.5, 542.0, "О, тут можно крутить кейс новичка."), (544.1, 544.6, "Мне предложили."),
               (547.3, 549.2, "2500 денег мне дали, представляешь?")],
        ai=("mr_05_B.mp3", 549.3), hook="САМЫЙ СПОКОЙНЫЙ ДЕНЬ В МАТРЁШКЕ", cx=0.5),
    "orly": dict(
        keep=[(567.9, 588.3)],
        lines=[(567.9, 568.9, "Тэш, 2500."), (569.1, 570.0, "Так же, как мне."), (571.6, 572.1, "Вау!"),
               (574.6, 575.5, "Смотри, вертолёт!"), (576.4, 577.0, "Где вертолёт?"), (577.4, 578.4, "Тут орлы летают!"),
               (579.9, 580.8, "Над нами орлы."), (583.6, 584.6, "Что, где вертолёт?"), (585.0, 585.5, "Я не знаю."),
               (585.6, 586.8, "А ты?"), (587.7, 588.2, "А ты где?")],
        ai=("mr_12_C.mp3", 588.35), hook="КУДА Я ПОПАЛ АХАХАХ", cx=0.5),
    "kuda": dict(
        keep=[(786.0, 810.2), (813.9, 823.6)], words="kuda", fix={"Когда": "Куда", "есть.": "ехать."},
        ai=("mr_04_A.mp3", 823.6), hook="МЫ ВРОДЕ ПРОСТО ПОКАТАТЬСЯ СОБИРАЛИСЬ", cx=0.5),
    "prava": dict(
        keep=[(872.4, 882.8), (909.2, 919.5)], words="prava", fix={"просрал": "пр*срал"},
        ai=("mr_11_A.mp3", 875.3), hook="КТО-НИБУДЬ ОБЪЯСНИТ, ЧТО ЩАС БЫЛО?", cx=0.5),
    "rap": dict(
        keep=[(921.6, 949.6)], words="rap", fix={"застязать.": "", "рэ": "", "респектой": ""},
        ai=("mr_09_A.mp3", 949.95), hook="НУ С ТАКИМИ КЕНТАМИ НЕ СОСКУЧИШЬСЯ", cx=0.5),
    "dozhd": dict(
        keep=[(1061.0, 1066.1), (1074.4, 1099.6)],
        lines=[(1061.0, 1062.0, "Братанчик, дождик."), (1062.1, 1064.2, "Я пойду постою под этим."),
               (1064.3, 1066.0, "Не хочу мокнуть."), (1074.5, 1076.6, "Очень устал после этой лесорубки."),
               (1081.7, 1083.4, "Ну-ка, я посмотрю на тебя, братан."), (1083.9, 1085.5, "Как-то посвежее выглядишь?"),
               (1089.1, 1090.8, "Посвежее? Да, посвежее ты как будто."), (1091.9, 1092.3, "Я прям устал."),
               (1093.4, 1096.2, "Всё, поехали. Надо смыть всю грязь после работы."),
               (1097.5, 1099.5, "Сейчас, погоди, я под дождём помоюсь немножко ещё.")],
        ai=("mr_13_A.mp3", 1099.55), hook="КАЖДЫЙ РАЗ ДУМАЮ, ЧТО ВИДЕЛ УЖЕ ВСЁ", cx=0.5),
})
for _n, _sc in SCENES.items():                              # текущая фраза + две v2 под тот же момент
    _sc["ai_opts"] = [_sc["ai"]] + _v2(_n, _sc["ai"][1])

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("split_vo2", str(WORK / "split_vo2.py"))
_sv = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_sv)
V2_TEXT = {f"../vo2/{sc}_{k}.wav": t for sc, k, t in _sv.LINES}


def est_len(text: str) -> float:
    """Ожидаемая длина фразы ElevenLabs, с: разговорно ~13 знаков/с + вдох."""
    return round(max(1.4, len(text) / 13 + 0.35), 2)


# ---------------- текст ----------------
def font(px: int, path: Path = FONT) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), px)


def wrap(lines: list[str], f: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Строка шире зоны — делим по пробелу ближе к середине (логично, не жадно)."""
    out = []
    for ln in lines:
        if f.getlength(ln) <= max_w or " " not in ln:
            out.append(ln)
            continue
        ws = ln.split()
        best = min(range(1, len(ws)), key=lambda k: abs(f.getlength(" ".join(ws[:k])) - f.getlength(" ".join(ws[k:]))))
        out += wrap([" ".join(ws[:best]), " ".join(ws[best:])], f, max_w)
    return out


def text_png(lines: list[str], px: int, top: int, fill=(255, 255, 255), stroke: float = 0.11,
             max_w: int = 790, min_px: int = 64) -> Image.Image:
    """Белый (или цветной) текст с ровной чёрной обводкой, строки по центру; кегль уменьшается под ширину зоны
    до min_px, дальше — перенос строки."""
    while px > min_px and max(font(px).getlength(ln) for ln in lines) + 2 * max(3, round(px * stroke)) > max_w:
        px -= 2
    lines = wrap(lines, font(px), max_w - 2 * max(3, round(px * stroke)))
    while True:
        f = font(px)
        st = max(3, round(px * stroke))
        if max(f.getlength(ln) for ln in lines) + 2 * st <= max_w or px <= 40:
            break
        px -= 2
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    asc, desc = f.getmetrics()
    adv = round(px * 1.12)
    for i, ln in enumerate(lines):
        d.text((W / 2, top + i * adv + asc), ln, font=f, anchor="ms", fill=fill + (255,), stroke_width=st,
               stroke_fill=(0, 0, 0, 255))
    return img


STOP_RU = {"и", "в", "на", "с", "а", "не", "что", "у", "по", "за", "к", "из", "от", "до", "же", "ну", "я", "мы", "ты", "он", "это", "так"}


def chunks_of(words: list[tuple[float, float, str]], max_words: int = 3, max_chars: int = 20) -> list[tuple]:
    """Слова → куски субтитров по 1–3 слова: рвём на знаке препинания и по длине."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        txt = " ".join(x[2] for x in cur)
        weak = re.sub(r"[^а-яё]", "", w[2].lower()) in STOP_RU and not re.search(r"[.!?…,]$", w[2])
        if ((len(cur) >= max_words and not weak) or len(cur) >= max_words + 2 or (len(txt) >= max_chars and not weak)
                or re.search(r"[.!?…]$", w[2]) or (re.search(r",$", w[2]) and len(cur) >= 2)):
            out.append((cur[0][0], cur[-1][1], txt))
            cur = []
    if cur:
        out.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
    return out


def scene_words(sc: dict) -> list[tuple[float, float, str]]:
    """Слова сцены (точное распознавание по окну) с правками и звёздочками; или строки из lines, разбитые по словам."""
    if "lines" in sc:
        ws = []
        for a, b, txt in sc["lines"]:
            parts = txt.split()
            step = (b - a) / len(parts)
            ws += [(a + i * step, a + (i + 1) * step, p) for i, p in enumerate(parts)]
        return ws
    allw = json.loads((WORK / "words_scenes.json").read_text(encoding="utf-8"))[sc["words"]]
    ws = []
    for a, b, t in sorted(allw, key=lambda w: w[0]):
        if "drop_words" in sc and sc["drop_words"][0] <= a <= sc["drop_words"][1]:
            continue
        if ws and a < ws[-1][1] - 0.05:                      # стык окон распознавания: то же слово ещё раз
            continue
        t = sc.get("fix", {}).get(t, t)
        if t.startswith("-") and ws:                           # «по -моему», «онлайн -игре» — склеить
            pa, pb, pt = ws[-1]
            ws[-1] = (pa, max(b, pb), pt + t)
            continue
        if t:
            ws.append((a, max(b, a + 0.12), t))
    return ws


def norm_ru(w: str) -> str:
    return re.sub(r"[^а-яё0-9a-z]", "", w.lower().replace("ё", "е"))


# ---------------- план ролика ----------------
GAP_MAX, PAD_IN, PAD_OUT = 0.7, 0.15, 0.22               # пауза длиннее 0.7 с вырезается (быстрый темп)


def split_pauses(keep: list, words: list, ai_at: float, ai_len: float, gap: float = GAP_MAX) -> list[list[float]]:
    """Внутри каждого куска вырезаем паузы между словами > GAP_MAX (джамп-каты); паузу под фразу кента оставляем
    длиной фразы."""
    out = []
    for a, b in keep:
        ws = sorted(w for w in words if a <= w[0] < b)
        cur = a
        for w0, w1 in zip(ws, ws[1:]):
            gap_a, gap_b = w0[1], w1[0]
            if gap_b - gap_a <= gap:
                continue
            if gap_a - 0.15 <= ai_at <= gap_b:                # пауза под кента
                cut_a = ai_at + ai_len + 0.35
            else:
                cut_a = gap_a + PAD_OUT
            cut_b = gap_b - PAD_IN
            if cut_b - cut_a > 0.3:
                out.append([cur, cut_a])
                cur = cut_b
        out.append([cur, b])
    return [k for k in out if k[1] - k[0] > 0.2]


def plan(name: str, sc: dict, rng: random.Random) -> dict:
    """Куски исходника, время каждого слова в ролике, место фразы кента и промокода."""
    ai_file, ai_at = sc["ai"]
    if isinstance(ai_at, str):                               # «после слова …» — конец первого такого слова сцены
        ai_at = next(w[1] for w in scene_words(sc) if norm_ru(ai_at) in norm_ru(w[2]) and w[0] >= sc["keep"][0][0]) + 0.08
    if (VO / ai_file).exists():
        ai_len = len(vo_audio(ai_file)) / SR                 # длина без тишины по краям (у ElevenLabs до 1.5 с хвоста)
    else:                                                    # ночная сборка: место под фразу по оценке длины
        ai_len = sc.get("ai_len_est") or est_len(V2_TEXT.get(ai_file, "") or "a" * 30)
    keep = split_pauses(sc["keep"], scene_words(sc), ai_at, ai_len, gap=sc.get("gap", GAP_MAX))
    # пауза под фразу кента: кусок от ai_at длиной фразы (+0.35 с) — внутри своего куска или в конце
    tail = ai_at + ai_len + 0.35
    # 18.11 юзер: «наша вставленная речь пусть не перебивается другими голосами». Фраза — после конца реплики (не внахлёст),
    # кусок идёт до конца фразы; всё, что ребята начали говорить под ней, вырезается: следующий кусок — с начала их
    # следующей реплики после фразы (а под фразой звук — фон этой же сцены без голосов, см. build_audio)
    allw = sorted(scene_words(sc))
    prev_end = max([w[1] for w in allw if w[1] <= ai_at + 0.05], default=ai_at)
    ai_at = max(ai_at, prev_end + 0.1)
    tail = ai_at + ai_len + 0.3
    nxt = [w[0] for w in allw if w[0] >= tail - 0.05]
    resume = (nxt[0] - PAD_IN) if nxt else None
    out_keep = []
    for k in keep:
        if k[1] <= ai_at - 0.12:
            out_keep.append(k)
        elif k[0] <= ai_at + 0.12:                            # кусок с фразой: до конца фразы
            out_keep.append([k[0], tail])
            if resume is not None and k[1] > resume + 0.3:   # продолжение — с начала следующей реплики
                out_keep.append([max(resume, tail + 0.05), k[1]])
        else:                                                # куски после: не раньше следующей реплики
            if resume is None or k[1] <= resume + 0.3:
                continue
            out_keep.append([max(k[0], resume, tail + 0.05), k[1]])
    if not any(k[0] <= ai_at <= k[1] for k in out_keep):      # фраза после последнего куска (orly, rap)
        out_keep.append([max(ai_at - 0.15, out_keep[-1][1] if out_keep else ai_at - 0.15), tail])
    keep = [k for k in out_keep if k[1] - k[0] > 0.2]
    # склейка на кадрах: границы кусков — целые кадры
    pcs, t_out = [], 0.0
    for a, b in keep:
        fa, fb = round(a * FPS), round(b * FPS)
        pcs.append(dict(a=fa / FPS, b=fb / FPS, n=fb - fa, o=t_out))
        t_out += (fb - fa) / FPS
    words = [w for w in scene_words(sc) if any(p["a"] - 0.05 <= w[0] < p["b"] for p in pcs)]

    def out_t(t: float) -> float:
        for p in pcs:
            if p["a"] - 0.05 <= t <= p["b"] + 0.05:
                return p["o"] + min(max(t - p["a"], 0.0), p["n"] / FPS)
        return min((p["o"] for p in pcs if p["a"] > t), default=t_out)
    # промокод: стоп-кадр на 1.3 с после слова promo_after (на стыке/в паузе), сдвигает всё после него; без promo_after —
    # конец фразы на 60–78 % ролика, не под кентом (ТЗ: «перебивкой в середине, поближе к концу, не в конце»)
    if sc.get("promo_after") is None:
        ai_o = out_t(ai_at)
        ends = [w for w in words if re.search(r"[.!?…]$", w[2]) and not (ai_o - 0.4 <= out_t(w[1]) <= ai_o + ai_len + 0.4)]
        ok = [w for w in ends if 0.6 * t_out <= out_t(w[1]) <= 0.78 * t_out]
        pick = rng.choice(ok) if ok else min(ends or words, key=lambda w: abs(out_t(w[1]) - 0.7 * t_out))
        sc = dict(sc, promo_after=pick[1] + 0.02)
    promo_t = out_t(sc["promo_after"]) + 0.05
    promo_f = round(promo_t * FPS)
    promo_n = round(1.3 * FPS)
    shift = lambda t: t + (promo_n / FPS if t >= promo_t else 0.0)  # noqa: E731
    subs = []
    for a, b, txt in chunks_of(words):
        sa, sb = shift(out_t(a)), shift(out_t(b))
        subs.append([sa, sb, txt])
    for i in range(len(subs) - 1):                           # субтитр держится до следующего (без мигания)
        if subs[i + 1][0] - subs[i][1] < 0.6:
            subs[i][1] = subs[i + 1][0]
        else:
            subs[i][1] += 0.35
    if subs:
        subs[-1][1] += 0.3
    ai_t = shift(out_t(ai_at))
    total = t_out + promo_n / FPS
    bleeps = []
    for a, b, t in words:
        if censor(t)[1] or "*" in t:
            bleeps.append((shift(out_t(a)), shift(out_t(b))))
    quiet = [(a, b) for a, b in zip([w[1] for w in allw], [w[0] for w in allw][1:]) if b - a >= 0.6]
    return dict(name=name, pcs=pcs, subs=subs, promo_f=promo_f, promo_n=promo_n, ai=(ai_file, ai_t, ai_len),
                quiet=quiet[:6], slot=(ai_t, shift(out_t(tail)) if out_t(tail) > 0 else ai_t + ai_len + 0.3),
                total=total, nf=sum(p["n"] for p in pcs) + promo_n, bleeps=bleeps)


def probe_len(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout.strip())


# ---------------- звук ----------------
def load_audio(path: Path, t0: float = 0.0, dur: float | None = None, af: str | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{t0:.4f}", "-i", str(path)] + (["-t", f"{dur:.4f}"] if dur else [])
    cmd += (["-af", af] if af else []) + ["-vn", "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.float32).reshape(-1, 2).copy()


_VO: dict = {}


def vo_audio(name: str, af: str | None = None) -> np.ndarray:
    """Фраза ElevenLabs без тишины по краям (+60 мс воздуха с каждой стороны)."""
    key = (name, af)
    if key not in _VO:
        x = load_audio(VO / name, af=af)
        env = np.convolve(np.abs(x.mean(1)), np.ones(480) / 480, mode="same")
        on = np.nonzero(env > max(0.004, env.max() * 0.05))[0]
        if len(on):
            x = x[max(0, on[0] - 2880): min(len(x), on[-1] + 2880)]
        _VO[key] = x
    return _VO[key]


def _ltas(x: np.ndarray, nfft: int = 2048) -> tuple[np.ndarray, np.ndarray]:
    """Средний спектр речи (кадры громче 60-го процентиля) и RMS речи."""
    m = x.mean(1) if x.ndim == 2 else x
    hop = nfft // 2
    n = (len(m) - nfft) // hop
    if n < 4:
        return np.ones(nfft // 2 + 1), float(np.sqrt((m ** 2).mean()) + 1e-6)
    fr = np.stack([m[i * hop:i * hop + nfft] for i in range(n)]) * np.hanning(nfft)
    e = np.sqrt((fr ** 2).mean(1))
    sp = fr[e >= np.percentile(e, 60)]
    return (np.abs(np.fft.rfft(sp, axis=1)) ** 2).mean(0) + 1e-9, float(np.median(e[e >= np.percentile(e, 60)]))


def chat_match(k: np.ndarray, v: np.ndarray, speech: np.ndarray | None = None) -> np.ndarray:
    """Фразу ElevenLabs — под звук войс-чата исходника: эквалайзер по среднему спектру (±12 дБ, сглажено по 1/3 октавы),
    громкость речи = громкости живых голосов, снизу — шум чата (его же тихие места)."""
    nfft = 2048
    ps, rs = _ltas(speech if speech is not None and len(speech) > 4 * nfft else v, nfft)
    pk, rk = _ltas(k, nfft)
    g = np.sqrt(ps / pk)
    f = np.fft.rfftfreq(nfft, 1 / SR)
    gs = np.empty_like(g)
    for i, fi in enumerate(f):                                # сглаживание 1/3 октавы
        lo_, hi_ = fi / 2 ** (1 / 6), fi * 2 ** (1 / 6) + 1
        sel = (f >= lo_) & (f <= hi_)
        gs[i] = np.exp(np.log(g[sel] + 1e-9).mean()) if sel.any() else g[i]
    gs /= np.exp(np.log(gs[(f > 300) & (f < 3000)]).mean())  # уровень задаёт громкость ниже, тут только тембр
    gs = np.clip(gs, 10 ** (-12 / 20), 10 ** (12 / 20))
    m = k.mean(1)
    spec = np.fft.rfft(m, n=len(m) + nfft)
    fg = np.interp(np.fft.rfftfreq(len(m) + nfft, 1 / SR), f, gs)
    y = np.fft.irfft(spec * fg)[: len(m)].astype(np.float32)
    _, ry = _ltas(y[:, None].repeat(2, 1), nfft)
    y *= (rs / (ry + 1e-6)) * 1.12                           # на уровне живых голосов (+1 дБ: это панчлайн)
    mv = v.mean(1)                                           # шум чата: самые тихие куски исходника
    hop = 1024
    e = np.array([np.sqrt((mv[i:i + hop] ** 2).mean()) for i in range(0, len(mv) - hop, hop)])
    live = np.nonzero(e > 1e-4)[0]                            # без тишины стоп-кадра промокода
    q = live[np.argsort(e[live])[: max(4, len(live) // 10)]]
    noise = np.concatenate([mv[i * hop:(i + 1) * hop] for i in sorted(q)])
    if len(noise):
        reps = int(np.ceil(len(y) / len(noise)))
        y = y + np.tile(noise, reps)[: len(y)] * 0.8
    return np.stack([y, y], 1)


# ---------------- игровой войс: обработка фразы кента (юзер 18.11: «голос по вайбу не попадал в атмосферу войс-чата») ----
VC_PRESET = __import__("os").environ.get("MR_VC", "B")
VC_PRESETS = {
    # A — как у ребят в записи: тембр по среднему спектру их микрофонов + Opus 24 кбит/с (кодек войс-чатов)
    "A": dict(eq="match", pre="highpass=f=90", opus=24, gate=True, drive=0.0, loss=0, room=0.0),
    # B — Discord: гарнитура 100 Гц–7.5 кГц, быстрый компрессор (подкачка), шумодав, Opus 32 кбит/с
    "B": dict(eq="match", pre="highpass=f=100,lowpass=f=7500,afftdn=nr=10:nf=-40,"
                              "acompressor=threshold=0.06:ratio=6:attack=2:release=60:makeup=2", opus=32, gate=True,
              drive=0.15, loss=0, room=0.0),
    # C — дешёвый микрофон в игровом войсе: узкая полоса 250 Гц–4 кГц, середина вперёд, автогромкость, перегруз,
    #     Opus 16 кбит/с и 1–2 микропропуска пакетов, маленькая комната
    "C": dict(eq="none", pre="highpass=f=250,lowpass=f=4000,equalizer=f=1800:t=q:w=1.2:g=5,"
                              "dynaudnorm=f=75:g=5:p=0.9:m=20,acompressor=threshold=0.05:ratio=8:attack=1:release=40:makeup=3",
              opus=16, gate=True, drive=0.35, loss=2, room=0.12),
    # D — B, но ближе к записи ребят (эквалайзер по их спектру сильнее) + 1 микропропуск
    "D": dict(eq="match", pre="highpass=f=120,lowpass=f=6500,acompressor=threshold=0.06:ratio=5:attack=3:release=70:makeup=2",
              opus=20, gate=True, drive=0.2, loss=1, room=0.06),
}


def opus_rt(x: np.ndarray, kbps: int) -> np.ndarray:
    """Настоящий кодек войс-чатов: Opus (режим voip) туда и обратно — его «мыльце» на верхах и сжатие речи."""
    enc = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", "-c:a", "libopus",
                          "-b:a", f"{kbps}k", "-application", "voip", "-vbr", "on", "-f", "ogg", "-"],
                         input=x.astype(np.float32).tobytes(), capture_output=True).stdout
    dec = subprocess.run(["ffmpeg", "-v", "error", "-f", "ogg", "-i", "-", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         input=enc, capture_output=True).stdout
    y = np.frombuffer(dec, np.float32).copy()
    return y[: len(x)] if len(y) >= len(x) else np.pad(y, (0, len(x) - len(y)))


def vc_chain(k: np.ndarray, v: np.ndarray, rng: random.Random, preset: str | None = None,
             speech: np.ndarray | None = None) -> np.ndarray:
    """Фраза ElevenLabs → голос из игрового войс-чата (пресет A–D), громкость и шум — как у живых голосов записи."""
    P = VC_PRESETS[preset or VC_PRESET]
    m = k.mean(1).astype(np.float32)
    if P["pre"]:
        m = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                                          "-af", P["pre"], "-f", "f32le", "-"], input=m.tobytes(),
                                         capture_output=True).stdout, np.float32).copy()
    if P["drive"]:                                           # перегруз дешёвого микрофона
        g = 1 + 6 * P["drive"]
        m = np.tanh(m / (np.abs(m).max() + 1e-6) * g) / np.tanh(g) * (np.abs(m).max() + 1e-6)
    if P["room"]:                                            # маленькая комната (ранние отражения)
        d = int(0.013 * SR)
        r = np.zeros_like(m)
        r[d:] += m[:-d] * P["room"]
        r[2 * d:] += m[:-2 * d] * P["room"] * 0.6
        m = m + r
    m = opus_rt(m, P["opus"])
    for _ in range(P["loss"]):                               # микропропуск пакета (20–40 мс) с плавными краями
        if len(m) > SR // 2:
            a = rng.randrange(int(0.25 * len(m)), int(0.85 * len(m)))
            n = int(rng.uniform(0.02, 0.04) * SR)
            f = np.ones(n, np.float32)
            f[:48], f[-48:] = np.linspace(1, 0, 48), np.linspace(0, 1, 48)
            f[48:-48] = 0.0
            m[a:a + n] *= f[: len(m[a:a + n])]
    if P["gate"]:                                            # шумовой гейт войса: хвосты обрезаются
        env = np.convolve(np.abs(m), np.ones(480) / 480, mode="same")
        th = env.max() * 0.04
        gm = (env > th).astype(np.float32)
        gm = np.convolve(gm, np.ones(960) / 960, mode="same")
        m = m * np.clip(gm * 1.2, 0, 1)
    k2 = np.stack([m, m], 1)
    if P["eq"] == "match":
        return chat_match(k2, v, speech)                     # тембр/громкость под РЕЧЬ ребят, шум — из записи
    _, rs = _ltas(v)
    _, rk = _ltas(k2)
    y = m * (rs / (rk + 1e-6)) * 1.12
    mv = v.mean(1)
    hop = 1024
    e = np.array([np.sqrt((mv[i:i + hop] ** 2).mean()) for i in range(0, len(mv) - hop, hop)])
    live = np.nonzero(e > 1e-4)[0]
    q = live[np.argsort(e[live])[: max(4, len(live) // 10)]]
    noise = np.concatenate([mv[i * hop:(i + 1) * hop] for i in sorted(q)]) if len(q) else np.zeros(1, np.float32)
    y = y + np.tile(noise, int(np.ceil(len(y) / len(noise))))[: len(y)] * 0.8
    return np.stack([y, y], 1)


def room_tone(pp: dict, n: int) -> np.ndarray | None:
    """Фон сцены без голосов длиной n отсчётов: склейка тихих мест между репликами этой же сцены (с переходами)."""
    parts = []
    for a, b in pp.get("quiet", []):
        x = load_audio(SRC, a + 0.15, max(0.2, b - a - 0.3))
        if len(x) > 2400:
            parts.append(x)
    if not parts:
        return None
    out, xf = parts[0], 1200
    while len(out) < n:
        nx = parts[len(out) % len(parts)]
        r = np.linspace(0, 1, xf)[:, None]
        out = np.concatenate([out[:-xf], out[-xf:] * (1 - r) + nx[:xf] * r, nx[xf:]])
    return out[:n].astype(np.float32)


def build_audio(pp: dict, out_wav: Path, rng: random.Random) -> None:
    n_total = round(pp["total"] * SR)
    mix = np.zeros((n_total + SR, 2), np.float32)
    voice = []
    for i, p in enumerate(pp["pcs"]):
        x = load_audio(SRC, p["a"], p["n"] / FPS)[: round(p["n"] / FPS * SR)]
        f = min(len(x), 220)                                 # микро-фейд на стыке (без щелчков)
        if f:
            x[:f] *= np.linspace(0, 1, f)[:, None]
            x[-f:] *= np.linspace(1, 0, f)[:, None]
        voice.append(x)
    v = np.concatenate(voice)
    pa = round(pp["promo_f"] / FPS * SR)
    pn = round(pp["promo_n"] / FPS * SR)
    v = np.concatenate([v[:pa], np.zeros((pn, 2), np.float32), v[pa:]])
    # громкость войс-чата: к −16 LUFS грубо — по пику речи
    peak = np.percentile(np.abs(v), 99.5) + 1e-6
    vscale = 0.55 / peak
    v *= vscale
    # фраза кента — как ещё один голос В ТОМ ЖЕ войс-чате (юзер 17.11: «тупо прозвучали… нету общего голосового чата»):
    # тембр подгоняется под микрофоны исходника (средний спектр речи), голос проходит «канал» войс-чата (16 кГц, сжатие),
    # громкость = громкости живых голосов, под ней шум чата; исходник почти не глушится (0.7), фраза заходит внахлёст
    ai_file, ai_t, ai_len = pp["ai"]
    if not (VO / ai_file).exists():                         # ночная сборка видео: фразы ещё нет — звук дособерётся утром
        k = np.zeros((1, 2), np.float32)
    else:
        k = vo_audio(ai_file)
        real = len(k) / SR
        if real > ai_len * 1.06:                             # длиннее места — чуть ускорить (не больше ×1.3)
            k = vo_audio(ai_file, af=f"atempo={min(1.3, real / ai_len):.3f}")
        sp = np.concatenate([v[round(a * SR):round(b * SR)] for a, b, _ in pp["subs"] if b > a] or [v])
        k = vc_chain(k, v, rng, pp.get("vc"), speech=sp)
    ka = max(0, round(ai_t * SR))                            # после конца реплики, не внахлёст
    s0, s1 = pp.get("slot", (ai_t, ai_t + len(k) / SR + 0.3))
    a0, a1 = max(0, round(s0 * SR)), min(len(v), round(s1 * SR))
    tone = room_tone(pp, a1 - a0)                            # фон этой же сцены без голосов
    if tone is not None and a1 > a0:
        tone *= vscale                                       # тот же уровень, что у чата
        f = min(2400, (a1 - a0) // 4)
        w_ = np.ones(a1 - a0, np.float32)
        w_[:f], w_[-f:] = np.linspace(0, 1, f), np.linspace(1, 0, f)
        v[a0:a1] = v[a0:a1] * (1 - w_[:, None]) + tone * w_[:, None]
    # писк на мате
    for a, b in pp["bleeps"]:
        s0, s1 = round(a * SR), round(b * SR)
        v[s0:s1] = 0
        t = np.arange(s1 - s0) / SR
        v[s0:s1] += (0.22 * np.sin(2 * np.pi * 1000 * t))[:, None]
    mix[: len(v)] += v[: len(mix)]
    mix[ka:ka + len(k)] += k[: max(0, len(mix) - ka)]
    laughs = sorted((VO.parent / "vo2").glob("laugh_*.wav"))
    if laughs:                                               # смешок другого кента на хвосте фразы, тише (−7 дБ)
        lf = rng.choice(laughs)
        lg = vc_chain(load_audio(lf), v, rng, pp.get("vc"))[: int(1.2 * SR)] * 0.5   # смешок ≤ 1.2 с, тише фразы
        fo = min(len(lg), int(0.25 * SR))
        lg[-fo:] *= np.linspace(1, 0, fo)[:, None]
        la = ka + len(k) + int(0.05 * SR)                    # ПОСЛЕ фразы — фразу никто не перебивает (юзер 18.11)
        mix[la:la + len(lg)] += lg[: max(0, len(mix) - la)]
    # промокод: whoosh + pop
    wh = load_audio(SFX / "whoosh" / rng.choice(["swing_487667.mp3", "simple_382724.mp3"]))[: SR]
    pop = load_audio(SFX / "pop" / rng.choice(["pop_402323.mp3", "minimal_467466.mp3"]))[: SR // 2]
    a0 = max(0, pa - len(wh) // 3)
    mix[a0:a0 + len(wh)] += wh[: len(mix) - a0] * 0.5
    mix[pa + SR // 10:pa + SR // 10 + len(pop)] += pop[: max(0, len(mix) - pa - SR // 10)] * 0.6
    mix = mix[:n_total]
    mix = (np.tanh(mix * 1.1) / np.tanh(1.1)).astype(np.float32)   # мягкий лимитер; float32 — иначе в ffmpeg шум
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", str(SR), str(out_wav)], input=mix.tobytes(), check=True)


# ---------------- картинки ----------------
def promo_png(dest: Path) -> None:
    """Перебивка: затемнение кадра + фиолетовая плашка «ПРОМОКОД / OTDUSHI / в описании ↓» по центру зоны."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 120))
    d = ImageDraw.Draw(img)
    bw, bh = 780, 400
    x0, y0 = (W - bw) // 2, 720
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=48, fill=(124, 58, 237, 245), outline=(255, 255, 255, 255),
                        width=6)
    d.text((W / 2, y0 + 92), "ПРОМОКОД", font=font(62, FONT_B), anchor="ms", fill=(255, 255, 255, 230))
    d.text((W / 2, y0 + 235), "OTDUSHI", font=font(150), anchor="ms", fill=(255, 221, 0, 255),
           stroke_width=6, stroke_fill=(40, 10, 90, 255))
    d.text((W / 2, y0 + 340), "в описании ↓", font=font(64, FONT_B), anchor="ms", fill=(255, 255, 255, 255))
    assert not check_box(W, H, (x0, y0, x0 + bw, y0 + bh)), check_box(W, H, (x0, y0, x0 + bw, y0 + bh))
    img.save(dest)


def top_shade(img: Image.Image, y1: int) -> Image.Image:
    """Мягкое затемнение сверху под хуком (чат и уведомления игры под текстом — каша): 45 % → 0 к y1."""
    a = np.zeros((H, 1), np.float32)
    a[:y1, 0] = np.linspace(0.62, 0.0, y1) ** 1.2
    sh = Image.fromarray(np.dstack([np.zeros((H, W, 3), np.uint8), (np.repeat(a, W, 1) * 255).astype(np.uint8)]), "RGBA")
    return Image.alpha_composite(sh, img)



def crop_layer(png: Path) -> tuple[Path, int, int]:
    """Слой PNG → только его непрозрачная часть + место (x, y): overlay маленькой картинки вместо кадра 1080×1920."""
    im = Image.open(png)
    bb = im.getbbox()
    if not bb or (bb[2] - bb[0]) * (bb[3] - bb[1]) > 0.8 * im.width * im.height:
        return png, 0, 0
    x0, y0 = bb[0] // 2 * 2, bb[1] // 2 * 2
    out = png.with_name(png.stem + "_c.png")
    im.crop((x0, y0, bb[2], bb[3])).save(out, compress_level=1)
    return out, x0, y0


def layers(pp: dict, hook: str, keep: Path) -> list[tuple[Path, float, float]]:
    """PNG-слои с временем показа: хук весь ролик, субтитры снизу, фраза кента жёлтым, плашка промокода."""
    out = []
    hk = text_png(HOOK_LINES.get(hook, [hook]), 96, 226, min_px=80)
    assert not check_box(W, H, hk.getbbox()), ("хук вне зоны", check_box(W, H, hk.getbbox()))
    hk = top_shade(hk, min(H, hk.getbbox()[3] + 160))
    hk.save(keep / "hook.png")
    out.append((keep / "hook.png", 0.0, pp["total"]))
    ai_file, ai_t, ai_len = pp["ai"]
    for i, (a, b, txt) in enumerate(pp["subs"]):
        if b <= ai_t - 0.02 or a >= ai_t + ai_len:          # под фразой кента — только её текст
            pass
        else:
            b = min(b, ai_t)
            if b - a < 0.15:
                continue
        p0, p1 = pp["promo_f"] / FPS, (pp["promo_f"] + pp["promo_n"]) / FPS
        if a < p1 and b > p0:                                 # на стоп-кадре промокода субтитров нет
            if a < p0:
                b = p0
            else:
                a = max(a, p1)
            if b - a < 0.15:
                continue
        txt = " ".join(censor(w)[0] for w in txt.split())
        txt = txt[:1].upper() + txt[1:]
        for top in (1420, 1380, 1340, 1300):              # 2 строки — чуть выше, но в безопасной зоне
            im = text_png([txt], 80, top)
            if not check_box(W, H, im.getbbox()):
                break
        assert not check_box(W, H, im.getbbox()), ("субтитр вне зоны", txt)
        p = keep / f"sub_{i:02d}.png"
        im.save(p)
        out.append((p, a, b))
    phrase = VO_MAP.get(ai_file) or V2_TEXT.get(ai_file, "")
    words = phrase.split()
    half = (len(words) + 1) // 2
    lines = [" ".join(words[:half]), " ".join(words[half:])] if len(phrase) > 24 else [phrase]
    for top in (1370, 1330, 1290, 1250, 1210):               # как можно ниже, но в безопасной зоне
        im = text_png(lines, 74, top, fill=(255, 221, 0))
        if not check_box(W, H, im.getbbox()):
            break
    assert not check_box(W, H, im.getbbox()), ("фраза вне зоны", phrase)
    im.save(keep / "ai.png")
    out.append((keep / "ai.png", ai_t, ai_t + ai_len + 0.3))
    promo_png(keep / "promo.png")
    out.append((keep / "promo.png", pp["promo_f"] / FPS, (pp["promo_f"] + pp["promo_n"]) / FPS))
    return out


# ---------------- сборка ----------------
TOP_UI = 0.105                                          # задание игры («Сруби 3 дерева…») — верхние 10.5 % кадра


def window_m(cx: float, zoom: float) -> tuple[int, int, int, int]:
    """Окно 9:16 в исходнике Артёма: под заданием игры сверху, по центру героя (cx — доля ширины)."""
    cw, ch = G._even(SH * 9 / 16 / zoom), G._even(SH / zoom)
    x = G._even(min(SW - cw, max(0, SW * cx - cw / 2)))
    y = G._even(min(SH - ch, max(SH * TOP_UI, (SH - ch) / 2)))
    return x, y, cw, ch


def render(pp: dict, hook: str, dest: Path, keep: Path, cx: float = 0.5, zoom: float = 1.13, zoom2: float = 1.08,
           rng: random.Random | None = None, parity: int = 1, light_seed: int | None = None) -> Path:
    rng = rng or random.Random(1)
    keep.mkdir(parents=True, exist_ok=True)
    build_audio(pp, keep / "a.wav", rng)
    lays = layers(pp, hook, keep)
    if light_seed is not None:                               # своё «поле света» у каждого ролика (несхожесть)
        from build_vibecity import light_png
        light_png(random.Random(light_seed), keep / "light.png")
        lays.insert(0, (keep / "light.png", 0.0, pp["total"] + 1))
    cw, ch = G._even(SH * 9 / 16 / zoom), G._even(SH / zoom)
    x = G._even(min(SW - cw, max(0, SW * cx - cw / 2)))
    y = G._even(min(SH - ch, max(SH * TOP_UI, (SH - ch) / 2)))   # без задания игры сверху
    # куски — по НОМЕРАМ кадров от начала чтения (по времени набегал сдвиг в кадр на стыках, 17.11 сверка)
    f0 = max(0, round(pp["pcs"][0]["a"] * FPS) - 15)
    t0 = f0 / FPS
    rel = [(round(p["a"] * FPS) - f0, round(p["a"] * FPS) - f0 + p["n"] - 1) for p in pp["pcs"]]
    sel = lambda idx: "+".join(f"between(n,{rel[i][0]},{rel[i][1]})" for i in idx)  # noqa: E731
    odd, even = [i for i in range(len(rel)) if i % 2 != parity], [i for i in range(len(rel)) if i % 2 == parity]
    if not odd:                                              # один кусок и он «наезд» — без наезда
        odd, even = even, []
    dur = (rel[-1][1] + 20) / FPS
    cpu_dec = __import__("os").environ.get("MR_CPUDEC") == "1"
    if cpu_dec:                                              # распаковка процессором (проверка: cuvid и кадры записи)
        inp = ["-ss", f"{t0:.4f}", "-t", f"{dur:.4f}", "-i", str(SRC)]
    else:
        inp = ["-ss", f"{t0:.4f}", "-t", f"{dur:.4f}", *G.gpu_input(SRC, crop=(x, y, cw, ch), resize=(W, H))]
    zc_w, zc_h = G._even(W / zoom2), G._even(H / zoom2)
    pre_f = f"crop={cw}:{ch}:{x}:{y},scale={W}:{H}:flags=bicubic," if cpu_dec else ""
    n_in = 1
    if even and not cpu_dec:                                 # 18.11 скорость: «наезд» — окно поменьше прямо в распаковщике
        zy = int((H - zc_h) * 0.45) // 2 * 2
        pr = (x + (W - zc_w) / 2 * cw / W, y + zy * ch / H, zc_w * cw / W, zc_h * ch / H)
        inp += ["-ss", f"{t0:.4f}", "-t", f"{dur:.4f}", *G.gpu_input(SRC, crop=pr, resize=(W, H))]
        n_in = 2
        fc = [f"[0:v]fps={FPS},select='{sel(odd)}'[p1]",
              f"[1:v]fps={FPS},select='{sel(even)}',setsar=1[p2]", "[p1][p2]interleave=nb_inputs=2[vi]"]
    else:
        fc = [f"[0:v]fps={FPS},{pre_f}split=2[v1][v2]",
              f"[v1]select='{sel(odd)}'[p1]"]
        if even:
            fc.append(f"[v2]select='{sel(even)}',crop={zc_w}:{zc_h}:{(W - zc_w) // 2}:{int((H - zc_h) * 0.45) // 2 * 2},"
                      f"scale={W}:{H}:flags=bicubic,setsar=1[p2]")
            fc.append("[p1][p2]interleave=nb_inputs=2[vi]")
        else:
            fc.append("[v2]nullsink")
            fc.append("[p1]null[vi]")
    fc.append(f"[vi]setpts=N/{FPS}/TB,fps={FPS},loop=loop={pp['promo_n']}:size=1:start={pp['promo_f']},"
              f"setpts=N/{FPS}/TB,format=yuv420p[b0]")
    cur, inputs = "b0", []
    for i, (png, a, b) in enumerate(lays):
        png, ox, oy = crop_layer(png)
        inputs += ["-i", str(png)]
        lab = f"l{i}"
        fc.append(f"[{i + n_in + 1}:v]format=rgba[{lab}]")
        nxt = f"o{i}"
        fc.append(f"[{cur}][{lab}]overlay={ox}:{oy}:enable='between(t,{a:.3f},{b:.3f})'[{nxt}]")
        cur = nxt
    fc.append(f"[{cur}]format=yuv420p[v]")
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", *inp, "-i", str(keep / "a.wav"), *inputs, "-filter_complex", ";".join(fc),
           "-map", "[v]", "-map", f"{n_in}:a", "-frames:v", str(pp["nf"]), *G.NVENC, "-c:a", "aac", "-b:a", "160k",
           *G.CLEAN, str(dest)]
    from core.gpu_slots import gpu_slot
    with gpu_slot():
        r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-1500:])
    return dest


# ---------------- партия ----------------
BAND = (560, 1248)                                       # полоса без текста (ниже хука, выше субтитров) — для сверки
BSIZE = (136, 86)                                        # полоса в 1/8, чётная (cuvid -resize)


def variant(rng: random.Random, name: str) -> dict:
    """Вариант ролика сцены: фраза кента, длина вырезаемых пауз, место промокода, хук, окно/зум/«наезд», свет."""
    sc = dict(SCENES[name])
    v2 = [o for o in sc.get("ai_opts", []) if "vo2" in o[0]]
    opts = v2 or [sc["ai"]]                                  # фразы v2 под момент (ночью их ещё нет — место по тексту)
    sc["ai"] = rng.choice(opts)
    sc["gap"] = round(rng.uniform(0.45, 0.9), 2)
    if sc.get("promo_auto", True):
        sc["promo_after"] = None
    pp = plan(name, sc, rng)
    hook = sc["hook"] if rng.random() < 0.4 else rng.choice(HOOKS)
    # 18.11 ночь: при 50 вариантах на сцену узкий разброс давал 15–70 общих кадров — шире зум/сдвиг/«наезд»
    return dict(pp=pp, hook=hook, cx=round(sc.get("cx", 0.5) + rng.uniform(-0.07, 0.07), 3),
                zoom=round(rng.uniform(1.05, 1.3), 3), zoom2=round(rng.uniform(1.04, 1.14), 3), parity=rng.randrange(2),
                light_seed=rng.randrange(10 ** 9), seed=rng.randrange(10 ** 9))


def frame_check_m(v: dict, G_: np.ndarray, keep: Path, margin: float = 1.2, junk: float = 18.0) -> list:
    """Каждый кадр полосы BAND = кадр исходника по плану (окно, зум, «наезд», свет); стоп-кадр промокода пропускается.
    Повторы кадров самой записи (~6 %) дают ничью соседей (запас < margin) — не флаг."""
    pp = v["pp"]
    y0, y1 = BAND
    bw, bh = BSIZE
    lay = Image.open(keep / "light.png").crop((0, y0, W, y1)).resize((bw, bh), Image.Resampling.BOX)
    la = np.asarray(lay, np.float32)
    al, lg = la[..., 3] / 255, la[..., 0] * 0.299 + la[..., 1] * 0.587 + la[..., 2] * 0.114
    if len(G_) != pp["nf"]:
        return [("кадров", len(G_), pp["nf"])]
    x, y, cw, ch = window_m(v["cx"], v["zoom"])
    zc_w, zc_h = G._even(W / v["zoom2"]), G._even(H / v["zoom2"])
    zy = int((H - zc_h) * 0.45) // 2 * 2
    pf, pn = pp["promo_f"], pp["promo_n"]
    n_odd = sum(1 for i in range(len(pp["pcs"])) if i % 2 != v["parity"])
    # исходник читается ТАК ЖЕ, как в сборке: один поток с кадра f0, кадры по номерам (запись с переменной частотой —
    # отдельное чтение каждого куска по времени расходилось на кадр на неровных местах)
    f0 = max(0, round(pp["pcs"][0]["a"] * FPS) - 15)
    span = round(pp["pcs"][-1]["a"] * FPS) + pp["pcs"][-1]["n"] - f0 + 20
    from core.gpu_slots import gpu_slot
    reads = {}
    for punch in (False, True):
        if punch:
            X0, X1, Y0, Y1 = (W - zc_w) / 2, (W + zc_w) / 2, zy + y0 * zc_h / H, zy + y1 * zc_h / H
        else:
            X0, X1, Y0, Y1 = 0, W, y0, y1
        sx, sy, sw_, sh_ = x + X0 * cw / W, y + Y0 * ch / H, (X1 - X0) * cw / W, (Y1 - Y0) * ch / H
        with gpu_slot():                                     # тот же распаковщик, что в сборке (18.11: процессор 94 %)
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{f0 / FPS:.4f}", "-t", f"{span / FPS:.4f}",
                                  *G.gpu_input(SRC, crop=(sx, sy, sw_, sh_), resize=(bw, bh)),
                                  "-vf", f"fps={FPS},format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        reads[punch] = np.frombuffer(raw, np.uint8).reshape(-1, bh, bw).astype(np.float32) * (1 - al) + lg * al
    flags, f = [], 0
    for i, p in enumerate(pp["pcs"]):
        src = reads[(i % 2 == v["parity"]) and n_odd > 0]
        base = round(p["a"] * FPS) - f0
        for j in range(p["n"]):
            sj = f + j
            if sj == pf:
                continue
            oj = sj + (pn if sj > pf else 0)
            if oj >= len(G_):
                continue
            kk = min(base + j, len(src) - 1)
            d = {dk: float(np.abs(G_[oj] - src[kk + dk]).mean()) for dk in range(-3, 4) if 0 <= kk + dk < len(src)}
            best = min(d, key=d.get)
            if d[best] > junk:
                flags.append((oj, "мусор", round(d[best], 1)))
            elif best != 0 and d[0] - d[best] > margin:
                flags.append((oj, best, round(d[0] - d[best], 2)))
        f += p["n"]
    return flags


def build_m(v: dict, tmp: Path, keep: Path) -> tuple[bool, str, np.ndarray | None]:
    from core import clip_batch as CB
    tmp.with_suffix(".json").write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
    render(v["pp"], v["hook"], tmp, keep, cx=v["cx"], zoom=v["zoom"], zoom2=v["zoom2"], rng=random.Random(v["seed"]),
           parity=v["parity"], light_seed=v["light_seed"])
    G_, H_ = CB.decode(tmp, BAND, size=BSIZE)
    fr = frame_check_m(v, G_, keep)
    if fr:
        return False, f"кадры не те {fr[:4]}", None
    return True, "", CB.hash_of(H_)


def audio_pass(jobs: int = 6) -> int:
    """Утро: для каждого готового ролика (план в batch/meta) собрать звук с фразой v2 и смешком и заменить звук,
    видео копируется как есть (кадры и проверки — ночные)."""
    from concurrent.futures import ThreadPoolExecutor
    meta = WORK / "batch" / "meta"
    jobs_ = []
    for js in sorted(meta.glob("*.json")):
        name = js.name[:-5]
        hits = list((ROOT / "output").glob(f"matryoshka_*/{name}"))
        if hits and not (__import__("os").environ.get("MR_AUDIO_SKIPDONE") == "1"
                         and hits[0].stat().st_mtime > js.stat().st_mtime + 120):   # звук уже наложен — пропуск
            jobs_.append((js, hits[0]))
    miss = sorted({json.loads(js.read_text(encoding="utf-8"))["pp"]["ai"][0] for js, _ in jobs_}
                  - {f for f in V2_TEXT if (VO / f).exists()})
    if miss:
        print("нет файлов фраз:", miss[:6], "… — сначала split_vo2.py")
        return 1

    def one(item):
        js, mp4 = item
        v = json.loads(js.read_text(encoding="utf-8"))
        keep = WORK / "batch" / "audio" / mp4.stem
        keep.mkdir(parents=True, exist_ok=True)
        build_audio(v["pp"], keep / "a.wav", random.Random(v["seed"]))
        tmp = keep / "out.mp4"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp4), "-i", str(keep / "a.wav"), "-map", "0:v",
                            "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", *G.CLEAN, str(tmp)],
                           capture_output=True, text=True)
        if r.returncode:
            return mp4.name, r.stderr[-300:]
        tmp.replace(mp4)
        return mp4.name, ""
    bad = 0
    with ThreadPoolExecutor(jobs) as ex:
        for i, (nm, err) in enumerate(ex.map(one, jobs_), 1):
            if err:
                bad += 1
                print("  ошибка", nm, err, flush=True)
            if i % 50 == 0:
                print(f"  звук: {i}/{len(jobs_)}", flush=True)
    print(f"ИТОГ звук: {len(jobs_) - bad}/{len(jobs_)}")
    return 0 if not bad else 1


def audition(n: int = 3) -> int:
    """Прослушка: n готовых роликов (разные сцены) × пресеты A–D — только звук, видео копируется →
    output/matryoshka_audition/<пресет>/."""
    meta = WORK / "batch" / "meta"
    picks, seen = [], set()
    for js in sorted(meta.glob("*.json")):
        v = json.loads(js.read_text(encoding="utf-8"))
        sc = v["pp"]["name"]
        if sc in seen or not (VO / v["pp"]["ai"][0]).exists():
            continue
        hits = list((ROOT / "output").glob(f"matryoshka_1_*/{js.name[:-5]}"))
        if hits:
            picks.append((v, hits[0]))
            seen.add(sc)
        if len(picks) >= n:
            break
    for pre in __import__("os").environ.get("MR_AUD", "".join(VC_PRESETS)):
        d = ROOT / "output" / "matryoshka_audition" / pre
        d.mkdir(parents=True, exist_ok=True)
        for v, mp4 in picks:
            pp = dict(v["pp"], vc=pre)
            keep = WORK / "audition" / pre / mp4.stem
            keep.mkdir(parents=True, exist_ok=True)
            build_audio(pp, keep / "a.wav", random.Random(v["seed"]))
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp4), "-i", str(keep / "a.wav"), "-map", "0:v",
                            "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", *G.CLEAN,
                            str(d / f"{pre}_{v['pp']['name']}_{mp4.name}")], check=True)
        print(pre, "→", d, len(picks), flush=True)
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--tt", type=int, default=0)
    ap.add_argument("--yt", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--audition", type=int, default=0, help="прослушка: N роликов × пресеты войса A–D")
    ap.add_argument("--audio", action="store_true", help="утро: звук фраз v2 в готовые ролики (видео не трогать)")
    ap.add_argument("--vtest", type=int, default=0, help="N вариантов на сцену через партийный путь (проверка сверки)")
    a = ap.parse_args()
    if a.audition:
        return audition(a.audition)
    if a.audio:
        return audio_pass(a.jobs)
    if a.tt or a.yt or a.vtest:
        from core import clip_batch as CB
        # kach и prava: в записи на одних и тех же местах кадр сбивается на 1 при любой сборке (17.11) — не в партию
        names = [n for n in SCENES if (n in a.only if a.only else n not in ("kach", "prava"))]
        slots = []
        if a.vtest:
            d = ROOT / "output" / "matryoshka_vtest"
            slots = [(n, d / f"matryoshka_vtest_{n}_{k}_1.mp4") for n in names for k in range(a.vtest)]
        for tag, n in (("tt", a.tt), ("yt", a.yt)):
            d = ROOT / "output" / f"matryoshka_1_{tag.upper()}_{n}"
            slots += [(names[i % len(names)], d / f"matryoshka_{tag}_{i + 1:03d}_1.mp4") for i in range(n)]
        return 0 if CB.run(slots, variant, build_m, jobs=a.jobs, work=WORK / "batch", label="Матрёшка", seed=1711) else 1
    out = ROOT / "output" / "matryoshka_test"
    rng = random.Random(17)
    for i, (name, sc) in enumerate(SCENES.items(), 1):
        if a.only and name not in a.only:
            continue
        pp = plan(name, sc, rng)
        dest = out / f"matryoshka_test_{i:02d}_{name}_1.mp4"
        render(pp, sc["hook"], dest, WORK / "test" / name, cx=sc.get("cx", 0.5), rng=rng)
        bad = G.bad_frames(dest)
        print(f"{dest.name}: {pp['total']:.1f} с, кусков {len(pp['pcs'])}, субтитров {len(pp['subs'])}, "
              f"промокод с {pp['promo_f'] / FPS:.1f} с, кент с {pp['ai'][1]:.1f} с; плохих кадров {len(bad)} {bad[:5]}",
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
