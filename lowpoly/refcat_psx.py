"""Ref-cat reel (@zawpolyshorts DcR1veBsjo7) rebuilt from the creator's own asset packs (PS1 look).
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
    """PS1 look: image textures sampled without filtering (except the smooth list above)."""
    for m in bpy.data.materials:
        if any(m.name.lower().startswith(k.lower()) for k in SMOOTH_MATS):
            continue
        if m.node_tree:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE":
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


ROOM_W, ROOM_D = 6.0, 6.0
BACK_Y = 1.6


def build_room():
    wall = plane_mat("wall", TP_TEX / "PlasterWhite.jpg", 0.45)
    floor = plane_mat("floor", TP_TEX / "Carpet.jpg", 0.9)
    slab("floor", (ROOM_W * 2, ROOM_D * 2, 0.02), (0, 0, -0.01), floor)
    slab("wall_back", (ROOM_W * 2, 0.1, 3.0), (0, BACK_Y + 0.05, 1.5), wall)
    slab("wall_left", (0.1, ROOM_D * 2, 3.0), (-3.0, 0, 1.5), wall)
    slab("wall_right", (0.1, ROOM_D * 2, 3.0), (3.0, 0, 1.5), wall)
    slab("ceiling", (ROOM_W * 2, ROOM_D * 2, 0.05), (0, 0, 2.8), wall)
    P = load_props({"Couch", "Table_02", "Lamp_01", "Curtain", "Picture_frames", "Picture_frames_001",
                    "Picture_frames_002", "Picture_frames_003", "Photo_frame", "Door_Mesh.006", "Door.006"})
    couch = P["Couch"]
    for m in couch.data.materials:                   # the ref sofa is navy weave: recolour via texture swap
        for n in m.node_tree.nodes:
            if n.type == "TEX_IMAGE":
                n.image = bpy.data.images.load(str(PROPS / "Textures/Couch_blue_weave.png"))
    couch.scale = (COUCH_SCALE,) * 3
    place(couch, (0.1, BACK_Y - 0.48 * COUCH_SCALE, 0), COUCH_ROT)
    place(P["Table_02"], (-1.75, BACK_Y - 0.4, 0))
    place(P["Lamp_01"], (-1.75, BACK_Y - 0.4, 0.80))
    place(P["Photo_frame"], (-1.55, BACK_Y - 0.55, 0.80), 15)
    place(P["Curtain"], (-2.35, BACK_Y - 0.06, 0.55), CURTAIN_ROT)
    for i, (nm, x, z) in enumerate([("Picture_frames", -0.9, 1.75), ("Picture_frames_001", -0.25, 1.95),
                                    ("Picture_frames_002", 0.55, 1.7), ("Picture_frames_003", 1.25, 1.9)]):
        place(P[nm], (x, BACK_Y - 0.01, z), FRAME_ROT)
        P[nm].scale = (1.6, 1.6, 1.6)
    for nm in ("Door_Mesh.006", "Door.006"):
        if nm in P:
            place(P[nm], (2.93, -0.8, 0), 0)
    return P


COUCH_ROT, CURTAIN_ROT, FRAME_ROT = 90.0, 90.0, 90.0
COUCH_SCALE = 0.82
SEAT_Z = 0.48          # replaced by seat_height() after the room is built


def seat_height(x, y):
    """Ray-cast straight down onto the couch seat."""
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    hit, loc, *_ = SC.ray_cast(dg, Vector((x, y, 2.5)), Vector((0, 0, -1)))
    return loc.z if hit else 0.45


# ---------------- man ----------------
def build_man(bvh, loc, rot=0.0, frames=None):
    with bpy.data.libraries.load(str(FARM / "lowpoly/assets/psx_man20.blend")) as (src, dst):
        dst.objects = [n for n in src.objects]
    for o in dst.objects:
        SC.collection.objects.link(o)
    arm = next(o for o in dst.objects if o.type == "ARMATURE")
    RT.apply_bvh_rpm(arm, str(bvh), SC, 1, frames=frames, hold_root=True)
    arm.rotation_mode = "XYZ"
    arm.rotation_euler.z = math.radians(rot)
    SC.frame_set(1)
    bpy.context.view_layer.update()
    hips = arm.matrix_world @ arm.pose.bones["Hips"].head
    arm.location += Vector(loc) - hips + Vector((0, 0, 0.10))     # loc = seat point under the hips
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
def build_cat(loc, rot_deg, length=0.95, look_at=None):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(A / "skf/bicolor/source/bicolor Cat.glb"))
    objs = [o for o in bpy.data.objects if o not in before]
    for o in objs:
        if o.type == "MESH" and o.name.startswith("Icosphere"):
            bpy.data.objects.remove(o, do_unlink=True)
    objs = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in objs if o.type == "ARMATURE")
    for o in objs:
        if o.type == "MESH":
            for m in o.data.materials:
                if m and m.node_tree:
                    for n in m.node_tree.nodes:
                        if n.type == "TEX_IMAGE" and n.image and "diffuse" in n.image.name.lower():
                            n.image = bpy.data.images.load(str(A / "skf/bicolor/textures/Diffuse_tabby_ref.png"))
    act = bpy.data.actions.get("Animation")
    arm.animation_data_create()
    if act:
        arm.animation_data.action = act
        if act.slots:
            arm.animation_data.action_slot = act.slots[0]
    k = length / 0.82
    for r in [o for o in objs if o.parent is None]:
        r.scale = r.scale * k
        r.location = loc
        r.rotation_mode = "XYZ"
        r.rotation_euler.z = math.radians(rot_deg)
    if look_at is not None:
        tgt = bpy.data.objects.new("cat_look", None)
        SC.collection.objects.link(tgt)
        tgt.location = look_at
        for bn, infl in (("Wolf_Neck_02SHJnt", 0.3), ("Wolf_Neck_TopSHJnt", 0.6)):
            pb = arm.pose.bones.get(bn)
            if pb:
                c = pb.constraints.new("DAMPED_TRACK")
                c.target = tgt
                c.track_axis = "TRACK_Y"
                c.influence = infl
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
SHOTS = {
    "s1": dict(frames=12, man=("sit_remote_1", (0.55, BACK_Y - 0.62, "seat"), 0), man_frames=(31, 150), cat=((-0.15, BACK_Y - 0.62, "seat"), 66, (0.55, BACK_Y - 0.85, 1.25)),
               man_look=(-0.05, BACK_Y - 0.7, 0.7),
               cam=[(1, (1.35, -0.55, 1.85), (-0.30, BACK_Y - 0.6, 0.55)), (12, (1.25, -0.42, 1.80), (-0.30, BACK_Y - 0.6, 0.55))], lens=24),
    # 0.40-1.50 close on the cat in profile looking at him; his hand + remote in the bottom-right foreground
    "s2": dict(frames=33, man=("sit_remote_1", (0.55, BACK_Y - 0.62, "seat"), 0), man_frames=(31, 150), cat=((-0.15, BACK_Y - 0.62, "seat"), 80, (0.55, BACK_Y - 0.85, 1.25)),
               cam=[(1, (0.42, 0.30, 0.88), (-0.02, BACK_Y - 0.6, 0.66)), (33, (0.40, 0.34, 0.87), (-0.02, BACK_Y - 0.6, 0.67))], lens=28),
    # 1.50-2.00 cat head-on staring into the lens, remote lying on the seat in front
    "s3": dict(frames=15, man=("sit_remote_1", (0.55, BACK_Y - 0.62, "seat"), 0), man_frames=(31, 150), cat=((-0.15, BACK_Y - 0.55, "seat"), 0, (-0.15, -0.5, 0.75)),
               cam=[(1, (-0.15, 0.05, 0.86), (-0.15, BACK_Y - 0.6, 0.62)), (15, (-0.15, 0.10, 0.85), (-0.15, BACK_Y - 0.6, 0.62))], lens=28,
               remote=(-0.20, BACK_Y - 0.93, "seat"), remote_rot=10),
    # 2.00-3.20 cat by his hand on the knee, looking up at him
    "s4": dict(frames=36, man=("sit_look_1", (0.55, BACK_Y - 0.62, "seat"), 0), cat=((0.18, BACK_Y - 0.62, "seat"), 75, (0.55, BACK_Y - 0.75, 1.35)),
               cam=[(1, (-0.35, 0.25, 0.92), (0.32, BACK_Y - 0.65, 0.66)), (36, (-0.31, 0.29, 0.91), (0.32, BACK_Y - 0.65, 0.67))], lens=28),
    # 3.20-4.10 cat POV from below: man looks into the lens ("!" pops at 3.6, added in post)
    "s5": dict(frames=27, man=("sit_look_1", (0.55, BACK_Y - 0.62, "seat"), 0), cat=((-0.29, BACK_Y - 0.82, "seat"), 104, (0.55, BACK_Y - 0.62, 1.35)),
               cam=[(1, (-0.15, BACK_Y - 0.80, 0.88), (0.52, BACK_Y - 0.62, 1.28)), (27, (-0.15, BACK_Y - 0.80, 0.88), (0.52, BACK_Y - 0.62, 1.30))], lens=19,
               man_look=(-0.15, BACK_Y - 0.80, 0.88)),
    "look": dict(frames=2, man=("sit_remote_1", (0.55, BACK_Y - 0.62, "seat"), 0), man_frames=(31, 150), cat=((-0.15, BACK_Y - 0.62, "seat"), 66, None),
                 cam=[(1, (0.0, -3.2, 1.6), (0.0, BACK_Y - 0.6, 0.8))], lens=22),
}

S = SHOTS[SHOT]
build_room()
SEAT_Z = seat_height(0.1, BACK_Y - 0.62)
print("SEAT_Z", round(SEAT_Z, 3))
def sz(v):
    return (v[0], v[1], SEAT_Z if v[2] == "seat" else v[2])
mn, mloc, mrot = S["man"]
man = build_man(KIM / f"{os.environ.get('MAN_BVH', mn)}.bvh", sz(mloc), mrot, frames=S.get("man_frames"))
if S.get("man_look"):
    man_look(man, S["man_look"])
cl, cr, ck = S["cat"]
build_cat(sz(cl), cr, look_at=ck)
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
