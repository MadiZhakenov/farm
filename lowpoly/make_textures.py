"""Low-res pixel textures for PS1-style rooms (PIL). python make_textures.py -> lowpoly/tex/*.png"""
import random
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "tex"
OUT.mkdir(exist_ok=True)
R = random.Random(7)


def noise(im: Image.Image, amt: int) -> Image.Image:
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b = px[x, y][:3]
            d = R.randint(-amt, amt)
            px[x, y] = (max(0, min(255, r + d)), max(0, min(255, g + d)), max(0, min(255, b + d)))
    return im


def checker(name, c1, c2, n=8, size=64):
    im = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(im)
    s = size // n
    for y in range(n):
        for x in range(n):
            d.rectangle((x * s, y * s, x * s + s - 1, y * s + s - 1), fill=c1 if (x + y) % 2 else c2)
    noise(im, 6).save(OUT / f"{name}.png")


def planks(name, base, size=64):
    im = Image.new("RGB", (size, size), base)
    d = ImageDraw.Draw(im)
    for i in range(0, size, 8):
        tone = tuple(max(0, c - R.randint(0, 25)) for c in base)
        d.rectangle((0, i, size, i + 7), fill=tone)
        d.line((0, i, size, i), fill=tuple(max(0, c - 50) for c in base))
        x = R.randint(0, size)
        d.line((x, i, x, i + 7), fill=tuple(max(0, c - 45) for c in base))
    noise(im, 5).save(OUT / f"{name}.png")


def wallpaper(name, base, dot, size=64):
    im = Image.new("RGB", (size, size), base)
    d = ImageDraw.Draw(im)
    for y in range(0, size, 8):
        for x in range((y // 8) % 2 * 4, size, 8):
            d.point((x, y), fill=dot)
            d.point((x + 1, y), fill=dot)
    noise(im, 4).save(OUT / f"{name}.png")


def windows(name, wall, glass, size=64):
    im = Image.new("RGB", (size, size), wall)
    d = ImageDraw.Draw(im)
    for y in range(4, size, 16):
        for x in range(4, size, 16):
            lit = R.random() < 0.25
            d.rectangle((x, y, x + 8, y + 9), fill=(250, 245, 210) if lit else glass)
    noise(im, 5).save(OUT / f"{name}.png")


def flat(name, c, amt=6, size=32):
    noise(Image.new("RGB", (size, size), c), amt).save(OUT / f"{name}.png")


checker("floor_checker", (70, 70, 74), (215, 215, 210))
planks("floor_wood", (150, 100, 60))
wallpaper("wall_peach", (232, 190, 165), (205, 150, 125))
wallpaper("wall_mint", (175, 215, 195), (140, 185, 165))
flat("wall_lobby", (178, 150, 140))
flat("grass", (85, 150, 60), 14)
flat("asphalt", (85, 85, 90), 10)
windows("building_blue", (70, 110, 170), (40, 60, 95))
windows("building_brick", (165, 90, 70), (60, 70, 90))
flat("metal", (160, 162, 168), 4)
print("ok", sorted(p.name for p in OUT.glob("*.png")))
