"""Текстволл ID 1, вторая группа: 16 английских историй ТЗ дословно (строчные, CEO/HR как в ТЗ).
Переносы по смыслу: предложение → строка; длинное делится по запятым, потом перед союзами/предлогами, чтобы куски были ровными;
перед последним предложением — пустая строка (развязка, как в рефе). FIX — ручные правки разбивки."""

import re

NL = chr(10)
MAX = 34

ORIG = [
    "my manager told the quietest guy on our team that he wasn't showing enough leadership. this guy had been fixing everyone's mistakes for almost three years without saying a word. he stayed late, answered weekend calls, and quietly corrected reports before clients saw them. after that meeting he stopped doing anything that wasn't officially assigned to him. within two weeks, three clients complained and our manager had to explain why projects were suddenly falling behind. she asked him what changed. he said nothing. i'm just doing the job you hired me to do. she called that an attitude problem.",
    "my boss presented my entire project to the CEO and forgot to mention my name. i'd spent six weeks building it while she kept telling me it was just a learning exercise. the CEO loved it and asked her to send over the original files. she forwarded the request to me and told me to remove my name from the documents first. i sent the files exactly as they were, including the version history showing every edit i'd made. apparently the CEO had a few questions. my boss hasn't spoken to me since, but suddenly i'm invited to meetings i wasn't allowed into before.",
    "my company made us attend a mandatory training session on a saturday. unpaid, obviously. the topic was work-life balance. the first slide literally said employees need to learn how to set healthy boundaries. so i raised my hand and asked whether we were being paid for attending. the trainer said that wasn't really the point of the workshop. i asked if attending on our day off was an example of a healthy boundary. nobody laughed except the guy from accounting. on monday HR asked me to stop making the company look bad in front of external speakers.",
    "they told my coworker she was easily replaceable after she asked for a raise. she didn't argue. she gave two weeks' notice and spent those two weeks documenting everything she did. management hired two people to replace her. then a third. last week they posted her old position again, this time offering almost double her salary. the funniest part is that she applied using a different email just to see what would happen. they invited her to interview. she declined because her new job pays more and lets her work from home.",
    "my manager gave me a bad performance review because i wasn't available outside office hours. i asked him to show me one deadline i'd missed. he couldn't. one client complaint. none. one unfinished project. nothing. he said performance wasn't just about results, it was about commitment. so i asked why the company measures our hours if the real expectation is to be available all the time. he told me i was being difficult. two days later he asked me to cover his weekend shift because he had family plans. apparently his weekends are different from mine.",
    "my mother-in-law asked for a spare key to our apartment in case of emergencies. i said no because she already has a habit of showing up without calling. last week she told my husband she was worried about me because i apparently spend too much time alone at home. i asked how she would even know that. turns out she'd been checking when my car was parked outside through our neighbor's security camera. my husband said she was just being protective. i asked him if my dad could start monitoring his location every day too. suddenly he understood why it was weird.",
    "my boyfriend asked me to stop wearing the necklace my ex gave me. i said okay because honestly it wasn't worth arguing about. two weeks later i found out he'd been wearing a watch from his ex every single day. when i pointed it out he said it was different because the watch was expensive and actually useful. apparently sentimental gifts are disrespectful unless they tell the time. i asked him to take it off. he said i was being controlling. so now we're having the exact same argument again, except this time he somehow thinks he's the victim.",
    "my sister announced her pregnancy at my wedding reception. not during dinner. not after the speeches. literally while my husband and i were cutting our cake. everyone started screaming and running over to hug her. my photographer even turned around to capture her reaction. i didn't say anything because i didn't want to cause a scene. three months later she asked me to help plan her baby shower. i told her i was busy. she said i was still holding a grudge over one little announcement. apparently the only person allowed to have a special day in our family is her.",
    "my parents asked me to lend my brother $8,000 because he was struggling financially. i said no because he'd already borrowed money from me twice and never paid it back. they called me selfish and said family should help family. a week later my brother posted pictures of his new car. when i asked how he could afford it, he said our parents helped with the down payment. apparently the money they wanted me to lend him wasn't for rent or groceries. it was so he could keep making car payments. my mom still thinks i should apologize for not supporting him.",
    "my fiancé told me his mother wanted to wear white to our wedding. i laughed because i thought he was joking. he wasn't. apparently she'd already bought the dress and didn't want to waste money returning it. i asked him to tell her to choose another color. he said i was making a big deal out of nothing because everyone would know who the bride was. so i sent him a picture of the dress i'd ordered. bright red. he immediately said it would be inappropriate for our wedding. funny how suddenly clothing colors mattered.",
    "my boss rejected my vacation request because the team couldn't function without me. i asked if that meant i was essential enough for a raise. he said no because my position was easily replaceable. so i asked him to pick one. he told me i was being unprofessional. the next morning i submitted my resignation and gave the standard two weeks' notice. suddenly he wanted to discuss retention bonuses, flexible hours, and career growth. apparently i became valuable the exact moment i stopped being available.",
    "my roommate told me i couldn't have guests over because she needed a quiet apartment to study. i respected that for three months. then her boyfriend started staying over every night. he cooked in our kitchen, used our shower, and watched movies until 2am. when i asked if the quiet apartment rule still applied, she said relationships were different from random visitors. last weekend i invited my sister over for dinner. my roommate sent me a four-paragraph message about boundaries while her boyfriend was literally sleeping on our couch.",
    "my best friend asked me to be her maid of honor and then sent me a list of rules. i wasn't allowed to change my hair color, get a tattoo, or lose too much weight before her wedding because she wanted the photos to look consistent. i thought she was joking until she asked another bridesmaid to cover her arm tattoos with makeup. when i said i wasn't comfortable with the rules, she told me being a bridesmaid was a privilege. i told her i'd rather attend as a guest. she said that wasn't an option anymore because i'd already ruined her vision.",
    "my landlord tried charging me $300 because i left the apartment too clean. i'm not kidding. he said the cleaning company he'd booked couldn't find enough work to justify their minimum fee, so he wanted me to cover the cancellation. i sent him pictures of the apartment and the move-out checklist showing everything was spotless. he replied that tenants weren't supposed to hire their own cleaners without permission. i hadn't hired anyone. i'd cleaned it myself. now he's threatening to keep my deposit because i apparently interfered with his cleaning arrangements.",
    "my coworker complained that i was making everyone look bad by finishing my work early. i thought she was joking until she asked me to stop submitting projects before the deadline. apparently our manager had started asking why other people needed more time for similar tasks. i told her i wasn't going to pretend my work took longer than it did. she reported me to HR for creating a competitive environment. HR asked if i could be more mindful of team dynamics. so now i'm apparently the problem because i know how to use spreadsheets.",
    "my boyfriend told me he didn't believe in celebrating anniversaries because relationships shouldn't be about material things. i respected that. no gifts, no fancy dinners, nothing. then his birthday came around and he got upset because i only planned a small dinner at home. he said birthdays were different because they were about making someone feel special. i asked why our anniversary couldn't be about making each other feel special too. he said i was twisting his words. i think what he actually meant was that he doesn't believe in celebrating occasions that aren't about him.",
]

