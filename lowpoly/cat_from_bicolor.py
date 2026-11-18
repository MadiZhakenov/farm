"""Low-poly PS1 cat built from the Bicolor Cat mesh (Sketchfab, kenchoo, CC-BY 4.0: credit the author).
  blender -b --factory-startup -P lowpoly/cat_from_bicolor.py -- OUT.blend ATLAS.(png|jpg) [face.png]
- tail is posed up (ref cat walks with the tail up) and baked into the mesh,
- the Wolf rig is dropped; our 21-bone quadruped rig (same bone names/axes as cat_build.py) is placed on
  the Bicolor joints, so lowpoly/cat_anim.py motions work unchanged,
- decimated to a PS1/PS2 facet count, re-textured with an atlas in Bicolor's UV layout (e.g. Flow-edited),
- white socks / light chest from per-vertex attributes, optional photo face on the head front.
Output objects: cat_rig (armature), cat_body (mesh). Faces -Y, paws on z=0.
"""
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Vector

FARM = Path(__file__).resolve().parent.parent
SRC = FARM / "downloads/lowpoly_ref/assets/skf/bicolor/source/bicolor Cat.glb"
args = sys.argv[sys.argv.index("--") + 1:]
OUT = Path(args[0])
ATLAS = args[1]
FACE = args[2] if len(args) > 2 and args[2] != "-" else None
SCALE = float(os.environ.get("CAT_SCALE", "1.2"))         # Bicolor is ~0.5 m nose-to-rump; scenes were laid out for ~0.6
TARGET_FACES = int(os.environ.get("CAT_FACES", "1800"))
TAIL_UP = [float(x) for x in os.environ.get("CAT_TAIL_UP", "0,45,35,15").split(",")]  # deg per tail bone
SOCK_TOP = 0.060 * SCALE
KEEP_EYES = os.environ.get("CAT_EYES", "1") == "1"
EYE_SCALE = float(os.environ.get("CAT_EYE_SCALE", "1.08"))
EYE_FWD = float(os.environ.get("CAT_EYE_FWD", "0.0"))
LID_RAISE = float(os.environ.get("CAT_LID_RAISE", "0.005"))   # m (before SCALE): opens the eyes, no grumpy look
LID_LOWER = float(os.environ.get("CAT_LID_LOWER", "0.0015"))
ATLAS_RES = int(os.environ.get("CAT_ATLAS_RES", "512"))
HEAD_SCALE = float(os.environ.get("CAT_HEAD_SCALE", "1.12"))   # ref cat has a bigger head
CREAM_TO_SAND = float(os.environ.get("CAT_CREAM_TO_SAND", "1.0"))
WIDEN = float(os.environ.get("CAT_WIDEN", "1.12"))     # chunkier body / thicker legs, like the ref cat
TINT = [float(x) for x in os.environ.get("CAT_TINT", "0.90,0.80,0.68").split(",")]  # warmer, darker than the pale atlas

bpy.ops.wm.read_factory_settings(use_empty=True)
SC = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=str(SRC))
wolf = next(o for o in SC.objects if o.type == "ARMATURE")
body = next(o for o in SC.objects if o.type == "MESH" and o.name.startswith("Ginger"))
for o in list(SC.objects):
    if o.type == "MESH" and o is not body:
        bpy.data.objects.remove(o, do_unlink=True)

# ---- pose the tail up with the original rig, bake the pose into the mesh ----
if wolf.animation_data:
    wolf.animation_data.action = None
wolf.data.pose_position = "POSE"
for pb in wolf.pose.bones:
    pb.rotation_mode = "XYZ"
    pb.rotation_euler = (0, 0, 0)
    pb.location = (0, 0, 0)
    pb.scale = (1, 1, 1)
for i, ang in enumerate(TAIL_UP):
    pb = wolf.pose.bones.get(f"Wolf_Tail_01_0{i + 2}SHJnt")
    if pb:
        pb.rotation_euler.z = math.radians(ang)      # bone-local axis that lifts this rig's tail (checked in preview)
bpy.context.view_layer.update()


def bone_world(name, end="head"):
    pb = wolf.pose.bones[name]
    return wolf.matrix_world @ (pb.head if end == "head" else pb.tail)


