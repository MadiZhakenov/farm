"""v2 — built inside the creator's own Trailer Park scene. Ref-cat reel (@zawpolyshorts DcR1veBsjo7) rebuilt from the creator's own asset packs (PS1 look).
Living room = Trailer Park Props (Elbolilloduro, CC-BY), man = Retro PSX Male Pack face 20 (jonniemadeit, CC-BY,
rigged by lowpoly/psx_rig_man.py), cat = Bicolor Cat (kenchoo, CC-BY) recoloured, 256 px texture.
  blender -b --factory-startup -P lowpoly/refcat_psx.py -- SHOT OUT_DIR [still_frame]
"""
import importlib.util
import math
import os
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

FARM = Path(__file__).resolve().parent.parent
A = FARM / "downloads/lowpoly_ref/assets"
PROPS = A / "psx/trailer_props/source/Trailer_Park_Props"
TP_TEX = A / "psx/trailer_park/source/Trailer_Park/Textures"
KIM = FARM / "output/_work/lowpoly/kimodo"
args = sys.argv[sys.argv.index("--") + 1:]
SHOT, OUT = args[0], Path(args[1])
STILL = int(args[2]) if len(args) > 2 else None

bpy.ops.wm.read_factory_settings(use_empty=True)
SC = bpy.context.scene
SC.render.fps = 30
spec_ = importlib.util.spec_from_file_location("retarget", FARM / "lowpoly/retarget.py")
RT = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(RT)


SMOOTH_MATS = ("cat diffuse", "eye", "Couch", "wall", "floor")   # ref: cat/sofa/walls are filtered, faces are not


def closest_all():
    """Ref: only the people are point-sampled (pixel-stepped face edges); scene textures stay filtered."""
    for m in bpy.data.materials:
        if m.node_tree:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image and n.image.name.startswith("Character"):
                    n.interpolation = "Closest"


def bbox(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    return (Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))),
            Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))))


# ---------------- props ----------------
def load_props(names):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(PROPS / "Models/Trailer_Park_Props.fbx"))
    for im in bpy.data.images:
        if not os.path.exists(bpy.path.abspath(im.filepath)):
            p = PROPS / "Textures" / os.path.basename(im.filepath.replace("\\", "/"))
            if p.exists():
                im.filepath = str(p)
                im.reload()
    new = [o for o in bpy.data.objects if o not in before]
    keep = {}
    for o in new:
        if o.type == "MESH" and o.name in names:
            keep[o.name] = o
    for o in new:
        if o.name not in keep:
            bpy.data.objects.remove(o, do_unlink=True)
    for o in keep.values():                         # normalise: unparent, origin at bottom centre
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
        bpy.context.view_layer.update()
        lo, hi = bbox([o])
        c = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
        o.data.transform(Matrix.Translation(-(o.matrix_world.inverted() @ c)))
        o.location = (0, 0, 0)
    return keep


def place(o, loc, rot_deg=0.0):
    o.location = loc
    o.rotation_euler = Euler((o.rotation_euler.x, o.rotation_euler.y, math.radians(rot_deg)))


