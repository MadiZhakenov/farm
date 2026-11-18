"""Dump rest-pose bones of the GLB character and of a Kimodo BVH (names, parents, world heads/tails).
  blender -b --factory-startup -P lowpoly/probe_rig.py -- char.glb motion.bvh
"""
import sys
import bpy

glb, bvh = sys.argv[sys.argv.index("--") + 1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)


def dump(arm, tag):
    bpy.context.view_layer.update()
    mw = arm.matrix_world
    print(f"== {tag}: {arm.name} bones={len(arm.data.bones)} obj_rot={tuple(round(a, 3) for a in arm.rotation_euler)} scale={tuple(round(s, 3) for s in arm.scale)}")
    for b in arm.data.bones:
        h, t = mw @ b.head_local, mw @ b.tail_local
        print(f"{b.name:28s} parent={b.parent.name if b.parent else '-':22s} head=({h.x:+.3f},{h.y:+.3f},{h.z:+.3f}) tail=({t.x:+.3f},{t.y:+.3f},{t.z:+.3f})")


bpy.ops.import_scene.gltf(filepath=glb)
dump(next(o for o in bpy.data.objects if o.type == "ARMATURE"), "GLB")
before = set(bpy.data.objects)
bpy.ops.import_anim.bvh(filepath=bvh, global_scale=0.01, rotate_mode="NATIVE", update_scene_fps=False, update_scene_duration=False)
src = next(o for o in bpy.data.objects if o not in before and o.type == "ARMATURE")
dump(src, "BVH")
act = src.animation_data.action
print("BVH action frames", tuple(act.frame_range))
