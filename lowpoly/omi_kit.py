"""Shared pieces for Mr-omi-style low-poly shorts (Blender 5, headless).
People: Characters_psx pack (Elbolillo, CC-BY) + Kimodo BVH clips, with the retarget fixes measured on this rig:
  - reset the FBX clip pose to rest after import,
  - the pack's rest faces +X: turn the Kimodo clip by +90 before baking, then the actor by -90 to face -Y,
  - head ~14 deg chin-up on this rig -> nod 14; arms 9 deg in toward the wide torso.
Faces: optional flat face photo swapped per frame range (Mr omi: 'swap the picture and the face changes').
Collision check: actors' bone positions are sampled per frame; overlaps are reported (Kimodo knows no neighbours).
"""
import importlib.util
import math
import os
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

FARM = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("retarget", FARM / "lowpoly/retarget.py")
RT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RT)
RT.RPM_REST_FIX = {"Neck": 0.0, "Head": 0.0}
CHARS = FARM / "downloads/lowpoly_ref/assets/psx/characters_psx/source/Characters_psx/Characters_psx"
MALE, FEMALE = CHARS / "Models/Male", CHARS / "Models/Female"
ACTORS = []                        # (name, armature) for the overlap check


def reset(fps=30, frames=60):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.fps = fps
    sc.frame_start, sc.frame_end = 1, frames
    ACTORS.clear()
    return sc


# ---------------- materials / simple geometry ----------------
def img_from_array(name, arr):
    h, w, _ = arr.shape
    im = bpy.data.images.new(name, w, h)
    rgba = np.concatenate([arr[::-1], np.ones((h, w, 1))], axis=2)
    im.pixels = rgba.reshape(-1).tolist()
    im.pack()
    return im


