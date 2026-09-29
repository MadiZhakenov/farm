#!/usr/bin/env python3
"""Generate full auto-carousel system audit PDF (Russian)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out" / "audits"
OUT.mkdir(parents=True, exist_ok=True)
PDF_PATH = OUT / f"carousel_system_audit_{datetime.now():%Y%m%d_%H%M}.pdf"

pdfmetrics.registerFont(TTFont("Arial", r"C:\Windows\Fonts\arial.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Bold", r"C:\Windows\Fonts\arialbd.ttf"))
pdfmetrics.registerFont(TTFont("CourierRU", r"C:\Windows\Fonts\cour.ttf"))

NAVY = colors.HexColor("#1a2744")
ACCENT = colors.HexColor("#2c5f8a")
SOFT = colors.HexColor("#f4f6f9")
CODE_BG = colors.HexColor("#1e1e1e")
CODE_FG = colors.HexColor("#d4d4d4")
WARN = colors.HexColor("#8b3a3a")
OK = colors.HexColor("#2d6a4f")


def styles():
    base = getSampleStyleSheet()
    s = {
        "cover": ParagraphStyle(
            "cover",
            fontName="Arial-Bold",
            fontSize=22,
            leading=28,
            alignment=TA_CENTER,
            textColor=NAVY,
            spaceAfter=12,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub",
            fontName="Arial",
            fontSize=11,
            leading=16,
            alignment=TA_CENTER,
            textColor=ACCENT,
            spaceAfter=6,
        ),
        "h1": ParagraphStyle(
            "h1",
            fontName="Arial-Bold",
            fontSize=14,
            leading=18,
            textColor=NAVY,
            spaceBefore=16,
            spaceAfter=8,
            borderPadding=3,
        ),
        "h2": ParagraphStyle(
            "h2",
            fontName="Arial-Bold",
            fontSize=12,
            leading=15,
            textColor=ACCENT,
            spaceBefore=12,
            spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "h3",
            fontName="Arial-Bold",
            fontSize=10.5,
            leading=13,
            textColor=NAVY,
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="Arial",
            fontSize=9.5,
            leading=13,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            fontName="Arial",
            fontSize=9.5,
            leading=13,
            leftIndent=10,
            spaceAfter=2,
        ),
        "small": ParagraphStyle(
            "small",
            fontName="Arial",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#444444"),
        ),
        "code": ParagraphStyle(
            "code",
            fontName="CourierRU",
            fontSize=7.5,
            leading=9.5,
            textColor=CODE_FG,
            backColor=CODE_BG,
            leftIndent=4,
            rightIndent=4,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "caption": ParagraphStyle(
            "caption",
            fontName="Arial",
            fontSize=8,
            leading=10,
            textColor=ACCENT,
            spaceBefore=2,
            spaceAfter=6,
        ),
        "warn": ParagraphStyle(
            "warn",
            fontName="Arial",
            fontSize=9.5,
            leading=13,
            textColor=WARN,
            spaceAfter=6,
        ),
        "ok": ParagraphStyle(
            "ok",
            fontName="Arial-Bold",
            fontSize=9.5,
            leading=13,
            textColor=OK,
            spaceAfter=6,
        ),
        "toc": ParagraphStyle(
            "toc",
            fontName="Arial",
            fontSize=10,
            leading=14,
            leftIndent=8,
            spaceAfter=3,
        ),
    }
    return s


def P(text: str, style: ParagraphStyle) -> Paragraph:
    # Escape minimal XML for reportlab
    t = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    # allow intentional tags back
    for tag in ("b", "i", "br/"):
        t = t.replace(f"&lt;{tag}&gt;", f"<{tag}>").replace(
            f"&lt;/{tag}&gt;", f"</{tag}>"
        )
    t = t.replace("&lt;br/&gt;", "<br/>")
    return Paragraph(t, style)


def code_block(src: str, caption: str, st) -> list:
    # Keep ASCII-heavy code; Cyrillic comments ok in Courier
    clean = src.replace("\t", "    ").rstrip() + "\n"
    return [
        P(f"<b>Код:</b> {caption}", st["caption"]),
        Preformatted(clean, st["code"]),
    ]


def table(data, col_widths=None):
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Arial-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Arial"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), SOFT),
                ("TEXTCOLOR", (0, 1), (-1, -1), colors.black),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c5ced9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return t


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Arial", 8)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(1.8 * cm, 1.2 * cm, "Farm Auto-Carousel — полный аудит системы")
    canvas.drawRightString(
        A4[0] - 1.8 * cm, 1.2 * cm, f"стр. {doc.page}"
    )
    canvas.setStrokeColor(colors.HexColor("#cccccc"))
    canvas.line(1.8 * cm, 1.5 * cm, A4[0] - 1.8 * cm, 1.5 * cm)
    canvas.restoreState()


def build():
    st = styles()
    story = []

    # -------- COVER --------
    story.append(Spacer(1, 3.5 * cm))
    story.append(P("FARM AUTO-CAROUSEL", st["cover"]))
    story.append(P("Полный технический аудит системы", st["cover"]))
    story.append(Spacer(1, 0.6 * cm))
    story.append(
        P(
            "Как работает автоматизированная карусель от текста до JPG:<br/>"
            "поиск, скоринг, вкус, style-pivot, borderline vision, обучение моделей",
            st["cover_sub"],
        )
    )
    story.append(Spacer(1, 1.2 * cm))
    story.append(
        P(
            f"Дата среза кода: {datetime.now():%Y-%m-%d %H:%M}<br/>"
            f"Репозиторий: e:\\Users\\Desktop\\farm<br/>"
            f"Ветка: main (после коммита style-pivot / taste veto / borderline vision)",
            st["cover_sub"],
        )
    )
    story.append(Spacer(1, 2 * cm))
    story.append(
        P(
            "<b>Важно:</b> источник истины — live-код (core/harvester.py и соседние модули). "
            "Файлы вроде current_pipeline_state.md могут быть устаревшими.",
            st["body"],
        )
    )
    story.append(PageBreak())

    # -------- TOC --------
    story.append(P("Содержание", st["h1"]))
    toc = [
        "1. Что это за система (одной страницей)",
        "2. Точки входа",
        "3. Полный пайплайн стадий",
        "4. Карта модулей",
        "5. Контракт отбора и live-константы",
        "6. Запросы: forge, prop-lock, vibe-rescue, style-pivot",
        "7. Harvest: Pinterest → фильтры → скачивание",
        "8. Скоринг: SigLIP + UGC + вкус + финальная формула",
        "9. Пограничная зона UGC и vision (moondream)",
        "10. Guarantee / Completion / Nuclear",
        "11. Agent gate vs unsupervised batch",
        "12. Рендер и артефакты",
        "13. Модели, данные, обучение",
        "14. Риски, баги, рекомендации",
        "15. Шпаргалка формул",
    ]
    for line in toc:
        story.append(P(line, st["toc"]))
    story.append(PageBreak())

    # -------- 1 --------
    story.append(P("1. Что это за система", st["h1"]))
    story.append(
        P(
            "Система собирает вертикальные карусели (обычно 1080×1440) под confession / food-noise "
            "контент: генерирует тексты слайдов, ищет живые UGC-фото на Pinterest, отсекает сток, "
            "выбирает победителя на слайд и накладывает типографику.",
            st["body"],
        )
    )
    story.append(
        P(
            "Ключевая идея качества фото: <b>сначала правильный запрос и честный отказ от шлака</b>, "
            "потом модель. Если точный кадр не находится — система делает <b>облегчённый запрос "
            "под настроение текста</b> (style-pivot), а не «берём любое с UGC 0.32».",
            st["body"],
        )
    )
    story.append(
        P(
            "Есть два режима: <b>agent-gated</b> (человек/LLM смотрит пулы по слайдам) и "
            "<b>unsupervised batch</b> (полный автомат). Skill agent-curate-carousel запрещает "
            "слепые батчи, если цель — красивые фото.",
            st["body"],
        )
    )

    # -------- 2 --------
    story.append(P("2. Точки входа", st["h1"]))
    story.append(
        table(
            [
                [P("<b>Файл</b>", st["small"]), P("<b>Роль</b>", st["small"])],
                [
                    P("agent_gate.py", st["small"]),
                    P(
                        "Стадийный контроллер: new→text→queries→harvest-slide→pick→render. "
                        "Сессии в out/agent_sessions/",
                        st["small"],
                    ),
                ],
                [
                    P("live_one_carousel.py", st["small"]),
                    P("Один топик → run_batch → стоп", st["small"]),
                ],
                [
                    P("rerun_food_topics.py", st["small"]),
                    P("Пакет food-noise топиков → run_batch", st["small"]),
                ],
                [
                    P("carousel_factory_app.py", st["small"]),
                    P("Tkinter GUI поверх harvester/batch", st["small"]),
                ],
                [
                    P("core/batch_factory.py", st["small"]),
                    P("Ядро end-to-end: build_one_carousel / run_batch", st["small"]),
                ],
            ],
            col_widths=[4.2 * cm, 12.3 * cm],
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(
        P(
            "Skill: <b>.cursor/skills/agent-curate-carousel/SKILL.md</b> — обязательный SOP "
            "для агента: не гонять слепой batch; читать JPG пула перед pick.",
            st["body"],
        )
    )

    # -------- 3 --------
    story.append(P("3. Полный пайплайн стадий", st["h1"]))
    story.extend(
        code_block(
            """topic
  → TEXT        Gemini (llm_engine) — тексты + visual_scene + draft query
  → [approve text]          # только agent_gate / --llm
  → QUERIES     query_forge.own_slide_queries (prop-lock)
  → [approve queries]
  → HARVEST     Pinterest search + download (harvester)
  → SCORE       SigLIP rel + UGC blend + taste veto + borderline vision
  → PICK        agent: human/moondream | batch: argmax + harmony
  → RENDER      renderer → 1080x1440 JPG + meta.json""",
            "Порядок стадий (концептуально)",
            st,
        )
    )
    story.append(P("3.1 Batch (непрерывный)", st["h2"]))
    story.append(
        P(
            "SigLIP warm → generate_carousel → own_slide_queries → Pinterest preflight → "
            "harvest_slides_parallel → guarantee/style-pivot/completion → color harmony → "
            "atomic check (пустой слайд = RuntimeError) → render.",
            st["body"],
        )
    )
    story.append(P("3.2 Agent (с гейтами)", st["h2"]))
    story.append(
        P(
            "Тот же смысл, но harvest по одному слайду; pick ручной. "
            "Borderline vision в agent harvest-пути не главный гейт — качество зависит от "
            "просмотра пула / moondream pick.",
            st["body"],
        )
    )

    # -------- 4 --------
    story.append(P("4. Карта модулей", st["h1"]))
    mods = [
        ("core/harvester.py", "Поиск, скачивание, floors, judge, guarantee, completion"),
        ("core/query_forge.py", "Prop-lock, mood banks, style-pivot, vibe-rescue"),
        ("core/ugc_filter.py", "Zero-shot UGC↔stock + blend с supervised"),
        ("core/ugc_classifier.py", "LogReg live/stock → ugc_live_model.pkl"),
        ("core/taste_classifier.py", "Личный вкус → my_taste_model.pkl"),
        ("core/taste_embedder.py", "SigLIP/CLIP embeddings + text↔image"),
        ("core/local_gate.py", "Ollama qwen + moondream (pick / borderline)"),
        ("core/llm_engine.py", "Gemini: тексты карусели и сцены"),
        ("core/renderer.py", "Типографика 1080×1440"),
        ("core/photo_vault.py", "SQLite approve + permanent pin blacklist"),
        ("core/color_matcher.py", "Color harmony якорь слайда 1"),
        ("core/visual_judge.py", "Тонкая обёртка final_rank_score"),
        ("core/batch_factory.py", "Сборка карусели end-to-end"),
    ]
    story.append(
        table(
            [[P("<b>Модуль</b>", st["small"]), P("<b>Роль</b>", st["small"])]]
            + [[P(a, st["small"]), P(b, st["small"])] for a, b in mods],
            col_widths=[5.5 * cm, 11 * cm],
        )
    )
    story.append(PageBreak())

    # -------- 5 --------
    story.append(P("5. Контракт отбора и live-константы", st["h1"]))
    story.append(
        P(
            "Это «правила игры» для автоматического выбора фото. Менять без понимания "
            "эффектов нельзя — отсюда и качество карусели.",
            st["body"],
        )
    )
    story.extend(
        code_block(
            """# core/harvester.py (live)
