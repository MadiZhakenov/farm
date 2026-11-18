"""Kimodo BVH (SOMA skeleton, --bvh_standard_tpose) -> Quaternius low-poly rig (T-pose, faces -Y).

World-delta retarget: for every mapped target bone,
    posed_rot = (src_posed_rot @ src_rest_rot^-1) @ tgt_rest_rot
i.e. the source bone's rotation away from its T-pose is applied to the target bone's T-pose in the
character's own frame. Both rigs are T-pose and face -Y, so no extra alignment is needed.
Quaternius specifics: legs hang off "Body"; Foot.L/R are free bones parented to Root (IK targets in
the original rig) -> placed at the end of the posed shin, rotated like the source foot.
Usage from shot.py:  apply_bvh(arm, "motion.bvh", scene, start_frame)
"""
import math

import bpy
from mathutils import Matrix, Vector

# target bone -> source bone whose world rotation delta drives it
MAP = {
    "Body": "Hips", "Hips": "Hips",
    "Abdomen": "Spine1", "Torso": "Spine2", "Chest": "Chest",
    "Neck": "Neck1", "Head": "Head",
    "Shoulder.L": "LeftShoulder", "UpperArm.L": "LeftArm", "LowerArm.L": "LeftForeArm", "Wrist.L": "LeftHand",
    "Shoulder.R": "RightShoulder", "UpperArm.R": "RightArm", "LowerArm.R": "RightForeArm", "Wrist.R": "RightHand",
    "UpperLeg.L": "LeftLeg", "LowerLeg.L": "LeftShin", "Foot.L": "LeftFoot",
    "UpperLeg.R": "RightLeg", "LowerLeg.R": "RightShin", "Foot.R": "RightFoot",
}
FOOT_OF = {"Foot.L": "LowerLeg.L", "Foot.R": "LowerLeg.R"}
# Rest-pose mismatch fixes (degrees about the character X axis, + = tip forward/down): Kimodo's T-pose
# head/neck are pitched down vs a neutral gaze, so a forward-looking walk otherwise stares ~25 deg up.
REST_FIX = {"Neck": 5.0, "Head": 20.0}


def _rot(m: Matrix) -> Matrix:
    return m.to_3x3().normalized()


