"""'Elevator cable' 37 s low-poly short, Mr omi pipeline (Characters_psx + Kimodo + code-built sets).
  blender -b --factory-startup -P lowpoly/omi_story.py -- OUT_DIR SHOT [SHOT ...]   (SHOT = s01..s12 or all)
Shots follow the voice-over word times (downloads/omi_story/words.json). Frames go to OUT_DIR/sNN/f_####.png
at the internal (PS1) resolution; lowpoly/omi_story_compose.py does the PSX post, text and audio.
"""
import importlib.util
import math
import os
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector

FARM = Path(__file__).resolve().parent.parent
_s = importlib.util.spec_from_file_location("omi_kit", FARM / "lowpoly/omi_kit.py")
K = importlib.util.module_from_spec(_s)
_s.loader.exec_module(K)

args = sys.argv[sys.argv.index("--") + 1:]
OUT = Path(args[0])
WANT = args[1:] or ["all"]
KS = FARM / "output/_work/lowpoly/kimodo/story"
HERO_TEX = FARM / "output/_work/lowpoly/omi/tex/main_red_black.png"
RES = int(os.environ.get("RES_PCT", "25"))        # 270x480 internal, x4 nearest = 1080x1920 (PS1 recipe)
FPS = 30
# shot: (start s, end s)
SHOTS = {"s01": (0.0, 2.0), "s02": (2.0, 5.3), "s03": (5.3, 9.1), "s04": (9.1, 12.2), "s05": (12.2, 15.0),
         "s06": (15.0, 18.5), "s07": (18.5, 22.1), "s08": (22.1, 24.0), "s09": (24.0, 28.1), "s10": (28.1, 30.2),
         "s11": (30.2, 32.5), "s12": (32.5, 37.0)}


def nframes(s):
    a, b = SHOTS[s]
    return int(round((b - a) * FPS))


