; Установщик OnAir Lamp (per-user, без прав администратора).
;
; Собирается из packaging\build.ps1:
;   iscc /DAppVersion=1.0.0 /DStageDir=D:\...\build\portable\OnAirLamp-1.0.0-win64 OnAirLamp.iss
;
; Раскладка повторяет портативную папку; app\data и app\secrets при удалении
; сохраняются, потому что установщик о них не знает.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#ifndef StageDir
  #define StageDir "..\build\portable\OnAirLamp-" + AppVersion + "-win64"
#endif

#define AppName "OnAir Lamp"
#define AppPublisher "OnAir Lamp"
#define AppId "{{6F1B6C2E-7A55-4B7E-9F31-2D6A4C8E0B11}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVerName={#AppName} {#AppVersion}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\OnAirLamp
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\build
OutputBaseFilename=OnAirLamp-Setup-{#AppVersion}
SetupIconFile=..\build\onair.ico
UninstallDisplayIcon={app}\onair.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AllowNoIcons=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "autostart"; Description: "Запускать OnAir Lamp при входе в Windows"; GroupDescription: "Автозапуск:"
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\onair.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\OnAir Lamp"; Filename: "{app}\start.vbs"; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"
Name: "{autoprograms}\Настройка OnAir Lamp"; Filename: "{app}\setup.cmd"; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"
Name: "{autoprograms}\Проверка розетки"; Filename: "{app}\verify.cmd"; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"
Name: "{autoprograms}\Отчёт для поддержки"; Filename: "{app}\report.cmd"; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"
Name: "{autoprograms}\Если не работает"; Filename: "{app}\SUPPORT.md"
Name: "{autodesktop}\OnAir Lamp"; Filename: "{app}\start.vbs"; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "OnAirLamp"; ValueData: "wscript.exe ""{app}\start.vbs"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\start.vbs"; Description: "Запустить OnAir Lamp"; Flags: postinstall nowait skipifsilent
