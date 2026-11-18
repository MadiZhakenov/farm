#!/usr/bin/env python3
"""Убрать все метаданные из JPEG без пересжатия: вырезаем сегменты APP0–APP15 (JFIF, EXIF, XMP, ICC, IPTC…) и COM,
сами данные картинки (DQT/SOF/DHT/SOS и скан) байт в байт.

  python strip_jpeg_meta.py output/1322_300
"""

from __future__ import annotations

import sys
from pathlib import Path


def strip(data: bytes) -> bytes:
    assert data[:2] == b"\xff\xd8", "не JPEG"
    out, i = bytearray(b"\xff\xd8"), 2
    while i < len(data):
        if data[i] != 0xFF:
            raise ValueError("битая разметка")
        m = data[i + 1]
        if m == 0xDA:                                   # SOS: дальше скан до конца файла
            out += data[i:]
            break
        n = int.from_bytes(data[i + 2:i + 4], "big")
        if not (0xE0 <= m <= 0xEF or m == 0xFE):         # APPn и COM — выкидываем
            out += data[i:i + 2 + n]
        i += 2 + n
    return bytes(out)


def main() -> int:
    files = [f for a in sys.argv[1:] for f in sorted(Path(a).rglob("*")) if f.suffix.lower() in (".jpg", ".jpeg")]
    saved = 0
    for f in files:
        raw = f.read_bytes()
        new = strip(raw)
        if new != raw:
            f.write_bytes(new)
            saved += len(raw) - len(new)
    print(f"файлов {len(files)}, убрано {saved / 1024:.0f} КБ метаданных")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
