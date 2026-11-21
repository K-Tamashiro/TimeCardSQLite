; Inno Setup script for Personal TimeCard for Free Lance
; Requires PyInstaller output in ..\dist\PersonalTimeCard\

#define MyAppName "Personal TimeCard for Free Lance"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "シマウマソフト Tamayan"
#define MyAppExeName "PersonalTimeCard.exe"

[Setup]
AppId={{8E9D5C31-7A2F-4B94-9A1E-42B91D0F7C11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PersonalTimeCard
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=out
OutputBaseFilename=PersonalTimeCard-Setup-{#MyAppVersion}
SetupIconFile=..\timecard\favicon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにアイコンを作成する"; GroupDescription: "追加タスク:"

[Files]
Source: "..\dist\PersonalTimeCard\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\アンインストール"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppName} を今すぐ起動する"; Flags: nowait postinstall skipifsilent
