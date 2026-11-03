# Attachment Tracker

Desktop app for students on an attachment (industrial placement) programme.

1. Pick your name (or add yourself).
2. **Upload** a photo of your logbook, then a face photo holding a pen (this order is enforced).
3. **Studio**: turn the face photo into a social media card (6 themes, 3 sizes) and export it.
4. **My Progress**: weekly task-completion graph, streak, and a cohort overview.
5. **Backup & Restore**: everything is stored in one folder that Veeam backs up.

## Run it

```
py -m pip install -r requirements.txt
py -m attachment_tracker
```

Requires Python 3.10+ with Tkinter (included in the standard Windows installer). Make a Windows .exe with `build_exe.bat`.

## Programme rules (hard-coded in `attachment_tracker/tasks.py`)

* Task 1: logbook photo. Task 2: face photo holding a pen, only after the logbook that week.
* Task 3 (bonus): export a social media card.
* **Streak day is Friday**, but students can upload **any day**; an upload counts for the Monday-Sunday week it
  was made in. A week with tasks 1 and 2 done adds one to the streak. The current week never breaks a streak
  while still in progress. Missing a full week resets it.
* Uploads made on a Friday get a gold diamond on the graph.

Change wording, add tasks, or move the streak day by editing `tasks.py` only.

## Get the app as a normal Windows program (no Python, no scripts)

The app is packaged by GitHub itself, so nobody has to run build scripts:

1. Put this folder in a **public** GitHub repository (for example `attachment-tracker`). Private repositories cannot give anonymous downloads.
2. Tag a release: `git tag v1.5.0` then `git push origin v1.5.0`. The workflow in `.github/workflows/build-windows.yml` builds
   `AttachmentTracker-Setup.exe` (installer with icon, Start menu and desktop shortcut) and `AttachmentTracker-portable.zip`
   on a Windows machine and attaches them to the release. About 10 minutes. You can also run it by hand from the Actions tab.
3. Open `download-page/index.html` (edit the `REPO` line near the bottom to your `owner/name`) and host it, for example with
   GitHub Pages (Settings, Pages, deploy from branch, copy `download-page/index.html` into a `docs` folder), or any web host.
   Students open that page and press **Download for Windows**.

The installer is not code-signed, so Windows SmartScreen shows "Windows protected your PC" once; the page tells students to click More info, Run anyway.
Student data is kept in `Documents\AttachmentTracker` and is not removed by uninstalling.
Building on your own PC instead: `pip install pyinstaller`, then `python -m PyInstaller packaging/AttachmentTracker.spec`. The icon is drawn by `packaging/make_icon.py`.

## Logbook photos (trust-based)

Earlier versions tried to recognise the institute logbook (bordered table, same layout every week, supervisor reset).
That was dropped: students are trusted to upload their own filled-in logbook page, and the supervisor can compare the
stored photos against the paper logbook when needed. The app only checks that the file is a readable image of a sensible size.

**Photo sizes:** face photos need a short side of at least 100 px, logbook photos a long side of at least 640 px.
The message always shows the size of the photo that was refused.

## Window size, zoom and small screens

The window opens sized to fit your screen (it was too tall for 768 px laptop screens in v1.0 and v1.1), can be resized or
maximised freely, and every tab scrolls when the window is small. Use the **Zoom** box (top right, 80% to 150%) or
**Ctrl +**, **Ctrl -**, **Ctrl 0** to make everything bigger or smaller; the choice is remembered. On Windows the app is
high-DPI aware, so text stays sharp at 125% / 150% display scaling. The window title shows the version
(`Attachment Tracker v1.5.0`), so you can always tell which copy is running.

## Where the data lives

`Documents\AttachmentTracker` by default (override with `--home <folder>` or env `ATTACHMENT_TRACKER_HOME`):

```
db\tracker.db   uploads\logbooks\   uploads\faces\   exports\   backup_staging\
```

Database file paths are relative, so a restore to another drive or folder just works.

## Veeam

See **veeam/VEEAM_SETUP.md**. In short: file-level Veeam job on the data folder, with `veeam/pre-job.bat`
as the pre-job script (it runs `--prepare-backup`). After any restore, run `--verify`
(or **Backup & Restore > Verify data**).

Command line:

```
AttachmentTracker.exe --prepare-backup   snapshot for Veeam (exit 0 ok / 1 failed)
AttachmentTracker.exe --verify           database + photo + manifest check (exit 0 ok / 1 problems)
```

## Tests

```
python tests/smoke_test.py
python tests/test_skills_lab.py
python tests/gui_test.py      # opens the real window (needs a display; use xvfb-run on a server)
```

`gui_test.py` drives the real window, including the Supervisor tab. `test_skills_lab.py` covers the optional skills lab. `smoke_test.py` covers upload rules, streak logic, all themes and sizes, snapshot/verify, corruption and missing-file detection,
restore to a different folder, database rollback, and the command line exit codes.

## Notes and limits

* Student selection is a drop-down with no passwords (fine for a supervised lab). If students share a PC and
  must not see each other's data, set `SHOW_COHORT = False` in `config.py` and consider adding a PIN.
* Photos are chosen from files (phone photos copied over, or a webcam app's output). Live webcam capture is a natural next step.
* Veeam is not driven through its API: it backs up the folder, and this app makes the folder consistent before the
  job and checks it after a restore.

## New in 1.3: skills lab (prototype, separate from the window)

`skills_lab/` reads the day entries from a stored logbook photo (Tesseract or Hugging Face TrOCR), tags them with IT
skill categories (networking, troubleshooting, ...), and builds a Word attachment report. It is not wired into the
Tkinter window yet. Start with `skills_lab/GUIDE.md`; quick try: `python -m skills_lab demo` and
`python -m skills_lab evaluate`. Extra packages: `pip install -r skills_lab/requirements.txt`.
Hugging Face models were not testable in the build environment, so no accuracy figures for them are claimed.
