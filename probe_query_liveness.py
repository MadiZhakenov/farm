#!/usr/bin/env python3
"""
Эксперимент: какие Pinterest-запросы дают живые (UGC) фото, а какие — сток.

Каждый запрос проходит тот же путь, что в фабрике (finalize_photo_query →
поиск → отсев stub / blacklist / ИИ-метка / мусорный title), берутся первые
PER_QUERY пинов, скачиваются и оцениваются той же UGC-моделью, что и в
пайплайне (core.ugc_filter). Каруселей не собирает, учёт серии не трогает.

Наборы запросов:
  pool       — текущие филлер-запросы (carousel_rules)
  factorial  — 12 предметов × 6 вариантов формулировки
               (plain / candid / aesthetic / руки / ночь / POV) — проверка
               гипотез «что в формулировке делает фото живым»
  mundane    — бытовые мелочи (ключи, зарядка, пакеты из магазина…)

  python probe_query_liveness.py                 # все наборы
  python probe_query_liveness.py --sets pool     # один набор
  python probe_query_liveness.py --plan plan.json --out out/query_liveness_v2
      план: [{"query": ..., "raw": true, ...любые метки для анализа}]

На каждый кадр: живость (UGC), смысл к запросу (SigLIP), лица (Haar),
предмет (метки carousel_rules).

Выход: out/query_liveness_<время>/ — pins.csv, queries.csv, summary.md,
листы кадров лучших и худших запросов.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics as st
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import carousel_rules as cr  # noqa: E402
from core.harvester import (  # noqa: E402
    UGC_HARD_FLOOR,
    PinterestHarvester,
    finalize_photo_query,
    is_fake_stub_pin_id,
    title_looks_like_junk,
)
from core.photo_vault import drop_blacklisted_pins  # noqa: E402

PER_QUERY = 24  # фабрика смотрит первые 12; берём 24 для устойчивости
PIPELINE_TOP = 12
CHUNK = 240  # пинов за порцию скачивания/оценки
LIVE = UGC_HARD_FLOOR  # 0.55 — порог «живого» кадра в пайплайне

FACTORIAL: dict[str, dict[str, str]] = {
    "coffee": {
        "plain": "coffee cup table", "candid": "coffee cup table candid",
        "aesthetic": "coffee cup table aesthetic", "hands": "hands holding coffee cup",
        "night": "coffee cup table night", "pov": "pov drinking coffee",
    },
    "strawberries": {
        "plain": "strawberries bowl table", "candid": "strawberries bowl candid",
        "aesthetic": "strawberries bowl aesthetic", "hands": "hand holding strawberries",
        "night": "strawberries bowl night", "pov": "pov eating strawberries",
    },
    "flowers": {
        "plain": "flowers vase table", "candid": "flowers vase candid",
        "aesthetic": "flowers vase aesthetic", "hands": "hands holding flowers bouquet",
        "night": "flowers vase night", "pov": "pov holding flowers",
    },
    "window": {
        "plain": "bedroom window curtains", "candid": "bedroom window candid",
        "aesthetic": "bedroom window aesthetic", "hands": "hand on window glass",
        "night": "bedroom window night", "pov": "pov looking out window",
    },
    "street": {
        "plain": "city street sidewalk", "candid": "city street candid",
        "aesthetic": "city street aesthetic", "hands": "feet walking sidewalk",
        "night": "city street night", "pov": "pov walking city street",
    },
    "sky": {
        "plain": "sunset sky", "candid": "sunset sky candid",
        "aesthetic": "sunset sky aesthetic", "hands": "hand holding phone sunset",
        "night": "night sky city", "pov": "pov sunset walk",
    },
    "bed": {
        "plain": "bed white sheets", "candid": "unmade bed candid",
        "aesthetic": "bed sheets aesthetic", "hands": "feet in bed blanket",
        "night": "bed night lamp", "pov": "pov lying in bed",
    },
    "desk": {
        "plain": "laptop desk", "candid": "laptop desk candid",
        "aesthetic": "laptop desk aesthetic", "hands": "hands typing laptop",
        "night": "laptop desk night", "pov": "pov working laptop",
    },
    "kitchen": {
        "plain": "kitchen counter", "candid": "kitchen counter candid",
        "aesthetic": "kitchen counter aesthetic", "hands": "hands cooking kitchen",
        "night": "kitchen counter night", "pov": "pov cooking kitchen",
    },
    "car": {
        "plain": "car interior", "candid": "car interior candid",
        "aesthetic": "car interior aesthetic", "hands": "hands on steering wheel",
        "night": "car interior night", "pov": "pov driving car",
    },
    "book": {
        "plain": "book on table", "candid": "reading book candid",
        "aesthetic": "book aesthetic", "hands": "hands holding book",
        "night": "reading book night", "pov": "pov reading book",
    },
    "pasta": {
        "plain": "pasta plate table", "candid": "pasta plate candid",
        "aesthetic": "pasta plate aesthetic", "hands": "hand holding fork pasta",
        "night": "pasta dinner night", "pov": "pov eating pasta",
    },
}
MUNDANE = [
    "keys on table", "phone charger bed", "laundry basket floor", "grocery bags floor",
    "shoes by front door", "bathroom mirror selfie", "hoodie on chair", "tote bag table",
    "train window view", "umbrella rainy street", "receipt on table", "takeout coffee car",
]


def build_queries(sets: list[str]) -> list[dict]:
    out: list[dict] = []
    if "pool" in sets:
        pool = list(dict.fromkeys(
            cr.NEUTRAL_LIGHT + cr.NEUTRAL_FOOD + cr.NEUTRAL_MOODY
            + cr.FINAL_PLEASANT + cr.FINAL_CALM
        ))
        out += [{"set": "pool", "query": q, "subject": "", "variant": ""} for q in pool]
    if "factorial" in sets:
        for subj, vs in FACTORIAL.items():
            out += [{"set": "factorial", "query": q, "subject": subj, "variant": v} for v, q in vs.items()]
    if "mundane" in sets:
        out += [{"set": "mundane", "query": q, "subject": "", "variant": ""} for q in MUNDANE]
    return out


def _face_counter():
    import cv2

    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    def count(im: Image.Image) -> int:
        import numpy as np

        g = im.convert("L")
        g.thumbnail((640, 640))
        a = np.asarray(g)
        return int(len(casc.detectMultiScale(a, 1.1, 5, minSize=(28, 28))))

    return count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", default="pool,factorial,mundane")
    ap.add_argument("--plan", type=Path, help="JSON-план: [{query, raw?, ...метки}]")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    if args.plan:
        rows = json.loads(args.plan.read_text(encoding="utf-8"))
    else:
        sets = [s.strip() for s in args.sets.split(",") if s.strip()]
        rows = build_queries(sets)
    out = args.out or ROOT / "out" / f"query_liveness_{datetime.now():%Y%m%d_%H%M%S}"
    (out / "thumbs").mkdir(parents=True, exist_ok=True)
    print(f"строк плана: {len(rows)} · выход: {out}")

    h = PinterestHarvester(on_status=lambda m: None)
    h.warm_session(force=True)

    # 1) поиск: raw=True — строка уходит как есть, иначе через чистильщик фабрики.
    # Одинаковые строки поиска ищутся один раз.
    t0 = time.perf_counter()
    from core.harvester import PinMeta

    cache_f = out / "search_cache.json"
    disk: dict[str, list[dict]] = (
        json.loads(cache_f.read_text(encoding="utf-8")) if cache_f.exists() else {}
    )
    searches: dict[str, dict] = {}
    items: list[tuple] = []
    for k, r in enumerate(rows):
        q = r["query"] if r.get("raw") else (finalize_photo_query(r["query"]) or r["query"])
        r["final"] = q
        key = q.lower()
        if key in searches:
            continue
        if key in disk:
            pins = [PinMeta(**d) for d in disk[key]]
        else:
            pins = h.search(q, finalize=False)
            disk[key] = [
                {"pin_id": x.pin_id, "title": x.title, "image_url": x.image_url,
                 "orig_url": x.orig_url, "is_ai": x.is_ai}
                for x in pins
            ]
            if len(disk) % 20 == 0:
                cache_f.write_text(json.dumps(disk, ensure_ascii=False), encoding="utf-8")
        found = len(pins)
        pins = [p for p in pins if not is_fake_stub_pin_id(p.pin_id)]
        pins, _bl = drop_blacklisted_pins(pins)
        ai = sum(1 for p in pins if p.is_ai is True)
        pins = [p for p in pins if p.is_ai is not True and not title_looks_like_junk(p.title)]
        sel = pins[:PER_QUERY]
        searches[key] = {"search": q, "found": found, "ai_flag": ai,
                         "ai_share": round(ai / max(1, found), 3), "taken": len(sel)}
        items += [(p, q, rank) for rank, p in enumerate(sel)]
        print(f"[{k + 1}/{len(rows)}] «{q}»: сеть {found}, ИИ-метка {ai}, взято {len(sel)}")
    cache_f.write_text(json.dumps(disk, ensure_ascii=False), encoding="utf-8")
    print(f"поиск: {len(searches)} строк · {time.perf_counter() - t0:.0f} с")

    # 2–3) скачивание + живость + лица + предмет — порциями; каждый пин один
    # раз (один пин часто приходит на несколько запросов). Кэш харвестера
    # держит все картинки — чистим его после каждой порции (иначе ~19 ГБ ОЗУ
    # и «Operation on closed image» на повторном пине).
    import numpy as np

    from core.taste_embedder import get_embedder

    emb = get_embedder()
    clf = cr.get_photo_classifier()
    faces = _face_counter()
    t1 = time.perf_counter()
    uniq: dict[str, tuple] = {}
    for p_, q, _r in items:
        uniq.setdefault(str(p_.pin_id), (p_, q))
    todo = list(uniq.values())
    metrics: dict[str, dict] = {}
    for start in range(0, len(todo), CHUNK):
        part = todo[start:start + CHUNK]
        cands = asyncio.run(h._download_many(part))
        h._apply_ugc_gate(cands)
        if cands:
            vecs = emb.embed_images([c.image.convert("RGB") for c in cands],
                                    cache_keys=[str(c.pin_id) for c in cands])
        for c, v in zip(cands, vecs if cands else []):
            pid = str(c.pin_id)
            subj, sprob = clf.subject_of_vector(v)
            thumb = out / "thumbs" / f"{pid}.jpg"
            if not thumb.exists():
                im = c.image.convert("RGB")
                im.thumbnail((220, 300))
                im.save(thumb, quality=82)
            metrics[pid] = {
                "ugc": round(float(c.ugc_score), 4), "vec": np.asarray(v, dtype=np.float32),
                "faces": faces(c.image), "subject": subj, "subject_prob": round(float(sprob), 3),
                "w": c.image.width, "h": c.image.height,
            }
        h._pin_cand_cache.clear()
        for c in cands:
            try:
                c.image.close()
            except Exception:
                pass
        del cands
        print(f"скачано и оценено {len(metrics)}/{min(start + CHUNK, len(todo))} уникальных · "
              f"{time.perf_counter() - t1:.0f} с")

    texts = sorted({q for _p, q, _r in items})
    tvec = dict(zip(texts, emb.embed_texts(texts)))
    pin_rows = []
    for p_, q, rank in items:
        m = metrics.get(str(p_.pin_id))
        if m is None:
            continue
        rel = float(emb._cosine_to_prob(np.array([float(m["vec"] @ tvec[q])]))[0])
        pin_rows.append({
            "search": q, "rank": rank, "pin_id": p_.pin_id, "ugc": m["ugc"],
            "rel": round(rel, 4), "faces": m["faces"], "subject": m["subject"],
            "subject_prob": m["subject_prob"], "w": m["w"], "h": m["h"],
            "title": (p_.title or "")[:80],
        })

    with (out / "pins.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(pin_rows[0].keys()))
        w.writeheader()
        w.writerows(pin_rows)
    with (out / "searches.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(next(iter(searches.values())).keys()))
        w.writeheader()
        w.writerows(searches.values())

    # строки плана с метриками по первым PIPELINE_TOP кадрам их поиска
    per_s: dict[str, list[dict]] = defaultdict(list)
    for pr in pin_rows:
        per_s[pr["search"].lower()].append(pr)
    q_rows = []
    for r in rows:
        ps = sorted(per_s.get(r["final"].lower(), []), key=lambda x: x["rank"])
        if not ps:
            continue
        top = ps[:PIPELINE_TOP]
        u = [x["ugc"] for x in top]
        sr = searches[r["final"].lower()]
        row = {k: v for k, v in r.items()}
        row.update({
            "n": len(ps), "mean_top12": round(st.mean(u), 4),
            "live_n_top12": sum(1 for x in u if x >= LIVE),
            "ok30_n_top12": sum(1 for x in u if x >= 0.30),
            "mean_all": round(st.mean(x["ugc"] for x in ps), 4),
            "rel_mean_top12": round(st.mean(x["rel"] for x in top), 4),
            "face_share_top12": round(sum(1 for x in top if x["faces"]) / len(top), 3),
            "usable_n_top12": sum(1 for x in top if x["ugc"] >= LIVE and x["rel"] >= 0.20 and not x["faces"]),
            "ai_share": sr["ai_share"], "found": sr["found"],
            "rewritten": r["final"].lower() != r["query"].lower(),
        })
        q_rows.append(row)
    q_rows.sort(key=lambda x: -x["mean_top12"])
    keys = sorted({k for r in q_rows for k in r})
    with (out / "queries.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(q_rows)
    (out / "queries.json").write_text(json.dumps(q_rows, ensure_ascii=False, indent=1), encoding="utf-8")

    per_q = {r["query"]: per_s[r["final"].lower()] for r in q_rows}
    write_sheets(out, q_rows, per_q)
    if not args.plan:
        write_summary(out, q_rows)
    print(f"готово → {out}")
    return 0


def write_sheets(out: Path, q_rows: list[dict], per_q: dict) -> None:
    font = ImageFont.truetype("arial.ttf", 15)
    tw, th, per = 120, 160, 8

    def sheet(qs: list[dict], name: str, title: str) -> None:
        W = 330 + per * tw
        H = 34 + len(qs) * (th + 6)
        s = Image.new("RGB", (W, H), (26, 26, 26))
        d = ImageDraw.Draw(s)
        d.text((8, 8), title, fill=(255, 230, 120), font=font)
        for i, q in enumerate(qs):
            y = 34 + i * (th + 6)
            d.text((6, y + 4), q["final"][:38], fill=(235, 235, 235), font=font)
            d.text((6, y + 26), f"живость {q['mean_top12']:.2f}", fill=(140, 220, 160), font=font)
            d.text((6, y + 46), f"живых {q['live_n_top12']}/12", fill=(140, 220, 160), font=font)
            ps = sorted(per_q[q["query"]], key=lambda x: int(x["rank"]))[:per]
            for j, pr in enumerate(ps):
                p = out / "thumbs" / f"{pr['pin_id']}.jpg"
                if p.exists():
                    im = Image.open(p)
                    im.thumbnail((tw - 4, th - 18))
                    s.paste(im, (330 + j * tw, y))
                    d.text((330 + j * tw + 2, y + th - 18), f"{pr['ugc']:.2f}",
                           fill=(255, 255, 255) if pr["ugc"] >= LIVE else (255, 120, 120), font=font)
        s.save(out / name, quality=84)

    sheet(q_rows[:15], "sheet_best.jpg", "Самые живые запросы (первые 8 кадров выдачи, цифра — живость)")
    sheet(q_rows[-15:][::-1], "sheet_worst.jpg", "Самые стоковые запросы (первые 8 кадров выдачи)")


def write_summary(out: Path, q_rows: list[dict]) -> None:
    lines = [f"# Живость Pinterest-запросов ({datetime.now():%Y-%m-%d %H:%M})", ""]
    lines.append(f"Метрика: средняя UGC-оценка первых {PIPELINE_TOP} кадров выдачи (то, что видит фабрика); "
                 f"«живых» — кадров с оценкой ≥ {LIVE}.")
    lines.append("")
    fact = [q for q in q_rows if q["set"] == "factorial"]
    if fact:
        by_v: dict[str, list[float]] = defaultdict(list)
        for q in fact:
            by_v[q["variant"]].append(q["mean_top12"])
        base = {q["subject"]: q["mean_top12"] for q in fact if q["variant"] == "plain"}
        lines += ["## Формулировка (12 предметов × 6 вариантов)", "",
                  "| вариант | средняя живость | разница с plain (по тем же предметам) |", "|---|---|---|"]
        for v in ("plain", "candid", "aesthetic", "hands", "night", "pov"):
            vals = [q for q in fact if q["variant"] == v]
            if not vals:
                continue
            diffs = [q["mean_top12"] - base[q["subject"]] for q in vals if q["subject"] in base]
            lines.append(f"| {v} | {st.mean(q['mean_top12'] for q in vals):.3f} | "
                         f"{st.mean(diffs):+.3f} |")
        lines += ["", "## Предмет (среднее по 6 вариантам)", "", "| предмет | живость |", "|---|---|"]
        by_s: dict[str, list[float]] = defaultdict(list)
        for q in fact:
            by_s[q["subject"]].append(q["mean_top12"])
        for s, v in sorted(by_s.items(), key=lambda x: -st.mean(x[1])):
            lines.append(f"| {s} | {st.mean(v):.3f} |")
    rew = [q for q in q_rows if q.get("rewritten")]
    if rew:
        lines += ["", "## Чистильщик запросов переписал", "", "| задумано | ушло в поиск | живость |", "|---|---|---|"]
        for q in rew:
            lines.append(f"| {q['query']} | {q['final']} | {q['mean_top12']:.3f} |")
    lines += ["", "## Все запросы", "",
              "| запрос (как ушёл в поиск) | набор | живость | живых из 12 | ИИ-метка в выдаче |",
              "|---|---|---|---|---|"]
    for q in q_rows:
        lines.append(f"| {q['final']} | {q['set']} | {q['mean_top12']:.3f} | {q['live_n_top12']} | "
                     f"{q.get('ai_share', 0):.0%} |")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
