"""Social media card studio: themes, templates and export sizes (Pillow only)."""
from __future__ import annotations

import random
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from .fonts import fit_font, get_font

Color = tuple[int, int, int]

SIZES: dict[str, tuple[str, tuple[int, int]]] = {
    "square": ("Post - Instagram / Facebook (1080x1080)", (1080, 1080)),
    "story": ("Status / Story (1080x1920)", (1080, 1920)),
    "wide": ("Banner - LinkedIn / X (1200x630)", (1200, 630)),
}


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    bg1: Color
    bg2: Color
    accent: Color
    text: Color
    sub: Color
    frame: str                      # circle | rounded | polaroid
    decor: str                      # rings | lines | stripes | bands | blocks | sparks
    duotone: tuple[Color, Color] | None = None
    flat_bg: bool = False


THEMES: tuple[Theme, ...] = (
    Theme("neon", "Neon Night", (11, 16, 48), (76, 20, 120), (0, 229, 255), (255, 255, 255), (186, 196, 255),
          "circle", "rings"),
    Theme("sunset", "Sunset Hustle", (255, 140, 0), (214, 36, 110), (255, 238, 186), (255, 255, 255),
          (255, 236, 214), "circle", "sparks"),
    Theme("harambee", "Harambee Green", (8, 96, 56), (4, 38, 24), (200, 30, 50), (255, 255, 255),
          (205, 235, 215), "rounded", "stripes"),
    Theme("paper", "Pen & Paper", (250, 244, 230), (250, 244, 230), (196, 52, 52), (24, 44, 112),
          (80, 96, 150), "polaroid", "lines", flat_bg=True),
    Theme("graduate", "Graduate Gold", (12, 29, 64), (26, 58, 120), (234, 186, 62), (255, 255, 255),
          (190, 205, 235), "rounded", "bands"),
    Theme("pop", "Duotone Pop", (255, 232, 70), (255, 168, 0), (24, 24, 24), (24, 24, 24),
          (70, 50, 0), "circle", "blocks", duotone=((24, 20, 70), (255, 120, 170))),
)
THEME_MAP = {t.key: t for t in THEMES}


# ------------------------------------------------------------------ helpers
def _gradient(size: tuple[int, int], c1: Color, c2: Color) -> Image.Image:
    g = Image.linear_gradient("L").resize(size)  # black (top) -> white (bottom)
    return ImageOps.colorize(g, black=c1, white=c2).convert("RGBA")


def _luma(c: Color) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _on(c: Color) -> Color:
    return (20, 20, 20) if _luma(c) > 150 else (255, 255, 255)


def _circle_mask(d: int) -> Image.Image:
    s = 4
    m = Image.new("L", (d * s, d * s), 0)
    ImageDraw.Draw(m).ellipse((0, 0, d * s - 1, d * s - 1), fill=255)
    return m.resize((d, d), Image.LANCZOS)


def _rounded_mask(d: int, radius: int) -> Image.Image:
    s = 4
    m = Image.new("L", (d * s, d * s), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, d * s - 1, d * s - 1), radius=radius * s, fill=255)
    return m.resize((d, d), Image.LANCZOS)


def _flame(draw: ImageDraw.ImageDraw, x: int, y: int, s: int, outer: Color, inner: Color) -> None:
    def shape(k: float, col: Color, dy: float = 0.0):
        r = int(0.6 * s * k)
        cy = int(y + 0.3 * s + dy * s)
        draw.ellipse((x - r, cy - r, x + r, cy + r), fill=col)
        draw.polygon([(x - r, cy - int(0.15 * r)), (x, int(y - s * k + dy * s)), (x + r, cy - int(0.15 * r))], fill=col)
    shape(1.0, outer)
    shape(0.55, inner, 0.2)


