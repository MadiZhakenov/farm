# UGC Reels Pipeline — handoff для другого ИИ

Документ для агента, который должен **спокойно повторять** сборку UGC-рилов в этом репо так же, как уже настроено. Не изобретай параллельный пайплайн. Не гоняй слепой e2e-батч без проверки текста/клипов.

Repo root: `E:\Users\Desktop\farm`  
OS: Windows. Shell: PowerShell. Python 3 + `ffmpeg` в PATH. Ключевые зависимости: `opencv-python`, `numpy`, `Pillow`.

---

## 0. Два продукта — два трека

| Трек | Игра / тема | Сырьё | Клипы | Тексты | Аудио | Сборка |
|------|-------------|-------|-------|--------|-------|--------|
| **Magic Sort** (default) | парень сортирует игру | `downloads/raw_materials/` | `output/clips_ugc/` girl **1s** + guy **2s** | `c:\Users\User\Downloads\текста.txt` (или `--texts`) | `downloads/instagram_*.mp3` | `assemble_ugc_reels.py` |
| **Cozy Home** (`--cozy`) | девушка раскрашивает | `downloads/raw_materials_cozy/` | `output/clips_ugc_cozy/` guy **1s** + girl **2s** | `downloads/teksta_parnya.txt` | `downloads/audio_new/*.mp3` | `assemble_ugc_reels.py --cozy` |

Длительность готового рила всегда **6.0 с** (4 клипа: 1+2+1+2 или 2+1+2+1). Разрешение **1080×1920**.

Готовые батчи (пример):
- `output/ugc_reels_200/` — Magic Sort ×200
- `output/ugc_reels_cozy_200/` — Cozy ×200

`output/` в gitignore — артефакты локальные.

---

## 0.1 Цвет / «перенасыщенность» (ОБЯЗАТЕЛЬНО)

Сырьё с iPhone часто **HDR HLG**: `color_transfer=arib-std-b67`, `bt2020`, 10-bit HEVC.  
Если после cut/assemble в 8-bit H.264 **оставить HLG-теги**, у коллег на телефоне / в Telegram / MPC (H/W) весь кадр (видео + текст + **эмодзи**) выглядит кислотным. На ноуте, где теги игнорят, «всё норм» — отсюда путаница.

**Мы сами saturation не крутили.** Баг = лживые HDR-метаданные на SDR-пикселях.

### Правило пайплайна
- Всегда писать честные SDR-теги: `bt709` / `bt709` / `bt709`, `color_range=tv`.
- Модуль: `core/ugc_color.py` → `vf_scale_crop_fps_sdr`, `overlay_filter_sdr`, `SDR_COLOR_ARGS`, `vf_retag_sdr`.
- Уже вшито в `cut_ugc_clips.py`, `cut_ugc_clips_cozy.py`, `assemble_ugc_reels.py`.
- **Не использовать tonemap/hable/zscale→linear** для уже собранных 8-bit рилов — делает ещё насыщеннее. Только retag: те же пиксели + bt709.

### Проверка
```powershell
ffprobe -v quiet -print_format json -show_streams -select_streams v:0 FILE.mp4
# нужно: color_transfer=bt709, color_primaries=bt709, color_space=bt709 (или bt709 / unknown но НЕ arib-std-b67)
```

### Фикс уже готового батча / rar
Пережать mp4 без tonemap (`vf_retag_sdr` + `SDR_COLOR_ARGS`), затем пересобрать rar.  
Скрипт-прецедент: `output/_fix_all_batches_sdr_retag.py`.  
Тест, который ок у коллег: `output/_hdr_tests/PROBE_for_colleagues.mp4` (retag only).  
Плохой тест (не повторять): `PROBE_sdr_one.mp4` (tonemap).

Перед сдачей батча: выборочно `ffprobe` на 2–3 файла — нигде не должно быть `arib-std-b67`.

---

## 1. Порядок работы (всегда так)

```
raw MOV → cut_* → pools mp4 → assemble_ugc_reels → batch folder + manifest.json
```

1. Положить/проверить сырьё в нужный `raw_materials*`.
2. Нарезать клипы (`cut_ugc_clips*.py`).
3. Проверить пулы (хватает girl/guy, роли не перепутаны).
4. Проверить **текстовый файл** (нумерация `1. …`, без баннеров секций, нужный POV).
5. Собрать маленький тест `-n 5`, глянуть кадр.
6. Только потом `-n 200` в отдельную `--out` папку.

**Не** пересобирай весь батч из‑за 5–10 битых текстов — чини только их (см. §7).

---

## 2. Нарезка клипов

### Magic Sort
```powershell
cd E:\Users\Desktop\farm
python cut_ugc_clips.py
# опции: --dry-run  --thumbs  --min-score 0.55
```
Выход:
- `output/clips_ugc/girl_1s/*.mp4`
- `output/clips_ugc/guy_2s/*.mp4`
- `output/clips_ugc/manifest.json`

