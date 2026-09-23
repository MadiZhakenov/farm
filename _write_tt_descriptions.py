#!/usr/bin/env python3
"""Copy TT captions into sorted_carousels group folders."""

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
            print("skip", group_dir.name)
            continue
        man = json.loads(man_path.read_text(encoding="utf-8"))
        run = man.get("run") or ""
        blocks: list[str] = []
        missing = 0
        for car in man["carousels"]:
            n = int(car["sort"])
            topic = str(car.get("topic") or "").strip()
            src = DOCS / run / "approved" / car["source"] / "caption.txt"
            if src.exists():
                caption = src.read_text(encoding="utf-8").strip()
            else:
                caption = f"{topic}\n\n#fyp #selfgrowth #mindset"
                missing += 1
            (group_dir / f"sort_{n}_tt.txt").write_text(
                caption + "\n", encoding="utf-8"
            )
            blocks.append(
                f"===== sort_{n} =====\n"
                f"Topic: {topic}\n\n"
                f"{caption}\n"
            )
        (group_dir / "tt_descriptions.txt").write_text(
            "\n".join(blocks) + "\n", encoding="utf-8"
        )
        print(
            f"{group_dir.name}: 20 sort_N_tt.txt + tt_descriptions.txt "
            f"(missing_caption={missing})"
        )


if __name__ == "__main__":
    main()
