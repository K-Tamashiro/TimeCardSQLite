; Inno Setup script for Personal TimeCard for Free Lance
; Requires PyInstaller output in ..\dist\PersonalTimeCard\

#define MyAppName "Personal TimeCard for Free Lance"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "シマウマソフト Tamayan"
#define MyAppURL "https://note.com/thinker_tamayan"
#define MyAppSupportURL "https://github.com/K-Tamashiro/TimeCardSQLite"
#define MyAppExeName "PersonalTimeCard.exe"

[Setup]
AppId={{8E9D5C31-7A2F-4B94-9A1E-42B91D0F7C11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppSupportURL}
AppUpdatesURL={#MyAppSupportURL}/releases
DefaultDirName={autopf}\PersonalTimeCard
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir=..\Release
OutputBaseFilename=PersonalTimeCard-Setup-{#MyAppVersion}
SetupIconFile=..\timecard\favicon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
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
Name: "{group}\はじめに (README)"; Filename: "{app}\README.txt"
Name: "{group}\ライセンス (AGPL-3.0)"; Filename: "{app}\LICENSE.txt"
Name: "{group}\アンインストール"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppName} を今すぐ起動する"; Flags: nowait postinstall skipifsilent
