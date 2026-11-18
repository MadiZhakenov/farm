# PS1 look (MGS1-style) — technical recipe

Researched 2026-11-12 from real shader code; links are in each section.

## What the hardware did

- **Resolution.** MGS1 renders at 320×240. There is no bilinear filtering and no mipmaps, so textures are nearest-neighbour.
- **Textures.** A texture page is at most 256×256. Textures are 4-bit CLUT (16 colours), 8-bit CLUT or 15-bit direct colour.
- **Colour depth.** The framebuffer is 15-bit RGB555. Gouraud polygons are ordered-dithered with this 4×4 table:
  `[-4,0,-3,1 / 2,-2,3,-1 / -3,1,-4,0 / 3,-1,2,-2]`
  per channel: `clip(c+D[y%4,x%4]) >> 3`
  (Source: psx-spx; DuckStation `src/core/gpu_types.h`.)
- **Vertex jitter.** Vertex X/Y are integers in screen space, so vertices snap to the pixel grid and "dance".
  (dsoft20/psx_retroshader: `floor(160*x)/160`, `floor(120*y)/120`.)
- **Affine textures.** Texture UVs are interpolated linearly in screen space, so textures wobble on big polygons. Games subdivided large polygons to hide this.
- **Lighting.** Gouraud per-vertex lighting (3 lights plus background), a depth-cue fog that is linear in 1/z, and no z-buffer (polygons pop).

## PS1 vs PS2

PS2 has bilinear filtering, mipmaps, a z-buffer, perspective-correct mapping, no jitter, and 448p with bloom. Soft, blurry output reads as PS2. Never enable smooth texture filtering or AA for a PS1 look.

## Pipeline we use

1. **Render settings.** Render small: 270×480, ×4 = 1080×1920. Set `filter_size=0` and `taa_render_samples=1`. Textures use `interpolation='Closest'` and are ≤128–256 px.
2. **Post per frame** (`lowpoly/psx_post.py`, numpy): RGB555 ordered dither at the internal resolution, then a nearest-neighbour upscale.
3. **Text.** Subtitles and graphics go on after the PSX post, inside the `core/safe_zones.py` frame.
4. **Planned.** A Geometry Nodes screen-space vertex snap (Camera Info node) for jitter, and the `uvw/w` affine trick on big floor and wall polygons.

## Sources

- github.com/dsoft20/psx_retroshader
- github.com/MenacingMecha/godot-psx-style-demo
- github.com/Kodrin/URP-PSX
- psx-spx.consoledev.net (GPU and GTE sections)
- pikuma.com/blog/how-to-make-ps1-graphics
