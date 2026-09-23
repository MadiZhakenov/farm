# Audit: UGC / «живость» фото — сухой срез кода

Дата среза: 2026-09-22. Источник: текущий код в репозитории + `out/carousel_20260921_*/meta.json`.

---

## 1. Текстовые промпты Pinterest (`core/llm_engine.py`, `core/query_patterns.py`)

### 1.1 Системный промпт — блок `search_query` (дословно из `build_system_prompt`)

```
=== PROVEN PINTEREST TAXONOMY (search_query) ===
{pinterest_rule}

search_query (per slide, required on EVERY slide):
- HARD LIMIT: each search_query MUST be EXACTLY 2–4 English words (never 5+).
- MUST pick the closest proven tag from the viral taxonomy above for the slide niche/subject.
- Real-life photo scenes only. No empty rooms, ceilings, lightbulbs, blinds, wallpapers, gradients, vectors.
- No product names in queries.
- FORBIDDEN: tag spam, full sentences, stock words, "photo dump", "candid 35mm film".

=== LOGICAL OBJECT MATCHING (Strict Rule) ===
1. TANGIBLE OBJECTS: If the slide mentions a physical object, food, action, or setting
   (e.g., 'chips', 'kitchen', 'fridge', 'mirror', 'sneakers', 'tea', 'phone'):
   The search query MUST directly reflect that real subject!
   Example: 'eating a bag of chips in the dark' -> 'chips snack night aesthetic'
   Example: 'late-night kitchen trip' -> 'kitchen fridge open night'
   NEVER replace food/kitchen with study desks or books!
2. ABSTRACT THOUGHTS: Only if the slide is purely abstract/emotional
   ('stop judging yourself', 'inner peace'):
   Use ambient atmospheric moodboards
   (e.g. 'soft evening window', 'dim room lamp').
Length: strictly 2–4 words.
PRIORITY: tangible object on the slide > niche geography defaults.

=== PHYSICAL ENVIRONMENT RULES (STRICT geography — anti mono-bed) ===
When the slide has NO concrete object/food/setting, bind search_query to niche location.
HARD BAN (unless topic is literally sleep / waking / insomnia / bedtime):
  NEVER use: bed, bedroom, duvet, sheets, blanket.
Skincare / Beauty (abstract slides only): bathroom, vanity, sink, mirror, serum.
Relationships / Dating / Anxiety (abstract slides only): cafe, car, street, rain, window.
Productivity / Study (abstract slides only): desk, library, journal — BUT if the slide
  names chips/kitchen/fridge/food, search THAT object, never a book desk.
Fitness: gym / mirror selfie / protein — never bed.
Sleep topics ONLY may use bed/bedroom scenes.
NEVER default unrelated niches to a bedroom photo.
```

`{pinterest_rule}` = `QueryPatternManager.get_top_archetypes_summary()` (`core/query_patterns.py`). Живой вывод на момент аудита:

```
PROVEN PINTEREST TAXONOMY (Strictly 2-4 words per query):
When generating `search_query` for each slide, use our proven subculture codes matching the slide's niche (3179 labeled backgrounds, 86 clean tags):
- Fitness: 'gym girl aesthetic', 'aesthetic yoga home', 'aesthetic yoga practice', 'protein shake gym'
- Skincare/Beauty: 'glow skin routine', 'skincare mirror selfie', 'clean girl vanity', 'clean girl skincare'
- Study/Intellectual: 'dark academia aesthetic', 'aesthetic journaling pov', 'aesthetic book reading pov', 'cozy study aesthetic'
- Cozy/Bed: 'golden hour aesthetic', 'golden hour kitchen', 'cozy study aesthetic', 'messy bed aesthetic'
- Relationships/Night: 'couple aesthetic', 'couple cozy aesthetic', 'relationship couple candid', 'vintage couple snow'
- Career: 'laptop window view', 'aesthetic laptop workspace', 'dark academia desk', 'surreal office mountain'
RULE: Combine [1 core object] + [1 proven tag].
Example: 'rory gilmore aesthetic', 'gym mirror selfie', 'clean girl skincare', 'book on bed aesthetic'.
NEVER write sentences. Max 3-4 words.
```

### 1.2 User-prompt (дословно, часть про query)

```
Each search_query: STRICTLY 2–4 words.
LOGICAL OBJECT MATCHING: if the slide names a real object/food/setting
(chips, kitchen, fridge, mirror, sneakers, tea, phone) — query MUST mirror it
(chips→'chips snack night'; kitchen→'kitchen fridge night').
NEVER replace food/kitchen with study desks or books.
Abstract-only slides may use ambient moodboards.
Niche defaults (vanity/cafe/desk) ONLY when no tangible object is present.
BAN bed/bedroom/duvet/sheets/blanket unless topic is sleep/waking.
NO full sentences, NO photo dump / candid 35mm film, NO stock words.
```

