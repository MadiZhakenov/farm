# Аудит Shorts: @Endlesslove025

Источник: `https://www.youtube.com/@Endlesslove025/shorts`. Канал Endless Love, около 11.7 млн подписчиков на момент сбора. Дата прогона: 2026-09-14 05:46 UTC.

Сбор без API-ключа. `scrapetube` на вкладке Shorts отдаёт только `videoId`; чип popular на этой вкладке падает (нет `feedFilterChipBarRenderer`). Заголовки и приблизительные просмотры сетки взяты плоским плейлистом `yt-dlp` по последним 600–800 Shorts. В выборку вошли 180 самых новых и самые просматриваемые из этого окна, без дублей, потолок 300. Точные `view_count`, `duration`, `published_time` и описание ролика — полный extract `yt-dlp`, файл не скачивается. «Популярные» здесь — верх по просмотрам в окне, не отдельный чип YouTube.

Виральность ниже — это `views / age_days`, не сырые просмотры. Сырой топ смещён к старым роликам. Все сравнения описательные: канал сам выбирает, что выкладывать, так что разница топ-5% и массы не есть причинность заголовка или секунд.

## Общая сводка

- В выборке после фильтра ≤180 с: **300** роликов (собрано листингом 300, ошибки обогащения с откатом на листинг: 12).
- С точной датой: 288. С длительностью: 288. С текстом описания: 10.
- Медиана просмотров: **119 223**. Среднее: 1 437 268. Медиана просмотров/день: **7 582**.
- Хронометраж: медиана **17 с**, среднее 18.8 с, IQR 13 с – 24 с.
- Окно публикаций: 2026-08-26 — 2026-09-14 (18 суток, 180 роликов с датой).
- Частота считается только по свежему срезу (newest/both, n=180), без подмешанных старых хитов, иначе паузы раздуваются. **9.95 ролика в сутки** по окну (включая дни без постов). В дни, когда постит: медиана 7 ролика, p90 16. Активных дней: 20.
- По неделям: медиана 53, среднее 45.0. Медианная пауза между роликами: 1.0 ч.

## Золотой стандарт хронометража

Это диапазон, где в этой выборке медиана просмотров/день максимальна при достаточном n. Это не порог YouTube и не гарантия следующего ролика.

- Устойчивое окно 8 секунд (n≥40, максимальная медиана views/day): **20–28 с** (медиана длины 23 с, n=62, медиана просмотров 396 060, медиана/день 13 172).
- Более узкий пик при n≥12: 34–42 с (n=13, медиана/день 16 409). n слишком мало, чтобы объявлять это стандартом.
- Грубый бин с тем же критерием: **21–31 с** (n=73, медиана просмотров 343 653, медиана/день 8 560).
- Топ-5% по views/day: медиана длины 21 с (IQR 16.5 с–24 с). Остальные: медиана 16 с.

Медиана views/day по бинам:

```
0–15 с     n=99   ███████████████████ 6 795 /день
15–21 с    n=86   ███████████████████████ 8 263 /день
21–31 с    n=73   ████████████████████████ 8 560 /день
31–45 с    n=27   █████████████████████ 7 414 /день
45–60 с    n=3    ██ 852 /день
```

## Аномалии: топ-5% против остальной массы

Порог топ-5%: 97 575 просмотров/день. n топа = 15, n остатка = 273.

| | Топ-5% | Остальные |
| --- | ---: | ---: |
| Медиана просмотров | 2 920 243 | 88 165 |
| Медиана просмотров/день | 145 753 | 7 064 |
| Медиана длины | 21 с | 16 с |
| Медиана слов в заголовке | 10.0 | 9.0 |
| Медиана символов заголовка | 54 | 53 |
| Доля с эмодзи | 100% | 97% |
| Доля с вопросом | 0% | 4% |
| Доля со словом КАПСОМ | 13% | 6% |
| Медиана возраста, дни | 17.1 | 15.0 |

Слова, которые чаще встречаются в заголовках топа, чем в остатке (lift). Это не «секретные триггеры», а относительная частота при маленьком n топа.

