"""Render 4 views (3/4, side, front, top-3/4) of every mesh in a .blend for quick model checks (EEVEE, flat light).
  blender -b -P lowpoly/preview_blend.py -- model.blend out_prefix [frame]
"""
import math
import sys

import bpy
from mathutils import Vector

blend, out = sys.argv[sys.argv.index("--") + 1:][:2]
frame = int(sys.argv[sys.argv.index("--") + 3]) if len(sys.argv) > sys.argv.index("--") + 3 else 1
bpy.ops.wm.open_mainfile(filepath=blend)
SC = bpy.context.scene
SC.frame_set(frame)
dg = bpy.context.evaluated_depsgraph_get()
pts = []
for o in SC.objects:
    if o.type == "MESH" and not o.hide_render:
        ev = o.evaluated_get(dg)
        m = ev.to_mesh()
        pts += [o.matrix_world @ v.co for v in m.vertices]
        ev.to_mesh_clear()
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
c, size = (lo + hi) / 2, (hi - lo).length
import os
if os.environ.get("FOCUS"):                     # FOCUS="x,y,z,size" frames a detail (e.g. the head)
    fx, fy, fz, fs = (float(v) for v in os.environ["FOCUS"].split(","))
    c, size = Vector((fx, fy, fz)), fs
cam = bpy.data.objects.new("pcam", bpy.data.cameras.new("pcam"))
SC.collection.objects.link(cam)
SC.camera = cam
cam.data.lens = 50
w = bpy.data.worlds.new("w")
SC.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.8, 0.8, 0.82, 1)
w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
sun = bpy.data.objects.new("psun", bpy.data.lights.new("psun", "SUN"))
sun.data.energy = 2.0
sun.rotation_euler = (math.radians(45), 0, math.radians(-30))
SC.collection.objects.link(sun)
r = SC.render
r.engine = "BLENDER_EEVEE"
SC.view_settings.view_transform = "Standard"
r.resolution_x, r.resolution_y = 600, 600
for name, (az, el) in {"34": (-40, 15), "side": (90, 5), "front": (0, 8), "top": (-30, 50)}.items():
    a, e = math.radians(az), math.radians(el)
    d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    cam.location = c + d * size * 1.35
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    r.filepath = f"{out}_{name}.png"
    bpy.ops.render.render(write_still=True)
