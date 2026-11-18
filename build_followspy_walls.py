#!/usr/bin/env python3
"""
FollowSpy / без продукта (айди нет): текстволлы как в рефах — один спокойный UGC-клип девушки на фоне (база Влада =
кадры Global Work: downloads/gw_wall2/srcA — девушка A, SDR; srcB — девушка B, HLG → tonemap hable npl 120),
по центру белый TikTok-текст с тонкой чёрной обводкой (core/renderer, как нативный TikTok), списки — белые плашки
с чёрным текстом (как реф milana). Звук — музыка рефа этого текста, длина ролика = длина рефа.
Тексты ТЗ дословно, переносы по смыслу. 2 части × 10 текстов × 2 версии (v1 — девушка A, v2 — девушка B):
  output/followspy/part1_followspy/p1_NN_vK_noid.mp4, output/followspy/part2_no_product/p2_NN_vK_noid.mp4.

  python build_followspy_walls.py --only p1_01_v1,p1_06_v2 --out output/followspy_test
  python build_followspy_walls.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build_1307_carousels as P  # noqa: E402  (белые TikTok-плашки)
import build_gw_wall_reels as WL  # noqa: E402  (текстволл, спокойное окно клипа, безопасная зона)
from core.safe_zones import check_overlay  # noqa: E402

W, H, FPS = 1080, 1920, 30
REFS = ROOT / "downloads" / "followspy" / "refs"
SRC = {"A": ROOT / "downloads" / "gw_wall2" / "srcA", "B": ROOT / "downloads" / "gw_wall2" / "srcB"}
# 5667 и 5672 сняты вечером (яркость 37 и 23 из 255) — вытягивать = шум, не берём
CLIPS = {"A": ["IMG_5663", "IMG_5664", "IMG_5665", "IMG_5668", "IMG_5669", "IMG_5670"],
         "B": ["IMG_8101", "IMG_8102", "IMG_8103", "IMG_8104", "IMG_8105", "IMG_8107", "IMG_8108"]}
EQ = {"IMG_5664": "eq=gamma=1.35:saturation=1.06,", "IMG_5668": "eq=gamma=1.15:saturation=1.04,"}   # мягко светлее
HLG = "zscale=t=linear:npl=120,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,"
OUT = ROOT / "output" / "followspy"
FOLDER = {1: "part1_followspy", 2: "part2_no_product"}
NL = "\n"

# (реф, текст): \n — перенос по смыслу, \n\n — отдельный абзац; LIST — заголовок и пункты плашками (строки пункта — \n)
P1 = [
    ("tt_cat", "He swore he unfollowed\nhis ex months ago.\nI checked FollowSpy.\nHe did.\nThen he followed her again\n"
               "from a new account\n3 days later"),
    ("tt_roxanne", "He asked me to stop posting us\nbecause his followers are\n\"mostly work people.\"\nFine. I respected it.\n"
                   "Then I checked FollowSpy.\nThat same week he followed\n14 new girls.\nNot one coworker. Not one boss.\n"
                   "Just bikini pics\nand \"link in bio.\"\nHe didn't want his followers\nto see me.\nHe wanted them\n"
                   "to think he's single.\nIf he hides you online,\nhe's hiding you everywhere."),
    ("tt_sofiia", "crazy?\nFollowSpy showed me\nmy boyfriend followed\nmy best friend's private account\nat 3am.\n"
                  "so I made a group chat\nwith both of them\nand just sent the screenshot.\nno caption.\nthey both left the chat"),
    ("ig_DVt8", "he can say \"you're the only one\"\na million times\nbut i'll never believe it\n"
                "bc you don't follow 6 new girls\nthe week of our anniversary\nif i'm genuinely the only one.\n"
                "FollowSpy doesn't lie,\nhe does"),
    ("tt_bridget", "He said \"I don't even use\nInstagram anymore.\"\nI almost believed him.\nThen he got mad\n"
                   "that I \"never trust him.\"\nI felt crazy.\nI checked FollowSpy.\n31 new follows this month.\nAll girls.\n"
                   "Most of them at 2am.\nHe doesn't use Instagram.\nHe just uses it\nwhen I'm asleep"),
    ("tt_milana", ["SIGNS HE'S TALKING\nTO SOMEONE ELSE:", "1. His phone is always face down.",
                   "2. He's suddenly \"busy\"\nevery Thursday night.", "3. FollowSpy shows he followed\nthe same girl twice.",
                   "4. He gets mad when you ask\na normal question.", "5. He starts calling you\n\"too insecure.\""]),
    ("ig_Dcib", "my sister's fiancé had the perfect\nexcuse for every weekend.\n\"work trip.\" \"guys' night.\"\n\"phone died.\"\n"
                "she trusted him for 3 years.\ntwo weeks before the wedding\nshe checked FollowSpy\njust to be sure.\n"
                "every \"work trip\" he followed girls\nfrom the same city.\nsame dates. same pattern.\n"
                "she didn't cancel the wedding.\nshe stood up at the rehearsal dinner,\ntook the mic and read\n"
                "every date out loud.\nhis mom started clapping.\n\nand honestly? she should have."),
    ("tt_polyglot", "my boyfriend said he followed her\n\"by accident\" while scrolling.\nI smiled because\n"
                    "it sounded so innocent.\nFollowSpy says\nhe had the same accident\n4 times this month"),
    ("tt_kia", "Really annoyed my boyfriend's\nbest friend at the party\nlast night bc he said\n\"he's not like that\"\n"
               "and I said \"oh no I know\"\nand he laughed\nand said it again\nand my reply was just\n"
               "a deadpan \"no I'm serious,\nI checked FollowSpy,\nhe's exactly like that\""),
    ("ig_DYBG", "no literally wdym he said\n\"she's just a coworker\"\nso i let it go.\ntoday he called her\n"
                "\"the only one who gets me.\"\ni checked FollowSpy.\nhe followed her 2 months\n"
                "before she even started at his job.\ncoworker is just a job title now"),
]
P2 = [
    ("tt_kait", "btw my mother in law\nwore a white dress to my wedding.\nmy husband didn't say a word.\nat the reception\n"
                "he handed her a gift bag.\ninside was the receipt for the dress\nand a note that said\n"
                "\"you can still return it.\"\nshe left before dessert"),
    ("tt_cat", "My husband said\nhe spent the whole weekend\nat his brother's.\nHis brother called me on Saturday\n"
               "asking where he was"),
    ("tt_sofiia", "crazy?\nmy boyfriend cheated\nso I didn't break up with him.\nI waited till his birthday party,\n"
                  "gave a speech and thanked\nthe girl he cheated with\nfor \"keeping him busy\nwhile I finished my degree.\"\n"
                  "everyone clapped.\nshe was in the room"),
    ("ig_DVt8", "he can say \"i was drunk,\nit meant nothing\" a million times\nbut i'll never believe it\n"
                "bc you don't delete the messages,\nthe call log AND the photos\nif it genuinely meant nothing"),
    ("tt_roxanne", "He forgot my birthday. Again.\nSaid he was \"slammed at work.\"\nThat same night he posted a story\n"
                   "from a rooftop bar.\nTagged the location.\nTagged his friends.\nTagged a girl I'd never heard of.\n"
                   "I didn't text him.\nI went to the rooftop.\nShe was there.\nShe was celebrating\nher birthday too.\n"
                   "He didn't forget my birthday.\nHe just picked hers."),
    ("tt_bridget", "My sister said she couldn't afford\nto come to my wedding.\nI offered to pay for her flight.\n"
                   "She said no, \"it's the principle.\"\nI felt guilty for weeks.\nThen I saw her Instagram.\n"
                   "Cancun. Same weekend.\nShe didn't skip my wedding\nbecause of money.\nShe skipped it\nbecause it was mine"),
    ("ig_Dcib", "my dad left when i was 7.\nnever called. never paid a cent.\nlast month he showed up\n"
                "at my graduation with flowers\nlike nothing happened.\nmy mom just smiled\nand pointed at me.\n"
                "i walked right past him.\nthen my stepdad walked up\nand handed him the program,\n"
                "opened to the page where i thanked\n\"the man who raised me.\"\nit had my stepdad's name on it.\n\n"
                "and honestly? that was\nthe only gift he deserved."),
    ("tt_polyglot", "my boyfriend said \"let's split\neverything 50/50, it's only fair.\"\nI smiled because\n"
                    "it sounded so fair.\nso I sent him the bill\nfor half the cooking,\nhalf the cleaning\n"
                    "and half the gifts\nI bought for his mom.\nhe's been quiet ever since"),
    ("tt_kia", "Really embarrassed a guy\nat a wedding last night\nbc he walked up and said\n\"you look just like my ex\"\n"
               "and I said \"oh that's sad\"\nand he laughed and said\n\"no it's a compliment\"\n"
               "and my reply was just a deadpan\n\"no I meant for her,\nshe's my cousin\nand she told me everything\""),
    ("tt_milana", ["THINGS MY GRANDMA TOLD ME\nTHAT I NEVER FORGOT:", "1. If he's sorry, he'll change.\nIf he just says sorry, he won't.",
                   "2. Never cry in front of\nthe person who made you cry.", "3. Always keep money\nhe doesn't know about.",
                   "4. A man who's rude to waiters\nwill be rude to you.", "5. Marry the one\nwho's kind when he's tired."]),
]
WALL_CY = (WL.Y0 + WL.Y1) // 2


def dur(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)


def wall_png(text: str, dest: Path) -> None:
    """Самый крупный кегль (≤ 56), при котором строки не переносятся сами и блок влезает в безопасную зону; по центру."""
    n_lines = len([ln for ln in text.split(NL) if ln.strip()])
    px = 56
    while px > 26 and (WL.wall_height(text, px) > WL.Y1 - WL.Y0 - 8 or
                       len([x for x in WL.wall_lines(text, px) if x]) > n_lines):
        px -= 1
    top = max(WL.Y0 + 4, int(WALL_CY - WL.wall_height(text, px) / 2))
    WL.render_wall(text, px, top, dest)


def plates_png(items: list[str], dest: Path) -> None:
    """Список как в рефе milana: заголовок и каждый пункт — своя белая плашка, чёрный текст, по центру, с зазорами."""
    clean = lambda s: P.C.B.A.sanitize_overlay_text(P.C.B.R._normalize_text(s))  # noqa: E731
    for px in range(54, 30, -2):
        blocks = [P.plate_block([clean(ln) for ln in it.split(NL)], px) for it in items]
        gap = int(px * 0.55)
        h = sum(b.height for b in blocks) + gap * (len(blocks) - 1)
        if max(b.width - 2 * int(0.42 * px) for b in blocks) <= WL.X1 - WL.X0 - 10 and h <= WL.Y1 - WL.Y0 - 20:
            break
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    y = int(WALL_CY - h / 2)
    for b in blocks:
        img.alpha_composite(b, ((W - b.width) // 2, y))
        y += b.height + gap
    pad = int(0.42 * px)                                     # поля плашек — не текст: проверяем зону по самим строкам
    a = img.getchannel("A").point(lambda v: 255 if v > 0 else 0)
    box = a.getbbox()
    inner = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    inner.paste((255, 255, 255, 255), (box[0] + pad, box[1] + pad // 2, box[2] - pad, box[3] - pad // 2))
    if bad := check_overlay(inner):
        raise SystemExit(f"плашки вне безопасной зоны: {bad}")
    img.save(dest)


def plan() -> list[dict]:
    """Каждому тексту — 2 версии: v1 на клипе девушки A, v2 — девушки B. Клип — наименее использованный из тех,
    чьё спокойное окно не короче музыки; повторное использование клипа — другое окно и зеркало."""
    rng_cache: dict[str, tuple[float, float]] = {}

    def usable(g: str, c: str) -> tuple[float, float]:
        if c not in rng_cache:
            WL.SRC = SRC[g]
            rng_cache[c] = WL.usable_range(c)
        return rng_cache[c]
    uses = {c: 0 for g in CLIPS for c in CLIPS[g]}
    rows = []
    for part, texts in ((1, P1), (2, P2)):
        for n, (ref, text) in enumerate(texts, 1):
            d = dur(REFS / f"{ref}.mp4")
            for k, g in enumerate("AB", 1):
                ok = [c for c in CLIPS[g] if usable(g, c)[1] - usable(g, c)[0] >= d + 0.2]
                c = min(ok, key=lambda x: (uses[x], CLIPS[g].index(x)))
                a, b = usable(g, c)
                u = uses[c]
                uses[c] += 1
                room = (b - a) - d
                start = a + (room * (0.15 + 0.35 * (u % 3)) if room > 0 else 0)
                rows.append(dict(name=f"p{part}_{n:02d}_v{k}", part=part, n=n, ref=ref, text=text, group=g, clip=c,
                                 start=round(start, 2), dur=round(d, 3), mirror=u % 2))
    return rows


def render(r: dict, out: Path, work: Path) -> Path:
    wall = work / f"{r['name']}.png"
    (plates_png if isinstance(r["text"], list) else wall_png)(r["text"], wall)
    src = SRC[r["group"]] / f"{r['clip']}.MOV"
    tone = (HLG if r["group"] == "B" else "") + EQ.get(r["clip"], "")
    a, d = r["start"], r["dur"]
    fc = (f"[0:v]trim=start={a:.3f}:duration={d:.3f},setpts=PTS-STARTPTS,{tone}scale={W}:{H}:flags=lanczos:"
          f"force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1{',hflip' if r['mirror'] else ''}[b];"
          f"[b][1:v]overlay=0:0,format=yuv420p[v];"
          f"[2:a]atrim=end={d:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={max(0, d - 0.3):.3f}:d=0.3,"
          f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[a]")
    dest = out / FOLDER[r["part"]] / f"{r['name']}_noid.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-i", str(wall), "-i", str(REFS / f"{r['ref']}.mp4"),
                    "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{d:.3f}",
                    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "27", "-maxrate", "6M", "-bufsize", "12M",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-metadata:s:v:0", "encoder=", "-metadata:s:v:0", "handler_name=",
                    "-metadata:s:a:0", "handler_name=", "-movflags", "+faststart", str(dest)], check=True)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--only", default="", help="через запятую: p1_01_v1,p2_07_v2 …")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = plan()
    if a.only:
        keep = set(a.only.split(","))
        rows = [r for r in rows if r["name"] in keep]
    work = a.out / "_work"
    work.mkdir(parents=True, exist_ok=True)
    for r in rows:
        dest = render(r, a.out, work)
        print(f"  {dest.relative_to(a.out)}  {r['clip']}{' зеркало' if r['mirror'] else ''}  {r['dur']:.1f} с", flush=True)
    for f in work.glob("*.png"):
        f.unlink()
    work.rmdir()
    (a.out / "manifest.json").write_text(json.dumps([{k: v for k, v in r.items() if k != "text"} for r in rows],
                                                   indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"готово: {len(rows)} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
