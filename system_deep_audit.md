# System Deep Audit — сравнение прогонов out/

**Дата аудита:** 2026-09-22  
**Источник фактов:** `meta.json`, `manifest.json`, `usage_summary.json`, `out/usage/session_*.jsonl`, фрагменты консольных логов терминала.  
**Правило:** только измеримое; где данных нет в артефактах — явно помечено `N/A` / `нет в meta`.

---

## 0. Какие прогоны сравниваем

| Код | Путь | Что это |
|-----|------|---------|
| **Прогон A (живой «binge/fridge»)** | `out/carousel_20260922_141109/` | Одиночная карусель про ночной fridge / snacks / cheese. В `out/` **нет** отдельной папки с topic-строкой `"nighttime binge eating"`; ближайший и единственный свежий артефакт с этим сюжетом и полными UGC/Taste/Relevance — этот. |
| **Прогон A2 (контроль, вчера)** | `out/carousel_20260921_154232/` | Тот же fridge-сюжет, более ранний пайплайн (часть скоров отсутствует). |
| **Прогон B (проблемный batch)** | `out/run_20260922_143715/` | multi-topic, `made=4`, запрошено 20. В аудит входят **carousel_001, 002, 003** как указано. |

**Важно:** карусель с темой из списка batch `Unlearning the food guilt that causes nighttime binge eating` в `run_20260922_150706` **не была собрана** (прогон упал раньше: failed carousel_001/002). Поэтому «живая еда» = `carousel_20260922_141109`, не multi-topic run.

---

## 1. Сравнительная таблица слайдов

Harmony в batch-meta Прогона B **не сериализуется** (поля нет в ключах slide). В Прогоне A — есть `harmony_score`.  
Время сборки на слайд в meta **не пишется**; для B — wall-clock на всю карусель из usage/created_at (см. §2).

### 1.1 Прогон A — `carousel_20260922_141109` (fridge / nighttime eating)

`created_at`: **2026-09-22T14:11:09** · topic в meta: **null** (одиночная генерация)  
Тексты явно про fridge / snacks / pantry / 1 AM.

| Тема (сюжет) | Слайд | search_query | UGC | Taste | Relevance (text↔image) | Harmony | Время сборки |
|---|---|---|---:|---:|---:|---:|---|
| fridge/binge vibe | 1 | `kitchen fridge night iphone` | 0.6467 | 0.8007 | 0.9406 | 100.0 | N/A (нет TIMER; нет session jsonl) |
| fridge/binge vibe | 2 | `rain soaked window iphone` | 0.5979 | 0.6301 | 0.6447 | 76.9 | N/A |
| fridge/binge vibe | 3 | `night city street iphone` | 0.8282 | 0.8801 | **0.3049** | 94.4 | N/A |
| fridge/binge vibe | 4 | `snack food night iphone` | 0.8178 | 0.7388 | 0.9762 | 94.2 | N/A |
| fridge/binge vibe | 5 | `mirror selfie cozy iphone` | 0.8493 | 0.8734 | **0.2009** | 81.9 | N/A |
| fridge/binge vibe | 6 | `kitchen fridge cozy iphone` | 0.7007 | 0.6990 | 0.5074 | 98.6 | N/A |
| **AVG A** | — | — | **0.740** | **0.770** | **0.596** | **91.0** | — |
| **MIN A** | — | — | 0.598 | 0.630 | 0.201 | 76.9 | — |

`relevance_reason`: **нет в meta** · `alt_count`: **нет в meta** · soft/emergency markers: **нет**

### 1.2 Прогон B — `run_20260922_143715` carousel_001

Topic: **Why you feel like an imposter right before your biggest breakthrough**  
`created_at`: **2026-09-22T14:40:14** · DNA: The Friction Protocol #2  
Wall-clock карусели (gemini start → created_at): **176 с ≈ 2.93 мин**

| Тема | Слайд | search_query | UGC | Taste | Relevance | Harmony | Время (карусель) |
|---|---|---|---:|---:|---:|---|---|
| Imposter | 1 | `laptop night aesthetic iphone` | 0.7728 | 0.6442 | 0.7530 | N/A | 176 с на всю карусель |
| Imposter | 2 | `dark academia cozy iphone` | 0.5674 | 0.6093 | 0.9905 | N/A | ↑ |
| Imposter | 3 | `surreal cafe window iphone` | 0.8595 | 0.7407 | 0.8323 | N/A | ↑ |
| Imposter | 4 | `aesthetic laptop cozy iphone` | 0.7451 | 0.7756 | **0.2422** | N/A | ↑ |
| Imposter | 5 | `laptop desk night iphone` | 0.6606 | 0.6175 | 0.9805 | N/A | ↑ |
| Imposter | 6 | `cafe window cozy iphone` | 0.7749 | 0.7880 | 0.8197 | N/A | ↑ |
| **AVG B1** | — | — | **0.730** | **0.696** | **0.770** | — | **176 с** |
| **MIN B1** | — | — | 0.567 | 0.609 | 0.242 | — | — |