STRICT_SELECTION_CONTRACT = True
COMPLETION_FILL_ENABLED = True

TASTE_ENABLED = True
TASTE_VETO_ONLY = True          # вкус = сторож, не рейтинг
FINAL_REL_W = 0.35
FINAL_TASTE_W = 0.0            # из-за VETO
FINAL_UGC_W = 0.65             # из-за VETO

UGC_HARD_FLOOR = 0.55
UGC_SOFT_FLOOR = 0.48
UGC_SOFT_REL_MIN = 0.30
UGC_VIBE_SOFT_FLOOR = 0.32
UGC_VIBE_SOFT_REL_MIN = 0.55

TASTE_HARD_FLOOR = 0.40
SELECT_RELEVANCE_MIN = 0.08

COMPLETION_UGC_FLOOR = 0.32
COMPLETION_REL_FLOOR = 0.05

BORDERLINE_VISION_ENABLED = True
BORDERLINE_VISION_FAIL_CLOSED = True
BORDERLINE_VISION_MAX = 6""",
            "Живой контракт отбора",
            st,
        )
    )
    story.append(P("5.1 Что значит STRICT + COMPLETION", st["h2"]))
    story.append(
        P(
            "STRICT выключает мягкие сдачи в обычном пути (pool_soft / guarantee_soft / soft-rel). "
            "COMPLETION_FILL оставляет last-mile путь, чтобы factory не отгрузила карусель "
            "с дыркой — но теперь перед soft идёт style-pivot с нормальным UGC.",
            st["body"],
        )
    )
    story.append(P("5.2 ugc_eligible — три полосы", st["h2"]))
    story.extend(
        code_block(
            """def ugc_eligible(ugc, rel, *, visual_scene="", query="", slide_text=""):
    if ugc >= 0.55:                          # hard
        return True
    if ugc >= 0.48 and rel >= 0.30:          # soft band
        return True
    if is_vibe_scene(...) and ugc >= 0.32 and rel >= 0.55:  # vibe soft
        return True
    return False