def plane_mat(name, img, tile):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = bpy.data.images.load(str(img), check_existing=True)
    t.interpolation = "Closest"
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (tile, tile, tile)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
    t.projection = "BOX"
    nt.links.new(t.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
    nt.nodes["Principled BSDF"].inputs["Roughness"].default_value = 1.0
    return m


def slab(name, size, loc, m):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    me.transform(Matrix.Diagonal((*size, 1)))
    ob = bpy.data.objects.new(name, me)
    SC.collection.objects.link(ob)
    ob.location = loc
    me.materials.append(m)
    return ob


TRAILER = FARM / "lowpoly/assets/trailer_park.blend"
BLUE_WEAVE = PROPS / "Textures/Couch_blue_weave.png"
# trailer 1 living room: couch along the +X wall, long axis Y, faces -X
COUCH_X, SEAT_X = 3.0, 2.78


def build_room():
    bpy.ops.wm.open_mainfile(filepath=str(TRAILER))
    global SC
    SC = bpy.context.scene
    SC.render.fps = 30
    blue = bpy.data.images.load(str(BLUE_WEAVE))
    for m in bpy.data.materials:
        if m.name.split(".")[0] == "Couch" and m.node_tree:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE":
                    n.image = blue
    # set dressing as in the ref: yellow vase lamp + red plaid curtain at the far (+Y) end, photo on the table
    lamp = bpy.data.objects.get("Lamp.003")
    yellow = next((o for o in bpy.data.objects if o.name.startswith("Lamp_01.")), None)
    if lamp and yellow:
        lamp.data = yellow.data                      # swap the mesh+UVs, keep the placement
    cur = bpy.data.objects.get("Curtain.002")
    if cur:
        cur.location.y += 2.05 - (-1.85)
        for m in cur.data.materials:                 # ref curtain is opaque
            b = m.node_tree.nodes.get("Principled BSDF")
            if b and b.inputs["Alpha"].links:
                m.node_tree.links.remove(b.inputs["Alpha"].links[0])
                b.inputs["Alpha"].default_value = 1.0
    pf = next((o for o in bpy.data.objects if o.name.startswith("Photo_frame") and not o.name.startswith("Photo_frame_")), None)
    if pf:
        dup = pf.copy()
        SC.collection.objects.link(dup)
        dup.parent = None
        dup.matrix_world = Matrix.Translation((2.92, 2.30, 0.80)) @ Matrix.Rotation(math.radians(-60), 4, "Z")
    # the ref shows no exterior: hide far trailers/trees to keep renders fast
    for o in bpy.data.objects:
        if o.type == "MESH":
            c = o.matrix_world.translation
            if abs(c.x - 2.0) > 12 or abs(c.y + 3.0) > 14:
                o.hide_render = True


# ---------------- man ----------------
CHARS = A / "psx/characters_psx/source/Characters_psx/Characters_psx"
SEAT_Z = 0.45


def seat_height(x, y):
    """Ray-cast straight down onto the couch seat."""
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    hit, loc, *_ = SC.ray_cast(dg, Vector((x, y, 1.2)), Vector((0, 0, -1)))
    return loc.z if hit else 0.45


def build_man(bvh, loc, rot=0.0, frames=None, who="Character_07"):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(CHARS / f"Models/Male/{who}.fbx"))
    new = [o for o in bpy.data.objects if o not in before]
    for im in bpy.data.images:
        if not os.path.exists(bpy.path.abspath(im.filepath)):
            p = CHARS / "Textures" / os.path.basename(im.filepath.replace("\\", "/"))
            if p.exists():
                im.filepath = str(p)
                im.reload()
    arm = next(o for o in new if o.type == "ARMATURE")
    if arm.animation_data:
        arm.animation_data.action = None
    for b in arm.data.bones:                         # mixamorig:Hips -> Hips (vertex groups follow)
        if b.name.startswith("mixamorig:"):
            b.name = b.name[len("mixamorig:"):]
    meshes = [o for o in new if o.type == "MESH"]
    bpy.context.view_layer.update()
    zs = [(o.matrix_world @ v.co).z for o in meshes for v in o.data.vertices]
    k = 1.80 / (max(zs) - min(zs))
    for r in [o for o in new if o.parent is None]:
        r.scale = r.scale * k
    bpy.context.view_layer.update()
    RT.apply_bvh_rpm(arm, str(bvh), SC, 1, frames=frames, hold_root=True)
    for r in [o for o in new if o.parent is None]:
        r.rotation_mode = "XYZ"
        r.rotation_euler.z += math.radians(rot)
    SC.frame_set(1)
    bpy.context.view_layer.update()
    hips = arm.matrix_world @ arm.pose.bones["Hips"].head
    for r in [o for o in new if o.parent is None]:
        r.location += Vector(loc) - hips + Vector((0, 0, 0.10))
    return arm


def man_look(arm, point, influence=0.9):
    tgt = bpy.data.objects.new("man_look", None)
    SC.collection.objects.link(tgt)
    tgt.location = point
    b = arm.data.bones["Head"]
    rest = arm.matrix_world.to_3x3().normalized() @ b.matrix_local.to_3x3().normalized()
    fwd = rest.inverted() @ Vector((0, -1, 0))
    ax = max(range(3), key=lambda i: abs(fwd[i]))
    track = ("TRACK_" if fwd[ax] > 0 else "TRACK_NEGATIVE_") + "XYZ"[ax]
    for bn, infl in (("Neck", influence * 0.4), ("Head", influence)):
        c = arm.pose.bones[bn].constraints.new("DAMPED_TRACK")
        c.target = tgt
        c.track_axis = track
        c.influence = infl


# ---------------- cat ----------------
CAT_BLEND = Path(os.environ.get("CAT_BLEND", str(FARM / "output/_work/lowpoly/ref_cat/cat_calib.blend")))
spec_ca = importlib.util.spec_from_file_location("cat_anim", FARM / "lowpoly/cat_anim.py")
CA = importlib.util.module_from_spec(spec_ca)
spec_ca.loader.exec_module(CA)