# ---------------- sets ----------------
def cabin(flicker=None, shake=0.0, n=60):
    """Elevator car interior 1.6 x 1.5 x 2.3 m, origin at floor centre, back wall at +Y, camera side open."""
    steel = K.photo_mat("steel", "metal_plate.jpg", rough=0.5, tint=(1.25, 1.3, 1.4))
    floor = K.photo_mat("rubber", "rubber_tiles.jpg", tint=(0.6, 0.6, 0.62))
    K.box("floor", (1.6, 1.5, 0.04), (0, 0, -0.02), floor, uv_scale=0.5)
    K.box("back", (1.6, 0.04, 2.3), (0, 0.77, 1.15), steel, uv_scale=1.0)
    for sx in (-1, 1):
        K.box(f"side{sx}", (0.04, 1.6, 2.3), (0.82 * sx, 0, 1.15), steel, uv_scale=1.0)
    K.box("ceiling", (1.7, 1.6, 0.04), (0, 0, 2.32), K.photo_mat("ceil", "grey_plaster.jpg"), uv_scale=1.0)
    panel = K.box("light_panel", (1.0, 0.8, 0.02), (0, 0.1, 2.29), K.mat_col("lightpanel", (1.0, 0.97, 0.88), emit=1.2))
    K.cyl("rail", 0.02, (-0.7, 0.70, 0.95), (0.7, 0.70, 0.95), K.mat_col("rail", (0.75, 0.75, 0.77), rough=0.2, metal=1))
    K.box("buttons", (0.02, 0.22, 0.42), (0.79, -0.35, 1.25), K.mat_col("btnpanel", (0.2, 0.2, 0.22), rough=0.4))
    for i in range(6):
        K.box(f"btn{i}", (0.01, 0.05, 0.05), (0.775, -0.40 + (i % 2) * 0.1, 1.10 + (i // 2) * 0.1),
              K.mat_col(f"btn{i}", (1.0, 0.75, 0.2) if i == 4 else (0.85, 0.85, 0.85), emit=1.5 if i == 4 else 0))
    K.world((0.4, 0.4, 0.42), 0.2)
    key = K.light("AREA", (0, 0.1, 2.2), 80, size=1.0, color=(1, 0.97, 0.92))
    if flicker:                                          # power cut flicker: list of (frame, on 0/1)
        mp = panel.data.materials[0].node_tree.nodes["Principled BSDF"].inputs["Emission Strength"]
        for f, on in flicker:
            key.data.energy = 80 * on + 3
            key.data.keyframe_insert("energy", frame=f)
            mp.default_value = 1.2 * on
            mp.keyframe_insert("default_value", frame=f)
        for fc in K.RT._fcurves(key.data.animation_data.action):
            for kp in fc.keyframe_points:
                kp.interpolation = "CONSTANT"
    return key


def shake_cam(cam, f0, f1, amp, seed=0, every=2):
    rnd = random.Random(seed)
    base = cam.location.copy()
    for f in range(f0, f1 + 1, every):
        cam.location = base + Vector((rnd.uniform(-amp, amp), rnd.uniform(-amp, amp) * 0.3, rnd.uniform(-amp, amp)))
        cam.keyframe_insert("location", frame=f)
    cam.location = base


def hero(bvh, loc=(0, 0.15), rot=0, frames=None, start=1):
    return K.person(K.MALE / "Character_06.fbx", KS / bvh, loc, rot_deg=rot, height=1.80, tex=HERO_TEX,
                    frames=frames, start=start, name="hero")


def shaft_walls(height=70.0, w=2.6, d=2.4):
    conc = K.photo_mat("concrete", "concrete_block_wall.jpg", tint=(0.8, 0.8, 0.8))
    rail_m = K.photo_mat("rail_steel", "metal_plate_02.jpg", rough=0.5)
    for sx in (-1, 1):                                    # car guide rails
        K.box(f"guide{sx}", (0.08, 0.12, height), (sx * (w / 2 - 0.06), 0, height / 2), rail_m, uv_scale=1.0)
    for i in range(int(height // 3.3)):                   # real landing doors (Sketchfab lift door, PSX-converted)
        K.append_blend(K.PSX_ASSETS / "elevator_modern.blend", loc=(0, d / 2 + 0.02, height - 3.3 * (i + 1) + 0.15),
                       rot_deg=(0, 0, 0), size=w + 0.4, axis=0)
    K.box("shaft_back", (w, 0.2, height), (0, d / 2 + 0.1, height / 2), conc, uv_scale=2.0)
    K.box("shaft_left", (0.2, d, height), (-w / 2 - 0.1, 0, height / 2), conc, uv_scale=2.0)
    K.box("shaft_right", (0.2, d, height), (w / 2 + 0.1, 0, height / 2), conc, uv_scale=2.0)
    nfl = int(height // 3.3)
    for i in range(nfl):                                  # floor numbers painted on the back wall
        K.text_obj(str(nfl - i), (-0.9, d / 2 - 0.01, height - 2.0 - i * 3.3), 0.45, (0.95, 0.85, 0.2),
                   rot=(90, 0, 0), emit=0.6)
        K.box(f"door_frame{i}", (1.2, 0.05, 0.05), (0.2, d / 2 - 0.02, height - 3.4 - i * 3.3),
              K.mat_col("ledge", (0.25, 0.25, 0.26)))


def car_exterior(z0=0.0):
    steel = K.photo_mat("car_steel", "painted_metal_shutter.jpg", tint=(0.5, 0.52, 0.55))
    car = K.box("car", (1.7, 1.6, 2.5), (0, 0, z0 + 1.25), steel, uv_scale=1.2)
    beam = K.box("crosshead", (1.9, 0.18, 0.18), (0, 0, z0 + 2.6), K.photo_mat("beam", "metal_plate_02.jpg", tint=(0.5, 0.5, 0.5)), uv_scale=0.5)
    beam.parent = car
    beam.matrix_parent_inverse = car.matrix_world.inverted()
    return car


# ---------------- shots ----------------
def s01(n):   # "If your elevator cable snapped" — inside, light flickers, hero nervous
    cabin(flicker=[(1, 1), (24, 0), (27, 1), (33, 0), (35, 1), (44, 0), (46, 1)])
    hero("cab_nervous.bvh", loc=(0.05, 0.25))
    cam = K.camera((0.55, -0.72, 1.55), (0.0, 0.25, 1.35), lens=16)
    shake_cam(cam, 24, n, 0.015, seed=1)


def s02(n):   # "jumping at the last second would not save you" — car drops down the shaft
    shaft_walls()
    car = car_exterior(60.0)
    K.world((0.05, 0.05, 0.06), 0.3)
    for f in range(1, n + 1):
        t = (f - 1) / FPS
        car.location.z = 60.0 - 0.5 * 9.81 * t * t                 # free fall
        car.keyframe_insert("location", frame=f)
    for i, x in enumerate((-0.4, -0.15, 0.15, 0.4)):              # snapped cable ends whipping above the car
        c = K.cyl(f"cable_end{i}", 0.012, (x, 0, 2.6), (x + 0.2 * (i - 1.5), 0, 5.0), K.mat_col("cable", (0.1, 0.1, 0.1), metal=1, rough=0.3))
        c.parent = car
    cam = K.camera((2.0, -3.2, 61.5), (0, 0, 61.0), lens=22)
    for f in range(1, n + 1, 3):
        t = (f - 1) / FPS
        z = 60.0 - 0.5 * 9.81 * t * t
        K.key_cam(cam, f, (1.9, -4.2, z + 3.4 + 0.5 * t), (0, 0, z + 1.4))
    lamp = K.light("AREA", (0, 0, 0), 900, size=2.5, color=(1, 0.95, 0.85))   # light rides with the camera
    lamp.parent = cam
    lamp.location = (0, 0.6, 0)
    for zl in range(5, 70, 8):
        K.light("POINT", (0.9, -0.9, zl), 120)


def s03(n):   # "your best jump only takes away about 10 km/h" — hero jumps (falling car, shake)
    cabin()
    hero("jump.bvh", loc=(0.0, 0.2), start=1)
    cam = K.camera((0.35, -0.72, 1.6), (0.0, 0.2, 1.25), lens=15)
    shake_cam(cam, 1, n, 0.02, seed=3)


def s04(n):   # "you'd still hit the floor almost as fast" — crash at the pit
    shaft_walls(height=12)
    pit = K.mat_col("buffer", (0.9, 0.75, 0.1))
    for x in (-0.5, 0.5):
        K.cyl(f"buffer{x}", 0.12, (x, 0, 0), (x, 0, 0.5), pit)
    K.box("pit", (2.6, 2.4, 0.1), (0, 0, -0.05), K.mat_col("pitfloor", (0.2, 0.2, 0.2)))
    car = car_exterior(0.0)
    K.world((0.05, 0.05, 0.06), 0.3)
    hit = 22
    for f in range(1, n + 1):
        if f < hit:
            z = 0.5 + (hit - f) * 0.9                                 # ~27 m/s
        else:
            z = 0.5 - 0.25 * math.exp(-(f - hit) / 3.0) * abs(math.sin((f - hit) * 0.9))
        car.location.z = z
        car.keyframe_insert("location", frame=f)
    rnd = random.Random(5)
    dust = K.mat_col("dust", (0.28, 0.26, 0.24), rough=1)
    for i in range(14):                                               # dust puffs after impact
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.06, location=(0, 0, 0.3))
        d = bpy.context.active_object
        d.data.materials.append(dust)
        d.scale = (0.001,) * 3
        d.keyframe_insert("scale", frame=hit - 1)
        d.keyframe_insert("location", frame=hit - 1)
        d.scale = (rnd.uniform(1.5, 3.0),) * 3
        d.location = (rnd.uniform(-1.2, 1.2), rnd.uniform(-1.6, -0.3), rnd.uniform(0.1, 1.2))
        d.keyframe_insert("scale", frame=hit + rnd.randint(8, 20))
        d.keyframe_insert("location", frame=hit + rnd.randint(8, 20))
    K.light("AREA", (0, -1.5, 5), 500, size=3)
    cam = K.camera((1.6, -3.6, 1.6), (0, 0, 1.2), lens=20)
    shake_cam(cam, hit, min(n, hit + 30), 0.08, seed=4, every=1)


def roof_set():
    shaft_walls(height=14)
    car = car_exterior(0.0)
    K.world((0.04, 0.04, 0.05), 0.3)
    K.light("AREA", (0.6, -1.4, 6.0), 280, size=2.0, color=(0.9, 0.95, 1.0))
    xs = [-0.42, -0.30, -0.18, -0.06, 0.06, 0.18, 0.30, 0.42]
    cables = []
    for i, x in enumerate(xs):
        m = K.mat_col(f"cable{i}", (0.12, 0.12, 0.13), metal=1, rough=0.35)
        cables.append(K.cyl(f"cable{i}", 0.014, (x, 0, 2.7), (x, 0, 14), m))
    return car, cables


def glow(cable, f, on, col=(1.0, 0.8, 0.1)):
    b = cable.data.materials[0].node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (*col, 1)
    b.inputs["Emission Strength"].default_value = 6.0 if on else 0.0
    b.inputs["Emission Strength"].keyframe_insert("default_value", frame=f)


def s05(n):   # "But you see, the cable can't really snap" — roof of the car, cables
    roof_set()
    cam = K.camera((1.8, -2.6, 4.2), (0, 0, 3.3), lens=20)
    K.key_cam(cam, 1, (1.8, -2.6, 4.2), (0, 0, 3.3))
    K.key_cam(cam, n, (1.2, -1.9, 4.6), (0, 0, 4.2))


def s06(n):   # "Every elevator hangs on four to eight steel ropes" — light them up one by one
    _, cables = roof_set()
    starts = [int((t - 15.0) * FPS) for t in (16.54, 16.85, 17.14, 17.3, 17.45, 17.6, 17.75, 17.9)]
    for i, c in enumerate(cables):
        glow(c, 1, False)
        glow(c, max(2, starts[i]), True)
    cam = K.camera((1.2, -1.9, 4.6), (0, 0, 4.2), lens=20)
    K.key_cam(cam, 1, (1.2, -1.9, 4.6), (0, 0, 4.4))
    K.key_cam(cam, n, (0.9, -1.6, 5.2), (0, 0, 5.2))


def s07(n):   # "and any one of them can hold the whole car by itself" — all but one fade
    _, cables = roof_set()
    for i, c in enumerate(cables):
        glow(c, 1, True)
        if i != 4:
            c.hide_render = False
            c.keyframe_insert("hide_render", frame=10 + i * 4)
            c.hide_render = True
            c.keyframe_insert("hide_render", frame=11 + i * 4)
    glow(cables[4], 1, True, col=(1.0, 0.85, 0.2))
    cam = K.camera((2.4, -3.4, 2.5), (0, 0, 3.0), lens=18)
    K.key_cam(cam, 1, (2.4, -3.4, 2.5), (0, 0, 3.0))
    K.key_cam(cam, n, (2.8, -4.2, 2.0), (0, 0, 3.4))


# ---- 1854 square ----
def square_set():
    stone = K.photo_mat("stone", "cobblestone_floor_01.jpg")
    K.box("ground", (40, 40, 0.1), (0, 0, -0.05), stone, uv_scale=2.0)
    brick = K.photo_mat("brick", "red_brick_03.jpg")
    rnd = random.Random(8)
    for i in range(7):                                    # old New York facades behind
        h = rnd.uniform(9, 15)
        K.box(f"bldg{i}", (5.5, 4, h), (-16 + i * 5.6, 14 + rnd.uniform(-1, 1), h / 2), brick, uv_scale=2.0)
        for r in range(int(h // 3)):
            for c in range(3):
                K.box(f"win{i}_{r}_{c}", (0.8, 0.05, 1.2), (-17.6 + i * 5.6 + c * 1.6, 11.9, 2 + r * 3),
                      K.mat_col("win", (0.12, 0.13, 0.16), rough=0.3))
    wood = K.photo_mat("wood", "brown_planks_05.jpg")
    K.append_blend(K.PSX_ASSETS / "tower.blend", loc=(0, 3.0, 0), size=9.0, axis=2)   # real wooden tower (Sketchfab)
    plat = K.box("platform", (1.9, 1.6, 0.15), (0, 3.0, 4.0), wood, uv_scale=1.0)
    rope_m = K.mat_col("rope", (0.55, 0.45, 0.30), rough=1)
    rope = K.cyl("rope", 0.03, (0, 3.0, 4.08), (0, 3.0, 9.0), rope_m)
    K.cyl("rope_down", 0.03, (0.2, 3.0, 9.0), (1.25, 2.85, 0.6), rope_m)
    K.world((0.62, 0.74, 0.88), 0.9)
    K.light("SUN", (0, 0, 10), 3.0, rot=(50, 0, 30), color=(1, 0.96, 0.88))
    return plat, rope


def crowd(start=1, gasp_at=None):
    people = [(K.MALE / "Character_03.fbx", "crowd_lookup.bvh", (-1.6, -0.6), 175, 1.76),
              (K.FEMALE / "Character_Female_13.fbx", "crowd_point.bvh", (-0.6, -1.0), 190, 1.65),
              (K.MALE / "Character_04.fbx", "crowd_lookup.bvh", (0.5, -0.8), 170, 1.80),
              (K.MALE / "Character_31.fbx", "crowd_lookup.bvh", (1.5, -0.5), 185, 1.78),
              (K.FEMALE / "Character_30_Female.fbx", "crowd_lookup.bvh", (-2.4, -1.6), 160, 1.66),
              (K.MALE / "Character_16.fbx", "crowd_point.bvh", (2.4, -1.5), 195, 1.79)]
    for i, (fbx, bvh, loc, rot, h) in enumerate(people):
        if gasp_at and i % 2 == 0:
            bvh = "crowd_gasp.bvh"
        K.person(fbx, KS / bvh, loc, rot_deg=rot, height=h, start=start, nod=6 if "lookup" in bvh else 14,
                 name=f"crowd{i}")


def otis(plat_z=4.075):
    return K.person(K.MALE / "Character_32.fbx", KS / "otis_present.bvh", (0, 3.0, plat_z), rot_deg=0, height=1.78,
                    name="otis")


def s08(n):   # "Back in 1854" — wide establishing shot (title is added in compose)
    square_set()
    otis()
    crowd()
    cam = K.camera((0, -9.5, 2.0), (0, 2.0, 4.5), lens=22)
    K.key_cam(cam, 1, (0, -9.5, 2.0), (0, 2.0, 4.5))
    K.key_cam(cam, n, (0, -8.6, 2.1), (0, 2.0, 4.7))


def s09(n):   # "Elisha Otis stood on a platform high above a crowd in New York"
    square_set()
    otis()
    crowd()
    cam = K.camera((0.8, -4.0, 1.4), (0, 3.0, 4.9), lens=20)
    K.key_cam(cam, 1, (0.8, -4.0, 1.4), (0, 3.0, 4.9))
    K.key_cam(cam, n, (0.4, -3.3, 1.5), (0, 3.0, 5.2))


def s10(n):   # "and had the only rope cut" — helper chops the rope at the post
    square_set()
    otis()
    arm, roots, meshes = K.person(K.MALE / "Character_14.fbx", KS / "axe_chop.bvh", (1.9, 2.4), rot_deg=-60,
                                  height=1.80, name="helper")
    handle, _ = K.append_blend(K.PSX_ASSETS / "axe.blend", size=0.75, axis=2)          # real low-poly axe (Sketchfab)
    handle.parent = arm                                  # axe rides on the right hand bone
    handle.parent_type = "BONE"
    handle.parent_bone = "RightHand"
    handle.matrix_parent_inverse.identity()
    s = handle.scale.x / arm.scale.x
    handle.scale = (s, s, s)
    handle.location = (0, -0.02 / arm.scale.x, 0)
    handle.rotation_euler = (0, 0, 0)
    cam = K.camera((3.4, 0.4, 1.4), (1.4, 2.9, 1.2), lens=24)


def s11(n):   # "It dropped a few inches and stopped" — platform jolts, crowd gasps
    plat, rope = square_set()
    oarm, oroots, _ = otis()
    crowd(gasp_at=1)
    drop_f, stop_f = 6, 10
    objs = [plat] + oroots
    for o in objs:
        o.keyframe_insert("location", frame=drop_f)
        o.location.z -= 0.15
        o.keyframe_insert("location", frame=stop_f)
    rope.scale.z = 1.0
    cam = K.camera((0.6, -4.6, 1.5), (0, 3.0, 4.6), lens=22)
    shake_cam(cam, stop_f, stop_f + 10, 0.03, seed=11, every=1)


def s12(n):   # "So the only thing likely to break ... is your ankle, from the jump"
    cabin()
    hero("jump_ankle.bvh", loc=(0.0, 0.2))
    cam = K.camera((0.45, -0.72, 1.35), (0.0, 0.2, 1.0), lens=16)


def run(shot):
    n = nframes(shot)
    K.reset(FPS, n)
    globals()[shot](n)
    K.render_setup(RES)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, n
    if len(K.ACTORS) > 1:
        K.check_overlaps(1, n)
    d = OUT / shot
    d.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(d / f"{shot}.blend"))
    if os.environ.get("STILL"):
        for f in (1, n // 2, n):
            sc.frame_set(f)
            sc.render.filepath = str(d / f"still_{f:04d}.png")
            bpy.ops.render.render(write_still=True)
    else:
        sc.render.filepath = str(d / "f_")
        bpy.ops.render.render(animation=True)
    print("SHOT", shot, n, "frames ->", d)


for s in (list(SHOTS) if "all" in WANT else WANT):
    run(s)