CONJ = {"and", "but", "because", "so", "while", "when", "until", "after", "before", "if", "that", "who", "which", "unless",
        "except", "since", "though", "or"}
PREP = {"to", "for", "with", "without", "about", "from", "on", "in", "at", "into", "through", "of", "by", "over", "outside",
        "every", "using", "including", "showing", "just", "again", "almost", "this", "even", "why", "how", "what", "where"}
FIX: dict[int, list[str]] = {   # ручная разбивка по смыслу (индекс истории с 0)
    0: ["my manager told the quietest guy", "on our team that he wasn't", "showing enough leadership.", "this guy had been fixing",
        "everyone's mistakes", "for almost three years", "without saying a word.", "he stayed late,", "answered weekend calls,",
        "and quietly corrected reports", "before clients saw them.", "after that meeting", "he stopped doing anything",
        "that wasn't officially", "assigned to him.", "within two weeks,", "three clients complained", "and our manager had to explain",
        "why projects were", "suddenly falling behind.", "she asked him what changed.", "he said nothing.", "i'm just doing the job",
        "you hired me to do.", "", "she called that an attitude problem."],
    1: ["my boss presented", "my entire project to the CEO", "and forgot to mention my name.", "i'd spent six weeks building it",
        "while she kept telling me", "it was just a learning exercise.", "the CEO loved it", "and asked her to send over",
        "the original files.", "she forwarded the request to me", "and told me to remove my name", "from the documents first.",
        "i sent the files", "exactly as they were,", "including the version history", "showing every edit i'd made.",
        "apparently the CEO", "had a few questions.", "", "my boss hasn't spoken to me since,", "but suddenly i'm invited",
        "to meetings", "i wasn't allowed into before."],
    2: ["my company made us attend", "a mandatory training session", "on a saturday.", "unpaid, obviously.",
        "the topic was work-life balance.", "the first slide literally said", "employees need to learn",
        "how to set healthy boundaries.", "so i raised my hand and asked", "whether we were being paid", "for attending.",
        "the trainer said", "that wasn't really the point", "of the workshop.", "i asked if attending", "on our day off was an example",
        "of a healthy boundary.", "nobody laughed", "except the guy from accounting.", "", "on monday HR asked me",
        "to stop making the company", "look bad in front", "of external speakers."],
    3: ["they told my coworker", "she was easily replaceable", "after she asked for a raise.", "she didn't argue.",
        "she gave two weeks' notice", "and spent those two weeks", "documenting everything she did.", "management hired two people",
        "to replace her.", "then a third.", "last week they posted", "her old position again,", "this time offering",
        "almost double her salary.", "the funniest part is", "that she applied", "using a different email",
        "just to see what would happen.", "they invited her to interview.", "", "she declined", "because her new job pays more",
        "and lets her work from home."],
    4: ["my manager gave me", "a bad performance review", "because i wasn't available", "outside office hours.",
        "i asked him to show me", "one deadline i'd missed.", "he couldn't.", "one client complaint. none.",
        "one unfinished project. nothing.", "he said performance", "wasn't just about results,", "it was about commitment.",
        "so i asked why the company", "measures our hours", "if the real expectation", "is to be available all the time.",
        "he told me i was being difficult.", "two days later he asked me", "to cover his weekend shift", "because he had family plans.",
        "", "apparently his weekends", "are different from mine."],
    5: ["my mother-in-law asked", "for a spare key to our apartment", "in case of emergencies.", "i said no because she already",
        "has a habit of showing up", "without calling.", "last week she told my husband", "she was worried about me",
        "because i apparently spend", "too much time alone at home.", "i asked how she would", "even know that.",
        "turns out she'd been checking", "when my car was parked outside", "through our neighbor's", "security camera.",
        "my husband said", "she was just being protective.", "i asked him if my dad", "could start monitoring",
        "his location every day too.", "", "suddenly he understood", "why it was weird."],
    6: ["my boyfriend asked me", "to stop wearing the necklace", "my ex gave me.", "i said okay because honestly",
        "it wasn't worth arguing about.", "two weeks later i found out", "he'd been wearing a watch", "from his ex every single day.",
        "when i pointed it out", "he said it was different", "because the watch was expensive", "and actually useful.",
        "apparently sentimental gifts", "are disrespectful", "unless they tell the time.", "i asked him to take it off.",
        "he said i was being controlling.", "", "so now we're having", "the exact same argument again,", "except this time",
        "he somehow thinks he's the victim."],
    7: ["my sister announced her pregnancy", "at my wedding reception.", "not during dinner.", "not after the speeches.",
        "literally while my husband and i", "were cutting our cake.", "everyone started screaming", "and running over to hug her.",
        "my photographer even turned around", "to capture her reaction.", "i didn't say anything", "because i didn't want",
        "to cause a scene.", "three months later she asked me", "to help plan her baby shower.", "i told her i was busy.",
        "she said i was still", "holding a grudge", "over one little announcement.", "", "apparently the only person",
        "allowed to have a special day", "in our family is her."],
    8: ["my parents asked me", "to lend my brother $8,000", "because he was", "struggling financially.",
        "i said no because he'd already", "borrowed money from me twice", "and never paid it back.", "they called me selfish",
        "and said family", "should help family.", "a week later my brother", "posted pictures of his new car.", "when i asked",
        "how he could afford it,", "he said our parents helped", "with the down payment.", "apparently the money",
        "they wanted me to lend him", "wasn't for rent or groceries.", "it was so he could keep", "making car payments.", "",
        "my mom still thinks", "i should apologize", "for not supporting him."],
    9: ["my fiancé told me his mother", "wanted to wear white", "to our wedding.", "i laughed because",
        "i thought he was joking.", "he wasn't.", "apparently she'd already", "bought the dress", "and didn't want to waste money",
        "returning it.", "i asked him to tell her", "to choose another color.", "he said i was making",
        "a big deal out of nothing", "because everyone would know", "who the bride was.", "so i sent him a picture",
        "of the dress i'd ordered.", "bright red.", "he immediately said", "it would be inappropriate", "for our wedding.", "",
        "funny how suddenly", "clothing colors mattered."],
    10: ["my boss rejected", "my vacation request", "because the team", "couldn't function without me.", "i asked if that meant",
         "i was essential enough", "for a raise.", "he said no because my position", "was easily replaceable.",
         "so i asked him to pick one.", "he told me", "i was being unprofessional.", "the next morning",
         "i submitted my resignation", "and gave the standard", "two weeks' notice.", "suddenly he wanted to discuss",
         "retention bonuses,", "flexible hours, and career growth.", "", "apparently i became valuable", "the exact moment",
         "i stopped being available."],
    11: ["my roommate told me", "i couldn't have guests over", "because she needed", "a quiet apartment to study.",
         "i respected that for three months.", "then her boyfriend started", "staying over every night.", "he cooked in our kitchen,",
         "used our shower,", "and watched movies until 2am.", "when i asked", "if the quiet apartment rule", "still applied,",
         "she said relationships", "were different", "from random visitors.", "last weekend i invited my sister", "over for dinner.",
         "", "my roommate sent me", "a four-paragraph message", "about boundaries", "while her boyfriend was literally",
         "sleeping on our couch."],
    12: ["my best friend asked me", "to be her maid of honor", "and then sent me a list of rules.", "i wasn't allowed",
         "to change my hair color,", "get a tattoo,", "or lose too much weight", "before her wedding", "because she wanted the photos",
         "to look consistent.", "i thought she was joking", "until she asked another bridesmaid", "to cover her arm tattoos",
         "with makeup.", "when i said i wasn't comfortable", "with the rules, she told me", "being a bridesmaid", "was a privilege.",
         "i told her i'd rather", "attend as a guest.", "", "she said that wasn't", "an option anymore", "because i'd already",
         "ruined her vision."],
    13: ["my landlord tried charging me $300", "because i left the apartment", "too clean.", "i'm not kidding.",
         "he said the cleaning company", "he'd booked", "couldn't find enough work", "to justify their minimum fee,",
         "so he wanted me", "to cover the cancellation.", "i sent him pictures", "of the apartment", "and the move-out checklist",
         "showing everything was spotless.", "he replied that tenants", "weren't supposed to hire", "their own cleaners",
         "without permission.", "i hadn't hired anyone.", "i'd cleaned it myself.", "", "now he's threatening", "to keep my deposit",
         "because i apparently interfered", "with his cleaning arrangements."],
    14: ["my coworker complained", "that i was making", "everyone look bad", "by finishing my work early.",
         "i thought she was joking", "until she asked me to stop", "submitting projects", "before the deadline.",
         "apparently our manager", "had started asking", "why other people needed more time", "for similar tasks.", "i told her",
         "i wasn't going to pretend", "my work took longer than it did.", "she reported me to HR", "for creating",
         "a competitive environment.", "HR asked if i could be more mindful", "of team dynamics.", "",
         "so now i'm apparently the problem", "because i know how", "to use spreadsheets."],
    15: ["my boyfriend told me", "he didn't believe", "in celebrating anniversaries", "because relationships",
         "shouldn't be about material things.", "i respected that.", "no gifts, no fancy dinners,", "nothing.",
         "then his birthday came around", "and he got upset", "because i only planned", "a small dinner at home.",
         "he said birthdays were different", "because they were about", "making someone feel special.", "i asked why our anniversary",
         "couldn't be about", "making each other", "feel special too.", "he said i was twisting his words.", "",
         "i think what he actually meant", "was that he doesn't believe", "in celebrating occasions", "that aren't about him."],
}


