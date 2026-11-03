"""Tkinter desktop UI: student picker + Upload, Studio, Progress, Backup and Supervisor tabs."""
from __future__ import annotations

import os
import shutil
import sys
import tkinter as tk
import tkinter.font as tkfont
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from . import __version__, backup, db, storage, streaks
from .chart import render_progress_chart
from .config import SHOW_COHORT, Paths
from .studio import SIZES, THEMES, THEME_MAP, render_card
from .tasks import DEFAULT_CAPTION, PROGRAM_NAME, RULES, STREAK_DAY_NAME, STREAK_WEEKDAY, WEEKLY_TASKS

IMG_TYPES = [("Photos", "*.jpg *.jpeg *.png *.webp *.bmp"), ("All files", "*.*")]
BG = "#f8fafc"


ASSETS = Path(__file__).resolve().parent / "assets"  # also correct inside a PyInstaller build (data is bundled next to the package)


def set_window_icon(win: tk.Misc) -> None:
    """Title-bar / taskbar icon. Never fatal: a missing icon file must not stop the app."""
    try:
        if sys.platform.startswith("win") and (ASSETS / "icon.ico").exists():
            win.iconbitmap(default=str(ASSETS / "icon.ico"))
        elif (ASSETS / "icon.png").exists():
            img = tk.PhotoImage(file=str(ASSETS / "icon.png"))
            win.iconphoto(True, img)
            win._icon_ref = img  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


def thumb(path: Path, box: tuple[int, int]) -> ImageTk.PhotoImage | None:
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail(box)
            return ImageTk.PhotoImage(im)
    except Exception:  # noqa: BLE001 - a missing/corrupt preview must never crash the UI
        return None


def pil_to_tk(img: Image.Image, box: tuple[int, int] | None = None) -> ImageTk.PhotoImage:
    if box:
        img = img.copy()
        img.thumbnail(box)
    return ImageTk.PhotoImage(img)


def open_folder(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception:  # noqa: BLE001
        messagebox.showinfo("Folder", str(path))


CUSTOM_FONTS = {  # name: (family, points, weight)  - sizes are multiplied by the Zoom setting
    "AppTitle": ("Segoe UI", 15, "bold"), "AppHead": ("Segoe UI", 13, "bold"), "AppBold": ("Segoe UI", 10, "bold"),
    "AppMono": ("Consolas", 10, "bold"), "AppMonoSm": ("Consolas", 10, "normal"),
}
DEFAULT_FONTS = ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont", "TkFixedFont", "TkTooltipFont",
                 "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont")


def flow(widget, pad: int = 90):
    """Mark a wrapping label: ScrollHost re-wraps it to (window width - pad) whenever the window is resized."""
    widget._flow_pad = pad
    return widget


class ScrollHost(ttk.Frame):
    """One notebook page. Scrolls vertically when the window is small and re-wraps long text to the window width."""

    def __init__(self, master):
        super().__init__(master)
        self.zoom = 1.0  # set by App.set_zoom: fixed paddings around wrapped text grow with the font
        bg = ttk.Style(master).lookup("TFrame", "background") or BG
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=bg)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)

    def _on_inner(self, _e=None) -> None:
        # the page keeps its natural height (so a change in wrapped text is always seen here)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, e) -> None:
        self.canvas.itemconfigure(self._win, width=e.width)
        self._fit_wraps(self.inner, e.width)
        self.after_idle(self._on_inner)

    def _fit_wraps(self, widget, width: int) -> None:
        for child in widget.winfo_children():
            pad = getattr(child, "_flow_pad", None)
            if pad is not None:
                want = max(260, width - int(pad * self.zoom))
                try:
                    have = int(float(str(child.cget("wraplength")) or 0))
                except ValueError:
                    have = 0
                if have != want:
                    child.configure(wraplength=want)
            self._fit_wraps(child, width)

    def scroll(self, units: int) -> None:
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(units, "units")