| Слово | Доля в топе | Доля в остатке | Lift |
| --- | ---: | ---: | ---: |
| woman | 13% | 0% | 28.54 |
| year | 13% | 1% | 17.12 |
| old | 13% | 1% | 17.12 |
| found | 13% | 1% | 12.23 |

Самые быстрые по views/day:

- This is how metal detectorists find gold using a metal detector device 😍 — 24 244 435 просмотров, 758 366/день, 25 с. https://www.youtube.com/shorts/z3FjecFvGVs
- Opening a 2,500-Year-Old Mummy 😍🤌 — 532 250 просмотров, 383 951/день, 21 с. https://www.youtube.com/shorts/vWEYvyxIb7g
- Couple Takes KIDS' Toy Porsche For A Real Joyride Down The Stairs Dog's Reaction Is Priceless 🥹❤️ — 2 833 395 просмотров, 375 138/день, 22 с. https://www.youtube.com/shorts/7r5J84JnvYQ
- When Mom And Dad Are Gen Z Parents Of The Year😂❤️ — 2 920 243 просмотров, 322 742/день, 12 с. https://www.youtube.com/shorts/qdUuTSWJ52I
- Now see how these operators demonstrate their skills 😍 — 23 284 339 просмотров, 241 469/день, 18 с. https://www.youtube.com/shorts/pg72_9GFAms
- I was today years old when I found this out! 👋 — 19 388 947 просмотров, 181 328/день, 14 с. https://www.youtube.com/shorts/yiRDsxmPCJU
- Wives are wives, whether human or not 🥹❤️ — 1 847 872 просмотров, 177 210/день, 20 с. https://www.youtube.com/shorts/5u5MuOdWLEI
- A Woman Offered Food To A Peacock, And Peacock Thanked Her In The Most Beautiful Way I WATCH ⌚️ — 1 501 646 просмотров, 145 753/день, 22 с. https://www.youtube.com/shorts/yBzlDHQVoLk

## Заголовки

- Среднее слов: **9.0**, медиана 9.0.
- Среднее символов: **53.6**, медиана 54.
- Доля с эмодзи: **97%**. С вопросом: **4%**. Со словом КАПСОМ: **6%**. Средняя доля заглавных букв: 12%.

Топ-20 слов в заголовках (без стоп-слов):

most (13), one (12), bro (12), like (10), baby (10), never (9), their (7), water (7), physics (7), funny (6), real (6), own (6), every (6), man (6), ever (6), looks (6), even (6), dog (6), life (6), mother (6).

Словари триггеров (фиксированные английские лексемы, доля заголовков с хотя бы одним попаданием):

- emotional: 14 / 300 (5%)
- curiosity: 63 / 300 (21%)
- animals: 30 / 300 (10%)
- empathy: 39 / 300 (13%)

Хештеги в заголовке и описании:

#motivation (7), #discipline (7), #funny (6), #love (1), #subscribe (1), #secret (1), #nokia (1), #respect (1), #shortsfeed (1), #short (1).

### Топ-5 формул заголовков

Формула = первые содержательные токены заголовка, числа схлопнуты в `#`. В список входят только шаблоны с n≥3, сортировка по медиане views/day.

Повторяющихся шаблонов с n≥3 нет. Ниже — структурные признаки вместо формул.

Структурные признаки, ранжированные по медиане views/day:

| Признак | n | Доля | Медиана/день | Lift к остальным |
| --- | ---: | ---: | ---: | ---: |
| хештег в заголовке | 11 | 4% | 15 264 | 2.03 |
| вопрос в заголовке | 10 | 3% | 14 960 | 2.01 |
| слово КАПСОМ (≥3 буквы) | 18 | 6% | 8 095 | 1.09 |
| эмодзи в заголовке | 280 | 97% | 7 517 | 0.78 |
| заголовок ≤ 4 слов | 27 | 9% | 7 064 | 0.88 |
| заголовок ≥ 8 слов | 178 | 62% | 6 809 | 0.66 |
| число в заголовке | 28 | 10% | 5 103 | 0.64 |

## Юридический щит

