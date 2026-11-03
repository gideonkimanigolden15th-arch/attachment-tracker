"""SQLite schema and connection helper.

Journal mode is left at the default (DELETE, not WAL) on purpose: the database is then a
single file, which is simple for Veeam / file copies to capture consistently. For extra
safety the backup layer still takes a proper SQLite online snapshot (see backup.py).

File paths are stored RELATIVE to the data root so a restore to a different drive or
folder (for example a Veeam "restore to new location") keeps working.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name   TEXT NOT NULL,
    reg_no      TEXT NOT NULL UNIQUE,
    institution TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id       INTEGER NOT NULL REFERENCES students(id),
    task_key         TEXT NOT NULL,
    week_start       TEXT NOT NULL,      -- ISO date of the Monday of the week
    uploaded_at      TEXT NOT NULL,      -- ISO datetime
    uploaded_weekday INTEGER NOT NULL,   -- Monday=0 ... Sunday=6
    file_path        TEXT NOT NULL,      -- relative to the data root, forward slashes
    sha256           TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_submissions_lookup
    ON submissions (student_id, week_start, task_key);

-- The logbook layout registered from each student's FIRST verified logbook photo.
CREATE TABLE IF NOT EXISTS logbook_profiles (
    student_id  INTEGER PRIMARY KEY REFERENCES students(id),
    signature   TEXT NOT NULL,          -- JSON layout fingerprint (see logbook.py)
    created_at  TEXT NOT NULL,
    source_file TEXT NOT NULL DEFAULT ''
);

-- Small key/value store (holds the salted hash of the supervisor PIN).
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Columns added after version 1.0 (existing databases are upgraded in place by connect()).
_NEW_SUBMISSION_COLUMNS = {
    "page_fp": "TEXT NOT NULL DEFAULT ''",   # handwriting fingerprint of a logbook photo (duplicate detection)
    "verdict": "TEXT NOT NULL DEFAULT ''",   # what the logbook verifier concluded
}


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    have = {r["name"] for r in conn.execute("PRAGMA table_info(submissions)")}
    for col, decl in _NEW_SUBMISSION_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE submissions ADD COLUMN {col} {decl}")
    conn.commit()
    return conn
