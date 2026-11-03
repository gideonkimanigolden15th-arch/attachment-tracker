"""Read the text of each day from a stored logbook photo.

Why cell by cell: the app already finds the ruled table (attachment_tracker.logbook). Cutting the page into one image
per day row, with the ruled lines erased, gives an OCR engine small, clean pieces instead of a whole messy page. That
is what makes line-level handwriting models such as TrOCR usable here.

Engines:
    TesseractEngine   offline, fast, good on printed or neat block capitals, poor on cursive handwriting
    TrOCREngine       Hugging Face 'microsoft/trocr-base-handwritten' (line-level handwriting model). Needs
                      `pip install transformers torch` and a model download. Wiring is tested here with a stand-in
                      model; accuracy on real student handwriting is NOT measured: see GUIDE.md for how to test it.

Whatever engine is used, the student must check the text before it is trusted (confirmed=1 in store.py).
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from attachment_tracker import logbook

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class OcrUnavailable(RuntimeError):
    """An OCR engine needs a program or package that is not installed."""


@dataclass
class DayCell:
    index: int                  # 0 = first day row on the page (Monday on a normal weekly page)
    label: str
    image: np.ndarray           # grey crop of the description cell, ruled lines erased
    box: tuple[int, int, int, int]
    ink: float                  # share of dark pixels: ~0 means the cell is empty


@dataclass
class OcrResult:
    text: str
    conf: float | None = None   # 0-100, None when the engine does not report one


@dataclass
class DayDraft:
    index: int
    label: str
    text: str
    conf: float | None
    empty: bool


# ---------------------------------------------------------------- cutting up the page
def flatten(crop: np.ndarray) -> np.ndarray:
    """Even out phone-photo shading (grey backgrounds, dark edges) so text is black on clean white."""
    bg = cv2.GaussianBlur(cv2.dilate(crop, np.ones((15, 15), np.uint8)), (0, 0), 20)
    out = cv2.divide(crop, np.maximum(bg, 1), scale=255)
    out[:3, :] = out[-3:, :] = 255
    out[:, :3] = out[:, -3:] = 255
    return out


def extract_day_cells(img: Image.Image, text_column: str | int = "widest") -> list[DayCell]:
    """One DayCell per day row of the weekly table. text_column: 'widest' (the work-description column on every
    logbook layout seen so far) or the 0-based column number (0 is the Day column)."""
    located = logbook.locate_table(img)
    if located is None:
        raise ValueError("No weekly logbook table found in this photo.")
    gray, table, hl, vl = located
    ys, xs = [int(y) for y in table.ys], [int(x) for x in table.xs]
    heights = np.diff(ys)
    med = float(np.median(heights))
    rows = [i for i, h in enumerate(heights) if abs(h - med) <= 0.35 * med][:7]  # a header band is taller/shorter: skipped
    widths = np.diff(xs)
    if text_column == "widest":
        col = 1 + int(np.argmax(widths[1:])) if len(widths) > 1 else 0
    else:
        col = int(text_column)
    grid = cv2.dilate(cv2.bitwise_or(hl, vl), np.ones((7, 7), np.uint8))
    clean = gray.copy()
    clean[grid > 0] = 255
    cells = []
    for n, ri in enumerate(rows):
        x0, x1, y0, y1 = xs[col] + 6, xs[col + 1] - 5, ys[ri] + 6, ys[ri + 1] - 5
        crop = clean[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        crop = flatten(crop)
        ink = float((crop < 150).mean())  # after flatten() paper is ~255 and writing is well below 150
        cells.append(DayCell(n, DAY_NAMES[n], crop, (x0, y0, x1, y1), ink))
    return cells


def split_lines(cell: np.ndarray, min_height: int = 10) -> list[np.ndarray]:
    """Cut a cell into text lines (needed by line-level models like TrOCR) using the ink's horizontal profile."""
    blur = cv2.GaussianBlur(cell, (3, 3), 0)
    _, ink = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    prof = (ink > 0).sum(axis=1)
    on = prof > max(2, 0.01 * cell.shape[1])
    bands, start = [], None
    for y, v in enumerate(on):
        if v and start is None:
            start = y
        elif not v and start is not None:
            bands.append([start, y])
            start = None
    if start is not None:
        bands.append([start, len(on)])
    bands = [b for b in bands if b[1] - b[0] >= 3]
    if not bands:
        return []
    typical = float(np.median([b[1] - b[0] for b in bands]))
    merged = [bands[0]]
    for b in bands[1:]:  # re-join the dots of i / j and accents with their line
        if b[0] - merged[-1][1] < 0.35 * typical:
            merged[-1][1] = b[1]
        else:
            merged.append(b)
    out = []
    for a, b in merged:
        if b - a < min_height:
            continue
        a, b = max(0, a - 5), min(cell.shape[0], b + 5)
        out.append(cell[a:b])
    return out


