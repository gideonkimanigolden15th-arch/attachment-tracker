; Inno Setup script: makes AttachmentTracker-Setup.exe (Start-menu + optional desktop shortcut, uninstaller).
; Build:  iscc /DAppVersion=1.5.0 packaging\installer.iss     (run after PyInstaller has produced dist\AttachmentTracker)
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F3B1C52-8D4E-4A57-9B0A-2E7C41D5A9F1}
AppName=Attachment Tracker
AppVersion={#AppVersion}
AppPublisher=Attachment Tracker
DefaultDirName={autopf}\Attachment Tracker
DefaultGroupName=Attachment Tracker
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=AttachmentTracker-Setup
SetupIconFile=..\attachment_tracker\assets\icon.ico
UninstallDisplayIcon={app}\AttachmentTracker.exe
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\AttachmentTracker\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Attachment Tracker"; Filename: "{app}\AttachmentTracker.exe"
Name: "{autodesktop}\Attachment Tracker"; Filename: "{app}\AttachmentTracker.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AttachmentTracker.exe"; Description: "Start Attachment Tracker"; Flags: nowait postinstall skipifsilent

; Student data lives in Documents\AttachmentTracker and is NOT touched by uninstalling.
