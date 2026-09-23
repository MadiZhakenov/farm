import io
import json
import sys
from pathlib import Path

import httpx
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
r = json.load(open(r"e:\Users\Desktop\farm\broken_slides_report.json", encoding="utf-8"))
items = [x for x in r["broken"] if x["reason"] == "unidentified"][:5]
h = {"User-Agent": "Mozilla/5.0", "Referer": "https://reel.farm/"}

for item in items:
    print("====", item["folder"], "slide", item["slide_index"])
    folder = Path(r"e:\Users\Desktop\farm\downloaded_carousels\_all") / item["folder"]
    files = list(folder.glob(f"{item['slide_index']}.*"))
    for f in files:
        if f.suffix == ".json":
            continue
        b = f.read_bytes()
        print(" local", f.name, "size", len(b), "hex", b[:16].hex(), "ascii", repr(b[:24]))
    url = item["url"]
    resp = httpx.get(url, headers=h, follow_redirects=True, timeout=30)
    c = resp.content
    print(" remote", resp.status_code, resp.headers.get("content-type"), "size", len(c), "hex", c[:16].hex())
    try:
        im = Image.open(io.BytesIO(c))
        print(" pillow", im.format, im.size, im.mode)
    except Exception as e:
        print(" pillow ERR", type(e).__name__, e)
    # brand
    if len(c) > 12:
        print(" box", c[4:8], c[8:12])