# ---------------------------------------------------------------------- engines
class TesseractEngine:
    name = "tesseract"

    def __init__(self, lang: str = "eng", psm: int = 6):
        self.exe = logbook._tesseract()
        if not self.exe:
            raise OcrUnavailable("Tesseract is not installed (Windows: UB Mannheim build; Linux: apt install tesseract-ocr)")
        self.lang, self.psm = lang, psm

    def read(self, cell: np.ndarray) -> OcrResult:
        big = cv2.resize(cell, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        big = cv2.copyMakeBorder(big, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        with tempfile.TemporaryDirectory() as td:
            png = Path(td) / "cell.png"
            cv2.imwrite(str(png), big)
            try:
                res = subprocess.run([self.exe, str(png), "stdout", "-l", self.lang, "--psm", str(self.psm), "tsv"],
                                     capture_output=True, text=True, timeout=60,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.SubprocessError) as exc:
                raise OcrUnavailable(f"Tesseract failed: {exc}") from exc
        lines: dict[tuple, list[str]] = {}
        confs: list[float] = []
        for row in res.stdout.splitlines()[1:]:
            p = row.split("\t")
            if len(p) >= 12 and p[11].strip():
                try:
                    c = float(p[10])
                except ValueError:
                    continue
                if c < 0:
                    continue
                lines.setdefault((p[2], p[3], p[4]), []).append(p[11].strip())
                confs.append(c)
        text = " ".join(" ".join(ws) for ws in lines.values())
        return OcrResult(text, float(np.mean(confs)) if confs else None)


class TrOCREngine:
    """Hugging Face TrOCR. `processor` / `model` can be passed in (used by the tests with stand-ins)."""

    name = "trocr"

    def __init__(self, model_name: str = "microsoft/trocr-base-handwritten", device: str | None = None,
                 processor=None, model=None):
        if processor is None or model is None:
            try:
                from transformers import TrOCRProcessor, VisionEncoderDecoderModel
            except ImportError as exc:
                raise OcrUnavailable("needs: pip install transformers torch") from exc
            try:
                processor = TrOCRProcessor.from_pretrained(model_name)
                model = VisionEncoderDecoderModel.from_pretrained(model_name)
            except Exception as exc:  # no internet / wrong name
                raise OcrUnavailable(f"could not load {model_name!r}: {exc}") from exc
            if device:
                model = model.to(device)
        self.processor, self.model, self.device = processor, model, device

    def _read_line(self, line: np.ndarray) -> str:
        pixel_values = self.processor(images=Image.fromarray(line).convert("RGB"), return_tensors="pt").pixel_values
        if self.device:
            pixel_values = pixel_values.to(self.device)
        ids = self.model.generate(pixel_values, max_new_tokens=64)
        return self.processor.batch_decode(ids, skip_special_tokens=True)[0].strip()

    def read(self, cell: np.ndarray) -> OcrResult:
        text = " ".join(t for t in (self._read_line(l) for l in split_lines(cell)) if t)
        return OcrResult(text, None)


def get_engine(name: str, **kw):
    if name == "tesseract":
        return TesseractEngine(**kw)
    if name == "trocr":
        return TrOCREngine(**kw)
    raise ValueError(f"unknown OCR engine {name!r}")


# --------------------------------------------------------------------- whole page
def read_page(img: Image.Image, engine, min_ink: float = 0.002,
              on_cell: Callable[[DayCell, OcrResult], None] | None = None) -> list[DayDraft]:
    """OCR every day row of a logbook photo. Empty-looking cells are returned with empty=True (not sent to the engine)."""
    drafts = []
    for cell in extract_day_cells(img):
        if cell.ink < min_ink:
            drafts.append(DayDraft(cell.index, cell.label, "", None, True))
            continue
        res = engine.read(cell.image)
        if on_cell:
            on_cell(cell, res)
        drafts.append(DayDraft(cell.index, cell.label, " ".join(res.text.split()), res.conf, not res.text.strip()))
    return drafts
