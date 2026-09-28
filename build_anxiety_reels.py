#!/usr/bin/env python3
"""
Build TikTok reels (N photos × unique 10s chunks, no repeats):

  0–4s   selfie photo + "Why do you like coloring / so much?"
  4–14s  coloring clip + "Best way to treat / my anxiety ❤️🩹✨"
  audio  ~14s TT original sound (muted source clips)

Typography from core/renderer.py (TikTokSans, white + black stroke).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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
from story_overlay import emoji_glyph, split_emoji_runs  # noqa: E402

W, H = 1080, 1920
FPS = 30
PHOTO_DUR = 4.0

PHOTOS_DIR = Path(r"C:\Users\User\Downloads\download")
CHUNKS_DIR = ROOT / "yandex_videos" / "new_3" / "chunks_10s_1.3x"
AUDIO = (
    ROOT
    / "yandex_videos"
    / "audio"
    / "original_sound_-_jacklevi121_7674670045485681941.mp3"
)
OUT = ROOT / "yandex_videos" / "anxiety_reels_out"
ASSETS = ROOT / "yandex_videos" / "_anxiety_assets"

# Forced line breaks
TEXT_PHOTO_LINES = ["Why do you like coloring", "so much?"]
# Heart + bandage as separate emoji (no ZWJ) — Windows can't compose ❤️‍🩹 cleanly.
TEXT_GAME_LINES = ["Best way to treat", "my anxiety ❤️🩹✨"]

# Photo: mid-lower (below face). Gameplay: upper (above drawing, above TT UI).
PHOTO_TEXT_CY = int(H * 0.58)
GAME_TEXT_CY = int(H * 0.28)
FONT_SIZE = 64
WORKERS = 4
EMOJI_GAP = 6  # px between consecutive emoji runs


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not in PATH")
    return exe


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    return float(r.stdout.strip() or 0)


def wrap_lines(text: str, font_size: int, max_width: int) -> list[str]:
    """Word-wrap plain text; keep emoji clusters attached to previous word."""
    # Split preserving emoji as tokens
    tokens: list[str] = []
    for is_emoji, run in split_emoji_runs(text):
        if is_emoji:
            if tokens:
                tokens[-1] = tokens[-1] + run
            else:
                tokens.append(run)
        else:
            tokens.extend(run.split())

    font = _load_font(font_size)
    stroke = stroke_width_for(font_size)
    lines: list[str] = []
    cur = ""
    for tok in tokens:
        trial = (cur + " " + tok).strip()
        if measure_mixed_width(trial, font, stroke, font_size) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = tok
    if cur:
        lines.append(cur)
    return lines or [text]


def tight_emoji(cluster: str, box_h: int) -> Image.Image | None:
    """Render emoji and collapse huge transparent gaps (Windows ZWJ quirk)."""
    g = emoji_glyph(cluster, box_h)
    if g is None:
        return None
    px = g.load()
    w, h = g.size
    nonempty = [
        any(px[x, y][3] > 10 for y in range(h))
        for x in range(w)
    ]
    if not any(nonempty):
        return g

    # Keep small gaps (≤4px), drop large empty runs between glyph parts
    keep_cols: list[int] = []
    i = 0
    while i < w:
        if nonempty[i]:
            keep_cols.append(i)
            i += 1
            continue
        j = i
        while j < w and not nonempty[j]:
            j += 1
        gap = j - i
        if gap <= 4 and keep_cols and j < w:
            keep_cols.extend(range(i, j))
        i = j

    if keep_cols and len(keep_cols) != w:
        tmp = Image.new("RGBA", (len(keep_cols), h), (0, 0, 0, 0))
        for dst_x, src_x in enumerate(keep_cols):
            tmp.paste(g.crop((src_x, 0, src_x + 1, h)), (dst_x, 0))
        g = tmp

    bbox = g.getbbox()
    if bbox:
        g = g.crop(bbox)
    return g


def measure_mixed_width(
    text: str,
    font: ImageFont.ImageFont,
    stroke: int,
    font_size: int,
) -> int:
    w = 0
    prev_emoji = False
    for is_emoji, run in split_emoji_runs(text):
        if is_emoji:
            if prev_emoji:
                w += EMOJI_GAP
            g = tight_emoji(run, int(font_size * 1.15))
            w += (g.width if g else font_size)
            prev_emoji = True
        else:
            w += _line_width(font, run, stroke)
            prev_emoji = False
    return w


def draw_mixed_line(
    draw: ImageDraw.ImageDraw,
    layer: Image.Image,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    stroke: int,
    font_size: int,
) -> None:
    x, y = xy
    shx, shy = TEXT_SHADOW_OFFSET
    prev_emoji = False
    for is_emoji, run in split_emoji_runs(text):
        if is_emoji:
            g = tight_emoji(run, int(font_size * 1.15))
            if g is None:
                continue
            if prev_emoji:
                x += EMOJI_GAP
            # vertically center emoji vs text ascent
            ey = int(y + (font_size - g.height) / 2)
            layer.alpha_composite(g, (int(x), ey))
            x += g.width
            prev_emoji = True
        else:
            prev_emoji = False
            if abs(LETTER_SPACING) < 1e-9:
                bb = _text_bbox(draw, (0, 0), run, font, stroke)
                # bb[0] can be negative; _draw_tracked_text expects top-left
                _ = bb
            if shx or shy:
                _draw_tracked_text(
                    draw,
                    (x + shx, y + shy),
                    run,
                    font,
                    fill=SHADOW_FILL,
                    stroke_width=stroke,
                    stroke_fill=SHADOW_FILL,
                )
            _draw_tracked_text(
                draw,
                (x, y),
                run,
                font,
                fill=TEXT_FILL,
                stroke_width=stroke,
                stroke_fill=STROKE_FILL,
            )
            x += _line_width(font, run, stroke)


def render_caption_overlay(
    text: str | None,
    cy: int,
    out_png: Path,
    font_size: int = FONT_SIZE,
    *,
    forced_lines: list[str] | None = None,
) -> None:
    """Transparent full-frame PNG with centered caption block at cy."""
    if forced_lines:
        lines = list(forced_lines)
    else:
        assert text is not None
        lines = wrap_lines(text, font_size, int(W * 0.88))
    # shrink if still too wide
    while font_size > 44:
        if not forced_lines:
            assert text is not None
            lines = wrap_lines(text, font_size, int(W * 0.88))
        font = _load_font(font_size)
        stroke = stroke_width_for(font_size)
        if max(measure_mixed_width(ln, font, stroke, font_size) for ln in lines) <= int(W * 0.90):
            break
        font_size -= 2

    font = _load_font(font_size)
    stroke = stroke_width_for(font_size)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    heights: list[int] = []
    widths: list[int] = []
    for ln in lines:
        # height from plain text bbox (emoji ~ same)
        plain = "".join(r for e, r in split_emoji_runs(ln) if not e) or "Ag"
        bb = _text_bbox(probe, (0, 0), plain, font, stroke)
        heights.append(bb[3] - bb[1])
        widths.append(measure_mixed_width(ln, font, stroke, font_size))

    advance = max(heights) + max(8, int(round(font_size * 0.18)))
    block_h = advance * (len(lines) - 1) + (heights[0] if heights else font_size)
    y = cy - block_h / 2.0

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for i, ln in enumerate(lines):
        lw = widths[i]
        x = W / 2.0 - lw / 2.0
        plain = "".join(r for e, r in split_emoji_runs(ln) if not e) or "A"
        bb = _text_bbox(probe, (0, 0), plain, font, stroke)
        yy = y - bb[1]
        draw_mixed_line(draw, canvas, (x, yy), ln, font, stroke, font_size)
        y += advance

    canvas.save(out_png, "PNG")


def cover_fit_photo(src: Path, out_png: Path) -> None:
    img = Image.open(src).convert("RGB")
    iw, ih = img.size
    scale = max(W / iw, H / ih)
    nw, nh = int(iw * scale + 0.5), int(ih * scale + 0.5)
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - W) // 2
    top = (nh - H) // 2
    img = img.crop((left, top, left + W, top + H))
    img.save(out_png, "PNG")


def make_photo_clip(
    ffmpeg: str,
    photo_png: Path,
    overlay_png: Path,
    out_mp4: Path,
    seconds: float,
) -> None:
    # burn overlay onto still, then loop
    burned = ASSETS / f"_burned_{photo_png.stem}.png"
    base = Image.open(photo_png).convert("RGBA")
    ov = Image.open(overlay_png).convert("RGBA")
    base.alpha_composite(ov)
    base.convert("RGB").save(burned, "PNG")

    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(burned),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-t", f"{seconds:.3f}",
        "-c:a", "aac", "-b:a", "128k", "-shortest",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("photo clip: " + (r.stderr[-400:] or "?"))


def make_game_clip(
    ffmpeg: str,
    src: Path,
    overlay_png: Path,
    out_mp4: Path,
    seconds: float,
) -> None:
    """Cover-fit (already 9:16), mute, burn text overlay, loop if short, trim to seconds."""
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        # loop short leftover tails so gameplay always fills `seconds`
        "-stream_loop", "-1", "-i", str(src),
        "-i", str(overlay_png),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-filter_complex",
        (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,fps={FPS}[v0];"
            f"[v0][1:v]overlay=0:0:format=auto[vout]"
        ),
        "-map", "[vout]", "-map", "2:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-t", f"{seconds:.3f}",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("game clip: " + (r.stderr[-400:] or "?"))


def concat_mux(
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

    tmp = ASSETS / f"_vid_{out.stem}.mp4"
    r = subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(lst),
            "-c", "copy", str(tmp),
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError("concat: " + (r.stderr[-400:] or "?"))

    r = subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(tmp), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total_dur:.3f}", "-shortest",
            "-movflags", "+faststart",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError("mux: " + (r.stderr[-400:] or "?"))

    tmp.unlink(missing_ok=True)
    lst.unlink(missing_ok=True)


def list_photos() -> list[Path]:
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    photos = sorted(
        p for p in PHOTOS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in exts
    )
    if not photos:
        raise SystemExit(f"no photos in {PHOTOS_DIR}")
    return photos


def list_chunks() -> list[Path]:
    chunks = sorted(CHUNKS_DIR.rglob("chunk_*.mp4"))
    if not chunks:
        raise SystemExit(f"no chunks in {CHUNKS_DIR}")
    return chunks


def pair_unique(photos: list[Path], chunks: list[Path]) -> list[tuple[int, int]]:
    """Assign every chunk to a photo without reuse. Spread evenly across photos.

    Returns list of (photo_index, chunk_index) — one job per chunk.
    """
    n_p, n_c = len(photos), len(chunks)
    if n_c < n_p:
        raise SystemExit(f"need ≥{n_p} chunks for {n_p} photos, got {n_c}")
    base, rem = divmod(n_c, n_p)
    # first `rem` photos get base+1 clips, rest get base
    pairs: list[tuple[int, int]] = []
    ci = 0
    for pi in range(n_p):
        take = base + (1 if pi < rem else 0)
        for _ in range(take):
            pairs.append((pi, ci))
            ci += 1
    assert ci == n_c
    return pairs


def build_one(
    ffmpeg: str,
    photo_mp4: Path,
    clip: Path,
    game_overlay: Path,
    out: Path,
    game_dur: float,
    total_dur: float,
) -> None:
    game_mp4 = ASSETS / f"_game_{out.stem}.mp4"
    make_game_clip(ffmpeg, clip, game_overlay, game_mp4, game_dur)
    concat_mux(ffmpeg, [photo_mp4, game_mp4], AUDIO, out, total_dur)
    game_mp4.unlink(missing_ok=True)


def main() -> None:
    if not AUDIO.is_file():
        raise SystemExit(f"audio missing: {AUDIO}")
    ffmpeg = find_ffmpeg()
    OUT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)

    # wipe previous batch so old photo pairings don't linger
    for old in OUT.glob("*.mp4"):
        old.unlink()

    photos = list_photos()
    chunks = list_chunks()
    pairs = pair_unique(photos, chunks)
    audio_dur = probe_duration(AUDIO)
    photo_dur = PHOTO_DUR
    game_dur = max(1.0, audio_dur - photo_dur)
    total_dur = audio_dur

    base, rem = divmod(len(chunks), len(photos))
    print(
        f"Photos: {len(photos)}  Chunks: {len(chunks)}  → {len(pairs)} reels "
        f"(~{base}+{'1' if rem else '0'} clips/photo, no repeats)",
        flush=True,
    )
    print(f"Structure: photo {photo_dur:.2f}s + game {game_dur:.2f}s = {total_dur:.2f}s")
    print(f"Photos dir: {PHOTOS_DIR}")
    print(f"Audio: {AUDIO.name} ({audio_dur:.3f}s)")
    print(f"Out → {OUT}")

    # Shared overlays
    ov_photo = ASSETS / "overlay_photo.png"
    ov_game = ASSETS / "overlay_game.png"
    render_caption_overlay(None, PHOTO_TEXT_CY, ov_photo, forced_lines=TEXT_PHOTO_LINES)
    render_caption_overlay(None, GAME_TEXT_CY, ov_game, forced_lines=TEXT_GAME_LINES)
    print("Overlays ready.", flush=True)

    # Prebuild one still-clip per photo
    photo_clips: list[Path] = []
    for i, ph in enumerate(photos):
        fitted = ASSETS / f"photo_{i:02d}_fit.png"
        clip = ASSETS / f"photo_{i:02d}.mp4"
        cover_fit_photo(ph, fitted)
        make_photo_clip(ffmpeg, fitted, ov_photo, clip, photo_dur)
        photo_clips.append(clip)
        print(f"  photo[{i:02d}] {ph.name}", flush=True)

    # per-photo clip counters for filenames
    per_photo_n = [0] * len(photos)
    jobs: list[tuple[int, Path, Path, Path]] = []
    for reel_i, (pi, ci) in enumerate(pairs, start=1):
        per_photo_n[pi] += 1
        out = OUT / f"reel_{reel_i:03d}_p{pi + 1:02d}_c{per_photo_n[pi]:02d}.mp4"
        jobs.append((reel_i, photo_clips[pi], chunks[ci], out))

    ok = fail = 0
    print(f"Building {len(jobs)} reels with {WORKERS} workers…", flush=True)

    def _job(item: tuple[int, Path, Path, Path]) -> tuple[int, Path, str | None]:
        n, photo_mp4, clip, out = item
        try:
            build_one(ffmpeg, photo_mp4, clip, ov_game, out, game_dur, total_dur)
            return n, out, None
        except Exception as e:
            return n, out, str(e)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = [pool.submit(_job, j) for j in jobs]
        for fut in as_completed(futs):
            n, out, err = fut.result()
            if err:
                fail += 1
                print(f"  [{n:03d}] FAIL {err}", flush=True)
            else:
                ok += 1
                mb = out.stat().st_size / 1e6
                print(f"  [{n:03d}] OK {out.name}  {mb:.1f} MB", flush=True)

    print(f"\nDone: {ok} ok, {fail} fail → {OUT}")
    # uniqueness check
    used_photos = {p for _, p, _, _ in jobs}
    used_chunks = {c for _, _, c, _ in jobs}
    print(
        f"Unique photos used: {len(used_photos)}/{len(photos)}  "
        f"Unique clips used: {len(used_chunks)}/{len(chunks)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
