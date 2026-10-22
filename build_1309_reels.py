#!/usr/bin/env python3
"""
1309 — OneState «люди не верят, что это игра на телефоне»: 9:16, 15 с, три слоя как на скрине-референсе
(белый фон): подпись сверху (чёрный текст, дословно из ТЗ, переносы по смыслу) → геймплей OneState по центру →
скриншот «комментария» в стиле X/Twitter снизу (аватар, имя, @ник, «···», текст из ТЗ), выезжает снизу на 1-й с.
Баннер с промокодом STATE9CNL (готовый файл клиента, версия с озвучкой, своя анимация: влёт → $10,000 → уход)
— в середине ролика поверх геймплея. Логотип OneState в каждом ролике: угол геймплея случайный, сдвиг и размер
чуть разные. Звук — футаж (музыка), под озвучку баннера приглушается, итог −14 LUFS.

Футаж (downloads/1309/footage, 1920×1080 60 к/с): 3 ролика, в конце — заставка с логотипом (вырезаем);
ролик = 3 куска по 5 с из разных роликов, кусок начинается со склейки футажа и не обрывается сразу после склейки.
Комментаторы — выдуманные имена/ники и аватары-картинки без лиц (наши пулы), не реальные люди.

  python build_1309_reels.py --test            # 6 роликов → output/1309_test
  python build_1309_reels.py --count 500 --jobs 4
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402  (Apple-эмодзи в строке)
from core.safe_zones import check_overlay, text_rect  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
ID = "1309"
W, H, FPS, TOTAL = 1080, 1920, 60, 11.0                # клиент: ровно 11 с
X0, Y0, X1, Y1 = text_rect(W, H)                     # 140, 200, 940, 1540
D = ROOT / "downloads" / "1309"
FOOT = D / "footage"
BANNER = D / "banner" / "Promo code with voiceover, STATE9CNL.mov"
LOGO = D / "logo" / "Copy of logo_horizontal_color_2048.png"
FONTS = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf"
# шрифты как на скрине-референсе: подпись — TikTok «Classic» (Proxima Nova Semibold) → бесплатный двойник Figtree 600;
# комментарий — скрин из Twitter на iPhone (SF Pro) → двойник Inter
F_CAP = ROOT / "fonts" / "ig_lookalike" / "Figtree.ttf"
F_REG, F_BOLD = ROOT / "fonts" / "inter" / "Inter-Regular.ttf", ROOT / "fonts" / "inter" / "Inter-Bold.ttf"
F_MED = F_CAP
NL = chr(10)

# рабочая часть футажа (с конца — заставка с логотипом OneState)
USABLE = {
    "OS_VP_Paired_Animation_02_1920x1080_34s_1": 30.6,
    "OS_VP_World_Interaction2_02_1920x1080_37s": 34.2,
    "OS_VP_World_Interaction_02_1920x1080_31s": 27.8,
}
PIECE = 5.0
# подписи и комментарии ТЗ дословно; переносы — по смыслу
CAPTIONS = [
    ["people online lost it after seeing", "the new graphics in this game 🔥👀"],
    ["nobody expected a mobile game", "to look like this"],
    ["this update broke", "the comment section"],
    ["people can’t believe", "this is running on a phone 👀"],
    ["nobody believes me when I say", "this is a phone game"],
]
COMMENTS = [
    ["me and my bro at 2am", "on a random Tuesday", "while the whole world sleeps 💀", "we don’t even have a plan,",
     "we’re just out here"],
    ["this is exactly what me and my bro", "look like at 2am", "pretending we have work tomorrow 😭"],
    ["me and my bro at 2am:", "“we’ll go to bed soon” 💀 it’s 5am"],
]
# выдуманные комментаторы (имя, ник)
PEOPLE = [  # выдуманные «живые» комментаторы (имя, ник) — как у обычных людей в X
    ('Kayleigh', 'kayleighmarie_'),
    ('jaylen 🦦', 'jaylenwilliamss'),
    ('Marcus Bell', 'marcusbell03'),
    ('tyler', 'tylerrr_21'),
    ('bri ✨', 'briannaxo__'),
    ('Devon W', 'devonwrites'),
    ('nae 🤍', 'naeeee'),
    ('Cam', 'camhendo'),
    ('Ethan Moore', 'ethanmoore7'),
    ('lex', 'lexxiiiii'),
    ('Josh 🏀', 'joshhoops23'),
    ('Destiny', 'destinyyy04'),
    ("D'Andre", 'dandre_j'),
    ('kenny', 'kennyfromtx'),
    ('jas 🌙', 'jasminelol'),
    ('Mike Rivera', 'mikerivera88'),
    ('Taylor', 'taylorrgrace'),
    ('Zay', 'zay4real'),
    ('Bryce', 'bryce_h02'),
    ('mel 🌸', 'melissaaa_r'),
    ('Trevor', 'trevorhayes12'),
    ('Jalen', 'jalenbrooks1'),
    ('KJ', 'kj_thompson'),
    ('Sami', 'samiyahh'),
    ('ari 🎧', 'arii_m'),
    ('Dom', 'domthegreat_'),
    ('Lily Nguyen', 'lilynguyenn'),
    ('nate', 'natesmithh'),
    ('Chris B', 'chrisbaker_10'),
    ('Marisol', 'marisol_g'),
    ('Tre', 'trejackson5'),
    ('gabby', 'gabbbyy_l'),
    ('Ty', 'tyrell_moss'),
    ('Jordan', 'jordanfromla'),
    ('Aaliyah 💕', 'aaliyahhhxo'),
    ('Ryan K', 'ryankelly_'),
    ('brandon', 'brandonnn_17'),
    ('Mia', 'miasantos__'),
    ('Isaiah', 'isaiahdavis4'),
    ('kev', 'kevinlee99'),
    ('Hailey', 'haileyy_b'),
    ('Malik', 'malikjames_'),
    ('Andre', 'dre_carter'),
    ('Sofia R', 'sofiarodriguezz'),
    ('Logan', 'logan_ross4'),
    ('Kiara 🦋', 'kiaraaa_m'),
    ('Jake', 'jakemiller_01'),
    ('Tiana', 'tianaaa__'),
    ('Xavier', 'xavier_ortiz7'),
    ('Riley', 'rileyy_jo'),
    ('Omar', 'omarr_k'),
    ('Gabe', 'gabe_martinez'),
    ('leah', 'leahhpaige'),
    ('Eli', 'eli_wright3'),
    ('Jasmine', 'jasminetaylorr'),
    ('Darius', 'dariusmcc'),
    ('savannah 🤠', 'savvyrae'),
    ('Noah', 'noahbrown_22'),
    ('Cole', 'colewalker01'),
    ('Brianna', 'bri_washington'),
]
AVATAR_DIRS = [D / "avatars"]                         # пул «живых» аватарок без лиц (harvest pfp_1309)
CAP_TOP, CAP_PX, CMT_PX = 214, 52, 44
CARD_BOTTOM = Y1 - 8
AVATAR, GAP = 104, 34
T_CARD, CARD_DUR = 1.0, 0.45                         # комментарий выезжает снизу
BANNER_T = TOTAL / 2 - 2.8                           # озвучка 5.6 с — по центру ролика
BANNER_SCALE = 0.8                                   # баннер клиента во всю ширину → 80 %, с полями (как в примере)
GREY = (101, 119, 134)


# ---------------- текст ----------------
def font(path: Path, px: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(path), px)
    if path == F_CAP:                                   # вариативный Figtree → SemiBold
        f.set_variation_by_axes([600])
    return f


def line_w(line: str, f: ImageFont.FreeTypeFont, px: int) -> float:
    return sum(A._chunk_width(c, k, f, px, 0) for k, c in A._tokenize_runs(line))


def draw_line(img: Image.Image, x: float, top: float, line: str, f: ImageFont.FreeTypeFont, px: int, fill) -> None:
    d = ImageDraw.Draw(img)
    base = top + f.getmetrics()[0]
    for kind, chunk in A._tokenize_runs(line):
        if kind == "emoji":
            e = A._apple_emoji_rgba(chunk, A._emoji_px(px))
            if e is not None:
                img.alpha_composite(e, (int(x), int(base - e.height * 0.84)))
        else:
            d.text((x, base), chunk, font=f, anchor="ls", fill=fill)
        x += A._chunk_width(chunk, kind, f, px, 0)


def fit_px(lines: list[str], path: Path, px_max: int, max_w: int) -> int:
    return next(p for p in range(px_max, 20, -1) if max(line_w(ln, font(path, p), p) for ln in lines) <= max_w)


def caption_png(k: int, dest: Path) -> int:
    lines = CAPTIONS[k]
    px = fit_px(lines, F_MED, CAP_PX, X1 - X0)
    f, adv = font(F_MED, px), int(px * 1.24)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for i, ln in enumerate(lines):
        draw_line(img, X0, CAP_TOP + i * adv, ln, f, px, (0, 0, 0, 255))
    bad = check_overlay(img)
    if bad:
        raise SystemExit(f"подпись {k + 1} вне зоны: {bad}")
    img.save(dest)
    return CAP_TOP + len(lines) * adv


def avatar(path: Path, side: int) -> Image.Image:
    im = ImageOps.fit(Image.open(path).convert("RGB"), (side * 2, side * 2), Image.Resampling.LANCZOS)
    m = Image.new("L", (side * 2, side * 2), 0)
    ImageDraw.Draw(m).ellipse([0, 0, side * 2 - 1, side * 2 - 1], fill=255)
    im = im.convert("RGBA")
    im.putalpha(m)
    return im.resize((side, side), Image.Resampling.LANCZOS)


def card_png(k: int, person: tuple[str, str], av: Path, dest: Path) -> int:
    """Карточка комментария (как скрин из X): аватар, имя жирным, @ник серым, «···», текст. Возвращает высоту."""
    lines = COMMENTS[k]
    px = fit_px(lines, F_REG, CMT_PX, X1 - X0)
    f, adv = font(F_REG, px), int(px * 1.3)
    h = AVATAR + 26 + len(lines) * adv
    img = Image.new("RGBA", (W, h + 10), (0, 0, 0, 0))
    img.alpha_composite(avatar(av, AVATAR), (X0, 0))
    name, handle = person
    tx = X0 + AVATAR + 24
    draw_line(img, tx, 10, name, font(F_BOLD, 38), 38, (15, 20, 25, 255))
    draw_line(img, tx, 58, "@" + handle, font(F_REG, 33), 33, GREY + (255,))
    d = ImageDraw.Draw(img)
    for i in range(3):                                # «···» справа
        cx = X1 - 8 - i * 14
        d.ellipse([cx - 3.5, 30, cx + 3.5, 37], fill=GREY + (255,))
    for i, ln in enumerate(lines):
        draw_line(img, X0, AVATAR + 26 + i * adv, ln, f, px, (15, 20, 25, 255))
    img.save(dest)
    return h


def logo_png(rng: random.Random, band: tuple[int, int], dest: Path) -> tuple[int, int, int]:
    """Логотип — левый нижний угол геймплея (фидбек клиента); ширина 180–205 px и отступ чуть разные."""
    lg = Image.open(LOGO).convert("RGBA")
    lg = lg.crop(lg.getchannel("A").getbbox())
    w = rng.randint(180, 205)
    lg = lg.resize((w, round(lg.height * w / lg.width)), Image.Resampling.LANCZOS)
    # сильная мягкая тёмная тень под логотипом — читается на любом фоне (клиент: «иногда не видно»)
    pad = 26
    a = Image.new("L", (lg.width + 2 * pad, lg.height + 2 * pad), 0)
    a.paste(lg.getchannel("A"), (pad, pad))
    a = a.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(11)).point(lambda v: min(255, int(v * 0.95)))
    sh = Image.new("RGBA", a.size, (0, 0, 0, 0))
    sh.putalpha(a)
    sh.alpha_composite(lg, (pad, pad))
    sh.save(dest)
    lg = sh
    x = rng.randint(14, 24) - pad                              # в самом углу кадра (клиент: без рамки безопасной зоны)
    y = band[1] - lg.height + pad - rng.randint(14, 22)
    return x, y, x + lg.width - pad


# ---------------- баннер (без озвучки): своя анимация появления/ухода ----------------
BANNER_ANIM = D / "banner" / "_banner_noVO_anim.mov"
B_CROP = (40, 820, 1040, 1100)                        # плашка в кадре баннера 1080×1920 (+ поля под свечение)
B_W = 540                                             # ширина плашки в ролике (рядом с логотипом)
B_POP, B_OUT = 0.32, 0.25


def banner_anim() -> tuple[int, int]:
    """Один раз: плашка из «NO voiceover» (в файле клиента без анимации входа) → влёт с пружиной + уход прозрачностью."""
    bw = B_W
    bh = round((B_CROP[3] - B_CROP[1]) * bw / (B_CROP[2] - B_CROP[0]))
    cw, ch = round(bw * 1.12 / 2) * 2, round(bh * 1.12 / 2) * 2
    if BANNER_ANIM.exists():
        return cw, ch
    src = D / "banner" / "Promo code with NO voiceover, STATE9CNL.mov"
    dec = subprocess.Popen([FF, "-v", "error", "-i", str(src), "-vf", f"fps={FPS},crop={B_CROP[2] - B_CROP[0]}:"
                            f"{B_CROP[3] - B_CROP[1]}:{B_CROP[0]}:{B_CROP[1]}", "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                           stdout=subprocess.PIPE)
    fw, fh = B_CROP[2] - B_CROP[0], B_CROP[3] - B_CROP[1]
    fs = fw * fh * 4
    n = round(float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                                   capture_output=True, text=True).stdout) * FPS)
    enc = subprocess.Popen([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{cw}x{ch}", "-r",
                            str(FPS), "-i", "-", "-c:v", "png", str(BANNER_ANIM)], stdin=subprocess.PIPE)
    for k in range(n):
        t = k / FPS
        buf = dec.stdout.read(fs)
        if len(buf) < fs:
            break
        fr = Image.frombuffer("RGBA", (fw, fh), buf)
        u = min(1.0, t / B_POP)
        sc = 0.55 + 1.0 * u if u < 0.5 else 1.05 - 0.1 * (u - 0.5)       # 0.55 → 1.05 → 1.0
        a = min(1.0, t / 0.12) * min(1.0, max(0.0, (n / FPS - t) / B_OUT))
        w, h = max(2, round(bw * sc)), max(2, round(bh * sc))
        im = fr.resize((w, h), Image.Resampling.LANCZOS)
        if a < 1:
            im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
        can = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        can.alpha_composite(im, ((cw - w) // 2, (ch - h) // 2))
        enc.stdin.write(can.tobytes())
    enc.stdin.close()
    enc.wait()
    return cw, ch


# ---------------- футаж: целые моменты (downloads/1309/scenes) ----------------
SCENES = D / "scenes"
MIN_LAST = 1.5                                        # последний момент обрезается до остатка 15 с, но не короче 1.5 с


def moments() -> list[dict]:
    return json.loads((SCENES / "_index.json").read_text(encoding="utf-8"))


# ---------------- план ----------------
NEW_VIDEO_FROM = 0       # с этого номера видеоряд (набор моментов) не повторяет ни один из предыдущих роликов


def plan(count: int) -> list[dict]:
    """Ролик = подряд целые моменты (разные), последний обрезан, чтобы вышло ровно TOTAL с."""
    rng = random.Random(1309)
    mom = moments()
    avatars = [p for d in AVATAR_DIRS if d.is_dir() for p in sorted(d.glob("*.jpg")) if not p.name.startswith("_")]
    rng.shuffle(avatars)
    use: dict = {}
    seen: set = set()
    seen_video: set = set()
    jobs = []
    for n in range(count):
        cap, cmt = n % len(CAPTIONS), (n // len(CAPTIONS)) % len(COMMENTS)
        for _ in range(500):
            order = sorted(range(len(mom)), key=lambda i: use.get(i, 0) + rng.random() * 3)
            seq, total = [], 0.0
            for i in order:
                rem = TOTAL - total
                d = mom[i]["dur"]
                if d < rem - 1e-6:
                    if rem - d < MIN_LAST:                    # иначе остаток выйдет крошечным
                        continue
                    seq.append([i, d])
                    total += d
                elif rem >= MIN_LAST:
                    seq.append([i, round(rem, 3)])
                    total = TOTAL
                    break
            if abs(total - TOTAL) > 1e-3:
                continue
            key = (cap, cmt, tuple(tuple(x) for x in seq))
            vkey = tuple(tuple(x) for x in seq)
            if key not in seen and not (NEW_VIDEO_FROM and n >= NEW_VIDEO_FROM and vkey in seen_video):
                break
        seen.add(key)
        seen_video.add(tuple(tuple(x) for x in seq))
        for i, _d in seq:
            use[i] = use.get(i, 0) + 1
        jobs.append({"n": n + 1, "caption": cap, "comment": cmt,
                     "moments": [[mom[i]["file"], d] for i, d in seq],
                     "person": list(PEOPLE[n % len(PEOPLE)]), "avatar": str(avatars[n % len(avatars)]),
                     "seed": rng.randint(0, 10 ** 6)})
    return jobs


# ---------------- рендер ----------------
MUSIC = D / "music" / "music_53-64s_-14lufs.wav"     # Instagram audio 423866028123501, 0:53–1:04 (11 с), −14 LUFS; звук футажа = 0


def build(job: dict) -> str:
    work = Path(tempfile.mkdtemp(prefix="r1309_"))
    rng = random.Random(job["seed"])
    cap_png, card, logo = work / "cap.png", work / "card.png", work / "logo.png"
    cap_bottom = caption_png(job["caption"], cap_png)
    card_h = card_png(job["comment"], tuple(job["person"]), Path(job["avatar"]), card)
    card_top = CARD_BOTTOM - card_h
    band = (cap_bottom + GAP, card_top - GAP)
    bh = band[1] - band[0]
    bh -= bh % 2
    lx, ly, lright = logo_png(rng, (band[0], band[0] + bh), logo)
    cw, ch = banner_anim()
    bx = (W - cw) // 2                                    # промокод — ровно по центру по горизонтали
    by = band[0] + bh - 16 - ch + round(ch * 0.06)       # низ плашки — у нижнего края геймплея
    inputs, parts = [], []
    for k, (name, d) in enumerate(job["moments"]):
        inputs += ["-i", str(SCENES / name)]
        parts.append(f"[{k}:v]fps={FPS},scale=-2:{bh}:flags=lanczos,crop={W}:{bh},trim=duration={d:.4f},"
                     f"setpts=PTS-STARTPTS,setsar=1[v{k}]")
    nm = len(job["moments"])
    inputs += ["-loop", "1", "-i", str(cap_png), "-loop", "1", "-i", str(card), "-loop", "1", "-i", str(logo),
               "-i", str(BANNER_ANIM), "-i", str(MUSIC)]
    ic, ik, il, ib = nm, nm + 1, nm + 2, nm + 3
    comma = "\\,"
    ease = f"pow(1-min(1{comma}max(0{comma}(t-{T_CARD})/{CARD_DUR})){comma}3)"
    bt = TOTAL / 2 - 4.0                                  # баннер 8 с — по центру ролика
    parts += [
        "".join(f"[v{k}]" for k in range(nm)) + f"concat=n={nm}:v=1:a=0[g]",
        f"color=white:s={W}x{H}:r={FPS}:d={TOTAL}[bg]",
        f"[bg][g]overlay=0:{band[0]}:shortest=1[s1]",
        f"[s1][{il}:v]overlay={lx}:{ly}[s2]",
        f"[s2][{ic}:v]overlay=0:0:shortest=1[s3]",
        f"[s3][{ik}:v]overlay=0:{card_top}:shortest=1[s4]",                      # комментарий без анимации (клиент)
        f"[{ib}:v]fps={FPS},format=yuva420p,setpts=PTS-STARTPTS+{bt:.3f}/TB[bn]",
        f"[s4][bn]overlay={bx}:{by}:eof_action=pass,format=yuv420p,{SET_SDR}[v]",
    ]
    out = Path(job["out"])
    dest = out / f"{job['n']:03d}_{ID}.mp4"
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[v]", "-map", f"{ib + 1}:a",
                    "-t", f"{TOTAL}", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(FPS),
                    *SDR_COLOR_ARGS, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dest)], check=True)
    return f"{dest.name}: подпись {job['caption'] + 1}, комм. {job['comment'] + 1}, моментов {nm}, {job['person'][0]}"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=500)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--from", dest="start", type=int, default=0, help="собрать только ролики с номером > N (доп. партия)")
    ap.add_argument("--out", default=None, help="папка в output/")
    args = ap.parse_args()
    banner_anim()                                         # один раз до параллельной сборки
    global NEW_VIDEO_FROM
    NEW_VIDEO_FROM = args.start
    jobs = plan(args.count)
    if args.test:
        jobs = [j for j in jobs if j["n"] in (1, 7, 13, 4, 10, 15)]   # все 5 подписей и 3 комментария
    if args.start:
        jobs = [j for j in jobs if j["n"] > args.start]
    out = ROOT / "output" / (args.out or (f"{ID}_test7" if args.test else f"{ID}_{args.count}"))
    out.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        j["out"] = str(out)
    if not args.test:
        (out / "manifest.json").write_text(json.dumps(jobs, indent=1, ensure_ascii=False), encoding="utf-8")
    with ProcessPoolExecutor(args.jobs) as ex:
        for k, msg in enumerate(ex.map(build, jobs), 1):
            print(f"[{k}/{len(jobs)}] {msg}", flush=True)
    print("готово →", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