# ======================================================================= tabs
class UploadTab(ttk.Frame):
    def __init__(self, master: ttk.Notebook, app: "App"):
        super().__init__(master, padding=16)
        self.app = app
        self._imgs: dict[str, ImageTk.PhotoImage | None] = {}

        self.columnconfigure(0, weight=1)
        self.week_lbl = ttk.Label(self, font="AppTitle")
        self.week_lbl.grid(row=0, column=0, columnspan=2, sticky="w")
        self.banner = flow(tk.Label(self, anchor="w", justify="left", padx=10, pady=8, wraplength=860, bg="#e0f2fe", fg="#0c4a6e"), 80)
        self.banner.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 10))

        rules = ttk.LabelFrame(self, text="How it works", padding=10)
        rules.grid(row=2, column=0, columnspan=2, sticky="ew")
        for r in RULES:
            flow(ttk.Label(rules, text="• " + r, wraplength=840, justify="left"), 100).pack(anchor="w", pady=1)

        self.status: dict[str, tk.StringVar] = {}
        tasks = ttk.LabelFrame(self, text="This week's tasks", padding=10)
        tasks.grid(row=3, column=0, columnspan=2, sticky="ew", pady=10)
        for t in WEEKLY_TASKS:
            row = ttk.Frame(tasks)
            row.pack(fill="x", pady=4)
            var = tk.StringVar(value="[ ]")
            self.status[t.key] = var
            ttk.Label(row, textvariable=var, width=10, font="AppMono").pack(side="left", anchor="n", padx=(0, 10))
            col = ttk.Frame(row)
            col.pack(side="left", fill="x", expand=True)
            ttk.Label(col, text=t.title, font="AppBold").pack(anchor="w")
            flow(ttk.Label(col, text=t.instructions, wraplength=520, foreground="#475569", justify="left"),
                 220).pack(anchor="w")

        btns = ttk.Frame(self)
        btns.grid(row=4, column=0, columnspan=2, sticky="w")
        self.btn_logbook = ttk.Button(btns, text="1. Upload logbook photo", command=lambda: self.upload("logbook"))
        self.btn_logbook.pack(side="left", padx=(0, 8))
        self.btn_face = ttk.Button(btns, text="2. Upload face photo (with pen)", command=lambda: self.upload("face"))
        self.btn_face.pack(side="left")

        prev = ttk.Frame(self)
        prev.grid(row=5, column=0, columnspan=2, sticky="w", pady=12)
        self.prev_lbl: dict[str, ttk.Label] = {}
        for i, (key, title) in enumerate((("logbook", "Latest logbook photo"), ("face", "Latest face photo"))):
            box = ttk.LabelFrame(prev, text=title, padding=6)
            box.grid(row=0, column=i, padx=(0, 12))
            lbl = ttk.Label(box, text="(none this week)", width=34, anchor="center")
            lbl.pack()
            self.prev_lbl[key] = lbl

    def refresh(self) -> None:
        s = self.app.student
        today = date.today()
        wk = storage.week_start(today)
        self.week_lbl.config(text=f"Week of {wk:%d %b} to {wk + timedelta(days=6):%d %b %Y}")
        is_streak_day = today.weekday() == STREAK_WEEKDAY
        if not s:
            self.banner.config(text="Pick your name at the top, or add yourself with 'New student'.")
            for v in self.status.values():
                v.set("[ ]")
            self.btn_logbook.state(["disabled"])
            self.btn_face.state(["disabled"])
            return
        streak = streaks.current_streak(self.app.conn, s["id"])
        if is_streak_day:
            msg = f"It's {STREAK_DAY_NAME}: streak day! Finish tasks 1 and 2 today to add to your {streak}-week streak."
        else:
            msg = (f"Streak day is {STREAK_DAY_NAME}, but you can upload any day and it counts for this week. "
                   f"Current streak: {streak} week(s).")
        self.banner.config(text=msg, bg="#fef3c7" if is_streak_day else "#e0f2fe", fg="#78350f" if is_streak_day else "#0c4a6e")

        done = {t.key: storage.has_task(self.app.conn, s["id"], t.key, wk) for t in WEEKLY_TASKS}
        for k, v in self.status.items():
            v.set("[x] done" if done[k] else "[ ] to do")
        self.btn_logbook.state(["!disabled"])
        self.btn_face.state(["!disabled"] if done["logbook"] else ["disabled"])
        for key in ("logbook", "face"):
            row = storage.latest_submission(self.app.conn, s["id"], key, wk)
            img = thumb(storage.abs_path(self.app.paths, row["file_path"]), (260, 200)) if row else None
            self._imgs[key] = img
            self.prev_lbl[key].config(image=img or "", text="" if img else "(none this week)")

    def upload(self, key: str) -> None:
        s = self.app.student
        if not s:
            messagebox.showinfo("Pick a student", "Choose your name at the top first.")
            return
        src = filedialog.askopenfilename(title="Choose a photo", filetypes=IMG_TYPES)
        if not src:
            return
        try:
            storage.save_submission(self.app.conn, self.app.paths, s, key, src)
        except storage.RuleError as exc:
            messagebox.showwarning("Cannot upload", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Upload failed", f"Something went wrong:\n{exc}")
            return
        if key == "face":
            self.app.studio.invalidate()
        self.app.refresh_all()
        if key == "face":
            messagebox.showinfo("Face photo saved", "Great! Now make your social media card in the Studio tab.")
            self.app.show(self.app.studio)
        else:
            messagebox.showinfo("Logbook saved", "Logbook photo saved. Now upload your face photo holding a pen.")


class StudioTab(ttk.Frame):
    def __init__(self, master: ttk.Notebook, app: "App"):
        super().__init__(master, padding=16)
        self.app = app
        self._face: Image.Image | None = None
        self._current: Image.Image | None = None
        self._tk: ImageTk.PhotoImage | None = None
        self._after = None

        ctl = ttk.Frame(self)
        ctl.pack(side="left", fill="y", padx=(0, 16))
        self.theme_var = tk.StringVar(value=THEMES[0].name)
        self.size_var = tk.StringVar(value=SIZES["square"][0])
        self.name_var = tk.StringVar()
        self.cap_var = tk.StringVar(value=DEFAULT_CAPTION)
        self.src_var = tk.StringVar(value="(no face photo yet)")

        ttk.Label(ctl, text="Theme / template").pack(anchor="w")
        cb = ttk.Combobox(ctl, textvariable=self.theme_var, values=[t.name for t in THEMES], state="readonly", width=40)
        cb.pack(anchor="w", pady=(0, 8))
        cb.bind("<<ComboboxSelected>>", lambda e: self.schedule())
        ttk.Label(ctl, text="Format").pack(anchor="w")
        cs = ttk.Combobox(ctl, textvariable=self.size_var, values=[v[0] for v in SIZES.values()], state="readonly", width=40)
        cs.pack(anchor="w", pady=(0, 8))
        cs.bind("<<ComboboxSelected>>", lambda e: self.schedule())
        ttk.Label(ctl, text="Name on card").pack(anchor="w")
        e1 = ttk.Entry(ctl, textvariable=self.name_var, width=42)
        e1.pack(anchor="w", pady=(0, 8))
        ttk.Label(ctl, text="Caption").pack(anchor="w")
        e2 = ttk.Entry(ctl, textvariable=self.cap_var, width=42)
        e2.pack(anchor="w", pady=(0, 8))
        for e in (e1, e2):
            e.bind("<KeyRelease>", lambda ev: self.schedule())
        ttk.Label(ctl, text="Photo used").pack(anchor="w")
        ttk.Label(ctl, textvariable=self.src_var, wraplength=250, foreground="#475569").pack(anchor="w")
        ttk.Button(ctl, text="Use a different photo…", command=self.pick_photo).pack(anchor="w", pady=(4, 14))
        ttk.Button(ctl, text="Export card", command=self.export).pack(anchor="w", fill="x")
        ttk.Button(ctl, text="Save a copy as…", command=self.save_copy).pack(anchor="w", fill="x", pady=(6, 0))
        ttk.Label(ctl, text="Exports are saved in your exports folder\nand count as the bonus task.",
                  foreground="#64748b").pack(anchor="w", pady=10)

        self.preview = ttk.Label(self, anchor="center", text="Upload your face photo to start")
        self.preview.pack(side="left", expand=True, fill="both")
        self._last_w = 0
        self._rz = None
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, e) -> None:
        if abs(e.width - self._last_w) < 8:
            return
        self._last_w = e.width
        if self._rz:
            self.after_cancel(self._rz)
        self._rz = self.after(150, self._show_current)

    def _show_current(self) -> None:
        self._rz = None
        if self._current is None:
            return
        w = self.winfo_width()
        across = max(240, min(620, w - 360)) if w > 1 else 560
        down = max(240, min(620, self.winfo_toplevel().winfo_height() - 220))
        self._tk = pil_to_tk(self._current, (across, down))
        self.preview.config(image=self._tk, text="")

    # -- helpers
    def _theme_key(self) -> str:
        return next((t.key for t in THEMES if t.name == self.theme_var.get()), THEMES[0].key)

    def _size_key(self) -> str:
        return next((k for k, v in SIZES.items() if v[0] == self.size_var.get()), "square")

    def invalidate(self) -> None:
        """Forget the loaded photo so the next refresh picks up the newest face upload."""
        self._face = None

    def refresh(self) -> None:
        s = self.app.student
        sid = s["id"] if s else None
        if sid != getattr(self, "_sid", None):
            self._face = None
        self._sid = sid
        if self._face is not None:  # keep the current photo (including a manually chosen one)
            return
        if not s:
            self.src_var.set("(no student selected)")
            self.preview.config(image="", text="Pick a student first")
            return
        if not self.name_var.get() or self.name_var.get() != s["full_name"]:
            self.name_var.set(s["full_name"])
        row = storage.latest_submission(self.app.conn, s["id"], "face")
        if row:
            self.load_photo(storage.abs_path(self.app.paths, row["file_path"]), f"Latest face photo ({row['uploaded_at'][:10]})")
        else:
            self.src_var.set("(no face photo yet)")
            self.preview.config(image="", text="Upload your face photo first")

    def load_photo(self, path: Path, label: str) -> None:
        try:
            with Image.open(path) as im:
                self._face = ImageOps.exif_transpose(im).convert("RGB")
        except Exception:  # noqa: BLE001
            self._face = None
            messagebox.showwarning("Photo", "That photo could not be opened.")
            return
        self.src_var.set(label)
        self.render()

    def pick_photo(self) -> None:
        p = filedialog.askopenfilename(title="Choose a photo", filetypes=IMG_TYPES)
        if p:
            self.load_photo(Path(p), Path(p).name)

    def schedule(self) -> None:
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(150, self.render)

    def render(self) -> None:
        self._after = None
        if self._face is None or not self.app.student:
            return
        try:
            streak = streaks.current_streak(self.app.conn, self.app.student["id"])
            self._current = render_card(self._face, self._theme_key(), self._size_key(),
                                        self.name_var.get(), self.cap_var.get(), streak)
            self._show_current()
        except Exception as exc:  # noqa: BLE001
            self.preview.config(image="", text=f"Could not draw the card: {exc}")

    def export(self) -> None:
        if self._current is None:
            messagebox.showinfo("Studio", "Upload your face photo first.")
            return
        s = self.app.student
        name = f"{storage.safe_name(s['reg_no'])}_{self._theme_key()}_{self._size_key()}_{datetime.now():%Y%m%d-%H%M%S}.png"
        out = self.app.paths.exports / name
        self._current.save(out, "PNG")
        storage.record_export(self.app.conn, self.app.paths, s, out)
        self.app.refresh_all()
        messagebox.showinfo("Card exported", f"Saved:\n{out}\n\nBonus task done for this week!")

    def save_copy(self) -> None:
        if self._current is None:
            return
        p = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("JPEG image", "*.jpg")])
        if p:
            self._current.save(p)


