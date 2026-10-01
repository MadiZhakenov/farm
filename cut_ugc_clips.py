#!/usr/bin/env python3
"""
Cut UGC raw MOVs into typed clip inventory for batch reel assembly.

Pattern (reference): girl 1s → guy 2s → girl 1s → guy 2s

  python cut_ugc_clips.py
  python cut_ugc_clips.py --dry-run
  python cut_ugc_clips.py --thumbs
  python cut_ugc_clips.py --min-score 0.55

Outputs:
  output/clips_ugc/girl_1s/
  output/clips_ugc/guy_2s/
  output/clips_ugc/manifest.json
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "downloads" / "raw_materials"
OUT_DIR = ROOT / "output" / "clips_ugc"
MANIFEST_NAME = "manifest.json"

SOURCE_ROLES: dict[str, str] = {
    "IMG_6418.mov": "guy",
    "IMG_6419.mov": "guy",
    "IMG_6419 (2).mov": "guy",
    "IMG_6419 (3).mov": "guy",
    "IMG_6424.mov": "girl",
    "IMG_6425.mov": "girl",
}

ROLE_DURATION = {"girl": 1.0, "guy": 2.0}
ROLE_DIR = {"girl": "girl_1s", "guy": "guy_2s"}

EDGE_MARGIN = 0.35
SCAN_STEP_FRAC = 0.5  # non-overlap-ish scan; greedy still dedupes
SAMPLE_FPS = 4.0  # analyze at 4 fps (sequential decode)
ANALYZE_MAX_SIDE = 480
EXPORT_W, EXPORT_H = 1080, 1920
EXPORT_FPS = 30


@dataclass
class ClipPick:
    source: str
    role: str
    start: float
    duration: float
    score: float
    reasons: list[str]
    out_name: str
    metrics: dict


def find_bin(name: str) -> str | None:
    return shutil.which(name)


def probe_duration(path: Path) -> float:
    ffprobe = find_bin("ffprobe")
    r = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"ffprobe failed: {path.name}")
    return float(r.stdout.strip())


def probe_rotation(path: Path) -> int:
    """Return display rotation degrees (0/90/-90/180) from first frame side data."""
    ffprobe = find_bin("ffprobe")
    r = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream_side_data=rotation",
            "-of", "default=noprint_wrappers=1:nokey=1",
            "-read_intervals", "%+#1",
            str(path),
        ],
        capture_output=True, text=True, timeout=60,
    )
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            return int(float(line))
        except ValueError:
            continue
    return 0


def analyze_vf(_path: Path) -> str:
    # Let ffmpeg autorotate via displaymatrix (do NOT pass -noautorotate).
    return (
        f"scale='min({ANALYZE_MAX_SIDE},iw)':'min({ANALYZE_MAX_SIDE},ih)'"
        f":force_original_aspect_ratio=decrease,fps={SAMPLE_FPS}"
    )


def slug_source(name: str) -> str:
    return re.sub(r"[^\w]+", "_", Path(name).stem).strip("_")


def sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def colorfulness(bgr: np.ndarray) -> float:
    b, g, r = cv2.split(bgr.astype(np.float32))
    rg = np.abs(r - g)
    yb = np.abs(0.5 * (r + g) - b)
    return float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))


def downscale(frame: np.ndarray, max_side: int = ANALYZE_MAX_SIDE) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = max_side / max(h, w)
    if scale >= 1:
        return frame
    return cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def score_guy_frame(frame: np.ndarray) -> tuple[float, dict, list[str]]:
    h, w = frame.shape[:2]
    # Phone sits mid/lower-center in over-shoulder UGC
    y0, y1 = int(h * 0.30), int(h * 0.95)
    x0, x1 = int(w * 0.10), int(w * 0.90)
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return 0.0, {}, ["empty_roi"]

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    # Room is dark; judge the phone by bright-tail + colorful pixels
    p80 = float(np.percentile(gray, 80))
    p95 = float(np.percentile(gray, 95))
    sat = float(np.mean(hsv[:, :, 1]))
    sharp = sharpness(gray)
    colorful = colorfulness(roi)
    bright_mask = (gray > 55) & (hsv[:, :, 1] > 35)
    bright_frac = float(np.mean(bright_mask))
    # Colorful bright = game liquid tubes
    game_mask = (gray > 60) & (hsv[:, :, 1] > 70)
    game_frac = float(np.mean(game_mask))

    reasons: list[str] = []
    score = 0.40

    if p95 > 120 and bright_frac > 0.04:
        score += 0.25
    elif p80 > 50 and bright_frac > 0.03:
        score += 0.12
    else:
        reasons.append("dark_screen")
        score -= 0.25

    if game_frac > 0.03 and colorful > 20:
        score += 0.25
    elif sat > 40 and colorful > 15:
        score += 0.12
    else:
        reasons.append("dull_ui")
        score -= 0.12

    if bright_frac > 0.06:
        score += 0.15
    elif bright_frac < 0.02:
        reasons.append("no_phone_glow")
        score -= 0.3

    if sharp > 50:
        score += 0.15
    elif sharp > 25:
        score += 0.06
    else:
        reasons.append("blurry")
        score -= 0.25

    metrics = {
        "p80": round(p80, 1),
        "p95": round(p95, 1),
        "sat": round(sat, 1),
        "colorful": round(colorful, 1),
        "sharp": round(sharp, 1),
        "bright_frac": round(bright_frac, 3),
        "game_frac": round(game_frac, 3),
    }
    return max(0.0, min(1.0, score)), metrics, reasons


def score_girl_frame(frame: np.ndarray, face_cascade: cv2.CascadeClassifier) -> tuple[float, dict, list[str]]:
    h, w = frame.shape[:2]
    y0, y1 = int(h * 0.05), int(h * 0.75)
    x0, x1 = int(w * 0.08), int(w * 0.92)
    roi = frame[y0:y1, x0:x1]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    # Warm LED casts orange — equalize helps Haar a bit
    gray_eq = cv2.equalizeHist(gray)
    sharp = sharpness(gray)
    mean_luma = float(np.mean(gray))
    faces = face_cascade.detectMultiScale(gray_eq, scaleFactor=1.07, minNeighbors=3, minSize=(32, 32))
    if len(faces) == 0:
        # retry without hist eq
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.07, minNeighbors=3, minSize=(32, 32))

    reasons: list[str] = []
    score = 0.35
    face_area = 0.0
    face_cx = 0.5

    if len(faces) == 0:
        # Soft fallback: upper-center skin-ish blob (HSV) — not a pass by itself
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        skin = cv2.inRange(hsv, (0, 30, 50), (35, 200, 255))
        skin_frac = float(np.mean(skin > 0))
        if skin_frac > 0.12 and sharp > 30:
            reasons.append("no_face_soft")
            score += 0.05
        else:
            reasons.append("no_face")
            score -= 0.35
    else:
        fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        face_area = (fw * fh) / float(roi.shape[0] * roi.shape[1])
        face_cx = (fx + fw / 2) / roi.shape[1]
        score += 0.35
        if 0.06 <= face_area <= 0.55:
            score += 0.15
        elif face_area < 0.04:
            reasons.append("face_tiny")
            score -= 0.15
        if abs(face_cx - 0.5) < 0.25:
            score += 0.08
        else:
            reasons.append("face_offcenter")

    if sharp > 45:
        score += 0.15
    elif sharp < 18:
        reasons.append("blurry")
        score -= 0.25

    if mean_luma < 25:
        reasons.append("too_dark")
        score -= 0.2
    elif mean_luma > 40:
        score += 0.08

    metrics = {
        "mean_luma": round(mean_luma, 1),
        "sharp": round(sharp, 1),
        "faces": int(len(faces)),
        "face_area": round(face_area, 3),
        "face_cx": round(face_cx, 3),
    }
    return max(0.0, min(1.0, score)), metrics, reasons


def analyze_timeline(
    path: Path,
    role: str,
    face_cascade: cv2.CascadeClassifier | None,
) -> tuple[np.ndarray, list[dict], list[list[str]], np.ndarray]:
    """Sequential decode at SAMPLE_FPS. Returns times, metrics, reasons, scores."""
    ffmpeg = find_bin("ffmpeg")
    assert ffmpeg
    vf = analyze_vf(path)
    print(f"  vf={vf}", flush=True)

    probe_cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-i", str(path),
        "-an", "-vf", vf,
        "-frames:v", "1",
        "-f", "image2pipe", "-vcodec", "png",
        "pipe:1",
    ]
    pr = subprocess.run(probe_cmd, capture_output=True, timeout=120)
    if pr.returncode != 0 or not pr.stdout:
        print("  ffmpeg probe failed, falling back to OpenCV", flush=True)
        return _analyze_timeline_cv2(path, role, face_cascade)

    arr = np.frombuffer(pr.stdout, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        print("  ffmpeg png decode failed, falling back to OpenCV", flush=True)
        return _analyze_timeline_cv2(path, role, face_cascade)
    fh, fw = img.shape[:2]
    print(f"  analyze frame size: {fw}x{fh}", flush=True)
    frame_bytes = fh * fw * 3

    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-i", str(path),
        "-an", "-vf", vf,
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None

    times: list[float] = []
    scores: list[float] = []
    metrics_list: list[dict] = []
    reasons_list: list[list[str]] = []
    prev_gray = None
    idx = 0

    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if not buf or len(buf) < frame_bytes:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape((fh, fw, 3)).copy()
            t = idx / SAMPLE_FPS
            if role == "guy":
                s, m, r = score_guy_frame(frame)
            else:
                assert face_cascade is not None
                s, m, r = score_girl_frame(frame, face_cascade)

            gray = cv2.cvtColor(cv2.resize(frame, (120, 200)), cv2.COLOR_BGR2GRAY)
            if prev_gray is not None:
                motion = float(np.mean(cv2.absdiff(prev_gray, gray)))
            else:
                motion = 0.0
            prev_gray = gray
            m = dict(m)
            m["motion"] = round(motion, 2)

            # motion adjustments per-frame (window will average)
            if role == "guy":
                if motion > 28:
                    r = r + ["camera_whip"]
                    s = max(0.0, s - 0.15)
                elif motion < 0.6 and idx > 0:
                    r = r + ["frozen"]
                    s = max(0.0, s - 0.08)
            else:
                if motion > 22:
                    r = r + ["camera_whip"]
                    s = max(0.0, s - 0.18)

            times.append(t)
            scores.append(s)
            metrics_list.append(m)
            reasons_list.append(r)
            idx += 1
            if idx % 40 == 0:
                print(f"    analyzed {t:.1f}s...", flush=True)
    finally:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:
            pass

    return np.array(times, dtype=np.float64), metrics_list, reasons_list, np.array(scores, dtype=np.float64)


def _analyze_timeline_cv2(
    path: Path,
    role: str,
    face_cascade: cv2.CascadeClassifier | None,
) -> tuple[np.ndarray, list[dict], list[list[str]], np.ndarray]:
    cap = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    step = max(1, int(round(fps / SAMPLE_FPS)))
    times: list[float] = []
    scores: list[float] = []
    metrics_list: list[dict] = []
    reasons_list: list[list[str]] = []
    prev_gray = None
    i = 0
    kept = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if i % step != 0:
                i += 1
                continue
            t = i / fps
            frame = downscale(frame)
            if role == "guy":
                s, m, r = score_guy_frame(frame)
            else:
                assert face_cascade is not None
                s, m, r = score_girl_frame(frame, face_cascade)
            gray = cv2.cvtColor(cv2.resize(frame, (120, 200)), cv2.COLOR_BGR2GRAY)
            motion = float(np.mean(cv2.absdiff(prev_gray, gray))) if prev_gray is not None else 0.0
            prev_gray = gray
            m = dict(m)
            m["motion"] = round(motion, 2)
            times.append(t)
            scores.append(s)
            metrics_list.append(m)
            reasons_list.append(r)
            kept += 1
            i += 1
            if kept % 40 == 0:
                print(f"    analyzed {t:.1f}s...", flush=True)
    finally:
        cap.release()
    return np.array(times), metrics_list, reasons_list, np.array(scores, dtype=np.float64)


def pick_from_timeline(
    path: Path,
    role: str,
    duration: float,
    min_score: float,
    times: np.ndarray,
    metrics_list: list[dict],
    reasons_list: list[list[str]],
    scores: np.ndarray,
) -> list[ClipPick]:
    clip_dur = ROLE_DURATION[role]
    usable_start = EDGE_MARGIN
    usable_end = duration - EDGE_MARGIN
    if usable_end - usable_start < clip_dur:
        print(f"  skip {path.name}: too short")
        return []

    step = clip_dur * SCAN_STEP_FRAC
    candidates: list[tuple[float, float, dict, list[str]]] = []
    t = usable_start
    while t + clip_dur <= usable_end + 1e-6:
        mask = (times >= t) & (times < t + clip_dur)
        idxs = np.where(mask)[0]
        if len(idxs) < 2:
            t += step
            continue
        win_scores = scores[idxs]
        base = float(np.mean(win_scores))
        base -= min(0.2, float(np.std(win_scores)) * 0.35)
        motions = [metrics_list[i].get("motion", 0.0) for i in idxs]
        motion = float(np.mean(motions)) if motions else 0.0
        if role == "guy":
            if 2.0 <= motion <= 18.0:
                base += 0.08
            elif motion < 0.8:
                base -= 0.1
            elif motion > 28:
                base -= 0.15
        else:
            if motion > 22:
                base -= 0.18
            elif motion < 12:
                base += 0.05

        # aggregate reasons
        uniq: dict[str, int] = {}
        for i in idxs:
            for r in reasons_list[i]:
                uniq[r] = uniq.get(r, 0) + 1
        reasons = [f"{k}x{v}" if v > 1 else k for k, v in sorted(uniq.items(), key=lambda x: -x[1])[:5]]

        n = len(idxs)
        # Hard rejects — bad moments we never want in the pool
        if role == "girl" and uniq.get("no_face", 0) + uniq.get("no_face_soft", 0) >= max(2, n // 2):
            t += step
            continue
        if role == "girl" and uniq.get("camera_whip", 0) >= max(2, n // 2):
            t += step
            continue
        if role == "guy" and uniq.get("no_phone_glow", 0) >= max(2, (n * 3) // 4):
            t += step
            continue
        if role == "guy" and uniq.get("blurry", 0) >= max(2, (n * 3) // 4):
            t += step
            continue
        if uniq.get("camera_whip", 0) >= max(2, n // 2):
            t += step
            continue

        avg_metrics: dict = {"motion": round(motion, 2)}
        keys = set().union(*(metrics_list[i].keys() for i in idxs))
        for k in keys:
            if k == "motion":
                continue
            vals = [metrics_list[i][k] for i in idxs if isinstance(metrics_list[i].get(k), (int, float))]
            if vals:
                avg_metrics[k] = round(float(np.mean(vals)), 3)

        candidates.append((t, max(0.0, min(1.0, base)), avg_metrics, reasons))
        t += step

    candidates.sort(key=lambda x: -x[1])
    picked: list[ClipPick] = []
    occupied: list[tuple[float, float]] = []

    def overlaps(a0: float, a1: float) -> bool:
        for b0, b1 in occupied:
            if a0 < b1 - 0.05 and a1 > b0 + 0.05:
                return True
        return False

    src_slug = slug_source(path.name)
    for start, score, metrics, reasons in candidates:
        if score < min_score:
            continue
        end = start + clip_dur
        if overlaps(start, end):
            continue
        occupied.append((start, end))
        picked.append(
            ClipPick(
                source=path.name,
                role=role,
                start=round(start, 3),
                duration=clip_dur,
                score=round(score, 3),
                reasons=reasons,
                out_name="",
                metrics=metrics,
            )
        )

    picked.sort(key=lambda c: c.start)
    for i, c in enumerate(picked, 1):
        c.out_name = f"{src_slug}_{role}_{i:03d}_{c.start:.2f}s.mp4"
    return picked


def export_clip(src: Path, pick: ClipPick, dest: Path) -> None:
    ffmpeg = find_bin("ffmpeg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Autorotate via displaymatrix, then fit 9:16
    vf = (
        f"scale={EXPORT_W}:{EXPORT_H}:force_original_aspect_ratio=increase,"
        f"crop={EXPORT_W}:{EXPORT_H},fps={EXPORT_FPS}"
    )
    cmd = [
        ffmpeg, "-y",
        "-ss", f"{pick.start:.3f}",
        "-t", f"{pick.duration:.3f}",
        "-i", str(src),
        "-an",
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(dest),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size < 1000:
        raise RuntimeError(f"ffmpeg failed for {pick.out_name}: {(r.stderr or '')[-500:]}")


def write_thumb(src: Path, pick: ClipPick, thumb_path: Path) -> None:
    ffmpeg = find_bin("ffmpeg")
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    t = pick.start + pick.duration * 0.5
    cmd = [
        ffmpeg, "-y", "-ss", f"{t:.3f}", "-i", str(src),
        "-frames:v", "1", "-q:v", "4", str(thumb_path),
    ]
    subprocess.run(cmd, capture_output=True, timeout=60)


def load_face_cascade() -> cv2.CascadeClassifier:
    path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    cc = cv2.CascadeClassifier(str(path))
    if cc.empty():
        raise RuntimeError(f"Failed to load face cascade: {path}")
    return cc


def main() -> int:
    ap = argparse.ArgumentParser(description="Cut UGC raws into girl_1s / guy_2s clip pools")
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--min-score", type=float, default=0.48)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--thumbs", action="store_true")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()

    # line-buffered prints
    sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

    if not find_bin("ffmpeg") or not find_bin("ffprobe"):
        print("ffmpeg/ffprobe required", file=sys.stderr)
        return 1

    face_cascade = load_face_cascade()
    sources = []
    for name, role in SOURCE_ROLES.items():
        if args.only and name not in args.only:
            continue
        path = args.raw_dir / name
        if not path.exists():
            print(f"MISSING: {path}")
            continue
        sources.append((path, role))

    if not sources:
        print("No sources found")
        return 1

    all_picks: list[ClipPick] = []

    for path, role in sources:
        dur = probe_duration(path)
        print(f"\n=== {path.name}  role={role}  dur={dur:.2f}s  clip={ROLE_DURATION[role]}s ===", flush=True)
        fc = face_cascade if role == "girl" else None
        times, metrics_list, reasons_list, scores = analyze_timeline(path, role, fc)
        print(f"  timeline samples: {len(times)}", flush=True)
        if len(times) == 0:
            print("  WARNING: no samples")
            continue
        print(
            f"  score min/mean/max: {scores.min():.2f}/{scores.mean():.2f}/{scores.max():.2f}",
            flush=True,
        )
        picks = pick_from_timeline(
            path, role, dur, args.min_score, times, metrics_list, reasons_list, scores
        )
        print(f"  kept {len(picks)} clips (min_score={args.min_score})", flush=True)
        for p in picks:
            why = ", ".join(p.reasons[:3]) or "ok"
            print(f"    [{p.score:.2f}] {p.start:6.2f}s  {why}", flush=True)
        all_picks.extend(picks)

    exported = 0
    if not args.dry_run:
        for pick in all_picks:
            src = args.raw_dir / pick.source
            dest = args.out_dir / ROLE_DIR[pick.role] / pick.out_name
            print(f"export {pick.out_name} ...", flush=True)
            export_clip(src, pick, dest)
            exported += 1
            if args.thumbs:
                write_thumb(
                    src, pick,
                    args.out_dir / "_thumbs" / pick.role / (Path(pick.out_name).stem + ".jpg"),
                )

    by_role = {"girl": 0, "guy": 0}
    for p in all_picks:
        by_role[p.role] += 1

    manifest = {
        "girl_duration": ROLE_DURATION["girl"],
        "guy_duration": ROLE_DURATION["guy"],
        "pattern": "girl(1s) → guy(2s) → girl(1s) → guy(2s)",
        "min_score": args.min_score,
        "export_size": [EXPORT_W, EXPORT_H],
        "counts": by_role,
        "max_assemblies_from_pool": min(by_role["girl"] // 2, by_role["guy"] // 2),
        "clips": [asdict(p) for p in all_picks],
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    man_path = args.out_dir / MANIFEST_NAME
    man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n======== SUMMARY ========", flush=True)
    print(f"girl_1s: {by_role['girl']}", flush=True)
    print(f"guy_2s:  {by_role['guy']}", flush=True)
    print(f"assemblies possible now: {manifest['max_assemblies_from_pool']}", flush=True)
    print(f"exported: {exported}" + (" (dry-run)" if args.dry_run else ""), flush=True)
    print(f"manifest: {man_path}", flush=True)
    if by_role["girl"] < 400:
        print(
            f"NOTE: for 200 finals need ~400 girl_1s clips; "
            f"have {by_role['girl']}. Need more girl footage.",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
