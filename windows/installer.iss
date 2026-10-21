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
; Let phones and tablets reach InnKeeper without Windows asking (only for installs with admin rights;
; otherwise Windows asks once on first start). Only devices on the same local network or a Tailscale
; network are allowed, on any network type, because Windows often marks a new Wi-Fi as "Public".
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""InnKeeper"""; Flags: runhidden; Check: IsAdminInstallMode; StatusMsg: "Firewall..."
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""InnKeeper"" dir=in action=allow program=""{app}\InnKeeper.exe"" enable=yes profile=any protocol=TCP remoteip=localsubnet,100.64.0.0/10 description=""InnKeeper: phones and tablets on this network"""; Flags: runhidden; Check: IsAdminInstallMode; StatusMsg: "Firewall..."
Filename: "{app}\InnKeeper.exe"; Description: "{cm:LaunchProgram,InnKeeper}"; Flags: nowait postinstall skipifsilent
; An update started from inside InnKeeper runs silently: open InnKeeper again when it is done.
Filename: "{app}\InnKeeper.exe"; Flags: nowait runasoriginaluser; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""InnKeeper"""; Flags: runhidden; RunOnceId: "DelFirewallRule"; Check: IsAdminInstallMode

; Data in %LOCALAPPDATA%\InnKeeper (database and backups) is deliberately kept on uninstall.