### 1.3 Что код реально дописывает / вычищает (не промпт)

| Место | Поведение |
|--------|-----------|
| `UGC_QUERY_MARKERS` | `("cozy", "aesthetic", "night", "candid")` — **не дописываются** в query (`_scrub_query`: `del preferred_marker  # больше не дописываем длинные маркеры`). Напротив, маркеры **вырезаются** в `_strip_ugc_and_legacy_tails` через `*UGC_QUERY_MARKERS`. |
| `_clamp_query_to_word_limit` | Жёстко **2–4 слова**; режет `35mm/film/dump/candid/snapshot`, `shot on iphone`, `photo dump`, … |
| `_scrub_query` | Tangible remap (`_extract_tangible_query`); `_force_geography_query`; бан `BANNED_STOCK_QUERY_TERMS` / face / dead objects; без auto-suffix UGC. |
| `finalize_photo_query` (`harvester`) | Clamp **3–5 слов**; fillers если мало слов: `cozy`, `aesthetic`, `night`, `lifestyle`, `vibes`; scrub legacy (`photo dump`, `candid 35mm film`, …). |
| `AUTHENTIC_PHOTO_MARKERS` (`harvester`) | `("cozy", "aesthetic", "candid", "iphone")` — комментарий в коде: **legacy; НЕ дописывать** в короткий query. |
| `BANNED_QUERY_TERMS` (`harvester`) | `cinematic`, `studio`, `editorial`, `35mm film`, `photoshoot`, … |

---

## 2. Математика UGC-фильтра (`core/ugc_filter.py`)

### 2.1 Anchors (дословно)

```python
UGC_ANCHOR = (
    "an unedited casual snapshot taken on an iPhone camera, authentic UGC photo dump, "
    "raw candid mobile photo, spontaneous real life snapshot"
)
STOCK_ANCHOR = (
    "a polished commercial stock photograph, staged studio photoshoot with three-point lighting, "
    "corporate shutterstock photo, editorial magazine shoot, 3d render"
)
```

### 2.2 Формула `ugc_score`

Константа: `SOFTMAX_TEMP = 0.07` (`τ = 0.07`).

Эмбеддинги: L2-нормированные SigLIP/CLIP (`TasteEmbedder.embed_images` / `embed_texts`).

```
sim_ugc   = img_vec · ugc_vec      # косинус (= dot при ||v||=1)
sim_stock = img_vec · stock_vec

ugc_score = softmax2(sim_ugc, sim_stock, τ)
          = exp(sim_ugc/τ − m) / (exp(sim_ugc/τ − m) + exp(sim_stock/τ − m))
где m = max(sim_ugc/τ, sim_stock/τ)
```

Код: `_softmax2` + `get_ugc_scores`.

### 2.3 Жёсткий порог

```python
UGC_MIN_SCORE = 0.55
```

В `harvester._apply_ugc_gate`: если есть кандидаты с `ugc_score >= 0.55` — оставляются только они; если **все** `< 0.55` — пул **не обнуляется**, сортировка по `ugc_score` (soft rank).

---

## 3. Ранжирование и фильтры (`core/harvester.py`)

### 3.1 `final_score` (актуальная формула)

```python
TEXT_RELEVANCE_MIN = 0.18
FINAL_REL_W = 0.50
FINAL_UGC_W = 0.30
FINAL_HARM_W = 0.20

# candidate_final_score:
final_score = relevance * 0.50 + ugc * 0.30 + (harmony / 100) * 0.20
```

**`taste` в `final_score` не входит.**

Legacy (если `relevance is None`) в `ugc_filter.final_rank_score`:

```
ugc * 0.45 + taste * 0.35 + (harmony/100) * 0.20
```

### 3.2 Порядок фильтров после скачивания (`judge_and_filter`)

1. **Анти-мусор** — `is_junk_candidate_image` (wallpaper / gradient / 3D / letterbox) → hard drop  
2. **Text↔image relevance** — `_apply_text_relevance_gate`  
   - текст скоринга: `build_relevance_text(slide_text, query)`  
   - score: SigLIP `sigmoid(cos * exp(logit_scale) + logit_bias)` (`taste_embedder._cosine_to_prob`)  
   - drop если `text_relevance < 0.18`  
3. **UGC** — `_apply_ugc_gate` (`UGC_MIN_SCORE = 0.55`, soft если все ниже)  
4. **Taste** — `_apply_taste_gate` (`TASTE_MIN_SCORE = 0.60` из `taste_classifier.py`)  
   - hard drop только если после порога остаётся ≥1; иначе soft rank  
