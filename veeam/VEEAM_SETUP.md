# Backing up and restoring Attachment Tracker with Veeam

The app keeps **everything** (database, logbook photos, face photos, exported cards, graph data)
under one folder, so Veeam only needs to protect that folder.

> Menu names vary slightly between Veeam versions (Veeam Agent for Windows vs Veeam Backup &
> Replication). The steps below follow the common layout; check against the Veeam help for your version.

## 1. Choose and fix the data folder

On the computer that runs the app, pick a stable location, for example `C:\AttachmentTrackerData`,
and tell the app to use it (either way works):

* Set the environment variable `ATTACHMENT_TRACKER_HOME=C:\AttachmentTrackerData`, **or**
* Start the app with `AttachmentTracker.exe --home C:\AttachmentTrackerData`.

Folder layout (inside it):

| Folder / file | What it holds |
|---|---|
| `db\tracker.db` | students, submissions, streak data |
| `uploads\logbooks\`, `uploads\faces\` | the student photos |
| `exports\` | finished social media cards |
| `backup_staging\` | consistent snapshot, `completion.csv`, graph PNGs, `manifest.json` (written by the app) |

## 2. Create the Veeam job (file-level backup)

1. In Veeam Agent for Windows (or your Veeam Backup & Replication file/agent job), create a new
   backup job in **File level backup** mode.
2. Include the data folder (`C:\AttachmentTrackerData`) only. Pick your repository (external disk,
   NAS, or Veeam repository), schedule (for example nightly, plus after the weekly Friday streak day), and retention.
3. Open the job's **Advanced** settings, go to **Scripts**, and set **`veeam\pre-job.bat`**
   as the pre-job script. Edit the two paths at the top of the .bat first.
   The script runs `AttachmentTracker.exe --prepare-backup`, which writes `backup_staging\`
   just before Veeam reads the folder. If the script fails it returns exit code 1.
4. Run the job once and confirm it finishes.

Why the pre-job step? The live SQLite database can be changing while Veeam reads it. The snapshot is
a consistent copy made with SQLite's online-backup API, so even if the live file was caught mid-write
you still have a clean `backup_staging\tracker_snapshot.db`.

## 3. Restore

**Whole data folder (or lost computer):**
1. Install the app on the new/repaired computer.
2. In Veeam choose **Restore > Files and folders**, pick the restore point, and restore the data
   folder to the original location (or any new location).
3. Point the app at it (`--home <folder>` or the environment variable) and run
   `AttachmentTracker.exe --verify` (or open **Backup & Restore > Verify data** in the app).
   File paths in the database are relative, so restoring to a different drive or folder works.

**Only the database is damaged:** open **Backup & Restore > Restore database from snapshot** in the app.
The current database is kept next to it as `tracker.db.pre_restore_<time>.bak`. Photos are untouched.

**A single photo was deleted:** restore just that file from Veeam with *Restore > Files and folders*,
then run **Verify data**.

## 4. What "Verify data" checks

* the database passes SQLite's integrity check,
* every photo recorded in the database exists and still matches its stored SHA-256,
* every file listed in `manifest.json` is present and unchanged.

Files added after the last snapshot are reported as a note, not an error.

## 5. Good practice

* Do a **test restore** to another folder at least once per term and run `--verify` on it.
* Keep a second copy (another Veeam repository or a copy job) off the same computer.
* The app also refreshes `backup_staging\` automatically when it is closed, as a safety net.
