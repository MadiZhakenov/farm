#!/usr/bin/env python3
"""
Convert TikTok/ByteDance VVIC (HEIF+VVC, ftyp=vvic) stills to JPEG
using ffmpeg's native VVC decoder.

Works around libheif's missing support for ptl_present_flag=0 by
bruteforce-scanning the vvcC box for NAL arrays.
"""
from __future__ import annotations

import struct
import subprocess
import tempfile
from pathlib import Path


class BoxReader:
    def __init__(self, data: bytes):
        self.data = data
        self.n = len(data)

    def boxes(self, start: int = 0, end: int | None = None):
        if end is None:
            end = self.n
        pos = start
        while pos + 8 <= end:
            size, typ = struct.unpack_from(">I4s", self.data, pos)
            typ = typ.decode("latin1")
            hdr = 8
            if size == 1:
                if pos + 16 > end:
                    break
                size = struct.unpack_from(">Q", self.data, pos + 8)[0]
                hdr = 16
            elif size == 0:
                size = end - pos
            if size < hdr or pos + size > end:
                break
            yield typ, pos, hdr, size
            pos += size


def find_boxes(reader: BoxReader, wanted: set[str], start=0, end=None):
    found = []
    for typ, pos, hdr, size in reader.boxes(start, end):
        payload_start = pos + hdr
        payload_end = pos + size
        if typ in wanted:
            found.append((typ, pos, hdr, size, payload_start, payload_end))
        if typ in {"moov", "meta", "iprp", "ipco"}:
            child_start = payload_start + (4 if typ == "meta" else 0)
            found.extend(find_boxes(reader, wanted, child_start, payload_end))
    return found


def parse_iloc(payload: bytes) -> dict[int, list[tuple[int, int]]]:
    if len(payload) < 6:
        return {}
    version = payload[0]
    pos = 4
    sizes = payload[pos]
    pos += 1
    offset_size = sizes >> 4
    length_size = sizes & 0xF
    sizes2 = payload[pos]
    pos += 1
    base_offset_size = sizes2 >> 4
    index_size = sizes2 & 0xF if version == 1 or version >= 2 else 0

    def read_uint(sz: int) -> int:
        nonlocal pos
        if sz == 0:
            return 0
        fmt = {1: "B", 2: ">H", 4: ">I", 8: ">Q"}[sz]
        if sz == 1:
            v = payload[pos]
        else:
            v = struct.unpack_from(fmt, payload, pos)[0]
        pos += sz
        return v

    if version < 2:
        item_count = struct.unpack_from(">H", payload, pos)[0]
        pos += 2
    else:
        item_count = struct.unpack_from(">I", payload, pos)[0]
        pos += 4

    mapping: dict[int, list[tuple[int, int]]] = {}
    for _ in range(item_count):
        if version < 2:
            item_id = struct.unpack_from(">H", payload, pos)[0]
            pos += 2
        else:
            item_id = struct.unpack_from(">I", payload, pos)[0]
            pos += 4
        if version == 1 or version >= 2:
            pos += 2
        pos += 2  # data_ref_index
        base_offset = read_uint(base_offset_size)
        extent_count = struct.unpack_from(">H", payload, pos)[0]
        pos += 2
        exts = []
        for _e in range(extent_count):
            if (version == 1 or version >= 2) and index_size > 0:
                read_uint(index_size)
            extent_offset = read_uint(offset_size)
            extent_length = read_uint(length_size)
            exts.append((base_offset + extent_offset, extent_length))
        mapping[item_id] = exts
    return mapping


def parse_pitm(payload: bytes) -> int:
    version = payload[0]
    pos = 4
    if version == 0:
        return struct.unpack_from(">H", payload, pos)[0]
    return struct.unpack_from(">I", payload, pos)[0]


