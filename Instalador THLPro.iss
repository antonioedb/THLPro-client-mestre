; Instalador THLPro Client - Inno Setup 6
#define MyAppName "THLPro Client"
#define MyAppVersion "0.4.0"
#define MyAppExeName "THLProClient.exe"

[Setup]
AppId={{A7229D53-1D5F-4EB6-B652-13F66EA83A4A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\THLPro Client
DefaultGroupName=THLPro
OutputBaseFilename=Instalador-THLPro-Client
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\THLPro Client"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\THLPro Client"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Criar ícone na área de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Executar THLPro Client"; Flags: nowait postinstall skipifsilent
