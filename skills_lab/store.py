"""Where log entries and their skill tags live: two extra tables in the app's own tracker.db.

Because they are in the same database file, the existing Veeam snapshot and restore carry them automatically.
Nothing here touches the existing tables; ensure() only adds the new ones.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS log_entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    INTEGER NOT NULL REFERENCES students(id),
    week_start    TEXT NOT NULL,
    day_index     INTEGER NOT NULL,          -- 0 = Monday ... 6 = Sunday (row order on the logbook page)
    entry_date    TEXT NOT NULL,
    text          TEXT NOT NULL,
    source        TEXT NOT NULL,             -- 'typed' | 'ocr:tesseract' | 'ocr:trocr' | 'import'
    ocr_conf      REAL,
    confirmed     INTEGER NOT NULL DEFAULT 0,-- 1 once the student has checked the text
    submission_id INTEGER,                   -- the stored logbook photo this was read from
    updated_at    TEXT NOT NULL,
    UNIQUE (student_id, week_start, day_index)
);
CREATE TABLE IF NOT EXISTS entry_skills (
    entry_id  INTEGER NOT NULL REFERENCES log_entries(id) ON DELETE CASCADE,
    category  TEXT NOT NULL,
    score     REAL NOT NULL,
    backend   TEXT NOT NULL,                 -- which classifier proposed it, or 'student' when set by hand
    confirmed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (entry_id, category)
);
"""


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_entry(conn: sqlite3.Connection, student_id: int, week_start: date, day_index: int, text: str,
                 source: str = "typed", ocr_conf: float | None = None, confirmed: bool = False,
                 submission_id: int | None = None) -> int:
    """Insert or replace the entry for one day. Returns the entry id. Skill tags of a changed text are cleared."""
    ensure(conn)
    text = " ".join(text.split())
    when = week_start + timedelta(days=day_index)
    old = conn.execute("SELECT id, text FROM log_entries WHERE student_id=? AND week_start=? AND day_index=?",
                       (student_id, week_start.isoformat(), day_index)).fetchone()
    now = datetime.now().isoformat(timespec="seconds")
    if old:
        if old["text"] != text:
            conn.execute("DELETE FROM entry_skills WHERE entry_id=?", (old["id"],))
        conn.execute("UPDATE log_entries SET text=?, source=?, ocr_conf=?, confirmed=?, submission_id=?, updated_at=? WHERE id=?",
                     (text, source, ocr_conf, int(confirmed), submission_id, now, old["id"]))
        conn.commit()
        return int(old["id"])
    cur = conn.execute(
        "INSERT INTO log_entries (student_id, week_start, day_index, entry_date, text, source, ocr_conf, confirmed,"
        " submission_id, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (student_id, week_start.isoformat(), day_index, when.isoformat(), text, source, ocr_conf, int(confirmed),
         submission_id, now))
    conn.commit()
    return int(cur.lastrowid)


def set_skills(conn: sqlite3.Connection, entry_id: int, picks: list[tuple[str, float]], backend: str,
               confirmed: bool = False) -> None:
    conn.execute("DELETE FROM entry_skills WHERE entry_id=?", (entry_id,))
    conn.executemany("INSERT INTO entry_skills (entry_id, category, score, backend, confirmed) VALUES (?,?,?,?,?)",
                     [(entry_id, k, float(s), backend, int(confirmed)) for k, s in picks])
    conn.commit()


def entries(conn: sqlite3.Connection, student_id: int) -> list[sqlite3.Row]:
    ensure(conn)
    return conn.execute("SELECT * FROM log_entries WHERE student_id=? ORDER BY entry_date", (student_id,)).fetchall()


def skills_of(conn: sqlite3.Connection, entry_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM entry_skills WHERE entry_id=? ORDER BY score DESC", (entry_id,)).fetchall()


def classify_student(conn: sqlite3.Connection, student_id: int, backend, only_missing: bool = True) -> int:
    """Tag every entry of a student with the backend. Entries whose tags the student confirmed are left alone."""
    todo = []
    for e in entries(conn, student_id):
        tags = skills_of(conn, e["id"])
        if only_missing and tags:
            continue
        if any(t["confirmed"] for t in tags):
            continue
        todo.append(e)
    if not todo:
        return 0
    preds = backend.predict([e["text"] for e in todo])
    for e, p in zip(todo, preds):
        set_skills(conn, e["id"], p, backend.name)
    return len(todo)
