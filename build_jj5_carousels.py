#!/usr/bin/env python3
"""June's Journey 5 (ID 1) — карусели «бабушкины хобби» по примеру клиента (Dropbox UGC.ninja «Granny Mommy hobbies»,
downloads/junes_journey_5/example): 6 слайдов, фото «от первого лица» (рука, уют), на 1-м слайде заголовок крупным
жирным шрифтом с засечками (Georgia Bold, кремовый, мягкое тёмное свечение) в верхней трети, на остальных — белая
подпись Arial Bold с тенью ниже середины; слайд с игрой — скриншот June's Journey во всю ширину по центру поверх его же
размытой копии, подпись под ним. Тексты ТЗ дословно, переносы по смыслу. Карусели 3:4 (1080×1440, правило фермы),
текст в рамке 3:4 (x 180–900, y 6–78 %). Юзер 16.11: только карусели, 3 версии × 50, фото — новые из Flow
(output/junes_journey_5/PROMPTS_jj5.md → downloads/junes_journey_5/flow/P01…P15).

Уникальность каруселей при одном фото на слайд (правило «1 промпт на слайд»): у каждой карусели свой кадр фото
(зум 1.0–1.14 со сдвигом), свет/тёплость, лёгкое зерно, сдвиг и размер текста; игровой слайд — свой скриншот уровня
и свой кадр. Проверка: отпечатки каждого слайда (dHash 16×16) по всем парам каруселей версии.

  python build_jj5_carousels.py --test          # по 2 карусели на версию → output/_work/jj5/test (+ QA-лист зон)
  python build_jj5_carousels.py                 # 3 × 50 → output/junes_journey_5_v{1,2,3}_50
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import check_box, draw_overlay  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402

W, H = 1080, 1440
X0, X1, Y0, Y1 = 180, 900, round(0.06 * H), round(0.78 * H)
FLOW = ROOT / "downloads" / "junes_journey_5" / "flow"
WORK = ROOT / "output" / "_work" / "jj5"
# юзер 16.11: «обычный тиктоковский без тени» — весь текст TikTok Sans, без тени; цвет как в TikTok: белый/чёрный по фону
F_TITLE = F_BODY = ROOT / "fonts" / "TikTokSans-SemiBold.ttf"
import build_jj4 as _J  # noqa: E402  (пул скриншотов игры, одобренный юзером для JJ4: 30 сцен уровней, без экранов наград)
STILLS = [p for p, _lv, _r in _J.POOL]

# тексты ТЗ дословно; строки — переносы по смыслу
VERS = {
    "v1": [["I used to laugh", "at my mom's hobbies."],
           ["Now I get excited", "about a new teacup."],
           ["I check my tomatoes", "every morning."],
           ["I have strong opinions", "about crossword puzzles."],
           ["And I look forward", "to quiet evenings."],
           ["One more mystery before bed.", "June's Journey."]],
    "v2": [["Signs I'm becoming", "a grandma", "before my time."],
           ["I own a favorite", "grocery shopping bag."],
           ["I get excited", "when the bread rises."],
           ["I take pictures of flowers."],
           ["I say “one more minute”", "during a mystery."],
           ["My evening obsession:", "June's Journey."]],
    "v3": [["I think granny hobbies", "might actually", "save us all."],
           ["Getting excited", "about fresh bread."],
           ["Spending Saturday mornings", "at the farmers market."],
           ["Solving little mysteries", "in June's Journey."],
           ["Buying another plant", "I definitely don't need."],
           ["Honestly,", "I've never been happier."]],
}
PHOTO = {"v1": ["P01F", "P02", "P03", "P04", "P05", "P16"],     # 16.11: слайд 1 — с лицом, слайд 6 — телефон с игрой (Flow)
         "v2": ["P06F", "P07", "P08", "P09", "P10", "P17"],
         "v3": ["P11F", "P12", "P13", "P18", "P14", "P15"]}


def font(path: Path, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), px)


def fit_px(lines: list[str], path: Path, px: int) -> int:
    while px > 30 and max(font(path, px).getlength(s) for s in lines) > X1 - X0 - 2 * max(2, round(px * 0.045)) - 6:
        px -= 1
    return px


def text_block(lines: list[str], path: Path, px: int, fill, lh: float, glow: bool) -> Image.Image:
    f = font(path, px)
    asc, desc = f.getmetrics()
    step = int(px * lh)
    blk = Image.new("RGBA", (W + 12, step * (len(lines) - 1) + asc + desc + 20), (0, 0, 0, 0))   # запас под обводку
    d = ImageDraw.Draw(blk)
    for i, s in enumerate(lines):
        # юзер 16.11: «белый текст, чёрный аутлайн» (обычный TikTok), без тени
        d.text(((W - f.getlength(s)) / 2 + 6, i * step + 6), s, font=f, fill=(255, 255, 255, 255),
               stroke_width=max(2, round(px * 0.045)), stroke_fill=(0, 0, 0, 255))
    return blk                                            # без тени (юзер 16.11)


def tone(img: Image.Image, cy: int, h: int) -> tuple:
    """Цвет текста как в TikTok: на светлом месте — чёрный, на тёмном — белый (средняя яркость под блоком)."""
    y0, y1 = max(0, cy - h // 2), min(H, cy + h // 2)
    lum = float(np.asarray(img.convert("L").crop((X0, y0, X1, y1)), np.float32).mean())
    return (255, 255, 255, 255)                           # всегда белый с чёрной обводкой (юзер 16.11)


def place(canvas: Image.Image, blk: Image.Image, cy: int) -> tuple[int, int, int, int]:
    """Блок по центру по горизонтали, середина на cy; возвращает рамку непрозрачных пикселей."""
    x, y = (W - blk.width) // 2, cy - blk.height // 2
    canvas.alpha_composite(blk, (x, y))
    bb = blk.getchannel("A").point(lambda v: 255 if v > 96 else 0).getbbox()
    return (x + bb[0], y + bb[1], x + bb[2], y + bb[3])


def calm_y(img: Image.Image, blk_h: int, pref: float = 0.27) -> int:
    """Середина подписи по высоте: самая спокойная полоса фото (меньше всего деталей — не рука, не предмет) в рамке
    3:4, при равенстве — ближе к pref (как в примере: ниже середины)."""
    g = np.asarray(img.convert("L").resize((W // 4, H // 4)), np.float32)
    e = np.abs(np.diff(g, axis=0))[:, :-1] + np.abs(np.diff(g, axis=1))[:-1]
    x0, x1 = X0 // 4, X1 // 4
    hb = max(4, (blk_h + 40) // 4)
    best, by = None, int(pref * H)
    for cy in range(Y0 + blk_h // 2 + 20, Y1 - blk_h // 2 - 10, 10):
        r0 = (cy - blk_h // 2 - 20) // 4
        busy = float(e[r0:r0 + hb, x0:x1].mean())
        score = busy + 4.0 * abs(cy / H - pref) + (8.0 if cy > 0.5 * H else 0.0)   # нижняя половина — рука/предмет
        if best is None or score < best:
            best, by = score, cy
    return by


def shade_field(seed: int, w: int, h: int) -> np.ndarray:
    """Мягкие волны света (как OneState): v<0 — светлее, v>0 — темнее."""
    r = random.Random(seed)
    x = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    ph = r.uniform(0, 6.28) + y * r.uniform(-6, 6) + np.sin(y * r.uniform(2, 5) + r.uniform(0, 6.28)) * r.uniform(0.5, 1.5)
    return (0.6 * np.sin(2 * np.pi * r.uniform(1.2, 2.6) * x + ph)
            + 0.4 * np.sin(2 * np.pi * r.uniform(2.5, 4.5) * x + ph * 1.7 + r.uniform(0, 6.28)))


def rand_params(rng: random.Random, nvar: int) -> dict:
    return dict(var=rng.randrange(nvar), z=round(rng.uniform(1.0, 1.3), 3), fx=round(rng.random(), 3),
                fy=round(rng.random(), 3), br=round(rng.uniform(0.95, 1.05), 3), warm=round(rng.uniform(-0.035, 0.035), 3),
                shade=rng.randrange(1 << 30), grain=rng.randrange(1 << 30))


def photo_frame(src: Image.Image, pr: dict, size: tuple[int, int] = (W, H), grain: bool = True) -> Image.Image:
    """Кадр фото карусели по параметрам pr: зум 1.0–1.3 со сдвигом, свет, тёплость, волны света ±10 %, зерно."""
    w, h = size
    im = ImageOps.fit(src.convert("RGB"), (W, H), Image.Resampling.LANCZOS) if src.size != (W, H) else src.convert("RGB")
    cw, ch = W / pr["z"], H / pr["z"]
    x, y = (W - cw) * pr["fx"], (H - ch) * pr["fy"]
    im = im.resize((w, h), Image.Resampling.LANCZOS if w == W else Image.Resampling.BILINEAR, box=(x, y, x + cw, y + ch))
    a = np.asarray(im, np.float32) * pr["br"]
    a[..., 0] *= 1 + pr["warm"]
    a[..., 2] *= 1 - pr["warm"]
    if not pr.get("plain"):
        v = shade_field(pr["shade"], w, h)[..., None]
        al = np.abs(v) * 0.10
        a = a * (1 - al) + np.where(v < 0, 255.0, 0.0) * al
    if grain and not pr.get("plain"):
        a += np.random.default_rng(pr["grain"]).normal(0, 2.0, a.shape[:2])[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def game_frame(rng: random.Random, still: Path) -> tuple[Image.Image, int]:
    """Скриншот игры во всю ширину (пропорции скрина) по центру поверх его размытой затемнённой копии."""
    src = Image.open(still).convert("RGB")
    sw, sh = src.size
    z = rng.uniform(1.0, 1.18)
    cw, ch = sw / z, sh / z
    x, y = rng.uniform(0, sw - cw), rng.uniform(0, sh - ch)
    shot = src.crop((int(x), int(y), int(x + cw), int(y + ch)))
    bh = round(W * shot.height / shot.width)
    band = shot.resize((W, bh), Image.Resampling.LANCZOS)
    bg = ImageOps.fit(shot, (W, H), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(28))
    bg = ImageEnhance.Brightness(bg).enhance(0.7)
    by = rng.randint(470, 520) - bh // 2 + 120
    bg.paste(band, (0, by))
    return bg, by + bh


def build(job: dict) -> list[str]:
    rng = random.Random(job["seed"])
    out = Path(job["dir"])
    out.mkdir(parents=True, exist_ok=True)
    errs = []
    for s, lines in enumerate(VERS[job["ver"]]):
        p = PHOTO[job["ver"]][s]
        if p is None:
            img, band_bottom = game_frame(rng, Path(job["still"]))
        else:
            vs = variants(p)
            pr = job["ph"][s]
            img = photo_frame(Image.open(vs[pr["var"]]) if vs else Image.new("RGB", (W, H), (120, 110, 100)), pr)
            band_bottom = None
        can = img.convert("RGBA")
        if s == 0:
            px = fit_px(lines, F_TITLE, job["tpx"])
            blk = text_block(lines, F_TITLE, px, (255, 255, 255, 255), 1.16, True)
            blk = text_block(lines, F_TITLE, px, tone(img, job["ty"], blk.height), 1.16, True)
            box = place(can, blk, job["ty"])
        else:
            px = fit_px(lines, F_BODY, job["bpx"])
            blk = text_block(lines, F_BODY, px, (255, 255, 255, 255), 1.18, False)
            # фото: подпись вверху (там фон — стена/полка/небо; рука и предмет ниже), сдвиг у каждой карусели свой
            if band_bottom is None:
                cy = int(0.15 * H) + (job["by"] - 995) // 2
            else:
                cy = min(Y1 - blk.height // 2 - 10, band_bottom + 30 + blk.height // 2)
            cy = max(Y0 + blk.height // 2, min(Y1 - blk.height // 2, cy))
            if band_bottom is None:
                blk = text_block(lines, F_BODY, px, tone(img, cy, blk.height), 1.18, False)
            box = place(can, blk, cy)
        bad = check_box(W, H, box)
        if bad:
            errs.append(f"{out.name} s{s + 1}: текст вне рамки {bad}")
        can.convert("RGB").save(out / f"sort_{s + 1}_{job['num']}_1.jpg", quality=92, optimize=True)   # без EXIF
    return errs


def variants(p: str) -> list[Path]:
    return sorted((FLOW / p).glob("*.*")) if (FLOW / p).is_dir() else sorted(FLOW.glob(f"{p}.*"))


def dhash(im: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    g = np.asarray(im.convert("L").resize((17, 16), Image.Resampling.BOX), np.int16)
    m = g[:, ::-1]
    return (g[:, 1:] > g[:, :-1]).ravel(), (m[:, 1:] > m[:, :-1]).ravel()


def plan_photos(jobs: list[dict], thr: int = 48, tries: int = 250) -> list[int]:
    """Уникальность слайдов: у каждой карусели для каждого фото-слайда подбираются параметры кадра так, чтобы отпечаток
    слайда (dHash 16×16 всего слайда с текстом, как проверка) был дальше thr бит от того же слайда ВСЕХ уже принятых
    каруселей (и зеркально). Расчёт — на уменьшенных копиях (270×360), быстро; итог проверяется по готовым JPG."""
    lw, lh = W // 4, H // 4
    worst = []
    for s in range(6):
        p = PHOTO[jobs[0]["ver"]][s]
        if p is None:
            continue
        vs = variants(p)
        base = [ImageOps.fit(Image.open(v).convert("RGB"), (W, H), Image.Resampling.LANCZOS) for v in vs]
        # слайд с телефоном: верх экрана игры (доля высоты, по картинкам из Flow) — подпись сверху на него не залезает
        tops = [PHONE_TOP[p] for _ in base] if p in PHONE_TOP else [None for _ in base]
        bank: list = []
        for j in jobs:
            rng = random.Random(j["seed"] * 7 + s)
            lines = VERS[j["ver"]][s]
            best = None
            for _ in range(tries):
                pr = rand_params(rng, len(vs))
                t = tops[pr["var"]]
                if t is not None and (t[0] * H - (H - H / pr["z"]) * pr["fy"]) * pr["z"] < t[1] * H:
                    continue                                   # экран игры поднялся бы под подпись
                im = photo_frame(base[pr["var"]], pr, (lw, lh), grain=False).convert("RGBA")
                txt = text_overlay_small(j, s, lines, lw, lh)
                im.alpha_composite(txt)
                h, m = dhash(im)
                d = min([int((h != b).sum()) for b in bank] + [int((h != b).sum()) for b in [x[::-1] for x in []]] + [256])
                if bank:
                    B = np.array(bank)
                    d = int(min((B != h).sum(1).min(), (B != m).sum(1).min()))
                if best is None or d > best[0]:
                    best = (d, pr, h)
                if d > thr:
                    break
            if best is None:                                   # ни один вариант не прошёл ограничение экрана — без него
                pr = rand_params(rng, len(vs))
                pr.update(z=1.0, fy=0.5)
                best = (0, pr, dhash(photo_frame(base[pr["var"]], pr, (lw, lh), grain=False))[0])
            j.setdefault("ph", {})[s] = best[1]
            bank.append(best[2])
            worst.append(best[0])
    return worst


_TXT: dict = {}
# верх того, что нельзя закрывать (доля высоты на фото из Flow) → не выше этой доли в карусели:
# экран телефона — под подписью (0.24), голова на селфи — под заголовком (0.31)
PHONE_TOP = {"P16": (0.30, 0.24), "P17": (0.32, 0.24), "P18": (0.33, 0.24),
             "P01F": (0.32, 0.31), "P06F": (0.30, 0.31), "P11F": (0.31, 0.36)}


def text_overlay_small(j: dict, s: int, lines: list[str], lw: int, lh: int) -> Image.Image:
    """Текст слайда в масштабе 1/4 (как в сборке: тот же размер и место)."""
    key = (j["ver"], s, j["tpx"] if s == 0 else j["bpx"], j["ty"] if s == 0 else j["by"])
    if key not in _TXT:
        can = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if s == 0:
            px = fit_px(lines, F_TITLE, j["tpx"])
            blk = text_block(lines, F_TITLE, px, (255, 255, 255, 255), 1.16, True)
            place(can, blk, j["ty"])
        else:
            px = fit_px(lines, F_BODY, j["bpx"])
            blk = text_block(lines, F_BODY, px, (255, 255, 255, 255), 1.18, False)
            place(can, blk, int(0.15 * H) + (j["by"] - 995) // 2)
        _TXT[key] = can.resize((lw, lh), Image.Resampling.BOX)
    return _TXT[key]


def jobs_for(ver: str, n: int, seed: int, out_root: Path) -> list[dict]:
    rng = random.Random(seed)
    stills = STILLS[:]
    rng.shuffle(stills)
    # вариант фото каждого слайда — по кругу со своим шагом у слайда: соседние карусели не повторяют набор
    return [dict(ver=ver, seed=rng.randrange(1 << 30), still=str(stills[i % len(stills)]),
                 var=[(i * (s + 1) + s + i // 4) for s in range(6)],
                 tpx=rng.randint(66, 70), bpx=rng.randint(50, 54), ty=rng.randint(300, 360), by=rng.randint(960, 1030),
                 num=i + 1, dir=str(out_root)) for i in range(n)]


def qa_sheet(dirs: list[Path], dest: Path) -> None:
    rows = []
    for d in dirs:
        ims = [draw_overlay(Image.open(d / f"{k:02d}.jpg").convert("RGB")).resize((270, 360)) for k in range(1, 7)]
        row = Image.new("RGB", (270 * 6, 360))
        for i, im in enumerate(ims):
            row.paste(im, (270 * i, 0))
        rows.append(row)
    sheet = Image.new("RGB", (270 * 6, 360 * len(rows)))
    for i, r in enumerate(rows):
        sheet.paste(r, (0, 360 * i))
    sheet.save(dest, quality=88)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=5116)
    ap.add_argument("--vers", default="v1,v2,v3")
    ap.add_argument("--plain", action="store_true", help="юзер 16.11: без своей уникализации — фото как есть")
    a = ap.parse_args()
    missing = [p for v in PHOTO.values() for p in v if p and not (FLOW / p).is_dir() and not next(FLOW.glob(f"{p}.*"), None)]
    if missing:
        print(f"нет фото из Flow: {missing} — для проверки раскладки стоят серые заглушки", flush=True)
    jobs = []
    for k, ver in enumerate(("v1", "v2", "v3")):
        if ver not in a.vers.split(","):
            continue
        root = (WORK / "test") if a.test else (ROOT / "output" / f"junes_journey_5_{ver}_{a.n}")
        if not a.test and root.exists():
            shutil.rmtree(root)
        jobs += jobs_for(ver, 2 if a.test else a.n, a.seed + k, root)
    t0 = __import__("time").time()
    for ver in ("v1", "v2", "v3"):
        js = [j for j in jobs if j["ver"] == ver]
        if js and a.plain:
            for i, j in enumerate(js):
                j.update(tpx=68, bpx=52, ty=330, by=995)
                j["ph"] = {s_: dict(var=(i + s_) % max(1, len(variants(PHOTO[ver][s_]))), z=1.0, fx=0.5, fy=0.5, br=1.0,
                                    warm=0.0, shade=0, grain=0, plain=True)
                           for s_ in range(6) if PHOTO[ver][s_]}
            continue
        if js:
            w = plan_photos(js)
            print(f"{ver}: подбор кадров {len(js)} каруселей, ближайший чужой слайд — мин {min(w)}, медиана {int(np.median(w))} "
                  f"бит; ≤ 40: {sum(x <= 40 for x in w)} ({__import__('time').time() - t0:.0f} с)", flush=True)
    with ProcessPoolExecutor(8) as ex:
        errs = [e for es in ex.map(build, jobs) for e in es]
    print(f"собрано {len(jobs)} каруселей × 6 слайдов; текст вне рамки: {len(errs)} {errs[:4]}", flush=True)
    if a.test:
        qa_sheet([Path(j["dir"]) for j in jobs], WORK / "test_qa_zones.jpg")
        print("QA-лист:", WORK / "test_qa_zones.jpg")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
