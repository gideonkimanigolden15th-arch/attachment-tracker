"""Draws the app icon (assets/icon.png and icon.ico). Run: python packaging/make_icon.py  (needs Pillow)."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "attachment_tracker" / "assets"
S = 1024  # draw large, then shrink for smooth edges


def draw() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # rounded square with a vertical teal -> blue gradient
    grad = Image.new("RGBA", (S, S))
    gp = grad.load()
    for y in range(S):
        t = y / (S - 1)
        c = (int(13 + (37 - 13) * t), int(148 + (99 - 148) * t), int(136 + (235 - 136) * t), 255)
        for x in range(S):
            gp[x, y] = c
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((32, 32, S - 32, S - 32), radius=210, fill=255)
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    # open logbook: two pages with a spine shadow
    page = (255, 255, 255, 255)
    d.polygon([(512, 300), (190, 345), (190, 760), (512, 715)], fill=page)
    d.polygon([(512, 300), (834, 345), (834, 760), (512, 715)], fill=(238, 244, 255, 255))
    d.line([(512, 300), (512, 715)], fill=(148, 163, 184, 255), width=10)
    # ruled lines on the left page (the day rows)
    for i in range(4):
        y = 420 + i * 70
        d.line([(236, y + 6 - i * 3 + 3), (470, y - 10 - i * 3 + 3)], fill=(148, 163, 184, 255), width=9)
    # green check on the right page = task completed
    d.line([(575, 520), (650, 600), (780, 440)], fill=(22, 163, 74, 255), width=46, joint="curve")
    for p in ((575, 520), (650, 600), (780, 440)):
        d.ellipse((p[0] - 23, p[1] - 23, p[0] + 23, p[1] + 23), fill=(22, 163, 74, 255))
    # small streak flame above the book
    d.polygon([(512, 105), (590, 215), (565, 290), (512, 255), (459, 290), (434, 215)], fill=(251, 146, 60, 255))
    d.polygon([(512, 175), (550, 235), (535, 275), (512, 258), (489, 275), (474, 235)], fill=(254, 240, 138, 255))
    return im


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw()
    big.resize((512, 512), Image.LANCZOS).save(OUT / "icon.png")
    big.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT / "icon.png", "and", OUT / "icon.ico")
