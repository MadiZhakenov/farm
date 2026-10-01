#!/usr/bin/env python3
"""Force honest SDR (bt709) tags on UGC encodes.

iPhone sources are often HLG/bt2020. If we re-encode to 8-bit H.264 but leave
HLG tags, phones/Telegram/MPC-HW treat the whole frame (video + text + emoji)
as HDR → neon / oversaturated. We do NOT tonemap by default: decoded 8-bit
pixels already match the "looks fine on laptop" view; we only stop lying in
metadata.
"""
from __future__ import annotations

# After geometry: tag the filter graph as SDR so libx264 writes bt709.
SET_SDR = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"

SDR_COLOR_ARGS: list[str] = [
    "-colorspace", "bt709",
    "-color_primaries", "bt709",
    "-color_trc", "bt709",
    "-color_range", "tv",
]


def vf_scale_crop_fps_sdr(w: int, h: int, fps: int | float) -> str:
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},fps={fps},format=yuv420p,{SET_SDR}"
    )


def vf_retag_sdr() -> str:
    """Re-encode an already-framed reel; keep pixels, fix color tags only."""
    return f"format=yuv420p,{SET_SDR}"


def overlay_filter_sdr() -> str:
    """filter_complex video branch for text burn — end in yuv420p + SDR params."""
    return (
        f"[0:v][2:v]overlay=0:0:format=auto,format=yuv420p,{SET_SDR}[v];"
        "[1:a]atrim=0:6,asetpts=PTS-STARTPTS,volume=1.0[a]"
    )
