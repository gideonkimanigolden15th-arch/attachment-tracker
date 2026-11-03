"""End-to-end test of everything except the Tkinter window.  Run:  python tests/smoke_test.py"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from attachment_tracker import backup, db, storage, streaks  # noqa: E402
from attachment_tracker.__main__ import main  # noqa: E402
from attachment_tracker.chart import render_cohort_chart, render_progress_chart  # noqa: E402
from attachment_tracker.config import get_paths  # noqa: E402
from attachment_tracker.studio import SIZES, THEMES, render_card  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))


def logbook_photo(path: Path, week: int, seed: int, layout: str = "kemu") -> Path:
    """Any photo will do now: the app no longer inspects logbook pages (students are trusted)."""
    img = Image.new("RGB", (1200, 1600), (250, 250, 246))
    d = ImageDraw.Draw(img)
    for i in range(12):
        d.line([(100, 200 + i * 100 + seed % 5), (1100, 200 + i * 100)], fill=(30, 40, 120), width=3)
    img.save(path, "JPEG", quality=85)
    return path


passed = 0


def check(cond: bool, label: str) -> None:
    global passed
    if not cond:
        raise AssertionError(f"FAILED: {label}")
    passed += 1
    print(f"  ok  {label}")


def fake_photo(path: Path, size=(1200, 1600), color=(150, 120, 90)) -> Path:
    im = Image.new("RGB", size, color)
    ImageDraw.Draw(im).ellipse((300, 300, 900, 1000), fill=(224, 172, 105))
    im.save(path, "JPEG")
    return path


def main_test() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="at_test_"))
    home = tmp / "data"
    src = tmp / "src"
    src.mkdir()
    paths = get_paths(home)
    conn = db.connect(paths.db)

    # Wednesday 2026-10-07 is in the week of Monday 2026-10-05 (today in the real session is Sun 2026-10-11)
    wed = datetime(2026, 10, 7, 10, 0)
    fri = datetime(2026, 10, 9, 15, 0)
    base_monday = date(2026, 10, 5)
    enrol = datetime(2026, 8, 1)

    print("students + upload order rule")
    s = storage.add_student(conn, "Wanjiru Kimani", "SC/2026/001", "Uni of Nairobi", created_at=enrol)
    try:
        storage.add_student(conn, "Dup", "SC/2026/001")
        check(False, "duplicate reg no rejected")
    except storage.RuleError:
        check(True, "duplicate reg no rejected")
    try:
        storage.save_submission(conn, paths, s, "face", fake_photo(src / "f.jpg"), wed)
        check(False, "face before logbook rejected")
    except storage.RuleError as e:
        check("logbook" in str(e).lower(), "face before logbook rejected")
    try:
        bad = src / "notes.txt"
        bad.write_text("not an image")
        storage.save_submission(conn, paths, s, "logbook", bad, wed)
        check(False, "non-image rejected")
    except storage.RuleError:
        check(True, "non-image rejected")
    try:
        storage.save_submission(conn, paths, s, "logbook", fake_photo(src / "tiny.jpg", (100, 100)), wed)
        check(False, "tiny image rejected")
    except storage.RuleError:
        check(True, "tiny image rejected")

    print("any-day uploads, weekly credit, streaks")
    # 6 consecutive weeks. Week 0 (current) uploaded on Wednesday; week -1 on Friday; others on Sunday/Monday.
    for w in range(6):
        monday = datetime.combine(base_monday - timedelta(weeks=w), datetime.min.time())
        when = monday + timedelta(days=[2, 4, 6, 0, 3, 5][w], hours=9)
        storage.save_submission(conn, paths, s, "logbook", logbook_photo(src / f"l{w}.jpg", w + 1, 10 + w), when)
        storage.save_submission(conn, paths, s, "face", fake_photo(src / f"p{w}.jpg"), when + timedelta(minutes=5))
    today = date(2026, 10, 11)  # Sunday of the current week
    check(streaks.current_streak(conn, s["id"], today) == 6, "6-week streak counted")
    check(streaks.best_streak(conn, s["id"]) == 6, "best streak = 6")
    stats = streaks.week_stats(conn, s["id"], today, 12)
    check(stats[-1].is_current and stats[-1].complete, "current week complete (uploaded Wednesday)")
    check(stats[-2].friday_upload and not stats[-1].friday_upload, "Friday uploads flagged only for that week")
    check(streaks.completion_pct(stats[-6:]) == 100, "100% over the six active weeks")

    # a gap: remove week -3 -> streak from today is 3
    conn.execute("DELETE FROM submissions WHERE week_start=?", ((base_monday - timedelta(weeks=3)).isoformat(),))
    conn.commit()
    check(streaks.current_streak(conn, s["id"], today) == 3, "gap breaks streak at 3")
    check(streaks.best_streak(conn, s["id"]) == 3, "best streak recomputed")

    # incomplete current week does not break the streak
    conn.execute("DELETE FROM submissions WHERE week_start=? AND task_key='face'", (base_monday.isoformat(),))
    conn.commit()
    check(streaks.current_streak(conn, s["id"], today) == 2, "in-progress week doesn't count but doesn't break")

    # restore week 0 face via the real API (logbook already present => allowed)
    storage.save_submission(conn, paths, s, "face", fake_photo(src / "again.jpg"), fri)
    check(streaks.current_streak(conn, s["id"], today) == 3, "re-upload completes the week again")

    check(storage.latest_submission(conn, s["id"], "face") is not None, "latest face lookup works")
    rel = storage.latest_submission(conn, s["id"], "face")["file_path"]
    check(not Path(rel).is_absolute() and "\\" not in rel, "stored paths are relative with forward slashes")

    s2 = storage.add_student(conn, "Otieno Mwangi", "SC/2026/002", created_at=enrol)
    storage.save_submission(conn, paths, s2, "logbook", logbook_photo(src / "o.jpg", 2, 77), wed)

    print("studio: every theme x size")
    face = Image.open(src / "p0.jpg")
    for t in THEMES:
        for k, (_, (w, h)) in SIZES.items():
            for streak in (0, 4):
                img = render_card(face, t.key, k, "Wanjiru Kimani", "Industrial Attachment 2026", streak)
                if img.size != (w, h):
                    raise AssertionError((t.key, k, img.size))
    check(True, f"{len(THEMES)} themes x {len(SIZES)} sizes x 2 render at the right dimensions")
    long = render_card(face, "neon", "wide", "A Very Long Student Name Indeed Mwangi-Otieno", "x" * 90, 12)
    check(long.size == (1200, 630), "very long name/caption still renders")
    exp = paths.exports / "card.png"
    render_card(face, "paper", "square", "Wanjiru", "Hello", 3).save(exp)
    storage.record_export(conn, paths, s, exp, wed)
    check("social" in streaks.week_stats(conn, s["id"], today)[-1].done, "export marks the social task")

    print("charts")
    c1 = render_progress_chart(streaks.week_stats(conn, s["id"], today))
    c2 = render_cohort_chart([("A", 3, 80), ("B", 0, 10)])
    c3 = render_progress_chart([])
    check(c1.size == (920, 380) and c2.width == 920 and c3.size == (920, 380), "charts render (incl. empty)")

    print("backup snapshot + verify")
    info = backup.prepare_snapshot(paths, today)
    check(info["students"] == 2 and info["file_count"] > 10, "snapshot written with manifest")
    for f in ("tracker_snapshot.db", "completion.csv", "cohort_overview.png", "manifest.json"):
        check((paths.staging / f).exists(), f"backup_staging/{f} exists")
    check(len(list((paths.staging / "progress_charts").glob("*.png"))) == 2, "one graph per student backed up")
    csv_lines = (paths.staging / "completion.csv").read_text().strip().splitlines()
    check(csv_lines[0].startswith("student,reg_no,week_start,logbook,face,social"), "completion.csv has header")
    rep = backup.verify(paths)
    check(rep.ok, f"verify passes on a clean install ({rep.checked} files)")
    check(backup.last_snapshot_info(paths)["students"] == 2, "last_snapshot_info readable")

    print("corruption detection")
    victim = paths.root / storage.latest_submission(conn, s["id"], "logbook")["file_path"]
    original = victim.read_bytes()
    victim.write_bytes(original[:-50] + b"X" * 50)
    check(not backup.verify(paths).ok, "corrupt photo detected")
    victim.write_bytes(original)
    check(backup.verify(paths).ok, "restoring the file clears the error")
    victim.unlink()
    rep = backup.verify(paths)
    check(not rep.ok and any("Missing" in e for e in rep.errors), "missing photo detected")
    victim.write_bytes(original)

    print("simulated Veeam restore to a different location")
    moved = tmp / "restored" / "elsewhere"
    shutil.copytree(home, moved)
    mp = get_paths(moved)
    check(backup.verify(mp).ok, "restored copy in a new folder verifies (relative paths)")
    mc = db.connect(mp.db)
    row = storage.latest_submission(mc, s["id"], "face")
    check(storage.abs_path(mp, row["file_path"]).exists(), "photo paths resolve in the new location")
    mc.close()

    print("database restore from snapshot")
    conn.execute("INSERT INTO students (full_name, reg_no, institution, created_at) VALUES ('Late','X9','',?)",
                 (datetime.now().isoformat(),))
    conn.commit()
    conn.close()
    kept = backup.restore_db_from_snapshot(paths)
    conn = db.connect(paths.db)
    names = [r["full_name"] for r in storage.list_students(conn)]
    check("Late" not in names and len(names) == 2, "live DB rolled back to snapshot")
    check(kept.exists() and kept.suffix == ".bak", "previous DB kept as .bak")
    paths.db.write_bytes(b"this is not a database" * 100)
    rep = backup.verify(paths)
    check(not rep.ok, "damaged database detected")
    conn.close()
    backup.restore_db_from_snapshot(paths)
    check(backup.verify(paths).ok, "damaged DB repaired from snapshot")

    print("command line (Veeam pre-job)")
    check(main(["--home", str(home), "--prepare-backup"]) == 0, "--prepare-backup exits 0")
    check(main(["--home", str(home), "--verify"]) == 0, "--verify exits 0 when healthy")
    json.loads((paths.staging / "manifest.json").read_text())
    victim.unlink()
    check(main(["--home", str(home), "--verify"]) == 1, "--verify exits 1 when a photo is missing")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nALL {passed} CHECKS PASSED")


if __name__ == "__main__":
    main_test()