def noise_tex(name, base, amp=0.04, size=128, cell=2, seed=0, streaks=False):
    rng = np.random.default_rng(seed)
    n = rng.normal(0, amp, (size // cell, size // cell)).repeat(cell, 0).repeat(cell, 1)
    if streaks:                                           # brushed steel: horizontal streaks
        n = n * 0.4 + rng.normal(0, amp, (size, 1)).repeat(size, 1)
    col = np.clip(np.array(base)[None, None, :] * (1 + n[..., None]), 0, 1)
    return img_from_array(name, col)


def mat_img(name, img, closest=False, rough=0.9, emit=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = img
    if closest:
        t.interpolation = "Closest"
    b = nt.nodes["Principled BSDF"]
    nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    if emit:
        nt.links.new(t.outputs["Color"], b.inputs["Emission Color"])
        b.inputs["Emission Strength"].default_value = emit
    return m


def mat_col(name, rgb, rough=0.8, emit=0.0, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*rgb, 1)
        b.inputs["Emission Strength"].default_value = emit
    return m


def box(name, size, loc, mat, uv_scale=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if uv_scale:                                          # world-size UVs so textures don't stretch
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.cube_project(cube_size=uv_scale)
        bpy.ops.object.mode_set(mode="OBJECT")
    o.data.materials.append(mat)
    return o


def cyl(name, r, p0, p1, mat, verts=8):
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=d.length, location=(p0 + p1) / 2)
    o = bpy.context.active_object
    o.name = name
    o.rotation_mode = "QUATERNION"
    o.rotation_quaternion = d.to_track_quat("Z", "Y")
    o.data.materials.append(mat)
    return o


def plane_uv(name, verts, uvs, mat):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new()
    for i, l in enumerate(me.loops):
        uv.data[i].uv = uvs[l.vertex_index]
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def world(rgb=(0.75, 0.75, 0.78), strength=0.6):
    sc = bpy.context.scene
    w = bpy.data.worlds.new("w")
    sc.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (*rgb, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = strength


def light(kind, loc, energy, rot=(0, 0, 0), size=1.0, color=(1, 1, 1)):
    ld = bpy.data.lights.new(kind.lower(), kind)
    ld.energy = energy
    ld.color = color
    if kind == "AREA":
        ld.size = size
    o = bpy.data.objects.new(ld.name, ld)
    o.location = loc
    o.rotation_euler = tuple(math.radians(a) for a in rot)
    bpy.context.scene.collection.objects.link(o)
    return o


def camera(loc, look_at, lens=30):
    sc = bpy.context.scene
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.lens = lens
    cam.location = loc
    cam.rotation_euler = (Vector(look_at) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return cam


def key_cam(cam, f, loc, look_at, lens=None):
    cam.location = loc
    cam.rotation_euler = (Vector(look_at) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    cam.keyframe_insert("location", frame=f)
    cam.keyframe_insert("rotation_euler", frame=f)
    if lens:
        cam.data.lens = lens
        cam.data.keyframe_insert("lens", frame=f)


def text_obj(txt, loc, size, rgb, rot=(90, 0, 0), emit=2.0):
    cu = bpy.data.curves.new("txt", "FONT")
    cu.body = txt
    cu.align_x, cu.align_y = "CENTER", "CENTER"
    cu.size = size
    cu.extrude = size * 0.08
    o = bpy.data.objects.new("txt", cu)
    o.location = loc
    o.rotation_euler = tuple(math.radians(a) for a in rot)
    o.data.materials.append(mat_col("txt_" + txt, rgb, emit=emit))
    bpy.context.scene.collection.objects.link(o)
    return o


# ---------------- people ----------------
def person(fbx, bvh, loc, rot_deg=0.0, height=1.78, hold_root=True, frames=None, tex=None, start=1,
           nod=14.0, arm_in=9.0, name=None):
    """Characters_psx actor driven by a Kimodo BVH. rot_deg 0 = facing -Y (toward a camera at -Y)."""
    sc = bpy.context.scene
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(fbx))
    new = [o for o in bpy.data.objects if o not in before]
    for im in bpy.data.images:
        if im.filepath and not os.path.exists(bpy.path.abspath(im.filepath)):
            p = CHARS / "Textures" / os.path.basename(im.filepath.replace("\\", "/"))
            if p.exists():
                im.filepath = str(p)
                im.reload()
    meshes = [o for o in new if o.type == "MESH"]
    if tex:
        img = bpy.data.images.load(str(tex), check_existing=True)
        for o in meshes:
            for m in o.data.materials:
                for n in m.node_tree.nodes:
                    if n.type == "TEX_IMAGE":
                        n.image = img
    arm = next(o for o in new if o.type == "ARMATURE")
    if arm.animation_data:
        arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
    for b in arm.data.bones:
        if b.name.startswith("mixamorig:"):
            b.name = b.name[len("mixamorig:"):]
    bpy.context.view_layer.update()
    zs = [(o.matrix_world @ v.co).z for o in meshes for v in o.data.vertices]
    k = height / (max(zs) - min(zs))
    roots = [o for o in new if o.parent is None]
    for r in roots:
        r.scale = r.scale * k
    bpy.context.view_layer.update()
    RT.apply_bvh_rpm(arm, str(bvh), sc, start, frames=frames, hold_root=hold_root, src_yaw_deg=90)
    if nod:
        RT.nod_head(arm, nod, facing=(1, 0, 0))
    if arm_in:
        RT.turn_bone(arm, "LeftArm", (1, 0, 0), -arm_in)
        RT.turn_bone(arm, "RightArm", (1, 0, 0), arm_in)
    for r in roots:
        r.rotation_mode = "XYZ"
        r.rotation_euler.z += math.radians(-90 + rot_deg)
    sc.frame_set(start)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    feet = min((o.matrix_world @ v.co).z for o in meshes for v in o.evaluated_get(dg).to_mesh().vertices)
    hips = arm.matrix_world @ arm.pose.bones["Hips"].head
    for r in roots:
        r.location += Vector((loc[0] - hips.x, loc[1] - hips.y, (loc[2] if len(loc) > 2 else 0) - feet))
    for o in meshes:
        for m in o.data.materials:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE":
                    n.interpolation = "Closest"
    ACTORS.append((name or Path(str(fbx)).stem, arm))
    return arm, roots, meshes


def check_overlaps(f0, f1, min_dist=0.22, step=3):
    """Report frames where two actors' torsos/heads come closer than min_dist (they would pass through)."""
    sc = bpy.context.scene
    bones = ("Hips", "Spine1", "Spine2", "Head")
    bad = []
    for f in range(f0, f1 + 1, step):
        sc.frame_set(f)
        pts = [(n, [a.matrix_world @ a.pose.bones[b].head for b in bones if b in a.pose.bones]) for n, a in ACTORS]
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                d = min((p - q).length for p in pts[i][1] for q in pts[j][1])
                if d < min_dist:
                    bad.append((f, pts[i][0], pts[j][0], round(d, 2)))
    if bad:
        print("OVERLAP", bad[:12], "..." if len(bad) > 12 else "")
    else:
        print("OVERLAP none")
    return bad


def render_setup(res_pct=40):
    sc = bpy.context.scene
    r = sc.render
    r.engine = "BLENDER_EEVEE"
    sc.view_settings.view_transform = "Standard"
    r.resolution_x, r.resolution_y = 1080, 1920
    r.resolution_percentage = res_pct
    r.image_settings.file_format = "PNG"


# ---------------- real photo textures + downloaded models (Mr omi: 'if a real one exists, download it') ----------------
PH = FARM / "downloads/omi_story/tex_ph"          # Poly Haven CC0 diffuse maps
PSX_ASSETS = FARM / "output/_work/lowpoly/omi/psx_assets"


def photo_mat(name, file, px=128, rough=0.9, tint=(1, 1, 1)):
    """real photo texture brought to PS1 terms: <=px, RGB555, nearest filtering."""
    img = bpy.data.images.load(str(PH / file), check_existing=False)
    img.name = name
    w, h = img.size
    s = min(1.0, px / max(w, h))
    if s < 1:
        img.scale(max(8, int(w * s)), max(8, int(h * s)))
    a = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)
    a[:, :3] = np.floor(np.clip(a[:, :3] * np.array(tint), 0, 1) * 31 + 0.5) / 31
    img.pixels = a.reshape(-1).tolist()
    img.pack()
    return mat_img(name, img, closest=True, rough=rough)


def append_blend(path, loc=(0, 0, 0), rot_deg=(0, 0, 0), size=None, axis=2, only=None, skip=("Cube",)):
    """link all mesh objects of a converted asset .blend into the scene, grouped under one empty.
    size: scale so the asset's extent along `axis` equals size (metres)."""
    with bpy.data.libraries.load(str(path)) as (src, dst):
        dst.objects = [n for n in src.objects if not any(n == s or n.startswith(s + ".") for s in skip)
                       and (only is None or any(k in n for k in only))]
    sc = bpy.context.scene
    root = bpy.data.objects.new(Path(path).stem, None)
    sc.collection.objects.link(root)
    objs = [o for o in dst.objects if o is not None]
    for o in objs:
        sc.collection.objects.link(o)
    bpy.context.view_layer.update()
    tops = [o for o in objs if o.parent is None or o.parent not in objs]
    pts = [o.matrix_world @ Vector(c) for o in objs if o.type == "MESH" for c in o.bound_box]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    k = size / max(1e-6, hi[axis] - lo[axis]) if size else 1.0
    base = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for o in tops:
        mw = o.matrix_world.copy()
        o.parent = root
        o.matrix_world = mw
        o.location -= base
    root.scale = (k, k, k)
    root.rotation_euler = tuple(math.radians(a) for a in rot_deg)
    root.location = loc
    bpy.context.view_layer.update()
    return root, (hi - lo) * k
