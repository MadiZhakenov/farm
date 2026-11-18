"""
Low-poly PS1-style shot in Blender from a JSON spec (rendered frame by frame).
  blender -b --factory-startup -P lowpoly/shot.py -- spec.json

spec = {
  "out": "abs/dir/frames", "frames": 72, "fps": 24, "res": [540, 960], "engine": "WORKBENCH" | "BLENDER_EEVEE",
  "set": "lobby" | "bedroom" | "street",
  "actors": [{"glb": "...", "action": "Idle", "loc": [0, 0, 0], "rot": 0,
              "bvh": null,                       # Kimodo motion (retarget.py) instead of the built-in action
              "faces": [[0, "neutral.png"], [30, "shock.png"]]}],   # face photo per frame (swap = expression)
  "camera": {"loc": [0, -5, 1.5], "look": [0, 0, 1.1], "lens": 32}
}
"""
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
TEX = ROOT / "tex"
spec = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
bpy.ops.wm.read_factory_settings(use_empty=True)
SC = bpy.context.scene
MATS: dict = {}


# ---------- materials / geometry ----------
def tex_mat(name: str, tex: str | None = None, color=(0.8, 0.8, 0.8), emit: float = 0.0) -> bpy.types.Material:
    key = (name, tex, color)
    if key in MATS:
        return MATS[key]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.9
    if tex:
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = bpy.data.images.load(str(TEX / f"{tex}.png"), check_existing=True)
        n.interpolation = "Closest"
        nt.links.new(n.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = (*color, 1)
        m.diffuse_color = (*color, 1)
    if emit:
        bsdf.inputs["Emission Color"].default_value = (*color, 1)
        bsdf.inputs["Emission Strength"].default_value = emit
    MATS[key] = m
    return m


def box_uv(ob: bpy.types.Object, tile: float) -> None:
    """Box mapping by dominant normal axis in world units: texture repeats every `tile` metres."""
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    uv = bm.loops.layers.uv.verify()
    mw = ob.matrix_world
    for f in bm.faces:
        n = (mw.to_3x3() @ f.normal)
        ax = max(range(3), key=lambda i: abs(n[i]))
        for lp in f.loops:
            p = mw @ lp.vert.co
            a, b = [(p.y, p.z), (p.x, p.z), (p.x, p.y)][ax]
            lp[uv].uv = (a / tile, b / tile)
    bm.to_mesh(me)
    bm.free()


def box(name, size, loc, mat, tile=1.0, rot=0.0) -> bpy.types.Object:
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    SC.collection.objects.link(ob)
    ob.scale = size
    ob.location = loc
    ob.rotation_euler = (0, 0, math.radians(rot))
    bpy.context.view_layer.update()
    me.transform(ob.matrix_basis)
    ob.matrix_basis.identity()
    ob.location = (0, 0, 0)
    me.materials.append(mat)
    box_uv(ob, tile)
    return ob


def cyl(name, r, h, loc, mat, verts=8) -> bpy.types.Object:
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=verts, radius1=r, radius2=r, depth=h)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    SC.collection.objects.link(ob)
    ob.location = (loc[0], loc[1], loc[2] + h / 2)
    me.materials.append(mat)
    return ob


def blob(name, r, loc, mat, sub=1) -> bpy.types.Object:
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=r)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    SC.collection.objects.link(ob)
    ob.location = loc
    me.materials.append(mat)
    return ob


# ---------- sets ----------
def room(floor_tex, wall_tex, w=7.0, d=6.0, h=3.2):
    box("floor", (w, d + 4, 0.1), (0, 1, -0.05), tex_mat("floor", floor_tex), tile=8.0)
    box("back", (w, 0.1, h), (0, d / 2, h / 2), tex_mat("wall", wall_tex), tile=1.2)
    box("left", (0.1, d + 4, h), (-w / 2, 1, h / 2), tex_mat("wall", wall_tex), tile=1.2)
    box("right", (0.1, d + 4, h), (w / 2, 1, h / 2), tex_mat("wall", wall_tex), tile=1.2)
    box("ceil", (w, d + 4, 0.1), (0, 1, h + 0.05), tex_mat("ceil", color=(0.92, 0.92, 0.9)))
    blob("lamp", 0.18, (0, 0.5, h - 0.25), tex_mat("lamp", color=(1, 0.97, 0.85), emit=4))


