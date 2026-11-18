#!/usr/bin/env python3
"""
Понятная витрина ffmpeg-skill: по одному ролику на функцию — «ДО | ПОСЛЕ» рядом, сверху по-русски,
какой инструмент и что именно применено. Берёт сырые результаты try_ffmpeg_skill.py
(output/_work/ffmpeg_skill_test/raw) и исходники (…/src) → output/ffmpeg_skill_test.

  python make_ffmpeg_skill_demo.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.safe_zones import check_box  # noqa: E402  (рамка 9:16: текст в x 140–940, y 200–1540)

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
WORK = ROOT / "output" / "_work" / "ffmpeg_skill_test"
RAW, SRC, OUT = WORK / "raw", WORK / "src", ROOT / "output" / "ffmpeg_skill_test"
W, H = 1080, 1920
PW, PH = 520, 924                       # панель «до»/«после»
PY = 520                                # верх панелей (под 3 строки описания)
FONT_B = str(ROOT / "fonts" / "TikTokSans-Bold.ttf")
FONT_S = str(ROOT / "fonts" / "TikTokSans-SemiBold.ttf")
MAXLEN = 10.0

# (сырой результат, исходник «до» или None, файл, заголовок, что применено — строки по смыслу)
DEMOS = [
    ("10_cut_two_segments.mp4", "talk.mp4", "01_нарезка_кусков", "cut.py — нарезка",
     ["взял куски 0–1,9 с и 4,3–7,6 с", "и склеил их встык"]),
    ("26_silence_cut_pauses.mp4", "talk.mp4", "02_вырезать_паузы", "silence.py — паузы",
     ["вырезал тишину в речи", "(порог −35 дБ, пауза от 0,4 с)"]),
    ("13_fit_duration_5s_speed.mp4", "talk.mp4", "03_подогнать_под_5с", "fit.py — под длину",
     ["ускорил ролик целиком,", "чтобы он длился ровно 5 с"]),
    ("11_fit_1x1_blur.mp4", "talk.mp4", "04_квадрат_с_блюром", "fit.py — формат 1:1",
     ["9:16 → квадрат,", "по бокам размытый фон"]),
    ("12_fit_4x5_crop.mp4", "talk.mp4", "05_формат_4x5", "fit.py — формат 4:5",
     ["9:16 → 4:5 обрезкой", "сверху и снизу"]),
    ("14_fit_flip_h.mp4", "face.mp4", "06_зеркало", "fit.py — зеркало",
     ["отразил по горизонтали"]),
    ("15_speedramp_slowmo_middle.mp4", "jump.mp4", "07_слоумо_в_середине", "speedramp.py — скорость",
     ["0–1,5 с обычно → 1,5–3,5 с слоумо 0,4×", "→ дальше ускорение 1,5×"]),
    ("16_freeze_frame.mp4", "jump.mp4", "08_стоп_кадр", "freeze.py — стоп-кадр",
     ["на 2-й секунде кадр замирает", "на 1,5 с"]),
    ("17_reverse.mp4", "jump.mp4", "09_реверс", "reverse.py — реверс", ["видео задом наперёд"]),
    ("18_loop_boomerang.mp4", "jump2s.mp4", "10_бумеранг", "loop.py — бумеранг",
     ["2 с прыжка: вперёд-назад", "3 раза подряд"]),
    ("22_broll_jump_into_talk.mp4", "talk.mp4", "11_вставка_брол", "broll.py — вставка",
     ["с 3-й секунды на 2,5 с показан прыжок,", "звук речи не прерывается"]),
    ("23_join_slideleft.mp4", "face.mp4", "12_склейка_с_переходом", "join.py — склейка",
     ["3 клипа подряд,", "переход «сдвиг влево» 0,4 с"]),
    ("24_grid_2x2.mp4", None, "13_сетка_2x2", "grid.py — сетка", ["4 клипа одновременно", "в сетке 2×2"]),
    ("20_insert_image_zoom_in.mp4", "image.jpg", "14_картинка_в_видео", "insert.py — фото → видео",
     ["слайд карусели → видео 3 с", "с медленным наездом"]),
    ("05_crop_from_cropdetect.mp4", "letterbox.mp4", "15_убрать_черные_полосы", "cropdetect + crop",
     ["сам нашёл чёрные полосы", "и обрезал их"]),
    ("30_straighten_minus4.mp4", "face.mp4", "16_выровнять_горизонт", "straighten.py — наклон",
     ["повернул на −4°", "и обрезал углы"]),
    ("33_stabilize_jump.mp4", "jump.mp4", "17_стабилизация", "stabilize.py — стабилизация",
     ["убрал тряску камеры", "(зум 5 %, чтобы не было краёв)"]),
    ("34_redact_pixelate.mp4", "talk.mp4", "18_пикселизация_области", "redact.py — скрыть область",
     ["запикселил прямоугольник", "внизу кадра (можно блюр)"]),
    ("36_color_hlg_to_sdr.mp4", "hlg.mov", "19_hdr_айфона_в_обычный", "color.py — HDR → SDR",
     ["HDR-видео с айфона (HLG)", "→ обычные цвета"]),
    ("37_color_lut_warm.mp4", "face.mp4", "20_lut_теплый", "color.py — LUT", ["наложил тёплый LUT (.cube)"]),
    ("38_color_correct.mp4", "face.mp4", "21_цветокоррекция", "color.py — коррекция",
     ["экспозиция +0,1, контраст 1,15,", "насыщенность 1,25, теплее (5200 K)"]),
    ("39_color_curves_vintage.mp4", "face.mp4", "22_кривые_винтаж", "color.py — кривые",
     ["готовые кривые «vintage»"]),
    ("40_caption_karaoke_word.mp4", "talk.mp4", "23_субтитры_по_словам", "caption.py — субтитры",
     ["по словам: текущее слово", "жёлтое и крупнее, появление «pop»"]),
    ("41_caption_karaoke_sweep_center.mp4", "talk.mp4", "24_субтитры_караоке", "caption.py — караоке",
     ["заливка цветом по словам,", "текст по центру"]),
    ("42_caption_box_emoji.mp4", "talk.mp4", "25_субтитры_плашка_эмодзи", "caption.py — плашка + эмодзи",
     ["субтитры на чёрной плашке", "+ эмодзи (встаёт криво, справа)"]),
    ("44_overlay_logo_fade.mp4", "talk.mp4", "26_логотип", "overlay.py — логотип",
     ["лого в правом верхнем углу", "с плавным появлением"]),
    ("45_overlay_text_box.mp4", "face.mp4", "27_текст_на_плашке", "overlay.py — текст",
     ["простой текст на плашке", "(эмодзи тут не умеет)"]),
    ("46_overlay_greenscreen_kitten.mp4", "jump.mp4", "28_хромакей_котенок", "overlay.py — хромакей",
     ["вырезал зелёный фон", "и наложил котёнка сверху"]),
    ("47_overlay_pip.mp4", "talk.mp4", "29_картинка_в_картинке", "overlay.py — окно в окне",
     ["второе видео в углу", "с белой рамкой"]),
    ("48_graphics_hook.mp4", "talk.mp4", "30_хук_плашка", "graphics.py — хук",
     ["плашка-хук на первые секунды"]),
    ("49_graphics_meme.mp4", "jump.mp4", "31_мем_текст", "graphics.py — мем", ["текст сверху и снизу"]),
    ("50_graphics_lower_third.mp4", "talk.mp4", "32_плашка_с_именем", "graphics.py — имя",
     ["плашка с именем и подписью", "(как в интервью)"]),
    ("51_graphics_sticker.mp4", "face.mp4", "33_стикер", "graphics.py — стикер", ["жёлтый стикер «LINK IN BIO»"]),
    ("52_graphics_progress.mp4", "talk.mp4", "34_полоса_прогресса", "graphics.py — прогресс",
     ["полоска внизу растёт", "до конца ролика"]),
    ("53_graphics_countdown.mp4", "jump.mp4", "35_обратный_отсчет", "graphics.py — отсчёт", ["цифры 3-2-1"]),
    ("54_graphics_title.mp4", "face.mp4", "36_титр", "graphics.py — титр", ["титр с подзаголовком"]),
    ("60_audio_music_ducked_under_voice.mp4", "talk.mp4", "37_музыка_под_голос", "audio.py — музыка под речь",
     ["СЛУШАТЬ СО ЗВУКОМ:", "музыка 1353 под речь,", "тише, когда она говорит"]),
    ("61_audio_replace_with_music.mp4", "face.mp4", "38_замена_звука", "audio.py — замена звука",
     ["СЛУШАТЬ СО ЗВУКОМ:", "родной звук заменён музыкой"]),
    ("63_loudness_minus14.mp4", "talk.mp4", "39_громкость_минус14", "loudness.py — громкость",
     ["СЛУШАТЬ СО ЗВУКОМ:", "выровнял до −14 LUFS (норма соцсетей)"]),
    ("65_waveform_over_image.mp4", "image.jpg", "40_аудиограмма", "waveform.py — волна",
     ["картинка + звуковая волна", "под музыку"]),
    ("68_multicam_auto_2s.mp4", "talk.mp4", "41_две_камеры", "multicam.py — 2 камеры",
     ["сам выровнял 2 камеры по звуку", "и переключает их каждые 2 с"]),
    ("84_render_template_tiktok.mp4", "talk.mp4", "42_шаблон_tiktok", "render.py — шаблон TikTok",
     ["одной командой: субтитры,", "лого и титр в начале"]),
]


def dur(p: Path) -> float:
    out = subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0             # картинка


def has_audio(p: Path) -> bool:
    return bool(subprocess.run([FP, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                                "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip())


def card(title: str, lines: list[str], before: bool, extra: str, dest: Path) -> None:
    """Подложка 1080×1920: заголовок, что применено, подписи ДО/ПОСЛЕ — всё в безопасной рамке 9:16."""
    im = Image.new("RGBA", (W, H), (17, 17, 20, 255))
    d = ImageDraw.Draw(im)
    boxes = []
    _text = d.text

    def text(xy, s, **kw):          # каждый текст — в отчёт о безопасной рамке
        boxes.append(d.textbbox(xy, s, font=kw["font"], anchor=kw.get("anchor")))
        _text(xy, s, **kw)
    d.text = text
    ft, fs, fl = ImageFont.truetype(FONT_B, 52), ImageFont.truetype(FONT_S, 38), ImageFont.truetype(FONT_B, 34)
    y = 210
    d.text((W // 2, y), title, font=ft, fill=(255, 210, 0), anchor="ma")
    y += 78
    for ln in lines:
        d.text((W // 2, y), ln, font=fs, fill=(255, 255, 255), anchor="ma")
        y += 50
    if before:
        d.text((20 + PW // 2, PY - 46), "ДО", font=fl, fill=(170, 170, 170), anchor="ma")
        d.text((W - 20 - PW // 2, PY - 46), "ПОСЛЕ", font=fl, fill=(255, 210, 0), anchor="ma")
    if extra:
        d.text((W // 2, PY + PH + 30), extra, font=fs, fill=(200, 200, 200), anchor="ma")
    # панели прозрачные — под ними видео
    if before:
        d.rectangle((20, PY, 20 + PW - 1, PY + PH - 1), fill=(0, 0, 0, 0))
        d.rectangle((W - 20 - PW, PY, W - 21, PY + PH - 1), fill=(0, 0, 0, 0))
    else:
        d.rectangle(((W - PW) // 2, PY, (W + PW) // 2 - 1, PY + PH - 1), fill=(0, 0, 0, 0))
    for bx in boxes:
        for warn in check_box(W, H, tuple(int(v) for v in bx)):
            print(f"  ! {dest.stem}: {warn}", flush=True)
    im.save(dest)


def fit_panel(label: str, src_is_image: bool) -> str:
    loop = "loop=-1:1:0," if src_is_image else ""
    return (f"{loop}scale={PW}:{PH}:force_original_aspect_ratio=decrease,pad={PW}:{PH}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps=30,setsar=1,tpad=stop_mode=clone:stop_duration={MAXLEN}[{label}]")


def build(raw: str, before: str | None, name: str, title: str, lines: list[str]) -> None:
    after = RAW / raw
    b = SRC / before if before else None
    da = dur(after)
    db = dur(b) if b and b.suffix != ".jpg" else 0.0
    L = min(MAXLEN, max(da, db) or da)
    extra = f"длина: {db:.1f} с → {da:.1f} с".replace(".", ",") if db and abs(da - db) > 0.25 else ""
    png = WORK / "cards" / f"{name}.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    card(title, lines, b is not None, extra, png)
    ins = ["-i", str(png)]
    if b:
        ins += (["-loop", "1", "-t", str(L)] if b.suffix == ".jpg" else []) + ["-i", str(b)]
    ins += ["-i", str(after)]
    ai = 2 if b else 1
    fc = []
    if b:
        fc.append(f"[1:v]{fit_panel('pb', False)}")
        fc.append(f"[{ai}:v]{fit_panel('pa', False)}")
        fc.append(f"[0:v]loop=-1:1:0,fps=30,trim=duration={L:.3f}[bg];[bg][pb]overlay=20:{PY}:shortest=1[t1];"
                  f"[t1][pa]overlay={W - 20 - PW}:{PY}:shortest=1,format=yuv420p[v]")
    else:
        fc.append(f"[{ai}:v]{fit_panel('pa', False)}")
        fc.append(f"[0:v]loop=-1:1:0,fps=30,trim=duration={L:.3f}[bg];[bg][pa]overlay={(W - PW) // 2}:{PY}:shortest=1,"
                  f"format=yuv420p[v]")
    amap = []
    if has_audio(after):
        fc.append(f"[{ai}:a]apad,atrim=duration={L:.3f}[a]")
        amap = ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    subprocess.run([FF, "-v", "error", "-y", *ins, "-filter_complex", ";".join(fc), "-map", "[v]", *amap,
                    "-t", f"{L:.3f}", "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "23", "-b:v", "0",
                    "-maxrate", "6M", "-bufsize", "12M", "-movflags", "+faststart", str(OUT / f"{name}.mp4")],
                   check=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1:]
    for raw, before, name, title, lines in DEMOS:
        if only and not any(x in name for x in only):
            continue
        build(raw, before, name, title, lines)
        print("✓", name, flush=True)
    print("готово →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
