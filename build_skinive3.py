#!/usr/bin/env python3
"""
skinive_3 (айди нет), 150 шт. ТЗ «Запись только в марте» (реф Flo @jaqueline_floapp, 9–11 с):
  0–3 с     женский реакт (усталость/тревога) — downloads/skinive3/proxy/copy_C9D09E69…mp4, окна отсмотрены;
  3–6 с     родинка крупно — кэш make_skinive3_moles.py (родинки в кругах маркером, ведутся оптическим потоком);
  6–~9.4 с  скан: App Store (страница Skinive → тап «Open» → открытие, обязательный кадр стора, ТЗ) → фото родинки
            в редакторе → «Skinive AI verarbeitet…»;
  посл. 1.2 с плашка-результат (шкала 100 % Gutartiger Nävus или «Geringes Risiko»).
Экраны приложения целиком, уменьшены до 0.75 и стоят под подписью (раскладка fit из skinive_2, поля — краевым цветом).
Текст ТЗ дословно, сверху, белый TikTok-шрифт с ровной чёрной обводкой (outline_text из build_skinive2), по шагам:
  «POV: … aussieht 👀» на лице → «du rufst beim hautarzt an» → «nächster termin: MÄRZ 🙂» на родинке →
  «du scannst es mit Skinive / und siehst DAS 👇» на скане и результате.
Звук — трек рефа skinive_2 по кругу (в ТЗ нет). Все исходники — 1080p-прокси (правило «1080p всегда»).
TT и YT одинаковые: YT = копия TT (только для этого проекта, юзер 2026-11-06).

  python build_skinive3.py --only 1,2 --out output/_work/skinive3_test
  python build_skinive3.py -n 150 --jobs 5 --out output/skinive3_TT_150
"""

from __future__ import annotations

import argparse
import itertools
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_skinive2 as S2  # noqa: E402  (outline_text, music_loop)
import build_skinive_walls as SW  # noqa: E402  (тайминги стора/приложения)
from core.safe_zones import check_box  # noqa: E402

W, H, FPS = 1080, 1920, 30
D = ROOT / "downloads" / "skinive3" / "proxy"
FACE = D / "copy_C9D09E69-1675-4B0B-86B4-24EF5AAF998F.mp4"
MOLES = ROOT / "output" / "_work" / "skinive3" / "moles"
MOLE_IDS = ["c1", "c3", "a1", "a2", "a3"]
# окна лица (старт, 3 с): осматривает кожу/трогает щёку, хмурится, тревожный взгляд — под «замечаешь, что родинка странная»
FACES = [1.5, 8.0, 12.5, 18.5, 32.0]
T_FACE, T_MOLE = 3.0, 3.0
STORE0 = 8.70                                 # стор: статичная страница → тап «Open» 9.40 → открытие до 9.90 (1.2 с)
PH, PH_LEN = (45.80, 46.82), 0.6              # фото в редакторе (статично)
P_LEN, R_LEN = 1.4, 1.2                       # анализ (ускоренно), плашка-результат
FIT_TOP, FIT_SCALE = 400, 0.75
TEXTS = [
    (["POV: du merkst, dass dein muttermal", "irgendwie komisch aussieht 👀"], 0.0, T_FACE),
    (["du rufst beim hautarzt an"], T_FACE, T_FACE + 1.5),
    (["nächster termin: MÄRZ 🙂"], T_FACE + 1.5, T_FACE + T_MOLE),
    (["du scannst es mit Skinive", "und siehst DAS 👇"], T_FACE + T_MOLE, 99.0),
]
CAP_PX, CAP_TOP = 54, 214


def text_pngs(work: Path) -> list[Path]:
    """Один кегль на все реплики: самый крупный, при котором самая широкая строка влезает в 790 px."""
    from core import renderer as R
    import assemble_ugc_reels as A
    px = CAP_PX
    while True:
        font, st = R._load_font(px), max(2, round(px * S2.STROKE))
        e_px = A._emoji_px(px)
        widest = max(sum(e_px * 1.08 if k == "emoji" else font.getlength(c) for k, c in A._tokenize_runs(ln) if c)
                     for lines, _, _ in TEXTS for ln in lines)
        if widest + 2 * st <= 790 or px <= 36:
            break
        px -= 1
    out = []
    for i, (lines, _, _) in enumerate(TEXTS):
        img = S2.outline_text(lines, px, CAP_TOP)
        if bad := check_box(W, H, img.getbbox()):
            raise SystemExit(f"текст вне безопасной зоны: {lines} {bad}")
        p = work / f"t{i}.png"
        img.save(p)
        out.append(p)
    return out


def app_vf(crop_y: int, white: bool) -> str:
    fw, fh = round(W * FIT_SCALE / 2) * 2, round(H * FIT_SCALE / 2) * 2
    x0 = (W - fw) // 2
    base = f"scale={W}:-2:flags=lanczos,crop={W}:{H}:0:{crop_y},scale={fw}:{fh}:flags=lanczos,"
    if white:
        return base + f"pad={W}:{H}:{x0}:{FIT_TOP}:color=white,setsar=1"
    return (base + f"pad={W}:{H}:{x0}:{FIT_TOP},format=yuv444p,fillborders=left={x0}:right={W - fw - x0}:"
            f"top={FIT_TOP}:bottom={H - FIT_TOP - fh}:mode=smear,format=yuv420p,setsar=1")