Это текст, который канал реально вставляет в описание. Дисклеймер не создаёт fair use и не останавливает Content ID или страйк. Копировать его как защиту бессмысленно.

Текст вкладки About канала (стабильный шаблон, не обязательно совпадает с описанием каждого Short):

```
💖Welcome to Endless Love,
a place where emotions find a home and every moment tells a story.

Here, we bring you the most heartfelt and captivating Shorts from around the world — moments that speak to the soul and remind us how beautiful love can be in all its forms.

---

Every video is shared to inspire love, positivity, and meaningful moments in your day.

🌟 Our Purpose

Welcome to a world of entertainment, creativity, and fresh content! We bring you engaging videos, music, fun moments, and unique entertainment experiences. Our goal is to keep you entertained with creative and original content made for our audience.

Original Content • Entertainment • Creativity • 
Fun

Copyright ©️Info.
Successfrom2024@gmail.com

Want to submit your clips? 🎬
📩 Send them to: successfrom2024@gmail.com
```

Непустых описаний: 10 (3% выборки). Точный повтор одного и того же текста: 5 роликов.

Строки с маркерами disclaimer / copyright / contact:

- (7) Copyright Disclaimer Under Section 107 of the Copyright Act 1976, allowance is made for "fair use" for purposes such as criticism, comment, news reporting, teaching, scholarship, education, and research.
- (3) 📹 Credits to the original creators

Строки, которые повторяются минимум в 35% непустых описаний:

- (7) Copyright Disclaimer Under Section 107 of the Copyright Act 1976, allowance is made for "fair use" for purposes such as criticism, comment, news reporting, teaching, scholarship, education, and research.
- (7) #motivation #discipline
- (6) all in one place. New Shorts uploaded regularly to keep your feed entertaining!
- (6) 😂 Funny Clips
- (6) 🔥 Viral Moments
- (6) 😲 Unbelievable Videos
- (6) ❤️ Wholesome Content
- (3) 🌙 “Every clip tells a story.”
- (3) 📹 Credits to the original creators
- (3) 🎬 Re-edited with creativity & respect

Самый частый полный текст описания:

```
Copyright Disclaimer Under Section 107 of the Copyright Act 1976, allowance is made for "fair use" for purposes such as criticism, comment, news reporting, teaching, scholarship, education, and research.
#motivation #discipline

all in one place. New Shorts uploaded regularly to keep your feed entertaining!

😂 Funny Clips
🔥 Viral Moments
😲 Unbelievable Videos
❤️ Wholesome Content
```

## Пошаговый рецепт для конвейера

Рецепт повторяет наблюдаемое распределение этого канала. Он не переносится на другую нишу как формула виральности.

1. Держать хронометраж в окне **20–28 с**, если цель — попасть в бин с максимальной медианой views/day на этой выборке. Вне окна бин либо реже, либо медленнее.
2. Частота этого канала: около 9.95 ролика в сутки по окну, медиана 53 в неделю, пауза 1.0 ч. Конвейер, который постит на порядок реже, не повторяет их режим набора выборки.
3. Заголовок под их медиану: около 9.0 слов и 54 символов. Эмодзи сейчас у 97% заголовков, вопрос у 4%, капслок-слово у 6%. Копировать признак имеет смысл только если его lift в таблице выше ≥1.2 и n≥8.
4. Темы в частотном хвосте заголовков: most, one, bro, like, baby, never, their, water. Это темы канала, не универсальные хуки.
5. Описание: если у себя нет юридической причины для того же текста, не вставлять их дисклеймер «для защиты от страйков». Он не является щитом. Имеет смысл повторить только фактические поля, которые у них стабильны (email, кредит источника), и то как контакт, не как оборону.
6. Не оптимизировать сырые просмотры. В своей аналитике считать views/age_days и минуты на показ в разрезе Suggested/Browse отдельно: сырой топ этого канала тоже смещён возрастом (медиана возраста топа 17.1 дней против 15.0 у остальных).

Сырые строки: `endlesslove_data.csv`. Промежуточные ответы yt-dlp: `endlesslove_checkpoint.jsonl`.