def apply_bvh(arm: bpy.types.Object, bvh_path: str, scene, start: int = 1, scale: float | None = None) -> int:
    """Bake the BVH onto `arm` starting at scene frame `start`. Returns the number of frames."""
    before = set(bpy.data.objects)
    bpy.ops.import_anim.bvh(filepath=bvh_path, global_scale=0.01, rotate_mode="NATIVE",
                            update_scene_fps=False, update_scene_duration=False)
    src = next(o for o in bpy.data.objects if o not in before and o.type == "ARMATURE")
    f0, f1 = (int(round(x)) for x in src.animation_data.action.frame_range)

    # Character frame = the armature's world frame right after glTF import (Z-up, faces -Y). The glTF
    # armature object carries a Y-up->Z-up quaternion rotation and a uniform scale, so armature space is
    # NOT the character frame. Call this before placing the actor (location 0).
    mw = arm.matrix_world.copy()
    S = mw.to_scale().x
    R0 = _rot(mw)
    tb = arm.data.bones
    sb = src.data.bones
    # target rest matrices in the character frame: metres, pure rotation
    rest_m = {b.name: Matrix.Translation(mw @ b.matrix_local.translation) @ (R0 @ _rot(b.matrix_local)).to_4x4()
              for b in tb}
    if isinstance(src_yaw_deg, str):                     # "auto:<target facing deg>": measure the clip's frame-1 facing
        tgt_face = math.radians(float(src_yaw_deg.split(":")[1]))
        scene.frame_set(f0)
        P0 = src.pose.bones
        lr = P0["LeftArm"].matrix.translation - P0["RightArm"].matrix.translation
        face = lr.cross(Vector((0, 0, 1)))
        src_yaw_deg = math.degrees(tgt_face - math.atan2(face.y, face.x))
    Qy = Matrix.Rotation(math.radians(src_yaw_deg), 4, "Z")
    src_rest = {b.name: Qy @ b.matrix_local for b in sb}
    if scale is None:   # leg length ratio target/source
        scale = (rest_m["UpperLeg.L"].translation.z) / max(1e-6, src_rest["LeftLeg"].translation.z)
    hips0 = src_rest["Hips"].translation.copy()
    body0 = rest_m["Body"].translation.copy()

    # foot offset from the shin, in the shin's rest frame (metres)
    foot_off = {f: rest_m[s].inverted() @ rest_m[f].translation for f, s in FOOT_OF.items()}

    order = []                                                          # parents before children
    def walk(b):
        order.append(b)
        for c in b.children:
            walk(c)
    for b in tb:
        if b.parent is None:
            walk(b)

    arm.animation_data_create()
    arm.animation_data.action = None
    for tr in list(arm.animation_data.nla_tracks):
        arm.animation_data.nla_tracks.remove(tr)
    pbs = arm.pose.bones
    for pb in pbs:
        pb.rotation_mode = "QUATERNION"

    n = f1 - f0 + 1
    for i in range(n):
        scene.frame_set(f0 + i)
        sp = {pb.name: Qy @ pb.matrix for pb in src.pose.bones}          # source armature space = metres
        posed = {}                                                          # target, metres
        for b in order:
            name = b.name
            if b.parent is not None:
                chain = posed[b.parent.name] @ (rest_m[b.parent.name].inverted() @ rest_m[name])
            else:
                chain = rest_m[name].copy()
            want = chain.copy()
            sname = MAP.get(name)
            if sname and sname in sp:
                d = _rot(sp[sname]) @ _rot(src_rest[sname]).inverted()
                r = d @ _rot(rest_m[name])
                if name in REST_FIX:
                    r = d @ Matrix.Rotation(math.radians(REST_FIX[name]), 3, "X") @ _rot(rest_m[name])
                if name == "Body":
                    h = sp["Hips"].translation
                    t = Vector((body0.x + (h.x - hips0.x) * scale, body0.y + (h.y - hips0.y) * scale,
                                h.z * body0.z / hips0.z))      # height scales with the pelvis height ratio
                elif name in FOOT_OF:
                    t = posed[FOOT_OF[name]] @ foot_off[name]
                else:
                    t = chain.translation
                want = Matrix.Translation(t) @ r.to_4x4()
            posed[name] = want
            # pose basis = (parent posed @ rest_rel)^-1 @ want; its translation back to armature units
            basis = chain.inverted() @ want
            loc, q, _ = basis.decompose()
            pb = pbs[name]
            pb.location = loc / S
            pb.rotation_quaternion = q
            pb.keyframe_insert("location", frame=start + i)
            pb.keyframe_insert("rotation_quaternion", frame=start + i)

    act = src.animation_data.action
    bpy.data.objects.remove(src, do_unlink=True)
    if act and act.users == 0:
        bpy.data.actions.remove(act)
    return n


# ---------------------------------------------------------------------------------------------
# ReadyPlayerMe / Mixamo-named rigs (A-pose rest). Every mapped bone is first aligned so its rest
# direction (bone -> child) matches the Kimodo T-pose direction, then the world delta is applied.
RPM_MAP = {  # target bone: (source bone, target child for direction, source child for direction)
    "Hips": ("Hips", "Spine", "Spine1"),
    "Spine": ("Spine1", "Spine1", "Spine2"), "Spine1": ("Spine2", "Spine2", "Chest"), "Spine2": ("Chest", "Neck", "Neck1"),
    "Neck": ("Neck1", "Head", "Head"), "Head": ("Head", "HeadTop_End", "HeadEnd"),
    "LeftShoulder": ("LeftShoulder", "LeftArm", "LeftArm"), "LeftArm": ("LeftArm", "LeftForeArm", "LeftForeArm"),
    "LeftForeArm": ("LeftForeArm", "LeftHand", "LeftHand"), "LeftHand": ("LeftHand", "LeftHandMiddle1", "LeftHandMiddle1"),
    "RightShoulder": ("RightShoulder", "RightArm", "RightArm"), "RightArm": ("RightArm", "RightForeArm", "RightForeArm"),
    "RightForeArm": ("RightForeArm", "RightHand", "RightHand"), "RightHand": ("RightHand", "RightHandMiddle1", "RightHandMiddle1"),
    "LeftUpLeg": ("LeftLeg", "LeftLeg", "LeftShin"), "LeftLeg": ("LeftShin", "LeftFoot", "LeftFoot"),
    "LeftFoot": ("LeftFoot", "LeftToeBase", "LeftToeBase"), "LeftToeBase": ("LeftToeBase", "LeftToe_End", "LeftToeEnd"),
    "RightUpLeg": ("RightLeg", "RightLeg", "RightShin"), "RightLeg": ("RightShin", "RightFoot", "RightFoot"),
    "RightFoot": ("RightFoot", "RightToeBase", "RightToeBase"), "RightToeBase": ("RightToeBase", "RightToe_End", "RightToeEnd"),
}