Все `relevance_reason` = `"local taste"`. `alt_count` финала: 4,3,4,3,3,4.

### 1.3 Прогон B — carousel_002

Topic: **The difference between resting and rotting in bed**  
`created_at`: **2026-09-22T14:45:24** · DNA: The Study Books Pattern  
Wall-clock: **297 с ≈ 4.95 мин**

| Тема | Слайд | search_query | UGC | Taste | Relevance | Harmony | Время |
|---|---|---|---:|---:|---:|---|---|
| Resting vs rotting | 1 | `aesthetic night cozy iphone` | 0.7445 | 0.7755 | 0.8633 | N/A | 297 с |
| Resting vs rotting | 2 | `dark academia cozy iphone` | 0.6770 | **0.5129** | 0.9842 | N/A | ↑ |
| Resting vs rotting | 3 | `night city street iphone` | 0.6566 | 0.6324 | 0.8517 | N/A | ↑ |
| Resting vs rotting | 4 | `aesthetic journaling pov iphone` | 0.8629 | 0.7267 | 0.9845 | N/A | ↑ |
| Resting vs rotting | 5 | `laptop desk night iphone` | 0.6035 | 0.6520 | 0.9227 | N/A | ↑ |
| Resting vs rotting | 6 | `cozy night aesthetic iphone` | 0.6219 | 0.6236 | 0.9814 | N/A | ↑ |
| **AVG B2** | — | — | **0.694** | **0.654** | **0.931** | — | **297 с** |
| **MIN B2** | — | — | 0.604 | 0.513 | 0.852 | — | — |

Все `relevance_reason` = `"local taste"`. `alt_count`: 3,3,3,4,4,3.  
Taste &lt; 0.60: **1** слайд (S2 = 0.5129, выше hard-floor 0.50).

### 1.4 Прогон B — carousel_003

Topic: **How to stop turning one bad hour into a ruined week**  
`created_at`: **2026-09-22T14:48:41** · DNA: The Study Books Pattern  
Wall-clock: **176 с ≈ 2.93 мин**

| Тема | Слайд | search_query | UGC | Taste | Relevance | Harmony | Время |
|---|---|---|---:|---:|---:|---|---|
| Bad hour → ruined week | 1 | `spilled coffee laptop iphone` | 0.7404 | 0.7455 | 0.9981 | N/A | 176 с |
| Bad hour → ruined week | 2 | `dark academia library iphone` | 0.6249 | 0.6520 | 0.9097 | N/A | ↑ |
| Bad hour → ruined week | 3 | `aesthetic book iphone` | 0.5938 | 0.6096 | 0.8662 | N/A | ↑ |
| Bad hour → ruined week | 4 | `aesthetic library cozy iphone` | 0.7038 | 0.6685 | 0.7474 | N/A | ↑ |
| Bad hour → ruined week | 5 | `books cozy aesthetic iphone` | 0.5831 | **0.5041** | 0.6812 | N/A | ↑ |
| Bad hour → ruined week | 6 | `vintage study cozy iphone` | 0.6770 | **0.5133** | 0.9877 | N/A | ↑ |
| **AVG B3** | — | — | **0.654** | **0.616** | **0.865** | — | **176 с** |
| **MIN B3** | — | — | 0.583 | 0.504 | 0.681 | — | — |

Все `relevance_reason` = `"local taste"`. `alt_count`: 4,3,3,4,3,4.  
Taste &lt; 0.60: **2** слайда (S5, S6).

### 1.5 Сводка средних (финальные выбранные кадры)

| Прогон | AVG UGC | AVG Taste | AVG Relevance | AVG Combined | Слайдов с Taste&lt;0.60 | Слайдов с UGC&lt;0.65 |
|--------|--------:|----------:|--------------:|-------------:|----------------------:|---------------------:|
| A fridge | **0.740** | **0.770** | 0.596 | 0.717 | **0** | 2 |
| B1 imposter | 0.730 | 0.696 | **0.770** | 0.745 | 0 | 1 |
| B2 resting | 0.694 | 0.654 | **0.931** | **0.778** | 1 | 2 |
| B3 bad hour | 0.654 | 0.616 | 0.865 | 0.729 | 2 | 3 |

