"""VIBE CITY — «эмоции игрока в моменте»: геймплей Vibe City + голос бразильского стримера (ElevenLabs, pt-BR), субтитры pt-BR
снизу, хук сверху с первого кадра, перебивка «EBRABO / Código na descrição 👇» в середине. ТЗ 17.11: 250 YT + 150 TT, ID 1.

Сцены и тексты: output/_work/vibecity/scenes.json (13 текстов: t1–t5 клиента дословно, t6–t13 наши; окна, куски, биты
«фраза → что на экране → время в ролике»). Голос: downloads/vibecity/vo/vc_tNN*.mp3 (утро 18.11, ElevenLabs); пока их нет —
временный голос Microsoft (edge-tts pt-BR-AntonioNeural) только для отладки монтажа.

Монтаж от голоса: каждая фраза ложится на свой бит картинки — длины кусков подгоняются (скорость всегда 1, тянется/режется
хвост куска), паузы геймплея не нужны. Рецепт сборки — CLAUDE.md: cuvid обрезает окно 9:16 и увеличивает → кадры в памяти →
склейка → стоп-кадр под промокод → слои обычным overlay → NVENC. Проверка: каждый кадр полосы без текста = кадр исходника
по плану; отпечатки — core.clip_batch (≤ 2 общих кадров в обе стороны).

  python build_vibecity.py --test            # по тесту на каждый текст → output/vibecity_test
  python build_vibecity.py --tt 150 --yt 250 # партия → output/vibecity_1_TT_150, vibecity_1_YT_250
"""
from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import math
import random
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import gpu_ffmpeg as G  # noqa: E402
from core.safe_zones import check_box  # noqa: E402

W, H, FPS, SR = 1080, 1920, 30, 48000
D = ROOT / "downloads" / "vibecity"
SRC = D / "src"
VO = D / "vo"
WORK = ROOT / "output" / "_work" / "vibecity"
SW, SH = 2556, 1180
SFX = ROOT / "downloads" / "drops_beats" / "sfx"
FONT = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf" / "TikTokSans12pt-Black.ttf"
FONT_B = ROOT / "fonts" / "TikTokSans" / "TikTokSans-v4.000" / "fonts" / "ttf" / "TikTokSans12pt-ExtraBold.ttf"
SCENES = {e["id"]: e for e in json.loads((WORK / "scenes.json").read_text(encoding="utf-8"))}
# общий список хуков ТЗ — дословно
HOOKS_ALL = ["QUE ISSO, MANO? KKKKK", "O QUE TÁ ACONTECENDO AQUI? KKKK", "MANO, ONDE EU VIM PARAR?",
             "EU SÓ QUERIA JOGAR DE BOA…", "O DIA MAIS NORMAL NO VIBE CITY", "NÃO TEM UM MINUTO DE PAZ KKKK",
             "COMO EU FUI PARAR NESSA SITUAÇÃO?", "ESSA GALERA NÃO EXISTE KKKKK", "ERA PRA SER SÓ UMA VOLTINHA…",
             "OLHA A IDEIA DO MALUCO KKKK", "EU NÃO TÔ ACREDITANDO NISSO KKKK", "TAVA TUDO INDO TÃO BEM…",
             "É CADA UMA QUE ME ACONTECE…", "FUI INVENTAR DE CONFIAR NO CARA…", "ALGUÉM ME EXPLICA ESSA CENA KKKK"]
BAND = (560, 1248)                                        # полоса без текста: ниже хука, выше субтитров — для сверки
PROMO_LEN = 1.3
BSIZE = (136, 86)                                         # полоса сверки в 1/8, чётная (распаковщик видеокарты)
STOP_PT = {"o", "a", "os", "as", "um", "uma", "de", "do", "da", "e", "e", "que", "na", "no", "pra", "se", "te", "me", "eu", "tu", "nem", "com", "em", "por", "ao", "ta", "to"}


# ---------------- текст ----------------
def font(px: int, path: Path = FONT) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), px)