# Kimodo's T-pose head is pitched down vs a neutral gaze; on the RPM rig a forward-looking walk otherwise
# stares ~41 deg up (measured on slip_3 frames 1-50). + = tip forward/down about the character X axis.
RPM_REST_FIX = {"Neck": 6.0, "Head": 36.0}


def apply_bvh_rpm(arm: bpy.types.Object, bvh_path: str, scene, start: int = 1, frames: tuple | None = None,
                  hold_root: bool = False, delta_bones=(), src_yaw_deg: float = 0.0) -> int:
    """Bake a Kimodo BVH onto a ReadyPlayerMe armature (call before placing the actor).
    delta_bones: bones that copy the source's rotation CHANGE from rest (no direction alignment). Use it for
    spine/neck/head/legs when both rest poses stand upright: copying raw directions onto a spine with other
    segment lengths leans the chest back and tips the head up (Characters_psx, measured).
    src_yaw_deg: turn the whole source clip about Z first so it faces like the target's rest pose
    (Kimodo faces -Y; Characters_psx rests facing +X -> +90). Otherwise limbs copy a 90-deg-off facing.
    frames=(first, last) source frames to use; hold_root keeps the hips at their first-frame xy (sitting)."""
    before = set(bpy.data.objects)
    bpy.ops.import_anim.bvh(filepath=bvh_path, global_scale=0.01, rotate_mode="NATIVE",
                            update_scene_fps=False, update_scene_duration=False)
    src = next(o for o in bpy.data.objects if o not in before and o.type == "ARMATURE")
    f0, f1 = frames or tuple(int(round(x)) for x in src.animation_data.action.frame_range)

    mw = arm.matrix_world.copy()
    S = mw.to_scale().x
    R0 = _rot(mw)
    tb, sb = arm.data.bones, src.data.bones
    rest_m = {b.name: Matrix.Translation(mw @ b.matrix_local.translation) @ (R0 @ _rot(b.matrix_local)).to_4x4()
              for b in tb}
    if isinstance(src_yaw_deg, str):                     # "auto:<target facing deg>": measure the clip's frame-1 facing
        tgt_face = math.radians(float(src_yaw_deg.split(":")[1]))
        scene.frame_set(f0)
        P0 = src.pose.bones
        lr = P0["LeftArm"].matrix.translation - P0["RightArm"].matrix.translation
        face = lr.cross(Vector((0, 0, 1)))
        src_yaw_deg = math.degrees(tgt_face - math.atan2(face.y, face.x))
    Qy = Matrix.Rotation(math.radians(src_yaw_deg), 4, "Z")
    src_rest = {b.name: Qy @ b.matrix_local for b in sb}

    def head_t(n):
        return rest_m[n].translation

    def head_s(n):
        return src_rest[n].translation

    align = {}
    for t, (s, tc, sc) in RPM_MAP.items():
        if t in tb and tc in tb and s in sb and sc in sb:
            dt = (head_t(tc) - head_t(t)).normalized()
            ds = (head_s(sc) - head_s(s)).normalized()
            align[t] = dt.rotation_difference(ds).to_matrix() if dt.length > 0 and ds.length > 0 else Matrix.Identity(3)
    scale = head_t("LeftUpLeg").z / max(1e-6, head_s("LeftLeg").z)
    hips_t0, hips_s0 = head_t("Hips").copy(), head_s("Hips").copy()

    order = []
    def walk(b):
        order.append(b)
        for c in b.children:
            walk(c)
    for b in tb:
        if b.parent is None:
            walk(b)

    arm.animation_data_create()
    arm.animation_data.action = None
    for tr in list(arm.animation_data.nla_tracks):
        arm.animation_data.nla_tracks.remove(tr)
    pbs = arm.pose.bones
    for pb in pbs:
        pb.rotation_mode = "QUATERNION"

    first_xy = None
    n = f1 - f0 + 1
    for i in range(n):
        scene.frame_set(f0 + i)
        sp = {pb.name: Qy @ pb.matrix for pb in src.pose.bones}
        posed = {}
        for b in order:
            name = b.name
            chain = (posed[b.parent.name] @ (rest_m[b.parent.name].inverted() @ rest_m[name])
                     if b.parent is not None else rest_m[name].copy())
            want = chain.copy()
            m = RPM_MAP.get(name)
            if m and m[0] in sp:
                s = m[0]
                d = _rot(sp[s]) @ _rot(src_rest[s]).inverted()
                al = Matrix.Identity(3) if name in delta_bones else align.get(name, Matrix.Identity(3))
                r = d @ al @ _rot(rest_m[name])
                if name in RPM_REST_FIX and name not in delta_bones:
                    r = d @ Matrix.Rotation(math.radians(RPM_REST_FIX[name]), 3, "X") @ align.get(name, Matrix.Identity(3)) @ _rot(rest_m[name])
                t = chain.translation
                if name == "Hips":
                    h = sp["Hips"].translation
                    if first_xy is None:
                        first_xy = h.copy()
                    hx, hy = (first_xy.x, first_xy.y) if hold_root else (h.x, h.y)
                    t = Vector((hips_t0.x + (hx - hips_s0.x) * scale, hips_t0.y + (hy - hips_s0.y) * scale,
                                h.z * hips_t0.z / hips_s0.z))
                want = Matrix.Translation(t) @ r.to_4x4()
            posed[name] = want
            basis = chain.inverted() @ want
            loc, q, _ = basis.decompose()
            pb = pbs[name]
            pb.location = loc / S
            pb.rotation_quaternion = q
            pb.keyframe_insert("location", frame=start + i)
            pb.keyframe_insert("rotation_quaternion", frame=start + i)

    act = src.animation_data.action
    bpy.data.objects.remove(src, do_unlink=True)
    if act and act.users == 0:
        bpy.data.actions.remove(act)
    return n


