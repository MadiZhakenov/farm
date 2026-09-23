#!/usr/bin/env python3
"""
Color Matcher — быстрый анализ палитры на чистом Pillow.

Профиль с 64×64 превью (~1–3 мс): яркость, теплота, насыщенность, mood.
Harmony Score 0–100% — насколько кандидат совпадает с якорным слайдом.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

PROFILE_SIZE = 64
# Разница гармонии > 45 п.п. → аномалия (score < 55)
ANOMALY_SCORE_MAX = 55.0

# Веса штрафа: температура и яркость важнее; RGB ловит кислотные выбросы
_W_LUMA = 0.25
_W_WARMTH = 0.25
_W_SAT = 0.15
_W_RGB = 0.35
_MOOD_PENALTY = 0.06
_ACID_SAT_PENALTY = 0.12


def get_color_profile(image: Image.Image) -> dict[str, Any]:
    """
    Сжимает копию до 64×64 и считает цветовой профиль.

    Returns:
      luminance  — 0..255 (формула BT.601)
      warmth     — (R-B)/255, >0 тёплый, <0 холодный
      saturation — средний (max-min)/255
      mean_r/g/b — средние каналы 0..255
      mood       — warm_vintage | cool_minimal | dark_moody | bright_clean
    """
    small = image.convert("RGB").resize(
        (PROFILE_SIZE, PROFILE_SIZE),
        Image.Resampling.BILINEAR,
    )
    pixels = small.getdata()
    n = PROFILE_SIZE * PROFILE_SIZE

    sum_l = 0.0
    sum_warm = 0.0
    sum_sat = 0.0
    sum_r = 0.0
    sum_g = 0.0
    sum_b = 0.0
    for r, g, b in pixels:
        sum_r += r
        sum_g += g
        sum_b += b
        sum_l += 0.299 * r + 0.587 * g + 0.114 * b
        sum_warm += (r - b) / 255.0
        mx = r if r > g else g
        if b > mx:
            mx = b
        mn = r if r < g else g
        if b < mn:
            mn = b
        sum_sat += (mx - mn) / 255.0

    luminance = sum_l / n
    warmth = sum_warm / n
    saturation = sum_sat / n
    mean_r = sum_r / n
    mean_g = sum_g / n
    mean_b = sum_b / n
    mood = _mood_from_metrics(luminance, warmth)

    return {
        "luminance": luminance,
        "warmth": warmth,
        "saturation": saturation,
        "mean_r": mean_r,
        "mean_g": mean_g,
        "mean_b": mean_b,
        "mood": mood,
    }


def _mood_from_metrics(luminance: float, warmth: float) -> str:
    if luminance < 75.0:
        return "dark_moody"
    if luminance > 185.0:
        return "bright_clean"
    if warmth >= 0.04:
        return "warm_vintage"
    if warmth <= -0.04:
        return "cool_minimal"
    return "bright_clean" if luminance >= 130.0 else "dark_moody"


def get_harmony_score(
    profile_anchor: dict[str, Any],
    profile_candidate: dict[str, Any],
) -> float:
    """
    Взвешенная близость палитр → Harmony Score 0..100%.

    Штраф сильнее за перепад температуры (warmth) и яркости;
    RGB-дистанция ловит неоновые/кислотные аномалии.
    """
    if not profile_anchor or not profile_candidate:
        return 0.0

    dl = abs(
        float(profile_anchor["luminance"]) - float(profile_candidate["luminance"])
    ) / 255.0

    # warmth ∈ примерно [-1, 1] → нормализуем разницу к [0, 1]
    dw = abs(
        float(profile_anchor["warmth"]) - float(profile_candidate["warmth"])
    ) / 2.0
    dw = min(1.0, dw)

    ds = abs(
        float(profile_anchor["saturation"]) - float(profile_candidate["saturation"])
    )
    ds = min(1.0, ds)

    # евклидово расстояние средних RGB / diag(255√3)
    dr = float(profile_anchor.get("mean_r", 0)) - float(
        profile_candidate.get("mean_r", 0)
    )
    dg = float(profile_anchor.get("mean_g", 0)) - float(
        profile_candidate.get("mean_g", 0)
    )
    db = float(profile_anchor.get("mean_b", 0)) - float(
        profile_candidate.get("mean_b", 0)
    )
    rgb_dist = (dr * dr + dg * dg + db * db) ** 0.5 / 441.67295593  # 255*sqrt(3)
    # нелинейно: далёкие палитры падают быстрее (кислотный зелёный vs кофе)
    rgb_dist = min(1.0, rgb_dist ** 0.85)

    penalty = (
        _W_LUMA * dl
        + _W_WARMTH * dw
        + _W_SAT * ds
        + _W_RGB * rgb_dist
    )
    if profile_anchor.get("mood") != profile_candidate.get("mood"):
        penalty += _MOOD_PENALTY
    # приглушённый якорь + кислотно-насыщенный кандидат
    if (
        float(profile_anchor["saturation"]) < 0.42
        and float(profile_candidate["saturation"]) > 0.55
    ):
        penalty += _ACID_SAT_PENALTY

    score = (1.0 - min(1.0, penalty)) * 100.0
    return round(max(0.0, min(100.0, score)), 1)


def is_color_anomaly(score: float, threshold: float = ANOMALY_SCORE_MAX) -> bool:
    """True, если разница с якорем > ~45% (harmony ниже порога)."""
    return score < threshold


def rank_by_harmony(
    profiles: list[dict[str, Any]],
    anchor: dict[str, Any],
) -> tuple[list[int], list[float]]:
    """
    Сортирует индексы кандидатов: лучшая гармония первая,
    аномалии (score < 55) — в конце списка.

    Returns:
      (order_indices, scores_in_original_order)
    """
    scores = [get_harmony_score(anchor, p) for p in profiles]
    normal = [i for i, s in enumerate(scores) if not is_color_anomaly(s)]
    anomalies = [i for i, s in enumerate(scores) if is_color_anomaly(s)]
    normal.sort(key=lambda i: scores[i], reverse=True)
    anomalies.sort(key=lambda i: scores[i], reverse=True)
    return normal + anomalies, scores