def split_sentence(s: str) -> list[str]:
    if len(s) <= MAX:
        return [s]
    words = s.split(" ")
    best = None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        if len(a) < 9 or len(b) < 9:
            continue
        prev, nxt = words[i - 1], words[i].strip("'\"").lower()
        if prev.endswith((",", ";", ":")):
            pen = 0
        elif nxt in CONJ:
            pen = 6
        elif nxt in PREP:
            pen = 12
        else:
            pen = 22
        score = max(len(a), len(b)) + pen + (40 if max(len(a), len(b)) > MAX + 8 else 0)
        if best is None or score < best[0]:
            best = (score, a, b)
    if best is None:
        return [s]
    return split_sentence(best[1]) + split_sentence(best[2])


def lines_for(k: int) -> list[str]:
    if k in FIX:
        return FIX[k]
    sents = re.findall(r"[^.?!]+[.?!]+(?=\s|$)", ORIG[k])
    sents = [x.strip() for x in sents]
    assert " ".join(sents) == ORIG[k], k
    out = []
    for j, s in enumerate(sents):
        if j == len(sents) - 1:
            out.append("")
        out += split_sentence(s)
    return out


LINES = {k + 1: lines_for(k) for k in range(len(ORIG))}
TEXTS = {n: NL.join(v) for n, v in LINES.items()}
for _n, _v in LINES.items():
    assert " ".join(x for x in _v if x) == ORIG[_n - 1], f"история {_n} не совпадает с ТЗ"
