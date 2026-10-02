; Inno Setup script for the InnKeeper Windows installer.
; Built by .github/workflows/windows.yml:  iscc /DAppVersion=2.1.0 windows\installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1A6C2E-6B7B-4C4D-9C7B-1D4E2A9B8F11}
AppName=InnKeeper
AppVersion={#AppVersion}
AppVerName=InnKeeper {#AppVersion}
AppPublisher=UncleKraken
AppPublisherURL=https://github.com/UncleKraken/InnKeeper
AppUpdatesURL=https://github.com/UncleKraken/InnKeeper/releases
DefaultDirName={autopf}\InnKeeper
DefaultGroupName=InnKeeper
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=InnKeeper-Setup-{#AppVersion}
SetupIconFile=innkeeper.ico
UninstallDisplayIcon={app}\InnKeeper.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "Start InnKeeper when Windows starts / Ndize me Windows"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\InnKeeper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\InnKeeper"; Filename: "{app}\InnKeeper.exe"
Name: "{group}\{cm:UninstallProgram,InnKeeper}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\InnKeeper"; Filename: "{app}\InnKeeper.exe"; Tasks: desktopicon
Name: "{userstartup}\InnKeeper"; Filename: "{app}\InnKeeper.exe"; Tasks: autostart

[Run]
Filename: "{app}\InnKeeper.exe"; Description: "{cm:LaunchProgram,InnKeeper}"; Flags: nowait postinstall skipifsilent

; Data in %LOCALAPPDATA%\InnKeeper (database and backups) is deliberately kept on uninstall.