def build_cat(loc, rot_deg, length=1.12, look_at=None, frames=60, motion="idle"):
    """Procedural PS1 cat (lowpoly/cat_build.py) with code-driven motion; length = scale factor."""
    with bpy.data.libraries.load(str(CAT_BLEND)) as (src, dst):
        dst.objects = [n for n in src.objects if n in ("cat_rig", "cat_body")]
    for o in dst.objects:
        SC.collection.objects.link(o)
    arm = next(o for o in dst.objects if o.type == "ARMATURE")
    arm.scale = (length,) * 3
    arm.location = loc
    arm.rotation_mode = "XYZ"
    arm.rotation_euler.z = math.radians(rot_deg)
    arm.animation_data_create()
    if motion == "idle":
        CA.idle(arm, 1, frames)
    elif motion == "sniff":
        CA.sniff(arm, 1, frames)
    if look_at is not None:
        tgt = bpy.data.objects.new("cat_look", None)
        SC.collection.objects.link(tgt)
        tgt.location = look_at
        CA.track_head(arm, tgt)
    return arm


def make_remote():
    tex = FARM / "output/_work/lowpoly/ref_cat/tex/remote_top.png"
    body = slab("remote", (0.19, 0.05, 0.022), (0, 0, 0), plane_mat("remote_white", TP_TEX / "PlasterWhite.jpg", 3.0))
    body.data.materials[0].node_tree.nodes["Principled BSDF"].inputs["Base Color"].links[0].from_node.image =         bpy.data.images.load(str(tex))
    m = bpy.data.materials.new("remote_top")
    m.use_nodes = True
    t = m.node_tree.nodes.new("ShaderNodeTexImage")
    t.image = bpy.data.images.load(str(tex))
    m.node_tree.links.new(t.outputs["Color"], m.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    top = slab("remote_top", (0.185, 0.046, 0.001), (0, 0, 0.0115), m)
    me = top.data
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    uv = me.uv_layers.new()
    for p_ in me.polygons:
        for li in p_.loop_indices:
            v = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = ((v.x - min(xs)) / (max(xs) - min(xs)), (v.y - min(ys)) / (max(ys) - min(ys)))
    top.parent = body
    for n in body.data.materials[0].node_tree.nodes:
        if n.type == "TEX_IMAGE":
            n.image = bpy.data.images.load(str(TP_TEX / "PlasterWhite.jpg"))
    return body


def remote_in_hand(remote, arm, bone="RightHand", along=0.06):
    SC.frame_set(1)
    bpy.context.view_layer.update()
    pb = arm.pose.bones[bone]
    hw = arm.matrix_world @ pb.matrix
    rot = hw.to_3x3().normalized()
    y = rot @ Vector((0, 1, 0))
    remote.matrix_world = Matrix.Translation(hw.translation + y * along) @ (rot @ Matrix.Rotation(math.radians(90), 3, "Z")).to_4x4()
    c = remote.constraints.new("CHILD_OF")
    c.target = arm
    c.subtarget = bone
    c.inverse_matrix = hw.inverted()


# ---------------- camera / light ----------------
def camera(keys, lens=30):
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    SC.collection.objects.link(cam)
    cam.data.lens = lens
    cam.data.sensor_fit = "VERTICAL"
    cam.data.sensor_height = 24
    cam.data.clip_start = 0.02
    SC.camera = cam
    for f, loc, look in keys:
        cam.location = loc
        cam.rotation_euler = (Vector(look) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)


def lights():
    """Flat game-like light: strong ambient + one soft sun, almost no contrast."""
    w = bpy.data.worlds.new("w")
    SC.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (1, 1, 1, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 0.85
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 1.6
    sun.data.angle = math.radians(25)
    sun.rotation_euler = (math.radians(50), 0, math.radians(-35))
    SC.collection.objects.link(sun)


# ---------------- shots ----------------
SEAT_Y_MAN, SEAT_Y_CAT = -0.05, 0.95
SHOTS = {
    "look": dict(frames=2, man=("sit_tv_2", (SEAT_X, SEAT_Y_MAN, "seat"), -90),
                 cat=((SEAT_X, SEAT_Y_CAT, "seat"), -163, None), cam=[(1, (0.6, 0.9, 1.5), (3.3, 0.9, 0.8))], lens=18),
    # 0.00-0.40 high 3/4 from the man's end: lamp + red curtain far left, cat mid-seat looking at him
    "s1": dict(frames=12, man=("sit_tv_2", (SEAT_X, SEAT_Y_MAN, "seat"), -90),
               cat=((SEAT_X, SEAT_Y_CAT, "seat"), 20, (SEAT_X - 0.1, SEAT_Y_MAN, 1.25)),
               cam=[(1, (1.5, -1.05, 1.98), (2.75, 0.45, 0.72)), (12, (1.58, -0.92, 1.93), (2.75, 0.45, 0.72))], lens=22),
    # 0.40-1.50 close on the cat in profile looking up at him, his hand + remote in the bottom-right foreground
    "s2": dict(frames=33, man=("sit_tv_2", (SEAT_X, SEAT_Y_MAN, "seat"), -90),
               cat=((SEAT_X, SEAT_Y_CAT, "seat"), 15, (SEAT_X - 0.1, SEAT_Y_MAN, 1.3)),
               cam=[(1, (2.28, -0.45, 1.05), (2.8, 0.6, 0.62)), (33, (2.30, -0.40, 1.04), (2.8, 0.6, 0.63))], lens=26),
    # 1.50-2.00 cat head-on into the lens, remote lying on the seat in front, door + table behind
    "s3": dict(frames=15, man=("sit_tv_2", (SEAT_X, SEAT_Y_MAN, "seat"), -90),
               cat=((SEAT_X - 0.05, 0.95, "seat"), 0, (SEAT_X - 0.05, -0.5, 0.8)),
               cam=[(1, (SEAT_X - 0.05, 0.05, 0.92), (SEAT_X - 0.05, 1.2, 0.62)), (15, (SEAT_X - 0.05, 0.11, 0.91), (SEAT_X - 0.05, 1.2, 0.62))], lens=26,
               remote=(SEAT_X - 0.08, 0.36, "seat"), remote_rot=75),
    # 2.00-3.20 cat by his hand on the knee, looking up at him
    "s4": dict(frames=36, man=("sit_look_1", (SEAT_X, SEAT_Y_MAN, "seat"), -90),
               cat=((SEAT_X - 0.05, 0.55, "seat"), 0, (SEAT_X - 0.15, SEAT_Y_MAN, 1.35)),
               cam=[(1, (1.9, 0.38, 0.97), (2.8, 0.22, 0.74)), (36, (1.94, 0.37, 0.96), (2.8, 0.22, 0.75))], lens=26),
    # 3.20-4.10 cat POV from below: man looks into the lens ("!" pops at 3.6 in post)
    "s5": dict(frames=27, man=("sit_look_1", (SEAT_X, SEAT_Y_MAN, "seat"), -90),
               cat=((2.62, 0.42, "seat"), 0, (2.9, -0.05, 1.2)),
               cam=[(1, (2.6, 0.72, 1.0), (2.9, -0.05, 1.22)), (27, (2.6, 0.72, 1.0), (2.9, -0.05, 1.24))], lens=19,
               man_look=(2.6, 0.72, 1.0)),
}

S = SHOTS[SHOT]
build_room()
SEAT_Z = seat_height(SEAT_X, 0.9)
print("SEAT_Z", round(SEAT_Z, 3))
def sz(v):
    return (v[0], v[1], SEAT_Z if v[2] == "seat" else v[2])
print("SEAT_Z", round(SEAT_Z, 3))
def sz(v):
    return (v[0], v[1], SEAT_Z if v[2] == "seat" else v[2])
mn, mloc, mrot = S["man"]
man = build_man(KIM / f"{os.environ.get('MAN_BVH', mn)}.bvh", sz(mloc), mrot, frames=S.get("man_frames"))
if S.get("man_look"):
    man_look(man, S["man_look"])
cl, cr, ck = S["cat"]
build_cat(sz(cl), cr, look_at=ck, frames=S["frames"])
remote = make_remote()
if S.get("remote"):
    remote.location = sz(S["remote"])
    remote.location.z += 0.012
    remote.rotation_euler.z = math.radians(S.get("remote_rot", 10))
else:
    remote_in_hand(remote, man)
camera(S["cam"], S.get("lens", 30))
lights()
closest_all()
if os.environ.get("PROBE"):
    SC.frame_set(STILL or 1)
    bpy.context.view_layer.update()
    for bn in ("Head", "RightHand", "LeftHand", "RightLeg", "LeftLeg", "Hips"):
        print("PROBE", bn, tuple(round(v, 2) for v in man.matrix_world @ man.pose.bones[bn].head))
    cat_arm = next(o for o in bpy.data.objects if o.type == "ARMATURE" and "Wolf_Neck_TopSHJnt" in o.pose.bones)
    print("PROBE cathead", tuple(round(v, 2) for v in cat_arm.matrix_world @ cat_arm.pose.bones["Wolf_Neck_TopSHJnt"].head))
    sys.exit(0)
r = SC.render
r.engine = "BLENDER_EEVEE"
SC.view_settings.view_transform = "Standard"
r.resolution_x, r.resolution_y = 1080, 1920
r.resolution_percentage = int(os.environ.get("RES_PCT", "50"))
SC.frame_start, SC.frame_end = 1, S["frames"]
OUT.mkdir(parents=True, exist_ok=True)
r.image_settings.file_format = "PNG"
if STILL:
    SC.frame_set(STILL)
    r.filepath = str(OUT / "still.png")
    bpy.ops.render.render(write_still=True)
else:
    r.filepath = str(OUT / "f_")
    bpy.ops.render.render(animation=True)
print("DONE", OUT)
