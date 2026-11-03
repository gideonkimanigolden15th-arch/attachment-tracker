@echo off
REM Builds a single-file Windows app: dist\AttachmentTracker.exe
REM Needs Python 3.10+ installed (tick "Add python.exe to PATH" in the installer).
py -m pip install -r requirements.txt pyinstaller
py -m PyInstaller --noconsole --onefile --name AttachmentTracker run_app.py
echo.
echo Done. Copy dist\AttachmentTracker.exe to C:\AttachmentTracker\ and edit veeam\pre-job.bat to match.
echo Note: --noconsole hides the window, so --prepare-backup / --verify print nothing but still set the exit code.
echo For visible output when testing, run from source:  py -m attachment_tracker --verify
pause
