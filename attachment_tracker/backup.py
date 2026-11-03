"""Backup preparation, verification and database restore.

How this fits with Veeam
------------------------
Veeam does the real backup and restore of the data folder (see veeam/VEEAM_SETUP.md).
This module makes that safe and checkable:

* prepare_snapshot()  -> run BEFORE the Veeam job (pre-job script). Writes into backup_staging/:
      tracker_snapshot.db     consistent copy of the live database (SQLite online-backup API)
      completion.csv          every student x week x task (the graph tracker as data)
      cohort_overview.png     cohort completion + streak chart
      progress_charts/<reg>.png   each student's weekly completion graph
      manifest.json           size + SHA-256 of every photo and staging file
* verify()            -> run AFTER a Veeam restore (or any time) to prove nothing is missing or corrupt.
* restore_db_from_snapshot() -> if only the live database is damaged, roll it back to the snapshot.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import __version__, db, storage, streaks
from .chart import render_cohort_chart, render_progress_chart
from .config import Paths, get_paths
from .tasks import REQUIRED_KEYS, TASK_KEYS

SNAPSHOT_NAME = "tracker_snapshot.db"
MANIFEST_NAME = "manifest.json"


@dataclass
class VerifyReport:
    checked: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [f"Checked {self.checked} files: {'OK' if self.ok else 'PROBLEMS FOUND'}"]
        lines += [f"  ERROR: {e}" for e in self.errors]
        lines += [f"  note: {w}" for w in self.warnings]
        return "\n".join(lines)


# ------------------------------------------------------------------ snapshot
def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _snapshot_db(paths: Paths) -> Path:
    snap = paths.staging / SNAPSHOT_NAME
    tmp = paths.staging / (SNAPSHOT_NAME + ".tmp")
    if tmp.exists():
        tmp.unlink()
    src = sqlite3.connect(str(paths.db), timeout=15)
    dst = sqlite3.connect(str(tmp))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, snap)
    return snap


def _hash_tree(paths: Paths) -> dict[str, dict]:
    files: dict[str, dict] = {}
    roots = [paths.uploads, paths.staging]
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.name == MANIFEST_NAME or p.suffix == ".tmp":
                continue
            rel = p.relative_to(paths.root).as_posix()
            files[rel] = {"size": p.stat().st_size, "sha256": storage.sha256_of(p)}
    return files


def prepare_snapshot(paths: Paths | None = None, today: date | None = None) -> dict:
    """Create the backup-ready staging folder. Safe to run repeatedly and while the app is open."""
    paths = paths or get_paths()
    paths.staging.mkdir(parents=True, exist_ok=True)
    today = today or date.today()

    snap = _snapshot_db(paths)
    conn = db.connect(snap)  # read the SNAPSHOT so CSV/charts match it exactly
    try:
        students = storage.list_students(conn)

        # completion.csv
        csv_path = paths.staging / "completion.csv"
        tmp_csv = csv_path.with_suffix(".csv.tmp")
        with open(tmp_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["student", "reg_no", "week_start", *TASK_KEYS, "week_complete", "friday_upload"])
            for s in students:
                for st in streaks.week_stats(conn, s["id"], today, n_weeks=520):
                    w.writerow([s["full_name"], s["reg_no"], st.week_start.isoformat(),
                                *[int(k in st.done) for k in TASK_KEYS], int(st.complete), int(st.friday_upload)])
        os.replace(tmp_csv, csv_path)

        # charts
        charts_dir = paths.staging / "progress_charts"
        charts_dir.mkdir(exist_ok=True)
        cohort_rows = []
        for s in students:
            stats = streaks.week_stats(conn, s["id"], today)
            streak = streaks.current_streak(conn, s["id"], today)
            cohort_rows.append((s["full_name"], streak, streaks.completion_pct(stats)))
            render_progress_chart(stats, f"{s['full_name']} ({s['reg_no']}) - weekly completion").save(
                charts_dir / f"{storage.safe_name(s['reg_no'])}.png")
        render_cohort_chart(cohort_rows).save(paths.staging / "cohort_overview.png")
        n_students = len(students)
        n_subs = conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
    finally:
        conn.close()

    files = _hash_tree(paths)
    manifest = {
        "app_version": __version__,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "students": n_students,
        "submissions": n_subs,
        "file_count": len(files),
        "files": files,
    }
    _write_atomic(paths.staging / MANIFEST_NAME, json.dumps(manifest, indent=2).encode("utf-8"))
    return {k: v for k, v in manifest.items() if k != "files"}


def last_snapshot_info(paths: Paths | None = None) -> dict | None:
    paths = paths or get_paths()
    mf = paths.staging / MANIFEST_NAME
    if not mf.exists():
        return None
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {k: v for k, v in data.items() if k != "files"}


# -------------------------------------------------------------------- verify
def verify(paths: Paths | None = None) -> VerifyReport:
    """Check database health, that every recorded photo exists, and that files match the manifest."""
    paths = paths or get_paths()
    rep = VerifyReport()

    if not paths.db.exists():
        rep.errors.append("Database file db/tracker.db is missing. Use 'Restore database from snapshot'.")
    else:
        try:
            conn = sqlite3.connect(str(paths.db))
            res = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if res != "ok":
                rep.errors.append(f"Database integrity check failed: {res}")
            conn.close()
            conn = db.connect(paths.db)
            for r in conn.execute("SELECT s.reg_no, x.task_key, x.week_start, x.file_path, x.sha256 "
                                  "FROM submissions x JOIN students s ON s.id = x.student_id"):
                p = storage.abs_path(paths, r["file_path"])
                rep.checked += 1
                if not p.exists():
                    (rep.warnings if r["task_key"] == "social" else rep.errors).append(
                        f"Missing {r['task_key']} file for {r['reg_no']} (week {r['week_start']}): {r['file_path']}")
                elif r["sha256"] and storage.sha256_of(p) != r["sha256"]:
                    rep.errors.append(f"Photo changed or corrupt: {r['file_path']}")
            conn.close()
        except sqlite3.DatabaseError as exc:
            rep.errors.append(f"Database cannot be read: {exc}")

    mf = paths.staging / MANIFEST_NAME
    if not mf.exists():
        rep.warnings.append("No backup manifest yet. Run 'Prepare backup snapshot' first.")
        return rep
    try:
        manifest = json.loads(mf.read_text(encoding="utf-8"))
    except ValueError:
        rep.errors.append("backup_staging/manifest.json is unreadable.")
        return rep
    listed = manifest.get("files", {})
    for rel, meta in listed.items():
        p = paths.root / rel
        rep.checked += 1
        if not p.exists():
            rep.errors.append(f"Missing since snapshot: {rel}")
        elif p.stat().st_size != meta["size"] or storage.sha256_of(p) != meta["sha256"]:
            rep.errors.append(f"Does not match snapshot (changed or corrupt): {rel}")
    current = set(_hash_tree(paths)) if paths.uploads.exists() else set()
    new = [f for f in current if f not in listed]
    if new:
        rep.warnings.append(f"{len(new)} file(s) added since the last snapshot (normal if students uploaded since).")
    return rep


# ------------------------------------------------------------------- restore
def restore_db_from_snapshot(paths: Paths | None = None) -> Path:
    """Replace the live database with backup_staging/tracker_snapshot.db (current one is kept as .bak).

    The caller must close any open connection to the live database first.
    """
    paths = paths or get_paths()
    snap = paths.staging / SNAPSHOT_NAME
    if not snap.exists():
        raise FileNotFoundError("No snapshot found in backup_staging.")
    check = sqlite3.connect(str(snap))
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("The snapshot database is itself damaged; restore an older copy with Veeam instead.")
    finally:
        check.close()
    backup_copy = None
    if paths.db.exists():
        backup_copy = paths.db.with_name(f"tracker.db.pre_restore_{datetime.now():%Y%m%d-%H%M%S}.bak")
        shutil.copy2(paths.db, backup_copy)
    shutil.copy2(snap, paths.db)
    return backup_copy or paths.db
