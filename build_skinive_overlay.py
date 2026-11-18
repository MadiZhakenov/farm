#!/usr/bin/env python3
"""
Skinive 3 + Skinive 6 (айди нет → ID 1), новая версия (юзер 2026-11-11): скринкаст приложения убран. Видео идёт
до конца, а поверх него, как карточка App Store у Inspoy (1383/1386):
  • карточка App Store (тёмная шапка страницы, немецкий стор: «Hautscanner:Muttermal&Hautarzt»,
    «KI-Test: Hautkrebs&UV-Index», иконка — вырезана из записи стора IMG_0134) — внизу, под родинкой;
  • окошко с результатом, вырезанное из записи приложения:
      plate — плашка «Geringes Risiko» (skinive_3, IMG_2697) / «Hohes Risiko» (skinive_6, IMG_2706);
      gauge — шкала (стрелка + отсчёт) и строка «100 % Gutartiger Nävus» / «98 % Melanom», анимация ускорена до 0.9 с.
Карточки выезжают снизу (0.18 с) с лёгким «поп»-звуком. Всё в безопасной рамке (core.safe_zones).

skinive_3 «Запись только в марте» (9.0 с): лицо 3 с (POV) → родинка 3 с (hautarzt → MÄRZ) → та же родинка
  другим окном 3 с: «du scannst es mit Skinive / und siehst DAS 👇», App Store с 6.15 с, результат с 7.0 с под текстом.
skinive_6 тату-текстволл (≈6.7 с): тату-рука + лицо (шок) под текстволлом → другое окно той же тату-руки 3 с:
  App Store сразу, результат через 0.9 с сверху (родинка на 0.45 H свободна).

  python build_skinive_overlay.py --proj 3 --test --out output/skinive_overlay_test
  python build_skinive_overlay.py --proj 6 --test --out output/skinive_overlay_test
"""

from __future__ import annotations

import argparse
import itertools
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_skinive2 as S2  # noqa: E402  (music_loop)
import build_skinive3 as S3  # noqa: E402  (лицо, родинки, тексты skinive_3)
import build_skinive5 as S5  # noqa: E402  (тату, шок-окна, текстволл skinive_6)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
WORK = ROOT / "output" / "_work" / "skinive_overlay"
CARDS = WORK / "cards"
APP3 = ROOT / "downloads" / "skinive" / "app" / "IMG_2697.MP4"      # скан руки → Geringes Risiko / 100 % Gutartiger Nävus
REC6 = ROOT / "downloads" / "skinive4" / "IMG_2706.MP4"            # злокачественная → Hohes Risiko / 98 % Melanom
STORE = ROOT / "downloads" / "skinive" / "store" / "IMG_0134.MP4"
POP = ROOT / "downloads" / "drops_beats" / "sfx" / "pop" / "pop_402323.mp3"
F_SEMI, F_REG = ROOT / "fonts" / "inter" / "Inter-SemiBold.ttf", ROOT / "fonts" / "inter" / "Inter-Regular.ttf"

# немецкий App Store (apps.apple.com/de/app/id1633219654, 2026-11-11)
APP_TITLE = ["Hautscanner:", "Muttermal&Hautarzt"]
APP_SUB = "KI-Test: Hautkrebs&UV-Index"
STORE_ICON_T, ICON_BOX = 8.6, (60, 379, 414, 733)                # неподвижная страница стора, квадрат иконки
PLATE_BOX = (26, 988, 860, 1206)                                 # плашка риска с белыми полями (кадр 886×1920)
GAUGE_TOP, GAUGE_ROW = (190, 806), (944, 1150)                   # шкала до верха белой панели + строка с процентом
SRC = {
    3: dict(rec=APP3, plate_t=89.2, gauge=(84.0, 87.8)),
    6: dict(rec=REC6, plate_t=56.5, gauge=(50.8, 55.15)),
}
APPCARD_W, APPCARD_BOTTOM = 640, 1525
POP_IN = 0.18
SHADOW = 26                                                      # поле под тень вокруг карточки


