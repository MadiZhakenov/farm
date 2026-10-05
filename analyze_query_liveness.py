#!/usr/bin/env python3
"""
Анализ эксперимента v2 (probe_query_liveness.py --plan …): формулировка,
предмет, реальные сценные запросы Gemini, чистильщик, позиция в выдаче,
стабильность, лица, смысл, слова-маркеры. Пишет analysis.md и листы кадров.

  python analyze_query_liveness.py out/query_liveness_v2 [--v1 out/query_liveness_<прошлый прогон>]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

LIVE = 0.55
OK = 0.30  # по ручным оценкам ниже 0.30 «да» только у 10%
TOP = 12
RNG = random.Random(0)
L: list[str] = []


def say(s: str = "") -> None:
    print(s)
    L.append(s)


def boot_ci(d: list[float], n: int = 4000) -> tuple[float, float]:
    if len(d) < 2:
        return (float("nan"), float("nan"))
    b = sorted(st.mean(RNG.choices(d, k=len(d))) for _ in range(n))
    return b[int(0.025 * n)], b[int(0.975 * n) - 1]


def load(out: Path):
    P = list(csv.DictReader((out / "pins.csv").open(encoding="utf-8")))
    for p in P:
        for k in ("ugc", "rel", "subject_prob"):
            p[k] = float(p[k])
        for k in ("rank", "faces", "w", "h"):
            p[k] = int(p[k])
    S = {r["search"].lower(): r for r in csv.DictReader((out / "searches.csv").open(encoding="utf-8"))}
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    by_s: dict[str, list[dict]] = defaultdict(list)
    for p in P:
        by_s[p["search"].lower()].append(p)
    for v in by_s.values():
        v.sort(key=lambda x: x["rank"])
    return P, S, plan, by_s


def qstats(ps: list[dict]) -> dict:
    top = ps[:TOP]
    if not top:
        return {}
    u = [x["ugc"] for x in top]
    return {
        "live": st.mean(u),
        "live_n": sum(1 for x in u if x >= LIVE),
        "ok_n": sum(1 for x in u if x >= OK),
        "rel": st.mean(x["rel"] for x in top),
        "face": sum(1 for x in top if x["faces"]) / len(top),
        "usable": sum(1 for x in top if x["ugc"] >= LIVE and x["rel"] >= 0.20 and not x["faces"]),
        "n": len(top),
    }


# «По теме» = SigLIP относит кадр к тому же предмету, что и запрос (top-1 из
# SUBJECT_PROMPTS правил карусели). Абсолютная вероятность SigLIP к короткому
# тексту («coffee cup») почти всегда < 0.2 даже для чашки кофе — не годится.
EXPECTED = {
    "coffee": "drink", "tea": "drink", "strawberries": "fruit", "pasta": "plate",
    "breakfast": "plate", "flowers": "plants", "window": "window", "street": "road",
    "sunset": "sky", "bed": "bed", "laptop": "desk", "kitchen": "kitchen", "car": "car",
    "book": "book", "rain": "window", "groceries": "groceries",
}


def add_topic_relevance(out: Path, rows: list[dict], by_s: dict) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from core import carousel_rules as cr
    from core.taste_embedder import get_embedder

    emb = get_embedder()
    clf = cr.get_photo_classifier()
    clf._ensure()
    names = list(clf._t_subject)
    for r in rows:
        if r["group"] == "scene" and r.get("variant") == "orig":
            SCENE_ORIG[r["scene_id"]] = r["query"]
    expect = {}
    for r in rows:
        if r["group"] == "modifier":
            expect[r["search"]] = EXPECTED.get(r["subject"])
        elif r["group"] == "scene":
            e = cr.query_subject(SCENE_ORIG.get(r["scene_id"], r["query"]))
            expect[r["search"]] = None if e in ("other", "candle") else e
    pids = list({x["pin_id"] for k in expect for x in by_s.get(k, [])[:TOP]})
    top1 = {}
    for i in range(0, len(pids), 128):
        chunk = pids[i:i + 128]
        ims = []
        for pid in chunk:
            f = out / "thumbs" / f"{pid}.jpg"
            ims.append(Image.open(f).convert("RGB") if f.exists() else Image.new("RGB", (8, 8)))
        for pid, v in zip(chunk, emb.embed_images(ims, cache_keys=chunk)):
            sims = np.array([float(np.max(clf._t_subject[n] @ v)) for n in names])
            top1[pid] = names[int(np.argmax(sims))]
    for r in rows:
        e = expect.get(r["search"])
        if not e:
            continue
        top = by_s.get(r["search"], [])[:TOP]
        on = [top1.get(x["pin_id"]) == e for x in top]
        r["st"]["topic"] = sum(on) / len(top)
        r["st"]["usable"] = sum(1 for x, o in zip(top, on) if o and x["ugc"] >= LIVE and not x["faces"])
        r["st"]["usable_any"] = sum(1 for x, o in zip(top, on) if o and x["ugc"] >= LIVE)
        r["st"]["ok_topic"] = sum(1 for x, o in zip(top, on) if o and x["ugc"] >= OK)


SCENE_ORIG: dict = {}


def paired(rows: list[tuple[str, dict, dict]], metric: str) -> tuple[float, tuple, int, int]:
    d = [b[metric] - a[metric] for _k, a, b in rows if metric in a and metric in b]
    if not d:
        return float("nan"), (float("nan"), float("nan")), 0, 0
    return st.mean(d), boot_ci(d), sum(1 for x in d if x > 0), len(d)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--v1", type=Path, default=None)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = args.out
    P, S, plan, by_s = load(out)
    for r in plan:
        r["search"] = r["query"].lower()
        r["st"] = qstats(by_s.get(r["search"], []))
    rows = [r for r in plan if r["st"]]
    add_topic_relevance(out, rows, by_s)

    say(f"# Живость Pinterest-запросов — эксперимент v2")
    say()
    say(f"Поисков {len(S)}, кадров {len(P)}, строк плана {len(rows)}. Метрики по первым {TOP} "
        f"кадрам выдачи (то, что видит фабрика). «Живой» — живость ≥ {LIVE}; "
        f"«годный» — ≥ {OK} (порог по ручным оценкам). «Пригодный для филлера» — "
        f"живой + по теме запроса (смысл ≥ 0.20) + без лица.")

    # 0) метрика vs ручные оценки
    vfile = out.parent / "liveness_metric_validation.json"
    if not vfile.exists():
        vfile = Path(__file__).resolve().parent / "out" / "liveness_metric_validation.json"
    if vfile.exists():
        v = json.loads(vfile.read_text(encoding="utf-8"))
        s, y = np.array(v["scores"]), np.array(v["labels"])
        say()
        say("## 0. Можно ли верить метрике")
        say(f"Ручные оценки «да/нет» ({v['n']} фото): AUC живости = {v['auc']:.2f}.")
        for lo, hi in ((0, .3), (.3, .45), (.45, .55), (.55, .65), (.65, 1.01)):
            m = (s >= lo) & (s < hi)
            if m.sum():
                say(f"- живость {lo:.2f}–{min(hi, 1):.2f}: «да» у {y[m].mean():.0%} (n={m.sum()})")

    # 1) формулировка
    M = [r for r in rows if r["group"] == "modifier"]
    base = {r["subject"]: r["st"] for r in M if r["modifier"] == "plain"}
    mods = [m for m in dict.fromkeys(r["modifier"] for r in M) if m != "plain"]
    say()
    say("## 1. Формулировка (16 предметов, разница с простым запросом)")
    say()
    say("| вариант | Δ живость [95%] | лучше простого | Δ живых из 12 | Δ живых по теме | Δ пригодных | доля по теме | лица | ИИ-метка |")
    say("|---|---|---|---|---|---|---|---|")
    mod_rank = []
    for m in mods:
        pr = [(r["subject"], base[r["subject"]], r["st"]) for r in M if r["modifier"] == m and r["subject"] in base]
        d, ci, w, n = paired(pr, "live")
        dn = paired(pr, "live_n")[0]
        du = paired(pr, "usable")[0]
        dr = st.mean(b["topic"] for _k, _a, b in pr if "topic" in b)
        dua = paired(pr, "usable_any")[0]
        fs = st.mean(b["face"] for _k, _a, b in pr)
        ai = st.mean(float(S[r["search"]]["ai_share"]) for r in M if r["modifier"] == m)
        mod_rank.append((d, m))
        say(f"| {m} | {d:+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}] | {w}/{n} | {dn:+.1f} | {dua:+.1f} | {du:+.1f} | {dr:.0%} | {fs:.0%} | {ai:.0%} |")
    pf = st.mean(b["face"] for b in base.values())
    pt = st.mean(b["topic"] for b in base.values() if "topic" in b)
    say(f"\nУ простых запросов: по теме {pt:.0%} кадров, лица в {pf:.0%}. «Пригодный» = живой + по теме + без лица.")

    # 1b) предмет × формулировка
    say()
    say("## 2. Предмет и формулировка вместе (живость, первые 12)")
    mlist = ["plain"] + [m for _d, m in sorted(mod_rank, reverse=True)]
    subs = list(dict.fromkeys(r["subject"] for r in M))
    grid = {(r["subject"], r["modifier"]): r["st"]["live"] for r in M}
    say()
    say("| предмет | " + " | ".join(mlist) + " | лучшее |")
    say("|---|" + "---|" * (len(mlist) + 1))
    for s_ in sorted(subs, key=lambda x: -st.mean(v for (a, _b), v in grid.items() if a == x)):
        vals = [grid.get((s_, m)) for m in mlist]
        best = max((v, m) for v, m in zip(vals, mlist) if v is not None)
        say(f"| {s_} | " + " | ".join(f"{v:.2f}" if v is not None else "–" for v in vals) + f" | {best[1]} |")
    # доля дисперсии: предмет vs формулировка (аддитивная модель)
    ys = np.array([grid[k] for k in grid])
    sm = {s_: np.mean([grid[(s_, m)] for m in mlist if (s_, m) in grid]) for s_ in subs}
    mm = {m: np.mean([grid[(s_, m)] for s_ in subs if (s_, m) in grid]) for m in mlist}
    gm = ys.mean()
    ss_tot = ((ys - gm) ** 2).sum()
    ss_s = sum(((sm[s_] - gm) ** 2) * sum(1 for m in mlist if (s_, m) in grid) for s_ in subs)
    ss_m = sum(((mm[m] - gm) ** 2) * sum(1 for s_ in subs if (s_, m) in grid) for m in mlist)
    say(f"\nРазброс живости объясняет: формулировка {ss_m / ss_tot:.0%}, предмет {ss_s / ss_tot:.0%}, "
        f"их сочетание и шум {1 - (ss_m + ss_s) / ss_tot:.0%}.")

    # 3) реальные сценные запросы Gemini
    Sc = [r for r in rows if r["group"] == "scene"]
    by_id: dict[int, dict] = defaultdict(dict)
    for r in Sc:
        by_id[r["scene_id"]][r["variant"]] = r
    say()
    say("## 3. Реальные сценные запросы из прошлых каруселей (как есть → с правкой)")
    say()
    say("| правка | Δ живость [95%] | лучше в | Δ живых по теме | Δ доли по теме | лица после |")
    say("|---|---|---|---|---|---|")
    for v in ("candid", "pov"):
        pr = [(i, d["orig"]["st"], d[v]["st"]) for i, d in by_id.items() if "orig" in d and v in d]
        d_, ci, w, n = paired(pr, "live")
        say(f"| + {v} | {d_:+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}] | {w}/{n} | {paired(pr, 'usable_any')[0]:+.1f} | "
            f"{paired(pr, 'topic')[0]:+.0%} | {st.mean(b['face'] for _i, _a, b in pr):.0%} |")
    origs = [d["orig"]["st"]["live"] for d in by_id.values() if "orig" in d]
    say(f"\nСценные запросы как есть: живость {st.mean(origs):.3f}, "
        f"живых {st.mean(d['orig']['st']['live_n'] for d in by_id.values() if 'orig' in d):.1f} из 12.")

    # 4) чистильщик
    F = [r for r in rows if r["group"] == "finalize"]
    raw_of = {r["query"].lower(): r for r in rows}
    pr = [(r["raw_of"], raw_of[r["raw_of"].lower()]["st"], r["st"]) for r in F if r["raw_of"].lower() in raw_of]
    if pr:
        d_, ci, w, n = paired(pr, "live")
        say()
        say("## 4. Чистильщик запросов (finalize_photo_query)")
        say(f"После чистильщика живость {d_:+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}], лучше в {w}/{n}. "
            f"Смысл {paired(pr, 'rel')[0]:+.3f}.")
        adds = Counter()
        for k, _a, _b in pr:
            f = next(r["query"] for r in F if r["raw_of"] == k)
            adds.update(set(f.split()) - set(k.split()))
        say(f"Что дописывает: {', '.join(f'«{w}» ×{c}' for w, c in adds.most_common(6))}.")

    # 5) позиция в выдаче
    say()
    say("## 5. Позиция кадра в выдаче")
    say()
    say("| места | живость | живых |")
    say("|---|---|---|")
    for lo, hi in ((0, 6), (6, 12), (12, 18), (18, 24)):
        u = [p["ugc"] for p in P if lo <= p["rank"] < hi]
        if u:
            say(f"| {lo + 1}–{hi} | {st.mean(u):.3f} | {sum(1 for x in u if x >= LIVE) / len(u):.0%} |")

    # 6) стабильность
    if args.v1 and (args.v1 / "pins.csv").exists():
        v1p = list(csv.DictReader((args.v1 / "pins.csv").open(encoding="utf-8")))
        v1 = defaultdict(list)
        for p in v1p:
            v1[p["final"].lower()].append(p)
        pairs, jac = [], []
        for r in rows:
            if r["group"] != "stability":
                continue
            a = sorted(v1.get(r["search"], []), key=lambda x: int(x["rank"]))[:TOP]
            b = by_s.get(r["search"], [])[:TOP]
            if a and b:
                pairs.append((st.mean(float(x["ugc"]) for x in a), st.mean(x["ugc"] for x in b)))
                sa, sb = {x["pin_id"] for x in a}, {x["pin_id"] for x in b}
                jac.append(len(sa & sb) / len(sa | sb))
        if len(pairs) > 3:
            say()
            say("## 6. Стабильность (те же запросы через ~2 часа, новая сессия)")
            say(f"Корреляция живости запроса между прогонами r = {np.corrcoef(*zip(*pairs))[0, 1]:.2f} "
                f"(n={len(pairs)}); общих пинов в первых 12: {st.mean(jac):.0%}.")

    # 7) лица и живость (на уровне кадра, внутри запроса)
    say()
    say("## 7. Лица и живость")
    diffs = []
    for ps in by_s.values():
        f1 = [p["ugc"] for p in ps if p["faces"]]
        f0 = [p["ugc"] for p in ps if not p["faces"]]
        if f1 and f0:
            diffs.append(st.mean(f1) - st.mean(f0))
    ci = boot_ci(diffs)
    allf = sum(1 for p in P if p["faces"]) / len(P)
    dm = st.mean(diffs)
    verdict = (
        "модель живости не добавляет баллов за лицо — живость не равна «есть человек»"
        if ci[0] <= 0 <= ci[1]
        else ("кадры с лицом модель считает живее" if dm > 0 else "кадры с лицом модель считает менее живыми")
    )
    say(f"Кадры с лицом: {allf:.0%}. Внутри одного запроса кадр с лицом живее на "
        f"{dm:+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}] (n={len(diffs)} запросов) — {verdict}.")

    # 8) слова
    say()
    say("## 8. Слова в запросе (все запросы; среднее с словом минус без)")
    words = Counter()
    qlive = {k: qstats(v)["live"] for k, v in by_s.items() if v}
    for k in qlive:
        words.update(set(re.findall(r"[a-z]+", k)))
    eff = []
    for w_, c in words.items():
        if c < 6:
            continue
        a = [v for k, v in qlive.items() if w_ in re.findall(r"[a-z]+", k)]
        b = [v for k, v in qlive.items() if w_ not in re.findall(r"[a-z]+", k)]
        eff.append((st.mean(a) - st.mean(b), w_, c))
    eff.sort()
    say("Тянут в сток: " + ", ".join(f"«{w}» {d:+.2f} (×{c})" for d, w, c in eff[:10]))
    say("Тянут в живое: " + ", ".join(f"«{w}» {d:+.2f} (×{c})" for d, w, c in eff[::-1][:10]))

    # 9) ИИ-метка, размер
    ai = [(float(S[k]["ai_share"]), qlive[k]) for k in qlive if k in S]
    say()
    say(f"## 9. Прочее\nДоля ИИ-меток в выдаче vs живость: r = {np.corrcoef(*zip(*ai))[0, 1]:.2f}.")
    port = [p["ugc"] for p in P if p["h"] > p["w"] * 1.1]
    land = [p["ugc"] for p in P if p["w"] > p["h"] * 1.1]
    sq = [p["ugc"] for p in P if p not in port and abs(p["w"] - p["h"]) <= 0.1 * max(p["w"], p["h"])]
    say(f"Вертикальные кадры {st.mean(port):.3f} (n={len(port)}), горизонтальные {st.mean(land):.3f} "
        f"(n={len(land)}).")

    # 10) лучшие запросы для филлеров (живые, по теме, без лица)
    say()
    say("## 10. Лучшие запросы для филлеров (пригодных из 12: живой + по теме предмета + без лица)")
    best = sorted([r for r in rows if "topic" in r["st"]], key=lambda r: (-r["st"]["usable"], -r["st"]["live"]))
    seen = set()
    say()
    say("| запрос | пригодных | живых | живость | лица |")
    say("|---|---|---|---|---|")
    for r in best:
        if r["search"] in seen:
            continue
        seen.add(r["search"])
        say(f"| {r['query']} | {r['st']['usable']} | {r['st']['live_n']} | {r['st']['live']:.2f} | {r['st']['face']:.0%} |")
        if len(seen) >= 30:
            break

    (out / "analysis.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    sheets(out, rows, by_s)
    print(f"\n→ {out / 'analysis.md'}")
    return 0


def sheets(out: Path, rows: list[dict], by_s: dict) -> None:
    font = ImageFont.truetype("arial.ttf", 14)
    tw, th, per = 110, 150, 7
    # формулировки для 4 предметов
    M = [r for r in rows if r["group"] == "modifier"]
    for subj in ("coffee", "kitchen", "bed", "street"):
        rs = [r for r in M if r["subject"] == subj]
        if not rs:
            continue
        rs.sort(key=lambda r: -r["st"]["live"])
        W, H = 260 + per * tw, 30 + len(rs) * (th + 4)
        s = Image.new("RGB", (W, H), (26, 26, 26))
        d = ImageDraw.Draw(s)
        d.text((6, 6), f"«{subj}»: 12 формулировок (первые {per} кадров, цифра — живость)", fill=(255, 230, 120), font=font)
        for i, r in enumerate(rs):
            y = 30 + i * (th + 4)
            d.text((6, y + 4), r["query"][:34], fill=(235, 235, 235), font=font)
            d.text((6, y + 24), f"живость {r['st']['live']:.2f}  живых {r['st']['live_n']}/12", fill=(140, 220, 160), font=font)
            d.text((6, y + 44), f"лица {r['st']['face']:.0%}  пригодных {r['st']['usable']}", fill=(160, 180, 230), font=font)
            for j, p in enumerate(by_s[r["search"]][:per]):
                f = out / "thumbs" / f"{p['pin_id']}.jpg"
                if f.exists():
                    im = Image.open(f)
                    im.thumbnail((tw - 4, th - 16))
                    s.paste(im, (260 + j * tw, y))
                    d.text((262 + j * tw, y + th - 16), f"{p['ugc']:.2f}",
                           fill=(255, 255, 255) if p["ugc"] >= LIVE else (255, 120, 120), font=font)
        s.save(out / f"sheet_modifiers_{subj}.jpg", quality=84)


if __name__ == "__main__":
    raise SystemExit(main())
