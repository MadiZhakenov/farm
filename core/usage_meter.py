#!/usr/bin/env python3
"""
Учёт токенов и $ для Gemini (carousel / caption / optional vision).
Локальный Visual Judge (Ollama) логируется с cost=0.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = ROOT / "out" / "usage"

# gemini-3.1-flash-lite paid (USD per 1M tokens)
PRICE_IN_PER_M = 0.25
PRICE_OUT_PER_M = 1.50


@dataclass
class UsageEvent:
    ts: str
    kind: str  # gemini_text_gen | judge_local | session | …
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    note: str = ""
    estimated: bool = False


@dataclass
class UsageSnapshot:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    judge_local_calls: int = 0
    by_kind: dict[str, dict[str, float]] = field(default_factory=dict)

    def line(self) -> str:
        return (
            f"API ${self.cost_usd:.4f} · "
            f"in {self._fmt(self.input_tokens)} · "
            f"out {self._fmt(self.output_tokens)} · "
            f"calls {self.calls}"
            + (
                f" · judge0 {self.judge_local_calls}"
                if self.judge_local_calls
                else ""
            )
        )

    @staticmethod
    def _fmt(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.2f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}k"
        return str(n)


class UsageMeter:
    """Потокобезопасный счётчик сессии + JSONL на диск."""

    def __init__(self, log_dir: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._events: list[UsageEvent] = []
        self._listeners: list[Callable[[UsageEvent, UsageSnapshot], None]] = []
        self.log_dir = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._jsonl = self.log_dir / f"session_{self.session_id}.jsonl"
        self._started = time.perf_counter()

    def add_listener(
        self, cb: Callable[[UsageEvent, UsageSnapshot], None]
    ) -> None:
        with self._lock:
            self._listeners.append(cb)

    def reset_session(self, *, label: str = "") -> None:
        with self._lock:
            self._events.clear()
            self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._jsonl = self.log_dir / f"session_{self.session_id}.jsonl"
            self._started = time.perf_counter()
        note = f"session reset {label}".strip()
        self.record(
            kind="session",
            model="-",
            input_tokens=0,
            output_tokens=0,
            note=note or "session reset",
            billable=False,
        )

    def record(
        self,
        *,
        kind: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        note: str = "",
        estimated: bool = False,
        billable: bool = True,
    ) -> UsageEvent:
        inp = max(0, int(input_tokens or 0))
        out = max(0, int(output_tokens or 0))
        if billable and kind != "judge_local" and kind != "session":
            cost = (inp / 1_000_000.0) * PRICE_IN_PER_M + (
                out / 1_000_000.0
            ) * PRICE_OUT_PER_M
        else:
            cost = 0.0
        ev = UsageEvent(
            ts=datetime.now().isoformat(timespec="seconds"),
            kind=kind,
            model=model or "-",
            input_tokens=inp,
            output_tokens=out,
            cost_usd=round(cost, 8),
            note=note[:200],
            estimated=estimated,
        )
        with self._lock:
            self._events.append(ev)
            snap = self._snapshot_unlocked()
            listeners = list(self._listeners)
            path = self._jsonl
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(ev), ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("usage log write failed: %s", exc)

        logger.info(
            "USAGE %s %s in=%d out=%d $%.6f%s %s",
            kind,
            model,
            inp,
            out,
            cost,
            " ~est" if estimated else "",
            note,
        )
        for cb in listeners:
            try:
                cb(ev, snap)
            except Exception:
                pass
        return ev

    def snapshot(self) -> UsageSnapshot:
        with self._lock:
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> UsageSnapshot:
        by: dict[str, dict[str, float]] = {}
        inp = out = calls = judge_local = 0
        cost = 0.0
        for ev in self._events:
            if ev.kind == "session":
                continue
            bucket = by.setdefault(
                ev.kind, {"calls": 0, "in": 0, "out": 0, "usd": 0.0}
            )
            bucket["calls"] += 1
            bucket["in"] += ev.input_tokens
            bucket["out"] += ev.output_tokens
            bucket["usd"] += ev.cost_usd
            if ev.kind == "judge_local":
                judge_local += 1
            else:
                calls += 1
                inp += ev.input_tokens
                out += ev.output_tokens
                cost += ev.cost_usd
        return UsageSnapshot(
            calls=calls,
            input_tokens=inp,
            output_tokens=out,
            cost_usd=round(cost, 6),
            judge_local_calls=judge_local,
            by_kind=by,
        )

    def summary_dict(self) -> dict[str, Any]:
        snap = self.snapshot()
        return {
            "session_id": self.session_id,
            "pricing": {
                "model": "gemini-3.1-flash-lite",
                "input_per_1m_usd": PRICE_IN_PER_M,
                "output_per_1m_usd": PRICE_OUT_PER_M,
            },
            "totals": {
                "api_calls": snap.calls,
                "input_tokens": snap.input_tokens,
                "output_tokens": snap.output_tokens,
                "cost_usd": snap.cost_usd,
                "judge_local_calls": snap.judge_local_calls,
            },
            "by_kind": snap.by_kind,
            "elapsed_sec": round(time.perf_counter() - self._started, 1),
            "log_file": str(self._jsonl),
        }

    def write_summary(self, path: Path | None = None) -> Path:
        snap_path = path or (self.log_dir / f"session_{self.session_id}_summary.json")
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(
            json.dumps(self.summary_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return snap_path


_METER: UsageMeter | None = None
_METER_LOCK = threading.Lock()


def get_meter() -> UsageMeter:
    global _METER
    with _METER_LOCK:
        if _METER is None:
            _METER = UsageMeter()
        return _METER


def estimate_tokens(text: str) -> int:
    """Грубая оценка, если usageMetadata нет (EN ≈ 4 chars/token)."""
    return max(1, len(text or "") // 4)


def extract_usage_from_sdk(response: Any) -> tuple[int, int, bool]:
    """Вернуть (input, output, estimated)."""
    um = getattr(response, "usage_metadata", None)
    if um is None:
        return 0, 0, True
    inp = int(
        getattr(um, "prompt_token_count", None)
        or getattr(um, "promptTokenCount", None)
        or 0
    )
    out = int(
        getattr(um, "candidates_token_count", None)
        or getattr(um, "candidatesTokenCount", None)
        or 0
    )
    thoughts = int(getattr(um, "thoughts_token_count", None) or 0)
    out += thoughts
    if inp or out:
        return inp, out, False
    return 0, 0, True


def extract_usage_from_http(data: dict[str, Any]) -> tuple[int, int, bool]:
    um = data.get("usageMetadata") or data.get("usage_metadata") or {}
    inp = int(um.get("promptTokenCount") or um.get("prompt_token_count") or 0)
    out = int(
        um.get("candidatesTokenCount") or um.get("candidates_token_count") or 0
    )
    thoughts = int(um.get("thoughtsTokenCount") or um.get("thoughts_token_count") or 0)
    out += thoughts
    if inp or out:
        return inp, out, False
    return 0, 0, True


def record_gemini(
    *,
    kind: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    note: str = "",
    estimated: bool = False,
) -> UsageEvent:
    return get_meter().record(
        kind=kind,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        note=note,
        estimated=estimated,
        billable=True,
    )


def record_local_judge(*, model: str = "moondream", note: str = "") -> UsageEvent:
    return get_meter().record(
        kind="judge_local",
        model=model,
        input_tokens=0,
        output_tokens=0,
        note=note,
        billable=False,
    )
