"""Command line for the skills lab.

    python -m skills_lab evaluate [--data my.csv] [--backends keyword tfidf | all] [--cv 5] [--per-category] [--model NAME]
    python -m skills_lab ocr  PHOTO.jpg [--engine tesseract|trocr] [--csv out.csv]
    python -m skills_lab report --home DATA_DIR --student-id 1 --out report.docx [--hours 8] [--org X] [--supervisor Y]
    python -m skills_lab demo --out demo_report.docx          # builds a clearly-labelled SAMPLE report from synthetic data
"""
from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path


def _cmd_evaluate(a) -> int:
    from .evaluate import run
    run(a.data, a.backends, a.cv, a.per_category, a.model)
    return 0


def _cmd_ocr(a) -> int:
    from PIL import Image
    from . import ocr
    try:
        eng = ocr.get_engine(a.engine)
        drafts = ocr.read_page(Image.open(a.photo), eng)
    except (ocr.OcrUnavailable, ValueError) as exc:
        print(f"Cannot read this page: {exc}")
        return 1
    for d in drafts:
        flag = "(empty)" if d.empty else (f"[conf {d.conf:.0f}]" if d.conf is not None else "")
        print(f"{d.label:10s} {flag:12s} {d.text}")
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["day", "text", "conf"])
            w.writerows([[d.label, d.text, d.conf] for d in drafts])
        print(f"saved {a.csv}")
    return 0


def _cmd_report(a) -> int:
    from attachment_tracker.config import get_paths
    from attachment_tracker import db
    from . import store
    from .backends import get_backend
    from .report import build_report
    paths = get_paths(Path(a.home))
    conn = db.connect(paths.db)
    store.ensure(conn)
    be = get_backend(a.backend)
    if be.needs_training:
        from .evaluate import DEFAULT_DATA, load_csv
        rows = load_csv(a.train or DEFAULT_DATA)
        be.fit([r["text"] for r in rows], [r["gold"] for r in rows])
    n = store.classify_student(conn, a.student_id, be)
    print(f"tagged {n} entries with '{be.name}'")
    out = build_report(conn, a.student_id, a.out, organisation=a.org, supervisor=a.supervisor, hours_per_day=a.hours)
    print(f"report written: {out}")
    return 0


def _cmd_demo(a) -> int:
    from attachment_tracker import db, storage
    from . import store
    from .backends import get_backend
    from .evaluate import DEFAULT_DATA, load_csv
    from .report import build_report
    td = Path(tempfile.mkdtemp(prefix="skills_demo_"))
    conn = db.connect(td / "tracker.db")
    stu = storage.add_student(conn, "Sample Student", "SAMPLE/0000", "Sample University", datetime(2026, 6, 1))
    store.ensure(conn)
    rows = [r for r in load_csv(DEFAULT_DATA) if r["split"] == "blind"][:30]
    wk0 = date(2026, 6, 1)
    for i, r in enumerate(rows):
        wk = wk0 + timedelta(weeks=i // 5)
        store.upsert_entry(conn, stu["id"], wk, i % 5, r["text"], source="typed", confirmed=True)
    for w in sorted({wk0 + timedelta(weeks=i // 5) for i in range(len(rows))}):
        for key in ("logbook", "face"):
            conn.execute("INSERT INTO submissions (student_id, task_key, week_start, uploaded_at, uploaded_weekday, file_path)"
                         " VALUES (?,?,?,?,?,?)", (stu["id"], key, w.isoformat(), w.isoformat() + "T10:00:00", 4, "demo"))
    conn.commit()
    be = get_backend("tfidf")
    seed = [r for r in load_csv(DEFAULT_DATA) if r["split"] == "seed"]
    be.fit([r["text"] for r in seed], [r["gold"] for r in seed])
    store.classify_student(conn, stu["id"], be)
    out = build_report(conn, stu["id"], a.out, organisation="Sample Company Ltd", supervisor="Sample Supervisor",
                       hours_per_day=8,
                       sample_banner="SAMPLE REPORT - built from synthetic entries, not a real student",
                       generated=date(2026, 8, 7))
    print(f"demo report written: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="skills_lab", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--data")
    e.add_argument("--backends", nargs="+", default=None)
    e.add_argument("--cv", type=int, default=0)
    e.add_argument("--per-category", action="store_true")
    e.add_argument("--model")
    e.set_defaults(fn=_cmd_evaluate)
    o = sub.add_parser("ocr")
    o.add_argument("photo")
    o.add_argument("--engine", default="tesseract", choices=["tesseract", "trocr"])
    o.add_argument("--csv")
    o.set_defaults(fn=_cmd_ocr)
    r = sub.add_parser("report")
    r.add_argument("--home", required=True)
    r.add_argument("--student-id", type=int, required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--backend", default="tfidf")
    r.add_argument("--train")
    r.add_argument("--hours", type=float)
    r.add_argument("--org", default="")
    r.add_argument("--supervisor", default="")
    r.set_defaults(fn=_cmd_report)
    d = sub.add_parser("demo")
    d.add_argument("--out", default="demo_report.docx")
    d.set_defaults(fn=_cmd_demo)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
