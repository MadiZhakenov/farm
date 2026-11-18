#!/usr/bin/env python3
"""
1390 «swaggy jeans» 8 с — версии на других языках (срочно: 10 немецких, 10 бразильских, 10 корейских).
Тот же сборщик build_1390_reels (--short), меняются только тексты: обложка, плашки, подпись Inspoy
(название приложения «Inspoy: Outfit Maker, Planner» и карточка App Store — как есть). Для корейского —
шрифт Malgun Gothic Bold (в Bebas Neue и TikTok Sans нет хангыля).

  python build_1390_lang.py de --out output/urgent_30/DE -n 10 --seed 4901
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1390_reels as R  # noqa: E402

NL = "\n"
LANG = {
    "de": {
        "cover": ["klamotten", "die ich", "im herbst", "extrem", "swaggy", "finde"],
        "labels": ["bestickte jeans", "jeans mit grafikprint", "dunkle wide-leg-jeans", "jeans in vintage-waschung",
                   "patchwork-jeans", "cargo-jeans", "jeans mit nieten", "raw-denim-jeans"],
        "caption": ["ich hab das alles", "in Inspoy kombiniert:", "Outfit Maker, Planner 🤍"],
    },
    "pt": {
        "cover": ["roupas", "que eu acho", "muito", "estilosas", "no outono"],
        "labels": ["jeans bordado", "jeans estampado", "jeans wide leg escuro", "jeans lavagem vintage",
                   "jeans patchwork", "jeans cargo", "jeans com tachas", "jeans de denim cru"],
        "caption": ["juntei tudo isso", "no Inspoy:", "Outfit Maker, Planner 🤍"],
    },
    "ko": {
        "cover": ["가을에", "진짜", "힙하다고", "생각하는", "옷들"],
        "labels": ["자수 청바지", "그래픽 프린트 청바지", "다크 와이드 청바지", "빈티지 워싱 청바지",
                   "패치워크 청바지", "카고 청바지", "스터드 청바지", "생지 데님 청바지"],
        "caption": ["이거 전부", "Inspoy에서 코디했어:", "Outfit Maker, Planner 🤍"],
    },
}
KO_FONT = Path("C:/Windows/Fonts/malgunbd.ttf")


def main() -> int:
    lang = sys.argv.pop(1)
    t = LANG[lang]
    R.SLIDES = [(R.SLIDES[0][0], NL.join(t["cover"]))] + [(slot, lab) for (slot, _), lab in zip(R.SLIDES[1:], t["labels"])]
    R.CAPTION = NL.join(t["caption"])
    if lang == "de":
        R.PLATE_CAP *= 0.9                                   # длинные немецкие плашки — чуть мельче, в рамке 140–940
    if lang == "ko":
        R.FONT = KO_FONT                                     # плашки и обложка
        R.SQX = 1.0                                          # хангыль не сжимаем
        R.PLATE_CAP *= 0.62                                  # Malgun шире Bebas — плашки в рамке 140–940
        R.COVER_CAP *= 0.75
        import build_1281_carousels as B                     # подпись (TikTok-шрифт → Malgun)
        from PIL import ImageFont
        B.R._load_font = lambda px: ImageFont.truetype(str(KO_FONT), px)
    if "--short" not in sys.argv:
        sys.argv.append("--short")
    if "--id" not in sys.argv:
        sys.argv += ["--id", lang]
    return R.main()


if __name__ == "__main__":
    raise SystemExit(main())
