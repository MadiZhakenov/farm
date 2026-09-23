# Audit: дубликаты в batch + утечки pro/AI фото

**Дата:** 2026-09-22  
**Источники:** `out/run_*/**/meta.json`, `core/batch_factory.py`, `core/harvester.py`, `carousel_factory_app.py`  
**Метод:** сравнение `pin_id` выбранных слайдов между каруселями одного run; MD5 первых 64 KB файлов `*.jpg` (рендер с текстом — см. ограничение ниже).

---

## 0. Executive summary (факты)

| Run | Каруселей с meta | Слотов фото | Unique pin | Reuse rate | Cross-carousel pins | Emergency keep | Low UGC/Taste |
|-----|-----------------:|------------:|-----------:|-----------:|--------------------:|---------------:|--------------:|
| `run_20260922_155221` | 6 | 36 | 25 | **30.6%** | **8** | **11/36 (30.6%)** | 5 |
| `run_20260922_151414` | 6 | 36 | 21 | **41.7%** | **7** | **6/36 (16.7%)** | 4 |
| `run_20260922_143715` | 4 | 24 | 20 | 16.7% | 4 | 0 | 2 |
| `run_20260922_155011` | 1 | 6 | 6 | 0% | 0 | 3/6 | 1 |
| `run_20260922_150706` | 1 | 6 | 6 | 0% | 0 | 0 | 0 |
| `run_20260922_154622` | 0 | — | — | — | — | — | FAIL×10 (bug `text`) |
| `run_20260917_104317` | 10 | 60 | 56 | 6.7% | 4 | 0* | 0 |
| `run_20260916_170735` | 20 | 120 | 109 | 9.2% | 9 | 0* | 0 |

\* Старые прогоны: другой `relevance_reason` (текстовый judge), не `emergency keep`.

**Вывод одной строкой:** в свежих multi-topic batch **30–42% слотов — повтор уже использованного `pin_id`**; причина в коде — `harvester.reset_used()` на **каждую** карусель + всегда берётся **argmax** (`selected=0` после sort). Низкий UGC/Taste проходит через **`emergency keep (gates empty)`**, который снимает hard-reject.

---

## 1. Дубликаты между каруселями одного запуска

### 1.1 Метрика

- Сравнивались **финальные** `pin_id` из `meta.json` (выбранный фон слайда).
- `source_url` / `image_url` в batch-meta **не сериализуется** (`batch_factory` пишет только `pin_id`) → URL-сравнение **N/A**.
- Хэш файлов `1.jpg`…`6.jpg`: **0 совпадений** во всех свежих run — ожидаемо: на диск пишется **рендер с текстом**, байты разные даже при одном фоне.

### 1.2 `run_20260922_151414` (худший по повторам)

- **36** слотов, **21** уникальный pin → **reuse 41.7%**.
- **7** pin встречаются в ≥2 каруселях.
- Средний pairwise overlap (intersection / min(|A|,|B|)): **32.2%** по 15 парам.
- **Худшая пара:** `carousel_004` vs `carousel_005` — **5 из 6** pin совпали (**83.3%**).

Топ повторных pin:

| pin_id | Раз | Карусели (сокращённо) |
|--------|----:|------------------------|
| `323555554502411938` | 5 | 001, 003, 004, 005, 006 |
| `49610033391477289` | 5 | 002, 003, 004, 005, 006 |
| `20266267069161196` | 3 | 001, 004, 005 |
| `37647346881552336` | 3 | 002, 004, 005 |

Запросы вокруг этих pin (из meta): `dark academia desk iphone`, `aesthetic journaling pov iphone`, `aesthetic book iphone`, `dark academia candid`, `laptop workspace candid` — похожие aesthetic/study шаблоны → один и тот же топ Pinterest.

### 1.3 `run_20260922_155221` (после tangible-fix)

- **36** слотов, **25** unique → **reuse 30.6%** (лучше 151414, но всё ещё высокий).
- **8** cross-carousel pins.
- Pairwise avg overlap: **15.6%**; worst pair **33.3%** (2 общих pin).
- Топ: `308707749481278724` ×3, `637048309836969246` ×3, `2462974793808579` ×3.

### 1.4 `run_20260922_143715`

- reuse **16.7%**, 4 cross-pins, emergency **0** — до широкого emergency-keep.
- Pairwise avg **11.1%**.

### 1.5 Внутри одной карусели

- `dedupe_carousel_pools` (после parallel harvest) держит уникальные pin **внутри** карусели.
- В сканированных meta **within-carousel dup pin на selected** не доминирует; проблема — **между** каруселями run.

---

## 2. Код: почему пул общий и «всегда одни и те же»

