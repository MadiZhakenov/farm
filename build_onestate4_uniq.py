#!/usr/bin/env python3
"""
OneState 4 (ID 1309) — партия 200 YT + 200 TT с гарантией уникальности (юзер 2026-11-13: «худшая пара ~1 %, как на
Skinive, максимум»). Формат и содержание — build_onestate4.py (mix: захватывающее начало + сцены 1309 + экшн-вставки,
×2–3, 7 с, новые подписи/комментарии). Сверху:
  • 20 начал (HOOKS + HOOKS_EXTRA, отобраны покадрово), у каждого ролика своё окно, скорость, зум 1.05–1.4 со сдвигом;
  • у каждого куска зум 1.0–1.35 со сдвигом, зеркало 40 %;
  • раскладка: кегль/высота подписи, отступы, низ карточки, оттенок белого фона; цвет геймплея; тон музыки ±2.5 %;
  • ПРОВЕРКА ВСЕХ ПАР: dHash 16×16 каждого кадра на 6 к/с (строже замера Skinive — 3 к/с), с зеркалом, расстояния
    считаются на видеокарте (torch). Ролик, у которого хоть один кадр «узнаётся» в другом ролике партии или в
    onestate_1310_*_v2 (тот же футаж), получает новый план и пересобирается — пока совпадений не останется.

  python build_onestate4_uniq.py --jobs 3      # → output/onestate_1309_YT_200 + output/onestate_1309_TT_200
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_onestate4 as O  # noqa: E402

B, DR, P = O.B, O.DR, O.P
ID, FPS, TOTAL = "1309", O.FPS, 7.0
WORK = ROOT / "output" / "_work" / "onestate4_uniq"
OUT = {"yt": ROOT / "output" / f"onestate_{ID}_YT_200", "tt": ROOT / "output" / f"onestate_{ID}_TT_200"}
REFS = [ROOT / "output" / "onestate_1310_TT_100_v2", ROOT / "output" / "onestate_1310_YT_100_v2"]
PK = O.PK1080
OS3 = O.OS3
HOOKS_EXTRA = [  # отобрано покадрово 2026-11-13: событие в первые 0.1–0.3 с
    (PK, 22.75, 23.75, "приземляется со стены у камеры"), (PK, 43.3, 44.35, "коп перепрыгивает изгородь"),
    (PK, 111.0, 112.1, "перекат через капот"), (PK, 116.5, 117.6, "нырок через капот"),
    (PK, 125.1, 126.15, "нырок через капот"), (PK, 129.3, 130.35, "коп ныряет через капот"),
    (PK, 46.9, 47.95, "прыгает со стены"), (PK, 26.9, 27.95, "перемахивает изгородь"),
    (OS3 / "Army_Protection_of_the_base.mp4", 17.4, 18.8, "армия стреляет по байкерам"),
    (OS3 / "Police_job_fight_with_Gang.mp4", 0.1, 1.5, "коп стреляет из-за двери машины"),
    (OS3 / "Army_Protection_of_the_base.mp4", 8.0, 9.4, "очередь по байкерам"),
]
HOOKS = O.HOOKS + HOOKS_EXTRA
HFPS, THR = 6, 40                                       # проверка: полоса геймплея, 6 к/с, «узнаётся» ≤ 40 из 256 бит


# ---------------- план одного ролика ----------------
# Кадрирование ПО ЦЕНТРУ (юзер 2026-11-13: «не по центру… разве это смотрибельно» — у 3 и у 4): объект в середине,
# сдвиг окна не больше ±~50 px, зум от центра (заодно срезает интерфейс игры по краям). Уникальность — не сдвигом,
# а тем, какие секунды исходника и с каким зумом берёт ролик: жадно выбираем вариант, меньше всего пересекающийся с уже
# взятыми кусками других роликов (TAKEN), плюс скорость, раскладка, цвет, музыка.
TAKEN: list = []


def _ov(x: dict, y: dict) -> float:
    if x["path"] != y["path"] or abs(x["z"] - y["z"]) > 0.08:
        return 0.0
    a0, a1 = x["a"], x["a"] + x["frames"] / FPS * x["speed"]
    b0, b1 = y["a"], y["a"] + y["frames"] / FPS * y["speed"]
    return max(0.0, min(a1, b1) - max(a0, b0))


def _candidate(rng: random.Random, win: list, hook_use: dict) -> dict | None:
    k = rng.choice((5, 5, 6))
    lo = min(hook_use.get(h, 0) for h in range(len(HOOKS)))
    hi = rng.choice([h for h in range(len(HOOKS)) if hook_use.get(h, 0) <= lo + 1])
    hp, hs, he, _ = HOOKS[hi]
    hsp = round(rng.uniform(1.3, 1.8), 2)
    hs = max(0.0, hs + rng.uniform(-0.08, 0.12))
    hf = round(min(he - hs, 1.25) / hsp * FPS)
    hook = dict(m=200 + hi, id=2000 + hi, file=Path(hp).name, path=str(hp), a=round(hs, 3), speed=hsp, frames=hf,
                action=True, hook=hi)
    rest_total = TOTAL - hf / FPS
    lens = [rng.uniform(0.9, 1.6) for _ in range(k - 1)]
    lens = [x * rest_total / sum(lens) for x in lens]
    fr = [round(x * FPS) for x in lens]
    fr[-1] = round(rest_total * FPS) - sum(fr[:-1])
    fr = [hf] + fr
    if min(fr[1:]) < 0.7 * FPS or hf < 0.55 * FPS:
        return None
    na = rng.choice((2, 3)) if k == 5 else 3
    for _t in range(50):
        rest = ["A"] * (na - 1) + ["S"] * (k - na)
        rng.shuffle(rest)
        types = ["A"] + rest
        if all(not (x == y == "A") for x, y in zip(types, types[1:])):
            break
    pieces = [hook]
    for i in range(1, len(fr)):
        L = fr[i]
        pool_i = [w for w in win if bool(w.get("action")) == (types[i] == "A")]
        cand = [w for w in pool_i if w["m"] not in {p["m"] for p in pieces} and w["dur"] >= L / FPS * 2.0 + 0.05
                and O.place(w) != O.place(pieces[-1])]
        if not cand:
            return None
        pieces.append(O.piece(rng, rng.choice(cand), L / FPS, False))
    for j, pc in enumerate(pieces):
        z0, z1 = (1.05, 1.3) if j == 0 else (1.0, 1.3)
        pc.update(z=round(rng.uniform(z0, z1), 3), ox=round(rng.uniform(0.44, 0.56), 3), oy=round(rng.uniform(0.42, 0.58), 3),
                  mirror=rng.random() < 0.4)
    return dict(hook=hi, pieces=pieces)


def make_job(n: int, tag: str, rng: random.Random, win: list, hook_use: dict, avatars: list, tries: int = 16) -> dict:
    best = None
    for _ in range(tries * 10):
        c = _candidate(rng, win, hook_use)
        if c is None:
            continue
        sc = sum(_ov(x, y) for x in c["pieces"] for y in TAKEN) + 3 * sum(_ov(c["pieces"][0], y) for y in TAKEN)
        if best is None or sc < best[0]:
            best = (sc, c)
        tries -= 1
        if tries <= 0:
            break
    if best is None:
        raise SystemExit("не собрал план ролика")
    c = best[1]
    TAKEN.extend(c["pieces"])
    hook_use[c["hook"]] = hook_use.get(c["hook"], 0) + 1
    return dict(n=n, tag=tag, caption=rng.randrange(len(O.CAPTIONS_RAW)), comment=rng.randrange(len(O.COMMENTS_RAW)),
                pieces=c["pieces"], person=list(B.PEOPLE[rng.randrange(len(B.PEOPLE))]),
                avatar=str(rng.choice(avatars)), seed=rng.randrange(10 ** 9),
                cap_top=rng.randint(206, 262), cap_px=rng.choice((44, 45, 46, 47, 48)), gap=rng.randint(24, 46),
                card_lift=rng.randint(0, 70), bg=rng.choice((255, 254, 253, 252, 251)), tint=rng.choice((0, 0, 1, -1, 2, -2)),
                pitch=round(rng.uniform(0.975, 1.025), 4),
                grade=dict(br=round(rng.uniform(-0.03, 0.035), 3), ct=round(rng.uniform(0.95, 1.08), 3),
                           sat=round(rng.uniform(0.95, 1.15), 3), temp=rng.randint(5400, 7400),
                           mix=round(rng.uniform(0.3, 0.6), 2), noise=rng.randint(2, 6)))


# ---------------- рендер ----------------
def build(job: dict) -> str:
    from core.gpu_slots import gpu_slot               # общий на весь компьютер лимит: ≤ 3 ffmpeg с CUDA-декодом
    with gpu_slot() as hw:
        return _build(job, bool(hw))


def _build(job: dict, gpu: bool) -> str:
    os.environ["OS1309_FONT"] = "tiktok" if job["tag"] == "tt" else "default"
    work = Path(tempfile.mkdtemp(prefix="os4u_"))
    rng = random.Random(job["seed"])
    B.CAP_TOP, B.CAP_PX = job["cap_top"], job["cap_px"]
    B.CAPTIONS = [DR.wrap_width(t, B.F_CAP, B.CAP_PX, B.X1 - B.X0) for t in O.CAPTIONS_RAW]
    cap_png, card, logo = work / "cap.png", work / "card.png", work / "logo.png"
    cap_bottom = B.caption_png(job["caption"], cap_png)
    card_h = B.card_png(job["comment"], tuple(job["person"]), Path(job["avatar"]), card)
    card_top = B.CARD_BOTTOM - job["card_lift"] - card_h
    band = (cap_bottom + job["gap"], card_top - job["gap"])
    bh = band[1] - band[0]
    bh -= bh % 2
    lx, ly, _lr = B.logo_png(rng, (band[0], band[0] + bh), logo)
    cw, ch = B.banner_anim()
    bx = (B.W - cw) // 2
    by = band[0] + bh - 16 - ch + round(ch * 0.06)
    inputs, parts = [], []
    for k, p in enumerate(job["pieces"]):
        src = p["frames"] / FPS * p["speed"]
        zw, zh = round(B.W * p["z"] / 2) * 2, round(bh * p["z"] / 2) * 2
        inputs += [*(["-hwaccel", "cuda"] if gpu else []), "-ss", f"{p['a']:.3f}", "-t", f"{src + 0.2:.3f}", "-i", p["path"]]
        parts.append(f"[{k}:v]setpts=(PTS-STARTPTS)/{p['speed']},fps={FPS},"
                     f"scale={zw}:{zh}:flags=lanczos:force_original_aspect_ratio=increase,"
                     f"crop={B.W}:{bh}:(iw-{B.W})*{p['ox']}:(ih-{bh})*{p['oy']}{',hflip' if p['mirror'] else ''},"
                     f"tpad=stop_mode=clone:stop=3,trim=end_frame={p['frames']},setpts=PTS-STARTPTS,setsar=1[v{k}]")
    n = len(job["pieces"])
    g = job["grade"]
    inputs += ["-loop", "1", "-i", str(cap_png), "-loop", "1", "-i", str(card), "-loop", "1", "-i", str(logo),
               "-i", str(B.BANNER_ANIM), "-i", str(O.MUSIC)]
    ic, ik, il, ib, ia = n, n + 1, n + 2, n + 3, n + 4
    bgv = job["bg"]
    bgc = f"0x{bgv:02x}{min(255, bgv + job['tint']):02x}{min(255, bgv - job['tint']):02x}"
    parts += [
        "".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0,"
        f"eq=brightness={g['br']}:contrast={g['ct']}:saturation={g['sat']}:"
        f"gamma_r={1 + (6400 - g['temp']) / 40000 * g['mix']:.4f}:gamma_b={1 - (6400 - g['temp']) / 40000 * g['mix']:.4f},"
        f"noise=c0s={g['noise']}:c0f=t[g]",
        f"color={bgc}:s={B.W}x{B.H}:r={FPS}:d={TOTAL}[bg]",
        f"[bg][g]overlay=0:{band[0]}:shortest=1[s1]",
        f"[s1][{il}:v]overlay={lx}:{ly}[s2]",
        f"[s2][{ic}:v]overlay=0:0:shortest=1[s3]",
        f"[s3][{ik}:v]overlay=0:{card_top}:shortest=1[s4]",
        f"[{ib}:v]fps={FPS},format=yuva420p,setpts=PTS-STARTPTS+{O.BANNER_T:.3f}/TB[bn]",
        f"[s4][bn]overlay={bx}:{by}:eof_action=pass,format=yuv420p,{O.SET_SDR}[v]",
        f"[{ia}:a]asetrate=48000*{job['pitch']},aresample=48000,atrim=0:{TOTAL},afade=t=out:st={TOTAL - 0.3}:d=0.3[a]",
    ]
    dest = OUT[job["tag"]] / f"{job['n']:03d}_{ID}.mp4"
    cmd = [B.FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
           "-t", f"{TOTAL}", "-r", str(FPS),
           "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
           "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-c:a", "aac", "-b:a", "192k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
           "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
           "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)]
    for attempt in range(3):
        try:
            subprocess.run(cmd, check=True, timeout=300)
            break
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt == 2:
                raise
    for f in work.iterdir():
        f.unlink()
    work.rmdir()
    return f"{job['tag']} {dest.name}: начало {HOOKS[job['pieces'][0]['hook']][3]}"


def render(jobs: list[dict], workers: int) -> None:
    """TikTok и YouTube — разными пулами (шрифт выбирается при импорте в процессе-воркере по OS1309_FONT)."""
    for tag, font in (("yt", "default"), ("tt", "tiktok")):
        js = [j for j in jobs if j["tag"] == tag]
        if not js:
            continue
        os.environ["OS1309_FONT"] = font
        OUT[tag].mkdir(parents=True, exist_ok=True)
        with ProcessPoolExecutor(workers) as ex:
            for k, msg in enumerate(ex.map(build, js), 1):
                print(f"  [{tag} {k}/{len(js)}] {msg}", flush=True)


# ---------------- проверка всех пар (видеокарта) ----------------
BAND = (450, 930)                                       # полоса геймплея: общий белый фон/подпись/карточку не сравниваем


def vhash(path: Path, k: int = 0, whole: bool = False) -> np.ndarray:
    crop = "" if whole else f"crop=1080:{BAND[1] - BAND[0]}:0:{BAND[0]},"
    fps = 3 if whole else HFPS
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps},{crop}scale=17:16:flags=area,format=gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 16, 17).astype(np.int16)
    h = (fr[:, :, 1:] > fr[:, :, :-1]).reshape(len(fr), -1)
    m = (fr[:, :, ::-1][:, :, 1:] > fr[:, :, ::-1][:, :, :-1]).reshape(len(fr), -1)
    return np.stack([h, m], 1)


def hashes(files: list[Path], whole: bool = False) -> dict:
    cache_f = WORK / ("hash_whole3.npz" if whole else "hash_band6.npz")
    cache = dict(np.load(cache_f, allow_pickle=True)["d"].item()) if cache_f.exists() else {}
    todo = [f for f in files if cache.get(str(f), (None, 0))[1] != f.stat().st_mtime]
    with ThreadPoolExecutor(8) as ex:
        for f, h in zip(todo, ex.map(lambda f: vhash(f, whole=whole), todo)):
            cache[str(f)] = (h, f.stat().st_mtime)
    np.savez(cache_f, d=np.array(cache, dtype=object))
    return {str(f): cache[str(f)][0] for f in files}


def similarity(own: list[Path], refs: list[Path], thr: int, whole: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """sim[i, j] = доля кадров ролика i, у которых в ролике j (как есть или зеркально) есть кадр ближе thr бит —
    для всех own × (own + refs). Матрица расстояний считается на видеокарте блоками."""
    import torch
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    H = hashes(own + refs, whole)
    allf = own + refs
    X = [H[str(f)] for f in allf]
    vid = np.concatenate([np.full(len(x), i) for i, x in enumerate(X)])
    A = torch.tensor(np.concatenate([x[:, 0] for x in X]), dtype=torch.float16, device=dev)
    M = torch.tensor(np.concatenate([x[:, 1] for x in X]), dtype=torch.float16, device=dev)
    vid_t = torch.tensor(vid, device=dev)
    nv, no = len(allf), len(own)
    sa, sm = A.float().sum(1), M.float().sum(1)
    hit = torch.zeros((int((vid < no).sum()), nv), device=dev)
    rows = torch.nonzero(vid_t < no).squeeze(1)
    for c in range(0, len(rows), 1024):
        r = rows[c:c + 1024]
        Ar = A[r].float()
        d1 = sa[r][:, None] + sa[None, :] - 2 * (Ar @ A.float().T)
        d2 = sa[r][:, None] + sm[None, :] - 2 * (Ar @ M.float().T)
        d = torch.minimum(d1, d2)
        m = torch.full((len(r), nv), 1e9, device=dev)
        m.scatter_reduce_(1, vid_t[None, :].expand(len(r), -1), d, reduce="amin")
        hit[c:c + len(r)] = (m <= thr).float()
    own_vid = vid_t[rows]
    cnt = torch.bincount(own_vid, minlength=no).float()
    S = torch.zeros((no, nv), device=dev)
    S.index_add_(0, own_vid, hit)
    S = S / cnt[:, None]
    S[torch.arange(no), torch.arange(no)] = 0
    S = S.cpu().numpy()
    own_pair = np.maximum(S[:, :no], S[:, :no].T)
    return own_pair, S[:, no:]


def bad_set(own_pair: np.ndarray, vs_ref: np.ndarray) -> list[int]:
    """Минимальный (жадно) набор роликов, после пересборки которых совпадений не останется."""
    E = {(i, j) for i, j in zip(*np.nonzero(np.triu(own_pair > 0, 1)))}
    bad = {i for i in range(len(vs_ref)) if (vs_ref[i] > 0).any()}
    E = {(i, j) for i, j in E if i not in bad and j not in bad}
    while E:
        deg: dict = {}
        for i, j in E:
            deg[i] = deg.get(i, 0) + 1
            deg[j] = deg.get(j, 0) + 1
        v = max(deg, key=deg.get)
        bad.add(v)
        E = {(i, j) for i, j in E if v not in (i, j)}
    return sorted(bad)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--iters", type=int, default=10)
    ap.add_argument("--seed", type=int, default=130913)
    ap.add_argument("--fresh", action="store_true", help="новый план и пересборка всех 400 (поверх)")
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    B.banner_anim()
    O.music()
    win, _top = O.pool()
    # «Police_job_fight» после 4.35 с — крупно колесо машины, скучно (2026-11-13)
    win = [w for w in win if not (w.get("action") and w["file"].startswith("Police_job_fight") and w["base"] > 4)]
    avatars = [p for d in B.AVATAR_DIRS if d.is_dir() for p in sorted(d.glob("*.jpg")) if not p.name.startswith("_")]
    state_f = WORK / "plan.json"
    rng = random.Random(a.seed)
    hook_use: dict = {}
    if state_f.exists() and not a.fresh:
        jobs = json.loads(state_f.read_text(encoding="utf-8"))
        for j in jobs:
            hook_use[j["pieces"][0]["hook"]] = hook_use.get(j["pieces"][0]["hook"], 0) + 1
            TAKEN.extend(j["pieces"])
        todo = [j for j in jobs if not (OUT[j["tag"]] / f"{j['n']:03d}_{ID}.mp4").exists()]
    else:
        jobs = [make_job(i, tag, rng, win, hook_use, avatars) for tag in ("yt", "tt") for i in range(1, 201)]
        state_f.write_text(json.dumps(jobs, indent=0, ensure_ascii=False), encoding="utf-8")
        todo = list(jobs)                                   # --fresh: пересобрать все (поверх старых файлов)
    print(f"план: {len(jobs)} роликов, рендер {len(todo)}", flush=True)
    render(todo, a.jobs)
    refs = [f for d in REFS if d.exists() for f in sorted(d.glob("*.mp4"))]
    for it in range(1, a.iters + 1):
        own = [OUT[j["tag"]] / f"{j['n']:03d}_{ID}.mp4" for j in jobs]
        pair, vs = similarity(own, refs, THR)
        bad = bad_set(pair, vs)
        print(f"проверка {it}: худшая пара {pair.max() * 100:.1f} %, пар с совпадениями {int((np.triu(pair, 1) > 0).sum())}, "
              f"с 1310_v2 {int((vs > 0).any(1).sum())} роликов → пересобираю {len(bad)}", flush=True)
        if not bad:
            break
        rng = random.Random(a.seed + it * 7919)
        for i in bad:
            old = jobs[i]
            hook_use[old["pieces"][0]["hook"]] -= 1
            for pc in old["pieces"]:
                if pc in TAKEN:
                    TAKEN.remove(pc)
            jobs[i] = make_job(old["n"], old["tag"], rng, win, hook_use, avatars)
        state_f.write_text(json.dumps(jobs, indent=0, ensure_ascii=False), encoding="utf-8")
        render([jobs[i] for i in bad], a.jobs)
    own = [OUT[j["tag"]] / f"{j['n']:03d}_{ID}.mp4" for j in jobs]
    for whole, name in ((False, "полоса геймплея, 6 к/с"), (True, "весь кадр, 3 к/с — как замер Skinive")):
        pair, vs = similarity(own, refs, THR, whole)
        tri = pair[np.triu_indices(len(own), 1)]
        print(f"ИТОГ ({name}, порог {THR}): худшая пара {tri.max() * 100:.1f} %, среднее {tri.mean() * 100:.3f} %, "
              f"пар с совпадениями {int((tri > 0).sum())} из {len(tri)}; против 1310_v2 худшая {vs.max() * 100:.1f} %", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