def plan(n: int, seed: int = 31) -> list[dict]:
    rng = random.Random(seed)
    combos = list(itertools.product(range(len(FACES)), range(len(MOLE_IDS)), ("gauge", "erg"), (0, 1)))
    rows = []
    for k in range(1, n + 1):
        if (k - 1) % len(combos) == 0:
            rng.shuffle(combos)
        f, m, end, mirror = combos[(k - 1) % len(combos)]
        rows.append(dict(n=k, face=f, mole=m, end=end, mirror=mirror, f_off=round(rng.uniform(0, 0.25), 2),
                         m_off=round(rng.uniform(0, 0.1), 2), bri=round(rng.uniform(-0.02, 0.03), 3),
                         sat=round(rng.uniform(1.0, 1.1), 3), zoom=round(rng.uniform(1.0, 1.06), 3)))
    return rows


def render(r: dict, out: Path, work: Path, texts: list[Path]) -> Path:
    name = f"skinive3_{r['n']:03d}"
    s_len = SW.STORE_END - STORE0
    p0, p1 = SW.PROC
    r0, r1 = SW.GAUGE if r["end"] == "gauge" else SW.ERG
    p_speed = (p1 - p0) / P_LEN
    r_speed = (r1 - r0) / (R_LEN - 0.4) if r["end"] == "gauge" else 1.0   # шкала доходит до 100 % и стоит 0.4 с
    r_hold = max(0.0, R_LEN - (r1 - r0) / r_speed)
    nres = round(R_LEN * FPS)
    total = T_FACE + T_MOLE + s_len + PH_LEN + P_LEN + nres / FPS
    grade = f"eq=brightness={r['bri']}:saturation={r['sat']}"
    z = r["zoom"]
    zw, zh = round(W * z / 2) * 2, round(H * z / 2) * 2
    mus = work / f"{name}.wav"
    S2.music_loop(mus, total)
    t_scan = T_FACE + T_MOLE
    fc = (f"[0:v]trim=start={FACES[r['face']] + r['f_off']:.3f}:duration={T_FACE},setpts=PTS-STARTPTS,fps={FPS},"
          f"scale={zw}:{zh},crop={W}:{H},{grade},setsar=1[f];"
          f"[1:v]trim=start={r['m_off']:.3f}:duration={T_MOLE},setpts=PTS-STARTPTS,fps={FPS},{grade}"
          f"{',hflip' if r['mirror'] else ''},setsar=1[m];"
          f"[2:v]trim=start=1:duration={s_len:.3f},setpts=PTS-STARTPTS,fps={FPS},{app_vf(SW.STORE_Y, True)}[s];"
          f"[3:v]trim=start=1:duration={PH[1] - PH[0]:.3f},setpts={PH_LEN / (PH[1] - PH[0]):.4f}*(PTS-STARTPTS),fps={FPS},"
          f"{app_vf(160, False)},trim=duration={PH_LEN},setpts=PTS-STARTPTS[ph];"
          f"[4:v]trim=start=1:duration={p1 - p0:.3f},setpts=(PTS-STARTPTS)/{p_speed:.4f},fps={FPS},{app_vf(150, False)}[p];"
          f"[5:v]trim=start=1:duration={r1 - r0:.3f},setpts=(PTS-STARTPTS)/{r_speed:.4f},fps={FPS},"
          f"tpad=stop_mode=clone:stop_duration={r_hold + 0.2:.3f},{app_vf(150, False)},"
          f"trim=end_frame={nres},setpts=PTS-STARTPTS[r];"
          f"[f][m][s][ph][p][r]concat=n=6:v=1:a=0[b0];")
    cur = "b0"
    for i, (_, a, b) in enumerate(TEXTS):
        fc += f"[{cur}][{6 + i}:v]overlay=0:0:enable='between(t,{a:.3f},{min(b, total):.3f})'[o{i}];"
        cur = f"o{i}"
    fc += f"[{cur}]format=yuv420p[v]"
    dest = out / f"{name}_noid.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(FACE), "-i", str(MOLES / f"{MOLE_IDS[r['mole']]}.mp4"),
                    "-ss", f"{STORE0 - 1:.3f}", "-i", str(SW.STORE), "-ss", f"{PH[0] - 1:.3f}", "-i", str(SW.APP),
                    "-ss", str(p0 - 1), "-i", str(SW.APP), "-ss", str(r0 - 1), "-i", str(SW.APP),
                    *[x for t in texts for x in ("-i", str(t))], "-i", str(mus),
                    "-filter_complex", fc, "-map", "[v]", "-map", f"{6 + len(texts)}:a", "-t", f"{total:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    mus.unlink()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "_work" / "skinive3_test")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = plan(max(a.n, max(map(int, a.only.split(","))) if a.only else 0))
    if a.only:
        keep = set(map(int, a.only.split(",")))
        rows = [r for r in rows if r["n"] in keep]
    a.out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "output" / "_work" / "skinive3"
    work.mkdir(parents=True, exist_ok=True)
    texts = text_pngs(work)
    with ThreadPoolExecutor(a.jobs) as ex:
        for dest in ex.map(lambda r: render(r, a.out, work, texts), rows):
            print(f"  {dest.name}", flush=True)
    print(f"готово: {len(rows)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
