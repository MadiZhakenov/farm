#!/usr/bin/env python3
"""Тайтлы / описания / теги для output/de_neutral_50 (формат как output/urgent_30/DE/_youtube_meta.txt):
у каждого ролика свой тайтл и описание (5 вариантов на историю), хэштеги и теги в разном порядке.
  python make_de_neutral_meta.py"""

from __future__ import annotations

import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIR = ROOT / "output" / "de_neutral_50"

# история → (тайтлы ×5, описания ×5, хэштеги, теги)
META = {
    1: (["Meine Schwiegermutter kam in Weiß zu meiner Hochzeit 👰",
         "Sie trug Weiß auf meiner Hochzeit – mein Mann hat's geregelt",
         "Die beste Antwort auf ein weißes Kleid",
         "Schwiegermutter vs. Hochzeit: 1:0 für meinen Mann",
         "Er hat nichts gesagt. Er hat ihr nur DAS gegeben 👇"],
        ["Ein weißes Kleid auf meiner Hochzeit. Mein Mann hatte die perfekte Antwort.",
         "Manche Leute lernen es nur so. Hättet ihr auch so reagiert? 👇",
         "Kein Streit, kein Drama – nur ein kleiner Zettel.",
         "Wenn die Schwiegermutter die Braut sein will…",
         "Sie ist vor dem Dessert gegangen. Verdient? 👇"],
        ["#storytime", "#hochzeit", "#schwiegermutter", "#shorts"],
        ["storytime", "hochzeit", "schwiegermutter", "brautkleid", "ehe", "familie", "drama", "beziehung", "shorts"]),
    2: (["Er war angeblich das ganze Wochenende bei seinem Bruder",
         "Dann rief sein Bruder mich an… 😶",
         "„Ich war bei meinem Bruder“ – sein Bruder sieht das anders",
         "Das Wochenende, an dem alles rauskam",
         "Wenn die Ausrede einen Anruf nicht überlebt 👇"],
        ["Sein Bruder wusste von nichts. Was hättet ihr gemacht? 👇",
         "Ein Anruf am Samstag und alles war klar.",
         "Die Ausrede hat genau bis Samstag gehalten.",
         "Manchmal verrät dich ausgerechnet die Familie.",
         "Und wo war er dann? 👀"],
        ["#storytime", "#beziehung", "#ehe", "#shorts"],
        ["storytime", "beziehung", "ehe", "ausrede", "lügen", "vertrauen", "partnerschaft", "drama", "shorts"]),
    3: (["Er hat mich betrogen – also hab ich eine Rede gehalten 🎤",
         "Meine Rache auf seiner Geburtstagsparty",
         "Ich hab mich bei ihr bedankt. Vor allen.",
         "Verrückt? Ich hab nicht Schluss gemacht…",
         "Die Geburtstagsrede, die er nie vergisst 👇"],
        ["Alle haben geklatscht. Sie war im Raum. 👇",
         "Ich hab gewartet – auf den perfekten Moment.",
         "Rache ist am besten mit Publikum.",
         "Team Rede oder Team einfach gehen? 👇",
         "Erst den Abschluss, dann die Rede."],
        ["#storytime", "#betrogen", "#rache", "#shorts"],
        ["storytime", "betrogen", "fremdgehen", "rache", "beziehung", "trennung", "geburtstag", "drama", "shorts"]),
    4: (["„Ich war betrunken, es hat nichts bedeutet“ 🙄",
         "Wenn es nichts bedeutet hat, warum alles löschen?",
         "Diese Ausrede glaube ich nie wieder",
         "Nachrichten, Anrufliste UND Fotos gelöscht…",
         "Betrunken ist keine Ausrede 👇"],
        ["Man löscht nicht alles, wenn es wirklich nichts bedeutet hat.",
         "Seid ihr Team „verzeihen“ oder Team „weg“? 👇",
         "Für alle, die diese Ausrede schon mal gehört haben.",
         "Gelöschte Chats sagen mehr als jede Entschuldigung.",
         "Ehrlich gesagt: das glaubt keiner 👇"],
        ["#beziehung", "#fremdgehen", "#vertrauen", "#shorts"],
        ["beziehung", "fremdgehen", "vertrauen", "ausrede", "nachrichten", "trennung", "liebe", "storytime", "shorts"]),
    5: (["Er hat meinen Geburtstag „vergessen“ 🎂",
         "Er hatte so viel Arbeit… in einer Rooftop-Bar",
         "Er hat nicht vergessen. Er hat sich entschieden.",
         "Seine Story hat ihn verraten",
         "Ich bin einfach zur Bar gefahren 👇"],
        ["Er hat sich nur für ihren Geburtstag entschieden. 👇",
         "Standort markiert. Freunde markiert. Und sie.",
         "Wenn eine Instagram-Story alles verrät.",
         "Was hättet ihr an meiner Stelle gemacht? 👇",
         "Schon wieder vergessen? Nein."],
        ["#storytime", "#geburtstag", "#beziehung", "#shorts"],
        ["storytime", "geburtstag", "beziehung", "fremdgehen", "instagram", "rooftop bar", "drama", "lügen", "shorts"]),
    6: (["Meine Schwester konnte sich meine Hochzeit „nicht leisten“",
         "Dann hab ich ihr Instagram gesehen… 🏝️",
         "Cancun. Am Tag meiner Hochzeit.",
         "Es ging nie ums Geld",
         "Ich hab ihr den Flug angeboten – sie sagte nein 👇"],
        ["Sie ist nicht gekommen, weil es meine Hochzeit war. 👇",
         "Wochenlang schlechtes Gewissen – und dann das.",
         "Familie kann manchmal am meisten wehtun.",
         "„Aus Prinzip“ – ja klar.",
         "Hättet ihr ihr verziehen? 👇"],
        ["#storytime", "#hochzeit", "#schwester", "#shorts"],
        ["storytime", "hochzeit", "schwester", "familie", "geschwister", "urlaub", "enttäuschung", "drama", "shorts"]),
    7: (["Mein Vater tauchte nach Jahren bei meinem Abschluss auf",
         "Ich bin einfach an ihm vorbeigegangen",
         "Das einzige Geschenk, das er verdient hat",
         "Der Mann, der mich großgezogen hat 🎓",
         "Mein Stiefvater hatte die perfekte Antwort 👇"],
        ["Nie angerufen, nie gezahlt – und dann mit Blumen. 👇",
         "Ein Vater ist, wer bleibt.",
         "Für alle Stiefväter, die geblieben sind. ❤️",
         "Manche kommen nur, wenn es was zu feiern gibt.",
         "Auf der Seite stand der richtige Name. 👇"],
        ["#storytime", "#familie", "#abschluss", "#shorts"],
        ["storytime", "familie", "vater", "stiefvater", "abschluss", "graduation", "kindheit", "emotional", "shorts"]),
    8: (["„Lass uns alles 50/50 teilen“ – okay 😌",
         "Er wollte 50/50. Er hat 50/50 bekommen.",
         "Ich hab ihm die Rechnung geschickt",
         "Halbes Kochen, halbes Putzen, halbe Geschenke",
         "Seitdem ist er ganz still 👇"],
        ["Fair ist fair, oder? 👇",
         "50/50 gilt dann aber für alles.",
         "Wenn er „fair“ sagt, nimm ihn beim Wort.",
         "Team 50/50 oder Team „wer mehr verdient, zahlt“? 👇",
         "Die Rechnung war länger als erwartet."],
        ["#beziehung", "#5050", "#paare", "#shorts"],
        ["beziehung", "50 50", "paare", "haushalt", "geld", "partnerschaft", "fairness", "storytime", "shorts"]),
    9: (["„Du siehst genau aus wie meine Ex“ 😬",
         "Er dachte, es war ein Kompliment…",
         "Die trockenste Antwort auf einer Hochzeit",
         "Sie ist meine Cousine. Und sie hat mir alles erzählt.",
         "Wie ich einen Typen auf einer Hochzeit blamiert hab 👇"],
        ["Falscher Spruch, falsche Person. 👇",
         "Manchmal ist die Welt einfach zu klein.",
         "Er hat danach nichts mehr gesagt.",
         "Die beste Antwort auf einen schlechten Anmachspruch.",
         "Hättet ihr auch so gekontert? 👇"],
        ["#storytime", "#hochzeit", "#dating", "#shorts"],
        ["storytime", "hochzeit", "dating", "anmachspruch", "ex", "cousine", "lustig", "konter", "shorts"]),
    10: (["Was meine Oma mir gesagt hat und ich nie vergessen hab",
          "5 Ratschläge meiner Oma über Männer 👵",
          "Omas Regeln, die immer noch stimmen",
          "Nummer 5 ist die wichtigste",
          "Die besten Tipps kommen von Oma 👇"],
         ["Welcher Rat ist euer Favorit? 👇",
          "Oma hatte einfach immer recht.",
          "Speichern und nie vergessen.",
          "Heirate den, der auch müde noch lieb ist. ❤️",
          "Was hat eure Oma euch beigebracht? 👇"],
         ["#oma", "#ratschläge", "#beziehung", "#shorts"],
         ["oma", "ratschläge", "beziehung", "lebensweisheiten", "tipps", "liebe", "männer", "familie", "shorts"]),
}


def main() -> int:
    rng = random.Random(1350)
    files = sorted(DIR.glob("de_*_v*_noid.mp4"))
    out = []
    for f in files:
        n, k = int(f.name.split("_")[1]), int(f.name.split("_v")[1].split("_")[0])
        titles, descs, hashtags, tags = META[n]
        h = hashtags[:]
        rng.shuffle(h)
        t = tags[:]
        rng.shuffle(t)
        out.append(f"===== {f.name} =====\nTITLE: {titles[k - 1]}\n\nDESCRIPTION:\n{descs[(k + n) % 5]}\n\n"
                   f"{' '.join(h)}\n\nTAGS: {', '.join(t)}\n")
    (DIR / "_youtube_meta.txt").write_text("\n".join(out), encoding="utf-8")
    print(len(out), "→", DIR / "_youtube_meta.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