### 2.1 Есть ли `used_pin_ids_in_run`?

**Нет.** В batch нет множества на весь run.

Что есть:

```python
# core/harvester.py — PinterestHarvester.__init__
self._used_pin_ids: set[str] = set()

def reset_used(self) -> None:
    self._used_pin_ids.clear()
```

```python
# core/batch_factory.py — build_one_carousel (КАЖДАЯ карусель)
harvester.reset_used()
...
harvested = harvester.harvest_slides_parallel(...)
```

```python
# core/batch_factory.py — run_batch
# один и тот же harvester передаётся в цикл,
# но build_one_carousel каждый раз вызывает reset_used()
folder = build_one_carousel(llm=llm, harvester=harvester, ...)
```

**Факт:** `_used_pin_ids` живёт только на время **одной** карусели (дедуп слайдов + ignore_used). Между `carousel_001` и `carousel_002` множество **обнуляется**. Карусели независимо черпают из одного Pinterest-топа по похожим query.

В GUI то же: `self.harvester.reset_used()` при старте harvest / новой теме — run-level set отсутствует.

### 2.2 Argmax vs sampling

Отбор финала — **жёсткий argmax**, рандома нет.

1. После гейтов:

```python
# harvester.judge_and_filter
kept.sort(key=lambda c: c.combined_score, reverse=True)
# top = kept[0]
```

2. Emergency:

```python
# harvester.rank_pool_emergency
pre.sort(key=lambda c: c.combined_score, reverse=True)
# берёт top[:limit] — снова №1
```

3. Batch всегда:

```python
BatchSlide(..., selected=0)
...
cand = s.candidates[s.selected]  # всегда индекс 0 после sort
```

4. Color harmony:

```python
scored.sort(key=lambda x: x[0], reverse=True)
_reorder_batch_slide(...)  # лучший → selected=0
```

**`random` / sampling из top-K в пути batch-отбора нет** (единственный `random` в harvester — ideas feed, не batch carousel).

Следствие: при одинаковых query + одинаковом ранжировании SigLIP → один и тот же pin №1 во многих каруселях.

---

## 3. Утечки профессиональных / «неживых» / низкий UGC

### 3.1 Кто проходит с низкими скорами

Пороги в коде (hard path): UGC ≥ **0.55**, Taste floor **0.50**, Relevance ≥ **0.18**.

В meta всё, что ниже, помечено:

```text
relevance_reason = "emergency keep (gates empty)"
```

#### `run_20260922_155221` — 5 low / 11 emergency

| UGC | Taste | reason | query |
|----:|------:|--------|-------|
| **0.220** | **0.371** | emergency keep | `old money office candid` |
| 0.504 | 0.614 | emergency keep | `open book desk candid` |
| 0.504 | 0.614 | emergency keep | `open book desk candid` (повтор pin) |
| 0.707 | **0.471** | emergency keep | `mirror reflection finsta` |
| **0.386** | **0.378** | emergency keep | `stack books candid` |

11/36 слайдов (**30.6%**) — emergency, не hard `local taste`.

#### `run_20260922_151414` — 4 low / 6 emergency

| UGC | Taste | reason | query |
|----:|------:|--------|-------|
| 0.590 | **0.495** | emergency | `aesthetic book stack iphone` |
| 0.536 | 0.705 | emergency | `hands phone lamp iphone` |
| **0.491** | **0.329** | emergency | `minimalist desk open iphone` |
| **0.397** | **0.491** | emergency | `aesthetic laptop workspace iphone` |

#### `run_20260922_143715` — без emergency

2 слайда с Taste чуть выше floor (0.50–0.54) при UGC ≥ 0.55, reason=`local taste` — легальный hard-pass у порога, не soft rescue.

### 3.2 Почему фильтры их не срезали

Цепочка (факт кода):

1. Hard gates (`_apply_ugc_gate` / `_apply_taste_gate`) **обнуляют** пул.
2. Candid-retry часто даёт 0 новых pin.
3. Включается **`rank_pool_emergency`**: считает скоры, **но не режет** по UGC/Taste floor; ставит `relevance_reason = "emergency keep (gates empty)"` и берёт argmax combined.
4. Цель emergency — «не пустой слайд»; побочный эффект — **сток/pro/низкий UGC** попадает в финал.

Это и есть **silent soft-fallback** (не тихий в логах — есть `[WARNING] emergency-keep`, но для качества = обход гейтов).

### 3.3 Метаданные / теги Pinterest у этих пинов

В batch `meta.json` **нет** полей title / board / Pinterest tags / `source_url` — только `pin_id`, query, скоры.  
Восстановить теги из артефактов run **нельзя** без повторного запроса к API. Статус: **N/A в артефактах**.

