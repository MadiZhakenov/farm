#!/usr/bin/env python3
"""
Drops, ID 1 — «he hasn’t texted me back in 6 hours / but he’s still playing the game I made from my song 😭» (реф darkugc
tt-7518976046180338958 = @findgonbump: лицо с текстом сверху → запись экрана приложения в две склейки, 6.7 с).
v2 после фидбека («немного странный контент» → эмоции, переход, музыка):
  - лицо ~3 с — только моменты обиды / расстройства (хмурится, рука у рта, «ну как так», грустно поджатые губы), без улыбок;
    внутри одной комнаты можно склеить два таких момента;
  - переход ~1.2 с — вкладка Ranks её игры Party Pop - Neon Arcade (автор Aria Vale = она), на первом месте он с большим счётом
    (capture_drops_ghost_ranks.py) — понятно, что это он играет;
  - геймплей ~2.3 с этой же игры (Party Pop) в две склейки;
  - музыка — 4 трендовых звука TikTok по кругу (Tokchart 9.11.2026): Wyw my sweetie (Super Slowed), Paper Moon Static, Piano Hush, Housewife.
Текст ТЗ дословно, TikTok-шрифт с обводкой, сверху на весь ролик. ≤ 7 с. YT 200 + TT 100, все сочетания разные.

  python build_drops_ghost.py --test
  python build_drops_ghost.py --batch
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_followspy_walls as F  # noqa: E402
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
FACES = ROOT / "downloads" / "drops_react" / "faces"
GAMES = ROOT / "output" / "drops_react" / "gameplay"
RANKS = ROOT / "downloads" / "drops_ghost" / "ranks"
MDIR = ROOT / "downloads" / "drops_ghost" / "music"
# трендовые звуки TikTok (Tokchart, 9.11.2026, выбор юзера) — по кругу; старт: 0 = начало клипа TikTok, None = самый плотный кусок
MUSIC = {"wyw_sweetie": (MDIR / "wyw_sweetie_7693157397116799762.mp3", 0.0),
         "paper_moon_static": (MDIR / "paper_moon_static_7684150368565250075.mp3", 0.0),
         "piano_hush": (MDIR / "piano_hush_7673184751242676258.mp3", None),
         "housewife": (MDIR / "housewife_7697010651306838068.mp3", 0.0)}


def music_start(p: Path, length: float = 7.0) -> float:
    """Самый плотный кусок трека нужной длины (по громкости)."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-ac", "1", "-ar", "8000", "-f", "f32le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.float32)
    rms = np.sqrt(np.convolve(a ** 2, np.ones(800) / 800, "same"))[::400]
    n = int(length * 20)
    return round(int(np.argmax(np.convolve(rms, np.ones(n), "valid"))) / 20, 2) if len(rms) > n else 0.0
# песни Drops (Dropbox клиента, те же, что в роликах с ИИ-группой; по сюжету — «её песня», из которой она сделала игру):
# игра (вкладка Ranks) появляется ровно на дропе — точки, выставленные юзером в тюнере (drops_band/music/_drops_manual.json),
# следующие склейки (Ranks → геймплей, геймплей → геймплей) — на биты песни.
DBAND = ROOT / "downloads" / "drops_band" / "music"
DROPS_SONGS = {"MP1_Get_Back": "1 Get Back.mp3", "MP2_Get_Out_Of_My_Head": "2 Get Out of My Head.mp3",
               "MP3_The_Best_Bad_Idea": "3 The Best Bad Idea.mp3", "MP4_Were_Not_Going_Home": "4 We're Not Going Home.mp3",
               "MP5_Your_Coat_On_The_Chair": "5 Your Coat on the Chair.mp3"}
DROPS_DB = -15.5                                    # постоянное усиление вместо loudnorm, чтобы дроп не сплющился