**Факт, который ломает интуицию:** по средним скорам Прогон B **не хуже** Прогона A (у B2 combined даже выше). «Неживость» B **не объясняется низкими UGC/Taste в meta финалистов**.

---

## 2. Расследование времени: где сидят 3–5 минут (Прогон B)

### 2.1 Жёсткие цифры wall-clock

Источник: `out/usage/session_20260922_143715.jsonl` (метки `gemini_text_gen`) + `created_at` в meta + `manifest.usage.elapsed_sec`.

| Карусель | Старт Gemini | created_at | Δ wall | Доля от сессии |
|----------|--------------|------------|-------:|----------------|
| 001 Imposter | 14:37:18 | 14:40:14 | **176 с (2.93 мин)** | |
| 002 Resting | 14:40:27 | 14:45:24 | **297 с (4.95 мин)** | пик |
| 003 Bad hour | 14:45:45 | 14:48:41 | **176 с (2.93 мин)** | |
| 004 (вне таблицы, для контекста) | 14:49:00 | 14:52:39 | **219 с (3.65 мин)** | |
| **Сессия целиком** | 14:37:15 → finished 14:53:03 | | **947.2 с** / 4 = **236.8 с ≈ 3.95 мин/карусель** | |

Gemini text gen сам по себе в поздних TIMER-прогонах ≈ **3–5 с**. Значит **≥95%** этих 3–5 минут — harvest / фильтры / рендер, не LLM.

В Прогоне B **нет строк `[TIMER]`** — профайлер этапов ещё не был внедрён (появился в прогонах ~15:07+). Поэтому разложение «сеть vs SigLIP vs render» для B **нельзя** взять из логов того же run; только wall-clock и косвенные логи.

### 2.2 Устройство SigLIP

Текущий код `core/taste_embedder.py`:

- если `torch.cuda.is_available()` → `device=cuda`, `float16`;
- иначе CPU + WARNING.

**Проверка после 14:37 (эта же машина):** в терминалах зафиксировано  
`[SigLIP] backend=google/siglip-base-patch16-224 device=cuda dtype=fp16 gpu=NVIDIA GeForce RTX 3060 Laptop GPU`.

Для самого `run_20260922_143715` отдельной строки `[SigLIP] device=...` в сохранённом логе сессии **нет**. Утверждать CPU для B нельзя. CUDA на этой машине доступна; узкое горлышко B по времени согласуется с **сетью + длинными fallback-цепочками**, а не обязательно с CPU-SigLIP.

### 2.3 Сеть / ретраи — что видно в логах того же стиля запросов

В `terminals/1.txt` (сессии с теми же `aesthetic` / `dark academia` запросами, формат `fallback[n/10]`):

- на слайд уходило до **`fallback[1/10]` … `[6/10]`** и выше — то есть цепочка до **10** вариантов запроса **последовательно**;
- частые `[WARNING] UGC/фильтры обнулили … candid-retry`;
- ответы Pinterest часто **0–2** картинки на попытку, иногда 6.

Это прямо объясняет 3–5 минут:  
**6 слайдов × (несколько search + AI-check + CDN + SigLIP) × до 10 fallback** = минуты wall-time при последовательном выполнении.

В коде на момент аудита уже урезано до `MAX_QUERY_ATTEMPTS = 2` и parallel gather; **Прогон B собран ДО этого ускорения**.

### 2.4 Сколько картинок на карусель

В meta B есть только `alt_count` финального пула (3–4 на слайд), **не** число скачанных/отброшенных.

Оценка по коду того периода + логам:

- целевой финал: `CANDIDATES=6`, `MIN_KEEP=3`;
- на каждый удачный search в логах: обычно 1–6 скачанных;
- при `fallback[k/10]` суммарно на слайд легко **десятки** сетевых циклов, из которых в meta остаётся 3–4 alt.

Точный count downloaded/rejected в артефактах B: **N/A**.

### 2.5 Вывод по времени (без сглаживания)

| Гипотеза | Вердикт по фактам |
|----------|-------------------|
| Gemini тормозит | **Нет** (~секунды) |
| SigLIP на CPU в B | **Не доказано**; сейчас CUDA. Даже на CUDA длинные последовательные циклы дают минуты |
| Узкое горлышко | **Последовательный harvest + длинная fallback-цепочка (до 10) + UGC-retry**, подтверждаемо логами `fallback[n/10]` и wall 176–297 с |
| Поздние TIMER (после фикса) | Pinterest wall ~4–6 с, SigLIP ~20–58 с, ИТОГО ~33–58 с — контраст с B подтверждает, что B был другим режимом исполнения |

