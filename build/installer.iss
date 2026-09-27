; Inno Setup script for Nolima Accounting.
; Built by build\build_windows.bat (or the GitHub workflow), which passes /DAppVersion=x.y.z
#ifndef AppVersion
  #define AppVersion "1.3.0"
#endif
#define AppName "Nolima Accounting"
#define Publisher "Nolima Tech Consultants"
#define ExeName "NolimaAccounting.exe"

[Setup]
AppId={{6F1E2B7A-4C1D-4E7B-9A3C-5B2D8E1F0A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#Publisher}
AppPublisherURL=https://nolima.mw
AppSupportPhone=099 025 2341
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\Nolima Accounting
DefaultGroupName=Nolima Accounting
DisableProgramGroupPage=yes
OutputDir=..\Output
OutputBaseFilename=NolimaAccounting-Setup-{#AppVersion}
SetupIconFile=..\assets\nolima.ico
UninstallDisplayIcon={app}\{#ExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; installing a newer version over an older one closes the running program first
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\NolimaAccounting\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Dirs]
; one shared data folder so every Windows user on this PC sees the same books and licence
Name: "{commonappdata}\NolimaAccounting"; Permissions: users-modify
Name: "{commonappdata}\NolimaAccounting\companies"; Permissions: users-modify
Name: "{commonappdata}\NolimaAccounting\backups"; Permissions: users-modify
Name: "{commonappdata}\NolimaAccounting\exports"; Permissions: users-modify

[Icons]
Name: "{group}\Nolima Accounting"; Filename: "{app}\{#ExeName}"
Name: "{group}\Nolima Accounting data folder"; Filename: "{commonappdata}\NolimaAccounting"
Name: "{group}\Uninstall Nolima Accounting"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Nolima Accounting"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#ExeName}"; Description: "Start Nolima Accounting"; Flags: nowait postinstall skipifsilent
; after an automatic (silent) update, open the program again
Filename: "{app}\{#ExeName}"; Flags: nowait skipifnotsilent

[UninstallDelete]
; program files only - the company data, licence and backups in ProgramData are always kept
Type: filesandordirs; Name: "{app}"

[Messages]
FinishedLabel=Nolima Accounting is installed.%n%nOn first start it shows this computer's Machine ID. Send it to Nolima Tech Consultants (099 025 2341) to receive the licence key, or start the 14-day trial.