# ---------- карточки ----------
def rounded(im: Image.Image, r: int) -> Image.Image:
    im = im.convert("RGBA")
    m = Image.new("L", (im.width * 4, im.height * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, im.width * 4 - 1, im.height * 4 - 1), radius=r * 4, fill=255)
    im.putalpha(m.resize(im.size, Image.Resampling.LANCZOS))
    return im


def with_shadow(card: Image.Image, alpha: int = 110) -> Image.Image:
    out = Image.new("RGBA", (card.width + 2 * SHADOW, card.height + 2 * SHADOW), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    a = card.getchannel("A").point(lambda v: v * alpha // 255)
    sh.paste((0, 0, 0, 255), (SHADOW, SHADOW + 8), a)
    out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    out.alpha_composite(card, (SHADOW, SHADOW))
    return out


def frame(src: Path, t: float) -> Image.Image:
    p = WORK / "ref" / f"{src.stem}_{t:.2f}.png"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", str(p)], check=True)
    return Image.open(p).convert("RGB")


def fit_font(path: Path, lines: list[str], width: int, px: int) -> ImageFont.FreeTypeFont:
    while px > 20:
        f = ImageFont.truetype(str(path), px)
        if max(f.getlength(s) for s in lines) <= width:
            return f
        px -= 1
    return ImageFont.truetype(str(path), px)


def app_card(theme: str = "dark", width: int = APPCARD_W) -> Image.Image:
    """Шапка страницы Skinive в App Store (тёмная тема, как карточка Inspoy в 1383; light — светлая): иконка,
    название, подзаголовок, «Laden», «In-App-Käufe». Рисуем в масштабе 820 px и уменьшаем до width."""
    cw, ch = 820, 330
    dark = theme == "dark"
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 255) if dark else (255, 255, 255, 255))
    ic = frame(STORE, STORE_ICON_T).crop(ICON_BOX).resize((272, 272), Image.Resampling.LANCZOS)
    img.alpha_composite(rounded(ic, round(272 * 0.2237)), (28, 29))
    d = ImageDraw.Draw(img)
    tx, tw = 336, cw - 336 - 26
    ft = fit_font(F_SEMI, APP_TITLE, tw, 50)
    for i, ln in enumerate(APP_TITLE):
        d.text((tx, 80 + i * 58), ln, font=ft, anchor="ls", fill=(255, 255, 255, 255) if dark else (0, 0, 0, 255))
    fs = fit_font(F_REG, [APP_SUB], tw, 34)
    d.text((tx, 186), APP_SUB, font=fs, anchor="ls", fill=(142, 142, 147, 255))
    d.rounded_rectangle((tx, 230, tx + 180, 303), radius=37, fill=(10, 132, 255, 255))
    d.text((tx + 90, 267), "Laden", font=ImageFont.truetype(str(F_SEMI), 36), anchor="mm", fill=(255, 255, 255, 255))
    fp = ImageFont.truetype(str(F_REG), 19)
    d.text((tx + 196, 262), "In-App-", font=fp, anchor="ls", fill=(142, 142, 147, 255))
    d.text((tx + 196, 285), "Käufe", font=fp, anchor="ls", fill=(142, 142, 147, 255))
    c = img.resize((width, round(ch * width / cw)), Image.Resampling.LANCZOS)
    return with_shadow(rounded(c, round(22 * width / APPCARD_W)), 140 if dark else 120)


def plate_card(proj: int, width: int) -> Image.Image:
    """Окошко результата: плашка риска из записи приложения на белом, скруглённая, с тенью."""
    p = frame(SRC[proj]["rec"], SRC[proj]["plate_t"]).crop(PLATE_BOX)
    p = p.resize((width, round(p.height * width / p.width)), Image.Resampling.LANCZOS)
    return with_shadow(rounded(p, 34))


