"""Нейтральные текстволлы «жиза» на немецком: 20 сюжетов × 6 версий = 120 (как ko_neutral_50 / br_neutral_50: бытовые узнаваемые
ситуации, без продуктов и без драмы). DE — (реф по длине текста, текст); META — номер сюжета → (6 тайтлов, 4 описания, хэштеги, теги)."""

_DUR = {"tt_kia": 5.17, "tt_cat": 5.53, "tt_kait": 5.73, "ig_Dcib": 6.21, "ig_DVt8": 6.64, "tt_polyglot": 6.76, "tt_bridget": 7.57,
        "tt_roxanne": 8.95, "tt_sofiia": 9.68}

_TEXTS = [
    "ich um 22 uhr:\nheute geh ich früh schlafen.\nich um 3 uhr nachts:\nschaue ein video,\nwie seife gemacht wird.\n"
    "wecker klingelt in 4 stunden.\nnur ich? 🙂",
    "5 mal den kühlschrank aufgemacht.\nnichts zu essen da.\nnochmal aufgemacht,\nvielleicht ist ja was aufgetaucht.\n"
    "mama: der kühlschrank ist doch voll!\nich: voll mit zutaten,\nnicht mit essen 😭",
    "20 minuten\nan einer nachricht gesessen.\ngeschrieben, gelöscht,\nneu geschrieben, 3 mal gelesen\nund abgeschickt.\n"
    "antwort von meiner freundin:\n\"ok\"\njetzt analysiere ich,\nwas dieses ok bedeuten soll",
    "jeden sonntag:\nab montag neues leben.\nfitnessstudio, salat,\num 23 uhr ins bett.\nmontag, 7 uhr morgens:\n4 mal snooze\n"
    "und mittags pizza.\negal,\nnächsten montag gibt's ja auch 🙂",
    "war nur kurz im supermarkt,\nmilch holen.\nrausgekommen mit:\nduftkerze, socken, chips,\neiner pflanze und einer neuen tasse.\n"
    "milch? vergessen.\nnochmal zurück 😭",
    "hab was online bestellt\nund checke die sendung\n12 mal am tag.\nendlich da,\ndirekt an der tür aufgerissen,\n"
    "wie ein geschenk an mich selbst.\n…socken.\naber ich freu mich 🙂",
    "freundin: \"bin gleich da!\"\nrealität: noch unter der dusche.\nich: warte seit 30 minuten im café.\naber mal ehrlich,\n"
    "ich hab auch schon\n\"bin unterwegs\" geschrieben\nund mir dabei die\nwimpern getuscht 🙂",
    "mein ordner mit gespeichertem:\n300 rezepte,\n120 workouts für zuhause,\n40 mal \"englisch in 30 tagen\".\n"
    "was ich davon gemacht hab:\nnichts.\naber gespeichert ist alles 🙂",
    "mama ruft an:\n\"isst du auch richtig?\"\nich um 23 uhr mit instant-nudeln:\n\"klar mama,\ngemüse, salat, alles dabei\" 🙂",
    ["DINGE, DIE JEDER MACHT,\nABER KEINER ZUGIBT:",
     "1. Die Nachricht nochmal lesen,\nnachdem man sie abgeschickt hat.",
     "2. Unter der Dusche\nStreitgespräche üben.",
     "3. Aufs Handy schauen,\nwenn man allein irgendwo steht.",
     "4. Nochmal in den Kühlschrank schauen,\nob was Neues drin ist.",
     "5. \"Bin gleich da\" schreiben\nund noch im Bett liegen."],
    "handy bei 1 %:\nich renne durch die wohnung\nwie bei einem notfall.\nladekabel gefunden.\n2 minuten später\nziehe ich es wieder ab,\n"
    "weil ich aufs sofa will.\nich bin das problem 🙂",
    "unter der dusche:\nich gewinne jede diskussion.\nperfekte sätze.\nrichtig schlagfertig.\nin echt, 3 tage vorher:\n\"äh… ja, du auch\" 😭",
    "kellner: \"guten appetit!\"\nich: \"danke, gleichfalls!\"\ner bringt nur das essen.\ner isst nicht mit.\ndas war vor 4 jahren.\n"
    "ich denke immer noch dran 😭",
    "besuch kommt in 10 minuten.\nalles unters bett,\nalles in den schrank,\nkerze an.\nbesuch: \"bei dir ist es\nimmer so ordentlich!\"\n"
    "bitte öffne hier keine tür 🙂",
    "mein stuhl im schlafzimmer:\nhat noch nie jemand drauf gesessen.\ndafür liegen da\n7 pullis, 3 jeans\nund ein leben,\n"
    "das ich irgendwann aufräume 🙂",
    "fitnessstudio: seit 14 monaten.\nwie oft ich da war: 3 mal.\nkostet mich pro besuch\nungefähr 130 euro.\naber ich kündige nicht,\n"
    "ab montag geh ich wieder hin 🙂",
    "wecker um 7.\nwecker um 7:05.\nwecker um 7:10.\nwecker um 7:15.\num 7:40 wach ich auf\nund renne los,\nmit einer socke in der hand 😭",
    "meine eltern:\n\"handys sind an allem schuld.\"\nauch meine eltern:\n14 videos am tag\nin die familiengruppe.\nmit ton.\num 6 uhr morgens 🙂",
    "freundin sagt das treffen ab.\nich nach außen:\n\"oh nein, wie schade!\"\nich innerlich:\nschlafanzug an,\nsofa,\nbester tag meines lebens 🙂",
    ["DINGE, DIE MAN NUR\nALS ERWACHSENER VERSTEHT:",
     "1. Sich über einen neuen\nSchwamm freuen.",
     "2. Um 21 Uhr müde sein\nund stolz drauf.",
     "3. \"Wir müssen uns unbedingt treffen\"\nheißt: in 2 Jahren.",
     "4. Das Geld ist weg,\nkeiner weiß wofür.",
     "5. Beim Aufstehen\nkomische Geräusche machen."],
]