def wrap(lines: list[str], f, max_w: int) -> list[str]:
    out = []
    for ln in lines:
        if f.getlength(ln) <= max_w or " " not in ln:
            out.append(ln)
            continue
        ws = ln.split()
        k = min(range(1, len(ws)), key=lambda i: abs(f.getlength(" ".join(ws[:i])) - f.getlength(" ".join(ws[i:]))))
        out += wrap([" ".join(ws[:k]), " ".join(ws[k:])], f, max_w)
    return out


def text_png(lines: list[str], px: int, top: int, fill=(255, 255, 255), stroke: float = 0.11, max_w: int = 790,
             min_px: int = 64) -> Image.Image:
    """Белый текст с ровной чёрной обводкой (как в нативных шортсах), по центру; не шире безопасной зоны."""
    while px > min_px and max(font(px).getlength(ln) for ln in lines) + 2 * max(3, round(px * stroke)) > max_w:
        px -= 2
    f = font(px)
    st = max(3, round(px * stroke))
    lines = wrap(lines, f, max_w - 2 * st)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    asc, _ = f.getmetrics()
    for i, ln in enumerate(lines):
        d.text((W / 2, top + i * round(px * 1.12) + asc), ln, font=f, anchor="ms", fill=fill + (255,), stroke_width=st,
               stroke_fill=(0, 0, 0, 255))
    return img


def hook_lines(h: str) -> list[str]:
    """Логичный перенос хука: по запятой/«?», иначе пополам по смыслу (wrap)."""
    m = re.match(r"^(.+?[,?])\s+(.+)$", h)
    return [m.group(1), m.group(2)] if m and len(h) > 18 else [h]


def top_shade(img: Image.Image, y1: int) -> Image.Image:
    """Мягкое затемнение сверху под хуком (чат и уведомления игры под текстом — каша): 45 % → 0 к y1."""
    a = np.zeros((H, 1), np.float32)
    a[:y1, 0] = np.linspace(0.62, 0.0, y1) ** 1.2
    sh = Image.fromarray(np.dstack([np.zeros((H, W, 3), np.uint8), (np.repeat(a, W, 1) * 255).astype(np.uint8)]), "RGBA")
    return Image.alpha_composite(sh, img)


