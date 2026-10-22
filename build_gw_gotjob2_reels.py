#!/usr/bin/env python3
"""
Global Work «I got the job», вторая партия — как output/gw_gotjob (build_gw_gotjob_reels.py): ролик на каждый дубль,
паузы вырезаны (джамп-каты, чередуем наезд 100 % / 110 %), текст «i got the job on global work ai» дословно из ТЗ
(TikTok Sans Bold 46 px, белый), голос −16 LUFS + трек рефа тихо под голосом, итог −14 LUFS.

  A — монтаж 2 (Drive 1UzfZHicrFohVBshQHyo1pJL3AGUMhHC1 → downloads/gw_gotjob2/srcA IMG_5700/5704/5705) → 3 ролика,
      текст на груди, как в первой партии.
  B — монтаж 3 (Drive 1kBkDMTT5lj6lib85nedKtf3QnzSlVMMv → srcB IMG_8111/8114, плачет очень крупным планом:
      подбородок в среднем на 1730 px, лицо на весь кадр) → 2 ролика, текст сверху (над головой / на лбу), чтобы
      не лечь на рот; наезд на склейках — от верха кадра, лицо при наезде уходит вниз, а не под текст.
Без сдвига кадра с размытой полосой (пользователь такое не любит, см. gw_wall2).
Лица по кадрам — src*/_faces.json (MediaPipe, 10 к/с).

  python build_gw_gotjob2_reels.py [A B]
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_gotjob_reels as G  # noqa: E402

D = ROOT / "downloads" / "gw_gotjob2"
OUT = ROOT / "output" / "gw_gotjob2"
# монтаж: (папка, дубли, центр текста по y, точка, от которой идёт наезд)
SETS = {
    "A": (D / "srcA", ["IMG_5700", "IMG_5704", "IMG_5705"], G.TEXT_CY, G.ZOOM_CY),
    "B": (D / "srcB", ["IMG_8111", "IMG_8114"], 240, 240),
}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    only = sys.argv[1:]
    OUT.mkdir(parents=True, exist_ok=True)
    G.OUT = OUT
    G.chin_shift = lambda clip, text_top: 0          # без подъёма кадра и размытой полосы снизу
    rep = []
    for tag, (src, takes, cy, zcy) in SETS.items():
        if only and tag not in only:
            continue
        G.SRC, G.TEXT_CY, G.ZOOM_CY = src, cy, zcy
        work = Path(tempfile.mkdtemp(prefix=f"gotjob2{tag}_"))
        png = work / "text.png"
        box = G.text_png(png)
        faces = json.loads((src / "_faces.json").read_text())
        for n, clip in enumerate(takes, 1):
            r = G.build(clip, f"{tag}{n}", png, work, box[1])
            segs = r["segments"]
            rows = [x for x in faces[clip] if any(a <= x[0] <= b for a, b in segs)]
            hit = sum(1 for _t, top, chin, _h in rows if top < box[3] and chin > box[1])
            r["text_box"], r["face_overlap_frames"] = box, f"{hit}/{len(rows)}"
            rep.append(r)
            print(f"{r['file']}: {clip}, {r['duration']} с, склеек {r['cuts']}, текст y {box[1]}–{box[3]}, "
                  f"лицо под текстом в {hit}/{len(rows)} кадрах", flush=True)
    (OUT / "manifest.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
