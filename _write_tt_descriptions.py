#!/usr/bin/env python3
"""One tt_descriptions.txt per group with all 20 captions + hashtags."""

from __future__ import annotations

import json
from pathlib import Path

DOCS = Path(r"E:/Users/Documents")
OUT = DOCS / "sorted_carousels"


def main() -> None:
    for group_dir in sorted(OUT.iterdir()):
        if not group_dir.is_dir():
            continue
        man_path = group_dir / "manifest.json"
        if not man_path.exists():
            continue
        man = json.loads(man_path.read_text(encoding="utf-8"))
        run = man.get("run") or ""

        # remove per-carousel tt files
        for old in group_dir.glob("sort_*_tt.txt"):
            old.unlink()

        blocks: list[str] = []
        for car in man["carousels"]:
            n = int(car["sort"])
            topic = str(car.get("topic") or "").strip()
            src = DOCS / run / "approved" / car["source"] / "caption.txt"
            if src.exists():
                caption = src.read_text(encoding="utf-8").strip()
            else:
                caption = f"{topic}\n\n#fyp #selfgrowth #mindset"
            blocks.append(f"{n}.\n{caption}")

        text = "\n\n".join(blocks) + "\n"
        out_path = group_dir / "tt_descriptions.txt"
        out_path.write_text(text, encoding="utf-8")
        print(f"{group_dir.name}: wrote {out_path.name} ({len(blocks)} captions)")


if __name__ == "__main__":
    main()
