"""Code-driven motions for the procedural cat rig (lowpoly/cat_build.py).
All functions keyframe pose bones (XYZ euler) and/or the armature object between f0 and f1 (inclusive).
Bone axes: Y runs along each bone; local X is the side-to-side axis, so X rotation = pitch / leg swing.
"""
import math

import bpy
from mathutils import Euler, Vector

LEGS = {  # name: (upper, lower, paw, phase)  lateral-sequence walk: LH, LF, RH, RF
    "hind.L": ("thigh.L", "shin.L", "hpaw.L", 0.00),
    "fore.L": ("upperarm.L", "forearm.L", "fpaw.L", 0.25),
    "hind.R": ("thigh.R", "shin.R", "hpaw.R", 0.50),
    "fore.R": ("upperarm.R", "forearm.R", "fpaw.R", 0.75),
}


def _key(pb, f, rx=0.0, ry=0.0, rz=0.0, add=False):
    pb.rotation_mode = "XYZ"
    if add:
        rx += pb.rotation_euler.x
        ry += pb.rotation_euler.y
        rz += pb.rotation_euler.z
    pb.rotation_euler = (rx, ry, rz)
    pb.keyframe_insert("rotation_euler", frame=f)


def rest(arm, f):
    for pb in arm.pose.bones:
        _key(pb, f)


def idle(arm, f0, f1, tail_amp=10, seed=0.0):
    """Breathing chest, slow tail sway, tiny head drift."""
    P = arm.pose.bones
    for f in range(f0, f1 + 1):
        t = (f - f0) / 30.0 + seed
        _key(P["spine1"], f, math.radians(1.5 * math.sin(t * 2 * math.pi * 0.35)))
        for i, tb in enumerate(("tail1", "tail2", "tail3")):
            _key(P[tb], f, math.radians(-6 - 4 * i), 0, math.radians(tail_amp * (1 + 0.5 * i) * math.sin(t * 2 * math.pi * 0.45 - i * 0.6)))
        _key(P["head"], f, math.radians(2 * math.sin(t * 2 * math.pi * 0.2)), 0, math.radians(3 * math.sin(t * 2 * math.pi * 0.13)))


def walk(arm, f0, f1, speed=0.32, hz=1.7, swing=26, start=None, heading_deg=None):
    """Lateral-sequence walk; moves the armature object forward (its local -Y) at `speed` m/s."""
    P = arm.pose.bones
    if start is not None:
        arm.location = start
    if heading_deg is not None:
        arm.rotation_euler.z = math.radians(heading_deg)
    p0 = arm.location.copy()
    fwd = arm.matrix_world.to_3x3() @ Vector((0, -1, 0))
    fwd.z = 0
    fwd.normalize()
    for f in range(f0, f1 + 1):
        t = (f - f0) / 30.0
        ph = t * hz
        for leg, (up, lo, paw, off) in LEGS.items():
            a = 2 * math.pi * (ph + off)
            s = math.sin(a)
            lift = max(0.0, math.cos(a))                       # leg is in swing when cos>0
            fore = leg.startswith("fore")
            _key(P[up], f, math.radians(swing * s * (0.8 if fore else 1.0)))
            _key(P[lo], f, math.radians((22 if fore else -22) * lift))
            _key(P[paw], f, math.radians((-25 if fore else 25) * lift))
        bob = 0.006 * math.sin(4 * math.pi * ph)
        _key(P["root"], f, math.radians(1.2 * math.sin(4 * math.pi * ph)))
        _key(P["head"], f, math.radians(-3 + 2 * math.sin(4 * math.pi * ph + 1)))
        for i, tb in enumerate(("tail1", "tail2", "tail3")):
            _key(P[tb], f, math.radians(-12 + 10 * i), 0, math.radians(8 * math.sin(2 * math.pi * ph - i * 0.7)))
        arm.location = p0 + fwd * speed * t + Vector((0, 0, bob))
        arm.keyframe_insert("location", frame=f)


def sniff(arm, f0, f1, depth=38):
    """Head down to the ground, quick sniffing bobs, slight front-leg bend."""
    P = arm.pose.bones
    for f in range(f0, f1 + 1):
        t = (f - f0) / 30.0
        k = min(1.0, t / 0.35)
        bob = math.sin(t * 2 * math.pi * 3.2) * 3
        _key(P["neck"], f, math.radians(depth * k))
        _key(P["head"], f, math.radians((22 + bob) * k))
        _key(P["spine1"], f, math.radians(8 * k))
        for s in ("L", "R"):
            _key(P[f"upperarm.{s}"], f, math.radians(-10 * k))
            _key(P[f"forearm.{s}"], f, math.radians(14 * k))


def look_up(arm, f0, f1, pitch=-32, yaw=0):
    """Head and neck turn up (negative pitch) toward something above."""
    P = arm.pose.bones
    for f in range(f0, f1 + 1):
        t = (f - f0) / 30.0
        k = min(1.0, t / 0.3)
        _key(P["neck"], f, math.radians(pitch * 0.45 * k), 0, math.radians(yaw * 0.4 * k))
        _key(P["head"], f, math.radians(pitch * 0.55 * k), 0, math.radians(yaw * 0.6 * k))


def track_head(arm, target_obj, influence=0.85):
    """Make the head look at an object (constraint, on top of any keyed motion)."""
    for bn, infl in (("neck", influence * 0.35), ("head", influence)):
        c = arm.pose.bones[bn].constraints.new("DAMPED_TRACK")
        c.target = target_obj
        c.track_axis = "TRACK_Y"
        c.influence = infl


def stand_hind(arm, f0, f1, rise=0.35):
    """Rear up on the hind legs (to look out of a window): pitch the whole rig about the hind paws."""
    P = arm.pose.bones
    piv_local = Vector((0, 0.17, 0.015))
    m0 = arm.matrix_world.copy()
    piv = m0 @ piv_local
    for f in range(f0, f1 + 1):
        t = (f - f0) / 30.0
        k = min(1.0, t / rise) if rise > 0 else 1.0
        k = k * k * (3 - 2 * k)
        ang = math.radians(68) * k
        arm.matrix_world = m0
        side = m0.to_3x3() @ Vector((1, 0, 0))
        from mathutils import Matrix
        R = Matrix.Translation(piv) @ Matrix.Rotation(-ang, 4, side) @ Matrix.Translation(-piv)
        arm.matrix_world = R @ m0
        arm.keyframe_insert("location", frame=f)
        arm.keyframe_insert("rotation_euler", frame=f)
        for s in ("L", "R"):
            _key(P[f"thigh.{s}"], f, math.radians(-60 * k))       # keep hind legs under the body
            _key(P[f"shin.{s}"], f, math.radians(25 * k))
            _key(P[f"upperarm.{s}"], f, math.radians(-35 * k))    # front paws up
            _key(P[f"forearm.{s}"], f, math.radians(55 * k))
        _key(P["neck"], f, math.radians(40 * k))
        _key(P["head"], f, math.radians(20 * k))