# ------------------------------------------------------------- photo styling
def _style_photo(face: Image.Image, d: int, theme: Theme) -> Image.Image:
    """Return an RGBA image (with border and soft shadow) for the face photo."""
    if theme.frame == "polaroid":
        d = int(d * 0.8)  # the white card + rotation need extra room
    photo = ImageOps.fit(face.convert("RGB"), (d, d), Image.LANCZOS, centering=(0.5, 0.38))
    if theme.duotone:
        photo = ImageOps.colorize(ImageOps.autocontrast(ImageOps.grayscale(photo)),
                                  black=theme.duotone[0], white=theme.duotone[1])
    b = max(6, d // 32)
    pad = d // 6  # room for shadow / rotation
    if theme.frame == "polaroid":
        w, h = d + 2 * b * 2, d + b * 2 + int(d * 0.2)
        card = Image.new("RGBA", (w, h), (255, 255, 255, 255))
        card.paste(photo, (b * 2, b * 2))
        base = card.rotate(4, expand=True, resample=Image.BICUBIC)
    else:
        mask = _circle_mask(d + 2 * b) if theme.frame == "circle" else _rounded_mask(d + 2 * b, d // 8)
        ring = Image.new("RGBA", mask.size, theme.accent + (255,))
        inner_mask = _circle_mask(d) if theme.frame == "circle" else _rounded_mask(d, max(4, d // 8 - b))
        ring.paste(photo, (b, b), inner_mask)
        ring.putalpha(mask)
        base = ring
    out = Image.new("RGBA", (base.width + 2 * pad, base.height + 2 * pad), (0, 0, 0, 0))
    shadow = Image.new("RGBA", out.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 110), (pad, pad + pad // 4), base.getchannel("A"))
    out = Image.alpha_composite(out, shadow.filter(ImageFilter.GaussianBlur(pad // 3)))
    out.alpha_composite(base, (pad, pad))
    return out


# --------------------------------------------------------------- decorations
def _decor(img: Image.Image, theme: Theme, center: tuple[int, int], d: int) -> Image.Image:
    W, H = img.size
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    g = ImageDraw.Draw(over)
    a = theme.accent
    if theme.decor == "rings":
        for i, r in enumerate((0.62, 0.8, 1.0, 1.25)):
            rr = int(d * r)
            g.ellipse((center[0] - rr, center[1] - rr, center[0] + rr, center[1] + rr),
                      outline=a + (90 - i * 18,), width=max(2, W // 300))
    elif theme.decor == "lines":
        gap = max(28, H // 26)
        for y in range(gap * 2, H, gap):
            g.line((0, y, W, y), fill=(120, 160, 220, 150), width=2)
        g.line((int(W * 0.1), 0, int(W * 0.1), H), fill=(220, 90, 90, 170), width=3)
    elif theme.decor == "stripes":
        bh = max(10, H // 64)
        y = H - bh * 4
        for i, col in enumerate(((0, 0, 0), (255, 255, 255), (200, 30, 50), (255, 255, 255))):
            g.rectangle((0, y + i * bh, W, y + (i + 1) * bh), fill=col + (255,))
        g.rectangle((0, 0, W, bh), fill=(0, 0, 0, 255))
        g.rectangle((0, bh, W, bh * 2), fill=(200, 30, 50, 255))
    elif theme.decor == "bands":
        for off, alpha in ((0.0, 70), (0.12, 40)):
            x0 = int(W * (0.55 + off))
            g.polygon([(x0, 0), (x0 + int(W * 0.18), 0), (int(W * (0.1 + off)), H), (int(W * (-0.08 + off)), H)],
                      fill=a + (alpha,))
        g.rectangle((0, H - max(10, H // 70), W, H), fill=a + (255,))
    elif theme.decor == "blocks":
        g.rectangle((0, 0, int(W * 0.34), int(H * 0.16)), fill=theme.accent + (255,))
        g.rectangle((int(W * 0.84), int(H * 0.92), W, H), fill=theme.accent + (255,))
        g.ellipse((int(W * 0.78), int(H * 0.04), int(W * 0.98), int(H * 0.04) + int(W * 0.2)), fill=(255, 255, 255, 120))
    elif theme.decor == "sparks":
        rnd = random.Random(7)
        for _ in range(46):
            x, y, r = rnd.randrange(W), rnd.randrange(H), rnd.randrange(4, max(6, W // 60))
            g.ellipse((x - r, y - r, x + r, y + r), fill=a + (rnd.randrange(40, 140),))
    return Image.alpha_composite(img, over)


# --------------------------------------------------------------------- render
def _layout(size_key: str, W: int, H: int) -> dict:
    if size_key == "wide":
        d = int(H * 0.62)
        return dict(cx=int(W * 0.27), cy=int(H * 0.5), d=d, tx=int(W * 0.64), ty=int(H * 0.42), tw=int(W * 0.6), align="mm")
    if size_key == "story":
        d = int(W * 0.66)
        return dict(cx=W // 2, cy=int(H * 0.36), d=d, tx=W // 2, ty=int(H * 0.64), tw=int(W * 0.82), align="mm")
    d = int(W * 0.52)
    return dict(cx=W // 2, cy=int(H * 0.36), d=d, tx=W // 2, ty=int(H * 0.705), tw=int(W * 0.84), align="mm")


def render_card(face: Image.Image, theme_key: str = "neon", size_key: str = "square", name: str = "",
                caption: str = "", streak: int = 0) -> Image.Image:
    theme = THEME_MAP.get(theme_key, THEMES[0])
    W, H = SIZES[size_key][1]
    lay = _layout(size_key, W, H)

    img = (Image.new("RGBA", (W, H), theme.bg1 + (255,)) if theme.flat_bg
           else _gradient((W, H), theme.bg1, theme.bg2))
    img = _decor(img, theme, (lay["cx"], lay["cy"]), lay["d"])

    styled = _style_photo(face, lay["d"], theme)
    img.alpha_composite(styled, (lay["cx"] - styled.width // 2, lay["cy"] - styled.height // 2))

    draw = ImageDraw.Draw(img)
    name = (name or "").strip() or "Your Name"
    tx, ty, tw = lay["tx"], lay["ty"], lay["tw"]
    name_font = fit_font(draw, name, tw, start=int(H * (0.085 if size_key != "wide" else 0.12)), bold=True)
    draw.text((tx, ty), name, font=name_font, fill=theme.text, anchor="mm")
    line_h = name_font.size if hasattr(name_font, "size") else 40

    cap = (caption or "").strip()
    y = ty + int(line_h * 0.95)
    if cap:
        cap_font = fit_font(draw, cap, tw, start=int(line_h * 0.55), bold=False, min_size=12)
        draw.text((tx, y), cap, font=cap_font, fill=theme.sub, anchor="mm")
        y += int(line_h * 0.9)

    # Streak pill (or hashtag when there is no streak yet)
    label = f"{streak}-WEEK STREAK" if streak > 0 else "#INDUSTRIALATTACHMENT"
    pill_font = fit_font(draw, label, tw, start=int(line_h * 0.5), bold=True, min_size=12)
    tw_text = int(draw.textlength(label, font=pill_font))
    ph = int(pill_font.size * 2.1) if hasattr(pill_font, "size") else 60
    icon = int(ph * 0.5) if streak > 0 else 0
    pw = tw_text + ph + icon
    x0, y0 = tx - pw // 2, y
    draw.rounded_rectangle((x0, y0, x0 + pw, y0 + ph), radius=ph // 2, fill=theme.accent)
    fg = _on(theme.accent)
    text_x = x0 + ph // 2 + icon
    if streak > 0:
        _flame(draw, x0 + ph // 2 + icon // 3, y0 + ph // 2 - icon // 3, int(ph * 0.4),
               (255, 120, 0) if fg == (255, 255, 255) else (214, 64, 0), (255, 220, 80))
    draw.text((text_x, y0 + ph // 2), label, font=pill_font, fill=fg, anchor="lm")
    return img.convert("RGB")
