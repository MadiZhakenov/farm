#!/usr/bin/env python3
"""Срочные 30 роликов: заголовок, описание и теги для YouTube Shorts — свои у каждого ролика, на языке папки.
→ output/urgent_30/<DE|BR|KR>/<имя ролика>.txt + _youtube_meta.txt (всё по папке одним файлом)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "urgent_30"

META = {
    "KR": {
        "titles": [
            "심심할 때 꼭 들어가 봐야 할 사이트 TOP 5 🌍",
            "시간 순삭되는 웹사이트 5개 (4번이 최애)",
            "지루할 때 몰래 들어가는 신기한 사이트 5곳",
            "아무도 안 알려주는 꿀잼 사이트 TOP 5",
            "이거 알면 심심할 틈이 없음 | 사이트 추천",
            "노래로 게임까지 만들어 주는 사이트?! 신기한 사이트 5",
            "폰으로도 되는 무료 꿀잼 사이트 5개",
            "저장 필수! 심심함 날려주는 사이트 모음",
            "진짜 재밌는 사이트 5개 추천 (4번 미쳤음)",
            "할 거 없을 때 들어가는 사이트 TOP 5 ✨",
        ],
        "descs": [
            "심심할 때 들어가면 시간 가는 줄 모르는 사이트 5개 모아봤어요. 4번이 제일 좋아요!",
            "지루한 날 꼭 저장해 두세요 📌 전부 브라우저에서 바로 돼요.",
            "라디오부터 남의 창밖 풍경까지, 신기한 사이트 모음 🌍",
            "친구한테 몰래 공유하고 싶은 꿀잼 사이트 TOP 5",
            "심심함 해결! 하나씩 들어가 보고 댓글로 최애 알려줘요 👇",
            "노래를 올리면 게임이 되는 사이트까지… 4번 꼭 해보세요 🎮",
            "설치 없이 폰이나 컴퓨터로 바로 들어가는 사이트들이에요.",
            "나중에 심심할 때 보려고 저장 ✨ 몇 번이 제일 좋았어요?",
            "한 번 들어가면 못 나오는 사이트 5곳 추천합니다.",
            "할 거 없을 때 이거 하나면 끝. 4번은 진짜 신기해요!",
        ],
        "tags": ["사이트추천", "웹사이트추천", "꿀잼사이트", "심심할때", "시간때우기", "신기한사이트", "재밌는사이트",
                 "인터넷꿀팁", "drops", "neal.fun", "radio garden", "window swap", "patatap", "shorts"],
        "hashtags": ["#사이트추천", "#꿀잼사이트", "#심심할때", "#shorts"],
    },
    "BR": {
        "titles": [
            "Jeans que eu acho MUITO estilosos pro outono 🍂",
            "8 tipos de jeans que estão em alta nesse outono",
            "Jeans bordado, cargo, com tachas… qual é o seu? 👖",
            "Os jeans mais estilosos da temporada (salva pra depois)",
            "Inspiração de jeans pro outono 2026",
            "Juntei tudo isso no Inspoy 🤍 jeans de outono",
            "Jeans streetwear que eu usaria todo dia",
            "Qual desses jeans você usaria? outono edition",
            "Tendência de jeans: do bordado ao denim cru",
            "Looks com jeans que eu amo pro outono ✨",
        ],
        "descs": [
            "Os jeans que mais me chamam atenção nesse outono. Qual você escolheria? 👇",
            "Do bordado ao cargo: os modelos de jeans que estão em todo lugar agora.",
            "Salva pra montar seus looks de outono depois 📌",
            "Jeans com personalidade pra sair do básico 🍂",
            "Inspiração de looks com jeans pra essa temporada.",
            "Montei as combinações no Inspoy: Outfit Maker, Planner 🤍",
            "Streetwear de outono com jeans que combinam com tudo.",
            "Comenta qual desses jeans você usaria primeiro 👖",
            "Bordado, estampado, wide leg, vintage, patchwork, cargo, tachas e denim cru.",
            "Meus jeans favoritos pro outono — qual é o seu?",
        ],
        "tags": ["jeans", "moda", "look outono", "tendencia jeans", "jeans cargo", "jeans bordado", "jeans wide leg",
                 "streetwear", "outfit", "looks do dia", "moda 2026", "inspoy", "shorts"],
        "hashtags": ["#jeans", "#moda", "#lookdodia", "#shorts"],
    },
    "DE": {
        "titles": [
            "Wer soll eigentlich die Familie versorgen? 👇",
            "2 Jahre ohne Job – und jetzt das",
            "Dieses Gesicht, wenn jemand sagt „das ist sein Job“",
            "Job verloren und trotzdem nicht aufgegeben",
            "Morgen ist mein erster Arbeitstag 😭",
            "Wie ich nach dem Jobverlust wieder Arbeit gefunden habe",
            "Mama, Versorgerin – und endlich wieder im Job",
            "Bewerben ohne Stress? So hab ich's gemacht",
            "Niemand hat an mich geglaubt – morgen starte ich",
            "Ehrlich: so hab ich meinen neuen Job gefunden",
        ],
        "descs": [
            "Ich versorge meine Familie – und hab trotz Jobverlust nicht aufgegeben. Wer soll bei euch versorgen? 👇",
            "Zwei Jahre ohne Job. Jetzt fange ich morgen an.",
            "Für alle, die hören „das ist doch der Job vom Mann“.",
            "Jobverlust ist nicht das Ende. Mein Weg zurück in den Job.",
            "Immer noch dasselbe Gesicht, aber morgen geht's los 😭",
            "Jobs passend zu meiner Erfahrung, Lebenslauf für jede Stelle angepasst – jede Bewerbung bestätige ich selbst.",
            "Für alle Mamas, die ihre Familie versorgen 🤍",
            "So hab ich mich beworben, ohne den Kopf zu verlieren.",
            "Alle sagten „wart doch ab“. Ich hab einfach angefangen.",
            "Mein neuer Job – und wie ich ihn gefunden habe. Fragen in die Kommentare 👇",
        ],
        "tags": ["jobsuche", "bewerbung", "lebenslauf", "neuer job", "arbeit", "karriere", "jobverlust", "mama",
                 "familie", "versorgerin", "globalwork", "shorts"],
        "hashtags": ["#jobsuche", "#bewerbung", "#neuerjob", "#shorts"],
    },
}


def main() -> int:
    for reg, m in META.items():
        vids = sorted((OUT / reg).glob("*.mp4"))
        if len(vids) != len(m["titles"]):
            raise SystemExit(f"{reg}: роликов {len(vids)}, заголовков {len(m['titles'])}")
        allf = []
        for k, v in enumerate(vids):
            tags = m["tags"][k % 3:] + m["tags"][:k % 3]                 # свой порядок тегов у каждого ролика
            hashtags = " ".join(m["hashtags"][(k % 2):] + m["hashtags"][:(k % 2)])
            block = (f"TITLE: {m['titles'][k]}\n\nDESCRIPTION:\n{m['descs'][k]}\n\n{hashtags}\n\n"
                     f"TAGS: {', '.join(tags)}\n")
            (OUT / reg / f"{v.stem}.txt").write_text(block, encoding="utf-8")
            allf.append(f"===== {v.name} =====\n{block}")
        (OUT / reg / "_youtube_meta.txt").write_text("\n".join(allf), encoding="utf-8")
        print(reg, len(vids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
