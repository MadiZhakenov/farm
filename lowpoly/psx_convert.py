"""Turn any downloaded model into a PS1-style asset (docs/PS1_LOOK.md).
  blender -b --factory-startup -P lowpoly/psx_convert.py -- IN.(glb|gltf|fbx|obj) OUT.blend [--tris 1500] [--tex 128] [--colors 256]
- geometry: collapse-decimated to about --tris triangles in total (shared out by each mesh's size), seams welded,
  flat-ish look kept (auto smooth off),
- textures: base colour only (no normal / roughness / metal maps: PS1 had none), downscaled to --tex px,
  quantised to --colors (16 = 4-bit CLUT, 256 = 8-bit CLUT), 'Closest' filtering,
- materials: rough 1, no specular / metal (matte, vertex-lit look).
Rigs and animations are kept (the decimate keeps vertex groups).
"""
import os
import sys
from pathlib import Path

import bpy
import numpy as np

a = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = Path(a[0]), Path(a[1])


def opt(name, default):
    return type(default)(a[a.index(name) + 1]) if name in a else default


TRIS, TEX, COLORS = opt("--tris", 1500), opt("--tex", 128), opt("--colors", 256)

bpy.ops.wm.read_factory_settings(use_empty=True)
ext = SRC.suffix.lower()
if ext in (".glb", ".gltf"):
    bpy.ops.import_scene.gltf(filepath=str(SRC))
elif ext == ".fbx":
    bpy.ops.import_scene.fbx(filepath=str(SRC))
elif ext == ".obj":
    bpy.ops.wm.obj_import(filepath=str(SRC))
else:
    raise SystemExit(f"unsupported: {ext}")

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
n0 = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in meshes)
ratio = min(1.0, TRIS / max(1, n0))
import bmesh
for o in meshes:
    if o.data.shape_keys:
        o.shape_key_clear()
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5 * max(o.dimensions) if max(o.dimensions) else 1e-6)
    bm.to_mesh(o.data)
    bm.free()
    if ratio < 1.0:
        d = o.modifiers.new("psx_dec", "DECIMATE")
        d.ratio = max(ratio, 8 / max(8, len(o.data.polygons)))          # never collapse small parts to nothing
        d.use_collapse_triangulate = True
        with bpy.context.temp_override(object=o, active_object=o):
            bpy.ops.object.modifier_apply(modifier="psx_dec")
n1 = sum(len(o.data.polygons) for o in meshes)


def psx_image(img):
    """downscale + palette-quantise a texture in place (PIL is not in Blender: numpy median-cut-ish via uniform bins)."""
    w, h = img.size
    if w == 0 or h == 0:
        return
    s = min(1.0, TEX / max(w, h))
    nw, nh = max(8, int(w * s)), max(8, int(h * s))
    if (nw, nh) != (w, h):
        img.scale(nw, nh)
    px = np.array(img.pixels[:], dtype=np.float32).reshape(nh, nw, 4)
    rgb = px[..., :3].reshape(-1, 3)
    k = min(COLORS, len(rgb))                                     # CLUT: k-means palette fitted to this texture
    rng = np.random.default_rng(0)
    pal = rgb[rng.choice(len(rgb), k, replace=False)].copy()
    for _ in range(8):
        idx = np.empty(len(rgb), np.int32)
        for i in range(0, len(rgb), 4096):
            d = ((rgb[i:i + 4096, None, :] - pal[None]) ** 2).sum(-1)
            idx[i:i + 4096] = d.argmin(1)
        for c in range(k):
            m = idx == c
            if m.any():
                pal[c] = rgb[m].mean(0)
    pal = np.floor(pal * 31 + 0.5) / 31                           # palette entries are RGB555
    px[..., :3] = pal[idx].reshape(nh, nw, 3)
    img.pixels = px.reshape(-1).tolist()
    img.pack()


done = set()
for m in bpy.data.materials:
    if not m.use_nodes:
        continue
    nt = m.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        continue
    for inp in ("Normal", "Roughness", "Metallic"):                  # PS1: colour only
        for l in list(bsdf.inputs[inp].links):
            nt.links.remove(l)
    bsdf.inputs["Roughness"].default_value = 1.0
    bsdf.inputs["Metallic"].default_value = 0.0
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.0
    for n in nt.nodes:
        if n.type == "TEX_IMAGE" and n.image:
            n.interpolation = "Closest"
            if n.image.name not in done and any(l.to_node == bsdf and l.to_socket.name == "Base Color" for l in n.outputs["Color"].links):
                psx_image(n.image)
                done.add(n.image.name)
for o in meshes:
    o.data.shade_flat() if hasattr(o.data, "shade_flat") else None
OUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT.resolve()))
print(f"PSX {SRC.name}: tris {n0} -> {n1}, textures {len(done)} at <= {TEX}px, saved {OUT}")
