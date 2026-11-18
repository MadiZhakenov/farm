# Ночная очередь 16→17.11.2026 (юзер спит, вопросов не задавать, тесты проверять самому)

Порядок строго по очереди. Каждый шаг: статус здесь + проверка, что следующий шаг реально пошёл.
Правила: CLAUDE.md (безопасные зоны, видеокарта: cuvid→память→NVENC, bad_frames + покадровая сверка, gpu_slot,
метаданные G.CLEAN / strip_jpeg_meta, ID 1 в именах), не убивать чужие процессы (только своё дерево по PID),
torch-расчёт плана не рядом с полной видеопамятью (GPU_VRAM_MAX_MB=5800, --jobs 3).

## 1. OneState «bro laughed SO HARD his mic glitched» (ID 1) — 200 TT + 200 YT
- build_onestate_mic.py, лог output/_work/onestate_mic/batch2.log → output/onestate_mic_TT_200, _YT_200.
- Перезапуск 22:31: 8 сборок разом забивали видеопамять → замена брака висла на torch; теперь --jobs 3, 5800 МБ.
- В конце скрипт сам запускает check_uniq_allframes (все пары, каждый кадр). Нужно: худшая пара ≤ 1 %, 0 с 1312_300.
- СТАТУС: ГОТОВО 23:35. 400 роликов, каждый кадр всех 79 800 пар: 0 пар с общими кадрами (худшая 0 %), с 1312_300 — 0.

## 2. Drops «whimsical websites to train your ear» (ID 1) — 200 каруселей TT + 200 видео YT
- Наш удачный концепт: аккаунт @confdsbpkhn (видео 7703553492522110239) — посмотреть, какой дизайн зашёл, и делать в нём.
- Новый реф: @cowsites.net/photo/7689935219767495958 (скачать слайды + звук).
- Контент Drops ТОЛЬКО из Dropbox: https://www.dropbox.com/scl/fo/wnmsp432pj36ydkv31cy0/AP-WJdsK5CgNU-lrDTvyaCY?rlkey=kmeorkl385rm8qlncb558mv51&st=lekxwmzy&dl=1
- Слайды (тексты дословно):
  1. обложка «whimsical websites to train your ear» + маленькие картинки про музыку (ноутбук, гитара, наушники…)
  2. https://musicmap.info — «Interactive genealogy of music. It shows how genres emerged, which movements influenced each other, and how musical styles developed»
  3. https://drops.game/ — «An interactive music game builder that turns your song into a small video game. It creates a game world inspired by the rhythm and mood of the selected track. No programming skills required. Upload your songs and play with other users’ tracks»
  4. https://www.whosampled.com — «Explore where samples came from, how old recordings were turned into new compositions, and which songs were reimagined by different artists»
  5. https://samplette.io — «Musical roulette. Serves up random tracks from YouTube, and you can set filters by genre, tempo, key, and popularity»
- Карусели 3:4 1080×1440 (правило), видео 9:16 из тех же слайдов (как drops_inspire). Все уникальны.
- Тест — сам смотрю и сам решаю, потом сразу партия.
- Сборщик build_drops_ear.py (дизайн 1389: вода/небо, адресная строка, iMac, карточка; обложка + музыкальные вырезки).
  Скрины: Drops — кадры из Dropbox (downloads/drops_ear/shots/drops_*), musicmap/whosampled/samplette — встроенный браузер.
  Musicmap: cookies НЕ принимал — окно и затемнение скрыты скриптом, карта показана.
- СТАТУС: карусели ГОТОВО 23:24 → output/drops_ear_TT_200 (1000 файлов sort_<слайд>_<n>_1.jpg, без exif).
  Видео ГОТОВО 23:50 → output/drops_ear_YT_200 (200 × 7.13 с, drops_ear_yt_NNN_1.mp4, метаданные чистые, md5 все разные).

## 3. YouTube Ehe9XufV3ZA — обрезать до 7 с, зауникалить: TT 100 + YT 150
- Схожесть 0–1 % между собой И со всем, что когда-либо делали из этих материалов (найти прошлые партии по исходнику).
- Это наш skinive_3 «Запись только в марте» (v1 10.4 с). Делаю в последнем одобренном формате v3 (карточки поверх видео),
  7.0 с: build_skinive3_7s.py --tt 100 --yt 150 → output/skinive3_7s_TT_100 + skinive3_7s_YT_150.
  Приём: bad_frames + покадровая сверка + 0 общих кадров со всеми skinive* (17 папок). Слои — overlay в памяти.