def extract_vvcC_params(vvcc: bytes) -> tuple[int, list[bytes]]:
    """
    Return (length_size_bytes, param_nals).
    Bruteforce num_of_arrays offset because PTL record length varies
    (and TikTok often uses ptl_present_flag forms libheif rejects).
    """
    if not vvcc:
        return 4, []
    b0 = vvcc[0]
    length_size = ((b0 >> 1) & 0x3) + 1
    best: list[bytes] = []
    for start in range(1, min(48, len(vvcc))):
        pos = start
        num_arrays = vvcc[pos]
        pos += 1
        if num_arrays < 1 or num_arrays > 8:
            continue
        got: list[bytes] = []
        ok = True
        for _ in range(num_arrays):
            if pos + 3 > len(vvcc):
                ok = False
                break
            pos += 1  # array header
            num_nalus = struct.unpack_from(">H", vvcc, pos)[0]
            pos += 2
            if num_nalus < 1 or num_nalus > 8:
                ok = False
                break
            for _n in range(num_nalus):
                if pos + 2 > len(vvcc):
                    ok = False
                    break
                ln = struct.unpack_from(">H", vvcc, pos)[0]
                pos += 2
                if ln < 2 or ln > 4096 or pos + ln > len(vvcc):
                    ok = False
                    break
                got.append(vvcc[pos : pos + ln])
                pos += ln
            if not ok:
                break
        if ok and got and pos == len(vvcc):
            # Prefer parse that consumes entire vvcC exactly
            return length_size, got
        if ok and got and len(got) >= len(best):
            best = got
    return length_size, best


def length_prefixed_to_annex_b(sample: bytes, length_size: int, params: list[bytes]) -> bytes:
    start = b"\x00\x00\x00\x01"
    out = bytearray()
    for nal in params:
        out += start + nal
    pos = 0
    while pos + length_size <= len(sample):
        if length_size == 4:
            nlen = struct.unpack_from(">I", sample, pos)[0]
        elif length_size == 2:
            nlen = struct.unpack_from(">H", sample, pos)[0]
        elif length_size == 1:
            nlen = sample[pos]
        else:
            nlen = struct.unpack_from(">I", sample, pos)[0]
            length_size = 4
        pos += length_size
        if nlen <= 0 or pos + nlen > len(sample):
            break
        out += start + sample[pos : pos + nlen]
        pos += nlen
    return bytes(out)


def extract_annex_b(vvic_bytes: bytes) -> bytes:
    if not (len(vvic_bytes) > 12 and vvic_bytes[4:8] == b"ftyp" and vvic_bytes[8:12] == b"vvic"):
        raise ValueError("not VVIC")
    r = BoxReader(vvic_bytes)
    top = list(r.boxes())
    meta = next((b for b in top if b[0] == "meta"), None)
    if not meta:
        raise ValueError("no meta")
    _, meta_pos, meta_hdr, meta_size = meta
    kids = find_boxes(r, {"iloc", "pitm", "vvcC"}, meta_pos + meta_hdr + 4, meta_pos + meta_size)
    by = {}
    for k in kids:
        by.setdefault(k[0], []).append(k)
    if "iloc" not in by or "pitm" not in by:
        raise ValueError("missing iloc/pitm")
    item_id = parse_pitm(vvic_bytes[by["pitm"][0][4] : by["pitm"][0][5]])
    extents_map = parse_iloc(vvic_bytes[by["iloc"][0][4] : by["iloc"][0][5]])
    extents = extents_map.get(item_id) or next(iter(extents_map.values()))
    length_size = 4
    params: list[bytes] = []
    if "vvcC" in by:
        vvcc = vvic_bytes[by["vvcC"][0][4] : by["vvcC"][0][5]]
        length_size, params = extract_vvcC_params(vvcc)
    sample = bytearray()
    for off, length in extents:
        sample += vvic_bytes[off : off + length]
    return length_prefixed_to_annex_b(bytes(sample), length_size, params)


def is_vvic(data: bytes) -> bool:
    return len(data) > 12 and data[4:8] == b"ftyp" and data[8:12] == b"vvic"


def vvic_to_jpg(src: Path | bytes, dest_jpg: Path, ffmpeg: str = "ffmpeg") -> Path:
    data = src if isinstance(src, bytes) else Path(src).read_bytes()
    annex = extract_annex_b(data)
    if len(annex) < 32:
        raise ValueError("annex-b too small")
    dest_jpg = Path(dest_jpg)
    dest_jpg.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        bit = Path(td) / "pic.266"
        bit.write_bytes(annex)
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "vvc",
                "-i",
                str(bit),
                "-frames:v",
                "1",
                "-update",
                "1",
                "-q:v",
                "2",
                str(dest_jpg),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not dest_jpg.exists() or dest_jpg.stat().st_size < 100:
            raise RuntimeError((proc.stderr or "ffmpeg failed")[-1000:])
    return dest_jpg


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    src = Path(sys.argv[1] if len(sys.argv) > 1 else r"e:\Users\Desktop\farm\_test_vvic.vvic")
    dst = Path(sys.argv[2] if len(sys.argv) > 2 else r"e:\Users\Desktop\farm\_test_vvic_converted.jpg")
    vvic_to_jpg(src, dst)
    print("OK", dst, dst.stat().st_size)
