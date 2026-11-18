"""blender -b -P inspect_glb.py -- file.glb : armature, bones, actions, meshes."""
import sys

import bpy

path = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)
for o in bpy.data.objects:
    print("OBJ", o.type, o.name, [round(v, 2) for v in o.dimensions], "mats", [m.name for m in getattr(o.data, "materials", [])] if o.type == "MESH" else "")
for a in bpy.data.armatures:
    print("ARM", a.name, len(a.bones), [b.name for b in a.bones])
for act in bpy.data.actions:
    print("ACT", act.name, [round(x) for x in act.frame_range])
for m in bpy.data.materials:
    print("MAT", m.name)
for i in bpy.data.images:
    print("IMG", i.name, i.size[:])
