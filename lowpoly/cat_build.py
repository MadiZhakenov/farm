"""Procedural low-poly house cat (PS1/PS2 style) with its own rig, generated tabby fur and a photo face.
  blender -b --factory-startup -P lowpoly/cat_build.py -- OUT.blend [face.png] [fur.png]
Body: Skin modifier over a joint graph (like a game-ready low-poly), decimated to ~1.2k faces.
Rig: quadruped bones on the same joints, automatic weights. Faces -Y, feet on z=0, ~0.75 m nose-to-tail tip.
Fur: generated mackerel-tabby texture (stripes across the body, lighter belly/chest/paws); optional photo fur.
Face: a front photo of a cat face planar-mapped onto the front of the head (swap the image = expression).
"""
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
OUT = Path(args[0])
FACE = args[1] if len(args) > 1 and args[1] != "-" else None
FUR = args[2] if len(args) > 2 and args[2] != "-" else None

bpy.ops.wm.read_factory_settings(use_empty=True)
SC = bpy.context.scene

# ---------------- joint graph (metres; front = -Y) ----------------
DROP = 0.035


def sink(p):
    x, y, z = p
    k = min(1.0, max(0.0, (z - 0.03) / 0.19))
    return (x, y, z - DROP * k)

J = {
    "tail4": ((0, 0.66, 0.36), 0.010), "tail3": ((0, 0.56, 0.33), 0.014), "tail2": ((0, 0.44, 0.29), 0.018),
    "tail1": ((0, 0.31, 0.26), 0.022),
    "pelvis": ((0, 0.21, 0.255), 0.062), "spine": ((0, 0.06, 0.262), 0.074), "chest": ((0, -0.10, 0.262), 0.070),
    "neck": ((0, -0.205, 0.30), 0.046), "head": ((0, -0.275, 0.335), 0.062), "muzzle": ((0, -0.335, 0.318), 0.034),
}
for s, x in (("L", 0.048), ("R", -0.048)):
    J[f"shoulder.{s}"] = ((x, -0.12, 0.215), 0.040)
    J[f"elbow.{s}"] = ((x, -0.125, 0.125), 0.024)
    J[f"wrist.{s}"] = ((x, -0.135, 0.035), 0.019)
    J[f"fpaw.{s}"] = ((x, -0.16, 0.014), 0.020)
    J[f"hip.{s}"] = ((x, 0.18, 0.205), 0.046)
    J[f"knee.{s}"] = ((x, 0.12, 0.125), 0.028)
    J[f"hock.{s}"] = ((x, 0.20, 0.06), 0.018)
    J[f"hpaw.{s}"] = ((x, 0.175, 0.014), 0.020)
EDGES = [("tail4", "tail3"), ("tail3", "tail2"), ("tail2", "tail1"), ("tail1", "pelvis"), ("pelvis", "spine"),
         ("spine", "chest"), ("chest", "neck"), ("neck", "head"), ("head", "muzzle")]
for s in ("L", "R"):
    EDGES += [("chest", f"shoulder.{s}"), (f"shoulder.{s}", f"elbow.{s}"), (f"elbow.{s}", f"wrist.{s}"),
              (f"wrist.{s}", f"fpaw.{s}"), ("pelvis", f"hip.{s}"), (f"hip.{s}", f"knee.{s}"),
              (f"knee.{s}", f"hock.{s}"), (f"hock.{s}", f"hpaw.{s}")]

J = {k: (sink(v[0]), v[1]) for k, v in J.items()}   # rig joints follow the shorter legs

# ---------------- body mesh: metaball blobs blended into one surface, then decimated ----------------
mb = bpy.data.metaballs.new("cat_mb")
import os
_RES = float(os.environ.get("CAT_RES", "0.011"))
mb.resolution = _RES
mb.render_resolution = _RES
mb.threshold = 0.2
mbo = bpy.data.objects.new("cat_mb", mb)
SC.collection.objects.link(mbo)
VIS = 1.37          # influence radius / visible radius for threshold 0.2, stiffness 2


