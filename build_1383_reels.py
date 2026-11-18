#!/usr/bin/env python3
"""
1383 — Inspoy, нарезка из трёх частей, 100 роликов 9:16, 8.5 с:
  1) реакция лица 3 с — исходники клиента (Drive → downloads/1383/src/face_1.mov блокнот, face_2.mov кофе), вступление
     срезано, старт с эмоции; текст — одна из двух фраз ТЗ в кавычках (поровну);
  2) осенние коллажи образов 4 с — 9 досок на белом (Pinterest, harvest_carousel_pool.py --profile ob_fall →
     output/_work/1383/boards/_full), смена по сетке нарезки рефа @aiyah.777 (как 1345); текст «5 minutes, one app,
     all these outfits»;
  3) концовка 1.5 с — жест «тсс» (end_1.mov), текст «save the name: Inspoy: Outfit Maker, Planner» над головой и
     карточка приложения в App Store (build_1319_carousels.app_card) на груди под подбородком.
Звук — тот же реф-звук @aiyah.777 (downloads/inspoy_found/music/ref_sound.mp3), −14 LUFS, обрезан так, что его дроп
(5.06 с) приходится ровно на первую доску, доски меняются на каждый бит (0.6105 с), концовка — тоже на бите. Тексты дословно, TikTok-шрифт белый с обводкой, переносы по смыслу, в безопасной зоне.
Исходники iPhone 4K HLG 60 к/с → один раз в 1080×1920 30 к/с (кэш output/_work/1383/clips) с тонмаппингом HLG→SDR
(zscale + hable, npl 120): без него девушка бледная и плоская (пользователь: «бледные … поиграться с экспозицией»).
Итоговая сотня: 001–050 — доски с Pinterest, 051–100 — наши доски из 1345 (downloads/inspoy_found/gen51). Кодирование — h264_nvenc, финальные cq 27 / maxrate 6M. Рабочие файлы — output/_work/1383.

  python build_1383_reels.py --test          # 4 ролика → output/_work/1383/test
  python build_1383_reels.py -n 100          # → output/1383_100/NNN_1383.mp4
  python build_1383_reels.py --test -n 5 --boards downloads/inspoy_found/gen51 --out output/_work/1383/test_own
  # итог: 001–050 — Pinterest, 051–100 — наши доски 1345:
  python build_1383_reels.py -n 100 --last 50
  python build_1383_reels.py -n 100 --first 51 --boards downloads/inspoy_found/gen51
  # YT 150 (2026-11-06): 001–075 Pinterest, 076–150 наши; другой сид, наборы прошлой сотни исключены:
  python build_1383_reels.py -n 150 --seed 2383 --avoid --last 75 --jobs 5 --out output/1383_YT_150
  python build_1383_reels.py -n 150 --seed 2383 --avoid --first 76 --jobs 5 --boards downloads/inspoy_found/gen51 --out output/1383_YT_150
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1303_reels as T  # noqa: E402  (text_png — белый TikTok-текст с обводкой в полосе BAND)
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF = T.FF
ID = "1383"
W, H, FPS = 1080, 1920, 30
D = ROOT / "downloads" / "1383"
WORK = ROOT / "output" / "_work" / ID
BOARDS = WORK / "boards" / "_full"
MUSIC = ROOT / "downloads" / "inspoy_found" / "music" / "ref_sound.mp3"
NL = chr(10)
# части: (клип, начало эмоции в исходнике, длительность)
FACES = [("face_1", 1.25), ("face_2", 2.5)]           # блокнот: лицо над раскрытым блокнотом с 1.25 с; кофе: удивление с 2.5 с
ENDS = [("end_1", 1.75)]                               # палец у губ 1.75–3.25 с (концовок может быть несколько)
JITTER = [0.0, 0.1, 0.2, 0.3]                          # сдвиг старта лица (разные первые кадры)
# звук рефа: брейк 4.3–5.06 с, дроп (вход баса) 5.06 с, дальше бит 0.6105 с (98.3 BPM; сетка подобрана по пикам
# спектрального потока и низов). Звук режем с MUSIC_OFFSET, чтобы дроп пришёлся ровно на первую доску (P1 = 3 с),
# доски меняются на каждый бит: 7 досок × 1 бит (≈4.27 с вместо 4 с ТЗ — чтобы и концовка началась на бите).
DROP, BEAT, N_BOARDS = 5.085, 0.6105, 7       # дроп 5.06 + 25 мс: склейки точно на ударах (замер по готовому ролику)
P1, P3 = 3.0, 1.5
P2 = N_BOARDS * BEAT
TOTAL = P1 + P2 + P3
MUSIC_OFFSET = DROP - P1
CUTS = [round(P1 + k * BEAT, 4) for k in range(N_BOARDS + 1)]
TEXT1 = [NL.join(["“i have no idea", "how to combine my clothes”"]),
         NL.join(["“i have so many clothes", "but i can't make outfits", "out of them”"])]
TEXT2 = NL.join(["5 minutes, one app,", "all these outfits"])
TEXT3 = NL.join(["save the name:", "Inspoy: Outfit Maker, Planner"])
BAND1 = (1060, 1500)                                   # под подбородком: блокнот / кофе
BAND2 = (840, 1080)                                    # середина доски (как 1345)
BAND3 = (205, 385)                                     # над головой (стена) — внизу карточка App Store
CARD_W, CARD_BOTTOM = 640, 1525                        # карточка App Store: по центру, низ — в безопасной зоне
# HLG → bt709: линейный свет (npl 120 — ярче, чем 203 по умолчанию), hable, обратно в bt709 tv
TONEMAP = ("zscale=t=linear:npl=120,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
           "zscale=t=bt709:m=bt709:r=tv")


def clip(name: str) -> Path:
    """Исходник iPhone → 1080×1920 30 к/с (кэш), без звука; HLG — с тонмаппингом, SDR — как есть."""
    out = WORK / "clips" / f"{name}.mp4"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        src = D / "src" / f"{name}.mov"
        trc = subprocess.run([FF.replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "stream=color_transfer", "-of", "csv=p=0", str(src)],
                             capture_output=True, text=True).stdout.strip()
        tm = f"{TONEMAP}," if trc == "arib-std-b67" else ""
        subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-an", "-vf",
                        f"{tm}scale={W}:{H}:flags=lanczos,fps={FPS},format=yuv420p,{SET_SDR}", "-c:v", "h264_nvenc",
                        "-preset", "p6", "-rc", "vbr", "-cq", "16", "-b:v", "0", *SDR_COLOR_ARGS, str(out)], check=True)
    return out


def board_frame(src: Path) -> Path:
    """Доска целиком в кадре 9:16 (по ширине; если высокая — по высоте); поля — цветом края самой доски,
    чтобы не было видно прямоугольника светло-серой доски на белом."""
    out = WORK / "frames" / f"{src.stem}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        im = Image.open(src).convert("RGB")
        sc = min(W / im.width, H / im.height)
        im = im.resize((round(im.width * sc), round(im.height * sc)), Image.Resampling.LANCZOS)
        import numpy as np
        a = np.asarray(im)
        edge = np.concatenate([a[:4].reshape(-1, 3), a[-4:].reshape(-1, 3), a[:, :4].reshape(-1, 3), a[:, -4:].reshape(-1, 3)])
        bg = Image.new("RGB", (W, H), tuple(int(v) for v in np.median(edge, axis=0)))
        bg.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
        bg.save(out, quality=95)
    return out


def texts() -> dict:
    """PNG текстов (полоса у каждой части своя)."""
    out = {}
    for key, text, band in [("t1_0", TEXT1[0], BAND1), ("t1_1", TEXT1[1], BAND1), ("t2", TEXT2, BAND2),
                            ("t3", TEXT3, BAND3)]:
        p = WORK / "text" / f"{key}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        T.BAND = band
        out[key] = (p, T.text_png(text, p))
    out["card"] = (app_card_png(), CARD_W)
    return out


def app_card_png() -> Path:
    """Карточка Inspoy в App Store (шапка страницы приложения, тёмная тема) со скруглёнными углами, на груди."""
    import build_1319_carousels as AS
    from PIL import ImageDraw
    from core.safe_zones import check_box
    p = WORK / "text" / "card.png"
    c = AS.app_card(CARD_W)
    m = Image.new("L", (c.width * 4, c.height * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, c.width * 4 - 1, c.height * 4 - 1), radius=22 * 4, fill=255)
    c.putalpha(m.resize(c.size, Image.Resampling.LANCZOS))
    box = ((W - c.width) // 2, CARD_BOTTOM - c.height, (W + c.width) // 2, CARD_BOTTOM)
    bad = check_box(W, H, box)
    if bad:
        raise SystemExit(f"карточка App Store вне безопасной зоны: {bad}")
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(c, box[:2])
    canvas.save(p)
    return p


def music() -> Path:
    norm = WORK / "music_-14lufs.wav"
    if not norm.exists():
        log = subprocess.run([FF, "-hide_banner", "-i", str(MUSIC), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                              "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
        j = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log).group(0))
        subprocess.run([FF, "-v", "error", "-y", "-i", str(MUSIC), "-af",
                        f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:"
                        f"measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}:"
                        "linear=true,aresample=48000", "-ac", "2", "-c:a", "pcm_s16le", str(norm)], check=True)
    return norm


def plan(n: int, bdir: Path = BOARDS, seed: int = int(ID), avoid: set | None = None) -> list[dict]:
    """Лицо, сдвиг старта и фраза — по кругу; 9 досок — реже всего использованные (с шумом), набор не повторяется.
    seed/avoid — для новых партий (YT): свой сид и наборы прошлых партий в исключениях."""
    rng = random.Random(seed)
    pool = sorted(p.name for p in bdir.glob("*.jpg"))
    use = {p: 0 for p in pool}
    seen, jobs = set(avoid or ()), []
    for i in range(n):
        face, f0 = FACES[i % len(FACES)]
        end, e0 = ENDS[(i // (2 * len(FACES))) % len(ENDS)]
        for _ in range(200):
            seq = sorted(pool, key=lambda p: use[p] + rng.random() * 1.5)[:len(CUTS) - 1]
            rng.shuffle(seq)
            if tuple(seq) not in seen:
                break
        seen.add(tuple(seq))
        for p in seq:
            use[p] += 1
        jobs.append({"n": i + 1, "face": face, "f0": round(f0 + JITTER[(i // 4) % len(JITTER)], 3),
                     "text": (i // len(FACES)) % 2, "end": end, "e0": e0, "boards": seq, "bdir": str(bdir)})
    return jobs


def build(job: dict) -> str:
    out = Path(job["out"])
    dest = out / f"{job['n']:03d}_{ID}.mp4"
    tx = texts_cached()
    lst = WORK / "lists" / f"{Path(job['out']).name}_{job['n']:03d}.txt"
    lst.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    bdir = Path(job["bdir"])
    for b, a, z in zip(job["boards"], CUTS[:-1], CUTS[1:]):
        rows += [f"file '{board_frame(bdir / b).as_posix()}'", f"duration {z - a:.3f}"]
    rows.append(f"file '{board_frame(bdir / job['boards'][-1]).as_posix()}'")
    lst.write_text(NL.join(rows) + NL, encoding="utf-8")
    vf = f"fps={FPS},format=yuv420p,setsar=1"
    parts = [f"[0:v]trim=duration={P1},setpts=PTS-STARTPTS,{vf}[f]",
             f"[1:v]{vf},trim=duration={P2},setpts=PTS-STARTPTS[b]",
             f"[2:v]trim=duration={P3},setpts=PTS-STARTPTS,{vf}[e]",
             "[f][3:v]overlay=0:0[p1]", "[b][4:v]overlay=0:0[p2]", "[e][5:v]overlay=0:0[e2]", "[e2][7:v]overlay=0:0[p3]",
             f"[p1][p2][p3]concat=n=3:v=1:a=0,format=yuv420p,{SET_SDR}[v]",
             f"[6:a]atrim=duration={TOTAL},afade=t=out:st={TOTAL - 0.3}:d=0.3,asetpts=PTS-STARTPTS[a]"]
    subprocess.run([FF, "-v", "error", "-y",
                    "-ss", f"{job['f0']:.3f}", "-t", f"{P1 + 0.2}", "-i", str(clip(job["face"])),
                    "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-ss", f"{job['e0']:.3f}", "-t", f"{P3 + 0.2}", "-i", str(clip(job["end"])),
                    "-i", str(tx[f"t1_{job['text']}"][0]), "-i", str(tx["t2"][0]), "-i", str(tx["t3"][0]),
                    "-ss", f"{MUSIC_OFFSET:.3f}", "-i", str(music()), "-i", str(tx["card"][0]),
                    "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]", "-t", f"{TOTAL}",
                    "-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "27", "-b:v", "0",
                    "-maxrate", "6M", "-bufsize", "12M", "-profile:v", "high", "-r", str(FPS), *SDR_COLOR_ARGS,
                    "-c:a", "aac", "-b:a", "192k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    return dest.name


_TX: dict = {}


def texts_cached() -> dict:
    if not _TX:
        _TX.update({k: (WORK / "text" / f"{k}.png", 0) for k in ("t1_0", "t1_1", "t2", "t3", "card")})
    return _TX


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("--test", action="store_true", help="4 ролика → output/_work/1383/test")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--boards", type=Path, default=BOARDS, help="папка досок (по умолчанию — Pinterest-пул)")
    ap.add_argument("--out", type=Path, help="папка роликов (по умолчанию output/1383_<n>, с --test — _work/1383/test)")
    ap.add_argument("--first", type=int, default=1, help="собрать только ролики с номера first (план тот же)")
    ap.add_argument("--last", type=int, default=10 ** 6, help="… и по номер last")
    ap.add_argument("--seed", type=int, default=int(ID), help="сид плана; для новой партии (YT) — другой")
    ap.add_argument("--avoid", action="store_true", help="исключить наборы досок из manifest_100_*.json (прошлая сотня)")
    args = ap.parse_args()
    T.PX_MAX = 64
    for k, (p, px) in texts().items():
        print(f"текст {k}: {px} px", flush=True)
    for name in [f for f, _ in FACES] + [e for e, _ in ENDS]:
        clip(name)
    music()
    avoid = set()
    if args.avoid:
        for mf in WORK.glob("manifest_100_*.json"):
            avoid |= {tuple(j["boards"]) for j in json.loads(mf.read_text(encoding="utf-8"))}
    jobs = plan(args.n if args.test and args.n != 100 else 4 if args.test else args.n, args.boards, args.seed, avoid)
    out = args.out or (WORK / "test" if args.test else ROOT / "output" / f"{ID}_{args.n}")
    out.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        j["out"] = str(out)
    mname = "test" if args.test else (f"{out.name}_{Path(args.boards).name}" if args.out else str(args.n))
    (WORK / f"manifest_{mname}.json").write_text(json.dumps(jobs, indent=1), encoding="utf-8")
    pool = len(list(args.boards.glob("*.jpg")))
    print(f"досок в пуле: {pool}; уникальных наборов: {len({tuple(j['boards']) for j in jobs})} из {len(jobs)}", flush=True)
    todo = [j for j in jobs if args.first <= j["n"] <= args.last and not (out / f"{j['n']:03d}_{ID}.mp4").exists()]
    with ProcessPoolExecutor(args.jobs) as ex:
        for k, name in enumerate(ex.map(build, todo), 1):
            print(f"[{k}/{len(todo)}] {name}", flush=True)
    print(f"готово → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
