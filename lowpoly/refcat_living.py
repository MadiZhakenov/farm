"""Ref-cat reel (@zawpolyshorts DcR1veBsjo7) — living-room set, man (ReadyPlayerMe + Flow face) and cat (Bicolor Cat).
  blender -b --factory-startup -P lowpoly/refcat_living.py -- SHOT OUT_DIR [still_frame]
SHOT = s1..s5 (see SHOTS). Frames are rendered at 30 fps into OUT_DIR/f_####.png (or OUT_DIR/still.png).
"""
import importlib.util
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

FARM = Path(__file__).resolve().parent.parent
A = FARM / "downloads/lowpoly_ref/assets"
TEX = FARM / "output/_work/lowpoly/ref_cat/tex"
KIM = FARM / "output/_work/lowpoly/kimodo"
FACE = FARM / "downloads/lowpoly_faces/crop/base.png"
args = sys.argv[sys.argv.index("--") + 1:]
SHOT, OUT = args[0], Path(args[1])
STILL = int(args[2]) if len(args) > 2 else None

bpy.ops.wm.read_factory_settings(use_empty=True)
SC = bpy.context.scene
SC.render.fps = 30

spec_ = importlib.util.spec_from_file_location("retarget", FARM / "lowpoly/retarget.py")
RT = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(RT)


