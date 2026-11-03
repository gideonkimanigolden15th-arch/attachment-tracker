"""Build the industrial-attachment time & skills report (a Word .docx) from what is stored in tracker.db.

Everything in the report comes from the database: the weeks that have a verified logbook photo, the day entries (typed
or read by OCR) and the skill tags. Nothing is invented. Two things the app does NOT know are left to the student and
supervisor: working hours (only included when you pass hours_per_day) and the signatures.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from . import store
from .taxonomy import BY_KEY, CATEGORIES

ACCENT = RGBColor(0x1F, 0x4E, 0x79)
GREY = RGBColor(0x59, 0x59, 0x59)
DAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _shade(cell, hex_fill: str) -> None:
    pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    pr.append(shd)


def _repeat_header(row) -> None:
    pr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    pr.append(el)


def _table(doc: Document, header: list[str], rows: list[list[str]], widths_cm: list[float]):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold = True
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        _shade(c, "1F4E79")
    _repeat_header(t.rows[0])
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(v))
            run.font.size = Pt(9.5)
    for i, w in enumerate(widths_cm):
        t.columns[i].width = Cm(w)
    for row in t.rows:
        for i, w in enumerate(widths_cm):
            row.cells[i].width = Cm(w)
    return t


def _h(doc: Document, text: str, level: int = 1) -> None:
    p = doc.add_heading(text, level=level)
    for r in p.runs:
        r.font.color.rgb = ACCENT
        r.font.name = "Calibri"


def _note(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.italic = True
    r.font.size = Pt(9)
    r.font.color.rgb = GREY


def collect(conn: sqlite3.Connection, student_id: int) -> dict:
    """Gather everything the report needs into plain Python structures (also handy for tests)."""
    store.ensure(conn)
    st = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    if st is None:
        raise ValueError(f"no student with id {student_id}")
    log_weeks = sorted({date.fromisoformat(r["week_start"]) for r in conn.execute(
        "SELECT week_start FROM submissions WHERE student_id=? AND task_key='logbook'", (student_id,))})
    face_weeks = {date.fromisoformat(r["week_start"]) for r in conn.execute(
        "SELECT week_start FROM submissions WHERE student_id=? AND task_key='face'", (student_id,))}
    ents = [dict(e) for e in store.entries(conn, student_id) if e["text"].strip()]
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for e in ents:
        e["skills"] = [dict(s) for s in store.skills_of(conn, e["id"])]
        for s in e["skills"]:
            by_cat[s["category"]].append(e)
    days = [date.fromisoformat(e["entry_date"]) for e in ents]
    first = min(days + log_weeks[:1], default=None)
    last = max(days + [w + timedelta(days=6) for w in log_weeks[-1:]], default=None)
    return {"student": dict(st), "log_weeks": log_weeks, "face_weeks": face_weeks, "entries": ents,
            "by_category": by_cat, "first": first, "last": last}


def build_report(conn: sqlite3.Connection, student_id: int, out_path: str | Path, *, organisation: str = "",
                 supervisor: str = "", hours_per_day: float | None = None, sample_banner: str = "",
                 generated: date | None = None) -> Path:
    d = collect(conn, student_id)
    s = d["student"]
    ents, log_weeks, by_cat = d["entries"], d["log_weeks"], d["by_category"]
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2)
    sec.top_margin = sec.bottom_margin = Cm(1.8)
    base = doc.styles["Normal"]
    base.font.name, base.font.size = "Calibri", Pt(10.5)

    if sample_banner:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(sample_banner)
        r.bold = True
        r.font.size = Pt(10)
        r.font.color.rgb = RGBColor(0xC0, 0x39, 0x2B)

    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("INDUSTRIAL ATTACHMENT REPORT")
    r.bold, r.font.size, r.font.color.rgb = True, Pt(20), ACCENT
    t2 = doc.add_paragraph()
    t2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t2.add_run("Time record and skills gained")
    r.font.size, r.font.color.rgb = Pt(12), GREY

    # ---- details
    n_logged_days = len(ents)
    complete = [w for w in log_weeks if w in d["face_weeks"]]
    rows = [["Student", s["full_name"]], ["Registration no.", s["reg_no"]], ["Institution", s["institution"] or "-"],
            ["Host organisation", organisation or "-"], ["Industry supervisor", supervisor or "-"]]
    if d["first"] and d["last"]:
        rows.append(["Period covered by the logbook", f"{d['first']:%d %b %Y} to {d['last']:%d %b %Y}"])
    rows += [["Weeks with a verified logbook photo", str(len(log_weeks))],
             ["Weeks fully complete (logbook + face photo)", str(len(complete))],
             ["Days with a logbook entry", str(n_logged_days)]]
    if hours_per_day:
        rows.append(["Hours worked (days logged x hours per day)",
                     f"{n_logged_days * hours_per_day:g} h ({n_logged_days} days x {hours_per_day:g} h)"])
    else:
        rows.append(["Hours worked", "Not recorded by the app: to be completed by the student/supervisor"])
    tb = _table(doc, ["Item", "Detail"], rows, [6.5, 10.5])
    for row in tb.rows[1:]:
        row.cells[0].paragraphs[0].runs[0].bold = True

    # ---- summary
    _h(doc, "1. Summary", 1)
    ranked = sorted(by_cat.items(), key=lambda kv: -len({e["id"] for e in kv[1]}))
    if ents and ranked:
        top = ", ".join(f"{BY_KEY[k].name} ({len({e['id'] for e in v})} days)" for k, v in ranked[:3])
        doc.add_paragraph(
            f"During the attachment {s['full_name']} recorded work on {n_logged_days} days across {len(log_weeks)} "
            f"logbook weeks. The areas that appear most often in the daily entries are {top}. "
            f"Sections 2-4 give the week-by-week record, the skills by category with the entries that support them, "
            f"and the full daily log.")
    else:
        doc.add_paragraph("No daily entries have been recorded yet, so there is no skills summary to show.")

    # ---- weekly time record
    _h(doc, "2. Weekly record", 1)
    wk_rows = []
    by_week: dict[str, list[dict]] = defaultdict(list)
    for e in ents:
        by_week[e["week_start"]].append(e)
    for i, w in enumerate(log_weeks, 1):
        es = by_week.get(w.isoformat(), [])
        cats = defaultdict(int)
        for e in es:
            for sk in e["skills"]:
                cats[sk["category"]] += 1
        main = ", ".join(BY_KEY[k].name for k, _ in sorted(cats.items(), key=lambda kv: -kv[1])[:2]) or "-"
        wk_rows.append([str(i), f"{w:%d %b} - {w + timedelta(days=6):%d %b %Y}", str(len(es)),
                        "Yes" if w in d["face_weeks"] else "No", main])
    if wk_rows:
        _table(doc, ["Wk", "Dates", "Days logged", "Face photo", "Main skill areas"], wk_rows, [1.2, 4.6, 2.2, 2.2, 6.8])
    else:
        doc.add_paragraph("No logbook weeks recorded yet.")
    if not hours_per_day:
        _note(doc, "Hours are not captured by the app. Add them by hand, or regenerate the report with the hours per day.")

    # ---- skills
    _h(doc, "3. Skills gained by category", 1)
    if ranked:
        _note(doc, "Each daily entry was matched to one or more categories by the classifier, and the student could correct "
                   "the tags. 'Confirmed' counts tags the student checked.")
        srows = []
        for c in CATEGORIES:
            es = {e["id"]: e for e in by_cat.get(c.key, [])}
            if not es:
                continue
            conf = sum(1 for e in es.values() for sk in e["skills"] if sk["category"] == c.key and sk["confirmed"])
            wks = len({e["week_start"] for e in es.values()})
            srows.append((len(es), [c.name, str(len(es)), str(wks), str(conf)]))
        srows.sort(key=lambda x: -x[0])
        _table(doc, ["Category", "Days of evidence", "Weeks", "Confirmed"], [r for _, r in srows], [7.5, 3.5, 2.5, 3.5])
        for c in CATEGORIES:
            es = sorted(by_cat.get(c.key, []), key=lambda e: e["entry_date"])
            uniq = list({e["id"]: e for e in es}.values())
            if not uniq:
                continue
            _h(doc, c.name, 2)
            for e in uniq[:3]:
                p = doc.add_paragraph(style="List Bullet")
                p.add_run(f"{date.fromisoformat(e['entry_date']):%d %b}: ").bold = True
                p.add_run(e["text"])
            if len(uniq) > 3:
                _note(doc, f"+ {len(uniq) - 3} more day(s) in the daily log.")
    else:
        doc.add_paragraph("No tagged entries yet.")

    # ---- daily log
    _h(doc, "4. Daily activity log", 1)
    if ents:
        rows = []
        for e in sorted(ents, key=lambda e: e["entry_date"]):
            dt = date.fromisoformat(e["entry_date"])
            tags = ", ".join(BY_KEY[sk["category"]].name for sk in e["skills"]) or "-"
            rows.append([f"{DAY[dt.weekday()]} {dt:%d %b %y}", e["text"], tags])
        _table(doc, ["Date", "Work done", "Skill areas"], rows, [2.8, 9.4, 4.8])
    else:
        doc.add_paragraph("No entries.")

    # ---- method
    _h(doc, "5. How this report was produced", 1)
    doc.add_paragraph(
        "The weekly logbook photo was stored by the Attachment Tracker. The day entries were either typed by the student "
        "or read from the photo by an OCR program, and the student was asked to correct the text. A text classifier then "
        "proposed the skill areas for each entry. Automatic reading of handwriting and automatic tagging both make "
        "mistakes, so this report is a summary of the logbook, not a replacement for it: the signed paper logbook "
        "remains the official record.")

    _h(doc, "6. Sign-off", 1)
    sg = doc.add_table(rows=3, cols=2)
    for i, (a, b) in enumerate([("Student", s["full_name"]), ("Industry supervisor", supervisor or ""),
                                ("Institution supervisor", "")]):
        sg.rows[i].cells[0].text = f"{a}: {b}"
        sg.rows[i].cells[1].text = "Signature: ______________________   Date: ____________"
    gen = generated or date.today()
    _note(doc, f"Generated {gen:%d %b %Y} by Attachment Tracker.")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out
