#!/usr/bin/env python3
"""
Проверка Ollama и скачивание модели qwen2.5:7b для Carousel Factory.

Запуск:
  python setup_ollama.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

OLLAMA_HOST = "http://127.0.0.1:11434"
MODEL_NAME = "qwen2.5:7b"
VISION_MODEL = "moondream"  # Visual Judge (локально, $0)
TIMEOUT = 30.0


def _ollama_exe() -> str | None:
    which = shutil.which("ollama")
    if which:
        return which
    candidate = (
        Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
    )
    if candidate.is_file():
        return str(candidate)
    return None


def check_service() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


def list_models() -> list[str]:
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return [str(m.get("name") or "") for m in (data.get("models") or [])]
    except Exception:
        return []


def model_ready(names: list[str], want: str = MODEL_NAME) -> bool:
    want_base = want.split(":")[0]
    for name in names:
        if name == want or name.startswith(want_base + ":"):
            return True
    return False


def pull_via_api(name: str = MODEL_NAME) -> bool:
    print(f"→ Скачивание через API: POST /api/pull {{name: {name!r}}}")
    try:
        with httpx.stream(
            "POST",
            f"{OLLAMA_HOST}/api/pull",
            json={"name": name},
            timeout=None,
        ) as resp:
            if resp.status_code >= 400:
                print(f"  HTTP {resp.status_code}")
                return False
            last_status = ""
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    chunk: dict[str, Any] = json.loads(line)
                except json.JSONDecodeError:
                    continue
                status = str(chunk.get("status") or "")
                if status and status != last_status:
                    completed = chunk.get("completed")
                    total = chunk.get("total")
                    if completed is not None and total:
                        pct = 100.0 * float(completed) / float(total)
                        print(f"  {status}  {pct:.0f}%")
                    else:
                        print(f"  {status}")
                    last_status = status
                if chunk.get("error"):
                    print(f"  ERROR: {chunk['error']}")
                    return False
        return True
    except Exception as exc:
        print(f"  API pull failed: {exc}")
        return False


def pull_via_cli(name: str = MODEL_NAME) -> bool:
    exe = _ollama_exe()
    if not exe:
        print("  ollama.exe не найден в PATH / Local\\Programs\\Ollama")
        return False
    print(f"→ Скачивание через CLI: {exe} pull {name}")
    try:
        proc = subprocess.run(
            [exe, "pull", name],
            check=False,
        )
        return proc.returncode == 0
    except Exception as exc:
        print(f"  CLI pull failed: {exc}")
        return False


def ensure_model(want: str, label: str) -> int:
    """0=ok already, 1=pulled ok, 2=fail."""
    names = list_models()
    if model_ready(names, want):
        print(f"\n[OK] {label}: {want} uzhe gotova")
        return 0
    print(f"\n[>>] {label}: {want} ne naydena — skachivaem...")
    ok = pull_via_api(want) or pull_via_cli(want)
    if not ok:
        print(f"\n[FAIL] Ne udalos skachat {want}")
        return 2
    if model_ready(list_models(), want):
        print(f"\n[OK] Gotovo: {want}")
        return 1
    print(f"\n[WARN] Pull {want} zavershilsya, no model ne vidna v /api/tags")
    return 2


def main() -> int:
    # Windows console (cp1251) — без emoji
    print("=" * 56)
    print("  Carousel Factory · Ollama setup")
    print(f"  Host:   {OLLAMA_HOST}")
    print(f"  Text:   {MODEL_NAME}")
    print(f"  Vision: {VISION_MODEL}  (Visual Judge)")
    print("=" * 56)

    if not check_service():
        print("\n[FAIL] Ollama ne otvechaet na", OLLAMA_HOST)
        print("       Zapustite: ollama serve")
        print("       ili otkroyte prilozhenie Ollama.")
        return 1

    print("\n[OK] Servis Ollama zapuschen")
    names = list_models()
    if names:
        print("   Ustanovlennye modeli:")
        for n in names:
            print(f"     - {n}")
    else:
        print("   Modeley poka net")

    text_rc = ensure_model(MODEL_NAME, "Text")
    vision_rc = ensure_model(VISION_MODEL, "Vision Judge")
    if text_rc == 2 or vision_rc == 2:
        return 1

    print("\n[OK] Setup complete")
    print("     Zapusk: python carousel_factory_app.py")
    print(f"     Judge model: {VISION_MODEL} (VISUAL_JUDGE_MODEL)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