Косвенно: query уровня `aesthetic laptop workspace`, `minimalist desk`, `old money office`, `stack books` — Pinterest отдаёт пресетный desk/office сток, который гейты режут, а emergency возвращает.

---

## 4. План безопасного устранения (без ломки пайплайна)

### 4.1 Batch-дедупликатор по `pin_id` (приоритет 1)

**Идея:** множество на весь `run_batch`, не сбрасывать между каруселями.

Минимальный дифф:

1. В `run_batch` создать `used_pins_run: set[str] = set()`.
2. Передавать в `build_one_carousel(..., exclude_pins=used_pins_run)`.
3. **Не** вызывать полный `reset_used()` вслепую — вместо:
   - `harvester.reset_used()` только в начале run **или**
   - `harvester._used_pin_ids |= exclude_pins` перед harvest, без clear;
   - после успешной карусели: добавить все `pin_id` финальных слайдов (+ опционально alts) в `used_pins_run`.
4. В `harvest_slides_parallel` / `harvest_for_query` уже есть фильтр `pin_id not in used` — достаточно засеять `_used_pin_ids` до поиска.
5. Если после exclude пул пуст → оставить текущий emergency **только тогда**, иначе риск снова пустых слайдов.

**Риск:** при 20 каруселях × 6 pin пул исчерпывается → больше candid/emergency. Митигация: exclude только **selected** pin (не все alts); при пустоте разрешить reuse с пометкой в meta `reuse_after_exhaustion=true`.

### 4.2 Контролируемая случайность top-K (приоритет 2)

Вместо всегда `kept[0]`:

```python
# псевдокод — только после hard gates (НЕ для emergency с ugc<0.55)
TOP_K = 3
pool = kept[:TOP_K]
# веса по combined_score (softmax) или uniform
chosen = random.choices(pool, weights=[c.combined_score for c in pool], k=1)[0]
# переставить chosen в индекс 0
```

Правила безопасности:

- Sampling **только** среди кандидатов, прошедших hard UGC/Taste/Rel.
- Для `emergency keep` — **не** сэмплировать низкий хвост; либо запретить emergency в batch и fail-slide / retry query; либо emergency только если `max(ugc,taste) ≥ soft_floor` (напр. 0.45).
- Seed от `(run_id, carousel_index, slide_index)` для воспроизводимости в аудитах.

### 4.3 Зажать emergency (приоритет 3, качество)

Варианты по возрастанию жёсткости:

| Уровень | Поведение |
|---------|-----------|
| A | Emergency разрешён, но **meta + лог**; batch UI бейдж «emergency» |
| B | Emergency только если best UGC≥0.50 и Taste≥0.45, иначе новый query / fail slide |
| C | В batch emergency **запрещён**; пустой слайд → retry topic query / skip carousel |

Рекомендация: **B** + run-level pin exclude + top-3 sample на hard path.

### 4.4 Порядок внедрения (без big-bang)

1. Run-level `used_pins` + не clear между каруселями (метрика: reuse% в следующем run).
2. Top-3 weighted sample на hard-pass only.
3. Soft-floor на emergency (B).
4. Писать в meta: `source_url`, `selection_mode` (`argmax`|`sample_top3`|`emergency`), `excluded_run_pins_count`.

---

## 5. Цифры для регрессии (цель после фикса)

| Метрика | Сейчас (155221 / 151414) | Цель |
|---------|--------------------------|------|
| Reuse rate pin в run | 30.6% / 41.7% | **&lt; 5%** |
| Worst pair overlap | 33% / **83%** | **&lt; 17%** (≤1 pin) |
| Emergency доля слайдов | 30.6% / 16.7% | **&lt; 5%** |
| Слайды с UGC&lt;0.55 | есть (emergency) | **0** |

---

## 6. Пробелы данных

1. Нет `image_url`/`source_url` в batch meta → дубли считали по `pin_id`.
2. Хэш рендеров с текстом не детектит одинаковый фон.
3. Теги Pinterest у low-score пинов в артефактах отсутствуют.
4. `run_20260922_154622` — полный fail по UnboundLocalError `text` (исправлено отдельно), в аудит дублей не входит.

---

## 7. Итог

Повторы в batch — не «магия Pinterest alone», а **сброс `_used_pin_ids` на каждую карусель** + **argmax №1**.  
Pro/AI ощущение и низкий UGC — в основном **`emergency keep`**, который обходит UGC/Taste floors после пустого hard-pass.  
Безопасный фикс: run-level exclude pin → sample top-3 на hard path → soft-floor/лимит emergency.
