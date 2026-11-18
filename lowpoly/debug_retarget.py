"""Compare bone directions source BVH vs retargeted rig at a few frames.
  blender -b --factory-startup -P lowpoly/debug_retarget.py -- char.glb motion.bvh
"""
import importlib.util
import sys
from pathlib import Path

import bpy

glb, bvh = sys.argv[sys.argv.index("--") + 1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
SC = bpy.context.scene
spec_ = importlib.util.spec_from_file_location("retarget", Path(__file__).resolve().parent / "retarget.py")
rt = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(rt)

bpy.ops.import_scene.gltf(filepath=glb)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
rt.apply_bvh(arm, bvh, SC, 1)
before = set(bpy.data.objects)
bpy.ops.import_anim.bvh(filepath=bvh, global_scale=0.01, rotate_mode="NATIVE", update_scene_fps=False, update_scene_duration=False)
src = next(o for o in bpy.data.objects if o not in before and o.type == "ARMATURE")

PAIRS = [("UpperArm.L", "LowerArm.L", "LeftArm", "LeftForeArm"),
         ("LowerArm.L", "Wrist.L", "LeftForeArm", "LeftHand"),
         ("UpperLeg.L", "LowerLeg.L", "LeftLeg", "LeftShin"),
         ("LowerLeg.L", "Foot.L", "LeftShin", "LeftFoot"),
         ("Hips", "Head", "Hips", "Head")]
for f in (1, 30, 60, 90):
    SC.frame_set(f)
    out = []
    for ta, tb_, sa, sb_ in PAIRS:
        tw = arm.matrix_world
        dt = (tw @ arm.pose.bones[tb_].head - tw @ arm.pose.bones[ta].head).normalized()
        ds = (src.matrix_world @ src.pose.bones[sb_].head - src.matrix_world @ src.pose.bones[sa].head).normalized()
        out.append(f"{ta}->{tb_}: tgt({dt.x:+.2f},{dt.y:+.2f},{dt.z:+.2f}) src({ds.x:+.2f},{ds.y:+.2f},{ds.z:+.2f}) dot={dt.dot(ds):+.2f}")
    print(f"--- frame {f}")
    print("\n".join(out))
    hb = arm.matrix_world @ arm.pose.bones["Body"].head
    hs = src.matrix_world @ src.pose.bones["Hips"].head
    print(f"body {tuple(round(v, 2) for v in hb)}  src hips {tuple(round(v, 2) for v in hs)}")
