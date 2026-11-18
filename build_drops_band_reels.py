#!/usr/bin/env python3
"""
Drops «band practices» (айди нет): 9:16 ролик 8 с по рефу.
  0–3 с — сгенерированное видео репетиции группы (downloads/drops_band/clips/*.mp4), по центру белый текст
          «our band practices / are getting / way too competitive» с мягкой тенью;
  3–8 с — чёрный фон, по центру полоса геймплея Drops (скринкаст клиента, только игровое поле), сверху
          «we turned our track into / a game on drops», снизу «let’s see who’s better / our bassist or drummer».
Звук — трек этой же игры (downloads/drops_band/music), свой отрезок у каждого ролика — только там, где поёт голос
(карта вокала Demucs: vocal_map_drops_band.py → music/_vocals.json). Тексты ТЗ дословно,
всё в безопасной зоне 9:16. nvenc cq 27, без метаданных.

  python build_drops_band_reels.py -n 2 --out output/drops_band_test
  python build_drops_band_reels.py -n 4 --clip band_02.mp4 --out output/drops_band_test3
  python build_drops_band_reels.py -n 150 --out output/drops_band_150      # клипы по кругу, окна и треки разнесены
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import check_box  # noqa: E402
from core.text_shadow import add_shadow  # noqa: E402

W, H, FPS = 1080, 1920, 30
D = ROOT / "downloads" / "drops_band"
FONT = ROOT / "fonts" / "TikTokSans-SemiBold.ttf"
HOOK = ["our band practices", "are getting", "way too competitive"]
TOP = ["we turned our track into", "a game on drops"]
BOTTOM = ["let’s see who’s better", "our bassist or drummer"]
T_BAND, T_GAME = 3.0, 5.0
AUDIO_GAIN = None                          # дБ на весь ролик вместо loudnorm (build_drops_band_drop: не сглаживать дроп)
CAP_GAP = 60                               # отступ подписей от полосы геймплея
CLIP_T_MAX = {"band_02.mp4": 2.0}          # дальше в клипе камера наезжает на вокалиста — басиста и барабанщика не видно
HOOK_Y = {"band_02.mp4": 0.64}             # центр хука по высоте; в band_02 лицо вокалиста на ~0,4 — хук на футболку
# скринкаст 1920×1080: игровое поле без жёлтой шапки сайта и белой панели рекордов справа
GAME_BOX = (60, 92, 1380, 1062)
PAIRS = {                                   # скринкаст → трек этой игры
    "MP1_Get_Back": "1 Get Back.mp3",
    "MP3_The_Best_Bad_Idea": "3 The Best Bad Idea.mp3",
    "MP4_Were_Not_Going_Home": "4 We're Not Going Home.mp3",
    "MP5_Your_Coat_On_The_Chair": "5 Your Coat on the Chair.mp3",
}


def dur(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)


_VOC: dict = {}


def vocal_starts(track: str) -> list[float]:
    """Начала отрезков, где поёт голос: первые 3 с (группа поёт в кадре) — голос ≥ 90 %, весь ролик ≥ 75 %
    (карта вокала — vocal_map_drops_band.py, паузы между словами до 0,3 с не считаем тишиной)."""
    import numpy as np
    if not _VOC:
        _VOC.update(json.loads((D / "music" / "_vocals.json").read_text(encoding="utf-8")))
    v = _VOC[track]
    hop = v["hop"]
    on = np.array(v["db"]) > v["thr"]
    k = max(1, round(0.3 / hop))
    on = np.convolve(on.astype(int), np.ones(2 * k + 1, int), "same") > 0          # склеить паузы между словами
    nb, nt = round(T_BAND / hop), round((T_BAND + T_GAME) / hop)
    starts = [i * hop for i in range(len(on) - nt)
              if on[i:i + 3].all() and on[i:i + nb].mean() >= 0.9 and on[i:i + nt].mean() >= 0.75]
    return starts


STROKE = 0.0                               # >0 — белый текст с чёрной обводкой (доля кегля), как подписи TikTok


def text_png(lines: list[str], px: int, dest: Path, shadow: bool) -> tuple[int, int]:
    f = ImageFont.truetype(str(FONT), px)
    sw = round(px * STROKE)
    while max(f.getlength(ln) for ln in lines) + 2 * sw > 790:
        px -= 2
        f = ImageFont.truetype(str(FONT), px)
        sw = round(px * STROKE)
    step = int(px * 1.22)
    w = int(max(f.getlength(ln) for ln in lines)) + 8 + 2 * sw
    im = Image.new("RGBA", (w, step * len(lines) + px // 3 + 2 * sw), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for k, ln in enumerate(lines):
        d.text(((w - f.getlength(ln)) / 2, k * step + sw), ln, font=f, fill=(255, 255, 255, 255),
               stroke_width=sw, stroke_fill=(0, 0, 0, 255))
    im = im.crop(im.getbbox())
    if shadow and not sw:
        im = add_shadow(add_shadow(im, blur=3, opacity=0.6, offset=(0, 2), grow=1), blur=16, opacity=0.35, offset=(0, 3), grow=5)
    im.save(dest)
    return im.size


def build(i: int, v: dict, out: Path, work: Path) -> dict:
    """v — план ролика из plan(): клип и старт окна, скорость/зум/сдвиг/цвет, окно геймплея, отрезок трека с голосом."""
    clip, sc = D / "clips" / v["clip"], v["game"]
    c0, sp, g0, m0 = v["clip_t"], v["speed"], v["game_t"], v["track_t"]
    track = D / "music" / PAIRS[sc]
    gx0, gy0, gx1, gy1 = GAME_BOX
    gz = v["game_zoom"]                                              # чуть ужать окно игрового поля и сдвинуть
    cw, ch = round((gx1 - gx0) * gz / 2) * 2, round((gy1 - gy0) * gz / 2) * 2
    cx = gx0 + round(((gx1 - gx0) - cw) * v["game_fx"])
    cy = gy0 + round(((gy1 - gy0) - ch) * v["game_fy"])
    gh = round((gy1 - gy0) * W / (gx1 - gx0) / 2) * 2
    gy = (H - gh) // 2
    hook, top, bot = work / f"{i}_hook.png", work / f"{i}_top.png", work / f"{i}_bot.png"
    hw, hh = text_png(HOOK, 66, hook, True)
    tw, th = text_png(TOP, 60, top, False)
    bw, bh = text_png(BOTTOM, 60, bot, False)
    hx, hy = (W - hw) // 2, int(H * HOOK_Y.get(clip.name, 0.5) - hh / 2)
    tx, ty = (W - tw) // 2, gy - CAP_GAP - th
    bx, by = (W - bw) // 2, gy + gh + CAP_GAP
    for b in ((hx + 18, hy + 18, hx + hw - 18, hy + hh - 18), (tx, ty, tx + tw, ty + th), (bx, by, bx + bw, by + bh)):
        if bad := check_box(W, H, b):
            raise SystemExit(f"{i:03d}: текст вне безопасной зоны {b} — {bad}")
    z = v["zoom"]
    zw, zh = round(W * z / 2) * 2, round(H * z / 2) * 2
    ox, oy = round((zw - W) * v["fx"]), round((zh - H) * v["fy"])
    br, ct, sa = v["eq"]
    level = f"volume={AUDIO_GAIN}dB,alimiter=limit=0.89:level=false" if AUDIO_GAIN is not None else "loudnorm=I=-14:TP=-1.5:LRA=11"
    fc = [
        f"[0:v]trim=start={c0}:duration={T_BAND * sp:.3f},setpts=(PTS-STARTPTS)/{sp:.4f},fps={FPS},"
        f"scale={zw}:{zh}:force_original_aspect_ratio=increase,crop={W}:{H}:{ox}:{oy},"
        f"eq=brightness={br:.3f}:contrast={ct:.3f}:saturation={sa:.3f},setsar=1,trim=end_frame={round(T_BAND * FPS)}[b0]",
        f"[b0][2:v]overlay={hx}:{hy}[band]",
        f"[1:v]trim=start={g0}:duration={T_GAME},setpts=PTS-STARTPTS,fps={FPS},crop={cw}:{ch}:{cx}:{cy},"
        f"scale={W}:{gh},pad={W}:{H}:0:{gy}:black,setsar=1[g0]",
        f"[g0][3:v]overlay={tx}:{ty}[g1]",
        f"[g1][4:v]overlay={bx}:{by}[game]",
        "[band][game]concat=n=2:v=1:a=0,format=yuv420p[v]",
        f"[5:a]atrim=start={m0}:duration={T_BAND + T_GAME},asetpts=PTS-STARTPTS,afade=t=in:d=0.15,"
        f"afade=t=out:st={T_BAND + T_GAME - 0.4}:d=0.4,{level}[a]",
    ]
    dest = out / f"{i:03d}_noid.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-i", str(D / "screencasts" / f"{sc}.mp4"),
                    "-i", str(hook), "-i", str(top), "-i", str(bot), "-i", str(track),
                    "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-t", str(T_BAND + T_GAME),
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-map_metadata", "-1", "-fflags", "+bitexact",
                    "-flags:v", "+bitexact", "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=",
                    "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart",
                    str(dest)], check=True)
    for p in (hook, top, bot):
        p.unlink()
    return {"video": dest.name, **v}


def spread(n: int, lo: float, hi: float, rng: random.Random) -> list[float]:
    """n стартов равномерно по [lo, hi] с дрожанием внутри своей ячейки, в случайном порядке."""
    step = (hi - lo) / max(n, 1)
    xs = [round(lo + step * (k + rng.uniform(0.15, 0.85)), 2) for k in range(n)]
    rng.shuffle(xs)
    return xs


def plan(n: int, clips: list[Path], seed: int) -> list[dict]:
    """Уникальность партии: клипы по кругу, игры по кругу независимо от клипов; окна клипа и геймплея разнесены
    равномерно; отрезки трека с голосом — не ближе 1,5 с друг к другу; у каждого ролика свои зум/сдвиг/цвет/скорость."""
    rng = random.Random(seed)
    games = list(PAIRS)
    rows = [{"clip": clips[(i - 1) % len(clips)].name, "game": games[((i - 1) // len(clips)) % len(games)]}
            for i in range(1, n + 1)]
    for c in clips:
        idx = [k for k, r in enumerate(rows) if r["clip"] == c.name]
        hi = min(CLIP_T_MAX.get(c.name, 99.0), dur(c) - T_BAND * 1.05 - 0.05)
        for k, t in zip(idx, spread(len(idx), 0.0, hi, rng)):
            rows[k]["clip_t"] = t
    for g in games:
        idx = [k for k, r in enumerate(rows) if r["game"] == g]
        sd = dur(D / "screencasts" / f"{g}.mp4")
        for k, t in zip(idx, spread(len(idx), 3.5, sd - T_GAME - 0.5, rng)):
            rows[k]["game_t"] = t
        cand = vocal_starts(PAIRS[g])
        rng.shuffle(cand)
        used: list[float] = []
        for k in idx:
            gap, pick = 1.5, None
            while pick is None and gap >= 0.2:
                pick = next((c for c in cand if all(abs(c - x) >= gap for x in used)), None)
                gap /= 2
            pick = pick if pick is not None else rng.choice(cand)
            used.append(pick)
            rows[k]["track_t"] = round(pick, 2)
    for r in rows:
        r.update(speed=round(rng.uniform(0.95, 1.05), 3), zoom=round(rng.uniform(1.0, 1.07), 3),
                 fx=round(rng.random(), 3), fy=round(rng.uniform(0.2, 0.8), 3),
                 eq=(round(rng.uniform(-0.025, 0.025), 3), round(rng.uniform(0.97, 1.05), 3),
                     round(rng.uniform(0.92, 1.12), 3)),
                 game_zoom=round(rng.uniform(0.96, 1.0), 3), game_fx=round(rng.random(), 3), game_fy=round(rng.random(), 3))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "drops_band_test")
    ap.add_argument("--seed", type=int, default=8)
    ap.add_argument("--clip", default="*.mp4", help="какие клипы группы брать (маска в clips/)")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    clips = sorted((D / "clips").glob(a.clip))
    a.out.mkdir(parents=True, exist_ok=True)
    work = a.out / "_work"
    work.mkdir(exist_ok=True)
    rows = plan(a.n, clips, a.seed)
    done = [0]

    def one(k: int) -> dict:
        r = build(k + 1, rows[k], a.out, work)
        done[0] += 1
        if done[0] % 10 == 0 or done[0] == a.n:
            print(f"  {done[0]}/{a.n}", flush=True)
        return r
    with ThreadPoolExecutor(a.jobs) as ex:
        man = list(ex.map(one, range(a.n)))
    work.rmdir()
    (a.out / "manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    print(f"готово: {a.n} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
