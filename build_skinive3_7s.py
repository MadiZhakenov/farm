#!/usr/bin/env python3
"""
skinive_3 (ID 1) — 7-секундная версия (юзер 16.11: «эту айдишку (youtube Ehe9XufV3ZA = наш skinive3, 10.4 с) обрезать
до 7с и зауникалить (схожесть между собой 0-1 проц и с теми что когда либо было генерировано этими материалами) тт 100
ют 150»). Формат — последний одобренный skinive3 (v3): лицо → родинка → родинка дальше, 4 текста ТЗ сверху,
карточка App Store всплывает, затем результат (плашка или шкала), музыка рефа + «поп». Длина ровно 7.0 с.

По правилам CLAUDE.md (16.11): видеокарта распаковывает и режет (cuvid -crop -resize), кадры — в обычной памяти,
склейка и ВСЕ слои (вид ролика, тексты, карточки) — обычным overlay в памяти, NVENC кодирует. Никаких overlay_cuda.
Приём ролика: bad_frames (пустые/зелёные/повторы) + покадровая сверка с исходником (каждый кадр — тот, что по плану)
+ ни одного общего кадра (3 к/с, dHash ≤ 40, с зеркалом) ни с одним принятым и ни с одним старым skinive-роликом
(skinive2/3/4/6 — все партии из этих материалов).

  python build_skinive3_7s.py --test 6               # пробы → output/_work/skinive3_7s/test
  python build_skinive3_7s.py --tt 100 --yt 150 --jobs 4
"""

from __future__ import annotations

import argparse
import json
import pickle
import random
import subprocess
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_skinive3_v3 as V3  # noqa: E402
OV, U, M, G = V3.OV, V3.U, V3.M, V3.G
from core.gpu_slots import gpu_slot  # noqa: E402
from core.safe_zones import check_box  # noqa: E402
from core import uniq_fast as UF  # noqa: E402

THR30 = 40                                               # приёмка по КАЖДОМУ кадру среди новых (итог проверяется при 40)


def h30_of(path: Path) -> np.ndarray:
    """Каждый кадр (30 к/с), весь кадр: ±1 [кадры, 256] прямые и зеркальные — как check_uniq_allframes --strip 0 1920."""
    h, m = UF.real_hash(path, (0, H))
    return np.concatenate([np.asarray(h, np.float32), np.asarray(m, np.float32)]) * 2 - 1


