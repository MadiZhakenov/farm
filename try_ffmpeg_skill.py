#!/usr/bin/env python3
"""
Пробный прогон ffmpeg-skill (github.com/kajisho5/ffmpeg-skill, клон в ../ffmpeg-skill) на наших исходниках:
каждый из 42 скриптов скилла хотя бы раз, результаты — output/ffmpeg_skill_test (NN_<инструмент>_<что>.*),
исходники и логи — output/_work/ffmpeg_skill_test. Ничего в проекте не меняет.

  python try_ffmpeg_skill.py            # все тесты
  python try_ffmpeg_skill.py caption    # только тесты, в имени которых есть «caption»
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SK = ROOT.parent / "ffmpeg-skill" / "scripts"
FFBIN = Path(r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin")
FF = str(FFBIN / "ffmpeg.exe")
OUT = ROOT / "output" / "_work" / "ffmpeg_skill_test" / "raw"   # сырые результаты скилла
DEMO = ROOT / "output" / "ffmpeg_skill_test"                  # понятные «до | после» с подписями
WORK = ROOT / "output" / "_work" / "ffmpeg_skill_test"
SRC = WORK / "src"
ENV = {**os.environ, "PATH": str(FFBIN) + os.pathsep + os.environ["PATH"], "PYTHONIOENCODING": "utf-8"}
FONT_FILE = ROOT / "fonts" / "TikTokSans-Bold.ttf"
EMOJI = ROOT / "assets" / "emoji_apple_64"
NV = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "18", "-b:v", "0", "-pix_fmt", "yuv420p"]


def s(name: str) -> str:
    return str(SRC / name)


def ff(*args: str) -> None:
    subprocess.run([FF, "-v", "error", "-y", *args], check=True)


def fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:05.2f}"


def prep() -> None:
    """Короткие вертикальные исходники 1080×1920 из наших клипов + вспомогательные файлы."""
    SRC.mkdir(parents=True, exist_ok=True)
    dl = ROOT / "downloads"
    if not (SRC / "talk.mp4").exists():      # девушка говорит «I got the job…» (gw_gotjob2 A), 13 с
        ff("-t", "13", "-i", str(dl / "gw_gotjob2/srcA/IMG_5700.MOV"), "-vf", "scale=1080:1920,fps=30", *NV,
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", s("talk.mp4"))
    if not (SRC / "jump.mp4").exists():      # прыжки с ноутбуком, 60 fps, 6.3 с
        ff("-ss", "2.2", "-t", "6.3", "-i", str(dl / "gw_jump2/src/IMG_5708.MOV"), "-vf", "scale=1080:1920", *NV,
           "-c:a", "aac", "-b:a", "192k", s("jump.mp4"))
    if not (SRC / "jump2s.mp4").exists():
        ff("-ss", "3.0", "-t", "2", "-i", str(dl / "gw_jump2/src/IMG_5708.MOV"), "-vf", "scale=1080:1920", *NV,
           "-c:a", "aac", s("jump2s.mp4"))
    if not (SRC / "face.mp4").exists():      # «серьёзное лицо» (gw_wall2 srcA), 7 с
        ff("-ss", "2", "-t", "7", "-i", str(dl / "gw_wall2/srcA/IMG_5663.MOV"), "-vf", "scale=1080:1920,fps=30", *NV,
           "-c:a", "aac", s("face.mp4"))
    if not (SRC / "hlg.mov").exists():       # айфон HLG (HDR) как есть
        ff("-t", "6", "-i", str(dl / "gw_gotjob/src/IMG_2937.MOV"), "-c", "copy", "-map", "0:v:0", "-map", "0:a:0",
           s("hlg.mov"))
    if not (SRC / "letterbox.mp4").exists():  # чёрные полосы сверху/снизу — для cropdetect
        ff("-i", s("face.mp4"), "-vf", "scale=1080:1350,pad=1080:1920:0:285:black", *NV, "-c:a", "copy",
           s("letterbox.mp4"))
    if not (SRC / "kitten.mp4").exists():    # котёнок на зелёном фоне (1324)
        ff("-t", "6", "-i", str(dl / "meme_os/meme/IMG_5430.MOV"), *NV, "-an", s("kitten.mp4"))
    if not (SRC / "music.m4a").exists():     # музыка 1353
        ff("-i", str(dl / "1353/music/ref.mp4"), "-vn", "-c:a", "copy", s("music.m4a"))
    if not (SRC / "logo.png").exists():
        ff("-i", str(dl / "1309/logo/Copy of logo_shield_color_2048.png"), "-vf", "scale=400:-1", s("logo.png"))
    if not (SRC / "image.jpg").exists():
        shutil.copy(ROOT / "output/1347_64/sort_1_10_1347.jpg", SRC / "image.jpg")
    if not (SRC / "frames").exists():
        (SRC / "frames").mkdir()
        ff("-i", s("jump.mp4"), "-vf", "fps=10,scale=540:960", str(SRC / "frames" / "frame_%04d.png"))
    if not (SRC / "lavmic.wav").exists():    # «петличка», начатая на 1.5 с позже камеры
        ff("-ss", "1.5", "-i", s("talk.mp4"), "-vn", "-c:a", "pcm_s16le", s("lavmic.wav"))
    if not (SRC / "camB.mp4").exists():      # «вторая камера»: крупнее и на 1 с позже
        ff("-ss", "1.0", "-i", s("talk.mp4"), "-vf", "crop=iw/1.6:ih/1.6,scale=1080:1920", *NV, "-c:a", "aac",
           s("camB.mp4"))
    # фразы из нашей whisper-разметки → cue-файл скилла и whisper-JSON для silence --filler
    words = [w for w in json.loads((dl / "gw_gotjob2/srcA/words.json").read_text(encoding="utf-8"))["IMG_5700"]
             if w[2] <= 13.0]
    cues, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt_ends = i + 1 < len(words) and words[i + 1][0][-1] in ".,!?"
        if w[0][-1] in ".,!?" or (len(cur) >= 4 and not nxt_ends):     # фраза по смыслу, без висящих слов
            cues.append((cur[0][1], cur[-1][2], " ".join(x[0] for x in cur)))
            cur = []
    if cur:
        cues.append((cur[0][1], cur[-1][2], " ".join(x[0] for x in cur)))
    (SRC / "cues.txt").write_text("\n".join(f"{fmt(a)}-{fmt(b)} {t}" for a, b, t in cues) + "\n", encoding="utf-8")
    emo = ["😭", "🔥", "✨", "🙌"]
    (SRC / "cues_emoji.txt").write_text(
        "\n".join(f"{fmt(a)}-{fmt(b)} {t} {emo[i % 4]}" for i, (a, b, t) in enumerate(cues)) + "\n", encoding="utf-8")
    (SRC / "words.json").write_text(json.dumps(
        {"segments": [{"words": [{"word": " " + w[0], "start": w[1], "end": w[2]} for w in words]}]}), encoding="utf-8")
    # тёплый LUT 17³
    n = 17
    rows = ["TITLE \"warm test\"", f"LUT_3D_SIZE {n}"]
    for b in range(n):
        for g in range(n):
            for r in range(n):
                R, G, B = r / (n - 1), g / (n - 1), b / (n - 1)
                rows.append(f"{min(1, R * 1.06 + 0.02):.5f} {min(1, G * 1.01):.5f} {B * 0.9:.5f}")
    (SRC / "warm.cube").write_text("\n".join(rows) + "\n", encoding="utf-8")
    bi = SRC / "batch_in"
    if not bi.exists():
        bi.mkdir()
        shutil.copy(SRC / "face.mp4", bi / "face.mp4")
        shutil.copy(SRC / "jump.mp4", bi / "jump.mp4")
    (SRC / "batch.json").write_text(json.dumps({
        "output_dir": str(OUT / "85_batch_loudness_export"), "suffix": "_tiktok",
        "steps": [["loudness.py", "{in}", "-I", "-14", "-o", "{out}"],
                  ["export.py", "{in}", "--preset", "tiktok", "-o", "{out}"]]}, indent=2), encoding="utf-8")


def o(name: str) -> str:
    return str(OUT / name)


FONT = ["--font", "TikTok Sans", "--fonts-dir", str(ROOT / "fonts"), "--bold"]
GFX = ["--font-file", str(FONT_FILE), "--platform", "tiktok"]


def tests() -> list[tuple[str, str, object, str]]:
    """(имя, скрипт, argv-функция, вид: file — результат в -o, json — stdout в файл, dir — свой вывод)."""
    def crop_args() -> list[str]:
        c = json.loads(Path(o("04_cropdetect.json")).read_text(encoding="utf-8")).get("crop") or {}
        return [s("letterbox.mp4"), "--x", str(c.get("x", 0)), "--y", str(c.get("y", 0)),
                "--width", str(c.get("width", 1080)), "--height", str(c.get("height", 1920))]

    def jump_len() -> float:
        p = json.loads(subprocess.run([sys.executable, str(SK / "probe.py"), s("jump.mp4"), "--json"], env=ENV,
                                      capture_output=True, text=True, encoding="utf-8").stdout)
        return float(p.get("duration") or p.get("format", {}).get("duration") or 6.3)

    return [
        # --- осмотр и измерения
        ("01_probe", "probe.py", lambda: [s("talk.mp4"), "--json"], "json"),
        ("02_look_contact_sheet_safezone.png", "look.py", lambda: [s("talk.mp4"), "--tiles", "4x3", "--width", "1080",
                                                                  "--safe", "tiktok"], "file"),
        ("03_scenes_jump_shots_peaks", "scenes.py", lambda: [s("jump.mp4"), "--shots", "--audio-peaks",
                                                              "--highlights", "2", "--min-scene", "1"], "json"),
        ("03b_scenes_music_beats", "scenes.py", lambda: [str(ROOT / "downloads/1353/music/ref.mp4"), "--beats"], "json"),
        ("04_cropdetect", "cropdetect.py", lambda: [s("letterbox.mp4")], "json"),
        ("05_crop_from_cropdetect.mp4", "crop.py", crop_args, "file"),
        ("06_silence_list", "silence.py", lambda: [s("talk.mp4"), "--list", "--threshold", "-35",
                                                   "--min-silence", "0.4"], "json"),
        # --- резка и время
        ("10_cut_two_segments.mp4", "cut.py", lambda: [s("talk.mp4"), "--segments", "0-1.9,4.3-7.6", "--accurate"], "file"),
        ("11_fit_1x1_blur.mp4", "fit.py", lambda: [s("talk.mp4"), "--aspect", "1:1", "--fit", "blur", "--width", "1080"], "file"),
        ("12_fit_4x5_crop.mp4", "fit.py", lambda: [s("talk.mp4"), "--aspect", "4:5", "--fit", "crop", "--width", "1080"], "file"),
        ("13_fit_duration_5s_speed.mp4", "fit.py", lambda: [s("talk.mp4"), "--duration", "5", "--method", "speed"], "file"),
        ("14_fit_flip_h.mp4", "fit.py", lambda: [s("face.mp4"), "--flip", "h"], "file"),
        ("15_speedramp_slowmo_middle.mp4", "speedramp.py", lambda: [s("jump.mp4"), "--segment", "0-1.5:1.0",
                                                                    "--segment", "1.5-3.5:0.4",
                                                                    "--segment", f"3.5-{jump_len():.3f}:1.5"], "file"),
        ("16_freeze_frame.mp4", "freeze.py", lambda: [s("jump.mp4"), "--at", "2", "--hold", "1.5"], "file"),
        ("17_reverse.mp4", "reverse.py", lambda: [s("jump.mp4")], "file"),
        ("18_loop_boomerang.mp4", "loop.py", lambda: [s("jump2s.mp4"), "--times", "3", "--boomerang"], "file"),
        ("19_pad_black_1s.mp4", "pad.py", lambda: [s("face.mp4"), "--start", "1", "--end", "1", "--color", "0x101014"], "file"),
        ("20_insert_image_zoom_in.mp4", "insert.py", lambda: [s("image.jpg"), "--duration", "3", "--width", "1080",
                                                              "--height", "1920", "--zoom", "in"], "file"),
        ("21_background_gradient.mp4", "background.py", lambda: ["--duration", "3", "--width", "1080", "--height", "1920",
                                                                 "--gradient", "0xff6a00:0x0057ff", "--angle", "45"], "file"),
        ("22_broll_jump_into_talk.mp4", "broll.py", lambda: [s("talk.mp4"), "--insert", s("jump.mp4"), "--at", "3",
                                                             "--duration", "2.5", "--audio", "a"], "file"),
        ("23_join_slideleft.mp4", "join.py", lambda: [s("face.mp4"), s("jump.mp4"), s("talk.mp4"), "--transition",
                                                      "slideleft", "--duration", "0.4"], "file"),
        ("24_grid_2x2.mp4", "grid.py", lambda: [s("face.mp4"), s("jump.mp4"), s("talk.mp4"), s("kitten.mp4"), "--cols", "2",
                                                "--rows", "2", "--cell-width", "540", "--cell-height", "960",
                                                "--audio-from", "2"], "file"),
        ("25_sequence_from_frames.mp4", "sequence.py", lambda: ["--dir", str(SRC / "frames"), "--pattern", "frame_%04d.png",
                                                                "--fps", "10", "--start-number", "1"], "file"),
        ("26_silence_cut_pauses.mp4", "silence.py", lambda: [s("talk.mp4"), "--threshold", "-35", "--min-silence", "0.4",
                                                             "--speech-aware"], "file"),
        ("27_silence_filler_words.mp4", "silence.py", lambda: [s("talk.mp4"), "--filler", "--words", s("words.json")], "file"),
        # --- картинка
        ("30_straighten_minus4.mp4", "straighten.py", lambda: [s("face.mp4"), "--degrees", "-4", "--fit", "crop"], "file"),
        ("31_denoise_high.mp4", "denoise.py", lambda: [s("face.mp4"), "--strength", "high"], "file"),
        ("32_deinterlace.mp4", "deinterlace.py", lambda: [s("face.mp4")], "file"),
        ("33_stabilize_jump.mp4", "stabilize.py", lambda: [s("jump.mp4"), "--shakiness", "8", "--smoothing", "20",
                                                           "--zoom", "5"], "file"),
        ("34_redact_pixelate.mp4", "redact.py", lambda: [s("talk.mp4"), "--x", "240", "--y", "1500", "--width", "600",
                                                         "--height", "260", "--mode", "pixelate"], "file"),
        ("35_sphere_equirect_view.mp4", "sphere.py", lambda: [s("jump.mp4"), "--input-projection", "equirect",
                                                              "--yaw", "40", "--width", "1080", "--height", "1920"], "file"),
        ("36_color_hlg_to_sdr.mp4", "color.py", lambda: [s("hlg.mov"), "--to-sdr", "--tonemap", "hable"], "file"),
        ("37_color_lut_warm.mp4", "color.py", lambda: [s("face.mp4"), "--lut", s("warm.cube")], "file"),
        ("38_color_correct.mp4", "color.py", lambda: [s("face.mp4"), "--correct", "--exposure", "0.1", "--contrast", "1.15",
                                                      "--saturation", "1.25", "--temperature", "5200"], "file"),
        ("39_color_curves_vintage.mp4", "color.py", lambda: [s("face.mp4"), "--correct", "--curves", "vintage"], "file"),
        # --- текст и графика
        ("40_caption_karaoke_word.mp4", "caption.py", lambda: [s("talk.mp4"), "--text", s("cues.txt"), *FONT, "--size", "20",
                                                               "--platform", "tiktok", "--karaoke", "--karaoke-style", "word",
                                                               "--animate", "pop", "--write-srt", str(WORK / "cues.srt")], "file"),
        ("41_caption_karaoke_sweep_center.mp4", "caption.py", lambda: [s("talk.mp4"), "--text", s("cues.txt"), *FONT,
                                                                       "--size", "22", "--position", "center",
                                                                       "--platform", "tiktok", "--karaoke"], "file"),
        ("42_caption_box_emoji.mp4", "caption.py", lambda: [s("talk.mp4"), "--text", s("cues_emoji.txt"), *FONT, "--size", "18",
                                                            "--platform", "tiktok", "--box", "--emoji", "png",
                                                            "--emoji-assets", str(EMOJI), "--animate", "fade"], "file"),
        ("43_caption_soft_subs_mux.mp4", "caption.py", lambda: [s("talk.mp4"), "--mode", "mux", "--srt",
                                                                str(WORK / "cues.srt") + ":en"], "file"),
        ("44_overlay_logo_fade.mp4", "overlay.py", lambda: [s("talk.mp4"), "--image", s("logo.png"), "--position", "top-right",
                                                            "--scale", "200", "--start", "0.5", "--fade", "0.5",
                                                            "--platform", "tiktok"], "file"),
        ("45_overlay_text_box.mp4", "overlay.py", lambda: [s("face.mp4"), "--text", "i got the job", "--font-file",
                                                           str(FONT_FILE), "--font-size", "80", "--box", "--position",
                                                           "center"], "file"),
        ("46_overlay_greenscreen_kitten.mp4", "overlay.py", lambda: [s("jump.mp4"), "--video", s("kitten.mp4"), "--chromakey",
                                                                     "0x01f205", "--chromakey-similarity", "0.12",
                                                                     "--position", "top-left", "--scale", "500",
                                                                     "--platform", "tiktok"], "file"),
        ("47_overlay_pip.mp4", "overlay.py", lambda: [s("talk.mp4"), "--video", s("jump.mp4"), "--position", "bottom-right",
                                                      "--scale", "360", "--border", "6", "--platform", "tiktok"], "file"),
        ("48_graphics_hook.mp4", "graphics.py", lambda: [s("talk.mp4"), "--template", "hook", "--title",
                                                         "POV: you finally got the job", *GFX], "file"),
        ("49_graphics_meme.mp4", "graphics.py", lambda: [s("jump.mp4"), "--template", "meme", "--top",
                                                         "ME AFTER 200 APPLICATIONS", "--bottom", "FINALLY HIRED", *GFX], "file"),
        ("50_graphics_lower_third.mp4", "graphics.py", lambda: [s("talk.mp4"), "--template", "lower-third", "--name", "Ciara",
                                                                "--title", "hired in 2 weeks", *GFX], "file"),
        ("51_graphics_sticker.mp4", "graphics.py", lambda: [s("face.mp4"), "--template", "sticker", "--text", "LINK IN BIO 🔗",
                                                            "--emoji", "png", "--emoji-assets", str(EMOJI), *GFX], "file"),
        ("52_graphics_progress.mp4", "graphics.py", lambda: [s("talk.mp4"), "--template", "progress", *GFX], "file"),
        ("53_graphics_countdown.mp4", "graphics.py", lambda: [s("jump.mp4"), "--template", "countdown", "--from", "3", *GFX], "file"),
        ("54_graphics_title.mp4", "graphics.py", lambda: [s("face.mp4"), "--template", "title", "--title", "Day 1",
                                                          "--subtitle", "of my new job", *GFX], "file"),
        ("55_graphics_chapter.mp4", "graphics.py", lambda: [s("face.mp4"), "--template", "chapter", "--title", "Part 2", *GFX], "file"),
        ("56_graphics_bug.mp4", "graphics.py", lambda: [s("face.mp4"), "--template", "bug", "--title", "@globalwork",
                                                        "--position", "top-left", *GFX], "file"),
        # --- звук
        ("60_audio_music_ducked_under_voice.mp4", "audio.py", lambda: [s("talk.mp4"), "--voice", "--music", s("music.m4a"),
                                                                       "--music-loop", "--duck", "--fade-out", "1"], "file"),
        ("61_audio_replace_with_music.mp4", "audio.py", lambda: [s("face.mp4"), "--replace", s("music.m4a"), "--fade-out", "0.3"], "file"),
        ("62_audio_compress_limit.mp4", "audio.py", lambda: [s("talk.mp4"), "--compress", "--limit"], "file"),
        ("63_loudness_minus14.mp4", "loudness.py", lambda: [s("talk.mp4"), "-I", "-14", "--tp", "-1"], "file"),
        ("64_waveform_spectrum.mp4", "waveform.py", lambda: [s("music.m4a"), "--style", "spectrum", "--width", "1080",
                                                             "--height", "1920"], "file"),
        ("65_waveform_over_image.mp4", "waveform.py", lambda: [s("music.m4a"), "--image", s("image.jpg"), "--width", "1080",
                                                               "--height", "1920", "--position", "bottom",
                                                               "--color", "0xffffff"], "file"),
        ("66_sync_offset", "sync.py", lambda: [s("talk.mp4"), s("lavmic.wav")], "json"),
        ("67_sync_replace_audio.mp4", "sync.py", lambda: [s("talk.mp4"), s("lavmic.wav"), "--replace-audio"], "file"),
        ("68_multicam_auto_2s.mp4", "multicam.py", lambda: [s("talk.mp4"), s("camB.mp4"), "--auto", "2"], "file"),
        ("69_metadata_tags_chapters.mp4", "metadata.py", lambda: [s("talk.mp4"), "--title", "ffmpeg-skill test",
                                                                  "--artist", "farm", "--auto-chapters",
                                                                  "--min-chapter", "2"], "file"),
        # --- выдача
        ("80_export_tiktok.mp4", "export.py", lambda: [s("talk.mp4"), "--preset", "tiktok"], "file"),
        ("81_export_gif.gif", "export.py", lambda: [s("jump2s.mp4"), "--preset", "gif"], "file"),
        ("82_proxy_360.mp4", "proxy.py", lambda: [s("talk.mp4"), "--width", "360"], "file"),
        ("83_check_tiktok", "check.py", lambda: [o("80_export_tiktok.mp4"), "--platform", "tiktok", "--content"], "json"),
        ("84_render_template_tiktok.mp4", "render.py", lambda: [s("talk.mp4"), "--template", "tiktok", "--cues", s("cues.txt"),
                                                                "--logo", s("logo.png"), "--title", "i got the job"], "file"),
        ("85_batch_loudness_export", "batch.py", lambda: [str(SRC / "batch_in"), "--recipe", s("batch.json")], "dir"),
        ("86_verify_report", "verify.py", lambda: [s("face.mp4"), "--quick", "--out", o("86_verify_files"), "--keep",
                                                   "--report", o("86_verify_report.md")], "dir"),
        ("83b_check_tiktok_after_loudness", "check.py", lambda: [o("85_batch_loudness_export/face_tiktok.mp4"), "--platform",
                                                                   "tiktok", "--content"], "json"),
        ("87_report.html", "report.py", lambda: ["--after", o("40_caption_karaoke_word.mp4"), "--before", s("talk.mp4"),
                                                 "--platform", "tiktok", "--title", "caption test"], "file"),
    ]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    flt = sys.argv[1:]
    OUT.mkdir(parents=True, exist_ok=True)
    prep()
    rows = []
    for name, tool, argv, kind in tests():
        if flt and not any(f in name for f in flt):
            continue
        try:
            args = argv()
        except Exception as e:  # noqa: BLE001  (зависимость от предыдущего теста)
            rows.append({"test": name, "tool": tool, "ok": False, "sec": 0, "note": f"нет входа: {e}"})
            print(f"✗ {name}: нет входа: {e}", flush=True)
            continue
        cmd = [sys.executable, str(SK / tool), *args]
        if kind == "file":
            cmd += ["-o", o(name), "--overwrite"]
        elif kind == "json":
            cmd += ["--json"]
        t0 = time.time()
        p = subprocess.run(cmd, env=ENV, capture_output=True, text=True, encoding="utf-8", errors="replace")
        sec = round(time.time() - t0, 1)
        if kind == "json":
            (OUT / f"{name}.json").write_text(p.stdout, encoding="utf-8")
        ok = p.returncode == 0
        tail = (p.stderr.strip().splitlines() or [""])[-1][:300] if not ok else ""
        (WORK / "logs").mkdir(parents=True, exist_ok=True)
        (WORK / "logs" / f"{name}.log").write_text(" ".join(cmd) + "\n\n" + p.stdout[-4000:] + "\n" + p.stderr[-8000:],
                                                   encoding="utf-8")
        rows.append({"test": name, "tool": tool, "ok": ok, "sec": sec, "note": tail})
        print(f"{'✓' if ok else '✗'} {name} ({tool}, {sec} с){'  ' + tail if tail else ''}", flush=True)
    path = WORK / "results.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["test", "tool", "ok", "sec", "note"], delimiter=";")
        w.writeheader()
        w.writerows(rows)
    print(f"\nготово: {sum(r['ok'] for r in rows)}/{len(rows)} ок → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
