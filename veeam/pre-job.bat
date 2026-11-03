@echo off
REM ---------------------------------------------------------------------------
REM Veeam PRE-JOB script for Attachment Tracker.
REM Builds a consistent snapshot (database copy, completion CSV, graphs, manifest)
REM in <data folder>\backup_staging BEFORE Veeam reads the data folder.
REM
REM 1. Edit the two lines below to match this computer.
REM 2. In the Veeam job: Advanced > Scripts > run this script before the job.
REM    A non-zero exit code means the snapshot failed.
REM ---------------------------------------------------------------------------

REM Option A (installed .exe built with build_exe.bat):
set "APP=C:\AttachmentTracker\AttachmentTracker.exe"

REM Option B (running from Python instead): comment out Option A and use this
REM set "APP=python -m attachment_tracker"

REM Leave empty to use the default (Documents\AttachmentTracker of the user running the job).
REM Because Veeam may run the script as another account, set it explicitly:
set "HOME_DIR=C:\AttachmentTrackerData"

if "%HOME_DIR%"=="" (
    %APP% --prepare-backup
) else (
    %APP% --home "%HOME_DIR%" --prepare-backup
)
exit /b %ERRORLEVEL%
