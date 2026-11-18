"""Mr omi tutorial demo, 1:1: lift lobby, a man in a red top slips by the WET FLOOR sign and falls on his back.
  blender -b --factory-startup -P lowpoly/omi_lobby.py -- OUT_DIR [still|anim]
Same pipeline as the tutorial (youtube lBh7dN2ts88):
- people from the Characters_psx pack (Elbolillo, CC-BY), photo faces; main = Character_06 repainted,
- room built in code (walls, floor, lights), props = real downloaded models (psx wet floor sign, CC-BY),
- motion from Kimodo text-to-motion ("A man slips and falls on his back."),
- face = one flat picture (swap the picture for an expression),
- 9:16, low-res render upscaled later ('crunchy low-poly effect').
"""
import importlib.util
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

FARM = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("retarget", FARM / "lowpoly/retarget.py")
RT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RT)
# the RPM head/neck rest fix was measured on another rig; this pack needs its own (env HEAD_FIX="neck,head" deg)
_hf = [float(v) for v in os.environ.get("HEAD_FIX", "0,0").split(",")]
RT.RPM_REST_FIX = {"Neck": _hf[0], "Head": _hf[1]}

args = sys.argv[sys.argv.index("--") + 1:]
OUT = Path(args[0])
MODE = args[1] if len(args) > 1 else "still"
CHARS = FARM / "downloads/lowpoly_ref/assets/psx/characters_psx/source/Characters_psx/Characters_psx"
KIM = FARM / "output/_work/lowpoly/kimodo/omi"
SIGN = FARM / "downloads/omi_tutorial/assets/wetfloor_psx/scene.gltf"
TEX = FARM / "output/_work/lowpoly/omi/tex"
MAIN_TEX = os.environ.get("MAIN_TEX")                       # repainted atlas for the main character
SLIP = os.environ.get("SLIP_BVH", str(KIM / "slip_a.bvh"))
RES_PCT = int(os.environ.get("RES_PCT", "50"))
FRAMES = int(os.environ.get("FRAMES", "120"))

bpy.ops.wm.read_factory_settings(use_empty=True)
SC = bpy.context.scene
SC.render.fps = 30
SC.frame_start, SC.frame_end = 1, FRAMES


# ---------------- textures made in code ----------------
def make_textures():
    from PIL import Image, ImageDraw, ImageFont, ImageFilter  # noqa: F401  (Blender's python has no PIL)


def img_from_array(name, arr):
    import numpy as np
    h, w, _ = arr.shape
    im = bpy.data.images.new(name, w, h)
    rgba = np.concatenate([arr[::-1], np.ones((h, w, 1))], axis=2)
    im.pixels = rgba.reshape(-1).tolist()
    im.pack()
    return im