def promo_png(dest: Path) -> None:
    """Перебивка: затемнение + плашка «EBRABO / Código na descrição 👇» по центру безопасной зоны."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 125))
    d = ImageDraw.Draw(img)
    bw, bh = 780, 360
    x0, y0 = (W - bw) // 2, 760
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=46, fill=(255, 196, 0, 250), outline=(20, 20, 20, 255), width=6)
    d.text((W / 2, y0 + 168), "EBRABO", font=font(160), anchor="ms", fill=(20, 20, 20, 255))
    f2 = font(58, FONT_B)
    t2 = "Código na descrição"
    w2 = f2.getlength(t2)
    d.text(((W - w2 - 70) / 2, y0 + 268), t2, font=f2, anchor="ls", fill=(20, 20, 20, 255))
    emo = ROOT / "assets" / "emoji_apple_160" / "1f447.png"
    if emo.exists():
        e = Image.open(emo).convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
        img.alpha_composite(e, (int((W - w2 - 70) / 2 + w2 + 6), y0 + 214))
    else:
        cx, cy = (W - w2 - 70) / 2 + w2 + 40, y0 + 248
        d.polygon([(cx - 22, cy - 20), (cx + 22, cy - 20), (cx, cy + 16)], fill=(20, 20, 20, 255))
    assert not check_box(W, H, (x0, y0, x0 + bw, y0 + bh))
    img.save(dest)


def light_png(rng: random.Random, dest: Path, amp: float = 0.035) -> Image.Image:
    """Мягкое «поле света» по сетке отпечатка (17×16) + волны: у каждого ролика своё — для несхожести, на глаз почти не видно."""
    w4, h4 = W // 4, H // 4
    x = np.linspace(0, 1, w4, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, h4, dtype=np.float32)[:, None]
    wave = np.sin(2 * math.pi * rng.uniform(1.0, 2.5) * x + y * rng.uniform(-5, 5) + rng.uniform(0, 6.28))
    cell = np.asarray(Image.fromarray(np.random.default_rng(rng.randrange(2 ** 32)).random((16, 17), dtype=np.float32), "F")
                      .resize((w4, h4), Image.Resampling.BICUBIC), np.float32)
    v = 0.5 * amp * wave + amp * (cell * 2 - 1)
    v = np.asarray(Image.fromarray(v.astype(np.float32), "F").resize((W, H), Image.Resampling.BILINEAR), np.float32)
    a = (np.abs(v) * 255).clip(0, 255).astype(np.uint8)
    rgb = np.where(v[..., None] > 0, 255, 0).astype(np.uint8).repeat(3, 2)
    im = Image.fromarray(np.dstack([rgb, a]), "RGBA")
    im.save(dest, compress_level=1)
    return im


# ---------------- голос ----------------
def norm(w: str) -> str:
    w = unicodedata.normalize("NFKD", w.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in w if not unicodedata.combining(c)))


def tts_placeholder(tid: str) -> tuple[Path, list]:
    """Временный голос (только для отладки до ElevenLabs): edge-tts pt-BR-AntonioNeural + тайминг слов."""
    import edge_tts
    d = WORK / "tts"
    d.mkdir(parents=True, exist_ok=True)
    mp3, js = d / f"{tid}.mp3", d / f"{tid}.json"
    if not (mp3.exists() and js.exists()):
        async def go():
            c = edge_tts.Communicate(SCENES[tid]["text"], "pt-BR-AntonioNeural", rate="+12%", boundary="WordBoundary")
            words, audio = [], bytearray()
            async for ch in c.stream():
                if ch["type"] == "audio":
                    audio += ch["data"]
                elif ch["type"] == "WordBoundary":
                    words.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]))
            mp3.write_bytes(bytes(audio))
            js.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
        asyncio.run(go())
    return mp3, json.loads(js.read_text(encoding="utf-8"))


_ASR = None


def asr_words(path: Path) -> list:
    """Слова с таймингом для файла ElevenLabs (whisper-large-v3-turbo, кэш рядом)."""
    global _ASR
    js = path.with_suffix(".words.json")
    if js.exists():
        return json.loads(js.read_text(encoding="utf-8"))
    import os
    import torch
    from transformers import pipeline
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    if _ASR is None:
        _ASR = pipeline("automatic-speech-recognition", model="openai/whisper-large-v3-turbo", device=0,
                        torch_dtype=torch.float16)
    a = load_audio(path, mono16=True)
    r = _ASR({"raw": a, "sampling_rate": 16000}, return_timestamps="word",
             generate_kwargs={"language": "portuguese", "task": "transcribe"})
    ws = [(c["timestamp"][0] or 0, c["timestamp"][1] or (c["timestamp"][0] or 0) + 0.2, c["text"].strip())
          for c in r["chunks"]]
    js.write_text(json.dumps(ws, ensure_ascii=False), encoding="utf-8")
    return ws


def voice_takes(tid: str) -> list[Path]:
    n = int(tid[1:])
    return sorted(VO.glob(f"vc_t{n:02d}*.mp3"))


def script_times(tid: str, take: Path | None) -> tuple[Path, list[tuple[float, float, str]]]:
    """Слова сценария (дословно, без тегов) с временем в файле голоса: сопоставление с распознанными словами."""
    if take is None:
        audio, rec = tts_placeholder(tid)
    else:
        audio, rec = take, asr_words(take)
    script = SCENES[tid]["text"].split()
    a = [norm(w) for w in script]
    b = [norm(w[2]) for w in rec]
    t = [None] * len(script)
    for blk in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for i in range(blk.size):
            t[blk.a + i] = (rec[blk.b + i][0], rec[blk.b + i][1])
    known = [i for i, x in enumerate(t) if x]
    for i in range(len(t)):                                   # пропущенные — между соседями
        if t[i] is None:
            lo = max([k for k in known if k < i], default=None)
            hi = min([k for k in known if k > i], default=None)
            t0 = t[lo][1] if lo is not None else 0.0
            t1 = t[hi][0] if hi is not None else t0 + 0.4
            n_gap = (hi if hi is not None else len(t)) - (lo if lo is not None else -1) - 1
            pos = i - (lo if lo is not None else -1)
            step = max(0.05, (t1 - t0) / (n_gap + 1))
            t[i] = (t0 + step * (pos - 1), t0 + step * pos)
    return audio, [(t[i][0], t[i][1], script[i]) for i in range(len(script))]


# ---------------- звук ----------------
def load_audio(path: Path, t0: float = 0.0, dur: float | None = None, mono16: bool = False) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{t0:.4f}", "-i", str(path)] + (["-t", f"{dur:.4f}"] if dur else [])
    if mono16:
        cmd += ["-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
        return np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.float32).copy()
    cmd += ["-vn", "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.float32).reshape(-1, 2).copy()


# ---------------- план ----------------
def plan(rng: random.Random, tid: str, wi: int | None = None, take: Path | None = None, hook: str | None = None) -> dict:
    """Ролик: окно сцены, куски (подогнаны под голос), голос, субтитры, перебивка EBRABO в середине."""
    sc = SCENES[tid]
    wi = rng.randrange(len(sc["windows"])) if wi is None else wi
    w = sc["windows"][wi]
    takes = voice_takes(tid)
    take = take if take is not None else (rng.choice(takes) if takes else None)
    audio, words = script_times(tid, take)
    lead = round(rng.uniform(0.15, 0.3), 2)                 # голос с первой ~0.2 с, хук с первого кадра
    # начало каждой фразы бита в голосе
    lines = [b["line"] for b in w["beats"]]
    starts, k = [], 0
    for ln in lines:
        n = len(ln.split())
        starts.append(words[min(k, len(words) - 1)][0])
        k += n
    v_end = words[-1][1]
    # опорные точки: время бита в старом монтаже → время его фразы в голосе (+lead); кусок тянется/режется хвостом
    old_t = [0.0] + [b["edit_t"] for b in w["beats"]]
    new_t = [0.0] + [lead + s for s in starts]
    segs = w["segments"]
    old_len = [s["end"] - s["start"] for s in segs]
    old_end = sum(old_len)
    old_t.append(old_end)
    new_t.append(lead + v_end + 0.55)
    for i in range(1, len(new_t)):                            # монотонно
        new_t[i] = max(new_t[i], new_t[i - 1] + 0.05)
        old_t[i] = max(old_t[i], old_t[i - 1] + 0.05)
    f = lambda x: float(np.interp(x, old_t, new_t))         # noqa: E731
    pcs, o = [], 0.0
    zoom = round(rng.uniform(1.0, 1.1), 3)
    jx = rng.uniform(-0.025, 0.025)
    for j, s in enumerate(segs):
        a_old, b_old = o, o + old_len[j]
        o = b_old
        L = max(0.4, f(b_old) - f(a_old))
        st = s["start"] + rng.uniform(0, min(0.15, max(0.0, old_len[j] - L)))
        n = max(12, round(L * FPS))
        pcs.append(dict(src=s["src"], t=round(st, 3), n=n, x=min(0.95, max(0.05, s.get("x", w.get("hero_x", 0.5)) + jx)),
                        punch=(j % 2 == 1)))
    nf_v = sum(p["n"] for p in pcs)
    total_v = nf_v / FPS
    # EBRABO: в середине, в паузе между фразами (40–60 % ролика)
    gaps = [(lead + words[i][1], lead + words[i + 1][0]) for i in range(len(words) - 1)]
    cands = [g for g in gaps if 0.4 * total_v <= g[0] <= 0.6 * total_v]
    pg = max(cands, key=lambda g: g[1] - g[0]) if cands else min(gaps, key=lambda g: abs(g[0] - 0.5 * total_v))
    promo_t = min(pg[0] + 0.08, (pg[0] + pg[1]) / 2)
    promo_f = round(promo_t * FPS)
    promo_n = round(PROMO_LEN * FPS)
    shift = lambda t: t + (promo_n / FPS if t >= promo_t else 0.0)  # noqa: E731
    # субтитры: 1–3 слова, рвём на знаках
    subs, cur = [], []
    for wd in words:
        cur.append(wd)
        txt = " ".join(x[2] for x in cur)
        weak = norm(wd[2]) in STOP_PT and not re.search(r"[.!?…,]$", wd[2])   # не рвать на «o / de / é / que»
        if (len(cur) >= 3 and not weak) or len(cur) >= 5 or (len(txt) >= 18 and not weak) or re.search(r"[.!?…,]$", wd[2]):
            subs.append([shift(lead + cur[0][0]), shift(lead + cur[-1][1]), txt])
            cur = []
    if cur:
        subs.append([shift(lead + cur[0][0]), shift(lead + cur[-1][1]), " ".join(x[2] for x in cur)])
    for i in range(len(subs) - 1):
        subs[i][1] = subs[i + 1][0] if subs[i + 1][0] - subs[i][1] < 0.5 else subs[i][1] + 0.3
    subs[-1][1] += 0.4
    if hook is None:
        hook = sc["hook"] if rng.random() < 0.5 else rng.choice(HOOKS_ALL)
    return dict(tid=tid, wi=wi, take=str(audio), lead=lead, words=words, pcs=pcs, zoom=zoom,
                promo_f=promo_f, promo_n=promo_n, promo_t=promo_t, subs=subs, hook=hook,
                total=(nf_v + promo_n) / FPS, nf=nf_v + promo_n, light_seed=rng.randrange(10 ** 9),
                game_vol=round(rng.uniform(0.12, 0.2), 3), sfx=rng.choice(["swing_487667.mp3", "simple_382724.mp3"]))


def build_audio(pp: dict, dest: Path) -> None:
    """Голос стримера (громко), звук игры по тем же кускам (тихо), тишина на стоп-кадре, whoosh + pop на EBRABO."""
    n_total = round(pp["total"] * SR)
    game = np.concatenate([load_audio(SRC / p["src"], p["t"], p["n"] / FPS)[: round(p["n"] / FPS * SR)] for p in pp["pcs"]])
    pa, pn = round(pp["promo_f"] / FPS * SR), round(pp["promo_n"] / FPS * SR)
    game = np.concatenate([game[:pa], np.zeros((pn, 2), np.float32), game[pa:]])
    g = np.percentile(np.abs(game), 99) + 1e-6
    game *= pp["game_vol"] / g
    v = load_audio(Path(pp["take"]))
    vp = np.percentile(np.abs(v), 99.5) + 1e-6
    v *= 0.8 / vp
    va = round(pp["lead"] * SR)
    vt = np.zeros((n_total + SR, 2), np.float32)
    head = v[: max(0, pa - va)]
    tail = v[max(0, pa - va):]
    vt[va:va + len(head)] += head
    vt[pa + pn:pa + pn + len(tail)] += tail[: max(0, len(vt) - pa - pn)]
    mix = vt[:n_total].copy()
    mix[: min(len(game), n_total)] += game[: n_total]
    wh = load_audio(SFX / "whoosh" / pp["sfx"])[:SR]
    pop = load_audio(SFX / "pop" / "pop_402323.mp3")[: SR // 2]
    a0 = max(0, pa - len(wh) // 3)
    mix[a0:a0 + len(wh)] += wh[: max(0, n_total - a0)] * 0.45
    mix[pa + SR // 10:pa + SR // 10 + len(pop)] += pop[: max(0, n_total - pa - SR // 10)] * 0.55
    mix = (np.tanh(mix * 1.1) / np.tanh(1.1)).astype(np.float32)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", str(SR), str(dest)], input=mix.tobytes(), check=True)


def window_of(p: dict, zoom: float) -> tuple[int, int, int, int]:
    """Окно 9:16 в исходнике вокруг героя/машины (x — доля ширины), с зумом."""
    cw, ch = G._even(SH * 9 / 16 / zoom), G._even(SH / zoom)
    x = G._even(min(SW - cw, max(0, SW * p["x"] - cw / 2)))
    y = G._even((SH - ch) / 2)
    return x, y, cw, ch


PUNCH = 1.08



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


def layers(pp: dict, keep: Path) -> list:
    out = []
    lp = keep / "light.png"
    light_png(random.Random(pp["light_seed"]), lp)
    out.append((lp, 0.0, pp["total"] + 1))
    hk = text_png(hook_lines(pp["hook"]), 96, 226, min_px=80)
    assert not check_box(W, H, hk.getbbox()), "хук вне зоны"
    hk = top_shade(hk, min(H, hk.getbbox()[3] + 160))
    hk.save(keep / "hook.png")
    out.append((keep / "hook.png", 0.0, pp["total"] + 1))
    p0, p1 = pp["promo_f"] / FPS, (pp["promo_f"] + pp["promo_n"]) / FPS
    for i, (a, b, txt) in enumerate(pp["subs"]):
        if a < p1 and b > p0:
            if a < p0:
                b = p0
            else:
                a = max(a, p1)
        if b - a < 0.12:
            continue
        for top in (1420, 1380, 1340, 1300):              # 2 строки — чуть выше, но в безопасной зоне
            im = text_png([txt], 80, top)
            if not check_box(W, H, im.getbbox()):
                break
        assert not check_box(W, H, im.getbbox()), ("субтитр вне зоны", txt)
        p = keep / f"sub_{i:02d}.png"
        im.save(p)
        out.append((p, a, b))
    promo_png(keep / "promo.png")
    out.append((keep / "promo.png", p0, p1))
    return out


def render(pp: dict, dest: Path, keep: Path) -> Path:
    keep.mkdir(parents=True, exist_ok=True)
    build_audio(pp, keep / "a.wav")
    lays = layers(pp, keep)
    inputs, fc = [], []
    zc_w, zc_h = G._even(W / PUNCH), G._even(H / PUNCH)
    for i, p in enumerate(pp["pcs"]):
        z = pp["zoom"] * (PUNCH if p["punch"] else 1.0)          # «наезд» — окно поменьше прямо в распаковщике
        inputs += ["-ss", f"{p['t']:.4f}", "-t", f"{p['n'] / FPS + 0.4:.4f}",
                   *G.gpu_input(SRC / p["src"], crop=window_of(p, z), resize=(W, H))]
        head = f"[{i}:v]fps={FPS},setpts=PTS-STARTPTS,"
        fc.append(head + f"setsar=1,format=yuv420p,tpad=stop_mode=clone:stop={p['n'] + 2},trim=end_frame={p['n']},"
                  f"setpts=PTS-STARTPTS[s{i}]")
    k = len(pp["pcs"])
    fc.append("".join(f"[s{i}]" for i in range(k)) + f"concat=n={k}:v=1:a=0,loop=loop={pp['promo_n']}:size=1:"
              f"start={pp['promo_f']},setpts=N/{FPS}/TB,format=yuv420p[b0]")
    cur = "b0"
    for j, (png, a, b) in enumerate(lays):
        png, ox, oy = crop_layer(png)
        inputs += ["-i", str(png)]
        fc.append(f"[{k + 1 + j}:v]format=rgba[l{j}]")
        fc.append(f"[{cur}][l{j}]overlay={ox}:{oy}:enable='between(t,{a:.3f},{b:.3f})'[o{j}]")
        cur = f"o{j}"
    fc.append(f"[{cur}]format=yuv420p[v]")
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs[:0]]
    # порядок входов: куски (0..k-1), звук (k), слои (k+1..)
    seg_inputs = inputs[: len(inputs) - 2 * len(lays)]
    lay_inputs = inputs[len(inputs) - 2 * len(lays):]
    cmd = ["ffmpeg", "-v", "error", "-y", *seg_inputs, "-i", str(keep / "a.wav"), *lay_inputs,
           "-filter_complex", ";".join(fc), "-map", "[v]", "-map", f"{k}:a", "-frames:v", str(pp["nf"]), *G.NVENC,
           "-c:a", "aac", "-b:a", "160k", *G.CLEAN, str(dest)]
    from core.gpu_slots import gpu_slot
    with gpu_slot():
        r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-1500:])
    return dest


# ---------------- проверка ----------------
def frame_check(pp: dict, G_: np.ndarray, keep: Path, margin: float = 1.5, junk: float = 18.0) -> list:
    """Каждый кадр полосы BAND (без текста) = кадр исходника по плану (окно, зум, «наезд», свет); стоп-кадр EBRABO
    пропускается. Исходник читает тот же распаковщик видеокарты, что и сборка (-ss на кусок, обрезка+масштаб в нём)."""
    y0, y1 = BAND
    bw, bh = BSIZE
    lay = Image.open(keep / "light.png").crop((0, y0, W, y1)).resize((bw, bh), Image.Resampling.BOX)
    la = np.asarray(lay, np.float32)
    al, lg = la[..., 3] / 255, la[..., 0] * 0.299 + la[..., 1] * 0.587 + la[..., 2] * 0.114
    if len(G_) != pp["nf"]:
        return [("кадров", len(G_), pp["nf"])]
    flags, f = [], 0
    pf, pn = pp["promo_f"], pp["promo_n"]
    from core.gpu_slots import gpu_slot
    for p in pp["pcs"]:
        x, y, cw, ch = window_of(p, pp["zoom"] * (PUNCH if p["punch"] else 1.0))
        sy, sh_ = y + y0 * ch / H, (y1 - y0) * ch / H         # полоса BAND ролика → прямоугольник в исходнике
        pre = min(3, int(p["t"] * FPS))
        crop = (x, G._even(sy), cw, G._even(sh_))
        with gpu_slot():
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0, p['t'] - pre / FPS):.4f}",
                                  "-t", f"{(p['n'] + pre + 6) / FPS:.4f}",
                                  *G.gpu_input(SRC / p["src"], crop=crop, resize=(bw, bh)),
                                  "-vf", f"fps={FPS},format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        src = np.frombuffer(raw, np.uint8).reshape(-1, bh, bw).astype(np.float32)
        if not len(src):
            return [("исходник не прочитался", p["src"])]
        src = src * (1 - al) + lg * al
        for j in range(p["n"]):
            sj = f + j
            if sj == pf:
                continue
            oj = sj + (pn if sj > pf else 0)
            if oj >= len(G_):
                continue
            kk = min(pre + j, len(src) - 1)
            d = {dk: float(np.abs(G_[oj] - src[kk + dk]).mean()) for dk in range(-3, 4) if 0 <= kk + dk < len(src)}
            best = min(d, key=d.get)
            if d[best] > junk:
                flags.append((oj, "мусор", round(d[best], 1)))
            elif best != 0 and d[0] - d[best] > margin:
                flags.append((oj, best, round(d[0] - d[best], 2)))
        f += p["n"]
    return flags


def build(pp: dict, tmp: Path, keep: Path) -> tuple[bool, str, np.ndarray | None]:
    from core import clip_batch as CB
    render(pp, tmp, keep)
    G_, H_ = CB.decode(tmp, BAND, size=BSIZE)
    fr = frame_check(pp, G_, keep)
    if fr:
        return False, f"кадры не те {fr[:4]}", None
    return True, "", CB.hash_of(H_)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--tt", type=int, default=0)
    ap.add_argument("--yt", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=5)
    a = ap.parse_args()
    if a.test:
        out = ROOT / "output" / "vibecity_test"
        out.mkdir(parents=True, exist_ok=True)
        rng = random.Random(1811)
        for tid in (a.only or [f"t{i}" for i in range(1, 14)]):
            pp = plan(rng, tid, wi=0, hook=SCENES[tid]["hook"])
            keep = WORK / "test" / tid
            dest = out / f"vibecity_test_{tid}_1.mp4"
            ok, why, h = build(pp, dest, keep)
            print(f"{dest.name}: {pp['total']:.1f} с, кусков {len(pp['pcs'])}, EBRABO с {pp['promo_t']:.1f} с, "
                  f"голос {'ElevenLabs' if 'vc_t' in pp['take'] else 'временный'}; сверка: {'ок' if ok else why}", flush=True)
        return 0
    from core import clip_batch as CB
    tids = [t for t in SCENES if voice_takes(t)] or list(SCENES)
    global _ASR                                              # слова голоса — заранее, одним процессом (не в потоках партии)
    for t_ in tids:
        for take in voice_takes(t_):
            asr_words(take)
    if _ASR is not None:
        import torch
        _ASR = None
        torch.cuda.empty_cache()
    slots = []
    for tag, n in (("tt", a.tt), ("yt", a.yt)):
        d = ROOT / "output" / f"vibecity_1_{tag.upper()}_{n}"
        slots += [(tids[i % len(tids)], d / f"vibecity_{tag}_{i + 1:03d}_1.mp4") for i in range(n)]
    return 0 if CB.run(slots, lambda rng, tid: plan(rng, tid), build, jobs=a.jobs, work=WORK / "batch",
                       label="Vibe City", seed=1811) else 1


if __name__ == "__main__":
    raise SystemExit(main())