def set_lobby():
    room("floor_checker", "wall_lobby")
    metal = tex_mat("metal", "metal")
    red = tex_mat("red", color=(0.75, 0.08, 0.06))
    for x in (-1.6, 1.6):
        box("lift", (1.2, 0.12, 2.3), (x, 2.95, 1.15), metal, tile=0.6)
        box("lift_gap", (0.03, 0.14, 2.3), (x, 2.95, 1.15), tex_mat("dark", color=(0.1, 0.1, 0.12)))
        box("lift_num", (0.36, 0.08, 0.18), (x, 2.9, 2.55), red)
    yel = tex_mat("yellow", color=(0.95, 0.75, 0.05))
    box("sign_a", (0.42, 0.06, 0.7), (1.0, 0.45, 0.33), yel, rot=10).rotation_euler.x = math.radians(12)
    box("sign_b", (0.42, 0.06, 0.7), (1.0, 0.62, 0.33), yel, rot=10).rotation_euler.x = math.radians(-12)
    cyl("pot", 0.22, 0.45, (-2.7, 2.4, 0), tex_mat("pot", color=(0.45, 0.25, 0.15)))
    blob("plant", 0.45, (-2.7, 2.4, 0.95), tex_mat("leaf", color=(0.15, 0.45, 0.15)))


def set_bedroom():
    room("floor_wood", "wall_peach")
    box("bed", (2.0, 2.4, 0.45), (1.6, 1.6, 0.22), tex_mat("bedframe", color=(0.35, 0.22, 0.12)))
    box("mattress", (1.9, 2.3, 0.2), (1.6, 1.6, 0.55), tex_mat("sheet", color=(0.92, 0.92, 0.95)))
    box("blanket", (1.95, 1.5, 0.08), (1.6, 1.15, 0.68), tex_mat("blanket", color=(0.25, 0.4, 0.75)))
    box("pillow", (1.2, 0.45, 0.16), (1.6, 2.5, 0.72), tex_mat("sheet", color=(0.92, 0.92, 0.95)))
    box("stand", (0.5, 0.45, 0.55), (-0.1, 2.6, 0.27), tex_mat("bedframe", color=(0.35, 0.22, 0.12)))
    cyl("lampbase", 0.1, 0.35, (-0.1, 2.6, 0.55), tex_mat("lampb", color=(0.9, 0.85, 0.7)))
    box("window", (1.4, 0.06, 1.2), (-1.6, 2.97, 1.7), tex_mat("sky", color=(0.55, 0.78, 0.95), emit=1.5))
    box("frame", (0.8, 0.05, 0.55), (1.6, 2.96, 1.9), tex_mat("pic", color=(0.85, 0.6, 0.3)))
    box("rug", (2.2, 1.6, 0.02), (-0.6, 0.6, 0.01), tex_mat("rug", color=(0.7, 0.2, 0.25)))


def set_street():
    w = bpy.data.worlds.new("sky")
    SC.world = w
    w.color = (0.45, 0.7, 0.95)
    box("road", (40, 6, 0.1), (0, 1, -0.05), tex_mat("asphalt", "asphalt"), tile=2)
    box("walk", (40, 3, 0.16), (0, 5.4, 0.0), tex_mat("walk", color=(0.7, 0.7, 0.68)))
    box("grass", (40, 20, 0.1), (0, -12, -0.06), tex_mat("grass", "grass"), tile=3)
    for i, x in enumerate(range(-12, 13, 5)):
        hgt = 7 + (i * 37 % 9)
        box(f"bld{i}", (4.6, 4, hgt), (x, 9, hgt / 2), tex_mat(f"bld{i % 2}", ["building_blue", "building_brick"][i % 2]), tile=3)
    box("car", (1.8, 3.8, 0.7), (-3.2, 1.8, 0.5), tex_mat("car", color=(0.1, 0.3, 0.8)), rot=90)
    box("car_top", (1.5, 2.0, 0.55), (-3.2, 1.8, 1.1), tex_mat("car", color=(0.1, 0.3, 0.8)), rot=90)
    for x in (-4.5, -1.9):
        cyl("wheel", 0.35, 0.3, (x, 1.0, 0.0), tex_mat("tyre", color=(0.05, 0.05, 0.05)))


