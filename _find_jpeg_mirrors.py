"""Find JPEG mirrors for VVIC S3 objects; inspect libheif error workaround."""
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
key = "1700bones/slideshow_80821f2c"
candidates = [
    f"https://reelfarm-slideshow-images.s3.us-west-1.amazonaws.com/{key}.jpg",
    f"https://dh8vpkzn300g4.cloudfront.net/{key}.jpeg",
    f"https://dh8vpkzn300g4.cloudfront.net/{key}.jpg",
    f"https://dh8vpkzn300g4.cloudfront.net/{key}.webp",
    f"https://reelfarm-slideshow-images.s3.us-west-1.amazonaws.com/{key}.jpeg",
    f"https://reelfarm-slideshow-images.s3.amazonaws.com/{key}.jpg",
]
h = {"User-Agent": "Mozilla/5.0", "Referer": "https://reel.farm/"}
for u in candidates:
    try:
        r = httpx.get(u, headers=h, follow_redirects=True, timeout=20)
        head = r.content[:12] if r.content else b""
        kind = "?"
        if head[4:8] == b"ftyp":
            kind = "ftyp:" + head[8:12].decode("latin1", errors="replace")
        elif head[:3] == b"\xff\xd8\xff":
            kind = "JPEG"
        elif head[:4] == b"RIFF":
            kind = "WEBP/RIFF"
        print(r.status_code, r.headers.get("content-type"), kind, len(r.content), u)
    except Exception as e:
        print("ERR", e, u)

# Sample more broken URLs from report - see host mix
import json
from collections import Counter
rep = json.load(open(r"e:\Users\Desktop\farm\broken_slides_report.json", encoding="utf-8"))
hosts = Counter()
for x in rep["broken"]:
    u = x.get("url") or ""
    if "://" in u:
        hosts[u.split("/")[2]] += 1
print("broken url hosts", hosts)
