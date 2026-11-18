#!/usr/bin/env python3
"""
Drops react — фоновая запись экрана «телефона» (Edge из drops_browser.py, порт 9333) через CDP-скринкаст:
кадры ~1210×2110 в реальном времени, пока не появится стоп-файл; потом склейка в mp4 30 fps (длительности по времени
прихода кадров). Пока идёт запись, сценарий управляется отдельными подключениями (connect_over_cdp).

  python drops_screenrec.py output/drops_react/rec/upload.mp4 [кусок_адреса]   # стоп: создать файл <out>.stop
Вкладку с записью не закрывать — запись оборвётся (кадры останутся в _<имя>_frames, время — по mtime файлов).
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    stop = out.with_suffix(".stop")
    frames = out.with_suffix("")
    frames = frames.parent / f"_{frames.name}_frames"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir(parents=True)
    stop.unlink(missing_ok=True)
    t: list[float] = []
    with sync_playwright() as pw:
        br = pw.chromium.connect_over_cdp("http://127.0.0.1:9333")
        pages = br.contexts[0].pages
        want = sys.argv[2] if len(sys.argv) > 2 else ""            # кусок адреса вкладки, иначе первая
        page = next((p for p in pages if want and want in p.url), pages[0])
        cdp = page.context.new_cdp_session(page)

        def frame(ev) -> None:
            (frames / f"{len(t):05d}.jpg").write_bytes(base64.b64decode(ev["data"]))
            t.append(time.perf_counter())
            try:
                cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
            except Exception:
                pass

        cdp.on("Page.screencastFrame", frame)
        cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 88, "maxWidth": 1400, "maxHeight": 2600})
        print("rec", out.name, flush=True)
        while not stop.exists():
            page.wait_for_timeout(100)                    # не time.sleep: иначе события скринкаста не разбираются
        cdp.send("Page.stopScreencast")
        t.append(time.perf_counter())
    lst = frames / "list.txt"
    n = len(t) - 1
    lines = []
    for i in range(n):
        lines += [f"file '{(frames / f'{i:05d}.jpg').as_posix()}'", f"duration {max(t[i + 1] - t[i], 1 / 120):.4f}"]
    lines.append(f"file '{(frames / f'{n - 1:05d}.jpg').as_posix()}'")
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-vf", "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p", "-c:v", "h264_nvenc",
                    "-preset", "p5", "-cq", "19", "-map_metadata", "-1", str(out)], check=True)
    shutil.rmtree(frames, ignore_errors=True)
    stop.unlink(missing_ok=True)
    print("saved", out, n, "frames", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