# звуки с darkugc (10.11.2026, песни Drops юзеру не зашли): TikTok-звуки из вирусных роликов про расставания / игнор / no contact /
# отношения на расстоянии (публичные аккаунты: karims.journey, court.girlcode, bella.longdistance, avagirltalk). Берётся начало звука —
# ровно тот кусок, что в вирусных роликах; склейка лицо → Ranks подтягивается на ближайший бит после ~3 с.
M2 = ROOT / "downloads" / "drops_ghost" / "music2"
DUGC = {"futile_devices": M2 / "futile_devices_7498146795982228270.mp3",      # Futile Devices (karims.journey, No Contact)
        "watch": M2 / "watch_7269062050672397062.mp3",                        # watch (court.girlcode)
        "jenny": M2 / "jenny_7548582234221053953.mp3",                        # i'd always think of jenny (bella.longdistance)
        "rodwave": M2 / "rodwave_7596903333727210270.mp3",                    # original sound - rodwavehairline (avagirltalk)
        "far_apart": M2 / "far_apart_7354103379888769824.mp3"}                # original sound - delaudios (bella.longdistance)


DUGC_TOTAL = 8.95                                   # длина ролика с треками darkugc (клиент 12.11: 9 с)


def dugc_points() -> list[tuple[str, float]]:
    """Точки перехода лицо → игра, выставленные в тюнере (tuner_drops_ghost.py → music2/_cuts_manual.json); без файла —
    первый бит в 3.2–3.9 с (как было)."""
    import tuner_drops_ghost as TG
    saved = json.loads(TG.MANUAL.read_text(encoding="utf-8")) if TG.MANUAL.exists() else {}
    pts = []
    for k in DUGC:
        lst = saved.get(k) or [{"t": t, "on": True} for t in TG.defaults(k)]
        pts += [(k, float(q["t"])) for q in lst if q.get("on")]
    return pts


def to_dugc(rows: list[dict], names: list[str] | None = None) -> list[dict]:
    """Трендовые звуки darkugc: переход лицо → Ranks ровно в точке из тюнера (старт звука = точка − длина лица),
    Ranks → геймплей и геймплей → геймплей — на ближайшие биты после точки; всё ≤ 7 с."""
    import tuner_drops_ghost as TG
    pts = [pt for pt in dugc_points() if not names or pt[0] in names]
    out = []
    for i, r in enumerate(rows):
        song, t = pts[i % len(pts)]
        face_len = sum(round(ln * FPS) for _, _, ln in r["face"]) / FPS
        bs = [b for b in TG.beats(song) if b > t + 0.3]
        b1 = min((b for b in bs if 0.95 <= b - t <= 1.45), key=lambda b: abs(b - t - 1.2), default=t + r["ranks_len"])
        b2 = min((b for b in bs if 0.65 <= b - b1 <= 1.05), key=lambda b: abs(b - b1 - .85), default=b1 + r["cut1"])
        ranks_len = round((b1 - t) * FPS) / FPS
        cut1 = round((b2 - b1) * FPS) / FPS
        cut2 = round((DUGC_TOTAL - face_len - ranks_len - cut1) * FPS) / FPS     # клиент: геймплей в конце +2 с → ~9 с
        out.append(dict(r, music=song, music_t=round(max(0.0, t - face_len), 3), drop=t, ranks_len=ranks_len, cut1=cut1,
                        cut2=cut2))
    return out


def drop_points() -> list[tuple[str, float]]:
    saved = json.loads((DBAND / "_drops_manual.json").read_text(encoding="utf-8"))
    return [(song, p["t"]) for song in DROPS_SONGS for p in saved.get(song, []) if p.get("on")]


def beats_after(song: str, t: float) -> list[float]:
    """Биты песни после дропа t (librosa по окну −4…+6 с), абсолютное время."""
    import librosa
    import numpy as np
    y, sr = librosa.load(str(DBAND / DROPS_SONGS[song]), sr=22050, mono=True, offset=max(0.0, t - 4), duration=10)
    _, fr = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    b = librosa.frames_to_time(fr, sr=sr) + max(0.0, t - 4)
    return [float(x) for x in np.asarray(b) if x > t + 0.3]