# ---------------- materials ----------------
def mat(name, color=(0.8, 0.8, 0.8), rough=0.8, img=None, emit=0.0, tile=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = rough
    if img:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(str(img), check_existing=True)
        if tile:
            tc = nt.nodes.new("ShaderNodeTexCoord")
            mp = nt.nodes.new("ShaderNodeMapping")
            mp.inputs["Scale"].default_value = (tile, tile, tile)
            nt.links.new(tc.outputs["UV"], mp.inputs["Vector"])
            nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
        nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    else:
        b.inputs["Base Color"].default_value = (*color, 1)
    if emit:
        b.inputs["Emission Color"].default_value = (*color, 1)
        b.inputs["Emission Strength"].default_value = emit
    return m


def fabric_blue():
    """Blue boucle upholstery (ref sofa): image texture box-projected in object space."""
    m = bpy.data.materials.new("fabric_blue")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.95
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (5.5, 5.5, 5.5)
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = bpy.data.images.load(str(TEX / "boucle.png"), check_existing=True)
    t.projection = "BOX"
    t.projection_blend = 0.25
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
    nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.6
    nt.links.new(t.outputs["Color"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


# ---------------- geometry helpers ----------------
def box(name, size, loc, m, bevel=0.0, rot=(0, 0, 0)):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    SC.collection.objects.link(ob)
    me.transform(Matrix.Diagonal((*size, 1.0)))      # apply scale: bevel + object-space textures stay even
    ob.location, ob.rotation_euler = loc, rot
    me.materials.append(m)
    if bevel:
        bv = ob.modifiers.new("bevel", "BEVEL")
        bv.width, bv.segments = bevel, 3
        bv.use_clamp_overlap = True
    uvp(ob)
    return ob


def uvp(ob):
    """Cube-project UVs in world-ish units so image textures tile evenly."""
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    uv = bm.loops.layers.uv.verify()
    s = ob.scale
    for f in bm.faces:
        n = f.normal
        ax = max(range(3), key=lambda i: abs(n[i]))
        for lp in f.loops:
            p = Vector((lp.vert.co.x * s.x, lp.vert.co.y * s.y, lp.vert.co.z * s.z))
            a, b2 = [(p.y, p.z), (p.x, p.z), (p.x, p.y)][ax]
            lp[uv].uv = (a, b2)
    bm.to_mesh(me)
    bm.free()


def prim(kind, name, loc, scale, m, rot=(0, 0, 0), **kw):
    getattr(bpy.ops.mesh, f"primitive_{kind}_add")(location=loc, rotation=rot, **kw)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = scale
    ob.data.materials.append(m)
    bpy.ops.object.shade_smooth()
    return ob


def import_glb(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    for o in new:
        if o.type == "MESH" and o.name.startswith("Icosphere"):
            bpy.data.objects.remove(o, do_unlink=True)
    return [o for o in bpy.data.objects if o not in before]


def root_of(objs):
    return [o for o in objs if o.parent is None]


# ---------------- set: living room ----------------
SEAT_Z = 0.46


def build_room():
    wall = mat("wall", (0.36, 0.37, 0.22), 0.9)
    carpet = mat("carpet", rough=1.0, img=TEX / "carpet.png", tile=1.0)
    carpet.node_tree.nodes["Principled BSDF"].inputs["Base Color"].links[0].from_node.image.colorspace_settings.name = "sRGB"
    box("floor", (8, 8, 0.02), (0, 0, -0.01), carpet)
    box("wall_back", (8, 0.1, 3.0), (0, 1.25, 1.5), wall)
    box("wall_left", (0.1, 8, 3.0), (-2.6, 0, 1.5), wall)
    box("wall_right", (0.1, 8, 3.0), (2.6, 0, 1.5), wall)
    box("ceiling", (8, 8, 0.05), (0, 0, 3.0), mat("ceil", (0.9, 0.9, 0.88)))
    # sofa (back to the back wall), blue weave
    fb = fabric_blue()
    sx, sy = 0.15, 0.62
    box("sofa_base", (2.1, 0.92, 0.30), (sx, sy, 0.15 + 0.02), fb, bevel=0.03)
    box("sofa_seat", (1.70, 0.80, 0.16), (sx, sy - 0.04, SEAT_Z - 0.08), fb, bevel=0.06)
    box("sofa_back", (2.1, 0.24, 0.62), (sx, sy + 0.36, 0.62), fb, bevel=0.07)
    for x in (-0.94, 0.94):
        box("sofa_arm", (0.22, 0.92, 0.62), (sx + x, sy, 0.33), fb, bevel=0.07)
    # side table + yellow lamp (left of sofa)
    wood = mat("wood", rough=0.6, img=TEX / "wood.png", tile=2.0)
    tx, ty = -1.45, 0.75
    box("table_top", (0.55, 0.50, 0.04), (tx, ty, 0.62), wood, bevel=0.01)
    box("table_shelf", (0.50, 0.45, 0.03), (tx, ty, 0.18), wood)
    for dx in (-0.24, 0.24):
        for dy in (-0.21, 0.21):
            box("table_leg", (0.04, 0.04, 0.62), (tx + dx, ty + dy, 0.31), wood)
    prim("uv_sphere", "lamp_vase", (tx, ty, 0.80), (0.13, 0.13, 0.17), mat("vase", rough=0.25, img=TEX / "vase.png"))
    prim("cylinder", "lamp_neck", (tx, ty, 1.00), (0.02, 0.02, 0.06), mat("brass", (0.75, 0.6, 0.3), 0.3))
    prim("cone", "lamp_shade", (tx, ty, 1.17), (1, 1, 1), mat("shade", (0.96, 0.95, 0.9), 0.9, emit=0.4),
         radius1=0.24, radius2=0.14, depth=0.26, vertices=32)
    # framed photos on the back wall + one on the left wall
    frame = mat("frame", (0.16, 0.09, 0.05), 0.5)
    for i, (x, z, w, h) in enumerate([(-0.95, 1.85, 0.40, 0.52), (-0.30, 2.05, 0.46, 0.36), (0.55, 1.75, 0.36, 0.46),
                                      (1.30, 2.0, 0.44, 0.34)]):
        box(f"frame{i}", (w, 0.04, h), (x, 1.19, z), frame)
        box(f"photo{i}", (w - 0.08, 0.01, h - 0.08), (x, 1.165, z), mat(f"photo{i}", rough=0.4, img=TEX / f"photo{i}.png"))
        set_plane_uv(bpy.data.objects[f"photo{i}"])
    # window with red/white plaid curtain, left of the frames
    box("window", (0.9, 0.05, 1.3), (-2.0, 1.2, 1.65), mat("sky", (0.85, 0.9, 0.95), emit=1.2))
    curtain(-1.72, 1.12, 0.55, 2.4)
    curtain(-2.30, 1.12, 0.45, 2.4)
    # white door on the right wall
    box("door", (0.06, 0.92, 2.05), (2.55, -0.9, 1.03), mat("door", (0.93, 0.93, 0.92), 0.5))
    box("door_knob", (0.05, 0.06, 0.06), (2.5, -0.55, 1.0), mat("knob", (0.8, 0.7, 0.4), 0.3))


def set_plane_uv(ob):
    """Map an image across the front (-Y) face of a thin box."""
    me = ob.data
    xs = [v.co.x for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    uv = me.uv_layers.active
    for p in me.polygons:
        for li in p.loop_indices:
            v = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = ((v.x - min(xs)) / (max(xs) - min(xs)), (v.z - min(zs)) / (max(zs) - min(zs)))


def curtain(x, y, w, h):
    me = bpy.data.meshes.new("curtain")
    bm = bmesh.new()
    nx, nz = 40, 2
    verts = []
    for j in range(nz + 1):
        row = []
        for i in range(nx + 1):
            u = i / nx
            row.append(bm.verts.new((x - w / 2 + u * w, y + 0.035 * math.sin(u * math.pi * 9), 2.95 - j * h / nz)))
        verts.append(row)
    uvl = bm.loops.layers.uv.new()
    for j in range(nz):
        for i in range(nx):
            f = bm.faces.new((verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]))
            for lp, (a, b2) in zip(f.loops, ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))):
                lp[uvl].uv = (a / nx * w * 2.2, 1 - b2 / nz * h * 2.2 / h * 1.0)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("curtain", me)
    SC.collection.objects.link(ob)
    me.materials.append(mat("plaid", rough=0.9, img=TEX / "plaid.png"))
    for p in me.polygons:
        p.use_smooth = True


# ---------------- man (ReadyPlayerMe) ----------------
def build_man(bvh, frames=None, loc=(0.55, 0.50, 0.0), rot=0.0):
    objs = import_glb(A / "skf/casual_man/source/radyplayer me casual man.glb")
    arm = next(o for o in objs if o.type == "ARMATURE")
    for o in objs:
        if o.type != "MESH":
            continue
        n = o.name.lower()
        if "glasses" in n:
            o.hide_render = o.hide_viewport = True
        for m in o.data.materials:
            if not m or not m.node_tree:
                continue
            for nd in m.node_tree.nodes:
                if nd.type == "TEX_IMAGE" and nd.image:
                    fn = nd.image.filepath.lower() + nd.image.name.lower()
                    if "top" in fn and "-d" in fn or ("top" in n and nd.image.name.lower().endswith("d_12.jpeg")):
                        nd.image = bpy.data.images.load(str(A / "skf/casual_man/textures/top_white.jpg"))
                    elif "bottom" in fn and ("-d" in fn or "d_8" in fn):
                        nd.image = bpy.data.images.load(str(A / "skf/casual_man/textures/bottom_denim.jpg"))
    root = root_of(objs)
    RT.apply_bvh_rpm(arm, str(bvh), SC, 1, frames=frames, hold_root=True)
    head = next((o for o in objs if o.type == "MESH" and o.name.startswith("Wolf3D_Head")), None)
    eyes = [o for o in objs if o.type == "MESH" and o.name.startswith("Eye")]
    if head:
        photo_face(head, eyes)
    for o in objs:
        if o.type == "MESH" and (o.name.startswith("Eye") or o.name.startswith("Wolf3D_Teeth")):
            o.hide_render = o.hide_viewport = True
    for r in root:
        r.location = loc
        r.rotation_mode = "QUATERNION"
        r.rotation_quaternion = Euler((0, 0, math.radians(rot))).to_quaternion() @ r.rotation_quaternion
    return arm, objs


def photo_face(head, eyes=()):
    """Planar-map the Flow face crop onto the front of the RPM head, aligned by the eye line.
    Crop facts (downloads/lowpoly_faces/crop): eye line 0.449 from the top, eye spacing 0.387 of the width,
    aspect w/h 0.696. The RPM eye meshes give the eye centres."""
    bpy.context.view_layer.update()
    me, mw = head.data, head.matrix_world
    if eyes:
        cs = []
        for e in eyes:
            ps = [e.matrix_world @ v.co for v in e.data.vertices]
            cs.append(sum(ps, Vector()) / len(ps))
        ex = abs(cs[0].x - cs[1].x)
        ez = (cs[0].z + cs[1].z) / 2
        cx = (cs[0].x + cs[1].x) / 2
    else:
        ex, ez, cx = 0.066, 1.724, 0.0
    W = ex / 0.387
    H = W / 0.696
    top = ez + 0.449 * H
    bot = top - H
    sel = []
    for p in me.polygons:
        n = (mw.to_3x3() @ p.normal).normalized()
        c = mw @ p.center
        if n.y < -0.2 and bot <= c.z <= top and abs(c.x - cx) <= W / 2:
            sel.append(p)
    uvl = me.uv_layers.new(name="FaceUV")
    for p in sel:
        for li in p.loop_indices:
            a = mw @ me.vertices[me.loops[li].vertex_index].co
            uvl.data[li].uv = ((a.x - cx) / W + 0.5, (a.z - bot) / H)
    m = bpy.data.materials.new("PhotoFace")
    m.use_nodes = True
    nt = m.node_tree
    img = nt.nodes.new("ShaderNodeTexImage")
    img.image = bpy.data.images.load(str(FACE))
    img.extension = "EXTEND"
    uvn = nt.nodes.new("ShaderNodeUVMap")
    uvn.uv_map = "FaceUV"
    nt.links.new(uvn.outputs["UV"], img.inputs["Vector"])
    nt.links.new(img.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
    nt.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.7
    me.materials.append(m)
    idx = len(me.materials) - 1
    for p in sel:
        p.material_index = idx


# ---------------- cat ----------------
def tabby_material(m):
    """Ref-like grey-brown mackerel tabby: recoloured painted texture where the source was ginger, procedural
    stripes (Generated coords = rest pose, so they do not swim) where the source was white, light paws."""
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    src = next(nd for nd in nt.nodes if nd.type == "TEX_IMAGE" and nd.image and "diffuse" in nd.image.name.lower())
    src.image = bpy.data.images.load(str(A / "skf/bicolor/textures/Diffuse_tabby_ref.png"))
    mask = nt.nodes.new("ShaderNodeTexImage")
    mask.image = bpy.data.images.load(str(A / "skf/bicolor/textures/white_mask.png"))
    mask.image.colorspace_settings.name = "Non-Color"
    if src.inputs["Vector"].links:
        nt.links.new(src.inputs["Vector"].links[0].from_socket, mask.inputs["Vector"])
    tc = nt.nodes.new("ShaderNodeTexCoord")
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type = "BANDS"
    wave.bands_direction = TABBY_AXIS
    wave.inputs["Scale"].default_value = 15.0
    wave.inputs["Distortion"].default_value = 4.5
    wave.inputs["Detail"].default_value = 3.0
    nt.links.new(tc.outputs["Generated"], wave.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.42, (0.33, 0.26, 0.18, 1)
    cr.elements[1].position, cr.elements[1].color = 0.78, (0.55, 0.45, 0.32, 1)
    nt.links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    paw = nt.nodes.new("ShaderNodeMapRange")
    paw.inputs["From Min"].default_value, paw.inputs["From Max"].default_value = 0.10, 0.22
    paw.inputs["To Min"].default_value, paw.inputs["To Max"].default_value = 0.0, 1.0
    nt.links.new(sep.outputs[TABBY_UP], paw.inputs["Value"])
    head = nt.nodes.new("ShaderNodeMapRange")          # no procedural stripes on the head end
    head.inputs["From Min"].default_value, head.inputs["From Max"].default_value = HEAD_FROM
    head.inputs["To Min"].default_value, head.inputs["To Max"].default_value = 0.0, 1.0
    nt.links.new(sep.outputs[TABBY_AXIS], head.inputs["Value"])
    f1 = nt.nodes.new("ShaderNodeMath")
    f1.operation = "MULTIPLY"
    nt.links.new(mask.outputs["Color"], f1.inputs[0])
    nt.links.new(paw.outputs["Result"], f1.inputs[1])
    fac = nt.nodes.new("ShaderNodeMath")
    fac.operation = "MULTIPLY"
    nt.links.new(f1.outputs[0], fac.inputs[0])
    nt.links.new(head.outputs["Result"], fac.inputs[1])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    nt.links.new(fac.outputs[0], mix.inputs["Factor"])
    nt.links.new(src.outputs["Color"], mix.inputs["A"])
    nt.links.new(ramp.outputs["Color"], mix.inputs["B"])
    nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    if not PROC_STRIPES:
        nt.links.new(src.outputs["Color"], bsdf.inputs["Base Color"])


TABBY_AXIS, TABBY_UP = "Y", "Z"
PROC_STRIPES = False   # procedural stripes on the white fur looked fake in close-ups
HEAD_FROM = (0.10, 0.17)   # Generated Y: head end -> 0 (no stripes), body -> 1


def build_cat(loc, rot_deg, length=1.0, look_at=None):
    """rot_deg 0 = facing -Y (towards a camera in front)."""
    objs = import_glb(A / "skf/bicolor/source/bicolor Cat.glb")
    arm = next(o for o in objs if o.type == "ARMATURE")
    done = set()
    for o in objs:
        if o.type == "MESH":
            for m in o.data.materials:
                if m and m.node_tree and m.name not in done and "diffuse" in m.name.lower():
                    tabby_material(m)
                    done.add(m.name)
    act = bpy.data.actions.get("Animation")
    arm.animation_data_create()
    if act:
        arm.animation_data.action = act
        if act.slots:
            arm.animation_data.action_slot = act.slots[0]
    root = root_of(objs)
    k = length / 0.82
    for r in root:
        r.scale = r.scale * k
        r.location = loc
        r.rotation_mode = "XYZ"
        r.rotation_euler.z = math.radians(rot_deg)
    if look_at is not None:
        tgt = bpy.data.objects.new("cat_look", None)
        SC.collection.objects.link(tgt)
        tgt.location = look_at
        for bn, infl in (("Wolf_Neck_02SHJnt", 0.35), ("Wolf_Neck_TopSHJnt", 0.7)):
            pb = arm.pose.bones.get(bn)
            if pb:
                c = pb.constraints.new("DAMPED_TRACK")
                c.target = tgt
                c.track_axis = "TRACK_Y"
                c.influence = infl
    return arm, objs


def make_remote():
    """White TV remote 19 x 5 x 2.2 cm, black ring + buttons on top (long axis = local X)."""
    body = box("remote", (0.19, 0.05, 0.022), (0, 0, 0), mat("remote_white", (0.92, 0.92, 0.9), 0.35), bevel=0.008)
    top = box("remote_top", (0.185, 0.046, 0.001), (0, 0, 0.0115), mat("remote_top", rough=0.35, img=TEX / "remote_top.png"))
    me = top.data
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    uv = me.uv_layers.active
    for p in me.polygons:
        for li in p.loop_indices:
            v = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = ((v.x - min(xs)) / (max(xs) - min(xs)), (v.y - min(ys)) / (max(ys) - min(ys)))
    top.parent = body
    return body


def remote_in_hand(remote, arm, bone="RightHand", along=0.075):
    """Glue the remote to the hand bone (Child Of with the inverse computed at frame 1)."""
    SC.frame_set(1)
    bpy.context.view_layer.update()
    pb = arm.pose.bones[bone]
    hw = arm.matrix_world @ pb.matrix
    rot = hw.to_3x3().normalized()
    y = rot @ Vector((0, 1, 0))
    m = Matrix.Translation(hw.translation + y * along) @ (rot @ Matrix.Rotation(math.radians(90), 3, "Z")).to_4x4()
    remote.matrix_world = m
    c = remote.constraints.new("CHILD_OF")
    c.target = arm
    c.subtarget = bone
    c.inverse_matrix = hw.inverted()


def man_look(arm, point, influence=0.9):
    """Turn the man's head toward a world point (Damped Track on the axis that faces forward at rest)."""
    tgt = bpy.data.objects.new("man_look", None)
    SC.collection.objects.link(tgt)
    tgt.location = point
    b = arm.data.bones["Head"]
    rest = (arm.matrix_world.to_3x3().normalized() @ b.matrix_local.to_3x3().normalized())
    fwd = rest.inverted() @ Vector((0, -1, 0))
    ax = max(range(3), key=lambda i: abs(fwd[i]))
    name = "XYZ"[ax]
    track = ("TRACK_" if fwd[ax] > 0 else "TRACK_NEGATIVE_") + name
    for bn, infl in (("Neck", influence * 0.4), ("Head", influence)):
        c = arm.pose.bones[bn].constraints.new("DAMPED_TRACK")
        c.target = tgt
        c.track_axis = track
        c.influence = infl


# ---------------- camera / light / render ----------------
def camera(keys, lens=30):
    """keys: [(frame, loc, look)] linear between keys."""
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    SC.collection.objects.link(cam)
    cam.data.lens = lens
    cam.data.sensor_fit = "VERTICAL"
    cam.data.sensor_height = 24
    SC.camera = cam
    for f, loc, look in keys:
        cam.location = loc
        cam.rotation_euler = (Vector(look) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)
    return cam


def lights():
    w = bpy.data.worlds.new("w")
    SC.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.75, 0.75, 0.72, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 0.40
    for loc, e, size in (((0.4, -2.2, 2.7), 170, 3.0), ((-1.4, 0.75, 1.15), 25, 0.3)):
        l = bpy.data.objects.new("area", bpy.data.lights.new("area", "AREA" if size > 1 else "POINT"))
        l.data.energy = e
        if l.data.type == "AREA":
            l.data.size = size
        l.location = loc
        l.rotation_euler = (Vector((0.2, 0.6, 0.5)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        SC.collection.objects.link(l)


# ---------------- shots ----------------
# frame numbers are local to the shot (1-based, 30 fps)
SHOTS = {
    "face": dict(frames=2, man=("sit_look_1", None), cat=((-0.25, 0.56, SEAT_Z), 20, (0.45, 0.4, 1.3)),
                 cam=[(1, (0.5, -0.35, 1.25), (0.45, 0.45, 1.2))], lens=50),
    # 0.00-0.40 wide: man at the right end of the sofa, cat on the seat facing him
    "s1": dict(frames=12, man=("sit_remote_1", None), cat=((-0.05, 0.52, SEAT_Z), 66, (0.55, 0.35, 1.25)),
               cam=[(1, (1.9, -1.55, 2.05), (-0.35, 0.55, 0.55)), (12, (1.75, -1.38, 1.95), (-0.35, 0.55, 0.55))], lens=24),
    # 0.40-1.50 close on the cat in profile, his hand + remote in the bottom-right foreground
    "s2": dict(frames=33, man=("sit_remote_1", None), cat=((-0.05, 0.52, SEAT_Z), 90, (0.55, 0.35, 1.25)),
               cam=[(1, (0.50, -0.20, 0.92), (0.20, 0.52, 0.80)), (33, (0.48, -0.16, 0.91), (0.20, 0.52, 0.81))], lens=30),
    # 1.50-2.00 cat head-on, staring into the lens; remote lying on the seat in front
    "s3": dict(frames=15, man=("sit_remote_1", None), cat=((-0.05, 0.62, SEAT_Z), 0, (-0.05, -0.6, 0.75)),
               cam=[(1, (-0.05, -0.55, 0.90), (-0.05, 0.6, 0.66)), (15, (-0.05, -0.48, 0.89), (-0.05, 0.6, 0.66))], lens=30,
               remote=(-0.08, 0.18, SEAT_Z + 0.012), remote_rot=12),
    # 2.00-3.20 cat next to his hand on the knee, looking up at him
    "s4": dict(frames=36, man=("sit_look_1", None), cat=((0.18, 0.47, SEAT_Z), 70, (0.55, 0.35, 1.3)),
               cam=[(1, (-0.35, -0.42, 0.98), (0.3, 0.45, 0.68)), (36, (-0.3, -0.38, 0.96), (0.3, 0.45, 0.68))], lens=28),
    # 3.20-4.10 cat's POV from below: man looks down at the lens, red "!" pops at 3.6 (overlay later)
    "s5": dict(frames=27, man=("sit_look_1", None), cat=((0.02, 0.50, SEAT_Z), 90, (0.55, 0.45, 1.35)),
               cam=[(1, (0.20, 0.40, 0.86), (0.55, 0.50, 1.40)), (27, (0.20, 0.40, 0.86), (0.55, 0.50, 1.42))], lens=19,
               man_look=(0.20, 0.40, 0.86)),
}

S = SHOTS[SHOT]
build_room()
mname, mframes = S["man"]
import os
mname = os.environ.get("MAN_BVH", mname)
man_arm, man_objs = build_man(KIM / f"{mname}.bvh", frames=mframes)
cat_loc, cat_rot, cat_look = S["cat"]
build_cat(cat_loc, cat_rot, look_at=cat_look)
if S.get("man_look"):
    man_look(man_arm, S["man_look"])
remote = make_remote()
if S.get("remote"):
    remote.location = S["remote"]
    remote.rotation_euler.z = math.radians(S.get("remote_rot", 15))
else:
    remote_in_hand(remote, man_arm)
camera(S["cam"], S.get("lens", 30))
lights()
r = SC.render
r.engine = "BLENDER_EEVEE"
SC.view_settings.view_transform = "Standard"
SC.view_settings.look = "None"
r.resolution_x, r.resolution_y = 1080, 1920
r.resolution_percentage = 50
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
