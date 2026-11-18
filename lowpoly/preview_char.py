"""blender -b -P preview_char.py -- file.glb out.png [action] [frame] : quick front render of a character."""
import math
import sys

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
path, out = args[0], args[1]
action = args[2] if len(args) > 2 else "Idle"
frame = int(args[3]) if len(args) > 3 else 10

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
act = next((a for a in bpy.data.actions if a.name.endswith("|" + action)), None)
if act:
    arm.animation_data_create()
    arm.animation_data.action = act
    if hasattr(arm.animation_data, "action_slot") and act.slots:
        arm.animation_data.action_slot = act.slots[0]
sc = bpy.context.scene
sc.frame_set(frame)
for o in bpy.data.objects:
    if o.type == "MESH" and o.name == "Icosphere":
        o.hide_render = True
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
cam.location = Vector((0, -4.2, 1.0))
cam.rotation_euler = (math.radians(90), 0, 0)
cam.data.lens = 50
sc.camera = cam
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.data.energy = 3
sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(-30))
sc.collection.objects.link(sun)
w = bpy.data.worlds.new("w")
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.75, 0.75, 0.78, 1)
w.node_tree.nodes["Background"].inputs[1].default_value = 0.8
sc.world = w
sc.render.engine = "BLENDER_EEVEE"
sc.render.resolution_x, sc.render.resolution_y = 540, 960
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