JW = {   # our joint -> Bicolor joint (posed, world)
    "pelvis": bone_world("Wolf_ROOTSHJnt"), "spine": bone_world("Wolf_Spine_02SHJnt"),
    "chest": bone_world("Wolf_Neck_01SHJnt") * 0.5 + bone_world("Wolf_Spine_TopSHJnt") * 0.5,
    "neck": bone_world("Wolf_Neck_TopSHJnt"),
    "tail1": bone_world("Wolf_Tail_01_02SHJnt"), "tail2": bone_world("Wolf_Tail_01_03SHJnt"),
    "tail3": bone_world("Wolf_Tail_01_04SHJnt"), "tail4": bone_world("Wolf_Tail_01_05SHJnt"),
}
for s, w in (("L", "l"), ("R", "r")):
    JW[f"shoulder.{s}"] = bone_world(f"Wolf_{w}_FrontLeg_HipSHJnt")
    JW[f"elbow.{s}"] = bone_world(f"Wolf_{w}_FrontLeg_KneeSHJnt")
    JW[f"wrist.{s}"] = bone_world(f"Wolf_{w}_FrontLeg_AnkleSHJnt")
    JW[f"fpaw.{s}"] = bone_world(f"Wolf_{w}_FrontLeg_BallSHJnt").lerp(bone_world(f"Wolf_{w}_FrontLeg_ToeSHJnt"), 0.5)
    JW[f"hip.{s}"] = bone_world(f"Wolf_{w}_HindLeg_HipSHJnt")
    JW[f"knee.{s}"] = bone_world(f"Wolf_{w}_HindLeg_Knee1SHJnt")
    JW[f"hock.{s}"] = bone_world(f"Wolf_{w}_HindLeg_Knee2SHJnt")
    JW[f"hpaw.{s}"] = bone_world(f"Wolf_{w}_HindLeg_BallSHJnt").lerp(bone_world(f"Wolf_{w}_HindLeg_ToeSHJnt"), 0.5)

bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
bpy.context.view_layer.objects.active = body
dg = bpy.context.evaluated_depsgraph_get()
posed = bpy.data.meshes.new_from_object(body.evaluated_get(dg))     # tail pose + shape-key mix baked in
body.modifiers.clear()
body.shape_key_clear()
body.data = posed
mw = body.matrix_world.copy()
body.parent = None
body.matrix_world = mw
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
body.vertex_groups.clear()
bpy.data.objects.remove(wolf, do_unlink=True)

# tail tip / nose from the mesh itself
vs = [v.co for v in body.data.vertices]
JW["tail4"] = max(vs, key=lambda c: c.z + 0.3 * c.y)       # tail tip (tail is posed up)
nose = min(vs, key=lambda c: c.y)
JW["muzzle"] = Vector((0, nose.y + 0.012, nose.z))
JW["head"] = JW["neck"].lerp(JW["muzzle"], 0.45)
for k in JW:
    JW[k] = JW[k] * SCALE
    if not k.startswith(("shoulder", "elbow", "wrist", "fpaw", "hip", "knee", "hock", "hpaw")):
        JW[k].x = 0.0
for v in body.data.vertices:
    v.co *= SCALE
    v.co.x *= WIDEN
for k in JW:
    JW[k].x *= WIDEN

# eyes: Bicolor has separate eyeball geometry ('eye' material)
mats = body.data.materials
eye_idx = next((i for i, m in enumerate(mats) if m and m.name == "eye"), None)
if not KEEP_EYES and eye_idx is not None:
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index == eye_idx], context="FACES")
    bm.to_mesh(body.data)
    bm.free()

# bigger head (smooth falloff into the neck so there is no seam)
if HEAD_SCALE != 1.0:
    nk = JW["neck"]
    hc = JW["neck"].lerp(JW["muzzle"], 0.35)
    for v in body.data.vertices:
        t = min(1.0, max(0.0, (nk.y + 0.02 * SCALE - v.co.y) / (0.05 * SCALE)))
        t *= min(1.0, max(0.0, (v.co.z - (nk.z - 0.09 * SCALE)) / (0.04 * SCALE)))
        k = 1.0 + (HEAD_SCALE - 1.0) * t * t * (3 - 2 * t)
        v.co = hc + (v.co - hc) * k
    JW["muzzle"] = hc + (JW["muzzle"] - hc) * HEAD_SCALE
    JW["head"] = hc + (JW["head"] - hc) * HEAD_SCALE

# glTF splits vertices along UV seams: weld them (UVs live per loop, so the atlas layout is kept),
# otherwise skinning and decimation tear the body open along every seam
import bmesh
bm = bmesh.new()
bm.from_mesh(body.data)
n_before = len(bm.verts)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0006 * SCALE)
bm.to_mesh(body.data)
bm.free()
print("welded seams", n_before, "->", len(body.data.vertices))

# the source mesh has stray 'eye' faces collapsed to a point under the belly: drop them
if eye_idx is not None:
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(body.data)
    junk = [f for f in bm.faces if f.material_index == eye_idx and f.calc_center_median().z < 0.2 * SCALE]
    bmesh.ops.delete(bm, geom=junk, context="FACES")
    bm.to_mesh(body.data)
    bm.free()
    print("dropped stray eye faces", len(junk))