def ball(p, r, sx=1.0, sy=1.0, sz=1.0, kind="ELLIPSOID"):
    """r = visible radius (metres)."""
    e = mb.elements.new(type=kind)
    e.co = sink(tuple(p))
    e.radius = r * VIS
    e.size_x, e.size_y, e.size_z = sx, sy, sz
    e.stiffness = 2.0
    return e


def chain(a, b, r0, r1, n, sx=1.0, sy=1.0, sz=1.0):
    a, b = Vector(a), Vector(b)
    for k in range(n + 1):
        t = k / n
        ball(a.lerp(b, t), r0 + (r1 - r0) * t, sx, sy, sz)


# torso: dense chain rump -> chest (deeper than wide), neck, skull, cheeks, muzzle
chain((0, 0.205, 0.245), (0, 0.06, 0.252), 0.086, 0.098, 5, 0.84, 1.0, 1.0)
chain((0, 0.06, 0.252), (0, -0.095, 0.262), 0.098, 0.088, 5, 0.86, 1.0, 1.0)
chain((0, -0.10, 0.27), (0, -0.21, 0.318), 0.070, 0.056, 4)
ball((0, -0.262, 0.345), 0.075, 1.18, 0.95, 0.90)            # skull
for sx in (1, -1):
    ball((0.036 * sx, -0.300, 0.322), 0.041, 1.0, 0.9, 0.85)  # cheeks
ball((0, -0.330, 0.314), 0.034, 1.0, 0.95, 0.85)             # muzzle
# legs (front: straight, hind: bent hock)
for sx in (1, -1):
    x = 0.050 * sx
    chain((x, -0.10, 0.225), (x, -0.115, 0.12), 0.040, 0.027, 5)
    chain((x, -0.115, 0.12), (x, -0.128, 0.03), 0.026, 0.023, 5)
    ball((x, -0.146, 0.016), 0.023, 1.0, 1.35, 0.7)           # front paw
    chain((x * 1.08, 0.18, 0.225), (x * 1.05, 0.125, 0.125), 0.060, 0.032, 5)
    chain((x * 1.05, 0.125, 0.125), (x, 0.190, 0.062), 0.029, 0.021, 4)
    chain((x, 0.190, 0.062), (x, 0.178, 0.022), 0.020, 0.020, 2)
    ball((x, 0.165, 0.015), 0.023, 1.0, 1.4, 0.7)             # hind paw
# tail
chain((0, 0.27, 0.25), (0, 0.42, 0.285), 0.022, 0.018, 7)
chain((0, 0.42, 0.285), (0, 0.55, 0.33), 0.018, 0.014, 6)
chain((0, 0.55, 0.33), (0, 0.64, 0.37), 0.014, 0.010, 5)
bpy.context.view_layer.update()
bpy.ops.object.select_all(action="DESELECT")
mbo.select_set(True)
bpy.context.view_layer.objects.active = mbo
bpy.ops.object.convert(target="MESH")
body = bpy.context.active_object
body.name = "cat_body"
bpy.context.view_layer.objects.active = body
dec = body.modifiers.new("dec", "DECIMATE")
dec.ratio = float(os.environ.get("CAT_DEC", "0.06"))   # PS1/PS2-ish facet count
bpy.ops.object.modifier_apply(modifier="dec")
bpy.ops.object.shade_smooth()


def add_ear(sx):
    bm = bmesh.new()
    base = Vector(sink((0.052 * sx, -0.268, 0.392)))
    pts = [base + Vector((-0.036 * sx, 0.004, -0.008)), base + Vector((0.030 * sx, 0.012, -0.012)),
           base + Vector((0.000, 0.032, -0.004)), base + Vector((0.008 * sx, 0.006, 0.076))]
    v = [bm.verts.new(p) for p in pts]
    uvl = bm.loops.layers.uv.new("UV_ear")
    tri = {0: (0.12, 0.08), 1: (0.88, 0.08), 3: (0.5, 0.95)}     # front face = pale inner ear, rest = fur rim
    for k, f in enumerate(((0, 1, 3), (1, 2, 3), (2, 0, 3), (0, 2, 1))):
        face = bm.faces.new([v[i] for i in f])
        for lp, i in zip(face.loops, f):
            lp[uvl].uv = tri[i] if k == 0 else (0.03, 0.03)
    m = bpy.data.meshes.new("ear")
    bm.to_mesh(m)
    bm.free()
    o = bpy.data.objects.new("ear", m)
    SC.collection.objects.link(o)
    return o


