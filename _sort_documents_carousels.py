#!/usr/bin/env python3
"""Sort Documents run_* carousels into 5 topic groups (20×6 flat files)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

DOCS = Path(r"E:/Users/Documents")
OUT = DOCS / "sorted_carousels"

GROUPS = [
    {
        "name": "01_psychology_selfesteem",
        "label": "Психология, загоны и самооценка (1-20)",
        "run": "run_20260923_105846",
    },
    {
        "name": "02_relationships_boundaries",
        "label": "Отношения, границы и переписки (21-40)",
        "run": "run_20260923_112821",
    },
    {
        "name": "03_girl_lifestyle_aesthetic",
        "label": "Девчачий лайфстайл, уют и эстетика (41-60)",
        "run": "run_20260923_125848",
    },
    {
        "name": "04_focus_productivity",
        "label": "Фокус, лень и продуктивность (61-80)",
        "run": "run_20260923_121650",
    },
    {
        "name": "05_health_sleep_body",
        "label": "Здоровье, сон, тело и ЖКТ (81-100)",
        "run": "run_20260923_132538",
    },
]


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    summary: list[dict] = []
    alts_deleted = 0

    for g in GROUPS:
        src_appr = DOCS / g["run"] / "approved"
        cars = sorted(
            [d for d in src_appr.iterdir() if d.is_dir()],
            key=lambda p: p.name,
        )
        if len(cars) != 20:
            raise SystemExit(f"{g['run']}: expected 20, got {len(cars)}")

        dest = OUT / g["name"]
        dest.mkdir()
        (dest / "GROUP.txt").write_text(g["label"] + "\n", encoding="utf-8")

        group_meta: list[dict] = []
        for i, car in enumerate(cars, start=1):
            topic = car.name
            meta_path = car / "meta.json"
            if meta_path.exists():
                try:
                    md = json.loads(meta_path.read_text(encoding="utf-8"))
                    topic = str(md.get("topic") or topic)
                except Exception:
                    pass

            slides: list[str] = []
            for s in range(1, 7):
                src = None
                for ext in (".jpg", ".jpeg", ".png", ".webp"):
                    cand = car / f"{s}{ext}"
                    if cand.exists():
                        src = cand
                        break
                if src is None:
                    raise SystemExit(f"Missing slide {s} in {car}")
                out_name = f"sort_{i}_{s}_id{src.suffix.lower()}"
                shutil.copy2(src, dest / out_name)
                slides.append(out_name)

            group_meta.append(
                {
                    "sort": i,
                    "topic": topic,
                    "source": car.name,
                    "files": slides,
                }
            )

            alts = car / "alts"
            if alts.exists() and alts.is_dir():
                shutil.rmtree(alts)
                alts_deleted += 1

        (dest / "manifest.json").write_text(
            json.dumps(
                {
                    "group": g["label"],
                    "run": g["run"],
                    "carousels": group_meta,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        n_files = len(list(dest.glob("sort_*")))
        print(f"{g['name']}: {n_files} photos from {g['run']}")
        summary.append(
            {
                "folder": g["name"],
                "label": g["label"],
                "photos": n_files,
                "run": g["run"],
            }
        )

    lines = [
        "Группы тем (по 20 каруселей × 6 слайдов = 120 файлов в папке)",
        "Имена: sort_{N}_{S}_id.jpg  N=карусель 1..20, S=слайд 1..6",
        "",
    ]
    for m in summary:
        lines.append(f"{m['folder']}: {m['label']} ({m['photos']} files)")
    (OUT / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"DONE out={OUT}")
    print(f"alts deleted from sources: {alts_deleted}")


if __name__ == "__main__":
    main()
