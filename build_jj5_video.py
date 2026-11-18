#!/usr/bin/env python3
"""
June's Journey 5 (ID 1) — карусели «бабушкины хобби» как видео 9:16: 6 слайдов листаются свайпом влево (как фото-карусель
в TikTok), как делали «папа-дальнобойщик» и «новогодние образы» (общий движок swipe_video.py). Юзер 16.11: 150 TT + 100 YT
всего, спокойная песня как в June's Journey 2 (cozy) — юзер одобрил все 6 вариантов («Найс, делай») → песни по кругу.

Слайды — те же фото из Flow, тексты ТЗ дословно, оформление как в карусели (build_jj5_carousels: TikTok Sans, белый
с чёрной обводкой, волны света, зерно), но в рамке 9:16 (x 140–940, y 200–1540). Свайп каждые ~2 с (обложка 2.4 с,
финал 3.2 с, ~13.6 с), конец каждого свайпа — на ближайшей доле песни. У каждого видео свой кадр фото (вариант из Flow,
зум 1.0–1.12 со сдвигом, свет, тёплость), своя песня и своё место в песне. TT/YT — разные сиды, повторов нет.

  python build_jj5_video.py --test                    # 3 теста (v1, v2, v3) → output/_work/jj5_video/test
  python build_jj5_video.py --tt 150 --yt 100         # → output/junes_journey_5_video_TT_150 + _YT_100
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_jj5_carousels as C  # noqa: E402
import swipe_video as SV  # noqa: E402
from core.gpu_slots import gpu_slot  # noqa: E402
from core.safe_zones import check_box, text_rect  # noqa: E402

W, H = SV.W, SV.H
# раскладка карусели — в рамке 9:16 (функции build_jj5_carousels берут W/H/X0… из своего модуля)
C.W, C.H = W, H
C.X0, C.Y0, C.X1, C.Y1 = text_rect(W, H)
WORK = ROOT / "output" / "_work" / "jj5_video"
_M5, _MJ = ROOT / "downloads" / "junes_journey_5" / "music", ROOT / "downloads" / "junes_journey" / "music"
SONGS = [_MJ / "autumn_leaves_timothy_cole.mp3", _MJ / "venus_and_flower.mp3", _MJ / "stardew_mori_original.mp3",
         _M5 / "autumn_piano_621532.mp3", _M5 / "cozy_lofi_split_memories_248205.mp3",
         _M5 / "chillhop_jazz_coffee_552792.mp3"]
HOLDS = [2.4, 2.0, 2.0, 2.0, 2.0, 3.2]                  # с на слайд — скорость как у «папы» и «образов» (~2 с)


def beats_of(song: Path) -> list[float]:
    import librosa
    y, sr = librosa.load(song, sr=22050, mono=True)
    _, b = librosa.beat.beat_track(y=y, sr=sr)
    return [float(t) for t in librosa.frames_to_time(b, sr=sr)] + [len(y) / sr]


def timing(beats: list[float], dur: float, rng: random.Random) -> tuple[float, list[float], float]:
    """Старт песни на доле (после вступления), концы свайпов — на ближайших долях к плану HOLDS."""
    total = round(round(sum(HOLDS) * SV.FPS) / SV.FPS, 3)
    ok = [b for b in beats if 3.0 <= b <= dur - total - 0.6] or [0.5]
    ss = round(max(0.0, rng.choice(ok) - 0.05), 3)
    ends, acc = [], 0.0
    for h in HOLDS[:-1]:
        acc += h
        near = [b - ss for b in beats if abs(b - ss - acc) <= 0.25]
        e = min(near, key=lambda b: abs(b - acc)) if near else acc
        ends.append(round(round(e * SV.FPS) / SV.FPS, 3))
    return ss, ends, total


def params(rng: random.Random, p: str, nvar: int, i: int, s: int) -> dict:
    """Кадр фото: вариант по кругу, зум 1.0–1.12 со сдвигом, свет, тёплость; экран телефона / голова — ниже подписи."""
    for _ in range(200):
        pr = dict(var=(i + s) % nvar, z=round(rng.uniform(1.0, 1.12), 3), fx=round(rng.random(), 3),
                  fy=round(rng.random(), 3), br=round(rng.uniform(0.96, 1.04), 3), warm=round(rng.uniform(-0.03, 0.03), 3),
                  shade=rng.randrange(1 << 30), grain=rng.randrange(1 << 30))
        t = C.PHONE_TOP.get(p)
        if t is None or (t[0] * H - (H - H / pr["z"]) * pr["fy"]) * pr["z"] >= t[1] * H:
            return pr
    return dict(pr, z=1.0, fy=0.5)


_FIT: dict = {}


def fast_frame(path: Path, pr: dict) -> Image.Image:
    """То же, что C.photo_frame (кадр, свет, тёплость, волны света ±10 %, зерно), но во float32 и с кэшем подогнанного
    фото в процессе — в 2.5 раза быстрее (замер 16.11: 0.9 с → 0.35 с на слайд)."""
    if str(path) not in _FIT:
        _FIT[str(path)] = ImageOps.fit(Image.open(path).convert("RGB"), (W, H), Image.Resampling.LANCZOS)
    cw, ch = W / pr["z"], H / pr["z"]
    x, y = (W - cw) * pr["fx"], (H - ch) * pr["fy"]
    im = _FIT[str(path)].resize((W, H), Image.Resampling.LANCZOS, box=(x, y, x + cw, y + ch))
    a = np.asarray(im, np.float32) * np.float32(pr["br"])
    a[..., 0] *= np.float32(1 + pr["warm"])
    a[..., 2] *= np.float32(1 - pr["warm"])
    v = C.shade_field(pr["shade"], W, H).astype(np.float32)
    al = (np.abs(v) * np.float32(0.10))[..., None]
    a = a * (1 - al) + (v < 0)[..., None].astype(np.float32) * np.float32(255) * al
    a += np.random.default_rng(pr["grain"]).standard_normal((H, W), dtype=np.float32)[..., None] * np.float32(2.0)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def slides(ver: str, i: int, seed: int, dest: Path) -> list[Path]:
    rng = random.Random(seed)
    tpx, bpx = rng.randint(66, 70), rng.randint(50, 54)
    ty, dy = rng.randint(int(0.215 * H), int(0.25 * H)), rng.randint(-20, 20)
    out = []
    for s, lines in enumerate(C.VERS[ver]):
        p = C.PHOTO[ver][s]
        vs = C.variants(p)
        pr = params(rng, p, len(vs), i, s)
        can = fast_frame(vs[pr["var"]], pr).convert("RGBA")
        if s == 0:
            px = C.fit_px(lines, C.F_TITLE, tpx)
            blk = C.text_block(lines, C.F_TITLE, px, (255, 255, 255, 255), 1.16, True)
            box = C.place(can, blk, ty)
        else:
            px = C.fit_px(lines, C.F_BODY, bpx)
            blk = C.text_block(lines, C.F_BODY, px, (255, 255, 255, 255), 1.18, False)
            cy = max(C.Y0 + blk.height // 2 + 4, int(0.165 * H) + dy)
            box = C.place(can, blk, cy)
        if bad := check_box(W, H, box):
            raise RuntimeError(f"{dest.name} слайд {s + 1}: текст вне рамки {box} {bad}")
        f = dest / f"{s + 1}.png"
        can.convert("RGB").save(f, compress_level=0)        # без сжатия — сохранение в 5 раз быстрее
        out.append(f)
    return out


def render(job: dict) -> str:
    work = WORK / "frames" / f"{Path(job['out']).parent.name}_{Path(job['out']).stem}"
    work.mkdir(parents=True, exist_ok=True)
    pngs = slides(job["ver"], job["i"], job["seed"], work)
    with gpu_slot():
        SV.encode(pngs, job["ends"], job["total"], Path(job["song"]), job["ss"], Path(job["out"]), work)
    shutil.rmtree(work)
    return Path(job["out"]).name


def prog(stage: str, done: int, total: int) -> None:
    p = ROOT / "output" / "_work" / "_qa_progress" / f"{__import__('os').getpid()}.json"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(dict(stage=stage, done=done, total=total), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--tt", type=int, default=0)
    ap.add_argument("--yt", type=int, default=0)
    ap.add_argument("--seed", type=int, default=51116)
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    t0 = time.time()
    WORK.mkdir(parents=True, exist_ok=True)
    bc = WORK / "beats.json"
    beats = json.loads(bc.read_text(encoding="utf-8")) if bc.exists() else {}
    for s in SONGS:
        if s.name not in beats:
            beats[s.name] = beats_of(s)
    bc.write_text(json.dumps(beats), encoding="utf-8")
    rng = random.Random(a.seed)
    plan = []                                           # (папка, имя файла, версия, номер внутри версии)
    if a.test:
        d = WORK / "test"
        plan = [(d, f"junes_journey_5_{v}_test_{k + 1}_1.mp4", v, k) for k, v in enumerate(("v1", "v2", "v3"))]
    else:
        for plat, n in (("tt", a.tt), ("yt", a.yt)):
            d = ROOT / "output" / f"junes_journey_5_video_{plat.upper()}_{n}"
            for k in range(n):
                v = ("v1", "v2", "v3")[k % 3]
                plan.append((d, f"junes_journey_5_{v}_{plat}_{k + 1:03d}_1.mp4", v, k // 3 + (0 if plat == "tt" else 100)))
    jobs, man = [], {}
    for n_, (d, name, v, i) in enumerate(plan):
        song = SONGS[(0, 3, 5)[n_] if a.test else n_ % len(SONGS)]     # тест: одна старая cozy + две новые
        ss, ends, total = timing(beats[song.name], beats[song.name][-1], rng)
        j = dict(out=str(d / name), ver=v, i=i, seed=rng.randrange(1 << 30), song=str(song), ss=ss, ends=ends, total=total)
        jobs.append(j)
        man.setdefault(d.name, {})[name] = dict(ends=ends, total=total, start=ss, picks=[v, song.name])
        d.mkdir(parents=True, exist_ok=True)
    for name, m in man.items():
        (WORK / f"manifest_{name}.json").write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
    todo = [j for j in jobs if not Path(j["out"]).exists()]
    print(f"план {len(jobs)}, собрать {len(todo)}; подготовка {time.time() - t0:.0f} с", flush=True)
    done, bad = 0, []
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [(j, ex.submit(render, j)) for j in todo]
        for j, f in futs:
            try:
                f.result()
            except Exception as e:                      # noqa: BLE001 — не роняем партию, недоделанное удаляем
                Path(j["out"]).unlink(missing_ok=True)
                bad.append(Path(j["out"]).name)
                print("  ОШИБКА", Path(j["out"]).name, e, flush=True)
            done += 1
            prog("June's Journey 5 видео: сборка", done, len(todo))
            if done % 25 == 0:
                print(f"  готово {done}/{len(todo)}  {time.time() - t0:.0f} с", flush=True)
    print(f"ГОТОВО за {time.time() - t0:.0f} с, ошибок {len(bad)} {bad[:5]}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
