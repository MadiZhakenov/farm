"""Try alternate Accept / URL variants to get decodeable images instead of VVIC."""
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
url = "https://reelfarm-slideshow-images.s3.us-west-1.amazonaws.com/1700bones/slideshow_80821f2c.jpg"
base_h = {"User-Agent": "Mozilla/5.0", "Referer": "https://reel.farm/"}

variants = [
    {},
    {"Accept": "image/jpeg,image/png,image/webp,*/*"},
    {"Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"},
    {"Accept": "image/jpeg"},
]
url_variants = [
    url,
    url + "?format=jpg",
    url.replace(".jpg", ".jpeg"),
    url.replace(".jpg", ".webp"),
    url.replace(".jpg", ".png"),
    url.replace("slideshow_", "slideshow_").replace(".jpg", "_jpg.jpg"),
]

client = httpx.Client(timeout=30, follow_redirects=True)
for uh in variants:
    r = client.get(url, headers={**base_h, **uh})
    print("hdr", uh.get("Accept", "default")[:40], "->", r.status_code, r.headers.get("content-type"), r.content[4:12], len(r.content))

print("--- url variants ---")
for u in url_variants:
    try:
        r = client.get(u, headers={**base_h, "Accept": "image/jpeg"})
        print(r.status_code, r.headers.get("content-type"), r.content[4:12] if len(r.content) > 12 else r.content[:20], u[-50:])
    except Exception as e:
        print("ERR", e, u[-50:])

# ffprobe streams
import subprocess
p = Path(r"e:\Users\Desktop\farm\_test_vvic.vvic")
proc = subprocess.run(["ffprobe", "-show_streams", "-show_format", "-print_format", "json", str(p)], capture_output=True, text=True)
print("ffprobe", proc.returncode)
print(proc.stdout[:1500])
print(proc.stderr[-400:])