# bigger, slightly bulging eyeballs: wide 'staring' look of the ref cat
if KEEP_EYES and eye_idx is not None:
    ev = {vi for p in body.data.polygons if p.material_index == eye_idx for vi in p.vertices}
    for side in (1, -1):
        vv = [body.data.vertices[i] for i in ev if body.data.vertices[i].co.x * side > 0]
        if not vv:
            continue
        c = sum((v.co for v in vv), Vector()) / len(vv)
        R = max((v.co - c).length for v in vv)
        for v in vv:
            v.co = c + (v.co - c) * EYE_SCALE + Vector((0, -EYE_FWD, 0))
        # open the eye: lift the upper lid / drop the lower lid of the head mesh around this eyeball
        for v in body.data.vertices:
            if v.index in ev or v.co.x * side <= 0 or v.co.y > c.y + 0.6 * R:
                continue
            d = math.hypot(v.co.x - c.x, v.co.z - c.z)
            if d > 1.9 * R:
                continue
            f = 1.0 if d < 1.0 * R else (1.9 * R - d) / (0.9 * R)
            f = f * f * (3 - 2 * f)
            if v.co.z > c.z + 0.15 * R:
                v.co.z += LID_RAISE * SCALE * f
            elif v.co.z < c.z - 0.25 * R:
                v.co.z -= LID_LOWER * SCALE * f

# ---- decimate to the PS1 facet count (eyeballs kept intact: their UVs break when collapsed) ----
n0 = len(body.data.polygons)
vg = body.vertex_groups.new(name="decimate")
eye_verts = {vi for p in body.data.polygons if p.material_index == eye_idx for vi in p.vertices} if eye_idx is not None else set()
vg.add([v.index for v in body.data.vertices if v.index not in eye_verts], 1.0, "REPLACE")
dec = body.modifiers.new("dec", "DECIMATE")
dec.ratio = min(1.0, TARGET_FACES / max(1, n0))
dec.vertex_group = "decimate"
bpy.ops.object.modifier_apply(modifier="dec")
bpy.ops.object.shade_smooth()
body.vertex_groups.remove(body.vertex_groups["decimate"])
print("EYE faces after decimate", sum(1 for p in body.data.polygons if p.material_index == eye_idx))
body.name = "cat_body"
body.data.name = "cat_body"

# ---- material: atlas + socks/bib attributes ----
img = bpy.data.images.load(str(Path(ATLAS).resolve()))
img.name = "cat_atlas_fur"
if ATLAS_RES and img.size[0] > ATLAS_RES:
    img.scale(ATLAS_RES, ATLAS_RES)                      # low-res photo fur = the soft PS2 look
img.pack()
eye_img = bpy.data.images.load(str(Path(ATLAS).resolve()), check_existing=False)
eye_img.name = "cat_atlas_eyes"
eye_img.pack()
fur = bpy.data.materials.new("cat_fur_atlas")
fur.use_nodes = True
nt = fur.node_tree
tex = nt.nodes.new("ShaderNodeTexImage")
tex.image = img
uvn = nt.nodes.new("ShaderNodeUVMap")
uvn.uv_map = body.data.uv_layers[0].name
nt.links.new(uvn.outputs["UV"], tex.inputs["Vector"])
tint = nt.nodes.new("ShaderNodeMix")
tint.data_type = "RGBA"
tint.blend_type = "MULTIPLY"
tint.inputs["Factor"].default_value = 1.0
nt.links.new(tex.outputs["Color"], tint.inputs["A"])
tint.inputs["B"].default_value = (*TINT, 1)
out = tint.outputs["Result"]
# former white areas of the bicolor (chest, legs, belly) read too pale: pull bright cream toward sand
lum = nt.nodes.new("ShaderNodeRGBToBW")
nt.links.new(tex.outputs["Color"], lum.inputs["Color"])
mr = nt.nodes.new("ShaderNodeMapRange")
mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = 0.50, 0.72
mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = 0.0, CREAM_TO_SAND
mr.interpolation_type = "SMOOTHSTEP"
nt.links.new(lum.outputs["Val"], mr.inputs["Value"])
sand = nt.nodes.new("ShaderNodeMix")
sand.data_type = "RGBA"
sand.blend_type = "MULTIPLY"
nt.links.new(mr.outputs["Result"], sand.inputs["Factor"])
nt.links.new(out, sand.inputs["A"])
sand.inputs["B"].default_value = (0.80, 0.66, 0.50, 1)
out = sand.outputs["Result"]
for name, rgb, gain in (("sock", (0.94, 0.92, 0.88, 1), 1.0), ("bib", (0.92, 0.88, 0.80, 1), 0.45)):
    at = nt.nodes.new("ShaderNodeAttribute")
    at.attribute_name = name
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = gain
    nt.links.new(at.outputs["Fac"], mul.inputs[0])
    mx = nt.nodes.new("ShaderNodeMix")
    mx.data_type = "RGBA"
    nt.links.new(mul.outputs["Value"], mx.inputs["Factor"])
    nt.links.new(out, mx.inputs["A"])
    mx.inputs["B"].default_value = rgb
    out = mx.outputs["Result"]
