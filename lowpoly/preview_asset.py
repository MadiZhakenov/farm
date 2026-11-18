"""Quick 3/4 + front preview of a GLB (EEVEE-free: Workbench, texture colours) and a list of its animations.
  blender -b --factory-startup -P lowpoly/preview_asset.py -- model.glb out.png [action_name frame]
"""
import math
import sys

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
glb, out = args[0], args[1]
act_name = args[2] if len(args) > 2 else None
act_frame = int(args[3]) if len(args) > 3 else 10
bpy.ops.wm.read_factory_settings(use_empty=True)
SC = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=glb)
arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
print("ACTIONS", [a.name for a in bpy.data.actions])
print("BONES", len(arms[0].data.bones) if arms else 0, [b.name for b in arms[0].data.bones][:80] if arms else [])
if arms and act_name:
    act = next((a for a in bpy.data.actions if act_name.lower() in a.name.lower()), None)
    if act:
        arms[0].animation_data_create()
        arms[0].animation_data.action = act
        if hasattr(arms[0].animation_data, "action_slot") and act.slots:
            arms[0].animation_data.action_slot = act.slots[0]
        SC.frame_set(act_frame)
bpy.context.view_layer.update()
pts = []
for o in bpy.data.objects:
    if o.type == "MESH" and not o.hide_render:
        ev = o.evaluated_get(bpy.context.evaluated_depsgraph_get())
        me = ev.to_mesh()
        pts += [o.matrix_world @ v.co for v in me.vertices]
        ev.to_mesh_clear()
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
c, size = (lo + hi) / 2, (hi - lo).length
print("BBOX", tuple(round(v, 3) for v in lo), tuple(round(v, 3) for v in hi))
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
SC.collection.objects.link(cam)
SC.camera = cam
cam.data.lens = 50
r = SC.render
r.engine = "BLENDER_WORKBENCH"
SC.display.shading.light = "STUDIO"
SC.display.shading.color_type = "TEXTURE"
r.resolution_x, r.resolution_y = 512, 512
r.film_transparent = False
w = bpy.data.worlds.new("w"); SC.world = w; w.color = (0.75, 0.75, 0.78)
shots = []
for ang in (-35, 0, 90):
    a = math.radians(ang)
    d = Vector((math.sin(a), -math.cos(a), 0.35)).normalized()
    cam.location = c + d * size * 1.5
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    p = out.replace(".png", f"_{ang}.png")
    r.filepath = p
    bpy.ops.render.render(write_still=True)
    shots.append(p)
print("SHOTS", shots)
