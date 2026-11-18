#!/usr/bin/env python3
"""
Inspoy — «доски образов» (реф TikTok @aiyah.777 7526213383302008071): коллажи образов на белом сменяются в бит
звука рефа, ролик ≤ 11 с; на склейке 8.03 с — текст ТЗ (дословно, переносы по смыслу) до конца.
Доски — наши (Flow по кадрам рефа, downloads/inspoy_found/gen51, 26 шт.). Склейки — как в рефе (замер по кадрам):
до 11 с это 22 доски. В каждом ролике 22 из 26 в своём порядке, первая доска у всех роликов разная по кругу.
Кадр 1080×1920: доска во всю ширину по центру на белом (фон досок — чистый белый). Текст — белый TikTok-шрифт
с чёрной обводкой, в безопасной зоне 9:16. Звук — оригинальный звук рефа с 0 с, −14 LUFS. NVENC.

  python build_inspoy_boards_reels.py --test                       # 2 ролика (без звука, если его нет)
  python build_inspoy_boards_reels.py -n 50 --id 1345 --sound downloads/inspoy_found/music/ref_sound.mp3   # → output/1345_50
  # +100 YouTube (11.11): новые сочетания, не повторяют 1345_50 и немецкую версию
  python build_inspoy_boards_reels.py -n 100 --id 1345 --seed 3345 --sound downloads/inspoy_found/music/ref_sound.mp3 \
      --exclude output/1345_50/manifest.json --exclude output/urgent_30/_alt/DE_boards/manifest.json --out output/inspoy_1345_YT_100
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_gw_pyramid_reel as P  # noqa: E402  (подпись белым TikTok-шрифтом с обводкой, громкость)
from core import renderer as R  # noqa: E402
from core.safe_zones import check_overlay  # noqa: E402
from core.ugc_color import SDR_COLOR_ARGS, SET_SDR  # noqa: E402

FF, W, H, FPS = P.FF, 1080, 1920, 30
BOARDS = sorted((ROOT / "downloads" / "inspoy_found" / "gen51").glob("*.jpg"))
OUT = ROOT / "output" / "1345_50"
CACHE = ROOT / "output" / "inspoy_boards_cache"
# склейки рефа, с (замер разницы кадров в плеере); последний кусок обрезан концом ролика
CUTS = [0.0, 0.433, 0.833, 1.3, 1.533, 1.9, 2.3, 2.833, 3.333, 3.733, 4.1, 4.433, 5.033, 5.633, 6.2, 6.733, 7.333,
        8.033, 8.6, 9.133, 9.8, 10.433]
END = 11.0
TEXT_ON = 8.033
TEXT = ["i found all of this in Inspoy:", "Outfit Maker, Planner", "and planned it", "the night before btw"]
TEXT_MAX_W, TEXT_CY = 760, 960


def frames() -> list[Path]:
    """Доска во всю ширину по центру белого кадра 9:16 (кэш)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = []
    for k, p in enumerate(BOARDS, 1):
        dest = CACHE / f"b{k:02d}.png"
        if not dest.exists():
            im = Image.open(p).convert("RGB")
            im = im.resize((W, round(im.height * W / im.width)), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (W, H), (255, 255, 255))
            canvas.paste(im, (0, (H - im.height) // 2))
            canvas.save(dest)
        out.append(dest)
    return out


def text_png() -> Path:
    dest = CACHE / "text.png"
    px = 64
    while px > 30:
        font = R._load_font(px)
        if max(font.getlength(t) for t in TEXT) + 2 * R.stroke_width_for(px) <= TEXT_MAX_W:
            break
        px -= 1
    lines = [P.label(t, TEXT_MAX_W, px) for t in TEXT]
    step = int(px * 1.28)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    y = int(TEXT_CY - step * len(lines) / 2)
    for im in lines:
        canvas.alpha_composite(im, ((W - im.width) // 2, y + (step - im.height) // 2))
        y += step
    bad = check_overlay(canvas)
    if bad:
        raise SystemExit(f"текст вне безопасной зоны: {bad}")
    canvas.save(dest)
    print(f"текст {px} px, строк {len(lines)}", flush=True)
    return dest


def plan(n: int, rng: random.Random, used_sets: set | None = None) -> list[list[int]]:
    """n последовательностей по len(CUTS) досок из 26: первая доска — по кругу (каждая ≤ ⌈n/26⌉ раз), без повторов.
    used_sets — уже выданные наборы досок (frozenset имён): новый ролик не повторяет ни один набор (сочетание 22 из 26)."""
    k = len(BOARDS)
    used_sets = set(used_sets or ())
    firsts: list[int] = []
    while len(firsts) < n:
        cyc = list(range(k))
        rng.shuffle(cyc)
        firsts += cyc
    seqs, seen = [], set()
    for i in range(n):
        while True:
            rest = [b for b in range(k) if b != firsts[i]]
            rng.shuffle(rest)
            s = [firsts[i]] + rest[:len(CUTS) - 1]
            bset = frozenset(BOARDS[b].name[:6] for b in s)
            if tuple(s) not in seen and bset not in used_sets:
                seen.add(tuple(s))
                used_sets.add(bset)
                seqs.append(s)
                break
    return seqs


def render(seq: list[int], imgs: list[Path], txt: Path, sound: Path | None, afilter: str, dest: Path) -> None:
    lst = dest.with_suffix(".txt")
    ends = CUTS[1:] + [END]
    rows = []
    for b, a, e in zip(seq, CUTS, ends):
        rows += [f"file '{imgs[b].as_posix()}'", f"duration {e - a:.3f}"]
    rows.append(f"file '{imgs[seq[-1]].as_posix()}'")
    lst.write_text("\n".join(rows) + "\n", encoding="utf-8")
    inputs = ["-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(txt)]
    fc = (f"[0:v]fps={FPS},format=rgb24[b];[b][1:v]overlay=0:0:enable='gte(t,{TEXT_ON})',trim=duration={END},"
          f"format=yuv420p,{SET_SDR}[v]")
    amap = []
    if sound:
        inputs += ["-i", str(sound)]
        fc += f";[2:a]atrim=0:{END},asetpts=PTS-STARTPTS,{afilter}[a]"
        amap = ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", fc, "-map", "[v]", *amap,
                    "-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "19", "-b:v", "0",
                    "-profile:v", "high", *SDR_COLOR_ARGS, "-t", str(END), "-movflags", "+faststart", str(dest)],
                   check=True)
    lst.unlink()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=50)
    ap.add_argument("--sound", type=Path)
    ap.add_argument("--id", default="noid")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--out", type=Path, help="папка выдачи (по умолчанию output/1345_50)")
    ap.add_argument("--exclude", type=Path, action="append", default=[], help="manifest.json прошлых партий — их наборы не повторяем")
    a = ap.parse_args()
    if len(BOARDS) < len(CUTS):
        raise SystemExit(f"досок {len(BOARDS)}, нужно ≥ {len(CUTS)}")
    imgs, txt = frames(), text_png()
    afilter = ""
    if a.sound:
        P.SOUND = a.sound
        afilter = P.audio_filter()
    out = OUT.parent / "inspoy_boards_test" if a.test else (a.out or OUT)
    out.mkdir(parents=True, exist_ok=True)
    used = {frozenset(b[:6] for b in m["boards"]) for f in a.exclude for m in json.loads(f.read_text(encoding="utf-8"))}
    seqs = plan(2 if a.test else a.n, random.Random(a.seed), used)
    for i, s in enumerate(seqs, 1):
        dest = out / f"{i:03d}_{a.id}.mp4"
        render(s, imgs, txt, a.sound, afilter, dest)
        print(f"  {dest.name}: {' '.join(BOARDS[b].name[4:6] for b in s)}", flush=True)
    (out / "manifest.json").write_text(json.dumps([{"file": f"{i:03d}_{a.id}.mp4", "boards": [BOARDS[b].name for b in s]}
                                                    for i, s in enumerate(seqs, 1)], indent=1), encoding="utf-8")
    print(f"готово: {len(seqs)} → {out}" + ("" if a.sound else " (без звука — нужен звук рефа)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