SETS = {"lobby": set_lobby, "bedroom": set_bedroom, "street": set_street}


# ---------- character ----------
def import_actor(a: dict) -> bpy.types.Object:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=a["glb"])
    new = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in new if o.type == "ARMATURE")
    for o in new:
        if o.type == "MESH" and o.name.startswith("Icosphere"):
            o.hide_render = True
            o.hide_viewport = True
    arm.animation_data_create()
    if a.get("faces"):
        photo_face(arm, new, a["faces"])
    if a.get("bvh"):
        import importlib.util
        spec_ = importlib.util.spec_from_file_location("retarget", ROOT / "retarget.py")
        rt = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(rt)
        rt.apply_bvh(arm, a["bvh"], SC, a.get("bvh_start", 1))   # before placement (needs import frame)
        place(arm, a)
        return arm
    place(arm, a)
    act = next((x for x in bpy.data.actions if x.name.endswith("|" + a.get("action", "Idle"))), None)
    arm.animation_data.action = None
    if act:
        tr = arm.animation_data.nla_tracks.new()
        st = tr.strips.new(act.name, 1, act)
        if hasattr(st, "action_slot") and act.slots:
            st.action_slot = act.slots[0]
        length = act.frame_range[1] - act.frame_range[0]
        st.repeat = max(1.0, spec["frames"] / max(1, length) + 1)
    return arm


def place(arm, a):
    """Spec loc + rot (degrees about Z). glTF armatures use quaternion rotation (Y-up -> Z-up)."""
    from mathutils import Quaternion
    arm.location = a.get("loc", (0, 0, 0))
    arm.rotation_mode = "QUATERNION"
    arm.rotation_quaternion = Quaternion((0, 0, 1), math.radians(a.get("rot", 0))) @ arm.rotation_quaternion


def photo_face(arm, objs, schedule):
    """Front faces of the head get one flat photo (planar UV); swapping the image per frame = expression."""
    head = next(o for o in objs if o.type == "MESH" and "Head" in o.name)
    bpy.context.view_layer.update()
    me = head.data
    mw = head.matrix_world
    zs = [(mw @ v.co).z for v in me.vertices]
    z0, z1 = min(zs), max(zs)
    keep = {i for i, m in enumerate(me.materials) if m and m.name.split(".")[0] in ("Skin", "Eye", "Eyebrows")}
    sel = []
    for p in me.polygons:
        n = (mw.to_3x3() @ p.normal).normalized()
        c = mw @ p.center
        if p.material_index in keep and n.y < -0.25 and c.z > z0 + 0.18 * (z1 - z0):
            sel.append(p)
    pts = [mw @ me.vertices[v].co for p in sel for v in p.vertices]
    xs, zz = [q.x for q in pts], [q.z for q in pts]
    cx, cz = (min(xs) + max(xs)) / 2, (min(zz) + max(zz)) / 2
    w, h = (max(xs) - min(xs)) * 1.04, (max(zz) - min(zz)) * 1.04
    uvl = me.uv_layers.new(name="FaceUV")
    for p in sel:
        for li in p.loop_indices:
            q = mw @ me.vertices[me.loops[li].vertex_index].co
            uvl.data[li].uv = ((q.x - cx) / w + 0.5, (q.z - cz) / h + 0.5)
    me.uv_layers.active = uvl
    uvl.active_render = True
    m = bpy.data.materials.new("PhotoFace")
    m.use_nodes = True
    nt = m.node_tree
    img = nt.nodes.new("ShaderNodeTexImage")
    img.interpolation = "Closest"
    uvn = nt.nodes.new("ShaderNodeUVMap")
    uvn.uv_map = "FaceUV"
    nt.links.new(uvn.outputs["UV"], img.inputs["Vector"])
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.85
    nt.links.new(img.outputs["Color"], bsdf.inputs["Base Color"])
    me.materials.append(m)
    idx = len(me.materials) - 1
    for p in sel:
        p.material_index = idx
    imgs = [(f, bpy.data.images.load(path, check_existing=True)) for f, path in schedule]
    img.image = imgs[0][1]

    def swap(scene, *_):
        cur = imgs[0][1]
        for f, im in imgs:
            if scene.frame_current >= f:
                cur = im
        if img.image != cur:
            img.image = cur
    bpy.app.handlers.frame_change_pre.append(swap)


