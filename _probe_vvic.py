import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
r = json.load(open(r"e:\Users\Desktop\farm\broken_slides_report.json", encoding="utf-8"))
all_dir = Path(r"e:\Users\Desktop\farm\downloaded_carousels\_all")
kinds = Counter()
for item in r["broken"]:
    if item["reason"] != "unidentified":
        kinds[item["reason"]] += 1
        continue
    folder = all_dir / item["folder"]
    idx = item["slide_index"]
    files = [f for f in folder.glob(str(idx) + ".*") if f.suffix.lower() not in {".json", ".part"}]
    if not files:
        kinds["gone"] += 1
        continue
    b = files[0].read_bytes()[:16]
    if len(b) >= 12 and b[4:8] == b"ftyp" and b[8:12] == b"vvic":
        kinds["vvic"] += 1
    elif b[:3] == b"\xff\xd8\xff":
        kinds["jpeg"] += 1
    elif b[:4] == b"\x89PNG":
        kinds["png"] += 1
    elif b[:4] == b"RIFF":
        kinds["webp"] += 1
    else:
        kinds["other:" + b[:12].hex()] += 1
print(dict(kinds))
print("ffmpeg", shutil.which("ffmpeg"))
print("magick", shutil.which("magick"))

# try convert one vvic if present
sample = None
for item in r["broken"]:
    if item["reason"] != "unidentified":
        continue
    folder = all_dir / item["folder"]
    files = [f for f in folder.glob(str(item["slide_index"]) + ".*") if f.suffix.lower() not in {".json", ".part"}]
    if not files:
        continue
    b = files[0].read_bytes()[:12]
    if len(b) >= 12 and b[4:8] == b"ftyp" and b[8:12] == b"vvic":
        sample = files[0]
        break
print("sample", sample)
if sample and shutil.which("ffmpeg"):
    out = sample.with_name(sample.stem + "_conv.jpg")
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(sample), str(out)],
        capture_output=True,
        text=True,
    )
    print("ffmpeg rc", proc.returncode)
    print(proc.stderr[-500:] if proc.stderr else "")
    print("out exists", out.exists(), out.stat().st_size if out.exists() else 0)
