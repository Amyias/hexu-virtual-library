; Windows setup program for the packaged library (Inno Setup 6). Built by tools/build-setup.mjs,
; which passes every path through the environment: the project lives under a Chinese path and
; this shell re-encodes non-ASCII command-line arguments.
;
; Installs per user under %LOCALAPPDATA%\Programs, never Program Files. The automatic updater
; swaps the whole install folder from its parent directory (tools/update-helper.ps1); under
; Program Files that would need administrator rights on every update.

#define AppName "和序图书馆"
#define AppVersion GetEnv("HEXU_SETUP_VERSION")
#define SourceDir GetEnv("HEXU_SETUP_SOURCE")
#define OutputDir GetEnv("HEXU_SETUP_OUTPUT")
#if AppVersion == "" || SourceDir == "" || OutputDir == ""
  #error 缺少 HEXU_SETUP_VERSION / HEXU_SETUP_SOURCE / HEXU_SETUP_OUTPUT，请用 node tools/build-setup.mjs 构建
#endif

[Setup]
; Fixed for the life of the product: Windows recognises upgrades and the uninstall entry by it.
AppId={{6D2B5C4E-8A71-4F0B-9C3E-2A5F7D1E4B60}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=和序图书馆
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} 安装程序
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
DefaultGroupName={#AppName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=hexu-library-{#AppVersion}-setup
SetupIconFile={#SourceDir}\_internal\public\favicon.ico
UninstallDisplayIcon={app}\{#AppName}.exe
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2
; Not solid, so the speech models below can be stored rather than spend minutes failing to shrink.
SolidCompression=no
; A running copy is closed through Restart Manager before its files are replaced.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chs"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "\_internal\models,\%SystemDrive%"; Flags: recursesubdirs createallsubdirs ignoreversion
; ONNX weights are already dense; storing them makes the build fast and the setup barely larger.
Source: "{#SourceDir}\_internal\models\*"; DestDir: "{app}\_internal\models"; Flags: recursesubdirs createallsubdirs ignoreversion nocompression

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; After an automatic update the folder holds files the setup never wrote, so the uninstall log
; does not know them. Remove the program's own tree by name; the reader's books and settings
; live in %APPDATA%\hexu-library and are deliberately left alone.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\{#AppName}.exe"
Type: files; Name: "{app}\使用说明.txt"
Type: filesandordirs; Name: "{app}\%SystemDrive%"
Type: dirifempty; Name: "{app}"
