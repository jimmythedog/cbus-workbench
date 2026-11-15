; Inno Setup installer for the PyInstaller onedir bundle in "dist\CBUS Workbench".
; Build from the repo root: iscc /DAppVersion=<version> packaging\windows\cbus-workbench.iss

#ifndef AppVersion
  #error Define AppVersion, e.g. iscc /DAppVersion=0.1.0a1
#endif

[Setup]
; Fixed AppId so later versions upgrade this installation in place. Never change it.
AppId={{E01E2E68-BB0C-4AB0-9531-0959994ECFAD}
AppName=CBUS Workbench
AppVersion={#AppVersion}
AppPublisher=CBUS Workbench
AppPublisherURL=https://github.com/jimmythedog/cbus-workbench
SourceDir=..\..
OutputDir=dist
OutputBaseFilename=cbus-workbench-{#AppVersion}-windows-x64-setup
SetupIconFile=assets\icons\cbus-workbench.ico
UninstallDisplayIcon={app}\CBUS Workbench.exe
DefaultDirName={autopf}\CBUS Workbench
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
Compression=lzma2
SolidCompression=yes

[InstallDelete]
; Remove the previous version's bundled libraries so an upgrade cannot mix them.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\CBUS Workbench\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\CBUS Workbench"; Filename: "{app}\CBUS Workbench.exe"

[Run]
Filename: "{app}\CBUS Workbench.exe"; Description: "Launch CBUS Workbench"; Flags: nowait postinstall skipifsilent
