"""Rig one man from the "Retro PSX Male Pack" (jonniemadeit, CC-BY) with a ReadyPlayerMe/Mixamo-named skeleton
so lowpoly/retarget.py:apply_bvh_rpm can drive it with Kimodo motion. Saves a .blend with one armature + mesh.
  blender -b --factory-startup -P lowpoly/psx_rig_man.py -- FACE_IMG BODY_IMG OUT.blend [height_m]
FACE_IMG/BODY_IMG: texture file names as in the pack (e.g. "ManFace 20.png" "BodyTexture (21).png") — the man
wearing that face is taken; BODY_IMG (optional "-") swaps his body texture.
"""
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

FARM = Path(__file__).resolve().parent.parent
PACK = FARM / "downloads/lowpoly_ref/assets/psx/retro_psx_males"
args = sys.argv[sys.argv.index("--") + 1:]
FACE, BODY, OUT = args[0], args[1], args[2]
HEIGHT = float(args[3]) if len(args) > 3 else 1.80

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(PACK / "source/PsxManGroup.fbx"))
for im in bpy.data.images:                                   # textures live in ../textures with "_" for " "
    p = PACK / "textures" / os.path.basename(im.filepath.replace("\\", "/")).replace(" ", "_")
    if p.exists():
        im.filepath = str(p)
        im.reload()


def img_of(o):
    for m in o.data.materials:
        if m and m.node_tree:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image:
                    return n
    return None


def centre(o):
    return sum((o.matrix_world @ Vector(v) for v in o.bound_box), Vector()) / 8


faces = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("Face")]
bodies = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("Body")]
face = next(o for o in faces if img_of(o) and img_of(o).image.name.replace("_", " ") == FACE.replace("_", " "))
body = min(bodies, key=lambda b: (centre(b) - centre(face)).xy.length)
if BODY != "-":
    p = PACK / "textures" / BODY.replace(" ", "_")
    img_of(body).image = bpy.data.images.load(str(p))
for o in list(bpy.data.objects):
    if o not in (face, body):
        bpy.data.objects.remove(o, do_unlink=True)
for n in (img_of(face), img_of(body)):                       # PS1 look: no texture filtering
    n.interpolation = "Closest"

# one mesh, centred, facing -Y, feet on the floor, HEIGHT tall
bpy.ops.object.select_all(action="DESELECT")
for o in (face, body):
    o.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()
man = body
man.name = "psx_man"
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
me = man.data
vs = [v.co.copy() for v in me.vertices]
lo = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
hi = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
c = (lo + hi) / 2
# the face sits at the man's front: find which horizontal side the face verts lean to
face_pts = [v for v in vs if v.z > lo.z + 0.88 * (hi.z - lo.z)]
fc = sum(face_pts, Vector()) / len(face_pts)
k = HEIGHT / (hi.z - lo.z)
man.location = (-c.x, -c.y, -lo.z)
bpy.ops.object.transform_apply(location=True)
man.scale = (k, k, k)
bpy.ops.object.transform_apply(scale=True)
# rotate so the nose points to -Y (pack men look along -X)
ang = math.atan2(-(fc.y - c.y), -(fc.x - c.x))       # angle of facing vector
man.rotation_euler.z = -math.pi / 2 - ang
bpy.ops.object.transform_apply(rotation=True)

vs = [v.co.copy() for v in man.data.vertices]
H = max(v.z for v in vs)


def band(z0, z1, side=0):
    pts = [v for v in vs if z0 * H <= v.z <= z1 * H and (side == 0 or v.x * side > 0)]
    return pts


def mean(pts):
    return sum(pts, Vector()) / max(1, len(pts))


# landmarks from the mesh
legL = mean(band(0.20, 0.35, +1))
yc = mean(band(0.45, 0.75)).y
sh_z = 0.815 * H
arm_pts = [v for v in vs if v.x > 0.12 * H and v.z < sh_z]
tip = min(arm_pts, key=lambda v: v.z) if arm_pts else Vector((0.25 * H, yc, 0.45 * H))
shoulder = Vector((0.115 * H, yc, 0.80 * H))
arm_vec = tip - shoulder

