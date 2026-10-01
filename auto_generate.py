#!/usr/bin/env python3
"""
Автогенерация каруселей без GUI (тот же пайплайн, что «Запустить фабрику»).

  python auto_generate.py                      # темы из topics.txt, по 1 карусели на тему
  python auto_generate.py "тема" -n 5          # 5 вариаций одной темы
  python auto_generate.py --topics-file my.txt
  python auto_generate.py --loop 60            # повторять каждые 60 минут

Результат: out/run_<время>/carousel_*  (смотреть: python review_panel.py)
Лог последнего запуска: out/auto_last.log
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class _Tee:
    """Дублирует stdout/stderr в out/auto_last.log (UTF-8)."""

    def __init__(self, stream, fh):
        self._s, self._f = stream, fh

    def write(self, data):
        try:
            self._s.write(data)
        except Exception:
            pass
        self._f.write(data)
        self._f.flush()
        return len(data)

    def flush(self):
        try:
            self._s.flush()
        except Exception:
            pass
        self._f.flush()

    def __getattr__(self, name):
        return getattr(self._s, name)


(ROOT / "out").mkdir(exist_ok=True)
_LOG_FH = open(ROOT / "out" / "auto_last.log", "w", encoding="utf-8")
sys.stdout = _Tee(sys.stdout, _LOG_FH)
sys.stderr = _Tee(sys.stderr, _LOG_FH)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from core.batch_factory import run_batch  # noqa: E402
from core.harvester import PinterestHarvester  # noqa: E402
from core.llm_engine import OllamaGenerator  # noqa: E402
from core.usage_meter import get_meter  # noqa: E402

OUT_DIR = ROOT / "out"
DEFAULT_TOPICS = ROOT / "topics.txt"


def _log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def read_topics(path: Path) -> list[str]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        t = line.strip()
        if t and not t.startswith("#"):
            out.append(t)
    return out


def run_once(topics: list[str], count: int, product: str) -> int:
    llm = OllamaGenerator()
    if not llm.is_available():
        _log("GEMINI_API_KEY не задан. Впиши ключ в файл .env (GEMINI_API_KEY=...).")
        return 2
    harvester = PinterestHarvester(on_status=_log)
    multi = len(topics) > 1
    get_meter().reset_session(label=f"auto x{len(topics) if multi else count}")

    def on_done(i: int, tot: int, folder: Path) -> None:
        _log(f"готово {i}/{tot}: {folder}")

    try:
        if multi:
            res = run_batch(
                topics=topics, product=product, count=1, out_root=OUT_DIR,
                llm=llm, harvester=harvester, on_status=_log, on_carousel_done=on_done,
            )
            total = len(topics)
        else:
            res = run_batch(
                topic=topics[0], product=product, count=count, out_root=OUT_DIR,
                llm=llm, harvester=harvester, on_status=_log, on_carousel_done=on_done,
            )
            total = count
    finally:
        try:
            harvester.close()
        except Exception:
            pass
    _log(f"ИТОГ: {res.made}/{total} каруселей, fail={res.failed}, skip={res.skipped} -> {res.run_dir}")
    return 0 if res.made else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Автогенерация каруселей")
    ap.add_argument("topic", nargs="?", default="", help="одна тема (иначе topics.txt)")
    ap.add_argument("-n", "--count", type=int, default=1, help="вариаций одной темы (1-50)")
    ap.add_argument("--topics-file", type=Path, default=DEFAULT_TOPICS)
    ap.add_argument("--product", default="", help="продукт/решение (опционально)")
    ap.add_argument("--loop", type=float, default=0, help="повторять каждые N минут")
    a = ap.parse_args(argv)

    topics = [a.topic.strip()] if a.topic.strip() else read_topics(a.topics_file)
    if not topics:
        _log(f"Нет тем: передай тему аргументом или заполни {a.topics_file.name}")
        return 2
    count = max(1, min(50, a.count))

    while True:
        rc = run_once(topics, count, a.product)
        if not a.loop or rc == 2:
            return rc
        _log(f"следующий прогон через {a.loop:g} мин (Ctrl+C — стоп)")
        time.sleep(a.loop * 60)


if __name__ == "__main__":
    raise SystemExit(main())