- ГОТОВО ~02:30: output/skinive3_7s_TT_100 + output/skinive3_7s_YT_150 (7.0 с, 210 кадров). Первая приёмка (3 к/с) пропустила
  31 пару (худшая 10.5 %) → 25 роликов убраны в output/_old/skinive3_7s_dropped и пересобраны с приёмкой по КАЖДОМУ кадру.
  Итог (каждый кадр, 31 125 пар): 0 пар с общими кадрами при пороге 40, худшая 0 %. Против 1908 старых skinive — 0 общих (3 к/с).

## 4. OneState KO — 200 TT + 200 YT, худшая пара ≤ 1 %
- Сборщик build_onestate_ko.py (из OneState 5): Map Update облёты + механик + такси, корейские тексты (Malgun Gothic),
  баннер KO (= banner Korea 2), музыка — звук роликов Map Update −18 LUFS, 15 с. Тест запущен 23:46.
- Формат-образец: https://drive.google.com/file/d/1FEuOV3v-OogdpFZgUtcQp0xCxgg9ZumU/view
- Материалы: https://drive.google.com/drive/folders/1nW1OmYcwwuUcs6mpI5dSb7lzoRmqTagD
- Баннер: Dropbox OneState_PromoBanner_V2_Loop_NoAmount_KO_04_STATEDQVH.mov
- Сборка: короткая надпись сверху → геймплей посередине → реальный корейский комментарий снизу. Акцент — графика 1.3
  / «это игра на телефоне?». БЕЗ стрельбы по игрокам и поверженных персонажей. 9:16, 15–25 с, баннер с промокодом.
  Тихая музыка с коммерческой лицензией или официальная тема OneState.
- Надписи сверху (дословно):
  - 이 정도면 폰 안에 도시 하나 넣어둔 거 아님? 🤯
  - 아니 물 반사까지 구현한 거 실화냐 👀🔥
  - 폰겜 그래픽 언제 여기까지 온 거임?
  - 잠깐 이게 폰겜이라고?ㅋㅋ
- Комментарии снизу (дословно):
  - 택시 첫 손님이 경찰한테 쫓기는 중이었음. 난 목적지 물어봤는데 일단 밟으래ㅋㅋ 💀
  - 친구가 택시 시작했다길래 손님인 척 탔는데 길을 몰라서 내가 운전함ㅋㅋ 돈은 왜 내가 내냐 😭
  - 택시 손님이 잠깐만 기다려 달래서 기다렸는데 다른 차 타고 감ㅋㅋ 게임에서도 이러네 🫠
  - 택시 운전하다가 손님 연애 상담만 한 시간 해줌ㅋㅋ 목적지는 도착했는데 얘기가 안 끝나 😭
- СТАТУС: ждёт.

## Журнал
- 22:58 очередь записана; mic 203/400.
- 23:24 Drops карусели 200 готовы; mic 362/400.

- 23:50 Drops видео 200 готовы; Skinive 7 с партия идёт; OneState KO тест рендерится.

- 00:10 Drops карусели ПЕРЕСОБРАНЫ (v1 давали общие кадры: 103 пары видео, худшая 45 %) — v2 с приёмкой по отпечаткам слайдов: 0 пар (порог 40). v1 → output/_old/drops_ear_*_v1. Видео v2 ГОТОВО ~00:30: каждый кадр 19 900 пар — 0 пар с общими кадрами (порог 40).
- 00:17 OneState KO: тест 2 ок (резка Map Update с учётом шторок), партия 200+200 запущена (лог output/_work/os_ko_gfx/batch.log).

## 5. Skinive 10 (добавлено юзером ~00:20) — 200 YT + 200 TT, схожесть 0–1 % и с прошлыми
- «дублируем залетный ролик» https://www.youtube.com/watch?v=TkTSJoZLunA (→ downloads/skinive10/ref).
- Новые исходники: Drive folder 1EsU4uSeHk2ec1wk1F-84hHqSoKbAYjMm (→ downloads/skinive10/src).
- Доп. вариации текста (дословно, немецкий; русское в скобках — перевод, НЕ на видео):
  - POV: du merkst, dass dein muttermal irgendwie komisch aussieht, lädst es bei Skinive hoch und siehst DAS 👇
  - POV: du willst nur kurz dein Muttermal bei Skinive checken und dann kommt DAS 👇
  - POV: du machst ein süßes selfie, zoomst auf dein muttermal und plötzlich geht’s nicht mehr ums selfie 😭