class ProgressTab(ttk.Frame):
    def __init__(self, master: ttk.Notebook, app: "App"):
        super().__init__(master, padding=16)
        self.app = app
        self._tk: ImageTk.PhotoImage | None = None
        self._chart_pil: Image.Image | None = None
        self._last_w = 0
        self._rz = None
        self.bind("<Configure>", self._on_resize)
        self.summary = ttk.Label(self, font="AppHead")
        self.summary.pack(anchor="w")
        self.chart = ttk.Label(self)
        self.chart.pack(anchor="w", pady=10)
        self.tree = None
        if SHOW_COHORT:
            box = ttk.LabelFrame(self, text="Cohort overview", padding=6)
            box.pack(fill="both", expand=True)
            self.tree = ttk.Treeview(box, columns=("name", "reg", "streak", "pct"), show="headings", height=7)
            for col, txt, w in (("name", "Student", 260), ("reg", "Reg. no", 160), ("streak", "Streak (weeks)", 120), ("pct", "Completion", 110)):
                self.tree.heading(col, text=txt)
                self.tree.column(col, width=w, anchor="w")
            self.tree.pack(fill="both", expand=True)

    def _on_resize(self, e) -> None:
        if abs(e.width - self._last_w) < 8:
            return
        self._last_w = e.width
        if self._rz:
            self.after_cancel(self._rz)
        self._rz = self.after(150, self._show_chart)

    def _show_chart(self) -> None:
        self._rz = None
        if self._chart_pil is None:
            self.chart.config(image="", text="")
            return
        w = self.winfo_width()
        self._tk = pil_to_tk(self._chart_pil, (max(380, min(1000, w - 60)) if w > 1 else 900, 700))
        self.chart.config(image=self._tk, text="")

    def refresh(self) -> None:
        conn = self.app.conn
        s = self.app.student
        if s:
            stats = streaks.week_stats(conn, s["id"])
            streak, best = streaks.current_streak(conn, s["id"]), streaks.best_streak(conn, s["id"])
            self.summary.config(text=f"{s['full_name']}: {streak}-week streak (best {best}), "
                                     f"{streaks.completion_pct(stats)}% of required tasks done")
            self._chart_pil = render_progress_chart(stats, "Your weekly task completion")
        else:
            self.summary.config(text="Pick a student to see their progress")
            self._chart_pil = None
        self._show_chart()
        if self.tree is not None:
            self.tree.delete(*self.tree.get_children())
            for st in storage.list_students(conn):
                stats = streaks.week_stats(conn, st["id"])
                self.tree.insert("", "end", values=(st["full_name"], st["reg_no"],
                                                    streaks.current_streak(conn, st["id"]),
                                                    f"{streaks.completion_pct(stats)}%"))


