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
