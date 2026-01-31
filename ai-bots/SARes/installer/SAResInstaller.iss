#pragma warntextmode off

#define MyAppName "SARes Control Tower"
#define MyAppVersion "1.0.0"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={pf}\SARes
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=.
OutputBaseFilename=SARes-Installer
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
[Files]
Source: "..\release\publish\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SARes Control Tower"; Filename: "{app}\SARes.exe"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\SARes.exe"; Description: "Launch SARes"; Flags: nowait postinstall skipifsilent
