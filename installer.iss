#define MyAppName "dy-download"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "ximishan"
#define MyAppExeName "dy-download.exe"

[Setup]
AppId={{8D4FC23B-6D09-4C2D-9B3F-8B7B6D8C31F4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\dy-download
DefaultGroupName=dy-download
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=dy-download-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "dist\dy-download\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\dy-download"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\dy-download"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 dy-download"; Flags: nowait postinstall skipifsilent
