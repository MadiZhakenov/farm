# Current Pipeline State — Carousel Factory

Срез кода на **2026-09-23**. Только факты из репозитория `e:\Users\Desktop\farm`.  
Hot path: `topic → Gemini slides/search_query → Pinterest harvest → SigLIP gates → render → review`.

---

## 1. Текст и запросы (`core/llm_engine.py`)

### 1.1 Системный промпт — блок `search_query` (дословно)

Из `build_system_prompt()`:

```
=== PINTEREST SEARCH QUERY — HUMAN SITUATION & VIBE (strict 3–4 words) ===
search_query is NOT a literal word→object dictionary.
FORBIDDEN literal parsing: never turn a random slide word into a prop.
  'spark' ≠ coffee, 'analyzed' ≠ notebook, 'danger' ≠ sports car,
  'perfume' ≠ steering wheel, metaphor nouns ≠ product still-life.

Before writing search_query, answer silently:
  1) WHAT DOES THE PERSON ON THIS SLIDE FEEL?
     (anxiety, loneliness, spiral, emptiness, hope, overwhelm, distance…)
  2) WHERE ARE THEY + IN WHAT POSE RIGHT NOW?
     (sitting on floor, lying in bed staring at ceiling, pacing, at window…)

Formula: [human pose/action] + [place/situation] + optional aesthetic|candid
Exactly 3–4 words. Viral-author patterns (reuse the SHAPE, rewrite to THIS slide):
  Anxiety / waiting on a text:
    "staring phone waiting aesthetic", "hands holding phone dark"
  Loneliness / emptiness:
    "sitting floor alone aesthetic", "girl leaning wall shadow"
  Night spirals:
    "lying bed staring ceiling", "pacing room night light"
  Breakup / distance:
    "walking alone sidewalk night", "looking out window dusk"
  Overwhelm:
    "head in hands desk", "sitting steps outside alone"

HARD BAN: iphone / finsta / snapshot / 35mm / photo dump / lighting poems /
moodboard-only ("cozy aesthetic", "dark academia", "aesthetic night").
HARD BAN: face close-ups, stock "stressed person", fashion/outfit street style.
Do NOT invent a still-life object just because a metaphor word appeared.
phone ONLY if the feeling is waiting/texting/doomscroll — not by default.
candid or aesthetic ONLY as the optional last word — never alone.

=== NO LITERAL OBJECT MATCHING ===
Never map slide vocabulary → desk props (journal/laptop/keys/wheel) by keyword.
Psychology / relationships / imposter / overthinking → human situation queries above.
Skincare product moments may show hands+serum sink — still no metaphor→object jumps.
```

User-prompt (фрагмент `build_user_prompt`):

```
search_query: HUMAN SITUATION 3–4 words —
[pose/action] + [place] + optional aesthetic|candid.
Ask: what do they FEEL? where/what pose are they in?
Examples: 'staring phone waiting aesthetic', 'sitting floor alone aesthetic',
'lying bed staring ceiling', 'walking alone sidewalk night',
'head in hands desk'.
FORBIDDEN: literal word→object ('analyzed'≠notebook, 'perfume'≠wheel,
'spark'≠coffee). NEVER append iphone/finsta/35mm.
NEVER moodboard-only or still-life from random nouns.
```

Модель: `DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"`.  
Длина карусели: **5–9** слайдов (`MIN_CAROUSEL_SLIDES` / `MAX_CAROUSEL_SLIDES`).

### 1.2 Постобработка запросов (sanitizer / clamp)

Цепочка после Gemini:

1. `_sanitize_carousel_queries` → `_force_tangible_noun_prefix` (если нет human pose → situation fallback) → `_force_geography_query` → `_clamp_query_to_word_limit`
2. `_scrub_query` → снова `_clamp_query_to_word_limit` → `finalize_photo_query` (`core/harvester.py`)

**`finalize_photo_query`:**