def checker_image():
    import numpy as np
    rng = np.random.default_rng(1)
    S, n = 512, 8
    yy, xx = np.mgrid[0:S, 0:S]
    tile = ((xx // (S // n)) + (yy // (S // n))) % 2
    base = np.where(tile[..., None] == 0, np.array([0.26, 0.26, 0.27]), np.array([0.50, 0.50, 0.51]))
    noise = rng.normal(0, 0.018, (S // 4, S // 4)).repeat(4, 0).repeat(4, 1)[..., None]
    grout = (((xx % (S // n)) < 2) | ((yy % (S // n)) < 2))[..., None]
    col = np.clip(base + noise, 0, 1) * np.where(grout, 0.8, 1.0)
    return img_from_array("lobby_floor", col)


def wall_image():
    """lower mauve wainscot / upper light grey, with faint plaster noise (1 px = 1 cm, 300 cm tall)."""
    import numpy as np
    rng = np.random.default_rng(2)
    H, W = 300, 64
    z = np.arange(H)[::-1][:, None]                       # row 0 = top
    col = np.where((z < 262)[..., None], np.array([0.47, 0.39, 0.39]), np.array([0.84, 0.84, 0.85]))
    col = col * (1 + rng.normal(0, 0.012, (H, W, 1)))
    col = np.broadcast_to(col, (H, W, 3)).copy()
    return img_from_array("lobby_wall", np.clip(col, 0, 1))


def display_image():
    """black floor display with an orange up-arrow and '12' (drawn with numpy, PS1-crude)."""
    import numpy as np
    H, W = 32, 80
    a = np.zeros((H, W, 3)) + 0.05
    org = np.array([1.0, 0.45, 0.10])
    for y in range(8, 24):                                 # triangle arrow
        half = (y - 8) // 2
        a[y, 14 - half:15 + half] = org
    digits = {"1": ["01", "11", "01", "01", "01", "01", "11"], "2": ["11", "01", "01", "11", "10", "10", "11"]}
    x0 = 30
    for ch in "12":
        pat = digits[ch]
        for r, row in enumerate(pat):
            for c, v in enumerate(row):
                if v == "1":
                    a[6 + r * 3:6 + r * 3 + 3, x0 + c * 5:x0 + c * 5 + 5] = org
        x0 += 16
    return img_from_array("lift_display", a)


def mat_img(name, img, closest=False, rough=0.9):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = img
    if closest:
        t.interpolation = "Closest"
    nt.links.new(t.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
    nt.nodes["Principled BSDF"].inputs["Roughness"].default_value = rough
    return m


def mat_col(name, rgb, rough=0.8, emit=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = rough
    return m


def box(name, size, loc, mat):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    bpy.ops.object.transform_apply(scale=True)
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
    SC.collection.objects.link(o)
    return o


# ---------------- room (built in code, like the tutorial) ----------------
def build_room():
    floor_m = mat_img("floor", checker_image(), rough=0.35)
    tiles = 3.0                                          # 4x4 tiles per image repeat -> 0.6 m tiles at 2.4 m
    plane_uv("floor", [(-3, -4, 0), (3, -4, 0), (3, 2, 0), (-3, 2, 0)],
             [(0, 0), (6 / 2.4, 0), (6 / 2.4, 6 / 2.4), (0, 6 / 2.4)], floor_m)
    wall_m = mat_img("wall", wall_image())
    plane_uv("back_wall", [(-3, 2, 0), (3, 2, 0), (3, 2, 3), (-3, 2, 3)], [(0, 0), (1, 0), (1, 1), (0, 1)], wall_m)
    for sx in (-1, 1):
        plane_uv(f"side_wall_{sx}", [(3 * sx, -4, 0), (3 * sx, 2, 0), (3 * sx, 2, 3), (3 * sx, -4, 3)],
                 [(0, 0), (1, 0), (1, 1), (0, 1)], wall_m)
    door_m = mat_col("lift_door", (0.86, 0.87, 0.88), rough=0.45)
    frame_m = mat_col("lift_frame", (0.62, 0.63, 0.65), rough=0.5)
    disp_m = mat_img("lift_display", display_image(), closest=True)
    for x in (-0.95, 0.95):
        box(f"frame_{x}", (1.18, 0.06, 2.24), (x, 1.98, 1.12), frame_m)
        box(f"door_{x}", (1.02, 0.04, 2.12), (x, 1.955, 1.06), door_m)
        box(f"door_gap_{x}", (0.008, 0.045, 2.12), (x, 1.952, 1.06), mat_col("gap", (0.35, 0.35, 0.36)))
        d = box(f"display_{x}", (0.36, 0.03, 0.15), (x, 1.965, 2.42), disp_m)
        d.data.uv_layers.active.data.foreach_set("uv", [c for p in d.data.polygons for li in p.loop_indices
                                                       for c in ((0, 0), (1, 0), (1, 1), (0, 1))[li % 4]])
    box("call_panel", (0.10, 0.02, 0.22), (0, 1.985, 1.18), mat_col("panel", (0.80, 0.80, 0.82), rough=0.4))
    box("call_btn", (0.04, 0.01, 0.04), (0, 1.97, 1.22), mat_col("btn", (0.95, 0.95, 0.95), rough=0.3))
    # lights: soft ceiling key + world fill (flat, game-like)
    w = bpy.data.worlds.new("w")
    SC.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.75, 0.75, 0.78, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = float(os.environ.get("WORLD", "0.55"))
    ld = bpy.data.lights.new("key", "AREA")
    ld.energy = float(os.environ.get("KEY_W", "350"))
    ld.size = 3.0
    lo = bpy.data.objects.new("key", ld)
    lo.location = (0.3, -1.0, 2.95)
    SC.collection.objects.link(lo)
    sun = bpy.data.lights.new("sun", "SUN")
    sun.energy = 1.2
    so = bpy.data.objects.new("sun", sun)
    so.rotation_euler = (math.radians(35), 0, math.radians(15))
    SC.collection.objects.link(so)


def build_sign(loc, rot_deg, height=0.62):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(SIGN))
    new = [o for o in bpy.data.objects if o not in before]
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ v.co for o in new if o.type == "MESH" for v in o.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    k = height / (hi.z - lo.z)
    for r in [o for o in new if o.parent is None]:
        r.scale = r.scale * k
        r.location = Vector(loc) - Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)) * k
        r.rotation_mode = "XYZ"
        r.rotation_euler.z += math.radians(rot_deg)


# ---------------- people (Characters_psx pack + Kimodo) ----------------
DELTA_BONES = ("Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase", "RightUpLeg", "RightLeg", "RightFoot", "RightToeBase")


def build_person(fbx, bvh, loc, rot_deg=0.0, height=1.78, hold_root=True, frames=None, tex=None):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(fbx))
    new = [o for o in bpy.data.objects if o not in before]
    for im in bpy.data.images:
        if im.filepath and not os.path.exists(bpy.path.abspath(im.filepath)):
            p = CHARS / "Textures" / os.path.basename(im.filepath.replace("\\", "/"))
            if p.exists():
                im.filepath = str(p)
                im.reload()
    if tex:
        for o in new:
            if o.type == "MESH":
                for m in o.data.materials:
                    for n in m.node_tree.nodes:
                        if n.type == "TEX_IMAGE":
                            n.image = bpy.data.images.load(tex, check_existing=True)
    arm = next(o for o in new if o.type == "ARMATURE")
    if arm.animation_data:
        arm.animation_data.action = None
    for pb in arm.pose.bones:                             # the FBX leaves its clip's pose on the bones: back to rest
        pb.matrix_basis.identity()
    for b in arm.data.bones:
        if b.name.startswith("mixamorig:"):
            b.name = b.name[len("mixamorig:"):]
    meshes = [o for o in new if o.type == "MESH"]
    bpy.context.view_layer.update()
    zs = [(o.matrix_world @ v.co).z for o in meshes for v in o.data.vertices]
    k = height / (max(zs) - min(zs))
    roots = [o for o in new if o.parent is None]
    for r in roots:
        r.scale = r.scale * k
    bpy.context.view_layer.update()
    RT.apply_bvh_rpm(arm, str(bvh), SC, 1, frames=frames, hold_root=hold_root, src_yaw_deg=90)  # pack rests facing +X
    RT.nod_head(arm, float(os.environ.get("NOD", "14")), facing=(1, 0, 0))  # head reads ~14 deg chin-up (measured)
    adduct = float(os.environ.get("ARM_IN", "9"))                            # wide low-poly torso: arms in a bit
    RT.turn_bone(arm, "LeftArm", (1, 0, 0), -adduct)
    RT.turn_bone(arm, "RightArm", (1, 0, 0), adduct)   # Kimodo reads ~15 deg chin-up on this rig (measured vs rest)
    for r in roots:                                       # rest faces +X: turn to the camera (-Y), then rot_deg
        r.rotation_mode = "XYZ"
        r.rotation_euler.z += math.radians(-90 + rot_deg)
    SC.frame_set(1)
    bpy.context.view_layer.update()
    feet = min((o.matrix_world @ v.co).z for o in meshes for v in o.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh().vertices)
    hips = arm.matrix_world @ arm.pose.bones["Hips"].head
    for r in roots:
        r.location += Vector((loc[0] - hips.x, loc[1] - hips.y, -feet))
    for o in meshes:                                      # PS1 look: nearest-neighbour texels on people
        for m in o.data.materials:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE":
                    n.interpolation = "Closest"
    return arm


def main():
    build_room()
    build_sign((-0.55, -0.55, 0), -18)
    M, F = CHARS / "Models/Male", CHARS / "Models/Female"
    st = {k: KIM / f"stand_{k}.bvh" for k in "abc"}
    build_person(F / "Character_30_Female.fbx", KIM / "stand_d.bvh", (-1.05, 1.15), rot_deg=10, height=1.66)
    build_person(M / "Character_31.fbx", st["a"], (0.05, 1.05), rot_deg=-5, height=1.80)
    build_person(M / "Character_29.fbx", st["b"], (0.75, 1.35), rot_deg=-12, height=1.78)
    build_person(M / "Character_06.fbx", Path(SLIP), (0.25, -0.15), rot_deg=0, height=1.80, hold_root=False,
                 tex=MAIN_TEX)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    SC.collection.objects.link(cam)
    SC.camera = cam
    cam.data.lens = 30
    cam.location = (0.0, -3.55, 1.25)
    cam.rotation_euler = (math.radians(86), 0, 0)
    r = SC.render
    r.engine = "BLENDER_EEVEE"
    SC.view_settings.view_transform = "Standard"
    r.resolution_x, r.resolution_y = 1080, 1920
    r.resolution_percentage = RES_PCT
    r.image_settings.file_format = "PNG"
    OUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "lobby.blend"))
    if MODE == "still":
        for f in (1, int(os.environ.get("STILL2", "45")), int(os.environ.get("STILL3", "90"))):
            SC.frame_set(f)
            r.filepath = str(OUT / f"still_{f:03d}.png")
            bpy.ops.render.render(write_still=True)
    else:
        r.filepath = str(OUT / "f_")
        bpy.ops.render.render(animation=True)


main()
