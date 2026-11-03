"""Skills lab: taxonomy, classifiers (with stand-ins for Hugging Face models), OCR cell cutting, store, report.
Run:  python tests/test_skills_lab.py     (needs scikit-learn, python-docx; Tesseract checks skip when it is not installed)"""
from __future__ import annotations

import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import logbook_fixtures as fx  # noqa: E402
from attachment_tracker import db, storage  # noqa: E402
from skills_lab import backends, evaluate, ocr, report, store  # noqa: E402
from skills_lab.taxonomy import BY_KEY, CATEGORIES, KEYS  # noqa: E402

passed = 0


def check(cond: bool, label: str) -> None:
    global passed
    if not cond:
        raise AssertionError(f"FAILED: {label}")
    passed += 1
    print(f"  ok  {label}")


def top(be, text):
    p = be.predict([text])[0]
    return p[0][0] if p else None


def main() -> None:
    print("taxonomy")
    check(len(KEYS) == len(set(KEYS)) == 10, "10 unique categories")
    check(all(c.description and c.keywords for c in CATEGORIES), "every category has a description and keywords")

    print("keyword baseline")
    kw = backends.get_backend("keyword")
    check(top(kw, "Configured the router and set static IP addresses") == "networking", "networking text -> networking")
    check(top(kw, "Troubleshot a printer that kept jamming") == "troubleshooting", "troubleshooting text")
    check(top(kw, "Configred the routr and DHCP scope") == "networking", "tolerates typos")
    check(kw.predict(["Went to the bank and had lunch"])[0] == [], "unrelated text gets no category")

    print("sample data + evaluation")
    rows = evaluate.load_csv(evaluate.DEFAULT_DATA)
    check(len(rows) == 190 and {r["split"] for r in rows} == {"seed", "test", "blind"}, "sample CSV loads (seed/test/blind)")
    res = evaluate.run(backends=["keyword", "tfidf"])
    check(set(res) == {"keyword", "tfidf"} and all(r["top1"] > 0.5 for r in res.values()), "offline backends beat 50% top-1")
    res = evaluate.run(backends=["embed_zeroshot", "nli_zeroshot"]) if not _has_hf() else {}
    check(isinstance(res, dict), "missing Hugging Face packages are skipped, not a crash")

    print("Hugging Face backends wired with stand-ins (no model downloads)")

    class FakeEncoder:  # bag-of-letters vectors: enough to prove the plumbing, says nothing about real accuracy
        def encode(self, texts):
            out = np.zeros((len(texts), 26))
            for i, t in enumerate(texts):
                for ch in t.lower():
                    if "a" <= ch <= "z":
                        out[i, ord(ch) - 97] += 1
            return out

    zs = backends.EmbeddingZeroShotBackend(encoder=FakeEncoder())
    sc = zs.scores(["router and switch cabling"])
    check(sc.shape == (1, 10), "embedding zero-shot returns one score per category")
    lr = backends.EmbeddingLogRegBackend(encoder=FakeEncoder())
    seed = [r for r in rows if r["split"] == "seed"]
    lr.fit([r["text"] for r in seed], [r["gold"] for r in seed])
    check(len(lr.predict(["fixed the printer"])) == 1, "embeddings + logistic regression trains and predicts")

    def fake_pipe(texts, candidate_labels, hypothesis_template, multi_label):
        out = []
        for t in texts:
            scores = [0.9 if ("router" in t.lower() and "network" in lab.lower()) else 0.05 for lab in candidate_labels]
            out.append({"labels": list(candidate_labels), "scores": scores})
        return out

    nli = backends.NliZeroShotBackend(pipe=fake_pipe)
    check(top(nli, "Installed a router") == "networking", "NLI zero-shot maps pipeline output back to categories")

    print("OCR: cutting a logbook photo into day cells")
    T = ["Configured a TP-Link router and assigned static IP addresses to the lab PCs",
         "Troubleshot a printer that kept jamming and replaced the fuser",
         "Installed Windows 11 and updated device drivers",
         "Set up a MySQL database backup script",
         "Wrote a weekly report and attended a team meeting"]
    page = fx.make_page("kemu", 3, seed=1, handwriting=False, texts=T)
    photo = fx.photograph(page, seed=2)
    cells = ocr.extract_day_cells(photo)
    check(len(cells) == 5 and [c.label for c in cells][:2] == ["Monday", "Tuesday"], "5 day cells found on a phone-style photo")
    check(all(c.ink > 0.02 for c in cells), "cells with writing have ink")
    blank = fx.photograph(fx.make_page("kemu", 4, seed=2, handwriting=False), seed=3)
    check(all(c.ink < 0.002 for c in ocr.extract_day_cells(blank)), "empty cells are detected as empty")
    lines = ocr.split_lines(cells[0].image)
    check(1 <= len(lines) <= 3, f"line splitter finds the text lines ({len(lines)})")
    try:
        ocr.extract_day_cells(fx.make_ruled_paper())
        check(False, "no table must raise")
    except ValueError:
        check(True, "a page without the table raises a clear error")

    class FakeProc:
        def __call__(self, images, return_tensors):
            class R: pixel_values = np.zeros((1, 1))
            return R()

        def batch_decode(self, ids, skip_special_tokens):
            return ["line text"]

    class FakeModel:
        def generate(self, pv, max_new_tokens):
            return [[1]]

    tr = ocr.TrOCREngine(processor=FakeProc(), model=FakeModel())
    check(tr.read(cells[0].image).text.startswith("line text"), "TrOCR engine wiring works with a stand-in model")

    try:
        eng = ocr.TesseractEngine()
    except ocr.OcrUnavailable:
        eng = None
        print("  --  Tesseract not installed: typed-page OCR check skipped")
    if eng:
        drafts = ocr.read_page(photo, eng)
        got = [d.text.lower() for d in drafts]
        check(sum("router" in g for g in got) == 1 and any("mysql" in g for g in got), "Tesseract reads typed text from the photo")
        check(all(not d.empty for d in drafts), "no cell wrongly skipped as empty")

    print("store + classify + report")
    td = Path(tempfile.mkdtemp(prefix="skills_test_"))
    conn = db.connect(td / "t.db")
    stu = storage.add_student(conn, "Test Student", "T/9", "Test Uni", datetime(2026, 6, 1))
    store.ensure(conn)
    wk = date(2026, 6, 1)
    eid = store.upsert_entry(conn, stu["id"], wk, 0, "Configured the router", source="ocr:tesseract", ocr_conf=90)
    store.upsert_entry(conn, stu["id"], wk, 1, "Troubleshot a printer fault")
    kwb = backends.get_backend("keyword")
    check(store.classify_student(conn, stu["id"], kwb) == 2, "classify_student tags both entries")
    check(store.classify_student(conn, stu["id"], kwb) == 0, "second run tags nothing new (only_missing)")
    store.set_skills(conn, eid, [("networking", 1.0)], "student", confirmed=True)
    check(store.skills_of(conn, eid)[0]["confirmed"] == 1, "student-confirmed tag saved")
    store.upsert_entry(conn, stu["id"], wk, 0, "Configured the router")
    check(len(store.skills_of(conn, eid)) == 1, "same text keeps its tags")
    store.upsert_entry(conn, stu["id"], wk, 0, "Cleaned the server room")
    check(store.skills_of(conn, eid) == [], "edited text clears the old tags")
    store.upsert_entry(conn, stu["id"], wk, 0, "Configured the router")
    store.classify_student(conn, stu["id"], kwb)
    for key in ("logbook", "face"):
        conn.execute("INSERT INTO submissions (student_id, task_key, week_start, uploaded_at, uploaded_weekday, file_path)"
                     " VALUES (?,?,?,?,?,?)", (stu["id"], key, wk.isoformat(), "2026-06-05T10:00:00", 4, "x"))
    conn.commit()

    out = report.build_report(conn, stu["id"], td / "r.docx", organisation="Acme", supervisor="Jane", hours_per_day=8)
    from docx import Document
    doc = Document(out)
    text = "\n".join(p.text for p in doc.paragraphs) + "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    for needle in ("INDUSTRIAL ATTACHMENT REPORT", "Test Student", "T/9", "Acme", "16 h (2 days x 8 h)", "Networking",
                   "Troubleshooting", "Daily activity log", "Sign-off"):
        check(needle in text, f"report contains {needle!r}")
    out2 = report.build_report(conn, stu["id"], td / "r2.docx")
    t2 = "\n".join(c.text for t in Document(out2).tables for r in t.rows for c in r.cells)
    check("Not recorded by the app" in t2, "hours are left blank unless supplied (never invented)")
    empty = storage.add_student(conn, "New Student", "T/10", "", datetime(2026, 6, 1))
    check(report.build_report(conn, empty["id"], td / "r3.docx").exists(), "report for a student with no entries still builds")

    print(f"\nALL {passed} SKILLS LAB CHECKS PASSED")


def _has_hf() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        import transformers  # noqa: F401
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    main()
