#!/usr/bin/env python3
"""
1391 (Drops, «top 5 websites to cure your boredom», 5,6 с) — корейская версия: те же слайды и бит, тексты
обложки и карточек сайтов на корейском (домены и названия сайтов — как есть), шрифт Malgun Gothic.

  python build_1391_ko.py -n 10 --half --seed 4911 --out output/urgent_30/KR
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1391_reels as R  # noqa: E402

B = R.B
MB, MR = Path("C:/Windows/Fonts/malgunbd.ttf"), Path("C:/Windows/Fonts/malgun.ttf")
B.F_BOLD = B.F_SEMI = MB
B.F_MED = B.F_REG = MR
B.SITES = [
    ("neal", "neal.fun", "1. Neal.fun", "한 시간이 순삭되는 작은 인터랙티브 게임과 이상한 실험 모음"),
    ("radio", "radio.garden", "2. Radio Garden", "지구본을 돌려서 전 세계 라이브 라디오 듣기"),
    ("window", "window-swap.com", "3. Window Swap", "전 세계 낯선 사람들의 창밖 풍경 구경하기"),
    ("drops", "drops.game", "4. Drops",
     "노래를 올리면 템포와 분위기에 맞춰 플레이할 수 있는 게임을 만들어 줘. 무료로 시작, 브라우저에서 바로 플레이"),
    ("patatap", "patatap.com", "5. Patatap", "아무 키나 누르면 소리와 애니메이션이 나와. 이상하게 힐링됨"),
]
KO = {"top 5": "TOP 5", "websites": "심심함", "to cure your": "날려줄", "boredom": "사이트",
      "(#4 is my favorite)": "(4번이 내 최애)", "save for later!": "저장해두기!"}
_text_img, _tag = B.text_img, B.tag
B.text_img = lambda s, f, fill, track=0.0: _text_img(KO.get(s, s), f, fill, track=0.0 if s in KO else track)
B.tag = lambda s, px: _tag(KO.get(s, s), px)

if __name__ == "__main__":
    raise SystemExit(R.main())
