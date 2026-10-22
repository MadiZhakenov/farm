"""Мягкая тень под белым текстом (чтобы не сливался со светлым фоном), без обводки."""

from __future__ import annotations

from PIL import Image, ImageFilter

PAD = 14   # запас по краям под размытие тени, px


def add_shadow(im: Image.Image, blur: float = 5.0, opacity: float = 0.75, offset: tuple[int, int] = (0, 3),
               grow: int = 3, pad: int = PAD) -> Image.Image:
    """RGBA с текстом → RGBA того же текста с тенью (холст больше на pad с каждой стороны, центр тот же)."""
    w, h = im.size
    base = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    base.alpha_composite(im, (pad, pad))
    a = base.getchannel("A").filter(ImageFilter.MaxFilter(2 * grow + 1)).filter(ImageFilter.GaussianBlur(blur))
    a = a.point(lambda v: int(v * opacity))
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sh.putalpha(a)
    out = Image.new("RGBA", base.size, (0, 0, 0, 0))
    out.alpha_composite(sh, offset)
    out.alpha_composite(base)
    return out


def shadow_full_frame(im: Image.Image, **kw) -> Image.Image:
    """Полный кадр (текст уже стоит на месте) → тот же кадр с тенью."""
    pad = kw.pop("pad", PAD)
    return add_shadow(im, pad=pad, **kw).crop((pad, pad, pad + im.width, pad + im.height))
