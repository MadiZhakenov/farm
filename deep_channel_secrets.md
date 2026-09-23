# Скрытые слои: топ-30 Shorts @Endlesslove025

Выборка: 30 роликов с максимальным `views_per_day` из `endlesslove_data.csv`. Прогон: 2026-09-14 06:47 UTC. Файлы роликов не скачивались. Интенсивность Most Replayed — относительная шкала 0–1 внутри ролика, не число пересмотров.

## Анализ сценариев

Автосубтитры с хотя бы 8 словами после снятия `[music]`: **8 / 30**. Субтитры выключены: 16. Пустых после очистки: 6.

Это не сценарий диктора. Там, где текст есть, автосубтитры совпадают с текстом фонового трека (Skyfall, It's Raining Men, Love Story, Play with Fire). Закадровой структуры «хук → конфликт → петля» в топ-30 нет. Ниже — три повторяемых текстовых слоя, которые реально встречаются: название трека и его распознанный припев.

По роликам с распознанным текстом: медиана слов **32**, медиана темпа **1.44 слов/с** на медиане длины 23 с. Темп ниже разговорного (~2.5 слов/с): это темп песни, не закадра.

### Шаблон 1: трек `Love Story (Version Orchestrale)` (n=2)

- Медиана слов: 36. Медиана темпа: 1.94 слов/с.
- Первая фраза: voulez pas tout a je serai musique rich je t'offrirai tout mon
- Последняя фраза: je t'offrirai mon dernier souffle de musique chant vie dans ma story
- Пример (A Woman Offered Food To A Peacock, And Peacock Thanked Her In The Most Beautiful Way I WATCH ⌚️): voulez pas tout ça je serai [musique] riché je t'offrirai tout mon or et si tu t'en fiches je t'attendrai sur le port et si tu [musique] mignores, je t'offrirai mon dernier souffle de [musique][chant] vie dans ma story.

### Шаблон 2: трек `It's Raining Men (Single Version)` (n=1)

- Медиана слов: 23. Медиана темпа: 1.28 слов/с.
- Первая фраза: It's raining men.
- Последняя фраза: I'm going to let myself get absolutely soaking wet.
- Пример (Now see how these operators demonstrate their skills 😍): It's raining men. Hallelujah, it's raining men. And men. I'm going to go out. I'm going to let myself get absolutely soaking wet.

### Шаблон 3: трек `Headlights (feat. KIDDO)` (n=1)

- Медиана слов: 48. Медиана темпа: 1.37 слов/с.
- Первая фраза: Full of all of them, jealous.
- Последняя фраза: Let me out, let me Baby, I'm all Play by Running in Let me out Baby, I'm all about Play by Play by Play by Play by
- Пример (This track is so Sticky; it can literally tear your Shoe apart 😍): Full of all of them, jealous. Baby, I'm all about her. Play by play by play. Running in, running in play. Let me out, let me Baby, I'm all Play by Running in Let me out Baby, I'm all about Play by Play by Play by Play by

## Анатомия пика пересмотра

Маркеры есть у **14 / 30**. У остальных Most Replayed в player-response нет (часто так у свежих Shorts). Форма графика у 14 / 14 роликов с данными: максимум value=1.0 в первом бине 0.0–0.25 с, дальше почти монотонный спад, внутренних восходящих горбов нет.

Сырой максимум — **0.1 с (0.5% длины)**. Это не момент события внутри клипа. Так выглядит петля Shorts: повтор начинается с нуля, и первый кадр становится самым пересматриваемым. Роликов с пиком в последних 25%: **0**.

Практическая секунда удержания внимания: момент, когда интенсивность падает ниже 0.5. Медиана по роликам с графиком: **1.2 с**. После неё график уже хвост, не горб.

| Доля длины | Роликов |
| --- | ---: |
| 0–20% | 14 |
| 20–40% | 0 |
| 40–60% | 0 |
| 60–80% | 0 |
| 80–100% | 0 |

Пять самых острых пиков (value — доля от максимума графика этого ролика, не от канала):

- This is how metal detectorists find gold using a metal detector device 😍: пик на 0.1 с (0% ролика, value 1.00).
- Now see how these operators demonstrate their skills 😍: пик на 0.1 с (0% ролика, value 1.00).
- I was today years old when I found this out! 👋: пик на 0.1 с (1% ролика, value 1.00).
- This track is so Sticky; it can literally tear your Shoe apart 😍: пик на 0.2 с (0% ролика, value 1.00).
- ￼ A person living in a tower in the middle of the sea 🌊: пик на 0.1 с (0% ролика, value 1.00).

## Звуки и треки

Частота `soundAttributionTitle` на этих 30. «Original Sound» — звук самого ролика, не трек из библиотеки. Отдельного artist/sound_id YouTube в соседнем блоке шапки Shorts почти не отдаёт.

| Трек / звук | Роликов |
| --- | ---: |
| Original Sound | 9 |
| Pretty Little Baby | 3 |
| Golden Brown | 2 |
| Love Story (Version Orchestrale) | 2 |
| Skyfall | 2 |
| blue | 1 |
| It's Raining Men (Single Version) | 1 |
| Lux Aeterna | 1 |
| Beanie | 1 |
| Headlights (feat. KIDDO) | 1 |
| Punisher | 1 |
| Play with Fire (feat. Yacht Money) | 1 |
| Любов, як осінь | 1 |
| SLAVA FUNK! (Slowed) | 1 |
| Love Story | 1 |

## Топ-10: пик, текст, поиск оригинала по кадру

Кадр лежит в `keyframes/{video_id}.jpg`. Ссылка поиска указывает на публичный URL превью YouTube, который Lens и Яндекс могут забрать без локального файла. Совпадение кадра не доказывает происхождение и не даёт права перезалить ролик.

| Название | Секунда пика | Полный текст сценария | Поиск оригинала по кадру |
| --- | --- | --- | --- |
| This is how metal detectorists find gold using a metal detector device 😍 | 0.1 с (старт петли, >0.5 до 1.2 с) | нет английской речи (disabled) | [Lens](https://lens.google.com/uploadbyurl?url=https%3A%2F%2Fi.ytimg.com%2Fvi%2Fz3FjecFvGVs%2Fmaxresdefault.jpg) · [Яндекс](https://yandex.com/images/search?rpt=imageview&url=https%3A%2F%2Fi.ytimg.com%2Fvi%2Fz3FjecFvGVs%2Fmaxresdefault.jpg) |
| Opening a 2,500-Year-Old Mummy 😍🤌 | н/д | нет английской речи (disabled) | [Lens](https://lens.google.com/uploadbyurl?url=https%3A%2F%2Fi.ytimg.com%2Fvi%2FvWEYvyxIb7g%2Fmaxresdefault.jpg) · [Яндекс](https://yandex.com/images/search?rpt=imageview&url=https%3A%2F%2Fi.ytimg.com%2Fvi%2FvWEYvyxIb7g%2Fmaxresdefault.jpg) |
| Couple Takes KIDS' Toy Porsche For A Real Joyride Down The Stairs Dog's Reactio… | н/д | нет английской речи (disabled) | [Lens](https://lens.google.com/uploadbyurl?url=https%3A%2F%2Fi.ytimg.com%2Fvi%2F7r5J84JnvYQ%2Fmaxresdefault.jpg) · [Яндекс](https://yandex.com/images/search?rpt=imageview&url=https%3A%2F%2Fi.ytimg.com%2Fvi%2F7r5J84JnvYQ%2Fmaxresdefault.jpg) |
| When Mom And Dad Are Gen Z Parents Of The Year😂❤️ | н/д | нет английской речи (disabled) | [Lens](https://lens.google.com/uploadbyurl?url=https%3A%2F%2Fi.ytimg.com%2Fvi%2FqdUuTSWJ52I%2Fmaxresdefault.jpg) · [Яндекс](https://yandex.com/images/search?rpt=imageview&url=https%3A%2F%2Fi.ytimg.com%2Fvi%2FqdUuTSWJ52I%2Fmaxresdefault.jpg) |
| Now see how these operators demonstrate their skills 😍 | 0.1 с (старт петли, >0.5 до 1.1 с) | It's raining men. Hallelujah, it's raining men. And men. I'm going to go out. I'm going to let myself get absolutely soaking wet. | [Lens](https://lens.google.com/uploadbyurl?url=https%3A%2F%2Fi.ytimg.com%2Fvi%2Fpg72_9GFAms%2Fmaxresdefault.jpg) · [Яндекс](https://yandex.com/images/search?rpt=imageview&url=https%3A%2F%2Fi.ytimg.com%2Fvi%2Fpg72_9GFAms%2Fmaxresdefault.jpg) |
| I was today years old when I found this out! 👋 | 0.1 с (старт петли, >0.5 до 1.1 с) | нет английской речи (disabled) | [Lens](https://lens.google.com/uploadbyurl?url=https%3A%2F%2Fi.ytimg.com%2Fvi%2FyiRDsxmPCJU%2Fmaxresdefault.jpg) · [Яндекс](https://yandex.com/images/search?rpt=imageview&url=https%3A%2F%2Fi.ytimg.com%2Fvi%2FyiRDsxmPCJU%2Fmaxresdefault.jpg) |
| Wives are wives, whether human or not 🥹❤️ | н/д | [musik] [musik] Ah. [musik] H | [Lens](https://lens.google.com/uploadbyurl?url=https%3A%2F%2Fi.ytimg.com%2Fvi%2F5u5MuOdWLEI%2Fmaxresdefault.jpg) · [Яндекс](https://yandex.com/images/search?rpt=imageview&url=https%3A%2F%2Fi.ytimg.com%2Fvi%2F5u5MuOdWLEI%2Fmaxresdefault.jpg) |
| A Woman Offered Food To A Peacock, And Peacock Thanked Her In The Most Beautifu… | н/д | voulez pas tout ça je serai [musique] riché je t'offrirai tout mon or et si tu t'en fiches je t'attendrai sur le port et si tu [musique] mignores, je t'offrirai mon dernier souffle de [musique][chant] vie dans ma story. | [Lens](https://lens.google.com/uploadbyurl?url=https%3A%2F%2Fi.ytimg.com%2Fvi%2FyBzlDHQVoLk%2Fmaxresdefault.jpg) · [Яндекс](https://yandex.com/images/search?rpt=imageview&url=https%3A%2F%2Fi.ytimg.com%2Fvi%2FyBzlDHQVoLk%2Fmaxresdefault.jpg) |
| Snowy owl gently approaches man inside frozen shelter ❤️😍 | н/д | нет английской речи (disabled) | [Lens](https://lens.google.com/uploadbyurl?url=https%3A%2F%2Fi.ytimg.com%2Fvi%2FfxRo-G7b-4I%2Fmaxresdefault.jpg) · [Яндекс](https://yandex.com/images/search?rpt=imageview&url=https%3A%2F%2Fi.ytimg.com%2Fvi%2FfxRo-G7b-4I%2Fmaxresdefault.jpg) |
| This track is so Sticky; it can literally tear your Shoe apart 😍 | 0.2 с (старт петли, >0.5 до 1.8 с) | Full of all of them, jealous. Baby, I'm all about her. Play by play by play. Running in, running in play. Let me out, let me Baby, I'm all Play by Running in Let me out Baby, I'm all about Play by Play by Play by Play by | [Lens](https://lens.google.com/uploadbyurl?url=https%3A%2F%2Fi.ytimg.com%2Fvi%2FCrcKiHP3CvI%2Fmaxresdefault.jpg) · [Яндекс](https://yandex.com/images/search?rpt=imageview&url=https%3A%2F%2Fi.ytimg.com%2Fvi%2FCrcKiHP3CvI%2Fmaxresdefault.jpg) |

Сырые маркеры, cues и ошибки: `deep_intelligence.json`.
