# Farm — Carousel Factory

Пайплайн для сборки Instagram/TikTok-каруселей: текст → Pinterest-фото → фильтры вкуса → рендер → ревью.

**Hot path:**  
`topic → Gemini (слайды + search_query) → Pinterest harvest → SigLIP / UGC / harmony → render → review`

Репозиторий **private**. Секреты и тяжёлые медиа в git не входят (см. ниже).

---

## Быстрый старт

```bash
# 1. Клон
git clone https://github.com/MadiZhakenov/farm.git
cd farm

# 2. Python 3.11+ и зависимости
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt

# 3. Ключи
copy .env.example .env
# впиши GEMINI_API_KEY в .env

# 4. (опционально) Playwright для браузерных скриптов
playwright install chromium

# 5. Главное приложение
python carousel_factory_app.py
```

Для локального Visual Judge без API (по умолчанию в `.env.example`):

```bash
# поставь Ollama и модель, например moondream
# VISUAL_JUDGE_BACKEND=ollama
```

`torch` для SigLIP/CLIP ставь отдельно (CPU или CUDA), чтобы не затереть свою GPU-сборку.

---

## Основные приложения

| Команда | Назначение |
|---------|------------|
| `python carousel_factory_app.py` | GUI фабрики каруселей (GEMINI + Pinterest + рендер) |
| `python review_panel.py` | Быстрый отсмотр `out/run_*/carousel_*` |
| `python taste_trainer_app.py` | Разметка вкуса (локальный SigLIP + LogisticRegression) |
| `python story_overlay.py` | Оверлеи для сторис |
| `python compose.py` | Композиция / монтаж слайдов |

Пакетная сборка живёт в `core/batch_factory.py` (вызывается из фабрики).

### Chrome-расширение (Google Flow)

См. [`extension/README.md`](extension/README.md): bulk-генерация картинок в [Google Flow](https://labs.google/fx/tools/flow).

```
chrome://extensions → Developer mode → Load unpacked → farm/extension
```

---

## Структура

```
farm/
├── carousel_factory_app.py   # главный GUI
├── review_panel.py           # ревью готовых каруселей
├── taste_trainer_app.py      # обучение вкуса
├── core/                     # движок пайплайна
│   ├── llm_engine.py         # Gemini / Ollama тексты и search_query
│   ├── harvester.py          # Pinterest harvest + query sanitize
│   ├── visual_judge.py       # ранжирование кандидатов
│   ├── renderer.py           # типографика на фото
│   ├── batch_factory.py      # пакетная сборка
│   ├── taste_*.py            # эмбеддинги и классификатор вкуса
│   └── ...
├── extension/                # Farm Flow — Chrome extension
├── extension-lab/            # лабораторные скрипты (без node_modules/профилей)
├── assets/                   # кисти, hairlines, pillows, products
├── fonts/                    # TikTok Sans и др.
├── keyframes/                # референсные кадры
├── requirements.txt
└── .env.example
```

Локально (не в git) появляются тяжёлые каталоги: `out/`, `output/`, `downloaded_carousels/`, `data/` и т.д.

---

## Переменные окружения

Скопируй `.env.example` → `.env`:

| Переменная | Описание |
|------------|----------|
| `GEMINI_API_KEY` | Обязателен для генерации текстов карусели |
| `VISUAL_JUDGE_BACKEND` | `ollama` (локально) или Gemini fallback |
| `VISUAL_JUDGE_MODEL` | например `moondream` |
| `OLLAMA_HOST` | по умолчанию `http://127.0.0.1:11434` |

**Никогда не коммить `.env`.**

---

## Что не в репозитории

Исключено через `.gitignore`:

- `.env` и секреты
- `.browser_session/`, Chrome-профили (`extension-lab/profile`, `extension-lab/farm`)
- `downloaded_carousels/`, `output/`, `out/`, `data/`
- `before after/`, `competitors_collection/`, `curated_collection/`
- `node_modules/`, `__pycache__/`, `_refs/`, временные `_test*`

После клона тяжёлые датасеты и прогоны нужно восстановить локально или собрать заново через пайплайн.

---

## Зависимости (кратко)

- **Gemini** (`google-genai`) — тексты слайдов и search queries  
- **Pinterest harvest** (`httpx` / Playwright) — кандидаты фото  
- **SigLIP / transformers / scikit-learn** — вкус и фильтры  
- **Pillow / OpenCV** — рендер и обработка изображений  
- **Tkinter** — GUI (обычно в стандартной поставке Python на Windows)

Подробности пайплайна: `current_pipeline_state.md`.