---

## 3. Анатомия запросов: почему еда ощущалась живее

### 3.1 Подсчёт токенов (простая лексика)

Словарь физического якоря (fridge, kitchen, snack, food, lamp, window, phone, desk, coffee, book**s** как объект и т.п.) vs абстрактного маркера (aesthetic, cozy, dark, academia, vibe-подобные).

| Прогон | Примеры query | Physical hits | Abstract hits | Токенов всего |
|--------|---------------|--------------:|--------------:|--------------:|
| A fridge | `kitchen fridge night`, `snack food night`, `mirror selfie` | **8** | 2 | 24 |
| A2 fridge | `kitchen fridge open` ×3, `dim room lamp` | **11** | 0 | 18 |
| B1 imposter | `laptop night aesthetic`, `dark academia cozy` | 2 | **7** | 24 |
| B2 resting | `aesthetic night cozy`, `cozy night aesthetic` | **0** | **8** | 24 |
| B3 bad hour | `aesthetic book`, `books cozy aesthetic` | 1 | **8** | 23 |

### 3.2 Структурная разница (факты)

**Прогон A**

- Повторяющиеся **конкретные существительные места/объекта:** `fridge`, `kitchen`, `snack`, `food`, `street`, `window`, `mirror`.
- Текст слайдов тоже предметный: cheese slices, pantry, fridge at 1 AM.
- DNA/archetype в meta: null (не Study Books / Friction).

**Прогон B**

- Доминируют шаблоны: `aesthetic`, `dark academia`, `cozy` + laptop/book/library.
- DNA: **The Study Books Pattern** (B2, B3), Friction Protocol (B1) — визуальный режим «учёба / aesthetic desk», не «бытовая сцена».
- Один относительно предметный запрос в B3: `spilled coffee laptop iphone` — и у него лучшие скоры карусели (UGC 0.74, Taste 0.75, Rel 0.998).

### 3.3 Вывод по «живости»

Субъективная «живость» A **не куплена более высоким UGC** (A и B1 почти равны: 0.74 vs 0.73).  
Она совпадает с:

1. **предметными query → Pinterest отдаёт бытовые/UGC-сцены** (открытый холодильник, еда), а не пресет dark academia;
2. **более высоким Taste в среднем у A (0.77 vs 0.62–0.70)** — единственный скор, где A устойчиво выше;
3. **контентом кадра**, который классификатор UGC может оценить высоко и у «красивого стока» (B), но глаз читает как мёртвый пресет.

Relevance у B **выше**, чем у A (0.77–0.93 vs 0.60). То есть B лучше «попадает в текст» по SigLIP, но текст/запрос тянут в aesthetic-библиотеку, а не в fridge-реализм. Relevance ≠ perceived life.

Отдельно: у A слайды 3 и 5 прошли с Relevance **0.30 и 0.20** (у порога 0.18) при высоком Taste/UGC — то есть в «живой» карусели смысл text↔image иногда слабый, а «жизнь» держат Taste+UGC+объект в кадре.

---

## 4. Статистика отбора

### 4.1 Что есть в meta

| Метрика | Прогон A | Прогон B (001–003) |
|---------|----------|---------------------|
| Финальных слайдов | 6 | 6+6+6 |
| `alt_count` (выживших кандидатов на слайд) | **нет поля** | 3–4 на каждом слайде |
| `relevance_reason` | нет | все **`local taste`** |
| Маркер soft-pass / rescue / emergency | нет | **нет** (ни одного `emergency keep`) |
| Harmony в meta | да | **нет** |
| Число отброшенных фильтром | **N/A** | **N/A** |

Интерпретация `alt_count` 3–4 при `CANDIDATES=6`: в финальный пул слайда прошло **не меньше 3** кадров; сколько было отрезано до этого — meta не пишет.

### 4.2 Soft-pass / rescue

По полям финалистов B:

- нет reason вроде `taste untrained`, `emergency keep`, soft UGC;
- все явно прошли ветку **`local taste`** (hard path вкуса сработал и оставил кадр).

В **более поздних** прогонах (после 15:07) в консоли уже есть `emergency-keep` с ugc=0.40 / taste=0.33 — это **другой** режим и **не** Прогон B.

### 4.3 Пороги vs факты финалистов