def _assign() -> list:
    """Реф (музыка и длина) по объёму текста, как у KO/PT ≈ 23 знака в секунду; среди подходящих — наименее использованный."""
    uses = {k: 0 for k in _DUR}
    out = []
    for t in _TEXTS:
        if isinstance(t, list):
            out.append(("tt_milana", t))
            continue
        need = len(t) / 23
        ok = [k for k, d in _DUR.items() if need <= d <= need + 1.7] or ["tt_sofiia"]
        ref = min(ok, key=lambda k: (uses[k], _DUR[k]))
        uses[ref] += 1
        out.append((ref, t))
    return out


DE = _assign()

_H = ["#relatable", "#alltag", "#shorts"]
_T = ["relatable", "alltag", "lustig", "shorts", "fürdich"]
META = {
    1: (["heute geh ich wirklich früh schlafen 🌙", "ich um 22 uhr vs. ich um 3 uhr", "wecker klingelt in 4 stunden…",
         "warum ist seife machen so spannend 🧼", "mein schlafrhythmus in einem video", "früh schlafen? klar 🙂"],
        ["nur ich? 👇", "was schaut ihr nachts so? 👇", "sorry an mein morgiges ich 🙂", "wer kennt's? speichern 📌"],
        _H + ["#nachtmensch"], _T + ["schlafen", "nachts", "wecker", "müde"]),
    2: (["kühlschrank voll, nichts zu essen 😭", "wer den kühlschrank auch 5 mal aufmacht", "mama: der kühlschrank ist doch voll!",
         "zutaten sind kein essen", "vielleicht ist ja was aufgetaucht 👀", "ich und mein kühlschrank"],
        ["wie oft macht ihr ihn auf? 👇", "voll mit zutaten, leer an essen.", "mama versteht das nicht 😂", "nur ich? 👇"],
        _H + ["#kühlschrank"], _T + ["kühlschrank", "hunger", "mama", "essen"]),
    3: (["20 minuten geschrieben, zurück kam \"ok\"", "was bedeutet dieses ok 🧐", "wer auch ewig an nachrichten sitzt",
         "geschrieben, gelöscht, neu geschrieben", "das \"ok\" meiner freundin", "ich analysiere ein ok"],
        ["ist ok gut oder schlecht? 👇", "3 mal korrekturgelesen für das hier…", "kennt ihr das? 👇", "bin ich zu ernst? 🙂"],
        _H + ["#whatsapp"], _T + ["nachricht", "freundin", "whatsapp", "antwort"]),
    4: (["ab montag neues leben (schon wieder) 🙂", "mein sonntagsversprechen", "fitness, salat, 23 uhr… und dann montag",
         "neues leben? nächste woche", "4 mal snooze und pizza 🍕", "montag ist auch nur ein tag"],
        ["wer startet auch immer montags? 👇", "nächsten montag dann wirklich.", "speichern für sonntag 📌", "nur ich? 👇"],
        _H + ["#montag"], _T + ["montag", "motivation", "fitness", "pizza"]),
    5: (["nur kurz milch holen 😭", "supermarkt: rein für milch", "duftkerze ja, milch nein", "was ich statt milch gekauft hab",
         "nochmal zurück zum supermarkt", "ich und einkaufen"],
        ["was kauft ihr immer aus versehen? 👇", "die pflanze war aber wirklich süß.", "kennt ihr das? 👇", "milch ist überbewertet 🙂"],
        _H + ["#einkaufen"], _T + ["supermarkt", "einkaufen", "milch", "geld"]),
    6: (["12 mal am tag die sendung checken 📦", "mein paket ist da!", "…socken", "ein geschenk an mich selbst",
         "wer auch jede sendung verfolgt", "die freude war trotzdem riesig"],
        ["wie oft checkt ihr eure sendung? 👇", "aber es sind schöne socken.", "nur ich? 👇", "speichern 📌"],
        _H + ["#paket"], _T + ["paket", "bestellung", "online", "socken"]),
    7: (["\"bin gleich da\" heißt unter der dusche", "30 minuten im café gewartet", "\"bin unterwegs\" – die wahrheit",
         "wir lügen alle gleich 🙂", "freundinnen und pünktlichkeit", "bin gleich da, versprochen"],
        ["markier deine freundin 👇", "wer ist bei euch immer zu spät? 👇", "wir sind alle gleich.", "kennt ihr das? 👇"],
        _H + ["#freundinnen"], _T + ["freundin", "pünktlich", "café", "warten"]),
    8: (["300 rezepte gespeichert, 0 gekocht", "mein ordner mit gespeichertem", "englisch in 30 tagen (40 mal)",
         "gespeichert ist alles 🙂", "was ich alles mal machen will", "workouts, die ich nie gemacht hab"],
        ["was speichert ihr so? 👇", "irgendwann. bestimmt.", "dieses video auch speichern 📌", "nur ich? 👇"],
        _H + ["#gespeichert"], _T + ["rezepte", "workout", "speichern", "englisch"]),
    9: (["\"isst du auch richtig?\" 🍜", "mama ruft um 23 uhr an", "instant-nudeln sind gemüse", "ich lüge meine mama an 🙂",
         "gemüse, salat, alles dabei", "wenn mama fragt"],
        ["was sagt ihr eurer mama? 👇", "nudeln zählen doch.", "markier deine mama 👇", "kennt ihr das? 👇"],
        _H + ["#mama"], _T + ["mama", "nudeln", "essen", "ausziehen"]),
    10: (["dinge, die jeder macht, aber keiner zugibt", "gib's zu, du machst das auch", "nummer 2 bin ich", "die liste, die jeder kennt",
          "streitgespräche unter der dusche", "welche nummer bist du?"],
         ["welche nummer bist du? 👇", "ertappt 🙂", "was fehlt noch? 👇", "speichern 📌"],
         _H + ["#gibszu"], _T + ["liste", "ehrlich", "dusche", "handy"]),
    11: (["handy bei 1 % = notfall 🔋", "ich renne durch die wohnung", "ich bin das problem", "ladekabel gefunden, kurz gefreut",
          "2 minuten geladen, reicht", "mein akku und ich"],
         ["bei wie viel prozent bekommt ihr panik? 👇", "das sofa war aber näher.", "nur ich? 👇", "kennt ihr das? 👇"],
         _H + ["#akku"], _T + ["handy", "akku", "ladekabel", "sofa"]),
    12: (["unter der dusche gewinne ich jede diskussion", "was ich hätte sagen sollen", "\"äh… ja, du auch\"", "3 tage zu spät schlagfertig",
          "perfekte sätze, falsche zeit", "ich unter der dusche"],
         ["nur ich? 👇", "die beste antwort kommt immer zu spät.", "was hättet ihr gesagt? 👇", "kennt ihr das? 👇"],
         _H + ["#dusche"], _T + ["dusche", "diskussion", "schlagfertig", "peinlich"]),
    13: (["\"guten appetit!\" – \"danke, gleichfalls!\"", "das war vor 4 jahren", "der kellner isst nicht mit 😭", "ich denke immer noch dran",
          "der peinlichste moment im restaurant", "gleichfalls…"],
         ["was war euer moment? 👇", "er isst nicht mit.", "bitte sagt, dass ihr das auch kennt 👇", "nur ich? 👇"],
         _H + ["#peinlich"], _T + ["kellner", "restaurant", "peinlich", "appetit"]),
    14: (["besuch kommt in 10 minuten", "alles unters bett 🙂", "\"bei dir ist es immer so ordentlich!\"", "bitte öffne hier keine tür",
          "aufräumen in 10 minuten", "die kerze rettet alles"],
         ["wo stopft ihr alles hin? 👇", "der schrank geht nicht mehr zu.", "kennt ihr das? 👇", "nur ich? 👇"],
         _H + ["#aufräumen"], _T + ["aufräumen", "besuch", "wohnung", "ordnung"]),
    15: (["der stuhl im schlafzimmer", "noch nie saß jemand drauf", "7 pullis, 3 jeans und mein leben", "jeder hat so einen stuhl",
          "ich räume das irgendwann auf", "mein zweiter kleiderschrank"],
         ["habt ihr auch so einen stuhl? 👇", "er trägt mehr als ich.", "markier jemanden mit stuhl 👇", "kennt ihr das? 👇"],
         _H + ["#wohnen"], _T + ["stuhl", "klamotten", "chaos", "schlafzimmer"]),
    16: (["130 euro pro besuch im fitnessstudio", "seit 14 monaten angemeldet", "3 mal da gewesen 🙂", "ab montag geh ich wieder hin",
          "ich kündige trotzdem nicht", "mein teuerstes hobby"],
         ["wie oft wart ihr dieses jahr? 👇", "montag. versprochen.", "nur ich? 👇", "kennt ihr das? 👇"],
         _H + ["#fitness"], _T + ["fitnessstudio", "vertrag", "sport", "geld"]),
    17: (["wecker um 7, 7:05, 7:10, 7:15…", "um 7:40 wach ich auf 😭", "mit einer socke in der hand", "warum stelle ich 4 wecker",
          "jeden morgen dasselbe", "nur noch 5 minuten"],
         ["wie viele wecker habt ihr? 👇", "keiner davon hat geholfen.", "nur ich? 👇", "kennt ihr das? 👇"],
         _H + ["#morgens"], _T + ["wecker", "morgens", "verschlafen", "socke"]),
    18: (["14 videos am tag in die familiengruppe", "\"handys sind an allem schuld\"", "mit ton. um 6 uhr morgens 🙂", "meine eltern und whatsapp",
          "die familiengruppe ist wach", "eltern vs. handy"],
         ["was schicken eure eltern? 👇", "markier deine eltern 👇", "ich hab sie stummgeschaltet.", "kennt ihr das? 👇"],
         _H + ["#eltern"], _T + ["eltern", "familie", "whatsapp", "handy"]),
    19: (["wenn das treffen abgesagt wird", "\"oh nein, wie schade!\"", "bester tag meines lebens 🙂", "schlafanzug an, sofa",
          "ich nach außen vs. innerlich", "bitte sagt mir öfter ab"],
         ["nur ich? 👇", "markier die, die immer absagt 👇", "das schönste wort: abgesagt.", "kennt ihr das? 👇"],
         _H + ["#introvertiert"], _T + ["freundin", "absagen", "sofa", "introvertiert"]),
    20: (["dinge, die man nur als erwachsener versteht", "die freude über einen neuen schwamm", "um 21 uhr müde und stolz drauf",
          "\"wir müssen uns unbedingt treffen\"", "erwachsen sein in 5 punkten", "welche nummer bist du?"],
         ["welche nummer bist du? 👇", "wann ist das passiert? 🙂", "was fehlt noch? 👇", "speichern 📌"],
         _H + ["#erwachsen"], _T + ["erwachsen", "alltag2", "müde", "geld"]),
}
