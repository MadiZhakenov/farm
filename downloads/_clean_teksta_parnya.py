#!/usr/bin/env python3
"""Normalize teksta_parnya.txt into a clean numbered list."""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent / "teksta_parnya.txt"


def main() -> None:
    raw = SRC.read_text(encoding="utf-8-sig")
    raw = re.sub(r"(?m)^\s*=+\s*.*?\s*=+\s*$", "", raw)
    raw = (
        raw.replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u00a0", " ")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\ufeff", "")
    )

    parts = re.split(r"(?m)^\s*(\d+)\.\s+", raw)
    items: list[tuple[int, str]] = []
    i = 1
    while i + 1 < len(parts):
        try:
            n = int(parts[i])
        except ValueError:
            i += 1
            continue
        body = re.sub(r"\s+", " ", parts[i + 1]).strip()
        if body:
            items.append((n, body))
        i += 2

    ids = [n for n, _ in items]
    missing = [x for x in range(1, 101) if x not in set(ids)]
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    print(f"count={len(items)} range={ids[0]}..{ids[-1]} unique={len(set(ids))}")
    print(f"missing={missing} dupes={dupes}")

    by_id = {n: body for n, body in items}
    out_lines = [f"{n}. {by_id[n]}" for n in sorted(by_id)]
    clean = "\n\n".join(out_lines) + "\n"

    bak = SRC.with_suffix(".txt.bak")
    if not bak.exists():
        bak.write_bytes(SRC.read_bytes())
        print(f"backup: {bak.name}")

    SRC.write_text(clean, encoding="utf-8", newline="\n")
    weird = sorted({(hex(ord(c)), c) for c in clean if ord(c) > 127})
    print(f"wrote {SRC} ({SRC.stat().st_size} bytes)")
    print(f"remaining non-ascii: {weird}")


if __name__ == "__main__":
    main()