ears = [add_ear(1), add_ear(-1)]
_ear_mat = bpy.data.materials.new("cat_ear_inner")
_ear_mat.use_nodes = True
_ear_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.56, 0.45, 0.33, 1)
for e in ears:
    e.data.materials.append(_ear_mat)
bpy.ops.object.select_all(action="DESELECT")
for o in ears + [body]:
    o.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()
body.data.name = "cat_body"

# ---------------- materials: generated tabby fur + photo face ----------------
def fur_material():
    m = bpy.data.materials.new("cat_fur")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.95
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    # mackerel stripes run around the body: bands along Y, wobbled by noise
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type = "BANDS"
    wave.bands_direction = "Y"
    wave.inputs["Scale"].default_value = 14.0
    wave.inputs["Distortion"].default_value = 4.0
    wave.inputs["Detail"].default_value = 2.5
    wave.inputs["Detail Scale"].default_value = 1.8
    nt.links.new(tc.outputs["Generated"], wave.inputs["Vector"])
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 60.0
    noise.inputs["Detail"].default_value = 6.0
    nt.links.new(tc.outputs["Generated"], noise.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")          # stripe colours (soft, ref-like grey-brown tabby)
    cr = ramp.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.36, (0.30, 0.22, 0.14, 1)
    cr.elements[1].position, cr.elements[1].color = 0.78, (0.64, 0.52, 0.37, 1)
    nt.links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    dors = nt.nodes.new("ShaderNodeMapRange")          # darker along the spine (top of the body)
    dors.inputs["From Min"].default_value, dors.inputs["From Max"].default_value = 0.42, 0.60
    dors.inputs["To Min"].default_value, dors.inputs["To Max"].default_value = 0.0, 0.45
    nt.links.new(sep.outputs["Z"], dors.inputs["Value"])
    dmix = nt.nodes.new("ShaderNodeMix")
    dmix.data_type = "RGBA"
    nt.links.new(dors.outputs["Result"], dmix.inputs["Factor"])
    nt.links.new(ramp.outputs["Color"], dmix.inputs["A"])
    dmix.inputs["B"].default_value = (0.20, 0.14, 0.08, 1)
    # fine fur grain
    grain = nt.nodes.new("ShaderNodeMix")
    grain.data_type = "RGBA"
    grain.blend_type = "MULTIPLY"
    grain.inputs["Factor"].default_value = 0.28
    nt.links.new(dmix.outputs["Result"], grain.inputs["A"])
    nt.links.new(noise.outputs["Color"], grain.inputs["B"])
    # lighter belly / chest / lower legs: by height (Z) under the body line
    belly = nt.nodes.new("ShaderNodeMapRange")
    belly.inputs["From Min"].default_value, belly.inputs["From Max"].default_value = 0.22, 0.42
    belly.inputs["To Min"].default_value, belly.inputs["To Max"].default_value = 0.85, 0.0
    nt.links.new(sep.outputs["Z"], belly.inputs["Value"])
    light = nt.nodes.new("ShaderNodeMix")
    light.data_type = "RGBA"
    nt.links.new(belly.outputs["Result"], light.inputs["Factor"])
    nt.links.new(grain.outputs["Result"], light.inputs["A"])
    light.inputs["B"].default_value = (0.70, 0.60, 0.46, 1)
    last = light.outputs["Result"]
    if FUR:                                          # optional photo fur (e.g. generated in Flow), mixed in
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(FUR)
        t.projection = "BOX"
        t.projection_blend = 0.3
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (3, 3, 3)
        nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
        mx = nt.nodes.new("ShaderNodeMix")
        mx.data_type = "RGBA"
        mx.blend_type = "OVERLAY"
        mx.inputs["Factor"].default_value = 0.6
        nt.links.new(last, mx.inputs["A"])
        nt.links.new(t.outputs["Color"], mx.inputs["B"])
        last = mx.outputs["Result"]
    nt.links.new(last, b.inputs["Base Color"])
    return m


fur = fur_material()
mats = body.data.materials
ear_idx = next(i for i, m in enumerate(mats) if m and m.name.startswith("cat_ear_inner"))
mats.append(fur)
fur_idx = len(mats) - 1
for p in body.data.polygons:                    # everything that is not ear = fur
    if p.material_index != ear_idx:
        p.material_index = fur_idx


def face_polys():
    """Front of the head (and muzzle) facing -Y: where the photo goes."""
    mw = body.matrix_world
    sel = []
    for p in body.data.polygons:
        c = mw @ p.center
        n = (mw.to_3x3() @ p.normal).normalized()
        if n.y < -0.25 and c.y < -0.235 and c.z > 0.262 - DROP and abs(c.x) < 0.09 and p.material_index != ear_idx:
            sel.append(p)
    return sel


FACE_BOX = (-0.085, 0.085, 0.250 - DROP, 0.44 - DROP)          # x0, x1, z0, z1 of the photo on the head (front view)
PHOTOS = os.environ.get("CAT_PHOTOS")
PHOTO_MODE = bool(PHOTOS and Path(PHOTOS, "side.png").exists())
if FACE and not PHOTO_MODE:
    me = body.data
    uvl = me.uv_layers.new(name="FaceUV")
    x0, x1, z0, z1 = FACE_BOX
    sel = face_polys()
    for p in sel:
        for li in p.loop_indices:
            v = me.vertices[me.loops[li].vertex_index].co
            uvl.data[li].uv = ((v.x - x0) / (x1 - x0), (v.z - z0) / (z1 - z0))
    fm = bpy.data.materials.new("cat_face")
    fm.use_nodes = True
    nt = fm.node_tree
    img = nt.nodes.new("ShaderNodeTexImage")
    img.image = bpy.data.images.load(FACE)
    img.extension = "EXTEND"
    uvn = nt.nodes.new("ShaderNodeUVMap")
    uvn.uv_map = "FaceUV"
    nt.links.new(uvn.outputs["UV"], img.inputs["Vector"])
    nt.links.new(img.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
    nt.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
    me.materials.append(fm)
    fi = len(me.materials) - 1
    for p in sel:
        p.material_index = fi

# ---------------- rig ----------------
BONES = [  # name, head joint, tail joint, parent
    ("root", "spine", "pelvis", None),
    ("pelvis", "pelvis", "tail1", "root"),
    ("spine1", "spine", "chest", "root"),
    ("neck", "chest", "neck", "spine1"),
    ("head", "neck", "head", "neck"),
    ("muzzle", "head", "muzzle", "head"),
    ("tail1", "tail1", "tail2", "pelvis"), ("tail2", "tail2", "tail3", "tail1"), ("tail3", "tail3", "tail4", "tail2"),
]
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
    b.head, b.tail = Vector(J[h][0]), Vector(J[t][0])
    if par:
        b.parent = eb[par]
    eb[name] = b
# ears follow the head
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.parent_set(type="ARMATURE_AUTO")
# make sure ears/face are fully on the head bone (auto weights may split them with the neck)
vg_head = body.vertex_groups.get("head")
for v in body.data.vertices:
    if v.co.z > 0.37 - DROP and v.co.y < -0.22:
        for g in list(v.groups):
            body.vertex_groups[g.group].remove([v.index])
        vg_head.add([v.index], 1.0, "REPLACE")
# ---------------- photo fur: one side photo warped onto the body by landmarks ----------------
# The Flow side photo (head left) is warped with a thin-plate spline: anatomical points of this model
# (nose, withers, belly, elbow, paw, hock, ...) land on the same points of the photo, so stripes,
# lighter belly and legs sit where they belong. The torso is unrolled around the spine (back line ->
# photo back line, belly -> photo belly), the tail follows its own centre line, the head front/sides
# carry the face photo (planar, like the ref), ears get a pale inner-ear texture.
import numpy as np

# (model y, z before sink)  ->  (photo u, v in px of side.png, 512 wide); tuned for the flow1 side photo
LM_SIDE = [
    ((-0.364, 0.314), (4, 74)), ((-0.325, 0.275), (22, 90)), ((-0.21, 0.385), (72, 46)),
    ((-0.10, 0.35), (150, 54)), ((0.06, 0.35), (250, 52)), ((0.20, 0.331), (328, 58)),
    ((0.29, 0.245), (382, 118)), ((0.27, 0.272), (380, 88)), ((0.27, 0.20), (380, 150)), ((0.24, 0.15), (374, 180)),
    ((-0.23, 0.235), (48, 112)), ((-0.18, 0.26), (78, 140)), ((-0.05, 0.16), (190, 178)),
    ((0.06, 0.155), (258, 180)), ((0.15, 0.165), (330, 176)),
    # front leg: front / back edge at elbow and wrist, paw, toe
    ((-0.141, 0.12), (118, 195)), ((-0.089, 0.12), (156, 195)),
    ((-0.151, 0.03), (120, 250)), ((-0.105, 0.03), (147, 250)),
    ((-0.146, 0.0), (126, 270)), ((-0.17, 0.01), (108, 271)),
    # hind leg (near one): thigh, knee edges, hock edges, paw, toe
    ((0.18, 0.225), (368, 162)), ((0.10, 0.125), (356, 205)), ((0.155, 0.125), (390, 205)),
    ((0.17, 0.062), (364, 238)), ((0.21, 0.062), (392, 238)),
    ((0.165, 0.0), (368, 272)), ((0.14, 0.01), (356, 272)),
]
TAIL_MODEL = [(0.27, 0.25), (0.42, 0.285), (0.55, 0.33), (0.64, 0.37), (0.655, 0.375)]
TAIL_PHOTO = [(398, 104), (424, 148), (444, 176), (472, 196), (500, 208)]
SPINE = [(-0.21, 0.318, 0.056), (-0.095, 0.262, 0.088), (0.06, 0.252, 0.098), (0.205, 0.245, 0.086)]  # y, zc, r
SOCK_TOP = 0.072                       # white socks up to this height (after sink)
FACE_NY = -0.32                        # head faces facing forward more than this get the face photo
HEAD_SHIFT = 0.05                      # head sides sample the side photo this far behind (skips the profile eye)
SOCK_RGB = (0.93, 0.90, 0.85, 1)


def _tps_fit(src, dst, lam=1e-8):
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    n = len(src)
    d = np.linalg.norm(src[:, None] - src[None], axis=-1)
    K = np.where(d > 0, d * d * np.log(d + 1e-12), 0.0)
    P = np.hstack([np.ones((n, 1)), src])
    A = np.zeros((n + 3, n + 3))
    A[:n, :n], A[:n, n:], A[n:, :n] = K + lam * np.eye(n), P, P.T
    rhs = np.zeros((n + 3, 2))
    rhs[:n] = dst
    return src, np.linalg.solve(A, rhs)


def _tps(model, pts):
    src, sol = model
    n = len(src)
    pts = np.atleast_2d(np.asarray(pts, float))
    d = np.linalg.norm(pts[:, None] - src[None], axis=-1)
    K = np.where(d > 0, d * d * np.log(d + 1e-12), 0.0)
    return K @ sol[:n] + sol[n] + pts @ sol[n + 1:]


def _polyline_param(pts):
    pts = np.asarray(pts, float)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    return pts, np.concatenate([[0], np.cumsum(seg)]) / seg.sum(), seg.sum()


def _poly_at(pl, t):
    pts, cum, _ = pl
    t = min(max(t, 0.0), 1.0)
    i = min(int(np.searchsorted(cum, t, side="right")) - 1, len(pts) - 2)
    k = (t - cum[i]) / max(1e-9, cum[i + 1] - cum[i])
    p = pts[i] + (pts[i + 1] - pts[i]) * k
    tan = (pts[i + 1] - pts[i]) / max(1e-9, np.linalg.norm(pts[i + 1] - pts[i]))
    return p, tan


def _poly_project(pl, q):
    """closest point on the polyline: (t, signed offset along the left normal)."""
    pts, cum, _ = pl
    best = None
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        ab = b - a
        k = min(max(float(np.dot(q - a, ab) / np.dot(ab, ab)), 0.0), 1.0)
        c = a + ab * k
        dist = np.linalg.norm(q - c)
        if best is None or dist < best[0]:
            tan = ab / np.linalg.norm(ab)
            nrm = np.array([-tan[1], tan[0]])
            best = (dist, cum[i] + (cum[i + 1] - cum[i]) * k, float(np.dot(q - c, nrm)))
    return best[1], best[2]


def _img_mat(name, img, uv_map, extra=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = img
    t.extension = "EXTEND"
    uvn = nt.nodes.new("ShaderNodeUVMap")
    uvn.uv_map = uv_map
    nt.links.new(uvn.outputs["UV"], t.inputs["Vector"])
    out = t.outputs["Color"]
    if extra:
        out = extra(nt, out)
    bsdf = nt.nodes["Principled BSDF"]
    nt.links.new(out, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.95
    return m


def _socks(nt, col):
    """mix pale socks / chest bib from per-vertex attributes (stay put when the rig moves)."""
    out = col
    for name, rgb, gain in (("sock", SOCK_RGB, 1.0), ("bib", (0.90, 0.85, 0.77, 1), 0.55)):
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
    return out


def _ear_image(fur):
    S = 64
    yy, xx = np.mgrid[0:S, 0:S].astype(float) / (S - 1)
    A, B, C = np.array([0.12, 0.08]), np.array([0.88, 0.08]), np.array([0.5, 0.95])
    det = (B[1] - C[1]) * (A[0] - C[0]) + (C[0] - B[0]) * (A[1] - C[1])
    l0 = ((B[1] - C[1]) * (xx - C[0]) + (C[0] - B[0]) * (yy - C[1])) / det
    l1 = ((C[1] - A[1]) * (xx - C[0]) + (A[0] - C[0]) * (yy - C[1])) / det
    l2 = 1 - l0 - l1
    m = np.clip((np.minimum(np.minimum(l0, l1), l2) - 0.05) / 0.22, 0, 1)
    m = m * m * (3 - 2 * m)
    rng = np.random.default_rng(7)
    hair = rng.normal(0, 0.05, (1, S)).repeat(S, 0) + rng.normal(0, 0.03, (S, S))
    inner = np.array([0.93, 0.80, 0.74])
    rgb = fur[None, None, :] * (1 - m[..., None]) + inner[None, None, :] * m[..., None]
    rgb = np.clip(rgb + hair[..., None] * (1 - 0.6 * m[..., None]), 0, 1)
    img = bpy.data.images.new("cat_ear_tex", S, S)
    img.pixels = np.dstack([rgb, np.ones((S, S))]).reshape(-1).tolist()
    img.pack()
    return img


if PHOTO_MODE:
    me = body.data
    side_img = bpy.data.images.load(str(Path(PHOTOS, "side.png")))
    side_img.pack()
    PW, PH = side_img.size
    spx = np.array(side_img.pixels[:]).reshape(PH, PW, 4)[::-1, :, :3]          # top row first
    fur_rgb = spx[int(PH * 0.25):int(PH * 0.5), int(PW * 0.35):int(PW * 0.6)].reshape(-1, 3).mean(0)

    tps = _tps_fit([(y, sink((0, y, z))[2]) for (y, z), _ in LM_SIDE], [uv for _, uv in LM_SIDE])
    tail_m = _polyline_param([(y, sink((0, y, z))[2]) for y, z in TAIL_MODEL])
    tail_p = _polyline_param(TAIL_PHOTO)
    sp_y = [s[0] for s in SPINE]
    sp_t = [sink((0, s[0], s[1] + s[2]))[2] for s in SPINE]
    sp_b = [sink((0, s[0], s[1] - s[2]))[2] for s in SPINE]

    torso_groups = {"root", "pelvis", "spine1", "neck", "head"}
    gname = {g.index: g.name for g in body.vertex_groups}

    def torso_w(v):
        tot = sum(g.weight for g in v.groups) or 1.0
        return sum(g.weight for g in v.groups if gname[g.group] in torso_groups) / tot

    def side_uv(v):
        x, y, z = v.co
        if y > 0.30 and z > 0.17:                                         # tail: along its centre line
            t, off = _poly_project(tail_m, np.array([y, z]))
            p, tan = _poly_at(tail_p, t)
            nrm = np.array([tan[1], -tan[0]])                             # photo 'up' side (v grows down)
            uv = p + nrm * off * (tail_p[2] / tail_m[2])
        else:
            w = torso_w(v)
            zt, zb = np.interp(y, sp_y, sp_t), np.interp(y, sp_y, sp_b)
            zc = 0.5 * (zt + zb)
            phi = math.atan2(abs(x), z - zc)                              # 0 = spine, pi = belly
            z_un = zt - (phi / math.pi) * (zt - zb)
            uv = _tps(tps, [(y, w * z_un + (1 - w) * z)])[0]
        return (float(uv[0]) / PW, 1 - float(uv[1]) / PH)

    # attributes for socks / bib (rest pose, so they ride with the rig)
    rng = np.random.default_rng(3)
    sock = me.attributes.new("sock", "FLOAT", "POINT")
    bib = me.attributes.new("bib", "FLOAT", "POINT")
    for v in me.vertices:
        z = v.co.z + rng.uniform(-0.007, 0.007)
        k = min(1.0, max(0.0, (SOCK_TOP + 0.010 - z) / 0.020))
        sock.data[v.index].value = k * k * (3 - 2 * k)
        nb = v.normal
        kb = 0.0
        if nb.y < -0.35 and -0.27 < v.co.y < -0.10 and 0.10 < v.co.z < 0.27 and abs(v.co.x) < 0.06:
            kb = min(1.0, (-nb.y - 0.35) / 0.4) * min(1.0, (0.27 - v.co.z) / 0.06)
        bib.data[v.index].value = kb

    face_img = bpy.data.images.load(FACE) if FACE else None
    if face_img:
        face_img.pack()
    uv_side = me.uv_layers.new(name="UV_side")
    uv_face = me.uv_layers.new(name="UV_face")
    ear_mi = [i for i, m in enumerate(me.materials) if m and m.name.startswith("cat_ear_inner")]
    side_mat = _img_mat("cat_photo_side", side_img, "UV_side", _socks)
    me.materials.append(side_mat)
    side_mi = len(me.materials) - 1
    face_mi = None
    if face_img:
        me.materials.append(_img_mat("cat_face", face_img, "UV_face"))
        face_mi = len(me.materials) - 1
    ear_mat = _img_mat("cat_ear", _ear_image(fur_rgb), "UV_ear")
    for i in ear_mi:
        me.materials[i] = ear_mat
    x0, x1, z0, z1 = FACE_BOX
    def head_side_uv(v):
        """sides / top of the head: fur from the side photo just behind the eye (no stretched face photo)."""
        uv = _tps(tps, [(v.co.y + HEAD_SHIFT, v.co.z)])[0]
        return (float(uv[0]) / PW, 1 - float(uv[1]) / PH)

    vuv, huv = {}, {}
    nface = 0
    for p in me.polygons:
        if p.material_index in ear_mi:
            continue
        c, n = p.center, p.normal
        is_head = c.y < -0.232 and c.z > 0.215
        front = n.y < FACE_NY or (n.y < 0.02 and abs(n.x) < 0.42 and n.z > 0.45)   # face + forehead, not the sides
        if face_mi is not None and is_head and front:
            for li in p.loop_indices:
                v = me.vertices[me.loops[li].vertex_index].co
                uv_face.data[li].uv = ((v.x - x0) / (x1 - x0), (v.z - z0) / (z1 - z0))
            p.material_index = face_mi
            nface += 1
            continue
        cache, fn = (huv, head_side_uv) if is_head else (vuv, side_uv)
        for li in p.loop_indices:
            vi = me.loops[li].vertex_index
            if vi not in cache:
                cache[vi] = fn(me.vertices[vi])
            uv_side.data[li].uv = cache[vi]
        p.material_index = side_mi
    me.uv_layers.active = uv_side
    print("PHOTO side warp:", len(vuv), "verts; face polys", nface)

print("CAT faces", len(body.data.polygons), "bones", len(ad.bones))
bpy.ops.wm.save_as_mainfile(filepath=str(OUT.resolve()))
print("SAVED", OUT)