5. **Harmony** — `_score_harmony(anchor)` → `harmony_score` 0..100  
6. **Sort** по `candidate_final_score(text_relevance, ugc_score, harmony_score)`

Перед этим: Pinterest search → `filter_ai` (digitalMediaSourceType / junk titles) → полный `asyncio.gather` CDN.

### 3.3 Пороги

| Метрика | Константа | Значение | Поведение |
|---------|-----------|----------|-----------|
| relevance | `TEXT_RELEVANCE_MIN` | **0.18** | hard drop |
| ugc | `UGC_MIN_SCORE` | **0.55** | hard если есть survivors; иначе soft |
| taste | `TASTE_MIN_SCORE` | **0.60** | hard если есть survivors; иначе soft |
| taste в final_score | — | **нет веса** | только gate / UI |

---

## 4. Реальные цифры из артефактов

`text_relevance` в `meta.json` **не пишется** (поле отсутствует во всех проверенных экспортах).

### 4.1 `out/carousel_20260921_154506/meta.json` (selected per slide)

| slide | query | ugc_score | taste_score | harmony_score |
|------:|-------|----------:|------------:|--------------:|
| 1 | passenger seat night | 0.7499 | 0.8571 | 100.0 |
| 2 | minimalist desk open journal | 0.6733 | 0.4203 | 70.1 |
| 3 | wine glass night | 0.6929 | 0.5305 | 95.7 |
| 4 | walking city street | 0.7640 | 0.8246 | 73.1 |
| 5 | coffee shop table | **0.4942** | 0.5601 | 86.1 |
| 6 | hands phone lamp night | 0.8904 | 0.9289 | 94.7 |

### 4.2 `out/carousel_20260921_154232/meta.json`

| slide | query | ugc_score | taste_score | harmony_score |
|------:|-------|----------:|------------:|--------------:|
| 1 | kitchen fridge open | 0.6775 | 0.5657 | 100.0 |
| 2 | dim room lamp | 0.6129 | 0.4329 | 77.4 |
| 3 | kitchen fridge food | 0.5515 | 0.3998 | 92.7 |
| 4 | kitchen fridge open | **0.4985** | 0.5021 | 72.2 |
| 5 | laptop desk lamp | 0.5948 | 0.3891 | 91.3 |
| 6 | kitchen fridge open | 0.5389 | 0.5205 | 87.9 |

### 4.3 `out/carousel_20260921_151730/meta.json`

| slide | query | ugc_score | taste_score | harmony_score |
|------:|-------|----------:|------------:|--------------:|
| 1 | two coffee cups | 0.8165 | 0.7040 | 100.0 |
| 2 | rain soaked window | 0.8621 | 0.6517 | 85.2 |
| 3 | cafe table view | 0.7205 | 0.8311 | 92.7 |
| 4 | two coffee cups cafe | 0.8648 | 0.6498 | 93.0 |
| 5 | quiet street evening | 0.7636 | 0.7315 | 81.1 |
| 6 | hands phone lamp | 0.8850 | 0.8776 | 85.3 |

### 4.4 Сводка ugc на попавших в слайды картинках (3 карусели выше)

- min ugc: **0.4942** (ниже порога 0.55 — следствие soft-pass когда hard-survivors=0 / старый rescue)  
- max ugc: **0.8904**  
- типичный диапазон: **~0.55–0.89**

### 4.5 Relevance (runtime-диагностика 2026-09-22, не в meta)

После калибровки SigLIP sigmoid (`compute_text_image_relevance`):

- query `kitchen fridge night` vs скачанные kitchen-кадры: probs ≈ **0.70–0.96** (все ≥ 0.18)  
- mismatch `chips snack bag night` vs те же kitchen-кадры: probs ≈ **0.0**  
- до калибровки сырой cosine был ≈ **0.12–0.14** → ложный hard-drop при пороге 0.18

---

## 5. Константы — шпаргалка

```
UGC_ANCHOR / STOCK_ANCHOR     → ugc_filter.py
SOFTMAX_TEMP                 = 0.07
UGC_MIN_SCORE                = 0.55
TASTE_MIN_SCORE              = 0.60
TEXT_RELEVANCE_MIN           = 0.18
final_score                  = 0.50*rel + 0.30*ugc + 0.20*(harm/100)
taste в final_score          = 0 (не участвует)
UGC_QUERY_MARKERS auto-append = НЕТ (вырезаются)
search_query word limit      = 2–4 (llm scrub) / 3–5 (finalize_photo_query)
```