- Срезает lighting-якоря (`CAROUSEL_LIGHTING_ANCHORS`) и legacy-фразы (`dark academia`, `cozy aesthetic`, `aesthetic night`, `35mm film`, `shot on iphone photo dump`, …).
- Regex-вырез: `\b(academia|vibes?|moody|ambient)\b`.
- **Не** вызывает `_inject_slide_noun` (literal word→object отключён).
- `_clamp_query_words(min_w=3, max_w=4, allow_phone=…)`.
- Дефолт при пустом результате: `"sitting floor alone aesthetic"`.

**Слова, которые clamp УДАЛЯЕТ (`drop`):**

| Группа | Токены |
|--------|--------|
| UGC/шум | `shot`, `on`, `photo`, `dump`, `raw`, `camera`, `roll`, `amateur`, `flash`, `girlhood`, `pinterest`, `rotting`, `covering`, `oversized`, `from`, `behind`, `fairy`, `lights`, `blanket`, `duvet`, `hoodie`, `open` |
| Стоп-слова | `the`, `and`, `with`, `for`, `a`, `an`, `of`, `to`, `in`, `by`, `at`, `on` |
| Маркеры | `iphone`, `finsta`, `snapshot` |
| Lighting spam | `warm`, `evening`, `ambient`, `soft`, `morning`, `natural`, `sunlight`, `moody`, `golden`, `hour`, `sunny`, `golden-hour` |
| Условно | `phone` — только если `allow_phone=False` (слайд не про телефон) |

**Слова, которые clamp СОХРАНЯЕТ (pose keep):**  
`sitting`, `lying`, `leaning`, `walking`, `pacing`, `staring`, `holding`, `waiting`, `looking`, `hands`, `head`, `writing`, `focused`.

**Стиль (не удаляются, вешаются в хвост если есть место ≤4):**  
`aesthetic`, `candid`.

**Что ДОПИСЫВАЕТСЯ (fillers, если слов &lt; 3):**  
по очереди `alone`, `night`, `window`, `room`, `desk`, `floor` — только недостающие до `min_w=3`.  
**iphone / candid / finsta НЕ дописываются** (`UGC_QUERY_MARKERS = ()`, `ensure_mobile_query_marker` = clamp без append).

**`_scrub_query` / sanitize дополнительно:**

- Вырезает moodboard-фразы, stock/face bans, `academia|vibes?|moody|ambient`.
- Still-life без позы человека → `_mood_query_from_slide` / situation pools.
- Bed вне sleep-темы: режется, **кроме** human-situation с bed (`lying bed…`).

### 1.3 `aesthetic_query_for_slide`

**Да, существует** в двух местах:

| Файл | Поведение |
|------|-----------|
| `carousel_factory_app.py` | `aesthetic_query_for_slide(text, index)` → делегирует в `core.harvester.situation_query_for_slide` |
| `core/harvester.py` | `aesthetic_query_for_slide` = alias → `situation_query_for_slide` |

**Что возвращает:** 3–4 слова human situation после `finalize_photo_query`, пул по вайбу текста:

- relationships → `walking alone sidewalk night` / `empty chair across table` / `looking out window dusk`
- study/work → `hands writing notebook desk` / `desk lamp focused night` / `head in hands desk`
- anxiety/psych → `staring phone dark room` / `sitting floor alone room` / `pacing room night light`
- else → `sitting floor alone aesthetic` / `looking out window dusk` / …

Object-map (`coffee cups`, `steering wheel`, `notebook desk`) **удалён**.

---

## 2. Поиск и скачивание (`core/harvester.py` + batch/GUI)

### 2.1 Кандидаты на слайд

| Константа | Значение | Файл |
|-----------|----------|------|
| `CANDIDATES_PER_SLIDE` | **10** | `harvester.py` |
| `CANDIDATES` | **10** | `batch_factory.py` |
| `CANDIDATES` | **10** | `carousel_factory_app.py` |
| `MIN_KEEP` | **3** | batch + GUI |
| `MAX_ALTS_SAVED` | **6** | batch + GUI |
| `_taste_fetch_limit(limit)` | `max(limit*2, limit+4)` → при 10 ≈ **20–24** скачиваний в пул до ранга | harvester |

