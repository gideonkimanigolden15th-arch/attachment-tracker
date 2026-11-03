"""Weekly completion statistics and streak maths.

A week (Monday-Sunday) is COMPLETE when every required task (logbook + face photo)
has at least one submission in it. A streak is the number of consecutive complete
weeks. The current week never breaks a streak while it is still in progress.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

from .storage import week_start
from .tasks import REQUIRED_KEYS, STREAK_WEEKDAY


@dataclass
class WeekStat:
    week_start: date
    done: set[str] = field(default_factory=set)
    required_total: int = len(REQUIRED_KEYS)
    friday_upload: bool = False   # at least one upload on the streak day
    is_current: bool = False

    @property
    def required_done(self) -> int:
        return len(self.done & REQUIRED_KEYS)

    @property
    def complete(self) -> bool:
        return REQUIRED_KEYS <= self.done

    @property
    def social_done(self) -> bool:
        return "social" in self.done


def _load(conn: sqlite3.Connection, student_id: int) -> dict[date, WeekStat]:
    weeks: dict[date, WeekStat] = {}
    rows = conn.execute(
        "SELECT task_key, week_start, uploaded_weekday FROM submissions WHERE student_id=?", (student_id,)
    ).fetchall()
    for r in rows:
        wk = date.fromisoformat(r["week_start"])
        st = weeks.setdefault(wk, WeekStat(wk))
        st.done.add(r["task_key"])
        if r["uploaded_weekday"] == STREAK_WEEKDAY and r["task_key"] in REQUIRED_KEYS:
            st.friday_upload = True
    return weeks


def week_stats(conn: sqlite3.Connection, student_id: int, today: date | None = None,
               n_weeks: int = 12) -> list[WeekStat]:
    """Oldest-to-newest stats for the last n_weeks (starting no earlier than enrolment)."""
    today = today or date.today()
    cur = week_start(today)
    window_start = cur - timedelta(weeks=n_weeks - 1)

    st = conn.execute("SELECT created_at FROM students WHERE id=?", (student_id,)).fetchone()
    enrolled = week_start(date.fromisoformat(st["created_at"][:10])) if st else window_start
    first = max(enrolled, window_start)

    loaded = _load(conn, student_id)
    if loaded:  # never hide weeks that have data
        first = min(first, max(min(loaded), window_start))

    out: list[WeekStat] = []
    wk = first
    while wk <= cur:
        stat = loaded.get(wk) or WeekStat(wk)
        stat.is_current = wk == cur
        out.append(stat)
        wk += timedelta(weeks=1)
    return out


def current_streak(conn: sqlite3.Connection, student_id: int, today: date | None = None) -> int:
    weeks = _load(conn, student_id)
    wk = week_start(today or date.today())
    if not (wk in weeks and weeks[wk].complete):
        wk -= timedelta(weeks=1)  # current week still in progress: don't break the streak
    n = 0
    while wk in weeks and weeks[wk].complete:
        n += 1
        wk -= timedelta(weeks=1)
    return n


def best_streak(conn: sqlite3.Connection, student_id: int) -> int:
    weeks = _load(conn, student_id)
    done = sorted(w for w, s in weeks.items() if s.complete)
    best = run = 0
    prev: date | None = None
    for w in done:
        run = run + 1 if prev and w - prev == timedelta(weeks=1) else 1
        best = max(best, run)
        prev = w
    return best


def completion_pct(stats: list[WeekStat]) -> int:
    """Share of required tasks done across the weeks shown (0-100)."""
    if not stats:
        return 0
    total = sum(s.required_total for s in stats)
    return round(100 * sum(s.required_done for s in stats) / total) if total else 0