- Реф скачан (9.25 с: рука с родинками + POV-текст → App Store → приложение → скан → шкала).
- БЛОК 00:10: папка Drive 1EsU4uSe… закрыта (gdown 401, подключённый Drive её не видит, встроенный браузер без входа в Google). Нужен доступ «всем, у кого есть ссылка» или вход в Google во встроенном браузере.

## 6. Skinive 11 — текстволлы, 200 YT + 200 TT, схожесть 0–1 %
- Реф тот же TkTSJoZLunA. Материал: Drive file 1G56J5NWbj2yGVP-ejTabl5xyL_5RCLT2 (→ downloads/skinive11/src).
- Тексты (дословно; «4.» — нумерация юзера, не текст; русское в скобках — перевод):
  1. POV: du machst ein süßes selfie, zoomst auf dein muttermal und plötzlich geht’s nicht mehr ums selfie 😭
  2. meine freundin wollte nur ein süßes selfie machen. dann hat sie auf ihr muttermal gezoomt und das selfie war erstmal egal 😭
  3. meine freundin wollte ihr selfie bearbeiten und hat stattdessen 20 minuten lang ihr muttermal angezoomt 😭
  4. meine freundin: „welches selfie soll ich posten?“ fünf minuten später checken wir ihr muttermal bei Skinive 💀
  5. wir wollten das beste selfie von meiner freundin aussuchen. jetzt haben wir 14 screenshots von ihrem muttermal 😭
- БЛОК 00:10: файл IMG_6994.MOV (289 МБ, владелец orekh007) не публичный: gdown не может; подключённый Drive его видит, но отдаёт только целиком в base64 — 289 МБ так не скачать. Нужен доступ «всем, у кого есть ссылка».

- 03:15 KO: 171/400. Ночью было медленно: видеопамять (сборки + расчёт на видеокарте) → замены брака висли по 20–200 с;
  расчёт перенесён на процессор (UF_DEV=cpu, core/uniq_fast теперь умеет), банк прошлых партий урезан до тех, где было такси.

- 03:39 OneState KO ГОТОВО: 400 (output/onestate_ko_gfx_TT_200 + _YT_200, 15.0 с, 450 кадров). Каждый кадр 79 800 пар: 0 пар при пороге 40 и при 48, худшая 0 %.
- 04:30 KO против 2500 прошлых роликов: ближайший кадр 49 бит, 0 кадров ≤ 40. Ночь закончена: 1–4 готовы, 5–6 ждут доступа к Drive.
- 17.11 Drops ear (ID 1582): тюнер tuner_drops_ear.py, YT пересобраны со сменами юзера (7.63 с, _1582), каждый кадр 0/19 900 пар; старые → output/_old/drops_ear_YT_200_v2_before_tuner.
- 17.11 ~10:50 OneState KO: клиент «все ролики с движения человека начинались» → первый кусок — механик/прохожий в движении; старая партия → output/_old/onestate_ko_gfx_*_200_v1; пересборка 200+200 (лог output/_work/os_ko_gfx/batch_human.log). Skinive 10/11: доступы открыты, исходники скачаны и переведены в 1080p (output/_work/skinive10/clips), отпечатки всех прошлых skinive по каждому кадру — output/_work/skinive10/old30.npz; ждут KO.
- 17.11 ~12:00 Skinive 10+11: сборщик build_skinive10.py (формат хита skinive2, слои на видеокарте, сверка каждого кадра со всеми 2158 прошлыми skinive), партия 4×200 запущена (лог output/_work/skinive10/batch.log). KO: хвост 33 ролика.
- 17.11 ~12:55 OneState KO (человек в начале) ГОТОВО: 400 (output/onestate_ko_gfx_TT_200 + _YT_200), каждый кадр 79 800 пар — 0 при 40 и 48; против 2700 прошлых: 3 ролика по 1–3 кадра ≤40 бит с 1309 (≤0.7 %).