def _fcurves(act):
    """all F-curves of an action (legacy list or Blender 4.4+/5 layered channelbags)."""
    if act is None:
        return []
    try:
        return list(act.fcurves)
    except AttributeError:
        pass
    out = []
    for layer in getattr(act, "layers", []):
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                out += list(bag.fcurves)
    return out


def nod_head(arm: bpy.types.Object, deg: float, split=(("Neck", 0.35), ("Head", 0.65)), facing=None):
    """Pitch the head down (+deg) / up (-deg) on top of baked motion, about each bone's own side axis.
    Kimodo's neutral stand reads ~17 deg 'chin up' on the Characters_psx rig (measured: nod_head(arm, 17)
    brings it to ~1 deg); the RPM_REST_FIX axis does not pitch this rig, so the fix is applied after baking."""
    from mathutils import Quaternion
    P = arm.pose.bones
    mw3 = arm.matrix_world.to_3x3()
    if facing is not None:                                     # rest facing in world space (Characters_psx: -Y)
        f = Vector(facing)
    elif "LeftToeBase" in P and "LeftFoot" in P:
        f = mw3 @ (arm.data.bones["LeftToeBase"].head_local - arm.data.bones["LeftFoot"].head_local)
    else:
        f = Vector((0, -1, 0))
    f.z = 0
    f.normalize()
    side = mw3.inverted() @ f.cross(Vector((0, 0, 1))).normalized()   # world side axis -> armature space
    act = arm.animation_data.action if arm.animation_data else None
    fcs = _fcurves(act)
    for name, share in split:
        if name not in P:
            continue
        pb = P[name]
        axis = (arm.data.bones[name].matrix_local.to_3x3().inverted() @ side).normalized()
        q_fix = Quaternion(axis, -math.radians(deg * share))   # + = chin down
        frames = sorted({int(k.co.x) for fc in fcs if fc.data_path == f'pose.bones["{name}"].rotation_quaternion' for k in fc.keyframe_points})
        if pb.rotation_mode != "QUATERNION" or not frames:
            continue
        for fr in frames:
            vals = []
            curves = [next(c for c in fcs if c.data_path == f'pose.bones["{name}"].rotation_quaternion' and c.array_index == i)
                      for i in range(4)]
            for fc in curves:
                vals.append(fc.evaluate(fr))
            q = Quaternion(vals) @ q_fix
            for i, fc in enumerate(curves):
                for k in fc.keyframe_points:
                    if int(k.co.x) == fr:
                        k.co.y = q[i]
                        k.handle_left.y = k.handle_right.y = q[i]


