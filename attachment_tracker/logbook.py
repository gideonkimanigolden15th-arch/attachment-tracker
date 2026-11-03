"""Logbook photo verification.

What it does
------------
1. FIRST logbook upload (analyse):  the photo must show a *weekly record page*:
      * a table with a closed, bordered grid (outer border + inner row/column lines),
      * at least 5 equal-height day rows (Monday-Friday),
      * written entries in the body cells (a blank template is rejected),
      * if Tesseract OCR is installed: printed "Week" / day-of-week wording.
   If it passes, the printed LAYOUT of that page (column positions, row positions, header words)
   is stored as the student's *logbook profile*.
2. EVERY later upload (compare):  must still be a bordered weekly record page AND its layout must match
   the registered profile, so a student cannot switch to a different or home-made logbook half way.
3. Duplicate detection (fingerprint): a fingerprint of the HANDWRITING in the body cells is stored with
   each photo. The same page photographed again, or another student's page, is rejected.

It is deliberately structure-based, not a library of university templates: universities differ (the KeMU
form has 3 columns, the KCAU form 6) and new formats appear every year, so the app learns each student's
own logbook from their first upload instead.

What it cannot do: it cannot tell a genuine logbook from a convincing hand-drawn copy of one, and it cannot
read the supervisor's stamp. It makes casual faking (random photo, blank form, notebook paper, a different
book, reused or shared photos) fail, and it gives supervisors a locked layout to spot-check against.
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

try:  # OpenCV is required for verification; the app tells the user if it is missing.
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

TARGET_LONG_SIDE = 1800
SIGNATURE_VERSION = 1

# ---- thresholds (tuned on synthetic phone-style photos; adjust in one place) ----
MIN_TABLE_LINES = 4          # horizontal lines  -> at least 3 rows
MIN_TABLE_COLS = 2           # at least 2 columns (Day + something)
MIN_DAY_ROWS = 5             # Monday-Friday
MIN_TABLE_WIDTH = 0.55       # of page width
MIN_TABLE_HEIGHT = 0.22      # of page height
BORDER_COVER = 0.80          # fraction of each outer edge that must be drawn
CELL_INK_MIN = 0.006         # ink density that counts as "something written" in a cell
MIN_FILLED_CELLS = 2
COL_TOL = 0.04               # max column-position difference vs the registered layout (genuine photos vary ~0.002;
ROW_TOL = 0.06               # the margin allows for curved pages near the book's spine)
WORDS_MIN_JACCARD = 0.30
DUPLICATE_SIMILARITY = 0.88

DAY_WORDS = {
    "mon", "monday", "tue", "tues", "tuesday", "wed", "wednesday", "thu", "thur", "thurs", "thursday",
    "fri", "friday", "sat", "saturday", "sun", "sunday",
    # Kiswahili
    "jumatatu", "jumanne", "jumatano", "alhamisi", "ijumaa", "jumamosi", "jumapili",
}
_DAY_KEY = {  # collapse variants so "Mon." and "Monday" count once
    "mon": "mon", "monday": "mon", "jumatatu": "mon",
    "tue": "tue", "tues": "tue", "tuesday": "tue", "jumanne": "tue",
    "wed": "wed", "wednesday": "wed", "jumatano": "wed",
    "thu": "thu", "thur": "thu", "thurs": "thu", "thursday": "thu", "alhamisi": "thu",
    "fri": "fri", "friday": "fri", "ijumaa": "fri",
    "sat": "sat", "saturday": "sat", "jumamosi": "sat",
    "sun": "sun", "sunday": "sun", "jumapili": "sun",
}
WEEK_WORDS = {"week", "wk", "wiki"}


def available() -> bool:
    return cv2 is not None


# =============================================================== report types
@dataclass
class Check:
    label: str
    ok: bool
    detail: str = ""


@dataclass
class LogbookReport:
    checks: list[Check] = field(default_factory=list)
    signature: dict | None = None
    fingerprint: str = ""          # handwriting fingerprint (base64), "" when nothing written
    ocr_used: bool = False

    def _ok(self, *labels: str) -> bool:
        return all(c.ok for c in self.checks if c.label in labels)

    @property
    def structure_ok(self) -> bool:
        return self._ok("Bordered table", "Closed outer border", "Day rows", "Table size")

    @property
    def content_ok(self) -> bool:
        return self._ok("Handwritten entries")

    @property
    def text_ok(self) -> bool:
        return self._ok("Week / day wording")

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks)

    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def summary(self) -> str:
        return "; ".join(f"{'OK' if c.ok else 'FAIL'} {c.label}" + (f" ({c.detail})" if c.detail else "")
                         for c in self.checks)


@dataclass
class Match:
    ok: bool
    reasons: list[str]
    score: float = 0.0


# ================================================================== image prep
def _to_gray(img: Image.Image) -> np.ndarray:
    g = np.array(img.convert("L"))
    h, w = g.shape
    s = TARGET_LONG_SIDE / max(h, w)
    if abs(s - 1) > 0.02:
        g = cv2.resize(g, (max(1, int(w * s)), max(1, int(h * s))),
                       interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    return g


def _order_quad(pts: np.ndarray) -> np.ndarray:
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype="float32")


def _rectify(gray: np.ndarray) -> np.ndarray:
    """If the page is photographed on a desk at an angle, warp it flat. Falls back to the input."""
    h, w = gray.shape
    blur = cv2.GaussianBlur(gray, (9, 9), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return gray
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.45 * h * w:
        return gray
    approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
    if len(approx) != 4 or not cv2.isContourConvex(approx):
        return gray
    quad = _order_quad(approx.reshape(4, 2).astype("float32"))
    tl, tr, br, bl = quad
    out_w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    out_h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if out_w < 0.4 * w or out_h < 0.4 * h or not (0.5 < out_w / out_h < 2.0):
        return gray
    dst = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(quad, dst)
    warped = cv2.warpPerspective(gray, M, (out_w, out_h), flags=cv2.INTER_CUBIC, borderValue=255)
    s = TARGET_LONG_SIDE / max(warped.shape)
    return cv2.resize(warped, (int(warped.shape[1] * s), int(warped.shape[0] * s)), interpolation=cv2.INTER_AREA)


def _rectify_table(gray: np.ndarray) -> np.ndarray | None:
    """Fallback for photos where the page edges are not visible: flatten the TABLE using its own border."""
    h, w = gray.shape
    mask = _ink(gray)
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, w // 40), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, h // 50)))
    lines = cv2.bitwise_or(cv2.morphologyEx(mask, cv2.MORPH_OPEN, hk), cv2.morphologyEx(mask, cv2.MORPH_OPEN, vk))
    lines = cv2.dilate(lines, np.ones((3, 3), np.uint8), iterations=2)
    cnts, _ = cv2.findContours(lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.08 * h * w:
        return None
    hull = cv2.convexHull(c)
    peri = cv2.arcLength(hull, True)
    quad = None
    for eps in (0.01, 0.02, 0.03, 0.045, 0.06):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            quad = _order_quad(approx.reshape(4, 2).astype("float32"))
            break
    if quad is None:
        return None
    tl, tr, br, bl = quad
    x0, x1 = (tl[0] + bl[0]) / 2, (tr[0] + br[0]) / 2
    y0, y1 = (tl[1] + tr[1]) / 2, (bl[1] + br[1]) / 2
    if x1 - x0 < 0.3 * w or y1 - y0 < 0.15 * h:
        return None
    dst = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype="float32")
    M = cv2.getPerspectiveTransform(quad, dst)
    return cv2.warpPerspective(gray, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)


def _ink(gray: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 35, 12)


def _deskew(gray: np.ndarray) -> np.ndarray:
    """Rotate by the small angle (+-6 deg) that makes the horizontal rules most 'row-like'."""
    small_scale = 600 / max(gray.shape)
    small = cv2.resize(gray, None, fx=small_scale, fy=small_scale, interpolation=cv2.INTER_AREA)
    mask = _ink(small)
    h, w = mask.shape
    best, best_angle = -1.0, 0.0
    for angle in np.arange(-6, 6.01, 0.5):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), float(angle), 1.0)
        r = cv2.warpAffine(mask, M, (w, h), flags=cv2.INTER_NEAREST)
        v = float(np.var(r.sum(axis=1).astype(np.float64)))
        if v > best:
            best, best_angle = v, float(angle)
    if abs(best_angle) < 0.3:
        return gray
    H, W = gray.shape
    M = cv2.getRotationMatrix2D((W / 2, H / 2), best_angle, 1.0)
    return cv2.warpAffine(gray, M, (W, H), flags=cv2.INTER_CUBIC, borderValue=255)


# ============================================================== table finding
def _groups(profile: np.ndarray, thresh: float, gap: int) -> list[tuple[int, int]]:
    idx = np.where(profile >= thresh)[0]
    out: list[list[int]] = []
    for i in idx:
        if out and i - out[-1][-1] <= gap:
            out[-1].append(int(i))
        else:
            out.append([int(i)])
    return [(g[0], g[-1]) for g in out]


def _extent(mask_band: np.ndarray) -> tuple[int, int] | None:
    cols = np.where(mask_band.any(axis=0))[0]
    return (int(cols[0]), int(cols[-1])) if len(cols) else None


@dataclass
class _Table:
    ys: list[float]      # horizontal line centres
    xs: list[float]      # vertical line centres
    borders: dict[str, float]


def _find_table(mask: np.ndarray) -> tuple[_Table | None, np.ndarray, np.ndarray]:
    H, W = mask.shape
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, W // 18), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(40, H // 30)))
    hl = cv2.morphologyEx(mask, cv2.MORPH_OPEN, hk)
    vl = cv2.morphologyEx(mask, cv2.MORPH_OPEN, vk)

    # horizontal rules that are wide enough to belong to a table
    rows = _groups(hl.sum(axis=1) / 255.0, 0.30 * W, 4)
    lines = []
    for a, b in rows:
        ext = _extent(hl[max(0, a - 1): b + 2])
        if ext and ext[1] - ext[0] >= 0.45 * W:
            lines.append(((a + b) / 2, ext[0], ext[1]))
    if len(lines) < MIN_TABLE_LINES:
        return None, hl, vl
    # keep the biggest family of lines that share the same left/right extent (the table, not underlines)
    best: list = []
    for _, x0, x1 in lines:
        fam = [ln for ln in lines if abs(ln[1] - x0) <= 0.04 * W and abs(ln[2] - x1) <= 0.04 * W]
        if len(fam) > len(best):
            best = fam
    if len(best) < MIN_TABLE_LINES:
        return None, hl, vl
    ys = [ln[0] for ln in best]
    x_left = float(np.median([ln[1] for ln in best]))
    x_right = float(np.median([ln[2] for ln in best]))
    y0, y1 = int(ys[0]), int(ys[-1])
    if y1 - y0 < 8:
        return None, hl, vl

    band = vl[y0: y1 + 1, :]
    cols = _groups(band.sum(axis=0) / 255.0, 0.60 * (y1 - y0), 4)
    margin = int(0.012 * W)
    xs = [(a + b) / 2 for a, b in cols if (a + b) / 2 > margin and (a + b) / 2 < W - margin
          and x_left - 0.04 * W <= (a + b) / 2 <= x_right + 0.04 * W]

    def hcover(y: float) -> float:
        seg = hl[max(0, int(y) - 3): int(y) + 4, int(x_left): int(x_right) + 1]
        return float(seg.any(axis=0).mean()) if seg.size else 0.0

    def vcover(x: float) -> float:
        seg = vl[y0: y1 + 1, max(0, int(x) - 3): int(x) + 4]
        return float(seg.any(axis=1).mean()) if seg.size else 0.0

    borders = {"top": hcover(ys[0]), "bottom": hcover(ys[-1]),
               "left": vcover(xs[0]) if xs else 0.0, "right": vcover(xs[-1]) if xs else 0.0}
    if xs:  # outer vertical rules must sit at the table edges
        if abs(xs[0] - x_left) > 0.04 * W:
            borders["left"] = 0.0
        if abs(xs[-1] - x_right) > 0.04 * W:
            borders["right"] = 0.0
    return _Table(ys=ys, xs=xs, borders=borders), hl, vl


# ====================================================================== OCR
def _tesseract() -> str | None:
    env = os.environ.get("TESSERACT_EXE")
    if env and Path(env).exists():
        return env
    exe = shutil.which("tesseract")
    if exe:
        return exe
    for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if Path(p).exists():
            return p
    return None


def ocr_available() -> bool:
    return _tesseract() is not None


def _ocr_words(gray: np.ndarray, psm: int = 11) -> list[tuple[str, float]]:
    exe = _tesseract()
    if not exe:
        return []
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "page.png"
        cv2.imwrite(str(png), gray)
        try:
            res = subprocess.run([exe, str(png), "stdout", "--psm", str(psm), "tsv"], capture_output=True, text=True,
                                 timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return []
    words = []
    for line in res.stdout.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 12 and parts[11].strip():
            try:
                words.append((parts[11].strip(), float(parts[10])))
            except ValueError:
                continue
    return words


def _text_evidence(words: list[tuple[str, float]]) -> tuple[set[str], bool, list[str]]:
    days, week, printed = set(), False, []
    for text, conf in words:
        t = re.sub(r"[^a-z]", "", text.lower())
        if len(t) < 2:
            continue
        if t in _DAY_KEY and conf >= 30:
            days.add(_DAY_KEY[t])
        if t in WEEK_WORDS and conf >= 30:
            week = True
        if conf >= 60 and len(t) >= 4:
            printed.append(t)
    return days, week, sorted(set(printed))[:80]


# ================================================================== analysis
def _analyse_oriented(gray: np.ndarray, use_ocr: bool) -> LogbookReport:
    rep = LogbookReport()
    H, W = gray.shape
    mask = _ink(gray)
    table, hl, vl = _find_table(mask)

    nlines = len(table.ys) if table else 0
    ncols = max(0, len(table.xs) - 1) if table else 0
    rep.checks.append(Check("Bordered table", bool(table) and nlines >= MIN_TABLE_LINES and ncols >= MIN_TABLE_COLS,
                            f"{max(0, nlines - 1)} rows x {ncols} columns of ruled lines found"))
    if not table or ncols < MIN_TABLE_COLS:
        rep.checks += [Check("Closed outer border", False, "no table"), Check("Day rows", False, "no table"),
                       Check("Table size", False, "no table")]
        return rep

    cover = table.borders
    weakest = min(cover.values())
    rep.checks.append(Check("Closed outer border", weakest >= BORDER_COVER,
                            f"edges drawn: top {cover['top']:.0%}, bottom {cover['bottom']:.0%}, "
                            f"left {cover['left']:.0%}, right {cover['right']:.0%}"))

    heights = np.diff(table.ys)
    med = float(np.median(heights))
    day_rows = int(np.sum(np.abs(heights - med) <= 0.35 * med))
    rep.checks.append(Check("Day rows", day_rows >= MIN_DAY_ROWS, f"{day_rows} equal-height rows (need {MIN_DAY_ROWS}+ for Mon-Fri)"))

    tw = (table.xs[-1] - table.xs[0]) / W
    th = (table.ys[-1] - table.ys[0]) / H
    rep.checks.append(Check("Table size", tw >= MIN_TABLE_WIDTH and th >= MIN_TABLE_HEIGHT,
                            f"table covers {tw:.0%} of page width, {th:.0%} of height"))

    # ---- handwriting in the body cells (not first row, not first column) -------------
    grid = cv2.dilate(cv2.bitwise_or(hl, vl), np.ones((7, 7), np.uint8))
    written = cv2.bitwise_and(mask, cv2.bitwise_not(grid))
    filled = 0
    body_cells = 0
    ys = [int(y) for y in table.ys]
    xs = [int(x) for x in table.xs]
    for ri in range(1, len(ys) - 1):
        for ci in range(1, len(xs) - 1):
            cell = written[ys[ri] + 5: ys[ri + 1] - 4, xs[ci] + 5: xs[ci + 1] - 4]
            if cell.size == 0:
                continue
            body_cells += 1
            if cell.mean() / 255.0 >= CELL_INK_MIN:
                filled += 1
    rep.checks.append(Check("Handwritten entries", filled >= MIN_FILLED_CELLS,
                            f"{filled} of {body_cells} body cells contain writing (need {MIN_FILLED_CELLS}+)"))

    # ---- optional OCR evidence of weeks and days ------------------------------------
    words: list[str] = []
    if use_ocr and ocr_available():
        # OCR reads table text far better once the ruled lines (which touch the letters) are erased
        clean = gray.copy()
        clean[grid > 0] = 255
        days, week, words = _text_evidence(_ocr_words(clean))
        if len(days) < 5 and len(xs) > 2:
            # second try: crop the first (Day) column, enlarge it and read it as a block of text
            col = clean[max(0, ys[0]): ys[-1], max(0, xs[0]): xs[1]]
            if col.size:
                col = cv2.resize(col, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                col = cv2.copyMakeBorder(col, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)
                d2, _w2, _p2 = _text_evidence(_ocr_words(col, psm=6))
                days |= d2
        rep.ocr_used = True
        ok = len(days) >= 3 and (week or len(days) >= 5)
        rep.checks.append(Check("Week / day wording", ok,
                                f"found {len(days)} day name(s)" + (" and the word 'Week'" if week else "")))

    # ---- layout signature -----------------------------------------------------------
    span_x = xs[-1] - xs[0]
    span_y = ys[-1] - ys[0]
    rep.signature = {
        "v": SIGNATURE_VERSION,
        "cols": ncols,
        "rows": len(ys) - 1,
        "col_fracs": [round((x - xs[0]) / span_x, 3) for x in xs],
        "row_fracs": [round((y - ys[0]) / span_y, 3) for y in ys],
        "bbox": [round(xs[0] / W, 3), round(ys[0] / H, 3), round(tw, 3), round(th, 3)],
        "words": words,
        "ocr": rep.ocr_used,
    }

    # ---- handwriting fingerprint (body cells only, so the printed form never matches) --
    if len(ys) > 2 and len(xs) > 2:
        body = written[ys[1] + 5: ys[-1] - 4, xs[1] + 5: xs[-1] - 4].astype(np.float32) / 255.0
        if body.size and body.mean() > 0.0005:
            small = cv2.resize(body, (24, 32), interpolation=cv2.INTER_AREA)
            small = cv2.GaussianBlur(small, (0, 0), 1.0)
            q = np.clip(small / max(float(small.max()), 1e-6) * 255, 0, 255).astype(np.uint8)
            rep.fingerprint = base64.b64encode(q.tobytes()).decode("ascii")
    return rep


def analyse(img: Image.Image, use_ocr: bool = True) -> LogbookReport:
    """Analyse one logbook photo. Tries the photo as-is and rotated 90 deg (sideways phone shots)."""
    if cv2 is None:
        raise RuntimeError("Logbook verification needs OpenCV: pip install opencv-python-headless")
    base = _to_gray(img)
    best: LogbookReport | None = None
    best_score = -1
    for rot in (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
        g = base if rot is None else cv2.rotate(base, rot)
        g = _deskew(_rectify(g))
        rep = _analyse_oriented(g, use_ocr=False)  # cheap structural pass first
        if not rep.structure_ok:  # page edges not visible / keystoned: flatten the table by its own border
            g2 = _rectify_table(g)
            if g2 is not None:
                rep2 = _analyse_oriented(g2, use_ocr=False)
                if sum(c.ok for c in rep2.checks) > sum(c.ok for c in rep.checks):
                    rep, g = rep2, g2
        score = sum(c.ok for c in rep.checks)
        if rep.structure_ok:
            if use_ocr and ocr_available():
                rep = _analyse_oriented(g, use_ocr=True)
            return rep
        if score > best_score:
            best, best_score = rep, score
    assert best is not None
    return best


def locate_table(img: Image.Image):
    """Find the bordered table the same way analyse() does. Returns (flattened grey page, table, h-line mask,
    v-line mask), or None when no weekly table is found. Used by skills_lab to cut the page into day cells."""
    if cv2 is None:
        raise RuntimeError("Needs OpenCV: pip install opencv-python-headless")
    base = _to_gray(img)
    for rot in (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
        g = base if rot is None else cv2.rotate(base, rot)
        g = _deskew(_rectify(g))
        rep = _analyse_oriented(g, use_ocr=False)
        if not rep.structure_ok:
            g2 = _rectify_table(g)
            if g2 is not None:
                rep2 = _analyse_oriented(g2, use_ocr=False)
                if sum(c.ok for c in rep2.checks) > sum(c.ok for c in rep.checks):
                    rep, g = rep2, g2
        if rep.structure_ok:
            table, hl, vl = _find_table(_ink(g))
            if table is not None:
                return g, table, hl, vl
    return None


# ================================================================== matching
def _col_err(a: list[float], b: list[float]) -> float:
    return max(abs(x - y) for x, y in zip(a, b))


def compare(registered: dict, new: dict) -> Match:
    """Does `new` look like the same printed logbook layout as `registered`?"""
    reasons: list[str] = []
    if registered["cols"] != new["cols"]:
        return Match(False, [f"your registered logbook has {registered['cols']} columns, this page has {new['cols']}"], 0.0)
    if abs(registered["rows"] - new["rows"]) > 1:
        return Match(False, [f"your registered logbook page has {registered['rows']} rows, this page has {new['rows']}"], 0.0)

    def errs(flip: bool) -> tuple[float, float]:
        cf = new["col_fracs"][::-1] if flip else new["col_fracs"]
        cf = [round(1 - x, 3) for x in cf] if flip else cf
        c = _col_err(registered["col_fracs"], cf)
        if registered["rows"] == new["rows"]:
            rf = [round(1 - x, 3) for x in new["row_fracs"][::-1]] if flip else new["row_fracs"]
            r = _col_err(registered["row_fracs"], rf)
        else:
            r = 0.0
        return c, r

    # a sideways photo can arrive rotated 180 deg relative to the registered one
    c_err, r_err = min(errs(False), errs(True), key=lambda t: t[0] + t[1])
    if c_err > COL_TOL:
        reasons.append(f"the column widths differ from your registered logbook (off by {c_err:.0%} of the table width)")
    if r_err > ROW_TOL:
        reasons.append(f"the row layout differs from your registered logbook (off by {r_err:.0%} of the table height)")

    rw, nw = set(registered.get("words") or []), set(new.get("words") or [])
    if registered.get("ocr") and new.get("ocr") and len(rw) >= 6 and len(nw) >= 6:
        jac = len(rw & nw) / len(rw | nw)
        if jac < WORDS_MIN_JACCARD:
            reasons.append("the printed headings are different from your registered logbook")
    score = max(0.0, 1.0 - (c_err / (2 * COL_TOL)) * 0.6 - (r_err / (2 * ROW_TOL)) * 0.4)
    return Match(not reasons, reasons, round(score, 2))


def fingerprint_similarity(a: str, b: str) -> float:
    """Zero-mean cosine similarity of two handwriting fingerprints (1.0 = same writing layout)."""
    if not a or not b:
        return 0.0
    va = np.frombuffer(base64.b64decode(a), dtype=np.uint8).astype(np.float32)
    vb = np.frombuffer(base64.b64decode(b), dtype=np.uint8).astype(np.float32)
    if va.shape != vb.shape:
        return 0.0
    va, vb = va - va.mean(), vb - vb.mean()
    den = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(np.dot(va, vb) / den) if den > 0 else 0.0


def signature_to_json(sig: dict) -> str:
    return json.dumps(sig, separators=(",", ":"))


def explain_failure(report: LogbookReport, first_time: bool) -> str:
    """Friendly message for the student."""
    bad = [c for c in report.failures() if first_time or c.label != "Week / day wording"]
    lines = [("This does not look like a filled-in weekly logbook page, so it was not accepted."
              if first_time else "This does not look like a weekly logbook page, so it was not accepted."), ""]
    advice = {
        "Bordered table": "Photograph the page with the ruled table of days (Monday-Friday) fully in view.",
        "Closed outer border": "Make sure all four edges of the table are inside the photo and not cut off or in shadow.",
        "Day rows": "The page must show the weekly table with at least 5 day rows.",
        "Table size": "Move closer so the table fills most of the photo.",
        "Handwritten entries": "Photograph a page that has your entries written in it, not a blank form.",
        "Week / day wording": "The words 'Week' and the day names should be clearly readable. Retake it in good light.",
    }
    for c in bad:
        lines.append(f"- {c.label}: {c.detail}. {advice.get(c.label, '')}")
    return "\n".join(lines)