def gauge_frames(proj: int, width: int, dur: float = 0.9) -> Path:
    """Шкала + строка с процентом из записи (анимация ускорена до dur) → PNG-кадры со скруглением и тенью."""
    d = CARDS / f"gauge{proj}_{width}"
    if d.exists() and any(d.glob("*.png")):
        return d
    d.mkdir(parents=True, exist_ok=True)
    g0, g1 = SRC[proj]["gauge"]
    raw = d / "raw"
    raw.mkdir(exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{g0:.3f}", "-t", f"{g1 - g0:.3f}", "-i", str(SRC[proj]["rec"]),
                    "-vf", f"setpts=PTS*{dur / (g1 - g0):.5f},fps={FPS}", str(raw / "%03d.png")], check=True)
    for i, f in enumerate(sorted(raw.glob("*.png")), 1):
        im = Image.open(f).convert("RGB")
        top, row = im.crop((0, GAUGE_TOP[0], im.width, GAUGE_TOP[1])), im.crop((0, GAUGE_ROW[0], im.width, GAUGE_ROW[1]))
        st = Image.new("RGB", (im.width, top.height + row.height), "white")
        st.paste(top, (0, 0))
        st.paste(row, (0, top.height))
        st = st.resize((width, round(st.height * width / st.width)), Image.Resampling.LANCZOS)
        with_shadow(rounded(st, 34)).save(d / f"{i:03d}.png")
        f.unlink()
    raw.rmdir()
    return d


def card_xy(card: Image.Image, top: int | None = None, bottom: int | None = None) -> tuple[int, int]:
    """Позиция PNG с полями под тень так, чтобы сама карточка стояла по центру с верхом top / низом bottom."""
    cw, chh = card.width - 2 * SHADOW, card.height - 2 * SHADOW
    x = (W - cw) // 2
    y = top if top is not None else bottom - chh
    if bad := check_box(W, H, (x, y, x + cw, y + chh)):
        raise SystemExit(f"карточка вне безопасной зоны: {bad}")
    return x - SHADOW, y - SHADOW


# ---------- проекты ----------
P3_GROUPS = {"c": ["c1", "c3"], "a": ["a1", "a2", "a3"]}          # окна одной и той же родинки (одна рука)
P3 = dict(result_top={"plate": 400, "gauge": 390}, result_w={"plate": 800, "gauge": 520}, t_app=6.15, t_res=7.0, total=9.0)
P6 = dict(result_top={"plate": 330, "gauge": 230}, result_w={"plate": 800, "gauge": 520}, t_app_rel=0.1, t_res_rel=0.9,
          end_len=3.0)


