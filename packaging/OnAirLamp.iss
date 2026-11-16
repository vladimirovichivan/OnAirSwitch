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
DisableDirPage=yes
UsePreviousAppDir=no
PrivilegesRequired=lowest
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
Name: "{group}\OnAir Lamp"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\start.vbs"""; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"
Name: "{group}\Настройка OnAir Lamp"; Filename: "{app}\setup.cmd"; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"
Name: "{group}\Проверка розетки"; Filename: "{app}\verify.cmd"; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"
Name: "{group}\Отчёт для поддержки"; Filename: "{app}\report.cmd"; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"
Name: "{group}\Если не работает"; Filename: "{app}\SUPPORT.md"
Name: "{autodesktop}\OnAir Lamp"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\start.vbs"""; IconFilename: "{app}\onair.ico"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "OnAirLamp"; ValueData: "wscript.exe ""{app}\start.vbs"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\start.vbs"""; Description: "Запустить OnAir Lamp"; Flags: postinstall nowait skipifsilent

[Code]
{ При удалении спрашиваем про настройки подключения к розетке. Тихая
  деинсталляция их сохраняет; /DELETEAPPSETTINGS удаляет без вопроса. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  SettingsFile: String;
  CmdTail: String;
  Answer: Integer;
begin
  if CurUninstallStep <> usUninstall then
    Exit;

  SettingsFile := ExpandConstant('{app}\app\secrets\tuya_plug.json');
  if not FileExists(SettingsFile) then
    Exit;

  CmdTail := Lowercase(GetCmdTail);
  if Pos('/deleteappsettings', CmdTail) > 0 then
  begin
    DeleteFile(SettingsFile);
    RemoveDir(ExpandConstant('{app}\app\secrets'));
    Exit;
  end;

  if UninstallSilent then
    Exit;

  Answer := MsgBox(
    'Удалить сохранённые настройки подключения к розетке?' + #13#10 + #13#10 +
    'Они позволяют после повторной установки продолжить работу без новой ' +
    'настройки розетки.' + #13#10 +
    'Журналы и остальные данные останутся на месте.' + #13#10 + #13#10 +
    'Если удалить, при следующей установке розетку нужно будет настроить заново.',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2);
  if Answer = IDYES then
  begin
    DeleteFile(SettingsFile);
    RemoveDir(ExpandConstant('{app}\app\secrets'));
  end;
end;
