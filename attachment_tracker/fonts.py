"""Font lookup that works on Windows, macOS and Linux with graceful fallbacks."""
from __future__ import annotations

from functools import lru_cache

from PIL import ImageDraw, ImageFont

_REGULAR = [
    "segoeui.ttf", "arial.ttf", "calibri.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_BOLD = [
    "segoeuib.ttf", "arialbd.ttf", "calibrib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


@lru_cache(maxsize=256)
def get_font(size: int, bold: bool = False):
    for name in (_BOLD if bold else _REGULAR):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start: int,
             bold: bool = True, min_size: int = 14):
    """Largest font (<= start) whose rendered text fits in max_width."""
    size = start
    while size > min_size:
        font = get_font(size, bold)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return get_font(min_size, bold)
