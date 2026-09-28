#!/usr/bin/env python3
"""
Build 18 TikTok reels (clip_01 … clip_18):
  0–~1.8s  variant intro caption — "lemme show you / how I color"
  then 3… 2… 1… until ~6.0s (same wash bg as intro)
  6.0–6.5s iris/zoom transition → clip
  6.5s+    clip slowed so TOTAL length == full music (~23.66s)
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.renderer import (  # noqa: E402
    LETTER_SPACING,
    SHADOW_FILL,
    STROKE_FILL,
    TEXT_FILL,
    TEXT_SHADOW_OFFSET,
    _draw_tracked_text,
    _load_font,
    _line_width,
    _text_bbox,
    stroke_width_for,
)
from preview_intro_variants import (  # noqa: E402
    VARIANTS,
    diagonal_wash,
    wash,
)

W, H = 1080, 1920
FPS = 30
HOOK_AT = 6.5          # when clip content begins (after transition)
TRANS_DUR = 0.5        # cool wipe just before clip

CAPTION = "lemme show you how I color"
CAPTION_LINES = ["lemme show you", "how I color"]  # forced 2-line layout
CAPTION_END = 1.8
COUNT_ORDER = ("3", "2", "1")
COUNT_START = 1.8
COUNT_END = HOOK_AT - TRANS_DUR  # 6.0

CLIP_ZOOM = 1.22
# body speed computed per-clip so total length == full music (~23.66s)
# intro + transition stay at normal speed

CLIPS = ROOT / "yandex_videos" / "clips_fixed"
AUDIO = ROOT / "yandex_videos" / "audio" / "Runaway_6943141579087563522.mp3"
OUT = ROOT / "yandex_videos" / "reels_out"
ASSETS = ROOT / "yandex_videos" / "_reel_assets"


def variant_bg(colors: tuple, diag: bool) -> Image.Image:
    return diagonal_wash(*colors) if diag else wash(*colors)


def render_intro_frame(variant_idx: int) -> Image.Image:
    """Full intro frame: wash + typography from preview_intro_variants."""
    name, colors, diag, fn = VARIANTS[variant_idx]
    img = variant_bg(colors, diag)
    fn(img)
    return img


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not in PATH")
    return exe


def draw_centered_block(
    img: Image.Image,
    lines: list[str],
    *,
    font_size: int,
    cy: float,
    max_width: int | None = None,
    alpha: int = 255,
) -> None:
    was_rgb = img.mode == "RGB"
    base = img.convert("RGBA") if was_rgb else img

    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font = _load_font(font_size)
    stroke = stroke_width_for(font_size)
    heights, widths = [], []
    for line in lines:
        bb = _text_bbox(probe, (0, 0), line, font, stroke)
        heights.append(bb[3] - bb[1])
        widths.append(_line_width(font, line, stroke))

    if max_width and widths and max(widths) > max_width and font_size > 40:
        tmp = Image.new("RGB", img.size) if was_rgb else img
        if was_rgb:
            tmp.paste(img)
        draw_centered_block(
            tmp, lines, font_size=font_size - 2, cy=cy,
            max_width=max_width, alpha=alpha,
        )
        if was_rgb:
            img.paste(tmp)
        return

    advance = max(heights) + max(6, int(round(font_size * 0.16)))
    block_h = advance * (len(lines) - 1) + (heights[0] if heights else 0)
    y = cy - block_h / 2.0
    shx, shy = TEXT_SHADOW_OFFSET
    fill = (*TEXT_FILL[:3], alpha)
    stroke_f = (*STROKE_FILL[:3], alpha)
    shadow_f = (*SHADOW_FILL[:3], min(255, alpha))
    for i, line in enumerate(lines):
        bb = _text_bbox(probe, (0, 0), line, font, stroke)
        lw = widths[i]
        x = W / 2.0 - lw / 2.0
        if abs(LETTER_SPACING) < 1e-9:
            x = W / 2.0 - lw / 2.0 - bb[0]
        yy = y - bb[1]
        if shx or shy:
            _draw_tracked_text(
                draw, (x + shx, yy + shy), line, font,
                fill=shadow_f, stroke_width=stroke, stroke_fill=shadow_f,
            )
        _draw_tracked_text(
            draw, (x, yy), line, font,
            fill=fill, stroke_width=stroke, stroke_fill=stroke_f,
        )
        y += advance

    composed = Image.alpha_composite(base, layer)
    if was_rgb:
        img.paste(composed.convert("RGB"))
    else:
        img.paste(composed)


def wrap_caption(text: str, font_size: int = 72) -> list[str]:
    words = text.split()
    font = _load_font(font_size)
    stroke = stroke_width_for(font_size)
    max_w = int(W * 0.88)
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if _line_width(font, trial, stroke) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_out_back(t: float) -> float:
    t = max(0.0, min(1.0, t))
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def render_caption_glyph(font_size: int = 76) -> Image.Image:
    """Transparent block of caption lines for scale/fade animation."""
    lines = wrap_caption(CAPTION, font_size)
    # measure
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font = _load_font(font_size)
    stroke = stroke_width_for(font_size)
    widths = [_line_width(font, ln, stroke) for ln in lines]
    heights = [
        _text_bbox(probe, (0, 0), ln, font, stroke)[3]
        - _text_bbox(probe, (0, 0), ln, font, stroke)[1]
        for ln in lines
    ]
    advance = max(heights) + max(6, int(round(font_size * 0.16)))
    block_w = int(max(widths)) + 40
    block_h = int(advance * (len(lines) - 1) + heights[0]) + 40
    canvas = Image.new("RGBA", (block_w, block_h), (0, 0, 0, 0))
    # draw onto temp full-size then crop — reuse draw_centered_block
    tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_centered_block(
        tmp, lines, font_size=font_size, cy=H / 2, max_width=int(W * 0.9),
    )
    # find bbox of non-transparent
    bbox = tmp.getbbox()
    if bbox:
        return tmp.crop(bbox)
    return canvas


def make_caption_clip(
    ffmpeg: str,
    seconds: float,
    out_mp4: Path,
    *,
    variant_idx: int,
) -> None:
    """Static intro frame from approved variant — no stamp/number overlay."""
    ASSETS.mkdir(parents=True, exist_ok=True)
    png = ASSETS / f"intro_caption_{variant_idx:02d}.png"
    img = render_intro_frame(variant_idx)
    img.save(png, "PNG")
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(png),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-t", f"{seconds:.3f}",
        "-c:a", "aac", "-b:a", "128k", "-shortest",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-500:] or "caption failed")


def render_number_glyph(digit: str, font_size: int = 460) -> Image.Image:
    canvas = Image.new("RGBA", (1000, 1000), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font = _load_font(font_size)
    stroke = max(5, stroke_width_for(font_size))
    bb = _text_bbox(probe, (0, 0), digit, font, stroke)
    lw = _line_width(font, digit, stroke)
    x = 500 - lw / 2.0
    if abs(LETTER_SPACING) < 1e-9:
        x = 500 - lw / 2.0 - bb[0]
    y = 500 - (bb[3] - bb[1]) / 2.0 - bb[1]
    _draw_tracked_text(
        draw, (x, y + 4), digit, font,
        fill=SHADOW_FILL, stroke_width=stroke, stroke_fill=SHADOW_FILL,
    )
    _draw_tracked_text(
        draw, (x, y), digit, font,
        fill=TEXT_FILL, stroke_width=stroke, stroke_fill=STROKE_FILL,
    )
    return canvas


def make_countdown_clip(
    ffmpeg: str,
    digit: str,
    seconds: float,
    out_mp4: Path,
    *,
    bg_img: Image.Image,
    tag: str,
) -> None:
    """Big centered digit, pop-in, no caption (clean beat)."""
    seq_dir = ASSETS / f"seq_{tag}_{digit}"
    if seq_dir.exists():
        for p in seq_dir.iterdir():
            p.unlink()
    else:
        seq_dir.mkdir(parents=True)

    glyph = render_number_glyph(digit, 460)
    n_frames = max(1, int(round(seconds * FPS)))
    pop_frames = min(n_frames, int(0.4 * FPS))
    bg_rgb = bg_img.convert("RGB")

    for i in range(n_frames):
        bg = bg_rgb.convert("RGBA")
        if i < pop_frames:
            t = i / max(1, pop_frames - 1)
            scale = 0.45 + 0.65 * ease_out_back(t)
            alpha = int(255 * min(1.0, t * 1.4))
        else:
            phase = (i - pop_frames) / FPS
            scale = 1.0 + 0.04 * math.sin(phase * math.pi * 2 / 1.15)
            alpha = 255
            remain = n_frames - i
            if remain <= int(0.15 * FPS):
                alpha = int(255 * remain / max(1, 0.15 * FPS))

        g = glyph
        if alpha < 255:
            g = glyph.copy()
            a = g.getchannel("A").point(lambda p, al=alpha: p * al // 255)
            g.putalpha(a)

        nw = max(2, int(g.width * scale))
        nh = max(2, int(g.height * scale))
        scaled = g.resize((nw, nh), Image.Resampling.LANCZOS)
        x = (W - nw) // 2
        y = (H - nh) // 2
        bg.alpha_composite(scaled, (x, y))
        bg.convert("RGB").save(seq_dir / f"f_{i:04d}.png")

    _seq_to_mp4(ffmpeg, seq_dir, seconds, out_mp4)


def _seq_to_mp4(ffmpeg: str, seq_dir: Path, seconds: float, out_mp4: Path) -> None:
    pattern = (seq_dir / "f_%04d.png").as_posix()
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-framerate", str(FPS), "-i", pattern,
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-shortest",
        "-t", f"{seconds:.3f}",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-500:] or f"seq failed {out_mp4.name}")


def ease_in_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 4 * t * t * t
    return 1 - (-2 * t + 2) ** 3 / 2


def extract_first_frame(ffmpeg: str, video: Path, out_png: Path) -> None:
    r = subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video), "-frames:v", "1", str(out_png),
        ],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not out_png.is_file():
        raise RuntimeError("extract frame: " + (r.stderr[-300:] or "?"))


def make_iris_transition(
    ffmpeg: str,
    clip_frame: Path,
    seconds: float,
    out_mp4: Path,
    *,
    bg_img: Image.Image,
    tag: str,
) -> None:
    """Iris / zoom punch: intro wash shrinks away via expanding hole + clip zooms in."""
    seq_dir = ASSETS / f"seq_trans_{tag}"
    if seq_dir.exists():
        for p in seq_dir.iterdir():
            p.unlink()
    else:
        seq_dir.mkdir(parents=True)

    clip_img = Image.open(clip_frame).convert("RGB").resize((W, H), Image.Resampling.LANCZOS)
    wash_bg = bg_img.convert("RGB")
    n_frames = max(2, int(round(seconds * FPS)))
    max_r = math.hypot(W / 2, H / 2) * 1.2
    cx, cy = W / 2, H / 2

    for i in range(n_frames):
        t = ease_in_out_cubic(i / (n_frames - 1))
        z = 1.28 - 0.28 * t
        zw, zh = int(W * z), int(H * z)
        zoomed = clip_img.resize((zw, zh), Image.Resampling.LANCZOS)
        x0 = (zw - W) // 2
        y0 = (zh - H) // 2
        base = zoomed.crop((x0, y0, x0 + W, y0 + H))

        overlay = wash_bg.copy().convert("RGBA")
        mask = Image.new("L", (W, H), 255)
        md = ImageDraw.Draw(mask)
        r = max_r * t
        md.ellipse([cx - r, cy - r, cx + r, cy + r], fill=0)
        mask = mask.filter(ImageFilter.GaussianBlur(radius=max(1, int(12 * (1 - t * 0.5)))))
        overlay.putalpha(mask)

        out = base.convert("RGBA")
        out.alpha_composite(overlay)
        if 0.35 < t < 0.55:
            flash_a = int(70 * (1 - abs(t - 0.45) / 0.1))
            flash = Image.new("RGBA", (W, H), (255, 255, 255, max(0, flash_a)))
            out.alpha_composite(flash)

        out.convert("RGB").save(seq_dir / f"f_{i:04d}.png")

    _seq_to_mp4(ffmpeg, seq_dir, seconds, out_mp4)


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip() or 0)


def scale_clip(
    ffmpeg: str,
    src: Path,
    out_mp4: Path,
    *,
    speed: float = 1.0,
    zoom: float = 1.0,
    out_dur: float | None = None,
) -> float:
    """Cover-fit 9:16, optional zoom-in + slowdown. Returns output duration."""
    src_dur = probe_duration(src)
    speed = max(0.15, min(speed, 2.0))
    zoom = max(1.0, zoom)
    tw, th = int(W * zoom), int(H * zoom)
    vf = (
        f"scale={tw}:{th}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H}:(iw-ow)/2:(ih-oh)*0.32,"
        f"setpts=PTS/{speed:.6f},"
        f"fps={FPS},setsar=1"
    )
    if out_dur is None:
        out_dur = src_dur / speed
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k",
        "-t", f"{out_dur:.3f}",
        "-map", "0:v:0", "-map", "1:a:0",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-500:] or f"scale failed {src.name}")
    return out_dur


def concat_and_mux(
    ffmpeg: str,
    parts: list[Path],
    audio: Path,
    out: Path,
    total_dur: float,
) -> None:
    lst = ASSETS / f"_concat_{out.stem}.txt"
    lines = []
    for p in parts:
        path = p.resolve().as_posix().replace("'", r"\'")
        lines.append(f"file '{path}'")
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")

    tmp_vid = ASSETS / f"_vid_{out.stem}.mp4"
    r = subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(lst),
            "-c", "copy", str(tmp_vid),
        ],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError("concat: " + (r.stderr[-400:] or "?"))

    r = subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(tmp_vid), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total_dur:.3f}", "-shortest",
            "-movflags", "+faststart", str(out),
        ],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError("mux: " + (r.stderr[-400:] or "?"))
    tmp_vid.unlink(missing_ok=True)
    lst.unlink(missing_ok=True)


def build_one(
    ffmpeg: str,
    clip: Path,
    out: Path,
    intro_parts: list[Path],
    *,
    audio_dur: float,
    bg_img: Image.Image,
    tag: str,
) -> None:
    """Intro+iris (normal) until HOOK_AT, then clip slowed to fill rest of music → ~23.66s total."""
    src_dur = probe_duration(clip)
    body_target = max(0.5, audio_dur - HOOK_AT)
    speed = src_dur / body_target

    p_body = ASSETS / f"_body_{out.stem}.mp4"
    body_dur = scale_clip(
        ffmpeg, clip, p_body,
        speed=speed, zoom=CLIP_ZOOM, out_dur=body_target,
    )

    frame_png = ASSETS / f"_frame_{out.stem}.png"
    extract_first_frame(ffmpeg, p_body, frame_png)
    p_trans = ASSETS / f"_trans_{out.stem}.mp4"
    make_iris_transition(ffmpeg, frame_png, TRANS_DUR, p_trans, bg_img=bg_img, tag=tag)

    total = HOOK_AT + body_dur  # ≈ audio_dur
    concat_and_mux(ffmpeg, [*intro_parts, p_trans, p_body], AUDIO, out, total)
    p_body.unlink(missing_ok=True)
    p_trans.unlink(missing_ok=True)
    frame_png.unlink(missing_ok=True)


def main() -> None:
    if not AUDIO.is_file():
        raise SystemExit(f"music missing: {AUDIO}")
    if not CLIPS.is_dir():
        raise SystemExit(f"clips missing: {CLIPS}")
    if len(VARIANTS) < 18:
        raise SystemExit(f"need 18 intro variants, got {len(VARIANTS)}")
    ffmpeg = find_ffmpeg()
    OUT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)

    audio_dur = probe_duration(AUDIO)
    body_target = audio_dur - HOOK_AT

    clips = sorted(
        p for p in CLIPS.iterdir()
        if p.suffix.lower() in {".mp4", ".mov", ".m4v"}
    )
    if len(clips) < 18:
        raise SystemExit(f"need 18 clips, got {len(clips)} in {CLIPS}")
    clips = clips[:18]

    beat = (COUNT_END - COUNT_START) / len(COUNT_ORDER)
    print(f"18 variants × 18 clips → clip_01…clip_18")
    print(f"Caption → 3…2…1… → iris → clip@{HOOK_AT}s")
    print(f"Music {audio_dur:.2f}s | body fills {body_target:.2f}s | zoom={CLIP_ZOOM}")
    print(f"Out → {OUT}")

    ok = fail = 0
    for i, clip in enumerate(clips):
        idx = i  # 0..17
        n = i + 1
        name, colors, diag, _fn = VARIANTS[idx]
        tag = f"{n:02d}"
        out = OUT / f"clip_{n:02d}.mp4"
        bg = variant_bg(colors, diag)

        src_d = probe_duration(clip)
        spd = src_d / body_target
        print(f"[{n:02d}/18] {name} + {clip.name[:40]}  ({src_d:.1f}s→{body_target:.1f}s @{spd:.2f}x)", flush=True)

        try:
            p_cap = ASSETS / f"_intro_cap_{tag}.mp4"
            make_caption_clip(ffmpeg, CAPTION_END, p_cap, variant_idx=idx)

            intro = [p_cap]
            for d in COUNT_ORDER:
                p = ASSETS / f"_intro_{tag}_{d}.mp4"
                make_countdown_clip(ffmpeg, d, beat, p, bg_img=bg, tag=tag)
                intro.append(p)

            build_one(ffmpeg, clip, out, intro, audio_dur=audio_dur, bg_img=bg, tag=tag)

            # cleanup per-clip intro assets
            p_cap.unlink(missing_ok=True)
            for d in COUNT_ORDER:
                (ASSETS / f"_intro_{tag}_{d}.mp4").unlink(missing_ok=True)

            print(f"    OK {out.name}  {out.stat().st_size / 1e6:.1f} MB  dur={probe_duration(out):.2f}s", flush=True)
            ok += 1
        except Exception as e:
            print(f"    FAIL {e}", flush=True)
            fail += 1

    print(f"\nDone: {ok} ok, {fail} fail → {OUT}")


if __name__ == "__main__":
    main()