def song_gain(song: str, start: float, length: float) -> float:
    import re
    err = subprocess.run(["ffmpeg", "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{length:.2f}", "-i", str(DBAND / DROPS_SONGS[song]),
                          "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
    return round(DROPS_DB - float(re.search(r"mean_volume: (-?[\d.]+) dB", err).group(1)), 2)


def to_drops(rows: list[dict]) -> list[dict]:
    """Те же ролики, но музыка — песни Drops: дроп на появлении игры, склейки на битах, всё ≤ 7 с."""
    pts = drop_points()
    grid = {pt: beats_after(*pt) for pt in pts}
    out = []
    for i, r in enumerate(rows):
        song, t = pts[i % len(pts)]
        face_len = sum(round(ln * FPS) for _, _, ln in r["face"]) / FPS       # ровно по кадрам: склейка лицо → игра = дроп
        bs = grid[(song, t)]
        b1 = min((b for b in bs if 0.95 <= b - t <= 1.45), key=lambda b: abs(b - t - 1.2), default=t + r["ranks_len"])
        b2 = min((b for b in bs if 0.65 <= b - b1 <= 1.05), key=lambda b: abs(b - b1 - .85), default=b1 + r["cut1"])
        ranks_len = round((b1 - t) * FPS) / FPS
        cut1 = round((b1 + (b2 - b1)) * FPS) / FPS - round(b1 * FPS) / FPS
        cut1 = round(cut1 * FPS) / FPS
        cut2 = round(min(1.5, 6.95 - face_len - ranks_len - cut1) * FPS) / FPS
        r2 = dict(r, music=song, music_t=round(t - face_len, 3), drop=t, ranks_len=ranks_len, cut1=cut1, cut2=cut2)
        r2["gain"] = song_gain(song, r2["music_t"], face_len + ranks_len + cut1 + cut2)
        out.append(r2)
    return out


TEXT = "he hasn’t texted me back in 6 hours\nbut he’s still playing the game\nI made from my song 😭"
TOP = 250
# отрезки лица с обидой/расстройством (клип, от, до), по комнатам — склейка двух отрезков только внутри одной комнаты
FACE_SEG = {                                     # 10.11: покадрово вырезаны улыбки/ухмылки (5721 после 1.95, 5733 1.15–4.4 и после 6.35, 5737 1.3–2.1)
    "mint": [("IMG_5721", 0.5, 1.95), ("IMG_5726", 0.0, 3.0), ("IMG_5732", 0.15, 1.7)],               # 5725 убран: поджатые губы читаются как ухмылка
    "orange": [("IMG_5733", 0.0, 1.15), ("IMG_5733", 4.4, 6.35)],
    "grey": [("IMG_5737", 0.0, 1.3), ("IMG_5737", 2.1, 3.8)],
}
GROUP_W = {"mint": 1}                            # 10.11 покадрово: в orange (5733) и grey (5737) между грустными кусками улыбки — на 2,9 с без них не хватает
GAME_RUNS = ["shooter_ariavale_11", "shooter_ariavale_12", "shooter_ariavale_13", "shooter_ariavale_14",
             "shooter_ariavale_16", "shooter_partypop_4", "shooter_partypop_5"]          # ariavale_15 — 62 % стоп-кадров записи, не берём
PARTYPOP_WIN = {"shooter_partypop_4": (3.0, 14.5), "shooter_partypop_5": (3.0, 14.0)}


def game_windows() -> dict:
    runs = json.loads((GAMES / "_runs.json").read_text(encoding="utf-8"))
    out = {k: tuple(v) for k, v in runs.items() if k in GAME_RUNS}
    out.update(PARTYPOP_WIN)
    return out


_MOTION: dict = {}


def motion(game: str):
    """Движение кадра по 0.1 с (кэш): в записях бывают стоп-кадры — сбои записи экрана (ariavale_16 8–13 с)."""
    import numpy as np
    if game not in _MOTION:
        cache = ROOT / "output" / "_work" / "drops_ghost" / f"motion_{game}.npy"
        if cache.exists():
            _MOTION[game] = np.load(cache)
        else:
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(GAMES / f"{game}.mp4"), "-vf", "fps=10,scale=54:96", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                                 capture_output=True).stdout
            v = np.frombuffer(raw, np.uint8).reshape(-1, 96, 54).astype(np.int16)
            d = np.r_[0, np.abs(np.diff(v, axis=0)).mean((1, 2))]
            cache.parent.mkdir(parents=True, exist_ok=True)
            np.save(cache, d)
            _MOTION[game] = d
    return _MOTION[game]


def moving(game: str, t: float, length: float) -> bool:
    """Кусок живой: нет стоп-кадра записи длиннее 0.2 с (раньше требовалось движение в каждом 0.1 с — для 3.5 с слишком строго)."""
    d = motion(game)
    seg = d[int(t * 10) + 1:int((t + length) * 10) + 2]
    if len(seg) == 0:
        return False
    run = 0
    for x in seg:
        run = run + 1 if x <= 0.08 else 0
        if run > 2:
            return False
    return True


def face_plan(rng: random.Random, total: float) -> list[tuple[str, float, float]]:
    """Части лица (клип, старт, длина) общей длиной total, одна комната."""
    group = rng.choices(list(GROUP_W), weights=list(GROUP_W.values()))[0]
    segs = FACE_SEG[group]
    long = [s for s in segs if s[2] - s[1] >= total]
    if long and (len(segs) == 1 or rng.random() < .45):
        c, a, b = rng.choice(long)
        st = round(rng.uniform(a, b - total), 2)
        return [(c, st, total)]
    a1, a2 = rng.sample(segs, 2)
    l1 = round(min(a1[2] - a1[1], rng.uniform(total * .4, total * .6)), 2)
    l2 = round(total - l1, 2)
    if a2[2] - a2[1] < l2:                       # второй отрезок короче — добираем первым
        l2 = round(a2[2] - a2[1], 2)
        l1 = round(total - l2, 2)
    if l1 > a1[2] - a1[1] + 1e-6 or l2 > a2[2] - a2[1] + 1e-6:      # не влезает в чистые окна — другое сочетание
        return []
    p1 = (a1[0], round(rng.uniform(a1[1], max(a1[1], a1[2] - l1)), 2), l1)
    p2 = (a2[0], round(rng.uniform(a2[1], max(a2[1], a2[2] - l2)), 2), l2)
    if any(st + ln > seg[2] + 1e-6 for (_, st, ln), seg in ((p1, a1), (p2, a2))):     # округление вылезло за окно
        return []
    return [p1, p2]


def plan(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    games = game_windows()
    ranks = sorted(p.name for p in RANKS.glob("ranks_*.png"))
    rows, seen, uses = [], set(), {}
    starts = {m: (t if t is not None else music_start(p)) for m, (p, t) in MUSIC.items()}
    for i in range(n):
        for _ in range(3000):
            face_len = round(rng.uniform(2.9, 3.2) * FPS) / FPS
            face = face_plan(rng, face_len)
            if not face:
                continue
            mirror = rng.random() < .5
            rk = min(ranks, key=lambda r: uses.get(r, 0) + rng.random() * 1.5)
            game = min(games, key=lambda g: uses.get(g, 0) + rng.random() * 1.5)
            a, b = games[game]
            g0 = round(rng.uniform(a, b - 6.0), 1)
            g1 = round(min(b - 4.2, g0 + rng.uniform(2.2, 4.5)), 1)        # второй кусок игры 3.6–4.1 с (ролик 9 с)
            if not (moving(game, g0, 1.0) and moving(game, g1, 4.2)):      # стоп-кадр записи — другое место
                continue
            key = (tuple((c, round(s, 1)) for c, s, _ in face), mirror, rk, game, round(g0))
            if key not in seen:
                break
        else:
            raise SystemExit(f"ролик {i + 1}: не нашлось живого геймплея с новым сочетанием")
        seen.add(key)
        for k in (rk, game):
            uses[k] = uses.get(k, 0) + 1
        rows.append(dict(face=face, mirror=mirror, ranks=rk, ranks_len=round(rng.uniform(1.1, 1.3) * FPS) / FPS,
                         ranks_z=round(rng.uniform(1.0, 1.1), 3), game=game, g0=g0, g1=g1,
                         cut1=round(rng.uniform(.75, .9) * FPS) / FPS, cut2=round(rng.uniform(1.35, 1.5) * FPS) / FPS,
                         music=list(MUSIC)[i % len(MUSIC)], music_t=starts[list(MUSIC)[i % len(MUSIC)]]))
    return rows


def text_png(dest: Path) -> tuple[int, int, int, int]:
    n_lines = TEXT.count("\n") + 1
    px = 56
    while px > 30 and (F.WL.wall_height(TEXT, px) > 380 or len([x for x in F.WL.wall_lines(TEXT, px) if x]) > n_lines):
        px -= 1
    F.WL.render_wall(TEXT, px, TOP, dest)
    from PIL import Image
    return Image.open(dest).getbbox()


def clean_ranks(name: str) -> Path:
    """Строку «ARIA VALE / Game creator» закрываем белым (она прямо под текстом ролика и мешает читать; Aria Vale видна вторым местом)."""
    out = ROOT / "output" / "_work" / "drops_ghost" / f"clean_{name}"
    if out.exists():
        return out
    from PIL import Image, ImageDraw
    import numpy as np
    im = Image.open(RANKS / name).convert("RGB")
    col = np.asarray(im.convert("L"))[:, 1000]
    dark = np.where(col < 60)[0]
    runs = np.split(dark, np.where(np.diff(dark) > 1)[0] + 1)
    top = next(int(r[-1]) for r in runs if len(r) and r[0] > 150 and r[-1] < 300) + 2       # низ чёрной полосы над панелью
    sep = next(int(r[0]) for r in runs if len(r) and r[0] > 500)                              # линия под строкой автора
    ImageDraw.Draw(im).rectangle((0, top, im.width, sep - 2), fill=(255, 255, 255))
    im.save(out)
    return out


def render(job: tuple[dict, str, str]) -> str:
    r, dest, png = job
    inputs, fc, labels = [], [], []
    mir = "hflip," if r["mirror"] else ""
    k = 0
    for c, st, ln in r["face"]:
        inputs += ["-ss", f"{st}", "-t", f"{ln + .3:.2f}", "-i", str(FACES / f"{c}.MOV")]
        fc.append(f"[{k}:v]fps={FPS},{mir}scale={W}:{H}:flags=lanczos:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,"
                  f"trim=end_frame={round(ln * FPS)},setpts=PTS-STARTPTS[p{k}]")
        labels.append(f"[p{k}]")
        k += 1
    z = r["ranks_z"]
    inputs += ["-loop", "1", "-t", f"{r['ranks_len'] + .2:.2f}", "-i", str(clean_ranks(r["ranks"]))]
    fc.append(f"[{k}:v]fps={FPS},scale={W}:{H}:flags=lanczos:force_original_aspect_ratio=increase,crop={W}:{H}:0:0,crop=iw/{z}:ih/{z}:(iw-iw/{z})/2:(ih-ih/{z})*0.3,scale={W}:{H}:flags=lanczos,"
              f"setsar=1,format=yuv420p,trim=end_frame={round(r['ranks_len'] * FPS)},setpts=PTS-STARTPTS[p{k}]")
    labels.append(f"[p{k}]")
    k += 1
    game = GAMES / f"{r['game']}.mp4"
    for t, ln in ((r["g0"], r["cut1"]), (r["g1"], r["cut2"])):
        inputs += ["-ss", f"{t}", "-t", f"{ln + .3:.2f}", "-i", str(game)]
        fc.append(f"[{k}:v]fps={FPS},crop=ih*9/16:ih,scale={W}:{H}:flags=lanczos,setsar=1,trim=end_frame={round(ln * FPS)},setpts=PTS-STARTPTS[p{k}]")
        labels.append(f"[p{k}]")
        k += 1
    total = sum(ln for _, _, ln in r["face"]) + r["ranks_len"] + r["cut1"] + r["cut2"]
    fc.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0,format=yuv420p[b]")
    mpath = (DBAND / DROPS_SONGS[r["music"]] if r["music"] in DROPS_SONGS else DUGC[r["music"]] if r["music"] in DUGC
             else MUSIC[r["music"]][0])
    inputs += ["-i", png, "-ss", f"{r['music_t']}", "-i", str(mpath)]
    fc.append(f"[b][{k}:v]overlay=0:0,format=yuv420p[v]")
    level = f"volume={r['gain']}dB,alimiter=limit=0.95" if "gain" in r else "loudnorm=I=-14:TP=-1.5:LRA=11"
    fc.append(f"[{k + 1}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,aresample=44100,{level},"
              f"afade=t=out:st={total - .35:.3f}:d=0.35[a]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
                    "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=", "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", dest],
                   check=True)
    return Path(dest).name


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--batch", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--music", default="trend", choices=["trend", "drops", "dugc"])
    ap.add_argument("--tracks", nargs="*", help="dugc: только эти треки (ключи DUGC)")
    ap.add_argument("--tt", type=int, default=100)
    ap.add_argument("--yt", type=int, default=200)
    a = ap.parse_args()
    rows = plan(a.tt + a.yt, 9912)
    if a.music == "drops":
        rows = to_drops(rows)
    elif a.music == "dugc":
        rows = to_dugc(rows, a.tracks)
    work = ROOT / "output" / "_work" / "drops_ghost"
    work.mkdir(parents=True, exist_ok=True)
    png = work / "text.png"
    box = text_png(png)
    if bad := check_box(W, H, box):
        raise SystemExit(f"текст вне безопасной зоны {box}: {bad}")
    print("текст:", box)
    if a.test:
        if a.music == "dugc":                        # каждая точка из тюнера по разу
            out = ROOT / "output" / "drops_ghost_test_dugc"
            n_pts = len([pt for pt in dugc_points() if not a.tracks or pt[0] in a.tracks])
            jobs = [(rows[i], str(out / f"{i + 1:02d}_{rows[i]['music']}_{rows[i]['drop']:.2f}s.mp4"), str(png))
                    for i in range(n_pts)]
        elif a.music == "drops":                     # каждая точка дропа каждой песни по разу
            out = ROOT / "output" / "drops_ghost_test_drops"
            jobs = [(rows[i], str(out / f"{i + 1:02d}_{rows[i]['music'][4:].lower()}_{rows[i]['drop']:.0f}s.mp4"), str(png))
                    for i in range(len(drop_points()))]
        else:
            out = ROOT / "output" / "drops_ghost_test"
            jobs = [(rows[i], str(out / f"{i + 1:03d}_test.mp4"), str(png)) for i in range(8)]
    else:
        jobs = []
        for idx, folder in ((range(0, a.tt), f"drops_1_TT_{a.tt}"), (range(a.tt, a.tt + a.yt), f"drops_1_YT_{a.yt}")):   # клиент: drops_<ID>_…
            out = ROOT / "output" / folder
            out.mkdir(parents=True, exist_ok=True)
            man = {}
            for k, i in enumerate(idx, 1):
                dest = out / f"{k:03d}_1.mp4"                  # ID 1
                man[dest.name] = rows[i]
                if not dest.exists():                          # перезапуск доделывает только недостающие
                    jobs.append((rows[i], str(dest), str(png)))
            (work / f"manifest_{folder}.json").write_text(json.dumps(man, indent=0), encoding="utf-8")
    for j in jobs:
        Path(j[1]).parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(a.jobs) as ex:
        for name in ex.map(render, jobs):
            print(" ", name, flush=True)
    print(f"готово: {len(jobs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