J = {
    "Hips": Vector((0, yc, 0.53 * H)), "Spine": Vector((0, yc, 0.585 * H)), "Spine1": Vector((0, yc, 0.65 * H)),
    "Spine2": Vector((0, yc, 0.72 * H)), "Neck": Vector((0, yc, 0.835 * H)), "Head": Vector((0, yc, 0.875 * H)),
    "HeadTop_End": Vector((0, yc, 1.0 * H)),
}
for s, sx in (("Left", 1), ("Right", -1)):
    m = Vector((sx, 1, 1))
    J[f"{s}Shoulder"] = Vector((0.035 * H * sx, yc, 0.81 * H))
    J[f"{s}Arm"] = Vector((shoulder.x * sx, shoulder.y, shoulder.z))
    J[f"{s}ForeArm"] = (shoulder + arm_vec * 0.46) * 1 if sx > 0 else Vector((-(shoulder + arm_vec * 0.46).x, (shoulder + arm_vec * 0.46).y, (shoulder + arm_vec * 0.46).z))
    w = shoulder + arm_vec * 0.80
    J[f"{s}Hand"] = Vector((w.x * sx, w.y, w.z))
    mid = shoulder + arm_vec * 0.92
    J[f"{s}HandMiddle1"] = Vector((mid.x * sx, mid.y, mid.z))
    J[f"{s}HandMiddle_End"] = Vector((tip.x * sx, tip.y, tip.z))
    lx = abs(legL.x) * sx
    J[f"{s}UpLeg"] = Vector((lx, yc, 0.50 * H))
    J[f"{s}Leg"] = Vector((lx, yc, 0.275 * H))
    J[f"{s}Foot"] = Vector((lx, yc + 0.01 * H, 0.045 * H))
    J[f"{s}ToeBase"] = Vector((lx, yc - 0.06 * H, 0.012 * H))
    J[f"{s}Toe_End"] = Vector((lx, yc - 0.11 * H, 0.012 * H))

PARENT = {"Spine": "Hips", "Spine1": "Spine", "Spine2": "Spine1", "Neck": "Spine2", "Head": "Neck", "HeadTop_End": "Head"}
CHILD = {"Hips": "Spine", "Spine": "Spine1", "Spine1": "Spine2", "Spine2": "Neck", "Neck": "Head", "Head": "HeadTop_End"}
for s in ("Left", "Right"):
    PARENT.update({f"{s}Shoulder": "Spine2", f"{s}Arm": f"{s}Shoulder", f"{s}ForeArm": f"{s}Arm", f"{s}Hand": f"{s}ForeArm",
                   f"{s}HandMiddle1": f"{s}Hand", f"{s}HandMiddle_End": f"{s}HandMiddle1",
                   f"{s}UpLeg": "Hips", f"{s}Leg": f"{s}UpLeg", f"{s}Foot": f"{s}Leg", f"{s}ToeBase": f"{s}Foot",
                   f"{s}Toe_End": f"{s}ToeBase"})
    CHILD.update({f"{s}Shoulder": f"{s}Arm", f"{s}Arm": f"{s}ForeArm", f"{s}ForeArm": f"{s}Hand", f"{s}Hand": f"{s}HandMiddle1",
                  f"{s}HandMiddle1": f"{s}HandMiddle_End", f"{s}UpLeg": f"{s}Leg", f"{s}Leg": f"{s}Foot",
                  f"{s}Foot": f"{s}ToeBase", f"{s}ToeBase": f"{s}Toe_End"})

ad = bpy.data.armatures.new("Armature")
arm = bpy.data.objects.new("Armature", ad)
bpy.context.scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
eb = {}
for name, head in J.items():
    b = ad.edit_bones.new(name)
    b.head = head
    ch = CHILD.get(name)
    if ch:
        b.tail = J[ch]
    else:                                                     # end bones: short stub along the parent direction
        par = PARENT.get(name)
        d = (head - J[par]).normalized() if par else Vector((0, 0, 1))
        b.tail = head + d * 0.03 * H
    if (b.tail - b.head).length < 1e-4:
        b.tail = b.head + Vector((0, 0, 0.02 * H))
    eb[name] = b
for name, par in PARENT.items():
    eb[name].parent = eb[par]
bpy.ops.object.mode_set(mode="OBJECT")

# skin with automatic weights
bpy.ops.object.select_all(action="DESELECT")
man.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.parent_set(type="ARMATURE_AUTO")
ok = any(len(v.groups) for v in man.data.vertices)
print("WEIGHTS", ok, "groups", len(man.vertex_groups), "H", round(H, 3), "tip", tuple(round(v, 3) for v in tip))
bpy.ops.wm.save_as_mainfile(filepath=str(Path(OUT).resolve()))
print("SAVED", OUT)
