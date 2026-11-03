"""Paths and global settings.

Everything the app owns lives under ONE data folder so that a single Veeam
file-level job (or a copy to a flash drive) captures the lot:

    <data root>/
        db/tracker.db              SQLite database (rollback-journal mode = one file)
        uploads/logbooks/<reg>/    logbook photos
        uploads/faces/<reg>/       face photos
        exports/                   finished social media cards
        backup_staging/            consistent snapshot + manifest + graphs (written by the app)

Default: ~/Documents/AttachmentTracker. Override with the environment variable
ATTACHMENT_TRACKER_HOME or the --home command line option.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "AttachmentTracker"

# Let students see the cohort overview table in the Progress tab.
# Set to False if students should only ever see their own progress.
SHOW_COHORT = True

# Uploaded photos are auto-rotated and shrunk so the longest side is at most this many pixels.
MAX_IMAGE_SIDE = 2400
# Smallest accepted photos. Face photos only need to be a sensible portrait; logbook photos need
# enough pixels for the table lines to be seen. Real phone photos are 3000+ px, so these only
# catch thumbnails, screenshots of thumbnails and tiny web images.
MIN_FACE_SHORT_SIDE = 100
MIN_LOGBOOK_LONG_SIDE = 320


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def db(self) -> Path:
        return self.root / "db" / "tracker.db"

    @property
    def logbooks(self) -> Path:
        return self.root / "uploads" / "logbooks"

    @property
    def faces(self) -> Path:
        return self.root / "uploads" / "faces"

    @property
    def uploads(self) -> Path:
        return self.root / "uploads"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def staging(self) -> Path:
        return self.root / "backup_staging"


def get_paths(home: str | os.PathLike | None = None) -> Paths:
    """Resolve (and create) the data folders."""
    chosen = home or os.environ.get("ATTACHMENT_TRACKER_HOME")
    root = Path(chosen) if chosen else Path.home() / "Documents" / APP_NAME
    p = Paths(root.expanduser().resolve())
    for d in (p.db.parent, p.logbooks, p.faces, p.exports, p.staging):
        d.mkdir(parents=True, exist_ok=True)
    return p