# ---------- camera, light, render ----------
def camera(c, actors):
    """Static camera (loc + look) or "follow": {"actor": 0, "offset": [x, y, z], "look_z": 0.8, "smooth": 12}
    -> baked keyframes that trail the actor's Body bone (smoothed, like a handheld follow-cam)."""
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    SC.collection.objects.link(cam)
    cam.data.lens = c.get("lens", 32)
    cam.data.sensor_fit = "VERTICAL"
    SC.camera = cam
    fol = c.get("follow")
    if not fol:
        cam.location = c.get("loc", (0, -5, 1.5))
        d = Vector(c.get("look", (0, 0, 1.1))) - cam.location
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        return
    arm = actors[fol.get("actor", 0)]
    bone = fol.get("bone", "Body")
    pts = []
    for f in range(1, spec["frames"] + 1):
        SC.frame_set(f)
        pts.append(arm.matrix_world @ arm.pose.bones[bone].head)
    k = int(fol.get("smooth", 12))
    off = Vector(fol.get("offset", (2.4, -2.0, 1.4)))
    look_z = fol.get("look_z", 0.8)
    for i in range(len(pts)):
        win = pts[max(0, i - k): i + k + 1]
        p = sum(win, Vector()) / len(win)
        tgt = Vector((p.x, p.y, look_z))
        cam.location = tgt + off
        cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
        cam.keyframe_insert("location", frame=i + 1)
        cam.keyframe_insert("rotation_euler", frame=i + 1)


def lights():
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3.2
    sun.data.angle = math.radians(8)
    sun.rotation_euler = (math.radians(48), math.radians(8), math.radians(-28))
    SC.collection.objects.link(sun)
    if not SC.world:
        w = bpy.data.worlds.new("w")
        w.color = (0.55, 0.55, 0.58)
        SC.world = w
    w = SC.world
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (*w.color, 1)
    bg.inputs[1].default_value = 0.9


SETS[spec.get("set", "lobby")]()
ACTORS = [import_actor(a) for a in spec.get("actors", [])]
for m in bpy.data.materials:                           # Workbench shows the viewport colour — copy base colours over
    if m.node_tree and "Principled BSDF" in m.node_tree.nodes:
        bc = m.node_tree.nodes["Principled BSDF"].inputs["Base Color"]
        if not bc.is_linked:
            m.diffuse_color = tuple(bc.default_value)
camera(spec.get("camera", {}), ACTORS)
lights()
r = SC.render
r.engine = {"WORKBENCH": "BLENDER_WORKBENCH", "EEVEE": "BLENDER_EEVEE"}.get(spec.get("engine", "WORKBENCH"), spec.get("engine"))
if r.engine == "BLENDER_WORKBENCH":
    sh = SC.display.shading
    sh.light = "STUDIO"
    sh.color_type = "TEXTURE"
    sh.show_shadows = True
    sh.shadow_intensity = 0.35
    sh.show_cavity = False
    SC.display.render_aa = "OFF"
else:
    r.filter_size = 0.6
r.resolution_x, r.resolution_y = spec.get("res", [540, 960])
r.fps = spec.get("fps", 24)
SC.frame_start, SC.frame_end = 1, spec["frames"]
out = Path(spec["out"]).resolve()
out.mkdir(parents=True, exist_ok=True)
r.filepath = str(out / "f_")
r.image_settings.file_format = "PNG"
if spec.get("still"):
    SC.frame_set(spec["still"])
    r.filepath = str(out / "still.png")
    bpy.ops.render.render(write_still=True)
else:
    bpy.ops.render.render(animation=True)
print("DONE", out)
