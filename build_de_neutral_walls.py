#!/usr/bin/env python3
"""
Нейтральный немецкий контент (айди нет, срочно): текстволлы без продукта в формате FollowSpy part 2
(build_followspy_walls.py) — 10 историй P2, переведены на немецкий (переносы по смыслу), по 5 версий = 50.
Версии одного текста — разные клипы (девушки A/B по очереди), при повторе клипа — другое окно и зеркало.
Музыка — реф этой истории, длина = длина рефа.

  python build_de_neutral_walls.py --only de_01_v1,de_10_v1 --out output/de_neutral_test
  python build_de_neutral_walls.py --jobs 5
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_followspy_walls as F  # noqa: E402

OUT = ROOT / "output" / "de_neutral_50"
F.FOLDER = {3: ""}
VERSIONS = 5

DE = [
    ("tt_kait", "btw meine schwiegermutter\nkam in einem weißen kleid\nzu meiner hochzeit.\nmein mann hat nichts gesagt.\n"
                "beim empfang\ngab er ihr eine geschenktüte.\ndrin war der kassenbon fürs kleid\nund ein zettel:\n"
                "\"du kannst es noch zurückgeben.\"\nsie ist vor dem dessert gegangen"),
    ("tt_cat", "Mein Mann meinte,\ner war das ganze Wochenende\nbei seinem Bruder.\nAm Samstag rief mich sein Bruder an\n"
               "und fragte, wo er ist"),
    ("tt_sofiia", "verrückt?\nmein freund hat mich betrogen,\nalso hab ich nicht schluss gemacht.\nich hab bis zu seiner\n"
                  "geburtstagsparty gewartet,\neine rede gehalten und mich\nbei dem mädchen bedankt,\n"
                  "dass sie \"ihn beschäftigt hat,\nwährend ich mein studium beendet hab.\"\nalle haben geklatscht.\n"
                  "sie war im raum"),
    ("ig_DVt8", "er kann tausendmal sagen\n\"ich war betrunken,\nes hat nichts bedeutet\"\naber ich werd's nie glauben,\n"
                "denn man löscht nicht die nachrichten,\ndie anrufliste UND die fotos,\nwenn es wirklich nichts bedeutet hat"),
    ("tt_roxanne", "Er hat meinen Geburtstag vergessen.\nSchon wieder.\nMeinte, er hätte \"so viel Arbeit.\"\n"
                   "Am selben Abend postete er eine Story\naus einer Rooftop-Bar.\nMit Standort.\nSeine Freunde markiert.\n"
                   "Und ein Mädchen,\ndas ich nicht kannte.\nIch hab ihm nicht geschrieben.\nIch bin zur Rooftop-Bar gefahren.\n"
                   "Sie war da.\nSie hat auch\nihren Geburtstag gefeiert.\nEr hat meinen Geburtstag nicht vergessen.\n"
                   "Er hat sich nur für ihren entschieden."),
    ("tt_bridget", "Meine Schwester meinte,\nsie kann sich die Reise\nzu meiner Hochzeit nicht leisten.\n"
                   "Ich hab angeboten, ihren Flug zu zahlen.\nSie sagte nein, \"aus Prinzip.\"\n"
                   "Ich hatte wochenlang ein schlechtes Gewissen.\nDann hab ich ihr Instagram gesehen.\n"
                   "Cancun. Dasselbe Wochenende.\nSie kam nicht wegen Geld\nnicht zu meiner Hochzeit.\n"
                   "Sie kam nicht,\nweil es meine war"),
    ("ig_Dcib", "mein vater ist gegangen, als ich 7 war.\nnie angerufen. nie einen cent gezahlt.\nletzten monat tauchte er\n"
                "mit blumen bei meinem abschluss auf,\nals wär nichts gewesen.\nmeine mama hat nur gelächelt\n"
                "und auf mich gezeigt.\nich bin einfach an ihm vorbeigegangen.\ndann kam mein stiefvater\n"
                "und gab ihm das programmheft,\naufgeschlagen auf der seite,\nauf der ich mich bedankt hab\n"
                "bei \"dem mann, der mich großgezogen hat.\"\ndort stand der name meines stiefvaters.\n\n"
                "und ehrlich? das war\ndas einzige geschenk, das er verdient hat."),
    ("tt_polyglot", "mein freund meinte: \"lass uns\nalles 50/50 teilen, das ist nur fair.\"\nich hab gelächelt, weil\n"
                    "es so fair klang.\nalso hab ich ihm die rechnung geschickt\nfürs halbe kochen,\ndas halbe putzen\n"
                    "und die hälfte der geschenke,\ndie ich für seine mutter gekauft hab.\nseitdem ist er ganz still"),
    ("tt_kia", "Hab gestern auf einer Hochzeit\neinen Typen richtig blamiert,\nweil er ankam und meinte:\n"
               "\"du siehst genau aus wie meine Ex\"\nund ich so: \"oh, das ist traurig\"\nund er lachte:\n"
               "\"nein, das ist ein Kompliment\"\nund meine Antwort war nur trocken:\n\"nein, ich meinte für sie,\n"
               "sie ist meine Cousine\nund hat mir alles erzählt\""),
    ("tt_milana", ["WAS MEINE OMA MIR GESAGT HAT\nUND ICH NIE VERGESSEN HAB:",
                   "1. Wenn es ihm leidtut, ändert er sich.\nWenn er nur sorry sagt, nicht.",
                   "2. Wein nie vor der Person,\ndie dich zum Weinen gebracht hat.",
                   "3. Hab immer Geld,\nvon dem er nichts weiß.",
                   "4. Wer zu Kellnern unhöflich ist,\nist es irgendwann auch zu dir.",
                   "5. Heirate den,\nder auch müde noch lieb ist."]),
]


def plan() -> list[dict]:
    """5 версий на текст: девушки A/B по очереди, у одного текста клипы не повторяются; клип — наименее
    использованный из тех, чьё спокойное окно не короче музыки; повтор клипа — другое окно и зеркало."""
    cache = ROOT / "downloads" / "followspy" / "usable_ranges.json"
    rng: dict[str, list[float]] = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}

    def usable(g: str, c: str) -> tuple[float, float]:
        if c not in rng:
            F.WL.SRC = F.SRC[g]
            rng[c] = list(F.WL.usable_range(c))
            cache.write_text(json.dumps(rng), encoding="utf-8")
        return tuple(rng[c])
    uses = {c: 0 for g in F.CLIPS for c in F.CLIPS[g]}
    rows = []
    for n, (ref, text) in enumerate(DE, 1):
        d = F.dur(F.REFS / f"{ref}.mp4")
        taken: set[str] = set()
        for k in range(1, VERSIONS + 1):
            g = "AB"[(n + k) % 2]
            ok = [c for c in F.CLIPS[g] if c not in taken and usable(g, c)[1] - usable(g, c)[0] >= d + 0.2]
            if not ok:
                g = "BA"[(n + k) % 2]
                ok = [c for c in F.CLIPS[g] if c not in taken and usable(g, c)[1] - usable(g, c)[0] >= d + 0.2]
            c = min(ok, key=lambda x: (uses[x], F.CLIPS[g].index(x)))
            taken.add(c)
            a, b = usable(g, c)
            u = uses[c]
            uses[c] += 1
            room = (b - a) - d
            start = a + (room * (0.1 + 0.4 * (u % 3) / 2) if room > 0 else 0)
            rows.append(dict(name=f"de_{n:02d}_v{k}", part=3, n=n, ref=ref, text=text, group=g, clip=c,
                             start=round(start, 2), dur=round(d, 3), mirror=(u // 3) % 2))
    return rows


def _render(job: tuple[dict, str, str]) -> str:
    r, out, work = job
    return str(F.render(r, Path(out), Path(work)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=5)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = plan()
    if a.only:
        keep = set(a.only.split(","))
        rows = [r for r in rows if r["name"] in keep]
    work = a.out / "_work"
    work.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(a.jobs) as ex:
        for dest in ex.map(_render, [(r, str(a.out), str(work)) for r in rows]):
            print(" ", Path(dest).name, flush=True)
    for f in work.glob("*.png"):
        f.unlink()
    work.rmdir()
    (a.out / "manifest.json").write_text(json.dumps([{k: v for k, v in r.items() if k != "text"} for r in rows],
                                                   indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"готово: {len(rows)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
