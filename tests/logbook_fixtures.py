"""Synthetic logbook pages and phone-style photos for testing the verifier.

Two real-world layouts (from the KeMU and KCAU attachment logbooks) plus a set of fakes.
Handwriting is simulated with wobbly pen strokes, different for every week/seed.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys_path_fix = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(sys_path_fix))
from attachment_tracker.fonts import get_font  # noqa: E402

PW, PH = 1240, 1754  # A4 at 150 dpi
DAYS = ["MON.", "TUE.", "WED.", "THUR.", "FRI."]

LAYOUTS = {
    "kemu": {  # Week No / Date from-to header; DAY | DESCRIPTION OF WORK DONE | NEW SKILLS LEARNT
        "title": "INDUSTRIAL ATTACHMENT PROGRESS FORM",
        "cols": [("DAY", 0.14), ("DESCRIPTION OF WORK DONE", 0.56), ("NEW SKILLS LEARNT", 0.30)],
    },
    "kcau": {  # six columns, one page = one week
        "title": "DAILY INDUSTRIAL ATTACHMENT RECORD",
        "cols": [("DAY/DATE", 0.11), ("DEPARTMENT", 0.13), ("DESCRIPTION OF WORK DONE", 0.32),
                 ("SKILL(S) ACQUIRED", 0.20), ("SUPERVISOR NAME", 0.12), ("REMARKS", 0.12)],
    },
}


def _scribble(d: ImageDraw.ImageDraw, box, rng: random.Random, ink=(25, 40, 120)) -> None:
    x0, y0, x1, y1 = box
    n_lines = rng.randint(1, 3)
    for i in range(n_lines):
        y = y0 + (i + 1) * (y1 - y0) / (n_lines + 1)
        x = x0 + rng.randint(6, 25)
        end = x0 + (x1 - x0) * rng.uniform(0.35, 0.92)
        pts = []
        while x < end:
            pts.append((x, y + rng.uniform(-7, 7)))
            x += rng.uniform(5, 11)
        if len(pts) > 2:
            d.line(pts, fill=ink, width=rng.choice([2, 3]), joint="curve")


def make_page(layout: str = "kemu", week: int = 3, seed: int | None = None, handwriting: bool = True,
              signature_line: bool = True, texts: list[str] | None = None) -> Image.Image:
    """texts: optional typed work description per day row, drawn into the 2nd column (for OCR tests)."""
    rng = random.Random(seed if seed is not None else week * 101)
    cfg = LAYOUTS[layout]
    im = Image.new("RGB", (PW, PH), (253, 253, 251))
    d = ImageDraw.Draw(im)
    d.text((PW // 2, 110), cfg["title"], font=get_font(34, True), fill=(10, 10, 10), anchor="mm")
    d.text((110, 190), f"Week No: {week}", font=get_font(28), fill=(10, 10, 10))
    d.text((520, 190), "Date from: ________  To: ________", font=get_font(28), fill=(10, 10, 10))
    if handwriting:
        d.line([(250, 205), (270, 195), (290, 210), (310, 198)], fill=(25, 40, 120), width=3)

    x0, x1 = int(PW * 0.07), int(PW * 0.93)
    y0 = 270
    head_h, row_h = 80, 150
    y1 = y0 + head_h + row_h * 5
    # cell lines (2-3px, like a printed form)
    xs = [x0]
    for _, frac in cfg["cols"]:
        xs.append(xs[-1] + int((x1 - x0) * frac))
    xs[-1] = x1
    ys = [y0, y0 + head_h] + [y0 + head_h + row_h * (i + 1) for i in range(5)]
    for y in ys:
        d.line([(x0, y), (x1, y)], fill=(20, 20, 20), width=3)
    for x in xs:
        d.line([(x, y0), (x, y1)], fill=(20, 20, 20), width=3)
    for (title, _), xa, xb in zip(cfg["cols"], xs[:-1], xs[1:]):
        f = get_font(18 if len(cfg["cols"]) > 3 else 22, True)
        # wrap long headings on two lines
        words = title.split()
        mid = len(words) // 2 if len(title) > 14 else len(words)
        lines = [" ".join(words[:mid]), " ".join(words[mid:])] if mid < len(words) else [title]
        for li, t in enumerate(lines):
            d.text(((xa + xb) // 2, y0 + head_h // 2 + (li - (len(lines) - 1) / 2) * 24), t, font=f,
                   fill=(10, 10, 10), anchor="mm")
    for i, day in enumerate(DAYS):
        d.text(((xs[0] + xs[1]) // 2, ys[i + 1] + row_h // 2), day, font=get_font(24, True), fill=(10, 10, 10), anchor="mm")
        if texts and i < len(texts):
            f = get_font(26)
            words, line, ln = texts[i].split(), "", 0
            for w in words:
                if f.getlength(line + " " + w) > (xs[2] - xs[1]) - 30 and line:
                    d.text((xs[1] + 14, ys[i + 1] + 14 + ln * 38), line, font=f, fill=(15, 15, 40)); ln += 1; line = w
                else:
                    line = (line + " " + w).strip()
            d.text((xs[1] + 14, ys[i + 1] + 14 + ln * 38), line, font=f, fill=(15, 15, 40))
        elif handwriting:
            for ci in range(1, len(xs) - 1):
                if rng.random() < 0.9:
                    _scribble(d, (xs[ci] + 8, ys[i + 1] + 8, xs[ci + 1] - 8, ys[i + 2] - 8), rng)
    d.text((x0, y1 + 60), "Industry Supervisor's Signature:", font=get_font(26), fill=(10, 10, 10))
    if signature_line:
        d.line([(x0 + 470, y1 + 85), (x0 + 800, y1 + 85)], fill=(20, 20, 20), width=2)
        if handwriting:
            d.line([(x0 + 500, y1 + 70), (x0 + 560, y1 + 55), (x0 + 600, y1 + 78), (x0 + 700, y1 + 60)], fill=(10, 30, 140), width=3)
    return im


def make_ruled_paper(seed: int = 5) -> Image.Image:
    """Plain school-notebook paper with handwriting: lines + margin, no table."""
    rng = random.Random(seed)
    im = Image.new("RGB", (PW, PH), (252, 252, 248))
    d = ImageDraw.Draw(im)
    for y in range(160, PH - 60, 52):
        d.line([(0, y), (PW, y)], fill=(150, 175, 215), width=2)
    d.line([(150, 0), (150, PH)], fill=(215, 110, 110), width=3)
    for y in range(190, PH - 120, 104):
        _scribble(d, (180, y - 40, PW - 100, y + 4), rng)
    return im


def make_excel_like(week_words: bool = True) -> Image.Image:
    """A bordered table with no handwriting that is a computer printout/screenshot (small cells, many columns)."""
    im = Image.new("RGB", (PW, PH), (255, 255, 255))
    d = ImageDraw.Draw(im)
    x0, x1, y0 = 80, PW - 80, 200
    for i in range(0, 13):
        y = y0 + i * 40
        d.line([(x0, y), (x1, y)], fill=(180, 180, 180), width=1)
    for i in range(0, 9):
        x = x0 + i * (x1 - x0) // 8
        d.line([(x, y0), (x, y0 + 12 * 40)], fill=(180, 180, 180), width=1)
    return im


def make_selfie_like() -> Image.Image:
    im = Image.new("RGB", (900, 1200), (120, 170, 200))
    d = ImageDraw.Draw(im)
    d.ellipse((250, 250, 650, 750), fill=(224, 172, 105))
    d.rectangle((300, 800, 600, 1200), fill=(40, 60, 120))
    return im


def photograph(page: Image.Image, seed: int = 0, tilt: float = 4.0, persp: float = 0.05,
               out_long: int = 2400, desk: bool = True, jpeg_q: int = 82) -> Image.Image:
    """Make `page` look like a handheld phone photo: perspective, rotation, shadow gradient, noise, JPEG."""
    rng = np.random.default_rng(seed)
    arr = np.array(page.convert("RGB"))
    h, w = arr.shape[:2]
    # canvas with a desk around the page
    cw, ch = int(w * 1.25), int(h * 1.18)
    canvas = np.full((ch, cw, 3), (92, 74, 58) if desk else (255, 255, 255), dtype=np.uint8)
    if desk:
        canvas = (canvas + rng.normal(0, 6, canvas.shape)).clip(0, 255).astype(np.uint8)
    ox, oy = (cw - w) // 2, (ch - h) // 2
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    jitter = lambda s: rng.uniform(-s, s)  # noqa: E731
    dst = np.float32([
        [ox + jitter(persp) * w, oy + jitter(persp) * h],
        [ox + w + jitter(persp) * w, oy + jitter(persp) * h],
        [ox + w + jitter(persp) * w, oy + h + jitter(persp) * h],
        [ox + jitter(persp) * w, oy + h + jitter(persp) * h],
    ])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(arr, M, (cw, ch), borderMode=cv2.BORDER_TRANSPARENT, dst=canvas.copy())
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (cw, ch))
    out = np.where(mask[..., None] > 0, warped, canvas)
    # rotation
    R = cv2.getRotationMatrix2D((cw / 2, ch / 2), tilt + jitter(1.0), 1.0)
    out = cv2.warpAffine(out, R, (cw, ch), borderValue=(92, 74, 58))
    # lighting gradient + noise + blur
    gx = np.linspace(rng.uniform(0.78, 0.95), rng.uniform(1.0, 1.08), cw)[None, :, None]
    gy = np.linspace(rng.uniform(0.9, 1.0), rng.uniform(0.82, 1.0), ch)[:, None, None]
    out = (out.astype(np.float32) * gx * gy + rng.normal(0, 4, out.shape)).clip(0, 255).astype(np.uint8)
    out = cv2.GaussianBlur(out, (3, 3), 0)
    s = out_long / max(out.shape[:2])
    out = cv2.resize(out, (int(out.shape[1] * s), int(out.shape[0] * s)), interpolation=cv2.INTER_AREA)
    img = Image.fromarray(out)
    return img


def save(img: Image.Image, path: Path, q: int = 82) -> Path:
    img.save(path, "JPEG", quality=q)
    return path


if __name__ == "__main__":  # quick visual check
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    save(photograph(make_page("kemu", 3), 1), out / "kemu_photo.jpg")
    save(photograph(make_page("kcau", 5), 2), out / "kcau_photo.jpg")
    save(make_ruled_paper(), out / "ruled.jpg")
    print("written to", out)
