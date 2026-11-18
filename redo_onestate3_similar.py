#!/usr/bin/env python3
"""OneState 3 (ID 1): довести похожесть пар до нуля общих кадров.

Метрика — как measure_skinive_uniq.py: 3 кадра в секунду, dHash 16×16, кадр «узнаётся» при Хэмминге ≤ 40 (зеркало тоже).
Для каждой пары с хоть одним общим кадром пересобирается один ролик (жадно — тот, что встречается в большем числе пар).
На ролик пробуется один новый вариант нарезки за шаг; он принимается, только если с остальными 299 у него 0 общих кадров,
иначе — следующий вариант. Сборка — та же, что в build_onestate3_uniq.py (распаковка/вырезка/масштаб на видеокарте),
не больше 3 параллельных ffmpeg. Прогресс виден на дашборде (qa_batch.tick). Манифесты и план обновляются.

  python redo_onestate3_similar.py
"""

from __future__ import annotations

import json
import pickle
import random
import shutil
import subprocess
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_onestate3_uniq as U  # noqa: E402
import measure_skinive_uniq as M  # noqa: E402
import qa_batch as Q  # noqa: E402

WORK = U.WORK
TT, YT = ROOT / "output" / "onestate_3_TT_100", ROOT / "output" / "onestate_3_YT_200"
PKL = WORK / "uniq_hashes.pkl"
TMP = WORK / "refine_tmp"
PLAN = WORK / "uniq_plan_300_31340.json"         # план с кадром по центру и под интерфейсом (31337 — сдвиг вбок)


def sim(a, b) -> float:
    return max(M.match(a, b), M.match(b, a))


def complete(f: Path) -> bool:
    if not f.exists():
        return False
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip()) > 6.9
    except ValueError:
        return False


def cand(row: dict, seed: int) -> dict:
    """Вариант нарезки по зерну — тот же при повторе (уже собранные варианты берём из refine_tmp без пересборки)."""
    c = U.candidate(random.Random(seed), row["prof"], row["snd"])
    c.update(i=row["i"], text=row["text"], snd=row["snd"], score=row.get("score", 0))
    return c


def make(args: tuple) -> tuple:
    c, tmp = args
    if not complete(tmp):
        U.R.B.banner_anim()
        U.render(dict(c, out=str(tmp)))
    return M.hashes(tmp)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    vids = sorted(TT.glob("*.mp4")) + sorted(YT.glob("*.mp4"))
    if PKL.exists():
        pv, H = pickle.load(open(PKL, "rb"))
        pv = [v if Path(v).is_absolute() else ROOT / v for v in map(Path, pv)]
        assert [str(x).lower() for x in pv] == [str(x).lower() for x in vids], "список роликов изменился — удали кэш"
    else:
        with ThreadPoolExecutor(8) as ex:
            H = list(ex.map(M.hashes, vids))
    mans = {d: json.loads((WORK / f"manifest_{d.name}.json").read_text(encoding="utf-8")) for d in (TT, YT)}
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    TMP.mkdir(exist_ok=True)
    rnd = random.Random(777)
    name = lambda k: f"{vids[k].parent.name[11:13]}/{vids[k].name}"   # noqa: E731
    total_fixed = 0
    for rnd_i in range(8):
        pairs = [(i, j) for i in range(len(vids)) for j in range(i + 1, len(vids)) if sim(H[i], H[j]) > 0]
        print(f"круг {rnd_i + 1}: пар с общими кадрами {len(pairs)}", flush=True)
        if not pairs:
            break
        left, pick = list(pairs), []
        while left:
            k = Counter(x for p in left for x in p).most_common(1)[0][0]
            pick.append(k)
            left = [p for p in left if k not in p]
        # те же зёрна, что у прерванного запуска: по 3 на ролик в порядке pick (готовые файлы берутся из refine_tmp)
        queue = {k: [(rnd.randrange(1 << 30), TMP / f"{vids[k].parent.name}_{vids[k].stem}_{t}.mp4") for t in range(3)]
                 for k in pick}
        Q._state.update(done=0, total=len(pick))
        Q.tick(f"OneState 3: пересборка {len(pick)} роликов из похожих пар (круг {rnd_i + 1})")
        print("  пересобираю", len(pick), [name(k) for k in pick], flush=True)
        pending, step = list(pick), 0
        while pending:
            step += 1
            jobs = []
            for k in pending:
                if not queue[k]:
                    queue[k].append((rnd.randrange(1 << 30), TMP / f"{vids[k].parent.name}_{vids[k].stem}_s{step}.mp4"))
                seed, tmp = queue[k].pop(0)
                row = mans[vids[k].parent][vids[k].name]
                jobs.append((k, cand(row, seed), tmp))
            with ProcessPoolExecutor(3) as ex:                  # CUDA-распаковка → не больше 3 ffmpeg
                hs = list(ex.map(make, [(c, t) for _, c, t in jobs]))
            nxt = []
            for (k, c, tmp), h in zip(jobs, hs):
                worst = max(sim(h, H[j]) for j in range(len(vids)) if j != k)
                if worst == 0:
                    v = vids[k]
                    shutil.move(str(tmp), str(v))
                    H[k] = h
                    mans[v.parent][v.name] = dict(c, out=str(v))
                    plan[c["i"] - 1] = c
                    total_fixed += 1
                    Q.tick()
                    print(f"  ✓ {name(k)} (шаг {step})", flush=True)
                else:
                    tmp.unlink(missing_ok=True)
                    nxt.append(k)
            pending = nxt
            if pending:
                print(f"  шаг {step}: ещё похожи {len(pending)} — следующий вариант", flush=True)
            for d, m in mans.items():
                (WORK / f"manifest_{d.name}.json").write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
            PLAN.write_text(json.dumps(plan), encoding="utf-8")
            pickle.dump(([str(v) for v in vids], H), open(PKL, "wb"))
    shutil.rmtree(TMP, ignore_errors=True)
    Q.PROG.unlink(missing_ok=True)
    print(f"готово: пересобрано {total_fixed}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