def ugc_is_borderline(...):
    # eligible ТОЛЬКО через soft/vibe (ugc < 0.55) → нужен vision KEEP
    ...""",
            "Полы живости (упрощённо)",
            st,
        )
    )

    # -------- 6 --------
    story.append(P("6. Запросы: forge, prop-lock, style-pivot", st["h1"]))
    story.append(
        P(
            "Модель выбирает только из того, что принёс Pinterest. Кривой запрос = красивый шлак. "
            "Поэтому query_forge жёстко держит prop из visual_scene и запрещает DNA-casting "
            "(blonde girl и т.п.) в строке поиска.",
            st["body"],
        )
    )
    story.append(P("6.1 Style-pivot (облегчение темы)", st["h2"]))
    story.append(
        P(
            "Если точный проп не дал живых фото — система не обязана изображать миндаль/quinoa. "
            "Она берёт <b>лёгкий запрос с кучей UGC</b>, подходящий по настроению текста: "
            "food_night, food_control, bed_spiral, desk_work, outside_night, body_gym, general.",
            st["body"],
        )
    )
    story.extend(
        code_block(
            """# core/query_forge.py — фрагмент банков
_EASY_MOOD_BANKS = {
  "food_night": (
    "open fridge night phone",
    "snack bags bed night",
    "kitchen counter night mess",
    "empty plate table night",
    ...
  ),
  "bed_spiral": (
    "phone on pillow night",
    "hands holding phone bed",
    ...
  ),
  "body_gym": (
    "sneakers by gym bag",
    "water bottle gym floor",
    ...
  ),
  "general": (...),
}