def near30(h: np.ndarray, bank: np.ndarray) -> bool:
    if not len(bank):
        return False
    q = h[: len(h) // 2]                                     # прямые кадры кандидата против прямых и зеркальных банка
    for i in range(0, len(bank), 60000):
        if ((256 - q @ bank[i:i + 60000].T) / 2 <= THR30).any():
            return True
    return False

W, H, FPS = V3.W, V3.H, V3.FPS
TOTAL = 7.0
NF = round(TOTAL * FPS)
WORK = ROOT / "output" / "_work" / "skinive3_7s"
OLD = sorted(d for d in (ROOT / "output").glob("skinive*") if d.is_dir() and "7s" not in d.name)
Q8 = 8                                                   # сверка кадров: уменьшение в 8 раз


def candidate(rng: random.Random) -> dict:
    """Как v3.candidate, но 7.0 с: лицо 2.1–2.4, родинка 2.0–2.3, дальше до 7.0 (2.3–2.9). Лицо — один кусок,
    рука — одна непрерывная запись, если хватает длины, иначе вторая часть из другой записи той же руки."""
    L0 = round(rng.uniform(2.1, 2.4), 2)
    L1 = round(rng.uniform(2.0, 2.3), 2)
    L2 = round(TOTAL - L0 - L1, 2)
    a, b = rng.choice(V3.FACE_SPANS)
    while b - a < L0 + 0.05:
        a, b = rng.choice(V3.FACE_SPANS)
    t = round(rng.uniform(a, b - L0 - 0.05), 3)
    g = U.geo(rng, *U.ZOOM["face3"], None)
    g.update(ang=0.0, dx=max(-0.05, min(0.05, g["dx"])), dy=max(-0.05, min(0.05, g["dy"])))
    face = dict(src="face", t=t, len=L0, g=g)
    grp = rng.choice(("c", "a"))
    spans = V3.MOLE_SPANS[grp]
    whole = [s for s in spans if s[2] - s[1] >= L1 + L2 + 0.1]
    g2 = U.geo(rng, *U.ZOOM[grp], rng.uniform(0.42, 0.62))
    g2["ang"] = 0.0
    if whole:
        sid, a, b = rng.choice(whole)
        t2 = round(rng.uniform(a, b - L1 - L2 - 0.05), 3)
        sid3, t3, g3 = sid, round(t2 + L1, 3), dict(g2)
    else:
        sid, a, b = rng.choice([s for s in spans if s[2] - s[1] >= L1 + 0.05])
        t2 = round(rng.uniform(a, b - L1 - 0.05), 3)
        other = [s for s in spans if s[0] != sid and s[2] - s[1] >= L2 + 0.05]
        if not other:
            L2 = round(min(L2, b - t2 - L1 - 0.05), 2)
            sid3, t3, g3 = sid, round(t2 + L1, 3), dict(g2)
        else:
            sid3, a3, b3 = rng.choice(other)
            t3 = round(rng.uniform(a3, b3 - L2 - 0.05), 3)
            g3 = U.geo(rng, *U.ZOOM[grp], rng.uniform(0.53, 0.58))
    g3["ang"] = 0.0
    segs = [[face], [dict(src=sid, t=t2, len=L1, g=g2)], [dict(src=sid3, t=t3, len=L2, g=g3)]]
    return dict(speed=1.0, segs=segs, L=[round(sum(x["len"] for x in s), 3) for s in segs],
                card=rng.choice(("plate", "gauge")), theme=rng.choice(("dark", "dark", "light")),
                seed=rng.randrange(10 ** 9))


def src_of(x: dict) -> Path:
    return U.FACE if x["src"] == "face" else V3.LONG_STAB / f"{x['src']}.mp4"


def render(r: dict, dest: Path, keep: Path) -> dict:
    """Ролик 7.0 с. Возвращает «паспорт» для сверки кадров: куски, свободная полоса (без текста/карточек), слои вида."""
    rng = random.Random(r["seed"])
    tmp = WORK / f"t_{dest.stem}"
    tmp.mkdir(parents=True, exist_ok=True)
    shots = [x for seg in r["segs"] for x in seg]
    nfr = [round(x["len"] * FPS) for x in shots]
    nfr[-1] = NF - sum(nfr[:-1])                          # ровно 210 кадров
    nf = NF
    total = TOTAL
    L = [sum(round(x["len"] * FPS) for x in seg) / FPS for seg in r["segs"]]
    t_end = L[0] + L[1]
    inputs, fc = [], []
    for i, x in enumerate(shots):
        inputs += G.gpu_input(src_of(x), crop=V3.crop_of(x["g"]), resize=(W, H))
        fc.append(f"[{i}:v]trim=start={x['t']:.3f}:duration={x['len'] + 0.05:.3f},setpts=PTS-STARTPTS,"
                  f"fps={FPS},setsar=1,format=yuv420p,tpad=stop_mode=clone:stop={nfr[i] + 2},"
                  f"trim=end_frame={nfr[i]},setpts=PTS-STARTPTS[s{i}]")
    fc.append("".join(f"[s{i}]" for i in range(len(shots))) + f"concat=n={len(shots)}:v=1:a=0,format=yuv420p[b0]")
    idx, cur = len(shots), "b0"

    def add_layer(png: Path, a0: int, n: int) -> None:
        nonlocal cur, idx
        inputs.extend(["-i", str(png)])
        fc.append(f"[{idx}:v]loop=loop={n - 1}:size=1:start=0,settb=1/{FPS},setpts=N+{a0},format=yuva420p[l{idx}]")
        fc.append(f"[{cur}][l{idx}]overlay=0:0:eof_action=pass:format=yuv420[o{idx}]")
        cur, idx = f"o{idx}", idx + 1

    V3.look_png(rng, keep / "look.png")
    add_layer(keep / "look.png", 0, nf)
    n_face = nfr[0]
    V3.face_wave_png(rng, keep / "face.png", V3.FACE_X)
    add_layer(keep / "face.png", 0, n_face)
    with V3.LOCK:
        texts, txt_bottom = U.text_layers(3, rng, tmp, L, total)
    for png, a, b in texts:
        a0, b0 = round(a * FPS), min(nf, round(b * FPS))
        add_layer(png, a0, max(1, b0 - a0))

    t_app = t_end + rng.uniform(0.05, 0.25)
    t_res = t_app + rng.uniform(0.55, 0.75)
    rects = []

    def place(card: Image.Image, top: int | None = None, bottom: int | None = None, jx: int = 0) -> tuple[int, int]:
        cw, chh = card.width - 2 * OV.SHADOW, card.height - 2 * OV.SHADOW
        x = max(141, min(939 - cw, (W - cw) // 2 + jx))
        y = top if top is not None else bottom - chh
        if bad := check_box(W, H, (x, y, x + cw, y + chh)):
            raise SystemExit(f"{dest.name}: карточка вне безопасной зоны: {bad}")
        rects.append((y - 50, y + chh + 50))              # с ходом всплытия и тенью
        return x - OV.SHADOW, y - OV.SHADOW

    def pop(frames: list[Image.Image], name: str, x: int, y: int, t0: float) -> None:
        nonlocal cur, idx
        dy = rng.choice((40, 30, -30))
        nd = max(3, round(rng.uniform(0.15, 0.24) * FPS))
        top0, _ = V3.card_seq(frames, dy, nd, tmp / name)
        inputs.extend(["-framerate", str(FPS), "-i", str(tmp / name / "%03d.png")])
        f0 = round(t0 * FPS)
        fc.append(f"[{idx}:v]format=yuva420p,setpts=PTS-STARTPTS+{f0}/{FPS}/TB[l{idx}]")
        fc.append(f"[{cur}][l{idx}]overlay={x // 2 * 2}:{(y + top0) // 2 * 2}:format=yuv420[o{idx}]")
        cur, idx = f"o{idx}", idx + 1

    app = OV.app_card(r["theme"], rng.randrange(560, 682, 2))
    ax, ay = place(app, bottom=rng.randint(1480, 1530), jx=rng.randint(-30, 30))
    pop([app], "app", ax, ay, t_app)
    if r["card"] == "plate":
        card = OV.plate_card(3, rng.randrange(700, 800, 2))
        rx, ry = place(card, top=txt_bottom + rng.randint(30, 70), jx=rng.randint(-20, 20))
        pop([card], "res", rx, ry, t_res)
    else:
        gd = OV.gauge_frames(3, rng.choice(U.GAUGE_W[3]))
        gfr = [Image.open(p).convert("RGBA") for p in sorted(gd.glob("*.png"))]
        rx, ry = place(gfr[0], top=txt_bottom + rng.randint(25, 50), jx=rng.randint(-30, 30))
        pop(gfr, "res", rx, ry, t_res)
    fc.append(f"[{cur}]format=yuv420p[v]")

    mus = tmp / "music.wav"
    U.music(mus, total, rng)
    p1, p2 = rng.choice(U.POPS), rng.choice(U.POPS)
    pv = rng.uniform(0.4, 0.6)
    ai = idx
    inputs += ["-i", str(mus), "-i", str(p1), "-i", str(p2)]
    fc.append(f"[{ai + 1}:a]volume={pv:.2f},adelay=delays={round(t_app * 1000)}:all=1[p1]")
    fc.append(f"[{ai + 2}:a]volume={pv:.2f},adelay=delays={round(t_res * 1000)}:all=1[p2]")
    fc.append(f"[{ai}:a][p1][p2]amix=inputs=3:normalize=0:duration=first,atrim=0:{total:.3f}[a]")
    (tmp / "graph.txt").write_text(";".join(fc), encoding="utf-8")
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex_script", str(tmp / "graph.txt"), "-map", "[v]",
           "-map", "[a]", "-frames:v", str(nf), "-r", str(FPS), *G.NVENC, "-c:a", "aac", "-b:a", "160k",
           "-t", f"{total:.3f}", *G.CLEAN, str(dest)]
    with gpu_slot():
        for attempt in range(2):
            try:
                subprocess.run(cmd, check=True, timeout=300, capture_output=True)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                if attempt == 1:
                    raise
    for p in sorted(tmp.rglob("*"), reverse=True):
        p.rmdir() if p.is_dir() else p.unlink()
    tmp.rmdir()
    # свободная полоса для сверки: между нижним краем текста/карточки результата и верхом карточки App Store
    top_free = max([txt_bottom + 20] + [b for a, b in rects if a < 1100])
    bot_free = min([1500] + [a for a, b in rects if a >= 1100])
    return dict(shots=[dict(src=str(src_of(x)), t=x["t"], g=x["g"]) for x in shots], nfr=nfr, n_face=n_face,
                band=(top_free // Q8 * Q8 + Q8, bot_free // Q8 * Q8 - Q8))


def _gray(cmd: list[str], w: int, h: int) -> np.ndarray:
    raw = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)


def frame_check(pp: dict, path: Path, keep: Path, margin: float = 0.8, junk: float = 16.0) -> list:
    """КАЖДЫЙ кадр ролика против того кадра исходника, что стоит по плану (юзер 13.11 «фризит, лагает, зелёное»):
    полоса без текста и карточек, уменьшенная в 8 раз, сравнивается с кадрами исходника k−3…k+3 (та же обрезка,
    те же слои «вида»). Плохо: ближе другой кадр исходника (повтор/пропуск) или ни один не похож (мусор)."""
    y0, y1 = pp["band"]
    if y1 - y0 < 64:
        return [("полоса для сверки мала", y0, y1)]
    w8, h8 = W // Q8, (y1 - y0) // Q8
    out = _gray(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                 f"crop={W}:{y1 - y0}:0:{y0},scale={w8}:{h8}:flags=area,format=gray", "-f", "rawvideo", "-"], w8, h8)
    if len(out) != NF:
        return [("кадров", len(out))]

    def lay(png: Path) -> tuple[np.ndarray, np.ndarray]:
        im = Image.open(png).convert("RGBA").crop((0, y0, W, y1)).resize((w8, h8), Image.Resampling.BOX)
        a = np.asarray(im, np.float32)
        al = a[..., 3] / 255
        g = a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
        return al, g
    look, face = lay(keep / "look.png"), lay(keep / "face.png")
    flags, f = [], 0
    for i, (x, n) in enumerate(zip(pp["shots"], pp["nfr"])):
        cx, cy, cw, ch = V3.crop_of(x["g"])
        pre = min(3, int(x["t"] * FPS))
        ts = x["t"] - pre / FPS
        src = _gray(["ffmpeg", "-v", "error", "-i", x["src"], "-vf",
                     f"trim=start={ts:.4f}:duration={n / FPS + 0.3:.3f},setpts=PTS-STARTPTS,fps={FPS},"
                     f"crop={cw}:{ch}:{cx}:{cy},scale={W}:{H}:flags=bicubic,crop={W}:{y1 - y0}:0:{y0},"
                     f"scale={w8}:{h8}:flags=area,format=gray", "-f", "rawvideo", "-"], w8, h8)
        for al, g in ([look, face] if i == 0 else [look]):
            src = src * (1 - al) + g * al
        for j in range(n):
            k = pre + j
            d = {dk: float(np.abs(out[f] - src[k + dk]).mean()) for dk in range(-3, 4) if 0 <= k + dk < len(src)}
            best = min(d, key=d.get)
            if d[best] > junk:
                flags.append((f, "мусор", round(d[best], 1)))
            elif best != 0 and d[0] - d[best] > margin:
                flags.append((f, best, round(d[0] - d[best], 2)))
            f += 1
    return flags


def old_bank() -> np.ndarray:
    """Все старые skinive-ролики (3 к/с, с зеркалом). Кэш v3 + свой (дописываем недостающие)."""
    f = WORK / "old_hashes.pkl"
    cache = {}
    for c in (V3.WORK / "old_hashes.pkl", f):
        if c.exists():
            cache.update(pickle.load(open(c, "rb")))
    files = [v for d in OLD for v in sorted(d.glob("*.mp4"))]
    todo = [v for v in files if str(v) not in cache]
    if todo:
        print(f"отпечатки старых skinive-роликов: {len(todo)} …", flush=True)
        with ThreadPoolExecutor(8) as ex:
            for v, h in zip(todo, ex.map(M.hashes, todo)):
                cache[str(v)] = h
        WORK.mkdir(parents=True, exist_ok=True)
        pickle.dump(cache, open(f, "wb"))
    print(f"старые skinive в сравнении: {len(files)} роликов из {len(OLD)} папок", flush=True)
    return V3.bank_of([cache[str(v)] for v in files])


def build_one(c: dict, tmp: Path) -> tuple:
    keep = tmp.with_suffix("")
    keep.mkdir(parents=True, exist_ok=True)
    try:
        pp = render(c, tmp, keep)
        bad = G.bad_frames(tmp)
        fr = [] if bad else frame_check(pp, tmp, keep)
        h = (M.hashes(tmp), h30_of(tmp)) if not bad and not fr else None
    finally:
        for p in keep.glob("*"):
            p.unlink()
        keep.rmdir()
    return c, tmp, h, bad, fr


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tt", type=int, default=0)
    ap.add_argument("--yt", type=int, default=0)
    ap.add_argument("--test", type=int, default=0)
    ap.add_argument("--seed", type=int, default=7161)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    import qa_batch as Q
    WORK.mkdir(parents=True, exist_ok=True)
    OV.app_card("dark")
    OV.app_card("light")
    OV.plate_card(3, 700)
    for gw in U.GAUGE_W[3]:
        OV.gauge_frames(3, gw)
    if a.test:
        outs = {"tt": WORK / "test"}
        want = [("tt", n) for n in range(1, a.test + 1)]
        for f in outs["tt"].glob("*.mp4"):
            f.unlink()
    else:
        outs = {"tt": ROOT / "output" / f"skinive3_7s_TT_{a.tt}", "yt": ROOT / "output" / f"skinive3_7s_YT_{a.yt}"}
        want = [("tt", n) for n in range(1, a.tt + 1)] + [("yt", n) for n in range(1, a.yt + 1)]
    for d in outs.values():
        d.mkdir(parents=True, exist_ok=True)
    name = lambda tag, n: outs[tag] / f"skinive3_{tag}_{n:03d}_1.mp4"   # noqa: E731
    bank_old = old_bank()
    have = [name(t, n) for t, n in want if name(t, n).exists()]
    with ThreadPoolExecutor(8) as ex:
        hh = list(ex.map(lambda f: (M.hashes(f), h30_of(f)), have))
    acc = {str(f): x[0] for f, x in zip(have, hh)}
    bank30 = np.concatenate([x[1] for x in hh]) if hh else np.zeros((0, 256), np.float32)
    todo = [(t, n) for t, n in want if str(name(t, n)) not in acc]
    bank_new = V3.bank_of(list(acc.values()))
    print(f"готовых: {len(acc)}, собрать: {len(todo)}", flush=True)
    rng = random.Random(a.seed + len(acc) * 7919)
    cand = WORK / "cand"
    cand.mkdir(parents=True, exist_ok=True)
    Q._state.update(done=len(acc), total=len(want))
    Q.tick("skinive3 7 с: сборка + проверка каждого кадра — принят только ролик без общих кадров со всеми")
    tried = rej_u = rej_f = 0
    man_f = WORK / "manifest.json"
    man = json.loads(man_f.read_text(encoding="utf-8")) if man_f.exists() else {}
    with ThreadPoolExecutor(a.jobs) as ex:
        live: set = set()
        while todo or live:
            while todo and len(live) < a.jobs + 1:
                tried += 1
                live.add(ex.submit(build_one, candidate(rng), cand / f"c{tried:05d}.mp4"))
            done, live = wait(live, return_when=FIRST_COMPLETED)
            for fu in done:
                try:
                    c, tmp, h, bad, fr = fu.result()
                except Exception as e:                       # noqa: BLE001
                    print("  ОШИБКА сборки кандидата:", str(e)[:300], flush=True)
                    continue
                if bad or fr:
                    rej_f += 1
                    print(f"  брак {tmp.name}: {('bad_frames ' + str(bad[:5])) if bad else ('кадры не те ' + str(fr[:4]))}",
                          flush=True)
                    tmp.unlink(missing_ok=True)
                    continue
                h, hb = h
                if not todo or V3.shares(h, bank_new) or V3.shares(h, bank_old) or near30(hb, bank30):
                    rej_u += 1
                    tmp.unlink(missing_ok=True)
                    continue
                tag, n = todo.pop(0)
                dst = name(tag, n)
                tmp.replace(dst)
                acc[str(dst)] = h
                man[dst.name] = c
                bank_new = np.concatenate([bank_new, V3.bank_of([h])])
                bank30 = np.concatenate([bank30, hb])
                man_f.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
                Q._state.update(done=len(acc))
                Q.tick()
                if len(acc) % 10 == 0 or not todo:
                    print(f"  ✓ {len(acc)}/{len(want)} (собрано {tried}, похожих отсеяно {rej_u}, брак {rej_f})",
                          flush=True)
    print(f"ИТОГ: {len(acc)} → {', '.join(str(d) for d in outs.values())}; собрано {tried}, похожих отсеяно {rej_u}, "
          f"брак {rej_f}", flush=True)
    Q.PROG.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
