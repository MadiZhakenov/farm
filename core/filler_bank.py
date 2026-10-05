#!/usr/bin/env python3
"""
Банк филлеров батча (фидбек команды 2026-10-02).

Банк хранит уже прошедших все фильтры кандидатов по запросу филлера
(спокойные кадры «настроения»); следующая карусель с тем же запросом
берёт из банка ещё не использованные кадры, без поиска в Pinterest
(быстрее). Каждый кадр — не больше чем в MAX_REUSE каруселях: с 3 повторами
треть слайдов батча повторяла другие карусели (аудит 2026-10-05), поэтому 1.
Внутри карусели повтор исключают правила (core.carousel_rules).

Хранит свои копии картинок: карусель после рендера закрывает картинки
своих кандидатов, банк от этого не страдает.
"""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

MAX_REUSE = 1  # в скольких каруселях батча может стоять один кадр-филлер
# сколько каруселей может взять из банка один и тот же запрос — иначе весь
# батч сходится к одним сценам («ocean waves» / «knitting yarn» везде)
MAX_QUERY_REUSE = 3
MIN_SERVE = 2  # сколько свободных кадров нужно, чтобы слайд взять из банка
MAX_PER_QUERY = 8  # сколько кадров хранить на запрос
# Банк хранит только живые бытовые кадры (UGC-оценка пайплайна): сток в
# банке размножался по всему батчу (проверка 2026-10-02)
MIN_UGC = 0.55


def _pid(c: Any) -> str:
    return str(getattr(c, "pin_id", "") or "")


def _clone(c: Any) -> Any:
    dup = copy.copy(c)
    img = getattr(c, "image", None)
    if img is not None:
        try:
            dup.image = img.copy()
        except Exception:
            pass
    return dup


@dataclass
class FillerBank:
    max_reuse: int = MAX_REUSE
    min_serve: int = MIN_SERVE
    per_query: int = MAX_PER_QUERY
    max_query_reuse: int = MAX_QUERY_REUSE
    _by_query: dict[str, list[Any]] = field(default_factory=dict)
    _uses: Counter = field(default_factory=Counter)
    _query_uses: Counter = field(default_factory=Counter)
    hits: int = 0
    misses: int = 0

    @staticmethod
    def _key(query: str) -> str:
        return (query or "").strip().lower()

    def add(self, query: str, cands: Iterable[Any]) -> int:
        """Положить кандидатов филлер-слайда (по рангу). Возвращает сколько добавлено."""
        key = self._key(query)
        if not key:
            return 0
        bucket = self._by_query.setdefault(key, [])
        have = {_pid(c) for c in bucket}
        added = 0
        for c in cands:
            pid = _pid(c)
            if not pid or pid in have or getattr(c, "image", None) is None:
                continue
            if getattr(c, "ugc_scored", False) and float(c.ugc_score or 0) < MIN_UGC:
                continue
            if len(bucket) >= self.per_query:
                break
            bucket.append(_clone(c))
            have.add(pid)
            added += 1
        return added

    def available(self, query: str, exclude: Iterable[str] = ()) -> list[Any]:
        ex = {str(p) for p in exclude}
        return [
            c
            for c in self._by_query.get(self._key(query), [])
            if self._uses[_pid(c)] < self.max_reuse and _pid(c) not in ex
        ]

    def can_serve(self, query: str, exclude: Iterable[str] = ()) -> bool:
        if self._query_uses[self._key(query)] >= self.max_query_reuse:
            return False
        return len(self.available(query, exclude)) >= self.min_serve

    def ready_queries(self) -> list[str]:
        """Запросы, которые банк может обслужить прямо сейчас (реже
        использованные — первыми)."""
        ready = [q for q in self._by_query if self.can_serve(q)]
        return sorted(ready, key=lambda q: self._query_uses[q])

    def take(self, query: str, exclude: Iterable[str] = ()) -> list[Any]:
        """Копии свободных кадров (менее использованные — первыми)."""
        free = self.available(query, exclude)
        if not self.can_serve(query, exclude):
            self.misses += 1
            return []
        self.hits += 1
        self._query_uses[self._key(query)] += 1
        ranked = sorted(
            enumerate(free), key=lambda t: (self._uses[_pid(t[1])], t[0])
        )
        return [_clone(c) for _, c in ranked]

    def known_pins(self) -> set[str]:
        """Все pin банка."""
        return {_pid(c) for v in self._by_query.values() for c in v}

    def mark_used(self, pin_ids: Iterable[str]) -> None:
        for p in pin_ids:
            if p:
                self._uses[str(p)] += 1

    def stats(self) -> str:
        n = sum(len(v) for v in self._by_query.values())
        reused = sum(1 for v in self._uses.values() if v > 1)
        return (
            f"банк филлеров: {len(self._by_query)} запросов · {n} кадров · "
            f"из банка {self.hits} слайдов · повторно использовано {reused} кадров"
        )
