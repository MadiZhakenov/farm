"""Общее для роликов раунда 3 (docs/REPOST_HYPOTHESES.md): правило юзера 2026-11-05 — «тайтл всегда сверху, субт внизу».
V2 (DdGwGMEx-Uj) — подпись была ВНИЗУ: берём очищенный исходник (clean_xmas_v2_caption.py, LaMa) и ставим тот же
заголовок сверху белым TikTok-шрифтом с обводкой и Apple-эмодзи, как у V1/V3 (у них подпись и так сверху)."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import assemble_ugc_reels as A  # noqa: E402
from core import renderer as R  # noqa: E402
from core.safe_zones import check_box  # noqa: E402

W, H = 1080, 1920
SRC = ROOT / "downloads" / "xmas_proj" / "src"
CLEAN = ROOT / "downloads" / "xmas_proj" / "src_clean"
NAME = {"v1": "DcNWKlfAbOo.mp4", "v2": "DdGwGMEx-Uj.mp4", "v3": "DdZ5O2bR39c.mp4"}
TITLE = {"v2": ["DO NOT show this to a", "Christmas-aholic😱🤫…"]}       # их текст дословно, но сверху
TITLE_CY, TITLE_PX = 0.235, 62
SUB_Y = 0.72                                                        # субтитры внизу (над подписью TikTok)


def source(key: str) -> Path:
    p = CLEAN / NAME[key]
    return p if p.exists() else SRC / NAME[key]


def title_png(key: str, dest: Path) -> tuple[int, int] | None:
    """Заголовок сверху (только где родной был снизу); None — заголовок уже в кадре."""
    if key not in TITLE:
        return None
    lines = TITLE[key]
    px = TITLE_PX
    font, st = R._load_font(px), R.stroke_width_for(px)
    adv = R.line_advance_for(px)
    img = Image.new("RGBA", (W, adv * len(lines) + 2 * st + 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        lw = A._line_width_mixed(ln, font, px, st)
        A._draw_line_mixed(img, d, int((W - lw) / 2), i * adv + st, ln, font, px, st)
    box = img.getbbox()
    img = img.crop(box)
    img.save(dest)
    x, y = box[0], int(H * TITLE_CY - img.height / 2)
    if bad := check_box(W, H, (x, y, x + img.width, y + img.height)):
        raise SystemExit(f"заголовок вне безопасной зоны: {bad}")
    return x, y
