#!/usr/bin/env python3
"""
Пул картинок для слайда карусели с Pinterest: поиск по запросам →
(слайд 1) похожесть на реф-картинку + «похожие пины» лучших находок →
фильтры (ИИ-метка Pinterest, UGC «живое фото», надписи на картинке,
размер/формат, повторы одного фото) → лучшие кадры 1080×1440 (3:4).

  python harvest_carousel_pool.py --profile tired_s1 --out output/tired_pool/s1 --target 120
  python harvest_carousel_pool.py --profile tired_s2 --out output/tired_pool/s2 --target 80

Выход: <out>/NNN_<pin>.jpg + manifest.json + _sheet.jpg (ручной отбор: лишнее
просто удалить из папки — сборщик каруселей берёт то, что осталось).
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
OUT_W, OUT_H = 1080, 1440

# Профили слайдов. ref — реф-картинки (похожесть по SigLIP), anchors —
# описание сцены словами, related_rounds — сколько раз расширять пул
# «похожими пинами» лучших находок.
PROFILES: dict[str, dict] = {
    # Реф: @lovesickmia, кадр 1 — девушка лежит в кровати, рука у щеки,
    # смотрит в камеру, мягкий свет, светлое бельё
    "tired_s1": {
        "ref": [ROOT / "output" / "carousel_refs" / "lovesickmia_1.jpg"],
        "anchors": [
            "a young woman lying in bed with her hand on her cheek looking at the camera",
            "a sleepy girl resting her head on a pillow in a cozy bedroom",
            "a tired woman lying in bed under a blanket, soft light",
        ],
        # «girl» вместе с «bed» / «selfie» Pinterest без входа отдаёт пусто —
        # только woman / без подлежащего
        "queries": [
            "woman lying in bed selfie",
            "woman in bed aesthetic",
            "lazy morning in bed",
            "cozy bed aesthetic woman",
            "woman resting head on pillow",
            "bed selfie aesthetic",
            "sleepy selfie",
            "morning bed selfie",
            "woman under blanket cozy",
            "tired woman",
            "woman lying on pillow hand on cheek",
            "lying in bed looking at camera",
            "morning in bed aesthetic",
            "bed rot aesthetic",
            "sick day in bed aesthetic",
            "tired woman blanket couch",
            "woman lying on couch blanket",
            "sunday in bed aesthetic",
            "brunette woman bed selfie",
            "blonde woman lying in bed",
            "messy hair morning selfie",
            "cozy autumn morning bed woman",
            "white sheets selfie aesthetic",
            "pillow selfie aesthetic",
        ],
        "related_rounds": 2,
        "related_seeds": 14,
        "weights": {"ref": 0.55, "text": 0.15, "ugc": 0.30},
        "min_ref": 0.55,
    },
    # Жизнь героини: ресторан / кафе / её дом (несмысловой, можно повторять
    # между каруселями, но не внутри одной)
    "tired_s2": {
        "ref": [],
        "anchors": [
            "a candid photo of a cozy restaurant dinner table with candles",
            "a candid photo of a cafe table with coffee and dessert",
            "a cozy apartment living room in the evening",
            "a cozy kitchen at home with warm light",
            "a girl's cozy bedroom with fairy lights",
        ],
        "queries": [
            "dinner date restaurant aesthetic",
            "restaurant table candles aesthetic",
            "cozy restaurant night aesthetic",
            "cafe table coffee dessert aesthetic",
            "fall cafe aesthetic",
            "wine dinner table candid",
            "pasta dinner restaurant aesthetic",
            "cozy apartment aesthetic evening",
            "cozy living room fall aesthetic",
            "cozy kitchen aesthetic warm light",
            "cozy bedroom fairy lights",
            "home aesthetic autumn",
            "woman dinner restaurant candid",
            "brunch table aesthetic",
            "city bistro night aesthetic",
            "cozy home night candles",
        ],
        "related_rounds": 1,
        "related_seeds": 10,
        "weights": {"ref": 0.0, "text": 0.55, "ugc": 0.45},
        "min_ref": 0.0,
        "no_faces": True,  # чужое лицо на 2-м слайде ломает историю героини
        "ugc_floor": 0.35,  # сцены без людей UGC-модель недооценивает
    },
    # Второй проход для слайда 2: дом и кофе без людей
    "tired_s2_home": {
        "ref": [],
        "anchors": [
            "a cozy apartment interior in the evening with warm lamps",
            "a cup of coffee on a table at home, candid",
            "a cozy bedroom with a made bed and soft light",
            "breakfast on a table at home, candid photo",
            "a cozy kitchen at home with warm light",
        ],
        "queries": [
            "coffee at home aesthetic",
            "morning coffee table aesthetic",
            "cozy apartment aesthetic",
            "cozy bedroom aesthetic evening",
            "breakfast at home aesthetic",
            "latte cafe table aesthetic",
            "cozy kitchen evening aesthetic",
            "home aesthetic warm lamp",
            "living room evening lamp aesthetic",
            "coffee cup window aesthetic",
            "iced coffee aesthetic",
            "cozy fall apartment",
            "fall home decor cozy",
            "cafe window seat aesthetic",
            "tea and candles at home",
            "cozy night in aesthetic",
        ],
        "related_rounds": 1,
        "related_seeds": 10,
        "weights": {"ref": 0.0, "text": 0.6, "ugc": 0.4},
        "min_ref": 0.0,
        "no_faces": True,
        "ugc_floor": 0.35,
    },
}

# «правила папы» (реф @cravingthetea): слайды 9:16, эстетичные фото без лиц, как в рефе
_DAD = {"no_faces": True, "out": (1080, 1920), "min_aspect": 1.4, "related_rounds": 1, "related_seeds": 8,
        "weights": {"ref": 0.4, "text": 0.4, "ugc": 0.2}, "min_ref": 0.0}
PROFILES["dad_s2"] = {**_DAD,  # «I'm Not Like Other Guys» — образ без лица, улица, осень
    "ref": [ROOT / "downloads" / "dad_rules" / "ref" / "slide_2.jpg"],
    "anchors": ["faceless outfit photo of a girl in a leather jacket and jeans on a city street",
                "aesthetic fall street style, cropped at the neck, no face"],
    "queries": ["leather jacket outfit aesthetic", "fall outfit street aesthetic", "faceless outfit aesthetic",
                "city walk outfit fall", "brown leather jacket jeans outfit", "street style autumn aesthetic",
                "outfit inspo no face", "fall aesthetic girl walking city"]}
PROFILES["dad_s3"] = {**_DAD,  # «Face-Down Phone» — телефон экраном вниз на столе, свидание
    "ref": [ROOT / "downloads" / "dad_rules" / "ref" / "slide_3.jpg"],
    "anchors": ["a smartphone lying face down on a restaurant table next to two drinks",
                "date night table with wine glasses and a phone face down, cozy dim light"],
    "queries": ["phone face down on table", "date night table aesthetic", "restaurant table wine aesthetic",
                "dinner date aesthetic table", "two glasses of wine aesthetic", "cafe table phone aesthetic",
                "bar date night aesthetic", "candle dinner table aesthetic"]}
PROFILES["dad_s5"] = {**_DAD,  # «Exit Rule» — свои деньги, свои ключи, свой план
    "ref": [ROOT / "downloads" / "dad_rules" / "ref" / "slide_4.jpg"],
    "anchors": ["a woman's hand holding car keys, aesthetic close-up",
                "car keys, wallet and cash on a table, independent woman aesthetic"],
    "queries": ["car keys aesthetic", "holding car keys aesthetic", "keys and wallet aesthetic",
                "new car keys girl", "wallet aesthetic cash", "keys coffee aesthetic", "car key in hand aesthetic",
                "independent woman aesthetic"]}
PROFILES["dad_s6"] = {**_DAD,  # «если спрашиваешь дважды…» — тихий кадр: кофе, кафе, осень
    "ref": [ROOT / "downloads" / "dad_rules" / "ref" / "slide_6.jpg"],
    "anchors": ["an iced coffee on an outdoor cafe table with fallen autumn leaves",
                "quiet moody cafe aesthetic, coffee on a wooden bench, no people"],
    "queries": ["iced coffee aesthetic outside", "coffee autumn aesthetic", "cafe table aesthetic fall",
                "iced latte bench aesthetic", "coffee and book aesthetic", "rainy cafe aesthetic",
                "moody coffee aesthetic", "fall leaves coffee aesthetic"]}

# «правила бабушки» (тот же реф @cravingthetea, Cozy Home): тема важнее сходства с рефом
_GM = {**_DAD, "weights": {"ref": 0.2, "text": 0.6, "ugc": 0.2}}
PROFILES["gm_s2"] = {**_GM,  # The Mother Rule — как он относится к маме
    "ref": [ROOT / "downloads" / "dad_rules" / "ref" / "slide_6.jpg"],
    "anchors": ["a grown son holding his elderly mother's hand, warm candid photo, faces not visible",
                "a man bringing a bouquet of flowers to his mother, cozy home, candid"],
    "queries": ["son holding mom hand aesthetic", "flowers for mom aesthetic", "mother and son aesthetic",
                "holding mother's hand aesthetic", "family sunday dinner aesthetic", "mom and son hands",
                "sunday lunch at mom's aesthetic", "bouquet for mom aesthetic"]}
PROFILES["gm_s3"] = {**_GM,  # The Birthday Rule
    "ref": [ROOT / "downloads" / "dad_rules" / "ref" / "slide_6.jpg"],
    "anchors": ["a birthday cake with lit candles on a table, cozy aesthetic, no people",
                "birthday flowers and a wrapped gift on a table, aesthetic photo"],
    "queries": ["birthday cake candles aesthetic", "birthday aesthetic", "birthday flowers gift aesthetic",
                "birthday dinner aesthetic", "slice of cake candle aesthetic", "birthday table aesthetic",
                "birthday balloons aesthetic", "heart cake aesthetic"]}
PROFILES["gm_s5"] = {**_GM,  # The Running-Away Money Rule — «just in case money»
    "ref": [ROOT / "downloads" / "dad_rules" / "ref" / "slide_6.jpg"],
    "anchors": ["hands holding cash in an envelope, savings aesthetic",
                "a wallet with cash and a bank card on a table, aesthetic close-up"],
    "queries": ["cash envelope aesthetic", "savings jar aesthetic", "wallet cash aesthetic", "money aesthetic hands",
                "cash stuffing envelopes", "piggy bank aesthetic", "counting money aesthetic", "bank card aesthetic"]}
PROFILES["gm_s6"] = {**_GM,  # Her last rule — смех: пара держится за руки / смеётся
    "ref": [ROOT / "downloads" / "dad_rules" / "ref" / "slide_6.jpg"],
    "anchors": ["an elderly couple holding hands, warm candid photo",
                "a young couple laughing together walking in the rain, candid, faces not visible"],
    "queries": ["old couple holding hands aesthetic", "couple holding hands aesthetic", "couple laughing aesthetic",
                "couple in the rain aesthetic", "elderly couple aesthetic", "couple walking holding hands",
                "grandparents holding hands", "couple aesthetic no face"]}

# 1281 (Global Work, «потеряла работу, но кормлю семью»): живые домашние кадры 3:4 без лиц, рефов нет —
# отбор по описанию сцены + «любительскость»; слайды 1 (лица семьи) и 6 (экран приложения) генерируем
_GW = {"no_faces": True, "out": (1080, 1440), "min_aspect": 1.3, "related_rounds": 1, "related_seeds": 8,
       "weights": {"ref": 0.0, "text": 0.7, "ugc": 0.3}, "min_ref": 0.0, "ref": []}
PROFILES["gw_s2"] = {**_GW,  # утренняя кухня, кофе, рука/силуэт, детские рисунки или рюкзак; грустно
    "anchors": ["a mug of coffee on a kitchen table in the early morning, a kid's school backpack nearby, quiet sad mood",
                "a woman's hand holding a coffee mug in a dim kitchen at dawn, children's drawings on the fridge"],
    "queries": ["morning coffee kitchen aesthetic", "early morning kitchen moody", "school backpack kitchen morning",
                "kids drawings on fridge", "mom morning coffee", "coffee mug kitchen window morning",
                "school morning routine kitchen", "lonely morning coffee"]}
PROFILES["gw_s3"] = {**_GW, "max_text_chars": 40,  # ноутбук ночью, много вкладок с вакансиями
    "anchors": ["an open laptop at night on a desk showing job search websites, dim room",
                "a laptop screen glowing in the dark with many browser tabs, job applications"],
    "queries": ["laptop at night aesthetic", "job search laptop", "working late laptop dark", "applying for jobs laptop",
                "laptop in the dark", "late night laptop desk", "job hunting aesthetic", "laptop in bed at night"]}
PROFILES["gw_s4"] = {**_GW, "max_text_chars": 40,  # тёмная комната, свет экрана, около часа ночи
    "anchors": ["a dark bedroom at night lit only by the glow of a laptop screen, a clock showing 1 am",
                "late night insomnia, someone at a laptop in a dark room, only screen light"],
    "queries": ["late night laptop glow", "screen light in dark room", "1am aesthetic", "can't sleep laptop night",
                "insomnia aesthetic night", "clock 1am aesthetic", "working at night dark room", "laptop glow dark bedroom"]}
PROFILES["gw_s5"] = {**_GW, "max_text_chars": 2000,  # распечатанное резюме с пометками / стопка черновиков
    "anchors": ["a printed resume on a desk with red pen corrections and sticky notes",
                "a messy stack of printed cover letter drafts and a pen on a kitchen table"],
    "queries": ["resume on desk aesthetic", "printed resume with notes", "job application papers desk",
                "resume red pen", "cover letter draft", "stack of papers desk aesthetic",
                "job hunting desk paperwork", "resume and coffee"]}
PROFILES["gw_s7"] = {**_GW,  # семья со спины / рука мужа на её плече, тёплый свет
    "anchors": ["a family seen from behind sitting together on a couch at home in warm evening light",
                "a man's hand resting on a woman's shoulder at home, warm cozy light, faces not visible"],
    "queries": ["family from behind aesthetic", "family on couch warm light", "hand on shoulder couple",
                "family silhouette home", "husband hand on wife shoulder", "family cozy evening home",
                "parents and kids from behind", "family hug from behind"]}

# 1281, второй заход по 5 и 7 (первый дал офисные стопки бумаг и целующиеся пары)
PROFILES["gw_s5b"] = {**_GW, "max_text_chars": 2000,
    "anchors": ["a printed resume on a kitchen table at home with handwritten notes and highlighter marks, a coffee mug nearby",
                "crumpled cover letter drafts next to a laptop on a home desk, pen corrections"],
    "queries": ["resume with handwritten notes", "resume editing at home", "cv on table with coffee", "highlighted resume",
                "job application at kitchen table", "rewriting my resume", "cover letter writing desk",
                "resume printout pen"]}
PROFILES["gw_s7b"] = {**_GW,
    "anchors": ["a mother and her kids sitting on a couch seen from behind, cozy living room, warm lamp light",
                "a family watching tv together on the sofa in the evening, seen from behind"],
    "queries": ["mom and kids on couch from behind", "family watching tv from behind", "family movie night couch",
                "mom hugging kids from behind", "family on sofa evening cozy", "kids cuddling mom couch",
                "family back view home", "husband hand on wife shoulder at home"]}

# 1283 (Magic Sort, «парень на лавочке под дождём играл в телефон»): как 1281 — живые кадры 3:4 без лиц;
# слайд 1 (её селфи как в рефе @joey.growth) генерируем, на 4–6 экран телефона потом меняем на Magic Sort
_RB = {**_GW}
PROFILES["rb_s2"] = {**_RB, "max_text_chars": 40,  # скучные свидания: телефоны на столе, еду ещё не принесли
    "anchors": ["two smartphones lying on a restaurant table next to two drinks, a boring first date, no food yet",
                "a date night table at a restaurant with phones out and cocktails, waiting for the food"],
    "queries": ["phones on restaurant table", "date night table aesthetic", "first date restaurant aesthetic",
                "dinner date drinks table", "boring date aesthetic", "two drinks restaurant table",
                "waiting for food restaurant aesthetic", "phone on table date night"]}
PROFILES["rb_s3"] = {**_RB,  # дождливый вечер, парень на лавочке уткнулся в телефон (издалека / сбоку)
    "anchors": ["a guy sitting alone on a bench in the rain in the evening, looking at his phone, seen from a distance",
                "rainy city street at night with wet pavement and street lights, a young man on a bench with a phone"],
    "queries": ["man on bench rain", "guy sitting on bench phone", "rainy evening city aesthetic", "rainy night street aesthetic",
                "man sitting on bench at night", "rain bench aesthetic", "boy on bench rain aesthetic",
                "rainy evening walk aesthetic"]}
PROFILES["rb_s4"] = {**_RB, "max_text_chars": 40,  # «what are you playing?» — он поворачивает экран ко мне (POV)
    "anchors": ["a man's hand holding a smartphone out toward the camera to show the screen, rainy street at night",
                "POV someone shows you their phone screen, city lights bokeh in the rain"],
    "queries": ["hand holding phone showing screen", "showing phone screen pov", "man holding phone out",
                "phone in hand rain night", "holding phone city lights", "hand holding iphone night street",
                "showing someone your phone", "phone screen rain aesthetic"]}
PROFILES["rb_s5"] = {**_RB, "max_text_chars": 40,  # Magic Sort крупно: его руки, телефон с игрой, вечер, дождь
    "anchors": ["close-up of a man's hands holding a smartphone and playing a mobile game, rain drops, evening street lights",
                "hands playing a game on a phone while sitting on a bench at night"],
    "queries": ["hands playing phone game", "man hands holding phone close up", "playing games on phone aesthetic",
                "phone in hands rain", "mobile game in hands", "holding phone with both hands night",
                "phone gaming aesthetic", "hands holding phone on bench"]}
PROFILES["rb_s6"] = {**_RB, "max_text_chars": 40,  # «wanna try?» — он протягивает мне телефон; длинный текст
    "anchors": ["a man's hand handing a smartphone to a woman, close-up of two hands passing a phone",
                "POV a guy hands you his phone on a rainy evening, city lights"],
    "queries": ["handing phone to someone", "passing phone hands", "giving phone hands close up", "two hands holding phone",
                "couple sharing phone", "couple looking at phone together", "hand giving phone aesthetic",
                "couple phone rain"]}
PROFILES["rb_s7"] = {**_RB,  # вместе с тех пор: пара без лиц — за руки, под зонтом, со спины
    "anchors": ["a young couple holding hands walking in the rain under an umbrella, seen from behind",
                "a cozy couple cuddling, faces not visible, warm light"],
    "queries": ["couple holding hands aesthetic", "couple under umbrella rain", "couple from behind aesthetic",
                "couple walking in the rain", "couple hands aesthetic", "couple no face aesthetic",
                "cozy couple aesthetic", "couple rainy night city"]}

# 1307 «I was a flight attendant for 20 years»: s2–s6 — «из её галереи», самолёт глазами экипажа, без лиц, ярко
_FA = {**_GW, "max_text_chars": 40}
PROFILES["fa_s2"] = {**_FA,  # посчитай ряды до ближайшего выхода
    "anchors": ["the aisle of a passenger airplane cabin with rows of seats and a lit red EXIT sign above the emergency exit",
                "an airplane emergency exit row door seen from the aisle, bright daylight through the windows"],
    "queries": ["airplane exit sign", "emergency exit airplane", "airplane cabin aisle", "airplane seats rows aesthetic",
                "exit row airplane", "airplane interior aesthetic", "airplane aisle view", "empty airplane cabin",
                "airplane window seat view", "plane cabin pov", "flight attendant pov cabin", "airplane boarding pov",
                "inside airplane aesthetic", "airplane seat aisle", "plane interior photo", "cabin crew view cabin"]}
PROFILES["fa_s3"] = {**_FA,  # при эвакуации бросай сумку: ручная кладь в проходе / на полках
    "anchors": ["a carry-on suitcase standing in the aisle of an airplane during boarding",
                "open overhead bins on a plane stuffed with carry-on bags and backpacks"],
    "queries": ["carry on bag airplane", "overhead bin airplane", "carry on luggage aesthetic", "airplane aisle luggage",
                "suitcase airplane cabin", "boarding plane carry on", "plane boarding aisle", "carry on suitcase travel",
                "backpack airplane seat", "luggage overhead compartment", "boarding the plane aesthetic", "airplane bag under seat",
                "travel bag plane aesthetic", "carry on essentials airplane", "people boarding plane aisle", "suitcase on plane"]}
PROFILES["fa_s4"] = {**_FA,  # нормальная обувь на взлёт/посадку: ноги в кроссовках / шлёпки на полу салона
    "anchors": ["POV of feet in sneakers on the floor of an airplane under the seat in front",
                "flip flops on the carpet of an airplane cabin next to a seat"],
    "queries": ["sneakers on plane", "feet on airplane floor", "airplane outfit shoes", "flip flops airplane",
                "airport outfit sneakers", "travel shoes airport", "shoes airplane seat pov", "comfy travel shoes plane",
                "airplane feet pov", "travel outfit airplane", "sandals airplane", "sneakers airport aesthetic",
                "legs on plane pov", "airplane legroom", "travel day shoes", "shoes on airplane floor"]}
PROFILES["fa_s5"] = {**_FA,  # протри столик: столик с перекусом, салфетки
    "anchors": ["an airplane tray table with a snack and a drink, seen from the seat, window light",
                "a hand wiping an airplane tray table with a disinfecting wipe"],
    "queries": ["airplane tray table", "plane food tray table", "airplane snack aesthetic", "disinfecting wipes airplane",
                "in flight meal aesthetic", "airplane coffee tray table", "airplane wipes travel essentials",
                "plane tray table window", "airplane snacks pov", "airplane drink tray", "in flight coffee window",
                "airplane breakfast tray", "plane meal pov", "laptop on airplane tray table", "airplane tray table aesthetic"]}
PROFILES["fa_s6"] = {**_FA,  # слушай инструктаж: карточка безопасности, маска, жилет, крыло в окне
    "anchors": ["an airplane safety instruction card in the seat pocket",
                "an oxygen mask and a life vest on an airplane, safety demonstration, bright cabin"],
    "queries": ["airplane safety card", "safety instructions airplane", "oxygen mask airplane", "life vest airplane",
                "flight attendant aesthetic", "cabin crew aesthetic", "airplane window wing", "flight attendant life",
                "airplane safety demonstration", "flight attendant galley", "emergency card airplane seat pocket",
                "airplane seat pocket", "plane window clouds", "airplane wing sunset", "flight crew aesthetic", "airplane life jacket"]}

PROFILES["fa_s6b"] = {**_FA, "no_faces": False,  # 1307 s6, добор: инструктаж, карточка в руке, жилет, ремень
    "anchors": ["a flight attendant in the aisle demonstrating the life vest and oxygen mask to passengers, seen from a seat",
                "a passenger's hand holding the airplane safety instruction card in front of the seat"],
    "queries": ["flight attendant safety demonstration", "safety demo airplane", "cabin crew life vest demo",
                "flight attendant pointing to exits", "airplane safety card in hand", "reading safety card airplane",
                "flight attendant seatbelt demonstration", "safety briefing airplane", "flight attendant life jacket",
                "oxygen mask demonstration", "cabin crew safety demo", "flight attendant demo aisle",
                "pre flight safety demonstration", "safety instructions card plane", "flight attendant aisle pov",
                "watching safety demo plane"]}

# 1308 «rating foods»: картинки еды без подписей, квадрат; глянец можно (ugc почти не важен), похожие не ищем
_FD = {"no_faces": True, "out": (800, 800), "min_aspect": 0.7, "related_rounds": 0, "related_seeds": 0,
       "weights": {"ref": 0.0, "text": 0.9, "ugc": 0.1}, "min_ref": 0.0, "ref": [], "ugc_floor": 0.15}
_FOODS = {
    "pizza_bad": ("a slice of pepperoni pizza being pulled away with long stretchy melted cheese",
                  ["pepperoni pizza cheese pull", "pepperoni pizza", "pepperoni pizza slice", "cheesy pepperoni pizza",
                   "pizza cheese pull", "homemade pepperoni pizza", "pepperoni pizza aesthetic", "pizza night pepperoni"]),
    "pizza_good": ("a classic margherita pizza with tomato sauce, mozzarella and fresh basil leaves",
                   ["margherita pizza", "pizza margherita basil", "neapolitan margherita pizza", "homemade margherita pizza",
                    "margherita pizza aesthetic", "wood fired margherita", "classic italian pizza", "margherita pizza slice"]),
    "pizza_amazing": ("a hawaiian pizza with pineapple chunks and ham on melted cheese",
                      ["pineapple pizza", "hawaiian pizza", "pizza with pineapple", "hawaiian pizza slice",
                       "ham and pineapple pizza", "pineapple pizza aesthetic", "homemade hawaiian pizza", "pizza ananas"]),
    "pasta_bad": ("spaghetti carbonara in a bowl with a raw egg yolk on top and grated cheese",
                  ["carbonara egg yolk", "spaghetti carbonara", "carbonara pasta yolk", "carbonara aesthetic",
                   "pasta carbonara bowl", "creamy carbonara", "carbonara with yolk on top", "authentic carbonara"]),
    "pasta_good": ("a plate of spaghetti bolognese with meat sauce and parmesan",
                   ["spaghetti bolognese", "bolognese pasta", "pasta bolognese plate", "spaghetti meat sauce",
                    "bolognese aesthetic", "homemade bolognese", "spaghetti bolognese bowl", "ragu pasta"]),
    "pasta_amazing": ("a kids' plate of plain spaghetti with ketchup and sliced boiled hot dog sausages, school cafeteria",
                      ["spaghetti with ketchup", "pasta with ketchup and sausage", "hot dog spaghetti", "kids spaghetti hot dogs",
                       "spaghetti and sausages", "pasta with hot dogs", "school lunch spaghetti", "ketchup pasta"]),
    "brk_bad": ("a bowl of chicken caesar salad with croutons and parmesan",
                ["chicken caesar salad", "caesar salad", "caesar salad bowl", "grilled chicken caesar",
                 "caesar salad aesthetic", "homemade caesar salad", "caesar salad croutons", "chicken caesar bowl"]),
    "brk_good": ("a breakfast plate of fried sunny side up eggs with crispy bacon",
                 ["eggs and bacon", "fried eggs bacon breakfast", "bacon and eggs plate", "sunny side up eggs bacon",
                  "english breakfast eggs bacon", "breakfast eggs bacon aesthetic", "bacon eggs pan", "eggs bacon toast"]),
    "brk_amazing": ("a bowl of breakfast cereal flakes in water, or cucumber slices with jam on them",
                    ["cereal with water", "cereal in water", "cucumber with jam", "cucumber and jam",
                     "bowl of cereal", "cereal bowl aesthetic", "cornflakes bowl", "weird food combinations"]),
}
for _k, (_a, _q) in _FOODS.items():
    PROFILES[f"fd_{_k}"] = {**_FD, "anchors": [_a], "queries": _q}

# 1309: аватарки «живых» комментаторов (как у реальных людей в X/Twitter), без узнаваемых лиц
PROFILES["pfp_1309"] = {"no_faces": True, "out": (400, 400), "min_aspect": 0.7, "related_rounds": 0, "related_seeds": 0,
    "weights": {"ref": 0.0, "text": 0.5, "ugc": 0.5}, "min_ref": 0.0, "ref": [], "ugc_floor": 0.3, "max_text_chars": 6,
    "anchors": ["a casual profile picture of a young guy: mirror selfie with the phone covering his face",
                "an everyday social media profile photo: car at night, sunset, dog, sneakers or gym, no face"],
    "queries": ["faceless pfp", "pfp no face boy", "mirror selfie pfp phone covering face", "car pfp", "car pfp night",
                "gym pfp", "sunset pfp", "dog pfp", "basketball pfp", "sneakers pfp", "streetwear pfp boy",
                "night drive pfp", "cat pfp", "gaming setup pfp", "jdm pfp", "fishing pfp", "hoodie pfp no face",
                "skate pfp", "concert pfp", "beach pfp aesthetic", "pfp aesthetic boy", "pfp aesthetic girl no face",
                "football pfp", "motorcycle pfp"]}

# 1319 Inspoy «Hot Girl Halloween Costumes»: 9:16; s2–s4 — костюм из вещей, разложенных на кровати (как в рефе @amarastyled)
_HW_REF = ROOT / "downloads" / "1319" / "ref"
_HW = {"no_faces": True, "out": (1080, 1920), "min_aspect": 1.3, "related_rounds": 1, "related_seeds": 8,
       "weights": {"ref": 0.4, "text": 0.4, "ugc": 0.2}, "min_ref": 0.0, "max_text_chars": 40,
       "ref": [_HW_REF / f"slide{i}.jpg" for i in range(2, 7)]}
PROFILES["hw_s1"] = {**_HW, "no_faces": False, "ref": [_HW_REF / "slide1.jpg"],  # обложка: красивая девушка, хэллоуин-вайб
    "anchors": ["a beautiful young woman in a halloween costume, moody flash photo, aesthetic",
                "a pretty girl with a lace veil and glossy lips, dark flash selfie, halloween"],
    "queries": ["halloween costume aesthetic girl", "hot girl halloween costume", "halloween makeup aesthetic",
                "halloween costume selfie", "flash photo halloween girl", "lace veil aesthetic", "halloween pfp aesthetic",
                "cat ears costume aesthetic", "angel costume aesthetic", "witch costume aesthetic girl",
                "halloween party outfit girl", "dark feminine halloween", "halloween night flash photo", "costume party selfie"]}
PROFILES["hw_s2"] = {**_HW,  # Mean Girl Cat: чёрный костюм + кошачьи ушки, разложено на кровати
    "anchors": ["a black cat halloween costume laid out flat on a white bed: black top, black mini skirt, cat ears headband, boots, accessories",
                "flat lay of an all-black outfit with cat ears on rumpled white sheets, top view"],
    "queries": ["cat costume flat lay", "cat ears outfit flat lay", "black cat costume outfit", "mean girls cat costume",
                "halloween costume flat lay", "halloween outfit laid out on bed", "black outfit flat lay bed",
                "cat halloween costume aesthetic", "outfit laid out on bed", "halloween costume ideas flat lay",
                "all black outfit flat lay", "cat costume diy outfit"]}
PROFILES["hw_s3"] = {**_HW,  # Witch, Please: зелёные оттенки, ведьма, разложено на кровати
    "anchors": ["a green witch halloween costume laid out flat on a white bed: green dress, black witch hat, boots, jewelry",
                "flat lay of an emerald green witchy outfit on rumpled white sheets, top view"],
    "queries": ["witch costume flat lay", "green witch costume", "witch outfit laid out on bed", "witchy outfit flat lay",
                "green dress flat lay", "witch halloween costume aesthetic", "emerald green outfit flat lay",
                "halloween costume flat lay", "witch hat outfit", "green witch aesthetic outfit", "elphaba costume",
                "outfit laid out on bed"]}
PROFILES["hw_s4"] = {**_HW,  # Fallen Angel: ангельская тема (крылья, нимб), разложено на кровати
    "anchors": ["an angel halloween costume laid out flat on a white bed: white corset top, white skirt, feathered wings, halo, heels",
                "flat lay of a fallen angel costume with feathered wings and a halo on rumpled sheets, top view"],
    "queries": ["angel costume flat lay", "angel halloween costume", "fallen angel costume", "angel wings outfit",
                "angel costume outfit laid out", "white outfit flat lay bed", "halo costume aesthetic", "angel costume aesthetic",
                "halloween costume flat lay", "corset outfit flat lay", "feather wings costume", "outfit laid out on bed"]}
# добор s2–s4: первые пулы — обычные наряды; костюмные флэтлеи на пинтересте глянцевее → ugc почти не важен
_HWB = {**_HW, "weights": {"ref": 0.5, "text": 0.45, "ugc": 0.05}, "ugc_floor": 0.2}
_HW_COMMON = ["halloween costume flat lay", "halloween costume laid out on bed", "halloween costume ideas laid out",
              "halloween costume inspo flat lay", "costume flat lay bed", "halloween costume layout",
              "diy halloween costume closet", "halloween costume ideas women outfit"]
PROFILES["hw_s2b"] = {**_HWB, "anchors": PROFILES["hw_s2"]["anchors"],
    "queries": ["cat costume flat lay", "black cat costume laid out", "cat woman costume flat lay", "cat ears costume outfit",
                "mean girls cat costume outfit", "black cat halloween costume diy", "cat costume ideas women",
                "catwoman diy costume"] + _HW_COMMON}
PROFILES["hw_s3b"] = {**_HWB, "anchors": PROFILES["hw_s3"]["anchors"],
    "queries": ["witch costume flat lay", "green witch costume diy", "witch costume laid out", "wicked elphaba costume diy",
                "witch costume ideas women", "green witch outfit", "witch hat outfit flat lay", "witchy halloween costume diy"]
               + _HW_COMMON}
PROFILES["hw_s4b"] = {**_HWB, "anchors": PROFILES["hw_s4"]["anchors"],
    "queries": ["angel costume flat lay", "angel costume laid out", "angel costume diy women", "fallen angel costume diy",
                "angel wings halo costume", "angel halloween costume ideas", "corset angel costume", "dark angel costume diy"]
               + _HW_COMMON}
PROFILES["hw_s5"] = {**_HW, "no_faces": False, "ref": [],  # девушка в одном из костюмов: селфи в зеркало
    "weights": {"ref": 0.0, "text": 0.7, "ugc": 0.3},
    "anchors": ["a young woman taking a mirror selfie in a black cat halloween costume with cat ears",
                "a girl taking a mirror selfie in an angel or witch halloween costume at home"],
    "queries": ["halloween costume mirror selfie", "cat costume mirror selfie", "angel costume mirror selfie",
                "witch costume mirror selfie", "halloween costume selfie aesthetic", "cat ears costume selfie",
                "halloween outfit mirror pic", "costume mirror selfie", "halloween costume aesthetic girl",
                "fallen angel costume selfie", "mean girls cat costume selfie", "halloween fit check"]}

# 1329 Inspoy «стилист: 5 хэллоуин-образов»: 3:4; s1 — девушка-стилист в студии (вешалка с костюмами, зеркало,
# доска с образами, тыква), образы — девушка в костюме (живое фото с телефона), лица потом заменяем в Flow
_ST = {"no_faces": False, "out": (1080, 1440), "min_aspect": 1.15, "related_rounds": 1, "related_seeds": 8,
       "weights": {"ref": 0.0, "text": 0.7, "ugc": 0.3}, "min_ref": 0.0, "ref": [], "max_text_chars": 40}
PROFILES["st_s1"] = {**_ST,
    "anchors": ["a young female stylist in her styling studio with a clothing rack of costumes, a mirror and a mood board "
                "of outfits on the wall, a pumpkin nearby, cozy halloween season",
                "a fashion stylist woman standing next to a garment rack in a bright studio, halloween decor"],
    "queries": ["stylist studio aesthetic", "fashion stylist at work", "stylist with clothing rack", "wardrobe stylist aesthetic",
                "styling studio clothing rack", "fashion stylist girl aesthetic", "garment rack studio aesthetic",
                "stylist mood board wall", "halloween costume rack", "stylist halloween", "fitting room stylist aesthetic",
                "personal stylist aesthetic photo"]}
PROFILES["st_witch"] = {**_ST,  # «ведьма дорого»: чёрное сатиновое платье, острая шляпа, тёмный макияж
    "anchors": ["a young woman in an elegant black satin slip dress and a pointed witch hat with dark makeup, "
                "expensive minimalist witch halloween costume, mirror selfie",
                "a chic witch costume: black satin dress, black pointed hat, dark lips"],
    "queries": ["elegant witch costume", "witch costume black dress", "classy witch halloween costume", "witch hat black dress",
                "chic witch costume aesthetic", "satin dress witch costume", "witch costume mirror selfie",
                "easy witch costume", "witch costume aesthetic girl", "dark feminine witch outfit", "witch makeup aesthetic",
                "black satin slip dress outfit"]}
PROFILES["st_vamp"] = {**_ST,  # «вампир»: бордовое бархатное платье, тёмная помада, бледная пудра
    "anchors": ["a young woman in a burgundy velvet dress with dark red lipstick and pale skin, elegant vampire halloween "
                "costume, mirror selfie",
                "a chic vampire costume: deep red velvet dress, dark lips, pale makeup"],
    "queries": ["vampire costume aesthetic", "velvet dress vampire costume", "burgundy velvet dress outfit", "classy vampire costume",
                "vampire halloween costume girl", "vampire makeup aesthetic", "red velvet dress aesthetic",
                "dark red lipstick aesthetic", "vampire costume mirror selfie", "elegant vampire outfit", "gothic velvet dress",
                "easy vampire costume"]}
PROFILES["st_angel"] = {**_ST,  # «ангел»: белое платье или белый костюм, крылья, светлый макияж
    "anchors": ["a young woman in an all-white dress with feathered angel wings and soft light makeup, angel halloween "
                "costume, mirror selfie",
                "an all white angel costume: white dress or white suit, white feather wings"],
    "queries": ["angel costume aesthetic", "all white angel costume", "angel wings costume girl", "white dress angel costume",
                "angel halloween costume", "angel costume mirror selfie", "white suit angel costume", "angel makeup aesthetic",
                "classy angel costume", "feather wings outfit", "angel costume ideas", "white outfit angel wings"]}

# 1337 «style test A/B» (реф @moodonmute101): квадратные фото вариантов ответа, без лиц
_Q = {"no_faces": True, "out": (1080, 1080), "min_aspect": 0.75, "related_rounds": 1, "related_seeds": 8, "ugc_floor": 0.15,
      "weights": {"ref": 0.0, "text": 0.9, "ugc": 0.1}, "min_ref": 0.0, "ref": [], "max_text_chars": 30}
for _k, _anch, _q in [
    ("q_outfit_a", "an oversized cozy outfit: chunky oversized knit sweater and baggy trousers, aesthetic mirror selfie, face hidden",
     ["oversized cozy outfit", "oversized sweater outfit aesthetic", "baggy cozy outfit", "oversized hoodie outfit aesthetic",
      "comfy outfit mirror selfie", "oversized knit outfit", "cozy outfit aesthetic", "slouchy outfit aesthetic"]),
    ("q_outfit_b", "a tailored sharp outfit: structured blazer and straight tailored trousers, aesthetic photo, face hidden",
     ["tailored blazer outfit", "tailored outfit women aesthetic", "blazer and trousers outfit", "sharp tailored look",
      "structured blazer outfit aesthetic", "suit outfit women aesthetic", "tailored trousers outfit", "power suit aesthetic"]),
    ("q_color_a", "an outfit in soft neutral colours: beige, cream, oatmeal, aesthetic",
     ["neutral outfit aesthetic", "beige outfit aesthetic", "cream outfit aesthetic", "soft neutral outfit", "all beige outfit",
      "oatmeal outfit", "neutral tones outfit flat lay", "beige knit outfit"]),
    ("q_color_b", "an outfit with one bold colour: a bright red or cobalt blue piece, aesthetic",
     ["one bold color outfit", "red outfit aesthetic", "cobalt blue outfit", "bold color outfit aesthetic", "pop of color outfit",
      "red coat outfit aesthetic", "bright color outfit", "colorful statement outfit"]),
    ("q_jewel_a", "a stack of gold jewelry: many gold rings and bracelets on hands, layered gold necklaces, close-up",
     ["gold jewelry stack", "stacked gold rings", "gold bracelet stack", "layered gold necklaces", "gold rings aesthetic hands",
      "chunky gold jewelry aesthetic", "gold jewelry close up", "maximal gold jewelry"]),
    ("q_jewel_b", "one tiny dainty piece of jewelry: a delicate thin gold necklace or a single tiny earring, close-up",
     ["dainty necklace minimal", "tiny gold necklace", "minimal jewelry aesthetic", "delicate gold chain necklace",
      "single tiny earring", "dainty jewelry close up", "minimalist necklace", "tiny pendant necklace"]),
    ("q_shoes_a", "sneakers on feet, aesthetic outfit photo from above",
     ["sneakers aesthetic", "white sneakers outfit", "sneakers pov", "new balance aesthetic", "sneakers outfit aesthetic",
      "chunky sneakers aesthetic", "sneakers on feet", "everyday sneakers outfit"]),
    ("q_shoes_b", "elegant heels on feet, aesthetic outfit photo",
     ["heels aesthetic", "pointed heels aesthetic", "heels pov", "stiletto heels aesthetic", "kitten heels outfit",
      "white heels aesthetic", "black heels outfit", "slingback heels aesthetic"]),
]:
    PROFILES[_k] = {**_Q, "anchors": [_anch], "queries": _q}

# 1337, второй заход «эстетичнее»: рефы стиля = фото со слайдов рефа (downloads/1337/ref/photos — крупные планы,
# мягкий тёплый свет, Pinterest-эстетика), UGC не учитываем, запросы — aesthetic / inspo / clean girl / old money
_QV = {**_Q, "ugc_floor": 0.0, "weights": {"ref": 0.35, "text": 0.65, "ugc": 0.0},
       "ref": sorted((ROOT / "downloads" / "1337" / "ref" / "photos").glob("*.jpg"))}
_QV_STYLE = ", Pinterest aesthetic photo, soft warm natural light, close-up detail shot, clean muted tones, editorial"
for _k, _anch, _q in [
    ("qv_outfit_a", "an oversized cozy outfit, chunky knit sweater sleeves and baggy trousers",
     ["oversized sweater aesthetic pinterest", "cozy knit sweater aesthetic", "chunky knit sweater sleeves aesthetic",
      "oversized knit outfit inspo", "cozy outfit details aesthetic", "baggy jeans oversized sweater aesthetic",
      "cozy girl aesthetic outfit", "knitwear aesthetic close up", "scandi cozy outfit", "oversized cardigan aesthetic"]),
    ("qv_outfit_b", "a tailored sharp outfit, structured blazer and pressed tailored trousers",
     ["old money outfit aesthetic", "tailored blazer aesthetic pinterest", "blazer outfit details aesthetic",
      "tailored trousers aesthetic", "quiet luxury outfit aesthetic", "minimal blazer outfit inspo", "office siren outfit",
      "structured blazer close up", "chic tailored outfit pinterest", "scandi style blazer outfit"]),
    ("qv_color_a", "an outfit in soft neutral colours: beige, cream, oatmeal knit and trousers",
     ["neutral outfit aesthetic pinterest", "cream outfit aesthetic", "beige aesthetic outfit details", "oatmeal knit aesthetic",
      "clean girl neutral outfit", "vanilla girl outfit", "soft neutrals aesthetic", "neutral tones outfit inspo",
      "beige knit sweater aesthetic", "cream tones aesthetic"]),
    ("qv_color_b", "an outfit with one bold colour: one bright red or cobalt blue piece with neutral basics",
     ["cherry red outfit aesthetic", "red sweater aesthetic pinterest", "cobalt blue outfit aesthetic", "red coat aesthetic",
      "pop of red outfit inspo", "burgundy outfit aesthetic", "red bag outfit aesthetic", "blue sweater aesthetic pinterest",
      "red knit aesthetic", "colour pop outfit pinterest"]),
    ("qv_jewel_a", "a stack of gold jewelry: many gold rings, bracelets and layered necklaces on hands",
     ["gold jewelry stack aesthetic", "chunky gold rings aesthetic", "gold bracelet stack pinterest", "layered gold necklaces aesthetic",
      "gold jewelry aesthetic hands", "maximalist gold jewelry", "stacked rings aesthetic", "gold jewellery inspo"]),
    ("qv_jewel_b", "one tiny dainty piece of jewelry: a delicate thin gold necklace on the collarbone",
     ["dainty necklace aesthetic", "minimal gold necklace aesthetic", "tiny pendant necklace pinterest", "dainty jewelry aesthetic",
      "delicate gold chain collarbone", "minimalist jewelry aesthetic", "clean girl jewelry", "small gold hoops aesthetic"]),
    ("qv_shoes_a", "white sneakers on feet with soft socks and sweatpants",
     ["sneakers aesthetic pinterest", "white sneakers aesthetic", "new balance aesthetic pinterest", "sneakers and socks aesthetic",
      "clean girl sneakers", "sneakers outfit details aesthetic", "white trainers aesthetic", "asics aesthetic"]),
    ("qv_shoes_b", "elegant pointed heels on feet, slim legs",
     ["heels aesthetic pinterest", "white heels aesthetic", "pointed heels aesthetic", "slingback heels aesthetic",
      "kitten heels aesthetic", "stiletto heels aesthetic legs", "black heels aesthetic pinterest", "old money heels"]),
]:
    PROFILES[_k] = {**_QV, "anchors": [_anch + _QV_STYLE], "queries": _q}

# 1340 Inspoy «5 outfits that make you look 10 years younger»: 3:4; s1 — яркое селфи красивой девушки 30+ (лицо потом
# новое во Flow), s2–s4 — образ разложен на кровати (как 1319), s5 — девушка в образе, селфи в зеркало (лицо за телефоном)
_OY = {"no_faces": True, "out": (1080, 1440), "min_aspect": 1.15, "related_rounds": 1, "related_seeds": 8,
       "weights": {"ref": 0.0, "text": 0.7, "ugc": 0.3}, "min_ref": 0.0, "ref": [], "max_text_chars": 40, "ugc_floor": 0.2}
_OY_BED = ["outfit laid out on bed", "outfit flat lay bed", "outfit laid out on bed aesthetic", "outfit flat lay on white sheets",
           "fall outfit laid out on bed", "outfit planning flat lay"]
PROFILES["oy_s1"] = {**_OY, "no_faces": False,
    "anchors": ["a bright sunny selfie of a beautiful stylish woman around 30, glowing skin, smiling, natural daylight, phone photo",
                "a pretty woman taking a bright selfie outdoors in the sun, chic outfit, aesthetic but casual"],
    "queries": ["bright selfie aesthetic woman", "sunny selfie aesthetic", "selfie golden hour woman", "chic woman selfie",
                "pretty selfie natural light", "selfie outdoors sunny aesthetic", "30s woman style selfie", "glowy selfie aesthetic",
                "car selfie sunny aesthetic", "selfie city sunny"]}
PROFILES["oy_s2"] = {**_OY,  # 1. Enters the room
    "anchors": ["an outfit laid out flat on a bed: red coat or red blazer, black turtleneck, straight black trousers, black ankle boots, gold earrings, top view"],
    "queries": ["red coat outfit flat lay", "red blazer outfit flat lay", "red coat black turtleneck outfit", "red blazer black outfit",
                "black turtleneck outfit flat lay", "red coat outfit"] + _OY_BED}
PROFILES["oy_s3"] = {**_OY,  # 2. Plot twist
    "anchors": ["an outfit laid out flat on a bed: black leather jacket, lace top, blue jeans, tall knee-high boots, chunky chain necklace, top view"],
    "queries": ["leather jacket outfit flat lay", "lace top leather jacket outfit", "leather jacket jeans boots flat lay",
                "knee high boots outfit flat lay", "chunky chain necklace outfit", "leather jacket outfit laid out"] + _OY_BED}
PROFILES["oy_s4"] = {**_OY,  # 3. Walks in slow motion
    "anchors": ["an outfit laid out flat on a bed: long burgundy or emerald satin dress, black trench coat, pointed black ankle boots, top view"],
    "queries": ["burgundy dress outfit flat lay", "emerald dress outfit flat lay", "long satin dress flat lay", "trench coat dress outfit",
                "slip dress trench coat outfit", "burgundy maxi dress outfit", "emerald green dress outfit"] + _OY_BED}
PROFILES["oy_s5"] = {**_OY, "weights": {"ref": 0.0, "text": 0.5, "ugc": 0.5},
    "anchors": ["a chic woman taking a full-length mirror selfie in a stylish fall outfit at home, phone covering her face, bright daylight"],
    "queries": ["outfit mirror selfie chic", "fall outfit mirror selfie", "elegant outfit mirror selfie", "mirror selfie trench coat outfit",
                "mirror selfie blazer outfit", "classy outfit mirror selfie", "30s woman outfit mirror selfie", "chic fall fit check"]}

# 1341 Inspoy «5 outfits I wore for my husband»: 3:4; s1 — яркое фото девушки с мужем (одежда синий/зелёный/красный),
# s2–s5 — она в образе в полный рост (фото «мужем» / селфи в зеркало), s6 — она в образе 5 + муж с кольцом/цветами;
# лица потом заменяем во Flow (одна пара на всю карусель)
_HB = {"no_faces": False, "out": (1080, 1440), "min_aspect": 1.15, "related_rounds": 1, "related_seeds": 8,
       "weights": {"ref": 0.0, "text": 0.6, "ugc": 0.4}, "min_ref": 0.0, "ref": [], "max_text_chars": 40, "ugc_floor": 0.25}
PROFILES["hb_s1"] = {**_HB,
    "anchors": ["a bright happy phone photo of a young married couple, wife and husband in colourful outfits (cobalt blue, emerald green, red), sunny day",
                "a stylish couple selfie in bright colours outdoors, candid, phone photo"],
    "queries": ["couple photo bright colors", "colorful couple outfits", "couple selfie sunny", "husband and wife photo aesthetic",
                "couple outfits red", "couple in blue outfits", "couple green outfit", "married couple selfie", "couple photo city summer",
                "couple pictures colorful", "couple vacation photo bright", "couple matching colors"]}
PROFILES["hb_look"] = {**_HB,
    "anchors": ["a full-length photo of a stylish woman in a chic outfit, taken by her boyfriend on the street or at home, phone photo",
                "a woman's full-body outfit mirror selfie at home, chic outfit, face visible"],
    "queries": ["outfit photo full body street", "full length outfit photo woman", "ootd full body street", "boyfriend took my outfit picture",
                "outfit pics city full body", "chic outfit full length photo", "street style woman full body photo", "outfit of the day photo street",
                "fall outfit full body photo", "date night outfit full body", "coat and boots outfit street photo", "midi dress outfit street"]}
PROFILES["hb_s6"] = {**_HB,
    "anchors": ["a beautiful woman in an elegant outfit in the foreground, her husband in the background holding a bouquet of flowers or a ring box, romantic surprise, phone photo",
                "a man on one knee with a ring proposing to a stylish woman on the street, candid phone photo"],
    "queries": ["husband surprise flowers wife", "boyfriend holding flowers behind her", "man with bouquet surprise girlfriend", "proposal photo street candid",
                "man on one knee proposal candid", "surprise proposal photo", "vow renewal proposal photo", "husband proposed again",
                "boyfriend waiting with flowers", "proposal ring box photo", "romantic surprise flowers street", "proposal at restaurant photo"]}

# 1338 (копия рефа @moodonmute101): обложка — ч/б фото девушки в полный рост на светлом фоне, лица не видно
PROFILES["q38_cover"] = {**_QV, "out": (1080, 1440), "min_aspect": 1.2,
    "ref": [ROOT / "downloads" / "1337" / "ref" / "slide1.jpg"],
    "weights": {"ref": 0.5, "text": 0.5, "ugc": 0.0},
    "anchors": ["black and white full-length fashion photo of a slim young woman in grey sweatpants and a fitted top "
                "on a plain white studio background, arms over her head hiding her face, minimal editorial"],
    "queries": ["black and white fashion photo woman", "minimal fashion photography white background", "sweatpants outfit studio photo",
                "faceless fashion photography", "black and white editorial pose", "white background full body fashion",
                "grey sweatpants outfit aesthetic", "monochrome fashion photoshoot", "studio fashion pose minimal",
                "loungewear photoshoot white"]}
# фидбек клиента: обложка цветная и «как с телефона», не фотосессия → селфи в зеркало / фото подруги, лицо скрыто
PROFILES["q38_cover_ugc"] = {**_QV, "out": (1080, 1440), "min_aspect": 1.2, "ref": [],
    "weights": {"ref": 0.0, "text": 0.5, "ugc": 0.5}, "ugc_floor": 0.3,
    "anchors": ["a casual iPhone mirror selfie of a young woman showing her everyday outfit, phone covering her face, "
                "bedroom or hallway mirror, natural light, amateur phone photo, not a photoshoot",
                "a candid phone photo of a girl's outfit taken by a friend, face turned away or cropped, everyday street"],
    "queries": ["outfit mirror selfie", "fit check mirror selfie", "ootd mirror selfie", "mirror selfie outfit aesthetic",
                "cozy outfit mirror selfie", "mirror pic outfit phone covering face", "outfit inspo mirror pic",
                "elevator mirror selfie outfit", "bedroom mirror selfie outfit", "casual outfit mirror selfie",
                "fall outfit mirror selfie", "outfit of the day mirror"]}

# 1320 Inspoy «fall outfits»: 9:16; s1 — девушка с парнем (лица видны), s2–s4 — осенний образ в полный рост,
# селфи в зеркало (лицо за телефоном)
_FO = {"no_faces": False, "out": (1080, 1920), "min_aspect": 1.3, "related_rounds": 1, "related_seeds": 8,
       "weights": {"ref": 0.0, "text": 0.7, "ugc": 0.3}, "min_ref": 0.0, "ref": [], "max_text_chars": 40}
PROFILES["fo_s1"] = {**_FO,  # девушка с парнем, осень
    "anchors": ["a young couple taking a cute photo together in autumn, girlfriend and boyfriend smiling, casual phone photo",
                "a boyfriend hugging his girlfriend from behind outdoors in fall, fallen leaves, candid"],
    "queries": ["couple fall photos", "couple autumn aesthetic", "boyfriend girlfriend fall pictures", "couple selfie autumn",
                "cute couple pictures fall", "couple pumpkin patch photo", "couple photo ideas fall", "couple mirror selfie fall",
                "boyfriend pics aesthetic", "couple candid photo autumn", "couple date fall outfit", "couple hug autumn leaves"]}
PROFILES["fo_s2"] = {**_FO,  # Cozy Sweater Weather
    "anchors": ["a young woman taking a full-length mirror selfie in a cozy chunky knit sweater outfit for fall, phone covering her face",
                "fall outfit mirror selfie: oversized knit sweater, jeans or skirt, boots, bedroom mirror"],
    "queries": ["cozy sweater outfit mirror selfie", "fall sweater outfit", "chunky knit sweater outfit", "sweater weather outfit",
                "fall outfit mirror pic", "cozy fall outfit aesthetic", "oversized sweater outfit fall", "knit sweater skirt outfit",
                "fall fit check mirror", "fall outfit inspo women", "cozy outfit ideas autumn", "sweater and boots outfit"]}
PROFILES["fo_s3"] = {**_FO,  # Date Night in Boots
    "anchors": ["a young woman taking a full-length mirror selfie in a fall date night outfit with knee-high boots, phone covering her face",
                "fall date night outfit mirror selfie: mini dress or skirt with tall boots and a jacket"],
    "queries": ["date night outfit boots", "knee high boots outfit fall", "fall date night outfit", "tall boots outfit mirror selfie",
                "date night outfit mirror pic", "boots outfit aesthetic fall", "fall going out outfit", "knee high boots skirt outfit",
                "fall dinner outfit", "date outfit autumn", "fall fit check boots", "leather boots outfit women"]}
PROFILES["fo_s4"] = {**_FO,  # Fall Trench Era
    "anchors": ["a young woman taking a full-length mirror selfie in a beige trench coat fall outfit, phone covering her face",
                "trench coat outfit mirror selfie for autumn, classic beige trench with jeans and loafers"],
    "queries": ["trench coat outfit", "trench coat outfit mirror selfie", "fall trench coat outfit", "beige trench coat outfit",
                "trench coat aesthetic", "trench coat fit check", "autumn trench outfit women", "trench coat and boots outfit",
                "classic trench outfit", "trench coat street style fall", "trench coat jeans outfit", "fall outfit trench coat"]}

# 1322 квиз «цветотип»: свои картинки вместо вырезок из рефа — другие фото тех же звёзд, волосы, глаза, запястья
# 1385: «prime» советы (реф @tips.with.alex), живые фото с телефона; A — девушки ~20, B — женщины 35–50
_PR = {"no_faces": False, "out": (1080, 1440), "min_aspect": 1.15, "related_rounds": 1, "related_seeds": 8,
       "weights": {"ref": 0.0, "text": 0.55, "ugc": 0.45}, "min_ref": 0.0, "ref": [], "max_text_chars": 30, "ugc_floor": 0.3}
PROFILES["pa_s1"] = {**_PR,  # обложка: яркое фото девушки ~20 в цветной одежде (не серой)
    "anchors": ["a bright candid phone selfie of a smiling young woman in her early twenties wearing a colorful outfit",
                "a vibrant mirror selfie of a stylish 20 year old girl in a red or pink outfit, sunny day",
                "a young woman in a bright colorful top laughing outside, iphone photo"],
    "queries": ["colorful outfit selfie", "bright outfit mirror selfie", "red outfit selfie girl", "pink outfit aesthetic girl",
                "colorful street style girl", "golden hour selfie girl", "it girl aesthetic photo", "fall outfit selfie colorful",
                "girl in red sweater selfie", "burgundy outfit mirror selfie", "colorful fit check", "happy girl selfie aesthetic"]}
PROFILES["pa_s2"] = {**_PR,  # sleep like it's your job: девушка спит / уютная кровать, вечер
    "anchors": ["a young woman sleeping peacefully in a cozy bed with white sheets, phone photo",
                "a girl asleep in bed at night wearing a silk sleep mask, soft lamp light"],
    "queries": ["sleeping girl aesthetic", "girl asleep in bed", "cozy bed sleeping aesthetic", "sleep mask aesthetic girl",
                "bedtime routine aesthetic", "girl sleeping white sheets", "night routine in bed", "early night aesthetic"]}
PROFILES["pa_s3"] = {**_PR,  # stop saving, start doing: девушка делает то, что сохраняла (готовит, лепит, рисует)
    "anchors": ["a young woman baking at home, candid phone photo", "a girl at a pottery class making a bowl",
                "a young woman painting on a canvas at home", "a girl cooking a new recipe in her kitchen"],
    "queries": ["girl baking aesthetic", "pottery class aesthetic girl", "painting hobby aesthetic girl", "cooking aesthetic girl",
                "girl trying new recipe", "new hobby aesthetic", "girl journaling aesthetic", "girl doing pilates aesthetic"]}
PROFILES["pa_s4"] = {**_PR,  # decide who you are before you walk out: уверенный образ, зеркало перед выходом
    "anchors": ["a confident young woman mirror selfie in a stylish outfit before going out",
                "a stylish girl walking out the front door in a put-together outfit, phone photo"],
    "queries": ["outfit mirror selfie", "ootd mirror selfie girl", "going out outfit mirror", "fit check mirror girl",
                "outfit of the day aesthetic girl", "stylish girl leaving apartment", "chic outfit mirror selfie", "fall fit check"]}
PROFILES["pb_s1"] = {**_PR,  # обложка B: яркое фото элегантной женщины 35–50 в цветной одежде
    "anchors": ["an elegant woman in her forties smiling in a bright colorful outfit, candid phone photo",
                "a stylish woman over 40 in a red coat on a sunny street"],
    "queries": ["stylish woman over 40", "women over 40 fashion", "chic woman 40s street style", "colorful outfit woman over 40",
                "woman over 50 style", "elegant woman red coat", "french woman style over 40", "mature woman colorful style",
                "woman 40s outfit inspo", "confident woman over 40 smiling"]}
PROFILES["pb_s2"] = {**_PR,  # stand like you belong there: уверенная осанка, идёт по городу / входит в зал
    "anchors": ["a confident woman in her forties walking with great posture in the city",
                "an elegant woman walking into a room with her shoulders back and chin level"],
    "queries": ["confident woman walking city", "elegant woman walking street", "woman walking street style 40s",
                "power walk woman", "woman good posture", "chic woman walking", "businesswoman walking", "woman walking in coat"]}
PROFILES["pb_s3"] = {**_PR, "no_faces": True,  # stop buying random pieces: капсульный гардероб, мало вещей, всё сочетается
    "anchors": ["a capsule wardrobe of a few neutral pieces on a clothing rack", "a woman's closet with a few curated outfits"],
    "queries": ["capsule wardrobe rack", "capsule wardrobe closet", "minimalist wardrobe aesthetic", "clothing rack neutral",
                "capsule wardrobe aesthetic", "minimal closet aesthetic", "neutral wardrobe rack", "curated closet"]}
PROFILES["pb_s4"] = {**_PR, "no_faces": True,  # plan your week on sunday: образы на неделю на кровати + обувь и сумки
    "anchors": ["several outfits for the week laid out on a bed with shoes and bags", "outfit planning on a bed, clothes shoes and bag"],
    "queries": ["outfits laid out on bed", "weekly outfit planning", "outfit flat lay on bed", "outfits for the week",
                "outfit planning bed", "outfit laid out with shoes and bag", "week of outfits", "planning outfits aesthetic"]}
# 1385 B, добор: другие запросы (первые дали повторы)
PROFILES["pb_s1x"] = {**PROFILES["pb_s1"], "queries": [
    "mom outfit colorful", "40 year old woman outfit", "stylish mom street style", "woman in her 40s red dress",
    "colorful blazer woman outfit", "pink coat outfit woman", "bright knit sweater outfit woman", "parisian chic woman 45",
    "milan street style woman colorful", "older woman fashion inspo", "chic over 40 outfit", "fashionable mom selfie",
    "woman 50 fashion colorful", "silver hair woman street style", "classy woman colorful coat", "yellow dress woman street"]}
PROFILES["pb_s2x"] = {**PROFILES["pb_s2"], "queries": [
    "woman walking confidently", "chic woman walking paris", "woman entering restaurant", "elegant woman street walking blazer",
    "woman walking trench coat city", "confident woman street style 35", "woman walking office building",
    "woman walking in heels city", "mom walking street style", "woman walking milan"]}
PROFILES["pb_s3x"] = {**PROFILES["pb_s3"], "queries": [
    "neat closet aesthetic", "organized wardrobe aesthetic", "capsule closet hangers", "wardrobe minimal aesthetic",
    "closet organization aesthetic", "clothes rail aesthetic", "walk in closet neutral", "capsule wardrobe 2024"]}
# 1383: осенние коллажи образов на белом (как доски @aiyah.777 из 1345): вещи без модели, без надписей
PROFILES["ob_fall"] = {"no_faces": True, "out": (900, 1200), "min_aspect": 1.0, "related_rounds": 1, "related_seeds": 8,
    "weights": {"ref": 0.35, "text": 0.65, "ugc": 0.0}, "min_ref": 0.0, "ugc_floor": 0.0, "max_text_chars": 6,
    "keep_full": True, "ref": sorted((ROOT / "downloads" / "inspoy_found" / "ref" / "boards").glob("ref_*.jpg")),
    "anchors": [
        "a fall outfit collage of clothing items on a plain white background: knit sweater, jeans, boots and a bag",
        "an autumn outfit flat lay on white with a coat, cozy sweater, trousers, ankle boots and gold jewelry",
        "a pinterest outfit board with fall clothes, shoes and accessories cut out on a white background",
    ],
    "queries": [
        "fall outfit collage", "autumn outfit collage", "fall outfit inspo collage", "fall outfits polyvore",
        "autumn outfit board", "fall capsule outfits collage", "cozy fall outfit ideas collage",
        "fall outfit flat lay white background", "autumn aesthetic outfit collage", "fall fits collage",
        "outfit shuffle fall", "fall outfit layout", "autumn outfit inspiration board", "fall outfit moodboard clothes",
    ]}
_CQ = {"no_faces": False, "out": (900, 1200), "min_aspect": 1.0, "related_rounds": 0, "related_seeds": 0,
       "weights": {"ref": 0.0, "text": 0.9, "ugc": 0.1}, "min_ref": 0.0, "ref": [], "ugc_floor": 0.0,
       "max_text_chars": 6, "keep_full": True}
_CQ_STARS = {"winter": "Anne Hathaway", "spring": "Blake Lively", "summer": "Emily Blunt", "autumn": "Julia Roberts",
             "true_summer": "Dakota Johnson", "light_summer": "Elle Fanning", "soft_summer": "Jennifer Aniston"}
for _k, _n in _CQ_STARS.items():
    _l = _n.lower()
    PROFILES[f"cq_{_k}"] = {**_CQ, "anchors": [f"a close portrait photo of {_n}, face and shoulders, looking at the camera"],
                            "queries": [f"{_l} portrait", f"{_l} headshot", f"{_l} red carpet", f"{_l} face",
                                        f"{_l} photoshoot", f"{_l} close up"]}
    PROFILES[f"cq_{_k}_wide"] = {**_CQ, "min_aspect": 0.7,          # по пояс: для круга нужно место над головой
                                 "anchors": [f"a waist-up photo of {_n} at an event, whole head and shoulders visible"],
                                 "queries": [f"{_l} red carpet", f"{_l} premiere", f"{_l} event", f"{_l} street style",
                                             f"{_l} outfit", f"{_l} gala", f"{_l} festival", f"{_l} 2024"]}
# 1322 партия 100: больше звёзд того же цветотипа (по цветотип-блогам; ref-звёзды тоже), студийные портреты крупно
CQ2_STARS = {
    "winter": ["Anne Hathaway", "Megan Fox", "Lucy Liu", "Lily Collins"],
    "spring": ["Blake Lively", "Amy Adams", "Emma Stone", "Taylor Swift"],
    "summer": ["Emily Blunt", "Kate Middleton", "Margot Robbie", "Cate Blanchett"],
    "autumn": ["Julia Roberts", "Jennifer Lopez", "Jessica Chastain", "Julianne Moore"],
    "card_5": ["Dakota Johnson", "Olivia Wilde", "Natalie Portman", "Caitriona Balfe"],          # true summer
    "card_6": ["Elle Fanning", "Dakota Fanning", "Gwyneth Paltrow", "Naomi Watts", "Reese Witherspoon"],  # light
    "card_7": ["Jennifer Aniston", "Sarah Jessica Parker", "Bella Hadid", "Zoe Saldana"],      # soft summer
    "1384": ["Liv Tyler", "Mindy Kaling", "Emma Watson", "Kendall Jenner"],   # 1384: звёзды из ТЗ, которых не было
}
for _slot, _names in CQ2_STARS.items():
    for _n in _names:
        _l = _n.lower()
        PROFILES["cq2_" + _l.replace(" ", "_")] = {**_CQ, "min_aspect": 0.7, "max_text_chars": 8,
            "anchors": [f"a studio headshot portrait of {_n}, face and shoulders, plain background, looking at the camera"],
            "queries": [f"{_l} headshot", f"{_l} portrait", f"{_l} photoshoot", f"{_l} studio portrait",
                        f"{_l} close up", f"{_l} photocall", f"{_l} face", f"{_l} beauty shoot"]}
# 1384 обложки: свежие (2025–2026) эстетичные фото звёзд из ТЗ — кампании, эдиториалы, как в фидбеке
# (Dior Cruise 2027 с Jennifer Lawrence, Bella Hadid 2026); старые фото 2010-х не нужны
CV26_STARS = ["Megan Fox", "Liv Tyler", "Lucy Liu", "Lily Collins", "Margot Robbie", "Mindy Kaling", "Emma Watson",
              "Blake Lively", "Amy Adams", "Jennifer Aniston", "Jennifer Lopez", "Kendall Jenner"]
for _n in CV26_STARS:
    _l = _n.lower()
    PROFILES["cv26_" + _l.replace(" ", "_")] = {**_CQ, "min_aspect": 1.15, "max_text_chars": 12,
        "anchors": [f"a 2026 high fashion campaign photo of {_n}, modern editorial, natural makeup, soft light, "
                    f"elegant, sharp high quality magazine photo",
                    f"{_n} in a recent luxury brand campaign, aesthetic editorial portrait, 2026"],
        "queries": [f"{_l} 2026", f"{_l} 2026 photoshoot", f"{_l} campaign 2026", f"{_l} editorial 2026",
                    f"{_l} 2025 photoshoot", f"{_l} vogue 2026", f"{_l} aesthetic 2026", f"{_l} magazine cover 2026",
                    f"{_l} campaign", f"{_l} editorial"]}
# 1384 обложки, раунд 2: конкретные профессиональные съёмки 2024–2026 (кампании брендов, обложки журналов) —
# названия из веб-поиска 2026-10-30; пользователь одобрил только кампании уровня Donna Karan FW26
CVPRO = {
    "kendall_jenner": ["kendall jenner donna karan campaign", "kendall jenner donna karan fall 2026",
                       "kendall jenner khaite campaign", "kendall jenner vogue france 2026",
                       "kendall jenner burberry campaign", "kendall jenner campaign 2026 editorial"],
    "margot_robbie": ["margot robbie british vogue 2026", "margot robbie vogue australia 2026", "margot robbie chanel campaign",
                      "margot robbie chanel 2026", "margot robbie v magazine 2026", "margot robbie wuthering heights photoshoot"],
    "megan_fox": ["megan fox photoshoot 2026", "megan fox amber asaly", "megan fox editorial 2025",
                  "megan fox magazine photoshoot", "megan fox campaign"],
    "blake_lively": ["blake lively vogue september 2024", "blake lively baz luhrmann vogue", "blake lively blake brown campaign",
                     "blake lively editorial 2025", "blake lively vogue photoshoot"],
    "lily_collins": ["lily collins zalando campaign", "lily collins zalando 2026", "lily collins lancome campaign",
                     "lily collins emily in paris season 5 photoshoot", "lily collins editorial 2025"],
    "jennifer_lopez": ["jennifer lopez instyle 2025", "jennifer lopez interview magazine brianna capozzi",
                       "jennifer lopez jlo beauty campaign", "jennifer lopez vogue mexico", "jennifer lopez editorial 2025"],
    "jennifer_aniston": ["jennifer aniston elle 2025", "jennifer aniston harpers bazaar 2025", "jennifer aniston vanity fair 2025",
                         "jennifer aniston lolavie campaign", "jennifer aniston editorial 2025"],
    "emma_watson": ["emma watson miu miu", "emma watson vogue photoshoot", "emma watson lancome campaign",
                    "emma watson editorial", "emma watson 2025"],
    "amy_adams": ["amy adams s magazine 2026", "amy adams nino munoz", "amy adams cultured magazine",
                  "amy adams daniel jack lyons", "amy adams editorial 2026"],
    "lucy_liu": ["lucy liu modern luxury 2026", "lucy liu moynat campaign", "lucy liu vogue singapore",
                 "lucy liu v magazine china", "lucy liu editorial 2025"],
    "liv_tyler": ["liv tyler g-star campaign", "liv tyler g-star raw 2026", "liv tyler the rake", "liv tyler editorial 2025",
                  "liv tyler campaign"],
    "mindy_kaling": ["mindy kaling bustle 2026", "mindy kaling christian soria", "mindy kaling vogue india",
                     "mindy kaling editorial 2025", "mindy kaling photoshoot 2026"],
}
for _k, _q in CVPRO.items():
    _n = _k.replace("_", " ").title()
    PROFILES["cvpro_" + _k] = {**_CQ, "min_aspect": 1.15, "max_text_chars": 12,
        "anchors": [f"a professional luxury fashion campaign photo of {_n} by a top photographer, magazine editorial, "
                    f"sharp high resolution, elegant styling, natural makeup"],
        "queries": _q}
# 1387 Inspoy «my ex invited me to his birthday»: 3:4; s1 яркое эмоциональное селфи (база для Flow), s2 подруга
# подбирает образы (POV), s3–s5 яркие образы — селфи в зеркале, лицо закрыто телефоном (из Pinterest как есть)
_EX = {"no_faces": False, "out": (1080, 1440), "min_aspect": 1.15, "related_rounds": 1, "related_seeds": 8,
       "weights": {"ref": 0.0, "text": 0.7, "ugc": 0.3}, "min_ref": 0.0, "ref": [], "max_text_chars": 30,
       "keep_full": True}
PROFILES["ex_s1"] = {**_EX,
    "anchors": ["a bright emotional phone selfie of a pretty young woman, shocked surprised face, hand on her cheek, "
                "colorful outfit, sunny vivid colors, close up",
                "a candid excited selfie of a girl with wide eyes and open mouth, bright saturated colors"],
    "queries": ["shocked selfie girl", "surprised face selfie aesthetic", "omg face selfie", "emotional selfie girl",
                "bright selfie aesthetic", "shocked girl aesthetic", "colorful selfie girl", "surprised girl selfie",
                "excited selfie girl", "girl gasping selfie"]}
PROFILES["ex_s2"] = {**_EX, "no_faces": True,
    "anchors": ["first person view of a best friend holding up bright colorful dresses and outfits in front of an open "
                "wardrobe, clothes on hangers, bedroom, candid phone photo",
                "girls choosing outfits, colorful clothes laid out on the bed and hanging, pov photo"],
    "queries": ["friend picking outfit", "choosing outfit with best friend", "getting ready with best friend",
                "girls trying on clothes", "outfit choosing bedroom aesthetic", "holding dress hanger aesthetic",
                "what should i wear aesthetic", "clothes on bed getting ready", "best friend styling me",
                "trying outfits with friends"]}
PROFILES["ex_s1b"] = {**_EX, "max_text_chars": 12,   # добор для s1: эстетичные селфи с эмоцией «😳», дорого и светло
    "anchors": ["an aesthetic iPhone selfie of a beautiful young woman with a surprised shocked expression, wide eyes, "
                "parted lips, hand near her face, soft natural daylight, clean bright background, high quality",
                "a pretty girl gasping in a candid selfie, eyebrows raised, glowing skin, bright airy room, pinterest aesthetic"],
    "queries": ["surprised selfie aesthetic", "shocked selfie aesthetic girl", "omg selfie aesthetic", "gasp selfie girl",
                "hand over mouth selfie aesthetic", "surprised face aesthetic pinterest", "shocked girl pinterest selfie",
                "selfie surprised expression natural light", "wide eyes selfie aesthetic", "pretty girl shocked face",
                "that girl selfie surprised", "clean girl selfie surprised"]}
PROFILES["ex_s1c"] = {**_EX, "max_text_chars": 12,   # s1, раунд 3: шок с открытым ртом, взгляд в камеру, по плечи
    "anchors": ["a gorgeous slim young woman taking a selfie, looking straight into the camera, shocked with her mouth "
                "wide open in a gasp, eyebrows raised, head and shoulders in frame, bright aesthetic room, natural light",
                "a beautiful model-like girl with a jaw-drop shocked expression in a bright selfie, looking at the lens"],
    "queries": ["shocked selfie model", "jaw drop selfie girl", "gasp selfie pretty girl", "shocked face selfie aesthetic",
                "surprised selfie beautiful girl", "omg face pretty girl", "shocked expression woman selfie",
                "mouth open shocked selfie", "shocked reaction selfie aesthetic", "surprised face model photoshoot",
                "shocked girl looking at camera", "pretty girl shocked selfie bedroom"]}
_EX_LOOK = {**_EX, "no_faces": True, "min_aspect": 1.2, "max_text_chars": 12}
PROFILES["ex_fine"] = {**_EX_LOOK,
    "anchors": ["a full length mirror selfie of a woman in a bright casual outfit, colorful knit sweater and jeans, "
                "phone covering her face, cute effortless look",
                "mirror selfie casual bright outfit, colorful cardigan, face hidden by the phone"],
    "queries": ["bright casual outfit mirror selfie", "colorful casual outfit mirror", "cute casual outfit mirror selfie",
                "colorful knit outfit mirror selfie", "bright outfit mirror pic", "casual chic colorful outfit",
                "colorful cardigan outfit mirror", "pink casual outfit mirror selfie", "green outfit mirror selfie",
                "blue outfit mirror selfie"]}
PROFILES["ex_better"] = {**_EX_LOOK,
    "anchors": ["a full length mirror selfie of a woman in a bold stylish bright outfit, colored blazer or satin set, "
                "heels, phone covering her face, confident chic look",
                "mirror selfie of a striking colorful two piece set, statement outfit, face hidden by the phone"],
    "queries": ["bold colorful outfit mirror selfie", "bright blazer outfit mirror", "colorful two piece set mirror selfie",
                "statement outfit mirror selfie", "chic bright outfit mirror", "red outfit mirror selfie",
                "satin skirt outfit mirror selfie", "colorful going out outfit mirror", "bright suit outfit mirror",
                "cobalt blue outfit mirror selfie"]}
PROFILES["ex_who"] = {**_EX_LOOK,
    "anchors": ["a full length mirror selfie of a woman in a show-stopping bright party dress, red or hot pink mini "
                "dress, heels, phone covering her face, glamorous birthday party look",
                "mirror selfie stunning bright satin or sequin dress, night out look, face hidden by the phone"],
    "queries": ["red dress mirror selfie", "hot pink dress mirror selfie", "party dress mirror selfie",
                "sequin dress mirror selfie", "birthday outfit mirror selfie", "bright mini dress mirror",
                "night out dress mirror selfie", "satin dress mirror selfie", "glam dress mirror pic",
                "baddie dress mirror selfie"]}
# 1342 квиз «какой цвет волос тебе идёт» (концепт 1322): звёзды с узнаваемым цветом волос; эры с другим цветом
# отсеиваем вручную при отборе
HC_STARS = {
    "ash blonde": ["Cara Delevingne", "Rosie Huntington-Whiteley", "Elsa Hosk", "Gwen Stefani"],
    "golden brown": ["Jennifer Lopez", "Jessica Alba", "Alessandra Ambrosio", "Gisele Bundchen"],
    "soft espresso": ["Lucy Hale", "Selena Gomez", "Kendall Jenner", "Mila Kunis"],
    "copper": ["Emma Stone", "Isla Fisher", "Karen Gillan", "Sophie Turner"],
}
for _hc, _names in HC_STARS.items():
    for _n in _names:
        _l = _n.lower()
        PROFILES["hc_" + _l.replace(" ", "_").replace("-", "_")] = {**_CQ, "min_aspect": 0.7, "max_text_chars": 8,
            "anchors": [f"a studio headshot portrait of {_n} with {_hc} hair, face and shoulders, plain background, looking at the camera"],
            "queries": [f"{_l} {_hc} hair", f"{_l} headshot", f"{_l} portrait", f"{_l} {_hc} hair color",
                        f"{_l} photoshoot", f"{_l} close up", f"{_l} beauty shoot", f"{_l} hair"]}
for _k, _c in {"blue": "light blue", "brown": "dark brown", "green": "green", "hazel": "hazel",
               "dark": "very dark brown, almost black"}.items():
    PROFILES[f"cq_eyes2_{_k}"] = {**_CQ, "out": (900, 900), "min_aspect": 0.3,
        "anchors": [f"a close up of a woman's face showing both {_c} eyes and eyebrows, horizontal crop, natural light"],
        "queries": [f"{_k} eyes close up both eyes", f"{_k} eyes face close up", f"{_c} eyes woman close up",
                    f"{_k} eyes eyebrows close up", f"{_k} eyes natural makeup close up", f"{_k} eyed girl close up",
                    f"{_k} eyes macro face", f"{_k} eyes aesthetic close up"]}
_CQ_HAIR = {"ginger": "copper ginger red", "brown": "chocolate brown", "blonde": "golden blonde", "black": "jet black"}
for _k, _c in _CQ_HAIR.items():
    PROFILES[f"cq_hair_{_k}"] = {**_CQ, "no_faces": True, "out": (900, 900), "min_aspect": 0.8,
        "anchors": [f"long {_c} hair seen from behind, close up of the hair, no face"],
        "queries": [f"{_k} hair back view", f"{_k} hair aesthetic", f"{_c} hair color", f"{_k} hair from behind",
                    f"{_k} wavy hair back", f"{_k} hair inspo"]}
_CQ_EYES = {"blue": "light blue", "brown": "dark brown", "green": "green", "hazel": "hazel"}
for _k, _c in _CQ_EYES.items():
    PROFILES[f"cq_eyes_{_k}"] = {**_CQ, "out": (900, 900), "min_aspect": 0.5,
        "anchors": [f"a close up photo of a woman's two {_c} eyes, both eyes visible, natural light"],
        "queries": [f"{_k} eyes close up", f"{_k} eyes aesthetic", f"{_k} eyes woman", f"{_c} eyes macro",
                    f"{_k} eyes makeup natural", f"pretty {_k} eyes"]}
PROFILES["cq_wrist3"] = {**_CQ, "no_faces": True, "out": (1200, 900), "min_aspect": 0.3, "max_text_chars": 400,
    "weights": {"ref": 0.5, "text": 0.5, "ugc": 0.0},
    "ref": [ROOT / "downloads" / "1322" / "ref" / "slide2.jpg"],
    "anchors": ["three raised fists side by side showing inner wrists with green, blue-green and purple veins, undertone test",
                "vein test chart: warm, neutral and cool undertone wrists with different vein colors"],
    "queries": ["undertone vein test", "vein test undertone", "warm neutral cool undertone veins", "undertone wrist veins chart",
                "how to find your undertone veins", "skin undertone vein color", "vein color undertone", "undertone test wrist",
                "cool warm neutral undertone", "find your undertone", "color analysis undertone veins", "veins green blue purple"]}
PROFILES["cq_wrist"] = {**_CQ, "no_faces": True, "out": (900, 1200), "min_aspect": 0.8,
    "anchors": ["a close up of a woman's inner wrist with visible veins, hand making a loose fist, plain background"],
    "queries": ["wrist veins undertone", "inner wrist veins", "vein test undertone", "veins on wrist",
                "undertone wrist test", "green veins wrist", "blue veins wrist", "purple veins wrist", "fist inner wrist"]}

# 1321 Inspoy «my grandma had 7 husbands»: 3:4; s1 внучка с бабушкой, s2 стильная бабушка у шкафа, s3–s5 образы
# «Husband #1 / #4 / #7» (разные эпохи) — селфи в зеркало
_GH = {"no_faces": False, "out": (1080, 1440), "min_aspect": 1.1, "related_rounds": 1, "related_seeds": 8,
       "weights": {"ref": 0.0, "text": 0.7, "ugc": 0.3}, "min_ref": 0.0, "ref": [], "max_text_chars": 40,
       "keep_full": True}
PROFILES["gh_s1"] = {**_GH,  # девушка с бабушкой, тёплое фото вдвоём
    "anchors": ["a young woman and her stylish elegant grandmother taking a selfie together, smiling, cozy candid photo",
                "granddaughter hugging her glamorous grandma at home, warm casual phone photo"],
    "queries": ["me and my grandma", "grandma and granddaughter selfie", "granddaughter grandmother aesthetic",
                "stylish grandma and granddaughter", "grandma selfie aesthetic", "my grandma and me photo",
                "grandmother granddaughter photo ideas", "grandma hug aesthetic", "glamorous grandma", "cool grandma photo"]}
PROFILES["gh_s2"] = {**_GH,  # бабушка показывает на шкаф / вещи
    "anchors": ["an elegant stylish grandmother standing at an open wardrobe full of clothes, pointing at an outfit",
                "a chic elderly woman with silver hair holding up a dress from her closet, smiling"],
    "queries": ["stylish grandma closet", "grandma wardrobe vintage clothes", "elegant old lady fashion",
                "grandmother closet aesthetic", "stylish older woman wardrobe", "grandma fashion icon",
                "vintage closet grandma", "chic grandma outfit", "older woman choosing clothes", "grandma dressing room"]}
PROFILES["gh_s3"] = {**_GH,  # Husband #1 — давно: ретро 60-х
    "anchors": ["a young woman taking a mirror selfie in a retro 1960s inspired outfit: polka dot dress, cardigan, kitten heels",
                "vintage style outfit mirror selfie: midi skirt, fitted cardigan, headscarf, pearls"],
    "queries": ["vintage outfit mirror selfie", "60s inspired outfit", "retro outfit aesthetic", "polka dot dress outfit",
                "vintage cardigan skirt outfit", "audrey hepburn style outfit", "retro fit check", "vintage fashion mirror pic"]}
PROFILES["gh_s4"] = {**_GH,  # Husband #4 — середина: 80-е/90-е
    "anchors": ["a young woman taking a mirror selfie in a 90s inspired outfit: oversized blazer, slip skirt, loafers",
                "80s power dressing outfit mirror selfie: shoulder pad blazer, high waist trousers, gold jewelry"],
    "queries": ["90s outfit mirror selfie", "90s inspired outfit", "oversized blazer outfit", "80s outfit aesthetic",
                "slip skirt blazer outfit", "90s fashion fit check", "power suit outfit women", "retro 90s look"]}
PROFILES["gh_s5"] = {**_GH,  # Husband #7 — сейчас: эффектный современный образ
    "anchors": ["a young woman taking a mirror selfie in a glamorous modern date night outfit: red satin dress, heels",
                "chic modern evening outfit mirror selfie: little black dress, statement earrings, heels"],
    "queries": ["date night outfit mirror selfie", "red dress outfit", "glamorous outfit mirror pic", "satin dress outfit",
                "little black dress outfit", "evening outfit fit check", "classy date outfit", "elegant night out outfit"]}

# 1328 Inspoy «my grandpa has been married to the same woman for 52 years»: 3:4; s1 внучка с дедушкой, s2 дедушка у
# шкафа, s3–s5 образы «Year 1 / 25 / 52» (70-е, конец 90-х, сейчас) — все «как на первое свидание», селфи в зеркало
_GP = {**_GH}
PROFILES["gp_s1"] = {**_GP,  # девушка с дедушкой, тёплое фото вдвоём
    "anchors": ["a young woman and her sweet stylish grandfather taking a selfie together, both smiling, cozy casual phone photo",
                "granddaughter hugging her grandpa at home, warm candid phone photo"],
    "queries": ["me and my grandpa", "grandpa and granddaughter selfie", "granddaughter grandfather aesthetic",
                "grandpa selfie aesthetic", "my grandpa and me photo", "grandfather granddaughter photo ideas",
                "grandpa hug aesthetic", "cool grandpa photo", "stylish grandpa", "grandpa and me"]}
PROFILES["gp_s2"] = {**_GP,  # дедушка у шкафа показывает на вещи
    "anchors": ["a stylish elderly man with grey hair standing at an open wardrobe, pointing at clothes and smiling",
                "a dapper grandfather holding up a dress or jacket from a closet at home"],
    "queries": ["stylish grandpa closet", "old man wardrobe", "dapper old man style", "grandfather closet aesthetic",
                "stylish older man wardrobe", "grandpa fashion", "old gentleman style home", "grandpa choosing clothes",
                "elderly man fashion icon", "vintage closet grandpa"]}
PROFILES["gp_s3"] = {**_GP,  # Year 1 — 70-е: свидание
    "anchors": ["a young woman taking a mirror selfie in a 1970s inspired date outfit: flared jeans, suede jacket, platform shoes",
                "70s style outfit mirror selfie: wide collar blouse, high waisted flares, suede bag"],
    "queries": ["70s outfit mirror selfie", "70s inspired outfit", "flared jeans outfit", "suede jacket outfit",
                "70s fashion aesthetic women", "retro 70s fit check", "boho 70s outfit", "70s date outfit"]}
PROFILES["gp_s4"] = {**_GP,  # Year 25 — конец 90-х: свидание
    "anchors": ["a young woman taking a mirror selfie in a late 1990s date outfit: slip dress over a fitted tee, cardigan, platform sandals",
                "90s date night outfit mirror selfie: satin slip dress, baby tee, small shoulder bag"],
    "queries": ["90s date outfit", "90s slip dress outfit", "late 90s fashion outfit", "90s outfit mirror selfie",
                "90s aesthetic outfit women", "slip dress cardigan outfit", "90s going out outfit", "90s fit check"]}
PROFILES["gp_s5"] = {**_GP,  # Year 52 — сейчас: свидание
    "anchors": ["a young woman taking a mirror selfie in a chic modern date night outfit: elegant midi dress, heels, small bag",
                "modern classy date outfit mirror selfie: satin skirt, fitted top, statement earrings"],
    "queries": ["date night outfit mirror selfie", "classy date outfit", "elegant date night outfit", "satin skirt outfit",
                "chic dinner outfit", "date night fit check", "elegant midi dress outfit", "first date outfit"]}

# 1322 партия 301–600: ни одного фото из сданных — новые звёзды тех же цветотипов (по цветотип-блогам, субъективно),
# студийные портреты / эдиториалы крупно; волосы и глаза — новые запросы (повторы с 1322_lib отсеиваем по dHash)
CQ3_STARS = {
    "winter": ["Jennifer Connelly", "Courteney Cox", "Zooey Deschanel", "Dita Von Teese"],
    "spring": ["Cameron Diaz", "Kate Hudson", "Amanda Seyfried", "Sydney Sweeney"],
    "summer": ["Charlize Theron", "Rosie Huntington-Whiteley", "Cara Delevingne", "Kate Bosworth"],
    "autumn": ["Eva Mendes", "Jessica Alba", "Gisele Bundchen", "Drew Barrymore"],
    "card_5": ["Rachel Weisz", "Brooke Shields", "Kirsten Dunst"],          # true summer
    "card_6": ["Elsa Hosk", "Anya Taylor-Joy", "Michelle Williams"],        # light summer
    "card_7": ["Hailey Bieber", "Kate Moss", "Gigi Hadid"],                 # soft summer
}
for _slot, _names in CQ3_STARS.items():
    for _n in _names:
        _l = _n.lower()
        PROFILES["cq3_" + _l.replace(" ", "_").replace("-", "_")] = {**_CQ, "min_aspect": 0.7, "max_text_chars": 8,
            "anchors": [f"a studio headshot portrait of {_n}, face and shoulders, plain background, looking at the camera",
                        f"a recent high quality editorial portrait of {_n}, soft light, natural makeup"],
            "queries": [f"{_l} headshot", f"{_l} portrait", f"{_l} photoshoot", f"{_l} studio portrait",
                        f"{_l} close up", f"{_l} beauty shoot", f"{_l} editorial", f"{_l} 2025 photoshoot",
                        f"{_l} campaign"]}
_CQ3_HAIR = {"ginger": ["ginger hair back view", "copper red hair from behind", "red hair waves back", "auburn hair aesthetic",
                        "strawberry copper hair", "ginger hair inspo back"],
             "brown": ["brunette hair back view", "brown hair waves from behind", "chestnut hair aesthetic",
                       "chocolate brown hair back", "glossy brown hair", "brunette blowout back"],
             "blonde": ["blonde hair back view", "honey blonde hair from behind", "golden blonde waves back",
                        "buttery blonde hair", "blonde blowout back", "blonde hair inspo back"],
             "black": ["black hair back view", "jet black hair from behind", "long black hair waves back",
                       "glossy black hair", "black hair aesthetic back", "raven hair long"]}
for _k, _q in _CQ3_HAIR.items():
    PROFILES[f"cq3_hair_{_k}"] = {**_CQ, "no_faces": True, "out": (900, 900), "min_aspect": 0.8,
        "anchors": [f"long {_CQ_HAIR[_k]} hair seen from behind, close up of the hair, no face"], "queries": _q}
for _k, _c in {"blue": "light blue", "brown": "dark brown", "green": "green", "hazel": "hazel"}.items():
    PROFILES[f"cq3_eyes_{_k}"] = {**_CQ, "out": (900, 900), "min_aspect": 0.3,
        "anchors": [f"a close up of a woman's face showing both {_c} eyes and eyebrows, horizontal crop, natural light"],
        "queries": [f"{_c} eyes close up", f"both {_k} eyes close up", f"{_k} eyes eyebrows macro", f"{_k} eyes no makeup close up",
                    f"{_k} eyes freckles close up", f"{_k} eyes photography", f"{_k} eyes model close up",
                    f"woman with {_k} eyes close up"]}

# добор глаз для партии 301–600: простые слова, как ищут люди (отбор глазами, только оба глаза)
for _k in ("blue", "brown", "hazel", "green"):
    PROFILES[f"cq4_eyes_{_k}"] = {**_CQ, "out": (900, 900), "min_aspect": 0.3,
        "anchors": [f"a close up of a woman's face showing both {_k} eyes and eyebrows, horizontal crop"],
        "queries": [f"{_k} eyes", f"{_k} eyes aesthetic", f"{_k} eyes girl", f"pretty {_k} eyes", f"{_k} eyed girl"]}

# 1322 партия 601–900 («визуально новее»): снова ни одной звезды из прошлых библиотек (CQ, CQ2, CQ3) — новые звёзды
# тех же цветотипов (по цветотип-блогам, субъективно); волосы и глаза — новые запросы, повторы отсеиваем по dHash
CQ5_STARS = {
    "winter": ["Katy Perry", "Selena Gomez", "Krysten Ritter", "Sandra Bullock"],
    "spring": ["Jennifer Lawrence", "Sabrina Carpenter", "Kate Upton", "Nicole Kidman"],
    "summer": ["Emilia Clarke", "Rose Byrne", "Kristen Bell", "Lily James"],
    "autumn": ["Isla Fisher", "Eva Longoria", "Penelope Cruz", "Shakira"],
    "card_5": ["Rachel McAdams", "Jennifer Garner", "Kristen Stewart"],    # true summer
    "card_6": ["Claire Danes", "Carey Mulligan", "Sienna Miller"],         # light summer
    "card_7": ["Olivia Palermo", "Mila Kunis", "Jessica Biel"],            # soft summer
}
for _slot, _names in CQ5_STARS.items():
    for _n in _names:
        _l = _n.lower()
        PROFILES["cq5_" + _l.replace(" ", "_").replace("-", "_")] = {**_CQ, "min_aspect": 0.7, "max_text_chars": 8,
            "anchors": [f"a studio headshot portrait of {_n}, face and shoulders, plain background, looking at the camera",
                        f"a recent high quality editorial portrait of {_n}, soft light, natural makeup"],
            "queries": [f"{_l} headshot", f"{_l} portrait", f"{_l} photoshoot", f"{_l} studio portrait",
                        f"{_l} close up", f"{_l} beauty shoot", f"{_l} editorial", f"{_l} 2025 photoshoot",
                        f"{_l} campaign"]}
_CQ5_HAIR = {"ginger": ["red hair from the back", "copper hair color", "ginger curls back", "natural red hair long",
                        "auburn balayage back", "strawberry blonde hair back"],
             "brown": ["brown hair from the back", "mocha brown hair", "brunette long layers back", "brown curly hair back",
                       "espresso brown hair", "brunette balayage back"],
             "blonde": ["blonde hair from the back", "platinum blonde long hair", "vanilla blonde waves", "blonde curls back",
                        "beige blonde hair", "sandy blonde hair back"],
             "black": ["black hair from the back", "black curly hair back", "sleek black hair long", "black wavy hair back",
                       "blue black hair", "black hair blowout back"]}
for _k, _q in _CQ5_HAIR.items():
    PROFILES[f"cq5_hair_{_k}"] = {**_CQ, "no_faces": True, "out": (900, 900), "min_aspect": 0.8,
        "anchors": [f"long {_CQ_HAIR[_k]} hair seen from behind, close up of the hair, no face"], "queries": _q}
for _k, _c in {"blue": "blue", "brown": "brown", "green": "green", "hazel": "hazel"}.items():
    PROFILES[f"cq5_eyes_{_k}"] = {**_CQ, "out": (900, 900), "min_aspect": 0.3,
        "anchors": [f"a close up of a woman's face showing both {_c} eyes and eyebrows, horizontal crop, looking at the camera"],
        "queries": [f"{_c} eyes model", f"{_c} eyes portrait close up", f"{_c} eyes makeup look", f"{_c} eyes natural beauty",
                    f"{_c} eyes face crop", f"beautiful {_c} eyes woman", f"{_c} eyes editorial"]}

# 1389 «top 5 websites to cure your boredom»: фон — фактура воды (как в рефе @farahzzrs: зеленоватая рябь с бликами), без людей
PROFILES["bg_water"] = {"no_faces": True, "out": (1080, 1350), "min_aspect": 0.9, "related_rounds": 0, "related_seeds": 0,
    "weights": {"ref": 0.5, "text": 0.4, "ugc": 0.1}, "min_ref": 0.0, "ugc_floor": 0.0, "max_text_chars": 2, "keep_full": True,
    "ref": [ROOT / "downloads" / "1389" / "ref" / "slide2.jpg"],
    "anchors": ["a close-up of rippling clear water surface with sunlight reflections, green turquoise water texture, full frame, no objects"],
    "queries": ["water texture", "water aesthetic", "pool water texture", "water ripples", "green water aesthetic",
                "sea water texture", "water background", "sparkling water aesthetic", "lake water texture", "clear water ripples"]}

# 1391 (видео-версия 1389, 9:16): новый фон вместо воды — небо с облаками; ref нужен только конструктору (вес 0)
PROFILES["bg_sky"] = {"no_faces": True, "out": (1080, 1920), "min_aspect": 1.4, "related_rounds": 0, "related_seeds": 0,
    "weights": {"ref": 0.0, "text": 0.75, "ugc": 0.25}, "min_ref": 0.0, "ugc_floor": 0.0, "max_text_chars": 2, "keep_full": True,
    "ref": [ROOT / "downloads" / "1389" / "ref" / "slide2.jpg"],
    "anchors": ["a dreamy blue sky full of soft white fluffy clouds, full frame, no ground, no buildings, no people"],
    "queries": ["sky aesthetic", "clouds aesthetic", "blue sky clouds", "cloud wallpaper", "aesthetic clouds",
                "sky wallpaper aesthetic", "dreamy clouds", "cotton candy sky", "pastel sky clouds", "fluffy clouds"]}

# 1389b «top 5 things to do when you're bored»: фото на экран iMac (16:9) для шуточных слайдов 1–3
_B89 = {"out": (1360, 766), "min_aspect": 0.4, "related_rounds": 0, "related_seeds": 0,
        "weights": {"ref": 0.0, "text": 0.75, "ugc": 0.25}, "min_ref": 0.0, "ugc_floor": 0.0, "max_text_chars": 2, "keep_full": True,
        "ref": [ROOT / "downloads" / "1389" / "ref" / "slide2.jpg"]}
PROFILES["b89_room"] = {**_B89, "no_faces": True,
    "anchors": ["a cozy bedroom at night lit by a warm lamp, wide shot of the whole room, furniture and bed, no people"],
    "queries": ["bedroom at night aesthetic", "cozy bedroom night", "dark bedroom aesthetic", "bedroom lamp glow",
                "bedroom fairy lights night", "room at night aesthetic", "moody bedroom", "late night room aesthetic",
                "rearranging room", "room makeover night", "messy room aesthetic night", "dorm room night aesthetic"]}
PROFILES["b89_dog"] = {**_B89, "no_faces": True,
    "anchors": ["a cute dog at home looking straight at the camera with sad longing eyes, the dog fills the frame"],
    "queries": ["sad dog aesthetic", "dog waiting by window", "dog looking at camera", "golden retriever aesthetic",
                "dog with phone", "dog on couch aesthetic", "puppy eyes", "dog in bed aesthetic", "sad puppy face",
                "dog staring funny", "cute dog at home", "french bulldog aesthetic"]}
PROFILES["b89_skill"] = {**_B89, "no_faces": False,
    "anchors": ["a person juggling colorful balls in the air, candid photo", "a person doing a moonwalk dance move, candid photo"],
    "queries": ["juggling", "juggling balls", "person juggling", "juggling aesthetic", "juggling photography", "juggling oranges",
                "learning to juggle", "moonwalk dance", "moonwalk", "street performer juggling", "whistling", "man whistling"]}

# 1389b, второй заход: ищем фото покрупнее; у собак вся морда с ушами и носом должна влезать в кадр 16:9
PROFILES["b89_dog2"] = {**_B89, "no_faces": True,
    "anchors": ["a whole dog's head with both ears and the entire muzzle in the middle of the photo, free space around it, at home"],
    "queries": ["dog portrait", "dog smiling at camera", "dog sitting on couch", "dog on bed looking at camera", "cute dog home photo",
                "dog head tilt", "sad dog", "dog waiting at door", "dog at window", "golden retriever portrait", "corgi face",
                "dog selfie", "french bulldog face", "labrador portrait", "beagle portrait", "puppy portrait", "dog looking out window",
                "dog in living room"]}
PROFILES["b89_room2"] = {**_B89, "no_faces": True,
    "anchors": ["a cozy bedroom at night lit by lamps and string lights, wide shot of the whole room, sharp photo, no people"],
    "queries": ["cozy bedroom at night", "bedroom night lamp aesthetic", "night room string lights", "bedroom night city view",
                "room decor night aesthetic", "bedroom led lights", "apartment at night cozy", "dark cozy room", "night bedroom photo",
                "studio apartment night", "small bedroom night aesthetic", "cozy room night window"]}
PROFILES["b89_skill2"] = {**_B89, "no_faces": False,
    "anchors": ["a person juggling balls or clubs in the air, sharp candid photo"],
    "queries": ["juggling photo", "juggler street", "juggling clubs", "juggling in park", "juggling at home", "juggling silhouette",
                "juggler sunset", "juggling hands balls", "juggling beach", "fire juggling", "moonwalk street", "whistling with fingers"]}

UGC_FLOOR = 0.45          # ниже — сток / глянец
MIN_SHORT_SIDE = 600      # px у оригинала
MIN_ASPECT = 1.1          # h / w — нужна вертикаль (3:4 после кропа)
DUP_HAMMING = 10          # dHash: то же фото (репин)
DUP_COSINE = 0.95         # SigLIP: то же фото в другом кадрировании
OCR_MAX_CHARS = 6         # надпись длиннее — картинка с текстом, не берём
FACE_MIN_FRAC = 0.07      # лицо шире 7% кадра — «в кадре человек»


@dataclass
class Cand:
    pin_id: str
    title: str
    url: str
    orig_url: str
    found_by: str
    image: Image.Image | None = None
    vec: np.ndarray | None = None
    ref: float = 0.0
    text: float = 0.0
    ugc: float = 0.0
    score: float = 0.0
    fp: int = 0
    reasons: list[str] = field(default_factory=list)


def url_736(url: str) -> str:
    return re.sub(r"/(?:\d+x|originals)/", "/736x/", url, count=1)


def dhash(im: Image.Image) -> int:
    g = np.asarray(im.convert("L").resize((9, 8)), dtype=np.int16)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def fetch(cli: httpx.Client, url: str) -> Image.Image | None:
    try:
        r = cli.get(url)
        if r.status_code != 200:
            return None
        return ImageOps.exif_transpose(Image.open(io.BytesIO(r.content))).convert("RGB")
    except Exception:
        return None


class Pool:
    def __init__(self, profile: dict) -> None:
        sys.path.insert(0, str(ROOT))
        from core.harvester import PinterestHarvester
        from core.taste_embedder import get_embedder
        from core.ugc_filter import get_ugc_filter

        self.p = profile
        self.h = PinterestHarvester()
        self.h.warm_session(force=False)
        self.emb = get_embedder()
        self.emb.ensure()
        self.ugc = get_ugc_filter()
        self.cli = httpx.Client(
            timeout=25, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com/"},
        )
        self.cands: dict[str, Cand] = {}
        self.seen_related: set[str] = set()
        refs = [Image.open(r).convert("RGB") for r in profile["ref"]]
        self.ref_vecs = self.emb.embed_images(refs) if refs else None
        self.anchor_vecs = self.emb.embed_texts(list(profile["anchors"]))
        self._ocr = None
        self._faces = None

    # --- сбор -----------------------------------------------------------
    def add_metas(self, metas, found_by: str) -> int:
        n = 0
        for m in metas:
            if m.pin_id in self.cands or m.is_ai is True:
                continue
            self.cands[m.pin_id] = Cand(m.pin_id, m.title, m.image_url, m.orig_url, found_by)
            n += 1
        return n

    def search_all(self) -> None:
        for q in self.p["queries"]:
            pins = self.h.search(q, finalize=False)
            print(f"[search] {q!r}: {len(pins)} пинов, новых {self.add_metas(pins, q)}", flush=True)

    def download_new(self) -> None:
        todo = [c for c in self.cands.values() if c.image is None and not c.reasons]
        with ThreadPoolExecutor(8) as ex:
            ims = list(ex.map(lambda c: fetch(self.cli, url_736(c.url)), todo))
        for c, im in zip(todo, ims):
            if im is None:
                c.reasons.append("download")
            elif im.height / im.width < self.p.get("min_aspect", MIN_ASPECT):
                c.reasons.append("landscape")
            else:
                c.image = im
        print(f"[download] {len(todo)} → ок {sum(im is not None for im in ims)}", flush=True)

    def score_new(self) -> None:
        todo = [c for c in self.cands.values() if c.image is not None and c.vec is None]
        if not todo:
            return
        vecs = self.emb.embed_images([c.image for c in todo])
        ugc = self.ugc.get_ugc_scores([c.image for c in todo])
        text = self.emb._cosine_to_prob(vecs @ self.anchor_vecs.T).max(axis=1)
        ref = (vecs @ self.ref_vecs.T).max(axis=1) if self.ref_vecs is not None else np.zeros(len(todo))
        w = self.p["weights"]
        for c, v, u, t, r in zip(todo, vecs, ugc, text, ref):
            c.vec, c.ugc, c.text, c.ref = v, float(u), float(t), float(r)
            c.fp = dhash(c.image)
            c.score = w["ref"] * c.ref + w["text"] * c.text + w["ugc"] * c.ugc
            if c.ugc < self.p.get("ugc_floor", UGC_FLOOR):
                c.reasons.append(f"ugc {c.ugc:.2f}")
            if self.p["min_ref"] and c.ref < self.p["min_ref"]:
                c.reasons.append(f"ref {c.ref:.2f}")

    def live(self) -> list[Cand]:
        return sorted(
            (c for c in self.cands.values() if c.vec is not None and not c.reasons),
            key=lambda c: -c.score,
        )

    def expand_related(self) -> None:
        for rnd in range(self.p["related_rounds"]):
            seeds = [c for c in self.live() if c.pin_id not in self.seen_related][: self.p["related_seeds"]]
            added = 0
            for c in seeds:
                self.seen_related.add(c.pin_id)
                metas = self.h.fetch_related_metas(c.pin_id, limit=24, exclude_ids=set(self.cands))
                added += self.add_metas(metas, f"related:{c.pin_id}")
            print(f"[related] раунд {rnd + 1}: от {len(seeds)} лучших +{added} пинов", flush=True)
            self.download_new()
            self.score_new()

    # --- отбор ----------------------------------------------------------
    def has_text(self, im: Image.Image) -> bool:
        if self._ocr is None:
            import easyocr

            self._ocr = easyocr.Reader(["en"], gpu=True, verbose=False)
        small = im.copy()
        small.thumbnail((640, 640))
        res = self._ocr.readtext(np.asarray(small), detail=1)
        chars = sum(len(t.strip()) for _b, t, conf in res if conf >= 0.45)
        return chars > self.p.get("max_text_chars", OCR_MAX_CHARS)

    def has_face(self, im: Image.Image) -> bool:
        import cv2

        if self._faces is None:
            self._faces = [
                cv2.CascadeClassifier(cv2.data.haarcascades + name)
                for name in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml")
            ]
        small = im.copy()
        small.thumbnail((480, 480))
        g = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2GRAY)
        min_px = max(24, int(small.width * FACE_MIN_FRAC))
        return any(
            len(c.detectMultiScale(g, 1.1, 6, minSize=(min_px, min_px))) for c in self._faces
        )

    def select(self, target: int) -> list[Cand]:
        picked: list[Cand] = []
        for c in self.live():
            if len(picked) >= target:
                break
            if any(bin(c.fp ^ p.fp).count("1") <= DUP_HAMMING for p in picked):
                c.reasons.append("dup-fp")
                continue
            if any(float(c.vec @ p.vec) >= DUP_COSINE for p in picked):
                c.reasons.append("dup-cos")
                continue
            if self.p.get("no_faces") and self.has_face(c.image):
                c.reasons.append("face")
                continue
            if self.has_text(c.image):
                c.reasons.append("text")
                continue
            picked.append(c)
        return picked

    def save(self, picked: list[Cand], out: Path) -> None:
        out.mkdir(parents=True, exist_ok=True)
        rows = []
        for i, c in enumerate(picked, 1):
            full = fetch(self.cli, c.orig_url) or c.image
            if min(full.size) < MIN_SHORT_SIDE:
                full = c.image if min(c.image.size) >= min(full.size) else full
            img = ImageOps.fit(full, self.p.get("out", (OUT_W, OUT_H)), Image.Resampling.LANCZOS, centering=(0.5, 0.42))
            name = f"{i:03d}_{c.pin_id}.jpg"
            img.save(out / name, quality=93)
            if self.p.get("keep_full"):                   # оригинал без кадрирования — для своей обрезки
                (out / "_full").mkdir(exist_ok=True)
                full.convert("RGB").save(out / "_full" / name, quality=93)
            rows.append({
                "file": name, "pin_id": c.pin_id, "title": c.title,
                "pin_url": f"https://www.pinterest.com/pin/{c.pin_id}/",
                "found_by": c.found_by, "score": round(c.score, 3),
                "ref": round(c.ref, 3), "text": round(c.text, 3), "ugc": round(c.ugc, 3),
                "source_px": list(full.size),
            })
        (out / "manifest.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        sheet(out, rows)


def sheet(out: Path, rows: list[dict]) -> None:
    tw, th, cols = 180, 240, 10
    n = len(rows)
    s = Image.new("RGB", (cols * tw, ((n + cols - 1) // cols) * (th + 18)), (25, 25, 25))
    d = ImageDraw.Draw(s)
    font = ImageFont.truetype("arial.ttf", 13)
    for i, r in enumerate(rows):
        x, y = (i % cols) * tw, (i // cols) * (th + 18)
        s.paste(Image.open(out / r["file"]).resize((tw, th)), (x, y + 18))
        d.text((x + 2, y + 2), f"{r['file'][:3]} s{r['score']:.2f} u{r['ugc']:.2f}", fill=(255, 230, 80), font=font)
    s.save(out / "_sheet.jpg", quality=85)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=sorted(PROFILES), required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--target", type=int, default=100)
    ap.add_argument("--ref-dir", type=Path, help="рефы = все jpg папки (напр. уже отобранные)")
    ap.add_argument("--exclude-dir", type=Path, action="append", default=[],
                    help="пины из этих папок (вкл. _rejected) не брать")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    t0 = time.perf_counter()
    profile = dict(PROFILES[args.profile])
    if args.ref_dir:
        profile["ref"] = sorted(f for f in args.ref_dir.glob("*.jpg") if not f.name.startswith("_"))
    pool = Pool(profile)
    seen = {f.stem.rsplit("_", 1)[-1] for d in args.exclude_dir for f in d.rglob("*.jpg")}
    if args.ref_dir:
        # «похожие пины» сразу от отобранных вручную
        for pid in sorted({f.stem.rsplit("_", 1)[-1] for f in profile["ref"]}):
            pool.seen_related.add(pid)
            pool.add_metas(pool.h.fetch_related_metas(pid, limit=24, exclude_ids=seen), f"related:{pid}")
    for pid in seen:
        pool.cands.pop(pid, None)
    pool.add_metas = (lambda orig: (lambda metas, by: orig([m for m in metas if m.pin_id not in seen], by)))(pool.add_metas)
    pool.search_all()
    pool.download_new()
    pool.score_new()
    pool.expand_related()
    picked = pool.select(args.target)
    pool.save(picked, args.out)

    why: dict[str, int] = {}
    for c in pool.cands.values():
        for r in c.reasons:
            k = r.split()[0]
            why[k] = why.get(k, 0) + 1
    print(f"кандидатов {len(pool.cands)} · отсеяно {why} · отобрано {len(picked)}")
    print(f"готово за {time.perf_counter() - t0:.0f} с → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
