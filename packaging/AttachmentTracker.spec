# PyInstaller spec. Run from the project folder:  pyinstaller packaging/AttachmentTracker.spec --noconfirm
# Produces dist/AttachmentTracker/ (AttachmentTracker.exe + support files). The installer and the portable zip are made from it.
from pathlib import Path

root = Path(SPECPATH).parent
icon = root / "attachment_tracker" / "assets" / "icon.ico"

a = Analysis(
    [str(root / "run_app.py")],
    pathex=[str(root)],
    datas=[(str(root / "attachment_tracker" / "assets"), "attachment_tracker/assets")],
    hiddenimports=["PIL._tkinter_finder"],
    # the optional skills lab and its heavy packages are not part of the desktop app
    excludes=["cv2", "sklearn", "scipy", "torch", "transformers", "docx", "lxml", "pandas", "matplotlib", "skills_lab"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AttachmentTracker",
    console=False,                      # no black console window
    icon=str(icon) if icon.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AttachmentTracker")