def plan(proj: int, n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    if proj == 3:
        pairs = [(a, b) for g in P3_GROUPS.values() for a in g for b in g if a != b]
        combos = list(itertools.product(range(len(S3.FACES)), pairs, ("plate", "gauge"), (0, 1)))
    else:
        pairs = [(a, b) for a in range(3) for b in range(3) if a != b]
        combos = list(itertools.product(range(len(S5.SHOCK)), pairs, ("plate", "gauge"), (0, 1)))
    rows = []
    for k in range(1, n + 1):
        if (k - 1) % len(combos) == 0:
            rng.shuffle(combos)
        f, (m1, m2), card, mirror = combos[(k - 1) % len(combos)]
        rows.append(dict(n=k, face=f, m1=m1, m2=m2, card=card, mirror=mirror, f_off=round(rng.uniform(0, 0.25), 2),
                         m_off=round(rng.uniform(0, 0.1), 2), m2_off=round(rng.uniform(0, 0.1), 2),
                         t_len=round(rng.uniform(1.9, 2.1), 2), f_len=round(rng.uniform(1.5, 1.7), 2),
                         bri=round(rng.uniform(-0.02, 0.03), 3), sat=round(rng.uniform(1.0, 1.1), 3),
                         zoom=round(rng.uniform(1.0, 1.06), 3)))
    return rows


def enc_args(dest: Path) -> list[str]:
    return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
            "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
            "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)]


def render(proj: int, r: dict, out: Path, assets: dict, tag: str) -> Path:
    name = f"skinive{proj}_{tag}{r['n']:03d}"
    grade = f"eq=brightness={r['bri']}:saturation={r['sat']}"
    z = r["zoom"]
    zw, zh = round(W * z / 2) * 2, round(H * z / 2) * 2
    mir = ",hflip" if r["mirror"] else ""
    inputs, parts = [], []
    if proj == 3:
        inputs += ["-i", str(S3.FACE), "-i", str(S3.MOLES / f"{r['m1']}.mp4"), "-i", str(S3.MOLES / f"{r['m2']}.mp4")]
        parts += [f"[0:v]trim=start={S3.FACES[r['face']] + r['f_off']:.3f}:duration={S3.T_FACE},setpts=PTS-STARTPTS,"
                  f"fps={FPS},scale={zw}:{zh},crop={W}:{H},{grade},setsar=1[s0]",
                  f"[1:v]trim=start={r['m_off']:.3f}:duration={S3.T_MOLE},setpts=PTS-STARTPTS,fps={FPS},{grade}{mir},setsar=1[s1]",
                  f"[2:v]trim=start={r['m2_off']:.3f}:duration=3.0,setpts=PTS-STARTPTS,fps={FPS},{grade}{mir},setsar=1[s2]"]
        total = P3["total"]
        t_app, t_res = P3["t_app"], P3["t_res"]
        overlays = [(p, 0, 0, a, min(b, total)) for p, (_, a, b) in zip(assets["texts"], S3.TEXTS)]
    else:
        tat = [S5.TAT / f"{t}.mp4" for t in S5.TATTOOS]
        inputs += ["-i", str(tat[r["m1"]]), "-i", str(S5.FACE), "-i", str(tat[r["m2"]])]
        parts += [f"[0:v]trim=start={r['m_off']:.3f}:duration={r['t_len']:.3f},setpts=PTS-STARTPTS,fps={FPS},{grade}{mir},setsar=1[s0]",
                  f"[1:v]trim=start={S5.SHOCK[r['face']] + r['f_off']:.3f}:duration={r['f_len']:.3f},setpts=PTS-STARTPTS,"
                  f"fps={FPS},scale={zw}:{zh},crop={W}:{H},{grade}{mir},setsar=1[s1]",
                  f"[2:v]trim=start={r['m2_off']:.3f}:duration={P6['end_len']:.3f},setpts=PTS-STARTPTS,fps={FPS},"
                  f"{grade}{mir},setsar=1[s2]"]
        t_wall = r["t_len"] + r["f_len"]
        total = round(t_wall + P6["end_len"], 3)
        t_app, t_res = t_wall + P6["t_app_rel"], t_wall + P6["t_res_rel"]
        overlays = [(assets["wall"], 0, 0, 0.0, t_wall)]
    parts.append("[s0][s1][s2]concat=n=3:v=1:a=0[b0]")
    idx = 3
    cur = "b0"
    for i, (png, x, y, a, b) in enumerate(overlays):
        inputs += ["-i", str(png)]
        parts.append(f"[{cur}][{idx}:v]overlay={x}:{y}:enable='between(t,{a:.3f},{b:.3f})'[o{i}]")
        cur, idx = f"o{i}", idx + 1

    def pop(src_idx: int, label: str, x: int, y: int, t0: float, seq: bool = False) -> None:
        nonlocal cur
        if seq:
            pre = f"[{src_idx}:v]format=rgba,tpad=stop_mode=clone:stop_duration={total:.3f},trim=duration={total - t0:.3f},"
            pre += f"setpts=PTS-STARTPTS+{t0:.3f}/TB,"
        else:
            pre = f"[{src_idx}:v]format=rgba,trim=duration={total:.3f},"
        parts.append(f"{pre}fade=t=in:st={t0:.3f}:d={POP_IN}:alpha=1[{label}]")
        parts.append(f"[{cur}][{label}]overlay=x={x}:y='{y}+40*max(0,1-(t-{t0:.3f})/{POP_IN})':"
                     f"enable='gte(t,{t0:.3f})':eof_action=pass[{label}o]")
        cur = f"{label}o"

    ax, ay = assets["app_xy"]
    inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(assets["app"])]
    pop(idx, "ap", ax, ay, t_app)
    idx += 1
    rx, ry = assets[r["card"] + "_xy"]
    if r["card"] == "plate":
        inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(assets["plate"])]
        pop(idx, "rs", rx, ry, t_res)
    else:
        inputs += ["-framerate", str(FPS), "-i", str(assets["gauge"] / "%03d.png")]
        pop(idx, "rs", rx, ry, t_res, seq=True)
    idx += 1
    parts.append(f"[{cur}]format=yuv420p,trim=duration={total:.3f}[v]")
    mus = WORK / f"{name}.wav"
    S2.music_loop(mus, total)
    inputs += ["-i", str(mus), "-i", str(POP), "-i", str(POP)]
    parts.append(f"[{idx + 1}:a]volume=0.55,adelay=delays={round(t_app * 1000)}:all=1[p1]")
    parts.append(f"[{idx + 2}:a]volume=0.55,adelay=delays={round(t_res * 1000)}:all=1[p2]")
    parts.append(f"[{idx}:a][p1][p2]amix=inputs=3:normalize=0:duration=first,atrim=0:{total:.3f}[a]")
    dest = out / f"{name}_1.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
                    "-t", f"{total:.3f}", *enc_args(dest)], check=True)
    mus.unlink()
    return dest


