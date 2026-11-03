"""Drives the REAL Tkinter window (needs Tkinter and a display).  Run:  python tests/gui_test.py
On a machine without a display (e.g. a server) use:  xvfb-run -a python tests/gui_test.py
Skips itself politely when Tkinter or a display is not available."""
from __future__ import annotations

import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import filedialog, messagebox
except ImportError:
    print("SKIPPED: Tkinter is not installed")
    sys.exit(0)

from PIL import Image  # noqa: E402

import logbook_fixtures as fx  # noqa: E402
from attachment_tracker import ui, storage  # noqa: E402
from attachment_tracker.config import get_paths  # noqa: E402

passed = 0


def check(cond: bool, label: str) -> None:
    global passed
    if not cond:
        raise AssertionError(f"FAILED: {label}")
    passed += 1
    print(f"  ok  {label}")


def main() -> None:
    home = Path(tempfile.mkdtemp(prefix="gui_test_"))
    paths = get_paths(home)
    try:
        app = ui.App(paths)
    except tk.TclError as exc:
        print(f"SKIPPED: no display available ({exc})")
        return

    def pump(n: int = 5) -> None:
        for _ in range(n):
            app.update_idletasks()
            app.update()
            time.sleep(0.05)

    shown: list[tuple[str, str]] = []
    messagebox.showinfo = lambda *a, **k: shown.append(("info", a[1] if len(a) > 1 else ""))
    messagebox.showwarning = lambda *a, **k: shown.append(("warn", a[1] if len(a) > 1 else ""))
    messagebox.showerror = lambda *a, **k: shown.append(("err", a[1] if len(a) > 1 else ""))
    messagebox.askyesno = lambda *a, **k: True
    ui.messagebox = messagebox

    print("window fits the screen and has a title with the version")
    pump()
    sw, sh = app.winfo_screenwidth(), app.winfo_screenheight()
    check(app.winfo_height() <= sh and app.winfo_width() <= sw, f"window {app.winfo_width()}x{app.winfo_height()} fits a {sw}x{sh} screen")
    check("v" in app.title() and "Attachment Tracker" in app.title(), f"title shows the version: {app.title()!r}")

    print("every tab scrolls when the window is small")
    app.geometry("760x470")
    pump(8)
    for tab in (app.upload, app.studio, app.progress, app.backup_tab, app.supervisor):
        app.show(tab)
        pump(6)
        host = app._host[tab]
        region = [float(v) for v in str(host.canvas.cget("scrollregion")).split()]
        need = host.inner.winfo_reqheight()
        check(region and region[3] >= need - 2, f"{type(tab).__name__}: scroll region ({int(region[3])}px) covers its content ({need}px)")
    app.show(app.upload)
    pump()
    host = app._host[app.upload]
    host.canvas.yview_moveto(1.0)
    pump()
    check(host.canvas.yview()[0] > 0, "Upload page scrolls down to reach the bottom")
    host.canvas.yview_moveto(0)

    print("long text re-wraps to the window width (nothing clipped on the right)")
    for width in (760, 1000, 1300):
        app.geometry(f"{width}x700")
        pump(8)
        cw = host.canvas.winfo_width()
        widest = 0
        stack = [app.upload]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            if getattr(w, "_flow_pad", None) is not None:
                widest = max(widest, w.winfo_rootx() + w.winfo_reqwidth() - host.canvas.winfo_rootx())
        check(widest <= cw + 2, f"at {width}px wide the wrapped text ends at {widest}px of {cw}px")

    print("zoom resizes the text live and is remembered")
    app.show(app.upload)
    sizes = {}
    for z in (80, 100, 150):
        app.set_zoom(z)
        pump(6)
        sizes[z] = (int(tkfont.nametofont("AppTitle", root=app).cget("size")), int(tkfont.nametofont("TkDefaultFont", root=app).cget("size")))
    check(sizes[80][0] < sizes[100][0] < sizes[150][0], f"heading font grows with zoom {sizes}")
    check(sizes[80][1] < sizes[100][1] < sizes[150][1], "default font grows with zoom too")
    check(storage.get_setting(app.conn, "ui_zoom") == "150", "zoom saved in the database")
    app.step_zoom(-1)
    check(app._zoom == 125, "Ctrl+minus steps down one level")
    app.set_zoom(100)
    check(app.zoom_var.get() == "100%", "zoom box shows the current level")

    print("uploading through the real window")
    s = storage.add_student(app.conn, "Test Student", "T/1")
    app.reload_students(select_id=s["id"])
    src = home / "src"
    src.mkdir()
    face = src / "face.jpg"
    Image.new("RGB", (240, 320), (90, 120, 160)).save(face)  # the size that was being refused
    page = src / "page.jpg"
    fx.photograph(fx.make_page("kemu", 2, seed=5), seed=5).save(page, "JPEG", quality=85)
    pick = {"f": str(face)}
    filedialog.askopenfilename = lambda **k: pick["f"]
    ui.filedialog = filedialog

    app.upload.upload("face")
    check(shown[-1][0] == "warn" and "logbook" in shown[-1][1].lower(), "face before logbook is refused with a clear message")
    pick["f"] = str(page)
    app.upload.upload("logbook")
    check(shown[-1][0] == "info" and storage.has_task(app.conn, s["id"], "logbook", storage.week_start(datetime.now().date())), "logbook photo accepted and stored")
    pump()
    pick["f"] = str(face)
    app.upload.upload("face")
    check(shown[-1][0] == "info", "240x320 face photo accepted (was 'too small' in v1.0)")

    print("studio and progress draw")
    app.show(app.studio)
    pump(8)
    check(app.studio._current is not None and app.studio._current.size == (1080, 1080), "Studio card rendered")
    check(app.studio.preview.cget("image") != "", "Studio preview is showing")
    app.studio.export()
    check(list(paths.exports.glob("*.png")) != [], "card exported")
    app.show(app.progress)
    pump(8)
    check(app.progress.chart.cget("image") != "", "Progress chart is showing")
    app.geometry("800x560")
    pump(10)
    check(app.progress.chart.cget("image") != "", "chart still shows after a resize")

    print("supervisor tab")
    sv = app.supervisor
    app.show(sv)
    pump()
    check(not sv.unlocked, "locked at first")
    sv.pin_var.set("4821")
    sv.pin2_var.set("4822")
    sv.submit()
    check(not sv.unlocked and shown[-1][0] == "warn", "mismatched PINs are refused")
    sv.pin_var.set("4821")
    sv.pin2_var.set("4821")
    sv.submit()
    check(sv.unlocked, "PIN created and tab unlocked")
    check(str(s["id"]) in sv.tree.get_children(), "student listed with progress")
    vals = sv.tree.item(str(s["id"]), "values")
    check(vals[2] == "1", f"overview counts the logbook week ({vals})")
    sv.lock()
    sv.pin_var.set("0000")
    sv.submit()
    check(not sv.unlocked and shown[-1][0] == "warn", "wrong PIN refused")
    sv.pin_var.set("4821")
    sv.submit()
    check(sv.unlocked, "right PIN unlocks")
    sv.tree.selection_set(str(s["id"]))
    sv.view()
    pump()
    wins = [w for w in sv.winfo_children() if isinstance(w, tk.Toplevel)]
    check(bool(wins) and wins[-1].title().startswith("Submitted photos"), "photo viewer opens for the student")
    wins[-1].destroy()
    app.show(app.upload)
    pump()
    check(not sv.unlocked, "leaving the tab locks it again")

    print("backup tab buttons")
    app.backup_tab.prepare()
    app.backup_tab.verify()
    check("Snapshot ready" in app.backup_tab.log.get("1.0", "end"), "snapshot message appears in the log")

    app.on_close()
    print(f"\nALL {passed} GUI CHECKS PASSED")


if __name__ == "__main__":
    main()
