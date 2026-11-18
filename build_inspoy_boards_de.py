#!/usr/bin/env python3
"""1345 Inspoy outfit boards (11 с) — немецкая версия (срочно, 10 шт.): только текст на 8 с переведён.
  python build_inspoy_boards_de.py -n 10 --id de --seed 4945 --sound downloads/inspoy_found/music/ref_sound.mp3"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_inspoy_boards_reels as I  # noqa: E402
I.TEXT = ["hab das alles in Inspoy gefunden:", "Outfit Maker, Planner", "und übrigens", "am Abend vorher geplant"]
I.OUT = ROOT / "output" / "urgent_30" / "DE"
if __name__ == "__main__":
    raise SystemExit(I.main())
