#!/usr/bin/env python3
"""
Global Work «BAD / GOOD / AMAZING», вторая партия — как output/gw_bga (build_gw_bga_reel.py): шапка
BAD · GOOD · AMAZING с логотипами LinkedIn / Indeed / Global Work (будущие размыты, проявляются на слово уровня),
субтитры по 1–3 слова дословно из ТЗ, джамп-каты с чередованием крупности, голос −14 LUFS; оба варианта:
v1 — логотипы весь ролик, v2 — после слова уровня окно 16:9 с записью сайта.

  A — монтаж 1 (Drive 1GMCLyP5_n8cQ86-1D2YLXJ0gL-O1f2HG): один дубль BAD → GOOD → AMAZING, режем на 3 уровня.
  B — монтаж 2 (Drive 16fYT0mY_6Bb2UEOO-y0c_27r3AEx7b4S, IMG_8100, 117 с с пересъёмками): чистые дубли
      BAD 0.6–7.2, GOOD 20.2–27.5 (дубль на 10 с с оговоркой пропущен), AMAZING 107.2–114.6 (последний полный).
Дубли — downloads/gw_bga2/takes/*.MOV (SDR 1080×1920), слова Whisper — takes/words.json.
Раскладка — по лицу каждого креатора: если шапка/окно сайта наезжает на лицо, видео сдвигаем вниз (сверху
размытое отражение); субтитры — под подбородком с учётом крупного плана на склейках; всё в безопасной зоне.

  python build_gw_bga2_reels.py [A B]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_bga_reel as G  # noqa: E402
import build_gw_wall2_reels as W2  # noqa: E402  (face_stats)
from core.safe_zones import text_rect  # noqa: E402

TAKES = ROOT / "downloads" / "gw_bga2" / "takes"
TEXT = {tier: text for _c, tier, text in G.SCRIPT}          # тексты ТЗ те же
MONTAGES = {"A": ["A_bad", "A_good", "A_amazing"], "B": ["B_bad", "B_good", "B_amazing"]}
PANEL = (700, 394)          # окно сайта чуть меньше, чем в gw_bga: иначе субтитры под подбородком не влезают в зону
GAP = 25


def layout(clips: list[str]) -> dict:
    faces = [W2.face_stats(TAKES / f"{c}.MOV", 0, 60) for c in clips]
    top = min(f["top_min"] for f in faces)
    c = (G.H - G.H / G.ZOOM) * G.ZOOM_Y                       # крупный план: y' = (y − c)·ZOOM
    chin = max(f["chin_max"] for f in faces)
    chin_z = max(chin, (chin - c) * G.ZOOM)
    a = G.header_assets()
    head_bottom = G.HEAD_TOP + max(h.height for h in a["heads"]) + 14 + G.ICON + 8 + max(lab.height for lab in a["labels"])
    sub_h = G.T.glow_text(["AMAZING"], G.T.mono(G.SUB_PX)).height
    _x0, _y0, _x1, y1 = text_rect(G.W, G.H)
    even = lambda v: int(v) + int(v) % 2                       # noqa: E731
    s1 = even(max(0, head_bottom + 30 - top))
    s2 = even(max(0, G.PANEL_TOP + PANEL[1] + GAP - top))
    out = {"top": top, "chin": chin, "chin_zoom": round(chin_z), "shift_v1": s1, "shift_v2": s2,
           "sub_v1": int(min(chin_z + s1 + GAP, y1 - sub_h)), "sub_v2": int(min(chin_z + s2 + GAP, y1 - sub_h))}
    for v in ("v1", "v2"):
        if chin_z + out[f"shift_{v}"] + 5 > out[f"sub_{v}"]:
            print(f"  {v}: субтитры близко к подбородку ({out[f'sub_{v}']} при подбородке {chin_z + out[f'shift_{v}']:.0f})")
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    only = sys.argv[1:]
    G.SRC, G.OUT = TAKES, ROOT / "output" / "gw_bga2"
    G.PANEL_W, G.PANEL_H = PANEL
    for tag, clips in MONTAGES.items():
        if only and tag not in only:
            continue
        G.SCRIPT = [(c, t, TEXT[t]) for c, t in zip(clips, ("BAD", "GOOD", "AMAZING"))]
        lay = layout(clips)
        print(f"{tag}: {lay}", flush=True)
        G.ID = f"{tag}_noid"
        for v2 in (False, True):
            G.SHIFT_V1, G.SUB_TOP = lay["shift_v1"], lay["sub_v1"]
            G.SHIFT, G.SUB_TOP_V2 = lay["shift_v2"], lay["sub_v2"]
            sys.argv = ["build_gw_bga_reel.py"] + (["--v2"] if v2 else [])
            G.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