### 2.2 Сеть

| Параметр | Значение |
|----------|----------|
| `REQUEST_TIMEOUT` | **20.0** с |
| `CDN_TIMEOUT` | **12.0** с |
| `MAX_NETWORK_RETRIES` | **2** (primary + 1 повтор) |
| `MAX_QUERY_ATTEMPTS` | **1** (только primary, без candid/finsta-цепочек) |
| `SEARCH_MAX_WORKERS` | **2** |
| `DOWNLOAD_CONCURRENCY` | **12** |
| `RELATED_DOWNLOAD_WORKERS` / `AI_CHECK_WORKERS` | **10** |
| `MAX_SEARCH_PINS` | **40** |
| `WARM_COOLDOWN_SEC` | **45.0** |

Параллельный harvest: `harvest_slides_parallel` → ThreadPoolExecutor с `workers = min(max_workers, SEARCH_MAX_WORKERS, n)`.  
Если ≥ половины слайдов пустые → sequential retry + `warm_session(force=True)`.  
Пустой search → warm + retry без токена `iphone`, затем ещё раз primary.

**Last-resort гарантия:** `guarantee_at_least_one` — цепочка `LAST_RESORT_QUERIES` с `ignore_used=True`; batch/GUI вызывают перед `No photos`. Падение только если Pinterest полностью мёртв.

### 2.3 Дедупликатор pin_id

- Внутренний бан-лист: `_used_pin_ids` + счётчик `_pin_use_counts`.
- **`mark_used` / run-level `used_pins_run`:** банятся **только финальные selected pin_id** (тот, что ушёл в `N.jpg`), **не** все скачанные и **не** alts.
- Комментарий в `batch_factory`: *«Отвергнутые alts / сырой пул в used_pins_run НЕ попадают»*.
- Перед каруселью: `reset_used()` + `seed_used(used_pins_run)` только finals прошлых каруселей.
- `_select_pins_avoiding_used`: предпочитает fresh; если все used — берёт least-used (не пустой список).
- Intra-carousel: `dedupe_carousel_pools` — уникальный pin на позиции selected между слайдами; если свободного нет — оставляет дубль с WARNING.
- Review «+ Ещё»: exclude = `pin_id` + `alt_pin_ids` + visual fingerprint файлов.

---

## 3. Скоринг и выбор

### 3.1 Формула final score

`core/harvester.py` → `candidate_final_score`:

```
final = relevance × 0.40 + taste × 0.35 + ugc × 0.25
```

Константы:

| Вес | Значение |
|-----|----------|
| `FINAL_REL_W` | **0.40** |
| `FINAL_TASTE_W` | **0.35** |
| `FINAL_UGC_W` | **0.25** |
| `FINAL_HARM_W` | **0.0** (harmony в сигнатуре, вес 0) |

`core/ugc_filter.py` → `final_rank_score`: та же формула при переданном `relevance`; legacy без relevance: `ugc×0.45 + taste×0.35`.

`taste=None` / untrained → **0.50**.

POV fashion: `POV_FASHION_UGC_MULT = 0.75` (−25% к ugc при full-body fashion).

### 3.2 Пороги отсева (soft / hard floors)

| Порог | Значение | Где |
|-------|----------|-----|
| `SELECT_RELEVANCE_MIN` / `TEXT_RELEVANCE_MIN` | **0.08** | harvester soft gate |
| `UGC_HARD_FLOOR` | **0.35** | harvester |
| `TASTE_HARD_FLOOR` | **0.32** | harvester |
| `ugc_filter.UGC_MIN_SCORE` | **0.35** | sync с HARD_FLOOR; сам harvest гейтит по HARD_FLOOR |
| `taste_classifier.TASTE_MIN_SCORE` | **0.60** | метаданные модели / trainer; **не** harvest hard floor |