class BackupTab(ttk.Frame):
    def __init__(self, master: ttk.Notebook, app: "App"):
        super().__init__(master, padding=16)
        self.app = app
        ttk.Label(self, text="Backup and restore (Veeam)", font="AppTitle").pack(anchor="w")
        flow(ttk.Label(self, wraplength=860, justify="left", foreground="#475569", text=(
            "All photos, the database and the graph data live in one data folder. Veeam backs up that folder. "
            "'Prepare backup snapshot' makes a consistent copy (database, completion CSV, graphs and a checksum list) "
            "inside it; the Veeam pre-job script does this automatically before each job. "
            "After a Veeam restore, use 'Verify data'. See veeam/VEEAM_SETUP.md.")), 60).pack(anchor="w", pady=(4, 10))
        self.folder_var = tk.StringVar()
        self.info_var = tk.StringVar()
        ttk.Label(self, textvariable=self.folder_var, font="AppMonoSm").pack(anchor="w")
        ttk.Label(self, textvariable=self.info_var, foreground="#334155").pack(anchor="w", pady=(2, 10))
        row = ttk.Frame(self)
        row.pack(anchor="w")
        for i, (text, cmd) in enumerate((("Prepare backup snapshot", self.prepare), ("Verify data", self.verify),
                                         ("Restore database from snapshot", self.restore),
                                         ("Open data folder", self.open_data))):
            ttk.Button(row, text=text, command=cmd).grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 8), pady=3)
        self.log = tk.Text(self, height=14, wrap="word", state="disabled", bg="white")
        self.log.pack(fill="both", expand=True, pady=12)

    def say(self, text: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", f"[{datetime.now():%H:%M:%S}] {text}\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def refresh(self) -> None:
        self.folder_var.set(f"Data folder: {self.app.paths.root}")
        info = backup.last_snapshot_info(self.app.paths)
        self.info_var.set(
            f"Last snapshot: {info['created_at'].replace('T', ' ')} ({info['students']} students, {info['file_count']} files)"
            if info else "No snapshot yet.")

    def prepare(self) -> None:
        try:
            info = backup.prepare_snapshot(self.app.paths)
            self.say(f"Snapshot ready: {info['students']} students, {info['submissions']} submissions, {info['file_count']} files.")
        except Exception as exc:  # noqa: BLE001
            self.say(f"Snapshot FAILED: {exc}")
        self.refresh()

    def verify(self) -> None:
        self.say(backup.verify(self.app.paths).summary())

    def restore(self) -> None:
        if not messagebox.askyesno("Restore database",
                                   "Replace the current database with the last snapshot?\n"
                                   "Anything recorded after the snapshot will be lost (a .bak copy of the current one is kept)."):
            return
        try:
            self.app.conn.close()
            kept = backup.restore_db_from_snapshot(self.app.paths)
            self.say(f"Database restored from snapshot. Previous database kept as: {kept.name}")
        except Exception as exc:  # noqa: BLE001
            self.say(f"Restore FAILED: {exc}")
        finally:
            self.app.conn = db.connect(self.app.paths.db)
            self.app.reload_students()
        self.say(backup.verify(self.app.paths).summary())

    def open_data(self) -> None:
        open_folder(self.app.paths.root)


class SupervisorTab(ttk.Frame):
    """PIN-protected overview for the supervisor: who has uploaded what, and the stored photos to compare with the paper logbook."""

    COLS = (("name", "Student", 170), ("reg_no", "Reg. no.", 110), ("logbook_weeks", "Logbook weeks", 100),
            ("complete_weeks", "Complete weeks", 105), ("streak", "Streak", 60), ("last_upload", "Last upload", 100))

    def __init__(self, master: ttk.Notebook, app: "App"):
        super().__init__(master, padding=16)
        self.app = app
        self.unlocked = False
        self._img: ImageTk.PhotoImage | None = None
        ttk.Label(self, text="Supervisor", font="AppTitle").pack(anchor="w")
        self.msg = flow(ttk.Label(self, wraplength=820, justify="left", foreground="#475569"), 60)
        self.msg.pack(anchor="w", pady=(2, 8))

        self.lock_box = ttk.Frame(self)
        self.pin_var, self.pin2_var = tk.StringVar(), tk.StringVar()
        ttk.Label(self.lock_box, text="PIN").grid(row=0, column=0, sticky="w")
        self.pin_entry = ttk.Entry(self.lock_box, textvariable=self.pin_var, show="*", width=18)
        self.pin_entry.grid(row=0, column=1, padx=6, pady=2)
        self.pin2_lbl = ttk.Label(self.lock_box, text="Repeat PIN")
        self.pin2_entry = ttk.Entry(self.lock_box, textvariable=self.pin2_var, show="*", width=18)
        self.go = ttk.Button(self.lock_box, text="Unlock", command=self.submit)
        self.go.grid(row=0, column=2, padx=6)
        self.pin_entry.bind("<Return>", lambda e: self.submit())
        self.pin2_entry.bind("<Return>", lambda e: self.submit())

        self.work = ttk.Frame(self)
        self.tree = ttk.Treeview(self.work, columns=[c[0] for c in self.COLS], show="headings", height=10, selectmode="browse")
        for key, title, w in self.COLS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=w, anchor="w" if key in ("name", "reg_no") else "center")
        self.tree.pack(fill="x")
        self.tree.bind("<Double-1>", lambda e: self.view())
        bar = ttk.Frame(self.work)
        bar.pack(anchor="w", pady=10)
        ttk.Button(bar, text="View submitted photos", command=self.view).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="Open student's folder", command=self.open_folder_).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="Change PIN", command=self.change_pin).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="Lock", command=self.lock).pack(side="left")

    # -- locking
    def lock(self) -> None:
        self.unlocked = False
        self.pin_var.set("")
        self.pin2_var.set("")
        self.work.pack_forget()
        self._layout_lock()

    def _layout_lock(self) -> None:
        first = not storage.has_supervisor_pin(self.app.conn)
        self.msg.config(text=("Create a supervisor PIN. It protects this page, which shows every student's progress and photos."
                              if first else "Enter the supervisor PIN to see all students' progress and submitted photos."))
        if first:
            self.pin2_lbl.grid(row=1, column=0, sticky="w")
            self.pin2_entry.grid(row=1, column=1, padx=6, pady=2)
            self.go.config(text="Create PIN")
        else:
            self.pin2_lbl.grid_remove()
            self.pin2_entry.grid_remove()
            self.go.config(text="Unlock")
        self.lock_box.pack(anchor="w")

    def submit(self) -> None:
        conn = self.app.conn
        try:
            if not storage.has_supervisor_pin(conn):
                if self.pin_var.get() != self.pin2_var.get():
                    raise storage.RuleError("The two PINs are not the same.")
                storage.set_supervisor_pin(conn, self.pin_var.get())
            elif not storage.check_supervisor_pin(conn, self.pin_var.get()):
                raise storage.RuleError("That PIN is not correct.")
        except storage.RuleError as exc:
            messagebox.showwarning("Supervisor", str(exc))
            return
        self.unlocked = True
        self.pin_var.set("")
        self.pin2_var.set("")
        self.lock_box.pack_forget()
        self.msg.config(text="Students' progress. Select a student and open their submitted photos to compare with the paper logbook. "
                             "This page locks again when you leave it.")
        self.work.pack(fill="x")
        self.refresh()

    def change_pin(self) -> None:
        win = tk.Toplevel(self)
        win.title("Change PIN")
        win.transient(self.winfo_toplevel())
        vars_ = [tk.StringVar() for _ in range(3)]
        for i, label in enumerate(("Current PIN", "New PIN", "Repeat new PIN")):
            ttk.Label(win, text=label).grid(row=i, column=0, padx=10, pady=4, sticky="w")
            ttk.Entry(win, textvariable=vars_[i], show="*", width=20).grid(row=i, column=1, padx=10, pady=4)

        def save() -> None:
            try:
                if vars_[1].get() != vars_[2].get():
                    raise storage.RuleError("The two new PINs are not the same.")
                storage.change_supervisor_pin(self.app.conn, vars_[0].get(), vars_[1].get())
            except storage.RuleError as exc:
                messagebox.showwarning("Change PIN", str(exc), parent=win)
                return
            messagebox.showinfo("Change PIN", "PIN changed.", parent=win)
            win.destroy()
        ttk.Button(win, text="Save", command=save).grid(row=3, column=1, sticky="e", padx=10, pady=10)

    # -- content
    def refresh(self) -> None:
        if not self.unlocked:
            self._layout_lock()
            return
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for r in storage.student_overview(self.app.conn):
            self.tree.insert("", "end", iid=str(r["id"]), values=[r[c[0]] for c in self.COLS])
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])

    def _selected(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Supervisor", "Select a student in the list first.")
            return None
        return int(sel[0])

    def open_folder_(self) -> None:
        sid = self._selected()
        if sid is None:
            return
        row = self.app.conn.execute("SELECT reg_no FROM students WHERE id=?", (sid,)).fetchone()
        folder = self.app.paths.logbooks / storage.safe_name(row["reg_no"])
        open_folder(folder if folder.exists() else self.app.paths.root)

    def view(self) -> None:
        """A window with the student's stored photos, one week at a time (logbook and face side by side)."""
        sid = self._selected()
        if sid is None:
            return
        conn = self.app.conn
        name = conn.execute("SELECT full_name FROM students WHERE id=?", (sid,)).fetchone()["full_name"]
        logs = {r["week_start"]: r for r in reversed(storage.submissions_of(conn, sid, "logbook"))}
        faces = {r["week_start"]: r for r in reversed(storage.submissions_of(conn, sid, "face"))}
        weeks = sorted(set(logs) | set(faces), reverse=True)
        if not weeks:
            messagebox.showinfo("Supervisor", f"{name} has not uploaded any photos yet.")
            return
        win = tk.Toplevel(self)
        win.title(f"Submitted photos: {name}")
        win.geometry("980x640")
        lb = tk.Listbox(win, width=22, exportselection=False)
        lb.pack(side="left", fill="y", padx=(8, 0), pady=8)
        right = ttk.Frame(win)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        panes = {}
        for i, (key, title) in enumerate((("logbook", "Logbook photo"), ("face", "Face photo"))):
            box = ttk.LabelFrame(right, text=title, padding=6)
            box.grid(row=0, column=i, sticky="n", padx=4)
            panes[key] = ttk.Label(box, text="(none)")
            panes[key].pack()
        keep: dict[str, ImageTk.PhotoImage | None] = {}
        for w in weeks:
            d = date.fromisoformat(w)
            lb.insert("end", f"Week of {d:%d %b %Y}")

        def show(_e=None) -> None:
            if not lb.curselection():
                return
            w = weeks[lb.curselection()[0]]
            for key, src in (("logbook", logs), ("face", faces)):
                row = src.get(w)
                img = thumb(storage.abs_path(self.app.paths, row["file_path"]), (440, 560)) if row else None
                keep[key] = img
                panes[key].config(image=img or "", text="" if img else "(none this week)")
        lb.bind("<<ListboxSelect>>", show)
        lb.selection_set(0)
        show()
        win._keep = keep  # type: ignore[attr-defined]  # keeps the PhotoImages alive


# ======================================================================== app
class App(tk.Tk):
    ZOOMS = (80, 90, 100, 110, 125, 150)

    def __init__(self, paths: Paths):
        super().__init__()
        set_window_icon(self)
        self.title(f"Attachment Tracker v{__version__} - {PROGRAM_NAME}")
        self.configure(bg=BG)
        self.paths = paths
        self.conn = db.connect(paths.db)
        self.student = None
        self._students: list = []

        # ---- window: fits the screen (768 px laptop screens are common), centred, freely resizable
        base = float(self.tk.call("tk", "scaling"))
        k = max(1.0, base / 1.3333)  # 1.0 at 96 dpi, 1.5 at 150 % Windows scaling
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(int(1100 * k), int(sw * 0.94)), min(int(820 * k), int(sh * 0.86))
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 4)}")
        self.minsize(min(int(700 * k), sw), min(int(440 * k), sh))

        # ---- fonts: named fonts, so the Zoom control can resize every label live
        self._zoom = 100
        self._font_base: dict[str, int] = {}
        for name in DEFAULT_FONTS:
            try:
                self._font_base[name] = int(tkfont.nametofont(name, root=self).cget("size"))
            except tk.TclError:
                pass
        # Segoe UI / Consolas exist on Windows; elsewhere fall back to the system's own scalable fonts
        have = set(tkfont.families(self))
        sans = tkfont.nametofont("TkDefaultFont", root=self).actual("family")
        mono = tkfont.nametofont("TkFixedFont", root=self).actual("family")
        self._fonts = []  # keep references: Tk deletes a named font as soon as its Python object is freed
        for name, (family, size, weight) in CUSTOM_FONTS.items():
            fallback = mono if family == "Consolas" else sans
            self._fonts.append(tkfont.Font(root=self, name=name, family=family if family in have else fallback,
                                           size=size, weight=weight))
            self._font_base[name] = size

        top = ttk.Frame(self, padding=(16, 10))
        top.pack(fill="x")
        ttk.Label(top, text="Student:", font="AppBold").pack(side="left")
        self.pick = ttk.Combobox(top, state="readonly", width=36)
        self.pick.pack(side="left", padx=8)
        self.pick.bind("<<ComboboxSelected>>", self.on_pick)
        ttk.Button(top, text="New student", command=self.new_student).pack(side="left")
        self.zoom_var = tk.StringVar(value="100%")
        zoom = ttk.Combobox(top, textvariable=self.zoom_var, values=[f"{z}%" for z in self.ZOOMS], state="readonly", width=6)
        zoom.pack(side="right")
        ttk.Label(top, text="Zoom:").pack(side="right", padx=(0, 6))
        zoom.bind("<<ComboboxSelected>>", lambda e: self.set_zoom(int(self.zoom_var.get().rstrip("%"))))

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._host: dict = {}

        def add(cls, title):
            host = ScrollHost(self.nb)
            tab = cls(host.inner, self)
            tab.pack(fill="both", expand=True)
            self.nb.add(host, text=title)
            self._host[tab] = host
            return tab

        self.upload = add(UploadTab, "Upload")
        self.studio = add(StudioTab, "Studio")
        self.progress = add(ProgressTab, "My Progress")
        self.backup_tab = add(BackupTab, "Backup & Restore")
        self.supervisor = add(SupervisorTab, "Supervisor")
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self.refresh_all())

        # mouse wheel scrolls the current page; Ctrl + / - / 0 change the zoom
        self.bind_all("<MouseWheel>", self._wheel)
        self.bind_all("<Button-4>", lambda e: self._wheel(e, 1))
        self.bind_all("<Button-5>", lambda e: self._wheel(e, -1))
        for seq, step in (("<Control-plus>", 1), ("<Control-equal>", 1), ("<Control-KP_Add>", 1),
                          ("<Control-minus>", -1), ("<Control-KP_Subtract>", -1)):
            self.bind_all(seq, lambda e, st=step: self.step_zoom(st))
        self.bind_all("<Control-0>", lambda e: self.set_zoom(100))

        saved = storage.get_setting(self.conn, "ui_zoom", "100")
        self.set_zoom(int(saved) if saved.isdigit() else 100, save=False)
        self.reload_students()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---- zoom / scrolling
    def set_zoom(self, pct: int, save: bool = True) -> None:
        pct = min(self.ZOOMS, key=lambda z: abs(z - pct))
        self._zoom = pct
        for name, base in self._font_base.items():
            size = round(abs(base) * pct / 100) * (1 if base > 0 else -1)
            try:
                tkfont.nametofont(name, root=self).configure(size=size)
            except tk.TclError:
                pass
        line = tkfont.nametofont("TkDefaultFont", root=self).metrics("linespace")
        ttk.Style(self).configure("Treeview", rowheight=int(line * 1.5))
        self.zoom_var.set(f"{pct}%")
        for host in self._host.values():
            host.zoom = pct / 100
            host._fit_wraps(host.inner, host.canvas.winfo_width())
        if save:
            try:
                storage.set_setting(self.conn, "ui_zoom", str(pct))
            except Exception:  # noqa: BLE001 - zoom is a convenience, never fatal
                pass
        self.update_idletasks()

    def step_zoom(self, direction: int) -> None:
        i = self.ZOOMS.index(self._zoom)
        self.set_zoom(self.ZOOMS[max(0, min(len(self.ZOOMS) - 1, i + direction))])

    def show(self, tab) -> None:
        self.nb.select(self._host[tab])

    def _wheel(self, event, direction: int | None = None) -> None:
        if isinstance(event.widget, (tk.Text, tk.Listbox, ttk.Treeview)):
            return  # these scroll themselves
        if direction is None:
            direction = 1 if event.delta > 0 else -1
        try:
            self.nametowidget(self.nb.select()).scroll(-direction * 3)
        except (KeyError, tk.TclError, AttributeError):
            pass

    def reload_students(self, select_id: int | None = None) -> None:
        self._students = storage.list_students(self.conn)
        self.pick["values"] = [f"{s['full_name']} ({s['reg_no']})" for s in self._students]
        idx = next((i for i, s in enumerate(self._students) if s["id"] == select_id), None)
        if idx is None and self.student is not None:
            idx = next((i for i, s in enumerate(self._students) if s["id"] == self.student["id"]), None)
        if idx is not None:
            self.pick.current(idx)
            self.student = self._students[idx]
        else:
            self.pick.set("")
            self.student = None
        self.refresh_all()

    def on_pick(self, _evt=None) -> None:
        i = self.pick.current()
        self.student = self._students[i] if 0 <= i < len(self._students) else None
        self.refresh_all()

    def refresh_all(self) -> None:
        if self.nb.select() != str(self._host[self.supervisor]):  # leaving the Supervisor tab locks it again
            self.supervisor.lock()
        for tab in (self.upload, self.studio, self.progress, self.backup_tab, self.supervisor):
            tab.refresh()

    def new_student(self) -> None:
        win = tk.Toplevel(self)
        win.title("New student")
        win.transient(self)
        win.grab_set()
        vars_ = {k: tk.StringVar() for k in ("name", "reg", "inst")}
        for r, (label, key) in enumerate((("Full name", "name"), ("Registration number", "reg"), ("Institution (optional)", "inst"))):
            ttk.Label(win, text=label).grid(row=r, column=0, sticky="w", padx=12, pady=(10, 0))
            ttk.Entry(win, textvariable=vars_[key], width=36).grid(row=r, column=1, padx=12, pady=(10, 0))

        def save() -> None:
            try:
                s = storage.add_student(self.conn, vars_["name"].get(), vars_["reg"].get(), vars_["inst"].get())
            except storage.RuleError as exc:
                messagebox.showwarning("New student", str(exc), parent=win)
                return
            win.destroy()
            self.reload_students(select_id=s["id"])

        ttk.Button(win, text="Save", command=save).grid(row=3, column=1, sticky="e", padx=12, pady=12)

    def on_close(self) -> None:
        try:  # safety net: refresh the Veeam-ready snapshot on exit
            backup.prepare_snapshot(self.paths)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.conn.close()
        finally:
            self.destroy()


def _enable_hidpi() -> None:
    """Windows: draw crisp text at the user's display scaling instead of a blurry bitmap-scaled window,
    and give the app its own taskbar identity so the taskbar shows our icon (not Python's)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AttachmentTracker.App")
            except (AttributeError, OSError):
                pass
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError, OSError):
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def run_app(paths: Paths) -> None:
    _enable_hidpi()
    App(paths).mainloop()