def build_assets(proj: int) -> dict:
    CARDS.mkdir(parents=True, exist_ok=True)
    a = {}
    app = app_card()
    a["app"] = CARDS / "appstore.png"
    app.save(a["app"])
    a["app_xy"] = card_xy(app, bottom=APPCARD_BOTTOM)
    cfg = P3 if proj == 3 else P6
    pl = plate_card(proj, cfg["result_w"]["plate"])
    a["plate"] = CARDS / f"plate{proj}.png"
    pl.save(a["plate"])
    a["plate_xy"] = card_xy(pl, top=cfg["result_top"]["plate"])
    a["gauge"] = gauge_frames(proj, cfg["result_w"]["gauge"])
    g = Image.open(a["gauge"] / "001.png")
    a["gauge_xy"] = card_xy(g, top=cfg["result_top"]["gauge"])
    if proj == 3:
        a["texts"] = S3.text_pngs(WORK)
    else:
        a["wall"] = WORK / "wall6.png"
        S5.wall_low(a["wall"])
    return a


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proj", type=int, choices=(3, 6), required=True)
    ap.add_argument("--test", action="store_true", help="4 теста: 2 × plate + 2 × gauge, разные окна")
    ap.add_argument("-n", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tag", default="")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "skinive_overlay_test")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    seed = a.seed or (311 if a.proj == 3 else 611)
    rows = plan(a.proj, max(a.n, 40), seed)
    if a.test:
        pick, seen = [], set()
        for card in ("plate", "gauge"):
            for r in rows:
                key = (r["card"], r["m1"], r["face"])
                if r["card"] == card and key not in seen and sum(x["card"] == card for x in pick) < 2:
                    pick.append(r)
                    seen.add(key)
        rows = pick
        for i, r in enumerate(rows, 1):
            r["n"] = i
    else:
        rows = rows[:a.n]
    a.out.mkdir(parents=True, exist_ok=True)
    assets = build_assets(a.proj)
    tag = a.tag + "_" if a.tag else ""
    with ThreadPoolExecutor(a.jobs) as ex:
        for dest in ex.map(lambda r: render(a.proj, r, a.out, assets, tag), rows):
            print(f"  {dest.name}", flush=True)
    print(f"готово: {len(rows)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
