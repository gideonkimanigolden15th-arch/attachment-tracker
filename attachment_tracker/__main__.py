"""Command line entry point.

    python -m attachment_tracker                  open the desktop app
    python -m attachment_tracker --prepare-backup build backup_staging/ (for the Veeam pre-job script)
    python -m attachment_tracker --verify         check the data (run after a Veeam restore)
    python -m attachment_tracker --home D:\\Data   use another data folder

Exit codes: 0 = success, 1 = problems found / failure (so Veeam or Task Scheduler can flag it).
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="attachment_tracker", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", help="data folder (default: Documents/AttachmentTracker or $ATTACHMENT_TRACKER_HOME)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--prepare-backup", action="store_true", help="write a consistent snapshot for Veeam, then exit")
    g.add_argument("--verify", action="store_true", help="verify database and photos against the manifest, then exit")
    args = ap.parse_args(argv)

    from . import backup
    from .config import get_paths

    paths = get_paths(args.home)

    if args.prepare_backup:
        try:
            info = backup.prepare_snapshot(paths)
        except Exception as exc:  # noqa: BLE001 - report any failure to the scheduler
            print(f"Backup preparation FAILED: {exc}", file=sys.stderr)
            return 1
        print(f"Snapshot ready in {paths.staging}: {info['students']} students, "
              f"{info['submissions']} submissions, {info['file_count']} files.")
        return 0

    if args.verify:
        rep = backup.verify(paths)
        print(rep.summary())
        return 0 if rep.ok else 1

    from .ui import run_app
    run_app(paths)
    return 0


if __name__ == "__main__":
    sys.exit(main())
