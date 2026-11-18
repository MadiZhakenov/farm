#!/usr/bin/env python3
"""
Drops react (айди пока нет): 9:16 ролик ~33 с по рефу @setups_ai — 3 с реакции лицом, дальше запись экрана Drops
(загрузка трека → Wizard → игра собрана → геймплей) под озвучку клиента (7 строк getchipbot, только их) + субтитры
по словам на тёмных плашках (текст ТЗ дословно, тайминги — Whisper), фоном — звук из TikTok (клиент), тихо и ровно, без приглушения.

Источники: downloads/drops_react/faces/IMG_*.MOV (12 реакций), output/drops_react/rec/upload2_cut.mp4 (загрузка,
Aria Vale), flow2.mp4 (Wizard заново на треке Aria Vale — без русской фамилии), game1.mp4 (титул игры),
output/drops_react/gameplay/shooter_ariavale_*.mp4 (заходы в игру, окна живой игры — gameplay/_runs.json),
downloads/drops_react/voice/line_N.mp3 + words.json.

Партия: у каждого ролика своё лицо (по кругу) и момент реакции, свои куски геймплея из разных заходов, сдвиги окон
записи экрана, свой отрезок фоновой песни и лёгкий зум — 150 разных роликов.

  python build_drops_react.py --face IMG_5724 --out output/drops_react/test/react_01.mp4
  python build_drops_react.py -n 150 --out-dir output/drops_react_150
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DL = ROOT / "downloads" / "drops_react"
REC = ROOT / "output" / "drops_react" / "rec"
FLOW, GAME = REC / "flow2.mp4", REC / "game1.mp4"
GP = ROOT / "output" / "drops_react" / "gameplay"
RUNS: dict[str, list[float]] = {}          # заход → [начало, конец] живой игры (до экрана Game over), gameplay/_runs.json
UPLOAD = REC / "upload2_cut.mp4"   # пересъёмка загрузки: party_pop_final.mp3 / Party Pop / Aria Vale (без русской фамилии)
VOICE = DL / "voice"
MUSIC = DL / "music" / "tt_7701860468008258335.mp3"   # звук из TikTok (клиент): фоном, тихо и ровно
W, H, FPS = 1080, 1920, 30
GAP = 0.06                      # пауза между строками озвучки — «как можно короче»
FACE_DUR = 3.0

# текст ТЗ дословно, по строкам озвучки (слова совпадают с распознанными по счёту → берём их тайминги)
SCRIPT = [
    "guys, why is nobody talking about this app.",
    "i uploaded my own song. just a regular track. and i answered a few questions, nothing complicated.",
    "and it made a whole game out of it.",
    "like, the game moves with the tempo. it changes with the mood of the song. it’s actually built around it.",
    "i sent the link to my friends, and they played it. they actually opened my music for the first time.",
    "I don’t even know how it works.",
    "but yeah. it’s called drops. and i honestly can’t stop thinking about it.",
]


def timeline() -> tuple[list[float], list[list[tuple[str, float, float]]], float]:
    """Начала строк на общей шкале + слова ТЗ с абсолютными временами; длина озвучки."""
    words = json.loads((VOICE / "words.json").read_text(encoding="utf-8"))
    starts, out, t = [], [], 0.0
    for i, line in enumerate(SCRIPT, 1):
        asr = words[f"line_{i}"]["words"]
        tz = line.split()
        if len(tz) != len(asr):
            raise SystemExit(f"строка {i}: слов в ТЗ {len(tz)}, распознано {len(asr)}")
        starts.append(t)
        out.append([(w, t + a, t + (b if b else a + 0.3)) for w, (_x, a, b) in zip(tz, asr)])
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                    str(VOICE / f"line_{i}.mp3")], capture_output=True, text=True).stdout)
        t += dur + GAP
    return starts, out, t - GAP


def at(starts, words, line: int, word: int) -> float:
    """Время начала слова № word (с 0) в строке line (с 1)."""
    return words[line - 1][word][1]


def gp_piece(rng: random.Random, dur: float, used: set) -> tuple[Path, float]:
    """Кусок живой игры длиной dur из случайного захода; не повторяем уже взятые в этом ролике отрезки."""
    for _ in range(80):
        name, (g0, g1) = rng.choice(list(RUNS.items()))
        if g1 - g0 < dur + 0.2:
            continue
        s0 = round(rng.uniform(g0, g1 - dur), 1)
        if all(abs(s0 - u) > 1.5 for n, u in used if n == name):
            used.add((name, s0))
            return GP / f"{name}.mp4", s0
    raise SystemExit("мало геймплея для куска")


def segments(face: Path, face_t: float, starts, words, end: float, rng: random.Random) -> list[tuple]:
    """(источник, s0, s1, начало на шкале). Конец сегмента = начало следующего; скорость подгоняется под окно,
    кроме геймплея и реакции (s1 = None → берём столько, сколько нужно, со скоростью 1).
    Окна flow2 сдвигаются на ±0,4 с, куски геймплея — из разных заходов."""
    a = lambda li, wi: at(starts, words, li, wi)          # noqa: E731
    j = lambda x: round(x + rng.uniform(-0.4, 0.4), 2)    # noqa: E731
    marks = [0.0, FACE_DUR, a(2, 5), a(2, 9), a(2, 13), a(2, 15), starts[2], a(3, 5), starts[3], starts[4], a(5, 7),
             starts[5], starts[6], a(7, 5), end + 0.35]
    used: set = set()
    g8, g10, g13 = (gp_piece(rng, marks[k + 1] - marks[k], used) for k in (8, 10, 13))
    return [
        (face, face_t, None, marks[0]),                     # реакция: «guys, why is nobody talking…»
        (UPLOAD, 0.0, 14.5, marks[1]),                      # «i uploaded my own song» — файл, название, артист
        (FLOW, j(6.5), j(12.5), marks[2]),                  # «just a regular track» — Party Pop · Aria Vale · 126 BPM
        (FLOW, j(24.5), j(30.0), marks[3]),                 # «and i answered…» — тип игры, настройки
        (FLOW, j(33.5), j(39.5), marks[4]),                 # «questions,» — персонаж
        (FLOW, j(40.5), j(53.0), marks[5]),                 # «nothing complicated» — мир, стиль → Build
        (FLOW, 53.6, 56.0, marks[6]),                       # «and it made a whole game» — Building your game
        (FLOW, j(90.5), 94.5, marks[7]),                    # «game out of it» — YOUR GAME IS LIVE
        (g8[0], g8[1], None, marks[8]),                     # «like, the game moves with the tempo…»
        (FLOW, 94.0, 97.8, marks[9]),                       # «i sent the link to my friends» — Copy link
        (g10[0], g10[1], None, marks[10]),                  # «and they played it…»
        (FLOW, j(77.5), j(85.5), marks[11]),                # «I don't even know how it works» — живое превью
        (GAME, j(142.0), None, marks[12]),                  # «but yeah. it's called drops» — титул игры
        (g13[0], g13[1], None, marks[13]),                  # «and i honestly can't stop…»
        ("END", 0, 0, marks[14]),
    ]


def sub_chunks(words) -> list[tuple[str, float, float]]:
    """Субтитры по 1–3 слова: новая плашка после точки/запятой или когда строка длиннее ~16 символов."""
    out = []
    for line in words:
        cur, t0 = [], None
        for k, (w, a, b) in enumerate(line):
            if not cur:
                t0 = a
            cur.append(w)
            nxt = line[k + 1][1] if k + 1 < len(line) else b
            text = " ".join(cur)
            if w[-1] in ",.!?" or len(cur) == 3 or len(text) >= 14 or k + 1 == len(line):
                out.append((text, t0, nxt))
                cur = []
    return out


def sub_png(text: str, path: Path) -> tuple[int, int]:
    """Белый жирный текст на тёмной скруглённой плашке: читается и на белом/жёлтом сайте, и на тёмном геймплее
    (белые буквы с обводкой сливались с интерфейсом). Ширина ≤ 800 (безопасная рамка 9:16: x 140–940)."""
    from PIL import Image, ImageDraw, ImageFont
    font_path = ROOT / "fonts" / "TikTokSans-Bold.ttf"
    for px in range(84, 40, -2):
        f = ImageFont.truetype(str(font_path), px)
        tw = f.getlength(text)
        if tw + px <= 800:
            break
    asc, desc = f.getmetrics()
    padx, pady = int(px * 0.42), int(px * 0.22)
    w, h = int(tw + 2 * padx), asc + desc + 2 * pady
    ss = 3
    im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=int(h * 0.3 * ss), fill=(12, 12, 12, 225))
    d.text((padx * ss, pady * ss), text, font=ImageFont.truetype(str(font_path), px * ss), fill="white")
    im = im.resize((w, h), Image.Resampling.LANCZOS)
    im.save(path)
    return im.size


def render(face: Path, face_t: float, out: Path, rng: random.Random, music_vol: float, sub_y: int,
           zoom: float = 1.0, music_t: float = 0.0) -> float:
    starts, words, vo_end = timeline()
    segs = segments(face, face_t, starts, words, vo_end, rng)
    work = out.parent / f"_{out.stem}"
    work.mkdir(parents=True, exist_ok=True)
    srcs = sorted({str(sg[0]) for sg in segs if sg[0] != "END"})
    ins = []
    for sp in srcs:
        ins += ["-i", sp]
    idx = {sp: i for i, sp in enumerate(srcs)}
    zw, zh = round(W * zoom / 2) * 2, round(H * zoom / 2) * 2         # лёгкий зум и свой сдвиг кадра
    cx, cy = rng.randint(0, zw - W), rng.randint(0, zh - H)
    fc, labels = [], []
    for k, (src, s0, s1, t0) in enumerate(segs[:-1]):
        dur = segs[k + 1][3] - t0
        if s1 is None:
            s1, speed = s0 + dur, 1.0
        else:
            speed = (s1 - s0) / dur
        fc.append(f"[{idx[str(src)]}:v]trim=start={s0:.3f}:end={s1:.3f},setpts=(PTS-STARTPTS)/{speed:.4f},"
                  f"fps={FPS},scale={zw}:{zh}:force_original_aspect_ratio=increase,crop={zw}:{zh},"
                  f"crop={W}:{H}:{cx}:{cy},setsar=1,trim=end_frame={round(dur * FPS)},setpts=PTS-STARTPTS[v{k}]")
        labels.append(f"[v{k}]")
    fc.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0,format=yuv420p[base]")
    subs = sub_chunks(words)
    n_in = len(srcs)
    sub_in, last = [], "base"
    for jx, (text, t0, t1) in enumerate(subs):
        p = work / f"sub_{jx:02d}.png"
        sw, sh = sub_png(text, p)
        sub_in += ["-i", str(p)]
        x, y = (W - sw) // 2, sub_y - sh // 2
        fc.append(f"[{last}][{n_in + jx}:v]overlay={x}:{y}:enable='between(t,{t0:.3f},{t1:.3f})'[s{jx}]")
        last = f"s{jx}"
    a_in, mix = [], []
    base = n_in + len(subs)
    for i, t0 in enumerate(starts, 1):
        a_in += ["-i", str(VOICE / f"line_{i}.mp3")]
        ms = round(t0 * 1000)
        fc.append(f"[{base + i - 1}:a]adelay={ms}|{ms},aformat=channel_layouts=stereo[a{i}]")
        mix.append(f"[a{i}]")
    a_in += ["-stream_loop", "-1", "-i", str(MUSIC)]
    total = segs[-1][3]
    # песня — ровно и тихо на фоне, без приглушения под голос (клиент: «приглушаешь при голосе — ужасно»)
    fc.append("".join(mix) + f"amix=inputs={len(mix)}:normalize=0[vo]")
    fc.append(f"[{base + len(starts)}:a]atrim=start={music_t:.2f}:end={music_t + total:.3f},asetpts=PTS-STARTPTS,"
              f"volume={music_vol},aformat=channel_layouts=stereo[mus]")
    fc.append(f"[vo][mus]amix=inputs=2:normalize=0,atrim=end={total:.3f},afade=t=out:st={total - 0.3:.3f}:d=0.3[aout]")
    cmd = ["ffmpeg", "-v", "error", "-y", *ins, *sub_in, *a_in, "-filter_complex", ";".join(fc),
           "-map", f"[{last}]", "-map", "[aout]", "-t", f"{total:.3f}",
           "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
           "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
           "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
           "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    shutil.rmtree(work, ignore_errors=True)
    return total


def faces() -> list[tuple[Path, float]]:
    out = []
    for f in sorted((DL / "faces").glob("IMG_*.MOV")):
        d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                  str(f)], capture_output=True, text=True).stdout)
        out.append((f, d))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--face", default="IMG_5724")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "drops_react" / "test" / "react_01.mp4")
    ap.add_argument("-n", type=int, default=0, help="партия: n роликов в --out-dir")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "output" / "drops_react_150")
    ap.add_argument("--start", type=int, default=1, help="с какого номера (дозапуск / параллельные куски)")
    ap.add_argument("--end", type=int, default=0, help="по какой номер включительно (0 = до n)")
    ap.add_argument("--seed", type=int, default=150)
    ap.add_argument("--music-vol", type=float, default=0.12, help="громкость фоновой песни (постоянная)")
    ap.add_argument("--sub-y", type=int, default=1390, help="центр субтитров по вертикали (нижняя треть, ≤ 1540)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    RUNS.update(json.loads((GP / "_runs.json").read_text(encoding="utf-8")))
    if not a.n:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        total = render(DL / "faces" / f"{a.face}.MOV", 0.4, a.out, random.Random(a.seed), a.music_vol, a.sub_y)
        print(f"готово: {a.out} ({total:.2f} с)")
        return 0
    fl = faces()
    rng = random.Random(a.seed)
    order = []
    while len(order) < a.n:                                          # лица по кругу, в каждом круге свой порядок
        order += rng.sample(fl, len(fl))
    a.out_dir.mkdir(parents=True, exist_ok=True)
    end = a.end or a.n
    man_f = a.out_dir / f"manifest_{a.start:03d}.json"                  # свой файл у каждого куска
    manifest = []
    for i in range(a.start, end + 1):
        f, fd = order[i - 1]
        r = random.Random(a.seed * 1000 + i)
        face_t = round(r.uniform(0.2, max(0.3, fd - FACE_DUR - 0.2)), 2)
        zoom, music_t = round(r.uniform(1.0, 1.05), 3), round(r.uniform(0, 14), 2)
        out = a.out_dir / f"{i:03d}_noid.mp4"
        render(f, face_t, out, r, a.music_vol, a.sub_y, zoom, music_t)
        manifest.append({"video": out.name, "face": f.name, "face_t": face_t, "zoom": zoom, "music_t": music_t})
        man_f.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        print(f"  {out.name}", flush=True)
    print(f"готово: {a.n} → {a.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
