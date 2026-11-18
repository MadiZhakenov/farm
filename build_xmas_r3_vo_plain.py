#!/usr/bin/env python3
"""
Раунд 3 (docs/REPOST_HYPOTHESES.md), R3-3d «оригинал + наш голос» — после отзыва юзера на R3-3c (2026-11-05):
«непонятно что происходит, что видео хочет сказать», «звуки странные», «кроп и зум странные».

  - порядок кадров как в оригинале (история линейная), кадр целиком без кропа/зума;
  - родные вшитые подписи оставлены (озвучка их повторяет по смыслу), своих субтитров нет;
  - куски слегка ускорены/замедлены (≈0.75–1.25×), чтобы показ совпадал с фразой озвучки;
  - звук: только озвучка юзера (chipbot) + тихая музыка, без синтезированных эффектов.

  python build_xmas_r3_vo_plain.py --out output/xmas_r3/R3-3d_vo_original
  python build_xmas_r3_vo_plain.py --reply --out output/xmas_r3/R3-6_reply
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
W, H, FPS = 1080, 1920, 30
SRC = ROOT / "downloads" / "xmas_proj" / "src"
VO = ROOT / "downloads" / "xmas_proj" / "vo"
MUSIC = ROOT / "downloads" / "1303" / "music" / "gZIrKXCzue8.m4a"

# (VO от, VO до, src от, src до) — подряд, в порядке оригинала
VIDS = {
    "v1": dict(src="DcNWKlfAbOo.mp4", vo="vo_v1.mp3", total=12.55,
               seg=[(0.0, 2.26, 0.0, 2.3), (2.26, 4.2, 2.3, 4.75), (4.2, 5.33, 4.9, 6.4), (5.33, 12.55, 6.55, 14.85)]),
    "v2": dict(src="DdGwGMEx-Uj.mp4", vo="vo_v2.mp3", total=12.55,
               seg=[(0.0, 4.14, 0.0, 4.9), (4.14, 5.5, 5.6, 7.25), (5.5, 6.5, 7.3, 8.5), (6.5, 7.8, 8.4, 9.37),
                    (7.8, 10.7, 9.4, 11.6), (10.7, 12.55, 11.6, 13.2)]),
    "v3": dict(src="DdZ5O2bR39c.mp4", vo="vo_v3.mp3", total=9.85,
               seg=[(0.0, 4.74, 0.0, 3.53), (4.74, 5.6, 3.55, 4.4), (5.6, 6.56, 5.1, 6.2), (6.56, 9.85, 6.2, 10.2)]),
}


# R3-6 «ответ на комментарий»: карточка TikTok «Reply to <ник>'s comment» на ВЕСЬ ролик (юзер 2026-11-05) — ролик
# выглядит как ответ, озвучка отвечает на вопрос. Место — одно на весь ролик, проверено по всем сценам:
#   v1 — крупная карточка ровно поверх их подписи «Every Christmas lover NEEDS this» (статична весь ролик, 204–876×384–520);
#   v2 — сверху, как в V1 (их нижняя подпись стёрта LaMa — clean_xmas_v2_caption.py);
#   v3 — справа на уровне лестницы (их «Back Then / VS / Now» остаются — это сюжет до/после).
# (ник, вопрос, центр x, центр y, кегль, ширина колонки в кеглях)
REPLY = {"v1": ("jess.holiday", "what is this and where do i get it 😭", 540, 452, 48, 15),
         "v2": ("mia_sleighs", "is this real?? i need it for my mom 😭", 540, 452, 48, 15),
         "v3": ("emilyrose.home", "how did you do the ceiling??", 750, 740, 36, 9)}


def reply_png(key: str, dest: Path) -> tuple[int, int]:
    import core.comment_sticker as CS
    sys.path.insert(0, str(ROOT))
    from core.safe_zones import check_box
    nick, text, cx, cy, px, col = REPLY[key]
    CS.COLUMN_MAX = col
    img = CS.render_reply_sticker(nick, text, body_px=px, avatar_seed=nick)
    img.save(dest)
    x, y = int(cx - img.width / 2), int(cy - img.height / 2)
    x = max(140 - 12, min(x, 940 + 12 - img.width))   # поля карточки могут чуть выйти за рамку, текст — нет
    if bad := check_box(W, H, (x + 14, y + 10, x + img.width - 14, y + img.height - 10)):
        raise SystemExit(f"карточка вне безопасной зоны: {key} {bad}")
    return x, y


def build(key: str, out: Path, reply: bool = False) -> Path:
    v = VIDS[key]
    import xmas_r3_common as XC
    src = XC.source(key)                                # V2 — очищенный от нижней подписи (LaMa)
    inputs, fc = [], []
    for i, (a, b, s0, s1) in enumerate(v["seg"]):
        nfr = round(b * FPS) - round(a * FPS)
        k = (nfr / FPS) / (s1 - s0)
        inputs += ["-ss", f"{s0:.3f}", "-t", f"{s1 - s0 + 0.15:.3f}", "-i", str(src)]
        fc.append(f"[{i}:v]setpts={k:.4f}*(PTS-STARTPTS),fps={FPS},scale={W}:{H}:flags=lanczos,setsar=1,"
                  f"trim=end_frame={nfr},setpts=PTS-STARTPTS[t{i}]")
    n = len(v["seg"])
    fc.append("".join(f"[t{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0,format=yuv420p[v]")
    ai = n
    out.mkdir(parents=True, exist_ok=True)
    tp = None if reply else XC.title_png(key, out / f"_title_{key}.png")   # с карточкой ответа заголовок не нужен
    if tp:                                              # заголовок сверху (V2: их нижний текст, перенесённый наверх)
        inputs += ["-loop", "1", "-t", f"{v['total'] + 0.1:.2f}", "-i", str(out / f"_title_{key}.png")]
        fc[-1] = fc[-1].replace("[v]", "[vt]")
        fc.append(f"[{n}:v]format=rgba[tt];[vt][tt]overlay={tp[0]}:{tp[1]}:shortest=1,format=yuv420p[v]")
        ai = n + 1
    if reply:
        card = out / f"_reply_{key}.png"
        out.mkdir(parents=True, exist_ok=True)
        x, y = reply_png(key, card)
        inputs += ["-loop", "1", "-t", f"{v['total'] + 0.1:.2f}", "-i", str(card)]
        fc[-1] = fc[-1].replace("[v]", "[v0]")
        fc.append(f"[{n}:v]format=rgba[rc];[v0][rc]overlay={x}:{y}:shortest=1,format=yuv420p[v]")
        ai = n + 1
    inputs += ["-i", str(VO / v["vo"]), "-stream_loop", "-1", "-i", str(MUSIC)]
    fc.append(f"[{ai}:a]aresample=44100,loudnorm=I=-15:TP=-1.5:LRA=11,apad[vo];[{ai + 1}:a]aresample=44100,volume=0.12[m];"
              f"[vo][m]amix=inputs=2:normalize=0:duration=first,atrim=0:{v['total']:.3f}[a]")
    dest = out / (f"R3-6_reply_{key}_noid.mp4" if reply else f"R3-3d_vo_original_{key}_noid.mp4")
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
                    "-map", "[v]", "-map", "[a]", "-t", f"{v['total']:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    if reply:
        card.unlink()
    if tp:
        (out / f"_title_{key}.png").unlink()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "xmas_r3" / "R3-3d_vo_original")
    ap.add_argument("--only", default="v1,v2,v3")
    ap.add_argument("--reply", action="store_true", help="R3-6: + карточка «Reply to …'s comment» на весь ролик")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for key in a.only.split(","):
        print("  ", build(key, a.out, a.reply), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