Роли сырья зашиты в `SOURCE_ROLES` в скрипте (`IMG_6418/6419*` = guy, `6424/6425` = girl). Новый файл → **добавь в `SOURCE_ROLES`**, не угадывай на лету.

### Cozy Home
```powershell
python cut_ugc_clips_cozy.py
# опции: --dry-run  --thumbs  --min-score 0.48
```
Выход:
- `output/clips_ugc_cozy/guy_1s/*.mp4`  (реакция лица ~1s)
- `output/clips_ugc_cozy/girl_2s/*.mp4` (игра/раскраска ~2s)
- `output/clips_ugc_cozy/manifest.json`

Роли: см. `SOURCE_ROLES` в `cut_ugc_clips_cozy.py` (`guy` / `girl` / `both`).

OpenCV скорит окна (лицо / руки / стабильность). Не понижай `--min-score` «чтобы набрать побольше» без просмотра thumbs.

---

## 3. Сборка рилов

Скрипт: `assemble_ugc_reels.py`.

### Паттерны монтажа
- **GUGU** = girl → guy → girl → guy  
- **UGUG** = guy → girl → guy → girl  
- По умолчанию `--gugu-pct 0.30` → ~30% GUGU / ~70% UGUG.

Для **Cozy** логика та же, но длительности обратные (guy 1s / girl 2s), поэтому UGUG = реакция → игра → реакция → игра — основной «уютный» ритм.

### Magic Sort ×200
```powershell
python assemble_ugc_reels.py -n 200 --out E:\Users\Desktop\farm\output\ugc_reels_200 --seed 42
```
Тексты по умолчанию: `DEFAULT_TEXTS` = `c:\Users\User\Downloads\текста.txt`.

### Cozy ×200
```powershell
python assemble_ugc_reels.py --cozy -n 200 --out E:\Users\Desktop\farm\output\ugc_reels_cozy_200 --seed 42
```
Тексты: `downloads/teksta_parnya.txt`. Аудио: все `downloads/audio_new/*.mp3`.

### Тест на 5
```powershell
python assemble_ugc_reels.py --cozy -n 5 --out E:\Users\Desktop\farm\output\ugc_reels_cozy_test --seed 1
```

Каждый прогон пишет `manifest.json` рядом с mp4:
```json
{
  "file": "001_gugu.mp4",
  "pattern": "GUGU",
  "clips": ["...mp4", "..."],
  "audio": "...mp3",
  "text": "первые ~160 символов…"
}
```
`text` в манифесте **обрезан** — для поиска мусора в конце оверлея смотри полный текст из source-файла или кадр из видео.

---

## 4. Текст на экране (критично)

### Формат файла
```
1. confession paragraph here...

2. next confession...
```
Парсер: `load_texts()` сплитит по `(?m)^\s*(\d+)\.\s+`.

### Обязательный стрип баннеров
В файл **нельзя** оставлять редакционные заголовки — раньше они прилипали к телу соседнего номера и сгорали в оверлей, например:
```
=================== ЧАСТЬ 2: БРАТ И СЕСТРА (48–100) ===================
```
В коде уже есть защита:
- `strip_section_banners()` при загрузке и в `sanitize_overlay_text()` перед PNG.
Всё равно **чисти source-файл**. Хелпер: `downloads/_clean_teksta_parnya.py`.

### POV
- **Cozy / teksta_parnya**: guy-POV про девушку / girlfriend / «she». Тексты вида **`my sister`** (POV брата) на кадрах пары — ошибка продукта. Лучше не пускать в пул или заменить при фиксе.
- Упоминание *her sister* как третьего лица (у girlfriend стресс из‑за сестры) — ок.
- **Magic Sort**: тексты про парня / игру / «he» под guy-клипы.

### Blocklist
В `assemble_ugc_reels.py`: `TEXT_BLOCKLIST_IDS` (сейчас `#48` funeral) + keyword-блок (funeral, death, suicide, …).  
`--no-id-blocklist` снимает только id-блок, keywords остаются.

### Эмодзи
Не Windows Segoe. Рендер пастит **Apple PNG** из `assets/emoji_apple_64/` (CDN fallback в коде). Квадраты/tofu = проблема шрифта, не «починка» Segoe.

### Визуал текста
Белый fill + чёрный stroke, safe zones top/bottom, узкий блок (~68% ширины), подгон размера шрифта 48→28. Не ломай `render_text_png` без нужды.

---

## 5. Жёсткие правила монтажа

