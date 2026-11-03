"""Double-click / PyInstaller entry point."""
import os
import sys


def _attach_console() -> None:
    """The packaged app has no console window. When it is started from a terminal (e.g. the Veeam pre-job script with
    --verify), connect it to that terminal so the messages are visible. Harmless when started by double-click."""
    if sys.platform.startswith("win") and getattr(sys, "frozen", False) and len(sys.argv) > 1:
        try:
            import ctypes
            if ctypes.windll.kernel32.AttachConsole(-1):
                sys.stdout = open("CONOUT$", "w", buffering=1)
                sys.stderr = open("CONOUT$", "w", buffering=1)
        except Exception:  # noqa: BLE001
            pass


_attach_console()

from attachment_tracker.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