Selectable после гейтов:  
`ugc ≥ 0.35` **и** `taste ≥ 0.32` **и** `rel ≥ 0.08`.

### 3.3 Emergency-keep — условия прохождения

Триггер: soft-gate обнулил пул (`score_candidates` / judge вернул пусто), есть уже скачанный `original_pool`.

Порядок в `rank_pool_emergency`:

1. Проставить rel / ugc / taste / combined на всём пуле (гейты не режут return).
2. `usable` = кадры с `rel ≥ EMERGENCY_REL_FLOOR` (**0.05**).  
   Если usable пуст → **fallback на весь `pre`** (не ронять слайд).
3. **Guarded path** (`selection_mode=emergency_guarded`, reason=`emergency keep (gates empty)`):  
   `ugc ≥ 0.35` **и** `taste ≥ 0.32` **и** `rel ≥ 0.05` → sort by combined → top `limit`.
4. Иначе **best-of-pool** (`emergency_best`): лучшие по `combined_score` из `pool_for_pick`, reason `emergency keep (best of pool)` или `… low rel`.
5. Абсолютный хвост: `return top if top else list(pre[:limit])`.
6. Если и скачиваний 0 → `guarantee_at_least_one` (last-resort search).

---

## 4. Рендер и UI

### 4.1 Renderer (`core/renderer.py`)

| Параметр | Значение |
|----------|----------|
| Разрешение | **1080 × 1440** (`SLIDE_W` / `SLIDE_H`) |
| Шрифт (приоритет) | `fonts/Montserrat-Bold.ttf` (авто-download), иначе TikTokSans-Bold / Inter-Bold / ProximaNova / DejaVu |
| `FONT_START` | **59** |
| `FONT_MIN` | **42** |
| `FONT_STEP` | **1** |
| `LINE_HEIGHT_RATIO` | **1.17** (gap ≈ 10 @ 59pt) |
| `TEXT_FILL` | `(255, 255, 255, 255)` #FFFFFF |
| `STROKE_FILL` | `(0, 0, 0, 255)` #000000 |
| Stroke base | **4** px если `font_size ≥ 48`, иначе **3** |
| Stroke +1 | если `zone_luma ≥ 140` (светлая зона) → фактически **4–5** |

Слоты текста: `top | mid | bot` (negative space).

### 4.2 Review panel (`review_panel.py`)

| Параметр | Значение |
|----------|----------|
| `MAX_SLIDES` | **9** |
| `FETCH_MORE_N` | **4** |
| `MAX_ALTS_SHOWN` | **16** |
| `ALT_COLS` | **4** (сетка: 4 фото в ряд, рост вниз, вертикальный скролл) |
| Alt thumb | 78×104 |

---

## 5. Сводка констант (quick ref)

```
CANDIDATES / CANDIDATES_PER_SLIDE = 10
MIN_KEEP = 3
MAX_ALTS_SAVED = 6
MAX_SLIDES (review) = 9

SELECT_RELEVANCE_MIN = 0.08
UGC_HARD_FLOOR = 0.35
TASTE_HARD_FLOOR = 0.32
EMERGENCY_REL_FLOOR = 0.05
EMERGENCY_UGC/TASTE = 0.35 / 0.32

final = rel×0.40 + taste×0.35 + ugc×0.25
harmony weight = 0

SEARCH_MAX_WORKERS = 2
MAX_QUERY_ATTEMPTS = 1
REQUEST_TIMEOUT = 20s
CDN_TIMEOUT = 12s

Render = 1080×1440 · Montserrat-Bold · font 59→42 · stroke ~4 black
Query clamp = 3–4 words · no iphone append · pose words kept
Dedupe ban = selected finals only
```

---

*Источник: актуальный код `core/llm_engine.py`, `core/harvester.py`, `core/batch_factory.py`, `core/ugc_filter.py`, `core/taste_classifier.py`, `core/renderer.py`, `review_panel.py`, `carousel_factory_app.py`.*
