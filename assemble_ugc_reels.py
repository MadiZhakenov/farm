#!/usr/bin/env python3
"""Assemble a few test UGC reels: girl/guy clips + renderer-style text + IG audio."""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import renderer as R  # noqa: E402

CLIPS = ROOT / "output" / "clips_ugc"
GIRL_DIR = CLIPS / "girl_1s"
GUY_DIR = CLIPS / "guy_2s"
AUDIO = [
    ROOT / "downloads" / "instagram_audio_38785992234348543.mp3",
    ROOT / "downloads" / "instagram_Dd10JpmN4sW.mp3",
]
# Cozy Home: guy 1s + girl 2s, guy-POV texts, new sounds
COZY_CLIPS = ROOT / "output" / "clips_ugc_cozy"
COZY_GIRL_DIR = COZY_CLIPS / "girl_2s"
COZY_GUY_DIR = COZY_CLIPS / "guy_1s"
COZY_AUDIO = sorted((ROOT / "downloads" / "audio_new").glob("*.mp3"))
COZY_TEXTS = ROOT / "downloads" / "teksta_parnya.txt"
COZY_OUT_DIR = ROOT / "output" / "ugc_reels_cozy_test"
DEFAULT_TEXTS = Path(r"c:\Users\User\Downloads\текста.txt")
OUT_DIR = ROOT / "output" / "ugc_reels_test"
BATCH_DIR = ROOT / "output" / "ugc_reels_200"

W, H = 1080, 1920
# Story-ish safe zones on 9:16 (scaled from renderer 3:4 spirit)
SAFE_TOP = 220
SAFE_BOTTOM = 380
SAFE_SIDE = 70
MAX_W_RATIO = 0.68  # narrower block per red frame (~65-70%)
TEXT_DOWN_FRAC = 0.12  # slight drop from center (was 0.25 — raise back up)
FONT_START = 48
FONT_MIN = 28
FONT_STEP = 1
MAX_AREA = 0.42  # long confession copy needs more than carousel 0.24

# iOS / Apple-style emoji PNGs (not Windows Segoe)
APPLE_EMOJI_DIR = ROOT / "assets" / "emoji_apple_64"
APPLE_EMOJI_CDN = (
    "https://cdn.jsdelivr.net/npm/emoji-datasource-apple@15.1.2/img/apple/64/{key}.png"
)

# Emoji / pictograph clusters (+ ZWJ sequences, VS16, skin tones)
_EMOJI_RE = re.compile(
    "("
    r"[\U0001F1E6-\U0001F1FF]{2}"
    r"|[\U0001F300-\U0001FAFF\U0001F900-\U0001F9FF\U0001F600-\U0001F64F"
    r"\U0001F680-\U0001F6FF\U00002600-\U000026FF\U00002700-\U000027BF]"
    r"[\U0001F3FB-\U0001F3FF]?"
    r"(?:\u200D[\U0001F300-\U0001FAFF\U00002600-\U000027BF\u2640-\u2642\uFE0F]*)*"
    r"|[\u2600-\u26FF\u2700-\u27BF]\uFE0F?"
    r"|\u2764\uFE0F?"
    ")"
)

_apple_emoji_cache: dict[tuple[str, int], Image.Image] = {}


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found")
    return exe


# Text numbers (1-based as in файла) to never use in reels
TEXT_BLOCKLIST_IDS = {
    48,  # funeral
}

# Hard themes — drop if any keyword hits (case-insensitive)
TEXT_BLOCKLIST_KEYWORDS = (
    "funeral",
    "funeral's",
    "died",
    "death",
    "dead ",
    " suicide",
    "kill myself",
    "cancer",
    "coffin",
    "grave",
    "mourning",
    "passed away",
    "overdose",
)

# File section banners (e.g. "===== ЧАСТЬ 2: БРАТ И СЕСТРА (48–100) =====")
# must never reach the burned overlay.
_SECTION_BANNER_RE = re.compile(
    r"(?:"
    r"={3,}.*?={3,}"  # === ... ===
    r"|ЧАСТЬ\s*\d+\s*:\s*[^\n.?!]*"  # ЧАСТЬ N: ...
    r"|\bPART\s*\d+\s*:\s*[^\n.?!]*"  # PART N: ...
    r")",
    re.IGNORECASE | re.DOTALL,
)