bsdf = nt.nodes["Principled BSDF"]
nt.links.new(out, bsdf.inputs["Base Color"])
bsdf.inputs["Roughness"].default_value = 0.95
eye_mat = bpy.data.materials.new("cat_eye")
eye_mat.use_nodes = True
et = eye_mat.node_tree
etex = et.nodes.new("ShaderNodeTexImage")
etex.image = eye_img
euv = et.nodes.new("ShaderNodeUVMap")
euv.uv_map = body.data.uv_layers[0].name
et.links.new(euv.outputs["UV"], etex.inputs["Vector"])
et.links.new(etex.outputs["Color"], et.nodes["Principled BSDF"].inputs["Base Color"])
et.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.25
for i, m in enumerate(mats):
    if m and m.name != "eye":
        mats[i] = fur
    elif m:
        mats[i] = eye_mat

import random
rnd = random.Random(3)
sock = body.data.attributes.new("sock", "FLOAT", "POINT")
bib = body.data.attributes.new("bib", "FLOAT", "POINT")
chest = JW["chest"]
for v in body.data.vertices:
    z = v.co.z + rnd.uniform(-0.006, 0.006) * SCALE
    k = min(1.0, max(0.0, (SOCK_TOP + 0.008 * SCALE - z) / (0.016 * SCALE)))
    sock.data[v.index].value = k * k * (3 - 2 * k)
    n = v.normal
    kb = 0.0
    if n.y < -0.3 and v.co.y < chest.y + 0.05 * SCALE and v.co.z < chest.z + 0.02 * SCALE and v.co.z > 0.09 * SCALE:
        kb = min(1.0, (-n.y - 0.3) / 0.4)
    bib.data[v.index].value = kb

# ---- our rig on the Bicolor joints ----
BONES = [("root", "spine", "pelvis", None), ("pelvis", "pelvis", "tail1", "root"), ("spine1", "spine", "chest", "root"),
         ("neck", "chest", "neck", "spine1"), ("head", "neck", "head", "neck"), ("muzzle", "head", "muzzle", "head"),
         ("tail1", "tail1", "tail2", "pelvis"), ("tail2", "tail2", "tail3", "tail1"), ("tail3", "tail3", "tail4", "tail2")]
for s in ("L", "R"):
    BONES += [(f"upperarm.{s}", f"shoulder.{s}", f"elbow.{s}", "spine1"),
              (f"forearm.{s}", f"elbow.{s}", f"wrist.{s}", f"upperarm.{s}"),
              (f"fpaw.{s}", f"wrist.{s}", f"fpaw.{s}", f"forearm.{s}"),
              (f"thigh.{s}", f"hip.{s}", f"knee.{s}", "pelvis"),
              (f"shin.{s}", f"knee.{s}", f"hock.{s}", f"thigh.{s}"),
              (f"hpaw.{s}", f"hock.{s}", f"hpaw.{s}", f"shin.{s}")]
ad = bpy.data.armatures.new("cat_rig")
arm = bpy.data.objects.new("cat_rig", ad)
SC.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
eb = {}
for name, h, t, par in BONES:
    b = ad.edit_bones.new(name)
    b.head, b.tail = JW[h].copy(), JW[t].copy()
    if (b.tail - b.head).length < 0.005:
        b.tail = b.head + Vector((0, 0, 0.02))
    if par:
        b.parent = eb[par]
    eb[name] = b
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.parent_set(type="ARMATURE_AUTO")
# whole skull (incl. ears, eyes) rigid on the head bone
vg_head = body.vertex_groups.get("head")
nk = JW["neck"]
for v in body.data.vertices:
    if v.co.y < nk.y - 0.005 * SCALE and v.co.z > nk.z - 0.045 * SCALE:
        for g in list(v.groups):
            body.vertex_groups[g.group].remove([v.index])
        vg_head.add([v.index], 1.0, "REPLACE")

print("CAT faces", len(body.data.polygons), "from", n0, "bones", len(ad.bones))
for k in ("muzzle", "head", "neck", "chest", "pelvis", "tail4", "fpaw.L", "hpaw.L"):
    print("  J", k, tuple(round(x, 3) for x in JW[k]))
bpy.ops.wm.save_as_mainfile(filepath=str(OUT.resolve()))
print("SAVED", OUT)