Актуальные пороги в коде: UGC ≥ 0.55, Taste floor 0.50 (предпочтительно ≥ 0.60), Relevance ≥ 0.18.

| | A | B1 | B2 | B3 |
|--|--:|--:|--:|--:|
| UGC &lt; 0.55 | 0 | 0 | 0 | 0 |
| Taste &lt; 0.50 | 0 | 0 | 0 | 0 |
| Taste &lt; 0.60 | 0 | 0 | 1 | 2 |
| Rel &lt; 0.18 | 0 | 0 | 0 | 0 |

Ближе всего к «еле пролез» в B: Taste 0.504–0.513 (B3 S5/S6), UGC 0.567 (B1 S2).  
В A «еле пролез» по смыслу: Rel 0.201 / 0.305 при сильном Taste.

### 4.4 Контроль A2 (`carousel_20260921_154232`)

Тот же fridge-сюжет, но скоры слабее и без Relevance/Combined в meta:

- AVG UGC **0.579**, AVG Taste **0.468**
- UGC &lt; 0.55: **2**; Taste &lt; 0.50: **3**; Taste &lt; 0.60: **все 6**

То есть «живой сюжет» вчера мог проходить с **более низкими** скорами — пороги/пайплайн были мягче или другие. Сегодняшний A (141109) уже ужесточён и при этом fridge всё ещё набирает высокий Taste.

---

## 5. Прямые ответы на три целевых вопроса

### 5.1 Почему binge/fridge выглядел живее последних каруселей?

По цифрам meta:

1. **Не потому что UGC выше** — A 0.74 ≈ B1 0.73; B даже с высоким Relevance.
2. **Потому что Taste выше** — A 0.77 vs B 0.62–0.70, и **0 слайдов A с Taste&lt;0.60** против 0/1/2 у B.
3. **Потому что query/сцена предметные** (`fridge`, `snack`, `kitchen`) vs `aesthetic`/`dark academia`/`cozy` шаблоны Study Books — это измеримо по лексике (§3).
4. Pinterest на aesthetic-шаблоны стабильно отдаёт «пресетный» тёмный academia/desk, который классификатор может счесть приемлемым UGC, но визуально это не fridge-реализм.

### 5.2 Почему в `run_20260922_143715` уходило 3–5 минут?

1. Wall-clock: **176 / 297 / 176 / 219 с** на карусель; сессия **947 с / 4 ≈ 3.95 мин**.
2. Gemini не виноват (~секунды).
3. В логах того поколения — **`fallback[n/10]`** + UGC candid-retry **последовательно по слайдам**.
4. TIMER-разложения для этого run нет; после фикса те же этапы укладываются в **~0.5–1 мин** (сеть ~5 с + SigLIP десятки секунд).

Узкое горлышко B: **последовательный multi-attempt harvest**, не «магические 5 минут Gemini».

### 5.3 Почему фото всё ещё «неживые», какие реальные оценки?

Финал B (001–003), факт:

| | Диапазон UGC | Диапазон Taste | Диапазон Relevance |
|--|-------------:|---------------:|-------------------:|
| B1 | 0.57–0.86 | 0.61–0.79 | 0.24–0.99 |
| B2 | 0.60–0.86 | 0.51–0.78 | 0.85–0.98 |
| B3 | 0.58–0.74 | 0.50–0.75 | 0.68–1.00 |

Они **не провальные** по порогам. «Неживость» при таких скорах = **mismatch между метрикой и желаемым look**: система оптимизирует UGC/Taste/Rel на выдаче Pinterest по aesthetic-query, а желаемый look ближе к fridge/snack A, где Taste реально выше и объекты конкретнее.

---

## 6. Пробелы данных (честный список)

1. Нет meta с topic `"…nighttime binge eating"` из multi-topic — использован ближайший fridge-артефакт `carousel_20260922_141109`.
2. Harmony не пишется в batch meta B.
3. Нет per-slide / per-stage TIMER в Прогоне B.
4. Нет count rejected/downloaded в meta — только `alt_count` финала.
5. Нет прямого `[SigLIP] device=` лога именно для сессии 143715 (есть для более поздних запусков на той же машине: cuda).

---

## 7. Итог одной строкой

**Прогон B медленный из‑за последовательных fallback×10; «неживой» не из‑за низких UGC в meta, а из‑за aesthetic/dark-academia запросов при сопоставимых/высоких Relevance; живой fridge-прогон A выигрывает предметом в query и средним Taste 0.77 при UGC≈0.74.**