def strip_section_banners(text: str) -> str:
    """Remove editorial section headers glued onto confession bodies."""
    cleaned = _SECTION_BANNER_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def load_texts(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8-sig")
    # Drop whole banner lines before numbered split so they can't glue to #N.
    raw = re.sub(r"(?m)^\s*={3,}.*$", "", raw)
    raw = re.sub(r"(?m)^\s*ЧАСТЬ\s+\d+\s*:.*$", "", raw)
    raw = re.sub(r"(?m)^\s*PART\s+\d+\s*:.*$", "", raw, flags=re.IGNORECASE)
    parts = re.split(r"(?m)^\s*(\d+)\.\s+", raw)
    # parts: [preamble, id1, body1, id2, body2, ...]
    texts: list[str] = []
    dropped: list[tuple[int, str]] = []
    i = 1
    while i + 1 < len(parts):
        try:
            num = int(parts[i])
        except ValueError:
            i += 1
            continue
        body = strip_section_banners(re.sub(r"\s+", " ", parts[i + 1]).strip())
        i += 2
        if not body:
            continue
        low = f" {body.lower()} "
        reason = None
        if num in TEXT_BLOCKLIST_IDS:
            reason = f"id {num}"
        else:
            for kw in TEXT_BLOCKLIST_KEYWORDS:
                if kw.lower() in low:
                    reason = f"keyword:{kw.strip()}"
                    break
        if reason:
            dropped.append((num, reason))
            continue
        texts.append(body)
    if dropped:
        print(
            "blocked texts: "
            + ", ".join(f"#{n} ({r})" for n, r in dropped),
            flush=True,
        )
    return texts


def is_6418(p: Path) -> bool:
    return "IMG_6418" in p.name


def pick_guys(guys: list[Path], n: int = 2) -> list[Path]:
    """6418 has a different camera angle — never mix with other guy sources."""
    if n != 2:
        return random.sample(guys, n)
    a6418 = [p for p in guys if is_6418(p)]
    other = [p for p in guys if not is_6418(p)]
    pools = []
    if len(a6418) >= 2:
        pools.append(a6418)
    if len(other) >= 2:
        pools.append(other)
    if not pools:
        raise RuntimeError("Need >=2 guy clips from the same angle pool (6418 or other)")
    # Weight by pool size so 6418-only videos appear in proportion to stock
    pool = random.choices(pools, weights=[len(p) for p in pools], k=1)[0]
    return random.sample(pool, 2)


def build_timeline(pattern: str, girls: list[Path], guys: list[Path]) -> list[Path]:
    g1, g2 = girls
    u1, u2 = guys
    if pattern == "GUGU":  # girl guy girl guy (70%)
        return [g1, u1, g2, u2]
    if pattern == "UGUG":  # guy girl guy girl (30%)
        return [u1, g1, u2, g2]
    raise ValueError(pattern)


def _emoji_filename_keys(cluster: str) -> list[str]:
    """Candidate Apple emoji-datasource filenames for a cluster."""
    # Prefer including FE0F for hearts; always also try without VS
    raw_cps = [ord(c) for c in cluster]
    with_vs = "-".join(f"{c:x}" for c in raw_cps)
    no_vs = "-".join(f"{c:x}" for c in raw_cps if c not in (0xFE0E, 0xFE0F))
    keys: list[str] = []
    for k in (no_vs, with_vs, f"{no_vs}-fe0f"):
        if k and k not in keys:
            keys.append(k)
    # Known aliases
    if no_vs == "2764" and "2764-fe0f" not in keys:
        keys.insert(0, "2764-fe0f")
    return keys


def _ensure_apple_emoji_file(cluster: str) -> Path | None:
    APPLE_EMOJI_DIR.mkdir(parents=True, exist_ok=True)
    for key in _emoji_filename_keys(cluster):
        dest = APPLE_EMOJI_DIR / f"{key}.png"
        if dest.is_file() and dest.stat().st_size > 100:
            return dest
        url = APPLE_EMOJI_CDN.format(key=key)
        try:
            urllib.request.urlretrieve(url, dest)
            if dest.is_file() and dest.stat().st_size > 100:
                return dest
        except Exception:
            if dest.exists():
                dest.unlink(missing_ok=True)
            continue
    return None


def _apple_emoji_rgba(cluster: str, px: int) -> Image.Image | None:
    """Load + scale Apple emoji PNG to ~px box (cached)."""
    key = (cluster, px)
    if key in _apple_emoji_cache:
        return _apple_emoji_cache[key]
    path = _ensure_apple_emoji_file(cluster)
    if path is None:
        return None
    im = Image.open(path).convert("RGBA")
    # keep aspect, fit into px x px
    im = im.resize((px, px), Image.Resampling.LANCZOS)
    _apple_emoji_cache[key] = im
    return im


def sanitize_overlay_text(text: str) -> str:
    """Normalize rare glyphs to ones we ship Apple assets for."""
    text = strip_section_banners(text)
    # Keep 🥹 / 🫶 if Apple assets exist; else map to safe ones
    if _ensure_apple_emoji_file("\U0001F979") is None:
        text = text.replace("\U0001F979", "\U0001F62D")
    if _ensure_apple_emoji_file("\U0001FAF6") is None:
        text = text.replace("\U0001FAF6", "\u2764")
    # Prefer plain heart; asset is 2764-fe0f
    text = text.replace("\u2764\uFE0F", "\u2764")
    return text


def _tokenize_runs(text: str) -> list[tuple[str, str]]:
    """Split into ('text'|'emoji', chunk) preserving order."""
    runs: list[tuple[str, str]] = []
    last = 0
    for m in _EMOJI_RE.finditer(text):
        if m.start() > last:
            chunk = text[last : m.start()]
            chunk = chunk.replace("\uFE0F", "").replace("\uFE0E", "")
            if chunk:
                runs.append(("text", chunk))
        runs.append(("emoji", m.group(0)))
        last = m.end()
    if last < len(text):
        chunk = text[last:].replace("\uFE0F", "").replace("\uFE0E", "")
        if chunk:
            runs.append(("text", chunk))
    return runs or [("text", "")]


def _emoji_px(font_size: int) -> int:
    # Slightly larger than Latin so Apple gloss reads clearly on 9:16
    return max(20, int(round(font_size * 1.18)))


def _chunk_width(
    chunk: str,
    kind: str,
    font: ImageFont.ImageFont,
    font_size: int,
    stroke: int,
) -> float:
    if not chunk:
        return 0.0
    if kind == "emoji":
        # Advance ≈ emoji box (+ tiny gap)
        return float(_emoji_px(font_size) + max(1, font_size // 16))
    bb = font.getbbox(chunk, stroke_width=stroke)
    if bb:
        return float(bb[2] - bb[0])
    return float(font.getlength(chunk)) + 2 * stroke


def _line_width_mixed(
    line: str,
    font: ImageFont.ImageFont,
    font_size: int,
    stroke: int,
) -> float:
    return sum(
        _chunk_width(chunk, kind, font, font_size, stroke)
        for kind, chunk in _tokenize_runs(line)
    )


def _wrap_mixed(
    text: str,
    font: ImageFont.ImageFont,
    font_size: int,
    max_width: int,
    stroke: int,
) -> list[str]:
    """Word-wrap; emoji stay attached to neighboring tokens."""
    tokens = re.findall(r"\S+|\s+", text)
    lines: list[str] = []
    cur = ""
    for tok in tokens:
        if tok.isspace():
            if cur and not cur.endswith(" "):
                trial = cur + " "
                if _line_width_mixed(trial, font, font_size, stroke) <= max_width:
                    cur = trial
            continue
        if not cur:
            candidate = tok
        elif cur.endswith(" "):
            candidate = cur + tok
        else:
            candidate = cur + " " + tok
        if _line_width_mixed(candidate, font, font_size, stroke) <= max_width or not cur:
            cur = candidate
        else:
            lines.append(cur.rstrip())
            cur = tok
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


def _measure_block_mixed(
    lines: list[str],
    font: ImageFont.ImageFont,
    font_size: int,
    stroke: int,
) -> tuple[int, int]:
    widths = [
        int(round(_line_width_mixed(line or " ", font, font_size, stroke)))
        for line in lines
    ]
    tw = max(widths) if widths else 0
    th = len(lines) * R.line_advance_for(font_size)
    return tw, th


def _draw_line_mixed(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y_top: int,
    line: str,
    font: ImageFont.ImageFont,
    font_size: int,
    stroke: int,
) -> None:
    """Draw Latin on baseline; paste Apple emoji PNGs optically inline."""
    ascent, _descent = font.getmetrics()
    baseline = y_top + ascent
    cx = float(x)
    sx, sy = R.TEXT_SHADOW_OFFSET
    e_px = _emoji_px(font_size)
    for kind, chunk in _tokenize_runs(line):
        if not chunk:
            continue
        if kind == "emoji":
            emoji_im = _apple_emoji_rgba(chunk, e_px)
            if emoji_im is None:
                # skip missing rather than paint tofu
                cx += _chunk_width(chunk, kind, font, font_size, stroke)
                continue
            # Sit on Latin baseline (Apple PNGs are square; leave ~12% below as descender)
            ey = int(round(baseline - e_px * 0.84))
            ex = int(round(cx))
            img.alpha_composite(emoji_im, (ex, ey))
            cx += _chunk_width(chunk, kind, font, font_size, stroke)
        else:
            draw.text(
                (cx + sx, baseline + sy),
                chunk,
                font=font,
                anchor="ls",
                fill=R.SHADOW_FILL,
                stroke_width=stroke,
                stroke_fill=R.SHADOW_FILL,
            )
            draw.text(
                (cx, baseline),
                chunk,
                font=font,
                anchor="ls",
                fill=R.TEXT_FILL,
                stroke_width=stroke,
                stroke_fill=R.STROKE_FILL,
            )
            cx += _chunk_width(chunk, "text", font, font_size, stroke)


def render_text_png(text: str, dest: Path) -> None:
    """White fill + black stroke; Apple/iOS emoji PNGs composited inline."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    clean = sanitize_overlay_text(R._normalize_text(text))
    max_w = int(W * MAX_W_RATIO)
    left = (W - max_w) // 2
    top_limit = SAFE_TOP
    bot_limit = H - SAFE_BOTTOM

    chosen = None
    for size in range(FONT_START, FONT_MIN - 1, -FONT_STEP):
        font = R._load_font(size)
        stroke = R.stroke_width_for(size)
        wrap_w = max(40, max_w - 2 * stroke)
        lines = _wrap_mixed(clean, font, size, wrap_w, stroke)
        tw, th = _measure_block_mixed(lines, font, size, stroke)
        area = (tw * th) / float(W * H)
        if th <= (bot_limit - top_limit) and (area <= MAX_AREA or size <= FONT_MIN + 2):
            chosen = (size, font, stroke, lines, tw, th)
            if area <= MAX_AREA:
                break

    if chosen is None:
        size = FONT_MIN
        font = R._load_font(size)
        stroke = R.stroke_width_for(size)
        lines = _wrap_mixed(clean, font, size, max_w - 2 * stroke, stroke)
        tw, th = _measure_block_mixed(lines, font, size, stroke)
        chosen = (size, font, stroke, lines, tw, th)

    size, font, stroke, lines, tw, th = chosen
    y0 = top_limit + max(0, (bot_limit - top_limit - th) // 2)
    y0 = int(y0 + H * TEXT_DOWN_FRAC)
    if y0 + th > bot_limit:
        y0 = max(top_limit, bot_limit - th)
    y = y0
    for line in lines:
        lw = int(round(_line_width_mixed(line or " ", font, size, stroke)))
        x = left + max(0, (tw - lw) // 2)
        _draw_line_mixed(img, draw, x, y, line, font, size, stroke)
        y += R.line_advance_for(size)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)


def concat_clips(clips: list[Path], out_mp4: Path, work: Path) -> None:
    ffmpeg = find_ffmpeg()
    # re-encode concat for reliable timestamps
    list_file = work / "concat.txt"
    lines = []
    for c in clips:
        # escape for concat demuxer
        p = c.resolve().as_posix().replace("'", r"'\''")
        lines.append(f"file '{p}'")
    list_file.write_text("\n".join(lines), encoding="utf-8")
    raw = work / "silent.mp4"
    cmd = [
        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-an",
        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-t", "6.0",
        "-movflags", "+faststart",
        str(raw),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(raw), str(out_mp4))


def burn_text_and_audio(
    video: Path,
    text_png: Path,
    audio: Path,
    dest: Path,
) -> None:
    ffmpeg = find_ffmpeg()
    # Loop/trim audio to 6s; overlay PNG full frame
    cmd = [
        ffmpeg, "-y",
        "-i", str(video),
        "-stream_loop", "-1", "-i", str(audio),
        "-i", str(text_png),
        "-filter_complex",
        "[0:v][2:v]overlay=0:0:format=auto,format=yuv420p[v];"
        "[1:a]atrim=0:6,asetpts=PTS-STARTPTS,volume=1.0[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        "-c:a", "aac", "-b:a", "160k",
        "-t", "6.0",
        "-movflags", "+faststart",
        str(dest),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=5)
    ap.add_argument("--texts", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument(
        "--cozy",
        action="store_true",
        help="Use Cozy pools (guy_1s/girl_2s), teksta_parnya + audio_new",
    )
    ap.add_argument(
        "--gugu-pct",
        type=float,
        default=0.30,
        help="Share of girl→guy→girl→guy (GUGU). Rest is UGUG. Default 0.30 → 60/200",
    )
    ap.add_argument(
        "--no-id-blocklist",
        action="store_true",
        help="Do not drop texts by numeric id (still apply keyword blocklist)",
    )
    ap.add_argument("--save-text-png", action="store_true")
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    if args.no_id_blocklist:
        TEXT_BLOCKLIST_IDS.clear()

    if args.cozy:
        girl_dir = COZY_GIRL_DIR
        guy_dir = COZY_GUY_DIR
        audio_files = list(COZY_AUDIO)
        texts_path = args.texts or COZY_TEXTS
        out_dir = args.out or COZY_OUT_DIR
    else:
        girl_dir = GIRL_DIR
        guy_dir = GUY_DIR
        audio_files = list(AUDIO)
        texts_path = args.texts or DEFAULT_TEXTS
        out_dir = args.out or (BATCH_DIR if args.n >= 50 else OUT_DIR)

    texts = load_texts(texts_path)
    girls = list(girl_dir.glob("*.mp4"))
    guys = list(guy_dir.glob("*.mp4"))
    audios = [a for a in audio_files if a.exists()]
    if len(texts) < 1:
        raise SystemExit("No texts after blocklist")
    if len(girls) < 2 or len(guys) < 2:
        raise SystemExit("Not enough clips")
    if not audios:
        raise SystemExit("No audio files")

    # 30% GUGU (girl guy girl guy), 70% UGUG — per latest brief for 200
    n_gugu = int(round(args.n * args.gugu_pct))
    n_ugug = args.n - n_gugu
    patterns = ["GUGU"] * n_gugu + ["UGUG"] * n_ugug
    random.shuffle(patterns)
    print(f"patterns: GUGU={n_gugu} UGUG={n_ugug}  out={out_dir}", flush=True)

    # Text/audio: random with replacement
    picked_texts = [random.choice(texts) for _ in range(args.n)]
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    pad = max(2, len(str(args.n)))

    for i, (pattern, text) in enumerate(zip(patterns, picked_texts), 1):
        # Reuse across videos OK; within one video still unique + same guy angle
        g_pair = random.sample(girls, 2)
        u_pair = pick_guys(guys, 2)

        timeline = build_timeline(pattern, g_pair, u_pair)
        audio = random.choice(audios)
        slug = f"{i:0{pad}d}_{pattern.lower()}"
        work = Path(tempfile.mkdtemp(prefix=f"ugc_{slug}_"))
        try:
            silent = work / "silent.mp4"
            print(f"[{i}/{args.n}] {pattern} ...", flush=True)
            concat_clips(timeline, silent, work)
            png = work / "text.png"
            render_text_png(text, png)
            dest = out_dir / f"{slug}.mp4"
            burn_text_and_audio(silent, png, audio, dest)
            if args.save_text_png:
                shutil.copy(png, out_dir / f"{slug}_text.png")
            entry = {
                "file": dest.name,
                "pattern": pattern,
                "clips": [p.name for p in timeline],
                "audio": audio.name,
                "text": text[:160] + ("…" if len(text) > 160 else ""),
            }
            manifest.append(entry)
            print(f"  OK {dest.name} ({dest.stat().st_size // 1024} KB)", flush=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)

        # checkpoint manifest every 10
        if i % 10 == 0 or i == args.n:
            man = out_dir / "manifest.json"
            man.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    gugu_done = sum(1 for e in manifest if e["pattern"] == "GUGU")
    ugug_done = sum(1 for e in manifest if e["pattern"] == "UGUG")
    print(f"\nDone: {len(manifest)} videos in {out_dir}")
    print(f"GUGU (girl-guy-girl-guy): {gugu_done}")
    print(f"UGUG (guy-girl-guy-girl): {ugug_done}")
    print(f"manifest: {out_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