1. **Один угол парня в одном ролике.** `pick_guys()`: клипы `IMG_6418*` **нельзя** мешать с другими guy-источниками в одном timeline (другой ракурс).
2. Внутри одного рила 2 girl + 2 guy клипа — `random.sample` / пул одного угла.
3. Аудио лупится и режется до 6s; видео silent concat → overlay PNG → aac.
4. Не коммить `output/`, `downloads/*.mp4|mp3|mov`, `*.rar` — они в `.gitignore`.

---

## 6. Типичные команды проверки

```powershell
# сколько клипов в пулах
(Get-ChildItem output\clips_ugc_cozy\guy_1s\*.mp4).Count
(Get-ChildItem output\clips_ugc_cozy\girl_2s\*.mp4).Count

# кадр из готового рила
ffmpeg -y -ss 1.5 -i output\ugc_reels_cozy_200\005_ugug.mp4 -frames:v 1 output\_check.jpg
```

Ищи в оверлее: кириллические `ЧАСТЬ` / `БРАТ`, `====`, tofu-эмодзи, неверный POV.

Поиск заражённых по манифесту (если баннер в начале текста) или по префиксу чистого тела текста #N из source.

---

## 7. Чинить только битые (не весь батч)

Если 5–20 роликов с плохим текстом:

1. Найди их по `manifest.json` + полному тексту из source.
2. Возьми **те же** `clips` + `audio` из манифеста.
3. Пережги только текст:
   - `concat_clips` → `render_text_png(clean_text)` → `burn_text_and_audio` → тот же `file` в out-папке.
4. Обнови поле `text` в манифесте.
5. Импорты уже есть в `assemble_ugc_reels.py` — не копируй ffmpeg-логику заново.

Пример прецедента: баннер «ЧАСТЬ 2…» прилип к тексту **#47** → затронуты только ролики с этим телом (у cozy_200 было 10, у ugc_reels_200 — 6).

---

## 8. Что другому ИИ **нельзя** делать

- Слепо `assemble -n 200` без проверки текстов/пулов.
- Подмешивать Segoe / системный emoji font вместо Apple PNG.
- Оставлять в txt строки `ЧАСТЬ…` / `====…` / `PART N:`.
- Перемешивать 6418 guy с другими guy в одном риле.
- Путать треки: Cozy texts на Magic Sort клипы и наоборот (если юзер не просил).
- Коммитить тонны медиа / rar / `story_usage.json`.
- «Исправлять» батч полной пересборкой, когда достаточно re-burn текста.
- Менять длительности паттерна (1s/2s) без явного запроса — это продукт.
- Отдавать рилы с `color_transfer=arib-std-b67` / bt2020-тегами на 8-bit H.264.
- «Чинить» цвет через `tonemap=hable` / агрессивный zscale на уже готовых 8-bit батчах (станет ещё насыщеннее). Только retag → bt709.
- Считать MPC/Telegram «сломанными», если на ноуте ок: сначала `ffprobe` теги.

---

## 9. Карта файлов

| Путь | Зачем |
|------|--------|
| `cut_ugc_clips.py` | Нарезка Magic Sort |
| `cut_ugc_clips_cozy.py` | Нарезка Cozy |
| `assemble_ugc_reels.py` | Сборка + текст PNG + burn |
| `core/ugc_color.py` | SDR bt709 tags (анти-перенасыщенность) |
| `core/renderer.py` | Шрифты / stroke helpers |
| `downloads/teksta_parnya.txt` | Cozy confessions |
| `downloads/_clean_teksta_parnya.py` | Нормализация списка текстов |
| `assets/emoji_apple_64/` | Эмодзи для оверлея |
| `output/clips_ugc*/` | Пулы клипов |
| `output/ugc_reels*/` | Готовые рилы + manifest |

---

## 10. Чеклист перед сдачей батча юзеру

- [ ] `-n 5` тест просмотрен (кадр / пара роликов)
- [ ] В оверлее нет `ЧАСТЬ` / `====` / кириллических заголовков
- [ ] POV совпадает с картинкой (Cozy ≠ brother/sister POV)
- [ ] Эмодзи не квадраты
- [ ] `ffprobe`: нет `arib-std-b67` / bt2020 на готовых mp4 (нужен bt709)
- [ ] Папка `--out` отдельная, старый батч не затёрт случайно
- [ ] `manifest.json` на месте
- [ ] Правки точечные, если баг только в тексте
- [ ] Если коллеги жалуются на «кислоту»/эмодзи — сначала теги, не крутить saturation вручную

---

## 11. Стиль работы с юзером этого репо

- Юзер пишет коротко по-русски; отвечай коротко, без воды.
- «Исправь только их» = только listed/matched файлы.
- Сначала найди и покажи масштаб (N файлов), потом чини.
- Не пушь в remote без просьбы; коммить только когда просят.
- Не трогай gitignore-медиа и не раздувай diff.

Если чего-то нет в этом файле — читай код `assemble_ugc_reels.py` / `cut_ugc_clips*.py`, не выдумывай второй пайплайн.