def yaw_body(arm: bpy.types.Object, deg: float):
    """Turn the whole baked body about the vertical through the hips, leaving the hips path as it is.
    On the Characters_psx rig the baked body comes out turned ~90 deg from where Kimodo faces while the
    hips path is right (falls 'on his back' would slide sideways if the whole actor were turned instead)."""
    from mathutils import Quaternion
    name = "Hips"
    A = (arm.matrix_world.to_3x3().normalized() @ arm.data.bones[name].matrix_local.to_3x3()).normalized()
    Qc = (A.inverted() @ Matrix.Rotation(math.radians(deg), 3, "Z") @ A).to_quaternion()
    act = arm.animation_data.action if arm.animation_data else None
    fcs = _fcurves(act)
    path = f'pose.bones["{name}"].rotation_quaternion'
    curves = [next(c for c in fcs if c.data_path == path and c.array_index == i) for i in range(4)]
    frames = sorted({int(k.co.x) for c in curves for k in c.keyframe_points})
    new = {}
    for fr in frames:
        q = Quaternion([c.evaluate(fr) for c in curves])
        new[fr] = q @ Qc                      # body-frame turn (the retarget error sits on the bone side)
    for i, c in enumerate(curves):
        for k in c.keyframe_points:
            v = new[int(k.co.x)][i]
            k.co.y = v
            k.handle_left.y = k.handle_right.y = v


def turn_bone(arm: bpy.types.Object, name: str, axis_world, deg: float):
    """Extra rotation of one bone about a fixed rest-pose world axis, on top of baked motion (body-relative).
    E.g. bring the upper arms in toward a wide low-poly torso: turn_bone(arm, 'LeftArm', facing, -8)."""
    from mathutils import Quaternion
    mw3 = arm.matrix_world.to_3x3()
    ax_arm = (mw3.inverted() @ Vector(axis_world)).normalized()
    axis = (arm.data.bones[name].matrix_local.to_3x3().inverted() @ ax_arm).normalized()
    q_fix = Quaternion(axis, math.radians(deg))
    fcs = _fcurves(arm.animation_data.action if arm.animation_data else None)
    path = f'pose.bones["{name}"].rotation_quaternion'
    curves = [next(c for c in fcs if c.data_path == path and c.array_index == i) for i in range(4)]
    frames = sorted({int(k.co.x) for c in curves for k in c.keyframe_points})
    new = {fr: Quaternion([c.evaluate(fr) for c in curves]) @ q_fix for fr in frames}
    for i, c in enumerate(curves):
        for k in c.keyframe_points:
            v = new[int(k.co.x)][i]
            k.co.y = v
            k.handle_left.y = k.handle_right.y = v
