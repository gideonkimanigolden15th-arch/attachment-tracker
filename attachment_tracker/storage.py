"""Service layer: students and photo submissions (upload-order rule: logbook first, then face)."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageOps

from .config import MAX_IMAGE_SIDE, MIN_FACE_SHORT_SIDE, MIN_LOGBOOK_LONG_SIDE, Paths
from .tasks import UPLOAD_KEYS


class RuleError(Exception):
    """A programme rule was broken (shown to the student as a friendly message)."""


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip()).strip("_") or "student"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------- students
def add_student(conn: sqlite3.Connection, full_name: str, reg_no: str,
                institution: str = "", created_at: datetime | None = None) -> sqlite3.Row:
    full_name, reg_no = full_name.strip(), reg_no.strip()
    if not full_name or not reg_no:
        raise RuleError("Please enter both your full name and registration number.")
    try:
        cur = conn.execute(
            "INSERT INTO students (full_name, reg_no, institution, created_at) VALUES (?,?,?,?)",
            (full_name, reg_no, institution.strip(), (created_at or datetime.now()).isoformat(timespec="seconds")),
        )
    except sqlite3.IntegrityError:
        raise RuleError(f"A student with registration number {reg_no} already exists.") from None
    conn.commit()
    return conn.execute("SELECT * FROM students WHERE id=?", (cur.lastrowid,)).fetchone()


def list_students(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM students ORDER BY full_name COLLATE NOCASE").fetchall()


# ----------------------------------------------------------------- settings
def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


# ------------------------------------------------------------ supervisor PIN
_PIN_ITERATIONS = 200_000


def _hash_pin(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, _PIN_ITERATIONS).hex()


def has_supervisor_pin(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM settings WHERE key='supervisor_pin'").fetchone() is not None


def set_supervisor_pin(conn: sqlite3.Connection, pin: str) -> None:
    """Create the PIN (first use only). Changing it later needs the old one: see change_supervisor_pin."""
    pin = pin.strip()
    if len(pin) < 4:
        raise RuleError("The supervisor PIN must be at least 4 characters.")
    if has_supervisor_pin(conn):
        raise RuleError("A supervisor PIN is already set.")
    salt = os.urandom(16)
    conn.execute("INSERT INTO settings (key, value) VALUES ('supervisor_pin', ?)", (f"{salt.hex()}${_hash_pin(pin, salt)}",))
    conn.commit()


def check_supervisor_pin(conn: sqlite3.Connection, pin: str) -> bool:
    row = conn.execute("SELECT value FROM settings WHERE key='supervisor_pin'").fetchone()
    if not row:
        return False
    salt_hex, digest = row["value"].split("$", 1)
    return hmac.compare_digest(_hash_pin(pin.strip(), bytes.fromhex(salt_hex)), digest)


def change_supervisor_pin(conn: sqlite3.Connection, old: str, new: str) -> None:
    if not check_supervisor_pin(conn, old):
        raise RuleError("The current PIN is not correct.")
    new = new.strip()
    if len(new) < 4:
        raise RuleError("The supervisor PIN must be at least 4 characters.")
    salt = os.urandom(16)
    conn.execute("UPDATE settings SET value=? WHERE key='supervisor_pin'", (f"{salt.hex()}${_hash_pin(new, salt)}",))
    conn.commit()


# -------------------------------------------------------------- submissions
def abs_path(paths: Paths, rel: str) -> Path:
    return paths.root / rel


def _load_image(src: Path, task_key: str) -> Image.Image:
    try:
        with Image.open(src) as im:
            im.load()
            im = ImageOps.exif_transpose(im).convert("RGB")
    except Exception:
        raise RuleError("That file could not be opened as a photo. Please choose a JPG or PNG image.") from None
    w, h = im.size
    if task_key == "face" and min(w, h) < MIN_FACE_SHORT_SIDE:
        raise RuleError(f"That photo is only {w}x{h} pixels, which is too small for a face photo "
                        f"(the short side must be at least {MIN_FACE_SHORT_SIDE}). "
                        "Take it with your phone camera instead of using a thumbnail or screenshot.")
    if task_key == "logbook" and max(w, h) < MIN_LOGBOOK_LONG_SIDE:
        raise RuleError(f"That photo is only {w}x{h} pixels, so the table lines of the logbook cannot be checked "
                        f"(the long side must be at least {MIN_LOGBOOK_LONG_SIDE}). "
                        "Take the picture with your phone camera at normal quality, not a thumbnail, "
                        "a screenshot, or a photo compressed by a chat app.")
    im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    return im


def has_task(conn: sqlite3.Connection, student_id: int, task_key: str, wk: date) -> bool:
    row = conn.execute(
        "SELECT 1 FROM submissions WHERE student_id=? AND task_key=? AND week_start=? LIMIT 1",
        (student_id, task_key, wk.isoformat()),
    ).fetchone()
    return row is not None


def save_submission(conn: sqlite3.Connection, paths: Paths, student: sqlite3.Row,
                    task_key: str, src_file: str | Path, when: datetime | None = None) -> sqlite3.Row:
    """Store a logbook or face photo. The only rule: the logbook photo comes first, then the face photo, in the same week.
    Students are trusted to upload their own filled-in logbook; nothing checks what the page looks like."""
    if task_key not in UPLOAD_KEYS:
        raise ValueError(f"Unknown upload task: {task_key}")
    when = when or datetime.now()
    wk = week_start(when.date())

    if task_key == "face" and not has_task(conn, student["id"], "logbook", wk):
        raise RuleError("Upload your logbook photo first. The face photo comes second.")

    im = _load_image(Path(src_file), task_key)

    folder = (paths.logbooks if task_key == "logbook" else paths.faces) / safe_name(student["reg_no"])
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / f"{wk.isoformat()}_{when:%Y%m%d-%H%M%S}.jpg"
    n = 1
    while dst.exists():  # two uploads in the same second
        dst = folder / f"{wk.isoformat()}_{when:%Y%m%d-%H%M%S}_{n}.jpg"
        n += 1
    im.save(dst, "JPEG", quality=90, optimize=True)

    row = _record(conn, paths, student["id"], task_key, dst, when, wk)
    return row


def record_export(conn: sqlite3.Connection, paths: Paths, student: sqlite3.Row,
                  exported_file: Path, when: datetime | None = None) -> sqlite3.Row:
    """Mark the 'social' bonus task as done for the week an export was made."""
    when = when or datetime.now()
    return _record(conn, paths, student["id"], "social", exported_file, when, week_start(when.date()))


def _record(conn, paths, student_id, task_key, file: Path, when: datetime, wk: date,
            page_fp: str = "", verdict: str = "") -> sqlite3.Row:
    rel = file.resolve().relative_to(paths.root).as_posix()
    cur = conn.execute(
        "INSERT INTO submissions (student_id, task_key, week_start, uploaded_at, uploaded_weekday, file_path,"
        " sha256, page_fp, verdict) VALUES (?,?,?,?,?,?,?,?,?)",
        (student_id, task_key, wk.isoformat(), when.isoformat(timespec="seconds"), when.weekday(), rel,
         sha256_of(file), page_fp, verdict),
    )
    conn.commit()
    return conn.execute("SELECT * FROM submissions WHERE id=?", (cur.lastrowid,)).fetchone()


def latest_submission(conn: sqlite3.Connection, student_id: int, task_key: str,
                      wk: date | None = None) -> sqlite3.Row | None:
    sql = "SELECT * FROM submissions WHERE student_id=? AND task_key=?"
    args: list = [student_id, task_key]
    if wk is not None:
        sql += " AND week_start=?"
        args.append(wk.isoformat())
    return conn.execute(sql + " ORDER BY id DESC LIMIT 1", args).fetchone()


def student_overview(conn: sqlite3.Connection, today: date | None = None) -> list[dict]:
    """One row per student for the supervisor: weeks with a logbook photo, complete weeks, streak, last upload."""
    from . import streaks  # local import: streaks imports this module
    out = []
    for st in list_students(conn):
        stats = streaks.week_stats(conn, st["id"], today, n_weeks=520)
        last = conn.execute("SELECT MAX(uploaded_at) AS t FROM submissions WHERE student_id=? AND task_key IN ('logbook','face')",
                            (st["id"],)).fetchone()["t"]
        out.append({"id": st["id"], "name": st["full_name"], "reg_no": st["reg_no"], "institution": st["institution"],
                    "logbook_weeks": sum("logbook" in s.done for s in stats),
                    "complete_weeks": sum(s.complete for s in stats),
                    "streak": streaks.current_streak(conn, st["id"], today),
                    "last_upload": (last or "")[:10]})
    return out


def submissions_of(conn: sqlite3.Connection, student_id: int, task_key: str) -> list[sqlite3.Row]:
    """Every stored photo of one kind for a student, newest week first."""
    return conn.execute("SELECT * FROM submissions WHERE student_id=? AND task_key=? ORDER BY week_start DESC, id DESC",
                        (student_id, task_key)).fetchall()