# Роутинг по ключевым словам текста → бакеты → style_pivot_queries()""",
            "Easy mood banks",
            st,
        )
    )
    story.append(
        P(
            "В guarantee_at_least_one порядок: prop vibe (hard) → <b>style-pivot (hard UGC)</b> → "
            "ignore_used → soft только после промаха pivot (completion).",
            st["body"],
        )
    )
    story.append(PageBreak())

    # -------- 7 --------
    story.append(P("7. Harvest: Pinterest → фильтры → скачивание", st["h1"]))
    story.append(
        P(
            "Harvester ищет пины, режет AI/title-blacklist/PhotoVault blacklist до скачивания, "
            "качает CDN, затем гоняет consistency gates (gender/DNA/no frontal faces на body slides) "
            "и скоринг.",
            st["body"],
        )
    )
    story.append(
        table(
            [
                [P("<b>Параметр</b>", st["small"]), P("<b>Значение</b>", st["small"])],
                [P("CANDIDATES_PER_SLIDE", st["small"]), P("10", st["small"])],
                [P("SLIDE_SEARCH_BUDGET", st["small"]), P("5", st["small"])],
                [P("GUARANTEE_MAX_SEARCHES", st["small"]), P("2", st["small"])],
                [P("SEARCH_MAX_WORKERS", st["small"]), P("3", st["small"])],
                [P("DOWNLOAD_CONCURRENCY", st["small"]), P("12", st["small"])],
                [P("MAX_QUERY_ATTEMPTS", st["small"]), P("1 (без candid-цепочек)", st["small"])],
            ],
            col_widths=[6 * cm, 10.5 * cm],
        )
    )
    story.append(Spacer(1, 0.25 * cm))
    story.append(
        P(
            "Post-download junk: wallpaper/gradient, крошечные/blurry, "
            "stock_pro_heuristic_penalty ≥ 0.34 → hard drop.",
            st["body"],
        )
    )

    # -------- 8 --------
    story.append(P("8. Скоринг", st["h1"]))
    story.append(P("8.1 Релевантность (SigLIP text↔image)", st["h2"]))
    story.append(
        P(
            "Строятся 1–2 текстовых якоря из visual_scene + vibe/prop. Считается max similarity "
            "картинки к якорям. Пол отбора SELECT_RELEVANCE_MIN = 0.08 (мягкий — известный риск offtopic).",
            st["body"],
        )
    )
    story.append(P("8.2 UGC score (живость)", st["h2"]))
    story.extend(
        code_block(
            """# core/ugc_filter.py — get_ugc_scores (упрощённо)
zs = softmax(best_ugc_sim, best_stock_sim, T=0.07)
zs -= stock_pro_heuristic_penalty(image)   # 0..0.40
if supervised_model_trained:
    score = 0.55 * P(live) + 0.45 * zs
else:
    score = zs""",
            "Blend supervised + zero-shot",
            st,
        )
    )
    story.append(P("8.3 Вкус = veto only", st["h2"]))
    story.append(
        P(
            "TasteClassifier считает score. Если &lt; 0.40 — DROP. В финальном ранге вес вкуса = 0, "
            "чтобы красивый сток снова не побеждал живое UGC (исторический «саботаж»).",
            st["body"],
        )
    )
    story.append(P("8.4 Финальная формула", st["h2"]))
    story.extend(
        code_block(
            """# LIVE при TASTE_VETO_ONLY=True
final = rel * 0.35 + taste * 0.0 + ugc * 0.65

# Кадр selectable только если:
#   ugc_eligible(...) AND taste >= 0.40 AND rel >= 0.08
#   AND (если borderline soft/vibe → moondream KEEP)""",
            "candidate_final_score / judge",
            st,
        )
    )
    story.append(
        P(
            "Порядок в judge_and_filter: junk → DNA/gender/faces → relevance → UGC → taste → "
            "combined_score → floors → borderline vision → argmax.",
            st["body"],
        )
    )

    # -------- 9 --------
    story.append(P("9. Пограничная зона и vision", st["h1"]))
    story.append(
        P(
            "Серая зона UGC (0.48–0.55 и vibe ~0.32) — там сидят и реальные ночные холодильники, "
            "и глянец. Формула больше не говорит «ок» автоматически.",
            st["body"],
        )
    )
    story.extend(
        code_block(
            """# core/local_gate.py — vision_borderline_is_live
# Moondream (Ollama). Ответ: KEEP 8 reason  /  DROP 2 reason
# KEEP со score < 5 → DROP
# Нет ollama / мусорный ответ → ok=False → fail-closed DROP

# core/harvester.py — _apply_borderline_vision
# Берёт до BORDERLINE_VISION_MAX=6 лучших borderline кадров
# Остальные за капом — DROP (не auto-pass soft)""",
            "Borderline vision contract",
            st,
        )
    )
    story.append(
        P(
            "Требование: ollama serve + модель moondream. Без них soft-band закрывается — "
            "система чаще уходит в style-pivot / completion.",
            st["warn"],
        )
    )
    story.append(PageBreak())

    # -------- 10 --------
    story.append(P("10. Guarantee / Completion / Nuclear", st["h1"]))
    story.append(
        table(
            [
                [P("<b>Шаг</b>", st["small"]), P("<b>Что делает</b>", st["small"])],
                [
                    P("1. Prop vibe-rescue", st["small"]),
                    P("Другие углы той же сцены, hard UGC", st["small"]),
                ],
                [
                    P("2. Style-pivot", st["small"]),
                    P(
                        "Кардинально другой лёгкий запрос под mood текста, hard UGC",
                        st["small"],
                    ),
                ],
                [
                    P("3. Soft completion", st["small"]),
                    P(
                        "Только если pivot не спас: COMPLETION_UGC_FLOOR=0.32, метка completion_fill",
                        st["small"],
                    ),
                ],
                [
                    P("4. Nuclear force_any", st["small"]),
                    P(
                        "Последний шанс: any non-junk; selection_mode=completion_nuclear",
                        st["small"],
                    ),
                ],
            ],
            col_widths=[4.5 * cm, 12 * cm],
        )
    )
    story.append(Spacer(1, 0.25 * cm))
    story.append(
        P(
            "В meta.json смотрите selection_mode. Значения completion_* / soft / emergency — "
            "сигнал «качество могло просесть».",
            st["body"],
        )
    )

    # -------- 11 --------
    story.append(P("11. Agent gate vs unsupervised batch", st["h1"]))
    story.append(
        table(
            [
                [
                    P("<b>Аспект</b>", st["small"]),
                    P("<b>Agent</b>", st["small"]),
                    P("<b>Batch</b>", st["small"]),
                ],
                [
                    P("Контроль", st["small"]),
                    P("Стоп после каждой стадии", st["small"]),
                    P("Полный автомат", st["small"]),
                ],
                [
                    P("Pick", st["small"]),
                    P("Человек / moondream", st["small"]),
                    P("Argmax + harmony", st["small"]),
                ],
                [
                    P("Taste + borderline", st["small"]),
                    P("Сильнее зависит от глаз", st["small"]),
                    P("Встроены в judge", st["small"]),
                ],
                [
                    P("Completion fill", st["small"]),
                    P("Нет (пусто → abort/re-query)", st["small"]),
                    P("Да (помечено в meta)", st["small"]),
                ],
                [
                    P("Skill", st["small"]),
                    P("Обязателен stage-by-stage", st["small"]),
                    P("Запрещён без явной просьбы", st["small"]),
                ],
            ],
            col_widths=[3.5 * cm, 6.5 * cm, 6.5 * cm],
        )
    )

    # -------- 12 --------
    story.append(P("12. Рендер и артефакты", st["h1"]))
    story.append(
        P(
            "renderer.render_slide: холст 1080×1440, safe margins, белый текст с чёрной обводкой, "
            "autofit, JPEG quality ~92.",
            st["body"],
        )
    )
    story.extend(
        code_block(
            """out/run_YYYYMMDD_HHMMSS/carousel_NNN/
  1.jpg … N.jpg
  alts/{i}_{j}.jpg
  meta.json          # topic, DNA, scores, selection_mode, pin_ids

out/agent_sessions/sess_*/
  texts.json, queries.json, slide_*/pool/, picks.json
  carousel/1.jpg…N.jpg + meta.json""",
            "Структура выходов",
            st,
        )
    )

    # -------- 13 --------
    story.append(P("13. Модели, данные, обучение", st["h1"]))
    story.append(
        table(
            [
                [P("<b>Артефакт</b>", st["small"]), P("<b>Путь / роль</b>", st["small"])],
                [
                    P("ugc_live_model.pkl", st["small"]),
                    P("data/ — supervised live vs stock", st["small"]),
                ],
                [
                    P("my_taste_model.pkl", st["small"]),
                    P("data/ — личный вкус (veto)", st["small"]),
                ],
                [
                    P("photo_vault.db", st["small"]),
                    P("data/ — approve + permanent blacklist", st["small"]),
                ],
                [
                    P("SigLIP", st["small"]),
                    P("google/siglip-base-patch16-224 (HF runtime)", st["small"]),
                ],
            ],
            col_widths=[4.5 * cm, 12 * cm],
        )
    )
    story.append(Spacer(1, 0.25 * cm))
    story.append(P("Обучение — что хорошо / плохо", st["h2"]))
    story.append(
        P(
            "<b>Хорошо:</b> train_ugc_from_probe.py (human ok/bad), "
            "train_ugc_from_taste_votes.py (human keep/stock/wrong).",
            st["ok"],
        )
    )
    story.append(
        P(
            "<b>Плохо / риск петли:</b> train_ugc_from_carousels.py — метки из ugc_score самой модели "
            "(учится подтверждать свои ошибки).",
            st["warn"],
        )
    )
    story.append(
        P(
            "Важно: голоса taste_votes часто кормят именно UGC-модель (живое/сток), а не обязательно "
            "переписывают my_taste_model. Вкус в карусели сейчас влияет как veto floor.",
            st["body"],
        )
    )
    story.append(PageBreak())

    # -------- 14 --------
    story.append(P("14. Риски, баги, рекомендации", st["h1"]))
    risks = [
        (
            "Completion soft всё ещё существует",
            "Может отгрузить слабый кадр с меткой completion_*. Смотреть meta.",
        ),
        (
            "SELECT_RELEVANCE_MIN = 0.08",
            "Очень мягко: живое, но не про тот предмет. Имеет смысл поднять для сильных prop.",
        ),
        (
            "Borderline fail-closed без Ollama",
            "Soft-band закрывается → больше pivot/completion. Держать moondream online.",
        ),
        (
            "Self-training carousels",
            "Не кормить ugc_live финалами без human labels.",
        ),
        (
            "Внутрикарусельный дедуп слабый",
            "Чёрный список пинов есть; похожие кухни разными pin_id могут повториться "
            "(эмбеддинг-дедуп — следующий приоритет).",
        ),
        (
            "Docstring drift",
            "Комментарии в candidate_final_score могут писать старые веса 0.30/0.30/0.40 — "
            "смотреть FINAL_*_W.",
        ),
        (
            "Agent vs batch gap",
            "Для красоты — agent_gate + чтение пула. Batch оптимизирует «сделать карусель».",
        ),
    ]
    for title, body in risks:
        story.append(P(f"<b>{title}</b>", st["h3"]))
        story.append(P(body, st["body"]))

    story.append(P("Рекомендуемый порядок следующих улучшений", st["h2"]))
    for i, line in enumerate(
        [
            "Эмбеддинг-дедуп похожих кадров внутри одной карусели",
            "Поднять пол релевантности для слайдов с сильным prop",
            "Учить UGC только human votes; переучить вкус на свежих keep/stock",
            "Мониторить долю selection_mode=completion_* в meta",
            "Не гонять rerun_food_topics без цели «скорость > красота»",
        ],
        1,
    ):
        story.append(P(f"{i}. {line}", st["bullet"]))

    # -------- 15 --------
    story.append(P("15. Шпаргалка формул", st["h1"]))
    story.extend(
        code_block(
            """STRICT=True  COMPLETION_FILL=True
TASTE_ENABLED=True  TASTE_VETO_ONLY=True

final = 0.35*rel + 0.0*taste + 0.65*ugc

UGC = 0.55*P(live) + 0.45*zs   # если pkl обучен
    = zs                         # иначе

DROP unless:
  ugc_eligible(ugc, rel)     # 0.55 | (0.48&rel0.30) | vibe(0.32&rel0.55)
  AND taste >= 0.40
  AND rel >= 0.08
  AND (borderline => moondream KEEP)

Empty after primary?
  prop vibe → style-pivot (easy mood) → soft completion → nuclear""",
            "Copy-paste шпаргалка",
            st,
        )
    )

    story.append(Spacer(1, 0.8 * cm))
    story.append(
        P(
            "Конец аудита. Файл сгенерирован скриптом build_carousel_audit_pdf.py. "
            "При смене констант в harvester.py — перегенерировать PDF.",
            st["small"],
        )
    )

    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.6 * cm,
        bottomMargin=2.0 * cm,
        title="Farm Auto-Carousel — полный аудит",
        author="Farm audit generator",
    )
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    return PDF_PATH


if __name__ == "__main__":
    path = build()
    print(f"OK -> {path}")
    print(f"size_kb = {path.stat().st_size / 1024:.1f}")
