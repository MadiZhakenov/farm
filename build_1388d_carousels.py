#!/usr/bin/env python3
"""
1388 (Drops, drops.game) — «i posted my first song ever and my friends left it on read 🙃»: 5 слайдов 3:4 (1080×1440).
Номер 1388 уже занят каруселью Inspoy (output/1388_100), поэтому все папки этой — 1388d_*.
Тексты ТЗ дословно, TikTok-шрифт с обводкой, переносы по смыслу, только в безопасной рамке core/safe_zones.

  s1 лицо девушки (Flow) + вставка-скрин чата Instagram: «new song out now 🎧», под ним только «Seen by everyone»
  s2 скрин группового чата: 🔥 / sounds good bro / Seen by …  (прочитали, но всем всё равно)
  s3 скрин загрузки трека на drops.game         — output/1388d_slides/s3 (нужен вход в аккаунт Drops)
  s4 скрин готовой игры из трека                — downloads/1388d/games (capture_1388d_games.py)
  s5 скрин чата: друг «my score is 8k, send me the next one 😭» под ссылкой на игру

Чаты рисует render_igdm.py заново для каждой карусели: в пределах карусели одна группа, имена, тема и время,
между каруселями всё разное — повторов нет.

  python build_1388d_carousels.py --qa -n 4 --out output/carousels_1388d_test
  python build_1388d_carousels.py -n 200 --out output/carousels_1388d --flat output/1388d_200 --flat-id 1388
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1281_carousels as B  # noqa: E402  (backdrop)
import build_1283_carousels as C  # noqa: E402  (block_for — та же типографика)
import render_igdm as R  # noqa: E402
from core.safe_zones import check_box, draw_overlay, text_rect  # noqa: E402

W, H = 1080, 1440
X0, Y0, X1, Y1 = text_rect(W, H)
SL = ROOT / "output" / "1388d_slides"
GAMES = ROOT / "downloads" / "1388d" / "games"    # все кадры; отобранные — в output/1388d_slides/s4
EXT = (".jpg", ".jpeg", ".png", ".webp")
NL = chr(10)

TEXTS = [
    NL.join(["i posted my first song ever", "and my friends left it on read 🙃"]),
    NL.join(["so yeah,", "nobody actually listened"]),
    NL.join(["so i decided", "to do something better.", "", "i went on Drops", "and uploaded my song"]),
    NL.join(["and it turned my track", "into a game"]),
    "my friends actually played it",
]

# аватарки друзей: кадры без лиц (руки, спины, закаты, кровати) из старых пулов
AV_SRC = (sorted((ROOT / "output" / "1281_pool" / "s7").glob("*.jpg"))[:40]
          + sorted((ROOT / "output" / "1307_pool" / "s2").glob("*.jpg"))[:10]
          + sorted((ROOT / "output" / "1321v2_pool" / "bed").glob("*.jpg"))[:20])
AV_PICK = [0, 1, 3, 5, 6, 9, 10, 11, 12, 14, 16, 20, 21, 23, 24, 25, 27, 30, 35, 36, 37, 38, 39, 43, 44, 52, 59, 62,
           66, 68]
AVATARS = [AV_SRC[i] for i in AV_PICK if i < len(AV_SRC)]

NAMES = ["mia", "jake", "sam", "ava", "leo", "noah", "chloe", "emma", "liam", "zoe", "max", "nina", "ethan", "lily",
         "ryan", "ella", "josh", "maya", "tyler", "grace", "ben", "sofia", "matt", "jess", "kai", "ruby", "dylan",
         "hannah", "luke", "abby", "nate", "olivia", "chris", "bella", "drew", "tess"]
GROUPS = ["the squad", "the group chat", "friends 🫶", "the gang", "college crew", "lunch table", "chaos 🌀",
          "besties + boys", "sunday crew", "the usual", "us ✨", "group chat 2.0", "ride or dies", "the fam 🫶",
          "weekend plans", "dorm 4B", "no thoughts just vibes", "the originals", "friday night", "real ones 🤍"]
SONG_LINKS = ["soundcloud.com/{h}/{s}", "open.spotify.com/track/{sp}", "youtu.be/{yt}", "soundcloud.com/{h}/{s}"]
HANDLES = ["lilyhartmusic", "itsnoa", "avamae", "juneskies", "rosiecantsleep", "mayaonrepeat", "ellie.sings",
           "claramoon", "sadiesongs", "nora.wav", "luna.demo", "chloesomething", "evie.mp3", "harper.hum"]
SONGS = ["first-light", "paper-hearts", "dont-wait-up", "golden-hour-demo", "on-read", "slow-motion", "my-first-song",
         "late-again", "pink-sky", "small-town-blue", "honey", "almost-summer", "say-it-back", "3am-thoughts"]
HER_DROP = ["play this 👀", "i made my song into a game lol", "ok try this", "my song is a game now 😭",
            "turned my song into a game, play it", "new drop 👀 play it"]
# старая болтовня группы над нашими сообщениями (верх уходит под шапку)
FILLER = [["who's coming saturday", "me!!", "same"],          # верхняя длинная уходит под шапку,
          ["did anyone finish the essay", "no 💀", "lol same"],  # две нижние короткие — справа от них подпись
          ["pizza tonight?", "YES", "i'm in"],
          ["who has my charger", "not me", "lmao"],
          ["omg did you see that video", "LMAO", "dead 💀"],
          ["im outside", "coming!!", "2 min"],
          ["what time is practice tmrw", "6 i think", "ugh"],
          ["send pics from last night", "no 😭", "never"],
          ["happy birthday chris 🎉", "🎂🎂", "ily"],
          ["anyone up for coffee", "omw", "me!!"]]
FILLER_TIME = ["Yesterday 6:02 PM", "Yesterday 9:41 PM", "Sun 4:15 PM", "Sat 11:20 AM", "Fri 7:48 PM", "Yesterday 1:12 PM"]
# название игры в превью ссылки — как в шапке её страницы на drops.game
GAME_TITLE = {"g1": "Overkill The Forest", "g2": "Meltdown - Crash", "g3": "What More Can I Say — Obby Course",
              "g7": "Lose The Desert"}
EXTRA_FRIEND = ["wait this is actually fun", "how did you make this??", "ok this slaps", "i've played it 6 times",
                "this is so cool", "WAIT"]


def plan_chat(rng: random.Random) -> dict:
    names = rng.sample(NAMES, 5)
    av = rng.sample(AVATARS, 5)
    h, m = rng.choice([7, 8, 9, 10]), rng.randint(0, 59)
    link = rng.choice(SONG_LINKS).format(
        h=rng.choice(HANDLES), s=rng.choice(SONGS),
        sp="".join(rng.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(22)),
        yt="".join(rng.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_") for _ in range(11)))
    return dict(
        theme="dark",
        group=rng.choice(GROUPS), names=names, av=av, link=link if rng.random() < 0.75 else None,
        t_pm=(h, m), s1_after=rng.randint(4, 25), s2_after=rng.randint(30, 140),
        drop_t=(rng.choice([1, 2, 3, 4, 5, 6]), rng.randint(0, 59)), drop_after=rng.randint(6, 50),
        her_drop=rng.choice(HER_DROP), extra=rng.choice(EXTRA_FRIEND) if rng.random() < 0.5 else None,
        react=rng.choice(["😭🔥", "🔥", "😭", "❤️🔥", "🔥😭"]), react_n=rng.randint(3, 5),
        uuid=str(uuid.UUID(int=rng.getrandbits(128), version=4)), link_long=True,
        bat=(rng.uniform(0.3, 0.9), rng.uniform(0.2, 0.8), rng.uniform(0.15, 0.7)),
        others=rng.randint(1, 3),
        filler=rng.sample(FILLER, 2), filler_t=rng.sample(FILLER_TIME, 2), filler_who=rng.random() < 0.5,
        card_frame=rng.random(),
    )


def fmt(h: int, m: int) -> str:
    h, m = h + m // 60, m % 60
    return f"{(h - 1) % 12 + 1}:{m:02d} PM"


def clock(h: int, m: int) -> str:
    h, m = h + m // 60, m % 60
    return f"{(h - 1) % 12 + 1}:{m:02d}"


def chat_s1(p: dict) -> R.Chat:
    h, m = p["t_pm"]
    rows = [("time", fmt(h, m)), ("me", "new song out now 🎧"), ("seen", "Seen by everyone")]
    return R.Chat(title=p["group"], subtitle="Active now", avatars=p["av"][:2], rows=rows, theme=p["theme"],
                  clock=clock(h, m + p["s1_after"]), battery=p["bat"][0])


def chat_s2(p: dict, hist: int = 1) -> R.Chat:
    h, m = p["t_pm"]
    n, av = p["names"], p["av"]
    rows = filler_rows(p, 0, hist) + [("time", fmt(h, m)), ("mark", "key"), ("me", "new song out now 🎧"),
                                ("them", "🔥", n[0], av[0]),
            ("them", "sounds good bro", n[1], av[1]),
            ("seen", f"Seen by {n[2]}, {n[3]}" + (f" and {p['others']} others" if p["others"] > 1 else f", {n[4]}"))]
    return R.Chat(title=p["group"], subtitle=f"Active {rng_m(p)}m ago", avatars=av[:2], rows=rows, theme=p["theme"],
                  clock=clock(h, m + p["s2_after"]), battery=p["bat"][1])


def rng_m(p: dict) -> int:
    return 1 + p["s1_after"] % 9


def filler_rows(p: dict, k: int, hist: int) -> list:
    """Старая история над нашими сообщениями: hist реплик (0 или 1), сверху отметка "top" — начало переписки."""
    n, av = p["names"], p["av"]
    who = (n[3], av[3]) if p["filler_who"] else (n[2], av[2])
    return [("mark", "top")] + [("them", p["filler"][k][-1], *who)][:hist]


def card_image(game: str, pick: float) -> Image.Image:
    """Кадр той же игры, что на слайде 4, для превью ссылки: игровое поле без шапки/кнопок, 1.91:1."""
    frames = sorted(f for f in GAMES.glob(f"{game}_*.png") if "_title" not in f.name and not f.name.endswith("_01.png"))
    im = Image.open(frames[int(pick * len(frames)) % len(frames)]).convert("RGB")
    im = im.crop((0, int(0.14 * im.height), im.width, int(0.80 * im.height)))
    return ImageOps.fit(im, (764, 400), Image.Resampling.LANCZOS, centering=(0.5, 0.55))


def chat_s5(p: dict, game: str | None, hist: int = 1) -> R.Chat:
    h, m = p["drop_t"]
    n, av = p["names"], p["av"]
    g = game or "g1_17bd5eb4"
    rows = filler_rows(p, 1, hist) + [("time", fmt(h, m)), ("mark", "key"),
                                ("card", card_image(g, p["card_frame"]), GAME_TITLE[g[:2]], "drops.game"),
                                ("react", p["react"], p["react_n"]),
                                ("them", "my score is 8k, send me the next one 😭", n[1], av[1])]
    return R.Chat(title=p["group"], subtitle="Active now", avatars=av[:2], rows=rows, theme=p["theme"],
                  clock=clock(h, m + p["drop_after"]), battery=p["bat"][2])


def glow_block(block: Image.Image, alpha: float = 0.6) -> Image.Image:
    """Тёмная мягкая подложка по форме текста: переписка под подписью гаснет, края плавные."""
    pad = 70
    a = Image.new("L", (block.width + 2 * pad, block.height + 2 * pad), 0)
    a.paste(block.getchannel("A"), (pad, pad))
    a = a.filter(ImageFilter.MaxFilter(41)).filter(ImageFilter.GaussianBlur(22)).point(lambda v: int(min(255, v * 1.6) * alpha))
    out = Image.new("RGBA", a.size, (0, 0, 0, 255))
    out.putalpha(a)
    out.alpha_composite(block, (pad, pad))
    return out


def caption(k: int, top: int, bottom: int, cx: float = 0.5, mw: float | None = None,
            glow: bool = False) -> tuple[Image.Image, tuple]:
    """Подпись слайда k по центру полосы [top, bottom] внутри безопасной рамки (mw — макс. ширина, доля кадра).
    glow — мягкая тёмная подложка по форме текста (поверх пузырей чата буквы не смешиваются с перепиской)."""
    top, bottom = max(top, Y0), min(bottom, Y1)
    block = C.block_for(TEXTS[k], bottom - top, int(mw * W) if mw else X1 - X0)
    x = int(cx * W - block.width / 2)
    x = max(X0, min(X1 - block.width, x))
    y = int((top + bottom) / 2 - block.height / 2)
    y = max(Y0, min(Y1 - block.height, y))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if glow:
        layer.alpha_composite(glow_block(block), (x - 70, y - 70))
    else:
        layer.alpha_composite(block, (x, y))
    return layer, (x, y, x + block.width, y + block.height)


CAP_PX_MIN = 44     # подпись на чате не мельче — иначе лучше убрать старую реплику


def overlaps(a: tuple, b: tuple, pad: int = 6) -> bool:
    return a[0] < b[2] + pad and b[0] < a[2] + pad and a[1] < b[3] + pad and b[1] < a[3] + pad


def chat_slide(k: int, make_chat) -> tuple[Image.Image, tuple]:
    """Скрин телефона на весь кадр: переписка прижата к строке ввода, сверху под шапкой — тёмная полоса,
    подпись в ней. Не задевает ни один пузырь / имя / время: если не влезает, старая реплика убирается."""
    for hist in (1, 0):
        chat = make_chat(hist)
        bg = R.render(chat, H, full=True, anchor="bottom").convert("RGBA")
        top, first = int(R.render.header_bottom) + 16, int(R.render.marks["top"]) - 16
        if first - top < 60 or not C.fits(TEXTS[k], CAP_PX_MIN, first - top, X1 - X0):
            continue
        layer, box = caption(k, top, first)
        hit = [b for b in R.render.boxes if b[3] > R.render.header_bottom and overlaps(box, b)]
        if hit:
            continue
        return Image.alpha_composite(bg, layer).convert("RGB"), box
    raise SystemExit(f"слайд {k + 1}: подпись не помещается над перепиской даже без старой истории")


def inset_card(chat: R.Chat, width: int) -> Image.Image:
    """Обрезанный скрин чата (шапка + сообщение + Seen) — карточка со скруглением и тенью."""
    full = R.render(chat, H)
    cut = int(R.render.bottom + 26)
    card = full.crop((0, R.STATUS_H, W, cut))
    card = card.resize((width, int(card.height * width / W)), Image.Resampling.LANCZOS).convert("RGBA")
    m = Image.new("L", (card.width * 3, card.height * 3), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, m.width - 1, m.height - 1), radius=34 * 3, fill=255)
    card.putalpha(m.resize(card.size, Image.Resampling.LANCZOS))
    pad = 40
    sh = Image.new("L", (card.width + 2 * pad, card.height + 2 * pad), 0)
    sh.paste(card.getchannel("A").point(lambda v: int(v * 0.55)), (pad, pad + 10))
    out = Image.new("RGBA", sh.size, (0, 0, 0, 255))
    out.putalpha(sh.filter(ImageFilter.GaussianBlur(18)))
    out.alpha_composite(card, (pad, pad))
    return out


def s1_slide(photo: Path | None, chat: R.Chat, layout: dict) -> tuple[Image.Image, tuple]:
    if photo is None:
        bg = Image.new("RGB", (W, H), (150, 140, 135))
        ImageDraw.Draw(bg).text((W / 2, H * 0.4), "PHOTO (Flow)", fill="white", anchor="mm",
                                font=R.font(70, 600))
    else:
        bg = ImageOps.fit(Image.open(photo).convert("RGB"), (W, H), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    bg = bg.convert("RGBA")
    card = inset_card(chat, int(layout.get("card_w", 0.62) * W))
    cx = int(layout.get("card_cx", 0.5) * W)
    cb = int(layout.get("card_bottom", 0.775) * H)
    bg.alpha_composite(card, (cx - card.width // 2, cb - card.height + 40))
    layer, box = caption(0, int(layout.get("text_top", 0.06) * H), int(layout.get("text_bottom", 0.24) * H))
    return Image.alpha_composite(bg, layer).convert("RGB"), box


def screen_slide(k: int, src: Path, layout: dict) -> tuple[Image.Image, tuple]:
    """Скрин телефона 1170×2532 → кусок 3:4 (top — доля высоты скрина), подпись в полосе text_top–text_bottom."""
    im = Image.open(src).convert("RGB")
    cw = im.width
    ch = int(cw * H / W)
    top = int(layout.get("top", 0.0) * im.height)
    top = max(0, min(im.height - ch, top))
    bg = im.crop((0, top, cw, top + ch)).resize((W, H), Image.Resampling.LANCZOS).convert("RGBA")
    layer, box = caption(k, int(layout.get("text_top", 0.3) * H), int(layout.get("text_bottom", 0.5) * H))
    return Image.alpha_composite(bg, layer).convert("RGB"), box


S1_LAYOUT: dict[str, dict] = {
    "girl_": {"card_w": 0.48, "card_cx": 0.38, "card_bottom": 0.775, "text_top": 0.05, "text_bottom": 0.21},
}     # по началу имени фото: card_cx / card_w / card_bottom / text_top / text_bottom
# s3: главная drops.game без входа (скрин Pro Max 430 css @3x): от подзаголовка до кнопок Upload a song — ровно 3:4
# на всю ширину; подпись справа от кружка START FREE
S3_LAYOUT = {"css": (95, 668), "bg": (255, 199, 0), "text_top": 0.258, "text_bottom": 0.445, "cx": 0.574, "mw": 0.52}


def site_slide(k: int, src: Path, lay: dict) -> tuple[Image.Image, tuple]:
    """Кусок скрина (css y0–y1, масштаб 3) на всю ширину кадра; если короче 3:4 — снизу фон сайта."""
    im = Image.open(src).convert("RGB")
    y0, y1 = (int(v * 3) for v in lay["css"])
    part = im.crop((0, y0, im.width, y1))
    part = part.resize((W, round(part.height * W / part.width)), Image.Resampling.LANCZOS)
    bg = Image.new("RGBA", (W, H), lay["bg"] + (255,))
    bg.paste(part.crop((0, 0, W, min(H, part.height))), (0, 0))
    layer, box = caption(k, int(lay["text_top"] * H), int(lay["text_bottom"] * H), lay["cx"], lay["mw"])
    return Image.alpha_composite(bg, layer).convert("RGB"), box


# s3 (основной вариант): фото экрана компа из Flow с настоящим скрином сайта (make_1388d_s3_screens.py),
# подпись — на пустой стене над экраном
S3P_LAYOUT = {"text_top": 0.05, "text_bottom": 0.25}


def photo_slide(k: int, src: Path, lay: dict) -> tuple[Image.Image, tuple]:
    bg = ImageOps.fit(Image.open(src).convert("RGB"), (W, H), Image.Resampling.LANCZOS).convert("RGBA")
    layer, box = caption(k, int(lay["text_top"] * H), int(lay["text_bottom"] * H))
    return Image.alpha_composite(bg, layer).convert("RGB"), box


# s4: кусок 3:4 скрина игры (top — доля высоты скрина) и полоса подписи по спокойному месту кадра
S4_LAYOUT = {
    "g1": {"top": 0.215, "text_top": 0.06, "text_bottom": 0.21},   # раннер: деревья сверху, герой внизу
    "g2": {"top": 0.17, "text_top": 0.17, "text_bottom": 0.33},    # неоновый полёт: тёмные небоскрёбы
    "g3": {"top": 0.19, "text_top": 0.06, "text_bottom": 0.21},    # обби: облака сверху
    "g6": {"top": 0.11, "text_top": 0.07, "text_bottom": 0.22},    # ритм-игра: небо
    "g7": {"top": 0.27, "text_top": 0.06, "text_bottom": 0.20},    # пустыня: герой бежит внизу, подпись над горами
    "g8": {"top": 0.17, "text_top": 0.06, "text_bottom": 0.20},    # визуализатор: тёмный верх
    "title": {"top": 0.085, "text_top": 0.06, "text_bottom": 0.19},  # заставка «A GAME ON DROPS … Play»
}


def s4_layout(name: str) -> dict:
    if "_title" in name:                                             # у «Lose the Desert» заставка ниже
        return dict(S4_LAYOUT["title"], top=0.15) if name.startswith("g7") else S4_LAYOUT["title"]
    return next(v for pre, v in S4_LAYOUT.items() if name.startswith(pre))


def pool(d: Path) -> list[Path]:
    return sorted(f for f in d.iterdir() if f.is_file() and f.suffix.lower() in EXT and not f.name.startswith("_")) \
        if d.is_dir() else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=200)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=1388)
    ap.add_argument("--flat", type=Path, help="ещё и одной папкой: sort_<слайд>_<карусель>_<id>.jpg")
    ap.add_argument("--flat-id", default="")
    ap.add_argument("--qa", action="store_true", help="к каждой карусели — копия с зонами интерфейса")
    ap.add_argument("--allow-missing", action="store_true", help="тест без фото/скринов: заглушки")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    p1, p3, p4 = pool(SL / "s1"), pool(SL / "s3_photo") or pool(SL / "s3"), pool(SL / "s4")
    print(f"кадров: s1 {len(p1)} · s3 {len(p3)} · s4 {len(p4)}")
    if not args.allow_missing and not (p1 and p3 and p4):
        raise SystemExit("не хватает кадров (s1 фото / s3 загрузка / s4 игры) — для теста --allow-missing")
    rng = random.Random(args.seed)
    order = {k: (rng.sample(p, len(p)) if p else []) for k, p in ((1, p1), (3, p3), (4, p4))}
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i in range(1, args.n + 1):
        p = plan_chat(rng)
        pick = {k: (order[k][(i - 1) % len(order[k])] if order[k] else None) for k in order}
        d = args.out / f"{i:03d}"
        d.mkdir(exist_ok=True)
        slides = []
        lay1 = next((v for pre, v in S1_LAYOUT.items() if pick[1] and pick[1].name.startswith(pre)), {})
        slides.append(s1_slide(pick[1], chat_s1(p), lay1))
        slides.append(chat_slide(1, lambda hist: chat_s2(p, hist)))
        for k in (3, 4):
            if pick[k] is None:
                ph = Image.new("RGB", (W, H), (40, 40, 40))
                ImageDraw.Draw(ph).text((W / 2, H / 2), f"s{k}: нет скрина", fill="white", anchor="mm",
                                        font=R.font(60, 600))
                layer, box = caption(k - 1, int(0.3 * H), int(0.5 * H))
                slides.append((Image.alpha_composite(ph.convert("RGBA"), layer).convert("RGB"), box))
            else:
                if k == 3:
                    slides.append(photo_slide(2, pick[3], S3P_LAYOUT) if pick[3].parent.name == "s3_photo"
                                  else site_slide(2, pick[3], S3_LAYOUT))
                else:
                    slides.append(screen_slide(3, pick[4], s4_layout(pick[4].name)))
        game = pick[4].name[:11] if pick[4] else None
        slides.append(chat_slide(4, lambda hist: chat_s5(p, game, hist)))
        for k, (im, box) in enumerate(slides, 1):
            bad = check_box(W, H, box)
            if bad:
                raise SystemExit(f"карусель {i}, слайд {k}: текст вне безопасной зоны — {bad}")
            im.save(d / f"{k}.jpg", quality=95)
            if args.qa:
                q = draw_overlay(im)
                ImageDraw.Draw(q).rectangle(box, outline=(255, 255, 0), width=5)
                q.save(d / f"_qa_{k}.jpg", quality=80)
            if args.flat:
                args.flat.mkdir(parents=True, exist_ok=True)
                suffix = f"_{args.flat_id}" if args.flat_id else ""
                shutil.copy2(d / f"{k}.jpg", args.flat / f"sort_{k}_{i}{suffix}.jpg")
        manifest.append({"carousel": d.name, "s1": pick[1] and pick[1].name, "s3": pick[3] and pick[3].name,
                         "s4": pick[4] and pick[4].name, "chat": {k: v for k, v in p.items() if k != "av"},
                         "avatars": [a.name for a in p["av"]]})
        print(f"  {d.name}", flush=True)
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False, default=str),
                                            encoding="utf-8")
    print(f"готово: {len(manifest)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
